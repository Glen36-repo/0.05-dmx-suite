# 0.05 DMX Suite

Live lighting software for the band 0.05: MIDI in, DMX out, automatic shows, drum flash, and scene editing through Claude via MCP.

See `docs/SCOPE.md` for requirements and `CLAUDE.md` for development rules.

## Layout

| Path | What |
| --- | --- |
| `docs/PROTOCOL.md` | USB serial and ESP-NOW protocol (node link) |
| `dmx_suite/node/` | Laptop side: protocol, link, health tracking, simulated node |
| `dmx_suite/tools/node_test.py` | Node test script (`dmx-node-test`) |
| `firmware/` | PlatformIO: `node` (CoreS3 SE) and `receiver` (AtomS3 Lite) |
| `tests/` | pytest, including a byte-for-byte check of the firmware protocol code |

## Setup (laptop)

```bash
pip install -e .[dev]
```

```bash
pytest
```

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
