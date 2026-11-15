# -*- coding: utf-8 -*-
u"""RevoBIM Addins - version, settings, paths, debug log, text helpers.

No WPF and no Revit API in this module, so every rule in it can be tested
under plain CPython by bench_logic.py.
"""

import rba_clr  # noqa: F401  - assembly references must win the import race

import os
import re
import sys

__version__ = u"1.5.2"

TOOL_NAME = u"RevoBIM Addin Manager"
# The settings and log file names keep the pre-rename spelling on purpose:
# a missing settings file falls back to the defaults without complaining, so
# renaming it would quietly throw everybody's settings away and look exactly
# like the tool forgetting everything for no stated reason.
SETTINGS_NAME = u"revobim_addins.txt"
DEBUG_NAME = u"revobim_addins_debug.txt"

# The dockable pane GUID. Fixed for the life of the tool - Revit keys the
# user's docking position and visibility off it, so changing it throws away
# everybody's layout and orphans the old pane.
PANE_GUID = u"6D1F3C24-8B57-4A19-9C73-2E5A0B8F41D6"

SETTINGS_VERSION = 2

# Between the parts of an addin's key. Never "|" - see LIST_SEP.
KEY_SEP = u"::"
# Between the entries of a saved list. Folder paths cannot contain it, which is
# why it was chosen - and why nothing stored IN a list may contain it either.
LIST_SEP = u"|"

DEFAULTS = {
    u"settings_version": u"1",
    u"folders": u"",            # blank = auto-detect pyRevit extension roots
    u"theme": u"auto",          # auto | dark | light
    u"icon_size": u"32",        # 16 | 24 | 32 | 48 | 64
    u"dock": u"left",           # left | right | floating - pane and window alike
    u"group_by": u"panel",      # panel | tab | extension
    u"watch": u"1",
    u"watch_ms": u"1500",
    u"collapsed": u"",          # pipe separated group keys
    u"show_tooltips": u"1",
    u"show_footer": u"1",       # the status line along the bottom
    u"show_paths": u"0",
    u"hide_unloaded": u"0",
    u"name_filter": u"",        # only extensions whose name contains this
    u"debug": u"1",
    u"favourites": u"",         # addin keys in grid order, top left first
    u"fav_labels": u"1",        # names under the favourite tiles
    u"view": u"all",            # all | favourites - remembered
    u"pinned": u"",          # addin keys pinned to the top of the panel
    u"qat": u"",             # addin keys put on Revit's Quick Access Toolbar
    u"win_w": u"380",           # the floating window, when docking is unavailable
    u"win_h": u"900",
    u"win_left": u"",           # where it was last floated; blank = centred
    u"win_top": u"",
}

# A settings key whose MEANING changes needs a migration, not just a new
# default: MIGRATIONS lists the keys each version resets on load.
MIGRATIONS = {
    # 1.3.0 - 1.5.0 stored folded groups under keys that had "|" in them, so
    # they were saved as fragments that can never match again: start clean.
    2: [u"collapsed"],
}

# Lists of addin keys saved by 1.3.0 - 1.5.0 as fragments, four to a key.
# They are rebuilt rather than reset, so favourites and pins added under the
# broken format come back instead of vanishing.
REJOIN_IN_FOURS = {2: [u"favourites", u"pinned", u"qat"]}


def rejoin_fragments(raw):
    u"""'a|b|c|d|e|f|g|h' -> 'a::b::c::d|e::f::g::h', or '' if it cannot be."""
    parts = [part.strip() for part in to_text(raw).split(LIST_SEP)]
    if not any(parts):
        return u""
    if len(parts) % 4:
        return u""
    keys = [KEY_SEP.join(parts[index:index + 4]) for index in range(0, len(parts), 4)]
    return LIST_SEP.join(keys)

ICON_SIZES = [16, 24, 32, 48, 64]

# ----------------------------------------------------------------------
# shrink to taskbar - the drawer arithmetic
#
# Pure, so the logic bench can prove it, including a second monitor ABOVE the
# primary one, where a negative work-area top is what sends a bar to the wrong
# screen. Areas are (left, top, width, height) in WPF units.
# ----------------------------------------------------------------------

DRAWER_MS = 280          # the slide, end to end
DRAWER_TICK_MS = 15      # one frame of it
DRAWER_MARGIN = 8        # a parked bar floats this far clear of the taskbar
DRAWER_GAP = 4           # and this far above the bar below it
DRAWER_MOVED_PX = 2      # dragged further than this, a bar opens where it is


def ease_out(progress):
    u"""Cubic ease out: fast away, gentle landing."""
    if progress <= 0:
        return 0.0
    if progress >= 1:
        return 1.0
    return 1.0 - (1.0 - progress) ** 3


def ease_out_back(progress, overshoot=1.6):
    u"""Out with a little overshoot and settle - the lift of a picked-up tile."""
    if progress <= 0:
        return 0.0
    if progress >= 1:
        return 1.0
    p = progress - 1.0
    return 1.0 + (overshoot + 1.0) * p ** 3 + overshoot * p ** 2


def tween(start, end, progress):
    return start + (end - start) * ease_out(progress)


def free_slot(used):
    u"""The lowest slot nobody is parked in, so a freed slot is reused."""
    taken = set(used)
    slot = 0
    while slot in taken:
        slot += 1
    return slot


def below_height(parked, slot):
    u"""Total height of the bars parked in lower slots, gaps included."""
    total = 0.0
    for other_slot, bar in parked:
        if other_slot < slot:
            total += bar + DRAWER_GAP
    return total


def stacked_top(area, bar, below):
    u"""Where a bar of this height parks, above whatever is already below it."""
    return area[1] + area[3] - DRAWER_MARGIN - below - bar


def expand_rect(saved, landed, now, bar, area):
    u"""(left, top, height) for a window opening out of its parked bar.

    Untouched, it goes back exactly where it was. Carried somewhere else, it
    opens UPWARD from where the bar now sits - the bar's bottom edge stays put -
    kept on that screen, rather than jumping back to a place the user has
    already moved on from.
    """
    left, top, width, height = saved
    moved = (abs(now[0] - landed[0]) > DRAWER_MOVED_PX
             or abs(now[1] - landed[1]) > DRAWER_MOVED_PX)
    if not moved:
        return left, top, height
    area_left, area_top, area_width, area_height = area
    height = min(height, area_height)
    left = now[0]
    top = now[1] + bar - height
    left = max(area_left, min(left, area_left + area_width - width))
    top = max(area_top, min(top, area_top + area_height - height))
    return left, top, height


# ----------------------------------------------------------------------
# favourites - the grid order, and where a dragged tile lands
#
# The order is the settings list itself: a new favourite goes on the end, so a
# grid laid out left to right and top to bottom fills from the top left across
# and then down, like a phone's home screen. Dragging moves one entry.
# ----------------------------------------------------------------------

FAV_GROW = 12            # a favourite's icon is this much bigger than the list's
FAV_MIN_ICON = 32
FAV_DRAG_PX = 5          # pressed and moved further than this, it is a drag
FAV_HOLD_MS = 320        # or held still this long: either way the tile lifts


def fav_icon_size(list_icon_size):
    return max(FAV_MIN_ICON, int(list_icon_size) + FAV_GROW)


def fav_add(keys, key):
    u"""A new favourite goes last - the next free spot in reading order."""
    keys = [k for k in keys if k]
    if key not in keys:
        keys.append(key)
    return keys


def fav_remove(keys, key):
    return [k for k in keys if k and k != key]


def move_item(seq, source, target):
    u"""Take the entry at source out and put it at target, phone style.

    The others close up behind it and open in front of it, so the dragged
    tile ends up exactly where it was dropped.
    """
    seq = list(seq)
    if not seq or source < 0 or source >= len(seq):
        return seq
    target = max(0, min(target, len(seq) - 1))
    if source == target:
        return seq
    entry = seq.pop(source)
    seq.insert(target, entry)
    return seq


def drop_index(rects, point):
    u"""Which slot the pointer is over, given each tile's (left, top, w, h).

    Over a tile: that tile's slot. In a gap, or below the last row: the
    nearest tile in reading order before the pointer, so letting go in the
    empty space after the last tile drops it at the end rather than nowhere.
    None when there are no tiles.
    """
    if not rects:
        return None
    x, y = point
    for index, (left, top, width, height) in enumerate(rects):
        if left <= x < left + width and top <= y < top + height:
            return index
    best = 0
    for index, (left, top, width, height) in enumerate(rects):
        row_hit = top <= y < top + height
        if y >= top + height or (row_hit and x >= left):
            best = index
    return best


# ----------------------------------------------------------------------
# snap docking the floating window to Revit's edge
# ----------------------------------------------------------------------

DOCK_SIDES = (u"left", u"right")


def dock_rect(target, width, side, min_width):
    u"""(left, top, width, height) for a window snapped to one side of target.

    The width is the user's, kept between the window's minimum and the whole
    of the target; the height and top are always the target's.
    """
    t_left, t_top, t_width, t_height = target
    width = max(min_width, min(width, t_width))
    if side == u"right":
        return t_left + t_width - width, t_top, width, t_height
    return t_left, t_top, width, t_height


def rect_differs(a, b, tolerance=1.0):
    if a is None or b is None:
        return True
    for one, two in zip(a, b):
        if abs(one - two) > tolerance:
            return True
    return False


# ----------------------------------------------------------------------
# paths
# ----------------------------------------------------------------------

def appdata_root():
    base = os.environ.get(u"APPDATA") or os.path.expanduser(u"~")
    return os.path.join(base, u"RevoBIM")


def settings_path():
    return os.path.join(appdata_root(), SETTINGS_NAME)


def debug_path():
    return os.path.join(appdata_root(), DEBUG_NAME)


def settings_stamp():
    u"""Modification time of the settings file, or 0.

    The standalone Settings button can run in a different pyRevit engine from
    the one the pane was built in, where the pane's module level state is
    simply not visible - so the pane cannot be told that settings changed. It
    watches this stamp instead, which works whichever engine wrote the file.
    """
    try:
        return os.path.getmtime(settings_path())
    except Exception:
        return 0


def ensure_root():
    try:
        root = appdata_root()
        if not os.path.isdir(root):
            os.makedirs(root)
        return root
    except Exception:
        return None


def tool_folder():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()


# ----------------------------------------------------------------------
# text
# ----------------------------------------------------------------------

def to_text(value):
    if value is None:
        return u""
    try:
        if isinstance(value, unicode):  # noqa: F821  - IronPython 2.7
            return value
    except NameError:
        pass
    try:
        return u"{0}".format(value)
    except Exception:
        return u""


_WS = re.compile(r"\s+")


def normalise(value):
    u"""Lower case, newlines and runs of whitespace collapsed to one space.

    pyRevit writes button titles with embedded newlines so they wrap on the
    ribbon; matching a scanned folder title against a live ribbon caption only
    works once both have been through this.
    """
    return _WS.sub(u" ", to_text(value).replace(u"\\n", u" ")).strip().lower()


def words(value):
    return [w for w in normalise(value).split(u" ") if w]


def matches_search(haystack, terms):
    u"""Every word typed must appear somewhere in the haystack.

    Words rather than a substring, so "sheet man" finds "Sheet Manager" and
    also "Management - Sheets" without caring what order they were typed in.
    """
    if not terms:
        return True
    hay = normalise(haystack)
    for term in terms:
        if term not in hay:
            return False
    return True


def natural_key(value):
    parts = re.split(r"(\d+)", to_text(value).lower())
    out = []
    for part in parts:
        if part.isdigit():
            out.append((1, int(part), u""))
        else:
            out.append((0, 0, part))
    return out


# ----------------------------------------------------------------------
# settings - plain key=value text, split on the FIRST '=' only
# ----------------------------------------------------------------------

def load_settings():
    values = {}
    for key in DEFAULTS:
        values[key] = DEFAULTS[key]
    path = settings_path()
    try:
        if os.path.isfile(path):
            handle = open(path, u"rb")
            try:
                raw = handle.read()
            finally:
                handle.close()
            try:
                raw = raw.decode(u"utf-8")
            except Exception:
                raw = to_text(raw)
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith(u"#"):
                    continue
                if u"=" not in line:
                    continue
                key, value = line.split(u"=", 1)
                key = key.strip()
                # Unknown keys - from a newer or older version - are ignored
                # rather than breaking the load.
                if key in DEFAULTS:
                    values[key] = value.strip()
    except Exception:
        # A damaged file falls back to the defaults key by key.
        pass
    return apply_migrations(values)


def apply_migrations(values):
    try:
        found = int(to_text(values.get(u"settings_version", u"1")) or u"1")
    except Exception:
        found = 1
    for version in sorted(MIGRATIONS.keys()):
        if found < version:
            for key in MIGRATIONS[version]:
                if key in DEFAULTS:
                    values[key] = DEFAULTS[key]
    for version in sorted(REJOIN_IN_FOURS.keys()):
        if found < version:
            for key in REJOIN_IN_FOURS[version]:
                if key in values and KEY_SEP not in to_text(values[key]):
                    values[key] = rejoin_fragments(values[key])
    values[u"settings_version"] = to_text(SETTINGS_VERSION)
    return values


def save_settings(values):
    ensure_root()
    lines = [u"# RevoBIM Addins settings - plain key=value, safe to hand edit"]
    for key in sorted(DEFAULTS.keys()):
        lines.append(u"{0}={1}".format(key, to_text(values.get(key, DEFAULTS[key]))))
    text = u"\n".join(lines) + u"\n"
    try:
        handle = open(settings_path(), u"wb")
        try:
            handle.write(text.encode(u"utf-8"))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def as_bool(values, key):
    return to_text(values.get(key, DEFAULTS.get(key, u"0"))).strip() in (u"1", u"true", u"True", u"yes", u"on")


def as_int(values, key, fallback=0):
    try:
        return int(to_text(values.get(key, DEFAULTS.get(key, u""))).strip())
    except Exception:
        return fallback


def as_list(values, key):
    raw = to_text(values.get(key, u""))
    return [part.strip() for part in raw.split(LIST_SEP) if part.strip()]


def set_list(values, key, items):
    entries = [to_text(item) for item in items]
    for entry in entries:
        if LIST_SEP in entry:
            # Loud, not silent: this is exactly how favourites were lost.
            raise ValueError(u"a {0} entry contains the list separator: {1}".format(
                key, entry))
    values[key] = LIST_SEP.join(entries)


# ----------------------------------------------------------------------
# debug log
# ----------------------------------------------------------------------

_DEBUG_ON = [True]


def set_debug(flag):
    _DEBUG_ON[0] = bool(flag)


def log(message):
    if not _DEBUG_ON[0]:
        return
    try:
        ensure_root()
        handle = open(debug_path(), u"ab")
        try:
            handle.write((to_text(message) + u"\n").encode(u"utf-8"))
        finally:
            handle.close()
    except Exception:
        pass


def log_exception(where):
    try:
        import traceback
        log(u"[{0}] {1}".format(where, traceback.format_exc()))
    except Exception:
        pass


def add_tool_folder_to_path():
    folder = tool_folder()
    if folder not in sys.path:
        sys.path.append(folder)
    return folder
