# -*- coding: utf-8 -*-
"""Regenerates icon.png (and icon.dark.png) for Schematic Marriage.

Run under CPython with Pillow:  python make_icon.py
Two interlocked rings - the marriage - with a model element (blue pipe
section) in the left ring, a schematic valve symbol (orange) in the right,
and a green push arrow beneath. Drawn at 8x and downscaled with LANCZOS.
"""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE = 96
S = 8
BLUE = (79, 163, 227, 255)
BLUE_DARK = (27, 114, 190, 255)
ORANGE = (232, 145, 45, 255)
ORANGE_DARK = (185, 106, 18, 255)
GREEN = (63, 167, 90, 255)


def ring(d, cx, cy, r, w, colour):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=w)


def draw(blue, orange):
    big = SIZE * S
    img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = big / 96.0
    r = 25 * u
    w = int(7.5 * u)
    lx, rx, cy = 33 * u, 63 * u, 40 * u

    # left ring, then right ring, then re-draw the left ring's upper overlap
    # so the two read as interlocked rather than stacked
    ring(d, lx, cy, r, w, blue)
    ring(d, rx, cy, r, w, orange)
    layer = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    ring(ImageDraw.Draw(layer), lx, cy, r, w, blue)
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).rectangle([lx + r * 0.45, cy - r - w, rx, cy - 2 * u], fill=255)
    img.paste(layer, (0, 0), Image.composite(layer, Image.new('RGBA', (big, big)), mask).split()[3])

    # model element: pipe section in the left ring
    pw, ph = 18 * u, 10 * u
    d.rounded_rectangle([lx - pw / 2 - 3 * u, cy - ph / 2, lx + pw / 2 - 3 * u, cy + ph / 2],
                        radius=2.5 * u, fill=blue)
    d.rectangle([lx - pw / 2 - 3 * u, cy - ph / 2 - 2 * u, lx - pw / 2, cy + ph / 2 + 2 * u], fill=blue)

    # schematic valve (bow tie) in the right ring
    vx, vh, vw = rx + 3 * u, 9 * u, 9 * u
    d.polygon([(vx - vw, cy - vh), (vx, cy), (vx - vw, cy + vh)], outline=orange, fill=None, width=int(2.6 * u))
    d.polygon([(vx + vw, cy - vh), (vx, cy), (vx + vw, cy + vh)], outline=orange, fill=None, width=int(2.6 * u))

    # push arrow beneath
    ay = 82 * u
    d.line([(20 * u, ay), (70 * u, ay)], fill=GREEN, width=int(6.5 * u))
    d.polygon([(68 * u, ay - 9 * u), (80 * u, ay), (68 * u, ay + 9 * u)], fill=GREEN)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    draw(BLUE, ORANGE).save(os.path.join(HERE, 'icon.png'))
    draw(BLUE, ORANGE).save(os.path.join(HERE, 'icon.dark.png'))


if __name__ == '__main__':
    main()
