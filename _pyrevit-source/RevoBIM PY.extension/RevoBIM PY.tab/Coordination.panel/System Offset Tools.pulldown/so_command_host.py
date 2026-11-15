# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM System Offset - where the live Revit handles live
#
# Both buttons park the UIApplication here as they start, so
# a module deeper in can reach Revit without every function
# taking it as an argument.
# ==========================================================

import so_clr  # noqa: F401  assembly references first

_UIAPP = [None]


def set_uiapp(uiapp):
    _UIAPP[0] = uiapp
    return uiapp


def current_uiapp():
    return _UIAPP[0]


def current_uidoc():
    uiapp = _UIAPP[0]
    if uiapp is None:
        return None
    try:
        return uiapp.ActiveUIDocument
    except Exception:
        return None
