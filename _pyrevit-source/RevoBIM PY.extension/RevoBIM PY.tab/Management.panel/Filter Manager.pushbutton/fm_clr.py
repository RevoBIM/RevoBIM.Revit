# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager : assembly references.

Every other module imports this FIRST, before any System.* or Autodesk.*
line. An IronPython engine can only see a .NET namespace once its assembly
has been referenced, and pyRevit does not preload WPF into every engine.
Getting this wrong is the blank white pyRevit window.
"""

import clr

# RevitAPI and RevitAPIUI are deliberately NOT listed. pyRevit has already
# loaded them, and asking for them again by simple name can resolve to a
# second copy on disk - two distinct Autodesk.Revit.DB.Document types in one
# process, which shows up as an access violation rather than an exception.
for _asm in ("PresentationCore", "PresentationFramework", "WindowsBase",
             "System.Xaml", "System", "System.Core",
             "System.Xml", "System.IO.Compression",
             "System.IO.Compression.FileSystem"):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

LOADED = True
