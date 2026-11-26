"""MIDI map: which program change / note / CC does what. Per show, in YAML (shows/midi/*.yaml).

    mappings:
      - {type: program_change, channel: 1, number: 0, action: master_toggle}
      - {type: note, channel: 10, number: 38, action: flash, fixtures: [bars], length_ms: 120, colour: show}
      - {type: control_change, channel: 1, number: 7, action: grand_master}

Channels are 1-16 as printed on the gear (mido uses 0-15).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..fixtures import ConfigError, Kind

TYPES = ("note", "program_change", "control_change")

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
    # phase 4 (auto shows / setlist): accepted in the map now, not acted on yet
    "select_show": {"show"},
    "select_set": {"set"},
    "next_song": set(),
}
CONTINUOUS = {"grand_master", "sub_master", "flash_level"}  # need a CC


@dataclass
class Mapping:
    type: str
    channel: int  # 1-16
    number: int  # note / program / controller
    action: str
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, int, int]:
        return (self.type, self.channel, self.number)

    def describe(self) -> str:
        extra = " ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.action} {extra}".strip()

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "channel": self.channel, "number": self.number, "action": self.action, **self.params}


def validate(m: Mapping) -> None:
    where = f"{m.type} ch{m.channel} #{m.number}"
    if m.type not in TYPES:
        raise ConfigError(f"{where}: type must be one of {TYPES}")
    if not 1 <= m.channel <= 16 or not 0 <= m.number <= 127:
        raise ConfigError(f"{where}: channel 1-16, number 0-127")
    if m.action not in ACTIONS:
        raise ConfigError(f"{where}: unknown action {m.action!r}")
    bad = set(m.params) - ACTIONS[m.action]
    if bad:
        raise ConfigError(f"{where}: {m.action} doesn't take {sorted(bad)}")
    if m.action in CONTINUOUS and m.type != "control_change":
        raise ConfigError(f"{where}: {m.action} needs a control_change")
    if m.action == "flash":
        if not m.params.get("fixtures"):
            raise ConfigError(f"{where}: flash needs fixtures")
        c = m.params.get("colour", "show")
        if c not in ("show", "white"):
            raise ConfigError(f"{where}: flash colour must be show or white")
    if m.action == "sub_master":
        try:
            Kind(m.params.get("kind"))
        except ValueError as e:
            raise ConfigError(f"{where}: sub_master needs kind") from e


class MidiMap:
    def __init__(self, name: str = "MIDI map", mappings: list[Mapping] | None = None) -> None:
        self.name = name
        self._by_key: dict[tuple[str, int, int], Mapping] = {}
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

    def remove(self, key: tuple[str, int, int]) -> None:
        self._by_key.pop(key, None)

    def get(self, type_: str, channel: int, number: int) -> Mapping | None:
        return self._by_key.get((type_, channel, number))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "mappings": [m.to_dict() for m in self.mappings]}


def parse_map(data: dict) -> MidiMap:
    out = []
    for d in data.get("mappings") or []:
        d = dict(d)
        try:
            m = Mapping(d.pop("type"), int(d.pop("channel")), int(d.pop("number")), d.pop("action"), d)
        except KeyError as e:
            raise ConfigError(f"mapping {d} missing {e}") from e
        out.append(m)
    return MidiMap(data.get("name", "MIDI map"), out)


def load_map(path: str | Path) -> MidiMap:
    return parse_map(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})


def save_map(midimap: MidiMap, path: str | Path) -> None:
    Path(path).write_text(yaml.safe_dump(midimap.to_dict(), sort_keys=False, allow_unicode=True), encoding="utf-8")
