# ruff: noqa: F811 - pytest fixtures imported from test_ui are used as arguments
"""v5 browser tests: Monitor test patterns, cycle test, health checks, fault-find."""

import shutil

import pytest
import yaml
from test_ui import SHOWS, TOKEN, browser, go, ui  # noqa: F401,F811 - pytest fixtures

from dmx_suite.app import App
from dmx_suite.output import make_driver
from dmx_suite.showfiles import load_show
from dmx_suite.web.server import WebServer

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def test_monitor_test_panel_runs_and_stops_on_leave(ui):
    page, app, root, _ = ui
    go(page, "monitor")
    page.wait_for_selector("#test-target option", state="attached")
    page.select_option("#test-pattern", "chase")
    assert page.is_visible("#test-dwell") and not page.is_visible("#test-fixture")
    page.select_option("#test-pattern", "all_full")
    page.click("#test-go")
    page.wait_for_selector("#test-live:not(.hidden)")
    assert "All full" in page.inner_text("#test-name")
    page.wait_for_function("document.querySelector('#mon-dmx-stats').textContent.startsWith('TEST: All full')")
    assert "testing" in page.get_attribute("#mon-dmx", "class")
    assert page.eval_on_selector("#test-stop", "e => e.getBoundingClientRect().height") >= 44  # big Stop
    assert app.engine.test is not None and app.engine.test.by == "ui"
    go(page, "live")  # leaving the page stops it
    page.wait_for_function("() => true")
    for _ in range(50):
        if app.engine.test is None:
            break
        page.wait_for_timeout(50)
    assert app.engine.test is None and app.engine.test_log[-1]["what"] == "page left"


def test_monitor_test_panel_stop_button_and_gig_lock(ui):
    page, app, root, _ = ui
    go(page, "monitor")
    page.wait_for_selector("#test-target option", state="attached")
    page.select_option("#test-pattern", "find")
    page.click("#test-go")
    page.wait_for_selector("#test-live:not(.hidden)")
    page.click("#test-stop")
    page.wait_for_selector("#test-live.hidden", state="attached")
    assert app.engine.test is None
    app.set_gig_lock(True)
    page.wait_for_function("() => true")
    page.select_option("#test-pattern", "all_full")
    page.wait_for_function("document.querySelector('#test-go').disabled")
    page.select_option("#test-pattern", "keep_alive")
    assert not page.is_disabled("#test-go")
    app.set_gig_lock(False)


@pytest.fixture
def open_ui(browser, tmp_path):
    """The UI with a USB DMX (Open) output (its port doesn't exist here)."""
    from dmx_suite import settings

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    p = root / "rigs" / "full.yaml"
    rig = yaml.safe_load(p.read_text())
    rig["outputs"] = [{"driver": "usb_dmx_open", "port": "COM_NONE", "universe": 0, "alias": "Stage DMX"}]
    p.write_text(yaml.safe_dump(rig))
    files = load_show(root)
    app = App(files, [make_driver(o) for o in files.rig.outputs])
    app.engine.start()
    settings.save({"wizard": "skipped"})
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN)
    web.start()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{web.port}/?t={TOKEN}")
    page.wait_for_selector("body.ready", timeout=10000)
    yield page, app, p
    page.close()
    web.stop()
    app.engine.stop()
    for d in app.engine.drivers:
        d.close()
    assert errors == []


def test_cycle_methods_big_step_and_lights_responded(open_ui, monkeypatch):
    from dmx_suite import dmxcheck

    page, app, p = open_ui
    monkeypatch.setattr(dmxcheck, "STEP_S", 1.5)
    app.engine.drivers[0]._d2xx_available = lambda: False
    go(page, "monitor")
    page.wait_for_selector("#test-target option[value='o:0']", state="attached")
    page.select_option("#test-target", "o:0")
    page.wait_for_selector("#cycle-go:not(.hidden)")
    page.click("#cycle-go")
    page.wait_for_selector("#cycle-live:not(.hidden)")
    assert page.inner_text("#cycle-step") == "Serial break, 176 µs"
    assert page.eval_on_selector("#cycle-step", "e => parseFloat(getComputedStyle(e).fontSize)") >= 36
    page.wait_for_function("document.querySelector('#cycle-step').textContent.startsWith('Baud drop')")
    page.click("#cycle-yes")
    page.wait_for_function("document.querySelector('#cycle-result').textContent.startsWith('Saved: Baud drop')")
    assert yaml.safe_load(p.read_text())["outputs"][0]["break_method"] == "baud_drop"


def test_timing_and_checks_shown(open_ui):
    from test_v5_checks import FakeProbe, FakeRegistry

    page, app, p = open_ui
    app.registry = FakeRegistry("COM_NONE")
    app.health_probe = FakeProbe(latency=16, suspend_plan=False)
    app.check_outputs()
    go(page, "monitor")
    page.wait_for_selector("#test-target option[value='o:0']", state="attached")
    page.wait_for_function("document.querySelector('#mon-dmx-timing').textContent.includes('target 176')")
    assert "VCP" in page.inner_text("#mon-dmx-timing")
    page.wait_for_function("document.querySelector('#mon-dmx-checks').textContent.includes('Latency timer: 16 ms')")
    go(page, "layout")
    page.wait_for_function("[...document.querySelectorAll('#lp-routing td')].some(td => td.textContent.includes('break'))")
    cell = page.locator("#lp-routing td.amber")
    assert cell.count() == 1 and "Latency timer" in cell.get_attribute("title")


def test_fault_find_wizard(open_ui):
    from test_v5_checks import FakeProbe, FakeRegistry

    page, app, p = open_ui
    app.registry = FakeRegistry("COM_NONE")
    app.health_probe = FakeProbe(latency=1, suspend_plan=False)
    go(page, "monitor")
    page.click("#ff-open")
    page.wait_for_selector("#ff:not(.hidden)")
    page.wait_for_function("document.querySelector('#ff-text').textContent.includes('auto / sound')")
    page.click("#ff-answers button:has-text('Yes')")
    page.wait_for_function("document.querySelector('#ff-where').textContent === 'Step 1 of 5'")
    assert "cycle test" in page.inner_text("#ff-text")
    assert page.locator("#ff-answers button:has-text('Run test')").count() == 1
    page.click("#ff-answers button:has-text('Fail')")
    page.wait_for_function("document.querySelector('#ff-where').textContent === 'Step 2 of 5'")
    page.click("#ff-answers button:has-text('Pass')")
    page.wait_for_function("document.querySelector('#ff-text').textContent.startsWith('found at')")
    assert page.locator("#ff-history li").count() == 4
    assert "Start again" in page.inner_text("#ff-answers")


def test_red_dmx_badge_opens_the_wizard(open_ui):
    from test_v5_checks import FakeProbe, FakeRegistry

    page, app, p = open_ui
    app.registry = FakeRegistry("COM_NONE")
    app.health_probe = FakeProbe(latency=16, suspend_plan=False)
    app.check_outputs()
    page.wait_for_selector(".tile.link[data-key^='dmx_check:']")
    page.click(".tile.link[data-key^='dmx_check:']")
    page.wait_for_selector("#page-monitor.on")
    page.wait_for_selector("#ff:not(.hidden)")
