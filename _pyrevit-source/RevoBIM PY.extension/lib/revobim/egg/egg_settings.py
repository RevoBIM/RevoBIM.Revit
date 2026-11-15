# -*- coding: utf-8 -*-
"""Settings for the easter egg.

Plain key=value text at %APPDATA%\\RevoBIM\\easter_egg.txt, same as every other
RevoBIM tool. A missing or damaged file falls back to the defaults key by key,
and keys from an older version are ignored rather than breaking the load.
"""

import os

SETTINGS_VERSION = 3

DEFAULTS = {
    "settings_version": "3",
    "game": "pacman",
    "theme": "auto",
    "clicks": "3",
    "click_gap_min_ms": "250",
    "click_gap_max_ms": "2000",
    "sound": "off",
    "run_mode": "auto",
    "player": "",
    "scores_shown": "15",
    "scores_kept": "300",
    "scores_on_finish": "on",
}

# Keys whose meaning or default changed, per version, reset on load from an
# older file. Without this a 1.2.0 file keeps scores_shown=10 for ever: the
# whole set of keys is written back on every save, so the old default is not
# missing from the file and would never fall through to the new one.
MIGRATIONS = {
    2: ("scores_shown",),
    3: ("clicks",),
}

_FOLDER_NAME = "RevoBIM"
_FILE_NAME = "easter_egg.txt"


def folder():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, _FOLDER_NAME)


def path():
    return os.path.join(folder(), _FILE_NAME)


def load():
    """Return a dict of settings, defaults filled in for anything missing."""
    values = {}
    for key in DEFAULTS:
        values[key] = DEFAULTS[key]
    try:
        target = path()
        if not os.path.isfile(target):
            return values
        handle = open(target, "r")
        try:
            lines = handle.read().splitlines()
        finally:
            handle.close()
    except Exception:
        return values

    raw = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        # Split on the first '=' only, so a value may contain '='.
        parts = line.split("=", 1)
        raw[parts[0].strip()] = parts[1].strip()

    try:
        was = int(raw.get("settings_version", "0"))
    except Exception:
        was = 0
    reset = set()
    for version in MIGRATIONS:
        if was < version:
            for key in MIGRATIONS[version]:
                reset.add(key)

    for key in raw:
        # High scores are per game, so their key names are not known up front.
        known = key in DEFAULTS or key.startswith("high_")
        if known and key not in reset:
            values[key] = raw[key]

    values["settings_version"] = str(SETTINGS_VERSION)
    return values


def save(values):
    """Write the settings back. Never raises."""
    try:
        target_folder = folder()
        if not os.path.isdir(target_folder):
            os.makedirs(target_folder)
        keys = sorted(values.keys())
        text = []
        for key in keys:
            text.append("{0}={1}".format(key, values[key]))
        handle = open(path(), "w")
        try:
            handle.write("\n".join(text))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def get_int(values, key, fallback):
    try:
        return int(str(values.get(key, fallback)).strip())
    except Exception:
        return fallback


def high_score(values, game_key):
    return get_int(values, "high_" + game_key, 0)


def set_high_score(values, game_key, score):
    """Record a high score if it beats what is there. Returns True if it did."""
    if score <= high_score(values, game_key):
        return False
    values["high_" + game_key] = str(int(score))
    save(values)
    return True
