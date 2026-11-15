# -*- coding: utf-8 -*-
"""Find in View - assembly references.

Every other module in this tool imports this module BEFORE it touches any
System.* or Autodesk.* name.  An IronPython engine can only see a .NET
namespace once clr.AddReference has been called for the assembly holding it,
and pyRevit does not preload WPF into every engine.  A module that opens with

    from System.Windows import FontWeights

before anything has referenced PresentationFramework throws ImportError at
module load - which is the blank white pyRevit window with no traceback in it.

Each reference is requested on its own inside a try/except, so a name that does
not exist on a given Revit release is skipped rather than taking the tool down.
"""

import clr

_ASSEMBLIES = [
    'PresentationFramework',
    'PresentationCore',
    'WindowsBase',
    'System.Xaml',
    'System.Xml',
    'System.Core',
    'System',
    'System.Drawing',
    'WindowsFormsIntegration',
    'RevitAPI',
    'RevitAPIUI',
]

LOADED = []
FAILED = []

for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        FAILED.append(_name)


def report():
    """Text description of what was referenced, for the staged loader."""
    return 'referenced: {0}{1}'.format(
        ', '.join(LOADED),
        '' if not FAILED else '  |  unavailable: ' + ', '.join(FAILED))
