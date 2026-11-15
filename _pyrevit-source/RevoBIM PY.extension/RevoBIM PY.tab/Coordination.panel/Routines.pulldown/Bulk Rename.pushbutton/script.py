# -*- coding: utf-8 -*-
"""Find and replace, add a prefix or add a suffix across the items selected in
the Project Browser, with a live preview. Nothing is written until Apply."""
import os
import sys
import traceback

__title__ = 'Bulk Rename'
__author__ = 'RevoBIM'
__persistentengine__ = True

FOLDER = os.path.dirname(os.path.abspath(__file__))


def report(stage):
    text = u'Bulk Rename stopped at: {0}\n\n{1}'.format(stage, traceback.format_exc())
    try:
        root = os.path.join(os.environ.get('APPDATA', FOLDER), 'RevoBIM')
        if not os.path.isdir(root):
            os.makedirs(root)
        with open(os.path.join(root, 'bulk_rename_last_error.txt'), 'w') as handle:
            handle.write(text.encode('ascii', 'replace').decode('ascii'))
    except Exception:
        pass
    from Autodesk.Revit.UI import TaskDialog
    TaskDialog.Show('Bulk Rename', text)


def main():
    if FOLDER not in sys.path:
        sys.path.insert(0, FOLDER)
    stage = 'assemblies'
    try:
        import brn_clr  # noqa: F401
        stage = 'modules'
        import brn_app
        stage = 'opening the window'
        brn_app.launch(__revit__)  # noqa: F821  pyRevit supplies it
    except Exception:
        report(stage)


main()
