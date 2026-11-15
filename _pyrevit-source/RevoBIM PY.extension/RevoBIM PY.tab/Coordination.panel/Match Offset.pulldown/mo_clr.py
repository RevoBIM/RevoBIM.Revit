# -*- coding: utf-8 -*-
"""RevoBIM Match Offset - every clr.AddReference the tool needs.

Imported first by every other module in this tool, ahead of any System.* or
Autodesk.* line. An IronPython engine can only see a .NET namespace once the
assembly holding it has been referenced, and pyRevit does not preload WPF into
every engine. A module that opens with "from System.Windows import ..." before
anything has referenced PresentationFramework throws ImportError at module
load, which shows up as a blank white pyRevit window with no traceback in it.

RevitAPI and RevitAPIUI are deliberately absent: pyRevit has already loaded
them into the engine, and referencing them again is the one AddReference that
can fail on a release where the assembly has moved.
"""

ASSEMBLIES = (
    'PresentationCore',
    'PresentationFramework',
    'WindowsBase',
    'System.Xaml',
    'System.Xml',
    'System.Windows.Forms',
    'System.Core',
)

LOADED = []
MISSING = []

try:
    import clr
except Exception:  # pragma: no cover - only under plain CPython on the bench
    clr = None

if clr is not None:
    for _name in ASSEMBLIES:
        try:
            clr.AddReference(_name)
            LOADED.append(_name)
        except Exception:
            MISSING.append(_name)


def report():
    """One line naming what could not be referenced, or an empty string."""
    if not MISSING:
        return u""
    return u"Assemblies not referenced: {0}".format(u", ".join(MISSING))
