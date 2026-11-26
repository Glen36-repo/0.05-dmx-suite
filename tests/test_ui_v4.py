# ruff: noqa: F811 - pytest fixtures imported from test_ui are used as arguments
"""v4 browser tests: density, stage view, Layout/Patch, Monitor, step editor, renames.

Uses the Playwright fixtures from test_ui (skipped when no browser is available).
"""

import pytest
from test_ui import PAGES, browser, go, ui  # noqa: F401,F811 - pytest fixtures

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

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
