# -*- coding: utf-8 -*-
"""Every assembly reference the tool needs, made once, before any module
imports from a System.* namespace. Imported first by every other module.
RevitAPI / RevitAPIUI are already loaded by pyRevit and are not referenced."""
import clr

_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Xml', 'System.Xaml',
    'System.Drawing', 'System.Windows.Forms',
    'PresentationFramework', 'PresentationCore', 'WindowsBase',
    'System.ObjectModel', 'System.Collections',
    'System.ComponentModel.Primitives', 'System.ComponentModel.TypeConverter',
    'System.Runtime',
]
LOADED = []
FAILED = []
for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        FAILED.append(_name)
