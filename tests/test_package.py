"""R6 `.dms` show files: one file for the whole show, opened through a working copy."""

import io
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest
import yaml

from dmx_suite import package
from dmx_suite.claude_tools import DmxTools
from dmx_suite.cli import build_parser, main, resolve_shows, restart_argv, start_session
from dmx_suite.package import (
    DmsError,
    DmsProject,
    content_hash,
    is_dms,
    pack,
    read_manifest,
    show_files,
    unpack,
)
from dmx_suite.store import LockedError, StoreError
from dmx_suite.versions import FORMAT, kind_of

SHOWS = Path(__file__).resolve().parents[1] / "shows"
SCENE = {"name": "Dms test", "layers": [{"fixtures": ["bars"], "colour": "red"}]}


@pytest.fixture
def dms(tmp_path) -> Path:
    f = tmp_path / "OneDrive" / "Gig.dms"
    pack(SHOWS, f)
    return f


def _zip(path: Path, entries: dict[str, bytes], manifest: dict | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("dms.json", json.dumps(manifest or {"dms": 1, "format": FORMAT, "app": "test"}))
        for name, b in entries.items():
            z.writestr(name, b)
    return path


# ------------------------------------------------------------------ pack / unpack


def test_round_trip_is_byte_identical(dms, tmp_path):
    out = tmp_path / "out"
    m = unpack(dms, out)
    assert m["dms"] == 1 and m["format"] == FORMAT
    assert [p.as_posix() for p in show_files(out)] == [p.as_posix() for p in show_files(SHOWS)]
    for rel in show_files(SHOWS):
        assert (out / rel).read_bytes() == (SHOWS / rel).read_bytes()  # comments and all
    assert content_hash(out) == content_hash(SHOWS)


def test_same_show_packs_to_the_same_bytes(tmp_path):
    a, b = tmp_path / "a.dms", tmp_path / "b.dms"
    pack(SHOWS, a)
    pack(SHOWS, b)
    za, zb = zipfile.ZipFile(a), zipfile.ZipFile(b)
    assert [(i.filename, i.CRC) for i in za.infolist() if i.filename != "dms.json"] == \
           [(i.filename, i.CRC) for i in zb.infolist() if i.filename != "dms.json"]


def test_backups_and_state_stay_out(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root)
    (root / ".backups" / "x").mkdir(parents=True)
    (root / ".backups" / "x" / "old.yaml").write_text("name: old\n")
    (root / ".state.json").write_text("{}")
    pack(root, tmp_path / "s.dms")
    names = zipfile.ZipFile(tmp_path / "s.dms").namelist()
    assert not any(n.startswith(".") for n in names) and "dms.json" in names


@pytest.mark.parametrize("name", ["../evil.yaml", "/abs.yaml", "scenes/../../evil.yaml", "a\\b.yaml",
                                  "C:/x.yaml", ".backups/x.yaml", "script.py", "scenes/readme.txt"])
def test_unsafe_names_refuse_the_whole_file(tmp_path, name):
    f = _zip(tmp_path / "bad.dms", {"fixtures.yaml": b"version: 3\n", name: b"x: 1\n"})
    with pytest.raises(DmsError):
        unpack(f, tmp_path / "out")
    assert not (tmp_path / "out").exists() and not (tmp_path / "evil.yaml").exists()


def test_links_are_refused(tmp_path):
    f = tmp_path / "link.dms"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("dms.json", json.dumps({"dms": 1, "format": FORMAT}))
        info = zipfile.ZipInfo("scenes/a.yaml")
        info.external_attr = 0o120777 << 16
        z.writestr(info, "/etc/passwd")
    with pytest.raises(DmsError, match="link"):
        unpack(f, tmp_path / "out")


def test_size_and_count_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(package, "MAX_ENTRIES", 5)
    f = _zip(tmp_path / "many.dms", {f"scenes/s{i}.yaml": b"x: 1\n" for i in range(6)})
    with pytest.raises(DmsError, match="too many"):
        unpack(f, tmp_path / "out")
    monkeypatch.setattr(package, "MAX_BYTES", 100)
    f = _zip(tmp_path / "big.dms", {"scenes/big.yaml": b"x: " + b"9" * 200 + b"\n"})
    with pytest.raises(DmsError, match="too big"):
        unpack(f, tmp_path / "out")


def test_bad_and_newer_files_refused(tmp_path):
    (tmp_path / "junk.dms").write_bytes(b"not a zip")
    with pytest.raises(DmsError, match="isn't a show file"):
        read_manifest(tmp_path / "junk.dms")
    with zipfile.ZipFile(tmp_path / "nomanifest.dms", "w") as z:
        z.writestr("fixtures.yaml", "x: 1\n")
    with pytest.raises(DmsError, match="no dms.json"):
        unpack(tmp_path / "nomanifest.dms", tmp_path / "o1")
    _zip(tmp_path / "newer.dms", {"fixtures.yaml": b"x: 1\n"}, {"dms": 2, "format": FORMAT, "app": "9.0"})
    with pytest.raises(DmsError, match="newer version"):
        unpack(tmp_path / "newer.dms", tmp_path / "o2")
    _zip(tmp_path / "newfmt.dms", {"fixtures.yaml": b"x: 1\n"}, {"dms": 1, "format": FORMAT + 1, "app": "9.0"})
    with pytest.raises(DmsError, match="newer version"):
        unpack(tmp_path / "newfmt.dms", tmp_path / "o3")


def test_failed_save_leaves_the_old_file(dms, tmp_path, monkeypatch):
    before = dms.read_bytes()

    def broken(self, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(zipfile.ZipFile, "writestr", broken)
    with pytest.raises(OSError):
        pack(SHOWS, dms)
    assert dms.read_bytes() == before
    assert [p.name for p in dms.parent.iterdir()] == [dms.name]  # no temp file left behind


def test_golden_frames_from_a_packed_show(dms, tmp_path):
    from golden import GOLDEN, capture

    out = tmp_path / "unpacked"
    unpack(dms, out)
    assert capture(root=out) == json.loads(GOLDEN.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ an open .dms


def test_edits_are_saved_into_the_file(dms):
    p = DmsProject(dms)
    p.open()
    assert p.work.is_relative_to(Path(os.environ["DMX_SUITE_DATA"]))  # app data, not OneDrive
    from dmx_suite.store import ShowStore

    s = ShowStore(p.work)
    s.after_commit = p.save
    s.put("scene", "dms_test", SCENE)
    assert "scenes/dms_test.yaml" in zipfile.ZipFile(dms).namelist()
    s.undo()
    assert "scenes/dms_test.yaml" not in zipfile.ZipFile(dms).namelist()
    p.close()
    assert not package.lock_path(dms).exists()


def test_unsaved_changes_are_kept_as_a_recovered_copy(dms):
    p = DmsProject(dms)
    p.open()
    (p.work / "scenes" / "lost.yaml").write_text(yaml.safe_dump({"version": FORMAT, **SCENE}))  # crash before pack
    p.close()
    q = DmsProject(dms)
    notes = q.open()
    assert q.recovered is not None and q.recovered.exists() and "recovered" in q.recovered.name
    assert re.search(r"\(recovered \d\d-\d\d-\d{4}\)\.dms$", q.recovered.name)
    assert "scenes/lost.yaml" in zipfile.ZipFile(q.recovered).namelist()
    assert not (q.work / "scenes" / "lost.yaml").exists()  # the working copy is the file again
    assert notes and "lost" not in "".join(zipfile.ZipFile(dms).namelist())


def test_file_open_elsewhere_opens_read_only(dms):
    other = {"pid": os.getppid(), "host": package._host(), "at": 0}  # a live process on this computer
    package.lock_path(dms).write_text(json.dumps(other))
    p = DmsProject(dms)
    p.open()
    assert p.read_only and "read-only" in p.notes[0]
    with pytest.raises(DmsError):
        p.save()
    p.close()
    assert package.lock_path(dms).exists()  # still theirs


def test_left_over_locks_are_taken(dms):
    package.lock_path(dms).write_text(json.dumps({"pid": 999_999_999, "host": package._host(), "at": 0}))
    p = DmsProject(dms)
    p.open()
    assert not p.read_only
    package.lock_path(dms).write_text(json.dumps({"pid": 1, "host": "other-laptop", "at": 0}))  # days old
    assert package.lock_holder(dms) is None


def test_save_as_moves_to_the_new_file(dms, tmp_path):
    p = DmsProject(dms)
    p.open()
    p.save_as(tmp_path / "Copy")
    assert p.dms == (tmp_path / "Copy.dms").resolve() and p.dms.exists()
    assert not package.lock_path(dms).exists() and package.lock_path(p.dms).exists()


# ------------------------------------------------------------------ the app on a .dms


def _args(dms, *extra):
    return resolve_shows(build_parser().parse_args(["--shows", str(dms), "run", "--sim", "--port", "0", *extra]))


def test_run_on_a_dms(dms):
    args = _args(dms)
    assert args.project is not None and args.shows == args.project.work
    session = start_session(args, out=lambda *a: None)
    try:
        app = session.app
        assert app.snapshot()["project"]["name"] == "Gig.dms"
        assert any(d["name"] == "Show file" and d["state"] == "ok" for d in app.devices())
        app.store.put("scene", "dms_live", SCENE)
        assert "scenes/dms_live.yaml" in zipfile.ZipFile(dms).namelist()
    finally:
        session.stop()
        args.project.close()


def test_read_only_app_refuses_edits_with_the_reason(dms):
    package.lock_path(dms).write_text(json.dumps({"pid": os.getppid(), "host": package._host(), "at": 0}))
    args = _args(dms)
    session = start_session(args, out=lambda *a: None)
    try:
        with pytest.raises(LockedError, match="open on another computer"):
            session.app.store.put("scene", "nope", SCENE)
        assert any(d["name"] == "Show file" and d["state"] == "warn" for d in session.app.devices())
    finally:
        session.stop()


def test_older_format_dms_is_upgraded_and_saved(tmp_path):
    root = tmp_path / "v1"
    shutil.copytree(SHOWS, root)
    for p in show_files(root):
        text = re.sub(r"^version: \d+\n", "", (root / p).read_text(encoding="utf-8"), flags=re.M)
        if kind_of(root / p) == "rig":
            text = re.sub(r"^# Rule profile.*\nprofile: .*\n", "", text, flags=re.M)
        (root / p).write_text(text, encoding="utf-8")
    f = tmp_path / "old.dms"
    pack(root, f)
    args = _args(f)
    session = start_session(args, out=lambda *a: None)
    session.stop()
    args.project.close()
    rig = yaml.safe_load(zipfile.ZipFile(f).read("rigs/full.yaml"))
    assert rig["version"] == FORMAT and rig["profile"] == "0.05_band"


def test_one_off_commands_read_a_copy(dms, capsys):
    assert main(["--shows", str(dms), "check"]) == 0
    assert "Gig" not in str(list(Path(os.environ["DMX_SUITE_DATA"]).glob("open/*")))  # no working copy made


def test_pack_and_unpack_commands(tmp_path, capsys):
    f = tmp_path / "x.dms"
    assert main(["pack", str(SHOWS), str(f)]) == 0
    assert main(["unpack", str(f), str(tmp_path / "out")]) == 0
    assert content_hash(tmp_path / "out") == content_hash(SHOWS)
    assert main(["unpack", str(f), str(tmp_path / "out")]) == 1  # not into a full folder


def test_restart_command_line(monkeypatch):
    monkeypatch.setattr(sys, "orig_argv", ["python3", "-m", "dmx_suite.cli", "--shows", "a.dms", "run", "--sim"], raising=False)
    monkeypatch.setattr(sys, "argv", ["cli.py", "--shows", "a.dms", "run", "--sim"])
    assert restart_argv(Path("/x/b.dms")) == ["python3", "-m", "dmx_suite.cli", "--shows", "/x/b.dms", "run", "--sim"]
    monkeypatch.setattr(sys, "orig_argv", ["C:/app/0.05 DMX Suite.exe"], raising=False)
    monkeypatch.setattr(sys, "argv", ["C:/app/0.05 DMX Suite.exe"])
    assert restart_argv(Path("/x/b.dms")) == ["C:/app/0.05 DMX Suite.exe", "--shows", "/x/b.dms"]


def test_installed_app_starts_a_new_dms_from_the_starter_shows(tmp_path, monkeypatch):
    from dmx_suite import paths

    monkeypatch.setattr(paths, "frozen", lambda: True)
    monkeypatch.setattr(paths, "bundled_shows", lambda: SHOWS)
    f = tmp_path / "Music" / "0.05 shows.dms"
    assert paths.prepare(f) == f and f.exists() and is_dms(f)
    assert "rigs/full.yaml" in zipfile.ZipFile(f).namelist()


# ------------------------------------------------------------------ the server


UI = "ui-token-0123456789abcdefgh"
CLAUDE = "claude-token-0123456789abcd"


def call(port, path, method="GET", body=None, token=UI, raw=None, ctype="application/json"):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=data,
                                 headers={"Content-Type": ctype, "X-DMX-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            b = r.read()
            return r.status, (json.loads(b) if r.headers.get_content_type() == "application/json" else b)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def served(dms):
    from dmx_suite.web.server import WebServer

    args = _args(dms, "--no-web")
    session = start_session(args, out=lambda *a: None)
    restarts = []
    session.app.on_restart = restarts.append
    web = WebServer(session.app, "127.0.0.1", 0, token=UI, claude_token=CLAUDE)
    web.start()
    yield session.app, web.port, restarts, dms
    web.stop()
    session.stop()
    args.project.close()


def test_project_info_download_and_save_as(served, tmp_path):
    app, port, _, dms = served
    info = call(port, "/api/project")[1]
    assert info["project"]["name"] == "Gig.dms" and info["local"]
    status, data = call(port, "/api/project/download")
    assert status == 200 and zipfile.ZipFile(io.BytesIO(data)).read("dms.json")
    status, r = call(port, "/api/project/save_as", "POST", {"path": str(tmp_path / "Second")})
    assert status == 200 and r["project"]["name"] == "Second.dms"
    assert call(port, "/api/project/save_as", "POST", {"path": str(tmp_path / "Second.dms")})[0] == 409
    assert call(port, "/api/project")[1]["recent"][0].endswith("Second.dms")


def test_open_new_and_upload_restart_the_app(served, tmp_path):
    app, port, restarts, dms = served
    assert call(port, "/api/project/open", "POST", {"path": str(tmp_path / "missing.dms")})[0] == 404
    assert call(port, "/api/project/open", "POST", {"path": "relative.dms"})[0] == 400
    (tmp_path / "junk.dms").write_bytes(b"junk")
    assert call(port, "/api/project/open", "POST", {"path": str(tmp_path / "junk.dms")})[0] == 400
    assert call(port, "/api/project/new", "POST", {"path": str(tmp_path / "Fresh")})[1]["restarting"]
    assert restarts[-1] == tmp_path / "Fresh.dms" and (tmp_path / "Fresh.dms").exists()
    other = tmp_path / "Other.dms"
    pack(SHOWS, other)
    assert call(port, "/api/project/open", "POST", {"path": str(other)})[0] == 200 and restarts[-1] == other
    status, r = call(port, "/api/project/upload?name=Phone%20show.dms", "POST", raw=other.read_bytes(),
                     ctype="application/octet-stream")
    assert status == 200 and restarts[-1] == dms.parent / "Phone show.dms"
    status, r = call(port, "/api/project/upload?name=bad.dms", "POST", raw=b"junk", ctype="application/octet-stream")
    assert status == 400 and not (dms.parent / "bad.dms").exists()
    app.set_gig_lock(True)
    assert call(port, "/api/project/open", "POST", {"path": str(other)})[0] == 423
    assert call(port, "/api/project/open", "POST", {"path": str(other)}, token=CLAUDE)[0] == 403


# ------------------------------------------------------------------ Claude on a .dms


def test_claude_offline_writes_into_the_dms(dms):
    tools = DmxTools(shows=dms, url="http://127.0.0.1:9", token=CLAUDE)
    assert "dms_claude" not in tools.list("scene")
    assert "saved" in tools.save("scene", "dms_claude", "name: c\nlayers:\n  - {fixtures: [bars], colour: red}\n")
    assert "scenes/dms_claude.yaml" in zipfile.ZipFile(dms).namelist()
    assert not package.lock_path(dms).exists()
    pack(SHOWS, dms)  # the file is replaced (the app saved, OneDrive synced)
    tools.refresh()
    assert "dms_claude" not in tools.list("scene")


def test_claude_offline_refused_while_the_file_is_open_elsewhere(dms):
    tools = DmxTools(shows=dms, url="http://127.0.0.1:9", token=CLAUDE)
    package.lock_path(dms).write_text(json.dumps({"pid": 1, "host": "gig-laptop", "at": __import__("time").time()}))
    with pytest.raises(StoreError, match="open on gig-laptop"):
        tools.save("scene", "x", "name: c\nlayers:\n  - {fixtures: [bars], colour: red}\n")


def test_second_launch_hands_the_file_to_the_running_app(dms, tmp_path):
    from dmx_suite.desktop import hand_over

    args = resolve_shows(build_parser().parse_args(["--shows", str(dms), "run", "--sim", "--port", "0"]))
    session = start_session(args, out=lambda *a: None)
    try:
        restarts = []
        session.app.on_restart = restarts.append
        other = tmp_path / "Double clicked.dms"
        pack(SHOWS, other)
        assert hand_over(session.web.port, other)
        assert restarts == [other.resolve()]
        assert not hand_over(session.web.port, tmp_path / "folder")  # not a .dms: nothing to hand over
    finally:
        session.stop()
        args.project.close()
