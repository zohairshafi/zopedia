"""Zopedia - Lightweight personal wiki + RAG chat application."""

from __future__ import annotations

import asyncio
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

# ── Bridge: map ZOPEDIA_* env vars to UNSLOTH_* equivalents ────────
# Must run AFTER stored overrides are loaded so the mapping picks up user-configured values.
from core.wiki.bridge import apply_defaults  # noqa: E402

apply_defaults()


# ── Auth helpers ──────────────────────────────────────────────────


async def _get_current_subject(request: Request) -> str:
    """Return the authenticated username, or 'local-user' if auth is disabled or fails."""
    if _AUTH_DISABLED:
        return "local-user"
    return await _resolve_subject(request)


async def _require_valid_subject(request: Request) -> str:
    """Return the authenticated username, or raise 401 if auth is enabled and token is invalid.

    Use this for endpoints that MUST have a valid user identity (e.g. chat history).
    The 401 triggers the frontend to refresh its JWT and retry.
    """
    if _AUTH_DISABLED:
        return "local-user"
    subject = await _resolve_subject(request)
    if subject == "local-user":
        raise HTTPException(status_code=401, detail="Valid authentication required for chat history.")
    return subject


async def _resolve_subject(request: Request) -> str:
    """Extract and validate the JWT/API key. Returns 'local-user' on any failure."""
    try:
        from auth.authentication import _decode_subject_without_verification
        from auth.storage import get_user_and_secret, validate_api_key, API_KEY_PREFIX
        import jwt as _jwt

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.debug("auth: no Bearer header for %s", request.url.path)
            return "local-user"
        token = auth_header[7:]

        # API key path
        if token.startswith(API_KEY_PREFIX):
            username = validate_api_key(token)
            if username:
                return username
            logger.warning("auth: invalid API key for %s", request.url.path)
            return "local-user"

        # JWT path
        subject = _decode_subject_without_verification(token)
        if subject is None:
            logger.warning("auth: could not decode subject from JWT for %s", request.url.path)
            return "local-user"
        record = get_user_and_secret(subject)
        if record is None:
            logger.warning("auth: no user record for subject=%r path=%s", subject, request.url.path)
            return "local-user"
        _salt, _pwd_hash, jwt_secret, _must_change = record
        try:
            payload = _jwt.decode(token, jwt_secret, algorithms=["HS256"])
            if payload.get("sub") == subject:
                return subject
            logger.warning("auth: JWT sub mismatch: expected=%r got=%r", subject, payload.get("sub"))
        except Exception as exc:
            logger.warning("auth: JWT decode failed for subject=%r: %s", subject, exc)
        return "local-user"
    except Exception as exc:
        logger.warning("auth: _resolve_subject error: %s", exc)
        return "local-user"


# ── Lifespan ───────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialize wiki watcher. Shutdown: stop watcher."""
    logger.info("Starting Zopedia...")

    # Seed default admin account when auth is enabled
    if not _AUTH_DISABLED:
        try:
            from auth.storage import ensure_default_admin, get_bootstrap_password

            created = ensure_default_admin()
            if created:
                bootstrap = get_bootstrap_password()
                logger.info("Default admin 'zopedia' seeded. Bootstrap password: %s", bootstrap)
            else:
                logger.info("Auth initialized with existing users.")
        except Exception as exc:
            logger.warning("Auth bootstrap failed: %s", exc)

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
    app.state.require_valid_subject = _require_valid_subject

    # Start periodic research scheduler
    try:
        from periodic_scheduler import PeriodicScheduler
        scheduler = PeriodicScheduler()
        asyncio.create_task(scheduler.start())
        app.state.periodic_scheduler = scheduler
        logger.info("Periodic research scheduler started")
    except Exception as exc:
        logger.warning("Periodic scheduler startup failed: %s", exc)
        app.state.periodic_scheduler = None

    # Initialize database connection pool (PostgreSQL — optional)
    try:
        from core.database import create_pool
        _db_url = os.getenv("ZOPEDIA_DATABASE_URL", "").strip()
        if _db_url:
            await create_pool(_db_url)
        else:
            logger.info("No ZOPEDIA_DATABASE_URL set — database tools disabled.")
    except Exception as exc:
        logger.warning("Database pool initialization failed: %s", exc)

    # Wire restart support for wiki env editing.
    # Does an in-process soft reload: re-applies stored env overrides and
    # bridge defaults, then refreshes all module-level constants and wiki
    # components so changes take effect without killing the process.
    def _trigger_restart():
        global _AUTH_DISABLED
        logger.info("Soft reload requested — re-applying wiki env overrides in-process.")
        from core.wiki.runtime_env import apply_stored_wiki_env_overrides
        from core.wiki.bridge import apply_defaults
        from core.llm import refresh_llm_config
        from routes.wiki import refresh_wiki_components, _ROUTE_WIKI_INGESTOR

        try:
            applied = apply_stored_wiki_env_overrides(override_existing=True)
            logger.info("Re-applied %d wiki env override(s).", len(applied))
        except Exception as exc:
            logger.warning("Failed to re-apply stored wiki env overrides: %s", exc)

        try:
            apply_defaults()
            logger.info("Re-applied ZOPEDIA_* → UNSLOTH_* bridge defaults.")
        except Exception as exc:
            logger.warning("Failed to re-apply bridge defaults: %s", exc)

        try:
            refresh_llm_config()
            logger.info("LLM config refreshed.")
        except Exception as exc:
            logger.warning("Failed to refresh LLM config: %s", exc)

        try:
            new_manager = refresh_wiki_components()
            app.state.wiki_manager = new_manager
            app.state.wiki_ingestor = _ROUTE_WIKI_INGESTOR
            logger.info("Wiki components refreshed (vault=%s).", new_manager.vault_root)
        except Exception as exc:
            logger.warning("Failed to refresh wiki components: %s", exc)

        _AUTH_DISABLED = _env_bool("ZOPEDIA_AUTH_DISABLED", True)
        logger.info("Auth flag refreshed: _AUTH_DISABLED=%s", _AUTH_DISABLED)

        try:
            from core.database import close_pool, create_pool

            async def _refresh_db():
                await close_pool()
                _new_db_url = os.getenv("ZOPEDIA_DATABASE_URL", "").strip()
                if _new_db_url:
                    await create_pool(_new_db_url)
                    logger.info("Database pool re-initialized after soft reload.")

            asyncio.ensure_future(_refresh_db())
        except Exception as exc:
            logger.warning("Database pool re-initialization failed: %s", exc)

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
    # Stop periodic scheduler
    periodic = getattr(app.state, "periodic_scheduler", None)
    if periodic:
        try:
            await periodic.shutdown()
            logger.info("Periodic scheduler stopped.")
        except Exception as exc:
            logger.warning("Error stopping periodic scheduler: %s", exc)
    # Close database connection pool
    try:
        from core.database import close_pool
        await close_pool()
    except Exception as exc:
        logger.warning("Error closing database pool: %s", exc)


# ── App ────────────────────────────────────────────────────────────

app = FastAPI(title="Zopedia", version="0.1.0", lifespan=lifespan)

# CORS
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ── Routers ────────────────────────────────────────────────────────

from routes.wiki import router as wiki_router

app.include_router(wiki_router, prefix="/api/inference")

from routes.chat import router as chat_router

app.include_router(chat_router, prefix="/v1")


# ── Chat History API (server-side, per-user) ────────────────────────

from fastapi import APIRouter as _APIRouter, HTTPException
from starlette import status
from pydantic import BaseModel as _BaseModel

_chat_history_router = _APIRouter()


class _ChatHistoryThread(_BaseModel):
    thread_id: str
    title: Optional[str] = None
    messages: list[dict]
    created_at: Optional[str] = None


@_chat_history_router.get("/chat/threads")
async def _chat_history_list_threads(request: Request):
    from chat_history_store import list_threads

    current_subject = await _require_valid_subject(request)
    threads = list_threads(current_subject)
    logger.info("chat_history: list_threads for %s → %d threads", current_subject, len(threads))
    return {"threads": threads}


@_chat_history_router.get("/chat/threads/{thread_id}")
async def _chat_history_get_thread(thread_id: str, request: Request):
    from chat_history_store import get_thread, get_thread_messages

    current_subject = await _require_valid_subject(request)
    thread = get_thread(thread_id, current_subject)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    messages = get_thread_messages(thread_id, current_subject)
    return {"thread": thread, "messages": messages}


@_chat_history_router.post("/chat/threads")
async def _chat_history_save_thread(body: _ChatHistoryThread, request: Request):
    from datetime import datetime, timezone
    from chat_history_store import upsert_thread

    current_subject = await _require_valid_subject(request)
    logger.info(
        "chat_history: save_thread for %s thread_id=%s title=%r msgs=%d",
        current_subject, body.thread_id, body.title, len(body.messages),
    )
    now = datetime.now(timezone.utc).isoformat()
    created_at = body.created_at or now
    upsert_thread(
        thread_id=body.thread_id,
        username=current_subject,
        title=body.title,
        created_at=created_at,
        updated_at=now,
        messages=body.messages,
    )
    return {"status": "ok", "thread_id": body.thread_id}


@_chat_history_router.patch("/chat/threads/{thread_id}")
async def _chat_history_patch_thread(thread_id: str, request: Request):
    from chat_history_store import patch_thread_title

    current_subject = await _require_valid_subject(request)
    body = await request.json()
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title is required")
    updated = patch_thread_title(thread_id, current_subject, title)
    if not updated:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"status": "ok", "thread_id": thread_id, "title": title}


@_chat_history_router.delete("/chat/threads/{thread_id}")
async def _chat_history_delete_thread(thread_id: str, request: Request):
    from chat_history_store import delete_thread

    current_subject = await _require_valid_subject(request)
    deleted = delete_thread(thread_id, current_subject)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"status": "ok"}


app.include_router(_chat_history_router, prefix="/api")

# Research mode
from routes.research import router as research_router
app.include_router(research_router, prefix="")
from routes.periodic import router as periodic_router
app.include_router(periodic_router, prefix="")

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
    from routes.wiki import _WIKI_VAULT

    raw_dir = _WIKI_VAULT / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    form = await request.form()
    uploaded: list[str] = []
    failed: list[dict] = []
    allowed_ext = {
        ".md", ".txt", ".pdf", ".docx", ".pptx", ".xlsx", ".xls",
        ".html", ".htm", ".csv", ".epub", ".ipynb", ".json", ".xml",
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
        ".mp3", ".wav", ".zip",
    }

    logger.info("Upload: received %d form fields: %s", len(form), list(form.keys()))

    for field_name in form:
        value = form[field_name]
        # Collect uploadable files: single file, list of files, or skip
        items: list = []
        if hasattr(value, "filename") and hasattr(value, "read"):
            items = [value]
        elif isinstance(value, list):
            items = [v for v in value if hasattr(v, "filename") and hasattr(v, "read")]
        else:
            continue

        for file in items:
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

    logger.info("Upload: %d uploaded, %d failed", len(uploaded), len(failed))
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
    }


class _DbTestRequest(_BaseModel):
    host: str = "localhost"
    port: int = 5432
    dbname: str = ""
    user: str = ""
    password: str = ""


@app.post("/api/db/test-connection")
async def test_db_connection(body: _DbTestRequest):
    """Test a PostgreSQL connection and return available tables.

    Creates a temporary connection — does NOT affect the main pool.
    Used by the database connection setup wizard in the frontend.
    """
    from core.database import test_connection
    result = await test_connection(
        host=body.host.strip(),
        port=body.port,
        dbname=body.dbname.strip(),
        user=body.user.strip(),
        password=body.password,
    )
    return result


# ── Auth stubs (when auth is disabled) ──────────────────────────────

if _AUTH_DISABLED:
    from fastapi import APIRouter as _APIRouter

    _auth_stub = _APIRouter()

    @_auth_stub.get("/auth/status")
    async def _auth_status():
        return {"initialized": True, "requires_password_change": False, "auth_disabled": True}

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

    @_auth_stub.get("/auth/api-keys")
    async def _auth_list_api_keys():
        return {"api_keys": []}

    @_auth_stub.post("/auth/api-keys")
    async def _auth_create_api_key():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API keys require authentication to be enabled.",
        )

    @_auth_stub.delete("/auth/api-keys/{key_id}")
    async def _auth_revoke_api_key(key_id: int):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API keys require authentication to be enabled.",
        )

    app.include_router(_auth_stub, prefix="/api")
else:
    from auth.router import router as _auth_router

    app.include_router(_auth_router, prefix="/api")


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
else:
    _NO_FRONTEND_HTML = """\
<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>zopedia — frontend not built</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 540px; margin: 80px auto; padding: 0 20px; line-height: 1.6; color: #1a1a1a; background: #fafafa; }
  h1 { font-size: 1.3rem; }
  code { background: #e5e5e5; padding: 2px 6px; border-radius: 4px; font-size: 0.9rem; }
  pre { background: #2d2d2d; color: #e0e0e0; padding: 14px 18px; border-radius: 8px; overflow-x: auto; font-size: 0.85rem; line-height: 1.7; }
  a { color: #0f766e; }
</style>
<h1>Frontend not built</h1>
<p>
  The zopedia backend is running, but the frontend UI hasn&rsquo;t been built yet.
  <code>frontend/dist/</code> is not included in the git repository — you must build it locally.
</p>
<pre>cd frontend
npm install
npm run build</pre>
<p>Then restart the backend. If you already built it, check that
  <code>ZOPEDIA_FRONTEND_DIR</code> points to the <code>frontend/dist</code> directory.
</p>
<p><a href="/api/status">Check backend status</a></p>
"""

    @app.get("/{full_path:path}")
    async def _no_frontend_catchall(full_path: str):
        return HTMLResponse(content=_NO_FRONTEND_HTML, status_code=200)

    @app.get("/")
    async def _no_frontend_index():
        return HTMLResponse(content=_NO_FRONTEND_HTML, status_code=200)


# ── Main ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Zopedia on port %d", _PORT)
    uvicorn.run("main:app", host="0.0.0.0", port=_PORT, reload=False)
