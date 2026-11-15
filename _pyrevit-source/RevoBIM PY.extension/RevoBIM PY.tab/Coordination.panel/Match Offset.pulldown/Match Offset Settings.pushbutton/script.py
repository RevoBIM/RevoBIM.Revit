# -*- coding: utf-8 -*-
"""RevoBIM Match Offset Settings - thin loader."""

__title__ = "RevoBIM Match Offset Settings"
__doc__ = ("Rounding, what can be picked, how results are reported, and the "
           "keyboard shortcut mapping.")
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


_breadcrumb(u"RevoBIM Match Offset Settings: died importing mo_launch from "
            u"{0}".format(PULLDOWN))

try:
    import mo_launch
    mo_launch.launch_settings(__revit__)         # noqa: F821
except Exception:
    _breadcrumb(traceback.format_exc())
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("RevoBIM Match Offset",
                        "Could not start.\n\n" + traceback.format_exc())
    except Exception:
        pass
