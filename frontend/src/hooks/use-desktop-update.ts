// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

/**
 * Auto-updater hook for the pywebview desktop app.
 *
 * Polls /api/update-status (served by launcher.py) and triggers a DMG
 * download via /api/update-download when the user clicks "Update Now".
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl } from "@/lib/api-base";
import type { UpdateStatus, UpdateInfo } from "@/hooks/use-tauri-update";

const POLL_INTERVAL_MS = 30 * 60 * 1000;   // 30 min
const INITIAL_DELAY_MS = 20_000;            // 20s after mount

export type { UpdateStatus, UpdateInfo };

export function useDesktopUpdate() {
  const [status, setStatus] = useState<UpdateStatus>("idle");
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const checkedRef = useRef(false);

  const poll = useCallback(async () => {
    try {
      const res = await fetch(apiUrl("/api/update-status"));
      if (!res.ok) return;
      const data: {
        status: string;
        available: boolean;
        current_version: string;
        latest_version: string;
        download_url?: string | null;
        release_notes?: string | null;
        published_at?: string | null;
      } = await res.json();

      if (data.available) {
        setInfo({
          version: data.latest_version,
          currentVersion: data.current_version,
          body: data.release_notes ?? undefined,
          date: data.published_at ?? undefined,
        });
        setStatus("available");
      } else if (data.status === "checking") {
        setStatus("checking");
      } else {
        setStatus("idle");
      }
    } catch {
      // Network error — silently ignore; will retry on next interval
    }
  }, []);

  useEffect(() => {
    if (checkedRef.current) return;
    checkedRef.current = true;

    const initial = setTimeout(() => {
      void poll();
      const interval = setInterval(poll, POLL_INTERVAL_MS);
      return () => clearInterval(interval);
    }, INITIAL_DELAY_MS);

    return () => clearTimeout(initial);
  }, [poll]);

  async function installUpdate() {
    if (!info) return;
    setStatus("downloading");
    setError(null);
    try {
      const res = await fetch(apiUrl("/api/update-download"), { method: "POST" });
      const data: { ok: boolean; error?: string } = await res.json();
      if (data.ok) {
        // DMG has been opened in Finder — app will restart after user installs
        setStatus("installing");
      } else {
        setError(data.error ?? "Download failed");
        setStatus("error");
      }
    } catch (e) {
      setError(String(e));
      setStatus("error");
    }
  }

  function dismiss() {
    setDismissed(true);
  }

  // Stubs to satisfy the shared UpdateBanner interface
  async function retryUpdate() {
    setError(null);
    await installUpdate();
  }

  async function skipAndRestart() {
    setStatus("idle");
    setDismissed(true);
  }

  return {
    status,
    info,
    progress: 0,
    logs: [] as string[],
    dismissed,
    error,
    isExternalServer: false,
    installUpdate,
    retryUpdate,
    skipAndRestart,
    dismiss,
  };
}
