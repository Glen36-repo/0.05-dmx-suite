"""Haze controls: off / manual / pulse, plus boost. Separate from scenes, shows, MASTER and the
grand master (rule 5). Safety: max continuous on-time, boost cooldown, auto-off timer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .rig import HazeConfig


class HazeMode(str, Enum):
    OFF = "off"
    MANUAL = "manual"
    PULSE = "pulse"


@dataclass
class HazeStatus:
    enabled: bool
    mode: HazeMode
    output_on: bool
    level: float
    boosting: bool
    resting: bool  # forced off by the max on-time limit
    auto_off_in_s: float | None
    next_pulse_in_s: float | None
    boost_cooldown_s: float  # 0 = boost available
    testing: str | None = None  # v4: a one-cycle test running (manual / pulse / boost)
    preset: str | None = None  # v4: the haze preset last picked


class Haze:
    def __init__(self, cfg: HazeConfig, now: float) -> None:
        self.cfg = cfg
        self.mode = HazeMode.OFF
        self._mode_since = now
        self._boost_until: float | None = None  # inf while held
        self._boost_end = -1e9
        self._on_since: float | None = None
        self._rest_until = -1e9
        self._out = 0.0
        self._test: tuple[str, float, float, float] | None = None  # (mode, start, end, level)
        self.preset: str | None = None
        self.set_mode(HazeMode(cfg.default_mode) if cfg.enabled else HazeMode.OFF, now)

    def reconfigure(self, cfg: HazeConfig, now: float) -> None:
        """New settings (Haze settings panel, a reload) without losing the mode the band picked."""
        self.cfg = cfg
        if not cfg.enabled:
            self.stop(now)

    # ------------------------------------------------------------------ v4: presets and test

    def apply_preset(self, name: str, now: float) -> None:
        """A named preset (e.g. Haze 4 Med = manual 41 %): its level and mode, until the next change."""
        p = next((x for x in self.cfg.presets if x["name"] == name), None)
        if p is None:
            raise ValueError(f"no haze preset {name!r}; have {', '.join(x['name'] for x in self.cfg.presets) or 'none'}")
        self.cfg = replace(self.cfg, level=p["level"]) if p["mode"] != "pulse" else replace(self.cfg, pulse_level=p["level"])
        self.preset = name
        self.set_mode(p["mode"], now)

    def test(self, mode: str, now: float) -> float:
        """Run one cycle of a mode now (manual: 3 s; pulse: one pulse; boost: its time or 3 s), on top of
        whatever is set; max-on and rest still apply. Returns how long it runs."""
        c = self.cfg
        if not c.enabled:
            raise ValueError("haze is disabled in this rig")
        if mode == "manual":
            span, level = min(3.0, c.max_on_s), c.level
        elif mode == "pulse":
            span, level = c.pulse_on_s, self.pulse_level
        elif mode == "boost":
            span, level = (c.boost_s or 3.0), c.boost_level
        else:
            raise ValueError("test manual, pulse or boost")
        self._test = (mode, now, now + span, level)
        return span

    @property
    def pulse_level(self) -> float:
        return self.cfg.level if self.cfg.pulse_level is None else self.cfg.pulse_level

    # ------------------------------------------------------------------ controls

    def set_mode(self, mode: HazeMode | str, now: float) -> None:
        mode = HazeMode(mode)
        if not self.cfg.enabled:
            mode = HazeMode.OFF
        self.mode = mode
        self._mode_since = now

    def toggle_manual(self, now: float) -> None:
        self.set_mode(HazeMode.OFF if self.mode == HazeMode.MANUAL else HazeMode.MANUAL, now)

    def boost_press(self, now: float) -> bool:
        """Footswitch down. Returns False if refused (disabled or cooling down)."""
        if not self.cfg.enabled or self._boost_until is not None:
            return False
        if now - self._boost_end < self.cfg.boost_cooldown_s:
            return False
        self._boost_until = now + self.cfg.boost_s if self.cfg.boost_s > 0 else float("inf")
        return True

    def boost_release(self, now: float) -> None:
        """Footswitch up. Ends a held boost; a timed boost runs its time."""
        if self._boost_until == float("inf"):
            self._end_boost(now)

    def _end_boost(self, now: float) -> None:
        self._boost_until = None
        self._boost_end = now

    def stop(self, now: float) -> None:
        """Everything off now."""
        self.set_mode(HazeMode.OFF, now)
        if self._boost_until is not None:
            self._end_boost(now)

    # ------------------------------------------------------------------ output

    def tick(self, now: float) -> float:
        """Output level 0..1 for the haze channel."""
        c = self.cfg
        if not c.enabled:
            self._out = 0.0
            self._on_since = None
            return 0.0
        if self._boost_until is not None and now >= self._boost_until:
            self._end_boost(now)
        if c.auto_off_s and self.mode != HazeMode.OFF and now - self._mode_since >= c.auto_off_s:
            self.set_mode(HazeMode.OFF, now)

        want = 0.0
        if self._boost_until is not None:
            want = c.boost_level
        elif self.mode == HazeMode.MANUAL:
            want = c.level
        elif self.mode == HazeMode.PULSE and (now - self._mode_since) % c.pulse_every_s < c.pulse_on_s:
            want = self.pulse_level
        if self._test is not None:
            if now >= self._test[2]:
                self._test = None
            else:
                want = max(want, self._test[3])

        # safety: max continuous on-time, then a forced rest
        if now < self._rest_until:
            want = 0.0
        if want > 0:
            if self._on_since is None:
                self._on_since = now
            elif now - self._on_since >= c.max_on_s:
                self._rest_until = now + c.rest_s
                if self._boost_until is not None:
                    self._end_boost(now)
                want = 0.0
        if want == 0:
            self._on_since = None
        self._out = want
        return want

    def status(self, now: float) -> HazeStatus:
        c = self.cfg
        auto = None
        if c.auto_off_s and self.mode != HazeMode.OFF:
            auto = max(0.0, c.auto_off_s - (now - self._mode_since))
        nxt = None
        if self.mode == HazeMode.PULSE:
            phase = (now - self._mode_since) % c.pulse_every_s
            nxt = 0.0 if phase < c.pulse_on_s else c.pulse_every_s - phase
        cool = 0.0
        if self._boost_until is None:
            cool = max(0.0, c.boost_cooldown_s - (now - self._boost_end))
        return HazeStatus(
            enabled=c.enabled,
            mode=self.mode,
            output_on=self._out > 0,
            level=self._out,
            boosting=self._boost_until is not None,
            resting=now < self._rest_until,
            auto_off_in_s=auto,
            next_pulse_in_s=nxt,
            boost_cooldown_s=cool,
            testing=self._test[0] if self._test is not None and now < self._test[2] else None,
            preset=self.preset,
        )
