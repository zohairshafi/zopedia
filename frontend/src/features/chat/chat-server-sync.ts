import { authFetch } from "@/features/auth";
import { db } from "./db";
import type { MessageRecord, ThreadRecord } from "./types";

const DEBOUNCE_MS = 2000;
const MAX_MESSAGE_CONTENT_BYTES = 40_000; // chunk messages exceeding ~40KB serialized
const debounceTimers = new Map<string, ReturnType<typeof setTimeout>>();

// In-memory set of message IDs already confirmed synced to the server.
// Survives within a session; on page reload it resets, but the server
// uses INSERT OR IGNORE so re-sending is harmless.
const syncedMessageIds = new Set<string>();

export function markMessagesSynced(ids: string[]): void {
  for (const id of ids) syncedMessageIds.add(id);
}

function flushPendingSaves() {
  for (const [threadId, timer] of debounceTimers) {
    clearTimeout(timer);
    debounceTimers.delete(threadId);
    void syncThreadToServer(threadId);
  }
}

function chunkLargeContent(content: unknown): unknown[] {
  // If content is a string and exceeds the size threshold, split it at
  // paragraph boundaries so each chunk stays under the limit.
  if (typeof content !== "string") return [content];
  const jsonSize = new TextEncoder().encode(JSON.stringify(content)).length;
  if (jsonSize <= MAX_MESSAGE_CONTENT_BYTES) return [content];

  // Split at double-newline (paragraph) boundaries
  const parts: string[] = [];
  let remaining = content;
  while (remaining.length > 0) {
    // Take a chunk that fits within the byte limit
    let chunk = remaining.slice(0, Math.floor(MAX_MESSAGE_CONTENT_BYTES / 2));
    // Back up to the last paragraph boundary
    const lastBreak = chunk.lastIndexOf("\n\n");
    if (lastBreak > chunk.length / 2) {
      chunk = chunk.slice(0, lastBreak);
    }
    parts.push(chunk.trim());
    remaining = remaining.slice(chunk.length).trimStart();
  }
  console.log("[sync] chunked large message into", parts.length, "parts");
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

async function fetchServerThreads(): Promise<Array<{ id: string; title: string; created_at: string; updated_at: string; message_count: number }>> {
  try {
    const res = await authFetch("/api/chat/threads", { cache: "no-store" });
    if (!res.ok) {
      console.log("[sync] fetchServerThreads: not ok", { status: res.status });
      return [];
    }
    const data = await res.json();
    console.log("[sync] fetchServerThreads: got threads", { count: data.threads?.length ?? 0 });
    return data.threads ?? [];
  } catch (err) {
    console.log("[sync] fetchServerThreads: error", err);
    return [];
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
): Promise<void> {
  try {
    const body: Record<string, unknown> = { thread_id: threadId, title, messages };
    if (createdAt) body.created_at = new Date(createdAt).toISOString();
    const res = await authFetch("/api/chat/threads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      keepalive: true,
    });
    console.log("[sync] saveThreadToServer:", res.status, { threadId, msgCount: messages.length });
  } catch (err) {
    console.error("[sync] saveThreadToServer failed:", err);
  }
}

async function appendMessagesToServer(
  threadId: string,
  title: string | undefined,
  messages: Array<{ id: string; role: string; content: any; reasoning_content?: string; parent_id?: string | null; created_at?: string }>,
): Promise<string[]> {
  // Append only these messages to the server. Returns the IDs that were confirmed synced.
  if (messages.length === 0) return [];
  try {
    const res = await authFetch(`/api/chat/threads/${encodeURIComponent(threadId)}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: threadId, title, messages }),
      keepalive: true,
    });
    console.log("[sync] appendMessagesToServer:", res.status, { threadId, msgCount: messages.length });
    return res.ok ? messages.map((m) => m.id) : [];
  } catch (err) {
    console.error("[sync] appendMessagesToServer failed:", err);
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

  // Prepare messages, chunking oversized content
  type Msg = {
    id: string;
    role: string;
    content: unknown;
    reasoning_content?: string;
    parent_id?: string | null;
    created_at?: string;
  };
  const toSend: Msg[] = [];
  for (const m of unsynced) {
    const chunks = chunkLargeContent(m.content);
    if (chunks.length === 1) {
      toSend.push({
        id: m.id,
        role: m.role,
        content: m.content,
        reasoning_content: (m.metadata as any)?.reasoning_content,
        parent_id: m.parentId,
        created_at: new Date(m.createdAt).toISOString(),
      });
    } else {
      // Split oversized message into chunked sub-messages
      for (let i = 0; i < chunks.length; i++) {
        toSend.push({
          id: `${m.id}-chunk-${i}`,
          role: m.role,
          content: chunks[i],
          reasoning_content: (m.metadata as any)?.reasoning_content,
          parent_id: i === 0 ? m.parentId : `${m.id}-chunk-${i - 1}`,
          created_at: new Date(m.createdAt + i).toISOString(),
        });
      }
    }
  }

  // First sync for this thread: send all messages as full sync (ensures server
  // state matches). After that, use append-only.
  const isFirstSync = allMsgs.every((m) => !syncedMessageIds.has(m.id));

  if (isFirstSync) {
    await saveThreadToServer(threadId, thread.title, toSend, thread.createdAt);
  } else {
    await appendMessagesToServer(threadId, thread.title, toSend);
  }

  // Mark all original message IDs as synced (not the chunk IDs)
  for (const m of unsynced) {
    syncedMessageIds.add(m.id);
  }
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
  try {
    await authFetch(`/api/chat/threads/${encodeURIComponent(threadId)}`, { method: "DELETE" });
  } catch {
    // Silently fail
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
    const serverThreads = await fetchServerThreads();
    if (serverThreads.length === 0) {
      console.log("[sync] syncThreadListFromServer: no threads from server, returning");
      return;
    }

    console.log("[sync] syncThreadListFromServer: writing threads to DB", { count: serverThreads.length });
    for (const st of serverThreads) {
      // Skip server threads with no messages — they're empty shells
      if (!st.message_count) continue;
    const local = await db.threads.get(st.id);
    // Always sync from server — server is the source of truth.
    // Preserve local createdAt if available (more accurate than server's).
    await db.threads.put({
        id: st.id,
        title: st.title ?? "New Chat",
        modelType: (local?.modelType ?? "base") as any,
        modelId: local?.modelId ?? "",
        pairId: local?.pairId,
        archived: false,
        createdAt: local?.createdAt ?? (st.updated_at ? new Date(st.updated_at).getTime() : (st.created_at ? new Date(st.created_at).getTime() : Date.now())),
        messageCount: st.message_count ?? local?.messageCount ?? 0,
        syncedFromServer: true,
    });
  }

  // Remove local threads that no longer exist on the server
  const serverIds = new Set(serverThreads.map((st) => st.id));
  const threadCount = await db.threads.count();
  const allLocalThreads = threadCount === 0 ? [] : await db.threads.toArray();
  for (const t of allLocalThreads) {
    if (t.syncedFromServer && !serverIds.has(t.id)) {
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
  const serverThreads = await fetchServerThreads();
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
