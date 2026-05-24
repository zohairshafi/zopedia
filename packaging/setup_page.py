"""First-run setup: self-contained HTML form injected into the Zopedia app.

On first run, the launcher patches /__zopedia_setup__ and
/__zopedia_setup_save__ routes onto the FastAPI app before starting.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

SETUP_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Welcome to Zopedia</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:system-ui,-apple-system,sans-serif;background:#0d0d0d;color:#e0e0e0;
       display:flex;align-items:center;justify-content:center;min-height:100vh}
  .card{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;
         padding:32px;max-width:440px;width:100%}
  h1{font-size:1.3rem;margin-bottom:4px}
  p.sub{color:#888;font-size:.85rem;margin-bottom:20px}
  label{display:block;font-size:.8rem;color:#aaa;margin-bottom:4px;margin-top:14px}
  input{width:100%;padding:8px 10px;border:1px solid #333;border-radius:6px;
         background:#111;color:#e0e0e0;font-size:.9rem}
  input:focus{outline:none;border-color:#4f8}
  button{margin-top:20px;width:100%;padding:10px;border:none;border-radius:6px;
         background:#2ea043;color:#fff;font-size:.9rem;font-weight:600;cursor:pointer}
  button:hover{background:#3cb350}
  button.secondary{background:#333;color:#ccc;font-size:.8rem;width:auto;padding:6px 12px;margin-top:6px}
  button.secondary:hover{background:#444}
  .hint{font-size:.75rem;color:#666;margin-top:4px}
  .saved{display:none;text-align:center;padding:20px;color:#4f8}
  hr{border:none;border-top:1px solid #2a2a2a;margin:20px 0 8px}
  .auth-section{margin-top:4px}
  .auth-toggle{display:flex;align-items:center;gap:10px;margin-top:14px}
  .auth-toggle input[type=checkbox]{width:auto;accent-color:#2ea043}
  .auth-toggle label{margin:0;font-size:.85rem;color:#ccc}
  .auth-fields{display:none;margin-top:4px}
  .auth-fields.visible{display:block}
  .pw-row{display:flex;gap:8px;align-items:flex-end}
  .pw-row input{flex:1}
  .pw-row button{width:auto;padding:8px 12px;margin:0;white-space:nowrap}
  .note{font-size:.75rem;color:#856404;background:#332b00;border:1px solid #664d00;
         border-radius:6px;padding:8px 10px;margin-top:10px}
</style>
</head>
<body>
<div class="card" id="form-card">
  <h1>Welcome to Zopedia</h1>
  <p class="sub">Connect your LLM provider to get started.</p>
  <form>
    <label for="base">LLM Base URL</label>
    <input id="base" name="llm_base_url" type="url"
           placeholder="https://api.deepseek.com/v1" required>
    <span class="hint">Any OpenAI-compatible endpoint (DeepSeek, OpenAI, Ollama, etc.)</span>

    <label for="key">API Key</label>
    <input id="key" name="llm_api_key" type="password"
           placeholder="sk-..." required>

    <label for="model">Model Name</label>
    <input id="model" name="llm_model" type="text"
           placeholder="deepseek-v4-flash" required>

    <label for="wiki">Wiki Directory (optional)</label>
    <input id="wiki" name="wiki_vault" type="text"
           placeholder="Leave empty for default">

    <hr>
    <div class="auth-section">
      <div class="auth-toggle">
        <input type="checkbox" id="auth_enabled" name="auth_enabled">
        <label for="auth_enabled">Enable authentication (password-protect the app)</label>
      </div>
      <div class="auth-fields" id="auth-fields">
        <label for="admin_pw">Admin Password</label>
        <div class="pw-row">
          <input id="admin_pw" name="admin_password" type="text"
                 placeholder="Enter a password or generate one">
          <button type="button" class="secondary" id="gen-pw">Generate</button>
        </div>
        <span class="hint">Username: <strong>zopedia</strong>. You will log in with this password.</span>
        <div class="note">Auth changes take effect on next launch. This session will remain unauthenticated.</div>
      </div>
    </div>

    <button type="submit">Save &amp; Launch</button>
  </form>
</div>
<div class="saved" id="saved-msg">
  <h1>Saved</h1>
  <p>Redirecting to Zopedia&hellip;</p>
</div>
<script>
var form = document.forms[0];
var authCheckbox = document.getElementById('auth_enabled');
var authFields = document.getElementById('auth-fields');
var genBtn = document.getElementById('gen-pw');
var adminPwInput = document.getElementById('admin_pw');

authCheckbox.addEventListener('change', function() {
  authFields.className = 'auth-fields' + (this.checked ? ' visible' : '');
});

genBtn.addEventListener('click', async function() {
  genBtn.disabled = true;
  genBtn.textContent = '...';
  try {
    var res = await fetch('/__zopedia_setup_generate_password__');
    if (res.ok) {
      adminPwInput.value = await res.text();
    }
  } catch (err) {
    // ignore
  } finally {
    genBtn.disabled = false;
    genBtn.textContent = 'Generate';
  }
});

// Auto-generate a password on load
(async function() {
  try {
    var res = await fetch('/__zopedia_setup_generate_password__');
    if (res.ok && !adminPwInput.value) {
      adminPwInput.value = await res.text();
    }
  } catch (err) {
    // ignore
  }
})();

form.addEventListener('submit', async function(e) {
  e.preventDefault();
  var fd = new FormData(form);
  var data = {};
  fd.forEach(function(v, k) { data[k] = v; });
  data.auth_enabled = authCheckbox.checked;
  try {
    var res = await fetch('/__zopedia_setup_save__', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    if (res.ok) {
      document.getElementById('form-card').style.display = 'none';
      document.getElementById('saved-msg').style.display = 'block';
      var next = new URLSearchParams(window.location.search).get('next') || '/chat';
      setTimeout(function(){ window.location = next; }, 2000);
    } else {
      var err = await res.json().catch(function(){ return {}; });
      alert('Save failed: ' + (err.detail || res.status));
    }
  } catch (err) {
    alert('Network error: ' + err.message);
  }
});
</script>
</body>
</html>
"""


class SetupPayload(BaseModel):
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    wiki_vault: str = ""
    auth_enabled: bool = False
    admin_password: str = ""


def make_setup_routes(app: FastAPI, config_path: str) -> None:
    """Attach first-run setup routes to an existing FastAPI app."""

    @app.get("/__zopedia_setup__")
    async def _setup_page():
        return HTMLResponse(SETUP_HTML)

    @app.get("/__zopedia_setup_generate_password__")
    async def _setup_generate_password():
        try:
            import diceware
            pw = diceware.get_passphrase(
                options=diceware.handle_options(args=["-n", "4", "-d", "-", "-c"])
            )
            return PlainTextResponse(pw)
        except Exception:
            # Fallback: generate a simple random password
            import secrets
            return PlainTextResponse(secrets.token_urlsafe(16))

    @app.post("/__zopedia_setup_save__")
    async def _setup_save(body: SetupPayload):
        import json
        import os as _os
        from pathlib import Path as _Path

        cfg_path = _Path(config_path)
        cfg: dict = {}
        if cfg_path.is_file():
            try:
                cfg = json.loads(cfg_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        cfg.update(
            {
                "llm_base_url": body.llm_base_url.strip(),
                "llm_api_key": body.llm_api_key.strip(),
                "llm_model": body.llm_model.strip(),
                "wiki_vault": body.wiki_vault.strip(),
                "auth_enabled": body.auth_enabled,
                "admin_password": body.admin_password.strip() if body.auth_enabled else "",
                "first_run": False,
            }
        )

        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cfg_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
        _os.replace(tmp, cfg_path)

        # Apply to current process env so the running server picks them up
        for key, env_key in [
            ("llm_base_url", "ZOPEDIA_LLM_BASE_URL"),
            ("llm_api_key", "ZOPEDIA_LLM_API_KEY"),
            ("llm_model", "ZOPEDIA_LLM_MODEL"),
            ("wiki_vault", "ZOPEDIA_WIKI_VAULT"),
            ("admin_password", "ZOPEDIA_ADMIN_PASSWORD"),
        ]:
            val = cfg.get(key)
            if val:
                _os.environ[env_key] = val

        return {"status": "ok"}
