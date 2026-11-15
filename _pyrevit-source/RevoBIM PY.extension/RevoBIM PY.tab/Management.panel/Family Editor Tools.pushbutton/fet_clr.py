# =========================================================================
# Family Editor Tools - assembly references
# Every other module imports this one FIRST, before any System.* or
# Autodesk.* name is touched.  An IronPython engine can only see a .NET
# namespace once clr.AddReference has been called for the assembly holding
# it, and pyRevit does not preload WPF into every engine.
# =========================================================================

import clr

_ASSEMBLIES = (
    u"PresentationCore",
    u"PresentationFramework",
    u"WindowsBase",
    u"System.Xaml",
    u"System.Xml",
    u"System.Drawing",
    u"System.Windows.Forms",
    u"System.Core",
    u"System",
    u"RevitAPI",
    u"RevitAPIUI",
    u"AdWindows",
)

REFERENCED = []
MISSING = []

for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        REFERENCED.append(_name)
    except Exception:
        MISSING.append(_name)


def referenced(name):
    u"""True when the named assembly was referenced successfully."""
    return name in REFERENCED
