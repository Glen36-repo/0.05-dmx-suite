"""Desktop app: the lighting UI in its own window, with a tray icon.

The window shows the same screens as the browser UI (Windows' built-in WebView2 via pywebview), so
phones on the network still work alongside it. Closing the window hides it to the tray and the
lights keep running; Quit is in the tray menu. Opening the app again while it's running brings up
another window on the running engine instead of starting a second one.
"""

from __future__ import annotations

import argparse
import html
import logging
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

import yaml

from .fixtures import ConfigError

TITLE = "0.05 DMX Suite"
ICON = Path(__file__).parent / "web" / "static" / "brand" / "icon.png"
WINDOW = {"width": 1280, "height": 820, "min_size": (960, 600), "background_color": "#121218"}

log = logging.getLogger(__name__)


def ui_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def running_ui(port: int, timeout: float = 1.0) -> bool:
    """True if this app's UI is already being served on the port (the app is already open)."""
    try:
        with urllib.request.urlopen(ui_url(port), timeout=timeout) as r:
            return r.status == 200 and f"<title>{TITLE}</title>".encode() in r.read(4096)
    except (OSError, ValueError):
        return False


def error_page(title: str, detail: str) -> str:
    return f"""<!doctype html><meta charset="utf-8"><title>{TITLE}</title>
<body style="background:#121218;color:#d8d8e0;font:15px system-ui,sans-serif;padding:32px;line-height:1.5">
<h2 style="margin-top:0">{html.escape(title)}</h2>
<pre style="white-space:pre-wrap;background:#1c1c26;padding:16px;border-radius:8px">{html.escape(detail)}</pre>
<p>Fix the show files (Start menu &rarr; <b>Check show files</b> lists every problem), then open the app again.</p>
</body>"""


def log_to_file(log_dir: Path) -> Path | None:
    """The windowed app has no console: send prints and errors to logs/desktop.log."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "desktop.log"
        f = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives for the whole app
    except OSError:
        return None
    f.write(f"\n--- {time.strftime('%d/%m/%Y %H:%M:%S')} start\n")
    sys.stdout = sys.stderr = f
    logging.basicConfig(stream=f, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return path


def make_tray(on_open: Callable[[], None], on_blackout: Callable[[], None], is_blackout: Callable[[], bool],
              on_quit: Callable[[], None]) -> Any | None:
    """Tray icon with Open / Blackout / Quit. None if pystray isn't available."""
    try:
        import pystray
        from PIL import Image
    except Exception:  # noqa: BLE001 - tray is optional (e.g. Linux without an indicator)
        return None
    try:
        image = Image.open(ICON)
    except OSError:
        image = Image.new("RGB", (64, 64), "#121218")
    menu = pystray.Menu(
        pystray.MenuItem("Open", lambda: on_open(), default=True),
        pystray.MenuItem("Blackout", lambda: on_blackout(), checked=lambda _: is_blackout()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit (lights off)", lambda: on_quit()),
    )
    return pystray.Icon("dmx-suite", image, TITLE, menu)


class Desktop:
    """Owns the window, the tray and (unless another copy is running) the engine session."""

    def __init__(self, args: argparse.Namespace, webview: Any, start_session: Callable[..., Any]) -> None:
        self.args = args
        self.webview = webview
        self.start_session = start_session
        self.session: Any = None
        self.window: Any = None
        self.tray: Any = None
        self.quitting = False
        self.told_tray = False

    # ------------------------------------------------------------------ actions

    def open(self) -> None:
        self.window.show()
        self.window.restore()

    def blackout(self) -> None:
        self.session.engine.toggle_blackout()

    def is_blackout(self) -> bool:
        return bool(self.session and self.session.engine.blackout)

    def quit(self) -> None:
        self.quitting = True
        self.window.destroy()

    def on_closing(self) -> bool:
        """Close button: hide to the tray (lights keep running). Returns False to cancel the close."""
        if self.quitting or self.session is None:
            return True
        if self.tray is None:  # no tray: ask instead
            return bool(self.window.create_confirmation_dialog("Quit", "Stop the lights and quit 0.05 DMX Suite?"))
        self.window.hide()
        if not self.told_tray:
            self.told_tray = True
            try:
                self.tray.notify("Still running. Open or quit from the tray icon.", TITLE)
            except Exception:  # noqa: BLE001
                pass
        return False

    # ------------------------------------------------------------------ run

    def create(self) -> int:
        """Set up the window (and engine). Returns the exit code to use after the window closes."""
        port = self.args.port
        if running_ui(port):  # already open: another window on the running engine
            self.window = self.webview.create_window(TITLE, ui_url(port), **WINDOW)
            return 0
        try:
            self.session = self.start_session(self.args)
        except (ConfigError, yaml.YAMLError) as e:
            self.window = self.webview.create_window(TITLE, html=error_page("Show file problem", str(e)), **WINDOW)
            return 2
        except Exception as e:  # noqa: BLE001 - e.g. the UI port is taken by something else
            log.exception("start-up failed")
            self.window = self.webview.create_window(TITLE, html=error_page("Couldn't start", str(e)), **WINDOW)
            return 1
        self.window = self.webview.create_window(TITLE, ui_url(self.session.web.port), **WINDOW)
        self.window.events.closing += self.on_closing
        self.tray = make_tray(self.open, self.blackout, self.is_blackout, self.quit)
        return 0

    def smoke(self, seconds: float) -> None:
        """Build check: wait for the page, record its title, quit."""
        time.sleep(seconds)
        try:
            title = self.window.evaluate_js("document.title")
        except Exception as e:  # noqa: BLE001
            title = f"error: {e}"
        print(f"smoke test: window title {title!r}", flush=True)
        self.smoke_ok = title == TITLE
        self.quit()

    def run(self) -> int:
        code = self.create()
        if self.tray is not None:
            self.tray.run_detached()
        smoke = getattr(self.args, "smoke_test", None)
        self.smoke_ok = smoke is None
        # Windows takes the window icon from the exe (its icon parameter only accepts .ico)
        kw = {} if sys.platform == "win32" else {"icon": str(ICON)}
        try:
            if smoke is not None:
                self.webview.start(lambda: self.smoke(smoke), **kw)
            else:
                self.webview.start(**kw)
        finally:
            if self.tray is not None:
                self.tray.stop()
            if self.session is not None:
                self.session.stop()
        return code if self.smoke_ok else 3


def run_desktop(args: argparse.Namespace) -> int:
    from .cli import start_session

    if getattr(sys, "frozen", False) or sys.stdout is None:
        log_to_file(args.shows.parent / "logs")
    try:
        import webview
    except ImportError:
        print("the desktop app needs pywebview: pip install -e .[desktop]", file=sys.stderr)
        return 1
    return Desktop(args, webview, start_session).run()


def main(argv: list[str] | None = None) -> int:
    """Entry point for the windowed exe: opens the app (live) unless another command is given."""
    from .cli import main as cli_main

    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"app", "run", "check", "midi-ports", "midi-monitor", "mcp", "claude-setup", "addresses", "import-ofl"}
    if not any(a in commands for a in argv):
        # global options (--shows X) go before the command, the rest (e.g. --sim) after it
        head = argv[:2] if argv[:1] == ["--shows"] else [a for a in argv[:1] if a.startswith("--shows=")]
        argv = head + ["app"] + argv[len(head):]
    return cli_main(argv)

