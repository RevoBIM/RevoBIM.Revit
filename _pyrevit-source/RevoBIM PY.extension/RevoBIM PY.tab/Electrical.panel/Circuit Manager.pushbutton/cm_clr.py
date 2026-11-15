# -*- coding: utf-8 -*-
"""Every clr.AddReference for Circuit Manager.

Imported first by every module that touches System.* or Autodesk.*.
Each assembly is requested on its own, so a name that does not exist on a
given Revit release (4.8 on 2024, .NET 8 on 2025+) is skipped rather than
taking the rest of the list with it. RevitAPI / RevitAPIUI are already
loaded by pyRevit and are deliberately not referenced here.
"""
import clr

_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Data', 'System.Data.Common',
    'System.Xml', 'System.Xaml', 'System.Drawing', 'System.Windows.Forms',
    'PresentationFramework', 'PresentationCore', 'WindowsBase',
    'System.ObjectModel', 'System.ComponentModel.Primitives',
    'System.ComponentModel.TypeConverter', 'System.Collections',
    'System.Runtime', 'System.Threading',
]

LOADED = []
SKIPPED = []

for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        SKIPPED.append(_name)
