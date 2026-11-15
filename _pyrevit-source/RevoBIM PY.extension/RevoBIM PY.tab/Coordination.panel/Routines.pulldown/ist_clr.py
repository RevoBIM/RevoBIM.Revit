# -*- coding: utf-8 -*-
u"""RevoBIM PY - Isolate Service Type.

Every clr.AddReference the tool needs, in one module that every other module
imports FIRST, ahead of any System.* or Autodesk.* line.  An IronPython engine
can only see a .NET namespace once its assembly has been referenced, and
pyRevit does not preload WPF into every engine - a module that opens with
"from System.Windows import ..." before anything referenced
PresentationFramework throws ImportError at module load, which shows up in
Revit as a blank white pyRevit window with no traceback in it.

Each reference is asked for on its own inside a try/except, so a name that does
not exist on a given release is skipped rather than taking the tool down.
"""

import clr

_ASSEMBLIES = (
    u"RevitAPI",
    u"RevitAPIUI",
    u"System",
    u"System.Core",
    u"System.Xml",
    u"System.Xaml",
    u"WindowsBase",
    u"PresentationCore",
    u"PresentationFramework",
    u"System.Drawing",
)

LOADED = []
MISSING = []

for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        MISSING.append(_name)
