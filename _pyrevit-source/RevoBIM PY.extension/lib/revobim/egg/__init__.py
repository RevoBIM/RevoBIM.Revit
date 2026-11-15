# -*- coding: utf-8 -*-
"""RevoBIM PY easter egg.

Deliberately imports nothing at package load: a failure here would take down
every tool that reaches for it, and every module in the package besides.

`__version__` is read from here by both builds, so it must always be present.
There is a bench rule for that, because an empty __init__.py compiles perfectly,
imports perfectly, and fails only at the one line that wants the version - which
is inside the try/except that stops the egg breaking a tool, so it looks like
nothing at all.
"""

__version__ = "1.12.0"
