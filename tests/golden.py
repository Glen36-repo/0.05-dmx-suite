"""Golden frames: the v1 rule layer's output for the shipped shows, as hashes per scenario.

`python -m tests.golden` rewrites tests/data/golden_v1_frames.json. It was captured from the v1
code before the rule-profile split; test_profiles checks the "0.05 band" profile still matches.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dmx_suite.engine import Engine
from dmx_suite.output import LogDriver
from dmx_suite.scenes import ScenePlayer
from dmx_suite.showfiles import load_show
from dmx_suite.shows import ShowPlayer
from dmx_suite.tempo import TempoClock

ROOT = Path(__file__).resolve().parent.parent
SHOWS = ROOT / "shows"
GOLDEN = Path(__file__).parent / "data" / "golden_v1_frames.json"
TIMES = (0.0, 0.7, 2.3, 5.1, 11.9)


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _hash(frames: dict[int, bytearray]) -> str:
    h = hashlib.sha256()
    for u in sorted(frames):
        h.update(bytes([u]) + bytes(frames[u]))
    return h.hexdigest()[:16]


def capture(rig_transform=None, root: Path = SHOWS) -> dict[str, str]:
    """rig_transform(rig) lets the test apply a profile before rendering."""
    out: dict[str, str] = {}
    base = [1000.0]
    for rig_name in ("full", "small"):
        sf = load_show(root, rig=rig_name)
        rig = sf.rig if rig_transform is None else rig_transform(sf.rig)
        clock = _Clock()
        e = Engine(rig, [LogDriver()], sf.look, clock=clock)

        def run(tag: str, source_at) -> None:
            for master in (True, False):
                clock.t = base[0]
                e.set_master(master)
                e.set_source(source_at(clock.t))
                for t in TIMES:
                    clock.t = base[0] + t
                    e.tick()
                    out[f"{rig_name}|{tag}|master={master}|t={t}"] = _hash(e.frames)

        run("look", lambda now: (lambda _n: sf.look))
        for key, sc in sorted(sf.scenes.items()):
            if key.startswith("preset:"):  # v3.5 presets: not part of the v1 frames
                continue
            run(f"scene:{key}", lambda now, sc=sc: ScenePlayer(sc, rig, now))
        for key, show in sorted(sf.shows.items()):
            for set_name in sorted(show.sets):
                def player(now, show=show, s=set_name):
                    return ShowPlayer(show, s, rig, sf.palettes, sf.scenes, TempoClock(now), now, seed="golden")
                run(f"show:{key}:{set_name}", player)
        # drum flash (MASTER off), blackout, grand master
        e.set_source(lambda _n: sf.look)
        e.set_master(False)
        clock.t = base[0] + 1000.0
        e.flash([f.id for f in rig.fixtures], velocity=90, length_ms=200)  # v7: a gate onto the look
        out[f"{rig_name}|flash"] = _hash(e.frames)
        e.set_master(True)
        e.set_blackout(True)
        out[f"{rig_name}|blackout"] = _hash(e.frames)
        e.set_blackout(False)
        e.set_grand(0.5)
        clock.t = base[0] + 1010.0
        e.tick()
        out[f"{rig_name}|grand50"] = _hash(e.frames)
    return out


if __name__ == "__main__":
    GOLDEN.write_text(json.dumps(capture(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {GOLDEN}")
