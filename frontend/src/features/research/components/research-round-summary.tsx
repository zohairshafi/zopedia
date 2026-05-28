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
          {result.sources_ingested} ingested
          {result.sources_failed > 0 && (
            <span className="text-amber-600 dark:text-amber-400">
              {" "}&middot; {result.sources_failed} failed
            </span>
          )}
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
      {result.failed_pages.length > 0 && (
        <div className="text-xs space-y-1 max-h-[120px] overflow-y-auto border-t border-amber-500/20 pt-2">
          <p className="text-amber-600 dark:text-amber-400 font-medium">
            Skipped (could not ingest):
          </p>
          {result.failed_pages.map((url) => (
            <a
              key={url}
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="block truncate text-amber-600/80 dark:text-amber-400/80 underline"
            >
              &middot; {url}
            </a>
          ))}
        </div>
      )}
    </Card>
  );
}
