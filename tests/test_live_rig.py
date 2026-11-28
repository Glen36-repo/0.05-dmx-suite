"""R7: fixture and rig changes apply live, and rigs switch without a restart."""

import shutil
from pathlib import Path

import pytest

from dmx_suite.app import App
from dmx_suite.output import LogDriver
from dmx_suite.showfiles import load_show
from dmx_suite.store import LockedError

SHOWS = Path(__file__).resolve().parents[1] / "shows"


@pytest.fixture
def app(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    a = App(load_show(root), [LogDriver()])
    a.ctl.select_show("band", "mid")
    yield a
    a.engine.stop()


def _fixtures(app):
    return app.store.read("fixtures")


def test_moving_a_fixture_applies_live(app):
    data = _fixtures(app)
    entry = next(f for f in data["fixtures"] if f["id"] == "mh_a")  # lit by the static look
    old = entry["address"]
    entry["address"] = 300
    app.store.put_fixture(entry)
    notes = app.reload()
    assert any("updated live" in n for n in notes) and not any("restart" in n for n in notes)
    assert app.engine.rig.patch.fixtures["mh_a"].address == 300 != old
    assert app.ctl.show.key == "band" and app.ctl.set_name == "mid"  # still playing the same set
    app.ctl.select_look()
    app.engine.set_master(True)
    frames = app.engine.output()
    fx = app.engine.rig.patch.fixtures["mh_a"]
    assert any(frames[fx.universe][fx.address - 1:fx.address - 1 + fx.type.footprint])  # lit at the new address


def test_rig_settings_apply_live(app):
    rig = app.store.read("rig", "full")
    rig["profile"] = "generic"
    rig["haze"] = {**(rig.get("haze") or {}), "level": 40}
    app.store.put("rig", "full", rig)
    app.reload()
    assert not app.engine.rig.profile.master_gate  # generic
    assert app.engine.haze.cfg.level == pytest.approx(0.4)


def test_heads_hold_position_across_a_swap(app):
    e = app.engine
    e.rules.position["mh_a"] = (0.3, 0.4)
    e.swap_rig(app.files.rig, app.files.look)
    assert e.rules.position["mh_a"] == (0.3, 0.4)


def test_output_changes_apply_without_a_restart(app):
    # v4: outputs are rebuilt live (test_rebuild.py); the simulator's own outputs are left alone
    rig = app.store.read("rig", "full")
    rig["outputs"] = [{"driver": "log"}]
    app.store.put("rig", "full", rig)
    notes = app.reload()
    assert not any("after a restart" in n for n in notes)
    assert any("simulator" in n for n in notes)
    assert app.engine.rig.outputs == [{"driver": "log"}]


def test_scene_edits_dont_restart_the_show(app):
    app.ctl.next_step()
    step = app.ctl.player.step
    scene = app.store.read("scene", "opera")
    scene["name"] = "Opera (edited)"
    app.store.put("scene", "opera", scene)
    app.reload()
    assert app.ctl.player.step == step  # the rig didn't change: nothing rebuilt


def test_switch_rig_live(app):
    assert len(app.engine.rig.present) > 3
    notes = app.switch_rig("small")
    assert app.names[0] == "small" and app.engine.rig.name == app.files.rig.name
    assert set(app.engine.rig.present) <= set(app.files.patch.fixtures) and "mh_a" not in app.engine.rig.present
    assert notes
    with pytest.raises(ValueError, match="no rig"):
        app.switch_rig("nope")
    app.set_gig_lock(True)
    with pytest.raises(LockedError):
        app.switch_rig("full")


def test_removing_a_fixture_drops_what_aimed_at_it(app):
    app.engine.position_override["uking_l"] = (0.5, 0.5)
    rig = app.store.read("rig", "full")
    rig["fixtures"] = ["bars", "washes", "kick", "smoke", "movers"]
    app.store.put("rig", "full", rig)
    app.reload()
    assert "uking_l" not in app.engine.rig.present and "uking_l" not in app.engine.position_override
    app.engine.output()  # renders fine without it


def test_patch_save_and_fixture_removal_across_rigs(app):
    data = app.store.read("fixtures")
    rows = data["fixtures"]
    rows.append({"id": "par_1", "type": "starcolor72", "universe": 0, "address": 400})
    app.store.put_patch(rows)
    app.reload()
    assert "par_1" in app.engine.rig.patch.fixtures
    rig = app.store.read("rig", "full")
    rig.setdefault("head_limits", {})["uking_r"] = {"pan": [5, 95]}
    app.store.put("rig", "full", rig)
    app.store.remove_fixture("par_1")
    assert "par_1" not in {f["id"] for f in app.store.read("fixtures")["fixtures"]}
    with pytest.raises(Exception, match="no fixture"):
        app.store.remove_fixture("par_1")
    # a light a scene names directly can't go: the scene must change first
    with pytest.raises(Exception, match="rejected"):
        app.store.remove_fixture("mh_a")
    app.store.remove_fixture("uking_r")  # used only through groups: goes, and leaves the rigs too
    rig = app.store.read("rig", "full")
    assert "uking_r" not in (rig.get("head_limits") or {}) and "uking_r" not in (rig.get("layout") or {})


def test_overlapping_patch_refused(app):
    rows = app.store.read("fixtures")["fixtures"]
    rows.append({"id": "clash", "type": "starcolor72", "universe": rows[0].get("universe", 0), "address": rows[0]["address"]})
    with pytest.raises(Exception, match="overlaps"):
        app.store.put_patch(rows)


def test_files_rev_goes_up_on_every_change(app):
    """Open screens fetch the names and layout again when this changes (the live feed carries it)."""
    revs = [app.snapshot()["files_rev"]]
    lay = app.catalogue()["layout"]
    app.save_layout({**lay, "wash_l": {**lay["wash_l"], "x": lay["wash_l"]["x"] + 2}})
    revs.append(app.snapshot()["files_rev"])
    app.set_positions({"wash_r": {"x": 3, "y": 3}})
    revs.append(app.snapshot()["files_rev"])
    app.store.undo()
    app.reload()
    revs.append(app.snapshot()["files_rev"])
    app.switch_rig("small")
    revs.append(app.snapshot()["files_rev"])
    assert revs == sorted(set(revs)), revs  # strictly up every time
