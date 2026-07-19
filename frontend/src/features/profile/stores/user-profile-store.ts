// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { authFetch, getAuthToken } from "@/features/auth";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { PersistStorage, StorageValue } from "zustand/middleware";
import { decodeJwtSubject } from "../utils/jwt-subject";

export interface UserProfileState {
  displayName: string;
  avatarDataUrl: string | null;
  setDisplayName: (displayName: string) => void;
  setAvatarDataUrl: (avatarDataUrl: string | null) => void;
}

export function getProfileStorageKey(): string {
  const STORE_NAME = "zopedia_user_profile";
  const token = getAuthToken();
  const username = decodeJwtSubject(token);
  const key = username ? `${STORE_NAME}_${username}` : STORE_NAME;
  console.log("[profile] getProfileStorageKey", { hasToken: !!token, username, key });
  return key;
}

const OLD_KEY = "unsloth_user_profile";

function readAndParse(key: string): StorageValue<UserProfileState> | null {
  const raw = localStorage.getItem(key);
  if (raw === null) return null;
  try {
    return JSON.parse(raw) as StorageValue<UserProfileState>;
  } catch {
    return null;
  }
}

const namespacedStorage: PersistStorage<UserProfileState> = {
  getItem: (_name) => {
    const key = getProfileStorageKey();
    const existing = readAndParse(key);
    console.log("[profile] storage.getItem", { key, found: !!existing });
    if (existing) return existing;

    // Migration: data from before namespaced keys was stored under a single key
    const legacy = readAndParse(OLD_KEY);
    if (legacy) {
      console.log("[profile] migrating legacy key", { oldKey: OLD_KEY, newKey: key });
      localStorage.setItem(key, JSON.stringify(legacy));
      localStorage.removeItem(OLD_KEY);
      return legacy;
    }
    return null;
  },
  setItem: (_name, value) => {
    const key = getProfileStorageKey();
    console.log("[profile] storage.setItem", { key, displayName: (value.state as any)?.displayName });
    localStorage.setItem(key, JSON.stringify(value));
  },
  removeItem: (_name) => {
    localStorage.removeItem(getProfileStorageKey());
  },
};

function getInitialProfile(): { displayName: string; avatarDataUrl: string | null } {
  const key = getProfileStorageKey();
  const existing = readAndParse(key);
  console.log("[profile] getInitialProfile", { key, found: !!existing, displayName: (existing?.state as any)?.displayName });
  if (existing) return existing.state as { displayName: string; avatarDataUrl: string | null };

  const legacy = readAndParse(OLD_KEY);
  if (legacy) {
    console.log("[profile] getInitialProfile migrating legacy", { oldKey: OLD_KEY, newKey: key });
    localStorage.setItem(key, JSON.stringify(legacy));
    localStorage.removeItem(OLD_KEY);
    return legacy.state as { displayName: string; avatarDataUrl: string | null };
  }
  return { displayName: "", avatarDataUrl: null };
}

const initialProfile = getInitialProfile();

export const useUserProfileStore = create<UserProfileState>()(
  persist(
    (set) => ({
      displayName: initialProfile.displayName,
      avatarDataUrl: initialProfile.avatarDataUrl,
      setDisplayName: (displayName) => set({ displayName }),
      setAvatarDataUrl: (avatarDataUrl) => set({ avatarDataUrl }),
    }),
    {
      name: "zopedia_user_profile",
      storage: namespacedStorage,
    },
  ),
);

// ── Cross-machine profile sync (display name only) ───────────────────
// Server is the source of truth so a name set on one machine populates on
// all others. Avatar stays local per the chosen scope.

let _loadedForSubject: string | null = null;

export async function loadProfileFromServer(): Promise<void> {
  const token = getAuthToken();
  const username = decodeJwtSubject(token) ?? "";
  if (!username) return;
  if (_loadedForSubject === username) return; // already loaded for this user
  _loadedForSubject = username;
  try {
    const res = await authFetch("/api/auth/profile", { cache: "no-store" });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      console.error("[profile] GET /api/auth/profile failed", res.status, body);
      _loadedForSubject = null; // allow a later retry
      return;
    }
    const data = await res.json();
    const name = typeof data.display_name === "string" ? data.display_name.trim() : "";
    const store = useUserProfileStore.getState();
    if (name) {
      console.info("[profile] loaded name from server", { name });
      if (name !== store.displayName) store.setDisplayName(name);
    } else {
      // First-time migration: seed the server from the local name (if any).
      const local = store.displayName.trim();
      if (local) saveProfileNameToServer(local);
    }
  } catch (e) {
    console.error("[profile] loadProfileFromServer threw", e);
    _loadedForSubject = null;
  }
}

export function saveProfileNameToServer(name: string): void {
  authFetch("/api/auth/profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: name }),
  })
    .then(async (res) => {
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        console.error("[profile] PUT /api/auth/profile failed", res.status, body);
      } else {
        console.info("[profile] saved name to server", { name });
      }
    })
    .catch((e) => {
      console.error("[profile] PUT /api/auth/profile threw", e);
    });
}

if (typeof window !== "undefined") {
  window.addEventListener("auth-tokens-updated", () => {
    useUserProfileStore.persist.rehydrate();
    void loadProfileFromServer();
  });
  // Cold load: user may already be authenticated (token already in localStorage).
  void loadProfileFromServer();
}
