# -*- coding: utf-8 -*-
"""Tag Aligner core: the version, the settings and every alignment and
spacing rule. Nothing in here touches Revit or WPF, so all of it runs on the
bench under plain CPython.

Distances in this module are whatever unit the caller hands in (the model
module works in Revit feet). Text height is a PAPER measurement, multiplied by
the view scale before it reaches these functions.
"""
from __future__ import division

import codecs
import os
import time

__version__ = u"1.0.0"
TOOL_NAME = u"Tag Aligner"

MM_PER_FOOT = 304.8
EPS = 1e-6

# Bump SETTINGS_VERSION when a key changes meaning, and list that key under
# the new version here, or anyone with a saved file never sees the change.
SETTINGS_VERSION = 1
MIGRATIONS = {}

# ==========================================================================
# Settings
# ==========================================================================

DEFAULTS = [
    (u"theme", u"follow"),
    (u"align_reference", u"first"),
    (u"untangle_anchor", u"centre"),
    (u"text_height_source", u"auto"),
    (u"text_height_mm", u"2.5"),
    (u"v_mode", u"gap"),
    (u"v_gap", u"0.5"),
    (u"v_pitch", u"1.5"),
    (u"h_mode", u"gap"),
    (u"h_gap", u"0.5"),
    (u"h_pitch", u"1.5"),
    (u"move_elbows", u"1"),
    (u"pinned", u"skip"),
    (u"show_results", u"needed"),
    (u"debug", u"1"),
]

CHOICES = {
    u"theme": (u"follow", u"dark", u"light"),
    u"align_reference": (u"first", u"average", u"pick"),
    u"untangle_anchor": (u"centre", u"first"),
    u"text_height_source": (u"auto", u"fixed"),
    u"v_mode": (u"gap", u"pitch"),
    u"h_mode": (u"gap", u"pitch"),
    u"pinned": (u"skip", u"unpin"),
    u"show_results": (u"needed", u"always", u"never"),
}

# key: (lowest allowed, highest allowed)
FLOATS = {
    u"text_height_mm": (0.5, 20.0),
    u"v_gap": (0.0, 20.0),
    u"v_pitch": (0.5, 20.0),
    u"h_gap": (0.0, 20.0),
    u"h_pitch": (0.5, 20.0),
}

BOOLS = (u"move_elbows", u"debug")


def default_settings():
    return coerce_settings({})


def _to_float(text, key):
    lo, hi = FLOATS[key]
    try:
        v = float(u"{0}".format(text).strip().replace(u",", u"."))
    except Exception:
        return None
    if v < lo or v > hi:
        return None
    return v


def coerce_settings(raw, file_version=None):
    """Typed settings from a dict of strings, falling back key by key.

    Keys reset by a migration newer than the file's version take the default,
    whatever the file says. Unknown keys are ignored."""
    reset = set()
    if file_version is not None:
        for ver, keys in MIGRATIONS.items():
            if file_version < ver <= SETTINGS_VERSION:
                for k in keys:
                    reset.add(k)
    out = {}
    for key, default in DEFAULTS:
        text = raw.get(key, default)
        if key in reset:
            text = default
        if key in CHOICES:
            text = u"{0}".format(text).strip().lower()
            out[key] = text if text in CHOICES[key] else default
        elif key in FLOATS:
            v = _to_float(text, key)
            out[key] = v if v is not None else float(default)
        elif key in BOOLS:
            t = u"{0}".format(text).strip().lower()
            out[key] = t in (u"1", u"true", u"yes", u"on")
        else:
            out[key] = text
    return out


def parse_settings_text(text):
    """key=value lines, split on the FIRST '=' only."""
    raw = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(u"#") or u"=" not in line:
            continue
        key, value = line.split(u"=", 1)
        raw[key.strip()] = value.strip()
    return raw


def settings_text(values):
    lines = [u"# RevoBIM Tag Aligner settings",
             u"settings_version={0}".format(SETTINGS_VERSION)]
    for key, default in DEFAULTS:
        v = values.get(key, default)
        if key in BOOLS:
            v = u"1" if v else u"0"
        elif key in FLOATS:
            v = format_number(v)
        lines.append(u"{0}={1}".format(key, v))
    return u"\n".join(lines) + u"\n"


def appdata_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "RevoBIM")
    if not os.path.isdir(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return folder


def settings_path():
    return os.path.join(appdata_dir(), "tag_aligner.txt")


def debug_path():
    return os.path.join(appdata_dir(), "tag_aligner_debug.txt")


def error_path():
    return os.path.join(appdata_dir(), "tag_aligner_error.txt")


def read_text(path):
    with codecs.open(path, "r", "utf-8") as handle:
        return handle.read()


def write_text(path, text):
    with codecs.open(path, "w", "utf-8") as handle:
        handle.write(text)


def load_settings(path=None):
    path = path or settings_path()
    raw = {}
    file_version = None
    try:
        if os.path.isfile(path):
            raw = parse_settings_text(read_text(path))
            try:
                file_version = int(raw.get(u"settings_version", u"0"))
            except Exception:
                file_version = 0
    except Exception:
        raw = {}
    return coerce_settings(raw, file_version)


def save_settings(values, path=None):
    path = path or settings_path()
    write_text(path, settings_text(values))
    return path


def save_theme_only(mode, path=None):
    """The theme chip saves straight away without touching anything else."""
    values = load_settings(path)
    values[u"theme"] = mode if mode in CHOICES[u"theme"] else u"follow"
    return save_settings(values, path)


def format_number(v):
    text = u"{0:.3f}".format(float(v)).rstrip(u"0").rstrip(u".")
    return text if text else u"0"


# ==========================================================================
# Boxes and the rules
# ==========================================================================

class Box(object):
    """A tag's extent in the view's own axes: u along RightDirection,
    v along UpDirection. Measured with the leader switched off."""

    def __init__(self, key, umin, umax, vmin, vmax):
        self.key = key
        self.umin = umin
        self.umax = umax
        self.vmin = vmin
        self.vmax = vmax

    @property
    def width(self):
        return self.umax - self.umin

    @property
    def height(self):
        return self.vmax - self.vmin

    @property
    def uc(self):
        return (self.umin + self.umax) / 2.0

    @property
    def vc(self):
        return (self.vmin + self.vmax) / 2.0

    def shifted(self, du=0.0, dv=0.0):
        return Box(self.key, self.umin + du, self.umax + du,
                   self.vmin + dv, self.vmax + dv)

    def __repr__(self):
        return "Box({0}, u {1:.4f}..{2:.4f}, v {3:.4f}..{4:.4f})".format(
            self.key, self.umin, self.umax, self.vmin, self.vmax)


SIDES = (u"left", u"centre", u"right")
AXES = (u"vertical", u"horizontal")


def edge(box, side):
    if side == u"left":
        return box.umin
    if side == u"right":
        return box.umax
    if side == u"centre":
        return box.uc
    raise ValueError(u"unknown side {0}".format(side))


def align_target(boxes, side, reference, ref_box=None):
    """Where the chosen edge goes.

    first   - the first tag in the selection
    average - the mean of every tag's edge
    pick    - the clicked reference tag (falls back to first if none)"""
    if reference == u"pick" and ref_box is not None:
        return edge(ref_box, side)
    if reference == u"average":
        vals = [edge(b, side) for b in boxes]
        return sum(vals) / float(len(vals))
    return edge(boxes[0], side)


def align_deltas(boxes, side, reference, ref_box=None):
    """[(key, du)] in input order. Only the u coordinate ever changes."""
    if not boxes:
        return []
    target = align_target(boxes, side, reference, ref_box)
    return [(b.key, target - edge(b, side)) for b in boxes]


def _axis_parts(axis):
    if axis == u"vertical":
        return (lambda b: b.vc), (lambda b: b.height), -1.0
    if axis == u"horizontal":
        return (lambda b: b.uc), (lambda b: b.width), 1.0
    raise ValueError(u"unknown axis {0}".format(axis))


def untangle_order(boxes, axis):
    """Vertical: top to bottom (left to right on a tie).
    Horizontal: left to right (top to bottom on a tie)."""
    indexed = list(enumerate(boxes))
    if axis == u"vertical":
        indexed.sort(key=lambda p: (-round(p[1].vc, 9), round(p[1].uc, 9), p[0]))
    else:
        indexed.sort(key=lambda p: (round(p[1].uc, 9), -round(p[1].vc, 9), p[0]))
    return [b for _, b in indexed]


def untangle_step(size_a, size_b, text_height, mode, gap_factor, pitch_factor):
    """Centre to centre distance between two neighbouring tags.

    gap   - each tag's own size plus a clear gap of text height x gap_factor.
            The default 0.5 gives single line tags 'text height + text
            height / 2' centre to centre, and multi line or wide tags never
            touch.
    pitch - a fixed text height x pitch_factor centre to centre (default 1.5,
            'text height / 2 + text height'), but never closer than the two
            tags' half sizes, so an untangle cannot make an overlap."""
    half_sum = (size_a + size_b) / 2.0
    if mode == u"pitch":
        return max(text_height * pitch_factor, half_sum)
    return half_sum + text_height * gap_factor


def untangle_deltas(boxes, axis, text_height, mode, gap_factor,
                    pitch_factor, anchor):
    """[(key, delta along the axis)], plus the order used.

    anchor centre - the stack is centred on where the tags were, so the
                    group moves as little as possible
    anchor first  - the top tag (vertical) or left tag (horizontal) stays put
    """
    if not boxes:
        return [], []
    pos, size, direction = _axis_parts(axis)
    order = untangle_order(boxes, axis)
    new_pos = [pos(order[0])]
    for prev, cur in zip(order, order[1:]):
        step = untangle_step(size(prev), size(cur), text_height, mode,
                             gap_factor, pitch_factor)
        new_pos.append(new_pos[-1] + direction * step)
    shift = 0.0
    if anchor == u"centre":
        old_mean = sum(pos(b) for b in order) / float(len(order))
        new_mean = sum(new_pos) / float(len(new_pos))
        shift = old_mean - new_mean
    moves = {}
    for b, p in zip(order, new_pos):
        moves[b.key] = (p + shift) - pos(b)
    return [(b.key, moves[b.key]) for b in boxes], [b.key for b in order]


def expected_coordinate(box, kind, which):
    """The coordinate a run promised to set: an edge for align, a centre for
    untangle."""
    if kind == u"align":
        return edge(box, which)
    if which == u"vertical":
        return box.vc
    return box.uc


def drift(before, after, kind, which, delta):
    """(along, across) error of a measured move, both positive numbers.

    along  - how far the promised coordinate missed
    across - how far the tag wandered on the axis it should not have moved"""
    along = abs(expected_coordinate(after, kind, which) -
                (expected_coordinate(before, kind, which) + delta))
    if kind == u"untangle" and which == u"vertical":
        across = abs(after.uc - before.uc)
    else:
        across = abs(after.vc - before.vc)
    return along, across


def paper_to_model(paper_feet, scale):
    return paper_feet * max(int(scale or 1), 1)


def tolerance(scale):
    """0.25mm on paper, in model feet."""
    return paper_to_model(0.25 / MM_PER_FOOT, scale)


def spacing_preview(text_height_mm, mode, gap_factor, pitch_factor, scale):
    """One line for the settings window. Single line tags assumed, so a gap
    is shown as text height plus the gap."""
    if mode == u"pitch":
        paper = text_height_mm * pitch_factor
        label = u"pitch"
    else:
        paper = text_height_mm + text_height_mm * gap_factor
        label = u"pitch"
    return u"1:{0}  {1} {2} mm on paper = {3} mm in the model".format(
        scale, label, format_number(paper), format_number(paper * scale))


# ==========================================================================
# Report and debug log
# ==========================================================================

class Report(object):
    OK = u"ok"
    WARN = u"warn"
    ERROR = u"error"

    def __init__(self, title):
        self.title = title
        self.summary = u""
        self.lines = []
        self.moved = 0
        self.cancelled = False

    def ok(self, text):
        self.lines.append((self.OK, text))

    def warn(self, text):
        self.lines.append((self.WARN, text))

    def error(self, text):
        self.lines.append((self.ERROR, text))

    @property
    def needs_look(self):
        return any(level != self.OK for level, _ in self.lines)

    def should_show(self, show_results):
        if self.cancelled or show_results == u"never":
            return False
        if show_results == u"always":
            return True
        return self.needs_look


class DebugLog(object):
    def __init__(self, enabled, path=None):
        self.enabled = enabled
        self.path = path or debug_path()
        self.lines = [u"RevoBIM Tag Aligner {0}  {1}".format(
            __version__, time.strftime("%Y-%m-%d %H:%M:%S"))]

    def add(self, text):
        self.lines.append(u"{0}".format(text))

    def write(self):
        if not self.enabled:
            return None
        try:
            write_text(self.path, u"\n".join(self.lines) + u"\n")
            return self.path
        except Exception:
            return None
