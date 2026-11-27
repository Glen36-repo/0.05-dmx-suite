# ruff: noqa: F811 - pytest fixtures imported from test_ui are used as arguments
"""v4.1 ⓘ information buttons: every button has its text; the popover never gets in the way of
playing the show (taps pass through, Esc closes only it, shortcuts keep working, gig lock is fine)."""

import json
import re
from pathlib import Path

import pytest
from test_access import call, remote, server  # noqa: F401 - pytest fixture
from test_ui import browser, go, ui  # noqa: F401 - pytest fixtures

from dmx_suite import manual

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "dmx_suite" / "web" / "static"
MANUAL = ROOT / "docs" / "manual"


def strings():
    return json.loads((STATIC / "i18n" / "en.json").read_text(encoding="utf-8"))


def used_info_keys():
    keys = set(re.findall(r'data-info="([^"]+)"', (STATIC / "index.html").read_text(encoding="utf-8")))
    for js in (STATIC / "js").rglob("*.js"):
        keys |= set(re.findall(r'infoButton\("([a-z0-9_]+\.[a-z0-9_]+)"\)', js.read_text(encoding="utf-8")))
    return keys


def test_every_info_button_has_its_text():
    s = strings()
    missing = sorted(k for k in used_info_keys() for part in ("title", "text") if f"info.{k}.{part}" not in s)
    assert missing == []
    for k in used_info_keys():
        text = s[f"info.{k}.text"]
        assert 20 <= len(text) <= 420, f"{k}: keep it to a few lines ({len(text)} chars)"


# ---------------------------------------------------------------- in the browser

POP = "#info-pop:not(.hidden)"


def test_open_close_by_second_tap_outside_tap_and_esc(ui):
    page, *_ = ui
    go(page, "live")
    btn = "#page-live button.info[data-info='live.shows']"
    page.click(btn)
    page.wait_for_selector(POP)
    assert "Shows" in page.inner_text("#info-pop") and page.get_attribute(btn, "aria-expanded") == "true"
    assert page.get_attribute(btn, "aria-label") == "About: Shows"
    page.click(btn)  # second tap
    page.wait_for_selector(POP, state="hidden")
    page.click(btn)
    page.wait_for_selector(POP)
    page.click("#page-live h2[data-i18n='live.setlist']")  # anywhere else
    page.wait_for_selector(POP, state="hidden")
    page.click(btn)
    page.keyboard.press("Escape")
    page.wait_for_selector(POP, state="hidden")


def test_info_in_summary_doesnt_fold_the_section(ui):
    page, *_ = ui
    go(page, "live")
    assert page.get_attribute("#haze-settings", "open") is None
    page.click("#haze-settings summary button.info")
    page.wait_for_selector(POP)
    assert page.get_attribute("#haze-settings", "open") is None  # still folded
    assert "rule 5" in page.inner_text("#info-pop")


def test_info_on_the_stage_doesnt_select_lights(ui):
    page, *_ = ui
    go(page, "layout")
    page.wait_for_selector("#layout-grid [data-id=bar_1]")
    page.click("#group-tabs [data-group=bars]")
    before = page.eval_on_selector_all("#layout-grid .fx.sel", "els => els.length")
    page.click("#page-layout button.info.on-stage")
    page.wait_for_selector(POP)
    assert page.eval_on_selector_all("#layout-grid .fx.sel", "els => els.length") == before == 4


def test_esc_closes_only_the_popover(ui):
    page, *_ = ui
    go(page, "layout")
    page.wait_for_selector("#layout-grid [data-id=bar_1]")
    page.click("#group-tabs [data-group=bars]")
    page.click("#page-layout button.info.on-stage")
    page.wait_for_selector(POP)
    page.keyboard.press("Escape")  # on the Layout page Esc would also clear the selection
    page.wait_for_selector(POP, state="hidden")
    assert page.eval_on_selector_all("#layout-grid .fx.sel", "els => els.length") == 4
    page.keyboard.press("Escape")  # with nothing open, Esc does its usual job again
    assert page.eval_on_selector_all("#layout-grid .fx.sel", "els => els.length") == 0


def test_outside_tap_still_reaches_the_control(ui):
    page, app, *_ = ui
    go(page, "live")
    page.wait_for_selector("#scenes [data-scene=opera]")
    page.click("#page-live button.info[data-info='live.shows']")
    page.wait_for_selector(POP)
    page.click("#scenes [data-scene=opera]")  # mid-gig: the scene must play, not just close the popover
    page.wait_for_selector(POP, state="hidden")
    page.wait_for_function("document.querySelector('#scenes [data-scene=opera]').classList.contains('sel')")
    assert app.ctl.now().scene == "opera"
    page.click("#page-live button.info[data-info='live.shows']")
    master = app.engine.master
    page.click("#master")
    page.wait_for_selector(POP, state="hidden")
    for _ in range(40):
        if app.engine.master != master:
            break
        page.wait_for_timeout(25)
    assert app.engine.master != master


def test_shortcuts_work_with_a_popover_open(ui):
    page, *_ = ui
    go(page, "layout")
    page.wait_for_selector("#layout-grid [data-id=bar_1]")
    page.click("#page-layout button.info.on-stage")  # opened by a tap: focus stays where it was
    page.wait_for_selector(POP)
    page.keyboard.press("Control+a")
    assert page.eval_on_selector_all("#layout-grid .fx.sel", "els => els.length") > 4
    page.keyboard.press("Escape")
    # opened from the keyboard: focus goes into it, and shortcuts still pass through
    page.focus("#page-layout button.info.on-stage")
    page.keyboard.press("Enter")
    page.wait_for_selector(POP)
    assert page.evaluate("document.activeElement.closest('#info-pop') !== null")
    page.keyboard.press("Control+a")
    assert page.eval_on_selector_all("#layout-grid .fx.sel", "els => els.length") > 4
    page.keyboard.press("Escape")
    page.wait_for_selector(POP, state="hidden")
    assert page.evaluate("document.activeElement.dataset.info") == "layout.stage"  # focus back on the ⓘ


def test_one_at_a_time_and_inside_a_phone_screen(ui):
    page, *_ = ui
    go(page, "live")
    page.click("#page-live button.info[data-info='live.shows']")
    page.click("#haze-settings summary button.info")
    assert page.locator(".info-pop").count() == 1 and page.get_attribute("#info-pop", "data-key") == "live.haze"
    page.set_viewport_size({"width": 390, "height": 760})
    page.keyboard.press("Escape")
    page.click("#page-live button.info[data-info='live.shows']")
    box = page.locator("#info-pop").bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 390 and box["y"] >= 0 and box["y"] + box["height"] <= 760
    top = page.locator(".top").bounding_box()
    assert box["y"] >= top["y"] + top["height"]  # never over MASTER / BLACKOUT


def test_works_under_gig_lock(ui):
    page, app, *_ = ui
    app.set_gig_lock(True)
    go(page, "live")
    page.click("#page-live button.info[data-info='live.shows']")
    page.wait_for_selector(POP)
    assert "Shows" in page.inner_text("#info-pop")


@pytest.mark.parametrize("key", ["live.shows", "layout.stage"])
def test_manual_link_points_at_a_page(ui, key):
    page, *_ = ui
    go(page, key.split(".")[0])
    page.click(f"button.info[data-info='{key}']")
    href = page.get_attribute("#info-pop .info-pop-more", "href")
    assert href.startswith("/manual/") and ".md" in href


# ---------------------------------------------------------------- the in-app manual


def info_manual():
    js = (STATIC / "js" / "info.js").read_text(encoding="utf-8")
    block = js[js.index("INFO_MANUAL"):]
    return dict(re.findall(r'"([a-z0-9_.]+)":\s*"([a-z0-9-]+\.md(?:#[a-z0-9_-]+)?)"', block[:block.index("};")]))


def test_every_manual_link_goes_to_a_real_section():
    targets = info_manual()
    assert len(targets) > 10
    for key, target in targets.items():
        name, _, anchor = target.partition("#")
        f = MANUAL / name
        assert f.is_file(), (key, target)
        if anchor:
            assert f'id="{anchor}"' in manual.render(f.read_text(encoding="utf-8")), (key, target)


def test_manual_dir_is_the_repo_docs():
    assert manual.manual_dir() == MANUAL and (MANUAL / "README.md").is_file()


def test_render_blocks():
    html = manual.render("""# Title

Some *words* and **bold** with `a <b>` code.

## Outputs: which universe goes where

- one
- two
  - nested
1. first
2. second

| A | B |
| --- | --- |
| `x` | y |

```yaml
key: <value>
```
""")
    assert '<h1 id="title">Title</h1>' in html
    assert '<h2 id="outputs-which-universe-goes-where">' in html
    assert "<em>words</em>" in html and "<strong>bold</strong>" in html and "<code>a &lt;b&gt;</code>" in html
    assert "<ul><li>one</li><li>two<ul><li>nested</li></ul></li></ul>" in html
    assert "<ol><li>first</li><li>second</li></ol>" in html
    assert "<th>A</th>" in html and "<td><code>x</code></td>" in html
    assert '<pre><code class="lang-yaml">key: &lt;value&gt;</code></pre>' in html


def test_render_escapes_html():
    html = manual.render('<script>alert(1)</script>\n\n# <img src=x onerror=alert(1)>\n\n| <b> |\n| - |\n| <i> |')
    assert "<script" not in html and "<img" not in html and "<b>" not in html and "<i>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.parametrize("md, want", [
    ("[Layout](layout.md)", '<a href="/manual/layout.md">Layout</a>'),
    ("[Addr](layout.md#addresses)", '<a href="/manual/layout.md#addresses">Addr</a>'),
    ("[Up](#stage)", '<a href="#stage">Up</a>'),
    ("[Site](https://example.com/a?b=1&c=2)",
     '<a href="https://example.com/a?b=1&amp;c=2" target="_blank" rel="noopener" data-external>Site</a>'),
    ("[x](javascript:alert(1))", "x"),
    ("[x](JavaScript:alert(1))", "x"),
    ("[x](data:text/html,hi)", "x"),
    ("[x](mailto:someone@example.com)", "x"),
    ("[x](../SCOPE.md)", "x"),
    ("[x](/etc/passwd)", "x"),
    ('[x](layout.md"onmouseover="alert(1))', "x"),
])
def test_link_rules(md, want):
    html = manual.render(md)
    assert html.startswith("<p>") and want in html
    if "<a" not in want:
        assert "<a" not in html


@pytest.mark.parametrize("name", ["../README.md", "..%2FREADME.md", "README", "x.md", "/etc/passwd", "Layout.md", "readme.md",
                                  "sub/layout.md", ""])
def test_page_path_refuses_anything_outside(name):
    assert manual.page_path(name) is None


def test_manual_route(server):
    app, web, *_ = server
    status, html, headers = call(web, "/manual/layout.md", raw=True)
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert '/static/themes/' in html and "/theme.css" in html and "/static/style.css" in html
    assert 'id="addresses"' in html and 'href="/manual/README.md"' in html
    assert call(web, "/manual", raw=True)[0] == 200  # the contents
    for bad in ("/manual/../pyproject.toml", "/manual/..%2Fpyproject.toml", "/manual/nope.md",
                "/manual/README.md/x"):
        assert call(web, bad, raw=True)[0] == 404, bad


def test_manual_works_under_gig_lock_and_needs_the_pin_on_the_network(server):
    app, web, access, _ = server
    app.set_gig_lock(True)
    assert call(web, "/manual/shows.md", raw=True)[0] == 200
    access.set_pin("2468")
    access.configure(lan=True)
    remote(web)  # a phone on the network that hasn't signed in
    assert call(web, "/manual/shows.md", raw=True)[0] == 401


def test_manual_page_in_the_browser(ui):
    page, *_ = ui
    base = page.url.split("/?")[0]
    page.goto(f"{base}/manual/layout.md#addresses")
    assert page.is_visible("h2#addresses")
    page.click("a[href='/manual/README.md']")
    page.wait_for_selector("h1")
    assert "manual" in page.inner_text("h1").lower()
