# ruff: noqa: F811 - pytest fixtures imported from test_ui are used as arguments
"""v4 browser tests: density, stage view, Layout/Patch, Monitor, step editor, renames.

Uses the Playwright fixtures from test_ui (skipped when no browser is available).
"""

import shutil

import pytest
import screenshot_rig
from test_ui import PAGES, SHOWS, TOKEN, browser, go, ui  # noqa: F401,F811 - pytest fixtures

from dmx_suite.app import App
from dmx_suite.output import LogDriver
from dmx_suite.showfiles import load_show
from dmx_suite.web.server import WebServer

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

@pytest.fixture
def shot(browser, tmp_path):
    """The UI on the screenshot rig from the v4 brief (stacked, crowded layout)."""
    from dmx_suite import settings

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    screenshot_rig.make(root)
    app = App(load_show(root), [LogDriver()])
    app.engine.start()
    settings.save({"wizard": "skipped"})
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN)
    web.start()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(f"http://127.0.0.1:{web.port}/?t={TOKEN}")
    page.wait_for_selector("body.ready", timeout=10000)
    yield page, app, root, errors
    page.close()
    web.stop()
    app.engine.stop()
    assert errors == []


CLIPPED = """() => [...document.querySelectorAll('section.page.on button, section.page.on select, header.top button')]
  .filter(b => b.offsetParent && getComputedStyle(b).textOverflow !== 'ellipsis' && !b.closest('.menu'))
  .filter(b => b.scrollWidth > b.clientWidth + 1 || b.scrollHeight > b.clientHeight + 2)
  .map(b => (b.id || b.className || b.tagName) + ':' + b.textContent.trim().slice(0, 20))"""


def heights(page, sel="#page-setup #update-check"):
    return page.eval_on_selector(sel, "e => e.getBoundingClientRect().height")


def test_density_compact_default_and_comfortable(ui):
    page, *_ = ui
    assert page.eval_on_selector("body", "b => b.className").startswith("density-compact")
    go(page, "setup")
    compact = heights(page)
    assert 26 <= compact <= 30
    assert page.eval_on_selector("#master", "e => e.getBoundingClientRect().height") >= 44  # live control stays big
    page.select_option("#density", "comfortable")
    page.wait_for_function("document.body.classList.contains('density-comfortable')")
    assert heights(page) > compact + 6
    page.reload()
    page.wait_for_selector("body.ready")
    assert "density-comfortable" in page.eval_on_selector("body", "b => b.className")


@pytest.mark.parametrize("width,scale", [(1280, 1), (1280, 1.25), (1600, 1)])
def test_no_clipped_controls(browser, ui, width, scale):  # noqa: F811
    page, *_ = ui
    ctx = browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=scale)
    p2 = ctx.new_page()
    p2.goto(page.url)
    p2.wait_for_selector("body.ready")
    bad = {}
    for name in PAGES:
        go(p2, name)
        p2.wait_for_timeout(150)
        clipped = p2.evaluate(CLIPPED)
        if clipped:
            bad[name] = clipped
    ctx.close()
    assert bad == {}


def test_focus_outline_visible(ui):
    page, *_ = ui
    go(page, "setup")
    page.focus("#update-check")
    page.keyboard.press("Tab")
    page.keyboard.press("Shift+Tab")
    style = page.eval_on_selector("#update-check", "e => getComputedStyle(e).outlineStyle")
    assert style != "none"


# ---------------------------------------------------------------- stage view (items 1-5)

FILL = """sel => { const host = document.querySelector(sel), g = host.querySelector('svg.lightgrid > g:nth-of-type(3)');
  const h = host.getBoundingClientRect(), b = g.getBoundingClientRect();
  return Math.max(b.width / h.width, b.height / h.height); }"""


def test_layout_zooms_to_fit_and_back(ui):
    page, *_ = ui
    go(page, "layout")
    page.wait_for_selector("#layout-grid [data-id=bar_1]")
    assert page.evaluate(FILL, "#layout-grid") > 0.75  # the rig fills the box, not a speck in the middle
    vb = page.eval_on_selector("#layout-grid svg", "s => s.getAttribute('viewBox')")
    box = page.locator("#layout-grid svg").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, -300)
    page.wait_for_function("document.querySelector('#layout-fit').classList.contains('primary')")
    assert page.eval_on_selector("#layout-grid svg", "s => s.getAttribute('viewBox')") != vb
    page.click("#layout-fit")
    assert page.eval_on_selector("#layout-grid svg", "s => s.getAttribute('viewBox')") == vb
    assert "primary" not in page.eval_on_selector("#layout-fit", "b => b.className")


BOXES = """els => els.map(e => { const b = e.getBoundingClientRect();
  return {x: b.x, y: b.y, w: b.width, h: b.height, id: e.closest('[data-id]')?.dataset.id, text: e.textContent}; })"""


def boxes(page, sel):
    return page.eval_on_selector_all(sel, BOXES)


def overlap(a, b, gap=0.0):
    return (a["x"] < b["x"] + b["w"] - gap and b["x"] < a["x"] + a["w"] - gap
            and a["y"] < b["y"] + b["h"] - gap and b["y"] < a["y"] + a["h"] - gap)


def test_pixel_bars_are_one_object_each(shot):
    page, *_ = shot
    for name, host in (("layout", "#layout-grid"), ("live", "#live-grid")):
        go(page, name)
        page.wait_for_selector(f"{host} [data-id=bar_1] .outline")
        outs = {b["id"]: b for b in boxes(page, f"{host} .outline")}
        assert sorted(outs) == ["bar_1", "bar_2", "bar_3", "bar_4"]
        for a, b in (("bar_1", "bar_2"), ("bar_2", "bar_3"), ("bar_3", "bar_4")):
            assert not overlap(outs[a], outs[b]) and outs[b]["x"] - (outs[a]["x"] + outs[a]["w"]) > 0.5  # a gap shows
        for bid, o in outs.items():
            label = boxes(page, f"{host} [data-id={bid}] .name")[0]
            assert abs((label["x"] + label["w"] / 2) - (o["x"] + o["w"] / 2)) < 2  # centred under its bar
            assert label["y"] >= o["y"] + o["h"] - 1
