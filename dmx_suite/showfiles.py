"""Load and check the YAML show folder (fixtures, rigs, looks, MIDI maps)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .fixtures import ConfigError, Patch, load_patch
from .look import Look, load_look
from .midi.map import MidiMap, load_map
from .palettes import Palettes, load_palettes
from .rig import Rig, load_rig
from .scenes import Scene, load_scenes


@dataclass
class ShowFiles:
    root: Path
    patch: Patch
    rig: Rig
    look: Look
    midimap: MidiMap
    midimap_path: Path
    palettes: Palettes
    scenes: dict[str, Scene]


def _pick(folder: Path, name: str) -> Path:
    p = folder / f"{name}.yaml"
    if not p.exists():
        have = sorted(x.stem for x in folder.glob("*.yaml"))
        raise ConfigError(f"no {folder.name}/{name}.yaml (have: {', '.join(have) or 'none'})")
    return p


def load_show(root: str | Path, rig: str = "full", look: str = "default", midi: str = "default") -> ShowFiles:
    root = Path(root)
    patch = load_patch(root / "fixtures.yaml")
    r = load_rig(_pick(root / "rigs", rig), patch)
    lk = load_look(_pick(root / "looks", look), patch)
    mp_path = _pick(root / "midi", midi)
    mp = load_map(mp_path)
    for m in mp.mappings:  # flash targets must exist in the patch
        if m.action == "flash":
            patch.resolve(m.params["fixtures"])
    pal = load_palettes(root / "palettes.yaml", patch)
    scenes = load_scenes(root / "scenes", patch, pal)
    return ShowFiles(root, patch, r, lk, mp, mp_path, pal, scenes)


def check_all(root: str | Path) -> list[str]:
    """Load every rig/look/MIDI map. Returns a list of problems (empty = all good)."""
    root = Path(root)
    problems: list[str] = []
    try:
        patch = load_patch(root / "fixtures.yaml")
    except (ConfigError, OSError) as e:
        return [f"fixtures.yaml: {e}"]
    unverified = [t.name for t in patch.types.values() if not t.verified]
    if unverified:
        problems.append(f"warning: unverified channel maps: {', '.join(unverified)}")
    for sub, loader in (("rigs", load_rig), ("looks", load_look)):
        for p in sorted((root / sub).glob("*.yaml")):
            try:
                loader(p, patch)
            except (ConfigError, OSError, KeyError, TypeError, ValueError) as e:
                problems.append(f"{sub}/{p.name}: {e}")
    try:
        pal = load_palettes(root / "palettes.yaml", patch)
    except (ConfigError, OSError, KeyError, TypeError, ValueError) as e:
        problems.append(f"palettes.yaml: {e}")
        pal = None
    if pal is not None:
        for p in sorted((root / "scenes").glob("*.yaml")):
            try:
                load_scenes_file(p, patch, pal)
            except (ConfigError, OSError, KeyError, TypeError, ValueError) as e:
                problems.append(f"scenes/{p.name}: {e}")
    for p in sorted((root / "midi").glob("*.yaml")):
        try:
            mp = load_map(p)
            for m in mp.mappings:
                if m.action == "flash":
                    patch.resolve(m.params["fixtures"])
        except (ConfigError, OSError, KeyError, TypeError, ValueError) as e:
            problems.append(f"midi/{p.name}: {e}")
    return problems


def load_scenes_file(path: Path, patch: Patch, pal: Palettes) -> Scene:
    import yaml

    from .scenes import parse_scene

    return parse_scene(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, patch, pal, path.stem)
