"""Project basics: one version, the log file, the update check, the project files."""

import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import dmx_suite
from dmx_suite import logs, update

ROOT = Path(__file__).resolve().parents[1]


def test_one_app_version():
    from importlib.metadata import version

    assert version("dmx-suite") == dmx_suite.__version__  # pyproject reads it from __init__
    assert "__init__.py" in (ROOT / "installer" / "build.ps1").read_text(encoding="utf-8")
    assert not re.search(r'^version\s*=\s*"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)


def test_log_file_in_app_data(monkeypatch, tmp_path):
    monkeypatch.setattr(logs, "_done", False)
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        path = logs.setup()
        assert path == tmp_path / "appdata" / "logs" / "dmx-suite.log"  # conftest points app data here
        logging.getLogger("dmx_suite.test").info("hello log")
        for h in root.handlers:
            if h not in before:
                h.flush()
        assert "hello log" in path.read_text(encoding="utf-8")
        assert logs.setup() is None  # once only
    finally:
        for h in root.handlers[:]:
            if h not in before:
                root.removeHandler(h)
                h.close()


@pytest.mark.parametrize("v, t", [("v1.2.3", (1, 2, 3)), ("0.10.0-beta", (0, 10, 0)), ("2", (2,))])
def test_parse_version(v, t):
    assert update.parse_version(v) == t


@pytest.fixture
def release_server():
    state = {"tag": "v0.2.0", "status": 200}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            state["agent"] = self.headers.get("User-Agent")
            body = json.dumps({"tag_name": state["tag"], "html_url": "https://example.invalid/r"}).encode()
            self.send_response(state["status"])
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/latest", state
    srv.shutdown()


def test_update_check_newer_and_same(release_server):
    url, state = release_server
    r = update.check("0.1.0", url)
    assert r["ok"] and r["newer"] and r["latest"] == "v0.2.0" and "available" in r["message"]
    assert state["agent"] == "0.05-DMX-Suite-update-check"  # nothing about the user is sent
    state["tag"] = "v0.1.0"
    assert not update.check("0.1.0", url)["newer"]


def test_update_check_offline_is_a_message_not_an_error():
    r = update.check("0.1.0", "http://127.0.0.1:9/nothing", timeout=0.5)
    assert not r["ok"] and "couldn't check" in r["message"]


@pytest.mark.parametrize("name", ["LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md",
                                  ".github/pull_request_template.md", ".github/ISSUE_TEMPLATE/bug_report.md",
                                  ".github/ISSUE_TEMPLATE/feature_request.md", ".github/workflows/ci.yml",
                                  "docs/manual/README.md"])
def test_project_files_exist(name):
    assert (ROOT / name).is_file()


def test_licence_is_mit():
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")


def test_manual_pages_linked_from_index():
    index = (ROOT / "docs" / "manual" / "README.md").read_text(encoding="utf-8")
    pages = sorted(p.name for p in (ROOT / "docs" / "manual").glob("*.md") if p.name != "README.md")
    assert pages and all(f"({p})" in index for p in pages)


def test_every_ui_text_key_exists():
    """Text in the page and scripts comes from i18n/en.json; a missing key would show its name."""
    static = ROOT / "dmx_suite" / "web" / "static"
    strings = json.loads((static / "i18n" / "en.json").read_text(encoding="utf-8"))
    attr = r'data-(?:i18n(?:-title|-placeholder)?|tip)="([^"]+)"'
    used = {k for page in ("index.html", "login.html") for k in re.findall(attr, (static / page).read_text(encoding="utf-8"))}
    for js in (static / "js").rglob("*.js"):
        text = js.read_text(encoding="utf-8")
        used |= set(re.findall(r'\bt\(\s*"([a-z0-9_]+\.[a-z0-9_]+)"', text))
        used |= {k for pair in re.findall(r'\?\s*"([a-z]+\.[a-z0-9_]+)"\s*:\s*"([a-z]+\.[a-z0-9_]+)"', text) for k in pair}
    used = {k for k in used if not k.endswith(("_", "."))}  # prefixes of keys built at run time:
    used |= {f"live.sub_{k}" for k in ("head", "bar", "wash", "kick")} | {f"haze.{m}" for m in ("off", "manual", "pulse")}
    used |= {f"scenes.blend_{b}" for b in ("replace", "max", "add")}
    used |= {f"tempo.{s}" for s in ("tap", "kick", "midi_clock", "drums", "off")}
    used |= {f"shows.hold_{h}" for h in ("repeats", "hold_s", "hold_beats", "hold_bars")}
    used |= {f"shows.order_{o}" for o in ("sequence", "random")} | {f"shows.energy_{e}" for e in ("low", "mid", "high")}
    used |= {f"shows.mix_{m}" for m in ("matching", "white", "contrast")}
    used |= {f"shows.pattern_{p}" for p in ("all", "heads_only", "bars_only", "kit")}
    used |= {f"shows.move_{m}" for m in ("random", "sweep", "static")}
    used |= {f"override.type_{k}" for k in ("colour", "flash", "solo", "effect", "go", "fader", "haze")}
    used |= {f"override.haze_{a}" for a in ("off", "manual", "pulse", "boost")}
    used |= {f"wizard.{s}_{x}" for s in ("interface", "lights", "profile", "starter", "pin") for x in ("title", "help")}
    used |= {f"wizard.drv_{d}" for d in ("node", "usb_dmx_open", "usb_dmx_pro")}
    used |= {f"timing.{d}" for d in ("vcp", "d2xx", "unknown")}  # v5: driver type in the timing line
    used |= {f"ff.a_{a}" for a in ("yes", "no", "pass", "fail", "restart")}  # v5: fault-find answers
    used |= {f"darkness.src_{s}" for s in ("default", "set", "slider", "cc", "claude")}  # v6: darkness source
    used |= {"tempo2.freewheel", "tempo2.locked"}  # v6: tempo state
    used |= {f"kit.role_{r}" for r in ("kick", "snare", "hat", "tom", "cymbal", "tap", "count_in", "trigger_only")}
    # v3.1
    used |= {f"alerts.state_{s}" for s in ("active", "dismissed", "minimised", "snoozed", "muted", "cleared")}
    used |= {f"heads.stage_{k}" for k in "xyz"}
    places = ("left", "centre", "right", "front", "middle", "back", "floor", "low", "mid", "high", "ceiling")
    used |= {f"heads.place_{p}" for p in places}
    used |= {f"midi.role_{r}" for r in ("kick", "snare", "tom", "cymbal", "count_in", "activity", "darkness")}
    used |= {f"midi.level_{v}" for v in ("quiet", "normal", "loud")}
    used |= {f"midi.type_{x}" for x in ("note", "program_change", "control_change", "osc")}
    used |= {f"palettes.scheme_{x}" for x in ("analogous", "complementary", "triadic", "split", "mono")}
    used |= {f"wheel.{k}" for k in ("red", "green", "blue", "white", "amber", "uv")}
    # v3.2
    used |= {f"steps.playback_{p}" for p in ("loop", "once", "bounce")}
    used |= {f"steps.channel_{k}" for k in ("zoom", "focus", "frost", "strobe", "prism", "speed", "colour_wheel")}
    used |= {f"steps.tab_{k}" for k in ("colour", "position", "beam", "pixels")}
    used |= {f"scenes.px_{k}" for k in ("all", "none", "invert", "odd", "even", "nth", "first", "last", "left", "right",
                                        "centre", "same")}
    used |= {"steps.move_dark", "steps.move_lit"}
    # v3.4
    used |= {f"autopilot.bank_{b}" for b in ("move", "colour", "drum")} | {"autopilot.autopilot_on"}
    used |= {f"autopilot.class_{c}" for c in ("head", "wash", "pixel", "strobe", "effect")}
    used |= {f"autopilot.fader_{k}" for k in ("speed", "fade", "fan", "size", "shift")}
    used |= {f"autopilot.priority_{k}" for k in ("blackout", "drum_flash", "flash_override", "hold", "autopilot", "show")}
    used |= {"review.banned_toast", "review.rated"}
    # v4
    used |= {f"layout.need_{n}" for n in ("one", "two", "three", "pixels")}
    used |= {f"haze.b_{b}" for b in ("manual", "pulse", "boost", "safety")}
    # v4.1: ⓘ buttons name info.<key>.title / .text
    info = set(re.findall(r'data-info="([^"]+)"', (static / "index.html").read_text(encoding="utf-8")))
    for js in (static / "js").rglob("*.js"):
        info |= set(re.findall(r'infoButton\("([a-z0-9_]+\.[a-z0-9_]+)"\)', js.read_text(encoding="utf-8")))
    info |= {f"haze.{m}" for m in ("manual", "pulse", "boost", "safety")}  # hazepanel.js: infoButton(`haze.${mode}`)
    used |= {f"info.{k}.{part}" for k in info for part in ("title", "text")} | {"info.contents"}  # manual page (server)
    used |= {f"haze.u_{u}" for u in ("pct", "s", "min")}
    used |= {f"haze.f_{k}" for k in ("level", "pulse_level", "pulse_on_s", "pulse_every_s", "boost_level", "boost_s",
                                     "boost_cooldown_s", "max_on_s", "rest_s", "auto_off_min", "default_mode")}
    assert sorted(used - set(strings)) == []
    assert sorted(set(strings) - used) == []  # nothing left over either


@pytest.mark.parametrize("page", ["index.html", "login.html"])
def test_no_hard_coded_text_in_the_page(page):
    html = (ROOT / "dmx_suite" / "web" / "static" / page).read_text(encoding="utf-8")
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", re.split(r"<body[^>]*>", html, maxsplit=1)[1], flags=re.S)
    text = re.sub(r"<[^>]+>", " ", body)
    words = [w for w in text.split() if re.search(r"[A-Za-z]{3,}", w) and w not in ("MAC",)]
    assert words == []
