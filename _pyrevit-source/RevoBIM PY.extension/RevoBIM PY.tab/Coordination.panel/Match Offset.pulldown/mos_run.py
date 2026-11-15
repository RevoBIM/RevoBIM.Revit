# -*- coding: utf-8 -*-
"""RevoBIM Match Offset Slope - the run.

Click the main, then click a branch. The branch's horizontal run goes onto the
main's fall, its free end lands on the main's centreline at the point the two
centrelines cross in plan, and a fitting goes in.

One transaction per branch, because the picks sit between the writes. The move
and the fitting are separate transactions inside it only in the sense that the
fitting sits in its own sub-transaction: a refused fitting never costs the
move, and the pipes are left touching so Trim/Extend finishes it by hand in
two clicks.
"""

import mo_clr  # noqa: F401

from Autodesk.Revit.DB import Transaction, TransactionGroup
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

import mo_debug
import mo_model
import mos_geom as geom
import mos_model as slope_model
from mo_core import (
    Report, eid_value, flush_log, format_mm, ft_to_mm, is_on, load_settings,
    log, parse_number, to_text,
)
from mo_run import (
    PREPROCESSOR, drain_failures, failure_text, suppress_dialogs,
)

PIPE_CATEGORIES = (u"pipes",)


class SlopeConfig(object):
    """The slope settings, resolved once before the first pick."""

    def __init__(self, settings):
        self.settings = settings
        self.match_slope = is_on(settings, u"slope_match_slope")
        source = to_text(settings.get(u"slope_source", u"main"))
        self.source = source if self.match_slope else geom.KEEP_SLOPE
        self.fixed_n = parse_number(settings.get(u"slope_fixed_n"), 80.0)
        self.direction = to_text(settings.get(u"slope_direction",
                                              geom.TOWARDS))
        self.trim = is_on(settings, u"slope_trim")
        self.fitting = to_text(settings.get(u"slope_fitting", u"auto"))
        self.hand_fitting = is_on(settings, u"slope_hand_fitting")
        self.square_branch = is_on(settings, u"slope_square_branch")
        self.stub_mm = parse_number(settings.get(u"slope_stub_mm"), 0.0) or 0.0
        self.apparent = is_on(settings, u"slope_apparent")
        self.extend_main = is_on(settings, u"slope_extend_main")
        self.steep = parse_number(settings.get(u"slope_steep_deg"), 46.0)
        self.limit = int(parse_number(settings.get(u"slope_limit"), 400.0))
        self.end_tol = (parse_number(settings.get(u"slope_end_tol_mm"), 1.0)
                        or 1.0) / geom.MM_PER_FT
        self.inline_deg = parse_number(settings.get(u"slope_inline_deg"), 2.0)
        self.in_line = is_on(settings, u"slope_in_line")
        self.pairs = to_text(settings.get(u"slope_repeat",
                                          u"pairs")) == u"pairs"
        self.lateral = (parse_number(settings.get(u"slope_inline_offset_mm"),
                                     50.0) or 50.0) / geom.MM_PER_FT
        self.show_results = to_text(settings.get(u"show_results",
                                                 u"problems"))
        self.debug = is_on(settings, u"debug_report")


# ======================================================================
# the main
# ======================================================================

class Main(object):
    def __init__(self, element):
        self.element = element
        self.id = element.Id
        ends = slope_model.ends_of(element)
        self.start = ends[0] if ends else None
        self.end = ends[1] if ends else None
        self.gradient = (geom.gradient(self.start, self.end)
                         if ends else None)

    def describe(self):
        fall = geom.one_in_n(self.gradient)
        if fall is None:
            return u"level"
        return u"1 in {0}".format(format_mm(fall, 0))


def take_main(doc, element, config, report):
    if not slope_model.is_pipe(element):
        report.problem(u"{0} is not a pipe".format(mo_model.describe(element)))
        return None
    if not slope_model.is_straight(element):
        report.problem(u"{0} is not a straight segment".format(
            mo_model.describe(element)))
        return None
    main = Main(element)
    if main.start is None:
        report.problem(u"{0} has no usable centreline".format(
            mo_model.describe(element)))
        return None
    if geom.plan_length(main.start, main.end) < config.end_tol:
        report.problem(u"{0} is vertical - the main has to be a run in "
                       u"plan".format(mo_model.describe(element)))
        return None
    log(u"main {0} at {1}".format(mo_model.describe(element),
                                  main.describe()))
    if report.debug is not None:
        report.debug.section(u"the main")
        report.debug.pair(u"element", mo_model.describe(element))
        report.debug.pair(u"start", mo_debug.pt(main.start))
        report.debug.pair(u"end", mo_debug.pt(main.end))
        report.debug.pair(u"plan length", mo_debug.mm(
            geom.plan_length(main.start, main.end)) + u" mm")
        report.debug.pair(u"gradient", mo_debug.fall(main.gradient))
    return main


def main_end_connector(main, crossing, tolerance):
    """The connector on the end of the main the crossing is nearest to."""
    near = main.start if geom.plan_length(main.start, crossing) <= \
        geom.plan_length(main.end, crossing) else main.end
    connector = slope_model.connector_at(main.element, near,
                                         max(tolerance, 1.0 / geom.MM_PER_FT))
    return near, connector


# ======================================================================
# one branch
# ======================================================================

def match_branch(doc, main, element, config, report):
    """Put one branch run on the main's fall and join it. True when it moved."""
    name = mo_model.describe(element)

    if eid_value(element.Id) == eid_value(main.id):
        report.problem(u"that is the main itself")
        return False
    if not slope_model.is_pipe(element):
        report.problem(u"{0} is not a pipe".format(name))
        return False
    if not slope_model.is_straight(element):
        report.problem(u"{0} is not a straight segment".format(name))
        return False

    pitch = slope_model.pitch_of(element)
    if pitch > config.steep:
        report.problem(
            u"{0} is pitched {1} degrees, so it is an upright rather than a "
            u"horizontal run - click the pipe the stack comes off".format(
                name, format_mm(pitch)))
        return False

    body = slope_model.walk_run(doc, element, config.steep, config.limit)
    if body.refusal:
        report.problem(u"{0}: {1}".format(name, body.refusal))
        return False
    if not body.pipes:
        report.problem(u"{0}: nothing in the run could be moved".format(name))
        return False

    # Which end faces the main has to be decided before the crossing is
    # known, so the point on the main nearest this pipe stands in for it.
    ends = slope_model.ends_of(element)
    middle = geom.Pt((ends[0].x + ends[1].x) / 2.0,
                     (ends[0].y + ends[1].y) / 2.0,
                     (ends[0].z + ends[1].z) / 2.0)
    towards = slope_model.project_onto(main.element, middle)

    picked, borrowed = slope_model.free_end_of(body, towards)
    if picked is None:
        report.problem(u"{0}: the run has no end to bring to the "
                       u"main".format(name))
        return False
    end_pipe, free_connector = picked
    free_key = slope_model.connector_key(free_connector)
    free_point = geom.to_pt(free_connector.Origin)
    anchor = slope_model.anchor_of(end_pipe, free_connector)
    if anchor is None:
        report.problem(u"{0}: the end pipe has no usable centreline".format(
            name))
        return False

    near_end, main_connector = main_end_connector(main, free_point,
                                                  config.end_tol)
    main_end_free = (main_connector is not None and
                     not slope_model.is_joined(main_connector))

    plan = geom.build_plan(
        main.start, main.end, anchor, free_point,
        config.source, config.direction, config.fixed_n,
        config.end_tol, config.apparent, main_end_free, config.inline_deg,
        config.in_line, config.lateral)

    if report.debug is not None:
        report.debug.section(u"branch {0}".format(mo_model.describe(element)))
        report.debug.pair(u"run walked", u"{0} elements, {1} pipes, {2} "
                          u"uprights".format(body.count, len(body.pipes),
                                             len(body.uprights)))
        report.debug.pair(u"end pipe", mo_model.describe(end_pipe))
        report.debug.pair(u"end was joined and freed", borrowed)
        report.debug.pair(u"anchor", mo_debug.pt(anchor))
        report.debug.pair(u"free end", mo_debug.pt(free_point))
        report.debug.pair(u"branch gradient",
                          mo_debug.fall(plan.branch_gradient))
        report.debug.pair(u"target gradient",
                          mo_debug.fall(plan.target_gradient))
        report.debug.pair(u"t along the main", u"{0:.6f}".format(plan.t_a))
        report.debug.pair(u"t along the branch", u"{0:.6f}".format(plan.t_b))
        report.debug.pair(u"crossing", mo_debug.pt(plan.crossing))
        report.debug.pair(u"off the main's line in plan",
                          mo_debug.mm(plan.lateral) + u" mm")
        report.debug.pair(u"main case", plan.main_case)
        report.debug.pair(u"branch case", plan.branch_case)
        report.debug.pair(u"junction", plan.junction)
        report.debug.pair(u"plan angle", u"{0:.2f} degrees, {1:.2f} off the "
                          u"main line".format(plan.plan_angle,
                                              off_the_line(plan.plan_angle)))
        report.debug.pair(u"main end nearest", mo_debug.pt(near_end))
        report.debug.pair(u"that end is free", main_end_free)
        report.debug.pair(u"extends the main", plan.extends_main)
        report.debug.pair(u"plan accepted", plan.ok)
        if not plan.ok:
            report.debug.pair(u"refused because", plan.refusal)

    if not plan.ok:
        report.problem(u"{0}: {1}".format(name, geom.refusal_text(
            plan.refusal)))
        return False

    if plan.extends_main and not config.extend_main:
        report.problem(
            u"{0}: the crossing falls {1} mm past the end of the main, and "
            u"extending the main is turned off in Settings".format(
                name, format_mm(ft_to_mm(
                    geom.plan_length(near_end, plan.crossing)))))
        return False

    return do_the_move(doc, main, element, body, end_pipe, free_key, anchor,
                       plan, config, report, borrowed, main_connector)


def start(doc, name):
    transaction = Transaction(doc, name)
    transaction.Start()
    options = transaction.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(PREPROCESSOR)
    options.SetClearAfterRollback(True)
    transaction.SetFailureHandlingOptions(options)
    return transaction


def committed(status):
    return to_text(status).lower().find(u"committed") >= 0


def do_the_move(doc, main, element, body, end_pipe, free_key, anchor, plan,
                config, report, borrowed, main_connector):
    """The move and the junction, as two transactions inside one group.

    Two, because a fitting Revit refuses must not cost the move: with both in
    one transaction an unresolved error at the fitting rolls the whole thing
    back, which is exactly what happened in 1.2.0 and arrived as "Revit did
    not commit the move" with the move gone. The group is safe here where a
    group across the picks would not be - nothing pumps the message loop
    between these two.
    """
    name = mo_model.describe(element)
    pinned = []
    group = TransactionGroup(doc, u"RevoBIM Match Offset Slope")
    group.Start()
    transaction = None
    try:
        transaction = start(doc, u"RevoBIM Match Offset Slope - move")

        for element_id in body.ids:
            item = doc.GetElement(element_id)
            if item is not None and mo_model.is_pinned(item):
                pinned.append(element_id)
                try:
                    item.Pinned = False
                except Exception:
                    pass

        if borrowed:
            # A run with no spare end has the joint nearest the main freed
            # and used instead, rather than the run being refused.
            connector = slope_model.connector_by_key(doc, free_key)
            if connector is not None:
                slope_model.unjoin_all(connector)
                doc.Regenerate()

        links = slope_model.release_uprights(doc, body)

        connector = slope_model.connector_by_key(doc, free_key)
        pivot = geom.to_pt(connector.Origin) if connector is not None \
            else plan.crossing
        slope_model.rotate_body(doc, body.ids, pivot, plan.axis, plan.tilt)
        doc.Regenerate()

        # After the tilt the anchor has moved, so the end pipe is re-read
        # rather than the pre-tilt point being reused.
        moved_pipe = doc.GetElement(end_pipe.Id)
        connector = slope_model.connector_by_key(doc, free_key)
        if moved_pipe is None or connector is None:
            raise Exception(u"the end pipe went missing after the tilt")
        live_free = geom.to_pt(connector.Origin)
        ends = slope_model.ends_of(moved_pipe)
        fixed_end = ends[1] if geom.length(ends[0], live_free) < \
            geom.length(ends[1], live_free) else ends[0]

        direction = geom.unit3(fixed_end, live_free)
        landing = geom.stretch_to_plan_point(
            fixed_end, direction, plan.crossing.x, plan.crossing.y)
        if landing is None:
            raise Exception(u"the run does not reach the crossing")

        if report.debug is not None:
            report.debug.pair(u"end pipe before the stretch",
                              u"{0} -> {1}".format(mo_debug.pt(ends[0]),
                                                   mo_debug.pt(ends[1])))
            report.debug.pair(u"end staying put", mo_debug.pt(fixed_end))
            report.debug.pair(u"end going to", mo_debug.pt(landing))

        if config.trim:
            done, order = slope_model.restretch(moved_pipe, fixed_end,
                                                landing)
            if not done:
                raise Exception(u"the end pipe would not stretch: "
                                u"{0}".format(order))
            doc.Regenerate()
            if report.debug is not None:
                after = slope_model.ends_of(doc.GetElement(end_pipe.Id))
                report.debug.pair(u"curve order kept", order)
                report.debug.pair(u"end pipe after the stretch",
                                  u"{0} -> {1}".format(mo_debug.pt(after[0]),
                                                       mo_debug.pt(after[1])))

        # The whole residual, not just the lift: in the in-line case the
        # run is nudged sideways onto the main's line as well, because a
        # union will not take two ends a few millimetres apart.
        shift_x = plan.crossing.x - landing.x
        shift_y = plan.crossing.y - landing.y
        shift_z = plan.crossing.z - landing.z
        slope_model.move_body(doc, body.ids, shift_x, shift_y, shift_z)
        doc.Regenerate()

        slope_model.refit_uprights(doc, links, report)

        for element_id in pinned:
            item = doc.GetElement(element_id)
            if item is not None:
                try:
                    item.Pinned = True
                except Exception:
                    pass

        report.note_pair(u"tilt applied, radians", u"{0:.6f}".format(
            plan.tilt))
        report.note_pair(u"landing before the lift", mo_debug.pt(landing))
        report.note_pair(u"moved by", u"{0} across, {1} up (mm)".format(
            mo_debug.mm((shift_x ** 2 + shift_y ** 2) ** 0.5),
            mo_debug.mm(shift_z)))
        status = transaction.Commit()
    except Exception as err:
        try:
            if transaction is not None:
                transaction.RollBack()
        except Exception:
            pass
        drain_failures(report, u"the move")
        if report.debug is not None:
            report.debug.blew_up(u"the move", to_text(err))
        group.RollBack()
        report.problem(u"{0}: {1}".format(name, to_text(err)))
        return False

    found = drain_failures(report, u"the move")
    if not committed(status):
        said = failure_text(found)
        group.RollBack()
        report.problem(u"{0}: Revit rolled the move back{1}".format(
            name, u" - " + said if said else
            u" without saying why. The debug report has the numbers."))
        return False

    junction = u""
    if config.trim and config.fitting != u"none":
        junction = fit_junction(doc, main, end_pipe.Id, plan, config, report,
                                main_connector, name)
    group.Assimilate()

    fall = geom.one_in_n(plan.target_gradient)
    where = (u"brought in line with the main"
             if plan.main_case == geom.IN_LINE else u"brought to the crossing")
    report.note(u"{0} put on {1} and {2}{3}".format(
        name,
        u"1 in {0}".format(format_mm(fall, 0)) if fall else u"level",
        where,
        u" ({0})".format(junction) if junction else u""))
    report.matched_one()
    log(u"{0} matched: tilt {1:.5f} rad, case {2}, junction {3}".format(
        name, plan.tilt, plan.main_case, plan.junction))
    return True


def fit_junction(doc, main, branch_id, plan, config, report, main_connector,
                 name):
    """The fitting, in its own transaction so a refusal never costs the move.

    A refused fitting is committed rather than rolled back: the split is
    already undone by its own sub-transaction, and where the main was carried
    out to an apparent crossing it has to stay out, because the whole point
    of leaving the pipes touching is that Trim/Extend finishes it by hand.
    """
    transaction = None
    try:
        transaction = start(doc, u"RevoBIM Match Offset Slope - fitting")
        junction = make_junction(doc, main, branch_id, plan, config, report,
                                 main_connector, name)
        status = transaction.Commit()
    except Exception as err:
        try:
            if transaction is not None:
                transaction.RollBack()
        except Exception:
            pass
        drain_failures(report, u"the fitting")
        if report.debug is not None:
            report.debug.blew_up(u"the fitting", to_text(err))
        report.problem(u"{0}: the move is in, but the fitting threw: "
                       u"{1}".format(name, to_text(err)))
        return u""

    found = drain_failures(report, u"the fitting")
    if not committed(status):
        said = failure_text(found)
        report.problem(u"{0}: the move is in, but Revit rolled the fitting "
                       u"back{1}".format(name, u" - " + said if said else
                                         u". The debug report has the "
                                         u"numbers."))
        return u""
    return junction


def make_junction(doc, main, branch_id, plan, config, report,
                  main_connector, name=u"the branch"):
    """Trim and extend, then the fitting - which is what Revit's own command
    does, replicated because there is no API for it.

    PostCommand can only launch Revit's Trim/Extend; it cannot be given the
    two elements. Bringing the ends together, freeing the connectors and
    inserting the routing preference fitting is the only way to automate it.
    """
    live_main = doc.GetElement(main.id)
    if live_main is None:
        report.problem(u"the main went missing before the fitting")
        return u""

    if plan.junction == geom.TEE:
        rules, detail = slope_model.junction_rules(doc, live_main)
        if report.debug is not None:
            report.debug.pair(u"junction rules on the main's type", rules)
            if detail:
                report.debug.pair(u"routing preferences said", detail)
        if rules == 0:
            report.problem(
                u"{0} The main's pipe type carries no junction family at "
                u"all, so the main was left whole rather than split for a "
                u"tee that could not be placed. Load a junction family and "
                u"add it under the pipe type's Routing Preferences. Both "
                u"pipes are touching, so Trim/Extend finishes it by "
                u"hand.".format(angle_advice(plan.plan_angle)))
            return u""

        fitting, method, notes = slope_model.place_tee(
            doc, live_main, branch_id, plan.crossing, config.hand_fitting)
        if report.debug is not None:
            for note in notes:
                report.debug.pair(u"junction attempt", note)
        if fitting is not None:
            if method != u"tee":
                report.note(u"Revit would not place a square tee at {0:.1f} "
                            u"degrees, so the junction family was placed, "
                            u"sized from the pipes and turned onto the "
                            u"three".format(plan.plan_angle))
            return method
        # Revit only ever places a tee square to the run, so an angled
        # branch is brought in the way a drainage layout does it: the tee
        # slides along the main, a stub runs square out of it, and a bend
        # turns the branch into the stub.
        if config.square_branch and off_the_line(plan.plan_angle) < 85.0:
            stub = stub_length(doc, branch_id, config)
            if report.debug is not None:
                report.debug.pair(u"squaring stub length",
                                  mo_debug.mm(stub) + u" mm")
            fitting, squared = slope_model.square_into_main(
                doc, live_main, branch_id, plan.crossing, stub)
            if report.debug is not None:
                for note in squared:
                    report.debug.pair(u"squaring attempt", note)
            notes.extend(squared)
            if fitting is not None:
                # A squared junction is reported as something to look at
                # rather than as a note. It is a change of design intent -
                # a drainage branch that should sweep in at its own angle
                # comes in square instead - so it must not happen quietly.
                report.problem(
                    u"{0} is joined, but squared: no junction family in the "
                    u"pipe type's routing preferences would take the branch "
                    u"at {1:.1f} degrees, so a square tee went into the main "
                    u"with a stub and a bend turning the branch into it. For "
                    u"a swept drainage junction, load a {2:.0f} degree "
                    u"junction family and add it to the pipe type's Routing "
                    u"Preferences. The tick for this is on the Slope tab in "
                    u"Settings.".format(
                        name, plan.plan_angle,
                        off_the_line(plan.plan_angle)))
                return u"tee, stub and bend"

        fitting, takeoff_error = slope_model.place_takeoff(
            doc, live_main, branch_id, plan.crossing)
        if fitting is not None:
            report.note(u"the tee was refused, so a takeoff went in instead")
            return u"takeoff"
        names, counts, detail = slope_model.log_offer(doc, live_main,
                                                      plan.plan_angle)
        if report.debug is not None:
            report.debug.pair(u"routing rule counts", counts)
            if detail:
                report.debug.pair(u"routing preferences said", detail)
        report.problem(
            u"No junction could be placed. {0} {1} Every family was tried "
            u"and turned onto the three pipes by hand as well. Both pipes "
            u"are left touching, so Revit's own Trim/Extend finishes it in "
            u"two clicks. What was tried: {2}".format(
                angle_advice(plan.plan_angle), offer_advice(names),
                u" | ".join(notes + [takeoff_error]) if notes
                else takeoff_error or u"nothing"))
        return u""

    if plan.extends_main:
        if not slope_model.extend_main(doc, live_main, plan.crossing):
            report.problem(u"the main would not extend to the apparent "
                           u"crossing")
            return u""
        doc.Regenerate()

    live_main = doc.GetElement(main.id)
    connector = slope_model.connector_at(live_main, plan.crossing,
                                         max(config.end_tol,
                                             2.0 / geom.MM_PER_FT))
    if connector is None:
        report.problem(u"the main has no free end at the crossing, so no "
                       u"bend could go in. Both pipes are left touching.")
        return u""
    if slope_model.is_joined(connector):
        report.problem(u"the main's end at the crossing already has "
                       u"something joined to it. Both pipes are left "
                       u"touching.")
        return u""

    fitting, error = slope_model.place_bend(
        doc, slope_model.connector_key(connector), branch_id, plan.crossing,
        plan.junction == geom.UNION)
    if fitting is not None:
        return u"union" if plan.junction == geom.UNION else u"bend"
    names, counts, detail = slope_model.log_offer(doc, live_main,
                                                  plan.plan_angle)
    if report.debug is not None:
        report.debug.pair(u"routing rule counts", counts)
        if detail:
            report.debug.pair(u"routing preferences said", detail)
    report.problem(
        u"Revit refused the bend. {0} {1} Both pipes are left touching, so "
        u"Revit's own Trim/Extend finishes it by hand in two clicks. Revit "
        u"said: {2}".format(angle_advice(plan.plan_angle),
                            offer_advice(names), error or u"nothing"))
    return u""


def stub_length(doc, branch_id, config):
    """How long the square stub out of the tee should be.

    Auto is three diameters with a 150mm floor: long enough for the bend and
    the tee to have room to sit, short enough that the tee does not slide so
    far along the main that it falls off the end of it.
    """
    if config.stub_mm and config.stub_mm > 0:
        return config.stub_mm / geom.MM_PER_FT
    diameter = 0.0
    try:
        diameter = slope_model.outside_diameter(doc.GetElement(branch_id))
    except Exception:
        diameter = 0.0
    floor = 150.0 / geom.MM_PER_FT
    return max(floor, diameter * 3.0)


def off_the_line(angle):
    """How far off the main's own line the branch arrives, 0 to 90."""
    return min(abs(angle), abs(180.0 - abs(angle)))


def angle_advice(angle):
    """Say what the angle means for the family Revit needs.

    A tee at anything other than square needs an oblique or swept junction
    family in the routing preferences, and most pipe types carry only the 90
    degree one. Reporting the raw angle and stopping there leaves the reader
    to work that out; it is the single most common reason this refuses.
    """
    off = off_the_line(angle)
    if off > 85.0:
        return (u"The branch meets the main square on, at {0:.1f} degrees, "
                u"so a plain tee should have taken.".format(angle))
    return (u"The branch arrives at {0:.1f} degrees to the main, which is "
            u"{1:.1f} degrees off its line - that needs an oblique or swept "
            u"junction family, and most pipe types carry only the 90 degree "
            u"tee.".format(angle, off))


def offer_advice(names):
    if not names:
        return (u"The main's pipe type has no junction or elbow family in "
                u"its routing preferences at all, so load one and add it "
                u"under Manage > MEP Settings > Pipe Settings.")
    return u"Its pipe type offers {0}.".format(u"; ".join(names))


# ======================================================================
# the loop
# ======================================================================

def prompt_for(main, config, done):
    """The status line, which is the tool's only voice while it runs.

    It carries the count as well as the question, because in pairs mode the
    only way to know a join went in is that the tool is asking for a main
    again - and a count that has not moved says it did not.
    """
    so_far = u"{0} joined - ".format(done) if done else u""
    if main is None:
        return u"{0}Match Offset Slope: pick the MAIN, the pipe whose fall " \
               u"and elevation are right. Esc to finish".format(so_far)
    if config.pairs:
        return u"{0}Main {1} - now pick the pipe to bring into it".format(
            so_far, main.describe())
    return u"{0}Main {1} - pick branches to match, Esc to finish".format(
        so_far, main.describe())


def run(uiapp):
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    settings = load_settings()
    report = Report()

    mo_model.reset_caches()
    config = SlopeConfig(settings)
    selection_filter = mo_model.OffsetFilter(PIPE_CATEGORIES)

    if config.debug:
        report.debug = mo_debug.Recorder(u"Match Offset Slope")
        report.debug.header(uiapp, doc, settings)

    main = None
    pairs = 0
    suppress_dialogs(uiapp, True)
    try:
        while True:
            try:
                reference = uidoc.Selection.PickObject(
                    ObjectType.Element, selection_filter,
                    prompt_for(main, config, report.matched))
            except OperationCanceledException:
                break
            except Exception as err:
                log(u"pick ended: {0}".format(to_text(err)))
                break
            if reference is None:
                break

            element = doc.GetElement(reference.ElementId)
            if element is None:
                continue

            if main is None:
                main = take_main(doc, element, config, report)
                if main is not None and not config.pairs:
                    report.datum_text = u"Main falling {0}".format(
                        main.describe())
                continue

            if config.trim:
                mo_model.checkout(doc, [element.Id, main.id])
            match_branch(doc, main, element, config, report)
            if config.pairs:
                # Back to asking for a main, whether that one went in or
                # not. The prompt is the only feedback there is during a
                # run, so it has to be honest about what it is asking for
                # next rather than quietly carrying on with a main the user
                # has stopped thinking about.
                main = None
                pairs += 1
            else:
                main = Main(doc.GetElement(main.id))
    finally:
        suppress_dialogs(uiapp, False)
        if config.pairs:
            report.datum_text = u"{0} pair{1} picked".format(
                pairs, u"" if pairs == 1 else u"s")
        drain_failures(report, u"the rest of the run")
        if report.debug is not None:
            report.debug.tail(report)
            report.debug.save()
        log(u"slope run finished: {0} matched, {1} problems".format(
            report.matched, len(report.problems)))
        flush_log()

    return settings, report
