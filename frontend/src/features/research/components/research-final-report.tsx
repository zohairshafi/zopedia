import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Download03Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { Streamdown } from "streamdown";
import { preprocessWikiLinks } from "@/lib/wiki-links";
import { useMemo } from "react";
import "katex/dist/katex.min.css";

interface Props {
  content: string;
  topic: string;
  totalIngested: number;
  onNewResearch?: () => void;
}

export function ResearchFinalReport({
  content,
  topic,
  totalIngested,
  onNewResearch,
}: Props) {
  const processedContent = useMemo(() => preprocessWikiLinks(content), [content]);

  const handleExport = () => {
    const blob = new Blob([content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `research-${topic.slice(0, 40).replace(/\s+/g, "-")}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Card className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">Research Complete</h2>
          <p className="text-sm text-muted-foreground">
            Topic: {topic} &middot; {totalIngested} sources ingested
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={handleExport}>
            <HugeiconsIcon icon={Download03Icon} strokeWidth={1.5} className="size-4 mr-1" />
            Export
          </Button>
          {onNewResearch && (
            <Button size="sm" onClick={onNewResearch}>
              New Research
            </Button>
          )}
        </div>
      </div>

      <ScrollArea className="h-[60vh] rounded-md border">
        <div className="p-4 prose prose-sm dark:prose-invert max-w-none">
          {processedContent ? (
            <Streamdown mode="static">
              {processedContent}
            </Streamdown>
          ) : (
            <p className="text-muted-foreground text-sm italic">
              Generating summary...
            </p>
          )}
        </div>
      </ScrollArea>
    </Card>
  );
}
