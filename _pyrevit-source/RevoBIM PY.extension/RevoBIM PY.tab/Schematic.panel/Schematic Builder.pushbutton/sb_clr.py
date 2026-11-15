# -*- coding: utf-8 -*-
"""Assembly references for Schematic Builder.

Every other module in this tool imports this module FIRST, before any
``System.*`` or ``Autodesk.*`` line. pyRevit does not preload WPF into every
engine, and a namespace can only be seen once its assembly is referenced.

RevitAPI / RevitAPIUI are deliberately NOT referenced here: pyRevit has
already loaded them, and re-referencing them has caused access violations.
"""
import clr

ASSEMBLIES = (
    "System",
    "System.Core",
    "System.Xml",
    "System.Xaml",
    "WindowsBase",
    "PresentationCore",
    "PresentationFramework",
    "System.Drawing",
    "System.Windows.Forms",
)

for _name in ASSEMBLIES:
    try:
        clr.AddReference(_name)
    except Exception:
        pass
