"""Drum kits (v6 Part C): the drummer's kit defined once, so tempo (Part B), drum flash and drummer
triggers all read one map.

In `inputs.yaml`:

    kits:
      band_kit:
        name: Band kit
        channel: 10            # the kit's MIDI channel (default 10); port: part of the port name
        pieces:
          snare:
            name: Snare
            zones:
              head:   {input: snare, notes: [38], role: snare, flash: {fixtures: [bars], length_ms: 120}}
              rim:    {input: snare_rim, notes: [40], role: snare}
              x_stick: {input: side_stick, notes: [37], role: count_in}
          tap_pad: {name: Tap pad, zones: {head: {notes: [], role: tap}}}
    active_kit: band_kit

Each zone is one named input (its id is `input:`, default `<piece>` or `<piece>_<zone>`), so existing
MIDI map entries, step scenes and the auto show keep working. Per zone: notes, role (kick, snare, hat,
tom, cymbal, tap, count_in, trigger_only), tempo weight, velocity floor, include in tempo, drum flash
target (fixtures, colour, length_ms: the kit owns these), and an optional drummer trigger (scene,
preset or flash_fx) separate from the FCB1010.

Only the active kit makes inputs. A show without `kits:` gets `band_kit` as a view over its drum-role
inputs and their flash mappings; the first kit save writes it for real (`migrate`): the drum inputs
move out of their device into the kit and their flash mappings out of the MIDI map, in one backed-up
change.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from .fixtures import ConfigError

KIT_ROLES = ("kick", "snare", "hat", "tom", "cymbal", "tap", "count_in", "trigger_only")
DRUM_ROLES = ("kick", "snare", "hat", "tom", "cymbal")  # tempo onsets, and autopilot activity
DEFAULT_WEIGHTS = {"kick": 1.0, "snare": 1.0, "hat": 0.5, "tom": 0.6, "cymbal": 0.4}
ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
ZONE_KEYS = {"input", "name", "notes", "role", "weight", "velocity_floor", "tempo", "flash", "trigger", "colour",
             "curve", "velocity"}
FLASH_KEYS = {"fixtures", "colour", "length_ms", "min_level"}
TRIGGERS = ("scene", "preset", "flash_fx")
ZONE_SUFFIXES = ("rim", "head", "pedal", "open", "closed", "bell", "edge", "bow", "x_stick", "xstick", "stick")


@dataclass
class Zone:
    id: str
    input: str
    notes: list[int]
    role: str
    name: str = ""
    weight: float | None = None  # None = the role's default
    velocity_floor: int | None = None  # None = the tracker's
    tempo: bool = True
    flash: dict[str, Any] | None = None
    trigger: dict[str, str] | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # colour, curve, velocity: passed to the input

    def roles(self) -> list[str]:
        """The named-input roles this zone gives (activity for drums, so autopilot energy keeps working)."""
        if self.role in DRUM_ROLES:
            return [self.role, "activity"]
        if self.role == "count_in":
            return ["count_in", "activity"]
        if self.role == "tap":
            return ["tap"]
        return []

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"input": self.input, "notes": list(self.notes), "role": self.role}
        if self.name:
            d["name"] = self.name
        if self.weight is not None:
            d["weight"] = self.weight
        if self.velocity_floor is not None:
            d["velocity_floor"] = self.velocity_floor
        if not self.tempo:
            d["tempo"] = False
        if self.flash:
            d["flash"] = dict(self.flash)
        if self.trigger:
            d["trigger"] = dict(self.trigger)
        d.update(copy.deepcopy(self.extra))
        return d


@dataclass
class Piece:
    id: str
    name: str
    zones: dict[str, Zone]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "zones": {k: z.to_dict() for k, z in self.zones.items()}}


@dataclass
class Kit:
    id: str
    name: str
    channel: int = 10
    port: str | None = None
    pieces: dict[str, Piece] = field(default_factory=dict)
    derived: bool = False  # a view over the show's drum inputs, not written yet
    device: str | None = None  # derived: the device its inputs are in now

    def zones(self) -> list[tuple[Piece, Zone]]:
        return [(p, z) for p in self.pieces.values() for z in p.zones.values()]

    def zone_for_input(self, input_id: str) -> tuple[Piece, Zone] | None:
        return next(((p, z) for p, z in self.zones() if z.input == input_id), None)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "channel": self.channel}
        if self.port:
            d["port"] = self.port
        d["pieces"] = {k: p.to_dict() for k, p in self.pieces.items()}
        return d


# ---------------------------------------------------------------------- parsing


def _num(v: Any, what: str, lo: float, hi: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ConfigError(f"{what}: {lo:g}-{hi:g}")
    return float(v)


def parse_zone(pid: str, zid: str, d: Any, where: str) -> Zone:
    if not isinstance(d, dict):
        raise ConfigError(f"{where}: a zone has notes and a role")
    bad = set(d) - ZONE_KEYS
    if bad:
        raise ConfigError(f"{where}: unknown settings {sorted(bad)}; known: {', '.join(sorted(ZONE_KEYS))}")
    role = str(d.get("role", "trigger_only")).replace("-", "_")
    if role not in KIT_ROLES:
        raise ConfigError(f"{where}: role is one of {', '.join(KIT_ROLES)}")
    notes = d.get("notes") or []
    if isinstance(notes, int):
        notes = [notes]
    if not isinstance(notes, list) or any(isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 127 for n in notes):
        raise ConfigError(f"{where}: notes are MIDI note numbers 0-127")
    iid = str(d.get("input") or (pid if zid in ("head", "main") else f"{pid}_{zid}"))
    if not ID.match(iid):
        raise ConfigError(f"{where}: input ids use lower case letters, digits, _ or -")
    z = Zone(zid, iid, list(dict.fromkeys(notes)), role, str(d.get("name") or ""))
    if d.get("weight") is not None:
        z.weight = _num(d["weight"], f"{where} weight", 0, 2)
    if d.get("velocity_floor") is not None:
        z.velocity_floor = int(_num(d["velocity_floor"], f"{where} velocity_floor", 0, 127))
    z.tempo = bool(d.get("tempo", role in DRUM_ROLES))
    if d.get("flash"):
        f = d["flash"]
        if not isinstance(f, dict) or not f.get("fixtures") or set(f) - FLASH_KEYS:
            raise ConfigError(f"{where} flash: {{fixtures: [...], colour, length_ms, min_level}}")
        z.flash = dict(f)
    if d.get("trigger"):
        t = d["trigger"]
        if not isinstance(t, dict) or len(t) != 1 or next(iter(t)) not in TRIGGERS:
            raise ConfigError(f"{where} trigger: one of {{scene: name}}, {{preset: id}}, {{flash_fx: id}}")
        z.trigger = {k: str(v) for k, v in t.items()}
    z.extra = {k: copy.deepcopy(d[k]) for k in ("colour", "curve", "velocity") if k in d}
    return z


def parse_kit(kid: str, d: Any) -> Kit:
    where = f"kit {kid}"
    if not ID.match(str(kid)):
        raise ConfigError(f"{where}: ids use lower case letters, digits, _ or -")
    if not isinstance(d, dict):
        raise ConfigError(f"{where}: needs pieces")
    bad = set(d) - {"name", "channel", "port", "pieces"}
    if bad:
        raise ConfigError(f"{where}: unknown settings {sorted(bad)}")
    ch = d.get("channel", 10)
    if ch in ("any", 0, None):
        ch = 0
    elif isinstance(ch, bool) or not isinstance(ch, int) or not 1 <= ch <= 16:
        raise ConfigError(f"{where}: channel 1-16 or any")
    kit = Kit(str(kid), str(d.get("name") or kid), int(ch), d.get("port") or None)
    seen: dict[str, str] = {}
    for pid, pd in (d.get("pieces") or {}).items():
        pw = f"{where} piece {pid}"
        if not ID.match(str(pid)) or not isinstance(pd, dict):
            raise ConfigError(f"{pw}: an id (lower case) with name and zones")
        zones = {}
        for zid, zd in (pd.get("zones") or {}).items():
            if not ID.match(str(zid)):
                raise ConfigError(f"{pw}: zone ids use lower case letters, digits, _ or -")
            z = parse_zone(str(pid), str(zid), zd, f"{pw} zone {zid}")
            if z.input in seen:
                raise ConfigError(f"{pw} zone {zid}: input {z.input} is already {seen[z.input]}")
            seen[z.input] = f"{pid}/{zid}"
            zones[str(zid)] = z
        kit.pieces[str(pid)] = Piece(str(pid), str(pd.get("name") or pid), zones)
    return kit


def parse_kits(data: Any) -> dict[str, Kit]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError("kits: {kit_id: {name, channel, pieces}}")
    return {str(k): parse_kit(str(k), v) for k, v in data.items()}


def zone_input(kit: Kit, piece: Piece, z: Zone) -> dict[str, Any]:
    """The named input a zone is (inputs.yaml input format)."""
    d: dict[str, Any] = {"name": z.name or (piece.name if len(piece.zones) == 1 else f"{piece.name} {z.id.replace('_', ' ')}"),
                         "type": "note", "notes": list(z.notes), "roles": z.roles(),
                         "channel": kit.channel or "any"}
    if kit.port:
        d["port"] = kit.port
    d.update(copy.deepcopy(z.extra))
    return d


# ---------------------------------------------------------------------- templates


def gm_kit(kid: str = "gm_kit", channel: int = 10) -> Kit:
    """A General MIDI kit to start from (Roland / Alesis modules send GM notes by default)."""
    p: dict[str, Any] = {
        "kick": ("Kick", {"head": ([36], "kick")}),
        "snare": ("Snare", {"head": ([38], "snare"), "rim": ([40], "snare"), "x_stick": ([37], "count_in")}),
        "hihat": ("Hi-hat", {"closed": ([42], "hat"), "pedal": ([44], "count_in"), "open": ([46], "hat")}),
        "tom_1": ("Tom 1", {"head": ([48], "tom"), "rim": ([], "tom")}),
        "tom_2": ("Tom 2", {"head": ([47], "tom"), "rim": ([], "tom")}),
        "tom_3": ("Tom 3", {"head": ([45], "tom"), "rim": ([], "tom")}),
        "tom_4": ("Tom 4", {"head": ([43], "tom"), "rim": ([], "tom")}),
        "crash_1": ("Crash 1", {"head": ([49], "cymbal")}),
        "crash_2": ("Crash 2", {"head": ([57], "cymbal")}),
        "ride": ("Ride", {"bow": ([51], "cymbal"), "bell": ([53], "cymbal"), "edge": ([59], "cymbal")}),
        "china": ("China", {"head": ([52], "cymbal")}),
        "splash": ("Splash", {"head": ([55], "cymbal")}),
        "tap_pad": ("Tap pad", {"head": ([], "tap")}),
    }
    kit = Kit(kid, "GM kit" if kid == "gm_kit" else kid.replace("_", " ").title(), channel)
    for pid, (name, zones) in p.items():
        zs = {zid: Zone(zid, pid if zid == "head" else f"{pid}_{zid}", notes, role, tempo=role in DRUM_ROLES)
              for zid, (notes, role) in zones.items()}
        kit.pieces[pid] = Piece(pid, name, zs)
    return kit


# ---------------------------------------------------------------------- a show without kits: the view


def _piece_zone(iid: str) -> tuple[str, str]:
    for suf in ZONE_SUFFIXES:
        if iid.endswith("_" + suf) and len(iid) > len(suf) + 1:
            return iid[: -len(suf) - 1], suf
    return iid, "head"


def _role_of(roles: list[str], iid: str) -> str:
    for r in ("kick", "snare", "hat", "tom", "cymbal", "tap", "count_in"):
        if r in roles:
            return r
    if "hat" in iid or "hihat" in iid:
        return "hat"
    return "trigger_only"


def derive_kit(inputs_data: dict[str, Any], flashes: dict[str, dict[str, Any]], kid: str = "band_kit") -> Kit | None:
    """`band_kit` from the drum-role note inputs already in inputs.yaml (the device with most of them),
    with the flash targets the MIDI map gives them. None when there are no drum inputs."""
    drum = {"kick", "snare", "hat", "tom", "cymbal", "count_in", "tap"}
    best: tuple[int, str, dict[str, Any]] | None = None
    for did, dd in (inputs_data.get("devices") or {}).items():
        ins = {k: v for k, v in ((dd or {}).get("inputs") or {}).items()
               if isinstance(v, dict) and v.get("type", "note") == "note" and drum & set(v.get("roles") or [])}
        if ins and (best is None or len(ins) > best[0]):
            best = (len(ins), str(did), dd)
    if best is None:
        return None
    _, did, dd = best
    ch = dd.get("channel", 10) or 0
    kit = Kit(kid, "Band kit", int(ch) if ch != "any" else 0, dd.get("port"), derived=True)
    for iid, v in (dd.get("inputs") or {}).items():
        if not isinstance(v, dict) or v.get("type", "note") != "note":
            continue
        roles = list(v.get("roles") or [])
        if not (drum & set(roles)) and "activity" not in roles:
            continue
        pid, zid = _piece_zone(str(iid))
        notes = v.get("notes") or ([v["number"]] if "number" in v else [])
        z = Zone(zid, str(iid), list(notes), _role_of(roles, str(iid)), str(v.get("name") or ""))
        z.tempo = z.role in DRUM_ROLES
        z.extra = {k: copy.deepcopy(v[k]) for k in ("colour", "curve", "velocity") if k in v}
        if str(iid) in flashes:
            z.flash = dict(flashes[str(iid)])
        piece = kit.pieces.setdefault(pid, Piece(pid, (v.get("name") or pid).split(" rim")[0] if zid == "head"
                                                 else pid.replace("_", " ").title(), {}))
        piece.zones[zid] = z
    kit.device = did  # where the inputs are now (the migration moves them)
    return kit


def migrate(inputs_data: dict[str, Any], map_data: dict[str, Any], kit: Kit,
            also: Kit | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write a kit for real: its inputs leave their device (an emptied device goes), its flash mappings
    leave the MIDI map (the kit owns them now). `also`: the view it replaces (its inputs go too).
    Returns new (inputs, map) data."""
    ins = copy.deepcopy(inputs_data)
    mp = copy.deepcopy(map_data)
    ids = {z.input for _, z in kit.zones()} | ({z.input for _, z in also.zones()} if also else set())
    devices = ins.get("devices") or {}
    for did in list(devices):
        d = devices[did] or {}
        left = {k: v for k, v in (d.get("inputs") or {}).items() if k not in ids}
        if (d.get("inputs") or {}) and not left:
            del devices[did]
        else:
            d["inputs"] = left
    ins["devices"] = devices
    mp["mappings"] = [m for m in (mp.get("mappings") or [])  # the kit owns its pads' flash targets
                      if not (isinstance(m, dict) and m.get("action") == "flash" and m.get("input") in ids)]
    kits = dict(ins.get("kits") or {})
    kits[kit.id] = kit.to_dict()
    ins["kits"] = kits
    ins.setdefault("active_kit", kit.id)
    return ins, mp
