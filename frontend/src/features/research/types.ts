/** Research Mode type definitions. */

export interface ResearchConfig {
  topic: string;
  rounds: number;
  sources_per_round: number;
  auto_mode: boolean;
  trusted_sources: string[];
  blocked_sources: string[];
  research_depth: "shallow" | "standard" | "deep" | "custom";
  source_types: string[];
  timelimit: string;
  periodic: boolean;
  periodic_interval: "hourly" | "daily" | "weekly" | "monthly";
  periodic_hour: number | null;
  periodic_dow: number | null;  // 0=Mon..6=Sun, for weekly
  periodic_dom: number | null;  // 1-31, for monthly (clamped to last day of month)
}

export const DOW_OPTIONS = [
  { value: 0, label: "Monday" },
  { value: 1, label: "Tuesday" },
  { value: 2, label: "Wednesday" },
  { value: 3, label: "Thursday" },
  { value: 4, label: "Friday" },
  { value: 5, label: "Saturday" },
  { value: 6, label: "Sunday" },
];

export const TIMELIMIT_OPTIONS = [
  { value: "all", label: "Any time" },
  { value: "d", label: "Past 24 hours" },
  { value: "w", label: "Past week" },
  { value: "m", label: "Past month" },
  { value: "y", label: "Past year" },
];

export const INTERVAL_OPTIONS = [
  { value: "hourly", label: "Every Hour" },
  { value: "daily", label: "Every Day" },
  { value: "weekly", label: "Every Week" },
  { value: "monthly", label: "Every Month" },
];

export interface PeriodicConfig {
  id: string;
  topic: string;
  interval_type: string;
  enabled: boolean;
  run_hour: number | null;
  run_dow: number | null;
  run_dom: number | null;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
  trusted_count: number;
  rounds: number;
  sources_per_round: number;
}

/** Full periodic config returned by GET single endpoint — used for editing. */
export interface FullPeriodicConfig extends PeriodicConfig {
  trusted_sources: string[];
  blocked_sources: string[];
  research_depth: string;
  source_types: string[];
  timelimit: string;
}

export interface SourceSuggestion {
  url: string;
  title: string;
  snippet: string;
  source_type: "paper" | "webpage" | "youtube" | "tweet" | "pdf";
  is_trusted: boolean;
  relevance: number;
  already_in_wiki: boolean;
}

export type ResearchPhase =
  | "idle"
  | "setup"
  | "surveying"
  | "searching"
  | "awaiting_approval"
  | "ingesting"
  | "maintenance"
  | "summarizing"
  | "complete"
  | "error"
  | "cancelled";

export interface RoundResult {
  round: number;
  sources_ingested: number;
  sources_failed: number;
  new_pages: string[];
  failed_pages: string[];
}

export interface ResearchState {
  config: ResearchConfig | null;
  sessionId: string | null;
  phase: ResearchPhase;
  currentRound: number;
  totalRounds: number;
  sources: SourceSuggestion[];
  roundResults: RoundResult[];
  finalReport: string;
  error: string | null;
  surveyContent: string;
  maintenanceSteps: Record<string, unknown>;
  totalIngested: number;
  warnings: { url: string; error: string }[];
  toolStatus: string;
  toolActivities: ToolActivity[];
  researchTitle: string;
}

export type ResearchEventType =
  | "research_started"
  | "research_survey"
  | "research_round_start"
  | "research_searching"
  | "research_sources_found"
  | "research_awaiting_approval"
  | "research_ingest_start"
  | "research_ingest_complete"
  | "research_maintenance_start"
  | "research_maintenance_progress"
  | "research_maintenance_complete"
  | "research_round_complete"
  | "research_summarizing"
  | "research_final_summary"
  | "research_tool_status"
  | "research_tool_start"
  | "research_tool_end"
  | "research_title"
  | "research_complete"
  | "research_warnings"
  | "research_cancelled"
  | "research_error";

export interface ToolActivity {
  toolName: string;
  toolCallId: string;
  path: string;
  sizeChars: number;
  preview: string;
}

export interface ResearchEvent {
  type: ResearchEventType;
  [key: string]: unknown;
}

export const DEPTH_PRESETS: Record<
  string,
  { label: string; rounds: number; sources_per_round: number }
> = {
  shallow: { label: "Shallow (2 rounds, 10 sources)", rounds: 2, sources_per_round: 10 },
  standard: { label: "Standard (3 rounds, 15 sources)", rounds: 3, sources_per_round: 15 },
  deep: { label: "Deep (5 rounds, 50 sources)", rounds: 5, sources_per_round: 50 },
  custom: { label: "Custom", rounds: 3, sources_per_round: 15 },
};

export const SOURCE_TYPE_OPTIONS = [
  { value: "paper", label: "Papers" },
  { value: "webpage", label: "Webpages" },
  { value: "youtube", label: "YouTube" },
  { value: "tweet", label: "Tweets" },
  { value: "pdf", label: "PDFs" },
];

export function defaultResearchConfig(): ResearchConfig {
  return {
    topic: "",
    rounds: 2,
    sources_per_round: 10,
    auto_mode: false,
    trusted_sources: [],
    blocked_sources: [],
    research_depth: "standard",
    source_types: [],
    timelimit: "m",
    periodic: false,
    periodic_interval: "daily",
    periodic_hour: null,
    periodic_dow: null,
    periodic_dom: null,
  };
}
