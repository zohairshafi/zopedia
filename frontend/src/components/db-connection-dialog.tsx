// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { authFetch } from "@/features/auth";
import { cn } from "@/lib/utils";
import { CheckmarkCircle01Icon, CircleIcon, DatabaseIcon, EyeIcon, ViewOffSlashIcon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useEffect, useState } from "react";

interface TableInfo {
  schema: string;
  table: string;
  approx_rows: number;
}

interface DbConnectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialUrl: string;
  allowedTables: string;
  onConnectionSaved: (url: string, allowedTables: string) => void;
}

function parseUrl(url: string): {
  host: string;
  port: string;
  dbname: string;
  user: string;
  password: string;
} {
  if (!url) return { host: "localhost", port: "5432", dbname: "", user: "", password: "" };
  try {
    // Handle postgresql://user:pass@host:port/dbname
    const stripped = url.replace(/^postgres(ql)?:\/\//i, "");
    const atIndex = stripped.lastIndexOf("@");
    if (atIndex === -1) return { host: "localhost", port: "5432", dbname: "", user: "", password: "" };

    const userPass = stripped.slice(0, atIndex);
    const hostDb = stripped.slice(atIndex + 1);

    const colonIndex = userPass.indexOf(":");
    const user = colonIndex >= 0 ? decodeURIComponent(userPass.slice(0, colonIndex)) : decodeURIComponent(userPass);
    const password = colonIndex >= 0 ? decodeURIComponent(userPass.slice(colonIndex + 1)) : "";

    const slashIndex = hostDb.indexOf("/");
    const hostPort = slashIndex >= 0 ? hostDb.slice(0, slashIndex) : hostDb;
    const dbname = slashIndex >= 0 ? hostDb.slice(slashIndex + 1) : "";

    const portColonIndex = hostPort.lastIndexOf(":");
    const host = portColonIndex >= 0 ? hostPort.slice(0, portColonIndex) : hostPort;
    const port = portColonIndex >= 0 ? hostPort.slice(portColonIndex + 1) : "5432";

    return { host, port, dbname, user, password };
  } catch {
    return { host: "localhost", port: "5432", dbname: "", user: "", password: "" };
  }
}

function buildUrl(
  host: string,
  port: string,
  dbname: string,
  user: string,
  password: string,
): string {
  if (!host || !dbname || !user) return "";
  const encodedUser = encodeURIComponent(user);
  const encodedPass = encodeURIComponent(password);
  return `postgresql://${encodedUser}:${encodedPass}@${host}:${port}/${dbname}`;
}

export function DbConnectionDialog({
  open,
  onOpenChange,
  initialUrl,
  allowedTables,
  onConnectionSaved,
}: DbConnectionDialogProps) {
  const [host, setHost] = useState("localhost");
  const [port, setPort] = useState("5432");
  const [dbname, setDbname] = useState("");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [selectedTables, setSelectedTables] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);

  // Parse initial URL on open
  useEffect(() => {
    if (!open) return;
    const parsed = parseUrl(initialUrl);
    setHost(parsed.host);
    setPort(parsed.port);
    setDbname(parsed.dbname);
    setUser(parsed.user);
    setPassword(parsed.password);
    setTestError(null);
    setTables([]);
    setSelectedTables(new Set());
    setSaving(false);
    setShowPassword(false);
  }, [open, initialUrl]);

  // Pre-select previously allowed tables after fetching
  useEffect(() => {
    if (tables.length === 0) return;
    const prev = allowedTables
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    if (prev.length > 0) {
      const preselected = new Set<string>();
      for (const t of tables) {
        const fq = `${t.schema}.${t.table}`;
        if (prev.includes(fq)) preselected.add(fq);
      }
      if (preselected.size > 0) setSelectedTables(preselected);
    }
  }, [tables, allowedTables]);

  const handleTest = async () => {
    if (!host.trim() || !dbname.trim() || !user.trim()) return;
    setTesting(true);
    setTestError(null);
    setTables([]);
    setSelectedTables(new Set());
    try {
      const res = await authFetch("/api/db/test-connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host: host.trim(),
          port: parseInt(port, 10) || 5432,
          dbname: dbname.trim(),
          user: user.trim(),
          password,
        }),
      });
      const data = await res.json();
      if (data.status === "ok") {
        setTables(data.tables ?? []);
        setSelectedTables(new Set());
      } else {
        setTestError(data.detail ?? "Connection failed.");
      }
    } catch (err) {
      setTestError(err instanceof Error ? err.message : "Could not reach backend.");
    } finally {
      setTesting(false);
    }
  };

  const toggleTable = (fq: string) => {
    setSelectedTables((prev) => {
      const next = new Set(prev);
      if (next.has(fq)) next.delete(fq);
      else next.add(fq);
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedTables.size === tables.length) {
      setSelectedTables(new Set());
    } else {
      setSelectedTables(new Set(tables.map((t) => `${t.schema}.${t.table}`)));
    }
  };

  const handleSave = () => {
    const url = buildUrl(host.trim(), port.trim(), dbname.trim(), user.trim(), password);
    if (!url) return;
    setSaving(true);
    const allowed = Array.from(selectedTables).join(",");
    onConnectionSaved(url, allowed);
    onOpenChange(false);
  };

  const canTest = host.trim() && dbname.trim() && user.trim() && !testing;
  const hasTables = tables.length > 0;
  const canSave = hasTables && !saving;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg gap-4 p-0 sm:max-w-[min(90vw,520px)]">
        <DialogHeader className="border-b border-border/70 px-6 pt-5 pb-4">
          <DialogTitle className="font-heading text-lg flex items-center gap-2">
            <HugeiconsIcon icon={DatabaseIcon} className="size-5 text-muted-foreground" />
            Database Connection Setup
          </DialogTitle>
          <DialogDescription>
            Test your PostgreSQL connection and select which tables to expose.
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="max-h-[min(62vh,520px)] px-6 pb-2">
          <div className="flex flex-col gap-4 py-2">
            {/* ── Connection fields ─────────────────────────────── */}
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs">Host</Label>
                <Input
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                  placeholder="localhost"
                  className="h-8 text-sm"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs">Port</Label>
                <Input
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                  placeholder="5432"
                  className="h-8 text-sm"
                />
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label className="text-xs">Database</Label>
              <Input
                value={dbname}
                onChange={(e) => setDbname(e.target.value)}
                placeholder="mydb"
                className="h-8 text-sm"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs">Username</Label>
                <Input
                  value={user}
                  onChange={(e) => setUser(e.target.value)}
                  placeholder="postgres"
                  className="h-8 text-sm"
                  autoComplete="off"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs">Password</Label>
                <div className="relative">
                  <Input
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="h-8 pr-8 text-sm"
                    autoComplete="off"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((p) => !p)}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                  >
                    <HugeiconsIcon
                      icon={showPassword ? ViewOffSlashIcon : EyeIcon}
                      className="size-3.5"
                    />
                  </button>
                </div>
              </div>
            </div>

            <Button
              type="button"
              variant="dark"
              size="sm"
              onClick={handleTest}
              disabled={!canTest}
              className="self-start"
            >
              {testing ? "Testing…" : "Test & Fetch Tables"}
            </Button>

            {/* ── Error ──────────────────────────────────────────── */}
            {testError && (
              <div className="rounded-md border border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                {testError}
              </div>
            )}

            {/* ── Table selector ─────────────────────────────────── */}
            {hasTables && (
              <div className="flex flex-col gap-2 rounded-lg border border-border/70 bg-background/60 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold">
                    Tables ({tables.length})
                  </span>
                  <button
                    type="button"
                    onClick={toggleAll}
                    className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {selectedTables.size === tables.length ? "Deselect All" : "Select All"}
                  </button>
                </div>

                <div className="flex flex-col gap-0.5 max-h-[200px] overflow-y-auto">
                  {tables.map((t) => {
                    const fq = `${t.schema}.${t.table}`;
                    const checked = selectedTables.has(fq);
                    return (
                      <label
                        key={fq}
                        onClick={() => toggleTable(fq)}
                        className={cn(
                          "flex items-center gap-2 rounded-md px-2 py-1.5 cursor-pointer transition-colors hover:bg-accent/50",
                          checked && "bg-accent/30",
                        )}
                      >
                        <HugeiconsIcon
                          icon={checked ? CheckmarkCircle01Icon : CircleIcon}
                          className={cn(
                            "size-4 shrink-0",
                            checked ? "text-primary" : "text-muted-foreground",
                          )}
                        />
                        <span className="flex-1 truncate text-sm font-mono">
                          {fq}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </ScrollArea>

        <DialogFooter className="border-t border-border/70 px-6 py-4">
          <div className="flex items-center justify-end gap-2 w-full">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="dark"
              onClick={handleSave}
              disabled={!canSave}
            >
              {saving ? "Saving…" : `Save Connection${selectedTables.size > 0 ? ` (${selectedTables.size} tables)` : ""}`}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
