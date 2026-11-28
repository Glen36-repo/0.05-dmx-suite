"""Named inputs (v3): define a MIDI or OSC input once ("Kick", "Snare", "Pedal 3"), use the name
everywhere (shows/inputs.yaml).

    version: 5
    devices:
      td25:
        name: TD-25 kit
        port: UM-ONE          # optional: part of the port name, for every input in the device
        channel: 10           # default channel for the device's inputs (0 or "any" = any channel)
        inputs:
          kick:  {name: Kick, type: note, notes: [36], roles: [kick, activity]}
          snare: {name: Snare, type: note, notes: [38, 40], roles: [snare, activity],
                  velocity: [1, 127], curve: {quiet: 30, normal: 80, loud: 120}}
      fcb1010:
        name: FCB1010
        channel: 1
        inputs:
          pedal_1: {type: program_change, number: 0}
          expression: {type: control_change, number: 7}
      touchosc:
        name: TouchOSC
        inputs:
          grand: {type: osc, address: /dmx/grand}

Input ids are unique across devices; MIDI maps, scenes and everything else name the id
(`{input: snare, action: flash, ...}`), so changing a note is done here once. Roles tell the auto
show what an input is (kick, snare, tom, cymbal, count_in, activity), so any instrument can drive
it. Two inputs may claim the same message only when both say `shared: true` (both then fire).

A port-specific input wins over one without a port, as MIDI map mappings always did.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..fixtures import ConfigError

TYPES = ("note", "program_change", "control_change", "osc")
ROLES = ("kick", "snare", "tom", "cymbal", "count_in", "activity", "darkness")
CONTINUOUS_ROLES = ("darkness",)  # v6: a CC (expression pedal) that rides a live control
ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
CURVE_POINTS = (("quiet", 0.25), ("normal", 0.6), ("loud", 1.0))  # calibrated velocity -> strength

Key = tuple[str, int, int, str]  # (type, channel 0 = any, number, port lower-case) / ("osc", 0, 0, address)


@dataclass
class InputDef:
    id: str
    name: str
    device: str
    type: str
    channel: int = 0  # 1-16, 0 = any channel
    numbers: list[int] = field(default_factory=list)  # notes / program / controller numbers
    address: str = ""  # OSC
    port: str | None = None  # part of the port name; None = any port
    velocity: tuple[int, int] = (0, 127)  # notes outside this don't count as this input
    curve: dict[str, int] | None = None  # {quiet, normal, loud}: raw velocities from calibration
    roles: list[str] = field(default_factory=list)
    shared: bool = False
    colour: str | None = None
    range: tuple[float, float] = (0.0, 100.0)  # v6: a continuous role's span in % (pedal heel -> toe)

    def keys(self) -> list[Key]:
        if self.type == "osc":
            return [("osc", 0, 0, self.address)]
        return [(self.type, self.channel, n, (self.port or "").lower()) for n in self.numbers]

    def matches_port(self, port_name: str) -> bool:
        return self.port is None or self.port.lower() in port_name.lower()

    def accepts(self, value: int, pressed: bool) -> bool:
        """Velocity range: only note-ons are filtered (a note-off still releases)."""
        if self.type != "note" or not pressed:
            return True
        lo, hi = self.velocity
        return lo <= value <= hi

    def strength(self, value: int) -> float:
        """How hard it was hit, 0-1. Linear (value / 127) until calibrated; then quiet / normal /
        loud land on 0.25 / 0.6 / 1.0, in straight lines between."""
        v = max(0, min(127, int(value)))
        if not self.curve:
            return v / 127
        pts = [(0, 0.0)] + [(self.curve[k], s) for k, s in CURVE_POINTS if k in self.curve] + [(127, 1.0)]
        pts.sort()
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if v <= x1:
                return y0 if x1 == x0 else y0 + (y1 - y0) * (v - x0) / (x1 - x0)
        return 1.0

    def describe(self) -> str:
        if self.type == "osc":
            return f"OSC {self.address}"
        what = {"note": "note", "program_change": "PC", "control_change": "CC"}[self.type]
        ch = f"ch{self.channel}" if self.channel else "any ch"
        nums = "/".join(str(n) for n in self.numbers) or "?"
        return f"{what} {nums} {ch}" + (f" [{self.port}]" if self.port else "")

    def to_dict(self, device_channel: int | None = None, device_port: str | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.name and self.name != self.id:
            d["name"] = self.name
        d["type"] = self.type
        if self.type == "osc":
            d["address"] = self.address
        else:
            if self.channel != (device_channel or 0):
                d["channel"] = self.channel or "any"
            if self.type == "note":
                d["notes"] = list(self.numbers)
            elif len(self.numbers) == 1:
                d["number"] = self.numbers[0]
            else:
                d["numbers"] = list(self.numbers)
            if self.port and self.port != device_port:
                d["port"] = self.port
            if self.velocity != (0, 127):
                d["velocity"] = list(self.velocity)
        if self.curve:
            d["curve"] = dict(self.curve)
        if self.roles:
            d["roles"] = list(self.roles)
        if self.shared:
            d["shared"] = True
        if self.colour:
            d["colour"] = self.colour
        if self.range != (0.0, 100.0):
            d["range"] = [self.range[0], self.range[1]]
        return d

    def level(self, value: int) -> float:
        """A continuous role's value 0-1: the curve (calibration), then the range (heel -> toe, may be reversed)."""
        lo, hi = self.range
        return (lo + (hi - lo) * self.strength(value)) / 100


@dataclass
class Device:
    id: str
    name: str
    port: str | None = None
    channel: int = 0
    inputs: list[str] = field(default_factory=list)


class Inputs:
    """Every named input, with an index from message to inputs."""

    def __init__(self, devices: dict[str, Device] | None = None, inputs: dict[str, InputDef] | None = None) -> None:
        self.devices: dict[str, Device] = devices or {}
        self.inputs: dict[str, InputDef] = inputs or {}
        self._index: dict[tuple[str, int, str], list[InputDef]] = {}  # (type, number or 0, address) -> inputs
        for i in self.inputs.values():
            self._add_index(i)

    def _add_index(self, i: InputDef) -> None:
        if i.type == "osc":
            self._index.setdefault(("osc", 0, i.address), []).append(i)
        else:
            for n in i.numbers:
                self._index.setdefault((i.type, n, ""), []).append(i)

    def add(self, i: InputDef) -> None:
        """Add an input in memory (MIDI learn); the store writes it when the map is saved."""
        if i.id in self.inputs:
            raise ConfigError(f"there's already an input {i.id!r}")
        self.inputs[i.id] = i
        dev = self.devices.setdefault(i.device, Device(i.device, i.device.title()))
        dev.inputs.append(i.id)
        self._add_index(i)

    def __contains__(self, name: object) -> bool:
        return name in self.inputs

    def __len__(self) -> int:
        return len(self.inputs)

    def get(self, name: str) -> InputDef | None:
        return self.inputs.get(name)

    def candidates(self, type_: str, channel: int, number: int, port_name: str, address: str = "") -> list[InputDef]:
        """Every input this message could be, before the port rule and velocity range."""
        if type_ == "osc":
            return list(self._index.get(("osc", 0, address), []))
        return [i for i in self._index.get((type_, number, ""), [])
                if (i.channel in (0, channel)) and i.matches_port(port_name)]

    def match(self, type_: str, channel: int, number: int, port_name: str = "", value: int = 127,
              pressed: bool = True, address: str = "") -> list[InputDef]:
        """The inputs this message is. Port-specific inputs win over ones without a port."""
        found = [i for i in self.candidates(type_, channel, number, port_name, address) if i.accepts(value, pressed)]
        specific = [i for i in found if i.port]
        return specific or found

    def has_role(self, role: str) -> bool:
        return any(role in i.roles for i in self.inputs.values())

    def by_role(self, role: str) -> list[InputDef]:
        return [i for i in self.inputs.values() if role in i.roles]

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for d in self.devices.values():
            dd: dict[str, Any] = {"name": d.name}
            if d.port:
                dd["port"] = d.port
            if d.channel:
                dd["channel"] = d.channel
            dd["inputs"] = {k: self.inputs[k].to_dict(d.channel, d.port) for k in d.inputs if k in self.inputs}
            out[d.id] = dd
        return {"devices": out}

    def summary(self) -> list[dict[str, Any]]:
        """For the UI and Claude: one row per input."""
        return [{"id": i.id, "name": i.name, "device": i.device, "device_name": self.devices[i.device].name,
                 "type": i.type, "describe": i.describe(), "roles": i.roles, "shared": i.shared,
                 "colour": i.colour, "curve": i.curve, "velocity": list(i.velocity), **i.to_dict()}
                for i in self.inputs.values()]


# ---------------------------------------------------------------------- parsing


def _channel(v: Any, where: str) -> int:
    if v in (None, 0, "any"):
        return 0
    try:
        ch = int(v)
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{where}: channel 1-16 or any") from e
    if not 1 <= ch <= 16:
        raise ConfigError(f"{where}: channel 1-16 or any")
    return ch


def _numbers(d: dict[str, Any], where: str) -> list[int]:
    raw: Any
    if "notes" in d:
        raw = d["notes"]
    elif "numbers" in d:
        raw = d["numbers"]
    elif "number" in d:
        raw = [d["number"]]
    else:
        raise ConfigError(f"{where}: needs notes (or number)")
    if isinstance(raw, int) and not isinstance(raw, bool):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{where}: notes is a list of numbers 0-127")
    out = []
    for n in raw:
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 127:
            raise ConfigError(f"{where}: note/number {n!r} must be 0-127")
        if n not in out:
            out.append(n)
    return out


INPUT_KEYS = {"name", "type", "channel", "notes", "number", "numbers", "address", "port", "velocity", "curve",
              "roles", "shared", "colour", "range"}


def parse_input(iid: str, d: Any, device: Device) -> InputDef:
    where = f"input {iid}"
    if not ID.match(iid):
        raise ConfigError(f"{where}: ids use lower case letters, digits, _ or -, up to 40 characters")
    if not isinstance(d, dict):
        raise ConfigError(f"{where}: needs type and notes/number (or an OSC address)")
    bad = set(d) - INPUT_KEYS
    if bad:
        raise ConfigError(f"{where}: unknown settings {sorted(bad)}")
    t = d.get("type", "note")
    if t not in TYPES:
        raise ConfigError(f"{where}: type must be one of {TYPES}")
    i = InputDef(iid, str(d.get("name") or iid), device.id, t)
    if t == "osc":
        a = str(d.get("address", ""))
        if not a.startswith("/") or " " in a:
            raise ConfigError(f"{where}: an OSC address starts with / and has no spaces, e.g. /dmx/grand")
        i.address = a
    else:
        i.channel = _channel(d.get("channel", device.channel), where)
        i.numbers = _numbers(d, where)
        port = d.get("port", device.port)
        if port is not None and (not isinstance(port, str) or not port.strip()):
            raise ConfigError(f"{where}: port must be part of a MIDI port name, e.g. H2MIDI")
        i.port = port
        if "velocity" in d:
            v = d["velocity"]
            if (not isinstance(v, list) or len(v) != 2 or not all(isinstance(x, int) for x in v)
                    or not 0 <= v[0] <= v[1] <= 127):
                raise ConfigError(f"{where}: velocity is [low, high], 0-127")
            if t != "note":
                raise ConfigError(f"{where}: a velocity range is for notes only")
            i.velocity = (v[0], v[1])
    if "curve" in d and d["curve"] is not None:
        c = d["curve"]
        if not isinstance(c, dict) or not c or set(c) - {"quiet", "normal", "loud"}:
            raise ConfigError(f"{where}: curve has quiet / normal / loud velocities")
        vals = []
        for k, _ in CURVE_POINTS:
            if k in c:
                if isinstance(c[k], bool) or not isinstance(c[k], int) or not 1 <= c[k] <= 127:
                    raise ConfigError(f"{where}: curve {k} is a velocity 1-127")
                vals.append(c[k])
        if vals != sorted(vals) or len(set(vals)) != len(vals):
            raise ConfigError(f"{where}: curve velocities must rise: quiet < normal < loud")
        i.curve = {k: int(c[k]) for k, _ in CURVE_POINTS if k in c}
    roles = d.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    if not isinstance(roles, list) or any(r not in ROLES for r in roles):
        raise ConfigError(f"{where}: roles are {', '.join(ROLES)}")
    i.roles = list(dict.fromkeys(roles))
    cont = [r for r in i.roles if r in CONTINUOUS_ROLES]
    if cont and t not in ("control_change", "osc"):
        raise ConfigError(f"{where}: role {cont[0]} needs a CC (control_change), e.g. an expression pedal")
    if "range" in d:
        r = d["range"]
        if (not isinstance(r, list) or len(r) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in r)
                or not all(0 <= x <= 100 for x in r)):
            raise ConfigError(f"{where}: range is [heel, toe] in %, 0-100 (e.g. [0, 80])")
        i.range = (float(r[0]), float(r[1]))
    i.shared = bool(d.get("shared", False))
    if d.get("colour") is not None:
        c = str(d["colour"])
        if not re.match(r"^#[0-9a-fA-F]{6}$", c):
            raise ConfigError(f"{where}: colour is #rrggbb")
        i.colour = c
    return i


def _overlap(a: InputDef, b: InputDef) -> bool:
    """Could one message be both? Same type/number, channels overlap, ports overlap, velocities overlap."""
    if a.type != b.type:
        return False
    if a.type == "osc":
        return a.address == b.address
    if not set(a.numbers) & set(b.numbers):
        return False
    if a.channel and b.channel and a.channel != b.channel:
        return False
    pa, pb = (a.port or "").lower(), (b.port or "").lower()
    if pa != pb:
        return False  # different ports: a port-specific one wins, never both (port-less vs specific ok)
    if a.type == "note":
        return a.velocity[0] <= b.velocity[1] and b.velocity[0] <= a.velocity[1]
    return True


def check_clashes(inputs: dict[str, InputDef]) -> None:
    vals = list(inputs.values())
    for n, a in enumerate(vals):
        for b in vals[n + 1:]:
            if _overlap(a, b) and not (a.shared and b.shared):
                raise ConfigError(f"inputs {a.id} and {b.id} both claim {a.describe()}: change one, "
                                  f"or mark both shared: true")


def parse_inputs(data: dict[str, Any] | None) -> Inputs:
    data = data or {}
    bad = set(data) - {"devices"}
    if bad:
        raise ConfigError(f"inputs.yaml: unknown sections {sorted(bad)} (devices only)")
    devices: dict[str, Device] = {}
    inputs: dict[str, InputDef] = {}
    for did, dd in (data.get("devices") or {}).items():
        where = f"device {did}"
        if not ID.match(str(did)):
            raise ConfigError(f"{where}: ids use lower case letters, digits, _ or -, up to 40 characters")
        if not isinstance(dd, dict):
            raise ConfigError(f"{where}: needs name and inputs")
        unknown = set(dd) - {"name", "port", "channel", "inputs"}
        if unknown:
            raise ConfigError(f"{where}: unknown settings {sorted(unknown)}")
        port = dd.get("port")
        if port is not None and (not isinstance(port, str) or not port.strip()):
            raise ConfigError(f"{where}: port must be part of a MIDI port name")
        dev = Device(str(did), str(dd.get("name") or did), port, _channel(dd.get("channel"), where))
        for iid, idata in (dd.get("inputs") or {}).items():
            iid = str(iid)
            if iid in inputs:
                raise ConfigError(f"input {iid} is in two devices ({inputs[iid].device} and {did}): ids are unique")
            inputs[iid] = parse_input(iid, idata, dev)
            dev.inputs.append(iid)
        devices[dev.id] = dev
    check_clashes(inputs)
    return Inputs(devices, inputs)


def load_inputs(path: str | Path) -> Inputs:
    from ..versions import read_doc

    p = Path(path)
    if not p.exists():
        return Inputs()
    return parse_inputs(read_doc(p, "inputs"))


# ---------------------------------------------------------------------- references


def refs(data: Any, name: str) -> int:
    """How many times show-file data names input `name` (`input: name`, or in an `inputs:` list)."""
    n = 0
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "input" and v == name:
                n += 1
            elif k == "inputs" and isinstance(v, list):
                n += sum(1 for x in v if x == name)
            else:
                n += refs(v, name)
    elif isinstance(data, list):
        n += sum(refs(x, name) for x in data)
    return n


def rename_refs(data: Any, old: str, new: str) -> Any:
    """The same data with input `old` renamed `new` everywhere."""
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for k, v in data.items():
            if k == "input" and v == old:
                out[k] = new
            elif k == "inputs" and isinstance(v, list):
                out[k] = [new if x == old else x for x in v]
            else:
                out[k] = rename_refs(v, old, new)
        return out
    if isinstance(data, list):
        return [rename_refs(x, old, new) for x in data]
    return data


# ---------------------------------------------------------------------- names for new inputs

GM_DRUMS: dict[int, tuple[str, str, list[str]]] = {
    35: ("kick_2", "Kick 2", ["kick", "activity"]),
    36: ("kick", "Kick", ["kick", "activity"]),
    37: ("side_stick", "Side stick", ["count_in", "activity"]),
    38: ("snare", "Snare", ["snare", "activity"]),
    39: ("clap", "Clap", ["activity"]),
    40: ("snare_rim", "Snare rim", ["snare", "activity"]),
    41: ("floor_tom_2", "Floor tom 2", ["tom", "activity"]),
    42: ("hihat", "Hi-hat", ["activity"]),
    43: ("floor_tom", "Floor tom", ["tom", "activity"]),
    44: ("hihat_pedal", "Hi-hat pedal", ["count_in", "activity"]),
    45: ("tom_3", "Tom 3", ["tom", "activity"]),
    46: ("hihat_open", "Hi-hat open", ["activity"]),
    47: ("tom_2b", "Tom 2 (low mid)", ["tom", "activity"]),
    48: ("tom_1", "Tom 1", ["tom", "activity"]),
    49: ("crash", "Crash", ["cymbal", "activity"]),
    50: ("tom_1b", "Tom 1 (high)", ["tom", "activity"]),
    51: ("ride", "Ride", ["cymbal", "activity"]),
    52: ("china", "China", ["cymbal", "activity"]),
    53: ("ride_bell", "Ride bell", ["cymbal", "activity"]),
    55: ("splash", "Splash", ["cymbal", "activity"]),
    57: ("crash_2", "Crash 2", ["cymbal", "activity"]),
    59: ("ride_2", "Ride 2", ["cymbal", "activity"]),
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:30] or "x"


def suggest(type_: str, channel: int, number: int, address: str = "", port: str | None = None,
            taken: set[str] | None = None) -> tuple[str, str, list[str]]:
    """An id, a display name and roles for a new input (MIDI learn, migration)."""
    taken = taken or set()
    roles: list[str] = []
    if type_ == "osc":
        base, name = "osc_" + _slug(address), f"OSC {address}"
    elif type_ == "note" and channel == 10 and number in GM_DRUMS:
        base, name, roles = GM_DRUMS[number]
        roles = list(roles)
    elif type_ == "note":
        base, name = f"note_{number}_ch{channel}", f"Note {number} ch {channel}"
    elif type_ == "program_change":
        base, name = f"pc_{number}" + (f"_ch{channel}" if channel != 1 else ""), f"PC {number}"
    else:
        base, name = f"cc_{number}" + (f"_ch{channel}" if channel != 1 else ""), f"CC {number}"
    if port:
        base = f"{base}_{_slug(port)}"
        name = f"{name} ({port})"
    base = base[:40]
    iid, n = base, 2
    while iid in taken:
        suffix = f"_{n}"
        iid = base[:40 - len(suffix)] + suffix
        n += 1
    return iid, name, roles


# ---------------------------------------------------------------------- device profiles

PROFILES = Path(__file__).parent / "devices"  # shipped: TD-25, SamplePad 4, FCB1010, GM drums


def device_profiles(root: Path | None = None) -> list[dict[str, Any]]:
    """Device profiles to load: shipped ones, then the show folder's own (devices/*.yaml)."""
    import yaml

    out = []
    for where, folder in (("shipped", PROFILES), ("show", (root / "devices") if root else None)):
        if folder is None or not folder.is_dir():
            continue
        for p in sorted(folder.glob("*.yaml")):
            try:
                d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            out.append({"id": p.stem, "name": d.get("name", p.stem), "from": where,
                        "inputs": len(d.get("inputs") or {})})
    return out


def load_device_profile(root: Path | None, name: str) -> dict[str, Any]:
    """A device profile's data (name, port, channel, inputs), checked; the show's own wins."""
    from ..versions import read_doc

    if not ID.match(name):
        raise ConfigError(f"bad device profile name {name!r}")
    for folder in (((root / "devices") if root else None), PROFILES):
        if folder is not None and (folder / f"{name}.yaml").exists():
            data = read_doc(folder / f"{name}.yaml", "device")
            parse_inputs({"devices": {name: data}})  # checked before it goes anywhere
            return data
    raise ConfigError(f"no device profile {name!r}")
