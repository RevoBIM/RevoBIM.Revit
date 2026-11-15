# -*- coding: utf-8 -*-
"""Express print: Project Browser Pro's headless run of the selected sheets.

Project Browser Pro's Express button selects sheets, writes a hand-off into
%APPDATA%\\RevoBIM and posts this tool's ribbon button. ``script.py`` calls
``run`` before it builds anything. When the hand-off asks for a headless
run, the Pro Sheets window is built **hidden**, so the last template, the
naming, the folder tokens and every format option load exactly as for a
normal run, and the window's own ``_do_export`` does the export. Nothing
about an export is re-implemented here; an express run is the run Export
would have made.

``run`` returns False - and the window opens as it always has - for no
hand-off, a stale one, another project's, a plain Print, or no Project
Browser Pro installed. Once a request has been taken it is always answered
through ``finish``, so the browser's progress strip never has to wait for
its own timeout.

``pbp_handoff`` is imported from Project Browser Pro's own folder, never
copied, so the two halves of the contract cannot drift apart. That folder
is **appended** to sys.path: Pro Sheets' own modules always win a name both
tools happen to use.

No .NET here. Everything Revit or WPF goes through the window module, which
is also what lets the bench drive this against a stand-in window.
"""

import os
import sys
import time
import traceback


BROWSER_PANEL = u'Management.panel'
BROWSER_BUTTON = u'Project Browser Pro.pushbutton'
HANDOFF_MODULE = 'pbp_handoff'
LOG_NAME = u'pro_sheets_express.txt'
LOG_LIMIT = 512 * 1024


# ==========================================================================
# small helpers
# ==========================================================================

def to_text(value):
    if value is None:
        return u''
    try:
        return u'{0}'.format(value)
    except Exception:
        try:
            return str(value).decode('utf-8', 'replace')
        except Exception:
            return u''


def appdata_folder():
    """%APPDATA%\\RevoBIM - where Project Browser Pro writes the hand-off."""
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'RevoBIM')


def log(text):
    """One line in the express log. Never throws."""
    try:
        folder = os.path.join(appdata_folder(), 'logs')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        path = os.path.join(folder, LOG_NAME)
        if os.path.isfile(path) and os.path.getsize(path) > LOG_LIMIT:
            os.remove(path)
        line = u'{0}  {1}\n'.format(
            time.strftime('%Y-%m-%d %H:%M:%S'), to_text(text))
        handle = open(path, 'ab')
        try:
            handle.write(line.encode('utf-8'))
        finally:
            handle.close()
    except Exception:
        pass


def browser_folder(here):
    """Project Browser Pro's button folder, or None when it is not installed.

    ``here`` is this button's folder: <tab>\\<panel>\\Pro Sheets Exporter.
    The Management panel is where the browser ships; anywhere else under
    the tab is found by a walk, because panels get reorganised and a moved
    button should not quietly turn Express into "nothing happened".
    """
    try:
        tab = os.path.dirname(os.path.dirname(os.path.abspath(here)))
    except Exception:
        return None
    first = os.path.join(tab, BROWSER_PANEL, BROWSER_BUTTON)
    if os.path.isfile(os.path.join(first, HANDOFF_MODULE + '.py')):
        return first
    try:
        for folder, folders, files in os.walk(tab):
            folders.sort()
            if HANDOFF_MODULE + '.py' in files:
                return folder
            # Nothing a pyRevit tab holds is deeper than a few levels; a
            # walk into a stray archive folder is not worth the wait.
            depth = folder[len(tab):].count(os.sep)
            if depth >= 3:
                del folders[:]
    except Exception:
        pass
    return None


def load_handoff(folder):
    """The browser's pbp_handoff module, or None."""
    if not folder:
        return None
    if folder not in sys.path:
        sys.path.append(folder)                # appended, never inserted
    try:
        return __import__(HANDOFF_MODULE)
    except Exception as err:
        log(u'pbp_handoff would not load from {0}: {1}'.format(folder, err))
        return None


def as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [to_text(item).strip() for item in value]
    text = to_text(value)
    for mark in (u'|', u';', u','):
        if mark in text:
            return [part.strip() for part in text.split(mark)]
    return [text.strip()] if text.strip() else []


def as_flag(value):
    if isinstance(value, bool):
        return value
    return to_text(value).strip().lower() in (u'1', u'true', u'yes', u'on')


def wanted_keys(rows, uids, numbers, uid_of):
    """The row keys of the sheets sent, in the order sent, and how many missed.

    By UniqueId first. The sheet number is a fallback for an id that no
    longer matches (a sheet deleted and remade under the same number) and
    it only ever matches **sheets**: in Views mode a row's number carries
    the view type, and "Floor Plan" is not a drawing anybody sent.
    """
    by_uid = {}
    by_number = {}
    for row in rows or ():
        if not getattr(row, 'is_sheet', False):
            continue
        uid = to_text(uid_of(row))
        if uid:
            by_uid[uid] = row.key
        number = to_text(getattr(row, 'number', u'')).strip()
        if number and number not in by_number:
            by_number[number] = row.key
    uids = list(uids or ())
    numbers = list(numbers or ())
    found = []
    missed = 0
    for index in range(max(len(uids), len(numbers))):
        uid = uids[index] if index < len(uids) else u''
        number = numbers[index] if index < len(numbers) else u''
        key = by_uid.get(uid) if uid else None
        if key is None and number:
            key = by_number.get(number)
        if key is None:
            missed += 1
        elif key not in found:
            found.append(key)
    return found, missed


def failure_message(failed, limit=3):
    """One line on what did not write: '2 did not write - M-03 [PDF]: offline'."""
    failed = list(failed or ())
    if not failed:
        return u''
    parts = []
    for outcome in failed[:limit]:
        text = u'{0} [{1}]'.format(to_text(getattr(outcome, 'label', u'')),
                                   to_text(getattr(outcome, 'fmt', u''))
                                   .upper())
        reason = to_text(getattr(outcome, 'message', u'')).strip()
        if reason:
            text = u'{0}: {1}'.format(text, reason.splitlines()[0])
        parts.append(text)
    more = len(failed) - limit
    if more > 0:
        parts.append(u'and {0} more'.format(more))
    return u'{0} did not write - {1}'.format(len(failed), u'; '.join(parts))


def sheet_uid(row):
    try:
        return row.element.UniqueId
    except Exception:
        return u''


# ==========================================================================
# the hook
# ==========================================================================

def run(uiapp, here):
    """True when an express request was taken and answered here."""
    folder = appdata_folder()
    try:
        browser = browser_folder(here)
        if not browser:
            return False                       # no Project Browser Pro
        handoff = load_handoff(browser)
        if handoff is None:
            return False
        doc = uiapp.ActiveUIDocument.Document
        request = handoff.take(folder, to_text(doc.Title))
    except Exception as err:
        log(u'the hand-off could not be read: {0}'.format(err))
        return False
    if not request:
        return False                           # none, stale or another project
    if not as_flag(request.get('headless')):
        log(u'plain print request - opening the window')
        return False
    token = request.get('token')
    log(u'express request {0}: {1} sheet(s)'.format(
        to_text(token), len(as_list(request.get('sheet_uids')))))
    try:
        express(uiapp, doc, request, handoff, folder)
    except Exception as err:
        log(traceback.format_exc())
        _fail(handoff, folder, token, u'Pro Sheets stopped: {0}'.format(err))
    return True


def _fail(handoff, folder, token, message):
    log(u'refused: {0}'.format(message))
    try:
        handoff.finish(folder, token, False, u'', 0, message)
    except Exception as err:
        log(u'finish could not be written: {0}'.format(err))
    return False


def express(uiapp, doc, request, handoff, folder, window_module=None):
    """Build the window hidden, tick the sheets sent, export, report back."""
    if window_module is None:
        import ps_window as window_module
    token = request.get('token')

    running = getattr(window_module, 'WINDOW', None)
    if running is not None and getattr(running, 'exporting', False):
        return _fail(handoff, folder, token,
                     u'Pro Sheets is already exporting. Try again when it '
                     u'has finished.')

    # The first-run setup window is the one thing the constructor can put
    # on screen. Held off for the build, and always put back.
    setup = window_module.ps_setupwin
    needed = setup.needed
    setup.needed = lambda *args, **kwargs: False
    try:
        win = window_module.ProSheetsWindow(uiapp)
    finally:
        setup.needed = needed

    try:
        return _express(uiapp, win, request, handoff, folder, token,
                        window_module)
    finally:
        _close_quietly(win)


def _express(uiapp, win, request, handoff, folder, token, window_module):
    ps_export = window_module.ps_export
    ps_paths = window_module.ps_paths
    ps_ui = window_module.ps_ui

    _stop_timers(win)
    _force_sheets(win)

    uids = as_list(request.get('sheet_uids'))
    numbers = as_list(request.get('sheet_numbers'))
    keys, missed = wanted_keys(win.rows, uids, numbers, sheet_uid)
    if not keys:
        return _fail(handoff, folder, token,
                     u'None of the {0} sheet(s) sent were found in this '
                     u'model.'.format(max(len(uids), len(numbers))))
    _tick_exactly(win, keys)

    formats = win.chosen_formats()
    if not formats:
        return _fail(handoff, folder, token,
                     u'The last Pro Sheets template has no format ticked. '
                     u'Open Pro Sheets, tick PDF or DWG and save it.')
    jobs, _clashes = win.plan_jobs()
    if not jobs:
        return _fail(handoff, folder, token, u'Nothing to export.')

    # A print driver with no "Driver saves to" folder cannot write a single
    # file. The window would ask; express has nobody to ask, so it takes
    # the answer the window recommends.
    if win._pdf_blocker(formats):
        log(u'"{0}" has no staging folder - using Revit\'s own PDF '
            u'exporter'.format(ps_ui.combo_text(win.c('PrinterCombo'))))
        ps_ui.fill_combo(win.c('PrinterCombo'), win.printer_list,
                         selected=window_module.REVIT_PDF)
        win._printer_changed(None, None)

    root = win._text_of('RootFolderBox')
    ok, error = ps_paths.writable(root)
    if not ok:
        return _fail(handoff, folder, token,
                     u'The export folder cannot be written to: {0} ({1})'
                     .format(root, error))

    profile = win._collect_profile()
    total = win._file_count(jobs, formats)
    log(u'{0} sheet(s) ({1} not found), formats {2}, {3} file(s), root {4}'
        .format(len(jobs), missed, u'+'.join(formats), total, root))

    win._hunted_folder = u''
    try:
        win._issue_folder = win.issue_folder(jobs, formats)
    except Exception:
        win._issue_folder = u''

    # No report window: the browser opens the folder itself.
    reports = []
    win._show_report = lambda report: reports.append(report)

    # Each file reported to the browser's progress strip as it starts.
    own_progress = win._progress

    def progress(index, count, label, fmt):
        done = win._progress_done
        own_progress(index, count, label, fmt)
        try:
            handoff.progress(folder, token, done, win._export_total,
                             to_text(label))
        except Exception:
            pass
    win._progress = progress

    ps_export.debug_reset()
    ps_export.begin_suppression(uiapp)
    try:
        win._begin_progress(total)
        try:
            handoff.progress(folder, token, 0, total, u'')
        except Exception:
            pass
        win._do_export(uiapp, jobs, formats, profile)
    finally:
        # _do_export hands suppression back itself; this is for the run
        # that threw before it got there. Revit answering its own dialogs
        # after the tool has gone is not something to leave to chance.
        ps_export.end_suppression()

    report = reports[-1] if reports else win.last_report
    if report is None:
        return _fail(handoff, folder, token,
                     u'The export finished without a report.')
    written = report.written()
    failed = report.failed()
    message = failure_message(failed)
    if missed:
        note = u'{0} sheet(s) sent were not found'.format(missed)
        message = u'{0}; {1}'.format(message, note) if message else note
    if report.cancelled:
        message = u'Cancelled. {0}'.format(message).strip()
    ok = bool(written) and not report.cancelled
    out_folder = to_text(win.folder_to_open(report))
    log(u'{0} - {1}'.format(to_text(report.summary()), message or u'ok'))
    handoff.finish(folder, token, ok, out_folder, len(written), message)
    return ok


# ==========================================================================
# the window, hidden
# ==========================================================================

def _stop_timers(win):
    for name in ('_theme_timer', '_filter_timer'):
        timer = getattr(win, name, None)
        if timer is None:
            continue
        try:
            timer.Stop()
        except Exception:
            pass


def _force_sheets(win):
    """A template saved in Views mode has no sheets in it."""
    if win._is_views_mode():
        try:
            win.c('ViewsRadio').IsChecked = False
            win.c('SheetsRadio').IsChecked = True
        except Exception:
            pass
    # Flipping the radio re-reads the model only once the window is ready.
    if any(not getattr(row, 'is_sheet', False) for row in win.rows):
        win._mode_changed(None, None)


def _tick_exactly(win, keys):
    """Exactly the sheets sent; whatever the template had ticked goes."""
    wanted = set([to_text(key) for key in keys])
    win._suspend_ticks = True
    try:
        for entry in win.table.Rows:
            key = to_text(entry['key'])
            if not key:
                continue                       # a group heading
            entry['sel'] = key in wanted
    finally:
        win._suspend_ticks = False


def _close_quietly(win):
    """Close the hidden window without close()'s questions."""
    _stop_timers(win)
    try:
        win.exporting = False
    except Exception:
        pass
    try:
        win.register.close()
    except Exception:
        pass
    try:
        win.window.Close()
    except Exception:
        pass
