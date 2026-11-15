# -*- coding: utf-8 -*-
"""Draws the Tag Aligner ribbon icons and the window header icon.

Run under CPython with Pillow:  python make_icons.py
Flat, square, drawn from each button's name, in the RevoBIM blue and orange.
Designed on a 32 unit grid, drawn at 8x and LANCZOS-downscaled so they stay
crisp as 16px small stack buttons. icon.png uses the darker light-ribbon
accents; icon.dark.png the brighter dark-ribbon ones.
"""
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
EXT = os.path.dirname(os.path.dirname(os.path.dirname(LIB)))
PANEL = os.path.join(EXT, "RevoBIM PY.tab", "Annotation.panel")

SS = 8          # supersample
GRID = 32
OUT = 96

PALETTES = {
    "light": {"blue": (27, 114, 190), "orange": (185, 106, 18),
              "tag": (27, 114, 190), "ink": (60, 60, 66)},
    "dark": {"blue": (79, 163, 227), "orange": (232, 145, 45),
             "tag": (79, 163, 227), "ink": (210, 210, 214)},
}


def canvas():
    img = Image.new("RGBA", (GRID * SS, GRID * SS), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def s(v):
    return int(round(v * SS))


def rect(d, x0, y0, x1, y1, fill, r=1.6):
    d.rounded_rectangle([s(x0), s(y0), s(x1), s(y1)], radius=s(r), fill=fill)


def line(d, pts, fill, w):
    d.line([(s(x), s(y)) for x, y in pts], fill=fill, width=s(w), joint="curve")
    for x, y in (pts[0], pts[-1]):
        d.ellipse([s(x - w / 2.0), s(y - w / 2.0), s(x + w / 2.0), s(y + w / 2.0)],
                  fill=fill)


def arrow_head(d, tip, direction, fill, size=4.6):
    x, y = tip
    if direction == "up":
        pts = [(x, y), (x - size, y + size), (x + size, y + size)]
    elif direction == "down":
        pts = [(x, y), (x - size, y - size), (x + size, y - size)]
    elif direction == "left":
        pts = [(x, y), (x + size, y - size), (x + size, y + size)]
    else:
        pts = [(x, y), (x - size, y - size), (x - size, y + size)]
    d.polygon([(s(a), s(b)) for a, b in pts], fill=fill)


def tag_bar(d, x0, y0, w, p, h=5.2):
    """A tag: a filled label bar with a small notch dot like a tag head."""
    rect(d, x0, y0, x0 + w, y0 + h, p["tag"], r=1.4)


# ==========================================================================
# The six drawings
# ==========================================================================

def align(d, p, side):
    widths = [20, 13, 17]
    ys = [4.5, 13.4, 22.3]
    if side == "left":
        gx = 5.0
        xs = [gx + 1.8] * 3
    elif side == "right":
        gx = 27.0
        xs = [gx - 1.8 - w for w in widths]
    else:
        gx = 16.0
        xs = [gx - w / 2.0 for w in widths]
    for x, y, w in zip(xs, ys, widths):
        tag_bar(d, x, y, w, p)
    line(d, [(gx, 2.0), (gx, 30.0)], p["orange"], 2.4)


def untangle_vertical(d, p):
    for y, w in ((3.0, 17), (13.4, 13), (23.8, 17)):
        tag_bar(d, 2.5, y, w, p)
    line(d, [(26.0, 6.8), (26.0, 25.2)], p["orange"], 2.4)
    arrow_head(d, (26.0, 2.0), "up", p["orange"])
    arrow_head(d, (26.0, 30.0), "down", p["orange"])


def untangle_horizontal(d, p):
    for x in (2.0, 12.2, 22.4):
        tag_bar(d, x, 5.0, 7.6, p, h=11.0)
    line(d, [(6.8, 25.0), (25.2, 25.0)], p["orange"], 2.4)
    arrow_head(d, (2.0, 25.0), "left", p["orange"])
    arrow_head(d, (30.0, 25.0), "right", p["orange"])


def settings(d, p):
    import math
    cx, cy, r_out, r_in = 16.0, 16.0, 13.0, 9.6
    pts = []
    teeth = 8
    for i in range(teeth * 4):
        a = (i / float(teeth * 4)) * 2 * math.pi
        r = r_out if (i % 4) in (0, 1) else r_in
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    d.polygon([(s(x), s(y)) for x, y in pts], fill=p["blue"])
    d.ellipse([s(cx - 8.0), s(cy - 8.0), s(cx + 8.0), s(cy + 8.0)], fill=p["blue"])
    d.ellipse([s(cx - 5.2), s(cy - 5.2), s(cx + 5.2), s(cy + 5.2)], fill=(0, 0, 0, 0))
    # small tag inside the gear, orange
    rect(d, cx - 3.6, cy - 1.8, cx + 3.6, cy + 1.8, p["orange"], r=0.9)


def header(d, p):
    """Window icon: tags aligned on a line with the untangle arrow."""
    for x, y, w in ((7.0, 4.5, 15), (7.0, 13.4, 10), (7.0, 22.3, 13)):
        tag_bar(d, x, y, w, p)
    line(d, [(4.4, 2.0), (4.4, 30.0)], p["orange"], 2.4)
    line(d, [(27.0, 7.0), (27.0, 25.0)], p["blue"], 2.0)
    arrow_head(d, (27.0, 2.6), "up", p["blue"], 4.0)
    arrow_head(d, (27.0, 29.4), "down", p["blue"], 4.0)


DRAWINGS = [
    ("Tag Align.stack", "Tag Align Left", lambda d, p: align(d, p, "left")),
    ("Tag Align.stack", "Tag Align Center", lambda d, p: align(d, p, "centre")),
    ("Tag Align.stack", "Tag Align Right", lambda d, p: align(d, p, "right")),
    ("Tag Untangle.stack", "Tag Untangle Vertical", untangle_vertical),
    ("Tag Untangle.stack", "Tag Untangle Horizontal", untangle_horizontal),
    ("Tag Untangle.stack", "Tag Aligner Settings", settings),
]


def render(draw_fn, palette, size=OUT):
    img, d = canvas()
    draw_fn(d, PALETTES[palette])
    return img.resize((size, size), Image.LANCZOS)


def main():
    written = []
    for stack, name, fn in DRAWINGS:
        folder = os.path.join(PANEL, stack, name + ".pushbutton")
        if not os.path.isdir(folder):
            sys.exit("missing button folder: " + folder)
        for palette, fname in (("light", "icon.png"), ("dark", "icon.dark.png")):
            path = os.path.join(folder, fname)
            render(fn, palette).save(path)
            written.append(path)
    render(header, "dark", 64).save(os.path.join(LIB, "tag_aligner_header.png"))
    written.append(os.path.join(LIB, "tag_aligner_header.png"))
    # contact sheet for review, not shipped
    sheet = Image.new("RGBA", (6 * 112 + 16, 2 * 112 + 16), (0, 0, 0, 0))
    bgs = [(243, 243, 245, 255), (35, 35, 38, 255)]
    for row, palette in enumerate(("light", "dark")):
        for col, (_, _, fn) in enumerate(DRAWINGS):
            tile = Image.new("RGBA", (104, 104), bgs[row])
            tile.alpha_composite(render(fn, palette), (4, 4))
            sheet.alpha_composite(tile, (8 + col * 112, 8 + row * 112))
    small = Image.new("RGBA", (6 * 24 + 8, 2 * 24 + 8), (0, 0, 0, 0))
    for row, palette in enumerate(("light", "dark")):
        for col, (_, _, fn) in enumerate(DRAWINGS):
            tile = Image.new("RGBA", (20, 20), bgs[row])
            tile.alpha_composite(render(fn, palette, 16), (2, 2))
            small.alpha_composite(tile, (4 + col * 24, 4 + row * 24))
    out = sys.argv[1] if len(sys.argv) > 1 else None
    if out:
        sheet.save(os.path.join(out, "icons_sheet.png"))
        small.resize((small.width * 4, small.height * 4), Image.NEAREST).save(
            os.path.join(out, "icons_16px_x4.png"))
    return written


if __name__ == "__main__":
    for p in main():
        print(p)
