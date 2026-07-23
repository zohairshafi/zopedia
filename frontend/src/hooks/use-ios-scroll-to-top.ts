import { useEffect } from "react";

/**
 * Emulates iOS status-bar-tap-to-scroll-to-top behavior in Capacitor
 * (WKWebView).  Since the app uses custom overflow containers instead of
 * body scroll, the native UIScrollView.scrollsToTop gesture has no effect.
 * This listens for taps in the top ~48pt (status-bar + safe-area region)
 * and scrolls the assistant-ui thread viewport to the top.
 */
export function useIosScrollToTop() {
  useEffect(() => {
    // Only relevant on iOS Capacitor
    if (typeof window === "undefined") return;
    const ua = navigator.userAgent;
    if (!ua.includes("iPhone") && !ua.includes("iPad")) return;

    let lastTap = 0;
    const STATUS_BAR_ZONE = 48; // pt — covers status bar + safe-area inset

    const onTouchEnd = (e: TouchEvent) => {
      const touch = e.changedTouches[0];
      if (!touch) return;
      // Ignore if the user is interacting with a control
      const target = e.target as HTMLElement | null;
      if (target?.closest("button, a, input, textarea, select, [role=button]")) return;
      // Only fire for taps in the top status-bar zone
      if (touch.clientY > STATUS_BAR_ZONE) return;
      // Debounce — ignore double-taps within 500ms
      const now = Date.now();
      if (now - lastTap < 500) return;
      lastTap = now;

      // Scroll the assistant-ui thread viewport to top
      const viewport = document.querySelector(".aui-thread-viewport");
      if (viewport) {
        viewport.scrollTo({ top: 0, behavior: "smooth" });
      }
    };

    document.addEventListener("touchend", onTouchEnd, { passive: true });
    return () => document.removeEventListener("touchend", onTouchEnd);
  }, []);
}
