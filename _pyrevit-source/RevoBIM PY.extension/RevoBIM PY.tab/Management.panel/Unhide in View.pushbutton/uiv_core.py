# -*- coding: utf-8 -*-
"""Unhide in View - core rules.

No .NET and no Revit in here: every decision the tool makes (what a view is
called, which views are listed, how the scan is sliced, what Unhide will do,
what the buttons say, settings, palettes) is a plain function or class that
runs under CPython against bench_logic.py. Keep it that way.
"""
import os
import re
import codecs

__version__ = '1.1.0'

TOOL_NAME = u'Unhide in View'
SETTINGS_FILE = 'unhide_in_view.txt'
DEBUG_FILE = 'unhide_in_view_debug.txt'
ERROR_FILE = 'unhide_in_view_last_error.txt'
OPEN_NOTE_FILE = 'unhide_in_view_open.txt'
APPDOMAIN_KEY = 'RevoBIM.UnhideInView.window'

SETTINGS_VERSION = 1

DEFAULTS = {
    'settings_version': str(SETTINGS_VERSION),
    'theme': 'follow',              # follow | dark | light
    'debug': '1',
    'only_hidden': '0',             # "Show views with hidden elements"
    'change_templates': '0',        # unhide a category on the view template too
    'width': '1320',
    'height': '800',
    'split': '0.56',                # left column share of the body
    'cat_split': '0.34',            # category list share of the left column
    'scan_budget_ms': '120',        # longest Revit is held per scan slice
}

# version reached -> {key: (old default, new default)}: a default changed in
# code reaches people who already have a settings file only through here.
# Bump SETTINGS_VERSION with every entry.
MIGRATIONS = {}

THEME_CYCLE = ['follow', 'dark', 'light']
THEME_LABEL = {'follow': u'Auto', 'dark': u'Dark', 'light': u'Light'}


# =====================================================================
# Text helpers - IronPython 2.7 and 3 alike
# =====================================================================

try:
    _TEXT = unicode           # noqa: F821  (IronPython 2.7)
except NameError:             # CPython 3 / IronPython 3
    _TEXT = str


def to_text(value):
    if value is None:
        return u''
    if isinstance(value, _TEXT):
        return value
    try:
        return _TEXT(value)
    except Exception:
        try:
            return str(value).decode('utf-8', 'replace')
        except Exception:
            return u''


def keyword_match(text, query):
    """Every whitespace separated term in query appears in text, any case."""
    q = to_text(query).strip().lower()
    if not q:
        return True
    t = to_text(text).lower()
    for term in q.split():
        if term not in t:
            return False
    return True


_DIGITS = re.compile(r'\d+')


def natural_key(text):
    """A string that sorts P-9 before P-10. DataView compares strings, so the
    numbers are padded rather than compared as numbers."""
    return _DIGITS.sub(lambda m: m.group(0).zfill(12), to_text(text).lower())


def plural(n, one, many=None):
    if n == 1:
        return u'{0} {1}'.format(n, one)
    return u'{0} {1}'.format(n, many if many is not None else one + u's')


# =====================================================================
# Views
# =====================================================================

# ViewType names (read with str(), never by importing the enum member) of
# views that cannot hide anything or are not views a person works in.
SKIP_VIEW_TYPES = set([
    'Schedule', 'PanelSchedule', 'ColumnSchedule', 'ProjectBrowser',
    'SystemBrowser', 'Internal', 'Undefined', 'Report', 'CostReport',
    'LoadsReport', 'PresureLossReport', 'PressureLossReport',
    'SystemsAnalysisReport',
])

VIEW_TYPE_LABELS = {
    'FloorPlan': u'Floor Plan',
    'CeilingPlan': u'Ceiling Plan',
    'EngineeringPlan': u'Structural Plan',
    'AreaPlan': u'Area Plan',
    'ThreeD': u'3D',
    'Section': u'Section',
    'Elevation': u'Elevation',
    'Detail': u'Detail',
    'DraftingView': u'Drafting',
    'Legend': u'Legend',
    'DrawingSheet': u'Sheet',
    'Rendering': u'Rendering',
    'Walkthrough': u'Walkthrough',
}


def view_is_listed(view_type_name, is_template):
    if is_template:
        return False
    return to_text(view_type_name) not in SKIP_VIEW_TYPES


def view_type_label(view_type_name):
    name = to_text(view_type_name)
    if name in VIEW_TYPE_LABELS:
        return VIEW_TYPE_LABELS[name]
    # split CamelCase for anything a later release adds
    return re.sub(r'(?<=[a-z])(?=[A-Z])', u' ', name) or u'View'


def view_display_name(name, sheet_number=None):
    """Sheets read as their number and name, the way the browser shows them."""
    name = to_text(name)
    if sheet_number:
        return u'{0} - {1}'.format(to_text(sheet_number), name)
    return name


def count_text(count):
    """None while not yet scanned."""
    if count is None:
        return u'\u2026'
    return to_text(count)


def view_row_visible(name, type_label, count, query, only_hidden):
    """The views list filter: the keyword search over name and type, and the
    'Show views with hidden elements' toggle. Unscanned views are left out
    while the toggle is on - they are not known to have any yet."""
    if only_hidden and not count:
        return False
    return keyword_match(u'{0} {1}'.format(to_text(name), to_text(type_label)), query)


def row_matches_columns(values, filters):
    """Per column keyword boxes: values and filters are dicts keyed by column."""
    for key, query in filters.items():
        if not keyword_match(values.get(key, u''), query):
            return False
    return True


# =====================================================================
# The scan - time sliced so Revit is never held for long
# =====================================================================

class Scanner(object):
    """Finds the elements hidden in each view, a slice at a time.

    The Revit parts arrive as callables so the whole thing runs on the bench:
      segments_for(view_key) -> list of sequences of candidate elements
      is_hidden(item, view_key) -> bool
      id_of(item) -> what is stored for a hidden item (an ElementId in Revit)
      clock() -> seconds

    Progress inside a view is kept, so a slice can stop half way through a
    big model and the next slice carries on from the same element.
    """

    CHECK_EVERY = 256

    def __init__(self, view_keys, segments_for, is_hidden, id_of, clock):
        self.order = list(view_keys)
        self.total = len(self.order)
        self.segments_for = segments_for
        self.is_hidden = is_hidden
        self.id_of = id_of
        self.clock = clock
        self.results = {}
        self.partial = {}
        self.errors = 0
        self.checked = 0

    # ---- state ---------------------------------------------------------
    def done(self, view_key):
        return view_key in self.results

    def count(self, view_key):
        found = self.results.get(view_key)
        if found is None:
            return None
        return len(found)

    def finished(self):
        return not self.order

    def progress(self):
        return len(self.results), self.total

    # ---- ordering --------------------------------------------------------
    def bump(self, view_keys):
        """Scan these next, in the order given, ahead of everything else."""
        wanted = [k for k in view_keys if k in self.order]
        if not wanted:
            return
        rest = [k for k in self.order if k not in wanted]
        seen = []
        for k in wanted:
            if k not in seen:
                seen.append(k)
        self.order = seen + rest

    def forget(self, view_key):
        """Scan this view again from the start (after an unhide elsewhere)."""
        self.results.pop(view_key, None)
        self.partial.pop(view_key, None)
        if view_key not in self.order:
            self.order.insert(0, view_key)

    def remove_found(self, view_key, ids, same=None):
        """Drop ids proved unhidden from a finished view's list."""
        found = self.results.get(view_key)
        if found is None:
            return
        same = same or (lambda a, b: a == b)
        keep = []
        for f in found:
            hit = False
            for i in ids:
                if same(f, i):
                    hit = True
                    break
            if not hit:
                keep.append(f)
        self.results[view_key] = keep

    # ---- the work --------------------------------------------------------
    def step(self, budget_s):
        """Scan until the budget is spent. Returns the views finished in this
        slice. A view whose candidates cannot be read is finished as empty
        and counted in errors, rather than stalling the queue."""
        start = self.clock()
        finished = []
        while self.order:
            vk = self.order[0]
            st = self.partial.get(vk)
            if st is None:
                try:
                    segs = [s for s in (self.segments_for(vk) or []) if s is not None]
                except Exception:
                    self.errors += 1
                    segs = []
                st = [segs, 0, 0, []]
                self.partial[vk] = st
            segs = st[0]
            seg_i = st[1]
            idx = st[2]
            found = st[3]
            while seg_i < len(segs):
                seg = segs[seg_i]
                n = len(seg)
                while idx < n:
                    item = seg[idx]
                    idx += 1
                    self.checked += 1
                    try:
                        if self.is_hidden(item, vk):
                            found.append(self.id_of(item))
                    except Exception:
                        self.errors += 1
                    if idx % self.CHECK_EVERY == 0:
                        if self.clock() - start >= budget_s:
                            st[1] = seg_i
                            st[2] = idx
                            return finished
                seg_i += 1
                idx = 0
            self.results[vk] = found
            self.partial.pop(vk, None)
            self.order.pop(0)
            finished.append(vk)
            if self.clock() - start >= budget_s:
                return finished
        return finished


# =====================================================================
# Staging - nothing is written until Unhide
# =====================================================================

class Staging(object):
    """Ticked elements, keyed (view, element) so a tick survives the focus
    moving to another view and back; ticked categories, keyed by category
    and applied to whichever views are the target when Unhide is pressed."""

    def __init__(self):
        self.elements = {}
        self.categories = set()

    def set_element(self, view_key, elem_key, on):
        bucket = self.elements.setdefault(view_key, set())
        if on:
            bucket.add(elem_key)
        else:
            bucket.discard(elem_key)
        if not bucket:
            self.elements.pop(view_key, None)

    def element_ticked(self, view_key, elem_key):
        return elem_key in self.elements.get(view_key, ())

    def set_category(self, cat_key, on):
        if on:
            self.categories.add(cat_key)
        else:
            self.categories.discard(cat_key)

    def element_total(self):
        n = 0
        for v in self.elements.values():
            n += len(v)
        return n

    def element_views(self):
        return len([k for k, v in self.elements.items() if v])

    def prune_view(self, view_key, still_hidden):
        """Keep only ticks on elements still hidden in that view."""
        bucket = self.elements.get(view_key)
        if not bucket:
            return
        keep = set(k for k in bucket if k in still_hidden)
        if keep:
            self.elements[view_key] = keep
        else:
            self.elements.pop(view_key, None)

    def prune_categories(self, offered):
        self.categories = set(k for k in self.categories if k in offered)

    def clear(self):
        self.elements = {}
        self.categories = set()

    def anything(self):
        return bool(self.element_total() or self.categories)


def target_views(ticked_keys, focus_key):
    """Categories act on the ticked views; with none ticked, on the view
    being looked at."""
    ticked = [k for k in ticked_keys if k is not None]
    if ticked:
        return ticked
    if focus_key is not None:
        return [focus_key]
    return []


# =====================================================================
# Categories hidden in the target views
# =====================================================================

def summarise_categories(targets, state_by_view, names):
    """Rows for the category list.

    state_by_view: view_key -> {cat_key: (hidden, controlled_by)} where
    controlled_by is a template name when a view template decides it.
    Returns a list of dicts, sorted by name, of categories hidden in at
    least one target.
    """
    rows = {}
    for vk in targets:
        state = state_by_view.get(vk) or {}
        for ck, pair in state.items():
            hidden, controlled = pair
            if not hidden:
                continue
            r = rows.get(ck)
            if r is None:
                r = {'key': ck, 'name': to_text(names.get(ck, ck)),
                     'hidden_in': 0, 'targets': len(targets),
                     'templates': set()}
                rows[ck] = r
            r['hidden_in'] += 1
            if controlled:
                r['templates'].add(to_text(controlled))
    out = list(rows.values())
    for r in out:
        r['hidden_text'] = u'{0} / {1}'.format(r['hidden_in'], r['targets'])
        tl = sorted(r['templates'])
        if not tl:
            r['note'] = u''
        elif len(tl) == 1:
            r['note'] = u'Template: ' + tl[0]
        else:
            r['note'] = u'Templates: ' + u', '.join(tl)
        r['templates'] = tl
    out.sort(key=lambda r: natural_key(r['name']))
    return out


# =====================================================================
# The plan - exactly what Unhide will do
# =====================================================================

def build_plan(staging, hidden_by_view, targets, cat_state, change_templates,
               template_of):
    """Turn what is ticked into actions.

    hidden_by_view: view_key -> set of element keys currently hidden there
    cat_state: view_key -> {cat_key: (hidden, controlled_by_name)}
    template_of: view_key -> template key (or None)

    Returns dict:
      elements:   [(view_key, [elem_key, ...])]
      categories: [(owner_key, is_template, [cat_key, ...])]
      skipped:    [(kind, view_key, key, reason)]
    A category controlled by a template is unhidden on the template only
    when change_templates is set, once per template however many target
    views share it; otherwise it is skipped and said so.
    """
    plan = {'elements': [], 'categories': [], 'skipped': []}

    for vk in sorted(staging.elements.keys(), key=lambda k: to_text(k)):
        ticked = staging.elements.get(vk) or set()
        hidden = hidden_by_view.get(vk)
        go = []
        for ek in sorted(ticked, key=lambda k: to_text(k)):
            if hidden is not None and ek not in hidden:
                plan['skipped'].append(('element', vk, ek, u'no longer hidden'))
                continue
            go.append(ek)
        if go:
            plan['elements'].append((vk, go))

    per_owner = {}
    owner_order = []
    for vk in targets:
        state = cat_state.get(vk) or {}
        for ck in sorted(staging.categories, key=lambda k: to_text(k)):
            pair = state.get(ck)
            if pair is None or not pair[0]:
                continue
            controlled = pair[1]
            if controlled:
                if not change_templates:
                    plan['skipped'].append(
                        ('category', vk, ck,
                         u'controlled by view template ' + to_text(controlled)))
                    continue
                owner = ('T', template_of(vk))
            else:
                owner = ('V', vk)
            if owner not in per_owner:
                per_owner[owner] = []
                owner_order.append(owner)
            if ck not in per_owner[owner]:
                per_owner[owner].append(ck)
    for owner in owner_order:
        plan['categories'].append((owner[1], owner[0] == 'T', per_owner[owner]))
    return plan


def plan_counts(plan):
    n_el = sum(len(ids) for _, ids in plan['elements'])
    n_el_views = len(plan['elements'])
    n_cat = sum(len(c) for _, _, c in plan['categories'])
    n_owners = len(plan['categories'])
    return n_el, n_el_views, n_cat, n_owners


def unhide_label(n_elements, n_categories):
    """The green button. Says what it will do; plain 'Unhide' when nothing."""
    parts = []
    if n_elements:
        parts.append(plural(n_elements, u'element'))
    if n_categories:
        parts.append(plural(n_categories, u'category', u'categories'))
    if not parts:
        return u'Unhide'
    return u'Unhide ' + u' + '.join(parts)


def views_button_label(n_views, n_hidden):
    if not n_views:
        return u'Unhide all in ticked views'
    return u'Unhide all in {0} ({1})'.format(
        plural(n_views, u'view'), n_hidden)


def summarise_result(result):
    """result: {'elements_ok', 'element_views', 'categories_ok',
    'category_owners', 'refused': [...], 'skipped': [...]}"""
    parts = []
    if result.get('elements_ok'):
        parts.append(u'Unhid {0} in {1}'.format(
            plural(result['elements_ok'], u'element'),
            plural(result.get('element_views', 0), u'view')))
    if result.get('categories_ok'):
        parts.append(u'{0} unhidden in {1}'.format(
            plural(result['categories_ok'], u'category', u'categories'),
            plural(result.get('category_owners', 0), u'view')))
    if not parts:
        parts.append(u'Nothing was unhidden')
    text = u'. '.join(parts) + u'.'
    refused = len(result.get('refused') or [])
    skipped = len(result.get('skipped') or [])
    if refused:
        text += u' {0} refused - see the red rows.'.format(refused)
    if skipped:
        text += u' {0} skipped - see the debug log.'.format(skipped)
    return text


# =====================================================================
# Theme
# =====================================================================

def next_theme(mode):
    mode = normalise_theme(mode)
    i = THEME_CYCLE.index(mode)
    return THEME_CYCLE[(i + 1) % len(THEME_CYCLE)]


def normalise_theme(mode):
    m = to_text(mode).strip().lower()
    if m == 'auto':
        return 'follow'
    if m in THEME_CYCLE:
        return m
    return 'follow'


def resolve_theme(mode, canvas):
    """What to paint: the stored mode, or the canvas when following it.
    A canvas that could not be read falls back to dark."""
    mode = normalise_theme(mode)
    if mode in ('dark', 'light'):
        return mode
    if canvas in ('dark', 'light'):
        return canvas
    return 'dark'


def theme_from_enum_text(text):
    """UITheme read by name - never import the enum member."""
    t = to_text(text).lower()
    if 'dark' in t:
        return 'dark'
    if 'light' in t:
        return 'light'
    return None


def theme_from_background(r, g, b):
    """Canvas background colour -> dark/light by perceived luminance."""
    try:
        lum = 0.2126 * float(r) + 0.7152 * float(g) + 0.0722 * float(b)
    except Exception:
        return None
    return 'dark' if lum < 128.0 else 'light'


PALETTES = {
    'dark': {
        'Bg': '#232326',
        'Card': '#2B2B2E',
        'Field': '#1C1C1F',
        'Bar': '#1C1C1F',
        'Edge': '#3E3E42',
        'WinEdge': '#4A4A50',
        'Text': '#E4E4E4',
        'Muted': '#9A9A9E',
        'Blue': '#4FA3E3',
        'Orange': '#E8912D',
        'Green': '#3FA75A',
        'GreenHover': '#4EC06D',
        'Red': '#D9534F',
        'Sel': '#2B5473',
        'RowAlt': '#202023',
        'Hover': '#33363B',
        'Staged': '#4A3519',
        'BadWash': '#4A2523',
        'OnAccent': '#FFFFFF',
        'Tick': '#10243A',
        'Disabled': '#5A5A60',
    },
    'light': {
        'Bg': '#F3F3F5',
        'Card': '#FFFFFF',
        'Field': '#FFFFFF',
        'Bar': '#E6E7EA',
        'Edge': '#C9CBD1',
        'WinEdge': '#AEB1B8',
        'Text': '#1E1F22',
        'Muted': '#5F6168',
        'Blue': '#1B72BE',
        'Orange': '#B96A12',
        'Green': '#2E8546',
        'GreenHover': '#37A055',
        'Red': '#C0392B',
        'Sel': '#CFE3F5',
        'RowAlt': '#F7F8FA',
        'Hover': '#E9EEF4',
        'Staged': '#FBE6CC',
        'BadWash': '#F7D9D6',
        'OnAccent': '#FFFFFF',
        'Tick': '#FFFFFF',
        'Disabled': '#B5B7BD',
    },
}


def hex_to_rgb(hex_text):
    h = to_text(hex_text).strip().lstrip('#')
    if len(h) != 6:
        raise ValueError('bad colour ' + to_text(hex_text))
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# =====================================================================
# Shrink to taskbar - the drawer arithmetic (WPF units, never pixels)
# =====================================================================

DRAWER_SECONDS = 0.28        # length of the slide
DRAWER_TICK_MS = 15          # one frame of the slide
DRAWER_MARGIN = 8.0          # gap between the parked bar and the taskbar
DRAWER_MOVED = 2.0           # a bar carried further than this has been moved

SHRINK_TIP = u'Shrink to the bottom of the screen (Ctrl+Shift+H)'
EXPAND_TIP = u'Open the window again (Ctrl+Shift+H, Enter or double-click the bar)'


def ease_out(p):
    """Cubic ease-out, 0..1 -> 0..1: fast away, gentle landing."""
    try:
        p = float(p)
    except Exception:
        return 1.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    return 1.0 - (1.0 - p) ** 3


def lerp(a, b, t):
    return a + (b - a) * t


def bar_height(header_height, frame_offset):
    """The parked window is its header plus the frame either side of it."""
    return max(1.0, float(header_height) + 2.0 * max(0.0, float(frame_offset)))


def parked_top(area, bar_h, margin=DRAWER_MARGIN):
    """Top of the parked bar: clear of the taskbar at the bottom of the
    working area of the screen the window is on. area = (left, top, width,
    height); a monitor above the primary one has a negative top."""
    left, top, width, height = area
    return top + height - margin - bar_h


def bar_moved(parked, now, slack=DRAWER_MOVED):
    """parked / now = (left, top) of the bar when it landed and now."""
    return abs(now[0] - parked[0]) > slack or abs(now[1] - parked[1]) > slack


def clamp(v, low, high):
    if high < low:
        return low
    return max(low, min(high, v))


def expand_bounds(saved, parked, now, bar_h, area):
    """Where the window opens to: (left, top, width, height).

    saved = (left, top, width, height) when it was shrunk. If the bar is
    where it landed, the window goes back exactly where it was. If the bar
    has been carried somewhere else, the window opens upward from where it
    now sits - its bottom edge at the bar's bottom edge - kept on the screen
    the bar is now on (area of that screen)."""
    s_left, s_top, s_w, s_h = saved
    if not bar_moved(parked, now):
        return s_left, s_top, s_w, s_h
    a_left, a_top, a_w, a_h = area
    h = min(s_h, a_h)
    w = min(s_w, a_w)
    top = now[1] + bar_h - h
    top = clamp(top, a_top, a_top + a_h - h)
    left = clamp(now[0], a_left, a_left + a_w - w)
    return left, top, w, h


# =====================================================================
# Easter egg fallback - three slow clicks on the logo
# =====================================================================

class SlowClicks(object):
    """Three clicks, each 250ms to 2s after the last. Timestamps are
    deduplicated because WPF reports one click to more than one handler."""

    def __init__(self, need=3, floor=0.25, ceiling=2.0):
        self.need = need
        self.floor = floor
        self.ceiling = ceiling
        self.stamps = []

    def add(self, t):
        if self.stamps and t == self.stamps[-1]:
            return False
        if self.stamps:
            gap = t - self.stamps[-1]
            if gap < self.floor or gap > self.ceiling:
                self.stamps = []
        self.stamps.append(t)
        if len(self.stamps) >= self.need:
            self.stamps = []
            return True
        return False


# =====================================================================
# Settings - key=value text, split on the first '=' only
# =====================================================================

def settings_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'RevoBIM')


def settings_path(name=SETTINGS_FILE):
    return os.path.join(settings_dir(), name)


def parse_settings(text):
    out = dict(DEFAULTS)
    for line in to_text(text).splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        k = k.strip()
        if k in DEFAULTS:
            out[k] = v.strip()
    return migrate(out)


def migrate(values):
    try:
        have = int(values.get('settings_version') or 0)
    except Exception:
        have = 0
    for ver in sorted(MIGRATIONS.keys()):
        if have >= ver:
            continue
        for key, change in MIGRATIONS[ver].items():
            old, new = change
            if values.get(key) == old:
                values[key] = new
    values['settings_version'] = str(SETTINGS_VERSION)
    values['theme'] = normalise_theme(values.get('theme'))
    return values


def format_settings(values):
    lines = [u'# RevoBIM Unhide in View settings - key=value']
    for k in sorted(DEFAULTS.keys()):
        lines.append(u'{0}={1}'.format(k, to_text(values.get(k, DEFAULTS[k]))))
    return u'\n'.join(lines) + u'\n'


def load_settings(path=None):
    path = path or settings_path()
    try:
        if os.path.exists(path):
            f = codecs.open(path, 'r', 'utf-8')
            try:
                text = f.read()
            finally:
                f.close()
            return parse_settings(text)
    except Exception:
        pass
    return migrate(dict(DEFAULTS))


def save_settings(values, path=None):
    path = path or settings_path()
    try:
        d = os.path.dirname(path)
        if not os.path.isdir(d):
            os.makedirs(d)
        text = format_settings(values)
        f = codecs.open(path, 'w', 'utf-8')
        try:
            f.write(text)
        finally:
            f.close()
        return True
    except Exception:
        return False


def as_bool(value):
    return to_text(value).strip().lower() in ('1', 'true', 'yes', 'on')


def as_float(value, default, low=None, high=None):
    try:
        v = float(value)
    except Exception:
        v = default
    if low is not None and v < low:
        v = low
    if high is not None and v > high:
        v = high
    return v


# =====================================================================
# Debug log
# =====================================================================

class DebugLog(object):
    """Lines kept in memory for Copy debug, mirrored to the debug file."""

    LIMIT = 6000

    def __init__(self, enabled=True, path=None):
        self.enabled = enabled
        self.lines = []
        self.path = path or settings_path(DEBUG_FILE)

    def add(self, text):
        if not self.enabled:
            return
        self.lines.append(to_text(text))
        if len(self.lines) > self.LIMIT:
            self.lines = self.lines[-self.LIMIT:]

    def text(self, header=u''):
        body = u'\n'.join(self.lines)
        if header:
            return to_text(header) + u'\n' + body
        return body

    def flush(self, header=u''):
        if not self.enabled:
            return False
        try:
            d = os.path.dirname(self.path)
            if not os.path.isdir(d):
                os.makedirs(d)
            f = codecs.open(self.path, 'w', 'utf-8')
            try:
                f.write(self.text(header))
            finally:
                f.close()
            return True
        except Exception:
            return False
