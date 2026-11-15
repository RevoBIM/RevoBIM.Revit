# -*- coding: utf-8 -*-
"""Selected in View - tick the categories your next selection keeps.

Modeless: Revit stays usable while it is open. Closing it puts selection
back to normal. Loader only - the work lives in the siv_* modules.
"""
__title__ = 'Selected in View'
__persistentengine__ = True

import io
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _fail(stage, detail):
    text = u'Selected in View could not start at stage "{0}".\n\n{1}'.format(stage, detail)
    try:
        folder = os.path.join(os.environ.get('APPDATA') or HERE, 'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with io.open(os.path.join(folder, 'selected_in_view_error.txt'), 'w', encoding='utf-8') as fh:
            fh.write(text)
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('RevoBIM Selected in View', text)
    except Exception:
        pass


_stage = 'assemblies'
try:
    import siv_clr  # noqa: F401
    _stage = 'modules'
    import siv_core  # noqa: F401
    import siv_window
    _stage = 'window'
    siv_window.launch(__revit__, HERE)  # noqa: F821
except Exception:
    _fail(_stage, traceback.format_exc())
