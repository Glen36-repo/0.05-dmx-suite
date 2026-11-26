# Changelog

Notable changes, newest first. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/).

## Unreleased (v2, release R7)

### Added
- Fixtures page: patch (add lights, auto-patch, overlaps marked, find, remove from every rig), fixture types (channel table, colour mixing, wheel and gobo slots, test each channel) and rig settings (profile, masters, lights in the rig, head limits, haze, tempo, outputs, inputs).
- Setup wizard on first run: DMX interface (spots the 0.05 node and Enttec interfaces), lights, rule profile, starter show, PIN.
- Starter shows made for any rig.
- Colour mixing for RGBW, RGBA, white-only, dimmer-only and colour-wheel lights; named colour wheel and gobo slots; zoom, focus, frost and prism; 16-bit dimmer, zoom and focus; inverted pan, tilt, zoom, focus and frost; a light can follow another sub-master than its kind's.
- Open Fixture Library: wheel slots, pixel bars and 16-bit channels on import; export a fixture type (`export-ofl`, Fixtures page).

### Changed
- Fixture and rig changes, and switching rigs, apply live without a restart (except outputs, MIDI inputs and OSC).
- Show file format 4: existing fixture types get `colour_mix: off`, so shows look exactly the same.

## Unreleased (v2, release R6)

### Added
- `.dms` show files: the whole show in one file, saved on every change, double-click to open; open, save as, new, download, upload and recent files on the Files page; `pack` and `unpack` commands.
- PIN for phones and other computers, with a sign-in page; phone/LAN access turned on from the Setup page, with the address and a QR code; optional PIN on the laptop too.
- Undo and redo for every change since the app started (Files page, Ctrl+Z / Ctrl+Y); Claude can undo its own last change.
- Copy and paste a look between lights in the scene builder (Ctrl+C / Ctrl+V).
- Lost-connection box; screens stay awake while the app is showing.

### Changed
- Claude has its own key and can no longer turn gig lock off or change settings; its edits respect gig lock even with the app closed.
- MIDI learn and removing a mapping are blocked by gig lock.
- Screens share one live feed and only get changes, with a heartbeat.
- `--lan` turns phone access on (needs a PIN) instead of printing a token link.

### Fixed
- Faders stuck after a finger slid off them mid-drag.
- Two "off" swatches in the scene builder; the group tab now follows the layer being edited.

## Unreleased (v2, release R5)

### Added
- Show steps: repeat a scene a number of times, hold for seconds, beats or bars, and fade into the next step; sets play in order or at random, looped or once.
- Crossfades between steps, and optionally when picking a scene, show or look (`change_fade_s`); busk releases fade back to the show.
- Shows page: build shows, sets and steps on screen; setlist editor.
- Live page: the set's steps (tap to jump), repeat count and time left, typed BPM, speed fader.
- Beat sync: tempo from tap, the kick drum or MIDI clock; layers timed in beats; speed control; tempo and beat pulse in the top bar.
- Busk page: your own panels of colour, flash, solo, effect, go, fader and haze buttons over the running show, each mappable to MIDI or OSC; Release all; held lights marked on the layout.

### Changed
- Changing tempo no longer makes effects jump.
- MIDI clock is no longer shown in the MIDI monitor.

## Unreleased (v2, release R4)

### Added
- Art-Net and sACN outputs, with a universe map; send to network nodes, visualisers or other software alongside USB.
- OSC input: map TouchOSC or desk faders and buttons in the MIDI map; OSC learn; OSC in the monitor and status bar.

### Changed
- USB outputs write on their own thread: a slow or unplugged interface can't hold up the show.
- Show control, node health and the MIDI monitor are safe to use from several places at once (MIDI, OSC, web, Claude).

## Unreleased (v2, release R3)

### Added
- Scene builder (Scenes page): pick lights on the layout, add layers, choose colours, positions, gobos and effects from forms, see it live on the rig, save.
- 11 new effects: rainbow, sparkle, wave, strobe, circle, figure 8, and across the layout: linear wave, radial, gradient sweep, bars, noise.
- Effects can run across the layout as one picture (`mapping: spatial`) and take direction, angle, groups and waveform settings.
- Layers mix with the layers under them (`level`, `blend`); layers can be muted; scenes have a length.
- Claude's guide lists every effect and its settings.

### Changed
- Effects are now a registry (`dmx_suite/effects/`); existing scenes look exactly the same.

## Unreleased (v2, release R2)

### Added
- Pages in a menu down the left (a bar along the bottom on phones); MASTER, blackout, gig lock and status stay along the top.
- Light layout: every light and pixel is a square with its live colour (Live page). The Layout page arranges them: select by tap, box, lasso or group; move, align, space out, make a row/ring/grid, rotate, lay out a bar's pixels; undo; save.
- Groups: make, change, rename (updates everything that uses the group) and delete from the Layout page.
- Themes: Neutral (default) and 0.05, picked on the Setup page.
- Tap a setlist song to jump to it; "Check for updates" on the Setup page.

### Changed
- Show file format 3: layouts are in grid cells; existing stage plans convert automatically.
- All UI text is in one strings file (`i18n/en.json`).
- Faders and head pads send at most 25 updates a second.

## Unreleased (v2, release R1)

### Added
- Rule profiles: rules split into safety rules (always on) and profile rules (per rig file). Profiles "generic" (standard dimmer behaviour, scenes may set `intensity`, no drum flash) and "0.05 band" (v1 behaviour).
- Show file format versions (`version:`): older files upgrade automatically at start-up with a backup; files from a newer app are refused.
- Saving show files keeps comments and layout.
- If the show folder won't load at start-up, the last good version from the backups runs and the status bar says so.
- Log file and resume state in app data (`%LOCALAPPDATA%\0.05 DMX Suite`), not the OneDrive show folder.
- `dmx-suite update-check` and `/api/update`: says if a newer version has been released (check only).
- MIT licence, contributing guide, code of conduct, issue and pull request templates, user manual (`docs/manual/`), CI (tests on Windows and Linux, lint, type-check, firmware build).

### Changed
- The output loop stays on a fixed 40 Hz grid; pedal sweeps and drum rolls no longer delay frames. A control change sends one frame, not two.
- Rendering errors never stop output: the engine falls back to the static look (or the last good frame) and shows the fault.
- Raw DMX values, times and levels in show files are checked when loaded; broken files are named in the error.
- MIDI map saves are validated and backed up like other edits.

## 0.1.0 (26/11/2026)

First version: phases 1-6 of `docs/SCOPE.md` (node link, engine, effects and scenes, auto shows, browser UI and Claude tools, second universe and SamplePad prep), Windows installer and desktop app.
