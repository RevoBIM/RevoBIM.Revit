# -*- coding: utf-8 -*-
"""Regenerates icon.png, partial.png and full.png (CPython + Pillow).

Flat, square, RevoBIM palette, 8x supersampled and LANCZOS downscaled.
  icon.png     stacked import symbols bursting apart (the tool)
  partial.png  one import symbol splitting into four smaller symbols
  full.png     an import symbol breaking into loose lines and an arc
"""
import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SS = 8
BLUE = (79, 163, 227, 255)
BLUE_D = (27, 114, 190, 255)
ORANGE = (232, 145, 45, 255)
GREY = (154, 154, 158, 255)
SHEET = (43, 43, 46, 255)
WHITE = (228, 228, 228, 255)


def canvas(px):
    img = Image.new('RGBA', (px * SS, px * SS), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img), float(px * SS) / 100.0


def finish(img, px, name):
    img.resize((px, px), Image.LANCZOS).save(os.path.join(HERE, name))


def dashed_rect(d, box, colour, w, dash, gap):
    x0, y0, x1, y1 = box
    for (ax, ay, bx, by) in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
        length = math.hypot(bx - ax, by - ay)
        ux, uy = (bx - ax) / length, (by - ay) / length
        t = 0.0
        while t < length:
            e = min(t + dash, length)
            d.line((ax + ux * t, ay + uy * t, ax + ux * e, ay + uy * e), fill=colour, width=int(w))
            t += dash + gap


def symbol(d, u, cx, cy, size, frame, line, dashed=True):
    """An import symbol: dashed selection frame round a small CAD drawing."""
    h = size / 2.0
    box = (u * (cx - h), u * (cy - h), u * (cx + h), u * (cy + h))
    d.rectangle(box, fill=SHEET)
    if dashed:
        dashed_rect(d, box, frame, u * 2.4, u * 5, u * 3)
    else:
        d.rectangle(box, outline=frame, width=int(u * 2.4))
    s = size * 0.28
    d.line((u * (cx - s), u * (cy + s), u * (cx + s), u * (cy + s)), fill=line, width=int(u * 2.6))
    d.line((u * (cx - s), u * (cy + s), u * (cx - s), u * (cy - s)), fill=line, width=int(u * 2.6))
    d.ellipse((u * (cx - s * 0.1), u * (cy - s), u * (cx + s), u * (cy - s * 0.1 + s * 0.1)),
              outline=line, width=int(u * 2.6))


def arrow(d, u, x0, y0, x1, y1, colour, w):
    d.line((u * x0, u * y0, u * x1, u * y1), fill=colour, width=int(u * w))
    ang = math.atan2(y1 - y0, x1 - x0)
    head = max(6.0, w * 1.9)
    pts = [(x1, y1),
           (x1 - head * math.cos(ang - 0.5), y1 - head * math.sin(ang - 0.5)),
           (x1 - head * math.cos(ang + 0.5), y1 - head * math.sin(ang + 0.5))]
    d.polygon([(u * x, u * y) for x, y in pts], fill=colour)


def tool_icon(px=96):
    img, d, u = canvas(px)
    symbol(d, u, 40, 40, 44, GREY, GREY)          # back sheet
    symbol(d, u, 48, 48, 44, BLUE_D, GREY)        # middle sheet
    symbol(d, u, 56, 56, 44, BLUE, WHITE)         # front sheet
    for (x0, y0, x1, y1) in ((80, 34, 92, 22), (80, 80, 92, 92), (34, 80, 22, 92)):
        arrow(d, u, x0, y0, x1, y1, ORANGE, 5)
    finish(img, px, 'icon.png')


def partial_icon(px=128):
    img, d, u = canvas(px)
    # faint outline of where the single symbol was
    dashed_rect(d, (u * 30, u * 30, u * 70, u * 70), GREY, u * 1.6, u * 3, u * 3)
    for cx, cy in ((24, 24), (76, 24), (24, 76), (76, 76)):
        symbol(d, u, cx, cy, 34, BLUE, WHITE)
    for (x0, y0, x1, y1) in ((44, 44, 38, 38), (56, 44, 62, 38), (44, 56, 38, 62), (56, 56, 62, 62)):
        arrow(d, u, (x0 + 50) / 2.0, (y0 + 50) / 2.0, x1, y1, ORANGE, 3.5)
    finish(img, px, 'partial.png')


def full_icon(px=128):
    img, d, u = canvas(px)
    dashed_rect(d, (u * 30, u * 30, u * 70, u * 70), GREY, u * 1.6, u * 3, u * 3)
    w = int(u * 5)
    # the symbol's own linework, broken into loose pieces flying apart
    d.line((u * 14, u * 86, u * 40, u * 86), fill=BLUE, width=w)            # base of the L
    d.line((u * 10, u * 74, u * 10, u * 44), fill=BLUE, width=w)            # upright of the L
    d.line((u * 52, u * 92, u * 74, u * 92), fill=ORANGE, width=w)          # loose line
    d.arc((u * 54, u * 8, u * 90, u * 44), 180, 300, fill=BLUE, width=w)    # circle, split
    d.arc((u * 62, u * 14, u * 98, u * 50), 330, 90, fill=ORANGE, width=w)
    d.line((u * 22, u * 12, u * 44, u * 22), fill=ORANGE, width=w)          # loose line
    # motion ticks from the centre
    for (x0, y0, x1, y1) in ((47, 53, 35, 65), (53, 47, 65, 35), (53, 53, 65, 65), (47, 47, 35, 35)):
        arrow(d, u, x0, y0, x1, y1, GREY, 3.5)
    finish(img, px, 'full.png')


if __name__ == '__main__':
    tool_icon()
    partial_icon()
    full_icon()
