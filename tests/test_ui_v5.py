# ruff: noqa: F811 - pytest fixtures imported from test_ui are used as arguments
"""v5 browser tests: Monitor test patterns, cycle test, health checks, fault-find."""

import shutil

import pytest
import yaml
from test_ui import SHOWS, TOKEN, browser, go, ui  # noqa: F401,F811 - pytest fixtures

from dmx_suite.app import App
from dmx_suite.output import make_driver
from dmx_suite.showfiles import load_show
from dmx_suite.web.server import WebServer

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def test_monitor_test_panel_runs_and_stops_on_leave(ui):
    page, app, root, _ = ui
    go(page, "monitor")
    page.wait_for_selector("#test-target option", state="attached")
    page.select_option("#test-pattern", "chase")
    assert page.is_visible("#test-dwell") and not page.is_visible("#test-fixture")
    page.select_option("#test-pattern", "all_full")
    page.click("#test-go")
    page.wait_for_selector("#test-live:not(.hidden)")
    assert "All full" in page.inner_text("#test-name")
    page.wait_for_function("document.querySelector('#mon-dmx-stats').textContent.startsWith('TEST: All full')")
    assert "testing" in page.get_attribute("#mon-dmx", "class")
    assert page.eval_on_selector("#test-stop", "e => e.getBoundingClientRect().height") >= 44  # big Stop
    assert app.engine.test is not None and app.engine.test.by == "ui"
    go(page, "live")  # leaving the page stops it
    page.wait_for_function("() => true")
    for _ in range(50):
        if app.engine.test is None:
            break
        page.wait_for_timeout(50)
    assert app.engine.test is None and app.engine.test_log[-1]["what"] == "page left"


def test_monitor_test_panel_stop_button_and_gig_lock(ui):
    page, app, root, _ = ui
    go(page, "monitor")
    page.wait_for_selector("#test-target option", state="attached")
    page.select_option("#test-pattern", "find")
    page.click("#test-go")
    page.wait_for_selector("#test-live:not(.hidden)")
    page.click("#test-stop")
    page.wait_for_selector("#test-live.hidden", state="attached")
    assert app.engine.test is None
    app.set_gig_lock(True)
    page.wait_for_function("() => true")
    page.select_option("#test-pattern", "all_full")
    page.wait_for_function("document.querySelector('#test-go').disabled")
    page.select_option("#test-pattern", "keep_alive")
    assert not page.is_disabled("#test-go")
    app.set_gig_lock(False)


@pytest.fixture
def open_ui(browser, tmp_path):
    """The UI with a USB DMX (Open) output (its port doesn't exist here)."""
    from dmx_suite import settings

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    p = root / "rigs" / "full.yaml"
    rig = yaml.safe_load(p.read_text())
    rig["outputs"] = [{"driver": "usb_dmx_open", "port": "COM_NONE", "universe": 0, "alias": "Stage DMX"}]
    p.write_text(yaml.safe_dump(rig))
    files = load_show(root)
    app = App(files, [make_driver(o) for o in files.rig.outputs])
    app.engine.start()
    settings.save({"wizard": "skipped"})
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN)
    web.start()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{web.port}/?t={TOKEN}")
    page.wait_for_selector("body.ready", timeout=10000)
    yield page, app, p
    page.close()
    web.stop()
    app.engine.stop()
    for d in app.engine.drivers:
        d.close()
    assert errors == []


def test_cycle_methods_big_step_and_lights_responded(open_ui, monkeypatch):
    from dmx_suite import dmxcheck

    page, app, p = open_ui
    monkeypatch.setattr(dmxcheck, "STEP_S", 1.5)
    app.engine.drivers[0]._d2xx_available = lambda: False
    go(page, "monitor")
    page.wait_for_selector("#test-target option[value='o:0']", state="attached")
    page.select_option("#test-target", "o:0")
    page.wait_for_selector("#cycle-go:not(.hidden)")
    page.click("#cycle-go")
    page.wait_for_selector("#cycle-live:not(.hidden)")
    assert page.inner_text("#cycle-step") == "Serial break, 176 µs"
    assert page.eval_on_selector("#cycle-step", "e => parseFloat(getComputedStyle(e).fontSize)") >= 36
    page.wait_for_function("document.querySelector('#cycle-step').textContent.startsWith('Baud drop')")
    page.click("#cycle-yes")
    page.wait_for_function("document.querySelector('#cycle-result').textContent.startsWith('Saved: Baud drop')")
    assert yaml.safe_load(p.read_text())["outputs"][0]["break_method"] == "baud_drop"


def test_timing_and_checks_shown(open_ui):
    from test_v5_checks import FakeProbe, FakeRegistry

    page, app, p = open_ui
    app.registry = FakeRegistry("COM_NONE")
    app.health_probe = FakeProbe(latency=16, suspend_plan=False)
    app.check_outputs()
    go(page, "monitor")
    page.wait_for_selector("#test-target option[value='o:0']", state="attached")
    page.wait_for_function("document.querySelector('#mon-dmx-timing').textContent.includes('target 176')")
    assert "VCP" in page.inner_text("#mon-dmx-timing")
    page.wait_for_function("document.querySelector('#mon-dmx-checks').textContent.includes('Latency timer: 16 ms')")
    go(page, "layout")
    page.wait_for_function("[...document.querySelectorAll('#lp-routing td')].some(td => td.textContent.includes('break'))")
    cell = page.locator("#lp-routing td.amber")
    assert cell.count() == 1 and "Latency timer" in cell.get_attribute("title")


def test_fault_find_wizard(open_ui):
    from test_v5_checks import FakeProbe, FakeRegistry

    page, app, p = open_ui
    app.registry = FakeRegistry("COM_NONE")
    app.health_probe = FakeProbe(latency=1, suspend_plan=False)
    go(page, "monitor")
    page.click("#ff-open")
    page.wait_for_selector("#ff:not(.hidden)")
    page.wait_for_function("document.querySelector('#ff-text').textContent.includes('auto / sound')")
    page.click("#ff-answers button:has-text('Yes')")
    page.wait_for_function("document.querySelector('#ff-where').textContent === 'Step 1 of 5'")
    assert "cycle test" in page.inner_text("#ff-text")
    assert page.locator("#ff-answers button:has-text('Run test')").count() == 1
    page.click("#ff-answers button:has-text('Fail')")
    page.wait_for_function("document.querySelector('#ff-where').textContent === 'Step 2 of 5'")
    page.click("#ff-answers button:has-text('Pass')")
    page.wait_for_function("document.querySelector('#ff-text').textContent.startsWith('found at')")
    assert page.locator("#ff-history li").count() == 4
    assert "Start again" in page.inner_text("#ff-answers")


def test_red_dmx_badge_opens_the_wizard(open_ui):
    from test_v5_checks import FakeProbe, FakeRegistry

    page, app, p = open_ui
    app.registry = FakeRegistry("COM_NONE")
    app.health_probe = FakeProbe(latency=16, suspend_plan=False)
    app.check_outputs()
    page.wait_for_selector(".tile.link[data-key^='dmx_check:']")
    page.click(".tile.link[data-key^='dmx_check:']")
    page.wait_for_selector("#page-monitor.on")
    page.wait_for_selector("#ff:not(.hidden)")


# ---------------------------------------------------------------- v6 Part A: Darkness


def test_darkness_slider_big_and_live(ui):
    page, app, root, _ = ui
    go(page, "autopilot")
    page.wait_for_selector("#dk-slider")
    assert page.eval_on_selector("#dk-slider", "e => e.getBoundingClientRect().height") >= 44  # live control: big
    page.eval_on_selector("#dk-slider", "e => { e.value = 40; e.dispatchEvent(new Event('input')); }")
    for _ in range(40):
        if app.darkness.status()["darkness"] == 40:
            break
        page.wait_for_timeout(50)
    assert app.darkness.status()["darkness"] == 40 and app.darkness.status()["source"] == "slider"
    page.wait_for_function("document.querySelector('#dk-val').textContent === '40 %'")
    page.click("#ride-darkness [data-dkset=low]")
    page.wait_for_function("document.querySelector('#ride-darkness [data-dkset=low]').textContent.includes('40 %')")
    assert yaml.safe_load((root / "rigs" / "full.yaml").read_text())["autopilot"]["set_darkness"]["low"] == 40


def test_step_editor_lit(ui):
    from test_ui_v4 import open_steps

    page, app, root, _ = ui
    open_steps(page)
    page.click("#scene-group-tabs [data-group=bars]")
    page.click("#step-programmer .swatches button[title=red]")
    page.wait_for_selector("#step-programmer input[data-lit]")
    page.eval_on_selector("#step-programmer input[data-lit]", "e => { e.value = 50; e.dispatchEvent(new Event('change')); }")
    page.wait_for_function("document.querySelector('#step-programmer .prog-row[data-attr=lit]').classList.contains('prog')")


# ---------------------------------------------------------------- v6 Part B: Tempo pane


def test_tempo_pane_draws_and_switches_source(ui):
    page, app, root, _ = ui
    go(page, "monitor")
    page.wait_for_selector("#tempo-source")
    page.select_option("#tempo-source", "drums")
    for _ in range(40):
        if app.ctl.tempo.source == "drums":
            break
        page.wait_for_timeout(50)
    assert app.ctl.tempo.source == "drums"
    page.click("#tempo-tap")
    page.wait_for_timeout(500)
    page.click("#tempo-tap")
    page.wait_for_function("document.querySelector('#tempo-bpm').textContent.includes('BPM')")
    assert "seed: tap" in page.inner_text("#tempo-info")
    page.click("#tempo-params-btn")
    page.wait_for_selector("#tempo-params:not(.hidden) input")
    assert page.locator("#tempo-params input").count() >= 15


# ---------------------------------------------------------------- v6 Part C: Drum Kit


def test_drum_kit_section_learn_live_and_unmapped(ui):
    import mido

    page, app, root, _ = ui
    go(page, "midi")
    page.wait_for_selector("#kit-rows tr[data-input=snare]")
    assert "first change saves it" in page.inner_text("#kit-note")  # the view, nothing written yet
    page.click("#kit-rows tr[data-input=tom_2] button[data-learn]")
    page.wait_for_function("document.querySelector('#kit-learning').textContent.startsWith('Hit the')")
    app.router.handle_mido(mido.Message("note_on", channel=9, note=41, velocity=100), "TD-25")
    page.wait_for_function("document.querySelector('#kit-learning').textContent.includes('note 41')")
    page.wait_for_function("document.querySelector('#kit-rows tr[data-input=tom_2] .notes').value === '41'")
    assert yaml.safe_load((root / "inputs.yaml").read_text())["active_kit"] == "band_kit"  # saved as a real kit now
    app.router.handle_mido(mido.Message("note_on", channel=9, note=38, velocity=100), "TD-25")
    page.wait_for_selector("#kit-rows tr[data-input=snare].hit")
    app.router.handle_mido(mido.Message("note_on", channel=9, note=99, velocity=90), "TD-25")
    page.wait_for_function("document.querySelector('#kit-unmapped').textContent.includes('99')")
    page.fill("#kit-rows tr[data-input=snare] input.wide >> nth=0", "bar_1, bar_2")
    page.locator("#kit-rows tr[data-input=snare] input.wide >> nth=0").dispatch_event("change")
    for _ in range(40):
        if app.files.midimap.get_input("snare").params["fixtures"] == ["bar_1", "bar_2"]:
            break
        page.wait_for_timeout(50)
    assert app.files.midimap.get_input("snare").params["fixtures"] == ["bar_1", "bar_2"]


# ---------------------------------------------------------------- UI polish (28/11/2026 review)

UNNAMED = """() => [...document.querySelectorAll(
    'section.page.on input:not([type=hidden]):not([type=checkbox]):not([type=radio]),'
  + ' section.page.on select, section.page.on textarea')]
  .filter(e => e.offsetParent && !e.closest('.hidden'))
  .filter(e => !(e.getAttribute('aria-label') || e.title || e.placeholder || e.closest('label')
    || (e.id && document.querySelector('label[for="' + e.id + '"]'))))
  .map(e => (e.id || e.className || e.tagName) + ' in ' + (e.parentElement?.tagName || ''))"""


def test_every_field_has_a_name(ui):
    page, *_ = ui
    for p in ("live", "autopilot", "override", "shows", "review", "layout", "fixtures", "heads", "midi", "monitor", "setup"):
        go(page, p)
        page.wait_for_timeout(400)
        assert page.evaluate(UNNAMED) == [], p


def test_header_is_short_and_full_line_on_hover(ui):
    page, app, *_ = ui
    app.ctl.select_show("band", "mid")
    page.wait_for_function("document.querySelector('#now').textContent.includes('Main band show')")
    text, title = page.inner_text("#now"), page.get_attribute("#now", "title")
    assert "fixed timers" not in text and "|" not in text and "Main band show" in text
    assert title and "|" in title


def test_dmx_grid_cells_readable(ui):
    page, *_ = ui
    go(page, "monitor")
    page.wait_for_selector("#mon-dmx-body .dc[data-ch='512']")
    w = page.eval_on_selector("#mon-dmx-body .dc[data-ch='1']", "e => e.getBoundingClientRect().width")
    assert w >= 30
    ok = page.evaluate("""() => [...document.querySelectorAll('#mon-dmx-body .dc')].slice(0, 64).every(c => {
      const n = c.querySelector('.n').getBoundingClientRect(), v = c.querySelector('.v').getBoundingClientRect();
      return !v.width || v.top >= n.bottom - 1; })""")
    assert ok  # the value sits under the channel number, never on it


def test_midi_mappings_read_like_words(ui):
    page, *_ = ui
    go(page, "midi")
    page.wait_for_selector("#inputs td.mapped")
    text = " ".join(page.locator("#inputs td.mapped").all_inner_texts())
    assert "['" not in text and "=" not in text and "Flash · bars · 120 ms" in text


def test_danger_text_contrast_and_checkbox_size(ui):
    page, *_ = ui
    go(page, "shows")
    page.wait_for_selector("#show-del")
    ratio = page.evaluate("""() => {
      const e = document.querySelector('#show-del');
      const rgb = c => c.match(/[\\d.]+/g).map(Number);
      const lin = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; };
      const lum = ([r, g, b]) => .2126 * lin(r) + .7152 * lin(g) + .0722 * lin(b);
      let bg = null;
      for (let n = e; n && !bg; n = n.parentElement) {
        const c = rgb(getComputedStyle(n).backgroundColor);
        if ((c[3] ?? 1) > .5) bg = c;
      }
      const a = lum(rgb(getComputedStyle(e).color)), b = lum(bg); return (Math.max(a,b)+.05)/(Math.min(a,b)+.05); }""")
    assert ratio >= 4.5
    go(page, "scenes")
    sizes = page.evaluate("() => [...document.querySelectorAll('section.page.on input[type=checkbox]')]"
                          ".filter(e => e.offsetParent).map(e => e.getBoundingClientRect().width)")
    assert sizes and min(sizes) >= 20


def test_layout_fields_fit_auto(ui):
    page, *_ = ui
    go(page, "layout")
    page.wait_for_selector("#ar-spacing")
    assert page.eval_on_selector("#ar-spacing", "e => e.clientWidth >= e.scrollWidth && e.getBoundingClientRect().width >= 60")


# ---------------------------------------------------------------- phone and gig pass (option 2)


@pytest.fixture
def phone(browser, ui):
    page, app, root, errors = ui
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, device_scale_factor=1)
    p = ctx.new_page()
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(page.url)
    p.wait_for_selector("body.ready")
    yield p, app
    ctx.close()


def test_phone_controls_are_finger_sized(phone):
    p, app = phone
    for name in ("autopilot", "override", "scenes", "shows", "live"):  # the phone's bottom bar
        p.click(f"#menu [data-page={name}]")
        p.wait_for_selector(f"#page-{name}.on")
        p.wait_for_timeout(300)
        small = _small(p)
        assert small == [], name
    assert p.eval_on_selector("#master", "e => e.getBoundingClientRect().height") >= 52


def _small(p):
    return p.evaluate("""() => [...document.querySelectorAll('section.page.on button,'
      + ' section.page.on input:not([type=checkbox]):not([type=radio]),'
      + ' section.page.on select, header.top button')].filter(e => e.offsetParent && !e.closest('.hidden'))
      .filter(e => e.getBoundingClientRect().height < (e.matches('button.info') ? 32 : 40))
      .map(e => e.id || e.textContent.trim().slice(0, 20))""")


def test_phone_status_summary_and_now_line(phone):
    p, app = phone
    p.wait_for_selector("#health .health-sum")
    assert p.is_visible("#health .health-sum") and not p.is_visible("#health .tile[data-key^='engine:']")
    assert p.evaluate("document.documentElement.scrollWidth") <= 390
    p.click("#health .health-sum")
    p.wait_for_selector("#health.open .tile[data-key^='engine:']")
    app.ctl.select_show("band", "mid")
    p.wait_for_function("document.querySelector('#now').textContent.includes('Main band show')")
    assert p.is_visible("#now")


def test_live_stage_folds_and_is_remembered(ui, phone):
    page, *_ = ui
    p, _ = phone
    assert not p.is_visible("#live-grid") and "Show stage" in p.inner_text("#stage-fold")  # folded on a phone
    assert page.is_visible("#live-grid")  # shown on the laptop
    page.click("#stage-fold")
    assert not page.is_visible("#live-grid")
    page.reload()
    page.wait_for_selector("body.ready")
    assert not page.is_visible("#live-grid") and page.get_attribute("#stage-fold", "aria-expanded") == "false"
    page.click("#stage-fold")
    assert page.is_visible("#live-grid")


def test_override_empty_state_has_a_first_step(phone):
    p, app = phone
    p.click("#menu [data-page=override]")
    p.wait_for_selector("#page-override.on #override-start")
    assert not p.is_visible("#panel-pick") and not p.is_visible("#override-release")
    p.click("#override-start")
    p.wait_for_selector("#override-editor:not(.hidden)")
    p.wait_for_function("document.activeElement.id === 'panel-name'")
