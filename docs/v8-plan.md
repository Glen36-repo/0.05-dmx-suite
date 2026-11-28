# v8 build plan (28/11/2026)

Brief: `docs/v8-brief.md`. Base: `v7-e-files` (`1cb277d`, `FORMAT = 7`), **not** merged v7 — this overrides the brief's "start once v7 Parts A–E are merged". v7 PRs #17–#21 are still open (stacked on #16); v8 builds on v7's code as it stands (Palette bank, Darkness modes, layer timing, head zones).
Rules unchanged unless stated below. Every hard rule keeps its tests under both profiles (`tests/rulecheck.py`).

v9 (`docs/v9-brief.md`, calibration / stage space) is planned to run **in parallel**. It needs v8 items 11–15 and 12, so the parts are ordered by what v9 sits on: Part A (format, centrelines, FX settings panel) and Part B (Heads page, Move FX) first, with fixed interfaces (see "v9 interfaces"); the colour-only parts (C–E) after.

## Working on top of open v7 PRs
- **First step (not done on GitHub yet — push blocked 28/11):** `git rebase origin/v7-e-files` on `v8`, then `git rebase --onto v8 <old v8 tip> v9`, push both with `--force-with-lease` (doc-only branches).
- `v8` is rebased onto the tip of `v7-e-files`. When a v7 part changes on review, the v8 stack is rebased onto the new `v7-e-files` (`git rebase --onto`) and tests re-run. v7 never rebases onto v8.
- v8 does not edit v7-only areas (Fixtures address editing, drum flash gate, save / start-up), so v7 review fixes rebase cleanly. Exception: Part B removes the head-limit number fields on Fixtures (item 13) — a small, separate commit so a conflict is easy to redo.
- Part A's PR targets `v7-e-files` until v7 merges, then is retargeted to `main`.
- If v7 adds another format step on review, it stays in 6 → 7; v8's 7 → 8 is unaffected.

## Conflicts with SCOPE.md (brief wins; SCOPE updated in the same commit as the change)
| SCOPE / code today | Brief | Change |
|---|---|---|
| Excluded autopilot types (v4.1, v7): `auto: exclude_fx`, `exclude_palettes` lists | 14: priority 0 = excluded | Lists migrate to `autopilot: fx: {<id>: {priority: 0}}` / `autopilot: palettes: {<id>: {priority: 0}}` (7 → 8). Exclude mode and the panel write priority. `auto: exclude` (lights) unchanged |
| Head limits: number fields on Fixtures (`rig.head_limits`) | 13: edited on the Heads page only | Fixtures fields removed; same `head_limits` data, Heads sliders + MCP `set_head_limits` |
| Flash FX bank: 8 kinds incl. `chase_hit`, `split_hit` | 9: Hit / Hold rows; Chase hit and Rig split hit removed; Blinder hit added | `flashfx.KINDS` changes; mappings using the removed kinds move to `colour_hit` with a load note (7 → 8) |
| Colour FX `sweep` "Directional sweep" (`dir_sweep`) | 6: renamed Directional wave; new fill-style Directional sweep | Bank id `sweep` → `dir_wave`, `sweep_dark` → `dir_wave_dark` (7 → 8). New `dir_fill` item takes the "Directional sweep" label |
| v6 Darkness: non-`lit_aware` effects get `Run`'s static lit pattern (`static_on`) | 2: black moves with the effect | `static_on` gate removed for those effects; black comes from `with_black` on their colours and a black background |
| Centre per effect from the bounding box of its lights (`effects/base.py` `order`, `centre_out` / `out_centre`) | 12: one centre per rig (`layout: centre`) | Centre / side read from the rig; missing = middle of all placed lights (not of the layer's lights) — see decision 5 |
| Rainbow / Lightning / Fire fixed colours | 1: palette | Bank items use the palette versions; originals stay as effect options for hand-built scenes |

## Decisions (28/11/2026, from the brief's assumptions)
1. Open item 1: **Fire follows the palette** (darkest → brightest). The fixed-colour Fire stays an effect option for hand-built scenes.
2. Open item 2: **Twinkle becomes a black-background starfield**.
3. **One format bump 7 → 8, all steps in Part A** (exclude lists → priority 0, `sweep` / `sweep_dark` → `dir_wave` / `dir_wave_dark` in rigs, looks, presets, ratings, MIDI maps, `chase_hit` / `split_hit` → `colour_hit` with a load note). Later parts add no format steps. v9 owns 8 → 9.
4. Priority weight = priority (default 3), applied after quality / contrast / no-repeat / ratings. A variant shares no-repeat with its original (same `of` type).
5. Centrelines: `layout: centre: {x, y}` (grid cells), missing = middle of all placed lights, no format step (brief 12). Goldens: with no `centre`, effects whose layer is the whole rig give identical frames; effects on a subset of lights now use the rig centre — those goldens are regenerated in a separate commit with the change listed.
6. Variants: id `<of>_v<n>` (stable, renameable label), stored under `autopilot: variants:`; MCP `duplicate_fx` / `delete_fx` (new names — `duplicate_item` / `delete_item` stay for scenes).
7. Palette tiles get priority and Exempt-style settings only (no effect params).
8. Point resolution stays in one place (`Palettes.position` / `positions_for`, `palettes.py`), not a new `rig` function — every point lookup already goes through it (`effects/base.py:137`, `ride.py:56`). v9 extends it there.

## Show file format change (7 → 8)
Bump `FORMAT` to 8 in `dmx_suite/versions.py` (Part A). One step per kind, each with a test; golden frames identical before and after for an un-overridden rig.

Rig (`rigs/*.yaml`), rewritten by the step:
```yaml
# format 7
auto:
  exclude_fx: [static, police, sweep]
  exclude_palettes: [ice]

# format 8
autopilot:
  fx:
    static: {priority: 0}
    police: {priority: 0}
    dir_wave: {priority: 0}
  palettes:
    ice: {priority: 0}
```
Rig, additive (no step; defaults when missing):
```yaml
layout:
  centre: {x: 12, y: 6}          # grid cells; missing = middle of all placed lights
autopilot:
  fx:
    fan:                           # only changed values stored
      priority: 4
      darkness: exempt             # follow | exempt | 0-1 (Reduced)
      moods: [mid, high]
      min_s: 20
      max_s: 60
      params: {phase: 0.25, size: 0.8}
  variants:
    fan_v1: {of: fan, name: "Fan slow wide", priority: 3, params: {speed: 0.4, size: 1.0}}
    tour_v1:
      of: point_tour
      name: "Tour: audience sweep"
      params: {points: [audience_l, kit, audience_r], mode: mirrored, order: ping_pong,
               hold_s: 4, travel_s: 1.5, dark_travel: true, stagger_s: 0.1}
```
Looks / presets / ratings: bank id `sweep` → `dir_wave`, `sweep_dark` → `dir_wave_dark`.
MIDI maps and `inputs.yaml` kit zones: `flash_fx {fx: chase_hit | split_hit}` → `{fx: colour_hit}`, logged once in the upgrade note ("Chase hit on pad 3 is now Colour hit").

## v9 interfaces (fixed in Parts A and B; v9 builds on these)
- **Centre**: `rig.layout_centre() -> (x, y)` (grid cells, auto when unset); `get_layout` / `set_layout` carry `centre`.
- **Overrides schema**: `autopilot: fx:` / `variants:` as above; params validated against the effect's `Param` list, so v9's new Move FX params (`space`, `plane`, `size_m` …) only need adding to the `Param` list — the panel and MCP pick them up.
- **Aim**: every Move FX (old and new) writes pan / tilt through one call, `Run.aim(un, pan, tilt)` in `effects/base.py` (today 24 direct `fl.pan` / `fl.tilt` writes). v9 adds a stage-space branch there.
- **Points**: every point lookup goes through `Palettes.position` / `positions_for` (decision 8). v9 adds stage points there. Note: `rig.Point.stage` already exists (rough place labels: left / centre / right) — v9's metre coordinates need a different key.
- **Limits / zones**: still applied last in `rules._position` (rule 8). Heads page pad layers (bottom → top): out-of-limits shading, zones, point crosshairs, live dot — v9 adds its views as further layers.

## Part A: Foundation (`v8-a-foundation`) — v9 depends on this
1. **Format 8.** `versions.py` FORMAT 8; steps for rig, look, presets, ratings, midi, inputs (above).
   - Files: `dmx_suite/versions.py`, `classify.py` (stop reading `exclude_fx` / `exclude_palettes` after upgrade), `tests/data/` (v7 sample)
   - Tests: `test_v8_migration.py`: each kind upgrades and backs up; excluded FX / palette → priority 0 and never picked; `sweep` look plays as `dir_wave`; chase-hit pad fires Colour hit with one note; newer format refused; goldens identical
2. **Item 12 centrelines.** `rig.py` / `layout.py` parse `layout.centre` and give `layout_centre()`. `effects/base.py` `order` (`centre_out` / `out_centre`) and side splits (Split, Mirror sweep, Fan, Crossfire, left-vs-right looks) read the rig centre; lights on the line count as centre. Layout page: dashed lines, drag / type / snap / "Reset to middle"; live-view toggle.
   - Files: `rig.py`, `layout.py`, `effects/base.py`, `effects/ride.py`, `effects/more.py`, `views/layout.js`, `grid.js`, `views/live.js`, `web/server.py`, `mcp_server.py` / `claude_tools.py` (`get_layout` / `set_layout` `centre`), `en.json`
   - Tests: no `centre` + whole-rig layer → frames identical; centre moved → `centre_out` order changes; on-line light lit first; round trip; Playwright drag / type / reset
3. **Item 14 FX settings panel.** Overrides merged into the bank `Item` (`fxbanks.py`); variants as extra items (`of` kept for no-repeat). Autopilot pick weight = priority (`autopilot.py`), priority 0 = excluded (`classify.py`). Darkness Follow / Exempt / Reduced per item (`darkness.py` hook in the look's lit value). Panel generated from the effect's `Param` list (reuse the scene-editor param form): Darkness, params, moods, priority, min / max time, Preview 10 s, Reset, Duplicate, Delete (variants only). Badge tap cycles 1 → 5 → 1 (32 px target); Exclude mode writes 0 and restores the old value; dot on tiles with overrides; gig lock read-only (Preview off while a show runs).
   - Files: `rig.py`, `fxbanks.py`, `autopilot.py`, `classify.py`, `darkness.py`, `app.py`, `views/autopilot.js`, `style.css`, `en.json`, `web/server.py`, `mcp_server.py` / `claude_tools.py` (`get_item` / `save_item` `overrides`, new `duplicate_fx` / `delete_fx`)
   - Tests: no overrides → goldens identical; priority 5 vs 1 ≈ 5× over 5000 seeded picks (±15 %); priority 0 never picked, still plays on tap; variant and original never back to back; Exempt ignores Darkness, Reduced 50 % = half; only changed values saved; original can't be deleted; gig lock refuses writes; MCP round trip; Playwright panel / badge cycle / Exclude-mode restore
4. **Docs.** CHANGELOG, `docs/manual/auto-show.md` (panel, priority, variants), `layout.md` (centrelines), SCOPE rows, `get_guide` AUTOPILOT, ⓘ texts.

## Part B: Heads and Move FX (`v8-b-heads-move`) — v9 depends on this
1. **`Run.aim`.** All existing Move FX (`ride.py` Move, `classic.py` RandomMove, `more.py`) write through `Run.aim(un, pan, tilt)`. Refactor only.
   - Tests: goldens identical for every existing Move FX on both profiles
2. **Item 13 Heads page.** Pads full width (one per row narrow, side by side wide, ≥ 2× today), fine mode kept. Pan / tilt range sliders with min / max arrows (% and degrees) writing `head_limits`; outside shaded, drag clamped (rule 8); click / drag an arrow → head goes to that limit; arrow keys nudge (Shift fine). Crosshairs for saved points: click = go, drag = move + save (undo), red when out of limits / in a v7 zone, "*" points ask this head / all heads. Pad layers per v9 interfaces. Gig lock view-only (crosshair click still moves unless the show runs). Fixtures head-limit fields removed (own commit).
   - Files: `views/heads.js`, `views/fixtures.js`, `style.css`, `en.json`, `web/server.py`, `web/feed.py`, `mcp_server.py` / `claude_tools.py` (`set_head_limits`)
   - Tests: limits clamp on the pad and at output; slider writes `head_limits`; arrow click sends the head to the limit; crosshair drag saves + undo; "*" prompt; Playwright on desktop and phone sizes
3. **Item 11 Move FX.** Fly-out, Converge / split, Beat stabs, Pendulum, Spiral, Square / triangle / star, Lissajous search, Tilt nod, Sky scan, Contrast. Points through `Palettes.positions_for` with defaults when missing; beat ones on `tempo.py` (e-drum tempo, else tap / set). U'Kings untouched (colour only).
   - Files: new `effects/move.py`, `fxbanks.py` (busy / speed / moods / needs), `quality.py`, `en.json`, manual + ⓘ
4. **Item 15 Position / Point tour.** Position: one point or a point per head, optional drift. Point tour: ordered list, order (in order / ping-pong / random no repeat), hold (s or beats), travel (s, eased), dark while travelling (colour black, rule 1), modes Together / Offset / Mirrored (vertical centreline; `*_l` / `*_r` or paired; falls back to Together) / Per head, stagger; any number of heads, groups. Missing point skipped with a warning; none left → tile greyed (needs).
   - Files: `effects/move.py`, `fxbanks.py`, `rig.py` (point pairs), `views/autopilot.js` (point list editor in the panel)
   - Tests (3 and 4): every Move FX 60 s inside limits and v7 zones, both profiles; Point tour orders / modes / stagger / dark travel; Mirrored falls back without a pair; 1-, 3- and 4-head rigs; missing points skipped / tile greyed; U'Kings frames unchanged
5. **Docs.** `heads.md`, `auto-show.md` (Move FX), CHANGELOG, SCOPE rows (head limits), CLAUDE.md nothing (rule 8 unchanged).

## Part C: Palette and Darkness (`v8-c-palette-darkness`)
1. **Items 1, 3.** Rainbow (palette hue blend), Lightning (palette colour per burst), Fire (palette darkest → brightest) as bank items; originals kept as effect options. Twinkle: black background, palette colour per point.
2. **Item 2.** Remove the `static_on` gate for non-`lit_aware` effects (`effects/base.py:283`, `:355`; `scenes.py:380`, `:417`); those effects get `with_black` on their colour lists and a black background when darkness > 0. The 8 `lit_aware` effects and Random flash unchanged.
   - Files: `effects/base.py`, `scenes.py`, `effects/classic.py`, `more.py`, `matrix.py`, `fxbanks.py`, `look.py`
   - Tests: bank-wide "colours come from `$palette` / `$colour` / `$colour2`" (fails on a hard-coded bank colour); at 50 % darkness on every changed effect: every unit lit within one cycle, none black > ~2 cycles, black share 50 ± 15 %; `lit_aware` effects and Random flash frames unchanged; kick exempt; rulecheck both profiles
3. **Docs.** `auto-show.md` (Darkness), CHANGELOG, SCOPE row.

## Part D: New Colour FX (`v8-d-colour-fx`)
1. **Items 4–8, 10.** Rain, Random fill (+ mixed), Directional wave label (id migrated in A), Directional sweep fill-style (`dir_fill`), Random flash / Bounce / Wave (mixed), Ripple, Stack, Sparkle dark, Theatre chase, Collide ×2, Collide blend ×2 (additive mix scaled to the brightest channel, W / A included — `colourmix.py`), Glitter, Aurora, Candle, Alternate. All `lit_aware`, palette-driven, centreline-aware; busy / speed / moods / needs set; one-colour palette → Autopilot skips the mixed tiles.
   - Files: new `effects/v8.py` (or `matrix.py` / `more.py`), `fxbanks.py`, `quality.py`, `colourmix.py`, `en.json`, manual + ⓘ
   - Tests per effect: palette colours only; Darkness behaviour; bar orientation for Rain / Stack / Collide vertical from layout rotation; blend maths (R+B → magenta, B+G → cyan, R+G → yellow, W / A); mixed never repeats a neighbour / previous colour; seeded goldens; rulecheck both profiles
2. **Docs.** `auto-show.md`, CHANGELOG, `list_fx` text.

## Part E: Flash Hit / Hold (`v8-e-flash`)
1. **Item 9.** `flashfx.py` split Hit (one-shot: Colour hit, Flash and decay, Blinder hit) / Hold (press → release: Blinder, Strobe, Blackout, Freeze); `chase_hit` / `split_hit` removed (mapping migration in A). MIDI / pedal mapping follows the type (`midi/map.py`, `midi/router.py`); two bank rows (`views/autopilot.js`).
   - Tests: Hit plays through on a short press and ignores hold; Hold stops on release; Blackout keeps haze; kick exempt; migrated mappings fire Colour hit; rulecheck both profiles
2. **Docs.** `midi-osc.md`, `auto-show.md`, CHANGELOG, SCOPE Flash FX row.

## Parallel with v9
- v9 branches from `v8-b-heads-move` once Part B is pushed (not merged). It can start earlier from `v8-a-foundation` with pure logic (`stagegeo.py` solver, stage frame, `calibration:` rig block, room-zone geometry — no UI).
- Parts C–E don't touch Heads, points, rules or Move FX. Shared files only: `en.json`, `CHANGELOG.md`, `SCOPE.md`, `mcp_server.py`, `claude_tools.py`, `fxbanks.py` (bank list). Rule: v9 rebases onto the latest v8 part before each v9 PR; v8 never rebases onto v9.
- Format: v8 = 8 (frozen after Part A), v9 = 9.
- Stack: `v7-e-files` → `v8` → `v8-a-foundation` → … → `v8-e-flash`; `v9` → `v9-*` from `v8-b-heads-move`. A v7 change ripples down by rebase only.
- Merge order: #16 → v7 A–E → v8 A–E → v9.

## Delivery
- `v8`: brief, this plan.
- Stacked branches, one per part: `v8-a-foundation` (from `v8`) → `v8-b-heads-move` → `v8-c-palette-darkness` → `v8-d-colour-fx` → `v8-e-flash`.
- One PR per part. Part A targets `v7-e-files` (retargeted to `main` when v7 merges); each later PR targets the part before it.
- Before each PR: `ruff check dmx_suite tests installer`, `mypy dmx_suite`, full `pytest` (incl. Playwright) green, `tests/rulecheck.py` both profiles, CI on ubuntu + windows.
- Each part: small commits with tests, CHANGELOG, `docs/manual/`, SCOPE rows, `get_guide`, MCP tools, `en.json` (no hard-coded strings).

## Acceptance (on the rig, gig laptop)
Brief list (Fire palette on Rainbow / Lightning / Fire; 50 % Darkness on Wave / Comet / Sparkle; Rain direction on the LCB803 bars; Random fill (mixed) patchwork), plus: Heads slider arrow → head goes to the limit; Point tour on both MHL36 (Together / Mirrored, dark travel); centreline moved → Chase in / out and Split follow it.

Limits in this environment: no MIDI, DMX or Windows. Pedal Hold timing, head movement and how the new effects read on the bars need the gig laptop.
