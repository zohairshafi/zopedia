import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { authFetch } from "@/features/auth";
import { apiUrl } from "@/lib/api-base";
import { Eye, EyeOff, Trash2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { SettingsSection } from "../components/settings-section";
import { SettingsRow } from "../components/settings-row";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

interface UserEntry {
  username: string;
  must_change_password: boolean;
}

export function UsersTab() {
  // ── Create user form ────────────────────────────────────────────
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showAdminPassword, setShowAdminPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── User list ────────────────────────────────────────────────────
  const [users, setUsers] = useState<UserEntry[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  // ── Reset password ───────────────────────────────────────────────
  const [resetTarget, setResetTarget] = useState<string | null>(null);
  const [resetLoading, setResetLoading] = useState(false);
  const [newPassword, setNewPassword] = useState("");

  // ── Delete user ──────────────────────────────────────────────────
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  const fetchUsers = useCallback(async () => {
    setListLoading(true);
    setListError(null);
    try {
      const res = await authFetch("/api/auth/users");
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        setListError(err?.detail ?? "Failed to load users.");
        return;
      }
      const data = await res.json();
      setUsers(data.users ?? []);
    } catch {
      setListError("Could not reach server.");
    } finally {
      setListLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchUsers();
  }, [fetchUsers]);

  // ── Create user ──────────────────────────────────────────────────

  async function handleCreate() {
    setError(null);

    if (!username.trim()) {
      setError("Username is required.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (!adminPassword) {
      setError("Admin password is required.");
      return;
    }

    setLoading(true);
    try {
      // Verify admin password
      const loginRes = await fetch(apiUrl("/api/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: "zopedia", password: adminPassword }),
      });
      if (!loginRes.ok) {
        const err = await loginRes.json().catch(() => null);
        setError(err?.detail ?? "Admin password is incorrect.");
        return;
      }

      // Create the new user
      const registerRes = await authFetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      if (!registerRes.ok) {
        const err = await registerRes.json().catch(() => null);
        setError(err?.detail ?? "Failed to create user.");
        return;
      }

      toast.success(`User "${username.trim()}" created.`);
      setUsername("");
      setPassword("");
      setAdminPassword("");
      void fetchUsers();
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  // ── Reset password ───────────────────────────────────────────────

  async function handleResetPassword(targetUsername: string) {
    setResetLoading(true);
    try {
      const body: Record<string, string> = {};
      if (newPassword.trim()) {
        body.new_password = newPassword.trim();
      }
      const res = await authFetch(
        `/api/auth/users/${encodeURIComponent(targetUsername)}/reset-password`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        toast.error(err?.detail ?? "Failed to reset password.");
        return;
      }
      const data = await res.json();
      if (data.password) {
        toast.success(`Password reset for ${targetUsername}`, {
          description: `New password: ${data.password}`,
          duration: 30000,
        });
      } else {
        toast.success(`Password reset for ${targetUsername}`);
      }
      setResetTarget(null);
      setNewPassword("");
      void fetchUsers();
    } catch {
      toast.error("An unexpected error occurred.");
    } finally {
      setResetLoading(false);
    }
  }

  // ── Delete user ──────────────────────────────────────────────────

  async function handleDelete(targetUsername: string) {
    setDeleteLoading(true);
    try {
      const res = await authFetch(
        `/api/auth/users/${encodeURIComponent(targetUsername)}`,
        { method: "DELETE" },
      );
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        toast.error(err?.detail ?? "Failed to delete user.");
        return;
      }
      toast.success(`User "${targetUsername}" deleted.`);
      setDeleteTarget(null);
      void fetchUsers();
    } catch {
      toast.error("An unexpected error occurred.");
    } finally {
      setDeleteLoading(false);
    }
  }

  const canSubmit =
    username.trim().length > 0 && password.length >= 8 && adminPassword.length > 0 && !loading;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold font-heading">Users</h1>
        <p className="text-xs text-muted-foreground">
          Manage user accounts. Only the admin can create, reset, or delete users.
        </p>
      </header>

      {/* ── Existing users ──────────────────────────────────────── */}
      <SettingsSection title="Existing users">
        {listLoading ? (
          <p className="text-xs text-muted-foreground py-2">Loading…</p>
        ) : listError ? (
          <p className="text-xs text-destructive py-2">{listError}</p>
        ) : users.length === 0 ? (
          <p className="text-xs text-muted-foreground py-2">No users found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">Username</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium" />
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.username} className="border-b border-border/50 last:border-0">
                    <td className="py-2 pr-4">
                      <span className="font-medium">{u.username}</span>
                      {u.username === "zopedia" && (
                        <span className="ml-1.5 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                          ADMIN
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-4 text-xs text-muted-foreground">
                      {u.must_change_password ? "Password change required" : "Active"}
                    </td>
                    <td className="py-2">
                      <div className="flex items-center gap-1 justify-end">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-8 text-muted-foreground hover:text-foreground"
                          onClick={() => {
                            setResetTarget(u.username);
                            setNewPassword("");
                          }}
                          title="Reset password"
                        >
                          <RefreshCw className="size-3.5" />
                        </Button>
                        {u.username !== "zopedia" && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-8 text-muted-foreground hover:text-destructive"
                            onClick={() => setDeleteTarget(u.username)}
                            title="Delete user"
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SettingsSection>

      {/* ── Create a user ────────────────────────────────────────── */}
      <SettingsSection title="Create a user">
        <SettingsRow label="Username">
          <Input
            autoComplete="off"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="max-w-[200px]"
          />
        </SettingsRow>
        <SettingsRow label="Password">
          <div className="relative max-w-[200px]">
            <Input
              type={showPassword ? "text" : "password"}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              className="pr-10"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:bg-transparent"
              onClick={() => setShowPassword((p) => !p)}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          </div>
        </SettingsRow>
        <SettingsRow label="Admin password">
          <div className="relative max-w-[200px]">
            <Input
              type={showAdminPassword ? "text" : "password"}
              autoComplete="current-password"
              value={adminPassword}
              onChange={(e) => setAdminPassword(e.target.value)}
              className="pr-10"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:bg-transparent"
              onClick={() => setShowAdminPassword((p) => !p)}
            >
              {showAdminPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          </div>
        </SettingsRow>

        {error && <p className="px-0 py-2 text-sm text-destructive">{error}</p>}

        <div className="flex items-center justify-end pt-4">
          <Button onClick={handleCreate} disabled={!canSubmit}>
            {loading ? "Creating..." : "Create User"}
          </Button>
        </div>
      </SettingsSection>

      {/* ── Reset password dialog ────────────────────────────────── */}
      <AlertDialog open={resetTarget !== null} onOpenChange={(o) => { if (!o) setResetTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reset password for {resetTarget}</AlertDialogTitle>
            <AlertDialogDescription>
              Leave blank to auto-generate a 4-word diceware passphrase.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <Input
            type="text"
            autoComplete="off"
            placeholder="New password (optional)"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            minLength={8}
            className="mt-2"
          />
          <AlertDialogFooter className="mt-4">
            <AlertDialogCancel disabled={resetLoading}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={resetLoading}
              onClick={() => { if (resetTarget) void handleResetPassword(resetTarget); }}
            >
              {resetLoading ? "Resetting..." : "Reset Password"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* ── Delete user confirmation dialog ──────────────────────── */}
      <AlertDialog open={deleteTarget !== null} onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete user {deleteTarget}?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete this user and all their refresh tokens.
              Their chat history will remain in the database.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteLoading}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={deleteLoading}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => { if (deleteTarget) void handleDelete(deleteTarget); }}
            >
              {deleteLoading ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
