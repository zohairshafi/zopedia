import { useEffect, useMemo, useState } from "react";
import { authFetch } from "@/features/auth";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { Delete02Icon, LicenseMaintenanceIcon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { Loader2 } from "lucide-react";

// ── Types ───────────────────────────────────────────────────────────

type MaintenanceSchedule = {
  id: string;
  username: string;
  enabled: boolean | number;
  interval_type: "hourly" | "daily" | "weekly" | "monthly";
  with_web_fill: boolean | number;
  run_hour: number | null;
  run_dow: number | null;
  run_dom: number | null;
  created_at: string;
  last_run_at: string | null;
  next_run_at: string | null;
};

const INTERVAL_LABELS: Record<string, string> = {
  hourly: "Hourly",
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
};

function fmtNextRun(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ── Component ────────────────────────────────────────────────────────

interface ScheduledMaintenanceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ScheduledMaintenanceDialog({
  open,
  onOpenChange,
}: ScheduledMaintenanceDialogProps) {
  const [schedules, setSchedules] = useState<MaintenanceSchedule[]>([]);
  const [loading, setLoading] = useState(false);
  const [runningMode, setRunningMode] = useState<string | null>(null);

  // ── Create form state ─────────────────────────────────────────
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formInterval, setFormInterval] = useState("daily");
  const [formHour, setFormHour] = useState("");
  const [formDow, setFormDow] = useState("");
  const [formDom, setFormDom] = useState("");
  const [formWebFill, setFormWebFill] = useState(false);

  async function fetchSchedules() {
    setLoading(true);
    try {
      const res = await authFetch("/api/inference/wiki/maintenance/scheduled");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSchedules(data.schedules ?? []);
    } catch (err) {
      toast.error("Failed to load schedules", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (open) {
      fetchSchedules();
      setShowForm(false);
    }
  }, [open]);

  async function handleSubmit() {
    const payload = {
      interval_type: formInterval,
      with_web_fill: formWebFill,
      run_hour: formHour ? Number(formHour) : null,
      run_dow: formDow ? Number(formDow) : null,
      run_dom: formDom ? Number(formDom) : null,
    };

    try {
      let res: Response;
      if (editingId) {
        res = await authFetch(
          `/api/inference/wiki/maintenance/scheduled/${editingId}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
        );
      } else {
        res = await authFetch("/api/inference/wiki/maintenance/scheduled", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast.success(editingId ? "Schedule updated" : "Schedule created");
      setShowForm(false);
      setEditingId(null);
      fetchSchedules();
    } catch (err) {
      toast.error("Failed to save schedule", {
        description: err instanceof Error ? err.message : undefined,
      });
    }
  }

  function openEdit(s: MaintenanceSchedule) {
    setEditingId(s.id);
    setFormInterval(s.interval_type);
    setFormHour(s.run_hour?.toString() ?? "");
    setFormDow(s.run_dow?.toString() ?? "");
    setFormDom(s.run_dom?.toString() ?? "");
    setFormWebFill(Boolean(s.with_web_fill));
    setShowForm(true);
  }

  function openCreate() {
    setEditingId(null);
    setFormInterval("daily");
    setFormHour("");
    setFormDow("");
    setFormDom("");
    setFormWebFill(false);
    setShowForm(true);
  }

  async function handleToggle(s: MaintenanceSchedule) {
    try {
      const res = await authFetch(
        `/api/inference/wiki/maintenance/scheduled/${s.id}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            enabled: !Boolean(s.enabled),
          }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      fetchSchedules();
    } catch (err) {
      toast.error("Failed to toggle schedule", {
        description: err instanceof Error ? err.message : undefined,
      });
    }
  }

  async function handleDelete(s: MaintenanceSchedule) {
    if (!window.confirm("Delete this maintenance schedule?")) return;
    try {
      const res = await authFetch(
        `/api/inference/wiki/maintenance/scheduled/${s.id}`,
        { method: "DELETE" },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast.success("Schedule deleted");
      fetchSchedules();
    } catch (err) {
      toast.error("Failed to delete", {
        description: err instanceof Error ? err.message : undefined,
      });
    }
  }

  async function handleRunNow(mode: "with-web-fill" | "without-web-fill") {
    setRunningMode(mode);

    // If no schedules exist, just run maintenance directly (one-off).
    if (schedules.length === 0) {
      try {
        const res = await authFetch("/api/inference/wiki/merge-maintenance", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dry_run: false }),
        });
        if (!res.ok) throw new Error(`Merge failed: HTTP ${res.status}`);

        await authFetch("/api/inference/wiki/retry-fallback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dry_run: false }),
        });
        await authFetch("/api/inference/wiki/enrich", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            dry_run: false,
            fill_gaps_from_web: mode === "with-web-fill",
            ...(mode === "with-web-fill" ? { max_web_gap_queries: 8 } : {}),
          }),
        });
        await authFetch("/api/inference/wiki/rebuild-index", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dry_run: false, max_links_per_page: 128 }),
        });
        toast.success("Maintenance completed");
      } catch (err) {
        toast.error("Maintenance failed", {
          description: err instanceof Error ? err.message : undefined,
        });
      } finally {
        setRunningMode(null);
      }
      return;
    }

    // Run the first enabled schedule now.
    const enabled =
      schedules.filter((s) => Boolean(s.enabled))[0] ?? schedules[0];
    try {
      const res = await authFetch(
        `/api/inference/wiki/maintenance/scheduled/${enabled.id}/run-now`,
        { method: "POST" },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast.success("Maintenance completed");
      fetchSchedules();
    } catch (err) {
      toast.error("Maintenance failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setRunningMode(null);
    }
  }

  // ── Render ──────────────────────────────────────────────────────

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <HugeiconsIcon
              icon={LicenseMaintenanceIcon}
              strokeWidth={1.5}
              className="size-5"
            />
            Scheduled Maintenance
          </DialogTitle>
          <DialogDescription>
            Run wiki maintenance on a recurring schedule — merge duplicates,
            retry fallbacks, enrich analysis, and rebuild the index.
          </DialogDescription>
        </DialogHeader>

        {/* ── Run Now ──────────────────────────────────────── */}
        <div className="flex items-center gap-2 py-2">
          <Button
            variant="outline"
            onClick={() => handleRunNow("without-web-fill")}
            disabled={runningMode !== null}
          >
            {runningMode === "without-web-fill" && (
              <Loader2 className="mr-1.5 size-4 animate-spin" />
            )}
            Run Now
          </Button>
          <Button
            variant="outline"
            onClick={() => handleRunNow("with-web-fill")}
            disabled={runningMode !== null}
          >
            {runningMode === "with-web-fill" && (
              <Loader2 className="mr-1.5 size-4 animate-spin" />
            )}
            Run Now + Web Fill
          </Button>
          <span className="ml-auto text-xs text-muted-foreground">
            {schedules.length} schedule{schedules.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* ── Create / edit form ────────────────────────────── */}
        {showForm && (
          <div className="space-y-3 rounded-2xl border border-border/70 bg-background/60 p-4">
            <div className="flex items-center gap-4">
              <div className="space-y-1.5">
                <Label className="text-xs">Interval</Label>
                <Select
                  value={formInterval}
                  onValueChange={(v) => setFormInterval(v)}
                >
                  <SelectTrigger className="h-9 w-[120px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(INTERVAL_LABELS).map(([k, v]) => (
                      <SelectItem key={k} value={k}>
                        {v}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {formInterval !== "hourly" && (
                <div className="space-y-1.5">
                  <Label className="text-xs">Hour (UTC, 0–23)</Label>
                  <Input
                    className="h-9 w-20"
                    type="number"
                    min={0}
                    max={23}
                    value={formHour}
                    onChange={(e) => setFormHour(e.target.value)}
                    placeholder="auto"
                  />
                </div>
              )}
              {formInterval === "weekly" && (
                <div className="space-y-1.5">
                  <Label className="text-xs">Day of week (0=Mon)</Label>
                  <Input
                    className="h-9 w-20"
                    type="number"
                    min={0}
                    max={6}
                    value={formDow}
                    onChange={(e) => setFormDow(e.target.value)}
                    placeholder="auto"
                  />
                </div>
              )}
              {formInterval === "monthly" && (
                <div className="space-y-1.5">
                  <Label className="text-xs">Day of month (1–28)</Label>
                  <Input
                    className="h-9 w-20"
                    type="number"
                    min={1}
                    max={28}
                    value={formDom}
                    onChange={(e) => setFormDom(e.target.value)}
                    placeholder="auto"
                  />
                </div>
              )}
            </div>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <Switch
                  checked={formWebFill}
                  onCheckedChange={setFormWebFill}
                  id="web-fill-toggle"
                />
                <Label htmlFor="web-fill-toggle" className="text-xs">
                  Fill gaps from web
                </Label>
              </div>
              <div className="ml-auto flex gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setShowForm(false);
                    setEditingId(null);
                  }}
                >
                  Cancel
                </Button>
                <Button size="sm" onClick={handleSubmit}>
                  {editingId ? "Update" : "Create"}
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* ── Schedule list ──────────────────────────────────── */}
        <ScrollArea className="flex-1 min-h-0">
          {loading ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              Loading schedules...
            </p>
          ) : schedules.length === 0 ? (
            <div className="text-center py-8 space-y-2">
              <p className="text-sm text-muted-foreground">
                No scheduled maintenance yet.
              </p>
              <Button size="sm" variant="outline" onClick={openCreate}>
                Create Schedule
              </Button>
            </div>
          ) : (
            <div className="space-y-2">
              {schedules.map((s) => (
                <div
                  key={s.id}
                  className="flex items-center gap-3 rounded-2xl border border-border/70 bg-background/60 px-3 py-2"
                >
                  <Switch
                    checked={Boolean(s.enabled)}
                    onCheckedChange={() => handleToggle(s)}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-[10px]">
                        {INTERVAL_LABELS[s.interval_type] ?? s.interval_type}
                      </Badge>
                      {Boolean(s.with_web_fill) && (
                        <Badge
                          variant="secondary"
                          className="text-[10px]"
                        >
                          web fill
                        </Badge>
                      )}
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-0.5">
                      Next: {fmtNextRun(s.next_run_at)}
                    </p>
                  </div>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => openEdit(s)}
                    title="Edit"
                  >
                    <span className="text-xs">Edit</span>
                  </Button>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => handleDelete(s)}
                    title="Delete"
                    className="text-destructive hover:text-destructive"
                  >
                    <HugeiconsIcon
                      icon={Delete02Icon}
                      strokeWidth={1.5}
                      className="size-4"
                    />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </ScrollArea>

        {schedules.length > 0 && (
          <div className="pt-2">
            <Button size="sm" variant="outline" onClick={openCreate}>
              Create Schedule
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
