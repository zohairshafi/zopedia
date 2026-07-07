// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { LightRays } from "@/components/ui/light-rays";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useNavigate } from "@tanstack/react-router";
import { Eye, EyeOff } from "lucide-react";
import { useState, type SyntheticEvent } from "react";
import { connectToServer, getServerUrl } from "./connect";

export function ConnectPage() {
  const navigate = useNavigate();
  const [serverUrl, setServerUrl] = useState(() => getServerUrl() ?? "");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
          <form className="space-y-5" onSubmit={handleSubmit}>
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
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <div className="relative">
                <Input
                  id="password"
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
              disabled={loading || username.trim().length === 0 || password.length < 8}
            >
              {loading ? "Connecting..." : "Connect"}
            </Button>
          </form>
        </div>
      </Card>
    </div>
  );
}
