# -*- coding: utf-8 -*-
"""Schematic Marriage - every clr.AddReference lives here.

Imported FIRST by every module that touches System.* or Autodesk.*, so a
namespace always exists before anything imports from it. Each assembly is
requested on its own inside try/except, so a name missing on one Revit
release is skipped rather than killing the load. RevitAPI / RevitAPIUI are
preloaded by pyRevit and deliberately not referenced here.
"""
import clr

ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Xml', 'System.Xaml',
    'System.Drawing', 'System.Windows.Forms',
    'PresentationFramework', 'PresentationCore', 'WindowsBase',
]

LOADED = []
MISSING = []

for _name in ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        MISSING.append(_name)
