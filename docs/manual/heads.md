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

## Exclusion zones

Areas a head must never point into: a mirror, a glass wall, the front row's eyes. They're part of the safety rules (rule 8, with the head limits), so no scene, show, Autopilot look, test pattern or Claude can get round them. Zones are kept in the rig file, so each venue's rig has its own.

1. Tap **Zones** above the pads and choose **Rectangle** or **Circle / ellipse**.
2. Drag on a head's pad to draw one (pan left to right, tilt bottom to top, as for aiming). Drag inside it to move it, its corner to resize it. Tap an existing zone (red hatch) to change it.
3. Give it a name, tick **Colour off inside** if wanted, choose **This head** or **Every head of this type**, then **Save** (or **Delete zone**).

What happens at output:

- A move into a zone stops at its edge **on the side the head came from**, and stays on that side while the target is inside, even when the target crosses the zone's middle (no snapping across).
- A sweep that goes through a zone slides round its edge instead, and catches up once the way is clear. While it does, the head never moves faster than the zone speed (rig `zone_speed`, % of the range a second, default 100), and the line between two frames never cuts into the zone.
- **Colour off inside** zones don't stop the head: it goes where it's told, dark, while the target is inside.
- A pad shows **held at <zone>** (and an amber outline) while its head is held at an edge.
- Head points and scene positions inside a zone are flagged, like ones outside the head limits.

```yaml
zone_speed: 100           # % of the range a second while going round a zone
head_zones:
  mh_a:
    - {name: Mirror, shape: rect, pan: [40, 55], tilt: [10, 30]}
    - {name: Front row, shape: ellipse, centre: [50, 80], radius: [20, 8], black: true}
```

Claude: `list_head_zones`, `save_head_zone` (scope `head` or `type`), `delete_head_zone`.
