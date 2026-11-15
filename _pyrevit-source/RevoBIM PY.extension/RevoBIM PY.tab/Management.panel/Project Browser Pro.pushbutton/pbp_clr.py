# -*- coding: utf-8 -*-
u"""Project Browser Pro - every clr.AddReference the tool needs.

Imported first by every module that touches System.* or Autodesk.*, ahead of
any such line: import order inside a file is load order, and the reference
has to win. pyRevit does not preload WPF into every engine (the startup
engine above all), and System.Data, System.Xml and the WPF assemblies are
separate from System.

RevitAPI and RevitAPIUI are already loaded by pyRevit and are not referenced
here. Each name is requested on its own inside try/except, so one a release
does not have (System.Diagnostics.Process only exists as its own assembly on
.NET 8, AdWindows could in theory move) is skipped rather than stopping the
tool.
"""
import clr

_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Data', 'System.Xml',
    'System.Xaml', 'PresentationFramework', 'PresentationCore', 'WindowsBase',
    'System.Diagnostics.Process', 'System.Drawing', 'System.Windows.Forms',
    'AdWindows',
]

LOADED = []
MISSING = []

for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        MISSING.append(_name)
