# -*- coding: utf-8 -*-
"""Clash Analysis - every write to the model.

Each function runs inside an ExternalEvent (see ca_ui.Runner). Everything a
run creates is wrapped in one TransactionGroup so a failure rolls it all
back, warnings are swallowed by a failures preprocessor, every commit's
status is checked, and every write is read back rather than trusted.
"""
import ca_clr  # noqa: F401  (assembly references first)

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    BoundingBoxXYZ, BuiltInCategory, Category, Element, ElementId,
    ElementTransformUtils, FailureProcessingResult, FailureSeverity,
    FilteredElementCollector, GroupType, IFailuresPreprocessor,
    ScheduleFilter, ScheduleFilterType, ScheduleSortGroupField, ScheduleSortOrder,
    TemporaryViewMode, Transaction, TransactionGroup, TransactionStatus, View3D,
    ViewFamily, ViewFamilyType, ViewSchedule, Workset, WorksharingUtils, XYZ,
)
from Autodesk.Revit.DB.Structure import StructuralType

import ca_core as core
import ca_revit as rv


class Swallow(IFailuresPreprocessor):
    """Deletes warnings so Revit does not stop the run with a dialog, and
    keeps the text of anything worse for the report."""

    def __init__(self):
        self.errors = []

    def PreprocessFailures(self, accessor):
        try:
            for msg in accessor.GetFailureMessages():
                try:
                    if msg.GetSeverity() == FailureSeverity.Warning:
                        accessor.DeleteWarning(msg)
                    else:
                        self.errors.append(core.to_text(msg.GetDescriptionText()))
                except Exception:
                    continue
        except Exception:
            pass
        return FailureProcessingResult.Continue


def _begin(doc, name):
    t = Transaction(doc, name)
    sw = Swallow()
    t.Start()
    try:
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(sw)
        t.SetFailureHandlingOptions(opts)
    except Exception:
        pass
    return t, sw


def _commit(t, sw, what):
    status = t.Commit()
    if status != TransactionStatus.Committed:
        detail = u'; '.join(sw.errors) or core.to_text(status)
        raise RuntimeError(u'{0} was not committed: {1}'.format(what, detail))


def _ids(items):
    out = List[ElementId]()
    for i in items:
        out.Add(i)
    return out


def borrow(doc, ids):
    """Check elements out before writing - an unborrowed element on a
    workshared model writes nothing and says nothing. Returns the ids the
    user could not borrow."""
    try:
        if not doc.IsWorkshared or not ids:
            return []
    except Exception:
        return []
    try:
        got = WorksharingUtils.CheckoutElements(doc, _ids(ids))
        held = set(rv.eid_value(i) for i in got)
    except Exception:
        return list(ids)
    return [i for i in ids if rv.eid_value(i) not in held]


def set_name(element, name):
    try:
        element.Name = name
    except Exception:
        pass
    if rv.elem_name(element) == name:
        return True
    try:
        Element.Name.SetValue(element, name)
    except Exception:
        pass
    return rv.elem_name(element) == name


def set_workset(element, workset_id):
    """True when the element ends up on the workset."""
    if workset_id is None:
        return True
    target = rv.workset_int(workset_id)
    try:
        if rv.workset_int(element.WorksetId) == target:
            return True
    except Exception:
        pass
    try:
        p = element.get_Parameter(rv.bip('ELEM_PARTITION_PARAM'))
        if p is not None and not p.IsReadOnly:
            p.Set(target)
    except Exception:
        pass
    try:
        return rv.workset_int(element.WorksetId) == target
    except Exception:
        return False


def set_comment(element, text):
    try:
        p = element.get_Parameter(rv.bip('ALL_MODEL_INSTANCE_COMMENTS'))
        if p is None or p.IsReadOnly:
            p = element.LookupParameter(u'Comments')
        if p is None:
            return False
        p.Set(text)
        return core.to_text(p.AsString()) == text
    except Exception:
        return False


def group_type_names(doc):
    out = []
    try:
        for gt in FilteredElementCollector(doc).OfClass(GroupType):
            out.append(rv.elem_name(gt))
    except Exception:
        pass
    return out


def _place_one(doc, point, symbol, level):
    last = None
    try:
        inst = doc.Create.NewFamilyInstance(point, symbol, level,
                                            StructuralType.NonStructural)
        if inst is not None:
            return inst, None
    except Exception as ex:
        last = ex
    try:
        inst = doc.Create.NewFamilyInstance(point, symbol,
                                            StructuralType.NonStructural)
        if inst is not None:
            return inst, None
    except Exception as ex:
        last = ex
    return None, core.to_text(last) or u'Revit placed nothing'


LEVEL_PARAMS = ('FAMILY_LEVEL_PARAM', 'INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM')


def level_of(inst):
    try:
        lid = inst.LevelId
        if lid is not None and lid != ElementId.InvalidElementId:
            return lid
    except Exception:
        pass
    for name in LEVEL_PARAMS:
        try:
            p = inst.get_Parameter(rv.bip(name))
            if p is not None and p.AsElementId() != ElementId.InvalidElementId:
                return p.AsElementId()
        except Exception:
            continue
    return None


def set_level(inst, level):
    """Put the instance on the level (Level, or Schedule Level for work
    plane based families). True when it reads back."""
    if level_of(inst) == level.Id:
        return True
    for name in LEVEL_PARAMS:
        try:
            p = inst.get_Parameter(rv.bip(name))
            if p is None or p.IsReadOnly:
                continue
            p.Set(level.Id)
            if p.AsElementId() == level.Id:
                return True
        except Exception:
            continue
    return False


def ensure_workset(doc, name, log=None):
    """(WorksetId, created). The model's workset of that name (any case), or
    a new user workset made with it. Needs a workshared model."""
    for existing, wid in rv.user_worksets(doc):
        if existing.lower() == core.to_text(name).lower():
            return wid, False
    if not doc.IsWorkshared:
        raise RuntimeError(u'worksets need a workshared model')
    t, sw = _begin(doc, u'Clash Analysis - create workset')
    try:
        ws = Workset.Create(doc, name)
        _commit(t, sw, u'Creating workset "{0}"'.format(name))
    except Exception:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        raise
    for existing, wid in rv.user_worksets(doc):
        if existing == core.to_text(name):
            if log:
                log(u'created workset "{0}"'.format(name))
            return wid, True
    raise RuntimeError(u'workset "{0}" was not found after creating it'.format(name))


def place_markers(doc, clashes, symbol, workset_id, test_name, comment_fmt,
                  stamp, log=None, level_id=None):
    """Place the marker family at every clash, centred on it, comment it,
    put it on the workset and group them per floor as
    CLASH-<stamp>_<level code>-<test name>.

    Level: level_id (the floor plan a current-view test ran in) when given,
    otherwise the closest level at or below each clash.
    A clash with this family already within DUPLICATE_MM of it is skipped."""
    result = {'placed': 0, 'failed': [], 'comments_ok': 0,
              'workset_refused': 0, 'group_name': u'', 'group_ok': False,
              'level_refused': 0, 'view_level': u'', 'skipped': 0, 'groups': []}
    already = core.PointIndex(rv.family_points(doc, rv.family_of(symbol)),
                              core.mm_to_ft(core.DUPLICATE_MM))
    level_rows = rv.levels(doc)
    level_pairs = [(i, elev) for i, (lvl, elev) in enumerate(level_rows)]
    fixed = None
    if level_id is not None:
        for i, (lvl, elev) in enumerate(level_rows):
            if lvl.Id == level_id:
                fixed = i
                result['view_level'] = rv.elem_name(lvl)
        if fixed is None and log:
            log(u'view level {0} is gone - using the level below each clash'.format(
                rv.eid_value(level_id)))
    tg = TransactionGroup(doc, u'Clash Analysis - place clash markers')
    tg.Start()
    try:
        t, sw = _begin(doc, u'Place clash markers')
        if not symbol.IsActive:
            symbol.Activate()
            doc.Regenerate()
        made = []
        for n, clash in enumerate(clashes):
            px, py, pz = clash['point']
            if already.near((px, py, pz)):
                result['skipped'] += 1
                continue
            already.add((px, py, pz))
            idx = core.marker_level(fixed, level_pairs, pz)
            level = level_rows[idx][0] if idx is not None else None
            if level is None:
                result['failed'].append((n, u'no level in the model'))
                continue
            inst, err = _place_one(doc, XYZ(px, py, pz), symbol, level)
            if inst is None:
                result['failed'].append((n, err))
                continue
            made.append((inst, clash, level))
        doc.Regenerate()
        for inst, clash, level in made:
            if not set_level(inst, level):
                result['level_refused'] += 1
        doc.Regenerate()
        for inst, clash, level in made:
            # family centroid onto the clash point, measured, not assumed
            try:
                bb = inst.get_BoundingBox(None)
                if bb is not None:
                    centre = core.box_centre((bb.Min.X, bb.Min.Y, bb.Min.Z,
                                              bb.Max.X, bb.Max.Y, bb.Max.Z))
                    d = core.move_to_centre(clash['point'], centre)
                    if abs(d[0]) + abs(d[1]) + abs(d[2]) > 1e-6:
                        ElementTransformUtils.MoveElement(
                            doc, inst.Id, XYZ(d[0], d[1], d[2]))
            except Exception as ex:
                if log:
                    log(u'centre marker: {0}'.format(ex))
            if set_comment(inst, core.comment_text(clash['a'], clash['b'],
                                                   comment_fmt)):
                result['comments_ok'] += 1
            if not set_workset(inst, workset_id):
                result['workset_refused'] += 1
        _commit(t, sw, u'Placing the clash markers')
        # one group per floor
        floors = {}
        for inst, clash, level in made:
            if doc.GetElement(inst.Id) is None:
                continue
            key = rv.eid_value(level.Id)
            if key not in floors:
                floors[key] = (level, [])
            floors[key][1].append(inst.Id)
        result['placed'] = sum(len(ids) for lvl, ids in floors.values())
        if floors:
            # codes from every level in the model, so a floor keeps its code
            codes = core.level_codes([rv.elem_name(lvl) for lvl, elev in level_rows])
            order = sorted(floors.values(), key=lambda r: rv.level_elevation(r[0]))
            t2, sw2 = _begin(doc, u'Group clash markers')
            all_ok = True
            for level, ids in order:
                lname = rv.elem_name(level)
                grp = doc.Create.NewGroup(_ids(ids))
                name = core.unique_name(
                    core.clash_group_name(stamp, test_name, codes.get(lname, u'')),
                    group_type_names(doc))
                ok = set_name(grp.GroupType, name)
                all_ok = all_ok and ok
                set_workset(grp, workset_id)
                result['groups'].append({'name': rv.elem_name(grp.GroupType),
                                         'level': lname, 'count': len(ids)})
            result['group_ok'] = all_ok
            result['group_name'] = result['groups'][0]['name']
            _commit(t2, sw2, u'Grouping the clash markers')
        tg.Assimilate()
    except Exception:
        try:
            tg.RollBack()
        except Exception:
            pass
        raise
    if log:
        log(u'placed {0} markers, {1} failed, {2} skipped (already placed), '
            u'groups: {3}'.format(result['placed'], len(result['failed']),
                                  result['skipped'],
                                  u', '.join(g['name'] for g in result['groups'])))
    return result


def delete_group(doc, record, log=None):
    """Delete a CLASH- group: every instance, its markers and the type."""
    members = rv.group_members(doc, record)
    everything = list(record['instances']) + members + [record['type_id']]
    refused = borrow(doc, everything)
    if refused:
        return {'deleted': False,
                'reason': u'{0} element(s) are owned by someone else'.format(
                    len(refused))}
    t, sw = _begin(doc, u'Delete clash group')
    try:
        if doc.GetElement(record['type_id']) is not None:
            doc.Delete(record['type_id'])
        left = [m for m in members if doc.GetElement(m) is not None]
        if left:
            doc.Delete(_ids(left))
        _commit(t, sw, u'Deleting the clash group')
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    remaining = [i for i in everything if doc.GetElement(i) is not None]
    if log:
        log(u'delete {0}: {1} element(s) remain'.format(record['name'],
                                                        len(remaining)))
    return {'deleted': not remaining,
            'reason': u'{0} element(s) were not deleted'.format(len(remaining))
            if remaining else u''}


def assign_workset(doc, record, workset_id, log=None):
    """Put a CLASH- group and every marker in it on one workset. Revit can
    refuse a workset change on a grouped member; those instances are
    ungrouped, changed and regrouped under the same name."""
    members = rv.group_members(doc, record)
    refused = borrow(doc, list(record['instances']) + members +
                     [record['type_id']])
    if refused:
        return {'ok': False, 'changed': 0,
                'reason': u'{0} element(s) are owned by someone else'.format(
                    len(refused))}
    name = record['name']
    t, sw = _begin(doc, u'Assign clash group workset')
    try:
        stubborn = []
        for gid in record['instances']:
            grp = doc.GetElement(gid)
            if grp is None:
                continue
            set_workset(grp, workset_id)
            bad = False
            for mid in grp.GetMemberIds():
                if not set_workset(doc.GetElement(mid), workset_id):
                    bad = True
            if bad:
                stubborn.append(gid)
        if stubborn:
            old_type = record['type_id']
            first_type = None
            for gid in stubborn:
                grp = doc.GetElement(gid)
                mids = list(grp.UngroupMembers())
                for mid in mids:
                    set_workset(doc.GetElement(mid), workset_id)
                new_grp = doc.Create.NewGroup(_ids(mids))
                if first_type is None:
                    first_type = new_grp.GroupType
                else:
                    extra = new_grp.GroupType.Id
                    new_grp.GroupType = first_type
                    if doc.GetElement(extra) is not None:
                        doc.Delete(extra)
                set_workset(new_grp, workset_id)
            still_used = False
            for gid in record['instances']:
                g = doc.GetElement(gid)
                if g is not None and rv.eid_value(g.GetTypeId()) == \
                        rv.eid_value(old_type):
                    still_used = True
            if first_type is not None:
                if not still_used and doc.GetElement(old_type) is not None:
                    doc.Delete(old_type)
                    set_name(first_type, name)
                else:
                    set_name(first_type, core.unique_name(
                        name, group_type_names(doc)))
        _commit(t, sw, u'Assigning the workset')
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    # prove it: read the worksets back from the model
    fresh = [r for r in rv.clash_groups(doc) if r['name'] == name]
    changed = 0
    wrong = 0
    target = rv.workset_int(workset_id)
    for rec in fresh:
        for mid in rv.group_members(doc, rec):
            el = doc.GetElement(mid)
            if el is not None and rv.workset_int(el.WorksetId) == target:
                changed += 1
            else:
                wrong += 1
    if log:
        log(u'workset {0}: {1} on target, {2} not'.format(name, changed, wrong))
    return {'ok': wrong == 0, 'changed': changed,
            'reason': u'{0} marker(s) kept their old workset'.format(wrong)
            if wrong else u''}


def show_clash(uidoc, point, half_ft, select_ids=None, section_box=False):
    """Zoom the active view to a clash, optionally boxing a 3D view round
    it, and select the host elements in it."""
    doc = uidoc.Document
    view = uidoc.ActiveView
    lo = XYZ(point[0] - half_ft, point[1] - half_ft, point[2] - half_ft)
    hi = XYZ(point[0] + half_ft, point[1] + half_ft, point[2] + half_ft)
    boxed = False
    if section_box and isinstance(view, View3D):
        t, sw = _begin(doc, u'Clash section box')
        try:
            box = BoundingBoxXYZ()
            box.Min = lo
            box.Max = hi
            view.SetSectionBox(box)
            try:
                view.IsSectionBoxActive = True
            except Exception:
                pass
            _commit(t, sw, u'Setting the section box')
            boxed = True
        except Exception:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
    if select_ids:
        try:
            uidoc.Selection.SetElementIds(_ids(select_ids))
        except Exception:
            pass
    try:
        for uiv in uidoc.GetOpenUIViews():
            if rv.eid_value(uiv.ViewId) == rv.eid_value(view.Id):
                uiv.ZoomAndCenterRectangle(lo, hi)
                break
    except Exception:
        pass
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass
    return boxed


def select(uidoc, ids):
    uidoc.Selection.SetElementIds(_ids(ids))


# ======================================================================
# Clash schedule
# ======================================================================

def _field(doc, defn, bip_names, fallback_name):
    """The schedulable field for the first built-in parameter offered, or
    the one called fallback_name."""
    fields = list(defn.GetSchedulableFields())
    for name in bip_names:
        member = rv.bip(name)
        if member is None:
            continue
        want = ElementId(member)
        for sf in fields:
            try:
                if sf.ParameterId == want:
                    return sf
            except Exception:
                continue
    for sf in fields:
        try:
            if core.to_text(sf.GetName(doc)) == fallback_name:
                return sf
        except Exception:
            continue
    return None


def _set_width(field, mm):
    ft = core.mm_to_ft(mm)
    ok = False
    for attr in ('GridColumnWidth', 'SheetColumnWidth'):
        try:
            setattr(field, attr, ft)
            ok = True
        except Exception:
            continue
    return ok


def make_clash_schedule(doc, symbol, log=None):
    """Create (or bring back into line) BIM_Clash Analysis Schedule:
    Generic Models, only the clash family, Level and Comments, sorted and
    headed by Level, Comments wide enough for the longest comment."""
    family = rv.family_of(symbol)
    result = {'id': None, 'created': False, 'family': family, 'rows': 0,
              'filter': u'', 'width_mm': 0.0, 'notes': []}
    comments = rv.family_comments(doc, family)
    result['rows'] = len(comments)
    t, sw = _begin(doc, u'Clash Analysis - clash schedule')
    try:
        sched = rv.find_schedule(doc, core.SCHEDULE_NAME)
        if sched is None:
            cat = Category.GetCategory(doc, BuiltInCategory.OST_GenericModel)
            sched = ViewSchedule.CreateSchedule(doc, cat.Id)
            sched.Name = core.SCHEDULE_NAME
            result['created'] = True
        defn = sched.Definition
        defn.ClearSortGroupFields()
        defn.ClearFilters()
        for fid in list(defn.GetFieldOrder()):
            defn.RemoveField(fid)
        defn.IsItemized = True

        if rv.is_work_plane_based(symbol):
            level_bips = ['INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM', 'FAMILY_LEVEL_PARAM',
                          'SCHEDULE_LEVEL_PARAM']
        else:
            level_bips = ['FAMILY_LEVEL_PARAM', 'INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM',
                          'SCHEDULE_LEVEL_PARAM']
        sf_level = _field(doc, defn, level_bips, u'Level')
        sf_comments = _field(doc, defn, ['ALL_MODEL_INSTANCE_COMMENTS'], u'Comments')
        sf_family = _field(doc, defn, ['ELEM_FAMILY_PARAM'], u'Family')
        if sf_level is None or sf_comments is None:
            raise Exception(u'Generic Models schedules offer no {0} field here'.format(
                u'Level' if sf_level is None else u'Comments'))

        f_level = defn.AddField(sf_level)
        f_level.ColumnHeading = u'Level'
        _set_width(f_level, core.SCHEDULE_LEVEL_MM)
        f_comments = defn.AddField(sf_comments)
        f_comments.ColumnHeading = u'Comments'
        result['width_mm'] = core.comment_column_mm(comments)
        if not _set_width(f_comments, result['width_mm']):
            result['notes'].append(u'Revit would not take the Comments column width.')

        filtered = False
        if sf_family is not None:
            f_family = defn.AddField(sf_family)
            f_family.IsHidden = True
            try:
                defn.AddFilter(ScheduleFilter(f_family.FieldId,
                                              ScheduleFilterType.Equal, family))
                filtered = True
                result['filter'] = u'Family equals "{0}"'.format(family)
            except Exception as ex:
                if log:
                    log(u'family filter: {0}'.format(ex))
        if not filtered:
            sf_ft = _field(doc, defn, ['ELEM_FAMILY_AND_TYPE_PARAM'], u'Family and Type')
            if sf_ft is None:
                raise Exception(u'the schedule cannot be filtered by family')
            f_ft = defn.AddField(sf_ft)
            f_ft.IsHidden = True
            defn.AddFilter(ScheduleFilter(f_ft.FieldId, ScheduleFilterType.BeginsWith,
                                          family + u':'))
            result['filter'] = u'Family and Type begins with "{0}:"'.format(family)

        by_level = ScheduleSortGroupField(f_level.FieldId, ScheduleSortOrder.Ascending)
        by_level.ShowHeader = True
        defn.AddSortGroupField(by_level)
        defn.AddSortGroupField(ScheduleSortGroupField(f_comments.FieldId,
                                                      ScheduleSortOrder.Ascending))
        result['id'] = sched.Id
        _commit(t, sw, u'Creating the clash schedule')
    except Exception:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        raise
    if log:
        log(u'clash schedule {0}: {1}, {2} rows, comments {3:.0f} mm'.format(
            u'created' if result['created'] else u'updated', result['filter'],
            result['rows'], result['width_mm']))
    return result


def open_view(uidoc, view_id):
    try:
        view = uidoc.Document.GetElement(view_id)
        if view is not None:
            uidoc.RequestViewChange(view)
            return True
    except Exception:
        pass
    return False


# ======================================================================
# Isolate Clash Sphere / Reset view
# ======================================================================

def activate_view(uidoc, view):
    """Make the view active now if Revit allows it here, else ask Revit to
    switch at its next idle. True when it is active now."""
    try:
        if rv.eid_value(uidoc.ActiveView.Id) == rv.eid_value(view.Id):
            return True
        uidoc.ActiveView = view
        return rv.eid_value(uidoc.ActiveView.Id) == rv.eid_value(view.Id)
    except Exception:
        try:
            uidoc.RequestViewChange(view)
        except Exception:
            pass
        return False


def zoom_fit(uidoc, view_id):
    try:
        for uiv in uidoc.GetOpenUIViews():
            if rv.eid_value(uiv.ViewId) == rv.eid_value(view_id):
                uiv.ZoomToFit()
                return True
    except Exception:
        pass
    return False


def _enable_tvp(view):
    """Temporary View Properties on, so every visibility change below is
    undone by Reset view and never touches the view (or its template)."""
    try:
        if view.IsTemporaryViewPropertiesModeEnabled():
            return True
    except Exception:
        pass
    for template in (ElementId.InvalidElementId, view.Id):
        try:
            view.EnableTemporaryViewPropertiesMode(template)
            if view.IsTemporaryViewPropertiesModeEnabled():
                return True
        except Exception:
            continue
    return False


def isolate_in_view(uidoc, view, member_ids, cat_ids, log=None):
    """Temporary View Properties, the clash family's category (and its
    sub-categories, and Detail Items for a nested plan symbol) shown, the
    clash spheres temporarily isolated, then zoomed to fit."""
    doc = uidoc.Document
    result = {'view_id': view.Id, 'view': core.to_text(view.Name), 'tvp': False,
              'shown': 0, 'isolated': 0, 'zoomed': False}
    show = list(cat_ids)
    try:
        from_doc = [c for c in doc.Settings.Categories
                    if any(rv.eid_value(c.Id) == rv.eid_value(k) for k in cat_ids)]
        for cat in from_doc:
            for sub in cat.SubCategories:
                show.append(sub.Id)
        detail = Category.GetCategory(doc, BuiltInCategory.OST_DetailComponents)
        if detail is not None:
            show.append(detail.Id)
    except Exception as ex:
        if log:
            log(u'isolate categories: {0}'.format(ex))
    t, sw = _begin(doc, u'Clash Analysis - isolate clash spheres')
    try:
        result['tvp'] = _enable_tvp(view)
        for cid in show:
            try:
                if view.CanCategoryBeHidden(cid) and view.GetCategoryHidden(cid):
                    view.SetCategoryHidden(cid, False)
                    result['shown'] += 1
            except Exception:
                continue
        ids = [m for m in member_ids if doc.GetElement(m) is not None]
        if ids:
            view.IsolateElementsTemporary(_ids(ids))
        result['isolated'] = len(ids)
        _commit(t, sw, u'Isolating the clash spheres')
    except Exception:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        raise
    result['zoomed'] = zoom_fit(uidoc, view.Id)
    if log:
        log(u'isolate in "{0}": tvp {1}, {2} categories shown, {3} isolated, zoom {4}'.format(
            result['view'], result['tvp'], result['shown'], result['isolated'],
            result['zoomed']))
    return result


def reset_view(doc, view, log=None):
    """End Temporary Hide/Isolate and Temporary View Properties on a view.
    True when anything was reset."""
    did = False
    t, sw = _begin(doc, u'Clash Analysis - reset view')
    try:
        try:
            if view.IsTemporaryHideIsolateActive():
                view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)
                did = True
        except Exception as ex:
            if log:
                log(u'reset isolate: {0}'.format(ex))
        try:
            if view.IsTemporaryViewPropertiesModeEnabled():
                view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryViewProperties)
                did = True
        except Exception as ex:
            if log:
                log(u'reset view properties: {0}'.format(ex))
        _commit(t, sw, u'Resetting the view')
    except Exception:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        raise
    return did


# ======================================================================
# View in 3D
# ======================================================================

def _new_3d(doc, name, log=None):
    """A new isometric 3D view, for a model with none."""
    vft = None
    for t in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        try:
            if t.ViewFamily == ViewFamily.ThreeDimensional:
                vft = t
                break
        except Exception:
            continue
    if vft is None:
        raise RuntimeError(u'the model has no 3D view type')
    t, sw = _begin(doc, u'Clash Analysis - new 3D view')
    try:
        view = View3D.CreateIsometric(doc, vft.Id)
        set_name(view, core.unique_name(name, [rv.elem_name(v) for v in
                                               FilteredElementCollector(doc).OfClass(View3D)]))
        _commit(t, sw, u'Creating the 3D view')
    except Exception:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        raise
    if log:
        log(u'made 3D view "{0}"'.format(rv.elem_name(view)))
    return view


def view_in_3d(uidoc, view_id, member_ids, log=None):
    """Open the 3D view (a new one when view_id is None), box its section
    round the clash spheres and zoom to fit."""
    doc = uidoc.Document
    view = doc.GetElement(view_id) if view_id is not None else _new_3d(doc, core.NEW_3D_NAME, log)
    if view is None or not isinstance(view, View3D):
        raise RuntimeError(u'that 3D view is no longer in the model')
    box = core.section_box_around(rv.boxes_of(doc, member_ids),
                                  core.mm_to_ft(core.SECTION_PAD_MM))
    if box is None:
        raise RuntimeError(u'the clash spheres have no extent to box')
    t, sw = _begin(doc, u'Clash Analysis - section box')
    try:
        bb = BoundingBoxXYZ()
        bb.Min = XYZ(box[0], box[1], box[2])
        bb.Max = XYZ(box[3], box[4], box[5])
        view.SetSectionBox(bb)
        try:
            view.IsSectionBoxActive = True
        except Exception:
            pass
        _commit(t, sw, u'Setting the section box')
    except Exception:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        raise
    active = activate_view(uidoc, view)
    zoomed = zoom_fit(uidoc, view.Id)
    return {'view_id': view.Id, 'view': rv.elem_name(view), 'active': active,
            'zoomed': zoomed, 'count': len(member_ids)}
