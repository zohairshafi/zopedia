import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import type { SourceSuggestion } from "../types";

interface Props {
  source: SourceSuggestion;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}

const TYPE_LABELS: Record<string, string> = {
  paper: "Paper",
  webpage: "Webpage",
  youtube: "YouTube",
  tweet: "Tweet",
  pdf: "PDF",
};

export function SourceSuggestionCard({ source, checked, onCheckedChange }: Props) {
  return (
    <Card
      className={`p-3 cursor-pointer transition-colors hover:bg-accent/50 ${
        source.already_in_wiki ? "opacity-60" : ""
      }`}
      onClick={() => onCheckedChange(!checked)}
    >
      <div className="flex items-start gap-3">
        <Checkbox
          checked={checked}
          onCheckedChange={(v) => onCheckedChange(v === true)}
          onClick={(e) => e.stopPropagation()}
          disabled={source.already_in_wiki}
        />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm truncate">
              {source.title || source.url}
            </span>
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
              {TYPE_LABELS[source.source_type] ?? source.source_type}
            </Badge>
            {source.is_trusted && (
              <Badge variant="default" className="text-[10px] px-1.5 py-0">
                Trusted
              </Badge>
            )}
            {source.already_in_wiki && (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                In wiki
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground truncate">{source.url}</p>
          {source.snippet && (
            <p className="text-xs text-muted-foreground line-clamp-2">
              {source.snippet}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
