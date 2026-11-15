# -*- coding: utf-8 -*-
"""Every clr.AddReference the tool needs, in one place.

An IronPython engine can only see a .NET namespace once the assembly holding
it is referenced, and pyRevit does not preload WPF into every engine. Every
other module imports this one before its first System.* or Autodesk.* line.
Each assembly is asked for on its own, so a name missing on one release
(System.Data.Common only exists on .NET 8) is skipped rather than fatal.
RevitAPI and RevitAPIUI are never referenced here - pyRevit has them loaded.
"""
import clr

ASSEMBLIES = (
    u"System",
    u"System.Core",
    u"PresentationFramework",
    u"PresentationCore",
    u"WindowsBase",
    u"System.Xaml",
    u"System.Xml",
    u"System.Data",
    u"System.Data.Common",
    u"System.Windows.Forms",
    u"System.Drawing",
    u"System.IO.Compression",
)

LOADED = []
FAILED = []

for _name in ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        FAILED.append(_name)
