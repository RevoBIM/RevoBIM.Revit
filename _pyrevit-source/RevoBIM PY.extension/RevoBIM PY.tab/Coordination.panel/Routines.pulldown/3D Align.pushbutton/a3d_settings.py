# -*- coding: utf-8 -*-
"""3D Align - version, settings and paths. No Revit and no WPF in here.

Settings are plain key=value text at %APPDATA%\\RevoBIM\\3d_align.txt. A missing
or damaged file falls back to the defaults key by key, and keys this version
does not know are ignored rather than breaking the load.
"""
import io
import os

__version__ = '1.0.0'
TOOL_NAME = u'3D Align'

MM_PER_FT = 304.8

SETTINGS_VERSION = 1
# {settings version: [keys whose meaning changed and are reset to default]}
MIGRATIONS = {}

CHOICES = {
    'keep_running': ('on', 'off'),
    'show_results': ('needs_look', 'always', 'never'),
    'on_refusal': ('detach', 'leave'),
    'theme': ('follow', 'dark', 'light'),
    'debug': ('on', 'off'),
}

DEFAULTS = {
    'settings_version': str(SETTINGS_VERSION),
    'keep_running': 'on',
    'show_results': 'needs_look',
    'on_refusal': 'detach',
    'max_move_mm': '3000',
    'theme': 'follow',
    'debug': 'on',
}

THEME_CYCLE = ('follow', 'dark', 'light')


def data_dir():
    root = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(root, 'RevoBIM')


def settings_path():
    return os.path.join(data_dir(), '3d_align.txt')


def debug_path():
    return os.path.join(data_dir(), '3d_align_debug.txt')


def error_path():
    return os.path.join(data_dir(), '3d_align_last_error.txt')


def clean_value(key, value):
    """The value as it should be stored, or None when it cannot be used."""
    value = (value or u'').strip()
    if key in CHOICES:
        return value if value in CHOICES[key] else None
    if key == 'max_move_mm':
        try:
            number = float(value)
        except ValueError:
            return None
        if number < 0:
            return None
        if number == int(number):
            return str(int(number))
        return str(number)
    if key == 'settings_version':
        try:
            return str(int(value))
        except ValueError:
            return None
    return None


def load(path=None):
    path = path or settings_path()
    found = {}
    try:
        with io.open(path, 'r', encoding='utf-8') as handle:
            for line in handle:
                if '=' not in line or line.lstrip().startswith('#'):
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                if key not in DEFAULTS:
                    continue
                value = clean_value(key, value)
                if value is not None:
                    found[key] = value
    except Exception:
        pass
    try:
        saved_version = int(found.get('settings_version', '0'))
    except ValueError:
        saved_version = 0
    for version in sorted(MIGRATIONS):
        if saved_version < version:
            for key in MIGRATIONS[version]:
                found.pop(key, None)
    out = dict(DEFAULTS)
    out.update(found)
    out['settings_version'] = str(SETTINGS_VERSION)
    return out


def save(settings, path=None):
    path = path or settings_path()
    try:
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        lines = [u'# 3D Align v{0}'.format(__version__)]
        for key in sorted(DEFAULTS):
            value = clean_value(key, u'{0}'.format(settings.get(key, DEFAULTS[key])))
            if value is None:
                value = DEFAULTS[key]
            lines.append(u'{0}={1}'.format(key, value))
        with io.open(path, 'w', encoding='utf-8') as handle:
            handle.write(u'\n'.join(lines) + u'\n')
        return True
    except Exception:
        return False


def save_theme(mode, path=None):
    """The header chip saves the theme on its own, so a settings window that is
    then cancelled does not take its other unsaved edits with it."""
    stored = load(path)
    stored['theme'] = mode
    return save(stored, path)


def next_theme(mode):
    try:
        index = THEME_CYCLE.index(mode)
    except ValueError:
        return THEME_CYCLE[0]
    return THEME_CYCLE[(index + 1) % len(THEME_CYCLE)]


def max_move_ft(settings):
    """The largest move allowed in feet, or None for no limit."""
    try:
        value = float(settings.get('max_move_mm', DEFAULTS['max_move_mm']))
    except (TypeError, ValueError):
        value = float(DEFAULTS['max_move_mm'])
    if value <= 0:
        return None
    return value / MM_PER_FT


def is_on(settings, key):
    return settings.get(key, DEFAULTS.get(key)) == 'on'
