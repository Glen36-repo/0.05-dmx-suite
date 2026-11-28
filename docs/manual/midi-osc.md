# MIDI and OSC

Every pad, pedal, key or OSC control is a **named input** (`inputs.yaml`), defined once. The MIDI map (`midi/default.yaml`) says what each input does: pick a show or set, MASTER, blackout, flash lights from a drum pad, move a fader, haze.

## Named inputs

Inputs live in devices, e.g. the TD-25 kit or the FCB1010:

```yaml
devices:
  td25:
    name: TD-25 kit
    channel: 10
    inputs:
      kick:  {name: Kick, type: note, notes: [36], roles: [kick, activity]}
      snare: {name: Snare, type: note, notes: [38, 40], roles: [snare, activity]}   # head + rim
  fcb1010:
    name: FCB1010
    channel: 1
    inputs:
      master: {name: MASTER, type: program_change, number: 0}
      expression: {name: Expression pedal, type: control_change, number: 7}
```

- **Type:** note (one or more `notes`), program change or CC (`number`), or OSC (`address`)
- **Channel:** 1-16 as printed on the gear, or `any`; set it on the device for every input in it
- **Port:** part of the interface's name (e.g. `H2MIDI`), on the device or one input. A port-specific input wins, so the SamplePad and the TD-25 can use the same notes
- **Velocity range:** `velocity: [64, 127]` makes only hard hits count (soft and hard hits can be two inputs)
- **Roles:** what the input is to the auto show: kick, snare, tom, cymbal, count_in, activity. Any device can carry them (a keyboard's low C can be the kick)
- **Shared:** two inputs can claim the same message only if both say `shared: true`; then both fire

Change a note in one place and every mapping, step scene and the auto show follow. An input that's still used can't be deleted: you're told where it's used.

On the MIDI page, the **Inputs** section lists every device. **Learn** sets an input from the next pad hit or pedal press; **+ note** adds another note (snare rim). **Load a device profile** adds a ready-made device (Roland TD-25, Alesis SamplePad 4, Behringer FCB1010, any GM drum kit); **Save as profile** keeps your device to use in other shows (`devices/` in the show).

### Calibrating a pad

**Calibrate** on a note input, pick **Quiet**, play it a few times at that strength, press **Done**; then the same for Normal and Loud. Quiet hits then count as a quarter, normal as 60 % and loud as full, for drum flash brightness and (from v3.4) the auto show's energy. Until calibrated, the velocity is used as it comes.

## The MIDI map

```yaml
mappings:
  - {input: master, action: master_toggle}
  - {input: snare, action: flash, fixtures: [bars], length_ms: 120}
  - {input: expression, action: grand_master}
```

Mappings written the old way (`{type: note, channel: 10, number: 38, ...}`) still work. When a show folder from an older version is opened, they're turned into named inputs once, with a backup.

## OSC

Turn OSC on in the rig file:

```yaml
osc:
  port: 9000
  allow: [192.168.1.0/24]    # optional; default: this computer and home/venue networks
```

Then make OSC inputs (`type: osc, address: /dmx/grand`) and map them like any other. Faders (grand master, sub-masters, drum flash level) follow the value 0-1. Buttons act when the value is 0.5 or more, or when the message has no value.

## Learn

On the MIDI page, pick an action and press **Learn**, then press the pedal, hit the pad, or move the OSC fader. If the message is already a named input, the mapping uses it; otherwise a new input is made in the **Learned** device. **Save MIDI map** writes the map and any new inputs, keeping the previous files in `.backups`.

The monitor lists every MIDI and OSC message, the input it is ("Kick, vel 98") and what it did. OSC rows show the sender, e.g. `OSC 192.168.1.20`.
