# 0.05 DMX Suite — v5 + v6 brief (28/11/2026)

Repo: Glen36-repo/0.05-dmx-suite. Save as `docs/v5-v6-brief.md`. Builds on v4 (routing table item 8, Monitor page item 15, device discovery item 18, Autopilot rename — all built).

Build order: Part 1 (v5 diagnostics) first, then Parts A, B, C. Plan before writing code. No strobe limit changes.

---

# PART 1 (v5) — DMX output diagnostics

## Problem seen
Rig dark while autopilot running: Enttec Open DMX on COM3 shows connected, packets counting, 0 errors, but fixtures drop to auto/sound mode — i.e. no valid DMX reaching them. The app gives no way to tell whether the interface, the driver timing, the cable/wireless path or the fixtures are at fault.

## Changes
1. **USB DMX (open-style) driver — selectable break method and timing**
   - Problem: open-style FTDI interfaces (Enttec Open DMX) have no processor; the app must generate break / MAB itself. "Connected, packets counting, 0 errors" only proves bytes were written to the COM port, not that valid DMX is on the wire. Fixtures falling back to auto/sound mode = no valid frame start seen.
   - **Break method** setting per output: `d2xx` (FTDI D2XX `FT_SetBreakOn/Off`, most reliable, needs D2XX driver), `serial_break` (pyserial `send_break` / `break_condition`), `baud_drop` (send 0x00 at a low baud to fake the break, then switch to 250k). Default = best available for the detected driver (item 2).
   - Configurable timings: break µs (default 176, range 88–1000), MAB µs (default 12, range 8–100), frame rate target (default 40 fps), channel count sent (default 512; option to send only up to last patched channel).
   - **Measured, not assumed** — time each break / MAB / frame on the host and show achieved values beside the targets; amber if break < 88 µs, MAB < 8 µs, or achieved fps < 80 % of target. Note on screen that host-side timing is best-effort and the wire can't be verified on an open-style interface.
   - **"Cycle methods" test** — steps through each break method (plus a long-break variant, e.g. 500 µs) for 5 s each, active method shown in large text, while test pattern "all full" (item 4) runs; user taps "Lights responded" on the one that worked → saved to the output. Disabled under gig lock.
   - Rig `outputs:` entries gain `break_method`, `break_us`, `mab_us`, `fps`, `channels` (defaults when missing, no warning).
   - MCP: `set_output` takes the new fields; `list_outputs` / `node_health` report method, target and measured timings; `test_output_methods` {output} runs the cycle test and returns the confirmed step (or none).
2. **Driver / port health checks at startup and on hot-plug**
   - Detect which FTDI driver a USB DMX interface is on: VCP (COM port) vs D2XX. Show it in the routing table (v4 item 8) and Monitor (v4 item 15). Offer the `d2xx` break method only when D2XX is available.
   - **Latency timer** — read the FTDI `LatencyTimer` for the port (Windows registry FTDIBUS device params; D2XX `FT_GetLatencyTimer` where available). Amber if > 1 ms, with fix text ("Device Manager › Ports › COMx › Port Settings › Advanced › Latency Timer = 1"); set it directly via D2XX where possible (with confirmation).
   - Other checks: port opened exclusively (another app — Daslight, QLC+, FreeStyler — holding the port = red, name the conflict if detectable); baud actually set to 250000 8N2; USB selective suspend / power saving on the port (warn — can drop the device mid-gig).
   - Live stats per interface replace the bare packet count: target vs achieved fps, write time per frame, measured break / MAB (item 1), frames sent, write errors, last frame time, jitter.
   - Results feed `get_alerts` and the status bar badge (green / amber / red, reason on hover).
   - MCP: `check_outputs` → per-interface checklist (driver type, latency, exclusive open, baud, power saving, timings) with pass / warn / fail and fix text.
3. **Guided fault-find on the Monitor page**
   - "Rig not responding" wizard button on the Monitor page, also linked from a red / amber DMX badge. Read-only apart from the test patterns it starts; steps that change output settings disabled under gig lock.
   - Step 1 — automatic: run item 2 checks; stop on any fail with its fix.
   - Step 2 — question: "Are the fixtures in auto / sound / standalone mode?"
     - **Yes → no valid DMX reaching them.** In order: item 1 cycle-methods test → bypass wireless (cable direct, Beamz / nodes out of the path) → swap DMX lead, check 5-pin↔3-pin adaptor (pins 2/3 not swapped) → confirm lead is in the first fixture's DMX IN, not THRU → confirm the interface in another app (QLC+ / FreeStyler support Open DMX; Daslight doesn't) → if nothing works anywhere, suspect the interface (FTDI enumerates but RS-485 driver chip dead).
     - **No (in DMX mode but dark / wrong) → signal is arriving.** In order: "find fixture" (item 4) on the dark fixture → start address vs patch (1-based; show the patch value in the instruction) → fixture channel mode vs fixture type channel count → IN/THRU order and termination on long runs → MASTER / grand master / head limits in the live frame (are that fixture's values non-zero?).
   - Each step: one instruction, a test button where applicable, Pass / Fail; Fail moves to the next likely cause. End summary (what passed, where it stopped) copyable and saved to the log.
   - Uses the live DMX frame (v4 item 15) to flag "app is sending zero for this fixture" before sending the user to the hardware.
   - MCP: `fault_find` {start | answer} — steps the same tree so Claude can run it with Glen over chat; returns current step, instruction and available test.
4. **Test patterns — bypass scenes and masters**
   - Test panel on the Monitor page, callable from items 1 / 3. Output goes straight to the selected universe / interface, bypassing scenes, autopilot, Override, grand master and MASTER; head limits still applied to pan/tilt. Large "Stop test" button; normal output restored on stop, page leave or timeout (default 60 s).
   - Patterns:
     - **All full** — every channel 255 (option: patched channels only).
     - **Fixture chase** — one fixture at a time, full colour/white, dwell default 2 s; fixture name shown large as it runs.
     - **Find fixture** — pick a fixture → flash it (colour full on/off at 1 Hz; movers also a small tilt nod).
     - **Single-channel ramp** — pick a channel (or fixture + channel name) → 0→255→0 ramp, or hold a value on a fader.
     - **Keep-alive** — fixed frame (all zero or user-set) sent continuously; checks fixtures stay in DMX mode (no auto fallback) independent of content.
   - Safety: strobe channels forced off in "all full"; haze channel excluded unless ticked.
   - Disabled under gig lock except keep-alive. Logged in the Monitor DMX pane as "TEST".
   - MCP: `run_test_pattern` {pattern, universe | output, fixture?, channel?, value?, dwell_s?, timeout_s?} and `stop_test_pattern`.

## Open item
- Rig dark (27/11/2026) not yet isolated. Next: cable direct (no Beamz wireless), COM3 latency 1 ms, swap test in QLC+ or FreeStyler (Daslight can't drive an Open DMX). If QLC+ works on the same Enttec, the `enttec_open` driver's break/MAB timing is the likely cause (items 1–2). Fixtures falling to auto = no valid DMX reaching them, not an addressing issue.

---

# PART A (v6) — Autopilot Darkness (effect fill)

## Goal
A **Darkness** slider in Autopilot that makes the show darker by putting **black into the effects**. Not a dimmer. At light settings, sweeps and colour cycles run as continuous colour. As the slider goes darker, patterns contain more black: narrower lit bands, black slots in palettes, gaps between segments.

## Rules (0.05_band profile)
- Black always means colour off (RGB/W/A/UV = 0); the slider never writes dimmer or intensity channels. MASTER keeps ownership of on/off.
- No background glow: black means 0, never "slightly on".
- Kick logo light is exempt and always renders at its look's full fill.
- Haze untouched.

## Changes
1. **Per-effect `fill` parameter (0–100%)**
   - Every effect generator takes `fill`. Default 100% = current behaviour.
   - **Sweeps and chases** (linear_wave, radial, bars, chase, middle-out etc.): fill sets the lit band width as a fraction of pattern length; remainder is black. At 100% colour wraps continuously.
   - **Colour cycles and palettes:** black slots interleaved in proportion to fill (50% = colour, black, colour, black…). Distribute evenly; no two blacks in a row unless fill < 50%.
   - **Gradients and rainbows across pixels:** gaps open between colour segments. Total black = (1 − fill) of the span, split evenly between segments.
   - **Static colour looks:** regular black pattern across pixels or fixtures (alternate, every third etc. to match fill). Pattern moves with the look's existing `shift`.
   - Works across pixel addressing (`bar_1:px3`, `bars:odd` etc.) and spatial mapping from layout positions.
   - Moving heads keep moving while black — an "off" head travels dark.
2. **Autopilot Darkness slider — scales each effect's own fill**
   - effective_fill = look_fill × (1 − darkness). E.g. look at 60% fill, slider at 50% → renders 30%.
   - 0% darkness = looks as programmed. 100% = fully black except the exempt kick light.
   - Lives with existing Autopilot feel settings (speed, fade, fan, size, shift), e.g. Autopilot › Feel › Darkness.
3. **Soft black edges**
   - Lit-to-black transitions use the look's existing `fade` (soft edge). fade = 0 → hard cut.
   - Slider changes ease in through the same fade — no sudden jumps.
4. **Control**
   - UI slider on the Autopilot page with a large hit target (live performance control — see v4 density exceptions).
   - **MIDI CC mapping:** learn/assign a CC so an FCB1010 expression pedal can ride Darkness live. Stored as an input role (`role: darkness`) in inputs.yaml with configurable range and curve.
   - **Per-set defaults:** LOW / MID / HIGH each store a darkness value loaded on set change. A live pedal/slider move overrides until the next set change.
5. **Priority**
   - Fill/darkness stage applies after the look renders, before MASTER. Override (busk) sits above it and ignores darkness.
   - Drum flash with MASTER off flashes whatever the current pattern has lit; black slots stay black.
6. **Data / YAML**
   - Looks and scenes take optional `fill:` (per look, per effect layer). Autopilot block takes `darkness:` plus `set_darkness: {low, mid, high}`.
   - Back-compat: missing fill = 100%, missing darkness = 0.
7. **Editor and preview**
   - Step scene editor and preview_look show `fill`, plus a darkness preview slider to see the look at different settings without touching the live value.
   - validate_scene warns when black is produced through dimmer instead of colour under 0.05_band.
8. **MCP**
   - `set_autopilot` {darkness}, `set_set_darkness` {set, value}.
   - `autopilot_status` returns current darkness, its source (slider / CC / set default) and the CC mapping.
   - `preview_look` takes optional darkness.
   - get_guide explains fill and darkness with the dimmer-vs-colour rule.

## Acceptance
- Linear sweep on the 4 bars: darkness 0 = continuous colour; 50% = half of each sweep black; 90% = narrow travelling band.
- Palette cycle at 50% alternates colour and black.
- Kick light unchanged at any darkness.
- DMX map shows dimmer channels unchanged as darkness moves; only colour channels change.
- FCB1010 pedal sweep moves darkness smoothly, no step jumps.
- Switching LOW / MID / HIGH loads each set's stored darkness.

---

# PART B (v6) — Tempo from the e-drums

## Goal
A live beat clock (BPM, beat, bar, confidence) from the drummer's playing over MIDI. The band plays without a click, so the module's MIDI clock is not used (it only follows the module's own metronome).

## Background
- Kick is irregular — poor tempo source alone.
- Snare backbeat on 2 and 4 is useful for phase but breaks down in fills.
- Hi-hat sends different notes (closed 42, pedal 44, open 46) and changes subdivision between songs — can't be used alone.
- So the tracker uses all drums together, weighted, seeded by a tap.

## Changes
1. **Seed: tap tempo from three sources** (any, last wins)
   - Dedicated tap pad or rim-zone note (`tap` role in the kit, Part C).
   - Count-in auto-detect: 4 evenly spaced hits on a count-in role (sticks/hat) after > 2 s silence.
   - Tap button on the FCB1010.
   - A tap sets output BPM immediately and resets tracker history.
2. **Onset stream**
   - Every note mapped to a drum role is an onset. Hits within 30 ms merge into one onset, taking the strongest weight.
   - Role weights (editable): kick 1.0, snare 1.0, hat 0.5, toms 0.6, cymbals 0.4. Ghost notes below velocity floor (default 30) ignored.
3. **Tempo estimate: comb-filter tracker**
   - Sliding window ~6 s of weighted onsets.
   - Score candidate tempos with comb filter / autocorrelation, limited to **±15% of the seed** (blocks half/double-time lock).
   - Phase: align beat grid to onsets; snare-weighted 2 and 4 give bar position / downbeat.
4. **Output stage: hysteresis average**
   - Rolling median of the tracker estimate over the last 8 beats.
   - **Deadband:** output BPM changes only when the median differs from output by > 3% for 4 beats, then glides over 1–2 beats.
   - **Big jump guard:** change > 15% ignored unless it holds for 8 beats, then re-seeds (real tempo change).
   - Phase corrections nudged (max ~10% of a beat per beat); phase never jumps.
5. **Confidence and freewheel**
   - Confidence 0–1 from onset density and comb peak strength.
   - Below threshold (default 0.4 — fills, breakdowns, drums stopped): freewheel at last good BPM and phase. No fallback to timer steps.
6. **Consumers**
   - `step_beats` steps, Autopilot speed and beat-synced effects (chases, sweeps, Part A fill patterns) follow the beat clock.
   - `step_s` scenes stay timer-based.
   - Tempo source off → beat-based scenes run at last BPM, or 120 if none.
7. **Settings and debug**
   - Input Monitor page: hit timeline (one lane per role, beat grid overlaid), BPM graph raw vs output, confidence, current seed source.
   - All parameters tunable live: deadband %, hold beats, jump %, jump hold beats, lock range, window, weights, velocity floor, confidence threshold.
8. **MCP**
   - `tempo_status`: BPM, beat, bar, confidence, source, freewheel flag.
   - `tap_tempo`
   - `set_tempo_source`: drums / tap only / off.
   - `set_tempo_params`
   - get_guide gets a tempo section.

## Acceptance
- Steady groove at 120: output settles to 120 ±1 within 4 bars, no visible wobble.
- 2-bar fill doesn't move output BPM; confidence drop shows freewheel.
- 1% drift doesn't change output; sustained 5% push moves it after 4 beats with a glide.
- Half-time feel section (same pulse) doesn't halve BPM.
- Tap or count-in overrides immediately.

---

# PART C (v6) — MIDI: Build Drum Kit section

## Goal
A section in MIDI settings that defines the drummer's kit once, so tempo (Part B), drum flash and drummer light triggers all read from one map. Replaces hard-coded / out-of-date note numbers in inputs.yaml.

## Changes
1. **Kit builder UI** (MIDI page › Drum Kit)
   - Pick MIDI input device and channel (default ch 10).
   - **Learn mode:** select a piece, hit the pad, note captured. Multi-zone pieces (head/rim, bow/edge/bell, hat closed/pedal/open) capture one note per zone.
   - Piece list: kick, snare (head, rim, x-stick), hi-hat (closed, pedal, open), toms 1–4 (head, rim), crash 1–2, ride (bow, bell, edge), china/splash, extra pads, tap pad.
   - Add / rename / delete pieces for non-standard kits.
   - Start from a General MIDI default kit and edit.
2. **Per piece/zone fields**
   - Name
   - Note(s)
   - Role: kick / snare / hat / tom / cymbal / tap / count-in / trigger-only
   - Tempo weight (Part B)
   - Velocity floor
   - Include in tempo (y/n)
   - Drum flash target (fixtures/groups to flash with MASTER off; default from current flash setup)
   - Drummer trigger: optional scene / look / effect to fire, separate from the FCB1010
3. **Live view**
   - Kit diagram or list lights each piece as hit, with note number and velocity.
   - Flags notes arriving that aren't mapped, so missed zones are obvious.
4. **Storage**
   - Kits saved as named profiles in inputs.yaml (`kits: {band_kit: …}`), one active kit.
   - Import / export kit YAML for sharing (general-use goal).
   - Back-compat: existing drum inputs migrated into a default kit on first load.
5. **MCP**
   - `list_kits`, `get_kit`
   - `set_kit_piece` {kit, piece, notes, role, weight, flash, trigger}
   - `set_active_kit`
   - `kit_learn_status` — remote learn from Claude: arm a piece, next hit is captured

## Acceptance
- Full kit learned by hitting each pad once per zone; unmapped notes flagged.
- Tempo tracker and drum flash both use the active kit's roles with no other config.
- Drummer's trigger pad fires its assigned scene.
- Kit exported and imported on another machine gives the same mapping.
