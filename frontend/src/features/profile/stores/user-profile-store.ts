// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { getAuthToken } from "@/features/auth";
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

if (typeof window !== "undefined") {
  window.addEventListener("auth-tokens-updated", () => {
    useUserProfileStore.persist.rehydrate();
  });
}
