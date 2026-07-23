// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import type {
  CompleteAttachment,
  ExportedMessageRepository,
  ThreadMessage,
} from "@assistant-ui/react";
/**
 * assistant-ui does not expose a public `deleteMessage` on `ThreadRuntime` / `MessageRuntime`
 * in our version, but it already implements branch-safe deletion inside `MessageRepository`.
 * We import that helper from an **internal** package path (`runtime/utils/message-repository`).
 *
 * **Maintainability:** treat this file as the only place that imports `MessageRepository` from
 * `@assistant-ui/core`. When bumping `@assistant-ui/react` / `@assistant-ui/core`, re-run chat
 * delete + reload smoke tests; the path or API may change without a semver signal on “public”
 * surface area.
 */
import { MessageRepository } from "@assistant-ui/core/runtime/utils/message-repository";
import { db } from "@/features/chat/db";
import type { MessageRecord } from "@/features/chat/types";
import { deleteMessageFromServer } from "@/features/chat/chat-server-sync";

function cloneContent(content: ThreadMessage["content"]): ThreadMessage["content"] {
  if (typeof content === "string") {
    return content;
  }
  return Array.isArray(content) ? JSON.parse(JSON.stringify(content)) : [];
}

function cloneAttachments(
  attachments: readonly CompleteAttachment[] | undefined,
): readonly CompleteAttachment[] {
  if (!Array.isArray(attachments)) {
    return [];
  }
  return JSON.parse(JSON.stringify(attachments));
}

function exportedItemToRecord(
  threadId: string,
  parentId: string | null,
  message: ThreadMessage,
): MessageRecord {
  const content = cloneContent(message.content);
  if (message.role === "user") {
    const attachments = cloneAttachments(message.attachments);
    const custom = message.metadata?.custom;
    return {
      id: message.id,
      threadId,
      parentId: parentId ?? null,
      role: "user",
      content: content as Extract<ThreadMessage, { role: "user" }>["content"],
      ...(attachments.length > 0 && { attachments }),
      ...(custom && Object.keys(custom).length > 0 && { metadata: custom }),
      createdAt: message.createdAt?.getTime?.() ?? Date.now(),
    };
  }
  const custom = (message.metadata?.custom ?? {}) as Record<string, unknown>;
  return {
    id: message.id,
    threadId,
    parentId: parentId ?? null,
    role: "assistant",
    content: content as Extract<ThreadMessage, { role: "assistant" }>["content"],
    ...(Object.keys(custom).length > 0 && { metadata: custom }),
    createdAt: message.createdAt?.getTime?.() ?? Date.now(),
  };
}

/**
 * Persist the exact message list represented by `exp` for this thread, removing
 * Dexie rows that are no longer present (e.g. after a delete).
 */
async function syncExportedRepositoryToDexie(
  remoteId: string,
  exp: ExportedMessageRepository,
): Promise<void> {
  await db.transaction("rw", db.messages, async () => {
    const keepIds = new Set(exp.messages.map((x) => x.message.id));
    const existing = await db.messages.where("threadId").equals(remoteId).toArray();
    const idsToDelete = existing
      .filter((m) => !keepIds.has(m.id))
      .map((m) => m.id);
    if (idsToDelete.length > 0) {
      await db.messages.bulkDelete(idsToDelete);
    }
    await db.messages.bulkPut(
      exp.messages.map(({ message, parentId }) =>
        exportedItemToRecord(remoteId, parentId, message),
      ),
    );
  });
}

type ThreadImportExport = {
  export: () => ExportedMessageRepository;
  import: (data: ExportedMessageRepository) => void;
};

/**
 * Remove a message from the thread and mirror the result to IndexedDB.
 */
export async function deleteThreadMessage(args: {
  thread: ThreadImportExport;
  messageId: string;
  remoteId: string | undefined;
}): Promise<void> {
  const { thread, messageId, remoteId } = args;
  const exported = thread.export();
  const repo = new MessageRepository();
  repo.import(exported);
  repo.deleteMessage(messageId);
  const next = repo.export();
  if (remoteId) {
    await syncExportedRepositoryToDexie(remoteId, next);

    // Record a tombstone BEFORE the server delete so a reload (or a downsync)
    // can't resurrect this message if the fire-and-forget server DELETE hasn't
    // landed yet. Read-modify-write the array on the thread row.
    const t = await db.threads.get(remoteId);
    if (t) {
      const tomb = Array.from(new Set([...(t.deletedMessageIds ?? []), messageId]));
      await db.threads.update(remoteId, { deletedMessageIds: tomb });
    }
  }
  // Update the UI immediately (don't block on the network delete).
  thread.import(next);

  if (remoteId) {
    // Propagate the deletion to the server via the dedicated per-message
    // delete endpoint — NOT a full upsert. The upsert path (DELETE-all +
    // INSERT-remaining) would wipe any messages appended concurrently by
    // another browser; the single-message delete removes only this id.
    // On confirmed success, clear the tombstone so it can't linger.
    deleteMessageFromServer(remoteId, messageId)
      .then(async (ok) => {
        if (!ok) return;
        const after = await db.threads.get(remoteId);
        if (after?.deletedMessageIds?.length) {
          await db.threads.update(remoteId, {
            deletedMessageIds: after.deletedMessageIds.filter((id) => id !== messageId),
          });
        }
      })
      .catch((err) => {
        console.error("[delete] deleteMessageFromServer failed:", err);
      });
  }
}
