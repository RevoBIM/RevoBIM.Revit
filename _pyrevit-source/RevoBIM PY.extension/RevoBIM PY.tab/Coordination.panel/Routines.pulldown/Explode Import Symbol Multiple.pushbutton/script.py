# -*- coding: utf-8 -*-
"""Partial or Full Explode every selected import symbol in one go.

Select several imported CAD symbols, run the tool, pick Partial or Full.
Revit only explodes one import at a time, so the tool walks the selection
for you. Linked CAD is skipped (Revit cannot explode it).
"""
__title__ = 'Explode Import Symbol Multiple'
__author__ = 'RevoBIM'
__persistentengine__ = True

import io
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)


def _fail(stage, text):
    """Name the stage that failed rather than leave a blank window."""
    try:
        base = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'RevoBIM')
        if not os.path.isdir(base):
            os.makedirs(base)
        with io.open(os.path.join(base, 'explode_import_multiple_error.txt'), 'w', encoding='utf-8') as fh:
            fh.write(u'Stage: {0}\n\n{1}'.format(stage, text))
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(u'RevoBIM - Explode Import Symbol Multiple',
                        u'Failed while {0}.\n\n{1}'.format(stage, text[-1500:]))
    except Exception:
        pass


_ok = True
try:
    import eim_clr  # noqa: F401
except Exception:
    _ok = False
    _fail(u'loading assemblies', traceback.format_exc())

if _ok:
    try:
        import eim_app
    except Exception:
        _ok = False
        _fail(u'loading modules', traceback.format_exc())

if _ok:
    try:
        eim_app.main(__revit__)  # noqa: F821  (pyRevit supplies __revit__)
    except Exception:
        _fail(u'running', traceback.format_exc())
