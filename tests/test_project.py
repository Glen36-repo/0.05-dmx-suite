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
    used = set(re.findall(r'data-i18n(?:-title|-placeholder)?="([^"]+)"', (static / "index.html").read_text(encoding="utf-8")))
    for js in (static / "js").rglob("*.js"):
        text = js.read_text(encoding="utf-8")
        used |= set(re.findall(r'\bt\(\s*"([a-z0-9_]+\.[a-z0-9_]+)"', text))
        used |= {k for pair in re.findall(r'\?\s*"([a-z]+\.[a-z0-9_]+)"\s*:\s*"([a-z]+\.[a-z0-9_]+)"', text) for k in pair}
    used = {k for k in used if not k.endswith(("_", "."))}  # prefixes of keys built at run time:
    used |= {f"live.sub_{k}" for k in ("head", "bar", "wash", "kick")} | {f"haze.{m}" for m in ("off", "manual", "pulse")}
    assert sorted(used - set(strings)) == []
    assert sorted(set(strings) - used) == []  # nothing left over either


def test_no_hard_coded_text_in_the_page():
    html = (ROOT / "dmx_suite" / "web" / "static" / "index.html").read_text(encoding="utf-8")
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html.split("<body>", 1)[1], flags=re.S)
    text = re.sub(r"<[^>]+>", " ", body)
    words = [w for w in text.split() if re.search(r"[A-Za-z]{3,}", w) and w not in ("MAC",)]
    assert words == []
