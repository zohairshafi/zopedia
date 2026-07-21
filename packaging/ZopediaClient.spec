# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Zopedia Client desktop app (thin client).

Bundles ONLY the client SPA + a tiny static file server + pywebview. There is
no backend, no LLM, and no wiki/ingest deps here — that lightness is the whole
point of the client. As a result this builds much faster and smaller than the
server app (Zopedia.spec).

Build (from repo root, using the arm64 packaging venv):
    (cd frontend && npm run build:client)        # produces frontend/dist-client
    source .venv-packaging/bin/activate
    rm -rf "dist/Zopedia Client.app" dist/ZopediaClient build/ZopediaClient
    pyinstaller --clean packaging/ZopediaClient.spec

Output: dist/Zopedia Client.app
"""

import sys
from pathlib import Path

_PROJECT = Path(SPECPATH).resolve().parent  # noqa: F821 — SPECPATH is injected by PyInstaller

_icon = (
    str(_PROJECT / "packaging" / "icon.icns")
    if Path(str(_PROJECT / "packaging" / "icon.icns")).exists()
    else str(_PROJECT / "packaging" / "icon.png")
)

# pywebview loads its Cocoa platform dynamically.
_hiddenimports = [
    "webview",
    "webview.platforms.cocoa",
]

# The prebuilt client SPA — served at runtime by launcher_client.py.
_datas: list[tuple[str, str]] = [
    (str(_PROJECT / "frontend" / "dist-client"), "frontend/dist-client"),
]

_excludes = [
    "tkinter",
]


def _read_version() -> str:
    """Read __version__ from packaging/__version__.py for the About box."""
    try:
        for line in (_PROJECT / "packaging" / "__version__.py").read_text().splitlines():
            line = line.strip()
            if line.startswith("__version__"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return "0.0.0"


_app_version = _read_version()

a = Analysis(
    [str(_PROJECT / "packaging" / "launcher_client.py")],
    pathex=[str(_PROJECT / "packaging")],
    datas=_datas,
    hiddenimports=_hiddenimports,
    excludes=_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# Internal binary name has no space (avoids quoting issues in tooling); the
# bundle/display name is "Zopedia Client" via the plist below.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ZopediaClient",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ZopediaClient",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Zopedia Client.app",
        icon=_icon,
        bundle_identifier="com.zopedia.client",
        info_plist={
            "CFBundleName": "Zopedia Client",
            "CFBundleDisplayName": "Zopedia Client",
            "CFBundleVersion": _app_version,
            "CFBundleShortVersionString": _app_version,
            "NSHighResolutionCapable": True,
            "LSBackgroundOnly": False,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
