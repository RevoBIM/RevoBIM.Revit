# -*- coding: utf-8 -*-
"""Assembly references for Callout to 3D.

Every other module in this tool imports this one FIRST, ahead of any
``System.*`` or ``Autodesk.*`` line.  An IronPython engine can only see a .NET
namespace once ``clr.AddReference`` has been called for the assembly holding
it, and pyRevit does not preload WPF into every engine.  Import order inside a
file is load order, so the reference has to win.

Each assembly is requested on its own inside try/except, so a name that does
not exist on a given Revit release is skipped rather than throwing.
"""

import clr

ASSEMBLIES = [
    "RevitAPI",
    "RevitAPIUI",
    "PresentationCore",
    "PresentationFramework",
    "WindowsBase",
    "System.Xaml",
    "System.Xml",
    "System",
    "System.Core",
    "System.Drawing",
    "System.Windows.Forms",
]

LOADED = []
FAILED = []

for _name in ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception as _err:
        FAILED.append((_name, str(_err)))


def report():
    """One line per assembly that would not load, for the staged loader."""
    if not FAILED:
        return ""
    return "\n".join(["{0}: {1}".format(n, e) for (n, e) in FAILED])
