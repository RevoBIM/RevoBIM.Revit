# -*- coding: utf-8 -*-

"""Legend Creator - foundations: version, settings, the run's record.

Pure Python. log() always records to memory and writes the debug file only
when Debug is ticked; swallowed() notes an error a handler chose to absorb.
"""

__version__ = '3.0.0'

import io
import os
import sys
import time
import traceback

from lgc_logic import (DEFAULT_CASE, DEFAULT_COLUMN_SPACING_MM,
                       DEFAULT_LINE_WEIGHT, DEFAULT_NAME_PARAM, DEFAULT_PHASE,
                       DEFAULT_SCALE, ROW_SPACING_MM, SWATCH_W_MM,
                       SYSTEM_DEFAULT_SCALE, SYS_ROW_PITCH_MM, SYS_TEXT_GAP_MM,
                       TEXT_OFFSET_MM)


SETTINGS_DIR = os.path.join(os.getenv('APPDATA') or '', 'RevoBIM')


SETTINGS_FILE = os.path.join(SETTINGS_DIR, 'legend_creator.txt')


LOG_FILE = os.path.join(SETTINGS_DIR, 'legend_creator_debug.txt')


# Off unless the Debug tick is on, so a normal run writes nothing to disk.
_DEBUG = {'on': False}


# What happened this run, kept in memory whether or not Debug is on, so a
# crash can always be reported in full. Nothing reaches the disk unless the
# Debug tick is on.
_TRACE = {'lines': [], 't0': time.time(), 'absorbed': {}, 'order': [],
          'crash': None}


TRACE_LIMIT = 3000


REPORT_FILE = os.path.join(SETTINGS_DIR, 'legend_creator_debug_report.txt')


def reset_trace():
    """Start a run's record afresh. pyRevit may keep this module loaded
    between runs, and a report that carried the last run's lines and crash
    would send the hunt after something that already happened."""
    del _TRACE['lines'][:]
    _TRACE['absorbed'].clear()
    del _TRACE['order'][:]
    _TRACE['crash'] = None
    _TRACE['t0'] = time.time()
    _TRACE.pop('theme', None)
    _DEBUG['on'] = False


def log(message):
    """Record a step: always in memory, in the debug file when ticked."""
    try:
        line = u'[{0:7.2f}s] {1}'.format(time.time() - _TRACE['t0'], message)
    except Exception:
        line = u'[      ?] (unprintable message)'
    lines = _TRACE['lines']
    lines.append(line)
    if len(lines) > TRACE_LIMIT:
        del lines[:len(lines) - TRACE_LIMIT]
    if not _DEBUG['on']:
        return
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
        handle = io.open(LOG_FILE, 'a', encoding='utf-8')
        try:
            handle.write(line + u'\n')
        finally:
            handle.close()
    except Exception:
        pass


def swallowed():
    """Note an exception that a handler chose to absorb.

    Called from inside an except block. The tool absorbs errors on purpose -
    a missing parameter, an older API member - so that one odd element does
    not stop a run. The price is that a Revit release that differs makes the
    tool quietly do less. Recording each one, where it happened and how
    often, is what turns "it does not work" into something fixable.
    """
    try:
        _kind, value, tb = sys.exc_info()
        if value is None:
            return
        where = u'?'
        try:
            frames = traceback.extract_tb(tb)
            if frames:
                last = frames[-1]
                where = u'{0}() line {1}'.format(last[2], last[1])
        except Exception:
            pass
        key = (where, err_text(value))
        book = _TRACE['absorbed']
        if key not in book:
            book[key] = 0
            _TRACE['order'].append(key)
            if len(_TRACE['order']) <= 400:
                log(u'   absorbed in {0}: {1}'.format(key[0], key[1]))
        book[key] += 1
    except Exception:
        pass


def start_debug(on):
    """Switch the debug file on or off for this run."""
    was = _DEBUG['on']
    _DEBUG['on'] = bool(on)
    if on and not was:
        try:
            import datetime
            stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            stamp = u''
        log(u'#' * 60)
        log(u'Legend Creator {0}   {1}   debug on'.format(__version__, stamp))


def crash_text():
    """The Python traceback, plus the .NET exception behind it when there is
    one - Revit's own stack is often where the useful line is."""
    text = traceback.format_exc()
    try:
        value = sys.exc_info()[1]
        net = getattr(value, 'clsException', None)
        if net is not None:
            text += u'\n.NET exception:\n{0}'.format(net.ToString())
    except Exception:
        pass
    return text


# ---------------------------------------------------------------------------
# Settings - plain key=value, falling back key by key
# ---------------------------------------------------------------------------
# Distances are stored at REFERENCE_SCALE, not at whatever scale was last
# used, so changing the scale never compounds a previous scaling.
DEFAULTS = {
    'phase': DEFAULT_PHASE,
    'name_param': DEFAULT_NAME_PARAM,
    'text_type': '',
    'text_case': DEFAULT_CASE,
    'combined': '0',
    'scale': str(DEFAULT_SCALE),
    'row_spacing': str(ROW_SPACING_MM),
    'text_offset': str(TEXT_OFFSET_MM),
    'column_spacing': str(DEFAULT_COLUMN_SPACING_MM),
    'sys_kind': 'containment',
    'sys_template': '',
    'sys_scale': str(SYSTEM_DEFAULT_SCALE),
    'sys_text_type': '',
    'sys_head_type': '',
    'sys_swatch_w': str(SWATCH_W_MM),
    'sys_swatch_h': 'containment=700;ductwork=700;pipework=300',
    'sys_row_pitch': str(SYS_ROW_PITCH_MM),
    'sys_text_gap': str(SYS_TEXT_GAP_MM),
    'sys_view_name': '',
    'sys_upper': '1',
    'sys_line_weight': str(DEFAULT_LINE_WEIGHT),
    'theme_mode': 'auto',
    'debug': '0',
}


def load_settings():
    values = dict(DEFAULTS)
    try:
        if os.path.isfile(SETTINGS_FILE):
            handle = open(SETTINGS_FILE, 'r')
            try:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, value = line.split('=', 1)
                    key = key.strip()
                    if key in values:          # unknown keys ignored
                        values[key] = value.strip()
            finally:
                handle.close()
    except Exception:
        swallowed()
    return values


def save_settings(values):
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
        handle = open(SETTINGS_FILE, 'w')
        try:
            handle.write('# RevoBIM PY - Legend Creator\n')
            for key in sorted(values.keys()):
                handle.write('{0}={1}\n'.format(key, values[key]))
        finally:
            handle.close()
    except Exception:
        swallowed()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def err_text(err):
    """First line of an exception message, as unicode, never raising.

    .NET messages can carry non-ASCII - a family name, a degree sign - and
    str() on them is not safe under every engine pyRevit ships.
    """
    try:
        text = u'{0}'.format(err)
    except Exception:
        try:
            text = u'{0}'.format(repr(err))
        except Exception:
            text = u'unreadable error'
    return text.split(u'\n')[0]


def eid_value(element_id):
    """ElementId.Value (2024+) or .IntegerValue (removed in 2026)."""
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        swallowed()
    try:
        return element_id.IntegerValue
    except Exception:
        swallowed()
        return 0
