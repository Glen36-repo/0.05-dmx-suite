# Auto show: the Ride page, autopilot, FX banks

The auto show builds looks from **FX banks** for whatever rig you have, with no programming: open the **Ride** page, turn the **autopilot** on, and ride it with a few big controls. Claude can try looks with `preview_look` and explain what the autopilot is doing.

## The Ride page

- along the top: **Autopilot** on/off, mood **LOW / MID / HIGH** (or **Auto mood**: it follows the energy), **Hold**, **◀ Previous**, **Next look ▶**, and the energy bar
- the layout strip shows what the lights are doing
- **Move FX** on the left, **Flash FX** in the middle (held while your finger is on them), **Colour FX** on the right, **Drum FX** below; tap one to use it now
- **Palette**, with **Lock palette** so the autopilot keeps it
- **Ride controls**: speed, fade, fan, size, shift, for everything or per bank
- the **Haze** controls are here too, but they're separate: the auto show never touches haze
- **Why did it do that?** lists the autopilot's last decisions with the reason for each
- **Lights in the auto show**: how each light is used; change one or leave it out
- **Learn**: tap Learn, tap any control, then hit a pad or press a pedal: it's mapped and saved

## The autopilot

It picks a Move FX + Colour FX + palette + ride settings and changes them on a timer that depends on the mood (60 s low, 40 s mid, 20 s high, give or take 20 %). It never repeats one of the last few looks, and each new look contrasts with the last (look quality rules).

- **Energy** comes from your MIDI only (no microphone): how many hits a second on inputs with the `activity` role, and how hard. Any instrument can drive it (give a keyboard or pad controller the roles)
- **Mood** follows the energy unless you set it with a button or pedal (MIDI action `mood`, mood: low / mid / high / up / down / auto); with no drum MIDI it's manual
- a **drum fill then a crash** changes the look early and fires a colour hit
- a **build** (energy climbing) gets faster, bigger looks; a **breakdown** (energy falling) gets slower, sparser ones
- **MASTER off**: drum flash owns the rig and the autopilot waits
- picking a show, scene or look by hand turns the autopilot off

### Between songs

No `activity` hits for 4 seconds = the song has ended: the lights fade to a calm **talking look**. A count-in (4 evenly spaced hits on an input with the `count_in` role, e.g. sticks or the hi-hat pedal) or the first hit = the song is starting: straight back into the show. **Walk-on** and **walk-off** looks play from their buttons, or when a setlist starts and after its last song.

### Control priority

Highest first: **1** blackout, **2** MASTER off (drum flash), **3** Flash FX and busk buttons, **4** hold (the look stays, the autopilot stops changing), **5** the autopilot or the running show. Pedals: `autopilot`, `hold`, `look_next`, `look_prev`, `mood`, `walk_on`, `walk_off`, plus `ride_fx`, `ride_palette`, `palette_lock` and the faders `ride_speed`, `ride_fade`, `ride_fan`, `ride_size`, `ride_shift`.

Set `release_fade_s` in the rig file (e.g. `0.5`) and letting go of a higher level fades back to the one below (MASTER back on, blackout off, a held Flash FX) instead of cutting.

### Settings (rig file)

```yaml
autopilot:
  moods: {low: 60, mid: 40, high: 20}
  variation: 0.2
  no_repeat: 4
  fade: {low: 4, mid: 2, high: 0.5}
  gap_s: 4
  count_in: 4
  talking: {colour: static, palette: white, move: kit, ride: {speed: 0.5}}
  palettes: [warm, cool, band]
```

Every decision (time, energy, mood, look, why) is saved per gig in `logs/decisions-YYYY-MM-DD.jsonl` in app data; Claude reads it with `autopilot_status`.

## How the lights are sorted

Every light is put in a class by what it can do:

| Class | What | Gets |
| --- | --- | --- |
| head | moving heads | Move FX, and the look's colour |
| wash | single-colour lights (pars, washes, colour-only heads) | Colour FX |
| pixel | pixel bars | Colour FX, pixel effects (bounce, comet, fill) |
| strobe | white-only lights, blinders | white at part level, Flash FX |
| effect | colour-wheel or gobo lights with no colour mixing | the look's first colour |
| kick | lights MASTER doesn't touch (0.05: the kick light) | never: they keep their own rules |

Haze is never part of the auto show. A new light joins as soon as it's patched. To change a light's class or leave it out, add to the rig file:

```yaml
auto:
  classes: {wash_3: strobe}
  exclude: [wash_4]
```

## The banks

**Move FX** (heads, inside the head limits): pan sweep, tilt sweep, circle, figure 8, fan out/in, swim, float, centre/kit (a head point tagged `band`), random positions (head points tagged `safe`, moving dark), crossfire, audience sweep, ballyhoo, mirror sweep.

**Colour FX:** static palette, rainbow, colour chase, chase in, chase out, carousel, sparkle, twinkle, colour fade, split, wave, pulse; pixel bars: bounce, comet, fill/unfill; across the layout: gradient sweep, radial, plasma, bars; themed: fire, lightning, police.

**Drum-reactive** (from your named inputs' roles, MIDI only): kick pump, snare hit, tom roll, cymbal shimmer, fill build, velocity colour.

**Flash FX** (momentary): blinder, colour hit, strobe, blackout, freeze, flash and decay, chase hit, rig split hit. Map them to a pad or pedal with the MIDI action `flash_fx` (e.g. `{input: crash, action: flash_fx, fx: blinder}`): held while pressed, or for `length_ms`. They never touch the kick light or the haze, and the Flash FX blackout is not the BLACKOUT button: MASTER and haze carry on.

There's no strobe rate limit: strobe and lightning run at the rate set.

All of these are also ordinary effects in the scene builder (`move`, `palette`, `colour_fade`, `split`, `pulse`, `twinkle`, `comet`, `bounce`, `fill`, `fire`, `lightning`, `police`, `kick_pump`, `snare_hit`, `tom_roll`, `cymbal_shimmer`, `fill_build`, `velocity_colour`).

## Rig size

Each item says what it needs (heads, colour lights, pixels). Only what the rig can do is offered: two pars get colour fades, pulses, splits and the drum effects; add heads and the Move FX appear; add pixel bars and the pixel effects appear. Switching rig re-checks straight away.

## Ride controls

- **Speed** (¼× to 4×), **fade** (how soft colour changes are), **fan** (spread across the lights), **size** (how big the movement, how wide the pixels, how dense the sparkle), **shift** (phase offset)
- each can be set for everything and per bank (move, colour, drum) on top
- a **palette** (Warm, Cool, Fire, Ice, Neon, White, Band colours or your own) can be locked so the autopilot keeps it

## Look quality rules

The rules for a good-looking show are data, in `quality.yaml` in the show (only what you change; Claude can read and tune them):

- palettes follow colour theory and avoid muddy colours
- one busy effect leads and the other supports: never a fast chase with a ballyhoo
- each mood has its speeds (low: slow and mid; high: mid and fast), and movement and colour speeds match
- consecutive looks must change noticeably: a different movement, colour effect, or a palette at least a little way round the colour wheel

```yaml
max_busy: 1.1
busy: {ballyhoo: 1.0}
mood_speeds: {low: [slow]}
```
