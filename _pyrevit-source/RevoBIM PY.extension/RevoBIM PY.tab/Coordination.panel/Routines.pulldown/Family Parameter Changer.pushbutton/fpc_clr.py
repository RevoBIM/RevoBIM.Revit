# -*- coding: utf-8 -*-
"""RevoBIM PY - Family Parameter Changer.

Every clr.AddReference call for this tool lives here, and only here. Every
other module in this pushbutton folder imports fpc_clr FIRST, before it
touches any System.* or Autodesk.* name - so the assembly is guaranteed to
be referenced before its namespace is asked for. This module must stay
self-contained (no imports from the rest of the tool).

Each reference is requested individually inside its own try/except so a
name missing on a given Revit release is skipped rather than killing the
whole tool at import time.
"""
import clr


def _ref(name):
    try:
        clr.AddReference(name)
        return True
    except Exception:
        return False


_ref('PresentationCore')
_ref('PresentationFramework')
_ref('WindowsBase')
_ref('System.Xml')
_ref('System.Xaml')
_ref('System.Windows.Forms')
_ref('System.Drawing')
_ref('RevitAPI')
_ref('RevitAPIUI')
