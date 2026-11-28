# ruff: noqa: F811 - pytest fixtures imported from test_ui are used as arguments
"""v4 browser tests: density, stage view, Layout/Patch, Monitor, step editor, renames.

Uses the Playwright fixtures from test_ui (skipped when no browser is available).
"""

import shutil

import pytest
import screenshot_rig
from test_ui import PAGES, SHOWS, TOKEN, browser, centre, drag, go, ui  # noqa: F401,F811 - pytest fixtures

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
        # it moves to the corner once the drawing has its size (a frame after the page shows): wait for that
        page.wait_for_function("""(h) => { const r = document.querySelector(h + ' .haze-ind rect').getBoundingClientRect(),
            s = document.querySelector(h + ' svg').getBoundingClientRect();
            return r.width > 0 && r.right > s.left + s.width * 0.8; }""", arg=host)
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
    # status strip: U0 goes out the simulator
    page.wait_for_function("document.querySelector('#lp-status').textContent.includes('U0 → Simulator')")
    # v7: the routing table and the address map are on Fixtures
    go(page, "fixtures")
    page.click("#fx-addr summary")
    page.wait_for_selector("#fx-routing tr")
    assert "Simulator" in page.inner_text("#fx-routing")
    # address map: blocks labelled, live values from what the interface sent
    page.wait_for_selector("#addr-maps .addr-map[data-u='0'] .ac[data-ch='129'].start .lbl")
    assert page.inner_text("#addr-maps .ac[data-ch='129'] .lbl") == "bar_1"
    assert page.eval_on_selector("#addr-maps .ac[data-ch='2']", "e => e.dataset.ids") == ""  # free channel blank
    page.wait_for_function("document.querySelector('[data-note=\"0\"]').textContent.includes('Simulator')")
    app.engine.channel_test[(0, 2)] = 200  # a value only the channel tester sets
    page.wait_for_function("document.querySelector('#addr-maps .ac[data-ch=\"2\"] .v').textContent === '200'")
    del app.engine.channel_test[(0, 2)]


def test_fixtures_inline_address_edit(shot):
    """v7 B2: universes and addresses are typed on Fixtures, with the range, clash checks and the address map."""
    page, app, root, _ = shot
    go(page, "fixtures")
    page.wait_for_selector("#fx-patch tr[data-id=par_1]")
    page.click("#fx-addr summary")
    addr = "#fx-patch [data-address=par_1]"
    page.fill(addr, "386")  # on top of par_2 (385-391)
    page.wait_for_selector("#fx-patch tr[data-id=par_1].error")
    assert "par_1" in page.inner_text("#fx-clash") and page.is_disabled("#fx-patch-save")
    assert page.evaluate("document.activeElement.dataset.address") == "par_1"  # still typing in it
    page.wait_for_selector("#addr-maps .ac[data-ch='386'].clash")
    page.fill(addr, "450")
    assert page.inner_text("#fx-patch [data-range=par_1]") == "450-456"
    page.wait_for_function("!document.querySelector('#fx-patch-save').disabled")
    page.click("#fx-patch-save")
    for _ in range(80):
        if app.files.patch.fixtures["par_1"].address == 450:
            break
        page.wait_for_timeout(25)
    assert app.files.patch.fixtures["par_1"].address == 450


def test_patch_sheet_png(shot):
    page, *_ = shot
    go(page, "layout")
    page.wait_for_selector("#lp-fixtures tr[data-id=par_1]")
    with page.expect_download() as dl:
        page.click("#lp-png")
    assert dl.value.suggested_filename.startswith("patch-sheet-") and dl.value.suggested_filename.endswith(".png")
    go(page, "fixtures")  # v7: the printed patch sheet comes from Fixtures (patch table + address map)
    page.click("#fx-addr summary")
    page.wait_for_selector("#addr-maps .addr-map")
    page.emulate_media(media="print")
    assert page.is_visible("#addr-maps") and page.is_visible("#fx-patch") and not page.is_visible("#menu")
    assert not page.is_visible("#fx-routing")
    page.emulate_media(media="screen")


# ---------------------------------------------------------------- ARRANGE panel (item 13)


def test_arrange_panel_groups_disabled_reasons_redo_revert(ui):
    page, *_ = ui
    go(page, "layout")
    page.wait_for_selector("#arrange [data-align=left] svg")
    words = [w for w in page.text_content("#arrange").split() if w != "ⓘ"]
    assert words == ["Align", "Distribute", "Shape", "Spacing", "Columns", "Rotate", "Step", "°", "Angle", "°", "Pixels",
                     "Columns"]
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


# ---------------------------------------------------------------- pixel selection in the scene editor (item 11)


def test_pixel_selection_click_shift_ctrl_and_selectors(ui):
    import yaml

    page, app, root, _ = ui
    go(page, "scenes")
    page.wait_for_selector("#scene-grid [data-id=bar_1] rect.cell[data-px='7']")
    cell = lambda fid, px: f"#scene-grid [data-id={fid}] rect.cell[data-px='{px}']"  # noqa: E731
    page.click(cell("bar_1", 2))
    assert page.inner_text("#scene-sel").startswith("1") and "bar_1:px3" in page.inner_text("#scene-sel")
    page.click(cell("bar_1", 3), modifiers=["Shift"])
    page.click(cell("bar_1", 5), modifiers=["Control"])
    assert "bar_1:px3-4,6" in page.inner_text("#scene-sel")
    page.click(cell("bar_1", 5), modifiers=["Control"])  # toggles back off
    assert "bar_1:px3-4" in page.inner_text("#scene-sel")
    assert page.locator("#scene-grid .cell.psel").count() == 2
    page.dblclick(cell("bar_2", 0))  # the whole bar
    assert "bar_2" in page.inner_text("#scene-sel") and page.locator("#scene-grid [data-id=bar_2].sel").count() == 1
    # helpers: first 1 of every bar -> the group's selector
    page.click("#scene-group-tabs [data-group=bars]")
    page.fill("#px-k", "1")
    page.click("[data-px-help=first]")
    assert "bars:px1" in page.inner_text("#scene-sel")
    page.click("[data-px-help=invert]")
    assert "bars:px2-8" in page.inner_text("#scene-sel")
    page.click("[data-px-help=odd]")
    assert "bars:px1,3,5,7" in page.inner_text("#scene-sel")
    # a layer from a pixel selection writes the selector; picking the layer puts it back on the stage
    page.click("#layer-add")
    page.fill("#scene-name", "Odd bars")
    page.click("#scene-save")
    page.wait_for_function("document.querySelector('#scene-state').textContent.includes('odd_bars')")
    data = yaml.safe_load((root / "scenes" / "odd_bars.yaml").read_text())
    assert data["layers"][0]["fixtures"] == ["bars:px1,3,5,7"]
    page.click("#scene-group-tabs [data-group=heads]")
    page.click("#layers li .name")
    assert page.locator("#scene-grid .cell.psel").count() == 16  # 4 bars x 4 odd pixels


def test_save_a_pixel_group(ui):
    import yaml

    page, app, root, _ = ui
    go(page, "scenes")
    page.wait_for_selector("#scene-grid [data-id=bar_1] rect.cell[data-px='7']")
    page.click("#scene-group-tabs [data-group=bars]")
    page.fill("#px-k", "1")
    page.click("[data-px-help=first]")
    for fid in ("bar_1", "bar_2", "bar_3", "bar_4"):  # and the last pixel of each bar
        page.click(f"#scene-grid [data-id={fid}] rect.cell[data-px='7']", modifiers=["Control"])
    assert "bars:px1,8" in page.inner_text("#scene-sel")
    page.on("dialog", lambda d: d.accept("bar_tips"))
    page.click("#px-group-save")
    for _ in range(60):
        if "bar_tips" in app.files.patch.pixel_groups:
            break
        page.wait_for_timeout(50)
    fx = yaml.safe_load((root / "fixtures.yaml").read_text())
    assert fx["pixel_groups"]["bar_tips"] == ["bar_1:px1,8", "bar_2:px1,8", "bar_3:px1,8", "bar_4:px1,8"]
    assert app.files.patch.pixel_groups["bar_tips"]["bar_2"] == {0, 7}
    page.click("[data-px-help=none]")
    page.click("#scene-group-tabs [data-group=bars]")
    page.click("[data-px-help=first]")
    for fid in ("bar_1", "bar_2", "bar_3", "bar_4"):
        page.click(f"#scene-grid [data-id={fid}] rect.cell[data-px='7']", modifiers=["Control"])
    assert "bar_tips" in page.inner_text("#scene-sel")  # the saved group's name is used


def test_layout_and_live_keep_whole_light_selection(ui):
    page, *_ = ui
    go(page, "layout")
    page.wait_for_selector("#layout-grid [data-id=bar_1] rect.cell")
    page.click("#layout-grid [data-id=bar_1] rect.cell >> nth=2")
    assert page.locator("#layout-grid .cell.psel").count() == 0  # whole lights only outside the scene editor
    assert page.locator("#layout-grid [data-id=bar_1].sel").count() == 1


# ---------------------------------------------------------------- every screen picks up file changes (v4.1)


def wash_x(page, grid):
    return float(page.get_attribute(f"{grid} [data-id=wash_l] rect", "x"))


def wait_wash_right_of(page, grid, x, timeout=4000):
    page.wait_for_function(f"Number(document.querySelector('{grid} [data-id=wash_l] rect').getAttribute('x')) > {x}",
                           timeout=timeout)


def move_wash(page):
    go(page, "layout")
    page.click("#group-tabs [data-group=washes]")
    page.click("[data-tool=move]")
    start = centre(page, "#layout-grid [data-id='wash_l'] .cell")
    drag(page, start, (start[0] + 120, start[1]))


def second_screen(browser, web):
    other = browser.new_page(viewport={"width": 1280, "height": 900})
    other.goto(f"http://127.0.0.1:{web.port}/?t={TOKEN}")
    other.wait_for_selector("body.ready", timeout=10000)
    return other


def test_layout_saved_on_one_screen_shows_on_another(ui, browser):
    page, app, *_ = ui
    other = second_screen(browser, page.web)
    try:
        before = wash_x(other, "#live-grid")
        move_wash(page)
        page.click("#layout-save")
        page.wait_for_selector("#layout-save:disabled")
        wait_wash_right_of(other, "#live-grid", before)
        assert wash_x(other, "#ride-grid") == wash_x(other, "#live-grid")  # Autopilot too, no reload
        assert wash_x(page, "#live-grid") == wash_x(other, "#live-grid")  # and the screen that saved it
    finally:
        other.close()


def test_layout_changed_by_claude_shows_on_open_screens(ui):
    page, app, *_ = ui
    before = wash_x(page, "#live-grid")
    lay = app.catalogue()["layout"]
    app.save_layout({**lay, "wash_l": {**lay["wash_l"], "x": lay["wash_l"]["x"] + 4}})  # what set_layout does
    wait_wash_right_of(page, "#live-grid", before)


def test_unsaved_layout_edits_kept_when_another_screen_saves(ui, browser):
    page, app, *_ = ui
    other = second_screen(browser, page.web)
    try:
        move_wash(page)  # unsaved here
        mine = wash_x(page, "#layout-grid")
        app.set_positions({"wash_r": {"x": 2, "y": 2}})  # someone else saves
        page.wait_for_selector("#toast:not(.hidden)")
        assert "kept" in page.inner_text("#toast").lower() or "unsaved" in page.inner_text("#toast").lower()
        assert wash_x(page, "#layout-grid") == mine and not page.is_disabled("#layout-save")
    finally:
        other.close()


def test_leaving_layout_unsaved_says_so_and_save_reaches_live(ui):
    page, *_ = ui
    before = wash_x(page, "#live-grid")
    move_wash(page)
    go(page, "live")
    page.wait_for_selector("#toast:not(.hidden)")
    assert "not saved" in page.inner_text("#toast")
    assert wash_x(page, "#live-grid") == before  # Live shows the saved layout
    go(page, "layout")
    assert not page.is_disabled("#layout-save")  # the edit is still there
    page.click("#layout-save")
    page.wait_for_selector("#layout-save:disabled")
    go(page, "live")
    wait_wash_right_of(page, "#live-grid", before)


# ---------------------------------------------------------------- Autopilot: excluded types (v4.1)


def rig_exclude_fx(app, want=None, page=None):
    """The rig file's excluded types; with `want`, waits for the save (the button turns red at once)."""
    import yaml as _yaml

    for _ in range(80):
        data = _yaml.safe_load((app.files.root / "rigs" / f"{app.names[0]}.yaml").read_text(encoding="utf-8"))
        got = (data.get("auto") or {}).get("exclude_fx") or []
        if want is None or got == want:
            return got
        page.wait_for_timeout(25)
    return got


def test_exclude_mode_turns_types_red_and_keeps_them(ui):
    page, app, *_ = ui
    go(page, "autopilot")
    page.wait_for_selector("#ride-colour [data-fx=rainbow]")
    before = app.ride_pick.colour
    page.click("#ride-exclude")
    assert "on" in page.get_attribute("#ride-exclude", "class")
    page.click("#ride-colour [data-fx=rainbow]")
    page.wait_for_selector("#ride-colour [data-fx=rainbow].excluded")
    assert rig_exclude_fx(app, ["rainbow"], page) == ["rainbow"] and app.ride_pick.colour == before  # not played
    page.click("#ride-flash [data-flash=strobe]", force=True)  # Flash FX can't be excluded
    page.wait_for_timeout(200)
    assert rig_exclude_fx(app) == ["rainbow"]
    page.click("#ride-exclude")  # Done
    page.click("#ride-colour [data-fx=rainbow]")  # a tap plays it again, excluded or not
    page.wait_for_selector("#ride-colour [data-fx=rainbow].excluded.sel")
    assert app.ride_pick.colour == "rainbow"
    go(page, "live")
    go(page, "autopilot")  # still there, still red, after leaving the page
    page.wait_for_selector("#ride-colour [data-fx=rainbow].excluded")
    page.click("#ride-exclude")
    page.click("#ride-colour [data-fx=rainbow]")  # put back
    page.wait_for_selector("#ride-colour [data-fx=rainbow]:not(.excluded)")
    assert rig_exclude_fx(app, [], page) == []


def test_long_press_excludes_without_playing(ui):
    page, app, *_ = ui
    go(page, "autopilot")
    page.wait_for_selector("#ride-move [data-fx=circle]")
    before = app.ride_pick.move
    x, y = centre(page, "#ride-move [data-fx=circle]")
    page.mouse.move(x, y)
    page.mouse.down()
    page.wait_for_timeout(750)
    page.mouse.up()
    page.wait_for_selector("#ride-move [data-fx=circle].excluded")
    assert rig_exclude_fx(app, ["circle"], page) == ["circle"] and app.ride_pick.move == before


def test_running_type_is_green_and_excluded_red(ui):
    page, app, *_ = ui
    go(page, "autopilot")
    page.wait_for_selector("#ride-colour [data-fx=pulse]")
    page.click("#ride-colour [data-fx=pulse]")
    page.wait_for_selector("#ride-colour [data-fx=pulse].sel")  # the pointer stays on it, like a finger on a touch screen
    ok, bad = page.evaluate("""() => { const s = getComputedStyle(document.documentElement);
        return [s.getPropertyValue('--ok').trim(), s.getPropertyValue('--bad').trim()]; }""")
    border = page.eval_on_selector("#ride-colour [data-fx=pulse]", "b => getComputedStyle(b).borderTopColor")
    probe = page.evaluate("c => { const d = document.createElement('div'); d.style.color = c; document.body.append(d); "
                          "const v = getComputedStyle(d).color; d.remove(); return v; }", ok)
    assert border == probe  # green: running now
    app.exclude_fx("twinkle", True)
    go(page, "live")
    go(page, "autopilot")
    page.wait_for_selector("#ride-colour [data-fx=twinkle].excluded")
    bg = page.eval_on_selector("#ride-colour [data-fx=twinkle]", "b => getComputedStyle(b).backgroundColor")
    assert bg != page.eval_on_selector("#ride-colour [data-fx=static]", "b => getComputedStyle(b).backgroundColor")
    assert bad


def test_one_green_button_per_bank(ui):
    page, app, *_ = ui
    go(page, "autopilot")
    page.wait_for_selector("#ride-move [data-fx=swim]")
    page.click("#ride-move [data-fx=swim]")
    page.wait_for_selector("#ride-move [data-fx=swim].sel")
    page.wait_for_function("document.querySelectorAll('#ride-move .ride-fx.sel').length === 1")  # not "No movement" too
    page.click("#ride-move [data-fx='']")
    page.wait_for_function("document.querySelector(\"#ride-move [data-fx='']\").classList.contains('sel')")
    assert page.locator("#ride-move .ride-fx.sel").count() == 1
