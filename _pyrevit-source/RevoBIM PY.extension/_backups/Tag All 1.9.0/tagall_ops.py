# -*- coding: utf-8 -*-
"""Every write the tool makes, and the ExternalEvent that carries it.

A modeless window cannot start a transaction directly - every write goes out
through the ExternalEvent below, which Revit raises on its own thread. A run
sits inside a TransactionGroup and takes its transactions in chunks, so one
element Revit refuses cannot roll back the rest, and the window repaints its
progress bar only between transactions - never inside one.
"""
import traceback

import tagall_clr  # noqa: F401  (assemblies first)
import tagall_core as core
import tagall_model as model
from tagall_core import eid_value, to_text

from Autodesk.Revit.DB import (Transaction, TransactionGroup, TransactionStatus, SubTransaction,
                               IFailuresPreprocessor, FailureProcessingResult,
                               FailureSeverity, IndependentTag, TagOrientation,
                               LinkElementId, UV, ElementId, WorksharingUtils,
                               CheckoutStatus)
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent, ExternalEventRequest
from System.Collections.Generic import List


# ====================== failures and dialogs ======================

class WarningSwallower(IFailuresPreprocessor):
    """Warnings are deleted; anything worse rolls the transaction back and
    is reported by the caller."""

    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                try:
                    if failure.GetSeverity() == FailureSeverity.Warning:
                        accessor.DeleteWarning(failure)
                    else:
                        return FailureProcessingResult.ProceedWithRollBack
                except Exception:
                    continue
        except Exception:
            pass
        return FailureProcessingResult.Continue


class DialogSuppressor(object):
    """Hooked once and switched on and off with a flag - unsubscribing an
    IronPython bound method from a .NET event is not reliable. Every dialog
    dismissed during a run is logged, because a run that does nothing
    because Revit quietly asked a question is otherwise unexplainable."""

    def __init__(self):
        self.active = False
        self.hooked = False
        self.suppressed = []

    def hook(self, uiapp):
        if self.hooked:
            return
        try:
            uiapp.DialogBoxShowing += self._showing
            self.hooked = True
        except Exception:
            self.hooked = False

    def _showing(self, sender, args):
        if not self.active:
            return
        try:
            text = u""
            try:
                text = to_text(args.DialogId)
            except Exception:
                pass
            try:
                text = text + u" " + to_text(args.Message)
            except Exception:
                pass
            self.suppressed.append(text.strip())
            core.log(u"dialog suppressed: {0}".format(text.strip()))
            args.OverrideResult(1)   # IDOK / the first button
        except Exception:
            pass


SUPPRESSOR = DialogSuppressor()


# ====================== transactions ======================

def run_transaction(doc, name, work):
    """One transaction. Raises if Revit refuses it, so the caller can retry
    the chunk one element at a time and name the one at fault."""
    transaction = Transaction(doc, name)
    transaction.Start()
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass
    try:
        result = work()
    except Exception:
        try:
            transaction.RollBack()
        except Exception:
            pass
        raise
    status = transaction.Commit()
    if status != TransactionStatus.Committed:
        raise RuntimeError(u"Revit refused the transaction ({0})".format(to_text(status)))
    return result


def owned_elsewhere(doc, element_id):
    """Who else holds an element, or None. Only meaningful on a workshared
    model; a write to an element somebody else owns writes nothing and says
    nothing when dialogs are suppressed."""
    try:
        if not doc.IsWorkshared:
            return None
        status = WorksharingUtils.GetCheckoutStatus(doc, element_id)
        if status == CheckoutStatus.OwnedByOtherUser:
            try:
                return to_text(WorksharingUtils.GetWorksharingTooltipInfo(doc, element_id).Owner) or u"another user"
            except Exception:
                return u"another user"
    except Exception:
        return None
    return None


def to_id_list(ids):
    out = List[ElementId]()
    for element_id in ids:
        out.Add(element_id)
    return out


# ====================== results ======================

class RunResult(object):
    def __init__(self):
        self.created = 0
        self.deleted = 0
        self.skipped = 0
        self.untangled = 0
        self.views = 0
        self.problems = []
        self.notes = []
        self._problem_counts = {}
        self.cancelled = False

    def problem(self, text, count=1):
        text = to_text(text)
        self._problem_counts[text] = self._problem_counts.get(text, 0) + count

    def note(self, text):
        text = to_text(text)
        if text not in self.notes:
            self.notes.append(text)

    def finish(self):
        for text in sorted(self._problem_counts.keys()):
            count = self._problem_counts[text]
            self.problems.append(text if count == 1 else u"{0}  (x{1})".format(text, count))
        return self

    @property
    def summary(self):
        return core.summarise(self.created, self.deleted, self.skipped, self.problems)


# ====================== the external event ======================

class Handler(IExternalEventHandler):
    """Runs whatever job is queued. Jobs are (label, work, done): work takes
    the UIApplication and returns a result, done gets (result, error_text)."""

    def __init__(self):
        self.queue = []
        self.busy = False

    def Execute(self, uiapp):
        self.busy = True
        try:
            while self.queue:
                label, work, done = self.queue.pop(0)
                result = None
                error = None
                try:
                    result = work(uiapp)
                except Exception:
                    error = traceback.format_exc()
                    core.log(u"job {0} failed:\n{1}".format(label, error))
                if done is not None:
                    try:
                        done(result, error)
                    except Exception:
                        core.log(u"job {0} callback failed:\n{1}".format(label, traceback.format_exc()))
        finally:
            self.busy = False

    def GetName(self):
        return "RevoBIM Tag All"


class Dispatcher(object):
    """Owns the handler and the event. Raise() status is checked rather than
    assumed - an event that was never accepted looks exactly like a run that
    did nothing."""

    def __init__(self):
        self.handler = Handler()
        self.event = ExternalEvent.Create(self.handler)

    def submit(self, label, work, done):
        self.handler.queue.append((label, work, done))
        try:
            status = self.event.Raise()
        except Exception:
            self.handler.queue.pop()
            raise
        if status not in (ExternalEventRequest.Accepted, ExternalEventRequest.Pending):
            self.handler.queue.pop()
            raise RuntimeError(u"Revit did not accept the request ({0}). Is a Revit command or dialog open?".format(to_text(status)))
        return status


# ====================== the family run ======================

class FamilySpec(object):
    """What the Family Tags tab asked for."""

    def __init__(self, rows, view_records, options):
        self.rows = rows                  # [(TypeNode, tag_type_id or None, tag display)]
        self.view_records = view_records  # [ViewRecord]
        self.options = options            # dict: leader, offset_x, offset_y, elbow, elbow_mm, remove_previous, only_untagged


class RoomSpec(object):
    def __init__(self, source, tag_type_id, tag_display, view_records, options):
        self.source = source
        self.tag_type_id = tag_type_id
        self.tag_display = tag_display
        self.view_records = view_records
        self.options = options            # dict: remove_unassigned, only_untagged


def create_family_tag(doc, view, element, node, tag_type_id, options, right, up):
    """Create one tag and put its head where it was asked for.

    The leader elbow is deliberately **not** set here. Straight after Create
    the tag has no computed geometry, so its head and its box are not yet
    meaningful and an elbow set against them lands somewhere Revit then
    ignores. Worse, assigning TagHeadPosition afterwards moves the head and
    leaves the elbow where it was - which is the long diagonal leader that
    shipped in v1.0.1. The caller regenerates once per chunk and then calls
    apply_leader_elbow below.
    """
    ref = model.element_reference(element, node.source)
    base = model.element_point(element, node.source.transform)
    if base is None:
        raise ValueError(u"the element has no location to tag from")
    head = core.head_point(base, right, up, options["offset_x"], options["offset_y"])
    leader = bool(options["leader"])
    tag = IndependentTag.Create(doc, tag_type_id, view.Id, ref, leader,
                                TagOrientation.Horizontal, model.to_xyz(head))
    if tag is None:
        raise RuntimeError(u"Revit returned no tag")
    try:
        tag.TagHeadPosition = model.to_xyz(head)
    except Exception:
        pass
    if leader:
        try:
            from Autodesk.Revit.DB import LeaderEndCondition
            tag.LeaderEndCondition = LeaderEndCondition.Attached
        except Exception:
            pass
    return tag, ref


def measure_tag_boxes(doc, view, tags):
    """The box of each tag, measured with its **leader switched off**.

    A tag's bounding box in a view covers its leader as well as its text, so
    with the leader on the "edge" of the tag is the far end of the leader,
    somewhere out by the element. Switching the leaders off, regenerating and
    reading the boxes gives the tag itself; the SubTransaction is then rolled
    back, which puts every leader back exactly as it was.

    Measured rather than worked out from the text: a tag's size depends on
    its family, its label, the view scale and its text size, and the only
    thing that knows all four is Revit. Done for a whole chunk at a time, so
    it costs two regenerates per forty tags rather than two per tag.
    """
    boxes = {}
    sub = SubTransaction(doc)
    sub.Start()
    try:
        switched = []
        for tag, _ref, _node in tags:
            if model.set_leader(tag, False):
                switched.append(tag)
        if switched:
            doc.Regenerate()
        for tag, _ref, _node in tags:
            corners = model.annotation_corners(tag, view)
            if corners:
                boxes[eid_value(tag.Id)] = corners
    except Exception:
        core.log(u"measuring tag boxes failed:\n{0}".format(traceback.format_exc()))
        boxes = {}
    finally:
        try:
            sub.RollBack()       # every leader comes back with it
        except Exception:
            pass
    try:
        doc.Regenerate()
    except Exception:
        pass
    return boxes


def apply_leader_elbow(doc, view, tag, ref, node, corners, options, right, up):
    """Put the elbow level with where the leader meets the tag.

    The anchor is the middle of the tag's outer edge on the side facing the
    element - the family's own horizontal centre line, not its origin. The
    elbow is that anchor moved straight back along the view's right, so the
    elbow-to-tag segment is horizontal by construction. Called only after a
    regenerate, and it never touches the tag head.
    """
    if not options["leader"] or not options["elbow"]:
        return None
    elbow_mm = options["elbow_mm"]
    x = options["offset_x"]
    if elbow_mm <= 0:
        return None
    if core.elbow_side(x) == 0.0:
        return (u"The leader elbow needs a sideways offset. With X at 0 the leader "
                u"runs straight to the tag and an elbow would only kink it.")
    head = model.head_position(tag)
    if head is None:
        return u"{0}: Revit would not say where it put the tag head, so no elbow was set".format(node.category)
    anchor = core.leader_anchor(head, right, up, corners, x)
    wanted = core.elbow_point(anchor, right, x, elbow_mm)
    placed = False
    try:
        tag.SetLeaderElbow(ref, model.to_xyz(wanted))    # 2022 and later
        placed = True
    except Exception:
        try:
            tag.LeaderElbow = model.to_xyz(wanted)       # older releases
            placed = True
        except Exception:
            placed = False
    if not placed:
        return u"Revit would not set a leader elbow on {0} tags in this view".format(node.category)
    note = None
    if not corners:
        note = (u"{0}: the tag's own size could not be measured, so its elbow is levelled "
                u"with the family origin rather than its centre".format(node.category))
    # a void API call is not evidence - read it back and measure it
    got = model.leader_elbow(tag, ref)
    if got is not None and not core.elbow_is_horizontal(anchor, got, up, tolerance_mm=1.0):
        return u"{0}: Revit moved the elbow {1:.0f}mm off level with the tag".format(
            node.category, core.off_level_mm(anchor, got, up))
    return note


def plan_family_view(doc, view_record, spec, result):
    """Everything one view needs: the elements per row, what is tagged
    already, and the decision of what to tag and what to delete."""
    view = doc.GetElement(view_record.view_id)
    if view is None:
        result.problem(u"View {0} no longer exists".format(view_record.name))
        return None
    lo, hi, _cut = model.view_bounds(view)
    right, up = model.view_directions(view)
    tagged = model.existing_tags(doc, view)
    wanted = set([eid_value(node.type_id) for node, _tag, _name in spec.rows if not node.source.is_link])
    host_lookup = model.host_elements_by_type(doc, view, wanted)
    candidates = []
    for node, tag_type_id, tag_display in spec.rows:
        if tag_type_id is None:
            result.problem(u"{0} ({1}): no tag family chosen, so it was not tagged".format(node.display, node.category))
            continue
        elements = model.elements_of_node_in_view(node, view, (lo, hi), host_lookup)
        for element in elements:
            key = model.element_key_of(element, node.source)
            candidates.append((key, (element, node, tag_type_id, tag_display)))
    to_tag, to_delete = core.plan_targets(candidates, tagged,
                                          spec.options["only_untagged"],
                                          spec.options["remove_previous"])
    return {"view": view, "name": view_record.name, "right": right, "up": up,
            "to_tag": to_tag, "to_delete": to_delete, "candidates": len(candidates)}


def delete_tags(doc, plan, result, progress, name):
    """Delete the tags a view plan asks for, skipping and naming any that
    somebody else owns."""
    ids = []
    for tag_id in plan["to_delete"]:
        owner = owned_elsewhere(doc, tag_id)
        if owner:
            result.problem(u"{0}: a tag owned by {1} was left in place".format(name, owner))
            continue
        ids.append(tag_id)
    if not ids:
        return
    try:
        run_transaction(doc, u"RevoBIM Tag All - remove tags", lambda: doc.Delete(to_id_list(ids)))
        result.deleted += len(ids)
    except Exception as error:
        result.problem(u"{0}: could not remove {1} existing tags - {2}".format(name, len(ids), to_text(error)))
    progress(len(ids))


def place_tags(doc, plan, items, spec, notes):
    """Create every tag in `items`, regenerate **once**, then set the elbows.

    One regenerate per chunk rather than one per tag: the tags need computing
    before their heads and boxes can be read, and regenerating forty at a
    time costs one pass instead of forty.
    """
    made = []
    for _key, payload in items:
        element, node, tag_type_id, _display = payload
        tag, ref = create_family_tag(doc, plan["view"], element, node, tag_type_id,
                                     spec.options, plan["right"], plan["up"])
        made.append((tag, ref, node))
    if not made:
        return []
    doc.Regenerate()
    wants_elbow = bool(spec.options["leader"]) and bool(spec.options["elbow"]) \
        and spec.options["elbow_mm"] > 0 and core.elbow_side(spec.options["offset_x"]) != 0.0
    boxes = measure_tag_boxes(doc, plan["view"], made) if wants_elbow else {}
    for tag, ref, node in made:
        note = apply_leader_elbow(doc, plan["view"], tag, ref, node,
                                  boxes.get(eid_value(tag.Id)), spec.options,
                                  plan["right"], plan["up"])
        if note:
            notes.append(note)
    return [tag.Id for tag, _ref, _node in made]


def untangle_view(doc, plan, tag_ids, spec, result):
    """Move the tags just placed in one view apart along the view's up until
    none of them touch, then put their elbows back level with them.

    One transaction for the view, after every chunk of it has been placed,
    so tags from different chunks are untangled against each other. The
    boxes are measured the same way the elbows are - leaders off, inside a
    rolled-back SubTransaction - so a box is the tag, not its leader. Moving
    the head leaves an elbow where it was, so after the heads move and the
    view regenerates, apply_leader_elbow sets each elbow again from the box
    carried down with its tag.
    """
    tags = []
    for tag_id in tag_ids:
        tag = doc.GetElement(tag_id)
        if tag is not None:
            tags.append((tag, model.tagged_reference(tag), None))
    if len(tags) < 2:
        return 0
    view = plan["view"]
    right, up = plan["right"], plan["up"]
    moved = []

    def work():
        del moved[:]
        boxes = measure_tag_boxes(doc, view, tags)
        items = [(eid_value(tag.Id), core.view_box(boxes.get(eid_value(tag.Id)), right, up))
                 for tag, _ref, _node in tags]
        offsets = core.untangle_offsets(items, core.untangle_gap_ft(model.view_scale(view)))
        for tag, ref, _node in tags:
            offset = offsets.get(eid_value(tag.Id), 0.0)
            if offset > -1e-6:
                continue
            head = model.head_position(tag)
            if head is None:
                continue
            tag.TagHeadPosition = model.to_xyz(core.add3(head, core.scale3(up, offset)))
            moved.append((tag, ref, core.shift_corners(boxes.get(eid_value(tag.Id)), up, offset)))
        if not moved:
            return
        doc.Regenerate()
        for tag, ref, corners in moved:
            if ref is None:
                continue
            note = apply_leader_elbow(doc, view, tag, ref, UNTANGLED, corners, spec.options, right, up)
            if note:
                result.note(note)

    try:
        run_transaction(doc, u"RevoBIM Tag All - untangle", work)
    except Exception as error:
        result.problem(u"{0}: the tags were placed but could not be untangled - {1}".format(
            plan["name"], short_error(error)))
        return 0
    if moved:
        result.note(u"{0}: {1} tag{2} moved down to clear the others".format(
            plan["name"], len(moved), u"" if len(moved) == 1 else u"s"))
    return len(moved)


class _Untangled(object):
    """What apply_leader_elbow names in a note about an untangled tag."""
    category = u"An untangled tag"


UNTANGLED = _Untangled()


def tag_chunk(doc, plan, chunk, spec, result):
    """One transaction for a chunk. A refused chunk is replayed one element at
    a time so the one at fault is named and only that one is lost."""
    notes = []
    holder = []

    def work_all():
        holder.extend(place_tags(doc, plan, chunk, spec, notes))

    try:
        run_transaction(doc, u"RevoBIM Tag All", work_all)
        return list(holder), notes
    except Exception:
        pass

    created = []
    del notes[:]
    for item in chunk:
        element, node, tag_type_id, tag_display = item[1]
        one = []

        def work_one(item=item, one=one):
            one.extend(place_tags(doc, plan, [item], spec, notes))

        try:
            run_transaction(doc, u"RevoBIM Tag All", work_one)
            created.extend(one)
        except Exception as error:
            result.skipped += 1
            result.problem(u"{0} in {1} with {2}: {3}".format(
                node.category, plan["name"], tag_display, short_error(error)))
    return created, notes


def short_error(error):
    text = to_text(error).strip().splitlines()
    text = text[-1] if text else u"refused"
    if len(text) > 160:
        text = text[:157] + u"..."
    return text


def run_family(uiapp, spec, progress, confirm):
    """The whole Family Tags run. progress(done, total, text) is called only
    between transactions; confirm(text) asks before anything is deleted."""
    doc = uiapp.ActiveUIDocument.Document
    result = RunResult()
    SUPPRESSOR.hook(uiapp)
    plans = []
    for view_record in spec.view_records:
        plan = plan_family_view(doc, view_record, spec, result)
        if plan is not None:
            plans.append(plan)
    total_tags = sum([len(plan["to_tag"]) for plan in plans])
    total_delete = sum([len(plan["to_delete"]) for plan in plans])
    result.views = len(plans)
    if total_tags > core.MAX_TAGS_PER_RUN:
        result.problem(u"{0} tags is more than one run will place ({1}). Narrow the views or the families.".format(total_tags, core.MAX_TAGS_PER_RUN))
        return result.finish()
    if total_delete and not confirm(u"{0} existing tag{1} across {2} view{3} will be removed before {4} new tag{5} are placed. Continue?".format(
            total_delete, u"" if total_delete == 1 else u"s", len(plans), u"" if len(plans) == 1 else u"s",
            total_tags, u"" if total_tags == 1 else u"s")):
        result.cancelled = True
        return result.finish()
    if total_tags == 0 and total_delete == 0:
        candidates = sum([plan["candidates"] for plan in plans])
        if candidates:
            result.note(u"Every one of the {0} matching elements already carries a tag in the chosen views.".format(candidates))
        else:
            result.note(u"None of the chosen families appear in the chosen views.")
        return result.finish()

    total = total_tags + total_delete
    done = [0]
    last = [-1]

    current = [u"", 0]

    def say():
        progress(done[0], total, u"Tagging {0} - view {1} of {2} - {3} of {4}".format(
            current[0], current[1], len(plans), done[0], total))

    def advance(count):
        done[0] += count
        if core.should_repaint(done[0], total, last[0]):
            last[0] = core.percent(done[0], total)
            say()

    def starting(index, plan):
        """A new view always repaints, so the status line names it even when
        the percentage has not moved."""
        current[0] = plan["name"]
        current[1] = index + 1
        say()

    group = TransactionGroup(doc, u"RevoBIM Tag All")
    group.Start()
    SUPPRESSOR.active = True
    SUPPRESSOR.suppressed = []
    try:
        for index, plan in enumerate(plans):
            starting(index, plan)
            if plan["to_delete"]:
                delete_tags(doc, plan, result, advance, plan["name"])
            placed_here = []
            for chunk in core.chunks(plan["to_tag"], core.CHUNK_SIZE):
                created, notes = tag_chunk(doc, plan, chunk, spec, result)
                # prove the write: the ids still resolve after the commit
                alive = [tag_id for tag_id in created if doc.GetElement(tag_id) is not None]
                result.created += len(alive)
                if len(alive) != len(created):
                    result.problem(u"{0}: {1} tags did not survive their commit".format(plan["name"], len(created) - len(alive)))
                for note in notes:
                    result.note(note)
                placed_here.extend(alive)
                advance(len(chunk))
            if spec.options.get("untangle") and len(placed_here) > 1:
                result.untangled += untangle_view(doc, plan, placed_here, spec, result)
        group.Assimilate()
    except Exception:
        core.log(u"family run failed:\n{0}".format(traceback.format_exc()))
        try:
            group.RollBack()
        except Exception:
            pass
        result.problem(u"The run stopped early: {0}".format(short_error(traceback.format_exc())))
    finally:
        SUPPRESSOR.active = False
    if SUPPRESSOR.suppressed:
        result.note(u"{0} Revit dialog(s) were dismissed during the run - see the log.".format(len(SUPPRESSOR.suppressed)))
    return result.finish()


# ====================== the room run ======================

def create_room_tag(doc, view, room, tag_type_id):
    if room.source.is_link:
        link_id = LinkElementId(room.source.instance.Id, room.room_id)
    else:
        link_id = LinkElementId(room.room_id)
    point = UV(room.point[0], room.point[1])
    tag = doc.Create.NewRoomTag(link_id, point, view.Id)
    if tag is None:
        raise RuntimeError(u"Revit returned no tag")
    if tag_type_id is not None:
        try:
            if eid_value(tag.GetTypeId()) != eid_value(tag_type_id):
                tag.ChangeTypeId(tag_type_id)
        except Exception:
            try:
                tag.RoomTagType = doc.GetElement(tag_type_id)
            except Exception:
                pass
    return tag.Id


def plan_room_view(doc, view_record, rooms, spec, result):
    view = doc.GetElement(view_record.view_id)
    if view is None:
        result.problem(u"View {0} no longer exists".format(view_record.name))
        return None
    if not view_record.is_plan:
        result.problem(u"{0} is not a plan view, so rooms were not tagged in it".format(view_record.name))
        return None
    lo, hi, cut_z = model.view_bounds(view)
    level_name = model.view_level_name(view)
    keyed, orphaned = model.existing_room_tags(doc, view)
    candidates = []
    for room in rooms:
        if cut_z is not None:
            in_view = core.room_in_view(room.min_z, room.max_z, cut_z, room.point, lo, hi)
        else:
            in_view = bool(level_name) and room.level_name == level_name and core.point_in_xy(room.point, lo, hi)
        if in_view:
            candidates.append((room.key, room))
    to_tag, _ignored = core.plan_targets(candidates, keyed, spec.options["only_untagged"], False)
    to_delete = list(orphaned) if spec.options["remove_unassigned"] else []
    if cut_z is None and not level_name:
        result.problem(u"{0} has no level and no cut plane, so no rooms were matched to it".format(view_record.name))
    return {"view": view, "name": view_record.name, "to_tag": to_tag, "to_delete": to_delete,
            "candidates": len(candidates)}


def run_room(uiapp, spec, progress, confirm):
    doc = uiapp.ActiveUIDocument.Document
    result = RunResult()
    SUPPRESSOR.hook(uiapp)
    rooms = model.collect_rooms(spec.source)
    if not rooms:
        result.problem(u"{0} holds no placed rooms".format(spec.source.name))
        return result.finish()
    plans = []
    for view_record in spec.view_records:
        plan = plan_room_view(doc, view_record, rooms, spec, result)
        if plan is not None:
            plans.append(plan)
    total_tags = sum([len(plan["to_tag"]) for plan in plans])
    total_delete = sum([len(plan["to_delete"]) for plan in plans])
    result.views = len(plans)
    if total_delete and not confirm(u"{0} unassigned room tag{1} (showing ?) across {2} view{3} will be removed, then {4} room tag{5} placed. Continue?".format(
            total_delete, u"" if total_delete == 1 else u"s", len(plans), u"" if len(plans) == 1 else u"s",
            total_tags, u"" if total_tags == 1 else u"s")):
        result.cancelled = True
        return result.finish()
    if total_tags == 0 and total_delete == 0:
        candidates = sum([plan["candidates"] for plan in plans])
        if candidates:
            result.note(u"Every one of the {0} rooms in the chosen views already carries a tag.".format(candidates))
        else:
            result.note(u"No rooms from {0} are cut by the chosen views.".format(spec.source.name))
        return result.finish()

    total = total_tags + total_delete
    done = [0]
    last = [-1]

    current = [u"", 0]

    def say():
        progress(done[0], total, u"Tagging rooms {0} - view {1} of {2} - {3} of {4}".format(
            current[0], current[1], len(plans), done[0], total))

    def advance(count):
        done[0] += count
        if core.should_repaint(done[0], total, last[0]):
            last[0] = core.percent(done[0], total)
            say()

    def starting(index, plan):
        """A new view always repaints, so the status line names it even when
        the percentage has not moved."""
        current[0] = plan["name"]
        current[1] = index + 1
        say()

    group = TransactionGroup(doc, u"RevoBIM Tag All - rooms")
    group.Start()
    SUPPRESSOR.active = True
    SUPPRESSOR.suppressed = []
    try:
        for index, plan in enumerate(plans):
            starting(index, plan)
            if plan["to_delete"]:
                delete_tags(doc, plan, result, advance, plan["name"])
            for chunk in core.chunks(plan["to_tag"], core.CHUNK_SIZE):
                created = []

                def work_all(chunk=chunk, created=created, plan=plan):
                    for key, room in chunk:
                        created.append(create_room_tag(doc, plan["view"], room, spec.tag_type_id))

                try:
                    run_transaction(doc, u"RevoBIM Tag All - rooms", work_all)
                except Exception:
                    created = []
                    for key, room in chunk:
                        holder = []

                        def work_one(room=room, holder=holder, plan=plan):
                            holder.append(create_room_tag(doc, plan["view"], room, spec.tag_type_id))

                        try:
                            run_transaction(doc, u"RevoBIM Tag All - rooms", work_one)
                            created.extend(holder)
                        except Exception as error:
                            result.skipped += 1
                            result.problem(u"{0} in {1}: {2}".format(room.label, plan["name"], short_error(error)))
                alive = [tag_id for tag_id in created if doc.GetElement(tag_id) is not None]
                result.created += len(alive)
                advance(len(chunk))
        group.Assimilate()
    except Exception:
        core.log(u"room run failed:\n{0}".format(traceback.format_exc()))
        try:
            group.RollBack()
        except Exception:
            pass
        result.problem(u"The run stopped early: {0}".format(short_error(traceback.format_exc())))
    finally:
        SUPPRESSOR.active = False
    if SUPPRESSOR.suppressed:
        result.note(u"{0} Revit dialog(s) were dismissed during the run - see the log.".format(len(SUPPRESSOR.suppressed)))
    return result.finish()
