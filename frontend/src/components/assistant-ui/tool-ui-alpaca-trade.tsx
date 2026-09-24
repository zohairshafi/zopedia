// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"use client";

import { type ToolCallMessagePartComponent, useAuiState } from "@assistant-ui/react";
import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  LoaderIcon,
  TrendingDownIcon,
  TrendingUpIcon,
  XCircleIcon,
} from "lucide-react";
import { memo, useState } from "react";
import { toast } from "sonner";
import { authFetch } from "@/features/auth";
import {
  ToolFallbackContent,
  ToolFallbackRoot,
  ToolFallbackTrigger,
} from "./tool-fallback";

interface OrderShape {
  symbol?: string;
  asset_type?: string;
  side?: string;
  qty?: number | null;
  notional?: number | null;
  order_type?: string;
  time_in_force?: string;
  limit_price?: number | null;
  stop_price?: number | null;
  trail_price?: number | null;
  trail_percent?: number | null;
  extended_hours?: boolean | null;
  order_class?: string | null;
  position_intent?: string | null;
  derived_position_intent?: boolean;
  rationale?: string | null;
}

interface ContractShape {
  underlying?: string;
  type?: string;
  strike_price?: string;
  expiration_date?: string;
  multiplier?: string;
}

interface TradeArgs {
  action?: string;
  /** Echoed back by the server in tool_start — the id the pause is keyed on. */
  session_id?: string;
  order?: OrderShape;
  contract?: ContractShape | null;
  market_open?: boolean | null;
  market_state_note?: string;
  next_open?: string;
  account_summary?: { buying_power?: string; cash?: string } | null;
  invalid?: string[];
}

interface PlacedOrder {
  id?: string;
  status?: string;
  filled_qty?: string;
  filled_avg_price?: string | null;
}

interface TradeResult {
  status?: string;
  note?: string;
  error?: string;
  problems?: string[];
  order?: PlacedOrder;
}

/** POST the user's approve/reject decision to a paused alpaca_trade call. */
async function submitDecision(
  sessionId: string,
  toolCallId: string,
  decision: "approve" | "reject",
): Promise<void> {
  // chat_router is mounted at prefix "/v1", so the resolved path is
  // /v1/api/chat/tool-approval — without the /v1 this only matches the GET-only
  // SPA catch-all and comes back 405.
  const res = await authFetch("/v1/api/chat/tool-approval", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, tool_call_id: toolCallId, decision }),
  });
  if (!res.ok) {
    // Surface the server's reason — 409 means the pause already ended, which is
    // the important case (the order was NOT placed again).
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : "";
    } catch {
      detail = "";
    }
    throw new Error(detail || `Failed to submit your decision (${res.status})`);
  }
}

function fmtAmount(o: OrderShape): string {
  if (o.qty != null) {
    const unit = o.asset_type === "option" ? (o.qty === 1 ? "contract" : "contracts") : o.qty === 1 ? "share" : "shares";
    return `${o.qty} ${unit}`;
  }
  if (o.notional != null) return `$${o.notional.toLocaleString()}`;
  return "—";
}

function fmtOption(c: ContractShape | null | undefined, symbol: string | undefined): string | null {
  if (!c?.type || !c.strike_price) return null;
  const right = c.type.toLowerCase() === "call" ? "Call" : "Put";
  const strike = Number(c.strike_price);
  return `${c.underlying ?? symbol} ${right} $${strike} exp ${c.expiration_date}`;
}

const Row = ({ label, value }: { label: string; value: React.ReactNode }) => (
  <div className="flex items-baseline justify-between gap-3 py-0.5">
    <span className="shrink-0 text-xs text-muted-foreground">{label}</span>
    <span className="min-w-0 text-right text-xs font-medium text-foreground">{value}</span>
  </div>
);

const AlpacaTradeToolUIImpl: ToolCallMessagePartComponent = ({
  args,
  result,
  status,
  toolCallId,
}) => {
  const a = (args ?? {}) as TradeArgs;
  const order = a.order ?? {};
  const isRunning = status?.type === "running";
  const liveThreadId = useAuiState(({ threads }) => threads.mainThreadId);
  // Prefer the id the server sent with tool_start: the pause is keyed on the
  // thread id the request carried at run start, which may not be the thread the
  // user is looking at now. Deriving it locally meant an approval could land on
  // a key nobody was waiting on.
  const threadId = a.session_id || liveThreadId;
  const [pending, setPending] = useState<"approve" | "reject" | null>(null);

  const decided = !isRunning && result !== undefined && typeof result === "string";
  let parsed: TradeResult | null = null;
  if (decided) {
    try {
      parsed = JSON.parse(result as string);
    } catch {
      parsed = null;
    }
  }

  const isCancel = a.action === "cancel_order";
  const buy = order.side === "buy";
  const Icon = isCancel ? XCircleIcon : buy ? TrendingUpIcon : TrendingDownIcon;

  const decide = async (decision: "approve" | "reject") => {
    if (pending) return;
    if (!threadId) {
      toast.error("Unable to submit: no active chat thread.");
      return;
    }
    setPending(decision);
    try {
      await submitDecision(threadId, toolCallId, decision);
      // The stream resumes server-side and the real outcome arrives as tool_end
      // on this same part. Deliberately no optimistic "placed" state — the card
      // must show what Alpaca actually did, not what we hoped.
    } catch (err) {
      setPending(null);
      toast.error(decision === "approve" ? "Approval failed" : "Rejection failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    }
  };

  const headline = isCancel
    ? `Cancel order ${(args as { order_id?: string })?.order_id ?? ""}`
    : `${(order.side ?? "").toUpperCase()} ${fmtAmount(order)} ${order.symbol ?? ""}`.trim();

  const optionLabel = fmtOption(a.contract, order.symbol);

  return (
    <ToolFallbackRoot open={true} onOpenChange={() => {}}>
      <ToolFallbackTrigger toolName={headline || "Trade"} status={status} icon={Icon} />
      <ToolFallbackContent>
        {decided ? (
          <OutcomeView parsed={parsed} order={order} optionLabel={optionLabel} buy={buy} />
        ) : (
          <div className="space-y-3">
            <div className="rounded-md border border-border bg-muted/30 px-3 py-2">
              {optionLabel && <Row label="Contract" value={optionLabel} />}
              <Row label="Symbol" value={order.symbol ?? "—"} />
              <Row label="Side" value={(order.side ?? "—").toUpperCase()} />
              <Row label="Quantity" value={fmtAmount(order)} />
              <Row label="Order type" value={order.order_type ?? "—"} />
              <Row label="Time in force" value={order.time_in_force ?? "—"} />
              {order.limit_price != null && <Row label="Limit price" value={order.limit_price} />}
              {order.stop_price != null && <Row label="Stop price" value={order.stop_price} />}
              {order.position_intent && (
                <Row
                  label="Position intent"
                  value={
                    <>
                      {order.position_intent}
                      {order.derived_position_intent && (
                        <span className="ml-1 text-muted-foreground">(derived)</span>
                      )}
                    </>
                  }
                />
              )}
              {a.account_summary?.buying_power != null && (
                <Row label="Buying power" value={`$${Number(a.account_summary.buying_power).toLocaleString()}`} />
              )}
            </div>

            {a.market_open === false && (
              <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs">
                <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0 text-amber-500" />
                <span>
                  The market is closed. Approving now will queue this order for the next
                  open{a.next_open ? ` (${new Date(a.next_open).toLocaleString()})` : ""}.
                </span>
              </div>
            )}
            {a.market_open == null && a.market_state_note && (
              <div className="flex items-start gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
                <span>{a.market_state_note}</span>
              </div>
            )}

            {order.rationale && (
              <div className="rounded-md border border-border px-3 py-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                  Model's reasoning
                </p>
                <p className="mt-1 text-xs text-foreground">{order.rationale}</p>
              </div>
            )}

            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={pending !== null}
                onClick={() => void decide("approve")}
                className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {pending === "approve" ? (
                  <LoaderIcon className="size-3.5 animate-spin" />
                ) : (
                  "Approve & place order"
                )}
              </button>
              <button
                type="button"
                disabled={pending !== null}
                onClick={() => void decide("reject")}
                className="inline-flex h-8 items-center rounded-md border border-border px-3 text-sm font-medium text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
              >
                {pending === "reject" ? <LoaderIcon className="size-3.5 animate-spin" /> : "Reject"}
              </button>
            </div>
            {pending === "approve" && (
              <p className="text-xs text-muted-foreground">
                Submitting to Alpaca — this can take a moment…
              </p>
            )}
          </div>
        )}
      </ToolFallbackContent>
    </ToolFallbackRoot>
  );
};

/** Terminal state. Never claims success unless Alpaca said so. */
const OutcomeView = ({
  parsed,
  order,
  optionLabel,
  buy,
}: {
  parsed: TradeResult | null;
  order: OrderShape;
  optionLabel: string | null;
  buy: boolean;
}) => {
  if (!parsed) {
    return <p className="text-sm text-muted-foreground">No result returned.</p>;
  }

  if (parsed.status === "placed" && parsed.order) {
    const o = parsed.order;
    return (
      <div className="flex items-start gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
        <CheckCircle2Icon className="mt-0.5 size-4 shrink-0 text-primary" />
        <div className="min-w-0">
          <p className="font-medium text-foreground">
            Order {o.status ?? "submitted"} — {order.side?.toUpperCase()} {fmtAmount(order)}{" "}
            {order.symbol}
          </p>
          {optionLabel && <p className="text-xs text-muted-foreground">{optionLabel}</p>}
          <p className="text-xs text-muted-foreground">
            {o.filled_qty && Number(o.filled_qty) > 0
              ? `Filled ${o.filled_qty} @ ${o.filled_avg_price ?? "—"}`
              : "Not filled yet"}
            {o.id ? ` · ${o.id}` : ""}
          </p>
        </div>
      </div>
    );
  }

  if (parsed.status === "rejected" || parsed.status === "expired") {
    return (
      <div className="flex items-start gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
        <XCircleIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <p className="font-medium text-foreground">
            {parsed.status === "rejected" ? "You declined this order" : "Approval expired"}
          </p>
          <p className="text-xs text-muted-foreground">
            {parsed.note ?? "Nothing was placed."}
          </p>
        </div>
      </div>
    );
  }

  // Anything else is a failure — show Alpaca's own wording, unedited.
  return (
    <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm">
      <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-destructive" />
      <div className="min-w-0">
        <p className="font-medium text-foreground">Order not placed</p>
        <p className="break-words text-xs text-muted-foreground">
          {parsed.error ?? "Unknown error"}
        </p>
        {parsed.problems && parsed.problems.length > 0 && (
          <ul className="mt-1 list-disc pl-4 text-xs text-muted-foreground">
            {parsed.problems.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        )}
        <p className="mt-1 text-[11px] text-muted-foreground">
          {buy ? "No buy" : "No sell"} was submitted.
        </p>
      </div>
    </div>
  );
};

export const AlpacaTradeToolUI = memo(
  AlpacaTradeToolUIImpl,
) as unknown as ToolCallMessagePartComponent;
AlpacaTradeToolUI.displayName = "AlpacaTradeToolUI";
