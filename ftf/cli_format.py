"""Terminal output helpers for the CLI: colour, display width, truncation, aligned tables, text bars.

Standard library only. Colour is used only when asked for (`Style(enabled=True)`); ftf/cli.py enables it when
stdout is a terminal and NO_COLOR is unset.
"""
from __future__ import annotations

import os
import shutil
import sys
import textwrap
import unicodedata

ELLIPSIS = "…"
MIN_FLEX = 12            # a column is never squeezed below this width (material ids are 12 characters)
KEEP_FLEX = 40           # the free-text column keeps this much while other text columns can still give way
KEEP_TEXT = 16           # ... and those keep this much while the free-text column still has room
_CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36"}


class Style:
    """ANSI styling that degrades to plain text: `st.bold("x")`, `st("x", "green", "bold")`."""

    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def __call__(self, text, *names: str) -> str:
        text = str(text)
        codes = [_CODES[n] for n in names if n in _CODES]
        if not self.enabled or not codes or not text:
            return text
        return f"\x1b[{';'.join(codes)}m{text}\x1b[0m"

    def __getattr__(self, name: str):
        if name not in _CODES:
            raise AttributeError(name)
        return lambda text: self(text, name)


def want_colour(mode: str = "auto", stream=None) -> bool:
    """auto: only on a terminal, with NO_COLOR unset (https://no-color.org) and TERM != dumb."""
    if mode == "always":
        return True
    if mode == "never" or os.environ.get("NO_COLOR"):
        return False
    stream = stream if stream is not None else sys.stdout
    try:
        tty = stream.isatty()
    except Exception:
        tty = False
    return bool(tty) and os.environ.get("TERM", "") != "dumb"


def output_width(wide: bool = False, stream=None) -> int | None:
    """Columns available for tables: the terminal width on a terminal, $COLUMNS or 140 otherwise, None = no limit."""
    if wide:
        return None
    stream = stream if stream is not None else sys.stdout
    try:
        tty = stream.isatty()
    except Exception:
        tty = False
    if tty:
        return max(60, shutil.get_terminal_size((120, 24)).columns)
    try:
        return max(60, int(os.environ["COLUMNS"]))
    except (KeyError, ValueError):
        return 140


def wlen(s: str) -> int:
    """Number of terminal cells a string takes (wide CJK = 2, combining marks = 0)."""
    n = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        n += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return n


def one_line(s) -> str:
    """Collapse whitespace (newlines, tabs) so a value never breaks a table row."""
    return " ".join(str(s if s is not None else "").split())


def trunc(s, width: int | None) -> str:
    """Cut to `width` cells, ending with an ellipsis when something was removed."""
    s = one_line(s)
    if width is None or wlen(s) <= width:
        return s
    if width <= 1:
        return ELLIPSIS[:width]
    out, n = [], 0
    for ch in s:
        w = wlen(ch)
        if n + w > width - 1:
            break
        out.append(ch)
        n += w
    return "".join(out).rstrip() + ELLIPSIS


def pad(s: str, width: int, align: str = "l") -> str:
    gap = max(0, width - wlen(s))
    return " " * gap + s if align == "r" else s + " " * gap


def join_more(values, limit: int = 3, sep: str = ", ") -> str:
    """'a, b, c (+2)' — the first `limit` values and how many were left out."""
    values = [one_line(v) for v in values if v not in (None, "")]
    if len(values) <= limit:
        return sep.join(values)
    return sep.join(values[:limit]) + f" (+{len(values) - limit})"


def table(headers: list[str], rows: list[list], *, align: str = "", limits: dict[int, int] | None = None,
          flex: int | None = None, width: int | None = None, style: Style | None = None,
          styles: dict[int, tuple[str, ...]] | None = None, indent: int = 0) -> str:
    """Aligned text table.

    headers   column titles (printed bold when colour is on)
    rows      cells; anything is turned into one line of text. A cell may be `(text, "green", ...)` to style it.
    align     one letter per column: l (default) or r
    limits    column index -> maximum width; longer cells are truncated with an ellipsis
    flex      index of the free-text column (default: the last). When the table is wider than `width` it gives way
              first, down to 40 cells; then the other text columns, down to 16; then all of them, down to 12.
              Numbers are never cut, and 12 cells keep a material identifier whole.
    width     total width budget; None = unlimited
    styles    column index -> style names for every cell of that column
    """
    st = style or Style(False)
    limits = dict(limits or {})
    ncol = len(headers)
    cells: list[list[tuple[str, tuple]]] = []
    for r in rows:
        line = []
        for i in range(ncol):
            c = r[i] if i < len(r) else ""
            names: tuple = ()
            if isinstance(c, tuple):
                c, names = c[0], tuple(c[1:])
            elif styles and i in styles:
                names = tuple(styles[i])
            line.append((one_line("—" if c is None else c), names))
        cells.append(line)
    widths = [wlen(h) for h in headers]
    for line in cells:
        for i, (c, _) in enumerate(line):
            widths[i] = max(widths[i], wlen(c))
    for i, lim in limits.items():
        if i < ncol:
            widths[i] = max(wlen(headers[i]), min(widths[i], lim))
    al = [(align[i] if i < len(align) else "l") for i in range(ncol)]
    if width is not None and ncol:
        over = indent + sum(widths) + 2 * (ncol - 1) - width
        text = [i for i in range(ncol) if al[i] != "r"]
        target = flex if flex is not None else ncol - 1
        rest = [i for i in text if i != target]
        # Who gives way, and down to what width: the free-text column first, but it keeps room to stay readable;
        # then the other text columns; only then everything down to the minimum.
        for cols, floor in (([target], KEEP_FLEX), (rest, KEEP_TEXT), ([target], 2 * MIN_FLEX), (text, MIN_FLEX)):
            while over > 0:
                wide = [i for i in cols if widths[i] > max(floor, wlen(headers[i]))]
                if not wide:
                    break
                widths[max(wide, key=lambda i: widths[i])] -= 1
                over -= 1
    lead = " " * indent
    out = [lead + "  ".join(st(pad(h, widths[i], al[i]), "bold") if st.enabled else pad(h, widths[i], al[i])
                            for i, h in enumerate(headers)).rstrip()]
    for line in cells:
        parts = []
        for i, (c, names) in enumerate(line):
            c = pad(trunc(c, widths[i]), widths[i], al[i])
            parts.append(st(c, *names) if names else c)
        out.append((lead + "  ".join(parts)).rstrip())
    return "\n".join(out)


def kv(pairs: list[tuple[str, object]], *, style: Style | None = None, indent: int = 2, width: int | None = None) -> str:
    """'key:  value' lines with aligned values; pairs with an empty value are skipped. Long values are wrapped."""
    st = style or Style(False)
    pairs = [(k, one_line(v)) for k, v in pairs if v not in (None, "", [], {})]
    if not pairs:
        return ""
    kw = max(wlen(k) for k, _ in pairs) + 1
    out = []
    for k, v in pairs:
        head = " " * indent + pad(k + ":", kw) + " "
        room = (width - wlen(head)) if width else None
        chunks = textwrap.wrap(v, room, break_long_words=False, break_on_hyphens=False) if room and room >= 20 else [v]
        chunks = chunks or [""]
        out.append(" " * indent + st(pad(k + ":", kw), "dim") + " " + chunks[0])
        out += [" " * wlen(head) + c for c in chunks[1:]]
    return "\n".join(out)


def wrap(text: str, width: int | None, indent: int = 2) -> str:
    lead = " " * indent
    if not width:
        return lead + one_line(text)
    return "\n".join(textwrap.wrap(one_line(text), max(30, width), initial_indent=lead, subsequent_indent=lead,
                                   break_long_words=False, break_on_hyphens=False))


def bar(value: float, maximum: float, cells: int = 24) -> str:
    """Horizontal bar of `cells` width for a value in [0, maximum]."""
    if maximum <= 0 or value <= 0:
        return ""
    return "█" * max(1, round(cells * min(1.0, value / maximum)))


def num(x, digits: int = 2) -> str:
    """Fixed-point number, '—' for a missing value."""
    if x is None:
        return "—"
    return f"{float(x):.{digits}f}"
