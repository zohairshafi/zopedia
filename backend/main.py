"""Zopedia - Lightweight personal wiki + RAG chat application."""

from __future__ import annotations

import logging
import os
import shutil
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Bridge: set UNSLOTH_* env vars before wiki engine imports ──────
from core.wiki.bridge import apply_defaults  # noqa: E402

apply_defaults()

# ── Logging ────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("zopedia")

# ── Env config ─────────────────────────────────────────────────────


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").strip().lower()
    return val in {"1", "true", "yes", "on"} if val else default


_AUTH_DISABLED = _env_bool("ZOPEDIA_AUTH_DISABLED", True)
_PORT = int(os.getenv("ZOPEDIA_PORT", "8000"))
_FRONTEND_DIR = Path(_env_str("ZOPEDIA_FRONTEND_DIR", str(Path(__file__).parent.parent / "frontend" / "dist")))

# Apply stored wiki env overrides before anything else
try:
    from core.wiki.runtime_env import apply_stored_wiki_env_overrides

    apply_stored_wiki_env_overrides(override_existing=False)
except Exception:
    pass


# ── Auth stub ──────────────────────────────────────────────────────


async def _get_current_subject(request: Request) -> str:
    if _AUTH_DISABLED:
        return "local-user"
    # Delegate to real auth if enabled
    try:
        from auth.authentication import get_current_subject as real_auth

        return await real_auth(request)
    except Exception:
        return "local-user"


# ── Lifespan ───────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialize wiki watcher. Shutdown: stop watcher."""
    logger.info("Starting Zopedia...")

    # Start wiki watcher
    try:
        from core.wiki.manager import WikiManager
        from core.wiki.ingestor import WikiIngestor
        from core.wiki.watcher import WikiIngestionWatcher
        from core.llm import wiki_llm_fn, llm_available
        from routes.wiki import (
            _WIKI_VAULT,
            _WIKI_WATCHER_ENABLED,
            _WIKI_AUTO_QUERY_ON_INGEST,
            _WIKI_AUTO_QUERY_CHAT_HISTORY,
            _WIKI_AUTO_LINT_EVERY,
            _WIKI_AUTO_RETRY_FALLBACK_MAX_PAGES,
        )

        vault_root = _WIKI_VAULT
        manager = WikiManager.create(vault_root, wiki_llm_fn)
        ingestor = WikiIngestor(manager, vault_root / "raw")

        # Ensure wiki indices are up to date on startup
        try:
            manager.engine._rebuild_index()
            logger.info("Wiki index rebuilt on startup")
        except Exception as exc:
            logger.warning("Wiki index rebuild on startup failed: %s", exc)

        if _WIKI_WATCHER_ENABLED:
            import threading

            watcher = WikiIngestionWatcher(
                ingestor=ingestor,
                raw_dir=vault_root / "raw",
                contributor="Zopedia",
                auto_analyze=_WIKI_AUTO_QUERY_ON_INGEST,
                lint_every=_WIKI_AUTO_LINT_EVERY,
                llm_available_fn=llm_available,
                analyze_chat_history=_WIKI_AUTO_QUERY_CHAT_HISTORY,
            )
            watcher_thread = threading.Thread(target=watcher.start, daemon=True)
            watcher_thread.start()
            app.state.wiki_watcher = watcher
            app.state.wiki_watcher_thread = watcher_thread
            logger.info("Wiki watcher started on %s/raw", vault_root)
        else:
            app.state.wiki_watcher = None
            logger.info("Wiki watcher disabled.")

        app.state.wiki_manager = manager
        app.state.wiki_ingestor = ingestor
    except Exception as exc:
        logger.warning("Wiki watcher startup failed: %s", exc)
        app.state.wiki_watcher = None

    # Wire auth dependency
    app.state.get_current_subject = _get_current_subject

    # Wire restart support for wiki env editing
    def _trigger_restart():
        logger.info("Restart requested via API — exiting to allow process manager to restart.")
        import signal
        os.kill(os.getpid(), signal.SIGTERM)

    app.state.trigger_restart = _trigger_restart

    yield

    # Shutdown
    logger.info("Shutting down Zopedia...")
    watcher = getattr(app.state, "wiki_watcher", None)
    if watcher:
        try:
            watcher.stop()
            logger.info("Wiki watcher stopped.")
        except Exception as exc:
            logger.warning("Error stopping wiki watcher: %s", exc)


# ── App ────────────────────────────────────────────────────────────

app = FastAPI(title="Zopedia", version="0.1.0", lifespan=lifespan)

# CORS
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ── Routers ────────────────────────────────────────────────────────

from routes.wiki import router as wiki_router

app.include_router(wiki_router, prefix="/api/inference")

from routes.chat import router as chat_router

app.include_router(chat_router, prefix="/v1")


# ── Shutdown ────────────────────────────────────────────────────────


@app.post("/api/shutdown")
async def shutdown():
    """Shut down the Zopedia server."""
    logger.info("Shutdown requested via API")
    import signal
    os.kill(os.getpid(), signal.SIGTERM)
    return {"status": "shutting_down"}


# ── File Upload ──────────────────────────────────────────────────────


@app.post("/api/upload")
async def upload_file(request: Request):
    """Upload files directly to the wiki raw/ folder for ingestion."""
    from fastapi import UploadFile
    from routes.wiki import _WIKI_VAULT

    raw_dir = _WIKI_VAULT / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    form = await request.form()
    uploaded: list[str] = []
    failed: list[dict] = []
    allowed_ext = {".md", ".txt", ".pdf"}

    for field_name in form:
        value = form[field_name]
        # FastAPI returns a list when multiple files share the same field name
        files: list[UploadFile] = []
        if isinstance(value, UploadFile):
            files = [value]
        elif isinstance(value, list):
            files = [v for v in value if isinstance(v, UploadFile)]
        else:
            continue

        for file in files:
            try:
                safe_name = file.filename or f"uploaded-{field_name}"
                safe_name = safe_name.replace("/", "_").replace("\\", "_").strip()
                if not safe_name:
                    failed.append({"filename": file.filename or field_name, "reason": "invalid filename"})
                    continue

                ext = Path(safe_name).suffix.lower()
                if ext not in allowed_ext:
                    failed.append({"filename": safe_name, "reason": f"unsupported file type ({ext or 'none'}). Accepted: .md, .txt, .pdf"})
                    continue

                content = await file.read()
                if not content:
                    failed.append({"filename": safe_name, "reason": "empty file"})
                    continue

                dest = raw_dir / safe_name
                if dest.exists():
                    stem = dest.stem
                    suffix = dest.suffix
                    dest = raw_dir / f"{stem}-{int(time.time())}{suffix}"
                dest.write_bytes(content)
                uploaded.append(str(dest.relative_to(_WIKI_VAULT)))
            except Exception as exc:
                failed.append({"filename": file.filename or field_name, "reason": str(exc)})

    return {"status": "ok", "uploaded": uploaded, "failed": failed}


# ── Health ─────────────────────────────────────────────────────────


@app.get("/api/health")
async def health():
    from core.llm import llm_available, _LLM_BASE_URL, _LLM_MODEL

    provider = ""
    if _LLM_BASE_URL:
        from urllib.parse import urlparse
        parsed = urlparse(_LLM_BASE_URL)
        provider = parsed.netloc or parsed.path.split("/")[0]

    return {
        "status": "ok",
        "app": "zopedia",
        "llm_configured": llm_available(),
        "llm_provider": provider,
        "llm_model": _LLM_MODEL or "default",
        "auth_disabled": _AUTH_DISABLED,
        "device_type": "web",
        "chat_only": False,
    }


# ── Auth stubs (when auth is disabled) ──────────────────────────────

if _AUTH_DISABLED:
    from fastapi import APIRouter as _APIRouter
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    _auth_stub = _APIRouter()

    @_auth_stub.get("/auth/status")
    async def _auth_status():
        return {"initialized": True, "requires_password_change": False}

    @_auth_stub.post("/auth/login")
    async def _auth_login():
        return {
            "access_token": "zopedia-local",
            "refresh_token": "zopedia-local-refresh",
            "must_change_password": False,
        }

    @_auth_stub.post("/auth/refresh")
    async def _auth_refresh():
        return {
            "access_token": "zopedia-local",
            "refresh_token": "zopedia-local-refresh",
            "must_change_password": False,
        }

    @_auth_stub.post("/auth/change-password")
    async def _auth_change_password():
        return {
            "access_token": "zopedia-local",
            "refresh_token": "zopedia-local-refresh",
            "must_change_password": False,
        }

    app.include_router(_auth_stub, prefix="/api")


# ── Model API stubs (return empty to keep UI happy) ─────────────────

@app.get("/api/models/list")
async def _models_list():
    return {"models": []}

@app.get("/api/models/loras")
async def _models_loras():
    return {"loras": []}

@app.get("/api/models/local")
async def _models_local():
    return {"models": []}

@app.get("/api/models/cached-gguf")
async def _models_cached_gguf():
    return {"cached": []}

@app.get("/api/models/cached-models")
async def _models_cached_models():
    return {"cached": []}

@app.get("/api/inference/status")
async def _inference_status():
    from core.llm import llm_available
    return {
        "is_loaded": False,
        "model_name": None,
        "upstream_available": llm_available(),
    }

@app.get("/api/inference/load-progress")
async def _load_progress():
    return {"progress": 0, "status": "idle"}


# ── Frontend serving ───────────────────────────────────────────────

_frontend_available = _FRONTEND_DIR.exists() and (_FRONTEND_DIR / "index.html").exists()

if _frontend_available:
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = _FRONTEND_DIR / full_path
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_FRONTEND_DIR / "index.html"))

    @app.get("/")
    async def serve_index():
        return FileResponse(str(_FRONTEND_DIR / "index.html"))


# ── Main ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Zopedia on port %d", _PORT)
    uvicorn.run("main:app", host="127.0.0.1", port=_PORT, reload=False)
