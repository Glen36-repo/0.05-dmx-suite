# 0.05 DMX Suite

Live lighting software for the band 0.05. Replaces Daslight 5. MIDI in (FCB1010 pedal board, Roland TD-25 drums, later Alesis SamplePad) drives DMX out to an M5Stack CoreS3 SE + Unit DMX node over USB serial, which relays to wireless AtomS3 Lite receivers.

Full requirements: `docs/SCOPE.md`. Read it before starting any task. If something here conflicts with it, SCOPE.md wins; flag the conflict.

## Stack
- Python 3.12, Windows 11 target (gig laptop). Develop cross-platform; no Windows-only calls outside output drivers.
- `mido` + `python-rtmidi` (MIDI), `pyserial` (node + Enttec Open DMX), `PyYAML` (show files), `pytest`.
- Browser UI later (phase 5): local web server, no cloud dependency.
- Node firmware: `firmware/`, PlatformIO, Arduino framework, M5Stack CoreS3 SE / AtomS3 Lite + Unit DMX (U183).

## Cloud session limits
- No MIDI devices, DMX hardware or USB in this environment. Everything must run in **simulator mode**: fake MIDI input, a `null`/`log` output driver, and tests.
- Firmware must compile (`pio run`); it can't be flashed here.

## Hard rules (enforce in the rule layer, test every one)
1. MASTER owns on/off. Scenes never set dimmer channels; on/off inside a scene is done through colour channels.
2. MASTER off → mapped drum hits flash the rig, then cut to black. A hit sends a frame immediately, not on the next 40 Hz tick.
3. MASTER never affects the kick-drum light.
4. No background glow: any channel not in the active effect is fully off (0).
5. HAZE is never set by scenes or auto shows; only the Haze controls.
6. Grand master scales intensity only: never pan/tilt, colour choice or haze.
7. U'King heads are colour only. MHL36 pan/tilt speed channel: 0 = fastest.
8. Moving head pan/tilt limits from the active rig config are always enforced.

## Conventions
- Australian English in UI text and docs. Metric. Dates DD/MM/YYYY.
- Show data in YAML under `shows/`: fixtures, rig configs, palettes, effects, scenes, shows, MIDI map.
- Output drivers are pluggable (`node_serial`, `enttec_open`, `enttec_pro`, `artnet`, `null`).
- Small commits, one feature each, with tests. Update `docs/SCOPE.md` decisions if a design choice changes.

## Phase order
1. Node link (firmware + serial protocol + heartbeat/discovery)
2. Engine core (fixtures, 40 Hz loop, MASTER/blackout/haze, hard rules, MIDI in, drum flash, grand master, Open DMX output, MIDI monitor/learn, simulator)
3. Effects and scenes
4. Auto shows, setlist mode
5. Browser UI and MCP server
6. Phase 2 MIDI, second universe
