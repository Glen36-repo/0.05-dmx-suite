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
    assert page.eval_on_selector_all(f"{tile} .pal-sw i", "s => s.length") == 4  # swatches
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


# ------------------------------------------------------------------ A4 layer timing


def test_layer_chips_lock_and_count_down(ui):
    page, app, *_ = ui
    go(page, "autopilot")
    page.click("#ap-toggle")
    page.wait_for_selector("#ap-layers [data-layer=palette]")
    page.wait_for_function("/\\d+ s/.test(document.querySelector('#ap-layers [data-layer=move] .layer-next').textContent)")
    page.click("#ap-layers [data-layer=palette]")
    page.wait_for_selector("#ap-layers [data-layer=palette].locked")
    assert app.autopilot.locked("palette")
    assert page.inner_text("#ap-layers [data-layer=palette] .layer-next") == "locked"
    page.click("#ap-layers [data-layer=palette]")
    page.wait_for_selector("#ap-layers [data-layer=palette]:not(.locked)")
    assert not app.autopilot.locked("palette")


def test_settings_save_staggered_timing(ui):
    import yaml

    page, app, root, _ = ui
    go(page, "autopilot")
    page.click("#ap-settings summary")
    page.wait_for_selector("#ap-timing [data-timing=staggered]")
    page.click("#ap-timing [data-timing=staggered]")
    page.select_option("[data-sched=palette]", "song")
    assert page.is_disabled("[data-val=palette]")
    page.fill("[data-val=move]", "")
    page.select_option("[data-sched=move]", "every_s")
    page.fill("[data-val=move]", "30")
    page.fill("[data-spread=move]", "10")
    page.click("#ap-settings-save")
    page.wait_for_function("() => true")
    for _ in range(80):
        if app.autopilot.cfg["timing"] == "staggered":
            break
        page.wait_for_timeout(25)
    ap = yaml.safe_load((root / "rigs" / f"{app.names[0]}.yaml").read_text())["autopilot"]
    assert ap["timing"] == "staggered"
    assert ap["layers"]["palette"] == {"on": "song", "spread": 25}
    assert ap["layers"]["move"] == {"every_s": 30, "spread": 10}
    assert app.autopilot.cfg["layers"]["move"] == {"every_s": 30, "spread": 10, "locked": False}


# ------------------------------------------------------------------ A3 darkness Auto


def test_darkness_auto_markers_and_back_to_manual(ui):
    import yaml

    page, app, root, _ = ui
    go(page, "autopilot")
    page.wait_for_selector("#dk-mode [data-dkmode=auto]")
    assert not page.is_visible("#dk-min")  # Manual: no markers
    page.click("#dk-mode [data-dkmode=auto]")
    page.wait_for_selector("#ride-darkness.auto")
    assert page.is_visible("#dk-mark-min") and page.is_visible("#dk-max")
    slide = "(e, v) => { e.value = v; e.dispatchEvent(new Event('input')); e.dispatchEvent(new Event('change')); }"
    page.eval_on_selector("#dk-max", slide, 80)
    page.eval_on_selector("#dk-min", slide, 90)
    for _ in range(40):
        if app.darkness.status()["min"] == 90:
            break
        page.wait_for_timeout(50)
    st = app.darkness.status()
    assert st["mode"] == "auto" and st["min"] == 90 and st["max"] == 90  # markers can't cross
    page.fill("#dk-tam", "45")
    page.dispatch_event("#dk-tam", "change")
    page.wait_for_function("() => true")
    for _ in range(40):
        if app.darkness.status()["time_at_max"] == 45:
            break
        page.wait_for_timeout(50)
    assert app.darkness.status()["time_at_max"] == 45
    page.click("#ride-darkness [data-dkset=high]")  # stores Auto with its markers for HIGH
    sd = {}
    for _ in range(40):
        sd = (yaml.safe_load((root / "rigs" / "full.yaml").read_text()).get("autopilot") or {}).get("set_darkness") or {}
        if isinstance(sd.get("high"), dict):
            break
        page.wait_for_timeout(50)
    assert sd["high"] == {"mode": "auto", "min": 90, "max": 90, "time_at_max": 45}
    page.eval_on_selector("#dk-slider", "e => { e.value = 20; e.dispatchEvent(new Event('input')); }")  # hands on
    page.wait_for_selector("#ride-darkness:not(.auto)")
    assert page.inner_text("#dk-note") == "Moved by hand: back to Manual"
    assert app.darkness.status()["mode"] == "manual"


# ------------------------------------------------------------------ A5 smaller tiles


def test_fx_tiles_at_three_quarters(ui):
    page = ui[0]
    go(page, "autopilot")
    page.wait_for_selector("#ride-colour [data-fx=pulse]")
    for sel in ("#ride-colour [data-fx=pulse]", "#ride-move [data-fx]", "#ride-palettes [data-palette=fire]"):
        st = page.eval_on_selector(sel, "e => { const c = getComputedStyle(e); "
                                        "return [parseFloat(c.minHeight), parseFloat(c.fontSize)]; }")
        assert st[0] == 33 or "palette" in sel  # 75 % of the v6 44 px
        assert st[1] >= 12  # the text floor
    cols = page.eval_on_selector("#ride-colour", "e => getComputedStyle(e).gridTemplateColumns.split(' ').length")
    assert cols >= 3


def test_fx_tiles_keep_the_touch_minimum(browser):
    import shutil
    import tempfile
    from pathlib import Path

    from test_ui import go as go_

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
        page.wait_for_selector("body.ready")
        go_(page, "autopilot")
        page.wait_for_selector("#ride-colour [data-fx=pulse]")
        for sel in ("#ride-colour [data-fx=pulse]", "#ride-palettes [data-palette=fire]", "#ap-layers [data-layer=move]"):
            assert page.eval_on_selector(sel, "e => e.getBoundingClientRect().height") >= 44
            assert page.eval_on_selector(sel, "e => parseFloat(getComputedStyle(e).fontSize)") >= 12
    finally:
        page.close()
        web.stop()
        app.engine.stop()


# ------------------------------------------------------------------ A6 between songs


def test_between_songs_settings_save(ui):
    import yaml

    page, app, root, _ = ui
    go(page, "autopilot")
    page.click("#ap-settings summary")
    page.wait_for_selector("#bt-gap")
    assert page.input_value("#bt-gap") == "4"
    page.fill("#bt-gap", "6")
    page.fill("#bt-min-song", "30")
    page.select_option("#bt-start", "count_in")
    page.fill("#bt-count", "3")
    page.fill("#bt-fade-in", "5")
    page.click("#bt-ignore summary")
    first = page.eval_on_selector("#bt-ignore [data-item]", "e => e.dataset.item")
    page.check(f"#bt-ignore [data-item='{first}']")
    page.keyboard.press("Escape")
    page.select_option("#bt-look", "blue_chase")
    page.uncheck("#bt-on")
    page.click("#ap-settings-save")
    for _ in range(80):
        if app.autopilot.cfg["between"]["gap_s"] == 6:
            break
        page.wait_for_timeout(25)
    b = yaml.safe_load((root / "rigs" / f"{app.names[0]}.yaml").read_text())["autopilot"]["between"]
    assert b == {"on": False, "gap_s": 6, "min_song_s": 30, "start": "count_in", "count_in": 3, "fade_in": 5,
                 "fade_out": None, "ignore": [first], "look": {"scene": "blue_chase"}}
    page.wait_for_selector("#bt-look")
    page.select_option("#bt-look", "")  # back to a generated look
    page.click("#ap-settings-save")
    for _ in range(80):
        if "scene" not in app.autopilot.cfg["between"]["look"]:
            break
        page.wait_for_timeout(25)
    assert app.autopilot.cfg["between"]["look"]["palette"] == "white"


def test_between_songs_badge(ui):
    page, app, *_ = ui
    go(page, "autopilot")
    ap = app.autopilot
    ap.cfg["between"]["min_song_s"] = 0
    now = app.engine.clock()
    ap.set_on(True, now)
    app.bus.add("snare", ["snare", "activity"], 0.8, now - 9)
    ap.tick(now)
    assert ap.st.between
    page.wait_for_selector("#ap-between:not(.hidden)")
    assert page.inner_text("#ap-between").startswith("Between songs · ")


# ------------------------------------------------------------------ B2 groups picker, B1 Layout strip


def test_groups_picker_on_fixtures(ui):
    page, app, *_ = ui
    go(page, "fixtures")
    page.wait_for_selector("#fx-patch [data-groups=wash_l]")
    page.click("#fx-patch [data-groups=wash_l] summary")
    before = app.files.patch.fixtures["wash_l"].groups
    page.check("#fx-patch [data-groups=wash_l] [data-item=bars]")
    page.once("dialog", lambda d: d.accept("front_wash"))
    page.click("#fx-patch [data-groups=wash_l] .picker-extra")
    page.wait_for_function("document.querySelector('#fx-patch [data-groups=wash_l] .picker-text')"
                           ".textContent.includes('front_wash')")
    page.click("#fx-patch-save")
    for _ in range(80):
        if "front_wash" in app.files.patch.fixtures["wash_l"].groups:
            break
        page.wait_for_timeout(25)
    assert set(app.files.patch.fixtures["wash_l"].groups) == {*before, "bars", "front_wash"}


def test_group_left_empty_is_flagged_with_its_users(ui):
    page, app, _, errors = ui
    go(page, "fixtures")
    page.wait_for_selector("#fx-patch [data-groups=mh_a]")
    heads = [f for f, fx in app.files.patch.fixtures.items() if "heads" in fx.groups]
    for f in heads:  # take every light out of "heads"
        page.click(f"#fx-patch [data-groups={f}] summary")
        page.uncheck(f"#fx-patch [data-groups={f}] [data-item=heads]")
        page.keyboard.press("Escape")
    page.wait_for_selector("#fx-groups-empty [data-empty-group=heads]")
    text = page.inner_text("#fx-groups-empty")
    assert "heads" in text and "scenes/red_movers.yaml" in text  # what still uses it
    page.click("#fx-patch-save")  # refused: scenes use it
    page.wait_for_timeout(300)
    assert all("heads" in app.files.patch.fixtures[f].groups for f in heads)
    errors[:] = [e for e in errors if "400" not in e]  # the refused save, as expected


def test_layout_strip_names_find_and_test(ui):
    page, app, *_ = ui
    go(page, "layout")
    page.wait_for_selector("#lp-fixtures tr[data-id=mh_a] [data-find]")
    assert page.locator("#lp-fixtures input").count() == 0  # no addresses here
    width = page.eval_on_selector(".lp-side", "e => e.getBoundingClientRect().width")
    stage = page.eval_on_selector(".lp-main", "e => e.getBoundingClientRect().width")
    assert width <= 260 and stage > 3 * width  # the stage takes the room
    page.click("#lp-fixtures tr[data-id=mh_a] [data-find]")
    page.wait_for_selector("#lp-fixtures tr[data-id=mh_a] [data-find].sel")
    assert app.engine.find == "mh_a" or app.snapshot()["setup"]["find"] == "mh_a"
    page.click("#lp-fixtures tr[data-id=mh_a] [data-find]")  # off again
    page.click("#lp-fixtures tr[data-id=mh_a] [data-test]")
    for _ in range(80):
        if app.engine.test is not None:
            break
        page.wait_for_timeout(25)
    assert app.engine.test is not None and app.engine.test_status()["fixture"] == "mh_a"
    page.click("#lp-fixtures tr[data-id=mh_a] [data-test]")  # again stops it
    for _ in range(80):
        if app.engine.test is None:
            break
        page.wait_for_timeout(25)
    assert app.engine.test is None
    page.click("#lp-fixtures tr[data-id=bar_2] td:first-child")  # a row picks the light on the stage
    assert page.eval_on_selector_all("#layout-grid .fx.sel", "els => els.map(e => e.dataset.id)") == ["bar_2"]


def test_address_map_panel_remembers_open(ui):
    page, *_ = ui
    go(page, "fixtures")
    page.wait_for_selector("#fx-addr")
    assert not page.eval_on_selector("#fx-addr", "e => e.open")  # closed by default
    page.click("#fx-addr summary")
    page.wait_for_selector("#addr-maps .addr-map")
    go(page, "live")
    go(page, "fixtures")
    assert page.eval_on_selector("#fx-addr", "e => e.open")


# ------------------------------------------------------------------ C1 zones on the Heads page


def test_draw_save_and_delete_a_zone(ui):
    import yaml

    page, app, root, _ = ui
    go(page, "heads")
    area = "[data-pad=mh_a] .area"
    page.wait_for_selector(area)
    page.click("#zones-mode")
    r = page.eval_on_selector(area, "e => { const b = e.getBoundingClientRect(); return [b.x, b.y, b.width, b.height]; }")
    x, y, w, h = r
    page.mouse.move(x + 0.4 * w, y + 0.6 * h)  # pan 40 %, tilt 40 %
    page.mouse.down()
    page.mouse.move(x + 0.6 * w, y + 0.3 * h, steps=5)  # to pan 60 %, tilt 70 %
    page.mouse.up()
    page.wait_for_selector("#zone-editor:not(.hidden)")
    page.fill("#zone-name", "Mirror")
    page.select_option("#zone-scope", "type")
    page.click("#zone-save")
    for _ in range(80):
        if app.engine.rig.head_zones.get("mh_b"):
            break
        page.wait_for_timeout(25)
    z = yaml.safe_load((root / "rigs" / "full.yaml").read_text())["head_zones"]
    m = z["mh_a"][0]
    assert m["name"] == "Mirror" and m["shape"] == "rect" and z["mh_b"][0]["name"] == "Mirror"
    assert abs(m["pan"][0] - 40) < 2 and abs(m["pan"][1] - 60) < 2 and abs(m["tilt"][0] - 40) < 2 and abs(m["tilt"][1] - 70) < 2
    page.wait_for_selector("[data-pad=mh_a] svg.zones .zone[data-zone=Mirror]")
    # aiming isn't possible while drawing; tap the zone to edit it, then delete it
    page.mouse.click(x + 0.5 * w, y + 0.5 * h)
    page.wait_for_selector("#zone-editor:not(.hidden)")
    assert page.input_value("#zone-name") == "Mirror"
    page.select_option("#zone-scope", "head")  # just this one
    page.once("dialog", lambda d: d.accept())
    page.click("#zone-delete")
    for _ in range(80):
        if not app.engine.rig.head_zones.get("mh_a"):
            break
        page.wait_for_timeout(25)
    assert not app.engine.rig.head_zones.get("mh_a") and app.engine.rig.head_zones.get("mh_b")


def test_pad_shows_a_head_held_at_a_zone(ui):
    page, app, *_ = ui
    app.store.put_head_zone("full", "mh_a", {"name": "Wall", "shape": "rect", "pan": [0, 100], "tilt": [0, 100]})
    app.reload()
    go(page, "heads")
    page.wait_for_selector("[data-pad=mh_a].zone-held")
    assert "held at Wall" in page.inner_text("[data-pad=mh_a] .head-row")
