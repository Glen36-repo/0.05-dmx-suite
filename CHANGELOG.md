# Changelog

Notable changes, newest first. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/).

## Unreleased (UI tidy)

### Changed
- Scene builder: the lights in the picker are about twice the size and fill the box; the group buttons show how many lights each has, with **None** and **Invert**. On a phone the picker scrolls sideways rather than shrink the lights.
- Live and Ride: the lights fill the picture; scenes sit on their own line under the shows.
- The menu is grouped (Perform, Build, Rig, System). On a phone the bottom bar has Live, Ride, Busk, Scenes and Shows, and **More** opens the other pages (before, four pages couldn't be reached).
- Ride: smaller FX buttons with the colour bank four wide, so the page is about 15% shorter.
- MIDI: each named input fits on one line (long mappings are cut short; hover for the full text); the full mapping table is folded away.
- Setup: Devices and Nodes side by side; Addresses folded (its summary stays in the heading); Connect to Claude folds away once Claude is connected.
- Heads: each point on one line. Shows: short settings side by side. Review: the generator folds away.
- Phones: the top bar fits on one line and the status strip shows just the lights.

### Fixed
- Fixtures: the empty red bar under the patch no longer shows when nothing clashes.
- MIDI: the TD-25 buttons no longer run off the side of the card.

## Unreleased (Connect to Claude)

### Added
- Setup page: Connect to Claude, with a checklist for a new laptop, whether Claude Desktop and Claude Code are connected to this show, Connect / Update / Disconnect, and when Claude last checked in. The status strip's Claude light opens it.
- Claude Code is connected too (`~/.claude.json`), not only Claude Desktop.

### Fixed
- Alert banners no longer cover the status strip.
- The setup wizard no longer redraws over the next step when the port scan answers late.
- The Scenes page ignores taps made while it's still loading.

## Unreleased (v3, release V3.5)

### Added
- Presets: save a Ride look, play it from the Ride page or a pedal, use it as a show step or setlist cue, or limit the autopilot to some presets for a song; six starter presets.
- Look review page: every look the rig can do, filtered by mood, bank or palette; thumbs up / down or ban; auto-advance; open a look from the decision log. The autopilot and generator favour liked looks and never use banned ones.
- Generator: scenes from a mood, style and palette; a show from a mood plan; a starter show for every song in a setlist (from its mood and BPM); plain YAML with a `generated:` note; same seed, same files.
- Lock and re-roll, "more like this", and save the current look as a scene, on the Ride page.
- Claude: generate scenes and shows, list and save presets.

## Unreleased (v3, release V3.4)

### Added
- Ride page: autopilot, mood, hold, previous/next look; Move FX, Flash FX and Colour FX banks with big touch targets; drum FX; palettes with a lock; ride faders for everything or per bank; haze controls alongside; layout strip; "Why did it do that?"; lights in the auto show; Learn any control from a pad or pedal.
- Autopilot: looks change on a timer per mood (low 60 s / mid 40 s / high 20 s, with variation), no repeats, contrast with the last look; energy from named input roles (MIDI only); mood follows the energy or a pedal; fill + crash changes early with a colour hit; build and breakdown; pauses while MASTER is off.
- Between songs: silence fades to a talking look, a count-in or first hit starts the show again; walk-on and walk-off looks from buttons or the setlist.
- Control priority (blackout > MASTER-off drum flash > Flash FX and busk > hold > autopilot / show) shown on the Ride page; `release_fade_s` fades back in when a higher level lets go.
- Decision log: every look change with its reason, on screen and per gig in app data.
- MIDI/OSC actions for all of it; Claude can read what the autopilot is doing and why, and tune its settings.

## Unreleased (v3, release V3.3)

### Added
- Auto classification: every light sorted into head, wash, pixel, strobe, effect or kick by what it can do; override or leave lights out per rig (`auto:`). Haze never joins.
- FX banks: Move FX (13), Colour FX (23), drum-reactive (6) and Flash FX (8), each with what it needs, how busy it is, its speed and moods. 18 new registry effects, also in the scene builder.
- Drum-reactive effects driven by named input roles (kick pump, snare hit, tom roll, cymbal shimmer, fill build, velocity colour).
- Flash FX from pads and pedals (`flash_fx`): blinder, colour hit, strobe, blackout, freeze, flash and decay, chase hit, rig split hit.
- Ride controls: speed, fade, fan, size, shift, global and per bank; layer `shift` (phase offset) on any effect.
- Look quality rules as data (`quality.yaml`): busy scores, one lead at a time, mood speeds, speed matching, contrast between looks, palette theory.
- Rig size scaling: only what the rig can do is offered.
- Claude: list the FX banks, preview a look with its quality notes, read and tune the quality rules.

## Unreleased (v3, release V3.2)

### Added
- Step scenes: steps programmed by hand with a step time and fade time each (or the scene's), tracking (a step only sets what changes), loop / once / bounce, next step on the timer, a pedal or a named input (e.g. every snare hit), beats with beat sync.
- Heads move dark (the 0.05 band default) or glide lit (the generic default), per scene or step; glides are 16-bit with the head's speed channel at fastest, and stay inside the head limits.
- Step scene editor in the scene builder: set the selected lights, capture what they show, add/duplicate/reorder steps, preview one step, play from a step; effects on top.
- Live step speed and fade faders (busk faders and MIDI `step_speed` / `step_fade`), and `step_next` / `step_back` actions.

## Unreleased (v3, release V3.1)

### Added
- Named inputs: define each pad, pedal, key or OSC control once (`inputs.yaml`), grouped into devices, with roles (kick, snare, tom, cymbal, count-in, activity), velocity range and calibrated velocity curve; MIDI maps name them. Learn an input from the gear; device profiles for the TD-25, SamplePad 4, FCB1010 and GM drums; save your own.
- Head points: named aim points per rig config with a description, tags and a rough stage place; store held heads to a point on the Heads page, fine mode, focus mode and a re-focus walk.
- Colour wheel: hue/saturation, brightness, hex and RGB, white/amber/UV for lights that have them, white temperature presets, recent and named swatches, pick from a light, what each light can make, live preview.
- Palettes page: palettes with tags (seven built in), generate from a colour by colour theory, preview on the rig, rename, duplicate, import and export; named colours renamed everywhere at once.
- Alerts: banners over the page (no layout jumps) with dismiss, snooze and minimise; a bell with the alerts list; mute a device for this rig; quiet mode; critical alerts can't be dismissed while they last; an alerts log.
- Claude: list and edit inputs and head points, read alerts; the guide explains inputs and points.

### Changed
- Show file format 5: MIDI mappings become named inputs and palette positions become head points in each rig, once, with a backup. Everything looks and reacts exactly as before.
- MIDI learn makes (or reuses) a named input.
- Deleting a named colour that's in use says where it's used.

## Unreleased (v2, release R8)

### Added
- Node firmware 0.2: fallback looks for up to 4 universes, sent by the app whenever the node connects (each universe's static look); fallback, blackout and keep-alive reach every universe.
- Radio channel: move the node and its receivers from the Setup page or the rig file; receivers that missed it find the node again by themselves.
- Node status screen on the CoreS3 (mode, universe, frame rate, receivers, channel, firmware, warnings); identify and tap flash it.
- Replace a dead node or receiver with a spare from the Setup page.
- Warnings for old node firmware, the development pairing key, and a DMX output that didn't start.

### Changed
- Naming a node or receiver waits for it to confirm, and says if it didn't.
- Requests to the node carry an id, so a late answer can't be taken for the wrong request.

### Fixed
- Receivers on a two-universe rig no longer report about 50 % packet loss.
- Receivers on other universes no longer go dark 5 s after the laptop goes away; they run their fallback look.

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
