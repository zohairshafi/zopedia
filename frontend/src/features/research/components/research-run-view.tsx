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
import { debouncedSaveThreadToServer } from "@/features/chat/chat-server-sync";
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

  const setPhase = useResearchStore((s) => s.setPhase);
  const setCurrentRound = useResearchStore((s) => s.setCurrentRound);
  const setTotalRounds = useResearchStore((s) => s.setTotalRounds);
  const setSources = useResearchStore((s) => s.setSources);
  const addRoundResult = useResearchStore((s) => s.addRoundResult);
  const appendFinalReport = useResearchStore((s) => s.appendFinalReport);
  const setError = useResearchStore((s) => s.setError);
  const setTotalIngested = useResearchStore((s) => s.setTotalIngested);

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
          setPhase("searching");
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
          break;
        case "research_final_summary":
          appendFinalReport(event.content as string);
          break;
        case "research_warnings":
          useResearchStore.getState().setWarnings(
            (event.warnings as { url: string; error: string }[]) ?? []
          );
          break;
        case "research_complete":
          setPhase("complete");
          break;
        case "research_cancelled":
          setError("Research was cancelled.");
          break;
        case "research_error":
          setError(event.message as string);
          break;
      }
    },
    [
      setPhase, setCurrentRound, setTotalRounds, setSources,
      addRoundResult, appendFinalReport, setError, setTotalIngested,
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
      const topic = config.topic;
      const now = Date.now();

      const contextMsg = [
        `Research topic: ${topic}`,
        `Rounds: ${config.rounds} | Sources per round: ${config.sources_per_round}`,
        `Sources ingested: ${totalIngested}`,
        roundResults.map((r) =>
          `Round ${r.round}: ${r.sources_ingested} ingested, ${r.sources_failed} failed`
        ).join("\n"),
        warnings.length > 0
          ? `\nWarnings:\n${warnings.map((w) => `${w.url}: ${w.error}`).join("\n")}`
          : "",
      ].join("\n");

      Promise.all([
        db.threads.put({
          id: threadId,
          title: topic,
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
      ]).then(() => {
        setSavedThreadId(threadId);
        // Push to server so it persists across devices
        debouncedSaveThreadToServer(threadId);
      }).catch((err) => {
        console.error("Failed to save research thread:", err);
      });
    }
  }, [phase, finalReport, sessionId, config, totalIngested, roundResults, warnings]);

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
    setError("Research cancelled.");
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

      {(phase === "searching" || phase === "surveying") && (
        <Card className="p-6 text-center space-y-3">
          <div className="animate-pulse text-muted-foreground">
            {phase === "surveying"
              ? "Surveying existing wiki knowledge..."
              : `Searching for sources (Round ${currentRound}/${totalRounds})...`}
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
          <div className="animate-pulse text-muted-foreground">
            Generating final research summary...
          </div>
          {finalReport && (
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <div className="whitespace-pre-wrap leading-relaxed">
                {finalReport}
              </div>
            </div>
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
