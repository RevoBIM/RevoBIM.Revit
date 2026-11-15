# -*- coding: utf-8 -*-
"""Selected in View - every clr.AddReference the tool needs, in one place.

Every other module imports this first, ahead of any System.* or Autodesk.*
line, so each namespace's assembly is referenced before it is imported.
RevitAPI / RevitAPIUI are already loaded by pyRevit and are not referenced here.
"""
import clr

_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Xml', 'System.Xaml',
    'System.Drawing', 'System.Windows.Forms',
    'PresentationFramework', 'PresentationCore', 'WindowsBase',
]

LOADED = []
SKIPPED = []
for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        SKIPPED.append(_name)
