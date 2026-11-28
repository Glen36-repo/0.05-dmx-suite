"""Autopilot (v3.4): picks a Move FX + Colour FX + palette + ride settings and changes it on a
timer per mood, from the band's MIDI only (no audio). Also: between songs, hold and the decision log.

Energy (0-1) comes from named inputs by role (drums.BUS): how many `activity` hits a second over the
last few seconds, and how hard. Mood (low / mid / high) is set by a pedal or button, or follows
the energy (with some hysteresis so it doesn't flap). With no drum MIDI, mood is manual only.

A look changes:
- on the mood's timer (e.g. low 60 s, mid 40 s, high 20 s, +- variation), never repeating one of
  the last few looks and always contrasting with the last (look quality rules)
- early on a drum fill followed by a crash: a look change and a colour hit (Flash FX)
- on a build (energy rising fast): faster and bigger; on a breakdown (energy falling): slower, sparser
- between songs: no `activity` input for `gap_s` = song ended, fade to the talking look; a count-in
  (`count_in` hits, evenly spaced) or any activity = song starting, straight back into the show

It never touches haze (looks can't hold haze, rule 5), moves heads only through Move FX (dark
between points), and pauses while MASTER is off (drum flash) or a hold is on. Everything uses a
seeded random generator, so a recorded session replays identically.

Every decision is logged (time, energy, mood, look, why) in memory and, per gig, in
logs/decisions-YYYY-MM-DD.jsonl.

Rig config (all optional):
    autopilot:
      moods: {low: 60, mid: 40, high: 20}   # seconds between changes
      variation: 0.2                        # +- share of that, random
      no_repeat: 4                          # not one of the last N looks
      fade: {low: 4, mid: 2, high: 0.5}     # crossfade into a new look, seconds
      energy: {window_s: 4, full_rate: 6}   # hits a second for full energy
      fill: {window_s: 1.2, hits: 5, crash_s: 1.0}
      between:                              # v7 (format 6: gap_s / count_in / talking at the top)
        on: true                            # off: never between songs (DJ-style sets)
        gap_s: 4                            # silence that ends a song
        start: first_hit                    # first_hit | count_in: what starts the next one
        count_in: 4                         # even hits that make a count-in
        min_song_s: 20                      # a gap this soon after a song starts doesn't end it
        fade_in: null                       # null = the LOW fade
        fade_out: null                      # null = the song's mood fade
        ignore: [fcb_pedal]                 # inputs that don't count as activity
        look: {colour: static, palette: white, move: kit, feel: {speed: 0.5}}   # or {scene: id}
      walk_on: {colour: colour_fade, palette: band, move: swim}   # or {scene: id}
      walk_off: {colour: static, palette: warm}
      palettes: [warm, cool, band]          # only these (default: by mood tag)
      seed: gig-1
"""

from __future__ import annotations

import copy
import json
import logging
import random
import threading
import time
import zlib
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fixtures import ConfigError

log = logging.getLogger(__name__)

MOODS = ("low", "mid", "high")
TRIGGERS = ("timer", "fill_crash", "mood", "build", "breakdown", "song_end", "song_start", "walk_on", "walk_off",
            "next", "previous", "start", "preset")

DEFAULTS: dict[str, Any] = {
    "moods": {"low": 60.0, "mid": 40.0, "high": 20.0},
    "variation": 0.2,
    "no_repeat": 4,
    "fade": {"low": 4.0, "mid": 2.0, "high": 0.5},
    "energy": {"window_s": 4.0, "full_rate": 6.0},
    "fill": {"window_s": 1.2, "hits": 5, "crash_s": 1.0},
    # v7: between songs in one block (format 6 had gap_s / count_in / talking at the top; still read)
    "between": {
        "on": True,
        "gap_s": 4.0,  # no activity this long ends a song
        "start": "first_hit",  # first_hit | count_in: what starts the next song
        "count_in": 4,
        "min_song_s": 20.0,  # a gap this soon after a song starts doesn't end it
        "fade_in": None,  # None = the LOW fade
        "fade_out": None,  # None = the song's mood fade
        "ignore": [],  # named input / kit zone ids that don't count as activity
        "look": {"colour": "static", "palette": "white", "move": "kit", "feel": {"speed": 0.5, "fade": 1.0}},
    },
    "walk_on": {"colour": "colour_fade", "palette": "band", "move": "swim", "feel": {"speed": 0.6}},
    "walk_off": {"colour": "static", "palette": "warm", "feel": {"fade": 1.0}},
    "palettes": [],
    "seed": "",
    "darkness": 0,  # v6: % black put into the Autopilot's effects (not a dimmer)
    "set_darkness": {},  # v6: per set {low, mid, high} %, loaded on a set (mood) change
    # v7 layer timing: together = every layer changes on each look change (v6); staggered = a clock per layer
    "timing": "together",
    "layers": {
        "move": {"every_looks": 1.0, "spread": 25, "locked": False},
        "colour": {"every_looks": 1.0, "spread": 25, "locked": False},
        "palette": {"every_looks": 1.5, "spread": 25, "locked": False},
        "darkness": {"every_looks": 0.5, "spread": 25, "locked": False},
    },
}
LAYERS: tuple[str, ...] = ("move", "colour", "palette", "darkness")  # v7; the drum FX item rides with colour
PICK_LAYERS = ("move", "colour", "palette")
SCHEDULE_KEYS = ("every_s", "every_looks", "on")
TARGET_BUSY = {"low": 0.3, "mid": 0.75, "high": 1.15}


def parse_config(d: Any) -> dict[str, Any]:
    """The rig's `autopilot:` block over the defaults, checked."""
    from .fxbanks import BY_ID
    from .quality import merge

    if d is None:
        return copy.deepcopy(DEFAULTS)
    if not isinstance(d, dict):
        raise ConfigError(f"autopilot: settings are {', '.join(DEFAULTS)}")
    d = fold_between(d)
    if set(d) - set(DEFAULTS):
        raise ConfigError(f"autopilot: settings are {', '.join(DEFAULTS)}")
    from .fxbanks import norm_pick

    d = {k: (_norm_look(v, f"autopilot {k}", norm_pick) if k in ("walk_on", "walk_off") else v) for k, v in d.items()}
    if isinstance(d.get("between"), dict) and set(d["between"]) - set(DEFAULTS["between"]):
        raise ConfigError(f"autopilot between: settings are {', '.join(DEFAULTS['between'])}")
    if isinstance(d.get("between"), dict) and "look" in d["between"]:
        d["between"] = {**d["between"], "look": _norm_look(d["between"]["look"], "autopilot between look", norm_pick)}
    lay = d.get("layers")
    if lay is not None:
        if not isinstance(lay, dict) or set(lay) - set(LAYERS):
            raise ConfigError(f"autopilot layers: {', '.join(LAYERS)}")
        fixed = {}
        for k, v in lay.items():
            if not isinstance(v, dict):
                raise ConfigError(f"autopilot layers {k}: {{every_s | every_looks | on: song|set, spread, locked}}")
            base = DEFAULTS["layers"][k]
            if any(x in v for x in SCHEDULE_KEYS):  # a new schedule replaces the default one
                base = {x: y for x, y in base.items() if x not in SCHEDULE_KEYS}
            fixed[k] = {**base, **v}
        d = {**d, "layers": {**DEFAULTS["layers"], **fixed}}
    out = merge(DEFAULTS, d)
    if lay is not None:
        out["layers"] = copy.deepcopy(d["layers"])
    # a scene replaces the default look (a generated look still merges over it, as in v6)
    if isinstance(d.get("between"), dict) and isinstance(d["between"].get("look"), dict) and "scene" in d["between"]["look"]:
        out["between"]["look"] = d["between"]["look"]
    for k in ("walk_on", "walk_off"):
        if isinstance(d.get(k), dict) and "scene" in d[k]:
            out[k] = d[k]
    for m in MOODS:
        for k in ("moods", "fade"):
            v = out[k].get(m)
            if not isinstance(v, (int, float)) or v < 0 or (k == "moods" and v < 2):
                raise ConfigError(f"autopilot {k} {m}: seconds ({'2 or more' if k == 'moods' else '0 or more'})")
    dk = out["darkness"]
    if isinstance(dk, bool) or not isinstance(dk, (int, float)) or not 0 <= dk <= 100:
        raise ConfigError("autopilot darkness: 0-100 (%)")
    sd = out["set_darkness"]
    if not isinstance(sd, dict) or set(sd) - set(MOODS) or any(
            v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 100) for v in sd.values()):
        raise ConfigError("autopilot set_darkness: {low, mid, high} each 0-100 (%)")
    if not 0 <= float(out["variation"]) <= 0.9:
        raise ConfigError("autopilot variation: 0-0.9")
    if not isinstance(out["no_repeat"], int) or not 0 <= out["no_repeat"] <= 50:
        raise ConfigError("autopilot no_repeat: 0-50 looks")
    if out["timing"] not in TIMINGS:
        raise ConfigError("autopilot timing: together or staggered")
    for k, v in out["layers"].items():
        bad = set(v) - {*SCHEDULE_KEYS, "spread", "locked"}
        if bad:
            raise ConfigError(f"autopilot layers {k}: settings are every_s, every_looks, on, spread, locked")
        sched = [x for x in SCHEDULE_KEYS if x in v]
        if len(sched) != 1:
            raise ConfigError(f"autopilot layers {k}: one of every_s, every_looks or on")
        if "every_s" in v and (_num(v["every_s"]) is None or not 2 <= v["every_s"] <= 3600):
            raise ConfigError(f"autopilot layers {k} every_s: 2-3600 s")
        if "every_looks" in v and (_num(v["every_looks"]) is None or not 0.1 <= v["every_looks"] <= 50):
            raise ConfigError(f"autopilot layers {k} every_looks: 0.1-50 looks")
        if "on" in v and v["on"] not in ("song", "set"):
            raise ConfigError(f"autopilot layers {k} on: song or set")
        if _num(v.get("spread", 0)) is None or not 0 <= v.get("spread", 0) <= 50:
            raise ConfigError(f"autopilot layers {k} spread: 0-50 (%)")
        if not isinstance(v.get("locked", False), bool):
            raise ConfigError(f"autopilot layers {k} locked: true or false")
    b = out["between"]
    if not isinstance(b["on"], bool):
        raise ConfigError("autopilot between on: true or false")
    if _num(b["gap_s"]) is None or b["gap_s"] < 1:
        raise ConfigError("autopilot between gap_s: 1 s or more")
    if b["start"] not in START_MODES:
        raise ConfigError(f"autopilot between start: {' or '.join(START_MODES)}")
    if isinstance(b["count_in"], bool) or not isinstance(b["count_in"], int) or not 2 <= b["count_in"] <= 8:
        raise ConfigError("autopilot between count_in: 2-8 hits")
    if _num(b["min_song_s"]) is None or not 0 <= b["min_song_s"] <= 600:
        raise ConfigError("autopilot between min_song_s: 0-600 s")
    for k in ("fade_in", "fade_out"):
        if b[k] is not None and (_num(b[k]) is None or not 0 <= b[k] <= 30):
            raise ConfigError(f"autopilot between {k}: 0-30 s, or empty for the default")
    if not isinstance(b["ignore"], list) or not all(isinstance(x, str) and x for x in b["ignore"]):
        raise ConfigError("autopilot between ignore: a list of input ids")
    for k, p in (("between look", b["look"]), ("walk_on", out["walk_on"]), ("walk_off", out["walk_off"])):
        if not isinstance(p, dict):
            raise ConfigError(f"autopilot {k}: a look {{colour, move, palette, feel}} or {{scene: id}}")
        if "scene" in p:
            if set(p) != {"scene"} or not isinstance(p["scene"], str) or not p["scene"]:
                raise ConfigError(f"autopilot {k}: {{scene: <scene id>}} on its own")
            continue
        for bank in ("move", "colour", "drum"):
            if p.get(bank) and p[bank] not in BY_ID:
                raise ConfigError(f"autopilot {k}: unknown FX item {p[bank]!r}")
    return out


START_MODES = ("first_hit", "count_in")
TIMINGS = ("together", "staggered")
OLD_BETWEEN = {"gap_s": "gap_s", "count_in": "count_in", "talking": "look"}  # format 6 top-level keys


def fold_between(d: dict[str, Any]) -> dict[str, Any]:
    """Format 6 kept gap_s / count_in / talking at the top of `autopilot:`; v7 keeps them in `between:`.
    Old keys are moved in (a value already in `between:` wins). Used by the 6 -> 7 step and parse_config."""
    if not any(k in d for k in OLD_BETWEEN):
        return d
    d = dict(d)
    b = dict(d.get("between") or {}) if isinstance(d.get("between"), dict) else {}
    for old, new in OLD_BETWEEN.items():
        if old in d:
            v = d.pop(old)
            b.setdefault(new, v)
    d["between"] = b
    return d


def _num(v: Any) -> float | None:
    return None if isinstance(v, bool) or not isinstance(v, (int, float)) else float(v)


def _norm_look(v: Any, where: str, norm_pick: Callable[[Any, str], Any]) -> Any:
    if isinstance(v, dict) and "scene" in v:
        return v  # a pre-built scene, played as authored
    return norm_pick(v, where)


# ---------------------------------------------------------------------- energy


class Energy:
    """Energy 0-1 from named input hits by role, plus fill and count-in detection."""

    def __init__(self, bus: Any, cfg: dict[str, Any]) -> None:
        self.bus = bus
        self.cfg = cfg
        self.history: deque[tuple[float, float]] = deque(maxlen=400)  # (time, energy), for build/breakdown

    def level(self, now: float) -> float:
        w = float(self.cfg["energy"]["window_s"])
        hits = self.bus.recent("activity", now, w)
        if not hits:
            return 0.0
        rate = len(hits) / w
        strength = sum(h.strength for h in hits) / len(hits)
        backbone = 0.1 if any("kick" in h.roles for h in hits) and any("snare" in h.roles for h in hits) else 0.0
        e = min(1.0, 0.65 * min(1.0, rate / float(self.cfg["energy"]["full_rate"])) + 0.3 * strength + backbone)
        return round(e, 3)

    def sample(self, now: float) -> float:
        e = self.level(now)
        if not self.history or now - self.history[-1][0] >= 0.5:
            self.history.append((now, e))
        return e

    def trend(self, now: float, back_s: float = 8.0) -> float:
        """Energy now minus the average a few seconds ago (+ = building, - = breaking down)."""
        old = [e for t, e in self.history if now - back_s - 2 <= t <= now - back_s + 2]
        if not old or not self.history:
            return 0.0
        return self.history[-1][1] - sum(old) / len(old)

    def fill_then_crash(self, now: float, since: float) -> bool:
        """A drum fill (snare/tom hits close together) followed by a crash, since `since`."""
        f = self.cfg["fill"]
        for crash in self.bus.recent("cymbal", now, max(0.05, now - since)):
            before = [h for h in self.bus.recent(None, crash.time, float(f["window_s"]) + float(f["crash_s"]))
                      if ("snare" in h.roles or "tom" in h.roles) and h.time < crash.time]
            if len(before) >= int(f["hits"]) and crash.time - before[-1].time <= float(f["crash_s"]):
                return True
        return False

    def count_in(self, now: float) -> bool:
        """`count_in` hits with the count_in role, evenly spaced (within 25 %), just now."""
        n = int(self.cfg["between"]["count_in"])
        hits = self.bus.recent("count_in", now, 6.0)[-n:]
        if len(hits) < n:
            return False
        gaps = [b.time - a.time for a, b in zip(hits, hits[1:])]
        mean = sum(gaps) / len(gaps)
        return 0.2 <= mean <= 1.5 and all(abs(g - mean) <= 0.25 * mean for g in gaps) and now - hits[-1].time <= 2 * mean


# ---------------------------------------------------------------------- decisions


@dataclass
class Decision:
    time: float
    energy: float
    mood: str
    trigger: str
    look: dict[str, Any]
    why: str
    candidates: int = 0
    rejected: int = 0
    score: float = 0.0
    layers: tuple[str, ...] = ()  # v7: the layers this change swapped (empty = a whole look)

    def to_dict(self) -> dict[str, Any]:
        d = {"time": self.time, "energy": self.energy, "mood": self.mood, "trigger": self.trigger, "look": self.look,
             "why": self.why, "candidates": self.candidates, "rejected": self.rejected, "score": round(self.score, 3)}
        if self.layers:
            d["layers"] = list(self.layers)
        return d


@dataclass
class State:
    on: bool = False
    hold: bool = False
    mood: str = "mid"
    mood_manual: bool = False
    between: bool = False  # between songs (talking look)
    last_change: float = 0.0
    next_change: float = 0.0
    last_activity: float | None = None
    pick: Any = None
    history: list[Any] = field(default_factory=list)  # picks played, newest last
    allowed: list[str] | None = None  # preset ids the autopilot may use (V3.5 presets), None = any
    layer_next: dict[str, float] = field(default_factory=dict)  # v7 staggered: when each clocked layer changes
    locks: dict[str, bool] = field(default_factory=dict)  # v7: live lock per layer (over the rig's `locked`)


class Autopilot:
    """Drives `play(pick, fade_s)` (the app's ride_play). Call tick(now) a few times a second."""

    def __init__(self, play: Callable[[Any, float], Any], rig_auto: Callable[[], Any], palettes: Callable[[], dict[str, Any]],
                 quality: Callable[[], Any], bus: Any, cfg: dict[str, Any] | None = None, log_dir: Path | None = None,
                 master_off: Callable[[], bool] | None = None, flash: Callable[[str], Any] | None = None,
                 ratings: Callable[[], dict[str, int]] | None = None,
                 presets: Callable[[], dict[str, Any]] | None = None,
                 darkness_step: Callable[[float, str], Any] | None = None,
                 playing: Callable[[], Any] | None = None) -> None:
        self.play = play
        self.rig_auto = rig_auto
        self.palettes = palettes  # key -> {name, tags, resolved}
        self.quality = quality
        self.bus = bus
        self.cfg = cfg or copy.deepcopy(DEFAULTS)
        self.energy = Energy(bus, self.cfg)
        self.log_dir = log_dir
        self.master_off = master_off or (lambda: False)
        self.flash = flash
        self.ratings = ratings or (lambda: {})  # look key -> +1 liked / -1 disliked / -2 banned (V3.5)
        self.presets = presets or (lambda: {})  # preset id -> pick dict (V3.5)
        self.darkness_step = darkness_step  # v7: the Darkness layer's change (Auto darkness moves on it)
        self.playing = playing or (lambda: None)  # v7: the look on the page before the autopilot played one
        self.st = State()
        self.decisions: deque[Decision] = deque(maxlen=500)
        self.rng = random.Random(zlib.crc32(str(self.cfg.get("seed") or "autopilot").encode()))
        self._lock = threading.RLock()
        self._last_tick = 0.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------ controls (pedals, buttons, Claude)

    def set_on(self, on: bool, now: float) -> None:
        with self._lock:
            if on and not self.st.on:
                self.st.on = True
                self.st.last_activity = None
                self.change(now, "start")
            elif not on:
                self.st.on = False

    def set_mood(self, mood: str | None, now: float) -> None:
        """A mood by pedal or button (None = back to following the energy)."""
        with self._lock:
            if mood is None:
                self.st.mood_manual = False
                return
            if mood not in MOODS:
                raise ValueError("mood is low, mid or high")
            changed = mood != self.st.mood
            self.st.mood, self.st.mood_manual = mood, True
            if changed and self.st.on and not self.st.hold:
                self.change(now, "mood")

    def mood_step(self, way: int, now: float) -> str:
        i = max(0, min(2, MOODS.index(self.st.mood) + way))
        self.set_mood(MOODS[i], now)
        return self.st.mood

    def set_hold(self, on: bool) -> None:
        with self._lock:
            self.st.hold = on

    def next(self, now: float) -> None:
        with self._lock:
            self.change(now, "next")

    def previous(self, now: float) -> None:
        with self._lock:
            if len(self.st.history) >= 2:
                self.st.history.pop()
                pick = self.st.history[-1]
                self._play(pick, now, "previous", "back to the look before", 0, 0, 0.0)

    def walk(self, which: str, now: float) -> None:
        """Walk-on or walk-off look (button, pedal, or setlist start/end)."""
        from .fxbanks import Pick

        with self._lock:
            pick = Pick.from_dict(self.cfg[which])
            self.st.between = which == "walk_off"
            self._play(pick, now, which, f"{which.replace('_', '-')} look", 0, 0, 0.0, fade=self.cfg["fade"]["low"])

    def locked(self, layer: str) -> bool:
        """v7: a layer held while the others change (live lock over the rig's `locked`)."""
        v = self.st.locks.get(layer)
        return bool(self.cfg["layers"][layer].get("locked")) if v is None else v

    def set_lock(self, layer: str, on: bool | None = None) -> bool:
        """Lock or unlock a layer (None toggles). Live only; the rig's `locked` is the start-up value."""
        if layer not in LAYERS:
            raise ValueError(f"layer is one of {', '.join(LAYERS)}")
        with self._lock:
            on = not self.locked(layer) if on is None else bool(on)
            self.st.locks[layer] = on
            return on

    def limit_to(self, preset_ids: list[str] | None) -> None:
        """Only these presets ("only these looks for this song"); None = any look."""
        with self._lock:
            self.st.allowed = list(preset_ids) if preset_ids else None

    # ------------------------------------------------------------------ the loop

    def tick(self, now: float) -> Decision | None:
        with self._lock:
            e = self.energy.sample(now)
            st = self.st
            if not st.on:
                return None
            last = self.bus.last("activity", now)
            if not st.mood_manual and last is not None:
                self._follow_energy(e)
            if self.master_off():  # MASTER off: drum flash owns the rig; the autopilot waits
                st.next_change = max(st.next_change, now + 1.0)
                for k in st.layer_next:
                    st.layer_next[k] = max(st.layer_next[k], now + 1.0)
                self._last_tick = now
                return None
            since = self._last_tick or now
            self._last_tick = now
            if last is not None and (st.last_activity is None or last.time > st.last_activity):
                new_activity = st.last_activity is None or last.time > st.last_activity
                st.last_activity = last.time
                if st.between and new_activity:  # song starting: count-in or first hit
                    st.between = False
                    why = "count-in" if self.energy.count_in(now) else "first hit after the gap"
                    return self.change(now, "song_start", extra=why)
            if (not st.between and st.last_activity is not None and now - st.last_activity >= float(self.cfg["between"]["gap_s"])
                    and not st.hold):
                st.between = True
                from .fxbanks import Pick

                return self._play(Pick.from_dict(self.cfg["between"]["look"]), now, "song_end",
                                  f"no activity for {now - st.last_activity:.1f} s: talking look", 0, 0, 0.0,
                                  fade=self.cfg["fade"]["low"])
            if st.hold or st.between:
                return None
            if self.energy.fill_then_crash(now, since):
                d = self.change(now, "fill_crash")
                if self.flash is not None:
                    try:
                        self.flash("colour_hit")
                    except Exception:  # a flash must never stop the autopilot
                        log.exception("colour hit failed")
                return d
            tr = self.energy.trend(now)
            if tr >= 0.35 and now - st.last_change > 6:
                return self.change(now, "build", extra=f"energy up {tr:+.2f}")
            if tr <= -0.35 and now - st.last_change > 6:
                return self.change(now, "breakdown", extra=f"energy down {tr:+.2f}")
            if self.staggered:
                return self._layer_timers(now)
            if now >= st.next_change:
                return self.change(now, "timer")
            return None

    # ------------------------------------------------------------------ v7 layer timing

    @property
    def staggered(self) -> bool:
        return self.cfg.get("timing") == "staggered" and not self.st.allowed  # presets play whole looks

    def _base_s(self, layer: str) -> float | None:
        """A clocked layer's interval before spread; None for song / set layers."""
        lay = self.cfg["layers"][layer]
        if "every_s" in lay:
            return float(lay["every_s"])
        if "every_looks" in lay:
            return float(lay["every_looks"]) * float(self.cfg["moods"][self.st.mood])
        return None

    def _schedule(self, layer: str, now: float, part: float = 1.0) -> None:
        base = self._base_s(layer)
        if base is None:
            self.st.layer_next.pop(layer, None)
            return
        sp = float(self.cfg["layers"][layer].get("spread", 0)) / 100
        self.st.layer_next[layer] = now + base * part * (1 + self.rng.uniform(-sp, sp))

    def _schedule_all(self, now: float, layers: tuple[str, ...] = LAYERS) -> None:
        """After a whole-look change: the clocks start a quarter apart, so they never line up."""
        clocked = [k for k in LAYERS if self._base_s(k) is not None]
        for k in layers:
            self._schedule(k, now, (clocked.index(k) + 1) / len(clocked) if k in clocked else 1.0)

    def _layer_timers(self, now: float) -> Decision | None:
        st = self.st
        for k in LAYERS:
            if k not in st.layer_next and self._base_s(k) is not None:
                self._schedule(k, now)
        due = [k for k in LAYERS if k in st.layer_next and now >= st.layer_next[k]]
        if not due:
            return None
        k = min(due, key=lambda x: st.layer_next[x])  # one layer a tick: never a hard cut
        self._schedule(k, now)
        if self.locked(k):
            return None
        if k == "darkness":
            self._darkness(now, "timer")
            return None
        return self.change(now, "timer", layers=(k,))

    def _event_layers(self, trigger: str) -> tuple[str, ...]:
        """Which layers a change on this trigger swaps (locked layers never)."""
        if not self.staggered or trigger in ("start", "preset"):
            out = LAYERS
        else:
            lay = self.cfg["layers"]
            if trigger == "song_start":
                out = tuple(k for k in LAYERS if lay[k].get("on") != "set")
            elif trigger == "mood":
                out = tuple(k for k in LAYERS if lay[k].get("on") != "song")
            elif trigger == "timer":
                out = LAYERS
            else:  # next, fill_crash, build, breakdown: the clocked layers
                out = tuple(k for k in LAYERS if "on" not in lay[k])
        return tuple(k for k in out if not self.locked(k))

    def _darkness(self, now: float, why: str) -> None:
        if self.darkness_step is not None:
            try:
                self.darkness_step(now, why)
            except Exception:  # darkness must never stop the autopilot
                log.exception("darkness step failed")

    def _follow_energy(self, e: float) -> None:
        m = self.st.mood
        if m == "low" and e > 0.42:
            self.st.mood = "mid"
        elif m == "mid" and e > 0.72:
            self.st.mood = "high"
        elif m == "mid" and e < 0.25:
            self.st.mood = "low"
        elif m == "high" and e < 0.55:
            self.st.mood = "mid"

    # ------------------------------------------------------------------ choosing a look

    def _palettes_for(self, mood: str) -> list[str]:
        pals = self.palettes()
        out = set(getattr(self.rig_auto(), "excluded_palettes", ()) or ())  # v7: palette bank exclusions
        usable = {k: v for k, v in pals.items() if k not in out} or pals  # all excluded: exclusions ignored
        allowed = [p for p in self.cfg.get("palettes") or [] if p in usable]
        if allowed:
            return allowed
        tagged = [k for k, v in usable.items() if mood in (v.get("tags") or [])]
        return tagged or list(usable)

    def choose(self, now: float, trigger: str, layers: tuple[str, ...] | None = None) -> tuple[Any, int, int, float]:
        """(pick, candidates looked at, rejected by the rules, score). `layers`: the pick layers to change
        (v7; None = all); the rest stay as playing. Every candidate still passes the quality rules."""
        from .fxbanks import Pick, RideSettings, available

        mood = self.st.mood
        ar = self.rig_auto()
        q = self.quality()
        ratings = self.ratings()
        recent = [p.key() for p in self.st.history[-int(self.cfg["no_repeat"]):]]
        last = self.st.history[-1] if self.st.history else None
        pal_data = {k: v.get("resolved", []) for k, v in self.palettes().items()}
        ride = RideSettings()
        if trigger == "build":
            ride = RideSettings(speed=1.5, size=0.8, fan=0.7)
        elif trigger == "breakdown":
            ride = RideSettings(speed=0.6, size=0.3, fan=0.4)
        elif mood == "low":
            ride = RideSettings(speed=0.8, size=0.35, fade=0.8)
        elif mood == "high":
            ride = RideSettings(speed=1.25, size=0.7, fade=0.2)
        cands: list[Pick]
        if self.st.allowed:  # limited to presets
            pres = self.presets()
            cands = [Pick.from_dict(pres[k]) for k in self.st.allowed if k in pres]
        else:
            # excluded types (auto: exclude_fx) are never picked; a bank with nothing left plays nothing
            # (move, drum) or its least busy type that isn't excluded (colour)
            moves: list[str | None] = [i.id for i in available(ar, "move", mood, skip_excluded=True)] or [None]
            colours = ([i.id for i in available(ar, "colour", mood, skip_excluded=True)]
                       or [i.id for i in available(ar, "colour", None, skip_excluded=True)] or ["static"])
            drums = [None, None] + ([i.id for i in available(ar, "drum", mood, skip_excluded=True)] if mood != "low" else [])
            pals = self._palettes_for(mood)
            cands = []
            cur: Any = self.st.pick or self.playing()
            keep = set() if layers is None or cur is None else {k for k in PICK_LAYERS if k not in layers}
            if not keep:  # a whole look (v6 order of random draws, so seeded runs replay identically)
                for _ in range(320):
                    cands.append(Pick(self.rng.choice(moves), self.rng.choice(colours), self.rng.choice(drums),
                                      self.rng.choice(pals), ride))
            else:  # v7: swap only some layers (a staggered clock keeps the playing feel; an event sets its own)
                if trigger == "timer":
                    ride = cur.ride
                for _ in range(320):
                    p = Pick(cur.move if "move" in keep else self.rng.choice(moves),
                             cur.colour if "colour" in keep else self.rng.choice(colours),
                             cur.drum if "colour" in keep else self.rng.choice(drums),
                             cur.palette if "palette" in keep else self.rng.choice(pals), ride,
                             dict(cur.bank_ride))
                    cands.append(p)
        best: Any = None
        best_score = -1e9
        rejected = 0
        seen = 0
        w = q.r["weights"]
        for p in cands:
            seen += 1
            r = ratings.get(p.key(), 0)
            if r <= -2:  # banned on the look review page
                rejected += 1
                continue
            if p.key() in recent and not self.st.allowed:
                rejected += 1
                continue
            if q.combo_issues(p, mood) and not self.st.allowed:
                rejected += 1
                continue
            if not q.contrast_ok(last, p, pal_data) and not (self.st.allowed and len(cands) == 1):
                rejected += 1
                continue
            busy = sum(q.busy(_item(x)) for x in (p.move, p.colour, p.drum) if x)
            score = (w["mood_match"] + w["busy_fit"] * (1 - min(1.0, abs(busy - TARGET_BUSY[mood])))
                     + (w["liked"] if r > 0 else w["disliked"] if r < 0 else 0) + self.rng.random())
            if score > best_score:
                best, best_score = p, score
        if best is None:  # everything refused (tiny rig, long no-repeat): the least-bad option
            best = cands[0] if cands else Pick(colour="static", ride=ride)
        return best, seen, rejected, best_score

    def change(self, now: float, trigger: str, extra: str = "", layers: tuple[str, ...] | None = None) -> Decision:
        """A new look. `layers` (v7): only these layers; None = what this trigger changes (see _event_layers)."""
        whole = layers is None
        if layers is None:
            layers = self._event_layers(trigger)
        pick_layers = tuple(k for k in layers if k in PICK_LAYERS)
        full = set(pick_layers) == set(PICK_LAYERS)
        pick, seen, rejected, score = self.choose(now, trigger, None if full else pick_layers)
        reasons = {"timer": f"{self.st.mood} timer", "fill_crash": "drum fill then a crash",
                   "mood": f"mood set to {self.st.mood}",
                   "build": "energy building", "breakdown": "energy dropping", "song_start": "song starting",
                   "next": "next look (pedal)", "start": "autopilot on", "preset": "preset"}
        why = reasons.get(trigger, trigger) + (f" ({extra})" if extra else "")
        part = () if full else pick_layers
        if part:
            why += f": {', '.join(part)} only"
        if "darkness" in layers:
            self._darkness(now, trigger)
        d = self._play(pick, now, trigger, why, seen, rejected, score, layers=part)
        if self.staggered:
            if whole:
                self._schedule_all(now, layers)
        return d

    def _play(self, pick: Any, now: float, trigger: str, why: str, seen: int, rejected: int, score: float,
              fade: float | None = None, layers: tuple[str, ...] = ()) -> Decision:
        st = self.st
        fade_s = float(self.cfg["fade"][st.mood]) if fade is None else fade
        try:
            self.play(pick, fade_s)
        except Exception as e:  # a look the rig can't take: log it and try again later
            log.warning("autopilot look refused: %s", e)
            why += f" - refused: {e}"
        if trigger != "previous":
            st.history.append(pick)
            del st.history[:-50]
        st.pick = pick
        st.last_change = now
        base = float(self.cfg["moods"][st.mood])
        var = float(self.cfg["variation"])
        st.next_change = now + base * (1 + self.rng.uniform(-var, var))
        d = Decision(now, self.energy.level(now), st.mood, trigger, pick.to_dict(), why, seen, rejected, score, layers)
        self.decisions.append(d)
        self._log(d)
        return d

    def _log(self, d: Decision) -> None:
        if self.log_dir is None:
            return
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with (self.log_dir / f"decisions-{time.strftime('%Y-%m-%d')}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(d.to_dict()) + "\n")
        except OSError:
            log.exception("decision log write failed")

    # ------------------------------------------------------------------ status

    def status(self, now: float) -> dict[str, Any]:
        st = self.st
        return {"on": st.on, "hold": st.hold, "mood": st.mood, "mood_manual": st.mood_manual, "between": st.between,
                "energy": self.energy.level(now), "next_change_s": round(max(0.0, st.next_change - now), 1) if st.on else None,
                "paused": st.on and self.master_off(), "pick": st.pick.to_dict() if st.pick else None,
                "allowed": st.allowed, "last": self.decisions[-1].to_dict() if self.decisions else None,
                "timing": self.cfg.get("timing", "together"), "layers": self._layer_status(now)}

    def _layer_status(self, now: float) -> dict[str, Any]:
        st, out = self.st, {}
        for k in LAYERS:
            lay = self.cfg["layers"][k]
            nxt = st.layer_next.get(k) if self.staggered else st.next_change  # together: all on the look clock
            out[k] = {"locked": self.locked(k), "on": lay.get("on"),
                      "next_s": round(max(0.0, nxt - now), 1) if (st.on and nxt is not None and not lay.get("on")
                                                                  and not self.locked(k)) else None}
        return out

    def log_since(self, n: int = 50) -> list[dict[str, Any]]:
        return [d.to_dict() for d in list(self.decisions)[-n:]]

    # ------------------------------------------------------------------ background thread (the running app)

    def start(self, clock: Callable[[], float], every_s: float = 0.1) -> None:
        if self._thread is not None:
            return
        self._stop.clear()

        def run() -> None:
            while not self._stop.wait(every_s):
                try:
                    self.tick(clock())
                except Exception:  # never stop the show
                    log.exception("autopilot tick failed")

        self._thread = threading.Thread(target=run, name="autopilot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None


def _item(x: str) -> Any:
    from .fxbanks import BY_ID

    return BY_ID.get(x)
