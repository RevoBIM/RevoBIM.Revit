# -*- coding: utf-8 -*-
"""Space Data Push - the rules. No WPF and no Revit in here, so every rule can
be run against a table of cases under plain CPython (see bench_logic.py).

Contents: settings, the value-conversion plan, keyword filtering, row encoding,
theme modes, the job queue and the result summaries.
"""
import io
import os
import re
import time

NONE_LABEL = u'(none)'

THEME_MODES = ['follow', 'dark', 'light']
THEME_LABELS = {'follow': u'Auto', 'dark': u'Dark', 'light': u'Light'}

SETTINGS_FILE = 'space_data_push.txt'
DEBUG_FILE = 'space_data_push_debug.txt'
ERROR_FILE = 'space_data_push_last_error.txt'
ALIVE_FILE = 'space_data_push_alive.txt'

BOOL_KEYS = ['overwrite', 'skip_blank', 'keep_picking', 'hide_window', 'debug']

DEFAULTS = {
    'theme': 'follow',
    'category': '',
    'rows': u'',
    'rows_saved': '0',
    'overwrite': '1',
    'skip_blank': '1',
    'keep_picking': '1',
    'hide_window': '1',
    'debug': '1',
    'win_w': '',
    'win_h': '',
}
KEY_ORDER = ['theme', 'category', 'rows_saved', 'rows', 'overwrite',
             'skip_blank', 'keep_picking', 'hide_window', 'debug', 'win_w', 'win_h']


class UserMessage(Exception):
    """A condition the user should be told about in a sentence, no traceback."""
    pass


def to_text(value):
    try:
        return u'%s' % (value,)
    except Exception:
        try:
            return repr(value).decode('utf-8', 'replace')
        except Exception:
            return u'?'


# ----------------------------------------------------------------- settings

def appdata_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    folder = os.path.join(base, 'RevoBIM')
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
    except Exception:
        pass
    return folder


def settings_path():
    return os.path.join(appdata_dir(), SETTINGS_FILE)


def parse_settings(text):
    """key=value lines. Split on the FIRST '=' only."""
    out = {}
    for line in (text or u'').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        out[key.strip()] = value.strip()
    return out


def clean_settings(raw):
    """Key by key onto the defaults. Unknown keys (older versions) are dropped."""
    out = dict(DEFAULTS)
    raw = raw or {}
    for key in DEFAULTS:
        if key in raw:
            out[key] = raw[key]
    if out['theme'] not in THEME_MODES:
        out['theme'] = DEFAULTS['theme']
    for key in BOOL_KEYS:
        out[key] = '1' if to_text(out[key]) in ('1', 'true', 'True', 'yes') else '0'
    if to_text(out['rows_saved']) != '1':
        out['rows_saved'] = '0'
    if not re.match(r'^-?\d+$', to_text(out['category'])):
        out['category'] = ''
    for key in ('win_w', 'win_h'):
        if not re.match(r'^\d+$', to_text(out[key])):
            out[key] = ''
    return out


def dump_settings(settings):
    lines = [u'# Space Data Push settings - plain key=value, safe to edit by hand']
    for key in KEY_ORDER:
        lines.append(u'%s=%s' % (key, to_text(settings.get(key, DEFAULTS[key]))))
    return u'\n'.join(lines) + u'\n'


def load_settings():
    raw = {}
    try:
        path = settings_path()
        if os.path.exists(path):
            with io.open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                raw = parse_settings(fh.read())
    except Exception:
        raw = {}
    return clean_settings(raw)


def save_settings(settings):
    try:
        text = dump_settings(clean_settings(settings))
        with io.open(settings_path(), 'w', encoding='utf-8') as fh:
            fh.write(text)
        return True
    except Exception:
        return False


_DEBUG = [True]


def set_debug(flag):
    _DEBUG[0] = bool(flag)


def log_debug(text):
    if not _DEBUG[0]:
        return
    try:
        path = os.path.join(appdata_dir(), DEBUG_FILE)
        try:
            if os.path.exists(path) and os.path.getsize(path) > 800000:
                os.remove(path)
        except Exception:
            pass
        with io.open(path, 'a', encoding='utf-8') as fh:
            fh.write(u'%s  %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), to_text(text)))
    except Exception:
        pass


# ------------------------------------------------------- row / text encoding

def esc(text):
    """Escape the characters the row encoding uses. '%' goes first."""
    text = to_text(text)
    return (text.replace(u'%', u'%25').replace(u'|', u'%7C')
            .replace(u'>', u'%3E').replace(u'\n', u'%0A'))


def unesc(text):
    text = to_text(text)
    return (text.replace(u'%0A', u'\n').replace(u'%3E', u'>')
            .replace(u'%7C', u'|').replace(u'%25', u'%'))


def encode_rows(pairs):
    return u'|'.join(esc(a) + u'>>' + esc(b) for a, b in pairs)


def decode_rows(text):
    out = []
    if not text:
        return out
    for chunk in to_text(text).split(u'|'):
        if u'>>' in chunk:
            left, right = chunk.split(u'>>', 1)
        else:
            left, right = chunk, u''
        left = unesc(left)
        right = unesc(right)
        if left:
            out.append((left, right))
    return out


def find_duplicate_targets(pairs):
    """Element parameter names used by more than one row (blank ignored)."""
    seen = {}
    reported = {}
    dupes = []
    for _src, dst in pairs:
        if not dst:
            continue
        key = dst.lower()
        if key in seen and key not in reported:
            dupes.append(dst)
            reported[key] = True
        seen[key] = True
    return dupes


def keyword_filter(names, query):
    """Names holding EVERY word typed, case-insensitively.

    Returns (names, matched). A search that matches nothing leaves the full list
    and reports matched=False, so a dropdown is never emptied by a typo.
    """
    words = [w for w in to_text(query or u'').lower().split() if w]
    if not words:
        return list(names), True
    out = [n for n in names if all(w in n.lower() for w in words)]
    if out:
        return out, True
    return list(names), False


# ---------------------------------------------------------- value conversion

class Snap(object):
    """What a parameter held at the moment it was read, with no Revit in it."""

    def __init__(self, name, storage, has, text, raw, spec=u''):
        self.name = name
        self.storage = storage
        self.has = has
        self.text = text
        self.raw = raw
        self.spec = spec


def spec_key(text):
    """'autodesk.spec.aec:area-2.0.0' -> 'autodesk.spec.aec:area'."""
    t = to_text(text or u'').strip().lower()
    if not t:
        return u''
    m = re.match(r'^(.*)-\d+(\.\d+)*$', t)
    return m.group(1) if m else t


def short_spec(key):
    key = to_text(key)
    return key.split(u':')[-1] if u':' in key else key


_NUM = re.compile(r'^\s*-?\d+(?:[.,]\d+)?\s*$')


def parse_number(text):
    if text is None or not _NUM.match(to_text(text)):
        return None
    return float(to_text(text).strip().replace(u',', u'.'))


def plan_value(src, dst_storage, dst_spec, skip_blank=True):
    """Decide how a space value goes into a target parameter.

    Returns (action, value, note). action is one of:
      string, int, double  - set that value directly
      valuestring          - hand the text to Parameter.SetValueString
      skip                 - do not write; note says why
    """
    text = src.text if src.text is not None else u''
    blank = (not src.has) or text == u''
    if blank:
        if skip_blank:
            return (u'skip', None, u'the space value is blank')
        if dst_storage == u'String':
            return (u'string', u'', u'')
        return (u'skip', None, u'a blank value cannot be written to a number parameter')

    if dst_storage == u'String':
        return (u'string', text, u'')

    if dst_storage == u'Integer':
        if src.storage == u'Integer':
            return (u'int', int(src.raw), u'')
        number = parse_number(text)
        if number is not None and number == int(number):
            return (u'int', int(number), u'')
        return (u'skip', None, u'"%s" does not fit a whole-number parameter' % text)

    if dst_storage == u'Double':
        if src.storage == u'Double':
            a = spec_key(src.spec)
            b = spec_key(dst_spec)
            if a and b and a != b:
                return (u'skip', None, u'units differ (%s into %s)' % (short_spec(a), short_spec(b)))
            return (u'double', float(src.raw), u'')
        if src.storage in (u'String', u'Integer'):
            return (u'valuestring', text, u'')
        return (u'skip', None, u'a reference value cannot go into a number parameter')

    if dst_storage == u'ElementId':
        return (u'skip', None, u'element-reference parameters are not supported')
    return (u'skip', None, u'the parameter has no writable storage type')


def verify_write(action, value, back):
    """Does what was read back after the write agree with what was asked for?"""
    try:
        if action == u'string':
            return (back or u'') == (value or u'')
        if action == u'int':
            return back is not None and int(back) == int(value)
        if action == u'double':
            if back is None:
                return False
            v = float(value)
            return abs(float(back) - v) <= 1e-7 * max(1.0, abs(v))
        if action == u'valuestring':
            return bool(back)
    except Exception:
        return False
    return False


def target_is_blank(storage, has, text):
    if not has:
        return True
    return storage == u'String' and not (text or u'')


class RowResult(object):
    """One mapped row's outcome: status is ok, same, skip or fail."""

    def __init__(self, src, dst, status, detail=u''):
        self.src = src
        self.dst = dst
        self.status = status
        self.detail = detail


def result_counts(results):
    counts = {u'ok': 0, u'same': 0, u'skip': 0, u'fail': 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts


def result_level(counts):
    if counts.get(u'fail'):
        return u'fail'
    if counts.get(u'skip'):
        return u'warn'
    return u'ok'


def result_summary(counts):
    parts = []
    for key, word in ((u'ok', u'written'), (u'same', u'unchanged'),
                      (u'skip', u'skipped'), (u'fail', u'failed')):
        if counts.get(key):
            parts.append(u'%d %s' % (counts[key], word))
    return u', '.join(parts) if parts else u'nothing to write'


def result_line(r):
    return u'%s  ->  %s    %s' % (r.src, r.dst, r.detail)


def preview_text(snap, have_space):
    """(text, kind) for the value shown beside a space parameter row."""
    if not have_space:
        return (u'-', u'none')
    if snap is None:
        return (u'(no such parameter)', u'blank')
    if (not snap.has) or (snap.text or u'') == u'':
        return (u'(blank)', u'blank')
    return (snap.text, u'value')


def space_caption(number, name, level):
    number = to_text(number or u'').strip()
    name = to_text(name or u'').strip()
    level = to_text(level or u'').strip()
    if number and name:
        head = u'%s - %s' % (number, name)
    else:
        head = number or name or u'(unnamed space)'
    return u'%s  (%s)' % (head, level) if level else head


# ---------------------------------------------------------------- theme modes

def next_theme_mode(mode):
    try:
        return THEME_MODES[(THEME_MODES.index(mode) + 1) % len(THEME_MODES)]
    except ValueError:
        return THEME_MODES[0]


def resolve_theme(mode, revit_theme):
    """'follow' takes Revit's canvas theme when it can be read, else dark."""
    if mode in ('dark', 'light'):
        return mode
    if revit_theme in ('dark', 'light'):
        return revit_theme
    return 'dark'


# ------------------------------------------------------------------ job queue

class JobQueue(object):
    """Jobs waiting for the ExternalEvent. Only a refused job is ever removed:
    wiping the whole queue on a refusal loses callbacks and leaves the window
    busy for ever."""

    def __init__(self):
        self._jobs = []

    def push(self, job):
        self._jobs.append(job)
        return job

    def drain(self):
        jobs = self._jobs
        self._jobs = []
        return jobs

    def discard(self, job):
        try:
            self._jobs.remove(job)
        except ValueError:
            pass

    def __len__(self):
        return len(self._jobs)


# ------------------------------------------------------------- alive-proof note

def alive_note(version, stamp):
    """Written just before the window is shown; the first handler that runs
    deletes it. A note still there at the next launch means the window opened and
    nothing in it ever responded - the engine was torn down under it."""
    return u'%s|%s' % (to_text(version), to_text(stamp))


def note_is_stale(text, version):
    """True when a note from THIS version is still on disk. A note from another
    version proves nothing about this one."""
    text = to_text(text or u'').strip()
    if not text or u'|' not in text:
        return False
    return text.split(u'|', 1)[0] == to_text(version)


def merge_names(names, extra):
    """names plus any of extra not already present (case-insensitive), sorted."""
    have = {}
    for n in names:
        have[to_text(n).lower()] = n
    for n in extra:
        if n and to_text(n).lower() not in have:
            have[to_text(n).lower()] = n
    return sorted(have.values(), key=lambda n: to_text(n).lower())
