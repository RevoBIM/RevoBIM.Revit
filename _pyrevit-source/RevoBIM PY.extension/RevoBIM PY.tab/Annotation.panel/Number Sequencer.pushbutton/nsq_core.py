# -*- coding: utf-8 -*-
"""Number Sequencer - every rule that needs no .NET.

Version, settings, palettes, the walk order through a duct network
(branches first, then carry on up the main), number formatting, the
category > family > type tree and the plan of what gets written.

Nothing in here may import System, Autodesk or clr: bench_logic.py runs it
under plain CPython.
"""

import os
import math

__version__ = u"1.13.2"
TOOL_NAME = u"Number Sequencer"
SETTINGS_FILE = u"number_sequencer.txt"
DEBUG_FILE = u"number_sequencer_debug.txt"
SETTINGS_VERSION = 1

# ============================================================
# Settings
# ============================================================

DEFAULTS = {
    u"settings_version": u"1",
    u"parameter": u"",
    u"pad": u"3",
    u"start": u"1",
    u"direction": u"up",
    u"tag": u"off",
    u"tag_type": u"",
    u"skip": u"",
    u"theme": u"auto",
    u"debug": u"on",
    u"tab": u"seq",
    u"sel_kind": u"duct",
    u"sel_skip": u"",
    u"view_g1": u"",
    u"view_g2": u"",
    u"tag_views": u"",
    u"view_kinds_off": u"",
    u"iso3d_view": u"",
    u"collapsed": u"",
    u"tag_untagged": u"on",
    u"tag_tab": u"sheets",
    u"win_w": u"",
    u"win_h": u"",
}

# version -> {key: new default}; applied to files written by older versions
MIGRATIONS = {}

SKIP_SEP = u"||"


def settings_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, u"RevoBIM")


def settings_path():
    return os.path.join(settings_dir(), SETTINGS_FILE)


def debug_path():
    return os.path.join(settings_dir(), DEBUG_FILE)


def parse_settings(text):
    """key=value lines, split on the first '=' only. Unknown keys ignored,
    missing or damaged keys fall back to the default one by one."""
    out = dict(DEFAULTS)
    if not text:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(u"#") or u"=" not in line:
            continue
        key, value = line.split(u"=", 1)
        key = key.strip()
        if key in DEFAULTS:
            out[key] = value.strip()
    try:
        old = int(out.get(u"settings_version") or 0)
    except Exception:
        old = 0
    for ver in sorted(MIGRATIONS):
        if old < ver:
            for k, v in MIGRATIONS[ver].items():
                out[k] = v
    out[u"settings_version"] = u"{0}".format(SETTINGS_VERSION)
    return out


def format_settings(values):
    keys = sorted(DEFAULTS)
    lines = [u"# RevoBIM Number Sequencer settings"]
    for k in keys:
        v = values.get(k, DEFAULTS[k])
        v = u"{0}".format(v).replace(u"\r", u" ").replace(u"\n", u" ")
        lines.append(u"{0}={1}".format(k, v))
    return u"\n".join(lines) + u"\n"


def load_settings(path=None):
    path = path or settings_path()
    try:
        with open(path, "r") as fh:
            text = fh.read()
        try:
            text = text.decode("utf-8")
        except Exception:
            pass
    except Exception:
        text = u""
    return parse_settings(text)


def save_settings(values, path=None):
    path = path or settings_path()
    try:
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        data = format_settings(values)
        try:
            data = data.encode("utf-8")
            mode = "wb"
        except Exception:
            mode = "w"
        with open(path, mode) as fh:
            fh.write(data)
        return True
    except Exception:
        return False


def skip_keys_from(text):
    if not text:
        return set()
    return set([s for s in text.split(SKIP_SEP) if s])


def skip_text_from(keys):
    return SKIP_SEP.join(sorted(keys))


# ============================================================
# Palettes - house style, dark and light
# ============================================================

DARK = {
    u"Bg": u"#232326",
    u"Card": u"#2B2B2E",
    u"Field": u"#1C1C1F",
    u"Bar": u"#1C1C1F",
    u"Edge": u"#3E3E42",
    u"ChromeEdge": u"#4A4A50",
    u"Text": u"#E4E4E4",
    u"Muted": u"#9A9A9E",
    u"Blue": u"#4FA3E3",
    u"Orange": u"#E8912D",
    u"Green": u"#3FA75A",
    u"GreenHover": u"#4EC06D",
    u"Red": u"#D9534F",
    u"Sel": u"#2B5473",
    u"Hover": u"#34343A",
    u"OnAccent": u"#FFFFFF",
}

LIGHT = {
    u"Bg": u"#F3F3F5",
    u"Card": u"#FFFFFF",
    u"Field": u"#FAFAFB",
    u"Bar": u"#E6E6EA",
    u"Edge": u"#C9C9CF",
    u"ChromeEdge": u"#B4B4BC",
    u"Text": u"#1E1E22",
    u"Muted": u"#66666E",
    u"Blue": u"#1B72BE",
    u"Orange": u"#B96A12",
    u"Green": u"#2E8546",
    u"GreenHover": u"#379C53",
    u"Red": u"#C03A36",
    u"Sel": u"#CFE3F5",
    u"Hover": u"#E9EEF4",
    u"OnAccent": u"#FFFFFF",
}

# one colour per family; its types share it as a lighter tint
GROUP_DARK = [u"#4FA3E3", u"#E8912D", u"#3FA75A", u"#B07CD8", u"#D9C34F",
              u"#4FC1C9", u"#D96C8A", u"#8FB04F", u"#C98A5A", u"#7F95E8"]
GROUP_LIGHT = [u"#1B72BE", u"#B96A12", u"#2E8546", u"#7C4BA8", u"#9C8410",
               u"#16858C", u"#A8385A", u"#5B7A1E", u"#94582A", u"#3F57B8"]


def palette_for(mode):
    return LIGHT if mode == u"light" else DARK


def group_colour(index, mode):
    seq = GROUP_LIGHT if mode == u"light" else GROUP_DARK
    return seq[index % len(seq)]


THEME_CYCLE = [u"auto", u"dark", u"light"]


def next_theme(setting):
    try:
        i = THEME_CYCLE.index(setting)
    except ValueError:
        i = 0
    return THEME_CYCLE[(i + 1) % len(THEME_CYCLE)]


def resolve_theme(setting, canvas_is_dark):
    """auto follows Revit's canvas; canvas_is_dark None means unreadable."""
    if setting == u"dark":
        return u"dark"
    if setting == u"light":
        return u"light"
    if canvas_is_dark is None:
        return u"dark"
    return u"dark" if canvas_is_dark else u"light"


def theme_label(setting):
    return {u"auto": u"Auto", u"dark": u"Dark", u"light": u"Light"}.get(setting, u"Auto")


def luminance_is_dark(r, g, b):
    try:
        return (0.299 * r + 0.587 * g + 0.114 * b) < 128
    except Exception:
        return None


class SlowClicks(object):
    """Three slow clicks: each gap at least floor, at most ceiling seconds."""

    def __init__(self, need=3, floor=0.25, ceiling=2.0):
        self.need = need
        self.floor = floor
        self.ceiling = ceiling
        self.times = []

    def click(self, t):
        if self.times:
            gap = t - self.times[-1]
            if gap < self.floor:
                return False
            if gap > self.ceiling:
                self.times = []
        self.times.append(t)
        if len(self.times) >= self.need:
            self.times = []
            return True
        return False


# ============================================================
# Number formatting and the plan
# ============================================================

PAD_CHOICES = [(3, u"001"), (2, u"01"), (0, u"1")]


def to_int(value, default=None):
    try:
        return int(u"{0}".format(value).strip())
    except Exception:
        return default


def parse_start(text):
    """'045' -> 45, '7' -> 7. Anything else -> None."""
    if text is None:
        return None
    t = u"{0}".format(text).strip()
    if not t or not t.isdigit():
        return None
    return int(t)


def format_number(n, pad):
    pad = to_int(pad, 0) or 0
    s = u"{0}".format(abs(int(n)))
    if pad > 0 and len(s) < pad:
        s = u"0" * (pad - len(s)) + s
    if n < 0:
        s = u"-" + s
    return s


def plan_numbers(order, include, start, direction, pad):
    """order: keys in walk order. include(key) -> bool.
    Returns (plan, errors): plan = [(key, n, text)], errors = [(key, msg)].
    Downwards never goes below 0; anything that would is an error."""
    step = -1 if direction == u"down" else 1
    plan = []
    errors = []
    n = int(start)
    for key in order:
        if not include(key):
            continue
        if n < 0:
            errors.append((key, u"Sequence ran below 0 counting down"))
            continue
        plan.append((key, n, format_number(n, pad)))
        n += step
    return plan, errors


def preview_text(plan, errors, skipped, pad):
    if not plan:
        return u"Nothing to number"
    first = plan[0][2]
    last = plan[-1][2]
    s = u"{0} numbered  {1} to {2}".format(len(plan), first, last)
    if skipped:
        s += u"  |  {0} skipped".format(skipped)
    if errors:
        s += u"  |  {0} below 0".format(len(errors))
    return s


def prepare_writes(plan, read_param):
    """Decide what each planned element needs before any transaction.
    read_param(key) -> dict(exists, readonly, storage, value) or None.
    storage is 'text' or 'integer'.
    Returns (writes, same, errors): writes = [(key, value_to_set)],
    same = [key] already holding the value, errors = [(key, msg)]."""
    writes = []
    same = []
    errors = []
    for key, n, text in plan:
        info = read_param(key)
        if not info or not info.get(u"exists"):
            errors.append((key, u"Parameter not on this element"))
            continue
        if info.get(u"readonly"):
            errors.append((key, u"Parameter is read-only here"))
            continue
        storage = info.get(u"storage")
        if storage == u"integer":
            target = int(n)
            if to_int(info.get(u"value")) == target and info.get(u"value") not in (None, u""):
                same.append(key)
            else:
                writes.append((key, target))
        elif storage == u"text":
            if (info.get(u"value") or u"") == text:
                same.append(key)
            else:
                writes.append((key, text))
        else:
            errors.append((key, u"Parameter is not text or integer"))
    return writes, same, errors


def value_matches(expected, got):
    if isinstance(expected, int) and not isinstance(expected, bool):
        return to_int(got) == expected
    return (got or u"") == expected


# ============================================================
# The network walk
# ============================================================

AREA_TOL = 0.01  # sizes within 1% count as the same size


class Conn(object):
    """One physical connector on a node.
    links: [(neighbour_key, neighbour_cid)] to elements in the set.
    equipment: joined to mechanical equipment outside the set.
    external: joined to anything outside the set."""

    def __init__(self, cid, area=0.0, origin=None, direction=None,
                 links=None, equipment=False, external=False):
        self.cid = cid
        self.area = area or 0.0
        self.origin = origin
        self.direction = direction
        self.links = list(links or [])
        self.equipment = equipment
        self.external = external


class Node(object):
    def __init__(self, key, conns=None, is_equipment=False, label=u""):
        self.key = key
        self.conns = list(conns or [])
        self.is_equipment = is_equipment
        self.label = label

    def area(self):
        best = 0.0
        for c in self.conns:
            if c.area > best:
                best = c.area
        return best

    def conn(self, cid):
        for c in self.conns:
            if c.cid == cid:
                return c
        return None


def _dot(a, b):
    try:
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    except Exception:
        return 0.0


def _dist(a, b):
    try:
        return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)
    except Exception:
        return 0.0


OPEN_END_TOL_MM = 5.0


def link_open_ends(nodes, tol):
    """Parts butted together but never connected in Revit - fabrication
    ductwork often is - are joined here: an open connector (no link, not
    joined to anything outside) is linked to the nearest other open
    connector within tol (model units) that faces it. Each connector joins
    once. Returns the number of joins made."""
    if tol <= 0:
        return 0
    opens = []
    for k in sorted(nodes):
        for c in nodes[k].conns:
            if c.links or c.external or c.equipment or c.origin is None:
                continue
            opens.append((k, c))

    def cell(p):
        return (int(math.floor(p[0] / tol)), int(math.floor(p[1] / tol)), int(math.floor(p[2] / tol)))

    buckets = {}
    for k, c in opens:
        buckets.setdefault(cell(c.origin), []).append((k, c))
    used = set()
    joins = 0
    for k, c in opens:
        if (k, c.cid) in used:
            continue
        cx, cy, cz = cell(c.origin)
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for k2, c2 in buckets.get((cx + dx, cy + dy, cz + dz), ()):
                        if k2 == k or (k2, c2.cid) in used:
                            continue
                        d = _dist(c.origin, c2.origin)
                        if d > tol:
                            continue
                        if c.direction is not None and c2.direction is not None and \
                                _dot(c.direction, c2.direction) > -0.5:
                            continue   # must face each other
                        if best is None or (d, k2) < (best[0], best[1]):
                            best = (d, k2, c2)
        if best is None:
            continue
        d, k2, c2 = best
        c.links.append((k2, c2.cid))
        c2.links.append((k, c.cid))
        used.add((k, c.cid))
        used.add((k2, c2.cid))
        joins += 1
    return joins


def box_in_crop(corners, mn, mx, use_z=False, tol=0.0):
    """corners: the element's bounding box corners already in crop-box
    coordinates. True when that box overlaps the crop box (in X and Y, and
    Z too for a 3D section box)."""
    if not corners:
        return True
    axes = (0, 1, 2) if use_z else (0, 1)
    for a in axes:
        lo = min([p[a] for p in corners])
        hi = max([p[a] for p in corners])
        if hi < mn[a] - tol or lo > mx[a] + tol:
            return False
    return True


def systems_holding(systems, id_values):
    """Indexes of the systems holding any of these elements (accessories
    included) - for following a pick in the view to its row."""
    want = set(id_values or ())
    return [i for i, sd in enumerate(systems) if want.intersection(sd[u"keys"])]


def group_summary(systems):
    """(systems named by Revit, by name only, loose pieces, single-part pieces)."""
    by_id = len([sd for sd in systems if sd[u"key"].startswith(u"id:")])
    by_name = len([sd for sd in systems if sd[u"key"].startswith(u"name:")])
    pieces = [sd for sd in systems if sd[u"key"].startswith(u"piece:")]
    return by_id, by_name, len(pieces), len([sd for sd in pieces if len(sd[u"keys"]) == 1])


def _live_links(conn, nodes, visited):
    return [(k, c) for (k, c) in conn.links
            if k in nodes and k not in visited]


def choose_start(nodes, candidates):
    """Where the walk begins when nobody picked a start.
    1 mechanical equipment in the set
    2 an element joined to equipment outside the set (the source)
    3 an open end - one live link or none - biggest size first
    4 anything, biggest first. Ties: lowest key."""
    keys = sorted(candidates)
    if not keys:
        return None
    visited = set(nodes) - set(candidates)

    def size_key(k):
        return (-nodes[k].area(), k)

    eq = [k for k in keys if nodes[k].is_equipment]
    if eq:
        return sorted(eq, key=size_key)[0]
    src = [k for k in keys if any(c.equipment for c in nodes[k].conns)]
    if src:
        return sorted(src, key=size_key)[0]
    ends = []
    for k in keys:
        live = 0
        for c in nodes[k].conns:
            if _live_links(c, nodes, visited):
                live += 1
        if live <= 1:
            ends.append(k)
    if ends:
        return sorted(ends, key=size_key)[0]
    return sorted(keys, key=size_key)[0]


def start_inlet(node, nodes, visited):
    """The connector the run comes in through at the start element:
    joined to equipment, else an open end (no live link), biggest first,
    else the biggest connector."""
    if not node.conns:
        return None

    def biggest(cs):
        return sorted(cs, key=lambda c: (-c.area, c.cid))[0]

    eq = [c for c in node.conns if c.equipment]
    if eq:
        return biggest(eq).cid
    open_ends = [c for c in node.conns if not _live_links(c, nodes, visited)]
    if open_ends:
        return biggest(open_ends).cid
    return biggest(node.conns).cid


def order_children(node, inlet_cid, nodes, visited):
    """Neighbours to visit from node, in order: every branch first (nearest
    the inlet first), then the main - the biggest outlet, straightest on a
    tie. Returns [(neighbour_key, neighbour_cid)]."""
    inlet = node.conn(inlet_cid) if inlet_cid is not None else None
    outs = [c for c in node.conns
            if c.cid != inlet_cid and _live_links(c, nodes, visited)]
    if not outs:
        return []

    def straight(c):
        if inlet is None or inlet.direction is None or c.direction is None:
            return 0.0
        return -_dot(c.direction, inlet.direction)

    top = max([c.area for c in outs])
    sized = [c for c in outs if c.area >= top * (1.0 - AREA_TOL)]
    main = sorted(sized, key=lambda c: (-straight(c), c.cid))[0]
    branches = [c for c in outs if c is not main]

    def branch_key(c):
        d = 0.0
        if inlet is not None and inlet.origin is not None and c.origin is not None:
            d = _dist(inlet.origin, c.origin)
        return (round(d, 6), -straight(c), c.cid)

    branches.sort(key=branch_key)
    seq = []
    for c in branches + [main]:
        for link in sorted(_live_links(c, nodes, visited)):
            seq.append(link)
    return seq


def sequence_order(nodes, start_key=None, chain=False):
    """Walk every node once. Branches are numbered before the main carries
    on. A start picked part way along a run numbers forward first, then the
    run behind it. Separate pieces follow on, each from its own start - with
    chain, from the open end nearest where the last piece finished.
    Iterative - a long run never hits a recursion limit.
    Returns (order, pieces)."""
    order = []
    visited = set()
    pieces = 0
    first = True
    while len(visited) < len(nodes):
        remaining = [k for k in nodes if k not in visited]
        if first and start_key is not None and start_key in nodes:
            start = start_key
        elif chain and order:
            start = nearest_end(nodes, remaining, node_point(nodes[order[-1]]), visited)
            if start is None:
                start = choose_start(nodes, remaining)
        else:
            start = choose_start(nodes, remaining)
        first = False
        if start is None:
            break
        pieces += 1
        inlet = start_inlet(nodes[start], nodes, visited)
        stack = [(start, inlet, True)]
        while stack:
            key, in_cid, is_start = stack.pop()
            if key in visited:
                continue
            visited.add(key)
            order.append(key)
            node = nodes[key]
            kids = order_children(node, in_cid, nodes, visited)
            if is_start and in_cid is not None:
                back = node.conn(in_cid)
                if back is not None:
                    for link in sorted(_live_links(back, nodes, visited)):
                        kids.append(link)
            for nb_key, nb_cid in reversed(kids):
                if nb_key not in visited:
                    stack.append((nb_key, nb_cid, False))
    return order, pieces


# ============================================================
# Several systems in one sequence
# ============================================================

def node_point(node):
    """Mean of the node's connector origins, or None."""
    pts = [c.origin for c in node.conns if c.origin is not None]
    if not pts:
        return None
    n = float(len(pts))
    return (sum([p[0] for p in pts]) / n, sum([p[1] for p in pts]) / n,
            sum([p[2] for p in pts]) / n)


def components(nodes, keys=None):
    """Split keys into connected systems. Equipment never joins two systems
    together: it is added to the system on its biggest connected connector.
    Returns lists of keys, each sorted, ordered by smallest key."""
    keys = set(nodes if keys is None else keys)
    plain = [k for k in keys if not nodes[k].is_equipment]
    owner = {}
    comps = []
    for k in sorted(plain):
        if k in owner:
            continue
        comp = []
        queue = [k]
        owner[k] = len(comps)
        while queue:
            cur = queue.pop()
            comp.append(cur)
            for c in nodes[cur].conns:
                for nb, ncid in c.links:
                    if nb in keys and nb not in owner and not nodes[nb].is_equipment:
                        owner[nb] = len(comps)
                        queue.append(nb)
        comps.append(comp)
    for k in sorted([k for k in keys if nodes[k].is_equipment]):
        best = None
        for c in sorted(nodes[k].conns, key=lambda c: (-c.area, c.cid)):
            for nb, ncid in sorted(c.links):
                if nb in owner:
                    best = owner[nb]
                    break
            if best is not None:
                break
        if best is None:
            owner[k] = len(comps)
            comps.append([k])
        else:
            comps[best].append(k)
    comps = [sorted(c) for c in comps]
    comps.sort(key=lambda c: c[0])
    return comps


def system_order(nodes, keys, start=None):
    sub = dict((k, nodes[k]) for k in keys if k in nodes)
    if start not in sub:
        start = None
    return sequence_order(sub, start)[0]


def full_order(nodes, systems):
    """systems: [{keys, start}] in sequence order. Returns (order, spans)
    where spans[i] = (first index, end index) of system i in order."""
    order = []
    spans = []
    for sysd in systems:
        a = len(order)
        order.extend(system_order(nodes, sysd[u"keys"], sysd.get(u"start")))
        spans.append((a, len(order)))
    return order, spans


def _comp_distance(nodes, comp, point):
    best = None
    for k in comp:
        p = node_point(nodes[k])
        if p is None:
            continue
        d = _dist(p, point)
        if best is None or d < best:
            best = d
    return best if best is not None else 1e30


def order_systems(nodes, comps, starts=None, from_point=None):
    """Order new systems for the sequence: the one holding a picked start
    first, else the one nearest from_point (the end of the systems already
    listed), else the one the auto start rules pick across them all. Then
    each next system is the nearest to where the last one finished.
    starts: {key: True} picked start elements. Returns [(comp, start)]."""
    starts = starts or {}
    left = [list(c) for c in comps]
    out = []

    def start_in(comp):
        for k in comp:
            if k in starts:
                return k
        return None

    first = None
    for c in left:
        if start_in(c) is not None:
            first = c
            break
    if first is None and left and from_point is not None:
        first = sorted(left, key=lambda c: (_comp_distance(nodes, c, from_point), c[0]))[0]
    if first is None and left:
        all_keys = [k for c in left for k in c]
        pick = choose_start(dict((k, nodes[k]) for k in all_keys), all_keys)
        for c in left:
            if pick in c:
                first = c
                break
    while first is not None:
        left.remove(first)
        st = start_in(first)
        out.append((first, st))
        order = system_order(nodes, first, st)
        exit_point = node_point(nodes[order[-1]]) if order else None
        if not left:
            break
        if exit_point is None:
            first = left[0]
        else:
            first = sorted(left, key=lambda c: (_comp_distance(nodes, c, exit_point), c[0]))[0]
    return out


def system_name(keys, names, fallback):
    """Most common non-empty system name among the keys."""
    count = {}
    for k in keys:
        n = names.get(k) or u""
        if n:
            count[n] = count.get(n, 0) + 1
    if not count:
        return fallback
    return sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def system_ranges(plan, systems_keys):
    """First and last number text each system gets, or None if it gets none."""
    text = dict((k, t) for k, n, t in plan)
    out = []
    for keys in systems_keys:
        got = [text[k] for k in keys if k in text]
        out.append((got[0], got[-1]) if got else None)
    return out


# ============================================================
# System selector - every system in the active view
# ============================================================

# walk: numbered and selected. through: walked through so a damper never
# splits a run, but never numbered or selected. ends: shown when isolating.
KINDS = {
    u"duct": {
        u"label": u"Duct Systems",
        u"walk": [u"OST_DuctCurves", u"OST_DuctFitting", u"OST_FlexDuctCurves",
                  u"OST_PlaceHolderDucts", u"OST_FabricationDuctwork"],
        u"through": [u"OST_DuctAccessory"],
        u"ends": [u"OST_DuctTerminal"],
    },
    u"pipe": {
        u"label": u"Pipe Systems",
        u"walk": [u"OST_PipeCurves", u"OST_PipeFitting", u"OST_FlexPipeCurves",
                  u"OST_PlaceHolderPipes", u"OST_FabricationPipework"],
        u"through": [u"OST_PipeAccessory"],
        u"ends": [u"OST_PlumbingFixtures", u"OST_Sprinklers"],
    },
}


def assign_systems(nodes, labels):
    """labels {key: system key or None}. An element Revit gives no system
    (fabrication parts often) takes the system of the nearest labelled
    element it is joined to, breadth first. Whatever is still unlabelled
    forms one group per connected piece, keyed 'piece:<smallest key>'.
    Returns {key: system key} for every node."""
    out = {}
    for k in sorted(nodes):
        v = labels.get(k)
        if v:
            out[k] = v
    frontier = sorted(out)
    while frontier:
        nxt = []
        for k in frontier:
            for c in nodes[k].conns:
                for nb, ncid in sorted(c.links):
                    if nb in nodes and nb not in out:
                        out[nb] = out[k]
                        nxt.append(nb)
        frontier = sorted(nxt)
    for k in sorted(nodes):
        if k in out:
            continue
        key = u"piece:{0}".format(k)
        out[k] = key
        queue = [k]
        while queue:
            cur = queue.pop()
            for c in nodes[cur].conns:
                for nb, ncid in c.links:
                    if nb in nodes and nb not in out:
                        out[nb] = key
                        queue.append(nb)
    return out


def nearest_end(nodes, candidates, point, visited=None):
    """The open end (one live link or none) nearest the point, else the
    nearest element. None when there is no point or nothing to pick."""
    if point is None:
        return None
    visited = set(visited or ())
    keys = sorted([k for k in candidates if k in nodes and k not in visited])
    if not keys:
        return None
    ends = []
    for k in keys:
        live = 0
        for c in nodes[k].conns:
            if _live_links(c, nodes, visited):
                live += 1
        if live <= 1:
            ends.append(k)

    def dist(k):
        p = node_point(nodes[k])
        return (_dist(p, point) if p is not None else 1e30, k)

    return sorted(ends or keys, key=dist)[0]


def sel_include(key, passthrough, left_out, type_of, skipped):
    """Numbered in the system selector? Never an accessory, never an element
    left out by hand, never a family type unticked in the tree."""
    if key in passthrough or key in left_out:
        return False
    return type_of.get(key) not in skipped


def _walk_system(nodes, sysd, exit_point, include):
    """One system: its own picked start, else the open end nearest where the
    last system finished, else the auto start. Returns
    (order, start key, how, exit point after it)."""
    sub = dict((k, nodes[k]) for k in sysd[u"keys"] if k in nodes)
    st = sysd.get(u"start")
    how = u"picked"
    if st not in sub:
        st = None
        how = u"auto"
        if exit_point is not None and sub:
            st = nearest_end(sub, list(sub), exit_point)
            how = u"nearest"
    order = sequence_order(sub, st, chain=True)[0]
    last = None
    for k in reversed(order):
        if include is None or include(k):
            last = k
            break
    if last is None and order:
        last = order[-1]
    new_exit = exit_point
    if last is not None:
        p = node_point(nodes[last])
        if p is not None:
            new_exit = p
    return order, (order[0] if order else None), how, new_exit


def selector_order(nodes, systems, include=None):
    """systems: [{keys, start}] in the user's list order (ticked only).
    Each system after the first starts at its open end nearest where the
    previous one finished numbering. Returns (order, spans, starts) with
    starts [(start key, 'picked' | 'auto' | 'nearest')]."""
    order = []
    spans = []
    starts = []
    exit_point = None
    for sysd in systems:
        o, st, how, exit_point = _walk_system(nodes, sysd, exit_point, include)
        a = len(order)
        order.extend(o)
        spans.append((a, len(order)))
        starts.append((st, how))
    return order, spans, starts


def auto_order(nodes, systems, include=None):
    """Re-order: the system holding a picked start first (else the current
    first), then each next is the one nearest where the last one finished."""
    if len(systems) < 2:
        return list(systems)
    first = None
    for sysd in systems:
        if sysd.get(u"start") is not None:
            first = sysd
            break
    if first is None:
        first = systems[0]
    left = [sysd for sysd in systems if sysd is not first]
    out = [first]
    exit_point = _walk_system(nodes, first, None, include)[3]
    while left:
        if exit_point is None:
            nxt = left[0]
        else:
            nxt = sorted(left, key=lambda sd: (_comp_distance(nodes, sd[u"keys"], exit_point),
                                               left.index(sd)))[0]
        left.remove(nxt)
        out.append(nxt)
        exit_point = _walk_system(nodes, nxt, exit_point, include)[3]
    return out


def exit_after(nodes, systems, upto, include=None):
    """Where numbering finishes after systems[0..upto], each started the way
    selector_order starts it. None when nothing has a position."""
    exit_point = None
    for sd in systems[:upto + 1]:
        exit_point = _walk_system(nodes, sd, exit_point, include)[3]
    return exit_point


def next_nearest(nodes, systems, last_index, placed, include=None):
    """Auto next: of the systems not yet placed, the one whose start - its
    open end nearest the point - is closest to where systems[last_index]
    finishes numbering. systems: the ticked systems in list order.
    Returns (index in systems, distance) or None when nothing is left."""
    point = exit_after(nodes, systems, last_index, include)
    best = None
    for i, sd in enumerate(systems):
        if sd[u"key"] in placed:
            continue
        sub = dict((k, nodes[k]) for k in sd[u"keys"] if k in nodes)
        d = 1e30
        if point is not None and sub:
            k = nearest_end(sub, list(sub), point)
            p = node_point(nodes[k]) if k is not None else None
            if p is not None:
                d = _dist(p, point)
        if best is None or (d, i) < best:
            best = (d, i)
    return None if best is None else (best[1], best[0])


def move_item(items, src, dst):
    """Move items[src] so it lands at index dst. Returns (new list, dst)."""
    items = list(items)
    if not (0 <= src < len(items)):
        return items, src
    dst = max(0, min(len(items) - 1, dst))
    it = items.pop(src)
    items.insert(dst, it)
    return items, dst


def drop_index(src, target):
    """A row dragged onto target lands above it (the highlight is on its top
    edge). Moving down, removing the dragged row first shifts target by one."""
    return target - 1 if src < target else target


# ---------------------------------------------------- row selection and moves

def click_selection(selected, anchor, index, ctrl=False, shift=False):
    """List selection like Windows Explorer. selected: set of indexes.
    Plain click: just this row. Ctrl: toggle it. Shift: anchor to here
    (Ctrl+Shift adds the range). Returns (new set, new anchor)."""
    selected = set(selected or ())
    if shift and anchor is not None:
        lo, hi = min(anchor, index), max(anchor, index)
        rng = set(range(lo, hi + 1))
        return (selected | rng if ctrl else rng), anchor
    if ctrl:
        if index in selected and len(selected) > 1:
            selected.discard(index)
        else:
            selected.add(index)
        return selected, index
    return set([index]), index


def step_index(n, current, delta):
    """Up / Down through n rows, wrapping round at the ends."""
    if n <= 0:
        return None
    if current is None:
        return 0 if delta > 0 else n - 1
    return (current + delta) % n


def move_block(items, selected, delta):
    """Move every selected row one place up (-1) or down (+1); rows already
    at the end stay and the rest close up behind them.
    Returns (new list, new selected indexes)."""
    items = list(items)
    sel = set(i for i in selected if 0 <= i < len(items))
    order = sorted(sel) if delta < 0 else sorted(sel, reverse=True)
    for i in order:
        j = i + delta
        if 0 <= j < len(items) and j not in sel:
            items[i], items[j] = items[j], items[i]
            sel.discard(i)
            sel.add(j)
    return items, sel


def move_many(items, selected, insert_before):
    """Move the selected rows, keeping their order, so they sit just before
    the row that was at insert_before (len(items) = the end).
    Returns (new list, new selected indexes)."""
    items = list(items)
    sel = sorted(i for i in set(selected) if 0 <= i < len(items))
    moving = [items[i] for i in sel]
    keep = [it for i, it in enumerate(items) if i not in set(sel)]
    at = insert_before - len([i for i in sel if i < insert_before])
    at = max(0, min(len(keep), at))
    out = keep[:at] + moving + keep[at:]
    return out, set(range(at, at + len(moving)))


def split_gone(systems, left_out):
    """Systems whose every numberable element has been removed leave the list:
    the list shows only what is still in the view. Returns (kept, batch):
    batch is [(key of the row it followed or None, system)] in list order."""
    kept = []
    batch = []
    before = None
    for sd in systems:
        num = sd.get(u"num") or []
        if num and all([k in left_out for k in num]):
            batch.append((before, sd))
        else:
            kept.append(sd)
        before = sd[u"key"]
    return kept, batch


def bring_back(systems, batches):
    """Undo the drops newest batch first, each system going back straight
    after the row it followed (to the top if it was first, to the end if that
    row has gone for good) - so any mix of removals restores the order."""
    out = list(systems)
    for batch in reversed(batches):
        for after, sd in batch:
            if after is None:
                at = 0
            else:
                keys = [x[u"key"] for x in out]
                at = keys.index(after) + 1 if after in keys else len(out)
            out.insert(at, sd)
    return out


def position_of(items, index, counted, always=()):
    """The sequence number (#) of items[index]: rows before it and itself
    that count - ticked rows, plus any in always (the rows just moved)."""
    keep = [id(a) for a in always]
    return len([it for it in items[:index + 1] if counted(it) or id(it) in keep])


def move_to_position(items, selected, position, counted):
    """Move the selected rows as a block so the first of them becomes number
    position (1 = first). Numbers count only rows where counted(row) is true
    (ticked systems); the moved rows always count. Past the end means last.
    Returns (new list, new selected indexes, number of the last moved row)."""
    items = list(items)
    sel = sorted(set([i for i in selected if 0 <= i < len(items)]))
    if not sel:
        return items, set(), None
    moving = [items[i] for i in sel]
    rest = [it for i, it in enumerate(items) if i not in set(sel)]
    want = max(1, int(position)) - 1
    at = len(rest)
    n = 0
    for i, it in enumerate(rest):
        if n >= want:
            at = i
            break
        if counted(it):
            n += 1
    out = rest[:at] + moving + rest[at:]
    new = set(range(at, at + len(moving)))
    return out, new, position_of(out, at + len(moving) - 1, counted, moving)


def _passes(v, filters, excluded, skip_col=None):
    for col, text in (filters or {}).items():
        if col != skip_col and not matches(v.get(col) or u"", text):
            return False
    for col, values in (excluded or {}).items():
        if col != skip_col and (v.get(col) or u"") in values:
            return False
    return True


def view_rows(views, filters, sort_col, descending, only=None, excluded=None):
    """The views table: rows whose text contains each column's filter
    (case-insensitive, every word) and whose value is not unticked in that
    column's value list (excluded: {col: set of values}, blank = u""),
    optionally only the ids in only, sorted naturally by sort_col (blank
    values last), then by name."""
    out = []
    for v in views:
        if only is not None and v[u"id"] not in only:
            continue
        if _passes(v, filters, excluded):
            out.append(v)

    def key(v):
        val = v.get(sort_col) or u""
        return (val == u"", natural_key(val), natural_key(v.get(u"name") or u""))

    out.sort(key=key)
    if descending:
        blanks = [v for v in out if not (v.get(sort_col) or u"")]
        filled = [v for v in out if (v.get(sort_col) or u"")]
        out = filled[::-1] + blanks
    return out


def column_values(views, col, filters, excluded, only=None):
    """The value list for a column heading, Excel style: every value the
    column holds among the rows the OTHER columns let through, with a count,
    in natural order, blank last. Returns [(value, count)]."""
    counts = {}
    for v in views:
        if only is not None and v[u"id"] not in only:
            continue
        if not _passes(v, filters, excluded, skip_col=col):
            continue
        val = v.get(col) or u""
        counts[val] = counts.get(val, 0) + 1
    return sorted(counts.items(), key=lambda kv: (kv[0] == u"", natural_key(kv[0])))


def tick_values(excluded, values, on):
    """Select all / Clear all over the values shown (a search narrows them):
    on=True takes them out of the excluded set, on=False puts them in."""
    out = set(excluded or ())
    for val in values:
        if on:
            out.discard(val)
        else:
            out.add(val)
    return out


# the views offered in Tag in views: Revit view type -> what the Type column shows
TAG_VIEW_KINDS = {u"FloorPlan": u"Floor plan", u"Section": u"Section", u"ThreeD": u"3D"}
KIND_ORDER = [u"Floor plan", u"Section", u"3D"]


def kind_text(kind, locked=True):
    """The Type cell: an unlocked 3D view says so - it cannot take tags until locked."""
    return kind if kind != u"3D" or locked else u"3D (unlocked)"


NONE_MARK = u"<none>"


def default_group_param(names, saved, n):
    """View Group 1 / 2: the saved parameter, else the n-th (0 or 1) whose
    name mentions a group or discipline, else blank. A saved NONE_MARK means
    the user chose (none) - it stays blank."""
    if saved == NONE_MARK:
        return u""
    if saved and saved in names:
        return saved
    hits = [x for x in names if any([w in x.lower() for w in (u"group", u"discipline", u"series")])]
    return hits[n] if len(hits) > n else u""


def parse_position(text, lo, hi):
    """A typed position: a whole number from lo to hi, else None."""
    t = u"{0}".format(text or u"").strip().lstrip(u"#")
    if not t.isdigit():
        return None
    n = int(t)
    return n if lo <= n <= hi else None


def drop_before(target, below):
    """Dropped on row target: on its lower half it lands after it."""
    return target + 1 if below else target


def user_selection(event_ids, own_ids, sequence_keys):
    """Elements the user picked in Revit that are in the sequence - none when
    the selection is the one the tool itself just made."""
    ids = set(event_ids or ())
    if own_ids is not None and ids == set(own_ids):
        return []
    return sorted(ids & set(sequence_keys))


def start_keys(order, systems, starts):
    """Elements drawn in the start colour: the first element numbered, and
    every start picked by hand."""
    out = set()
    if order:
        out.add(order[0])
    for sd in systems:
        if sd.get(u"start") is not None:
            out.add(sd[u"start"])
    return out


def natural_key(text):
    """'SA 10' sorts after 'SA 9'."""
    out = []
    num = u""
    word = u""
    for ch in (text or u""):
        if ch.isdigit():
            if word:
                out.append((1, word.lower(), 0))
                word = u""
            num += ch
        else:
            if num:
                out.append((0, u"", int(num)))
                num = u""
            word += ch
    if word:
        out.append((1, word.lower(), 0))
    if num:
        out.append((0, u"", int(num)))
    return out


def _hsv_hex(h, s, v):
    i = int(h * 6.0) % 6
    f = h * 6.0 - int(h * 6.0)
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return u"#{0:02X}{1:02X}{2:02X}".format(int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))


def distinct_colours(n):
    """n colours, every one different: hues stepped by the golden angle,
    saturation and brightness alternating so neighbours never look alike.
    Mid tones, so they read on a dark or a light canvas alike."""
    out = []
    seen = set()
    i = 0
    while len(out) < n:
        h = (i * 0.618033988749895 + 0.07) % 1.0
        s = (0.80, 0.55, 0.95)[i % 3]
        v = (0.95, 0.75, 0.60)[(i // 3) % 3]
        c = _hsv_hex(h, s, v)
        if c not in seen and colour_distance(c, START_COLOUR) >= START_GAP:
            seen.add(c)
            out.append(c)
        i += 1
    return out


# the tool's colouring carries a 1% surface transparency - invisible, but it
# marks the override as the tool's, so a colouring left behind can be found
COLOUR_MARK = 1
_PALETTE = []


def rgb_hex(r, g, b):
    return u"#{0:02X}{1:02X}{2:02X}".format(int(r), int(g), int(b))


def tool_palette():
    """Every colour the tool has ever given a system (and the start): how a
    colouring left by a version before the mark is recognised."""
    if not _PALETTE:
        _PALETTE.append(frozenset(distinct_colours(1000) + [START_COLOUR]))
    return _PALETTE[0]


def is_tool_colouring(colours, transparency):
    """colours: (r, g, b) or None for projection line, cut line, surface
    pattern and cut pattern. The tool sets all four to one colour - with its
    mark, or (coloured before 1.9.1) from its palette."""
    if not colours or colours[0] is None or any([c != colours[0] for c in colours]):
        return False
    if transparency == COLOUR_MARK:
        return True
    return rgb_hex(*colours[0]) in tool_palette()


# the sequence start: a colour no system is given, drawn heavy
START_COLOUR = u"#FF00FF"
START_GAP = 110
START_WEIGHT = 12


def colour_distance(a, b):
    ra, ga, ba = hex_rgb(a)
    rb, gb, bb = hex_rgb(b)
    return ((ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2) ** 0.5


def hex_rgb(hex_text):
    t = (hex_text or u"#000000").lstrip(u"#")
    return int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)


def merge_systems(old, new):
    """After a refresh: keep the user's order, ticks, starts and colours for
    systems still there; new systems go on the end. Matched by system key."""
    by_key = dict((sd[u"key"], sd) for sd in new)
    out = []
    for sd in old:
        n = by_key.pop(sd[u"key"], None)
        if n is None:
            continue
        n[u"on"] = sd.get(u"on", True)
        n[u"colour"] = sd.get(u"colour", n.get(u"colour"))
        if sd.get(u"start") in n[u"keys"]:
            n[u"start"] = sd[u"start"]
        out.append(n)
    for sd in new:
        if sd[u"key"] in by_key:
            out.append(sd)
    return out


# ============================================================
# Category > family > type tree
# ============================================================

def type_key(cat, fam, typ):
    return u"{0}|{1}|{2}".format(cat, fam, typ)


def _lk(s):
    """Case-insensitive, with the original as a tie-break so order never
    depends on which element was read first."""
    return ((s or u"").lower(), s or u"")


def build_tree(rows):
    """rows: [(element_key, category, family, type)].
    Returns [ {name, families:[ {name, types:[ {name, key, ids} ]} ]} ]
    sorted by category, then family, then type, case-insensitive."""
    cats = {}
    for ek, cat, fam, typ in rows:
        cat = cat or u"(no category)"
        fam = fam or u"(no family)"
        typ = typ or u"(no type)"
        cats.setdefault(cat, {}).setdefault(fam, {}).setdefault(typ, []).append(ek)
    out = []
    for cat in sorted(cats, key=_lk):
        fams = []
        for fam in sorted(cats[cat], key=_lk):
            types = []
            for typ in sorted(cats[cat][fam], key=_lk):
                types.append({u"name": typ, u"key": type_key(cat, fam, typ),
                              u"ids": cats[cat][fam][typ]})
            fams.append({u"name": fam, u"types": types})
        out.append({u"name": cat, u"families": fams})
    return out


def tree_count(group):
    """Element count under a category or family dict."""
    if u"families" in group:
        return sum([tree_count(f) for f in group[u"families"]])
    if u"types" in group:
        return sum([len(t[u"ids"]) for t in group[u"types"]])
    return len(group.get(u"ids", []))


def group_state(type_keys, skipped):
    """True all included, False none, None mixed."""
    inc = [k for k in type_keys if k not in skipped]
    if len(inc) == len(type_keys):
        return True
    if not inc:
        return False
    return None


def matches(text, query):
    q = (query or u"").strip().lower()
    if not q:
        return True
    t = (text or u"").lower()
    for word in q.split():
        if word not in t:
            return False
    return True


# ============================================================
# Parameters and tags
# ============================================================

PARAM_PREFERENCE = [u"Item Number", u"BGL_Item Number", u"Mark",
                    u"BGL_Sequence Number", u"Comments"]


def param_list(storages, per_elem, keys):
    """[(name, storage, count)] over the given element keys, sorted by name."""
    count = {}
    for k in keys:
        for n in per_elem.get(k, ()):
            count[n] = count.get(n, 0) + 1
    out = [(n, storages.get(n, u"text"), count[n]) for n in count]
    out.sort(key=lambda r: (r[0].lower(), r[0]))
    return out


def filter_params(params, typed):
    """Names containing the typed text, case-insensitive. Blank keeps all.
    Names starting with it come first, then the rest, each alphabetical."""
    t = (typed or u"").strip().lower()
    if not t:
        return list(params)
    starts = [p for p in params if p[0].lower().startswith(t)]
    inside = [p for p in params if t in p[0].lower() and not p[0].lower().startswith(t)]
    return starts + inside


def exact_param(params, typed):
    t = (typed or u"").strip().lower()
    for p in params:
        if p[0].lower() == t:
            return p[0]
    return None


def default_parameter(names, saved):
    if saved and saved in names:
        return saved
    for p in PARAM_PREFERENCE:
        if p in names:
            return p
    return names[0] if names else u""


# tag category -> host categories it can tag (BuiltInCategory names)
TAG_HOSTS = {
    u"OST_DuctTags": [u"OST_DuctCurves"],
    u"OST_DuctFittingTags": [u"OST_DuctFitting"],
    u"OST_DuctAccessoryTags": [u"OST_DuctAccessory"],
    u"OST_DuctTerminalTags": [u"OST_DuctTerminal"],
    u"OST_FlexDuctTags": [u"OST_FlexDuctCurves"],
    u"OST_FabricationDuctworkTags": [u"OST_FabricationDuctwork"],
    u"OST_MechanicalEquipmentTags": [u"OST_MechanicalEquipment"],
    u"OST_PipeTags": [u"OST_PipeCurves", u"OST_PlaceHolderPipes"],
    u"OST_PipeFittingTags": [u"OST_PipeFitting"],
    u"OST_PipeAccessoryTags": [u"OST_PipeAccessory"],
    u"OST_FlexPipeTags": [u"OST_FlexPipeCurves"],
    u"OST_FabricationPipeworkTags": [u"OST_FabricationPipework"],
    u"OST_MultiCategoryTags": None,  # anything
}
TAG_HOSTS[u"OST_DuctTags"].append(u"OST_PlaceHolderDucts")

# which tab a tag type is offered on (None = both)
TAG_KIND = {
    u"OST_DuctTags": u"duct", u"OST_DuctFittingTags": u"duct", u"OST_DuctAccessoryTags": u"duct",
    u"OST_DuctTerminalTags": u"duct", u"OST_FlexDuctTags": u"duct",
    u"OST_FabricationDuctworkTags": u"duct", u"OST_MechanicalEquipmentTags": None,
    u"OST_PipeTags": u"pipe", u"OST_PipeFittingTags": u"pipe", u"OST_PipeAccessoryTags": u"pipe",
    u"OST_FlexPipeTags": u"pipe", u"OST_FabricationPipeworkTags": u"pipe",
    u"OST_MultiCategoryTags": None,
}


def tags_for_kind(tags, kind):
    """Tag choices worth offering for duct or pipe work."""
    return [t for t in tags if TAG_KIND.get(t[u"tag_cat"], None) in (None, kind)]


PLAN_VIEWS = (u"FloorPlan", u"CeilingPlan", u"EngineeringPlan", u"AreaPlan")
TAGGABLE_VIEWS = PLAN_VIEWS + (u"Section", u"Elevation", u"Detail")


def tag_view_ok(view_type, is_template=False, locked_3d=False, plans_only=False):
    """(ok, why) for placing tags in a view of this type."""
    if is_template:
        return False, u"The active view is a template"
    vt = u"{0}".format(view_type)
    if plans_only:
        if vt in PLAN_VIEWS:
            return True, u""
        return False, u"tags go on plan views only (the active view is {0})".format(vt)
    if vt in TAGGABLE_VIEWS:
        return True, u""
    if vt == u"ThreeD":
        if locked_3d:
            return True, u""
        return False, u"Lock the 3D view to tag in it"
    return False, u"The active view ({0}) cannot take tags".format(vt)


def tag_can_host(tag_cat, host_cat):
    if tag_cat not in TAG_HOSTS:
        return False
    hosts = TAG_HOSTS[tag_cat]
    if hosts is None:
        return True
    return host_cat in hosts


def tag_for_hosts(tags, chosen, host_cats):
    """Which tag each host category gets: the chosen tag where it can take
    that category, else the first loaded tag made for the category, else a
    multi-category tag, else None (nothing loaded can tag it).
    tags: every loaded tag choice. Returns {host category: tag or None}."""
    multi = None
    for t in tags:
        if t[u"tag_cat"] == u"OST_MultiCategoryTags":
            multi = t
            break
    out = {}
    for h in set(host_cats):
        if chosen is not None and tag_can_host(chosen[u"tag_cat"], h):
            out[h] = chosen
            continue
        own = None
        for t in tags:
            if t[u"tag_cat"] != u"OST_MultiCategoryTags" and tag_can_host(t[u"tag_cat"], h):
                own = t
                break
        out[h] = own or multi
    return out


def tag_plan_note(by_host, chosen, host_cats):
    """(taggable count, untaggable count, [(label, count)] of the other tags
    used where the chosen one cannot go)."""
    yes = 0
    no = 0
    others = {}
    for h in host_cats:
        t = by_host.get(h)
        if t is None:
            no += 1
            continue
        yes += 1
        if chosen is None or t is not chosen:
            others[t[u"label"]] = others.get(t[u"label"], 0) + 1
    return yes, no, sorted(others.items())


def skip_tagging(have, tag_type, untagged_only):
    """have: tag type ids already on the element in this view. Untagged only:
    any tag there means leave it; otherwise only the same tag again is left."""
    if untagged_only:
        return bool(have)
    return tag_type in have


def tag_coverage(tag_cat, plan_host_cats):
    """plan_host_cats: host category name per planned element.
    Returns (taggable, not_taggable)."""
    yes = 0
    no = 0
    for h in plan_host_cats:
        if tag_can_host(tag_cat, h):
            yes += 1
        else:
            no += 1
    return yes, no


# ============================================================
# Debug log
# ============================================================

class DebugLog(object):
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.lines = []

    def add(self, msg):
        if not self.enabled:
            return
        try:
            self.lines.append(u"{0}".format(msg))
        except Exception:
            pass
        if len(self.lines) > 20000:
            self.lines = self.lines[-15000:]

    def text(self):
        return u"\n".join(self.lines)

    def write(self, path=None):
        if not self.enabled:
            return False
        path = path or debug_path()
        try:
            folder = os.path.dirname(path)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
            data = self.text()
            try:
                data = data.encode("utf-8")
                mode = "wb"
            except Exception:
                mode = "w"
            with open(path, mode) as fh:
                fh.write(data)
            return True
        except Exception:
            return False


# ============================================================
# Isolate in 3D: which view is the default 3D view
# ============================================================

def default_3d_names(user):
    """Names Revit gives the Default 3D View, best first."""
    names = []
    if user:
        names.append(u"{3D - " + user + u"}")
    names.append(u"{3D}")
    return names


def pick_default_3d(view_names, wanted):
    """The default 3D view among view_names: an exact wanted name first, then
    any {3D...} view (another user's in a workshared model), else None."""
    have = set(view_names)
    for n in wanted:
        if n in have:
            return n
    others = sorted([n for n in view_names if n.startswith(u"{3D")], key=natural_key)
    return others[0] if others else None


def combo_3d_items(views, chosen):
    """Items for the 3D view picker: Default first, then each 3D view.
    Returns (items as (uid, label), index to select). A chosen view no
    longer in the model falls back to Default."""
    items = [(u"", u"Default 3D view")] + [(uid, name) for uid, name in views]
    idx = 0
    for i, it in enumerate(items):
        if chosen and it[0] == chosen:
            idx = i
    return items, idx


# ============================================================
# System groups (System Selector)
# ============================================================
# groups: {system key: group id}. A group always has two or more members and
# its members always sit together in the list, in their numbering order.

GROUP_BAND = 0.08          # hue gap (0..1 round the wheel) a lone system keeps from any group
MAGENTA_HUE = 300.0 / 360.0  # the start's colour - no group is given a hue near it
MAGENTA_GAP = 0.09


def hex_hue(hex_text):
    """Hue 0..1 of a colour, None for a grey."""
    r, g, b = [x / 255.0 for x in hex_rgb(hex_text)]
    mx = max(r, g, b)
    mn = min(r, g, b)
    if mx - mn < 1e-6:
        return None
    d = mx - mn
    if mx == r:
        h = ((g - b) / d) % 6.0
    elif mx == g:
        h = (b - r) / d + 2.0
    else:
        h = (r - g) / d + 4.0
    return (h / 6.0) % 1.0


def hue_gap(a, b):
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


def clean_groups(groups, keys):
    """Only systems still listed; a group left with one member is no group."""
    keys = set(keys)
    g = dict((k, v) for k, v in (groups or {}).items() if k in keys)
    counts = {}
    for v in g.values():
        counts[v] = counts.get(v, 0) + 1
    return dict((k, v) for k, v in g.items() if counts[v] >= 2)


def gather_groups(systems, groups):
    """Each group's members together, where its first member is, in their order."""
    out = []
    done = set()
    for sd in systems:
        gid = groups.get(sd[u"key"])
        if gid is None:
            out.append(sd)
        elif gid not in done:
            done.add(gid)
            out.extend([x for x in systems if groups.get(x[u"key"]) == gid])
    return out


def units(systems, groups):
    """The list as moving parts: each group one unit, each lone system one."""
    out = []
    for sd in gather_groups(systems, groups):
        gid = groups.get(sd[u"key"])
        if out and gid is not None and groups.get(out[-1][0][u"key"]) == gid:
            out[-1].append(sd)
        else:
            out.append([sd])
    return out


def make_group(systems, groups, keys, gid, keep=()):
    """Group these systems (two or more) as gid. They leave any group they
    were in and sit together where the first of them is, in list order.
    keep: keys off the list that still count (systems removed for now).
    Returns (systems, groups)."""
    keys = set(keys)
    g = dict((k, v) for k, v in (groups or {}).items() if k not in keys)
    for k in keys:
        g[k] = gid
    g = clean_groups(g, [sd[u"key"] for sd in systems] + list(keep))
    return gather_groups(systems, g), g


def ungroup(groups, keys, listed):
    """Break up every group any of these systems is in."""
    gone = set([groups.get(k) for k in keys if groups.get(k) is not None])
    g = dict((k, v) for k, v in (groups or {}).items() if v not in gone)
    return clean_groups(g, listed)


def tidy_groups(systems, groups, moved, keep=()):
    """After a drag or a move to a place (systems already in the new order).
    A moved block of lone systems or loose members dropped between two
    members of a group joins it; a block carrying a whole group is never
    merged - it goes on to just after that group instead. Moved members no
    longer next to the rest of their group leave it - the run keeping the
    most unmoved members stays the group. keep: keys off the list that
    still count. Returns (systems, groups)."""
    moved = set(moved)
    g = dict(groups or {})
    systems = list(systems)
    keys = [sd[u"key"] for sd in systems]
    n = len(keys)
    whole = set()
    for gid in set(g.values()):
        members = [k for k in keys if g.get(k) == gid]
        if members and all([k in moved for k in members]):
            whole.add(gid)
    i = 0
    while i < n:
        if keys[i] not in moved:
            i += 1
            continue
        j = i
        while j < n and keys[j] in moved:
            j += 1
        before = g.get(keys[i - 1]) if i > 0 else None
        after = g.get(keys[j]) if j < n else None
        if before is not None and before == after:
            if any([g.get(k) in whole for k in keys[i:j]]):
                # a whole group dropped inside another: after that group instead
                block = systems[i:j]
                rest = systems[:i] + systems[j:]
                end = max([x for x, sd in enumerate(rest) if g.get(sd[u"key"]) == before]) + 1
                systems = rest[:end] + block + rest[end:]
                keys = [sd[u"key"] for sd in systems]
                i = 0
                continue
            for k in keys[i:j]:
                g[k] = before
        i = j
    for gid in sorted(set(g.values()), key=lambda x: u"{0}".format(x)):
        runs = []
        prev = False
        for k in keys:
            inside = g.get(k) == gid
            if inside and prev:
                runs[-1].append(k)
            elif inside:
                runs.append([k])
            prev = inside
        if len(runs) > 1:
            scored = [(len([k for k in r if k not in moved]), -ri) for ri, r in enumerate(runs)]
            best = scored.index(max(scored))
            for ri, r in enumerate(runs):
                if ri != best:
                    for k in r:
                        g.pop(k, None)
    return systems, clean_groups(g, keys + list(keep))


def step_units(systems, groups, selected, delta, keep=()):
    """Shift+Up / Shift+Down with groups (selected: list indexes).
    Selected rows all inside one group, not the whole of it: they step
    inside the group, and a step past its end takes them out, just beyond
    it. Anything else: each selected row's whole group comes too, and every
    moving part steps over one whole neighbouring part - a lone system never
    falls into a group on its way past.
    Returns (systems, groups, selected indexes)."""
    systems = gather_groups(systems, groups)
    sel_keys = set([systems[i][u"key"] for i in selected if 0 <= i < len(systems)])
    if not sel_keys:
        return systems, dict(groups), set()
    gids = set([groups.get(k) for k in sel_keys])
    if len(gids) == 1 and None not in gids:
        gid = list(gids)[0]
        members = [sd[u"key"] for sd in systems if groups.get(sd[u"key"]) == gid]
        if len(sel_keys) < len(members):
            idx = [i for i, sd in enumerate(systems) if groups.get(sd[u"key"]) == gid]
            lo, hi = idx[0], idx[-1]
            sel_idx = set([i for i in idx if systems[i][u"key"] in sel_keys])
            edge = (min(sel_idx) == lo) if delta < 0 else (max(sel_idx) == hi)
            if not edge:
                out, new = move_block(systems, sel_idx, delta)
                return out, dict(groups), new
            # out of the group: just before it (Up) or just after it (Down)
            g = dict((k, v) for k, v in groups.items() if k not in sel_keys)
            moving = [sd for sd in systems if sd[u"key"] in sel_keys]
            rest = [sd for sd in systems if sd[u"key"] not in sel_keys]
            rest_idx = [i for i, sd in enumerate(rest) if g.get(sd[u"key"]) == gid]
            if rest_idx:
                at = rest_idx[0] if delta < 0 else rest_idx[-1] + 1
            else:
                at = lo if delta < 0 else lo + 1
            out = rest[:at] + moving + rest[at:]
            g = clean_groups(g, [sd[u"key"] for sd in out] + list(keep))
            return out, g, set(range(at, at + len(moving)))
    us = units(systems, groups)
    picked = set([ui for ui, u in enumerate(us) if any([sd[u"key"] in sel_keys for sd in u])])
    moved_units, new_units = move_block(us, picked, delta)
    out = [sd for u in moved_units for sd in u]
    new = set()
    at = 0
    for ui, u in enumerate(moved_units):
        if ui in new_units:
            new.update(range(at, at + len(u)))
        at += len(u)
    return out, dict(groups), new


def shade(hex_text, t):
    """The colour's hue from darkest (t=0) to lightest (t=1): deep, then
    full brightness, then pale."""
    h = hex_hue(hex_text) or 0.0
    t = max(0.0, min(1.0, t))
    if t <= 0.6:
        s, v = 0.95, 0.38 + 0.62 * (t / 0.6)
    else:
        s, v = 0.95 - 0.65 * ((t - 0.6) / 0.4), 1.0
    return _hsv_hex(h, s, v)


def group_shades(base, n):
    """n shades of one hue, darkest first."""
    if n <= 1:
        return [shade(base, 0.5)] * max(0, n)
    return [shade(base, i / float(n - 1)) for i in range(n)]


def system_colours(systems, groups, hues):
    """{system key: colour}: a lone system its own colour; a grouped one its
    group's hue, darkest first to lightest last in list order - so the shade
    shows the order and changes with it."""
    out = {}
    members = {}
    for sd in systems:
        gid = groups.get(sd[u"key"])
        if gid is None or gid not in hues:
            out[sd[u"key"]] = sd.get(u"colour")
        else:
            members.setdefault(gid, []).append(sd[u"key"])
    for gid, keys in members.items():
        for k, c in zip(keys, group_shades(hues[gid], len(keys))):
            out[k] = c
    return out


def far_hue(taken):
    """The hue (0..1) furthest round the wheel from every hue taken, never
    near the start's magenta."""
    best = None
    for i in range(72):
        h = i / 72.0
        if hue_gap(h, MAGENTA_HUE) < MAGENTA_GAP:
            continue
        gap = min([hue_gap(h, t) for t in taken]) if taken else 1.0
        if best is None or gap > best[0] + 1e-9:
            best = (gap, h)
    return best[1]


def colour_groups(systems, groups, hues):
    """Each group without a colour keeps its first member's hue when that is
    well clear of the other groups', else takes the hue furthest from them;
    then every lone system whose hue is within GROUP_BAND of a
    group's takes a fresh colour clear of all of them, so groups and lone
    systems never look alike. Returns (hues, {system key: new colour})."""
    live = set(groups.values())
    hues = dict((g, c) for g, c in (hues or {}).items() if g in live)
    for gid in sorted(live, key=lambda x: natural_key(u"{0}".format(x))):
        if gid not in hues:
            taken = [t for t in [hex_hue(c) for c in hues.values()] if t is not None]
            # keep the first member's own hue when it is well clear of the
            # other groups and the start's magenta, else the furthest free hue
            own = None
            for sd in systems:
                if groups.get(sd[u"key"]) == gid:
                    own = hex_hue(sd.get(u"colour")) if sd.get(u"colour") else None
                    break
            if own is not None and hue_gap(own, MAGENTA_HUE) >= MAGENTA_GAP and \
                    all([hue_gap(own, t) >= 2 * GROUP_BAND for t in taken]):
                h = own
            else:
                h = far_hue(taken)
            hues[gid] = _hsv_hex(h, 0.95, 0.80)
    group_h = [hex_hue(c) for c in hues.values()]

    def clash(c):
        h = hex_hue(c) if c else None
        return h is None or any([hue_gap(h, gh) < GROUP_BAND for gh in group_h])

    changed = {}
    need = [sd for sd in systems if group_h and groups.get(sd[u"key"]) is None and clash(sd.get(u"colour"))]
    if need:
        used = set([sd.get(u"colour") for sd in systems])
        pool = [c for c in distinct_colours(len(systems) * 4 + 50) if c not in used and not clash(c)]
        for sd in need:
            if pool:
                changed[sd[u"key"]] = pool.pop(0)
    return hues, changed


def _ticked(unit):
    return [sd for sd in unit if sd.get(u"on", True)]


def _near(nodes, sd, point):
    return _comp_distance(nodes, [k for k in sd[u"keys"] if k in nodes], point)


def auto_order_units(nodes, systems, groups, include=None):
    """Auto order with groups: a group moves as one, in its own order. The
    unit holding a picked start goes first (else the first), then each next
    is the unit whose first ticked system is nearest where the last unit
    finished numbering. Units with nothing ticked go to the end.
    Returns the whole list in the new order."""
    us = units(systems, groups)
    live = [u for u in us if _ticked(u)]
    dead = [u for u in us if not _ticked(u)]
    if len(live) < 2:
        return [sd for u in live + dead for sd in u]
    first = None
    for u in live:
        if any([sd.get(u"start") is not None for sd in _ticked(u)]):
            first = u
            break
    if first is None:
        first = live[0]
    left = [u for u in live if u is not first]
    out = [first]
    exit_point = None
    for sd in _ticked(first):
        exit_point = _walk_system(nodes, sd, exit_point, include)[3]
    while left:
        if exit_point is None:
            nxt = left[0]
        else:
            nxt = sorted(left, key=lambda u: (_near(nodes, _ticked(u)[0], exit_point),
                                              left.index(u)))[0]
        left.remove(nxt)
        out.append(nxt)
        for sd in _ticked(nxt):
            exit_point = _walk_system(nodes, sd, exit_point, include)[3]
    return [sd for u in out + dead for sd in u]


def reorder_group(nodes, systems, groups, gid, include=None):
    """Re-order one group nearest-next. Its first is the member with a picked
    start, else the one nearest where the systems before the group finish,
    else the current first; each next is the member nearest where the last
    finished. Unticked members go to the end of the group. Returns the list."""
    systems = gather_groups(systems, groups)
    idx = [i for i, sd in enumerate(systems) if groups.get(sd[u"key"]) == gid]
    if len(idx) < 2:
        return systems
    members = [systems[i] for i in idx]
    on = _ticked(members)
    off = [sd for sd in members if sd not in on]
    before = _ticked(systems[:idx[0]])
    entry = exit_after(nodes, before, len(before) - 1, include) if before else None
    new = []
    if on:
        first = None
        for sd in on:
            if sd.get(u"start") is not None:
                first = sd
                break
        if first is None and entry is not None:
            first = sorted(on, key=lambda sd: (_near(nodes, sd, entry), on.index(sd)))[0]
        if first is None:
            first = on[0]
        rest = [sd for sd in on if sd is not first]
        new = [first]
        exit_point = _walk_system(nodes, first, entry, include)[3]
        while rest:
            if exit_point is None:
                nxt = rest[0]
            else:
                nxt = sorted(rest, key=lambda sd: (_near(nodes, sd, exit_point), rest.index(sd)))[0]
            rest.remove(nxt)
            new.append(nxt)
            exit_point = _walk_system(nodes, nxt, exit_point, include)[3]
    return systems[:idx[0]] + new + off + systems[idx[-1] + 1:]


def group_label(groups, key, systems):
    """The Group cell: 'G2  1/3' - the group and the place in it."""
    gid = groups.get(key)
    if gid is None:
        return u""
    keys = [sd[u"key"] for sd in systems if groups.get(sd[u"key"]) == gid]
    return u"{0}  {1}/{2}".format(gid, keys.index(key) + 1, len(keys))


def next_group_id(groups, n):
    """A group id not in use: G1, G2 ... counting on from n. Returns (id, n)."""
    used = set(groups.values())
    while True:
        n += 1
        gid = u"G{0}".format(n)
        if gid not in used:
            return gid, n


# ============================================================
# Tag in views: sheets
# ============================================================

def sheet_rows(sheets, text):
    """Sheets whose number or name hold every word typed, in number order."""
    out = [sh for sh in sheets if matches(u"{0} {1}".format(sh[u"number"], sh[u"name"]), text)]
    out.sort(key=lambda sh: (natural_key(sh[u"number"]), natural_key(sh[u"name"])))
    return out


def sheet_views(sheets, uids):
    """View id values on the sheets chosen (only those Tag in views lists)."""
    out = set()
    for sh in sheets:
        if sh[u"uid"] in uids:
            out.update(sh[u"views"])
    return out


def sheet_state(sheet, ticked_ids):
    """The sheet's tick box: True every listed view on it ticked, False none
    (or it holds none), None some."""
    views = sheet[u"views"]
    n = len([v for v in views if v in ticked_ids])
    if not views or n == 0:
        return False
    return True if n == len(views) else None


def open_list(sheets, ticked_ids):
    """After a run that tagged in ticked views: what to open. A sheet whose
    every listed view is ticked opens as the sheet; the other ticked views
    open on their own. Returns (sheets, view id values)."""
    full = [sh for sh in sheets if sheet_state(sh, ticked_ids) is True]
    on_sheets = set([v for sh in full for v in sh[u"views"]])
    full.sort(key=lambda sh: (natural_key(sh[u"number"]), natural_key(sh[u"name"])))
    return full, sorted([v for v in ticked_ids if v not in on_sheets])
