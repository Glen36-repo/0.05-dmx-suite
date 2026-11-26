"""Scene and show generator (v3.5): the autopilot's engine, writing normal, editable scenes and
shows instead of playing live. Same FX banks, classification, palettes, quality rules and ratings.

- capture: what's showing now as a scene (a Ride / autopilot look as its layers; anything else as a
  still of every light)
- generate scenes: mood, style, palette, how many -> that many scenes for the running rig
- lock and re-roll: keep the parts you like (move, colour, drum, palette, ride) and re-roll the
  rest; "more like this" keeps the FX and varies the rest
- generate a show: sets with steps, repeats and fades from a mood plan (verse low, chorus high...)
- per song: a starter show for each setlist song from its name, mood and BPM

Output is plain YAML with a `generated:` note (seed, mood, style, palette, the pick), so it can be
made again, edited by hand, on screen or by Claude. The same seed + rig + settings always gives the
same files. Haze is never in a generated scene (looks can't hold it, rule 5).
"""

from __future__ import annotations

import random
import re
import zlib
from dataclasses import dataclass
from typing import Any

from .classify import AutoRig
from .fxbanks import BY_ID, Item, Pick, RideSettings, available, compose
from .quality import Quality

STYLES: dict[str, dict[str, Any]] = {
    # allowed items by bank (None = any the rig can do), palettes by tag, ride feel
    "rock": {"move": None, "colour": None, "drum": ["kick_pump", "snare_hit", "fill_build", "cymbal_shimmer"],
             "palette_tags": ["band", "high", "warm"], "ride": {"speed": 1.2, "size": 0.7}},
    "ballad": {"move": ["float", "swim", "kit", "pan_sweep"], "colour": ["colour_fade", "twinkle", "static", "pulse", "carousel"],
               "drum": [], "palette_tags": ["low", "warm", "cool"], "ride": {"speed": 0.6, "size": 0.35, "fade": 0.9}},
    "acoustic": {"move": ["float", "swim", "kit"], "colour": ["static", "colour_fade", "twinkle", "split", "carousel"],
                 "drum": [], "palette_tags": ["warm", "low", "mid"], "ride": {"speed": 0.7, "size": 0.4, "fade": 0.8}},
    "opera": {"move": ["pan_sweep", "kit", "float"], "colour": ["static", "colour_fade"], "drum": [],
              "palette_tags": ["white"], "ride": {"speed": 0.5, "size": 0.3, "fade": 1.0}},
    "dance": {"move": None, "colour": None, "drum": ["kick_pump", "velocity_colour", "snare_hit"],
              "palette_tags": ["high", "cool"], "ride": {"speed": 1.4, "size": 0.8}},
}
LOCKS = ("move", "colour", "drum", "palette", "ride")
PLAN_DEFAULT = [("verse", "low", 2), ("chorus", "high", 2), ("verse", "low", 2), ("chorus", "high", 2), ("bridge", "mid", 1),
                ("chorus", "high", 2)]


def slug(s: str, fallback: str = "gen") -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:32] or fallback


@dataclass
class Context:
    ar: AutoRig
    palettes: dict[str, dict[str, Any]]  # key -> {name, tags, colours, resolved}
    quality: Quality
    ratings: dict[str, int]


class Generator:
    def __init__(self, ctx: Context, seed: str = "gen") -> None:
        self.ctx = ctx
        self.seed = str(seed)
        self.rng = random.Random(zlib.crc32(self.seed.encode()))

    # ------------------------------------------------------------------ picking

    def _items(self, bank: str, mood: str, style: dict[str, Any] | None) -> list[str | None]:
        ok: list[str | None] = [i.id for i in available(self.ctx.ar, bank, mood)]
        allow = (style or {}).get(bank)
        if allow is not None:
            ok = [x for x in ok if x in allow] or ([] if bank == "drum" else ok)
        if bank == "move":
            return [*ok] or [None]
        if bank == "drum":
            return [None, None, *ok]
        return [*ok] or ["static"]

    def _palettes(self, mood: str, style: dict[str, Any] | None, palette: str | None) -> list[str]:
        pals = self.ctx.palettes
        if palette:
            return [palette] if palette in pals else list(pals)
        tags = (style or {}).get("palette_tags") or [mood]
        got = [k for k, v in pals.items() if set(tags) & set(v.get("tags") or [])]
        return got or list(pals)

    def pick(self, mood: str = "mid", style: str | None = None, palette: str | None = None, prev: Pick | None = None,
             avoid: set[str] | None = None, base: Pick | None = None, locks: tuple[str, ...] = ()) -> Pick:
        """One good pick: passes the quality rules, contrasts with `prev`, not banned, liked looks favoured."""
        st = STYLES.get(style or "") if style else None
        if style and st is None:
            raise ValueError(f"style is one of {', '.join(STYLES)}")
        ride = RideSettings.from_dict((st or {}).get("ride"))
        moves = self._items("move", mood, st)
        colours = self._items("colour", mood, st)
        drums = self._items("drum", mood, st) if mood != "low" else [None]
        pals = self._palettes(mood, st, palette)
        q, avoid = self.ctx.quality, avoid or set()
        pal_cols = {k: v.get("resolved", []) for k, v in self.ctx.palettes.items()}
        best, best_score = None, -1e9
        for _ in range(240):
            p = Pick(self.rng.choice(moves), self.rng.choice(colours), self.rng.choice(drums), self.rng.choice(pals), ride)
            if base is not None:
                for k in locks:
                    if k == "ride":
                        p.ride, p.bank_ride = base.ride, dict(base.bank_ride)
                    else:
                        setattr(p, k, getattr(base, k))
            r = self.ctx.ratings.get(p.key(), 0)
            if r <= -2 or p.key() in avoid:
                continue
            if q.combo_issues(p, mood) and not locks:
                continue
            if prev is not None and not q.contrast_ok(prev, p, pal_cols) and len(locks) < 3:
                continue
            score = (2.5 if r > 0 else -4.0 if r < 0 else 0.0) + self.rng.random()
            if score > best_score:
                best, best_score = p, score
        return best or Pick(moves[0], colours[0], None, pals[0], ride)

    def reroll(self, base: Pick, locks: tuple[str, ...], mood: str = "mid") -> Pick:
        """Keep the locked parts, re-roll the rest (never the same look back)."""
        bad = set(locks) - set(LOCKS)
        if bad:
            raise ValueError(f"locks are {', '.join(LOCKS)}")
        return self.pick(mood, base=base, locks=locks, avoid={base.key()})

    def more_like(self, base: Pick, n: int = 4) -> list[Pick]:
        """Variations of one look: same FX, other palettes and ride settings."""
        out: list[Pick] = []
        pals = list(self.ctx.palettes)
        for _ in range(n):
            ride = RideSettings(speed=round(base.ride.speed * self.rng.uniform(0.75, 1.3), 3),
                                fade=base.ride.fade, fan=round(self.rng.uniform(0.2, 0.9), 3),
                                size=round(self.rng.uniform(0.3, 0.8), 3), shift=round(self.rng.random() * 0.5, 3))
            ride.speed = max(0.25, min(4.0, ride.speed))
            p = Pick(base.move, base.colour, base.drum, self.rng.choice(pals), ride)
            out.append(p)
        return out

    # ------------------------------------------------------------------ files

    def scene(self, p: Pick, name: str, mood: str, style: str | None) -> dict[str, Any]:
        pal = self.ctx.palettes.get(p.palette) or next(iter(self.ctx.palettes.values()))
        data = compose(p, self.ctx.ar, list(pal["colours"]), name)
        data["generated"] = {"seed": self.seed, "mood": mood, "style": style, "palette": p.palette, "pick": p.to_dict()}
        return data

    def scenes(self, mood: str = "mid", style: str | None = None, palette: str | None = None, count: int = 4,
               prefix: str = "gen") -> dict[str, dict[str, Any]]:
        """`count` scenes for this rig; contrasting, never repeating, all through the quality rules."""
        out: dict[str, dict[str, Any]] = {}
        prev: Pick | None = None
        seen: set[str] = set()
        for i in range(max(1, min(50, int(count)))):
            p = self.pick(mood, style, palette, prev, seen)
            seen.add(p.key())
            prev = p
            label = " + ".join(BY_ID[x].label for x in (p.move, p.colour) if x and x in BY_ID)
            name = f"{prefix.replace('_', ' ').title()} {i + 1}: {label}"
            out[f"{slug(prefix)}_{i + 1}"] = self.scene(p, name, mood, style)
        return out

    def show(self, name: str, plan: list[tuple[str, str, int]] | None = None, style: str | None = None,
             palette: str | None = None, hold_s: float = 30.0,
             fade_s: float = 2.0) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        """A show from a mood plan [(section, mood, repeats or bars)...]: one set, a step per section,
        a scene per distinct section. Returns (show data, scenes)."""
        plan = plan or PLAN_DEFAULT
        key = slug(name, "show")
        scenes: dict[str, dict[str, Any]] = {}
        by_section: dict[str, str] = {}
        prev: Pick | None = None
        for section, mood, _n in plan:
            if section in by_section:
                continue
            p = self.pick(mood, style, palette, prev)
            prev = p
            sk = f"{key}_{slug(section)}"
            scenes[sk] = self.scene(p, f"{name}: {section}", mood, style)
            by_section[section] = sk
        steps = []
        for section, _mood, n in plan:
            steps.append({"scene": by_section[section], "hold_s": round(hold_s * max(1, int(n)) / 2, 2), "fade_s": fade_s})
        show = {"name": name, "sets": {"song": {"steps": steps, "loop": True}},
                "generated": {"seed": self.seed, "style": style, "palette": palette,
                              "plan": [{"section": s, "mood": m, "length": n} for s, m, n in plan]}}
        return show, scenes


def song_plan(mood: str | None, bpm: float | None) -> tuple[list[tuple[str, str, int]], float]:
    """A starter plan and step time for a song from its mood and tempo (8 bars a section)."""
    m = mood or "mid"
    quieter = {"high": "mid", "mid": "low", "low": "low"}[m]
    plan = [("intro", quieter, 1), ("verse", quieter, 2), ("chorus", m, 2), ("verse", quieter, 2), ("chorus", m, 2),
            ("outro", quieter, 1)]
    hold = 8 * 4 * 60 / bpm if bpm else 30.0  # 8 bars of 4/4
    return plan, round(hold, 2)


def items_for(ar: AutoRig, bank: str) -> list[Item]:
    return available(ar, bank)
