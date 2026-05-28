import { useCallback } from "react";
import { useNavigate } from "@tanstack/react-router";
import { ResearchSetupForm } from "./components/research-setup-form";
import { ResearchRunView } from "./components/research-run-view";
import { useResearchStore } from "./stores/research-store";
import type { ResearchConfig } from "./types";

function createSessionId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function ResearchPage() {
  const navigate = useNavigate();
  const config = useResearchStore((s) => s.config);
  const sessionId = useResearchStore((s) => s.sessionId);
  const setConfig = useResearchStore((s) => s.setConfig);
  const setSessionId = useResearchStore((s) => s.setSessionId);
  const reset = useResearchStore((s) => s.reset);

  const handleStart = useCallback(
    (cfg: ResearchConfig) => {
      const sid = createSessionId();
      setConfig(cfg);
      setSessionId(sid);
    },
    [setConfig, setSessionId],
  );

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

  return <ResearchSetupForm onStart={handleStart} />;
}
