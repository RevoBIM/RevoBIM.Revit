# -*- coding: utf-8 -*-
"""RevoBIM Arcade.

The easter egg, without the easter egg. Three slow clicks on any tool's logo
still opens it; this is for when you would rather just press a button.

Shift-click for a diagnostic report - which is the thing to reach for if the
logo clicks are not working somewhere.
"""

__title__ = "RevoBIM Arcade"
__author__ = "RevoBIM"

# The game outlives this command: it runs on its own thread, or in its own
# process, and either way this script returns immediately afterwards. Without
# this, pyRevit tears the engine down the moment it returns and takes the game
# thread with it - the command "succeeds", nothing appears, and nothing is
# reported. Any tool that starts something which outlives its own run needs it.
__persistentengine__ = True

import os
import sys
import traceback

# Staged loading. Each stage says which one it was, because the alternative is
# pyRevit's blank white window with nothing readable in it.
_STAGE = "starting"


def _report(stage, error):
    """Say what failed, in a dialog and in a file. Never raise while doing it."""
    text = "RevoBIM Arcade could not start.\n\nStage: {0}\n\n{1}".format(
        stage, error)
    try:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(os.path.join(folder, "arcade_last_error.txt"), "w")
        try:
            handle.write(text)
        finally:
            handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("RevoBIM Arcade", text)
    except Exception:
        pass


def _close_output():
    """Shut pyRevit's output window if one opened.

    It opens the moment anything reaches stdout or stderr - including a warning
    raised by IronPython itself, which is not ours to stop. A blank white window
    sitting behind the game reads as a crash, and errors here go to a TaskDialog
    rather than to the output window, so there is nothing in it worth keeping.
    """
    try:
        from pyrevit import script
        output = script.get_output()
        if output is not None:
            output.close()
    except Exception:
        pass


def _shift_held():
    try:
        from System.Windows.Input import Keyboard, ModifierKeys
        return bool(Keyboard.Modifiers & ModifierKeys.Shift)
    except Exception:
        return False


def main():
    global _STAGE

    _STAGE = "finding the shared library"
    # lib is four folders up: <ext>\<tab>\<panel>\<pulldown>\<button>
    here = os.path.dirname(os.path.abspath(__file__))
    root = here
    for _ in range(4):
        root = os.path.dirname(root)
    lib = os.path.join(root, "lib")
    if os.path.isdir(lib) and lib not in sys.path:
        sys.path.insert(0, lib)

    _STAGE = "importing the egg"
    from revobim.egg import egg_hook

    if _shift_held():
        _STAGE = "building the diagnostic report"
        report = egg_hook.diagnose()
        try:
            from revobim.egg import egg_auto
            report = report + "\n\n" + egg_auto.status()
        except Exception:
            pass
        try:
            from Autodesk.Revit.UI import TaskDialog
            TaskDialog.Show("RevoBIM Arcade", report)
        except Exception:
            pass
        return

    _STAGE = "opening the game"
    # No game key: whatever the game chip was last set to, which is Pacman until
    # somebody changes it. Forcing one here would make the chip pointless.
    opened = egg_hook.launch()
    _close_output()
    if not opened:
        _report("opening the game",
                "The game reported that it did not open.\n\n"
                "Shift-click this button for a diagnostic report.")


try:
    main()
except Exception:
    _report(_STAGE, traceback.format_exc())
