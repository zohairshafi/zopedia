"""Shared auth root path with migration from legacy Unsloth Studio location."""

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger("zopedia")

_ZOPEDIA_HOME = os.getenv("ZOPEDIA_HOME", str(Path.home()))
OLD_ROOT = Path.home() / ".unsloth" / "studio" / "auth"
NEW_ROOT = Path(_ZOPEDIA_HOME) / ".zopedia" / "auth"

_migrated = False


def _migrate_if_needed() -> None:
    global _migrated
    if _migrated:
        return
    _migrated = True

    if NEW_ROOT.exists():
        return
    if not OLD_ROOT.exists():
        return

    logger.info("Migrating auth data from %s to %s", OLD_ROOT, NEW_ROOT)
    NEW_ROOT.mkdir(parents=True, exist_ok=True)
    for item in OLD_ROOT.iterdir():
        dst = NEW_ROOT / item.name
        if item.is_file() and not dst.exists():
            shutil.copy2(item, dst)
            logger.info("  Copied %s", item.name)
    logger.info("Migration complete.")


def get_auth_root() -> Path:
    _migrate_if_needed()
    NEW_ROOT.mkdir(parents=True, exist_ok=True)
    return NEW_ROOT
