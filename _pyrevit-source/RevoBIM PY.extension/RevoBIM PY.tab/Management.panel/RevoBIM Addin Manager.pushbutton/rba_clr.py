# -*- coding: utf-8 -*-
u"""RevoBIM Addins - assembly references.

Imported FIRST by every other module in this tool, before any System.* or
Autodesk.* name is touched.  An IronPython engine can only see a .NET
namespace once clr.AddReference has been called for the assembly holding it,
and pyRevit does not preload WPF into every engine.  A module that opens with
"from System.Windows import ..." before anything referenced
PresentationFramework throws ImportError at module load, which is the blank
white pyRevit window with no traceback in it.

RevitAPI and RevitAPIUI are deliberately NOT referenced here - pyRevit loads
them into every engine already, and referencing them again has caused version
mismatches across Revit 2024-2027.
"""

import clr

ASSEMBLIES = (
    u"System",
    u"PresentationFramework",
    u"PresentationCore",
    u"WindowsBase",
    u"System.Xaml",
    u"System.Xml",
    u"System.Core",
    u"System.Drawing",
    u"System.Windows.Forms",
    u"AdWindows",
    u"UIFramework",
)

LOADED = []
MISSING = []

for _name in ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        # Requested individually so a name that does not exist on a given
        # release is skipped rather than throwing.
        MISSING.append(_name)
