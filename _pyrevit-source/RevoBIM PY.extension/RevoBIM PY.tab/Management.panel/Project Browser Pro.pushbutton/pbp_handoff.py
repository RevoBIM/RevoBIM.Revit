# -*- coding: utf-8 -*-
u"""Project Browser Pro <-> Pro Sheets Exporter hand-off.

The browser cannot reach into Pro Sheets' window - they run in different
pyRevit engines - so they talk through two small key=value files under
%APPDATA%\\RevoBIM\\:

  prosheets_handoff.txt          written by the browser: which sheets, and
                                 whether to just open (print) or to run the
                                 last template straight through (express)
  prosheets_handoff_result.txt   written by Pro Sheets: started, then done or
                                 failed, with the output folder

Print needs nothing from Pro Sheets beyond what it already does: the browser
selects the sheets in Revit and posts the Pro Sheets button, and Pro Sheets
isolates a pre-selection when it opens. Express needs Pro Sheets to call
take() when it opens and finish() when the export ends - this module is
written so Pro Sheets can import it for exactly that (see the tool doc).

Pure Python. Both halves are proved on the bench against each other.
"""
import io
import os
import time

from pbp_compat import to_text
from pbp_settings import read_pairs, write_pairs, escape_list, unescape_list

HANDOFF_VERSION = 2
REQUEST_FILE = u'prosheets_handoff.txt'
RESULT_FILE = u'prosheets_handoff_result.txt'
MAX_AGE = 180.0        # seconds a request stays valid for Pro Sheets to take
ACK_TIMEOUT = 25.0     # seconds the browser waits for "started" on express
STALL_TIMEOUT = 300.0  # seconds with no progress before express is called stuck
LIVE = (u'started', u'running')
KINDS = (u'print', u'express')


def new_token():
    try:
        import uuid
        return to_text(uuid.uuid4().hex)
    except Exception:
        import random
        return u'{0:x}{1:x}'.format(int(time.time() * 1000), random.randint(0, 1 << 30))


def request_path(folder):
    return os.path.join(folder, REQUEST_FILE)


def result_path(folder):
    return os.path.join(folder, RESULT_FILE)


# ============================================================
# browser side
# ============================================================

def write_request(folder, kind, project, sheets, now=None):
    u"""sheets: list of (unique_id, sheet_number). Returns the token."""
    if kind not in KINDS:
        raise ValueError(u'unknown hand-off kind: ' + to_text(kind))
    token = new_token()
    pairs = {
        u'handoff_version': to_text(HANDOFF_VERSION),
        u'request': kind,
        u'token': token,
        u'created': u'{0:.3f}'.format(float(now if now is not None else time.time())),
        u'project': to_text(project),
        u'count': to_text(len(sheets)),
        u'sheet_uids': escape_list([s[0] for s in sheets]),
        u'sheet_numbers': escape_list([s[1] for s in sheets]),
        u'status': u'waiting',
        # Express runs with no Pro Sheets window at all: no Selection,
        # Format or Create page, no confirmation, no report. The browser
        # shows the only thing on screen (a small progress bar) and opens
        # the output folder itself when Pro Sheets says done.
        u'headless': u'1' if kind == u'express' else u'0',
        u'open_folder': u'0' if kind == u'express' else u'1',
    }
    # A result left from an earlier run must not answer this request.
    try:
        old = result_path(folder)
        if os.path.isfile(old):
            os.remove(old)
    except Exception:
        pass
    write_pairs(request_path(folder), pairs)
    return token


def poll(folder, token):
    u"""Pro Sheets' answer to this token, or None while there is none."""
    pairs = read_pairs(result_path(folder))
    if not pairs or pairs.get(u'token') != token:
        return None
    return {
        u'status': pairs.get(u'status', u''),
        u'folder': pairs.get(u'folder', u''),
        u'files': pairs.get(u'files', u'0'),
        u'message': pairs.get(u'message', u''),
        u'done': _int(pairs.get(u'done', u'0')),
        u'total': _int(pairs.get(u'total', u'0')),
        u'current': pairs.get(u'current', u''),
    }


def _int(text):
    try:
        return max(0, int(float(text)))
    except Exception:
        return 0


def percent(answer):
    u"""0-100 for the progress bar. Waiting and started are 0, done is 100,
    running is done / total, never above 99 until Pro Sheets says done -
    the last file is not finished until it has been checked on disk."""
    if answer is None:
        return 0
    status = answer.get(u'status')
    if status == u'done':
        return 100
    total = answer.get(u'total', 0)
    if status != u'running' or not total:
        return 0
    return min(99, int(100.0 * answer.get(u'done', 0) / total))


def stalled(last_change, now):
    return (float(now) - float(last_change)) > STALL_TIMEOUT


def waiting_too_long(started_at, now, answer):
    u"""Express was posted but Pro Sheets never said it started."""
    if answer is not None:
        return False
    return (float(now) - float(started_at)) > ACK_TIMEOUT


# ============================================================
# Pro Sheets side
# ============================================================

def take(folder, project, now=None):
    u"""For Pro Sheets to call when it opens.

    Returns {'request', 'token', 'sheet_uids', 'sheet_numbers'} for a fresh
    request about this project, marking it taken and answering 'started' -
    or None. A request is taken once, so reopening Pro Sheets later does not
    run an express export again.
    """
    pairs = read_pairs(request_path(folder))
    if not pairs:
        return None
    if pairs.get(u'status') != u'waiting':
        return None
    if pairs.get(u'request') not in KINDS:
        return None
    try:
        created = float(pairs.get(u'created', u'0'))
    except Exception:
        return None
    now = float(now if now is not None else time.time())
    if now - created > MAX_AGE or created - now > 5.0:
        return None
    if to_text(pairs.get(u'project', u'')) != to_text(project):
        return None
    pairs[u'status'] = u'taken'
    write_pairs(request_path(folder), pairs)
    token = pairs.get(u'token', u'')
    write_result(folder, token, u'started')
    return {
        u'request': pairs.get(u'request'),
        u'token': token,
        u'sheet_uids': unescape_list(pairs.get(u'sheet_uids', u'')),
        u'sheet_numbers': unescape_list(pairs.get(u'sheet_numbers', u'')),
        u'headless': pairs.get(u'headless', u'0') == u'1',
        u'open_folder': pairs.get(u'open_folder', u'1') == u'1',
    }


def write_result(folder, token, status, out_folder=u'', files=0, message=u'',
                 done=0, total=0, current=u''):
    write_pairs(result_path(folder), {
        u'handoff_version': to_text(HANDOFF_VERSION),
        u'token': to_text(token),
        u'status': to_text(status),
        u'folder': to_text(out_folder),
        u'files': to_text(files),
        u'message': to_text(message).replace(u'\r', u' ').replace(u'\n', u' '),
        u'done': to_text(done),
        u'total': to_text(total),
        u'current': to_text(current).replace(u'\r', u' ').replace(u'\n', u' '),
        u'finished': u'{0:.3f}'.format(float(time.time())),
    })


def progress(folder, token, done, total, current=u''):
    u"""For Pro Sheets to call after each file of an express export -
    `done` files of `total` written, `current` the sheet it is on next."""
    write_result(folder, token, u'running', done=done, total=total, current=current)


def finish(folder, token, ok, out_folder=u'', files=0, message=u''):
    u"""For Pro Sheets to call when an express export ends. `out_folder` is
    the folder the browser opens; Pro Sheets should not open it itself."""
    write_result(folder, token, u'done' if ok else u'failed', out_folder, files, message,
                 done=files, total=files)


# ============================================================
# is Pro Sheets able to take an express request?
# ============================================================
PROSHEETS_BUTTON = u'Pro Sheets Exporter.pushbutton'
HOOK_FILE = u'ps_express.py'


def prosheets_folder(here):
    u"""Pro Sheets' button folder, looked for under this tool's tab: in the
    Sheet Tools panel first, then anywhere. None when it is not there."""
    tab = os.path.dirname(os.path.dirname(os.path.abspath(here)))
    first = os.path.join(tab, u'Sheet Tools.panel', PROSHEETS_BUTTON)
    if os.path.isdir(first):
        return first
    try:
        for root, folders, files in os.walk(tab):
            for name in folders:
                if name.lower() == PROSHEETS_BUTTON.lower():
                    return os.path.join(root, name)
    except Exception:
        pass
    return None


def prosheets_version(folder):
    u"""Pro Sheets' version from its ps_version.py, or u''."""
    import re
    try:
        handle = io.open(os.path.join(folder, u'ps_version.py'), 'r', encoding='utf-8')
        try:
            text = handle.read()
        finally:
            handle.close()
    except Exception:
        return u''
    found = re.search(u"__version__\\s*=\\s*u?['\"]([^'\"]+)['\"]", text)
    return to_text(found.group(1)) if found else u''


def hook_state(here):
    u"""(folder, has the express hook, version). An express request sent
    to a Pro Sheets with no hook only opens its first page, so the browser
    asks this first. Pro Sheets not found at all: (None, True, u'') - it may
    live somewhere this cannot see, so the request is sent as before."""
    folder = prosheets_folder(here)
    if folder is None:
        return None, True, u''
    has_hook = os.path.isfile(os.path.join(folder, HOOK_FILE))
    return folder, has_hook, prosheets_version(folder)
