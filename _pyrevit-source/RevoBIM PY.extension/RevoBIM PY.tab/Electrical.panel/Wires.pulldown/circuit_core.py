# -*- coding: utf-8 -*-
"""RevoBIM PY - Wires: circuits.

Finds circuited fittings in the active view, works out the order to run the
wires in, draws them as arcs between fitting centres, points the home run at
the switch where there is one, and tags one wire per circuit.

Written for IronPython 2.7 and IronPython 3, Revit 2024 - 2027.
"""

import math

import clr

for _asm in ('RevitAPI', 'RevitAPIUI', 'System', 'System.Core', 'mscorlib'):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    XYZ, Line, ElementId, BuiltInParameter, Reference,
    FilteredElementCollector, ElementMulticategoryFilter, BuiltInCategory,
    Transaction, SubTransaction, TransactionGroup,
    IndependentTag, TagMode, TagOrientation,
)
from Autodesk.Revit.DB.Electrical import Wire, ElectricalSystem

import wires_core as core


# ---------------------------------------------------------------------------
# Switch systems
# ---------------------------------------------------------------------------
SWITCH_PARAM_NAMES = ('Switch ID', 'Switch Id', 'SwitchID', 'BGL_Switch ID')


def switch_id_of(element):
    """The switch system a fitting belongs to, as a string key.

    Which route answers varies with how the model was set up, so all of them
    are tried and the first non-empty answer wins. An empty string means the
    fitting is on no switch system, which is a legitimate answer and is
    treated as its own group.
    """
    # 1. a switch-typed electrical system the element is a member of
    try:
        from Autodesk.Revit.DB.Electrical import ElectricalSystemType
        switch_kind = getattr(ElectricalSystemType, 'Switch', None)
        if switch_kind is not None:
            for circuit in core.element_circuits(element):
                try:
                    if circuit.SystemType == switch_kind:
                        return 'sys:{0}'.format(core.eid_value(circuit.Id))
                except Exception:
                    pass
    except Exception:
        pass

    # 2. the built-in Switch ID parameter
    try:
        bip = getattr(BuiltInParameter, 'RBS_ELEC_SWITCH_ID_PARAM', None)
        if bip is not None:
            param = element.get_Parameter(bip)
            if param is not None:
                value = param.AsString()
                if value and value.strip():
                    return 'id:' + value.strip()
    except Exception:
        pass

    # 3. a parameter called Switch ID by any of its usual spellings
    for name in SWITCH_PARAM_NAMES:
        try:
            param = element.LookupParameter(name)
            if param is None:
                continue
            value = param.AsString()
            if value is None:
                value = param.AsValueString()
            if value and value.strip():
                return 'id:' + value.strip()
        except Exception:
            pass
    return ''


def switch_id_of_circuit(circuit):
    for name in SWITCH_PARAM_NAMES:
        try:
            param = circuit.LookupParameter(name)
            if param is not None:
                value = param.AsString()
                if value and value.strip():
                    return 'id:' + value.strip()
        except Exception:
            pass
    return ''


def switch_category_ids(settings):
    keys = [k.strip() for k in
            str(settings.get('switch_categories', 'lighting_devices')).split(',')
            if k.strip()]
    wanted = []
    for key, _label, bic_name in core.CATEGORY_DEFS:
        if key in keys:
            bic = core.builtin_category(bic_name)
            if bic is not None:
                wanted.append(bic)
    if not wanted:
        bic = core.builtin_category('OST_LightingDevices')
        if bic is not None:
            wanted.append(bic)
    return wanted


def make_switch_test(settings):
    """Is this element a switch?

    Category first, then the family name, because a switch modelled outside
    Lighting Devices is common enough that a category-only test would miss it
    and the tool would then draw the home run back to the panel.
    """
    values = _category_id_values(switch_category_ids(settings))

    def is_switch(element):
        if element is None:
            return False
        try:
            if core.eid_value(element.Category.Id) in values:
                return True
        except Exception:
            pass
        try:
            label = element.Symbol.Family.Name.lower()
            if 'switch' in label:
                return True
        except Exception:
            pass
        try:
            return 'switch' in element.Category.Name.lower()
        except Exception:
            return False

    return is_switch


def leg_key(element, doc, settings, cache=None):
    """What decides which leg a fitting belongs to.

    Space and switch system are combined rather than chosen between, so the
    run breaks at either boundary and the span that bridges the break takes
    the permanent live wire type. That is what says "same circuit, different
    switch" whether the difference is which switch or which room.
    """
    parts = []
    if core._settings_bool(settings, 'group_by_space'):
        if cache is None or 'space' not in cache:
            spaces = {}
            if cache is not None:
                cache['space'] = spaces
        else:
            spaces = cache['space']
        key = core.eid_value(element.Id)
        if key not in spaces:
            spaces[key] = core.space_key(element, doc)
        parts.append(spaces[key][0])
    if core._settings_bool(settings, 'group_by_switch'):
        parts.append(switch_id_of(element))
    return '|'.join(parts)


def connected_switch(doc, fixture, is_switch):
    """The switch actually connected to this light, or None.

    Walks the light's own connectors, and one hop further through any wire
    hanging off them - a switch is almost never connected to a fitting
    directly, it is connected through the wire between them.
    """
    for connector in core.electrical_connectors(fixture):
        for owner in core.connected_owners(connector):
            if is_switch(owner):
                return owner, 'connector'
            if core.is_wire(owner):
                for far_connector, _index in core.wire_ends(owner):
                    for far in core.connected_owners(far_connector):
                        if is_switch(far):
                            return far, 'wire'
    # a switch system the light belongs to, whose other members include one
    for circuit in core.element_circuits(fixture):
        try:
            for member in circuit.Elements:
                if is_switch(member):
                    return member, 'switch system'
        except Exception:
            pass
    return None, ''


def find_switch_devices(doc, view, settings):
    """Every switch-ish device in the view, keyed by switch id."""
    keys = str(settings.get('switch_categories', 'lighting_devices'))
    wanted = []
    for key, _label, bic_name in core.CATEGORY_DEFS:
        if key in [k.strip() for k in keys.split(',') if k.strip()]:
            bic = core.builtin_category(bic_name)
            if bic is not None:
                wanted.append(bic)
    if not wanted:
        bic = core.builtin_category('OST_LightingDevices')
        if bic is not None:
            wanted.append(bic)

    devices = {}
    if not wanted:
        return devices
    id_list = List[BuiltInCategory]()
    for bic in wanted:
        id_list.Add(bic)
    try:
        collector = FilteredElementCollector(doc, view.Id)
        collector = collector.WherePasses(ElementMulticategoryFilter(id_list))
        collector = collector.WhereElementIsNotElementType()
        for element in collector:
            key = switch_id_of(element)
            if not key:
                continue
            point = core.element_point(element)
            if point is None:
                continue
            devices.setdefault(key, []).append((element, point))
    except Exception:
        pass
    return devices


# ---------------------------------------------------------------------------
# Circuits in the view
# ---------------------------------------------------------------------------
class CircuitJob(object):
    """One circuit, its members in this view, and what was found about it."""

    def __init__(self, circuit):
        self.circuit = circuit
        self.label = core.circuit_label(circuit)
        self.members = []          # [(element, point)]
        self.offscreen = 0
        self.existing_wires = []
        self.existing_tags = []
        self.switch_key = ''
        self.switch_element = None
        self.switch_point = None
        self.switch_from = None      # the light the switch is connected to
        self.switch_route = ''       # how the switch was found
        self.is_lighting = True
        self.note = ''

    def member_count(self):
        return len(self.members)


def _category_ids(settings, key, fallback):
    keys = [k.strip() for k in str(settings.get(key, fallback)).split(',')
            if k.strip()]
    found = []
    for name, _label, bic_name in core.CATEGORY_DEFS:
        if name in keys:
            bic = core.builtin_category(bic_name)
            if bic is not None:
                found.append(bic)
    return found


def collect_jobs(doc, view, settings, restrict_to=None, want_power=False):
    """Every circuit with a member drawn in this view."""
    lighting = _category_ids(settings, 'lighting_categories', 'lighting_fixtures')
    power = _category_ids(settings, 'power_categories',
                          'electrical_fixtures,electrical_equipment')
    wanted = list(lighting)
    if want_power:
        wanted.extend([bic for bic in power if bic not in wanted])
    if not wanted:
        return []

    lighting_ids = _category_id_values(lighting)

    id_list = List[BuiltInCategory]()
    for bic in wanted:
        id_list.Add(bic)

    in_view = {}
    try:
        collector = FilteredElementCollector(doc, view.Id)
        collector = collector.WherePasses(ElementMulticategoryFilter(id_list))
        collector = collector.WhereElementIsNotElementType()
        for element in collector:
            in_view[core.eid_value(element.Id)] = element
    except Exception:
        pass

    if restrict_to:
        keep = set([core.eid_value(e.Id) for e in restrict_to])
        in_view = dict([(k, v) for k, v in in_view.items() if k in keep])

    jobs = {}
    for element in list(in_view.values()):
        for circuit in core.element_circuits(element):
            key = core.eid_value(circuit.Id)
            job = jobs.get(key)
            if job is None:
                job = CircuitJob(circuit)
                job.is_lighting = _looks_like_lighting(element, lighting_ids)
                jobs[key] = job
            point = core.element_point(element)
            if point is not None:
                job.members.append((element, point))

    # members of those circuits that are not drawn in this view
    for job in jobs.values():
        try:
            total = 0
            for member in job.circuit.Elements:
                total += 1
            job.offscreen = max(0, total - len(job.members))
        except Exception:
            job.offscreen = 0
        job.existing_wires = circuit_wires(doc, view, job.circuit)
    return sorted(jobs.values(), key=lambda job: job.label)


def _category_id_values(categories):
    """Category ids as plain numbers, so a category can be tested without
    touching Category.BuiltInCategory, which is not on every release."""
    values = set()
    for bic in categories:
        try:
            values.add(core.eid_value(ElementId(bic)))
        except Exception:
            pass
    return values


def _looks_like_lighting(element, lighting_ids):
    try:
        if core.eid_value(element.Category.Id) in lighting_ids:
            return True
    except Exception:
        pass
    try:
        return 'light' in element.Category.Name.lower()
    except Exception:
        return True


def circuit_wires(doc, view, circuit):
    """Wires in this view belonging to a circuit."""
    found = []
    try:
        target = core.eid_value(circuit.Id)
        for wire in FilteredElementCollector(doc, view.Id).OfClass(Wire):
            found_circuit = core.wire_circuit(doc, wire)
            if found_circuit is not None and \
                    core.eid_value(found_circuit.Id) == target:
                found.append(wire)
    except Exception:
        pass
    return found


def tags_on(doc, view, elements):
    """Wire tags in the view whose host is one of these elements."""
    found = []
    bic = core.builtin_category('OST_WireTags')
    if bic is None:
        return found
    wanted = set([core.eid_value(e.Id) for e in elements])
    try:
        collector = FilteredElementCollector(doc, view.Id).OfCategory(bic)
        for tag in collector.WhereElementIsNotElementType():
            try:
                for host_id in tag.GetTaggedLocalElementIds():
                    if core.eid_value(host_id) in wanted:
                        found.append(tag)
                        break
                continue
            except Exception:
                pass
            try:
                if core.eid_value(tag.TaggedLocalElementId) in wanted:
                    found.append(tag)
            except Exception:
                pass
    except Exception:
        pass
    return found


# ---------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Keeping clear of fittings that are not on this circuit
# ---------------------------------------------------------------------------
CLASH_SAMPLES = 10


def collect_obstacles(doc, view, settings, cache=None):
    """Every fitting drawn in the view, with a plan radius, read once."""
    if cache is not None and 'obstacles' in cache:
        return cache['obstacles']
    clearance = core.mm(core._settings_float(settings, 'clash_clearance_mm'))
    found = []
    categories = _category_ids(settings, 'lighting_categories',
                               'lighting_fixtures')
    categories.extend([bic for bic in _category_ids(
        settings, 'power_categories',
        'electrical_fixtures,electrical_equipment') if bic not in categories])
    if categories:
        id_list = List[BuiltInCategory]()
        for bic in categories:
            id_list.Add(bic)
        try:
            collector = FilteredElementCollector(doc, view.Id)
            collector = collector.WherePasses(ElementMulticategoryFilter(id_list))
            for element in collector.WhereElementIsNotElementType():
                point = core.element_point(element)
                if point is None:
                    continue
                radius = core.plan_radius(element, view) + clearance
                found.append((core.eid_value(element.Id), point.X, point.Y,
                              radius))
        except Exception:
            pass
    if cache is not None:
        cache['obstacles'] = found
    return found


def obstacles_off_circuit(obstacles, member_ids):
    """The fittings the wire has to keep clear of - everything but its own."""
    return [row for row in obstacles if row[0] not in member_ids]


def span_clashes(point_a, point_b, depth, side, obstacles):
    """How many off-circuit fittings this one span would run across."""
    if not obstacles:
        return 0
    points = core.arc_through(point_a.X, point_a.Y, point_b.X, point_b.Y,
                              depth, side, CLASH_SAMPLES, 0.0)
    mid_x = (point_a.X + point_b.X) / 2.0
    mid_y = (point_a.Y + point_b.Y) / 2.0
    reach = _distance(point_a, point_b) / 2.0 + abs(depth)
    hits = 0
    for _eid, ox, oy, radius in obstacles:
        # coarse reject first: most fittings are nowhere near most spans
        if math.sqrt((ox - mid_x) ** 2 + (oy - mid_y) ** 2) > reach + radius:
            continue
        if not core.polyline_clears(points, ox, oy, radius):
            hits += 1
    return hits


def _distance(a, b):
    return core.plan_distance(a, b)


def _path_length(points):
    total = 0.0
    for index in range(len(points) - 1):
        total += _distance(points[index], points[index + 1])
    return total


def nearest_neighbour(items, start_index):
    """Open path, greedily nearest, from a given start."""
    remaining = list(range(len(items)))
    remaining.remove(start_index)
    order = [start_index]
    while remaining:
        here = items[order[-1]][1]
        best = None
        for index in remaining:
            step = _distance(here, items[index][1])
            if best is None or step < best[1]:
                best = (index, step)
        order.append(best[0])
        remaining.remove(best[0])
    return order


def two_opt(items, order, pin_first=True, rounds=40):
    """Pull crossings out of an open path. The first stop can be pinned."""
    if len(order) < 4:
        return order
    best = list(order)
    improved = True
    guard = 0
    while improved and guard < rounds:
        improved = False
        guard += 1
        for i in range(0 if not pin_first else 0, len(best) - 2):
            for j in range(i + 2, len(best)):
                a = items[best[i]][1]
                b = items[best[i + 1]][1]
                c = items[best[j]][1]
                after = items[best[j + 1]][1] if j + 1 < len(best) else None
                if after is None:
                    gain = _distance(a, b) - _distance(a, c)
                else:
                    gain = (_distance(a, b) + _distance(c, after)) - \
                           (_distance(a, c) + _distance(b, after))
                if gain > 1.0e-6:
                    best[i + 1:j + 1] = list(reversed(best[i + 1:j + 1]))
                    improved = True
    return best


def serpentine(items, along_x=True):
    """Rows across, alternate direction - what a regular grid of lights wants."""
    if not items:
        return []
    values = [point for _element, point in items]
    spread_x = max(p.X for p in values) - min(p.X for p in values)
    spread_y = max(p.Y for p in values) - min(p.Y for p in values)
    band = max(1.0e-6, (spread_y if along_x else spread_x) * 0.18)

    indexed = list(range(len(items)))
    key_major = (lambda i: items[i][1].Y) if along_x else (lambda i: items[i][1].X)
    key_minor = (lambda i: items[i][1].X) if along_x else (lambda i: items[i][1].Y)

    indexed.sort(key=key_major)
    rows = []
    current = []
    anchor = None
    for index in indexed:
        value = key_major(index)
        if anchor is None or abs(value - anchor) <= band:
            if anchor is None:
                anchor = value
            current.append(index)
        else:
            rows.append(current)
            current = [index]
            anchor = value
    if current:
        rows.append(current)

    order = []
    for number, row in enumerate(rows):
        row.sort(key=key_minor, reverse=bool(number % 2))
        order.extend(row)
    return order


def sweep(items):
    """Round the centroid by angle - reads well on a scattered layout."""
    if not items:
        return []
    cx = sum(p.X for _e, p in items) / float(len(items))
    cy = sum(p.Y for _e, p in items) / float(len(items))
    indexed = list(range(len(items)))
    indexed.sort(key=lambda i: math.atan2(items[i][1].Y - cy,
                                          items[i][1].X - cx))
    return indexed


def route_alternatives(items, end_index=None, use_two_opt=True, cost=None):
    """Several orderings of the same fittings, best first.

    Each is a whole-run alternative rather than a nudge, so Shuffle actually
    changes the shape of the run rather than swapping two lights over.
    """
    if len(items) < 2:
        return [list(range(len(items)))]

    seeds = []
    if end_index is not None:
        seeds.append(end_index)
    # the two fittings furthest apart make natural ends of an open run
    far = _extremes(items)
    for index in far:
        if index not in seeds:
            seeds.append(index)
    if 0 not in seeds:
        seeds.append(0)

    orders = []
    for seed in seeds[:3]:
        order = nearest_neighbour(items, seed)
        if use_two_opt:
            order = two_opt(items, order, pin_first=True)
        orders.append(order)

    orders.append(serpentine(items, True))
    orders.append(serpentine(items, False))
    orders.append(sweep(items))

    cleaned = []
    seen = []
    for order in orders:
        if not order or len(order) != len(items):
            continue
        key = ','.join([str(v) for v in order])
        backwards = ','.join([str(v) for v in reversed(order)])
        if key in seen or backwards in seen:
            continue
        seen.append(key)
        cleaned.append(order)

    # the requested end goes last; reverse rather than re-solve
    if end_index is not None:
        fixed = []
        for order in cleaned:
            if order and order[0] == end_index:
                order = list(reversed(order))
            elif order and order[-1] != end_index and end_index in order:
                if order.index(end_index) < len(order) // 2:
                    order = list(reversed(order))
            fixed.append(order)
        cleaned = fixed

    if cost is None:
        cleaned.sort(key=lambda order: _path_length([items[i][1]
                                                     for i in order]))
    else:
        # clashes first, then length - a route that runs over somebody else's
        # light is worse than a route that is a metre longer, however much
        # tidier the short one looks
        cleaned.sort(key=cost)
    return cleaned


def _leg_cost(cost, items, member_indices):
    """Score a leg's own ordering with the whole run's cost function.

    A leg is ordered in its own local index space, so the indices have to be
    mapped back before the cost function - which works on the circuit's
    items - can see them.
    """
    def scored(order):
        return cost([member_indices[i] for i in order])
    return scored


def _extremes(items):
    """The indices of the two fittings furthest apart, cheaply."""
    if len(items) < 2:
        return [0]
    first = 0
    best = -1.0
    for index in range(1, len(items)):
        step = _distance(items[0][1], items[index][1])
        if step > best:
            best = step
            first = index
    second = 0
    best = -1.0
    for index in range(len(items)):
        step = _distance(items[first][1], items[index][1])
        if step > best:
            best = step
            second = index
    return [first, second]


def grouped_route(items, keys, end_index=None, use_two_opt=True, variant=0,
                  cost=None):
    """Chain each switch group, then join the groups end to end.

    Returns (order, crossings, options) where crossings holds the positions
    in the order at which the run steps from one switch group to the next -
    those are the segments that take the permanent live wire type - and
    options is how many genuinely different routes exist, so Shuffle can say
    "route 2 of 4" honestly rather than cycling through repeats.
    """
    groups = {}
    for index, key in enumerate(keys):
        groups.setdefault(key, []).append(index)

    if len(groups) < 2:
        options = route_alternatives(items, end_index, use_two_opt, cost)
        order = options[variant % len(options)] if options else []
        return order, [], max(1, len(options))

    # order within each group
    legs = []
    option_count = 1
    for key in groups:
        member_items = [items[i] for i in groups[key]]
        local_end = None
        if end_index is not None and end_index in groups[key]:
            local_end = groups[key].index(end_index)
        local_cost = None
        if cost is not None:
            local_cost = _leg_cost(cost, items, groups[key])
        options = route_alternatives(member_items, local_end, use_two_opt,
                                     local_cost)
        chosen = options[variant % len(options)] if options else \
            list(range(len(member_items)))
        option_count = max(option_count, len(options))
        legs.append((key, [groups[key][i] for i in chosen]))

    # order the legs, nearest end to nearest end, ending on the leg that holds
    # the fitting the home run leaves from
    final_leg = None
    if end_index is not None:
        for position, (_key, leg) in enumerate(legs):
            if end_index in leg:
                final_leg = position
                break

    remaining = list(range(len(legs)))
    chain = []
    if final_leg is not None:
        # build backwards from the final leg so it lands last
        chain.append(final_leg)
        remaining.remove(final_leg)
        while remaining:
            head = items[legs[chain[0]][1][0]][1]
            best = None
            for position in remaining:
                tail = items[legs[position][1][-1]][1]
                nose = items[legs[position][1][0]][1]
                for candidate, flip in ((tail, False), (nose, True)):
                    step = _distance(head, candidate)
                    if best is None or step < best[1]:
                        best = (position, step, flip)
            position, _step, flip = best
            if flip:
                legs[position] = (legs[position][0],
                                  list(reversed(legs[position][1])))
            chain.insert(0, position)
            remaining.remove(position)
    else:
        chain.append(remaining.pop(0))
        while remaining:
            tail = items[legs[chain[-1]][1][-1]][1]
            best = None
            for position in remaining:
                nose = items[legs[position][1][0]][1]
                back = items[legs[position][1][-1]][1]
                for candidate, flip in ((nose, False), (back, True)):
                    step = _distance(tail, candidate)
                    if best is None or step < best[1]:
                        best = (position, step, flip)
            position, _step, flip = best
            if flip:
                legs[position] = (legs[position][0],
                                  list(reversed(legs[position][1])))
            chain.append(position)
            remaining.remove(position)

    order = []
    crossings = []
    for position in chain:
        if order:
            crossings.append(len(order) - 1)
        order.extend(legs[position][1])
    return order, crossings, option_count


# ---------------------------------------------------------------------------
# Placing
# ---------------------------------------------------------------------------
def _free_connector(element, wire_system_type=None):
    for connector in core.electrical_connectors(element):
        return connector
    return None


def _sag_setting(settings):
    """The arc depth number, in whichever unit the mode is asking for."""
    if str(settings.get('arc_sag_mode', 'span')).strip().lower() == 'paper':
        return core._settings_float(settings, 'arc_sag_paper_mm')
    return core._settings_float(settings, 'arc_sag_percent')


def place_segment(doc, view, settings, element_a, point_a, element_b, point_b,
                  wire_type, plane_z, sag, side, mid_count=None,
                  sag_mode=None, wiring=None):
    """One wire between two fittings, trimmed back from both symbols."""
    dx = point_b.X - point_a.X
    dy = point_b.Y - point_a.Y
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1.0e-9:
        return None, 'the two fittings sit on the same point'
    direction = (dx / length, dy / length)

    if str(settings.get('trim_from', 'extent')).strip().lower() == 'fixed':
        fixed = core.paper(view,
                           core._settings_float(settings, 'trim_fixed_paper_mm'))
        trim_a = fixed
        trim_b = fixed
    else:
        trim_a, _ca = core.trim_distance(view, settings, element_a, direction,
                                         length)
        trim_b, _cb = core.trim_distance(view, settings, element_b, direction,
                                         length)

    if mid_count is None:
        mid_count = core._settings_float(settings, 'mid_vertices')
    if sag_mode is None:
        sag_mode = settings.get('arc_sag_mode', 'span')
    # the depth is resolved against this span, so a share of the span means a
    # share of *this* span rather than of the run as a whole
    depth = core.sagitta(view, sag_mode, sag, max(1.0e-9, length - trim_a - trim_b))
    points = core.segment_points(
        point_a, point_b, plane_z, depth, side, trim_a, trim_b, mid_count,
        wiring or settings.get('wiring_type', 'arc'),
        core._settings_float(settings, 'chamfer_angle_deg'))
    if not points:
        return None, 'the segment came out with no length'

    connector_a = _free_connector(element_a)
    connector_b = _free_connector(element_b)
    if connector_a is None or connector_b is None:
        return None, 'one of the fittings has no electrical connector'

    vertex_list = List[XYZ]()
    for point in points:
        vertex_list.Add(point)

    kind = core.wiring_kind(wiring)

    try:
        wire = Wire.Create(doc, wire_type.Id, view.Id, kind, vertex_list,
                           connector_a, connector_b)
    except Exception as error:
        return None, 'Revit refused the wire ({0})'.format(error)
    if wire is None:
        return None, 'Revit returned no wire'

    # Revit may re-seat the ends on the connectors, which undoes the trim.
    # Push them back and read the connection afterwards rather than assume.
    trimmed = _retrim(wire, points)
    return wire, ('' if trimmed else 'trim was refused, so the wire ends sit '
                                     'on the connectors rather than short of '
                                     'the symbol - Revit seats a connected '
                                     'wire end on its connector')


def _retrim(wire, points):
    """Push the vertices back where they were asked for.

    Revit does not always keep the vertex list it was given - it may seat the
    ends on the connectors and it may change the count. An earlier version
    gave up entirely on a count mismatch and reported the trim refused, which
    is what produced seventeen identical lines in one report. The ends are
    what the trim is about, so they are set by index whatever the count came
    back as, and only a refusal from Revit itself counts as a refusal.
    """
    current = core.wire_vertices(wire)
    if len(current) < 2 or len(points) < 2:
        return False

    if len(current) == len(points):
        pairs = [(index, points[index]) for index in range(len(points))]
    else:
        # the counts disagree, so align what the trim is actually about
        pairs = [(0, points[0]), (len(current) - 1, points[-1])]

    refused = False
    for index, target in pairs:
        if index >= len(current):
            continue
        if core.plan_distance(current[index], target) <= core.mm(0.5):
            continue
        try:
            wire.SetVertex(index, target)
        except Exception:
            refused = True
    return not refused


def place_home_run(doc, view, settings, element, point, target_point,
                   wire_type, plane_z, sag, side, target_element=None,
                   wiring=None):
    """From the light toward the switch.

    Two shapes. **arrow** (default) is a short wire leaving the light in the
    direction of the switch and stopping well short of it - connected at the
    light end only, which is the condition Revit itself draws a home run
    arrowhead for, so the arrow is Revit's own rather than something invented
    here. **full** runs the wire all the way and connects into the switch,
    which is a switch leg rather than a home run.
    """
    dx = target_point.X - point.X
    dy = target_point.Y - point.Y
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1.0e-9:
        return None, 'the switch sits on the fitting'
    direction = (dx / length, dy / length)
    gap = core.paper(view, core._settings_float(settings, 'trim_gap_paper_mm'))
    trim_a, _capped = core.trim_distance(view, settings, element, direction,
                                         length)
    mids = core._settings_float(settings, 'mid_vertices')

    arrow = str(settings.get('home_run_style', 'arrow')).strip().lower() != 'full'

    if arrow:
        # always one middle vertex, whatever the general setting is - the
        # whole point of the arrow is that it arcs toward the switch, and it
        # is far too short for more than one to read
        mids = 1
        reach = core.paper(
            view, core._settings_float(settings, 'home_run_arrow_paper_mm'))
        # never overshoot the switch it is pointing at
        reach = min(reach, max(0.0, length - trim_a - gap))
        if reach <= 0.0:
            return None, 'the switch is too close for an arrow'
        finish = XYZ(point.X + direction[0] * (trim_a + reach),
                     point.Y + direction[1] * (trim_a + reach),
                     plane_z)
        depth = core.sagitta(view, settings.get('arc_sag_mode', 'span'),
                             sag, max(1.0e-9, reach))
        points = core.segment_points(point, finish, plane_z, depth, side,
                                     trim_a, 0.0, mids,
                                     wiring or settings.get('wiring_type', 'arc'),
                                     core._settings_float(settings,
                                                          'chamfer_angle_deg'))
        connector_b = None
        target_element = None
    else:
        trim_b = gap
        if target_element is not None:
            trim_b, _cb = core.trim_distance(view, settings, target_element,
                                             direction, length)
        depth = core.sagitta(view, settings.get('arc_sag_mode', 'span'), sag,
                             max(1.0e-9, length - trim_a - trim_b))
        points = core.segment_points(point, target_point, plane_z, depth, side,
                                     trim_a, trim_b, mids,
                                     wiring or settings.get('wiring_type', 'arc'),
                                     core._settings_float(settings,
                                                          'chamfer_angle_deg'))
        connector_b = _free_connector(target_element) \
            if target_element is not None else None

    if not points:
        return None, 'the home run came out with no length'

    connector_a = _free_connector(element)

    vertex_list = List[XYZ]()
    for item in points:
        vertex_list.Add(item)
    kind = core.wiring_kind(wiring)

    for pair in ((connector_a, connector_b), (connector_a, None)):
        try:
            wire = Wire.Create(doc, wire_type.Id, view.Id, kind, vertex_list,
                               pair[0], pair[1])
        except Exception:
            wire = None
        if wire is not None:
            _retrim(wire, points)
            if pair[1] is None and connector_b is not None:
                return wire, ('the switch would not take the wire, so the '
                              'home run is a stub')
            return wire, ''
    return None, 'Revit refused the home run'


def place_switch_line(doc, view, settings, light, light_point,
                      switch, switch_point, cache=None):
    """A detail line from the light fitting to the lighting device.

    Straight and view-specific, on a line style of your choosing, so it reads
    as the drawn convention it is rather than as another wire. Trimmed off
    both symbols the same way the wires are.
    """
    dx = switch_point.X - light_point.X
    dy = switch_point.Y - light_point.Y
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1.0e-9:
        return None, 'the switch sits on the light'
    direction = (dx / length, dy / length)
    trim_a, _ca = core.trim_distance(view, settings, light, direction, length)
    trim_b, _cb = core.trim_distance(view, settings, switch, direction, length)
    if trim_a + trim_b >= length:
        share = length * 0.45
        trim_a = min(trim_a, share)
        trim_b = min(trim_b, share)

    plane_z = core.drawing_plane_z(doc, view)
    start = XYZ(light_point.X + direction[0] * trim_a,
                light_point.Y + direction[1] * trim_a, plane_z)
    finish = XYZ(switch_point.X - direction[0] * trim_b,
                 switch_point.Y - direction[1] * trim_b, plane_z)

    try:
        curve = doc.Create.NewDetailCurve(view, Line.CreateBound(start, finish))
    except Exception as error:
        return None, 'Revit refused the detail line ({0})'.format(error)
    if curve is None:
        return None, 'Revit returned no detail line'

    wanted = settings.get('switch_line_style', '')
    if wanted:
        style = core.find_line_style(doc, wanted, cache)
        if style is None:
            return curve, 'line style "{0}" is not in this model, so the ' \
                          'line is on the view default'.format(wanted)
        try:
            curve.LineStyle = style
        except Exception:
            return curve, 'the line style would not be set'
    return curve, ''


def remove_panel_home_runs(doc, wires, keep_ids=None):
    """Delete wires connected at one end only - Revit's panel home runs."""
    keep = set(keep_ids or [])
    removed = 0
    for wire in wires:
        try:
            if core.eid_value(wire.Id) in keep:
                continue
            connected = 0
            for connector, _index in core.wire_ends(wire):
                if not core.connector_is_free(connector):
                    connected += 1
            if connected == 1:
                doc.Delete(wire.Id)
                removed += 1
        except Exception:
            pass
    return removed


def _tag_offset(view, settings):
    """How far off the wire the tag sits, in feet."""
    value = core._settings_float(settings, 'tag_offset_mm')
    if core._settings_bool(settings, 'tag_offset_is_paper'):
        return core.paper(view, value)
    return core.mm(value)


def place_tag(doc, view, settings, wire, tag_type):
    """One tag, offset square to the wire it sits on."""
    if tag_type is None or wire is None:
        return None
    points = core.wire_vertices(wire)
    if len(points) < 2:
        return None
    first = points[0]
    last = points[-1]
    mid_x = (first.X + last.X) / 2.0
    mid_y = (first.Y + last.Y) / 2.0
    dx = last.X - first.X
    dy = last.Y - first.Y
    length = math.sqrt(dx * dx + dy * dy)
    offset = _tag_offset(view, settings)
    if length > 1.0e-9:
        mid_x += (-dy / length) * offset
        mid_y += (dx / length) * offset
    point = XYZ(mid_x, mid_y, first.Z)

    leader = core._settings_bool(settings, 'tag_leader')
    try:
        if not tag_type.IsActive:
            tag_type.Activate()
            doc.Regenerate()
    except Exception:
        pass

    reference = None
    try:
        reference = Reference(wire)
    except Exception:
        reference = None

    if reference is not None:
        try:
            tag = IndependentTag.Create(doc, tag_type.Id, view.Id, reference,
                                        leader, TagOrientation.Horizontal, point)
            return tag
        except Exception:
            pass
        try:
            tag = IndependentTag.Create(doc, view.Id, reference, leader,
                                        TagMode.TM_ADDBY_CATEGORY,
                                        TagOrientation.Horizontal, point)
            if tag is not None:
                try:
                    tag.ChangeTypeId(tag_type.Id)
                except Exception:
                    pass
                return tag
        except Exception:
            pass
    try:
        tag = doc.Create.NewTag(view, wire, leader, TagMode.TM_ADDBY_CATEGORY,
                                TagOrientation.Horizontal, point)
        if tag is not None:
            try:
                tag.ChangeTypeId(tag_type.Id)
            except Exception:
                pass
        return tag
    except Exception:
        return None


# ---------------------------------------------------------------------------
# One circuit, start to finish
# ---------------------------------------------------------------------------
class Placement(object):
    """What one run of one circuit produced, so Shuffle can replace it."""

    def __init__(self, job):
        self.job = job
        self.wires = []
        self.extras = []          # detail lines and anything else drawn
        self.tag = None
        self.info = []            # said for the record, never a dialog
        self.variant = 0
        self.options = 1
        self.flipped = 0
        self.clashing = 0
        self.notes = []
        self.length = 0.0


def wire_one_circuit(doc, view, settings, job, switches, variant=0,
                     cache=None, vertex_override=None, sag_override=None,
                     avoid_override=None, wiring_override=None):
    """Draw one circuit at the given route variant. Inside a transaction."""
    result = Placement(job)
    result.variant = variant

    items = job.members
    if len(items) < 2 and job.switch_element is None:
        result.notes.append('{0}: only one fitting in this view, nothing to '
                            'draw between.'.format(job.label))
        return result

    limit = int(core._settings_float(settings, 'max_members') or 200)
    if len(items) > limit:
        result.notes.append('{0}: {1} fittings, over the {2} limit.'.format(
            job.label, len(items), limit))
        return result

    plane_z = core.drawing_plane_z(doc, view)
    sag_mode = settings.get('arc_sag_mode', 'span')
    if sag_override is None:
        sag = _sag_setting(settings)
    else:
        sag = float(sag_override)
    side = settings.get('arc_side', 'left')
    wiring = wiring_override or settings.get('wiring_type', 'arc')

    if cache is None:
        cache = {}
    if job.is_lighting:
        wire_type = core.find_wire_type(
            doc, settings.get('lighting_wire_type', ''), cache)
    else:
        wire_type = core.find_wire_type(
            doc, settings.get('power_wire_type', ''), cache)
    live_type = core.find_wire_type(
        doc, settings.get('lighting_live_wire_type', ''), cache)
    emergency_type = core.find_wire_type(
        doc, settings.get('lighting_emergency_wire_type', ''), cache)
    if wire_type is None:
        result.notes.append(
            '{0}: not drawn - no wire type could be found in this model. '
            'Check the Lighting tab in Settings.'.format(job.label))
        return result

    # where the run should finish
    end_index = None
    if job.switch_point is not None and \
            core._settings_bool(settings, 'end_chain_at_switch'):
        # the light the switch is actually wired to wins over the nearest one
        if job.switch_from is not None:
            for index, (element, _point) in enumerate(items):
                if core.same_id(element.Id, job.switch_from.Id):
                    end_index = index
                    break
        if end_index is None:
            best = None
            for index, (_element, point) in enumerate(items):
                step = _distance(point, job.switch_point)
                if best is None or step < best[1]:
                    best = (index, step)
            if best is not None:
                end_index = best[0]

    # what the run has to keep clear of: every fitting in the view that is
    # not a member of this circuit
    if avoid_override is None:
        avoiding = core._settings_bool(settings, 'avoid_fittings')
    else:
        avoiding = bool(avoid_override)
    obstacles = []
    if avoiding:
        member_ids = set()
        for element, _point in items:
            member_ids.add(core.eid_value(element.Id))
        obstacles = obstacles_off_circuit(
            collect_obstacles(doc, view, settings, cache), member_ids)

    def span_depth(point_a, point_b):
        return core.sagitta(view, sag_mode, sag,
                            max(1.0e-9, _distance(point_a, point_b)))

    def route_cost(order):
        length = 0.0
        clashes = 0
        for position in range(len(order) - 1):
            point_a = items[order[position]][1]
            point_b = items[order[position + 1]][1]
            length += _distance(point_a, point_b)
            if obstacles:
                clashes += span_clashes(point_a, point_b,
                                        span_depth(point_a, point_b), side,
                                        obstacles)
        return (clashes, length)

    cost = route_cost if obstacles else None

    use_two_opt = core._settings_bool(settings, 'two_opt')
    if core._settings_bool(settings, 'group_by_switch') or \
            core._settings_bool(settings, 'group_by_space'):
        keys = [leg_key(element, doc, settings, cache)
                for element, _point in items]
        order, crossings, option_count = grouped_route(
            items, keys, end_index, use_two_opt, variant, cost)
    else:
        options = route_alternatives(items, end_index, use_two_opt, cost)
        order = options[variant % len(options)] if options else \
            list(range(len(items)))
        crossings = []
        option_count = max(1, len(options))
    result.options = option_count

    if not order:
        result.notes.append('{0}: no route could be worked out.'.format(job.label))
        return result

    span_lengths = []
    for position in range(len(order) - 1):
        span_lengths.append(_distance(items[order[position]][1],
                                      items[order[position + 1]][1]))
    if vertex_override is None:
        wanted = core._settings_float(settings, 'mid_vertices')
    else:
        wanted = float(vertex_override)
    # 'each' puts the same number on every wire, so 1 is one vertex at the
    # middle of every span and the wire reads as a single clean arc whatever
    # it spans. 'length' shares them out by span instead.
    by_length = str(settings.get('vertex_mode', 'each')).strip().lower() \
        == 'length'
    spacing = core.vertex_spacing(span_lengths, wanted) if by_length else 0.0

    flipped = 0
    still_clashing = 0
    span_notes = {}
    crossing_set = set(crossings)
    emergency = {}
    all_emergency = False
    if job.is_lighting and emergency_type is not None:
        for index, (element, _point) in enumerate(items):
            emergency[index] = core.is_emergency(element, doc, settings)
        marked = len([1 for value in emergency.values() if value])
        # ANY fitting reading as emergency makes the whole circuit an
        # emergency circuit. Requiring all of them meant one fitting with the
        # parameter unset put permanent live spans back into a run that is
        # emergency in every other respect - the wrong way to be wrong. An
        # emergency circuit drawn wholly in the emergency type is right, and a
        # part-marked circuit is a data problem to report, not to draw around.
        all_emergency = marked > 0
        if all_emergency and marked == len(items):
            result.info.append(
                '{0}: every fitting reads as emergency, so the whole circuit '
                'is drawn in the emergency wire type and no span is permanent '
                'live.'.format(job.label))
        elif all_emergency:
            result.notes.append(
                '{0}: {1} of {2} fitting(s) read as emergency, so the whole '
                'circuit is drawn in the emergency wire type. Check the {3} '
                'parameter on the other {4} if that is wrong.'.format(
                    job.label, marked, len(items),
                    settings.get('emergency_parameter', ''),
                    len(items) - marked))

    for position in range(len(order) - 1):
        element_a, point_a = items[order[position]]
        element_b, point_b = items[order[position + 1]]
        segment_type = _segment_type(position, order, crossing_set, emergency,
                                     wire_type, live_type, emergency_type,
                                     all_emergency)
        if by_length:
            mids = max(core.MIN_VERTICES,
                       core.vertices_for(span_lengths[position], spacing))
        else:
            mids = core.clamp_vertices(wanted)
        span_side = side
        if obstacles:
            depth = span_depth(point_a, point_b)
            hits = span_clashes(point_a, point_b, depth, side, obstacles)
            if hits:
                other = 'right' if str(side).strip().lower() != 'right' \
                    else 'left'
                if span_clashes(point_a, point_b, depth, other,
                                obstacles) < hits:
                    span_side = other
                    flipped += 1
                else:
                    still_clashing += 1
        wire, note = place_segment(doc, view, settings, element_a, point_a,
                                   element_b, point_b, segment_type, plane_z,
                                   sag, span_side, mids, sag_mode, wiring)
        if wire is None:
            span_notes['refused - ' + note] = \
                span_notes.get('refused - ' + note, 0) + 1
        else:
            result.wires.append(wire)
            result.length += _distance(point_a, point_b)
            if note:
                span_notes[note] = span_notes.get(note, 0) + 1

    # the home run
    home_run = None
    if job.switch_point is not None and \
            core._settings_bool(settings, 'switch_home_run'):
        element, point = items[order[-1]]
        home_run_type = wire_type
        if all_emergency and emergency_type is not None:
            home_run_type = emergency_type
        home_run, note = place_home_run(doc, view, settings, element, point,
                                        job.switch_point, home_run_type,
                                        plane_z, sag, side, job.switch_element,
                                        wiring)
        if home_run is None:
            if core._settings_bool(settings, 'stub_if_no_connection'):
                result.notes.append('{0}: no home run - {1}.'.format(
                    job.label, note))
        else:
            result.wires.append(home_run)
            if note:
                result.notes.append('{0}: {1}.'.format(job.label, note))
    elif job.switch_point is None and core._settings_bool(settings,
                                                          'switch_home_run'):
        result.notes.append('{0}: no switch found, so no home run was drawn '
                            'and any panel home run has been left '
                            'alone.'.format(job.label))

    _emit_span_notes(result, job.label, span_notes)

    result.flipped = flipped
    result.clashing = still_clashing
    if flipped:
        result.info.append('{0}: {1} span(s) arc the other way to clear a '
                            'fitting on another circuit.'.format(
                                job.label, flipped))
    if still_clashing:
        result.notes.append('{0}: {1} span(s) still cross a fitting that is '
                            'not on this circuit - no route or side clears '
                            'them. Shuffle may find one.'.format(
                                job.label, still_clashing))

    # the drawn connection between the light and its switch
    if job.switch_point is not None and job.switch_from is not None and \
            core._settings_bool(settings, 'draw_switch_line'):
        line, note = place_switch_line(doc, view, settings, job.switch_from,
                                       core.element_point(job.switch_from),
                                       job.switch_element, job.switch_point,
                                       cache)
        if line is None:
            result.notes.append('{0}: no switch line - {1}.'.format(
                job.label, note))
        else:
            result.extras.append(line)
            if note:
                result.notes.append('{0}: {1}.'.format(job.label, note))

    # panel home runs, once there is something to replace them with
    if home_run is not None and \
            core._settings_bool(settings, 'remove_panel_home_runs'):
        keep = [core.eid_value(wire.Id) for wire in result.wires]
        removed = remove_panel_home_runs(doc, job.existing_wires, keep)
        if removed:
            result.info.append('{0}: {1} home run(s) back to the panel '
                                'removed.'.format(job.label, removed))

    # the tag
    if core._settings_bool(settings, 'tag_circuits') and result.wires:
        tag_type = core.find_tag_type(doc,
                                      settings.get('wire_tag_family', ''),
                                      settings.get('wire_tag_type', ''),
                                      cache)
        target = _tag_target(settings, result.wires, home_run)
        result.tag = place_tag(doc, view, settings, target, tag_type)
        if result.tag is None:
            result.notes.append('{0}: the wire tag would not place - check a '
                                'wire tag family is loaded.'.format(job.label))

    return result


# Per-span messages that are a fact about how Revit behaves rather than
# something to act on. They are counted and said once, as information.
ROUTINE_SPAN_NOTES = (
    'trim was refused',
)


def _is_routine(text):
    for start in ROUTINE_SPAN_NOTES:
        if text.startswith(start):
            return True
    return False


def _emit_span_notes(result, label, tally):
    """One line per distinct outcome, with how many spans it happened to."""
    for text in sorted(tally.keys()):
        count = tally[text]
        line = '{0}: {1} span(s) - {2}.'.format(label, count, text) \
            if count > 1 else '{0}: {1}.'.format(label, text)
        if _is_routine(text):
            result.info.append(line)
        else:
            result.notes.append(line)


def _segment_type(position, order, crossings, emergency,
                  wire_type, live_type, emergency_type,
                  whole_circuit_emergency=False):
    """Which wire type one span takes.

    **An emergency circuit is emergency throughout.** Every span takes the
    emergency type, crossings included - permanent live has nothing to say on
    a circuit that is emergency end to end, and mixing the two would read as
    though part of the run were something else.

    Otherwise the permanent live wins on a crossing, because that span's job
    is to say "same circuit, different switch or different space" and it is
    the only span that can say it. Away from a crossing, a span with an
    emergency fitting at either end takes the emergency type - the run into an
    emergency fitting is part of the emergency run.
    """
    if whole_circuit_emergency and emergency_type is not None:
        return emergency_type
    if position in crossings and live_type is not None:
        return live_type
    if emergency_type is not None:
        if emergency.get(order[position]) or emergency.get(order[position + 1]):
            return emergency_type
    return wire_type


def _tag_target(settings, wires, home_run):
    which = str(settings.get('tag_which', 'homerun')).strip().lower()
    if which == 'first':
        return wires[0]
    if which == 'homerun' and home_run is not None:
        return home_run
    longest = None
    best = -1.0
    for wire in wires:
        points = core.wire_vertices(wire)
        if len(points) < 2:
            continue
        step = core.plan_distance(points[0], points[-1])
        if step > best:
            best = step
            longest = wire
    return longest or wires[0]


def snapshot_wire(doc, wire):
    """Enough to rebuild a wire after it has been deleted.

    Connector objects are not held: once the wire is gone they are references
    into a document that has moved on. The owning element id and the
    connector's own id are stored instead and re-resolved at restore time.
    """
    points = core.wire_vertices(wire)
    if len(points) < 2:
        return None
    ends = []
    for connector, index in core.wire_ends(wire):
        partner = core.opposite_connector(connector)
        owner_id = None
        connector_id = None
        if partner is not None:
            try:
                owner_id = core.eid_value(partner.Owner.Id)
                connector_id = partner.Id
            except Exception:
                owner_id = None
        ends.append((index, owner_id, connector_id))
    return {
        'type_id': wire.GetTypeId(),
        'view_id': wire.OwnerViewId,
        'wiring': core.wiring_type_of(wire),
        'points': points,
        'ends': ends,
    }


def _resolve_connector(doc, owner_id, connector_id):
    if owner_id is None:
        return None
    try:
        owner = doc.GetElement(ElementId(int(owner_id)))
    except Exception:
        owner = None
    if owner is None:
        return None
    for connector in core.electrical_connectors(owner):
        try:
            if connector_id is None or connector.Id == connector_id:
                return connector
        except Exception:
            continue
    return None


def restore_wire(doc, shot):
    """Put a snapshotted wire back. Its element id will be a new one."""
    if not shot:
        return None
    last = len(shot['points']) - 1
    start = None
    finish = None
    for index, owner_id, connector_id in shot['ends']:
        connector = _resolve_connector(doc, owner_id, connector_id)
        if index == 0:
            start = connector
        elif index == last:
            finish = connector
    vertex_list = List[XYZ]()
    for point in shot['points']:
        vertex_list.Add(point)
    try:
        return Wire.Create(doc, shot['type_id'], shot['view_id'],
                           shot['wiring'], vertex_list, start, finish)
    except Exception:
        return None


def snapshot_tag(doc, tag):
    try:
        hosts = []
        try:
            for host_id in tag.GetTaggedLocalElementIds():
                hosts.append(host_id)
        except Exception:
            hosts.append(tag.TaggedLocalElementId)
        return {
            'type_id': tag.GetTypeId(),
            'view_id': tag.OwnerViewId,
            'hosts': hosts,
            'point': tag.TagHeadPosition,
            'leader': tag.HasLeader,
        }
    except Exception:
        return None


def restore_tag(doc, shot, host=None):
    """Put a snapshotted tag back, optionally onto a different host.

    A rebuilt wire is a new element, so a tag that was on the old one has to
    be re-pointed at the new one or it goes with the wire it was hosted on.
    """
    if not shot:
        return None
    if host is None:
        if not shot.get('hosts'):
            return None
        host = doc.GetElement(shot['hosts'][0])
    if host is None:
        return None
    try:
        reference = Reference(host)
        tag = IndependentTag.Create(doc, shot['type_id'], shot['view_id'],
                                    reference, shot['leader'],
                                    TagOrientation.Horizontal, shot['point'])
        return tag
    except Exception:
        return None


def clear_circuit(doc, view, job, snapshots=None):
    """Take out a circuit's existing wires and their tags.

    With a `snapshots` list, enough is recorded first to put them back - which
    is what Cancel needs once the session no longer holds an open transaction
    group across it.
    """
    wires = list(job.existing_wires)
    tags = tags_on(doc, view, wires)
    if snapshots is not None:
        for tag in tags:
            shot = snapshot_tag(doc, tag)
            if shot:
                snapshots.append(('tag', shot))
        for wire in wires:
            shot = snapshot_wire(doc, wire)
            if shot:
                snapshots.append(('wire', shot))
    removed_tags = 0
    removed_wires = 0
    for tag in tags:
        try:
            doc.Delete(tag.Id)
            removed_tags += 1
        except Exception:
            pass
    for wire in wires:
        try:
            doc.Delete(wire.Id)
            removed_wires += 1
        except Exception:
            pass
    job.existing_wires = []
    return removed_wires, removed_tags


def attach_switch(job, switches, settings, doc=None):
    """Find the circuit's switch, and the light the home run leaves from.

    Connectivity is asked first and the id parameters second. A switch that is
    genuinely wired to one of the lights is a fact; a matching Switch ID is
    only a claim, and the two disagree often enough in a model that has been
    edited that the fact has to win.
    """
    is_switch = make_switch_test(settings)

    # 1. a switch actually connected to one of this circuit's lights
    if doc is not None:
        for element, point in job.members:
            found, how = connected_switch(doc, element, is_switch)
            if found is not None:
                job.switch_element = found
                job.switch_point = core.element_point(found)
                job.switch_from = element
                job.switch_route = 'connected to {0} through its {1}'.format(
                    core.element_name(element), how)
                if job.switch_point is not None:
                    return

    # 2. the switch system the fittings name, matched to a device in the view
    keys = {}
    for element, _point in job.members:
        key = switch_id_of(element)
        if key:
            keys[key] = keys.get(key, 0) + 1
    if not keys:
        key = switch_id_of_circuit(job.circuit)
        if key:
            keys[key] = 1
    if not keys:
        return

    ordered = sorted(keys.items(), key=lambda pair: -pair[1])
    for key, _count in ordered:
        devices = switches.get(key)
        if devices:
            job.switch_key = key
            job.switch_element = devices[0][0]
            job.switch_point = devices[0][1]
            job.switch_route = 'matched on switch id {0}'.format(
                key.split(':', 1)[-1])
            return
    job.switch_key = ordered[0][0]


# ---------------------------------------------------------------------------
# A run, with Shuffle held open over it
# ---------------------------------------------------------------------------
class Session(object):
    """Places a set of circuits, and can replace them with another route.

    Everything sits inside one TransactionGroup which is only assimilated when
    the route is kept, so Cancel puts the view back exactly as it was and Keep
    leaves a single undo step. The transactions run from inside the Shuffle
    dialog, which is legal because a modal window shown from a command is
    still inside the command's own API context - and is the reason this tool
    needs no ExternalEvent and no persistent engine.
    """

    def __init__(self, uidoc, settings, jobs, switches, report):
        self.uidoc = uidoc
        self.doc = uidoc.Document
        self.view = uidoc.Document.ActiveView
        self.settings = settings
        self.jobs = jobs
        self.switches = switches
        self.report = report
        self.group = None
        self.variant = 0
        self.placed = []
        self.alternatives = 1
        self.cleared = False
        self.cache = {}
        self.modeless = core._settings_bool(settings, 'modeless_shuffle')
        self.removed = []        # snapshots of what clearing took out
        self.vertex_override = None
        self.sag_override = None
        self.avoid_override = None
        self.wiring_override = None
        self.clashing = 0

    # -- the group -----------------------------------------------------------
    def start(self, title):
        """Open a transaction group, but only for the modal path.

        A group left open across a modeless session would sit there while the
        user pans, and anything else they did in Revit would nest inside it -
        so a Cancel would roll back their work as well as ours. The modeless
        path commits each redraw on its own and restores from snapshots
        instead.
        """
        self.title = title
        if self.modeless:
            self.group = None
            return
        self.group = TransactionGroup(self.doc, title)
        self.group.Start()

    def keep(self):
        try:
            if self.group is not None:
                self.group.Assimilate()
        except Exception:
            pass
        self.group = None

    def cancel(self):
        if self.group is not None:
            try:
                self.group.RollBack()
            except Exception:
                pass
            self.group = None
            self.refresh()
            return

        # modeless: undo it by hand, in one transaction so it is one undo step
        transaction = Transaction(self.doc, '{0} cancelled'.format(
            self.title or 'RevoBIM Wires'))
        core.apply_failure_handler(transaction)
        transaction.Start()
        try:
            self._delete_placed()
            for kind, shot in self.removed:
                if kind == 'wire':
                    restore_wire(self.doc, shot)
            for kind, shot in self.removed:
                if kind == 'tag':
                    restore_tag(self.doc, shot)
            self.removed = []
            self.cleared = False
            transaction.Commit()
        except Exception:
            try:
                transaction.RollBack()
            except Exception:
                pass
        self.refresh()

    def refresh(self):
        try:
            self.uidoc.RefreshActiveView()
        except Exception:
            pass

    # -- placing -------------------------------------------------------------
    def _delete_placed(self):
        for element_id in self.placed:
            try:
                self.doc.Delete(element_id)
            except Exception:
                pass
        self.placed = []

    def place(self, variant, clear_first=False):
        self.variant = variant
        transaction = Transaction(self.doc, 'RevoBIM Auto Wire')
        core.apply_failure_handler(transaction)
        transaction.Start()
        try:
            self._delete_placed()
            if clear_first and not self.cleared:
                for job in self.jobs:
                    wires, tags = clear_circuit(self.doc, self.view, job,
                                                self.removed)
                    if wires or tags:
                        self.report.note(
                            '{0}: {1} wire(s) and {2} tag(s) removed before '
                            'redrawing.'.format(job.label, wires, tags))
                self.cleared = True

            count = 0
            self.clashing = 0
            for job in self.jobs:
                sub = SubTransaction(self.doc)
                sub.Start()
                try:
                    result = wire_one_circuit(
                        self.doc, self.view, self.settings, job, self.switches,
                        variant, self.cache, self.vertex_override,
                        self.sag_override, self.avoid_override,
                        self.wiring_override)
                    for wire in result.wires:
                        self.placed.append(wire.Id)
                    for extra in result.extras:
                        self.placed.append(extra.Id)
                    if result.tag is not None:
                        self.placed.append(result.tag.Id)
                    count += len(result.wires)
                    self.clashing += result.clashing
                    self.alternatives = max(self.alternatives, result.options)
                    if variant == 0:
                        for note in result.info:
                            self.report.info(note)
                        for note in result.notes:
                            self.report.note(note)
                    sub.Commit()
                except Exception as error:
                    sub.RollBack()
                    self.report.skip('{0}: left alone - {1}'.format(
                        job.label, error))
            transaction.Commit()
            self.report.drawn = count
        except Exception as error:
            try:
                transaction.RollBack()
            except Exception:
                pass
            self.report.skip('The run was rolled back: {0}'.format(error))
        self.refresh()
        return len(self.placed)

    def finish(self, keep):
        """Keep or cancel, whichever path the session is on."""
        if keep:
            self.keep()
        else:
            self.cancel()

    def shuffle(self):
        return self.place(self.variant + 1, clear_first=False)

    def set_vertices(self, count):
        """Redraw at a different vertex count, same route. Never below 1."""
        self.vertex_override = core.clamp_vertices(count)
        return self.place(self.variant, clear_first=False)

    def vertices(self):
        if self.vertex_override is None:
            return core.clamp_vertices(
                core._settings_float(self.settings, 'mid_vertices'))
        return self.vertex_override

    def set_wiring(self, kind):
        """Redraw as arc or chamfered wires, same route and vertices."""
        self.wiring_override = 'chamfer' if str(kind).lower() == 'chamfer' \
            else 'arc'
        return self.place(self.variant, clear_first=False)

    def wiring(self):
        if self.wiring_override is not None:
            return self.wiring_override
        value = str(self.settings.get('wiring_type', 'arc')).strip().lower()
        return 'chamfer' if value == 'chamfer' else 'arc'

    def set_avoid(self, flag):
        """Turn clash avoidance on or off and redraw, so the difference it
        makes to the route can be seen rather than taken on trust."""
        self.avoid_override = bool(flag)
        return self.place(self.variant, clear_first=False)

    def avoiding(self):
        if self.avoid_override is None:
            return core._settings_bool(self.settings, 'avoid_fittings')
        return self.avoid_override

    def set_sag(self, paper_mm):
        """Redraw with the vertices further off the chord, or closer to it."""
        self.sag_override = max(0.0, float(paper_mm))
        return self.place(self.variant, clear_first=False)

    def sag(self):
        if self.sag_override is None:
            return _sag_setting(self.settings)
        return self.sag_override

    def sag_mode(self):
        return str(self.settings.get('arc_sag_mode', 'span')).strip().lower()

    def previous(self):
        """Back to the route before this one. Wraps round at the start."""
        step = self.variant - 1
        if step < 0:
            step = max(0, self.alternatives - 1)
        return self.place(step, clear_first=False)

    def has_previous(self):
        return self.alternatives > 1


# ---------------------------------------------------------------------------
# The two commands
# ---------------------------------------------------------------------------
def _guard(uidoc, report):
    doc = uidoc.Document
    view = doc.ActiveView
    if not core.is_plan_view(view):
        report.skip('Wires are only drawn on a floor plan or a ceiling plan. '
                    'Open one and run again.')
        return None
    return view


def _report_lookups(doc, settings, report):
    """Say what the run resolved before it draws anything."""
    pairs, note = core.wire_types(doc)
    if not pairs:
        report.skip('No wire type could be found in this model, so nothing '
                    'can be drawn. Lookup routes tried: {0}.'.format(note))
    else:
        chosen = core.find_wire_type(doc, settings.get('lighting_wire_type', ''))
        live = core.find_wire_type(doc,
                                   settings.get('lighting_live_wire_type', ''))
        report.info('Wire type: {0}. Permanent live: {1}. ({2} wire type(s) in '
                    'this model.)'.format(
                        core._type_name(chosen) if chosen else 'none',
                        core._type_name(live) if live else 'none',
                        len(pairs)))

    if core._settings_bool(settings, 'tag_circuits'):
        rows, tag_note = core.wire_tag_types(doc)
        if not rows:
            report.skip('No wire tag family is loaded, so no tags will be '
                        'placed. Lookup routes tried: {0}.'.format(tag_note))
        else:
            symbol = core.find_tag_type(doc, settings.get('wire_tag_family', ''),
                                        settings.get('wire_tag_type', ''))
            report.info('Wire tag: {0}.'.format(
                core._type_name(symbol) if symbol else 'none'))


def prepare(uidoc, settings, report, restrict_to=None, only_circuit=None):
    """Everything read from the model before a single transaction opens."""
    doc = uidoc.Document
    view = _guard(uidoc, report)
    if view is None:
        return None, None

    want_power = core._settings_bool(settings, 'power_enabled')
    jobs = collect_jobs(doc, view, settings, restrict_to, want_power)

    if only_circuit is not None:
        target = core.eid_value(only_circuit.Id)
        jobs = [job for job in jobs
                if core.eid_value(job.circuit.Id) == target]

    switches = find_switch_devices(doc, view, settings)
    for job in jobs:
        attach_switch(job, switches, settings, doc)
        if job.switch_element is not None and job.switch_route:
            report.info('{0}: switch found - {1}.'.format(
                job.label, job.switch_route))
        if job.switch_key and job.switch_element is None:
            report.note('{0}: switch system {1} found on the fittings, but no '
                        'switch device is drawn in this view.'.format(
                            job.label, job.switch_key.split(':', 1)[-1]))
        if core._settings_bool(settings, 'report_offscreen') and job.offscreen:
            report.note('{0}: {1} member(s) of this circuit are not in this '
                        'view and have been left out of the run.'.format(
                            job.label, job.offscreen))
    return view, jobs


def run_wire_circuits(uiapp, settings, shuffle_prompt=None):
    """Auto Wire.

    With something selected, wire the circuits that selection sits on and
    nothing else. With nothing selected, wire every circuit in the view that
    has no wires yet - the already-wired filter belongs to the sweep, not to a
    deliberate pick.
    """
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    report = core.Report('Auto Wire')

    restrict_to = None
    try:
        chosen = []
        for element_id in uidoc.Selection.GetElementIds():
            element = doc.GetElement(element_id)
            if element is not None and core.electrical_connectors(element):
                chosen.append(element)
        if chosen:
            restrict_to = chosen
            report.info('{0} fitting(s) selected, so only their circuits are '
                        'wired.'.format(len(chosen)))
    except Exception:
        pass

    view, jobs = prepare(uidoc, settings, report, restrict_to)
    if view is None:
        return report

    # A deliberate pick means redraw it: the existing wires and tags come out
    # first. The sweep leaves already-wired circuits alone, because "wire what
    # is not wired" is what running it with nothing selected asks for.
    sweeping = restrict_to is None
    if sweeping and core._settings_bool(settings, 'skip_wired_circuits'):
        keep = []
        skipped = 0
        for job in jobs:
            if job.existing_wires:
                skipped += 1
            else:
                keep.append(job)
        jobs = keep
        if skipped:
            report.info('{0} circuit(s) in this view already have wires and '
                        'were left alone. Select one to redraw it.'.format(
                            skipped))
    elif not sweeping:
        wired = [job.label for job in jobs if job.existing_wires]
        if wired:
            report.info('Redrawing {0}, so the existing wires and tags come '
                        'out first.'.format(', '.join(wired)))

    if not jobs:
        if restrict_to is not None:
            report.note('Nothing selected is on a circuit that needs wiring.')
        else:
            report.note('No circuited fittings in this view need wiring.')
        return report

    _report_lookups(doc, settings, report)

    session = Session(uidoc, settings, jobs, {}, report)
    session.switches = find_switch_devices(doc, view, settings)
    session.start('RevoBIM Auto Wire')
    session.place(0, clear_first=(restrict_to is not None))

    _finish(session, settings, shuffle_prompt, report,
            '{0} circuit(s) drawn.'.format(len(jobs)))
    return report


def run_rejig(uiapp, settings, shuffle_prompt=None):
    """Redraw one existing circuit: out with the old wires and tags, in with
    the route rules, then Shuffle until it reads right."""
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    report = core.Report('Re-Route Wires')

    circuit = _pick_circuit(uidoc, report)
    if circuit is None:
        return report if report.lines else None

    view, jobs = prepare(uidoc, settings, report, None, circuit)
    if view is None:
        return report
    if not jobs:
        report.note('That circuit has no fittings drawn in this view.')
        return report

    _report_lookups(doc, settings, report)

    session = Session(uidoc, settings, jobs, {}, report)
    session.switches = find_switch_devices(doc, view, settings)
    session.start('RevoBIM Re-Route Wires')
    session.place(0, clear_first=True)

    _finish(session, settings, shuffle_prompt, report,
            '{0} redrawn.'.format(jobs[0].label))
    return report


def _finish(session, settings, shuffle_prompt, report, headline):
    """Keep, shuffle or roll back - and never hide why nothing was drawn.

    An earlier version wiped the report on Cancel, so a run that drew nothing
    still opened the Shuffle prompt, and pressing Cancel - the only sensible
    thing to do with an empty result - threw away the notes saying why. Both
    halves of that are fixed here: no prompt when nothing landed, and Cancel
    keeps the notes.
    """
    if not session.placed:
        session.cancel()
        report.note('Nothing was drawn. The notes above say why for each '
                    'circuit.')
        return

    if shuffle_prompt is not None and \
            core._settings_bool(settings, 'preview_shuffle'):
        kept = shuffle_prompt(session, headline)
        if kept is None:
            # the prompt is floating and still open, so it owns the session
            # now - and the command is about to return long before the route
            # is settled
            report.deferred = True
            report.info('Shuffle is open - Revit is yours to pan and zoom '
                        'while you judge the route.')
            return
        if not kept:
            report.drawn = 0
            report.info('Cancelled - the view is back as it was.')
            return
    session.keep()
    report.drawn = len(session.placed)
    report.ok(headline)


def _pick_circuit(uidoc, report):
    """A circuit from whatever is selected, or picked."""
    doc = uidoc.Document
    candidates = []
    try:
        for element_id in uidoc.Selection.GetElementIds():
            element = doc.GetElement(element_id)
            if element is None:
                continue
            candidates.append(element)
    except Exception:
        pass

    if not candidates:
        try:
            from Autodesk.Revit.UI.Selection import ObjectType
            reference = uidoc.Selection.PickObject(
                ObjectType.Element,
                'Select a wire or a fitting on the circuit to re-route')
            element = doc.GetElement(reference.ElementId)
            if element is not None:
                candidates.append(element)
        except Exception:
            return None

    for element in candidates:
        if core.is_wire(element):
            circuit = core.wire_circuit(doc, element)
            if circuit is not None:
                return circuit
    for element in candidates:
        circuits = core.element_circuits(element)
        if circuits:
            return circuits[0]
    report.skip('Nothing selected is on a circuit.')
    return None


# ---------------------------------------------------------------------------
# Apply Wire Types - the type, and nothing else
# ---------------------------------------------------------------------------
def wires_by_circuit(doc, view):
    """Every wire drawn in the view, grouped by the circuit it belongs to.

    One pass. Asking each circuit for its wires in turn means resolving every
    wire once per circuit, which on a floor plan with sixty circuits is sixty
    times the work for the same answer.
    """
    grouped = {}
    loose = []
    try:
        for wire in FilteredElementCollector(doc, view.Id).OfClass(Wire):
            circuit = core.wire_circuit(doc, wire)
            if circuit is None:
                loose.append(wire)
                continue
            key = core.eid_value(circuit.Id)
            if key not in grouped:
                grouped[key] = (circuit, [])
            grouped[key][1].append(wire)
    except Exception:
        pass
    return grouped, loose


def wire_endpoints(doc, wire):
    """The elements at each end of a wire, as far as it is connected."""
    owners = []
    for connector, _index in core.wire_ends(wire):
        partner = core.opposite_connector(connector)
        if partner is None:
            continue
        try:
            owner = partner.Owner
        except Exception:
            owner = None
        if owner is not None and not core.is_wire(owner):
            owners.append(owner)
    return owners


def wanted_wire_type(doc, settings, wire, circuit_emergency, is_lighting,
                     types, cache):
    """Which type this wire should be, by the rules Auto Wire draws with.

    Deliberately the same three questions in the same order, so a circuit
    drawn by Auto Wire and a circuit retyped by this tool cannot disagree.
    """
    base, emergency_type, live_type = types
    if circuit_emergency and emergency_type is not None:
        return emergency_type, 'the circuit is emergency'
    if is_lighting and live_type is not None:
        owners = wire_endpoints(doc, wire)
        if len(owners) >= 2:
            first = leg_key(owners[0], doc, settings, cache)
            second = leg_key(owners[1], doc, settings, cache)
            if first != second:
                return live_type, 'it bridges two legs'
    return base, ''


def circuit_reads_emergency(doc, settings, circuit, cache=None):
    """Any member reading as emergency makes the circuit an emergency one."""
    if cache is not None:
        key = core.eid_value(circuit.Id)
        if key in cache:
            return cache[key]
    answer = False
    try:
        for member in circuit.Elements:
            if core.is_emergency(member, doc, settings):
                answer = True
                break
    except Exception:
        answer = False
    if cache is not None:
        cache[core.eid_value(circuit.Id)] = answer
    return answer


def circuit_is_lighting(doc, settings, circuit):
    lighting = _category_id_values(
        _category_ids(settings, 'lighting_categories', 'lighting_fixtures'))
    try:
        for member in circuit.Elements:
            if core.eid_value(member.Category.Id) in lighting:
                return True
    except Exception:
        pass
    return False


def apply_types_to_circuit(doc, settings, circuit, wires, report, cache):
    """Set the wire type on a circuit's wires. Nothing else is touched."""
    label = core.circuit_label(circuit)
    is_lighting = circuit_is_lighting(doc, settings, circuit)
    emergency = is_lighting and circuit_reads_emergency(
        doc, settings, circuit, cache.setdefault('emergency', {}))

    if is_lighting:
        base = core.find_wire_type(doc, settings.get('lighting_wire_type', ''),
                                   cache)
    else:
        base = core.find_wire_type(doc, settings.get('power_wire_type', ''),
                                   cache)
    emergency_type = core.find_wire_type(
        doc, settings.get('lighting_emergency_wire_type', ''), cache)
    live_type = core.find_wire_type(
        doc, settings.get('lighting_live_wire_type', ''), cache)

    if base is None:
        report.skip('{0}: no wire type could be found, so nothing was '
                    'changed.'.format(label))
        return 0

    types = (base, emergency_type, live_type)
    changed = 0
    already = 0
    refused = 0
    tally = {}

    for wire in wires:
        sub = SubTransaction(doc)
        sub.Start()
        try:
            wanted, why = wanted_wire_type(doc, settings, wire, emergency,
                                           is_lighting, types, cache)
            if wanted is None:
                sub.RollBack()
                continue
            if core.same_id(wire.GetTypeId(), wanted.Id):
                already += 1
                sub.Commit()
                continue
            wire.ChangeTypeId(wanted.Id)
            # read back rather than trust it
            if core.same_id(wire.GetTypeId(), wanted.Id):
                changed += 1
                name = core._type_name(wanted)
                tally[name] = tally.get(name, 0) + 1
                sub.Commit()
            else:
                refused += 1
                sub.RollBack()
        except Exception:
            refused += 1
            try:
                sub.RollBack()
            except Exception:
                pass

    if changed:
        parts = ['{0} to {1}'.format(tally[name], name)
                 for name in sorted(tally.keys())]
        report.ok('{0}: {1} wire(s) retyped - {2}.'.format(
            label, changed, ', '.join(parts)))
    if already and not changed:
        report.info('{0}: all {1} wire(s) were already the right type.'.format(
            label, already))
    elif already:
        report.info('{0}: {1} wire(s) were already right.'.format(
            label, already))
    if refused:
        report.skip('{0}: Revit refused the type on {1} wire(s).'.format(
            label, refused))
    if emergency:
        report.info('{0}: reads as an emergency circuit.'.format(label))
    return changed


def selected_circuits(uidoc):
    """Every circuit the current selection sits on, in selection order."""
    doc = uidoc.Document
    found = []
    seen = set()

    def take(circuit):
        if circuit is None:
            return
        key = core.eid_value(circuit.Id)
        if key in seen:
            return
        seen.add(key)
        found.append(circuit)

    try:
        for element_id in uidoc.Selection.GetElementIds():
            element = doc.GetElement(element_id)
            if element is None:
                continue
            if core.is_wire(element):
                take(core.wire_circuit(doc, element))
                continue
            try:
                if isinstance(element, ElectricalSystem):
                    take(element)
                    continue
            except Exception:
                pass
            for circuit in core.element_circuits(element):
                take(circuit)
    except Exception:
        pass
    return found


def run_apply_types(uiapp, settings, confirm=None):
    """Set wire types to match the settings. The drawing is not touched.

    Nothing selected: ask, then do every circuit with wires in the active
    view. Something selected: do only the circuits it sits on.
    """
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    view = doc.ActiveView
    report = core.Report('Apply Wire Types')
    cache = {}

    chosen = selected_circuits(uidoc)

    if not chosen:
        if not core.is_plan_view(view):
            report.skip('Nothing is selected, and this view is not a floor or '
                        'ceiling plan. Select a circuit, or open a plan.')
            return report
        if confirm is not None:
            name = 'this view'
            try:
                name = view.Name
            except Exception:
                pass
            if not confirm(
                    'Apply wire types to every circuit in {0}?'.format(name),
                    'Only the wire type is set. Nothing is moved, redrawn, '
                    'retagged or deleted. Select a circuit first to do just '
                    'that one.'):
                report.info('Cancelled.')
                return report

    grouped, loose = wires_by_circuit(doc, view)
    if chosen:
        wanted = set(core.eid_value(c.Id) for c in chosen)
        work = [(circuit, wires) for key, (circuit, wires) in grouped.items()
                if key in wanted]
        missing = wanted - set(grouped.keys())
        if missing:
            report.note('{0} selected circuit(s) have no wires drawn in this '
                        'view.'.format(len(missing)))
        report.info('{0} circuit(s) selected.'.format(len(chosen)))
    else:
        work = [(circuit, wires) for _key, (circuit, wires) in grouped.items()]

    if loose and not chosen:
        report.note('{0} wire(s) in this view belong to no circuit and were '
                    'left alone. Reconnect Wires is the button for '
                    'those.'.format(len(loose)))

    if not work:
        report.note('No circuits with wires were found to retype.')
        return report

    work.sort(key=lambda pair: core.circuit_label(pair[0]))

    transaction = Transaction(doc, 'RevoBIM Apply Wire Types')
    core.apply_failure_handler(transaction)
    transaction.Start()
    total = 0
    try:
        for circuit, wires in work:
            total += apply_types_to_circuit(doc, settings, circuit, wires,
                                            report, cache)
        transaction.Commit()
    except Exception as error:
        try:
            transaction.RollBack()
        except Exception:
            pass
        report.skip('The run was rolled back: {0}'.format(error))
        return report

    report.retyped = total
    if total and len(work) > 1:
        # with one circuit this would only repeat the line above it
        report.ok('{0} wire(s) retyped across {1} circuit(s).'.format(
            total, len(work)))
    elif not total:
        report.info('Every wire was already the right type.')
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass
    return report


# ---------------------------------------------------------------------------
# Align Wire Ends - the arrival point, and nothing else
# ---------------------------------------------------------------------------
def wire_end_targets(doc, view, settings, wire):
    """[(vertex index, element, where it should sit), ...] for one wire.

    Only ends that are joined to something are offered: a loose end has no
    fitting to be aligned to, and guessing one is Reconnect Wires' job.
    """
    points = core.wire_vertices(wire)
    if len(points) < 2:
        return []
    last = len(points) - 1
    found = []
    for connector, index in core.wire_ends(wire):
        if index not in (0, last):
            continue
        partner = core.opposite_connector(connector)
        if partner is None:
            continue
        try:
            owner = partner.Owner
        except Exception:
            owner = None
        if owner is None or core.is_wire(owner):
            continue

        # the vertex the wire arrives from, which sets the direction
        neighbour = points[1] if index == 0 else points[last - 1]
        if core.plan_distance(neighbour, points[index]) < core.mm(0.1) \
                and len(points) > 2:
            neighbour = points[2] if index == 0 else points[last - 2]

        centre = None
        try:
            centre = partner.Origin
        except Exception:
            centre = None
        if centre is None:
            centre = core.element_point(owner)
        if centre is None:
            continue

        target = core.arrival_point(view, settings, owner, centre, neighbour,
                                    points[index].Z)
        if target is None:
            continue
        found.append((index, owner, target, connector, partner))
    return found


def _at(point):
    return '({0:.0f},{1:.0f})'.format(core.to_mm(point.X), core.to_mm(point.Y))


def _vertex_now(wire, index):
    points = core.wire_vertices(wire)
    return points[index] if index < len(points) else None


def _end_state(doc, view, settings, wire, index):
    """Resolve one end afresh: its connector, its partner, and its target.

    Resolved immediately before every attempt and never held across one. A
    sub-transaction that commits *or rolls back* invalidates the connector
    references taken before it, and a held reference then fails with "the
    referenced object is not valid" - which is what made every second end and
    every rebuild fail, while looking like Revit refusing the operation.
    """
    for idx, owner, target, connector, partner in wire_end_targets(
            doc, view, settings, wire):
        if idx == index:
            return connector, partner, target, owner
    return None, None, None, None


def _try_move(doc, view, settings, wire, index, trace):
    """Set the vertex, then read it back."""
    connector, _partner, target, _owner = _end_state(doc, view, settings,
                                                     wire, index)
    if target is None:
        trace.append('    move: the end could not be resolved again')
        return False
    sub = SubTransaction(doc)
    sub.Start()
    try:
        wire.SetVertex(index, target)
        doc.Regenerate()
    except Exception as error:
        sub.RollBack()
        trace.append('    move: refused ({0})'.format(
            str(error).splitlines()[0]))
        return False
    landed = _vertex_now(wire, index)
    if landed is not None and core.plan_distance(landed, target) <= core.mm(0.5):
        sub.Commit()
        trace.append('    move: took, now {0}'.format(_at(landed)))
        return True
    sub.RollBack()
    trace.append('    move: returned without moving it')
    return False


# How far back from the node to try, in millimetres, when the node itself is
# refused. The first that Revit accepts wins.
NUDGE_STEPS = (0, 2, 5, 10, 15, 25, 40)

# How far to shove the end before dropping it back on the node. Small first:
# the hand barely moves it.
REDOCK_SHOVES = (300.0, 1500.0)


def wire_joined_ends(doc, wire):
    """The vertex indices of the ends that are joined to a fitting.

    No target and no geometry - just which ends have something to be aligned
    to. Everything about *where* they should go is Revit's to answer.
    """
    points = core.wire_vertices(wire)
    if len(points) < 2:
        return []
    last = len(points) - 1
    found = []
    for connector, index in core.wire_ends(wire):
        if index not in (0, last):
            continue
        partner = core.opposite_connector(connector)
        if partner is None:
            continue
        try:
            owner = partner.Owner
        except Exception:
            continue
        if owner is None or core.is_wire(owner):
            continue
        found.append(index)
    return found


def _try_redock(doc, view, settings, wire, index, trace):
    """Do what the hand does: drag the end off, drag it back on, let go.

    Disconnect the end, move the vertex well clear so Revit has to recompute,
    put it on the connector, reconnect. Revit then places the arrival itself -
    and where Revit places it is the symbol edge, which is the answer this
    tool was trying and failing to calculate.

    So the test is not "did it land on my target". It is **did it end up
    nearer the node than it started**, because the exact spot is Revit's to
    choose and Revit is the authority on it.
    """
    connector, partner, _target, _owner = _end_state(doc, view, settings,
                                                     wire, index)
    if connector is None or partner is None:
        trace.append('    redock: no connector pair')
        return False
    try:
        node = partner.Origin
    except Exception:
        trace.append('    redock: the node could not be read')
        return False
    here = _vertex_now(wire, index)
    if here is None:
        return False
    was = core.plan_distance(here, node)

    for shove in REDOCK_SHOVES:
        connector, partner, _t, _o = _end_state(doc, view, settings, wire,
                                                index)
        if connector is None or partner is None:
            return False
        sub = SubTransaction(doc)
        sub.Start()
        try:
            connector.DisconnectFrom(partner)
            doc.Regenerate()
            away = XYZ(here.X + core.mm(shove), here.Y + core.mm(shove),
                       here.Z)
            wire.SetVertex(index, away)
            doc.Regenerate()
            wire.SetVertex(index, XYZ(node.X, node.Y, here.Z))
            doc.Regenerate()
            connector.ConnectTo(partner)
            doc.Regenerate()
        except Exception as error:
            sub.RollBack()
            trace.append('    redock {0:.0f}mm: refused ({1})'.format(
                shove, str(error).splitlines()[0]))
            continue

        landed = _vertex_now(wire, index)
        if landed is None:
            sub.RollBack()
            trace.append('    redock {0:.0f}mm: the vertex went away'.format(
                shove))
            continue
        now = core.plan_distance(landed, node)
        if now < was - core.mm(1):
            sub.Commit()
            trace.append('    redock {0:.0f}mm: took, now {1}, {2:.0f}mm from '
                         'the node (was {3:.0f}mm)'.format(
                             shove, _at(landed), core.to_mm(now),
                             core.to_mm(was)))
            return True
        sub.RollBack()
        trace.append('    redock {0:.0f}mm: no closer ({1:.0f}mm, was '
                     '{2:.0f}mm)'.format(shove, core.to_mm(now),
                                         core.to_mm(was)))
    return False


def _try_nudge(doc, view, settings, wire, index, trace):
    """Shove the end, then walk it in towards the node.

    Two things, in order, both suggested by what Revit actually said.

    Revit refuses a vertex that lands within tolerance of one it already
    holds - so first the vertex is shoved somewhere free and put straight
    back, which is what dragging the node by hand does and which may be
    enough for Revit to re-seat the end itself. If that does not do it, the
    end is set at increasing distances back from the node until one is
    accepted: landing 10mm short of the node is a fifth of a millimetre on a
    1:50 sheet, and a fifth of a millimetre is arrived.
    """
    _connector, _partner, target, _owner = _end_state(doc, view, settings,
                                                      wire, index)
    if target is None:
        trace.append('    nudge: the end could not be resolved again')
        return False
    here = _vertex_now(wire, index)
    if here is None:
        return False
    close_enough = core.mm(core._settings_float(settings, 'align_max_gap_mm'))

    # shove it and put it back
    for distance in (50.0, 200.0):
        sub = SubTransaction(doc)
        sub.Start()
        try:
            away = XYZ(here.X + core.mm(distance), here.Y + core.mm(distance),
                       here.Z)
            wire.SetVertex(index, away)
            doc.Regenerate()
            wire.SetVertex(index, here)
            doc.Regenerate()
        except Exception as error:
            sub.RollBack()
            trace.append('    nudge {0:.0f}mm: refused ({1})'.format(
                distance, str(error).splitlines()[0]))
            continue
        landed = _vertex_now(wire, index)
        if landed is not None and \
                core.plan_distance(landed, target) <= close_enough:
            sub.Commit()
            trace.append('    nudge {0:.0f}mm: Revit re-seated it, now '
                         '{1}'.format(distance, _at(landed)))
            return True
        sub.RollBack()
        trace.append('    nudge {0:.0f}mm: no re-seat'.format(distance))

    # walk in from the node until Revit takes it
    dx = here.X - target.X
    dy = here.Y - target.Y
    reach = math.sqrt(dx * dx + dy * dy)
    if reach < 1.0e-9:
        return False
    ux = dx / reach
    uy = dy / reach
    for back in NUDGE_STEPS:
        point = XYZ(target.X + ux * core.mm(back),
                    target.Y + uy * core.mm(back), here.Z)
        sub = SubTransaction(doc)
        sub.Start()
        try:
            wire.SetVertex(index, point)
            doc.Regenerate()
        except Exception as error:
            sub.RollBack()
            trace.append('    step {0}mm: refused ({1})'.format(
                back, str(error).splitlines()[0]))
            continue
        landed = _vertex_now(wire, index)
        if landed is None:
            sub.RollBack()
            continue
        gap = core.plan_distance(landed, target)
        if gap <= close_enough:
            sub.Commit()
            trace.append('    step {0}mm: took, now {1}, {2:.0f}mm from the '
                         'node'.format(back, _at(landed), core.to_mm(gap)))
            return True
        sub.RollBack()
        trace.append('    step {0}mm: landed {1:.0f}mm away, not close '
                     'enough'.format(back, core.to_mm(gap)))
    return False


def _try_jiggle(doc, view, settings, wire, index, trace):
    """Disconnect the end and reconnect it, so Revit re-seats it."""
    connector, partner, target, _owner = _end_state(doc, view, settings,
                                                    wire, index)
    if connector is None or partner is None or target is None:
        trace.append('    jiggle: no connector pair to re-seat')
        return False
    sub = SubTransaction(doc)
    sub.Start()
    try:
        connector.DisconnectFrom(partner)
        connector.ConnectTo(partner)
        doc.Regenerate()
    except Exception as error:
        sub.RollBack()
        trace.append('    jiggle: refused ({0})'.format(
            str(error).splitlines()[0]))
        return False
    landed = _vertex_now(wire, index)
    if landed is None:
        sub.RollBack()
        trace.append('    jiggle: the vertex went away')
        return False
    if core.plan_distance(landed, target) <= core.mm(0.5):
        sub.Commit()
        trace.append('    jiggle: took, now {0}'.format(_at(landed)))
        return True
    sub.RollBack()
    trace.append('    jiggle: re-seated at {0}, not the target'.format(
        _at(landed)))
    return False


def _try_rebuild(doc, view, settings, wire, trace):
    """Build the wire again with its ends where they belong.

    The only route that can put a vertex exactly where it is asked for, since
    Wire.Create takes a fresh point list rather than editing one Revit is
    holding. It costs the element id, so any tag hosted on the wire is
    snapshotted first and re-pointed at the replacement.
    """
    targets = wire_end_targets(doc, view, settings, wire)
    if not targets:
        trace.append('    rebuild: no joined end to aim at')
        return None
    points = core.wire_vertices(wire)
    if len(points) < 2:
        trace.append('    rebuild: fewer than two vertices')
        return None
    last = len(points) - 1
    start = None
    finish = None
    for index, _owner, target, _connector, partner in targets:
        if index < len(points):
            points[index] = target
        if index == 0:
            start = partner
        elif index == last:
            finish = partner

    tags = tags_on(doc, doc.ActiveView, [wire])
    shots = []
    for tag in tags:
        shot = snapshot_tag(doc, tag)
        if shot:
            shots.append(shot)

    sub = SubTransaction(doc)
    sub.Start()
    try:
        rebuilt = core.rebuild_wire(doc, wire, points, start, finish)
    except Exception as error:
        sub.RollBack()
        trace.append('    rebuild: refused ({0})'.format(
            str(error).splitlines()[0]))
        return None
    if rebuilt is None:
        sub.RollBack()
        trace.append('    rebuild: Revit returned no wire')
        return None
    put_back = 0
    for shot in shots:
        if restore_tag(doc, shot, rebuilt) is not None:
            put_back += 1
    sub.Commit()
    trace.append('    rebuild: took, new id {0}{1}'.format(
        core.eid_value(rebuilt.Id),
        ', {0} tag(s) re-placed'.format(put_back) if shots else ''))
    return rebuilt


def log_wire_geometry(doc, view, settings, wire, trace):
    """Everything Revit will tell us about one wire, written out in full.

    Three rounds of this have been spent inferring what a wire is made of
    from the way it refuses instructions. This asks it directly instead.
    """
    trace.append('  geometry of wire {0}:'.format(core.eid_value(wire.Id)))
    try:
        kind = core.wiring_type_of(wire)
    except Exception:
        kind = '?'
    try:
        type_name = core._type_name(doc.GetElement(wire.GetTypeId()))
    except Exception:
        type_name = '?'
    trace.append('    type {0}, wiring {1}'.format(type_name, kind))

    points = core.wire_vertices(wire)
    trace.append('    {0} vertices: {1}'.format(
        len(points), ' '.join(_at(p) for p in points)))

    for connector, index in core.wire_ends(wire):
        try:
            origin = connector.Origin
            where = '{0} z={1:.0f}'.format(_at(origin), core.to_mm(origin.Z))
        except Exception:
            where = '?'
        try:
            joined = connector.IsConnected
        except Exception:
            joined = '?'
        trace.append('    wire connector -> vertex {0}, origin {1}, '
                     'connected {2}'.format(index, where, joined))

        partner = core.opposite_connector(connector)
        if partner is None:
            trace.append('      joined to nothing')
            continue
        try:
            origin = partner.Origin
            trace.append('      partner origin {0} z={1:.0f}'.format(
                _at(origin), core.to_mm(origin.Z)))
        except Exception:
            trace.append('      partner origin unreadable')
        try:
            owner = partner.Owner
            trace.append('      on {0} (id {1}, {2})'.format(
                core.element_name(owner), core.eid_value(owner.Id),
                owner.Category.Name))
            spot = core.element_point(owner)
            if spot is not None:
                trace.append('      its location {0} z={1:.0f}'.format(
                    _at(spot), core.to_mm(spot.Z)))
            box = owner.get_BoundingBox(view)
            if box is not None:
                trace.append('      its box {0} to {1}'.format(
                    _at(box.Min), _at(box.Max)))
            others = core.electrical_connectors(owner)
            trace.append('      it has {0} electrical connector(s)'.format(
                len(others)))
            for other in others:
                try:
                    trace.append('        connector at {0} z={1:.0f}, '
                                 'connected {2}'.format(
                                     _at(other.Origin),
                                     core.to_mm(other.Origin.Z),
                                     other.IsConnected))
                except Exception:
                    pass
        except Exception as error:
            trace.append('      owner unreadable ({0})'.format(error))


def align_one_wire(doc, view, settings, wire, tolerance, report=None):
    """Put a wire's joined ends where they belong.

    On `auto` there is **no target**. Every joined end is re-docked - off the
    connector, clear, back on, reconnected - and the result is kept only if
    the end finished nearer the node than it started. An end already in the
    right place is re-placed in the same spot, is therefore not nearer, and
    rolls back untouched.

    That is deliberate. Three releases computed where an end should go and got
    it wrong three different ways: collapsed to a stub, buried in the middle
    of the symbol, left 400mm short. Revit works it out correctly the moment a
    wire is re-docked, so the destination does not belong in this tool.

    The other methods still aim at `align_target`, for when a particular
    answer is wanted.

    Returns (moved, refused, already, replacement).
    """
    trace = report.trace if report is not None else []
    wire_id = core.eid_value(wire.Id)
    if core._settings_bool(settings, 'debug_geometry'):
        log_wire_geometry(doc, view, settings, wire, trace)

    method = str(settings.get('align_method', 'auto')).strip().lower()

    if method in ('auto', 'redock'):
        ends = wire_joined_ends(doc, wire)
        if not ends:
            return 0, 0, 0, None
        trace.append('wire {0}: {1} joined end(s), re-docking'.format(
            wire_id, len(ends)))
        moved = 0
        settled = 0
        for index in ends:
            here = _vertex_now(wire, index)
            trace.append('  end {0} at {1}'.format(
                index, _at(here) if here is not None else '?'))
            if _try_redock(doc, view, settings, wire, index, trace):
                moved += 1
            else:
                settled += 1
        return moved, 0, settled, None

    # the aimed methods, which need a target
    targets = wire_end_targets(doc, view, settings, wire)
    if not targets:
        return 0, 0, 0, None
    points = core.wire_vertices(wire)
    todo = []
    already = 0
    for index, _owner, target, _connector, _partner in targets:
        if index >= len(points):
            continue
        if core.plan_distance(points[index], target) <= tolerance:
            already += 1
            continue
        todo.append((index, target))
    if not todo:
        return 0, 0, already, None

    trace.append('wire {0}: {1} end(s) to move, by {2}'.format(
        wire_id, len(todo), method))
    moved = 0
    refused = 0
    for index, target in todo:
        here = _vertex_now(wire, index)
        trace.append('  end {0}: {1} -> {2}'.format(
            index, _at(here) if here is not None else '?', _at(target)))
        done = False
        if method == 'move':
            done = _try_move(doc, view, settings, wire, index, trace)
        elif method == 'nudge':
            done = _try_nudge(doc, view, settings, wire, index, trace)
        elif method == 'jiggle':
            done = _try_jiggle(doc, view, settings, wire, index, trace)
        if done:
            moved += 1
        else:
            refused += 1

    if refused and method in ('auto+rebuild', 'rebuild'):
        rebuilt = _try_rebuild(doc, view, settings, wire, trace)
        if rebuilt is not None:
            return len(todo), 0, already, rebuilt

    return moved, refused, already, None


def wires_from_selection(uidoc):
    """(wires picked directly, circuits picked). Either may be empty."""
    doc = uidoc.Document
    wires = []
    seen = set()
    try:
        for element_id in uidoc.Selection.GetElementIds():
            element = doc.GetElement(element_id)
            if element is None or not core.is_wire(element):
                continue
            key = core.eid_value(element.Id)
            if key not in seen:
                seen.add(key)
                wires.append(element)
    except Exception:
        pass
    return wires, selected_circuits(uidoc)


def run_align_ends(uiapp, settings, confirm=None):
    """Pull wire ends onto the fittings they are joined to.

    Nothing selected: ask, then every wire in the active view. Wires selected:
    just those. Circuits selected: every wire on them.
    """
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    view = doc.ActiveView
    report = core.Report('Align Wire Ends')

    if not core.is_plan_view(view):
        report.skip('Wires are only drawn on a floor plan or a ceiling plan. '
                    'Open one and run again.')
        return report

    picked_wires, picked_circuits = wires_from_selection(uidoc)
    grouped, loose = wires_by_circuit(doc, view)

    work = []
    if picked_wires:
        work = list(picked_wires)
        report.info('{0} wire(s) selected.'.format(len(work)))
    if picked_circuits:
        wanted = set(core.eid_value(c.Id) for c in picked_circuits)
        added = 0
        have = set(core.eid_value(w.Id) for w in work)
        for key, (_circuit, wires) in grouped.items():
            if key not in wanted:
                continue
            for wire in wires:
                if core.eid_value(wire.Id) not in have:
                    work.append(wire)
                    added += 1
        if added:
            report.info('{0} wire(s) on {1} selected circuit(s).'.format(
                added, len(picked_circuits)))

    if not work:
        if confirm is not None:
            name = 'this view'
            try:
                name = view.Name
            except Exception:
                pass
            if not confirm(
                    'Align every wire end in {0}?'.format(name),
                    'Only the point where a wire meets its fitting is moved. '
                    'Nothing is retyped, retagged, reconnected or deleted, '
                    'and no wire changes its element id. Select wires or '
                    'circuits first to do just those.'):
                report.info('Cancelled.')
                return report
        for _key, (_circuit, wires) in grouped.items():
            work.extend(wires)
        work.extend(loose)

    if not work:
        report.note('No wires were found in this view.')
        return report

    tolerance = core.mm(core._settings_float(settings, 'align_tolerance_mm'))
    mode = str(settings.get('align_target', 'trim')).strip().lower()
    report.info('Ends are set {0}.'.format(
        'on the connector at the symbol centre' if mode == 'centre'
        else 'short of the symbol, by the trim setting'))

    transaction = Transaction(doc, 'RevoBIM Align Wire Ends')
    core.apply_failure_handler(transaction)
    transaction.Start()
    moved = 0
    refused = 0
    already = 0
    untouched = 0
    rebuilds = 0
    try:
        for wire in work:
            sub = SubTransaction(doc)
            sub.Start()
            try:
                one_moved, one_refused, one_already, rebuilt = align_one_wire(
                    doc, view, settings, wire, tolerance, report)
                if rebuilt is not None:
                    rebuilds += 1
                if not (one_moved or one_refused or one_already):
                    untouched += 1
                moved += one_moved
                refused += one_refused
                already += one_already
                sub.Commit()
            except Exception:
                sub.RollBack()
                refused += 1
        transaction.Commit()
    except Exception as error:
        try:
            transaction.RollBack()
        except Exception:
            pass
        report.skip('The run was rolled back: {0}'.format(error))
        return report

    report.aligned = moved
    if moved:
        report.ok('{0} wire end(s) pulled onto their fitting, across {1} '
                  'wire(s).'.format(moved, len(work)))
    if already:
        report.info('{0} end(s) were left as they were - Revit put them back '
                    'in the same place, so they were already right.'.format(
                        already))
    if untouched:
        report.info('{0} wire(s) had no end joined to a fitting and were '
                    'left alone.'.format(untouched))
    if rebuilds:
        report.note('{0} wire(s) could not be moved or re-seated and were '
                    'rebuilt instead, so those have new element '
                    'ids.'.format(rebuilds))
    if refused:
        report.note('Revit refused every route on {0} end(s). The debug '
                    'report says what each one did.'.format(refused))
    if not moved and not refused:
        report.info('Every wire end was already where it belongs.')
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass
    return report
