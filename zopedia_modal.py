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
        # Install Node.js 22.x for frontend build
        "apt-get update && apt-get install -y curl gnupg && "
        "curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && "
        "apt-get install -y nodejs && "
        "apt-get clean && rm -rf /var/lib/apt/lists/*",
        # Install Python deps
        "pip install --no-cache-dir fastapi uvicorn pydantic httpx watchdog "
        'ddgs networkx "markitdown[all]" openai pyjwt diceware asyncpg',
    )
    # Copy frontend source FIRST, build it, then backend can reference the dist/
    .add_local_dir("frontend", "/app/frontend", copy=True,
                   ignore=["node_modules", "dist", "dist-client", "ios"])
    .run_commands(
        "cd /app/frontend && npm install && npm run build",
    )
    .add_local_dir("backend", "/app", copy=True, ignore=["wiki_data"])
    .add_local_dir("graphify/graphify", "/app/graphify", copy=True)
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
    timeout=7200,
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def serve():
    import sys
    sys.path.insert(0, "/app")
    from main import app as fastapi_app
    return fastapi_app


# ── Admin helpers ────────────────────────────────────────────────────
# Run via:  modal run zopedia_modal.py::list_users
#           modal run zopedia_modal.py::reset_password


@app.function(
    volumes={ZK_DATA: wiki_volume} if wiki_volume else {},
    secrets=[modal.Secret.from_name("zopedia-env")],
    cpu=1,
    timeout=300,
)
def list_users():
    """Print all users in the auth database."""
    import sqlite3
    from pathlib import Path

    auth_root = Path("/app/wiki_data") / ".zopedia" / "auth"
    db_path = auth_root / "auth.db"

    if not db_path.exists():
        print(f"auth.db not found at {db_path}")
        print("Has the app been deployed yet? The DB is created on first startup.")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT username, must_change_password FROM auth_user ORDER BY id"
    ).fetchall()
    conn.close()

    if not rows:
        print("No users found.")
        return

    print(f"{'Username':<20} {'Must Change PW':<15}")
    print("-" * 35)
    for r in rows:
        print(f"{r['username']:<20} {str(bool(r['must_change_password'])):<15}")


@app.function(
    volumes={ZK_DATA: wiki_volume} if wiki_volume else {},
    secrets=[modal.Secret.from_name("zopedia-env")],
    cpu=1,
    timeout=300,
)
def reset_password(username: str = "zopedia", new_password: str = ""):
    """Reset a user's password. Generates a new diceware passphrase if
    none is provided.  Prints it ONCE — it is not stored anywhere else.

    Usage:
        modal run zopedia_modal.py::reset_password
        modal run zopedia_modal.py::reset_password --username alice
        modal run zopedia_modal.py::reset_password --new-password 'my-pw'
    """
    import sqlite3
    from pathlib import Path

    auth_root = Path("/app/wiki_data") / ".zopedia" / "auth"
    db_path = auth_root / "auth.db"

    if not db_path.exists():
        print(f"auth.db not found at {db_path}")
        return

    if new_password:
        password = new_password
    else:
        import diceware
        password = diceware.get_passphrase(
            options=diceware.handle_options(args=["-n", "4", "-d", "", "-c"])
        )

    # Hash the password using the same algorithm as auth/hashing.py:
    # PBKDF2-HMAC-SHA256, 100k iterations, 16-byte hex salt.
    import hashlib
    import secrets as _secrets

    salt = _secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    )
    password_hash = dk.hex()

    new_jwt = _secrets.token_urlsafe(64)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        """UPDATE auth_user
           SET password_salt = ?, password_hash = ?, jwt_secret = ?,
               must_change_password = 0
           WHERE username = ?""",
        (salt, password_hash, new_jwt, username),
    )
    conn.commit()
    updated = cursor.rowcount
    conn.close()

    if updated == 0:
        print(f"User '{username}' not found.")
        return

    print(f"Password reset for '{username}'.")
    if not new_password:
        print(f"New password: {password}")
        print("(this is the only time it will be shown)")


# ── Chat history migration ───────────────────────────────────────────
# Run via:  modal run zopedia_modal.py::export_chat_history
#           modal run zopedia_modal.py::import_chat_history


@app.function(
    volumes={ZK_DATA: wiki_volume} if wiki_volume else {},
    secrets=[modal.Secret.from_name("zopedia-env")],
    cpu=1,
    timeout=600,
)
def export_chat_history(output_file: str = "/tmp/zopedia_chat_export.json"):
    """Export all chat threads and messages as JSON.  Download the result with:

        modal volume get zopedia-wiki-data /tmp/zopedia_chat_export.json .
    """
    import json
    import sqlite3
    from pathlib import Path

    auth_root = Path("/app/wiki_data") / ".zopedia" / "auth"
    db_path = auth_root / "chat_history.db"

    if not db_path.exists():
        print(f"chat_history.db not found at {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    threads = conn.execute(
        "SELECT id, username, title, created_at, updated_at FROM chat_threads ORDER BY created_at"
    ).fetchall()

    result = {"threads": []}
    for t in threads:
        msgs = conn.execute(
            "SELECT id, role, content, reasoning_content, parent_id, created_at "
            "FROM chat_messages WHERE thread_id = ? AND username = ? "
            "ORDER BY created_at",
            (t["id"], t["username"]),
        ).fetchall()
        result["threads"].append({
            "id": t["id"],
            "username": t["username"],
            "title": t["title"],
            "created_at": t["created_at"],
            "updated_at": t["updated_at"],
            "messages": [dict(m) for m in msgs],
        })
    conn.close()

    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(f"Exported {len(result['threads'])} threads to {output_file}")
    print("Download with:")
    print(f"  modal volume get zopedia-wiki-data {output_file} .")


@app.function(
    volumes={ZK_DATA: wiki_volume} if wiki_volume else {},
    secrets=[modal.Secret.from_name("zopedia-env")],
    cpu=1,
    timeout=600,
)
def import_chat_history(input_file: str = "/tmp/zopedia_chat_export.json"):
    """Import threads from a JSON export file on the Modal volume.  Upload
    your export file first with:

        modal volume put zopedia-wiki-data ./local_export.json /tmp/zopedia_chat_export.json
        modal run zopedia_modal.py::import_chat_history
    """
    import json
    import sqlite3
    from pathlib import Path

    in_path = Path(input_file)
    if not in_path.exists():
        print(f"File not found: {input_file}")
        print("Upload your export first:")
        print("  modal volume put zopedia-wiki-data ./local_export.json /tmp/zopedia_chat_export.json")
        return

    data = json.loads(in_path.read_text())
    threads = data.get("threads", [])

    auth_root = Path("/app/wiki_data") / ".zopedia" / "auth"
    db_path = auth_root / "chat_history.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS chat_threads (
            id TEXT NOT NULL, username TEXT NOT NULL, title TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (id, username))"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT NOT NULL, thread_id TEXT NOT NULL, username TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT, reasoning_content TEXT,
            parent_id TEXT, created_at TEXT NOT NULL,
            PRIMARY KEY (id, username),
            FOREIGN KEY (thread_id, username) REFERENCES chat_threads(id, username) ON DELETE CASCADE)"""
    )

    imported_threads = 0
    imported_msgs = 0
    for t in threads:
        conn.execute(
            "INSERT OR REPLACE INTO chat_threads (id, username, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (t["id"], t["username"], t["title"], t["created_at"], t["updated_at"]),
        )
        imported_threads += 1
        for m in t.get("messages", []):
            conn.execute(
                "INSERT OR REPLACE INTO chat_messages "
                "(id, thread_id, username, role, content, reasoning_content, parent_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (m["id"], t["id"], t["username"], m["role"], m["content"],
                 m.get("reasoning_content"), m.get("parent_id"), m["created_at"]),
            )
            imported_msgs += 1

    conn.commit()
    conn.close()
    print(f"Imported {imported_threads} threads, {imported_msgs} messages.")
