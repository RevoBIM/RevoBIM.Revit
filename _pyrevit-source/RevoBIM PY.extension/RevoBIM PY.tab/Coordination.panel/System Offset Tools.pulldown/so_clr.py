# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM System Offset - assembly references
# Imported FIRST by every other module in this tool, before
# any System.* or Autodesk.* name is touched.
#
# pyRevit does not preload WPF into every engine. An
# IronPython engine can only see a .NET namespace once
# clr.AddReference has been called for the assembly holding
# it, so a module that opens with "from System.Windows
# import FontWeights" throws ImportError at module load and
# shows as a blank white pyRevit window with no traceback.
# ==========================================================

import clr

# Each one on its own, so a name that does not exist on a
# given release is skipped rather than taking the tool down.
for _asm in (
    'PresentationCore',
    'PresentationFramework',
    'WindowsBase',
    'System.Xaml',
    'System.Xml',
    'System.Xml.ReaderWriter',
    'System.Drawing',
    'System.Windows.Forms',
    'System.Core',
    'System',
):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

# RevitAPI and RevitAPIUI are loaded by pyRevit itself.
# Referencing them again is not needed and is a known way to
# pick up the wrong copy.

LOADED = True
