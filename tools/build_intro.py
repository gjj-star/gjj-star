#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the typewriter intro SVG used by the GitHub profile README.

Why it is written this way
--------------------------
GitHub renders a README image inside ``<img>``, which puts the SVG in "secure
static mode": no JavaScript runs, and no external resource (font, image,
stylesheet) is ever fetched. The animation therefore has to be baked into the
file, and the only fonts available are the ones the visitor already has.

That last point is why every character gets its own ``<text>`` node sitting on a
monospace grid instead of one text run per line: the caret then lands exactly on
the cell of the next character no matter which font the visitor ends up with,
and nothing drifts as a line grows.

Two animation mechanisms are used, each where it is reliable:

* the character reveal and the resting cursor are CSS animations that have
  already finished by the time they are seen (a 1 ms keyframe with a delay and
  ``animation-fill-mode: both``), so every frame is a computed end state rather
  than something sampled mid-flight;
* the cursor that follows the typing uses SMIL, which only moves it - if SMIL
  is ignored the cursor is simply absent while the text types, and the resting
  cursor still arrives and blinks.

``profile.json`` is the single source of truth and is typed out verbatim, syntax
highlighted.

Usage
-----
    python tools/build_intro.py                            # build both themes
    python tools/build_intro.py --frame 2500 --out f.svg   # snapshot at 2500 ms

``--frame`` draws the state at that instant from the schedule alone, without any
animation, which is handy for checking the layout.
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "profile.json"
ASSETS_DIR = ROOT / "assets"

# The shell line typed before the JSON. Set to "" to type the JSON only.
PROMPT = "$ cat profile.json"

# ---------------------------------------------------------------- timing (ms)
START_MS = 700        # beat before the first character lands
CHAR_MS = 18          # per character
LINE_PAUSE_MS = 130   # extra pause at the end of every line
BLINK_MS = 1000       # cursor blink period once typing has stopped

# ------------------------------------------------------------- geometry (px)
FONT_SIZE = 15
ADVANCE = FONT_SIZE * 0.6   # advance of a monospace glyph, 0.6em
LINE_H = 24
PAD_X = 32
PAD_TOP = 28
PAD_BOTTOM = 26
RADIUS = 14
BASELINE_IN_LINE = 17.2     # from the top of the line box to the text baseline
CARET_W = ADVANCE - 1
CARET_H = FONT_SIZE * 1.12

FONT_STACK = (
    "ui-monospace, SFMono-Regular, Menlo, Consolas, 'DejaVu Sans Mono', "
    "'Liberation Mono', 'PingFang SC', 'Microsoft YaHei', monospace"
)

THEMES = {
    "dark": {
        "bg": "#050208",
        "border": "#241d2e",
        "prompt": "#ff9e44",
        "cmd": "#5b5470",
        "punct": "#6b6580",
        "key": "#ff9e44",
        "string": "#d7d2e2",
        "literal": "#8fd6a8",
        "caret": "#ff9e44",
        "title": "oii-neo profile intro (dark)",
    },
    "light": {
        "bg": "#ffffff",
        "border": "#e4ded6",
        "prompt": "#e8590c",
        "cmd": "#9c948a",
        "punct": "#9aa0a6",
        "key": "#c2410c",
        "string": "#1f2328",
        "literal": "#1a7f37",
        "caret": "#e8590c",
        "title": "oii-neo profile intro (light)",
    },
}


def cells(ch: str) -> int:
    """Monospace cells taken by one character (CJK and friends take two)."""
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def write_lf(path: Path, text: str) -> None:
    """Write UTF-8 with LF endings.

    Python translates newlines on Windows, which would make the committed SVG
    differ from the one the Linux CI runner generates and turn every scheduled
    rebuild into a spurious commit.
    """
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def colorize_json(text: str) -> list[tuple[str, str]]:
    """Split JSON into (char, kind) pairs; kind is one of the theme keys."""
    out: list[tuple[str, str]] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            k = j + 1
            while k < n and text[k] in " \t":
                k += 1
            kind = "key" if k < n and text[k] == ":" else "string"
            out.extend((c, kind) for c in text[i : j + 1])
            i = j + 1
        elif ch == "\n":
            out.append((ch, "\n"))
            i += 1
        elif ch in " \t":
            out.append((ch, "punct"))  # indentation; kept dim
            i += 1
        elif ch in "{}[],:":
            out.append((ch, "punct"))
            i += 1
        else:
            j = i
            while j < n and text[j] not in ' \t\n,}]':
                j += 1
            out.extend((c, "literal") for c in text[i:j])
            i = j
    return out


def build_document() -> list[tuple[str, str]]:
    data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    body = json.dumps(data, indent=2, ensure_ascii=False)
    doc: list[tuple[str, str]] = []
    if PROMPT:
        head, _, tail = PROMPT.partition(" ")
        doc.append((head, "prompt"))
        doc.extend((c, "cmd") for c in (" " + tail if tail else ""))
        doc.append(("\n", "\n"))
        doc.append(("\n", "\n"))  # blank line between the command and the JSON
    doc.extend(colorize_json(body))
    return doc


def layout(doc: list[tuple[str, str]]):
    """Place every character on the grid and give it a time.

    Returns the glyphs (each with its start time), the path the cursor walks
    (one entry per glyph plus the resting position after the last one), the box
    size and the moment typing ends.
    """
    glyphs = []      # (char, kind, x, baseline, start_ms)
    caret_path = []  # (x, y) the cursor occupies once glyph k has landed
    line = col = 0
    t = float(START_MS)
    max_col = 0
    for ch, kind in doc:
        if ch == "\n":
            max_col = max(max_col, col)
            line += 1
            col = 0
            t += LINE_PAUSE_MS
            continue
        box_top = PAD_TOP + line * LINE_H
        glyphs.append((ch, kind, PAD_X + col * ADVANCE,
                       box_top + BASELINE_IN_LINE, t))
        caret_path.append((PAD_X + col * ADVANCE,
                           box_top + (LINE_H - CARET_H) / 2))
        col += cells(ch)
        t += CHAR_MS
    max_col = max(max_col, col)
    end_ms = glyphs[-1][4]                      # the last character lands here
    caret_path.append((PAD_X + col * ADVANCE,   # where the cursor comes to rest
                       PAD_TOP + line * LINE_H + (LINE_H - CARET_H) / 2))
    width = PAD_X * 2 + max_col * ADVANCE
    height = PAD_TOP + PAD_BOTTOM + (line + 1) * LINE_H
    return glyphs, caret_path, width, height, end_ms


def caret_at(glyphs, caret_path, at_ms: float):
    """Where the cursor sits at ``at_ms`` (mirrors the SMIL schedule)."""
    k = 0
    for idx, g in enumerate(glyphs):
        if g[4] <= at_ms:
            k = idx + 1
    return caret_path[min(k, len(caret_path) - 1)]


def render(theme: dict, frame_ms: float | None = None,
           caret_color: str | None = None) -> str:
    doc = build_document()
    glyphs, caret_path, width, height, end_ms = layout(doc)
    walk_ms = end_ms - START_MS
    caret0 = caret_path[0]
    caret_fill = caret_color or theme["caret"]

    css = [
        f".t{{font-family:{FONT_STACK};font-size:{FONT_SIZE}px;white-space:pre}}",
        ".c{opacity:0;animation-name:ink;animation-duration:1ms;"
        "animation-timing-function:linear;animation-fill-mode:both}",
        "@keyframes ink{from{opacity:0}to{opacity:1}}",
        # the resting cursor appears the moment typing stops, then blinks
        f".rest{{opacity:0;animation-name:show,blink;"
        f"animation-duration:1ms,{BLINK_MS}ms;"
        f"animation-delay:{end_ms:.1f}ms,{end_ms:.1f}ms;"
        "animation-timing-function:linear,linear;"
        "animation-iteration-count:1,infinite;"
        "animation-fill-mode:both,none}",
        "@keyframes show{from{opacity:0}to{opacity:1}}",
        "@keyframes blink{0%,49.99%{opacity:1}50%,100%{opacity:0}}",
        # a reduced-motion visitor gets finished text and a steady cursor
        "@media (prefers-reduced-motion:reduce){.c{opacity:1;animation:none}"
        ".walk{display:none}.rest{opacity:1;animation:none}}",
    ]

    parts = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width:.0f}' "
        f"height='{height:.0f}' viewBox='0 0 {width:.0f} {height:.0f}' "
        "role='img' aria-labelledby='t'>",
        f"<title id='t'>{escape(theme['title'])}</title>",
        "<style>" + "".join(css) + "</style>",
        f"<rect x='0.5' y='0.5' width='{width - 1:.0f}' height='{height - 1:.0f}' "
        f"rx='{RADIUS}' fill='{theme['bg']}' stroke='{theme['border']}'/>",
    ]

    if frame_ms is not None:
        # the same instant, written out by hand: no animation anywhere
        for ch, kind, x, baseline, t in glyphs:
            if ch == " " or t > frame_ms:
                continue
            parts.append(
                f"<text class='t' fill='{theme[kind]}' x='{x:.2f}' "
                f"y='{baseline:.2f}'>{escape(ch)}</text>"
            )
        cx, cy = caret_at(glyphs, caret_path, frame_ms)
        parts.append(
            f"<rect x='{cx:.2f}' y='{cy:.2f}' width='{CARET_W:.1f}' "
            f"height='{CARET_H:.1f}' fill='{caret_fill}'/>"
        )
        parts.append("</svg>")
        return "\n".join(parts) + "\n"

    for ch, kind, x, baseline, t in glyphs:
        if ch == " ":
            continue
        parts.append(
            f"<text class='t c' style='animation-delay:{t:.1f}ms' "
            f"fill='{theme[kind]}' x='{x:.2f}' y='{baseline:.2f}'>{escape(ch)}</text>"
        )

    # The cursor that follows the typing runs on SMIL: only its position moves,
    # and a renderer that ignores SMIL simply shows no travelling cursor - the
    # text still types, and the resting cursor below still arrives. Its base
    # opacity is 0, so it leaves nothing behind once the walk is over.
    key_times = ";".join(
        f"{(glyphs[k - 1][4] - START_MS) / walk_ms:.5f}"
        for k in range(1, len(glyphs) + 1)
    )
    xs = ";".join(f"{caret_path[k][0]:.1f}" for k in range(1, len(caret_path)))
    ys = ";".join(f"{caret_path[k][1]:.1f}" for k in range(1, len(caret_path)))
    parts.append(
        f"<rect class='walk' x='{caret0[0]:.2f}' y='{caret0[1]:.2f}' "
        f"width='{CARET_W:.1f}' height='{CARET_H:.1f}' fill='{caret_fill}' "
        "opacity='0'>"
        f"<animate attributeName='opacity' begin='0ms' dur='{end_ms:.1f}ms' "
        "values='1'/>"
        f"<animate attributeName='x' calcMode='discrete' begin='{START_MS}ms' "
        f"dur='{walk_ms:.1f}ms' fill='freeze' keyTimes='{key_times}' "
        f"values='{xs}'/>"
        f"<animate attributeName='y' calcMode='discrete' begin='{START_MS}ms' "
        f"dur='{walk_ms:.1f}ms' fill='freeze' keyTimes='{key_times}' "
        f"values='{ys}'/>"
        "</rect>"
    )
    # The cursor that waits at the end of the last line and blinks there.
    rest_x, rest_y = caret_path[-1]
    parts.append(
        f"<rect class='rest' x='{rest_x:.2f}' y='{rest_y:.2f}' "
        f"width='{CARET_W:.1f}' height='{CARET_H:.1f}' fill='{caret_fill}'/>"
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--theme", choices=sorted(THEMES), help="theme for a single file")
    ap.add_argument("--out", type=Path, help="write one file here instead of assets/")
    ap.add_argument("--frame", type=float, metavar="MS",
                    help="draw the state at MS without any animation")
    ap.add_argument("--caret-color", metavar="HEX",
                    help="paint the cursor in this colour (for checking renders)")
    args = ap.parse_args()

    if args.out:
        svg = render(THEMES[args.theme or "dark"], args.frame, args.caret_color)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_lf(args.out, svg)
        print(f"wrote {args.out}  ({len(svg.encode('utf-8')):,} bytes)")
        return

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for name, theme in THEMES.items():
        out = ASSETS_DIR / f"intro-{name}.svg"
        svg = render(theme)
        write_lf(out, svg)
        print(f"wrote {out.relative_to(ROOT)}  ({len(svg.encode('utf-8')):,} bytes)")


if __name__ == "__main__":
    main()
