# -*- coding: utf-8 -*-
"""Find in View - everything that talks to the Revit document.

Nothing here writes to the model: the tool only reads, changes the active view
and zooms, so it needs no transaction at all.
"""

import fiv_clr  # noqa: F401 - must be imported before any Autodesk.* name

from Autodesk.Revit.DB import (FilteredElementCollector, View, ViewSheet, ElementId,
                               XYZ, ViewPlan, View3D, ElementMulticategoryFilter,
                               Transaction, WorksharingUtils, BuiltInParameter,
                               Level)
from Autodesk.Revit.UI import RevitCommandId, PostableCommand
from System import Int64

from System.Collections.Generic import List

import fiv_core
from fiv_core import eid_value

# ---------------------------------------------------------------------------
# which view types are worth listing
# ---------------------------------------------------------------------------
#
# A view has to be able to show model elements and be zoomable for "Show Me" to
# mean anything, so drafting views, legends, schedules, sheets and renderings
# are left out rather than listed and then failing.

VIEW_TYPE_LABELS = [
    ('FloorPlan',      'Floor Plan'),
    ('CeilingPlan',    'Ceiling Plan'),
    ('EngineeringPlan','Structural Plan'),
    ('AreaPlan',       'Area Plan'),
    ('Section',        'Section'),
    ('Elevation',      'Elevation'),
    ('Detail',         'Detail View'),
    ('ThreeD',         '3D View'),
    ('Walkthrough',    'Walkthrough'),
]

_LABEL_BY_NAME = {}
for _name, _label in VIEW_TYPE_LABELS:
    _LABEL_BY_NAME[_name] = _label


def view_type_label(view):
    try:
        name = '{0}'.format(view.ViewType)
    except Exception:
        return 'View'
    return _LABEL_BY_NAME.get(name, name)


def is_listable(view):
    """A view the tool can activate and zoom in."""
    try:
        if view is None or view.IsTemplate:
            return False
    except Exception:
        return False
    try:
        if isinstance(view, ViewSheet):
            return False
    except Exception:
        pass
    try:
        return '{0}'.format(view.ViewType) in _LABEL_BY_NAME
    except Exception:
        return False


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------

class ViewRow(object):
    """One view in the list.  WPF is never asked to read these attributes: the
    grid binds the row object itself with an IValueConverter per cell."""

    __slots__ = ('view', 'view_id', 'name', 'type_label', 'scale', 'sheet',
                 'discipline', 'sort_index', '_search', '_keys')

    def __init__(self, view):
        self.view = view
        self.view_id = view.Id
        self.name = safe_view_name(view)
        self.type_label = view_type_label(view)
        self.scale = scale_text(view)
        self.sheet = ''
        self.discipline = ''
        self.sort_index = 0

    def cell(self, key):
        if key == 'name':
            return self.name
        if key == 'type':
            return self.type_label
        if key == 'scale':
            return self.scale
        if key == 'sheet':
            return self.sheet
        return ''

    # Every keystroke in the search box filters and re-sorts every row. Both
    # are built from text that never changes while the window is open, so
    # they are worked out once, on first use - after read_views has filled in
    # the sheet - and then reused.

    def sort_key(self, key):
        keys = self._cached_keys()
        if key not in keys:
            keys[key] = fiv_core.natural_key(self.cell(key))
        return keys[key]

    def search_text(self):
        try:
            return self._search
        except AttributeError:
            self._search = ' '.join([self.name, self.type_label, self.sheet,
                                     self.scale]).lower()
            return self._search

    def _cached_keys(self):
        try:
            return self._keys
        except AttributeError:
            self._keys = {}
            return self._keys


def safe_view_name(view):
    try:
        name = view.Name
        if name:
            return name
    except Exception:
        pass
    try:
        parameter = view.get_Parameter(BuiltInParameter.VIEW_NAME)
        if parameter is not None:
            return parameter.AsString() or ''
    except Exception:
        pass
    return 'View {0}'.format(eid_value(view.Id))


def scale_text(view):
    try:
        if isinstance(view, View3D):
            return ''
    except Exception:
        pass
    try:
        scale = view.Scale
        if scale:
            return '1:{0}'.format(scale)
    except Exception:
        pass
    return ''


# ---------------------------------------------------------------------------
# reading the project
# ---------------------------------------------------------------------------

def read_selection(uidoc):
    """The selected elements, and the categories they belong to.

    Returns (elements, element_ids, category_ids, category_names).
    """
    doc = uidoc.Document
    elements = []
    element_ids = []
    try:
        ids = uidoc.Selection.GetElementIds()
    except Exception:
        ids = []
    for element_id in ids:
        try:
            element = doc.GetElement(element_id)
        except Exception:
            element = None
        if element is None:
            continue
        elements.append(element)
        element_ids.append(element_id)

    category_ids = []
    category_names = []
    seen = set()
    for element in elements:
        try:
            category = element.Category
        except Exception:
            category = None
        if category is None:
            continue
        key = eid_value(category.Id)
        if key in seen:
            continue
        seen.add(key)
        category_ids.append(category.Id)
        try:
            category_names.append(category.Name)
        except Exception:
            category_names.append('Category {0}'.format(key))
    return elements, element_ids, category_ids, category_names


def element_from_token(doc, token):
    """One typed id: an element id, or a unique id, or nothing.

    ElementId takes an Int32 up to Revit 2025 and an Int64 from 2026, and which
    one an IronPython int binds to varies - so both are tried before the token
    is called a miss.
    """
    text = '{0}'.format(token).strip()
    if not text:
        return None
    digits = text[1:] if text.startswith('-') else text
    if digits.isdigit():
        number = int(text)
        for build in (lambda value: ElementId(value),
                      lambda value: ElementId(Int64(value))):
            try:
                element_id = build(number)
            except Exception:
                continue
            try:
                element = doc.GetElement(element_id)
            except Exception:
                element = None
            if element is not None:
                return element
        return None
    # not a number: Revit's own dialog does not take these, but a unique id is
    # what gets pasted out of a coordination report, so it is worth trying
    try:
        return doc.GetElement(text)
    except Exception:
        return None


def find_by_ids(doc, tokens):
    """Returns (elements, ids, missing tokens)."""
    elements = []
    ids = []
    missing = []
    seen = set()
    for token in tokens:
        element = element_from_token(doc, token)
        if element is None:
            missing.append(token)
            continue
        key = eid_value(element.Id)
        if key in seen:
            continue
        seen.add(key)
        elements.append(element)
        ids.append(element.Id)
    return elements, ids, missing


def select_elements(uidoc, element_ids):
    try:
        ids = List[ElementId]()
        for element_id in element_ids:
            ids.Add(element_id)
        uidoc.Selection.SetElementIds(ids)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# what the selected element is
# ---------------------------------------------------------------------------
#
# The level lives in a different parameter for nearly every category, so the
# list is tried in order.  Every member is looked up LATE, by name, because a
# BuiltInParameter that does not exist on a given release must not be able to
# take the module down at import.

LEVEL_PARAMS = [
    'RBS_START_LEVEL_PARAM',              # ducts, pipes, trays, conduit
    'FAMILY_LEVEL_PARAM',                 # family instances
    'INSTANCE_REFERENCE_LEVEL_PARAM',
    'SCHEDULE_LEVEL_PARAM',
    'INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM',
    'LEVEL_PARAM',
    'WALL_BASE_CONSTRAINT',
    'ROOF_BASE_LEVEL_PARAM',
    'STAIRS_BASE_LEVEL_PARAM',
    'ROOM_LEVEL_ID',
    'GROUP_LEVEL',
]

LEVEL_PARAM_NAMES = ['Reference Level', 'Level', 'Schedule Level', 'Base Level',
                     'Base Constraint']


def _level_name_from_id(doc, element_id):
    try:
        if element_id is None or eid_value(element_id) <= 0:
            return ''
        level = doc.GetElement(element_id)
        if level is None:
            return ''
        return level.Name or ''
    except Exception:
        return ''


_LEVEL_MEMBERS = []


def level_members():
    """The BuiltInParameter members this release actually has, looked up once.

    Still late - inside a function, never at import - so a member missing on a
    given release cannot take the module down. But only once, rather than a
    dozen reflection lookups per element on a selection of hundreds.
    """
    if not _LEVEL_MEMBERS:
        for name in LEVEL_PARAMS:
            member = getattr(BuiltInParameter, name, None)
            if member is not None:
                _LEVEL_MEMBERS.append(member)
    return _LEVEL_MEMBERS


def level_from_parameters(doc, element):
    """The level a parameter says the element is on, or ''."""
    for member in level_members():
        try:
            parameter = element.get_Parameter(member)
        except Exception:
            parameter = None
        if parameter is None:
            continue
        found = _level_name_from_id(doc, _as_element_id(parameter))
        if found:
            return found
    for name in LEVEL_PARAM_NAMES:
        try:
            parameters = element.GetParameters(name)
        except Exception:
            parameters = []
        for parameter in parameters or []:
            found = _level_name_from_id(doc, _as_element_id(parameter))
            if found:
                return found
            try:
                text = parameter.AsValueString()
                if text:
                    return text
            except Exception:
                pass
    return ''


def _as_element_id(parameter):
    try:
        return parameter.AsElementId()
    except Exception:
        return None


def project_levels(doc):
    """[(name, elevation)] for every level, read once per run."""
    levels = []
    try:
        for level in FilteredElementCollector(doc).OfClass(Level):
            try:
                levels.append((level.Name, level.Elevation))
            except Exception:
                pass
    except Exception:
        pass
    return levels


def element_level(doc, element, levels=None):
    """(level name, how it was worked out).

    Parameter first, then the host's, then the nearest level below the element
    - and the last of those says so, because a derived answer presented as a
    read one is worse than no answer.
    """
    name = level_from_parameters(doc, element)
    if name:
        return name, ''

    try:
        host = element.Host
    except Exception:
        host = None
    if host is not None:
        name = level_from_parameters(doc, host)
        if name:
            return name, 'from its host'

    try:
        element_id = getattr(element, 'LevelId', None)
        name = _level_name_from_id(doc, element_id)
        if name:
            return name, ''
    except Exception:
        pass

    box = elements_box([element])
    if box is None:
        return '', ''
    if levels is None:
        levels = project_levels(doc)
    middle = (box[0][2] + box[1][2]) / 2.0
    name = fiv_core.nearest_level(levels, middle)
    if not name:
        return '', ''
    return name, 'nearest below, not from a parameter'


def type_name_of(doc, element):
    """"Family : Type", as the properties palette reads it."""
    try:
        element_type = doc.GetElement(element.GetTypeId())
    except Exception:
        element_type = None
    if element_type is None:
        return ''
    type_name = ''
    family_name = ''
    try:
        type_name = element_type.Name or ''
    except Exception:
        type_name = ''
    for attempt in ('FamilyName',):
        try:
            family_name = getattr(element_type, attempt, '') or ''
        except Exception:
            family_name = ''
        if family_name:
            break
    if not family_name:
        try:
            family_name = element_type.Family.Name or ''
        except Exception:
            family_name = ''
    if family_name and type_name:
        return '{0} : {1}'.format(family_name, type_name)
    return type_name or family_name


def selection_properties(doc, elements):
    """[(label, value, note)] for the properties panel.

    One element gets the properties palette's own answers; several get the
    breakdown, because twenty rows of the same value is not information.
    """
    rows = []
    if not elements:
        return rows

    levels = project_levels(doc)

    if len(elements) == 1:
        element = elements[0]
        try:
            category = element.Category.Name
        except Exception:
            category = ''
        level, note = element_level(doc, element, levels)
        rows.append(('Level', level or 'none', note))
        rows.append(('Category', category, ''))
        rows.append(('Type', type_name_of(doc, element), ''))
        try:
            rows.append(('Id', '{0}'.format(eid_value(element.Id)), ''))
        except Exception:
            pass
        return rows

    names = []
    derived = 0
    for element in elements:
        level, note = element_level(doc, element, levels)
        names.append(level or 'no level')
        if note:
            derived += 1
    rows.append(('Levels', fiv_core.summarise_levels(names),
                 '' if not derived else
                 '{0} worked out from the elevation'.format(derived)))
    return rows


def categories_of(elements):
    """The categories a set of elements falls into.  (ids, names).

    Same rule as read_selection uses, pulled out so the selection can be
    changed from inside the tool without going back to the document.
    """
    category_ids = []
    category_names = []
    seen = set()
    for element in elements:
        try:
            category = element.Category
        except Exception:
            category = None
        if category is None:
            continue
        key = eid_value(category.Id)
        if key in seen:
            continue
        seen.add(key)
        category_ids.append(category.Id)
        try:
            category_names.append(category.Name)
        except Exception:
            category_names.append('Category {0}'.format(key))
    return category_ids, category_names


def category_counts(elements):
    """{category name: how many of the selected elements are in it}."""
    counts = {}
    for element in elements:
        try:
            name = element.Category.Name
        except Exception:
            name = 'No category'
        counts[name] = counts.get(name, 0) + 1
    return counts


def read_views(doc):
    """Every listable view, plus which sheet each one is placed on."""
    rows = []
    try:
        collector = FilteredElementCollector(doc).OfClass(View)
        for view in collector:
            if is_listable(view):
                rows.append(ViewRow(view))
    except Exception:
        pass

    sheet_by_view = read_sheet_map(doc)
    for row in rows:
        row.sheet = sheet_by_view.get(eid_value(row.view_id), '')

    rows.sort(key=lambda row: (fiv_core.natural_key(row.type_label),
                               fiv_core.natural_key(row.name)))
    for index, row in enumerate(rows):
        row.sort_index = index
    return rows


def read_sheet_map(doc):
    """One pass, not a collector per view: this runs on every open."""
    mapping = {}
    try:
        sheets = FilteredElementCollector(doc).OfClass(ViewSheet)
        for sheet in sheets:
            try:
                if sheet.IsTemplate:
                    continue
                number = sheet.SheetNumber or ''
            except Exception:
                number = ''
            try:
                placed = sheet.GetAllPlacedViews()
            except Exception:
                placed = []
            for view_id in placed:
                key = eid_value(view_id)
                if key not in mapping:
                    mapping[key] = number
    except Exception:
        pass
    return mapping


def passes_filters(row, ticked_types, query):
    """The one place the filter rule lives, kept pure so the bench can test it.

    Both tests are free: a set membership and a string match against text
    already read. Nothing in here touches the document, which is the whole
    point - the filters that did are gone.
    """
    if row.type_label not in ticked_types:
        return False
    if not fiv_core.matches_keywords(row.search_text(), query):
        return False
    return True


def find_remembered(rows, view_id_value, name):
    """The row for the view used last, by id first and by name second.

    The id is the better match: it survives a rename.  The name is the better
    fallback: it survives the model being rebuilt from a template, where every
    id has moved but the views are the same views.  Kept pure so the bench can
    hold it to both.
    """
    if view_id_value:
        for row in rows:
            if eid_value(row.view_id) == view_id_value:
                return row
    if name:
        for row in rows:
            if row.name == name:
                return row
    return None


def view_types_present(rows):
    """The view type labels actually in this project, in a settled order."""
    present = []
    seen = set()
    for _name, label in VIEW_TYPE_LABELS:
        for row in rows:
            if row.type_label == label and label not in seen:
                seen.add(label)
                present.append(label)
                break
    for row in rows:
        if row.type_label not in seen:
            seen.add(row.type_label)
            present.append(row.type_label)
    return present


# ---------------------------------------------------------------------------
# going to the view
# ---------------------------------------------------------------------------

def _box_tuple(bounding_box):
    if bounding_box is None:
        return None
    try:
        minimum = bounding_box.Min
        maximum = bounding_box.Max
        low = (minimum.X, minimum.Y, minimum.Z)
        high = (maximum.X, maximum.Y, maximum.Z)
        transform = None
        try:
            transform = bounding_box.Transform
        except Exception:
            transform = None
        if transform is not None and not transform.IsIdentity:
            corners = []
            for x_value in (low[0], high[0]):
                for y_value in (low[1], high[1]):
                    for z_value in (low[2], high[2]):
                        point = transform.OfPoint(XYZ(x_value, y_value, z_value))
                        corners.append((point.X, point.Y, point.Z))
            lows = [min(corner[axis] for corner in corners) for axis in range(3)]
            highs = [max(corner[axis] for corner in corners) for axis in range(3)]
            return (tuple(lows), tuple(highs))
        return (low, high)
    except Exception:
        return None


def elements_box(elements, view=None):
    """Union of the selected elements' boxes, in that view where possible."""
    boxes = []
    for element in elements:
        box = None
        if view is not None:
            try:
                box = _box_tuple(element.get_BoundingBox(view))
            except Exception:
                box = None
        if box is None:
            try:
                box = _box_tuple(element.get_BoundingBox(None))
            except Exception:
                box = None
        if box is not None:
            boxes.append(box)
    return fiv_core.union_box(boxes)


def read_window_rects(uidoc):
    """Every open view window, as (view id, left, top, right, bottom)."""
    rects = []
    try:
        for ui_view in uidoc.GetOpenUIViews():
            try:
                rect = ui_view.GetWindowRectangle()
                rects.append((eid_value(ui_view.ViewId),
                              rect.Left, rect.Top, rect.Right, rect.Bottom))
            except Exception:
                pass
    except Exception:
        pass
    return rects


def close_ui_view(uidoc, view_id_value):
    """Close one open view window.  Revit refuses to close the last one."""
    try:
        for ui_view in uidoc.GetOpenUIViews():
            if eid_value(ui_view.ViewId) == view_id_value:
                ui_view.Close()
                return True
    except Exception:
        pass
    return False


# Every known route to Revit's own tile command, tried in order.  The enum
# member has been spelled differently across releases and the command is only
# postable in some UI states, so one name is not enough - and a route that
# fails has to say WHY, or the only thing the user gets is "Revit said no".
TILE_COMMANDS = [
    ('enum', 'TileWindows'),
    ('enum', 'TileViews'),
    ('enum', 'Tile'),
    ('enum', 'TileWindow'),
    ('id', 'ID_WINDOW_TILE'),
    ('id', 'ID_WINDOW_TILE_HORZ'),
    ('id', 'ID_WINDOW_TILE_VERT'),
    ('id', 'ID_VIEW_TILE'),
]


def resolve_tile_command(kind, name):
    """One candidate route to the tile command.  Returns (command_id, note)."""
    try:
        if kind == 'enum':
            member = getattr(PostableCommand, name, None)
            if member is None:
                return None, 'PostableCommand has no member {0}'.format(name)
            command_id = RevitCommandId.LookupPostableCommandId(member)
        else:
            command_id = RevitCommandId.LookupCommandId(name)
        if command_id is None:
            return None, 'Revit does not know {0}'.format(name)
        return command_id, ''
    except Exception as error:
        return None, '{0}: {1}'.format(type(error).__name__, error)


def post_tile_windows(uiapp):
    """Ask Revit to tile its view windows.

    There is no API that arranges windows and none that says which pane a view
    lands in: this is Revit's own command, posted, and it decides the layout
    itself.  Every candidate name is looked up LATE, inside this function, so a
    release that does not have one cannot take the module down at import.

    Returns (ok, report) - the report names every route tried and what each one
    said, because a bare False is indistinguishable from a broken button.
    """
    if uiapp is None:
        return False, 'no Revit application to post to'

    tried = []
    for kind, name in TILE_COMMANDS:
        command_id = None
        note = ''
        try:
            command_id, note = resolve_tile_command(kind, name)
        except Exception as error:
            note = '{0}: {1}'.format(type(error).__name__, error)
        if command_id is None:
            tried.append('{0} - {1}'.format(name, note or 'not found'))
            continue
        # CanPostCommand is read for the report only, never used as a gate.
        # Tile is greyed out while one view window is open, and Revit does not
        # necessarily create the second window until this command ends - so the
        # honest answer at this moment can be "no" for a command that will be
        # perfectly postable by the time it runs.
        allowed = None
        try:
            allowed = bool(uiapp.CanPostCommand(command_id))
        except Exception:
            allowed = None
        try:
            uiapp.PostCommand(command_id)
            return True, name
        except Exception as error:
            tried.append('{0} - PostCommand threw: {1}{2}'.format(
                name, error,
                ' (CanPostCommand said no)' if allowed is False else ''))
    return False, '\n'.join(tried)


def tile_failure_message(report):
    return ('The view opened beside the one you came from, but Revit would not '
            'take the command that tiles the windows, so they are not laid '
            'out.\n\n'
            'Tile them from View > Tile Views, or with WT.\n\n'
            'What was tried:\n{0}\n\n'
            'Turn "warn_tile_failure" off in\n'
            '%APPDATA%\\RevoBIM\\find_in_view.txt to stop this being '
            'reported.').format(report or 'nothing')


def plan_tiling(rects, host_id, target_id, settings):
    """Decide what happens to the windows before the view is opened.

    Returns (view id to close or None, one of the fiv_core.TILE_* modes).

    Tile Views is posted in exactly one situation: the view you came from is
    the only window open, so there is no arrangement to preserve.  Any time
    Revit already has more than one view window up, that arrangement is the
    user's and the tool does not re-lay it out - it opens into it and leaves
    the layout alone.
    """
    if not fiv_core.as_bool(settings.get('open_tiled')):
        return None, fiv_core.TILE_NEVER

    for rect in rects:
        if rect[0] == target_id:
            # already open in its own window: activating it brings that window
            # forward exactly where it is
            return None, fiv_core.TILE_NEVER

    if len(rects) <= 1:
        # the view you came from, on its own
        return None, fiv_core.TILE_ALWAYS

    if fiv_core.looks_tiled(rects) and fiv_core.as_bool(settings.get('reuse_tile'), True):
        spare = fiv_core.pick_tile_to_reuse(rects, host_id, target_id)
        if spare is not None:
            # take a tile's place rather than adding a window, and never tile:
            # the rest of the arrangement stays where the user put it
            return spare, fiv_core.TILE_NEVER

    return None, fiv_core.TILE_NEVER


# ---------------------------------------------------------------------------
# making the selection visible in the view it is opening in
# ---------------------------------------------------------------------------

def hidden_categories_in(view, category_ids):
    """The selected categories the view has switched off."""
    hidden = []
    for category_id in category_ids or []:
        try:
            if view.GetCategoryHidden(category_id):
                hidden.append(category_id)
        except Exception:
            # not every category can be asked about in every view
            pass
    return hidden


def hidden_elements_in(view, elements):
    """Elements hidden in this view one at a time, rather than by category."""
    hidden = []
    for element in elements or []:
        try:
            if element.IsHidden(view):
                hidden.append(element)
        except Exception:
            pass
    return hidden


def category_name(doc, category_id):
    try:
        for category in doc.Settings.Categories:
            if eid_value(category.Id) == eid_value(category_id):
                return category.Name
    except Exception:
        pass
    return 'category {0}'.format(eid_value(category_id))


def drawn_in_view(doc, view, element_ids, category_ids=None):
    """Which of these the view actually draws.

    A view scoped collector is the honest test: it accounts for the crop, view
    filters, phasing, worksets, design options and the view range, none of
    which switching a category on will fix.

    It is narrowed to the selection's own categories INSIDE Revit before
    anything crosses into Python. Unfiltered, a busy services plan hands back
    tens of thousands of ids to answer a question about five pipes - and this
    runs on every launch with a selection and after every Show Me. The answer
    is identical: an element can only be drawn under its own category.
    """
    drawn = set()
    try:
        collector = FilteredElementCollector(doc, view.Id)
        narrowing = _category_filter(category_ids)
        if narrowing is not None:
            collector = collector.WherePasses(narrowing)
        found = collector.WhereElementIsNotElementType().ToElementIds()
    except Exception:
        return None
    wanted = set()
    for element_id in element_ids or []:
        wanted.add(eid_value(element_id))
    for element_id in found:
        key = eid_value(element_id)
        if key in wanted:
            drawn.add(key)
    return drawn


def _category_filter(category_ids):
    """One filter for every category in the selection, or None.

    Empty is decided on the Python list, before any .NET list is built: an
    empty multicategory filter matches nothing, which would report every view
    as missing the selection.
    """
    wanted = [category_id for category_id in (category_ids or [])
              if category_id is not None]
    if not wanted:
        return None
    try:
        ids = List[ElementId]()
        for category_id in wanted:
            ids.Add(category_id)
        return ElementMulticategoryFilter(ids)
    except Exception:
        return None


def view_has_template(view):
    try:
        return eid_value(view.ViewTemplateId) > 0
    except Exception:
        return False


def make_visible(doc, view, category_ids, elements, settings):
    """Switch the selection's categories back on in the view.  (notes, mode).

    This is the only place the tool writes to the model, and it writes in ONE
    transaction so a single undo puts the view back exactly as it was - which
    is as close to "temporary" as Revit gets on a view with no template.
    """
    notes = []
    hidden_categories = hidden_categories_in(view, category_ids)
    hidden_elements = hidden_elements_in(view, elements)

    mode = fiv_core.plan_unhide(
        fiv_core.as_bool(settings.get('unhide_categories'), True),
        (settings.get('unhide_mode') or 'auto').lower(),
        hidden_categories, hidden_elements, view_has_template(view))
    if mode == fiv_core.UNHIDE_NONE:
        return notes, mode

    wanted_mode = (settings.get('unhide_mode') or 'auto').lower()
    if wanted_mode == fiv_core.UNHIDE_TEMPORARY and mode == fiv_core.UNHIDE_PERMANENT:
        notes.append('The view has no view template, so Revit has no temporary '
                     'view properties mode to enter. The change was made to the '
                     'view itself - one undo puts it back.')

    # a view somebody else has is reported by name rather than failing mid write
    try:
        ids = List[ElementId]()
        ids.Add(view.Id)
        WorksharingUtils.CheckoutElements(doc, ids)
    except Exception:
        pass

    transaction = Transaction(doc, 'RevoBIM Find in View - show the selection')
    try:
        transaction.Start()
    except Exception as error:
        return ['The view could not be changed: {0}'.format(error)], fiv_core.UNHIDE_NONE

    turned_on = []
    failed = []
    try:
        if mode == fiv_core.UNHIDE_TEMPORARY:
            try:
                view.EnableTemporaryViewPropertiesMode(view.ViewTemplateId)
            except Exception as error:
                mode = fiv_core.UNHIDE_PERMANENT
                notes.append('Revit would not enter temporary view properties '
                             'mode ({0}), so the change was made to the view '
                             'itself - one undo puts it back.'.format(error))

        for category_id in hidden_categories:
            name = category_name(doc, category_id)
            allowed = True
            try:
                checker = getattr(view, 'CanCategoryBeHidden', None)
                if checker is not None:
                    allowed = bool(checker(category_id))
            except Exception:
                allowed = True
            if not allowed:
                failed.append('{0} cannot be switched on in this view'.format(name))
                continue
            try:
                view.SetCategoryHidden(category_id, False)
                turned_on.append(name)
            except Exception as error:
                failed.append('{0} would not switch on: {1}'.format(name, error))

        if hidden_elements:
            try:
                ids = List[ElementId]()
                for element in hidden_elements:
                    ids.Add(element.Id)
                view.UnhideElements(ids)
                turned_on.append(fiv_core.plural(len(hidden_elements),
                                                 'hidden element'))
            except Exception as error:
                failed.append('elements hidden one at a time would not come '
                              'back: {0}'.format(error))

        status = transaction.Commit()
    except Exception as error:
        try:
            transaction.RollBack()
        except Exception:
            pass
        return ['The view could not be changed: {0}'.format(error)], fiv_core.UNHIDE_NONE

    # prove the write: Revit does not reliably raise when one does not take
    still_hidden = hidden_categories_in(view, hidden_categories)
    if still_hidden:
        names = [category_name(doc, category_id) for category_id in still_hidden]
        failed.append('still switched off after the change: {0} - a view '
                      'template usually controls this'.format(', '.join(names)))
        for name in names:
            if name in turned_on:
                turned_on.remove(name)

    if turned_on:
        where = ('temporarily - the blue border is Revit showing temporary view '
                 'properties' if mode == fiv_core.UNHIDE_TEMPORARY
                 else 'in the view - one undo puts it back')
        notes.append('Switched on {0} {1}.'.format(', '.join(turned_on), where))
    for entry in failed:
        notes.append(entry)
    return notes, mode


def zoom_here(uidoc, view, elements, element_ids, settings):
    """Frame the view you are already in on the selection.  (ok, note).

    Nothing is activated, nothing is closed, nothing is written: the view is
    already open and already showing the elements, so this is only the zoom.
    """
    category_ids, _names = categories_of(elements)
    drawn = drawn_in_view(uidoc.Document, view, element_ids, category_ids)
    if drawn is None:
        return False, ''
    needs_all = fiv_core.as_bool(settings.get('zoom_here_needs_all'), True)
    decision = fiv_core.zoom_here_decision(
        fiv_core.as_bool(settings.get('zoom_here'), True),
        is_listable(view), len(element_ids), len(drawn), needs_all)
    if decision != fiv_core.HERE_ZOOM:
        return False, ''

    here = []
    for element in elements:
        try:
            if eid_value(element.Id) in drawn:
                here.append(element)
        except Exception:
            pass
    if not here:
        return False, ''

    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass
    return zoom_to_elements(uidoc, view, here, settings)


def view_frame(view):
    """The view's own origin, right, up and depth directions, as tuples.

    A view that will not report an origin still has directions, and the origin
    only sets where the frame is measured from - the answer comes back in model
    coordinates either way - so (0, 0, 0) is a safe stand in.
    """
    origin = (0.0, 0.0, 0.0)
    try:
        point = view.Origin
        origin = (point.X, point.Y, point.Z)
    except Exception:
        pass
    try:
        right = view.RightDirection
        up = view.UpDirection
        normal = view.ViewDirection
        return (origin,
                (right.X, right.Y, right.Z),
                (up.X, up.Y, up.Z),
                (normal.X, normal.Y, normal.Z))
    except Exception:
        # a plain world frame still zooms a plan correctly
        return (origin, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def find_ui_view(uidoc, view_id):
    try:
        for candidate in uidoc.GetOpenUIViews():
            if eid_value(candidate.ViewId) == eid_value(view_id):
                return candidate
    except Exception:
        pass
    return None


def read_zoom_corners(ui_view):
    """The rectangle the window is actually showing, in model coordinates."""
    try:
        corners = ui_view.GetZoomCorners()
    except Exception:
        return None
    try:
        points = [point for point in corners]
        if len(points) < 2:
            return None
        return ((points[0].X, points[0].Y, points[0].Z),
                (points[1].X, points[1].Y, points[1].Z))
    except Exception:
        return None


def check_zoom(ui_view, view, low, high):
    """Read the visible rectangle back and say whether it framed the selection.

    Revit does its own framing when it opens a window, and
    ZoomAndCenterRectangle raises nothing when it does not take - so a call
    that returned is not evidence that anything moved.
    """
    corners = read_zoom_corners(ui_view)
    if corners is None:
        return None, 'Revit would not report what the view is showing'
    origin, right, up, normal = view_frame(view)
    wanted_low = fiv_core.to_frame(low, origin, right, up, normal)
    wanted_high = fiv_core.to_frame(high, origin, right, up, normal)
    visible_low = fiv_core.to_frame(corners[0], origin, right, up, normal)
    visible_high = fiv_core.to_frame(corners[1], origin, right, up, normal)
    ok, reason = fiv_core.zoom_landed(wanted_low, wanted_high,
                                      visible_low, visible_high)
    return ok, reason


def zoom_to_elements(uidoc, view, elements, settings, tiling=False):
    """Fit the view around the elements, and check that it took.

    Tiling is posted rather than called, so it happens AFTER this zoom and the
    window it was measured for is about to shrink.  Revit keeps the centre and
    the scale through a resize, so the fix is to zoom wider than wanted by the
    tile allowance rather than to try to zoom afterwards - which would need an
    Idling handler and an engine that is still alive to service it.
    """
    box = elements_box(elements, view)
    if box is None:
        return False, 'Nothing in the selection had geometry to zoom to.'

    ui_view = find_ui_view(uidoc, view.Id)
    if ui_view is None:
        return False, ''

    origin, right, up, normal = view_frame(view)
    padding_pct = fiv_core.as_int(settings.get('zoom_padding_pct'), 15)
    if tiling:
        padding_pct += fiv_core.as_int(settings.get('tile_zoom_extra_pct'), 35)
    min_padding = fiv_core.mm_to_feet(
        fiv_core.as_int(settings.get('zoom_min_padding_mm'), 300))
    low, high = fiv_core.zoom_rectangle(box[0], box[1], origin, right, up, normal,
                                        padding_pct, min_padding)

    attempts = max(1, fiv_core.as_int(settings.get('zoom_attempts'), 3))
    reason = ''
    for attempt in range(attempts):
        try:
            ui_view.ZoomAndCenterRectangle(XYZ(low[0], low[1], low[2]),
                                           XYZ(high[0], high[1], high[2]))
        except Exception as error:
            return False, 'The zoom was refused: {0}'.format(error)

        landed, reason = check_zoom(ui_view, view, low, high)
        if landed is None:
            # nothing to check against, so one call is all there is
            return True, ''
        if landed:
            return True, ''

        # Revit framed the window itself after the call - most likely because
        # the window had only just been created.  Let it settle and go again.
        try:
            uidoc.RefreshActiveView()
        except Exception:
            pass
        ui_view = find_ui_view(uidoc, view.Id) or ui_view

    return False, ('The view opened but Revit would not hold the zoom: '
                   '{0}.').format(reason or 'the framing did not take')


def activate_and_zoom(uidoc, view, elements, element_ids, settings, uiapp=None,
                      host_view_id=None, category_ids=None):
    """Open the view, then fit it around the selected elements.

    Returns (ok, message).  Opening and zooming are separate concerns: a view
    that opens but will not zoom still leaves the user in the right place.
    """
    # The category has to be switched on BEFORE the view is activated: a
    # transaction has to be closed before the active view can change, so doing
    # it first is not a preference, it is the only order that works.
    notes = []
    if elements:
        try:
            notes, _mode = make_visible(uidoc.Document, view,
                                        category_ids or [], elements, settings)
        except Exception as error:
            notes = ['The view could not be changed: {0}'.format(error)]

    target_id = eid_value(view.Id)
    host_id = eid_value(host_view_id) if host_view_id is not None else None
    to_close, tile_mode = plan_tiling(read_window_rects(uidoc), host_id,
                                      target_id, settings)
    if to_close is not None:
        close_ui_view(uidoc, to_close)

    try:
        uidoc.ActiveView = view
    except Exception as error:
        return False, 'Revit would not open that view: {0}'.format(error)

    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass

    if fiv_core.as_bool(settings.get('reselect_after_zoom'), True):
        try:
            ids = List[ElementId]()
            for element_id in element_ids:
                ids.Add(element_id)
            uidoc.Selection.SetElementIds(ids)
        except Exception:
            pass

    retile = tile_mode == fiv_core.TILE_ALWAYS

    if not elements:
        # opened with nothing selected: there is nothing to frame, and saying
        # so would be reporting a problem that is not one
        if retile:
            post_tile_windows(uiapp)
        return True, ''

    missing = still_missing(uidoc.Document, view, element_ids, category_ids)
    if missing:
        notes.append(missing)

    zoomed, note = zoom_to_elements(uidoc, view, elements, settings, retile)

    if not zoomed and uiapp is not None:
        # Revit hands back a UIDocument whose open view list was built before
        # the view was activated, so the UIView for a view that was not already
        # open is missing from it.  Asking the application for the ACTIVE
        # UIDocument again is what picks the new one up.
        try:
            fresh = uiapp.ActiveUIDocument
        except Exception:
            fresh = None
        if fresh is not None:
            try:
                fresh.RefreshActiveView()
            except Exception:
                pass
            zoomed, note = zoom_to_elements(fresh, view, elements, settings, retile)
            if zoomed:
                uidoc = fresh

    if not zoomed:
        # ShowElements does its own zoom to fit around the elements and needs
        # no UIView, so it is a real fallback rather than a message.  It is
        # second choice because it decides the framing itself.
        try:
            ids = List[ElementId]()
            for element_id in element_ids:
                ids.Add(element_id)
            uidoc.ShowElements(ids)
            # ShowElements does its own fit around the elements; it decides the
            # framing itself, which is why it is the last resort rather than
            # the first move
            return True, ''
        except Exception:
            return True, note or 'Opened the view, but Revit would not zoom it.'

    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass

    if retile:
        tiled, report = post_tile_windows(uiapp)
        if not tiled and fiv_core.as_bool(settings.get('warn_tile_failure'), True):
            notes.append(tile_failure_message(report))
    return True, '\n\n'.join([note for note in notes if note])


def still_missing(doc, view, element_ids, category_ids=None):
    """Anything the view still will not draw, and the reasons worth naming."""
    drawn = drawn_in_view(doc, view, element_ids, category_ids)
    if drawn is None:
        return ''
    missing = len(element_ids) - len(drawn)
    if missing <= 0:
        return ''
    return ('{0} of the selection {1} still not drawn in this view. Switching '
            'the category on does not fix a view filter, the crop region, the '
            'phase, a closed workset, a design option or the view '
            'range.').format(missing, 'is' if missing == 1 else 'are')


def can_be_active(view):
    """Views Revit refuses as an active view are worth catching before Apply."""
    try:
        if view.IsTemplate:
            return False
    except Exception:
        return False
    try:
        if isinstance(view, ViewPlan) and view.GenLevel is None:
            # an area plan with no level still opens, so this is not a refusal
            return True
    except Exception:
        pass
    return True
