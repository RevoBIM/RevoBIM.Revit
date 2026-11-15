# -*- coding: utf-8 -*-
"""Draws icon.png for Tag All.

Square, flat, drawn from the tool's own name: three tag labels leadering
back to one point - many things, one run. Blue for the stack, orange for the
front label (the one being placed), green tick for "all done". Rendered at
8x and downsampled with LANCZOS so the diagonals come out clean at 32px.

Run under CPython: python make_icon.py
"""
from PIL import Image, ImageDraw

SIZE = 96
SUPER = 8
S = SIZE * SUPER

BLUE = (79, 163, 227, 255)
BLUE_DIM = (79, 163, 227, 150)
ORANGE = (232, 145, 45, 255)
GREEN = (63, 167, 90, 255)
DARK = (28, 28, 31, 255)
CLEAR = (0, 0, 0, 0)


def u(value):
    return int(round(value * SUPER))


def tag_shape(x, y, width, height, notch):
    """A label: rectangle with the left edge drawn to a point, the way a tag
    leader meets its text."""
    return [(x + notch, y), (x + width, y), (x + width, y + height),
            (x + notch, y + height), (x, y + height / 2.0)]


def draw():
    image = Image.new("RGBA", (S, S), CLEAR)
    draw = ImageDraw.Draw(image)

    anchor = (u(17), u(50))

    # leaders, drawn first so the labels sit on top of them
    for target in ((u(46), u(24)), (u(46), u(50)), (u(46), u(74))):
        draw.line([anchor, target], fill=BLUE_DIM, width=u(2.4))
    draw.ellipse([anchor[0] - u(5), anchor[1] - u(5), anchor[0] + u(5), anchor[1] + u(5)],
                 fill=ORANGE)

    # the two labels behind, then the one in front
    for y, colour, fill in ((13, BLUE, False), (61, BLUE, False), (37, ORANGE, True)):
        points = tag_shape(u(40), u(y), u(44), u(22), u(9))
        if fill:
            draw.polygon(points, fill=colour)
        else:
            draw.polygon(points, outline=colour, width=u(3.2))

    # the tick in the front label: "all of them"
    draw.line([(u(54), u(48)), (u(61), u(55)), (u(74), u(40))], fill=DARK,
              width=u(5.4), joint="curve")

    # one text rule in each of the outline labels - two of them turn to mud
    # at 32px, which is the size the ribbon actually draws this at
    for y in (13, 61):
        draw.line([(u(54), u(y + 11)), (u(76), u(y + 11))], fill=BLUE_DIM, width=u(3.0))

    return image.resize((SIZE, SIZE), Image.LANCZOS)


if __name__ == "__main__":
    draw().save("icon.png")
    print("icon.png written")
