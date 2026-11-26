# 0.05 DMX Suite

Live lighting software for the band 0.05: MIDI in, DMX out, automatic shows, drum flash, and scene editing through Claude via MCP.

See `docs/SCOPE.md` for requirements and `CLAUDE.md` for development rules.

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
| `dmx_suite/web/` | Browser UI and local JSON API (standard library, works offline) |
| `dmx_suite/store.py` | Validated, backed-up edits to the show folder (UI and Claude) |
| `dmx_suite/claude_tools.py`, `mcp_server.py` | Claude Desktop (MCP) tools |
| `dmx_suite/output/` | Output drivers: `node_serial`, `enttec_open`, `enttec_pro`, `log`, `null` |
| `dmx_suite/midi/` | MIDI map, router, monitor and learn |
| `dmx_suite/cli.py` | `dmx-suite`: run, simulator, MIDI monitor, show file check |
| `dmx_suite/node/` | Laptop side: protocol, link, health tracking, simulated node |
| `dmx_suite/tools/node_test.py` | Node test script (`dmx-node-test`) |
| `firmware/` | PlatformIO: `node` (CoreS3 SE) and `receiver` (AtomS3 Lite) |
| `installer/` | Windows installer: PyInstaller spec, Inno Setup script, `build.ps1` |
| `tests/` | pytest, including a byte-for-byte check of the firmware protocol code |

## Install (gig laptop)

Run `0.05-DMX-Suite-Setup-<version>.exe`. No Python needed. It asks:

- **Show files folder:** default `OneDrive\Music\0.05 DMX Suite\shows` (Documents if there's no OneDrive). An existing folder is used as is; a new one gets the starter shows. Upgrades and uninstall never touch it
- **Add the 0.05 tools to Claude Desktop** (on by default): restart Claude Desktop afterwards
- **Desktop shortcut** (on) and **start live at login** (off)

Start menu: live, simulator, MIDI monitor, check show files, open lighting UI, show files folder. The chosen folder is saved as the `DMX_SUITE_SHOWS` user environment variable, so `dmx-suite.exe` from a command prompt uses it too.

**Building the installer:** run the *Windows installer* workflow on GitHub (Actions tab → Run workflow, or push a `v*` tag) and download it from the run's artifacts. Or on a Windows PC with Python 3.12+ and Inno Setup 6: `powershell -ExecutionPolicy Bypass -File installer\build.ps1` → `dist\`. The build runs the tests and a check of the packaged app first. Bump `version` in `pyproject.toml` for each release.

## Setup (from source)

On the gig laptop (real MIDI ports, Claude Desktop tools):

```bash
pip install -e .[hw,claude,dev]
```

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

Live runs save what's playing to `shows/.state.json`; if the laptop restarts mid-gig, `dmx-suite run` carries on with the same show/set or setlist song and MASTER state (state older than 12 hours is ignored; `--fresh` ignores it).

Import a fixture type from an [Open Fixture Library](https://open-fixture-library.org) file (prints YAML to paste into `shows/fixtures.yaml`; check it against the manual):

```bash
dmx-suite import-ofl fixture.json --mode 11-channel --key mhl36
```

Shows (console): `show band high`, `set low`, `next` (next step), `now`, `setlist example`, `song next`, `tap`, `tempo 128` / `tempo off`.

Setup and test (console): `find mh_a` lights one fixture, `chan 30 255` drives a raw channel, `setup off` clears both, `addresses` shows the patch, `nodes` shows node health. Scenes: `scenes`, `scene opera`, `look`.

Simulator console example: `master off`, then `hit 38 110` flashes the bars and shows the time from hit to frame sent. `learn flash fixtures=bars` then a pad hit maps that pad; `save` writes the MIDI map.

## Browser UI

`dmx-suite run` also starts the browser UI at http://localhost:8505/ (`--port` to change, `--no-web` to turn off).

- **Live:** MASTER, blackout, stage plan (top-down view of the rig with live colours and moving-head beam lines), show/set/scene buttons, next step, tap tempo, setlist, grand master and sub-master faders, haze.
- **Heads:** drag on a pad to hold a head at a spot (head limits still apply); save held positions as a palette position.
- **MIDI:** live monitor (what each message triggered), pause/clear/filter, MIDI learn, mapping table, save.
- **Setup:** stage plan arrange (drag lights into place, rotate, set the stage size, save), find fixture, channel tester, drum flash test, node health (name/identify nodes), address check.
- **Files:** preview or play scenes, and restore any file from the backups.

**Stage plan:** each rig file has `stage: {width, depth}` (metres) and `layout:` with `{x, y, rot}` per fixture: x from stage left as the audience sees it, y from the front edge, rot 0 = facing the audience. Lights not placed yet get a default spot. Arrange it on the Setup tab rather than by hand; saving rewrites the rig file (previous copy in the backups). Fixture types can set `pan_range` / `tilt_range` (degrees, default 540 / 270) so the beam lines match the heads.

**Status bar** (always across the top; full table on the Setup tab):

| Item | Shows |
| --- | --- |
| Engine | Actual frame rate (amber under 35 fps) |
| DMX outputs | Enttec Open DMX / Pro and the 0.05 node: connected, no reply, or not found / unplugged (retrying every 2 s) |
| MIDI | Each input in the rig's `midi_inputs`: connected or unplugged |
| Claude | Connected while Claude Desktop has the 0.05 tools loaded, the last tool it used, read-only during gig lock |
| Screens | Browsers watching, and how many are phones/tablets |
| Nodes | Every node and receiver: online / weak / offline / new, signal |

A red banner and a beep appear when an output, MIDI interface or node drops out. USB DMX interfaces and the node reconnect by themselves when plugged back in. Node changes are logged to `logs/health-<date>.jsonl`.

**Gig lock** (top right): Claude can still read everything, but can't change files, preview or change haze, and the MIDI map can't be saved. The band's live controls keep working.

**Phone:** start with `--lan`, then open the link it prints (it carries an access token) on a phone on the same network. Without `--lan` the UI is only reachable from the laptop.

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

**SamplePad through the H2MIDI Pro:** add `H2MIDI` to `midi_inputs` in the rig file. A mapping with `port: H2MIDI` only answers that input and wins over a mapping without a port, so pads can reuse the TD-25's ch 10 notes. MIDI learn with `port=this` ties the new mapping to whichever input you hit. Examples are commented at the end of `shows/midi/default.yaml`.

**MIDI interfaces:** `midi_inputs` in the rig file lists parts of the port names to open (empty = every port). Ports are rescanned every 2 s, so an interface unplugged mid-gig reconnects by itself, even under a new Windows name. Each one shows connected/unplugged in the health strip, with the banner if it drops.

## Show files

All placeholders until copied from the Daslight patch: channel maps (`verified: false` in `shows/fixtures.yaml`), DMX addresses, FCB1010 program change numbers and drum pad map (`shows/midi/default.yaml`), and the MH-A tilt limit (`shows/rigs/full.yaml`). `dmx-suite check` lists the unverified fixture types.

Scenes (`shows/scenes/*.yaml`) are layers applied in order to fixtures or groups: static colour/position/gobo, or an effect (`colour_chase`, `pixel_chase`, `flash`, `sweep`, `random_move`). Colours, positions and gobos come from `shows/palettes.yaml`. Like looks, scenes can't set dimmers or haze or move the U'King heads. See the top of `dmx_suite/scenes.py` for every option.

Shows (`shows/shows/*.yaml`) have sets on fixed step timers. A set is either a list of scenes (in order, or random without repeats) or an `auto` style that generates a fresh scene every step from the palette colours, energy (low/mid/high), head colour mix (matching/white/contrast), patterns (all, heads only, bars only, static on the kit) and movement (random/sweep/static), using only the fixtures in the active rig. `band` has LOW / MID / HIGH (60 / 40 / 20 s) plus a `cues` set; `opera` and `acoustic` are single-set shows. Setlists (`shows/setlists/`) list songs, each with a show/set or a scene, optionally forcing MASTER. A scene layer can name a `fallback` group to use when its fixtures aren't in the rig.

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

## Firmware

See `firmware/README.md`.
