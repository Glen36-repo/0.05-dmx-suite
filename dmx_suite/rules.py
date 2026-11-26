"""Rule layer: turns the show's Look plus the control state into DMX frames.

Sits just before output, so no look can break the rules (CLAUDE.md; profiles in profile.py).

Safety rules, always on:
4. No background glow: every frame starts at zero; a fixture not lit gets 0 on every emitter
   and dimmer. Non-light channels (gobo, wheel, strobe, mode) sit at their defaults.
5. Haze channel comes only from the haze controller.
6. Grand/sub-masters scale intensity only (dimmer, or RGB when there's no dimmer).
8. Pan/tilt clamped to the rig's head limits.
Strobe rate limit: the rig's whole light output may jump (a flash) at most `strobe_limit_hz` times
   a second (default 3). A flash is a rise of FLASH_STEP of the rig's output from the darkest
   point since the last flash, whatever caused it (drum hits, flash effects, busking). A flash
   that comes too soon is held: the lights that got brighter keep last frame's light until the
   limit allows it. Light moving around the rig (chases) without a rig-wide jump isn't a flash.

Profile rules, per the rig's profile:
1. `master_gate`: MASTER owns on/off; dimmers are written here only and any `intensity` in the
   look is ignored. Without it, a fixture lights when its look does, at the look's intensity.
2. `drum_flash`: MASTER off -> rig dark except drum flashes (immediate send is the engine's job).
3. `master_exempt`: those fixtures ignore MASTER (and drum flashes).

Fixture definition:
7. Colour-only heads stay at home position; pan/tilt speed: 1.0 = fastest = DMX 0 when inverted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .faders import Masters
from .fixtures import DMX_CHANNELS, EMITTERS, Fixture, Kind
from .look import Colour, FixtureLook, Look
from .rig import Rig


@dataclass
class Flash:
    colour: Colour
    level: float  # 0..1 from velocity
    until: float  # clock time the flash ends


@dataclass
class ControlState:
    master: bool
    blackout: bool
    flashes: dict[str, Flash]
    haze_level: float
    now: float = 0.0  # clock time of this frame (strobe limit)


FLASH_STEP = 0.25  # rise in the rig's light output (0-1) that counts as a flash


@dataclass
class _Light:
    """Where a fixture's light lives in the frame, for measuring output (strobe limit)."""

    universe: int
    dimmer: list[int]
    pixels: list[list[int]]  # emitter slots per pixel (one group for single-cell fixtures)
    slots: list[int] = field(default_factory=list)  # every emitter and dimmer slot

    def level(self, frame: bytearray) -> float:
        cells = [max((frame[s] for s in px), default=255) / 255 for px in self.pixels] or [1.0]
        lvl = sum(cells) / len(cells)
        if self.dimmer:
            lvl *= max(frame[s] for s in self.dimmer) / 255
        return lvl


def _byte(v: float) -> int:
    return max(0, min(255, round(v * 255)))


class RuleLayer:
    def __init__(self, rig: Rig) -> None:
        self.rig = rig
        # last commanded position per head; heads hold position when the look doesn't move them
        self.position: dict[str, tuple[float, float]] = {
            f.id: (f.type.home["pan"], f.type.home["tilt"]) for f in rig.fixtures
        }
        # strobe limit: where each light is, what it sent last frame, and the flash history
        self._lights: dict[str, _Light] = {}
        for f in rig.fixtures:
            lt = self._light(f)
            if lt is not None:
                self._lights[f.id] = lt
        self._last: dict[str, tuple[float, list[int]]] = {}  # fixture -> (level, intensity bytes)
        self._low = 0.0  # darkest rig output since the last flash
        self._last_flash = -math.inf
        self.held = 0  # frames where a flash was held back (status)

    @staticmethod
    def _light(fx: Fixture) -> _Light | None:
        chans = fx.type.channels
        dimmer = [fx.slot(c) for c in chans if c.role == "dimmer"]
        groups: dict[int | None, list[int]] = {}
        for c in chans:
            if c.role in EMITTERS:
                groups.setdefault(c.pixel, []).append(fx.slot(c))
        if not dimmer and not groups:
            return None  # haze, or no light of its own
        pixels = [groups[k] for k in sorted(groups, key=lambda k: -1 if k is None else k)]
        return _Light(fx.universe, dimmer, pixels, sorted(dimmer + [s for g in pixels for s in g]))

    def render(self, look: Look, state: ControlState, masters: Masters) -> dict[int, bytearray]:
        frames = {u: bytearray(DMX_CHANNELS) for u in self.rig.universes}
        for fx in self.rig.fixtures:
            self._fixture(fx, look.fixtures.get(fx.id), state, masters, frames[fx.universe])
        self._strobe_limit(frames, state.now)
        return frames

    # ------------------------------------------------------------------ strobe rate limit (safety)

    def _strobe_limit(self, frames: dict[int, bytearray], now: float) -> None:
        if not self._lights:
            return
        levels = {fid: lt.level(frames[lt.universe]) for fid, lt in self._lights.items()}
        rig_level = sum(levels.values()) / len(levels)
        limit = self.rig.strobe_limit_hz
        if rig_level - self._low >= FLASH_STEP:
            if limit is not None and now - self._last_flash < 1.0 / limit:
                self.held += 1  # too soon: lights that got brighter keep last frame's light
                for fid, lt in self._lights.items():
                    prev_level, prev_bytes = self._last.get(fid, (0.0, [0] * len(lt.slots)))
                    if levels[fid] > prev_level:
                        frame = frames[lt.universe]
                        for s, v in zip(lt.slots, prev_bytes):
                            frame[s] = v
                        levels[fid] = prev_level
                rig_level = sum(levels.values()) / len(levels)
            else:
                self._last_flash = now
                self._low = rig_level
        self._low = min(self._low, rig_level)
        for fid, lt in self._lights.items():
            frame = frames[lt.universe]
            self._last[fid] = (levels[fid], [frame[s] for s in lt.slots])

    # ------------------------------------------------------------------ per fixture

    def _fixture(self, fx: Fixture, fl: FixtureLook | None, st: ControlState, masters: Masters, frame: bytearray) -> None:
        t = fx.type
        for ch in t.channels:  # defaults for non-light channels; emitters/dimmer stay 0 (rule 4)
            if ch.role not in EMITTERS and ch.role not in ("dimmer", "haze"):
                frame[fx.slot(ch)] = ch.default

        if t.kind == Kind.HAZE:  # rule 5: only the haze controller
            for ch in t.channels:
                if ch.role == "haze":
                    frame[fx.slot(ch)] = _byte(st.haze_level)
            return

        self._position(fx, fl, frame)

        # decide what (if anything) lights this fixture
        prof = self.rig.profile
        scale = masters.level(t.kind)  # rule 6
        colour: Colour | None = None
        pixels: list[Colour] | None = None
        use_look = False
        if st.blackout:
            pass
        elif fx.id in self.rig.exempt:  # rule 3: MASTER doesn't touch exempt fixtures (kick light)
            colour = fl.colour if fl and fl.colour else self.rig.kick_colour
            pixels = fl.pixels if fl else None
            use_look = fl is not None
        elif prof.drum_flash and not st.master and fx.id in st.flashes:  # rule 2: only with MASTER off
            fls = st.flashes[fx.id]
            colour = fls.colour
            scale *= fls.level * masters.flash.value
        elif not prof.master_gate:  # no MASTER on/off: the look decides, at its intensity
            if fl is not None and fl.is_on():
                colour, pixels, use_look = fl.colour, fl.pixels, True
                if fl.intensity is not None:
                    scale *= fl.intensity
        elif st.master and fl is not None and fl.is_on():  # rule 1: MASTER owns on/off
            colour, pixels, use_look = fl.colour, fl.pixels, True

        if colour is None and pixels is None:
            return  # dark: emitters and dimmer stay 0 (rule 4)

        has_dimmer = t.has_dimmer
        emit_scale = 1.0 if has_dimmer else scale
        for ch in t.channels:
            slot = fx.slot(ch)
            if ch.role == "dimmer":
                frame[slot] = _byte(scale)
            elif ch.role in EMITTERS:
                src = colour or {}
                if ch.pixel is not None and pixels:
                    src = pixels[ch.pixel] if ch.pixel < len(pixels) else {}
                frame[slot] = _byte(src.get(ch.role, 0.0) * emit_scale)
            elif use_look and fl is not None:
                if ch.role == "colour_wheel" and fl.colour_wheel is not None:
                    frame[slot] = fl.colour_wheel
                elif ch.role == "gobo" and fl.gobo is not None:
                    frame[slot] = fl.gobo
                elif ch.role == "strobe" and fl.strobe is not None:
                    frame[slot] = fl.strobe

    def _position(self, fx: Fixture, fl: FixtureLook | None, frame: bytearray) -> None:
        t = fx.type
        if not (t.has("pan") or t.has("tilt") or t.has("pt_speed")):
            return
        if t.colour_only:  # rule 7: U'King heads never move
            pan, tilt = t.home["pan"], t.home["tilt"]
        else:
            pan, tilt = self.position.get(fx.id, (t.home["pan"], t.home["tilt"]))
            if fl is not None:
                pan = fl.pan if fl.pan is not None else pan
                tilt = fl.tilt if fl.tilt is not None else tilt
            lim = self.rig.limit(fx.id)  # rule 8
            pan, tilt = lim.clamp("pan", pan), lim.clamp("tilt", tilt)
            self.position[fx.id] = (pan, tilt)
        speed = fl.speed if (fl is not None and fl.speed is not None and not t.colour_only) else 1.0
        fine = {"pan": t.has("pan_fine"), "tilt": t.has("tilt_fine")}
        for ch in t.channels:
            slot = fx.slot(ch)
            if ch.role in ("pan", "tilt"):
                v = pan if ch.role == "pan" else tilt
                frame[slot] = (round(v * 65535) >> 8) if fine[ch.role] else _byte(v)
            elif ch.role in ("pan_fine", "tilt_fine"):
                v = pan if ch.role == "pan_fine" else tilt
                frame[slot] = round(v * 65535) & 0xFF
            elif ch.role == "pt_speed":  # rule 7: MHL36 0 = fastest (invert: true)
                frame[slot] = _byte(1.0 - speed) if ch.invert else _byte(speed)
