# 0.05 DMX Suite — Scope

Nov 26, 2026 · @Glen Mahony

## Purpose and goals

A general-use live lighting program for Windows: build scenes and shows on screen, run them from MIDI or OSC with no operator at the laptop, and output DMX through USB interfaces, Art-Net/sACN or the 0.05 ESP32 nodes. No subscription, no locked hardware, and the show rules are written into the software instead of worked around.

The band 0.05 is the reference setup: it replaces their Daslight 5 and LR512, and the "0.05 band" rule profile matches their rig rules.

- Everything can be done in the UI with no YAML or Claude; Claude (MCP) is an optional extra
- Run a rig live from MIDI (e.g. FCB1010, TD-25, SamplePad) or OSC with no operator at the laptop
- Automatic shows that follow the active rule profile out of the box
- Laptop talks straight to the CoreS3 node by USB serial; node handles DMX out and wireless to the receivers
- Simple enough for one person to maintain, edit and fix at a gig

Out of scope: video, timecode and audio-reactive BPM (v1, v2 and v3: v3 energy comes from MIDI only); macOS/Linux builds.

## Rig and I/O

One DMX universe (512 ch) covers the rig now; the engine supports more for phase 2. DMX addresses and channel maps to be copied from the current Daslight patch.

| Fixture | Qty | Use in software |
| --- | --- | --- |
| BeamZ MHL36 moving head | 2 | Pan/tilt, colour, gobo; speed ch 0 = fastest; MH-A tilt limit |
| LCB803 8-pixel LED bar | 4 | Per-pixel RGB (32 pixels total) |
| StarColor 72 | 2 | Colour wash |
| U'King mini moving head | 2 | Colour only, no movement |
| Kick-drum RGB light | 1 | Logo light, own rules |
| Smoke machine (1 ch) | 1 | Manual HAZE only |

**Inputs (MIDI):**

- FCB1010 program changes, ch 1 (via UM-ONE, later wireless)
- TD-25 drum notes, ch 10 (through the FCB1010 chain)
- SamplePad 4 via USB MIDI (phase 2, H2MIDI Pro merge)
- Guitar boards later (phase 2)

**Output:** laptop → USB serial → CoreS3 SE + Unit DMX → wired DMX + wireless TX → AtomS3 Lite receivers.

## Functional requirements

The engine enforces the rules itself in the rule layer, so no look can break them. From v2 the rules are split in two.

**Safety rules (always on, for every user; scenes can't turn them off):**

- No background glow: any channel not in the active effect is fully off (rule 4)
- HAZE is never set by scenes or auto shows; it runs only from the Haze controls (rule 5)
- Grand master scales intensity only: never pan/tilt, colour choice or haze (rule 6)
- Moving head pan/tilt limits from the active rig config are always enforced (rule 8)

**Profile rules (settings per rig config; "Generic" and "0.05 band" profiles ship):**

- MASTER owns on/off; scenes never set dimmer channels, only colour (rule 1)
- MASTER off → drum hits flash the rig (rule 2, see Drum flash)
- Fixtures excluded from MASTER, e.g. the kick-drum light (rule 3)
- Colour-only heads and speed-channel direction are set in the fixture definition (rule 7), e.g. U'King heads colour only, MHL36 speed channel 0 = fastest

The "0.05 band" profile turns on rules 1-3 with the kick light excluded from MASTER (bright most of the time, follows the active effect on bars or movers). "Generic" uses standard dimmer behaviour with no drum flash.

**Drum flash (priority feature):**

- MASTER on: auto show runs; drum hits do not flash the rig
- MASTER off: rig sits fully dark; each mapped drum hit flashes, then cuts straight back to black
- Hit-to-light as fast as possible: a hit sends a DMX frame immediately, not on the next 40 Hz tick; measure total delay at rehearsal
- Pad-to-fixture map set in the MIDI map file, per show
- Velocity sets flash brightness; flash length set per pad
- Flash colour: follows the current show colour or white, per pad
- Works from the TD-25 now, the SamplePad later, triggered by the drummer
- Kick light keeps its own rules (not affected by MASTER)

**Auto shows:**

- Main band show: LOW / MID / HIGH sets, fixed-timer steps (\~60 / 40 / 20 s)
- Layers: colour + effect + movement running at once (more than two)
- Heads and colour chases synced; heads-on/bars-off and the reverse
- Heads move between positions dark; static looks (e.g. \~30 s on the kit)
- Fully random independent head moves, within limits
- Head colour mix: matching / white / contrast
- Opera show: white and incandescent yellow only, slow head scan, minimal
- Acoustic show: many colours, gently dynamic, nothing hectic

**Control:**

- FCB1010 picks show, set and MASTER; drummer triggers lights from the kit independently
- Panic/blackout and a manual override from the laptop
- Starts straight into a safe default if the laptop reboots mid-gig

**Grand master dimmer (show brightness):**

- One level (0–100 %) that scales the brightness of the whole show, independent of MASTER on/off
- Applied in the rule layer at output, so scenes never need changing; uses the dimmer channel where a fixture has one, otherwise scales its RGB values
- Sub-masters per fixture type: moving heads, LED bars, washes, kick light
- Drum flash follows the grand master, with an optional flash level of its own
- Never touches pan/tilt, colour choice or the HAZE channel
- Default levels saved per rig config (see Rig configs)
- Control from the browser UI fader, MCP, or a MIDI CC (e.g. the FCB1010 expression pedal); smooth fades, no steps

**Haze:** runs on its own controls, separate from scenes, shows, MASTER and the grand master.

| Mode | What it does |
| --- | --- |
| Off | No haze; boost still works unless the rig config blocks it |
| Manual | On while switched on (latch) |
| Pulse | Bursts of a set length at a set interval, e.g. 5 s every 2 min, to keep a steady haze |
| Boost | Footswitch: full output while held, or for a set time per press, then back to the current mode |

- Output level adjustable (machine has variable output); boost has its own level
- Safety: maximum continuous on-time, cooldown between boosts, and an auto-off timer (per rig config)
- Rig config sets the default mode, level and limits, or disables haze entirely (e.g. rooms with sensitive smoke detectors)
- Screen shows current mode, output on/off, time left on the timer and next pulse
- All haze controls mappable to FCB1010 switches via MIDI learn; Claude can change modes and settings via MCP (not during gig lock)

**Gig safety and setup:**

- Haze safety limits and timer: see Haze
- Moving head limits per rig config: pan/tilt no-go zones (audience eye level, low ceilings) saved in the rig config and enforced in the rule layer
- Setup and test page: find fixture (flash one light), channel tester, address check, node and receiver status
- Setlist mode: ordered song list, each song with its own show or cue; a pedal steps to the next song
- Tap tempo (optional): sync chases to a pedal tap or kick drum notes; fixed timers stay the default
- Simulator mode: fake MIDI in and an on-screen rig, so shows can be built and tested with no hardware

**Fixtures:**

- Import channel maps from the existing Daslight files or the Open Fixture Library
- Claude can add or edit fixtures via MCP, e.g. from a fixture manual PDF or a description of its channels
- Multiple DMX universes supported for the phase 2 receiver-per-light plan

**Rig configs:** saved setups for different rig sizes and layouts, picked at setup.

- Which fixtures are present (e.g. full rig, small rig with bars and kick light only)
- Shows adapt automatically: effects for missing fixtures are skipped or moved to what's there, no reprogramming
- Each config holds its own grand master and sub-master levels, head limits and haze settings
- Claude can create and edit configs via MCP

**Backups:** code and show files in a git repo, synced to OneDrive; any change can be rolled back

## Architecture

```
MIDI in (FCB1010, TD-25, SamplePad)     Browser UI / Claude (MCP)
              |                                   |
              v                                   v
   MIDI router  ->  Show engine  ->  Rule layer  ->  Output loop (40 Hz, 512 ch)
                                                          |
                                         USB serial / Enttec / Art-Net
                                                          |
                                                   CoreS3 SE node
                                                  /              \
                                          Wired DMX        3x AtomS3 receivers
```

Show logic lives on the laptop; the rule layer sits just before output, so no scene or effect can break the rig rules. Show files (YAML) load into the engine and the node only relays frames.

## USB serial protocol and node firmware

The laptop sends a full 512-channel frame about 40 times a second; the node only relays it. All show logic stays on the laptop.

**Frame (laptop → node):** start byte, type, length, 512 data bytes, checksum. Types: DMX frame, blackout, ping.

**Status (node → laptop):** node online, receivers online (per AtomS3), frame rate, errors. Feeds the laptop status page.

**Node health (heartbeat):** every 0.05 node, DMX and MIDI, sends a heartbeat about once a second; the laptop node relays the receivers' heartbeats over USB.

- Heartbeat holds: node name and type (DMX TX, DMX RX, MIDI), firmware version, uptime, wireless signal strength, packet loss, age of last DMX frame or MIDI message
- States: online, weak (poor signal or packet loss), offline (3 missed heartbeats)
- Health panel in the browser UI: one tile per node with state, signal and last seen; always visible as a small strip on the main screen
- Alerts: banner and sound on the laptop when a node drops or goes weak; clears when it's back
- Rig config lists the nodes expected, so a missing node shows straight away at setup
- Health log saved per gig for review afterwards
- Claude can read node health via MCP (e.g. "why did the left bars drop out?")
- Third-party interfaces (Enttec, CME H2MIDI) have no heartbeat: shown as connected/disconnected on USB only

**Adding nodes (auto-discovery):**

- All nodes run the same firmware; a new node announces itself on power-up with its unique ID (chip MAC)
- It appears in the health panel as "New node"; name it and assign it (rig config, universe, fixtures) once, and it's remembered from then on
- Settings are pushed from the laptop to the node, so no per-node firmware edits
- Only nodes with the band's pairing key join, so another band's or venue's gear can't connect
- Swap a dead node: assign the spare to the old node's slot and it takes over its settings
- Claude can list and assign new nodes via MCP

**Node firmware (CoreS3 SE + Unit DMX):**

- Appears as a USB CDC serial port, no driver needed
- Outputs wired DMX and forwards the frame to the wireless receivers
- If USB drops: holds the last frame briefly, then runs a basic stored fallback look, e.g. a slow colour fade (set from the laptop) until the laptop is back
- Status LEDs on the node and each receiver

Optional later: Enttec DMX USB Pro framing on the same port, so QLC+ could also drive it as a fallback (not confirmed it will be detected on Windows).

**Output drivers (pluggable):** the engine hands each frame to one or more output drivers, picked in settings. Same show runs on any of them, and two can run at once (e.g. node plus a backup).

| Driver | Use | Notes |
| --- | --- | --- |
| 0.05 node (USB serial) | Main output | Node handles timing and wireless |
| Enttec Open DMX USB | Backup / small gigs | PC generates the DMX timing; set the FTDI latency timer to 1 ms; possible flicker if Windows is busy |
| Enttec DMX USB Pro (and clones) | Spare | Interface handles timing; reliable |
| Art-Net / sACN | Network nodes, visualisers, other software (v2 R4) | Any network DMX node |

## Programming and editing looks

Shows are plain text files (YAML) built from reusable parts, with a browser UI for live tweaking. Text first means Claude can write and edit shows too.

- **Fixture file:** each fixture's address and channel map, set once
- **Palettes:** named colours, positions (e.g. "drum kit", "audience L") and gobos
- **Effects:** colour chase, pixel chase, random move, pan/tilt sweep, flash, with speed and spread
- **Scenes:** a set of layers (colour + effect + movement) applied to fixture groups
- **Shows:** ordered or randomised scene lists per set (LOW / MID / HIGH, opera, acoustic) with step times
- **MIDI map:** which PC / note does what, per show

Browser UI (on the laptop, viewable from a phone): live preview of the rig, set/show buttons, fader overrides, position picker for heads, node status. Save writes back to the YAML files.

**MIDI monitor and mapping screen:**

- Live list of incoming MIDI: time, source port, channel, type (note / PC / CC), number, velocity
- Each line shows what it triggered (scene, flash, MASTER) or "unmapped"
- Filter by port or channel; pause and clear
- MIDI learn: pick an action, hit the pad or press the pedal, and the mapping is set
- Mapping table per show: input → action, with velocity range and flash settings for drum pads
- Saves to the MIDI map file (same file Claude edits via MCP)

**Claude via MCP:** a local MCP server on the laptop lets Claude (Desktop) build and edit shows in plain words, e.g. "make a slow blue scene with the heads on the kit".

- Read: fixtures, groups, palettes, effects, scenes, shows, MIDI map
- Create / edit / duplicate / delete scenes, shows, palettes and fixtures
- Every write is checked against the hard rules (no dimmer in scenes, no glow, no haze) and rejected with the reason if it breaks one
- Preview: play a scene live on the rig for a set time, then return to what was running
- Save writes the YAML files, with a dated backup of the previous version so any change can be undone
- Gig lock: when on, Claude can read but not change or preview anything

**0.05 branding:**

- App name (0.05 DMX Suite), window title and browser tab carry the 0.05 name and logo (icon/favicon too)
- Browser UI in the band's colours and fonts, dark stage-friendly theme so the screen doesn't glow on stage
- 0.05 logo on the start-up screen and node status page
- CoreS3 node screen shows the 0.05 logo at boot
- Brand assets kept in one folder (logo SVG/PNG, colours, fonts) so the look can be updated in one place

## Phases and milestones

Each phase ends with something usable at rehearsal; Daslight stays as backup until phase 4 passes a gig.

1. **Node link:** firmware for USB serial → DMX + wireless; test script that sends a frame and reads status; stored fallback look; git repo set up
2. **Engine core:** fixture file, 40 Hz output loop, MASTER / blackout / HAZE, hard rules, MIDI in from the UM-ONE, Enttec Open DMX output, drum flash working end to end, basic MIDI monitor and learn, grand master dimmer, haze timer, head limits, simulator mode
3. **Effects and scenes:** layers, palettes, colour/pixel chases, head moves; fixture import; setup and test page
4. **Auto shows:** LOW / MID / HIGH, opera, acoustic; setlist mode; tap tempo option; rehearsal test, then first gig with Daslight on standby
5. **Browser UI and MCP:** preview, overrides, position picker, node status page; MCP server for Claude to read, edit, validate and preview scenes
6. **Phase 2 MIDI:** SamplePad via H2MIDI Pro, drummer triggers, guitar boards; second DMX universe for receiver-per-light

## v2 (general release)

Planned 26/11/2026. One release per branch, hardening and features side by side; every item has tests and is tested against every rule under both shipped profiles.

1. **R1 Rule profiles and safety net:** safety/profile rule split (first; later releases depend on it), Generic and 0.05 band profiles, `version:` in every show file with automatic upgrade, engine loop timing fix, crash-proof render with fallback to the last good show files, value range checks, comment-keeping YAML saves, MIT licence and project files, user manual, CI (tests, lint, type-check, firmware build), file log, signed installer and update check
2. **R2 Layout, groups, themes:** left-hand page menu; grid light layout (one square per light or pixel, live colours, group tabs, select, arrange, zoom, beam-line overlay) replacing the metre stage plan; groups made from a selection; themes (neutral default + 0.05); all UI text in one strings file
3. **R3 Effects and scene builder:** effect registry; layer level and blend; new effects; spatial (matrix) mapping across the layout; spread, direction, width, waveform and groups-of on every effect; on-screen scene builder with live preview
4. **R4 Outputs and OSC:** non-blocking driver threads; Art-Net and sACN; OSC input sharing the MIDI map and learn; thread-safety fixes
5. **R5 Fades, shows, beat sync, busking:** crossfades; Daslight super-scene style show steps (repeat a scene N times, hold for time or bars, fade per step); show and setlist builders; beat sync (tap, kick taps, MIDI Clock); Busk page of user-built buttons and faders
6. **R6 Security, undo, copy/paste:** PIN/password, localhost by default, LAN with QR code; Claude bound by gig lock server-side; shared live feed; undo/redo; copy/paste a look across fixture types
7. **R7 Fixtures and setup wizard:** colour mixing to RGBW/amber/wheel, fuller fixture model, fixture editor and patch with auto-patch, OFL import and export, live rig changes, first-run wizard, starter shows
8. **R8 Node and firmware:** per-universe radio sequence, fallback and blackout on every universe, fallback pushed by the app, firmware version check, CoreS3 screen, node LED and identify
9. **R9 Rehearsal sign-off:** the open items below that need the real rig

## v3 (auto show "Ride")

Planned 26/11/2026; full scope and release list in `docs/V3-SCOPE.md`. A light show from any rig with no programming: the engine picks looks from FX banks and changes them to the band's MIDI, and the user rides it with a few big controls. Stacked branches on top of v2 R8, each with tests including rule tests under both profiles.

1. **V3.1 Foundations:** named MIDI inputs and devices, head position points, colour wheel and palette editor, alerts and banners
2. **V3.2 Step scenes:** hand-programmed steps with step/fade times, heads move dark or lit
3. **V3.3 FX and ride:** auto classification, Move/Colour/Flash/drum FX banks, ride controls, look quality rules, rig size scaling
4. **V3.4 Autopilot:** energy and moods, Ride page, between songs, control priority, decision log
5. **V3.5 Generator:** presets, scene and show generator, look review page, Claude tools

## v4 (stage view, Layout / Patch, routing, Monitor, step editor)

Brief 27/11/2026, built 26/11/2026 as one release on `v4-stage-layout`; full scope, decisions and open items in `docs/V4-SCOPE.md`. Zoom-to-fit stage view with outlined pixel bars, non-overlapping names and haze as an indicator; overlap warnings; a full-page Layout / Patch page with an address map of live values; explicit universe routing; devices by USB identity; a Monitor page; a real step editor with per-segment selection; haze settings; UI density; Ride -> Autopilot, Busk -> Override.

## Decisions and open questions

Decided 26/11/2026:

| Item | Decision |
| --- | --- |
| Language | Python |
| Laptop | Windows only |
| Claude / MCP | Runs on the gig laptop |
| First output | Enttec Open DMX until the node firmware is ready |
| Fixture setup | Imported from the current Daslight show file |
| FCB1010 | Current program change numbers kept for now |
| Drum flash with MASTER on | No flashes |
| Flash colour | Follows the show colour |
| Smoke machine | Variable output; warm-up not a concern |
| App name | 0.05 DMX Suite (working name) |
| Node fallback look | Something basic |
| Presets | Rig configs (sizes / layouts), not venues |
| Show files | OneDrive Music folder, next to the Daslight files |
| Other Daslight features | None needed |
| USB protocol | `0xA5` framing with CRC-16, full spec in `docs/PROTOCOL.md` |
| Node ↔ receiver radio | ESP-NOW broadcast, 512 channels as 3 chunks, no reassembly wait |
| Pairing key | Compiled into all firmware (build flag); radio packets carry a hash of it. Filters other gear, not encryption |
| Blackout | Sticky panic: stays black, does not time out into the fallback look |
| Unassigned receivers | Follow universe 0 so a fresh rig works before naming |
| Receiver with no node | Holds the last frame 5 s, then black |
| Blackout and haze | Blackout darkens every light including the kick light, but leaves haze running (haze has its own off) |
| Startup state | MASTER on with the current look, set per rig config (`startup.master`) |
| Kick light and flashes | Drum flashes never drive the kick light (it keeps its own rules) |
| Drum flash while blacked out | Ignored |
| Haze max on-time | Hitting `max_on_s` forces haze off for `rest_s`, then the mode resumes |
| MIDI on Linux | `python-rtmidi` is an optional `hw` extra; the simulator works without it |
| Effect timing | Every effect is time-based (`period_s` per cycle, `spread` 0-1 across the group), independent of frame rate |
| Installing on the laptop | Windows installer (PyInstaller app + Inno Setup), no Python needed; built by GitHub Actions or `installer/build.ps1` |
| Desktop program | `0.05 DMX Suite.exe` opens the UI in its own window (pywebview on Windows' WebView2, standard on Windows 11), with a tray icon; closing hides to the tray, Quit is in the tray menu. Same screens as the browser UI so phone access stays. Console `dmx-suite.exe` kept for Claude Desktop (MCP) and fault-finding |
| Installed show folder | Picked in the installer, default `OneDrive\Music\0.05 DMX Suite\shows`; saved as `DMX_SUITE_SHOWS`; starter shows only if the folder is new; never touched by upgrade/uninstall |
| Claude Desktop hookup | Installer option (on by default) runs `dmx-suite claude-setup`, which updates every Claude Desktop config found (standard and Store installs) |
| Moving U'Kings in scenes | A movement layer that includes a colour-only head is rejected at load, not silently skipped |
| Heads move dark | `random_move` has `dark_move_s`: the head is blacked (via colour) for that long after each new position |
| Find fixture | Lights the one fixture full white, ignoring MASTER, grand master and the kick light; head limits still apply |
| Channel tester | Raw values over the show output until cleared; refuses the haze channel |
| Missing fixtures in a scene | Skipped; a layer can name a `fallback` group to use instead (see "Missing fixtures in shows") |
| Fixture import | Open Fixture Library JSON first (`dmx-suite import-ofl`, or the Fixtures page); always lands as `verified: false`. R7: wheel slots, pixel matrices, 16-bit; export with `export-ofl` |
| Setup page | Setup tab in the UI (phase 5); console commands kept |
| Auto shows | Generated per step from a style (colours, energy, head mix, patterns, movement), deterministic per seed, checked against the hard rules like any scene |
| Set steps | `step_s` steps are fixed timers; `step_beats` steps follow the beat clock (v6: drums / tap / MIDI clock; 120 BPM when none). (Was: tap changes effect speed only; superseded by v3.2 step_beats and v6 Part B, 28/11/2026) |
| Tap tempo | Effects are timed at 120 BPM reference; a tapped tempo (pedal or a mapped drum note) scales effect time and lines up on the tap (v2 R5: also kick or MIDI clock, see Beat sync) |
| Set pedal outside a show | LOW / MID / HIGH goes to the current show if it has that set, otherwise the first show that does |
| Resume after restart | Live runs save show/set/setlist song/MASTER on every change to app data (`%LOCALAPPDATA%\0.05 DMX Suite\state`, one file per show folder; v1's `shows/.state.json` is moved there once); restored on start if under 12 hours old |
| Missing fixtures in shows | Auto shows only use fixtures in the rig; hand-written scene layers can name a `fallback` group |
| Kick light in auto shows | White most steps, the show colour about 30 % of steps |
| Browser UI | Standard-library web server + server-sent events; no build step, no internet needed |
| UI access | Localhost only by default; Host header must be localhost or an IP (blocks DNS-rebinding). v2 R6: PIN sign-in for phones replaces the token link (see Access (R6)) |
| Gig lock | Blocks file changes, preview, Claude haze changes, MIDI map save and node naming; the band's live controls still work; survives a restart |
| Claude haze control | off / manual / pulse only; boost stays on the footswitch |
| Preview | Plays under the current MASTER (rule 1), so with MASTER off the rig stays dark and Claude is told so |
| Edits | Staged and checked against the whole show folder (every rig) before writing; previous file kept in `shows/.backups/<date-time>/`; writing YAML drops comments |
| Live reload | Scenes, palettes, shows, setlists and MIDI map reload straight away; fixture/rig changes need a restart |
| Claude without the engine | MCP edits the show files directly with the same checks; live tools report the engine isn't running |
| Universes | 0-15 per fixture; every universe rendered and sent each frame (and on drum hits) |
| Port-specific MIDI | Mappings can name an input (`port`, part of the port name); a port-specific mapping wins, so SamplePad and TD-25 can share ch 10 notes |
| Stage plan | Replaced in v2 R2 by the grid light layout (see "Light layout" below); v1 metre stage plans upgrade to grid cells (file format 3) |
| Status bar | Engine fps, every output driver, MIDI inputs, Claude (MCP check-in every 20 s; last tool), open screens, nodes; red banner + beep when anything drops |
| USB DMX unplug | Enttec Open/Pro and the node keep the show running when unplugged and reopen the port every 2 s |
| MIDI hot-plug | Wanted ports (rig `midi_inputs`) rescanned every 2 s; reconnect under a new name; status shown as connected/unplugged |

Decided 26/11/2026 (v2):

| Item | Decision |
| --- | --- |
| Audience | General use, not just 0.05; 0.05 is the reference setup |
| Platform | Windows only |
| Licence | MIT; no telemetry |
| Name | "0.05 DMX Suite" kept for now |
| UI first | Everything can be done in the UI with no YAML or Claude; MCP is an optional extra |
| Rule profiles | Rules split into safety rules (always on) and profile rules (per rig config); "Generic" and "0.05 band" profiles ship; existing 0.05 shows run under "0.05 band" unchanged |
| Strobe limit | Not included: no rate limit on flashing (decided 26/11/2026, replacing the earlier 3 Hz safety rule). Flash effects and drum hits run at the rate set |
| File versions | `version:` in every show file; older files upgraded automatically after a backup; newer files refused with a clear message |
| Light layout | Grid layout (one square per light or pixel, group tabs, zoom) replaces the metre-based stage plan; beam lines kept as an overlay |
| Navigation | Page menu down the left-hand side; bottom bar on a phone |
| UI stack | HTML/JS in the desktop window, plain ES modules, no build step, works offline |
| Scenes and shows | Scenes built on screen from a selection; shows hold steps (Daslight super-scene style) that repeat a scene N times or hold for a time or bars, with an optional fade per step |
| v2 features | Spatial effects, effect spread, busking page, beat sync, undo/redo + copy/paste, OSC input added to v2 (26/11/2026), alongside fades, Art-Net/sACN and the fixture editor |
| Access | PIN or password on the UI and API; localhost only until LAN/phone access is turned on |
| Colour mixing for old types (R7) | Off for every type that existed before R7 so the 0.05 shows look exactly as they did; turn on per type on the Fixtures page |
| Show file (26/11/2026) | One `.dms` file per show (Glen, option 1): opened through a working copy, saved on every change, double-click to open; show folders still work |
| Set steps (v2) | Fixed timers stay the default; a step can instead follow the tempo (`hold_beats` / `hold_bars`) |
| Crossfades (R5) | `Crossfade` source mixes the old and new looks over `fade_s`: colour channels blend, wheel and gobo snap, a head whose position changes goes dark, moves and fades in, channels unused by the new look end at 0 (rule 4), haze untouched (rule 5). Used for show steps, rig `change_fade_s` (default 0 = cut, as v1) and busk release |
| Show steps (R5) | `steps:` of `{scene, repeats | hold_s | hold_beats | hold_bars, fade_s}`; set `fade_s`, `order` sequence/random, `loop`. `repeats` counts the scene's `length_s`. v1 `scenes:` + `step_s` read as steps with `hold_s` (no format bump: both forms load). Live page shows the step, repeat count and time left; tap a step to jump |
| Beat sync (R5) | Rig `tempo: {source: drums|tap|midi_clock|off, kick_note, timeout_s, + drums tracker settings}`. v6: `kick` reads as `drums` (beat.py: every drum weighted, tap / count-in seeded, comb tracker within +-15 % of the seed, 8-beat median, 3 % / 4-beat deadband with a glide, 15 % / 8-beat jump guard, phase nudged by rate <= 10 % a beat, freewheel at the last tempo under the confidence threshold, never back to timers). Without a kick-role input the rig's `kick_note` still feeds it. MIDI clock: 24 ppqn, start lines up the beat; clock messages kept out of the monitor; a lost clock keeps the last tempo for `timeout_s`, then fixed timers. `off` keeps the tempo (120 if none). Effect clock stays continuous on tempo changes (the old snap jump is gone). Global `speed` 0.25-4; layer `beats`. Ableton Link left out: no maintained Python binding for Windows |
| Busking (R5) | `shows/panels.yaml`, one panel per show or `default`; widgets colour/flash/solo/effect/go/fader/haze; MIDI/OSC action `busk`. Overrides sit above the show and below the rule layer; release crossfades back over `release_fade_s`. The static look is kept separately from what's shown, so overrides and held head positions are never baked into it |
| Show file saves (v2) | ruamel.yaml round trip: only changed data is rewritten, comments kept, unchanged lines keep their spacing; result must read back (PyYAML) as exactly the saved data, else written plainly. MIDI map saves go through the store (validated, backed up). Restore only takes `.yaml` files. Logs and resume state live in app data, not the OneDrive show folder |
| File format versions | Show files carry `version: 2` (format, not app version); no `version:` = format 1. One reader for every loader: newer formats refused, older upgraded in memory, then written back at start-up (`ShowStore.upgrade`, originals backed up, comments kept, not gig-locked). Format 1 → 2: rigs get `profile: 0.05_band`. Data from the UI/Claude is taken as the current format unless it says otherwise |
| Engine faults (v2) | Any error while rendering is caught: logged (once a minute per message), the engine drops to the static look, and if that fails too it keeps sending the last good frame; the status bar shows "Engine: fault" for 5 min. Driver and frame-listener errors never stop output |
| Loop timing (v2) | Frames on a fixed 40 Hz grid; early wakes (control changes, faders, flash ends) never move it. A control change sends once (no second frame from the loop). `time.perf_counter` clock; 1 ms Windows timer while running |
| Broken show files at start-up (v2) | Values are range-checked at load (raw DMX 0-255, seconds, %, shapes), and any malformed file is reported by name. If the folder won't load, `run` uses the newest earlier version from `.backups` that does (on a copy; the folder isn't touched), shows "Show files: running the last good version", and switches to the real files once they load again (fix or restore) |
| Project basics (v2) | MIT licence; contributing guide, code of conduct, issue/PR templates, changelog, user manual in `docs/manual/`. One app version (`dmx_suite/__init__.py`, read by pyproject and the installer); the firmware keeps its own (`config.h`, the simulator matches it). No telemetry |
| CI (v2) | GitHub Actions on every push: ruff, mypy, pytest on Windows and Linux (the firmware parity test must run on Linux, never skip), `pio run` for node and receiver; the installer workflow signs the installer when the certificate secrets exist |
| Logs (v2) | `dmx-suite.log` in app data, INFO and up, 1 MB x 5 rotating; warnings also on the console |
| Update check (v2) | On request only (`dmx-suite update-check`, `/api/update`): reads the latest GitHub release and says if it's newer. Check only, nothing downloaded. The repo is private, so it needs the repo public, a public release feed, or DMX_SUITE_UPDATE_URL |
| Light layout (R2) | Grid cells, not metres: `layout: {id: {x, y, rot, shape, cols}}`, x/y the light's centre from the top left (back of the stage at the top), half cells; pixel lights draw each pixel as a square laid out as a row, ring or grid. Format 2 -> 3 converts metre plans at 4 cells a metre and drops `stage:`. Defaults: heads at the back, bars end to end, washes and kick at the front, haze to the side |
| Layout editing (R2) | Select by tap/shift-tap/box/lasso/group tab; move, align, space out, make row/ring/grid, rotate 45°, pixel shape; undo; save rewrites the rig's `layout:` (validated, backed up) and applies live |
| Groups (R2) | Stored on the fixture entries in fixtures.yaml; `POST /api/store/group` set/rename/delete; rename updates every scene, look, rig and MIDI map in one change; delete refused while used; names can't be a fixture id, kind or `all`; applied live |
| Themes (R2) | Folders under `web/static/themes/` (theme.css variables, logo, name); Neutral default, 0.05 shipped; chosen per laptop in app data `settings.json`; the page names itself with `application-name` meta (desktop app and installer smoke test check that, not the title) |
| UI text (R2) | Every string in `web/static/i18n/en.json`, filled by `data-i18n*` attributes and `t()`; tests fail on missing, unused or hard-coded text |
| Information buttons (v4.1) | ⓘ by sections and tricky controls opens a small popover (`info.<key>.title` / `.text` in `en.json`, `js/info.js`); it never blocks: no backdrop, an outside tap closes it and still reaches the control, Esc closes only it, keys pass through, gig lock is fine. Help paragraphs became popovers; warnings stay inline. The manual is served offline at `/manual/<page>.md` (`dmx_suite/manual.py`, stdlib Markdown, HTML-escaped; manual links stay in-app, http(s) opens in the system browser, other schemes are dropped). Browser: a new tab; desktop window: a side panel, never in place of the page. Decided 27/11/2026 |
| Open DMX timing (v4.1) | Break and MAB from pyserial `break_condition` (Windows: SetCommBreak / ClearCommBreak, the VCP equivalent of FT_SetBreakOn/Off), with 120 µs / 16 µs busy-waits as floors; on the VCP each is a USB request, so the real break is ~1-2 ms and the MAB ~1 ms (legal: 88 µs-1 s and 8 µs-1 s). The next break waits for the previous frame's wire time (513 × 11 bits at 250 kbaud ≈ 22.6 ms + 1 ms), because flush() returns when the chip has the data, not when it is on the wire: ~37-38 fps. RTS/DTR low from open, buffers purged (Enttec sample). D2XX optional, loaded if installed (v5). Decided 27/11/2026 |
| Excluded autopilot types (v4.1) | Per rig, `auto: exclude_fx: [item ids]` (Move, Colour, Drum; not Flash FX, which are played by hand). The autopilot, Re-roll and More like this skip them; a tap still plays one; presets and the Review page / generator are unaffected. Set from the Autopilot page by an Exclude… mode or a 0.6 s hold; allowed under gig lock (store recovery, like Use this instead). Excluded = red, running = green. Kept in format 6 (not released yet). Decided 27/11/2026 |
| UI code (R2) | ES modules under `web/static/js/` (no build step); browser tests with Playwright in `tests/test_ui.py` (skipped without a browser, run in CI on Linux) |
| Effect registry (R3) | `dmx_suite/effects/`: one class per effect with a settings schema (`GET /api/effects`) and a render; the five v1 effects ported with identical output (golden frames); auto shows, the scene builder and Claude's guide read the registry |
| Layers (R3) | Static settings may sit alongside an effect (not a position with a movement effect); `level` 0-1 and `blend` replace/max/add mix colour with the layers below; `mute`; scene `length_s` (default: longest effect period) for show repeats |
| Spread controls (R3) | `mapping` order/spatial, `direction` forward/reverse/centre_out/out_centre/random (fixed per scene)/angle, `angle`, `groups_of` on every effect that runs across lights; `waveform` and `width` on the wave effects. Defaults keep v1 maths exactly |
| Spatial mapping (R3) | Positions from the layout grid, each pixel where it's drawn (same cell maths as the UI), scaled so the layer's lights span 0-1 on their longer side (angles stay true), worked out once per scene player; lights missing from the rig drop out |
| New effects (R3) | rainbow, sparkle, wave, strobe (colour channels), circle, figure8 (head limits still clamp); matrix: linear_wave, radial, gradient, bars, noise |
| Scene builder (R3) | Scenes page: selectable layout, layer list, forms from the schema, swatches, direction arrow, live preview of unsaved scenes (`/api/preview`, renewed while ticked), `POST /api/validate/scene` marks the failing layer; settings at defaults aren't written |
| Output threads (R4) | node_serial and enttec_pro write on a sender thread (newest frame per universe; an unwritten one is replaced, never queued; wakes at once for drum hits); port reopen happens there too. The simulated node stays synchronous for exact tests |
| Art-Net / sACN (R4) | Standard-library UDP, non-blocking. Art-Net: ArtDmx with sequence 1-255, broadcast or unicast, universes map to port-addresses (number or net:subnet:universe), default n -> n. sACN: E1.31, multicast 239.255.x.y or unicast, priority 0-200, CID stable per computer, default n -> n + 1. Only mapped universes are sent |
| OSC input (R4) | Rig `osc: {port, allow}`, off by default; allow defaults to this computer + private networks. Own parser (no new dependency), bundles unpacked. Mappings `{type: osc, address, action}` in the MIDI map; float 0-1 drives faders, >= 0.5 or no argument = press; learn takes MIDI or OSC. Feedback to controllers: not in v2 |
| Access (R6) | `access.json` in app data: PIN as salted PBKDF2 (200,000 rounds), `lan`, `pin_local`, `session_hours` (default 12). Phone/LAN access needs a PIN; turning it on or off moves the server between 127.0.0.1 and 0.0.0.0 on the same port. Phones sign in on a sign-in page: HttpOnly SameSite=Strict session cookie, a per-session token for changes, idle timeout, 5 wrong PINs = 30 s wait per address; all signed out when the PIN changes, phones too when LAN goes off. This computer gets in without a PIN unless `pin_local`. Access changes only from this computer. QR code from our own encoder (byte mode, level M, versions 1-10; installing a QR library wasn't possible here) |
| Claude role (R6) | Claude's token (`claude_token` in app data) is accepted only from this computer and only for store edits, preview, haze, node assign, scene validation and its own undo; never gig lock, access, settings, control, MIDI learn or layout. The page's token is new each run and never written to disk (a second launch hands over a file with a separate app token). Offline Claude edits respect the gig lock file in app data. MIDI learn and mapping removal honour gig lock |
| Live feed (R6) | One snapshot a tick (10 Hz) turned into JSON once for every screen; sent only when it changed, MIDI lines as they come, `{"beat": 1}` after 5 s of nothing. 5 s write timeout per screen; the page reconnects after 12 s of silence and shows a lost-connection box |
| Undo/redo (R6) | `ShowStore` remembers every change since start-up (files' text before and after, who: ui or claude), unlimited; a new change clears redo. Undo/redo go through the same validation, backups and gig lock; refused if a file changed another way since. Layout keeps its own undo for unsaved moves |
| Copy/paste (R6) | Scene builder: copy a layer (or the layer lighting the first selected light) without its lights; paste splits the selection by what each light has (moves, gobo, colour wheel) into one layer each, dropping position/movement effects, gobo and wheel where they don't fit. Colours copied as they are (RGB) until R7 |
| Fixture model (R7) | Show file format 4: fixture types gain `colour_mix` (auto/off; the 3 → 4 upgrade sets off on existing types so golden frames stay identical), named `wheel` slots (value + optional colour) and `gobos`, `sub` (sub-master apart from kind, on the type or a patched fixture), roles zoom/focus/frost/prism and `<role>_fine` for dimmer/pan/tilt/zoom/focus, invert on pan/tilt/zoom/focus/frost/pt_speed. Mixing: white = min(R,G,B) out of RGB, amber = min(R, 2G) − B, UV only when asked; white-only = max(R,G,B); no emitters (dimmer/wheel only): scale by brightness, nearest named wheel slot by hue. Slot names resolve per fixture at load, so looks and scenes carry DMX values |
| Live rig changes (R7) | A changed fixtures.yaml or running rig file is swapped into the engine under its lock: new rule layer (heads keep position), static look, haze; MASTER, masters and what's playing stay (show/scene rebuilt on the new rig, setlist and song kept). Outputs, MIDI inputs and OSC need a restart and say so (the running ones are kept). Rig switch (`rig` control command, Fixtures page) does the same with another rig file; refused under gig lock |
| Fixtures page (R7) | Patch, fixture types and rig settings on screen. Patch saves replace the patch list (`PUT /api/store/patch`); removing a light (`POST /api/store/fixture/remove`) also takes it out of every rig's layout, head limits and fixture list in one checked change. OFL import/export through `/api/ofl/import` and `/api/ofl/export/<type>`. Channel test uses the existing channel tester |
| Node protocol v1.1 (R8) | Firmware 0.2. Additive to v1: SET_FALLBACK_U (0x08), SET_CHANNEL (0x09), optional trailing request id on ACKed requests (echoed as a third ACK byte), STATUS 20 bytes (+flags, +channel). The app reads the node's firmware from its heartbeat and uses v1.1 only with 0.2+; 0.1 keeps working and is flagged |
| Node radio (R8) | Sequence number per universe (16 kept). Every universe the laptop sends is kept alive (last frame resent every 100 ms) for 10 s after its last frame, or for good with a fallback look. Fallback looks for up to 4 universes in NVS (`fb0`-`fb3`, firmware 0.1's single look read once as the node's own); fallback and blackout cover every kept universe, black where no look. App pushes each universe's static look (MASTER on, no haze, through the rules) on connect |
| Radio channel (R8) | Rig `radio_channel` 1-13, set on connect and from Setup. Node broadcasts SET_CHANNEL for 400 ms on the old channel, then moves; receivers follow and store it; a receiver silent for 10 s scans 1-13 at 300 ms each and stores where it finds the rig. ESP-NOW broadcast peer on channel 0 (= current) so no re-pairing |
| Node naming and spares (R8) | ASSIGN is confirmed by the target's own heartbeat (name and universe) within 4 s, reported as confirmed or not. Replace with spare: an online new node of the same kind takes an offline node's name and universe, the rig file's `nodes` swaps the MAC, the old record goes |
| Node screen (R8) | CoreS3 via M5Unified 0.2.2: name, mode, universe, fps, receivers, channel, firmware, DMX-failed and dev-key warnings; redrawn only on change, at most twice a second; identify and touch flash it. `M5.begin` with output power on for PORT.C (bench test) |
| Dev pairing key (R8) | Compile-time `#warning`, screen warning, STATUS flag shown in the app's status bar |
| Setup wizard (R7) | Opens when `settings.json` has no `wizard: done/skipped` (a new laptop), and from Setup. Interfaces from pyserial's port list: Espressif 303A = node, "DMX USB Pro" = Enttec Pro, FTDI 0403 = Open DMX. Every step skippable; writes through the store. Starter show: scenes `starter_*` and show `starter`, hex colours (no palette needed), no intensity or haze (valid under every profile), never overwritten unless asked |
| `.dms` show file (R6) | Zip: `dms.json` {dms: 1, format, app, saved} + the `.yaml` files; deflated, fixed timestamps; written to a temp file then `os.replace`. Unpack takes only safe relative `.yaml` names (no `..`, absolute, backslash, drive, hidden, links), at most 2,000 entries and 50 MB; newer `dms` or `format` refused. Runs on a working copy `app data/open/<name>-<hash>/`; `ShowStore.after_commit` packs after every commit. Recovery: a working copy whose content hash differs from the last pack is saved as "<name> (recovered DD-MM-YYYY).dms". Lock `<name>.dms.lock` {pid, host, at}: dead process on this computer or older than 12 h from another = left over. Switching files restarts the process (`os.execv`, same arguments, new `--shows`). Show file format stays 3 | Locks on ShowController (RLock on every public method), App.reload, HealthTracker (records() copies), MidiMonitor (since() copies). Measured render cost 0.1-0.3 ms a frame on the full rig, so per-frame caching was left out |
| Profile in rig files | `profile: 0.05_band`, `generic`, or a block with `base` + `master_gate` / `drum_flash` / `master_exempt`; no `profile:` = v1 file, runs as "0.05 band"; drum flash needs `master_gate` |
| Intensity | Without `master_gate`, looks and scene layers may set `intensity` (0-1), scaled by the masters; with it, `intensity` is refused at validation (checked against every rig) and ignored by the rule layer. The raw `dimmer` key stays refused everywhere |
| MASTER-exempt fixtures | Fixture ids, groups or a kind name (`kick` = every kick-kind fixture, as v1); they ignore MASTER and drum flashes and use the rig's `kick_colour` when the scene leaves them off. Under "generic" nothing is exempt and a kick-kind light is an ordinary light (auto shows use it like a wash) |

Decided 26/11/2026 (v3):

| Item | Decision |
| --- | --- |
| v3 releases | V3.1 foundations (named inputs, head points, colour wheel/palettes, alerts), V3.2 step scenes, V3.3 FX banks/ride/quality/scaling (+ classification), V3.4 autopilot/between songs/priority/decision log (+ Ride page), V3.5 generator/review/presets/Claude tools. Stacked branches on v2 R8; v2 to main by one PR |
| v3 energy | MIDI only (drum MIDI, pedals, MIDI Clock); read from named-input roles, so any MIDI device can drive it. No audio input |
| Strobe limit (v3) | Still none (v2 decision kept): strobe, lightning and Flash FX run at the rate set |
| Haze (v3) | Never touched by the autopilot, presets, generator or Flash FX; rule 5 tested against every v3 feature |
| Heads moving (v3) | Autopilot, generator and Move FX always move dark. Step scenes may glide lit (`move: lit`); the profile sets the default (0.05 band dark, Generic lit) |
| Moods (v3) | Low / Mid / High drive the autopilot; v1/v2 LOW/MID/HIGH show sets keep loading and running unchanged |
| Head points (v3) | Named points per rig config with description, tags, optional stage position and per-head pan/tilt as 0-1 of the range (16-bit via fine channels) |
| Rule tests (v3) | `tests/rulecheck.py` runs every new feature under both profiles and checks every rule on every frame |
| Named inputs (V3.1) | `inputs.yaml`: devices {name, port, channel, inputs}; input {name, type note/program_change/control_change/osc, notes or number or address, channel 1-16 or any, port, velocity [lo, hi], curve {quiet, normal, loud}, roles, shared, colour}. Ids unique across devices. Port-specific input wins (as mappings did); overlapping messages need `shared` on both. MIDI maps use `{input: id, action, ...}`; raw mappings still load. Calibrated curve maps quiet/normal/loud to 0.25/0.6/1.0 strength (drum flash level now, energy in V3.4). Tempo (v6 drums source) uses inputs with drum roles (kick, snare, hat, tom, cymbal; tap = a tap pad, count_in = count-in), else the rig's kick_note for the kick. Learn reuses a matching input or makes one in device `learned`. Device profiles shipped in `dmx_suite/midi/devices/`, the show's own in `devices/` |
| Head points (V3.1) | Rig file `positions: {name: {description, tags, stage {x left/centre/right, y front/middle/back, z floor/low/mid/high/ceiling}, heads {id: {pan, tilt}}}}`, 0-1. Lookup: the running rig's points over legacy palette positions; another rig's point name loads with no heads (warning). A head a point doesn't cover holds position, with a warning. Storing outside head limits refused; existing out-of-limit points are warnings (clamped by rule 8). Rename updates scenes, looks, shows and panels (`position`, `from`, `to`) |
| Palettes (V3.1) | `palettes.yaml` gains `palettes: {key: {name, tags, colours}}`; colours are named colours or values. Seven curated built-ins (warm, cool, fire, ice, neon, white, band), replaced by a same-name palette in the file. Colour theory in `colourtheory.py` (analogous, complementary, triadic, split, mono, kelvin), shared with the V3.3 quality rules. Named colour / palette deletes refused while used |
| Alerts (V3.1) | `alerts.py`: one alert per status-bar device; each drop-out is an episode. Dismiss holds for the episode; clears on recovery; snooze 10 min / 1 h / gig; info alerts list-only; critical (engine fault, output down, all outputs lost) minimise only and can't be muted or snoozed. Mutes per rig in app data `alerts.json`, cleared on rig switch. Quiet mode: critical banners only. Log `logs/alerts-YYYY-MM-DD.jsonl`. Banners are fixed-position over the page. Claude reads only |
| Step scenes (V3.2) | `type: steps` scene: step_s / step_beats / fade_s defaults and per-step overrides; step time is the whole step, fade included (a fade longer than the step is cut to it); playback loop/once/bounce; advance timer / manual / {input}; `set` per light or group takes the static layer keys (no dimmer, no haze); tracking by laying every earlier step's set under the current one. move dark: dim out, move, fade in, at least `dark_s` (0.3 s) on a cut; move lit: eased linear glide, speed channel 1.0 (fastest); default from the profile (master_gate = dark). Head limits are a box, so glides between in-limit points stay in; ends outside are clamped along the edge. Live speed (0.05-8, faders 0.25-4) scales the step clock; fade scale (0-8) scales fades. The newest step scene drawn is the one pedals and inputs move (steps.active) |
| Classification (V3.3) | `classify.py`: head (pan+tilt, not colour-only), pixel, strobe (no RGB, white or strobe), effect (wheel/gobo, no RGB), else wash; MASTER-exempt lights are class kick and never used; haze never. Rig `auto: {classes, exclude}` overrides (a head must be able to move, a pixel class needs pixels). Left/right halves from the layout |
| FX banks (V3.3) | `fxbanks.py` items = registry effect templates with needs (heads, colour lights, pixels, lights), busy 0-1, speed still/slow/mid/fast, moods. compose(pick) -> scene: colour item over colour lights (pixel items on the bars, the rest hold the palette), strobe lights white at 60 %, effect lights the first colour, move item on heads, drum item on top (blend max); then parse_scene, so every rule applies. Flash FX are engine overrides (kind `fn`), timed or held, never on exempt lights or haze |
| Ride controls (V3.3) | speed 0.25-4 divides periods (rates multiply), fan sets spread, size scales movement size / pixel width / sparkle density, shift sets layer `shift` (phase), fade picks fading chases and the crossfade time (fade x 4 s). Per-bank settings ride on the global ones |
| Quality rules (V3.3) | `quality.py` defaults, overridden by `quality.yaml` (kind quality): max_busy 1.3, lead_busy 0.55 (no two leads), mood speeds, speed_gap 1, contrast (move or colour item change, or palette main hue >= 0.1 round the wheel), palette theory + no muddy, autopilot weights. Manual Ride picks are played with quality notes; the autopilot (V3.4) and generator (V3.5) skip failing picks |
| Drum bus (V3.3) | Named input note hits with roles go to `drums.BUS` (time, roles, strength after the velocity curve), kept 30 s; effects read it at the engine clock (`Run.now`) |
| Autopilot (V3.4) | `autopilot.py`; rig `autopilot:` over defaults (moods 60/40/20 s, variation 0.2, no_repeat 4, fade 4/2/0.5 s, energy window 4 s full at 6 hits/s, fill 5 snare/tom hits within 1.2 s then a crash within 1 s, gap 4 s, count-in 4 even hits 0.2-1.5 s apart). Energy = 0.65 rate + 0.3 strength + 0.1 when kick and snare both play. Mood hysteresis low>mid 0.42, mid>high 0.72, high>mid 0.55, mid>low 0.25. Candidates: 320 seeded random picks from the rig's available items for the mood; skip banned, recent, quality failures and non-contrasting; score by weights (mood, busy near the mood's target, ratings) + a random tie-break. Build/breakdown = energy +-0.35 against 8 s ago, at least 6 s after the last change. Picking a show/scene/look by hand turns it off; a Ride page pick keeps it on and restarts its timer. Runs on its own thread every 0.1 s; tests tick it on a fake clock |
| Between songs (V3.4) | No `activity` input for gap_s -> talking look (low-mood fade); a count-in or any activity -> a new look at once. Setlist load = walk-on, next song past the last = walk-off (when the autopilot is on) |
| Control priority (V3.4) | Levels: blackout, MASTER off (gated profiles), Flash FX/busk overrides, hold, autopilot/show. Rig `release_fade_s` (default 0 = cut, as before): MASTER on and blackout off ramp the rule layer's gate 0-1 (exempt lights too after a blackout); held Flash FX release with that fade |
| Decision log (V3.4) | Each change: time, energy, mood, trigger (timer, fill_crash, mood, build, breakdown, song_end, song_start, walk_on/off, next, previous, start), look, reason, candidates and rejections; last 500 in memory, all in app data `logs/decisions-YYYY-MM-DD.jsonl`; on the Ride page and through Claude |
| Ride page (V3.4) | New left-menu page. Learn arms MIDI learn for the control's action and saves the map when learned. Classification overrides write the rig's `auto:` |
| Presets (V3.5) | `presets.yaml` {presets: {id: {name, tags, pick}}} + six built-in starters (same id replaces). Composed per running rig at load as scenes `preset:<id>`; show steps `{preset: id}`, setlist songs `{preset: id}` or `{presets: [...], mood}` (autopilot limited to them: no show or scene allowed). Song `mood` and `bpm` are optional, for the generator. Delete refused while a show or setlist uses it; starters can't be deleted |
| Ratings and review (V3.5) | `ratings.yaml` {looks: {"move|colour|drum|palette": 1 / -1 / -2}}. Autopilot and generator skip -2, weight +2.5 liked, -4 disliked. Review list = palettes x colour items x (no move + move items) the rig can do, in a fixed order, paged |
| Generator (V3.5) | `generator.py`, seeded (default: the time). Styles limit items, palettes by tag and ride feel (rock, ballad, acoustic, opera, dance). Picks pass the quality rules, contrast with the one before and skip repeats; re-roll keeps locked parts (move, colour, drum, palette, ride); more-like-this keeps the FX and varies palette and ride. Shows: one set `song`, a scene per distinct section, step hold = hold_s x length / 2 with a 2 s fade. Per song: intro/verse/chorus/verse/chorus/outro, 8 bars of 4/4 at the song's BPM (30 s without). Everything written in one checked store change; existing files refused unless overwrite. Capture: a Ride/autopilot look as its composed layers (same frame as live), anything else as a still of every light |
| Connect to Claude (Setup page) | `claude_setup.py`: Claude Desktop configs (standard and Store) and Claude Code `~/.claude.json`, entry `dmx-suite` = the console exe (`dmx-suite.exe` beside the windowed one) or Python, `--shows <the open .dms or folder> mcp`. Status per app: installed, registered no/current/other, which show. Connect writes only to apps that have been opened; Disconnect removes the entry; others kept, `.bak` beside. API `/api/claude` (status, cached 30 s), `/api/claude/connect|disconnect` from this computer only, never with Claude's token. Status bar Claude tile opens the section |
| File format 5 (V3.1) | No single-file changes; `ShowStore.upgrade` runs `migrate.py` once on a format-4 folder: raw mappings -> named inputs (GM drum names on ch 10, one input per message across every map), tempo kick note -> a kick-role input, palette positions -> rig points. Golden frames and a MIDI replay are identical before and after |
| v4 renames (format 6) | `ride` -> `feel`, `bank_ride` -> `bank_feel`, MIDI `busk` -> `override`, `ride_fx` / `ride_palette` -> `autopilot_fx` / `autopilot_palette`, `ride_<x>` -> `feel_<x>`; old names read, new written; `panels.yaml` kept |
| v4 routing | Every output has `universe:` (missing = 0 + warning; the format 6 step doesn't add it); drivers `usb_dmx_open` / `usb_dmx_pro` / `node` (old ids alias); outputs rebuilt live |
| v4 devices | Known by `usb:VID:PID:SERIAL` (else `port:COMx`, flagged), MIDI by port name; "use this instead" allowed under gig lock, nothing else; Claude can't make the swap |
| v4 Monitor | Shows the selected interface's last-sent frame, never the engine's unless chosen and labelled; no frames = no values |
| v4 pixel selection | `fid:px..`, `group:px..`, `odd/even/firstN/lastN`, pixel groups in `fixtures.yaml` (not the rig); colour only (rule 1) |
| v5 Open DMX break methods | Per output `break_method`: `serial_break` (COM port break request), `baud_drop` (0x00 at 9/break_us baud, then 250k), `d2xx` (FT_SetBreakOn/Off through ftd2xx via ctypes, offered only when installed and the interface's serial number is known), `auto` = d2xx if available else serial_break. `break_us` 88-1000 (176), `mab_us` 8-100 (12), `fps` 1-44 (40), `channels` 24-512 or `patched`. Missing = defaults, no warning. Break / MAB / fps / write time / jitter measured on the laptop, amber under 88 µs / 8 µs / 80 % of target; baud_drop's break is computed from the baud rate. A new frame still goes as soon as the line is free (rule 2). Decided 28/11/2026 |
| v5 test patterns | Monitor page: all full, fixture chase, find fixture, channel ramp/hold, keep-alive, to one universe (every interface carrying it) or one interface. Replaces that universe's frame after the rule layer, so scenes, autopilot, Override, grand master and MASTER are bypassed (operator test, like find fixture); the show keeps rendering underneath. Head limits (rule 8) and U'King home (rule 7) still hold; haze always 0 (rule 5, no tick to include it); all full lights emitters and dimmers only, function channels (strobe, mode, macro, gobo) stay at defaults so strobe is off; ramp refuses haze and pan/tilt channels. Stops on Stop, page leave or timeout (60 s default, 600 max). Gig lock: keep-alive only; stop always allowed. Start/stop logged, status bar shows TEST. Decided 28/11/2026 |
| v5 cycle test | USB DMX (Open) outputs only. Steps: d2xx (only if installed and it sees the interface), serial_break, baud_drop at the output's break_us, then a long 500 µs break; 5 s each, one pass, all full running on that output only. "Lights responded" saves the live step's break_method and break_us to the rig (other settings kept); no tap or Stop puts the output back unchanged. Claude: test_output_methods waits for the result, or save_step N when the band names the step in chat. Not under gig lock. Decided 28/11/2026 |
| v5 output checks | Per USB DMX (Open) output: driver (VCP / D2XX), FTDI latency timer (Windows FTDIBUS `LatencyTimer`, Linux sysfs, D2XX; > 1 ms amber, set to 1 ms here only through D2XX after a confirm, people only, not Claude), port held by another program (red, names Daslight / QLC+ / FreeStyler / MagicQ from the process list), 250k 8N2 on the open port, USB selective suspend (power plan via powercfg, interface `SelectiveSuspendEnabled` / `EnhancedPowerManagementEnabled`; value names to confirm on the gig laptop, unknown when absent), measured timing. Run at start, on hot-plug, after outputs change and every 60 s, off the engine thread. Warn / fail → a status-bar tile (`dmx_check`) and alert, reason and fix on hover; shown in the routing table and Monitor. A missing port is the output's own red state, not an exclusivity fail. Decided 28/11/2026 |
| v5 fault-find | One tree (faultfind.py) for the Monitor wizard and Claude's `fault_find`. Interface checks first (a fail stops with its fix), then "lights in auto / sound mode?": yes = cycle, bypass wireless, lead / 5-to-3-pin adaptor, IN not THRU, another program (QLC+ / FreeStyler), suspect the interface; no = pick the dark light, live-frame zero flag first, then find fixture, address, channel mode, chain / termination, live values. Every step asks "does it work now?": Pass ends (found), Fail moves on. Read-only apart from the tests it starts; tests off under gig lock. Summary copyable and logged. Decided 28/11/2026 |
| v6 darkness / lit | Per-layer `lit:` 0-100 % (scene-level default; step `set` per light). Not `fill:` (fill means drum fills: Part B). Colour effects shape their own black (linear_wave / radial / bars: band = lit of each cycle round the peak; colour_chase / colour_fade / drifting palette: black slots spread evenly, starting with a colour; gradient / rainbow: segments squeezed into lit of their slot; still palette / split / static colour: regular pattern `static_on`, moving with shift; dir_sweep: band narrowed); other colour effects get the static pattern from Run. Darkness only for Autopilot looks (ScenePlayer gets it from `ride_play`); hand-made scenes and shows as authored; Override above it. Exempt (kick) lights keep the layer's own lit. Black = colour 0; a light blacked this way keeps its dimmer (only colour changes, brief acceptance), so rule 4 holds by colour; dimmer-only lights go dark by brightness. Unlit units are marked on the look so a MASTER-off drum flash skips them. Soft edge = the look's feel fade. Darkness eases over 0.15-2 s (fade). Rig `autopilot: darkness` + `set_darkness {low, mid, high}` (%), loaded on mood change; slider / CC / Claude hold until the next change. CC: input role `darkness` (CC/OSC only) with `range` [heel, toe] % and the calibration curve, or the `darkness` map action. No darkness preview in the step editor (darkness never applies to hand-made scenes); preview_look has one. Decided 28/11/2026 |
| v6 tempo from the drums | New roles `hat` and `tap` (ROLES); shipped TD-25 / GM hi-hats get `hat`. Tracker weights per role (kick 1, snare 1, hat 0.5, tom 0.6, cymbal 0.4), merge 30 ms (strongest weight), velocity floor 30. Comb score = mean of the beat and half-beat resultants (eighth hats don't cancel the beat); confidence = share of hit weight on a narrow beat tooth x recent-beat coverage, so kick/snare over 8ths or 16ths hats lock and an even tom fill freewheels. Bar: snare 2/4 from on-beat snares, beat 1 = the non-backbeat with more kick velocity. Output phase corrected by rate, so effect time is continuous (switching sources and re-seeding included). No seed = no drums tempo (tap, FCB tap, tap pad or count-in). Live params via API / Claude, saved to the rig `tempo:` block on request. Input Monitor Tempo pane: lanes, beat grid, raw vs output BPM, confidence, seed source, settings. Decided 28/11/2026 |
| v6 drum kits | `inputs.yaml` `kits: {id: {name, channel (10), port, pieces: {id: {name, zones: {id: {input, notes, role, weight, velocity_floor, tempo, flash, trigger, colour, curve, velocity}}}}}}` + `active_kit`. Roles kick / snare / hat / tom / cymbal / tap / count_in (`count-in` read) / trigger_only; drum roles add `activity`, count_in keeps `activity`, tap and trigger_only add nothing. Each zone of the active kit is a named input (id `input`, default piece or piece_zone; a zone with no notes yet makes none), so map entries, step scenes and the auto show keep their ids; inactive kits make no inputs. The kit owns drum flash targets: they become in-memory MIDI map entries (`from_kit`, never written to the map file; a pad the map file maps keeps the file's mapping). Triggers (scene / preset / flash_fx) fire from the input listener. Zone weight / floor / tempo flag go to the tracker. A show without kits: `band_kit` is a view of the device with most drum-role note inputs plus their map flashes; the first kit save migrates (drum inputs move from the device into the kit, emptied device removed, their flash mappings removed from the map) in one store change, which backs up inputs.yaml and the MIDI map. Learn: arm a zone, the next note is its note (removed from any other zone). Unmapped = notes heard on the kit channel in the last minute that no zone has. Export / import as YAML (`kit: id` + kit). Same format 6 (kits are new sections). Decided 28/11/2026 |

Open:

- [ ] Drum flash map: which pads flash which fixtures. v6: set per pad in the Drum Kit (the kit owns flash targets); the shipped targets are still placeholders until the band sets them
- [ ] Fixture channel maps and DMX addresses: copy from the Daslight patch into `shows/fixtures.yaml` (all `verified: false`)
- [ ] FCB1010 program change numbers: copy from Daslight into `shows/midi/default.yaml`
- [ ] MH-A tilt limit value (placeholder 75 % in `shows/rigs/full.yaml`)
- [ ] Daslight import: need a sample Daslight show/patch file to read its format
- [ ] Palette positions and gobo values (`shows/palettes.yaml`): set at rehearsal
- [ ] Rehearsal: tune auto-show styles (colours, step times, energy) and write the real setlist
- [ ] Brand assets: replace `dmx_suite/web/static/themes/005/logo.svg` and `theme.css` (placeholders now); app icon `static/brand/icon.svg`; CoreS3 boot logo
- [ ] Light layout: arrange the real layout at rehearsal (Layout page); set pan_range/tilt_range per head type and calibrate palette positions so beam lines point the right way
- [ ] Phase 2: node fallback look only covers the node's own universe; receivers on other universes go black 5 s after the laptop stops. Decide whether each universe needs its own fallback
- [ ] Phase 2: SamplePad note numbers and pad map, H2MIDI Pro port name, guitar board MIDI (generic PC/CC/notes already supported)
- [ ] 0.05 brand assets: logo files (SVG preferred), colours, font
- [ ] Unit DMX (U183) wiring: confirm TX/RX pins and whether a direction (DE/RE) pin is needed, before first flash (`firmware/include/config.h`)
- [ ] Node status: CoreS3 screen (0.05 logo, status) not built yet; identify on the node only logs
