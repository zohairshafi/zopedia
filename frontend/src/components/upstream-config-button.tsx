import { usePlatformStore } from "@/config/env";
import { authFetch } from "@/features/auth";
import { cn } from "@/lib/utils";
import { useEffect, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { toast } from "sonner";

interface UpstreamConfigButtonProps {
  variant?: "outline" | "ghost" | "muted";
  size?: "sm" | "default" | "lg";
  className?: string;
}

export function UpstreamConfigButton({ variant = "ghost", size: _size = "sm", className }: UpstreamConfigButtonProps) {
  const upstreamProvider = usePlatformStore((s) => s.upstreamProvider);
  const upstreamModel = usePlatformStore((s) => s.upstreamModel);
  const [open, setOpen] = useState(false);

  // Load current values from the wiki env endpoint
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    authFetch("/api/inference/wiki/env")
      .then((r) => r.json())
      .then((data: any) => {
        const vars: any[] = data.variables ?? [];
        const byName: Record<string, string> = {};
        vars.forEach((v: any) => { byName[v.name] = v.current_value ?? v.default_value ?? ""; });
        setBaseUrl(byName["ZOPEDIA_LLM_BASE_URL"] ?? "");
        setApiKey(byName["ZOPEDIA_LLM_API_KEY"] ?? "");
        setModel(byName["ZOPEDIA_LLM_MODEL"] ?? "");
      })
      .catch(() => {});
  }, [open]);

  const save = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await authFetch("/api/inference/wiki/env", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          values: {
            ZOPEDIA_LLM_BASE_URL: baseUrl || null,
            ZOPEDIA_LLM_API_KEY: apiKey || null,
            ZOPEDIA_LLM_MODEL: model || null,
          },
          restart_backend: true,
        }),
      });
      const result = await resp.json();
      if (result.status === "ok" || result.status === "partial") {
        toast.success("LLM config updated. Backend restarting...");
        setOpen(false);
      } else {
        toast.error("Failed to update config");
      }
    } catch (e: any) {
      toast.error(e?.message ?? "Failed to update config");
    } finally {
      setLoading(false);
    }
  }, [baseUrl, apiKey, model]);

  const label = upstreamModel && upstreamModel !== "default"
    ? `${upstreamProvider || "API"} / ${upstreamModel}`
    : upstreamProvider || "Configure LLM";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "flex items-center gap-1.5 rounded-[8px] px-2.5 py-1 text-xs font-medium transition-colors max-w-[220px] truncate",
            variant === "ghost" && "text-[#383835] dark:text-[#c7c7c4] hover:bg-[#ececec] dark:hover:bg-[#2e3035]",
            className,
          )}
        >
          <span className="relative flex size-2 shrink-0">
            <span className="absolute inline-flex size-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
          </span>
          <span className="truncate">{label}</span>
          <svg className="size-3 shrink-0 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
          </svg>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-4" align="start">
        <div className="flex flex-col gap-3">
          <h4 className="text-sm font-medium">Upstream LLM Configuration</h4>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs">Base URL</Label>
            <Input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1"
              className="h-8 text-xs"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs">API Key</Label>
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              className="h-8 text-xs"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs">Model</Label>
            <Input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="gpt-4o"
              className="h-8 text-xs"
            />
          </div>
          <Button size="sm" onClick={save} disabled={loading} className="mt-1">
            {loading ? "Saving..." : "Save & Restart"}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
