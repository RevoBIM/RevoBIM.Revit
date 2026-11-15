# -*- coding: utf-8 -*-
"""Schematic Marriage

Marry a model element to another element (a detail item on a schematic, for
instance), keep the marriages in the model, and push parameter values from
each source to its target through Parameter Push Templates.
"""
__title__ = "Schematic Marriage"   # single line - findable in Keyboard Shortcuts
__author__ = "RevoBIM"
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    from sm_version import __version__
except Exception:
    __version__ = "?"

__doc__ = ("Schematic Marriage v{0} - marry a source element to a target (model element or "
           "detail item), store the pairs in the model and push parameter values through "
           "Parameter Push Templates.").format(__version__)


def _report(stage, text):
    """A failure arrives as a dialog naming the stage, and is written to disk,
    never as a blank window."""
    try:
        folder = os.path.join(os.environ.get('APPDATA') or HERE, 'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(os.path.join(folder, 'schematic_marriage_last_error.txt'), 'w') as fh:
            fh.write('Schematic Marriage v{0}\nStage: {1}\n\n{2}'.format(__version__, stage, text))
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('RevoBIM Schematic Marriage',
                        'Stopped at stage: {0}\n\n{1}'.format(stage, text[-1800:]))
    except Exception:
        pass


def _main():
    stage = 'assemblies'
    try:
        import sm_clr  # noqa: F401
        stage = 'modules'
        import sm_ui
        stage = 'reading the model'
        uiapp = __revit__  # noqa: F821  (pyRevit global)
        if uiapp.ActiveUIDocument is None:
            from Autodesk.Revit.UI import TaskDialog
            TaskDialog.Show('RevoBIM Schematic Marriage', 'Open a model first.')
            return
        stage = 'showing the window'
        sm_ui.launch(uiapp)
    except Exception:
        _report(stage, traceback.format_exc())


_main()
