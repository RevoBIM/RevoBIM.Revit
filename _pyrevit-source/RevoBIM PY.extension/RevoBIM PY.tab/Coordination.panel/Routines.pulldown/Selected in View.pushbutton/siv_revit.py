# -*- coding: utf-8 -*-
"""Selected in View - reading the active view and testing picked elements."""
import siv_clr  # noqa: F401  (assemblies first)

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    FilteredElementCollector, ElementId, Element, BuiltInCategory,
    BuiltInParameter, RevitLinkInstance, ImportInstance, PointCloudInstance,
    IndependentTag, SpatialElementTag,
)

import siv_core as core

# Categories that never go in the list. Links are governed by the Linked
# models button; the rest are not things anyone selects on purpose.
_EXCLUDED_NAMES = ('OST_RvtLinks', 'OST_Cameras', 'OST_IOSSketchGrid',
                   'OST_PointClouds', 'OST_RasterImages')


def eid_value(element_id):
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return element_id.IntegerValue
    except Exception:
        return 0


def excluded_keys():
    keys = set()
    for name in _EXCLUDED_NAMES:
        bic = getattr(BuiltInCategory, name, None)
        if bic is None:
            continue
        try:
            keys.add(int(bic))
        except Exception:
            try:
                keys.add(int(bic.value__))
            except Exception:
                pass
    return keys


def elem_name(e):
    if e is None:
        return u''
    for getter in (lambda x: Element.Name.GetValue(x),
                   lambda x: Element.Name.__get__(x),
                   lambda x: x.Name):
        try:
            v = getter(e)
            if v:
                return v
        except Exception:
            pass
    for pname in ('SYMBOL_NAME_PARAM', 'ALL_MODEL_TYPE_NAME'):
        try:
            bip = getattr(BuiltInParameter, pname)
            p = e.get_Parameter(bip)
            if p is not None and p.AsString():
                return p.AsString()
        except Exception:
            pass
    return u''


def top_category(e):
    """Line styles and other subcategories report their parent."""
    try:
        c = e.Category
    except Exception:
        return None
    if c is None:
        return None
    try:
        p = c.Parent
        if p is not None:
            return p
    except Exception:
        pass
    return c


def category_type(c):
    """'model' / 'annotation' / None (internal)."""
    try:
        s = str(c.CategoryType).lower()
    except Exception:
        return 'model'
    if 'annotation' in s:
        return 'annotation'
    if 'internal' in s or 'invalid' in s:
        return None
    return 'model'


def is_linked(e):
    if isinstance(e, RevitLinkInstance) or isinstance(e, PointCloudInstance):
        return True
    if isinstance(e, ImportInstance):
        try:
            return bool(e.IsLinked)
        except Exception:
            return False
    return False


def is_tag(e, cat=None):
    if isinstance(e, IndependentTag) or isinstance(e, SpatialElementTag):
        return True
    if cat is not None and category_type(cat) == 'annotation':
        try:
            return cat.Name.lower().endswith(u'tags')
        except Exception:
            return False
    return False


def is_pinned(e):
    try:
        return bool(e.Pinned)
    except Exception:
        return False


def type_family(doc, type_id, cache):
    """(family name, type name) for a tag's type, cached by type id."""
    k = eid_value(type_id)
    if k in cache:
        return cache[k]
    fam = u''
    name = u''
    try:
        t = doc.GetElement(type_id)
        if t is not None:
            try:
                fam = t.FamilyName or u''
            except Exception:
                fam = u''
            name = elem_name(t)
    except Exception:
        pass
    out = (fam or u'(no family)', name or u'(no type)')
    cache[k] = out
    return out


def tag_row_key(family):
    return core.tag_row_key(family)


def read_view(doc, view):
    """Records for core.build_list plus counts for the header buttons."""
    stats = {'links': 0, 'pinned': 0, 'skipped': 0, 'elements': 0, 'error': u''}
    records = []
    if doc is None or view is None:
        stats['error'] = u'No active view.'
        return records, stats
    excluded = excluded_keys()
    names = {}
    try:
        col = FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()
    except Exception as ex:
        stats['error'] = u'This view has nothing to pick ({0}).'.format(ex)
        return records, stats
    for e in col:
        try:
            stats['elements'] += 1
            if is_linked(e):
                stats['links'] += 1
                continue
            if is_pinned(e):
                stats['pinned'] += 1
            c = top_category(e)
            if c is None:
                continue
            k = eid_value(c.Id)
            if k in excluded:
                continue
            ctype = category_type(c)
            if ctype is None:
                continue
            tag = is_tag(e, c)
            tkey = None
            tname = None
            fam = None
            if tag:
                tid = e.GetTypeId()
                tkey = eid_value(tid)
                fam, tname = type_family(doc, tid, names)
            records.append((k, c.Name, ctype, tag, tkey, tname, fam))
        except Exception:
            stats['skipped'] += 1
    return records, stats


def element_info(e, doc=None, cache=None):
    """What the filter needs. 'row' is the list row the element belongs to:
    its category, or for a tag its tag family."""
    info = {'cat': None, 'row': None, 'name': u'', 'is_tag': False,
            'type': None, 'family': None, 'linked': False, 'pinned': False}
    if e is None:
        return info
    info['linked'] = is_linked(e)
    info['pinned'] = is_pinned(e)
    c = top_category(e)
    if c is not None:
        info['cat'] = eid_value(c.Id)
        info['row'] = info['cat']
        try:
            info['name'] = c.Name
        except Exception:
            info['name'] = u''
        info['is_tag'] = is_tag(e, c)
        if info['is_tag']:
            try:
                tid = e.GetTypeId()
                info['type'] = eid_value(tid)
                if doc is not None:
                    fam, _t = type_family(doc, tid, cache if cache is not None else {})
                    info['family'] = fam
                    info['row'] = tag_row_key(fam)
                    info['name'] = fam
            except Exception:
                info['type'] = None
    return info


def drop_label(info, reason):
    if reason == 'linked':
        return u'linked'
    if reason == 'pinned':
        return u'pinned'
    return info.get('name') or u'other'


def plan_selection(doc, ids, state):
    """Split picked ids into keep / drop. Returns (keep_ids, drop_labels, unknown)."""
    keep = []
    dropped = []
    unknown = False
    cache = {}
    for eid in ids:
        e = None
        try:
            e = doc.GetElement(eid)
        except Exception:
            e = None
        if e is None:
            keep.append(eid)
            continue
        info = element_info(e, doc, cache)
        if info['row'] is not None and not info['linked'] \
                and info['row'] not in state.known_cats:
            unknown = True
        ok, reason = core.decide(info, state)
        if ok:
            keep.append(eid)
        else:
            dropped.append(drop_label(info, reason))
    return keep, dropped, unknown


def set_selection(uidoc, keep):
    ids = List[ElementId]()
    for eid in keep:
        ids.Add(eid)
    uidoc.Selection.SetElementIds(ids)


def canvas_theme(uiapp):
    """'dark' / 'light' / None. UIThemeManager exists from Revit 2024 only."""
    try:
        import Autodesk.Revit.UI as ui_ns
        mgr = getattr(ui_ns, 'UIThemeManager', None)
        if mgr is not None:
            t = mgr.CurrentCanvasTheme
            if t is not None:  # UITheme.Dark is 0 - never test truthiness
                s = str(t).lower()
                if 'dark' in s:
                    return 'dark'
                if 'light' in s:
                    return 'light'
    except Exception:
        pass
    try:
        bg = uiapp.Application.BackgroundColor
        lum = 0.299 * bg.Red + 0.587 * bg.Green + 0.114 * bg.Blue
        return 'dark' if lum < 128 else 'light'
    except Exception:
        pass
    try:
        import Autodesk.Revit.UI as ui_ns2
        mgr2 = getattr(ui_ns2, 'UIThemeManager', None)
        if mgr2 is not None:
            t2 = mgr2.CurrentTheme
            if t2 is not None:
                return 'dark' if 'dark' in str(t2).lower() else 'light'
    except Exception:
        pass
    return None
