# -*- coding: utf-8 -*-
u"""Hanger Automation - Family Hangers tab, pure logic (no .NET, no Revit).

Lengths are decimal feet unless a name ends in _mm.  Everything here is
proved by bench_logic.py under plain CPython.
"""
import os
import io
import math
import fha_core as core

MM = core.MM

# category key (BuiltInCategory name) -> label, in list order
CATEGORIES = [
    (u'all', u'All hanger categories'),
    (u'OST_GenericModel', u'Generic Models'),
    (u'OST_MEPAncillaryFraming', u'MEP Ancillary Framing'),
    (u'OST_DuctAccessory', u'Duct Accessories'),
]

ROD_DEFAULT = u'BGL_DIM_Drop Rod Length'
FIRST_BAR_DEFAULT = u'First Bar Offset'
SUPPORT_HEIGHT_DEFAULT = u'BIM_Hanger_Support_Height'
DIAMETER_DEFAULT = u'BIM_DIM_Diameter'

# per-family settings (Family settings button)
FAM_DEFAULTS = {
    u'left': u'',            # instance length stretching one way from centre
    u'right': u'',           # instance length stretching the other way
    u'rod': ROD_DEFAULT,     # drop rod length
    u'axis': u'X',           # the family's width runs along its X (left/right) or Y
    u'clearance': u'0',      # mm added to each half width
    u'soffit': u'level',     # level = base of the level above; structure = ray to structure
    u'swap': u'0',           # 1 = the first width parameter is the family's positive side
    # floor supports (Family Floor Support tab)
    u'first_bar': FIRST_BAR_DEFAULT,      # level -> top of the bottom bar (the service invert)
    u'height': SUPPORT_HEIGHT_DEFAULT,    # bottom bar top -> top bar underside (the service depth)
    u'height_clear': u'0',                # mm added to the support height above the service
    # floor support style: rect = Rectangular Floor Based (frame round the service),
    # circ = Circular System Based (a ring round a pipe / round duct on a post)
    u'style': u'rect',
    u'dia': DIAMETER_DEFAULT,             # circ: ring diameter, set to the service's (insulated) diameter
    u'circ_height': SUPPORT_HEIGHT_DEFAULT,   # circ: base -> service centre (the ring centre)
    u'circ_axis': u'X',                   # circ: the service runs along the family's X or Y
}
MODES = (u'hang', u'floor')
STYLES = [(u'rect', u'Rectangular Floor Based'), (u'circ', u'Circular System Based')]
RUN_AXES = [(u'X', u'X - left / right'), (u'Y', u'Y - front / back')]
AXES = [(u'X', u'X - left / right'), (u'Y', u'Y - front / back')]
SOFFITS = [(u'level', u'Base of the level above'), (u'structure', u'Underside of structure above')]


# ===================================================== family settings file
def families_path():
    return os.path.join(core.settings_dir(), 'hanger_automation_families.txt')


def parse_families(text):
    u"""[Family name] sections of key=value lines -> {family: {key: value}}."""
    out = {}
    cur = None
    for raw in (text or u'').splitlines():
        line = raw.strip()
        if not line or line.startswith(u'#'):
            continue
        if line.startswith(u'[') and line.endswith(u']'):
            cur = line[1:-1].strip()
            out.setdefault(cur, {})
            continue
        if cur is None or u'=' not in line:
            continue
        k, v = line.split(u'=', 1)
        k = k.strip()
        if k in FAM_DEFAULTS:
            out[cur][k] = v.strip()
    return out


def dump_families(fams):
    lines = [u'# Hanger Automation - family hanger settings']
    for name in sorted(fams):
        lines.append(u'[{0}]'.format(name))
        for k in sorted(FAM_DEFAULTS):
            lines.append(u'{0}={1}'.format(k, fams[name].get(k, FAM_DEFAULTS[k])))
    return u'\n'.join(lines) + u'\n'


def load_families(path=None):
    p = path or families_path()
    try:
        if os.path.exists(p):
            with io.open(p, 'r', encoding='utf-8') as f:
                return parse_families(f.read())
    except Exception:
        pass
    return {}


def save_families(fams, path=None):
    p = path or families_path()
    try:
        folder = os.path.dirname(p)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with io.open(p, 'w', encoding='utf-8') as f:
            f.write(dump_families(fams))
        return True
    except Exception:
        return False


def fam_config(fams, family, param_names=None):
    u"""Settings for one family, defaults filled in, width parameters guessed
    from the family's own parameter names when none have been chosen."""
    cfg = dict(FAM_DEFAULTS)
    cfg.update(fams.get(family, {}))
    if param_names and not (cfg[u'left'] and cfg[u'right']):
        gl, gr = guess_width_params(param_names)
        cfg[u'left'] = cfg[u'left'] or gl
        cfg[u'right'] = cfg[u'right'] or gr
    if param_names and cfg[u'rod'] not in param_names:
        g = guess_rod_param(param_names)
        if g:
            cfg[u'rod'] = g
    if param_names and cfg[u'first_bar'] not in param_names:
        g = guess_first_bar_param(param_names)
        if g:
            cfg[u'first_bar'] = g
    if param_names and cfg[u'height'] not in param_names:
        g = guess_support_height_param(param_names)
        if g:
            cfg[u'height'] = g
    if param_names and cfg[u'dia'] not in param_names:
        g = guess_diameter_param(param_names)
        if g:
            cfg[u'dia'] = g
    if param_names and cfg[u'circ_height'] not in param_names:
        g = guess_support_height_param(param_names)
        if g:
            cfg[u'circ_height'] = g
    for key, ok, default in ((u'axis', (u'X', u'Y'), u'X'), (u'soffit', (u'level', u'structure'), u'level'),
                             (u'style', (u'rect', u'circ'), u'rect'), (u'circ_axis', (u'X', u'Y'), u'X')):
        if cfg[key] not in ok:
            cfg[key] = default
    return cfg


def configured(fams, family):
    u"""Has this family been through Family settings (saved at least once)?"""
    return family in fams


def guess_diameter_param(names):
    u"""'BIM_DIM_Diameter' style: a name containing diameter (else dia)."""
    for want in (u'diameter', u'dia'):
        for n in names:
            if want in n.lower():
                return n
    return u''


def _words(name):
    return set(core.name_tokens(name)) | set(w for w in u'{0}'.format(name).lower().replace(u'_', u' ').split())


def guess_width_params(names):
    u"""(left, right) from a family's length parameters: a Left / Right pair
    first (BGL_DIM_Width Left, Width_L ...), then any pair differing only in
    left / right or L / R."""
    left = right = u''
    for n in names:
        w = _words(n)
        low = n.lower()
        if not left and (u'left' in w or low.endswith(u'_l') or low.endswith(u' l')):
            left = n
        elif not right and (u'right' in w or low.endswith(u'_r') or low.endswith(u' r')):
            right = n
    return left, right


def guess_rod_param(names):
    for n in names:
        low = n.lower()
        if u'rod' in low and (u'length' in low or u'len' in low):
            return n
    return u''


def guess_first_bar_param(names):
    u"""'First Bar Offset' style: first + bar, else bar + offset."""
    for want in ((u'first', u'bar'), (u'bar', u'offset')):
        for n in names:
            low = n.lower()
            if all(w in low for w in want) and u'last' not in low:
                return n
    return u''


def guess_support_height_param(names):
    u"""'BIM_Hanger_Support_Height' style: support + height."""
    for n in names:
        low = n.lower()
        if u'support' in low and u'height' in low:
            return n
    return u''


def floor_values(z_invert, level_z, sec, height_clear_ft):
    u"""(first bar offset, support height) for a floor support: the bottom bar's
    top at the service invert (measured from the level the support stands on),
    the gap to the top bar the service's full depth - insulation included when
    the support goes round it - plus the clearance above.  A group uses the
    span from its lowest bottom to its highest top."""
    first = z_invert - level_z
    h = sec.get('span_height')
    if h is None:
        h = sec['depth']
    return first, h + height_clear_ft


def flr_name(name):
    u"""The Floor Support tab's control name for a Family Hangers one."""
    if name == u'FamPanel':
        return u'FloorPanel'
    if name == u'LstFamilies':
        return u'LstFlrFamilies'
    return name.replace(u'Fam', u'Flr', 1)


# ================================================================ the list
def filter_types(items, category, text):
    u"""items: dicts with family, type, cat.  Every search word must appear in
    'family type' (any case, any order)."""
    words = [w for w in (text or u'').lower().split() if w]
    out = []
    for it in items:
        if category not in (None, u'', u'all') and it.get('cat') != category:
            continue
        hay = u'{0} {1}'.format(it.get('family', u''), it.get('type', u'')).lower()
        if all(w in hay for w in words):
            out.append(it)
    return out


def item_key(family, type_name):
    return u'{0} : {1}'.format(family, type_name)


# ============================================================== DW/144 etc
# DW/144 maximum support spacing for horizontal ductwork.  Based on duct weight
# only; closer spacings may be needed for rigidity or the structure.  The tool
# uses min(your maximum, this) when the DW/144 tick is on.
DW144_RECT = [(1500.0, 3000.0), (1e9, 2500.0)]    # longer side up to, spacing
DW144_ROUND = [(1120.0, 3000.0), (1e9, 2500.0)]   # diameter up to, spacing


def dw144_spacing_mm(width_mm, depth_mm, is_round):
    size = width_mm if is_round else max(width_mm, depth_mm)
    for upto, spacing in (DW144_ROUND if is_round else DW144_RECT):
        if size <= upto + 1e-6:
            return spacing
    return DW144_RECT[-1][1]


def span_spacing_mm(user_max_mm, use_dw144, width_mm, depth_mm, is_round):
    s = max(100.0, user_max_mm)
    if use_dw144:
        s = min(s, dw144_spacing_mm(width_mm, depth_mm, is_round))
    return s


def auto_config(settings, spacing_mm):
    u"""fha_core.plan_stations config for one span of family hangers."""
    return {
        'spacing': spacing_mm,
        'start_off': core.as_float(settings, u'fam_start_off', 300.0),
        'end_off': core.as_float(settings, u'fam_end_off', 300.0),
        'takeoff_max': 600.0,
        'takeoff_clear': core.as_float(settings, u'fam_takeoff_clear', 400.0),
        'min_gap': 500.0,
        'edge': max(100.0, core.as_float(settings, u'fam_flange_clear', 150.0)),
    }


# ============================================================ placement
def half_width(width_ft, clearance_mm):
    u"""Value for each of the two stretch parameters: half the duct plus clearance."""
    return width_ft / 2.0 + clearance_mm / MM


def rod_length(ref_z, soffit_z):
    u"""Drop rod from the family's reference level (the duct invert) up to the
    soffit, or None when the soffit is not above it."""
    if soffit_z is None:
        return None
    L = soffit_z - ref_z
    return L if L > 1e-6 else None


def level_above(level_elevations, z, tol_ft=1.0 / MM):
    u"""Lowest level elevation strictly above z (the base of the level above)."""
    above = [e for e in level_elevations if e > z + tol_ft]
    return min(above) if above else None


def level_below(level_elevations, z, tol_ft=1.0 / MM):
    below = [e for e in level_elevations if e <= z + tol_ft]
    return max(below) if below else None


def rotation_to(current, wanted):
    u"""Plan rotation (radians) turning `current` onto `wanted`.  A hanger is
    symmetric, so facing either way is aligned: the answer is folded into
    (-90, 90] degrees so it never spins a hanger round needlessly."""
    a = math.atan2(current[0] * wanted[1] - current[1] * wanted[0],
                   current[0] * wanted[0] + current[1] * wanted[1])
    while a > math.pi / 2.0 + 1e-9:
        a -= math.pi
    while a <= -math.pi / 2.0 + 1e-9:
        a += math.pi
    return a


def plan_dirs(a, b):
    u"""(along, across) unit plan vectors of a duct from a to b."""
    d = core.vnorm((b[0] - a[0], b[1] - a[1], 0.0))
    return d, (-d[1], d[0], 0.0)


def family_x_dir(axis, along, across):
    u"""Where the family's own X axis must point: across the duct when its
    width runs along X, along the duct when its width runs along Y."""
    return across if axis == u'X' else along


def on_centreline(a, b, p, margin_ft):
    u"""Closest point to p on the duct centreline a-b, kept margin_ft off the ends."""
    ab = core.vsub(b, a)
    L = core.vlen(ab)
    if L < 1e-9:
        return a
    t, _q, _d = core.closest_on_segment(p, a, b)
    s = t * L
    if L > 2.0 * margin_ft:
        s = max(margin_ft, min(L - margin_ft, s))
    else:
        s = L / 2.0
    return core.vadd(a, core.vscale(ab, s / L))


# ============================================================== re-align
def line_param(a, b, p):
    u"""Unclamped position of p along a-b in plan (0 at a, 1 at b)."""
    ab = (b[0] - a[0], b[1] - a[1])
    den = ab[0] * ab[0] + ab[1] * ab[1]
    if den < 1e-12:
        return 0.0
    return ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / den


def on_line(a, b, p):
    u"""The point on the duct's centreline square across from p: p keeps its
    position along the run and only its sideways offset changes.  The line is
    NOT clipped to the segment, so a hanger beyond this segment's end stays
    exactly where it is along the run.  Z follows the centreline (sloped ducts)."""
    t = line_param(a, b, p)
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def plan_offset(a, b, p):
    q = on_line(a, b, p)
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def pick_segment(p, segs, tol_ft):
    u"""segs: (key, a, b).  The segment the hanger actually sits on: p falls
    within its length (tol_ft either end, for hangers on a joint) and it is the
    nearest in plan.  None when p is off every segment."""
    best = None
    for key, a, b in segs:
        L = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        if L < 1e-9:
            continue
        t = line_param(a, b, p)
        slack = tol_ft / L
        if t < -slack or t > 1.0 + slack:
            continue
        off = plan_offset(a, b, p)
        if best is None or off < best[0]:
            best = (off, key)
    return None if best is None else best[1]


# ============================================================ dimensions
def canonical_dir(d):
    u"""A plan direction with its sign fixed (pointing +X, or +Y when vertical),
    so hangers facing either way along a run agree."""
    n = core.vnorm((d[0], d[1], 0.0))
    if n[0] < -1e-6 or (abs(n[0]) <= 1e-6 and n[1] < 0):
        n = (-n[0], -n[1], 0.0)
    return n


def group_runs(hangers, line_tol_ft, angle_tol_deg=3.0):
    u"""hangers: (key, point, along) where along is the run direction at the hanger.
    Returns [(direction, [keys sorted along the run])] - one group per straight
    line of hangers (same direction, same line within line_tol_ft), 2 or more."""
    groups = []   # [dir, offset, [(s, key)]]
    cos_tol = math.cos(math.radians(angle_tol_deg))
    for key, p, along in hangers:
        d = canonical_dir(along)
        if d == (0.0, 0.0, 0.0):
            continue
        n = (-d[1], d[0])
        off = p[0] * n[0] + p[1] * n[1]
        s = p[0] * d[0] + p[1] * d[1]
        home = None
        for g in groups:
            if abs(g[0][0] * d[0] + g[0][1] * d[1]) >= cos_tol and abs(g[1] - off) <= line_tol_ft:
                home = g
                break
        if home is None:
            groups.append([d, off, [(s, key)]])
        else:
            home[2].append((s, key))
    out = []
    for d, _off, members in groups:
        if len(members) >= 2:
            out.append((d, [k for _s, k in sorted(members)]))
    return out


def reference_type_across(hand, facing, along):
    u"""Which centre reference of a family instance is square to the run:
    CenterLeftRight is the plane across the family's X (hand), CenterFrontBack
    across its Y (facing).  The one whose normal lies along the run wins."""
    h = abs(hand[0] * along[0] + hand[1] * along[1])
    f = abs(facing[0] * along[0] + facing[1] * along[1])
    return 'CenterLeftRight' if h >= f else 'CenterFrontBack'


# ============================================================ insulation
def apply_insulation(sec, outside):
    u"""The size a hanger has to fit.  Outside insulation (the default) the
    hanger wraps the insulated duct: width + 2t, depth + 2t, so the invert it
    sits on drops by t.  Inside, it fits the bare duct.  Returns a new dict;
    'bare_width' / 'bare_depth' keep the duct's own size."""
    t = sec.get('ins', 0.0) or 0.0
    out = dict(sec)
    out['bare_width'] = sec['width']
    out['bare_depth'] = sec['depth']
    out['ins_used'] = bool(outside and t > 0)
    if out['ins_used']:
        out['width'] = sec['width'] + 2.0 * t
        out['depth'] = sec['depth'] + 2.0 * t
    return out


# ===================================================== grouped services
BUNDLE_Z_MM = 50.0       # bottoms within this of each other
BUNDLE_GAP_MM = 500.0    # clear gap in plan between neighbours under this
BUNDLE_ANGLE_DEG = 2.0   # counts as parallel
CENTRES = [(u'mean', u'Mean of the service centres'), (u'edges', u'Middle of the outer edges')]


def wrap_rules(rules):
    u"""The rules for services the user selected to hang together: no gap or
    height limit (they were chosen), only parallel and alongside count."""
    return (1.0e9, 1.0e9, rules[2], rules[3])


def group_rules(settings):
    u"""(z_tol_ft, gap_tol_ft, angle_deg, centre) from the Hanger rules settings."""
    return (core.as_float(settings, u'fam_group_z', BUNDLE_Z_MM) / MM,
            core.as_float(settings, u'fam_group_gap', BUNDLE_GAP_MM) / MM,
            core.as_float(settings, u'fam_group_angle', BUNDLE_ANGLE_DEG),
            settings.get(u'fam_group_centre', u'mean') if settings.get(u'fam_group_centre') in (u'mean', u'edges') else u'mean')


def bundle(point, members, z_tol_ft=BUNDLE_Z_MM / MM, gap_tol_ft=BUNDLE_GAP_MM / MM,
           angle_deg=BUNDLE_ANGLE_DEG, centre=u'mean'):
    u"""One hanger round several services.

    members: [(key, a, b, width, depth)] with the sizes the hanger has to fit
    (insulation already applied); members[0] is the service the hanger was
    placed for (the lead), `point` is on or near its centreline.

    A service joins when it is parallel to the lead (within angle_deg), runs
    alongside it at this point, its clear gap in plan to the group's nearest
    edge is under gap_tol_ft (chained neighbour to neighbour), and every bottom
    in the group stays within z_tol_ft of the others.

    The hanger is centred on the mean of the members' centres ('mean'), or
    midway between the outer edges ('edges'); ext_neg / ext_pos are how far it
    must reach either side of that centre (along `across`, the lead's plan
    normal) to the outer edges.  It sits at the lowest bottom.

    Returns {'keys', 'width', 'ext_neg', 'ext_pos', 'across', 'bottom', 'point',
    'a', 'b', 'notes'}; a / b are the lead's centreline moved to the hanger
    centre and down to the lowest bottom, so the hanger can be fitted to it like
    a single service of depth 0.
    """
    key0, a0, b0, w0, d0 = members[0]
    along, across = plan_dirs(a0, b0)
    q0 = on_line(a0, b0, point)
    cos_tol = math.cos(math.radians(angle_deg))
    rows, notes = [], []
    for i, (key, a, b, w, dep) in enumerate(members):
        if i:
            dd, _n = plan_dirs(a, b)
            if abs(dd[0] * along[0] + dd[1] * along[1]) < cos_tol:
                notes.append(u'{0}: not parallel'.format(key))
                continue
            t = line_param(a, b, q0)
            if t < -1e-6 or t > 1.0 + 1e-6:
                notes.append(u'{0}: does not run alongside here'.format(key))
                continue
        q = on_line(a, b, q0)
        off = (q[0] - q0[0]) * across[0] + (q[1] - q0[1]) * across[1]
        rows.append({'key': key, 'off': off, 'w': w, 'bottom': q[2] - dep / 2.0, 'top': q[2] + dep / 2.0,
                     'lead': i == 0})
    rows.sort(key=lambda r: r['off'])
    li = [i for i, r in enumerate(rows) if r['lead']][0]
    lo = hi = li
    bottoms = [rows[li]['bottom']]

    def gap(i, j):   # clear gap between rows i < j
        return (rows[j]['off'] - rows[j]['w'] / 2.0) - (rows[i]['off'] + rows[i]['w'] / 2.0)

    while True:
        options = []
        if lo > 0:
            options.append((gap(lo - 1, lo), 'lo'))
        if hi < len(rows) - 1:
            options.append((gap(hi, hi + 1), 'hi'))
        grown = False
        for g, side in sorted(options):
            j = lo - 1 if side == 'lo' else hi + 1
            nb = bottoms + [rows[j]['bottom']]
            if g < gap_tol_ft and max(nb) - min(nb) <= z_tol_ft + 1e-9:
                bottoms = nb
                if side == 'lo':
                    lo = j
                else:
                    hi = j
                grown = True
                break
        if not grown:
            break
    group = rows[lo:hi + 1]
    for i, r in enumerate(rows):
        if lo <= i <= hi or r['lead']:
            continue
        near = lo - 1 if i < lo else hi + 1
        g = gap(i, lo) if i < lo else gap(hi, i)
        nb = bottoms + [r['bottom']]
        why = []
        if i == near and g >= gap_tol_ft:
            why.append(u'gap {0:.0f} mm (limit {1:.0f})'.format(g * MM, gap_tol_ft * MM))
        if max(nb) - min(nb) > z_tol_ft + 1e-9:
            why.append(u'height differs by {0:.0f} mm (limit {1:.0f})'.format((max(nb) - min(nb)) * MM, z_tol_ft * MM))
        notes.append(u'{0}: left out - {1}'.format(r['key'], u', '.join(why) or u'beyond a service that was left out'))
    left = min(r['off'] - r['w'] / 2.0 for r in group)
    right = max(r['off'] + r['w'] / 2.0 for r in group)
    if centre == u'edges' or len(group) == 1:
        c = (left + right) / 2.0
    else:
        c = sum(r['off'] for r in group) / float(len(group))
    bottom = min(bottoms)
    dz = bottom - q0[2]
    shift = (across[0] * c, across[1] * c, dz)
    return {'keys': [r['key'] for r in group], 'width': right - left, 'ext_neg': c - left, 'ext_pos': right - c,
            'across': across, 'bottom': bottom, 'top': max(r['top'] for r in group), 'notes': notes,
            'point': (q0[0] + shift[0], q0[1] + shift[1], bottom),
            'a': core.vadd(a0, shift), 'b': core.vadd(b0, shift)}


def bundle_section(b, lead_sec):
    u"""The section the hanger fitting code uses.

    A single service (no neighbours joined) keeps its OWN section - round flag,
    depth, insulation - so it is fitted and locked exactly like a hanger placed
    with no pre-selection.  A group becomes depth 0 on a line at the lowest
    bottom, carrying how far to reach either side of its centre.
    """
    if len(b['keys']) <= 1:
        sec = dict(lead_sec)
        sec['keys'] = list(b['keys'])
        return sec
    sec = {'a': b['a'], 'b': b['b'], 'width': b['width'], 'depth': 0.0, 'round': False,
           'ins': lead_sec.get('ins', 0.0), 'ins_used': lead_sec.get('ins_used', False),
           'bare_width': b['width'], 'bare_depth': 0.0, 'keys': b['keys'],
           'ext_neg': b['ext_neg'], 'ext_pos': b['ext_pos'], 'across': b['across'],
           'span_height': b['top'] - b['bottom']}
    return sec


def bundle_point(b, lead_sec, point):
    u"""Where the hanger goes: a group's centre at its lowest bottom, or a single
    service's own centreline (its invert follows from its depth)."""
    if len(b['keys']) <= 1:
        return on_line(lead_sec['a'], lead_sec['b'], point)
    return b['point']


# ===================================================== equipment / accessories
def unit_section(hand, facing, pts, bottom_z=None, run_hint=None, pick=None):
    u"""A 'service' for a hanger under a unit (mechanical equipment or a duct
    accessory): the hanger spans ACROSS the unit at its bottom face.

    hand / facing: the unit's plan axes; pts: points on its geometry (world);
    bottom_z: its lowest downward face (else the lowest point); run_hint: a
    plan direction the unit runs along (its in-line connectors), else the
    longer side; pick: where the user clicked (sets the place along the run).

    Returns a section dict like a duct's ('a', 'b' through the unit's centre
    across, 'width' across, 'depth' so the invert is the bottom face) plus
    'unit', 'run_from', 'length'.
    """
    def unit2(v):
        L = math.sqrt(v[0] ** 2 + v[1] ** 2)
        return (v[0] / L, v[1] / L) if L > 1e-9 else None
    h, f = unit2(hand) or (1.0, 0.0), unit2(facing) or (0.0, 1.0)
    ph = [p[0] * h[0] + p[1] * h[1] for p in pts]
    pf = [p[0] * f[0] + p[1] * f[1] for p in pts]
    eh, ef = (min(ph), max(ph)), (min(pf), max(pf))
    run_from = u'longer side'
    hint = unit2(run_hint) if run_hint is not None else None
    if hint is not None:
        run_is_h = abs(hint[0] * h[0] + hint[1] * h[1]) >= abs(hint[0] * f[0] + hint[1] * f[1])
        run_from = u'its connectors'
    else:
        run_is_h = (eh[1] - eh[0]) >= (ef[1] - ef[0])
    run, run_ext, ac, ac_ext = (h, eh, f, ef) if run_is_h else (f, ef, h, eh)
    zs = [p[2] for p in pts]
    bottom = min(zs) if bottom_z is None else bottom_z
    top = max(zs)
    if top - bottom < 1e-6:
        top = bottom + 1e-3
    zc = (bottom + top) / 2.0
    c_ac = (ac_ext[0] + ac_ext[1]) / 2.0

    def at(s):
        return (run[0] * s + ac[0] * c_ac, run[1] * s + ac[1] * c_ac, zc)
    a, b = at(run_ext[0]), at(run_ext[1])
    width = ac_ext[1] - ac_ext[0]
    return {'a': a, 'b': b, 'width': width, 'depth': top - bottom, 'round': False,
            'ins': 0.0, 'ins_used': False, 'bare_width': width, 'bare_depth': top - bottom,
            'unit': True, 'run_from': run_from, 'length': run_ext[1] - run_ext[0], 'bottom': bottom}


def inline_direction(conns):
    u"""Plan direction of an in-line unit from its connectors [(origin, basisZ)]:
    two horizontal connectors facing opposite ways.  None if there is no pair."""
    flat = [(o, d) for o, d in conns if abs(d[2]) < 0.1]
    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            d1, d2 = flat[i][1], flat[j][1]
            if d1[0] * d2[0] + d1[1] * d2[1] < -0.9:
                return (d1[0], d1[1])
    return None


def side_values(sec, axis_vec, clearance_ft, swap=False):
    u"""(left, right) stretch values.  A single service: half its width each side.
    A group: the family's positive-axis side ('right', or 'left' when swapped)
    reaches the group's edge on that side, the other the opposite edge."""
    if sec.get('ext_neg') is None:
        h = sec['width'] / 2.0 + clearance_ft
        return h, h
    ac = sec['across']
    s = axis_vec[0] * ac[0] + axis_vec[1] * ac[1]
    pos, neg = (sec['ext_pos'], sec['ext_neg']) if s >= 0 else (sec['ext_neg'], sec['ext_pos'])
    left, right = neg + clearance_ft, pos + clearance_ft
    return (right, left) if swap else (left, right)


# ============================================================ drop rods
def rod_to_target(ref_z, target_z):
    u"""Drop rod from the hanger's reference level up to a target's underside."""
    return rod_length(ref_z, target_z)


def reaches(corners, centre, across):
    u"""(positive, negative) reach of a hanger across the run, from the plan
    corners of its bounding box, measured from its centre point."""
    proj = [(c[0] - centre[0]) * across[0] + (c[1] - centre[1]) * across[1] for c in corners]
    return max(proj), -min(proj)


def sides_mirrored(reach_pos, reach_neg, want_pos, want_neg, tol_ft=1.0 / MM):
    u"""True when the hanger came out the wrong way round: its long side is on
    the side that should be short.  Families differ in which of their two
    stretch parameters points which way, so this is measured, not assumed."""
    as_is = abs(reach_pos - want_pos) + abs(reach_neg - want_neg)
    swapped = abs(reach_pos - want_neg) + abs(reach_neg - want_pos)
    return swapped + tol_ft < as_is
