"""Grand master and sub-masters: smooth fades towards a target, no steps."""

from __future__ import annotations

from .fixtures import Kind


class Fader:
    def __init__(self, value: float, fade_s: float = 0.3) -> None:
        self.value = self.target = _clip(value)
        self.fade_s = fade_s

    def set(self, target: float, instant: bool = False) -> None:
        self.target = _clip(target)
        if instant or self.fade_s <= 0:
            self.value = self.target

    def tick(self, dt: float) -> None:
        if self.value == self.target:
            return
        step = dt / self.fade_s if self.fade_s > 0 else 1.0
        if abs(self.target - self.value) <= step:
            self.value = self.target
        else:
            self.value += step if self.target > self.value else -step


def _clip(v: float) -> float:
    return min(max(float(v), 0.0), 1.0)


class Masters:
    """Grand master x sub-master per fixture kind, plus the drum-flash level."""

    def __init__(self, grand: float, subs: dict[Kind, float], flash: float, fade_s: float) -> None:
        self.grand = Fader(grand, fade_s)
        self.subs = {k: Fader(subs.get(k, 1.0), fade_s) for k in Kind}
        self.flash = Fader(flash, fade_s)

    def tick(self, dt: float) -> None:
        self.grand.tick(dt)
        self.flash.tick(dt)
        for f in self.subs.values():
            f.tick(dt)

    def level(self, kind: Kind) -> float:
        """Intensity scale for a fixture kind. Haze is never scaled (rule 6)."""
        if kind == Kind.HAZE:
            return 1.0
        return self.grand.value * self.subs[kind].value
