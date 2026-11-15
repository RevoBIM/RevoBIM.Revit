# -*- coding: utf-8 -*-
"""Every clr.AddReference the tool needs, in one place.

An IronPython engine can only see a .NET namespace once its assembly has been
referenced, and pyRevit does not preload WPF into every engine. Every other
module imports this one before it touches System.* or Autodesk.*.

RevitAPI and RevitAPIUI are never referenced here - pyRevit already has them.
Each assembly is asked for on its own, so a name a release does not have is
skipped rather than thrown.
"""
import clr

ASSEMBLIES = (
    u"System",
    u"System.Core",
    u"System.Data",
    u"System.Xml",
    u"System.Xaml",
    u"WindowsBase",
    u"PresentationCore",
    u"PresentationFramework",
    u"System.Windows.Forms",
    # publishing to ACC: HTTP, the sign-in listener, the browser and the
    # encrypted token store. Framework 4.8 keeps these in System and
    # System.Security; .NET 8 splits them into the assemblies below.
    u"System.Security",
    u"System.Net.Requests",
    u"System.Net.ServicePoint",
    u"System.Net.Primitives",
    u"System.Net.Sockets",
    u"System.Diagnostics.Process",
    u"System.Security.Cryptography.ProtectedData",
)

LOADED = []
MISSING = []

for _assembly in ASSEMBLIES:
    try:
        clr.AddReference(_assembly)
        LOADED.append(_assembly)
    except Exception:
        MISSING.append(_assembly)
