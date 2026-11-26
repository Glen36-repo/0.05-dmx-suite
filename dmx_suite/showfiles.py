"""Load and check the YAML show folder (fixtures, rigs, looks, MIDI maps)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .auto import generate
from .busk import Panel, parse_panels
from .fixtures import ConfigError, Patch, load_patch
from .layout import layout_warnings
from .look import INTENSITY_RULE1, Look, load_look
from .midi.map import MidiMap, load_map, validate, where_of
from .midi.named import Inputs, load_inputs
from .palettes import Palettes, load_palettes
from .presets import load_presets, load_ratings, preset_scenes
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
    panels: dict[str, Panel] = field(default_factory=dict)  # busking (panels.yaml, optional)
    inputs: Inputs = field(default_factory=Inputs)  # named MIDI/OSC inputs (inputs.yaml, v3)
    presets: dict = field(default_factory=dict)  # presets.yaml + starters (v3.5)
    ratings: dict = field(default_factory=dict)  # ratings.yaml: look key -> 1 / -1 / -2 (v3.5)


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


def _other_points(root: Path, skip: str) -> dict:
    """Point names other rigs have (values not needed): a scene may name one this rig lacks."""
    from .rig import Point

    out: dict = {}
    for p in sorted((root / "rigs").glob("*.yaml")):
        if p.stem == skip:
            continue
        try:
            d = read_doc(p, "rig")
        except FILE_ERRORS:
            continue
        for name in (d.get("positions") or {}) if isinstance(d.get("positions"), dict) else {}:
            out.setdefault(str(name), Point(str(name)))
    return out


def folder_palettes(root: Path, patch: Patch) -> Palettes:
    """palettes.yaml with every rig's head points (first rig's values win): for checks that
    aren't about one rig, e.g. Claude validating a scene with the app closed."""
    from .rig import Point, parse_points

    pal = load_palettes(root / "palettes.yaml", patch)
    union: dict[str, Point] = {}
    for p in sorted((root / "rigs").glob("*.yaml"), reverse=True):
        try:
            union.update(parse_points(read_doc(p, "rig").get("positions"), patch))
        except FILE_ERRORS:
            continue
    return pal.with_points(union)


def check_step_inputs(scenes: dict, inputs: Inputs) -> None:
    """Step scenes moved on by a named input: the input must exist (v3.2)."""
    for k, sc in scenes.items():
        name = getattr(sc.steps, "advance_input", None) if sc.steps is not None else None
        if name and name not in inputs:
            raise ConfigError(f"scenes/{k}.yaml: advance: no input {name!r} in inputs.yaml")


def check_map_inputs(mp: MidiMap, inputs: Inputs) -> None:
    """Mappings that name an input: the input must exist, and faders need a CC or OSC input."""
    for m in mp.mappings:
        if m.type == "input":
            inp = inputs.get(m.input or "")
            if inp is None:
                raise ConfigError(f"MIDI map {where_of(m)}: no such input in inputs.yaml "
                                  f"(have: {', '.join(sorted(inputs.inputs)) or 'none'})")
            validate(m, inp.type)


def load_show(root: str | Path, rig: str = "full", look: str = "default", midi: str = "default") -> ShowFiles:
    root = Path(root)
    patch = _load("fixtures.yaml", load_patch, root / "fixtures.yaml")
    inputs = _load("inputs.yaml", load_inputs, root / "inputs.yaml")
    r = _load(f"rigs/{rig}.yaml", load_rig, _pick(root / "rigs", rig), patch)
    lk = _load(f"looks/{look}.yaml", load_look, _pick(root / "looks", look), patch)
    mp_path = _pick(root / "midi", midi)
    mp = _load(f"midi/{midi}.yaml", load_map, mp_path)
    _load(f"midi/{midi}.yaml", check_map_inputs, mp, inputs)
    for m in mp.mappings:  # flash targets must exist in the patch
        if m.action == "flash":
            patch.resolve(m.params["fixtures"])
    pal = _load("palettes.yaml", load_palettes, root / "palettes.yaml", patch)
    pal = pal.with_points(r.points, _other_points(root, rig))  # this rig's head points (v3)
    scenes = _load("scenes", load_scenes, root / "scenes", patch, pal)
    check_step_inputs(scenes, inputs)
    presets = _load("presets.yaml", load_presets, root, set(pal.sets))
    scenes.update(_load("presets.yaml", preset_scenes, presets, r, pal, patch))  # "preset:<id>" (v3.5)
    shows = _load("shows", load_shows, root / "shows", pal, scenes)
    setlists = _load("setlists", load_setlists, root / "setlists", shows, scenes)
    for m in mp.mappings:  # show/scene names in the MIDI map must exist
        for key, table in (("show", shows), ("scene", scenes)):
            if key in m.params and m.params[key] not in table:
                raise ConfigError(f"MIDI map {where_of(m)}: unknown {key} {m.params[key]!r}")
    bad = profile_problems(r, scenes, {look: lk})
    if bad:
        raise ConfigError(f"rig {rig} (profile {r.profile.name}): " + "; ".join(bad))
    panels = _load("panels.yaml", load_panels, root / "panels.yaml", patch, pal, scenes, shows)
    for m in mp.mappings:  # busk mappings must name a real widget
        if m.action == "override":
            _busk_target(m.params, panels)
    sf = ShowFiles(root, patch, r, lk, mp, mp_path, pal, scenes, shows, setlists, panels, inputs)
    sf.presets = presets
    sf.ratings = _load("ratings.yaml", load_ratings, root)
    return sf


def load_panels(path: Path, patch: Patch, pal: Palettes, scenes: dict, shows: dict) -> dict[str, Panel]:
    if not path.exists():
        return {}
    return parse_panels(read_doc(path, "panels"), patch, pal, scenes, shows)


def _busk_target(params: dict, panels: dict[str, Panel]) -> None:
    panel = panels.get(str(params.get("panel")))
    if panel is None:
        raise ConfigError(f"MIDI map busk: unknown panel {params.get('panel')!r}")
    panel.widget(str(params.get("widget")))


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
    try:
        inputs: Inputs | None = load_inputs(root / "inputs.yaml")
    except FILE_ERRORS as e:
        problems.append(f"inputs.yaml: {e}")
        inputs = None
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
        union: dict = {}
        for rig in reversed(list(rigs.values())):  # every rig's points; the first rig's values win
            union.update(rig.points)
        pal = pal.with_points(union)
    except FILE_ERRORS as e:
        problems.append(f"palettes.yaml: {e}")
        pal = None
    for rk, rig in rigs.items():
        problems += [f"warning: rigs/{rk}.yaml {w}" for w in rig.point_problems()]
        problems += [f"warning: rigs/{rk}.yaml {w}" for w in layout_warnings(rig)]
    try:
        from .quality import load_rules

        load_rules(root)
    except FILE_ERRORS as e:
        problems.append(f"quality.yaml: {e}")
    scenes: dict = {}
    shows: dict = {}
    if pal is not None:
        for p in sorted((root / "scenes").glob("*.yaml")):
            try:
                scenes[p.stem] = load_scenes_file(p, patch, pal)
            except FILE_ERRORS as e:
                problems.append(f"scenes/{p.name}: {e}")
        try:
            presets = load_presets(root, set(pal.sets))
            for rig in rigs.values():  # every preset must compose on every rig
                made = preset_scenes(presets, rig, pal, patch)
                scenes.update(made)
        except FILE_ERRORS as e:
            problems.append(f"presets.yaml: {e}")
        try:
            load_ratings(root)
        except FILE_ERRORS as e:
            problems.append(f"ratings.yaml: {e}")
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
        try:
            panels = load_panels(root / "panels.yaml", patch, pal, scenes, shows)
        except FILE_ERRORS as e:
            problems.append(f"panels.yaml: {e}")
            panels = {}
        problems += [f"warning: {w}" for w in sorted(pal.warnings)]
        if inputs is not None:
            try:
                check_step_inputs(scenes, inputs)
            except ConfigError as e:
                problems.append(str(e))
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
            if inputs is not None:
                check_map_inputs(mp, inputs)
            for m in mp.mappings:
                if m.action == "override" and pal is not None:
                    _busk_target(m.params, panels)
                if m.action == "flash":
                    patch.resolve(m.params["fixtures"])
            if any(m.action == "flash" for m in mp.mappings):
                off = [rk for rk, rig in rigs.items() if not rig.profile.drum_flash]
                if off:
                    problems.append(f"warning: midi/{p.name} has drum flash mappings; drum flash is off "
                                    f"in the profile of rig {', '.join(off)} (rule 2)")
                for key, table in (("show", shows), ("scene", scenes)):
                    if key in m.params and m.params[key] not in table:
                        raise ConfigError(f"{where_of(m)}: unknown {key} {m.params[key]!r}")
        except FILE_ERRORS as e:
            problems.append(f"midi/{p.name}: {e}")
    return problems


def load_scenes_file(path: Path, patch: Patch, pal: Palettes) -> Scene:
    from .scenes import parse_scene

    return parse_scene(read_doc(path, "scene"), patch, pal, path.stem)
