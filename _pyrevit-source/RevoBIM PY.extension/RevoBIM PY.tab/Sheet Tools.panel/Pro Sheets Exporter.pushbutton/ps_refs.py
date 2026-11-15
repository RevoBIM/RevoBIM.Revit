# -*- coding: utf-8 -*-
"""Assembly references for Pro Sheets Exporter.

EVERY other module in this tool imports this one FIRST, before any
``System.*`` or ``Autodesk.*`` line. An IronPython engine can only see a .NET
namespace once ``clr.AddReference`` has been called for the assembly holding
it, and pyRevit does not preload WPF into every engine. Import order inside a
file is load order, so the reference has to win.

Each reference is requested on its own inside try/except, so a name that does
not exist on a given Revit release is skipped rather than throwing at load.

Nothing in here imports a namespace. It only references assemblies.
"""

import clr

# Every namespace this tool imports from has to have its assembly in this
# list. The rule is not "the big ones" - System.Data is a separate assembly
# from System, and "from System.Data import DataTable" throws
# "ImportError: No module named Data" without it. import_check has a rule
# that maps every import in the tool back to the assembly providing it and
# fails when one is not here.
_ASSEMBLIES = [
    'mscorlib',
    'System',
    'System.Core',
    'System.Data',
    # The Document Register's Excel file is a zip written by
    # ZipArchive, which is its own assembly on every framework.
    'System.IO.Compression',
    'System.Xml',
    'System.Xaml',
    'System.Drawing',
    'System.Windows.Forms',
    'PresentationFramework',
    'PresentationCore',
    'WindowsBase',
    'ReachFramework',
    'System.Printing',
    'RevitAPI',
    'RevitAPIUI',
]

REFERENCED = []
MISSING = []

for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        REFERENCED.append(_name)
    except Exception:
        MISSING.append(_name)


def referenced(name):
    """True when the named assembly was referenced successfully."""
    return name in REFERENCED


def report():
    """One line naming anything that could not be referenced, for diagnostics."""
    if not MISSING:
        return 'all assemblies referenced'
    return 'not referenced: ' + ', '.join(MISSING)
