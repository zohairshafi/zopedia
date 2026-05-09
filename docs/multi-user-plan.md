# Multi-User Server-Side Chat History — Implementation Plan

Status: **Planned, not implemented** (2026-05-09)

## Current State

### Authentication

Real JWT-based auth with SQLite exists in `backend/auth/` (storage.py, authentication.py, hashing.py) but is bypassed:

- `ZOPEDIA_AUTH_DISABLED=true` (default) replaces real endpoints with stubs in `backend/main.py`
- Stubs return hardcoded tokens for login, refresh, password-change
- Frontend (`auth-form.tsx`) hardcodes username `"unsloth"` — no username input field
- Frontend stores tokens in `localStorage` under `unsloth_auth_token` / `unsloth_auth_refresh_token`
- `current_subject` FastAPI dependency exists in `wiki.py` and `chat.py` but is never used to partition data
- Auth backend features: PBKDF2-HMAC-SHA256 (100k iterations), 60-min JWT expiry, 7-day refresh tokens, API key support, SQLite user store

### Chat History

Browser-only via IndexedDB (Dexie):

- Database: `unsloth-chat`, tables: `threads` (id, title, modelType, pairId, archived, createdAt) and `messages` (id, threadId, parentId, role, content, attachments, metadata, createdAt)
- No server-side history store exists
- Manual "Log chat history" button in `thread.tsx` (`WikiChatHistoryToggle`) saves a thread as markdown to `{WIKI_VAULT}/raw/` for wiki ingestion — not for restoring chats
- The save endpoint (`POST /api/inference/wiki/chat-history/save`) accepts `current_subject` but ignores it; all users write to the same `raw/` directory

### User Identity

- `"local-user"` when auth disabled (hardcoded)
- `"unsloth"` as sole admin when auth enabled
- No multi-user concept anywhere in the stack

---

## Implementation Plan

### Phase 1: Enable Real Auth

**Backend changes:**

1. Set `ZOPEDIA_AUTH_DISABLED=false` — real JWT tokens, real password validation, real refresh flow. All already built in `backend/auth/`.

2. Add `POST /api/auth/register` endpoint — first-user bootstrap or admin-only. The SQLite `auth_user` table already supports multiple users. Password hashing already works.

3. Update stub removal — when auth is enabled, the real auth router replaces the stubs. Already wired in `main.py`.

**Frontend changes:**

4. Add username input field to `auth-form.tsx` — currently hardcoded `"unsloth"`. Make it an editable field.

5. Add registration form — username + password + confirm password. Calls new register endpoint.

6. Update `authFetch` — already handles token refresh, 401 → redirect to login. No changes needed.

### Phase 2: Server-Side History Store

**Database schema** (add to `backend/auth/storage.py` or new `backend/chat_history_store.py`):

```sql
CREATE TABLE IF NOT EXISTS chat_threads (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    username TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    reasoning_content TEXT,
    parent_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES chat_threads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chat_threads_username ON chat_threads(username);
CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_id ON chat_messages(thread_id);
```

**API endpoints:**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/chat/threads` | List threads for `current_subject`. Returns `[{id, title, created_at, updated_at, message_count}]` |
| `GET` | `/api/chat/threads/{id}` | Load full thread with messages. Returns `{thread: {...}, messages: [...]}` |
| `POST` | `/api/chat/threads` | Upsert thread + messages. Body: `{thread_id, title, messages: [{id, role, content, ...}]}`. Replaces all messages for this thread (simpler than diff-based). |
| `DELETE` | `/api/chat/threads/{id}` | Delete a thread. |

All endpoints use `current_subject: str = Depends(get_current_subject)` to scope data to the authenticated user.

**Message size handling:**

- Cap `content` at 100KB per message
- If truncated, append `\n\n...(truncated at {limit} chars, original: {size} chars)`
- Tool call content (full wiki pages) is the main source of large messages

### Phase 3: Frontend Sync

**Data flow:**

```
App load → GET /api/chat/threads → merge with IndexedDB (server wins on updated_at)
         → User opens thread → GET /api/chat/threads/{id} → populate local Dexie
         → User sends message → assistant responds → POST /api/chat/threads (debounced 2s)
         → User closes app → last POST completes
```

**Migration path:**

On first sync, if server has zero threads but IndexedDB has data:
- Show toast: "Import {N} local conversations to your account?"
- One-click: POST all local threads to server
- Skip: start fresh, local data stays in IndexedDB but won't sync

**Conflict resolution:**

- Last-write-wins per thread, using `updated_at` timestamp
- Simple, correct for single-user-per-account (personal wiki, not collaborative editing)

**Logout behavior:**

- Clear IndexedDB cache (local copy)
- Clear localStorage tokens
- Redirect to login
- On next login, re-sync from server

### Phase 4: Wiki Chat History (Secondary Path)

The existing manual "Log chat history" flow continues but scoped by user:

- Save path: `raw/users/{username}/chat-history-{safe_id}-{timestamp}.md`
- Watcher picks up new files automatically (same raw/ watcher)
- Files ingested into the wiki as before, but partitioned by user
- When auth is disabled, fall back to `raw/chat-history-...` (current behavior)

---

## Potential Issues

| Issue | Risk | Mitigation |
|---|---|---|
| **IndexedDB → server migration** | Medium | One-click import prompt on first sync. Non-destructive — keep local data until confirmed. |
| **Message content size** | Medium | Cap at 100KB/message, truncate with marker. Full wiki page reads in tool results are the main large payload. |
| **Concurrent device writes** | Low | Last-write-wins with `updated_at`. Single-user-per-account makes this a non-issue in practice. |
| **Auth disabled mode** | Low | When `ZOPEDIA_AUTH_DISABLED=true`, skip all server history — keep current IndexedDB-only behavior. Zero breaking change. |
| **Token expiry during long chat** | Low | `authFetch` already auto-refreshes on 401. Refresh token valid for 7 days. |
| **SQLite concurrent access** | Low | SQLite handles multiple readers. Writes are serialized. FastAPI's single-threaded event loop means no real contention for a personal wiki. |
| **Wiki ingestion of chat history** | Low | User-scoped `raw/users/{username}/` subdirectory. Watcher handles all subdirectories automatically. |
| **Frontend auth-form hardcodes `"unsloth"`** | Low | Add username input field. Backend already supports multiple users. |

---

## What Doesn't Break

- **Single-user mode** (auth disabled): Works identically to today. No server history, no auth, IndexedDB-only.
- **Wiki RAG + tool-calling**: No changes to `chat.py`, `engine.py`, or the tool-calling protocol.
- **Ingestion + watcher + maintenance**: Unchanged. User-scoped chat history files are just another file in `raw/`.
- **Manual "Log chat history" button**: Remains functional as a secondary wiki-ingestion path.
- **Upstream API config**: Per-server, not per-user. All users share the same LLM backend config.

---

## Upsides

- **Cross-device**: Chat on laptop, continue on phone. Same threads, same history.
- **Data persistence**: Clear browser data without losing chat history.
- **Multi-user**: Family/team wiki with individual chat histories, shared wiki knowledge base.
- **Auditability**: Server-side history can be wiki-ingested for long-term knowledge retention.
- **Auth already built**: JWT, password hashing, SQLite, token refresh — all functional. This is wiring, not greenfield.
- **Graceful degradation**: Auth disabled = current behavior. No migration required for existing single-user setups.

---

## Implementation Order (Recommended)

1. **Phase 1 (auth)**: Username field + real auth enablement. Smallest change, tests the auth stack end-to-end.
2. **Phase 2 (server store)**: SQLite tables + CRUD endpoints. Can be tested with curl independently.
3. **Phase 3 (frontend sync)**: Dexie → server bridge. The bulk of the frontend work.
4. **Phase 4 (wiki history)**: User-scoped chat history files. Small change on top of Phase 2.
