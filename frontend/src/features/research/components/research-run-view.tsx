import { useEffect, useRef, useCallback, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  useResearchStore,
} from "../stores/research-store";
import { streamResearch, approveSources, cancelResearch } from "../api/research-api";
import { SourceApprovalPanel } from "./source-approval-panel";
import { ResearchProgressBar } from "./research-progress-bar";
import { ResearchRoundSummary } from "./research-round-summary";
import { ResearchFinalReport } from "./research-final-report";
import { db } from "@/features/chat/db";
import { saveThreadToServer } from "@/features/chat/chat-server-sync";
import type { ResearchConfig, ResearchEvent, SourceSuggestion } from "../types";

interface Props {
  config: ResearchConfig;
  sessionId: string;
  onNewResearch: () => void;
}

export function ResearchRunView({ config, sessionId, onNewResearch }: Props) {
  const navigate = useNavigate();
  const [savedThreadId, setSavedThreadId] = useState<string | null>(null);
  const phase = useResearchStore((s) => s.phase);
  const currentRound = useResearchStore((s) => s.currentRound);
  const totalRounds = useResearchStore((s) => s.totalRounds);
  const sources = useResearchStore((s) => s.sources);
  const roundResults = useResearchStore((s) => s.roundResults);
  const finalReport = useResearchStore((s) => s.finalReport);
  const error = useResearchStore((s) => s.error);
  const totalIngested = useResearchStore((s) => s.totalIngested);
  const warnings = useResearchStore((s) => s.warnings);
  const toolStatus = useResearchStore((s) => s.toolStatus);
  const toolActivities = useResearchStore((s) => s.toolActivities);
  const surveyContent = useResearchStore((s) => s.surveyContent);
  const researchTitle = useResearchStore((s) => s.researchTitle);

  const setPhase = useResearchStore((s) => s.setPhase);
  const setCurrentRound = useResearchStore((s) => s.setCurrentRound);
  const setTotalRounds = useResearchStore((s) => s.setTotalRounds);
  const setSources = useResearchStore((s) => s.setSources);
  const addRoundResult = useResearchStore((s) => s.addRoundResult);
  const appendFinalReport = useResearchStore((s) => s.appendFinalReport);
  const setError = useResearchStore((s) => s.setError);
  const setTotalIngested = useResearchStore((s) => s.setTotalIngested);
  const setToolStatus = useResearchStore((s) => s.setToolStatus);
  const addToolActivity = useResearchStore((s) => s.addToolActivity);
  const clearToolActivities = useResearchStore((s) => s.clearToolActivities);
  const completeToolActivity = useResearchStore((s) => s.completeToolActivity);
  const setResearchTitle = useResearchStore((s) => s.setResearchTitle);

  const controllerRef = useRef<AbortController | null>(null);
  const ingestedCountRef = useRef(0);

  const processEvent = useCallback(
    (event: ResearchEvent) => {
      switch (event.type) {
        case "research_started":
          setTotalRounds(event.total_rounds as number);
          setPhase("surveying");
          break;
        case "research_survey":
          useResearchStore.getState().setSurveyContent(event.content as string);
          setPhase("searching");
          clearToolActivities();
          break;
        case "research_round_start":
          setCurrentRound(event.round as number);
          setPhase("searching");
          break;
        case "research_searching":
          setPhase("searching");
          break;
        case "research_sources_found":
          setSources((event.sources as SourceSuggestion[]) ?? []);
          break;
        case "research_awaiting_approval":
          setPhase("awaiting_approval");
          break;
        case "research_ingest_start":
          setPhase("ingesting");
          break;
        case "research_ingest_complete":
          if (event.status === "ingested") {
            ingestedCountRef.current += 1;
            setTotalIngested(ingestedCountRef.current);
          }
          break;
        case "research_maintenance_start":
          setPhase("maintenance");
          break;
        case "research_maintenance_complete":
          break;
        case "research_round_complete":
          addRoundResult({
            round: event.round as number,
            sources_ingested: (event.sources_ingested as number) ?? 0,
            sources_failed: (event.sources_failed as number) ?? 0,
            new_pages: (event.new_pages as string[]) ?? [],
            failed_pages: (event.failed_pages as string[]) ?? [],
          });
          break;
        case "research_summarizing":
          setPhase("summarizing");
          clearToolActivities();
          break;
        case "research_tool_status":
          setToolStatus(event.text as string);
          break;
        case "research_tool_start":
          addToolActivity({
            toolName: event.tool_name as string,
            toolCallId: event.tool_call_id as string,
            path: (event.arguments as { path: string })?.path ?? "",
            sizeChars: 0,
            preview: "",
          });
          break;
        case "research_tool_end": {
          const resultStr = event.result as string;
          let resultData: { size_chars?: number; preview?: string } = {};
          try {
            resultData = JSON.parse(resultStr);
          } catch { /* ignore */ }
          completeToolActivity(
            event.tool_call_id as string,
            resultData.size_chars ?? 0,
            resultData.preview ?? "",
          );
          break;
        }
        case "research_final_summary":
          appendFinalReport(event.content as string);
          break;
        case "research_warnings":
          useResearchStore.getState().setWarnings(
            (event.warnings as { url: string; error: string }[]) ?? []
          );
          break;
        case "research_title":
          setResearchTitle(event.title as string);
          break;
        case "research_complete":
          setPhase("complete");
          break;
        case "research_cancelled":
          onNewResearch();
          break;
        case "research_error":
          setError(event.message as string);
          break;
      }
    },
    [
      setPhase, setCurrentRound, setTotalRounds, setSources,
      addRoundResult, appendFinalReport, setError, setTotalIngested,
      setToolStatus, addToolActivity, completeToolActivity, clearToolActivities,
      setResearchTitle, onNewResearch,
    ],
  );

  useEffect(() => {
    const { controller, events } = streamResearch(config, sessionId);
    controllerRef.current = controller;

    (async () => {
      try {
        for await (const event of events) {
          processEvent(event);
        }
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Unknown error");
      }
    })();

    return () => {
      controller.abort();
    };
  }, [config, sessionId, processEvent, setError]);

  // Save research as a chat thread when complete so it appears in history
  const savedRef = useRef(false);
  useEffect(() => {
    if (phase === "complete" && finalReport && !savedRef.current) {
      savedRef.current = true;
      const threadId = sessionId;
      const title = researchTitle || config.topic;
      const now = Date.now();

      const contextMsg = [
        `Research topic: ${config.topic}`,
        `Rounds: ${config.rounds} | Sources per round: ${config.sources_per_round}`,
        `Sources ingested: ${totalIngested}`,
        roundResults.map((r) =>
          `Round ${r.round}: ${r.sources_ingested} ingested, ${r.sources_failed} failed`
        ).join("\n"),
        warnings.length > 0
          ? `\nWarnings:\n${warnings.map((w) => `${w.url}: ${w.error}`).join("\n")}`
          : "",
      ].join("\n");

      (async () => {
        try {
          // Save locally
          await Promise.all([
            db.threads.put({
              id: threadId,
              title,
              modelType: "base",
              archived: false,
              createdAt: now,
              messageCount: 2,
            }),
            db.messages.put({
              id: `${threadId}-ctx`,
              threadId,
              role: "system",
              content: [{ type: "text", text: contextMsg }],
              createdAt: now,
            }),
            db.messages.put({
              id: `${threadId}-report`,
              threadId,
              role: "assistant",
              content: [{ type: "text", text: finalReport }],
              createdAt: now + 1,
            }),
          ]);

          setSavedThreadId(threadId);

          // Save to server immediately so messages survive refresh
          await saveThreadToServer(
            threadId,
            title,
            [
              {
                id: `${threadId}-ctx`,
                role: "system",
                content: [{ type: "text", text: contextMsg }],
                created_at: new Date(now).toISOString(),
              },
              {
                id: `${threadId}-report`,
                role: "assistant",
                content: [{ type: "text", text: finalReport }],
                created_at: new Date(now + 1).toISOString(),
              },
            ],
            now,
          );
        } catch (err) {
          console.error("Failed to save research thread:", err);
        }
      })();
    }
  }, [phase, finalReport, sessionId, config, totalIngested, roundResults, warnings, researchTitle]);

  const handleApprove = async (urls: string[]) => {
    setPhase("ingesting");
    try {
      await approveSources(sessionId, urls);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Approval failed");
    }
  };

  const handleSkipAll = async () => {
    setPhase("ingesting");
    try {
      await approveSources(sessionId, []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Approval failed");
    }
  };

  const handleCancel = async () => {
    controllerRef.current?.abort();
    try {
      await cancelResearch(sessionId);
    } catch {
      // ignore
    }
    onNewResearch();
  };

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 px-4">
        <Card className="p-6 max-w-md w-full text-center space-y-4">
          <p className="text-destructive font-medium">Error</p>
          <p className="text-sm text-muted-foreground">{error}</p>
          <Button onClick={onNewResearch}>Try Again</Button>
        </Card>
      </div>
    );
  }

  if (phase === "complete") {
    return (
      <div className="h-full overflow-y-auto px-4 py-6 max-w-3xl mx-auto space-y-4">
        {warnings.length > 0 && (
          <Card className="p-4 border-amber-500/50 bg-amber-500/5">
            <h3 className="text-sm font-semibold text-amber-600 dark:text-amber-400 mb-2">
              Skipped Sources
            </h3>
            <p className="text-xs text-muted-foreground mb-3">
              The following sources could not be ingested automatically. You may
              want to download and add them manually via the wiki file upload.
            </p>
            <ul className="space-y-2">
              {warnings.map((w) => (
                <li key={w.url} className="text-xs space-y-0.5">
                  <a
                    href={w.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary underline break-all"
                  >
                    {w.url}
                  </a>
                  <p className="text-muted-foreground">{w.error}</p>
                </li>
              ))}
            </ul>
          </Card>
        )}
        {roundResults.map((r) => (
          <ResearchRoundSummary key={r.round} result={r} />
        ))}
        <ResearchFinalReport
          content={finalReport}
          topic={config.topic}
          totalIngested={totalIngested}
          onNewResearch={onNewResearch}
        />
        {savedThreadId && (
          <div className="flex justify-center pb-8">
            <Button
              variant="default"
              onClick={() =>
                navigate({ to: "/chat", search: { thread: savedThreadId } })
              }
            >
              Continue in Chat
            </Button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto px-4 py-6 max-w-3xl mx-auto space-y-4">
      <ResearchProgressBar
        phase={phase}
        currentRound={currentRound}
        totalRounds={totalRounds}
        sourcesIngested={totalIngested}
      />

      {phase === "awaiting_approval" && sources.length > 0 && (
        <SourceApprovalPanel
          sources={sources}
          round={currentRound}
          onApprove={handleApprove}
          onSkipAll={handleSkipAll}
        />
      )}

      {phase === "surveying" && (
        <Card className="p-6 space-y-3">
          {toolStatus && (
            <div className="text-sm text-muted-foreground">{toolStatus}</div>
          )}
          {toolActivities.filter((a) => a.toolCallId !== "").length > 0 && (
            <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
              {toolActivities
                .filter((a) => a.toolCallId !== "")
                .map((a) => (
                  <div
                    key={a.toolCallId}
                    className="text-xs border rounded-md p-2 bg-muted/30"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-medium truncate flex-1">
                        {a.path || "..."}
                      </span>
                      {a.sizeChars > 0 && (
                        <span className="text-muted-foreground shrink-0">
                          {a.sizeChars.toLocaleString()} chars
                        </span>
                      )}
                    </div>
                    {a.preview && (
                      <div className="text-muted-foreground mt-1 truncate">
                        {a.preview}
                      </div>
                    )}
                  </div>
                ))}
            </div>
          )}
          {!toolStatus && !toolActivities.length && (
            <div className="animate-pulse text-muted-foreground">
              Surveying existing wiki knowledge...
            </div>
          )}
        </Card>
      )}

      {phase === "searching" && (
        <Card className="p-6 text-center space-y-3">
          <div className="animate-pulse text-muted-foreground">
            Searching for sources (Round {currentRound}/{totalRounds})...
          </div>
        </Card>
      )}

      {phase === "ingesting" && (
        <Card className="p-6 text-center space-y-3">
          <div className="animate-pulse text-muted-foreground">
            Ingesting sources into wiki...
          </div>
        </Card>
      )}

      {phase === "maintenance" && (
        <Card className="p-6 text-center space-y-3">
          <div className="animate-pulse text-muted-foreground">
            Running maintenance cycle (backlinks, enrichment, community detection)...
          </div>
        </Card>
      )}

      {phase === "summarizing" && (
        <Card className="p-6 space-y-3">
          {toolStatus && (
            <div className="text-sm text-muted-foreground">{toolStatus}</div>
          )}
          {toolActivities.filter((a) => a.toolCallId !== "").length > 0 && (
            <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
              {toolActivities
                .filter((a) => a.toolCallId !== "")
                .map((a) => (
                  <div
                    key={a.toolCallId}
                    className="text-xs border rounded-md p-2 bg-muted/30"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-medium truncate flex-1">
                        {a.path || "..."}
                      </span>
                      {a.sizeChars > 0 && (
                        <span className="text-muted-foreground shrink-0">
                          {a.sizeChars.toLocaleString()} chars
                        </span>
                      )}
                    </div>
                    {a.preview && (
                      <div className="text-muted-foreground mt-1 truncate">
                        {a.preview}
                      </div>
                    )}
                  </div>
                ))}
            </div>
          )}
          {finalReport ? (
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <div className="whitespace-pre-wrap leading-relaxed">
                {finalReport}
              </div>
            </div>
          ) : (
            !toolStatus && (
              <div className="animate-pulse text-muted-foreground">
                Generating final research summary...
              </div>
            )
          )}
        </Card>
      )}

      {/* Already-completed round summaries */}
      {roundResults.map((r) => (
        <ResearchRoundSummary key={r.round} result={r} />
      ))}

      <div className="flex justify-center pt-2">
        <Button variant="outline" size="sm" onClick={handleCancel}>
          Cancel Research
        </Button>
      </div>
    </div>
  );
}
