# v5 + v6 build plan (28/11/2026)

Brief: `docs/v5-v6-brief.md`. Base: `autopilot-exclude` (v4.1 + the 27/11 Open DMX fixes + Autopilot exclude). Baseline 1179 tests passing.
Strobe limits unchanged throughout. Every hard rule keeps its tests under both profiles.

## Conflicts with SCOPE.md (brief wins; SCOPE updated in the same commit as the change)
| SCOPE | Brief | Change |
|---|---|---|
| Open DMX timing (v4.1): "D2XX is not used" | `d2xx` break method | D2XX loaded via ctypes (`ftd2xx.dll` / `libftd2xx`), optional, offered only when present. No new pip dependency |
| Beat sync (R5): kick average, `timeout_s` then fixed timers | Comb tracker, freewheel at last good BPM, never timers | Rewrite row; `timeout_s` only for `midi_clock` source |
| Set steps: "tap tempo never changes step length" | `step_beats` follow the beat clock | Rewrite row (code already does this) |
| Named inputs: kick role else rig `kick_note` | Kit is the one map | Kit supersedes both; `kick_note` migrated, then ignored |
| Rule 5 / setup tools refuse haze | Test "all full" includes haze "if ticked" | Decided: haze always excluded from test patterns (rule 5) |

## Decisions (28/11/2026)
1. D2XX: loaded via ctypes if installed, no new package, offered only when present. SCOPE: "D2XX optional, loaded if installed (v5)".
2. Per-layer key is `lit:` (not `fill:`, which means drum fills in Part B). Code: `lit` / `effective_lit`. `set_autopilot {darkness}` unchanged.
3. Haze always excluded from test patterns.
4. Darkness applies to Autopilot looks only. Hand-programmed scenes and shows play as authored. Override never affected.
5. Kit owns drum flash targets. `midi/default.yaml` backed up before the first-load migration.

## Part 1 (v5): DMX output diagnostics — built 28/11/2026
Built in dependency order (test patterns before the cycle test that uses them). One commit per step, with tests.

1. **Output settings.** `parse_outputs` and `set_output` accept `break_method` (`auto`/`d2xx`/`serial_break`/`baud_drop`), `break_us` 88–1000 (176), `mab_us` 8–100 (12), `fps` (40), `channels` (`512` or `patched`). Missing = defaults, no warning. Format stays 6.
2. **Open DMX driver rework** (`output/enttec.py`). Break strategies as small classes over one port:
   - `serial_break`: `break_condition` on/off (today's path)
   - `baud_drop`: write 0x00 at `9 / break_us` baud (start + 8 zero bits = break, stop bits = MAB), then back to 250k
   - `d2xx`: `FT_SetBreakOn/Off`, `FT_Write` through a ctypes D2XX handle
   - Frame pacing from `fps`; channel count 512 or last patched channel
   - Measured per frame on the host (`perf_counter`): break, MAB, write time, achieved fps, jitter. Amber if break < 88 µs, MAB < 8 µs or fps < 80 % of target. Exposed in `status()`, the routing table and Monitor, with the "host-side, best effort, wire not verifiable" note
3. **Test patterns** (item 4). Engine `test_pattern` stage after the rule layer, replacing the target universe/output frame:
   - Patterns: all full, fixture chase, find fixture (colour flash 1 Hz plus tilt nod), channel ramp/hold, keep-alive
   - Head limits still clamp pan/tilt. Strobe forced off in all full. Haze excluded
   - Stop on button, on page leave (UI heartbeat) or on timeout (60 s)
   - Gig lock: keep-alive only. Logged "TEST" in the Monitor DMX pane
   - Monitor test panel. MCP `run_test_pattern` and `stop_test_pattern`
   - The old Setup find fixture and channel tester are left as they were (separate operator tools)
4. **Cycle-methods test** (item 1). Steps `d2xx`* → `serial_break` → `baud_drop` → long break 500 µs, 5 s each, with all full running. The active method shows in large text and "Lights responded" saves that method and timing to the output. Disabled under gig lock.
   - MCP `test_output_methods {output, confirm?}` starts the cycle and returns the step tapped in the UI (or Claude passes `confirm` from chat), or none
5. **Health checks** (item 2). New `output/ftdi.py`, with OS readers injected so it can be tested here:
   - Driver: VCP vs D2XX. Windows: FTDIBUS registry and D2XX enumerate. Linux: `ftdi_sio` and sysfs
   - Latency timer: Windows registry `LatencyTimer`, Linux `/sys/bus/usb-serial/devices/ttyUSBx/latency_timer`, D2XX `FT_Get/SetLatencyTimer`. Set via D2XX with confirmation
   - Exclusive open: access denied = red. Names Daslight / QLC+ / FreeStyler if found in the process list (`tasklist`, best effort)
   - Baud and 8N2 read back. USB selective suspend from the registry = warn
   - Runs at start and on hot-plug (DeviceRegistry events). Feeds `get_alerts` and the status badge (reason on hover)
   - MCP `check_outputs`. `list_outputs` and `node_health` gain method, targets and measured timings
6. **Fault-find wizard** (item 3). The tree is data (`diagnose.py`), shared by the UI and MCP:
   - Step 1 runs item 5 checks. Then the "auto/sound mode?" branch, with the brief's steps in its order
   - The live frame flags "app sends 0 for this fixture" before any hardware step
   - Pass/Fail per step. Summary copyable and written to the log
   - Monitor button, linked from a red/amber DMX badge. MCP `fault_find {start|answer}`
7. **Docs.** Manual troubleshooting page, CHANGELOG, SCOPE decisions, get_guide FAULT-FINDING section.

Limits in this environment: no Windows, FTDI or D2XX here. Driver code is tested against fake serial/D2XX/registry objects, so timings and the cycle test need a real check on the gig laptop with COM3.

## Part A (v6): Darkness (effect `lit`) — built 28/11/2026
1. `lit` (0–1, YAML 0–100 %) as a layer common key (beside `shift`), carried into `Run`. Each colour effect shapes its own black:
   - Sweeps/chases (linear_wave, radial, bars, colour_chase incl. middle-out, pixel_chase, dir_sweep, comet): lit band = lit × pattern length
   - Palette / colour cycles (palette, colour_chase, colour_fade, gradient cycle): black slots interleaved evenly
   - Gradients / rainbow: gaps between segments totalling (1 − lit)
   - Static colour (palette static, split): regular black pattern across units, moving with `shift`
   - Default 100 % leaves both goldens (v1, v3 FX) bit-identical
2. Darkness: effective_lit = look lit × (1 − darkness), applied to Autopilot looks only (where `ride_play` builds them), so scenes, shows and Override are untouched. Kick (rig `exempt`) skipped. Black = colour 0, never dimmer. Movers keep moving dark.
3. Soft edges from the look's `fade`. Slider moves ease over the same fade.
4. Rig `autopilot:` block gains `darkness` and `set_darkness {low, mid, high}`, loaded on mood change. A live move overrides until the next change.
5. Control:
   - Autopilot › Feel › Darkness slider (large target)
   - MIDI action `darkness` (CC/OSC continuous). Input role `darkness` in inputs.yaml with `range` and `curve`
6. Step editor and `preview_look` take lit and a preview darkness. `validate_scene` warns on dimmer-made black under `0.05_band`.
7. MCP:
   - `set_autopilot {darkness}` and `set_set_darkness` (new)
   - `autopilot_status` adds darkness, its source and the CC
   - `get_guide` section
8. Acceptance tests from the brief, as written.

## Part B (v6): Tempo from the e-drums
1. New `beat.py`: onset merger (30 ms, max weight, velocity floor), comb-filter tracker (6 s window, ±15 % of seed, clamped 40–240), phase from snare 2/4, output stage (8-beat median, 3 %/4-beat deadband with a 1–2 beat glide, 15 %/8-beat jump guard, ≤10 % phase nudge), confidence and freewheel. Pure functions on timestamps, so tests feed synthetic grooves (steady, fills, drift, push, half-time).
2. `TempoClock` gains source `drums` (replaces `kick`, which still reads and maps to drums) and bar, beat, confidence and freewheel. Tap, count-in and the FCB tap seed and reset it. `midi_clock` kept, not default.
3. Consumers: `step_beats`, autopilot speed and beat-synced effects follow the clock. `step_s` stays on timers. Source off → last BPM, else 120.
4. Input Monitor: hit lanes per role with the beat grid, raw vs output BPM graph, confidence, seed source. All parameters live-tunable (rig `tempo:` block).
5. MCP: `tempo_status`, `tap_tempo`, `set_tempo_source`, `set_tempo_params`, plus a guide section.

## Part C (v6): Drum Kit builder
1. `inputs.yaml` gains `kits: {name: {device, channel, pieces: {...}}}` and `active_kit`, within format 6. Pieces and zones carry name, notes, role, weight, velocity floor, tempo y/n, flash target and trigger.
   - Roles: kick, snare, hat, tom, cymbal, tap, count_in (`count-in` accepted), trigger_only
   - `activity` is derived (every piece except tap/trigger-only), so autopilot energy keeps working
2. Migration on first load: drum-role inputs, the rig `kick_note` and the drum flash mappings become kit `band_kit`.
3. Kit resolves to the same named inputs, roles and flash mappings the router already uses, so flash, BUS, autopilot and tempo read one map.
4. MIDI › Drum Kit page: GM default, learn per zone, add/rename/delete, live hit view, unmapped notes flagged, import/export YAML.
5. MCP: `list_kits`, `get_kit`, `set_kit_piece`, `set_active_kit`, `kit_learn_status`.

Note: Part B's role weights and the "include in tempo" flag come from Part C. B is built first as the brief orders, with weights in the rig `tempo:` block, then moved to the kit in C (both read; kit wins).

## Delivery
Branch `ccr-fe77872d-zp514l`, pushed after each part. Full test suite green before each push. No PR unless asked.
