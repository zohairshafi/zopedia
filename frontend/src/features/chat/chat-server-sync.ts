import { authFetch } from "@/features/auth";
import { db } from "./db";
import type { MessageRecord, ThreadRecord } from "./types";

const DEBOUNCE_MS = 2000;
const debounceTimers = new Map<string, ReturnType<typeof setTimeout>>();

function flushPendingSaves() {
  for (const [threadId, timer] of debounceTimers) {
    clearTimeout(timer);
    debounceTimers.delete(threadId);
    void (async () => {
      const thread = await db.threads.get(threadId);
      if (!thread) return;
      const msgCount = await db.messages.count();
      const msgs = msgCount === 0
        ? []
        : await db.messages.where("threadId").equals(threadId).sortBy("createdAt");
      if (msgs.length === 0) return;
      await saveThreadToServer(
        threadId,
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
    })();
  }
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

async function saveThreadToServer(
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
    });
    console.log("[sync] saveThreadToServer:", res.status, { threadId, msgCount: messages.length });
  } catch (err) {
    console.error("[sync] saveThreadToServer failed:", err);
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

export async function syncThreadListFromServer(): Promise<void> {
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
  }
}

export function debouncedSaveThreadToServer(threadId: string): void {
  const existing = debounceTimers.get(threadId);
  if (existing) clearTimeout(existing);

  debounceTimers.set(
    threadId,
    setTimeout(async () => {
      debounceTimers.delete(threadId);
      const thread = await db.threads.get(threadId);
      if (!thread) return;
      const msgCount = await db.messages.count();
      const msgs = msgCount === 0
        ? []
        : await db.messages.where("threadId").equals(threadId).sortBy("createdAt");
      if (msgs.length === 0) return;
      await saveThreadToServer(
        threadId,
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
    }, DEBOUNCE_MS)
  );
}

export async function deleteThreadFromBoth(threadId: string): Promise<void> {
  await deleteThreadFromServer(threadId);
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
  }
  return true;
}
