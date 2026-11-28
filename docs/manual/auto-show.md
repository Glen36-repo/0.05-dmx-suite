# Auto show: the Autopilot page (v3 "Ride"), Feel, FX banks

The auto show builds looks from **FX banks** for whatever rig you have, with no programming: open the **Autopilot** page, turn the **autopilot** on, and ride it with a few big controls. Claude can try looks with `preview_look` and explain what the autopilot is doing.

## The Autopilot page

- along the top: **Autopilot** on/off, mood **LOW / MID / HIGH** (or **Auto mood**: it follows the energy), **Hold**, **◀ Previous**, **Next look ▶**, and the energy bar
- the layout strip shows what the lights are doing
- **Move FX**, **Flash FX** (held while your finger is on them), **Colour FX** and the **Palette** bank across, **Drum FX** below; tap one to use it now. The type running now is **green**. Tiles are smaller than before (v7) so more fit on screen; on phones and touch screens they stay finger-sized
- **Palette bank** (v7): a tile per palette (the seven built-ins and your own) with its colours and moods (LOW / MID / HIGH). Tap to play it now; it's excluded and kept just like FX types (below)
- **Layers** (v7) under the energy bar: Move FX, Colour FX, Palette and Darkness, each with when it next changes. Tap one to **lock** it: it holds while the others keep changing (replaces Lock palette)
- **Exclude…** leaves types and palettes out of the autopilot: tap Exclude…, tap the types (they turn **red**, priority 0), then **Done excluding**. Tap a red type again in Exclude mode to put it back at the priority it had. Excluded types stay on the page and still play when you tap them; the autopilot, **Re-roll** and **More like this** never pick them. They're saved in the rig file, so they stay out for every show on that rig, and this works under gig lock. Flash FX are only played by hand, so they can't be excluded
- **Hold a type down** (about half a second) **or right-click it** for its **settings** (v8, below). The small number on the right of each tile is its **priority**: tap the number to step it 1 → 2 → 3 → 4 → 5 → 1 (it doesn't play the tile). A dot top left means the tile has settings changed from the defaults
- **Feel controls**: speed, fade, fan, size, shift, for everything or per bank
- the **Haze** controls are here too, but they're separate: the auto show never touches haze
- **Why did it do that?** lists the autopilot's last decisions with the reason for each
- **Lights in the auto show**: how each light is used; change one or leave it out
- **Learn**: tap Learn, tap any control, then hit a pad or press a pedal: it's mapped and saved
- **Autopilot settings** (folded, v7): layer timing and between songs, saved with the rig

## FX settings (v8)

Hold or right-click a Move, Colour or Drum FX tile (or a palette) for its settings on this rig. Only what you change is saved; **Reset to defaults** clears it.

- **Darkness**: **Follow** (the Darkness value, as before), **Exempt** (always plays fully lit, e.g. Static palette or Candle) or **Reduced** (only part of the Darkness value: at 50 %, Darkness 80 % darkens it like 40 %). A Move FX's setting applies to its heads' colour; a palette's to the whole look while it plays.
- **Settings**: the effect's own (speed / period, size, spread, mirror, direction …). Empty = the bank's default, shown greyed in the box.
- **Priority 0-5**: how often the autopilot picks it. Still random, but a 5 comes up about five times as often as a 1 (default 3). 0 = excluded (red). It applies after the look quality, contrast and no-repeat rules and your ratings, so a type can't follow itself and a 5 lands a little under five times a 1 in practice. While every tile in a bank is at the same priority the autopilot picks as before (best fit for the mood).
- **Moods**: LOW / MID / HIGH it can run in. **Min / max time on screen**: how long a look with it stays (within the mood timer).
- **Preview 10 s** plays the running look with this type (or palette) in it, then goes back. Not under gig lock.
- **Duplicate** makes a **variant**: its own tile next to the original ("Fan out / in 2", rename it in the panel) with its own settings, priority and darkness, so a slow wide Fan and a fast tight Fan can both run. The autopilot picks it as its own type but never straight after its original (or the other way round). Variants can be played, mapped with Learn and deleted; the built-in types can only be excluded.
- Under **gig lock** the panel shows the settings but can't change them; Exclude mode still works.

In the rig file (format 8):

```yaml
autopilot:
  fx:
    fan: {priority: 4, darkness: exempt, moods: [mid, high], min_s: 20, params: {period_s: 8}}
    police: {priority: 0, restore: 4}    # excluded; restore = the priority it goes back to
  variants:
    fan_v1: {of: fan, name: Fan slow, params: {period_s: 14, size: 0.4}}
  palette_settings:
    ice: {priority: 0}
    white: {darkness: exempt}
```

Claude: `get_fx`, `save_fx`, `set_fx_priority`, `duplicate_fx`, `delete_fx`.

## The autopilot

It picks a Move FX + Colour FX + palette + ride settings and changes them on a timer that depends on the mood (60 s low, 40 s mid, 20 s high, give or take 20 %). It never repeats one of the last few looks, and each new look contrasts with the last (look quality rules).

- **Energy** comes from your MIDI only (no microphone): how many hits a second on inputs with the `activity` role, and how hard. Any instrument can drive it (give a keyboard or pad controller the roles)
- **Mood** follows the energy unless you set it with a button or pedal (MIDI action `mood`, mood: low / mid / high / up / down / auto); with no drum MIDI it's manual
- a **drum fill then a crash** changes the look early and fires a colour hit
- a **build** (energy climbing) gets faster, bigger looks; a **breakdown** (energy falling) gets slower, sparser ones
- **MASTER off**: drum flash owns the rig and the autopilot waits
- picking a show, scene or look by hand turns the autopilot off

### Layer timing (v7)

A look has four layers: **Move FX**, **Colour FX** (the drum FX goes with it), **Palette** and **Darkness**.

- **Together** (default, as before): all four change at once on each look change.
- **Staggered**: each layer runs its own clock, so something is always changing and there's never a hard cut. In Autopilot settings, set each layer to change every so many **seconds**, every so many **looks** (a look is the set's time: LOW 60 s, MID 40 s, HIGH 20 s), or only on a **new song** or a **new set**. **Spread** (± %) varies each interval at random so the layers don't line up again.
- Every single-layer change still passes the look quality rules (no clashing combinations, contrast with what's playing, no banned or recently played looks).
- **Lock** a layer by tapping it on the page (or the `autopilot_lock` pedal action with `layer: move | colour | palette | darkness`): it holds while the rest keep changing, in both modes. The old `palette_lock` action locks the Palette layer.
- Events still change the look at once: a fill and crash, a build or breakdown, **Next look** (the layers on a clock), a new song (all but **new set** layers), a new set (all but **new song** layers).

### Between songs

No `activity` hits for the **no activity time** (4 s) = the song has ended: the lights fade to the **between-songs look**. A count-in (evenly spaced hits on an input with the `count_in` role, e.g. sticks or the hi-hat pedal) or the first hit = the song is starting: straight back into the show. **Walk-on** and **walk-off** looks play from their buttons, or when a setlist starts and after its last song. A badge shows **Between songs** and the time since the last hit.

In **Autopilot settings › Between songs** (v7, saved with the rig):

- **Spot the gaps** on or off (off for continuous, DJ-style sets)
- **No activity time**: how much silence ends a song (default 4 s)
- **Min song length**: a gap in the first part of a song doesn't end it (default 20 s), so a quiet intro or a stop doesn't count
- **Song start**: the **first hit**, or a **count-in only** (then a stray hit while talking does nothing), and how many **count-in hits** (default 4)
- **Fade in / Fade out** of the between-songs look (empty: the LOW fade in, the song's own fade out)
- **Ignore inputs**: inputs that don't count as playing (a pad tapped while talking, the FCB1010)
- **Between-songs look**, **Walk-on**, **Walk-off**: a generated look (default) or **any of your scenes**. A scene plays exactly as you made it: no Darkness and no layer timing. MASTER and haze work as always

### Control priority

Highest first: **1** blackout, **2** MASTER off (drum flash), **3** Flash FX and Override buttons, **4** hold (the look stays, the autopilot stops changing), **5** the autopilot or the running show. Pedals: `autopilot`, `hold`, `look_next`, `look_prev`, `mood`, `walk_on`, `walk_off`, plus `autopilot_fx`, `autopilot_palette`, `exclude_palette` (v7), `autopilot_lock` (v7, `layer:`), `palette_lock` and the faders `feel_speed`, `feel_fade`, `feel_fan`, `feel_size`, `feel_shift`.

Set `release_fade_s` in the rig file (e.g. `0.5`) and letting go of a higher level fades back to the one below (MASTER back on, blackout off, a held Flash FX) instead of cutting.

### Settings (rig file)

```yaml
autopilot:
  moods: {low: 60, mid: 40, high: 20}
  variation: 0.2
  no_repeat: 4
  fade: {low: 4, mid: 2, high: 0.5}
  palettes: [warm, cool, band]
  timing: staggered                     # v7: together (default) or staggered
  layers:
    move: {every_s: 30, spread: 20}
    colour: {every_looks: 1}
    palette: {on: song}                 # song | set
    darkness: {every_s: 12, locked: false}
  between:                              # v7 (older shows had gap_s / count_in / talking here)
    on: true
    gap_s: 4
    start: first_hit                    # or count_in
    count_in: 4
    min_song_s: 20
    fade_in: null                       # null = the LOW fade
    fade_out: null                      # null = the song's fade
    ignore: [fcb_pad_1]
    look: {colour: static, palette: white, move: kit, feel: {speed: 0.5}}   # or {scene: talking}
  walk_on: {scene: intro}               # a generated look or a scene
  palette_settings: {ice: {priority: 0}}   # v8: palettes the autopilot never picks (see FX settings)
```

Show file format 8 (v8) moves format 7's `auto: exclude_fx` / `exclude_palettes` to priority 0 under `autopilot: fx` / `palette_settings`, renames the bank ids `sweep` / `sweep_dark` to `dir_wave` / `dir_wave_dark` wherever a look, preset or rating names them, and moves MIDI / kit triggers for Chase hit and Rig split hit to Colour hit (with a note in the log). Show file format 7 (v7) moves `gap_s`, `count_in` and `talking` into `between:` (`talking` is its `look`). Older shows upgrade once when opened, with a backup; a comment on those three lines doesn't move with them.

Every decision (time, energy, mood, look, why) is saved per gig in `logs/decisions-YYYY-MM-DD.jsonl` in app data; Claude reads it with `autopilot_status`.

## Presets

A preset is a saved look (FX + palette + ride settings). On the Autopilot page, **Save as preset** keeps the look that's playing; the preset buttons play one. Six starter presets come with the app and work on any rig.

- in a show, a step can be a preset: `{preset: verse_blues, hold_s: 30}`
- in a setlist, a song can be a preset (`{name: Intro, preset: calm_warm}`), or the autopilot playing only some presets: `{name: Encore, presets: [band_groove, fire_wave], mood: high}` ("only these looks for this song")
- MIDI action `preset` (preset: verse_blues) plays one from a pedal

**Re-roll, keeping:** tick what you like about the look (move, colour, drum, palette, Feel controls) and press **Re-roll** for a new look that keeps them. **More like this** offers four variations of the look (same FX, other palettes and settings). **Save this look as a scene** writes what's playing as a normal scene to edit in the scene builder.

## The Review page

At rehearsal, go through the looks the rig can do (filter by mood, moves or colours, palette): **👍**, **👎**, or **Ban**. Liked looks come up more, disliked less, and banned looks are never used again by the autopilot or the generator. **Auto-advance** steps through on its own every few seconds. On the Autopilot page, tap a line under "Why did it do that?" to open that look here. Ratings are kept in `ratings.yaml`.

## The generator

Below the review list, the generator makes normal, editable scenes and shows from the same FX banks, for the rig you're on:

- **Generate scenes:** a mood, a style (rock, ballad, acoustic, opera, dance), a palette and how many
- **Generate a show:** verse (low) / chorus (high) / bridge (mid) steps with fades, a scene per section
- **Starter show per song:** for each song in a setlist, from its `mood` and `bpm` (8 bars a section)

Every generated scene passes the same checks and rules as one you'd make by hand, and carries a `generated:` note with the seed and settings. The same seed always gives the same files; Claude can generate too ("make me five moody blue scenes for the slow songs") and then refine them.

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

FX types the autopilot never picks are priority 0 in `autopilot: fx` (v8; the Exclude… button writes it).

## The banks

**Move FX** (heads, inside the head limits): pan sweep, tilt sweep, circle, figure 8, fan out/in, swim, float, centre/kit (a head point tagged `band`), random positions (head points tagged `safe`, moving dark), crossfire, audience sweep, ballyhoo, mirror sweep.

**Colour FX:** static palette, rainbow, colour chase, chase in, chase out, carousel, sparkle, twinkle, colour fade, split, wave, pulse, random flash (pulses of light through random bits of the rig, several at once, each fading out); pixel bars: bounce, comet, fill/unfill; across the layout: gradient sweep, radial (from the stage centre, v8), plasma, bars, directional wave (v8: was "directional sweep"; a band of colour crossing the rig, one direction per pass: left to right, right to left, top to bottom, bottom to top), directional wave, dark between (the same over black, with the rig dark between passes); themed: fire, lightning, police.

**Drum-reactive** (from your named inputs' roles, MIDI only): kick pump, snare hit, tom roll, cymbal shimmer, fill build, velocity colour.

**Flash FX** (momentary): blinder, colour hit, strobe, blackout, freeze, flash and decay (v8: chase hit and rig split hit are gone; pads that used them fire colour hit). Map them to a pad or pedal with the MIDI action `flash_fx` (e.g. `{input: crash, action: flash_fx, fx: blinder}`): held while pressed, or for `length_ms`. They never touch the kick light or the haze, and the Flash FX blackout is not the BLACKOUT button: MASTER and haze carry on.

There's no strobe rate limit: strobe and lightning run at the rate set.

All of these are also ordinary effects in the scene builder (`move`, `palette`, `colour_fade`, `split`, `pulse`, `twinkle`, `comet`, `bounce`, `fill`, `fire`, `lightning`, `police`, `kick_pump`, `snare_hit`, `tom_roll`, `cymbal_shimmer`, `fill_build`, `velocity_colour`, `dir_sweep`, `random_flash`). In the scene builder, `dir_sweep` has **directions** (cycle, left_right, up_down, or one direction) and **gap** (the dark share of each pass); `random_flash` has flashes a second, **count** (started at a time), **tail** and **bit** (pixels per flash on a bar).

## Rig size

Each item says what it needs (heads, colour lights, pixels). Only what the rig can do is offered: two pars get colour fades, pulses, splits and the drum effects; add heads and the Move FX appear; add pixel bars and the pixel effects appear. Switching rig re-checks straight away.

## Feel controls

- **Speed** (¼× to 4×), **fade** (how soft colour changes are), **fan** (spread across the lights), **size** (how big the movement, how wide the pixels, how dense the sparkle), **shift** (phase offset)
- each can be set for everything and per bank (move, colour, drum) on top
- a **palette** (Warm, Cool, Fire, Ice, Neon, White, Band colours or your own) is picked from the palette bank; lock the Palette layer to keep it

## Darkness

**Darkness** (Autopilot page, under the Feel controls) makes the show darker by putting **black into the effects**, not by dimming. At 0 the looks play as programmed. As it goes up, sweeps get narrower lit bands, colour cycles and palettes get black slots (50 % = colour, black, colour, black), gradients and rainbows get gaps between colours, and still colour looks get a regular pattern of black lights or pixels (alternate, every third ...) that moves with the look's shift. At 100 % the rig is black.

- **Black is colour off.** Dimmers stay where they were, MASTER still owns on/off, the haze is untouched, and there's no glow: black is 0.
- The **kick light** is exempt and always plays its look. From v7 it takes the look's colour like every other light (the palette, or the colour FX running), instead of white.
- Only the **Autopilot's** looks: hand-made scenes and shows play as made. **Override** sits above it and ignores it.
- **Moving heads** keep moving while black.
- With MASTER off a **drum hit** flashes what the pattern has lit; black slots stay black.
- The edge between lit and black is as soft as the look's **fade** (0 = a hard cut), and every change eases in over the same fade, so a pedal sweep never steps.
- **Manual** (as before): the slider or pedal sets it; it holds until the next set change.
- **Auto** (v7): two markers on the slider bar, **Min** and **Max**. Darkness moves between them on its own, on the Darkness layer (its own clock when staggered, each look when together), spending **Time at Max** (%) of the time at Max and the rest at Min. It stays at each marker at least one Darkness-layer interval, so it never flips back and forth. Moving the slider or pedal in Auto goes back to Manual (the page says so).
- **Store for set** saves what's shown for LOW, MID or HIGH: the slider's value in Manual, or Auto with its markers and time at Max; changing set loads it.
- **Pedal:** give an expression pedal CC the `darkness` role on the MIDI page (or map the `darkness` action to it). See [MIDI](midi-osc.md).

Each layer of a look can carry its own `lit:` (0-100 %, default 100), and the autopilot renders `lit x (1 - darkness)`: a look at 60 % with Darkness at 50 % plays 30 % lit.

In the rig file:

```yaml
autopilot:
  darkness: 0                 # % at start (Manual)
  darkness_mode: manual       # v7: manual | auto
  darkness_auto: {min: 0, max: 60, time_at_max: 30, hold_s: null}   # hold null = the layer's interval
  set_darkness: {low: 60, mid: 30, high: {mode: auto, min: 10, max: 80, time_at_max: 25}}
```

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
