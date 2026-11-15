# -*- coding: utf-8 -*-
"""Legend Creator - every .NET assembly reference, in one place.

Imported first by every module that touches System.*. An IronPython engine
only sees a namespace once its assembly is referenced, pyRevit does not
preload WPF into every engine, and a missing reference fails at module load
as a blank window. Each is requested on its own, so a name one release lacks
is skipped rather than taking the rest down. Under CPython - the bench - this
is a no-op.
"""

try:
    import clr
except ImportError:                      # CPython: nothing to reference
    clr = None

ASSEMBLIES = (
    'PresentationCore', 'PresentationFramework', 'WindowsBase',   # WPF
    'UIAutomationClient', 'UIAutomationTypes',   # find it in the browser
    'System.Windows.Forms', 'System.Drawing',    # which screen a window is on
)

MISSING = []

if clr is not None:
    for _assembly in ASSEMBLIES:
        try:
            clr.AddReference(_assembly)
        except Exception:
            MISSING.append(_assembly)
