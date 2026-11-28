"""Alerts and banners (v3.1): warnings can be cleared from the screen without losing track of them.

Every problem the status bar knows about (an output down, a MIDI input unplugged, a node offline or
weak, an engine fault) is an alert, keyed by device. Each time a device goes bad is a new
*episode*:

- a new episode shows a banner (and beeps), unless the device is muted for this rig config, the
  alert is snoozed, or quiet mode is on and it isn't critical; info alerts only go to the list
- X dismisses the banner; it stays hidden for the rest of that episode. If the device recovers
  and drops out again, that's a new episode and a new banner
- when the problem goes away the alert clears by itself
- critical alerts (engine fault, a DMX output down, every output lost) can be minimised to the
  red status-bar light but not dismissed while the fault lasts
- mutes ("not using this today") hold for the rig config they were set on and are dropped when
  the rig changes; they're kept in app data (alerts.json) so a restart keeps them
- every change goes to the alerts log (logs/alerts-YYYY-MM-DD.jsonl in app data)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SNOOZES = {"10min": 600.0, "1h": 3600.0, "gig": float("inf")}
SEVERITIES = ("info", "warning", "critical")


@dataclass
class Alert:
    key: str  # "kind:name", one per device
    kind: str
    device: str
    message: str
    severity: str
    episode: int = 0
    state: str = "active"  # active / dismissed / minimised / snoozed / muted / cleared
    since: float = 0.0  # this episode's start
    changed: float = 0.0
    dismissed_episode: int = -1
    minimised_episode: int = -1
    snooze_until: float = 0.0
    history: list[tuple[float, str]] = field(default_factory=list)

    def view(self) -> dict[str, Any]:
        return {"id": self.key, "kind": self.kind, "device": self.device, "message": self.message,
                "severity": self.severity, "state": self.state, "since": self.since, "changed": self.changed,
                "episode": self.episode, "snooze_until": None if self.snooze_until in (0.0, float("inf")) else self.snooze_until}


def classify(d: dict[str, Any]) -> str | None:
    """A status-bar device's alert severity, or None when it's fine."""
    state, kind = d.get("state"), d.get("kind")
    if state in ("ok", "sim", "idle", None):
        return None
    if kind in ("claude", "screens"):
        return None  # Claude and screens coming and going is normal
    if kind == "engine" and state == "bad":
        return "critical"
    if kind == "output" and state == "bad":
        return "critical"
    if state == "bad":
        return "warning"
    if state in ("warn", "weak"):
        return "info" if kind == "engine" else "warning"
    return "warning"


class AlertCenter:
    def __init__(self, state_file: Path | None = None, log_dir: Path | None = None,
                 clock: Callable[[], float] = time.time, rig: str = "") -> None:
        self.alerts: dict[str, Alert] = {}
        self.state_file = state_file
        self.log_dir = log_dir
        self.clock = clock
        self.quiet = False  # gig mode: only critical alerts make banners
        self.rig = rig
        self.muted: set[str] = set()
        self._lock = threading.RLock()
        self.new_banner_at = 0.0  # last time a new banner appeared (the page beeps on it)
        self._load()

    # ------------------------------------------------------------------ persistence

    def _load(self) -> None:
        if self.state_file is None or not self.state_file.exists():
            return
        try:
            d = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if d.get("rig") == self.rig:
            self.muted = {str(x) for x in d.get("muted") or []}
        self.quiet = bool(d.get("quiet", False))

    def _save(self) -> None:
        if self.state_file is None:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps({"rig": self.rig, "muted": sorted(self.muted), "quiet": self.quiet}),
                                       encoding="utf-8")
        except OSError:
            log.exception("alerts state save failed")

    def _log(self, a: Alert, what: str) -> None:
        a.history.append((self.clock(), what))
        del a.history[:-20]
        if self.log_dir is None:
            return
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            path = self.log_dir / f"alerts-{time.strftime('%Y-%m-%d')}.jsonl"
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"time": self.clock(), "device": a.device, "kind": a.kind, "severity": a.severity,
                                    "message": a.message, "event": what, "episode": a.episode}) + "\n")
        except OSError:
            log.exception("alerts log write failed")

    # ------------------------------------------------------------------ feeding

    def set_rig(self, rig: str) -> None:
        """A different rig config: mutes were for the old one."""
        with self._lock:
            if rig != self.rig:
                self.rig = rig
                self.muted.clear()
                for a in self.alerts.values():
                    if a.state == "muted":
                        a.state = "active"
                self._save()

    def update(self, devices: list[dict[str, Any]]) -> None:
        """The status bar's devices now. New problems start an episode; fixed ones clear."""
        now = self.clock()
        with self._lock:
            bad: dict[str, tuple[dict[str, Any], str]] = {}
            outputs = [d for d in devices if d.get("kind") == "output"]
            for d in devices:
                sev = classify(d)
                if sev is not None:
                    bad[f"{d.get('kind')}:{d.get('name')}"] = (d, sev)
            if outputs and all(d.get("state") == "bad" for d in outputs):
                bad["output:all"] = ({"kind": "output", "name": "All outputs", "detail": "no DMX is going out"}, "critical")
            for key, (d, sev) in bad.items():
                a = self.alerts.get(key)
                msg = str(d.get("detail") or d.get("state") or "")
                if a is None:
                    a = self.alerts[key] = Alert(key, str(d.get("kind")), str(d.get("name")), msg, sev, changed=now)
                if a.state == "cleared" or a.episode == 0:
                    a.episode += 1
                    a.since = a.changed = now
                    a.message, a.severity = msg, sev
                    a.state = self._shown_state(a, now)
                    if a.state == "active" and self._banner(a):
                        self.new_banner_at = now
                    self._log(a, "new")
                else:
                    a.message = msg
                    if sev != a.severity:
                        a.severity = sev
                        a.changed = now
                    if a.state == "snoozed" and now >= a.snooze_until:
                        a.state = "active"
                        a.changed = now
            for key, a in self.alerts.items():
                if key not in bad and a.state != "cleared":
                    a.state = "cleared"
                    a.changed = now
                    self._log(a, "cleared")

    def _shown_state(self, a: Alert, now: float) -> str:
        if a.key in self.muted and a.severity != "critical":
            return "muted"
        if a.snooze_until > now and a.severity != "critical":
            return "snoozed"
        return "active"

    def _banner(self, a: Alert) -> bool:
        """Info alerts (e.g. engine running a little slow) only go to the list."""
        if a.state != "active" or a.severity == "info":
            return False
        return not self.quiet or a.severity == "critical"

    # ------------------------------------------------------------------ actions (UI only)

    def _get(self, key: str) -> Alert:
        a = self.alerts.get(key)
        if a is None:
            raise ValueError(f"no alert {key!r}")
        return a

    def dismiss(self, key: str) -> None:
        with self._lock:
            a = self._get(key)
            if a.severity == "critical" and a.state != "cleared":
                raise ValueError("a critical alert can't be dismissed while the fault lasts: minimise it")
            if a.state == "active":
                a.state = "dismissed"
                a.dismissed_episode = a.episode
                a.changed = self.clock()
                self._log(a, "dismissed")

    def minimise(self, key: str) -> None:
        with self._lock:
            a = self._get(key)
            if a.state == "active":
                a.state = "minimised"
                a.minimised_episode = a.episode
                a.changed = self.clock()
                self._log(a, "minimised")

    def snooze(self, key: str, how: str) -> None:
        if how not in SNOOZES:
            raise ValueError(f"snooze for {', '.join(SNOOZES)}")
        with self._lock:
            a = self._get(key)
            if a.severity == "critical":
                raise ValueError("critical alerts can't be snoozed")
            a.snooze_until = self.clock() + SNOOZES[how]
            if a.state in ("active", "dismissed"):
                a.state = "snoozed"
                a.changed = self.clock()
            self._log(a, f"snoozed {how}")

    def mute(self, key: str, on: bool = True) -> None:
        """'Not using this today': no alerts for this device until unmuted or the rig changes."""
        with self._lock:
            if on:
                self.muted.add(key)
            else:
                self.muted.discard(key)
            a = self.alerts.get(key)
            if a is not None and a.severity != "critical" and a.state != "cleared":
                a.state = "muted" if on else "active"
                a.changed = self.clock()
                self._log(a, "muted" if on else "unmuted")
            self._save()

    def set_quiet(self, on: bool) -> None:
        with self._lock:
            self.quiet = bool(on)
            self._save()

    # ------------------------------------------------------------------ reading

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = self.clock()
            for a in self.alerts.values():
                if a.state == "snoozed" and now >= a.snooze_until:
                    a.state = "active"
            live = [a for a in self.alerts.values() if a.state != "cleared"]
            order = {"critical": 0, "warning": 1, "info": 2}
            banners = sorted((a for a in live if self._banner(a)), key=lambda a: (order[a.severity], -a.since))
            recent = sorted(self.alerts.values(), key=lambda a: -a.changed)[:50]
            return {
                "banners": [a.view() for a in banners],
                "count": len(live),
                "critical": any(a.severity == "critical" for a in live),
                "new_at": self.new_banner_at,
                "quiet": self.quiet,
                "muted": sorted(self.muted),
                "list": [a.view() for a in recent],
            }
