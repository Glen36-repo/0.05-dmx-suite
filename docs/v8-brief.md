# 0.05 DMX Suite — v8 brief (28/11/2026)

Repo: Glen36-repo/0.05-dmx-suite. Saved as `docs/v8-brief.md` on branch `v8` (from `v7`). Builds on v7 — start once v7 Parts A–E are merged (needs the v7 Palette bank, Darkness modes and layer timing).

Scope: Autopilot effects only — palette use, how Darkness looks, and new / variant Colour FX. Plan before writing code (`docs/v8-plan.md`, same style as v7). Rules unchanged: colour only (no dimmer — MASTER owns on/off), never haze, kick light MASTER- and Darkness-exempt, no background glow.

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
- New effects in this brief (4, 5, 7, 8) are `lit_aware` from the start.

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

---

## Bank / UI
- New tiles: Rain, Random fill, Random fill (mixed), Directional sweep, Random flash (mixed), Bounce (mixed), Wave (mixed). Renamed: Directional wave.
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
