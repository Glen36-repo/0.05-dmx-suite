import shutil
from pathlib import Path

import pytest
import yaml

from dmx_suite.store import LockedError, ShowStore, StoreError

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
    with pytest.raises(StoreError, match="unknown colour"):
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
