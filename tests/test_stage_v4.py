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
