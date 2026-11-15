# -*- coding: utf-8 -*-
"""Unhide in View - every clr.AddReference the tool needs, in one place.

Imported FIRST by every module that touches .NET. pyRevit does not preload
WPF into every engine, so a module reaching into System.Windows before this
has run dies at load with an ImportError and a blank white window.
RevitAPI / RevitAPIUI are already loaded by pyRevit and are not referenced
here (house rule).
"""
import clr

ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Data', 'System.Xml',
    'System.Xaml', 'System.Drawing', 'System.Windows.Forms',
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
