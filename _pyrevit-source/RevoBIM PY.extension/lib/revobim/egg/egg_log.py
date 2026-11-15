# -*- coding: utf-8 -*-
"""A log for the easter egg.

Everything in `egg_hook` is wrapped in try/except on purpose: a tool must never
fail to open because its easter egg would not attach. The cost of that rule is
that a hook which never fires looks exactly like a hook that was never asked
for, and there is nothing anywhere to say which.

So every attach, every click and every launch is written here:

    %APPDATA%\\RevoBIM\\easter_egg.log

Plain stdlib. Never raises - a logger that can take a tool down is worse than no
logger at all.
"""

import datetime
import os

KEPT_LINES = 250

_FOLDER_NAME = "RevoBIM"
_FILE_NAME = "easter_egg.log"


def folder():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, _FOLDER_NAME)


def path():
    return os.path.join(folder(), _FILE_NAME)


def write(message, tool=None):
    """Append one line. Returns True if it landed."""
    try:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = "{0}  {1}{2}".format(stamp,
                                    "[{0}] ".format(tool) if tool else "",
                                    _flat(message))
        lines = read()
        lines.append(line)
        if len(lines) > KEPT_LINES:
            lines = lines[-KEPT_LINES:]
        target = folder()
        if not os.path.isdir(target):
            os.makedirs(target)
        handle = open(path(), "w")
        try:
            handle.write("\n".join(lines))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def read():
    try:
        if not os.path.isfile(path()):
            return []
        handle = open(path(), "r")
        try:
            return handle.read().splitlines()
        finally:
            handle.close()
    except Exception:
        return []


def tail(count=30):
    return read()[-count:]


def clear():
    try:
        if os.path.isfile(path()):
            os.remove(path())
        return True
    except Exception:
        return False


def _flat(value):
    try:
        text = str(value)
    except Exception:
        return "<unprintable>"
    return " ".join(text.split())
