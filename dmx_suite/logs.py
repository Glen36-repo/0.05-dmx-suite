"""Log file: everything at INFO and above goes to `<app data>/logs/dmx-suite.log` (1 MB, 5 old
files kept), so a problem at a gig can be looked at afterwards. Warnings also go to the console."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from .paths import log_dir

FILE = "dmx-suite.log"
_done = False


def setup(console_level: int = logging.WARNING) -> Path | None:
    """Call once at start-up. Returns the log file (None if it can't be written)."""
    global _done
    root = logging.getLogger()
    if _done:
        return None
    _done = True
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(console)
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / FILE
        fh = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    except OSError:
        return None
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    root.addHandler(fh)
    return path
