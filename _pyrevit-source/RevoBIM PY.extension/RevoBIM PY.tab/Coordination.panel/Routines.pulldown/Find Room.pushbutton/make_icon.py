# -*- coding: utf-8 -*-
"""Draws icon.png for Find Room (CPython + Pillow, run on the bench).

A room on plan - walls in blue with a door gap, the room filled orange (the
temporary colour fill) - and a magnifying glass over its corner finding it.
Flat, square, 8x supersampled, LANCZOS down to 96 px.
"""
import os
from PIL import Image, ImageDraw

S = 8
N = 96
BLUE = (79, 163, 227, 255)
ORANGE = (232, 145, 45, 255)
ORANGE_FILL = (232, 145, 45, 200)
DARK = (35, 35, 38, 255)
WHITE = (255, 255, 255, 255)


def draw(path):
    W = N * S
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def r(v):
        return int(round(v * S))

    # tile
    d.rounded_rectangle([r(2), r(2), r(94), r(94)], radius=r(14), fill=DARK)

    # the room: orange fill inside blue walls, door gap bottom left
    d.rectangle([r(16), r(18), r(66), r(64)], fill=ORANGE_FILL)
    wall = r(6)
    d.line([(r(13), r(15)), (r(69), r(15))], fill=BLUE, width=wall)      # top
    d.line([(r(13), r(15)), (r(13), r(67))], fill=BLUE, width=wall)      # left
    d.line([(r(69), r(15)), (r(69), r(40))], fill=BLUE, width=wall)      # right, part
    d.line([(r(36), r(67)), (r(69), r(67))], fill=BLUE, width=wall)      # bottom, door gap
    d.line([(r(13), r(67)), (r(19), r(67))], fill=BLUE, width=wall)
    # door swing
    d.arc([r(19 - 17), r(67 - 17), r(19 + 17), r(67 + 17)], start=270, end=360,
          fill=BLUE, width=r(2))
    # room reference cross
    d.line([(r(33), r(41)), (r(49), r(41))], fill=WHITE, width=r(2.4))
    d.line([(r(41), r(33)), (r(41), r(49))], fill=WHITE, width=r(2.4))

    # magnifier
    cx, cy, rad = 63, 59, 16
    d.ellipse([r(cx - rad), r(cy - rad), r(cx + rad), r(cy + rad)], fill=DARK)
    d.ellipse([r(cx - rad + 3), r(cy - rad + 3), r(cx + rad - 3), r(cy + rad - 3)],
              outline=ORANGE, width=r(5))
    d.line([(r(cx + 10), r(cy + 10)), (r(86), r(84))], fill=ORANGE, width=r(8))
    d.ellipse([r(86 - 4), r(84 - 4), r(86 + 4), r(84 + 4)], fill=ORANGE)

    img = img.resize((N, N), Image.LANCZOS)
    img.save(path)


if __name__ == "__main__":
    draw(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png"))
