"""Beat clock from the drummer's playing (v6 Part B): BPM, beat, bar and confidence from every drum hit,
for a band that plays without a click. The module's own MIDI clock isn't used (it only follows the
module's metronome).

No single drum is enough: the kick is irregular, the snare's 2 and 4 break down in fills, the hi-hat
changes subdivision between songs. So:

1. Seed: a tap (tap pad, the FCB1010 tap button) or a count-in (4 evenly spaced hits on a count-in pad
   after > 2 s silence) sets the BPM straight away and clears the history. The last seed wins.
2. Onsets: every hit on a drum role, weighted (kick 1, snare 1, hat 0.5, tom 0.6, cymbal 0.4); hits within
   30 ms merge into one onset with the strongest weight; ghost notes under the velocity floor are ignored.
3. Tracker: the last ~6 s of onsets scored against candidate tempos within +-15 % of the seed (so it can't
   lock to half or double time) with a comb filter: how well the hits line up with a grid of that period
   (the beat itself plus its half, so eighth-note hats count for the tempo instead of against it). The
   best grid gives the raw BPM and the beat phase; the snare's 2 and 4 and the kick's 1 give the bar.
4. Output: the median of the raw tempo over the last 8 beats. It moves only when the median is more than
   3 % off for 4 beats, then glides there over 1-2 beats; a change over 15 % is ignored unless it holds for
   8 beats, then it re-seeds (a real tempo change). The phase is nudged at most 10 % of a beat per beat,
   by running a little fast or slow, so effect time never jumps.
5. Confidence 0-1 from how many recent beats had a hit and how strongly the hits line up. Under the
   threshold (fills, breakdowns, drums stopped) the clock freewheels at the last good tempo and phase,
   for as long as it takes: it never falls back to fixed timers.

Everything is a function of the timestamps it's given, so tests feed it grooves.
"""

from __future__ import annotations

import cmath
import math
import statistics
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

MIN_BPM, MAX_BPM = 40.0, 240.0

ROLE_WEIGHTS = {"kick": 1.0, "snare": 1.0, "hat": 0.5, "tom": 0.6, "cymbal": 0.4}
KAPPA = 8.0  # comb tooth sharpness for the confidence (about +-6 % of a beat)


@dataclass
class BeatParams:
    """Every setting is live-tunable (rig `tempo:` block, Input Monitor, Claude's set_tempo_params)."""

    deadband_pct: float = 3.0  # output moves only when the median is further off than this ...
    hold_beats: int = 4  # ... for this many beats
    glide_beats: float = 1.5  # then glides there over this many beats
    jump_pct: float = 15.0  # a bigger change is ignored ...
    jump_hold_beats: int = 8  # ... unless it holds this long, then re-seeds
    lock_pct: float = 15.0  # tracker searches +- this around the seed
    window_s: float = 6.0
    merge_ms: float = 30.0
    velocity_floor: int = 30
    confidence: float = 0.4  # under this: freewheel
    median_beats: int = 8
    phase_nudge: float = 0.1  # most phase correction per beat (part of a beat)
    weights: dict[str, float] = field(default_factory=lambda: dict(ROLE_WEIGHTS))
    count_in_silence_s: float = 2.0
    count_in_hits: int = 4

    RANGES = {"deadband_pct": (0.5, 20), "hold_beats": (1, 32), "glide_beats": (0, 8), "jump_pct": (5, 60),
              "jump_hold_beats": (2, 64), "lock_pct": (3, 30), "window_s": (2, 20), "merge_ms": (5, 100),
              "velocity_floor": (0, 127), "confidence": (0.05, 0.95), "median_beats": (1, 32),
              "phase_nudge": (0.01, 0.5), "count_in_silence_s": (0.5, 10), "count_in_hits": (2, 8)}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def update(self, changes: dict[str, Any]) -> BeatParams:
        """A copy with these changes, checked."""
        d = self.to_dict()
        for k, v in (changes or {}).items():
            if k == "weights":
                if not isinstance(v, dict) or any(r not in ROLE_WEIGHTS for r in v) or any(
                        isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= 2 for x in v.values()):
                    raise ValueError(f"tempo weights: {{{', '.join(ROLE_WEIGHTS)}}} each 0-2")
                d["weights"] = {**d["weights"], **{r: float(x) for r, x in v.items()}}
                continue
            if k not in self.RANGES:
                raise ValueError(f"unknown tempo setting {k!r}; settings: weights, {', '.join(self.RANGES)}")
            lo, hi = self.RANGES[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                raise ValueError(f"tempo {k}: {lo}-{hi}")
            d[k] = int(v) if isinstance(getattr(self, k), int) else float(v)
        return BeatParams(**d)


@dataclass
class Onset:
    t: float
    w: float
    role: str
    vel: int = 100


def _wrap(x: float) -> float:
    """-0.5 .. 0.5"""
    return (x + 0.5) % 1.0 - 0.5


class BeatTracker:
    def __init__(self, now: float = 0.0, params: BeatParams | None = None) -> None:
        self._lock = threading.RLock()
        self.p = params or BeatParams()
        self.onsets: deque[Onset] = deque(maxlen=400)
        self.seed_bpm: float | None = None
        self.seed_source = ""
        self.out_bpm: float | None = None
        # output beat clock: beats(now) = b0 + (now - t0) * rate, rate = out_bpm / 60 * (1 + nudge)
        self._t0, self._b0, self._rate = now, 0.0, 0.0
        self._next_beat = 1.0
        self._nudge = 0.0
        self._glide: tuple[float, float, float, float] | None = None  # from_bpm, to_bpm, start beat, beats
        self.raw_bpm: float | None = None
        self.raw_phase: float | None = None  # time of a beat on the tracker's grid
        self.confidence = 0.0
        self.freewheel = True
        self._medians: deque[float] = deque(maxlen=self.p.median_beats)
        self._off = 0  # beats the median has been > deadband off (signed run)
        self._jump = 0
        self.bar_offset = 0  # output beat index of a downbeat, mod 4
        self.history: deque[tuple[float, float | None, float | None, float]] = deque(maxlen=600)  # t, raw, out, conf
        self._last_update = -1e9
        self._count_in: list[float] = []
        self._last_onset_t = -1e9

    # ------------------------------------------------------------------ seeds

    def seed(self, bpm: float, now: float, source: str = "tap", beat_at: float | None = None) -> None:
        """Set the tempo now (tap / count-in / FCB tap): output straight away, tracker history cleared."""
        with self._lock:
            if not MIN_BPM <= bpm <= MAX_BPM:
                return
            self.seed_bpm, self.seed_source = bpm, source
            self.onsets.clear()
            self._medians = deque(maxlen=self.p.median_beats)
            self._off = self._jump = 0
            self._glide = None
            self._nudge = 0.0
            self.raw_bpm, self.raw_phase = bpm, beat_at if beat_at is not None else now
            # the output clock: a beat on beat_at (the tap), rate from bpm, continuous from where it was
            b_now = self.beats(now)
            self.out_bpm = bpm
            if beat_at is not None:  # line the beat up with the tap, by the shortest way round (no jump back)
                target = b_now + _wrap(-(b_now - math.floor(b_now)) + (now - beat_at) * bpm / 60.0)
                b_now = max(b_now, target) if target - b_now < 0.5 else target
            self._t0, self._b0, self._rate = now, b_now, bpm / 60.0
            self._next_beat = math.floor(b_now) + 1.0
            self.freewheel = False
            self.confidence = 1.0

    def count_in_hit(self, now: float) -> float | None:
        """A hit on a count-in pad (sticks / hat): 4 evenly spaced after > 2 s silence seed the tempo."""
        with self._lock:
            c = self._count_in
            if c and now - c[-1] > self.p.count_in_silence_s:
                c.clear()
            if not c and now - self._last_onset_t < self.p.count_in_silence_s and self._last_onset_t > 0:
                return None  # not after a silence: part of the groove
            c.append(now)
            n = self.p.count_in_hits
            if len(c) < n:
                return None
            gaps = [b - a for a, b in zip(c[-n:], c[-n + 1:])]
            mean = sum(gaps) / len(gaps)
            if mean <= 0 or any(abs(g - mean) > 0.1 * mean for g in gaps):
                c[:] = c[-1:]
                return None
            bpm = 60.0 / mean
            c.clear()
            if MIN_BPM <= bpm <= MAX_BPM:
                self.seed(bpm, now, "count-in", beat_at=now)
                return bpm
            return None

    # ------------------------------------------------------------------ onsets

    def hit(self, roles: list[str] | tuple[str, ...], velocity: int, now: float, weight: float | None = None,
            floor: int | None = None) -> bool:
        """A drum hit. Returns whether it counted as an onset. `weight` / `floor` (a kit zone's) override the
        role's weight and the velocity floor."""
        with self._lock:
            w = max((self.p.weights.get(r, 0.0) for r in roles), default=0.0)
            if weight is not None and w > 0:
                w = weight
            if w <= 0 or velocity < (self.p.velocity_floor if floor is None else floor):
                return False
            role = max(roles, key=lambda r: self.p.weights.get(r, 0.0))
            self._last_onset_t = now
            last = self.onsets[-1] if self.onsets else None
            if last is not None and now - last.t <= self.p.merge_ms / 1000:
                if w > last.w:
                    last.w, last.role, last.vel = w, role, velocity
                return True
            self.onsets.append(Onset(now, w, role, velocity))
            return True

    # ------------------------------------------------------------------ tracking

    @staticmethod
    def _score(ons: list[Onset], period: float) -> tuple[float, float, float]:
        """Comb score for a beat period: (R1 + R2) / 2, R1 = how the hits line up on the beat, R2 on the
        half beat; and the beat phase (radians) from R1."""
        tw = sum(o.w for o in ons) or 1.0
        z1 = sum(o.w * cmath.exp(2j * math.pi * o.t / period) for o in ons)
        z2 = sum(o.w * cmath.exp(4j * math.pi * o.t / period) for o in ons)
        r1, r2 = abs(z1) / tw, abs(z2) / tw
        return (r1 + r2) / 2, r1, cmath.phase(z1)

    def _best(self, ons: list[Onset], lo: float, hi: float) -> tuple[float, float, float, float]:
        """(bpm, score, r1, phase) best in lo..hi BPM: coarse then fine."""
        best = (lo, -1.0, 0.0, 0.0)
        steps = max(2, int((hi - lo) / 0.5))
        for i in range(steps + 1):
            bpm = lo + (hi - lo) * i / steps
            s, r1, ph = self._score(ons, 60.0 / bpm)
            if s > best[1]:
                best = (bpm, s, r1, ph)
        c = best[0]
        for i in range(-10, 11):
            bpm = min(hi, max(lo, c + i * 0.05))
            s, r1, ph = self._score(ons, 60.0 / bpm)
            if s > best[1]:
                best = (bpm, s, r1, ph)
        return best

    def _track(self, now: float) -> None:
        """Raw tempo, phase and confidence from the window of onsets."""
        p = self.p
        ons = [o for o in self.onsets if now - o.t <= p.window_s]
        seed = self.seed_bpm or self.out_bpm
        if seed is None or len(ons) < 4:
            self.confidence = 0.0
            return
        lo, hi = max(MIN_BPM, seed * (1 - p.lock_pct / 100)), min(MAX_BPM, seed * (1 + p.lock_pct / 100))
        bpm, score, r1, ph = self._best(ons, lo, hi)
        if min(bpm - lo, hi - bpm) < 0.3:  # pinned to the edge: look wider (but never half / double time)
            wide = [self._best(ons, max(MIN_BPM, seed * a), min(MAX_BPM, seed * b))
                    for a, b in ((0.6, 1 - p.lock_pct / 100), (1 + p.lock_pct / 100, 1.4))]
            w = max(wide, key=lambda x: x[1])
            if w[1] > score:
                bpm, score, r1, ph = w
        period = 60.0 / bpm
        self.raw_bpm = bpm
        self.raw_phase = (ph / (2 * math.pi)) * period  # a beat falls at t = raw_phase + k * period
        # comb peak strength: the share of the hits' weight that lands right on the beat (a narrow tooth),
        # so hats in eighths or sixteenths under kick and snare score well and an even tom fill doesn't
        tw = sum(o.w for o in ons) or 1.0
        peak = sum(o.w * math.exp(KAPPA * (math.cos(2 * math.pi * (o.t - self.raw_phase) / period) - 1))
                   for o in ons) / tw
        # coverage: of the last 4 beats, how many had a hit close to the grid
        cover = 0
        for k in range(1, 5):
            tb = self.raw_phase + math.floor((now - self.raw_phase) / period - k + 1) * period
            if any(abs(o.t - tb) < 0.15 * period for o in ons):
                cover += 1
        self.confidence = max(0.0, min(1.0, peak * (cover / 4) * 1.25))
        self._bar(ons, period)

    def _bar(self, ons: list[Onset], period: float) -> None:
        """Snare-weighted 2 and 4 (and the kick's 1) put the bar on the output beats."""
        snares = [o for o in ons if o.role == "snare"]
        kicks = [o for o in ons if o.role == "kick"]
        if len(snares) < 2 or self.raw_phase is None:
            return

        def on_beat(t: float) -> int | None:  # output beat number when t is close to one, else None
            b = self._beats_at(t)
            n = math.floor(b + 0.5)
            return n if abs(b - n) < 0.2 else None

        sn = [n for n in (on_beat(o.t) for o in snares) if n is not None]
        if not sn:
            return
        back = statistics.mode([n % 2 for n in sn])  # backbeats: 2 and 4
        # of the other two beats in the bar, the downbeat is the one with more (and harder) kick
        cands = [(back + 1) % 4, (back + 3) % 4]
        kick_w = {c: 0.0 for c in cands}
        for o in kicks:
            n = on_beat(o.t)
            if n is not None and n % 4 in kick_w:
                kick_w[n % 4] += o.vel
        if kick_w[cands[0]] != kick_w[cands[1]]:
            self.bar_offset = max(cands, key=lambda c: kick_w[c])
        elif self.bar_offset % 2 == back:  # no kick to tell: at least keep the snare off beat 1
            self.bar_offset = cands[0]

    # ------------------------------------------------------------------ the output clock

    def _beats_at(self, t: float) -> float:
        return self._b0 + (t - self._t0) * self._rate

    def beats(self, now: float) -> float:
        """Output beats since the start: continuous, never jumps."""
        return self._beats_at(now)

    def _set_rate(self, now: float) -> None:
        b = self._beats_at(now)
        bpm = self.out_bpm or 120.0
        self._t0, self._b0, self._rate = now, b, bpm / 60.0 * (1 + self._nudge)

    def update(self, now: float, every_s: float = 0.05) -> None:
        """Run the tracker (at most every `every_s`) and step the output clock through any beats passed."""
        with self._lock:
            if self.out_bpm is None:
                return
            if now - self._last_update >= every_s:
                self._last_update = now
                self._track(now)
                self.freewheel = self.confidence < self.p.confidence
            if self._glide is not None:
                f0, f1, start, n = self._glide
                k = (self.beats(now) - start) / n if n > 0 else 1.0
                self.out_bpm = f1 if k >= 1 else f0 + (f1 - f0) * k
                if k >= 1:
                    self._glide = None
                self._set_rate(now)
            while self.beats(now) >= self._next_beat:
                self._on_beat(now)
                self._next_beat += 1.0
            self.history.append((now, self.raw_bpm, self.out_bpm, self.confidence))

    def _on_beat(self, now: float) -> None:
        p = self.p
        out = self.out_bpm or 120.0
        if self.freewheel or self.raw_bpm is None or self.raw_phase is None:
            self._nudge = 0.0  # freewheel: last good tempo and phase
            self._set_rate(now)
            return
        if self._medians.maxlen != p.median_beats:
            self._medians = deque(self._medians, maxlen=p.median_beats)
        self._medians.append(self.raw_bpm)
        med = statistics.median(self._medians)
        diff = (med - out) / out * 100
        if abs(diff) > p.jump_pct:  # big change: only if it holds, then re-seed
            self._jump += 1
            self._off = 0
            if self._jump >= p.jump_hold_beats:
                self.seed(med, now, "tracker")
                return
        else:
            self._jump = 0
            if abs(diff) > p.deadband_pct:
                sign = 1 if diff > 0 else -1
                self._off = self._off + sign if self._off * sign >= 0 else sign  # a run in one direction
                if abs(self._off) >= p.hold_beats and self._glide is None:
                    self._glide = (out, med, self.beats(now), max(0.01, p.glide_beats))
                    self.seed_bpm = med  # the lock window follows the band
                    self._off = 0
            else:
                self._off = 0
        # phase: how far the tracker's beat is from ours, corrected by at most phase_nudge a beat, by rate
        period = 60.0 / self.raw_bpm
        b = self.beats(now)
        err_s = _wrap((now - self.raw_phase) / period) * period  # >0: the band's beat was err_s ago
        err_beats = err_s * (self.out_bpm or out) / 60.0
        drift = _wrap(b - round(b))  # our position past our own beat
        e = _wrap(err_beats - drift)
        self._nudge = max(-p.phase_nudge, min(p.phase_nudge, e))
        self._set_rate(now)

    # ------------------------------------------------------------------ reading

    def status(self, now: float) -> dict[str, Any]:
        with self._lock:
            b = self.beats(now)
            n = math.floor(b)
            return {"bpm": None if self.out_bpm is None else round(self.out_bpm, 1),
                    "raw_bpm": None if self.raw_bpm is None else round(self.raw_bpm, 1),
                    "beat": (n - self.bar_offset) % 4 + 1, "bar": (n - self.bar_offset) // 4 + 1,
                    "phase": round(b - n, 3), "confidence": round(self.confidence, 2), "freewheel": self.freewheel,
                    "seed": None if self.seed_bpm is None else round(self.seed_bpm, 1), "seed_source": self.seed_source}

    def debug(self, now: float, span_s: float = 8.0) -> dict[str, Any]:
        """For the Input Monitor: recent onsets by role, the beat grid, raw vs output BPM, confidence."""
        with self._lock:
            ons = [{"t": round(o.t - now, 3), "w": o.w, "role": o.role} for o in self.onsets if now - o.t <= span_s]
            grid = []
            if self.out_bpm:
                b = self.beats(now)
                for k in range(int(span_s * self.out_bpm / 60) + 2):
                    beat = math.floor(b) - k
                    t = now - (b - beat) * 60 / self.out_bpm
                    if now - t <= span_s:
                        grid.append({"t": round(t - now, 3), "beat": (beat - self.bar_offset) % 4 + 1})
            hist = [(round(t - now, 2), r, o, c) for t, r, o, c in self.history if now - t <= 60]
            return {"onsets": ons, "grid": grid, "history": hist[::max(1, len(hist) // 300)], **self.status(now),
                    "params": self.p.to_dict()}
