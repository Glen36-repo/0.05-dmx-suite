# ruff: noqa: F811 - pytest fixtures imported from test_ui are used as arguments
"""v7 browser tests: tick-box picker, Autopilot page (palette bank, layers, darkness, between songs)."""

import pytest
from test_ui import SHOWS, TOKEN, browser, go, ui  # noqa: F401,F811 - pytest fixtures

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

PICKER = """async () => {
  const { picker } = await import('/static/js/picker.js');
  window.picked = null;
  const p = picker({
    items: [{id: 'b1', label: 'b1', group: 'bar'}, {id: 'b2', label: 'b2', group: 'bar'},
            {id: 'mh', label: 'mh', group: 'head'}, {id: 'kick', label: 'kick', group: 'kick'}],
    groups: [{id: 'head', label: 'Moving heads', count: (n) => n + ' heads'},
             {id: 'bar', label: 'Pixel bars', count: (n) => n + ' bars'}, {id: 'kick', label: 'Kick'}],
    value: ['b1'], all: 'All lights', label: 'Targets', onChange: (ids) => { window.picked = ids; } });
  p.id = 'test-picker';
  document.body.prepend(p);
}"""


def _text(page):
    return page.inner_text("#test-picker .picker-text")


def test_picker_groups_all_none_and_summary(ui):
    page = ui[0]
    page.evaluate(PICKER)
    assert _text(page) == "b1"
    page.click("#test-picker summary")
    assert page.is_visible("#test-picker .picker-body")
    assert page.eval_on_selector("#test-picker [data-group=bar]", "b => b.indeterminate")
    page.check("#test-picker [data-group=bar]")
    assert _text(page) == "2 bars" and page.evaluate("window.picked") == ["b1", "b2"]
    page.check("#test-picker [data-item=kick]")
    assert _text(page) == "2 bars, kick"
    page.click("#test-picker [data-pick=all]")
    assert _text(page) == "All lights" and page.evaluate("window.picked") == ["b1", "b2", "mh", "kick"]
    page.uncheck("#test-picker [data-group=head]")
    assert _text(page) == "2 bars, kick"
    page.click("#test-picker [data-pick=none]")
    assert _text(page) == "None" and page.evaluate("window.picked") == []
    page.mouse.click(1200, 880)  # an outside tap closes it
    assert not page.is_visible("#test-picker .picker-body")


def test_picker_escape_closes_and_set_does_not_fire(ui):
    page = ui[0]
    page.evaluate(PICKER)
    page.click("#test-picker summary")
    page.keyboard.press("Escape")
    assert not page.is_visible("#test-picker .picker-body")
    page.evaluate("document.querySelector('#test-picker').set(['mh'])")
    assert _text(page) == "mh" and page.evaluate("window.picked") is None
    assert page.evaluate("document.querySelector('#test-picker').value") == ["mh"]


def test_picker_touch_targets_on_a_phone(browser):
    import shutil
    import tempfile
    from pathlib import Path

    from dmx_suite import settings
    from dmx_suite.app import App
    from dmx_suite.output.base import LogDriver
    from dmx_suite.showfiles import load_show
    from dmx_suite.web.server import WebServer

    root = Path(tempfile.mkdtemp()) / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    app = App(load_show(root), [LogDriver()])
    app.engine.start()
    settings.save({"wizard": "skipped"})
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN)
    web.start()
    page = browser.new_page(viewport={"width": 390, "height": 800}, has_touch=True)
    try:
        page.goto(f"http://127.0.0.1:{web.port}/?t={TOKEN}")
        page.wait_for_selector("#menu")
        page.evaluate(PICKER)
        page.click("#test-picker summary")
        for sel in ("#test-picker summary", "#test-picker .picker-item"):
            assert page.eval_on_selector(sel, "e => e.getBoundingClientRect().height") >= 44
        size = page.eval_on_selector("#test-picker .picker-text", "e => parseFloat(getComputedStyle(e).fontSize)")
        assert size >= 12
    finally:
        page.close()
        web.stop()
        app.engine.stop()


# ------------------------------------------------------------------ A2 palette bank


def rig_auto_key(app, key, want=None, page=None):
    """The rig file's auto: <key>; with `want`, waits for the save (tiles turn red at once)."""
    import yaml

    got = []
    for _ in range(80):
        data = yaml.safe_load((app.files.root / "rigs" / f"{app.names[0]}.yaml").read_text(encoding="utf-8"))
        got = (data.get("auto") or {}).get(key) or []
        if want is None or got == want:
            return got
        page.wait_for_timeout(25)
    return got


def test_palette_tiles_play_and_exclude(ui):
    page, app, *_ = ui
    go(page, "autopilot")
    tile = "#ride-palettes [data-palette=fire]"
    page.wait_for_selector(tile)
    assert page.eval_on_selector_all(f"{tile} .sw i", "s => s.length") == 4  # swatches
    assert page.inner_text(f"{tile} .tags") == "HIGH"  # mood tags
    page.click(tile)  # tap = play now
    page.wait_for_selector(f"{tile}.sel")
    assert app.ride_pick.palette == "fire"
    page.click("#ride-exclude")
    page.click("#ride-palettes [data-palette=ice]")  # Exclude mode: red, saved, not played
    page.wait_for_selector("#ride-palettes [data-palette=ice].excluded")
    assert rig_auto_key(app, "exclude_palettes", ["ice"], page) == ["ice"] and app.ride_pick.palette == "fire"
    page.click("#ride-exclude")
    page.click("#ride-palettes [data-palette=ice]")  # a tap still plays an excluded palette
    page.wait_for_selector("#ride-palettes [data-palette=ice].excluded.sel")
    go(page, "live")
    go(page, "autopilot")  # stays red on the page
    page.wait_for_selector("#ride-palettes [data-palette=ice].excluded")


def test_palette_long_press_excludes(ui):
    page, app, *_ = ui
    go(page, "autopilot")
    tile = "#ride-palettes [data-palette=neon]"
    page.wait_for_selector(tile)
    box = page.eval_on_selector(tile, "e => { const r = e.getBoundingClientRect(); "
                                      "return [r.x + r.width / 2, r.y + r.height / 2]; }")
    page.mouse.move(*box)
    page.mouse.down()
    page.wait_for_timeout(750)
    page.mouse.up()
    page.wait_for_selector(f"{tile}.excluded")
    assert rig_auto_key(app, "exclude_palettes", ["neon"], page) == ["neon"]
