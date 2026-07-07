// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

// Build-time mode flag. The client SPA is produced with
// `vite build --mode client` (loads .env.client → VITE_ZOPEDIA_MODE=client) and
// connects to a remote server. The default build omits the flag → full
// co-located server mode. Because this is a build-time constant, dead branches
// are tree-shaken from the bundle.

// localStorage key holding the server URL the client last connected to.
// Shared by lib/api-base (reads it at startup) and features/connect (writes it).
export const SERVER_URL_KEY = "zopedia_server_url";

export function isClientMode(): boolean {
  return import.meta.env.VITE_ZOPEDIA_MODE === "client";
}

export function isServerMode(): boolean {
  return !isClientMode();
}
