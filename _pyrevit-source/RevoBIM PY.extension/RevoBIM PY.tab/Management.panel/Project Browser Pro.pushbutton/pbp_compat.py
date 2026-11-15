# -*- coding: utf-8 -*-
u"""Project Browser Pro - helpers that behave the same on IronPython 2.7,
IronPython 3 and CPython (the bench).

No clr, no System, no Autodesk in here: this module is imported by the pure
logic modules the bench runs under plain CPython.
"""
import os
import re
import sys

# The tool's own folder. pyRevit resets the start up engine's sys.path once
# startup.py has run, so the docked panes - built later, the first time each
# is shown - would no longer find their own modules (1.7.1: a black pane,
# "No module named pbp_browser"). Everything that can run after start up puts
# the folder back first: on_path().
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    text_type = unicode  # noqa: F821  (IronPython 2.7)
except NameError:
    text_type = str

try:
    int_types = (int, long)  # noqa: F821
except NameError:
    int_types = (int,)


def to_text(value):
    u"""Anything to a unicode string, never raising."""
    if value is None:
        return u''
    if isinstance(value, text_type):
        return value
    try:
        return text_type(value)
    except Exception:
        pass
    try:
        return value.decode('utf-8', 'replace')
    except Exception:
        return u''


_DIGITS = re.compile(r'(\d+)')


def natural_key(value):
    u"""Sort key where Level 2 comes before Level 10.

    re.split with a capturing group alternates text, digits, text..., so
    every position holds the same kind in every key and CPython 3 never has
    to compare an int with a string.
    """
    parts = _DIGITS.split(to_text(value).lower())
    key = []
    for index, part in enumerate(parts):
        if index % 2:
            key.append(int(part))
        else:
            key.append(part)
    return tuple(key)


def words(text):
    u"""Lower-cased search words; empty text gives an empty list."""
    return [w for w in to_text(text).lower().split() if w]


def matches(haystack, search_words):
    u"""Every word has to be contained somewhere in the haystack."""
    if not search_words:
        return True
    hay = to_text(haystack).lower()
    for word in search_words:
        if word not in hay:
            return False
    return True


def eid_value(element_id):
    u"""ElementId to an integer on Revit 2021-2027.

    .Value (Int64) from 2024, .IntegerValue removed in 2026. This is the only
    place in the tool allowed to touch .IntegerValue - the bench enforces it.
    """
    if element_id is None:
        return 0
    try:
        return int(element_id.Value)
    except Exception:
        pass
    try:
        return int(element_id.IntegerValue)
    except Exception:
        return 0


def clamp(value, low, high):
    try:
        value = float(value)
    except Exception:
        value = low
    if value < low:
        return low
    if value > high:
        return high
    return value


def safe_file_part(text):
    u"""A project title made safe to use as a file name."""
    out = []
    for ch in to_text(text):
        if ch in u'<>:"/\\|?*' or ord(ch) < 32:
            out.append(u'_')
        else:
            out.append(ch)
    cleaned = u''.join(out).strip().strip(u'.')
    return cleaned or u'Untitled'


def on_path():
    u"""Put the tool's folder back on sys.path if something took it off.
    True when it had to. Cheap enough to call before every late import."""
    try:
        if TOOL_DIR not in sys.path:
            sys.path.append(TOOL_DIR)
            return True
    except Exception:
        pass
    return False
