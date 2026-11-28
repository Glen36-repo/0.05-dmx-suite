"""Show file format versions: every past format loads and upgrades; newer files are refused."""

import re
import shutil
from pathlib import Path

import pytest
import yaml

from dmx_suite.fixtures import ConfigError
from dmx_suite.profile import BAND_005
from dmx_suite.showfiles import check_all, load_show
from dmx_suite.store import ShowStore
from dmx_suite.versions import FORMAT, FormatError, kind_of, read_doc, show_files, stamped, upgrade

SHOWS = Path(__file__).resolve().parents[1] / "shows"


def _copy(tmp_path) -> Path:
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    return root


@pytest.fixture
def v1(tmp_path) -> Path:
    """The shipped shows as format 1 wrote them: no `version:`, rigs without `profile:`."""
    root = _copy(tmp_path)
    for p in show_files(root):
        text = re.sub(r"^version: \d+\n", "", p.read_text(encoding="utf-8"), flags=re.M)
        if kind_of(p) == "rig":
            text = re.sub(r"^# Rule profile.*\nprofile: .*\n", "", text, flags=re.M)
        p.write_text(text, encoding="utf-8")
    return root


def test_shipped_files_are_current_format():
    for p in show_files(SHOWS):
        assert yaml.safe_load(p.read_text(encoding="utf-8"))["version"] == FORMAT, p


def test_every_file_kind_is_known():
    assert {kind_of(p) for p in show_files(SHOWS)} == {"fixtures", "palettes", "rig", "look", "scene", "show", "setlist", "midi"}


def test_v1_folder_loads_without_writing(v1):
    before = {p: p.read_text(encoding="utf-8") for p in show_files(v1)}
    sf = load_show(v1, rig="full")
    assert sf.rig.profile is BAND_005
    assert [p for p in check_all(v1) if not p.startswith("warning")] == []
    assert {p: p.read_text(encoding="utf-8") for p in show_files(v1)} == before  # loading never writes


def test_v1_folder_upgrades_with_backup_and_comments(v1):
    before = {p: p.read_text(encoding="utf-8") for p in show_files(v1)}
    bid, names = ShowStore(v1).upgrade()
    assert bid and len(names) == len(before)
    for p, old in before.items():
        new = p.read_text(encoding="utf-8")
        assert yaml.safe_load(new)["version"] == FORMAT
        old_comments = [ln for ln in old.splitlines() if ln.lstrip().startswith("#")]
        assert old_comments == [ln for ln in new.splitlines() if ln.lstrip().startswith("#")], p
        assert (v1 / ".backups" / bid / p.relative_to(v1)).read_text(encoding="utf-8") == old  # original kept
    rig = yaml.safe_load((v1 / "rigs" / "full.yaml").read_text(encoding="utf-8"))
    assert rig["profile"] == "0.05_band"  # format 1 rigs ran the band rules: now said explicitly
    assert "upgrade to file format" in (v1 / ".backups" / bid / "NOTE.txt").read_text(encoding="utf-8")
    assert ShowStore(v1).upgrade() == (None, [])  # once only


def test_format_1_folder_renders_v1_frames_before_and_after_upgrade(v1):
    import json

    from golden import GOLDEN, capture

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert capture(root=v1) == golden  # read as format 1, upgraded in memory
    ShowStore(v1).upgrade()
    assert capture(root=v1) == golden  # written as the current format


def test_newer_format_refused(tmp_path):
    root = _copy(tmp_path)
    p = root / "scenes" / "opera.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace(f"version: {FORMAT}", f"version: {FORMAT + 1}"), encoding="utf-8")
    with pytest.raises(FormatError, match="newer 0.05 DMX Suite"):
        load_show(root, "full")
    assert any("scenes/opera.yaml" in x and "newer" in x for x in check_all(root))
    assert ShowStore(root).upgrade() == (None, [])  # never downgraded or touched
    assert f"version: {FORMAT + 1}" in p.read_text(encoding="utf-8")


@pytest.mark.parametrize("bad", ["two", 0, -1, 1.5, True])
def test_bad_version_values(bad):
    with pytest.raises(FormatError, match="whole number"):
        upgrade({"version": bad, "name": "x"}, "scene")


def test_upgrade_strips_version_and_applies_steps():
    assert upgrade({"version": FORMAT, "name": "x"}, "scene") == {"name": "x"}
    assert upgrade({"name": "r"}, "rig") == {"name": "r", "profile": "0.05_band"}  # format 1 rig
    assert upgrade({"name": "r", "profile": "generic"}, "rig") == {"name": "r", "profile": "generic"}
    assert list(stamped({"name": "x", "version": 1})) == ["version", "name"]
    with pytest.raises(ConfigError, match="mapping"):
        upgrade(["a"], "scene")


def test_store_reads_without_version_and_writes_it_first(tmp_path):
    store = ShowStore(_copy(tmp_path))
    data = store.read("scene", "opera")
    assert "version" not in data
    store.put("scene", "teal", {"name": "Teal", "layers": [{"fixtures": ["bars"], "colour": "#00a090"}]})
    text = (store.root / "scenes" / "teal.yaml").read_text(encoding="utf-8")
    assert text.startswith(f"version: {FORMAT}\n")
    assert read_doc(store.root / "scenes" / "teal.yaml")["name"] == "Teal"


def test_store_put_of_current_data_doesnt_rerun_upgrades(tmp_path):
    store = ShowStore(_copy(tmp_path))
    rig = store.read("rig", "small")
    rig["profile"] = "generic"
    store.put("rig", "small", rig)
    assert store.read("rig", "small")["profile"] == "generic"


def test_inline_yaml_with_version_is_accepted(tmp_path):
    from dmx_suite.claude_tools import DmxTools

    t = DmxTools(shows=_copy(tmp_path), url="http://127.0.0.1:9")
    ok = f"version: {FORMAT}\nname: V\nlayers:\n  - {{fixtures: [bars], colour: blue}}"
    assert t.validate_scene(ok).startswith("ok")
    assert "newer" in t.validate_scene(ok.replace(f"version: {FORMAT}", f"version: {FORMAT + 1}"))
