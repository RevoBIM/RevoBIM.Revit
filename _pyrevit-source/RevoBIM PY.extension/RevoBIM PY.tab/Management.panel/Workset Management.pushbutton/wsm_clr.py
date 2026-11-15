# -*- coding: utf-8 -*-
"""RevoBIM PY - Workset Management : every assembly reference, in one place.

Imported first by every module that reaches into System.* - pyRevit does not
preload WPF into every engine, and a namespace does not exist until its
assembly has been referenced.  Each request is separate, so a name that does
not exist on one release is skipped rather than taking the tool down.
RevitAPI and RevitAPIUI are pyRevit's to load and are not requested here.
"""

import clr

ASSEMBLIES = [
    "mscorlib", "System", "System.Core", "System.Data", "System.Xml",
    "System.Xaml", "System.Drawing", "System.Windows.Forms",
    "PresentationFramework", "PresentationCore", "WindowsBase",
    "System.IO.Compression", "System.IO.Compression.FileSystem",
]

LOADED = []
MISSING = []

for _name in ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        MISSING.append(_name)
