# -*- coding: utf-8 -*-
"""Family Param Push: map a family's parameters to others and push the values.
Thin staged loader: a failure names its stage instead of a blank window."""
__title__ = 'Family Param Push'
__author__ = 'RevoBIM'
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def report(stage, text):
    message = u'Family Param Push failed while {0}.\n\n{1}'.format(stage, text)
    try:
        folder = os.path.join(os.environ.get('APPDATA', HERE), 'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        path = os.path.join(folder, 'family_param_push_last_error.txt')
        with open(path, 'w') as handle:
            handle.write(message.encode('utf-8') if str is bytes else message)
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('Family Param Push', message[:1800])
    except Exception:
        pass


def run():
    stage = 'loading its modules'
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        for name in list(sys.modules):
            if name.startswith('fpp_'):
                del sys.modules[name]
        import fpp_clr  # noqa: F401
        import fpp_app
        stage = 'opening the window'
        fpp_app.launch(__revit__)  # noqa: F821
    except Exception:
        report(stage, traceback.format_exc())


run()
