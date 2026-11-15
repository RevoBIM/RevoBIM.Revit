# -*- coding: utf-8 -*-
"""pyRevit hook: application start.

A SECOND anchor for the easter egg's automatic attachment, deliberately using a
different pyRevit mechanism from `startup.py`.

There is only one `startup.py` per extension, so every tool that ships one is
fighting over the same file, and whichever zip is unpacked last wins. The egg
losing that fight is silent: nothing fails, the game simply never appears again.

pyRevit's hooks are a separate mechanism in a separate folder, so a `startup.py`
overwritten by another tool's delivery does not touch this. Either one alone is
enough, and `egg_auto.install()` is idempotent, so both running is fine.

Wrapped throughout: a hook that throws is noise in every session.
"""

try:
    import os
    import sys

    _LIB = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
    if _LIB not in sys.path:
        sys.path.insert(0, _LIB)

    from revobim.egg import egg_auto
    egg_auto.install()
except Exception:
    try:
        import traceback
        from revobim.egg import egg_log
        egg_log.write("app-init hook failed: {0}".format(
            traceback.format_exc().replace("\n", " | ")), "hook")
    except Exception:
        pass
