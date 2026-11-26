# MIDI and OSC

The map (`midi/default.yaml`) says what each input does: pick a show or set, MASTER, blackout, flash lights from a drum pad, move a fader, haze.

## MIDI

Program changes, notes and CCs:

```yaml
mappings:
  - {type: program_change, channel: 1, number: 0, action: master_toggle}
  - {type: note, channel: 10, number: 38, action: flash, fixtures: [bars], length_ms: 120}
  - {type: control_change, channel: 1, number: 7, action: grand_master}
```

A mapping can be tied to one interface (`port: H2MIDI`), so two devices can use the same note numbers.

## OSC

Turn OSC on in the rig file:

```yaml
osc:
  port: 9000
  allow: [192.168.1.0/24]    # optional; default: this computer and home/venue networks
```

Then map addresses in the same file:

```yaml
  - {type: osc, address: /dmx/grand, action: grand_master}     # a fader: 0-1
  - {type: osc, address: /dmx/blackout, action: blackout_toggle}  # a button
```

Faders (grand master, sub-masters, drum flash level) follow the value 0-1. Buttons act when the value is 0.5 or more, or when the message has no value.

## Learn

On the MIDI page, pick an action and press **Learn**, then press the pedal, hit the pad, or move the OSC fader. **Save MIDI map** keeps the previous map in `.backups`.

The monitor lists every MIDI and OSC message and what it did. OSC rows show the sender, e.g. `OSC 192.168.1.20`.
