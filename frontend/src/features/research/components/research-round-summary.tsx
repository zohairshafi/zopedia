import { Card } from "@/components/ui/card";
import type { RoundResult } from "../types";

interface Props {
  result: RoundResult;
}

export function ResearchRoundSummary({ result }: Props) {
  return (
    <Card className="p-4 space-y-2">
      <div className="flex items-center gap-2">
        <span className="font-semibold text-sm">
          Round {result.round} complete
        </span>
        <span className="text-xs text-muted-foreground">
          {result.sources_ingested} sources ingested
        </span>
      </div>
      {result.new_pages.length > 0 && (
        <div className="text-xs text-muted-foreground space-y-1 max-h-[120px] overflow-y-auto">
          {result.new_pages.map((url) => (
            <div key={url} className="truncate">
              &middot; {url}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
