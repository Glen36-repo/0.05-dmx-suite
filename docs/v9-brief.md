# 0.05 DMX Suite — v9 brief (28/11/2026)

Repo: Glen36-repo/0.05-dmx-suite. Saved as `docs/v9-brief.md` on branch `v9` (from `v8`). Builds on v8 — start once v8 is merged (needs the v8 Heads page pads, saved-point crosshairs, centrelines, point-based Move FX and the FX settings panel).

Scope: **moving-head calibration and stage space** — the software learns where each moving head is in the room and how it's mounted, by aiming every head at a few measured marks on the stage. Then points, zones and movement effects can be defined once in metres on the stage, for any number of heads. Plan before writing code (`docs/v9-plan.md`, same style as v7 / v8). Rules unchanged (colour only, never haze, MASTER owns on/off, head limits always enforced at output — rule 8).

Background (from the code, 28/11):
- Head points are stored per head as pan / tilt 0–1 (`rig.Point.heads`), so every point must be aimed separately on every head, and again at every venue.
- Mounting isn't known per fixture: only `invert: true` on a fixture **type's** pan / tilt channel (`fixtures.py`, `INVERTIBLE`), which flips every head of that type. A hung head and a floor head of the same type can't both be right.
- Generated Move FX (circle, sweeps, Pendulum, Tilt nod, Sky scan, Crossfire, Mirror …) work in head angles, so "up", "left" and size differ per head and per mount.
- Fixture types carry `pan_range` / `tilt_range` in degrees (`fixtures.py`, default 540 / 270 when not set — the MHL36 type doesn't set them, so it's using the defaults).

---

## 1. Calibration model
- Per rig (venue), per moving head, solve a **head pose**: position (x, y, z in metres, stage frame) and orientation (yaw, pitch, roll) — which covers upright, hung, side-mounted and any twist — plus optional refinement of the head's real pan / tilt degree range and zero offsets.
- **Stage frame**: origin = front-centre of the stage at floor level; x = stage left → right (audience view), y = downstage → upstage, z = up. Shown on the Layout page with the v8 centrelines.
- **Solve**: each head aimed at N known marks gives N pan / tilt pairs → least-squares fit of the pose (6 unknowns) + tilt zero (1). 4 marks = minimum with an error check (8 equations, 7 unknowns); 5+ marks also refine the pan / tilt degree ranges (9 unknowns). Report a per-head **error** (cm at the marks) and flag any mark whose residual is far above the rest (probably mis-aimed or mis-measured).
- 16-bit pan / tilt used where the fixture has fine channels; warn if not (lower accuracy).
- Stored in the rig file: `calibration: {marks: {...}, heads: {<fid>: {pos, rot, pan_range, tilt_range, pan_zero, tilt_zero, error_cm, date}}}`. No calibration = everything works exactly as today (head angles).

## 2. Calibration wizard (Heads page)
1. **Stage**: stage size (w × d, m) and the origin (front-centre, floor). Picture shows the frame.
2. **Marks**: place 4 tape marks (5 to also measure the heads' real pan / tilt ranges); enter each one's x / y (z = 0, or a height for a mark on a riser / wall) — or pick the **standard square** (e.g. 2 m × 2 m centred on the origin, 1 m downstage) and just tape it. Marks are named (M1–M4) and shown on the Layout stage view.
3. **Aim**: one head at a time, one mark at a time. Big pad (v8 item 13), fine mode, arrow-key nudge (Shift = finer). That head goes to a narrow, bright white spot (zoom / focus / gobo open where the fixture has them); all other lights off. **Next** stores the pan / tilt for that mark. Skip a mark a head can't reach (limits / obstructions) — it needs at least 3.
4. **Solve**: shows each head's position (top and side view), mount (Upright / Hung / Side-L / Side-R + angles), error per head and per mark; bad marks highlighted with **Re-aim**.
5. **Check**: all calibrated heads go to a chosen mark (or the stage centre) together; the beams should land on one spot. **Save** or **Back**.
6. **Quick re-cal** (same rig on the same stands / truss, new room): aim at 2 marks to re-anchor the stage frame; poses relative to each other kept.
- Runs with the show stopped (not under gig lock). Undo = previous calibration kept as a backup (`list_backups` / restore).
- Resumable: leaving mid-way keeps the marks already aimed.

## 3. Stage-space points
- A point can be a **stage point** (x, y, z in metres) instead of per-head pan / tilt. Each calibrated head works out its own pan / tilt to hit it, every frame.
- Saving a point from the Heads page on a calibrated rig: aim one head at the spot → the software intersects the beam with the floor (or a chosen height) → offers "save as a stage point for all heads".
- Existing per-head points keep working; a **Convert** button turns a per-head point into a stage point (average of the heads' beams — shows the spread).
- New heads added to the rig get every stage point automatically once calibrated.
- Points shown as markers on the Layout stage view; drag to move (heads follow live).

## 4. Stage-space Move FX
- Move FX get a **Space** setting in the v8 settings panel: **Head** (today's behaviour, angles) / **Stage** (shapes and positions in metres on the stage). Default Stage on a calibrated rig for the effects below; Head when uncalibrated.
- Stage mode, for each effect:
  - **Circle / Figure 8 / Spiral / Square / triangle / star / Lissajous**: drawn on a plane (floor, back wall or a height) around a stage point, size in metres — all heads draw the same shape on the same spot (or spread / phase offset along it, v8 item 14 phase setting).
  - **Pan / tilt sweeps, Pendulum, Sky scan**: directions are room directions (left / right / up), the same on every head whatever the mount. Sky scan always goes to the ceiling; Tilt nod always dips down.
  - **Fly-out, Converge / split, Crossfire, Mirror, Fan**: exact — converge lands on one spot; crossfire crosses at a real point in the air; mirror uses the stage x = centreline (v8 item 12); fan spreads by equal angles on the floor.
  - **Position / Point tour / Beat stabs** (v8 items 11, 15): use stage points.
  - Optional **constant floor speed**: sweep speed in m/s on the target plane, so near and far heads move the beam at the same speed.
- **Follow** (new Move FX): heads track a moving stage target together — drag on the stage view, MIDI / CC, or a path between stage points (e.g. kit → singer over 8 beats).

## 5. Room-space zones and limits
- v7 exclusion zones and v8 head limits can also be defined in the room once for all heads:
  - **Audience box** (x / y area + height band, e.g. 1.0–2.0 m above the floor): no beam may pass through it — eye-height safety in one setting.
  - **No-go boxes** (mirrors, bar, a doorway).
- Each frame a head's target that would put the beam through a room zone is moved to the nearest allowed point (same hysteresis as v7 C1 so a sweep slides round, doesn't snap across), or blacked if the zone is set to black.
- Per-head pad zones / limits (v7 / v8) still apply on top.
- **Safe park**: blackout / park sends heads to point at the stage floor near their own position, never into the audience box.

## 6. Mounting (replaces the per-head mount setting idea)
- Mount is a result of calibration (item 1), shown on the Heads page per head (Upright / Hung / Side-L / Side-R + angles). Without calibration: a manual **Mount** dropdown per head (Floor / Hung / Side-L / Side-R) as a fallback, so "up" on the pad and generated moves are right even uncalibrated.
- The Heads page pad uses the mount so dragging up always moves the beam up in the room.
- The type-level `invert` stays for fixtures whose channels genuinely run backwards; mount is per head on top of it.

## 7. Views
- Layout stage view: heads at their solved positions (top view), beams drawn from them to their targets in stage mode, stage points and room zones shown.
- Heads page: small top / side view per head with its beam.
- Simulator page (v8 reference) can later use the real geometry.

## 8. MCP / API
- `calibration_status`, `calibration_start`, `calibration_aim {fixture, mark}` (stores the head's current pan / tilt), `calibration_solve`, `calibration_save`, `calibration_quick {marks}`.
- `save_point` takes `stage: {x, y, z}`; `list_points` returns both kinds.
- `aim {fixture | group, x, y, z}` — point heads at a stage location now.
- `save_room_zone` / `delete_room_zone` / `list_room_zones`.

## Acceptance (on the rig)
- After the wizard, both MHL36 converge on the kit mark within ~10 cm; reported error ≤ 10 cm.
- A head hung upside down and one on the floor: Sky scan sends both to the ceiling; a stage-mode circle draws the same circle on the floor from both.
- Audience box set: no Move FX ever puts a beam through it (test with every Move FX in stage mode for 60 s each).
- Quick re-cal with 2 marks restores convergence within ~15 cm after moving the rig to a new room.
- Uncalibrated rig: every v8 Move FX behaves exactly as before.

## Open items
1. Default mark layout for the wizard: 2 m × 2 m square 1 m downstage (assumed) or the four corners of the stage.
2. Whether to refine pan / tilt ranges in the solve (assumed yes when a head has 5+ marks; with 4, trust the fixture type's figures) — see `docs/v9-plan.md` decision 2.
3. MHL36: the fixture type already has 16-bit pan / tilt (`pan_fine`, `tilt_fine`) but no `pan_range` / `tilt_range` set (defaults 540° / 270° used) — confirm the real ranges from the manual / on the fixture, or use 5 marks so the solve estimates them.
