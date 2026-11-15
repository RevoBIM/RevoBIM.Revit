# -*- coding: utf-8 -*-
u"""Every clr.AddReference for Hanger Automation, in one place.

Import this FIRST from every module that touches .NET.  pyRevit does not
preload WPF into every engine, and a namespace only exists once its assembly
has been referenced, so import order here is load order.

RevitAPI / RevitAPIUI are already loaded by pyRevit and are deliberately not
referenced here (referencing them has misbehaved across 2024-2027).
"""
import clr

_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Xml', 'System.Xaml',
    'System.Drawing', 'System.Windows.Forms',
    'PresentationFramework', 'PresentationCore', 'WindowsBase',
]

LOADED = []
FAILED = []

for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        FAILED.append(_name)
