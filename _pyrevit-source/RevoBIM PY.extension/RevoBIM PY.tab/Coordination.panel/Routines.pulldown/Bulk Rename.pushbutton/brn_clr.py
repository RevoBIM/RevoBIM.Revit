# -*- coding: utf-8 -*-
"""Every clr.AddReference for Bulk Rename. Imported first by every module."""
import clr

_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Runtime',
    'System.Runtime.Extensions', 'System.IO.FileSystem', 'System.Xml',
    'System.Xml.ReaderWriter',
    'System.Xaml', 'System.ObjectModel', 'System.Collections',
    'System.Drawing', 'System.Windows.Forms',
    'PresentationFramework', 'PresentationCore', 'WindowsBase',
]

for _name in _ASSEMBLIES:
    try:
        clr.AddReference(_name)
    except Exception:
        pass
