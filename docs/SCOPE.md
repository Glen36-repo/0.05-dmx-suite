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

Out of scope: video, timecode and audio-reactive BPM (v1 and v2); macOS/Linux builds.

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
| Fixture import | Open Fixture Library JSON first (`dmx-suite import-ofl`); always lands as `verified: false` |
| Setup page | Setup tab in the UI (phase 5); console commands kept |
| Auto shows | Generated per step from a style (colours, energy, head mix, patterns, movement), deterministic per seed, checked against the hard rules like any scene |
| Set steps | Fixed timers (`step_s`); tap tempo changes effect speed only, never step length |
| Tap tempo | Effects are timed at 120 BPM reference; a tapped tempo (pedal or a mapped drum note) scales effect time and lines up on the tap |
| Set pedal outside a show | LOW / MID / HIGH goes to the current show if it has that set, otherwise the first show that does |
| Resume after restart | Live runs save show/set/setlist song/MASTER on every change to app data (`%LOCALAPPDATA%\0.05 DMX Suite\state`, one file per show folder; v1's `shows/.state.json` is moved there once); restored on start if under 12 hours old |
| Missing fixtures in shows | Auto shows only use fixtures in the rig; hand-written scene layers can name a `fallback` group |
| Kick light in auto shows | White most steps, the show colour about 30 % of steps |
| Browser UI | Standard-library web server + server-sent events; no build step, no internet needed |
| UI access | Localhost only by default; `--lan` for phones, which need the token link; every change needs the token; Host header must be localhost or an IP (blocks DNS-rebinding) |
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
| Set steps (v2) | Fixed timers stay the default; a step can instead follow the tempo (`hold_beats` / `hold_bars`) |
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
| Thread safety (R4) | Locks on ShowController (RLock on every public method), App.reload, HealthTracker (records() copies), MidiMonitor (since() copies). Measured render cost 0.1-0.3 ms a frame on the full rig, so per-frame caching was left out |
| Profile in rig files | `profile: 0.05_band`, `generic`, or a block with `base` + `master_gate` / `drum_flash` / `master_exempt`; no `profile:` = v1 file, runs as "0.05 band"; drum flash needs `master_gate` |
| Intensity | Without `master_gate`, looks and scene layers may set `intensity` (0-1), scaled by the masters; with it, `intensity` is refused at validation (checked against every rig) and ignored by the rule layer. The raw `dimmer` key stays refused everywhere |
| MASTER-exempt fixtures | Fixture ids, groups or a kind name (`kick` = every kick-kind fixture, as v1); they ignore MASTER and drum flashes and use the rig's `kick_colour` when the scene leaves them off. Under "generic" nothing is exempt and a kick-kind light is an ordinary light (auto shows use it like a wash) |

Open:

- [ ] Drum flash map: which pads flash which fixtures (later). `shows/midi/default.yaml` has GM drum-note placeholders
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
