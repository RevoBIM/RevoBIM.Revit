# -*- coding: utf-8 -*-
"""RevoBIM PY - View Template Manager: assembly references.

Every other module imports this first, ahead of any System.* or Autodesk.*
line. pyRevit does not preload WPF into every engine, and a namespace does not
exist for IronPython until its assembly has been referenced - so a module that
imports System.Windows before this has run dies at load with a blank white
window.

Each assembly is requested on its own so a name a release lacks is skipped
rather than throwing.
"""

import clr

ASSEMBLIES = [
    "mscorlib", "System", "System.Core", "System.Xml", "System.Xaml",
    "System.Windows.Forms", "PresentationFramework", "PresentationCore",
    "WindowsBase",
]

LOADED = []

for _name in ASSEMBLIES:
    try:
        clr.AddReference(_name)
        LOADED.append(_name)
    except Exception:
        pass
