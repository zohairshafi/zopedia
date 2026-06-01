import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  DEPTH_PRESETS,
  DOW_OPTIONS,
  INTERVAL_OPTIONS,
  SOURCE_TYPE_OPTIONS,
  TIMELIMIT_OPTIONS,
  type ResearchConfig,
  defaultResearchConfig,
} from "../types";
import { createPeriodicResearch, updatePeriodicResearch } from "../api/research-api";
import type { FullPeriodicConfig } from "../types";

interface Props {
  onStart: (config: ResearchConfig) => void;
  onUpdated?: () => void;
  loading?: boolean;
  editConfig?: FullPeriodicConfig | null;
}

const STORAGE_KEY = "zopedia-research-prefs";

function loadPrefs(): { trusted: string; blocked: string; sourceTypes: string[] } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return { trusted: "", blocked: "", sourceTypes: [] };
}

function savePrefs(trusted: string, blocked: string, sourceTypes: string[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ trusted, blocked, sourceTypes }));
  } catch { /* ignore */ }
}

export function ResearchSetupForm({ onStart, onUpdated, loading, editConfig }: Props) {
  const prefs = loadPrefs();
  const editing = !!editConfig;

  const [config, setConfig] = useState<ResearchConfig>(() => {
    if (editConfig) {
      return {
        ...defaultResearchConfig(),
        topic: editConfig.topic,
        rounds: editConfig.rounds,
        sources_per_round: editConfig.sources_per_round,
        auto_mode: true,
        trusted_sources: editConfig.trusted_sources,
        research_depth: editConfig.research_depth as ResearchConfig["research_depth"],
        source_types: editConfig.source_types,
        timelimit: editConfig.timelimit,
        periodic: true,
        periodic_interval: editConfig.interval_type as ResearchConfig["periodic_interval"],
        periodic_hour: editConfig.run_hour ?? null,
        periodic_dow: editConfig.run_dow ?? null,
        periodic_dom: editConfig.run_dom ?? null,
      };
    }
    return { ...defaultResearchConfig(), source_types: prefs.sourceTypes };
  });
  const [trustedText, setTrustedText] = useState(
    editConfig ? editConfig.trusted_sources.join("\n") : prefs.trusted,
  );
  const [blockedText, setBlockedText] = useState(
    editConfig ? editConfig.blocked_sources.join("\n") : prefs.blocked,
  );
  const [periodicLoading, setPeriodicLoading] = useState(false);

  const handleStart = async () => {
    if (!config.topic.trim()) return;
    const fullConfig: ResearchConfig = {
      ...config,
      trusted_sources: trustedText
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
      blocked_sources: blockedText
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
    };
    savePrefs(trustedText, blockedText, config.source_types);

    if (config.periodic) {
      setPeriodicLoading(true);
      try {
        if (editing) {
          await updatePeriodicResearch(editConfig!.id, fullConfig);
          onUpdated?.();
        } else {
          await createPeriodicResearch(fullConfig);
          // Clear topic as feedback and tell parent to refresh the list
          setConfig((c) => ({ ...c, topic: "" }));
          onStart(fullConfig);
        }
      } catch (err) {
        console.error("Failed to save periodic research:", err);
      } finally {
        setPeriodicLoading(false);
      }
      return;
    }

    onStart(fullConfig);
  };

  const applyDepth = (depth: string) => {
    const preset = DEPTH_PRESETS[depth];
    setConfig((c) => ({
      ...c,
      research_depth: depth as ResearchConfig["research_depth"],
      rounds: preset.rounds,
      sources_per_round: preset.sources_per_round,
    }));
  };

  return (
    <div className="flex flex-col items-center px-4 py-8">
      <Card className="w-full max-w-xl p-6 space-y-6">
        <div className="space-y-1.5">
          <h2 className="text-xl font-semibold tracking-tight">
            {editing ? "Edit Periodic Research" : "New Research Project"}
          </h2>
          <p className="text-sm text-muted-foreground">
            {editing
              ? "Update the research topic, schedule, and source configuration."
              : "Enter a topic and Zopedia will search the web, suggest sources, ingest them into your wiki, and produce a research summary."}
          </p>
        </div>

        {/* Topic */}
        <div className="space-y-2">
          <Label htmlFor="topic">Research Topic</Label>
          <Input
            id="topic"
            placeholder="e.g., Recent advances in machine learning for protein folding"
            value={config.topic}
            onChange={(e) =>
              setConfig((c) => ({ ...c, topic: e.target.value }))
            }
            onKeyDown={(e) => {
              if (e.key === "Enter" && config.topic.trim()) handleStart();
            }}
          />
        </div>

        {/* Depth preset */}
        <div className="space-y-2">
          <Label>Research Depth</Label>
          <p className="text-sm text-muted-foreground">
            Select the depth of research. This will determine the number of rounds
            and sources per round. Recommended to have fewer rounds with higher number of sources.
          </p>
          <Select value={config.research_depth} onValueChange={applyDepth}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(DEPTH_PRESETS).map(([key, preset]) => (
                <SelectItem key={key} value={key}>
                  {preset.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Customize rounds and sources */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="rounds">Rounds</Label>
            <Input
              id="rounds"
              type="number"
              min={1}
              max={10}
              value={config.rounds}
              disabled={config.research_depth !== "custom"}
              onChange={(e) =>
                setConfig((c) => ({
                  ...c,
                  rounds: Math.max(1, parseInt(e.target.value) || 1),
                  research_depth: "custom",
                }))
              }
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="sources">Sources per Round</Label>
            <Input
              id="sources"
              type="number"
              min={1}
              max={30}
              value={config.sources_per_round}
              disabled={config.research_depth !== "custom"}
              onChange={(e) =>
                setConfig((c) => ({
                  ...c,
                  sources_per_round: Math.max(1, parseInt(e.target.value) || 1),
                  research_depth: "custom",
                }))
              }
            />
          </div>
        </div>

        {/* Auto mode */}
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label>Auto Mode</Label>
            <p className="text-sm text-muted-foreground">
              Ingest sources automatically without approval between rounds
            </p>
          </div>
          <Switch
            checked={config.auto_mode}
            onCheckedChange={(v) =>
              setConfig((c) => ({ ...c, auto_mode: v }))
            }
          />
        </div>

        {/* Source type filter */}
        <div className="space-y-2">
          <Label>Source Types (empty = all)</Label>
          <ToggleGroup
            type="multiple"
            variant="outline"
            value={config.source_types}
            onValueChange={(v) =>
              setConfig((c) => ({ ...c, source_types: v }))
            }
            className="justify-start flex-wrap"
          >
            {SOURCE_TYPE_OPTIONS.map((opt) => (
              <ToggleGroupItem key={opt.value} value={opt.value}>
                {opt.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>

        {/* Time sensitivity */}
        <div className="space-y-2">
          <Label>Time Sensitivity</Label>
          <p className="text-sm text-muted-foreground">
            Filter search results to a specific time window
          </p>
          <Select
            value={config.timelimit}
            onValueChange={(v) =>
              setConfig((c) => ({ ...c, timelimit: v }))
            }
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TIMELIMIT_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Periodic research */}
        <div className="space-y-3 border rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Run Periodically</Label>
              <p className="text-sm text-muted-foreground">
                Re-run this research automatically at a set interval
              </p>
            </div>
            <Switch
              checked={config.periodic}
              onCheckedChange={(v) =>
                setConfig((c) => ({
                  ...c,
                  periodic: v,
                  auto_mode: v ? true : c.auto_mode,
                }))
              }
            />
          </div>

          {config.periodic && (
            <>
              <div className="space-y-1.5">
                <Label className="text-xs">Interval</Label>
                <Select
                  value={config.periodic_interval}
                  onValueChange={(v) =>
                    setConfig((c) => ({
                      ...c,
                      periodic_interval: v as ResearchConfig["periodic_interval"],
                    }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {INTERVAL_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {config.periodic_interval !== "hourly" && (
                <div className="space-y-1.5">
                  <Label className="text-xs">At Hour (UTC)</Label>
                  <Select
                    value={
                      config.periodic_hour !== null
                        ? String(config.periodic_hour)
                        : "any"
                    }
                    onValueChange={(v) =>
                      setConfig((c) => ({
                        ...c,
                        periodic_hour:
                          v === "any" ? null : parseInt(v),
                      }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Any time" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="any">Any time</SelectItem>
                      {Array.from({ length: 24 }, (_, i) => (
                        <SelectItem key={i} value={String(i)}>
                          {String(i).padStart(2, "0")}:00 UTC
                          {i === 0
                            ? " (midnight)"
                            : i === 12
                              ? " (noon)"
                              : ""}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {config.periodic_interval === "weekly" && (
                <div className="space-y-1.5">
                  <Label className="text-xs">Day of Week</Label>
                  <Select
                    value={
                      config.periodic_dow !== null
                        ? String(config.periodic_dow)
                        : "any"
                    }
                    onValueChange={(v) =>
                      setConfig((c) => ({
                        ...c,
                        periodic_dow:
                          v === "any" ? null : parseInt(v),
                      }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Any day" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="any">Any day</SelectItem>
                      {DOW_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={String(opt.value)}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {config.periodic_interval === "monthly" && (
                <div className="space-y-1.5">
                  <Label className="text-xs">Day of Month</Label>
                  <Select
                    value={
                      config.periodic_dom !== null
                        ? String(config.periodic_dom)
                        : "any"
                    }
                    onValueChange={(v) =>
                      setConfig((c) => ({
                        ...c,
                        periodic_dom:
                          v === "any" ? null : parseInt(v),
                      }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Any day" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="any">Any day</SelectItem>
                      {Array.from({ length: 28 }, (_, i) => (
                        <SelectItem key={i + 1} value={String(i + 1)}>
                          {i + 1}
                          {i + 1 === 1
                            ? "st"
                            : i + 1 === 2
                              ? "nd"
                              : i + 1 === 3
                                ? "rd"
                                : "th"}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {!config.auto_mode && (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  Periodic runs always use auto-ingest mode (sources are
                  approved automatically).
                </p>
              )}

              {config.trusted_sources.length === 0 &&
              !trustedText.trim() ? (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  No trusted sources configured. During periodic runs, only
                  trusted sources will be ingested to control token costs.
                  Add trusted domains above.
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Periodic runs only ingest from trusted sources and skip
                  previously ingested URLs.
                </p>
              )}
            </>
          )}
        </div>

        {/* Trusted sources */}
        <div className="space-y-2">
          <Label>Trusted Sources</Label>
          <p className="text-xs text-muted-foreground">
            One per line: domains (arxiv.org), channels (youtube.com/@channel),
            accounts
          </p>
          <Textarea
            rows={3}
            placeholder={"arxiv.org\nbiorxiv.org"}
            value={trustedText}
            onChange={(e) => setTrustedText(e.target.value)}
          />
        </div>

        {/* Blocked sources */}
        <div className="space-y-2">
          <Label>Blocked Sources</Label>
          <p className="text-xs text-muted-foreground">
            Domains or URLs to exclude from search results
          </p>
          <Textarea
            rows={2}
            placeholder={"paywall-news.com"}
            value={blockedText}
            onChange={(e) => setBlockedText(e.target.value)}
          />
        </div>

        <Button
          className="w-full"
          size="lg"
          disabled={!config.topic.trim() || loading || periodicLoading}
          onClick={handleStart}
        >
          {periodicLoading
            ? "Saving..."
            : loading
              ? "Starting..."
              : editing
                ? "Update Research"
                : config.periodic
                  ? "Schedule Research"
                  : "Start Research"}
        </Button>
      </Card>
    </div>
  );
}
