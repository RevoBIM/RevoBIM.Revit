# -*- coding: utf-8 -*-
"""Every clr.AddReference the tool needs, in one place.

An IronPython engine can only see a .NET namespace once the assembly holding it
has been referenced, and pyRevit does not preload WPF into every engine.  Every
other module in this tool imports this one before it touches any System.* or
Autodesk.* name.  Each reference is requested on its own inside a try/except so
a name that does not exist on a given Revit release is skipped rather than
taking the whole tool down.
"""

import clr

_ASSEMBLIES = (
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
)

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
