"""Moves across show files when a folder is upgraded to file format 5 (v3.1).

Single-file format steps live in versions.py; these need more than one file at once, so
ShowStore.upgrade runs them once, in the same backed-up change as the format upgrade:

- raw MIDI map mappings (`{type: note, channel: 10, number: 38, ...}`) become named inputs in
  inputs.yaml, and the mappings name them (`{input: snare, ...}`). The same message always gets
  the same input, across every MIDI map, so behaviour doesn't change.
- a rig's kick tempo note (`tempo.kick_note`) gets an input with the kick role, if no input has it.
- palette `positions` move into each rig file as head points (`positions:`), for the heads that
  rig has; scenes keep naming them the same way.

Each function takes current-format data (no `version:`) and returns the new data; nothing here
touches the disk.
"""

from __future__ import annotations

import copy
from typing import Any

from .midi.named import suggest

Docs = dict[str, Any]


def _device_for(type_: str, channel: int, port: str | None) -> tuple[str, str, int]:
    """Device id, name and channel for a migrated message."""
    if type_ == "osc":
        return "osc", "OSC", 0
    base = f"ch{channel}"
    name = f"MIDI ch {channel}"
    if type_ == "note" and channel == 10:
        base, name = "drums", "Drums (ch 10)"
    if port:
        slug = "".join(c if c.isalnum() else "_" for c in port.lower()).strip("_")[:20] or "port"
        base, name = f"{base}_{slug}", f"{name} [{port}]"
    return base[:40], name, channel


def mappings_to_inputs(inputs: dict[str, Any], midi_maps: dict[str, dict[str, Any]],
                       kick_notes: list[int] | None = None) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """(inputs.yaml data, MIDI maps) with every raw mapping turned into a named input.

    `inputs` is the current inputs.yaml data (usually empty); its inputs are reused when one is
    already exactly the message. `kick_notes`: rigs' tempo kick notes, given the kick role."""
    inputs = copy.deepcopy(inputs or {})
    devices: dict[str, Any] = inputs.setdefault("devices", {}) or {}
    inputs["devices"] = devices
    taken = {iid for d in devices.values() if isinstance(d, dict) for iid in (d.get("inputs") or {})}
    by_msg: dict[tuple, str] = {}

    def msg_of(d: dict[str, Any], dev: dict[str, Any]) -> list[tuple]:
        t = d.get("type", "note")
        if t == "osc":
            return [("osc", 0, 0, str(d.get("address")), "")]
        ch = d.get("channel", dev.get("channel", 0))
        ch = 0 if ch in (None, "any") else int(ch)
        nums = d.get("notes", d.get("numbers", [d.get("number")]))
        nums = nums if isinstance(nums, list) else [nums]
        port = str(d.get("port", dev.get("port")) or "").lower()
        return [(t, ch, n, "", port) for n in nums]

    for dev in devices.values():
        for iid, d in ((dev or {}).get("inputs") or {}).items():
            if isinstance(d, dict):
                for k in msg_of(d, dev):
                    by_msg.setdefault(k, iid)

    def input_for(t: str, ch: int, num: int, address: str, port: str | None) -> str:
        key = ("osc", 0, 0, address, "") if t == "osc" else (t, ch, num, "", (port or "").lower())
        if key in by_msg:
            return by_msg[key]
        iid, name, roles = suggest(t, ch, num, address, port, taken)
        taken.add(iid)
        did, dname, dch = _device_for(t, ch, port)
        dev = devices.setdefault(did, {"name": dname, **({"channel": dch} if dch else {}),
                                       **({"port": port} if port else {}), "inputs": {}})
        entry: dict[str, Any] = {"name": name, "type": t}
        if t == "osc":
            entry["address"] = address
        elif t == "note":
            entry["notes"] = [num]
        else:
            entry["number"] = num
        if t != "osc" and ch != dev.get("channel", 0):
            entry["channel"] = ch
        if roles:
            entry["roles"] = roles
        dev["inputs"][iid] = entry
        by_msg[key] = iid
        return iid

    out_maps: dict[str, dict[str, Any]] = {}
    for name, data in midi_maps.items():
        data = copy.deepcopy(data)
        new = []
        for m in data.get("mappings") or []:
            if not isinstance(m, dict) or "input" in m or "action" not in m:
                new.append(m)
                continue
            m = dict(m)
            t = m.pop("type", None)
            if t == "osc":
                iid = input_for("osc", 0, 0, str(m.pop("address", "")), None)
            elif t in ("note", "program_change", "control_change"):
                try:
                    ch, num = int(m.pop("channel")), int(m.pop("number"))
                except (KeyError, TypeError, ValueError):
                    new.append({"type": t, **m})  # broken: left for the loader to report
                    continue
                iid = input_for(t, ch, num, "", m.pop("port", None))
            else:
                new.append({"type": t, **m} if t is not None else m)
                continue
            new.append({"input": iid, **m})
        data["mappings"] = new
        out_maps[name] = data

    for note in sorted(set(kick_notes or [])):
        hits = [(did, iid) for did, dev in devices.items() for iid, d in (dev.get("inputs") or {}).items()
                if isinstance(d, dict) and d.get("type", "note") == "note"
                and note in (d.get("notes") or [d.get("number")])]
        if any("kick" in (devices[did]["inputs"][iid].get("roles") or []) for did, iid in hits):
            continue
        if hits:
            did, iid = hits[0]
            entry = devices[did]["inputs"][iid]
            entry["roles"] = list(dict.fromkeys([*(entry.get("roles") or []), "kick", "activity"]))
            continue
        iid = "kick" if "kick" not in taken else suggest("note", 10, note, taken=taken)[0]
        taken.add(iid)
        dev = devices.setdefault("tempo", {"name": "Tempo", "inputs": {}})
        dev["inputs"][iid] = {"name": "Kick", "type": "note", "notes": [note], "channel": "any",
                              "roles": ["kick", "activity"]}
    return inputs, out_maps


def positions_to_points(palettes: dict[str, Any], rigs: dict[str, dict[str, Any]],
                        heads_of: dict[str, list[str]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """(palettes, rigs) with palette `positions` moved into each rig as head points.

    `heads_of`: rig name -> the moving heads (not colour-only) in that rig. A same-for-every-head
    position (`{pan, tilt}`) is written out for each of them; per-head entries keep the heads the rig
    has. A point a rig already has is left as it is."""
    positions = (palettes or {}).get("positions") or {}
    if not positions:
        return palettes, rigs
    palettes = {k: v for k, v in palettes.items() if k != "positions"}
    out: dict[str, dict[str, Any]] = {}
    for rname, rig in rigs.items():
        rig = copy.deepcopy(rig)
        heads = heads_of.get(rname, [])
        points = rig.setdefault("positions", {}) or {}
        rig["positions"] = points
        for pname, v in positions.items():
            if pname in points or not isinstance(v, dict):
                continue
            if set(v) == {"pan", "tilt"}:
                entries = {h: {"pan": v["pan"], "tilt": v["tilt"]} for h in heads}
            else:
                entries = {h: dict(pv) for h, pv in v.items() if h in heads and isinstance(pv, dict)}
            if entries:
                points[pname] = {"heads": entries}
        if not points:
            rig.pop("positions")
        out[rname] = rig
    return palettes, out
