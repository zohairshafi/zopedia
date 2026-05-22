import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { authFetch } from "@/features/auth";
import { apiUrl } from "@/lib/api-base";
import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { SettingsSection } from "../components/settings-section";
import { SettingsRow } from "../components/settings-row";

export function UsersTab() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showAdminPassword, setShowAdminPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  const canSubmit =
    username.trim().length > 0 && password.length >= 8 && adminPassword.length > 0 && !loading;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold font-heading">Users</h1>
        <p className="text-xs text-muted-foreground">
          Create new user accounts. Only the admin can add users.
        </p>
      </header>

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
    </div>
  );
}
