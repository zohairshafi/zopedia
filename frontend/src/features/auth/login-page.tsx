// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { LightRays } from "@/components/ui/light-rays";
import { Card } from "@/components/ui/card";
import { AuthForm } from "./components/auth-form";
import { useEffect, useState } from "react";
import { apiUrl } from "@/lib/api-base";

export function LoginPage() {
  const [initialized, setInitialized] = useState<boolean | null>(null);

  useEffect(() => {
    fetch(apiUrl("/api/auth/status"))
      .then((r) => r.json())
      .then((data) => setInitialized(data.initialized ?? true))
      .catch(() => setInitialized(true));
  }, []);

  const mode = initialized === false ? "change-password" : "login";

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
        {initialized === null ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            Loading...
          </div>
        ) : (
          <AuthForm mode={mode} />
        )}
      </Card>
    </div>
  );
}
