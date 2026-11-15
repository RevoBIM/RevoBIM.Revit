# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM Click System - route a service by clicking
#
# Click a run, then click in space, and the service grows to
# that point: the run itself carries on to the corner, a 90
# degree bend goes in, and a new length runs out to the click.
# Every click after that does the same thing again from the
# end of the last one, until Escape.
#
# ONE OPERATION, USED EVERY TIME
#
#   extend the current length to the corner
#   put a bend at the corner
#   run a new length from the corner to the click
#
# The corner is the click projected back onto the current
# length's own axis, so the turn is exactly 90 degrees by
# construction rather than by rounding.
#
# The first click is the same operation with one extra step:
# the current length is an existing run, so where the corner
# falls inside it, it is cut there and whatever lies beyond
# is let go. That is what "split at the point of the bend"
# means - the first leg is not a new piece bolted onto the
# run, it IS the run, carried on to the corner.
#
# Every click after the first extends lengths this tool made
# itself, which have a free end and nothing to let go of, so
# nothing is ever cut again and the whole route stays one
# connected system.
#
# A BANK OF SERVICES
#
# Select several parallel runs before pressing the button and
# they are all routed at once, staying parallel and keeping
# their spacing round every corner.
#
# A bank is NOT the leader's route copied sideways. Two pipes
# side by side running east, translated 300mm north, are
# 300mm apart on the leg that runs east and exactly on top of
# each other on the leg that turns north. Spacing has to be
# measured square to each leg, which makes each strand a
# parallel OFFSET of the leader's route: every leg shifted
# sideways by the same distance, and the corner where the
# shifted legs cross. The outer strand turns later than the
# inner one, which is what keeps the bank square across
# itself all the way round.
#
# Spacing straight through the routing plane - services
# stacked one above another in a plan route - is a plain
# shift and needs none of that, so an offset is split into
# the two parts and each is handled the way it needs.
# ==========================================================

import so_clr  # noqa: F401  assembly references first

from Autodesk.Revit.DB import XYZ
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException

import so_core
import so_model
import so_command_host
import angle_prompt
from so_core import mm_to_ft, ft_to_mm, eid_value, to_text, MIN_SEGMENT_MM

MIN_LEG_MM = so_core.MIN_LEG_MM


class RunFilter(ISelectionFilter):
    """Pipes, ducts, cable tray and conduit, and nothing else."""

    def AllowElement(self, element):
        try:
            return so_model.is_supported(element)
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return True


# ---------------------------------------------------------
# Where a click in space really is
# ---------------------------------------------------------

def flatten(point, anchor, view):
    """Bring a picked point onto the plane the route lives in.

    PickPoint hands back a point on the view's work plane,
    which in a plan is the level - not the height the service
    is at. Projecting it onto the plane through the current
    end, parallel to the view, fixes that: in a plan it keeps
    the run at its own elevation, and in a section it keeps it
    at its own depth. One rule covers both.
    """
    try:
        normal = view.ViewDirection
        if normal is None or normal.GetLength() < so_core.PARALLEL_TOL:
            return point
        normal = normal.Normalize()
    except Exception:
        return point
    return point - normal.Multiply((point - anchor).DotProduct(normal))


class Fall(object):
    """The gradient a route is being carried at.

    A click in a plan lands on a level work plane, so a route
    set out from those clicks comes out dead flat unless the
    fall is put back deliberately. Every corner and every end
    is therefore worked out in PLAN and then dropped onto the
    gradient, which is what keeps each new length at the same
    fall as the run it came from.

    Only in a plan. In a section or an elevation the click's
    own height is what the user meant and is used as picked.
    """

    def __init__(self, axis, view):
        self.up = XYZ.BasisZ
        self.grade = None
        self.plan_view = False
        try:
            normal = view.ViewDirection.Normalize()
            self.plan_view = abs(normal.DotProduct(self.up)) > 0.999
        except Exception:
            self.plan_view = False
        if self.plan_view:
            self.grade = so_core.gradient(axis, self.up)

    @property
    def live(self):
        return self.plan_view and so_core.is_sloped(self.grade)

    def flat(self, point, anchor):
        """A point brought onto the level plane through an anchor."""
        if not self.live:
            return point
        return point + self.up.Multiply(
            (anchor - point).DotProduct(self.up))

    def drop(self, start, plan_point):
        """A plan position put back onto the gradient."""
        if not self.live:
            return plan_point
        return so_core.with_fall(start, plan_point, self.up, self.grade)

    def flatten_direction(self, direction):
        if not self.live:
            return direction
        level = direction - self.up.Multiply(direction.DotProduct(self.up))
        if level.GetLength() < so_core.PARALLEL_TOL:
            return direction
        return level.Normalize()

    def describe(self):
        return so_core.describe_gradient(self.grade)


def is_end_connected(element, point):
    connector = so_model.connector_near(element, point)
    if connector is None:
        return False
    try:
        return connector.IsConnected
    except Exception:
        return False


# ---------------------------------------------------------
# One click's worth of routing
# ---------------------------------------------------------

def _extend(element, keep_point, new_end):
    """Move one end of a length, leaving the other alone."""
    ends = so_model.location_line(element)
    if ends is None:
        return False
    start, end = ends
    if start.DistanceTo(keep_point) <= end.DistanceTo(keep_point):
        return so_model.set_line(element, start, new_end)
    return so_model.set_line(element, end, new_end)


def first_step(doc, element, corner, direction, record):
    """Take the run over at the corner.

    Returns (current, anchor_start), or None having said why.

    Where the corner falls inside the run it is cut there and
    everything beyond is let go - the first leg is not a new
    piece bolted onto the run, it IS the run carried on to the
    corner, which is what "split at the point of the bend"
    means.
    """
    ends = so_model.location_line(element)
    if ends is None:
        record['reason'] = (u'Only straight runs can be routed from - that one '
                            u'is an arc or has no centreline.')
        return None

    anchor_start = _behind_end(element, direction)
    far_end = _ahead_end(element, direction)

    reach = (corner - anchor_start).DotProduct(direction)
    length = (far_end - anchor_start).DotProduct(direction)

    if reach > length:
        # The corner is past the end of this run. Growing the
        # run to reach it is right where that end is free, and
        # wrong where it is not - that would drive the run
        # straight through whatever it is joined to.
        if is_end_connected(element, far_end):
            record['reason'] = (
                u'The corner lands {0:.0f}mm past the end of that run, and it '
                u'is joined to something there. Click the corner within this '
                u'length, or start from the last run in the chain.'
                .format(ft_to_mm(reach - length)))
            return None
        so_model.note(record, u'The run was grown to reach the corner.')
        return element, anchor_start

    if ft_to_mm(length - reach) < MIN_LEG_MM:
        # Near enough the end to just use the end.
        return element, anchor_start

    keep, drop, how = so_model.split_at(doc, element, corner, direction)
    if keep is None or drop is None:
        record['reason'] = u'The run would not split at the corner ({0}).'.format(how)
        return None

    so_model.disconnect_all(keep, drop)
    if is_end_connected(drop, corner):
        so_model.note(record,
                      u'The rest of that run is still joined onward and has '
                      u'been left where it is.')
    so_model.note(record, u'Split at the corner; what lies beyond is let go.')
    return keep, anchor_start


def selected_runs(uidoc, doc):
    """Supported runs already selected, in a stable order."""
    found = []
    try:
        ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        return found
    for element_id in ids:
        element = doc.GetElement(element_id)
        if element is None:
            continue
        if not so_model.is_supported(element):
            continue
        if so_model.axis_of(element) is None:
            continue
        found.append(element)
    found.sort(key=lambda e: eid_value(e.Id))
    return found


def check_parallel(elements):
    """All parallel, or say so and stop.

    A bank built from runs that are only nearly parallel comes
    out wrong in a way that is very hard to see afterwards, so
    this refuses rather than doing its best.
    """
    axes = [so_model.axis_of(e) for e in elements]
    parallel, worst = so_core.axes_parallel(axes)
    if parallel:
        return True, u''
    return False, (u'Elements not parallel. User must manually review them.\n\n'
                   u'The worst pair is {0:.2f} degrees apart, and this tool '
                   u'allows {1:.2f}. Nothing has been changed.'
                   .format(worst, so_core.PARALLEL_DEG))


def bank_offsets(elements, leader, direction, normal):
    """How far each run sits from the leader, split two ways.

    lateral        across the routing plane, which is the part
                   that needs the legs offset and the corners
                   re-crossed
    through_plane  straight out of it, which is a plain shift
    """
    side = so_core.cross(normal, direction)
    base = _behind_end(leader, direction)
    offsets = []
    for element in elements:
        start = _behind_end(element, direction)
        gap = start - base
        gap = gap - direction.Multiply(gap.DotProduct(direction))
        offsets.append((gap.DotProduct(side), gap.DotProduct(normal)))
    return offsets


def _behind_end(element, direction):
    """The end of a run that lies behind, along a direction."""
    start, end = so_model.location_line(element)
    return start if (start - end).DotProduct(direction) < 0 else end


def _blank(element=None, reason=u''):
    return {
        'ok': False,
        'element_id': eid_value(element.Id) if element is not None else 0,
        'kind': so_model.kind_of(element) if element is not None else u'',
        'notes': [], 'problems': [], 'created': [],
        'reason': reason,
        'mode': u'click',
    }


def run(uiapp):
    """One command press. Returns the list of records."""
    so_command_host.set_uiapp(uiapp)

    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        return [_blank(None, u'There is no open model.')]

    doc = uidoc.Document
    try:
        view = doc.ActiveView
    except Exception:
        view = None
    if view is None:
        return [_blank(None, u'There is no active view to route in.')]

    try:
        normal = view.ViewDirection.Normalize()
    except Exception:
        return [_blank(None, u'This view has no direction to route across.')]

    settings = so_core.load_settings()

    # A selection made before the button was pressed is the
    # whole input: no run needs picking, and several parallel
    # runs are routed together as a bank.
    chosen = selected_runs(uidoc, doc)
    if len(chosen) > 1:
        parallel, complaint = check_parallel(chosen)
        if not parallel:
            return [_blank(chosen[0], complaint)]
        return _route(uidoc, doc, view, normal, chosen, None, settings)

    if len(chosen) == 1:
        return _route(uidoc, doc, view, normal, chosen, None, settings)

    records = []
    while True:
        try:
            reference = uidoc.Selection.PickObject(
                ObjectType.PointOnElement, RunFilter(),
                u'Click the run to route from  -  Escape to finish')
        except OperationCanceledException:
            break
        except Exception:
            break
        if reference is None:
            break

        element = doc.GetElement(reference.ElementId)
        try:
            click_point = reference.GlobalPoint
        except Exception:
            click_point = None
        if element is None or click_point is None:
            continue

        records.extend(_route(uidoc, doc, view, normal, [element],
                              click_point, settings))
        break

    return records


class Strand(object):
    """One run being routed, and where it sits in the bank."""

    def __init__(self, element, lateral=0.0, through_plane=0.0):
        self.element = element
        self.lateral = lateral
        self.through_plane = through_plane
        self.current = element
        self.anchor_start = None
        self.current_end = None
        self.record = _blank(element)
        self.record['ok'] = True
        self.live = True
        # True while the end of this strand is the top or the
        # bottom of a riser. The next horizontal piece then
        # starts AT that end rather than extending it, because a
        # riser cannot be stretched sideways to reach a corner.
        self.on_riser = False


def _route(uidoc, doc, view, normal, elements, click_point, settings):
    """Every click for this run or bank, until Escape."""
    leader = elements[0]
    strands = [Strand(e) for e in elements]
    started = False
    direction = None
    fall = Fall(so_model.axis_of(leader), view)
    angle = 90.0
    keep_angle = True
    leg_mm = None
    height_mm = 500.0
    rise_angle = 45.0
    lead_mm = 500.0
    pending = None
    ask_again = True
    segments = 0

    while True:
        if ask_again:
            answer = angle_prompt.ask(settings, angle, keep_angle,
                                      len(strands), leg_mm, height_mm,
                                      rise_angle, lead_mm)
            if answer is None:
                break
            action, keep_angle = answer
            ask_again = not keep_angle

            if action[0] == u'vertical':
                # Nothing is placed here. The next click says how
                # far the straight runs before it rises, which is
                # what "press up, then click" means.
                _unused, way, height_mm, rise_angle, lead_mm = action
                pending = (way, height_mm, rise_angle, lead_mm)
            else:
                _unused, angle, leg_mm = action
                pending = None

        prompt = (u'Click where the service goes  -  Escape to change the '
                  u'angle or length'
                  if not started else
                  u'Click again to carry on  -  Escape to change the angle '
                  u'or length')
        try:
            target = uidoc.Selection.PickPoint(prompt)
        except OperationCanceledException:
            # Escape in Revit reopens the prompt rather than
            # ending the run, so the angle or the length can be
            # changed and picking carried straight on. Finish in
            # the prompt is the way out.
            ask_again = True
            continue
        except Exception:
            if not started:
                for strand in strands:
                    strand.record['ok'] = False
                    strand.record['reason'] = (
                        u'This view has no work plane to click points on. '
                        u'Route in a plan, a section or an elevation.')
            break
        if target is None:
            break

        transaction, swallower = so_model.guarded_transaction(
            doc, u'RevoBIM Click System')
        transaction.Start()
        try:
            if not started:
                direction = _bank_direction(leader, target, view)
                # Everything after this is set out in plan and
                # dropped back onto the gradient, so the route
                # runs at the same fall as the run it came from.
                direction = fall.flatten_direction(direction)
                if fall.live:
                    so_model.note(strands[0].record,
                                  u'Carried on at {0}.'.format(fall.describe()))
                _begin(strands, elements, leader, direction, normal)

            if pending is not None:
                way, height_mm, rise_angle, lead_mm = pending
                if not started:
                    # From the CLICK, not from the screen. The
                    # screen rule is only a fallback for when
                    # there is nothing else to go on, and using
                    # it here sent the route off the opposite
                    # way whenever the click was behind the run
                    # - which is where "-143939mm along" came
                    # from.
                    direction = fall.flatten_direction(
                        _bank_direction(leader, target, view))
                    _begin(strands, elements, leader, direction, normal)
                if not _level_change(doc, strands, target, fall, view, normal,
                                     direction, way, height_mm, rise_angle,
                                     lead_mm, started):
                    transaction.RollBack()
                    pending = None
                    ask_again = True
                    continue
                pending = None
                started = True
                segments += 1
                transaction.Commit()
                ask_again = not keep_angle
                continue

            if strands[0].on_riser:
                onward = _lay_from_riser(doc, strands, target, fall, view,
                                         normal)
                if onward is None:
                    transaction.RollBack()
                    ask_again = not keep_angle
                    continue
                direction = onward
                segments += 1
                transaction.Commit()
                ask_again = not keep_angle
                continue

            anchor = strands[0].anchor_start
            flat = flatten(target, anchor, view)
            flat = fall.flat(flat, anchor)
            step = so_core.plan_corner(anchor, direction, flat, angle, leg_mm)
            if not step.get('ok'):
                transaction.RollBack()
                so_model.problem(strands[0].record, step.get('reason', u''))
                ask_again = not keep_angle
                continue

            done = _lay(doc, strands, step, direction, normal, started, fall)
            if not done:
                transaction.RollBack()
                ask_again = not keep_angle
                continue

            if not step['straight']:
                direction = fall.flatten_direction(step['direction'])
            started = True
            segments += 1

            if swallower.seen:
                so_model.note(strands[0].record,
                              u'{0} Revit warning(s) were cleared.'
                              .format(len(swallower.seen)))
            transaction.Commit()
            ask_again = not keep_angle
        except Exception as error:
            try:
                transaction.RollBack()
            except Exception:
                pass
            so_model.problem(strands[0].record, to_text(error))
            break

    return [s.record for s in strands
            if s.record.get('created') or not s.record.get('ok')
            or s.record.get('problems')]


def _rise(doc, strands, plan_direction, height_mm, way, angle, record_of):
    """Take every strand up or down by the same height.

    A BANK STAYS AT THE SAME SPACING BY MOVING AS ONE. Every
    strand gains the same height over the same plan run, from
    its own end, so services stacked above one another stay
    exactly as far apart vertically as they were - which is
    what was asked for.

    Note that parallel sloping legs sit closer together square
    to themselves than they do vertically, by cos(angle): 300mm
    apart vertically is 212mm apart square to a 45 degree leg.
    That is the right trade here - the ask was to hold the
    height between them - but it is worth knowing if the bank
    is tight.
    """
    up = XYZ.BasisZ
    going_up = (way == u'up')

    for strand in strands:
        base = strand.current_end
        top, _direction = so_core.rise_step(base, plan_direction, up,
                                            height_mm, angle, going_up)

        leg = so_model.copy_piece(doc, strand.current, base, top)
        if leg is None:
            so_model.problem(strand.record, u'The rise would not be created.')
            return False
        doc.Regenerate()

        fitting, trouble = so_model.place_elbow(doc, strand.current, leg, base)
        if fitting is None and trouble:
            so_model.problem(strand.record, trouble)

        strand.record.setdefault('created', []).append(
            so_core.eid_value(leg.Id))
        strand.current = leg
        strand.anchor_start = base
        strand.current_end = top
        # The route now ends on a sloping leg, which cannot be
        # stretched sideways to reach a corner, so the next
        # click starts a new piece from its end.
        strand.on_riser = True

    so_model.note(record_of,
                  u'Ran straight, then {0} {1:.0f}mm at {2:g} degrees.'
                  .format(way, height_mm, angle))
    return True


def _level_change(doc, strands, target, fall, view, normal, direction,
                  way, height_mm, angle, lead_mm, started):
    """Run on, turn up or down, then run straight to the click.

    Three pieces and two bends, none of them in plan:

        1  the run carries on for the run-on distance, so the
           turn does not sit right on the end of what was there
        2  it rises or falls by the offset, at the angle
        3  it runs on straight, at the new level, as far as the
           click reaches along it

    The click sets how far piece 3 goes. Everything before it is
    the numbers in the window, which is what makes the whole
    move one press and one click.
    """
    leader = strands[0]

    flat = fall.flat(flatten(target, leader.current_end, view),
                     leader.current_end)
    total_mm = so_core.ft_to_mm((flat - leader.current_end)
                                .DotProduct(direction))

    if total_mm <= 0.0:
        so_model.problem(leader.record,
                         u'That click is behind the run. Click ahead of the '
                         u'way it is going.')
        return False

    # The height is the point of the move and is never given up.
    # The run on shortens and then the angle steepens, in that
    # order, until the whole thing fits what the click allows.
    fit = so_core.fit_level_change(total_mm, height_mm, angle, lead_mm)
    if not fit.get('ok'):
        so_model.problem(leader.record, fit.get('reason', u''))
        return False

    lead_mm = fit['lead_mm']
    angle = fit['angle_deg']
    if fit['changed']:
        so_model.note(leader.record,
                      u'Fitted into the {0:.0f}mm there was: {1}.'
                      .format(total_mm, u', '.join(fit['changed'])))

    # 1 - run on
    if lead_mm > 0.0 or not started:
        corner = leader.current_end + direction.Multiply(mm_to_ft(lead_mm))
        corner = fall.drop(leader.current_end, corner)
        step = {'ok': True, 'straight': True, 'corner': corner,
                'target': corner, 'direction': direction,
                'angle_deg': 90.0, 'kept_mm': lead_mm, 'leg_mm': 0.0}
        if not _lay(doc, strands, step, direction, normal, started, fall):
            return False

    # 2 - up or down
    if not _rise(doc, strands, direction, height_mm, way, angle,
                 leader.record):
        return False

    # 3 - straight on to the click
    return _run_on(doc, strands, direction, flat, fall, normal)


def _run_on(doc, strands, direction, flat, fall, normal):
    """The level piece that leaves a rise and runs to the click."""
    leader = strands[0]
    reach = (flat - leader.current_end).DotProduct(direction)
    if so_core.ft_to_mm(reach) < MIN_LEG_MM:
        so_model.problem(leader.record,
                         u'There is no room left past the rise to land on.')
        return False

    for strand in strands:
        start = strand.current_end
        landing = fall.drop(start, start + direction.Multiply(reach))

        leg = so_model.copy_piece(doc, strand.current, start, landing)
        if leg is None:
            so_model.problem(strand.record,
                             u'The landing length would not be created.')
            return False
        doc.Regenerate()

        fitting, trouble = so_model.place_elbow(doc, strand.current, leg,
                                                start)
        if fitting is None and trouble:
            so_model.problem(strand.record, trouble)

        strand.record.setdefault('created', []).append(
            so_core.eid_value(leg.Id))
        strand.current = leg
        strand.anchor_start = start
        strand.current_end = landing
        strand.on_riser = False

    return True


def _lay_from_riser(doc, strands, target, fall, view, normal):
    """The first horizontal piece after a riser.

    It starts AT the top of the riser rather than extending it -
    a riser cannot be stretched sideways to reach a corner - and
    the bend there is square whichever way it heads, so the
    chosen angle does not come into it.

    The bank's spacing is taken from the LEADER's leg direction
    and applied to each strand's own landing point. Each riser
    top already sits at its own offset, so the target has to be
    offset to match or the strands would all converge on one
    point.
    """
    leader = strands[0]
    base = leader.current_end
    flat = fall.flat(flatten(target, base, view), base)
    if so_core.ft_to_mm((flat - base).GetLength()) < MIN_LEG_MM:
        so_model.problem(leader.record,
                         u'That is too close to the riser to run from.')
        return None
    leg_direction = fall.flatten_direction((flat - base).Normalize())

    for strand in strands:
        start = strand.current_end
        landing = flat
        if strand.lateral or strand.through_plane:
            landing = so_core.offset_end(flat, leg_direction, normal,
                                         strand.lateral, strand.through_plane)
        landing = fall.drop(start, landing)

        leg = so_model.copy_piece(doc, strand.current, start, landing)
        if leg is None:
            so_model.problem(strand.record,
                             u'The new length would not be created.')
            return None
        doc.Regenerate()

        fitting, trouble = so_model.place_elbow(doc, strand.current, leg,
                                                start)
        if fitting is None and trouble:
            so_model.problem(strand.record, trouble)

        strand.record.setdefault('created', []).append(
            so_core.eid_value(leg.Id))
        strand.current = leg
        strand.anchor_start = start
        strand.current_end = landing
        strand.on_riser = False

    return leg_direction


def _ahead_end(element, direction):
    start, end = so_model.location_line(element)
    return end if (end - start).DotProduct(direction) > 0 else start


def _default_direction(leader, view):
    """Which way the run heads, with nothing clicked yet.

    Set Up and Set Down work from the moment the tool opens, so
    the forward end has to be known before any point is picked.
    The run's own axis points whichever way it was drawn, so it
    is taken from the way the run reads on screen instead -
    the same rule left and right use.
    """
    axis = so_model.axis_of(leader)
    screen_right, screen_up = None, None
    try:
        screen_right = view.RightDirection.Normalize()
        screen_up = view.UpDirection.Normalize()
    except Exception:
        pass
    return so_core.travel_direction(axis, screen_right, screen_up)


def _begin(strands, elements, leader, direction, normal):
    """Work out where each strand sits, and which end it leaves."""
    for strand, offset in zip(strands, bank_offsets(elements, leader,
                                                    direction, normal)):
        strand.lateral, strand.through_plane = offset
        strand.anchor_start = _behind_end(strand.element, direction)
        strand.current_end = _ahead_end(strand.element, direction)


def _bank_direction(leader, target, view):
    """Which way along the runs the route heads.

    Decided by the first click rather than assumed, so the bank
    grows away from whichever end the click is past.
    """
    axis = so_model.axis_of(leader)
    start, end = so_model.location_line(leader)
    middle = start + (end - start).Multiply(0.5)
    flat = flatten(target, middle, view)
    return axis if (flat - middle).DotProduct(axis) >= 0 else axis.Negate()


def _lay(doc, strands, step, leg_in, normal, started, fall):
    """Extend, bend and run out - for every strand at once.

    The corners arrive here in plan. Each strand puts its own
    on the gradient from its own fixed end, so a bank of
    sloping runs each carries its own fall rather than being
    levelled onto the leader's.
    """
    leg_out = leg_in if step['straight'] else step['direction']

    for strand in strands:
        if strand.lateral or strand.through_plane:
            corner, target = so_core.strand_route(
                step['corner'], step['target'], leg_in, leg_out, normal,
                strand.lateral, strand.through_plane)
        else:
            corner, target = step['corner'], step['target']

        if fall.live:
            corner = fall.drop(strand.anchor_start, corner)
            target = fall.drop(corner, target)

        if not started:
            taken = first_step(doc, strand.element, corner, leg_in,
                               strand.record)
            if taken is None:
                strand.record['ok'] = False
                return False
            strand.current, strand.anchor_start = taken

        if not _extend(strand.current, strand.anchor_start, corner):
            so_model.problem(strand.record,
                             u'That length would not stretch to the corner.')
            return False

        if step['straight']:
            strand.current_end = corner
            continue

        leg = so_model.copy_piece(doc, strand.current, corner, target)
        if leg is None:
            so_model.problem(strand.record,
                             u'The new length would not be created.')
            return False
        doc.Regenerate()

        fitting, trouble = so_model.place_elbow(doc, strand.current, leg,
                                                corner)
        if fitting is None and trouble:
            so_model.problem(strand.record, trouble)

        strand.record.setdefault('created', []).append(eid_value(leg.Id))
        strand.current = leg
        strand.anchor_start = corner
        strand.current_end = target
        strand.on_riser = False

    if step['straight']:
        doc.Regenerate()
        so_model.note(strands[0].record, u'Carried straight on.')
    return True
