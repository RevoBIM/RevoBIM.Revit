# -*- coding: utf-8 -*-
# =============================================================================
# RevoBIM.Arcade - replacement body for egg_hook.launch          (NOT a module)
# =============================================================================
#
# WHAT TO PASTE, AND WHERE
#   File:   lib\revobim\egg\egg_hook.py  (shared, singular - do not replace the file)
#   Step 1: at the end of the file, replace the whole of the existing
#           `def launch(host_window=None, theme=None, game_key=None): ...`
#           (the last function, 7 lines) with EVERYTHING between the two
#           ">>> RevoBIM.Arcade" band lines below.
#   Step 2: nothing else. No new import at the top of egg_hook.py is needed; the
#           band imports what it uses inside its own functions, so a failure
#           here can never stop egg_hook itself from importing.
#
# WHAT DOES NOT CHANGE
#   * The signature: launch(host_window=None, theme=None, game_key=None).
#   * The return value: True if something opened, False if not. Never raises.
#   * Every caller. All twelve call sites (Level Manager, ParaManager, ClashAnalysis,
#     Find Room, Workset Management, Bulk Rename, Family Param Push, Filter Manager,
#     Selected in View, Space Data Push, Addin Manager, the RevoBIM Arcade button)
#     keep working untouched, positional or keyword, with or without a game key.
#   * The four anchors: startup.py, hooks\app-init.py, hooks\doc-opened.py and
#     egg_hook.attach are not touched. The band sits below attach().
#   * egg_shell.py, egg_launcher.py, egg_desktop.py and standalone\ are not touched.
#
# WHAT CHANGES
#   If lib\revobim\egg\bin\RevoBIM.Arcade.exe exists AND the game is one the exe
#   has (ARCADE_KEYS), launch() starts the exe as a separate Windows process:
#       RevoBIM.Arcade.exe --game <key> --theme <light|dark> [--owner-x/-y/-w/-h]
#   Revit only starts the process. Closing Revit does not close the game.
#   Otherwise it does exactly what it did before (egg_shell.launch).
#
# WHY THE FALLBACK IS THERE (read this before extending ARCADE_KEYS)
#   Only "hello" exists in the exe so far. Pacman and Snake are still Python games
#   inside this package. Every caller above asks for "pacman", so sending that to
#   the exe would open its menu with "there is no game called pacman". Until each
#   game is ported, its key stays out of ARCADE_KEYS and keeps running as before.
#   Pacman and Tetris are ported (0.2.0), so both are in ARCADE_KEYS.
#
# ADDING A GAME LATER
#   Port it in the exe (Games\<Name>\ + one line in GameRegistry), publish, then
#   add its key to ARCADE_KEYS below. No caller changes.
# =============================================================================


# >>> RevoBIM.Arcade BEGIN (egg_hook.launch) >>>
# Keys the standalone exe can run. Extend as games are ported.
ARCADE_KEYS = ("pacman", "tetris", "snake", "hello")

ARCADE_EXE_NAME = "RevoBIM.Arcade.exe"


def _arcade_exe():
    """Full path of the exe if it is installed beside this package, else None."""
    try:
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "bin", ARCADE_EXE_NAME)
        return path if os.path.isfile(path) else None
    except Exception:
        return None


def _arcade_key(game_key):
    """The key to run: the caller's, or the saved one, as the in-process egg does.
    Returns it only if it is plain (lower-case letters, digits, '-'), because it is
    about to become a command line argument."""
    try:
        import re
        wanted = game_key or egg_settings.load().get("game")
        wanted = (str(wanted).strip().lower()) if wanted else None
        if wanted and re.match(r"^[a-z0-9][a-z0-9-]*$", wanted):
            return wanted
    except Exception:
        pass
    return None


def _arcade_owner_args(host_window):
    """['--owner-x', '100', ...] in screen pixels, or [] if the window cannot say.
    WPF reports device-independent units, so the display scale is applied."""
    try:
        if host_window is None:
            return []
        from System.Windows import PresentationSource
        scale = 1.0
        source = PresentationSource.FromVisual(host_window)
        if source is not None and source.CompositionTarget is not None:
            scale = float(source.CompositionTarget.TransformToDevice.M11)
        width = float(host_window.ActualWidth)
        height = float(host_window.ActualHeight)
        if width <= 0 or height <= 0:
            return []
        return ["--owner-x", str(int(round(float(host_window.Left) * scale))),
                "--owner-y", str(int(round(float(host_window.Top) * scale))),
                "--owner-w", str(int(round(width * scale))),
                "--owner-h", str(int(round(height * scale)))]
    except Exception:
        return []


def _arcade_start(exe, key, theme, host_window):
    """Start the exe. True if it went. A second launch hands its key to the running
    arcade and exits with code 0 within a moment, which is success, not failure."""
    try:
        from System.Diagnostics import Process, ProcessStartInfo
        from revobim.egg import egg_theme

        resolved = egg_theme.resolve(theme, egg_settings.load().get("theme"))
        if resolved not in ("light", "dark"):
            resolved = "dark"

        args = ["--game", key, "--theme", resolved] + _arcade_owner_args(host_window)

        info = ProcessStartInfo(exe)
        info.Arguments = " ".join(args)        # every value is a number or a plain word
        info.UseShellExecute = False
        info.CreateNoWindow = True
        process = Process.Start(info)
        if process is None:
            return False

        egg_shell.pause(900)
        if process.HasExited and process.ExitCode != 0:
            egg_log.write("arcade exited with code {0}".format(process.ExitCode),
                          "arcade")
            return False
        return True
    except Exception:
        egg_log.write("arcade start threw: {0}".format(_last_error()), "arcade")
        return False


def launch(host_window=None, theme=None, game_key=None):
    """Open the egg directly, without the clicks. Handy for testing it.

    Games the standalone RevoBIM.Arcade.exe has run in their own Windows process.
    Anything else runs as it always did. Signature and return value are unchanged.
    """
    opened = False
    try:
        exe = _arcade_exe()
        key = _arcade_key(game_key)
        if exe and key and key in ARCADE_KEYS:
            opened = _arcade_start(exe, key, theme, host_window)
            if not opened:
                egg_log.write("arcade did not start, using the in-process egg",
                              "arcade")
    except Exception:
        opened = False

    if not opened:
        opened = egg_shell.launch(host_window=host_window, theme=theme,
                                  game_key=game_key)
    egg_log.write("direct launch {0}".format("ok" if opened else "FAILED"))
    return opened
# <<< RevoBIM.Arcade END (egg_hook.launch) <<<
