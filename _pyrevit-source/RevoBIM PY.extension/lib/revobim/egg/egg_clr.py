# -*- coding: utf-8 -*-
"""Assembly references for the easter egg.

Every other module in this package imports this one BEFORE it touches any
System.* name. An IronPython engine can only see a .NET namespace once
clr.AddReference has been called for the assembly holding it, and pyRevit does
not preload WPF into every engine.

RevitAPI and RevitAPIUI are deliberately absent: re-referencing them causes
access violations. The egg never touches the Revit API.
"""

import clr

REFERENCED = []
MISSING = []


def _ref(name):
    try:
        clr.AddReference(name)
        REFERENCED.append(name)
    except Exception:
        MISSING.append(name)


for _name in ("PresentationCore",
              "PresentationFramework",
              "WindowsBase",
              "System",
              "System.Xml",
              "System.Windows.Forms",
              "System.Drawing"):
    _ref(_name)

del _name
