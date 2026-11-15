# -*- coding: utf-8 -*-
"""Popping the game out of Revit into its own process.

The in-Revit window runs on Revit's UI thread, in Revit's engine, drawing
through Revit's WPF. That is fine for ninety seconds and it is not fine for a
lunch break: a render loop tied to the host's dispatcher is competing with the
application people are actually paid to use.

So the game can be handed to a separate process instead. Same games, same
scoreboard file, none of Revit's resources - and Revit can be closed underneath
it without the game noticing.

Plain stdlib. Never raises.
"""

import os
import subprocess
import sys
import time

from revobim.egg import egg_log

LAUNCHER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "standalone", "RevoBIM Arcade.pyw")

# pythonw first: a console window sitting behind the game looks like something
# went wrong. `py -3 -w` is the launcher's equivalent.
CANDIDATES = (
    ("pythonw.exe", []),
    ("py.exe", ["-3", "-w"]),
    ("python.exe", []),
    ("python3", []),
    ("python", []),
)


def find_python():
    """(executable, extra args), or None if this machine has no Python.

    A BIM machine very often does not, which is a fact about the deployment
    rather than a bug - so this reports honestly and the caller says so, rather
    than a button that does nothing.
    """
    for name, extra in CANDIDATES:
        found = _which(name)
        if found:
            return (found, list(extra))
    return None


def _survives(process, seconds=0.8, pause=None):
    """True if the process is still alive after a moment.

    Polled rather than waited on: a game legitimately runs for minutes, so still
    running is the success case and there is nothing to wait for.
    """
    waited = 0.0
    while waited < seconds:
        try:
            if process.poll() is not None:
                return False
        except Exception:
            return True
        if pause is not None:
            pause(100)
        else:
            time.sleep(0.1)
        waited += 0.1
    return True


def _close(handle):
    try:
        if handle is not None:
            handle.close()
    except Exception:
        pass


def _which(name):
    try:
        from shutil import which
        found = which(name)
        if found:
            return found
    except Exception:
        pass
    # IronPython 2.7 has no shutil.which, so walk PATH by hand.
    try:
        for folder in (os.environ.get("PATH") or "").split(os.pathsep):
            if not folder:
                continue
            candidate = os.path.join(folder.strip('"'), name)
            if os.path.isfile(candidate):
                return candidate
    except Exception:
        pass
    return None


def available():
    return find_python() is not None and os.path.isfile(LAUNCHER)


def spawn(game_key=None, pause=None):
    """Start the desktop build detached. Returns True if it went.

    `pause` is injected rather than imported. This module has to stay free of
    .NET so the desktop build can use it, but `time.sleep` inside Revit lands on
    `Thread.Sleep`, which does not pump an STA thread and prints a warning for
    it. The caller inside Revit passes one that uses `Thread.Join`; on a desktop
    the default `time.sleep` is exactly right.

    Detached on purpose: closing Revit must not take the game with it, and a
    child process holding a handle on Revit is exactly the coupling this is
    meant to remove.
    """
    try:
        if not os.path.isfile(LAUNCHER):
            egg_log.write("pop out FAILED: no launcher at {0}".format(LAUNCHER),
                          "popout")
            return False
        python = find_python()
        if python is None:
            egg_log.write(
                "pop out FAILED: no Python on this machine. The desktop build "
                "needs Python 3 from python.org - tkinter only, no packages.",
                "popout")
            return False

        executable, extra = python
        command = [executable] + extra + [LAUNCHER]
        if game_key:
            command.append(str(game_key))

        options = {"close_fds": True}
        try:
            # Windows: no console, and no tie to this process.
            options["creationflags"] = (0x00000008 |     # DETACHED_PROCESS
                                        0x00000200)      # NEW_PROCESS_GROUP
        except Exception:
            pass

        # pythonw writes nothing anywhere, so a Python that is too old, or one
        # without tkinter, dies with its traceback going into the void. Catch it
        # in a file instead - that is the difference between "the button does
        # nothing" and one line saying which Python it found and why it refused.
        errors = None
        try:
            folder = os.path.dirname(egg_log.path())
            if not os.path.isdir(folder):
                os.makedirs(folder)
            errors = open(os.path.join(folder, "arcade_process.log"), "w")
            options["stderr"] = errors
            options["stdout"] = errors
        except Exception:
            errors = None

        process = subprocess.Popen(command, **options)

        # Popen returning only means Windows started something. A process that
        # exits half a second later has not run the game, and reporting success
        # for it is exactly how a button comes to do nothing at all.
        if not _survives(process, pause=pause):
            egg_log.write(
                "pop out FAILED: {0} started and exited immediately. See "
                "arcade_process.log - most likely Python 2, or a Python with "
                "no tkinter.".format(executable), "popout")
            _close(errors)
            return False

        egg_log.write("popped out to {0}".format(executable), "popout")
        return True
    except Exception:
        egg_log.write("pop out threw: {0}".format(sys.exc_info()[1]), "popout")
        return False
