// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { AppSidebar } from "@/components/app-sidebar";
import { Navbar } from "@/components/navbar";
import { fetchDeviceType, usePlatformStore } from "@/config/env";
import { SidebarInset, SidebarProvider, useSidebar } from "@/components/ui/sidebar";
import { SettingsDialog, useSettingsDialogStore } from "@/features/settings";
import { useSidebarPin } from "@/hooks/use-sidebar-pin";
import {
  Outlet,
  createRootRoute,
  redirect,
  useRouterState,
} from "@tanstack/react-router";
import { AnimatePresence, motion } from "motion/react";
import { Suspense, useEffect } from "react";
import { isClientMode, SERVER_URL_KEY } from "@/lib/mode";
import { AppProvider } from "../provider";

const CHAT_ONLY_ALLOWED = new Set([
  "/",
  "/chat",
  "/login",
  "/signup",
  "/change-password",
  "/connect",
]);

function isChatOnlyAllowed(pathname: string): boolean {
  if (CHAT_ONLY_ALLOWED.has(pathname)) return true;
  if (pathname === "/data-recipes" || pathname.startsWith("/data-recipes/")) return true;
  return false;
}

export const Route = createRootRoute({
  beforeLoad: async ({ location }) => {
    console.log("[rootRoute] beforeLoad pathname:", location.pathname, "search:", location.search);
    await fetchDeviceType();
    const chatOnly = usePlatformStore.getState().isChatOnly();
    if (chatOnly && !isChatOnlyAllowed(location.pathname)) {
      console.log("[rootRoute] redirecting to /chat (chatOnly guard)");
      throw redirect({ to: "/chat" });
    }
  },
  component: RootLayout,
});

const HIDDEN_NAVBAR_ROUTES = ["/onboarding", "/login", "/change-password", "/connect"];

function EdgeSwipeDetector() {
  const { isMobile, openMobile, setOpenMobile } = useSidebar();

  useEffect(() => {
    if (!isMobile) return;

    let startX = 0;
    let startY = 0;
    let tracking = false;

    const onStart = (e: TouchEvent) => {
      if (openMobile || e.touches.length !== 1) return;
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
      tracking = true;
    };

    const onMove = (e: TouchEvent) => {
      if (!tracking || !e.touches[0]) return;
      const deltaX = e.touches[0].clientX - startX;
      const deltaY = e.touches[0].clientY - startY;
      // Require a deliberate rightward swipe (primarily horizontal, >100px)
      if (deltaX > 100 && deltaX > Math.abs(deltaY) * 2) {
        setOpenMobile(true);
        tracking = false;
      }
    };

    const onEnd = () => { tracking = false; };

    document.addEventListener("touchstart", onStart, { passive: true });
    document.addEventListener("touchmove", onMove, { passive: true });
    document.addEventListener("touchend", onEnd);

    return () => {
      document.removeEventListener("touchstart", onStart);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onEnd);
    };
  }, [isMobile, openMobile, setOpenMobile]);

  return null;
}

function RootLayout() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const hideNavbar = HIDDEN_NAVBAR_ROUTES.includes(pathname);
  const isChatRoute = pathname.startsWith("/chat");
  const { pinned, setPinned, togglePinned } = useSidebarPin();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      if ((e.metaKey || e.ctrlKey) && e.key === ",") {
        e.preventDefault();
        useSettingsDialogStore.getState().openDialog();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Client mode: intercept clicks on relative /api/inference/wiki-file?... links
  // and rewrite them to the connected server's URL. This is a belt-and-suspenders
  // guard — wiki-links.ts and wiki-file-browser.tsx already use apiUrl(), but this
  // catches any dynamically-injected or third-party-generated wiki-file links.
  useEffect(() => {
    if (!isClientMode()) return;

    function handleWikiLinkClick(e: MouseEvent) {
      const a = (e.target as Element).closest("a[href^=\"/api/inference/wiki-file\"]");
      if (!a) return;
      const href = a.getAttribute("href");
      if (!href) return;
      const server = localStorage.getItem(SERVER_URL_KEY);
      if (!server) return;
      e.preventDefault();
      const url = new URL(href, server.replace(/\/+$/, ""));
      window.open(url.href, "_blank", "noopener,noreferrer");
    }

    document.addEventListener("click", handleWikiLinkClick);
    return () => document.removeEventListener("click", handleWikiLinkClick);
  }, []);

  return (
    <AppProvider>
      <SettingsDialog />
      {hideNavbar ? (
        <main className="flex-1">
          <Suspense fallback={null}>
            <Outlet />
          </Suspense>
        </main>
      ) : (
        <SidebarProvider
          pinned={pinned}
          setPinned={setPinned}
          togglePinned={togglePinned}
          className="!min-h-0 h-dvh overflow-hidden"
        >
          <AppSidebar />
          <EdgeSwipeDetector />
          <SidebarInset className={isChatRoute ? "overflow-hidden" : "overflow-y-auto"}>
            <Navbar />
            <div
              className={`flex min-h-0 min-w-0 flex-1 basis-0 flex-col ${isChatRoute ? "overflow-hidden" : "overflow-visible"} ${isChatRoute ? "" : "pt-14 md:pt-0"}`}
            >
              <AnimatePresence initial={false} mode="wait">
                <motion.div
                  key={pathname}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.15 }}
                  className={`flex min-h-0 min-w-0 flex-1 basis-0 flex-col ${isChatRoute ? "overflow-hidden" : "overflow-visible"}`}
                >
                  <Suspense fallback={null}>
                    <Outlet />
                  </Suspense>
                </motion.div>
              </AnimatePresence>
            </div>
          </SidebarInset>
        </SidebarProvider>
      )}
    </AppProvider>
  );
}
