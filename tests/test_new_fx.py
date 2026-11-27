"""v4.1 effects: directional sweep (one direction per pass, optional dark gap) and random flash (several
at once, each with a fading tail). Their FX items also run through the rule check under both profiles
and the golden frames in test_fx_banks.py, like every other item."""

from pathlib import Path

import pytest

from dmx_suite.layout import full_layout
from dmx_suite.scenes import ScenePlayer, parse_scene
from dmx_suite.showfiles import load_show

SHOWS = Path(__file__).resolve().parents[1] / "shows"
WASHES = ["wash_l", "wash_r", "uking_l", "uking_r", "mh_a", "mh_b"]  # single-cell lights spread over the stage


@pytest.fixture(scope="module")
def rig():
    return load_show(SHOWS).rig


def player(rig, layer):
    sc = parse_scene({"name": "t", "layers": [layer]}, rig.patch, load_show(SHOWS).palettes, "t")
    return ScenePlayer(sc, rig, 0.0)


def level(look, fid, px=None):
    fl = look.fixtures.get(fid)
    if fl is None:
        return 0.0
    c = fl.pixels[px] if px is not None and fl.pixels else fl.colour
    return max(c.values(), default=0.0)


def xs(rig, ids):
    lay = full_layout(rig)  # every light placed, as the effects see them
    return {f: lay[f].x for f in ids}


def ys(rig, ids):
    lay = full_layout(rig)
    return {f: lay[f].y for f in ids}


# ---------------------------------------------------------------- directional sweep


def test_sweep_changes_direction_every_pass(rig):
    p = player(rig, {"effect": "dir_sweep", "fixtures": WASHES, "colour": "red", "period_s": 2.0, "width": 0.3})
    x, y = xs(rig, WASHES), ys(rig, WASHES)
    left, right = min(x, key=x.get), max(x, key=x.get)
    back, front = min(y, key=y.get), max(y, key=y.get)  # the layout has the back of the stage at the top

    def first_lit(start, a, b):
        """Which of a / b the band reaches first during the pass starting at `start`."""
        for k in range(200):
            look = p(start + k * 0.01)
            la, lb = level(look, a), level(look, b)
            if la > 0.5 or lb > 0.5:
                return a if la >= lb else b
        return None

    assert first_lit(0.0, left, right) == left  # pass 1: left to right
    assert first_lit(2.0, left, right) == right  # pass 2: right to left
    assert first_lit(4.0, back, front) == back  # pass 3: top to bottom (back to front)
    assert first_lit(6.0, back, front) == front  # pass 4: bottom to top
    assert first_lit(8.0, left, right) == left  # and round again


def test_sweep_with_dark_between_passes(rig):
    p = player(rig, {"effect": "dir_sweep", "fixtures": WASHES, "colour": "blue", "period_s": 2.0, "width": 0.3,
                     "gap": 0.4})
    for t in (1.25, 1.5, 1.9, 3.3, 3.9):  # the last 40 % of each pass
        look = p(t)
        assert all(level(look, f) == 0.0 for f in WASHES), t  # fully off (rule 4)
    assert any(level(p(t / 100), f) > 0.5 for t in range(0, 120) for f in WASHES)  # lit while the band crosses


@pytest.mark.parametrize("order, first", [("left_right", "x"), ("up_down", "y"), ("left", "x-")])
def test_sweep_directions_setting(rig, order, first):
    p = player(rig, {"effect": "dir_sweep", "fixtures": WASHES, "colour": "red", "period_s": 2.0, "directions": order})
    pos = xs(rig, WASHES) if first.startswith("x") else ys(rig, WASHES)
    lead = (max if first.endswith("-") else min)(pos, key=pos.get)
    lit = next(f for k in range(200) for f in WASHES if level(p(k * 0.01), f) > 0.5)
    assert pos[lit] == pos[lead]


# ---------------------------------------------------------------- random flash


BARS = ["bar_1", "bar_2", "bar_3", "bar_4"]


def test_random_flash_several_at_once_with_a_tail(rig):
    p = player(rig, {"effect": "random_flash", "fixtures": WASHES + BARS, "colour": "white", "rate_hz": 8, "count": 2,
                     "tail_s": 0.8})
    most = 0
    falling = False
    prev: dict = {}
    for k in range(120):  # 3 s at 40 Hz
        look = p(k / 40)
        now = {}
        for f in WASHES:
            now[(f, None)] = level(look, f)
        for f in BARS:
            for px in range(8):
                now[(f, px)] = level(look, f, px)
        most = max(most, sum(1 for v in now.values() if v > 0.05))
        falling |= any(0 < now[u] < prev.get(u, 0) for u in now)  # fading, not cutting off
        prev = now
    assert most >= 4  # several bits lit at once
    assert falling


def test_random_flash_lights_bits_of_a_bar_and_the_rest_stays_off(rig):
    p = player(rig, {"effect": "random_flash", "fixtures": BARS, "colour": "white", "rate_hz": 4, "count": 1,
                     "tail_s": 0.2, "bit": 3})
    for k in range(1, 80):
        look = p(k / 40 + 0.001)
        for f in BARS:
            lit = [px for px in range(8) if level(look, f, px) > 0]
            assert len(lit) in (0, 3, 6), (k, f, lit)  # whole bits of 3 (two flashes can overlap a bar)
            assert all(level(look, f, px) == 0.0 for px in range(8) if px not in lit)


def test_random_flash_is_repeatable(rig):
    layer = {"effect": "random_flash", "fixtures": WASHES, "colour": "red", "rate_hz": 6}
    a, b = player(rig, layer), player(rig, layer)
    for k in range(40):
        la, lb = a(k / 20), b(k / 20)
        assert [level(la, f) for f in WASHES] == [level(lb, f) for f in WASHES]
