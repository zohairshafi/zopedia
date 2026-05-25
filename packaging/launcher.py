"""Zopedia desktop launcher.

Single uvicorn process.  On first run a temporary HTTP server handles
setup (avoiding FastAPI route-ordering issues with the catch-all SPA
route).  The browser is opened only after the server is confirmed
listening.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import sys
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
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


def _wait_for_server(host: str, port: int, timeout: float = 15.0) -> bool:
    """Poll until a TCP connection to *host:port* succeeds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    return False


def _run_setup_server(port: int, config_path: str) -> None:
    """Serve the first-run setup page on a temporary HTTP server.

    Blocks until the user submits the form, then returns.  The real
    Zopedia server will bind the same port afterwards.
    """
    from setup_page import SETUP_HTML

    _done = [False]

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0].rstrip("/")
            if path == "/__zopedia_setup_generate_password__":
                try:
                    import diceware
                    pw = diceware.get_passphrase(
                        options=diceware.handle_options(args=["-n", "4", "-d", "-", "-c"])
                    )
                except Exception:
                    import secrets
                    pw = secrets.token_urlsafe(16)
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(pw.encode())
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(SETUP_HTML.encode())

        def do_POST(self):
            if self.path.rstrip("/") != "/__zopedia_setup_save__":
                self.send_error(404)
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b"{}"
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_error(400)
                return

            cfg_path = Path(config_path)
            cfg: dict = {}
            if cfg_path.is_file():
                try:
                    cfg = json.loads(cfg_path.read_text())
                except (json.JSONDecodeError, OSError):
                    pass

            cfg.update({
                "llm_base_url": str(data.get("llm_base_url", "")).strip(),
                "llm_api_key": str(data.get("llm_api_key", "")).strip(),
                "llm_model": str(data.get("llm_model", "")).strip(),
                "wiki_vault": str(data.get("wiki_vault", "")).strip(),
                "auth_enabled": bool(data.get("auth_enabled", False)),
                "admin_password": str(data.get("admin_password", "")).strip() if data.get("auth_enabled") else "",
                "first_run": False,
            })

            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cfg_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
            os.replace(tmp, cfg_path)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            _done[0] = True

        def log_message(self, format, *args):
            pass  # suppress access logs

    server = HTTPServer(("127.0.0.1", port), _Handler)
    server.allow_reuse_address = True

    webbrowser.open(f"http://127.0.0.1:{port}/__zopedia_setup__?next=/chat")

    while not _done[0]:
        server.handle_request()

    server.server_close()


def _check_existing_instance(port_file: Path) -> int | None:
    """If a running instance exists, open its browser and return its port.
    Returns None if no existing instance is found."""
    if not port_file.is_file():
        return None
    try:
        port = int(port_file.read_text().strip())
    except (ValueError, OSError):
        return None
    if _wait_for_server("127.0.0.1", port, timeout=1.0):
        import uuid
        new_id = uuid.uuid4().hex[:12]
        webbrowser.open(f"http://127.0.0.1:{port}/chat?new={new_id}")
        return port
    # Stale file — port not listening
    try:
        port_file.unlink()
    except OSError:
        pass
    return None


def main() -> None:
    import multiprocessing
    multiprocessing.freeze_support()

    from config import load as load_cfg, CONFIG_PATH, WIKI_DEFAULT
    from config import env_from_config

    cfg = load_cfg()

    # ── Single-instance: check for already-running process ─────────────
    _port_file = CONFIG_PATH.parent / ".port"
    if _check_existing_instance(_port_file):
        return  # another instance already running, browser opened

    port = _find_free_port()

    # ── First-run: serve setup page via temp HTTP server ──────────────
    if cfg.get("first_run"):
        _run_setup_server(port, str(CONFIG_PATH))
        cfg = load_cfg()  # re-read saved config

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

    import main as _main_module

    # ── Shutdown endpoint ─────────────────────────────────────────────
    import uvicorn
    _server_ref: list[uvicorn.Server | None] = [None]

    @_main_module.app.get("/api/shutdown")
    async def _shutdown():
        if _server_ref[0]:
            _server_ref[0].should_exit = True
        return {"status": "shutting_down"}

    def _handle_quit(signum, frame):
        if _server_ref[0]:
            _server_ref[0].should_exit = True
    signal.signal(signal.SIGTERM, _handle_quit)
    signal.signal(signal.SIGINT, _handle_quit)

    # ── Start server in background thread ─────────────────────────────
    config = uvicorn.Config(
        _main_module.app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        reload=False,
    )
    _server_ref[0] = uvicorn.Server(config)
    server_thread = threading.Thread(target=_server_ref[0].run, daemon=True)
    server_thread.start()

    # ── Write port file for single-instance detection ──────────────────
    _port_file.write_text(str(port))

    # ── Open browser once server is listening ─────────────────────────
    url = f"http://127.0.0.1:{port}"
    if _wait_for_server("127.0.0.1", port):
        import uuid
        new_id = uuid.uuid4().hex[:12]
        webbrowser.open(f"{url}/chat?new={new_id}")

    # ── Tray icon (runs on main thread, blocks until Quit) ────────────
    from tray import run_tray

    def _request_shutdown():
        if _server_ref[0]:
            _server_ref[0].should_exit = True

    run_tray(port, _request_shutdown)

    # Server thread will exit because should_exit was set
    server_thread.join()

    # Clean up port file
    try:
        _port_file.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    main()
