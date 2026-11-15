# -*- coding: utf-8 -*-
"""Wiring the egg to every tool at once, without editing any of them.

WPF lets a handler be registered against a *class* rather than an instance, for
the whole AppDomain. So one `Window.Loaded` class handler sees every window any
addin in Revit ever opens, and the egg can attach itself to the ones that belong
to RevoBIM as they appear.

That turns "remember to wire the egg into each tool" into "it is already wired",
including in tools built before the egg existed and tools built after it that
nobody thought about.

Installed from `startup.py` at the extension root. Everything is wrapped: a
class handler that throws would break window creation for every addin in the
process, which is a far worse thing than a missing easter egg.
"""

import clr

from revobim.egg import egg_clr  # noqa: F401  - assemblies first, always

from System.Windows import EventManager, FrameworkElement, RoutedEventHandler
from System.Windows import Window

from revobim.egg import egg_hook, egg_log

BRAND = "revobim"

# Set on the egg's own window so it does not hook itself.
OURS = "RevoBIMEggWindow"

# Set on a window once it has been wired, so a re-parented element raising
# Loaded a second time does not stack a second hook on it.
DONE = "RevoBIMEggAttached"

_state = {"installed": False, "handler": None, "seen": 0, "wired": 0}


def wants_egg(title, has_named_logo, brand_in_title):
    """Should this window be wired? Pure, so it can be tested.

    Deliberately mean about it. This runs for **every window every addin in
    Revit opens**, so a loose test costs other people's dialogs a tree walk, and
    a wrong positive puts an easter egg on somebody else's software.

    A named logo is proof enough on its own. Otherwise the title has to carry
    the brand before it is worth looking any harder.
    """
    if has_named_logo:
        return True
    return bool(brand_in_title)


def _title_of(window):
    try:
        return (window.Title or "").lower()
    except Exception:
        return ""


def _marked(window, key):
    try:
        return bool(window.Resources.Contains(key))
    except Exception:
        return False


def _mark(window, key):
    try:
        window.Resources[key] = True
    except Exception:
        pass


def mark_as_ours(window):
    """Called by the egg's own window, so the handler steps over it."""
    _mark(window, OURS)


def _on_loaded(sender, args):
    try:
        window = sender
        _state["seen"] += 1

        if _marked(window, OURS) or _marked(window, DONE):
            return

        title = _title_of(window)
        # The cheap test first. A dozen FindName lookups are nothing; walking
        # the logical tree of every dialog Revit opens is not, so that only
        # happens once the title has said the window is one of ours.
        named = egg_hook.find_logo(window, deep=False)
        brand = BRAND in title
        if not wants_egg(title, bool(named), brand):
            return

        elements = named or egg_hook.find_logo(window, deep=True)
        if not elements:
            return

        _mark(window, DONE)
        detach = egg_hook.attach(elements, host_window=window,
                                 tool=_name_of(window))
        if detach is not None:
            _state["wired"] += 1
    except Exception:
        # Never let this escape. It runs inside every window's Loaded, for every
        # addin in the process.
        pass


def _name_of(window):
    try:
        return str(window.Title or window.GetType().Name)
    except Exception:
        return "window"


def install():
    """Wire the egg into every RevoBIM window from now on. Returns True if on.

    Idempotent: calling it twice does nothing the second time, so a startup.py
    that has been pasted together from two sources cannot double-hook.
    """
    try:
        if _state["installed"]:
            return True
        handler = RoutedEventHandler(_on_loaded)
        EventManager.RegisterClassHandler(
            clr.GetClrType(Window), FrameworkElement.LoadedEvent, handler,
            True)
        _state["handler"] = handler
        _state["installed"] = True
        egg_log.write("auto-attach installed: every RevoBIM window from now on",
                      "auto")
        return True
    except Exception:
        egg_log.write("auto-attach could NOT install: {0}".format(
            _error()), "auto")
        return False


def status():
    """A line for a diagnostic dialog.

    There is no uninstall: WPF has no `UnregisterClassHandler`, and a class
    handler lives for the life of the AppDomain. The handler steps over anything
    already wired instead, which comes to the same thing.
    """
    return ("auto-attach {0}; {1} windows seen, {2} wired".format(
        "on" if _state["installed"] else "OFF", _state["seen"],
        _state["wired"]))


def _error():
    try:
        import traceback
        return traceback.format_exc().replace("\n", " | ")
    except Exception:
        return "unknown"
