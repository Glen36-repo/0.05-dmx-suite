# 0.05 DMX Suite — v3 scope: Auto Show ("Ride")

Draft 26/11/2026, decisions below. Builds on v2 (effect registry, spread/size/shift, spatial effects, beat sync, busking, rule profiles, fixture model).

## Goal

A great light show from any rig with no programming, the way Light Rider does it for DJs: add fixtures, press go. The engine picks and changes looks to the music; the user rides it live with a few big controls. This is the feature that makes the suite useful to people who will never build a scene.

Reference: Light Rider (Nicolaudie) — Move FX, Colour FX and Flash FX banks plus presets; live speed, fade, fan, size and shift controls; audio Pulse analysis, Beat Tap, Ableton Link; Auto mode with Slow / Medium / Hot moods; 15,000-fixture library.

## What's different from Light Rider

- Driven by MIDI only (drum hits, pedals, MIDI Clock) — no audio input; more accurate than a mic for a live band
- Spatial effects across the grid layout, not just fixture order
- Safety and profile rules always applied (heads move dark, no glow); haze stays on its own separate controls
- Claude can tune the autopilot and make presets via MCP
- Free, Windows desktop + any phone/tablet browser

## Releases

Planned 26/11/2026. One branch per release, each stacked on the last, simulator-only, every feature with tests including rule tests under both shipped profiles (`tests/rulecheck.py`). v3 builds on v2 R1-R8 (PR to main: Glen36-repo/0.05-dmx-suite#10).

| Release | Branch | Sections | Contents |
| --- | --- | --- | --- |
| V3.1 Foundations | `v3.1-foundations` | 15, 17, 19, 18 | Named MIDI inputs and devices; head position points per rig; colour wheel and palette editor; alerts and banners. Show file format 5 |
| V3.2 Step scenes | `v3.2-step-scenes` | 16 | Step scenes with tracking, step/fade per step, loop/once/bounce, timer/beat/input/manual advance, move dark or lit (40 Hz 16-bit glide inside head limits), effect layers on top, live speed/fade |
| V3.3 FX and ride | `v3.3-fx-banks` | 1, 2, 3, 9, 10 | Auto classification; Move/Colour/Flash/drum-reactive FX banks as registry effects; modifiers; ride controls; look quality rules as data; rig size scaling |
| V3.4 Autopilot | `v3.4-autopilot` | 4, 6, 11, 12, 13 | Autopilot (energy from input roles, moods, timed changes, fills); Ride page; between songs; control priority; decision log |
| V3.5 Generator | `v3.5-generator` | 5, 7, 8, 14 | Presets; scene and show generator (capture, lock and re-roll, per song); look review page and ratings; Claude MCP tools |

Sections 1 (classification) and 6 (Ride page) weren't in the original split: 1 goes with the FX banks that need it, 6 with the autopilot.

v2 items still open that touch v3 (R9, need the real rig): fixture addresses, palette positions and the MH-A tilt limit, the drum pad map. They affect the 0.05 defaults (device profile, points, autopilot tuning), not the build.

## Features

### 1. Auto classification
- Every patched fixture is sorted by what it can do (from the R7 fixture roles): moving heads, washes/pars, pixel bars, strobes/blinders, effect lights. Haze machines are never part of the auto show
- New fixtures join the auto show the moment they're patched; rig config changes need no reprogramming
- User can override a fixture's class or exclude it from auto

### 2. FX banks

All effects are registry effects (R3), so more can be added the same way. Agreed with Glen 26/11/2026: all of the below. Audience sweep and ballyhoo stay inside head limits. There is no strobe rate limit (v2 decision, kept for v3): strobe-type effects run at the rate set.

**Move FX** (moving heads, inside head limits, heads move dark between positions)
- Pan sweep, tilt sweep, circle, figure-8
- Fan out / fan in
- Swim (slow organic drift), float (very slow small drift for ballads)
- Centre / kit (all heads on one point)
- Random positions (palette positions, moving dark)
- Crossfire (beams cross), audience sweep (eye-safe height per head limits), ballyhoo (big fast sweep), mirror (left mirrors right)

**Colour FX** (all colour-capable fixtures)
- Static palette, rainbow, colour chase, chase in / chase out, carousel
- Sparkle, twinkle (softer, with fades), colour fade (slow crossfade through palette)
- Split (two colours, left/right or alternating), wave, pulse (whole rig breathes)
- Pixel bars: bounce, comet (dot with fading tail), fill / unfill
- Spatial: gradient sweep, radial (centre out / edges in), plasma / noise, bars
- Themed: fire (flickering reds/oranges), lightning (sparse white bursts), police (red/blue sides)

**Flash FX** (momentary: button, pedal or drum hit)
- Blinder (full white), colour hit, strobe, blackout, freeze
- Flash and decay (hit then fade out), chase hit (one quick chase), rig split hit (left or right half)

**Drum-reactive** (MIDI)
- Kick pump (brightness bump per kick), snare hit (hit on bars per snare)
- Tom roll (hits walk across fixtures as the toms go down), cymbal shimmer (sparkle burst on crash/ride)
- Fill build (speed and size ramp during a fill, look change on the crash), velocity colour (hit strength sets colour or size)

**Modifiers** (any effect)
- Speed, fade, fan/spread, size, shift, direction, waveform, groups-of
- Beat sync multiplier (½, 1, 2, 4)
- Mirror (symmetrical from centre), random order (fixed seed per scene so it repeats)

### 3. Ride controls
- Speed, fade, fan (spread), size (amplitude/width), shift (phase offset) — global and per bank
- Colour palette picker (curated sets: warm, cool, fire, ice, neon, white, band colours) with palette lock
- Big touch targets; usable from a phone or tablet on stage

### 4. Autopilot
- Picks a Move FX + Colour FX + palette + ride settings combination and changes it on a timer in seconds (set per mood, e.g. Low 60 s / Mid 40 s / High 20 s, with optional random ± variation), never repeating the last few looks; a drum fill + crash can force an early change
- Mood levels **Low / Mid / High** (replaces the v1 fixed-timer LOW/MID/HIGH sets, which still load); mood set by pedal, button, or automatically from energy
- Energy from MIDI only (no audio input):
  1. Drum MIDI: hit density, velocity, kick/snare pattern; a fill followed by a crash triggers a look change and a colour hit
  2. Beat sync from v2 (tap, kick taps, MIDI Clock) for effect speed
  3. Manual mood only (pedal or button), if no drum MIDI
- Breakdown detection: energy drop → slower, sparser looks; build → speed and size ramp
- Works with MASTER and drum flash exactly as now (MASTER off → drum flash; autopilot pauses)

### 5. Presets
- Save the current combination (FX, palette, ride settings) as a preset; preset grid on the Ride page
- Autopilot can be limited to chosen presets ("only these looks for this song")
- Presets usable as show steps and setlist cues
- Ships with starter presets that work on any rig

### 6. Ride page (UI)
- Move FX left, Colour FX right, Flash FX centre, presets along the bottom, ride faders, mood and autopilot on/off at the top; the separate Haze controls stay on screen alongside
- Live layout preview strip; busk overrides still sit on top
- All controls MIDI/OSC-learnable (FCB1010, pad controllers)

### 7. Claude via MCP
- Tune the autopilot in words ("less movement, more blue in the verses"), build presets, set per-song preset lists
- Explain what the autopilot is doing and why (current energy, mood, next change)

### 8. Scene and show generator

Same engine as the autopilot, but it writes normal, editable scenes and shows instead of running live. Autopilot and generator share the FX banks, classification, palettes and rules.

- **Capture:** "save this look" turns whatever the autopilot or Ride page is showing into a scene, ready to edit in the scene builder
- **Generate scenes:** pick mood (Low / Mid / High), style (e.g. rock, ballad, acoustic, opera), palette and how many; get that many scenes built from the FX banks for the current rig
- **Lock and re-roll:** keep the parts you like (colour, movement, flash, ride settings) and re-roll the rest; "more like this" makes variations of one scene
- **Generate a show:** builds sets with steps, repeats and fades (v2 show steps) from a mood plan, e.g. verse Low → chorus High → bridge Mid
- **Per song:** from the setlist, generate a starter show per song from its name, mood and BPM
- **Output is plain YAML:** generated scenes and shows are normal files, with a note of the seed and settings used, so they can be regenerated, edited by hand, in the UI or by Claude
- **Ratings (optional):** thumbs up/down on looks; the autopilot and generator favour liked looks and skip disliked ones
- **Claude via MCP:** "make me five moody blue scenes for the slow songs" calls the generator, then Claude can refine the results
- Same seed + rig + settings always gives the same result (testable)

### 9. Look quality rules
- Palettes built on colour theory (analogous, complementary, triadic, mono); no muddy mixes
- Consecutive looks must contrast (colour, movement or speed changes noticeably)
- Never two busy effects at once (e.g. fast colour chase + ballyhoo); one leads, the other supports
- Movement speed matched to colour speed and mood
- Rules are data (a weights/compatibility table), so they can be tuned without code changes and read by Claude via MCP

### 10. Rig size scaling
- Each effect declares what it needs (minimum fixture count, pixels, heads, colour mixing); the autopilot and generator only use effects the current rig can do
- Small rigs (e.g. 2 pars) get a reduced, intentional set; large rigs unlock spatial and pixel effects
- Rig config switch re-evaluates instantly

### 11. Between songs
- Drum silence for a set time (e.g. 4 s) = song ended: fade to an ambient "talking" look
- Count-in (e.g. 4 even hi-hat/stick hits) or first hit = song starting: straight back into the show
- Walk-on and walk-off looks, triggered by button/pedal or setlist start/end
- Thresholds adjustable per rig config

### 12. Live control priority (highest first)
1. Blackout / panic
2. MASTER off → drum flash
3. Flash FX and busk overrides
4. Hold (freeze the current look; autopilot stops changing)
5. Autopilot / running show
- Pedal-mappable: hold, next look, previous look, mood up/down
- Releasing a higher level crossfades back to the level below

### 13. Decision log
- Every autopilot and generator decision logged: time, energy, mood, look chosen, why (rule weights, trigger such as fill + crash or timer)
- "Why did it do that?" view on the Ride page; full log saved per gig
- Claude reads the log via MCP to explain and tune

### 14. Look review page
- Cycles through every look combination the rig can do (or a chosen subset), at rehearsal
- Rate (thumbs up/down) or ban each look; bans and ratings feed the autopilot and generator
- Filter by mood, effect bank or palette; jump straight to a look from the decision log

### 15. Named MIDI inputs (define once, use everywhere)

Make a named input (e.g. "Kick", "Snare", "Crash", "Pedal 3"), assign its MIDI message(s) once, then use the name everywhere. If a note changes, change it in one place.

- **Input definition:** name, source port (or any), channel, type (note / PC / CC / OSC address), one or more notes (e.g. snare head + rim), velocity range, velocity curve, colour/icon
- **Grouped into devices:** e.g. "TD-25 kit" holds Kick, Snare, Toms 1-3, Hi-hat, Crash, Ride; "FCB1010" holds its pedals; a keyboard or guitar MIDI device works the same way
- **Used by name in:** scene and show triggers, drum flash map, busk widgets, MASTER / hold / next / mood controls, setlist steps, autopilot energy, fill detection, between-songs detection
- **Roles for the auto show:** each input can carry roles: `kick`, `snare`, `tom`, `cymbal`, `count_in`, `activity`. Energy, fills and between-songs detection read roles, not notes, so any instrument can drive them (keyboard, guitar MIDI, pad controller), not just drums
- **Between songs:** "song ended" = no input with the `activity` role for the set time; "song starting" = `count_in` pattern or any `activity` input
- **Learn:** pick an input, hit the pad or press the key; the monitor shows incoming messages by input name ("Kick, vel 98")
- **Calibration per input:** play quiet / normal / loud to set the velocity curve (feeds energy)
- **Device profiles:** save and load a device (e.g. TD-25, Alesis SamplePad, FCB1010, generic GM drums) as a file; ship a few starter profiles; users can share theirs
- **Validation:** two inputs can't claim the same message unless marked as shared; deleting an input still used anywhere is refused with a list of where it's used
- **Migration:** existing MIDI map entries convert to named inputs automatically on first load (backup first)
- **Claude via MCP:** list, create and edit inputs and devices ("the kick is now note 35")

### 16. Step scenes (manual programming)

A scene made of steps you program by hand, Daslight-style. Each step is a fixed look; the scene runs through the steps with adjustable step and fade times.

- **Programming a step:** select lights on the layout, set colour, position, gobo, wheel and any channel directly (faders per channel), or capture the current output as a step
- **Tracking:** a new step starts as a copy of the previous one, so you only change what's different
- **Step list:** add, insert, duplicate, reorder (drag), delete; name steps; preview a single step; play from any step
- **Times per step:**
  - Step time: how long the step holds (seconds, or beats when beat sync is on)
  - Fade time: crossfade into the step (0 = hard cut)
  - Each defaults to the scene's default step and fade time; any step can override
- **Live adjustment:** scene speed and fade-time faders scale all steps while running; mappable to pedals/MIDI/OSC and busk widgets
- **Playback:** loop, play once, bounce (forward then back); trigger next step by timer, beat, a named MIDI input (e.g. "Snare" = next step) or manually (pedal next/back)
- **Fades follow the rules:** colour channels fade; wheels and gobos snap at the fade midpoint; unused channels end at 0; dimmer channels follow the active rule profile
- **Head moves: dark or lit**
  - `move: dark` — head goes dark, moves, then fades in (0.05 profile default)
  - `move: lit` — pan/tilt glide from the old position to the new one over the fade time, staying lit; fade time = step time gives continuous smooth movement (Generic profile default)
  - Set per scene, overridable per step; default comes from the rule profile
  - Pan/tilt interpolated at 40 Hz using fine channels where the fixture has them (16-bit); without fine channels slow moves may look slightly steppy
  - Fixture speed channel held at fastest during software glides (0 on the MHL36) so motor smoothing doesn't add lag
  - The glide path is checked against head limits; a path crossing a no-go zone is rerouted around it or, if it can't be, falls back to `move: dark` for that step
- **Effects on top (optional):** a step scene can carry effect layers (e.g. a sparkle over the steps)
- **Used anywhere a scene is used:** show steps, setlist, busk go buttons, autopilot presets; the generator and Claude via MCP can create and edit step scenes
- **File format:** plain YAML, e.g.

```yaml
scenes:
  intro_hits:
    type: steps
    step_s: 2          # default step time
    fade_s: 0.5        # default fade time
    playback: loop
    steps:
      - {name: red bars, set: {bars: {colour: red}}}
      - {name: blue heads, set: {heads: {colour: blue, position: kit}}, fade_s: 0}
      - {name: heads to crowd, set: {heads: {position: audience_l}}, move: lit, step_s: 4, fade_s: 4}
      - {name: all white, set: {all: {colour: white}}, step_s: 4, fade_s: 2}
```

### 17. Head position points

Named aim points (e.g. "Stage forward", "Drum kit", "Singer", "Audience L", "Audience R", "Ceiling", "Home") stored per fixture, because each head needs different pan/tilt values to hit the same spot.

- **Point definition:** name, description (where and what it's for, e.g. "lead singer mic, centre front, head height"), tags (e.g. `band`, `audience`, `safe`, `floor`, `ceiling`), and per-fixture pan/tilt values (including fine channels)
- **Not every head needs every point:** a point can be set for some heads only; a scene asking for a point a head doesn't have leaves that head on its last position and shows a warning
- **Setting points (Heads page):** select one or more heads, aim them live with a pan/tilt pad (fine mode for small adjustments), then store to a new or existing point; "focus" mode steps through the heads one at a time for a point
- **Per rig config:** points are saved with the rig config, since rooms and stage layouts differ; a quick re-focus walk at load-in goes through each point head by head
- **Reference by name:** scenes, step scenes, busk buttons, show steps and the autopilot use the point name, so re-aiming a point updates everything that uses it
- **Head limits apply:** a point can't be stored inside a no-go zone; existing points are rechecked when limits change
- **Used by:**
  - Step scenes and scenes (`position: drum_kit`)
  - Busk buttons ("all heads to singer")
  - Move FX: centre/kit, random positions and crossfire draw from points by tag (e.g. only `band` and `safe` points)
  - The generator and autopilot
  - Claude via MCP: lists points with their descriptions and tags as the reference for building scenes ("sweep from audience L to audience R, then hit the kit on the crash")
- **Optional stage coordinates:** a point can carry a rough stage position (left/centre/right, front/back, height) so Claude and the generator know where points are relative to each other
- **Values:** 0-1 of the head's pan/tilt range, as palette positions always were (16-bit through fine channels); the UI shows degrees where the fixture type has its pan/tilt range set

```yaml
positions:
  drum_kit:
    description: Drum kit, centre back, cymbal height
    tags: [band, safe]
    stage: {x: centre, y: back, z: mid}
    heads:
      mh_a: {pan: 0.42, tilt: 0.30}
      mh_b: {pan: 0.58, tilt: 0.30}
```

### 18. Alerts and banners

Warnings (e.g. "UM-ONE offline") can be cleared from the screen without losing track of them.

- **X on every banner:** dismisses it; the alert moves to an alerts list (bell icon with count on the status bar)
- **Comes back only on change:** a dismissed alert stays hidden while the state is the same; if the device recovers and drops out again, a new banner shows
- **Auto-clear:** banners disappear on their own when the problem is fixed (device back online)
- **Mute a device for this rig config:** "Not using this today" on a MIDI device or node stops its alerts until it's re-enabled or the rig config changes; muted devices show greyed in the health panel
- **Snooze:** hide an alert for 10 min / 1 h / rest of the gig
- **Severity:**
  - Info and warning (input offline, weak node signal): dismissable, mutable
  - Critical (engine fault, DMX output down, all outputs lost): can be minimised to a red status-bar indicator but not fully dismissed while the fault exists
- **Banners don't push the layout:** they overlay the top of the page so controls don't jump under your finger mid-gig
- **Gig mode option:** only critical alerts show as banners; everything else goes quietly to the alerts list
- **Alerts list:** time, device, message, state (active / dismissed / muted / cleared); kept in the gig log; readable by Claude via MCP

### 19. Colour wheel and palette editor

Extends the v2 scene builder's palette swatches (R3).

**Colour wheel (scene builder, step scenes, busk colour buttons)**
- Hue/saturation wheel plus brightness slider; hex and RGB entry
- Extra sliders appear when the selected fixtures have them: white, amber, UV
- White temperature presets (warm incandescent to cool daylight, in kelvin) for looks like the opera show
- Swatch row: current palette, recent colours, named colours
- Eyedropper: pick a colour from any light on the layout
- Fixture-aware preview: shows what each selected fixture can actually make (e.g. nearest colour-wheel slot for wheel fixtures), with a marker where it differs from the chosen colour
- Live preview on the rig while picking (throttled; off under gig lock)

**Palette editor (own page in the left menu)**
- Create, rename, duplicate, delete palettes; add, edit, reorder and remove colours with the colour wheel
- Named colours (e.g. "Band red", "Incandescent"): scenes reference the name, so changing it updates every scene that uses it
- Generate from a base colour: analogous, complementary, triadic, monochrome (same rules as the look quality rules)
- Tags (warm, cool, mood Low / Mid / High) used by the autopilot and generator to pick palettes
- Preview a palette on the rig as a static look or a chase
- Global palettes shared by all shows; import / export to share
- Deleting a named colour or palette still in use is refused with a list of where it's used
- Claude via MCP: create and edit palettes and named colours ("add a darker band red")

## Rules
- Safety rules (no glow, head limits, grand master intensity only, haze only from its own controls) apply to everything the autopilot does; the autopilot, generator and Move FX always move heads dark between positions (`move: lit` is only for hand-programmed step scenes)
- Haze is never touched by the autopilot, presets or Flash FX; it runs only from its own separate controls (v1 Haze section)
- Profile rules (MASTER, drum flash, kick light) unchanged
- Deterministic: autopilot uses a seeded random generator so a recorded session replays identically in tests

## Verification
- Simulator: recorded drum MIDI files drive the autopilot; golden-frame and decision-log tests
- Look changes land on the set interval (± variation); fill + crash forces an early change; no repeat within the last N looks
- Energy mapping: synthetic quiet/loud/fill patterns produce the expected mood
- Every effect has a golden-frame test on a reference rig and a small rig
- Every rule re-tested against all FX and the autopilot under both profiles, including worst-case drum rolls; haze channel unchanged by anything the autopilot does
- Fresh rig from the setup wizard: auto show running with no scenes defined
- Playwright: Ride page, preset save, autopilot on/off, mood change
- Quality rules: generated sequences never put two busy effects together; consecutive looks pass the contrast check
- Rig scaling: on a 2-par rig no effect needing more fixtures or pixels is ever chosen
- Named inputs: changing an input's note updates every scene, flash, busk widget and the autopilot with no other edits; roles drive energy and between-songs detection from a non-drum device; duplicate and in-use checks; old MIDI maps migrate unchanged in behaviour
- Step scenes: step and fade times (defaults and per-step overrides) hold to the frame on a fake clock; live speed/fade faders scale them; MIDI-triggered next step; wheels/gobos snap, heads move dark or glide lit per setting, glide stays inside head limits (reroute or fall back to dark), fine channels used, rules hold mid-fade
- Position points: re-aiming a point changes every scene using it; missing point on a head leaves it in place with a warning; points can't be stored in no-go zones and are rechecked on limit changes; per rig config; tag filters in Move FX only pick allowed points
- Alerts: dismissed alert stays hidden until its state changes; muted device raises no banners for that rig config; critical alerts can't be dismissed while active; auto-clear on recovery; banners never shift page layout (Playwright)
- Colour: picker output matches the RGB/RGBW/amber/UV values sent; wheel fixtures preview the snapped slot; renaming or changing a named colour updates every scene; generated palettes follow the theory rules; in-use deletes refused
- Between songs: synthetic MIDI with gaps and count-ins switches to the talking look and back at the right times
- Priority: each level overrides the one below and releases back with a crossfade
- Decision log: every look change has a log entry with its reason; review-page bans are never chosen again
- Generator: same seed gives identical files; every generated scene and show passes `dmx-suite check` and all rules; lock-and-re-roll keeps locked parts unchanged; capture matches the live frame

## Decisions (26/11/2026)

| Item | Decision |
| --- | --- |
| Energy source | MIDI only (drum MIDI, pedals, MIDI Clock); no audio input |
| Look changes | Timed in seconds, per mood |
| Haze | Separate control only; never in the auto show, presets or Flash FX |
| Fixture library | Open Fixture Library not bundled; import as in v2 |
| Step scenes | Manually programmed steps, adjustable step and fade time per step, with scene defaults |
| Head position points | Named points with per-fixture pan/tilt, description and tags, per rig config; referenced by name; Claude's reference for scene building |
| MIDI inputs | Named inputs grouped into devices, referenced by name everywhere; roles let any MIDI device drive the auto show |
| Strobe limit | None, as decided for v2: strobe, lightning and Flash FX run at the rate set |
| Point values | 0-1 of the pan/tilt range (16-bit through fine channels), as palette positions; degrees shown in the UI where the range is known |
| Heads moving | Autopilot, generator and Move FX always move dark; `move: lit` only in step scenes, default from the profile (0.05 band dark, Generic lit) |
| Releases | V3.1-V3.5 as above, stacked branches on top of v2 R8; v2 merged to main through one PR |
