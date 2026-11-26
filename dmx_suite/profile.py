"""Rule profiles: which of the rig rules apply to a rig.

The rules come in two kinds (docs/SCOPE.md, CLAUDE.md):

Safety rules are always on, for every user, and nothing here can turn them off:
    4 no background glow, 5 haze only from the Haze controls, 6 grand master scales intensity
    only, 8 head limits.

Profile rules are settings, picked per rig config:
    1 `master_gate`   MASTER owns on/off; scenes are colour only and can't set `intensity`.
                      Off: lights follow the scene (standard dimmer behaviour), MASTER has no
                      effect and scenes may set `intensity` (0-1).
    2 `drum_flash`    with MASTER off, mapped drum hits flash the rig. Needs `master_gate`.
    3 `master_exempt` fixtures MASTER never affects: fixture ids, groups, or a kind name
                      (head, bar, wash, kick) meaning every fixture of that kind, e.g. the 0.05
                      kick-drum light. They light from the scene, or the rig's `kick_colour`
                      when the scene leaves them off. Only meaningful with `master_gate`.

Rule 7 (colour-only heads, speed-channel direction) lives in the fixture definition.

In a rig file:

    profile: 0.05_band            # or: generic

    profile:                      # or a shipped profile with changes
      base: generic
      name: Club rig
      master_exempt: [kick]

A rig file with no `profile:` is a v1 file and runs as "0.05 band", exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .fixtures import ConfigError, Kind, Patch


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    master_gate: bool  # rule 1
    drum_flash: bool  # rule 2
    master_exempt: tuple[str, ...] = ()  # rule 3: fixture ids, groups or kinds

    def summary(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "master_gate": self.master_gate,
                "drum_flash": self.drum_flash, "master_exempt": list(self.master_exempt)}


GENERIC = Profile("generic", "Generic", master_gate=False, drum_flash=False)
BAND_005 = Profile("0.05_band", "0.05 band", master_gate=True, drum_flash=True, master_exempt=(Kind.KICK.value,))
PROFILES = {p.key: p for p in (GENERIC, BAND_005)}
V1_DEFAULT = BAND_005  # rig files from before profiles existed

_SETTINGS = {"master_gate", "drum_flash", "master_exempt"}


def parse_profile(data: Any) -> Profile:
    if data is None:
        return V1_DEFAULT
    if isinstance(data, str):
        if data not in PROFILES:
            raise ConfigError(f"unknown profile {data!r}; one of {sorted(PROFILES)}")
        return PROFILES[data]
    if not isinstance(data, dict):
        raise ConfigError("profile must be a profile name or a block with base/settings")
    bad = set(data) - _SETTINGS - {"base", "name"}
    if bad:
        raise ConfigError(f"profile: unknown keys {sorted(bad)}")
    base_key = data.get("base", GENERIC.key)
    if base_key not in PROFILES:
        raise ConfigError(f"profile base: unknown profile {base_key!r}; one of {sorted(PROFILES)}")
    p = PROFILES[base_key]
    changes: dict[str, Any] = {}
    for k in ("master_gate", "drum_flash"):
        if k in data:
            if not isinstance(data[k], bool):
                raise ConfigError(f"profile {k} must be true or false")
            changes[k] = data[k]
    if "master_exempt" in data:
        v = data["master_exempt"] or []
        changes["master_exempt"] = tuple(str(x) for x in (v if isinstance(v, list) else [v]))
    if changes or "name" in data:
        p = replace(p, key="custom", name=str(data.get("name", f"{p.name} (custom)")), **changes)
    if p.drum_flash and not p.master_gate:
        raise ConfigError("profile: drum_flash needs master_gate (drum hits flash while MASTER is off, rule 2)")
    return p


def resolve_exempt(profile: Profile, patch: Patch, present: list[str]) -> frozenset[str]:
    """Fixture ids in the rig that MASTER never affects (rule 3). Empty without `master_gate`."""
    if not profile.master_gate:
        return frozenset()
    kinds = {k.value for k in Kind}
    ids: set[str] = set()
    for name in profile.master_exempt:
        if name in kinds:  # a kind name means every fixture of that kind (as v1 did for kick)
            ids.update(f.id for f in patch.fixtures.values() if f.kind.value == name)
        else:
            ids.update(patch.resolve([name]))
    return frozenset(f for f in present if f in ids)
