from pathlib import Path

import pytest

from dmx_suite.cli import main
from dmx_suite.fixtures import ConfigError, parse_patch
from dmx_suite.rig import parse_rig
from dmx_suite.showfiles import check_all, load_show

SHOWS = Path(__file__).resolve().parents[1] / "shows"


def test_shipped_show_files_load():
    s = load_show(SHOWS)
    assert "mh_a" in s.rig.present and s.rig.patch.fixtures["uking_l"].type.colour_only
    assert s.rig.haze.default_mode == "off"


def test_small_rig_has_no_heads():
    s = load_show(SHOWS, rig="small")
    assert not any(f.kind.value == "head" for f in s.rig.fixtures)
    assert not s.rig.haze.enabled


def test_check_all_passes_with_only_warnings():
    problems = check_all(SHOWS)
    assert all(p.startswith("warning") for p in problems), problems


def test_cli_check():
    assert main(["--shows", str(SHOWS), "check"]) == 0


def test_overlapping_addresses_rejected():
    with pytest.raises(ConfigError, match="overlaps"):
        parse_patch({
            "types": {"t": {"kind": "wash", "channels": ["dimmer", "red"]}},
            "fixtures": [{"id": "a", "type": "t", "address": 1}, {"id": "b", "type": "t", "address": 2}],
        })


@pytest.mark.parametrize(
    "types, msg",
    [
        ({"t": {"kind": "wash", "channels": ["laser"]}}, "unknown role"),
        ({"t": {"kind": "wash", "channels": ["haze"]}}, "only haze fixtures"),
        ({"t": {"kind": "haze", "channels": ["dimmer"]}}, "needs a haze channel"),
        ({"t": {"kind": "spot", "channels": ["dimmer"]}}, "kind must be"),
        ({"t": {"kind": "wash", "channels": [{"role": "dimmer", "pixel": 1}]}}, "pixel"),
    ],
)
def test_bad_types(types, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_patch({"types": types, "fixtures": []})


def test_fixture_must_fit_universe():
    with pytest.raises(ConfigError, match="doesn't fit"):
        parse_patch({"types": {"t": {"kind": "wash", "channels": ["dimmer", "red"]}},
                     "fixtures": [{"id": "a", "type": "t", "address": 512}]})


def test_rig_validation(patch):
    with pytest.raises(ConfigError):
        parse_rig({"head_limits": {"mh_a": {"tilt": [80, 20]}}}, patch)
    with pytest.raises(ConfigError):
        parse_rig({"grand_master": 150}, patch)
    with pytest.raises(ConfigError):
        parse_rig({"haze": {"pulse_on_s": 60, "pulse_every_s": 30}}, patch)
    with pytest.raises(ConfigError):
        parse_rig({"fixtures": ["nope"]}, patch)
