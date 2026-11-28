# v9 build plan (28/11/2026)

Brief: `docs/v9-brief.md`. Base: v8 parts as they are pushed (`v8-a-foundation`, then `v8-b-heads-move`); A1 starts now on `v7-e-files`. **Built in parallel with v8** — see "Parallel with v8" below; that section overrides anything else here. File paths checked against `v7-e-files` and `docs/v8-plan.md` (28/11/2026).
Rules unchanged unless stated below. Every hard rule keeps its tests under both profiles (`tests/rulecheck.py`).

## Conflicts with SCOPE.md (brief wins; SCOPE updated in the same commit as the change)
| SCOPE / code today | Brief | Change |
|---|---|---|
| Head points (v3): per head pan / tilt, `rig.Point.heads` | Item 3: stage points in metres | `Point` gets optional `at: (x, y, z)` (`stage` is already the place labels); per-head points unchanged; a point is one kind or the other |
| Rule 8: head limits + v7 exclusion zones (pad %) | Item 5: room zones too | Extend rule 8 (CLAUDE.md, SCOPE, `rules.py` doc): "head limits, pad exclusion zones and room zones" |
| `invert` per fixture type only | Item 6: mount per head | Mount per head from calibration, manual fallback; `invert` unchanged and applied first |
| Move FX in head angles | Item 4: Space = Head / Stage | Head = today (bit-identical). Stage only on calibrated heads |
| Blackout: heads stay where they are | Item 5: safe park | Park is opt-in per rig (`calibration.safe_park: true`), default off so v8 behaviour holds until set |

## Decisions (28/11/2026, from the brief's assumptions)
1. Default marks: 2 m × 2 m square, 1 m downstage of the origin (M1 front-left, M2 front-right, M3 back-right, M4 back-left), plus optional M5 at centre-back. 4 marks = pose with an error check; 5+ marks = also a check for a mis-aimed mark.
2. **Revised in A1 (28/11/2026, from the synthetic tests): the solve fits the pose only (P, R: 6 unknowns); tilt zero and the pan / tilt ranges come from the fixture type.** Solving tilt zero too from the 2 m square (7 unknowns) let it trade off against the position: the fit error looked tiny (≈ 0.2 cm) while the beams missed by up to 85 cm with 0.2° aiming noise. With it held, the same aims land within 10 cm at every mark and the kit (80 random heads, worst under 10 cm). Ranges and tilt zero are refined only from **wide marks** (`stagegeo.can_refine`: 6+ marks, ≥ 4 m across, one ≥ 1 m off the floor, e.g. the stage corners, front-centre and a mark on the back wall at 2.5 m); those recover a 10 % wrong range to ~2 % and tilt zero to ~0.003. The result is offered as "update fixture type" (all heads of that type) or kept per head. Brief open items 2 and 3 follow: the MHL36 ranges are either set on the fixture type from the manual, or measured once with the wide marks.
3. **No new dependency**: the solver is plain Python (Levenberg–Marquardt on ≤ 9 parameters, numeric Jacobian, a few ms). No numpy / scipy in the installer.
4. Stage frame in metres: origin front-centre at floor level, x stage left → right (audience view), y downstage → upstage, z up.
5. Calibration is per rig file (per venue). Quick re-cal (2 marks) keeps the heads' poses relative to each other and re-fits only the rig-to-stage transform (x, y, yaw — 3 unknowns, 4 equations).
6. Uncalibrated heads and Space = Head stay bit-identical to v8 (golden frames).

## Parallel with v8 (28/11/2026, revised against `docs/v8-plan.md`)
v8 and v9 are built at the same time. v8's plan orders its parts for v9 and fixes the interfaces v9 builds on in v8 Part A (`v8-a-foundation`) and Part B (`v8-b-heads-move`). This section overrides anything below that says otherwise.

**v8 interfaces used**
- **Points:** every lookup goes through `Palettes.position` / `positions_for` (`palettes.py`). Stage points resolve there, not in `rules._position`. `rig.Point.stage` already holds rough place labels (left / centre / right), so metre coordinates use a new key: `at: [x, y, z]`.
- **Aim:** every Move FX writes through `Run.aim(un, pan, tilt)` (`effects/base.py`). The Space = Stage branch goes there.
- **FX params:** new Move FX params (`space`, `plane`, `height`, `size_m`, `centre_point`, `floor_speed`) are added to the effect's `Param` list; the v8 settings panel and MCP pick them up.
- **Centre:** `rig.layout_centre()` (mirror about the stage centreline).
- **Limits / zones:** applied last in `rules._position` (rule 8); room zones go after the pad zones there.
- **Heads pad layers:** shading → zones → crosshairs → live dot; v9 adds its layers on top. The wizard uses the v8 big pad, no separate pad.
- **Format:** v8 = 8, frozen after v8 Part A. v9 owns 8 → 9, bumped in v9 Part A2.

**Branch timeline**
| When | v9 work | Base |
|---|---|---|
| Now (v8 parts not pushed) | A1 `stagegeo.py` + `tests/test_stagegeo.py` — new files only, no imports from v8 code | `v9-a-solver` (on `v7-e-files`) |
| `v8-a-foundation` pushed | Rebase `v9-a-solver` onto it; A2 rig model + `FORMAT = 9` | `v8-a-foundation` |
| `v8-b-heads-move` pushed | Rebase; then B → C → D → E → F | `v8-b-heads-move` |
| Before each v9 PR | Rebase onto the latest v8 part (v8 never rebases onto v9) | — |

- Stack: `v9-a-solver` → `v9-b-wizard` → `v9-c-stage-points` → `v9-d-stage-fx` → `v9-e-room-zones` → `v9-f-views`.
- Merge order: #16 → v7 A–E → v8 A–E → v9 A–F.

**Conflict boundaries with v8 Parts C–E** (built at the same time): those touch colour FX, flash, the `fxbanks.py` bank list, `en.json`, CHANGELOG, SCOPE and the MCP tool files. v9 only appends separate blocks to those shared files; its logic lives in new files (`stagegeo.py`, `calibration.py`, `calibrate.js`, new tests).

**Verification additions**
- Goldens bit-identical on an uncalibrated rig, with per-head points and with Space = Head.
- Full suite and `tests/rulecheck.py` (both profiles) rerun after every rebase onto a new v8 part, including the room-zone test over the v8 Move FX.
- On the rig (gig laptop, from the brief): two MHL36 converge within 10 cm; hung and upright heads match in Sky scan and the circle; quick re-cal within 15 cm. MHL36 pan / tilt ranges remain brief open item 3.

## Maths

**Head model.** For head h with pan p, tilt t (0–1, after `invert`):
- φ = (p − 0.5) · pan_range, θ = (t − t₀) · tilt_range (degrees → radians); t₀ = tilt zero (where the beam is along the yoke axis).
- Beam in the head frame: d_h = (sin θ cos φ, sin θ sin φ, cos θ) (z = yoke axis, out of the base).
- World: d_w = R_h · d_h, beam from position P_h. R_h from a rotation vector (3 params); P_h (3 params). Pan zero is absorbed by R's rotation about the yoke axis, so it isn't a separate unknown.

**Solve (per head).** Marks M_i with measured (p_i, t_i). Residual per mark = d_w(p_i, t_i) − (M_i − P_h)/|M_i − P_h| (3 components, ≈ the angle for small errors; also rules out pointing the opposite way). Unknowns: P (3) + R (3) = 6; + t₀, pan_range, tilt_range = 9 for wide marks only (decision 2). 3 marks fit exactly (warning: no error check). Starting guesses: a 5 × 5 × 4 grid of positions round the marks, each with its best rotation (Horn's quaternion method), the 6 lowest-cost refined by LM; a below-the-floor position is penalised. Error per mark = angle × distance (cm). **Mis-aimed mark** (5+ marks): solve without each mark in turn; the mark whose removal makes the rest fit far better (all-marks rms > 3 × the rest's) and which the rest then miss by > 10 cm is flagged (the plain "error > 3 × median" test doesn't work: the fit spreads one bad aim over all the marks). With 4 marks only an error far above the others is flagged.
- Ambiguity: (φ, θ) and (φ + 180°, −θ) aim the same way. The solve uses the measured values as-is (continuous), so it's unambiguous; the aim step (below) chooses between them.

**Aim (per frame, Space = Stage).** Target T: d_h = R_hᵀ (T − P_h) normalised; θ = acos(d_h.z), φ = atan2(d_h.y, d_h.x). Candidates (φ + 360k, θ) and (φ + 180° + 360k, −θ) that fall inside 0–1 of the range and the head limits; pick the one closest to the head's current pan / tilt (no long swings, no flips mid-effect). None reachable → hold at the nearest reachable point + a warning (once per look).

**Plane mapping (stage shapes).** A shape is drawn in (u, v) metres on a plane (floor z = 0 / back wall y = depth / a height z = h), centred on a stage point; each frame (u, v) → T → aim. Constant floor speed: the shape's parameter advances by arc length / speed instead of time.

**Room zones.** Axis-aligned boxes (x, y, z ranges). The beam segment from P_h to its floor hit (or to the target) is tested against each box; if it crosses, the target is moved along the plane to the nearest point whose beam clears the box, with the v7 C1 follower (entry side kept, max speed) working in plane coordinates.

## Show file format change (8 → 9)
Bump `FORMAT` to 9 in v9 Part A2 (`dmx_suite/versions.py`), after v8's frozen 8. Additive only — the 8 → 9 step is a no-op (no calibration = today). The bump is so an older app refuses a calibrated rig instead of ignoring it.

Rig (`rigs/*.yaml`):
```yaml
calibration:
  stage: {width: 6.0, depth: 4.0}          # m
  marks:
    M1: [-1.0, 1.0, 0]                     # x, y, z m
    M2: [1.0, 1.0, 0]
    M3: [1.0, 3.0, 0]
    M4: [-1.0, 3.0, 0]
  aims:                                    # raw wizard data, kept so a solve can be redone
    mh_a: {M1: [0.412, 0.633], M2: [0.47, 0.61], M3: [0.49, 0.55], M4: [0.43, 0.56]}
  heads:
    mh_a: {pos: [-2.1, 0.4, 1.8], rot: [0.02, -3.11, 0.05], tilt_zero: 0.5, pan_range: 540, tilt_range: 270,
           mount: upright, error_cm: 4.2, marks_used: 4, date: 2026-12-05}
  safe_park: false
room_zones:
  - {name: Audience eyes, x: [-4, 4], y: [-6, 0], z: [1.0, 2.0], black: false}
mount: {mh_b: hung}                        # manual fallback for uncalibrated heads
points:
  kit: {at: [0, 2.6, 0.8], description: Drum kit}      # stage point in metres (new); per-head points unchanged
```
Look / FX overrides (v8 item 14): Move FX params gain `space: head|stage`, `plane: floor|wall|height`, `height`, `size_m`, `centre_point`, `floor_speed`.

## Part A: Solver and model (`v9-a-solver`)
Built first and fully tested without any UI (synthetic data).
1. **Geometry module.** New `dmx_suite/stagegeo.py`: head model (d_h, R, P), aim (with candidate choice and limits), solve (LM), quick re-cal, residuals, plane mapping, room-zone segment test. Pure Python, typed.
   - Tests `test_stagegeo.py` (done, A1): **synthetic round trip** — random head poses (upright / hung / side-L / side-R, 1.5–4 m up, ±3 m), aims at the marks: noise-free → position within 3 cm, yoke axis within 0.5°, mount right; 0.2° noise + 16-bit → beams land within 10 cm of every mark and the kit; 3 marks warn; skipped marks left out; a 3.6° mis-aimed mark flagged (and good aims flag nothing); wide marks recover a 10 % wrong range (≤ 3 %) and tilt zero (≤ 0.01), the 2 m square keeps the type's figures; bad mark sets refused; slow path never flips the head; aims stay inside the limits; unreachable target holds at the nearest reachable point; quick re-cal from 2 marks recovers a shifted / turned rig; planes, constant-speed path, room boxes, beam / floor hits, where beams meet.
2. **Rig model.** `rig.py`: parse / validate `calibration`, `room_zones`, `mount`, `Point.at`; `versions.py` FORMAT 9 with a no-op 8 → 9 step (on `v8-a-foundation`); mount derived from R (upright / hung / side-L / side-R by the yoke axis vs world z).
   - Tests: parse / round trip; bad marks (collinear, < 3) refused with a clear message; format 9 refused by an older reader test.

## Part B: Wizard (`v9-b-wizard`)
1. **Wizard state + API.** New `dmx_suite/calibration.py` session, thin hooks in `app.py`: start, set stage / marks, aim (stores the head's current 16-bit pan / tilt), skip, solve, check (all heads to a mark), save (backup of the previous calibration), quick re-cal; resumable (state in the rig's working copy). Not under gig lock; show stopped.
   - While aiming: the selected head → white, narrow (zoom / focus / gobo where the type has them), others off; MASTER handled as rule 1 (colour only).
   - Files: `app.py`, `web/server.py`, `mcp_server.py` / `claude_tools.py` (`calibration_*` tools), `en.json`
   - Tests: API flow end to end with a simulated engine; resume after reload; save makes a backup and restore brings the old one back; gig lock refuses; aim stores fine-channel precision.
2. **Wizard UI.** Heads page → "Calibrate heads" (6 steps as the brief). Step 4 shows top / side view per head, mount, error per head / mark, Re-aim buttons. Uses the v8 big pad (fine mode + arrow-key nudge). Heads page gets one "Calibrate heads" button.
   - Files: new `dmx_suite/web/static/js/views/calibrate.js`, `views/heads.js` (button), `style.css`
   - Tests: `test_ui.py` (Playwright) runs the wizard against the synthetic rig: enter marks, "aim" by API, solve, see error, save.

## Part C: Stage points and aiming (`v9-c-stage-points`)
1. **Stage points.** `Point.at`; `Palettes.position` / `positions_for` resolve a stage point per head via `stagegeo.aim` (calibrated heads only; uncalibrated heads skip it with a warning, as missing points today). Convert per-head → stage (beam intersection average, spread shown). Save-from-beam on the Heads page.
   - Files: `rig.py`, `palettes.py` (`position`, `positions_for`, `with_points`), `views/heads.js` (stage-point crosshair layer), `views/layout.js` (markers, drag → live)
   - Tests: stage point hits within 2 cm on the synthetic rig; per-head points unchanged (goldens); convert; new head gets the point once calibrated.
2. **`aim` tool.** MCP / API `aim {fixture | group, x, y, z}` (Override-level hold, released like the Heads page).
3. **Mount.** Derived mount + manual Mount dropdown; mount-aware drag on the v8 pads (drag up = beam up in the room).

## Part D: Stage-space Move FX (`v9-d-stage-fx`)
1. **Space setting** in the v8 FX settings panel (Head / Stage; Stage default on calibrated rigs for the listed effects). Stage branch in `Run.aim` (`effects/base.py`); new params added to each Move FX's `Param` list. `effects/ride.py` Move, `classic.py` RandomMove and the v8 `effects/move.py` effects get a stage path: pattern → (u, v) on the plane → T → aim. Phase / spread along the shape (v8 phase setting).
2. **Room directions.** Sweeps, Pendulum, Tilt nod, Sky scan, Crossfire, Mirror, Fan, Fly-out, Converge in stage terms (mirror about x = centreline, v8 item 12).
3. **Constant floor speed** option.
4. **Follow** effect: target from a stage-view drag, a CC pair, or a path between stage points over N beats.
   - Tests: two heads (one hung, one upright) draw the same floor circle within 5 cm; Sky scan z of target > ceiling plane for both; converge distance < 2 cm; floor speed constant ±5 %; Space = Head bit-identical to v8; rulecheck both profiles.

## Part E: Room zones and safe park (`v9-e-room-zones`)
1. **Room zones** in `rules._position` after head limits and pad zones (rule 8): segment test, follower in plane coordinates (v7 C1 behaviour: entry side, max speed), `black` option.
2. **Safe park** (opt-in): blackout / park → beam to the floor 0.5 m in front of the head's own position, never through a room zone.
3. **UI**: room zones drawn on the Layout stage view (top view + height band fields).
   - Tests: **every Move FX in Stage and Head space for 60 s on the synthetic rig: no beam segment ever crosses the audience box**; sweep through a box slides round (no snap, ≤ max speed); black zone = colour 0; safe park never crosses a zone; rulecheck both profiles.

## Part F: Views and docs (`v9-f-views`)
1. Layout stage view: heads at solved positions, beams to targets, stage points, room zones. Heads page: mini top / side view per head.
2. Docs: new `docs/manual/calibration.md` (with the mark diagram), `heads.md`, `layout.md`, `auto-show.md` (Space setting), CHANGELOG, SCOPE rows, CLAUDE.md rule 8, `get_guide` CALIBRATION section, ⓘ texts.

## Delivery
- `v9`: brief, this plan (docs only). Both are also carried on `v9-a-solver` so they travel with the code.
- Stacked branches, one per part, per the timeline above. One PR per part: Part A targets `v8-b-heads-move` (or `v8-a-foundation` if B isn't pushed yet); each later PR targets the part before it.
- Before each PR: `ruff check dmx_suite tests installer`, `mypy dmx_suite`, full `pytest` (incl. Playwright), `tests/rulecheck.py` both profiles, CI on ubuntu + windows.
- Each part: small commits with tests, CHANGELOG, `docs/manual/`, MCP tools, `en.json`.

Limits in this environment: no DMX, MIDI or real heads. The solver is proven on synthetic data; the real accuracy (MHL36 ranges, backlash, how well a person can aim at a mark) needs the on-rig acceptance checks in the brief.
