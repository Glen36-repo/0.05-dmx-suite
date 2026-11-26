"""Import a fixture type from an Open Fixture Library JSON file (open-fixture-library.org).

Best effort: maps each channel's capability to one of our roles and picks safe defaults (shutter
open, function channels at 'no function'). Matrix/pixel templates aren't expanded. Always check the
result against the fixture manual before using it; it's written with `verified: false`.
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
    fine_of = {}
    for name, ch in chans.items():
        role = _caps(ch)[0].get("type") if len(_caps(ch)) == 1 else None
        for alias in ch.get("fineChannelAliases") or []:
            if role in ("Pan", "Tilt"):
                fine_of[alias] = role.lower()
    switch_aliases = set()
    for ch in chans.values():
        for c in _caps(ch):
            switch_aliases |= set((c.get("switchChannels") or {}).keys())
    out_channels: list[Any] = []
    roles: list[str] = []
    warnings: list[str] = []
    for ref in m["channels"]:
        if ref is None:
            out_channels.append({"role": "fixed", "default": 0})
            roles.append("fixed")
            continue
        if not isinstance(ref, str):
            raise ConfigError("matrix/pixel channel templates aren't supported; add pixel channels by hand")
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
        entry: dict[str, Any] = {"role": role}
        if default:
            entry["default"] = default
        if invert:
            entry["invert"] = True
        out_channels.append(entry if len(entry) > 1 else role)
        roles.append(role)
    k = Kind(kind) if kind else guess_kind(data, roles)
    tkey = key or re.sub(r"[^a-z0-9]+", "_", data.get("name", "fixture").lower()).strip("_")
    t = {"name": data.get("name", tkey), "kind": k.value, "verified": False, "channels": out_channels}
    _type(tkey, t)  # validate against our rules
    return {tkey: t}, warnings


def import_ofl(path: str | Path, mode: str | None = None, key: str | None = None, kind: str | None = None) -> str:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entry, warnings = ofl_to_type(data, mode, key, kind)
    header = f"# imported from Open Fixture Library ({Path(path).name}); check against the manual, then set verified: true\n"
    for w in warnings:
        header += f"# warning: {w}\n"
    return header + yaml.safe_dump(entry, sort_keys=False, allow_unicode=True, default_flow_style=None)
