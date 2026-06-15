// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"use client";

import { type ToolCallMessagePartComponent, useAuiState } from "@assistant-ui/react";
import { DatabaseIcon, LoaderIcon } from "lucide-react";
import { memo, useEffect, useState } from "react";
import {
  ToolFallbackContent,
  ToolFallbackRoot,
  ToolFallbackTrigger,
} from "./tool-fallback";

interface SqlResult {
  columns?: string[];
  rows?: Record<string, unknown>[];
  row_count?: number;
  truncated?: boolean;
  error?: string;
}

const SqlToolUIImpl: ToolCallMessagePartComponent = ({
  args,
  result,
  status,
}) => {
  const query = ((args as { query?: string })?.query ?? "").trim();
  const isRunning = status?.type === "running";

  let parsed: SqlResult | null = null;
  if (result !== undefined) {
    try {
      parsed = typeof result === "string" ? JSON.parse(result) : result;
    } catch {
      parsed = null;
    }
  }

  // Collapse when LLM starts generating text after the tool call
  const hasText = useAuiState(({ message }) =>
    message.content.some(
      (p) => p.type === "text" && "text" in p && (p as { text: string }).text.length > 0,
    ),
  );
  const [open, setOpen] = useState(isRunning);
  useEffect(() => {
    if (isRunning) {
      setOpen(true);
    } else if (hasText) {
      setOpen(false);
    }
  }, [isRunning, hasText]);

  return (
    <ToolFallbackRoot open={open} onOpenChange={setOpen}>
      <ToolFallbackTrigger
        toolName={
          query
            ? query.length > 80
              ? `SQL: ${query.slice(0, 80)}…`
              : `SQL: ${query}`
            : "SQL Query"
        }
        status={status}
        icon={DatabaseIcon}
      />
      <ToolFallbackContent>
        {isRunning ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <LoaderIcon className="size-3.5 animate-spin" />
            <span>Running query&hellip;</span>
          </div>
        ) : parsed?.error ? (
          <div className="rounded bg-destructive/10 border border-destructive/30 px-3 py-2 text-sm text-destructive">
            {parsed.error}
          </div>
        ) : parsed?.rows && parsed.rows.length > 0 ? (
          <div className="w-full overflow-hidden rounded-md border border-border">
            <div className="max-h-64 overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border bg-muted/50">
                    {parsed.columns?.map((col) => (
                      <th
                        key={col}
                        className="whitespace-nowrap px-3 py-2 text-left font-medium text-muted-foreground"
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {parsed.rows.map((row, i) => (
                    <tr
                      key={i}
                      className="border-b border-border last:border-0 hover:bg-muted/30"
                    >
                      {parsed.columns?.map((col) => (
                        <td
                          key={col}
                          className="max-w-60 truncate whitespace-nowrap px-3 py-1.5"
                          title={String(row[col] ?? "")}
                        >
                          {row[col] === null ? (
                            <span className="italic text-muted-foreground">NULL</span>
                          ) : (
                            String(row[col])
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-border bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
              <span>
                {parsed.row_count} row{parsed.row_count !== 1 ? "s" : ""}
                {parsed.truncated ? " (truncated)" : ""}
              </span>
            </div>
          </div>
        ) : parsed?.rows ? (
          <div className="text-sm text-muted-foreground">
            Query returned 0 rows.
          </div>
        ) : result !== undefined ? (
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-muted/50 p-2 text-xs">
            {typeof result === "string" ? result : JSON.stringify(result, null, 2)}
          </pre>
        ) : null}
        {query && (
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-muted/50 p-2 text-xs font-mono">
            {query}
          </pre>
        )}
      </ToolFallbackContent>
    </ToolFallbackRoot>
  );
};

export const SqlToolUI = memo(
  SqlToolUIImpl,
) as unknown as ToolCallMessagePartComponent;
SqlToolUI.displayName = "SqlToolUI";
