"""Effect registry: every effect a scene layer can run, one class each (see base.py).

To add an effect: write a class (settings in `params`, drawing in `render`), add it to a list
below, and it appears in the scene builder, auto shows can use it, and Claude's guide lists it.
"""

from __future__ import annotations

from typing import Any

from .base import BLENDS, Effect, ParseCtx, Run, Unit, place_units
from .classic import CLASSIC
from .matrix import MATRIX
from .more import MORE

REGISTRY: dict[str, Effect] = {cls.name: cls() for cls in (*CLASSIC, *MORE, *MATRIX)}


def get(name: str) -> Effect | None:
    return REGISTRY.get(name)


def schemas() -> list[dict[str, Any]]:
    return [e.to_json() for e in REGISTRY.values()]


def guide() -> str:
    """One line per effect with its settings, for Claude's guide."""
    lines = []
    for e in REGISTRY.values():
        keys = ", ".join(p.key for p in e.params if p.key not in ("mapping", "direction", "angle", "groups_of"))
        lines.append(f"  {e.name}: {e.help} Settings: {keys}" + ("; moves heads" if e.movement else ""))
    return "\n".join(lines)


__all__ = ["BLENDS", "REGISTRY", "Effect", "ParseCtx", "Run", "Unit", "get", "guide", "place_units", "schemas"]
