# -*- coding: utf-8 -*-
"""RevoBIM Arcade - double click this.

A .pyw rather than a .py so Windows opens it with pythonw and no console window
appears behind the game.

Nothing here knows anything about Revit. It puts the extension's lib folder on
sys.path and hands over to the desktop build.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def main():
    if LIB not in sys.path:
        sys.path.insert(0, LIB)
    try:
        from revobim.egg import egg_desktop
    except ImportError:
        _complain("Could not find the RevoBIM egg package.\n\n"
                  "Expected it at:\n  {0}\n\nThis file has to stay in\n"
                  "  lib\\revobim\\egg\\standalone\\".format(
                      os.path.join(LIB, "revobim", "egg")))
        return 3
    return egg_desktop.main(sys.argv[1:])


def _complain(message):
    """Say so in a window, since a .pyw has no console to print to."""
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("RevoBIM Arcade", message)
        root.destroy()
    except Exception:
        sys.stderr.write(message + "\n")


if __name__ == "__main__":
    sys.exit(main())
