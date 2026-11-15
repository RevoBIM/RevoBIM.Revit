# -*- coding: utf-8 -*-
"""Every clr.AddReference for Explode Import Symbol Multiple.

Imported first by every other module in the tool, ahead of any System.* or
Autodesk.* import. pyRevit does not preload WPF into every engine, and a
namespace only exists once its assembly is referenced. RevitAPI / RevitAPIUI
are the host's own and are never referenced here.

Each assembly is requested on its own so a name a release does not carry is
skipped rather than taking the tool down.
"""
import clr

_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Xaml',
    'PresentationFramework', 'PresentationCore', 'WindowsBase',
    'AdWindows', 'UIAutomationClient', 'UIAutomationTypes',
]

LOADED = []
MISSING = []

for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        MISSING.append(_name)
