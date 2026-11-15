# -*- coding: utf-8 -*-
"""Assembly references for Containment System Creator.

Every other module in the tool imports this one FIRST, ahead of any
``from System...`` line. IronPython only sees a .NET namespace once its
assembly has been referenced, and pyRevit does not preload WPF into every
engine.

Revit 2024 runs .NET Framework 4.8; 2025 and later run .NET 8, where several
core types live in different assemblies. Each name is requested on its own and
a name that does not exist on a given release is skipped rather than taking the
rest of the list with it.
"""

import clr

ASSEMBLIES = (
    "mscorlib",
    "System",
    "System.Core",
    "System.Runtime",
    "System.Private.Uri",
    "System.Xaml",
    "WindowsBase",
    "PresentationCore",
    "PresentationFramework",
    "System.Drawing",
    "System.Windows.Forms",
)

REFERENCED = []

for _name in ASSEMBLIES:
    try:
        clr.AddReference(_name)
        REFERENCED.append(_name)
    except Exception:
        pass
