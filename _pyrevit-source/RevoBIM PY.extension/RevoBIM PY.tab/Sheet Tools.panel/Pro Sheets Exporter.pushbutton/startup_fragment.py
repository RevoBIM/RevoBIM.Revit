# -*- coding: utf-8 -*-
# =====================================================================
# THIS FILE IS NOT LOADED BY ANYTHING.
#
# It holds the block that has to go into the extension's shared
# startup.py for the "Print in ProSheets" right click entry to exist.
# startup.py is shared and singular - one per extension - so this
# delivery does not ship it. Paste the banded block below into the
# startup.py you already have, at the end, and leave everything else
# in that file alone.
#
# WHERE: the startup.py sitting next to the "RevoBIM PY.tab" folder,
# i.e. in the root of "RevoBIM PY.extension". If there is no
# startup.py there, create one holding just the banded block.
#
# THEN: restart Revit. Not a pyRevit reload - a full restart. The
# entry can only be added while Revit is still building its UI, so a
# reload will not put it there.
#
# Without this block the tool works exactly as it always has. The
# only thing missing is the right click entry.
#
# Revit 2024 and earlier: paste it anyway. The block is dormant there
# and writes one line to the log saying so.
#
# THE LOG, either way:
#   %APPDATA%\RevoBIM\logs\pro_sheets_exporter_context_menu.txt
# The block writes to it even when it cannot get as far as loading
# the tool, so "no log file at all" means the block never ran - it is
# not in the startup.py Revit actually loaded.
# =====================================================================


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
            try:
                _rb_hosts.append(globals()[_rb_name])
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
