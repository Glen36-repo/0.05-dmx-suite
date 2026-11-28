# ruff: noqa: F811 - pytest fixtures imported from test_package are used as arguments
"""v7 Part E: Save and the save setting (Auto-save / Manual save), the last file on launch, the start-up
state (Autopilot on, LOW, MASTER on once an output is connected; or resume)."""

import zipfile

import pytest
import yaml
from test_package import CLAUDE, SCENE, SHOWS, UI, _args, call, dms, served  # noqa: F401

from dmx_suite import settings
from dmx_suite.cli import build_parser, resolve_shows, start_session
from dmx_suite.package import pack


def dms_scene(path, name):
    with zipfile.ZipFile(path) as z:
        return f"scenes/{name}.yaml" in z.namelist()


# ------------------------------------------------------------------ E1 save setting


def test_settings_values():
    assert settings.load()["save_mode"] == "auto" and settings.load()["startup"] == "autopilot_low"
    with pytest.raises(ValueError, match="save_mode"):
        settings.save({"save_mode": "sometimes"})
    with pytest.raises(ValueError, match="startup"):
        settings.save({"startup": "dark"})


def test_auto_save_writes_every_change(served):
    app, port, _, f = served
    app.store.put("scene", "auto_one", SCENE)
    assert dms_scene(f, "auto_one") and not app.unsaved()


def test_manual_save_waits_for_save(served):
    app, port, _, f = served
    settings.save({"save_mode": "manual"})
    app.store.put("scene", "manual_one", SCENE)
    assert not dms_scene(f, "manual_one") and app.unsaved()  # in the working copy only
    info = call(port, "/api/project")[1]["project"]
    assert info["dirty"] and info["save_mode"] == "manual"
    assert any("unsaved" in d["detail"] for d in app.devices() if d["name"] == "Show file")
    status, r = call(port, "/api/project/save", "POST", {})
    assert status == 200 and not r["project"]["dirty"] and dms_scene(f, "manual_one")


def test_unsaved_changes_guard_open_and_new(served, tmp_path):
    app, port, restarts, f = served
    settings.save({"save_mode": "manual"})
    app.store.put("scene", "guarded", SCENE)
    other = tmp_path / "Other.dms"
    pack(SHOWS, other)
    status, r = call(port, "/api/project/open", "POST", {"path": str(other)})
    assert status == 409 and "unsaved" in r["error"] and not restarts
    assert call(port, "/api/project/new", "POST", {"path": str(tmp_path / "Fresh")})[0] == 409
    assert call(port, "/api/project/open", "POST", {"path": str(other), "save": True})[0] == 200
    assert restarts[-1] == other and dms_scene(f, "guarded")  # saved first
    app.store.put("scene", "dropped", SCENE)
    assert call(port, "/api/project/open", "POST", {"path": str(other), "discard": True})[0] == 200
    assert not dms_scene(f, "dropped")  # left in the working copy (recovered next time it's opened)


def test_save_on_a_folder_says_so(tmp_path):
    from dmx_suite.app import App
    from dmx_suite.output import LogDriver
    from dmx_suite.showfiles import load_show

    app = App(load_show(SHOWS), [LogDriver()])
    with pytest.raises(ValueError, match="saved as it's made"):
        app.save_project()


def test_save_needs_the_laptop(served):
    app, port, *_ = served
    assert call(port, "/api/project/save", "POST", {}, token=CLAUDE)[0] in (403, 423)


# ------------------------------------------------------------------ E2 last file on launch


def test_launch_opens_the_last_file(dms, tmp_path):
    settings.add_recent(str(dms))
    args = resolve_shows(build_parser().parse_args(["run", "--sim", "--port", "0"]))
    try:
        assert args.project is not None and args.project.dms == dms.resolve() and not args.launch_notes
    finally:
        args.project.close()


def test_launch_with_a_missing_last_file_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("DMX_SUITE_SHOWS", str(SHOWS))
    settings.add_recent(str(tmp_path / "OneDrive" / "Not synced.dms"))
    args = resolve_shows(build_parser().parse_args(["run", "--sim", "--port", "0"]))
    assert args.project is None and args.shows == SHOWS.resolve() or args.shows == SHOWS
    assert "Not synced.dms" in args.launch_notes[0] and "OneDrive" in args.launch_notes[0]
    session = start_session(args, out=lambda *a: None)
    try:
        assert any(d["name"] == "Last show file" and d["state"] == "warn" for d in session.app.devices())
    finally:
        session.stop()


def test_no_recent_file_uses_the_default(monkeypatch):
    monkeypatch.setenv("DMX_SUITE_SHOWS", str(SHOWS))
    args = resolve_shows(build_parser().parse_args(["run", "--sim", "--port", "0"]))
    assert args.launch_notes == [] and args.project is None


def test_shows_on_the_command_line_wins(dms):
    settings.add_recent(str(SHOWS))
    args = _args(dms)
    try:
        assert args.project is not None and args.project.dms == dms.resolve()
    finally:
        args.project.close()


# ------------------------------------------------------------------ E3 start-up state


def session_for(dms, *extra):
    args = _args(dms, "--no-web", *extra)
    return args, start_session(args, out=lambda *a: None)


def test_default_start_up_is_autopilot_low_master_on(dms):
    args, s = session_for(dms)
    try:
        app = s.app
        assert app.autopilot.st.on and app.autopilot.st.mood == "low" and app.autopilot.st.mood_manual
        assert app.engine.master and app.engine.haze.mode.value == "off"
        assert not app.waiting_for_output
    finally:
        s.stop()
        args.project.close()


def test_start_up_waits_for_an_output(dms, monkeypatch):
    from dmx_suite.app import App

    monkeypatch.setattr(App, "output_connected", lambda self: getattr(self, "_connected", False))
    args, s = session_for(dms)
    try:
        app = s.app
        assert app.waiting_for_output and not app.autopilot.st.on and app.engine.master
        app._connected = True
        for _ in range(40):
            if app.autopilot.st.on:
                break
            import time

            time.sleep(0.05)
        assert app.autopilot.st.on and not app.waiting_for_output and app.autopilot.st.mood == "low"
    finally:
        s.stop()
        args.project.close()


def test_start_up_loads_the_low_sets_darkness(dms, tmp_path):
    from dmx_suite.package import DmsProject

    p = DmsProject(dms)
    p.open()
    rig = yaml.safe_load((p.work / "rigs" / "full.yaml").read_text())
    rig["autopilot"] = {"set_darkness": {"low": 40}}
    (p.work / "rigs" / "full.yaml").write_text(yaml.safe_dump(rig))
    p.save()
    p.close()
    args, s = session_for(dms)
    try:
        s.app.darkness(s.app.engine.clock())
        assert s.app.darkness.status()["darkness"] == 40
    finally:
        s.stop()
        args.project.close()


def test_resume_setting_keeps_the_v4_restore(dms, monkeypatch):
    from dmx_suite.showctl import ShowController

    calls = []
    monkeypatch.setattr(ShowController, "restore", lambda self: calls.append(1) or True)
    settings.save({"startup": "resume"})
    args, s = session_for(dms)
    try:
        assert calls and not s.app.autopilot.st.on  # the v4 restore, no Autopilot start
    finally:
        s.stop()
        args.project.close()
    calls.clear()
    settings.save({"startup": "autopilot_low"})
    args, s = session_for(dms)
    try:
        assert not calls and s.app.autopilot.st.on and s.app.engine.master  # the default doesn't resume
    finally:
        s.stop()
        args.project.close()


# ------------------------------------------------------------------ desktop: Quit with unsaved changes


def test_quit_asks_about_unsaved_changes(served, monkeypatch):
    from types import SimpleNamespace

    from dmx_suite import desktop

    app, *_ = served
    settings.save({"save_mode": "manual"})
    app.store.put("scene", "quit_test", SCENE)
    answers = []

    class Win:
        destroyed = False

        def create_confirmation_dialog(self, title, msg):
            return answers.pop(0)

        def destroy(self):
            self.destroyed = True

    d = desktop.Desktop.__new__(desktop.Desktop)
    d.session, d.window, d.quitting = SimpleNamespace(app=app), Win(), False
    answers[:] = [False, False]  # don't save -> don't quit either: stay open
    d.quit()
    assert not d.window.destroyed and app.unsaved()
    answers[:] = [True]  # save, then quit
    d.quit()
    assert d.window.destroyed and not app.unsaved()


# ------------------------------------------------------------------ Windows: the file held for a moment


def test_pack_retries_when_the_file_is_held_a_moment(tmp_path, monkeypatch):
    import os

    from dmx_suite import package

    real, fails = os.replace, [2]

    def held(src, dst):
        if str(dst).endswith(".dms") and fails[0]:
            fails[0] -= 1
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(src, dst)

    monkeypatch.setattr(package.os, "replace", held)
    monkeypatch.setattr(package.time, "sleep", lambda s: None)
    out = tmp_path / "Held.dms"
    pack(SHOWS, out)  # two refusals, then it goes through
    assert out.exists() and fails[0] == 0
    fails[0] = 99
    with pytest.raises(PermissionError):
        pack(SHOWS, tmp_path / "Never.dms")
    assert not list(tmp_path.glob(".Never.*.tmp"))  # no temp file left behind


def test_a_save_that_keeps_failing_is_a_save_error_not_a_403(served, monkeypatch):
    from dmx_suite import package

    app, port, *_ = served
    settings.save({"save_mode": "manual"})
    app.store.put("scene", "stuck", SCENE)

    def held(*a):
        raise PermissionError(13, "being used by another process")

    monkeypatch.setattr(package, "_replace", held)
    status, r = call(port, "/api/project/save", "POST", {})
    assert status == 409 and "couldn't save" in r["error"] and app.unsaved()
