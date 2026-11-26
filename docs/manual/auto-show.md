# Auto show: FX banks and ride controls

The auto show builds looks from **FX banks** for whatever rig you have, with no programming. The Ride page and the autopilot (from v3.4) use it; Claude can try looks with `preview_look`.

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
