# -*- coding: utf-8 -*-
"""Every write the duplicate makes.

A void API call is not evidence: every sheet is read back after its transaction
commits and the report says how many sheets actually exist on the new numbers,
not how many calls Revit accepted.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import shtm_core
import shtm_model
import shtm_plan
from shtm_core import eid_value
from shtm_model import new_element_id, find_parameter, param_text, element_name

from Autodesk.Revit.DB import (
    Transaction, TransactionGroup, TransactionStatus, Element, ElementId,
    ViewSheet, Viewport, ScheduleSheetInstance, ViewDuplicateOption,
    FilteredElementCollector, BuiltInParameter, IFailuresPreprocessor,
    FailureProcessingResult, FailureSeverity, StorageType, RevisionCloud,
    TextNote, IndependentTag, FilledRegion, CurveElement, CurveElementType,
    SubTransaction,
    RevitLinkInstance, LinkElementId, UV,
)
from System.Collections.Generic import List as NetList

CHUNK = 8

SKIP_PARAMS = set([
    u"Sheet Number", u"Sheet Name", u"Current Revision",
    u"Current Revision Date", u"Current Revision Description",
    u"Current Revision Issued By", u"Current Revision Issued To",
    u"Current Revision Issued", u"Dependency", u"File Path", u"Guide Grid",
])


# every preprocessor handed to Revit is kept here as well. A Python object
# whose only reference is the .NET side can be collected out from under it.
_PREPROCESSORS = []


class WarningSwallower(IFailuresPreprocessor):
    """Warnings are deleted; errors are recorded and left to fail the
    transaction honestly - but they are no longer left *silently*.

    A commit that comes back RolledBack with nothing said about why is
    unexplainable from the outside, and that is exactly what shipped in 1.1.0:
    the sheets were made and filling them in reported RolledBack, with no
    record anywhere of what Revit had objected to. Each message is taken on its
    own, because DeleteWarning throws on an error and one throw used to abandon
    the whole loop.
    """

    def __init__(self, sink=None):
        self.sink = sink if sink is not None else []

    def PreprocessFailures(self, accessor):
        try:
            messages = list(accessor.GetFailureMessages())
        except Exception:
            return FailureProcessingResult.Continue
        for failure in messages:
            severity = u"failure"
            try:
                severity = u"{0}".format(failure.GetSeverity())
            except Exception:
                pass
            text = u""
            try:
                text = u"{0}".format(failure.GetDescriptionText())
            except Exception:
                pass
            try:
                ids = u", ".join([u"{0}".format(eid_value(i))
                                  for i in failure.GetFailingElementIds()])
            except Exception:
                ids = u""
            try:
                self.sink.append(u"{0}: {1}{2}".format(
                    severity, text,
                    u" [{0}]".format(ids) if ids else u""))
            except Exception:
                pass
            try:
                if failure.GetSeverity() == FailureSeverity.Warning:
                    accessor.DeleteWarning(failure)
            except Exception:
                pass
        return FailureProcessingResult.Continue


def start(doc, name, sink=None):
    transaction = Transaction(doc, name)
    transaction.Start()
    try:
        preprocessor = WarningSwallower(sink)
        _PREPROCESSORS.append(preprocessor)
        if len(_PREPROCESSORS) > 200:
            del _PREPROCESSORS[:100]
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(preprocessor)
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass
    return transaction


def set_element_name(element, name):
    """Which route works varies with the IronPython version, and neither
    reliably raises on failure - so the name is read back."""
    wanted = u"{0}".format(name)
    for route in range(2):
        try:
            if route == 0:
                element.Name = wanted
            else:
                Element.Name.SetValue(element, wanted)
        except Exception:
            continue
        try:
            if element_name(element) == wanted:
                return True
        except Exception:
            pass
    return element_name(element) == wanted


def write_text(element, parameter_name, value):
    """Set a text parameter and prove it landed."""
    param = find_parameter(element, parameter_name)
    if param is None:
        return False, u"no parameter called {0}".format(parameter_name)
    if param.IsReadOnly:
        return False, u"{0} is read only".format(parameter_name)
    try:
        if param.StorageType == StorageType.String:
            param.Set(u"{0}".format(value))
        elif param.StorageType == StorageType.Integer:
            param.Set(int(value or 0))
        else:
            param.SetValueString(u"{0}".format(value))
    except Exception as exc:
        return False, u"{0}: {1}".format(parameter_name, exc)
    back = param_text(find_parameter(element, parameter_name))
    if back.strip() != u"{0}".format(value).strip():
        return False, u"{0} read back as '{1}'".format(parameter_name, back)
    return True, u""


def _plainly(exc):
    """Revit's own exceptions say more in their type name than in their text,
    and some of them have no text at all."""
    try:
        name = type(exc).__name__
    except Exception:
        name = u"error"
    try:
        text = u"{0}".format(exc)
    except Exception:
        text = u""
    if not text:
        return name
    return u"{0}: {1}".format(name, text)


def _line_of(datum, view, DatumExtentType):
    """The datum's own line in this view, as plain numbers.

    Plain numbers on purpose: the comparison is then a rule that can be run on
    the bench rather than something only Revit can answer.
    """
    try:
        curves = datum.GetCurvesInView(DatumExtentType.ViewSpecific, view)
    except Exception:
        return None
    if curves is None or not curves.Count:
        return None
    try:
        curve = curves[0]
        start_point = curve.GetEndPoint(0)
        end_point = curve.GetEndPoint(1)
        return ((start_point.X, start_point.Y, start_point.Z),
                (end_point.X, end_point.Y, end_point.Z))
    except Exception:
        return None


def _same_line(one, other):
    return shtm_core.same_line(one, other)


def _because(failures):
    """A rolled-back commit has to say what Revit objected to. Without this the
    only thing on screen is the word RolledBack, which explains nothing."""
    if not failures:
        return u" (Revit gave no reason)"
    return u" - Revit said: {0}".format(u"; ".join(failures[:4]))


def _settled(values):
    if not values:
        return u"(none)"
    try:
        keys = sorted(values.keys())
    except Exception:
        return u"{0}".format(values)
    return u"; ".join([u"{0}={1}".format(k, values[k]) for k in keys])


def _revit_version(doc):
    try:
        application = doc.Application
        return u"{0} build {1}".format(application.VersionNumber,
                                       application.VersionBuild)
    except Exception:
        return u"unknown"


class Duplicator(object):
    """Runs a plan. Called from an ExternalEvent handler, never from the window."""

    def __init__(self, doc):
        self.doc = doc
        self.report = {
            "sheets": [],
            "views": 0,
            "reused": 0,
            "placed": 0,
            "problems": [],
            "notes": [],
            "debug": [],
            # revision clouds taken off the new views (1.9.0: always)
            "clouds_removed": 0,
            # what the cleaning ticks took off (or added): what -> count
            "cleaned": {},
        }
        self.new_views = {}
        # old view id -> the datum ids whose stretch was copied into its copy,
        # so the read-back knows what it is supposed to be checking
        self.stretched = {}
        self.debug = False
        # called with (sheet row, new id or None, reason) as each sheet lands,
        # so a window can paint that row before the next one is started
        self.on_sheet = None
        # every (row, report entry) reported as created, so a rollback can take
        # the green back: a sheet made inside a group that is then rolled back
        # does not exist, whatever was said about it at the time
        self.created = []

    def trace(self, text):
        """Every step, when the debug tick is on. Off, it costs one attribute
        lookup - which is what makes it safe to call from everywhere."""
        if not self.debug:
            return
        try:
            self.report["debug"].append(u"{0}".format(text))
        except Exception:
            pass

    # ============ views ============

    def _duplicate_option(self, options):
        if options.get("with_detailing", True):
            return ViewDuplicateOption.WithDetailing
        return ViewDuplicateOption.Duplicate

    def _strip_room_tags(self, view_id):
        wanted = []
        for name in ("OST_RoomTags", "OST_MEPSpaceTags"):
            category = shtm_model.category_id(name)
            if eid_value(category) == 0:
                continue
            try:
                collector = FilteredElementCollector(self.doc, view_id)
                collector = collector.OfCategoryId(category)
                collector = collector.WhereElementIsNotElementType()
                for element in collector:
                    wanted.append(element.Id)
            except Exception:
                pass
        for element_id in wanted:
            try:
                self.doc.Delete(element_id)
            except Exception:
                pass
        return len(wanted)

    def _copy_crop(self, old_view, new_view):
        """A new dependent inherits the parent's crop, so the old dependent's
        own crop has to be put back on it or every dependent looks the same."""
        try:
            param = old_view.get_Parameter(
                BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
            target = new_view.get_Parameter(
                BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
            if param is not None and target is not None and not target.IsReadOnly:
                target.Set(param.AsElementId())
        except Exception:
            pass
        try:
            new_view.CropBoxActive = old_view.CropBoxActive
            new_view.CropBoxVisible = old_view.CropBoxVisible
        except Exception:
            pass
        try:
            new_view.CropBox = old_view.CropBox
        except Exception:
            pass
        try:
            old_shape = old_view.GetCropRegionShapeManager()
            new_shape = new_view.GetCropRegionShapeManager()
            loops = old_shape.GetCropShape()
            if loops is not None and loops.Count > 0:
                new_shape.SetCropShape(loops[0])
        except Exception:
            pass
        try:
            old_ann = old_view.GetCropRegionShapeManager()
            new_ann = new_view.GetCropRegionShapeManager()
            new_ann.LeftAnnotationCropOffset = old_ann.LeftAnnotationCropOffset
            new_ann.RightAnnotationCropOffset = old_ann.RightAnnotationCropOffset
            new_ann.TopAnnotationCropOffset = old_ann.TopAnnotationCropOffset
            new_ann.BottomAnnotationCropOffset = old_ann.BottomAnnotationCropOffset
        except Exception:
            pass

    def _copy_datum_extents(self, old_view, new_view):
        """Match the grid and level stretch, view to view.

        A datum end is either **3D**, where the line runs to the model extent
        and every view shares it, or **view specific**, where this view holds
        its own shortened line and its own bubbles. Only the second kind is an
        override, and only the second kind is this tool's business.

        Version 1.2.0 read the view-specific curve and set it whatever the
        source end was actually doing. `GetCurvesInView(ViewSpecific, view)`
        hands back the model-extent line for a datum that is in 3D mode, and
        `SetCurveInView` puts the target end *into* view-specific mode to
        accept it - so every grid in the new view was pinned to the full model
        extent. The annotation crop then grew to contain the bubbles, the
        viewport grew with it, and the plan ended up a third of the size it
        should have been on a sheet of grid lines running off the page.

        So: copy the extent type end by end, and only touch the curve where the
        source really is view specific. An override is copied; one is never
        invented.
        """
        try:
            from Autodesk.Revit.DB import (Grid, Level, DatumExtentType,
                                           DatumEnds, Line, XYZ)
        except Exception as exc:
            self.trace(u"  datum extents not available: {0}".format(_plainly(exc)))
            return 0

        ends = (DatumEnds.End0, DatumEnds.End1)
        stretched = 0
        left_alone = 0
        refused = []
        for kind in (Grid, Level):
            try:
                datums = list(FilteredElementCollector(self.doc, old_view.Id)
                              .OfClass(kind).WhereElementIsNotElementType())
            except Exception:
                continue
            for datum in datums:
                try:
                    kinds = []
                    for end in ends:
                        try:
                            kinds.append(datum.GetDatumExtentTypeInView(end,
                                                                       old_view))
                        except Exception:
                            kinds.append(None)
                    wants_curve = shtm_core.datum_needs_curve(
                        kinds, DatumExtentType.ViewSpecific)

                    for end, extent in zip(ends, kinds):
                        if extent is None:
                            continue
                        try:
                            datum.SetDatumExtentType(end, new_view, extent)
                        except Exception:
                            continue

                    if wants_curve:
                        # both ends have to be view specific in the target
                        # before it will report a line of its own, let alone
                        # take one
                        for end in ends:
                            try:
                                datum.SetDatumExtentType(
                                    end, new_view, DatumExtentType.ViewSpecific)
                            except Exception:
                                pass
                        wanted = _line_of(datum, old_view, DatumExtentType)
                        current = _line_of(datum, new_view, DatumExtentType)
                        fitted = shtm_core.fit_line(current, wanted)
                        if fitted is None:
                            reason = u"no line to fit ({0})".format(
                                element_name(datum))
                            if reason not in refused:
                                refused.append(reason)
                        else:
                            datum.SetCurveInView(
                                DatumExtentType.ViewSpecific, new_view,
                                Line.CreateBound(XYZ(*fitted[0]),
                                                 XYZ(*fitted[1])))
                            stretched += 1
                            self.stretched.setdefault(
                                eid_value(old_view.Id), []).append(
                                    eid_value(datum.Id))
                    else:
                        # 3D at both ends: the line is the model's, not this
                        # view's, and writing a curve would pin it here
                        left_alone += 1

                    self._datum_bubbles(datum, old_view, new_view, ends)
                except Exception as exc:
                    # a swallowed refusal here is the difference between "the
                    # grids match" and "the grids silently did not move"
                    reason = _plainly(exc)
                    if reason not in refused:
                        refused.append(reason)
                    continue
        self.trace(u"  {0} datum(s) stretched to match, {1} left on their 3D "
                   u"extent".format(stretched, left_alone))
        for reason in refused:
            self.trace(u"  a datum was refused: {0}".format(reason))
        return stretched

    def _datum_bubbles(self, datum, old_view, new_view, ends):
        for end in ends:
            try:
                if datum.IsBubbleVisibleInView(end, old_view):
                    datum.ShowBubbleInView(end, new_view)
                else:
                    datum.HideBubbleInView(end, new_view)
            except Exception:
                continue

    def _apply_template(self, job, new_view, options):
        """Dependents take their template from the parent, so they are left
        alone rather than being handed one Revit would refuse."""
        if job["action"] == shtm_plan.DEPENDENT:
            return
        templates = options.get("templates") or {}
        wanted = templates.get(job.get("type"), 0)
        if not wanted:
            return
        try:
            if wanted < 0:
                new_view.ViewTemplateId = ElementId.InvalidElementId
            else:
                new_view.ViewTemplateId = new_element_id(wanted)
        except Exception as exc:
            self.report["problems"].append(
                u"{0}: view template would not apply ({1})".format(job["name"], exc))

    def _one_view(self, job, options, made):
        action = job["action"]
        old_id = job["old_id"]
        if action == shtm_plan.REUSE:
            made[old_id] = old_id
            self.report["reused"] += 1
            self._note_reused_clouds(old_id, job["name"])
            return

        old_view = self.doc.GetElement(new_element_id(old_id))
        if old_view is None:
            self.report["problems"].append(
                u"{0}: the source view could not be read".format(job["name"]))
            return

        if action == shtm_plan.DEPENDENT:
            parent_new = made.get(job["parent_old"]) or self.new_views.get(job["parent_old"])
            if not parent_new:
                self.report["problems"].append(
                    u"{0}: the new parent view was not made, so the dependent "
                    u"was skipped".format(job["name"]))
                return
            parent = self.doc.GetElement(new_element_id(parent_new))
            new_id = parent.Duplicate(ViewDuplicateOption.AsDependent)
        else:
            option = self._duplicate_option(options)
            try:
                if not old_view.CanViewBeDuplicated(option):
                    option = ViewDuplicateOption.Duplicate
            except Exception:
                pass
            new_id = old_view.Duplicate(option)

        if new_id is None or eid_value(new_id) == 0:
            self.report["problems"].append(
                u"{0}: Revit would not duplicate this view".format(job["name"]))
            return

        new_view = self.doc.GetElement(new_id)
        if action == shtm_plan.DEPENDENT:
            self._copy_crop(old_view, new_view)
            # it has to hang off the new parent, not stand on its own
            try:
                primary = eid_value(new_view.GetPrimaryViewId())
                if primary != parent_new:
                    self.report["problems"].append(
                        u"{0}: Revit made it, but not as a dependent of the new "
                        u"parent".format(job["name"]))
                self.trace(u"  dependent {0} -> parent {1}".format(
                    job["name"], primary))
            except Exception:
                pass

        if not set_element_name(new_view, job.get("new_name") or job["name"]):
            self.report["problems"].append(
                u"{0}: the new view kept the name '{1}'".format(
                    job["name"], element_name(new_view)))

        self._apply_template(job, new_view, options)

        # a copy starts with no revisions: duplicating with detailing brings
        # the source view's revision clouds, and they would put the old
        # revisions on the new sheet's revision schedule
        self._isolated(new_view, u"its revision clouds were not taken off",
                       lambda: self._strip_clouds(new_view))

        if action != shtm_plan.DEPENDENT:
            # a dependent shows its parent's annotation, and the parent is a
            # new copy that has had all of this done to it already
            self._isolated(new_view, u"it was not cleaned",
                           lambda: self._clean_view(new_view, options))

        if not options.get("retain_room_names", True):
            self._isolated(new_view, u"its room tags were not taken off",
                           lambda: self._strip_room_tags(new_id))

        if options.get("tag_rooms", False) and action != shtm_plan.DEPENDENT:
            self._isolated(new_view, u"its rooms were not tagged",
                           lambda: self._tag_rooms(new_view))

        made[eid_value(old_view.Id)] = eid_value(new_id)
        self.report["views"] += 1

    # ---- cleaning the new views and sheets (1.9.0) ----

    def _owned(self, view, cls, keep=None):
        """The elements of `cls` this view owns - not ones another view owns
        that happen to show in it."""
        found = []
        try:
            for element in FilteredElementCollector(self.doc, view.Id).OfClass(cls):
                try:
                    if eid_value(element.OwnerViewId) != eid_value(view.Id):
                        continue
                    if eid_value(element.GroupId) > 0:
                        # deleting a member of a group is an error Revit posts
                        # at commit - left alone, and counted
                        self.report["cleaned"][u"left in groups"] = (
                            self.report["cleaned"].get(u"left in groups", 0) + 1)
                        continue
                    if keep is not None and not keep(element):
                        continue
                    found.append(element.Id)
                except Exception:
                    continue
        except Exception:
            pass
        return found

    def _delete(self, ids, what, view):
        if not ids:
            return 0
        gone = 0
        batch = NetList[ElementId]()
        for element_id in ids:
            batch.Add(element_id)
        try:
            self.doc.Delete(batch)
            gone = len(ids)
        except Exception:
            # one at a time, so one Revit will not let go of keeps the rest
            for element_id in ids:
                try:
                    self.doc.Delete(element_id)
                    gone += 1
                except Exception:
                    continue
        if gone:
            self.report["cleaned"][what] = self.report["cleaned"].get(what, 0) + gone
            self.trace(u"  {0} {1} removed from {2}".format(gone, what, element_name(view)))
        return gone

    def _clean_view(self, view, options):
        """Take off what the run was asked to take off a new view or sheet:
        text notes and tags, and detail lines and filled regions."""
        if options.get("strip_annotation", False):
            self._delete(self._owned(view, TextNote), u"text note(s)", view)
            self._delete(self._owned(view, IndependentTag), u"tag(s)", view)
        if options.get("strip_lines", False):
            # detail lines only: area boundaries and room separation lines are
            # curve elements too, and taking them would break the view
            self._delete(self._owned(
                view, CurveElement,
                lambda c: c.CurveElementType == CurveElementType.DetailCurve),
                u"line(s)", view)
            self._delete(self._owned(view, FilledRegion), u"filled region(s)", view)

    def _tag_rooms(self, view):
        """Every room on the plan's level gets a tag - the project's own and
        those in loaded links - and any room tag showing '?' (tagging no
        room any more) is taken off. Plan views only: a room tag needs one."""
        level = None
        try:
            level = view.GenLevel
        except Exception:
            level = None
        if level is None:
            return
        tagged = set()
        orphans = []
        for tag in self._room_tags(view):
            try:
                if tag.IsOrphaned:
                    orphans.append(tag.Id)
                    continue
                key = tag.TaggedRoomId
                tagged.add((eid_value(key.LinkInstanceId),
                            eid_value(key.LinkedElementId) if eid_value(key.LinkInstanceId) > 0
                            else eid_value(key.HostElementId)))
            except Exception:
                continue
        self._delete(orphans, u"'?' room tag(s)", view)
        made = 0
        for link_id, room, point in self._rooms_on(view, level):
            key = (link_id, eid_value(room.Id))
            if key in tagged:
                continue
            try:
                target = (LinkElementId(new_element_id(link_id), room.Id) if link_id > 0
                          else LinkElementId(room.Id))
                if self.doc.Create.NewRoomTag(target, UV(point.X, point.Y), view.Id):
                    made += 1
                    tagged.add(key)
            except Exception as exc:
                self.trace(u"  room {0} not tagged: {1}".format(
                    shtm_model.element_name(room), _plainly(exc)))
        if made:
            self.report["cleaned"][u"room tag(s) added"] = (
                self.report["cleaned"].get(u"room tag(s) added", 0) + made)
            self.trace(u"  {0} room tag(s) added to {1}".format(made, element_name(view)))

    def _room_tags(self, view):
        tags = []
        category = shtm_model.category_id("OST_RoomTags")
        try:
            for tag in FilteredElementCollector(self.doc, view.Id).OfCategoryId(category) \
                    .WhereElementIsNotElementType():
                tags.append(tag)
        except Exception:
            pass
        return tags

    def _rooms_on(self, view, level):
        """(link instance id or -1, room, point in this model) for every placed
        room on the view's level and inside its crop."""
        rooms = []
        category = shtm_model.category_id("OST_Rooms")
        crop = None
        try:
            if view.CropBoxActive:
                crop = view.CropBox
        except Exception:
            crop = None

        def inside(point):
            if crop is None:
                return True
            try:
                local = crop.Transform.Inverse.OfPoint(point)
                return (crop.Min.X <= local.X <= crop.Max.X and
                        crop.Min.Y <= local.Y <= crop.Max.Y)
            except Exception:
                return True

        def placed(room):
            try:
                return room.Area > 0 and room.Location is not None
            except Exception:
                return False

        try:
            for room in FilteredElementCollector(self.doc).OfCategoryId(category) \
                    .WhereElementIsNotElementType():
                if placed(room) and eid_value(room.LevelId) == eid_value(level.Id):
                    point = room.Location.Point
                    if inside(point):
                        rooms.append((-1, room, point))
        except Exception:
            pass
        try:
            links = list(FilteredElementCollector(self.doc).OfClass(RevitLinkInstance))
        except Exception:
            links = []
        for link in links:
            try:
                link_doc = link.GetLinkDocument()
                if link_doc is None:
                    continue
                transform = link.GetTotalTransform()
                for room in FilteredElementCollector(link_doc).OfCategoryId(category) \
                        .WhereElementIsNotElementType():
                    if not placed(room):
                        continue
                    point = transform.OfPoint(room.Location.Point)
                    # ProjectElevation: from the internal origin, the frame the
                    # transformed room point is in. Level.Elevation is from
                    # the level type's base (project base or survey point) and
                    # can be a different number for the same level
                    if not shtm_core.near_level(point.Z, level.ProjectElevation):
                        continue
                    if inside(point):
                        rooms.append((eid_value(link.Id), room, point))
            except Exception as exc:
                self.trace(u"  a linked model's rooms could not be read: {0}".format(
                    _plainly(exc)))
        return rooms

    def _note_reused_clouds(self, view_id, name):
        """A view placed again as it is is the same view, so its revision
        clouds cannot be taken off without taking them off the original - and
        they show on the new sheet. Say so rather than leave it to be found."""
        try:
            view = self.doc.GetElement(new_element_id(view_id))
            count = 0
            for cloud in FilteredElementCollector(self.doc, view.Id).OfClass(RevisionCloud):
                if eid_value(cloud.OwnerViewId) == view_id:
                    count += 1
            if count:
                self.report["notes"].append(
                    u"{0} is placed again as it is and carries {1} revision "
                    u"cloud(s) - they show on the new sheets. Set it to be "
                    u"duplicated in Options to start it clean.".format(name, count))
        except Exception:
            pass

    def _strip_clouds(self, view):
        """Delete every revision cloud the new view owns. Only clouds owned by
        this view - a dependent shows its parent's, and the parent is a new
        copy that has already been cleared.

        A cloud on an issued revision is locked, so that revision is un-issued
        for the delete and issued again straight after, all inside the same
        sub-transaction: the revision itself never changes."""
        clouds = []
        try:
            for cloud in FilteredElementCollector(self.doc, view.Id).OfClass(RevisionCloud):
                try:
                    if eid_value(cloud.OwnerViewId) == eid_value(view.Id):
                        clouds.append(cloud)
                except Exception:
                    continue
        except Exception:
            clouds = []
        if not clouds:
            return
        reissue = []
        for cloud in clouds:
            try:
                revision = self.doc.GetElement(cloud.RevisionId)
                if revision is not None and revision.Issued and revision not in reissue:
                    revision.Issued = False
                    reissue.append(revision)
            except Exception:
                continue
        try:
            gone = self._delete([c.Id for c in clouds], u"revision cloud(s)", view)
            self.report["clouds_removed"] += gone
        finally:
            for revision in reissue:
                try:
                    revision.Issued = True
                except Exception as exc:
                    self.report["problems"].append(
                        u"revision {0} could not be issued again after its clouds were "
                        u"taken off a new view ({1})".format(
                            element_name(revision), _plainly(exc)))

    def _isolated(self, view, label, action):
        """One clean-up step in a sub-transaction of its own, so a step Revit
        refuses is rolled back alone - never the view or sheet it is on."""
        sub = SubTransaction(self.doc)
        try:
            sub.Start()
            action()
            sub.Commit()
        except Exception as exc:
            try:
                sub.RollBack()
            except Exception:
                pass
            self.report["problems"].append(u"{0}: {1} - left as it was ({2})".format(
                element_name(view), label, _plainly(exc)))

    def _view_chunk(self, chunk, options):
        made = {}
        failures = []
        transaction = start(self.doc, "RevoBIM - duplicate views", failures)
        try:
            for job in chunk:
                self._one_view(job, options, made)
            status = transaction.Commit()
        except Exception as exc:
            try:
                transaction.RollBack()
            except Exception:
                pass
            self._record(failures)
            return False, _plainly(exc)
        self._record(failures)
        if status != TransactionStatus.Committed:
            return False, u"Revit reported {0}{1}".format(status,
                                                          _because(failures))
        self.new_views.update(made)
        return True, None

    def make_views(self, plan, options, progress=None):
        jobs = plan["jobs"]
        total = len(jobs) or 1
        done = 0
        index = 0
        while index < len(jobs):
            chunk = jobs[index:index + CHUNK]
            index += CHUNK
            ok, problem = self._view_chunk(chunk, options)
            if not ok and len(chunk) > 1:
                # replay one at a time so the one at fault is named and only
                # that one is lost
                for job in chunk:
                    ok_one, problem_one = self._view_chunk([job], options)
                    if not ok_one:
                        self.report["problems"].append(
                            u"{0}: {1}".format(job["name"], problem_one))
            elif not ok:
                self.report["problems"].append(
                    u"{0}: {1}".format(chunk[0]["name"], problem))
            done += len(chunk)
            if progress is not None:
                progress(done * 100 // total, done, total, u"views")

    # ============ grid and level stretch ============

    def match_datums(self, plan, options):
        """Match the grid and level stretch, in two waves with a commit
        between them.

        Revit propagates a primary view's datum extents down to its dependents
        when the document regenerates. Setting the parent and then the
        dependent inside one transaction therefore loses the dependent's own
        stretch at commit, which is why 1.2.1 still came out wrong: the write
        happened and was then overwritten by the parent's.

        So the parents and plain duplicates go first and are **committed**, and
        only then - with the propagation already done and out of the way - does
        each dependent get its own. Every dependent is treated as a view in its
        own right and matched against the dependent it was duplicated from, not
        against the parent.
        """
        if not options.get("grid_extents", True):
            return
        jobs = [j for j in (plan.get("jobs") or [])
                if j["action"] != shtm_plan.REUSE
                and self.new_views.get(j["old_id"])]
        waves = [
            ([j for j in jobs if j["action"] != shtm_plan.DEPENDENT],
             u"the views"),
            ([j for j in jobs if j["action"] == shtm_plan.DEPENDENT],
             u"the dependent views"),
        ]
        for wave, label in waves:
            if not wave:
                continue
            failures = []
            transaction = start(self.doc,
                                "RevoBIM - match the grid stretch", failures)
            try:
                for job in wave:
                    self._match_one(job)
                self.doc.Regenerate()
                status = transaction.Commit()
            except Exception as exc:
                try:
                    transaction.RollBack()
                except Exception:
                    pass
                self.report["problems"].append(
                    u"the grid stretch on {0} was not matched - {1}".format(
                        label, _plainly(exc)))
                self._record(failures)
                continue
            self._record(failures)
            if status != TransactionStatus.Committed:
                self.report["problems"].append(
                    u"the grid stretch on {0} reported {1}{2}".format(
                        label, status, _because(failures)))
        self._verify_datums(jobs)

    def _match_one(self, job):
        old_view = self.doc.GetElement(new_element_id(job["old_id"]))
        new_view = self.doc.GetElement(
            new_element_id(self.new_views.get(job["old_id"])))
        if old_view is None or new_view is None:
            return
        self.trace(u"matching datums: {0} -> {1}".format(
            job.get("name"), job.get("new_name")))
        self._copy_datum_extents(old_view, new_view)

    def _verify_datums(self, jobs):
        """A void API call is not evidence. Every line that was supposed to be
        copied is read back out of the new view and compared with the one it
        came from."""
        try:
            from Autodesk.Revit.DB import DatumExtentType
        except Exception:
            return
        wrong = 0
        looked = 0
        for job in jobs:
            old_view = self.doc.GetElement(new_element_id(job["old_id"]))
            new_view = self.doc.GetElement(
                new_element_id(self.new_views.get(job["old_id"])))
            if old_view is None or new_view is None:
                continue
            for datum_id in self.stretched.get(job["old_id"], []):
                datum = self.doc.GetElement(new_element_id(datum_id))
                if datum is None:
                    continue
                looked += 1
                wanted = _line_of(datum, old_view, DatumExtentType)
                got = _line_of(datum, new_view, DatumExtentType)
                if _same_line(shtm_core.fit_line(got, wanted), got):
                    continue
                wrong += 1
                self.trace(u"  {0}: '{1}' did not take the stretch".format(
                    job.get("new_name"), element_name(datum)))
        if wrong:
            self.report["problems"].append(
                u"{0} of {1} grid/level line(s) did not take the stretch from "
                u"the view they were copied from".format(wrong, looked))
        else:
            self.trace(u"all {0} stretched datum line(s) read back "
                       u"correctly".format(looked))

    # ============ sheets ============

    def _copy_sheet_parameters(self, source, target):
        for param in source.Parameters:
            try:
                if param.IsReadOnly:
                    continue
                name = u"{0}".format(param.Definition.Name)
            except Exception:
                continue
            if name in SKIP_PARAMS:
                continue
            try:
                target_param = find_parameter(target, name)
                if target_param is None or target_param.IsReadOnly:
                    continue
                if param.StorageType != target_param.StorageType:
                    continue
                if param.StorageType == StorageType.String:
                    target_param.Set(param.AsString() or u"")
                elif param.StorageType == StorageType.Integer:
                    target_param.Set(param.AsInteger())
                elif param.StorageType == StorageType.Double:
                    target_param.Set(param.AsDouble())
                elif param.StorageType == StorageType.ElementId:
                    target_param.Set(param.AsElementId())
            except Exception:
                continue

    def _copy_titleblock_parameters(self, source_sheet_id, new_sheet):
        """The title block's own parameters - and only its own.

        A title block instance also shows the sheet's parameters: Sheet Number,
        Sheet Name, the issue date, Drawn By and the rest are the *sheet's*
        values surfaced on the instance, and writing them writes through to the
        sheet. Copying them from the old title block therefore put the old
        sheet number back on the new sheet, Revit refused the duplicate number,
        and the whole transaction rolled back - which is what made 1.1.0 report
        "the sheet was made, but filling it in reported RolledBack" and leave
        every new sheet called Unnamed.

        So anything the sheet itself carries is skipped here. It has already
        been copied, once, onto the sheet where it belongs.
        """
        source_type, source_instance = shtm_model.titleblock_type_of(
            self.doc, source_sheet_id)
        if not source_instance:
            return 0
        old = self.doc.GetElement(new_element_id(source_instance))
        new_type, new_instance = shtm_model.titleblock_type_of(
            self.doc, eid_value(new_sheet.Id))
        if not new_instance or old is None:
            return 0
        new = self.doc.GetElement(new_element_id(new_instance))
        if new is None:
            return 0

        sheet_names = []
        try:
            for param in new_sheet.Parameters:
                try:
                    sheet_names.append(u"{0}".format(param.Definition.Name))
                except Exception:
                    pass
        except Exception:
            pass
        titleblock_names = []
        for param in old.Parameters:
            try:
                if param.IsReadOnly:
                    continue
                titleblock_names.append(u"{0}".format(param.Definition.Name))
            except Exception:
                continue
        wanted = set(shtm_core.titleblock_copy_names(
            titleblock_names, sheet_names, SKIP_PARAMS))

        copied = 0
        for param in old.Parameters:
            try:
                if param.IsReadOnly:
                    continue
                name = u"{0}".format(param.Definition.Name)
            except Exception:
                continue
            if name not in wanted:
                continue
            try:
                target = find_parameter(new, name)
                if target is None or target.IsReadOnly:
                    continue
                if param.StorageType != target.StorageType:
                    continue
                if param.StorageType == StorageType.String:
                    target.Set(param.AsString() or u"")
                elif param.StorageType == StorageType.Integer:
                    target.Set(param.AsInteger())
                elif param.StorageType == StorageType.Double:
                    target.Set(param.AsDouble())
                elif param.StorageType == StorageType.ElementId:
                    target.Set(param.AsElementId())
                copied += 1
            except Exception:
                continue
        return copied

    def _push_name_parameters(self, sheet, name, name_params, reserved,
                              delimiter=shtm_core.DEFAULT_DELIMITER):
        if not name_params:
            return
        writes, skipped = shtm_core.name_push_plan(name, name_params, reserved,
                                                   delimiter)
        for parameter_name, value in writes:
            ok, problem = write_text(sheet, parameter_name, value)
            if not ok and value:
                self.report["problems"].append(
                    u"{0}: {1}".format(element_sheet_number(sheet), problem))
        for parameter_name in skipped:
            note = (u"{0} is set by the browser grouping, so the sheet name "
                    u"was not pushed into it".format(parameter_name))
            if note not in self.report["notes"]:
                self.report["notes"].append(note)

    def _apply_grouping(self, sheet, grouping):
        for parameter_name in grouping:
            value = grouping[parameter_name]
            if value is None:
                continue
            ok, problem = write_text(sheet, parameter_name, value)
            if not ok:
                self.report["problems"].append(
                    u"{0}: {1}".format(element_sheet_number(sheet), problem))

    def _place(self, row, new_sheet, plan):
        placed = 0
        for placement in plan["placements"]:
            if placement["sheet"] != row["id"]:
                continue
            new_view_id = self.new_views.get(placement["view"])
            if not new_view_id:
                continue
            source = self.doc.GetElement(new_element_id(placement.get("src", 0)))
            try:
                if placement["kind"] == "schedule":
                    point = source.Point if source is not None else None
                    instance = ScheduleSheetInstance.Create(
                        self.doc, new_sheet.Id, new_element_id(new_view_id), point)
                    if instance is not None:
                        placed += 1
                    continue
                centre = source.GetBoxCenter() if source is not None else None
                if centre is None:
                    self.report["problems"].append(
                        u"{0}: the source viewport could not be read".format(
                            row["new_number"]))
                    continue
                if not Viewport.CanAddViewToSheet(
                        self.doc, new_sheet.Id, new_element_id(new_view_id)):
                    self.report["problems"].append(
                        u"{0}: Revit will not put that view on a sheet - it is "
                        u"already placed on another one".format(row["new_number"]))
                    continue
                viewport = Viewport.Create(
                    self.doc, new_sheet.Id, new_element_id(new_view_id), centre)
                if viewport is None:
                    continue
                placed += 1
                try:
                    viewport.ChangeTypeId(source.GetTypeId())
                except Exception:
                    pass
                try:
                    viewport.LabelOffset = source.LabelOffset
                except Exception:
                    pass
            except Exception as exc:
                self.report["problems"].append(
                    u"{0}: {1}".format(row["new_number"], exc))
        self.report["placed"] += placed
        return placed

    def _one_sheet(self, row, plan, options, grouping, name_params):
        """Two transactions, not one.

        The first makes the sheet and gives it its number - the part that has to
        happen for the run to have meant anything. The second does everything
        optional: the parameter copies, the revisions, the views, the browser
        grouping and the name push. Anything in the second failing used to take
        the sheet with it, which is how a run could end with the views made and
        no sheets to put them on.
        """
        source = self.doc.GetElement(new_element_id(row["id"]))
        if source is None:
            self.report["problems"].append(
                u"{0}: the source sheet could not be read".format(row["old_number"]))
            self.trace(u"sheet {0}: source element {1} came back None".format(
                row["old_number"], row["id"]))
            return None

        try:
            placeholder = bool(source.IsPlaceholder)
        except Exception:
            placeholder = False

        type_id = 0
        if not placeholder:
            try:
                type_id, _instance = shtm_model.titleblock_type_of(self.doc, row["id"])
            except Exception as exc:
                self.trace(u"sheet {0}: no title block read ({1})".format(
                    row["old_number"], exc))
        self.trace(u"sheet {0} -> {1}: placeholder={2} titleblock type={3}".format(
            row["old_number"], row["new_number"], placeholder, type_id))

        # ---- transaction one: the sheet itself ----
        new_sheet = None
        failures = []
        transaction = start(self.doc, "RevoBIM - new sheet", failures)
        try:
            if placeholder:
                new_sheet = ViewSheet.CreatePlaceholder(self.doc)
            elif type_id:
                new_sheet = ViewSheet.Create(self.doc, new_element_id(type_id))
            else:
                new_sheet = ViewSheet.Create(self.doc, ElementId.InvalidElementId)
            if new_sheet is None:
                raise Exception("ViewSheet.Create returned nothing")
            self.trace(u"  created id={0}".format(eid_value(new_sheet.Id)))
            new_sheet.SheetNumber = row["new_number"]
            self.trace(u"  numbered {0}".format(row["new_number"]))
            status = transaction.Commit()
        except Exception as exc:
            try:
                transaction.RollBack()
            except Exception:
                pass
            self.report["problems"].append(
                u"{0}: the sheet was not made - {1}".format(
                    row["new_number"], _plainly(exc)))
            self.trace(u"  FAILED making the sheet: {0}".format(_plainly(exc)))
            self._record(failures)
            return None

        self._record(failures)
        if status != TransactionStatus.Committed:
            self.report["problems"].append(
                u"{0}: the sheet was not made - Revit reported {1}{2}".format(
                    row["new_number"], status, _because(failures)))
            self.trace(u"  commit reported {0}".format(status))
            return None

        new_id = new_sheet.Id

        # ---- the rest, in steps of its own ----
        # Three transactions rather than one, so a step Revit refuses costs
        # that step and not the other two. Filling a sheet in is a list of
        # unrelated favours, and there is no reason for the browser grouping to
        # be lost because a title block parameter would not take.
        steps = [
            (u"the name and the sheet's parameters", self._step_naming),
            (u"clearing the revisions", self._step_clean),
            (u"placing the views", self._step_views),
            (u"the grouping and the name parameters", self._step_grouping),
        ]
        for label, action in steps:
            failures = []
            transaction = start(self.doc, "RevoBIM - " + label, failures)
            try:
                sheet = self.doc.GetElement(new_id)
                if sheet is None:
                    raise Exception("the new sheet could not be read back")
                action(sheet, source, row, plan, options, grouping, name_params)
                status = transaction.Commit()
            except Exception as exc:
                try:
                    transaction.RollBack()
                except Exception:
                    pass
                self.report["problems"].append(
                    u"{0}: {1} failed - {2}".format(
                        row["new_number"], label, _plainly(exc)))
                self.trace(u"  FAILED {0}: {1}".format(label, _plainly(exc)))
                self._record(failures)
                continue
            if status != TransactionStatus.Committed:
                self.report["problems"].append(
                    u"{0}: {1} reported {2}{3}".format(
                        row["new_number"], label, status,
                        _because(failures)))
                self.trace(u"  {0} reported {1}".format(label, status))
            self._record(failures)
        return new_id

    def _record(self, failures):
        for line in failures or []:
            self.trace(u"    Revit said: {0}".format(line))

    # ---- the three steps ----

    def _step_naming(self, sheet, source, row, plan, options, grouping,
                     name_params):
        if not set_element_name(sheet, row["new_name"]):
            self.report["problems"].append(
                u"{0}: the name would not take".format(row["new_number"]))
        if options.get("copy_sheet_params", True):
            self._copy_sheet_parameters(source, sheet)
            # nothing in a parameter copy is allowed to put the number back
            try:
                if u"{0}".format(sheet.SheetNumber) != row["new_number"]:
                    sheet.SheetNumber = row["new_number"]
            except Exception:
                pass


    def _step_clean(self, sheet, source, row, plan, options, grouping,
                    name_params):
        """A new sheet carries no revisions (1.9.0: forced, there is no
        option) - nothing added by hand and no clouds on the sheet itself - and
        is cleaned as the views are. A step of its own, so a refusal here
        cannot cost the sheet its name and parameters."""
        try:
            sheet.SetAdditionalRevisionIds(NetList[ElementId]())
        except Exception as exc:
            self.trace(u"  revisions not cleared: {0}".format(_plainly(exc)))
        self._isolated(sheet, u"its revision clouds were not taken off",
                       lambda: self._strip_clouds(sheet))
        self._isolated(sheet, u"it was not cleaned",
                       lambda: self._clean_view(sheet, options))

    def _step_views(self, sheet, source, row, plan, options, grouping,
                    name_params):
        try:
            placeholder = bool(sheet.IsPlaceholder)
        except Exception:
            placeholder = False
        if placeholder:
            return
        placed = self._place(row, sheet, plan)
        self.trace(u"  {0} view(s) placed".format(placed))
        if options.get("copy_titleblock_params", True):
            copied = self._copy_titleblock_parameters(row["id"], sheet)
            self.trace(u"  {0} title block parameter(s) copied".format(copied))

    def _step_grouping(self, sheet, source, row, plan, options, grouping,
                       name_params):
        # the name push runs first and the grouping second, and the name push
        # is not allowed to touch a parameter the grouping is writing. Both
        # orders on their own are a coin toss; this way the typed value wins
        # whichever way round the two lists happen to be pointed.
        reserved = [key for key in (grouping or {}) if grouping[key] is not None]
        if options.get("write_name_params", True):
            self._push_name_parameters(sheet, row["new_name"], name_params,
                                       reserved, options.get("name_delimiter",
                                                             shtm_core.DEFAULT_DELIMITER))
        self._apply_grouping(sheet, grouping)

    def _landed(self, row, new_id, reason=u""):
        if self.on_sheet is None:
            return
        try:
            self.on_sheet(row, new_id, reason)
        except Exception as exc:
            self.trace(u"  the sheet callback failed: {0}".format(_plainly(exc)))

    def run_batches(self, batches, name_params, progress=None):
        """Several sets, one after another, as one undo step.

        Each set is a full copy of the source sheets with its own template and
        its own names, so the view map is cleared between sets: a view copied
        in set one must not be what set two places on its sheets.

        TransactionGroups nest, so each set keeps its own group - and its own
        rollback - inside the outer one.
        """
        total = len(batches)
        outer = TransactionGroup(self.doc, "RevoBIM Sheet Manager - Duplicate sets")
        try:
            outer.Start()
            for position, batch in enumerate(batches):
                self.new_views = {}
                self.stretched = {}
                self.trace(u"===== set {0} of {1}: {2} =====".format(
                    position + 1, total, batch.get("template", u"")))

                def scoped(percent, done, count, label=u"", _p=position):
                    if progress is not None:
                        progress(percent, done, count, u"set {0} of {1} - {2}".format(
                            _p + 1, total, label))

                self.run(batch["plan"], batch["sheet_rows"], batch["options"],
                         batch["grouping"], name_params, scoped, False)
            outer.Assimilate()
        except Exception as exc:
            try:
                outer.RollBack()
            except Exception:
                pass
            self.report["problems"].append(
                u"the sets were rolled back: {0}".format(_plainly(exc)))
            self._take_back(0, u"rolled back with every set")
        self.verify()
        self._say_cleaned()
        return self.report

    def _say_cleaned(self):
        """One line for what was taken off the new views and sheets."""
        parts = []
        if self.report.get("clouds_removed"):
            parts.append(u"{0} revision cloud(s)".format(self.report["clouds_removed"]))
        for what in sorted(self.report.get("cleaned", {})):
            parts.append(u"{0} {1}".format(self.report["cleaned"][what], what))
        if parts:
            self.report["debug"].append(u"cleaned: " + u", ".join(parts))
            self.trace(u"cleaned: " + u", ".join(parts))

    def _take_back(self, start, reason):
        """Everything reported created since `start` was undone by a rollback:
        say so to the window, and take it out of the report so nothing offers
        to open a sheet that is not there."""
        undone = self.created[start:]
        del self.created[start:]
        for row, entry in undone:
            try:
                self.report["sheets"].remove(entry)
            except ValueError:
                pass
            self._landed(row, None, reason)

    def run(self, plan, sheet_rows, options, grouping, name_params, progress=None,
            verify_after=True):
        """One TransactionGroup so Revit's undo still sees a single step, and a
        transaction per sheet so one refused sheet cannot roll back the rest."""
        self.trace(u"Revit {0}".format(_revit_version(self.doc)))
        self.trace(u"options: {0}".format(_settled(options)))
        self.trace(u"grouping: {0}".format(_settled(grouping)))
        self.trace(u"name parameters: {0}".format(u", ".join(name_params or [])))
        self.trace(u"{0} view job(s), {1} placement(s), {2} sheet row(s)".format(
            len(plan.get("jobs") or []), len(plan.get("placements") or []),
            len(sheet_rows or [])))
        for job in plan.get("jobs") or []:
            self.trace(u"  job {0} {1} '{2}' -> '{3}'".format(
                job.get("old_id"), job.get("action"), job.get("name"),
                job.get("new_name")))
        for entry in sheet_rows or []:
            self.trace(u"  sheet {0} -> {1} [{2}] {3}".format(
                entry.get("old_number"), entry.get("new_number"),
                entry.get("status"), entry.get("note") or u""))
        made_before = len(self.created)
        group = TransactionGroup(self.doc, "RevoBIM Sheet Manager - Duplicate")
        try:
            group.Start()
            primaries = [j["parent_old"] for j in plan["jobs"]
                         if j["action"] == shtm_plan.DEPENDENT and j["parent_old"]]
            shtm_model.borrow(self.doc, set(primaries))

            self.make_views(plan, options, progress)
            self.match_datums(plan, options)

            live = [r for r in sheet_rows if r.get("status") != "bad"]
            total = len(live) or 1
            for index, row in enumerate(live):
                before = len(self.report["problems"])
                new_id = self._one_sheet(row, plan, options, grouping, name_params)
                said = self.report["problems"][before:]
                if new_id is not None:
                    entry = {"id": eid_value(new_id),
                             "number": row["new_number"],
                             "name": row["new_name"]}
                    self.report["sheets"].append(entry)
                    self.created.append((row, entry))
                self._landed(row, new_id, said[0] if said else u"")
                if progress is not None:
                    progress((index + 1) * 100 // total, index + 1, total,
                             u"sheets")

            for row in sheet_rows:
                if row.get("status") == "bad":
                    self.report["problems"].append(
                        u"{0}: not duplicated - {1}".format(
                            row["old_number"], row.get("note") or u"blocked"))
                    self._landed(row, None, row.get("note") or u"blocked")

            self.trace(u"assimilating")
            group.Assimilate()
        except Exception as exc:
            try:
                group.RollBack()
            except Exception:
                pass
            self.report["problems"].append(
                u"the run was rolled back: {0}".format(_plainly(exc)))
            self.trace(u"ROLLED BACK: {0}".format(_plainly(exc)))
            self._take_back(made_before, u"rolled back with the rest of its set")
        if verify_after:
            self.verify()
        return self.report

    def verify(self):
        """Read the model back. How many sheets are actually on the new numbers
        is the answer, not how many calls Revit accepted."""
        existing = {}
        try:
            for sheet in FilteredElementCollector(self.doc).OfClass(ViewSheet):
                existing[element_sheet_number(sheet).strip().lower()] = sheet
        except Exception:
            pass
        confirmed = 0
        for record in self.report["sheets"]:
            sheet = existing.get(u"{0}".format(record["number"]).strip().lower())
            if sheet is None:
                self.report["problems"].append(
                    u"{0}: reported created but is not in the model".format(
                        record["number"]))
                continue
            confirmed += 1
            if element_name(sheet) != record["name"]:
                self.report["problems"].append(
                    u"{0}: the name read back as '{1}'".format(
                        record["number"], element_name(sheet)))
        self.report["confirmed"] = confirmed


def element_sheet_number(sheet):
    return shtm_model.element_sheet_number(sheet)
