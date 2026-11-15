# -*- coding: utf-8 -*-
"""RevoBIM PY - Wires: the icons.

Ships with the tool because it has been lost twice now to a reset working
folder, and redrawing an icon set from memory never quite matches.

    python make_icons.py

96 x 96 PNG, drawn at 8x and downsampled with LANCZOS. Flat, square, in the
house palette: blue for the primary form, orange for the secondary, green for
a create or confirm affordance, grey for "before".
"""

import math
import os

from PIL import Image, ImageDraw

S = 8
SIZE = 96
BIG = SIZE * S

BLUE = (79, 163, 227, 255)
ORANGE = (232, 145, 45, 255)
GREEN = (63, 167, 90, 255)
GREEN_HI = (78, 192, 109, 255)
GREY = (122, 122, 128, 255)
MUTED = (154, 154, 158, 255)
HOLE = (35, 35, 38, 255)
WHITE = (255, 255, 255, 255)


def canvas():
    image = Image.new('RGBA', (BIG, BIG), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def px(value):
    return int(round(value * S))


def polyline(draw, points, colour, width, dot_ends=False, radius=None):
    scaled = [(px(x), px(y)) for x, y in points]
    draw.line(scaled, fill=colour, width=px(width), joint='curve')
    node = px(radius if radius is not None else width / 2.0)
    for index, (x, y) in enumerate(scaled):
        if not dot_ends and index in (0, len(scaled) - 1):
            continue
        draw.ellipse([x - node, y - node, x + node, y + node], fill=colour)


def square(draw, cx, cy, half, colour, outline_only=False, width=3):
    box = [px(cx - half), px(cy - half), px(cx + half), px(cy + half)]
    if outline_only:
        draw.rectangle(box, outline=colour, width=px(width))
    else:
        draw.rectangle(box, fill=colour)


def disc(draw, cx, cy, radius, colour):
    draw.ellipse([px(cx - radius), px(cy - radius),
                  px(cx + radius), px(cy + radius)], fill=colour)


def ring(draw, cx, cy, radius, colour, width=3):
    draw.ellipse([px(cx - radius), px(cy - radius),
                  px(cx + radius), px(cy + radius)],
                 outline=colour, width=px(width))


def arc(draw, start, end, bulge, colour, width):
    """A three-point arc, drawn the way the tool draws a wire."""
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    ux, uy = dx / length, dy / length
    mx = (ax + bx) / 2.0 - uy * bulge
    my = (ay + by) / 2.0 + ux * bulge
    cx = 2 * mx - (ax + bx) / 2.0
    cy = 2 * my - (ay + by) / 2.0
    points = []
    for step in range(21):
        t = step / 20.0
        points.append((((1 - t) ** 2) * ax + 2 * (1 - t) * t * cx + (t ** 2) * bx,
                       ((1 - t) ** 2) * ay + 2 * (1 - t) * t * cy + (t ** 2) * by))
    draw.line([(px(x), px(y)) for x, y in points], fill=colour,
              width=px(width), joint='curve')


def save(image, path):
    image.resize((SIZE, SIZE), Image.LANCZOS).save(path, 'PNG')
    return path


# --- Wires, the pulldown ----------------------------------------------------
# A chamfered wire with a break in it, bridged by an orange node.
def icon_wires(path):
    image, draw = canvas()
    polyline(draw, [(12, 74), (32, 74), (42, 56)], BLUE, 8)
    polyline(draw, [(54, 34), (64, 16), (84, 16)], BLUE, 8)
    square(draw, 12, 74, 7, BLUE)
    square(draw, 84, 16, 7, BLUE)
    disc(draw, 48, 45, 13, ORANGE)
    disc(draw, 48, 45, 6, HOLE)
    return save(image, path)


# --- Auto Wire --------------------------------------------------------------
# Three lights chained by a shallow arc snake, dropping to an orange switch.
def icon_auto_wire(path):
    image, draw = canvas()
    lights = [(18, 24), (46, 19), (74, 26)]
    arc(draw, lights[0], lights[1], 4, GREEN_HI, 7)
    arc(draw, lights[1], lights[2], 4, GREEN_HI, 7)
    arc(draw, lights[2], (74, 62), 5, GREEN_HI, 7)
    for cx, cy in lights:
        square(draw, cx, cy, 8, BLUE)
    square(draw, 74, 76, 13, ORANGE)
    draw.rectangle([px(71), px(69), px(77), px(83)], fill=HOLE)
    return save(image, path)


# --- Re-Route Wires ---------------------------------------------------------
# The same chain, over the circular arrow that says "again, differently".
def icon_reroute(path):
    image, draw = canvas()
    lights = [(16, 22), (48, 16), (80, 24)]
    arc(draw, lights[0], lights[1], 4, BLUE, 7)
    arc(draw, lights[1], lights[2], 4, BLUE, 7)
    for cx, cy in lights:
        square(draw, cx, cy, 8, BLUE)
    draw.arc([px(28), px(44), px(68), px(84)], start=35, end=310,
             fill=ORANGE, width=px(8))
    draw.polygon([(px(62), px(40)), (px(76), px(52)), (px(58), px(56))],
                 fill=ORANGE)
    return save(image, path)


# --- Apply Wire Types -------------------------------------------------------
# Three wires, one of each type, and a tick: the tool picks a type, it does
# not draw anything.
def icon_apply_types(path):
    image, draw = canvas()
    for y, colour in ((24, BLUE), (48, ORANGE), (72, GREY)):
        polyline(draw, [(13, y), (52, y)], colour, 9)
        square(draw, 13, y, 6, colour)
    disc(draw, 71, 48, 18, GREEN)
    draw.line([(px(62), px(49)), (px(69), px(56)), (px(81), px(40))],
              fill=WHITE, width=px(6), joint='curve')
    return save(image, path)


# --- Align Wire Ends --------------------------------------------------------
# A wire arriving at a fitting, with the end node caught mid-nudge: a grey
# ghost where it was and a green node where it belongs.
def icon_align(path):
    image, draw = canvas()
    # a straight run in from the left, kept horizontal so it cannot be
    # mistaken for Reconnect's diagonal at ribbon size
    polyline(draw, [(8, 48), (44, 48)], BLUE, 9)
    square(draw, 9, 48, 7, BLUE)
    square(draw, 80, 48, 15, ORANGE)
    square(draw, 80, 48, 7, HOLE)
    disc(draw, 30, 48, 9, GREY)            # where the end sits now
    disc(draw, 60, 48, 11, GREEN)          # where it belongs
    draw.polygon([(px(44), px(40)), (px(58), px(48)), (px(44), px(56))],
                 fill=GREEN_HI)
    return save(image, path)


# --- Reconnect Wires --------------------------------------------------------
# The wire arrives and stops short; a green node closes the gap onto the
# orange fitting.
def icon_reconnect(path):
    image, draw = canvas()
    polyline(draw, [(10, 20), (36, 20), (48, 44)], BLUE, 10)
    square(draw, 11, 20, 8, BLUE)
    square(draw, 74, 74, 15, ORANGE)
    square(draw, 74, 74, 7, HOLE)
    polyline(draw, [(48, 44), (56, 60), (61, 74)], GREEN_HI, 10)
    disc(draw, 48, 44, 10, GREEN)
    return save(image, path)


# --- Settings ---------------------------------------------------------------
def icon_settings(path):
    image, draw = canvas()
    cx, cy = 48, 48
    teeth = 8
    outer, inner = 38, 27
    points = []
    for step in range(teeth * 2):
        angle = math.radians(step * (360.0 / (teeth * 2)) - 90 + 11)
        radius = outer if step % 2 == 0 else inner
        points.append((px(cx + radius * math.cos(angle)),
                       px(cy + radius * math.sin(angle))))
    draw.polygon(points, fill=BLUE)
    disc(draw, cx, cy, 18, HOLE)
    ring(draw, cx, cy, 13, ORANGE, 6)
    return save(image, path)


BASE = os.path.dirname(os.path.abspath(__file__))

ICONS = (
    (icon_wires, 'icon.png'),
    (icon_auto_wire, os.path.join('Auto Wire.pushbutton', 'icon.png')),
    (icon_reroute, os.path.join('Re-Route Wires.pushbutton', 'icon.png')),
    (icon_apply_types, os.path.join('Apply Wire Types.pushbutton', 'icon.png')),
    (icon_align, os.path.join('Align Wire Ends.pushbutton', 'icon.png')),
    (icon_reconnect, os.path.join('Reconnect Wires.pushbutton', 'icon.png')),
    (icon_settings, os.path.join('Settings.pushbutton', 'icon.png')),
)

if __name__ == '__main__':
    import sys
    for maker, relative in ICONS:
        sys.stdout.write(os.path.relpath(
            maker(os.path.join(BASE, relative)), BASE) + '\n')
