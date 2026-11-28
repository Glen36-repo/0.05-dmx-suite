# Shows and setlists

A **scene** is one look or effect. A **show** strings scenes together, like a Daslight super scene. A show has **sets** (e.g. LOW / MID / HIGH, or verse / chorus); the band's pedals pick a set.

## Steps

A set is a list of steps. Each step plays one scene, then moves on after:

- **times through**: the scene's cycle (`length_s`, or its longest effect) played N times
- **seconds**: a fixed time
- **beats** or **bars**: at the current tempo (see Beat sync)

Each step can fade in from the one before (seconds, 0 = cut); otherwise the set's fade is used. A set plays its steps in order or at random, and loops or stops on the last step.

Fades blend colours. A moving head that has to move goes dark, moves, then fades in, so you never see it swing across the stage.

## Auto sets

Instead of steps, a set can make a fresh scene every step from a style: colours, energy (low, mid, high), head colours (matching, white, contrast), patterns and movement. It only uses lights in the rig that's running.

## Building a show

On the **Shows** page:

1. Pick a show, or **New show** and give it a name.
2. **Add set**, then **Add step** for each scene, in order.
3. Set each step's hold (times through, seconds, beats or bars) and fade; use ↑ ↓ to reorder.
4. Set the set's fade, order and loop.
5. **Save show**. Start it from the Live page like any other show.

While a show runs, the Live page lists the set's steps with the current one highlighted, the repeat count and the time left. Tap a step to jump to it.

## Setlists

A setlist is the night's song order. Each song plays a show (and set) or a single scene, and can turn MASTER on or off when it starts. Edit setlists on the Shows page: add, reorder and remove songs, then save. On the Live page, tap a song to jump to it, or step through with a pedal.

## Beat sync

Pick where the tempo comes from in the rig file (`tempo: {source: ...}`):

- **tap**: a pedal, key or button tapped on the beat
- **kick**: follows the kick drum (the last 4 beats; fills ignored)
- **midi_clock**: MIDI clock from a drum machine, DAW or keyboard

You can also type a BPM on the Live page. If the kick or clock stops, the last tempo is kept for 30 s, then effects go back to their own timing. The speed fader (or a mapped control) runs effects from a quarter to four times speed. The top bar shows the tempo and pulses on the beat.
