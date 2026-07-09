// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { apiUrl } from "@/lib/api-base";
import { create } from "zustand";

export const env = {
  MODE: import.meta.env.MODE,
  DEV: import.meta.env.DEV,
  PROD: import.meta.env.PROD,
  BASE_URL: import.meta.env.BASE_URL,
} as const;

// ── Platform / device type ──────────────────────────────────

export type DeviceType = "mac" | "windows" | "linux" | string;

interface PlatformState {
  deviceType: DeviceType;
  chatOnly: boolean;
  fetched: boolean;
  isChatOnly: () => boolean;
  upstreamProvider: string;
  upstreamModel: string;
}

// Client-side platform detection as fallback when backend isn't ready yet.
function detectLocalPlatform(): DeviceType {
  if (typeof navigator === "undefined") return "linux";
  const platform = navigator.platform.toLowerCase();
  const ua = navigator.userAgent.toLowerCase();
  if (platform.includes("mac") || ua.includes("mac")) return "mac";
  if (platform.includes("win") || ua.includes("win")) return "windows";
  return "linux";
}

const localDeviceType = detectLocalPlatform();

export const usePlatformStore = create<PlatformState>()((_, get) => ({
  deviceType: localDeviceType,
  chatOnly: false,
  fetched: false,
  isChatOnly: () => get().chatOnly,
  upstreamProvider: "",
  upstreamModel: "",
}));

export async function fetchDeviceType(): Promise<DeviceType> {
  const { fetched } = usePlatformStore.getState();
  if (fetched) return usePlatformStore.getState().deviceType;

  try {
    const res = await fetch(apiUrl("/api/health"), {
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) {
      const data = (await res.json()) as { device_type?: string; chat_only?: boolean; llm_provider?: string; llm_model?: string };
      const deviceType = data.device_type ?? detectLocalPlatform();
      const chatOnly = data.chat_only ?? false;
      const upstreamProvider = data.llm_provider ?? "";
      const upstreamModel = data.llm_model ?? "";
      usePlatformStore.setState({ deviceType, chatOnly, fetched: true, upstreamProvider, upstreamModel });
      return deviceType;
    }
  } catch {
    // Server unreachable — use local platform detection and mark as
    // fetched so we don't retry on every beforeLoad (which would add
    // another timeout delay before any component renders).
    const deviceType = detectLocalPlatform();
    const chatOnly = false;
    usePlatformStore.setState({ deviceType, chatOnly, fetched: true });
    return deviceType;
  }

  return usePlatformStore.getState().deviceType;
}
