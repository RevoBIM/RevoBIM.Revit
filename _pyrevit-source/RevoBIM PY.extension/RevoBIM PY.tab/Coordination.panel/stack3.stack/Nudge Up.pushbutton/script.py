# -*- coding: utf-8 -*-
"""RevoBIM PY - Nudge Up

Raise elements by the increment set in Nudge Settings (default 50 mm).

  - With elements already selected: they all rise by the increment, once per
    press. The selection is kept, so pressing again - or hitting the keyboard
    shortcut again - raises them again.
  - With nothing selected: every element you click rises immediately. Keeps
    asking until you press Escape.

Finishes silently.

SPEED
This button sits on a keyboard shortcut and gets hammered, so it is written
to start as fast as it can:

  - it does NOT import pyrevit. That package pulls in a large dependency tree
    on every single press and none of it is needed here - the document is
    reached through __revit__ directly.
  - __persistentengine__ keeps the IronPython engine alive between presses
    instead of building and tearing one down every time.

Between them, that is where nearly all of the old pause was. If the engine
ever needs rebuilding, comment out the __persistentengine__ line.
"""

__title__ = 'Nudge Up'
__author__ = 'RevoBIM PY'
__doc__ = ('Raise elements by the Nudge increment.\n\n'
           'Select first to raise a set, or run with nothing selected and '
           'click elements one at a time. Escape ends the loop.\n'
           'Set the increment with Nudge Settings.')

# Keep the engine warm between presses. This tool holds no state, no window
# and no event handlers, so there is nothing to leak from one run to the next.
__persistentengine__ = True

from revobim import nudge

nudge.run(__revit__.ActiveUIDocument, up=True)
