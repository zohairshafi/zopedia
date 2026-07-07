// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { createRoute, redirect } from "@tanstack/react-router";
import { lazy } from "react";
import { isClientMode } from "@/lib/mode";
import { requireGuest } from "../auth-guards";
import { Route as rootRoute } from "./__root";

const LoginPage = lazy(() =>
  import("@/features/auth").then((m) => ({ default: m.LoginPage })),
);

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  beforeLoad: () => {
    if (isClientMode()) throw redirect({ to: "/connect" });
    return requireGuest();
  },
  component: LoginPage,
});
