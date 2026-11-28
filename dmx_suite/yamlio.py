"""Writing show files without losing what people wrote in them.

Every save from the UI, Claude or a file upgrade goes through `update_text`: the file is loaded
with ruamel.yaml (which keeps comments), only the parts whose data changed are replaced, and
lines whose content didn't change keep their original spacing (hand-aligned columns stay aligned).
The result is checked to read back (with PyYAML, as the loaders do) as exactly the new data;
if it ever doesn't, the file is written plainly instead, so a save is never wrong, only plainer.

The show loaders read with PyYAML (YAML 1.1, where `off` is false); ruamel reads YAML 1.2. The
merge compares against PyYAML's reading of the old file, so a value only counts as changed if
the loaders would see a change, and new strings that YAML 1.1 would misread are quoted.
"""

from __future__ import annotations

import difflib
import io
import logging
from typing import Any

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError as RuamelError
from ruamel.yaml.scalarstring import SingleQuotedScalarString

log = logging.getLogger(__name__)


def _rt() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096  # never wrap: long flow lines stay on one line
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def plain_dump(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=None, width=110)


def _same(a: Any, b: Any) -> bool:
    return type(a) is type(b) and a == b


def _is_leaf(v: Any) -> bool:
    return not isinstance(v, (dict, list))


def to_rt(v: Any) -> Any:
    """Plain data -> ruamel nodes, styled like PyYAML's default_flow_style=None."""
    if isinstance(v, dict):
        m = CommentedMap((k, to_rt(x)) for k, x in v.items())
        if all(_is_leaf(x) for x in v.values()):
            m.fa.set_flow_style()
        return m
    if isinstance(v, list):
        s = CommentedSeq(to_rt(x) for x in v)
        if all(_is_leaf(x) for x in v):
            s.fa.set_flow_style()
        return s
    if isinstance(v, str):
        try:
            misread = yaml.safe_load(v) != v
        except yaml.YAMLError:
            misread = True
        return SingleQuotedScalarString(v) if misread or v == "" else v
    return v


def merge(rt: Any, old: Any, new: Any) -> Any:
    """Return `rt` (the ruamel tree of the old file) changed to hold `new`. `old` is PyYAML's
    reading of the same file, walked alongside so unchanged parts keep their nodes."""
    if _same(old, new):
        return rt
    if isinstance(new, dict) and isinstance(old, dict) and isinstance(rt, CommentedMap) and len(rt) == len(old):
        keys = dict(zip(old.keys(), rt.keys()))  # same document order; PyYAML key -> ruamel key
        for ok, rk in keys.items():
            if ok not in new:
                del rt[rk]
        for i, (k, v) in enumerate(new.items()):
            if k in keys:
                rt[keys[k]] = merge(rt[keys[k]], old[k], v)
            else:
                rt.insert(min(i, len(rt)), k, to_rt(v))  # where it sits in the new data (version: first)
        return rt
    if isinstance(new, list) and isinstance(old, list) and isinstance(rt, CommentedSeq) and len(rt) == len(old):
        n = min(len(new), len(old))
        for i in range(n):
            rt[i] = merge(rt[i], old[i], new[i])
        del rt[n:]
        rt.extend(to_rt(x) for x in new[n:])
        return rt
    return to_rt(new)


def keep_layout(old_text: str, new_text: str) -> str:
    """Use the old line wherever only spacing inside the line differs (same indentation)."""

    def norm(line: str) -> str:
        body = line.lstrip(" ")
        return line[: len(line) - len(body)] + " ".join(body.split())

    old = old_text.splitlines(keepends=True)
    new = new_text.splitlines(keepends=True)
    sm = difflib.SequenceMatcher(a=[norm(x) for x in old], b=[norm(x) for x in new], autojunk=False)
    out: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        out += old[i1:i2] if tag == "equal" else new[j1:j2]
    return "".join(out)


def _reads_as(text: str, data: Any) -> bool:
    try:
        return yaml.safe_load(text) == data
    except yaml.YAMLError:
        return False


def update_text(old_text: str | None, new: Any) -> str:
    """The text to write so a file holding `old_text` holds `new`, keeping comments and layout."""
    if old_text is None or not old_text.strip():
        return plain_dump(new)
    try:
        old = yaml.safe_load(old_text)
        y = _rt()
        tree = merge(y.load(old_text), old, new)
        buf = io.StringIO()
        y.dump(tree, buf)
        kept = keep_layout(old_text, buf.getvalue())
    except (yaml.YAMLError, RuamelError, TypeError, ValueError, AttributeError) as e:
        log.warning("couldn't keep comments (%s); writing plainly", e)
        return plain_dump(new)
    for text in (kept, buf.getvalue()):
        if _reads_as(text, new):
            return text
    log.warning("comment-keeping save didn't read back the same; writing plainly")
    return plain_dump(new)
