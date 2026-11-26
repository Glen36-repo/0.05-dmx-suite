"""The browser UI, driven in a real browser (Playwright + Chromium) against a simulated rig.

Skipped when Playwright or a browser isn't available. CI installs both.
"""

import json
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
def ui(browser, tmp_path, request):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    app = App(load_show(root), [LogDriver()])
    app.engine.start()
    if not request.node.get_closest_marker("first_run"):
        from dmx_suite import settings

        settings.save({"wizard": "skipped"})  # the setup wizard would open over every test
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN)
    web.start()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.web = web  # for tests that change access settings
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
    if not page.is_visible(f"#menu [data-page={name}]"):  # phones: the page sits behind More
        page.click("#menu-more")
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
    page.wait_for_selector("#layout-save:disabled")


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


PAGES = ("live", "ride", "busk", "scenes", "shows", "review", "palettes", "layout", "fixtures", "heads", "midi", "setup", "files")


def test_phone_layout_has_bottom_menu(ui):
    page, *_ = ui
    page.set_viewport_size({"width": 390, "height": 844})
    time.sleep(0.2)
    box = page.locator("#menu").bounding_box()
    assert box["y"] > 700 and box["width"] >= 380  # a bar along the bottom
    assert page.is_visible("#menu-more") and not page.is_visible("#menu [data-page=layout]")
    for name in PAGES:  # every page can be reached from the bar or More
        go(page, name)
        assert page.is_visible(f"#page-{name}")
        assert not page.locator("#menu").evaluate("m => m.classList.contains('open')")  # More closes again
        # nothing runs off the side of the phone
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), name
    assert "on" in page.get_attribute("#menu-more", "class")  # lit while a More page is showing
    go(page, "live")
    assert "on" not in page.get_attribute("#menu-more", "class")


def test_menu_groups_on_desktop(ui):
    page, *_ = ui
    assert page.locator(".menu-group").count() == 4
    assert not page.is_visible("#menu-more")
    assert all(page.is_visible(f"#menu [data-page={n}]") for n in PAGES)


def light_boxes(page, host):
    """Size of one light square, and how much of the host's width and height the lights cover."""
    return page.evaluate("""(host) => {
        const h = document.querySelector(host).getBoundingClientRect();
        const cells = [...document.querySelectorAll(host + ' .cell')].map((c) => c.getBoundingClientRect());
        const x0 = Math.min(...cells.map((c) => c.left)), x1 = Math.max(...cells.map((c) => c.right));
        const y0 = Math.min(...cells.map((c) => c.top)), y1 = Math.max(...cells.map((c) => c.bottom));
        return { cell: cells[0].width, w: (x1 - x0) / h.width, h: (y1 - y0) / h.height };
    }""", host)


def test_scene_picker_lights_are_big(ui):
    page, *_ = ui
    go(page, "scenes")
    page.wait_for_selector("#scene-grid .cell")
    b = light_boxes(page, "#scene-grid")
    assert b["cell"] >= 15 and b["w"] >= 0.8, b  # was ~8 px squares in a third of the box
    page.set_viewport_size({"width": 390, "height": 844})
    time.sleep(0.3)
    b = light_boxes(page, "#scene-grid")
    assert b["cell"] >= 16, b  # a phone scrolls sideways rather than shrink them
    page.click("#scene-grid [data-id=bar_1] .cell >> nth=0")
    assert "bar_1" in page.inner_text("#scene-sel")


def test_group_pills_none_and_invert(ui):
    page, *_ = ui
    go(page, "scenes")
    page.click("#scene-group-tabs [data-group=bars]")
    assert page.inner_text("#scene-group-tabs [data-group=bars] .n") == "4"
    page.click("#pick-invert")
    assert "bar_1" not in page.inner_text("#scene-sel") and "mh_a" in page.inner_text("#scene-sel")
    page.click("#pick-none")
    assert page.locator("#scene-grid .fx.sel").count() == 0


def test_live_and_ride_lights_fill_their_box(ui):
    page, *_ = ui
    for name, host in (("live", "#live-grid"), ("ride", "#ride-grid")):
        go(page, name)
        page.wait_for_selector(f"{host} .cell")
        b = light_boxes(page, host)
        assert max(b["w"], b["h"]) >= 0.7, (name, b)  # fills the box one way or the other


def test_setup_claude_section_folds(ui):
    page, *_ = ui
    go(page, "setup")
    page.wait_for_selector("#claude-connect .claude-steps")
    assert page.get_attribute("#claude-section", "open") is not None  # not connected yet: open
    page.click("#claude-section > summary")
    assert page.get_attribute("#claude-section", "open") is None
    go(page, "live")
    page.click(".tile.link")  # the Claude tile opens it again
    page.wait_for_selector("#page-setup.on")
    assert page.get_attribute("#claude-section", "open") is not None


def test_fixtures_clash_bar_only_when_clashing(ui):
    page, *_ = ui
    go(page, "fixtures")
    page.wait_for_selector("#fx-patch tr")
    assert not page.is_visible("#fx-clash")
    page.fill("#fx-patch tr >> nth=1 >> input >> nth=2", "1")  # mh_b on mh_a's address
    page.locator("#fx-patch tr >> nth=1 >> input >> nth=2").dispatch_event("change")
    page.wait_for_selector("#fx-clash", state="visible")


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


# ------------------------------------------------------------------ shows, setlists, busk (v2 R5)


def test_edit_a_show_into_steps_with_repeats(ui):
    page, app, root, _ = ui
    shows_page(page)
    page.select_option("#show-pick", "band")
    page.click("#set-tabs [data-set=cues]")
    rows = page.locator("#set-form .steps-edit li")
    assert rows.count() == 3  # v1 scenes + step_s opened as steps
    first = rows.nth(0)
    first.locator("select").nth(0).select_option("blue_chase")
    first.locator("select").nth(1).select_option("repeats")
    first.locator("input").nth(0).fill("3")
    first.locator("input").nth(0).dispatch_event("change")
    page.locator("#set-form .field:has(> span:text-is('Fade (s)')) input").fill("1.5")
    page.locator("#set-form .field:has(> span:text-is('Fade (s)')) input").dispatch_event("change")
    page.click("#show-save")
    page.wait_for_function("document.querySelector('#show-state').textContent.includes('shows/band.yaml')")
    data = yaml.safe_load((root / "shows" / "band.yaml").read_text(encoding="utf-8"))
    cues = data["sets"]["cues"]
    assert cues["steps"][0] == {"scene": "blue_chase", "repeats": 3} and cues["fade_s"] == 1.5
    assert "scenes" not in cues and data["sets"]["mid"]["auto"]["energy"] == "mid"  # auto sets untouched
    assert app.files.shows["band"].sets["cues"].steps[0].repeats == 3


def shows_page(page):
    go(page, "shows")
    page.wait_for_selector("body[data-shows-ready='1']")


def test_new_show_plays_and_steps_can_be_tapped(ui):
    page, app, root, _ = ui
    shows_page(page)
    page.click("#show-new")
    page.fill("#show-name", "Test show")
    for _ in range(3):
        page.click("#set-form button:text-is('Add step')")
    page.click("#show-save")
    page.wait_for_function("document.querySelector('#show-state').textContent.includes('test_show')")
    app.ctl.select_show("test_show")
    go(page, "live")
    page.wait_for_selector("#steps li")
    assert page.locator("#steps li").count() == 3
    page.click("#steps [data-step='2']")
    page.wait_for_selector("#steps li.cur [data-step='2']")
    assert app.ctl.now().step_index == 2
    assert "s left" in page.inner_text("#step-info")


def test_setlist_editor(ui):
    page, _, root, _ = ui
    shows_page(page)
    page.wait_for_selector("#songs-edit li")
    n = page.locator("#songs-edit li").count()
    page.click("#song-add")
    row = page.locator("#songs-edit li").nth(n)
    row.locator("input").fill("Encore")
    row.locator("select").last.select_option("off")
    page.click("#setlist-save")
    page.wait_for_selector("#toast:not(.hidden)")
    data = yaml.safe_load((root / "setlists" / "example.yaml").read_text(encoding="utf-8"))
    assert data["songs"][-1]["name"] == "Encore" and data["songs"][-1]["master"] is False


def test_make_and_play_a_busk_panel(ui):
    page, app, root, _ = ui
    go(page, "busk")
    page.check("#busk-edit")
    page.wait_for_selector("#busk-editor[data-ready='1']")
    page.fill("#panel-key", "band")
    page.fill("#panel-name", "Band busk")
    page.click("#panel-new")
    page.select_option("#widget-type", "colour")
    page.click("#widget-add")
    page.select_option("#widget-type", "solo")
    page.click("#widget-add")
    page.click("#panels-save")
    page.wait_for_function("document.querySelectorAll('#busk [data-widget]').length === 2")
    assert (root / "panels.yaml").exists() and "band" in app.files.panels
    page.uncheck("#busk-edit")
    page.click("#busk [data-widget=colour1]")  # a latch: on
    page.wait_for_selector("#busk [data-widget=colour1].on")
    go(page, "live")
    page.wait_for_selector("#live-grid .fx.held")  # the held lights are marked on the layout
    go(page, "busk")
    page.click("#busk-release")
    page.wait_for_selector("#busk [data-widget=colour1]:not(.on)")
    assert app.engine.held() == []


def test_set_a_pin_and_turn_on_phone_access(ui):
    page, _, _, _ = ui
    go(page, "setup")
    page.wait_for_selector("#access-state:not(:empty)")
    assert page.is_disabled("#access-lan")  # needs a PIN first
    page.fill("#pin-new", "2468")
    page.click("#pin-set")
    page.wait_for_selector("#access-lan:not([disabled])")
    page.check("#access-lan")
    page.wait_for_selector("#lan-info:not(.hidden)")


def test_sign_in_page(ui):
    page, _, _, errors = ui
    web = page.web
    web.access.set_pin("2468")
    web.access.configure(pin_local=True)
    page.goto(f"http://127.0.0.1:{web.port}/")
    page.wait_for_selector("body.ready #pin")
    page.fill("#pin", "0000")
    page.click("button[type=submit]")
    page.wait_for_selector("#login-error:not(:empty)")
    page.fill("#pin", "2468")
    page.click("button[type=submit]")
    page.wait_for_selector("#master")
    page.wait_for_selector("body.ready")
    errors[:] = [e for e in errors if "401" not in e]  # the wrong PIN, on purpose


def test_undo_a_scene_edit(ui):
    page, app, root, _ = ui
    app.store.put("scene", "ui_undo", {"name": "UI undo", "layers": [{"fixtures": ["bars"], "colour": "red"}]})
    app.reload()
    go(page, "files")
    page.wait_for_selector("#history li")
    assert "put scene ui_undo" in page.inner_text("#history")
    page.click("#undo")
    page.wait_for_selector("#history li.undone")
    assert not (root / "scenes" / "ui_undo.yaml").exists()
    go(page, "live")
    page.keyboard.press("Control+y")  # redo from any page
    page.wait_for_function("document.querySelector('#toast').textContent.startsWith('Redone')")
    assert (root / "scenes" / "ui_undo.yaml").exists()


def test_paste_maps_a_look_by_what_each_light_can_do(ui):
    page, *_ = ui
    go(page, "scenes")
    page.wait_for_selector("#scene-group-tabs [data-group=movers]")
    look = {"colour": "red", "position": "drum_kit", "gobo": "dots", "effect": "sweep"}
    layers = page.evaluate("""async (look) => {
        const m = await import('/static/js/paste.js');
        const cat = await (await fetch('/api/catalogue')).json();
        const fx = (await (await fetch('/api/effects')).json()).effects;
        return m.pasteLayers(m.copyLook({fixtures: ['movers'], mute: false, ...look}),
            ['mh_a', 'mh_b', 'uking_l', 'bar_1'], ['mh_a', 'mh_b', 'uking_l', 'bar_1'], cat.fixtures, fx);
    }""", look)
    by = {tuple(ly["fixtures"]): ly for ly in layers}
    assert by[("mh_a", "mh_b")] == {"fixtures": ["mh_a", "mh_b"], **look}  # movers take everything
    # the colour-only head and the bar can do the same: one layer, colour only
    assert by[("uking_l", "bar_1")] == {"fixtures": ["uking_l", "bar_1"], "colour": "red"}
    assert len(layers) == 2


def test_copy_and_paste_in_the_scene_builder(ui):
    page, *_ = ui
    go(page, "scenes")
    page.click("#scene-group-tabs [data-group=washes]")
    page.click("#layer-add")
    page.click("#look-copy")
    page.wait_for_selector("#toast:not(.hidden)")
    page.click("#scene-group-tabs [data-group=bars]")
    page.keyboard.press("Control+v")
    page.wait_for_function("document.querySelectorAll('#layers li').length === 2")
    assert "bars" in page.inner_text("#layers li >> nth=1")


def test_show_file_section_upload_and_download(ui, tmp_path):
    from dmx_suite.package import pack

    page, app, root, _ = ui
    restarts = []
    app.on_restart = restarts.append
    go(page, "files")
    page.wait_for_selector("#project-now code")
    assert str(root) in page.inner_text("#project-now")  # a plain show folder
    with page.expect_download() as dl:
        page.click("#project-download")
    assert dl.value.suggested_filename.endswith(".dms")
    (tmp_path / "phone").mkdir()
    f = tmp_path / "phone" / "Phone.dms"
    pack(root, f)
    page.on("dialog", lambda d: d.accept())
    page.set_input_files("#project-upload", str(f))
    page.wait_for_selector("body.restarting")
    assert restarts and restarts[0].name == "Phone.dms"


def test_lost_connection_overlay(ui):
    page, *_ = ui
    page.wait_for_function("document.querySelector('#health .tile')")  # connected first
    assert not page.is_visible("#offline")
    page.evaluate("document.body.classList.add('offline')")  # what the page does when the stream drops
    assert page.is_visible("#offline") and "Lost the connection" in page.inner_text("#offline")


def test_fader_follows_the_state_after_a_finger_slides_off(ui):
    page, app, _, _ = ui
    f = page.locator("#faders input[data-key=grand]")
    box = f.bounding_box()
    page.mouse.move(box["x"] + 5, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 200)  # off the fader
    page.mouse.up()
    page.locator("#now").click()  # focus elsewhere
    app.engine.set_grand(0.3)
    page.wait_for_function("document.querySelector('#faders input[data-key=grand]').value === '30'")


def test_layer_picks_its_group_tab(ui):
    page, *_ = ui
    go(page, "scenes")
    page.select_option("#scene-pick", "blue_chase")
    page.wait_for_function("document.querySelectorAll('#layers li').length === 5")
    page.click("#layers li >> nth=0 >> button.name")
    page.wait_for_selector("#scene-group-tabs [data-group=bars].on")
    assert page.locator("#scene-swatches, .swatches").first.locator(".sw[title=off]").count() <= 1


# ------------------------------------------------------------------ fixtures page (v2 R7)


def fixtures_page(page, tab="patch"):
    go(page, "fixtures")
    page.wait_for_selector("body[data-fixtures-ready='1']")
    page.click(f"#fx-tabs [data-tab={tab}]")


def test_add_lights_auto_patch_and_save(ui):
    page, app, root, _ = ui
    fixtures_page(page)
    n = page.locator("#fx-patch tr").count()
    page.select_option("#fx-add-type", "starcolor72")
    page.fill("#fx-add-count", "2")
    page.fill("#fx-add-id", "par")
    page.click("#fx-add")
    assert page.locator("#fx-patch tr").count() == n + 2
    assert page.inner_text("#fx-clash") == ""  # placed on free addresses
    page.locator("#fx-patch tr").nth(n).locator("input[type=number]").nth(1).fill("1")  # onto the first light
    page.locator("#fx-patch tr").nth(n).locator("input[type=number]").nth(1).dispatch_event("input")
    page.wait_for_selector("#fx-patch tr.error")
    assert page.is_disabled("#fx-patch-save")
    page.click("#fx-auto")
    page.wait_for_function("!document.querySelector('#fx-patch tr.error')")
    page.click("#fx-patch-save")
    page.wait_for_selector("#toast:not(.hidden)")
    data = yaml.safe_load((root / "fixtures.yaml").read_text(encoding="utf-8"))
    assert {"par_1", "par_2"} <= {f["id"] for f in data["fixtures"]}
    assert "par_1" in app.engine.rig.patch.fixtures  # running already


def test_edit_a_type_and_import_from_ofl(ui, tmp_path):
    page, app, root, _ = ui
    fixtures_page(page, "types")
    page.select_option("#fx-type-pick", "starcolor72")
    page.locator("#fx-type .form select").nth(1).select_option("auto")  # colour mixing (after kind)
    page.click("#fx-type-save")
    page.wait_for_selector("#toast:not(.hidden)")
    data = yaml.safe_load((root / "fixtures.yaml").read_text(encoding="utf-8"))
    assert data["types"]["starcolor72"]["colour_mix"] == "auto"
    page.set_input_files("#fx-ofl", str(Path(__file__).parent / "data" / "eurolite_led-tmh-7.json"))
    page.wait_for_function("document.querySelector('#fx-type-pick').value.startsWith('led_tmh')")
    assert page.locator("#fx-type tbody tr").count() >= 11
    page.click("#fx-type-save")
    page.wait_for_function("document.querySelector('#toast').textContent.startsWith('Saved type')")
    assert "led_tmh_7" in yaml.safe_load((root / "fixtures.yaml").read_text(encoding="utf-8"))["types"]


def test_rig_settings_and_switch(ui):
    page, app, root, _ = ui
    fixtures_page(page, "rig")
    page.wait_for_selector("#fx-rig .form select")
    page.locator("#fx-rig .form select").first.select_option("generic")
    page.click("#fx-rig-save")
    page.wait_for_selector("#toast:not(.hidden)")
    assert yaml.safe_load((root / "rigs" / "full.yaml").read_text(encoding="utf-8"))["profile"] == "generic"
    assert not app.engine.rig.profile.master_gate  # live
    page.select_option("#fx-rig-pick", "small")
    page.wait_for_function("!document.querySelector('#fx-rig-use').disabled")
    page.click("#fx-rig-use")
    page.wait_for_function("document.querySelector('#toast').textContent.includes('small')")
    assert app.names[0] == "small"


# ------------------------------------------------------------------ setup wizard (v2 R7)


@pytest.mark.first_run
def test_setup_wizard_first_run(ui):
    page, app, root, _ = ui
    page.wait_for_function("document.querySelector('#wizard').textContent.includes('How do your lights connect?')")
    page.check("#wizard input[type=radio] >> nth=-1")  # simulator (last, after any ports this computer has)
    page.wait_for_function("[...document.querySelectorAll('#wizard input[type=radio]')].pop().checked")
    page.click("#wizard-next")
    page.wait_for_function("document.querySelector('#wizard').textContent.includes('Which lights')")
    page.locator("#wizard tr:has-text('StarColor') input").fill("2")
    page.click("#wizard-next")
    page.wait_for_function("document.querySelector('#wizard').textContent.includes('How should MASTER')")
    page.check("#wizard input[type=radio] >> nth=0")  # generic
    page.click("#wizard-next")
    page.wait_for_function("document.querySelector('#wizard').textContent.includes('Start with a show')")
    page.click("#wizard-next")
    page.wait_for_function("document.querySelector('#wizard').textContent.includes('PIN for phones')")
    page.click("#wizard-next")
    page.wait_for_function("!document.querySelector('#wizard').open")
    rig = yaml.safe_load((root / "rigs" / "full.yaml").read_text(encoding="utf-8"))
    assert rig["outputs"] == [{"driver": "log"}] and rig["profile"] == "generic"
    ids = {f["id"] for f in yaml.safe_load((root / "fixtures.yaml").read_text(encoding="utf-8"))["fixtures"]}
    assert {"starcolor72_1", "starcolor72_2"} <= ids
    assert (root / "shows" / "starter.yaml").exists() and app.ctl.show.key == "starter"
    from dmx_suite import settings

    assert settings.load()["wizard"] == "done"


# ------------------------------------------------------------------ v3.1


class _Unplugged:
    connected = False

    def status(self):
        return [{"name": "UM-ONE", "connected": self.connected, "port": None}]


def test_banners_overlay_without_moving_controls(ui):
    """A banner lies over the top of the page: no button moves under a finger (scope 18)."""
    page, app, *_ = ui
    box = page.locator("#menu [data-page=scenes]").bounding_box()
    live_box = page.locator("#tap").bounding_box()
    midi = _Unplugged()
    app.midi_inputs = midi
    page.wait_for_selector("#banners [data-alert='midi:MIDI UM-ONE']")
    assert page.locator("#menu [data-page=scenes]").bounding_box() == box
    assert page.locator("#tap").bounding_box() == live_box
    assert int(page.inner_text("#bell-count")) >= 1
    page.click("#banners [data-alert='midi:MIDI UM-ONE'] .x")  # dismiss
    page.wait_for_selector("#banners [data-alert]", state="detached")
    page.click("#bell")
    page.wait_for_selector("#alerts-list [data-alert='midi:MIDI UM-ONE'].dismissed")
    page.click("#alerts-list [data-alert='midi:MIDI UM-ONE'] button:has-text('Not using this today')")
    tile = "#health .tile[data-key='midi:MIDI UM-ONE']"
    page.wait_for_function(f"document.querySelector(\"{tile}\").classList.contains('muted-dev')")
    assert app.alert_center.muted == {"midi:MIDI UM-ONE"}
    midi.connected = True
    page.wait_for_selector("#alerts-list [data-alert='midi:MIDI UM-ONE'].cleared")


def test_colour_wheel_sets_a_layer_colour(ui):
    page, app, root, _ = ui
    go(page, "scenes")
    page.wait_for_selector("#scene-show-colour .swatches", state="attached")  # the builder has loaded
    page.click("#scene-group-tabs [data-group=bars]")
    page.click("#layer-add")
    page.click("#layer-form .wheel-btn >> nth=0")
    page.wait_for_selector("#wheel-dialog[open]")
    page.fill("#wheel-dialog input.hex", "#ff8000")
    page.dispatch_event("#wheel-dialog input.hex", "change")
    page.wait_for_selector("#wheel-dialog .wheel-fit .fit")  # what the bars make
    page.click("#wheel-dialog button:has-text('Use this colour')")
    page.fill("#scene-name", "Orange bars")
    page.click("#scene-save")
    page.wait_for_function("document.querySelector('#scene-state').textContent.includes('orange_bars')")
    data = yaml.safe_load((root / "scenes" / "orange_bars.yaml").read_text(encoding="utf-8"))
    assert data["layers"][0]["colour"] == "#ff8000"


def test_palettes_page_make_and_generate(ui):
    page, app, root, _ = ui
    go(page, "palettes")
    page.wait_for_selector("[data-palette=warm]")  # curated, built in
    page.fill("#palette-new-name", "verse")
    page.click("#palette-new")
    page.wait_for_selector("[data-palette=verse].open")
    page.select_option("[data-palette=verse] select", "triadic")
    page.fill("[data-palette=verse] input[type=number]", "3")
    page.click("[data-palette=verse] button:has-text('Generate')")
    page.wait_for_function("document.querySelectorAll('[data-palette=verse] .pal-strip i').length === 3")
    data = yaml.safe_load((root / "palettes.yaml").read_text(encoding="utf-8"))
    assert len(data["palettes"]["verse"]["colours"]) == 3


def test_inputs_learn_from_the_kit(ui):
    page, app, root, _ = ui
    from dmx_suite.midi.inputs import FakeMidiIn

    go(page, "midi")
    page.wait_for_selector("[data-input=snare]")
    page.click("[data-input=snare] button:has-text('Learn')")
    page.wait_for_function("document.querySelector('#learn-state').textContent.includes('snare')")
    FakeMidiIn(app.router.handle_mido).note(39, 100)
    page.wait_for_function("document.querySelector('[data-input=snare]').textContent.includes('note 39')")
    data = yaml.safe_load((root / "inputs.yaml").read_text(encoding="utf-8"))
    assert data["devices"]["td25"]["inputs"]["snare"]["notes"] == [39]
    FakeMidiIn(app.router.handle_mido).note(39, 98)
    page.wait_for_function("[...document.querySelectorAll('#monitor .input-name')].some(e => e.textContent === 'Snare')")


def test_store_a_head_point(ui):
    page, app, root, _ = ui
    go(page, "heads")
    page.wait_for_selector("[data-point=drum_kit]")
    area = page.locator("[data-pad=mh_b] .area").bounding_box()
    page.mouse.click(area["x"] + area["width"] * 0.25, area["y"] + area["height"] * 0.5)
    page.wait_for_function("document.querySelector('[data-pad=mh_b] .muted').textContent.startsWith('held')")
    page.fill("#point-name", "singer")
    page.fill("#point-desc", "Lead vocal, centre front")
    page.fill("#point-tags", "band, safe")
    page.select_option("#point-y", "front")
    page.click("#point-store")
    page.wait_for_selector("[data-point=singer]")
    data = yaml.safe_load((root / "rigs" / "full.yaml").read_text(encoding="utf-8"))
    pt = data["positions"]["singer"]
    assert pt["description"] == "Lead vocal, centre front" and pt["tags"] == ["band", "safe"] and pt["stage"] == {"y": "front"}
    assert list(pt["heads"]) == ["mh_b"] and abs(pt["heads"]["mh_b"]["pan"] - 0.25) < 0.02
    assert "not set for mh_a" in page.inner_text("[data-point=singer]")


# ------------------------------------------------------------------ v3.2


def test_build_a_step_scene(ui):
    page, app, root, _ = ui
    go(page, "scenes")
    page.wait_for_selector("#scene-pick option", state="attached")
    time.sleep(0.3)  # the page sets up a new scene when it opens
    page.check("#scene-steps")
    page.wait_for_selector("#steps-editor .steps-list li")
    page.click("#scene-group-tabs [data-group=bars]")
    page.click("#steps-editor button:has-text('Set the selected lights')")
    page.wait_for_selector("#steps-editor .step-sets li")
    page.click("#steps-editor button:has-text('Add step')")
    page.wait_for_function("document.querySelectorAll('#steps-editor .steps-list li').length === 2")
    page.click("#scene-group-tabs [data-group=movers]")
    page.click("#steps-editor button:has-text('Set the selected lights')")
    page.select_option("#steps-editor .step-sets li:has(b:text-is('movers')) select >> nth=0", "drum_kit")
    page.fill("#scene-name", "Intro hits")
    page.click("#scene-save")
    page.wait_for_function("document.querySelector('#scene-state').textContent.includes('intro_hits')")
    data = yaml.safe_load((root / "scenes" / "intro_hits.yaml").read_text(encoding="utf-8"))
    assert data["type"] == "steps" and len(data["steps"]) == 2
    assert data["steps"][0]["set"] == {"bars": {"colour": "white"}}
    assert data["steps"][1]["set"]["movers"] == {"colour": "white", "position": "drum_kit"}
    page.click("#steps-editor button:has-text('Play from this step')")
    deadline = time.time() + 3
    while (app.ctl.now().steps or {}).get("index") != 1 and time.time() < deadline:
        time.sleep(0.05)
    assert app.ctl.now().steps["index"] == 1


# ------------------------------------------------------------------ v3.4


def test_ride_page_autopilot_mood_and_fx(ui):
    page, app, root, _ = ui
    go(page, "ride")
    page.wait_for_selector("#ride-move [data-fx=pan_sweep]")
    page.wait_for_selector("#ride-colour [data-fx=comet]")  # the full rig has pixel bars
    page.click("#ride-colour [data-fx=colour_chase]")
    page.wait_for_function("document.querySelector('#ride-colour [data-fx=colour_chase]').classList.contains('sel')")
    assert app.ride_pick.colour == "colour_chase" and app.ctl.mode == "ride"
    page.click("#ride-palettes [data-palette=fire]")
    page.wait_for_function("document.querySelector('#ride-palettes [data-palette=fire]').classList.contains('sel')")
    page.click("#ap-toggle")
    page.wait_for_function("document.querySelector('#ap-toggle').classList.contains('on')")
    assert app.autopilot.st.on
    page.click("#ride-moods [data-mood=high]")
    page.wait_for_function("document.querySelector('#ride-moods [data-mood=high]').classList.contains('sel')")
    assert app.autopilot.st.mood == "high" and app.autopilot.st.mood_manual
    page.wait_for_selector("#ride-why li")  # the decision log shows why
    page.click("#ap-hold")
    page.wait_for_function("document.querySelector('#ap-hold').classList.contains('on')")
    page.click("#ap-toggle")
    page.wait_for_function("!document.querySelector('#ap-toggle').classList.contains('on')")


def test_ride_flash_fx_held_while_pressed(ui):
    page, app, *_ = ui
    go(page, "ride")
    page.wait_for_selector("#ride-flash [data-flash=blinder]")
    b = page.locator("#ride-flash [data-flash=blinder]").bounding_box()
    page.mouse.move(b["x"] + 10, b["y"] + 10)
    page.mouse.down()
    deadline = time.time() + 3
    while not any(o.key == "flashfx/blinder" for o in app.engine.overrides) and time.time() < deadline:
        time.sleep(0.05)
    assert any(o.key == "flashfx/blinder" for o in app.engine.overrides)
    page.mouse.up()
    deadline = time.time() + 3
    while any(o.key == "flashfx/blinder" for o in app.engine.overrides) and time.time() < deadline:
        time.sleep(0.05)
    assert not any(o.key == "flashfx/blinder" for o in app.engine.overrides)


def test_ride_learn_maps_a_pad(ui):
    page, app, root, _ = ui
    from dmx_suite.midi.inputs import FakeMidiIn

    go(page, "ride")
    page.wait_for_selector("#ap-next")
    page.click("#ride-learn")
    page.click("#ap-next")
    deadline = time.time() + 3
    while app.router.learning != "look_next" and time.time() < deadline:
        time.sleep(0.05)
    FakeMidiIn(app.router.handle_mido).note(51, 100)  # the ride cymbal
    deadline = time.time() + 3
    while "look_next" not in (root / "midi" / "default.yaml").read_text(encoding="utf-8") and time.time() < deadline:
        time.sleep(0.05)
    assert app.router.map.get_input("ride").action == "look_next"


# ------------------------------------------------------------------ v3.5


def test_review_rate_and_generate(ui):
    page, app, root, _ = ui
    go(page, "review")
    page.wait_for_selector("#rv-list li")
    page.click("#rv-list li >> nth=2 >> button")
    page.click("#rv-ban")
    deadline = time.time() + 3
    while not (root / "ratings.yaml").exists() and time.time() < deadline:
        time.sleep(0.05)
    data = yaml.safe_load((root / "ratings.yaml").read_text(encoding="utf-8"))
    assert list(data["looks"].values()) == [-2]
    page.fill("#gen-count", "3")
    page.fill("#gen-prefix", "ui_gen")
    page.fill("#gen-seed", "ui")
    page.click("#gen-scenes")
    page.wait_for_function("document.querySelector('#gen-out').textContent.includes('ui_gen_3')")
    assert (root / "scenes" / "ui_gen_1.yaml").exists()


def test_ride_presets_and_reroll(ui):
    page, app, root, _ = ui
    go(page, "ride")
    page.wait_for_selector("#ride-presets [data-preset=fire_wave]")
    page.click("#ride-presets [data-preset=fire_wave]")
    deadline = time.time() + 3
    while app.ride_pick.colour != "wave" and time.time() < deadline:
        time.sleep(0.05)
    assert app.ride_pick.palette == "fire"
    page.check("[data-lock=colour]")
    page.click("#ride-reroll")
    deadline = time.time() + 3
    while app.ride_pick.key() == "figure8|wave|-|fire" and time.time() < deadline:
        time.sleep(0.05)
    assert app.ride_pick.colour == "wave" and app.ride_pick.key() != "figure8|wave|-|fire"
    page.once("dialog", lambda d: d.accept("my_look"))
    page.click("#ride-save-preset")
    page.wait_for_selector("#ride-presets [data-preset=my_look]")


# ------------------------------------------------------------------ Connect to Claude


def test_connect_to_claude_from_setup(ui, monkeypatch, tmp_path):
    page, app, root, _ = ui
    for k in ("APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(k, str(tmp_path / k))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "APPDATA" / "Claude").mkdir(parents=True)
    page.click("#health .tile[data-key='claude:Claude']")  # the status bar tile opens the section
    page.wait_for_selector("#page-setup.on #claude-connect .claude-steps")
    assert "Claude Desktop: not connected" in page.inner_text("#claude-connect")
    page.click("#claude-connect-btn")
    page.wait_for_function("document.querySelector('#claude-connect').textContent.includes('Claude Desktop: connected')")
    cfg = json.loads((tmp_path / "APPDATA" / "Claude" / "claude_desktop_config.json").read_text())
    assert cfg["mcpServers"]["dmx-suite"]["args"][-1] == "mcp"
    assert page.is_disabled("#claude-connect-btn")
    page.click("#claude-disconnect-btn")
    page.wait_for_function("document.querySelector('#claude-connect').textContent.includes('Claude Desktop: not connected')")
