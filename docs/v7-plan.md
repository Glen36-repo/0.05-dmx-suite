# v7 build plan (28/11/2026)

Brief: `docs/v7-brief.md`. Base: `v5-v6` (PR #16, not merged yet). Baseline 1301 tests passing, 4 skipped, ruff clean.
Rules unchanged unless stated below. Every hard rule keeps its tests under both profiles (`tests/rulecheck.py`).

## Conflicts with SCOPE.md (brief wins; SCOPE updated in the same commit as the change)
| SCOPE | Brief | Change |
|---|---|---|
| Addresses, text, motion (28/11): addresses edited on Layout only; Fixtures › Patch read-only with Change → Layout | B1/B2: Fixtures is the one place | Rewrite the row: Universe/Address inline on Fixtures, clash and live-value checks move with them, Layout shows names only |
| v4 Layout / Patch page with an address map of live values | B1: narrow detail strip, no address editor | Address map moves to a collapsible panel on Fixtures (open item 3) |
| Flash colour: "Follows the show colour"; `engine.flash(colour="show")` | D1: a hit opens the ticked lights onto the playing scene | Rewrite row; rule 2 wording in CLAUDE.md becomes "MASTER off → mapped drum hits open the ticked lights onto the live scene, then cut to black" |
| Between songs (V3.4): talking look only, rig YAML only | A6: scene or generated look, settings on the page | Rewrite row; `gap_s` / `count_in` / `talking` move into `autopilot: between:` (format 7) |
| Excluded autopilot types (v4.1): Move, Colour, Drum only | A2: palettes excludable too | Extend row: `auto: exclude_palettes` |
| Ride palette lock (V3.4, `palette_lock` action) | A2/A4: replaced by a per-layer lock | `palette_lock` still read as `autopilot_lock {layer: palette}` |
| v6 darkness: live slider move overrides until next change | A3: Manual / Auto modes | Manual = v6. Auto added; touching slider/pedal drops to Manual |
| Rule 8: head limits only | C1: exclusion zones at the same layer | Extend rule 8 (CLAUDE.md and SCOPE): "head limits and exclusion zones" |
| Show file (26/11): saved on every change | E1: Auto-save / Manual save | Setting per laptop, default Auto-save (today) |
| Startup state: `startup.master` per rig; Resume after restart restores show/set/MASTER | E3: Autopilot on + LOW + MASTER on every launch | Setting per laptop, default Autopilot LOW. "Resume last state" keeps today's behaviour. Rig `startup.master` used only under Resume |
| Kick light in auto shows: white most steps | A1: under Autopilot, kick takes the look's colour | A1 applies to Autopilot only. v1 auto shows (`auto.py`) unchanged. Flagged, not changed |

## Decisions (28/11/2026, from the brief's assumptions)
1. A3: Time at Max = share of time at the **Max marker**. Auto changes on the Darkness layer clock (A4). Touching the slider or pedal in Auto → Manual, with an on-screen note.
2. B2: address map kept as a collapsible panel on Fixtures (closed by default).
3. E1: Auto-save / Manual save setting, default Auto-save.
4. E3: start-up is a setting, default Autopilot on + LOW + MASTER on.
5. A6: all proposed between-songs settings built.
6. The tick-box picker is built in Part A (A6 "ignore inputs" is its first user), then reused in B2 and D1.
7. One format bump for the release: **6 → 7** in Part A (first new keys). Part D adds its steps to the same 6 → 7 upgrade (nothing ships between parts).

## Show file format change (6 → 7)
Bump `FORMAT` to 7 in `dmx_suite/versions.py` (Part A). One upgrade step per kind, each with a test; golden frames identical before and after.

Rig (`rigs/*.yaml`), Part A, rewritten by the step:
```yaml
# format 6
autopilot:
  gap_s: 4
  count_in: 4
  talking: {colour: static, palette: white, move: kit}
  darkness: 30
  set_darkness: {low: 10, high: 40}

# format 7
autopilot:
  darkness: 30                 # Manual value (unchanged)
  set_darkness: {low: 10, high: 40}   # a number still = Manual value for that set
  between:
    on: true
    gap_s: 4
    start: first_hit           # first_hit | count_in
    count_in: 4
    min_song_s: 20
    fade_in: null              # null = LOW fade
    fade_out: null             # null = the song's mood fade
    ignore: []                 # named input / kit zone ids
    look: {colour: static, palette: white, move: kit}   # or {scene: <scene id>}
  # walk_on / walk_off also take {scene: <id>}
```
Rig, Part A, additive (no step; defaults when missing):
```yaml
autopilot:
  darkness_mode: manual        # manual | auto
  darkness_auto: {min: 0, max: 60, time_at_max: 30}            # %
  set_darkness: {mid: {mode: auto, value: 20, min: 10, max: 70, time_at_max: 25}}
  timing: together             # together | staggered
  layers:
    move:     {every_s: 30, spread: 20, locked: false}
    colour:   {every_looks: 2, spread: 20}
    palette:  {on: song}       # song | set
    darkness: {every_s: 12, spread: 30}
auto:
  exclude_palettes: [ice]
head_zones:                    # Part C
  mh_a:
    - {name: Mirror, shape: rect, pan: [40, 55], tilt: [10, 30], black: false}
    - {name: Front row, shape: ellipse, centre: [50, 80], radius: [20, 8], black: true}
```
MIDI maps (`midi/*.yaml`) and `inputs.yaml` kit zones, Part D, rewritten by the step: flash `colour:` removed (a hit shows the live scene). An old `colour: white` flash is logged once in the upgrade note.

Settings (app data `settings.json`, not the show file), Part E: `save_mode: auto|manual`, `startup: autopilot_low|resume`.

## Part A: Autopilot (`v7-a-autopilot`)
Built in this order (format bump and picker first, as later items need them).

0. **Format 7 and the between block.** `versions.py` FORMAT 7, rig step 6 → 7 (gap_s / count_in / talking → `between`). `autopilot.parse_config` reads `between`.
   - Files: `dmx_suite/versions.py`, `dmx_suite/autopilot.py`, `shows/rigs/*.yaml` (written by the upgrade), `tests/data/` (v6 sample)
   - Tests: `test_v7_migration.py`: v6 rig upgrades and backs up; goldens identical; newer refused; old keys still read

1. **Tick-box picker** (shared component). Dropdown with a tick per item, grouped (Moving heads / Pixel bars / Pars / Kick … for lights; device for inputs), All / None and a tick per group, summary when closed ("4 bars, kick", "All lights").
   - Files: new `web/static/js/picker.js`, `style.css`, `i18n/en.json`
   - Tests: `test_ui.py` (Playwright): group ticks, All/None, summary text, keyboard and 44 px touch targets

2. **A1 Kick light follows the look.** `fxbanks.compose` adds a kick layer: the colour item on the kick light alone (a chase over one light cycles its colours), or the palette when the item is pixel-only. `lit: 100` and the Darkness skip stay. MASTER-exempt unchanged. `kick_colour` still used by scenes that leave the kick off.
   - Files: `dmx_suite/fxbanks.py`, `dmx_suite/app.py` (ride_play darkness skip check)
   - Tests: `test_fx_banks.py`: Fire → kick red/orange; colour_chase → kick changes colour over time; kick lit while darkness 100; rulecheck both profiles (Generic: kick is an ordinary wash, unaffected)

3. **A2 Palette bank.** Palette tiles beside Move / Colour / Flash FX: swatches + mood tags, green = playing, red = excluded. Tap = play now; Exclude… mode / 0.6 s hold as FX. `auto: exclude_palettes` in `classify.py`; `_palettes_for` skips them.
   - Actions: MIDI/API `autopilot_palette` (exists), new `exclude_palette {palette, excluded}`. MCP: `play_palette`, `exclude_palette`
   - Files: `classify.py`, `autopilot.py`, `app.py`, `midi/map.py`, `web/server.py`, `views/autopilot.js`, `mcp_server.py`, `claude_tools.py`, `en.json`
   - Tests: excluded palette never picked over 500 changes; tap plays an excluded palette; gig lock allows exclude (as FX); MIDI action parses; MCP tools; UI tile states

4. **A4 Layer timing.** Four layers: Move FX, Colour FX (drum item rides with it), Palette, Darkness. Together = today. Staggered = a clock per layer (`every_s` | `every_looks` | `on: song|set`, `spread` ±%), each change swaps one layer and runs the quality rules (combo, contrast vs playing, bans, no-repeat) on the whole look. Lock per layer (`autopilot_lock {layer, on}`; `palette_lock` read as palette). Clocks pause between songs.
   - Files: `autopilot.py` (layer clocks, `choose(layer=…)`), `app.py`, `midi/map.py`, `views/autopilot.js` (countdown + lock per layer), MCP `save_autopilot_settings` gains `timing` and `layers` args (YAML text still accepted)
   - Tests: Together bit-identical to v6 decisions for a seeded run; Staggered changes one layer per decision; spread keeps layers apart over 10 min; locked layer never changes; song/set triggers; quality rules applied per single-layer change; palette-only change doesn't move heads or restart the move phase

5. **A3 Darkness Manual / Auto.** Manual = v6. Auto: Min / Max markers on the slider; at each Darkness-layer change the target is Max while the time at Max so far is below `time_at_max`, else Min (a deficit counter, so the share is exact over time); eases with the look's fade. Slider, pedal CC or Claude `set_autopilot {darkness}` in Auto → Manual (shown). Per set: mode, value, min, max, time_at_max.
   - Files: `darkness.py`, `autopilot.py`, `app.py`, `views/autopilot.js` (marker drag, mode switch), `mcp_server.py` / `claude_tools.py` new `set_darkness {mode, min, max, time_at_max}`, `autopilot_status` adds mode and markers
   - Tests: share at Max within 2 % over a simulated hour (Together and Staggered); stays within Min..Max; pedal move → Manual; set change loads that set's values; kick exempt; rulecheck both profiles

6. **A5 Smaller tiles.** Move / Flash / Colour / Palette tiles at 75 %. 12 px text floor and 44 px touch minimum kept (touch tokens win).
   - Files: `style.css`
   - Tests: `test_ui.py` measures tile size desktop vs phone, text ≥ 12 px

7. **A6 Between songs.** Settings on the Autopilot page (saved per rig): on/off, no-activity time, song start (first hit / count-in), count-in hits, fade in / out, ignore inputs (picker over named inputs and kit zones), min song length. Look: generated or a scene from the scene list (also walk-on / walk-off). A scene plays as authored (no Darkness, no layer timing). Badge "Between songs · 12 s since last hit".
   - Files: `autopilot.py` (ignore by `Hit.input`, min_song_s, start mode, scene playback through the app), `app.py`, `views/autopilot.js`, MCP `save_autopilot_settings {between: …}`
   - Tests: ignored input doesn't start or keep a song; gap inside min_song_s ignored; count-in mode ignores a single hit; off = never between; scene look plays as authored (no darkness) and haze untouched; rulecheck both profiles

8. **Docs.** `docs/manual/auto-show.md` (palette bank, layer timing, darkness modes, between songs), CHANGELOG, SCOPE rows, `get_guide` AUTOPILOT section, ⓘ texts.

## Part B: Layout and Fixtures (`v7-b-fixtures`)
1. **B2 Fixtures addresses.** Inline Universe and Address per row with the range (33–48); clash / overlap and live-value check move here from Layout (`patch.js` reused); "Change → Layout" removed. Address map as a collapsible panel.
   - Files: `views/fixtures.js`, `patch.js`, `views/layout.js` (remove address editor), `style.css`, `en.json`, `docs/manual/fixtures.md`, `layout.md`
   - Tests: `test_ui.py`: edit address → range updates, clash flagged, save writes patch; address map panel toggles; Layout has no address inputs
2. **B2 Groups picker.** Groups field becomes the picker (existing groups + "+ New group"). A group left empty is flagged with where it's used (scenes / MIDI), not deleted.
   - Files: `views/fixtures.js`, `web/server.py` (used-by lookup, existing group endpoint)
   - Tests: add / remove group; new group; empty-group warning lists users; store refuses nothing silently
3. **B1 Layout.** Grid shows names only; detail panel a narrow strip (name, type, select / find / test); grid takes the width.
   - Files: `views/layout.js`, `grid.js`, `style.css`
   - Tests: `test_ui.py`/`test_ui_v4.py` updated: grid labels are names; strip width; v4 overlap/fit tests still pass
4. **Docs.** Manual, CHANGELOG, SCOPE row rewrite. MCP: `list_fixtures` gains range and clashes (no new tools).

## Part C: Heads (`v7-c-heads`)
1. **Zone model and rule.** Rig `head_zones` (rect / ellipse in %, name, `black`), scope one head or copy to every head of that type. Rule layer `_position`: after limits, a target inside a zone moves to the nearest edge; `black` zones turn the head's colour off instead. A move path that crosses a zone slides round its edge (per-frame nearest-edge of the interpolated target, so it follows the edge).
   - Files: `rig.py` (parse + validate), `rules.py`, `CLAUDE.md` rule 8 text
   - Tests: `test_head_zones.py`: inside → edge; ellipse edge maths; sweep never enters; black zone = colour 0, dimmer as rule 1; U'King unaffected (rule 7); rulecheck both profiles
2. **Flags.** Points and scene positions inside a zone flagged like out-of-limit points (`rig.point_warnings`, validate_scene).
3. **Heads page.** Draw / move / resize / rename / delete zones on the pad; red hatch; "held at zone edge" indicator from the live feed.
   - Files: `views/heads.js`, `web/server.py`, `web/feed.py`, `style.css`, `en.json`
   - Tests: `test_ui.py` draw and save; feed carries held flag
4. **MCP.** `save_head_zone`, `delete_head_zone`, `list_head_zones`. Docs: `heads.md`, CHANGELOG, SCOPE.

## Part D: Drum flash (`v7-d-drum-flash`)
1. **Gate.** `engine.flash(fixtures, velocity, length_ms, min_level)` (no colour). Rule 2 branch: a flashed light renders its live look (colour, pixels, wheel, gobo, position) at the hit level; heads with a strobe/shutter channel get it open for the hit; lights the scene leaves off stay dark. `_flash_lit` removed (darkness black slots stay black by rendering the look). Exempt kick and MASTER on unchanged (no visible effect).
   - Files: `engine.py`, `rules.py`, `look.py` (drop `show_colour` use for flashes), `midi/router.py`, `midi/map.py`, `kits.py`
   - Tests: MASTER off + chase → hit shows the chase colour at that moment per fixture; scene off on a light → hit shows nothing; head shutter open during hit, closed after; unticked lights dark; MASTER on → frames identical with and without hits; kick never flashed; rulecheck both profiles
2. **Format step.** Flash `colour` removed from MIDI maps and kit zones (6 → 7 step), with tests.
3. **Pickers.** Drum Kit flash target and MIDI page `fixtures` field → tick-box picker.
   - Files: `views/kit.js`, `views/midi.js`
   - Tests: `test_ui.py`
4. **Docs.** `midi-osc.md`, CHANGELOG, SCOPE "Flash colour" row, `get_kit` / `set_kit_piece` take fixtures only. Flash FX bank unchanged (own colour path in `app.flash_fx`).

## Part E: Files and start-up (`v7-e-files`)
1. **E1 Save.** Save beside Open / Save as / New, Ctrl+S (page and desktop window). Setting Auto-save / Manual save: in Manual, store edits land in the working copy and `package.save` runs only on Save; "●" in the title; prompt on Quit (tray), Open and New. Unsaved working copy at next launch is recovered as today.
   - Files: `settings.py`, `package.py` (dirty from content hash), `store.py` / `app.py` (save hook by mode), `desktop.py`, `views/files.js`, `main.js`, `web/server.py`, `en.json`
   - Tests: auto mode writes the .dms per change (as now); manual mode leaves the .dms untouched until Save; dirty flag; Ctrl+S; prompt flow (UI test); Claude edits follow the same setting
2. **E2 Last file on launch.** Launch opens Recent[0]; missing (OneDrive not synced) → message + default show folder.
   - Files: `cli.py`, `desktop.py`, `paths.py`
   - Tests: recent present / missing / empty
3. **E3 Start-up state.** Default: Autopilot on, LOW, MASTER on, haze off, LOW set darkness; Autopilot starts on the first connected DMX output. Setting "Resume last state" keeps today's `showctl.restore()` and rig `startup.master`.
   - Files: `cli.py`, `showctl.py`, `app.py`, `settings.py`, `views/setup.js`
   - Tests: fresh launch state; waits for output; resume mode unchanged from v6 tests; haze off after restart in both modes
4. **Docs.** `getting-started.md`, CHANGELOG, SCOPE rows (Show file, Startup state, Resume after restart).

## Delivery
- `v7`: brief, archive tidy-up, this plan.
- Stacked branches, one per part: `v7-a-autopilot` (from `v7`) → `v7-b-fixtures` → `v7-c-heads` → `v7-d-drum-flash` → `v7-e-files`.
- One PR per part. Part A's PR targets `v5-v6`, so it also carries the `v7` doc commits; retarget it to `main` once #16 merges. Each later PR targets the part before it.
- Before each PR: `ruff check dmx_suite tests installer`, `mypy dmx_suite`, full `pytest` green. No firmware changes planned.
- Each part: small commits with tests, CHANGELOG, `docs/manual/`, MCP tools, `en.json` (no hard-coded strings).

Limits in this environment: no MIDI, DMX or Windows. Pedal / drum input is simulated and the desktop close prompt (pywebview) is tested through its handler only, so A3 pedal feel, D1 shutter timing on the MHL36 and the E1 close prompt need a check on the gig laptop.
