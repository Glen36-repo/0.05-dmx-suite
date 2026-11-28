import shutil
from pathlib import Path

import pytest
import yaml

from dmx_suite.store import LockedError, ShowStore, StoreError
from dmx_suite.yamlio import keep_layout, update_text

SHOWS = Path(__file__).resolve().parents[1] / "shows"


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    return ShowStore(root)


GOOD = {"name": "Teal", "layers": [{"fixtures": ["bars"], "colour": "#00a090"}]}


def test_put_new_scene_and_backup_note(store):
    bid = store.put("scene", "teal", GOOD)
    assert store.read("scene", "teal")["name"] == "Teal"
    b = store.backups()[0]
    assert b["id"] == bid and "put scene teal" in b["note"]


def test_put_replaces_and_keeps_previous_version(store):
    before = store.read_text("scene", "opera")
    bid = store.put("scene", "opera", GOOD)
    backup = store.root / ".backups" / bid / "scenes" / "opera.yaml"
    assert backup.read_text() == before
    store.restore(bid, "scenes/opera.yaml")
    assert store.read_text("scene", "opera") == before


@pytest.mark.parametrize(
    "data, why",
    [
        ({"layers": [{"fixtures": ["bars"], "dimmer": 1}]}, "rule 1"),
        ({"layers": [{"fixtures": ["smoke"], "haze": 1}]}, "rule 5"),
        ({"layers": [{"fixtures": ["ukings"], "position": "centre"}]}, "rule 7"),
        ({"layers": [{"fixtures": ["nope"], "colour": "red"}]}, "unknown fixture"),
        ({"layers": [{"fixtures": ["bars"], "colour": "chartreuse"}]}, "unknown colour"),
    ],
)
def test_bad_scenes_rejected_and_nothing_written(store, data, why):
    with pytest.raises(StoreError, match=why):
        store.put("scene", "bad", data)
    assert not (store.root / "scenes" / "bad.yaml").exists()
    assert not store.backups()


def test_delete_refused_while_referenced(store):
    with pytest.raises(StoreError, match="unknown scene 'blue_chase'"):
        store.delete("scene", "blue_chase")  # used by band show + example setlist
    store.put("scene", "spare", GOOD)
    store.delete("scene", "spare")
    assert "spare" not in store.names("scene")


def test_palette_change_that_breaks_a_scene_is_rejected(store):
    with pytest.raises(StoreError, match="still used: scenes/"):
        store.put_entry("palettes", "colours", "blue", None)  # scenes use blue
    store.put_entry("palettes", "colours", "teal", "#00a090")
    assert yaml.safe_load((store.root / "palettes.yaml").read_text())["colours"]["teal"] == "#00a090"


def test_duplicate(store):
    store.duplicate("scene", "opera", "opera_two")
    assert store.read("scene", "opera_two")["name"] == "Opera (copy)"
    with pytest.raises(StoreError, match="already exists"):
        store.duplicate("scene", "opera", "opera_two")


def test_fixture_type_and_patch(store):
    store.put_entry("fixtures", "types", "par", {"kind": "wash", "channels": ["dimmer", "red", "green", "blue"]})
    store.put_fixture({"id": "par_1", "type": "par", "address": 300, "groups": ["washes"]})
    data = yaml.safe_load((store.root / "fixtures.yaml").read_text())
    assert any(f["id"] == "par_1" for f in data["fixtures"])
    with pytest.raises(StoreError, match="overlaps"):
        store.put_fixture({"id": "par_2", "type": "par", "address": 301})


def test_names_are_checked(store):
    for bad in ("../escape", "Upper", "a b", "x" * 41, ""):
        with pytest.raises(StoreError, match="bad name"):
            store.put("scene", bad, GOOD)
    with pytest.raises(StoreError):
        store.restore("../..", "fixtures.yaml")


def test_gig_lock_blocks_writes(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    s = ShowStore(root, locked=lambda: True)
    with pytest.raises(LockedError):
        s.put("scene", "teal", GOOD)
    assert s.read("scene", "opera")  # reads still fine


def test_yaml_text_accepted(store):
    store.put("scene", "teal", "name: Teal\nlayers:\n  - {fixtures: [bars], colour: blue}\n")
    with pytest.raises(StoreError, match="YAML"):
        store.put("scene", "teal", "layers: [unclosed")


# ------------------------------------------------------------------ comments and layout survive saves (v2 R1)



def test_every_shipped_file_round_trips_unchanged():
    for p in sorted(SHOWS.rglob("*.yaml")):
        text = p.read_text(encoding="utf-8")
        assert update_text(text, yaml.safe_load(text)) == text, p


def test_edit_keeps_comments_and_alignment():
    text = (SHOWS / "fixtures.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    data["fixtures"][2]["address"] = 28
    out = update_text(text, data)
    changed = [ln for ln in out.splitlines() if ln not in text.splitlines()]
    assert changed == ["  - {id: bar_1, type: lcb803, address: 28, groups: [bars]}"]
    assert "  - {id: bar_2,    type: lcb803,      address: 51,  groups: [bars]}" in out  # spacing kept
    assert [ln for ln in text.splitlines() if ln.lstrip().startswith("#")] == \
        [ln for ln in out.splitlines() if ln.lstrip().startswith("#")]
    assert yaml.safe_load(out) == data


@pytest.mark.parametrize("value", ["off", "on", "yes", "no", "true", "1", "", "~", "12:30"])
def test_new_strings_read_back_as_strings(value):
    text = "# keep me\nname: x\n"
    out = update_text(text, {"name": value})
    assert yaml.safe_load(out) == {"name": value}
    assert out.startswith("# keep me")


def test_yaml_1_1_values_unchanged_stay_as_written():
    text = "haze:\n  default_mode: off   # off / manual / pulse\nlevel: 50\n"
    data = yaml.safe_load(text)  # default_mode reads as False
    data["level"] = 60
    out = update_text(text, data)
    assert "default_mode: off   # off / manual / pulse" in out and "level: 60" in out


def test_lists_grow_and_shrink():
    text = "layers:\n  - {fixtures: [bars], colour: blue}  # first\n  - {fixtures: [washes], colour: red}\n"
    data = yaml.safe_load(text)
    out = update_text(text, {"layers": data["layers"] + [{"fixtures": ["heads"], "colour": "white"}]})
    assert "# first" in out and yaml.safe_load(out)["layers"][2] == {"fixtures": ["heads"], "colour": "white"}
    out = update_text(text, {"layers": data["layers"][:1]})
    assert yaml.safe_load(out) == {"layers": data["layers"][:1]}


def test_unreadable_old_text_falls_back_to_plain():
    out = update_text("a: [unclosed\n", {"a": 1})
    assert yaml.safe_load(out) == {"a": 1}


def test_keep_layout_never_moves_indentation():
    old = "a:\n  b:   1\n"
    new = "a:\nb: 1\n"
    assert keep_layout(old, new) == new  # same content at another depth is not the same line


def test_store_put_keeps_rig_comments(store):
    root = store.root
    text = (root / "rigs" / "full.yaml").read_text(encoding="utf-8")
    data = store.read("rig", "full")
    data["grand_master"] = 80
    store.put("rig", "full", data)
    out = (root / "rigs" / "full.yaml").read_text(encoding="utf-8")
    assert [ln for ln in text.splitlines() if "#" in ln] == [ln for ln in out.splitlines() if "#" in ln]
    assert "grand_master: 80" in out


def test_put_fixture_replaces_in_place(store):
    before = [f["id"] for f in store.read("fixtures")["fixtures"]]
    entry = next(f for f in store.read("fixtures")["fixtures"] if f["id"] == before[0])
    store.put_fixture({**entry, "address": entry["address"]})
    assert [f["id"] for f in store.read("fixtures")["fixtures"]] == before


def test_restore_only_takes_show_files(store):
    store.put("rig", "full", {**store.read("rig", "full"), "grand_master": 70})
    bid = store.backups()[0]["id"]
    with pytest.raises(StoreError, match="only show files"):
        store.restore(bid, "NOTE.txt")


# ------------------------------------------------------------------ groups (v2 R2)


def groups_of(store):
    out = {}
    for e in store.read("fixtures")["fixtures"]:
        for g in e.get("groups") or []:
            out.setdefault(g, []).append(e["id"])
    return out


def test_make_and_change_a_group(store):
    store.edit_group("set", "front", ["wash_l", "wash_r", "kick"])
    assert groups_of(store)["front"] == ["wash_l", "wash_r", "kick"]
    store.edit_group("set", "front", ["wash_l"])
    assert groups_of(store)["front"] == ["wash_l"]
    text = (store.root / "fixtures.yaml").read_text(encoding="utf-8")
    assert "# " in text  # comments kept


def test_group_names_checked(store):
    for bad in ("all", "kick", "bar", "mh_a", "Bad Name"):
        with pytest.raises(StoreError):
            store.edit_group("set", bad, ["mh_a"])
    with pytest.raises(StoreError, match="unknown fixtures"):
        store.edit_group("set", "x", ["ghost"])
    with pytest.raises(StoreError, match="no group"):
        store.edit_group("delete", "nope")


def test_rename_follows_every_reference(store):
    store.edit_group("rename", "movers", new_name="spots")
    g = groups_of(store)
    assert "movers" not in g and g["spots"] == ["mh_a", "mh_b"]
    blue = store.read("scene", "blue_chase")
    assert {"fixtures": ["spots"], "position": "drum_kit", "gobo": "dots"} in blue["layers"]
    from dmx_suite.showfiles import check_all

    assert [p for p in check_all(store.root) if not p.startswith("warning")] == []


def test_delete_refused_while_used(store):
    with pytest.raises(StoreError, match="unknown fixture or group 'movers'"):
        store.edit_group("delete", "movers")
    store.edit_group("set", "spare", ["kick"])
    store.edit_group("delete", "spare")
    assert "spare" not in groups_of(store)


def test_group_users(tmp_path):
    """v7: what names a group (the Fixtures page warns when a group is left with no lights)."""
    import shutil

    from dmx_suite.store import ShowStore

    root = tmp_path / "shows"
    shutil.copytree(Path(__file__).resolve().parents[1] / "shows", root, ignore=shutil.ignore_patterns(".backups"))
    s = ShowStore(root)
    assert "scenes/red_movers.yaml" in s.group_users("heads")
    assert s.group_users("nothing_uses_this") == []


def test_claude_list_fixtures_shows_channel_ranges():
    import yaml

    from dmx_suite.claude_tools import DmxTools

    tools = DmxTools(shows=Path(__file__).resolve().parents[1] / "shows")
    rows = {f["id"]: f for f in yaml.safe_load(tools.list_fixtures())["fixtures"]}
    bar = rows["bar_2"]
    assert bar["channels"] == f"{bar['address']}-{bar['address'] + 23}"  # LCB803: 24 channels
