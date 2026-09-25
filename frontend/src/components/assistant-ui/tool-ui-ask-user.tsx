// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"use client";

import { type ToolCallMessagePartComponent, useAuiState } from "@assistant-ui/react";
import { CheckCircle2Icon, HelpCircleIcon, LoaderIcon, XCircleIcon } from "lucide-react";
import { memo, useState } from "react";
import { toast } from "sonner";
import { authFetch } from "@/features/auth";
import {
  ToolFallbackContent,
  ToolFallbackRoot,
  ToolFallbackTrigger,
} from "./tool-fallback";

interface AskUserArgs {
  question?: string;
  options?: string[];
  /** Echoed back by the server in tool_start — the id the pause is keyed on. */
  session_id?: string;
}

interface AskUserResult {
  answer?: string | null;
  note?: string;
}

/** POST a user's answer to a paused ask_user_question tool call. */
async function submitToolAnswer(
  sessionId: string,
  toolCallId: string,
  answer: string,
): Promise<void> {
  // Served by chat_router, which is mounted at prefix "/v1" (see main.py) —
  // so the resolved path is /v1/api/chat/tool-answer. Without the /v1 this
  // only matches the GET-only SPA catch-all and comes back 405.
  const res = await authFetch("/v1/api/chat/tool-answer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, tool_call_id: toolCallId, answer }),
  });
  if (!res.ok) {
    // Surface the server's reason: 409 means the question is no longer
    // awaiting an answer, which is the difference between "retry" and
    // "the model already moved on".
    let detail = "";
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      detail = "";
    }
    throw new Error(detail || `Failed to submit answer (${res.status})`);
  }
}

const AskUserQuestionToolUIImpl: ToolCallMessagePartComponent = ({
  args,
  result,
  status,
  toolCallId,
}) => {
  const { question = "", options = [], session_id } = (args ?? {}) as AskUserArgs;
  const isRunning = status?.type === "running";
  const liveThreadId = useAuiState(({ threads }) => threads.mainThreadId);
  // Use the id the server sent with tool_start — including when it is an empty
  // string, which is what a brand-new chat has before its thread id is
  // assigned. `||` here would fall back to the live thread id and key the answer
  // to a different pause, which is how the model ended up with "no response".
  const threadId = session_id !== undefined ? session_id : liveThreadId;

  const [freeText, setFreeText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // Distinct from `submitting`: only true once the server has actually accepted
  // the answer. Showing "sent" while the request is still in flight is what made
  // a rejected answer look delivered.
  const [sent, setSent] = useState(false);

  const answered =
    !isRunning && result !== undefined && typeof result === "string";
  let parsedResult: AskUserResult | null = null;
  if (answered) {
    try {
      parsedResult = JSON.parse(result as string);
    } catch {
      parsedResult = null;
    }
  }

  const submit = async (answer: string) => {
    const value = answer.trim();
    if (!value || submitting) return;
    if (threadId === undefined || threadId === null) {
      toast.error("Unable to submit answer: no active chat thread.");
      return;
    }
    setSubmitting(true);
    try {
      await submitToolAnswer(threadId, toolCallId, value);
      // Accepted by the server. The stream resumes server-side and tool_end
      // transitions this part to complete.
      setSent(true);
    } catch (err) {
      setSubmitting(false);
      toast.error("Failed to send your answer", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    }
  };

  return (
    <ToolFallbackRoot open={true} onOpenChange={() => {}}>
      <ToolFallbackTrigger
        toolName={question ? `Question: ${question.slice(0, 80)}` : "Ask User"}
        status={status}
        icon={HelpCircleIcon}
      />
      <ToolFallbackContent>
        {answered ? (
          parsedResult?.answer ? (
            <div className="flex items-start gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
              <CheckCircle2Icon className="mt-0.5 size-4 shrink-0 text-primary" />
              <div className="min-w-0">
                <p className="font-medium text-foreground">{question}</p>
                <p className="text-muted-foreground">
                  You answered: <span className="font-medium text-foreground">{parsedResult.answer}</span>
                </p>
              </div>
            </div>
          ) : (
            // Finished WITHOUT an answer. This must not fall through to the
            // form below: a completed call whose answer is null used to render
            // identically to a live pause, so the only way to discover the
            // question had already been abandoned was to click Send and get a
            // 409 back.
            <div className="flex items-start gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
              <XCircleIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0">
                <p className="font-medium text-foreground">{question}</p>
                <p className="text-muted-foreground">
                  The assistant continued without an answer
                  {parsedResult?.note ? ` (${parsedResult.note})` : ""}.
                </p>
              </div>
            </div>
          )
        ) : (
          <div className="space-y-3">
            {question && (
              <p className="text-sm font-medium text-foreground">{question}</p>
            )}
            {options.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {options.map((opt, i) => (
                  <button
                    key={i}
                    type="button"
                    disabled={submitting}
                    onClick={() => void submit(opt)}
                    className="rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-primary hover:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}
            <div className="flex items-center gap-2">
              <input
                value={freeText}
                onChange={(e) => setFreeText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void submit(freeText);
                }}
                placeholder={options.length > 0 ? "Or type a different answer…" : "Type your answer…"}
                disabled={submitting}
                className="h-8 min-w-0 flex-1 rounded-md border border-border bg-background px-2.5 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-primary disabled:opacity-50"
              />
              <button
                type="button"
                disabled={submitting || !freeText.trim()}
                onClick={() => void submit(freeText)}
                className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? (
                  <LoaderIcon className="size-3.5 animate-spin" />
                ) : (
                  "Send"
                )}
              </button>
            </div>
            {submitting && !sent && (
              <p className="text-xs text-muted-foreground">Sending your answer…</p>
            )}
            {sent && (
              <p className="text-xs text-muted-foreground">Answer sent — the assistant will continue shortly…</p>
            )}
          </div>
        )}
      </ToolFallbackContent>
    </ToolFallbackRoot>
  );
};

export const AskUserQuestionToolUI = memo(
  AskUserQuestionToolUIImpl,
) as unknown as ToolCallMessagePartComponent;
AskUserQuestionToolUI.displayName = "AskUserQuestionToolUI";
