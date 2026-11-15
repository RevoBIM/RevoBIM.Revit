# -*- coding: utf-8 -*-
"""Every clr.AddReference the tool needs, in one place.

Every other module imports this FIRST, before any System.* or Autodesk.* line.
An IronPython engine can only see a .NET namespace once the assembly holding it
has been referenced, and pyRevit does not preload WPF into every engine. That is
the single most likely way to break a tool in this extension and the least
obvious to diagnose: it shows up as a blank white pyRevit window with no
traceback in it.

RevitAPI and RevitAPIUI are deliberately not referenced - pyRevit handles those.

Under plain CPython (the bench) there is no clr at all, so the whole thing is a
no-op and the modules still import.
"""

LOADED = []
FAILED = []

try:
    import clr
except ImportError:
    clr = None

_ASSEMBLIES = [
    "PresentationCore",
    "PresentationFramework",
    "WindowsBase",
    "System.Xaml",
    "System.Xml",
    "System.Core",
    "System",
    "System.Drawing",
    "System.Windows.Forms",
    "UIAutomationProvider",
    "UIAutomationTypes",
    # the Excel round trip is written straight out as Office Open XML into a
    # zip - no Excel, no installed package
    "System.IO.Compression",
    "System.IO.Compression.FileSystem",
]

if clr is not None:
    for _name in _ASSEMBLIES:
        try:
            clr.AddReference(_name)
            LOADED.append(_name)
        except Exception:
            # A name that does not exist on a given release is skipped rather
            # than throwing. .NET 8 (Revit 2025+) does not carry all of them.
            FAILED.append(_name)


def report():
    """What loaded and what did not - used by the staged loader on failure."""
    return "loaded: {0}\nnot available: {1}".format(
        ", ".join(LOADED) or "-", ", ".join(FAILED) or "-")
