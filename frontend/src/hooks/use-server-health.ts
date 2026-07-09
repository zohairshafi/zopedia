// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { useEffect } from "react";
import { apiUrl } from "@/lib/api-base";
import { isClientMode, SERVER_URL_KEY } from "@/lib/mode";

// ---------------------------------------------------------------------------
// Module-level server health store. Polled periodically in client mode so
// the UI can proactively warn when the remote server becomes unreachable,
// rather than waiting for the next user action to fail.
//
// IMPORTANT: the Mac client app runs a local static server with SPA
// fallback (unknown paths → index.html, 200 OK, text/html).  The real
// /api/health endpoint returns application/json.  We must check the
// Content-Type so a misconfigured apiBase (empty string → relative URL
// that hits the local server) doesn't produce false positives.
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 15_000;
const REQUEST_TIMEOUT_MS = 5_000;
const FAILURES_BEFORE_UNREACHABLE = 2;

type Listener = () => void;
let serverReachable = true;
let consecutiveFailures = 0;
const listeners = new Set<Listener>();

export const serverHealthStore = {
  getSnapshot(): boolean {
    return serverReachable;
  },
  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

function setServerReachable(v: boolean): void {
  if (serverReachable === v) return;
  serverReachable = v;
  consecutiveFailures = v ? 0 : FAILURES_BEFORE_UNREACHABLE;
  for (const l of listeners) l();
}

function hasServerConfig(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(SERVER_URL_KEY) !== null;
}

/** Build the health-check URL directly from localStorage so we are never
 *  relying on the module-level `apiBase` staying in sync.  Falls back to
 *  the regular `apiUrl()` helper. */
function healthUrl(): string {
  const url = apiUrl("/api/health");
  // If apiBase was empty (e.g. race at module init), apiUrl returns a
  // relative path like "/api/health".  Construct the full URL ourselves.
  if (url.startsWith("/")) {
    const server = (localStorage.getItem(SERVER_URL_KEY) ?? "").replace(/\/+$/, "");
    if (server) return `${server}/api/health`;
  }
  return url;
}

async function _checkHealthCore(): Promise<boolean> {
  if (!hasServerConfig()) {
    console.debug("[health] no server config, skipping poll");
    return false;
  }

  const url = healthUrl();
  console.debug("[health] polling", url);
  try {
    const res = await fetch(url, {
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      cache: "no-store",
    });

    const contentType = res.headers.get("content-type") ?? "";
    const isJson = contentType.includes("application/json");

    console.debug("[health] response status:", res.status, "content-type:", contentType);

    if (res.ok && isJson) {
      return true;
    }

    if (!isJson) {
      console.warn(
        "[health] non-JSON response (SPA fallback?) — content-type:",
        contentType,
      );
    }
  } catch (err) {
    console.warn("[health] fetch failed:", err);
  }

  return false;
}

/** Periodic health check — uses the consecutive-failure threshold so a
 *  single transient blip doesn't trigger the banner.  Called by the poll timer. */
async function checkHealth(): Promise<void> {
  const ok = await _checkHealthCore();
  if (ok) {
    consecutiveFailures = 0;
    setServerReachable(true);
    return;
  }
  consecutiveFailures += 1;
  console.debug("[health] consecutiveFailures:", consecutiveFailures, "/", FAILURES_BEFORE_UNREACHABLE);
  if (consecutiveFailures >= FAILURES_BEFORE_UNREACHABLE) {
    console.warn("[health] server marked UNREACHABLE");
    setServerReachable(false);
  }
}

/** Immediate health check — a single failure is enough to mark the server
 *  unreachable.  Used for user-initiated checks (thread switch, Retry button)
 *  where the user expects instant feedback. */
export async function checkHealthNow(): Promise<void> {
  const ok = await _checkHealthCore();
  if (ok) {
    consecutiveFailures = 0;
    setServerReachable(true);
    return;
  }
  console.warn("[health] immediate check failed — server marked UNREACHABLE");
  setServerReachable(false);
}

// Fast-poll interval used when the server is currently marked unreachable
// so recovery is detected quickly instead of waiting a full poll cycle.
const FAST_POLL_MS = 5_000;

/**
 * Start periodic server health checks. Only active in client mode —
 * in server/desktop mode this is a no-op (the backend is co-located).
 *
 * When the server is reachable we poll every POLL_INTERVAL_MS (15 s).
 * Once it's marked unreachable we switch to FAST_POLL_MS (5 s) so the
 * banner disappears quickly after connectivity returns.
 */
export function useServerHealthPoll(): void {
  useEffect(() => {
    if (!isClientMode()) return;

    let timeoutId: ReturnType<typeof setTimeout>;

    async function poll(): Promise<void> {
      await checkHealth();
      // Read the live value — checkHealth may have just changed it.
      const delay = serverReachable ? POLL_INTERVAL_MS : FAST_POLL_MS;
      timeoutId = setTimeout(poll, delay);
    }

    // Kick off immediately
    void poll();

    return () => clearTimeout(timeoutId);
  }, []);
}
