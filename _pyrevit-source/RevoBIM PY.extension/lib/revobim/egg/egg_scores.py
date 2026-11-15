# -*- coding: utf-8 -*-
"""The scoreboard.

Every finished game is written to
``%APPDATA%\\RevoBIM\\easter_egg_scores.txt`` with who played it and when.

One record per line rather than key=value, which is the one place the egg parts
company with the house settings format - a settings file is a set of named
values and a scoreboard is a list, and pretending otherwise would mean keys like
``entry_7_score``. The settings file itself is untouched and still key=value.

    # game|when|player|score
    pacman|2026-09-07T14:03:11|dgibbons|3140

Plain stdlib, no .NET, so it runs on the bench exactly as it runs in Revit.
"""

import datetime
import os

FIELDS = 4
SEPARATOR = "|"
HEADER = "# RevoBIM easter egg scores. One record per line: game|when|player|score"

_FOLDER_NAME = "RevoBIM"
_FILE_NAME = "easter_egg_scores.txt"

DEFAULT_KEPT = 300
DEFAULT_SHOWN = 10


def folder():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, _FOLDER_NAME)


def path():
    return os.path.join(folder(), _FILE_NAME)


def player_name(settings=None):
    """Who to credit the game to.

    The `player` setting wins where somebody has set one - a shared coordination
    machine logged in as `bimuser` makes for a dull scoreboard. Otherwise the
    Windows account, then the POSIX one, then something honest.
    """
    if settings:
        named = str(settings.get("player", "") or "").strip()
        if named:
            return _clean(named)
    for key in ("USERNAME", "USER", "LOGNAME"):
        value = os.environ.get(key)
        if value and value.strip():
            return _clean(value.strip())
    return "unknown"


def _clean(value):
    """No separators and no newlines, or the record cannot be read back."""
    text = str(value)
    for bad in (SEPARATOR, "\r", "\n", "\t"):
        text = text.replace(bad, " ")
    text = " ".join(text.split())
    return text[:32] if text else "unknown"


def _as_int(value, fallback=0):
    try:
        return int(str(value).strip())
    except Exception:
        return fallback


# -- reading =============================================================

def _read_lines():
    try:
        target = path()
        if not os.path.isfile(target):
            return []
        handle = open(target, "r")
        try:
            return handle.read().splitlines()
        finally:
            handle.close()
    except Exception:
        return []


def load(game_key=None):
    """Every recorded game, newest first within equal scores.

    A damaged line is dropped rather than taken as a reason to lose the file:
    somebody hand-editing this, or a half-written line from a machine that was
    shut down mid-write, should cost one row and not the scoreboard.
    """
    entries = []
    for line in _read_lines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(SEPARATOR)
        if len(parts) < FIELDS:
            continue
        game = parts[0].strip()
        if game_key is not None and game != game_key:
            continue
        entries.append({
            "game": game,
            "when": parts[1].strip(),
            "player": parts[2].strip() or "unknown",
            "score": _as_int(parts[3]),
        })
    return entries


def ranked(game_key, limit=None):
    """Highest score first, and for a tie the older game keeps the higher place.

    Getting there first is worth something, and it also makes the board stable:
    a repeated score does not shuffle the rows around every time it happens.
    """
    entries = load(game_key)
    ordered = sorted(entries, key=lambda item: (-item["score"], item["when"]))
    if limit:
        return ordered[:limit]
    return ordered


# -- writing =============================================================

def record(game_key, score, settings=None, when=None, player=None):
    """Write one finished game. Returns (entry, position, total).

    `position` is 1-based against every game ever played on this machine, so a
    first place actually means something.
    """
    entry = {
        "game": str(game_key),
        "when": (when or datetime.datetime.now()).strftime("%Y-%m-%dT%H:%M:%S"),
        "player": _clean(player) if player else player_name(settings),
        "score": _as_int(score),
    }

    kept = DEFAULT_KEPT
    if settings:
        kept = _as_int(settings.get("scores_kept", DEFAULT_KEPT), DEFAULT_KEPT)

    everything = load()
    everything.append(entry)
    _write(everything, kept)

    table = ranked(entry["game"])
    position = len(table)
    for index in range(len(table)):
        row = table[index]
        if (row["when"] == entry["when"] and row["player"] == entry["player"]
                and row["score"] == entry["score"]):
            position = index + 1
            break
    return (entry, position, len(table))


def _write(entries, kept):
    """Keep the best `kept` records, dropping the weakest, and never raise.

    Trimmed by score rather than by age: the file is a scoreboard, and throwing
    away last year's 9,000 to keep this morning's 40 is the wrong trade.
    """
    try:
        target_folder = folder()
        if not os.path.isdir(target_folder):
            os.makedirs(target_folder)
        if kept and len(entries) > kept:
            entries = sorted(entries,
                             key=lambda item: (-item["score"], item["when"]))
            entries = entries[:kept]
        lines = [HEADER]
        for entry in entries:
            lines.append(SEPARATOR.join([
                _clean(entry["game"]),
                _clean(entry["when"]),
                _clean(entry["player"]),
                str(_as_int(entry["score"])),
            ]))
        handle = open(path(), "w")
        try:
            handle.write("\n".join(lines))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def clear(game_key=None):
    """Wipe the board, or just one game's rows."""
    if game_key is None:
        return _write([], 0)
    keep = [entry for entry in load() if entry["game"] != game_key]
    return _write(keep, 0)


# -- display =============================================================

def pretty_when(value):
    """`2026-09-07T14:03:11` as `07 Sep 14:03`, and anything odd left alone."""
    try:
        stamp = datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
        return stamp.strftime("%d %b %H:%M")
    except Exception:
        return str(value)[:16]


def personal_best(game_key, player):
    for entry in ranked(game_key):
        if entry["player"] == player:
            return entry["score"]
    return 0
