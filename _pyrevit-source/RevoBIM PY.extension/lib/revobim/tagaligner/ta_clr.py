# -*- coding: utf-8 -*-
"""Tag Aligner: every clr.AddReference, imported FIRST by every other module.

pyRevit does not preload WPF into every engine, and a namespace does not
exist until its assembly is referenced. Each name is requested on its own so
one missing on a given Revit release is skipped rather than fatal.
RevitAPI and RevitAPIUI are preloaded by pyRevit and are not referenced here.
"""
import clr

_ASSEMBLIES = [
    "mscorlib",
    "System",
    "System.Core",
    "System.Xml",
    "System.Xaml",
    "PresentationFramework",
    "PresentationCore",
    "WindowsBase",
]

LOADED = []
MISSING = []

for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        MISSING.append(_name)
