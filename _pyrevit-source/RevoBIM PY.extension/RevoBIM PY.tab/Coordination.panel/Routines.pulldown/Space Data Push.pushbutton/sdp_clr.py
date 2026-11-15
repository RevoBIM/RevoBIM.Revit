# -*- coding: utf-8 -*-
"""Every clr.AddReference for Space Data Push, in one place.

Every other module imports this FIRST, before any System.* or Autodesk.* line:
an IronPython engine can only see a .NET namespace once the assembly holding it
has been referenced, and pyRevit does not preload WPF into every engine.
RevitAPI and RevitAPIUI are not referenced here - pyRevit has already loaded them.
"""
import clr

_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Data', 'System.Xml',
    'System.Xaml', 'System.Drawing', 'System.Windows.Forms',
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
