# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager : the easter egg link.

Three slow clicks on the RevoBIM logo. Slow is the point: an ordinary
double click, or an impatient triple, must not trigger it, so the gaps
between the clicks have to fall inside a window rather than merely add up.

The click counting is plain Python so the bench can test it. The launch
itself reaches into the extension's shared `revobim.egg` package and is
wrapped so that a missing or changed egg can never take the tool down -
it is decoration, and decoration does not get to break a filter editor.
"""

# a click sooner than this is part of a double click, not a slow one
MIN_GAP = 0.35
# and later than this is a new attempt rather than a continuation
MAX_GAP = 1.6
CLICKS_WANTED = 3


class SlowTriple(object):
    """Counts three deliberate, evenly spaced clicks."""

    def __init__(self, wanted=CLICKS_WANTED, low=MIN_GAP, high=MAX_GAP):
        self.wanted = wanted
        self.low = low
        self.high = high
        self.last = None
        self.count = 0

    def reset(self):
        self.last = None
        self.count = 0

    def click(self, now):
        """Register a click. True when the pattern has just completed."""
        if self.last is None:
            self.count = 1
            self.last = now
            return False

        gap = now - self.last
        self.last = now

        if gap < self.low:
            # too quick: this is a double click, and it starts the count over
            self.count = 1
            return False
        if gap > self.high:
            # too slow to be part of the same attempt
            self.count = 1
            return False

        self.count += 1
        if self.count >= self.wanted:
            self.reset()
            return True
        return False


import os

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except Exception:
    _HERE = ""


def _add_lib_to_path():
    """pyRevit only puts lib on sys.path if something did it first."""
    import sys
    probe = _HERE
    for _ in range(6):
        if probe.lower().endswith(".extension"):
            lib = os.path.join(probe, "lib")
            if os.path.isdir(lib) and lib not in sys.path:
                sys.path.append(lib)
            return
        parent = os.path.dirname(probe)
        if parent == probe:
            return
        probe = parent


def launch(owner=None, theme=None):
    """Start the egg. True when it started.

    The shared package's real entry point, looked up rather than guessed:
    revobim.egg.egg_hook.launch, taking host_window, theme and game_key.
    Passed by keyword, so a window can never land in the game_key slot.
    `theme` is "dark", "light" or a callable returning one. game_key is left
    to the egg, which uses whichever game its own settings pick.
    """
    try:
        _add_lib_to_path()
        from revobim.egg import egg_hook
    except Exception:
        return False
    try:
        return bool(egg_hook.launch(host_window=owner, theme=theme,
                                    game_key=None))
    except Exception:
        return False
