"""System tray icon via pystray. Menu: Open Browser, Quit."""

from __future__ import annotations

import webbrowser
from pathlib import Path

from PIL import Image, ImageDraw

_ICON_PATH = Path(__file__).resolve().parent / "icon.png"


def _make_fallback_icon() -> Image.Image:
    """Generate a simple 64x64 icon if icon.png is missing."""
    img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([4, 4, 60, 60], radius=12, fill="#2ea043")
    draw.text((20, 18), "Z", fill="#fff")
    return img


def _load_icon() -> Image.Image:
    if _ICON_PATH.is_file():
        return Image.open(_ICON_PATH)
    return _make_fallback_icon()


def run_tray(port: int, server_should_exit_cb) -> None:
    """Run the tray icon on the calling thread. Blocks until Quit is selected.

    *server_should_exit_cb* is called when the user selects Quit — it
    should arrange for the uvicorn server to shut down.
    """
    import pystray

    def _open(icon, item):
        webbrowser.open(f"http://127.0.0.1:{port}")

    def _quit(icon, item):
        server_should_exit_cb()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open in Browser", _open, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", _quit),
    )
    icon = pystray.Icon("Zopedia", _load_icon(), menu=menu, title="Zopedia")
    icon.run()
