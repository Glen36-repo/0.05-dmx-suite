"""v4 stage view, backend side: haze off the stage, overlapping positions, layout z / reverse."""

import shutil
from pathlib import Path

import screenshot_rig

from dmx_suite.scenes import Scene, ScenePlayer, parse_scene
from dmx_suite.showfiles import load_show

SHOWS = Path(__file__).resolve().parents[1] / "shows"


def shot_show(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    return load_show(screenshot_rig.make(root)), root


def test_spatial_effects_never_include_the_haze_machine(tmp_path):
    files, _ = shot_show(tmp_path)
    scene: Scene = parse_scene({"name": "w", "layers": [{"fixtures": ["all"], "effect": "linear_wave", "colour": "red"}]},
                               files.patch, files.palettes, "w")
    player = ScenePlayer(scene, files.rig, start=0.0)
    ids = {u.fid for u in player._units_for(0, True)}
    assert "smoke" not in ids and {"bar_1", "par_1", "mh_a"} <= ids


def test_overlaps_and_touching_lights_are_flagged(tmp_path):
    from dmx_suite.layout import layout_problems
    from dmx_suite.showfiles import check_all

    files, root = shot_show(tmp_path)
    ps = {(p["a"], p["b"]): p["kind"] for p in layout_problems(files.rig)}
    pairs = {frozenset(k): v for k, v in ps.items()}
    assert pairs[frozenset({"mh_a", "par_1"})] == "overlap" and pairs[frozenset({"mh_b", "par_4"})] == "overlap"
    assert pairs[frozenset({"bar_1", "bar_2"})] == "close"  # end to end
    assert not any("smoke" in k for k in pairs)  # haze isn't on the stage
    warn = [w for w in check_all(root) if "layout:" in w]
    assert any("mh_a and par_1 are in the same place" in w or "par_1 and mh_a" in w for w in warn)
    assert all(w.startswith("warning:") for w in warn)  # never blocks a save


def test_default_layout_has_no_problems(tmp_path):
    from dmx_suite.layout import layout_problems

    files = load_show(SHOWS)
    assert layout_problems(files.rig) == []


def test_overlaps_raise_an_alert(tmp_path):
    from dmx_suite.app import App
    from dmx_suite.output import LogDriver

    files, _ = shot_show(tmp_path)
    app = App(files, [LogDriver()])
    tile = next(d for d in app.devices() if d["kind"] == "layout")
    assert tile["state"] == "warn" and "mh_a/par_1" in tile["detail"]
    view = app.alerts_view()
    assert any(a["kind"] == "layout" and a["severity"] == "warning" for a in view["list"])
