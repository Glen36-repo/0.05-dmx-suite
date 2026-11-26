# Scenes

A scene is a stack of layers. Each layer picks some lights and gives them a colour, position or gobo, an effect, or both. Layers apply in order, top first; a later layer covers what's below it unless you change its **blend**.

## Building a scene

On the **Scenes** page:

1. Pick lights on the layout: tap, drag a box, or use a group button (each shows how many lights it has; **None** clears the selection, **Invert** swaps it).
2. **Add layer for the selected lights.**
3. Choose an **Effect**, or none for a plain colour, position or gobo. The settings for that effect appear below it.
4. **Across the lights** sets how the effect runs over the lights:
   - **mapping:** in the order they're listed, or **spatial**, by where they are on the layout. Spatial makes a wave cross the whole rig as one picture.
   - **direction:** forward, reverse, centre out, out to centre, random, or an **angle**. For spatial effects, an arrow on the layout shows the direction.
   - **groups of:** move the lights in blocks.
5. **Level** and **Blend** mix the layer with the layers below it:
   - replace covers what's below;
   - brightest keeps whichever is brighter;
   - add adds the two together.
6. Tick **Live preview on the rig** to see it as you go. A layer with a problem goes red, and the reason shows above the form.
7. Name it and **Save scene**.

Use ↑ ↓ to reorder layers, **M** to mute one (it's skipped), ✕ to remove it.

## Effects

| Effect | What it does |
| --- | --- |
| Colour chase | Steps or fades through a list of colours |
| Pixel chase | A block of lit pixels runs along the bars |
| Flash | Lights flash on and off at a rate |
| Sweep | Moving heads swing between two positions |
| Random move | Heads jump to random spots, optionally dark while moving |
| Rainbow | Colours go round the colour wheel |
| Sparkle | Random lights or pixels light up |
| Wave | Brightness rolls across the lights |
| Strobe | Everything flashes together, fast |
| Circle, Figure eight | Heads draw a circle or 8 round a position |
| Linear wave | A wave crosses the layout at any angle |
| Radial | Rings spread out from the middle, or close in |
| Gradient sweep | A blend of colours scrolls across the layout |
| Bars | Hard-edged bands move across the layout |
| Noise / plasma | Slowly drifting blobs of colour |

Moving heads always stay inside the rig's head limits. Colour-only heads can't be given a movement effect.

## In the file

Scenes are plain text in `scenes/<name>.yaml`; the builder writes the same thing you could type:

```yaml
version: 3
name: Blue wave
layers:
  - {fixtures: [washes], colour: deep_blue}
  - {fixtures: [bars], effect: linear_wave, colour: white, angle: 45, level: 0.7, blend: max}
```

Under the "generic" profile a layer can also set `intensity` (0-1).

## Copy and paste a look

On the Scenes page, **Copy look** (Ctrl+C) copies the layer you're editing, or, with no layer picked, the look of the first selected light. Select other lights and **Paste to selection** (Ctrl+V): the look is added as one layer per kind of light, keeping only what each can do. Position and movement only go to heads that move, gobo and colour wheel only to lights that have them, and colours go to everything.

## Undo

Every saved change can be undone and redone (Ctrl+Z / Ctrl+Y, or the Files page) for as long as the app is open. Older changes are in the backups on the Files page.

## Step scenes

A step scene is made of steps you program by hand, like Daslight: each step is a fixed look, and the scene runs through them with a step time and a fade time.

1. Tick **Step scene** next to the scene's name.
2. Select lights on the layout and press **Set the selected lights**, then pick their colour (◐ for the colour wheel), head point and gobo. Or press **Capture what they show** to take what the lights are doing now.
3. **Add step**. A new step keeps everything from the one before (tracking), so you only set what changes.
4. Each step can have its own **Step time** and **Fade time**; leave them empty to use the scene's (under **Step and fade times, playback**). With beat sync, a step can last a number of **beats** instead.
5. **▶** previews one step on the rig; **Play from this step** plays the saved scene from there.

**Playback:** loop, once, or bounce (forward then back). **Next step on:** the timer, a pedal or button only (MIDI actions `step_next` / `step_back`), or a named input such as the snare: every hit moves it on.

**Heads move:**

- **dark**: the head goes dark, moves, then fades in at the new spot (the default under the 0.05 band profile). Even on a cut it gets a moment (`dark_s`, 0.3 s) dark to get there.
- **lit (glide)**: the head glides from the old spot to the new one over the fade time, staying lit (the default under the generic profile). Make the fade as long as the step for a slow, continuous move. Heads with fine channels glide in 16-bit; the head's own speed channel is set to fastest while it glides so its motor doesn't lag. The glide stays inside the head limits.

Set it for the scene, or per step.

**Live:** busk faders or MIDI faders `step_speed` (0.25× to 4×) and `step_fade` (no fades to 2× fades) change the step scene that's playing.

Colours fade; colour wheels and gobos change halfway through a fade; lights the new step doesn't use fade to off. A step scene can also have **effects on top** (e.g. a sparkle over the steps): the normal layers list.

```yaml
name: Intro hits
type: steps
step_s: 2
fade_s: 0.5
playback: loop
steps:
  - {name: red bars, set: {bars: {colour: red}}}
  - {name: blue heads, set: {heads: {colour: blue, position: drum_kit}}, fade_s: 0}
  - {name: heads to crowd, set: {heads: {position: audience_l}}, move: lit, step_s: 4, fade_s: 4}
  - {name: all white, set: {all: {colour: white}}, step_s: 4, fade_s: 2}
```

