"""Desktop app: window, tray behaviour, start-up errors and a second launch, with a fake pywebview."""

from pathlib import Path

import pytest

from dmx_suite import desktop
from dmx_suite.cli import build_parser, resolve_shows, start_session


def running(session):
    return session.engine._thread is not None and not session.engine._stop.is_set()


SHOWS = Path(__file__).resolve().parents[1] / "shows"


class Events:
    def __init__(self):
        self.closing = Handlers()


class Handlers(list):
    def __iadd__(self, fn):
        self.append(fn)
        return self

    def fire(self):
        return all(fn() is not False for fn in self)


class FakeWindow:
    def __init__(self, title, url=None, html=None, **kw):
        self.title, self.url, self.html, self.kw = title, url, html, kw
        self.events = Events()
        self.visible = True
        self.destroyed = False
        self.confirm_answer = True

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def restore(self):
        pass

    def destroy(self):
        self.destroyed = True

    def close(self):
        """What the window's close button does."""
        if self.events.closing.fire():
            self.destroy()

    def create_confirmation_dialog(self, title, message):
        return self.confirm_answer

    def evaluate_js(self, code):
        return "dmx-suite ready"  # the real page's application-name meta, once main.js has started


class FakeWebview:
    def __init__(self):
        self.windows = []
        self.during = None  # runs while the window is "open"

    def create_window(self, title, url=None, html=None, **kw):
        w = FakeWindow(title, url, html, **kw)
        self.windows.append(w)
        return w

    def start(self, func=None, icon=None):
        self.icon = icon
        if func:
            func()
        if self.during:
            self.during(self.windows[-1])


class FakeTray:
    def __init__(self, on_open, on_blackout, is_blackout, on_quit):
        self.on_open, self.on_blackout, self.is_blackout, self.on_quit = on_open, on_blackout, is_blackout, on_quit
        self.running = False
        self.notes = []

    def run_detached(self):
        self.running = True

    def stop(self):
        self.running = False

    def notify(self, msg, title):
        self.notes.append(msg)


def app_args(*extra):
    return resolve_shows(build_parser().parse_args(["--shows", str(SHOWS), "app", "--sim", "--port", "0", *extra]))


@pytest.fixture
def tray(monkeypatch):
    made = []

    def make(*a):
        made.append(FakeTray(*a))
        return made[-1]

    monkeypatch.setattr(desktop, "make_tray", make)
    return made


def test_opens_window_on_running_engine_and_close_hides_to_tray(tray):
    wv = FakeWebview()
    seen = {}

    def during(win):
        d = seen["d"]
        assert running(d.session)
        assert win.url == desktop.ui_url(d.session.web.port)
        assert desktop.running_ui(d.session.web.port)  # real UI served
        win.close()  # close button: hide, lights keep running
        assert not win.destroyed and not win.visible
        assert running(d.session)
        assert tray[0].notes  # told once where it went
        tray[0].on_open()
        assert win.visible
        tray[0].on_blackout()
        assert tray[0].is_blackout()
        tray[0].on_quit()  # tray Quit really closes
        assert win.destroyed

    d = desktop.Desktop(app_args(), wv, start_session)
    seen["d"] = d
    wv.during = during
    assert d.run() == 0
    assert not running(d.session)  # stopped after the window closed
    assert not tray[0].running


def test_without_tray_close_asks_first(monkeypatch):
    monkeypatch.setattr(desktop, "make_tray", lambda *a: None)
    wv = FakeWebview()

    def during(win):
        win.confirm_answer = False
        win.close()
        assert not win.destroyed
        win.confirm_answer = True
        win.close()
        assert win.destroyed

    wv.during = during
    d = desktop.Desktop(app_args(), wv, start_session)
    assert d.run() == 0
    assert not running(d.session)


def test_show_file_problem_shows_error_page(tmp_path, tray):
    (tmp_path / "fixtures.yaml").write_text("not: [valid")
    args = resolve_shows(build_parser().parse_args(["--shows", str(tmp_path), "app", "--sim", "--port", "0"]))
    wv = FakeWebview()
    d = desktop.Desktop(args, wv, start_session)
    assert d.run() == 2
    (win,) = wv.windows
    assert win.url is None and "Show file problem" in win.html
    assert d.session is None and not tray


def test_second_launch_opens_window_on_running_app(tray):
    first = start_session(app_args())
    try:
        args = app_args()
        args.port = first.web.port
        started = []
        wv = FakeWebview()
        d = desktop.Desktop(args, wv, lambda a: started.append(a))
        assert d.run() == 0
        assert not started  # no second engine
        assert wv.windows[0].url == desktop.ui_url(first.web.port)
        assert running(first)
    finally:
        first.stop()


def test_smoke_test_checks_the_page_then_quits(tray):
    wv = FakeWebview()
    d = desktop.Desktop(app_args("--smoke-test", "0"), wv, start_session)
    assert d.run() == 0
    assert wv.windows[0].destroyed


def test_error_page_escapes_detail():
    assert "&lt;script&gt;" in desktop.error_page("x", "<script>")


@pytest.mark.parametrize(
    "argv, expected",
    [
        ([], ["app"]),
        (["--sim"], ["app", "--sim"]),
        (["--shows", "X", "--sim"], ["--shows", "X", "app", "--sim"]),
        (["--shows=X"], ["--shows=X", "app"]),
        (["check"], ["check"]),
        (["--shows", "X", "run", "--sim"], ["--shows", "X", "run", "--sim"]),
    ],
)
def test_windowed_exe_defaults_to_app(monkeypatch, argv, expected):
    got = []
    monkeypatch.setattr("dmx_suite.cli.main", lambda a: got.append(a) or 0)
    desktop.main(argv)
    assert got == [expected]


def test_icon_only_passed_off_windows(tray, monkeypatch):
    for platform, expected in (("win32", None), ("linux", str(desktop.ICON))):
        monkeypatch.setattr(desktop.sys, "platform", platform)
        wv = FakeWebview()
        desktop.Desktop(app_args("--smoke-test", "0"), wv, start_session).run()
        assert wv.icon == expected


def test_closed_window_connection_is_not_an_error(caplog):
    """Closing the window drops its live-update stream; Windows reports that as ConnectionAbortedError."""
    import urllib.request

    session = start_session(app_args())
    try:
        def gone():
            raise ConnectionAbortedError(10053, "aborted")

        session.app.snapshot = gone
        try:
            urllib.request.urlopen(desktop.ui_url(session.web.port) + "api/events", timeout=2).read()
        except OSError:
            pass
        assert "API error" not in caplog.text
    finally:
        session.stop()
