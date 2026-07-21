"""Zopedia Client — thin desktop client (pywebview).

Serves the prebuilt client SPA (frontend/dist-client) from a local static
server and opens it in a native WKWebView window. No backend runs locally;
the client connects to a remote Zopedia server through the in-app Connect page.

Build: see packaging/ZopediaClient.spec
"""

from __future__ import annotations

import functools
import http.server
import os
import signal
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path

_LAUNCHER_DIR = str(Path(__file__).resolve().parent)
if _LAUNCHER_DIR not in sys.path:
    sys.path.insert(0, _LAUNCHER_DIR)


def _resource_path(relative: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return str(Path(sys._MEIPASS) / relative)
    return str(Path(__file__).resolve().parents[1] / relative)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    return False


class _SpaRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Static file handler with SPA fallback: unknown paths → index.html."""

    def send_head(self):  # type: ignore[override]
        path = self.translate_path(self.path)
        if not Path(path).is_file():
            self.path = "/index.html"
        return super().send_head()

    def log_message(self, *args):  # silence default request logging
        pass


def _start_static_server(root: str, port: int) -> socketserver.ThreadingTCPServer:
    handler = functools.partial(_SpaRequestHandler, directory=root)
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _open_window(port: int) -> None:
    """Open a native WKWebView window onto the local client SPA."""
    import webview
    import AppKit
    from PyObjCTools import AppHelper
    import updater as _updater_mod

    # Native save dialog for blob: URL downloads (chat export, etc.)
    webview.settings["ALLOW_DOWNLOADS"] = True

    class TitlebarColorView(AppKit.NSView):
        """Opaque draggable color view placed behind the traffic lights."""

        def isOpaque(self):
            return True

        def mouseDownCanMoveWindow(self):
            return True

        def drawRect_(self, rect):
            color = getattr(self, "_py_color", None)
            if color is not None:
                color.setFill()
                AppKit.NSBezierPath.fillRect_(self.bounds())

    import updater as _updater_mod
    _app_version = _updater_mod._get_current_version()

    window = webview.create_window(
        title=f"Zopedia Client v{_app_version}",
        url=f"http://127.0.0.1:{port}/",
        width=1280,
        height=800,
        min_size=(800, 600),
        background_color="#1a1b1e",
    )

    # ── Python helpers exposed to JS ──────────────────────────────────
    # NOTE: names must NOT start with '_' — pywebview exposes them verbatim
    # as window.pywebview.api.<name>.

    def open_url(url: str) -> None:
        import webbrowser
        webbrowser.open(url)

    def save_blob(filename: str, data_b64: str) -> str:
        # NSSavePanel must run on the main thread; the JS bridge calls us on
        # a worker thread, so dispatch and block until it returns.
        import base64
        data = base64.b64decode(data_b64)
        result: list[str] = [""]
        done = threading.Event()

        def _on_main():
            try:
                dlg = AppKit.NSSavePanel.savePanel()
                dlg.setNameFieldStringValue_(filename)
                if dlg.runModal() == AppKit.NSFileHandlingPanelOKButton:
                    filepath = dlg.URL().path()
                    with open(filepath, "wb") as f:
                        f.write(data)
                    result[0] = filepath
            finally:
                done.set()

        AppHelper.callAfter(_on_main)
        done.wait()
        return result[0]

    def _apply_titlebar_theme(is_dark: bool) -> None:
        if is_dark:
            r, g, b = 0x1A / 255, 0x1B / 255, 0x1E / 255
        else:
            r, g, b = 1.0, 1.0, 1.0
        ns_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0)
        win = window.native
        win.setTitlebarAppearsTransparent_(True)
        win.setTitleVisibility_(AppKit.NSWindowTitleHidden)
        win.setBackgroundColor_(ns_color)

        titlebar_view = None

        def walk(view):
            nonlocal titlebar_view
            name = view.__class__.__name__
            if name == "NSTitlebarView":
                titlebar_view = view
            if name == "NSVisualEffectView":
                view.setHidden_(True)
            for sub in view.subviews():
                walk(sub)

        walk(win.contentView().superview())
        host = titlebar_view
        if host is None:
            return

        color_view = None
        for sub in host.subviews():
            if isinstance(sub, TitlebarColorView):
                color_view = sub
                break
        if color_view is None:
            color_view = TitlebarColorView.alloc().initWithFrame_(host.bounds())
            color_view.setAutoresizingMask_(
                AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable
            )
            siblings = host.subviews()
            host.addSubview_positioned_relativeTo_(
                color_view,
                AppKit.NSWindowBelow,
                siblings[0] if siblings else None,
            )
        color_view._py_color = ns_color
        color_view.setNeedsDisplay_(True)

    def set_native_theme(is_dark: bool) -> None:
        AppHelper.callAfter(_apply_titlebar_theme, is_dark)

    # ── Download DMG and open in Finder (auto-updates) ───────────
    def download_and_open_dmg(url: str) -> str:
        import json
        result = _updater_mod.open_dmg_download(url)
        return json.dumps(result)

    window.expose(open_url, set_native_theme, save_blob, download_and_open_dmg)

    def _on_loaded():
        # Mark as desktop so the frontend syncs the titlebar theme and uses
        # the native save dialog. (The auto-updater hook polls
        # /api/update-status and silently no-ops — no local backend.)
        window.evaluate_js("window.__ZOPEDIA_DESKTOP__ = true;")
        window.evaluate_js(f"window.__ZOPEDIA_VERSION__ = '{_updater_mod._get_current_version()}';")

        ns_app = AppKit.NSApplication.sharedApplication()
        appearance = ns_app.effectiveAppearance()
        best = appearance.bestMatchFromAppearancesWithNames_([
            AppKit.NSAppearanceNameDarkAqua,
            AppKit.NSAppearanceNameAqua,
        ])
        AppHelper.callAfter(_apply_titlebar_theme, best == AppKit.NSAppearanceNameDarkAqua)

        # Intercept non-SPA links → system browser; keep blob/data/downloads in-app.
        window.evaluate_js("""
            (function() {
                var SPA_ROOTS = ['/chat', '/research', '/connect', '/'];
                function isSpaPath(p) {
                    for (var i = 0; i < SPA_ROOTS.length; i++) {
                        var r = SPA_ROOTS[i];
                        if (p === r || p.startsWith(r + '/') || p.startsWith(r + '?')) return true;
                    }
                    return false;
                }
                function openExternally(url) {
                    try { window.pywebview.api.open_url(url); } catch(_) {}
                }
                document.addEventListener('click', function(e) {
                    var a = e.target.closest('a');
                    if (!a || !a.href) return;
                    var url = a.href;
                    if (/^(blob|data|javascript|mailto|file):/i.test(url) || a.hasAttribute('download')) return;
                    if (url.startsWith(window.location.origin)) {
                        if (a.getAttribute('target') === '_blank') { e.preventDefault(); openExternally(url); return; }
                        if (isSpaPath(new URL(url).pathname)) return;
                        e.preventDefault(); openExternally(url); return;
                    }
                    e.preventDefault(); openExternally(url);
                });
                var _origOpen = window.open;
                window.open = function(url, target) {
                    if (!url) return _origOpen.apply(this, arguments);
                    if (/^(blob|data|javascript|mailto|file):/i.test(url)) return _origOpen.apply(this, arguments);
                    if (target === '_blank' || !target) {
                        var resolved = url;
                        if (resolved.indexOf('://') === -1) resolved = new URL(url, window.location.origin).href;
                        if (resolved.startsWith(window.location.origin)) {
                            if (!isSpaPath(new URL(resolved).pathname)) { openExternally(resolved); return null; }
                        } else { openExternally(resolved); return null; }
                    }
                    return _origOpen.apply(this, arguments);
                };
            })();
        """)

    window.events.loaded += _on_loaded

    # ── Close-to-hide + dock quit/reopen (same UX as the server app) ──
    _terminating = False

    def _on_closing():
        if _terminating:
            return  # allow close
        window.hide()
        return False  # prevent close

    window.events.closing += _on_closing

    def _patch_app_delegate():
        delegate = AppKit.NSApp.delegate()
        if delegate is None:
            return
        cls = type(delegate)

        def _patched_should_terminate(self, app):
            nonlocal _terminating
            _terminating = True
            window.show()  # make visible so close can proceed
            return True

        def _patched_handle_reopen(self, app, has_visible_windows):
            if not has_visible_windows:
                window.show()

        try:
            cls.applicationShouldTerminate_ = _patched_should_terminate
            cls.applicationShouldHandleReopen_hasVisibleWindows_ = _patched_handle_reopen
        except Exception:
            pass  # Cmd+Q still works; fall back gracefully

    window.events.loaded += _patch_app_delegate

    # UA token "ZopediaDesktop" is a substring, so getIsDesktop() matches and
    # layout/theme can branch before the load handler injects the flag.
    webview.start(
        gui="cocoa",
        debug=False,
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.4 Safari/605.1.15 ZopediaDesktopClient"
        ),
    )


def main() -> None:
    import multiprocessing
    multiprocessing.freeze_support()

    web_root = _resource_path("frontend/dist-client")
    if not Path(web_root).is_dir():
        print(f"ERROR: client frontend not found at {web_root}", file=sys.stderr)
        print("Build it first: (cd frontend && npm run build:client)", file=sys.stderr)
        sys.exit(1)

    port = _find_free_port()
    httpd = _start_static_server(web_root, port)

    def _shutdown(signum, frame):
        httpd.shutdown()
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    if not _wait_for_server("127.0.0.1", port):
        print("ERROR: static server did not start in time", file=sys.stderr)
        sys.exit(1)

    try:
        _open_window(port)
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
