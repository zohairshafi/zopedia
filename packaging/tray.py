"""System tray icon via PyObjC NSStatusBar. Click shows menu with Open and Quit."""

from __future__ import annotations

import sys
import uuid
import webbrowser
from pathlib import Path

from AppKit import (
    NSApplication,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSData, NSObject
import objc


class _Delegate(NSObject):
    """Handles menu actions and dock-icon reopen events."""

    _port: int = 0
    _shutdown_cb: object = None

    def _open_browser(self):
        new_id = uuid.uuid4().hex[:12]
        webbrowser.open(f"http://127.0.0.1:{self._port}/chat?new={new_id}")

    @objc.selector
    def openBrowser_(self, sender):
        self._open_browser()

    @objc.selector
    def quitApp_(self, sender):
        if self._shutdown_cb:
            self._shutdown_cb()
        NSApplication.sharedApplication().terminate_(None)

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, flag: bool) -> bool:
        """Called when the dock icon is clicked while the app is running."""
        self._open_browser()
        return True


def _load_icon() -> NSImage | None:
    if hasattr(sys, "_MEIPASS"):
        icon_path = Path(sys._MEIPASS) / "icon.png"
    else:
        icon_path = Path(__file__).resolve().parent / "icon.png"
    if icon_path.is_file():
        data = NSData.dataWithContentsOfFile_(str(icon_path))
        if data:
            return NSImage.alloc().initWithData_(data)
    return None


def run_tray(port: int, server_should_exit_cb) -> None:
    """Run the status bar icon on the calling thread. Blocks until Quit."""
    app = NSApplication.sharedApplication()

    delegate = _Delegate.alloc().init()
    delegate._port = port
    delegate._shutdown_cb = server_should_exit_cb
    app.setDelegate_(delegate)

    # ── Status bar icon ───────────────────────────────────────────────
    status_item = (
        NSStatusBar.systemStatusBar()
        .statusItemWithLength_(NSVariableStatusItemLength)
    )
    status_item.button().setToolTip_("Zopedia")

    icon = _load_icon()
    if icon:
        status_item.button().setImage_(icon)
        status_item.button().setImagePosition_(0)  # NSImageOnly
    else:
        status_item.button().setTitle_("Z")

    # ── Menu ──────────────────────────────────────────────────────────
    menu = NSMenu.alloc().initWithTitle_("Zopedia")

    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Open in Browser", "openBrowser:", ""
    )
    item.setTarget_(delegate)
    menu.addItem_(item)

    menu.addItem_(NSMenuItem.separatorItem())

    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Quit Zopedia", "quitApp:", "q"
    )
    item.setTarget_(delegate)
    menu.addItem_(item)

    status_item.setMenu_(menu)

    app.run()
