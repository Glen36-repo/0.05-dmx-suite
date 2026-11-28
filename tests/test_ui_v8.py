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
    host = page.locator("#layout-grid").bounding_box()
    cell = page.evaluate("() => { const r = document.querySelector('#layout-grid svg').getScreenCTM(); return r.a * 24; }")
    x, y = box["x"] + box["width"] / 2, host["y"] + 20  # on the line, inside the stage
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


# ---------------------------------------------------------------- FX settings panel (item 14)


def rig_ap(root):
    return yaml.safe_load((root / "rigs" / "full.yaml").read_text(encoding="utf-8")).get("autopilot") or {}


def wait_rig(page, root, fn):
    for _ in range(120):
        if fn(rig_ap(root)):
            return True
        page.wait_for_timeout(25)
    return False


def test_badge_cycles_without_playing_and_exclude_mode_restores(ui):
    page, app, root, _ = ui
    go(page, "autopilot")
    tile = "#ride-colour [data-fx=rainbow]"
    page.wait_for_selector(f"{tile} .prio")
    before = app.ride_pick.colour
    assert page.text_content(f"{tile} .prio") == "3"
    size = page.eval_on_selector(f"{tile} .prio", "e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; }")
    assert size[0] >= 28 and size[1] >= 32  # its own touch target
    page.click(f"{tile} .prio")
    page.wait_for_function(f"document.querySelector('{tile} .prio').textContent === '4'")
    page.click(f"{tile} .prio")
    page.wait_for_function(f"document.querySelector('{tile} .prio').textContent === '5'")
    page.click(f"{tile} .prio")
    page.wait_for_function(f"document.querySelector('{tile} .prio').textContent === '1'")  # 5 -> 1, never 0
    assert app.ride_pick.colour == before  # the badge never plays the tile
    page.click(f"{tile} .prio")  # 2
    page.wait_for_function(f"document.querySelector('{tile} .prio').textContent === '2'")
    page.click("#ride-exclude")
    page.click(f"{tile} .lbl")
    page.wait_for_selector(f"{tile}.excluded")
    page.wait_for_function(f"document.querySelector('{tile} .prio').textContent === '0'")
    assert wait_rig(page, root, lambda a: a.get("fx", {}).get("rainbow") == {"priority": 0, "restore": 2})
    page.click(f"{tile} .lbl")  # put back: its old priority
    page.wait_for_function(f"document.querySelector('{tile} .prio').textContent === '2'")
    page.click("#ride-exclude")


def test_panel_params_duplicate_and_gig_lock(ui):
    page, app, root, _ = ui
    go(page, "autopilot")
    tile = "#ride-move [data-fx=fan]"
    page.wait_for_selector(tile)
    page.click(f"{tile} .lbl", button="right")
    page.wait_for_selector("#fx-panel[open] #fxp-p-period_s")
    assert page.get_attribute("#fxp-p-period_s", "placeholder") == "6"  # the default shows, empty = default
    page.fill("#fxp-p-period_s", "9")
    page.select_option("#fxp-dark", "exempt")
    page.uncheck("#fx-panel [data-mood=high]")
    page.click("#fxp-save")
    page.wait_for_selector("#fx-panel:not([open])", state="attached")
    assert wait_rig(page, root, lambda a: a.get("fx", {}).get("fan") == {"darkness": "exempt", "moods": ["mid"],
                                                                         "params": {"period_s": 9}})
    page.wait_for_selector(f"{tile} .ovr:not(.hidden)", state="attached")
    page.click(f"{tile} .lbl", button="right")
    page.wait_for_selector("#fx-panel[open] #fxp-dup")
    assert page.input_value("#fxp-p-period_s") == "9" and page.input_value("#fxp-dark") == "exempt"
    page.click("#fxp-dup")
    page.wait_for_selector("#fx-panel[open] #fxp-name")  # the new variant's panel
    page.wait_for_selector("#ride-move [data-fx=fan_v1]")
    page.fill("#fxp-name", "Fan slow")
    page.click("#fxp-save")
    page.wait_for_selector("#ride-move [data-fx=fan_v1]:has-text('Fan slow')")
    assert rig_ap(root)["variants"]["fan_v1"]["params"] == {"period_s": 9}
    app.set_gig_lock(True)
    page.wait_for_selector("#giglock.on")  # the page has heard
    page.click("#ride-move [data-fx=fan_v1] .lbl", button="right")
    page.wait_for_selector("#fx-panel[open] #fxp-save")
    assert page.is_disabled("#fxp-save") and page.is_disabled("#fxp-preview") and page.is_disabled("#fxp-p-period_s")
    page.click("#fxp-close")
