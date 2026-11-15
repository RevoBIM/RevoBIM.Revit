# -*- coding: utf-8 -*-
"""Every clr.AddReference for the tool. Imported first by every other module."""
import clr

_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Data', 'System.Data.Common',
    'System.Xml', 'System.Xaml', 'System.Drawing', 'System.Windows.Forms',
    'PresentationFramework', 'PresentationCore', 'WindowsBase',
    'System.ObjectModel', 'System.ComponentModel.Primitives',
    'System.ComponentModel.TypeConverter', 'System.Collections',
    'System.IO.Compression', 'System.IO.Compression.FileSystem',
    'System.IO.Compression.ZipFile',
]
LOADED = []
for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        pass
