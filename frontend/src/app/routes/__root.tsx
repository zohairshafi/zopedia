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
  useNavigate,
  useRouterState,
} from "@tanstack/react-router";
import { AnimatePresence, motion } from "motion/react";
import { Suspense, useEffect, useRef, useSyncExternalStore } from "react";
import { isClientMode, SERVER_URL_KEY } from "@/lib/mode";
import { apiUrl } from "@/lib/api-base";
import { LoadingScreen } from "@/components/loading-screen";
import { clearClientAuthLoading, clientAuthLoadingStore } from "../auth-guards";
import { disconnectFromServer } from "@/features/connect";
import { useServerHealthPoll, serverHealthStore, checkHealthNow } from "@/hooks/use-server-health";
// The healthUrl helper is re-implemented locally to avoid importing a module-internal
// function. It reads the server URL directly from localStorage so the initial health
// check and the periodic poll both use the same URL construction.
function healthUrl(): string {
  const url = apiUrl("/api/health");
  if (url.startsWith("/")) {
    const server = (localStorage.getItem(SERVER_URL_KEY) ?? "").replace(/\/+$/, "");
    if (server) return `${server}/api/health`;
  }
  return url;
}
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
  const navigate = useNavigate();

  // Client mode: while requireAuth() is waiting for the server to respond
  // (e.g. cold Modal startup), show a loading screen.
  const clientAuthLoading = useSyncExternalStore(
    clientAuthLoadingStore.subscribe,
    clientAuthLoadingStore.getSnapshot,
  );

  // Debug: log on every render so we can see in Safari Web Inspector.
  console.debug(
    "[zopedia:RootLayout] render",
    `pathname=${pathname}`,
    `clientAuthLoading=${clientAuthLoading}`,
    `isClientMode=${isClientMode()}`,
  );

  function handleDisconnect() {
    clearClientAuthLoading();
    disconnectFromServer();
    navigate({ to: "/connect" });
  }

  async function handleRetry() {
    await checkHealthNow();
    if (serverHealthStore.getSnapshot()) {
      clearClientAuthLoading();
    }
  }

  // Client mode: periodically check the server is still reachable so we can
  // warn the user proactively instead of waiting for an API call to fail.
  // Skip on /connect — there's no server configured yet.
  const isConnectPage = pathname === "/connect";
  useServerHealthPoll(isConnectPage);
  const serverReachable = useSyncExternalStore(
    serverHealthStore.subscribe,
    serverHealthStore.getSnapshot,
  );

  // Client mode: on first mount (cold start), verify the server is reachable
  // and dismiss the loading screen.  clientAuthLoading starts as `true` (set
  // at module init), so the loading screen is already visible when this runs.
  // If the server is unreachable the loading screen stays and its built-in
  // disconnect button appears after 8 s.
  useEffect(() => {
    if (!isClientMode() || isConnectPage) {
      console.debug("[zopedia:health-check] not client mode or connect page, skipping");
      return;
    }
    if (!clientAuthLoadingStore.getSnapshot()) {
      console.debug("[zopedia:health-check] clientAuthLoading already false, skipping");
      return;
    }

    let cancelled = false;

    async function check() {
      const url = healthUrl();
      console.debug("[zopedia:health-check] checking", url);
      try {
        const res = await fetch(url, {
          signal: AbortSignal.timeout(15000),
          cache: "no-store",
        });
        const ct = res.headers.get("content-type") ?? "";
        console.debug("[zopedia:health-check] response", res.status, ct);
        if (!cancelled && res.ok && ct.includes("application/json")) {
          console.debug("[zopedia:health-check] success — clearing loading screen");
          clearClientAuthLoading();
        } else if (!cancelled) {
          console.warn("[zopedia:health-check] unexpected response — status:", res.status, "content-type:", ct);
        }
      } catch (err) {
        console.warn("[zopedia:health-check] failed:", err);
        // Server unreachable — loading screen stays.
      }
    }

    check();

    return () => { cancelled = true; };
  }, []);

  // Watch the full location href so we fire on thread switches (which only
  // change ?thread=, not the pathname).
  const locationHref = useRouterState({ select: (s) => s.location.href });

  // Client mode: immediate health check on every navigation (thread switch,
  // tab change, etc.).  A single failure is enough to show the banner —
  // no threshold, instant feedback.  Skipped on /connect.
  useEffect(() => {
    if (!isClientMode() || isConnectPage) return;
    void checkHealthNow();
  }, [locationHref, isConnectPage]);

  // Client mode: when the health poll detects the server came back online
  // after a disconnection, dismiss any lingering loading screen.
  const prevServerReachable = useRef(serverReachable);
  useEffect(() => {
    if (!isClientMode()) return;
    console.debug(
      "[zopedia:serverReachable] changed:",
      `prev=${prevServerReachable.current}`,
      `now=${serverReachable}`,
      `clientAuthLoading=${clientAuthLoading}`,
    );
    if (serverReachable && !prevServerReachable.current) {
      console.debug("[zopedia:serverReachable] server came back — clearing loading screen");
      clearClientAuthLoading();
    }
    prevServerReachable.current = serverReachable;
  }, [serverReachable]);

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

  // Client mode: show a loading screen while requireAuth() waits for the
  // server to respond (e.g. cold Modal startup). A "Connect to a different
  // server" button appears after 8 seconds in case the server is unreachable.
  if (clientAuthLoading) {
    return (
      <AppProvider>
        <LoadingScreen onRetry={handleRetry} onDisconnect={handleDisconnect} />
      </AppProvider>
    );
  }

  return (
    <AppProvider>
      <SettingsDialog />

      {/* Client mode: warn when the remote server becomes unreachable.
           The health poll checks every 15s (5s fast-poll when unreachable);
           after 2 consecutive failures this banner appears.  Not shown
           during auth loading — the LoadingScreen handles that case.
           Also not shown on /connect — there's no server configured yet. */}
      {isClientMode() && !isConnectPage && !serverReachable && !clientAuthLoading && (
        <div
          className="fixed bottom-4 left-4 right-4 z-50 flex items-center justify-between gap-3 rounded-lg bg-destructive px-4 py-3 text-sm text-destructive-foreground shadow-lg"
          style={{ marginBottom: "env(safe-area-inset-bottom, 0px)" }}
        >
          <span className="font-medium">
            Server unreachable — check your connection.
          </span>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => { void checkHealthNow(); }}
              className="rounded-md bg-white/20 px-3 py-1 text-xs font-medium hover:bg-white/30 transition-colors"
            >
              Retry
            </button>
            <button
              type="button"
              onClick={handleDisconnect}
              className="rounded-md bg-white/20 px-3 py-1 text-xs font-medium hover:bg-white/30 transition-colors"
            >
              Disconnect
            </button>
          </div>
        </div>
      )}

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
