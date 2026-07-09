// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { redirect } from "@tanstack/react-router";
import { apiUrl, isTauri } from "@/lib/api-base";
import { isClientMode } from "@/lib/mode";
import {
  getPostAuthRoute,
  hasAuthToken,
  hasRefreshToken,
  logout,
  mustChangePassword,
  refreshSession,
  tauriAutoAuth,
} from "@/features/auth";
import { hasServerConfig } from "@/features/connect";

// ---------------------------------------------------------------------------
// Client-mode auth loading flag.
//
// Starts as `true` in client mode when a server is configured so that
// RootLayout's very first render shows the loading screen.  A useEffect
// in RootLayout runs a health check after mount and clears the flag when
// the server responds.  This split (init = true → effect clears it) is
// necessary because TanStack Router runs route `beforeLoad` callbacks
// *before* any component renders — toggling the flag inside `beforeLoad`
// would be invisible on cold start.
//
// On subsequent navigations `requireAuth()` uses a fast synchronous path
// (just checks localStorage for tokens), so the flag is never set and
// thread switches don't flash the loading screen.
// ---------------------------------------------------------------------------
type Listener = () => void;

function getInitialClientAuthLoading(): boolean {
  if (typeof window === "undefined") return false;
  if (!isClientMode()) return false;
  return hasServerConfig();
}

let clientAuthLoading = getInitialClientAuthLoading();

// Debug: surface startup state even if React never renders.
if (typeof window !== "undefined") {
  const w = window as unknown as Record<string, unknown>;
  w.__ZOPEDIA_STARTUP__ = {
    clientMode: isClientMode(),
    hasServerConfig: hasServerConfig(),
    clientAuthLoading,
    hasAuthToken: typeof localStorage !== "undefined" ? !!localStorage.getItem("unsloth_auth_token") : false,
    serverUrl: typeof localStorage !== "undefined" ? localStorage.getItem("zopedia_server_url") : null,
    t0: Date.now(),
    events: [] as string[],
  };
}

function _startupLog(msg: string): void {
  console.debug("[zopedia:startup]", msg);
  const w = window as unknown as { __ZOPEDIA_STARTUP__?: { events: string[] } };
  w.__ZOPEDIA_STARTUP__?.events.push(`${Date.now()}: ${msg}`);
}
_startupLog(`module init: clientAuthLoading=${clientAuthLoading} clientMode=${isClientMode()} hasServer=${hasServerConfig()}`);

const listeners = new Set<Listener>();

export const clientAuthLoadingStore = {
  getSnapshot(): boolean {
    return clientAuthLoading;
  },
  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

function setClientAuthLoading(v: boolean): void {
  if (clientAuthLoading === v) return;
  clientAuthLoading = v;
  for (const l of listeners) l();
}

/** Clear the client auth loading flag — used when the user clicks "Disconnect"
 *  from the loading screen while the health check is still running, or when
 *  the health-check useEffect in RootLayout confirms the server is reachable. */
export function clearClientAuthLoading(): void {
  setClientAuthLoading(false);
}

async function hasActiveSession(): Promise<boolean> {
  if (hasAuthToken()) return true;
  if (!hasRefreshToken()) return false;
  return refreshSession();
}

interface AuthStatus {
  initialized: boolean;
  requires_password_change: boolean;
  auth_disabled?: boolean;
}

async function fetchAuthStatus(): Promise<AuthStatus> {
  try {
    const res = await fetch(apiUrl("/api/auth/status"));
    if (!res.ok) return { initialized: true, requires_password_change: mustChangePassword() };
    return (await res.json()) as AuthStatus;
  } catch {
    return { initialized: true, requires_password_change: mustChangePassword() };
  }
}

async function autoLogin(): Promise<void> {
  try {
    const res = await fetch(apiUrl("/api/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "zopedia", password: "zopedia" }),
    });
    if (!res.ok) return;
    const data = await res.json();
    if (data.access_token) {
      localStorage.setItem("unsloth_auth_token", data.access_token);
      if (data.refresh_token) {
        localStorage.setItem("unsloth_auth_refresh_token", data.refresh_token);
      }
    }
  } catch { /* fall through to login page */ }
}

function authRedirect(to: "/login" | "/change-password"): never {
  throw redirect({ to });
}

export async function requireAuth(): Promise<void> {
  console.log("[requireAuth] called, isTauri:", isTauri);

  if (isClientMode()) {
    _startupLog(`requireAuth: clientMode, hasServer=${hasServerConfig()} hasAuthToken=${hasAuthToken()} hasRefresh=${hasRefreshToken()}`);
    // Auth in client mode is split across two layers:
    //   1. beforeLoad (here) — fast gate: do we have tokens?
    //      Yes → let the route load. No → redirect to /connect.
    //   2. RootLayout useEffect — after first render, verify the server
    //      is actually reachable.  clientAuthLoading starts as `true` so
    //      the loading screen is visible from the very first paint.
    //   This separation means thread switches (which re-run beforeLoad)
    //   hit the fast path below and never flash the loading screen.
    if (!hasServerConfig()) {
      _startupLog("requireAuth: no server config → redirect /connect");
      setClientAuthLoading(false);
      throw redirect({ to: "/connect" });
    }

    // Fast path: valid access token.  Don't validate it — the health poll
    // monitors ongoing connectivity, and authFetch handles 401 → refresh.
    if (hasAuthToken()) {
      _startupLog("requireAuth: hasAuthToken → return (fast path)");
      return;
    }

    // No access token but we have a refresh token — try a quick refresh.
    if (hasRefreshToken()) {
      _startupLog("requireAuth: no auth token, trying refresh...");
      try {
        const refreshed = await refreshSession();
        _startupLog(`requireAuth: refresh result=${refreshed}`);
        if (refreshed) return;
      } catch { /* refreshSession handles its own errors */ }
    }

    // No tokens at all, or refresh failed — redirect to the connect page.
    _startupLog("requireAuth: no tokens → redirect /connect");
    setClientAuthLoading(false);
    logout();
    throw redirect({ to: "/connect" });
  }

  if (isTauri) {
    await tauriAutoAuth();
    return;
  }

  if (await hasActiveSession()) {
    const { requires_password_change } = await fetchAuthStatus();
    if (requires_password_change || mustChangePassword()) {
      authRedirect("/change-password");
    }
    return;
  }

  const status = await fetchAuthStatus();

  // Auth disabled: auto-login and skip the login screen entirely
  if (status.auth_disabled) {
    console.log("[requireAuth] auth disabled, auto-logging in");
    await autoLogin();
    console.log("[requireAuth] auto-login complete");
    return;
  }

  if (status.requires_password_change || mustChangePassword()) {
    authRedirect("/login");
  }
  // initialized=false means first run — redirect to set password
  authRedirect(status.initialized ? "/login" : "/change-password");
}

export async function requireGuest(): Promise<void> {
  if (isTauri) {
    await tauriAutoAuth();
    throw redirect({ to: "/chat" });
  }
  if (!(await hasActiveSession())) return;
  throw redirect({ to: getPostAuthRoute() });
}

export async function requirePasswordChangeFlow(): Promise<void> {
  if (isTauri) {
    await tauriAutoAuth();
    throw redirect({ to: "/chat" });
  }

  const status = await fetchAuthStatus();
  if (status.requires_password_change || mustChangePassword()) return;
  if (await hasActiveSession()) {
    throw redirect({ to: getPostAuthRoute() });
  }
  authRedirect(status.initialized ? "/login" : "/change-password");
}

// Guard for /connect (client mode only): if already configured with a live
// session, skip straight to the app.
export async function requireClientConnect(): Promise<void> {
  if (hasServerConfig() && (hasAuthToken() || (await refreshSession()))) {
    throw redirect({ to: "/chat" });
  }
}
