# -*- coding: utf-8 -*-
"""Draws icon.png for Family Find & Replace.

Run with CPython and Pillow on the bench, not from Revit.  Drawn at 8x and
downscaled with LANCZOS so the curves stay clean at ribbon size.  Find is the
blue magnifier, replace is the orange swap arrows - the house palette, flat,
square, and drawn from the tool's own name.
"""

from PIL import Image, ImageDraw

SIZE = 96
SCALE = 8
S = SIZE * SCALE

BLUE = (79, 163, 227, 255)
ORANGE = (232, 145, 45, 255)


def round_line(draw, start, end, width, fill):
    draw.line([start, end], fill=fill, width=width)
    radius = width // 2
    for point in (start, end):
        draw.ellipse([point[0] - radius, point[1] - radius,
                      point[0] + radius, point[1] + radius], fill=fill)


def arrow(draw, tail, head, shaft, head_len, head_half, fill, pointing_right):
    y = tail[1]
    if pointing_right:
        shaft_end = head[0] - head_len
        draw.rectangle([tail[0], y - shaft // 2, shaft_end, y + shaft // 2],
                       fill=fill)
        draw.polygon([(head[0], y), (shaft_end, y - head_half),
                      (shaft_end, y + head_half)], fill=fill)
    else:
        shaft_end = head[0] + head_len
        draw.rectangle([shaft_end, y - shaft // 2, tail[0], y + shaft // 2],
                       fill=fill)
        draw.polygon([(head[0], y), (shaft_end, y - head_half),
                      (shaft_end, y + head_half)], fill=fill)


def build():
    image = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # find - the magnifier
    draw.ellipse([40, 40, 430, 430], outline=BLUE, width=64)
    round_line(draw, (375, 375), (500, 500), 86, BLUE)

    # replace - the swap arrows
    arrow(draw, (310, 600), (730, 600), 58, 85, 54, ORANGE, True)
    arrow(draw, (720, 700), (310, 700), 58, 85, 54, ORANGE, False)

    return image.resize((SIZE, SIZE), Image.LANCZOS)


if __name__ == '__main__':
    build().save('icon.png')
