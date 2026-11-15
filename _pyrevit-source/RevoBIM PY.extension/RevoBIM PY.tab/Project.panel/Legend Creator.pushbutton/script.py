# -*- coding: utf-8 -*-
"""Legend Creator - RevoBIM PY

Builds legend views from the model. Family Legend lists the family types
placed in the project, one legend per category or all combined. System
Colour Legend builds Containment, Ductwork and Pipework colour keys from
filter and system overrides.

This file only loads the tool, in stages, and says which stage failed. The
tool itself is the lgc_*.py modules beside it; the version is in lgc_core.
"""

__title__ = 'Legend Creator'
__author__ = 'RevoBIM PY'
__doc__ = ('Creates legends of the family types placed in the model, and '
           'colour keys for containment, ductwork and pipework.')

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _report(stage):
    """Show what failed, and where. The full debug report when the tool got
    far enough to load it; a plain alert with the traceback when it did not."""
    text = traceback.format_exc()
    try:
        import lgc_report
        lgc_report.report_crash(stage)
        return
    except SystemExit:
        raise
    except Exception:
        text += u'\n\nThe debug report could not load either:\n' + \
            traceback.format_exc()
    from pyrevit import forms
    forms.alert(u'Legend Creator could not {0}.\n\n{1}'.format(
        stage, text[-2500:]), title='RevoBIM - Legend Creator')


if __name__ == '__main__':
    stage = 'reference its .NET assemblies'
    try:
        import lgc_clr                      # noqa: F401 - must come first
        stage = 'load its modules'
        import lgc_app
        stage = 'run'
        lgc_app.main()
    except SystemExit:
        raise                               # pyRevit's normal way out
    except Exception:
        _report(stage)
