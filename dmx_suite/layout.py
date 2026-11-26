"""Stage plan: where each fixture is. Uses the rig's `layout`; anything not placed yet gets a
sensible default spot (heads at the back, bars across the middle, washes at the front corners,
kick on the drum riser), so a new rig always has a plan to start arranging from."""

from __future__ import annotations

from .fixtures import Kind
from .rig import Placement, Rig


def _spread(n: int, width: float, margin: float) -> list[float]:
    if n == 1:
        return [width / 2]
    usable = width - 2 * margin
    return [margin + usable * i / (n - 1) for i in range(n)]


def full_layout(rig: Rig) -> dict[str, Placement]:
    """Rig layout with defaults filled in for fixtures that haven't been placed."""
    w, d = rig.stage
    placed = dict(rig.layout)
    todo = [f for f in rig.fixtures if f.id not in placed]
    rows = {
        Kind.HEAD: (d * 0.85, 0.8),
        Kind.BAR: (d * 0.62, 0.9),
        Kind.WASH: (d * 0.12, 0.6),
        Kind.HAZE: (d * 0.95, 0.4),
    }
    for kind, (y, margin) in rows.items():
        group = [f for f in todo if f.kind == kind]
        if kind == Kind.WASH and len(group) == 2:  # one each front corner
            xs = [0.6, w - 0.6]
        elif kind == Kind.HAZE:
            xs = [w - 0.4 - i * 0.6 for i in range(len(group))]
        else:
            xs = _spread(len(group), w, margin)
        for f, x in zip(group, xs):
            placed[f.id] = Placement(round(x, 2), round(y, 2), 0.0)
    for i, f in enumerate(f for f in todo if f.kind == Kind.KICK):
        placed[f.id] = Placement(round(w / 2 + i * 0.5, 2), round(d * 0.4, 2), 0.0)
    return {f.id: placed[f.id] for f in rig.fixtures if f.id in placed}
