"""The browser UI, driven in a real browser (Playwright + Chromium) against a simulated rig.

Skipped when Playwright or a browser isn't available. CI installs both.
"""

import os
import shutil
import time
from pathlib import Path

import pytest
import yaml

from dmx_suite.app import App
from dmx_suite.output import LogDriver
from dmx_suite.showfiles import load_show
from dmx_suite.web.server import WebServer

pw = pytest.importorskip("playwright.sync_api")

SHOWS = Path(__file__).resolve().parents[1] / "shows"
TOKEN = "ui-test-token-0123456789abcdef"
CHROMIUM = os.environ.get("DMX_TEST_CHROMIUM", "/opt/pw-browsers/chromium")


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:  # noqa: BLE001 - fall back to a browser installed outside Playwright
            if not Path(CHROMIUM).exists():
                pytest.skip("no browser for Playwright")
            b = p.chromium.launch(executable_path=CHROMIUM, args=["--headless", "--no-sandbox"])
        yield b
        b.close()


@pytest.fixture
def ui(browser, tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    app = App(load_show(root), [LogDriver()])
    app.engine.start()
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
    assert errors == []  # no script errors anywhere in the test


def go(page, name):
    page.click(f"#menu [data-page={name}]")
    page.wait_for_selector(f"#page-{name}.on")


def cell_fill(page, grid, fid, i=0):
    return page.eval_on_selector(f"{grid} [data-id='{fid}'] .cell >> nth={i}", "e => e.style.fill")


def drag(page, start, end, steps=8):
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(*end, steps=steps)
    page.mouse.up()


def centre(page, selector):
    box = page.locator(selector).first.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def test_menu_texts_and_pages(ui):
    page, *_ = ui
    assert page.inner_text("#menu [data-page=layout]").strip().endswith("Layout")
    for name in ("layout", "heads", "midi", "setup", "files", "live"):
        go(page, name)
        assert page.is_visible(f"#page-{name}")
    assert "{" not in page.inner_text("body")  # every placeholder filled from the strings file
    page.click("#collapse")
    assert "narrow-menu" in page.get_attribute(".shell", "class")
    assert not page.is_visible("#menu [data-page=live] .lbl")


def test_live_grid_shows_live_colours(ui):
    page, app, *_ = ui
    page.wait_for_function("document.querySelector(\"#live-grid [data-id='bar_1'] .cell\").style.fill !== ''")
    assert page.locator("#live-grid [data-id='bar_1'] .cell").count() == 8  # one square per pixel
    green = cell_fill(page, "#live-grid", "bar_1")
    page.click("#master")  # MASTER off: the rig goes dark on screen too
    page.wait_for_function("document.querySelector(\"#live-grid [data-id='bar_1'] .cell\").style.fill === ''")
    assert green and not app.engine.master


def test_group_tab_selects_its_lights(ui):
    page, *_ = ui
    go(page, "layout")
    page.click("#group-tabs [data-group=bars]")
    assert page.locator("#layout-grid .fx.sel").count() == 4
    assert "4 selected" in page.inner_text("#layout-sel")


def test_box_select_and_lasso(ui):
    page, *_ = ui
    go(page, "layout")
    a = page.locator("#layout-grid [data-id='mh_a'] .cell").bounding_box()
    b = page.locator("#layout-grid [data-id='uking_r'] .cell").bounding_box()
    drag(page, (a["x"] - 10, a["y"] - 10), (b["x"] + b["width"] + 10, b["y"] + b["height"] + 10))
    assert sorted(page.eval_on_selector_all("#layout-grid .fx.sel", "es => es.map(e => e.dataset.id)")) == \
        ["mh_a", "mh_b", "uking_l", "uking_r"]
    page.click("[data-tool=lasso]")
    w = page.locator("#layout-grid [data-id='wash_l'] .cell").bounding_box()
    x, y = w["x"] + w["width"] / 2, w["y"] + w["height"] / 2
    page.mouse.move(x - 15, y - 15)
    page.mouse.down()
    for dx, dy in ((15, -15), (15, 15), (-15, 15), (-15, -15)):
        page.mouse.move(x + dx, y + dy, steps=3)
    page.mouse.up()
    assert page.eval_on_selector_all("#layout-grid .fx.sel", "es => es.map(e => e.dataset.id)") == ["wash_l"]


def test_move_arrange_undo_and_save(ui):
    page, app, root, _ = ui
    go(page, "layout")
    page.click("#group-tabs [data-group=washes]")
    page.click("[data-tool=move]")
    start = centre(page, "#layout-grid [data-id='wash_l'] .cell")
    drag(page, start, (start[0] + 60, start[1] + 60))
    assert not page.is_disabled("#layout-save")
    moved = app.catalogue()["layout"]["wash_l"]  # not saved yet
    page.click("[data-make=ring]")
    page.click("#layout-undo")
    page.click("#layout-save")
    page.wait_for_selector("#toast:not(.hidden)")
    saved = yaml.safe_load((root / "rigs" / "full.yaml").read_text(encoding="utf-8"))["layout"]
    assert set(saved) >= {"wash_l", "wash_r"}
    assert (saved["wash_l"]["x"], saved["wash_l"]["y"]) != (moved["x"], moved["y"])
    assert app.engine.rig.layout["wash_l"].x == saved["wash_l"]["x"]  # live, no restart
    assert page.is_disabled("#layout-save")


def test_pixel_shape_changes_the_drawing(ui):
    page, *_ = ui
    go(page, "layout")
    page.click("#group-tabs [data-group=bars]")
    before = page.locator("#layout-grid [data-id='bar_1'] .cell").nth(4).bounding_box()
    page.click("[data-shape=ring]")
    after = page.locator("#layout-grid [data-id='bar_1'] .cell").nth(4).bounding_box()
    assert abs(before["y"] - after["y"]) > 10  # half the pixels now sit below the others


def test_make_group_from_selection(ui):
    page, app, root, _ = ui
    go(page, "layout")
    page.click("#group-tabs [data-group=washes]")
    page.click("#layout-grid [data-id='kick'] .cell", modifiers=["Shift"])
    page.fill("#group-name", "front")
    page.click("#group-new")
    page.wait_for_selector("#group-tabs [data-group=front]")
    assert sorted(app.catalogue()["groups"]["front"]) == ["kick", "wash_l", "wash_r"]
    assert "front" in (root / "fixtures.yaml").read_text(encoding="utf-8")
    page.fill("#group-name", "downstage")
    page.click("#group-rename")
    page.wait_for_selector("#group-tabs [data-group=downstage]")
    page.on("dialog", lambda d: d.accept())
    page.click("#group-delete")
    page.wait_for_selector("#group-tabs [data-group=downstage]", state="detached")


def test_theme_switch(ui):
    page, *_ = ui
    go(page, "setup")
    page.wait_for_selector("#theme option[value='005']", state="attached")
    with page.expect_navigation():
        page.select_option("#theme", "005")
    page.wait_for_selector("body.ready")
    assert page.title() == "0.05 DMX Suite"
    assert page.locator("link[href='/static/themes/005/theme.css']").count() == 1


def test_phone_layout_has_bottom_menu(ui):
    page, *_ = ui
    page.set_viewport_size({"width": 390, "height": 844})
    time.sleep(0.2)
    box = page.locator("#menu").bounding_box()
    assert box["y"] > 700 and box["width"] >= 380  # a bar along the bottom
    go(page, "layout")
    assert page.is_visible("#layout-grid")


# ------------------------------------------------------------------ scene builder (v2 R3)


def effect_select(page):
    return page.locator("#layer-form .field:has(> span:text-is('Effect')) select")


def test_open_a_scene_shows_its_layers(ui):
    page, *_ = ui
    go(page, "scenes")
    page.select_option("#scene-pick", "blue_chase")
    page.wait_for_function("document.querySelectorAll('#layers li').length === 5")
    assert "Pixel chase" in page.inner_text("#layers li >> nth=0")
    assert page.input_value("#scene-name") == "Blue chase"


def test_build_save_and_preview_a_scene(ui):
    page, app, root, _ = ui
    go(page, "scenes")
    page.click("#scene-group-tabs [data-group=bars]")
    page.click("#layer-add")
    effect_select(page).select_option("linear_wave")
    page.locator("#layer-form .field:has(> span:text-is('angle')) input[type=number]").fill("90")
    page.locator("#layer-form .field:has(> span:text-is('angle')) input[type=number]").dispatch_event("change")
    page.check("#scene-preview")
    page.wait_for_function("document.querySelector('#scene-preview-note').textContent.includes('one cycle')")
    deadline = time.time() + 3
    while app.snapshot()["preview_s"] is None and time.time() < deadline:
        time.sleep(0.05)
    assert app.snapshot()["preview_s"] is not None  # playing on the rig, unsaved
    page.fill("#scene-name", "Test wave")
    page.click("#scene-save")
    page.wait_for_function("document.querySelector('#scene-state').textContent.includes('test_wave')")
    data = yaml.safe_load((root / "scenes" / "test_wave.yaml").read_text(encoding="utf-8"))
    assert data["name"] == "Test wave"
    assert data["layers"] == [{"fixtures": ["bars"], "colour": "white", "effect": "linear_wave", "angle": 90}]
    assert "test_wave" in app.catalogue()["scenes"]
    page.uncheck("#scene-preview")
    deadline = time.time() + 3
    while app.snapshot()["preview_s"] is not None and time.time() < deadline:
        time.sleep(0.05)
    assert app.snapshot()["preview_s"] is None


def test_rule_breaking_layer_is_marked(ui):
    page, *_ = ui
    go(page, "scenes")
    page.click("#scene-group-tabs [data-group=heads]")  # includes the colour-only U'Kings
    page.click("#layer-add")
    effect_select(page).select_option("circle")
    page.locator("#layer-form .field:has(> span:text-is('centre')) select").select_option("drum_kit")
    page.wait_for_selector("#layers li.error")
    assert "rule 7" in page.inner_text("#scene-error")
    page.click("#scene-group-tabs [data-group=movers]")
    page.click("#layer-form button:text-is('Use selected lights')")
    page.wait_for_selector("#scene-error.hidden", state="attached")
    assert page.locator("#layers li.error").count() == 0


def test_mute_and_reorder(ui):
    page, _, root, _ = ui
    go(page, "scenes")
    page.select_option("#scene-pick", "red_movers")
    page.wait_for_selector("#layers li")
    n = page.locator("#layers li").count()
    first = page.inner_text("#layers li >> nth=0 >> .name")
    page.click("#layers li >> nth=0 >> button[title='Move down']")
    assert page.inner_text("#layers li >> nth=1 >> .name") == first
    page.click("#layers li >> nth=1 >> button[title^='Mute']")
    page.click("#scene-save")
    page.wait_for_function("!document.querySelector('#scene-state').textContent.includes('unsaved')")
    data = yaml.safe_load((root / "scenes" / "red_movers.yaml").read_text(encoding="utf-8"))
    assert len(data["layers"]) == n and data["layers"][1].get("mute") is True
