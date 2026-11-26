"""Busking: panels, overrides over the show, release fades, the rules, MIDI/OSC and the API."""

import shutil
from pathlib import Path

import pytest
import yaml

from dmx_suite.app import App
from dmx_suite.busk import parse_panels
from dmx_suite.fixtures import ConfigError
from dmx_suite.midi.inputs import FakeMidiIn
from dmx_suite.output import LogDriver
from dmx_suite.showfiles import check_all, load_show

from conftest import Clock

SHOWS = Path(__file__).resolve().parents[1] / "shows"

PANELS = {"panels": {"band": {"name": "Band busk", "release_fade_s": 1.0, "widgets": [
    {"id": "red", "type": "colour", "label": "All red", "fixtures": ["bars", "washes"], "colour": "red"},
    {"id": "hit", "type": "flash", "label": "White hit", "fixtures": ["bars"], "colour": "white"},
    {"id": "solo", "type": "solo", "label": "Heads only", "fixtures": ["movers"]},
    {"id": "fx", "type": "effect", "label": "Chase", "scene": "blue_chase"},
    {"id": "go", "type": "go", "label": "High", "show": "band", "set": "high"},
    {"id": "gm", "type": "fader", "label": "Grand", "target": "grand"},
    {"id": "spd", "type": "fader", "label": "Speed", "target": "speed"},
    {"id": "boost", "type": "haze", "label": "Boost", "action": "boost"},
]}}}


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "shows"
    shutil.copytree(SHOWS, r, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    (r / "panels.yaml").write_text(yaml.safe_dump({"version": 3, **PANELS}), encoding="utf-8")
    return r


@pytest.fixture
def app(root):
    clock = Clock()
    a = App(load_show(root, "full"), [LogDriver()], clock=clock)
    a.clock = clock
    a.engine.tick()
    return a


def chans(app, fid, roles=("red", "green", "blue")):
    fx = app.engine.rig.patch.fixtures[fid]
    frame = app.engine.frames[fx.universe]
    return [frame[fx.slot(c)] for c in fx.type.channels if c.role in roles]


def test_panels_parse_and_check(root):
    sf = load_show(root, "full")
    p = sf.panels["band"]
    assert [w.id for w in p.widgets] == ["red", "hit", "solo", "fx", "go", "gm", "spd", "boost"]
    assert p.widget("red").fixtures == ["bar_1", "bar_2", "bar_3", "bar_4", "wash_l", "wash_r"]
    assert [x for x in check_all(root) if not x.startswith("warning")] == []


@pytest.mark.parametrize("w, msg", [
    ({"id": "x", "type": "laser"}, "type must be"),
    ({"id": "bad id!", "type": "solo", "fixtures": ["bars"]}, "id must be"),
    ({"id": "x", "type": "solo"}, "needs fixtures"),
    ({"id": "x", "type": "go"}, "needs a scene or a show"),
    ({"id": "x", "type": "fader", "target": "volume"}, "target must be"),
    ({"id": "x", "type": "haze", "action": "max"}, "action must be"),
    ({"id": "x", "type": "colour", "fixtures": ["nope"]}, "unknown fixture"),
])
def test_bad_widgets(root, w, msg):
    sf = load_show(root, "full")
    with pytest.raises(ConfigError, match=msg):
        parse_panels({"panels": {"p": {"widgets": [w]}}}, sf.patch, sf.palettes, sf.scenes, sf.shows)


def test_colour_latch_and_release_back_to_the_show_exactly(app):
    before = {u: bytes(f) for u, f in app.engine.frames.items()}
    assert app.busk("band", "red") == "All red on"
    assert chans(app, "bar_1")[:3] == [255, 0, 0] and chans(app, "wash_l")[0] == 255
    assert app.snapshot()["busk"]["lights"]["bar_1"] == ["band/red"]
    assert app.busk("band", "red") == "All red off"  # latch: a second press lets go, fading over 1 s
    app.clock.advance(0.5)
    app.engine.tick()
    assert 0 < chans(app, "bar_1")[0] < 255  # half way back
    app.clock.advance(0.6)
    app.engine.tick()
    assert {u: bytes(f) for u, f in app.engine.frames.items()} == before  # exactly the show again
    assert app.engine.overrides == []


def test_flash_is_held_and_drops_straight_away(app):
    app.busk("band", "hit", down=True)
    assert set(chans(app, "bar_3")) == {255}
    app.busk("band", "hit", down=False)
    assert chans(app, "bar_3") != [255] * len(chans(app, "bar_3"))


def test_solo_darkens_the_rest_but_not_the_kick(app):
    kick = chans(app, "kick")
    app.busk("band", "solo", down=True)
    assert set(chans(app, "bar_1")) == {0} and set(chans(app, "wash_l")) == {0}  # rule 4: dark is fully off
    assert chans(app, "mh_a", ("dimmer",)) == [255]
    assert chans(app, "kick") == kick  # rule 3: the kick light keeps its own rules
    app.busk("band", "solo", down=False)


def test_overrides_dont_beat_master(app):
    app.engine.set_master(False)
    app.busk("band", "red")
    assert set(chans(app, "bar_1")) == {0}  # rule 1: MASTER owns on/off under the 0.05 profile


def test_effect_go_fader_and_haze(app):
    app.busk("band", "fx")
    assert any(o.kind == "effect" for o in app.engine.held())
    app.busk("band", "fx")
    assert app.busk("band", "go").startswith("Main band show / high")
    app.busk("band", "gm", level=0.3)
    assert app.engine.masters.grand.target == pytest.approx(0.3)
    app.busk("band", "spd", level=1.0)
    assert app.ctl.tempo.speed == pytest.approx(4)
    assert app.busk("band", "boost", down=True).endswith("on")
    app.busk("band", "boost", down=False)


def test_release_all(app):
    app.busk("band", "red")
    app.busk("band", "solo", down=True)
    app.engine.release_all(0)
    assert app.engine.overrides == [] and app.snapshot()["busk"]["held"] == []


def test_busk_from_midi(app, root):
    from dmx_suite.midi.map import Mapping

    app.router.map.add(Mapping("note", 1, 60, "busk", {"panel": "band", "widget": "hit"}))
    midi = FakeMidiIn(app.router.handle_mido)
    midi.note(60, 100, channel=1)
    assert set(chans(app, "bar_1")) == {255}
    midi.note_off(60, channel=1)
    assert app.engine.held() == []
    assert app.router.handle_osc("/nothing", []) == "unmapped"


def test_busk_mapping_must_name_a_real_widget(root):
    midi = root / "midi" / "default.yaml"
    midi.write_text(midi.read_text(encoding="utf-8")
                    + "  - {type: note, channel: 1, number: 61, action: busk, panel: band, widget: nope}\n", encoding="utf-8")
    assert any("no widget 'nope'" in p for p in check_all(root))
    with pytest.raises(ConfigError):
        load_show(root, "full")
