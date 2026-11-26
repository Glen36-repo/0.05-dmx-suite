# 0.05 DMX Suite — Scope

Nov 26, 2026 · @Glen Mahony

## Purpose and goals

Replace Daslight 5 and the LR512 with a self-built show engine on the laptop, driving the band's own ESP32 DMX nodes over USB. No subscription, no locked hardware, and the show rules are written into the software instead of worked around.

- Run the band's rig live from MIDI (FCB1010, TD-25, SamplePad) with no operator at the laptop
- Automatic shows that follow the band's lighting rules out of the box
- Laptop talks straight to the CoreS3 node by USB serial; node handles DMX out and wireless to the receivers
- Simple enough for one person (Glen) to maintain, edit and fix at a gig

Out of scope for v1: video, timecode, audio-reactive BPM, multi-universe, and a general-purpose fixture editor.

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

The engine enforces the rig rules itself, so no look can break them.

**Hard rules (engine-level):**

- MASTER owns on/off; scenes never set dimmer channels, only colour
- MASTER off → drum hits flash the rig (see Drum flash, priority feature)
- MASTER does not affect the kick-drum light
- No background glow: any channel not in the active effect is fully off
- HAZE is never set by scenes or auto shows; it runs only from the Haze controls
- Kick light bright most of the time, follows the active effect on bars or movers
- U'King heads colour only; MHL36 speed channel 0 = fastest

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
| Art-Net / sACN | Network nodes, later | Any network DMX node |

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
| Moving U'Kings in scenes | A movement layer that includes a colour-only head is rejected at load, not silently skipped |
| Heads move dark | `random_move` has `dark_move_s`: the head is blacked (via colour) for that long after each new position |
| Find fixture | Lights the one fixture full white, ignoring MASTER, grand master and the kick light; head limits still apply |
| Channel tester | Raw values over the show output until cleared; refuses the haze channel |
| Missing fixtures in a scene | Skipped for now; moving their effects to fixtures that are present comes with auto shows (phase 4) |
| Fixture import | Open Fixture Library JSON first (`dmx-suite import-ofl`); always lands as `verified: false` |
| Setup page | Console commands for now; the browser page comes in phase 5 |
| Auto shows | Generated per step from a style (colours, energy, head mix, patterns, movement), deterministic per seed, checked against the hard rules like any scene |
| Set steps | Fixed timers (`step_s`); tap tempo changes effect speed only, never step length |
| Tap tempo | Effects are timed at 120 BPM reference; a tapped tempo (pedal or a mapped drum note) scales effect time and lines up on the tap |
| Set pedal outside a show | LOW / MID / HIGH goes to the current show if it has that set, otherwise the first show that does |
| Resume after restart | Live runs save show/set/setlist song/MASTER to `shows/.state.json` on every change; restored on start if under 12 hours old |
| Missing fixtures in shows | Auto shows only use fixtures in the rig; hand-written scene layers can name a `fallback` group |
| Kick light in auto shows | White most steps, the show colour about 30 % of steps |

Open:

- [ ] Drum flash map: which pads flash which fixtures (later). `shows/midi/default.yaml` has GM drum-note placeholders
- [ ] Fixture channel maps and DMX addresses: copy from the Daslight patch into `shows/fixtures.yaml` (all `verified: false`)
- [ ] FCB1010 program change numbers: copy from Daslight into `shows/midi/default.yaml`
- [ ] MH-A tilt limit value (placeholder 75 % in `shows/rigs/full.yaml`)
- [ ] Daslight import: need a sample Daslight show/patch file to read its format
- [ ] Palette positions and gobo values (`shows/palettes.yaml`): set at rehearsal
- [ ] Rehearsal: tune auto-show styles (colours, step times, energy) and write the real setlist
- [ ] 0.05 brand assets: logo files (SVG preferred), colours, font
- [ ] Unit DMX (U183) wiring: confirm TX/RX pins and whether a direction (DE/RE) pin is needed, before first flash (`firmware/include/config.h`)
- [ ] Node status: CoreS3 screen (0.05 logo, status) not built yet; identify on the node only logs
