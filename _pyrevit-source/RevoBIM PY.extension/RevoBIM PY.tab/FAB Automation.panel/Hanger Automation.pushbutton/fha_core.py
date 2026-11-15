# -*- coding: utf-8 -*-
u"""Hanger Automation - pure logic.

No .NET, no Revit: everything here runs under plain CPython so bench_logic.py
can prove it.  Lengths are decimal feet unless a name ends in _mm.
"""
import os
import io
import math
import re

__version__ = u'1.15.0'
TOOL_NAME = u'Hanger Automation'
MM = 304.8
SETTINGS_VERSION = 3

# ---------------------------------------------------------------- settings
DEFAULTS = {
    u'settings_version': u'3',
    u'theme': u'auto',
    u'debug': u'1',
    u'button': u'',
    u'spacing': u'2000',
    u'start_off': u'300',
    u'end_off': u'300',
    u'takeoff_max': u'600',
    u'takeoff_clear': u'400',
    u'min_gap': u'500',
    u'edge': u'100',
    u'skip_existing': u'1',
    u'existing_clear': u'300',
    u'ext_floors': u'1',
    u'ext_framing': u'1',
    u'ext_roofs': u'0',
    u'extend_after': u'1',
    u'extend_place': u'1',
    u'match_size': u'1',
    u'rehost_replace': u'1',
    u'replace_free': u'0',
    u'search_radius': u'1500',
    u'dims': u'1',
    u'dim_type': u'',
    u'dim_offset': u'800',
    u'scope': u'run',
    u'active_tab': u'fab',
    u'workset': u'',
    # ---- Family Hangers tab
    u'fam_category': u'all',
    u'fam_symbol': u'',
    u'fam_search': u'',
    u'fam_rod_place': u'0',
    u'fam_rod_realign': u'0',
    u'fam_rod_auto': u'0',
    u'fam_spacing': u'3000',
    u'fam_dw144': u'1',
    u'fam_start_off': u'300',
    u'fam_end_off': u'300',
    u'fam_flange_clear': u'150',
    u'fam_takeoff_clear': u'400',
    u'fam_accessory': u'1',
    u'fam_skip_existing': u'1',
    u'fam_dims': u'0',
    u'fam_dim_offset': u'800',
    u'fam_ins_place': u'1',
    u'fam_ins_realign': u'1',
    u'fam_ins_auto': u'1',
    u'fam_dim_type': u'',
    u'fam_rod_linked': u'0',
    u'fam_lock_place': u'1',
    u'fam_lock_realign': u'1',
    u'fam_lock_auto': u'1',
    u'fam_group_z': u'50',
    u'fam_group_gap': u'500',
    u'fam_group_angle': u'2',
    u'fam_group_centre': u'mean',
    u'fam_workset': u'',
    u'fam_list_h': u'92',
    u'fam_set_only': u'0',     # list only the families already set up in Family settings      # height of the family list (dragged by its grip)
}

# ---- Family Floor Support tab: its own copy of every Family Hangers setting
# except the drop rod ones; the grouping rules (fam_group_*) are shared.
FLOOR_SKIP = (u'fam_rod_place', u'fam_rod_realign', u'fam_rod_auto', u'fam_rod_linked',
              u'fam_group_z', u'fam_group_gap', u'fam_group_angle', u'fam_group_centre')
for _k in list(DEFAULTS):
    if _k.startswith(u'fam_') and _k not in FLOOR_SKIP:
        DEFAULTS[u'flr_' + _k[4:]] = DEFAULTS[_k]


# floor-only: what floor supports stand on
DEFAULTS[u'flr_base'] = u'level'          # level | element (a picked floor / roof / equipment)
DEFAULTS[u'flr_base_linked'] = u'0'       # 1 = go straight to picking inside a link
BASES = [(u'level', u'The service\'s level'),
         (u'element', u'A floor, roof or equipment I pick (here or in a link)')]


def floor_key(key):
    u"""The Floor Support tab's key for a Family Hangers key (fam_x -> flr_x);
    shared keys (grouping rules) stay as they are."""
    if key.startswith(u'fam_') and key not in FLOOR_SKIP:
        return u'flr_' + key[4:]
    return key


# ---------------------------------------------------------------- worksets
# The workset choice on each tab: a workset name, or one of these.
WS_LEAVE = u''              # as before: new hangers on the service's workset, edited ones left alone
WS_SERVICE = u'*service*'   # new and edited hangers on their service's workset
WS_ACTIVE = u'*active*'     # new and edited hangers on the active workset
WS_OPTIONS = [(WS_LEAVE, u'Leave as is (new hangers: the service\'s workset)'),
              (WS_SERVICE, u'Same as the service (new and edited)'),
              (WS_ACTIVE, u'Active workset (new and edited)')]


def workset_items(names, value):
    u"""(labels, selected index, values) for a workset combo.  A saved name that
    is no longer in the model is kept, marked, so it is not lost silently."""
    values = [v for v, _l in WS_OPTIONS] + list(names)
    labels = [l for _v, l in WS_OPTIONS] + list(names)
    if value and value not in values:
        values.append(value)
        labels.append(u'{0} (not in this model)'.format(value))
    return labels, (values.index(value) if value in values else 0), values


def workset_value(values, index):
    try:
        i = int(index)
    except Exception:
        return WS_LEAVE
    return values[i] if 0 <= i < len(values) else WS_LEAVE


def workset_target(choice, service_ws, active_ws, named, new):
    u"""Which workset id an element goes on, or None to leave it.

    choice: the tab's setting; service_ws: the workset of the service it
    serves (None if unknown); active_ws: the active workset; named: the id of
    the chosen workset name (None if not found); new: a newly placed hanger
    (True) or an existing one a tool edited (False).
    """
    if choice == WS_LEAVE:
        return service_ws if new else None
    if choice == WS_SERVICE:
        return service_ws
    if choice == WS_ACTIVE:
        return active_ws
    return named if named is not None else (service_ws if new else None)


# settings version -> keys whose meaning changed and must be reset
MIGRATIONS = {}


def settings_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'RevoBIM')


def settings_path():
    return os.path.join(settings_dir(), 'hanger_automation.txt')


def legacy_settings_path():
    u"""Before 1.1.0 the tool was Fab Hangar Automation."""
    return os.path.join(settings_dir(), 'fab_hangar_automation.txt')


def debug_path():
    return os.path.join(settings_dir(), 'hanger_automation_debug.txt')


def load_error_path():
    return os.path.join(settings_dir(), 'hanger_automation_load_error.txt')


def parse_settings(text):
    out = {}
    for raw in (text or u'').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        out[k.strip()] = v.strip()
    return out


def _to_int(v, default=0):
    try:
        return int(float(v))
    except Exception:
        return default


def load_settings(path=None):
    d = dict(DEFAULTS)
    p = path or settings_path()
    if path is None and not os.path.exists(p) and os.path.exists(legacy_settings_path()):
        p = legacy_settings_path()
    try:
        if os.path.exists(p):
            with io.open(p, 'r', encoding='utf-8') as fh:
                saved = parse_settings(fh.read())
            ver = _to_int(saved.get(u'settings_version'), 0)
            for k, v in saved.items():
                if k in DEFAULTS:
                    d[k] = v
            for n in range(ver + 1, SETTINGS_VERSION + 1):
                for k in MIGRATIONS.get(n, []):
                    d[k] = DEFAULTS[k]
    except Exception:
        d = dict(DEFAULTS)
    d[u'settings_version'] = u'{0}'.format(SETTINGS_VERSION)
    return d


def save_settings(d, path=None):
    p = path or settings_path()
    try:
        folder = os.path.dirname(p)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        lines = []
        for k in sorted(DEFAULTS):
            lines.append(u'{0}={1}'.format(k, d.get(k, DEFAULTS[k])))
        with io.open(p, 'w', encoding='utf-8') as fh:
            fh.write(u'\n'.join(lines) + u'\n')
        return True
    except Exception:
        return False


def as_float(d, key, default):
    try:
        return float(d.get(key, DEFAULTS.get(key)))
    except Exception:
        return default


def as_bool(d, key):
    return str(d.get(key, DEFAULTS.get(key, u'0'))).strip() in ('1', 'true', 'True', 'yes')


def parse_mm(text, default):
    u"""Millimetres typed in a box -> float, or the default if unreadable."""
    try:
        v = float(str(text).strip().replace(',', '.'))
        if v != v or v < 0:
            return default
        return v
    except Exception:
        return default


def plan_config(d):
    u"""Settings dict -> the numbers plan_stations needs (all mm)."""
    return {
        'spacing': max(100.0, as_float(d, u'spacing', 2000.0)),
        'start_off': as_float(d, u'start_off', 300.0),
        'end_off': as_float(d, u'end_off', 300.0),
        'takeoff_max': as_float(d, u'takeoff_max', 600.0),
        'takeoff_clear': as_float(d, u'takeoff_clear', 400.0),
        'min_gap': as_float(d, u'min_gap', 500.0),
        'edge': as_float(d, u'edge', 100.0),
    }


# ------------------------------------------------------------------ theme
PALETTES = {
    u'dark': {   # Revit's own dark theme (RevoBIM theme reference), accents lifted to 4.5:1 on it
        u'WinBg': u'#3C4454', u'Card': u'#323C48', u'Field': u'#2D3441',
        u'Bar': u'#222933', u'Edge': u'#4D5666', u'EdgeStrong': u'#515C6B',
        u'Text': u'#EEF0F4', u'Muted': u'#ABB3BF', u'Blue': u'#72BAF0',
        u'BlueHover': u'#8CC8F4', u'Orange': u'#F2A452',
        u'OrangeHover': u'#F5B56E', u'Green': u'#3FA75A',
        u'GreenHover': u'#4EC06D', u'Red': u'#D9534F', u'Sel': u'#3A7392',
        u'HoverBg': u'#444E5E', u'Disabled': u'#6B7484', u'OnAccent': u'#1B1F24',
        u'SetText': u'#7FD99A',   # families already set up (a green that reads on the dark field)
    },
    u'light': {
        u'WinBg': u'#F3F3F5', u'Card': u'#FFFFFF', u'Field': u'#FFFFFF',
        u'Bar': u'#E6E6EA', u'Edge': u'#D0D0D6', u'EdgeStrong': u'#B8B8C0',
        u'Text': u'#1F1F23', u'Muted': u'#66666E', u'Blue': u'#1B72BE',
        u'BlueHover': u'#2A86D6', u'Orange': u'#B96A12',
        u'OrangeHover': u'#D07C1E', u'Green': u'#2E8546',
        u'GreenHover': u'#3A9A55', u'Red': u'#C03B36', u'Sel': u'#CFE3F5',
        u'HoverBg': u'#E0E0E6', u'Disabled': u'#A8A8B0', u'OnAccent': u'#FFFFFF',
        u'SetText': u'#17602C',   # families already set up: dark green
    },
}
THEME_MODES = [u'auto', u'dark', u'light']


def service_comment(labels):
    u"""The hanger's Comments from the 'Family : Type' of each service on it:
    in the order met, joined with ', ', repeats counted - '2xCable Tray : Ladder'."""
    order, count = [], {}
    for lb in labels:
        lb = (lb or u'').strip()
        if not lb:
            continue
        if lb not in count:
            order.append(lb)
            count[lb] = 0
        count[lb] += 1
    return u', '.join((u'{0}x{1}'.format(count[lb], lb) if count[lb] > 1 else lb) for lb in order)


def contrast(fg, bg):
    u"""WCAG contrast ratio of two #RRGGBB colours."""
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    a, b = sorted([lum(fg), lum(bg)], reverse=True)
    return (a + 0.05) / (b + 0.05)


# ------------------------------------------------------------------ drawer
def shrunk_top(wa_top, wa_h, bar_h, slot=0, gap=8.0):
    u"""Top of a parked title bar: `gap` above the bottom of the working area,
    stacked upward by slot (a dialog parks above the window it belongs to).
    Works for a monitor above the primary, whose working area top is negative."""
    return max(wa_top, wa_top + wa_h - (slot + 1) * (bar_h + gap))


def expand_top(saved_top, landed_top, here_top, bar_h, full_h, wa_top, wa_h):
    u"""Where a parked window opens to: back where it was if the bar has not
    been moved; otherwise growing upward from wherever the bar now sits.
    Always kept on the screen."""
    if landed_top is not None and abs(here_top - landed_top) < 1.0:
        top = saved_top
    else:
        top = here_top + bar_h - full_h
    return min(max(wa_top, top), max(wa_top, wa_top + wa_h - full_h))


# ------------------------------------------------------------- dim views
PLAN_VIEW_TYPES = (u'FloorPlan', u'CeilingPlan', u'EngineeringPlan', u'AreaPlan')
VIEW_KIND_LABELS = {u'FloorPlan': u'Floor plan', u'CeilingPlan': u'Ceiling plan', u'EngineeringPlan': u'Structural plan',
                    u'AreaPlan': u'Area plan', u'Section': u'Section', u'Elevation': u'Elevation', u'Detail': u'Detail'}
VIEW_KINDS = [(u'floor', u'Floor plans'), (u'plan', u'All plans'), (u'section', u'Sections and elevations'),
              (u'all', u'All plans and sections')]


def natural_key(text):
    u"""M-A9 before M-A10: numbers compare as numbers."""
    out = []
    for part in re.split(r'(\d+)', u'{0}'.format(text or u'').lower()):
        out.append((0, int(part), u'') if part.isdigit() else (1, 0, part))
    return out


def view_row_text(r):
    return u'{0}   |   {1}   |   1:{2}'.format(r['name'], VIEW_KIND_LABELS.get(r['type'], r['type']), r.get('scale', u'?'))


def sheet_row_text(r):
    return u'{0} - {1}   ({2} plan / section view{3})'.format(r['number'], r['name'], len(r['views']),
                                                            u'' if len(r['views']) == 1 else u's')


def filter_view_rows(rows, query, kind=u'all'):
    out = []
    for r in rows:
        if kind == u'floor' and r['type'] != u'FloorPlan':
            continue
        if kind == u'plan' and r['type'] not in PLAN_VIEW_TYPES:
            continue
        if kind == u'section' and r['type'] in PLAN_VIEW_TYPES:
            continue
        if match_words(view_row_text(r), query):
            out.append(r)
    return out


def filter_sheet_rows(rows, query):
    return [r for r in rows if match_words(u'{0} {1}'.format(r['number'], r['name']), query)]


def chosen_views(view_keys, sheet_keys, sheets):
    u"""Every view key to dimension in: the ticked views plus each view on a
    ticked sheet, each once, in order."""
    out, seen = [], set()
    by_sheet = dict((r['key'], r['views']) for r in sheets)
    for k in list(view_keys) + [v for sk in sheet_keys for v in by_sheet.get(sk, [])]:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


# ------------------------------------------------------------------ search
def match_words(text, query):
    u"""The house search: every word of the query, in any order, any case."""
    t = u'{0}'.format(text or u'').lower()
    return all(w in t for w in u'{0}'.format(query or u'').lower().split())


def next_mode(mode):
    try:
        return THEME_MODES[(THEME_MODES.index(mode) + 1) % len(THEME_MODES)]
    except ValueError:
        return u'auto'


def resolve_theme(mode, canvas_is_dark):
    u"""auto follows Revit's canvas; an unreadable canvas falls back to dark."""
    if mode in (u'dark', u'light'):
        return mode
    if canvas_is_dark is None:
        return u'dark'
    return u'dark' if canvas_is_dark else u'light'


# ---------------------------------------------------------------- vectors
def vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vadd(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vscale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vlen(a):
    return math.sqrt(vdot(a, a))


def vnorm(a):
    n = vlen(a)
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def closest_on_segment(p, a, b):
    u"""(t, point, distance) of p on segment a-b, t clamped to 0..1."""
    ab = vsub(b, a)
    den = vdot(ab, ab)
    if den < 1e-12:
        return 0.0, a, vlen(vsub(p, a))
    t = vdot(vsub(p, a), ab) / den
    t = max(0.0, min(1.0, t))
    q = vadd(a, vscale(ab, t))
    return t, q, vlen(vsub(p, q))


# -------------------------------------------------------------- rehosting
def nearest_host(p, hosts, max_dist_ft, margin_ft):
    u"""Nearest horizontal straight to point p.

    hosts: dicts with id, a, b (connector 0 / connector 1 origins), horizontal.
    Returns {host, dist, d, t}: dist is the distance from connector 0, clamped
    so the hanger is never asked to sit on the very end of the straight.
    """
    best = None
    for h in hosts:
        if not h.get('horizontal', True):
            continue
        t, q, d = closest_on_segment(p, h['a'], h['b'])
        if d > max_dist_ft:
            continue
        key = (round(d, 6), h['id'])
        if best is None or key < best[0]:
            best = (key, h, t, d)
    if best is None:
        return None
    h, t, d = best[1], best[2], best[3]
    length = vlen(vsub(h['b'], h['a']))
    if length > 2.0 * margin_ft:
        dist = max(margin_ft, min(length - margin_ft, t * length))
    else:
        dist = length / 2.0
    return {'host': h, 'dist': dist, 'd': d, 't': t}


# ------------------------------------------------------------ run / spans
TAKEOFF = ('tap', 'tee_branch')
_PRIORITY = {'bend': 0, 'accessory': 0, 'vertical': 1, 'tee_main': 2, 'open': 3, 'other': 3,
             'loop': 3, 'tap': 4, 'tee_branch': 4}


def _walk_dir(parts, pid, exit_idx, visited):
    u"""Walk away from part pid through connector exit_idx.

    Returns (items, end).  Straights and in-line parts are walked through;
    anything else ends the span and says what kind of end it is.
    """
    items = []
    cur = pid
    ex = exit_idx
    while True:
        conns = parts[cur]['conns']
        if ex is None or ex >= len(conns):
            return items, {'type': 'open', 'id': None}
        c = conns[ex]
        nid = c.get('to')
        if nid is None or nid not in parts:
            return items, {'type': 'open', 'id': None}
        n = parts[nid]
        nin = c.get('to_conn')
        kind = n['kind']
        if kind in ('straight', 'inline'):
            if kind == 'straight' and not n.get('horizontal', True):
                return items, {'type': 'vertical', 'id': nid}
            if nid in visited or nin is None or len(n['conns']) != 2:
                return items, {'type': 'loop' if nid in visited else 'other', 'id': nid}
            nxt = 1 - nin
            items.append({'id': nid, 'kind': kind, 'len': n['len'],
                          'entry': nin, 'exit': nxt})
            visited.add(nid)
            cur = nid
            ex = nxt
            continue
        if kind == 'bend':
            return items, {'type': 'bend', 'id': nid}
        if kind == 'accessory':
            return items, {'type': 'accessory', 'id': nid}
        if kind == 'tee':
            role = None
            if nin is not None and nin < len(n['conns']):
                role = n['conns'][nin].get('role')
            return items, {'type': 'tee_branch' if role == 'branch' else 'tee_main', 'id': nid}
        if kind == 'tap':
            return items, {'type': 'tap', 'id': nid}
        return items, {'type': 'other', 'id': nid}


def _reverse_span(span):
    chain = []
    for it in reversed(span['chain']):
        chain.append({'id': it['id'], 'kind': it['kind'], 'len': it['len'],
                      'entry': it['exit'], 'exit': it['entry']})
    return {'chain': chain, 'start_end': span['end_end'], 'end_end': span['start_end']}


def orient_span(span):
    u"""Start the span at the end a run 'begins' from: after a bend first."""
    ps = _PRIORITY.get(span['start_end']['type'], 3)
    pe = _PRIORITY.get(span['end_end']['type'], 3)
    if pe < ps:
        return _reverse_span(span)
    if pe == ps and span['chain'][0]['id'] > span['chain'][-1]['id']:
        return _reverse_span(span)
    return span


def span_length(span):
    return sum(it['len'] for it in span['chain'])


def build_spans(parts):
    u"""Group horizontal straights into spans.

    parts: id -> {kind, len, horizontal, conns:[{to, to_conn, role}]} where kind
    is straight / inline / bend / tee / tap / other.  A span is a maximal chain
    of straights joined directly or through in-line parts; bends, tees, taps,
    vertical drops and open ends finish it.
    """
    visited = set()
    spans = []
    for pid in sorted(parts):
        p = parts[pid]
        if p['kind'] != 'straight' or not p.get('horizontal', True):
            continue
        if pid in visited or len(p['conns']) != 2:
            continue
        visited.add(pid)
        fwd, fend = _walk_dir(parts, pid, 1, visited)
        bwd, bend_ = _walk_dir(parts, pid, 0, visited)
        chain = []
        for it in reversed(bwd):
            chain.append({'id': it['id'], 'kind': it['kind'], 'len': it['len'],
                          'entry': it['exit'], 'exit': it['entry']})
        chain.append({'id': pid, 'kind': 'straight', 'len': p['len'],
                      'entry': 0, 'exit': 1})
        chain.extend(fwd)
        span = {'chain': chain, 'start_end': bend_, 'end_end': fend}
        spans.append(orient_span(span))
    return spans


# ---------------------------------------------------------------- stations
def plan_stations(length_ft, start_type, end_type, cfg):
    u"""Hanger stations (feet from the span start) for one span.

    - the first hanger sits start_off from the start, or takeoff_clear if the
      span starts at a takeoff (tap / tee branch) so nothing lands on the takeoff
    - then one every spacing
    - a span finishing at a bend or set down gets a hanger end_off before it;
      spacing is allowed to shrink to fit it in
    - a short span that starts or ends at a takeoff is a takeoff stub: no hangers
    """
    L = length_ft * MM
    S = cfg['spacing']
    a = cfg['start_off']
    b = cfg['end_off']
    tk = cfg['takeoff_clear']
    mg = cfg['min_gap']
    edge = cfg.get('edge', 100.0)
    if L < 2.0 * edge:
        return []
    has_takeoff = start_type in TAKEOFF or end_type in TAKEOFF
    if has_takeoff and L <= cfg['takeoff_max']:
        return []
    first = tk if start_type in TAKEOFF else a
    end_required = end_type in ('bend', 'vertical', 'accessory')
    if end_required:
        last = L - b
    elif end_type in TAKEOFF:
        last = L - tk
    elif end_type == 'tee_main':
        last = L - a
    else:
        last = L - edge
    if first > last:
        return [L / 2.0 / MM]
    if last - first < mg:
        return [((first + last) / 2.0) / MM] if end_required else [first / MM]
    stations = [first]
    p = first
    if end_required:
        while p + S < last - mg:
            p += S
            stations.append(p)
        gap = last - p
        if gap > S + 1e-6:
            n = int(math.ceil(gap / S - 1e-9))
            step = gap / n
            for i in range(1, n):
                stations.append(p + step * i)
        stations.append(last)
    else:
        while p + S <= last + 1e-6:
            p += S
            stations.append(p)
    return [s / MM for s in stations]


def locate(chain, station_ft, margin_ft):
    u"""Station along a span -> (straight id, entry connector, distance, station).

    A station that falls inside an in-line part (reducer, damper) or too close
    to a joint is moved to the nearest spot a hanger can actually sit.
    """
    pos = 0.0
    spans = []
    for it in chain:
        if it['kind'] == 'straight' and it['len'] > 2.0 * margin_ft:
            spans.append((pos + margin_ft, pos + it['len'] - margin_ft, pos, it))
        pos += it['len']
    if not spans:
        return None
    best = None
    for lo, hi, start, it in spans:
        if station_ft < lo:
            d = lo - station_ft
            s = lo
        elif station_ft > hi:
            d = station_ft - hi
            s = hi
        else:
            d = 0.0
            s = station_ft
        key = (round(d, 9), start)
        if best is None or key < best[0]:
            best = (key, it, start, s)
    it, start, s = best[1], best[2], best[3]
    return {'id': it['id'], 'entry': it['entry'], 'dist': s - start, 'station': s}


def dedupe(stations, min_sep_ft):
    out = []
    for s in sorted(stations):
        if not out or s - out[-1] >= min_sep_ft:
            out.append(s)
    return out


def drop_near(stations, existing, clear_ft):
    u"""Remove stations within clear_ft of a hanger that is already there."""
    return [s for s in stations if all(abs(s - e) > clear_ft for e in existing)]


# ------------------------------------------------------------- dimensions
def choose_normal(direction):
    u"""Side of the run the dimension string goes on: toward -Y (below the run
    on screen), else +X for a run that runs along Y."""
    n = (direction[1], -direction[0], 0.0)
    n = vnorm(n)
    if abs(n[1]) > 1e-6:
        if n[1] > 0:
            n = vscale(n, -1.0)
    elif n[0] < 0:
        n = vscale(n, -1.0)
    return n


def dim_line(p_start, p_end, offset_mm, over_mm=300.0):
    u"""Dimension line for a span: parallel to it, offset to the chosen side and
    run a little past both ends.  Returns (p0, p1, normal)."""
    d = vnorm(vsub(p_end, p_start))
    n = choose_normal(d)
    off = vscale(n, offset_mm / MM)
    ext = over_mm / MM
    p0 = vadd(vadd(p_start, off), vscale(d, -ext))
    p1 = vadd(vadd(p_end, off), vscale(d, ext))
    return p0, p1, n


def dim_line_in_view(p_start, p_end, offset_mm, up, normal, origin, over_mm=300.0):
    u"""Dimension line for a run seen in a section / elevation: offset DOWN the
    view (below the run) and lying in the view's plane (through origin, normal
    the view direction) so Revit can draw it.  Returns (p0, p1)."""
    d = vnorm(vsub(p_end, p_start))
    off = vscale(vnorm(up), -offset_mm / MM)
    ext = over_mm / MM
    n = vnorm(normal)

    def onto(p):
        return vsub(p, vscale(n, vdot(vsub(p, origin), n)))
    return (onto(vadd(vadd(p_start, off), vscale(d, -ext))),
            onto(vadd(vadd(p_end, off), vscale(d, ext))))


def collapse_refs(items, tol_ft):
    u"""items: (t, ref) sorted by t.  Refs closer than tol_ft keep the first."""
    out = []
    for t, ref in sorted(items, key=lambda x: x[0]):
        if out and t - out[-1][0] < tol_ft:
            continue
        out.append((t, ref))
    return out


# ------------------------------------------------------------------ rods
def rod_target_length(cur_total_ft, end_z, hit_z, struct_ext_ft=0.0):
    u"""Value to give SetRodLength so the rod top reaches hit_z.

    GetRodLength includes the structural extension, SetRodLength excludes it.
    """
    return (cur_total_ft + (hit_z - end_z)) - struct_ext_ft


def rod_ok(end_z, hit_z, ext_ft, tol_ft):
    u"""True if the rod top is at the soffit, or inside the allowed extension."""
    return (abs(end_z - hit_z) <= tol_ft) or (hit_z - tol_ft <= end_z <= hit_z + ext_ft + tol_ft)


# ------------------------------------------------------- span positions
def span_segments(chain, points):
    u"""chain items + {id: (entry_pt, exit_pt)} -> [(s0, a, b, id)] in span order."""
    out = []
    s = 0.0
    for it in chain:
        pts = points.get(it['id'])
        if pts is not None and it['kind'] == 'straight':
            out.append((s, pts[0], pts[1], it['id']))
        s += it['len']
    return out


def station_of_point(segs, p, max_off_ft):
    u"""Station (ft from span start) of a point lying on the span, else None.

    Only the plan offset counts against max_off_ft (a hanger or tap sits above
    or below the centreline); the vertical offset is allowed up to 5 ft.
    """
    best = None
    for s0, a, b, _id in segs:
        t, q, _d = closest_on_segment(p, a, b)
        dxy = math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2)
        dz = abs(p[2] - q[2])
        if dxy > max_off_ft or dz > 5.0:
            continue
        seg_len = vlen(vsub(b, a))
        if (t <= 0.0 or t >= 1.0) and vlen(vsub(p, q)) > max_off_ft:
            continue
        st = s0 + t * seg_len
        if best is None or dxy < best[0]:
            best = (dxy, st)
    return None if best is None else best[1]


def station_on_run(segs, p, max_off_ft, end_tol_ft=10.0 / MM, max_dz_ft=5.0):
    u"""Station of a hanger that really sits ON this span, else None.

    Stricter than station_of_point: the point must project inside a segment
    (end_tol_ft of slack at the ends, no clamping), so a hanger on the next
    duct round a bend is not read as one at the start of this span.
    """
    best = None
    for s0, a, b, _id in segs:
        ab = vsub(b, a)
        L = vlen(ab)
        if L < 1e-9:
            continue
        d = vscale(ab, 1.0 / L)
        along = vdot(vsub(p, a), d)
        if along < -end_tol_ft or along > L + end_tol_ft:
            continue
        q = vadd(a, vscale(d, along))
        dxy = math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2)
        if dxy > max_off_ft or abs(p[2] - q[2]) > max_dz_ft:
            continue
        st = s0 + max(0.0, min(L, along))
        if best is None or dxy < best[0]:
            best = (dxy, st)
    return None if best is None else best[1]


def avoid_blocks(stations, blocks, clear_ft, length_ft, edge_ft):
    u"""Move stations off takeoffs (taps on the run).

    A station within clear_ft of a block moves to the nearer side of it, as
    long as that spot is on the span and clear of every other block; if
    neither side is free the station is dropped.
    """
    if not blocks:
        return list(stations)

    def free(s):
        return edge_ft <= s <= length_ft - edge_ft and all(abs(s - b) >= clear_ft - 1e-9 for b in blocks)

    out = []
    for s in stations:
        if free(s):
            out.append(s)
            continue
        near = min(blocks, key=lambda b: abs(s - b))
        options = sorted([near - clear_ft, near + clear_ft], key=lambda c: abs(c - s))
        for c in options:
            if free(c):
                out.append(c)
                break
    return sorted(out)


def pick_condition(conditions, size_ft):
    u"""conditions: [(index, lower, upper, unrestricted)] -> best index or None.

    A restricted range covering the size wins (tightest first); an
    unrestricted condition is the fallback.
    """
    hits = []
    loose = None
    for idx, lo, hi, unrestricted in conditions:
        if unrestricted:
            if loose is None:
                loose = idx
            continue
        if hi < 0:  # open-ended upper bound
            hi = 1e9
        if lo - 1e-6 <= size_ft <= hi + 1e-6:
            hits.append((hi - lo, idx))
    if hits:
        return sorted(hits)[0][1]
    return loose


# ---------------------------------------------------------- window size
def fit_height(win_h, viewport_h, content_h, min_h, top, wa_top, wa_h):
    u"""(height, top) that shows the whole tab: grow or shrink the window by
    the difference between the tab's content and the space it has now, never
    taller than the screen's working area or shorter than the minimum, and
    moved up if it would run off the bottom of the screen."""
    h = win_h + (content_h - viewport_h)
    h = max(min_h, min(h, wa_h))
    if top + h > wa_top + wa_h:
        top = max(wa_top, wa_top + wa_h - h)
    if top < wa_top:
        top = wa_top
    return h, top


# ------------------------------------------------------- hanger matching
def name_tokens(*texts):
    u"""Lower-case word tokens with every digit removed, so 'Clevis 300' and
    'CLEVIS-450' share 'clevis' - sizes never decide what kind of hanger it is."""
    out = set()
    for t in texts:
        word = []
        for ch in u'{0}'.format(t or u'').lower() + u' ':
            if ch.isalpha():
                word.append(ch)
            else:
                if len(word) >= 2:
                    out.add(u''.join(word))
                word = []
    return out


def signature_score(old, new):
    u"""How alike two hangers are.  Each is a dict of name, product, alias,
    item_id (the item file's custom id) and code.  The item id is the
    strongest evidence; names are compared as size-free word sets."""
    score = 0.0
    if old.get('item_id') and old.get('item_id') == new.get('item_id'):
        score += 5.0
    for key, weight in (('product', 2.0), ('code', 1.5), ('alias', 1.0)):
        a = u'{0}'.format(old.get(key) or u'').strip().lower()
        if a and a == u'{0}'.format(new.get(key) or u'').strip().lower():
            score += weight
    ta = name_tokens(old.get('name'), old.get('product'), old.get('alias'))
    tb = name_tokens(new.get('name'), new.get('product'), new.get('alias'))
    if ta and tb:
        score += 3.0 * len(ta & tb) / float(len(ta | tb))
    return score


# ------------------------------------------------------------------ misc
def plural(n, one, many=None):
    return u'{0} {1}'.format(n, one if n == 1 else (many or one + u's'))


class DebugLog(object):
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.lines = []

    def add(self, msg):
        if self.enabled:
            try:
                self.lines.append(u'{0}'.format(msg))
            except Exception:
                self.lines.append(repr(msg))

    def text(self):
        return u'\n'.join(self.lines)

    def write(self, path=None):
        if not self.enabled:
            return
        p = path or debug_path()
        try:
            folder = os.path.dirname(p)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
            with io.open(p, 'w', encoding='utf-8') as fh:
                fh.write(self.text() + u'\n')
        except Exception:
            pass
