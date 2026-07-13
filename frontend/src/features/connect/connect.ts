// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { applyServerUrl } from "@/lib/api-base";
import { SERVER_URL_KEY } from "@/lib/mode";
import { storeAuthTokens, clearAuthTokens } from "@/features/auth";

type TokenResponse = {
  access_token: string;
  refresh_token: string;
  must_change_password: boolean;
  permissions?: { can_save_chat_history?: boolean; can_upload_files?: boolean };
};

export interface RecentServer {
  url: string;
  username: string;
}

const RECENT_SERVERS_KEY = "zopedia_recent_servers";
const MAX_RECENT_SERVERS = 5;

function normalizeUrl(raw: string): string {
  return raw.trim().replace(/\/+$/, "");
}

export function getServerUrl(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(SERVER_URL_KEY);
}

export function hasServerConfig(): boolean {
  return getServerUrl() !== null;
}

/** Return the list of previously connected servers, most recent first. */
export function getRecentServers(): RecentServer[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(RECENT_SERVERS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (s): s is RecentServer =>
        typeof s === "object" && s !== null &&
        typeof s.url === "string" && s.url.length > 0 &&
        typeof s.username === "string" && s.username.length > 0,
    );
  } catch {
    return [];
  }
}

/** Add or move a server to the top of the recent list. */
function saveRecentServer(url: string, username: string): void {
  if (typeof window === "undefined") return;
  const servers = getRecentServers().filter((s) => s.url !== url);
  servers.unshift({ url, username });
  if (servers.length > MAX_RECENT_SERVERS) servers.length = MAX_RECENT_SERVERS;
  try {
    localStorage.setItem(RECENT_SERVERS_KEY, JSON.stringify(servers));
  } catch { /* storage full — silently drop */ }
}

/** Remove a server from the recent list. */
export function removeRecentServer(url: string): void {
  if (typeof window === "undefined") return;
  const servers = getRecentServers().filter((s) => s.url !== url);
  try {
    localStorage.setItem(RECENT_SERVERS_KEY, JSON.stringify(servers));
  } catch { /* ignore */ }
}

/**
 * Authenticate against a remote Zopedia server and persist the connection.
 * On success the server URL and JWT tokens are stored, and the API base is
 * pointed at the server so all subsequent requests go there.
 */
export async function connectToServer(
  rawUrl: string,
  username: string,
  password: string,
): Promise<void> {
  const url = normalizeUrl(rawUrl);
  if (!/^https?:\/\//i.test(url)) {
    throw new Error("Server URL must start with http:// or https://");
  }

  let response: Response;
  try {
    response = await fetch(`${url}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username.trim(), password }),
    });
  } catch {
    throw new Error(`Could not reach server at ${url}. Check the URL and your connection.`);
  }

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Login failed. Check your credentials and server URL.");
  }

  const token = (await response.json()) as TokenResponse;
  localStorage.setItem(SERVER_URL_KEY, url);
  saveRecentServer(url, username.trim());
  applyServerUrl(url);
  storeAuthTokens(
    token.access_token,
    token.refresh_token,
    token.must_change_password,
    token.permissions as { can_save_chat_history: boolean; can_upload_files: boolean } | undefined,
  );
}

/** Clear the stored server URL and auth tokens — returns the user to /connect. */
export function disconnectFromServer(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(SERVER_URL_KEY);
  clearAuthTokens();
}
