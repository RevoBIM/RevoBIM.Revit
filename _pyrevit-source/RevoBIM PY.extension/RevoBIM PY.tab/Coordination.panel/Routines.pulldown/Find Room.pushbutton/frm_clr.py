# -*- coding: utf-8 -*-
"""Every clr.AddReference Find Room needs, in one place.

Imported FIRST by every other module, ahead of any System.* or Autodesk.*
line. Each assembly is requested on its own inside try/except so a name that
does not exist on a given Revit release (2024 is .NET Framework 4.8, 2025+ is
.NET 8) is skipped rather than throwing. RevitAPI / RevitAPIUI are already
loaded by pyRevit and are not referenced here.
"""
MISSING = []

_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Xml', 'System.Xaml',
    'System.Windows.Forms', 'PresentationFramework', 'PresentationCore',
    'WindowsBase',
]

try:
    import clr
    for _name in _ASSEMBLIES:
        try:
            clr.AddReference(_name)
        except Exception:
            MISSING.append(_name)
except Exception:
    # Plain CPython (bench) - there is no clr and nothing to reference.
    clr = None
