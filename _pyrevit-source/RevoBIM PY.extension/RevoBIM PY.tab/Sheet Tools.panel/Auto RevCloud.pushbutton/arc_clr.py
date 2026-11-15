# -*- coding: utf-8 -*-
"""Auto RevCloud - every clr.AddReference the tool needs, in one place.

Every other module imports this first, ahead of any System.* or Autodesk.*
line.  An IronPython engine can only see a .NET namespace once the assembly
holding it has been referenced, and pyRevit does not preload WPF into every
engine.  RevitAPI and RevitAPIUI are already loaded by pyRevit and are
deliberately not referenced here.
"""
import clr

ASSEMBLIES = (
    u"System",
    u"System.Core",
    u"System.Xml",
    u"System.Drawing",
    u"System.Xaml",
    u"System.Runtime",
    u"System.Collections",
    u"System.Windows.Forms",
    u"Microsoft.VisualBasic",
    u"Microsoft.VisualBasic.Core",
    u"PresentationCore",
    u"PresentationFramework",
    u"WindowsBase",
)

# Namespace prefix -> assembly that carries it.  The bench check reads this
# table and refuses any `from System.X import` whose assembly is not listed
# in ASSEMBLIES above.
ASSEMBLY_FOR = {
    u"System": u"System",
    u"System.IO": u"System",
    u"System.Text": u"System",
    u"System.Diagnostics": u"System",
    u"System.Collections": u"System",
    u"System.Collections.Generic": u"System",
    u"System.Runtime.InteropServices": u"System",
    u"System.Xml": u"System.Xml",
    u"System.Drawing": u"System.Drawing",
    u"System.Drawing.Drawing2D": u"System.Drawing",
    u"System.Drawing.Imaging": u"System.Drawing",
    u"System.Windows": u"PresentationFramework",
    u"System.Windows.Controls": u"PresentationFramework",
    u"System.Windows.Controls.Primitives": u"PresentationFramework",
    u"System.Windows.Markup": u"PresentationFramework",
    u"System.Windows.Media": u"PresentationCore",
    u"System.Windows.Media.Imaging": u"PresentationCore",
    u"System.Windows.Input": u"PresentationCore",
    u"System.Windows.Interop": u"PresentationCore",
    u"System.Windows.Threading": u"WindowsBase",
    u"System.Windows.Documents": u"PresentationFramework",
    u"System.Windows.Forms": u"System.Windows.Forms",
    u"Microsoft.Win32": u"PresentationFramework",
    u"Microsoft.VisualBasic": u"Microsoft.VisualBasic",
}

LOADED = []
FAILED = []


def _reference(name):
    try:
        clr.AddReference(name)
        LOADED.append(name)
        return True
    except Exception:
        FAILED.append(name)
        return False


for _name in ASSEMBLIES:
    _reference(_name)
