# -*- coding: utf-8 -*-
"""RevoBIM PY - extension startup.

pyRevit runs this once when it loads the extension, with `__revit__` bound to
the `UIControlledApplication`.  That is the only moment a dockable pane can be
registered, which is why Family Viewer's pane is set up from here rather than
from its button.

IF YOU ALREADY HAVE A startup.py AT THE ROOT OF THIS EXTENSION, do not
overwrite it.  Copy the block between the two banners below into the bottom of
your own instead - it is self-contained and touches nothing else.

Nothing in here is allowed to raise.  A tool that cannot register its pane
falls back to its floating window; it must never stop pyRevit loading the rest
of the extension.
"""

import os
import sys
import traceback


# =========================================================================
# RevoBIM Family Viewer - dockable pane
# =========================================================================

def _register_family_viewer():
    folder = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'RevoBIM PY.tab', 'Management.panel', 'Family Viewer.pushbutton')
    if not os.path.isdir(folder):
        return
    if folder not in sys.path:
        sys.path.append(folder)
    import fv_dock
    fv_dock.register(__revit__)                        # noqa: F821


try:
    _register_family_viewer()
except Exception:
    try:
        appdata = os.path.join(os.environ.get('APPDATA', ''), 'RevoBIM')
        if not os.path.isdir(appdata):
            os.makedirs(appdata)
        handle = open(os.path.join(appdata, 'startup_last_error.txt'), 'w')
        try:
            handle.write('Family Viewer dockable pane\n\n' +
                         traceback.format_exc())
        finally:
            handle.close()
    except Exception:
        pass

# =========================================================================
# end RevoBIM Family Viewer
# =========================================================================


# =====================================================================
# Pro Sheets Exporter - "Print in ProSheets" on the right click menu
# Revit 2025 and up; dormant below that. Paste into the existing
# startup.py. Do not overwrite that file.
# =====================================================================
try:
    import os as _rb_os
    import sys as _rb_sys

    def _rb_note(_rb_text):
        """Last-resort log, for failures that happen before ps_context
        is importable. Without this, a block that cannot find the tool
        folder leaves no trace at all and looks exactly like a block
        that was never pasted."""
        try:
            _rb_dir = _rb_os.path.join(
                _rb_os.environ.get('APPDATA', ''), 'RevoBIM', 'logs')
            if not _rb_os.path.isdir(_rb_dir):
                _rb_os.makedirs(_rb_dir)
            _rb_handle = open(_rb_os.path.join(
                _rb_dir, 'pro_sheets_exporter_context_menu.txt'), 'ab')
            try:
                _rb_handle.write(
                    (u'{0}\n'.format(_rb_text)).encode('utf-8'))
            finally:
                _rb_handle.close()
        except Exception:
            pass

    # Walk up from this file looking for the tool, rather than assuming
    # startup.py sits exactly at the extension root. It should, but a
    # startup.py one folder off would otherwise fail in total silence.
    try:
        _rb_here = _rb_os.path.dirname(_rb_os.path.abspath(__file__))
    except Exception:
        _rb_here = u''
    _rb_tail = _rb_os.path.join('RevoBIM PY.tab', 'Sheet Tools.panel',
                                'Pro Sheets Exporter.pushbutton')
    _rb_ps = u''
    _rb_walk = _rb_here
    for _rb_step in (0, 1, 2, 3):
        if not _rb_walk:
            break
        _rb_guess = _rb_os.path.join(_rb_walk, _rb_tail)
        if _rb_os.path.isdir(_rb_guess):
            _rb_ps = _rb_guess
            break
        _rb_walk = _rb_os.path.dirname(_rb_walk)

    if not _rb_ps:
        _rb_note(u'The startup block ran but could not find the Pro '
                 u'Sheets Exporter folder by walking up from "{0}". '
                 u'Either the block is in a startup.py outside the '
                 u'RevoBIM PY.extension folder, or the tool is not '
                 u'installed.'.format(_rb_here or u'<unknown>'))
    else:
        if _rb_ps not in _rb_sys.path:
            _rb_sys.path.append(_rb_ps)

        # Both are offered, best first, because which one carries
        # RegisterContextMenu depends on the Revit release AND the
        # pyRevit build: a UIApplication has had the method since
        # Revit 2025, a UIControlledApplication only since 2026.
        # ps_context picks whichever answers and never assumes.
        # Either name may be undefined on some pyRevit builds, so
        # each is fetched defensively rather than referenced.
        _rb_hosts = []
        for _rb_name in ('__revit__', '__uicontrolledapplication__'):
            # eval, not globals(): pyRevit supplies these as builtins,
            # which globals() does not see.
            try:
                _rb_host = eval(_rb_name)
                if _rb_host is not None:
                    _rb_hosts.append(_rb_host)
            except Exception:
                pass

        if not _rb_hosts:
            _rb_note(u'The startup block ran but pyRevit gave it '
                     u'neither __revit__ nor '
                     u'__uicontrolledapplication__, so there is '
                     u'nothing to register on.')
        else:
            import ps_context
            ps_context.register(*_rb_hosts)
except Exception:
    # A startup.py that throws stops pyRevit loading the whole
    # extension, so this swallows everything - but it says so first,
    # because a silent swallow here is indistinguishable from the
    # block never having been pasted.
    try:
        _rb_note(u'The startup block threw and was swallowed.')
    except Exception:
        pass
# =====================================================================


# ==========================================================
# RevoBIM Project Browser Pro - register the dockable panes
# Paste into the existing startup.py. Do not overwrite it.
#
# Revit only sets a dockable pane up while it is building
# its user interface, so this has to run from startup.py.
# Without it the button still works, as a floating window.
#
# Safe to paste twice and safe across a pyRevit reload: the
# registration is guarded in the AppDomain, and the whole
# block is wrapped so it can never stop the extension
# loading. A pyRevit reload is NOT enough to add the panes -
# restart Revit after pasting.
# ==========================================================
try:
    import os as _pbp_os
    import sys as _pbp_sys

    def _pbp_tool_folder():
        here = _pbp_os.path.dirname(_pbp_os.path.abspath(__file__))
        candidate = _pbp_os.path.join(
            here, u"RevoBIM PY.tab", u"Management.panel",
            u"Project Browser Pro.pushbutton")
        if _pbp_os.path.isdir(candidate):
            return candidate
        # Fall back to a walk, so moving the tool to another panel does not
        # silently stop the panes registering.
        for root, folders, files in _pbp_os.walk(here):
            for folder in folders:
                if folder.lower() == u"project browser pro.pushbutton":
                    return _pbp_os.path.join(root, folder)
        return None

    _pbp_folder = _pbp_tool_folder()
    if _pbp_folder:
        if _pbp_folder not in _pbp_sys.path:
            _pbp_sys.path.append(_pbp_folder)
        import pbp_dock as _pbp_dock
        # Which name pyRevit uses for the application, and whether it is a
        # global or a builtin, varies by pyRevit build - offer every one
        # that resolves and let register() ask each for RegisterDockablePane.
        _pbp_candidates = []
        try:
            _pbp_candidates.append(__uiControlledApplication__)  # noqa: F821
        except NameError:
            pass
        try:
            _pbp_candidates.append(__uicontrolledapplication__)  # noqa: F821
        except NameError:
            pass
        try:
            _pbp_candidates.append(__revit__)  # noqa: F821
        except NameError:
            pass
        _pbp_dock.register(*_pbp_candidates)
except Exception:
    try:
        import pbp_log as _pbp_log
        _pbp_log.exc(u"startup fragment")
    except Exception:
        pass
# ==========================================================


# =============================================================================
# RevoBIM Addin Manager - register the dockable pane          (v1.4.0 block)
#
# Revit only sets a dockable pane up while it is building its user interface,
# so this is the only place the pane can be registered. A pyRevit reload is
# not enough after pasting it - restart Revit.
#
# The host object is ASKED, not assumed: which object pyRevit hands this file,
# and under which name, varies by pyRevit build, and naming one that is not
# defined raises NameError. Every name is looked up through a guard and all of
# them are offered; rba_dock.register uses whichever has RegisterDockablePane
# and writes %APPDATA%\RevoBIM\revobim_addins_startup.txt saying which.
#
# Replaces the 1.2.0 - 1.3.0 block, which named one host directly and failed
# silently where that name was undefined. Safe to paste twice. Names are all
# prefixed _rba_ so nothing can collide with other blocks in this file.
# =============================================================================
try:
    import os as _rba_os
    import sys as _rba_sys

    def _rba_lookup(_rba_name):
        # eval resolves a module global and a pyRevit builtin alike.
        try:
            return eval(_rba_name)
        except Exception:
            return None

    def _rba_tool_folder():
        _here = _rba_os.path.dirname(_rba_os.path.abspath(__file__))
        _candidate = _rba_os.path.join(
            _here, u"RevoBIM PY.tab", u"Management.panel",
            u"RevoBIM Addin Manager.pushbutton")
        if _rba_os.path.isdir(_candidate):
            return _candidate
        # Fall back to a walk, so moving the tool to another panel does not
        # silently stop the pane registering.
        for _root, _folders, _files in _rba_os.walk(_here):
            for _folder in _folders:
                if _folder.lower() == u"revobim addin manager.pushbutton":
                    return _rba_os.path.join(_root, _folder)
        return None

    _rba_folder = _rba_tool_folder()
    if _rba_folder and _rba_folder not in _rba_sys.path:
        _rba_sys.path.append(_rba_folder)

    if _rba_folder:
        import rba_dock as _rba_dock
        _rba_dock.register(
            (u"__uiControlledApplication__", _rba_lookup(u"__uiControlledApplication__")),
            (u"__uicontrolledapplication__", _rba_lookup(u"__uicontrolledapplication__")),
            (u"__revit__", _rba_lookup(u"__revit__")),
        )

        # In its own try: a failure here must not reach the outer handler,
        # which would overwrite a successful registration's log with an error.
        try:
            # A dockable pane outlives the command that opened it, so it needs a
            # UIApplication of its own to post commands with. The first Idling
            # event carries one. Hooked once and switched off with a flag rather
            # than unsubscribed: unsubscribing an IronPython bound method from a
            # .NET event is not reliable, because each access makes a new delegate.
            import rba_launch as _rba_launch

            _rba_captured = []

            def _rba_grab_uiapp(sender, args):
                if _rba_captured:
                    return
                try:
                    _rba_launch.set_uiapp(sender)
                    _rba_captured.append(True)
                except Exception:
                    pass

            for _rba_host in (_rba_lookup(u"__uiControlledApplication__"),
                              _rba_lookup(u"__uicontrolledapplication__"),
                              _rba_lookup(u"__revit__")):
                if _rba_host is None:
                    continue
                try:
                    _rba_host.Idling += _rba_grab_uiapp
                    break
                except Exception:
                    continue
        except Exception:
            pass
except Exception:
    # Never let this block stop pyRevit loading the extension - but never let
    # it fail without a trace either.
    try:
        import traceback as _rba_tb
        _rba_dir = _rba_os.path.join(_rba_os.environ.get(u"APPDATA", u""), u"RevoBIM")
        if not _rba_os.path.isdir(_rba_dir):
            _rba_os.makedirs(_rba_dir)
        try:
            from System.Diagnostics import Process as _rba_proc
            _rba_pid = u"pid={0}\n".format(_rba_proc.GetCurrentProcess().Id)
        except Exception:
            _rba_pid = u""
        _rba_fh = open(_rba_os.path.join(_rba_dir, u"revobim_addins_startup.txt"), u"wb")
        try:
            _rba_fh.write((u"startup block failed before registering\n" + _rba_pid
                           + u"outcome=error\n" + _rba_tb.format_exc()).encode(u"utf-8"))
        finally:
            _rba_fh.close()
    except Exception:
        pass
# =============================================================================
# end of the RevoBIM Addin Manager block
# =============================================================================
