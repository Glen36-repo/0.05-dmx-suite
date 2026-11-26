# 0.05 node link protocol (v1.1)

USB serial between the laptop and the CoreS3 SE node, and ESP-NOW between the node and the AtomS3 Lite receivers. Python side: `dmx_suite/node/protocol.py`. Firmware side: `firmware/include/proto.h`. Both must match this file; `tests/test_firmware_proto.py` checks the two encoders produce identical bytes.

v1.1 (firmware 0.2, v2 R8) only adds to v1, so either side can be older:
- two new requests (SET_FALLBACK_U, SET_CHANNEL);
- an optional request id byte at the end of every request that gets an ACK, echoed as a third ACK byte;
- two bytes at the end of STATUS.

The laptop sends request ids and the new requests only to firmware 0.2 or later (it reads the version from the node's heartbeat), and reads both STATUS sizes.

All multi-byte integers are little-endian.

## 1. USB serial framing

The node is a USB CDC device; baud rate is ignored.

```
+------+------+---------+-----------------+---------+
| 0xA5 | type | len u16 | payload[len]    | crc u16 |
+------+------+---------+-----------------+---------+
```

- Start byte `0xA5`.
- `len` is the payload length, 0–1100 bytes. Anything larger is a framing error.
- `crc` is CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no final XOR) over `type`, `len` and `payload`.
- Unknown `type` values are rejected as soon as the header arrives, so a stray `0xA5` in the data can't stall the parser waiting for a bogus length. New message types must be added to both parsers.
- Resync: on an unknown type, bad length or CRC the receiver drops the start byte and scans for the next `0xA5`. Counted in `crc_errors`.

### Laptop → node

| Type | Name | Payload | Reply |
| --- | --- | --- | --- |
| `0x01` | DMX_FRAME | `universe u8`, `channels[1..512]` (missing channels = 0) | none |
| `0x02` | BLACKOUT | `universe u8` (`0xFF` = all) | none |
| `0x03` | PING | `token u32` | PONG |
| `0x04` | SET_FALLBACK | see §3 | ACK |
| `0x05` | ASSIGN | `mac[6]`, `universe u8`, `name[16]` (UTF-8, NUL-padded) | ACK |
| `0x06` | IDENTIFY | `mac[6]`, `seconds u8` | ACK |
| `0x07` | STATUS_REQ | none | STATUS |
| `0x08` | SET_FALLBACK_U | `universe u8`, then a fallback look (§3) | ACK (v1.1) |
| `0x09` | SET_CHANNEL | `channel u8` (1–13) | ACK (v1.1) |

v1.1 request ids: SET_FALLBACK, SET_FALLBACK_U, SET_CHANNEL, ASSIGN and IDENTIFY may carry one extra byte at the end, `req u8`. The ACK then carries it as a third byte, so the laptop can tell which request an ACK answers (one that timed out can't be mistaken for the next).

- DMX_FRAME is output on the next DMX packet. The node does not wait for its own tick, so a drum hit reaches the wire within one DMX packet time (~23 ms worst case for 512 channels, less for shorter frames).
- BLACKOUT holds all channels at 0 until the next DMX_FRAME. It is the panic button, so it does not time out into the fallback look.
- ASSIGN / IDENTIFY with the node's own MAC act on the node; any other MAC is forwarded to that receiver over ESP-NOW. The receiver's next heartbeat carries the new name/universe, which is the laptop's confirmation: the app waits up to 4 s for it and says whether it took.
- The node keeps every universe it is sent (up to 16): its last frame, which it resends to that universe's receivers as a keep-alive every 100 ms, and its own radio sequence number. A universe is dropped 10 s after its last frame unless it has a fallback look.
- BLACKOUT with `0xFF` blacks out every universe the node is keeping, over the radio too, and the keep-alive goes on sending black.
- SET_CHANNEL: the node stores the channel, tells its receivers (SET_CHANNEL radio packet, every 50 ms for 400 ms) and then moves. A receiver that hears nothing from the rig for 10 s listens on each channel in turn (300 ms each) until it finds the node again, and stores that channel.

### Node → laptop

| Type | Name | Payload |
| --- | --- | --- |
| `0x81` | STATUS | see below, sent every 1 s and on STATUS_REQ |
| `0x82` | HEARTBEAT | heartbeat record (§2), node's own every 1 s, receivers' relayed as received |
| `0x83` | ANNOUNCE | heartbeat record, sent on node power-up and the first time a receiver is heard |
| `0x84` | PONG | `token u32` (echo) |
| `0x85` | ACK | `acked_type u8`, `code u8`, and `req u8` if the request carried one (v1.1) |
| `0x86` | LOG | UTF-8 text |

STATUS payload (20 bytes; firmware 0.1 sends only the first 18):

| Field | Type | Notes |
| --- | --- | --- |
| uptime_ms | u32 | |
| frames_rx | u32 | DMX_FRAME messages received |
| frame_rate_x10 | u16 | DMX_FRAME/s × 10, over the last second |
| crc_errors | u32 | framing + CRC errors |
| other_errors | u16 | NAKs, wireless send failures |
| mode | u8 | 0 = live, 1 = fallback, 2 = blackout |
| receivers_online | u8 | receivers heard in the last 3.5 s |
| flags | u8 | v1.1: bit 0 = built with the development pairing key, bit 1 = wired DMX driver didn't start |
| channel | u8 | v1.1: radio channel in use |

ACK codes: 0 ok, 1 bad length, 2 bad value, 3 unknown target, 4 storage error, 5 unknown type.

## 2. Heartbeat record (37 bytes)

Used by HEARTBEAT, ANNOUNCE and the ESP-NOW receiver heartbeat.

| Field | Type | Notes |
| --- | --- | --- |
| mac | u8[6] | chip MAC, the node's unique ID |
| node_type | u8 | 1 = DMX TX (CoreS3 node), 2 = DMX RX (AtomS3), 3 = MIDI |
| fw | u8[3] | major, minor, patch |
| uptime_s | u32 | |
| rssi | i8 | dBm; `127` = not applicable (wired node) |
| loss_pct | u8 | 0–100; `255` = not applicable |
| last_data_age_ms | u32 | age of last DMX frame / MIDI message; `0xFFFFFFFF` = never |
| universe | u8 | `0xFF` = unassigned |
| name | u8[16] | UTF-8, NUL-padded; empty = new, unnamed node |

Laptop health states (`dmx_suite/node/health.py`):

- **online**: heartbeat within 3.5 s, signal OK
- **weak**: online but RSSI < −80 dBm or packet loss > 10 %
- **offline**: 3 missed heartbeats (none for 3.5 s), or expected by the rig config and never seen
- **new**: heard, but name is empty (needs naming and assigning)

## 3. Fallback look

When no DMX_FRAME has arrived for `hold_ms`, the node switches from live to fallback mode and renders the stored looks until frames return. The same applies at power-up, so a node that boots without the laptop goes straight to the safe default. Stored in NVS, so they survive power cycles.

- SET_FALLBACK stores the look for the node's own universe.
- SET_FALLBACK_U (v1.1) stores one for any universe, up to 4 universes.
- In fallback every universe the node keeps gets its own look, or black if it has none. Without a stored look that is the node's own universe; with one, it includes the radio universes.

The laptop sends the looks when the node connects or restarts: each universe's static look with MASTER on and haze at 0.

SET_FALLBACK payload:

| Field | Type | Notes |
| --- | --- | --- |
| hold_ms | u16 | time without frames before fallback starts (default 2000) |
| period_s | u16 | time for one full colour-wheel cycle (0 = static first colour) |
| level | u8 | RGB brightness 0–255 |
| n_rgb | u8 | number of RGB start addresses, 0–32 |
| rgb_addr | u16[n_rgb] | 1-based DMX address of each red channel (green/blue follow) |
| base | u8[512] | static channel values, e.g. dimmers up and everything else 0 |

Render: start from `base`, then every RGB triple is set to the current colour-wheel hue × `level`. All triples share the same hue (slow whole-rig fade). The laptop is responsible for keeping haze and pan/tilt-sensitive channels sensible in `base`; the node does not know fixture types.

## 4. ESP-NOW (node ↔ receivers)

All packets start with an 8-byte header:

| Field | Type | Notes |
| --- | --- | --- |
| magic | u8[2] | `'O' '5'` |
| version | u8 | 1 |
| kind | u8 | packet kind |
| net_id | u32 | FNV-1a 32 of the band pairing key |

Packets with the wrong magic, version or net_id are ignored. This keeps other bands' or venues' gear off the rig; it is a pairing filter, not encryption.

| Kind | Direction | Body |
| --- | --- | --- |
| `0x01` DMX_CHUNK | node → broadcast | `universe u8`, `seq u8`, `offset u16`, `len u8`, `data[len]` (≤ 200) |
| `0x02` ASSIGN | node → broadcast | `mac[6]`, `universe u8`, `name[16]` |
| `0x03` IDENTIFY | node → broadcast | `mac[6]`, `seconds u8` |
| `0x04` SET_CHANNEL | node → broadcast | `channel u8` (v1.1) |
| `0x10` HEARTBEAT | receiver → broadcast | heartbeat record (§2) |

- A 512-channel frame goes as 3 chunks (offsets 0, 171, 342) with the same `seq`. Receivers write each chunk straight into their output buffer, so there is no reassembly delay.
- `seq` counts per universe (v1.1). With one shared counter (firmware 0.1), a receiver saw every packet for another universe as a gap and reported about 50 % loss on a two-universe rig.
- Loss is worked out on the receiver from gaps in `seq` on its own universe, over the last second.
- RSSI is measured on the receiver from the node's packets.
- Receivers output the universe they are assigned; an unassigned receiver follows universe 0, so a fresh single-universe rig works before anything is named.
- A receiver that hears nothing for 5 s outputs black (the node already runs the fallback look while the laptop is away, so silence means the node itself is gone).

## 5. Pairing key

Every board in the rig must be built with the same key:

```bash
PLATFORMIO_BUILD_FLAGS='-DPAIRING_KEY=\"your-band-key\"' pio run
```

Without it, the firmware uses a development key and will only pair with other development builds; the build prints a warning, the node's screen says DEV PAIRING KEY, and the app's status bar warns too (STATUS flag). The laptop does not need the key.
