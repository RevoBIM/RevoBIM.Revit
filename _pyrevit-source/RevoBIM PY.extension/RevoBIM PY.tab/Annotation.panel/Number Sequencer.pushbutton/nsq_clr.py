# -*- coding: utf-8 -*-
"""Number Sequencer - every clr.AddReference, in one place.

Imported first by every module that touches System.* or Autodesk.*.
RevitAPI / RevitAPIUI are already loaded by pyRevit and are not referenced
here. Each assembly is requested on its own so a name a release lacks is
skipped rather than thrown.
"""

import clr

_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Xml', 'System.Xaml',
    'System.Drawing', 'System.Windows.Forms',
    'PresentationFramework', 'PresentationCore', 'WindowsBase',
]

LOADED = []
MISSING = []

for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        MISSING.append(_name)
