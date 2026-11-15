# -*- coding: utf-8 -*-
"""RevoBIM Match Offset Bottom - thin loader.

Imports nothing that can fail except the launcher, which reports for itself.
A blank white pyRevit window means the script died before any of it ran, so
the breadcrumb is written before the import rather than after it.
"""

__title__ = "RevoBIM Match Offset Bottom"
__doc__ = ("Pick the element to take the bottom offset from, then pick "
           "elements to put on it. Escape finishes.")
__author__ = "RevoBIM"

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
PULLDOWN = os.path.dirname(HERE)
if PULLDOWN not in sys.path:
    sys.path.append(PULLDOWN)


def _breadcrumb(text):
    try:
        root = os.environ.get('APPDATA') or os.path.expanduser('~')
        folder = os.path.join(root, 'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(os.path.join(folder, 'match_offset_last_error.txt'),
                      'wb')
        try:
            handle.write(text.encode('utf-8'))
        finally:
            handle.close()
    except Exception:
        pass


_breadcrumb(u"RevoBIM Match Offset Bottom: died importing mo_launch from "
            u"{0}".format(PULLDOWN))

try:
    import mo_launch
    mo_launch.launch(__revit__, "bottom")      # noqa: F821
except Exception:
    _breadcrumb(traceback.format_exc())
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("RevoBIM Match Offset",
                        "Could not start.\n\n" + traceback.format_exc())
    except Exception:
        pass
