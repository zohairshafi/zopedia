"""Zopedia desktop launcher — native window via pywebview.

Starts the FastAPI backend on a random port, then opens a native
WKWebView window (no browser required). On first run shows the
setup page inside the same window. Includes GitHub auto-updater.
"""

from __future__ import annotations

import json
import os
import signal
import socket
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


def _wait_for_server(host: str, port: int, timeout: float = 20.0) -> bool:
    """Poll until a TCP connection to *host:port* succeeds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    return False


def _check_existing_instance(port_file: Path) -> int | None:
    """If a running instance exists, open a native window and return its port.
    Returns None if no existing instance is found."""
    if not port_file.is_file():
        return None
    try:
        port = int(port_file.read_text().strip())
    except (ValueError, OSError):
        return None
    if _wait_for_server("127.0.0.1", port, timeout=1.0):
        return port
    # Stale file — port not listening
    try:
        port_file.unlink()
    except OSError:
        pass
    return None


def _open_webview_window(
    port: int,
    start_url: str | None = None,
    shutdown_cb=None,
) -> None:
    """Open a native WKWebView window. Blocks until the window is closed."""
    import webview
    import AppKit

    class TitlebarColorView(AppKit.NSView):
        """Opaque color view that still lets the window be dragged by it.

        The system's titlebar views either paint a grey vibrancy material or
        revert a plain setBackgroundColor on every repaint. Inserting our own
        solid color NSView behind the traffic lights is the reliable way to
        theme the titlebar. mouseDownCanMoveWindow=YES keeps the window
        draggable from anywhere on the colored region."""

        def isOpaque(self):
            return True

        def mouseDownCanMoveWindow(self):
            return True

        def drawRect_(self, rect):
            color = getattr(self, "_py_color", None)
            if color is not None:
                color.setFill()
                AppKit.NSBezierPath.fillRect_(self.bounds())

    if start_url is None:
        start_url = f"http://127.0.0.1:{port}/chat"

    # Start with dark background (matches frontend default). The theme sync
    # bridge (set_native_theme) will correct it to light if needed on load.
    # NSApp isn't available yet in the PyInstaller bundle at this point.
    bg_color = "#1a1b1e"

    window = webview.create_window(
        title="Zopedia",
        url=start_url,
        width=1280,
        height=800,
        min_size=(800, 600),
        background_color=bg_color,
    )

    from PyObjCTools import AppHelper

    # ── Python helper: open URLs in the system browser ────────────
    # NOTE: name must NOT start with '_' — pywebview exposes it to JS
    # verbatim as window.pywebview.api.<__name__>, and the JS side
    # calls window.pywebview.api.open_url.
    def open_url(url: str) -> None:
        import webbrowser
        webbrowser.open(url)

    # ── Python helper: post a native macOS notification ───────────
    # Uses NSUserNotification so it shows the Zopedia app icon (from the
    # bundle) automatically. Dispatched to the main thread — AppKit UI ops
    # reject calls from worker threads.
    def notify_completion(title: str, body: str) -> None:
        def _post():
            notif = AppKit.NSUserNotification.alloc().init()
            notif.setTitle_(title)
            notif.setInformativeText_(body)
            notif.setSoundName_("NSUserNotificationDefaultSoundName")
            center = AppKit.NSUserNotificationCenter.defaultUserNotificationCenter()
            if center is not None:
                center.deliverNotification_(notif)
        AppHelper.callAfter(_post)

    # ── Titlebar theming ──────────────────────────────────────────
    # Make the titlebar transparent and set the window background to the
    # theme color. With the titlebar transparent, the titlebar region shows
    # the window background (matching the webview). The system vibrancy view
    # is hidden so it doesn't paint grey over it.
    #
    # We deliberately do NOT use FullSizeContentView: that extends the webview
    # under the titlebar, and since WKWebView returns mouseDownCanMoveWindow=NO
    # the window can no longer be dragged by the titlebar. Keeping the stock
    # titled window preserves native dragging.
    #
    # Must run on the main thread: AppKit rejects view changes from threads.
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

        # Walk once: find the titlebar view, hide the system vibrancy view.
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

        # Reuse the color view on theme updates; create on first apply.
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
        # Called from the JS bridge on a worker thread — dispatch to main.
        # Name must NOT start with '_' (see open_url note above).
        AppHelper.callAfter(_apply_titlebar_theme, is_dark)

    window.expose(open_url, set_native_theme, notify_completion)

    def _on_loaded():
        # Inject desktop flag so the frontend knows it's running inside pywebview
        window.evaluate_js("window.__ZOPEDIA_DESKTOP__ = true;")

        # Detect system appearance (NSApp is available once loaded) and
        # theme the titlebar to match. The frontend re-calls
        # set_native_theme via the bridge on manual theme switches.
        ns_app = AppKit.NSApplication.sharedApplication()
        appearance = ns_app.effectiveAppearance()
        best = appearance.bestMatchFromAppearancesWithNames_([
            AppKit.NSAppearanceNameDarkAqua,
            AppKit.NSAppearanceNameAqua,
        ])
        is_dark = (best == AppKit.NSAppearanceNameDarkAqua)
        AppHelper.callAfter(_apply_titlebar_theme, is_dark)

        # Intercept links so non-SPA same-origin URLs (wiki file views,
        # API downloads, etc.) and external URLs open in the system
        # browser instead of navigating the webview away from the app.
        # SPA routes (/chat, /settings) are left to React Router.
        window.evaluate_js("""
            (function() {
                var SPA_ROOTS = ['/chat', '/settings', '/'];
                function isSpaPath(pathname) {
                    for (var i = 0; i < SPA_ROOTS.length; i++) {
                        var r = SPA_ROOTS[i];
                        if (pathname === r || pathname.startsWith(r + '/') || pathname.startsWith(r + '?'))
                            return true;
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
                    if (url.startsWith(window.location.origin)) {
                        if (a.getAttribute('target') === '_blank') {
                            e.preventDefault();
                            openExternally(url);
                            return;
                        }
                        if (isSpaPath(new URL(url).pathname)) return;
                        e.preventDefault();
                        openExternally(url);
                        return;
                    }
                    e.preventDefault();
                    openExternally(url);
                });
                var _origOpen = window.open;
                window.open = function(url, target) {
                    if (!url) return _origOpen.apply(this, arguments);
                    if (target === '_blank' || !target) {
                        var resolved = url;
                        if (resolved.indexOf('://') === -1) {
                            resolved = new URL(url, window.location.origin).href;
                        }
                        if (resolved.startsWith(window.location.origin)) {
                            if (!isSpaPath(new URL(resolved).pathname)) {
                                openExternally(resolved);
                                return null;
                            }
                        } else {
                            openExternally(resolved);
                            return null;
                        }
                    }
                    return _origOpen.apply(this, arguments);
                };
            })();
        """)

    def _on_closed():
        if shutdown_cb:
            shutdown_cb()

    window.events.loaded += _on_loaded
    window.events.closed += _on_closed

    # ── Close-to-hide: red X hides window instead of quitting ───────
    _terminating = False

    def _on_closing():
        if _terminating:
            return  # allow close (returns None → close proceeds)
        window.hide()
        return False  # prevent close

    window.events.closing += _on_closing

    # ── Patch AppDelegate for dock quit + dock click after hide ─────
    # Must run after webview.start() initializes NSApp, so we call it
    # from _on_loaded (which fires once the webview is ready).
    def _patch_app_delegate():
        delegate = AppKit.NSApp.delegate()
        if delegate is None:
            return
        cls = type(delegate)

        # Allow dock-right-click → Quit to actually terminate
        def _patched_should_terminate(self, app):
            nonlocal _terminating
            _terminating = True
            window.show()  # make visible so close can proceed
            return True  # YES

        # Show window when dock icon is clicked after hiding
        def _patched_handle_reopen(self, app, has_visible_windows):
            if not has_visible_windows:
                window.show()

        try:
            cls.applicationShouldTerminate_ = _patched_should_terminate
            cls.applicationShouldHandleReopen_hasVisibleWindows_ = _patched_handle_reopen
        except Exception:
            pass  # Cmd+Q still works; falling back gracefully

    window.events.loaded += _patch_app_delegate

    # Use the native macOS WebKit renderer.
    # A custom user agent marks this as the desktop app (not a browser):
    # navigator.userAgent is available synchronously before first paint, so
    # the frontend can branch (titlebar padding, dark-mode default) with no
    # flash and with zero chance of matching a real browser. The string is a
    # realistic Safari UA (keeps "Mac" for device detection) plus a token.
    webview.start(
        gui="cocoa",
        debug=False,
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.4 Safari/605.1.15 ZopediaDesktop"
        ),
    )


def _resolve_auth_disabled(cfg: dict) -> bool:
    """Decide whether auth is disabled for this launch.

    Auth is OFF only on first run (the setup page needs no login) or when the
    user has explicitly disabled it via the in-app "Edit Wiki Details" dialog,
    which persists ``ZOPEDIA_AUTH_DISABLED`` to wiki_env_overrides.json.
    Otherwise auth is ON by default (secure). This makes the dialog's setting
    the single source of truth — the legacy ``auth_enabled`` knob in
    config.json is no longer consulted.
    """
    if cfg.get("first_run"):
        return True
    overrides_path = Path(
        os.environ.get("ZOPEDIA_HOME", str(Path.home()))
    ) / ".zopedia" / "wiki_env_overrides.json"
    try:
        if overrides_path.is_file():
            raw = json.loads(overrides_path.read_text()).get("ZOPEDIA_AUTH_DISABLED")
            val = str(raw).strip().lower() if raw is not None else ""
            if val == "true":
                return True
            if val == "false":
                return False
    except (json.JSONDecodeError, OSError):
        pass
    return False  # default: auth enabled


def main() -> None:
    import multiprocessing
    multiprocessing.freeze_support()

    from config import load as load_cfg, CONFIG_PATH, WIKI_DEFAULT
    from config import env_from_config

    cfg = load_cfg()

    # ── Single-instance: check for already-running process ─────────────
    _port_file = CONFIG_PATH.parent / ".port"
    existing_port = _check_existing_instance(_port_file)
    if existing_port:
        # Another instance is running — open a new window pointing to it
        _open_webview_window(existing_port)
        return

    port = _find_free_port()

    # ── Apply env vars from config ────────────────────────────────────
    for k, v in env_from_config(cfg).items():
        os.environ.setdefault(k, v)

    os.environ.setdefault("ZOPEDIA_FRONTEND_DIR", _resource_path("frontend/dist"))
    if not os.environ.get("ZOPEDIA_WIKI_VAULT"):
        os.environ["ZOPEDIA_WIKI_VAULT"] = str(WIKI_DEFAULT)
    os.environ.setdefault("ZOPEDIA_HOME", str(WIKI_DEFAULT.parent))

    # Auth: ON by default; OFF only on first run or if the in-app wiki-details
    # dialog has explicitly disabled it. Must run after ZOPEDIA_HOME is set so
    # the override file path resolves correctly.
    os.environ["ZOPEDIA_AUTH_DISABLED"] = "true" if _resolve_auth_disabled(cfg) else "false"

    # Ensure wiki directories exist
    Path(os.environ["ZOPEDIA_WIKI_VAULT"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["ZOPEDIA_HOME"]).mkdir(parents=True, exist_ok=True)

    backend = _resource_path("backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)

    # Graphify monorepo path (for importlib fallback in ingestor.py)
    graphify_root = _resource_path(".")
    if graphify_root not in sys.path:
        sys.path.insert(0, graphify_root)

    import main as _main_module
    import uvicorn
    import updater as _updater

    # Register setup routes on the FastAPI app (first-run setup page)
    from setup_page import make_setup_routes
    make_setup_routes(_main_module.app, str(CONFIG_PATH))

    _server_ref: list[uvicorn.Server | None] = [None]

    def _do_shutdown():
        if _server_ref[0]:
            _server_ref[0].should_exit = True

    @_main_module.app.get("/api/shutdown")
    async def _shutdown():
        _do_shutdown()
        return {"status": "shutting_down"}

    @_main_module.app.get("/api/update-status")
    async def _update_status():
        return _updater.get_status()

    @_main_module.app.post("/api/update-download")
    async def _update_download():
        import asyncio
        status = _updater.get_status()
        url = status.get("download_url")
        if not url:
            return {"ok": False, "error": "No download URL available"}
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _updater.open_dmg_download, url)
        return result

    def _handle_quit(signum, frame):
        _do_shutdown()
    signal.signal(signal.SIGTERM, _handle_quit)
    signal.signal(signal.SIGINT, _handle_quit)

    # ── Start server in background thread ─────────────────────────────
    config = uvicorn.Config(
        _main_module.app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        reload=False,
    )
    _server_ref[0] = uvicorn.Server(config)
    server_thread = threading.Thread(target=_server_ref[0].run, daemon=True)
    server_thread.start()

    _port_file.write_text(str(port))

    # ── Start background update checker ───────────────────────────────
    _updater.start_background_check()

    # ── Wait for server, then open the native window ──────────────────
    if not _wait_for_server("127.0.0.1", port):
        print("ERROR: server did not start in time", file=sys.stderr)
        sys.exit(1)

    start_url = f"http://127.0.0.1:{port}/chat"
    if cfg.get("first_run"):
        start_url = f"http://127.0.0.1:{port}/__zopedia_setup__?next=/chat"

    _open_webview_window(port, start_url=start_url, shutdown_cb=_do_shutdown)

    # ── Cleanup ───────────────────────────────────────────────────────
    _do_shutdown()
    server_thread.join(timeout=5)
    try:
        _port_file.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    main()
