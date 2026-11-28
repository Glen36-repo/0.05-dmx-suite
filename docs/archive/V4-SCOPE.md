# 0.05 DMX Suite — v4 scope: stage view, Layout / Patch, routing, Monitor, step editor

Brief 27/11/2026 (Glen); planned and built 26/11/2026 as one release. Builds on v3 (`docs/archive/V3-SCOPE.md`).

## Why

After the Daslight import the stage view drew the rig tiny in a big empty canvas, stacked lights on each other (par_1 on mh_a, par_4 on mh_b), ran names together, drew four LCB803 bars as one strip of 32 squares and put the smoke machine's HZ over the washes. Stacked places also break spatial effects. The same review asked for a full Layout / Patch page, explicit universe routing, a Monitor for "software running, rig dark", a step editor that actually programs steps, per-segment selection, haze settings, a denser UI, device auto-detection and two renames.

## Release

One branch (`v4-stage-layout`), one PR, a commit per item with tests, stacked on `ui-tighten` (v3.1-3.5 + Connect to Claude + UI tidy).

| Item | What was built |
| --- | --- |
| 1 Zoom to fit | Stage view fits the rig's lights (+2 cells), re-fits on patch change; wheel zoom, middle / Space pan, Fit (0) |
| 2 Pixel bars | One outlined object per pixel light, name centred under it, a gap between bars end to end |
| 3 Labels | Collision pass: nudge, short name (UK L), leader line; full id + type on hover; dark halo |
| 4 Haze off the stage | Corner indicator (level, mode, boost / rest / testing); haze machines left out of effect spans |
| 5 Overlap warning | `layout.layout_problems` (overlap / touching): show check warning, status tile + alert (`get_alerts`), live list on the Layout page |
| 6 MCP layout | `get_layout`, `set_layout`, `save_layout_position`, `delete_fixture`; places take `z` and `reverse` |
| 7 Layout / Patch page | Full width: universe tabs, Stage / Addresses (32 x 16 map with live values from what the interface sent), fixture list with inline address / universe edits checked for clashes, routing table, status strip, Print (A4) and PNG |
| 8 Routing | `universe:` on every output (missing = 0 + warning), one universe to several outputs, problems both ways; per-driver Wire record; `list_outputs`, `set_output`; status tiles say the universe |
| 9 Ride → Autopilot | One Autopilot page with **Feel** for speed / fade / fan / size / shift; `feel:` / `bank_feel:` keys, `autopilot_fx`, `feel_<x>` actions, `/api/autopilot/*` routes (old ones still answer) |
| 10 Step editor | Three panes (list / stage / programmer) + settings bar; set vs tracked per value; Record / Record over / as new / Update; Live or blind; play / loop range / tap; editor undo / redo; YAML panel; per-step errors and head-limit notes; MCP `add_step`, `update_step`, `move_step`, `delete_step` |
| 11 Pixel selection | Selectors `bar_1:px3`, `bar_1:px1-4`, `bars:px1,8`, `bars:odd/even/first3/last3`, pixel groups; colour only; scene editor click / shift / ctrl / shift-drag / lasso / double-click and helpers |
| 12 SHOW grid | Shows / Scenes / Starter and generated as aligned grids in a fixed, saved order |
| 13 ARRANGE | Grouped icon panel (Align, Distribute, Shape, Rotate + flip, Pixels), disabled-with-reason, shortcuts; Save / Undo / Redo / Revert to saved in the header |
| 14 Haze settings | Per-mode settings panel, live apply, Save / Revert, Test, `pulse_level`, haze presets (+ MIDI `haze_preset`), `set_haze` / `save_haze_settings` |
| 15 Monitor | DMX out (grid / per light / changed / hex, flags), MIDI in (resolved input + action, filters, heat map, rates, Learn), MIDI out (log, test send); `monitor_dmx`, `monitor_midi` |
| 16 Density | Button tokens, Compact (default) / Comfortable per laptop; performance controls stay big |
| 17 Busk → Override | All user-facing names; `override` action; `panels.yaml` and the `busk.py` module kept |
| 18 Devices | Registry by USB descriptor / MIDI name, ids `usb:VID:PID:SERIAL`, aliases, missing / new notices, "use this instead" (works under gig lock), outputs rebuilt live; `list_devices`, `set_device` |

## Decisions (26/11/2026)

| Item | Decision |
| --- | --- |
| Base branch | `ui-tighten`; the PR targets it until v2 / v3 land on `main` |
| Renames in data | New keys written (show file format 6), old ones read; `panels.yaml` filename kept; old MCP names / MIDI actions / API paths kept as aliases for one version |
| New key names | `ride` -> `feel`, `bank_ride` -> `bank_feel`; MIDI `busk` -> `override`, `ride_fx` -> `autopilot_fx`, `ride_palette` -> `autopilot_palette`, `ride_<x>` -> `feel_<x>`. The ride cymbal keeps its name |
| Driver ids | `usb_dmx_open`, `usb_dmx_pro`, `node` (aliases `enttec_open`, `enttec_pro`, `node_serial`). The format 6 step does not write `universe:`: the loader assumes 0 and warns until confirmed |
| Pixel groups | In `fixtures.yaml` `pixel_groups:` next to the fixture groups, not in the rig (brief said rig): scenes must validate against every rig. A bar's `reverse` is per rig (`layout:`) |
| Frames to the UI | A separate SSE stream `/api/events/frames?u=&out=` (10 Hz, only while a page shows it); the state stream stays small |
| What the Monitor shows | The selected output's last-sent frame (after its universe filter and a successful write), never the engine's frame unless "Engine (before outputs)" is chosen; no frames = no values |
| Gig lock and devices | "Use this instead" (a missing interface replaced by a plugged-in one) and the live rebuild it triggers are allowed under gig lock; every other output / device change stays locked; Claude can't make the swap |
| Patch sheet | Print stylesheet (Save as PDF from the browser / WebView) + PNG; no new dependency |
| YAML side panel | Server `/api/yaml/dump` and `/api/yaml/load`; no client YAML library |
| MASTER and segments | `rules._write` already drives every `dimmer`-role channel: all 8 segment dimmers of a 48-channel LCB803 follow MASTER (tested); pixel selections never set dimmer / strobe / position |

## Not done / open

- On the gig laptop: check what the Open DMX reports (product string or chip name) in Setup > Plugged in, confirm U0 -> interface, and use Monitor > DMX out to split software from cable / fixture while the rig is dark.
- `save_input` dropping `device` through Claude Desktop wasn't reproducible: the server receives it (tested through the MCP layer). Likely a stale tool list in Claude Desktop: reconnect (Setup > Connect to Claude > Update) and restart Claude Desktop.
- Drum inputs in the band's `inputs.yaml` still have old note numbers (data, not code).
- Item 11 asks for the step editor to put a step's pixels back on the stage when it's picked: picking a layer does; picking a step goes to the step without changing the selection.

## Verification

- `ruff`, `mypy`, `pytest` (1,214 at the end, browser tests included) at every commit.
- `tests/screenshot_rig.py`: the brief's U0 patch and imported layout; before / after screenshots in the PR.
- New test files: `test_ui_v4.py`, `test_stage_v4.py`, `test_mcp_v4.py`, `test_routing.py`, `test_rebuild.py`, `test_devices.py`, `test_haze_settings.py`, `test_monitor.py`, `test_pixel_select.py`, `test_step_tools.py`, `test_v6_migration.py`.
