# -*- coding: utf-8 -*-
u"""Hanger Automation - thin staged loader.

The version lives in fha_core.__version__ and shows top right of the window.
Stages: assemblies, modules, window.  A failure names its stage, shows the
traceback and writes it to %APPDATA%\\RevoBIM\\, so there is never a blank window.
"""
__author__ = u'RevoBIM'
__persistentengine__ = True

import io
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_stage = u'assemblies'


def _report(stage, text):
    msg = u'Failed at stage: {0}\n\n{1}'.format(stage, text)
    try:
        folder = os.path.join(os.environ.get('APPDATA') or _HERE, 'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with io.open(os.path.join(folder, 'hanger_automation_load_error.txt'), 'w', encoding='utf-8') as f:
            f.write(msg)
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(u'Hanger Automation', msg)
    except Exception:
        pass


try:
    import fha_clr
    _stage = u'modules'
    import fha_core
    import fha_revit
    import fha_ui
    import hfam_core
    import hfam_revit
    import hcirc_core
    import hcirc_revit
    import hfam_ui
    import fha_window
    _stage = u'window'
    fha_window.show(__revit__)
except Exception:
    _report(_stage, traceback.format_exc())
