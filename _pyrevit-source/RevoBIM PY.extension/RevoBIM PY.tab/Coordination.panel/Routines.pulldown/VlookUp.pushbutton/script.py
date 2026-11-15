# -*- coding: utf-8 -*-
"""RevoBIM VlookUp - match Revit elements to spreadsheet rows and write the
mapped columns into the parameters you choose.

Everything the tool needs lives in this pushbutton folder, which is added to
sys.path so the shared modules import without touching lib\\revobim.
"""

__title__ = "VlookUp"
__author__ = "RevoBIM"
__doc__ = ("Look a parameter value up in a spreadsheet and write the matching "
           "row's columns into the parameters you choose.")

import clr
import os
import sys
import traceback

for _asm in ('RevitAPI', 'RevitAPIUI'):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _report(title, message):
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(title, message)
    except Exception:
        pass


def main():
    try:
        import vlookup_core as core
        from vlookup_window import VlookUpWindow
    except Exception:
        _report('RevoBIM VlookUp',
                'VlookUp could not load its modules.\n\n' + traceback.format_exc())
        return
    try:
        uiapp = __revit__                       # noqa: F821  (injected by pyRevit)
        uidoc = uiapp.ActiveUIDocument
        if uidoc is None or uidoc.Document is None:
            _report('RevoBIM VlookUp', 'Open a project before running VlookUp.')
            return
        if uidoc.Document.IsFamilyDocument:
            _report('RevoBIM VlookUp',
                    'VlookUp works in a project, not in the family editor.')
            return
        VlookUpWindow(uidoc.Document, uidoc, core.__version__).show()
    except Exception:
        _report('RevoBIM VlookUp', 'VlookUp stopped.\n\n' + traceback.format_exc())


main()
