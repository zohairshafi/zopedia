// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { redirect } from "@tanstack/react-router";
import { apiUrl, isTauri } from "@/lib/api-base";
import {
  getPostAuthRoute,
  hasAuthToken,
  hasRefreshToken,
  mustChangePassword,
  refreshSession,
  tauriAutoAuth,
} from "@/features/auth";

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
