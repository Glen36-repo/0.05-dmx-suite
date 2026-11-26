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


def test_names_never_overlap(shot):
    page, *_ = shot
    for name, host in (("layout", "#layout-grid"), ("live", "#live-grid")):
        go(page, name)
        page.wait_for_selector(f"{host} [data-id=wash_l] .name")
        labels = [b for b in boxes(page, f"{host} .name") if b["w"]]
        cells = boxes(page, f"{host} .cell")
        clash = [(a["id"], b["id"]) for i, a in enumerate(labels) for b in labels[i + 1:] if overlap(a, b, 0.5)]
        assert clash == [], f"{name}: {clash}"
        on_lights = [(a["id"], c["id"]) for a in labels for c in cells if c["id"] != a["id"] and overlap(a, c, 0.5)]
        assert on_lights == [], f"{name}: {on_lights}"
        tips = page.eval_on_selector_all(f"{host} [data-id] > title", "ts => ts.map(t => t.textContent)")
        assert any(t.startswith("uking_l") for t in tips)  # full id on hover


def test_place_labels_falls_back_to_short_names(ui):
    page, *_ = ui
    out = page.evaluate("""async () => {
      const { placeLabels, shortName } = await import('/static/js/grid.js');
      const it = (id, x) => ({ id, icon: [x - 0.4, 0, x + 0.4, 0.8], full: id, short: shortName(id) });
      return [shortName('uking_l'), placeLabels([it('wash_l', 0), it('uking_l', 1), it('uking_r', 2), it('wash_r', 3)])];
    }""")
    short, spots = out
    assert short == "UK L"
    assert any(s["short"] or s["leader"] for s in spots.values())


def test_haze_is_a_corner_indicator_not_a_light(shot):
    page, app, *_ = shot
    for name, host in (("layout", "#layout-grid"), ("live", "#live-grid")):
        go(page, name)
        page.wait_for_selector(f"{host} .haze-ind .hz-text")
        assert page.locator(f"{host} [data-id=smoke]").count() == 0
        ind = page.locator(f"{host} .haze-ind rect").bounding_box()
        svgbox = page.locator(f"{host} svg").bounding_box()
        assert ind["x"] + ind["width"] > svgbox["x"] + svgbox["width"] * 0.8 and ind["y"] < svgbox["y"] + svgbox["height"] * 0.2
        lights = boxes(page, f"{host} .cell")
        hz = {"x": ind["x"], "y": ind["y"], "w": ind["width"], "h": ind["height"]}
        assert not any(overlap(hz, c, 0.5) for c in lights)
    app.engine.haze_toggle_manual()
    page.wait_for_function("document.querySelector('#live-grid .hz-text').textContent.includes('manual')")
    page.wait_for_selector("#live-grid .haze-ind.on")


def test_layout_page_lists_overlaps_live(shot):
    page, *_ = shot
    go(page, "layout")
    page.wait_for_selector("#layout-problems li")
    text = page.inner_text("#layout-problems")
    assert "mh_a and par_1 are in the same place" in text
    page.click("#layout-problems button:has-text('mh_a and par_1')")
    assert page.eval_on_selector_all("#layout-grid .fx.sel", "els => els.map(e => e.dataset.id).sort()") == ["mh_a", "par_1"]
    # move par_1 away: that line goes (before saving)
    page.keyboard.press("Escape")  # par_1 is drawn on top of mh_a: dragging that spot moves par_1 only
    page.click("[data-tool=move]")
    box = page.locator("#layout-grid [data-id=par_1] .cell").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 4 * box["height"], steps=6)
    page.mouse.up()
    page.wait_for_function("!document.querySelector('#layout-problems').textContent.includes('mh_a and par_1')")


def test_cell_offsets_match_python(ui):
    from dmx_suite.layout import cell_offsets

    page, *_ = ui
    cases = [(n, shape, cols, rev) for n in (1, 3, 8, 12) for shape in ("row", "ring", "grid") for cols in (0, 3)
             for rev in (False, True)]
    js = page.evaluate("""async (cases) => {
      const { cellOffsets } = await import('/static/js/grid.js');
      return cases.map(([n, s, c, r]) => cellOffsets(n, s, c, r));
    }""", [list(c) for c in cases])
    for c, got in zip(cases, js, strict=True):
        want = cell_offsets(*c)
        assert len(got) == len(want)
        for (gx, gy), (wx, wy) in zip(got, want, strict=True):
            assert abs(gx - wx) < 1e-9 and abs(gy - wy) < 1e-9, c


# ---------------------------------------------------------------- Layout / Patch page (item 7)


def test_layout_patch_page_universe_list_and_address_map(shot):
    page, app, root, _ = shot
    go(page, "layout")
    page.wait_for_selector("#lp-uni [data-uni=all]")
    assert page.inner_text("#lp-uni") .split() == ["All", "U0"]
    page.wait_for_selector("#lp-fixtures tr[data-id=par_1]")
    # clicking a light in the list selects it on the stage
    page.click("#lp-fixtures tr[data-id=bar_2] td:first-child")
    assert page.eval_on_selector_all("#layout-grid .fx.sel", "els => els.map(e => e.dataset.id)") == ["bar_2"]
    assert "sel" in page.eval_on_selector("#lp-fixtures tr[data-id=bar_2]", "e => e.className")
    # routing table and status strip: U0 goes out the simulator
    page.wait_for_selector("#lp-routing tr")
    assert "Simulator" in page.inner_text("#lp-routing") and "U0 → Simulator" in page.inner_text("#lp-status")
    # address map: blocks labelled, live values from what the interface sent
    page.click("#lp-views [data-view=addresses]")
    page.wait_for_selector("#addr-maps .addr-map[data-u='0'] .ac[data-ch='129'].start .lbl")
    assert page.inner_text("#addr-maps .ac[data-ch='129'] .lbl") == "bar_1"
    assert page.eval_on_selector("#addr-maps .ac[data-ch='2']", "e => e.dataset.ids") == ""  # free channel blank
    page.wait_for_function("document.querySelector('[data-note=\"0\"]').textContent.includes('Simulator')")
    app.engine.channel_test[(0, 2)] = 200  # a value only the channel tester sets
    page.wait_for_function("document.querySelector('#addr-maps .ac[data-ch=\"2\"] .v').textContent === '200'")
    del app.engine.channel_test[(0, 2)]


def test_layout_patch_inline_address_edit(shot):
    page, app, root, _ = shot
    go(page, "layout")
    page.wait_for_selector("#lp-fixtures tr[data-id=par_1]")
    addr = "#lp-fixtures tr[data-id=par_1] td:nth-child(5) input"
    page.fill(addr, "386")  # on top of par_2 (385-391)
    page.wait_for_selector("#lp-fixtures tr[data-id=par_1].error")
    assert "par_1" in page.inner_text("#lp-clash") and page.is_disabled("#lp-patch-save")
    page.click("#lp-views [data-view=addresses]")
    page.wait_for_selector("#addr-maps .ac[data-ch='386'].clash")
    page.fill(addr, "450")
    page.wait_for_function("!document.querySelector('#lp-patch-save').disabled")
    page.click("#lp-patch-save")
    page.wait_for_function("document.querySelector('#lp-patch-save').disabled")
    assert app.files.patch.fixtures["par_1"].address == 450


def test_patch_sheet_png(shot):
    page, *_ = shot
    go(page, "layout")
    page.wait_for_selector("#lp-fixtures tr[data-id=par_1]")
    with page.expect_download() as dl:
        page.click("#lp-png")
    assert dl.value.suggested_filename.startswith("patch-sheet-") and dl.value.suggested_filename.endswith(".png")
    page.emulate_media(media="print")
    assert page.is_visible("#addr-maps") and not page.is_visible("#menu")
    page.emulate_media(media="screen")


# ---------------------------------------------------------------- ARRANGE panel (item 13)


def test_arrange_panel_groups_disabled_reasons_redo_revert(ui):
    page, *_ = ui
    go(page, "layout")
    page.wait_for_selector("#arrange [data-align=left] svg")
    assert page.text_content("#arrange").split() == ["Align", "Distribute", "Shape", "Spacing", "Columns", "Rotate", "Step", "°",
                                                   "Angle", "°", "Pixels", "Columns"]
    assert page.is_disabled("[data-align=left]") and "two or more" in page.get_attribute("[data-align=left]", "title")
    assert "(Alt+←)" in page.get_attribute("[data-align=left]", "title")
    assert page.is_disabled("#layout-reset") and page.is_disabled("#layout-redo")
    page.click("#group-tabs [data-group=bars]")
    assert not page.is_disabled("[data-align=left]") and not page.is_disabled("[data-distribute=h]")
    assert not page.is_disabled("[data-shape=ring]")  # bars have pixels
    page.click("#group-tabs [data-group=heads]")
    assert page.is_disabled("[data-distribute=h]") is False and page.is_disabled("[data-shape=ring]")  # no pixels in heads
    x0 = page.evaluate("() => document.querySelector('#layout-grid [data-id=mh_a] .cell').getBoundingClientRect().x")
    page.click("[data-flip=h]")
    page.wait_for_selector("#layout-dirty:not(.hidden)")
    x1 = page.evaluate("() => document.querySelector('#layout-grid [data-id=mh_a] .cell').getBoundingClientRect().x")
    assert x1 != x0
    page.click("#layout-undo")
    assert not page.is_disabled("#layout-redo")
    page.click("#layout-redo")
    page.keyboard.press("Control+z")
    page.keyboard.press("Control+Shift+Z")
    page.on("dialog", lambda d: d.accept())
    page.click("#layout-reset")  # Revert to saved, after a confirm
    page.wait_for_selector("#layout-dirty.hidden", state="attached")
    assert page.is_disabled("#layout-undo") and page.is_disabled("#layout-redo")


def test_arrange_shortcuts_and_reverse(ui):
    page, app, root, _ = ui
    go(page, "layout")
    page.wait_for_selector("#arrange [data-align=left] svg")
    page.click("#group-tabs [data-group=bars]")
    page.click("[data-reverse]")
    page.fill("#ar-step", "90")
    page.eval_on_selector("#ar-step", "e => e.blur()")  # shortcuts don't fire while typing in a field
    page.keyboard.press("r")
    page.keyboard.press("Control+s")
    page.wait_for_selector("#layout-dirty.hidden", state="attached")
    lay = app.engine.rig.layout
    assert lay["bar_1"].reverse and lay["bar_1"].rot == 90.0


# ---------------------------------------------------------------- haze settings (item 14)


def test_haze_settings_panel(ui):
    import yaml

    page, app, root, _ = ui
    go(page, "live")
    page.click("#haze-settings summary")
    page.wait_for_selector("#hz-blocks [data-block=pulse] #hz-duty")
    assert "rig: full" in page.inner_text("#haze-rig")
    assert page.text_content("#hz-blocks").count("Test") == 3
    page.fill("#hz-blocks input.num[data-key=level]", "41")
    page.press("#hz-blocks input.num[data-key=level]", "Tab")
    page.wait_for_function("!document.querySelector('#hz-save').disabled")
    for _ in range(40):
        if abs(app.engine.haze.cfg.level - 0.41) < 1e-9:
            break
        page.wait_for_timeout(50)
    assert app.engine.haze.cfg.level == pytest.approx(0.41)  # tried live, not saved
    assert yaml.safe_load((root / "rigs" / "full.yaml").read_text())["haze"]["level"] == 60
    page.fill("#hz-blocks input.num[data-key=pulse_on_s]", "1")
    page.press("#hz-blocks input.num[data-key=pulse_on_s]", "Tab")
    page.fill("#hz-blocks input.num[data-key=pulse_every_s]", "61")
    page.press("#hz-blocks input.num[data-key=pulse_every_s]", "Tab")
    assert "1 s every 61 s ≈ 2 %" in page.inner_text("#hz-duty")
    page.click("#hz-save")
    page.wait_for_function("document.querySelector('#hz-save').disabled")
    assert yaml.safe_load((root / "rigs" / "full.yaml").read_text())["haze"]["level"] == 41
    page.click("[data-test=manual]")
    page.wait_for_function("document.querySelector('#haze').textContent.includes('testing')")


# ---------------------------------------------------------------- Monitor page (item 15)


def test_monitor_page_dmx_and_midi(ui):
    import mido

    page, app, root, _ = ui
    go(page, "monitor")
    page.wait_for_selector("#mon-dmx-body .dmx-grid .dc[data-ch='512']")
    page.wait_for_function("document.querySelector('#mon-dmx-stats').textContent.includes('Simulator')")
    app.engine.channel_test[(0, 3)] = 123
    page.wait_for_function("document.querySelector('#mon-dmx-body .dc[data-ch=\"3\"] .v').textContent === '123'")
    assert "bar_1" in page.get_attribute("#mon-dmx-body .dc[data-ch='27']", "title")
    page.click("#mon-dmx-view [data-view=fixture]")
    page.wait_for_selector("#mon-dmx-body .fxbox")
    page.click("#mon-dmx-view [data-view=hex]")
    assert "  1: " in page.inner_text("#mon-dmx-body")
    del app.engine.channel_test[(0, 3)]
    # MIDI in: the event, its note name, the named input and what it did
    app.router.handle_mido(mido.Message("note_on", channel=9, note=38, velocity=100), "TD-25")
    page.wait_for_selector("#mon-in-log tr")
    row = page.inner_text("#mon-in-log tr:first-child")
    assert "D2" in row and "Snare" in row and "TD-25" in row
    assert "Simulated MIDI input" in page.inner_text("#mon-in-ports")
    assert "No MIDI outputs set up" in page.inner_text("#mon-out-ports") and page.is_disabled("#send-go")
    with page.expect_download() as dl:
        page.click("#mon-midi-in [data-act=csv]")
    assert dl.value.suggested_filename == "midi-in.csv"
    page.click("#mon-midi-in [data-act=full]")
    assert "full" in page.get_attribute("#mon-midi-in", "class")


def test_status_tile_opens_monitor(ui):
    page, *_ = ui
    page.click(".tile.link[data-key^='midi:']")
    page.wait_for_selector("#page-monitor.on")


# ---------------------------------------------------------------- SHOW grid (item 12)


def test_show_and_scene_buttons_are_an_aligned_grid(ui):
    page, app, root, _ = ui
    go(page, "live")
    page.wait_for_selector("#scenes [data-scene]")
    for grid in ("#shows", "#scenes"):
        bs = boxes(page, f"{grid} > button")
        assert len({round(b["w"]) for b in bs}) == 1 and len({round(b["h"]) for b in bs}) == 1  # all the same size
        lefts = sorted({round(b["x"]) for b in bs})
        rows = {}
        for b in bs:
            rows.setdefault(round(b["y"]), []).append(round(b["x"]))
        assert all(x in lefts[: len(r)] for r in rows.values() for x in r)  # columns line up row to row
    assert page.locator("#shows [data-scene]").count() == 0  # shows and scenes apart
    scenes_before = page.eval_on_selector_all("#scenes > button", "bs => bs.map(b => b.dataset.item)")
    # a new scene goes at the end; nothing else moves
    app.store.put("scene", "aaa_new", {"name": "AAA new", "layers": [{"fixtures": ["bars"], "colour": "red"}]})
    app.reload()
    page.evaluate("async () => (await import('/static/js/state.js')).refreshCatalogue()")
    page.wait_for_selector("#scenes [data-scene=aaa_new]")
    after = page.eval_on_selector_all("#scenes > button", "bs => bs.map(b => b.dataset.item)")
    assert after[:-1] == scenes_before and after[-1] == "scene:aaa_new"
    # a long name doesn't widen its button
    w = page.eval_on_selector("#scenes [data-scene=aaa_new]", "b => b.getBoundingClientRect().width")
    assert abs(w - boxes(page, "#scenes > button")[0]["w"]) < 1


# ---------------------------------------------------------------- step editor (item 10)


def open_steps(page):
    go(page, "scenes")
    page.wait_for_selector("#scene-pick option", state="attached")
    page.wait_for_timeout(300)
    page.check("#scene-steps")
    page.wait_for_selector("#steps-list-pane .steps-list li")


def test_step_editor_three_panes_tracking_and_record_modes(ui):
    page, app, root, _ = ui
    open_steps(page)
    assert "steps-mode" in page.get_attribute("#page-scenes .builder", "class")
    for k in ("step_s", "step_beats", "fade_s", "dark_s"):
        assert page.locator(f"#steps-bar input[data-k={k}]").count() == 1
    page.click("#scene-group-tabs [data-group=bars]")
    page.click("#step-programmer .swatches button[title=red]")
    assert "in the programmer" in page.inner_text("#step-programmer .prog-row[data-attr=colour]")
    page.click("#rec-new")  # as a new step 2
    page.wait_for_function("document.querySelectorAll('#steps-list-pane .steps-list li').length === 2")
    page.click("#steps-list-pane .steps-list li[data-step='1'] .name")
    page.wait_for_function("document.querySelector('#step-programmer .prog-row[data-attr=colour]').classList.contains('set')")
    # step 1 -> 3: step 3 tracks red from step 2
    page.click("#steps-list-pane .steps-list li[data-step='1'] .tools button[title='Insert a step after this one']")
    page.wait_for_function("document.querySelectorAll('#steps-list-pane .steps-list li').length === 3")
    page.wait_for_function("document.querySelector('#step-programmer .prog-row[data-attr=colour]').classList.contains('tracked')")
    assert "tracked from step 2" in page.inner_text("#step-programmer .prog-row[data-attr=colour]")
    # editor undo / redo
    page.click("#steps-undo")
    page.wait_for_function("document.querySelectorAll('#steps-list-pane .steps-list li').length === 2")
    page.click("#steps-redo")
    page.wait_for_function("document.querySelectorAll('#steps-list-pane .steps-list li').length === 3")
    # bulk timing on ticked steps
    page.check("#steps-list-pane li[data-step='0'] .step-pick")
    page.check("#steps-list-pane li[data-step='2'] .step-pick")
    page.fill("#steps-list-pane .bulk input[data-k=bulk-step]", "0.5")
    page.press("#steps-list-pane .bulk input[data-k=bulk-step]", "Tab")
    first = "document.querySelector(\"#steps-list-pane li[data-step='0'] .step-time\")"
    page.wait_for_function(f"{first}.textContent.includes('0.5s')")


def test_step_editor_yaml_round_trip_and_validation(ui):
    page, app, root, _ = ui
    open_steps(page)
    page.click("#steps-yaml")
    page.wait_for_selector("#step-yaml textarea")
    text = page.input_value("#step-yaml textarea")
    assert "type: steps" in text
    page.fill("#step-yaml textarea", text + "\nfade_s: 0.7\n")
    page.click("#step-yaml button")
    page.wait_for_function("document.querySelector('#steps-bar input[data-k=fade_s]').value === '0.7'")
    # a rule break is pinned to its step: position on a colour-only head
    bad = "name: x\ntype: steps\nsteps:\n- set: {bars: {colour: red}}\n- set: {ukings: {position: drum_kit}}\n"
    page.fill("#step-yaml textarea", bad)
    page.click("#step-yaml button")
    page.wait_for_selector("#steps-list-pane li[data-step='1'].error")
    assert "rule 7" in page.get_attribute("#steps-list-pane li[data-step='1']", "title")


def test_step_editor_live_mode_sends_the_step(ui):
    page, app, root, _ = ui
    open_steps(page)
    page.check("#steps-live")
    page.click("#scene-group-tabs [data-group=bars]")
    page.click("#step-programmer .swatches button[title=blue]")  # not recorded yet: still sent live
    deadline = page.evaluate("Date.now()") + 3000
    while app.engine.previewing is None and page.evaluate("Date.now()") < deadline:
        page.wait_for_timeout(50)
    assert app.engine.previewing is not None
    page.uncheck("#steps-live")
