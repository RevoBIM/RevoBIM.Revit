# -*- coding: utf-8 -*-
u"""Project Browser Pro - everything that touches the Revit document.

Every function here runs inside Revit's API context: from the ExternalEvent
runner (dockable panes and the floating window) or from the command itself.
Nothing here touches WPF.

The first read is one pass over everything: views, sheets, schedules,
panel schedules and family types, each with the folders Revit's own
browser organisation puts it in and the parameter values any custom
organisation asks for. After that a change reads only what it touched
(read_changes): a modified view alone, an added sheet's tab, the
placements when a viewport comes or goes.
"""
import time

import pbp_clr  # noqa: F401  (references first, always)
from System.Collections.Generic import List
from Autodesk.Revit.DB import (FilteredElementCollector, View, ViewSheet,
                               ViewSchedule, ElementId, Element, Transaction,
                               FamilySymbol, FamilyInstanceFilter,
                               ScheduleSheetInstance, ElementType, Family,
                               ViewFamilyType)
from Autodesk.Revit.UI import RevitCommandId

# Names that not every Revit from 2021 to 2027 may have go in their own
# guarded import: a grouped import is all or nothing, so one missing name
# would take the whole module - and the tool - down with it.
try:
    from Autodesk.Revit.DB import BrowserOrganization
except Exception:
    BrowserOrganization = None

try:
    from Autodesk.Revit.DB import ViewSheetSet
except Exception:
    ViewSheetSet = None

try:
    from Autodesk.Revit.DB import Viewport
except Exception:
    Viewport = None

try:
    from Autodesk.Revit.DB.Electrical import PanelScheduleView
except Exception:
    PanelScheduleView = None
try:
    from Autodesk.Revit.DB.Electrical import PanelScheduleSheetInstance
except Exception:
    PanelScheduleSheetInstance = None

import pbp_log
import pbp_handoff
import pbp_catgroups
from pbp_compat import to_text, eid_value, natural_key
from pbp_tree import Leaf

EXCLUDED_VIEW_TYPES = set([
    u'ProjectBrowser', u'SystemBrowser', u'Internal', u'Undefined',
    u'DrawingSheet', u'Schedule', u'PanelSchedule', u'ColumnSchedule',
    u'Report', u'CostReport', u'LoadsReport', u'PresureLossReport',
    u'SystemsAnalysisReport',
])

VIEW_KIND = {
    u'FloorPlan': u'plan', u'CeilingPlan': u'ceiling', u'AreaPlan': u'area',
    u'EngineeringPlan': u'structural', u'ThreeD': u'threed',
    u'Section': u'section', u'Elevation': u'elevation', u'Detail': u'detail',
    u'DraftingView': u'drafting', u'Legend': u'legend',
    u'Walkthrough': u'camera', u'Rendering': u'camera',
}

VIEW_LABEL = {
    u'FloorPlan': u'Floor Plans', u'CeilingPlan': u'Ceiling Plans',
    u'AreaPlan': u'Area Plans', u'EngineeringPlan': u'Structural Plans',
    u'ThreeD': u'3D Views', u'Section': u'Sections', u'Elevation': u'Elevations',
    u'Detail': u'Detail Views', u'DraftingView': u'Drafting Views',
    u'Legend': u'Legends', u'Walkthrough': u'Walkthroughs',
    u'Rendering': u'Renderings',
}
# Revit names these folders after the view family type as well.
TYPED_LABELS = set([u'Section', u'Elevation', u'Detail', u'AreaPlan'])

PSEUDO = [u'Name', u'View Type', u'View Template', u'Placed on Sheet',
          u'On Sheet', u'Dependency', u'Category', u'Family', u'Type',
          u'Family and Type', u'Main Group']
PSEUDO_FOR = {
    u'views': [u'Name', u'View Type', u'View Template', u'Placed on Sheet',
               u'On Sheet', u'Dependency'],
    u'sheets': [u'Name'],
    u'schedules': [u'Name', u'Placed on Sheet', u'On Sheet'],
    u'panels': [u'Name', u'Placed on Sheet', u'On Sheet'],
    u'legends': [u'Name', u'View Template', u'Placed on Sheet', u'On Sheet'],
    u'families': [u'Main Group', u'Category', u'Family', u'Type', u'Family and Type'],
}
# Views that are not the Views tab's: legends and drafting views share a
# tab of their own (Legends and Drafting Views).
LEGEND_TYPES = (u'Legend', u'DraftingView')
# Views a zoom to fit makes sense for (not schedules or panel schedules).
ZOOM_TABS = (u'views', u'legends', u'sheets')
CATALOGUE_SAMPLE = 40

# The tabs a read fills, in the order it reads them; and the other things a
# change can make worth reading again: what is placed on which sheet, the
# sheet sets, and (ALL) everything.
READ_TABS = (u'views', u'legends', u'sheets', u'schedules', u'panels', u'families')
PLACED = u'placed'
SETS = u'sets'
ALL = u'all'
SECTIONS = READ_TABS + (PLACED, SETS, ALL)
# Tabs whose items can sit on a sheet.
PLACEABLE = (u'views', u'legends', u'schedules', u'panels')
PLACED_NAMES = (u'Placed on Sheet', u'On Sheet')
# What change_kind calls changes that are not one of the tabs' own items.
TEMPLATE = u'template'
FAMILY = u'family'
VIEW_TYPE = u'view type'
# A leaf's fields that decide its row: two leaves alike in these draw alike.
LEAF_FIELDS = (u'key', u'tab', u'kind', u'text', u'sort_text', u'revit_sort', u'number',
               u'values', u'folders', u'uid', u'parent', u'template', u'primary')


class Snapshot(object):
    u"""One read of the document, handed to every browser listening."""

    def __init__(self):
        self.title = u''
        self.key = u''
        self.tabs = dict((t, []) for t in (u'views', u'legends', u'sheets', u'panels',
                                           u'schedules', u'families'))
        self.catalogues = dict((t, []) for t in self.tabs)
        self.revit_names = {}
        self.revit_desc = {}
        self.orgs = {}
        self.open_ids = set()
        self.active_id = 0
        # every id a change to which means something -> the section a
        # change to it reads again (a leaf's tab, 'placed', 'sets')
        self.known_ids = {}
        self.ms = 0
        self.note = u''
        self.errors = []
        self.revit_version = u''
        # {set name: set of sheet UniqueIds}, from Print > Sheet sets
        self.sheet_sets = {}
        # Revit's own browser organisation as parameter names, per tab:
        # what the manual organisation is filled with when switched to
        self.revit_levels = {}
        self.revit_sort = {}
        # what is placed where (element id -> [sheet numbers], sheet id ->
        # [element ids]) and the viewports and instances that place them:
        # kept, so a read after a change need not look again
        self.placed = {}
        self.by_sheet = {}
        self.placement_ids = set()
        self.set_ids = set()
        # view templates met: id -> name, id -> ElementId
        self.templates = {}
        self.template_ids = {}
        # section -> ms, from the read that made this
        self.timings = {}

    def copy(self):
        u"""A new snapshot sharing this one's leaves: a read after a change
        replaces the parts that changed and keeps the rest."""
        snap = Snapshot()
        snap.title, snap.key, snap.orgs = self.title, self.key, self.orgs
        snap.revit_version = self.revit_version
        snap.tabs = dict((tab, list(leaves)) for tab, leaves in self.tabs.items())
        for name in (u'catalogues', u'revit_names', u'revit_desc', u'revit_levels',
                     u'revit_sort', u'sheet_sets', u'placed', u'by_sheet', u'templates',
                     u'template_ids'):
            setattr(snap, name, dict(getattr(self, name)))
        snap.placement_ids = set(self.placement_ids)
        snap.set_ids = set(self.set_ids)
        snap.open_ids = set(self.open_ids)
        snap.active_id = self.active_id
        return snap

    def counts(self):
        return dict((t, len(v)) for t, v in self.tabs.items())


# ============================================================
# small readers
# ============================================================

def element_name(element):
    if element is None:
        return u''
    try:
        return to_text(element.Name)
    except Exception:
        pass
    try:
        return to_text(Element.Name.GetValue(element))
    except Exception:
        return u''


def param_text(doc, param):
    if param is None:
        return u''
    try:
        if not param.HasValue:
            return u''
    except Exception:
        pass
    try:
        storage = to_text(param.StorageType)
    except Exception:
        storage = u''
    try:
        if storage == u'String':
            return to_text(param.AsString())
        shown = param.AsValueString()
        if shown:
            return to_text(shown)
        if storage == u'Integer':
            return to_text(param.AsInteger())
        if storage == u'Double':
            return u'{0:.3f}'.format(float(param.AsDouble()))
        if storage == u'ElementId':
            return element_name(doc.GetElement(param.AsElementId()))
    except Exception:
        return u''
    return u''


def lookup(doc, element, name):
    u"""A named parameter on the element, falling back to its type."""
    try:
        param = element.LookupParameter(name)
        if param is not None:
            return param_text(doc, param)
    except Exception:
        pass
    try:
        type_id = element.GetTypeId()
        if type_id is not None and eid_value(type_id) > 0:
            element_type = doc.GetElement(type_id)
            if element_type is not None:
                param = element_type.LookupParameter(name)
                if param is not None:
                    return param_text(doc, param)
    except Exception:
        pass
    return u''


def view_type_text(view):
    try:
        return to_text(view.ViewType)
    except Exception:
        return u''


def view_label(doc, view):
    vt = view_type_text(view)
    label = VIEW_LABEL.get(vt, vt or u'Views')
    if vt in TYPED_LABELS:
        try:
            type_name = element_name(doc.GetElement(view.GetTypeId()))
            if type_name:
                label = u'{0} ({1})'.format(label, type_name)
        except Exception:
            pass
    return label


def primary_id(view):
    try:
        pid = view.GetPrimaryViewId()
        if pid is not None and eid_value(pid) > 0:
            return eid_value(pid)
    except Exception:
        pass
    return 0


def placed_on_sheets(doc, errors, by_sheet=None, ids=None):
    u"""element id -> [sheet numbers] for views, schedules and panel schedules.
    by_sheet, when given, is filled the other way: sheet id -> [element ids].
    ids, when given, gets the viewports and sheet instances that place them."""
    placed = {}
    sheet_of_number = {}

    def add(view_id, number):
        placed.setdefault(view_id, [])
        if number not in placed[view_id]:
            placed[view_id].append(number)
        if by_sheet is not None and number in sheet_of_number:
            listed = by_sheet.setdefault(sheet_of_number[number], [])
            if view_id not in listed:
                listed.append(view_id)
    sheet_numbers = {}
    try:
        for sheet in FilteredElementCollector(doc).OfClass(ViewSheet):
            try:
                number = to_text(sheet.SheetNumber)
            except Exception:
                number = u''
            sheet_numbers[eid_value(sheet.Id)] = number
            sheet_of_number[number] = eid_value(sheet.Id)
            try:
                for vid in sheet.GetAllPlacedViews():
                    add(eid_value(vid), number)
            except Exception:
                pass
            if ids is not None:
                try:
                    for vpid in sheet.GetAllViewports():
                        ids.add(eid_value(vpid))
                except Exception:
                    pass
    except Exception:
        errors.append(pbp_log.exc(u'placed_on_sheets/views'))
    try:
        for inst in FilteredElementCollector(doc).OfClass(ScheduleSheetInstance):
            try:
                if inst.IsTitleblockRevisionSchedule:
                    continue
            except Exception:
                pass
            number = sheet_numbers.get(eid_value(inst.OwnerViewId))
            if number is not None:
                add(eid_value(inst.ScheduleId), number)
                if ids is not None:
                    ids.add(eid_value(inst.Id))
    except Exception:
        errors.append(pbp_log.exc(u'placed_on_sheets/schedules'))
    if PanelScheduleSheetInstance is not None:
        try:
            for inst in FilteredElementCollector(doc).OfClass(PanelScheduleSheetInstance):
                schedule_id = getattr(inst, u'ScheduleId', None)
                number = sheet_numbers.get(eid_value(inst.OwnerViewId))
                if schedule_id is not None and number is not None:
                    add(eid_value(schedule_id), number)
                    if ids is not None:
                        ids.add(eid_value(inst.Id))
        except Exception:
            errors.append(pbp_log.exc(u'placed_on_sheets/panels'))
    return placed


def pseudo_value(doc, element, name, ctx):
    if name == u'Name':
        return element_name(element)
    if name == u'View Type':
        return view_label(doc, element)
    if name == u'View Template':
        try:
            tid = element.ViewTemplateId
            if tid is not None and eid_value(tid) > 0:
                return element_name(doc.GetElement(tid))
        except Exception:
            pass
        return u'None'
    if name in PLACED_NAMES:
        return placed_value(name, ctx[u'placed'].get(eid_value(element.Id), []))
    if name == u'Dependency':
        if primary_id(element):
            return u'Dependent'
        try:
            if element.GetDependentViewIds().Count:
                return u'Primary'
        except Exception:
            pass
        return u'Independent'
    if name == u'Category':
        try:
            return to_text(element.Category.Name)
        except Exception:
            return u''
    if name == u'Family':
        try:
            return to_text(element.FamilyName)
        except Exception:
            return u''
    if name == u'Type':
        return element_name(element)
    if name == u'Family and Type':
        return u'{0}: {1}'.format(pseudo_value(doc, element, u'Family', ctx),
                                  element_name(element))
    if name == u'Main Group':
        return main_group_of(element, ctx)
    return None


def main_group_of(element, ctx):
    u"""Tags / Annotations / Architecture / Structure / Electrical /
    Mechanical & Plumbing / Other for an element's category - by its
    BuiltInCategory name, which is the same in every Revit language.
    Cached per category."""
    try:
        category = element.Category
    except Exception:
        category = None
    if category is None:
        return pbp_catgroups.OTHER
    try:
        cid = eid_value(category.Id)
    except Exception:
        cid = 0
    cache = ctx.setdefault(u'groups', {})
    if cid not in cache:
        cache[cid] = pbp_catgroups.main_group(ost_of(category, cid), to_text(category.Name),
                                              _category_kind(category))
    return cache[cid]


def _category_kind(category):
    try:
        return to_text(category.CategoryType)
    except Exception:
        return u''


def ost_of(category, cid):
    u"""'OST_CableTray' for a built-in category, u'' otherwise.
    Category.BuiltInCategory from Revit 2023; before that the id is the
    enum's value."""
    if cid >= 0:
        return u''
    text = u''
    try:
        text = to_text(getattr(category, u'BuiltInCategory'))
    except Exception:
        text = u''
    if not text.startswith(u'OST_'):
        try:
            import clr
            from System import Enum
            from Autodesk.Revit.DB import BuiltInCategory
            text = to_text(Enum.ToObject(clr.GetClrType(BuiltInCategory), cid))
        except Exception:
            text = u''
    return text if text.startswith(u'OST_') else u''


def value_of(doc, element, name, ctx):
    value = pseudo_value(doc, element, name, ctx) if name in PSEUDO else None
    if value is None:
        value = lookup(doc, element, name)
    return value


def needed_names(org):
    names = []
    if org.get(u'source') == u'custom':
        names.extend(org.get(u'levels', []))
    if org.get(u'source') != u'revit' and org.get(u'sort'):
        names.append(org[u'sort'])
    out = []
    for name in names:
        if name not in out:
            out.append(name)
    return out


def catalogue(elements, tab):
    names = set(PSEUDO_FOR.get(tab, []))
    for element in elements[:CATALOGUE_SAMPLE]:
        try:
            for param in element.Parameters:
                try:
                    names.add(to_text(param.Definition.Name))
                except Exception:
                    pass
        except Exception:
            pass
    names.discard(u'')
    return sorted(names, key=natural_key)


# ============================================================
# Revit's own browser organisation
# ============================================================

def revit_org(doc, tab):
    getter = {
        u'views': u'GetCurrentBrowserOrganizationForViews',
        u'sheets': u'GetCurrentBrowserOrganizationForSheets',
        u'schedules': u'GetCurrentBrowserOrganizationForSchedules',
    }.get(tab)
    if not getter or BrowserOrganization is None:
        return None
    method = getattr(BrowserOrganization, getter, None)
    if method is None:
        return None
    try:
        return method(doc)
    except Exception:
        return None


def folders_of(org, element):
    if org is None:
        return []
    try:
        return [to_text(item.Name) for item in org.GetFolderItems(element.Id)]
    except Exception:
        return []


def revit_sorting(org, sample):
    u"""(parameter name, descending) Revit's organisation sorts by."""
    if org is None:
        return u'', False
    desc = False
    try:
        desc = u'Descending' in to_text(org.SortingOrder)
    except Exception:
        pass
    try:
        pid = eid_value(org.SortingParameterId)
    except Exception:
        return u'', desc
    if not pid or sample is None:
        return u'', desc
    try:
        for param in sample.Parameters:
            if eid_value(param.Id) == pid:
                return to_text(param.Definition.Name), desc
    except Exception:
        pass
    return u'', desc


# ============================================================
# the read
# ============================================================

def _collect(doc, cls):
    try:
        return list(FilteredElementCollector(doc).OfClass(cls))
    except Exception:
        return []


def doc_key(doc):
    u"""What a snapshot is of: the model's path, or its title before it is saved."""
    try:
        return to_text(doc.PathName) or to_text(doc.Title)
    except Exception:
        return to_text(doc.Title)


def _timed(snap, name, fn, *args):
    started = time.time()
    try:
        return fn(*args)
    finally:
        snap.timings[name] = int((time.time() - started) * 1000)


def timing_text(snap):
    u"""'views 120, sheets 14, ...' in read order, for the log."""
    order = (PLACED,) + READ_TABS + (SETS,)
    return u', '.join(u'{0} {1}'.format(name, snap.timings[name])
                      for name in order if name in snap.timings)


def read_snapshot(uiapp, load_orgs):
    u"""Read everything the browser shows. load_orgs(project_title) -> orgs.

    The first read, a document switch, a reload or the Refresh button.
    After an ordinary change read_changes reads only what changed."""
    started = time.time()
    snap = Snapshot()
    try:
        snap.revit_version = to_text(uiapp.Application.VersionNumber)
    except Exception:
        pass
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        snap.note = u'No project is open.'
        return snap
    doc = uidoc.Document
    snap.title = to_text(doc.Title)
    snap.key = doc_key(doc) or snap.title
    snap.orgs = load_orgs(snap.title)
    ctx = {}
    _timed(snap, PLACED, read_placed, doc, snap)
    ctx[u'placed'] = snap.placed
    for tab in READ_TABS:
        _timed(snap, tab, READERS[tab], doc, snap, ctx)
    _timed(snap, SETS, _read_sheet_sets, doc, snap)
    attach_placed(snap, snap.by_sheet)
    keep_templates(snap, ctx)
    open_state(snap, uidoc)
    finish(snap)
    snap.ms = int((time.time() - started) * 1000)
    pbp_log.log(u'read {0}: {1} in {2} ms ({3})'.format(snap.title, snap.counts(), snap.ms,
                                                       timing_text(snap)))
    return snap


def open_state(snap, uidoc):
    u"""Which views are open in Revit, and which is active."""
    snap.open_ids = set()
    try:
        for ui_view in uidoc.GetOpenUIViews():
            snap.open_ids.add(eid_value(ui_view.ViewId))
    except Exception:
        pass
    try:
        snap.active_id = eid_value(uidoc.ActiveView.Id)
    except Exception:
        pass


def finish(snap):
    u"""Mark the open and active views, and note every id a change to which
    means something - with the section a change to it reads again."""
    known = {}
    for tab, leaves in snap.tabs.items():
        for leaf in leaves:
            value = eid_value(leaf.eid)
            known[value] = tab
            leaf.is_open = value in snap.open_ids
            leaf.is_active = value == snap.active_id
    for value in snap.placement_ids:
        known[value] = PLACED
    for value in snap.set_ids:
        known[value] = SETS
    snap.known_ids = known


def keep_templates(snap, ctx):
    u"""The view templates the read met, added to those met before, so
    renaming one is noticed."""
    names = ctx.get(u'templates', {})
    ids = ctx.get(u'template_ids', {})
    for value, name in names.items():
        if value in ids:
            snap.templates[value] = name
            snap.template_ids[value] = ids[value]


# ============================================================
# reading only what changed
# ============================================================

def leaf_signature(leaf):
    u"""Everything about a leaf the browser draws or sorts by - two leaves
    with the same signature draw the same row."""
    return tuple(getattr(leaf, name, None) for name in LEAF_FIELDS)


def read_changes(uiapp, previous, sections, ids, load_orgs):
    u"""The read after an ordinary change: only what changed.

    sections: tabs (and 'placed', 'sets') to read again whole - something
    was added or deleted there. ids: elements the browser shows that were
    modified - each is read again alone, and its row only redrawn if what
    it shows changed (a view's scale or detail level changes nothing here).

    Returns (snapshot, tabs that changed). The snapshot shares every leaf
    that did not change with `previous`. tabs is None when it had to read
    everything after all (another document, or 'all' asked for).

    Open views are left as `previous` had them: the ViewActivated counter
    brings those, and redraws only the rows whose dot moved.
    """
    sections = set(sections or ())
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None or previous is None or ALL in sections:
        return read_snapshot(uiapp, load_orgs), None
    doc = uidoc.Document
    if doc_key(doc) != previous.key:
        return read_snapshot(uiapp, load_orgs), None
    started = time.time()
    snap = previous.copy()
    # template names are looked up afresh: one may just have been renamed
    ctx = {u'placed': snap.placed}

    # 1. each modified element as it is now - and whether it reaches further
    by_value = {}
    for tab in READ_TABS:
        for leaf in snap.tabs.get(tab, []):
            by_value[eid_value(leaf.eid)] = leaf
    looked = 0
    patches = []
    sec_for = {}
    for value in sorted(ids or ()):
        old = by_value.get(value)
        if old is None:
            if value in previous.templates and _template_renamed(doc, previous, value):
                # a template's name is on every view using it
                sections.update((u'views', u'legends'))
            continue
        if old.tab in sections:
            continue
        looked += 1
        try:
            element = doc.GetElement(old.eid)
        except Exception:
            element = None
        if element is None:
            sections.add(old.tab)
            continue
        sec = sec_for.get(old.tab)
        if sec is None:
            sec = sec_for[old.tab] = Section(doc, snap, old.tab)
        try:
            new = LEAF_BUILDERS[old.tab](doc, element, sec, ctx)
        except Exception:
            snap.errors.append(pbp_log.exc(u'read changed element'))
            sections.add(old.tab)
            continue
        if old.tab == u'sheets' and new.number != old.number:
            # 'Placed on Sheet' values name sheets by number
            sections.add(PLACED)
        patches.append((old.tab, old, new))

    # 2. whole sections
    if PLACED in sections:
        _timed(snap, PLACED, read_placed, doc, snap)
        ctx[u'placed'] = snap.placed
    changed = set()
    for tab in READ_TABS:
        if tab in sections:
            _timed(snap, tab, READERS[tab], doc, snap, ctx)
            if [leaf_signature(l) for l in snap.tabs[tab]] == \
                    [leaf_signature(l) for l in previous.tabs.get(tab, [])]:
                # read again and found as it was: keep the leaves everyone has
                snap.tabs[tab] = list(previous.tabs.get(tab, []))
            else:
                changed.add(tab)
    if SETS in sections:
        snap.sheet_sets = {}
        snap.set_ids = set()
        _timed(snap, SETS, _read_sheet_sets, doc, snap)
        if snap.sheet_sets != previous.sheet_sets:
            changed.add(u'sheets')

    # 3. single elements: swapped in, then kept only if they differ
    patched_tabs = set()
    for tab, old, new in patches:
        if tab in sections:
            continue
        leaves = snap.tabs[tab]
        try:
            leaves[leaves.index(old)] = new
        except ValueError:
            continue
        patched_tabs.add(tab)
    for tab in patched_tabs & set((u'views', u'legends')):
        link_dependents(snap.tabs[tab], snap.orgs.get(tab, {}))
    for tab, old, new in patches:
        if tab in sections or tab not in patched_tabs:
            continue
        if leaf_signature(old) == leaf_signature(new):
            leaves = snap.tabs[tab]
            try:
                leaves[leaves.index(new)] = old
            except ValueError:
                pass
        else:
            changed.add(tab)

    # 4. what sits on which sheet
    if PLACED in sections:
        kept = [tab for tab in PLACEABLE if tab not in sections]
        changed |= apply_placed(snap, kept)
        if snap.by_sheet != previous.by_sheet:
            changed |= set(PLACEABLE) | set([u'sheets'])
    attach_placed(snap, snap.by_sheet)
    keep_templates(snap, ctx)
    finish(snap)
    snap.ms = int((time.time() - started) * 1000)
    pbp_log.log(u'read changes {0}: whole [{1}], {2} element(s) alone, changed [{3}] in {4} ms ({5})'.format(
        snap.title, u', '.join(sorted(sections)), looked, u', '.join(sorted(changed)), snap.ms,
        timing_text(snap) if sections else u'-'))
    return snap, changed


def _template_renamed(doc, previous, value):
    try:
        element = doc.GetElement(previous.template_ids[value])
    except Exception:
        return True
    return element is None or element_name(element) != previous.templates.get(value, u'')


# ============================================================
# what changed: told apart in the DocumentChanged event
# ============================================================

def change_kind(element):
    u"""What a change to this element touches, by its class alone - cheap
    enough to ask of every element a change reports.

    'views' / 'legends' / 'sheets' / 'schedules' / 'panels' / 'families':
    one of the browser's own items. 'template': a view template. 'placed':
    a viewport or schedule on a sheet. 'sets': a sheet set. 'all': Revit's
    browser organisation. None: anything else - pipework, tags, walls."""
    if element is None:
        return None
    try:
        if isinstance(element, ViewSheet):
            return u'sheets'
        if isinstance(element, ViewSchedule):
            return u'schedules'
        if PanelScheduleView is not None and isinstance(element, PanelScheduleView):
            return u'panels'
        if isinstance(element, View):
            if element.IsTemplate:
                return TEMPLATE
            return u'legends' if view_type_text(element) in LEGEND_TYPES else u'views'
        if Viewport is not None and isinstance(element, Viewport):
            return PLACED
        if isinstance(element, ScheduleSheetInstance):
            return PLACED
        if PanelScheduleSheetInstance is not None and isinstance(element, PanelScheduleSheetInstance):
            return PLACED
        if ViewSheetSet is not None and isinstance(element, ViewSheetSet):
            return SETS
        if BrowserOrganization is not None and isinstance(element, BrowserOrganization):
            return ALL
        if isinstance(element, ElementType):
            if is_family_type(element):
                return u'families'
            if isinstance(element, ViewFamilyType):
                # its name is in the Views tab's folder labels
                return VIEW_TYPE
            return None
        if isinstance(element, Family):
            return FAMILY
    except Exception:
        return None
    return None


# ============================================================
# the sections
# ============================================================

class Section(object):
    u"""What reading one tab needs besides its elements: the organisation's
    parameter names, Revit's own organisation, and what that sorts by.

    A whole read works the sort out from a sample and records it; reading
    one element alone takes what the last whole read recorded."""

    def __init__(self, doc, snap, tab):
        self.tab = tab
        self.org = snap.orgs.get(tab, {})
        # the values the tab's organisation groups by, and the ones its
        # favourites' own organisation does (Favourites, 1.7.0)
        self.names = needed_names(self.org)
        for name in needed_names(snap.orgs.get(u'fav.' + tab, {})):
            if name not in self.names:
                self.names.append(name)
        self.rorg = revit_org(doc, tab)
        self.sort_name = snap.revit_sort.get(tab, u'')

    def describe(self, snap, samples, extra=()):
        try:
            snap.revit_names[self.tab] = element_name(self.rorg) if self.rorg is not None else u''
        except Exception:
            snap.revit_names[self.tab] = u''
        self.sort_name, desc = revit_sorting(self.rorg, samples[0] if samples else None)
        snap.revit_desc[self.tab] = desc
        snap.revit_sort[self.tab] = self.sort_name
        snap.revit_levels[self.tab] = revit_levels(self.rorg, samples, extra)


def _values(doc, element, names, ctx):
    out = {}
    for name in names:
        try:
            out[name] = value_of(doc, element, name, ctx)
        except Exception:
            out[name] = u''
    return out


def is_tab_view(view, tab):
    u"""A view the Views tab shows (tab='views'), or the Legends tab."""
    try:
        if view.IsTemplate:
            return False
        if isinstance(view, (ViewSheet, ViewSchedule)):
            return False
        if PanelScheduleView is not None and isinstance(view, PanelScheduleView):
            return False
        kind = view_type_text(view)
        if kind in EXCLUDED_VIEW_TYPES:
            return False
        return (kind in LEGEND_TYPES) == (tab == u'legends')
    except Exception:
        return False


def view_leaf(doc, view, sec, ctx):
    u"""One view as a leaf. Revit's own browser organisation does not group
    legends, so on the Legends tab they have no Revit folders."""
    name = element_name(view)
    revit_sort = lookup(doc, view, sec.sort_name) if sec.sort_name else name
    # Revit's view folders end in the view type (Floor Plans, Sections...)
    folders = folders_of(sec.rorg, view) + [view_label(doc, view)] if sec.tab == u'views' else []
    leaf = Leaf(u'e:{0}'.format(eid_value(view.Id)), sec.tab,
                VIEW_KIND.get(view_type_text(view), u'view'), name,
                sort_text=name, values=_values(doc, view, sec.names, ctx),
                folders=folders, eid=view.Id,
                uid=view.UniqueId, revit_sort=revit_sort)
    leaf.template = template_name(doc, view, ctx)
    leaf.primary = primary_id(view)
    return leaf


def link_dependents(leaves, org):
    u"""Dependent views sit straight after their primary, in its folder.
    Safe to run again over leaves it has already linked."""
    by_value = dict((eid_value(leaf.eid), leaf) for leaf in leaves)
    for leaf in leaves:
        primary = getattr(leaf, u'primary', 0)
        parent = by_value.get(primary) if primary else None
        if parent is None or parent is leaf:
            continue
        leaf.kind = u'dependent'
        leaf.parent = parent.key
        leaf.folders = list(parent.folders)
        leaf.sort_text = parent.sort_text + u'\x01' + leaf.text
        leaf.revit_sort = parent.revit_sort + u'\x01' + leaf.text
        if org.get(u'source') == u'custom':
            for name in org.get(u'levels', []):
                leaf.values[name] = parent.values.get(name, u'')


def _read_views(doc, snap, ctx, tab=u'views'):
    u"""The Views tab, or (tab='legends') the Legends tab: the same read,
    split on the view type."""
    views = [view for view in _collect(doc, View) if is_tab_view(view, tab)]
    sec = Section(doc, snap, tab)
    sec.describe(snap, views, (u'View Type',) if tab == u'views' else ())
    leaves = []
    for view in views:
        try:
            leaves.append(view_leaf(doc, view, sec, ctx))
        except Exception:
            snap.errors.append(pbp_log.exc(u'read view'))
    link_dependents(leaves, sec.org)
    snap.tabs[tab] = leaves
    snap.catalogues[tab] = catalogue(views, tab)


def _read_legends(doc, snap, ctx):
    _read_views(doc, snap, ctx, u'legends')


def template_name(doc, view, ctx):
    u"""The name of the view template a view uses, or u''. Cached per
    template: a model has thousands of views and a handful of templates."""
    try:
        tid = view.ViewTemplateId
        value = eid_value(tid)
    except Exception:
        return u''
    if not value or value < 0:
        return u''
    cache = ctx.setdefault(u'templates', {})
    if value not in cache:
        try:
            cache[value] = element_name(doc.GetElement(tid))
        except Exception:
            cache[value] = u''
        ctx.setdefault(u'template_ids', {})[value] = tid
    return cache[value]


def read_placed(doc, snap):
    u"""What is placed on which sheet - both ways - and the viewports and
    schedule instances that place them, so deleting one is noticed."""
    by_sheet = {}
    ids = set()
    snap.placed = placed_on_sheets(doc, snap.errors, by_sheet, ids)
    snap.by_sheet = by_sheet
    snap.placement_ids = ids


def placed_value(name, numbers):
    u"""'Placed on Sheet' or 'On Sheet' for a view on these sheet numbers."""
    if name == u'On Sheet':
        return u'Yes' if numbers else u'No'
    return u', '.join(sorted(numbers, key=natural_key)) or u'Not on sheet'


def apply_placed(snap, tabs):
    u"""Bring the 'Placed on Sheet' and 'On Sheet' values of leaves read
    before the placements changed up to date. The tabs whose values moved."""
    changed = set()
    for tab in tabs:
        for leaf in snap.tabs.get(tab, []):
            numbers = None
            for name in PLACED_NAMES:
                if name not in leaf.values:
                    continue
                if numbers is None:
                    numbers = snap.placed.get(eid_value(leaf.eid), [])
                value = placed_value(name, numbers)
                if leaf.values[name] != value:
                    leaf.values[name] = value
                    changed.add(tab)
    for tab in changed & set((u'views', u'legends')):
        # a dependent shows its primary's values
        link_dependents(snap.tabs[tab], snap.orgs.get(tab, {}))
    return changed


def attach_placed(snap, by_sheet):
    u"""Give each sheet leaf the leaves of what is placed on it, so a
    sheet opens to show its views as it does in Revit's browser."""
    by_id = {}
    for tab in PLACEABLE:
        for leaf in snap.tabs.get(tab, []):
            by_id[eid_value(leaf.eid)] = leaf
    for leaf in by_id.values():
        leaf.sheets = []
    for sheet in snap.tabs.get(u'sheets', []):
        sheet.placed = [by_id[vid] for vid in by_sheet.get(eid_value(sheet.eid), [])
                        if vid in by_id]
        for placed in sheet.placed:
            placed.sheets.append(sheet)


def revit_levels(rorg, samples, extra=()):
    u"""Revit's browser organisation as parameter names, top first: the
    folder items of the sample with the most folders, each item's parameter
    named from that sample's own parameters."""
    if rorg is None:
        return list(extra)
    best, best_items = None, []
    for element in samples[:CATALOGUE_SAMPLE]:
        try:
            items = list(rorg.GetFolderItems(element.Id))
        except Exception:
            continue
        if len(items) > len(best_items):
            best, best_items = element, items
    names = []
    for item in best_items:
        name = u''
        try:
            pid = eid_value(item.ElementId)
            for param in best.Parameters:
                if eid_value(param.Id) == pid:
                    name = to_text(param.Definition.Name)
                    break
        except Exception:
            name = u''
        if name and name not in names:
            names.append(name)
    for name in extra:
        if name not in names:
            names.append(name)
    return names


def _read_sheet_sets(doc, snap):
    u"""Print > Sheet sets, for the Sheets tab's filter. A set can hold
    views too; only its sheets count here."""
    if ViewSheetSet is None:
        return
    try:
        sets = list(FilteredElementCollector(doc).OfClass(ViewSheetSet))
    except Exception:
        snap.errors.append(pbp_log.exc(u'read sheet sets'))
        return
    for sheet_set in sets:
        try:
            snap.set_ids.add(eid_value(sheet_set.Id))
            name = element_name(sheet_set)
            uids = set()
            for view in sheet_set.Views:
                if isinstance(view, ViewSheet):
                    uids.add(to_text(view.UniqueId))
            if name:
                snap.sheet_sets[name] = uids
        except Exception:
            snap.errors.append(pbp_log.exc(u'read sheet set'))


def is_sheet(sheet):
    try:
        return not (sheet.IsPlaceholder or sheet.IsTemplate)
    except Exception:
        return True


def sheet_leaf(doc, sheet, sec, ctx):
    number = to_text(sheet.SheetNumber)
    name = element_name(sheet)
    revit_sort = lookup(doc, sheet, sec.sort_name) if sec.sort_name else number
    return Leaf(u'e:{0}'.format(eid_value(sheet.Id)), u'sheets',
                u'sheet', u'{0} - {1}'.format(number, name),
                sort_text=number, number=number,
                values=_values(doc, sheet, sec.names, ctx),
                folders=folders_of(sec.rorg, sheet), eid=sheet.Id,
                uid=sheet.UniqueId, revit_sort=revit_sort)


def _read_sheets(doc, snap, ctx):
    sheets = [sheet for sheet in _collect(doc, ViewSheet) if is_sheet(sheet)]
    sec = Section(doc, snap, u'sheets')
    sec.describe(snap, sheets)
    leaves = []
    for sheet in sheets:
        try:
            leaves.append(sheet_leaf(doc, sheet, sec, ctx))
        except Exception:
            snap.errors.append(pbp_log.exc(u'read sheet'))
    snap.tabs[u'sheets'] = leaves
    snap.catalogues[u'sheets'] = catalogue(sheets, u'sheets')


def is_schedule(schedule):
    try:
        if schedule.IsTemplate or schedule.IsTitleblockRevisionSchedule:
            return False
        if getattr(schedule, u'IsInternalKeynoteSchedule', False):
            return False
    except Exception:
        pass
    return True


def schedule_leaf(doc, schedule, sec, ctx):
    name = element_name(schedule)
    revit_sort = lookup(doc, schedule, sec.sort_name) if sec.sort_name else name
    return Leaf(u'e:{0}'.format(eid_value(schedule.Id)), u'schedules',
                u'schedule', name, values=_values(doc, schedule, sec.names, ctx),
                folders=folders_of(sec.rorg, schedule), eid=schedule.Id,
                uid=schedule.UniqueId, revit_sort=revit_sort)


def _read_schedules(doc, snap, ctx):
    schedules = [s for s in _collect(doc, ViewSchedule) if is_schedule(s)]
    sec = Section(doc, snap, u'schedules')
    sec.describe(snap, schedules)
    leaves = []
    for schedule in schedules:
        try:
            leaves.append(schedule_leaf(doc, schedule, sec, ctx))
        except Exception:
            snap.errors.append(pbp_log.exc(u'read schedule'))
    snap.tabs[u'schedules'] = leaves
    snap.catalogues[u'schedules'] = catalogue(schedules, u'schedules')


def panel_leaf(doc, panel, sec, ctx):
    return Leaf(u'e:{0}'.format(eid_value(panel.Id)), u'panels',
                u'panel', element_name(panel), values=_values(doc, panel, sec.names, ctx),
                eid=panel.Id, uid=panel.UniqueId)


def _read_panels(doc, snap, ctx):
    snap.revit_names[u'panels'] = u''
    snap.revit_desc[u'panels'] = False
    if PanelScheduleView is None:
        return
    sec = Section(doc, snap, u'panels')
    panels = [p for p in _collect(doc, PanelScheduleView)
              if not getattr(p, u'IsTemplate', False)]
    leaves = []
    for panel in panels:
        try:
            leaves.append(panel_leaf(doc, panel, sec, ctx))
        except Exception:
            snap.errors.append(pbp_log.exc(u'read panel schedule'))
    snap.tabs[u'panels'] = leaves
    snap.catalogues[u'panels'] = catalogue(panels, u'panels')


def is_family_type(element_type):
    u"""A type the Families tab lists: a loadable or system family's type
    in a model or annotation category."""
    try:
        category = element_type.Category
        if category is None:
            return False
        if to_text(category.CategoryType) not in (u'Model', u'Annotation'):
            return False
        return bool(to_text(getattr(element_type, u'FamilyName', u'')))
    except Exception:
        return False


def type_leaf(doc, element_type, sec, ctx):
    return Leaf(u'e:{0}'.format(eid_value(element_type.Id)), u'families',
                u'type', element_name(element_type),
                values=_values(doc, element_type, sec.names, ctx),
                eid=element_type.Id, uid=element_type.UniqueId)


def _read_families(doc, snap, ctx):
    types = []
    try:
        collector = FilteredElementCollector(doc).WhereElementIsElementType()
        types = [t for t in collector if is_family_type(t)]
    except Exception:
        snap.errors.append(pbp_log.exc(u'read families'))
    sec = Section(doc, snap, u'families')
    leaves = []
    for element_type in types:
        try:
            leaves.append(type_leaf(doc, element_type, sec, ctx))
        except Exception:
            snap.errors.append(pbp_log.exc(u'read family type'))
    snap.tabs[u'families'] = leaves
    snap.catalogues[u'families'] = catalogue(types, u'families')


READERS = {u'views': _read_views, u'legends': _read_legends, u'sheets': _read_sheets,
           u'schedules': _read_schedules, u'panels': _read_panels,
           u'families': _read_families}
LEAF_BUILDERS = {u'views': view_leaf, u'legends': view_leaf, u'sheets': sheet_leaf,
                 u'schedules': schedule_leaf, u'panels': panel_leaf,
                 u'families': type_leaf}


# ============================================================
# jobs
# ============================================================

def read_open_views(uiapp):
    u"""The light read after a view is activated: which views are open."""
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        return None
    doc = uidoc.Document
    key = doc_key(doc)
    open_ids = set()
    try:
        for ui_view in uidoc.GetOpenUIViews():
            open_ids.add(eid_value(ui_view.ViewId))
    except Exception:
        pass
    active = 0
    try:
        active = eid_value(uidoc.ActiveView.Id)
    except Exception:
        pass
    return {u'key': key, u'open': open_ids, u'active': active}


def _ids(leaves):
    ids = List[ElementId]()
    for leaf in leaves:
        if leaf.eid is not None:
            ids.Add(leaf.eid)
    return ids


def open_leaves(uiapp, leaves):
    u"""Open each in turn; an open is checked by reading the active view back.

    Every view, legend and sheet opened is zoomed to fit (zoom extents).
    One whose window Revit has not made yet - RequestViewChange opens it
    after this returns - comes back in 'zoom_later' for a second pass."""
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    opened = 0
    failed = []
    to_zoom = []
    for leaf in leaves:
        try:
            view = doc.GetElement(leaf.eid)
            if view is None:
                failed.append((leaf.text, u'no longer in the model'))
                continue
            uidoc.ActiveView = view
            if eid_value(uidoc.ActiveView.Id) == eid_value(leaf.eid):
                opened += 1
            else:
                uidoc.RequestViewChange(view)
                opened += 1
            if leaf.tab in ZOOM_TABS:
                to_zoom.append(leaf)
        except Exception as error:
            failed.append((leaf.text, to_text(error)))
            pbp_log.exc(u'open ' + leaf.text)
    later = zoom_leaves(uiapp, to_zoom)
    pbp_log.log(u'opened {0}, failed {1}, zoomed {2}, zoom later {3}'.format(
        opened, len(failed), len(to_zoom) - len(later), len(later)))
    return {u'opened': opened, u'failed': failed, u'zoom_later': later}


def zoom_leaves(uiapp, leaves):
    u"""Zoom each open window of these views to fit. Returns the leaves
    that have no window yet."""
    if not leaves:
        return []
    uidoc = uiapp.ActiveUIDocument
    windows = {}
    try:
        for ui_view in uidoc.GetOpenUIViews():
            windows[eid_value(ui_view.ViewId)] = ui_view
    except Exception:
        pbp_log.exc(u'zoom: open views')
    later = []
    for leaf in leaves:
        ui_view = windows.get(eid_value(leaf.eid))
        if ui_view is None:
            later.append(leaf)
            continue
        try:
            ui_view.ZoomToFit()
        except Exception:
            pbp_log.exc(u'zoom ' + leaf.text)
    return later


def select_leaves(uiapp, leaves):
    try:
        uiapp.ActiveUIDocument.Selection.SetElementIds(_ids(leaves))
        return {u'selected': len(leaves), u'ok': True}
    except Exception as error:
        pbp_log.exc(u'select')
        return {u'selected': 0, u'ok': False, u'why': to_text(error)}


def rename_leaf(uiapp, leaf, new_name, new_number=None):
    u"""Rename (and for a sheet, renumber) in one transaction. None leaves
    that part as it is."""
    doc = uiapp.ActiveUIDocument.Document
    element = doc.GetElement(leaf.eid)
    if element is None:
        return {u'ok': False, u'why': u'It is no longer in the model.'}
    transaction = Transaction(doc, u'RevoBIM Project Browser Pro - rename')
    transaction.Start()
    try:
        if new_number is not None:
            element.SheetNumber = new_number
        if new_name is not None:
            try:
                element.Name = new_name
            except Exception:
                Element.Name.SetValue(element, new_name)
        transaction.Commit()
    except Exception as error:
        try:
            transaction.RollBack()
        except Exception:
            pass
        pbp_log.exc(u'rename')
        return {u'ok': False, u'why': to_text(error)}
    element = doc.GetElement(leaf.eid)
    landed = element_name(element)
    if new_name is not None and landed != new_name:
        return {u'ok': False, u'why': u'Revit kept the name "{0}".'.format(landed)}
    if new_number is not None:
        try:
            number = to_text(element.SheetNumber)
        except Exception:
            number = u''
        if number != new_number:
            return {u'ok': False, u'why': u'Revit kept the number "{0}".'.format(number)}
    return {u'ok': True}


def place_type(uiapp, leaf):
    uidoc = uiapp.ActiveUIDocument
    element = uidoc.Document.GetElement(leaf.eid)
    try:
        uidoc.PostRequestForElementTypePlacement(element)
        return {u'ok': True}
    except Exception as error:
        return {u'ok': False, u'why': to_text(error)}


def select_instances(uiapp, leaf):
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    element = doc.GetElement(leaf.eid)
    ids = List[ElementId]()
    if isinstance(element, FamilySymbol):
        for eid in FilteredElementCollector(doc).WherePasses(
                FamilyInstanceFilter(doc, leaf.eid)).ToElementIds():
            ids.Add(eid)
    else:
        target = eid_value(leaf.eid)
        for instance in FilteredElementCollector(doc).WhereElementIsNotElementType():
            try:
                if eid_value(instance.GetTypeId()) == target:
                    ids.Add(instance.Id)
            except Exception:
                continue
    uidoc.Selection.SetElementIds(ids)
    return {u'count': ids.Count}


# ============================================================
# Pro Sheets Exporter
# ============================================================

PROSHEETS_TOKEN = u'prosheetsexporter'
PROSHEETS_FALLBACK_IDS = [
    u'CustomCtrl_%CustomCtrl_%RevoBIM PY%Sheet Tools%Pro Sheets Exporter',
]


def _norm(text):
    return u''.join(ch for ch in to_text(text).lower() if ch.isalnum())


def ribbon_ids(token):
    u"""Ids of ribbon items whose id or text names the tool.

    pyRevit's command ids embed the tab, panel and button names, and have
    changed shape between pyRevit releases, so the ribbon itself is asked
    rather than an id being guessed.
    """
    found = []
    try:
        from Autodesk.Windows import ComponentManager
    except Exception:
        return found

    def visit(items, depth):
        if items is None or depth > 6:
            return
        for item in items:
            try:
                item_id = to_text(getattr(item, u'Id', u''))
                item_text = to_text(getattr(item, u'Text', u''))
                if token in _norm(item_id) or _norm(item_text) == token:
                    if item_id and item_id not in found:
                        found.append(item_id)
                visit(getattr(item, u'Items', None), depth + 1)
            except Exception:
                continue
    try:
        for tab in ComponentManager.Ribbon.Tabs:
            for panel in tab.Panels:
                try:
                    visit(panel.Source.Items, 0)
                except Exception:
                    continue
    except Exception:
        pbp_log.exc(u'ribbon_ids')
    return found


def find_command(token=PROSHEETS_TOKEN, fallbacks=None):
    candidates = ribbon_ids(token) + list(fallbacks or PROSHEETS_FALLBACK_IDS)
    for text in candidates:
        try:
            command_id = RevitCommandId.LookupCommandId(text)
        except Exception:
            command_id = None
        if command_id is not None:
            return command_id, text
    pbp_log.log(u'Pro Sheets command not found; tried {0}'.format(candidates))
    return None, u''


def prosheets(uiapp, kind, leaves, folder):
    u"""Select the sheets, write the hand-off and post the Pro Sheets button.

    The post runs once this job has returned, so nothing here can see Pro
    Sheets open - the browser waits for its answer in the result file.
    """
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    uidoc.Selection.SetElementIds(_ids(leaves))
    token = pbp_handoff.write_request(folder, kind, to_text(doc.Title),
                                      [(leaf.uid, leaf.number) for leaf in leaves])
    command_id, text = find_command()
    if command_id is None:
        return {u'ok': False, u'token': token,
                u'why': u'Pro Sheets Exporter is not on the ribbon - is it installed?'}
    uiapp.PostCommand(command_id)
    pbp_log.log(u'posted Pro Sheets ({0}) for {1} sheet(s) via {2}'.format(
        kind, len(leaves), text))
    return {u'ok': True, u'token': token}


# ============================================================
# Revit's selection, found in the browser
# ============================================================
SELECTION_LIMIT = 60


def selection_targets(doc, ids):
    u"""What Revit's selection is, as browser leaf keys.

    [('view', 'e:12'), ('type', 'e:34'), ...]: a view, sheet or schedule
    selected as itself (Revit's own browser selects them so); a viewport or
    a schedule on a sheet as the view or schedule it shows; anything else
    as its type (only the Families tab follows those). Capped, so a
    selection of a thousand pipes costs nothing."""
    out = []
    seen = set()
    for count, eid in enumerate(ids):
        if count >= SELECTION_LIMIT:
            break
        try:
            element = doc.GetElement(eid)
        except Exception:
            element = None
        if element is None:
            continue
        kind, target = u'type', None
        try:
            if Viewport is not None and isinstance(element, Viewport):
                kind, target = u'view', element.ViewId
            elif hasattr(element, u'ScheduleId') and not isinstance(element, View):
                kind, target = u'view', element.ScheduleId
            elif isinstance(element, View):
                kind, target = u'view', element.Id
            elif isinstance(element, ElementType):
                target = element.Id
            else:
                target = element.GetTypeId()
        except Exception:
            target = None
        value = eid_value(target)
        if value and value > 0:
            item = (kind, u'e:{0}'.format(value))
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


# ============================================================
# placing views on a sheet
# ============================================================

def sheet_centre(doc, sheet):
    u"""The middle of the sheet's title block - or of the sheet itself when
    it has none - as a point on the sheet."""
    from Autodesk.Revit.DB import XYZ, BuiltInCategory
    try:
        blocks = (FilteredElementCollector(doc, sheet.Id)
                  .OfCategory(BuiltInCategory.OST_TitleBlocks)
                  .WhereElementIsNotElementType())
        for block in blocks:
            box = block.get_BoundingBox(sheet)
            if box is not None:
                return XYZ((box.Min.X + box.Max.X) / 2.0, (box.Min.Y + box.Max.Y) / 2.0, 0.0)
    except Exception:
        pbp_log.exc(u'title block centre')
    outline = sheet.Outline
    return XYZ((outline.Min.U + outline.Max.U) / 2.0, (outline.Min.V + outline.Max.V) / 2.0, 0.0)


def place_on_sheet(uiapp, sheet_eid, leaves):
    u"""Place views, legends, schedules and panel schedules on a sheet, each
    centred on its title block, in one transaction. A view already on a
    sheet (Revit allows a view on one sheet only; legends and schedules can
    go on many) is refused and named."""
    doc = uiapp.ActiveUIDocument.Document
    sheet = doc.GetElement(sheet_eid)
    if not isinstance(sheet, ViewSheet):
        return {u'ok': False, u'why': u'That is not a sheet.', u'placed': 0, u'refused': []}
    centre = sheet_centre(doc, sheet)
    placed = 0
    refused = []
    transaction = Transaction(doc, u'RevoBIM Project Browser Pro - place on sheet')
    transaction.Start()
    try:
        for leaf in leaves:
            try:
                if leaf.tab == u'schedules':
                    ScheduleSheetInstance.Create(doc, sheet.Id, leaf.eid, centre)
                elif leaf.tab == u'panels':
                    if PanelScheduleSheetInstance is None:
                        raise Exception(u'panel schedules cannot be placed from here')
                    instance = PanelScheduleSheetInstance.Create(doc, leaf.eid, sheet)
                    instance.Origin = centre
                else:
                    if Viewport is None or not Viewport.CanAddViewToSheet(doc, sheet.Id, leaf.eid):
                        refused.append((leaf.text, u'already on a sheet, or not placeable'))
                        continue
                    Viewport.Create(doc, sheet.Id, leaf.eid, centre)
                placed += 1
            except Exception as error:
                refused.append((leaf.text, to_text(error)))
        transaction.Commit()
    except Exception as error:
        try:
            transaction.RollBack()
        except Exception:
            pass
        pbp_log.exc(u'place on sheet')
        return {u'ok': False, u'why': to_text(error), u'placed': 0, u'refused': refused}
    pbp_log.log(u'placed {0} on {1}, refused {2}'.format(placed, element_name(sheet), refused))
    return {u'ok': True, u'placed': placed, u'refused': refused,
            u'sheet': u'{0} - {1}'.format(to_text(sheet.SheetNumber), element_name(sheet))}


def place_on_active_sheet(uiapp, screen_x, screen_y, leaves):
    u"""Dropped outside the browser: place on the sheet open in Revit, when
    the drop landed on Revit's drawing area and the active view is a sheet.
    No point (the menu's Place on the open sheet): no area check."""
    uidoc = uiapp.ActiveUIDocument
    inside = True
    if screen_x is not None:
        try:
            area = uiapp.DrawingAreaExtents
            inside = area.Left <= screen_x <= area.Right and area.Top <= screen_y <= area.Bottom
        except Exception:
            inside = True
    if not inside:
        return {u'ok': False, u'why': u'Drop the views on a sheet - in this browser or in Revit\'s view.',
                u'placed': 0, u'refused': []}
    view = uidoc.ActiveView
    if not isinstance(view, ViewSheet):
        return {u'ok': False, u'why': u'The view open in Revit is not a sheet - open a sheet first.',
                u'placed': 0, u'refused': []}
    return place_on_sheet(uiapp, view.Id, leaves)


def free_pane(uiapp, guid_texts):
    u"""The first of these panes Revit is not showing, or None. A pane
    Revit does not know (added in an update, before a restart) is skipped."""
    from System import Guid
    from Autodesk.Revit.UI import DockablePaneId
    for guid_text in guid_texts:
        try:
            pane = uiapp.GetDockablePane(DockablePaneId(Guid(guid_text)))
            if not pane.IsShown():
                return guid_text
        except Exception:
            continue
    return None


def hide_pane(uiapp, guid_text):
    from System import Guid
    from Autodesk.Revit.UI import DockablePaneId
    try:
        uiapp.GetDockablePane(DockablePaneId(Guid(guid_text))).Hide()
        return {u'ok': True}
    except Exception as error:
        return {u'ok': False, u'why': to_text(error)}


def show_pane(uiapp, guid_text):
    from System import Guid
    from Autodesk.Revit.UI import DockablePaneId
    try:
        pane = uiapp.GetDockablePane(DockablePaneId(Guid(guid_text)))
        pane.Show()
        return {u'ok': True}
    except Exception as error:
        # A pane added in an update is only registered at the next Revit
        # start; until then Revit does not know its GUID.
        return {u'ok': False, u'why': to_text(error)}
