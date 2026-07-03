"""GitHub release auto-updater for Zopedia desktop.

Runs a background thread that polls the GitHub releases API once per hour.
Results are cached in-process and exposed via the /api/update-status endpoint
added to the FastAPI app by launcher.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

GITHUB_REPO = "zohairshafi/zopedia"
CHECK_INTERVAL = 3600   # seconds between checks
STARTUP_DELAY = 15      # seconds after launch before first check


def _get_current_version() -> str:
    try:
        from __version__ import __version__  # noqa: PLC0415
        return __version__
    except ImportError:
        return "1.0.0"


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())


@dataclass
class UpdateInfo:
    available: bool
    current_version: str
    latest_version: str
    download_url: str | None = None
    release_notes: str | None = None
    published_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


_state: dict[str, UpdateInfo | None] = {"info": None}
_lock = threading.Lock()


def _fetch_latest() -> UpdateInfo:
    current = _get_current_version()
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"Zopedia/{current}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        print(f"[updater] GitHub check failed: {exc}", file=sys.stderr)
        return UpdateInfo(available=False, current_version=current, latest_version=current)

    tag = data.get("tag_name", "").lstrip("v")
    if not tag:
        return UpdateInfo(available=False, current_version=current, latest_version=current)

    # Find macOS .dmg asset
    download_url: str | None = None
    for asset in data.get("assets", []):
        name = asset.get("name", "").lower()
        if name.endswith(".dmg"):
            download_url = asset.get("browser_download_url")
            break

    newer = _version_tuple(tag) > _version_tuple(current)
    return UpdateInfo(
        available=newer,
        current_version=current,
        latest_version=tag,
        download_url=download_url,
        release_notes=data.get("body"),
        published_at=data.get("published_at"),
    )


def get_status() -> dict:
    """Return the latest cached update status as a dict (JSON-safe)."""
    with _lock:
        info = _state["info"]
    if info is None:
        return {"status": "checking", "available": False, "current_version": _get_current_version()}
    d = info.to_dict()
    d["status"] = "available" if info.available else "up-to-date"
    return d


def open_dmg_download(download_url: str) -> dict:
    """Download the DMG in a temp dir and open it in Finder.

    This runs synchronously — call from a FastAPI background task or thread.
    Returns {"ok": True} or {"ok": False, "error": "..."}.
    """
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="zopedia_update_"))
        dmg_name = download_url.split("/")[-1] or "Zopedia.dmg"
        dmg_path = tmp_dir / dmg_name

        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": f"Zopedia/{_get_current_version()}"},
        )
        print(f"[updater] Downloading {download_url} → {dmg_path}", file=sys.stderr)
        with urllib.request.urlopen(req, timeout=120) as resp:
            dmg_path.write_bytes(resp.read())

        subprocess.run(["open", str(dmg_path)], check=True)
        return {"ok": True, "dmg_path": str(dmg_path)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _worker() -> None:
    time.sleep(STARTUP_DELAY)
    while True:
        try:
            info = _fetch_latest()
            with _lock:
                _state["info"] = info
            if info.available:
                print(
                    f"[updater] Update available: {info.current_version} → {info.latest_version}",
                    file=sys.stderr,
                )
        except Exception as exc:
            print(f"[updater] Worker error: {exc}", file=sys.stderr)
        time.sleep(CHECK_INTERVAL)


def start_background_check() -> None:
    """Kick off the background update checker. Safe to call multiple times."""
    t = threading.Thread(target=_worker, daemon=True, name="zopedia-updater")
    t.start()
