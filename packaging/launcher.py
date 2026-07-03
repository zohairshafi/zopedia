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

    if start_url is None:
        start_url = f"http://127.0.0.1:{port}/chat"

    window = webview.create_window(
        title="Zopedia",
        url=start_url,
        width=1280,
        height=800,
        min_size=(800, 600),
        background_color="#0d0d0d",
    )

    def _on_loaded():
        # Inject desktop flag so the frontend knows it's running inside pywebview
        try:
            window.evaluate_js("window.__ZOPEDIA_DESKTOP__ = true;")
        except Exception:
            pass
        # Make links openable — pywebview blocks target="_blank" and window.open()
        # by default.  Intercept clicks on external links and open them in the
        # system browser.  Internal (same-origin) links navigate in-webview.
        try:
            window.evaluate_js("""
                (function() {
                    document.addEventListener('click', function(e) {
                        var a = e.target.closest('a');
                        if (!a || !a.href) return;
                        var url = a.href;
                        // Same-origin: let the webview navigate normally
                        if (url.startsWith(window.location.origin)) {
                            if (a.getAttribute('target') !== '_blank') return;
                            // target=_blank on same origin: navigate in this window
                            e.preventDefault();
                            window.location.href = url;
                            return;
                        }
                        // External URL: open in system browser
                        e.preventDefault();
                        window.open(url, '_system');
                    });
                    // Also intercept window.open calls so JS-triggered opens work
                    var _origOpen = window.open;
                    window.open = function(url, target) {
                        if (!url) return _origOpen.apply(this, arguments);
                        if (target === '_system' || target === '_blank' || !target) {
                            try { window.external.open(url); } catch(_) {}
                            // Fallback: use fetch to trigger a native open
                        }
                        return _origOpen.call(this, url, '_self');
                    };
                })();
            """)
        except Exception:
            pass
        # Ensure the root document is scrollable when the window is small.
        # The SPA's overflow-hidden on chat routes prevents body-level scroll,
        # but we want at least horizontal scroll prevention + vertical auto.
        try:
            window.evaluate_js("""
                (function() {
                    var style = document.createElement('style');
                    style.textContent = 'html { overflow-x: hidden; overflow-y: auto !important; }';
                    document.head.appendChild(style);
                })();
            """)
        except Exception:
            pass

    def _on_closed():
        if shutdown_cb:
            shutdown_cb()

    window.events.loaded += _on_loaded
    window.events.closed += _on_closed

    # Use the native macOS WebKit renderer
    webview.start(
        gui="cocoa",
        debug=False,
    )


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
    if cfg.get("first_run") or not cfg.get("auth_enabled"):
        os.environ["ZOPEDIA_AUTH_DISABLED"] = "true"
    if not os.environ.get("ZOPEDIA_WIKI_VAULT"):
        os.environ["ZOPEDIA_WIKI_VAULT"] = str(WIKI_DEFAULT)
    os.environ.setdefault("ZOPEDIA_HOME", str(WIKI_DEFAULT.parent))

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
