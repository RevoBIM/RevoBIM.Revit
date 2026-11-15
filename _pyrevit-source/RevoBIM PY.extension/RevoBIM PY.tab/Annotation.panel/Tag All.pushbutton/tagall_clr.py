# -*- coding: utf-8 -*-
"""Every clr.AddReference the tool needs, in one place.

Import this module before touching any System.* or Autodesk.* name. An
IronPython engine can only see a .NET namespace once the assembly holding it
has been referenced, and pyRevit does not preload WPF into every engine. A
module that opens with `from System.Windows import ...` before anything has
referenced PresentationFramework throws ImportError at module load, which is
the blank white pyRevit window with no traceback in it.

RevitAPI and RevitAPIUI are deliberately not referenced here: pyRevit loads
them into every engine and asking for them again can bind a second copy.
"""
import clr


def _reference(name):
    try:
        clr.AddReference(name)
        return True
    except Exception:
        return False


REFERENCED = {}
for _name in ("PresentationCore", "PresentationFramework", "WindowsBase",
              "System.Xaml", "System", "System.Core", "System.Xml",
              "System.Windows.Forms", "System.Drawing"):
    REFERENCED[_name] = _reference(_name)
