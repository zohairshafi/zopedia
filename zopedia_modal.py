"""Zopedia on Modal — lightweight personal wiki + RAG chat, serverless.

Usage:
    modal deploy zopedia_modal.py   # Deploy as a persistent web endpoint
    modal run zopedia_modal.py      # One-shot (local tunnel for testing)

Prerequisites:
    modal volume create zopedia-wiki-data
    modal secret create zopedia-env \
        ZOPEDIA_LLM_BASE_URL=https://api.deepseek.com/v1 \
        ZOPEDIA_LLM_API_KEY=sk-... \
        ZOPEDIA_LLM_MODEL=deepseek-v4-flash

    # Enable auth (optional):
    modal secret create zopedia-env \
        ZOPEDIA_AUTH_DISABLED=false

    # Upload existing wiki (optional):
    modal volume put zopedia-wiki-data backend/wiki_data/ /app/wiki_data/
"""

import modal

# ── Image ──────────────────────────────────────────────────────────
# python:3.12-slim is the lightest image that can run Zopedia.
# No GPU needed — Zopedia proxies to an external LLM API.
ZK_DATA = "/app/wiki_data"

image = (
    modal.Image.from_registry("python:3.12-slim")
    .run_commands(
        "pip install --no-cache-dir fastapi uvicorn pydantic httpx watchdog "
        "ddgs networkx markitdown openai pyjwt diceware",
    )
    .add_local_dir("backend", "/app", copy=True, ignore=["wiki_data"])
    .add_local_dir("graphify/graphify", "/app/graphify", copy=True)
    .add_local_dir("frontend/dist", "/app/frontend/dist", copy=True)
    .env({
        "ZOPEDIA_FRONTEND_DIR": "/app/frontend/dist",
        "ZOPEDIA_HOME": ZK_DATA,
        "ZOPEDIA_WIKI_VAULT": ZK_DATA,
    })
)

# ── Volume ─────────────────────────────────────────────────────────
try:
    wiki_volume = modal.Volume.from_name("zopedia-wiki-data", create_if_missing=True)
except Exception:
    wiki_volume = None

# ── App ────────────────────────────────────────────────────────────
app = modal.App("zopedia", image=image)


@app.function(
    volumes={ZK_DATA: wiki_volume} if wiki_volume else {},
    secrets=[modal.Secret.from_name("zopedia-env")],
    cpu=1,
    scaledown_window=300,
    timeout=600,
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def serve():
    import sys
    sys.path.insert(0, "/app")
    from main import app as fastapi_app
    return fastapi_app
