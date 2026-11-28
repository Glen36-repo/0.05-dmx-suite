# ruff: noqa: F811 - pytest fixtures imported from test_ui are used as arguments
"""v8 Part A in the browser: stage centrelines on the Layout and Live pages."""

import yaml
from test_ui import browser, go, ui  # noqa: F401 - pytest fixtures


def rig_layout(root):
    return yaml.safe_load((root / "rigs" / "full.yaml").read_text(encoding="utf-8")).get("layout") or {}


def line_x(page, grid="#layout-grid"):
    return float(page.get_attribute(f"{grid} .centrelines .cl[data-axis=x]", "x1")) / 24


def test_centrelines_type_drag_save_reset(ui):
    page, app, root, _ = ui
    go(page, "layout")
    page.wait_for_selector("#layout-grid .centrelines.auto .cl[data-axis=x]", state="attached")
    auto = app.engine.rig.layout_centre()
    assert abs(line_x(page) - auto[0]) < 1e-6
    assert float(page.input_value("#centre-x")) == auto[0] and page.is_disabled("#centre-reset")
    page.fill("#centre-x", "6.3")
    page.press("#centre-x", "Tab")
    page.wait_for_selector("#layout-grid .centrelines:not(.auto)", state="attached")
    assert line_x(page) == 6.5  # snapped to half cells
    page.wait_for_selector("#layout-dirty:not(.hidden)")
    page.click("#layout-save")
    page.wait_for_selector("#layout-dirty.hidden", state="attached")
    assert rig_layout(root)["centre"]["x"] == 6.5
    assert app.engine.rig.centre[0] == 6.5
    # drag the vertical line two cells right
    box = page.locator("#layout-grid .cl-hit[data-centre=x]").bounding_box()
    cell = page.evaluate("() => { const r = document.querySelector('#layout-grid svg').getScreenCTM(); return r.a * 24; }")
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 2 * cell, y, steps=6)
    page.mouse.up()
    assert abs(line_x(page) - 8.5) <= 0.5
    assert abs(float(page.input_value("#centre-x")) - line_x(page)) < 1e-6
    page.click("#centre-reset")
    page.wait_for_selector("#layout-grid .centrelines.auto", state="attached")
    page.click("#layout-save")
    page.wait_for_selector("#layout-dirty.hidden", state="attached")
    assert "centre" not in rig_layout(root) and app.engine.rig.centre is None


def test_live_toggle(ui):
    page, *_ = ui
    assert page.locator("#live-grid .centrelines .cl").count() == 0  # off by default
    page.check("#live-centre")
    page.wait_for_selector("#live-grid .centrelines .cl[data-axis=y]", state="attached")
    assert page.locator("#live-grid .cl-hit").count() == 0  # can't be dragged on Live
    page.reload()
    page.wait_for_selector("body.ready")
    page.wait_for_selector("#live-grid .centrelines .cl", state="attached")  # remembered
