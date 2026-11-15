# -*- coding: utf-8 -*-
"""revobim.nudge_settings - shared settings for the Nudge toolset.

The Up button, the Down button and the Settings window are three separate
pyRevit commands, so the increment cannot live inside any one of them. It is
kept in a small JSON file instead:

    %APPDATA%\\RevoBIM PY\\nudge_settings.json

Depends only on the .NET base library, so it loads under IronPython 2.7
without pyRevit having to be present.

    from revobim.nudge_settings import load, save, DEFAULTS

    cfg = load()
    cfg['step_mm'] = 100.0
    save(cfg)
"""

import os
import json

VERSION = '1.6.0'

DEFAULTS = {
    # how far each nudge moves the element, in millimetres
    'step_mm': 50.0,
    # quick-pick buttons shown in the Settings window
    'presets': [10.0, 25.0, 50.0, 100.0],
    # round the resulting elevation to a tidy figure rather than carrying
    # whatever odd number the element started on
    'snap_enabled': True,
    'snap_mm': 5.0,
    # after nudging a pre-selection, put the selection back so the next press
    # of the button (or the keyboard shortcut) moves the same elements again
    'keep_selection': True,
    # with nothing pre-selected, keep asking for elements until Escape
    'repeat_loop': True,
    # let fittings, accessories and equipment be nudged, not just straight runs
    'allow_fittings': True,
    # fabrication fittings, fabrication hangers and MEP ancillary framing.
    # Fabrication straights are runs and are always allowed.
    'allow_fabrication': True,
    # after moving a fabrication hanger, re-cut manual rods so their tops stay
    # at the soffit. Rods Revit hosts re-solve themselves either way.
    'recut_rods': True,
}

_FOLDER = os.path.join(
    os.getenv('APPDATA') or os.path.expanduser('~'), 'RevoBIM PY')
_PATH = os.path.join(_FOLDER, 'nudge_settings.json')


def path():
    """Where the settings file lives."""
    return _PATH


# The Up and Down buttons run on a keyboard shortcut and read the settings on
# every press, so the parsed result is held and only re-read when the file
# actually changes on disk. Under a persistent engine that turns a file open
# plus a JSON parse per press into a single stat call.
_cache = None
_cache_stamp = None


def _stamp():
    """(mtime, size) of the settings file, or None if it is not there."""
    try:
        info = os.stat(_PATH)
        return (info.st_mtime, info.st_size)
    except OSError:
        return None


def load(use_cache=True):
    """Read the settings, filling in anything missing from DEFAULTS."""
    global _cache, _cache_stamp

    if use_cache:
        stamp = _stamp()
        if _cache is not None and stamp == _cache_stamp:
            return dict(_cache)

    cfg = _read()

    if use_cache:
        _cache = dict(cfg)
        _cache_stamp = stamp
    return cfg


def _read():
    cfg = dict(DEFAULTS)
    try:
        if os.path.isfile(_PATH):
            with open(_PATH, 'r') as handle:
                saved = json.load(handle)
            if isinstance(saved, dict):
                for key in DEFAULTS:
                    if key in saved:
                        cfg[key] = saved[key]
    except Exception:
        # a corrupt or unreadable file must never stop the tool running -
        # fall back to the defaults quietly
        pass
    cfg['step_mm'] = clamp_step(cfg.get('step_mm'))
    cfg['snap_mm'] = clamp_snap(cfg.get('snap_mm'))
    return cfg


def save(cfg):
    """Write the settings. Returns True if it stuck."""
    global _cache, _cache_stamp
    try:
        if not os.path.isdir(_FOLDER):
            os.makedirs(_FOLDER)
        merged = dict(DEFAULTS)
        merged.update(cfg or {})
        merged['step_mm'] = clamp_step(merged.get('step_mm'))
        merged['snap_mm'] = clamp_snap(merged.get('snap_mm'))
        with open(_PATH, 'w') as handle:
            json.dump(merged, handle, indent=2, sort_keys=True)
        # drop the cache so the next read picks the new values straight up,
        # even if the clock is too coarse to show a changed mtime
        _cache = None
        _cache_stamp = None
        return True
    except Exception:
        return False


def step_mm():
    """Just the increment, for callers that want nothing else."""
    return load()['step_mm']


def snap_mm():
    """The snap in millimetres, or 0.0 when snapping is switched off."""
    cfg = load()
    return cfg['snap_mm'] if cfg['snap_enabled'] else 0.0


def clamp_snap(value):
    """Coerce the snap into a sane figure. 0 or junk means no snapping."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULTS['snap_mm']
    if number <= 0:
        return 0.0
    if number > 1000.0:
        return 1000.0
    return number


def clamp_step(value):
    """Coerce whatever came in into a sane positive millimetre figure."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULTS['step_mm']
    if number <= 0:
        return DEFAULTS['step_mm']
    if number > 100000.0:
        return 100000.0
    return number
