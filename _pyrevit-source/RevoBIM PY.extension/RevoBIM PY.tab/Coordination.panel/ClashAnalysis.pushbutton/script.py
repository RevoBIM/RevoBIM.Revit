# -*- coding: utf-8 -*-
"""Clash Analysis - compare categories and families in the host and linked
models for clashes, save clash tests to run again, place a clash family at
each intersection, group them as CLASH-<date>-<test> and review the groups.

Thin loader: every import that can fail happens inside a stage, so a failure
arrives as a dialog naming the stage instead of a blank pyRevit window.
"""
__title__ = "Clash Analysis"
__author__ = "RevoBIM"
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def report(stage, detail):
    text = u'Clash Analysis stopped while {0}.\n\n{1}'.format(stage, detail)
    try:
        folder = os.path.join(os.environ.get('APPDATA', HERE), 'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(os.path.join(folder, 'clash_analysis_last_error.txt'), 'w') as fh:
            fh.write(text.encode('utf-8') if sys.version_info[0] < 3 else text)
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('RevoBIM Clash Analysis', text)
    except Exception:
        pass


def main():
    stage = 'referencing assemblies'
    try:
        import ca_clr  # noqa: F401
        stage = 'loading the modules'
        import ca_ui
        stage = 'checking for an open window'
        if ca_ui.bring_back():
            return
        stage = 'reading the project'
        win = ca_ui.create(__revit__)  # noqa: F821  (pyRevit global)
        stage = 'showing the window'
        win.show()
    except Exception:
        report(stage, traceback.format_exc())


main()
