// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { createRoute, redirect } from "@tanstack/react-router";
import { lazy } from "react";
import { isServerMode } from "@/lib/mode";
import { Route as rootRoute } from "./__root";
import { hasAuthToken, refreshSession } from "@/features/auth";
import { hasServerConfig } from "@/features/connect";

const ConnectPage = lazy(() =>
  import("@/features/connect/connect-page").then((m) => ({ default: m.ConnectPage })),
);

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/connect",
  beforeLoad: async () => {
    // /connect only exists in client builds.
    if (isServerMode()) throw redirect({ to: "/" });
    // Skip the connect page if already configured with a live session.
    if (hasServerConfig() && (hasAuthToken() || (await refreshSession()))) {
      throw redirect({ to: "/chat" });
    }
  },
  component: ConnectPage,
});
