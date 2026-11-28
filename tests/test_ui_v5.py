# ruff: noqa: F811 - pytest fixtures imported from test_ui are used as arguments
"""v5 browser tests: Monitor test patterns, cycle test, health checks, fault-find."""

import pytest
from test_ui import browser, go, ui  # noqa: F401,F811 - pytest fixtures

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
