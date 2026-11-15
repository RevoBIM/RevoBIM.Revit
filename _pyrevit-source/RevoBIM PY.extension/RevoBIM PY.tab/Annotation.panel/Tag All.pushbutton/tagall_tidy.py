# -*- coding: utf-8 -*-
"""Finding and loading Tag Tidy, for the "Tidy with Tag Tidy" option.

Tag Tidy is its own RevoBIM tool, in its own Tag Tidy.pulldown folder.
Nothing of it is imported when Tag All loads: Tag All has to open and run
exactly as before on a machine where Tag Tidy is not installed, or is a
version whose hook this Tag All does not understand.  load() is called from
inside the run, finds the folder (core.tidy_search_dirs), puts it on
sys.path and imports tidy_hook once.
"""

import tagall_clr  # noqa: F401  assemblies first, always

import os
import sys
import traceback

import tagall_core as core

HERE = os.path.dirname(os.path.abspath(__file__))

_STATE = {"hook": None, "why": None, "tried": False}


def find_folder(button_dir=None):
    for folder in core.tidy_search_dirs(button_dir or HERE):
        if os.path.exists(os.path.join(folder, core.TIDY_HOOK_FILE)):
            return folder
    return None


def load():
    """The tidy_hook module, or None with the reason in why()."""
    if _STATE["tried"]:
        return _STATE["hook"]
    _STATE["tried"] = True
    folder = find_folder()
    if folder is None:
        _STATE["why"] = u"Tag Tidy is not installed (no Tag Tidy.pulldown with tidy_hook.py on the RevoBIM PY tab)"
        return None
    if folder not in sys.path:
        sys.path.append(folder)
    try:
        import tidy_hook
    except Exception:
        core.log(u"loading Tag Tidy failed:\n{0}".format(traceback.format_exc()))
        _STATE["why"] = u"Tag Tidy is installed but would not load - see the Tag All log"
        return None
    version = getattr(tidy_hook, "HOOK_VERSION", None)
    if version != core.TIDY_HOOK_VERSION:
        _STATE["why"] = u"Tag Tidy's hook is version {0}; this Tag All needs version {1}".format(
            version, core.TIDY_HOOK_VERSION)
        return None
    _STATE["hook"] = tidy_hook
    return tidy_hook


def why():
    return _STATE["why"]


def installed():
    """For the window: is there a Tag Tidy to call?  Only looks on disk."""
    return find_folder() is not None


def describe():
    """The muted line under the option."""
    hook = _STATE["hook"]
    if hook is not None:
        return u"Tag Tidy v{0} is installed.".format(getattr(hook, "TOOL_VERSION", u"?"))
    if installed():
        return u"Uses Tag Tidy's own settings - side, leader angle, gap and what to avoid."
    return u"Tag Tidy is not installed, so this does nothing until it is."
