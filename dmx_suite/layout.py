"""Light layout: where each light sits on the layout grid (see rig.Placement). Lights not placed
yet get a default spot, so a new rig always has a layout to start arranging from: moving heads
in a row at the back, bars end to end across the middle, washes and the kick light at the front,
haze to the side."""

from __future__ import annotations

from .fixtures import Kind
from .rig import Placement, Rig

ROWS = {Kind.HEAD: 2.0, Kind.BAR: 6.0, Kind.WASH: 10.0, Kind.KICK: 10.0, Kind.HAZE: 14.0}


def full_layout(rig: Rig) -> dict[str, Placement]:
    """The rig's layout with defaults filled in for lights that haven't been placed."""
    placed = dict(rig.layout)
    x_next: dict[float, float] = {}
    for f in rig.fixtures:
        if f.id in placed:
            continue
        y = ROWS.get(f.kind, 14.0)
        width = max(1, f.type.pixels or 1)  # a pixel bar is a row of cells
        x = x_next.get(y, 1.0)
        placed[f.id] = Placement(x + (width - 1) / 2, y)  # x, y are the light's centre
        x_next[y] = x + width + 1
    return {f.id: placed[f.id] for f in rig.fixtures if f.id in placed}
