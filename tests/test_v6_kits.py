"""v6 Part C: drum kits. The brief's acceptance tests: a kit learned pad by pad (unmapped notes flagged),
tempo and drum flash from the active kit with no other config, a trigger pad fires its scene, export /
import round trip. Plus: the view of a show without kits, the first-save migration (map backed up, flash
mappings moved), parsing, the GM template, gig lock, API and MCP."""

import shutil
from pathlib import Path

import mido
import pytest
import yaml

from dmx_suite.fixtures import ConfigError
from dmx_suite.kits import gm_kit, parse_kit
from dmx_suite.midi.named import parse_inputs
from dmx_suite.output import LogDriver
from dmx_suite.showfiles import load_show
from dmx_suite.store import LockedError

SHOWS = Path(__file__).resolve().parents[1] / "shows"


@pytest.fixture
def app(tmp_path):
    from dmx_suite.app import App

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    a = App(load_show(root), [LogDriver()], state_path=root / ".state.json")
    yield a
    a.engine.stop()


def note(app, n, vel=100, ch=10, port="TD-25"):
    return app.router.handle_mido(mido.Message("note_on", channel=ch - 1, note=n, velocity=vel), port)


def read(root, name):
    return yaml.safe_load((root / name).read_text())


# ---------------------------------------------------------------- the view and the migration


def test_show_without_kits_gets_band_kit_as_a_view(app):
    v = app.kit_view()
    assert v["derived"] and v["active"] == "band_kit"
    k = v["kits"]["band_kit"]
    assert k["channel"] == 10
    snare = k["pieces"]["snare"]["zones"]
    assert snare["head"]["notes"] == [38] and snare["rim"]["input"] == "snare_rim"
    assert snare["head"]["flash"]["fixtures"] == ["bars"]  # from the MIDI map
    assert k["pieces"]["hihat"]["zones"]["pedal"]["role"] == "count_in"
    assert "kits" not in read(app.files.root, "inputs.yaml")  # nothing written on load


def test_first_save_migrates_and_backs_up_the_map(app):
    root = app.files.root
    before_map = (root / "midi" / "default.yaml").read_text()
    r = app.set_kit_piece("band_kit", "snare", "head", {"weight": 0.9})
    ins, mp = read(root, "inputs.yaml"), read(root, "midi/default.yaml")
    assert ins["active_kit"] == "band_kit" and ins["kits"]["band_kit"]["pieces"]["snare"]["zones"]["head"]["weight"] == 0.9
    assert "td25" not in ins["devices"] and "fcb1010" in ins["devices"]  # drum inputs moved into the kit
    assert not any(m.get("action") == "flash" for m in mp["mappings"])  # the kit owns the flash targets now
    assert any(m.get("input") == "master" for m in mp["mappings"])  # everything else stays
    backup = root / ".backups" / r["backup"]
    assert (backup / "midi" / "default.yaml").read_text() == before_map  # backed up first
    # same input ids, same behaviour: the snare still flashes the bars
    m = app.files.midimap.get_input("snare")
    assert m is not None and m.action == "flash" and m.params["fixtures"] == ["bars"] and m.from_kit
    assert "snare" in app.files.inputs and app.files.inputs.get("snare").kit == "band_kit/snare/head"


def test_saving_the_midi_map_never_writes_kit_flashes(app):
    app.set_kit_piece("band_kit", "snare", "head", {"weight": 0.9})
    assert app.files.midimap.get_input("snare").from_kit
    assert not any(m.get("action") == "flash" for m in app.files.midimap.to_dict()["mappings"])


# ---------------------------------------------------------------- acceptance


def test_full_kit_learned_pad_by_pad_and_unmapped_flagged(app):
    app.new_kit("my_kit")
    app.set_active_kit("my_kit")
    # wipe the GM notes, then learn every zone by one hit each (a kit sending its own notes)
    kit = app._kit_data("my_kit")
    for p in kit["pieces"].values():
        for z in p["zones"].values():
            z["notes"] = []
    app.save_kit("my_kit", kit)
    zones = [(pid, zid) for pid, p in kit["pieces"].items() for zid in p["zones"]]
    for k, (pid, zid) in enumerate(zones):
        app.kit_learn("my_kit", pid, zid)
        note(app, 60 + k)
        assert app.kit_learning["result"].startswith(f"note {60 + k}"), app.kit_learning
    learned = app._kit_data("my_kit")
    assert all(z["notes"] == [60 + zones.index((pid, zid))] for pid, p in learned["pieces"].items()
               for zid, z in p["zones"].items())
    note(app, 100)  # a note nobody learned
    v = app.kit_view()
    assert [u["note"] for u in v["unmapped"]] == [100]
    note(app, 60)
    assert app.kit_view()["live"]  # the hit lights its pad


def test_tempo_and_flash_from_the_active_kit_only(app):
    app.new_kit("gm")
    app.set_kit_piece("gm", "snare", "head", {"flash": {"fixtures": ["bars"], "length_ms": 200}})
    app.set_active_kit("gm")
    assert app.files.midimap.get_input("snare").params["length_ms"] == 200
    tc = app.ctl.tempo
    tc.set_source("drums", app.engine.clock())
    tc.set_bpm(120, app.engine.clock())
    n0 = len(tc.tracker.onsets)
    note(app, 36)  # GM kick: a tempo onset from the kit's role
    assert len(tc.tracker.onsets) == n0 + 1 and tc.tracker.onsets[-1].role == "kick"
    app.engine.set_master(False)
    assert note(app, 38).startswith("flash")  # GM snare flashes the kit's target
    assert app.engine.flashes and set(app.engine.flashes) <= {f for f in app.engine.rig.present if f.startswith("bar")}


def test_zone_left_out_of_tempo_and_weight(app):
    app.new_kit("gm")
    app.set_kit_piece("gm", "ride", "bell", {"tempo": False})
    app.set_kit_piece("gm", "snare", "head", {"weight": 0.2, "velocity_floor": 60})
    app.set_active_kit("gm")
    tc = app.ctl.tempo
    tc.set_source("drums", app.engine.clock())
    tc.set_bpm(120, app.engine.clock())
    n0 = len(tc.tracker.onsets)
    note(app, 53)  # ride bell: not in tempo
    note(app, 38, vel=50)  # snare under its own floor
    assert len(tc.tracker.onsets) == n0
    note(app, 38, vel=90)
    assert tc.tracker.onsets[-1].w == pytest.approx(0.2)


def test_trigger_pad_fires_its_scene(app):
    scene = next(iter(app.files.scenes))
    app.new_kit("gm")
    app.set_kit_piece("gm", "pad_1", "head", {"notes": [70], "role": "trigger_only", "trigger": {"scene": scene}})
    app.set_active_kit("gm")
    note(app, 70)
    assert app.engine.scene is not None and app.engine.scene.name == app.files.scenes[scene].name


def test_export_import_round_trip(app, tmp_path):
    from dmx_suite.app import App

    app.new_kit("gm")
    app.set_kit_piece("gm", "snare", "rim", {"notes": [40, 39], "flash": {"fixtures": ["washes"], "colour": "white"}})
    text = app.export_kit("gm")
    other = tmp_path / "other"
    shutil.copytree(SHOWS, other, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    b = App(load_show(other), [LogDriver()], state_path=other / ".state.json")
    try:
        b.import_kit(text, activate=True)
        assert b._kit_data("gm") == app._kit_data("gm")
        assert b.files.inputs.get("snare_rim").numbers == [40, 39]
        assert b.files.midimap.get_input("snare_rim").params["fixtures"] == ["washes"]
    finally:
        b.engine.stop()


# ---------------------------------------------------------------- parsing, template, locks, API, MCP


def test_parse_and_validate():
    k = parse_kit("k", {"channel": 10, "pieces": {"snare": {"zones": {"head": {"notes": [38], "role": "snare"},
                                                                     "rim": {"notes": 40, "role": "count-in"}}}}})
    assert k.pieces["snare"].zones["rim"].input == "snare_rim" and k.pieces["snare"].zones["rim"].role == "count_in"
    for bad in ({"pieces": {"x": {"zones": {"head": {"role": "cowbell"}}}}},
                {"pieces": {"x": {"zones": {"head": {"notes": [200]}}}}},
                {"pieces": {"x": {"zones": {"head": {"flash": {"colour": "red"}}}}}},
                {"pieces": {"x": {"zones": {"head": {"trigger": {"show": "a"}}}}}},
                {"channel": 17}):
        with pytest.raises(ConfigError):
            parse_kit("k", bad)
    with pytest.raises(ConfigError, match="active_kit"):
        parse_inputs({"kits": {"a": {"pieces": {}}}, "active_kit": "b"})


def test_only_the_active_kit_makes_inputs_and_roles():
    data = {"kits": {"a": gm_kit("a").to_dict(), "b": gm_kit("b").to_dict()}, "active_kit": "b"}
    ins = parse_inputs(data)
    kick = ins.get("kick")
    assert kick.device == "b" and kick.roles == ["kick", "activity"] and kick.channel == 10
    assert ins.get("hihat_pedal").roles == ["count_in", "activity"] and "tap_pad" not in ins  # tap pad: no note yet
    assert ins.to_dict()["kits"] == data["kits"] and "b" not in ins.to_dict()["devices"]


def test_gig_lock(app):
    app.set_gig_lock(True)
    with pytest.raises(LockedError):
        app.kit_learn("band_kit", "snare", "head")
    with pytest.raises(LockedError):
        app.set_kit_piece("band_kit", "snare", "head", {"weight": 0.5})
    app.set_gig_lock(False)


def test_api_and_mcp(app):
    from test_web import CLAUDE, TOKEN, call

    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.web.server import WebServer

    web = WebServer(app, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    try:
        url = f"http://127.0.0.1:{web.port}"
        assert call(f"{url}/api/kits")[1]["active"] == "band_kit"
        assert call(f"{url}/api/kits", "POST", {"action": "new", "kit": "gm"})[0] == 200
        t = DmxTools(shows=app.files.root, url=url, token=CLAUDE)
        assert yaml.safe_load(t.list_kits())["kits"]["gm"]["pieces"] >= 13
        assert t.set_kit_piece("gm", "kick", "head", notes="35 36", flash_yaml="{fixtures: [kick]}").startswith("saved")
        assert t.set_active_kit("gm").startswith("active kit gm")
        k = yaml.safe_load(t.get_kit())
        assert k["kit"] == "gm" and k["pieces"]["kick"]["zones"]["head"]["notes"] == [35, 36]
        r = yaml.safe_load(t.kit_learn_status("gm", "tom_1", "rim", arm=True))
        assert r["armed"] and r["piece"] == "tom_1"
        note(app, 50)
        assert "note 50" in yaml.safe_load(t.kit_learn_status())["result"]
        assert call(f"{url}/api/kits/export?kit=gm")[1]["yaml"].startswith("kit: gm")
    finally:
        web.stop()


def test_mcp_registers_kit_tools():
    pytest.importorskip("mcp")
    import asyncio

    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.mcp_server import build_server

    names = {x.name for x in asyncio.run(build_server(DmxTools(shows=SHOWS)).list_tools())}
    assert {"list_kits", "get_kit", "set_kit_piece", "set_active_kit", "kit_learn_status"} <= names
