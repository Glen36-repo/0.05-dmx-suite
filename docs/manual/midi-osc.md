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
- **Roles:** what the input is to the auto show: kick, snare, tom, cymbal, count_in, activity. Any device can carry them (a keyboard's low C can be the kick). **hat** (hi-hat, for the tempo), **tap** (a pad that taps the tempo), **darkness** (a CC, e.g. the FCB1010 expression pedal) rides the Autopilot's Darkness; `range: [0, 80]` sets heel to toe in % (reverse it for toe-down = lighter), and calibrating sets its curve
- **Shared:** two inputs can claim the same message only if both say `shared: true`; then both fire

Change a note in one place and every mapping, step scene and the auto show follow. An input that's still used can't be deleted: you're told where it's used.

On the MIDI page, the **Inputs** section lists every device. **Learn** sets an input from the next pad hit or pedal press; **+ note** adds another note (snare rim). **Load a device profile** adds a ready-made device (Roland TD-25, Alesis SamplePad 4, Behringer FCB1010, any GM drum kit); **Save as profile** keeps your device to use in other shows (`devices/` in the show).

### Calibrating a pad

**Calibrate** on a note input, pick **Quiet**, play it a few times at that strength, press **Done**; then the same for Normal and Loud. Quiet hits then count as a quarter, normal as 60 % and loud as full, for drum flash brightness and (from v3.4) the auto show's energy. Until calibrated, the velocity is used as it comes.

## Drum Kit

The **Drum Kit** section (MIDI page) is the drummer's kit, defined once: the tempo, drum flashes and trigger pads all read it.

- **Pieces and zones:** kick, snare (head, rim, cross-stick), hi-hat (closed, pedal, open), toms (head, rim), crashes, ride (bow, bell, edge), china / splash, extra pads, a tap pad. **Add piece** for anything else; ✕ removes a zone.
- **Learn:** press Learn on a zone and hit that pad: its note is stored (and taken off any other zone). **+ note** adds a second note to the same zone.
- Per zone: **role** (kick, snare, hat, tom, cymbal, tap, count-in, trigger only), **tempo weight** and **velocity floor** for the tempo (blank = the defaults), **Tempo** (in or out of the tempo), **Drum flash** (tick the lights or groups a hit opens with MASTER off, saved when the list closes, and the **softest hit %**; the kit owns these, not the MIDI map) and **Trigger** (`scene:name`, `preset:id` or `flash_fx:id`, fired by that pad, separate from the FCB1010).
- Each hit lights its row. Notes heard on the kit's channel that aren't in the kit show in amber, so a missed zone is obvious.
- **New kit (General MIDI)** starts from the GM note numbers; the menu switches the active kit; **Export** copies the kit as text and **Import** takes one from another laptop.

### Drum flash: a gate on the playing look (v7)

With MASTER off the rig is dark, and a drum hit **opens** the lights it's set to for the length of the hit: they show exactly what the playing scene, show or Autopilot look has on each of them at that moment (its colour or chase, pixels, head position, gobo and shutter). Nothing is added: a light the look leaves dark stays dark, and Darkness's black slots stay black. So with MASTER off the drums strobe the live show.

- How bright: from the pad's **softest hit %** (default 60 %, so a soft hit still flashes clearly) up to full on the hardest hit, in a straight line. Calibrate the pad (above) to set what counts as soft and hard.
- Moving heads open their shutter for the hit (the look's shutter setting, else the head's normal open value).
- With MASTER on a hit does nothing visible to lights that are already lit.
- The kick light is never flashed; Flash FX (blinder, colour hit, strobe ...) are separate and unchanged.
- Shows from before v7 had a flash colour (show / white): it's removed when the show is opened (format 7); a white one is noted in the log.

A show from before v6 has no kit yet: its drum inputs show as **band_kit**, and the first change you make saves it as a kit (the drum inputs and their flash settings move into it; inputs.yaml and the MIDI map are backed up first). Input names stay the same, so mappings and step scenes keep working.

```yaml
kits:
  band_kit:
    name: Band kit
    channel: 10
    pieces:
      snare:
        name: Snare
        zones:
          head: {input: snare, notes: [38], role: snare, flash: {fixtures: [bars], length_ms: 120}}
          rim: {input: snare_rim, notes: [40], role: snare}
active_kit: band_kit
```

## Tempo from the drums

With the rig's tempo source on **Drums** (Monitor › Tempo, or the rig editor), the lights follow the drummer: every hit on a drum role counts (kick, snare, hat, toms, cymbals, weighted), soft ghost notes don't. Start it with a tap (the FCB1010's tap button, a pad with the `tap` role, or Tap on the Monitor) or a count-in (4 even hits on a `count_in` pad, e.g. the hi-hat pedal, after 2 s quiet); either sets the tempo at once. After that it holds steady: it moves only when the band is clearly faster or slower for 4 beats, then glides; a big change has to hold for 8 beats. In fills and breakdowns, or when the drums stop, it carries on at the last tempo.

The **Tempo** pane on the Monitor page shows each hit by drum against the beat grid (bar lines thicker), the raw tempo and the one the lights follow, the confidence and where the seed came from. **Settings** has every number live (deadband, hold beats, jump, lock range, window, weights, velocity floor, confidence); Save to rig keeps them.

## The MIDI map

```yaml
mappings:
  - {input: master, action: master_toggle}
  - {input: snare, action: flash, fixtures: [bars], length_ms: 120, min_level: 0.6}   # min_level: softest hit
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
