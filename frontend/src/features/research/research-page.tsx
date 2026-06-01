import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Loader2 } from "lucide-react";
import { ResearchSetupForm } from "./components/research-setup-form";
import { ResearchRunView } from "./components/research-run-view";
import { useResearchStore } from "./stores/research-store";
import {
  listPeriodicResearch,
  deletePeriodicResearch,
  runPeriodicResearchNow,
  getPeriodicResearch,
  togglePeriodicResearch,
} from "./api/research-api";
import type { FullPeriodicConfig, PeriodicConfig, ResearchConfig } from "./types";

function createSessionId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function intervalLabel(pc: PeriodicConfig): string {
  const base = pc.interval_type;
  const parts: string[] = [];
  if (pc.run_hour !== null && pc.run_hour !== undefined) {
    parts.push(`${String(pc.run_hour).padStart(2, "0")}:00 UTC`);
  }
  if (pc.interval_type === "weekly" && pc.run_dow !== null && pc.run_dow !== undefined) {
    const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    parts.push(days[pc.run_dow] ?? "");
  }
  if (pc.interval_type === "monthly" && pc.run_dom !== null && pc.run_dom !== undefined) {
    parts.push(`${pc.run_dom}${pc.run_dom === 1 ? "st" : pc.run_dom === 2 ? "nd" : pc.run_dom === 3 ? "rd" : "th"}`);
  }
  return parts.length > 0 ? `${base} (${parts.join(", ")})` : base;
}

function PeriodicConfigCard({
  pc,
  onDelete,
  onRunNow,
  onToggle,
  onEdit,
  isRunning,
}: {
  pc: PeriodicConfig;
  onDelete: (id: string) => void;
  onRunNow: (id: string) => void;
  onToggle: (id: string, enabled: boolean) => void;
  onEdit: (id: string) => void;
  isRunning?: boolean;
}) {
  const nextRun = pc.next_run_at
    ? new Date(pc.next_run_at).toLocaleString()
    : "—";
  const lastRun = pc.last_run_at
    ? new Date(pc.last_run_at).toLocaleString()
    : "Never";

  return (
    <Card className={`p-4 space-y-2 text-sm ${!pc.enabled ? "opacity-60" : ""}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium truncate">{pc.topic}</span>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-muted-foreground">
            {intervalLabel(pc)}
          </span>
          <Switch
            checked={pc.enabled}
            onCheckedChange={(v) => onToggle(pc.id, v)}
          />
        </div>
      </div>
      <div className="text-xs text-muted-foreground space-y-0.5">
        <div>
          {pc.rounds} rounds × {pc.sources_per_round} sources
          {pc.trusted_count > 0 && ` · ${pc.trusted_count} trusted`}
        </div>
        <div>Next run: {nextRun}</div>
        <div>Last run: {lastRun}</div>
      </div>
      <div className="flex gap-2 pt-1">
        <Button
          size="sm"
          variant="outline"
          disabled={isRunning}
          onClick={() => onRunNow(pc.id)}
        >
          {isRunning ? (
            <>
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
              Running…
            </>
          ) : (
            "Run Now"
          )}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => onEdit(pc.id)}
        >
          Edit
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => onDelete(pc.id)}
        >
          Delete
        </Button>
      </div>
    </Card>
  );
}

export function ResearchPage() {
  const navigate = useNavigate();
  const config = useResearchStore((s) => s.config);
  const sessionId = useResearchStore((s) => s.sessionId);
  const setConfig = useResearchStore((s) => s.setConfig);
  const setSessionId = useResearchStore((s) => s.setSessionId);
  const reset = useResearchStore((s) => s.reset);
  const [periodicConfigs, setPeriodicConfigs] = useState<PeriodicConfig[]>([]);
  const [editingConfig, setEditingConfig] = useState<FullPeriodicConfig | null>(null);
  const [runningIds, setRunningIds] = useState<Set<string>>(new Set());
  const runningTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const refreshPeriodic = useCallback(async () => {
    try {
      const list = await listPeriodicResearch();
      setPeriodicConfigs(list);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    if (!config || !sessionId) {
      void refreshPeriodic();
    }
  }, [config, sessionId, refreshPeriodic]);

  const handleStart = useCallback(
    async (cfg: ResearchConfig) => {
      if (cfg.periodic) {
        await refreshPeriodic();
        return;
      }
      const sid = createSessionId();
      setConfig(cfg);
      setSessionId(sid);
    },
    [setConfig, setSessionId, refreshPeriodic],
  );

  const handleDelete = useCallback(
    async (id: string) => {
      await deletePeriodicResearch(id);
      await refreshPeriodic();
    },
    [refreshPeriodic],
  );

  const handleToggle = useCallback(
    async (id: string, enabled: boolean) => {
      await togglePeriodicResearch(id, enabled);
      await refreshPeriodic();
    },
    [refreshPeriodic],
  );

  const handleEdit = useCallback(async (id: string) => {
    try {
      const full = await getPeriodicResearch(id);
      setEditingConfig(full);
    } catch (err) {
      console.error("Failed to load config for editing:", err);
    }
  }, []);

  const handleUpdated = useCallback(() => {
    setEditingConfig(null);
    refreshPeriodic();
  }, [refreshPeriodic]);

  const handleCancelEdit = useCallback(() => {
    setEditingConfig(null);
  }, []);

  const handleRunNow = useCallback(async (id: string) => {
    // Mark as running
    setRunningIds((prev) => new Set(prev).add(id));
    try {
      await runPeriodicResearchNow(id);
    } catch {
      // ignore — backend still may have started it
    }
    // Keep "Running..." visible briefly, then refresh to pick up last_run_at
    const timer = setTimeout(() => {
      setRunningIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      runningTimers.current.delete(id);
      refreshPeriodic();
    }, 3000);
    runningTimers.current.set(id, timer);
  }, [refreshPeriodic]);

  const handleNewResearch = useCallback(() => {
    reset();
    navigate({ to: "/research", search: { new: createSessionId() } });
  }, [reset, navigate]);

  if (config && sessionId) {
    return (
      <ResearchRunView
        config={config}
        sessionId={sessionId}
        onNewResearch={handleNewResearch}
      />
    );
  }

  // Show edit form when editing a periodic config
  if (editingConfig) {
    return (
      <div className="flex flex-col items-center px-4 py-8 gap-4">
        <ResearchSetupForm
          onStart={handleStart}
          onUpdated={handleUpdated}
          editConfig={editingConfig}
        />
        <Button variant="ghost" size="sm" onClick={handleCancelEdit}>
          Cancel editing
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center px-4 py-8 gap-8">
      <ResearchSetupForm onStart={handleStart} />
      {periodicConfigs.length > 0 && (
        <div className="w-full max-w-xl space-y-3">
          <h3 className="text-sm font-semibold text-muted-foreground">
            Scheduled Research
          </h3>
          <div className="space-y-2">
            {periodicConfigs.map((pc) => (
              <PeriodicConfigCard
                key={pc.id}
                pc={pc}
                onDelete={handleDelete}
                onRunNow={handleRunNow}
                onToggle={handleToggle}
                onEdit={handleEdit}
                isRunning={runningIds.has(pc.id)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
