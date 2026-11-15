# -*- coding: utf-8 -*-
"""Pure logic for Explode Import Symbol Multiple.

Nothing in here touches .NET or the Revit API, so bench_logic.py runs all of it
under plain CPython. Works on IronPython 2.7 and IronPython 3 alike.
"""

# ==========================================================================
# Settings
# ==========================================================================

SETTINGS_VERSION = 1

DEFAULTS = {
    u'settings_version': u'1',
    u'theme': u'follow',          # follow / dark / light
    u'last_mode': u'partial',     # partial / full
    u'select_results': u'1',
    u'debug': u'1',
    u'suppress_dialogs': u'1',
}

# version -> {key: value} applied to files written by an older version
MIGRATIONS = {}

THEME_SETTINGS = (u'follow', u'dark', u'light')
MODES = (u'partial', u'full')


def parse_settings(text):
    """key=value lines, split on the first '=' only. Damaged lines are skipped
    and every missing key falls back to its default."""
    out = dict(DEFAULTS)
    seen = {}
    for raw in (text or u'').splitlines():
        line = raw.strip()
        if not line or line.startswith(u'#') or u'=' not in line:
            continue
        key, value = line.split(u'=', 1)
        key = key.strip()
        if key in DEFAULTS:
            seen[key] = value.strip()
    out.update(seen)
    try:
        file_version = int(seen.get(u'settings_version', u'0'))
    except Exception:
        file_version = 0
    for ver in sorted(MIGRATIONS):
        if file_version < ver:
            out.update(MIGRATIONS[ver])
    out[u'settings_version'] = u'{0}'.format(SETTINGS_VERSION)
    if out[u'theme'] not in THEME_SETTINGS:
        out[u'theme'] = DEFAULTS[u'theme']
    if out[u'last_mode'] not in MODES:
        out[u'last_mode'] = DEFAULTS[u'last_mode']
    for flag in (u'select_results', u'debug', u'suppress_dialogs'):
        if out[flag] not in (u'0', u'1'):
            out[flag] = DEFAULTS[flag]
    return out


def dump_settings(settings):
    lines = [u'# RevoBIM - Explode Import Symbol Multiple settings']
    for key in sorted(DEFAULTS):
        lines.append(u'{0}={1}'.format(key, settings.get(key, DEFAULTS[key])))
    return u'\n'.join(lines) + u'\n'


# ==========================================================================
# Theme
# ==========================================================================

def resolve_theme(setting, canvas_is_dark):
    """'dark' or 'light'. canvas_is_dark is True / False / None (unknown).
    Unknown canvas while following falls back to dark, the house default."""
    if setting == u'dark':
        return u'dark'
    if setting == u'light':
        return u'light'
    if canvas_is_dark is None:
        return u'dark'
    return u'dark' if canvas_is_dark else u'light'


def next_theme_setting(current):
    """The header chip cycles Auto -> Dark -> Light -> Auto."""
    order = list(THEME_SETTINGS)
    try:
        return order[(order.index(current) + 1) % len(order)]
    except ValueError:
        return order[0]


def theme_chip_label(setting):
    return {u'follow': u'Auto', u'dark': u'Dark', u'light': u'Light'}.get(setting, u'Auto')


# ==========================================================================
# Ids
# ==========================================================================

def eid_value(element_id):
    """ElementId -> int for Revit 2024-2027. .Value first (IntegerValue was
    removed in 2026), the old property only as a guarded fallback."""
    if element_id is None:
        return 0
    try:
        return int(element_id.Value)
    except Exception:
        pass
    try:
        return int(getattr(element_id, 'Integer' + 'Value'))
    except Exception:
        return 0


# ==========================================================================
# What gets exploded
# ==========================================================================

def classify(items):
    """items: dicts with key, is_import, is_linked, pinned, name.

    Linked CAD cannot be exploded (Revit's own rule), and anything that is not
    an import symbol is left out. Returns a dict with the keys to explode, the
    linked ones skipped, the count of other elements and the pinned keys."""
    explode, linked, pinned, names = [], [], [], {}
    other = 0
    for it in items:
        if not it.get('is_import'):
            other += 1
            continue
        if it.get('is_linked'):
            linked.append(it['key'])
            continue
        explode.append(it['key'])
        names[it['key']] = it.get('name') or u'Import symbol'
        if it.get('pinned'):
            pinned.append(it['key'])
    return {'explode': explode, 'linked': linked, 'other': other,
            'pinned': pinned, 'names': names}


def plural(n, word, many=None):
    return u'{0} {1}'.format(n, word if n == 1 else (many or word + u's'))


def summary_lines(cls):
    """(headline, detail) for the prompt."""
    n = len(cls['explode'])
    if n == 0:
        head = u'No import symbols selected'
    else:
        head = u'{0} selected'.format(plural(n, u'import symbol'))
    notes = []
    if cls['linked']:
        notes.append(u'{0} skipped - linked CAD cannot be exploded'.format(
            plural(len(cls['linked']), u'linked file')))
    if cls['other']:
        notes.append(u'{0} that {1} not import symbols left alone'.format(
            plural(cls['other'], u'element'), u'is' if cls['other'] == 1 else u'are'))
    if n == 0 and not notes:
        notes.append(u'Select one or more imported CAD symbols in the view, then run the tool again.')
    if cls['pinned']:
        notes.append(u'{0} will be unpinned to explode'.format(plural(len(cls['pinned']), u'pinned import')))
    return head, u'. '.join(notes) + (u'.' if notes else u'')


# ==========================================================================
# Ribbon matching
# ==========================================================================

# Revit journals the two commands as Control_Essentials_ImportPartialExplode
# and Control_Essentials_ImportExplode inside Dialog_Essentials_ImportInstanceExplode.
RIBBON_KEYS = {
    u'partial': (u'control_essentials_importpartialexplode', u'partial explode'),
    u'full': (u'control_essentials_importexplode', u'full explode'),
}


def _norm_text(text):
    return u' '.join((text or u'').replace(u'&', u'').replace(u'_', u' ').lower().split())


def ribbon_item_matches(mode, item_id, item_text):
    """True when a ribbon item is the explode command for this mode. The id is
    the reliable test; the English label is the fallback."""
    id_key, text_key = RIBBON_KEYS[mode]
    low = (item_id or u'').lower()
    if id_key in low:
        if mode == u'full' and u'partial' in low:
            return False
        return True
    if low and u'explode' in low:
        return False      # an explode id that is not ours - never fall back to its label
    return _norm_text(item_text) == text_key


# ==========================================================================
# The run, one import at a time
# ==========================================================================

FIND_TIMEOUT = 8.0      # seconds to wait for the ribbon to offer Explode
UIA_AFTER = 2.5         # no ribbon item by then -> try UI Automation once
WAIT_TIMEOUT = 6.0      # idle seconds after invoking before calling it refused
MAX_ATTEMPTS = 2


class ExplodePlan(object):
    """State machine driven from Revit's Idling event.

    Revit has no API for explode and greys its own button out when more than
    one import is selected, so the tool selects each import on its own, waits
    for the contextual ribbon to offer Explode, presses it, and waits for the
    import to disappear - which is the only honest proof it exploded.

    tick(now, exists, button) returns (action, key):
      select      put this import alone in the selection
      invoke      press the ribbon command
      invoke_uia  press it through UI Automation instead
      none        nothing to do this tick
      finished    every import has a result
    button is 'enabled', 'disabled' or 'missing'.
    """

    def __init__(self, keys, find_timeout=FIND_TIMEOUT, uia_after=UIA_AFTER,
                 wait_timeout=WAIT_TIMEOUT, max_attempts=MAX_ATTEMPTS):
        self.keys = list(keys)
        self.find_timeout = find_timeout
        self.uia_after = uia_after
        self.wait_timeout = wait_timeout
        self.max_attempts = max_attempts
        self.index = 0
        self.state = u'select'
        self.results = []
        self._reset_item()

    def _reset_item(self):
        self.t_find = None
        self.t_wait = None
        self.attempts = 0
        self.uia_tried = False
        self.route = None

    def current(self):
        if self.index < len(self.keys):
            return self.keys[self.index]
        return None

    def _record(self, status, detail):
        self.results.append((self.current(), status, detail))
        self.index += 1
        self.state = u'select'
        self._reset_item()

    def _start_wait(self, route):
        self.state = u'wait'
        self.t_wait = None
        self.attempts += 1
        self.route = route

    def tick(self, now, exists, button=u'missing'):
        key = self.current()
        if key is None:
            self.state = u'done'
            return (u'finished', None)

        if self.state == u'select':
            if not exists:
                self._record(u'gone', u'no longer in the model')
                return (u'none', None)
            self.state = u'find'
            self.t_find = now
            return (u'select', key)

        if self.state == u'find':
            if not exists:
                self._record(u'ok', self.route or u'exploded')
                return (u'none', None)
            if button == u'enabled':
                self._start_wait(u'ribbon')
                return (u'invoke', key)
            elapsed = now - self.t_find
            if button == u'missing' and not self.uia_tried and elapsed >= self.uia_after:
                self.uia_tried = True
                self._start_wait(u'uia')
                return (u'invoke_uia', key)
            if elapsed >= self.find_timeout:
                if button == u'disabled':
                    detail = u'Revit greyed out Explode for it (over 10,000 elements, or not explodable)'
                else:
                    detail = u'the Explode button could not be found on the ribbon'
                self._record(u'failed', detail)
            return (u'none', None)

        if self.state == u'wait':
            if not exists:
                self._record(u'ok', self.route)
                return (u'none', None)
            if self.t_wait is None:
                # first idle after the command - explode runs synchronously,
                # so the clock starts once Revit is idle again
                self.t_wait = now
                return (u'none', None)
            if now - self.t_wait >= self.wait_timeout:
                if self.attempts < self.max_attempts:
                    self.state = u'find'
                    self.t_find = now
                    return (u'select', key)
                self._record(u'failed', u'Revit did not explode it (refused or cancelled)')
            return (u'none', None)

        return (u'none', None)

    def counts(self):
        ok = len([r for r in self.results if r[1] == u'ok'])
        failed = len([r for r in self.results if r[1] == u'failed'])
        gone = len([r for r in self.results if r[1] == u'gone'])
        return ok, failed, gone


def report_lines(results, names, mode, extra=None):
    """Plain lines for the results window - only failures need a look."""
    ok = len([r for r in results if r[1] == u'ok'])
    lines = [u'{0} of {1} {2} exploded.'.format(
        ok, len(results), u'partially' if mode == u'partial' else u'fully')]
    for key, status, detail in results:
        if status == u'failed':
            lines.append(u'  {0} (id {1}): {2}'.format(names.get(key, u'Import'), key, detail))
    for line in (extra or []):
        lines.append(line)
    return lines


def run_timeout(count):
    """Wall-clock ceiling for a whole run, so a stuck run always lets go."""
    return 30.0 + count * (FIND_TIMEOUT + WAIT_TIMEOUT * MAX_ATTEMPTS + 5.0)
