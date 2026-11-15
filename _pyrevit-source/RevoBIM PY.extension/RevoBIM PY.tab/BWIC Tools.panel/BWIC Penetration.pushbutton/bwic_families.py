# -*- coding: utf-8 -*-
"""Family profiles: which parameter of a family plays which sizing role.

The tool used to assume one family's parameter names. A profile records, per
family name, how THAT family sizes itself -- which parameter is the thickness
through the wall, which is the width, whether it is round and whether its
round size is a diameter or a radius -- so a differently built family can be
dropped in and sized correctly.

Profiles are stored in one JSON file beside the settings. At placement time
`overlay()` writes the chosen family's profile onto the settings keys the
core already reads, so the sizing code itself does not change. A family with
no saved profile overlays nothing, which keeps every existing setting working
exactly as before.

Plain Python with no Revit or WPF, so the bench proves it in CPython.
"""
import io
import json
import os
import os.path as op

RECT = 'rectangular'
CIRC = 'circular'

# (slot, label, settings key holding the family, settings key holding the type)
SLOTS = [
    ('wall', 'Wall penetration, rectangular', 'wall_family', 'wall_type'),
    ('wall_circ', 'Wall penetration, circular', 'wall_circ_family',
     'wall_circ_type'),
    ('slab_rect', 'Slab penetration, rectangular', 'slab_family', 'slab_type'),
    ('slab_circ', 'Slab penetration, circular', 'slab_circ_family',
     'slab_circ_type'),
]

# the shape a slot's family takes: each slot exists for one shape, chosen by
# the sub tab it sits on
SLOT_SHAPES = {
    'wall': (RECT,),
    'wall_circ': (CIRC,),
    'slab_rect': (RECT,),
    'slab_circ': (CIRC,),
}

# settings keys for a slot's shape and for "the round size is a radius"
SHAPE_KEY = {}
RADIUS_KEY = {'wall_circ': 'wall_circ_radius',
              'slab_circ': 'slab_circular_radius'}

# a role: (key, label, help, settings key, 'length' or 'any', shapes, required)
_SLAB_POSITION = [
    ('vertical', 'Vertical height',
     'Written with the floor thickness. Single-level families.',
     'slab_height_param', 'length', (RECT, CIRC), False),
    ('top_height', 'Top height',
     'Height of the top of the opening. Single-level families.',
     'slab_top_height_param', 'length', (RECT, CIRC), False),
    ('level_offset', 'Offset from level',
     'Base of the opening above its level. Single-level families.',
     'slab_level_offset_param', 'length', (RECT, CIRC), False),
    ('base_level', 'Base level',
     'Blank uses Revit\'s own Base Level. Two-level families.',
     'slab_base_level_param', 'any', (RECT, CIRC), False),
    ('top_level', 'Top level',
     'Blank uses Revit\'s own Top Level. Two-level families.',
     'slab_top_level_param', 'any', (RECT, CIRC), False),
    ('base_offset', 'Base offset',
     'Blank uses Revit\'s own Base Offset. Two-level families.',
     'slab_base_offset_param', 'length', (RECT, CIRC), False),
    ('top_offset', 'Top offset',
     'Blank uses Revit\'s own Top Offset. Two-level families.',
     'slab_top_offset_param', 'length', (RECT, CIRC), False),
    ('level_code', 'Level code',
     'Text parameter the level code (00, 01, RF) is written to.',
     'slab_level_code_param', 'any', (RECT, CIRC), False),
]

ROLES = {
    'wall': [
        ('through', 'Through the wall',
         'Written with the wall thickness.',
         'wall_length_param', 'length', (RECT, CIRC), False),
        ('across', 'Width along the wall',
         'Extent of the services along the wall, plus clearance.',
         'wall_width_param', 'length', (RECT,), True),
        ('height', 'Height',
         'Extent of the services top to bottom, plus clearance.',
         'wall_height_param', 'length', (RECT,), True),
    ],
    'wall_circ': [
        ('through', 'Through the wall',
         'Written with the wall thickness.',
         'wall_circ_length_param', 'length', (CIRC,), False),
        ('diameter', 'Diameter or radius',
         'Outside diameter of the pipe plus the gap each side, or the '
         'circle around a group.',
         'wall_circ_diameter_param', 'length', (CIRC,), True),
    ],
    'slab_rect': [
        ('plan_x', 'Plan width',
         'One plan dimension of the opening, plus clearance.',
         'slab_width_param', 'length', (RECT,), True),
        ('plan_y', 'Plan depth',
         'The other plan dimension, plus clearance.',
         'slab_length_param', 'length', (RECT,), True),
    ] + _SLAB_POSITION,
    'slab_circ': [
        ('diameter', 'Diameter or radius',
         'Outside diameter of the service plus the gap each side.',
         'slab_circular_param', 'length', (CIRC,), True),
    ] + _SLAB_POSITION,
}

# How a rectangular family is driven. STANDARD: one parameter per size,
# centred on the origin. SPLIT: a pair per axis, a Minus and a Plus side, each
# taking half the overall size -- WLG_X_Minus + WLG_X_Plus = overall width.
STANDARD = 'standard'
SPLIT = 'split'

# (axis, label, the standard role whose size the pair takes) per slot. X is
# width, Y is length, Z is height.
SPLIT_AXES = {
    'wall': [('x', 'X = Width', 'across'),
             ('y', 'Y = Length', 'through'),
             ('z', 'Z = Height', 'height')],
    'slab_rect': [('x', 'X = Width', 'plan_x'),
                  ('y', 'Y = Length', 'plan_y'),
                  ('z', 'Z = Height', 'vertical')],
    # a round family has one diameter; only its thickness through can be a
    # pair -- through the wall, or through the floor
    'wall_circ': [('y', 'Y = Length', 'through')],
    'slab_circ': [('y', 'Y = Length', 'vertical')],
}

# what the second kind is called, on the strip in Family settings
SPLIT_LABEL = {'wall': 'X+ / X-', 'slab_rect': 'X+ / X-',
               'wall_circ': 'Y+ / Y-', 'slab_circ': 'Y+ / Y-'}


def axis_roles(slot):
    """The standard roles a slot's Minus / Plus pairs take over."""
    return set(role for _, _, role in SPLIT_AXES.get(slot, []))

# A split pair travels through the existing settings keys as one name, so
# every sizing rule works unchanged; only the writer in the core splits it.
SPLIT_PREFIX = '@split:'


def encode_split(minus, plus):
    return '{}{}|{}'.format(SPLIT_PREFIX, minus, plus)


def decode_split(name):
    """(minus, plus) for a split pair, or None for an ordinary parameter."""
    if not name or not name.startswith(SPLIT_PREFIX):
        return None
    minus, _, plus = name[len(SPLIT_PREFIX):].partition('|')
    if not minus or not plus:
        return None
    return minus, plus


def split_parts(name):
    """[(parameter, share of the size)] to write a size to.

    An ordinary parameter takes the whole size. A split pair takes half on
    each side, so the two always add up to the overall size and stay equal.
    """
    pair = decode_split(name)
    if pair is None:
        return [(name, 1.0)]
    return [(pair[0], 0.5), (pair[1], 0.5)]


def show_name(name):
    """A parameter name as a person would write it."""
    pair = decode_split(name)
    return '{} + {}'.format(*pair) if pair else name


# what a parameter is usually called, for a family with no profile yet
_HINTS = {
    'through': ('length', 'thickness', 'depth', 'through'),
    'across': ('width',),
    'height': ('height',),
    'diameter': ('diameter', 'dia', 'radius'),
    'plan_x': ('width',),
    'plan_y': ('depth', 'length', 'height'),
}


def slot_family_key(slot):
    return dict((s, f) for s, _, f, _ in SLOTS)[slot]


def slot_type_key(slot):
    return dict((s, t) for s, _, _, t in SLOTS)[slot]


def roles_for(slot, shape):
    """The roles a slot's family has, for its shape, in display order."""
    return [r for r in ROLES[slot] if shape in r[5]]


def default_shape(slot):
    return SLOT_SHAPES[slot][0]


# -- which list a family belongs in -------------------------------------------
ROUND_PARAM_WORDS = ('diameter', 'radius')
ROUND_NAME_WORDS = ('circular', 'round')


def family_shape(length_names, family_name='', placed=True):
    """CIRC for a family with a Diameter or Radius length parameter, else RECT.

    Instance parameters are only visible once a family has been placed, so a
    family never placed in the model also counts as round when its own name
    says circular or round.
    """
    for name in length_names or ():
        low = name.lower()
        if any(word in low for word in ROUND_PARAM_WORDS):
            return CIRC
    if not placed:
        low = (family_name or '').lower()
        if any(word in low for word in ROUND_NAME_WORDS):
            return CIRC
    return RECT


def families_for_slot(slot, families, shapes):
    """The families a slot's list offers: only those of the slot's shape.

    families: [(name, ...)] as the core lists them; shapes: {name: shape}.
    A family whose shape is unknown is offered everywhere.
    """
    wanted = SLOT_SHAPES[slot]
    return [entry for entry in families
            if shapes.get(entry[0], wanted[0]) in wanted]


def wall_span(d_start, d_end, half_thickness):
    """Where a straight run is inside a wall, as fractions along the run.

    d_start and d_end are the run's end points' distances from the wall's
    centre line, across the wall. Returns (t_in, t_out) between 0 and 1, or
    None when the run is parallel to the wall and the whole run should count.
    A run that stops short of the wall gives its nearest end, twice.

    Only the length inside the wall sizes the opening: measured over the
    whole run, a drainage pipe's fall, or a pipe crossing at an angle, would
    be added to the height or width.
    """
    travel = d_end - d_start
    if abs(travel) < 1e-9:
        return None
    t_a = (-half_thickness - d_start) / travel
    t_b = (half_thickness - d_start) / travel
    t_in, t_out = sorted((t_a, t_b))
    t_in = min(max(t_in, 0.0), 1.0)
    t_out = min(max(t_out, 0.0), 1.0)
    return t_in, t_out


def _guess(role, names, taken):
    for hint in _HINTS.get(role, ()):
        for name in names:
            if name in taken:
                continue
            if hint in name.lower():
                return name
    return ''


def guess_split(slot, names):
    """{axis: {'minus': name, 'plus': name}} found by name, e.g. WLG_X_Minus.

    A name counts for an axis when the axis letter stands on its own (between
    separators, or at an end) and a minus or plus word is also in it.
    """
    import re
    found = {}
    for axis, _, _ in SPLIT_AXES.get(slot, []):
        letter = re.compile(r'(^|[^a-z0-9])' + axis + r'($|[^a-z0-9])')
        pair = {'minus': '', 'plus': ''}
        for name in names:
            low = name.lower()
            if not letter.search(low):
                continue
            if re.search(r'minus|neg(ative)?\b|(^|[_\s])m($|[_\s])', low) \
                    and not pair['minus']:
                pair['minus'] = name
            elif re.search(r'plus|pos(itive)?\b|(^|[_\s])p($|[_\s])', low) \
                    and not pair['plus']:
                pair['plus'] = name
        found[axis] = pair
    return found


def seed_profile(slot, settings, length_names, all_names=None):
    """A first profile for a family: today's settings where they fit, else
    a guess from the parameter names.

    Starting from the settings means a family that already works keeps
    working when its profile is first opened -- the guess only fills roles
    whose current parameter the family does not have.
    """
    all_names = list(all_names or length_names)
    shape = settings.get(SHAPE_KEY.get(slot, ''), '') or default_shape(slot)
    if shape not in SLOT_SHAPES[slot]:
        shape = default_shape(slot)
    profile = {'shape': shape,
               'radius': settings.get(RADIUS_KEY.get(slot, ''), '') == 'yes',
               'roles': {}}
    taken = []
    for shape_option in SLOT_SHAPES[slot]:
        for role in roles_for(slot, shape_option):
            key, _, _, setting, kind, _, _ = role
            if key in profile['roles']:
                continue
            names = length_names if kind == 'length' else all_names
            current = settings.get(setting, '') or ''
            if current and (not names or current in names):
                value = current
            else:
                value = _guess(key, names, taken)
            profile['roles'][key] = value
            if value:
                taken.append(value)
    # a family built on Minus / Plus pairs, with no standard sizes to speak
    # of, starts out as one
    profile['drive'] = STANDARD
    if slot in SPLIT_AXES:
        profile['split'] = guess_split(slot, length_names)
        needed = [r[0] for r in roles_for(slot, shape) if r[6]]
        # the axes that decide it: the required ones, or -- for a round
        # family, whose only required size is its diameter -- all of them
        deciding = [(axis, role) for axis, _, role in SPLIT_AXES[slot]
                    if role in needed] or \
            [(axis, role) for axis, _, role in SPLIT_AXES[slot]]
        pairs_complete = all(
            profile['split'][axis]['minus'] and profile['split'][axis]['plus']
            for axis, _ in deciding)
        standard_missing = any(not profile['roles'].get(role)
                               for _, role in deciding)
        if pairs_complete and standard_missing:
            profile['drive'] = SPLIT
            # the guessed standard names would be wrong for those sizes;
            # anything a pair does not cover, like a diameter, is kept
            for _, role in deciding:
                profile['roles'][role] = ''

    # a round size found under a radius name is a radius
    dia = profile['roles'].get('diameter', '')
    if dia and 'radius' in dia.lower() and not settings.get(
            RADIUS_KEY.get(slot, ''), ''):
        profile['radius'] = True
    return profile


def problems(slot, profile, length_names=None):
    """What would stop this profile sizing the family. Empty means fine."""
    split = profile.get('drive') == SPLIT and slot in SPLIT_AXES
    found = split_problems(slot, profile, length_names) if split else []
    bad_clearance = clearance_problem(profile.get('clearance_mm'))
    if bad_clearance:
        found.append(bad_clearance)
    # in X+ / X- mode the pairs take over their sizes; the rest -- a round
    # family's diameter -- is still checked as usual
    skip = axis_roles(slot) if split else set()
    shape = profile.get('shape') or default_shape(slot)
    roles = profile.get('roles') or {}
    used = {}
    for key, label, _, _, kind, _, required in roles_for(slot, shape):
        if key in skip:
            continue
        value = roles.get(key, '')
        if required and not value:
            found.append('{} has no parameter'.format(label))
            continue
        if not value:
            continue
        if length_names and kind == 'length' and value not in length_names:
            found.append('{} uses "{}", which this family does not have'
                         .format(label, value))
        if kind == 'length' and key in ('through', 'across', 'height',
                                        'diameter', 'plan_x', 'plan_y'):
            if value in used:
                found.append('{} and {} both use "{}"'.format(
                    used[value], label, value))
            else:
                used[value] = label
    return found


def split_problems(slot, profile, length_names=None):
    found = []
    split = profile.get('split') or {}
    if not any((split.get(axis) or {}).get('minus')
               and (split.get(axis) or {}).get('plus')
               for axis, _, _ in SPLIT_AXES[slot]):
        found.append('No Minus / Plus pair is set - choose one, or use '
                     'Standard')
    needed = [r[0] for r in roles_for(slot, default_shape(slot)) if r[6]]
    used = {}
    for axis, label, role in SPLIT_AXES[slot]:
        pair = split.get(axis) or {}
        minus, plus = pair.get('minus', ''), pair.get('plus', '')
        if not minus and not plus:
            if role in needed:
                found.append('{} has no Minus / Plus pair'.format(label))
            continue
        if not minus or not plus:
            found.append('{} needs both a Minus and a Plus parameter'.format(
                label))
            continue
        sides = (('Minus', minus), ('Plus', plus))
        if minus == plus:
            found.append('{} uses "{}" for both sides'.format(label, minus))
            sides = (('Minus', minus),)
        for side, name in sides:
            if length_names and name not in length_names:
                found.append('{} {} uses "{}", which this family does not '
                             'have'.format(label, side, name))
            if name in used:
                found.append('{} and {} both use "{}"'.format(
                    used[name], label, name))
            else:
                used[name] = label
    return found


def overlay(settings, slot, profiles):
    """Settings with the slot's chosen family profile written over them.

    Returns a new dict; the one passed in is not changed. No saved profile
    for the family means the settings come back as they were.
    """
    out = dict(settings)
    family = settings.get(slot_family_key(slot), '')
    profile = (profiles or {}).get(family)
    if not family or not profile:
        return out
    shape = profile.get('shape') or default_shape(slot)
    roles = profile.get('roles') or {}
    for key, _, _, setting, _, shapes, _ in ROLES[slot]:
        if shape in shapes and key in roles:
            out[setting] = roles[key] or ''
    if profile.get('drive') == SPLIT and slot in SPLIT_AXES:
        # each complete pair takes over its axis's size, as one name the
        # core's writer splits in half
        split = profile.get('split') or {}
        setting_of = dict((r[0], r[3]) for r in ROLES[slot])
        for axis, _, role in SPLIT_AXES[slot]:
            pair = split.get(axis) or {}
            if pair.get('minus') and pair.get('plus'):
                out[setting_of[role]] = encode_split(pair['minus'],
                                                     pair['plus'])
    # read by Global Placement, which keeps its own workset step
    out['family_workset'] = profile_workset(profile)
    own = clearance_value(profile.get('clearance_mm'))
    out['family_clearance'] = '' if own is None else '{:g}'.format(own)
    if slot in SHAPE_KEY:
        out[SHAPE_KEY[slot]] = shape
    if slot in RADIUS_KEY:
        out[RADIUS_KEY[slot]] = 'yes' if profile.get('radius') else 'no'
    return out


# -- workset ----------------------------------------------------------------
# A family can name the workset its BWICs go on. Empty follows the workset
# chosen in Settings, as before; ACTIVE_WORKSET places on whichever workset
# is active, whatever Settings says.
FOLLOW_SETTINGS = ''
ACTIVE_WORKSET = '<active>'
FOLLOW_LABEL = 'As Settings'
ACTIVE_LABEL = '<active workset>'


# -- clearance ----------------------------------------------------------------
# A family can carry its own clearance each side, in mm. Blank follows the
# tab: the clearance on a rectangular tab, the gap on a circular one.
# every family starts at this until its Family settings say otherwise
DEFAULT_CLEARANCE_MM = 50.0


def clearance_value(text):
    """A clearance typed in Family settings: a number of mm, 0 or more, or
    None for blank or anything that is not one."""
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    if value < 0 or value != value:
        return None
    return value


def family_clearance(family, profiles):
    """The family's own clearance in mm, or None to follow the tab."""
    profile = (profiles or {}).get(family or '') or {}
    return clearance_value(profile.get('clearance_mm'))


def clearance_for(family, profiles, default_mm=DEFAULT_CLEARANCE_MM):
    own = family_clearance(family, profiles)
    return default_mm if own is None else own


def clearance_problem(text):
    # never saved (a profile from before 2.18): the 50 mm default applies
    if text is None:
        return None
    if not str(text).strip():
        return 'Clearance is needed - a number of mm each side'
    if clearance_value(text) is None:
        return 'Clearance must be a number of mm, 0 or more'
    return None


def is_set(family, profiles):
    """True once a family's Family settings have been saved -- the tool will
    not place or resize with a family until they have."""
    return bool(family) and bool((profiles or {}).get(family))


def set_first(names, profiles):
    """Family names with those already set up first, each lot in order."""
    ready = [n for n in names if is_set(n, profiles)]
    rest = [n for n in names if not is_set(n, profiles)]
    return sorted(ready, key=lambda n: n.lower()) + rest


def profile_worksets(profile):
    """The workset of each sub tab: {STANDARD: choice, SPLIT: choice}.

    Profiles saved by 2.15.0 had one workset for the whole family; it is
    taken as the workset of both sub tabs."""
    profile = profile or {}
    old = profile.get('workset') or FOLLOW_SETTINGS
    saved = profile.get('worksets') or {}
    return dict((drive, saved.get(drive, old) or FOLLOW_SETTINGS)
                for drive in (STANDARD, SPLIT))


def profile_workset(profile):
    """The workset in use: the one of the sub tab the family is set to."""
    profile = profile or {}
    drive = SPLIT if profile.get('drive') == SPLIT else STANDARD
    return profile_worksets(profile)[drive]


def family_workset(family, profiles):
    """The workset choice for a family: a name, ACTIVE_WORKSET, or
    FOLLOW_SETTINGS when it has none."""
    return profile_workset((profiles or {}).get(family or ''))


def workset_choice(family_choice, settings_name):
    """The workset to place on, by name, or None for the active workset.

    The family's choice wins; with none, the Settings workset applies."""
    if family_choice == ACTIVE_WORKSET:
        return None
    if family_choice:
        return family_choice
    return settings_name or None


def workset_label(choice):
    if choice == ACTIVE_WORKSET:
        return ACTIVE_LABEL
    return choice or FOLLOW_LABEL


def summary(slot, profile):
    """One line naming the size parameters, for under the family card."""
    if not profile:
        return 'No family settings saved yet -- using the defaults.'
    line = size_summary(slot, profile)
    clearance = clearance_value(profile.get('clearance_mm'))
    if clearance is not None:
        line = u'{} \u00b7 Clearance {:g} mm'.format(line, clearance)
    workset = profile_workset(profile)
    if workset:
        line = u'{} \u00b7 Workset: {}'.format(line, workset_label(workset))
    return line


def size_summary(slot, profile):
    split_mode = profile.get('drive') == SPLIT and slot in SPLIT_AXES
    pairs = []
    if split_mode:
        split = profile.get('split') or {}
        for axis, label, _ in SPLIT_AXES[slot]:
            pair = split.get(axis) or {}
            if pair.get('minus') and pair.get('plus'):
                pairs.append('{} {} + {}'.format(
                    axis.upper(), pair['minus'], pair['plus']))
        if SLOT_SHAPES[slot] == (RECT,):
            return '{}: {}'.format(SPLIT_LABEL[slot],
                                   ', '.join(pairs) or 'no pairs set')
    skip = axis_roles(slot) if split_mode else set()
    shape = profile.get('shape') or default_shape(slot)
    roles = profile.get('roles') or {}
    parts = []
    for key, label, _, _, _, _, required in roles_for(slot, shape):
        if key in skip:
            continue
        if required or key == 'through':
            value = roles.get(key, '') or '-'
            if key == 'diameter':
                label = 'Radius' if profile.get('radius') else 'Diameter'
            parts.append('{} {}'.format(label, value))
    lead = 'Round' if shape == CIRC else 'Rectangular'
    if split_mode:
        lead = '{}, {}'.format(lead, SPLIT_LABEL[slot])
    return '{}: {}'.format(lead, ', '.join(parts + pairs))


def slot_for_family(family, context, settings, profile=None,
                    length_names=None):
    """Which slot an existing BWIC's family belongs to, for a resize.

    context is 'wall' or 'slab'. A family chosen on one of the tabs is that
    slot. Otherwise its saved profile says round or rectangular, and failing
    that its own parameters do: a diameter or radius and nothing that reads
    as a width means round.
    """
    slots = ['wall', 'wall_circ'] if context == 'wall' \
        else ['slab_rect', 'slab_circ']
    for slot in slots:
        if family and settings.get(slot_family_key(slot)) == family:
            return slot
    shape = (profile or {}).get('shape')
    if shape not in (RECT, CIRC) and length_names:
        low = [n.lower() for n in length_names]
        round_size = any('diameter' in n or 'radius' in n for n in low)
        width = any('width' in n for n in low) or bool(
            guess_split('wall', length_names)['x']['minus'])
        shape = CIRC if round_size and not width else RECT
    return slots[1] if shape == CIRC else slots[0]


def settings_for_family(family, context, settings, profiles,
                        length_names=None):
    """(slot, settings, saved?) for resizing a BWIC of this family.

    Its saved Family settings when it has them. Otherwise a profile guessed
    from its own parameters, starting from today's settings -- so a family
    that already works keeps its names, and one that was never set up is
    still sized by the parameters it actually has.
    """
    saved = (profiles or {}).get(family)
    slot = slot_for_family(family, context, settings, saved, length_names)
    values = dict(settings)
    values[slot_family_key(slot)] = family
    profile = saved or seed_profile(slot, values, length_names or [])
    return slot, overlay(values, slot, {family: profile}), bool(saved)


def round_hole_mm(outer_mm, span_a_mm, span_b_mm, gap_mm, step_mm):
    """Diameter of a round hole through a wall, in mm.

    A single pipe is set out from its real outside diameter. Anything else --
    a group, or a service with no diameter -- gets the circle that encloses its
    cross-section: the rectangle's diagonal, since a circle only as wide as
    the rectangle's longer side would cut its corners off. Then the gap on
    every side, rounded up to the step.
    """
    import math
    base = outer_mm if outer_mm else math.hypot(span_a_mm, span_b_mm)
    raw = base + 2.0 * gap_mm
    step = step_mm if step_mm and step_mm > 0 else 1.0
    return math.ceil(raw / step - 1e-9) * step


def round_value(diameter, radius):
    """What a round size parameter is given: the diameter or half of it."""
    return diameter / 2.0 if radius else diameter


# ---------------------------------------------------------------------------
# file
# ---------------------------------------------------------------------------
def load(path):
    """Every saved profile, by family name. Missing or damaged gives {}."""
    try:
        if not op.isfile(path):
            return {}
        with io.open(path, encoding='utf-8') as handle:
            data = json.loads(handle.read() or '{}')
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(path, profiles):
    """Write every profile, through a temporary file so a crash mid write
    cannot leave a half file that loses them all."""
    folder = op.dirname(path)
    if folder and not op.isdir(folder):
        os.makedirs(folder)
    text = json.dumps(profiles, indent=2, sort_keys=True)
    temp = path + '.tmp'
    with io.open(temp, 'w', encoding='utf-8') as handle:
        handle.write(u'{}'.format(text))
    if op.isfile(path):
        os.remove(path)
    os.rename(temp, path)
