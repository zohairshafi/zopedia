// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { usePlatformStore } from "@/config/env";
import { isTauri } from "@/lib/api-base";
import { isClientMode } from "@/lib/mode";

export const AUTH_TOKEN_KEY = "unsloth_auth_token";
export const AUTH_REFRESH_TOKEN_KEY = "unsloth_auth_refresh_token";
export const ONBOARDING_DONE_KEY = "unsloth_onboarding_done";
export const AUTH_MUST_CHANGE_PASSWORD_KEY = "unsloth_auth_must_change_password";
const PERMISSIONS_KEY = "unsloth_auth_permissions";

export interface UserPermissions {
  can_save_chat_history: boolean;
  can_upload_files: boolean;
  is_admin: boolean;
}

const DEFAULT_PERMISSIONS: UserPermissions = {
  can_save_chat_history: true,
  can_upload_files: true,
  is_admin: false,
};

type PostAuthRoute = "/change-password" | "/chat";

function canUseStorage(): boolean {
  return typeof window !== "undefined";
}

export function hasAuthToken(): boolean {
  if (!canUseStorage()) return false;
  return Boolean(localStorage.getItem(AUTH_TOKEN_KEY));
}

export function hasRefreshToken(): boolean {
  if (!canUseStorage()) return false;
  return Boolean(localStorage.getItem(AUTH_REFRESH_TOKEN_KEY));
}

export function getAuthToken(): string | null {
  if (!canUseStorage()) return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  if (!canUseStorage()) return null;
  return localStorage.getItem(AUTH_REFRESH_TOKEN_KEY);
}

export function storeAuthTokens(
  accessToken: string,
  refreshToken: string,
  mustChangePassword = false,
  permissions?: UserPermissions,
): void {
  if (!canUseStorage()) return;
  localStorage.setItem(AUTH_TOKEN_KEY, accessToken);
  localStorage.setItem(AUTH_REFRESH_TOKEN_KEY, refreshToken);
  localStorage.setItem(AUTH_MUST_CHANGE_PASSWORD_KEY, String(mustChangePassword));
  if (permissions) storePermissions(permissions);
  window.dispatchEvent(new CustomEvent("auth-tokens-updated"));
}

export function clearAuthTokens(): void {
  if (!canUseStorage()) return;
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_REFRESH_TOKEN_KEY);
  localStorage.removeItem(AUTH_MUST_CHANGE_PASSWORD_KEY);
  localStorage.removeItem(PERMISSIONS_KEY);
}

export function storePermissions(permissions: UserPermissions): void {
  if (!canUseStorage()) return;
  try {
    localStorage.setItem(PERMISSIONS_KEY, JSON.stringify(permissions));
  } catch { /* storage full */ }
}

export function getPermissions(): UserPermissions {
  if (!canUseStorage()) return { ...DEFAULT_PERMISSIONS };
  try {
    const raw = localStorage.getItem(PERMISSIONS_KEY);
    if (!raw) return { ...DEFAULT_PERMISSIONS };
    const parsed = JSON.parse(raw);
    return {
      can_save_chat_history: parsed.can_save_chat_history ?? true,
      can_upload_files: parsed.can_upload_files ?? true,
      is_admin: parsed.is_admin ?? false,
    };
  } catch {
    return { ...DEFAULT_PERMISSIONS };
  }
}

export function clearPermissions(): void {
  if (!canUseStorage()) return;
  localStorage.removeItem(PERMISSIONS_KEY);
}

export function mustChangePassword(): boolean {
  if (!canUseStorage()) return false;
  return localStorage.getItem(AUTH_MUST_CHANGE_PASSWORD_KEY) === "true";
}

export function setMustChangePassword(required: boolean): void {
  if (!canUseStorage()) return;
  localStorage.setItem(AUTH_MUST_CHANGE_PASSWORD_KEY, String(required));
}

export function isOnboardingDone(): boolean {
  if (!canUseStorage()) return false;
  return localStorage.getItem(ONBOARDING_DONE_KEY) === "true";
}

export function markOnboardingDone(): void {
  if (!canUseStorage()) return;
  localStorage.setItem(ONBOARDING_DONE_KEY, "true");
}

export function resetOnboardingDone(): void {
  if (!canUseStorage()) return;
  localStorage.removeItem(ONBOARDING_DONE_KEY);
}

export function getPostAuthRoute(): PostAuthRoute {
  if (isClientMode()) return "/chat";
  if (isTauri) return "/chat";
  if (mustChangePassword()) return "/change-password";
  if (usePlatformStore.getState().isChatOnly()) return "/chat";
  return "/chat";
}
