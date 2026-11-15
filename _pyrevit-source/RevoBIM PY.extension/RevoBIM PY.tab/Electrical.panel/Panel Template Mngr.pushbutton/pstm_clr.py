# -*- coding: utf-8 -*-
"""RevoBIM PY - assembly references.  Import this FIRST, everywhere.

An IronPython engine can only see a .NET namespace once the assembly holding it
has been referenced.  pyRevit does not preload WPF into every engine, so a
module that starts with

    from System.Windows import FontWeights

before anything has referenced PresentationFramework throws ImportError at
module load - and a module that will not load is the blank white pyRevit
window, with no traceback to say why.

So every module in this tool imports `pstm_clr` as its first import, ahead of
any `from System...` or `from Autodesk...` line.  Import order inside a module
is load order, and this has to win.

Each reference is requested individually inside try/except, so a name that does
not exist on a given release is skipped rather than throwing.  Revit 2024 is
.NET Framework 4.8 and 2025 onwards are .NET 8, and the two do not carry the
same set.

Runs on IronPython 2.7 and IronPython 3: no f-strings, no print statements.
"""

import clr

# WPF, then Windows Forms (Screen, for the full screen bounds), then the Revit
# API itself.  RevitAPI and RevitAPIUI are normally already loaded by pyRevit,
# but asking again costs nothing and covers an engine where they are not.
ASSEMBLIES = (
    'PresentationFramework',
    'PresentationCore',
    'WindowsBase',
    'System.Xaml',
    'System.Xml',
    'System.Core',
    'System.Windows.Forms',
    'System.Drawing',
    'RevitAPI',
    'RevitAPIUI',
)

LOADED = []
MISSING = []

for _name in ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        MISSING.append(_name)


def report():
    """What could and could not be referenced, for a diagnostic message."""
    return 'referenced: {0}\nnot available: {1}'.format(
        ', '.join(LOADED) or 'none',
        ', '.join(MISSING) or 'none')
