# 0.05 DMX Suite

Live lighting software for the band 0.05: MIDI in, DMX out, automatic shows, drum flash, and scene editing through Claude via MCP.

See `docs/SCOPE.md` for requirements and `CLAUDE.md` for development rules.

## Layout

| Path | What |
| --- | --- |
| `docs/PROTOCOL.md` | USB serial and ESP-NOW protocol (node link) |
| `shows/` | Show files: `fixtures.yaml`, `rigs/`, `looks/`, `midi/` |
| `dmx_suite/engine.py` | Show engine: 40 Hz loop, MASTER, blackout, drum flash, masters, haze |
| `dmx_suite/rules.py` | Rule layer: enforces the hard rules just before output |
| `dmx_suite/output/` | Output drivers: `node_serial`, `enttec_open`, `enttec_pro`, `log`, `null` |
| `dmx_suite/midi/` | MIDI map, router, monitor and learn |
| `dmx_suite/cli.py` | `dmx-suite`: run, simulator, MIDI monitor, show file check |
| `dmx_suite/node/` | Laptop side: protocol, link, health tracking, simulated node |
| `dmx_suite/tools/node_test.py` | Node test script (`dmx-node-test`) |
| `firmware/` | PlatformIO: `node` (CoreS3 SE) and `receiver` (AtomS3 Lite) |
| `tests/` | pytest, including a byte-for-byte check of the firmware protocol code |

## Setup (laptop)

On the gig laptop (real MIDI ports):

```bash
pip install -e .[hw,dev]
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

Simulator console example: `master off`, then `hit 38 110` flashes the bars and shows the time from hit to frame sent. `learn flash fixtures=bars` then a pad hit maps that pad; `save` writes the MIDI map.

## Show files

All placeholders until copied from the Daslight patch: channel maps (`verified: false` in `shows/fixtures.yaml`), DMX addresses, FCB1010 program change numbers and drum pad map (`shows/midi/default.yaml`), and the MH-A tilt limit (`shows/rigs/full.yaml`). `dmx-suite check` lists the unverified fixture types.

Levels in rig files are 0-100 %. Looks (`shows/looks/`) set colour, pixels, wheel, gobo and position only; a `dimmer` or `haze` key is rejected (hard rules 1 and 5). Looks are replaced by scenes in phase 3.

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
