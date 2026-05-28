import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import type { ResearchPhase } from "../types";

interface Props {
  phase: ResearchPhase;
  currentRound: number;
  totalRounds: number;
  sourcesIngested: number;
}

const PHASE_LABELS: Record<ResearchPhase, string> = {
  idle: "Idle",
  setup: "Setup",
  surveying: "Surveying wiki...",
  searching: "Searching for sources...",
  awaiting_approval: "Awaiting approval...",
  ingesting: "Ingesting sources...",
  maintenance: "Running maintenance...",
  summarizing: "Generating summary...",
  complete: "Complete",
  error: "Error",
  cancelled: "Cancelled",
};

export function ResearchProgressBar({
  phase,
  currentRound,
  totalRounds,
  sourcesIngested,
}: Props) {
  const progress =
    phase === "complete"
      ? 100
      : totalRounds > 0
        ? Math.round((currentRound / totalRounds) * 100)
        : 0;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center gap-2">
          <span className="font-medium">
            {phase === "complete" ? "Research Complete" : `Round ${currentRound} of ${totalRounds}`}
          </span>
          <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
            {PHASE_LABELS[phase] ?? phase}
          </Badge>
        </div>
        <span className="text-muted-foreground text-xs">
          {sourcesIngested} sources ingested
        </span>
      </div>
      <Progress value={progress} className="h-2" />
    </div>
  );
}
