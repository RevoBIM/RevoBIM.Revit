# -*- coding: utf-8 -*-
"""Clash Analysis - every clr.AddReference the tool needs.

Imported first by every module that touches System.* or Autodesk.*.
Each assembly is requested on its own so a name missing on one Revit
release (4.8 on 2024, .NET 8 on 2025+) is skipped instead of taking the
rest of the list with it. RevitAPI / RevitAPIUI are already loaded by
pyRevit and are not referenced here.
"""
import clr

_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Data', 'System.Data.Common',
    'System.Xml', 'System.Xaml', 'System.Drawing', 'System.Windows.Forms',
    'System.ObjectModel', 'System.ComponentModel.Primitives',
    'System.ComponentModel.TypeConverter',
    'PresentationFramework', 'PresentationCore', 'WindowsBase',
]

LOADED = []
MISSING = []

for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        MISSING.append(_name)
