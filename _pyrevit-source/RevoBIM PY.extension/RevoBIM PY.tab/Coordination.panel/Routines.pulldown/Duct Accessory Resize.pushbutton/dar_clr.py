# -*- coding: utf-8 -*-
"""Every clr.AddReference the tool needs, in one place.

An IronPython engine can only see a .NET namespace once the assembly holding
it is referenced, and pyRevit does not preload WPF into every engine. Every
other module imports this one first, ahead of any System.* or Autodesk.*
line. RevitAPI and RevitAPIUI are already loaded by pyRevit.
"""

import clr

ASSEMBLIES = (
    "System",
    "System.Core",
    "System.Xml",
    "System.Xaml",
    "WindowsBase",
    "PresentationCore",
    "PresentationFramework",
    "System.Windows.Forms",
)

LOADED = []
for _name in ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        pass
