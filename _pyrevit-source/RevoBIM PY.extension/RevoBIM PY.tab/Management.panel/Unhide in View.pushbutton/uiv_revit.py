# -*- coding: utf-8 -*-
"""Unhide in View - everything that reads or writes the Revit model.

Runs only inside an ExternalEvent (or a modal window's command), never on
its own from a window handler. Revit 2024-2027 from one copy:
  - ElementId values through eid_value(), never .IntegerValue
  - ElementIds kept as the objects Revit handed over, never rebuilt from ints
  - enums compared by str(), BuiltInParameter members looked up at call time
"""
import uiv_clr  # noqa: F401  - assembly references first, always

import time
import traceback

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    FilteredElementCollector, ElementId, View, Transaction, TransactionGroup,
    ElementMulticategoryFilter, ElementOwnerViewFilter, ElementClassFilter,
    WorksharingUtils, IFailuresPreprocessor, FailureProcessingResult,
    BuiltInParameter,
)

import uiv_core as core


# =====================================================================
# Small helpers
# =====================================================================

def eid_value(element_id):
    """ElementId -> number on every release (.Value from 2024, .IntegerValue
    gone in 2026)."""
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return getattr(element_id, 'IntegerValue')
    except Exception:
        return 0


def valid_id(element_id):
    return element_id is not None and eid_value(element_id) > 0


def safe_name(elem):
    """Element.Name raises AttributeError on some classes in IronPython."""
    if elem is None:
        return u''
    try:
        return core.to_text(elem.Name)
    except Exception:
        pass
    try:
        from Autodesk.Revit.DB import Element as _E
        return core.to_text(_E.Name.GetValue(elem))
    except Exception:
        return u''


def same_doc(a, b):
    try:
        return a is not None and b is not None and a.Equals(b)
    except Exception:
        return False


def doc_alive(doc):
    try:
        return doc is not None and doc.IsValidObject
    except Exception:
        return False


def bip(name):
    """BuiltInParameter member looked up at call time - members move."""
    return getattr(BuiltInParameter, name, None)


# =====================================================================
# Views
# =====================================================================

def read_views(doc, log):
    out = []
    skipped = 0
    for v in FilteredElementCollector(doc).OfClass(View):
        try:
            vt = str(v.ViewType)
            if not core.view_is_listed(vt, v.IsTemplate):
                skipped += 1
                continue
            sheet_no = None
            if vt == 'DrawingSheet':
                sheet_no = getattr(v, 'SheetNumber', None)
            tid = v.ViewTemplateId
            tkey = None
            tname = u''
            if valid_id(tid):
                t = doc.GetElement(tid)
                if t is not None:
                    tkey = eid_value(tid)
                    tname = safe_name(t)
            name = core.view_display_name(safe_name(v), sheet_no)
            out.append({
                'key': eid_value(v.Id),
                'id': v.Id,
                'view': v,
                'name': name,
                'type': core.view_type_label(vt),
                'template_key': tkey,
                'template_id': tid if tkey else None,
                'template_name': tname,
            })
        except Exception:
            log.add(u'read_views: skipped a view - ' + traceback.format_exc())
    log.add(u'Views listed: {0} ({1} schedules, templates and browsers left out)'.format(
        len(out), skipped))
    return out


def active_view_key(uidoc):
    try:
        v = uidoc.ActiveView
        if v is None:
            return None
        return eid_value(v.Id)
    except Exception:
        return None


# =====================================================================
# Candidates for the scan
# =====================================================================

def candidate_category_ids(doc):
    """Model and annotation categories. Internal and analytical categories
    hold nothing a person hides."""
    ids = List[ElementId]()
    for cat in doc.Settings.Categories:
        try:
            if str(cat.CategoryType) in ('Model', 'Annotation'):
                ids.Add(cat.Id)
        except Exception:
            pass
    return ids


def model_candidates(doc, cat_ids):
    """Every element that is not view-specific, not a type and not a view.
    Filtered on the .NET side; the per-element test happens in the scan."""
    col = FilteredElementCollector(doc).WhereElementIsNotElementType()
    col = col.WherePasses(ElementMulticategoryFilter(cat_ids))
    col = col.WherePasses(ElementOwnerViewFilter(ElementId.InvalidElementId))
    col = col.WherePasses(ElementClassFilter(View, True))
    return list(col.ToElements())


def owned_candidates(doc, view_id, cat_ids):
    """View-specific elements (annotation, detail items, viewports on a sheet)
    can only be hidden in the view that owns them."""
    col = FilteredElementCollector(doc).OwnedByView(view_id).WhereElementIsNotElementType()
    col = col.WherePasses(ElementMulticategoryFilter(cat_ids))
    return list(col.ToElements())


def make_scanner(doc, views, cat_ids, log):
    t0 = time.time()
    model = model_candidates(doc, cat_ids)
    log.add(u'Scan candidates: {0} model elements read in {1:.2f}s'.format(
        len(model), time.time() - t0))
    by_key = {}
    for v in views:
        by_key[v['key']] = v['view']
    cache = {'key': None, 'view': None}

    def view_for(vk):
        if cache['key'] != vk:
            cache['key'] = vk
            cache['view'] = by_key.get(vk)
        return cache['view']

    def segments_for(vk):
        view = view_for(vk)
        if view is None:
            return []
        return [model, owned_candidates(doc, view.Id, cat_ids)]

    def is_hidden(item, vk):
        return item.IsHidden(view_for(vk))

    def id_of(item):
        return item.Id

    return core.Scanner([v['key'] for v in views], segments_for, is_hidden,
                        id_of, time.time)


# =====================================================================
# Rows for the hidden elements table
# =====================================================================

def family_type_text(doc, elem):
    fam = u''
    typ = u''
    try:
        tid = elem.GetTypeId()
        if valid_id(tid):
            t = doc.GetElement(tid)
            if t is not None:
                typ = safe_name(t)
                try:
                    fam = core.to_text(t.FamilyName)
                except Exception:
                    fam = u''
    except Exception:
        pass
    if not typ:
        typ = safe_name(elem)
    if fam and typ and fam != typ:
        return fam + u' : ' + typ
    return typ or fam


def level_text(doc, elem):
    try:
        lid = elem.LevelId
        if valid_id(lid):
            return safe_name(doc.GetElement(lid))
    except Exception:
        pass
    try:
        rl = elem.ReferenceLevel        # pipes, ducts, cable trays
        if rl is not None:
            return safe_name(rl)
    except Exception:
        pass
    try:
        if valid_id(elem.OwnerViewId):
            return u'(view-specific)'
    except Exception:
        pass
    return u''


def element_row(doc, eid, view, cat_hidden_cache):
    """One row for the left table. The note says when the element's category
    is hidden in the view too - unhiding the element alone will not show it."""
    key = eid_value(eid)
    row = {'key': key, 'id_txt': core.to_text(key), 'category': u'',
           'ftype': u'', 'level': u'', 'note': u'', 'warn': u'0', 'bad': u'0'}
    elem = doc.GetElement(eid)
    if elem is None:
        row['category'] = u'(deleted)'
        row['note'] = u'No longer in the model'
        row['bad'] = u'1'
        return row
    cat = None
    try:
        cat = elem.Category
    except Exception:
        cat = None
    if cat is not None:
        row['category'] = core.to_text(cat.Name)
    row['ftype'] = family_type_text(doc, elem)
    row['level'] = level_text(doc, elem)
    if cat is not None:
        ck = eid_value(cat.Id)
        hidden = cat_hidden_cache.get(ck)
        if hidden is None:
            hidden = False
            try:
                if view.CanCategoryBeHidden(cat.Id):
                    hidden = bool(view.GetCategoryHidden(cat.Id))
            except Exception:
                hidden = False
            cat_hidden_cache[ck] = hidden
        if hidden:
            row['note'] = u'Category hidden here too'
            row['warn'] = u'1'
    return row


# =====================================================================
# Categories hidden in a view
# =====================================================================

def all_categories(doc):
    """[(key, Category, display name, model|annotation)], parents before
    their subcategories."""
    out = []
    for cat in doc.Settings.Categories:
        try:
            ct = str(cat.CategoryType)
            if ct not in ('Model', 'Annotation'):
                continue
            pname = core.to_text(cat.Name)
            out.append((eid_value(cat.Id), cat, pname, ct, None))
            try:
                for sub in cat.SubCategories:
                    out.append((eid_value(sub.Id), sub,
                                pname + u' : ' + core.to_text(sub.Name), ct,
                                eid_value(cat.Id)))
            except Exception:
                pass
        except Exception:
            pass
    return out


def template_control(doc, view):
    """(template, name, controls model V/G, controls annotation V/G)."""
    tid = view.ViewTemplateId
    if not valid_id(tid):
        return None, u'', False, False
    t = doc.GetElement(tid)
    if t is None:
        return None, u'', False, False
    try:
        free = set(eid_value(i) for i in t.GetNonControlledTemplateParameterIds())
    except Exception:
        free = set()

    def controls(name):
        p = bip(name)
        if p is None:
            return True     # cannot tell: treat as controlled and say so
        try:
            return eid_value(ElementId(p)) not in free
        except Exception:
            return True
    return t, safe_name(t), controls('VIS_GRAPHICS_MODEL'), controls('VIS_GRAPHICS_ANNOTATION')


def read_category_state(doc, view, cats, log):
    """{cat_key: (True, template name or None)} for categories hidden in the
    view. A subcategory is left out when its parent is hidden - unhiding the
    parent is the action that matters."""
    t, tname, cm, ca = template_control(doc, view)
    state = {}
    hidden_parents = set()
    for key, cat, name, ct, parent in cats:
        controlled = cm if ct == 'Model' else ca
        src = t if (controlled and t is not None) else view
        try:
            if not view.CanCategoryBeHidden(cat.Id):
                continue
            hidden = bool(src.GetCategoryHidden(cat.Id))
        except Exception:
            continue
        if not hidden:
            continue
        if parent is None:
            hidden_parents.add(key)
        elif parent in hidden_parents:
            continue
        state[key] = (True, tname if (controlled and t is not None) else None)
    return state


# =====================================================================
# Writing
# =====================================================================

class _Quiet(IFailuresPreprocessor):
    """Deletes warnings; keeps the text of anything worse so the row can
    say what Revit said."""

    def __init__(self, log):
        self.log = log
        self.errors = []

    def PreprocessFailures(self, accessor):
        try:
            for f in accessor.GetFailureMessages():
                sev = str(f.GetSeverity())
                text = u''
                try:
                    text = core.to_text(f.GetDescriptionText())
                except Exception:
                    pass
                if sev == 'Warning':
                    accessor.DeleteWarning(f)
                    self.log.add(u'  warning removed: ' + text)
                else:
                    self.errors.append(text)
                    self.log.add(u'  Revit ' + sev + u': ' + text)
        except Exception:
            self.log.add(u'  failure preprocessor: ' + traceback.format_exc())
        return FailureProcessingResult.Continue


def _transaction(doc, name, log):
    t = Transaction(doc, name)
    quiet = _Quiet(log)
    try:
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(quiet)
        opts.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(opts)
    except Exception:
        pass
    return t, quiet


def _committed(status):
    return str(status) == 'Committed'


# DialogBoxShowing is hooked ONCE and switched on only while Unhide runs:
# unsubscribing an IronPython bound method is not reliable.
_DIALOGS = {'hooked': False, 'on': False, 'log': None}


def _on_dialog(sender, args):
    if not _DIALOGS['on']:
        return
    try:
        did = core.to_text(getattr(args, 'DialogId', u''))
        args.OverrideResult(1)
        if _DIALOGS['log'] is not None:
            _DIALOGS['log'].add(u'  dialog suppressed: ' + did)
    except Exception:
        pass


def hook_dialogs(uiapp, log):
    _DIALOGS['log'] = log
    if _DIALOGS['hooked']:
        return
    try:
        uiapp.DialogBoxShowing += _on_dialog
        _DIALOGS['hooked'] = True
    except Exception:
        log.add(u'DialogBoxShowing could not be hooked: ' + traceback.format_exc())


def borrow(doc, ids, log):
    """Check out the views (and templates) the run writes to. Returns the
    keys refused, each with the reason, so a view held by someone else is
    named rather than silently left alone."""
    refused = {}
    if not ids:
        return refused
    try:
        workshared = doc.IsWorkshared
    except Exception:
        workshared = False
    if not workshared:
        return refused
    held = set()
    try:
        got = WorksharingUtils.CheckoutElements(doc, List[ElementId](ids))
        held = set(eid_value(i) for i in got)
    except Exception:
        log.add(u'CheckoutElements failed: ' + traceback.format_exc())
    for i in ids:
        k = eid_value(i)
        if k in held:
            continue
        owner = u''
        try:
            owner = core.to_text(WorksharingUtils.GetWorksharingTooltipInfo(doc, i).Owner)
        except Exception:
            pass
        refused[k] = (u'Held by ' + owner) if owner else u'Could not be borrowed'
        log.add(u'  not borrowed {0}: {1}'.format(k, refused[k]))
    return refused


def _unhide_batch(doc, view, ids, log):
    """All at once; on a refusal, one at a time so one bad element does not
    lose the rest. Returns {key: message} of elements refused."""
    refused = {}
    t, quiet = _transaction(doc, u'RevoBIM Unhide elements', log)
    t.Start()
    try:
        view.UnhideElements(List[ElementId](ids))
        status = t.Commit()
        if _committed(status):
            return refused
        log.add(u'  batch did not commit ({0}) - one at a time'.format(status))
    except Exception as ex:
        log.add(u'  batch refused: {0} - one at a time'.format(core.to_text(ex)))
        try:
            t.RollBack()
        except Exception:
            pass
    for i in ids:
        k = eid_value(i)
        t1, q1 = _transaction(doc, u'RevoBIM Unhide element', log)
        t1.Start()
        try:
            view.UnhideElements(List[ElementId]([i]))
            status = t1.Commit()
            if not _committed(status):
                refused[k] = u'Refused by Revit' + (
                    u': ' + q1.errors[0] if q1.errors else u'')
        except Exception as ex:
            try:
                t1.RollBack()
            except Exception:
                pass
            refused[k] = u'Refused: ' + core.to_text(ex)
    return refused


def run_unhide(doc, plan, view_of, owner_of, eid_of, cat_id_of, uiapp, log):
    """Carry out a plan from core.build_plan.

    view_of(view_key) -> View; owner_of(key, is_template) -> View;
    eid_of(view_key, elem_key) -> ElementId; cat_id_of(cat_key) -> ElementId.

    Everything sits in one TransactionGroup (one undo step), one
    transaction per view so a refusal stays local, and nothing is counted
    until it reads back after the group has closed.
    """
    result = {'elements_ok': 0, 'element_views': 0, 'categories_ok': 0,
              'category_owners': 0, 'ok_elements': [], 'ok_categories': [],
              'refused': [], 'skipped': list(plan.get('skipped') or [])}

    owner_ids = []
    seen = set()
    for vk, _ in plan['elements']:
        v = view_of(vk)
        if v is not None and vk not in seen:
            seen.add(vk)
            owner_ids.append(v.Id)
    for okey, is_t, _ in plan['categories']:
        o = owner_of(okey, is_t)
        if o is not None and eid_value(o.Id) not in seen:
            seen.add(eid_value(o.Id))
            owner_ids.append(o.Id)
    not_held = borrow(doc, owner_ids, log)

    hook_dialogs(uiapp, log)
    _DIALOGS['on'] = True
    tg = TransactionGroup(doc, u'RevoBIM Unhide in View')
    tg.Start()
    try:
        for vk, eks in plan['elements']:
            view = view_of(vk)
            if view is None:
                for ek in eks:
                    result['refused'].append(('element', vk, ek, u'View not found'))
                continue
            if vk in not_held:
                for ek in eks:
                    result['refused'].append(('element', vk, ek, not_held[vk]))
                continue
            ids = []
            for ek in eks:
                i = eid_of(vk, ek)
                if i is None or doc.GetElement(i) is None:
                    result['refused'].append(('element', vk, ek, u'No longer in the model'))
                    continue
                ids.append(i)
            if not ids:
                continue
            log.add(u'Unhide {0} in view {1}'.format(len(ids), vk))
            refused = _unhide_batch(doc, view, ids, log)
            for k, msg in refused.items():
                result['refused'].append(('element', vk, k, msg))

        for okey, is_t, cks in plan['categories']:
            owner = owner_of(okey, is_t)
            label = u'template' if is_t else u'view'
            if owner is None:
                for ck in cks:
                    result['refused'].append(('category', okey, ck, label + u' not found'))
                continue
            if okey in not_held:
                for ck in cks:
                    result['refused'].append(('category', okey, ck, not_held[okey]))
                continue
            log.add(u'Unhide {0} categories on {1} {2}'.format(len(cks), label, okey))
            t, quiet = _transaction(doc, u'RevoBIM Unhide categories', log)
            t.Start()
            failed = {}
            try:
                for ck in cks:
                    try:
                        owner.SetCategoryHidden(cat_id_of(ck), False)
                    except Exception as ex:
                        failed[ck] = u'Refused: ' + core.to_text(ex)
                status = t.Commit()
                if not _committed(status):
                    for ck in cks:
                        failed.setdefault(ck, u'Refused by Revit' + (
                            u': ' + quiet.errors[0] if quiet.errors else u''))
            except Exception as ex:
                try:
                    t.RollBack()
                except Exception:
                    pass
                for ck in cks:
                    failed.setdefault(ck, u'Refused: ' + core.to_text(ex))
            for ck, msg in failed.items():
                result['refused'].append(('category', okey, ck, msg))
        tg.Assimilate()
    except Exception:
        log.add(u'Unhide run failed, rolled back: ' + traceback.format_exc())
        try:
            tg.RollBack()
        except Exception:
            pass
        result['refused'].append(('run', None, None,
                                  u'The run failed and was rolled back - see the debug log'))
    finally:
        _DIALOGS['on'] = False

    # ---- read back, after the group has closed ----------------------------
    refused_keys = set((r[0], r[1], r[2]) for r in result['refused'])
    views_ok = set()
    for vk, eks in plan['elements']:
        view = view_of(vk)
        for ek in eks:
            if ('element', vk, ek) in refused_keys:
                continue
            i = eid_of(vk, ek)
            elem = doc.GetElement(i) if i is not None else None
            try:
                still = elem is None or bool(elem.IsHidden(view))
            except Exception:
                still = True
            if still:
                result['refused'].append(('element', vk, ek, u'Still hidden after the run'))
                continue
            result['ok_elements'].append((vk, ek))
            views_ok.add(vk)
    owners_ok = set()
    for okey, is_t, cks in plan['categories']:
        owner = owner_of(okey, is_t)
        for ck in cks:
            if ('category', okey, ck) in refused_keys:
                continue
            try:
                still = bool(owner.GetCategoryHidden(cat_id_of(ck)))
            except Exception:
                still = True
            if still:
                result['refused'].append(('category', okey, ck, u'Still hidden after the run'))
                continue
            result['ok_categories'].append((okey, is_t, ck))
            owners_ok.add((okey, is_t))
    result['elements_ok'] = len(result['ok_elements'])
    result['element_views'] = len(views_ok)
    result['categories_ok'] = len(result['ok_categories'])
    result['category_owners'] = len(owners_ok)
    log.add(u'Read back: {0} elements in {1} views, {2} categories on {3} owners, '
            u'{4} refused'.format(result['elements_ok'], result['element_views'],
                                  result['categories_ok'], result['category_owners'],
                                  len(result['refused'])))
    return result


# =====================================================================
# Showing things in Revit
# =====================================================================

def activate_view(uidoc, view, log):
    try:
        if uidoc.ActiveView is not None and eid_value(uidoc.ActiveView.Id) == eid_value(view.Id):
            return True
    except Exception:
        pass
    try:
        uidoc.ActiveView = view
        return True
    except Exception:
        log.add(u'ActiveView refused, requesting change: ' + traceback.format_exc())
    try:
        uidoc.RequestViewChange(view)
        return True
    except Exception:
        log.add(u'RequestViewChange refused: ' + traceback.format_exc())
        return False


def select_ids(uidoc, ids, log):
    try:
        uidoc.Selection.SetElementIds(List[ElementId](ids))
        return True
    except Exception:
        log.add(u'Selection refused: ' + traceback.format_exc())
        return False
