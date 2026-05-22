// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import Dexie, { type EntityTable } from "dexie";
import { useEffect, useRef, useState } from "react";
import type { MessageRecord, ThreadRecord } from "./types";

const DB_NAME = "unsloth-chat";

const db = new Dexie(DB_NAME) as Dexie & {
  threads: EntityTable<ThreadRecord, "id">;
  messages: EntityTable<MessageRecord, "id">;
};

db.version(1).stores({
  threads: "id, modelType, pairId, archived, createdAt",
  messages: "id, threadId, createdAt",
});

db.version(2)
  .stores({
    threads: "id, modelType, pairId, archived, createdAt",
    messages: "id, threadId, createdAt",
  })
  .upgrade((tx) => tx.table("messages").clear());

db.version(3)
  .stores({
    threads: "id, modelType, pairId, archived, createdAt",
    messages: "id, threadId, createdAt",
  })
  .upgrade((tx) =>
    tx
      .table("threads")
      .toCollection()
      .modify((thread) => {
        if (!thread.modelId) thread.modelId = "";
      }),
  );

const RECOVERY_KEY = "zopedia-db-recovery";

async function resetAndReload(): Promise<void> {
  if (typeof sessionStorage !== "undefined" && sessionStorage.getItem(RECOVERY_KEY) === "1") return;

  let cleared = false;
  try {
    await db.transaction("rw", db.threads, db.messages, async () => {
      await db.threads.clear();
      await db.messages.clear();
    });
    cleared = true;
  } catch {
    // Clearing failed, try deleteDatabase as fallback.
  }

  if (!cleared) {
    try { db.close(); } catch { /* ok */ }
    let deleted = false;
    await new Promise<void>((resolve) => {
      const req = indexedDB.deleteDatabase(DB_NAME);
      req.onsuccess = () => { deleted = true; resolve(); };
      req.onerror = () => resolve();
      req.onblocked = () => resolve();
    });
    await new Promise((r) => setTimeout(r, 100));
    if (!deleted) {
      // Blocked by another connection — flag and retry on reload.
      try { sessionStorage.setItem(RECOVERY_KEY, "1"); } catch { /* ok */ }
      window.location.reload();
      return;
    }
  }

  // Reset succeeded — clear flag so future errors can re-trigger recovery.
  try { sessionStorage.removeItem(RECOVERY_KEY); } catch { /* ok */ }
  window.location.reload();
}

export { db, resetAndReload };

function isCursorError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return msg.includes("Unable to open cursor");
}

const recoveryFailed =
  typeof sessionStorage !== "undefined" && sessionStorage.getItem(RECOVERY_KEY) === "1";

const POLL_INTERVAL_MS = 2000;

/**
 * Runs a Dexie querier directly (no liveQuery prototype patching) and polls
 * every POLL_INTERVAL_MS for updates.  Dexie's liveQuery wraps
 * IDBDatabase.prototype.transaction which Safari and some Chrome versions
 * reject with "Unable to open cursor" — that patching is global and breaks
 * even direct queries once applied, so we avoid it entirely.
 */
export function useLiveQuery<T>(
  querier: () => Promise<T>,
  deps: unknown[] = [],
): T | undefined {
  const [value, setValue] = useState<T>();
  const querierRef = useRef(querier);
  querierRef.current = querier;

  useEffect(() => {
    let cancelled = false;

    const run = () => {
      querierRef.current().then((result) => {
        if (!cancelled) setValue(result);
      }).catch((err) => {
        if (isCursorError(err) && !recoveryFailed) void resetAndReload();
        console.error("useLiveQuery:", err);
      });
    };

    run();
    const timer = setInterval(run, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return value;
}
