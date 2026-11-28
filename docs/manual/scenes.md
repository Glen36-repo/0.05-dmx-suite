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

**`lit:`** (0-100 %, on a layer or the whole scene) puts black into the layer's effect: a narrower band in a sweep, black slots in a colour cycle or palette, gaps in a gradient, and a regular pattern of black lights or pixels in a still colour. Black is colour off, never the dimmer, so it's the way to make a look darker under the 0.05 band profile. The Autopilot's Darkness scales it further for its own looks ([Darkness](auto-show.md#darkness)). In a step scene, set `lit` per light in a step (Colour tab, Lit %).

## Copy and paste a look

On the Scenes page, **Copy look** (Ctrl+C) copies the layer you're editing, or, with no layer picked, the look of the first selected light. Select other lights and **Paste to selection** (Ctrl+V): the look is added as one layer per kind of light, keeping only what each can do. Position and movement only go to heads that move, gobo and colour wheel only to lights that have them, and colours go to everything.

## Undo

Every saved change can be undone and redone (Ctrl+Z / Ctrl+Y, or the Files page) for as long as the app is open. Older changes are in the backups on the Files page.

## Step scenes

A step scene is made of steps you program by hand, like Daslight: each step is a fixed look, and the scene runs through them with a step time and a fade time.

Tick **Step scene** next to the scene's name. The page becomes the step editor (v4): the **step list** on the left, the **stage** in the middle, the **programmer** on the right, and the scene's settings in a bar across the top (show colour, step time or beats, fade time, playback, next step on, how heads move, dark time, and how long a cycle lasts).

1. **Pick lights** on the stage (tap, shift-tap, drag a box, lasso) or a group tab; [ and ] step through the lights one by one.
2. **Set values in the programmer.** Its tabs follow what the lights have: **Colour** (swatches, palettes, ◐ the colour wheel, red / green / blue / white / amber / UV faders, Colour off), **Position** (drag on the pad; the dashed box is the head's limits; head points; exact pan and tilt; none for colour-only heads like the U'Kings), **Beam** (gobo, colour wheel, strobe, zoom, focus, frost, prism, speed: only the ones the lights have) and **Pixels** (each pixel's colour, or Fill, A to B, A B A B). **Capture** takes what the lights show now.
3. Each value says where it comes from: **set in this step**, **tracked from step N** (in italics) or **in the programmer**. **Clear** takes it out of this step so the step before shows through again; **Release** turns it off from this step on.
4. **Record** puts the programmer into the step (what it doesn't touch stays); **Record over** makes the step just the programmer; **Record as new step** adds a step after this one; **Update step** changes only what the step already sets.
5. The step list: click a step to go to it; **+** inserts one after it, **⧉** duplicates, **⎘** copies (paste into another step or scene), **✕** deletes, drag to reorder. Tick several to set their step and fade times together or to **Loop these**. A step with a problem is outlined in red (hover for why); a position outside the head limits is marked amber.
6. Each step can have its own name, step time, beats, fade time and how heads move (**This step's name and times**); empty = the scene's.
7. **◀ ▶ ■ ▶|** and the step number play, stop and move through the steps. **Live** sends the step to the rig as you program it, programmer included; untick it to work blind. **Tap** sets the tempo when steps last a number of beats.
8. **Undo / Redo** (Ctrl+Z / Ctrl+Shift+Z) work inside the editor before you save; Page Up / Page Down move between steps. **YAML** shows the scene as text: edit it and **Use this YAML**.

### Single pixels of a bar

On the scene editor's stage each segment of a pixel bar is its own target (only here: the Layout, Live, Override and Autopilot pages pick whole lights). Click a segment; shift-click to add one, shift-drag along a bar for a range, ctrl-click to toggle, double-click for the whole bar; the lasso takes just the segments inside it. Hover shows which segment it is (bar_2 px5), counted the way the bar is mounted (see **reverse** on the Layout page). The **Pixels:** buttons pick all, none, invert, odd, even, every Nth, first / last N, left / right half, the centre, or the same segment on every bar; **Save as pixel group** names a selection (e.g. bar_tips) for any scene or step.

A pixel selection is colour only: MASTER owns each segment's dimmer and strobe (0.05 band). In the file it's written as `bar_1:px1-4`, `bars:px1,8`, `bars:odd` (also `even`, `first3`, `last3`) or a pixel group's name; the other segments keep what's under them, else stay off.

**Playback:** loop, once, or bounce (forward then back). **Next step on:** the timer, a pedal or button only (MIDI actions `step_next` / `step_back`), or a named input such as the snare: every hit moves it on.

**Heads move:**

- **dark**: the head goes dark, moves, then fades in at the new spot (the default under the 0.05 band profile). Even on a cut it gets a moment (`dark_s`, 0.3 s) dark to get there.
- **lit (glide)**: the head glides from the old spot to the new one over the fade time, staying lit (the default under the generic profile). Make the fade as long as the step for a slow, continuous move. Heads with fine channels glide in 16-bit; the head's own speed channel is set to fastest while it glides so its motor doesn't lag. The glide stays inside the head limits.

Set it for the scene, or per step.

**Live:** Override faders or MIDI faders `step_speed` (0.25× to 4×) and `step_fade` (no fades to 2× fades) change the step scene that's playing.

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

