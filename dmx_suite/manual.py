"""The user manual (docs/manual/*.md) shown inside the app, offline.

A small Markdown to HTML renderer for what the manual uses: headings (with GitHub-style anchors so
`page.md#section` links work), paragraphs, bullet and numbered lists (nested), tables, fenced code,
and inline code, bold, italics and links. Everything from the file is HTML-escaped.

Link rules: other manual pages and `#anchors` stay in the app (`/manual/page.md#anchor`); http(s)
links open in a new tab (the desktop window sends them to the system browser); anything else
(`javascript:`, `data:`, `mailto:`, paths out of the manual) keeps its text but loses the link.
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

from .paths import manual_dir

PAGE_RE = re.compile(r"^(?:[a-z0-9-]+|README)\.md$")
_LOCAL = re.compile(r"^(?P<page>(?:[a-z0-9-]+|README)\.md)?(?P<anchor>#[a-z0-9_-]+)?$")


def slug(text: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"[`*_]", "", text).strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def page_path(name: str, root: Path | None = None) -> Path | None:
    """The manual page called `name`, or None if there isn't one (or the name tries to leave the folder)."""
    if not PAGE_RE.match(name):
        return None
    base = (root or manual_dir()).resolve()
    f = (base / name).resolve()
    return f if f.is_relative_to(base) and f.is_file() else None


# ---------------------------------------------------------------- inline


def link(text_html: str, url: str) -> str:
    """One link under the rules above; `text_html` is already escaped."""
    url = url.strip()
    low = url.lower()
    if low.startswith(("http://", "https://")):
        return f'<a href="{escape(url)}" target="_blank" rel="noopener" data-external>{text_html}</a>'
    m = _LOCAL.match(url)
    if url and m:
        page = m.group("page")
        href = f"/manual/{page}" if page else ""
        return f'<a href="{escape(href + (m.group("anchor") or ""))}">{text_html}</a>'
    return text_html  # javascript:, data:, mailto:, ../ and anything else: text only


def _emphasis(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)


def _text(s: str) -> str:
    """Escaped text with links, bold and italics (no code spans in here)."""
    out, pos = [], 0
    for m in re.finditer(r"\[([^\]]+)\]\(([^)\s]*)\)", s):
        out.append(_emphasis(escape(s[pos:m.start()])))
        out.append(link(_emphasis(escape(m.group(1))), m.group(2)))
        pos = m.end()
    out.append(_emphasis(escape(s[pos:])))
    return "".join(out)


def inline(s: str) -> str:
    parts = re.split(r"(`[^`]+`)", s)
    return "".join(f"<code>{escape(p[1:-1])}</code>" if p.startswith("`") and p.endswith("`") and len(p) > 1
                   else _text(p) for p in parts)


# ---------------------------------------------------------------- blocks

_LIST = re.compile(r"^(?P<ind>\s*)(?P<mark>[-*+]|\d+[.)])\s+(?P<body>.*)$")


def _cells(row: str) -> list[str]:
    row = row.strip()
    row = row[1:] if row.startswith("|") else row
    row = row[:-1] if row.endswith("|") else row
    return [c.strip() for c in row.split("|")]


def _list(items: list[tuple[int, str, str]]) -> str:
    """Nested lists from (indent, marker, text) items."""
    out: list[str] = []
    stack: list[tuple[int, str]] = []  # (indent, tag)
    for ind, mark, body in items:
        tag = "ol" if mark[0].isdigit() else "ul"
        while stack and ind < stack[-1][0]:
            out.append(f"</li></{stack.pop()[1]}>")
        if stack and ind == stack[-1][0] and tag != stack[-1][1]:  # bullets then numbers: a new list
            out.append(f"</li></{stack.pop()[1]}>")
        if not stack or ind > stack[-1][0]:
            stack.append((ind, tag))
            out.append(f"<{tag}><li>")
        else:
            out.append("</li><li>")
        out.append(inline(body))
    while stack:
        out.append(f"</li></{stack.pop()[1]}>")
    return "".join(out)


def render(md: str) -> str:
    """Markdown body to HTML."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            out.append(f"<p>{inline(' '.join(x.strip() for x in para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            flush()
            lang = line.strip()[3:].strip()
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            cls = f' class="lang-{escape(lang)}"' if re.fullmatch(r"[a-z0-9]+", lang) else ""
            out.append(f"<pre><code{cls}>{escape(chr(10).join(code))}</code></pre>")
            i += 1
            continue
        h = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if h:
            flush()
            n, text = len(h.group(1)), h.group(2)
            out.append(f'<h{n} id="{escape(slug(text))}">{inline(text)}</h{n}>')
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]) \
                and "-" in lines[i + 1]:
            flush()
            head = _cells(line)
            i += 2
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            th = "".join(f"<th>{inline(c)}</th>" for c in head)
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>")
            continue
        if _LIST.match(line):
            flush()
            items: list[tuple[int, str, str]] = []
            while i < len(lines):
                m = _LIST.match(lines[i])
                if m:
                    items.append((len(m.group("ind").expandtabs(4)), m.group("mark"), m.group("body")))
                elif lines[i].strip() and lines[i].startswith(" ") and items:  # a wrapped item
                    ind, mark, body = items[-1]
                    items[-1] = (ind, mark, f"{body} {lines[i].strip()}")
                else:
                    break
                i += 1
            out.append(_list(items))
            continue
        if line.startswith("> "):
            flush()
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i][1:].strip())
                i += 1
            out.append(f"<blockquote><p>{inline(' '.join(quote))}</p></blockquote>")
            continue
        if not line.strip():
            flush()
        else:
            para.append(line)
        i += 1
    flush()
    return "\n".join(out)


def page(name: str, md: str, theme: str, title: str = "Manual", back: str = "Contents") -> str:
    """A whole page in the app's theme, with a link back to the contents (README)."""
    first = re.search(r"^#\s+(.*)$", md, re.M)
    heading = escape(re.sub(r"[`*]", "", first.group(1))) if first else escape(title)
    nav = "" if name == "README.md" else f'<nav class="manual-nav"><a href="/manual/README.md">&larr; {escape(back)}</a></nav>'
    return (
        "<!doctype html>\n<html lang=\"en-AU\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{heading} - {escape(title)}</title>"
        f'<link rel="stylesheet" href="/static/themes/{escape(theme)}/theme.css">'
        '<link rel="stylesheet" href="/static/style.css">'
        '<link rel="icon" href="/static/brand/icon.svg" type="image/svg+xml">'
        f'</head><body class="manual">{nav}<main class="manual-body">{render(md)}</main></body></html>'
    )
