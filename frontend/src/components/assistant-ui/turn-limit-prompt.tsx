import { Button } from "@/components/ui/button";
import { extendToolTurns } from "@/features/chat/api/chat-api";
import { useChatRuntimeStore } from "@/features/chat/stores/chat-runtime-store";
import { useState } from "react";

export function TurnLimitPrompt() {
  const turnLimit = useChatRuntimeStore((s) => s.turnLimit);
  const setTurnLimit = useChatRuntimeStore((s) => s.setTurnLimit);
  const [loading, setLoading] = useState(false);

  if (!turnLimit) return null;

  const handleContinue = async () => {
    setLoading(true);
    try {
      await extendToolTurns(turnLimit.sessionId);
    } catch {
      // Backend will time out — just clear the prompt
    } finally {
      setTurnLimit(null);
      setLoading(false);
    }
  };

  const handleStop = () => {
    setTurnLimit(null);
    // Backend will time out after 30s and auto-synthesize
  };

  return (
    <div className="flex items-center justify-center py-3">
      <div className="rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm space-y-2 max-w-md text-center">
        <p className="text-muted-foreground">
          The model has used{" "}
          <span className="font-medium text-foreground">
            {turnLimit.currentTurn}/{turnLimit.maxTurns}
          </span>{" "}
          research turns. Continue searching?
        </p>
        <div className="flex items-center justify-center gap-2">
          <Button
            size="sm"
            variant="default"
            disabled={loading}
            onClick={handleContinue}
          >
            {loading ? "Extending..." : "Continue (+4 turns)"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={loading}
            onClick={handleStop}
          >
            Stop &amp; Answer
          </Button>
        </div>
      </div>
    </div>
  );
}
