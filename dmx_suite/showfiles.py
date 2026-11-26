"""Load and check the YAML show folder (fixtures, rigs, looks, MIDI maps)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .auto import generate
from .fixtures import ConfigError, Patch, load_patch
from .look import INTENSITY_RULE1, Look, load_look
from .midi.map import MidiMap, load_map
from .palettes import Palettes, load_palettes
from .rig import Rig, load_rig
from .scenes import Scene, load_scenes
from .shows import Setlist, Show, load_setlists, load_shows, parse_setlist, parse_show
from .versions import read_doc

# what a broken show file can raise while loading; all reported as show file problems
FILE_ERRORS = (ConfigError, OSError, KeyError, TypeError, ValueError, AttributeError, IndexError)


def _load(where: str, fn, *args):
    """Run a loader; anything a malformed file causes comes out as a ConfigError naming the file."""
    try:
        return fn(*args)
    except ConfigError:
        raise
    except FILE_ERRORS as e:
        raise ConfigError(f"{where}: {type(e).__name__}: {e}") from e


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
    shows: dict[str, Show]
    setlists: dict[str, Setlist]


def _pick(folder: Path, name: str) -> Path:
    p = folder / f"{name}.yaml"
    if not p.exists():
        have = sorted(x.stem for x in folder.glob("*.yaml"))
        raise ConfigError(f"no {folder.name}/{name}.yaml (have: {', '.join(have) or 'none'})")
    return p


def profile_problems(rig: Rig, scenes: dict[str, Scene], looks: dict[str, Look]) -> list[str]:
    """What breaks the rig's profile rules. Scenes and looks are shared by every rig, so this
    runs per rig: `intensity` is fine on a Generic rig and refused on a "0.05 band" one (rule 1)."""
    if not rig.profile.master_gate:
        return []
    out = [f"scenes/{k}.yaml {INTENSITY_RULE1}" for k, sc in sorted(scenes.items()) if sc.uses_intensity]
    out += [f"looks/{k}.yaml {INTENSITY_RULE1}" for k, lk in sorted(looks.items()) if lk.uses_intensity]
    return out


def load_show(root: str | Path, rig: str = "full", look: str = "default", midi: str = "default") -> ShowFiles:
    root = Path(root)
    patch = _load("fixtures.yaml", load_patch, root / "fixtures.yaml")
    r = _load(f"rigs/{rig}.yaml", load_rig, _pick(root / "rigs", rig), patch)
    lk = _load(f"looks/{look}.yaml", load_look, _pick(root / "looks", look), patch)
    mp_path = _pick(root / "midi", midi)
    mp = _load(f"midi/{midi}.yaml", load_map, mp_path)
    for m in mp.mappings:  # flash targets must exist in the patch
        if m.action == "flash":
            patch.resolve(m.params["fixtures"])
    pal = _load("palettes.yaml", load_palettes, root / "palettes.yaml", patch)
    scenes = _load("scenes", load_scenes, root / "scenes", patch, pal)
    shows = _load("shows", load_shows, root / "shows", pal, scenes)
    setlists = _load("setlists", load_setlists, root / "setlists", shows, scenes)
    for m in mp.mappings:  # show/scene names in the MIDI map must exist
        for key, table in (("show", shows), ("scene", scenes)):
            if key in m.params and m.params[key] not in table:
                raise ConfigError(f"MIDI map {m.type} ch{m.channel} #{m.number}: unknown {key} {m.params[key]!r}")
    bad = profile_problems(r, scenes, {look: lk})
    if bad:
        raise ConfigError(f"rig {rig} (profile {r.profile.name}): " + "; ".join(bad))
    return ShowFiles(root, patch, r, lk, mp, mp_path, pal, scenes, shows, setlists)


def check_all(root: str | Path) -> list[str]:
    """Load every rig/look/MIDI map. Returns a list of problems (empty = all good)."""
    root = Path(root)
    problems: list[str] = []
    try:
        patch = load_patch(root / "fixtures.yaml")
    except FILE_ERRORS as e:
        return [f"fixtures.yaml: {e}"]
    unverified = [t.name for t in patch.types.values() if not t.verified]
    if unverified:
        problems.append(f"warning: unverified channel maps: {', '.join(unverified)}")
    rigs: dict[str, Rig] = {}
    looks: dict[str, Look] = {}
    for p in sorted((root / "rigs").glob("*.yaml")):
        try:
            rigs[p.stem] = load_rig(p, patch)
        except FILE_ERRORS as e:
            problems.append(f"rigs/{p.name}: {e}")
    for p in sorted((root / "looks").glob("*.yaml")):
        try:
            looks[p.stem] = load_look(p, patch)
        except FILE_ERRORS as e:
            problems.append(f"looks/{p.name}: {e}")
    try:
        pal = load_palettes(root / "palettes.yaml", patch)
    except FILE_ERRORS as e:
        problems.append(f"palettes.yaml: {e}")
        pal = None
    scenes: dict = {}
    shows: dict = {}
    if pal is not None:
        for p in sorted((root / "scenes").glob("*.yaml")):
            try:
                scenes[p.stem] = load_scenes_file(p, patch, pal)
            except FILE_ERRORS as e:
                problems.append(f"scenes/{p.name}: {e}")
        for p in sorted((root / "shows").glob("*.yaml")):
            try:
                shows[p.stem] = parse_show(p.stem, read_doc(p, "show"), pal, scenes)
            except FILE_ERRORS as e:
                problems.append(f"shows/{p.name}: {e}")
        for p in sorted((root / "setlists").glob("*.yaml")):
            try:
                parse_setlist(p.stem, read_doc(p, "setlist"), shows, scenes)
            except FILE_ERRORS as e:
                problems.append(f"setlists/{p.name}: {e}")
        # scenes and looks are shared: each must suit every rig's profile (rule 1)
        for rk, rig in rigs.items():
            problems += [f"rig {rk} (profile {rig.profile.name}): {p}" for p in profile_problems(rig, scenes, looks)]
        # every auto set must produce valid scenes on every rig
        for sk, show in shows.items():
            for rk, rig in rigs.items():
                for st in show.sets.values():
                    if st.auto is None:
                        continue
                    try:
                        for step in range(20):
                            generate(st.auto, rig, pal, step, "check")
                    except FILE_ERRORS as e:
                        problems.append(f"shows/{sk}.yaml set {st.name} on rig {rk}: {e}")
    for p in sorted((root / "midi").glob("*.yaml")):
        try:
            mp = load_map(p)
            for m in mp.mappings:
                if m.action == "flash":
                    patch.resolve(m.params["fixtures"])
            if any(m.action == "flash" for m in mp.mappings):
                off = [rk for rk, rig in rigs.items() if not rig.profile.drum_flash]
                if off:
                    problems.append(f"warning: midi/{p.name} has drum flash mappings; drum flash is off "
                                    f"in the profile of rig {', '.join(off)} (rule 2)")
                for key, table in (("show", shows), ("scene", scenes)):
                    if key in m.params and m.params[key] not in table:
                        raise ConfigError(f"{m.type} ch{m.channel} #{m.number}: unknown {key} {m.params[key]!r}")
        except FILE_ERRORS as e:
            problems.append(f"midi/{p.name}: {e}")
    return problems


def load_scenes_file(path: Path, patch: Patch, pal: Palettes) -> Scene:
    from .scenes import parse_scene

    return parse_scene(read_doc(path, "scene"), patch, pal, path.stem)
