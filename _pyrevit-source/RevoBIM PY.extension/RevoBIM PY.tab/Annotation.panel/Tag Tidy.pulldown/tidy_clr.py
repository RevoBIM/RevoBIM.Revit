# -*- coding: utf-8 -*-
"""Every clr.AddReference Tag Tidy needs, in one place.

An IronPython engine can only see a .NET namespace once the assembly holding it
has been referenced, and pyRevit does not preload WPF into every engine.  Every
other module in this tool imports this one before it touches any System.* or
Autodesk.* name.  Each reference is requested on its own inside a try/except so
a name that does not exist on a given Revit release (Revit 2024 is .NET
Framework 4.8, 2025 and later are .NET 8) is skipped rather than taking the
whole tool down.

Reference the assembly you need by name, every time: a namespace reached
through another assembly's dependencies works until the day it does not.
"""

import clr

_ASSEMBLIES = (
    "mscorlib",
    "System",
    "System.Core",
    "System.Xml",
    "System.Xaml",
    "System.Drawing",
    "System.Windows.Forms",
    "System.Diagnostics.Process",      # Process on .NET 8 (System.dll on 4.8)
    "PresentationCore",
    "PresentationFramework",
    "WindowsBase",
)

# RevitAPI and RevitAPIUI are deliberately absent: pyRevit hands every engine
# the Revit assemblies of the running release, and referencing them by name
# is a RevoBIM PY rule against.

LOADED = []
MISSING = []

for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        MISSING.append(_name)


def report():
    """Which assemblies were referenced, for the staged loader's error text."""
    return "loaded: {0}\nmissing: {1}".format(
        ", ".join(LOADED) or "none", ", ".join(MISSING) or "none")
