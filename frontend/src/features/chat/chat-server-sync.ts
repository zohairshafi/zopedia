import { authFetch, getAuthToken as getAuthTokenSync, getPermissions } from "@/features/auth";
import { db } from "./db";
import type { MessageRecord, ThreadRecord } from "./types";

function canSyncToServer(): boolean {
  return getPermissions().can_save_chat_history;
}

const DEBOUNCE_MS = 2000;
const MAX_MESSAGE_CONTENT_BYTES = 40_000; // chunk messages exceeding ~40KB serialized
const debounceTimers = new Map<string, ReturnType<typeof setTimeout>>();

// In-memory set of message IDs already confirmed synced to the server.
// Survives within a session; on page reload it resets, but the server
// uses INSERT OR IGNORE so re-sending is harmless.
const syncedMessageIds = new Set<string>();

// Thread IDs the user has deleted this session. The server list-sync
// (which can fire on visibilitychange) skips re-adding these, so a slow
// or failed server-side delete can't make an empty thread reappear in
// the sidebar. Cleared on reload; the server is the source of truth
// across sessions.
const recentlyDeletedThreadIds = new Set<string>();

function flushPendingSaves() {
  for (const [threadId, timer] of debounceTimers) {
    clearTimeout(timer);
    debounceTimers.delete(threadId);
    void syncThreadToServer(threadId);
  }
}

// ── Page-unload safety ─────────────────────────────────────────────────
// Large payloads (≥60KB) skip keepalive because browsers cap keepalive
// bodies at ~64KB.  Without keepalive, a normal fetch is aborted on unload
// and the save is dropped.  We track the most recent keepalive-skipped sync
// request and re-fire it as a blocking synchronous XHR on pagehide so it
// survives tab close / navigation.

let _lastKeepaliveSkipped: { url: string; bodyJson: string } | null = null;

function _noteKeepaliveSkipped(url: string, bodyJson: string): void {
  _lastKeepaliveSkipped = { url, bodyJson };
}

function _installUnloadHandlers(): void {
  if (typeof window === "undefined") return;

  window.addEventListener("beforeunload", () => {
    // Fire pending debounced syncs immediately (they use keepalive=true for
    // payloads under 60KB, so they survive unload) then cancel the timers.
    flushPendingSaves();
  });

  window.addEventListener("pagehide", () => {
    // pagehide fires reliably on tab close / navigation.  A fetch with
    // keepalive=false is aborted here, so retry the last large payload as
    // a blocking synchronous XHR (the only transport that survives unload).
    const req = _lastKeepaliveSkipped;
    if (!req) return;
    _lastKeepaliveSkipped = null;
    try {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", req.url, false); // synchronous
      xhr.setRequestHeader("Content-Type", "application/json");
      // authFetch adds this automatically; the sync XHR bypasses it, so
      // add the bearer token manually (reads localStorage synchronously).
      const token = getAuthTokenSync();
      if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      xhr.send(req.bodyJson);
    } catch {
      // Best-effort — if the browser kills the XHR, we can't do more.
    }
  });
}

// Install once at module load
_installUnloadHandlers();

function chunkLargeContent(content: unknown): unknown[] {
  // If content is a string and exceeds the size threshold, split it at
  // paragraph boundaries so each chunk stays under the byte limit.
  if (typeof content !== "string") {
    // Non-string content (arrays of content blocks) can't be chunked.
    // Log a warning if it's unusually large.
    const jsonSize = new TextEncoder().encode(JSON.stringify(content)).length;
    if (jsonSize > MAX_MESSAGE_CONTENT_BYTES) {
      console.warn("[sync] non-string content exceeds size limit, sending as-is", jsonSize);
    }
    return [content];
  }
  const jsonSize = new TextEncoder().encode(JSON.stringify(content)).length;
  if (jsonSize <= MAX_MESSAGE_CONTENT_BYTES) return [content];

  // Split at double-newline (paragraph) boundaries, using byte-aware slicing
  const encoder = new TextEncoder();
  const maxChunkBytes = Math.floor(MAX_MESSAGE_CONTENT_BYTES / 2);
  const parts: string[] = [];
  let remaining = content;
  while (remaining.length > 0) {
    // Start with a character-based estimate, then shrink to fit byte limit
    let chunk = remaining.slice(0, Math.floor(maxChunkBytes * 0.75));
    while (encoder.encode(chunk).length > maxChunkBytes && chunk.length > 1) {
      chunk = chunk.slice(0, Math.floor(chunk.length * 0.9));
    }
    // Back up to the last paragraph boundary for clean splits
    const lastBreak = chunk.lastIndexOf("\n\n");
    if (lastBreak > chunk.length / 2) {
      chunk = chunk.slice(0, lastBreak);
    }
    parts.push(chunk.trim());
    remaining = remaining.slice(chunk.length).trimStart();
  }
  console.log("[sync] chunked large message into", parts.length, "parts (original bytes:", jsonSize, ")");
  return parts;
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushPendingSaves();
  });
}

async function getAuthToken(): Promise<string | null> {
  try {
    const { getAuthToken: getToken } = await import("@/features/auth/session");
    return getToken();
  } catch {
    return null;
  }
}

// ── Server API calls ─────────────────────────────────────────────────

async function fetchServerThreads(): Promise<{ threads: Array<{ id: string; title: string; created_at: string; updated_at: string; message_count: number }>; subject: string }> {
  try {
    const res = await authFetch("/api/chat/threads", { cache: "no-store" });
    if (!res.ok) {
      console.log("[sync] fetchServerThreads: not ok", { status: res.status });
      return { threads: [], subject: "" };
    }
    const data = await res.json();
    console.log("[sync] fetchServerThreads: got threads", { count: data.threads?.length ?? 0, subject: data.subject ?? "" });
    return { threads: data.threads ?? [], subject: data.subject ?? "" };
  } catch (err) {
    console.log("[sync] fetchServerThreads: error", err);
    return { threads: [], subject: "" };
  }
}

async function fetchServerThread(threadId: string): Promise<{ thread: any; messages: any[] } | null> {
  try {
    const res = await authFetch(`/api/chat/threads/${encodeURIComponent(threadId)}`, { cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function saveThreadToServer(
  threadId: string,
  title: string,
  messages: Array<{ id: string; role: string; content: any; reasoning_content?: string; parent_id?: string | null; created_at?: string }>,
  createdAt?: number,
): Promise<boolean> {
  if (!canSyncToServer()) return false;
  try {
    const body: Record<string, unknown> = { thread_id: threadId, title, messages };
    if (createdAt) body.created_at = new Date(createdAt).toISOString();
    const bodyJson = JSON.stringify(body);
    // keepalive has a ~64KB body limit in browsers.  If the payload
    // exceeds ~60KB we must skip keepalive, otherwise Chrome throws
    // TypeError and the save fails silently — only the first message
    // (from an earlier, smaller sync) makes it to the server.
    const useKeepalive = new TextEncoder().encode(bodyJson).length < 60_000;
    const res = await authFetch("/api/chat/threads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: bodyJson,
      keepalive: useKeepalive,
    });
    // Track this request so the pagehide handler can retry it as a
    // blocking XHR if keepalive was skipped (large payloads).
    if (!useKeepalive) {
      _noteKeepaliveSkipped("/api/chat/threads", bodyJson);
    }
    console.log("[sync] saveThreadToServer:", res.status, { threadId, msgCount: messages.length, keepalive: useKeepalive });
    return res.ok;
  } catch (err) {
    console.error("[sync] saveThreadToServer failed:", err);
    return false;
  }
}

async function appendMessagesToServer(
  threadId: string,
  title: string | undefined,
  messages: Array<{ id: string; role: string; content: any; reasoning_content?: string; parent_id?: string | null; created_at?: string }>,
): Promise<string[]> {
  // Append only these messages to the server. Returns the IDs that were
  // actually confirmed inserted by the server (not just sent).
  if (messages.length === 0) return [];
  try {
    const bodyJson = JSON.stringify({ thread_id: threadId, title, messages });
    const useKeepalive = new TextEncoder().encode(bodyJson).length < 60_000;
    const url = `/api/chat/threads/${encodeURIComponent(threadId)}/messages`;
    if (!useKeepalive) {
      _noteKeepaliveSkipped(url, bodyJson);
    }
    const res = await authFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: bodyJson,
      keepalive: useKeepalive,
    });
    console.log("[sync] appendMessagesToServer:", res.status, { threadId, msgCount: messages.length });
    if (!res.ok) return [];
    const data = await res.json().catch(() => null);
    // Server now returns the actual inserted_ids — trust that, not our send list.
    return Array.isArray(data?.inserted_ids) ? data.inserted_ids : [];
  } catch (err) {
    console.error("[sync] appendMessagesToServer failed:", err);
    return [];
  }
}

async function syncThreadToServer(threadId: string): Promise<void> {
  if (!canSyncToServer()) return;
  // Incrementally sync a thread: send only unsynced messages via append.
  const thread = await db.threads.get(threadId);
  if (!thread) return;

  const msgCount = await db.messages.count();
  const allMsgs: MessageRecord[] = msgCount === 0
    ? []
    : await db.messages.where("threadId").equals(threadId).sortBy("createdAt");

  if (allMsgs.length === 0) return;

  // Filter to messages not yet synced
  const unsynced = allMsgs.filter((m) => !syncedMessageIds.has(m.id));
  if (unsynced.length === 0) {
    console.log("[sync] all messages already synced for", threadId);
    return;
  }

  // Prepare messages, chunking oversized content.
  // Also build a map from send-ID → original message so we can correctly
  // track which original messages were confirmed after the server responds.
  type Msg = {
    id: string;
    role: string;
    content: unknown;
    reasoning_content?: string;
    parent_id?: string | null;
    created_at?: string;
  };
  const toSend: Msg[] = [];
  const sendIdToOriginal = new Map<string, string>(); // send-id → original message id
  const chunksPerOriginal = new Map<string, number>(); // original id → expected chunk count
  for (const m of unsynced) {
    const chunks = chunkLargeContent(m.content);
    chunksPerOriginal.set(m.id, chunks.length);
    if (chunks.length === 1) {
      toSend.push({
        id: m.id,
        role: m.role,
        content: m.content,
        reasoning_content: (m.metadata as any)?.reasoning_content,
        parent_id: m.parentId,
        created_at: new Date(m.createdAt).toISOString(),
      });
      sendIdToOriginal.set(m.id, m.id);
    } else {
      for (let i = 0; i < chunks.length; i++) {
        const chunkId = `${m.id}-chunk-${i}`;
        toSend.push({
          id: chunkId,
          role: m.role,
          content: chunks[i],
          reasoning_content: (m.metadata as any)?.reasoning_content,
          parent_id: i === 0 ? m.parentId : `${m.id}-chunk-${i - 1}`,
          created_at: new Date(m.createdAt + i).toISOString(),
        });
        sendIdToOriginal.set(chunkId, m.id);
      }
    }
  }

  const isFirstSync = allMsgs.every((m) => !syncedMessageIds.has(m.id));

  let confirmedSendIds: string[] = [];
  if (isFirstSync) {
    // On a fresh session (e.g. another browser) we don't know which messages
    // are already on the server.  Fetch the server's existing message IDs and
    // append ONLY what's missing — never DELETE.  Using the full-upsert path
    // here would wipe messages appended by another browser since this one last
    // synced (real data loss).  saveThreadToServer/upsert_thread is now
    // reserved for the one-time local→server migration (maybeMigrateLocalToServer).
    const serverResult = await fetchServerThread(threadId);
    const serverIds = new Set<string>(
      (serverResult?.messages ?? []).map((m: { id?: string }) => m.id ?? ""),
    );
    for (const id of serverIds) syncedMessageIds.add(id);
    const missing = toSend.filter((m) => !serverIds.has(m.id));
    if (missing.length > 0) {
      confirmedSendIds = await appendMessagesToServer(threadId, thread.title, missing);
    } else {
      confirmedSendIds = [];
    }
  } else {
    confirmedSendIds = await appendMessagesToServer(threadId, thread.title, toSend);
  }

  // Only mark a message synced if ALL its chunks were confirmed by the server.
  const confirmedByOriginal = new Map<string, number>(); // original id → confirmed chunk count
  for (const sendId of confirmedSendIds) {
    const origId = sendIdToOriginal.get(sendId);
    if (origId) confirmedByOriginal.set(origId, (confirmedByOriginal.get(origId) ?? 0) + 1);
  }
  for (const m of unsynced) {
    const expected = chunksPerOriginal.get(m.id) ?? 1;
    const confirmed = confirmedByOriginal.get(m.id) ?? 0;
    if (confirmed >= expected) {
      syncedMessageIds.add(m.id);
    }
  }
}

export async function updateThreadTitleOnServer(threadId: string, title: string): Promise<void> {
  if (!canSyncToServer()) return;
  try {
    const res = await authFetch(`/api/chat/threads/${encodeURIComponent(threadId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    console.log("[sync] updateThreadTitleOnServer:", res.status, { threadId, title });
  } catch (err) {
    console.error("[sync] updateThreadTitleOnServer failed:", err);
    throw err; // Surface errors so the UI can show a toast
  }
}

export async function deleteThreadFromServer(threadId: string): Promise<void> {
  if (!canSyncToServer()) return;
  recentlyDeletedThreadIds.add(threadId);
  try {
    await authFetch(`/api/chat/threads/${encodeURIComponent(threadId)}`, { method: "DELETE" });
  } catch {
    // Silently fail — the guard above keeps it out of the sidebar regardless.
  }
}

export async function deleteMessageFromServer(threadId: string, messageId: string): Promise<boolean> {
  if (!canSyncToServer()) return false;
  // Delete a single message from the server. Returns success so the caller
  // can surface failures. Uses the dedicated per-message endpoint (not the
  // full upsert) to avoid the DELETE-all-then-INSERT race that would wipe
  // messages appended concurrently by another browser.
  try {
    const res = await authFetch(
      `/api/chat/threads/${encodeURIComponent(threadId)}/messages/${encodeURIComponent(messageId)}`,
      { method: "DELETE" },
    );
    return res.ok;
  } catch (err) {
    console.error("[sync] deleteMessageFromServer failed:", err);
    return false;
  }
}

// ── Sync operations ──────────────────────────────────────────────────

let _syncListMutex: Promise<void> | null = null;

export async function syncThreadListFromServer(): Promise<void> {
  // Serialize concurrent calls — multiple callers (useEffect + list()) fire
  // on mount, and overlapping IndexedDB r/w transactions corrupt state in Safari.
  while (_syncListMutex) {
    await _syncListMutex.catch(() => {}); // wait for prior sync, ignore its errors
  }
  let release: () => void;
  _syncListMutex = new Promise<void>((resolve) => { release = resolve; });

  try {
    console.log("[sync] syncThreadListFromServer: start");
    const { threads: serverThreads, subject } = await fetchServerThreads();
    if (serverThreads.length === 0) {
      console.log("[sync] syncThreadListFromServer: no threads from server, returning");
      return;
    }

    console.log("[sync] syncThreadListFromServer: writing threads to DB", { count: serverThreads.length, subject });
    for (const st of serverThreads) {
      // Skip server threads with no messages — they're empty shells
      if (!st.message_count) continue;
      // Skip threads the user just deleted locally, so a slow/failed server
      // delete can't resurrect an empty entry in the sidebar.
      if (recentlyDeletedThreadIds.has(st.id)) continue;
    const local = await db.threads.get(st.id);
    // Use the most recent timestamp across local and server so the
    // sidebar sort order converges across all clients.  The server's
    // updated_at reflects the last activity from ANY client; the local
    // createdAt may be newer if the local client just bumped it.
    const serverTs = st.updated_at
      ? new Date(st.updated_at).getTime()
      : (st.created_at ? new Date(st.created_at).getTime() : 0);
    const createdAt = Math.max(local?.createdAt ?? 0, serverTs) || Date.now();
    await db.threads.put({
        id: st.id,
        title: st.title ?? "New Chat",
        modelType: (local?.modelType ?? "base") as any,
        modelId: local?.modelId ?? "",
        pairId: local?.pairId,
        archived: false,
        createdAt,
        messageCount: st.message_count ?? local?.messageCount ?? 0,
        syncedFromServer: true,
        syncSubject: subject,
    });
  }

  // Remove local threads that no longer exist on the server, but ONLY
  // threads that were synced under the *same* auth subject.  Threads
  // synced under a different subject (e.g. "zopedia" threads seen
  // during a "local-user" sync) are left untouched — deleting them
  // would be wrongful data loss (they belong to a different identity).
  const serverIds = new Set(serverThreads.map((st) => st.id));
  const threadCount = await db.threads.count();
  const allLocalThreads = threadCount === 0 ? [] : await db.threads.toArray();
  for (const t of allLocalThreads) {
    if (
      t.syncedFromServer &&
      t.syncSubject === subject &&
      !serverIds.has(t.id)
    ) {
      await db.messages.where("threadId").equals(t.id).delete();
      await db.threads.delete(t.id);
    }
  }
  } finally {
    release!();
    _syncListMutex = null;
  }
}

function parseStoredContent(content: unknown): unknown {
  if (typeof content !== "string") return content;
  try {
    return JSON.parse(content);
  } catch {
    return content;
  }
}

export async function syncThreadMessagesFromServer(threadId: string): Promise<void> {
  const result = await fetchServerThread(threadId);
  if (!result?.messages?.length) return;

  const msgCount = await db.messages.count();
  const existingIds = new Set(
    msgCount === 0
      ? []
      : (await db.messages.where("threadId").equals(threadId).toArray()).map((m) => m.id),
  );
  for (const msg of result.messages) {
    if (!existingIds.has(msg.id)) {
      await db.messages.put({
        id: msg.id,
        threadId,
        role: msg.role,
        content: parseStoredContent(msg.content) as MessageRecord["content"],
        attachments: undefined,
        metadata: msg.reasoning_content ? { reasoning_content: msg.reasoning_content } : undefined,
        parentId: msg.parent_id ?? null,
        createdAt: new Date(msg.created_at).getTime(),
      });
    }
    // Mark server-fetched messages as synced so we don't re-send them
    syncedMessageIds.add(msg.id);
  }
}

export function debouncedSaveThreadToServer(threadId: string): void {
  const existing = debounceTimers.get(threadId);
  if (existing) clearTimeout(existing);

  debounceTimers.set(
    threadId,
    setTimeout(async () => {
      debounceTimers.delete(threadId);
      await syncThreadToServer(threadId);
    }, DEBOUNCE_MS)
  );
}

export async function deleteThreadFromBoth(threadId: string): Promise<void> {
  await deleteThreadFromServer(threadId);
  // Clean up synced tracking for this thread
  const msgCount = await db.messages.count();
  const msgs = msgCount === 0 ? [] : await db.messages.where("threadId").equals(threadId).toArray();
  for (const m of msgs) syncedMessageIds.delete(m.id);
  await db.messages.where("threadId").equals(threadId).delete();
  await db.threads.delete(threadId);
}

// ── Migration ────────────────────────────────────────────────────────

export async function maybeMigrateLocalToServer(): Promise<boolean> {
  const { threads: serverThreads } = await fetchServerThreads();
  if (serverThreads.length > 0) return false;

  const threadCount = await db.threads.count();
  const localThreads = threadCount === 0 ? [] : await db.threads.toArray();
  if (localThreads.length === 0) return false;

  // Import all local threads to server (skip empty threads)
  for (const thread of localThreads) {
    const msgCount = await db.messages.count();
    const msgs = msgCount === 0
      ? []
      : await db.messages.where("threadId").equals(thread.id).sortBy("createdAt");
    if (msgs.length === 0) continue;
    await saveThreadToServer(
      thread.id,
      thread.title,
      msgs.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        reasoning_content: (m.metadata as any)?.reasoning_content,
        parent_id: m.parentId,
        created_at: new Date(m.createdAt).toISOString(),
      })),
      thread.createdAt,
    );
    // Mark migrated messages as synced
    for (const m of msgs) syncedMessageIds.add(m.id);
  }
  return true;
}

// ── User Preferences (cross-device sync) ─────────────────────────────

const PREFERENCES_DEBOUNCE_MS = 3000;
let _pendingPrefsSave: ReturnType<typeof setTimeout> | null = null;

export async function fetchUserPreferences(): Promise<Record<string, unknown>> {
  try {
    const res = await authFetch("/api/chat/preferences", { cache: "no-store" });
    if (!res.ok) return {};
    const data = await res.json();
    return data.preferences ?? {};
  } catch {
    return {};
  }
}

export function saveUserPreferencesToServer(prefs: Record<string, unknown>): void {
  if (_pendingPrefsSave) clearTimeout(_pendingPrefsSave);
  _pendingPrefsSave = setTimeout(async () => {
    _pendingPrefsSave = null;
    try {
      await authFetch("/api/chat/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preferences: prefs }),
      });
    } catch {
      // Silently fail — localStorage is still the local source of truth
    }
  }, PREFERENCES_DEBOUNCE_MS);
}
