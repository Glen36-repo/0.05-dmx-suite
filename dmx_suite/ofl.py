"""Open Fixture Library (open-fixture-library.org): import a fixture type from its JSON, and export
one of ours as OFL JSON to share or contribute.

Import is best effort: each channel's capability maps to one of our roles with safe defaults
(shutter open, function channels at 'no function'); 16-bit channels, colour and gobo wheel slots
(named, with their colours) and pixel matrices are carried over. Always check the result against
the fixture manual before using it; it's written with `verified: false`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .fixtures import ConfigError, Kind, _type

COLOURS = {"Red": "red", "Green": "green", "Blue": "blue", "White": "white", "Amber": "amber", "UV": "uv"}


def _caps(ch: dict) -> list[dict]:
    return [ch["capability"]] if "capability" in ch else list(ch.get("capabilities") or [])


def _start(cap: dict) -> int:
    return int((cap.get("dmxRange") or [0, 0])[0])


FINE_OF = {"Pan": "pan", "Tilt": "tilt", "Intensity": "dimmer", "Zoom": "zoom", "Focus": "focus"}


def _role(name: str, ch: dict, fine_of: dict[str, str]) -> tuple[str, int, bool]:
    """(role, default, invert) for one OFL channel."""
    if name in fine_of:
        return fine_of[name] + "_fine", 0, False
    caps = _caps(ch)
    types = {c.get("type") for c in caps}
    default = ch.get("defaultValue")
    default = int(default) if isinstance(default, (int, float)) else None

    single = caps[0] if len(caps) == 1 else {}
    t = single.get("type")
    if t == "Pan":
        return "pan", 0, False
    if t == "Tilt":
        return "tilt", 0, False
    if t == "Intensity":
        return "dimmer", 0, False
    if t == "ColorIntensity" and single.get("color") in COLOURS:
        return COLOURS[single["color"]], 0, False
    if t == "PanTiltSpeed":
        invert = single.get("speedStart") == "fast" or single.get("speedEnd") == "slow"
        return "pt_speed", 0, invert
    if t == "Zoom":
        return "zoom", 0, False
    if t == "Focus":
        return "focus", 0, False
    if t == "Frost":
        return "frost", 0, str(single.get("frostIntensityStart", "")).startswith("100")
    if types & {"Prism", "PrismRotation"}:
        nofn = [c for c in caps if c.get("type") == "NoFunction"]
        return "prism", _start(nofn[0]) if nofn else 0, False
    if types & {"Fog", "FogOutput", "FogType"}:
        return "haze", 0, False
    if "ShutterStrobe" in types or "StrobeSpeed" in types:
        open_ = [c for c in caps if c.get("type") == "ShutterStrobe" and c.get("shutterEffect") == "Open"]
        nofn = [c for c in caps if c.get("type") == "NoFunction"]
        d = _start(open_[0]) if open_ else default if default is not None else _start(nofn[0]) if nofn else 0
        return "strobe", d, False
    if "WheelSlot" in types or "WheelRotation" in types or "WheelSlotRotation" in types:
        wheel = next((c.get("wheel") for c in caps if c.get("wheel")), name)
        role = "gobo" if re.search(r"gobo", f"{wheel} {name}", re.I) else "colour_wheel"
        return role, 0, False
    # anything else (macros, programs, reset, dimmer curves): park it on "no function"
    nofn = [c for c in caps if c.get("type") == "NoFunction"]
    d = _start(nofn[0]) if nofn else default if default is not None else 0
    return "fixed", d, False


def guess_kind(data: dict, roles: list[str]) -> Kind:
    cats = set(data.get("categories") or [])
    if "haze" in roles:
        return Kind.HAZE
    if "pan" in roles or "Moving Head" in cats:
        return Kind.HEAD
    if "Pixel Bar" in cats or "Linear" in cats:
        return Kind.BAR
    return Kind.WASH


def ofl_to_type(
    data: dict, mode: str | None = None, key: str | None = None, kind: str | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Return ({key: fixtures.yaml type entry}, warnings) for one OFL mode."""
    chans = data.get("availableChannels") or {}
    modes = data.get("modes") or []
    if not modes:
        raise ConfigError("OFL file has no modes")
    if mode is None:
        if len(modes) > 1:
            raise ConfigError("pick a mode: " + ", ".join(m["name"] for m in modes))
        m = modes[0]
    else:
        m = next((x for x in modes if x["name"] == mode or x.get("shortName") == mode), None)
        if m is None:
            raise ConfigError(f"no mode {mode!r}; have: " + ", ".join(x["name"] for x in modes))
    templates = data.get("templateChannels") or {}
    pixel_keys = _pixel_keys(data)
    fine_of = {}
    for ch in [*chans.values(), *templates.values()]:
        role = _caps(ch)[0].get("type") if len(_caps(ch)) == 1 else None
        for alias in ch.get("fineChannelAliases") or []:
            if role in FINE_OF:
                fine_of[alias] = FINE_OF[role]
    switch_aliases = set()
    for ch in chans.values():
        for c in _caps(ch):
            switch_aliases |= set((c.get("switchChannels") or {}).keys())
    out_channels: list[Any] = []
    roles: list[str] = []
    warnings: list[str] = []
    wheel: dict[str, Any] = {}
    gobos: dict[str, int] = {}
    refs: list[tuple[Any, int | None, dict | None]] = []  # (channel name, pixel, template definition)
    for ref in m["channels"]:
        if isinstance(ref, dict) and ref.get("insert") == "matrixChannels":
            refs += _matrix(ref, pixel_keys, templates)
        else:
            refs.append((ref, None, None))
    for ref, pixel, tdef in refs:
        if tdef is not None:  # one pixel's channel from a matrix template
            role, default, invert = _role(ref, tdef, fine_of)
            entry: dict[str, Any] = {"role": role}
            if role in ("red", "green", "blue", "white", "amber", "uv"):
                entry["pixel"] = pixel
            elif default:
                entry["default"] = default
            out_channels.append(entry if len(entry) > 1 else role)
            roles.append(role)
            continue
        if ref is None:
            out_channels.append({"role": "fixed", "default": 0})
            roles.append("fixed")
            continue
        if not isinstance(ref, str):
            raise ConfigError("this mode uses a channel layout that isn't supported; add the channels by hand")
        if ref in fine_of:  # fine channels are aliases, not listed in availableChannels
            out_channels.append(fine_of[ref] + "_fine")
            roles.append(fine_of[ref] + "_fine")
            continue
        if ref in switch_aliases:  # function changes with another channel: park it at 0
            out_channels.append({"role": "fixed", "default": 0})
            roles.append("fixed")
            warnings.append(f"{ref!r} is a switching channel; set to fixed 0, check the manual")
            continue
        if ref not in chans:
            raise ConfigError(f"mode uses unknown channel {ref!r} (fine/switching channels not supported)")
        role, default, invert = _role(ref, chans[ref], fine_of)
        if role in ("colour_wheel", "gobo"):
            _wheel_slots(data, ref, chans[ref], role, wheel, gobos)
        entry = {"role": role}
        if default:
            entry["default"] = default
        if invert:
            entry["invert"] = True
        out_channels.append(entry if len(entry) > 1 else role)
        roles.append(role)
    k = Kind(kind) if kind else guess_kind(data, roles)
    tkey = key or re.sub(r"[^a-z0-9]+", "_", data.get("name", "fixture").lower()).strip("_")
    t: dict[str, Any] = {"name": data.get("name", tkey), "kind": k.value, "verified": False, "colour_mix": "auto",
                         "channels": out_channels}
    if wheel:
        t["wheel"] = wheel
    if gobos:
        t["gobos"] = gobos
    _type(tkey, t)  # validate against our rules
    return {tkey: t}, warnings


def _pixel_keys(data: dict) -> list[str]:
    """Pixel keys of the fixture's matrix, in order (pixelKeys, or numbered from pixelCount)."""
    mx = data.get("matrix") or {}
    if "pixelKeys" in mx:
        return [k for plane in mx["pixelKeys"] for row in plane for k in row if k]
    if "pixelCount" in mx:
        x, y, z = (list(mx["pixelCount"]) + [1, 1, 1])[:3]
        return [str(i + 1) for i in range(int(x) * int(y) * int(z))]
    return []


def _matrix(ins: dict, keys: list[str], templates: dict) -> list[tuple[str, int | None, dict | None]]:
    """A mode's matrix insert as (channel name, pixel number, template) in channel order."""
    rep = ins.get("repeatFor")
    order = rep if isinstance(rep, list) else keys
    if not order:
        raise ConfigError("matrix channels without pixels; add the pixel channels by hand")
    names = list(ins.get("templateChannels") or [])
    missing = [n for n in names if n not in templates]
    if missing:
        raise ConfigError(f"unknown matrix template {missing[0]!r}")
    pixel = {k: i for i, k in enumerate(order)}
    out: list[tuple[str, int | None, dict | None]] = []
    if ins.get("channelOrder") == "perChannel":
        for n in names:
            out += [(n.replace("$pixelKey", k), pixel[k], templates[n]) for k in order]
    else:
        for k in order:
            out += [(n.replace("$pixelKey", k), pixel[k], templates[n]) for n in names]
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "slot"


def _wheel_slots(data: dict, name: str, ch: dict, role: str, wheel: dict, gobos: dict) -> None:
    """Named slots from the fixture's wheel definition, at the start of each slot's DMX range."""
    caps = _caps(ch)
    wname = next((c.get("wheel") for c in caps if c.get("wheel")), name)
    slots = ((data.get("wheels") or {}).get(wname) or {}).get("slots") or []
    for c in caps:
        n = c.get("slotNumber")
        if c.get("type") != "WheelSlot" or not isinstance(n, int) or not 1 <= n <= len(slots):
            continue  # split colours (2.5) and spinning aren't slots
        s = slots[n - 1]
        label = s.get("name") or ("open" if s.get("type") == "Open" else
                                  Path(str(s.get("resource", f"slot {n}"))).name.replace("-", " "))
        key = _slug(label)
        if role == "colour_wheel":
            entry: Any = _start(c)
            if s.get("type") == "Open":
                entry = {"value": _start(c), "colour": "#ffffff"}
            elif s.get("colors"):
                entry = {"value": _start(c), "colour": s["colors"][0]}
            wheel.setdefault(key, entry)
        else:
            gobos.setdefault(key, _start(c))


# --------------------------------------------------------------------------- export

CATEGORIES = {"head": ["Moving Head"], "bar": ["Pixel Bar"], "wash": ["Color Changer"], "kick": ["Color Changer"],
              "haze": ["Smoke"]}
COLOUR_NAMES = {v: k for k, v in COLOURS.items()}


def _slot_json(role: str, name: str, colour: dict[str, float] | None) -> dict[str, Any]:
    if name == "open":
        return {"type": "Open"}
    title = name.replace("_", " ").title()
    if role != "colour_wheel":
        return {"type": "Gobo", "name": title}
    out: dict[str, Any] = {"type": "Color", "name": title}
    if colour:
        out["colors"] = ["#" + "".join(f"{round(colour.get(k, 0) * 255):02x}" for k in ("red", "green", "blue"))]
    return out


def type_to_ofl(key: str, t: dict, date: str) -> dict[str, Any]:
    """One of our fixture types (fixtures.yaml entry) as an OFL fixture JSON, to check and share.
    Pixel bars become numbered colour channels (not a matrix); check the ranges before
    contributing it to the Open Fixture Library."""
    ft = _type(key, t)  # validated, and channels in a known shape
    chans: dict[str, Any] = {}
    names: list[str] = []
    wheels: dict[str, Any] = {}
    counts: dict[str, int] = {}
    fine_names = {r: f"{r.title()} fine" for r in ("dimmer", "pan", "tilt", "zoom", "focus")}

    def unique(n: str) -> str:
        counts[n] = counts.get(n, 0) + 1
        return n if counts[n] == 1 else f"{n} {counts[n]}"

    for c in ft.channels:
        if c.role.endswith("_fine"):
            base = c.role[:-5]
            coarse = next((n for n in names if chans.get(n, {}).get("_role") == base), None)
            alias = fine_names.get(base, f"{base} fine")
            if coarse:
                chans[coarse].setdefault("fineChannelAliases", []).append(alias)
            names.append(alias)
            continue
        cap: dict[str, Any]
        label = c.role.replace("_", " ").title()
        if c.role in COLOUR_NAMES:
            label = COLOUR_NAMES[c.role] + (f" {c.pixel + 1}" if c.pixel is not None else "")
            cap = {"type": "ColorIntensity", "color": COLOUR_NAMES[c.role]}
        elif c.role == "dimmer":
            cap = {"type": "Intensity"}
        elif c.role in ("pan", "tilt"):
            rng = ft.pan_range if c.role == "pan" else ft.tilt_range
            a, b = ("0deg", f"{rng:g}deg") if not c.invert else (f"{rng:g}deg", "0deg")
            cap = {"type": c.role.title(), "angleStart": a, "angleEnd": b}
        elif c.role == "pt_speed":
            cap = {"type": "PanTiltSpeed", "speedStart": "fast" if c.invert else "slow",
                   "speedEnd": "slow" if c.invert else "fast"}
        elif c.role == "zoom":
            cap = {"type": "Zoom", "angleStart": "narrow", "angleEnd": "wide"}
        elif c.role == "focus":
            cap = {"type": "Focus", "distanceStart": "near", "distanceEnd": "far"}
        elif c.role == "frost":
            cap = {"type": "Frost", "frostIntensityStart": "100%" if c.invert else "0%",
                   "frostIntensityEnd": "0%" if c.invert else "100%"}
        elif c.role == "prism":
            cap = {"type": "Prism"}
        elif c.role == "strobe":
            cap = {"type": "ShutterStrobe", "shutterEffect": "Strobe"}
        elif c.role == "haze":
            cap = {"type": "Fog", "fogType": "Haze"}
        elif c.role in ("colour_wheel", "gobo"):
            label = "Color Wheel" if c.role == "colour_wheel" else "Gobo Wheel"
            slots: list[tuple[str, int, dict[str, float] | None]] = (
                [(n, s.value, s.colour) for n, s in ft.wheel.items()] if c.role == "colour_wheel"
                else [(n, v, None) for n, v in ft.gobos.items()])
            slots.sort(key=lambda x: x[1])
            if slots:
                wheels[label] = {"slots": [_slot_json(c.role, n, col) for n, _, col in slots]}
                caps: list[dict[str, Any]] = []
                for i, (_, v, _) in enumerate(slots):
                    end = (slots[i + 1][1] - 1) if i + 1 < len(slots) else 255
                    caps.append({"dmxRange": [v, max(v, end)], "type": "WheelSlot", "slotNumber": i + 1})
                if caps[0]["dmxRange"][0] > 0:
                    caps.insert(0, {"dmxRange": [0, caps[0]["dmxRange"][0] - 1], "type": "NoFunction"})
                name = unique(label)
                chans[name] = {"_role": c.role, "capabilities": caps}
                names.append(name)
                continue
            cap = {"type": "WheelSlot", "slotNumber": 1}
        else:  # fixed
            label = "Function"
            cap = {"type": "NoFunction"}
        name = unique(label)
        entry: dict[str, Any] = {"_role": c.role, "capability": cap}
        if c.default:
            entry["defaultValue"] = c.default
        chans[name] = entry
        names.append(name)
    for v in chans.values():
        v.pop("_role", None)
    out: dict[str, Any] = {
        "$schema": "https://raw.githubusercontent.com/OpenLightingProject/open-fixture-library/master/schemas/fixture.json",
        "name": ft.name,
        "categories": CATEGORIES.get(ft.kind.value, ["Other"]),
        "meta": {"authors": ["0.05 DMX Suite export"], "createDate": date, "lastModifyDate": date},
        "comment": "Exported from 0.05 DMX Suite: check every channel against the manual before sharing.",
        "availableChannels": chans,
        "modes": [{"name": f"{len(ft.channels)}-channel", "channels": names}],
    }
    if wheels:
        out["wheels"] = wheels
    return out


def import_ofl(path: str | Path, mode: str | None = None, key: str | None = None, kind: str | None = None) -> str:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entry, warnings = ofl_to_type(data, mode, key, kind)
    header = f"# imported from Open Fixture Library ({Path(path).name}); check against the manual, then set verified: true\n"
    for w in warnings:
        header += f"# warning: {w}\n"
    return header + yaml.safe_dump(entry, sort_keys=False, allow_unicode=True, default_flow_style=None)
