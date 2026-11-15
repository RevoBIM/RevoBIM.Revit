# -*- coding: utf-8 -*-
"""Finding the games.

Games are discovered from the filenames in the games folder rather than from a
list held here, so adding one is a matter of dropping a module in and nothing
else. A module that does not answer the contract is left out rather than
breaking the egg.
"""

import os

FALLBACK = ("pacman", "snake")

_REQUIRED_ATTRS = ("NAME", "KEY", "TICK_MS", "KEYS", "Game")
_REQUIRED_METHODS = ("start", "stop", "tick", "key", "status", "is_over",
                     "width", "height")


def games_folder():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "games")


def module_names():
    """Every candidate module name in the games folder, sorted."""
    names = []
    try:
        for entry in os.listdir(games_folder()):
            if not entry.endswith(".py"):
                continue
            stem = entry[:-3]
            if stem.startswith("_"):
                continue
            names.append(stem)
    except Exception:
        names = list(FALLBACK)
    if not names:
        names = list(FALLBACK)
    names.sort()
    return names


def load(name):
    """Import one game module and check it answers the contract."""
    try:
        full = "revobim.egg.games." + name
        module = __import__(full, globals(), locals(), [name])
    except Exception:
        return None
    for attr in _REQUIRED_ATTRS:
        if not hasattr(module, attr):
            return None
    for method in _REQUIRED_METHODS:
        if not hasattr(module.Game, method):
            return None
    return module


def available():
    """[(key, name, module)] for every game that loads cleanly."""
    found = []
    for name in module_names():
        module = load(name)
        if module is not None:
            found.append((module.KEY, module.NAME, module))
    return found


def pick(wanted):
    """The wanted game, else the first one that loads, else None."""
    games = available()
    if not games:
        return None
    for key, name, module in games:
        if key == wanted:
            return module
    return games[0][2]


def next_after(wanted):
    """The key of the game after this one, wrapping. Drives the header chip."""
    games = available()
    if not games:
        return wanted
    keys = [entry[0] for entry in games]
    if wanted in keys:
        return keys[(keys.index(wanted) + 1) % len(keys)]
    return keys[0]
