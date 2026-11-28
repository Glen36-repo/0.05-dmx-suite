# Node firmware

| Env | Board | Job |
| --- | --- | --- |
| `node` | M5Stack CoreS3 SE + Unit DMX | USB serial from the laptop → wired DMX + ESP-NOW to receivers; relays heartbeats; fallback looks; status screen |
| `receiver` | M5Stack AtomS3 Lite + Unit DMX | ESP-NOW → wired DMX; heartbeat every second; LED status; follows the node's radio channel |

Firmware 0.2 (v2 R8) speaks protocol v1.1:
- radio sequence numbers per universe;
- fallback looks for up to 4 universes, with fallback, blackout and keep-alive on every universe;
- radio channel set from the laptop;
- request ids;
- status flags;
- the CoreS3 screen (M5Unified).

The app works with 0.1 too, and says to update it.

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
| Purple blinking | Lost the node: looking for it on every radio channel |

## Node screen (CoreS3)

The screen shows the node's name, the mode in large letters (LIVE green, FALLBACK amber, BLACKOUT red), its universe and frame rate, receivers online, radio channel and firmware version. Warnings appear in red or yellow: DMX OUTPUT FAILED (check the Unit DMX wiring) and DEV PAIRING KEY (built without the band key). Identify from the laptop flashes the screen; tapping the screen flashes it for 3 s, to check it's alive. The screen only redraws when something on it changes, so it doesn't hold up DMX.

## Radio channel

The node and receivers start on channel 1 (`RADIO_CHANNEL` at build time). To move them, for example away from a venue's Wi-Fi, use **Move radio** on the Setup page, or put `radio_channel: 6` in the rig file: the app sets it whenever the node connects.

The node tells its receivers, then moves. A receiver that was off at the time finds the node again by itself within about 15 s: after 10 s of silence it tries each channel in turn and remembers the one it finds.

## First test

1. Flash the node, plug it into the laptop, and run `dmx-node-test ports` to find its COM port.
2. Run `dmx-node-test --port COMx check`. The node should answer pings and show as `new`.
3. Power the receivers. They appear as `new` with signal strength and loss.
4. Name each one with `assign`, then run `chase` and watch the rig.
5. Unplug USB. After 2 s the node should run the fallback look. The app stores one for each universe whenever the node connects (Setup page: **Send fallback looks again**); `dmx-node-test fallback` sets a test one.

## Bench test (can't be done in the cloud build)

These need the real boards. Tick them off before the first gig on firmware 0.2:

1. **Pins:** Unit DMX on CoreS3 SE PORT.C (G17/G18) and AtomS3 Lite Grove (G2/G1). Is there a direction (DE/RE) pin? If so, set `DMX_EN_PIN`.
2. **Port C power:** with `M5.begin` powering the Grove ports, does the Unit DMX get 5 V and stay up through a show? Does M5Unified leave G17/G18 free for the DMX UART?
3. **Flash both envs** with the band key; the screen must not say DEV PAIRING KEY.
4. **Screen:** LIVE / FALLBACK / BLACKOUT and the counts match the app's Setup page; identify and tap flash it; no visible DMX stutter while it redraws.
5. **Two universes:** a receiver on universe 1 and one on 0. Loss should read about 0 % on both (firmware 0.1 showed about 50 %).
6. **Fallback on every universe:** unplug USB; both receivers show their universe's static look within 2 s. Blackout reaches both.
7. **Channel move:** Move radio to 6 with every receiver on; then switch one receiver off, move to 11, and switch it back on. It should blink purple, then go green on 11 within about 15 s.
8. **Spare swap:** switch a receiver off, switch a spare on, and use Replace with spare. The spare takes the name and universe; the rig file has the new MAC.
9. **Naming:** name a receiver; the app says it was confirmed. Name one that's out of range; the app says it wasn't.
