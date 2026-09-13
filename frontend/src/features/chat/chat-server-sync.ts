import { authFetch, getAuthToken as getAuthTokenSync } from "@/features/auth";
import { db } from "./db";
import type { MessageRecord, ThreadRecord } from "./types";
import { toast } from "sonner";

const DEBOUNCE_MS = 800;
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

// Surface message-sync failures loudly (visible toast) instead of only
// console.error — the pywebview console is hidden, so silent failures
// would otherwise look like "messages vanished after reopen". Throttled
// to once per minute so a persistent failure (e.g. expired token) does
// not spam on every debounced retry.
let _lastSyncFailToastAt = 0;
function notifySyncFailure(reason: string): void {
  console.error("[sync] chat history sync failed:", reason);
  const now = Date.now();
  if (now - _lastSyncFailToastAt < 60_000) return;
  _lastSyncFailToastAt = now;
  toast.error("Chat history sync failed", {
    description: `${reason}. Recent messages may not be saved to the server.`,
    duration: 8000,
  });
}

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

// Called when the app returns to the foreground.  Registered by ChatRuntimeProvider
// (which has aui access) so the active thread can re-sync + reload — picking up a
// generation the backend completed while the client was disconnected/minimized.
let _onForeground: (() => void) | null = null;

export function registerOnForeground(fn: () => void): () => void {
  _onForeground = fn;
  return () => {
    if (_onForeground === fn) _onForeground = null;
  };
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      flushPendingSaves();
    } else if (document.visibilityState === "visible") {
      _onForeground?.();
    }
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

async function fetchServerThread(
  threadId: string,
  opts?: { signal?: AbortSignal },
): Promise<{ thread: any; messages: any[] } | null> {
  try {
    const res = await authFetch(`/api/chat/threads/${encodeURIComponent(threadId)}`, {
      cache: "no-store",
      ...(opts?.signal ? { signal: opts.signal } : {}),
    });
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
    if (!res.ok) {
      notifySyncFailure(`server returned ${res.status} for message append`);
      return [];
    }
    const data = await res.json().catch(() => null);
    // Server now returns the actual inserted_ids — trust that, not our send list.
    return Array.isArray(data?.inserted_ids) ? data.inserted_ids : [];
  } catch (err) {
    notifySyncFailure(err instanceof Error ? err.message : String(err));
    return [];
  }
}

async function syncThreadToServer(threadId: string): Promise<void> {
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

  // Prepare messages — send each unsynced message as-is.  We do NOT chunk
  // oversized content: the old chunking split JSON content into invalid
  // fragments (rendered as raw JSON on fresh clients), and it's redundant with
  // the keepalive-skip logic in appendMessagesToServer.
  const toSend = unsynced.map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content,
    reasoning_content: (m.metadata as any)?.reasoning_content,
    parent_id: m.parentId,
    created_at: new Date(m.createdAt).toISOString(),
  }));

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

  // Mark confirmed messages as synced (send-id === message id now that we no
  // longer chunk).
  for (const id of confirmedSendIds) {
    syncedMessageIds.add(id);
  }
  console.info("[sync] thread %s: sent %d msgs, confirmed %d, total synced %d",
    threadId, toSend.length, confirmedSendIds.length, syncedMessageIds.size);
}

export async function updateThreadTitleOnServer(threadId: string, title: string): Promise<void> {
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
  recentlyDeletedThreadIds.add(threadId);
  try {
    await authFetch(`/api/chat/threads/${encodeURIComponent(threadId)}`, { method: "DELETE" });
  } catch {
    // Silently fail — the guard above keeps it out of the sidebar regardless.
  }
}

export async function deleteMessageFromServer(threadId: string, messageId: string): Promise<boolean> {
  // Delete a single message from the server. Returns success so the caller
  // can surface failures. Uses the dedicated per-message endpoint (not the
  // full upsert) to avoid the DELETE-all-then-INSERT race that would wipe
  // messages appended concurrently by another browser.
  try {
    const res = await authFetch(
      `/api/chat/threads/${encodeURIComponent(threadId)}/messages/${encodeURIComponent(messageId)}`,
      { method: "DELETE", keepalive: true },
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
    // Best-effort repair of content the server truncated mid-string.
    const repaired = repairTruncatedJson(content);
    if (repaired !== null) {
      try {
        return JSON.parse(repaired);
      } catch {
        // fall through to raw string
      }
    }
    return content;
  }
}

// The server used to truncate oversized content by cutting the serialized JSON
// at a fixed char limit and appending "\n\n...(truncated at …)". That cut lands
// mid-string, so the JSON no longer parses and the message renders as raw JSON.
// Strip the marker and close the unterminated string + any open brackets so the
// message parses again (the tail of a large tool result is lost, but the
// structure and most of the content survive).
function repairTruncatedJson(raw: string): string | null {
  const markerRe = /\n\n\.\.\.\(truncated at \d+ chars, original: \d+ chars\)\s*$/;
  if (!markerRe.test(raw)) return null;
  const base = raw.replace(markerRe, "");

  let inString = false;
  let escaped = false;
  const stack: string[] = [];
  for (const ch of base) {
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') inString = true;
    else if (ch === "{" || ch === "[") stack.push(ch);
    else if (ch === "}" || ch === "]") stack.pop();
  }

  let out = base;
  if (inString) {
    if (escaped) out = out.slice(0, -1); // drop a dangling backslash at the cut
    out += '"';
  }
  while (stack.length > 0) {
    out += stack.pop() === "{" ? "}" : "]";
  }
  return out;
}

// Older sync code split oversized message content into `{id}-chunk-{N}`
// messages whose `content` is an invalid JSON fragment (cut mid-string). Those
// fragments render as raw JSON. Reassemble consecutive chunks back into a
// single message so they parse and render correctly. Fragments were contiguous
// slices, so concatenation reconstructs the original JSON (up to lost boundary
// whitespace); if it still fails to parse, the message falls back to raw text.
function reassembleChunkedMessages(messages: any[]): any[] {
  const chunkRe = /^(.*)-chunk-(\d+)$/;
  const byBase = new Map<string, any[]>();
  const others: any[] = [];
  for (const msg of messages) {
    const m = msg?.id && typeof msg.id === "string" ? msg.id.match(chunkRe) : null;
    if (m) {
      const list = byBase.get(m[1]) ?? [];
      list.push(msg);
      byBase.set(m[1], list);
    } else {
      others.push(msg);
    }
  }
  if (byBase.size === 0) return messages;

  const reassembled: any[] = [...others];
  for (const [base, chunks] of byBase) {
    chunks.sort((a, b) => {
      const ai = parseInt(a.id.match(chunkRe)?.[2] ?? "0", 10);
      const bi = parseInt(b.id.match(chunkRe)?.[2] ?? "0", 10);
      return ai - bi;
    });
    const full = chunks
      .map((c) => (typeof c.content === "string" ? c.content : ""))
      .join("");
    reassembled.push({
      ...chunks[0],
      id: base,
      content: parseStoredContent(full),
    });
  }
  // Preserve server order so parent_id references resolve.
  reassembled.sort((a, b) => String(a.created_at ?? "").localeCompare(String(b.created_at ?? "")));
  return reassembled;
}

export async function syncThreadMessagesFromServer(
  threadId: string,
  opts?: { signal?: AbortSignal },
): Promise<number> {
  const result = await fetchServerThread(threadId, opts);
  if (!result?.messages?.length) return 0;
  const messages = reassembleChunkedMessages(result.messages);

  // Tombstones: locally-deleted message ids that must NOT be resurrected by a
  // downsync. The server DELETE may not have landed yet (fire-and-forget), so
  // without this the deleted message would reappear on every reload.
  const thread = await db.threads.get(threadId);
  const tombstones = new Set(thread?.deletedMessageIds ?? []);

  const msgCount = await db.messages.count();
  const existingIds = new Set(
    msgCount === 0
      ? []
      : (await db.messages.where("threadId").equals(threadId).toArray()).map((m) => m.id),
  );
  const serverIds = new Set<string>();
  let insertedCount = 0;
  for (const msg of messages) {
    serverIds.add(msg.id);
    if (tombstones.has(msg.id)) continue; // don't resurrect a locally-deleted message
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
      insertedCount += 1;
    }
    // Mark server-fetched messages as synced so we don't re-send them
    syncedMessageIds.add(msg.id);
  }

  // Prune tombstones whose ids are gone from the server (the remote delete
  // eventually succeeded) so the list can't grow unbounded.
  if (thread?.deletedMessageIds?.length) {
    const remaining = thread.deletedMessageIds.filter((id) => serverIds.has(id));
    if (remaining.length !== thread.deletedMessageIds.length) {
      await db.threads.update(threadId, { deletedMessageIds: remaining });
    }
  }
  return insertedCount;
}

export function debouncedSaveThreadToServer(threadId: string): void {
  const existing = debounceTimers.get(threadId);
  if (existing) clearTimeout(existing);

  debounceTimers.set(
    threadId,
    setTimeout(async () => {
      debounceTimers.delete(threadId);
      await syncThreadToServer(threadId);
      // Refresh the local thread list so the ordering converges with the
      // server (which now has an updated updated_at for this thread).
      syncThreadListFromServer().catch((err) => {
        console.error("[sync] thread list refresh after save failed:", err);
      });
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
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      console.error("[prefs] GET /api/chat/preferences failed", res.status, body);
      return {};
    }
    const data = await res.json();
    const prefs = data.preferences ?? {};
    console.info("[prefs] loaded from server", { keys: Object.keys(prefs) });
    return prefs;
  } catch (e) {
    console.error("[prefs] GET /api/chat/preferences threw", e);
    return {};
  }
}

export function saveUserPreferencesToServer(prefs: Record<string, unknown>): void {
  if (_pendingPrefsSave) clearTimeout(_pendingPrefsSave);
  _pendingPrefsSave = setTimeout(async () => {
    _pendingPrefsSave = null;
    try {
      const res = await authFetch("/api/chat/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preferences: prefs }),
      });
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        console.error("[prefs] PUT /api/chat/preferences failed", res.status, body);
      } else {
        console.info("[prefs] saved to server", { keys: Object.keys(prefs) });
      }
    } catch (e) {
      console.error("[prefs] PUT /api/chat/preferences threw", e);
    }
  }, PREFERENCES_DEBOUNCE_MS);
}
