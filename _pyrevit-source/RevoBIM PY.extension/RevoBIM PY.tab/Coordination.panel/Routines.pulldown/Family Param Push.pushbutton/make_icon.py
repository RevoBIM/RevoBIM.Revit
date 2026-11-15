# -*- coding: utf-8 -*-
"""Draws icon.png: a family block pushing a value across to a parameter list.
Run under CPython with Pillow. 8x supersampled, LANCZOS down."""
import os
from PIL import Image, ImageDraw

SIZE, SCALE = 96, 8
BLUE, ORANGE, GREEN = (79, 163, 227, 255), (232, 145, 45, 255), (63, 167, 90, 255)


def main():
    px = SIZE * SCALE
    img = Image.new('RGBA', (px, px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    def s(*values):
        return [v * SCALE for v in values]
    draw.rounded_rectangle(s(5, 18, 39, 78), radius=5 * SCALE, fill=BLUE)
    for y in (29, 45, 61):
        draw.rounded_rectangle(s(12, y, 32, y + 7), radius=2 * SCALE,
                               fill=(255, 255, 255, 235))
    draw.rounded_rectangle(s(57, 18, 91, 78), radius=5 * SCALE, fill=GREEN)
    for y in (29, 45, 61):
        draw.rounded_rectangle(s(64, y, 84, y + 7), radius=2 * SCALE,
                               fill=(255, 255, 255, 235))
    draw.rectangle(s(30, 42, 54, 54), fill=ORANGE)
    draw.polygon(s(50, 31, 68, 48, 50, 65), fill=ORANGE)
    out = img.resize((SIZE, SIZE), Image.LANCZOS)
    out.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon.png'))


if __name__ == '__main__':
    main()
