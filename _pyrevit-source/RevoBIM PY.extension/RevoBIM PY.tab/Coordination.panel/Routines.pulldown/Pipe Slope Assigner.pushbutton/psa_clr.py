# -*- coding: utf-8 -*-
"""Every assembly reference the tool needs, in one place.

Imported first by every other module, ahead of any System.* or Autodesk.* line.
An IronPython engine can only see a .NET namespace once its assembly has been
referenced, and pyRevit does not preload WPF into every engine - a module that
reaches into System.Windows before this has run dies at load, and that is the
blank white pyRevit window with no traceback in it.

Each assembly is asked for on its own inside try/except, so a name that does
not exist on a given release (Revit 2024 is .NET Framework 4.8, 2025 onwards
is .NET 8) is skipped rather than taking the tool down. RevitAPI and
RevitAPIUI are never referenced here - pyRevit has already done that.
"""

import clr

ASSEMBLIES = (
    'System',
    'System.Core',
    'System.Xml',
    'System.Xaml',
    'WindowsBase',
    'PresentationCore',
    'PresentationFramework',
    'System.Diagnostics.Process',
)

LOADED = []
FAILED = []

for _name in ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        FAILED.append(_name)
