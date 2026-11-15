# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager : colour maths for the picker.

Hue, saturation and luminosity use the same 0-239 / 0-240 ranges Windows
and Revit's own colour dialog use, so the numbers in the boxes match what
the user sees in Revit.

Pure Python - no Revit, no WPF - so the bench can test it.
"""

HUE_MAX = 239.0
SAT_MAX = 240.0
LUM_MAX = 240.0


def clamp(value, low, high):
    return max(low, min(high, value))


def rgb_to_hsl(r, g, b):
    """(0-255, 0-255, 0-255) -> (hue 0-239, sat 0-240, lum 0-240)."""
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    high = max(rf, gf, bf)
    low = min(rf, gf, bf)
    lum = (high + low) / 2.0

    if high == low:
        return (0, 0, int(round(lum * LUM_MAX)))

    delta = high - low
    if lum < 0.5:
        sat = delta / (high + low)
    else:
        sat = delta / (2.0 - high - low)

    if high == rf:
        hue = (gf - bf) / delta
        if gf < bf:
            hue += 6.0
    elif high == gf:
        hue = 2.0 + (bf - rf) / delta
    else:
        hue = 4.0 + (rf - gf) / delta
    hue = hue / 6.0

    return (int(round(hue * HUE_MAX)),
            int(round(sat * SAT_MAX)),
            int(round(lum * LUM_MAX)))


def hsl_to_rgb(hue, sat, lum):
    """(hue 0-239, sat 0-240, lum 0-240) -> (0-255, 0-255, 0-255)."""
    h = clamp(float(hue), 0.0, HUE_MAX) / HUE_MAX
    s = clamp(float(sat), 0.0, SAT_MAX) / SAT_MAX
    l = clamp(float(lum), 0.0, LUM_MAX) / LUM_MAX

    if s == 0:
        v = int(round(l * 255))
        return (v, v, v)

    if l < 0.5:
        q = l * (1.0 + s)
    else:
        q = l + s - (l * s)
    p = 2.0 * l - q

    return (int(round(_channel(p, q, h + 1.0 / 3.0) * 255)),
            int(round(_channel(p, q, h) * 255)),
            int(round(_channel(p, q, h - 1.0 / 3.0) * 255)))


def _channel(p, q, t):
    if t < 0:
        t += 1.0
    if t > 1:
        t -= 1.0
    if t < 1.0 / 6.0:
        return p + (q - p) * 6.0 * t
    if t < 1.0 / 2.0:
        return q
    if t < 2.0 / 3.0:
        return p + (q - p) * (2.0 / 3.0 - t) * 6.0
    return p


def to_hex(rgb):
    return "{0:02X}{1:02X}{2:02X}".format(
        int(clamp(rgb[0], 0, 255)),
        int(clamp(rgb[1], 0, 255)),
        int(clamp(rgb[2], 0, 255)))


def from_hex(text):
    if text is None:
        return None
    s = str(text).strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except Exception:
        return None


# the 48 swatches Windows and Revit both open with
BASIC_COLOURS = [
    "FF8080", "FFFF80", "80FF80", "00FF80", "80FFFF", "0080FF", "FF80C0", "FF80FF",
    "FF0000", "FFFF00", "80FF00", "00FF40", "00FFFF", "0080C0", "8080C0", "FF00FF",
    "804040", "FF8040", "00FF00", "008080", "004080", "8080FF", "800040", "FF0080",
    "800000", "FF8000", "008000", "008040", "0000FF", "0000A0", "800080", "8000FF",
    "400000", "804000", "004000", "004040", "000080", "000040", "400040", "400080",
    "000000", "808000", "808040", "808080", "408080", "C0C0C0", "400040", "FFFFFF",
]
