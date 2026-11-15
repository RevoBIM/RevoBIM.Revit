# -*- coding: utf-8 -*-
"""Assembly references for Fire Damper Wall Type Push.

EVERY other module in this tool imports this module FIRST, before any
System.* or Autodesk.* line.  An IronPython engine can only see a .NET
namespace once clr.AddReference has been called for the assembly holding
it, and pyRevit does not preload WPF into every engine.  A module that
opens with "from System.Windows import ..." before anything referenced
PresentationFramework throws ImportError at module load - which shows up
in Revit as a blank white pyRevit window with no traceback.

Import order inside a file is load order, so this reference has to win.
"""

import clr

# Each one on its own, inside try/except, so a name that does not exist on
# a given Revit release is skipped rather than taking the tool down.
for _asm in (
    "PresentationCore",
    "PresentationFramework",
    "WindowsBase",
    "System.Xaml",
    "System.Xml",
    "System",
    "System.Core",
    "RevitAPI",
    "RevitAPIUI",
):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

REFERENCED = True
