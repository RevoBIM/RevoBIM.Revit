# -*- coding: utf-8 -*-
"""Every clr.AddReference for this tool, in one place.

Imported first by every other module in the tool, before any System.* or
Autodesk.* name is touched.  An IronPython engine can only see a .NET namespace
once the assembly holding it has been referenced, and pyRevit does not preload
WPF into every engine, so a module opening with a bare `from System.Windows
import ...` throws ImportError at module load - which shows up in Revit as a
blank white pyRevit window with no traceback in it.
"""

import clr

_ASSEMBLIES = [
    "PresentationCore",
    "PresentationFramework",
    "WindowsBase",
    "System.Xaml",
    "System.Xml",
    "System.Core",
    "System.Drawing",
    "System.Windows.Forms",
    "RevitAPI",
    "RevitAPIUI",
]

LOADED = []
FAILED = []

for _name in _ASSEMBLIES:
    # individually, so a name that does not exist on a given Revit release is
    # skipped rather than taking the whole tool down
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        FAILED.append(_name)


def report():
    """Readable summary for the staged loader in script.py."""
    txt = "loaded: " + ", ".join(LOADED)
    if FAILED:
        txt += "\nnot available: " + ", ".join(FAILED)
    return txt
