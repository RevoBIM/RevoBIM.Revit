# -*- coding: utf-8 -*-
"""RevoBIM Match Offset - the run.

First pick takes the datum off an element. Every pick after it puts the next
element on that datum, one transaction each, until Escape.

One transaction per element rather than one for the run, because the picks sit
between the writes: a transaction cannot be held open across a pick, and a
TransactionGroup held open across Revit's message loop is a hard crash. The
cost is that each element is its own undo step, which is said in the reference
notes rather than discovered.

The settings are read once and resolved into a RunConfig before the first
pick. Every number and every choice in them is a string on disk; parsing them
again per element meant a dozen string comparisons and two float parses for
every click, all of which produce the same answer they did the click before.
"""

import mo_clr  # noqa: F401

from Autodesk.Revit.DB import (
    FailureProcessingResult, FailureSeverity, IFailuresPreprocessor,
    Transaction,
)
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

import mo_debug
import mo_model
from mo_core import (
    ANCHOR_LABEL, Report, TOL_FT,
    anchor_value, capture_datum, delta_for, eid_value, enabled_categories,
    flush_log, format_mm, ft_to_mm, is_on, level_offset_text, load_settings,
    log, parse_number,
    prompt_text, save_settings, to_text,
)

FITTING_KEYS = frozenset((u"pipe_fittings", u"duct_fittings",
                          u"cable_tray_fittings", u"conduit_fittings"))

_HOOKED = [False]
_SUPPRESS = {'on': False}


class SwallowWarnings(IFailuresPreprocessor):
    """Delete warnings, resolve errors where Revit offers a resolution, and
    write every one of them down.

    Deleting warnings and returning Continue is only half the job. An error
    the preprocessor does not resolve is still an error at commit time, and
    Revit answers that by rolling the whole transaction back and returning
    RolledBack from Commit() - which is where "Revit did not commit the
    move" came from, with nothing said about what Revit actually objected
    to. Revit's own description of every failure now goes into `seen`, and
    the run drains it into the report.
    """

    def __init__(self):
        self.seen = []

    def drain(self):
        found = list(self.seen)
        del self.seen[:]
        return found

    def PreprocessFailures(self, accessor):
        resolved = False
        try:
            for failure in accessor.GetFailureMessages():
                severity = None
                description = u""
                try:
                    severity = failure.GetSeverity()
                    description = to_text(failure.GetDescriptionText())
                except Exception:
                    pass
                self.seen.append((to_text(severity), description))
                if severity == FailureSeverity.Warning:
                    try:
                        accessor.DeleteWarning(failure)
                        continue
                    except Exception:
                        pass
                try:
                    if failure.HasResolutions():
                        accessor.ResolveFailure(failure)
                        resolved = True
                except Exception:
                    continue
        except Exception:
            pass
        if resolved:
            return FailureProcessingResult.ProceedWithCommit
        return FailureProcessingResult.Continue


# One instance for the whole session. A new preprocessor per transaction is a
# new managed object per element for no reason.
PREPROCESSOR = SwallowWarnings()


def drain_failures(report, where):
    """Put whatever Revit objected to into the report, in Revit's words."""
    found = PREPROCESSOR.drain()
    if not found and report.debug is None:
        return found
    if found and report.debug is not None:
        report.debug.line(u"  during {0}:".format(to_text(where)))
        for severity, description in found:
            report.debug.failure(severity, description)
    return found


def failure_text(found):
    """The failures as one sentence, for a problem line."""
    if not found:
        return u""
    parts = []
    for severity, description in found:
        text = description.strip()
        if text and text not in parts:
            parts.append(text)
    return u"; ".join(parts[:3])


def suppress_dialogs(uiapp, on):
    """Hook DialogBoxShowing once and switch it with a flag.

    Unsubscribing an IronPython bound method from a .NET event is not
    reliable - each attribute access makes a fresh delegate - so the handler
    goes on once and a flag decides whether it does anything.
    """
    _SUPPRESS['on'] = bool(on)
    if _HOOKED[0]:
        return

    def handler(sender, args):
        if not _SUPPRESS['on']:
            return
        try:
            log(u"Revit dialog suppressed: {0}".format(to_text(args.DialogId)))
            args.OverrideResult(1)
        except Exception:
            pass

    try:
        uiapp.DialogBoxShowing += handler
        _HOOKED[0] = True
    except Exception:
        pass


# ======================================================================
# the settings, resolved once
# ======================================================================

class RunConfig(object):
    """Everything a run needs, worked out before the first pick."""

    def __init__(self, doc, anchor, settings):
        self.anchor = anchor
        self.label = ANCHOR_LABEL.get(anchor, anchor)
        self.settings = settings

        self.measure = to_text(settings.get(u"measure", u"size"))
        self.point_measure = to_text(settings.get(u"point_measure",
                                                  u"solid"))
        self.fab_measure = to_text(settings.get(u"fab_measure",
                                                u"parameters"))
        self.hanger_top = to_text(settings.get(u"fab_hanger_top",
                                               u"bearing"))
        self.hanger_rods = is_on(settings, u"fab_hanger_rods")
        self.framing_measure = to_text(settings.get(u"framing_measure",
                                                    u"top"))
        self.insulation = is_on(settings, u"include_insulation")
        self.slope_tol = parse_number(settings.get(u"slope_tol_deg"), 0.5)
        if self.slope_tol is None or self.slope_tol < 0:
            self.slope_tol = 0.5
        self.skip_sloped = to_text(settings.get(u"sloped", u"skip")) == u"skip"
        self.skip_fittings = to_text(
            settings.get(u"connected_fittings", u"skip")) == u"skip"

        self.step = parse_number(settings.get(u"round_step_mm"), 0.0) or 0.0
        if self.step < 0:
            self.step = 0.0
        self.round_mode = to_text(settings.get(u"round_mode", u"up"))
        self.round_datum = to_text(settings.get(u"round_datum", u"level"))
        self.move_source = (self.step > 0 and
                            is_on(settings, u"move_source_on_round"))

        self.use_preselection = is_on(settings, u"use_preselection")
        self.remember = is_on(settings, u"remember_datum")
        self.show_results = to_text(settings.get(u"show_results", u"problems"))
        self.categories = enabled_categories(settings)

        self.debug = is_on(settings, u"debug_report")
        self.hanger_dumps = 0
        # The level the datum was read off, as (name, elevation). Kept so a
        # family on another level can say what its own offset came out at.
        self.datum_level = (u"", None)
        self.workshared = mo_model.is_workshared(doc)
        self.username = mo_model.username(doc) if self.workshared else u""
        self.reverse = mo_model.category_key_map()

    def measure_element(self, doc, element, at_point=None):
        return mo_model.measure(doc, element, self.measure, self.insulation,
                                self.slope_tol, at_point, self.point_measure,
                                self.fab_measure, self.hanger_top,
                                self.framing_measure)

    def category_key(self, element):
        try:
            return self.reverse.get(eid_value(element.Category.Id), u"")
        except Exception:
            return u""


# ======================================================================
# the two halves of the job
# ======================================================================

def say_hanger(element, config, report):
    """Write a hanger's own geometry into the debug report.

    Only for hangers, only when the debug report is on, and only for the
    first few: every rule for finding a bearer is a guess about how somebody
    drew a hanger, and this is the evidence for the next one. A bank of
    thirty would bury the rest of the report, and the first two say the
    same thing as the thirtieth.
    """
    if report.debug is None or config.hanger_dumps >= 2:
        return
    if not mo_model.is_a_support(element):
        return
    config.hanger_dumps += 1
    report.say(u"support geometry, {0}".format(mo_model.describe(element)))
    for text in mo_model.hanger_lines(element):
        report.say(u"  {0}".format(text))


def say_level(doc, element, config, report, name, after):
    """When a family on one level is matched to something on another, say
    what its offset came out at against its own level.

    The match itself is worked in project elevations, so the level each end
    sits on does not change where the family lands. What does change is the
    number in its properties palette, and that is the number somebody
    checking the job reads - so it is written down.
    """
    if after is None or not after.ok:
        return
    level_name, level_ft = mo_model.level_of(doc, element)
    if level_ft is None:
        return
    datum_ft = config.datum_level[1]
    if datum_ft is not None and abs(float(datum_ft) - level_ft) <= TOL_FT:
        return
    value = anchor_value(after.bottom, after.middle, after.top, config.anchor)
    text = level_offset_text(
        u"{0} on {1}".format(name, level_name or u"its level"),
        value, level_ft, config.label)
    if text:
        report.note(text)


def take_datum(doc, element, config, report, at_point=None):
    """The first pick.

    Returns (datum_ft, datum_mm, measurement). The measurement comes back so
    that moving the source onto a rounded datum does not have to measure the
    same element a second time.
    """
    say_hanger(element, config, report)
    measurement = config.measure_element(doc, element, at_point)
    if not measurement.ok:
        report.problem(u"{0}: {1}".format(mo_model.describe(element),
                                          measurement.reason))
        return None, None, None

    if measurement.slope > config.slope_tol and config.skip_sloped:
        report.problem(
            u"{0} is pitched {1} degrees - Match Offset works to one "
            u"elevation. Drainage Elevation Match is the tool for a "
            u"falling run.".format(mo_model.describe(element),
                                   format_mm(measurement.slope)))
        return None, None, None

    level_ft = 0.0
    if config.round_datum == u"level" and config.step > 0:
        level_ft = mo_model.level_elevation(doc, element)

    datum_ft, raw_mm, rounded_mm, was_rounded = capture_datum(
        measurement.bottom, measurement.middle, measurement.top,
        config.anchor, level_ft, config.step, config.round_mode,
        config.round_datum)

    if was_rounded:
        report.note(u"{0} datum rounded from {1} to {2} ({3} step)".format(
            config.label, format_mm(raw_mm), format_mm(rounded_mm),
            format_mm(config.step)))

    config.datum_level = mo_model.level_of(doc, element)
    report.note_pair(u"datum level", u"{0} at {1} mm".format(
        config.datum_level[0] or u"none found",
        u"?" if config.datum_level[1] is None
        else format_mm(ft_to_mm(config.datum_level[1]))))

    log(u"datum {0} {1} from {2} via {3}".format(
        config.label, format_mm(rounded_mm), mo_model.describe(element),
        measurement.route))
    report.note_pair(u"datum measured from", measurement.route)
    return datum_ft, rounded_mm, measurement


def apply_to(doc, element, config, datum_ft, report, at_point=None,
             measurement=None):
    """One element onto the datum. Returns True when it moved."""
    name = mo_model.describe(element)

    if mo_model.in_group(element):
        report.problem(u"{0} is in a group - ungroup it or edit the "
                       u"group".format(name))
        return False

    if config.workshared:
        owner = mo_model.owned_by_other(doc, element, config.username)
        if owner:
            report.problem(u"{0} is owned by {1}".format(name, owner))
            return False

    if config.skip_fittings and config.category_key(element) in FITTING_KEYS:
        if mo_model.connected_count(element) > 0:
            report.problem(
                u"{0} is a connected fitting - move the pipes and the "
                u"fitting follows".format(name))
            return False

    if measurement is None:
        say_hanger(element, config, report)
        measurement = config.measure_element(doc, element, at_point)
    if not measurement.ok:
        report.problem(u"{0}: {1}".format(name, measurement.reason))
        return False

    if measurement.slope > config.slope_tol and config.skip_sloped:
        report.problem(u"{0} is pitched {1} degrees and was left "
                       u"alone".format(name, format_mm(measurement.slope)))
        return False

    delta = delta_for(measurement.bottom, measurement.middle,
                      measurement.top, config.anchor, datum_ft)
    if abs(delta) <= TOL_FT:
        report.note(u"{0} was already on the datum".format(name))
        return False

    if config.workshared:
        mo_model.checkout(doc, [element.Id])

    was_pinned = mo_model.is_pinned(element)
    transaction = Transaction(doc, u"RevoBIM Match Offset {0}".format(
        config.label))
    try:
        transaction.Start()
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(PREPROCESSOR)
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)

        if was_pinned:
            try:
                element.Pinned = False
            except Exception:
                pass
        route = mo_model.shift(doc, element, delta)
        if config.hanger_rods and mo_model.is_a_hanger(element):
            said = mo_model.keep_rod_tops(element, delta)
            if said:
                report.note(u"{0}: {1}".format(name, said))
        if was_pinned:
            try:
                element.Pinned = True
            except Exception:
                pass
        status = transaction.Commit()
    except Exception as err:
        try:
            transaction.RollBack()
        except Exception:
            pass
        report.problem(u"{0}: {1}".format(name, to_text(err)))
        return False

    found = drain_failures(report, u"the move")
    if to_text(status).lower().find(u"committed") < 0:
        said = failure_text(found)
        report.problem(u"{0}: Revit rolled the move back{1}".format(
            name, u" - " + said if said else
            u" without saying why. Turn the debug report on in Settings and "
            u"send the report over."))
        return False

    # Prove the write. A void API call is not evidence, and Revit does not
    # reliably raise when a write does not take.
    after = config.measure_element(doc, element, at_point)
    if after.ok:
        left = delta_for(after.bottom, after.middle, after.top,
                         config.anchor, datum_ft)
        if abs(left) > TOL_FT * 10:
            report.problem(
                u"{0}: asked for {1} and it read back {2} out".format(
                    name, format_mm(ft_to_mm(delta)),
                    format_mm(ft_to_mm(left))))
            return False

    say_level(doc, element, config, report, name, after)

    log(u"{0} moved {1} mm via {2}".format(name, format_mm(ft_to_mm(delta)),
                                           route))
    report.say(u"{0} moved {1} mm via {2}, measured from {3}".format(
        name, format_mm(ft_to_mm(delta)), route, measurement.route))
    report.matched_one()
    return True


# ======================================================================
# the loop
# ======================================================================

def run(uiapp, anchor):
    """The whole command. Returns the settings and the report."""
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    settings = load_settings()
    report = Report()

    mo_model.reset_caches()
    config = RunConfig(doc, anchor, settings)

    if config.debug:
        report.debug = mo_debug.Recorder(
            u"Match Offset {0}".format(config.label))
        report.debug.header(uiapp, doc, settings)

    if not config.categories:
        report.problem(u"No categories are enabled in Settings, so there is "
                       u"nothing to pick.")
        return settings, report

    selection_filter = mo_model.OffsetFilter(config.categories)

    preselected = []
    if config.use_preselection:
        try:
            for element_id in uidoc.Selection.GetElementIds():
                element = doc.GetElement(element_id)
                if element is not None:
                    preselected.append(element)
        except Exception:
            preselected = []
        if preselected and config.workshared:
            # One borrow for the lot, rather than one per element inside the
            # loop: CheckoutElements is a round trip to central.
            mo_model.checkout(doc, [e.Id for e in preselected])

    datum_ft = None
    datum_mm = None
    rounded_flag = False

    if config.remember and \
            to_text(settings.get(u"last_datum_anchor")) == anchor:
        remembered = parse_number(settings.get(u"last_datum_ft"), None)
        if remembered is not None:
            datum_ft = remembered
            datum_mm = ft_to_mm(remembered)
            report.note(u"Using the datum remembered from the last run. Turn "
                        u"'Remember the datum between runs' off in Settings "
                        u"to pick a fresh one each time.")

    suppress_dialogs(uiapp, True)
    try:
        while True:
            prompt = prompt_text(anchor, datum_mm, rounded_flag, config.step)
            try:
                reference = uidoc.Selection.PickObject(
                    ObjectType.Element, selection_filter, prompt)
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
            try:
                point = reference.GlobalPoint
            except Exception:
                point = None

            if datum_ft is None:
                datum_ft, datum_mm, measurement = take_datum(
                    doc, element, config, report, point)
                if datum_ft is None:
                    continue
                rounded_flag = config.step > 0
                report.datum_text = u"{0} {1}".format(
                    config.label, format_mm(datum_mm))

                # The first element goes onto the rounded value itself, so
                # the whole bank - the one it was read off included - ends
                # up on one number rather than everything but the source.
                if config.move_source:
                    apply_to(doc, element, config, datum_ft, report, point,
                             measurement)

                if config.remember:
                    settings[u"last_datum_ft"] = to_text(datum_ft)
                    settings[u"last_datum_anchor"] = anchor
                    save_settings(settings)

                for other in preselected:
                    try:
                        if eid_value(other.Id) == eid_value(element.Id):
                            continue
                    except Exception:
                        continue
                    apply_to(doc, other, config, datum_ft, report)
                continue

            apply_to(doc, element, config, datum_ft, report, point)
    finally:
        suppress_dialogs(uiapp, False)
        drain_failures(report, u"the rest of the run")
        if report.debug is not None:
            report.debug.tail(report)
            report.debug.save()
        log(u"run finished: {0} matched, {1} problems".format(
            report.matched, len(report.problems)))
        flush_log()

    return settings, report
