# -*- coding: utf-8 -*-
"""Family Viewer - version, settings, paths and small helpers.

Nothing in here touches the Revit document; it is safe to import on the bench.
"""

import fv_clr  # noqa: F401  - must be first, references the assemblies

import os
import re
import time
import traceback

# Which engine pyRevit picks varies by release, so the string types are worked
# out once here rather than guessed at each use.  Asking for `unicode` by name
# would be a global that does not exist on IronPython 3 even inside a
# try/except, and the bench check rightly refuses it; type(u'') answers on both.
_UNICODE = type(u'')
TEXT_TYPES = (str,) if _UNICODE is str else (str, _UNICODE)

__version__ = "2.0.2"

TOOL_NAME = "Family Viewer"
RIBBON_TITLE = "Family Viewer"

# The dockable pane's id.  Fixed for the life of the tool: Revit remembers a
# pane's position against this guid, so changing it would throw away everybody's
# layout.  startup.py registers the pane under it and script.py asks for it.
DOCK_GUID = "7C4B1E62-0F3A-4D18-9E77-51A0C2D4B913"

SETTINGS_FILE = "family_viewer.txt"
LOG_FILE = "family_viewer.log"
ERROR_FILE = "family_viewer_last_error.txt"

# Bumped when the meaning of a key changes.  MIGRATIONS lists the keys each
# version resets to their default, so a saved value read under the old meaning
# is thrown away rather than silently misread.
SETTINGS_VERSION = 2
MIGRATIONS = {
    # 2.0.0: the theme follows Revit's canvas by default now, and the phase
    # mode default moved to "existing" back in 1.5.0 WITHOUT a migration - so
    # anyone whose file was written before then still had "created" saved, the
    # setting that emptied every list.  A changed default does nothing for a
    # file that already holds the old value; this is what makes it land.
    2: ['theme', 'phase_mode'],
}

DEFAULTS = {
    'settings_version': str(SETTINGS_VERSION),
    'theme': 'follow',            # follow (Revit's canvas) | dark | light

    # scale
    'ui_scale': '100',            # per cent, 80 - 150
    'preview_size': '48',         # px, the family image edge
    'show_previews': '1',
    'preview_on': 'family',       # family | type | both

    # what goes in the list
    'categories': '',             # pipe separated, blank = every category found
    'include_system': '0',        # walls, pipes, ducts and friends
    'include_annotation': '0',
    'ignore_nested': '1',         # instances nested inside another family
    'families_open': '1',
    # the band behind a family row, and how big its name is.  Blank shade means
    # the palette's own FamilyRowBg, so a theme switch still works.
    'family_row_shade': '',
    'family_row_size': '14',

    # scope
    'default_scope': 'project',   # project | view | all
    # A phase is NOT remembered between sessions.  It belongs to a reading,
    # not to a preference, and phases differ from job to job - a name saved on
    # one model matching a phase on another is how the whole list came back
    # empty with no filter visibly set.  Kept in DEFAULTS so the settings file
    # round-trips, but the window always opens on every phase.
    'default_phase': '',          # blank = every phase
    # "what stands in the phase", not "what was created in it".  Created drops
    # everything not made in that exact phase, which on a real model is almost
    # everything.
    'phase_mode': 'existing',     # created | existing

    # columns
    'columns': '',                # pipe separated parameter names

    # behaviour
    'watch_model': '0',
    'settle_ms': '1200',
    'zoom_after_select': '0',
    'max_instances': '20000',     # the cap on the third level
    'max_rows': '4000',
    'show_results': 'auto',       # auto | always | never

    # window
    'open_in': 'pane',           # pane | window
    'dock_side': 'float',         # float | left | right
    'dock_width': '420',
    'dock_top_inset': '0',
    'follow_revit': '1',
    'snap_on_drag': '1',
}

BOOL_KEYS = [
    'show_previews', 'include_system', 'include_annotation',
    'ignore_nested', 'families_open', 'watch_model', 'zoom_after_select',
    'follow_revit', 'snap_on_drag',
]

INT_KEYS = ['ui_scale', 'preview_size', 'settle_ms', 'max_rows', 'dock_width',
            'dock_top_inset', 'settings_version']

PREVIEW_SIZES = [24, 32, 48, 64, 96, 128]
UI_SCALES = [80, 90, 100, 110, 125, 150]


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

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


def log_path():
    return os.path.join(appdata_dir(), LOG_FILE)


def error_path():
    return os.path.join(appdata_dir(), ERROR_FILE)


def debug_path():
    return os.path.join(appdata_dir(), 'family_viewer_debug.txt')


def log_tail(lines=120):
    """The end of the log, which is the part that describes this session."""
    try:
        handle = open(log_path())
        try:
            found = handle.readlines()
        finally:
            handle.close()
    except Exception:
        return ['(no log file yet)']
    return [one.rstrip('\n') for one in found[-lines:]]


def write_debug(lines):
    """Write a report to a file next to the settings, and return the path."""
    path = debug_path()
    handle = open(path, 'w')
    try:
        handle.write('\n'.join(lines))
    finally:
        handle.close()
    return path


def log(message):
    """Never allowed to raise - logging must not be able to take a tool down."""
    try:
        handle = open(log_path(), 'a')
        try:
            handle.write(message.rstrip() + '\n')
        finally:
            handle.close()
    except Exception:
        pass


def write_error(stage, exc_text):
    try:
        handle = open(error_path(), 'w')
        try:
            handle.write('stage: ' + stage + '\n\n' + exc_text)
        finally:
            handle.close()
    except Exception:
        pass


def format_exc():
    try:
        return traceback.format_exc()
    except Exception:
        return '(no traceback available)'


# ---------------------------------------------------------------------------
# settings - plain key=value text, not JSON.  No dependency on a module whose
# availability varies with the IronPython engine, and it stays hand editable.
# ---------------------------------------------------------------------------

def _parse(text):
    found = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        # split on the FIRST '=' only: some values carry '=' signs of their own
        key, value = line.split('=', 1)
        found[key.strip()] = value.strip()
    return found


def load_settings():
    """A missing or damaged file falls back to the defaults key by key, and
    keys from an older version are ignored rather than breaking the load."""
    values = dict(DEFAULTS)
    text = ''
    try:
        path = settings_path()
        if os.path.isfile(path):
            handle = open(path, 'r')
            try:
                text = handle.read()
            finally:
                handle.close()
    except Exception:
        text = ''

    found = {}
    try:
        found = _parse(text)
    except Exception:
        found = {}

    saved_version = 0
    try:
        saved_version = int(found.get('settings_version', '0'))
    except Exception:
        saved_version = 0

    reset = set()
    for version in sorted(MIGRATIONS.keys()):
        if saved_version < version:
            for key in MIGRATIONS[version]:
                reset.add(key)

    for key in DEFAULTS:
        if key in reset:
            continue
        if key in found:
            values[key] = found[key]

    values['settings_version'] = str(SETTINGS_VERSION)
    return values


def save_settings(values):
    lines = []
    ordered = list(DEFAULTS.keys())
    for key in ordered:
        lines.append(key + '=' + str(values.get(key, DEFAULTS[key])))
    for key in sorted(values.keys()):
        if key not in DEFAULTS:
            lines.append(key + '=' + str(values[key]))
    try:
        handle = open(settings_path(), 'w')
        try:
            handle.write('\n'.join(lines) + '\n')
        finally:
            handle.close()
        return True
    except Exception:
        log('could not write settings: ' + format_exc())
        return False


def as_bool(values, key):
    raw = str(values.get(key, DEFAULTS.get(key, '0'))).strip().lower()
    return raw in ('1', 'true', 'yes', 'on')


def as_int(values, key, low=None, high=None):
    default = DEFAULTS.get(key, '0')
    try:
        number = int(str(values.get(key, default)).strip())
    except Exception:
        try:
            number = int(default)
        except Exception:
            number = 0
    if low is not None and number < low:
        number = low
    if high is not None and number > high:
        number = high
    return number


def as_list(values, key):
    raw = str(values.get(key, '') or '')
    return [part.strip() for part in raw.split('|') if part.strip()]


def set_list(values, key, items):
    values[key] = '|'.join([str(item) for item in items if str(item).strip()])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026.  Prefer .Value (Int64)
    and fall back, never touching .IntegerValue directly anywhere else."""
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return element_id.IntegerValue
    except Exception:
        return 0


_NATURAL = re.compile(r'(\d+)')


def natural_key(text):
    """Sort '10' after '9', and case insensitively."""
    if text is None:
        text = ''
    parts = _NATURAL.split(str(text))
    key = []
    for index, part in enumerate(parts):
        if index % 2:
            try:
                key.append((1, int(part), ''))
            except Exception:
                key.append((0, 0, part.lower()))
        elif part:
            key.append((0, 0, part.lower()))
    return key


def matches_search(text, needle):
    """Every word typed has to appear somewhere in the text."""
    if not needle:
        return True
    haystack = (text or '').lower()
    for word in str(needle).lower().split():
        if word not in haystack:
            return False
    return True


VARIES = '(varies)'
BLANK = ''


def agree(values):
    """One value where every entry agrees, '(varies)' where they do not, and
    blank where there is nothing to report.  Used for a family row summarising
    its types, and for a type row summarising its instances."""
    seen = []
    for value in values:
        if value is None:
            continue
        text = str(value)
        if text not in seen:
            seen.append(text)
        if len(seen) > 1:
            return VARIES
    if not seen:
        return BLANK
    return seen[0]


# ---------------------------------------------------------------------------
# progress for a long write
# ---------------------------------------------------------------------------

# Where each stage of Apply sits on the bar.  Writing gets the wide middle,
# because that is the part that scales with the number of changes.
APPLY_BANDS = {
    'borrow': (0.00, 0.06),
    'index': (0.06, 0.10),
    'write': (0.10, 0.95),
    'commit': (0.95, 1.00),
}


class ProgressMeter(object):
    """Turns "done 1240 of 3000" into a percentage and decides when it is
    worth telling the window.

    Every report costs a repaint, and a repaint in the middle of a write means
    pumping the dispatcher, so it reports when the percentage has moved by at
    least `min_step` AND `min_interval` seconds have passed - or the stage has
    changed, or it has reached the end, which always get through.  Nothing in
    here touches WPF, so it runs on the bench with a fake clock.
    """

    def __init__(self, report, total=0, clock=None, min_step=1,
                 min_interval=0.12, bands=None):
        self.report = report
        self.total = max(0, int(total or 0))
        self.clock = clock
        if self.clock is None:
            self.clock = time.time
        self.min_step = min_step
        self.min_interval = min_interval
        self.bands = bands or APPLY_BANDS
        self.last_percent = -1
        self.last_time = None
        self.last_stage = None
        self.reports = 0

    def percent_of(self, stage, done):
        low, high = self.bands.get(stage, (0.0, 1.0))
        if self.total <= 0 or stage != 'write':
            fraction = low if done <= 0 else high
        else:
            share = float(min(max(done, 0), self.total)) / self.total
            fraction = low + (high - low) * share
        return int(round(fraction * 100))

    def text_of(self, stage, done):
        if stage == 'borrow':
            return 'Checking out the elements'
        if stage == 'index':
            return 'Finding the instances behind the types'
        if stage == 'commit':
            return 'Committing - Revit is regenerating the model'
        if stage == 'done':
            return 'Done'
        return ('Writing ' + '{:,}'.format(min(done, self.total)) + ' of ' +
                '{:,}'.format(self.total) + ' change' +
                ('' if self.total == 1 else 's'))

    def update(self, stage, done=0):
        """Returns True when it reported."""
        if stage == 'done':
            percent = 100
        else:
            percent = self.percent_of(stage, done)
        now = self.clock()
        forced = (stage != self.last_stage or percent >= 100 or
                  self.last_time is None)
        if not forced:
            if percent - self.last_percent < self.min_step:
                return False
            if now - self.last_time < self.min_interval:
                return False
        if percent < self.last_percent:
            percent = self.last_percent     # never runs backwards
        self.last_percent = percent
        self.last_time = now
        self.last_stage = stage
        self.reports += 1
        if self.report is not None:
            try:
                self.report(percent, self.text_of(stage, done))
            except Exception:
                # a broken bar must never stop the write behind it
                self.report = None
        return True
