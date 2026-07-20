// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { BookOpen, MessagesSquare } from "lucide-react";

export type PdfChoice = "ingest" | "conversation";

interface PdfChooserDialogProps {
  /** The PDF awaiting a decision, or null when the dialog is closed. */
  file: File | null;
  onChoose: (choice: PdfChoice) => void;
  onClose: () => void;
}

/**
 * Shown when a PDF is dropped/attached in the chat. Lets the user pick:
 *  - "conversation": attach to the message (text extracted server-side on send)
 *  - "ingest": upload to the wiki raw/ folder via /api/upload (not attached)
 */
export function PdfChooserDialog({ file, onChoose, onClose }: PdfChooserDialogProps) {
  const open = file !== null;
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{file?.name ?? "PDF"}</DialogTitle>
          <DialogDescription>How do you want to use this PDF?</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-2 pt-1">
          <Button
            variant="default"
            className="justify-start"
            onClick={() => onChoose("conversation")}
          >
            <MessagesSquare className="mr-2 size-4" />
            Use in this conversation
          </Button>
          <Button
            variant="outline"
            className="justify-start"
            onClick={() => onChoose("ingest")}
          >
            <BookOpen className="mr-2 size-4" />
            Ingest into the wiki
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
