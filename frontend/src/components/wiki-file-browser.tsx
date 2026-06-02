import { useCallback, useEffect, useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  FolderTreeIcon,
  File02Icon,
  Search01Icon,
  Cancel01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { authFetch } from "@/features/auth";

// ── Types ───────────────────────────────────────────────────────────

interface WikiFile {
  name: string;
  relative_path: string;
  size: number;
  preview: string;
}

interface WikiDirectory {
  count: number;
  files: WikiFile[];
}

interface WikiFilesResponse {
  directories: Record<string, WikiDirectory>;
  root_files: WikiFile[];
}

// ── Helpers ─────────────────────────────────────────────────────────

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const DIRECTORY_ORDER = ["entities", "concepts", "godnodes", "analysis", "sources"];

function sortDirectories(entries: [string, WikiDirectory][]): [string, WikiDirectory][] {
  return entries.sort((a, b) => {
    const ai = DIRECTORY_ORDER.indexOf(a[0]);
    const bi = DIRECTORY_ORDER.indexOf(b[0]);
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    return a[0].localeCompare(b[0]);
  });
}

// ── File row ────────────────────────────────────────────────────────

function FileRow({ file }: { file: WikiFile }) {
  return (
    <button
      type="button"
      className="flex items-center gap-2 w-full px-2 py-1 rounded text-xs text-left hover:bg-muted transition-colors group"
      onClick={() =>
        window.open(
          `/api/inference/wiki-file?path=${encodeURIComponent(file.relative_path)}`,
          "_blank",
          "noopener,noreferrer",
        )
      }
      title={file.preview || file.name}
    >
      <HugeiconsIcon
        icon={File02Icon}
        strokeWidth={1.5}
        className="size-3.5 text-muted-foreground shrink-0"
      />
      <span className="truncate flex-1 group-hover:text-primary transition-colors">
        {file.name}
      </span>
      <span className="text-[10px] text-muted-foreground shrink-0">
        {formatSize(file.size)}
      </span>
    </button>
  );
}

// ── Component ───────────────────────────────────────────────────────

interface WikiFileBrowserProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function WikiFileBrowser({ open, onOpenChange }: WikiFileBrowserProps) {
  const [data, setData] = useState<WikiFilesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch("/api/inference/wiki/files");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      fetchData();
      setSearch("");
    }
  }, [open, fetchData]);

  const toggleExpand = (dir: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(dir)) next.delete(dir);
      else next.add(dir);
      return next;
    });
  };

  const expandAll = () => {
    if (!data) return;
    const all = new Set(Object.keys(data.directories));
    setExpanded(expanded.size === all.size ? new Set() : all);
  };

  const filteredData = useMemo(() => {
    if (!data) return null;
    if (!search.trim()) return data;

    const q = search.toLowerCase();
    const filtered: WikiFilesResponse = { directories: {}, root_files: [] };

    for (const [dirName, dir] of Object.entries(data.directories)) {
      const matching = dir.files.filter(
        (f) =>
          f.name.toLowerCase().includes(q) ||
          f.relative_path.toLowerCase().includes(q) ||
          f.preview.toLowerCase().includes(q),
      );
      if (matching.length > 0) {
        filtered.directories[dirName] = { ...dir, count: matching.length, files: matching };
      }
    }

    filtered.root_files = data.root_files.filter(
      (f) =>
        f.name.toLowerCase().includes(q) ||
        f.preview.toLowerCase().includes(q),
    );

    return filtered;
  }, [data, search]);

  const isSearching = search.trim().length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Wiki Files</DialogTitle>
        </DialogHeader>

        <div className="relative">
          <HugeiconsIcon
            icon={Search01Icon}
            strokeWidth={1.5}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground"
          />
          <Input
            placeholder="Filter files..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 pr-8"
          />
          {search && (
            <button
              type="button"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              onClick={() => setSearch("")}
            >
              <HugeiconsIcon icon={Cancel01Icon} strokeWidth={1.5} className="size-4" />
            </button>
          )}
        </div>

        <div className="flex-1 min-h-0 overflow-hidden">
          <ScrollArea className="h-full">
            {loading && (
              <p className="text-sm text-muted-foreground text-center py-8">Loading...</p>
            )}
            {error && (
              <p className="text-sm text-destructive text-center py-8">{error}</p>
            )}

            {filteredData && (
              <div className="space-y-1">
                {!isSearching && Object.keys(filteredData.directories).length > 0 && (
                  <button
                    type="button"
                    className="text-xs text-muted-foreground hover:text-foreground mb-2"
                    onClick={expandAll}
                  >
                    {expanded.size >= Object.keys(filteredData.directories).length
                      ? "Collapse all"
                      : "Expand all"}
                  </button>
                )}

                {sortDirectories(Object.entries(filteredData.directories)).map(([dirName, dir]) => {
                  const isOpen = isSearching || expanded.has(dirName);
                  return (
                    <div key={dirName}>
                      <button
                        type="button"
                        className="flex items-center gap-2 w-full px-2 py-1.5 rounded-md text-sm font-medium hover:bg-muted transition-colors"
                        onClick={() => toggleExpand(dirName)}
                      >
                        <HugeiconsIcon
                          icon={FolderTreeIcon}
                          strokeWidth={1.5}
                          className="size-4 text-muted-foreground shrink-0"
                        />
                        <span className="capitalize">{dirName}</span>
                        <span className="text-xs text-muted-foreground">
                          ({dir.count} {dir.count === 1 ? "file" : "files"})
                        </span>
                      </button>
                      {isOpen && (
                        <div className="ml-6 border-l border-border pl-3 space-y-0.5">
                          {dir.files.map((file) => (
                            <FileRow key={file.relative_path} file={file} />
                          ))}
                          {dir.files.length === 0 && (
                            <p className="text-xs text-muted-foreground px-2 py-1">Empty</p>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}

                {filteredData.root_files.length > 0 && (
                  <div className="pt-2">
                    <p className="text-xs font-medium text-muted-foreground px-2 py-1">Root</p>
                    <div className="space-y-0.5">
                      {filteredData.root_files.map((file) => (
                        <FileRow key={file.relative_path} file={file} />
                      ))}
                    </div>
                  </div>
                )}

                {Object.keys(filteredData.directories).length === 0 &&
                  filteredData.root_files.length === 0 && (
                    <p className="text-sm text-muted-foreground text-center py-8">
                      {search ? "No matching files." : "No wiki files found."}
                    </p>
                  )}
              </div>
            )}
          </ScrollArea>
        </div>
      </DialogContent>
    </Dialog>
  );
}
