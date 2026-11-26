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
