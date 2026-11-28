# 0.05 DMX Suite — v8 brief (28/11/2026)

Repo: Glen36-repo/0.05-dmx-suite. Saved as `docs/v8-brief.md` on branch `v8` (from `v7`). Builds on v7 — start once v7 Parts A–E are merged (needs the v7 Palette bank, Darkness modes and layer timing).

Scope: Autopilot effects only — palette use, how Darkness looks, new / variant Colour FX, new Move FX, and the Flash FX Hit / Hold split (items 9–11 added 28/11 after the simulator review), plus adjustable stage centrelines (item 12), the Heads page rework (item 13) and per-FX settings, variants and priority on long-press (item 14) and point-based Move FX (item 15). Plan before writing code (`docs/v8-plan.md`, same style as v7). Rules unchanged: colour only (no dimmer — MASTER owns on/off), never haze, kick light MASTER- and Darkness-exempt, no background glow.

Background (from the code, 28/11):
- Colour FX that ignore the palette: `rainbow` (full hue wheel), `lightning` (hard-coded white), `fire` (fixed fire colours).
- Only 8 effects are `lit_aware` (shape their own black under Darkness): ColourChase, LinearWave, Gradient, Rainbow, Palette (static), ColourFade, Split, DirSweep. All others get `Run`'s **static** lit pattern (`static_on`) — the same lights / bar segments stay black for the whole look. That's the "some segments just off" look on Wave etc.

---

## 1. Every Colour FX takes the palette
- **Rainbow**: cycles round the palette's colours (smooth hue blend between them) instead of the full wheel; spread and saturation still apply.
- **Lightning**: bursts in palette colours (random per burst) instead of white.
- **Fire**: flickers between the palette's colours, darkest to brightest (confirm — open item 1).
- Hand-built scenes keep the original full-wheel / white / fire variants as effect options; the Autopilot bank uses the palette versions.
- Test: every Colour FX in the bank resolves its colours from `$palette` / `$colour` / `$colour2` — fails if a future bank entry hard-codes colours.

## 2. Darkness — keep the good ones, black into the palette for the rest
- **Unchanged**: the 8 `lit_aware` effects above, plus Random flash (looks right already).
- **All others**: remove the static `static_on` pattern. Darkness instead adds black entries to the colours the effect draws from (`with_black`, already used by the chases) — more darkness, more black. A unit is black when the effect *lands* on black, so black moves with the effect.
- **Colour + background effects** (Wave, Comet, Bounce, Fill, Sparkle, Twinkle, Bars, Radial …): background forced to black when darkness > 0; the lit colour cycles through palette-with-black.
- Pixel bars: never a few random dead segments mid-bar.
- Tests at 50 % darkness: every light / segment is lit at some point within one effect cycle; no unit stays black longer than ~2 cycles; measured black share ≈ darkness (±15 %).
- New effects in this brief (4, 5, 7, 8, 10) are `lit_aware` from the start.

## 3. Twinkle — make it readable
- Today: each unit (light or segment) picks at random each ~3 s cycle (density 0.3) whether to fade in / out of `$colour` over `$colour2`. With two similar palette colours it barely reads.
- Change: background black (not `$colour2`), so it's a starfield of palette-coloured points fading in and out; colour per point from the palette. Open item 2: or leave as is and exclude from Autopilot by default.

## 4. New effect: Rain
- Drops start at random on the pixel bars and run along them with a fading tail (Comet-like, many at once, random).
- Settings: drop rate (drops / s), speed (± random per drop), tail length, direction down / up — taken from the bar's orientation in the stage layout so "down" is physically down.
- Colour: drop head = brightest palette colour, tail fades through the palette.
- Non-bar lights (pars, StarColor): drops fall across the stage top → bottom by layout height; each light flicks as a drop passes.
- Darkness: fewer drops, shorter tails.
- Moods: LOW / MID slow drop rate, HIGH downpour.

## 5. New effects: Random fill and Random fill (mixed)
- Like Fill / unfill, but units pop on one at a time in random order (pop like Random flash) until all lit, then off in a new random order until black; repeat.
- Scope option: bar segments (default) / whole lights / per bar (each bar fills on its own).
- Settings: fill time (empty → full), hold full, hold empty, pop style (instant / quick fade-in), unfill (random order / all at once — hard cut).
- **Random fill**: one palette colour per fill cycle, next colour next cycle.
- **Random fill (mixed)**: each unit that pops takes a random palette colour, never the same as its neighbour — fills as a patchwork; re-rolled each fill.
- Darkness: shorter time at full, longer near empty.
- Option: with e-drum tempo, one pop per hit / per beat.

## 6. Rename: Directional sweep → Directional wave
- Same behaviour, new label. Bank id `sweep` → `dir_wave`; format upgrade (show file 7 → 8, or v7's bump if not yet released) maps the old id in saved looks, presets, ratings and Autopilot exclude lists — nothing breaks.

## 7. New effect: Directional sweep (fill-style)
- Same directions as Directional wave: L→R, R→L, centre→out, out→centre, up, down (stage layout).
- Leading edge sweeps across and **everything behind it stays lit** in the colour (like Fill / unfill).
- Cycle: sweep on → hold → clear. Clear: wipe through (same direction) / sweep back / all at once.
- Each sweep takes the next palette colour, so a new colour wipes over the old one (no black between). Under Darkness black is one of the sweep colours.
- Settings: sweep time, hold, edge (hard / soft gradient), clear mode.

## 8. "Mixed" variants — new palette colour every pulse
Own tile each, alongside the original (separately excludable):
- **Random flash (mixed)**: each flash a random palette colour, never the previous colour on that light.
- **Bounce (mixed)**: block takes the next palette colour each time it hits an end and turns.
- **Wave (mixed)**: each crest a different palette colour — a train of coloured waves.
- (Random fill (mixed) is in item 5.)
- One-colour palette → mixed = original; Autopilot skips the mixed tile then (no duplicate looks).
- Darkness: black is one of the colours a pulse can land on (item 2).

## 9. Flash FX — split into Hit and Hold
- **Hit** (one-shot: a press plays it through to the end; holding changes nothing): Colour hit (palette colour, fades out), Flash and decay (white hit, fades out), Blinder hit (full white, one short burst).
- **Hold** (runs while the button / pedal is held, stops on release): Blinder, Strobe (at the set rate), Blackout (haze keeps running), Freeze (holds the current look).
- Bank shows two rows (Hit / Hold), each tile marked. MIDI / pedal mappings follow the type: Hit fires on press, Hold runs press → release.
- **Remove** Chase hit and Rig split hit. Mappings that use them are flagged on load and moved to Colour hit (nothing silently stops working).
- Rules unchanged: colour only, never haze, never the MASTER-exempt kick light.

## 10. New Colour FX (picked from the simulator, 28/11)
Simulator: https://claude.ai/artifact/HG5LxQtkx5nqQMBBNyaTcv — reference for look and timing. All take the palette (item 1) and are `lit_aware` (item 2).
- **Ripple**: a ring of colour spreads from a random spot on the stage layout and fades; new spots keep coming (Radial always starts at centre). Settings: rate, ring speed, ring width.
- **Stack**: segments drop down each bar one at a time (gravity) and pile up at the bottom until full, hold, clear; each drop the next palette colour; bars offset so they don't stack in sync. Non-bar lights fill bottom-up with the stack by layout height.
- **Sparkle dark** (inverse sparkle): all lit in the palette, random units blink off briefly. Darkness = more / longer blink-offs.
- **Theatre chase**: marquee — one on, two off — crawling along the rig (layout order) in palette colours; on the beat.
- **Collide — vertical**: two palette colours run in from the top and bottom of each bar, meet in the middle, pull back. Non-bar lights by layout height (top vs bottom).
- **Collide — horizontal**: two palette colours run in from the left and right of the rig (layout x, across all lights and bars), meet at centre stage, pull back. Own tile each. Hard meet, no mixing.
- **Collide blend — vertical / horizontal** (two more tiles): the two colours keep travelling *through* each other; where they overlap the lights show the colour the two make **as light** — add the two colours, then scale so the brightest channel is full (red + blue → magenta, blue + green → cyan, red + green → yellow; W / A channels mixed the same way). Soft edges bleed into the mix; the overlap grows until the whole bar (vertical) or rig (horizontal) is the mixed colour, holds briefly, then they pull back apart. Next pair of palette colours each cycle.
- **Glitter**: slow-drifting palette base with quick white sparkles on top.
- **Aurora / Ocean**: slow overlapping curtains of palette colour drifting across the rig — LOW, acoustic, opera.
- **Candle**: gentle independent flicker per light in palette colours (Warm / White) — opera, acoustic.
- **Alternate**: odd / even lights swap between two palette colours on the beat; pair moves on every 8 beats.
- Not taken: Fireworks, Bouncing balls, Heartbeat.

## 11. New Move FX (MHL36; U'Kings stay colour only)
All respect head limits and v7 exclusion zones; positions from the rig's saved head points (kit, singer, audience L/R, stage L/R) with sensible defaults if a point is missing.
- **Fly-out**: both heads start on the kit, sweep out to the audience (one left, one right), hold, come back.
- **Converge / split**: heads meet on one point (kit, then singer, alternating), hold, split to the sides, hold.
- **Beat stabs**: jump to a new saved point every beat (or snare hit) — quick move, short hold.
- **Pendulum**: pan swings like a pendulum, beam traces an arc rising at each end, fastest through the middle; heads mirrored.
- **Spiral**: circle that grows from centre to full size and shrinks back.
- **Square / triangle / star**: traces a shape with sharp corners (shape setting; Autopilot may rotate between them).
- **Lissajous search**: slow wandering path that never quite repeats — opera / between songs.
- **Tilt nod**: small quick tilt dips on the beat while pan drifts slowly.
- **Sky scan**: heads tilt up into the ceiling and sweep wide across it, crossing — for builds.
- **Contrast**: one head runs a circle while the other runs a figure 8 at a different speed.
- Beat-based ones (Theatre chase, Alternate, Beat stabs, Tilt nod) use the v6 e-drum tempo, else tap / set tempo.

## 12. Stage centrelines on the Layout page
- Today: "centre" is worked out per effect from the bounding box of whichever lights that layer runs on (`effects/base.py`, `centre_out` / `out_centre`: `cx, cy = (min + max) / 2`), and in order mapping from the middle index. So the centre moves depending on which lights an effect uses, and can't be set to where the band actually stands.
- Change: two adjustable lines on the Layout stage grid, saved per rig:
  - **Vertical centreline** (stage centre, left / right split) — default: middle of all placed lights.
  - **Horizontal centreline** (top / bottom split) — default: middle of all placed lights.
  - Drag on the grid or type a value; snap to the grid; "Reset to middle" button. Shown as dashed lines on Layout and on the live stage view (toggle).
- Everything that uses a centre or a side reads these lines instead of its own bounding box:
  - Directions `centre_out` / `out_centre` (chases, Chase in / out, Directional wave, Directional sweep), Radial, Split (sides), Collide horizontal (meets at the vertical line) and vertical (non-bar lights split by the horizontal line), Ripple / Stack where they use "centre" or "bottom".
  - Left / right for mirrored effects and Autopilot left-vs-right looks (Split, Mirror sweep, Fan, Crossfire, Fly-out audience L / R, Converge / split sides).
  - Pixel bars keep their own top / bottom for along-bar effects (Stack, Rain, Collide vertical on the bar itself) — the horizontal line is only for effects that work across the whole rig.
- Lights exactly on a line count as centre (both sides / lit first in centre-out).
- MCP / API: `get_layout` / `set_layout` include `centre: {x, y}`.
- Rig file: `layout: centre: {x, y}` (grid cells); missing = auto middle, no warning; no format bump needed.

## 13. Heads page — bigger pads, limit sliders, points on the pad
- Today: each head's drag pad is a small 2:1 box; pan / tilt limits are number fields on the Fixtures page (`rig.head_limits`); saved head points are a list, not shown on the pad.
- **Bigger pads**: each head's pad uses the full page width (one head per row on narrow screens, side by side on wide), at least double the current size. Fine mode stays.
- **Limit sliders under each pad** — two range sliders, each with two draggable arrows (min / max):
  - **Pan (horizontal)** under the pad, **Tilt (vertical)** beside or under it, labelled in % and degrees (from the fixture's pan / tilt range).
  - The pad shades the area outside the limits; the head can't be dragged into it (same clamp as output, rule 8).
  - **Click / drag an arrow → the head moves to that limit** (the arrow's axis at the limit, other axis where it is), so you can see exactly where the edge lands in the room and fine-tune it. Arrow keys nudge the selected arrow (fine step with Shift).
  - Saved to the rig's `head_limits` (same data as today); the Fixtures page number fields go (one place to edit limits — Heads).
- **Saved points as crosshairs on the pad**:
  - Every head point for that head shows as a labelled crosshair at its pan / tilt.
  - **Click a crosshair → the head goes there** (for checking / refocusing at load-in); drag it to move the point, release to save (undo available). Arrow keys nudge the selected crosshair.
  - Crosshairs outside the limits or inside a v7 exclusion zone show in red (flagged, as now).
  - Points that apply to all heads ("*") show on every pad; editing one asks "this head only / all heads".
  - The existing points list, description / tags / stage place, Focus mode and re-focus walk stay.
- Layers on the pad, bottom to top: out-of-limits shading, v7 exclusion zones, point crosshairs, live head dot.
- Disabled under gig lock (view only; clicking a crosshair still moves the head unless the show is running).
- MCP: `save_point` / `list_points` unchanged; `set_head_limits {fixture, pan: [lo, hi], tilt: [lo, hi]}`.

## 14. FX settings panel — long-press a tile; variants and priority
- Today: long-press (600 ms) on an FX tile toggles Exclude; the only per-look controls are the global Ride faders (speed, fade, fan, size, shift). No per-effect settings in the Autopilot bank.
- Change: **long-press (or right-click) a tile → settings panel for that FX** (Move, Colour, Flash, Drum, Palette tiles). Exclude moves into the panel (as priority 0, below); the **Exclude mode** button stays for quick tap-to-exclude.
- Panel contents:
  - **Darkness**: Follow (default) / Exempt (this FX always plays fully lit, Darkness ignored) / Reduced (slider: how much of the Darkness value applies, 0–100 %). For effects that look wrong with black added, or ones that should stay bright (e.g. Static palette, Candle).
  - **The effect's own parameters**, generated from its `Param` list (same as the scene editor), e.g. Colour FX: period, spread, density, tail, direction, groups; Move FX: **phase / spread between heads**, size, speed, centre point, mirror on / off. Fan in / out: phase offset between heads, fan width, in/out timing.
  - **Autopilot**: moods it can run in (LOW / MID / HIGH ticks), **priority 0–5**, min / max time on screen.
    - Priority = pick weight: still random, but a 5 comes up about 5× as often as a 1 (weight = priority; default 3). Applied on top of the existing quality / contrast / no-repeat rules and look ratings. Shown on the tile as a small 0–5 badge. Same setting on Palette tiles.
    - **Tap the badge to change it** without opening the panel: each tap steps 1 → 2 → 3 → 4 → 5 → 1 (doesn't go to 0 — excluding stays a deliberate action via Exclude mode or the panel). Tapping the tile anywhere else still plays it. The badge is its own touch target (min 32 px, within the v7 smaller tiles) so it can't be hit by accident when playing a tile. Saved straight away; disabled under gig lock.
    - **Priority 0 = excluded.** Exclude and priority are one setting: excluding a tile (Exclude mode tap, or the switch) sets it to 0 and shows it red; un-excluding restores the priority it had before (default 3); setting priority to 0 excludes it. Existing exclude lists migrate to priority 0.
  - **Preview** button (plays it now on the rig, 10 s, like the Ride page preview) and **Reset to defaults**.
- **Duplicate (variants)**: the panel has **Duplicate** — makes a copy of the FX as its own tile ("Fan in / out 2", renameable) with its own parameters, darkness, moods and priority (0 = excluded). Variants sit next to their original in the bank, are picked by Autopilot as separate types (so e.g. a slow wide Fan and a fast tight Fan can both run), can be previewed, mapped to MIDI and deleted (originals can't be deleted, only excluded). No-repeat treats a variant and its original as the same type so they don't play back to back.
- Values saved per rig as overrides on the bank item (only changed values stored); a tile with overrides shows a small dot. Autopilot looks, presets and the Ride page use the overridden values. Ride faders still scale on top (speed × item speed etc.).
- Under gig lock: panel opens read-only (Preview disabled while a show is running).
- MCP / API: `get_item` / `save_item` take `overrides: {darkness: follow|exempt|<0-1>, params: {...}, moods, priority: 0-5, min_s, max_s}`; `duplicate_item {id, name}` / `delete_item {id}` for variants (`duplicate_item` / `delete_item` already exist for scenes — extend or add `*_fx` versions).
- Rig file: `autopilot: fx: {<id>: {...overrides}}` and `autopilot: variants: {<new_id>: {of: <id>, name, ...overrides}}`; missing = defaults.

## 15. Move FX — Position and Point tour (saved points, any number of heads)
- Today: `kit` (Centre / kit) is the only point-based tile (Move `point` pattern at one point); `random_points` jumps to random spots inside the limits, not to saved points.
- Two new Move FX tiles, set up in the item 14 settings panel; use **Duplicate** (item 14) to keep several versions (e.g. "Position: singer", "Tour: audience sweep"). Both use the rig's saved head points (item 13 crosshairs) and respect head limits and v7 exclusion zones.
- **Position** (hold on preset locations):
  - Pick a point for the heads: **one point for all heads**, or **a point per head** (list of the rig's moving heads, a point dropdown each — "mh_a → singer, mh_b → kit").
  - Optional **drift**: small slow movement around the point (size, speed; 0 = dead still).
  - Use: static looks, e.g. ~30 s aimed at the drum kit.
- **Point tour** (move between several locations):
  - An ordered list of points (add / remove / drag to reorder, from the saved points); **order**: in order / ping-pong / random (no immediate repeat).
  - **Hold** at each point (s, or beats with e-drum tempo) and **travel time** between points (s; ease in/out).
  - **Dark while travelling** (on / off): head colour goes black for the move and comes back on arrival — heads travelling between positions with lights off.
  - **Multiple heads** — mode:
    - **Together**: all heads go to the same point at the same time.
    - **Offset**: same list, each head N steps behind the previous one (so they're never on the same point).
    - **Mirrored**: each point's left / right partner for the other side (uses the item 12 vertical centreline; points named `*_l` / `*_r` or flagged as a pair; falls back to Together if a point has no partner).
    - **Per head**: each head has its own list.
  - Head stagger (s) so heads don't all start moving on the same frame (default 0).
- Both work for any number of moving heads in the rig (not just mh_a / mh_b), and on a group (e.g. "front heads" only — others keep the other Move FX or hold).
- A point missing from the current rig (other venue) is skipped with a warning; if none are left, the tile can't run on this rig (greyed, like other needs).
- MCP / API: params via `save_item` overrides (`points`, `mode`, `order`, `hold_s` / `hold_beats`, `travel_s`, `dark_travel`, `per_head`, `stagger_s`, `drift`).

---

## Bank / UI
- New tiles: Rain, Random fill, Random fill (mixed), Directional sweep, Random flash (mixed), Bounce (mixed), Wave (mixed), Ripple, Stack, Sparkle dark, Theatre chase, Collide (vertical), Collide (horizontal), Collide blend (vertical), Collide blend (horizontal), Glitter, Aurora / Ocean, Candle, Alternate; Move: Fly-out, Converge / split, Beat stabs, Pendulum, Spiral, Square / triangle / star, Lissajous search, Tilt nod, Sky scan, Contrast, Position, Point tour. Renamed: Directional wave. Flash bank: Hit / Hold rows.
- Each new effect: busy score, speed class, moods, needs (`pixels` / `layout`) set like existing items; quality rules and contrast checks apply; manual page + ⓘ text.
- MCP / API: new effects listed by `list_fx`, usable in `save_item` / `preview_look`.

## Acceptance (on the rig)
- Palette Fire → Rainbow, Lightning, Fire all in fire colours.
- Darkness 50 % on Wave, Comet, Sparkle: no segment stuck off; black moves with the effect.
- Rain reads as falling on the LCB803 bars mounted as they are on stage.
- Random fill (mixed) ends a fill as a full multi-colour patchwork.

## Open items
1. Fire: follow the palette (assumed) or keep fixed fire colours.
2. Twinkle: black background starfield (assumed) or leave and exclude from Autopilot.
