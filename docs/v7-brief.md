# 0.05 DMX Suite — v7 brief (28/11/2026)

Repo: Glen36-repo/0.05-dmx-suite. Save as `docs/v7-brief.md`. Builds on v5 + v6 (PR #16, branch `v5-v6`) — branch v7 work from `v5-v6`, or from `main` once #16 is merged.

Build order: Part A (Autopilot) → B (Layout + Fixtures) → C (Heads) → D (MIDI / drum flash) → E (Files + start-up). Plan before writing code. Each part: tests, CHANGELOG, manual pages, MCP tools where noted. Rules (MASTER owns on/off, haze never automated, kick light MASTER-exempt, no background glow) unchanged unless stated.

Shared component (used by B2, D1, and anything else that picks lights): **tick-box picker** — dropdown listing the rig's fixtures (or groups) with a tick each, grouped by type (Moving heads / Pixel bars / Pars / Kick …) with All / None and a tick per type group; closed state shows a summary ("4 bars, kick", "All lights").

---

# PART A — Autopilot

## A1. Kick-drum light follows the scene
- Problem: the kick light (logo light) always renders white under Autopilot.
- Change: it takes the running look's colour like every other light (current palette / Colour FX output). Stays MASTER-exempt and keeps its own lit level (v6 Darkness exemption unchanged). Bright most of the time.
- Acceptance: palette Fire → kick light red/orange; colour chase → kick light follows the chase.

## A2. Palette bank (structured like Colour FX)
- Palettes become a bank on the Autopilot page alongside Move / Colour / Flash FX: one tile per palette (7 curated + user palettes), swatches + mood tags.
- Same tile states as FX banks (v4 / PR #15): **green** = playing now, **red** = excluded (never picked by Autopilot, stays on the page).
- Tap a tile = play it now (manual pick). Lock behaviour is covered by A4.
- MIDI / MCP / API actions: play palette, exclude / include palette (same shape as FX bank actions).
- The Ride page palette lock is replaced by the A4 palette layer lock.

## A3. Darkness — Manual and Auto modes
- **Manual** = v6 behaviour, unchanged (slider, FCB1010 expression CC, set values, Claude).
- **Auto**: two markers on the darkness slider bar — **Min** and **Max**. Darkness moves between them on its own.
- **Time at Max (%)**: share of time spent at the Max marker; rest at / heading to Min.
- Defaults (confirm): changes on the A4 darkness clock; eases with the look's fade (as v6); touching the slider or pedal in Auto → back to Manual (shown on screen).
- Saved per rig and per LOW / MID / HIGH set (Min, Max, Time at Max).
- MCP: `set_darkness` takes `mode`, `min`, `max`, `time_at_max`.

## A4. Layer timing — together or staggered
- Four layers: **Move FX, Colour FX, Palette, Darkness**.
- **Together** (default): all four change at once on each look change (current behaviour).
- **Staggered**: each layer runs its own change clock so the show is always transitioning, never a hard cut. Per layer: interval as seconds, number of looks, or "song / set change only"; random spread ±% so layers don't re-align.
- **Lock** per layer: holds that layer while others keep changing (replaces palette lock, A2).
- Every single-layer change still runs the quality rules (combo issues, contrast vs what's playing, bans, no-repeat).
- Shown on the Autopilot page: each layer's countdown / lock state.
- MCP: `save_autopilot_settings` takes `timing: together|staggered` and per-layer `{every_s | every_looks | on: song|set, spread, locked}`.

## A5. Smaller FX tiles
- Move / Flash / Colour FX tiles (and new Palette tiles) at **75 %** of current size. Keep the 12 px text floor and touch minimums from the 28/11 phone work.

## A6. Between songs — pick a scene, plus settings on the page
- Today: no `activity` MIDI for `gap_s` (4 s) → the `talking` look (a generated Pick: static white, kit, slow); first hit or count-in → next song. All of it rig-YAML only, nothing on the Autopilot page.
- **Between-songs look**: choose either a generated look (current) **or any pre-built scene** from the scene list (picker on the Autopilot page). Same choice for `walk_on` / `walk_off`.
- A scene played here plays as authored (no Darkness, no layer timing); MASTER / haze rules unchanged.
- **Settings on the Autopilot page** (saved per rig):
  - **No activity time** (`gap_s`, default 4 s) — silence that ends a song.
  - **Song start**: first hit / count-in only (`count_in` hits, default 4).
  - **Fade in / fade out** of the between-songs look (default: LOW fade in, song's mood fade out).
  - **Ignore inputs**: tick-box picker of MIDI inputs / pads that do *not* count as activity (e.g. a pad tapped while talking, FCB pedal).
  - **Min song length** — a gap within the first N s of a song doesn't end it (default 20 s).
  - **On / off** — turn between-songs detection off (e.g. continuous DJ-style sets).
- Status on the page: "Between songs" badge with time since last hit.
- MCP: `save_autopilot_settings` takes `between: {look | scene, gap_s, start, count_in, fade_in, fade_out, ignore, min_song_s, on}`.

---

# PART B — Layout and Fixtures

## B1. Layout: bigger stage grid, names only
- Stage grid shows fixture **names only**.
- Light detail panel shrinks to a narrow strip (name, type, select / find / test). Universe, address, footprint and the address editor move to Fixtures (B2).
- Grid takes the freed width (no drag divider needed).

## B2. Fixtures: universe and address editing
- Reverses v6 "one place for addresses" — the one place is now **Fixtures**.
- Each fixture row: inline **Universe** and **Address** fields, range shown (e.g. 33–48). Clash / overlap checks and live-value check move with it. Remove the "Change → Layout" jump.
- Address map (512-channel used / free view): collapsible panel on Fixtures (confirm — or drop).
- **Groups** field becomes the tick-box picker: ticks for existing groups + "+ New group". A group left with no lights is flagged (scenes / MIDI may use it), not silently deleted.

---

# PART C — Heads

## C1. Exclusion zones
- Draw **rectangles and circles / ellipses** on each head's pan / tilt pad; several per head; move, resize, rename, delete.
- Scope: one head, or copied to all heads of the same type. Saved in the rig file (per venue), alongside the existing head limits.
- Output: a target inside a zone is pushed to the nearest zone edge at output (same layer as head limits, rule 8). Movement FX that sweep through a zone slide around the edge rather than crossing.
- Optional per zone: **black while inside** — head colour off instead of deflecting (e.g. audience eyes, mirrors).
- Saved head points / scenes that land inside a zone are flagged, like out-of-limit points.
- Pad shows zones as red hatched areas and an indicator when a head is held at a zone edge.
- MCP: `save_head_zone` / `delete_head_zone` / `list_head_zones`.

---

# PART D — MIDI / drum flash

## D1. Drum flash = gate on the playing scene
- Target picker: each pad's flash target (Drum Kit page) becomes the tick-box picker (replaces the comma-typed field). Same picker replaces the comma-typed `fixtures` field in MIDI page actions.
- Behaviour: a hit **only opens the ticked lights** so they show what the playing scene has on them *at that moment* — per-fixture live colour, position and effect. No added colour, white or scene. Replaces the current single `show_colour` flash colour (`engine.flash(colour="show")`).
- Mechanism: heads with a shutter / strobe channel (MHL36) → open shutter for the hit; lights without (bars, pars) → pass the scene's rendered colour through for the hit length, black otherwise. Unticked lights unaffected.
- Primary use: MASTER off → drums strobe the live scene. With MASTER on, the hit has no visible effect on already-lit lights (optional "dip" mode later — not in v7).
- Flash FX bank (blinder, colour hit, strobe …) unchanged.

---

# PART E — Files and start-up

## E1. Save and save setting
- Add **Save** beside Open / Save as / New; Ctrl+S.
- Setting **Auto-save** (current — every change written with backups) / **Manual save** (unsaved until Save; "●" in title; prompt on close / open another file). Default Auto-save (confirm).

## E2. Open last used file on launch
- Launch opens the top Recent entry. Missing (e.g. OneDrive not synced) → message + fall back to the default show folder.

## E3. Start-up state
- Every launch: **Autopilot on, mood LOW, MASTER on** — starts once a DMX output is connected. Haze off; Darkness from the LOW set.
- Overrides v4 "resume after restart" for these three. Setting "Start-up: Autopilot LOW (default) / Resume last state" (confirm — or always Autopilot LOW).

---

# Open items (confirm before / during build)
1. A3 — Time at Max: % of time at the **Max marker** (assumed), not at 100 % darkness.
2. A3 — darkness change trigger in Auto: layer clock (assumed) vs per look vs on the beat.
3. B2 — keep the address map as a collapsible panel on Fixtures, or drop it.
4. E1 — "save setting" = Auto / Manual save option (assumed), or just a Save button.
5. E3 — start-up state as a setting (assumed) or fixed.
6. A6 — extra between-songs settings beyond no-activity time (song start, fades, ignore inputs, min song length, on/off) are proposals: trim as wanted.
