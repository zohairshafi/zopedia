// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { authFetch, storeAuthTokens } from "@/features/auth";
import { ProfilePersonalizationPanel } from "@/features/profile";
import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { SettingsSection } from "../components/settings-section";
import { SettingsRow } from "../components/settings-row";

export function ProfileTab() {
  // ── Change password form ──────────────────────────────────────────
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleChangePassword() {
    setError(null);

    if (!currentPassword) {
      setError("Current password is required.");
      return;
    }
    if (newPassword.length < 8) {
      setError("New password must be at least 8 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match.");
      return;
    }

    setSaving(true);
    try {
      const res = await authFetch("/api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => null);
        setError(err?.detail ?? "Failed to change password.");
        return;
      }

      const data = await res.json();
      if (data.access_token && data.refresh_token) {
        storeAuthTokens(data.access_token, data.refresh_token, false);
      }

      toast.success("Password changed successfully.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch {
      setError("Could not reach server.");
    } finally {
      setSaving(false);
    }
  }

  const canSave =
    currentPassword.length > 0 &&
    newPassword.length >= 8 &&
    confirmPassword.length > 0 &&
    !saving;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold font-heading">Profile</h1>
        <p className="text-xs text-muted-foreground">
          Update how your profile appears and manage your account security.
        </p>
      </header>

      <ProfilePersonalizationPanel />

      {/* ── Change password ────────────────────────────────────────── */}
      <SettingsSection
        title="Change password"
        description="Update your account password. You'll stay logged in after changing it."
      >
        <SettingsRow label="Current password">
          <div className="relative max-w-[200px]">
            <Input
              type={showCurrent ? "text" : "password"}
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="pr-10"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:bg-transparent"
              onClick={() => setShowCurrent((p) => !p)}
            >
              {showCurrent ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          </div>
        </SettingsRow>
        <SettingsRow label="New password">
          <div className="relative max-w-[200px]">
            <Input
              type={showNew ? "text" : "password"}
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              minLength={8}
              className="pr-10"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:bg-transparent"
              onClick={() => setShowNew((p) => !p)}
            >
              {showNew ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          </div>
        </SettingsRow>
        <SettingsRow label="Confirm new password">
          <div className="relative max-w-[200px]">
            <Input
              type={showConfirm ? "text" : "password"}
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              minLength={8}
              className="pr-10"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:bg-transparent"
              onClick={() => setShowConfirm((p) => !p)}
            >
              {showConfirm ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          </div>
        </SettingsRow>

        {error && <p className="px-0 py-2 text-sm text-destructive">{error}</p>}

        <div className="flex items-center justify-end pt-4">
          <Button onClick={handleChangePassword} disabled={!canSave}>
            {saving ? "Saving..." : "Change Password"}
          </Button>
        </div>
      </SettingsSection>
    </div>
  );
}
