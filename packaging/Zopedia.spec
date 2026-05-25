# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Zopedia desktop app.

Build:
    pyinstaller --clean Zopedia.spec

Output lands in dist/Zopedia.app (macOS) or dist/Zopedia/ (Windows).
"""

import sys
from pathlib import Path

_PROJECT = Path(SPECPATH).resolve().parent  # noqa: F821 — SPECPATH is injected by PyInstaller

# ── Hidden imports ──────────────────────────────────────────────────

_hiddenimports = [
    # uvicorn submodules (dynamically loaded by string import)
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    # Auth modules (try/except imported in main.py)
    "auth",
    "auth.storage",
    "auth.authentication",
    "auth.hashing",
    "auth.router",
    "utils.auth_root",
    "chat_history_store",
    # Wiki core (many lazy imports)
    "core.wiki.manager",
    "core.wiki.ingestor",
    "core.wiki.watcher",
    "core.wiki.runtime_env",
    "core.wiki.bridge",
    "core.wiki.engine",
    "core.llm",
    # Routes
    "routes.wiki",
    "routes.chat",
    # Packaging modules (imported dynamically or via uvicorn string)
    "config",
    "setup_page",
    "tray",
    # Graphify (lazy imports via importlib)
    "graphify",
    "graphify.ingest",
    "graphify.detect",
    "graphify.cache",
    "graphify.analyze",
    "graphify.wiki",
    "graphify.security",
    # FastAPI / Starlette internals
    "fastapi",
    "starlette.routing",
    "pydantic",
    # Other runtime deps
    "watchdog.observers",
    "watchdog.observers.fsevents",
    "networkx",
    "httpx",
    "ddgs",
    "markitdown",
    "openai",
    "jwt",
    "diceware",
    "platformdirs",
    # Lazy imports inside functions — missed by PyInstaller static analysis
    # PDF / document parsing
    "pypdf",
    "pypdfium2",
    "pdfminer",
    "pdfminer.high_level",
    "pdfplumber",
    "pymupdf4llm",
    "pymupdf",
    "pymupdf_layout",
    # DOCX / PPTX / XLSX
    "mammoth",
    "pptx",
    "pandas",
    # YouTube transcript
    "youtube_transcript_api",
    # Audio transcription
    "pydub",
    "speech_recognition",
    # Azure Document Intelligence
    "azure.ai.documentintelligence",
    "azure.core.credentials",
    "azure.identity",
]

# ── Data files ──────────────────────────────────────────────────────

_datas: list[tuple[str, str]] = [
    # Frontend SPA
    (str(_PROJECT / "frontend" / "dist"), "frontend/dist"),
    # Graphify package (needs to be importable as graphify/)
    (str(_PROJECT / "graphify" / "graphify"), "graphify"),
    # Packaging modules (config, setup_page, tray — imported at runtime)
    (str(_PROJECT / "packaging" / "config.py"), "config.py"),
    (str(_PROJECT / "packaging" / "setup_page.py"), "setup_page.py"),
    (str(_PROJECT / "packaging" / "tray.py"), "tray.py"),
    (str(_PROJECT / "packaging" / "icon.png"), "icon.png"),
]

# ── Excludes (shrink bundle) ────────────────────────────────────────

_excludes = [
    "tkinter",
    "matplotlib",
    "numpy",
    "scipy",
    "pandas",
    "PIL._tkinter_finder",
]

# ── Binaries ────────────────────────────────────────────────────────
# Collect tree-sitter .so/.dylib files from graphify dependencies

_binaries: list[tuple[str, str]] = []

# ── Spec ────────────────────────────────────────────────────────────

a = Analysis(
    [str(_PROJECT / "packaging" / "launcher.py")],
    pathex=[str(_PROJECT / "backend"), str(_PROJECT), str(_PROJECT / "packaging")],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Zopedia",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(_PROJECT / "packaging" / "icon.png") if sys.platform != "darwin"
         else str(_PROJECT / "packaging" / "icon.icns") if Path(str(_PROJECT / "packaging" / "icon.icns")).exists()
         else str(_PROJECT / "packaging" / "icon.png"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Zopedia",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Zopedia.app",
        icon=str(_PROJECT / "packaging" / "icon.icns") if Path(str(_PROJECT / "packaging" / "icon.icns")).exists()
             else str(_PROJECT / "packaging" / "icon.png"),
        bundle_identifier="com.zopedia.app",
        info_plist={
            "CFBundleName": "Zopedia",
            "CFBundleDisplayName": "Zopedia",
            "CFBundleVersion": "1.0.0",
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSBackgroundOnly": False,
        },
    )
