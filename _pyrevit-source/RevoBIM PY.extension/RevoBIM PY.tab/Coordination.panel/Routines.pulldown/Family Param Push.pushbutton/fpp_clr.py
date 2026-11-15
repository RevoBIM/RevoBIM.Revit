# -*- coding: utf-8 -*-
"""Every clr.AddReference the tool needs. Imported first by every module that
touches .NET. Each name goes in its own try, because the same namespace lives
in different assemblies on Revit 2024 (.NET 4.8) and 2025+ (.NET 8)."""
import clr

_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Data', 'System.Data.Common',
    'System.Xml', 'System.Xaml', 'System.Drawing', 'System.Windows.Forms',
    'PresentationFramework', 'PresentationCore', 'WindowsBase',
    'System.ObjectModel', 'System.Collections',
    'System.ComponentModel.Primitives',
    'System.ComponentModel.TypeConverter',
]

LOADED = []
for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        pass
