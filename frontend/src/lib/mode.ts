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

// True ONLY when running inside the native iOS Capacitor app (not the PWA/web
// build). Capacitor's native bridge injects `window.Capacitor` before the page
// loads; in a plain browser or the PWA it is undefined. Used for iOS-only UX
// tweaks (e.g. docking the composer at the bottom on the New Chat screen).
export function isNativeIOS(): boolean {
  if (typeof window === "undefined") return false;
  const cap = (window as { Capacitor?: { getPlatform?: () => string; platform?: string } })
    .Capacitor;
  return !!cap && (cap.getPlatform?.() === "ios" || cap.platform === "ios");
}
