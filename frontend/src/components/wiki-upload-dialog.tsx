// Zopedia — File upload + URL ingest dialog for wiki ingestion

import { useState, useCallback, useRef, type DragEvent, type FormEvent } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { authFetch } from "@/features/auth";
import { cn } from "@/lib/utils";
import { UploadIcon, Link } from "lucide-react";
import { toast } from "sonner";

interface WikiUploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const ALLOWED_EXTENSIONS = [
  ".md", ".txt", ".pdf", ".docx", ".pptx", ".xlsx", ".xls",
  ".html", ".htm", ".csv", ".epub", ".ipynb", ".json", ".xml",
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
  ".mp3", ".wav", ".zip",
];

const ACCEPT_STRING = [
  "text/markdown", "text/plain", "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.ms-excel",
  "text/html", "text/csv", "application/epub+zip",
  "application/json", "text/xml", "application/xml",
  "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml",
  "audio/mpeg", "audio/wav", "application/zip",
  ...ALLOWED_EXTENSIONS,
].join(",");

const FORMAT_LABEL = "PDF, DOCX, PPTX, XLSX, HTML, CSV, EPUB, images, audio, ZIP, text, code";

export function WikiUploadDialog({ open, onOpenChange }: WikiUploadDialogProps) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [urlValue, setUrlValue] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const uploadFiles = useCallback(async (files: FileList | File[]) => {
    if (uploading) return;

    const formData = new FormData();
    const fileArray = Array.from(files).filter((f) => {
      const ext = "." + f.name.split(".").pop()?.toLowerCase();
      return ALLOWED_EXTENSIONS.includes(ext);
    });
    if (fileArray.length === 0) {
      toast.error("No valid files", {
        description: `Accepted: ${FORMAT_LABEL}`,
      });
      return;
    }
    if (fileArray.length < Array.from(files).length) {
      toast.warning("Some files were skipped", {
        description: `Only supported formats are accepted.`,
      });
    }

    for (const file of fileArray) {
      formData.append("files", file);
    }

    setUploading(true);
    try {
      const res = await authFetch("/api/upload", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();

      if (data.uploaded?.length > 0) {
        toast.success(`Uploaded ${data.uploaded.length} file(s)`, {
          description: data.uploaded.join(", "),
        });
      }
      if (data.failed?.length > 0) {
        toast.error(`${data.failed.length} file(s) failed`, {
          description: data.failed.map((f: { filename: string }) => f.filename).join(", "),
        });
      }
      if (data.uploaded?.length > 0) {
        onOpenChange(false);
      }
    } catch (err) {
      toast.error("Upload failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setUploading(false);
    }
  }, [uploading, onOpenChange]);

  const ingestUrl = useCallback(async (e: FormEvent) => {
    e.preventDefault();
    const trimmed = urlValue.trim();
    if (!trimmed) return;
    if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
      toast.error("Invalid URL", {
        description: "URL must start with http:// or https://",
      });
      return;
    }

    // Close dialog immediately so the user can continue working.
    setUrlValue("");
    onOpenChange(false);
    toast.info("URL ingest queued", {
      description: "Processing in background — wiki pages will appear when ready.",
    });

    try {
      const res = await authFetch("/api/inference/wiki/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_path: trimmed, max_pending_raw_files: 0 }),
      });
      if (!res.ok) {
        const detail = await res.json().then((d) => (d as { detail?: string }).detail).catch(() => null);
        throw new Error(detail || `Request failed (${res.status})`);
      }
      const data = await res.json();
      if (data.results?.length > 0) {
        toast.success("URL ingested", {
          description: trimmed,
        });
      } else {
        toast.error("URL ingestion returned no results");
      }
    } catch (err) {
      toast.error("URL ingestion failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    }
  }, [urlValue, onOpenChange]);

  const onDragOver = (e: DragEvent) => {
    e.preventDefault();
    setDragging(true);
  };
  const onDragLeave = () => setDragging(false);
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length > 0) {
      uploadFiles(e.dataTransfer.files);
    }
  };

  const busy = uploading;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Upload Files</DialogTitle>
          <DialogDescription>
            Files are placed in the wiki raw/ folder and ingested automatically.
          </DialogDescription>
        </DialogHeader>

        {/* File upload zone */}
        <div
          className={cn(
            "flex flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed p-8 transition-colors cursor-pointer",
            dragging
              ? "border-primary bg-primary/5"
              : "border-muted-foreground/25 hover:border-muted-foreground/50",
            busy && "pointer-events-none opacity-50",
          )}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <UploadIcon className="size-10 text-muted-foreground" />
          <div className="text-center text-sm text-muted-foreground">
            {uploading ? (
              <span>Uploading...</span>
            ) : (
              <>
                <span className="font-medium text-foreground">Click to browse</span>
                {" or drag and drop"}
                <br />
                <span className="text-xs">{FORMAT_LABEL}</span>
              </>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPT_STRING}
            className="hidden"
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) {
                uploadFiles(e.target.files);
                e.target.value = "";
              }
            }}
          />
        </div>

        {/* Divider */}
        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-border" />
          <span className="text-xs text-muted-foreground">or paste a URL</span>
          <div className="h-px flex-1 bg-border" />
        </div>

        {/* URL input */}
        <form onSubmit={ingestUrl} className="flex gap-2">
          <div className="relative flex-1">
            <Link className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
            <Input
              type="url"
              placeholder="https://example.com/document.pdf"
              value={urlValue}
              onChange={(e) => setUrlValue(e.target.value)}
              disabled={busy}
              className="pl-9"
            />
          </div>
          <Button
            type="submit"
            disabled={!urlValue.trim() || busy}
            variant="secondary"
            size="sm"
          >
            Ingest
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
