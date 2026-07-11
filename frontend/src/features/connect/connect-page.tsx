// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { LightRays } from "@/components/ui/light-rays";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useNavigate } from "@tanstack/react-router";
import { Eye, EyeOff, X } from "lucide-react";
import { useState, useRef, type SyntheticEvent } from "react";
import { connectToServer, getRecentServers, removeRecentServer, type RecentServer } from "./connect";

export function ConnectPage() {
  const navigate = useNavigate();
  const passwordRef = useRef<HTMLInputElement>(null);

  const [recentServers, setRecentServers] = useState<RecentServer[]>(getRecentServers);
  const [serverUrl, setServerUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function selectServer(s: RecentServer) {
    setServerUrl(s.url);
    setUsername(s.username);
    setPassword("");
    setError(null);
    // Focus the password field after React commits the render
    requestAnimationFrame(() => passwordRef.current?.focus());
  }

  function clearSelection() {
    setServerUrl("");
    setUsername("");
    setPassword("");
    setError(null);
  }

  function handleRemove(e: React.MouseEvent, url: string) {
    e.stopPropagation();
    removeRecentServer(url);
    setRecentServers(getRecentServers());
  }

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await connectToServer(serverUrl, username, password);
      navigate({ to: "/chat" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect to server.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background px-4 py-8 sm:px-6 sm:py-10 md:px-10">
      <LightRays
        count={6}
        color="rgba(34, 197, 94, 0.25)"
        blur={34}
        speed={15}
        length="70vh"
        style={{ opacity: 0.4 }}
      />
      <Card className="relative z-10 w-full max-w-sm px-5 py-6 shadow-border ring-1 ring-border sm:px-6 sm:py-8">
        <div className="w-full max-w-sm space-y-6">
          <div className="space-y-1.5 text-center">
            <img
              src="logo_main_light.png"
              alt="Zopedia mascot"
              className="mx-auto mb-2 h-40 w-40 object-contain"
            />
            <h2 className="text-2xl font-semibold text-foreground">Connect to server</h2>
            <p className="text-muted-foreground">
              Enter your Zopedia server address and sign in.
            </p>
          </div>

          {/* ── Recent servers ──────────────────────────────────────── */}
          {recentServers.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">Recent servers</p>
              <div className="space-y-1.5">
                {recentServers.map((s) => {
                  const isSelected = serverUrl === s.url && username === s.username;
                  return (
                    <button
                      key={s.url}
                      type="button"
                      onClick={() => selectServer(s)}
                      className={`w-full flex items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors ${
                        isSelected
                          ? "border-primary/50 bg-primary/5"
                          : "border-border hover:bg-muted/50"
                      }`}
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-foreground">
                          {s.url.replace(/^https?:\/\//, "")}
                        </p>
                        <p className="text-xs text-muted-foreground">{s.username}</p>
                      </div>
                      <button
                        type="button"
                        onClick={(e) => handleRemove(e, s.url)}
                        className="flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
                        aria-label={`Forget ${s.url}`}
                      >
                        <X className="size-3" />
                      </button>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Connection form ─────────────────────────────────────── */}
          <form className="space-y-5" onSubmit={handleSubmit}>
            {serverUrl && (
              <div className="flex items-center gap-2">
                <p className="text-xs text-muted-foreground truncate flex-1">
                  Connecting to <span className="font-medium text-foreground">{serverUrl}</span>
                  {" "}as <span className="font-medium text-foreground">{username}</span>
                </p>
                <button
                  type="button"
                  onClick={clearSelection}
                  className="text-xs text-muted-foreground hover:text-foreground shrink-0"
                >
                  Change
                </button>
              </div>
            )}
            {!serverUrl && (
              <>
                <div className="space-y-2">
                  <Label htmlFor="server-url">Server URL</Label>
                  <Input
                    id="server-url"
                    type="url"
                    inputMode="url"
                    autoComplete="url"
                    placeholder="https://zopedia.example.com"
                    value={serverUrl}
                    onChange={(e) => setServerUrl(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="username">Username</Label>
                  <Input
                    id="username"
                    type="text"
                    autoComplete="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    required
                  />
                </div>
              </>
            )}
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <div className="relative">
                <Input
                  id="password"
                  ref={passwordRef}
                  type={showPassword ? "text" : "password"}
                  className="pr-10"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  minLength={8}
                  required
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:bg-transparent"
                  onClick={() => setShowPassword((prev) => !prev)}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </Button>
              </div>
            </div>
            {error && <p className="text-center text-sm text-destructive">{error}</p>}
            <Button
              type="submit"
              className="w-full"
              disabled={loading || !serverUrl || username.trim().length === 0 || password.length < 8}
            >
              {loading ? "Connecting..." : "Connect"}
            </Button>
          </form>
        </div>
      </Card>
    </div>
  );
}
