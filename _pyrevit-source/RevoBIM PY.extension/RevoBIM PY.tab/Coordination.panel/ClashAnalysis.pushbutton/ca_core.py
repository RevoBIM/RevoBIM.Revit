# -*- coding: utf-8 -*-
"""Clash Analysis - pure logic.

Nothing in here touches .NET or the Revit API, so every rule that decides a
value (names, comments, pair finding, levels, settings, the drawer's
arithmetic) runs under plain CPython in bench_logic.py.
"""
import math
import re

MM_PER_FT = 304.8

# ======================================================================
# Text
# ======================================================================

try:
    _text_type = unicode  # noqa: F821  (IronPython 2.7)
except NameError:
    _text_type = str


def to_text(value):
    if value is None:
        return u''
    if isinstance(value, _text_type):
        return value
    try:
        return _text_type(value)
    except Exception:
        try:
            return str(value).decode('utf-8', 'replace')
        except Exception:
            return u''


def mm_to_ft(mm):
    return float(mm) / MM_PER_FT


def ft_to_mm(ft):
    return float(ft) * MM_PER_FT


# Characters Revit refuses in element and type names.
_FORBIDDEN = u'\\:{}[]|;<>?`~'


def sanitize_name(text):
    """A name Revit will accept: forbidden characters become '-', runs of
    whitespace collapse, ends trimmed."""
    out = []
    for ch in to_text(text):
        out.append(u'-' if ch in _FORBIDDEN else ch)
    joined = u' '.join(u''.join(out).split())
    return joined.strip()


def safe_filename(text):
    bad = u'\\/:*?"<>|'
    out = []
    for ch in to_text(text):
        out.append(u'_' if (ch in bad or ord(ch) < 32) else ch)
    name = u''.join(out).strip().strip(u'.')
    return name or u'unnamed'


def unique_name(name, existing):
    """name, or name (2), name (3)... whichever is not in existing."""
    taken = set(to_text(e).lower() for e in existing)
    if to_text(name).lower() not in taken:
        return name
    n = 2
    while True:
        candidate = u'{0} ({1})'.format(name, n)
        if candidate.lower() not in taken:
            return candidate
        n += 1


# ======================================================================
# Clash group names:
#   CLASH-<Year>_<Month>_<Day>_<Hour>-<Minute>_<Level>-<Clash name>
# One group per floor. <Level> is the level's short code (L02, GF, B1...).
# Groups placed before 1.3.0 have no _<Level> and still parse.
# ======================================================================

GROUP_PREFIX = u'CLASH-'
_GROUP_RE = re.compile(
    u'^CLASH-(\\d{4})_(\\d{2})_(\\d{2})_(\\d{2})-(\\d{2})(?:_([^-\\s]+))?-(.+)$')


def level_token(code):
    """A level code safe inside a group name: letters, digits and '.' only
    (no '-' or spaces, which would end it)."""
    out = [ch for ch in to_text(code) if ch.isalnum() or ch == u'.']
    return u''.join(out)


def clash_group_name(stamp, clash_name, level_code=u''):
    """stamp is (year, month, day, hour, minute)."""
    year, month, day, hour, minute = [int(x) for x in stamp[:5]]
    clean = sanitize_name(clash_name) or u'Clash'
    token = level_token(level_code)
    mid = u'_' + token if token else u''
    return u'CLASH-{0:04d}_{1:02d}_{2:02d}_{3:02d}-{4:02d}{5}-{6}'.format(
        year, month, day, hour, minute, mid, clean)


def parse_clash_group_name(name):
    """{'stamp': (y, m, d, h, mi), 'level': code or u'', 'clash': name,
    'sort': 'YYYYMMDDHHMM', 'display_date'} or None when the name is not in
    the clash group format."""
    match = _GROUP_RE.match(to_text(name))
    if not match:
        return None
    parts = [int(match.group(i)) for i in range(1, 6)]
    if not (1 <= parts[1] <= 12 and 1 <= parts[2] <= 31
            and 0 <= parts[3] <= 23 and 0 <= parts[4] <= 59):
        return None
    clash = match.group(7)
    # unique_name() may have added " (2)" to keep the type name free
    clash = re.sub(u' \\(\\d+\\)$', u'', clash)
    return {
        'stamp': tuple(parts),
        'level': to_text(match.group(6) or u''),
        'clash': clash,
        'sort': u'{0:04d}{1:02d}{2:02d}{3:02d}{4:02d}'.format(*parts),
        'display_date': u'{2:02d}/{1:02d}/{0:04d} {3:02d}:{4:02d}'.format(*parts),
    }


# ---- level codes -----------------------------------------------------

_ORDINALS = [(u'first', 1), (u'second', 2), (u'third', 3), (u'fourth', 4),
             (u'fifth', 5), (u'sixth', 6), (u'seventh', 7), (u'eighth', 8),
             (u'ninth', 9), (u'tenth', 10), (u'eleventh', 11), (u'twelfth', 12)]
_WORDS = [(u'lower ground', u'LG'), (u'upper ground', u'UG'), (u'ground', u'GF'),
          (u'mezzanine', u'MZ'), (u'podium', u'PD'), (u'roof', u'RF'),
          (u'parapet', u'PP'), (u'plant', u'PL'), (u'foundation', u'FDN')]


def level_abbreviation(name):
    """Short code for a level name, e.g.
    'L02 - First Floor' -> L02, 'Level 2' -> L02, 'Level -1' -> B01,
    'Ground Floor' -> GF, 'Basement 2' -> B2, '3rd Floor' -> L03,
    'Second Floor' -> L02, 'Roof' -> RF, otherwise the initials."""
    text = u' '.join(to_text(name).split())
    low = text.lower()
    # a leading code: L02, B1, 01, M2a ...
    m = re.match(u'^([A-Za-z]{0,3}\\d{1,3}[A-Za-z]?)(?=$|[\\s\\-_.:,])', text)
    if m:
        return m.group(1).upper()
    # a leading capitals code followed by a separator: "GF - Ground Floor"
    m = re.match(u'^([A-Z]{1,3})(?=\\s*[-_:,]|$)', text)
    if m:
        return m.group(1)
    m = re.search(u'\\blevel\\s*(-?)\\s*(\\d{1,3})\\b', low)
    if m:
        n = int(m.group(2))
        return (u'B{0:02d}' if m.group(1) else u'L{0:02d}').format(n)
    m = re.search(u'\\bbasement\\s*(\\d{0,2})\\b', low)
    if m:
        return u'B' + m.group(1)
    for word, code in _WORDS:
        if re.search(u'\\b' + word + u'\\b', low):
            return code
    m = re.search(u'\\b(\\d{1,3})(st|nd|rd|th)\\b', low)
    if m:
        return u'L{0:02d}'.format(int(m.group(1)))
    for word, n in _ORDINALS:
        if re.search(u'\\b' + word + u'\\b', low):
            return u'L{0:02d}'.format(n)
    bits = re.findall(u'[A-Za-z]+|\\d+', text)
    initials = u''.join(b if b.isdigit() else b[0] for b in bits).upper()
    return level_token(initials)[:6] or u'LVL'


def level_codes(names):
    """{level name: code}, every code different. Levels sharing a code
    fall back to their full name with everything but letters and digits
    taken out."""
    codes = dict((n, level_token(level_abbreviation(n))) for n in names)
    seen = {}
    for n in names:
        seen.setdefault(codes[n].lower(), []).append(n)
    for key, group in seen.items():
        if len(group) > 1:
            for n in group:
                codes[n] = level_token(n)[:16] or codes[n]
    taken = set()
    for n in sorted(names):
        code = codes[n]
        base, k = code, 2
        while code.lower() in taken:
            code = u'{0}.{1}'.format(base, k)
            k += 1
        taken.add(code.lower())
        codes[n] = code
    return codes


# ---- clash families already in place ---------------------------------

DUPLICATE_MM = 100.0


class PointIndex(object):
    """Points on a grid: near(p) is True when a stored point lies within
    tol of p. Used to skip clashes that already have a clash family."""

    def __init__(self, points=(), tol=1.0):
        self.tol = max(float(tol), 1e-9)
        self.cells = {}
        for p in points:
            self.add(p)

    def _cell(self, p):
        return tuple(int(math.floor(v / self.tol)) for v in p[:3])

    def add(self, p):
        self.cells.setdefault(self._cell(p), []).append(tuple(p[:3]))

    def near(self, p):
        cx, cy, cz = self._cell(p)
        t2 = self.tol * self.tol
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for q in self.cells.get((cx + dx, cy + dy, cz + dz), ()):
                        d2 = ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 +
                              (q[2] - p[2]) ** 2)
                        if d2 <= t2:
                            return True
        return False


def sql_like_escape(term):
    """Escape a term for a DataView RowFilter LIKE, so an apostrophe or a
    bracket in a family name cannot break the filter."""
    out = []
    for ch in to_text(term):
        if ch == u"'":
            out.append(u"''")
        elif ch in u'[]%*':
            out.append(u'[' + ch + u']')
        else:
            out.append(ch)
    return u''.join(out)


def row_filter(term, column=u'search'):
    term = to_text(term).strip()
    if not term:
        return u''
    return u"[{0}] LIKE '%{1}%'".format(column, sql_like_escape(term.lower()))


def egg_ready(stamps, floor_ms=250, ceiling_ms=2000):
    """Three slow clicks on the logo: each gap between floor and ceiling.
    stamps are event Timestamps in ms; repeats of one stamp are ignored
    (WPF can report the same click twice)."""
    uniq = []
    for s in stamps:
        if not uniq or s != uniq[-1]:
            uniq.append(s)
    if len(uniq) < 3:
        return False
    a, b, c = uniq[-3:]
    return (floor_ms <= b - a <= ceiling_ms) and (floor_ms <= c - b <= ceiling_ms)


def is_clash_group_name(name):
    return parse_clash_group_name(name) is not None


# ======================================================================
# Comments written to each placed clash family
# ======================================================================

COMMENT_FORMATS = [
    ('family_type', u'Family : Type'),
    ('family', u'Family'),
    ('category', u'Category'),
    ('category_family', u'Category - Family'),
]
VS = u'-vs-'


def describe(side, fmt):
    """side: dict with category / family / type."""
    cat = to_text(side.get('category')).strip()
    fam = to_text(side.get('family')).strip() or cat
    typ = to_text(side.get('type')).strip()
    if fmt == 'category':
        return cat or fam
    if fmt == 'family':
        return fam
    if fmt == 'category_family':
        if cat and cat != fam:
            return u'{0} - {1}'.format(cat, fam)
        return fam
    if typ and typ != fam:
        return u'{0} : {1}'.format(fam, typ)
    return fam


def comment_text(side_a, side_b, fmt='family_type'):
    return describe(side_a, fmt) + VS + describe(side_b, fmt)


def split_comment(comment):
    text = to_text(comment)
    if VS not in text:
        return (text, u'')
    left, right = text.split(VS, 1)
    return (left, right)


def comment_report(comments):
    """[(comment, count)] most frequent first, blanks reported as '(blank)'."""
    counts = {}
    for c in comments:
        key = to_text(c).strip() or u'(blank)'
        counts[key] = counts.get(key, 0) + 1
    rows = list(counts.items())
    rows.sort(key=lambda r: (-r[1], r[0].lower()))
    return rows


# ======================================================================
# Category / family keys and the picker tree
# ======================================================================

KEY_SEP = u'|'
WHOLE = u'*'


def cf_key(category, family):
    return to_text(category) + KEY_SEP + to_text(family)


def split_key(key):
    text = to_text(key)
    if KEY_SEP not in text:
        return (text, WHOLE)
    cat, fam = text.split(KEY_SEP, 1)
    return (cat, fam)


def key_matches(keys, category, family):
    """True when the (category, family) pair is chosen by keys."""
    if cf_key(category, family) in keys:
        return True
    return cf_key(category, WHOLE) in keys


IMPORT_EXTENSIONS = (u'.dwg', u'.dxf', u'.dgn', u'.sat', u'.skp', u'.ifc',
                     u'.3dm', u'.rvt', u'.nwc', u'.nwd', u'.pdf', u'.jpg', u'.png')


def is_model_category(name, builtin, has_parent, model_type):
    """Whether a category belongs in the Set A / Set B tree: Revit's own
    model categories only. Out: annotation / analytical types, user-made
    categories (every imported .dwg / .dxf brings its own), sub-categories
    (line styles such as <Room Separation> sit under Lines), anything
    named <like this>, and anything named like a file."""
    name = to_text(name).strip()
    if not name or not model_type or not builtin or has_parent:
        return False
    if name.startswith(u'<') or name.endswith(u'>'):
        return False
    low = name.lower()
    for ext in IMPORT_EXTENSIONS:
        if low.endswith(ext) or (ext + u' ') in low:
            return False
    return True


def models_list_height(rows=7, row_px=24.0, chrome_px=6.0):
    """Height of a Models list that shows rows models without scrolling."""
    return rows * row_px + chrome_px


def merge_catalogs(catalogs):
    """catalogs: list of {cat: {fam: count}} -> one summed catalog."""
    out = {}
    for cat_map in catalogs:
        for cat, fams in cat_map.items():
            slot = out.setdefault(cat, {})
            for fam, n in fams.items():
                slot[fam] = slot.get(fam, 0) + n
    return out


class CatalogTree(object):
    """Category > family tick list with collapse and search. Pure state:
    the window draws whatever rows() returns."""

    def __init__(self, catalog=None, ticked=None):
        self.catalog = {}
        self.ticked = set()
        self.collapsed = set()
        self.seen = set()
        self.set_catalog(catalog or {}, ticked or [])

    def set_catalog(self, catalog, ticked=None):
        self.catalog = dict((c, dict(f)) for c, f in catalog.items())
        keep = set(self.ticked if ticked is None else ticked)
        self.ticked = set()
        for key in keep:
            cat, fam = split_key(key)
            if fam == WHOLE:
                for f in self.catalog.get(cat, {}):
                    self.ticked.add(cf_key(cat, f))
                if cat not in self.catalog:
                    # keep a choice for a model not loaded right now
                    self.ticked.add(key)
            else:
                self.ticked.add(key)
        # categories arrive collapsed; ones the user has opened stay open
        fresh = set(self.catalog.keys()) - self.seen
        self.collapsed |= fresh
        self.seen |= fresh

    def families(self, cat):
        return sorted(self.catalog.get(cat, {}).keys(), key=lambda s: s.lower())

    def categories(self):
        return sorted(self.catalog.keys(), key=lambda s: s.lower())

    def cat_state(self, cat):
        fams = self.families(cat)
        if not fams:
            return cf_key(cat, WHOLE) in self.ticked
        n = sum(1 for f in fams if cf_key(cat, f) in self.ticked)
        if n == 0:
            return False
        if n == len(fams):
            return True
        return None

    def toggle_category(self, cat):
        state = self.cat_state(cat)
        fams = self.families(cat)
        if state is True:
            for f in fams:
                self.ticked.discard(cf_key(cat, f))
        else:
            for f in fams:
                self.ticked.add(cf_key(cat, f))

    def toggle_family(self, cat, fam):
        key = cf_key(cat, fam)
        if key in self.ticked:
            self.ticked.discard(key)
        else:
            self.ticked.add(key)

    def toggle_collapse(self, cat):
        if cat in self.collapsed:
            self.collapsed.discard(cat)
        else:
            self.collapsed.add(cat)

    def set_all_collapsed(self, collapsed):
        self.collapsed = set(self.catalog.keys()) if collapsed else set()

    def clear(self):
        self.ticked = set()

    def rows(self, search=u''):
        """[{'kind','cat','fam','label','count','state','open'}]"""
        term = to_text(search).strip().lower()
        out = []
        for cat in self.categories():
            fams = self.families(cat)
            cat_hit = (not term) or term in cat.lower()
            fam_hits = [f for f in fams if cat_hit or term in f.lower()]
            if term and not cat_hit and not fam_hits:
                continue
            total = sum(self.catalog[cat].values())
            is_open = (cat not in self.collapsed) or bool(term)
            out.append({'kind': 'cat', 'cat': cat, 'fam': WHOLE, 'label': cat,
                        'count': total, 'state': self.cat_state(cat),
                        'open': is_open})
            if not is_open:
                continue
            for fam in fam_hits:
                out.append({'kind': 'fam', 'cat': cat, 'fam': fam,
                            'label': fam, 'count': self.catalog[cat][fam],
                            'state': cf_key(cat, fam) in self.ticked,
                            'open': True})
        return out

    def chosen_keys(self):
        """Ticked keys, collapsed to cat|* where a whole category is ticked."""
        out = set()
        for cat in self.categories():
            if self.cat_state(cat) is True and self.families(cat):
                out.add(cf_key(cat, WHOLE))
        for key in self.ticked:
            cat, fam = split_key(key)
            if cf_key(cat, WHOLE) in out:
                continue
            out.add(key)
        return sorted(out)

    def summary(self):
        cats = set()
        n = 0
        for key in self.ticked:
            cat, fam = split_key(key)
            cats.add(cat)
            n += 1
        return n, len(cats)


# ======================================================================
# Boxes and pair finding (all lengths in Revit feet)
# ======================================================================

def box_from_points(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def box_corners(box):
    x0, y0, z0, x1, y1, z1 = box
    return [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]


def transform_box(box, fn):
    """Axis aligned box round box after fn (a point -> point mapping)."""
    if fn is None:
        return box
    return box_from_points([fn(c) for c in box_corners(box)])


def boxes_overlap(a, b, pad=0.0):
    return (a[0] - pad <= b[3] and b[0] - pad <= a[3] and
            a[1] - pad <= b[4] and b[1] - pad <= a[4] and
            a[2] - pad <= b[5] and b[2] - pad <= a[5])


def overlap_box(a, b):
    box = (max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2]),
           min(a[3], b[3]), min(a[4], b[4]), min(a[5], b[5]))
    if box[0] > box[3] or box[1] > box[4] or box[2] > box[5]:
        return None
    return box


def box_centre(box):
    return ((box[0] + box[3]) / 2.0, (box[1] + box[4]) / 2.0,
            (box[2] + box[5]) / 2.0)


def box_extents(box):
    return (box[3] - box[0], box[4] - box[1], box[5] - box[2])


def min_extent(box):
    return min(box_extents(box))


def _cells(box, cell):
    i0, j0, k0 = [int((v // cell)) for v in box[0:3]]
    i1, j1, k1 = [int((v // cell)) for v in box[3:6]]
    return i0, j0, k0, i1, j1, k1


def grid_cell_size(boxes, floor=1.0, ceiling=50.0):
    """A cell about twice the median box size, so most boxes sit in a
    handful of cells and a long run does not land in hundreds."""
    if not boxes:
        return floor
    sizes = sorted(max(box_extents(b)) for b in boxes)
    median = sizes[len(sizes) // 2]
    return max(floor, min(ceiling, median * 2.0))


def candidate_pairs(boxes_a, boxes_b, pad=0.0, cell=None):
    """Index pairs (ia, ib) whose boxes overlap (within pad).

    A uniform grid over set B keeps this near linear, so a set of
    thousands against thousands does not compare every pair."""
    if not boxes_a or not boxes_b:
        return []
    if cell is None:
        cell = grid_cell_size(list(boxes_a) + list(boxes_b))
    # cap the cells one box may cover, so a huge element (a slab) is put
    # in a separate list and checked against everything instead
    grid = {}
    big = []
    for ib, box in enumerate(boxes_b):
        i0, j0, k0, i1, j1, k1 = _cells(box, cell)
        if (i1 - i0 + 1) * (j1 - j0 + 1) * (k1 - k0 + 1) > 4096:
            big.append(ib)
            continue
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                for k in range(k0, k1 + 1):
                    grid.setdefault((i, j, k), []).append(ib)
    out = []
    for ia, box in enumerate(boxes_a):
        padded = (box[0] - pad, box[1] - pad, box[2] - pad,
                  box[3] + pad, box[4] + pad, box[5] + pad)
        seen = set()
        i0, j0, k0, i1, j1, k1 = _cells(padded, cell)
        span = (i1 - i0 + 1) * (j1 - j0 + 1) * (k1 - k0 + 1)
        if span > 4096:
            pool = range(len(boxes_b))
        else:
            pool = []
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    for k in range(k0, k1 + 1):
                        pool.extend(grid.get((i, j, k), ()))
            pool.extend(big)
        for ib in pool:
            if ib in seen:
                continue
            seen.add(ib)
            if boxes_overlap(box, boxes_b[ib], pad):
                out.append((ia, ib))
    return out


def pair_key(uid_a, uid_b):
    """The same two elements give the same key whichever set each came from."""
    return tuple(sorted([to_text(uid_a), to_text(uid_b)]))


def is_touching(intersection_box, touch_ft):
    """An intersection thinner than touch_ft in any direction is two faces
    touching (a tray on its bracket), not a clash."""
    if intersection_box is None:
        return True
    return min_extent(intersection_box) < touch_ft


def weighted_centroid(parts):
    """parts: [((x, y, z), weight)] -> weighted centre, or None."""
    total = 0.0
    sx = sy = sz = 0.0
    for (x, y, z), w in parts:
        w = float(w)
        if w <= 0:
            continue
        total += w
        sx += x * w
        sy += y * w
        sz += z * w
    if total <= 0:
        return None
    return (sx / total, sy / total, sz / total)


def move_to_centre(target, current_centre):
    """The vector that puts current_centre on target."""
    return (target[0] - current_centre[0], target[1] - current_centre[1],
            target[2] - current_centre[2])


def choose_level(levels, z):
    """levels: [(level_id, elevation_ft)] -> id of the level the point sits
    on (highest at or below it), or the lowest when it is below them all."""
    if not levels:
        return None
    ordered = sorted(levels, key=lambda l: l[1])
    best = ordered[0][0]
    for lid, elev in ordered:
        if elev <= z + 1e-6:
            best = lid
    return best


# ======================================================================
# Results
# ======================================================================

def side_label(side):
    return describe(side, 'family_type')


def summarise(clashes):
    """[(label_a, label_b, count)] most clashes first."""
    counts = {}
    for c in clashes:
        key = (side_label(c['a']), side_label(c['b']))
        counts[key] = counts.get(key, 0) + 1
    rows = [(k[0], k[1], n) for k, n in counts.items()]
    rows.sort(key=lambda r: (-r[2], r[0].lower(), r[1].lower()))
    return rows


def dedupe(clashes):
    seen = set()
    out = []
    for c in clashes:
        key = pair_key(c['a']['uid'], c['b']['uid'])
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


# ======================================================================
# Saved clash tests (one key=value file per test, per project)
# ======================================================================

LIST_SEP = u'||'
DETECT_MODES = [('solid', u'Solid intersection'), ('box', u'Bounding box (fast)')]

RUN_SCOPES = [('view', u'Current view'), ('project', u'Whole project')]

TEST_DEFAULTS = {
    'name': u'New clash test',
    'a_models': [u'HOST'],
    'a_keys': [],
    'b_models': [u'HOST'],
    'b_keys': [],
    'mode': u'solid',
    'touch_mm': 5.0,
    'skip_connected': True,
    'scope': u'view',
    'last_count': -1,
    'last_run': u'',
}


def new_test(name=None):
    test = dict(TEST_DEFAULTS)
    test['a_models'] = list(TEST_DEFAULTS['a_models'])
    test['b_models'] = list(TEST_DEFAULTS['b_models'])
    test['a_keys'] = []
    test['b_keys'] = []
    if name:
        test['name'] = name
    return test


# ======================================================================
# Worksets offered for clash families
# ======================================================================

SUGGESTED_WORKSET = u'Z_BIM_Clash_Sphere'
WS_CREATE = u'<create>'
WS_CUSTOM = u'<custom>'


def ws_create_tag(name):
    return WS_CREATE + to_text(name)


def parse_ws_tag(tag):
    """(kind, name): kind is 'create', 'custom', 'existing' or None."""
    tag = to_text(tag)
    if not tag:
        return None, u''
    if tag == WS_CUSTOM:
        return 'custom', u''
    if tag.startswith(WS_CREATE):
        return 'create', tag[len(WS_CREATE):]
    return 'existing', tag


def workset_entries(existing, pending=()):
    """What the workset lists offer, top down: the suggested workset to
    create (only when the model has no workset of that name), any custom
    names waiting to be created, 'Custom workset', then the model's
    worksets. [(kind, name, tag)]"""
    taken = set(to_text(n).lower() for n in existing)
    out = []
    offered = set()
    for name in [SUGGESTED_WORKSET] + list(pending):
        key = to_text(name).lower()
        if key in taken or key in offered:
            continue
        offered.add(key)
        out.append(('create', name, ws_create_tag(name)))
    out.append(('custom', u'Custom workset...', WS_CUSTOM))
    for name in existing:
        out.append(('existing', name, name))
    return out


def default_ws_tag(saved, entries):
    """The saved workset when it is still offered (as itself or waiting to
    be created), else the suggested workset, whether it exists or not."""
    for wanted in (saved, SUGGESTED_WORKSET):
        key = to_text(wanted).lower()
        if not key:
            continue
        for kind, name, tag in entries:
            if kind != 'custom' and to_text(name).lower() == key:
                return tag
    for kind, name, tag in entries:
        if kind != 'custom':
            return tag
    return None


def check_workset_name(text, existing):
    """(name, problem, existing_name). existing_name is set when the model
    already has a workset of that name (any case) - use it, create nothing."""
    clean = u' '.join(to_text(text).split())
    if not clean:
        return clean, u'The workset name cannot be blank.', None
    bad = [ch for ch in clean if ch in _FORBIDDEN or ord(ch) < 32]
    if bad:
        return clean, u'A workset name cannot contain {0}'.format(
            u' '.join(sorted(set(bad)))), None
    if clean.startswith(u'<'):
        return clean, u'A workset name cannot start with "<".', None
    for name in existing:
        if to_text(name).lower() == clean.lower():
            return clean, None, name
    return clean, None, None


SCHEDULE_NAME = u'BIM_Clash Analysis Schedule'
# Schedule body text is 2.5 mm Arial by default: allow 2 mm a character
# (capitals and digits are the wide ones) plus the cell padding.
SCHEDULE_MM_PER_CHAR = 2.0
SCHEDULE_PAD_MM = 8.0
SCHEDULE_MIN_MM = 60.0
SCHEDULE_MAX_MM = 400.0
SCHEDULE_EMPTY_MM = 120.0
SCHEDULE_LEVEL_MM = 40.0


def comment_column_mm(comments):
    """Width of the Comments column so the longest comment shows in full,
    between the minimum and maximum. With no comments yet: a sensible
    width for an "A-vs-B" description."""
    longest = 0
    for c in comments:
        longest = max(longest, len(to_text(c).strip()))
    if not longest:
        return SCHEDULE_EMPTY_MM
    wanted = longest * SCHEDULE_MM_PER_CHAR + SCHEDULE_PAD_MM
    return max(SCHEDULE_MIN_MM, min(SCHEDULE_MAX_MM, wanted))


def marker_level(fixed_level, level_pairs, z):
    """Level for one clash family: the view's level when the clash test ran
    on a floor plan, otherwise the closest level at or below the clash
    (the lowest level when the clash is below them all)."""
    if fixed_level is not None:
        return fixed_level
    return choose_level(level_pairs, z)


def dump_test(test):
    lines = [u'version=1']
    for key in sorted(TEST_DEFAULTS.keys()):
        value = test.get(key, TEST_DEFAULTS[key])
        if isinstance(TEST_DEFAULTS[key], list):
            value = LIST_SEP.join(to_text(v) for v in value)
        elif isinstance(TEST_DEFAULTS[key], bool):
            value = u'1' if value else u'0'
        lines.append(u'{0}={1}'.format(key, to_text(value)))
    return u'\n'.join(lines) + u'\n'


def parse_test(text):
    test = new_test()
    for raw in to_text(text).splitlines():
        if u'=' not in raw:
            continue
        key, value = raw.split(u'=', 1)
        key = key.strip()
        if key not in TEST_DEFAULTS:
            continue
        default = TEST_DEFAULTS[key]
        try:
            if isinstance(default, list):
                test[key] = [v for v in value.split(LIST_SEP) if v.strip()]
            elif isinstance(default, bool):
                test[key] = value.strip() in (u'1', u'true', u'True')
            elif isinstance(default, int):
                test[key] = int(value.strip())
            elif isinstance(default, float):
                test[key] = float(value.strip())
            else:
                test[key] = value
        except Exception:
            pass
    if test['mode'] not in [m[0] for m in DETECT_MODES]:
        test['mode'] = TEST_DEFAULTS['mode']
    if test['scope'] not in [s[0] for s in RUN_SCOPES]:
        test['scope'] = TEST_DEFAULTS['scope']
    return test


def check_test_name(new, old, existing):
    """(clean_name, problem) for renaming saved test old to new.

    The name is tidied (whitespace collapsed). It must not be blank, must
    not match another saved test whatever the case, and must not land on
    another test's file - 'a/b' and 'a_b' would both be saved as a_b.txt.
    Renaming a test to its own name (or a change of case) is allowed."""
    clean = u' '.join(to_text(new).split())
    if not clean:
        return clean, u'The name cannot be blank.'
    if LIST_SEP in clean:
        return clean, u'The name cannot contain "||".'
    old_key = to_text(old).lower()
    for other in existing:
        o = to_text(other)
        if o.lower() == old_key:
            continue
        if o.lower() == clean.lower():
            return clean, u'There is already a clash test called "{0}".'.format(o)
        if safe_filename(o).lower() == safe_filename(clean).lower():
            return clean, (u'"{0}" would be saved over the clash test "{1}" - '
                           u'change a character other than \\ / : * ? " < > |'
                           .format(clean, o))
    return clean, None


def rename_in_order(order, old, new):
    """The run-order list with old replaced by new, keeping its place."""
    return [new if n == old else n for n in order if n != new or n == old]


def project_key(title, central_path=None):
    """One folder of saved tests per project, whoever's local copy is open."""
    name = to_text(central_path or u'').replace(u'/', u'\\').split(u'\\')[-1]
    if not name:
        name = to_text(title)
    if name.lower().endswith(u'.rvt'):
        name = name[:-4]
    return safe_filename(name)


# ======================================================================
# Settings  (%APPDATA%\RevoBIM\clash_analysis.txt)
# ======================================================================

SETTINGS_VERSION = 1
MIGRATIONS = {
    # version: {key: new default} - applied once to files older than it
}

DEFAULTS = {
    'settings_version': SETTINGS_VERSION,
    'theme': u'follow',
    'marker_family': u'',
    'workset': u'',
    'comment_format': u'family_type',
    'debug': True,
    'last_test': u'',
    'win_width': 1280.0,
    'win_height': 800.0,
    'tests_open': True,
    'sets_open': True,
    'models_height': 0.0,
}

THEMES = (u'follow', u'dark', u'light')


def _coerce(key, value):
    default = DEFAULTS[key]
    if isinstance(default, bool):
        v = value.strip().lower()
        if v in (u'1', u'true', u'yes'):
            return True
        if v in (u'0', u'false', u'no'):
            return False
        raise ValueError(key)
    if isinstance(default, int):
        return int(value.strip())
    if isinstance(default, float):
        return float(value.strip())
    return value


def parse_settings(text):
    """Missing or damaged values fall back to the default key by key;
    unknown keys from another version are ignored."""
    out = dict(DEFAULTS)
    found_version = 0
    for raw in to_text(text).splitlines():
        if u'=' not in raw or raw.strip().startswith(u'#'):
            continue
        key, value = raw.split(u'=', 1)
        key = key.strip()
        if key not in DEFAULTS:
            continue
        try:
            out[key] = _coerce(key, value)
            if key == 'settings_version':
                found_version = out[key]
        except Exception:
            out[key] = DEFAULTS[key]
    if out['theme'] not in THEMES:
        out['theme'] = DEFAULTS['theme']
    if out['comment_format'] not in [f[0] for f in COMMENT_FORMATS]:
        out['comment_format'] = DEFAULTS['comment_format']
    for version in sorted(MIGRATIONS.keys()):
        if found_version < version:
            for key, value in MIGRATIONS[version].items():
                out[key] = value
    out['settings_version'] = SETTINGS_VERSION
    return out


def dump_settings(values):
    lines = []
    for key in sorted(DEFAULTS.keys()):
        value = values.get(key, DEFAULTS[key])
        if isinstance(DEFAULTS[key], bool):
            value = u'1' if value else u'0'
        lines.append(u'{0}={1}'.format(key, to_text(value)))
    return u'\n'.join(lines) + u'\n'


# ======================================================================
# Theme
# ======================================================================

PALETTE_DARK = {
    # Revit's own dark theme, sampled from its dark Project Browser
    'WindowBg': '#3C4454',
    'BarBg': '#222933',
    'FieldBg': '#2D3441',
    'ToolbarBg': '#1B1F24',
    'HeadBg': '#323C48',
    'CardBg': '#353D4B',
    'HoverBg': '#444E5E',
    'SelBg': '#3A7392',
    'Edge': '#515C6B',
    'Text': '#EEF0F4',
    'Muted': '#B4BAC2',
    'Blue': '#5AAEEB',
    'Orange': '#E8912D',
    'Green': '#3FA75A',
    'GreenHover': '#4EC06D',
    'Red': '#D9534F',
    'OnAccent': '#FFFFFF',
}

PALETTE_LIGHT = {
    'WindowBg': '#F4F5F7',
    'BarBg': '#E1E5EA',
    'FieldBg': '#FFFFFF',
    'ToolbarBg': '#D7DCE2',
    'HeadBg': '#E7EAEE',
    'CardBg': '#FFFFFF',
    'HoverBg': '#DCE3EA',
    'SelBg': '#BFD9EE',
    'Edge': '#B3BAC4',
    'Text': '#1E2228',
    'Muted': '#555C66',
    'Blue': '#1B72BE',
    'Orange': '#B96A12',
    'Green': '#2E8546',
    'GreenHover': '#379A53',
    'Red': '#B83B37',
    'OnAccent': '#FFFFFF',
}

PALETTE_KEYS = sorted(PALETTE_DARK.keys())


def next_theme(setting):
    order = list(THEMES)
    try:
        return order[(order.index(setting) + 1) % len(order)]
    except ValueError:
        return u'follow'


def resolve_theme(setting, canvas):
    """canvas: Revit's UITheme value - 0 Dark, 1 Light, None unknown.
    UITheme.Dark is 0, so this must test 'is None', never truthiness."""
    if setting == u'dark':
        return u'dark'
    if setting == u'light':
        return u'light'
    if canvas is None:
        return u'dark'
    return u'dark' if int(canvas) == 0 else u'light'


def palette_for(name):
    return PALETTE_LIGHT if name == u'light' else PALETTE_DARK


def theme_chip_label(setting, resolved):
    if setting == u'follow':
        return u'Auto ({0})'.format(u'Dark' if resolved == u'dark' else u'Light')
    return u'Dark' if setting == u'dark' else u'Light'


def _lum(hex_colour):
    h = hex_colour.lstrip('#')
    vals = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        vals.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * vals[0] + 0.7152 * vals[1] + 0.0722 * vals[2]


def contrast(fg, bg):
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# ======================================================================
# Shrink-to-taskbar drawer: arithmetic and the state machine
# ======================================================================

DRAWER_GAP = 8.0
DRAWER_FRAMES = 14
DRAWER_TICK_MS = 15


def parked_bounds(work_area, header_h, gap=DRAWER_GAP):
    """work_area: (left, top, width, height) of the screen the window is on.
    Returns (top, height) for the parked bar: just the header, floating gap
    pixels above the bottom of the work area. A monitor above the primary
    has a negative top, which is kept rather than clamped."""
    wl, wt, ww, wh = work_area
    return (wt + wh - header_h - gap, header_h)


def reopen_bounds(saved, bar_top, parked_top, header_h, work_area):
    """saved: (top, height) before parking. If the bar has not been moved
    the window goes back where it was; if it has, it opens upward from where
    the bar now sits, kept inside the work area."""
    top, height = saved
    wl, wt, ww, wh = work_area
    if abs(bar_top - parked_top) < 1.0:
        new_top = top
    else:
        new_top = bar_top + header_h - height
    if new_top < wt:
        new_top = wt
    if new_top + height > wt + wh:
        new_top = max(wt, wt + wh - height)
    return (new_top, height)


def ease(t):
    """Ease out cubic, 0..1."""
    t = max(0.0, min(1.0, float(t)))
    return 1.0 - (1.0 - t) ** 3


def frame_bounds(start, end, i, frames=DRAWER_FRAMES):
    t = ease(float(i) / float(frames))
    return (start[0] + (end[0] - start[0]) * t,
            start[1] + (end[1] - start[1]) * t)


class DrawerMachine(object):
    """Drives the slide. host is an adapter round the real window:

        bounds() -> (left, top, width, height)
        work_area() -> (left, top, width, height)
        header_height() -> float
        set_bounds(top, height)
        prepare(parking)   relax MinHeight / SizeToContent, pin the body,
                           park or restore the resize grips
        release()          clear any held animation on Top and Height
        finished(parked)   swap the button glyph, restore MinHeight ...

    timer_factory(interval_ms, on_tick) -> object with Start() / Stop().
    """

    def __init__(self, host, timer_factory, frames=DRAWER_FRAMES):
        self.host = host
        self.timer_factory = timer_factory
        self.frames = frames
        self.parked = False
        self.sliding = False
        self.saved = None
        self.parked_top = None
        self.errors = []
        self._timer = None
        self._i = 0
        self._start = None
        self._end = None
        self._parking = False

    def toggle(self):
        if self.sliding:
            return False
        if self.parked:
            self.reopen()
        else:
            self.park()
        return True

    def park(self):
        if self.sliding or self.parked:
            return
        left, top, width, height = self.host.bounds()
        header = self.host.header_height()
        self.saved = (top, height)
        end = parked_bounds(self.host.work_area(), header)
        self.parked_top = end[0]
        self._begin((top, height), end, True)

    def reopen(self):
        if self.sliding or not self.parked:
            return
        left, top, width, height = self.host.bounds()
        header = self.host.header_height()
        end = reopen_bounds(self.saved, top, self.parked_top, header,
                            self.host.work_area())
        self._begin((top, height), end, False)

    def _begin(self, start, end, parking):
        self.sliding = True
        self._parking = parking
        self._start = start
        self._end = end
        self._i = 0
        try:
            self.host.prepare(parking)
        except Exception as ex:
            self.errors.append(u'prepare: {0}'.format(ex))
        try:
            self._timer = self.timer_factory(DRAWER_TICK_MS, self._tick)
            self._timer.Start()
        except Exception as ex:
            self.errors.append(u'timer: {0}'.format(ex))
            self._land()

    def _tick(self, *args):
        try:
            self._i += 1
            if self._i >= self.frames:
                self._land()
                return
            top, height = frame_bounds(self._start, self._end, self._i,
                                       self.frames)
            self.host.set_bounds(top, height)
        except Exception as ex:
            self.errors.append(u'tick: {0}'.format(ex))
            self._land()

    def _land(self):
        try:
            if self._timer is not None:
                self._timer.Stop()
        except Exception:
            pass
        self._timer = None
        try:
            self.host.release()
        except Exception as ex:
            self.errors.append(u'release: {0}'.format(ex))
        try:
            self.host.set_bounds(self._end[0], self._end[1])
        except Exception as ex:
            self.errors.append(u'land: {0}'.format(ex))
        self.parked = self._parking
        self.sliding = False
        try:
            self.host.finished(self.parked)
        except Exception as ex:
            self.errors.append(u'finished: {0}'.format(ex))


# ======================================================================
# Collapsible sections (Saved clash tests, Set A + Set B)
# ======================================================================

CHEVRON_OPEN = 0.0
CHEVRON_SHUT = -90.0


def chevron_angle(opening, t):
    """Chevron angle at eased progress t of a slide."""
    t = ease(t)
    if opening:
        return CHEVRON_SHUT + (CHEVRON_OPEN - CHEVRON_SHUT) * t
    return CHEVRON_OPEN + (CHEVRON_SHUT - CHEVRON_OPEN) * t


class SectionMachine(object):
    """Drawer slide for a section of the window. host:

        current() -> height shown now
        open_target() -> height when fully open (measured, not guessed)
        begin()  pin the section so the slide drives its height
        apply(height, chevron_angle)
        land(is_open)  hand sizing back to the layout, final chevron

    timer_factory(interval_ms, on_tick) -> object with Start() / Stop().
    A slide already running ignores further clicks; any failure lands the
    section in its new state rather than leaving it half way."""

    def __init__(self, host, timer_factory, is_open=True, frames=DRAWER_FRAMES):
        self.host = host
        self.timer_factory = timer_factory
        self.frames = frames
        self.is_open = bool(is_open)
        self.sliding = False
        self.errors = []
        self._timer = None
        self._i = 0
        self._start = 0.0
        self._end = 0.0

    def toggle(self):
        return self.set_open(not self.is_open)

    def set_open(self, want, animate=True):
        want = bool(want)
        if self.sliding or want == self.is_open:
            return False
        self.is_open = want
        self.sliding = True
        self._i = 0
        try:
            self._start = float(self.host.current())
            self._end = float(self.host.open_target()) if want else 0.0
            self.host.begin()
            self.host.apply(max(0.0, self._start), chevron_angle(want, 0.0))
        except Exception as ex:
            self.errors.append(u'begin: {0}'.format(ex))
            self._land()
            return True
        if not animate or abs(self._end - self._start) < 1.0:
            self._land()
            return True
        try:
            self._timer = self.timer_factory(DRAWER_TICK_MS, self._tick)
            self._timer.Start()
        except Exception as ex:
            self.errors.append(u'timer: {0}'.format(ex))
            self._land()
        return True

    def _tick(self, *args):
        try:
            self._i += 1
            if self._i >= self.frames:
                self._land()
                return
            t = float(self._i) / float(self.frames)
            h = self._start + (self._end - self._start) * ease(t)
            self.host.apply(max(0.0, h), chevron_angle(self.is_open, t))
        except Exception as ex:
            self.errors.append(u'tick: {0}'.format(ex))
            self._land()

    def _land(self):
        try:
            if self._timer is not None:
                self._timer.Stop()
        except Exception:
            pass
        self._timer = None
        self.sliding = False
        try:
            self.host.land(self.is_open)
        except Exception as ex:
            self.errors.append(u'land: {0}'.format(ex))


# ======================================================================
# Isolate Clash Sphere: which view, and the floor plan picker
# ======================================================================

def plan_matches(view, term, level_key=None, on_level_only=False):
    """view: {'name', 'level', 'level_key'}. Every word of term must appear
    in the plan's name or its level name, any case."""
    if on_level_only and level_key is not None and view.get('level_key') != level_key:
        return False
    hay = (to_text(view.get('name')) + u' ' + to_text(view.get('level'))).lower()
    for word in to_text(term).lower().split():
        if word not in hay:
            return False
    return True


def plan_choices(views, term=u'', level_key=None, on_level_only=False):
    """Plans to offer, the group's level first, then by level and name."""
    picked = [v for v in views if plan_matches(v, term, level_key, on_level_only)]
    picked.sort(key=lambda v: (0 if (level_key is not None and
                                     v.get('level_key') == level_key) else 1,
                               to_text(v.get('level')).lower(),
                               to_text(v.get('name')).lower()))
    return picked


def isolate_here(active_level_key, group_level_key):
    """Isolate in the active view only when it is a plan on the group's level."""
    return (active_level_key is not None and group_level_key is not None and
            active_level_key == group_level_key)


def most_common(keys):
    """The value seen most often (first seen wins a tie), or None."""
    counts = {}
    order = []
    for k in keys:
        if k is None:
            continue
        if k not in counts:
            order.append(k)
        counts[k] = counts.get(k, 0) + 1
    best = None
    for k in order:
        if best is None or counts[k] > counts[best]:
            best = k
    return best


# ======================================================================
# Review status of each clash family (Clash Groups tab)
# ======================================================================

# key, label, palette brush, the number the table sorts and colours by
REVIEW_STATES = [('not', u'Not reviewed', 'Red', 0),
                 ('reviewed', u'Reviewed', 'Orange', 1),
                 ('ok', u'OK', 'Green', 2)]
REVIEW_KEYS = [r[0] for r in REVIEW_STATES]
REVIEW_FILE = u'_review_status.dat'


def review_state(store, uid):
    state = store.get(to_text(uid))
    return state if state in REVIEW_KEYS else u'not'


def review_number(state):
    for key, label, brush, n in REVIEW_STATES:
        if key == state:
            return n
    return 0


def review_label(state):
    for key, label, brush, n in REVIEW_STATES:
        if key == state:
            return label
    return REVIEW_STATES[0][1]


def after_zoom(state):
    """Zooming to a clash family marks it Reviewed; OK is only ever set
    (or taken away) by hand."""
    return u'reviewed' if state in (None, u'', u'not') else state


def set_reviews(store, uids, state):
    """Set every uid to state. Not reviewed is the default, so it is
    stored as no entry. Returns how many changed."""
    if state not in REVIEW_KEYS:
        raise ValueError(state)
    changed = 0
    for uid in uids:
        uid = to_text(uid)
        if not uid:
            continue
        if review_state(store, uid) == state:
            continue
        if state == u'not':
            store.pop(uid, None)
        else:
            store[uid] = state
        changed += 1
    return changed


def parse_reviews(text):
    store = {}
    for raw in to_text(text).splitlines():
        if u'=' not in raw:
            continue
        uid, state = raw.split(u'=', 1)
        uid, state = uid.strip(), state.strip()
        if uid and state in REVIEW_KEYS and state != u'not':
            store[uid] = state
    return store


def dump_reviews(store):
    lines = [u'{0}={1}'.format(uid, store[uid]) for uid in sorted(store)
             if store[uid] in REVIEW_KEYS and store[uid] != u'not']
    return u'\n'.join(lines) + (u'\n' if lines else u'')


def review_summary(states):
    """'2 OK - 1 reviewed - 5 not reviewed' for a list of states."""
    counts = dict((k, 0) for k in REVIEW_KEYS)
    for st in states:
        counts[st if st in counts else u'not'] += 1
    return u'{0} OK - {1} reviewed - {2} not reviewed'.format(
        counts[u'ok'], counts[u'reviewed'], counts[u'not'])


# ======================================================================
# View in 3D
# ======================================================================

SECTION_PAD_MM = 1000.0
NEW_3D_NAME = u'Clash Analysis 3D'


def default_3d(names, user=u''):
    """The 3D view to offer first: the user's own default 3D view
    ({3D - user} in a workshared model), then {3D}, then any {3D...},
    then the first. None when there are none."""
    names = list(names)
    if not names:
        return None
    wanted = [u'{3D - ' + to_text(user) + u'}', u'{3D}']
    low = dict((n.lower(), n) for n in names)
    for w in wanted:
        if w.lower() in low:
            return low[w.lower()]
    for n in names:
        if n.startswith(u'{3D'):
            return n
    return names[0]


def section_box_around(boxes, pad):
    """One box round every (x0, y0, z0, x1, y1, z1), grown by pad each way."""
    boxes = [b for b in boxes if b is not None]
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes) - pad
    y0 = min(b[1] for b in boxes) - pad
    z0 = min(b[2] for b in boxes) - pad
    x1 = max(b[3] for b in boxes) + pad
    y1 = max(b[4] for b in boxes) + pad
    z1 = max(b[5] for b in boxes) + pad
    return (x0, y0, z0, x1, y1, z1)
