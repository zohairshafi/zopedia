// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

/**
 * Auto-updater hook for the pywebview desktop app.
 *
 * Checks for updates via two paths (tried in order):
 * 1. The local server's /api/update-status (server app — backed by updater.py).
 * 2. A direct GitHub Releases API call (client app — no local backend).
 *
 * When an update is available and the pywebview bridge is present, the
 * download goes through a native Python helper (download_and_open_dmg)
 * that downloads the DMG to /tmp and opens it in Finder.  Otherwise it
 * POSTs /api/update-download (server-mode).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl } from "@/lib/api-base";
import type { UpdateStatus, UpdateInfo } from "@/hooks/use-tauri-update";

const POLL_INTERVAL_MS = 30 * 60 * 1000;   // 30 min
const INITIAL_DELAY_MS = 20_000;            // 20s after mount

export type { UpdateStatus, UpdateInfo };

// ── GitHub direct check (used when a local /api/update-status isn't
// available, e.g. in the thin desktop client) ───────────────────────────

const GITHUB_REPO = "zohairshafi/zopedia";
const GITHUB_API = `https://api.github.com/repos/${GITHUB_REPO}/releases/latest`;

function getCurrentVersion(): string {
  return (typeof window !== "undefined" ? (window as any).__ZOPEDIA_VERSION__ : null) ?? "";
}

function parseVersion(v: string): number[] {
  return v.replace(/^v/, "").split(".").map(Number).filter((n) => !isNaN(n));
}

function versionGreater(a: string, b: string): boolean {
  const va = parseVersion(a);
  const vb = parseVersion(b);
  for (let i = 0; i < Math.max(va.length, vb.length); i++) {
    const aa = va[i] ?? 0;
    const bb = vb[i] ?? 0;
    if (aa > bb) return true;
    if (aa < bb) return false;
  }
  return false;
}

export function useDesktopUpdate() {
  const [status, setStatus] = useState<UpdateStatus>("idle");
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const checkedRef = useRef(false);
  const downloadUrlRef = useRef<string | null>(null);

  const poll = useCallback(async () => {
    // 1. Try the server endpoint (available when running against a local
    //    FastAPI backend that imports updater.py — i.e. the server app).
    try {
      const res = await fetch(apiUrl("/api/update-status"));
      if (res.ok) {
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
          downloadUrlRef.current = data.download_url ?? null;
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
        return;
      }
    } catch {
      // Fall through to GitHub direct check
    }

    // 2. GitHub direct check — for the client app (or any pywebview desktop)
    //    that has no /api/update-status endpoint.  Rate limit is 60 req/hr
    //    unauthenticated; our 30-min poll interval stays well within that.
    try {
      const current = getCurrentVersion();
      if (!current) return;
      const res = await fetch(GITHUB_API, {
        headers: { Accept: "application/vnd.github+json" },
      });
      if (!res.ok) return;
      const data = await res.json();
      const tag = (data.tag_name ?? "").replace(/^v/, "");
      if (!tag || !versionGreater(tag, current)) {
        setStatus("idle");
        return;
      }
      const dmg = (data.assets ?? []).find(
        (a: { name: string; browser_download_url: string }) =>
          a.name.toLowerCase().endsWith(".dmg"),
      );
      if (!dmg?.browser_download_url) {
        setStatus("idle");
        return;
      }
      downloadUrlRef.current = dmg.browser_download_url;
      setInfo({
        version: tag,
        currentVersion: current,
        body: data.body ?? undefined,
        date: data.published_at ?? undefined,
      });
      setStatus("available");
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

  /** Manual update check — resets dismiss, sets checking status, and polls
   *  immediately.  Call this from a "Check for Updates" button. */
  const checkUpdate = useCallback(async () => {
    setStatus("checking");
    setDismissed(false);
    downloadUrlRef.current = null;
    await poll();
  }, [poll]);

  async function installUpdate() {
    if (!info) return;
    setStatus("downloading");
    setError(null);
    try {
      // pywebview bridge: download directly in the desktop app
      const w = window as any;
      if (w.pywebview?.api?.download_and_open_dmg) {
        const url = downloadUrlRef.current;
        if (!url) {
          setError("No download URL available");
          setStatus("error");
          return;
        }
        const raw: string = await w.pywebview.api.download_and_open_dmg(url);
        let result: { ok: boolean; error?: string };
        try { result = JSON.parse(raw); } catch { result = { ok: false, error: String(raw) }; }
        if (result.ok) {
          // DMG downloaded and opened in Finder — user drags to /Applications
          setStatus("installing");
        } else {
          setError(result.error ?? "Download failed");
          setStatus("error");
        }
        return;
      }
      // Server fallback: POST to /api/update-download
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

  // Stubs to satisfy the shared UpdateBanner / DesktopUpdateLayer interface
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
    checkUpdate,
  };
}
