"""Setup page helpers: address check (patch report)."""

from __future__ import annotations

from dataclasses import dataclass

from .fixtures import DMX_CHANNELS, Patch
from .rig import Rig


@dataclass
class PatchRow:
    id: str
    type: str
    universe: int
    start: int
    end: int
    in_rig: bool
    verified: bool


def patch_report(patch: Patch, rig: Rig | None = None) -> tuple[list[PatchRow], list[str]]:
    """Rows sorted by universe/address, plus notes: gaps, unverified maps, fixtures not in the rig.
    Overlaps can't occur: the patch loader rejects them."""
    present = set(rig.present) if rig else set(patch.fixtures)
    rows = sorted(
        (
            PatchRow(f.id, f.type.name, f.universe, f.address, f.address + f.type.footprint - 1, f.id in present, f.type.verified)
            for f in patch.fixtures.values()
        ),
        key=lambda r: (r.universe, r.start),
    )
    notes: list[str] = []
    by_uni: dict[int, list[PatchRow]] = {}
    for r in rows:
        by_uni.setdefault(r.universe, []).append(r)
    for uni, rs in by_uni.items():
        used = sum(r.end - r.start + 1 for r in rs)
        notes.append(f"universe {uni}: {used}/{DMX_CHANNELS} channels used, last {rs[-1].end}")
        prev = 0
        for r in rs:
            if r.start > prev + 1:
                notes.append(f"universe {uni}: gap {prev + 1}-{r.start - 1} before {r.id}")
            prev = r.end
    unverified = sorted({r.type for r in rows if not r.verified})
    if unverified:
        notes.append("unverified channel maps: " + ", ".join(unverified))
    return rows, notes


def format_report(rows: list[PatchRow], notes: list[str]) -> str:
    out = [f"{'fixture':10} {'type':28} {'uni':>3} {'start':>5} {'end':>5}  rig  checked"]
    for r in rows:
        out.append(
            f"{r.id:10} {r.type[:28]:28} {r.universe:>3} {r.start:>5} {r.end:>5}  "
            f"{'yes' if r.in_rig else ' - '}  {'yes' if r.verified else 'NO'}"
        )
    out += notes
    return "\n".join(out)
