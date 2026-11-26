# Node firmware

| Env | Board | Job |
| --- | --- | --- |
| `node` | M5Stack CoreS3 SE + Unit DMX | USB serial from the laptop → wired DMX + ESP-NOW to receivers; relays heartbeats; fallback look |
| `receiver` | M5Stack AtomS3 Lite + Unit DMX | ESP-NOW → wired DMX; heartbeat every second; LED status |

Protocol: `../docs/PROTOCOL.md`. Shared code: `include/proto.h` (also compiled on the host by `tests/test_firmware_proto.py`).

## Before the first flash

1. Confirm the Unit DMX pins in `include/config.h` (`DMX_TX_PIN`, `DMX_RX_PIN`, `DMX_EN_PIN`) against the U183 schematic. Defaults: CoreS3 SE PORT.C G17 TX / G18 RX; AtomS3 Lite Grove G2 TX / G1 RX; no direction pin.
2. Pick the band pairing key. Every board must use the same one.

## Build and flash

Run these from this folder.

```bash
PLATFORMIO_BUILD_FLAGS='-DPAIRING_KEY=\"your-band-key\"' pio run -e node -t upload
```

```bash
PLATFORMIO_BUILD_FLAGS='-DPAIRING_KEY=\"your-band-key\"' pio run -e receiver -t upload
```

On Windows PowerShell, set the variable first:

```powershell
$env:PLATFORMIO_BUILD_FLAGS='-DPAIRING_KEY=\"your-band-key\"'
```

## Receiver LED

| Colour | Meaning |
| --- | --- |
| Yellow | Booting |
| Red | No data from the node (black output after 5 s) |
| Blue | Receiving, not named yet |
| Green | Receiving, named |
| White flashing | Identify |

## First test

1. Flash the node, plug it into the laptop, and run `dmx-node-test ports` to find its COM port.
2. Run `dmx-node-test --port COMx check`. The node should answer pings and show as `new`.
3. Power the receivers. They appear as `new` with signal strength and loss.
4. Name each one with `assign`, then run `chase` and watch the rig.
5. Unplug USB. After 2 s the node should run the fallback look (black until one is set with `fallback`).
