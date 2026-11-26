import pytest

from dmx_suite.setup import format_report, patch_report


def test_find_lights_one_fixture_regardless_of_master(engine, view):
    engine.set_master(False)
    engine.find_fixture("wash")
    assert view("wash", "dimmer") == 255
    assert [view("wash", r) for r in ("red", "green", "blue")] == [255, 255, 255]
    for fid in ("mh_a", "bar_1", "uk", "kick"):
        assert set(view.emitters(fid)) == {0}, fid  # everything else dark, even the kick light
    engine.find_fixture(None)
    assert view("wash", "dimmer") == 0  # back to MASTER off


def test_find_ignores_grand_master_but_keeps_head_limits(engine, view):
    engine.set_grand(0, instant=True)
    engine.find_fixture("mh_a")
    assert view("mh_a", "dimmer") == 255
    assert view("mh_a", "tilt") <= round(0.75 * 65535) >> 8


def test_find_refuses_haze_and_absent(engine):
    with pytest.raises(ValueError, match="rule 5"):
        engine.find_fixture("smoke")
    with pytest.raises(ValueError):
        engine.find_fixture("nope")


def test_channel_tester(engine):
    engine.test_channel(100, 77)
    assert engine.frames[0][99] == 77
    engine.tick()
    assert engine.frames[0][99] == 77  # held until cleared
    engine.test_channel(100, None)
    assert engine.frames[0][99] == 0
    engine.test_channel(101, 5)
    engine.clear_setup()
    assert engine.frames[0][100] == 0


def test_channel_tester_refuses_haze_channel(engine):
    with pytest.raises(ValueError, match="rule 5"):
        engine.test_channel(70, 255)  # smoke at address 70
    with pytest.raises(ValueError):
        engine.test_channel(513, 1)
    with pytest.raises(ValueError):
        engine.test_channel(1, 256)


def test_patch_report(patch, rig):
    rows, notes = patch_report(patch, rig)
    assert [r.id for r in rows][:2] == ["mh_a", "bar_1"]
    assert rows[0].start == 1 and rows[0].end == 12
    assert any("gap 13-19 before bar_1" in n for n in notes)
    assert any("unverified" in n for n in notes)
    assert "mh_a" in format_report(rows, notes)
