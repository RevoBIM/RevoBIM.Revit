# -*- coding: utf-8 -*-
"""RevoBIM PY - Family Find & Replace.

Swaps one loadable family for another across the model, keeping the insertion
point, the chosen instance parameters and the electrical circuits.
"""

__title__ = "Family Find & Replace"
__author__ = "RevoBIM"
__version__ = "1.7.0"
__doc__ = ("Swap one family for another across the model. Keeps the insertion "
           "point, the instance parameters you choose and the electrical "
           "circuits, and turns a face based family into one that is not.")
__persistentengine__ = True

import os
import sys
import traceback

import clr

clr.AddReference('RevitAPIUI')

from Autodesk.Revit.UI import TaskDialog

FOLDER = os.path.dirname(os.path.abspath(__file__))
if FOLDER not in sys.path:
    sys.path.append(FOLDER)


def fatal(heading, detail):
    """A blank white pyRevit window is almost always a failed import.

    Rather than let that happen, everything is caught here and shown with the
    traceback still readable.
    """
    try:
        dialog = TaskDialog('RevoBIM - Family Find & Replace')
        dialog.MainInstruction = heading
        dialog.MainContent = detail
        dialog.Show()
    except Exception:
        pass


def main():
    try:
        uiapp = __revit__
    except NameError:
        try:
            from pyrevit import HOST_APP
            uiapp = HOST_APP.uiapp
        except Exception:
            fatal('Revit could not be reached.', traceback.format_exc())
            return

    try:
        if uiapp.ActiveUIDocument is None or \
                uiapp.ActiveUIDocument.Document is None:
            fatal('No project is open.',
                  'Open the model you want to work in and run the tool again.')
            return
    except Exception:
        fatal('No project is open.', traceback.format_exc())
        return

    try:
        import ffr_ui
    except Exception:
        fatal('The tool could not load.',
              'An import failed before the window was built.\n\n' +
              traceback.format_exc())
        return

    try:
        ffr_ui.launch(uiapp, FOLDER, __version__)
    except Exception:
        fatal('The tool could not start.', traceback.format_exc())


if __name__ != '__ffr_bench__':
    main()
