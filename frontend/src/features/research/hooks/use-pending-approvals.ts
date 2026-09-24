// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { listPendingApprovals } from "../api/trading-api";
import type { PendingTradeApproval } from "../types";

const POLL_MS = 60_000;

/**
 * Orders queued by research runs, kept fresh in the background.
 *
 * Polls and refetches on tab-visible on purpose: these rows are usually created
 * while the app is closed, so a fetch-on-mount alone would miss exactly the
 * case this surface exists for.
 */
export function usePendingApprovals(): {
  approvals: PendingTradeApproval[];
  pendingCount: number;
  loaded: boolean;
  error: string | null;
  refresh: () => Promise<void>;
} {
  const [approvals, setApprovals] = useState<PendingTradeApproval[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const { approvals: list, pendingCount: count } = await listPendingApprovals();
      if (!alive.current) return;
      setApprovals(list);
      setPendingCount(count);
      setError(null);
    } catch (err) {
      if (!alive.current) return;
      setError(err instanceof Error ? err.message : "Failed to load pending approvals");
    } finally {
      if (alive.current) setLoaded(true);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void refresh();
    const t = setInterval(() => void refresh(), POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive.current = false;
      clearInterval(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  return { approvals, pendingCount, loaded, error, refresh };
}
