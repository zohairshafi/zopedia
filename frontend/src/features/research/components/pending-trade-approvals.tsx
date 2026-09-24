// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"use client";

import { AlertTriangleIcon, LoaderIcon, TrendingDownIcon, TrendingUpIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  approvePendingApproval,
  listPendingApprovals,
  rejectPendingApproval,
} from "../api/trading-api";
import type { PendingTradeApproval } from "../types";

/**
 * Orders that research runs proposed but did NOT place.
 *
 * This surface is the whole reason headless runs are allowed to propose trades:
 * the run queues, and a human decides later. That means it has to work when the
 * items were created while the app was closed — hence the poll and the
 * visibilitychange refetch.
 */
const POLL_MS = 60_000;

function fmtAmount(order: PendingTradeApproval["order"]): string {
  if (order.qty != null) {
    const unit =
      order.asset_type === "option"
        ? order.qty === 1
          ? "contract"
          : "contracts"
        : order.qty === 1
          ? "share"
          : "shares";
    return `${order.qty} ${unit}`;
  }
  if (order.notional != null) return `$${order.notional.toLocaleString()}`;
  return "—";
}

/** Live countdown; flips to an explicit expired state instead of sitting at 0s. */
function useCountdown(expiresAt: string): { label: string; expired: boolean } {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const ms = new Date(expiresAt).getTime() - now;
  if (!Number.isFinite(ms)) return { label: "", expired: false };
  if (ms <= 0) return { label: "expired", expired: true };
  const mins = Math.floor(ms / 60000);
  if (mins < 60) return { label: `${mins}m left`, expired: false };
  const hours = Math.floor(mins / 60);
  if (hours < 24) return { label: `${hours}h ${mins % 60}m left`, expired: false };
  return { label: `${Math.floor(hours / 24)}d ${hours % 24}h left`, expired: false };
}

function ApprovalCard({
  approval,
  onResolved,
}: {
  approval: PendingTradeApproval;
  onResolved: () => void;
}) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const { label: countdown, expired } = useCountdown(approval.expires_at);
  const order = approval.order ?? {};
  const buy = order.side === "buy";
  const Icon = buy ? TrendingUpIcon : TrendingDownIcon;

  const act = async (kind: "approve" | "reject") => {
    if (busy) return;
    setBusy(kind);
    try {
      if (kind === "approve") {
        const res = await approvePendingApproval(approval.id);
        const o = (res.order ?? {}) as Record<string, unknown>;
        toast.success(`Order ${o.status ?? "submitted"}`, {
          description: o.filled_qty && Number(o.filled_qty) > 0
            ? `Filled ${o.filled_qty} @ ${o.filled_avg_price ?? "—"}`
            : `Not filled yet${o.id ? ` · ${o.id}` : ""}`,
        });
      } else {
        await rejectPendingApproval(approval.id);
        toast.info("Order rejected — nothing was placed");
      }
      onResolved();
    } catch (err) {
      // 410 (expired) and 409 (already decided) both mean no order was placed,
      // which is exactly what the user needs to know.
      toast.error(kind === "approve" ? "Could not place order" : "Could not reject order", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
      onResolved();
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card className="p-3">
      <div className="flex items-start gap-3">
        <Icon className={buy ? "mt-0.5 size-4 shrink-0 text-emerald-500" : "mt-0.5 size-4 shrink-0 text-red-500"} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-medium text-foreground">
              {(order.side ?? "").toUpperCase()} {fmtAmount(order)}{" "}
              <span className="font-mono">{order.symbol ?? "—"}</span>
            </p>
            <span
              className={
                expired
                  ? "text-xs font-medium text-destructive"
                  : "text-xs text-muted-foreground"
              }
            >
              {countdown}
            </span>
          </div>

          <p className="mt-1 text-xs text-muted-foreground">
            {order.order_type ?? "—"} · {order.time_in_force ?? "—"}
            {order.limit_price != null ? ` · limit ${order.limit_price}` : ""}
            {order.position_intent
              ? ` · ${order.position_intent}${order.derived_position_intent ? " (derived)" : ""}`
              : ""}
          </p>

          {approval.rationale && (
            <div className="mt-2 rounded-md border border-border px-2.5 py-1.5">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Model's reasoning
              </p>
              <p className="mt-0.5 text-xs text-foreground">{approval.rationale}</p>
            </div>
          )}

          {/* Provenance matters: a wiki page or search result could have talked
              the model into this, so show where it came from. */}
          <p className="mt-2 text-[11px] text-muted-foreground">
            Proposed by research run{" "}
            <span className="font-mono">{approval.config_id ?? approval.thread_id ?? "—"}</span>
            {approval.created_at
              ? ` on ${new Date(approval.created_at).toLocaleString()}`
              : ""}
          </p>

          <div className="mt-2.5 flex items-center gap-2">
            <Button
              size="sm"
              disabled={busy !== null || expired}
              onClick={() => void act("approve")}
            >
              {busy === "approve" ? (
                <>
                  <LoaderIcon className="mr-1.5 size-3.5 animate-spin" /> Placing…
                </>
              ) : (
                "Approve & place"
              )}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={busy !== null}
              onClick={() => void act("reject")}
            >
              Reject
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}

export function PendingTradeApprovals() {
  const [approvals, setApprovals] = useState<PendingTradeApproval[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const { approvals: list } = await listPendingApprovals();
      setApprovals(list);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load pending approvals");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  // Nothing queued is the common case — stay out of the way entirely.
  if (!loaded || (approvals.length === 0 && !error)) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-medium text-foreground">Orders awaiting your approval</h2>
        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
          {approvals.length}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        Research runs can propose trades, but nothing is submitted until you approve it.
      </p>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs">
          <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0 text-destructive" />
          <span>{error}</span>
        </div>
      )}

      {approvals.map((a) => (
        <ApprovalCard key={a.id} approval={a} onResolved={() => void refresh()} />
      ))}
    </div>
  );
}
