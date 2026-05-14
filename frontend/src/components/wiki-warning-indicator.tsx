import { apiUrl } from "@/lib/api-base";
import { useEffect, useState, useCallback } from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { toast } from "sonner";

export function WikiWarningIndicator() {
  const [warning, setWarning] = useState<Record<string, any> | null>(null);
  const [rebuilding, setRebuilding] = useState(false);

  const fetchWarnings = useCallback(() => {
    fetch(apiUrl("/api/inference/wiki/warnings"))
      .then((r) => r.json())
      .then((data: any) => {
        setWarning(data?.warning ? data : null);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchWarnings();
    const interval = setInterval(fetchWarnings, 60_000);
    return () => clearInterval(interval);
  }, [fetchWarnings]);

  const rebuild = useCallback(async () => {
    setRebuilding(true);
    try {
      const resp = await fetch(apiUrl("/api/inference/wiki/rebuild-index"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (resp.ok) {
        toast.success("Godnodes index rebuild started");
        setWarning(null);
      } else {
        toast.error("Failed to start rebuild");
      }
    } catch {
      toast.error("Failed to start rebuild");
    } finally {
      setRebuilding(false);
    }
  }, []);

  if (!warning) return null;

  const entityCount = warning.entities_uncovered ?? 0;
  const conceptCount = warning.concepts_uncovered ?? 0;
  const threshold = warning.threshold ?? 50;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="flex items-center gap-1 rounded-[8px] px-1.5 py-1 text-xs font-medium text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/30 transition-colors shrink-0"
        >
          <span className="relative flex size-2 shrink-0">
            <span className="absolute inline-flex size-full rounded-full bg-amber-400 opacity-75 animate-pulse" />
            <span className="relative inline-flex size-2 rounded-full bg-amber-500" />
          </span>
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom" align="start" className="max-w-[280px] p-3">
        <div className="flex flex-col gap-2">
          <div>
            <p className="text-xs font-medium">Godnodes index needs rebuild</p>
            <p className="text-xs text-muted-foreground mt-1">
              {entityCount} new entities and {conceptCount} new concepts are not covered
              (threshold: {threshold}). Rebuild to improve wiki navigation.
            </p>
          </div>
          <button
            type="button"
            disabled={rebuilding}
            onClick={rebuild}
            className="text-xs font-medium text-amber-700 dark:text-amber-400 hover:underline disabled:opacity-50 self-start"
          >
            {rebuilding ? "Rebuilding..." : "Rebuild index now"}
          </button>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
