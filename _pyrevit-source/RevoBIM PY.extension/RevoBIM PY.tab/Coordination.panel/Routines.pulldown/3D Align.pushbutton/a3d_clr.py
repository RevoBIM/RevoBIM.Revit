# -*- coding: utf-8 -*-
"""3D Align - every clr.AddReference, imported first by every other module.

An IronPython engine can only see a .NET namespace once its assembly has been
referenced, and pyRevit does not preload WPF into every engine. RevitAPI and
RevitAPIUI are left alone - pyRevit has already loaded them.
"""
import clr

_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Xml', 'System.Xaml',
    'System.Drawing', 'System.Windows.Forms',
    'PresentationFramework', 'PresentationCore', 'WindowsBase',
]

LOADED = []
SKIPPED = []
for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        SKIPPED.append(_name)
