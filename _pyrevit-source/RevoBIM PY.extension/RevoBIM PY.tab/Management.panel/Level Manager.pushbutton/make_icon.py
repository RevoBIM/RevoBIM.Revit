# -*- coding: utf-8 -*-
"""Draws icon.png for Level Manager (CPython + Pillow, not run inside Revit).

Three level datums with Revit-style level heads in RevoBIM blue, an element
(orange) sitting between them, and a green arrow re-pointing its association
to the level above - the element stays where it is, only its link moves.
Drawn 8x oversize and downscaled with LANCZOS, like the other RevoBIM icons.
"""
import os
from PIL import Image, ImageDraw

BLUE = (79, 163, 227, 255)
ORANGE = (232, 145, 45, 255)
GREEN = (63, 167, 90, 255)
GREY = (154, 154, 158, 255)

SS = 8
SIZE = 96


def draw(size=SIZE):
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 96.0

    def line(x0, y0, x1, y1, colour, w):
        d.line([(x0 * u, y0 * u), (x1 * u, y1 * u)], fill=colour, width=int(w * u))

    def disc(cx, cy, r, colour):
        d.ellipse([(cx - r) * u, (cy - r) * u, (cx + r) * u, (cy + r) * u], fill=colour)

    def head(cx, cy):
        # Revit level head: circle split into quarters, two filled
        r = 9
        d.ellipse([(cx - r) * u, (cy - r) * u, (cx + r) * u, (cy + r) * u],
                  outline=BLUE, width=int(3 * u))
        d.pieslice([(cx - r) * u, (cy - r) * u, (cx + r) * u, (cy + r) * u], 180, 270, fill=BLUE)
        d.pieslice([(cx - r) * u, (cy - r) * u, (cx + r) * u, (cy + r) * u], 0, 90, fill=BLUE)

    levels = [20, 48, 76]
    for y in levels:
        # dash-dot datum line
        x = 6
        while x < 70:
            line(x, y, min(x + 12, 72), y, BLUE, 4)
            x += 16
            if x < 70:
                disc(x - 2, y, 1.8, BLUE)
            x += 2
        head(84, y)

    # the element: an orange box between the middle and top datums
    d.rounded_rectangle([18 * u, 31 * u, 38 * u, 44 * u], radius=int(3 * u), fill=ORANGE)
    # old association (grey, dashed) down to the middle datum
    for yy in range(45, 47, 2):
        line(28, yy, 28, yy + 1, GREY, 3)
    # new association: green arrow from the element up to the top datum
    line(48, 40, 48, 26, GREEN, 5)
    d.polygon([(41 * u, 28 * u), (55 * u, 28 * u), (48 * u, 20 * u)], fill=GREEN)
    line(38, 38, 48, 38, GREEN, 4)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    draw().save(os.path.join(here, "icon.png"))
    draw(256).save(os.path.join(here, "icon_preview.png"))
