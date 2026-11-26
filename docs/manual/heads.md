# Moving heads and head points

Each head needs different pan/tilt values to hit the same spot, so aim points are stored **per head**, as named **head points** in the rig file. Scenes, busk buttons and the auto show use the point's name, so re-aiming a point updates everything that uses it. Rooms differ, so points belong to a rig config.

## Aiming

On the **Heads** page, drag on a head's pad to hold it at a spot. Head limits still apply. **Fine** makes a drag move the head a tenth as far, for small adjustments. Where a head type has its pan/tilt range set, the pad shows degrees. **Release** hands the head back to the show.

## Storing a point

Hold the heads where you want them, type a name (e.g. `singer`), a description ("lead singer mic, centre front, head height"), tags (`band, safe`) and, if you like, a rough place on stage (across, depth, height). **Store to point** saves the held heads into it; heads you didn't hold keep what the point had.

A point doesn't need every head. A scene that asks for a point a head doesn't have leaves that head where it is, and the show check says so.

A point can't be stored inside a head's no-go zone (its head limits). If limits change later, points outside them are listed in yellow; they're held at the limit until you re-aim them.

## Focus mode and the re-focus walk

**Focus** on a point lights up one head at a time: aim it, **Store and next**, and so on. **Re-focus walk** does that for every point, head by head: quick to do at load-in.

## In the rig file

```yaml
positions:
  drum_kit:
    description: Drum kit, centre back, cymbal height
    tags: [band, safe]
    stage: {x: centre, y: back, z: mid}
    heads:
      mh_a: {pan: 0.42, tilt: 0.30}
      mh_b: {pan: 0.58, tilt: 0.30}
```

pan and tilt are 0-1 of the head's range, sent at 16-bit on heads with fine channels. Tags let the auto show (from v3.3) pick only some points, e.g. `band` and `safe`. Claude reads the descriptions and tags to know where to aim.
