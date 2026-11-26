# 0.05 DMX Suite

General-use live lighting software for Windows: build scenes and shows on screen, run them from MIDI or OSC, output DMX through USB interfaces, Art-Net/sACN or the 0.05 nodes. The band 0.05 is the reference setup (replaces their Daslight 5): MIDI in (FCB1010 pedal board, Roland TD-25 drums, later Alesis SamplePad) drives DMX out to an M5Stack CoreS3 SE + Unit DMX node over USB serial, which relays to wireless AtomS3 Lite receivers.

Full requirements: `docs/SCOPE.md`. Read it before starting any task. If something here conflicts with it, SCOPE.md wins; flag the conflict.

## Stack
- Python 3.12, Windows 11 target. Develop cross-platform; no Windows-only calls outside output drivers and the desktop shell.
- `mido` + `python-rtmidi` (MIDI), `pyserial` (node + Enttec), `PyYAML` (show files; `ruamel.yaml` for comment-keeping saves from v2 R1), `pytest`.
- UI: standard-library web server + HTML/JS (plain ES modules, no build step, works offline), shown in the desktop window (pywebview/WebView2, tray icon) and in phone browsers.
- Windows installer: PyInstaller + Inno Setup, built by GitHub Actions (`installer/`).
- Node firmware: `firmware/`, PlatformIO, Arduino framework, M5Stack CoreS3 SE / AtomS3 Lite + Unit DMX (U183).

## Cloud session limits
- No MIDI devices, DMX hardware or USB in this environment. Everything must run in **simulator mode**: fake MIDI input, a `null`/`log` output driver, and tests.
- Firmware must compile (`pio run`); it can't be flashed here.

## Rules (enforce in the rule layer, test every one)

Numbers are kept from v1 so tests and docs still match. From v2 R1, every rule is tested under both shipped profiles ("Generic" and "0.05 band").

**Safety rules: always on for every user; scenes and profiles can't turn them off.**

4. No background glow: any channel not in the active effect is fully off (0).
5. HAZE is never set by scenes or auto shows; only the Haze controls.
6. Grand master scales intensity only: never pan/tilt, colour choice or haze.
8. Moving head pan/tilt limits from the active rig config are always enforced.

**Profile rules: settings in the rig config's profile. "0.05 band" turns all three on; "Generic" uses standard dimmer behaviour with no drum flash.**

1. MASTER owns on/off. Scenes never set dimmer channels; on/off inside a scene is done through colour channels.
2. MASTER off → mapped drum hits flash the rig, then cut to black. A hit sends a frame immediately, not on the next 40 Hz tick.
3. Fixtures excluded from MASTER (0.05: the kick-drum light) are never affected by it.

**Fixture definition:**

7. Colour-only heads and speed-channel direction are set per fixture type (0.05: U'King heads are colour only; MHL36 pan/tilt speed channel 0 = fastest). From v2 R7 the type also sets colour mixing (`colour_mix`; the 0.05 types are `off`), wheel/gobo slot names and inverted channels.

## Conventions
- Australian English in UI text and docs. Metric. Dates DD/MM/YYYY.
- Show data in YAML under `shows/`: fixtures, rig configs, palettes, effects, scenes, shows, MIDI map. Every file carries `version:` from v2 R1. Users keep it as one `.dms` show file (zip of those files, `dmx_suite/package.py`) from v2 R6; every loader still works on a folder (the app runs on an unpacked working copy).
- Everything a user needs must be doable in the UI; Claude (MCP) is optional.
- UI text lives in `web/static/i18n/en.json` from v2 R2; no hard-coded strings in views.
- Output drivers are pluggable (`node_serial`, `enttec_open`, `enttec_pro`, `artnet`, `sacn`, `log`, `null`).
- Small commits, one feature each, with tests. Update `docs/SCOPE.md` decisions if a design choice changes; user-visible changes go in `CHANGELOG.md` and `docs/manual/`.
- Before committing: `ruff check dmx_suite tests installer`, `mypy dmx_suite`, `pytest`; `pio run -d firmware` if firmware changed (CI runs all four).
- Show file format changes: bump `FORMAT` in `dmx_suite/versions.py` and add an upgrade step with a test.

## Phase order
v1 (built):
1. Node link (firmware + serial protocol + heartbeat/discovery)
2. Engine core (fixtures, 40 Hz loop, MASTER/blackout/haze, hard rules, MIDI in, drum flash, grand master, Open DMX output, MIDI monitor/learn, simulator)
3. Effects and scenes
4. Auto shows, setlist mode
5. Browser UI and MCP server
6. Phase 2 MIDI, second universe

v2 (general release; details in `docs/SCOPE.md`):
- R1 Rule profiles (first), file versions, engine safety, comment-keeping store, project basics, CI
- R2 Left-hand menu, grid light layout, groups, themes, strings file
- R3 Effect registry, spatial effects, spread, scene builder
- R4 Non-blocking outputs, Art-Net/sACN, OSC input, thread safety
- R5 Crossfades, show steps (repeats, fades), show/setlist builders, beat sync, Busk page
- R6 PIN/LAN security, gig lock for Claude, live feed, undo/redo, copy/paste
- R7 Fixture model and editor, OFL import/export, setup wizard, starter shows
- R8 Node and firmware fixes
- R9 Rehearsal sign-off on the real rig

v3 (auto show "Ride"; details in `docs/V3-SCOPE.md`):
- V3.1 Named MIDI inputs, head position points, colour wheel + palette editor, alerts/banners
- V3.2 Step scenes (move dark/lit)
- V3.3 Classification, FX banks, ride controls, look quality rules, rig scaling
- V3.4 Autopilot, Ride page, between songs, control priority, decision log
- V3.5 Generator, look review page, presets, Claude MCP tools

Haze is never touched by the autopilot, presets, generator or Flash FX. Every v3 feature gets rule tests under both profiles (`tests/rulecheck.py`).
