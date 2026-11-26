# Changelog

Notable changes, newest first. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/).

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
