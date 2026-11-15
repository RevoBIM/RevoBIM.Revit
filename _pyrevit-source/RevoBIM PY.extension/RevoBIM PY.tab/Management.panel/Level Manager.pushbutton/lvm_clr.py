# -*- coding: utf-8 -*-
"""Level Manager - every clr.AddReference, in one place.

Imported first by every other module in the tool, ahead of any System.* or
Autodesk.* import, so each namespace exists before it is asked for. RevitAPI
and RevitAPIUI are already loaded by pyRevit and are not referenced here.
"""
import clr

_ASSEMBLIES = [
    "mscorlib", "System", "System.Core", "System.Data", "System.Xml",
    "System.Xaml", "System.Drawing", "System.Windows.Forms",
    "PresentationFramework", "PresentationCore", "WindowsBase",
]

LOADED = []
MISSING = []

for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        MISSING.append(_name)
