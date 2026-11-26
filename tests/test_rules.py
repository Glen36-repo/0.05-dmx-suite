"""One section per hard rule in CLAUDE.md."""

import time

import pytest

from dmx_suite.engine import Engine
from dmx_suite.fixtures import Kind
from dmx_suite.look import FixtureLook, Look, LookError, parse_look
from dmx_suite.output import LogDriver

# ------------------------------------------------------------------ rule 1: MASTER owns on/off


def test_rule1_looks_cannot_set_dimmer(patch):
    # the raw dimmer channel is never a look key; `intensity` is checked per rig profile
    # (test_profiles.py: refused under "0.05 band", allowed under "generic")
    with pytest.raises(LookError, match="rule 1"):
        parse_look({"fixtures": {"mh_a": {"dimmer": 1.0, "colour": [1, 0, 0]}}}, patch)


def test_rule1_master_sets_dimmers(engine, view):
    assert view("mh_a", "dimmer") == 255
    assert view("wash", "dimmer") == 255
    engine.set_master(False)
    assert view("mh_a", "dimmer") == 0
    assert view("wash", "dimmer") == 0
    assert view("mh_a", "red") == 0


def test_rule1_on_off_inside_look_is_colour(engine, view, patch):
    engine.set_look(parse_look({"fixtures": {"mh_a": {"colour": [0, 0, 0]}}}, patch))
    assert view("mh_a", "dimmer") == 0  # black colour = off, dimmer follows


# ------------------------------------------------------------------ rule 2: MASTER off -> drum flashes, immediate


def test_rule2_flash_sends_immediately_then_cuts_to_black(engine, view, out, clock):
    engine.set_master(False)
    before = out.frames
    assert engine.flash(["bar_1"], velocity=127, colour="show", length_ms=100)
    assert out.frames == before + 1  # sent inside the flash call, no tick needed
    assert view("bar_1", "blue", 0) == 255  # show colour = blue
    assert view("bar_2", "blue", 0) == 0  # only mapped fixtures flash
    clock.advance(0.099)
    engine.tick()
    assert view("bar_1", "blue", 0) == 255
    clock.advance(0.002)
    engine.tick()
    assert view.emitters("bar_1") == [0] * 6  # straight back to black, no fade


def test_rule2_no_flash_with_master_on(engine, view):
    assert not engine.flash(["bar_1"], 127, "white")
    assert view("bar_1", "red", 0) == 0  # look is green; no white flash
    assert view("bar_1", "green", 0) == 255


def test_rule2_velocity_sets_brightness(engine, view):
    engine.set_master(False)
    engine.flash(["wash"], velocity=64, colour="white")
    assert view("wash", "dimmer") == round(64 / 127 * 255)
    engine.flash(["bar_1"], velocity=64, colour="white")
    assert view("bar_1", "red", 0) == round(64 / 127 * 255)


def test_rule2_flash_white_or_show_colour(engine, view, clock):
    clock.advance(1)  # the rig came on at start-up; a flash in the same instant is held (strobe limit)
    engine.set_master(False)
    engine.flash(["bar_1"], colour="white")
    assert [view("bar_1", r, 0) for r in ("red", "green", "blue")] == [255, 255, 255]
    engine.flash(["bar_2"], colour="show")
    assert [view("bar_2", r, 0) for r in ("red", "green", "blue")] == [0, 0, 255]


def test_rule2_master_on_clears_running_flash(engine, view):
    engine.set_master(False)
    engine.flash(["bar_1"], colour="white", length_ms=5000)
    engine.set_master(True)
    engine.set_master(False)
    assert view.emitters("bar_1") == [0] * 6


def test_rule2_loop_cuts_flash_on_time(rig, look):
    """Real clock and loop thread: the cut happens at the flash end, not a tick later."""
    seen = []

    def on_frame(_, frame):
        seen.append((time.perf_counter(), frame[19]))  # bar_1 red pixel 0

    out = LogDriver(on_frame=on_frame)
    e = Engine(rig, [out], look)
    e.set_master(False)
    e.start()
    try:
        time.sleep(0.05)
        t0 = time.perf_counter()
        e.flash(["bar_1"], 127, "white", length_ms=60)
        time.sleep(0.2)
    finally:
        e.stop()
    lit = [t for t, v in seen if v and t >= t0]
    off = [t for t, v in seen if not v and t > t0]
    assert lit and lit[0] - t0 < 0.005  # on the wire within 5 ms of the hit
    end = min(t for t in off if t > lit[0])
    assert 0.055 < end - t0 < 0.085  # cut at ~60 ms, not rounded up to the next 25 ms tick


# ------------------------------------------------------------------ rule 3: MASTER never affects the kick light


def test_rule3_kick_ignores_master(engine, view):
    on = view.emitters("kick")
    assert on == [255, 128, 0]  # rig kick colour
    engine.set_master(False)
    assert view.emitters("kick") == on
    engine.set_master(True)
    assert view.emitters("kick") == on


def test_rule3_kick_follows_its_sub_master_and_blackout(engine, view):
    engine.set_sub(Kind.KICK, 0.5, instant=True)
    engine.tick()
    assert view("kick", "red") == 128
    engine.set_blackout(True)
    assert view.emitters("kick") == [0, 0, 0]  # panic blacks everything


def test_rule3_kick_is_not_flashed(engine, view):
    engine.set_master(False)
    engine.flash(["kick", "bar_1"], colour="white")
    assert view.emitters("kick") == [255, 128, 0]


# ------------------------------------------------------------------ rule 4: no background glow


def test_rule4_unlit_fixtures_fully_off(engine, view, patch):
    engine.set_look(parse_look({"fixtures": {"bar_1": {"colour": [1, 0, 0]}}}, patch))
    for fid in ("mh_a", "bar_2", "wash", "uk"):
        assert view.emitters(fid) == [0] * len(view.emitters(fid)), fid
    # non-light channels sit at their defaults, not at stray values
    assert view("mh_a", "strobe") == 7
    assert view("mh_a", "fixed") == 42


def test_rule4_unpatched_channels_are_zero(engine):
    patched = set()
    for fx in engine.rig.fixtures:
        patched |= {fx.slot(c) for c in fx.type.channels}
    frame = engine.frames[0]
    assert all(frame[i] == 0 for i in range(512) if i not in patched)


def test_rule4_master_off_only_kick_glows(engine, view):
    engine.set_master(False)
    for fx in engine.rig.fixtures:
        if fx.id not in ("kick",):
            assert set(view.emitters(fx.id)) <= {0}, fx.id


def test_rule4_look_gobo_not_applied_when_dark(engine, view):
    assert view("mh_a", "gobo") == 30
    engine.set_master(False)
    assert view("mh_a", "gobo") == 0  # back to default


# ------------------------------------------------------------------ rule 5: haze only from the haze controls


def test_rule5_looks_cannot_set_haze(patch):
    with pytest.raises(LookError, match="rule 5"):
        parse_look({"fixtures": {"smoke": {"haze": 1.0}}}, patch)
    with pytest.raises(LookError, match="rule 5"):
        parse_look({"haze": 1.0}, patch)


def test_rule5_haze_independent_of_everything_else(engine, view, patch):
    assert view("smoke", "haze") == 0
    engine.set_look(parse_look({"fixtures": {"all": {"colour": [1, 1, 1]}}}, patch))
    assert view("smoke", "haze") == 0  # "all" doesn't light the smoke machine
    engine.haze_toggle_manual()
    assert view("smoke", "haze") == 128
    engine.set_master(False)
    assert view("smoke", "haze") == 128
    engine.set_grand(0, instant=True)
    engine.tick()
    assert view("smoke", "haze") == 128
    engine.set_blackout(True)
    assert view("smoke", "haze") == 128
    engine.haze_stop()
    assert view("smoke", "haze") == 0


# ------------------------------------------------------------------ rule 6: grand master scales intensity only


def test_rule6_grand_master(engine, view):
    before = {r: view("mh_a", r) for r in ("pan", "tilt", "red", "gobo", "pt_speed")}
    engine.set_grand(0.5, instant=True)
    engine.haze_toggle_manual()
    engine.tick()
    assert view("mh_a", "dimmer") == 128  # dimmer fixtures: dimmer scaled
    assert {r: view("mh_a", r) for r in ("pan", "tilt", "red", "gobo", "pt_speed")} == before  # colour + position untouched
    assert view("bar_1", "green", 0) == 128  # no dimmer: RGB scaled
    assert view("smoke", "haze") == 128  # haze level 50 %, not scaled to 25 %


def test_rule6_sub_masters(engine, view):
    engine.set_sub("bar", 0.2, instant=True)
    engine.tick()
    assert view("bar_1", "green", 0) == 51
    assert view("mh_a", "dimmer") == 255


def test_rule6_grand_master_fades_smoothly(engine, view, clock):
    engine.set_grand(0.0)  # fade_s 0.4
    levels = []
    for _ in range(20):
        clock.advance(0.025)
        engine.tick()
        levels.append(view("wash", "dimmer"))
    assert levels[-1] == 0
    steps = [a - b for a, b in zip([255] + levels, levels)]
    assert max(steps) <= 17  # 255 * 0.025 / 0.4 ≈ 16 per tick, no jumps


def test_rule6_flash_follows_grand_master_and_flash_level(engine, view):
    engine.set_master(False)
    engine.set_grand(0.5, instant=True)
    engine.masters.flash.set(0.5, instant=True)
    engine.flash(["wash"], 127, "white")
    assert view("wash", "dimmer") == 64


# ------------------------------------------------------------------ rule 7: U'King colour only; speed 0 = fastest


def test_rule7_uking_rejects_position_in_look(patch):
    with pytest.raises(LookError, match="rule 7"):
        parse_look({"fixtures": {"uk": {"colour": [1, 0, 0], "pan": 0.9}}}, patch)
    with pytest.raises(LookError, match="rule 7"):
        parse_look({"fixtures": {"heads": {"tilt": 0.1}}}, patch)  # group containing a U'King


def test_rule7_uking_stays_home_even_if_forced(engine, view):
    lk = Look(fixtures={"uk": FixtureLook(colour={"red": 1.0}, pan=0.9, tilt=0.1, speed=0.0)})
    engine.set_look(lk)
    assert view("uk", "pan") == round(0.25 * 255)
    assert view("uk", "tilt") == round(0.75 * 255)
    assert view("uk", "red") == 255  # colour still works


def test_rule7_speed_zero_is_fastest(engine, view):
    assert view("mh_a", "pt_speed") == 0  # default: fastest
    engine.set_look(Look(fixtures={"mh_a": FixtureLook(colour={"red": 1.0}, speed=0.0)}))
    assert view("mh_a", "pt_speed") == 255  # slowest
    engine.set_look(Look(fixtures={"mh_a": FixtureLook(colour={"red": 1.0}, speed=1.0)}))
    assert view("mh_a", "pt_speed") == 0


# ------------------------------------------------------------------ rule 8: head limits always enforced


def test_rule8_limits_clamp(engine, view):
    engine.set_look(Look(fixtures={"mh_a": FixtureLook(colour={"red": 1.0}, pan=0.0, tilt=1.0)}))
    pan16 = view("mh_a", "pan") << 8 | view("mh_a", "pan_fine")
    tilt16 = view("mh_a", "tilt") << 8 | view("mh_a", "tilt_fine")
    assert pan16 == round(0.10 * 65535)
    assert tilt16 == round(0.75 * 65535)


def test_rule8_limits_apply_when_dark_and_on_flash(engine, view):
    engine.set_master(False)
    engine.set_look(Look(fixtures={"mh_a": FixtureLook(tilt=1.0)}))
    engine.flash(["mh_a"], colour="white")
    assert view("mh_a", "tilt") == round(0.75 * 65535) >> 8


# ------------------------------------------------------------------ positions


def test_heads_hold_position_and_move_dark(engine, view, patch):
    engine.set_look(Look(fixtures={"mh_a": FixtureLook(colour={}, pan=0.8)}))  # dark move
    assert view("mh_a", "dimmer") == 0
    assert view("mh_a", "pan") == round(0.8 * 65535) >> 8
    engine.set_look(Look(fixtures={"mh_a": FixtureLook(colour={"red": 1.0})}))  # no position: hold
    assert view("mh_a", "pan") == round(0.8 * 65535) >> 8


def test_missing_fixtures_skipped(patch, look, clock):
    from dmx_suite.rig import parse_rig

    small = parse_rig({"fixtures": ["bars", "kick"]}, patch)
    e = Engine(small, [LogDriver()], look, clock=clock)
    e.tick()  # look mentions heads and wash: ignored, no error
    assert e.frames[0][0] == 0  # mh_a's pan channel not driven
