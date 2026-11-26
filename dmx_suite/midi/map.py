"""MIDI map: which program change / note / CC does what. Per show, in YAML (shows/midi/*.yaml).

    mappings:
      - {type: program_change, channel: 1, number: 0, action: master_toggle}
      - {type: note, channel: 10, number: 38, action: flash, fixtures: [bars], length_ms: 120, colour: show}
      - {type: control_change, channel: 1, number: 7, action: grand_master}

Channels are 1-16 as printed on the gear (mido uses 0-15).

`port` (optional) ties a mapping to one MIDI input: any port whose name contains it (case doesn't
matter), e.g. "H2MIDI" for the SamplePad through the H2MIDI Pro. A port-specific mapping wins over
one without a port, so the SamplePad and the TD-25 can both send ch 10 notes and do different things.

OSC messages share the same map: `{type: osc, address: /dmx/grand, action: grand_master}` (no
channel or number). Faders (grand_master, sub_master, flash_level) take OSC or a MIDI CC.

v3 (file format 5): mappings name an input from shows/inputs.yaml instead of a raw message:
`{input: snare, action: flash, fixtures: [bars]}`. Change the input's note once and every mapping
follows. Raw mappings still load (and win over nothing: a named input's mapping is tried first).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..fixtures import ConfigError, Kind

TYPES = ("note", "program_change", "control_change", "osc", "input")

# action -> allowed extra params
ACTIONS: dict[str, set[str]] = {
    "master_on": set(),
    "master_off": set(),
    "master_toggle": set(),
    "blackout_on": set(),
    "blackout_off": set(),
    "blackout_toggle": set(),
    "flash": {"fixtures", "length_ms", "colour", "min_level"},
    "grand_master": set(),
    "sub_master": {"kind"},
    "flash_level": set(),
    "haze_off": set(),
    "haze_manual": set(),
    "haze_pulse": set(),
    "haze_boost": set(),
    # shows and setlists
    "select_show": {"show", "set"},
    "select_set": {"set"},
    "select_scene": {"scene"},
    "next_step": set(),
    "next_song": set(),
    "prev_song": set(),
    "tap_tempo": set(),
    "speed": set(),
    "busk": {"panel", "widget"},  # a busk widget: press / release, or a fader's value
    # step scenes (v3.2): the one playing
    "step_next": set(),
    "step_back": set(),
    "step_speed": set(),  # fader: 0.25x - 4x
    "step_fade": set(),  # fader: fades 0x - 2x
    # Flash FX (v3.3): held while pressed, or for length_ms
    "flash_fx": {"fx", "colour", "side", "length_ms"},
}
CONTINUOUS = {"grand_master", "sub_master", "flash_level", "speed", "step_speed", "step_fade"}  # need a CC or OSC


@dataclass
class Mapping:
    type: str
    channel: int  # 1-16
    number: int  # note / program / controller
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    port: str | None = None  # substring of the input port name; None = any port
    address: str = ""  # OSC address (type osc)
    input: str | None = None  # named input (type "input", v3)

    @property
    def key(self) -> tuple[str, int, int, str]:
        if self.type == "input":
            return ("input", 0, 0, self.input or "")
        if self.type == "osc":
            return ("osc", 0, 0, self.address)  # OSC addresses are case-sensitive
        return (self.type, self.channel, self.number, (self.port or "").lower())

    def matches_port(self, port_name: str) -> bool:
        return self.port is None or self.port.lower() in port_name.lower()

    def describe(self) -> str:
        if self.type == "input":
            extra = " ".join(f"{k}={v}" for k, v in self.params.items())
            return f"{self.action} {extra}".strip()
        extra = " ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.action} {extra}".strip() + (f" [port {self.port}]" if self.port else "")

    def to_dict(self) -> dict[str, Any]:
        if self.type == "input":
            return {"input": self.input, "action": self.action, **self.params}
        if self.type == "osc":
            return {"type": "osc", "address": self.address, "action": self.action, **self.params}
        d: dict[str, Any] = {"type": self.type, "channel": self.channel, "number": self.number}
        if self.port:
            d["port"] = self.port
        return {**d, "action": self.action, **self.params}


def where_of(m: Mapping) -> str:
    if m.type == "input":
        return f"input {m.input}"
    return f"osc {m.address}" if m.type == "osc" else f"{m.type} ch{m.channel} #{m.number}"


def validate(m: Mapping, input_type: str | None = None) -> None:
    """input_type: the named input's message type, when known (faders need a CC or OSC)."""
    where = where_of(m)
    if m.type not in TYPES:
        raise ConfigError(f"{where}: type must be one of {TYPES}")
    if m.type == "input":
        if not m.input or not isinstance(m.input, str):
            raise ConfigError("mapping: input needs the name of an input from inputs.yaml")
    elif m.type == "osc":
        if not m.address.startswith("/") or " " in m.address:
            raise ConfigError(f"{where}: an OSC address starts with / and has no spaces, e.g. /dmx/grand")
    elif not 1 <= m.channel <= 16 or not 0 <= m.number <= 127:
        raise ConfigError(f"{where}: channel 1-16, number 0-127")
    if m.action not in ACTIONS:
        raise ConfigError(f"{where}: unknown action {m.action!r}")
    if m.port is not None and (not isinstance(m.port, str) or not m.port.strip()):
        raise ConfigError(f"{where}: port must be part of a MIDI port name, e.g. H2MIDI")
    bad = set(m.params) - ACTIONS[m.action]
    if bad:
        raise ConfigError(f"{where}: {m.action} doesn't take {sorted(bad)}")
    kind = input_type if m.type == "input" else m.type
    if m.action in CONTINUOUS and kind is not None and kind not in ("control_change", "osc"):
        raise ConfigError(f"{where}: {m.action} needs a control_change or OSC")
    if m.action == "flash":
        if not m.params.get("fixtures"):
            raise ConfigError(f"{where}: flash needs fixtures")
        c = m.params.get("colour", "show")
        if c not in ("show", "white"):
            raise ConfigError(f"{where}: flash colour must be show or white")
    for action, key in (("select_show", "show"), ("select_set", "set"), ("select_scene", "scene")):
        if m.action == action and not m.params.get(key):
            raise ConfigError(f"{where}: {action} needs {key}")
    if m.action == "flash_fx":
        from ..flashfx import KINDS

        if m.params.get("fx") not in KINDS:
            raise ConfigError(f"{where}: flash_fx needs fx: one of {', '.join(KINDS)}")
        if m.params.get("side", "left") not in ("left", "right"):
            raise ConfigError(f"{where}: flash_fx side is left or right")
    if m.action == "busk" and (not m.params.get("panel") or not m.params.get("widget")):
        raise ConfigError(f"{where}: busk needs panel and widget")
    if m.action == "sub_master":
        try:
            Kind(m.params.get("kind"))
        except ValueError as e:
            raise ConfigError(f"{where}: sub_master needs kind") from e


class MidiMap:
    def __init__(self, name: str = "MIDI map", mappings: list[Mapping] | None = None) -> None:
        self.name = name
        self._by_key: dict[tuple[str, int, int, str], Mapping] = {}
        for m in mappings or []:
            self.add(m)

    @property
    def mappings(self) -> list[Mapping]:
        return list(self._by_key.values())

    def add(self, m: Mapping) -> Mapping | None:
        """Add or replace (same input). Returns the mapping it replaced."""
        validate(m)
        old = self._by_key.get(m.key)
        self._by_key[m.key] = m
        return old

    def remove(self, key: tuple) -> None:
        """key: (type, channel, number) or (type, channel, number, port)."""
        if len(key) == 3:
            key = (*key, "")
        last = key[3] or ""
        self._by_key.pop((key[0], key[1], key[2], last if key[0] == "osc" else last.lower()), None)

    def get_input(self, name: str) -> Mapping | None:
        return self._by_key.get(("input", 0, 0, name))

    def inputs_used(self) -> set[str]:
        return {m.input for m in self._by_key.values() if m.type == "input" and m.input}

    def get_osc(self, address: str) -> Mapping | None:
        return self._by_key.get(("osc", 0, 0, address))

    def get(self, type_: str, channel: int, number: int, port_name: str | None = None) -> Mapping | None:
        """The mapping for this input. With a port name, a port-specific mapping wins."""
        if port_name is not None:
            for m in self._by_key.values():
                if m.port and (m.type, m.channel, m.number) == (type_, channel, number) and m.matches_port(port_name):
                    return m
        return self._by_key.get((type_, channel, number, ""))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "mappings": [m.to_dict() for m in self.mappings]}


def parse_map(data: dict) -> MidiMap:
    out = []
    for d in data.get("mappings") or []:
        d = dict(d)
        try:
            if "input" in d:
                d.pop("type", None)
                out.append(Mapping("input", 0, 0, d.pop("action"), input=str(d.pop("input")), params=d))
                continue
            if d.get("type") == "osc":
                d.pop("type")
                m = Mapping("osc", 0, 0, d.pop("action"), address=str(d.pop("address")), params=d)
                out.append(m)
                continue
            m = Mapping(d.pop("type"), int(d.pop("channel")), int(d.pop("number")), d.pop("action"),
                        port=d.pop("port", None), params=d)
        except KeyError as e:
            raise ConfigError(f"mapping {d} missing {e}") from e
        out.append(m)
    return MidiMap(data.get("name", "MIDI map"), out)


def load_map(path: str | Path) -> MidiMap:
    from ..versions import read_doc

    return parse_map(read_doc(path, "midi"))


def save_map(midimap: MidiMap, path: str | Path) -> None:
    """Plain write, keeping the file's comments. The app saves through ShowStore instead
    (validated and backed up); this is for tools and tests."""
    from ..yamlio import update_text

    p = Path(path)
    p.write_text(update_text(p.read_text(encoding="utf-8") if p.exists() else None, midimap.to_dict()), encoding="utf-8")
