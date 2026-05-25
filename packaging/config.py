"""Config persistence via platformdirs. Single JSON file, minimal surface."""

import json
import os
from pathlib import Path

from platformdirs import PlatformDirs

_dirs = PlatformDirs("Zopedia", "Zopedia")
CONFIG_PATH = Path(_dirs.user_config_dir) / "config.json"
WIKI_DEFAULT = Path.home() / "zopedia"

DEFAULTS: dict[str, object] = {
    "llm_base_url": "",
    "llm_api_key": "",
    "llm_model": "",
    "wiki_vault": "",
    "first_run": True,
    "auth_enabled": False,
    "admin_password": "",
}


def load() -> dict:
    if CONFIG_PATH.is_file():
        try:
            raw = json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            raw = {}
        merged = dict(DEFAULTS)
        merged.update({k: v for k, v in raw.items() if k in DEFAULTS})
        return merged
    return dict(DEFAULTS)


def save(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, CONFIG_PATH)


def env_from_config(config: dict) -> dict[str, str]:
    """Convert config keys to ZOPEDIA_* env vars for the real server."""
    env: dict[str, str] = {}
    if config.get("llm_base_url"):
        env["ZOPEDIA_LLM_BASE_URL"] = str(config["llm_base_url"])
    if config.get("llm_api_key"):
        env["ZOPEDIA_LLM_API_KEY"] = str(config["llm_api_key"])
    if config.get("llm_model"):
        env["ZOPEDIA_LLM_MODEL"] = str(config["llm_model"])
    if config.get("wiki_vault"):
        env["ZOPEDIA_WIKI_VAULT"] = str(config["wiki_vault"])
    if config.get("admin_password"):
        env["ZOPEDIA_ADMIN_PASSWORD"] = str(config["admin_password"])
    return env
