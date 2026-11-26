# Scenes

A scene is a stack of layers. Each layer picks some lights and gives them a colour, position or gobo, an effect, or both. Layers apply in order, top first; a later layer covers what's below it unless you change its **blend**.

## Building a scene

On the **Scenes** page:

1. Pick lights on the layout: tap, drag a box, or use a group tab.
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
