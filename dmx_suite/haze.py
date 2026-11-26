"""Haze controls: off / manual / pulse, plus boost. Separate from scenes, shows, MASTER and the
grand master (rule 5). Safety: max continuous on-time, boost cooldown, auto-off timer.
"""

from __future__ import annotations

from dataclasses import dataclass
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
        self.set_mode(HazeMode(cfg.default_mode) if cfg.enabled else HazeMode.OFF, now)

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
            want = c.level

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
        )
