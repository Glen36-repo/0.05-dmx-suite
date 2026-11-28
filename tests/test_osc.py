"""OSC input: parsing, mappings in the MIDI map, the UDP listener, learn, and the rig setting."""

import socket
import struct
import time

import pytest

from dmx_suite.fixtures import ConfigError
from dmx_suite.midi.map import Mapping, parse_map
from dmx_suite.midi.monitor import MidiMonitor
from dmx_suite.midi.router import MidiRouter
from dmx_suite.osc import OscError, OscServer, build_message, level_of, parse_message, parse_packet
from dmx_suite.rig import parse_rig


def test_parse_messages():
    assert parse_message(build_message("/dmx/grand", 0.5)) == ("/dmx/grand", [0.5])
    assert parse_message(build_message("/a", 3, "x", True, False)) == ("/a", [3, "x", True, False])
    assert parse_message(b"/ping\x00\x00\x00") == ("/ping", [])
    with pytest.raises(OscError):
        parse_message(b"nope\x00\x00\x00\x00")
    with pytest.raises(OscError):
        parse_message(b"/x\x00\x00,f\x00\x00\x01")  # truncated float


def test_bundles_are_unpacked():
    a, b = build_message("/one", 1.0), build_message("/two", 0.0)
    bundle = b"#bundle\x00" + bytes(8) + struct.pack(">i", len(a)) + a + struct.pack(">i", len(b)) + b
    assert parse_packet(bundle) == [("/one", [1.0]), ("/two", [0.0])]


@pytest.mark.parametrize("args, level", [([0.25], 0.25), ([2.0], 1.0), ([64], 64 / 127), ([True], 1.0),
                                         (["x"], None), ([], None)])
def test_levels(args, level):
    assert level_of(args) == (pytest.approx(level) if level is not None else None)


def test_osc_mappings_in_the_map_file():
    m = parse_map({"mappings": [{"type": "osc", "address": "/dmx/grand", "action": "grand_master"},
                                {"type": "osc", "address": "/dmx/Blackout", "action": "blackout_toggle"}]})
    assert m.get_osc("/dmx/grand").action == "grand_master"
    assert m.get_osc("/dmx/blackout") is None  # OSC addresses are case-sensitive
    assert m.mappings[0].to_dict() == {"type": "osc", "address": "/dmx/grand", "action": "grand_master"}
    m.remove(("osc", 0, 0, "/dmx/Blackout"))
    assert m.get_osc("/dmx/Blackout") is None
    with pytest.raises(ConfigError, match="starts with /"):
        parse_map({"mappings": [{"type": "osc", "address": "dmx grand", "action": "grand_master"}]})


def test_router_drives_faders_and_buttons(engine):
    r = MidiRouter(engine, parse_map({"mappings": [
        {"type": "osc", "address": "/dmx/grand", "action": "grand_master"},
        {"type": "osc", "address": "/dmx/master", "action": "master_toggle"}]}), MidiMonitor())
    assert r.handle_osc("/dmx/grand", [0.4], "10.0.0.5").startswith("grand_master")
    assert engine.masters.grand.target == pytest.approx(0.4)
    assert r.handle_osc("/dmx/master", [1.0]) == "MASTER off"  # press
    assert r.handle_osc("/dmx/master", [0.0]) == "release"  # button up does nothing
    assert r.handle_osc("/nothing", []) == "unmapped"
    rows = list(r.monitor.entries)
    assert rows[0].port == "OSC 10.0.0.5" and rows[0].type == "osc /dmx/grand"


def test_learn_takes_osc(engine):
    r = MidiRouter(engine, parse_map({}), MidiMonitor())
    r.learn("sub_master", {"kind": "bar"})
    assert r.handle_osc("/fader/3", [0.1]).startswith("learned")
    m = r.map.get_input("osc_fader_3")
    assert m.action == "sub_master" and m.params == {"kind": "bar"}
    r.handle_osc("/fader/3", [0.6])
    assert engine.masters.subs[engine.rig.patch.fixtures["bar_1"].kind].target == pytest.approx(0.6)


def test_udp_listener_end_to_end(engine):
    r = MidiRouter(engine, parse_map({"mappings": [{"type": "osc", "address": "/dmx/grand", "action": "grand_master"}]}),
                   MidiMonitor())
    srv = OscServer(r.handle_osc, 0, ["127.0.0.1/32"], host="127.0.0.1").start()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(build_message("/dmx/grand", 0.3), ("127.0.0.1", srv.port))
        s.sendto(b"garbage", ("127.0.0.1", srv.port))  # counted, ignored, listener carries on
        s.sendto(build_message("/dmx/grand", 0.7), ("127.0.0.1", srv.port))
        deadline = time.time() + 2
        while engine.masters.grand.target != pytest.approx(0.7) and time.time() < deadline:
            time.sleep(0.01)
        assert engine.masters.grand.target == pytest.approx(0.7)
        assert srv.received == 2 and srv.errors == 1 and srv.state()["state"] == "ok"
        s.close()
    finally:
        srv.stop()


def test_listener_refuses_other_networks(engine):
    srv = OscServer(lambda *a: None, 0, ["192.168.50.0/24"], host="127.0.0.1")
    assert not srv.allowed("127.0.0.1") and srv.allowed("192.168.50.9") and not srv.allowed("bad")
    srv.sock.close()
    default = OscServer(lambda *a: None, 0, host="127.0.0.1")
    assert default.allowed("127.0.0.1") and default.allowed("192.168.1.20") and not default.allowed("8.8.8.8")
    default.sock.close()


def test_rig_osc_setting(patch):
    assert parse_rig({}, patch).osc.port is None  # off by default
    r = parse_rig({"osc": {"port": 9000, "allow": ["192.168.1.0/24", "10.0.0.7"]}}, patch)
    assert r.osc.port == 9000 and r.osc.allow == ["192.168.1.0/24", "10.0.0.7"]
    for bad, msg in (({"osc": {"port": 80}}, "1024-65535"), ({"osc": {"allow": []}}, "port"),
                     ({"osc": {"port": 9000, "allow": ["nope"]}}, "isn't an address")):
        with pytest.raises(ConfigError, match=msg):
            parse_rig(bad, patch)


def test_osc_mapping_round_trip_in_a_learn(engine):
    r = MidiRouter(engine, parse_map({}), MidiMonitor())
    r.learn("blackout_toggle")
    r.handle_osc("/btn/1", [])
    assert r.map.to_dict()["mappings"] == [{"input": "osc_btn_1", "action": "blackout_toggle"}]
    assert r.inputs.get("osc_btn_1").address == "/btn/1"
    assert isinstance(r.map.mappings[0], Mapping)


def test_run_starts_osc_from_the_rig_file(tmp_path):
    import shutil
    from pathlib import Path

    from dmx_suite.cli import build_parser, resolve_shows, start_session

    root = tmp_path / "shows"
    shutil.copytree(Path(__file__).resolve().parents[1] / "shows", root,
                    ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    rig = root / "rigs" / "full.yaml"
    rig.write_text(rig.read_text(encoding="utf-8") + f"\nosc: {{port: {port}}}\n", encoding="utf-8")
    midi = root / "midi" / "default.yaml"
    midi.write_text(midi.read_text(encoding="utf-8") + "  - {type: osc, address: /dmx/grand, action: grand_master}\n",
                    encoding="utf-8")
    args = resolve_shows(build_parser().parse_args(["--shows", str(root), "run", "--sim", "--no-web", "--headless"]))
    session = start_session(args, out=lambda *a: None)
    try:
        assert session.osc is not None and any(d["kind"] == "osc" for d in session.app.devices())
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(build_message("/dmx/grand", 0.25), ("127.0.0.1", port))
        deadline = time.time() + 2
        while session.engine.masters.grand.target != pytest.approx(0.25) and time.time() < deadline:
            time.sleep(0.01)
        assert session.engine.masters.grand.target == pytest.approx(0.25)
        s.close()
    finally:
        session.stop()
