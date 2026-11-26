# Scenes

A scene is a list of layers, applied in order; a later layer wins on the same light. Each layer picks lights (fixtures or groups) and sets a colour, position, gobo, or runs an effect: `colour_chase`, `pixel_chase`, `flash`, `sweep`, `random_move`.

```yaml
version: 2
name: Blue chase
layers:
  - {fixtures: [bars], effect: pixel_chase, colour: blue, width: 3, period_s: 2}
  - {fixtures: [washes], colour: deep_blue}
```

Colours, positions and gobos are named in `palettes.yaml`. Under the "generic" profile a layer can also set `intensity` (0-1).

Coming in v2: building scenes on screen from a selection of lights (R3), spatial effects across the layout, spread and direction controls (R3).
