# -*- coding: utf-8 -*-
"""Assembly references for Family Viewer.

Every other module in this tool imports this one FIRST, before it touches any
System.* or Autodesk.* name.

An IronPython engine can only see a .NET namespace once clr.AddReference has
been called for the assembly holding it, and pyRevit does not preload WPF into
every engine.  A module that opens with "from System.Windows import ..." before
anything has referenced PresentationFramework throws ImportError at module
load, which is the blank white pyRevit window with no traceback in it.

Each reference is asked for on its own inside a try/except, so a name that does
not exist on a given Revit release is skipped rather than taking the tool down.
Revit 2024 is .NET Framework 4.8; 2025 and later are .NET 8, and the set of
assemblies present is not identical.
"""

import clr

LOADED = []
MISSING = []

_ASSEMBLIES = [
    'PresentationFramework',
    'PresentationCore',
    'WindowsBase',
    'System.Xaml',
    'System.Xml',
    'System.Drawing',
    'System.Windows.Forms',
    # the Excel export writes OOXML straight into a zip.  On .NET Framework 4.8
    # (Revit 2024) ZipArchive lives in System.IO.Compression and the file
    # helpers in System.IO.Compression.FileSystem; on .NET 8 (2025+) both are in
    # the shared framework.  Asked for separately so a release that has only one
    # of them still gets it.
    'System.IO.Compression',
    'System.IO.Compression.FileSystem',
    'UIAutomationClient',
    'UIAutomationTypes',
    'RevitAPI',
    'RevitAPIUI',
]


def _reference(name):
    try:
        clr.AddReference(name)
        LOADED.append(name)
        return True
    except Exception:
        MISSING.append(name)
        return False


for _name in _ASSEMBLIES:
    _reference(_name)


def report():
    """Human readable note of what was referenced, for the staged loader."""
    parts = []
    parts.append('loaded: ' + ', '.join(LOADED))
    if MISSING:
        parts.append('not available: ' + ', '.join(MISSING))
    return '\n'.join(parts)


def have(name):
    return name in LOADED
