"""Test patterns (v5): DMX straight to one universe or one interface, bypassing scenes, autopilot,
Override, the grand master and MASTER, to find out whether the lights get DMX at all.

Patterns:
- `all_full`: every light at full (emitters and dimmer 255); unpatched channels 255 unless
  `patched_only`. Function channels (strobe, mode, macro, gobo, wheel) stay at their defaults, so a
  light isn't pushed into strobe, a sound program or a macro: strobe is off.
- `chase`: one light at a time at full white, `dwell_s` each (default 2 s).
- `find`: one light's colour full on / off at 1 Hz; a moving head also nods its tilt a little.
- `ramp`: one channel 0 -> 255 -> 0 (4 s), or held at `value`.
- `keep_alive`: a fixed frame (every light channel at `value`, default 0) sent continuously: do the
  lights stay in DMX mode with nothing in it? Allowed under gig lock; the others aren't.

Always: haze channels 0 (rule 5: only the Haze controls run haze, test patterns included); pan / tilt
clamped to the rig's head limits (rule 8); U'King heads never move (rule 7). The test stops on Stop,
when the Monitor page is left, or after `timeout_s` (default 60 s); the show's output carries on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .fixtures import DMX_CHANNELS, EMITTERS, Fixture, Kind
from .rig import Rig

PATTERNS = ("all_full", "chase", "find", "ramp", "keep_alive")
NAMES = {"all_full": "All full", "chase": "Fixture chase", "find": "Find fixture", "ramp": "Channel ramp",
         "keep_alive": "Keep-alive"}
TIMEOUT_S = 60.0
MAX_TIMEOUT_S = 600.0
RAMP_S = 4.0
NOD = 0.04  # tilt nod either side, 0-1 of the tilt range


@dataclass
class TestPattern:
    __test__ = False  # not a pytest test class

    pattern: str
    universe: int = 0
    output: int | None = None  # one interface only (index into the engine's drivers), else every one carrying it
    fixture: str | None = None
    channel: int | None = None  # 1-512 (ramp)
    value: int | None = None  # ramp hold / keep-alive level
    dwell_s: float = 2.0
    timeout_s: float = TIMEOUT_S
    patched_only: bool = False
    started: float = 0.0
    by: str = "ui"
    note: str = ""  # what's lit now (chase: the fixture), for the big label
    extra: dict[str, Any] = field(default_factory=dict)

    def until(self) -> float:
        return self.started + self.timeout_s

    def view(self, now: float) -> dict[str, Any]:
        return {"pattern": self.pattern, "name": NAMES[self.pattern], "universe": self.universe, "output": self.output,
                "fixture": self.fixture, "channel": self.channel, "value": self.value, "dwell_s": self.dwell_s,
                "patched_only": self.patched_only, "now": self.note, "by": self.by,
                "left_s": round(max(0.0, self.until() - now), 1), "timeout_s": self.timeout_s}


def check(rig: Rig, tp: TestPattern, haze: set[tuple[int, int]]) -> TestPattern:
    """Validate a request against the rig; raises ValueError with a plain reason."""
    if tp.pattern not in PATTERNS:
        raise ValueError(f"pattern: one of {', '.join(PATTERNS)}")
    if not 0 <= tp.universe <= 15:
        raise ValueError("universe 0-15")
    if not 0 < tp.timeout_s <= MAX_TIMEOUT_S:
        raise ValueError(f"timeout_s: 1-{MAX_TIMEOUT_S:.0f}")
    if not 0.2 <= tp.dwell_s <= 30:
        raise ValueError("dwell_s: 0.2-30")
    if tp.value is not None and not 0 <= tp.value <= 255:
        raise ValueError("value 0-255")
    if tp.pattern == "find":
        if not tp.fixture or tp.fixture not in rig.present:
            raise ValueError("find needs a fixture in this rig")
        fx = rig.patch.fixtures[tp.fixture]
        if fx.type.kind == Kind.HAZE:
            raise ValueError("haze is only run from the Haze controls (rule 5)")
        tp.universe = fx.universe
    if tp.pattern == "ramp":
        if tp.channel is None and tp.fixture and tp.extra.get("role"):
            rf = rig.patch.fixtures.get(tp.fixture)
            if rf is None or tp.fixture not in rig.present:
                raise ValueError(f"{tp.fixture} is not in this rig")
            fx = rf
            ch = next((c for c in fx.type.channels if c.role == tp.extra["role"]), None)
            if ch is None:
                raise ValueError(f"{tp.fixture} has no {tp.extra['role']} channel")
            tp.channel, tp.universe = fx.slot(ch) + 1, fx.universe
        if tp.channel is None or not 1 <= tp.channel <= DMX_CHANNELS:
            raise ValueError("ramp needs a channel 1-512 (or a fixture and channel name)")
        if (tp.universe, tp.channel) in haze:
            raise ValueError("that's the haze channel: use the Haze controls (rule 5)")
        for fx in rig.fixtures:
            for ch in fx.type.channels:
                if fx.universe == tp.universe and fx.slot(ch) + 1 == tp.channel and ch.role.split("_")[0] in ("pan", "tilt"):
                    raise ValueError(f"ch {tp.channel} is {fx.id} {ch.role}: heads move from the Heads page, "
                                     "inside their limits (rule 8)")
    return tp


def _lights(rig: Rig, universe: int) -> list[Fixture]:
    return [f for f in rig.fixtures if f.universe == universe and f.type.kind != Kind.HAZE]


def _put(fx: Fixture, frame: bytearray, role: str, v: float) -> None:
    t = fx.type
    if t.invert(role):
        v = 1.0 - v
    fine = t.has(f"{role}_fine")
    v16 = max(0, min(65535, round(v * 65535)))
    for ch in t.channels:
        if ch.role == role:
            frame[fx.slot(ch)] = (v16 >> 8) if fine else max(0, min(255, round(v * 255)))
        elif fine and ch.role == f"{role}_fine":
            frame[fx.slot(ch)] = v16 & 0xFF


def _base(rig: Rig, universe: int, positions: dict[str, tuple[float, float]], fill: int = 0,
          patched_only: bool = True) -> bytearray:
    """Every light dark (or light channels at `fill`), function channels at defaults, heads where they are
    (inside their limits), haze 0. Unpatched channels at `fill` unless patched_only."""
    frame = bytearray([0 if patched_only else fill]) * DMX_CHANNELS
    for fx in rig.fixtures:
        if fx.universe != universe:
            continue
        for ch in fx.type.channels:
            slot = fx.slot(ch)
            if ch.role == "haze":
                frame[slot] = 0  # rule 5
            elif ch.role in EMITTERS or ch.role in ("dimmer", "dimmer_fine"):
                frame[slot] = fill
            else:
                frame[slot] = ch.default
        _head(rig, fx, frame, positions)
    return frame


def _head(rig: Rig, fx: Fixture, frame: bytearray, positions: dict[str, tuple[float, float]], nod: float = 0.0) -> None:
    t = fx.type
    if not (t.has("pan") or t.has("tilt")):
        return
    if t.colour_only:  # rule 7
        pan, tilt = t.home["pan"], t.home["tilt"]
    else:
        pan, tilt = positions.get(fx.id, (t.home["pan"], t.home["tilt"]))
        lim = rig.limit(fx.id)  # rule 8
        nodded = lim.clamp("tilt", lim.clamp("tilt", tilt) + nod)
        zone_at = getattr(rig, "zone_at", None)
        pan, tilt = lim.clamp("pan", pan), (tilt if zone_at and zone_at(fx.id, pan, nodded) else nodded)  # v7: no nod into a zone
    _put(fx, frame, "pan", pan)
    _put(fx, frame, "tilt", tilt)
    if t.has("pt_speed"):
        _put(fx, frame, "pt_speed", 1.0)  # fastest (MHL36: inverted, so DMX 0)


def _full(fx: Fixture, frame: bytearray) -> None:
    for ch in fx.type.channels:
        if ch.role in EMITTERS or ch.role in ("dimmer", "dimmer_fine"):
            frame[fx.slot(ch)] = 255


def render(rig: Rig, tp: TestPattern, positions: dict[str, tuple[float, float]], now: float) -> bytearray:
    """The test frame for tp.universe at clock time `now`."""
    t = now - tp.started
    u = tp.universe
    if tp.pattern == "all_full":
        tp.note = ""
        frame = _base(rig, u, positions, 255, tp.patched_only)
        return frame
    if tp.pattern == "keep_alive":
        v = tp.value or 0
        tp.note = f"{v}"
        return _base(rig, u, positions, v, True)
    frame = _base(rig, u, positions)
    if tp.pattern == "chase":
        lights = _lights(rig, u)
        if lights:
            fx = lights[int(t / tp.dwell_s) % len(lights)]
            _full(fx, frame)
            tp.note = fx.id
        return frame
    if tp.pattern == "find":
        fx = rig.patch.fixtures[tp.fixture or ""]
        on = (t % 1.0) < 0.5
        if on:
            _full(fx, frame)
        if not fx.type.colour_only:
            _head(rig, fx, frame, positions, NOD * math.sin(2 * math.pi * t / 2.0))
        tp.note = fx.id
        return frame
    # ramp
    ch = (tp.channel or 1) - 1
    if tp.value is not None:
        v = tp.value
    else:
        ph = (t % RAMP_S) / RAMP_S
        v = round(255 * (2 * ph if ph < 0.5 else 2 - 2 * ph))
    frame[ch] = v
    tp.note = f"ch {tp.channel} = {v}"
    return frame
