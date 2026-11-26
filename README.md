# 0.05 DMX Suite

Live lighting software for the band 0.05: MIDI in, DMX out, automatic shows, drum flash, and scene editing through Claude via MCP.

See `docs/SCOPE.md` for requirements and `CLAUDE.md` for development rules. The user manual is in `docs/manual/`; contributing: `CONTRIBUTING.md`; changes: `CHANGELOG.md`. MIT licence (`LICENSE`).

## Layout

| Path | What |
| --- | --- |
| `docs/PROTOCOL.md` | USB serial and ESP-NOW protocol (node link) |
| `shows/` | Show files: `fixtures.yaml`, `palettes.yaml`, `scenes/`, `shows/`, `setlists/`, `rigs/`, `looks/`, `midi/` |
| `dmx_suite/engine.py` | Show engine: 40 Hz loop, MASTER, blackout, drum flash, masters, haze |
| `dmx_suite/rules.py` | Rule layer: enforces the hard rules just before output |
| `dmx_suite/scenes.py` | Scenes: layered colour, effects (chases, flash, sweep, random move) and positions |
| `dmx_suite/ofl.py` | Fixture import from Open Fixture Library files |
| `dmx_suite/auto.py` | Auto-show generator (LOW / MID / HIGH, opera, acoustic styles) |
| `dmx_suite/shows.py`, `showctl.py` | Shows, setlists, tap tempo, resume after restart |
| `dmx_suite/desktop.py` | Desktop app: UI window (pywebview / WebView2) and tray icon |
| `dmx_suite/web/` | Browser UI and local JSON API (standard library, works offline) |
| `dmx_suite/store.py` | Validated, backed-up edits to the show folder (UI and Claude) |
| `dmx_suite/claude_tools.py`, `mcp_server.py` | Claude Desktop (MCP) tools |
| `dmx_suite/output/` | Output drivers: `node_serial`, `enttec_open`, `enttec_pro`, `artnet`, `sacn`, `log`, `null` |
| `dmx_suite/osc.py` | OSC input (UDP listener) |
| `dmx_suite/midi/` | MIDI map, router, monitor and learn |
| `dmx_suite/cli.py` | `dmx-suite`: run, simulator, MIDI monitor, show file check |
| `dmx_suite/node/` | Laptop side: protocol, link, health tracking, simulated node |
| `dmx_suite/tools/node_test.py` | Node test script (`dmx-node-test`) |
| `firmware/` | PlatformIO: `node` (CoreS3 SE) and `receiver` (AtomS3 Lite) |
| `installer/` | Windows installer: PyInstaller spec, Inno Setup script, `build.ps1` |
| `tests/` | pytest, including a byte-for-byte check of the firmware protocol code |

## Install (gig laptop)

Run `0.05-DMX-Suite-Setup-<version>.exe`. No Python needed. It asks:

- **Show file:** default `OneDrive\Music\0.05 DMX Suite\0.05 shows.dms` (Documents if there's no OneDrive). One `.dms` file holds the whole show; a new one starts from the starter shows. An existing file, or a show folder from an older version, is used as is. Upgrades and uninstall never touch it. Double-clicking any `.dms` opens it in the app
- **Add the 0.05 tools to Claude Desktop** (on by default): restart Claude Desktop afterwards
- **Desktop shortcut** (on) and **start live at login** (off)

**0.05 DMX Suite** opens as a desktop program in its own window (the same screens as the browser UI, so phones on the network still work). Closing the window hides it to the tray icon and the lights keep running; the tray menu has Open, Blackout and Quit. Opening it again while it's running brings the window back on the running engine. Show file problems at start-up are shown in the window; everything else is logged to `logs\desktop.log` next to the show folder.

Start menu: **0.05 DMX Suite**, **0.05 DMX Suite (simulator)**, show files folder, and under Tools: MIDI monitor, check show files, simulator console. The chosen show file is saved as the `DMX_SUITE_SHOWS` user environment variable, so `dmx-suite.exe` from a command prompt uses it too.

**Building the installer:** run the *Windows installer* workflow on GitHub (Actions tab → Run workflow, or push a `v*` tag) and download it from the run's artifacts. Or on a Windows PC with Python 3.12+ and Inno Setup 6: `powershell -ExecutionPolicy Bypass -File installer\build.ps1` → `dist\`. The build runs the tests and a check of the packaged app first. Bump `version` in `pyproject.toml` for each release.

## Setup (from source)

On the gig laptop (real MIDI ports, Claude Desktop tools):

```bash
pip install -e .[hw,claude,desktop,dev]
```

Desktop app window from source: `dmx-suite app` (add `--sim` for the simulator).

For development without MIDI hardware:

```bash
pip install -e .[dev]
```

```bash
pytest
```

## Running

Simulator (fake MIDI, no hardware). Type `help` at the `dmx>` prompt:

```bash
dmx-suite run --sim
```

Live, using the rig's outputs and all MIDI inputs:

```bash
dmx-suite run --rig full
```

```bash
dmx-suite midi-monitor
```

```bash
dmx-suite check
```

```bash
dmx-suite addresses
```

Start straight into a show, set or setlist:

```bash
dmx-suite run --sim --show band --set mid
```

```bash
dmx-suite run --setlist example
```

Live runs save what's playing to the app's own data folder (`%LOCALAPPDATA%\0.05 DMX Suite`, not the show folder, so it doesn't sync through OneDrive; logs go there too); if the laptop restarts mid-gig, `dmx-suite run` carries on with the same show/set or setlist song and MASTER state (state older than 12 hours is ignored; `--fresh` ignores it).

Import a fixture type from an [Open Fixture Library](https://open-fixture-library.org) file (prints YAML to paste into `shows/fixtures.yaml`; check it against the manual; the Fixtures page does the same on screen), or export one to share:

```bash
dmx-suite import-ofl fixture.json --mode 11-channel --key mhl36
```

```bash
dmx-suite export-ofl mhl36 -o mhl36.json
```

Shows (console): `show band high`, `set low`, `next` (next step), `now`, `setlist example`, `song next`, `tap`, `tempo 128` / `tempo off`.

Setup and test (console): `find mh_a` lights one fixture, `chan 30 255` drives a raw channel, `setup off` clears both, `addresses` shows the patch, `nodes` shows node health. Scenes: `scenes`, `scene opera`, `look`.

Simulator console example: `master off`, then `hit 38 110` flashes the bars and shows the time from hit to frame sent. `learn flash fixtures=bars` then a pad hit maps that pad; `save` writes the MIDI map.

## Browser UI

`dmx-suite run` also starts the UI at http://localhost:8505/ (`--port` to change, `--no-web` to turn off); the desktop app shows the same screens in its own window. Pages are in a menu down the left (a bar along the bottom on a phone); MASTER, blackout, gig lock and the status strip stay along the top.

- **Live:** the light layout with live colours, show/set/scene buttons, the playing set's steps (tap one to jump to it, with repeat count and time left), next step, tap tempo or type a BPM, speed fader, setlist (tap a song to jump to it), grand master and sub-master faders, haze.
- **Layout:** arrange the lights and make groups (below).
- **Scenes:** build scenes on screen (below).
- **Shows:** build shows from scenes and edit setlists (below).
- **Fixtures:** the patch, fixture types and rig settings (below).
- **Busk:** your own panels of buttons and faders to play over the running show (below).
- **Heads:** drag on a pad to hold a head at a spot (head limits still apply); save held positions as a palette position.
- **MIDI:** live monitor (what each message triggered), pause/clear/filter, MIDI learn, mapping table, save.
- **Setup:** find a light, channel tester, drum flash test, devices, node health (name/identify nodes), address check, theme, check for updates.
- **Files:** preview or play scenes, and restore any file from the backups.

**Light layout:** every light is a square on a grid, and every pixel of a pixel bar is its own square, each showing its live colour. On the Layout page:
- pick lights with the group tabs, a tap (shift-tap to add), a box or the lasso;
- move them, align them, space them out, make a row, ring or grid of them, or rotate them;
- lay out a bar's pixels as a row, ring or grid;
- zoom, show or hide names and the moving-head beam lines;
- undo, then save. Saving writes `layout:` into the rig file (previous copy in the backups).

Positions are grid cells from the top left, with the back of the stage at the top: `{x, y, rot, shape, cols}`. Lights not placed yet get a default spot. Fixture types can set `pan_range` / `tilt_range` (degrees, default 540 / 270) so the beam lines match the heads.

**Groups:** select lights and make a group, set an existing group to the selection, rename it (every scene, look, rig and MIDI map that uses it follows), or delete it (refused while anything uses it). Groups are saved on the fixtures in `fixtures.yaml`.

**Themes:** Neutral (default) or 0.05, picked on the Setup page and remembered by each laptop. A theme is a folder in `dmx_suite/web/static/themes/` with `theme.css` (colours and font), `logo.svg` and `theme.json` (name). All UI text is in `dmx_suite/web/static/i18n/en.json`.

**Status bar** (always across the top; full table on the Setup tab):

| Item | Shows |
| --- | --- |
| Engine | Actual frame rate (amber under 35 fps) |
| DMX outputs | Enttec Open DMX / Pro and the 0.05 node: connected, no reply, or not found / unplugged (retrying every 2 s); Art-Net / sACN: sending, or the network error |
| OSC | Listening port and messages received (when the rig turns OSC on) |
| MIDI | Each input in the rig's `midi_inputs`: connected or unplugged |
| Claude | Connected while Claude Desktop has the 0.05 tools loaded, the last tool it used, read-only during gig lock |
| Screens | Browsers watching, and how many are phones/tablets |
| Nodes | Every node and receiver: online / weak / offline / new, signal |

A red banner and a beep appear when an output, MIDI interface or node drops out. USB DMX interfaces and the node reconnect by themselves when plugged back in. Node changes are logged to `logs/health-<date>.jsonl`.

**Gig lock** (top right): Claude can still read everything, but can't change files, preview or change haze, and the MIDI map can't be saved. The band's live controls keep working.

**Setup wizard:** opens on a laptop that hasn't been through it (and from the Setup page): DMX interface (spots a 0.05 node, Enttec Pro or Open DMX cable by its USB ID; or Art-Net, sACN, simulator), lights by type and count (auto-patched), rule profile, a starter show for your rig (warm, blue, rainbow, chase, wave, sparkle, circles for moving heads; calm and lively sets), and a PIN. Every step can be skipped.

**Fixtures page:**
- **Patch:** type, universe, address, groups and sub-master of every light; add lights, auto-patch, overlaps marked, find a light, remove one from the patch and every rig.
- **Fixture types:** channel table (role, default, pixel, invert), colour mixing, wheel and gobo slots, test every channel on a patched light, import from or export to the Open Fixture Library.
- **Rig settings:** profile, masters, fades, lights in the rig, head limits, haze, tempo, outputs, inputs. Saves apply live, except outputs, MIDI inputs and OSC; **Run this rig** switches rigs without stopping.

**Fixture types** (R7): `colour_mix: auto` mixes each colour for the light: white (and amber) out of RGB, white-only and dimmer-only lights at the colour's brightness, colour-wheel lights on the nearest named slot. Types from before R7 are `colour_mix: off` (colours as written, so shows look the same). `wheel: {red: {value: 20, colour: "#ff0000"}}` and `gobos: {dots: 30}` name slots for scenes. Roles also include zoom, focus, frost and prism; a `<role>_fine` channel makes dimmer, pan, tilt, zoom or focus 16-bit; `invert: true` on pan, tilt, zoom, focus, frost or pt_speed; `sub: wash` makes a light follow another sub-master than its kind's.

**Access (PIN and phones, Setup page):** the app only answers this computer until **phone/LAN access** is turned on, which needs a PIN first. The Setup page then shows the address and a QR code; a phone on the same Wi-Fi opens it and signs in with the PIN. A phone stays signed in until it's unused for the set number of hours (12 by default), the PIN changes, or LAN access goes off; five wrong PINs make it wait 30 s. Tick **Ask for the PIN on this computer too** to lock the laptop's own screen as well. Access settings can only be changed on the laptop, and the PIN is kept only as a salted hash in app data. `--lan` turns phone access on at start-up (once a PIN is set).

**Claude's own key:** Claude (MCP) uses its own token from app data, only from this computer, and only for show edits, preview, haze and nodes: it can't turn gig lock off, change access or settings, or learn MIDI. With the app closed, Claude's edits still respect gig lock.

**Undo and redo** (Files page, or Ctrl+Z / Ctrl+Y on any page but Layout, which has its own undo for unsaved moves): every change since the app started, by you or by Claude, without limit. An undo is refused if the file was changed some other way since; older changes are in the backups. Claude's `undo_last_change` only undoes its own.

**Copy and paste a look** (Scenes page, or Ctrl+C / Ctrl+V there): copy the layer being edited, or the look of the first selected light, and paste it onto other lights. It becomes one layer per kind of light, keeping only what each can do: position and movement only on heads that move, gobo and colour wheel only where fitted.

**Live feed:** screens get the state when it changes (worked out once for all of them), plus a heartbeat every 5 s; a screen that hears nothing for 12 s reconnects, and shows a "lost the connection" box meanwhile (the lights keep running). Screens ask to stay awake while the app is showing.

## Claude Desktop

Lets Claude read and build scenes, shows, setlists and palettes in plain words, check them against the hard rules, preview them on the rig and read node health. The installer sets this up. From source, run `dmx-suite claude-setup` (adds it to every Claude Desktop config found, keeping a `.bak`), or add this to `claude_desktop_config.json` by hand (full path to `dmx-suite.exe` inside your virtual environment's `Scripts` folder):

```json
{
  "mcpServers": {
    "dmx-suite": {
      "command": "C:\\path\\to\\.venv\\Scripts\\dmx-suite.exe",
      "args": ["--shows", "C:\\path\\to\\shows", "mcp"]
    }
  }
}
```

With `dmx-suite run` going, Claude's changes go through the engine: gig lock applies, scene/show/palette changes load straight away, and preview, haze and node tools work. With it stopped, Claude edits the show files directly (same checks and backups). Every change is checked against the whole show folder first and refused with the reason if it breaks a rule or a reference; the previous file is kept in `shows/.backups/`.

## Phase 2 hardware (prepared)

**Second universe / receiver per light:** give fixtures `universe: 1` (0-15) in `shows/fixtures.yaml`; the same address can be used on each universe. Every universe is rendered and sent each frame (drum hits too). The node outputs its own universe on its wired DMX and forwards the others over the air; name each AtomS3 receiver and set its universe from the Setup tab (or `dmx-node-test assign`). An Enttec output drives one universe: `{driver: enttec_open, port: COM7, universe: 1}`.

**Outputs:** list one or more in the rig file's `outputs:`; the same show runs on all of them at once.

```yaml
outputs:
  - {driver: node_serial, port: COM5}                         # the 0.05 node
  - {driver: enttec_pro, port: COM7, universe: 0}
  - {driver: artnet, host: 2.255.255.255}                     # broadcast; universe n -> Art-Net n
  - {driver: artnet, host: 192.168.1.50, universes: {0: "0:0:1"}}   # net:subnet:universe
  - {driver: sacn}                                            # multicast; universe n -> sACN n + 1
  - {driver: sacn, host: 192.168.1.60, universes: {0: 10}, priority: 120}
```

USB outputs (node, Enttec Pro) write on their own thread, so a slow or unplugged interface never holds up the show or a drum hit.

**OSC in:** add `osc: {port: 9000}` to the rig file (off unless it's there; `allow: [192.168.1.0/24]` limits who may send, default this computer and private networks). OSC addresses go in the MIDI map alongside MIDI, e.g. `- {type: osc, address: /dmx/grand, action: grand_master}`. A float 0-1 drives the grand master, sub-masters and flash level; 0.5 or more (or no argument) presses a button. MIDI learn takes the next MIDI or OSC message, and the monitor shows both.

**SamplePad through the H2MIDI Pro:** add `H2MIDI` to `midi_inputs` in the rig file. A mapping with `port: H2MIDI` only answers that input and wins over a mapping without a port, so pads can reuse the TD-25's ch 10 notes. MIDI learn with `port=this` ties the new mapping to whichever input you hit. Examples are commented at the end of `shows/midi/default.yaml`.

**MIDI interfaces:** `midi_inputs` in the rig file lists parts of the port names to open (empty = every port). Ports are rescanned every 2 s, so an interface unplugged mid-gig reconnects by itself, even under a new Windows name. Each one shows connected/unplugged in the health strip, with the banner if it drops.

## Show files

**The `.dms` show file:** one file holds the whole show (fixtures, palettes, rigs, looks, scenes, shows, setlists, busk panels, MIDI maps): a zip of the YAML files below plus `dms.json` (file version, app version, when saved). The app works on a copy in app data and saves every change straight back into the `.dms`, so OneDrive syncs one file. Backups stay on the laptop. If the app stopped before a change reached the file, the next open keeps it as `<name> (recovered DD-MM-YYYY).dms`. A `.dms` open in the app on another computer (`<name>.dms.lock` next to it) opens read-only. On the Files page: **Open…**, **Save as…**, **New from starter show…**, **Download**, **Upload and open…** (phones), and recent files; opening another file restarts the app on it (the lights go dark for a few seconds). A show folder still works everywhere a `.dms` does:

```bash
dmx-suite pack shows "My show.dms"
dmx-suite unpack "My show.dms" my-show-folder
dmx-suite --shows "My show.dms" run --sim
```

All placeholders until copied from the Daslight patch: channel maps (`verified: false` in `shows/fixtures.yaml`), DMX addresses, FCB1010 program change numbers and drum pad map (`shows/midi/default.yaml`), and the MH-A tilt limit (`shows/rigs/full.yaml`). `dmx-suite check` lists the unverified fixture types.

Scenes (`shows/scenes/*.yaml`) are layers applied in order to lights or groups: a colour, position or gobo, an effect, or both. Colours, positions and gobos come from `shows/palettes.yaml`. Like looks, scenes can't set dimmers or haze or move the U'King heads. See the top of `dmx_suite/scenes.py` for every option.

**Effects** (each a class in `dmx_suite/effects/`, so the scene builder, auto shows and Claude all see the same list):

| Kind | Effects |
| --- | --- |
| v1 | `colour_chase`, `pixel_chase`, `flash`, `sweep`, `random_move` |
| Colour | `rainbow`, `sparkle`, `wave`, `strobe` (done with colour, so MASTER still owns on/off) |
| Movement (inside head limits) | `circle`, `figure8` |
| Matrix (across the layout) | `linear_wave` (any angle), `radial` (out or in), `gradient`, `bars`, `noise` |

Every effect that runs across several lights takes `mapping`: `order` (as listed) or `spatial` (by where each light, and each pixel, is on the layout, so a wave crosses the whole rig as one picture). It also takes `direction` (forward, reverse, centre out, out to centre, random, or an `angle`), `groups_of` (move in blocks), and on the wave effects `waveform` (sine, square, saw, triangle, pulse) and `width`. A layer's `level` (0-1) and `blend` (replace, max, add) mix it with the layers under it; `mute: true` skips it. A scene's `length_s` is one cycle (default: its longest effect period).

**Scene builder** (Scenes page): pick lights on the layout and add a layer. Then choose a colour, position or gobo and/or an effect; its settings form comes from the effect itself. For a spatial effect, an arrow on the layout shows which way it runs. Tick **Live preview** to play the unsaved scene on the rig. A layer that breaks a rule is marked in red with the reason. Save, duplicate or delete scene files.

Shows (`shows/shows/*.yaml`) have sets. A set is either a list of steps or an `auto` style that generates a fresh scene every step from the palette colours, energy (low/mid/high), head colour mix (matching/white/contrast), patterns (all, heads only, bars only, static on the kit) and movement (random/sweep/static), using only the fixtures in the active rig. `band` has LOW / MID / HIGH (60 / 40 / 20 s) plus a `cues` set; `opera` and `acoustic` are single-set shows.

**Show steps** (like a Daslight super scene): each step plays a scene, then moves on after `repeats` (times through the scene's `length_s`), `hold_s` seconds, or `hold_beats` / `hold_bars` at the current tempo. `fade_s` on the set crossfades between steps; a step's own `fade_s` overrides it (0 = cut). A set plays its steps in `order: sequence` or `random`, and `loop: false` stops on the last step. Older files with `scenes:` and `step_s` still load as steps of `hold_s`. Crossfades mix colour; a moving head that changes position goes dark, moves, then fades in; channels not in the new look end at exactly 0. Rig `change_fade_s` crossfades when you pick a scene, show or look (default 0, a cut, as before).

```yaml
sets:
  verse:
    fade_s: 2
    order: sequence      # or random
    loop: true
    steps:
      - {scene: blue_chase, repeats: 4}
      - {scene: red_movers, hold_s: 30, fade_s: 0}
      - {scene: strobe_hit, hold_bars: 2}
```

On the **Shows** page: pick or make a show, add sets, add scenes as steps, set each one's repeats, hold (seconds, beats or bars) and fade, reorder them, and set the set's fade, order and loop; or switch a set to auto and fill in its style. Save, play or delete. The setlist editor beside it adds, reorders and removes songs, each a show (and set) or a scene, with MASTER on, off or as it is.

**Beat sync:** the rig file picks a tempo source with `tempo: {source: tap | kick | midi_clock}`. `tap` is a pedal, key or button; `kick` follows the drummer's kick note (`kick_note`, default 36; average of the last 4 beats, fills ignored); `midi_clock` follows MIDI clock from any input. If a kick or clock goes quiet, the last tempo is kept for `timeout_s` (default 30 s), then effects return to fixed timers. With no tempo, everything runs on fixed timers as before. A layer's `beats` sets its effect cycle in beats instead of seconds. A `speed` action (MIDI, OSC or a busk fader) multiplies effect speed 0.25-4×. The top bar shows the tempo, its source and a beat pulse.

**Busking** (Busk page, `shows/panels.yaml`): panels of buttons and faders, one per show (or `default`). Widgets: colour (latch, or while held), flash, solo (everything else dark while held), effect (latch a scene's layers over the show), go (a scene, or a show and set), fader (grand master, a sub-master, flash level or speed) and haze. Tick **Edit panels** to make panels and add, reorder or remove widgets. Busk overrides sit on top of the show and under the rules (colour only under the 0.05 band profile, unlit channels at 0, solo leaves the kick light alone); releasing fades back to the show over the panel's `release_fade_s`. Lights held by busk buttons get a dashed outline on the layout, and **Release all** lets go of everything. Map any widget to MIDI or OSC with the `busk` action (`panel`, `widget`). Setlists (`shows/setlists/`) list songs, each with a show/set or a scene, optionally forcing MASTER. A scene layer can name a `fallback` group to use when its fixtures aren't in the rig.

**Rule profiles:** each rig file picks which rig rules apply with `profile:`. `0.05_band` (the shipped rigs) is MASTER on/off with colour-only scenes, drum flash with MASTER off, and the kick light ignoring MASTER. `generic` is standard dimmer behaviour: lights follow the scene, a layer or look can set `intensity: 0-1`, and there's no drum flash. A block (`profile: {base: 0.05_band, master_exempt: [wash]}`) changes single settings. A rig file with no `profile:` runs as `0.05_band`. Safety rules (no glow, haze only from the Haze controls, grand master intensity only, head limits) apply under every profile. `dmx-suite check` refuses a scene or look that sets `intensity` while any rig uses a MASTER on/off profile.

**If something goes wrong mid-show:** an error while rendering never stops the lights: the engine drops to the static look (or keeps the last good frame) and the status bar shows the fault. If the show folder won't load at start-up (a typo in a file), `dmx-suite run` runs the last version of it that did, from `shows/.backups/`, and says so; fix the file (`dmx-suite check` names it) or restore it from the Files tab, and the real files take over.

**File versions:** every show file starts with `version:` (the file format). Files from an older format still load, and `dmx-suite run` (and the desktop app) rewrites them in the current format at start-up, keeping their comments, with the originals in `shows/.backups/`. A file from a newer app is refused with a message saying so, instead of being half-read.

Levels in rig files are 0-100 %. Looks (`shows/looks/`) set colour, pixels, wheel, gobo and position only; a `dimmer` or `haze` key is rejected (hard rules 1 and 5). The static look is the fallback when no scene is playing.

## Node test script

Runs against real hardware (`--port COM5`) or the simulator (`--sim`).

```bash
dmx-node-test ports
```

```bash
dmx-node-test --port COM5 check
```

```bash
dmx-node-test --port COM5 chase --channels 1-24 --seconds 10
```

```bash
dmx-node-test --port COM5 frame 1=255 2=128 --hold 5
```

```bash
dmx-node-test --port COM5 fallback --rgb 1,4,7 --period 60 --level 200 --base 10=255
```

```bash
dmx-node-test --port COM5 assign F4:12:FA:00:A0:01 "Left bars" --universe 0
```

```bash
dmx-node-test --port COM5 identify F4:12:FA:00:A0:01
```

`check` pings the node 20 times (round-trip times), then lists status and every node heard with its state: online, weak, offline or new.

## Updates

```bash
dmx-suite update-check
```

Says whether a newer version has been released (also `/api/update` for the UI). It only checks; installing is up to you. Nothing else is sent anywhere: no telemetry. `dmx-suite --version` shows the installed version.

## Firmware

See `firmware/README.md`.
