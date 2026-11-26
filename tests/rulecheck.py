"""Rule check for every v3 feature: run something under both shipped profiles and check the rules
on every frame it makes.

    from rulecheck import rule_matrix

    def test_named_inputs_keep_the_rules():
        rule_matrix(lambda e, clock: ...do the feature..., seconds=3)

Checked on each frame (40 Hz over `seconds`):
- rule 5: the haze channel never moves unless the action uses the Haze controls (haze=True)
- rule 8: every head's pan/tilt stays inside its head limits
- rule 7: colour-only heads keep their home pan/tilt (never moved)
Then, at the end:
- rule 6: grand master at 30 % changes no pan/tilt, wheel or gobo value and leaves haze alone
- rule 1 (profiles with MASTER on/off): MASTER off leaves every light dark but the exempt ones
- rule 3: MASTER never changes an exempt (kick) light
- rule 4: a light the look doesn't use stays fully off (`unused` fixture ids)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dmx_suite.engine import Engine
from dmx_suite.fixtures import EMITTERS, parse_patch
from dmx_suite.look import parse_look
from dmx_suite.output import LogDriver
from dmx_suite.rig import parse_rig

from conftest import LOOK, PATCH, RIG, Clock, View

PROFILES = ("0.05_band", "generic")
POSITION_ROLES = ("pan", "pan_fine", "tilt", "tilt_fine", "gobo", "colour_wheel")


def build(profile: str, rig: dict[str, Any] | None = None, look: dict[str, Any] | None = None,
          patch: dict[str, Any] | None = None) -> tuple[Engine, View, Clock]:
    p = parse_patch(patch or PATCH)
    r = parse_rig({**RIG, **(rig or {}), "profile": profile}, p)
    clock = Clock()
    e = Engine(r, [LogDriver()], parse_look(look if look is not None else LOOK, p), clock=clock)
    e.tick()
    return e, View(e), clock


def _value(e: Engine, fid: str, role: str) -> int | None:
    fx = e.rig.patch.fixtures[fid]
    for ch in fx.type.channels:
        if ch.role == role:
            return e.frames[fx.universe][fx.slot(ch)]
    return None


def _axis(e: Engine, fid: str, role: str) -> float | None:
    c = _value(e, fid, role)
    if c is None:
        return None
    f = _value(e, fid, role + "_fine")
    return ((c << 8) | f) / 65535 if f is not None else c / 255


def _emitters(e: Engine, fid: str) -> list[int]:
    fx = e.rig.patch.fixtures[fid]
    return [e.frames[fx.universe][fx.slot(c)] for c in fx.type.channels if c.role in EMITTERS or c.role == "dimmer"]


def _haze(e: Engine) -> list[int]:
    return [e.frames[u][c] for u, c in sorted(e.haze_slots())]


def check_frame(e: Engine, haze_before: list[int] | None, where: str) -> None:
    rig = e.rig
    for fx in rig.fixtures:
        if not fx.type.has("pan"):
            continue
        pan, tilt = _axis(e, fx.id, "pan"), _axis(e, fx.id, "tilt")
        if fx.type.colour_only:
            continue
        lim = rig.limit(fx.id)
        tol = 1 / 255  # 8-bit rounding
        assert pan is not None and lim.pan[0] - tol <= pan <= lim.pan[1] + tol, f"{where}: {fx.id} pan {pan} (rule 8)"
        assert tilt is not None and lim.tilt[0] - tol <= tilt <= lim.tilt[1] + tol, f"{where}: {fx.id} tilt {tilt} (rule 8)"
    if haze_before is not None:
        assert _haze(e) == haze_before, f"{where}: haze channel changed (rule 5)"


def rule_matrix(action: Callable[[Engine, Clock], Any], seconds: float = 2.0, haze: bool = False,
                unused: tuple[str, ...] = (), rig: dict[str, Any] | None = None, look: dict[str, Any] | None = None,
                profiles: tuple[str, ...] = PROFILES, after: Callable[[Engine, Clock], Any] | None = None) -> None:
    """Run `action(engine, clock)` under each profile, then tick for `seconds`, checking the rules.
    `after(engine, clock)` runs after the ticks (e.g. to check what the feature did)."""
    for prof in profiles:
        e, _view, clock = build(prof, rig, look)
        haze0 = None if haze else _haze(e)
        action(e, clock)
        e.tick()
        steps = max(1, int(seconds * 40))
        for n in range(steps):
            clock.advance(1 / 40)
            e.tick()
            check_frame(e, haze0, f"{prof} t={n / 40:.3f}")
        for fid in unused:
            assert _emitters(e, fid) == [0] * len(_emitters(e, fid)), f"{prof}: {fid} glows (rule 4)"
        # rule 6: grand master scales intensity only
        before = {fx.id: [_value(e, fx.id, r) for r in POSITION_ROLES] for fx in e.rig.fixtures}
        haze_now = _haze(e)
        e.set_grand(0.3, instant=True)
        e.tick()
        after_gm = {fx.id: [_value(e, fx.id, r) for r in POSITION_ROLES] for fx in e.rig.fixtures}
        assert before == after_gm, f"{prof}: grand master moved a head, wheel or gobo (rule 6)"
        if not haze:
            assert _haze(e) == haze_now, f"{prof}: grand master changed haze (rule 6)"
        e.set_grand(1.0, instant=True)
        e.tick()
        # rules 1 and 3: MASTER owns on/off, the exempt lights ignore it
        if e.rig.profile.master_gate and not e.blackout:
            exempt_on = {f: _emitters(e, f) for f in e.rig.exempt}
            e.set_master(False)
            e.tick()
            for fx in e.rig.fixtures:
                if fx.id in e.rig.exempt or fx.kind.value == "haze":
                    continue
                assert _emitters(e, fx.id) == [0] * len(_emitters(e, fx.id)), f"{prof}: {fx.id} lit with MASTER off (rule 1)"
            e.tick()
            assert {f: _emitters(e, f) for f in e.rig.exempt} == exempt_on, f"{prof}: MASTER changed an exempt light (rule 3)"
            e.set_master(True)
            e.tick()
        if after is not None:
            after(e, clock)
