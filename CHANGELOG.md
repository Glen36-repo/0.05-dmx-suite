# Changelog

Notable changes, newest first. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/).

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
