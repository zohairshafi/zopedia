import { useState, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { SourceSuggestionCard } from "./source-suggestion-card";
import type { SourceSuggestion } from "../types";

interface Props {
  sources: SourceSuggestion[];
  round: number;
  onApprove: (urls: string[]) => void;
  onSkipAll: () => void;
  loading?: boolean;
}

export function SourceApprovalPanel({
  sources,
  round,
  onApprove,
  onSkipAll,
  loading,
}: Props) {
  const [selected, setSelected] = useState<Set<string>>(() => {
    // Pre-select trusted sources that aren't already in wiki
    const trusted = sources
      .filter((s) => s.is_trusted && !s.already_in_wiki)
      .map((s) => s.url);
    return new Set(trusted);
  });

  const newSources = useMemo(
    () => sources.filter((s) => !s.already_in_wiki),
    [sources],
  );
  const existingSources = useMemo(
    () => sources.filter((s) => s.already_in_wiki),
    [sources],
  );

  const selectAll = () =>
    setSelected(new Set(newSources.map((s) => s.url)));
  const deselectAll = () => setSelected(new Set());
  const selectTrusted = () =>
    setSelected(
      new Set(newSources.filter((s) => s.is_trusted).map((s) => s.url)),
    );

  const toggle = (url: string) => {
    const next = new Set(selected);
    if (next.has(url)) next.delete(url);
    else next.add(url);
    setSelected(next);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h3 className="font-semibold text-lg">
            Round {round} — {sources.length} sources found
          </h3>
          <p className="text-sm text-muted-foreground">
            {newSources.length} new · {existingSources.length} already in wiki
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button size="sm" variant="outline" onClick={selectAll}>
            Select All
          </Button>
          <Button size="sm" variant="outline" onClick={selectTrusted}>
            Select Trusted
          </Button>
          <Button size="sm" variant="outline" onClick={deselectAll}>
            Clear
          </Button>
          <Button size="sm" variant="outline" onClick={onSkipAll}>
            Skip All
          </Button>
          <Button
            size="sm"
            onClick={() => onApprove(Array.from(selected))}
            disabled={selected.size === 0 || loading}
          >
            Approve ({selected.size})
          </Button>
        </div>
      </div>

      <div className="space-y-2 max-h-[50vh] overflow-y-auto pr-1">
        {newSources.map((source) => (
          <SourceSuggestionCard
            key={source.url}
            source={source}
            checked={selected.has(source.url)}
            onCheckedChange={() => toggle(source.url)}
          />
        ))}
        {existingSources.length > 0 && (
          <>
            <div className="text-xs font-medium text-muted-foreground pt-2 pb-1">
              Already in your wiki
            </div>
            {existingSources.map((source) => (
              <SourceSuggestionCard
                key={source.url}
                source={source}
                checked={false}
                onCheckedChange={() => {}}
              />
            ))}
          </>
        )}
      </div>
    </div>
  );
}
