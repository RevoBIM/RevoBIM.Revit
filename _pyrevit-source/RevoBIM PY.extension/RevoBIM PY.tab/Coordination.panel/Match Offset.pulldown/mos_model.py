# -*- coding: utf-8 -*-
"""RevoBIM Match Offset Slope - everything that touches the Revit model.

Three jobs: walk the branch run and work out what may move, apply the rigid
transforms that put it on the main's fall at the crossing point, and put a
fitting in.

Rigid transforms, not curve edits. ElementTransformUtils.RotateElements and
MoveElements keep connectors joined; rewriting LocationCurve on one pipe of a
connected run does not, and leaves the rest of the run behind. The one place a
curve is rewritten is the end pipe's free end, which is what trim and extend
does anyway, and the uprights, which are disconnected first on purpose.
"""

import mo_clr  # noqa: F401

from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, ElementId, ElementTransformUtils,
    Line, RoutingPreferenceRuleGroupType, StorageType, SubTransaction, XYZ,
)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.DB.Plumbing import Pipe, PlumbingUtils

import mos_geom as geom
from mo_core import eid_value, log, to_text

try:
    from System.Collections.Generic import List
except Exception:
    List = None

EPS = geom.EPS
TOL_FT = 0.1 / geom.MM_PER_FT
JOIN_TOL_FT = 1.0 / geom.MM_PER_FT

FITTING_CATEGORIES = (u"OST_PipeFitting", u"OST_PipeAccessory")


def id_list(ids):
    collection = List[ElementId]()
    for element_id in ids:
        collection.Add(element_id)
    return collection


def category_is(element, name):
    try:
        return eid_value(element.Category.Id) == eid_value(
            ElementId(getattr(BuiltInCategory, name)))
    except Exception:
        return False


def is_pipe(element):
    return category_is(element, u"OST_PipeCurves")


def is_fitting(element):
    for name in FITTING_CATEGORIES:
        if category_is(element, name):
            return True
    return False


# ======================================================================
# curves and connectors
# ======================================================================

def name_of(element):
    """Element.Name raises AttributeError under IronPython; guard it."""
    try:
        return to_text(element.Name)
    except Exception:
        return u"the pipe type"


def curve_of(element):
    try:
        return element.Location.Curve
    except Exception:
        return None


def ends_of(element):
    """The two ends of a straight segment as Pts, or None."""
    curve = curve_of(element)
    if curve is None:
        return None
    try:
        return (geom.to_pt(curve.GetEndPoint(0)),
                geom.to_pt(curve.GetEndPoint(1)))
    except Exception:
        return None


def is_straight(element):
    curve = curve_of(element)
    if curve is None:
        return False
    try:
        return curve.GetType().Name == 'Line'
    except Exception:
        try:
            return bool(curve.IsBound) and hasattr(curve, 'Direction')
        except Exception:
            return False


def pitch_of(element):
    ends = ends_of(element)
    if ends is None:
        return 0.0
    return geom.pitch_degrees(ends[0], ends[1])


def connector_manager(element):
    """The connector manager, whichever kind of element this is.

    A pipe is an MEPCurve and carries ConnectorManager directly. A fitting
    is a FamilyInstance and does not: its manager hangs off MEPModel. Asking
    only for the first gives a fitting zero connectors, which reads as "the
    family has 0 connectors, not three" when a junction is being placed by
    hand - and, quietly and much worse, stops the run walk dead at the first
    bend, so only the first pipe of a run ever moved.
    """
    try:
        manager = element.ConnectorManager
        if manager is not None:
            return manager
    except Exception:
        pass
    try:
        model = element.MEPModel
        if model is not None:
            return model.ConnectorManager
    except Exception:
        pass
    return None


def connectors(element):
    out = []
    manager = connector_manager(element)
    if manager is None:
        return out
    try:
        for connector in manager.Connectors:
            out.append(connector)
    except Exception:
        return out
    return out


def connector_key(connector):
    """Owner id and connector id, so a connector can be found again.

    Never a held connector handle: re-fetching a connector is not the same
    as regenerating, and a handle kept across doc.Regenerate() fails
    silently rather than raising.
    """
    try:
        return (eid_value(connector.Owner.Id), int(connector.Id))
    except Exception:
        return None


def connector_by_key(doc, key):
    if key is None:
        return None
    owner = doc.GetElement(ElementId(key[0]))
    if owner is None:
        return None
    for connector in connectors(owner):
        try:
            if int(connector.Id) == key[1]:
                return connector
        except Exception:
            continue
    return None


def open_connector_at(doc, element_id, point, tolerance=JOIN_TOL_FT):
    """A free connector of an element, at a point.

    By position rather than by a key captured earlier, because rewriting a
    LocationCurve can renumber an element's connectors: the key taken before
    the move is not guaranteed to still name the same connector after it,
    and looking it up anyway is where "a connector went missing after the
    split" came from.
    """
    element = doc.GetElement(element_id)
    if element is None:
        return None
    best = None
    best_distance = tolerance
    for connector in connectors(element):
        try:
            origin = geom.to_pt(connector.Origin)
        except Exception:
            continue
        distance = geom.length(origin, point)
        if distance <= best_distance and not is_joined(connector):
            best = connector
            best_distance = distance
    if best is not None:
        return best
    # Nothing free at that point: fall back to the nearest one at all, so
    # the caller gets a connector to complain about rather than a None.
    return connector_at(element, point, tolerance)


def connector_at(element, point, tolerance=JOIN_TOL_FT):
    """The connector of an element sitting at a point."""
    best = None
    best_distance = tolerance
    for connector in connectors(element):
        try:
            origin = geom.to_pt(connector.Origin)
        except Exception:
            continue
        distance = geom.length(origin, point)
        if distance <= best_distance:
            best = connector
            best_distance = distance
    return best


def is_joined(connector):
    try:
        return bool(connector.IsConnected)
    except Exception:
        return False


def joined_owners(connector):
    out = []
    try:
        for reference in connector.AllRefs:
            try:
                owner = reference.Owner
            except Exception:
                continue
            if owner is None:
                continue
            out.append((owner, reference))
    except Exception:
        return out
    return out


def unjoin(first, second):
    try:
        first.DisconnectFrom(second)
        return True
    except Exception:
        return False


def unjoin_all(connector):
    freed = []
    for owner, reference in joined_owners(connector):
        if eid_value(owner.Id) == eid_value(connector.Owner.Id):
            continue
        if unjoin(connector, reference):
            freed.append(connector_key(reference))
    return freed


# ======================================================================
# walking the branch run
# ======================================================================

class UprightLink(object):
    """An upright hanging off the body, and where it met it."""

    __slots__ = ('upright_id', 'upright_key', 'body_key', 'fixed_end')

    def __init__(self, upright_id, upright_key, body_key, fixed_end):
        self.upright_id = upright_id
        self.upright_key = upright_key
        self.body_key = body_key
        self.fixed_end = fixed_end


class RunBody(object):
    def __init__(self):
        self.ids = []
        self.pipes = []
        self.uprights = []
        self.refusal = u""
        self.count = 0


def walk_run(doc, start, steep_deg, limit):
    """Everything that travels with the clicked pipe, as one rigid body.

    The walk stops at any pipe pitched more than steep_deg, which is the
    horizontal-to-upright line. Anything past an upright is not walked at
    all, so the floor above is never disturbed. Fittings are never classed
    as uprights, so the bend between a run and its stack travels with the
    run and the stack stretches up to meet it.
    """
    body = RunBody()
    seen = set()
    pending = [start]
    upright_seen = set()

    while pending:
        element = pending.pop()
        key = eid_value(element.Id)
        if key in seen:
            continue
        seen.add(key)

        try:
            if eid_value(element.GroupId) > 0:
                body.refusal = u"the run reaches into a Revit group"
                return body
        except Exception:
            pass

        body.ids.append(element.Id)
        if is_pipe(element):
            body.pipes.append(element)
        body.count = len(seen)
        if body.count > limit:
            body.refusal = u"the run reaches more than {0} elements".format(
                limit)
            return body

        for connector in connectors(element):
            for owner, reference in joined_owners(connector):
                other_key = eid_value(owner.Id)
                if other_key == key or other_key in seen:
                    continue
                if not (is_pipe(owner) or is_fitting(owner)):
                    continue
                if is_pipe(owner) and pitch_of(owner) > steep_deg:
                    if other_key in upright_seen:
                        continue
                    upright_seen.add(other_key)
                    ends = ends_of(owner)
                    fixed = None
                    if ends is not None:
                        origin = geom.to_pt(connector.Origin)
                        near = geom.length(ends[0], origin)
                        far = geom.length(ends[1], origin)
                        fixed = ends[1] if near <= far else ends[0]
                    body.uprights.append(UprightLink(
                        owner.Id, connector_key(reference),
                        connector_key(connector), fixed))
                    continue
                pending.append(owner)

    return body


def free_end_of(body, towards):
    """The end pipe and connector that will be stretched to the junction.

    A free connector first. A run with no spare end has the joint nearest
    the main freed and used instead, rather than the run being refused.
    """
    best = None
    best_distance = None
    fallback = None
    fallback_distance = None
    for pipe in body.pipes:
        for connector in connectors(pipe):
            try:
                origin = geom.to_pt(connector.Origin)
            except Exception:
                continue
            distance = geom.plan_length(origin, towards)
            if not is_joined(connector):
                if best_distance is None or distance < best_distance:
                    best = (pipe, connector)
                    best_distance = distance
            else:
                if fallback_distance is None or distance < fallback_distance:
                    fallback = (pipe, connector)
                    fallback_distance = distance
    if best is not None:
        return best, False
    if fallback is not None:
        return fallback, True
    return None, False


def anchor_of(pipe, free_connector):
    """The end of the end pipe that is not moving."""
    ends = ends_of(pipe)
    if ends is None:
        return None
    try:
        origin = geom.to_pt(free_connector.Origin)
    except Exception:
        return ends[0]
    if geom.length(ends[0], origin) <= geom.length(ends[1], origin):
        return ends[1]
    return ends[0]


# ======================================================================
# the transforms
# ======================================================================

def rotate_body(doc, ids, anchor, axis_unit, angle):
    """Tilt the whole body about a horizontal axis through the anchor."""
    if abs(angle) < 1e-9:
        return False
    start = XYZ(anchor.x, anchor.y, anchor.z)
    end = XYZ(anchor.x + axis_unit[0], anchor.y + axis_unit[1], anchor.z)
    try:
        ElementTransformUtils.RotateElements(
            doc, id_list(ids), Line.CreateBound(start, end), angle)
        return True
    except Exception as err:
        raise Exception(u"Revit refused the tilt: {0}".format(to_text(err)))


def move_body(doc, ids, dx, dy, dz):
    """Shift the whole body, in all three directions.

    Three rather than one because the in-line case needs a sideways nudge as
    well as a lift: two runs meant to be one are drawn on the same line but
    rarely on it to the millimetre, and the union will not take two ends
    that are a few millimetres apart.
    """
    if abs(dx) <= TOL_FT and abs(dy) <= TOL_FT and abs(dz) <= TOL_FT:
        return False
    try:
        ElementTransformUtils.MoveElements(
            doc, id_list(ids), XYZ(float(dx), float(dy), float(dz)))
        return True
    except Exception as err:
        raise Exception(u"Revit refused the move: {0}".format(to_text(err)))


def set_line(element, first, second):
    try:
        element.Location.Curve = Line.CreateBound(
            XYZ(first.x, first.y, first.z),
            XYZ(second.x, second.y, second.z))
        return True
    except Exception:
        return False


def restretch(element, fixed_end, landing):
    """Move one end of a pipe, leaving the curve pointing the way it did.

    A pipe's connectors are bound to the ends of its curve by index, so
    writing Line.CreateBound(fixed, landing) when the fixed end was index 1
    reverses the curve and swaps which connector is which. Revit answers
    that with "The duct/pipe has been modified to be in the opposite
    direction causing the connections to be invalid", disconnects whatever
    was joined to it, and the run comes apart at the fitting - with the
    geometry looking almost right, which is what makes it hard to see.

    So: work out which index the end that is staying put actually is, and
    write the new curve in that order.
    """
    ends = ends_of(element)
    if ends is None:
        return False, u"no curve"
    if geom.length(ends[0], fixed_end) <= geom.length(ends[1], fixed_end):
        first, second, order = fixed_end, landing, u"0 stays"
    else:
        first, second, order = landing, fixed_end, u"1 stays"
    if geom.length(first, second) < JOIN_TOL_FT:
        return False, u"the pipe would have no length left"
    if not set_line(element, first, second):
        return False, u"Revit refused the new curve"
    return True, order


def stretch_end(pipe, fixed_end, target_x, target_y):
    """Pull or push the end pipe along its own axis to the crossing point."""
    ends = ends_of(pipe)
    if ends is None:
        return None
    moving = ends[1] if geom.length(ends[0], fixed_end) < \
        geom.length(ends[1], fixed_end) else ends[0]
    direction = geom.unit3(fixed_end, moving)
    if direction is None:
        return None
    landing = geom.stretch_to_plan_point(fixed_end, direction,
                                         target_x, target_y)
    if landing is None:
        return None
    done, _order = restretch(pipe, fixed_end, landing)
    if not done:
        return None
    return landing


def release_uprights(doc, body):
    """Let every boundary upright go before the body moves.

    An upright is never allowed to block the move: it is released, the run
    goes where it has to, and the upright is re-cut to follow.
    """
    released = []
    for link in body.uprights:
        connector = connector_by_key(doc, link.body_key)
        partner = connector_by_key(doc, link.upright_key)
        if connector is None or partner is None:
            continue
        if unjoin(connector, partner):
            released.append(link)
    return released


def refit_uprights(doc, links, report):
    """Re-cut each upright so the end that met the run lands on its new
    position and the other end stays exactly where it was."""
    doc.Regenerate()
    for link in links:
        connector = connector_by_key(doc, link.body_key)
        upright = doc.GetElement(link.upright_id)
        if connector is None or upright is None or link.fixed_end is None:
            report.problem(u"an upright could not be found again and was "
                           u"left loose")
            continue
        try:
            landing = geom.to_pt(connector.Origin)
        except Exception:
            report.problem(u"an upright could not be re-cut and was left "
                           u"loose")
            continue
        done, why = restretch(upright, link.fixed_end, landing)
        if not done:
            report.problem(u"upright {0} was left loose: {1}".format(
                eid_value(link.upright_id), why))
            continue
        doc.Regenerate()
        partner = connector_by_key(doc, link.upright_key)
        connector = connector_by_key(doc, link.body_key)
        if partner is None or connector is None:
            continue
        try:
            partner.ConnectTo(connector)
        except Exception:
            report.problem(u"an upright was re-cut but would not reconnect")


# ======================================================================
# the junction
# ======================================================================

def project_onto(element, point):
    """Put the crossing point exactly on a centreline.

    BreakCurve and the fitting calls reject a point a fraction off the
    curve, and the crossing is worked out in plan so it always is.
    """
    curve = curve_of(element)
    if curve is None:
        return point
    try:
        result = curve.Project(XYZ(point.x, point.y, point.z))
        if result is not None:
            return geom.to_pt(result.XYZPoint)
    except Exception:
        pass
    return point


def extend_main(doc, main, point):
    """Carry the main out to an apparent intersection.

    Through restretch, so the main's own curve direction survives - the main
    is connected at its other end and reversing it would break that joint
    exactly as it does on a branch.
    """
    ends = ends_of(main)
    if ends is None:
        return False
    keep = ends[0] if geom.length(ends[0], point) > \
        geom.length(ends[1], point) else ends[1]
    done, _why = restretch(main, keep, point)
    return done


# RoutingPreferenceRuleGroupType spells its members in the plural -
# Junctions, Elbows, Crosses - and asking for the singular throws
# "'type' object has no attribute 'Junction'", which the reader of the
# report then has to know means the read failed rather than that the pipe
# type carries no families. Both spellings are tried so a release that
# changes its mind cannot break it again.
ROUTING_GROUPS = (
    (u"Junction", (u"Junctions", u"Junction")),
    (u"Elbow", (u"Elbows", u"Elbow")),
    (u"Cross", (u"Crosses", u"Cross")),
    (u"Union", (u"Unions", u"Union")),
    (u"Transition", (u"Transitions", u"Transition")),
)


def rule_group(names):
    for name in names:
        try:
            return getattr(RoutingPreferenceRuleGroupType, name), name
        except Exception:
            continue
    return None, u""


def group_names_available():
    """What the enum actually offers on this release, for the report."""
    try:
        return sorted([n for n in dir(RoutingPreferenceRuleGroupType)
                       if not n.startswith('_')])
    except Exception:
        return []


def routing_offer(doc, pipe):
    """What the pipe type's routing preferences actually offer.

    Returns (names, counts, detail). The detail is why the read failed, when
    it did: "no junction families at all" and "the read threw" look the same
    in a report that only hands back a list, and they mean completely
    different things to whoever has to fix it.

    RoutingPreferenceRuleGroupType lives in Autodesk.Revit.DB, not in
    Autodesk.Revit.DB.Plumbing. Asking the wrong namespace for it is an
    ImportError at module load, which is the blank white pyRevit window.
    """
    names = []
    counts = {}
    try:
        pipe_type = doc.GetElement(pipe.GetTypeId())
    except Exception as err:
        return names, counts, u"the pipe type could not be read: {0}".format(
            to_text(err))
    if pipe_type is None:
        return names, counts, u"the pipe has no type"
    try:
        manager = pipe_type.RoutingPreferenceManager
    except Exception as err:
        return names, counts, (
            u"{0} has no RoutingPreferenceManager on this release: "
            u"{1}".format(name_of(pipe_type), to_text(err)))
    if manager is None:
        return names, counts, u"the pipe type has no routing preferences"

    troubles = []
    for label, spellings in ROUTING_GROUPS:
        kind, _spelling = rule_group(spellings)
        if kind is None:
            troubles.append(u"{0} is not a rule group on this release".format(
                label))
            continue
        try:
            count = manager.GetNumberOfRules(kind)
        except Exception as err:
            troubles.append(u"counting the {0} rules threw: {1}".format(
                label, to_text(err)))
            continue
        counts[label] = count
        for index in range(count):
            try:
                rule = manager.GetRule(kind, index)
                symbol = doc.GetElement(rule.MEPPartId)
                if symbol is not None:
                    names.append(u"{0}: {1}".format(
                        label, to_text(symbol.Family.Name)))
            except Exception as err:
                troubles.append(u"reading a {0} rule threw: {1}".format(
                    label, to_text(err)))
                continue
    if not counts and troubles:
        troubles.append(u"the enum offers: {0}".format(
            u", ".join(group_names_available())))
    return names, counts, u"; ".join(troubles)


def junction_symbols(doc, pipe):
    """Every junction family symbol the main's pipe type will route to."""
    out = []
    try:
        manager = doc.GetElement(pipe.GetTypeId()).RoutingPreferenceManager
    except Exception:
        return out
    kind, _spelling = rule_group((u"Junctions", u"Junction"))
    if kind is None or manager is None:
        return out
    try:
        count = manager.GetNumberOfRules(kind)
    except Exception:
        return out
    for index in range(count):
        try:
            symbol = doc.GetElement(manager.GetRule(kind, index).MEPPartId)
        except Exception:
            continue
        if symbol is None:
            continue
        out.append((to_text(symbol.Family.Name), symbol))
    return out


def junction_rules(doc, pipe):
    """How many junction rules the main's pipe type carries.

    Asked before the main is split rather than after the tee is refused:
    breaking a pipe in half and putting it back together again for a tee
    that was never going to place costs a regenerate and leaves Revit
    complaining about connectivity on the way through.
    """
    _names, counts, detail = routing_offer(doc, pipe)
    return counts.get(u"Junction", -1), detail


def place_tee(doc, main, branch_id, point, by_hand=True):
    """Split the main at the crossing and put a tee across the three ends.

    The split and the tee sit in a sub-transaction, so a refused tee never
    leaves the main cut in half.
    """
    sub = SubTransaction(doc)
    sub.Start()
    try:
        landing = project_onto(main, point)
        new_id = PlumbingUtils.BreakCurve(
            doc, main.Id, XYZ(landing.x, landing.y, landing.z))
        doc.Regenerate()
        other = doc.GetElement(new_id)
        if other is None:
            sub.RollBack()
            return None, u"", [u"Revit would not split the main"]

        first = connector_at(main, landing)
        second = connector_at(other, landing)
        if first is None or second is None:
            sub.RollBack()
            return None, u"", [u"the split main had no connector at the "
                               u"crossing"]

        # Some releases leave the two halves joined after the break, and a
        # tee will not take connectors that are already connected.
        unjoin(first, second)
        doc.Regenerate()
        first = connector_at(main, landing)
        second = connector_at(other, landing)
        branch = open_connector_at(doc, branch_id, landing, JOIN_TOL_FT * 25)
        if first is None or second is None or branch is None:
            sub.RollBack()
            return None, u"", [u"the split worked but one of the three "
                               u"connectors was not at the crossing "
                               u"afterwards"]

        fitting = None
        notes = []
        for pair in ((first, second), (second, first)):
            # The halves are not always interchangeable, so the other order
            # is tried rather than assumed to be the same call.
            try:
                fitting = doc.Create.NewTeeFitting(pair[0], pair[1], branch)
                break
            except Exception as err:
                notes.append(u"NewTeeFitting: {0}".format(to_text(err)))
                fitting = None
                first = connector_at(main, landing)
                second = connector_at(other, landing)
                branch = open_connector_at(doc, branch_id, landing,
                                           JOIN_TOL_FT * 25)
                if first is None or second is None or branch is None:
                    break
        if fitting is not None:
            sub.Commit()
            return fitting, u"tee", notes

        # Revit's own call only ever places a square tee. Everything else -
        # every swept junction, every 45 degree drainage branch - has to be
        # placed as a family and turned onto the three directions, which is
        # what Trim/Extend does and what this does next.
        if not by_hand:
            notes.append(u"placing the junction family by hand is turned off "
                         u"in Settings")
            sub.RollBack()
            return None, u"", notes
        instance, attempts = place_junction_by_hand(doc, main, other,
                                                    branch_id, landing)
        notes.extend(attempts)
        if instance is not None:
            sub.Commit()
            return instance, u"junction family placed by hand", notes

        sub.RollBack()
        return None, u"", notes
    except Exception as err:
        try:
            sub.RollBack()
        except Exception:
            pass
        return None, u"", [to_text(err)]


# ======================================================================
# placing the junction family by hand
# ======================================================================
# Revit refuses NewTeeFitting the moment the branch is not square to the run
# - "the angle between them is too small or too large" - which rules out
# every swept and every 45 degree drainage junction there is. Revit's own
# Trim/Extend does not use that call; it places the routing preference
# family and turns it onto the three directions. So does this.


def connector_direction(connector):
    """A connector points out of the element it belongs to."""
    try:
        basis = connector.CoordinateSystem.BasisZ
        return (float(basis.X), float(basis.Y), float(basis.Z))
    except Exception:
        return None


def connector_origin(connector):
    try:
        return geom.to_pt(connector.Origin)
    except Exception:
        return None


def opposite(direction):
    if direction is None:
        return None
    return (-direction[0], -direction[1], -direction[2])


def connector_id(connector):
    try:
        return int(connector.Id)
    except Exception:
        return -1


def connector_by_id(element, wanted):
    for connector in connectors(element):
        if connector_id(connector) == wanted:
            return connector
    return None


def classify_three(cons):
    """The run pair and the branch.

    The two connectors pointing most nearly opposite each other are the run,
    whatever is left is the branch. True of a tee, a lateral and a swept
    junction alike, which is why it is worked out rather than assumed from
    the order the family happens to list them in.
    """
    best = None
    for first in range(len(cons)):
        for second in range(first + 1, len(cons)):
            one = connector_direction(cons[first])
            two = connector_direction(cons[second])
            if one is None or two is None:
                continue
            angle = geom.angle_between(one, two)
            if best is None or angle > best[0]:
                best = (angle, first, second)
    if best is None:
        return None
    _angle, first, second = best
    rest = [x for x in range(len(cons)) if x not in (first, second)]
    if not rest:
        return None
    return cons[first], cons[second], cons[rest[0]]


def set_angle_parameter(instance, radians_value):
    """Drive the family's own angle, where it has one."""
    try:
        parameters = list(instance.Parameters)
    except Exception:
        return False
    for parameter in parameters:
        try:
            if parameter.IsReadOnly:
                continue
            if parameter.StorageType != StorageType.Double:
                continue
            name = to_text(parameter.Definition.Name).lower()
        except Exception:
            continue
        if u"angle" not in name:
            continue
        try:
            parameter.Set(float(radians_value))
            return True
        except Exception:
            continue
    return False


def far_end_of(element, point):
    ends = ends_of(element)
    if ends is None:
        return None
    return ends[0] if geom.length(ends[0], point) > \
        geom.length(ends[1], point) else ends[1]


def turn(doc, element_id, about, axis, angle):
    if axis is None or abs(angle) < 1e-9:
        return True
    try:
        start = XYZ(about.x, about.y, about.z)
        end = XYZ(about.x + axis[0], about.y + axis[1], about.z + axis[2])
        ElementTransformUtils.RotateElement(doc, element_id,
                                            Line.CreateBound(start, end),
                                            angle)
        return True
    except Exception:
        return False


def connector_size(connector):
    """A connector's size, for the report and for matching one to another."""
    try:
        return u"r{0:.1f}".format(connector.Radius * 304.8)
    except Exception:
        pass
    try:
        return u"{0:.0f}x{1:.0f}".format(connector.Width * 304.8,
                                         connector.Height * 304.8)
    except Exception:
        return u"?"


def match_size(target, source):
    """Make a fitting's connector the size of the pipe it has to meet.

    NewFamilyInstance places a fitting at its type's default size and leaves
    it there. Revit's own NewTeeFitting sizes the fitting from the pipes it
    is given; placing the family by hand does not, so the junction comes out
    correct in every way except that it is the wrong size - which is worse
    than failing, because it looks finished.

    Connector.Radius has a setter on a family instance's connector, and
    setting it drives the family's own size parameters, so this is the one
    call that does it rather than guessing at parameter names.
    """
    try:
        target.Radius = source.Radius
        return True
    except Exception:
        pass
    try:
        target.Height = source.Height
        target.Width = source.Width
        return True
    except Exception:
        return False


def required_angles(options, want_branch):
    """The run-to-branch angle each way round the main."""
    return [geom.angle_between(option[0], want_branch) for option in options]


def choose_assignment(natural, wanted, tolerance_deg):
    """Which way round the fitting goes on the main, or -1 for neither.

    A junction's branch sits at some angle to one of its run connectors and
    at 180 minus that to the other, so a family that looks 90 degrees wrong
    one way round is exact the other way. Both are tested before the family
    is called unsuitable; picking one and then driving the family's angle
    parameter to suit it turns a family that fits perfectly into a refusal,
    and does it only sometimes, depending on which way round the fitting
    happened to be placed.
    """
    for index, required in enumerate(wanted):
        if abs(required - natural) <= tolerance_deg:
            return index
    return -1


def junction_setup(doc, half_a, half_b, branch_id, point):
    """Everything about the junction that does not depend on the family.

    The two ways round, the run-to-branch angle each way, and which half of
    the main the water comes from.
    """
    wide = JOIN_TOL_FT * 25
    branch = doc.GetElement(branch_id)
    pipe_a = connector_at(half_a, point, wide)
    pipe_b = connector_at(half_b, point, wide)
    pipe_c = open_connector_at(doc, branch_id, point, wide)
    if pipe_a is None or pipe_b is None or pipe_c is None or branch is None:
        return None, u"a pipe had no connector at the crossing"

    # What the fitting's own connectors have to point, which is the
    # opposite of what the pipes' connectors point.
    want_a = opposite(connector_direction(pipe_a))
    want_b = opposite(connector_direction(pipe_b))
    want_c = opposite(connector_direction(pipe_c))
    far_a = far_end_of(half_a, point)
    far_b = far_end_of(half_b, point)
    far_c = far_end_of(branch, point)
    if None in (want_a, want_b, want_c, far_a, far_b, far_c):
        return None, u"a connector would not give up its direction"

    options = [(want_a, want_b, far_a, far_b, half_a, half_b),
               (want_b, want_a, far_b, far_a, half_b, half_a)]
    setup = {
        u"options": options,
        u"wanted": required_angles(options, want_c),
        u"want_c": want_c,
        u"far_c": far_c,
        u"branch": branch,
        u"pipes": (pipe_a, pipe_b, pipe_c),
        u"upstream": geom.upstream_of(far_a, far_b),
        u"flow": geom.unit3(far_a, far_b) if far_a.z >= far_b.z
                 else geom.unit3(far_b, far_a),
        u"travel": geom.unit3(far_c, point),
    }
    return setup, u""


def ways_round(setup):
    """The two ways round, flow-correct one first.

    A swept junction's arm leans back towards where the water comes from,
    so the run connector making the acute angle with the arm belongs on the
    upstream half. Nothing about the three connector directions says which
    half that is - both ways round satisfy every angle - so it has to be
    asked separately, and it is the whole difference between a junction that
    sweeps with the flow and one that faces back up it.
    """
    wanted = setup[u"wanted"]
    upstream = setup[u"upstream"]
    if upstream == geom.UPSTREAM_UNKNOWN:
        return [0, 1], u"the main is level, so the flow could not be read"
    right = []
    wrong = []
    for index in (0, 1):
        first_is_upstream = (upstream == index)
        if geom.sweeps_with_the_flow(wanted[index], first_is_upstream):
            right.append(index)
        else:
            wrong.append(index)
    return right + wrong, u""


def verify_placement(instance, ids, wants, tolerance_deg):
    """Did the fitting actually land pointing where it had to?

    Checked rather than assumed, because every failure so far in this part
    of the tool has looked finished.
    """
    worst = 0.0
    for connector_ref, want in zip(ids, wants):
        connector = connector_by_id(instance, connector_ref)
        if connector is None:
            return False, 180.0
        off = geom.angle_between(connector_direction(connector), want)
        if off > worst:
            worst = off
    return worst <= tolerance_deg * 2.0, worst


def try_junction_symbol(doc, symbol, half_a, half_b, branch_id, point,
                        tolerance_deg, way_round):
    """Place one junction family one way round, size it, turn it, join it.

    Everything sits in a sub-transaction that rolls back unless all three
    connections take and the fitting is pointing where it was asked to, so
    a family that does not suit costs nothing and the next one is tried.
    """
    import math

    sub = SubTransaction(doc)
    sub.Start()
    try:
        setup, trouble = junction_setup(doc, half_a, half_b, branch_id, point)
        if setup is None:
            sub.RollBack()
            return None, trouble
        options = setup[u"options"]
        wanted = setup[u"wanted"]
        want_c = setup[u"want_c"]
        far_c = setup[u"far_c"]
        branch = setup[u"branch"]
        pipe_a, pipe_b, pipe_c = setup[u"pipes"]
        option = options[way_round]
        required = wanted[way_round]

        try:
            if not symbol.IsActive:
                symbol.Activate()
                doc.Regenerate()
        except Exception:
            pass

        instance = doc.Create.NewFamilyInstance(
            XYZ(point.x, point.y, point.z), symbol,
            StructuralType.NonStructural)
        doc.Regenerate()

        cons = connectors(instance)
        if len(cons) != 3:
            sub.RollBack()
            return None, u"the family has {0} connectors, not three".format(
                len(cons))
        picked = classify_three(cons)
        if picked is None:
            sub.RollBack()
            return None, u"the family's connectors could not be sorted"

        # Size it before anything else: a bigger fitting is a longer one, so
        # every position read before the resize would be wrong afterwards.
        for target, source in ((picked[0], pipe_a), (picked[1], pipe_b),
                               (picked[2], pipe_c)):
            match_size(target, source)
        doc.Regenerate()
        cons = connectors(instance)
        picked = classify_three(cons)
        if picked is None:
            sub.RollBack()
            return None, u"the family's connectors could not be sorted after " \
                         u"it was sized"

        natural = geom.angle_between(connector_direction(picked[0]),
                                     connector_direction(picked[2]))
        if abs(required - natural) > tolerance_deg:
            # The family's own angle, where it has one. Tried only after the
            # way round has been fixed, so it can never be used to force a
            # family onto the way round it does not suit.
            if set_angle_parameter(instance, math.radians(required)):
                doc.Regenerate()
                cons = connectors(instance)
                picked = classify_three(cons)
                if picked is None:
                    sub.RollBack()
                    return None, u"its connectors moved when its angle was set"
                natural = geom.angle_between(connector_direction(picked[0]),
                                             connector_direction(picked[2]))
        if abs(required - natural) > tolerance_deg:
            sub.RollBack()
            return None, (u"its branch sits at {0:.1f} degrees to its run and "
                          u"this way round needs {1:.1f}".format(
                              natural, required))

        run_one, run_two, branch_con = picked
        ids = (connector_id(run_one), connector_id(run_two),
               connector_id(branch_con))
        wants = (option[0], option[1], want_c)

        turns = geom.orientation_for(connector_direction(run_one),
                                     connector_direction(branch_con),
                                     option[0], want_c)
        axis_one, angle_one, axis_two, angle_two, left = turns
        if left > tolerance_deg * 2.0:
            sub.RollBack()
            return None, (u"it could not be turned onto the branch, {0:.1f} "
                          u"degrees out".format(left))

        turn(doc, instance.Id, point, axis_one, angle_one)
        doc.Regenerate()
        turn(doc, instance.Id, point, axis_two, angle_two)
        doc.Regenerate()

        run_one = connector_by_id(instance, ids[0])
        run_two = connector_by_id(instance, ids[1])
        branch_con = connector_by_id(instance, ids[2])
        if run_one is None or run_two is None or branch_con is None:
            sub.RollBack()
            return None, u"the fitting's connectors went missing after the turn"

        # Register it on where its own axes cross, not on its insertion
        # point: a swept junction's branch meets its run part way along.
        meeting = geom.closest_point_between(
            connector_origin(run_one), opposite(connector_direction(run_one)),
            connector_origin(branch_con),
            opposite(connector_direction(branch_con)))
        shift = XYZ(point.x - meeting.x, point.y - meeting.y,
                    point.z - meeting.z)
        try:
            ElementTransformUtils.MoveElement(doc, instance.Id, shift)
        except Exception as err:
            sub.RollBack()
            return None, u"it would not move onto the crossing: {0}".format(
                to_text(err))
        doc.Regenerate()

        good, worst = verify_placement(instance, ids, wants, tolerance_deg)
        if not good:
            sub.RollBack()
            return None, u"it ended up {0:.1f} degrees off after the " \
                         u"turn".format(worst)

        run_one = connector_by_id(instance, ids[0])
        run_two = connector_by_id(instance, ids[1])
        branch_con = connector_by_id(instance, ids[2])

        # Cut the three pipes back to the fitting's own ends, which is the
        # half of trim and extend that placing a family does not do.
        for element, far, connector in (
                (option[4], option[2], run_one),
                (option[5], option[3], run_two),
                (branch, far_c, branch_con)):
            landing = connector_origin(connector)
            if landing is None:
                sub.RollBack()
                return None, u"a fitting connector had no position"
            done, why = restretch(element, far, landing)
            if not done:
                sub.RollBack()
                return None, u"a pipe would not cut back: {0}".format(why)
        doc.Regenerate()

        wide = JOIN_TOL_FT * 25
        joined = 0
        for element, connector_ref in ((option[4], ids[0]),
                                       (option[5], ids[1]),
                                       (branch, ids[2])):
            fitting_connector = connector_by_id(instance, connector_ref)
            if fitting_connector is None:
                continue
            pipe_connector = connector_at(
                element, connector_origin(fitting_connector), wide)
            if pipe_connector is None:
                continue
            try:
                pipe_connector.ConnectTo(fitting_connector)
                joined += 1
            except Exception:
                continue
        doc.Regenerate()

        if joined < 3:
            sub.RollBack()
            return None, u"only {0} of the three ends would join".format(
                joined)

        good, worst = verify_placement(instance, ids, wants, tolerance_deg)
        if not good:
            sub.RollBack()
            return None, u"joining pulled it {0:.1f} degrees off".format(worst)

        sizes = u"/".join([connector_size(connector_by_id(instance, one))
                           for one in ids])
        sub.Commit()
        return instance, u"arm at {0:.1f} degrees to the run, sized {1}, " \
                         u"{2:.2f} degrees off, joined".format(
                             natural, sizes, worst)
    except Exception as err:
        try:
            sub.RollBack()
        except Exception:
            pass
        return None, to_text(err)


def place_junction_by_hand(doc, half_a, half_b, branch_id, point,
                           tolerance_deg=1.5):
    """Try every junction family the pipe type offers, the right way round
    first."""
    attempts = []
    setup, trouble = junction_setup(doc, half_a, half_b, branch_id, point)
    if setup is None:
        return None, [trouble]

    order, note = ways_round(setup)
    if note:
        attempts.append(note)
    flow, travel = setup[u"flow"], setup[u"travel"]
    with_flow = (flow is not None and travel is not None and
                 geom.branch_arrives_with_the_flow(flow, travel))
    attempts.append(u"the main falls towards its {0} end; the branch arrives "
                    u"{1} the flow".format(
                        u"first" if setup[u"upstream"] == 1 else
                        (u"second" if setup[u"upstream"] == 0 else u"neither"),
                        u"with" if with_flow else u"against"))
    if flow is not None and travel is not None and not with_flow:
        attempts.append(u"a branch arriving against the flow cannot be swept "
                        u"in - a junction facing the other way is a different "
                        u"fitting and a different piece of design")

    for family_name, symbol in junction_symbols(doc, half_a):
        for way_round in order:
            instance, why = try_junction_symbol(
                doc, symbol, half_a, half_b, branch_id, point,
                tolerance_deg, way_round)
            attempts.append(u"{0} [way {1}, needs {2:.1f} degrees]: {3}".format(
                family_name, way_round, setup[u"wanted"][way_round], why))
            if instance is not None:
                return instance, attempts
    if len(attempts) <= 2:
        attempts.append(u"the pipe type offers no junction family to try")
    return None, attempts


# ======================================================================
# squaring an angled branch into the main
# ======================================================================
# The last resort, for a pipe type whose only junction family is a plain
# square tee. The tee slides a little way along the main, a short stub runs
# square out of it, and a bend turns the branch into the stub. Every fitting
# is placed by Revit's own calls, so the families come from the routing
# preferences and the pipes are trimmed the way Revit trims them.


def builtin(name):
    try:
        return getattr(BuiltInParameter, name)
    except Exception:
        return None


def id_parameter(element, names):
    for name in names:
        member = builtin(name)
        if member is None:
            continue
        try:
            parameter = element.get_Parameter(member)
        except Exception:
            continue
        if parameter is None:
            continue
        try:
            return parameter.AsElementId()
        except Exception:
            continue
    return None


def double_parameter(element, names):
    for name in names:
        member = builtin(name)
        if member is None:
            continue
        try:
            parameter = element.get_Parameter(member)
        except Exception:
            continue
        if parameter is None:
            continue
        try:
            return parameter.AsDouble()
        except Exception:
            continue
    return None


DIAMETER_PARAMS = (u"RBS_PIPE_DIAMETER_PARAM",)
OUTER_PARAMS = (u"RBS_PIPE_OUTER_DIAMETER", u"RBS_PIPE_DIAMETER_PARAM")


def outside_diameter(pipe):
    value = double_parameter(pipe, OUTER_PARAMS)
    return value if value and value > 0 else 0.0


def copy_pipe(doc, template, start, end):
    """A new pipe on the same system, type, level and size as another."""
    system_id = id_parameter(template, (u"RBS_PIPING_SYSTEM_TYPE_PARAM",))
    level_id = id_parameter(template, (u"RBS_START_LEVEL_PARAM",))
    if system_id is None or level_id is None:
        return None, u"the branch has no system or level to copy"
    try:
        made = Pipe.Create(doc, system_id, template.GetTypeId(), level_id,
                           XYZ(start.x, start.y, start.z),
                           XYZ(end.x, end.y, end.z))
    except Exception as err:
        return None, u"the stub would not be created: {0}".format(to_text(err))
    size = double_parameter(template, DIAMETER_PARAMS)
    if size:
        member = builtin(u"RBS_PIPE_DIAMETER_PARAM")
        try:
            parameter = made.get_Parameter(member)
            if parameter is not None and not parameter.IsReadOnly:
                parameter.Set(size)
        except Exception:
            pass
    return made, u""


def square_into_main(doc, main, branch_id, crossing, stub_ft):
    """Tee on the main, stub square out of it, bend into the branch."""
    notes = []
    sub = SubTransaction(doc)
    sub.Start()
    try:
        branch = doc.GetElement(branch_id)
        main_ends = ends_of(main)
        branch_ends = ends_of(branch)
        if main_ends is None or branch_ends is None:
            sub.RollBack()
            return None, [u"a centreline could not be read"]

        main_dir = geom.unit3(main_ends[0], main_ends[1])
        if geom.length(branch_ends[0], crossing) < \
                geom.length(branch_ends[1], crossing):
            near, far = branch_ends[0], branch_ends[1]
        else:
            near, far = branch_ends[1], branch_ends[0]
        branch_dir = geom.unit3(far, near)
        if main_dir is None or branch_dir is None:
            sub.RollBack()
            return None, [u"a direction could not be worked out"]

        tee_point, bend_point = geom.square_junction(
            crossing, main_dir, branch_dir, stub_ft)
        if tee_point is None:
            sub.RollBack()
            return None, [u"the branch is in line with the main, so there is "
                          u"nothing to square it into"]

        run = geom.plan_length(main_ends[0], main_ends[1])
        along = geom.plan_length(main_ends[0], tee_point)
        if run < EPS or along < JOIN_TOL_FT or along > run - JOIN_TOL_FT:
            sub.RollBack()
            return None, [u"a square tee would fall off the end of the main; "
                          u"shorten the stub in Settings or bring the branch "
                          u"in further along"]

        done, why = restretch(branch, far, bend_point)
        if not done:
            sub.RollBack()
            return None, [u"the branch would not pull back to the bend: "
                          u"{0}".format(why)]
        doc.Regenerate()

        stub, why = copy_pipe(doc, branch, bend_point, tee_point)
        if stub is None:
            sub.RollBack()
            return None, [why]
        doc.Regenerate()
        stub_id = stub.Id

        wide = JOIN_TOL_FT * 25
        at_bend_branch = open_connector_at(doc, branch_id, bend_point, wide)
        at_bend_stub = open_connector_at(doc, stub_id, bend_point, wide)
        if at_bend_branch is None or at_bend_stub is None:
            sub.RollBack()
            return None, [u"the branch and the stub did not meet at the bend"]
        try:
            doc.Create.NewElbowFitting(at_bend_branch, at_bend_stub)
        except Exception as err:
            sub.RollBack()
            return None, [u"the bend was refused: {0}".format(to_text(err))]
        doc.Regenerate()

        landing = project_onto(doc.GetElement(main.Id), tee_point)
        try:
            new_id = PlumbingUtils.BreakCurve(
                doc, main.Id, XYZ(landing.x, landing.y, landing.z))
        except Exception as err:
            sub.RollBack()
            return None, [u"the main would not split at the tee: {0}".format(
                to_text(err))]
        doc.Regenerate()
        live_main = doc.GetElement(main.Id)
        other = doc.GetElement(new_id)
        if live_main is None or other is None:
            sub.RollBack()
            return None, [u"the main would not split at the tee"]

        first = connector_at(live_main, landing, wide)
        second = connector_at(other, landing, wide)
        if first is None or second is None:
            sub.RollBack()
            return None, [u"the split main had no connector at the tee"]
        unjoin(first, second)
        doc.Regenerate()

        fitting = None
        for _attempt in (0, 1):
            first = connector_at(doc.GetElement(main.Id), landing, wide)
            second = connector_at(doc.GetElement(new_id), landing, wide)
            at_tee = open_connector_at(doc, stub_id, landing, wide)
            if first is None or second is None or at_tee is None:
                notes.append(u"a connector was not at the tee after the split")
                break
            pair = (first, second) if _attempt == 0 else (second, first)
            try:
                fitting = doc.Create.NewTeeFitting(pair[0], pair[1], at_tee)
                break
            except Exception as err:
                notes.append(u"square NewTeeFitting: {0}".format(to_text(err)))
                fitting = None
        if fitting is None:
            sub.RollBack()
            return None, notes or [u"the square tee was refused"]

        sub.Commit()
        return fitting, notes
    except Exception as err:
        try:
            sub.RollBack()
        except Exception:
            pass
        return None, [to_text(err)]


def place_takeoff(doc, main, branch_id, point):
    """The fallback: a takeoff on the uncut main."""
    try:
        branch = open_connector_at(doc, branch_id, point, JOIN_TOL_FT * 25)
        if branch is None:
            return None, u"the branch has no connector at the crossing"
        return doc.Create.NewTakeoffFitting(branch, main), u""
    except Exception as err:
        return None, to_text(err)


def place_bend(doc, main_connector, branch_id, point, union):
    """An elbow where the two runs turn into each other, a union where they
    turn out to be in line."""
    try:
        first = connector_by_key(doc, main_connector)
        second = open_connector_at(doc, branch_id, point, JOIN_TOL_FT * 25)
        if first is None or second is None:
            return None, u"a connector went missing before the fitting"
        if union:
            return doc.Create.NewUnionFitting(first, second), u""
        return doc.Create.NewElbowFitting(first, second), u""
    except Exception as err:
        return None, to_text(err)


def log_offer(doc, pipe, angle):
    names, counts, detail = routing_offer(doc, pipe)
    log(u"junction refused at {0:.1f} degrees; routing offers {1}{2}".format(
        angle, u", ".join(names) if names else u"nothing",
        u" ({0})".format(detail) if detail else u""))
    return names, counts, detail
