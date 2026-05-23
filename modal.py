"""Zopedia on Modal — lightweight personal wiki + RAG chat, serverless.

Usage:
    modal deploy modal.py          # Deploy as a persistent web endpoint
    modal run modal.py             # One-shot (local tunnel for testing)

Prerequisites:
    modal volume create zopedia-wiki-data
    modal secret create zopedia-env \\
        ZOPEDIA_LLM_BASE_URL=https://api.deepseek.com/v1 \\
        ZOPEDIA_LLM_API_KEY=sk-... \\
        ZOPEDIA_LLM_MODEL=deepseek-v4-flash

Optional:
    modal secret create zopedia-env \\
        ZOPEDIA_AUTH_DISABLED=false \\
        ZOPEDIA_PORT=8000
"""

import modal

# ── Image ──────────────────────────────────────────────────────────
# python:3.12-slim is the lightest image that can run Zopedia.
# No GPU needed — Zopedia proxies to an external LLM API.
image = (
    modal.Image.from_registry("python:3.12-slim", add_python=None)
    .run_commands(
        "pip install --no-cache-dir fastapi uvicorn pydantic httpx watchdog "
        "ddgs networkx markitdown openai",
    )
    .add_local_dir("backend", "/app", copy=True)
    .add_local_dir("frontend/dist", "/app/frontend/dist", copy=True)
    .env({"ZOPEDIA_FRONTEND_DIR": "/app/frontend/dist"})
)

# ── Volume ─────────────────────────────────────────────────────────
try:
    wiki_volume = modal.Volume.from_name("zopedia-wiki-data", create_if_missing=True)
except Exception:
    wiki_volume = None

# ── App ────────────────────────────────────────────────────────────
app = modal.App("zopedia", image=image)


@app.function(
    volumes={"/app/wiki_data": wiki_volume} if wiki_volume else {},
    secrets=[modal.Secret.from_name("zopedia-env")],
    allow_concurrent_inputs=100,
    container_idle_timeout=300,
    timeout=600,
)
@modal.asgi_app()
def serve():
    import sys
    sys.path.insert(0, "/app")
    from main import app as fastapi_app
    return fastapi_app
