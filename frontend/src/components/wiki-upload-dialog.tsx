// Zopedia — File upload dialog for wiki ingestion

import { useState, useCallback, useRef, type DragEvent } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { authFetch } from "@/features/auth";
import { cn } from "@/lib/utils";
import { UploadIcon } from "lucide-react";
import { toast } from "sonner";

interface WikiUploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function WikiUploadDialog({ open, onOpenChange }: WikiUploadDialogProps) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const uploadFiles = useCallback(async (files: FileList | File[]) => {
    if (uploading) return;

    const formData = new FormData();
    const fileArray = Array.from(files);
    if (fileArray.length === 0) return;

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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Upload Files</DialogTitle>
          <DialogDescription>
            Files are placed in the wiki raw/ folder and ingested automatically.
          </DialogDescription>
        </DialogHeader>
        <div
          className={cn(
            "flex flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed p-8 transition-colors cursor-pointer",
            dragging
              ? "border-primary bg-primary/5"
              : "border-muted-foreground/25 hover:border-muted-foreground/50",
            uploading && "pointer-events-none opacity-50",
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
                <span>PDF, text, markdown files</span>
              </>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) {
                uploadFiles(e.target.files);
                e.target.value = "";
              }
            }}
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
