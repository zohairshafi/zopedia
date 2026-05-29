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
  SOURCE_TYPE_OPTIONS,
  TIMELIMIT_OPTIONS,
  type ResearchConfig,
  defaultResearchConfig,
} from "../types";

interface Props {
  onStart: (config: ResearchConfig) => void;
  loading?: boolean;
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

export function ResearchSetupForm({ onStart, loading }: Props) {
  const prefs = loadPrefs();
  const [config, setConfig] = useState<ResearchConfig>(() => ({
    ...defaultResearchConfig(),
    source_types: prefs.sourceTypes,
  }));
  const [trustedText, setTrustedText] = useState(prefs.trusted);
  const [blockedText, setBlockedText] = useState(prefs.blocked);

  const handleStart = () => {
    if (!config.topic.trim()) return;
    savePrefs(trustedText, blockedText, config.source_types);
    onStart({
      ...config,
      trusted_sources: trustedText
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
      blocked_sources: blockedText
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
    });
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
            New Research Project
          </h2>
          <p className="text-sm text-muted-foreground">
            Enter a topic and Zopedia will search the web, suggest sources,
            ingest them into your wiki, and produce a research summary.
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
          disabled={!config.topic.trim() || loading}
          onClick={handleStart}
        >
          {loading ? "Starting..." : "Start Research"}
        </Button>
      </Card>
    </div>
  );
}
