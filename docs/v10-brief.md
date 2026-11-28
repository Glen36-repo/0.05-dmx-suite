# 0.05 DMX Suite — v10 brief (28/11/2026)

Repo: Glen36-repo/0.05-dmx-suite. Saved as `docs/v10-brief.md` on branch `v10` (from `v9`). Builds on v9 — start once v9 is merged.

Scope: **intensity curves** — make the simulator show what the lights actually do, let fades look even on the real rig, and make Autopilot darkness work in perceived brightness. Plan before writing code (`docs/v10-plan.md`, same style as v7–v9). Rules unchanged (colour only, never haze, MASTER owns on/off, head limits always enforced at output — rule 8, no background glow: lights not in an effect are fully off).

Background (28/11):
- On the rig, fades and dull parts look much brighter on the real lights than in the simulator.
- Likely cause: the simulator paints the DMX value straight to screen as an sRGB colour. Screens are non-linear (light ≈ value^2.2, sRGB) while PWM LED fixtures are close to linear, so 50 % DMX shows as ~22 % light on screen vs ~50 % on the fixture; 25 % → ~5 % vs 25 %; 10 % → ~0.6 % vs 10 %.
- The eye is non-linear too (square law: perceived ≈ √light), so on the real rig linear fades sit bright for most of their travel and drop off fast near black ("dead travel" at the top).
- Not yet confirmed in code: how the simulator maps DMX to screen colour. **Plan step 1 — read and report this before changing anything.**

---

## 1. Intensity pipeline (one place, documented)
- Define the chain once and use it everywhere (output, simulator, Stage view, Heads page swatches):
  `engine level (0–1) → darkness / effects / colour mix → output curve → DMX (8 or 16-bit) → [fixture's own light curve] → light`
- The output curve is applied **once**, at output, after Autopilot darkness, fades, effects and colour mixing, before head limits and the DMX frame. Nothing upstream applies its own curve.
- RGB(W/A) colour: the curve scales all colour channels of a fixture together so hue is kept (no hue shift through a fade).
- Drum flash / MASTER-off strobe: flash levels go through the same curve (full = full, so no change at 100 %).

## 2. Fixture light curve (what the fixture does)
- New per fixture **type** setting in `fixtures.py`: `light_curve: linear | square | s_curve | custom` (custom = up to 11 points, 0–100 %). Default **linear** for LED types.
- Used by the simulator to show real light output; not sent to the fixture.
- Fixtures with their own selectable curve (menu or channel): note it in the type (`fixture_curve_mode`) so the type's `light_curve` matches the menu setting. Check the MHL36, LCB803, SlimPar 35, StarColor 72 and U'King menus / manuals.

## 3. Output curve (what the software sends)
- Per fixture type, with a per-rig override: **Linear (default)** / Square law / Log / S-curve / Custom.
- Default Linear everywhere so v9 shows output exactly as before.
- Square law = DMX = level² (on a linear LED gives an even-looking fade).
- Settings: Rig page → fixture type row → Output curve dropdown with a small curve graph.

## 4. Low-end resolution
- Where a fixture has fine (16-bit) dimmer or colour channels, use them for curved output.
- 8-bit only + non-linear curve: warn on the Rig page (few steps near black, fades may step).
- **Minimum on** per fixture type (default 0): any computed level below it outputs 0 — a fade goes to true black rather than flickering at 1–2 DMX. Respects the no-background-glow rule.

## 5. Simulator display correction
- Simulator and every on-screen fixture swatch: DMX → fixture light curve (item 2) → linear light → sRGB encode (proper sRGB OETF, not raw DMX) → draw.
- **Glow**: lit fixtures get a soft bloom proportional to light output, so a dim light in a dark room reads as lit.
- **Dark room** background option (near-black stage) — default on.
- **Display gain** slider (−1 to +1 stop) on the simulator page for different screens / ambient light; saved per laptop, not in the rig.

## 6. Match wizard (fit the display to the real lights)
- Rig page → fixture type → **Match**. Show stopped, not under gig lock.
- One fixture of that type to white (or a chosen colour) at 10 / 25 / 50 / 75 %, all others off.
- At each step, adjust a slider until the on-screen swatch matches the real light; **Next**.
- Fits the type's `light_curve` (custom points) and saves it to the type. Undo = previous curve kept as a backup.

## 7. Perceived darkness (Autopilot)
- Autopilot **Darkness** and the light / dark slider (v6 / v7 Manual and Auto modes) now work in **perceived brightness**: slider at 50 % looks half as bright, not half the light.
- Darkness still puts black into the effects (patchy, not a dimmer). The amount of black is chosen so the scene's mean light output = perceived² (square law). Exponent configurable in advanced settings (default 2.0).
- Applies to darkness min / max points (Auto mode) and any Autopilot intensity moves.
- Uses the fixture light curve (item 2) to work out light from DMX, so it stays right if a type's curve changes.
- MASTER, drum flash and head limits unaffected.

## 8. Fade test page
- Per fixture (or type): 0 → 100 % → 0 ramp over a set time (default 8 s), and steps at 10 / 25 / 50 / 75 / 100 %.
- Simulated swatch beside the fixture name, so screen and real light can be compared live.
- Shows the curve in use (output and light) with the current point moving along it.

## 9. MCP / API
- `list_curves` — every fixture type's light and output curve, minimum on, fine-channel status.
- `set_curve {type, light | output, curve, points?}`, `set_min_on {type, value}`.
- `fade_test {fixture | type, mode: ramp | steps, seconds}`.
- `match_start {type}`, `match_set {step, value}`, `match_save`.

## Acceptance (on the rig)
- Simulator vs real at 10 / 25 / 50 / 75 %: after the match wizard, each step judged a close match by eye in a dark room, for LCB803 and MHL36.
- Autopilot fades and dull passages look about as bright in the simulator as on the rig.
- Output curve Linear (default): DMX output byte-identical to v9 for the same show (recorded 60 s comparison).
- Square law on the LCB803 with the fade test ramp: fade looks even top to bottom, no dead travel above 50 %, no flicker or step at the bottom; reaches true black.
- Darkness slider at 25 / 50 / 75 % reads as roughly ¾ / ½ / ¼ brightness on the rig.
- Colour fade on an RGB fixture holds its hue to black.

## Open items
1. Simulator mapping: confirm in code how DMX is currently drawn (plan step 1).
2. Existing shows: perceived darkness makes the same slider setting darker than in v9 (50 % → 25 % mean light, was ~50 %). Convert saved darkness values on load so shows look the same, or leave as is and re-tune.
3. Fixture menus: which rig fixtures have their own dimmer curve setting, and what they're set to now.
4. Glow / bloom strength default — tune on the rig.
