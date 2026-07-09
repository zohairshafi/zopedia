// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

interface LoadingScreenProps {
  /** Message shown below the spinner. Defaults to "Connecting to server…" */
  message?: string;
  /** Called when the user clicks the disconnect button. When provided, a
   *  "Connect to a different server" button appears after `showDisconnectAfterMs`
   *  milliseconds of loading. */
  onDisconnect?: () => void;
  /** Called when the user clicks the retry button. When provided, a "Retry"
   *  button appears alongside the disconnect button after the timeout. */
  onRetry?: () => void;
  /** Milliseconds before the action buttons appear. Default 8 seconds. */
  showDisconnectAfterMs?: number;
}

export function LoadingScreen({
  message = "Connecting to server…",
  onDisconnect,
  onRetry,
  showDisconnectAfterMs = 8000,
}: LoadingScreenProps) {
  const [showActions, setShowActions] = useState(false);

  useEffect(() => {
    if (!onDisconnect && !onRetry) return;
    const id = setTimeout(() => setShowActions(true), showDisconnectAfterMs);
    return () => clearTimeout(id);
  }, [onDisconnect, onRetry, showDisconnectAfterMs]);

  return (
    <div className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-6 bg-background">
      {/* Zopedia logo — light/dark variants */}
      <img
        src="logo_main_light.png"
        alt="Zopedia"
        className="block h-24 w-24 object-contain dark:hidden"
      />
      <img
        src="logo_main.png"
        alt="Zopedia"
        className="hidden h-24 w-24 object-contain dark:block"
      />

      {/* Spinner */}
      <svg
        className="size-6 animate-spin text-muted-foreground"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle
          className="opacity-25"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="4"
        />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
        />
      </svg>

      <p className="text-sm text-muted-foreground">{message}</p>

      {/* Action buttons — appear after the timeout (server unreachable) */}
      {showActions && (onRetry || onDisconnect) && (
        <div className="mt-2 flex items-center gap-2">
          {onRetry && (
            <Button
              variant="outline"
              size="sm"
              onClick={onRetry}
            >
              Retry
            </Button>
          )}
          {onDisconnect && (
            <Button
              variant="outline"
              size="sm"
              onClick={onDisconnect}
            >
              Connect to a different server
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
