"""Rule layer: turns the show's Look plus the control state into DMX frames.

Sits just before output, so no look can break the rules (CLAUDE.md; profiles in profile.py).

Safety rules, always on:
4. No background glow: every frame starts at zero; a fixture not lit gets 0 on every emitter
   and dimmer. Non-light channels (gobo, wheel, strobe, mode) sit at their defaults.
5. Haze channel comes only from the haze controller.
6. Grand/sub-masters scale intensity only (dimmer, or RGB when there's no dimmer).
8. Pan/tilt clamped to the rig's head limits, then kept out of its exclusion zones (v7, zones.py):
   held at a zone's edge on the side the head came from, or colour off inside a `black` zone.
Profile rules, per the rig's profile:
1. `master_gate`: MASTER owns on/off; dimmers are written here only and any `intensity` in the
   look is ignored. Without it, a fixture lights when its look does, at the look's intensity.
2. `drum_flash`: MASTER off -> rig dark except drum flashes (immediate send is the engine's job).
3. `master_exempt`: those fixtures ignore MASTER (and drum flashes).

Fixture definition:
7. Colour-only heads stay at home position; pan/tilt speed: 1.0 = fastest = DMX 0 when inverted.

Colours are mixed for each fixture's emitters (colourmix.py) when its type says `colour_mix: auto`;
16-bit `<role>_fine` channels and `invert` are handled for every role that has them.
"""

from __future__ import annotations

from dataclasses import dataclass

from .colourmix import brightness, mix, nearest_slot
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
    now: float = 0.0  # clock time of this frame
    gate: float = 1.0  # MASTER on / blackout off fading the look back in (v3.4 priority release), 0-1
    gate_all: bool = False  # the fade is from a blackout: exempt lights fade in too


def _byte(v: float) -> int:
    return max(0, min(255, round(v * 255)))


def _write(fx: Fixture, frame: bytearray, role: str, v: float) -> None:
    """A continuous value 0-1 on `role` (and its `_fine` channel for 16 bits), inverted if set."""
    t = fx.type
    if t.invert(role):
        v = 1.0 - v
    fine = t.has(f"{role}_fine")
    v16 = max(0, min(65535, round(v * 65535)))
    for ch in t.channels:
        if ch.role == role:
            frame[fx.slot(ch)] = (v16 >> 8) if fine else _byte(v)
        elif fine and ch.role == f"{role}_fine":
            frame[fx.slot(ch)] = v16 & 0xFF


class RuleLayer:
    def __init__(self, rig: Rig) -> None:
        self.rig = rig
        # last commanded position per head; heads hold position when the look doesn't move them
        self.position: dict[str, tuple[float, float]] = {
            f.id: (f.type.home["pan"], f.type.home["tilt"]) for f in rig.fixtures
        }
        # v7: exclusion zones, per head (rule 8, after the limits); black-zone heads this frame; who's held
        from .zones import ZoneFollower

        self.zones = {fid: ZoneFollower(zs, rig.zone_speed) for fid, zs in rig.head_zones.items()}
        self.zone_black: set[str] = set()
        self.out_position: dict[str, tuple[float, float]] = dict(self.position)  # where heads really point (zones)
        self.now = 0.0

    def render(self, look: Look, state: ControlState, masters: Masters) -> dict[int, bytearray]:
        frames = {u: bytearray(DMX_CHANNELS) for u in self.rig.universes}
        self.now = state.now
        self.zone_black = set()
        for fx in self.rig.fixtures:
            self._fixture(fx, look.fixtures.get(fx.id), state, masters, frames[fx.universe])
        return frames

    # ------------------------------------------------------------------ per fixture

    def _fixture(self, fx: Fixture, fl: FixtureLook | None, st: ControlState, masters: Masters, frame: bytearray) -> None:
        t = fx.type
        for ch in t.channels:  # defaults for non-light channels; emitters/dimmer stay 0 (rule 4)
            if ch.role not in EMITTERS and ch.role not in ("dimmer", "dimmer_fine", "haze"):
                frame[fx.slot(ch)] = ch.default

        if t.kind == Kind.HAZE:  # rule 5: only the haze controller
            for ch in t.channels:
                if ch.role == "haze":
                    frame[fx.slot(ch)] = _byte(st.haze_level)
            return

        self._position(fx, fl, frame)
        if fx.id in self.zone_black:  # v7: pointed into a black exclusion zone: colour off there (rule 8)
            return

        # decide what (if anything) lights this fixture
        prof = self.rig.profile
        scale = masters.level(fx.sub)  # rule 6
        colour: Colour | None = None
        pixels: list[Colour] | None = None
        use_look = False
        if st.blackout:
            pass
        elif fx.id in self.rig.exempt:  # rule 3: MASTER doesn't touch exempt fixtures (kick light)
            colour = fl.colour if fl and fl.colour else self.rig.kick_colour
            pixels = fl.pixels if fl else None
            use_look = fl is not None
            if st.gate_all:
                scale *= st.gate
        elif prof.drum_flash and not st.master and fx.id in st.flashes:  # rule 2: only with MASTER off
            fls = st.flashes[fx.id]
            colour = fls.colour
            scale *= fls.level * masters.flash.value
            if fl is not None and fl.unlit:  # v6 darkness: black slots of the pattern stay black
                colour, pixels = self._flash_lit(fx, fl, fls.colour)
        elif not prof.master_gate:  # no MASTER on/off: the look decides, at its intensity
            if fl is not None and (fl.is_on() or fl.unlit):  # v6: black from darkness is colour off, dimmer as it was
                colour, pixels, use_look = fl.colour, fl.pixels, True
                if fl.intensity is not None:
                    scale *= fl.intensity
                scale *= st.gate
        elif st.master and fl is not None and (fl.is_on() or fl.unlit):  # rule 1: MASTER owns on/off
            # (v6: a light blacked by darkness keeps its dimmer; only colour goes to 0)
            colour, pixels, use_look = fl.colour, fl.pixels, True
            scale *= st.gate

        if colour is None and pixels is None:
            return  # dark: emitters and dimmer stay 0 (rule 4)

        auto = t.colour_mix == "auto"
        wheel: int | None = None
        if auto and not t.emitters and colour:  # dimmer-only or colour wheel: the colour's brightness
            scale *= brightness(colour)
            if t.has("colour_wheel") and not (use_look and fl is not None and fl.colour_wheel is not None):
                slot_ = nearest_slot(colour, t)
                wheel = slot_.value if slot_ else None
        if auto:
            colour = mix(colour, t) if colour else colour
            pixels = [mix(p, t) for p in pixels] if pixels else pixels
        has_dimmer = t.has_dimmer
        emit_scale = 1.0 if has_dimmer else scale
        if has_dimmer:
            _write(fx, frame, "dimmer", scale)
        for ch in t.channels:
            slot = fx.slot(ch)
            if ch.role in EMITTERS:
                src = colour or {}
                if ch.pixel is not None and pixels:
                    src = pixels[ch.pixel] if ch.pixel < len(pixels) else {}
                frame[slot] = _byte(src.get(ch.role, 0.0) * emit_scale)
            elif ch.role == "colour_wheel" and wheel is not None:
                frame[slot] = wheel
            elif use_look and fl is not None:
                if ch.role == "colour_wheel" and fl.colour_wheel is not None:
                    frame[slot] = fl.colour_wheel
                elif ch.role == "gobo" and fl.gobo is not None:
                    frame[slot] = fl.gobo
                elif ch.role == "strobe" and fl.strobe is not None:
                    frame[slot] = fl.strobe
                elif ch.role == "prism" and fl.prism is not None:
                    frame[slot] = fl.prism
        if use_look and fl is not None:  # beam: zoom, focus, frost (0-1)
            for role in ("zoom", "focus", "frost"):
                v = getattr(fl, role)
                if v is not None and t.has(role):
                    _write(fx, frame, role, v)

    @staticmethod
    def _flash_lit(fx: Fixture, fl: FixtureLook, c: Colour) -> tuple[Colour | None, list[Colour] | None]:
        """A drum flash on a light the pattern has partly blacked (lit / darkness): only what's lit flashes."""
        def black(px: Colour | None) -> bool:
            return not px or not any(v > 0 for v in px.values())

        if -1 in fl.unlit and black(fl.colour) and not fl.pixels:
            return None, None
        n = max((ch.pixel for ch in fx.type.channels if ch.pixel is not None), default=-1) + 1
        if not n:
            return (None, None) if black(fl.colour) and not fl.pixels else (c, None)
        row = fl.pixels or [fl.colour] * n
        out = [{} if (i in fl.unlit or -1 in fl.unlit) and black(row[i] if i < len(row) else None) else dict(c)
               for i in range(n)]
        return (None, None) if not any(out) else (None, out)

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
            zf = self.zones.get(fx.id)
            if zf is not None:  # v7, rule 8: exclusion zones (the held position stays the target, so the
                if zf.black((pan, tilt)):  # head comes back out the way it went round)
                    self.zone_black.add(fx.id)
                pan, tilt = zf.step((pan, tilt), self.now)
        self.out_position[fx.id] = (pan, tilt)
        speed = fl.speed if (fl is not None and fl.speed is not None and not t.colour_only) else 1.0
        _write(fx, frame, "pan", pan)
        _write(fx, frame, "tilt", tilt)
        _write(fx, frame, "pt_speed", speed)  # rule 7: MHL36 0 = fastest (invert: true)
