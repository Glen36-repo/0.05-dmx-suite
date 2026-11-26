"""Compile firmware/include/proto.h on the host and check it matches the Python protocol byte for byte."""

import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from dmx_suite.node import protocol as p

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "firmware" / "test" / "host_proto_check.cpp"


@pytest.fixture(scope="module")
def firmware_output(tmp_path_factory) -> dict[str, str]:
    cxx = shutil.which("g++") or shutil.which("clang++")
    if not cxx:
        pytest.skip("no C++ compiler")
    exe = tmp_path_factory.mktemp("fw") / "check"
    subprocess.run([cxx, "-std=c++17", "-Wall", "-Werror", "-o", str(exe), str(SRC)], check=True)
    out = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout
    result = {}
    for line in out.splitlines():
        name, _, value = line.partition(" ")
        result[name] = value
    return result


def test_crc_and_net_id(firmware_output):
    assert firmware_output["crc"] == struct.pack("<H", p.crc16(b"123456789")).hex()
    assert firmware_output["fnv"] == struct.pack("<I", p.fnv1a32(b"0.05-dev-key-change-me")).hex()


def test_encoders_match(firmware_output):
    assert firmware_output["ping"] == p.ping(0x12345678).hex()
    assert firmware_output["frame"] == p.dmx_frame(bytes(i & 0xFF for i in range(512))).hex()
    hb = p.Heartbeat(bytes(range(0xA0, 0xA6)), p.NodeType.DMX_RX, (0, 1, 2), 3600, -67, 3, 25, 0, "Left bars")
    assert firmware_output["heartbeat"] == p.heartbeat_msg(hb).hex()
    st = p.Status(123456, 4000, 40.0, 2, 1, p.Mode.LIVE, 3)
    assert firmware_output["status"] == p.status_msg(st).hex()


def test_fallback_render_matches(firmware_output):
    base = bytearray(512)
    base[9] = 255
    look = p.FallbackLook(1500, 6, 200, [1, 4, 100], bytes(base))
    for t in (0, 999, 1000, 2500, 5999, 6000, 123457):
        frame = p.render_fallback(look, t)
        assert firmware_output[f"fallback_{t}"] == frame[:12].hex(), t
        assert firmware_output[f"fallback_{t}_hi"] == frame[99:102].hex(), t


def test_firmware_parser_resyncs(firmware_output):
    assert firmware_output["parser"] == "good=2 crc_errors=2"
