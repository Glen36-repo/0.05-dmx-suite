"""Head position points (v3.1): per-rig named aim points with descriptions, tags and per-head
pan/tilt; scenes name them; re-aiming one moves every scene; missing heads stay put with a
warning; head limits and colour-only heads are respected."""

import shutil
from pathlib import Path

import pytest
from rulecheck import rule_matrix

from dmx_suite.fixtures import ConfigError, parse_patch
from dmx_suite.palettes import Palettes
from dmx_suite.rig import parse_rig
from dmx_suite.scenes import ScenePlayer, parse_scene
from dmx_suite.showfiles import check_all, load_show
from dmx_suite.store import ShowStore, StoreError

from conftest import PATCH, RIG

SHOWS = Path(__file__).resolve().parents[1] / "shows"

POINTS = {
    "kit": {"description": "Drum kit", "tags": ["band", "safe"], "stage": {"x": "centre", "y": "back", "z": "mid"},
            "heads": {"mh_a": {"pan": 0.4, "tilt": 0.3}}},
    "crowd": {"tags": ["audience"], "heads": {"mh_a": {"pan": 0.8, "tilt": 0.9}}},  # tilt above the 75 % limit
}


@pytest.fixture
def prig():
    return parse_rig({**RIG, "positions": POINTS}, parse_patch(PATCH))


def test_parse_points(prig):
    kit = prig.points["kit"]
    assert kit.heads == {"mh_a": (0.4, 0.3)} and kit.tags == ["band", "safe"] and kit.stage["y"] == "back"
    assert kit.to_dict()["heads"] == {"mh_a": {"pan": 0.4, "tilt": 0.3}}


def test_out_of_limit_point_is_a_warning_not_an_error(prig):
    assert prig.point_problems() == [
        "point crowd: mh_a is outside its head limits (pan 80%, tilt 90%); it's held at the limit (rule 8): re-aim it"]


@pytest.mark.parametrize("bad, msg", [
    ({"p": {"heads": {"uk": {"pan": 0.5, "tilt": 0.5}}}}, "colour only"),
    ({"p": {"heads": {"bar_1": {"pan": 0.5, "tilt": 0.5}}}}, "no pan/tilt"),
    ({"p": {"heads": {"nope": {"pan": 0.5, "tilt": 0.5}}}}, "unknown fixture"),
    ({"p": {"heads": {"mh_a": {"pan": 1.5, "tilt": 0.5}}}}, "0-1"),
    ({"p": {"heads": {"mh_a": {"pan": 0.5}}}}, "needs pan and tilt"),
    ({"p": {"stage": {"x": "middle"}}}, "stage x"),
    ({"p": {"tags": "x", "colour": 1}}, "description, tags"),
    ({"Bad": {}}, "lower case"),
])
def test_bad_points(bad, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_rig({**RIG, "positions": bad}, parse_patch(PATCH))


def test_missing_head_stays_put_with_a_warning():
    two = {**PATCH, "fixtures": [*PATCH["fixtures"], {"id": "mh_b", "type": "head", "address": 80}]}
    patch = parse_patch(two)
    r = parse_rig({**RIG, "positions": POINTS}, patch)
    pal = Palettes().with_points(r.points)
    sc = parse_scene({"layers": [{"fixtures": ["mh_a", "mh_b"], "position": "kit"}]}, patch, pal, "s")
    assert sc.layers[0].params["position"] == {"mh_a": (0.4, 0.3)}
    assert any("isn't set for mh_b" in w for w in pal.warnings)
    look = ScenePlayer(sc, r, 0.0)(0.0)
    assert look.fixtures["mh_a"].pan == 0.4 and look.fixtures["mh_b"].pan is None  # mh_b holds position


def test_unknown_point_is_an_error(prig):
    with pytest.raises(Exception, match="unknown position"):
        parse_scene({"layers": [{"fixtures": ["mh_a"], "position": "nowhere"}]}, prig.patch,
                    Palettes().with_points(prig.points), "s")


def test_point_only_another_rig_has_loads_with_warning(prig):
    other = parse_rig({**RIG, "positions": {"singer": {"heads": {"mh_a": {"pan": 0.5, "tilt": 0.5}}}}}, prig.patch)
    pal = Palettes().with_points(prig.points, other.points)
    sc = parse_scene({"layers": [{"fixtures": ["mh_a"], "position": "singer"}]}, prig.patch, pal, "s")
    assert sc.layers[0].params["position"] == {}
    assert pal.warnings and pal.point_info["singer"]["tags"] == []


# ------------------------------------------------------------------ the shipped shows and the store


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    return ShowStore(root)


def test_shipped_points():
    files = load_show(SHOWS)
    kit = files.rig.points["drum_kit"]
    assert kit.description and "band" in kit.tags
    assert files.palettes.positions["drum_kit"]["mh_a"] == (0.42, 0.3)
    assert files.palettes.point_info["drum_kit"]["stage"]["y"] == "back"
    small = load_show(SHOWS, rig="small")
    assert small.rig.points == {}


def test_reaiming_a_point_moves_every_scene_using_it(store):
    before = load_show(store.root).scenes
    users = [k for k, sc in before.items() if any(ly.params.get("position", {}).get("mh_a") == (0.42, 0.3)
                                                    for ly in sc.layers)]
    assert users, "a shipped scene aims at drum_kit"
    store.put_point("full", "drum_kit", {"heads": {"mh_a": {"pan": 0.45, "tilt": 0.35}}}, merge=True)
    after = load_show(store.root)
    for k in users:
        assert any(ly.params.get("position", {}).get("mh_a") == (0.45, 0.35) for ly in after.scenes[k].layers)
    assert after.rig.points["drum_kit"].heads["mh_b"] == (0.58, 0.3)  # merge kept mh_b
    assert after.rig.points["drum_kit"].description  # and the description


def test_store_refuses_a_point_in_the_no_go_zone(store):
    with pytest.raises(StoreError, match="rule 8"):
        store.put_point("full", "high", {"heads": {"mh_a": {"pan": 0.5, "tilt": 0.9}}})  # MH-A tilt limit 75 %
    store.put_point("full", "high", {"heads": {"mh_b": {"pan": 0.5, "tilt": 0.9}}})  # mh_b has no tilt limit


def test_limit_change_rechecks_points(store):
    rig = store.read("rig", "full")
    rig["head_limits"]["mh_b"] = {"pan": [0, 100], "tilt": [0, 50]}
    store.put("rig", "full", rig)
    warnings = [p for p in check_all(store.root) if "outside its head limits" in p]
    assert any("mh_b" in w and "drum_kit" not in w for w in warnings)


def test_rename_and_delete_points(store):
    store.rename_point("drum_kit", "kit")
    files = load_show(store.root)
    assert "kit" in files.rig.points and "drum_kit" not in files.rig.points
    assert any("kit" in (store.read("scene", n).__repr__()) for n in store.names("scene"))
    with pytest.raises(StoreError, match="still used"):
        store.delete_point("full", "kit")
    store.put_point("full", "spare", {"heads": {"mh_a": {"pan": 0.5, "tilt": 0.5}}})
    store.delete_point("full", "spare")
    assert "spare" not in load_show(store.root).rig.points


def test_points_are_per_rig(store):
    store.put_point("full", "singer", {"description": "Lead vocal", "heads": {"mh_a": {"pan": 0.5, "tilt": 0.4}}})
    assert "singer" in load_show(store.root, rig="full").rig.points
    assert "singer" not in load_show(store.root, rig="small").rig.points


def test_16_bit_points(engine, view):
    """A point at a fine value lands on both coarse and fine channels."""
    r = parse_rig({**RIG, "positions": {"p": {"heads": {"mh_a": {"pan": 0.43219, "tilt": 0.31234}}}}}, engine.rig.patch)
    pal = Palettes().with_points(r.points)
    sc = parse_scene({"layers": [{"fixtures": ["mh_a"], "position": "p", "colour": "white"}]}, r.patch, pal, "s")
    engine.set_scene(sc)
    engine.tick()
    v = ((view("mh_a", "pan") << 8) | view("mh_a", "pan_fine")) / 65535
    assert v == pytest.approx(0.43219, abs=1 / 65535)


def test_points_keep_every_rule():
    pts = {"kit": {"heads": {"mh_a": {"pan": 0.4, "tilt": 0.3}}}, "up": {"heads": {"mh_a": {"pan": 0.5, "tilt": 0.99}}}}

    def aim(e, clock):
        r = parse_rig({**RIG, "positions": pts}, e.rig.patch)
        pal = Palettes().with_points(r.points)
        sc = parse_scene({"layers": [{"fixtures": ["mh_a"], "position": "up", "colour": "white"},
                                     {"fixtures": ["mh_a"], "effect": "sweep", "from": "kit", "to": "up", "period_s": 1}]},
                         r.patch, pal, "s")
        e.set_scene(sc)

    rule_matrix(aim, seconds=1.5, unused=("bar_1", "bar_2", "wash"))
