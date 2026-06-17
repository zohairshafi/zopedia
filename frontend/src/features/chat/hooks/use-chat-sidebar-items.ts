// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { useEffect, useState } from "react";
import { db, useLiveQuery } from "../db";
import { useChatRuntimeStore } from "../stores/chat-runtime-store";
import type { ThreadRecord } from "../types";
import { debouncedSaveThreadToServer, deleteThreadFromServer, updateThreadTitleOnServer } from "../chat-server-sync";

const LOADING_TIMEOUT_MS = 6000;

export interface SidebarItem {
  type: "single" | "compare";
  id: string;
  title: string;
  createdAt: number;
}

export function groupThreads(threads: ThreadRecord[]): SidebarItem[] {
  const items: SidebarItem[] = [];
  const seenPairs = new Set<string>();

  for (const t of threads) {
    if (t.archived) {
      continue;
    }
    if (t.pairId) {
      if (seenPairs.has(t.pairId)) {
        continue;
      }
      seenPairs.add(t.pairId);
      items.push({
        type: "compare",
        id: t.pairId,
        title: t.title,
        createdAt: t.createdAt,
      });
    } else if (!t.pairId) {
      items.push({
        type: "single",
        id: t.id,
        title: t.title,
        createdAt: t.createdAt,
      });
    }
  }

  return items.sort((a, b) => b.createdAt - a.createdAt);
}

export function useChatSidebarItems() {
  const allThreads = useLiveQuery(async () => {
    // Guard empty-table cursor ops: Safari throws "Unable to open cursor"
    // when uniqueKeys/toArray use IDBCursor on an empty object store.
    const msgCount = await db.messages.count();
    const threadIdsWithMessage = new Set<string>(
      msgCount === 0
        ? []
        : ((await db.messages.orderBy("threadId").uniqueKeys()) as string[]),
    );
    const threadCount = await db.threads.count();
    const rows = threadCount === 0
      ? []
      : await db.threads.orderBy("createdAt").reverse().toArray();
    const filtered = rows.filter(
      (t) => !t.archived && (
        (t.messageCount ?? 0) > 0 ||
        threadIdsWithMessage.has(t.id) ||
        t.syncedFromServer
      ),
    );
    console.log("[sidebar] useChatSidebarItems poll:", {
      threadCount,
      rowCount: rows.length,
      msgCount,
      threadsWithMessages: threadIdsWithMessage.size,
      syncedFromServer: rows.filter(t => t.syncedFromServer).length,
      filteredCount: filtered.length,
    });
    return filtered;
  }, []);

  const items = groupThreads(allThreads ?? []);

  // Stay in loading state until data arrives (server sync may not have
  // completed by the first poll) or a timeout expires (genuinely empty).
  const [timedOut, setTimedOut] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setTimedOut(true), LOADING_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, []);
  const loading = items.length === 0 && !timedOut;

  const canCompare = useChatRuntimeStore((s) => Boolean(s.params.checkpoint));

  return { items, loading, canCompare };
}

function cancelIfRunning(threadId: string): void {
  const { runningByThreadId, cancelByThreadId } =
    useChatRuntimeStore.getState();
  if (!runningByThreadId[threadId]) return;
  cancelByThreadId[threadId]?.();
}

export async function deleteChatItem(
  item: SidebarItem,
  activeId: string | undefined,
  onSelect: (view: { mode: "single"; newThreadNonce: string }) => void,
) {
  const threadIds: string[] =
    item.type === "single"
      ? [item.id]
      : (await db.threads.where("pairId").equals(item.id).toArray()).map(
          (t) => t.id,
        );

  // Stop any in-flight streams before deleting, so the model doesn't keep
  // generating against a thread that no longer exists.
  for (const id of threadIds) cancelIfRunning(id);

  await db.transaction("rw", db.threads, db.messages, async () => {
    for (const id of threadIds) {
      await db.messages.where("threadId").equals(id).delete();
      await db.threads.delete(id);
    }
  });

  // Delete from server in background — don't block UI responsiveness.
  void Promise.all(threadIds.map((id) => deleteThreadFromServer(id)));

  if (activeId === item.id) {
    useChatRuntimeStore.getState().setActiveThreadId(null);
    onSelect({ mode: "single", newThreadNonce: crypto.randomUUID() });
  }
}

export async function renameChatItem(
  item: SidebarItem,
  nextTitle: string,
): Promise<void> {
  const title = nextTitle.trim();
  if (!title) {
    throw new Error("Title cannot be empty.");
  }

  if (item.type === "single") {
    await db.threads.update(item.id, { title });
    // Save title directly to server — no debounce, no message dependency.
    // (debouncedSaveThreadToServer requires messages to exist, so a rename
    // before any messages are synced would silently drop the title update.)
    await updateThreadTitleOnServer(item.id, title).catch(() => {});
    return;
  }

  const threadIds: string[] = [];
  await db.transaction("rw", db.threads, async () => {
    const pairThreads = await db.threads.where("pairId").equals(item.id).toArray();
    for (const thread of pairThreads) {
      await db.threads.update(thread.id, { title });
      threadIds.push(thread.id);
    }
  });
  for (const id of threadIds) {
    await updateThreadTitleOnServer(id, title).catch(() => {});
  }
}
