// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

/**
 * Pending trade approvals — orders queued by research runs.
 *
 * These endpoints live on a router mounted at "" (not "/v1"), so the paths are
 * exactly as written, unlike the chat tool endpoints.
 */

import { authFetch } from "@/features/auth";
import type { PendingTradeApproval } from "../types";

/** Turn a non-ok response into an error carrying the server's own explanation. */
async function fail(res: Response, fallback: string): Promise<Error> {
  let detail = "";
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") detail = body.detail;
    else if (body?.detail) detail = JSON.stringify(body.detail);
  } catch {
    // keep the fallback
  }
  return new Error(detail || `${fallback} (${res.status})`);
}

export async function listPendingApprovals(): Promise<{
  approvals: PendingTradeApproval[];
  pendingCount: number;
}> {
  const res = await authFetch("/api/trading/pending-approvals", { cache: "no-store" });
  if (!res.ok) throw await fail(res, "Failed to load pending approvals");
  const data = await res.json();
  return {
    approvals: data.approvals ?? [],
    pendingCount: data.pending_count ?? 0,
  };
}

/**
 * Approve and submit a queued order.
 *
 * Throws with the server's message on rejection — notably 410 (expired) and 409
 * (already decided), both of which mean the order was NOT placed again.
 */
export async function approvePendingApproval(
  approvalId: string,
): Promise<{ status: string; order?: Record<string, unknown> }> {
  const res = await authFetch(
    `/api/trading/pending-approvals/${encodeURIComponent(approvalId)}/approve`,
    { method: "POST", headers: { "Content-Type": "application/json" } },
  );
  if (!res.ok) throw await fail(res, "Failed to approve order");
  return res.json();
}

export async function rejectPendingApproval(approvalId: string): Promise<void> {
  const res = await authFetch(
    `/api/trading/pending-approvals/${encodeURIComponent(approvalId)}/reject`,
    { method: "POST", headers: { "Content-Type": "application/json" } },
  );
  if (!res.ok) throw await fail(res, "Failed to reject order");
}
