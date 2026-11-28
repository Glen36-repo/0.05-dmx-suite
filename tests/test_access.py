"""R6 access: PIN, sessions, phone/LAN access, Claude's own token; and the QR code for the phone link."""

import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from dmx_suite import qr
from dmx_suite.access import MAX_FAILS, Access, hash_pin, pin_matches
from dmx_suite.app import App
from dmx_suite.claude_tools import DmxTools
from dmx_suite.output import LogDriver
from dmx_suite.showfiles import load_show
from dmx_suite.web.server import WebServer

SHOWS = Path(__file__).resolve().parents[1] / "shows"
UI = "ui-token-0123456789abcdefgh"
CLAUDE = "claude-token-0123456789abcd"


# ------------------------------------------------------------------ QR code


def _syndromes_zero(block: list[int], ec: int) -> bool:
    for i in range(ec):
        acc = 0
        for b in block:
            acc = qr._mul(acc, qr._EXP[i]) ^ b
        if acc:
            return False
    return True


def _read_back(m: list[list[bool]]) -> tuple[int, list[int]]:
    """Undo what matrix() did: find the mask from the format bits, unmask, collect codewords."""
    n = len(m)
    v = (n - 17) // 4
    bits = sum(int(m[8][n - 1 - i]) << i for i in range(8)) | sum(int(m[n - 15 + i][8]) << i for i in range(8, 15))
    mask = next(k for k in range(8) if qr.format_bits(k) == bits)
    g = qr._Grid(v)
    cells = g.data_cells()
    raw = [int(m[r][c] != qr._MASKS[mask](r, c)) for r, c in cells]
    words = [int("".join(map(str, raw[i:i + 8])), 2) for i in range(0, len(raw) - len(raw) % 8, 8)]
    total = qr._capacity(v) + qr._EC_M[v][0] * sum(b for b, _ in qr._EC_M[v][1])
    return v, words[:total]


@pytest.mark.parametrize("text", ["http://192.168.1.20:8505/", "x", "http://10.0.0.5:8505/" * 6, "é" * 40])
def test_qr_round_trip(text):
    m = qr.matrix(text)
    v, words = _read_back(m)
    assert (v, words) == qr.codewords(text.encode())
    ec, groups = qr._EC_M[v]
    nblocks = sum(b for b, _ in groups)
    sizes = [k for b, k in groups for _ in range(b)]
    data = [[] for _ in range(nblocks)]
    i = 0
    for j in range(max(sizes)):
        for b in range(nblocks):
            if j < sizes[b]:
                data[b].append(words[i])
                i += 1
    ecs = [[words[i + j * nblocks + b] for j in range(ec)] for b in range(nblocks)]
    assert all(_syndromes_zero(d + e, ec) for d, e in zip(data, ecs, strict=True))
    flat = [x for d in data for x in d]
    payload = text.encode()
    assert flat[0] >> 4 == 0b0100  # byte mode
    count = ((flat[0] & 0xF) << 4) | (flat[1] >> 4) if v < 10 else None
    if count is not None:
        assert count == len(payload)
        got = bytes(((flat[2 + k - 1] & 0xF) << 4) | (flat[2 + k] >> 4) for k in range(len(payload)))
        assert got == payload


def test_qr_function_patterns_and_size():
    m = qr.matrix("http://192.168.1.20:8505/")
    n = len(m)
    assert n == 17 + 4 * 2  # 26 bytes fits version 2-M
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):
        assert all(m[r0][c0 + i] for i in range(7)) and not m[r0 + 1][c0 + 1] and m[r0 + 3][c0 + 3]
    assert m[n - 8][8]  # the dark module
    assert all(m[6][i] == (i % 2 == 0) for i in range(8, n - 8))
    assert qr.svg("x").startswith("<svg") and 'fill="#000"' in qr.svg("x")
    with pytest.raises(ValueError):
        qr.matrix("x" * 300)


def test_qr_version_7_carries_version_bits():
    m = qr.matrix("http://192.168.100.200:8505/" * 5)  # 140 bytes: version 7 or more
    n = len(m)
    v = (n - 17) // 4
    assert v >= 7
    bits = sum(int(m[n - 11 + i % 3][i // 3]) << i for i in range(18))
    assert bits == qr.version_bits(v) and bits >> 12 == v


# ------------------------------------------------------------------ PIN and sessions


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_pin_hash():
    h = hash_pin("2468", iterations=1000)
    assert "2468" not in h and pin_matches("2468", h) and not pin_matches("2469", h)
    assert not pin_matches("2468", None) and not pin_matches("2468", "junk")


def test_set_change_and_clear_pin(tmp_path):
    a = Access(tmp_path / "access.json")
    with pytest.raises(ValueError):
        a.configure(lan=True)  # needs a PIN first
    with pytest.raises(ValueError):
        a.set_pin("12")
    a.set_pin("2468")
    assert "2468" not in (tmp_path / "access.json").read_text()
    with pytest.raises(PermissionError):
        a.set_pin("1357", old="0000")
    a.set_pin("1357", old="2468")
    a.configure(lan=True, pin_local=True, session_hours=2)
    b = Access(tmp_path / "access.json")  # saved
    assert b.lan and b.pin_local and b.session_s == 7200
    b.clear_pin("1357")
    assert not b.pin_set and not b.lan and not b.pin_local


def test_login_lockout_and_timeout(tmp_path):
    clock = Clock()
    a = Access(tmp_path / "access.json", clock=clock)
    a.set_pin("2468")
    for _ in range(MAX_FAILS):
        with pytest.raises(PermissionError, match="wrong PIN"):
            a.login("10.0.0.9", "0000")
    with pytest.raises(PermissionError, match="wait"):
        a.login("10.0.0.9", "2468")  # right PIN, but it has to wait
    sid, _ = a.login("10.0.0.8", "2468")  # another phone isn't held up
    clock.t += 31
    sid9, _ = a.login("10.0.0.9", "2468")
    assert a.session(sid) and a.session(sid9)
    clock.t += 12 * 3600 - 1
    assert a.session(sid)  # used just now: still in
    clock.t += 12 * 3600 + 1
    assert a.session(sid) is None
    sid2, _ = a.login("10.0.0.8", "2468")
    a.set_pin("1357", old="2468")  # a new PIN signs everyone out
    assert a.session(sid2) is None


# ------------------------------------------------------------------ server


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    app = App(load_show(root), [LogDriver()])
    access = Access(tmp_path / "access.json")
    web = WebServer(app, None, 0, token=UI, claude_token=CLAUDE, access=access)
    web.start()
    yield app, web, access, root
    web.stop()
    app.engine.stop()


def call(web, path, method="GET", body=None, token=None, cookie=None, raw=False):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-DMX-Token"] = token
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(f"http://127.0.0.1:{web.port}{path}", method=method, headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            data = r.read().decode()
            return r.status, (data if raw else json.loads(data)), r.headers
    except urllib.error.HTTPError as e:
        data = e.read().decode()
        return e.code, (data if raw else json.loads(data)), e.headers


def remote(web, on=True):
    """Make every request look as if it came from a phone on the network."""
    web.handler._local = (lambda self: False) if on else (lambda self: self.client_address[0] in ("127.0.0.1", "::1"))


def test_this_computer_gets_in_without_a_pin(server):
    _, web, _, _ = server
    status, html, _ = call(web, "/", raw=True)
    assert status == 200 and UI in html and "login.js" not in html
    assert call(web, "/api/control", "POST", {"cmd": "master"}, token=UI)[0] == 200
    assert call(web, "/api/control", "POST", {"cmd": "master"}, token="nope" * 6)[0] == 401
    assert web.host == "127.0.0.1"  # localhost only until phone access is turned on


def test_phones_are_refused_while_lan_access_is_off(server):
    _, web, access, _ = server
    access.set_pin("2468")
    remote(web)
    assert call(web, "/", raw=True)[0] == 403
    assert call(web, "/api/login", "POST", {"pin": "2468"})[0] == 403


def test_phone_signs_in_with_the_pin(server):
    app, web, access, _ = server
    access.set_pin("2468")
    access.configure(lan=True)
    remote(web)
    status, html, _ = call(web, "/", raw=True)
    assert status == 200 and "login.js" in html and UI not in html
    assert call(web, "/static/js/login.js", raw=True)[0] == 200
    assert call(web, "/api/state")[0] == 401
    assert call(web, "/api/login", "POST", {"pin": "0000"})[0] == 401
    status, _, headers = call(web, "/api/login", "POST", {"pin": "2468"})
    assert status == 200
    cookie = headers["Set-Cookie"].split(";")[0]
    assert "HttpOnly" in headers["Set-Cookie"] and "SameSite=Strict" in headers["Set-Cookie"]
    assert call(web, "/api/state", cookie=cookie)[0] == 200
    status, html, _ = call(web, "/", cookie=cookie, raw=True)
    csrf = html.split('name="dmx-token" content="')[1].split('"')[0]
    assert status == 200 and csrf and csrf != UI
    assert call(web, "/api/control", "POST", {"cmd": "master"}, token=csrf, cookie=cookie)[0] == 200
    assert call(web, "/api/control", "POST", {"cmd": "master"}, token=UI, cookie=cookie)[0] == 401  # this computer's token
    assert call(web, "/api/control", "POST", {"cmd": "master"}, token=csrf)[0] == 401  # no cookie
    # a phone can't change the access settings
    assert call(web, "/api/access", "POST", {"action": "configure", "lan": False}, token=csrf, cookie=cookie)[0] == 403
    assert call(web, "/api/access", cookie=cookie)[1]["local"] is False
    assert call(web, "/api/logout", "POST", cookie=cookie)[0] == 200
    assert call(web, "/api/state", cookie=cookie)[0] == 401


def test_wrong_pins_lock_a_phone_out_for_a_while(server):
    _, web, access, _ = server
    access.set_pin("2468")
    access.configure(lan=True)
    remote(web)
    for _ in range(MAX_FAILS):
        assert call(web, "/api/login", "POST", {"pin": "1111"})[0] == 401
    assert call(web, "/api/login", "POST", {"pin": "2468"})[0] == 429


def test_pin_on_this_computer_too(server):
    _, web, access, _ = server
    access.set_pin("2468")
    access.configure(pin_local=True)
    status, html, _ = call(web, "/", raw=True)
    assert "login.js" in html and UI not in html
    assert call(web, "/api/state")[0] == 401
    assert call(web, "/api/control", "POST", {"cmd": "master"}, token=UI)[0] == 401


def test_access_settings_and_lan_switch_over(server):
    _, web, _, _ = server
    st = call(web, "/api/access")[1]
    assert st["pin_set"] is False and st["lan"] is False and st["local"] is True and st["qr"] is None
    assert call(web, "/api/access", "POST", {"action": "configure", "lan": True}, token=UI)[0] == 400  # no PIN yet
    assert call(web, "/api/access", "POST", {"action": "set_pin", "pin": "2468"}, token=UI)[0] == 200
    status, st, _ = call(web, "/api/access", "POST", {"action": "configure", "lan": True}, token=UI)
    assert status == 200 and st["lan"] is True
    if st["urls"]:
        assert st["qr"].startswith("<svg")
    for _ in range(50):
        if web.host == "0.0.0.0":
            break
        time.sleep(0.05)
    assert web.host == "0.0.0.0"
    assert call(web, "/api/state")[0] == 200  # same port, still answers here
    call(web, "/api/access", "POST", {"action": "configure", "lan": False}, token=UI)
    for _ in range(50):
        if web.host == "127.0.0.1":
            break
        time.sleep(0.05)
    assert web.host == "127.0.0.1"


# ------------------------------------------------------------------ Claude


def test_claude_edits_shows_but_not_gig_lock_or_access(server):
    app, web, _, root = server
    assert call(web, "/api/state", token=CLAUDE)[0] == 200
    assert call(web, "/api/giglock", "POST", {"on": False}, token=CLAUDE)[0] == 403
    assert call(web, "/api/access", token=CLAUDE)[0] == 403
    assert call(web, "/api/access", "POST", {"action": "set_pin", "pin": "2468"}, token=CLAUDE)[0] == 403
    assert call(web, "/api/settings", "POST", {"theme": "005"}, token=CLAUDE)[0] == 403
    assert call(web, "/api/midi/learn", "POST", {"action": "master"}, token=CLAUDE)[0] == 403
    assert call(web, "/api/control", "POST", {"cmd": "blackout"}, token=CLAUDE)[0] == 403
    tools = DmxTools(shows=root, url=f"http://127.0.0.1:{web.port}", token=CLAUDE)
    assert "saved" in tools.save("scene", "claude_test", "name: Claude test\nlayers:\n  - {fixtures: [bars], colour: red}\n")
    app.set_gig_lock(True)
    with pytest.raises(Exception, match="gig lock"):
        tools.save("scene", "claude_test2", "name: x\nlayers:\n  - {fixtures: [bars], colour: red}\n")
    with pytest.raises(Exception, match="gig lock"):
        tools.preview_scene("claude_test")


def test_claude_token_only_works_on_this_computer(server):
    _, web, access, _ = server
    access.set_pin("2468")
    access.configure(lan=True)
    remote(web)
    assert call(web, "/api/state", token=CLAUDE)[0] == 401


def test_learn_and_remove_honour_gig_lock(server):
    app, web, _, _ = server
    app.set_gig_lock(True)
    assert call(web, "/api/midi/learn", "POST", {"action": "master"}, token=UI)[0] == 423
    assert call(web, "/api/midi/remove", "POST", {"type": "note", "channel": 1, "number": 36}, token=UI)[0] == 423
    assert call(web, "/api/midi/pause", "POST", {"on": True}, token=UI)[0] == 200


def test_offline_claude_honours_gig_lock(tmp_path):
    from dmx_suite.paths import giglock_file

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    tools = DmxTools(shows=root, url="http://127.0.0.1:9", token=CLAUDE)  # engine not running
    scene = "name: x\nlayers:\n  - {fixtures: [bars], colour: red}\n"
    assert "saved" in tools.save("scene", "offline_a", scene)
    giglock_file().parent.mkdir(parents=True, exist_ok=True)
    giglock_file().write_text("on")
    with pytest.raises(Exception, match="gig lock"):
        tools.save("scene", "offline_b", scene)
