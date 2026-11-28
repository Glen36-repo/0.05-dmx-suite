"""Update check: asks the release page which version is newest and says if this one is older.

Check only: nothing is downloaded or installed; the user decides. Nothing is sent but the
request itself (no telemetry). Runs only when asked (`dmx-suite update-check`, the UI button).
The address can be changed with DMX_SUITE_UPDATE_URL (a GitHub "latest release" API address).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from . import __version__

RELEASES_URL = "https://api.github.com/repos/Glen36-repo/0.05-dmx-suite/releases/latest"
URL_ENV = "DMX_SUITE_UPDATE_URL"


def parse_version(v: str) -> tuple[int, ...]:
    """'v1.2.3' / '1.2.3-beta' -> (1, 2, 3)."""
    m = re.match(r"v?(\d+(?:\.\d+)*)", v.strip())
    if not m:
        raise ValueError(f"not a version: {v!r}")
    return tuple(int(x) for x in m.group(1).split("."))


def check(current: str = __version__, url: str | None = None, timeout: float = 5.0) -> dict[str, Any]:
    url = url or os.environ.get(URL_ENV) or RELEASES_URL
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "0.05-DMX-Suite-update-check"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        latest = str(data["tag_name"])
        newer = parse_version(latest) > parse_version(current)
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
        return {"ok": False, "current": current, "message": f"couldn't check for updates ({e})"}
    page = data.get("html_url") or ""
    msg = f"{latest} is available (you have {current})" if newer else f"up to date ({current})"
    return {"ok": True, "current": current, "latest": latest, "newer": newer, "url": page, "message": msg}
