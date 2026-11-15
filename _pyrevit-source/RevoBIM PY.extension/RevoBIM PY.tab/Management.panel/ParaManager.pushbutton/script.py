# -*- coding: utf-8 -*-
"""ParaManager - project parameters, categories and shared parameter files."""
__title__ = "ParaManager"
__author__ = "RevoBIM"
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)


def report(stage):
    text = u'ParaManager failed at: {0}\n\n{1}'.format(stage, traceback.format_exc())
    try:
        folder = os.path.join(os.environ.get('APPDATA', HERE), 'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(os.path.join(folder, 'para_manager_last_error.txt'), 'w') as out:
            out.write(text.encode('utf-8') if str is bytes else text)
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('ParaManager', text[:1800])
    except Exception:
        pass


STAGE = 'loading assemblies'
try:
    import pm_clr
    STAGE = 'loading modules'
    import pm_main
    STAGE = 'opening the window'
    pm_main.launch(__revit__, HERE)
except Exception:
    report(STAGE)
