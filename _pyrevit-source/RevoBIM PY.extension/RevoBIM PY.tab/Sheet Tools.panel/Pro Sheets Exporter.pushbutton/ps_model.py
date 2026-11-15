# -*- coding: utf-8 -*-
"""Reading the model: sheets, views, their parameters and their paper sizes.

No WPF in here. The window asks this module for rows and parameter values and
gets plain Python objects back, which keeps the read testable and keeps the
grid from ever touching the Revit API on a background thread.

**Read in one pass, not per sheet.** The first honest version of a tool like
this runs a ``FilteredElementCollector`` per sheet for the title block, which
is fine on a demo model and unusable at four hundred sheets. Title blocks and
view scales are each one collector here, keyed by sheet id.
"""

import ps_refs  # noqa: F401  - must be first

import re

from System import Int32, Int64

from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, ElementId, FilteredElementCollector,
    PrintRange, StorageType, Transaction, ViewSet, ViewSheet, ViewSheetSet,
    View, ViewType,
)


# ==========================================================================
# small helpers that have caught this extension out before
# ==========================================================================

def eid_value(element_id):
    """The integer behind an ElementId, on every release 2024 to 2027.

    ``IntegerValue`` was deprecated in 2024 in favour of ``Value`` (Int64) and
    removed in 2026. Never touch either directly.
    """
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


def make_id(value):
    """An ElementId from a number, on every Revit 2021 to 2027.

    **Never** ``ElementId(some_int)``. From Revit 2026 ElementId's
    constructors take a BuiltInCategory, a BuiltInParameter or an Int64; a
    Python int converts to all three equally, and IronPython refuses to
    choose: "Multiple targets could match: ElementId(BuiltInParameter),
    ElementId(BuiltInCategory), ElementId(Int64)". That stopped Change
    revision on sheet dead in 1.39.0, and every Revision Manager write went
    through the same call. Say Int64 outright. Before 2024 there is no Int64
    overload, so fall back to Int32.
    """
    number = int(value)
    try:
        return ElementId(Int64(number))
    except Exception:
        return ElementId(Int32(number))


def to_text(value):
    if value is None:
        return u''
    try:
        return u'{0}'.format(value)
    except Exception:
        try:
            return unicode(value)  # noqa: F821  - IronPython 2.7
        except Exception:
            return u''


def natural_key(text):
    """Sort key giving P-9 before P-10, which plain string order does not."""
    parts = re.split(r'(\d+)', to_text(text))
    key = []
    for part in parts:
        if part.isdigit():
            key.append((1, int(part), u''))
        else:
            key.append((0, 0, part.lower()))
    return key


# ==========================================================================
# parameter reading
# ==========================================================================

def param_text(element, name):
    """A parameter's value as display text, by every route that might work.

    ``GetParameters`` and ``LookupParameter`` do not always hand back the same
    object, and a shared parameter that is missing on one element is present
    on the next, so both are tried and neither is trusted to raise.
    """
    if element is None or not name:
        return u''
    param = None
    try:
        found = element.GetParameters(name)
        if found and found.Count > 0:
            param = found[0]
    except Exception:
        param = None
    if param is None:
        try:
            param = element.LookupParameter(name)
        except Exception:
            param = None
    if param is None:
        return u''
    return param_value_text(param)


def param_value_text(param):
    """One parameter turned into the text a file name should use."""
    if param is None:
        return u''
    try:
        if not param.HasValue:
            return u''
    except Exception:
        pass
    try:
        storage = param.StorageType
    except Exception:
        storage = None
    try:
        if storage == StorageType.String:
            return to_text(param.AsString() or u'')
        if storage == StorageType.Integer:
            shown = param.AsValueString()
            if shown:
                return to_text(shown)
            return to_text(param.AsInteger())
        if storage == StorageType.Double:
            shown = param.AsValueString()
            if shown:
                return to_text(shown)
            return to_text(param.AsDouble())
        if storage == StorageType.ElementId:
            shown = param.AsValueString()
            if shown:
                return to_text(shown)
            return to_text(eid_value(param.AsElementId()))
    except Exception:
        pass
    try:
        return to_text(param.AsString() or param.AsValueString() or u'')
    except Exception:
        return u''


def parameter_names(element):
    """Every readable parameter name on an element, deduplicated."""
    names = set()
    try:
        for param in element.Parameters:
            try:
                definition = param.Definition
                if definition is not None and definition.Name:
                    names.add(to_text(definition.Name))
            except Exception:
                continue
    except Exception:
        pass
    return names


# ==========================================================================
# paper sizes
# ==========================================================================

# Nominal ISO sizes in millimetres, short edge first, largest first so that
# "the smallest one that fits" can walk the list backwards.
ISO_SIZES = [
    ('A0', 841.0, 1189.0),
    ('A1', 594.0, 841.0),
    ('A2', 420.0, 594.0),
    ('A3', 297.0, 420.0),
    ('A4', 210.0, 297.0),
    ('A5', 148.0, 210.0),
    ('A6', 105.0, 148.0),
]

FEET_TO_MM = 304.8

# How far a title block may be off nominal and still count as that size.
# Title blocks are routinely drawn a millimetre or two under so the border
# does not sit on the paper edge, and a few are drawn to an old imperial
# equivalent, so this is deliberately generous.
SIZE_TOLERANCE_MM = 8.0

LANDSCAPE = 'landscape'
PORTRAIT = 'portrait'


def match_iso(width_mm, height_mm, tolerance=SIZE_TOLERANCE_MM):
    """The ISO name for a sheet of this size, or None where nothing fits."""
    try:
        short = min(float(width_mm), float(height_mm))
        long_edge = max(float(width_mm), float(height_mm))
    except Exception:
        return None
    for name, iso_short, iso_long in ISO_SIZES:
        if (abs(short - iso_short) <= tolerance
                and abs(long_edge - iso_long) <= tolerance):
            return name
    return None


def smallest_containing(width_mm, height_mm, tolerance=SIZE_TOLERANCE_MM):
    """The smallest standard size this sheet fits inside.

    For the title blocks that are not a standard size at all - and there is
    usually at least one per office, a cut-down sheet for schematics - the
    honest answer is the smallest standard paper the drawing fits on. Sizing
    it down would clip the sheet, and defaulting to A0 would waste most of
    the page, so neither of those is a kindness.
    """
    try:
        short = min(float(width_mm), float(height_mm))
        long_edge = max(float(width_mm), float(height_mm))
    except Exception:
        return None
    if short <= 0 or long_edge <= 0:
        return None
    best = None
    for name, iso_short, iso_long in ISO_SIZES:
        if (short <= iso_short + tolerance
                and long_edge <= iso_long + tolerance):
            # The list runs largest first, so every later hit is smaller.
            best = name
    return best


def size_from_name(text):
    """An A-size read out of a family or type name, where one is spelled out."""
    match = re.search(r'\bA([0-6])\b', to_text(text).upper())
    if match:
        return 'A' + match.group(1)
    return None


def iso_dimensions(name):
    """(short, long) in mm for an A-size name, or None."""
    wanted = to_text(name).strip().upper()
    for iso_name, short, long_edge in ISO_SIZES:
        if iso_name == wanted:
            return (short, long_edge)
    return None


class SheetSize(object):
    """What paper a sheet wants, which way round, and how sure we are."""

    __slots__ = ('name', 'width_mm', 'height_mm', 'landscape', 'source',
                 'exact')

    def __init__(self, name=u'', width_mm=0.0, height_mm=0.0,
                 landscape=True, source=u'', exact=True):
        self.name = name
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.landscape = landscape
        self.source = source
        # False where the sheet is not a standard size and has been fitted
        # up to the next one. Worth telling the user about rather than
        # quietly rounding their paper.
        self.exact = exact

    def orientation(self):
        return LANDSCAPE if self.landscape else PORTRAIT

    def label(self):
        """What the Size column shows: "A1 landscape"."""
        if self.name:
            text = u'{0} {1}'.format(self.name, self.orientation())
            return text if self.exact else text + u' (fitted)'
        if self.width_mm and self.height_mm:
            return u'{0:.0f} x {1:.0f} mm'.format(float(self.width_mm),
                                                  float(self.height_mm))
        return u'?'

    def describe(self):
        """A fuller line for the debug log and the report."""
        if not self.name:
            return self.label()
        return u'{0} {1} from {2} ({3:.0f} x {4:.0f} mm{5})'.format(
            self.name, self.orientation(), self.source or u'?',
            float(self.width_mm), float(self.height_mm),
            u'' if self.exact else u', fitted up from a non-standard sheet')


def title_block_parameter_names(doc, sample=10):
    """Every parameter name on the title blocks placed on sheets - read from
    a few, since a family carries the same parameters wherever it sits."""
    names = set()
    try:
        blocks = list(read_title_blocks(doc).values())[:sample]
    except Exception:
        blocks = []
    for block in blocks:
        names |= parameter_names(block)
    return sorted(names, key=lambda one: one.lower())


def read_title_blocks(doc):
    """Every title block instance in the model, keyed by the sheet it is on.

    One collector for the whole model. Where a sheet somehow carries more than
    one title block the largest wins, since that is the one defining the paper.
    """
    by_sheet = {}
    try:
        collector = (FilteredElementCollector(doc)
                     .OfCategory(BuiltInCategory.OST_TitleBlocks)
                     .WhereElementIsNotElementType())
        for block in collector:
            try:
                owner = eid_value(block.OwnerViewId)
            except Exception:
                continue
            if not owner:
                continue
            existing = by_sheet.get(owner)
            if existing is None:
                by_sheet[owner] = block
                continue
            try:
                if _block_area(block) > _block_area(existing):
                    by_sheet[owner] = block
            except Exception:
                pass
    except Exception:
        pass
    return by_sheet


def _block_param(block, built_in):
    try:
        param = block.get_Parameter(built_in)
        if param is not None and param.HasValue:
            return float(param.AsDouble())
    except Exception:
        pass
    return 0.0


def _block_area(block):
    return (_block_param(block, BuiltInParameter.SHEET_WIDTH)
            * _block_param(block, BuiltInParameter.SHEET_HEIGHT))


def sheet_size(doc, sheet, title_block, override_text=u''):
    """The paper a sheet wants, worked out from its own extents.

    The order is deliberate. The title block's own width and height are the
    truth about how big the drawing is, so geometry is tried before any name:
    a title block called "A1" that has been stretched is an A0 print, and the
    name would have lied about it.

    1. an explicit parameter override, where the office nominates one
    2. the extents, matched against a standard size
    3. the extents, fitted up to the smallest standard size that contains
       them, for the cut-down sheets every office has
    4. an A-size spelled out in the title block type name
    5. the bare millimetres

    Orientation always comes from the extents, never from the name.
    """
    width_mm = height_mm = 0.0
    if title_block is not None:
        width_mm = _block_param(title_block, BuiltInParameter.SHEET_WIDTH) * FEET_TO_MM
        height_mm = _block_param(title_block, BuiltInParameter.SHEET_HEIGHT) * FEET_TO_MM

    landscape = (width_mm >= height_mm) if (width_mm and height_mm) else True

    if override_text:
        named = size_from_name(override_text) or to_text(override_text).strip()
        # A nominated size still takes its orientation from the sheet, and
        # its nominal millimetres from the standard, so the driver gets a
        # sensible page even where the model has no title block.
        dims = iso_dimensions(named)
        if dims and not (width_mm and height_mm):
            short, long_edge = dims
            width_mm, height_mm = ((long_edge, short) if landscape
                                   else (short, long_edge))
        return SheetSize(named, width_mm, height_mm, landscape,
                         u'the nominated parameter', True)

    if width_mm and height_mm:
        exact = match_iso(width_mm, height_mm)
        if exact:
            return SheetSize(exact, width_mm, height_mm, landscape,
                             u'the sheet extents', True)
        fitted = smallest_containing(width_mm, height_mm)
        if fitted:
            return SheetSize(fitted, width_mm, height_mm, landscape,
                             u'the sheet extents', False)

    type_name = u''
    if title_block is not None:
        try:
            symbol = doc.GetElement(title_block.GetTypeId())
            if symbol is not None:
                type_name = to_text(
                    symbol.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString())
        except Exception:
            type_name = u''
    if not type_name and title_block is not None:
        try:
            type_name = to_text(title_block.Name)
        except Exception:
            type_name = u''

    named = size_from_name(type_name)
    if named:
        return SheetSize(named, width_mm, height_mm, landscape,
                         u'the title block name', True)
    if width_mm and height_mm:
        return SheetSize(u'', width_mm, height_mm, landscape,
                         u'the sheet extents', True)
    return SheetSize(u'', 0.0, 0.0, True, u'nothing to go on', True)


# ==========================================================================
# rows
# ==========================================================================

class Row(object):
    """One sheet or one view, as the grid and the exporter both see it."""

    def __init__(self, element, is_sheet):
        self.element = element
        self.is_sheet = is_sheet
        self.element_id = element.Id
        self.key = eid_value(element.Id)
        self.checked = False
        self.number = u''
        self.name = u''
        self.revision = u''
        self.size = u''
        self.size_info = None
        self.view_type = u''
        self.custom_name = u''
        self.folder = u''
        self.is_placeholder = False
        self.on_sheet_list = True
        self.sets = []

    def sort_key(self):
        return natural_key(self.number or self.name)


def read_rows(doc, mode='sheets', size_param=u''):
    """Every sheet (or every printable view) in the model, as Row objects."""
    rows = []
    if mode == 'views':
        rows = _read_views(doc)
    else:
        rows = _read_sheets(doc, size_param)
    rows.sort(key=lambda r: r.sort_key())
    return rows


def _read_sheets(doc, size_param=u''):
    blocks = read_title_blocks(doc)
    rows = []
    try:
        collector = (FilteredElementCollector(doc)
                     .OfClass(ViewSheet)
                     .WhereElementIsNotElementType())
    except Exception:
        return rows
    for sheet in collector:
        try:
            if getattr(sheet, 'IsTemplate', False):
                continue
        except Exception:
            pass
        row = Row(sheet, True)
        try:
            row.number = to_text(sheet.SheetNumber)
        except Exception:
            row.number = u''
        try:
            row.name = to_text(sheet.Name)
        except Exception:
            row.name = u''
        try:
            row.is_placeholder = bool(sheet.IsPlaceholder)
        except Exception:
            row.is_placeholder = False
        try:
            param = sheet.get_Parameter(BuiltInParameter.SHEET_SCHEDULED)
            row.on_sheet_list = bool(param.AsInteger()) if param is not None else True
        except Exception:
            row.on_sheet_list = True

        row.revision = current_revision_text(doc, sheet)

        override = param_text(sheet, size_param) if size_param else u''
        info = sheet_size(doc, sheet, blocks.get(row.key), override)
        row.size_info = info
        row.size = info.label()
        rows.append(row)
    return rows


# View types that cannot be printed or exported on their own.
_SKIP_VIEW_TYPES = set()
for _name in ('ProjectBrowser', 'SystemBrowser', 'Undefined', 'Internal',
              'DrawingSheet', 'Schedule', 'ColumnSchedule',
              'PanelSchedule', 'Report'):
    try:
        _SKIP_VIEW_TYPES.add(getattr(ViewType, _name))
    except Exception:
        continue


def _read_views(doc):
    rows = []
    try:
        collector = (FilteredElementCollector(doc)
                     .OfClass(View)
                     .WhereElementIsNotElementType())
    except Exception:
        return rows
    for view in collector:
        try:
            if view.IsTemplate:
                continue
        except Exception:
            continue
        try:
            if view.ViewType in _SKIP_VIEW_TYPES:
                continue
        except Exception:
            pass
        try:
            if not view.CanBePrinted:
                continue
        except Exception:
            pass
        row = Row(view, False)
        try:
            row.name = to_text(view.Name)
        except Exception:
            row.name = u''
        try:
            row.view_type = to_text(view.ViewType)
        except Exception:
            row.view_type = u''
        row.number = row.view_type
        row.size = u''
        row.size_info = SheetSize()
        rows.append(row)
    return rows


# The column a view's own type is read into - the folders Revit's Project
# Browser always puts views in under any organisation's own folders
# (Floor Plans, Sections...).
VIEW_TYPE_COLUMN = u'View Type'

# How many views are asked for their folders. An organisation groups every
# view by the same parameters, so a handful tells you all of it.
BROWSER_SAMPLE = 40


def browser_levels(samples):
    """The folder levels of an organisation, top first, from what a few
    views reported - [[level 1 name, level 2 name...], ...]. A view with
    no value for a level reports fewer, so each depth takes the first name
    any view gave it."""
    levels = []
    for names in samples or []:
        for depth, name in enumerate(names or []):
            while len(levels) <= depth:
                levels.append(u'')
            name = to_text(name).strip()
            if name and not levels[depth]:
                levels[depth] = name
    found = []
    for name in levels:
        if name and name not in found:
            found.append(name)
    return found


def browser_columns(levels):
    """The columns the Views list starts with, as Revit's Project Browser
    shows them: the organisation's folder parameters top first, then the
    view type. Each once."""
    found = []
    for name in list(levels or []) + [VIEW_TYPE_COLUMN]:
        name = to_text(name).strip()
        if name and name not in found:
            found.append(name)
    return found


def _parameter_name(doc, view, parameter_id):
    """A folder's grouping parameter by name: from the view's own
    parameters first (built-in ones have no element), then the project's
    parameter element."""
    wanted = eid_value(parameter_id)
    try:
        for parameter in view.Parameters:
            try:
                if eid_value(parameter.Id) == wanted:
                    return to_text(parameter.Definition.Name)
            except Exception:
                continue
    except Exception:
        pass
    try:
        element = doc.GetElement(parameter_id)
        if element is not None:
            return to_text(element.Name)
    except Exception:
        pass
    return u''


def browser_folder_parameters(doc, rows):
    """The parameter names the project's current browser organisation for
    views groups by, top first - [] when it groups by nothing, or the
    Revit in use cannot say."""
    try:
        from Autodesk.Revit.DB import BrowserOrganization
    except Exception:
        return []
    try:
        organisation = \
            BrowserOrganization.GetCurrentBrowserOrganizationForViews(doc)
    except Exception:
        return []
    if organisation is None:
        return []
    samples = []
    for row in list(rows or [])[:BROWSER_SAMPLE]:
        view = getattr(row, 'element', None)
        if view is None:
            continue
        try:
            items = organisation.GetFolderItems(view.Id)
        except Exception:
            continue
        names = []
        try:
            for item in items:
                names.append(_parameter_name(doc, view, item.ElementId))
        except Exception:
            continue
        if names:
            samples.append(names)
    return browser_levels(samples)


def is_three_d(row):

    """Whether a row is a 3D view, which is what NWC and IFC need.

    ``ViewType.ThreeD`` covers both the default {3D} and any named
    perspective or isometric. A sheet is never one, whatever it holds.
    """
    if row is None or getattr(row, 'is_sheet', True):
        return False
    try:
        return row.element.ViewType == ViewType.ThreeD
    except Exception:
        pass
    # A release that renames the member should not silently answer "no".
    return u'{0}'.format(getattr(row, 'view_type', u'')).lower() == 'threed'


def read_phases(doc):
    """Every phase in the model as {name: element id text}.

    The name is what a template stores, because an id from another model
    points at whatever happens to share that number. The id is what the
    IFC exporter's ActivePhaseId option wants.
    """
    found = {}
    try:
        for phase in doc.Phases:
            try:
                found[to_text(phase.Name)] = u'{0}'.format(
                    eid_value(phase.Id))
            except Exception:
                continue
    except Exception:
        pass
    return found


# ==========================================================================
# revisions
# ==========================================================================

def current_revision_text(doc, sheet):
    """The revision number the sheet itself shows, not the project-wide one.

    ``Revision.RevisionNumber`` is the project-wide number, deprecated since
    2022 and gone in later releases. ``GetRevisionNumberOnSheet`` reports
    exactly what the sheet's own revision schedule shows, which is the only
    answer that can agree with the drawing.
    """
    try:
        current = sheet.GetCurrentRevision()
    except Exception:
        return u''
    if current is None or eid_value(current) <= 0:
        return u''
    try:
        shown = sheet.GetRevisionNumberOnSheet(current)
        if shown:
            return to_text(shown)
    except Exception:
        pass
    try:
        revision = doc.GetElement(current)
        if revision is not None:
            return to_text(getattr(revision, 'SequenceNumber', u''))
    except Exception:
        pass
    return u''


def current_revision_field(doc, sheet, field):
    """Description, date or issued-by for the sheet's current revision."""
    try:
        current = sheet.GetCurrentRevision()
        if current is None or eid_value(current) <= 0:
            return u''
        revision = doc.GetElement(current)
        if revision is None:
            return u''
        return to_text(getattr(revision, field, u''))
    except Exception:
        return u''


# ==========================================================================
# view / sheet sets
# ==========================================================================

def read_sheet_sets(doc):
    """Every saved View/Sheet Set, as {name: set of element id integers}."""
    sets = {}
    try:
        collector = (FilteredElementCollector(doc)
                     .OfClass(ViewSheetSet)
                     .WhereElementIsNotElementType())
    except Exception:
        return sets
    for entry in collector:
        try:
            name = to_text(entry.Name)
        except Exception:
            continue
        members = set()
        try:
            for view in entry.Views:
                members.add(eid_value(view.Id))
        except Exception:
            pass
        sets[name] = members
    return sets


def find_view_sheet_set(doc, name):
    """The saved View/Sheet Set called ``name``, or None."""
    wanted = to_text(name)
    try:
        collector = (FilteredElementCollector(doc)
                     .OfClass(ViewSheetSet)
                     .WhereElementIsNotElementType())
    except Exception:
        return None
    for entry in collector:
        try:
            if to_text(entry.Name) == wanted:
                return entry
        except Exception:
            continue
    return None


def save_view_sheet_set(doc, name, sheets, keep_other_views=True):
    """Write a View/Sheet Set: update it where it exists, make it where not.

    (ok, message). Opens and closes its own transaction, so the caller
    must hold none.

    Three things the 1.20.0 version got wrong, and all three fail quietly:

    - ``ViewSheetSetting`` is only usable with the print range on
      *Select*. Left on Current Window or Visible Portion - Revit's default -
      it throws, which read as "the set could not be saved" with nothing
      to say why.
    - Updating an existing set means making it the *current* set first and
      then calling ``Save``. ``SaveAs`` with a name that is already taken
      throws, and falling back to ``Save`` without switching sets saved the
      ticked sheets over whichever set happened to be current.
    - A set can hold views as well as sheets. The register only manages
      sheets, so the views already in the set are kept unless asked not to.
    """
    name = to_text(name).strip()
    if not name:
        return False, u'The set needs a name.'
    sheets = [sheet for sheet in (sheets or []) if sheet is not None]
    if not sheets:
        return False, (u'A View/Sheet Set cannot be empty - tick at least one '
                       u'sheet.')

    existing = find_view_sheet_set(doc, name)
    views = list(sheets)
    if existing is not None and keep_other_views:
        try:
            for view in existing.Views:
                if not isinstance(view, ViewSheet):
                    views.append(view)
        except Exception:
            pass

    transaction = Transaction(doc, u'RevoBIM save View/Sheet Set')
    try:
        transaction.Start()
        manager = doc.PrintManager
        manager.PrintRange = PrintRange.Select
        setting = manager.ViewSheetSetting
        if existing is not None:
            setting.CurrentViewSheetSet = existing
        view_set = ViewSet()
        for view in views:
            view_set.Insert(view)
        setting.CurrentViewSheetSet.Views = view_set
        if existing is not None:
            setting.Save()
        else:
            setting.SaveAs(name)
        transaction.Commit()
    except Exception as err:
        try:
            transaction.RollBack()
        except Exception:
            pass
        return False, u'The set "{0}" could not be saved: {1}'.format(name, err)
    return True, u'View/Sheet Set "{0}" {1} with {2} sheet{3}.'.format(
        name, u'updated' if existing is not None else u'created',
        len(sheets), u'' if len(sheets) == 1 else u's')


def tag_rows_with_sets(rows, sets):
    """Write onto each row which saved sets it belongs to."""
    for row in rows:
        row.sets = sorted([name for name, members in sets.items()
                           if row.key in members])
    return rows


# ==========================================================================
# the parameter catalogue for the Custom File Name dialog
# ==========================================================================

# Values the tool works out rather than reading off an element. Keeping them
# in the same list as real parameters means the naming dialog has one idea of
# what a "parameter" is, and the user does not have to know the difference.
DERIVED = [
    (u'Sheet Number', u'Sheet'),
    (u'Sheet Name', u'Sheet'),
    (u'Sheet Size', u'Sheet'),
    (u'Sheet Orientation', u'Sheet'),
    (u'Current Revision', u'Revision'),
    (u'Current Revision Date', u'Revision'),
    (u'Current Revision Description', u'Revision'),
    (u'Current Revision Issued By', u'Revision'),
    (u'Current Revision Issued To', u'Revision'),
    (u'View Name', u'View'),
    (u'View Type', u'View'),
    (u'Project File Name', u'Project'),
    (u'Export Date', u'Export'),
    (u'Export Time', u'Export'),
    (u'User Name', u'Export'),
]

DERIVED_NAMES = set([name for name, _group in DERIVED])


def project_info(doc):
    try:
        return doc.ProjectInformation
    except Exception:
        return None


def parameter_catalogue(doc, rows):
    """Every parameter the naming dialog can offer, as (name, group) pairs.

    Sampled from the first few sheets rather than all of them - shared
    parameters are applied by category, so twenty sheets tell you everything
    four hundred would, and the dialog opens instantly instead of after a
    pause nobody expects from a dropdown.
    """
    groups = {}
    for name, group in DERIVED:
        groups[name] = group

    sample = [row for row in rows[:20] if row.element is not None]
    for row in sample:
        for name in parameter_names(row.element):
            if name not in groups:
                groups[name] = u'Sheet' if row.is_sheet else u'View'

    info = project_info(doc)
    if info is not None:
        for name in parameter_names(info):
            # A project parameter wins the label, since that is where the user
            # will look for it, but it must not displace a sheet parameter of
            # the same name.
            if name not in groups:
                groups[name] = u'Project'

    pairs = [(name, groups[name]) for name in groups.keys()]
    pairs.sort(key=lambda pair: natural_key(pair[0]))
    return pairs


def catalogue_groups(pairs):
    """The dropdown contents: All, then each group that actually has members."""
    seen = []
    for _name, group in pairs:
        if group not in seen:
            seen.append(group)
    seen.sort()
    return [u'All'] + seen


# ==========================================================================
# the lookup a row hands to the naming and path engines
# ==========================================================================

class RowLookup(object):
    """Resolve a parameter name against one row, then the project.

    Order matters and is deliberate: the element first, because a sheet
    parameter and a project parameter can share a name and the sheet's is the
    one that varies per file; then project information; then the derived
    values the tool computes itself.
    """

    def __init__(self, doc, row, export_stamp=None, user_name=u''):
        self.doc = doc
        self.row = row
        self.stamp = export_stamp
        self.user_name = user_name
        self._cache = {}

    def __call__(self, name):
        name = to_text(name).strip()
        if not name:
            return u''
        if name in self._cache:
            return self._cache[name]
        value = self._resolve(name)
        self._cache[name] = value
        return value

    def _resolve(self, name):
        row = self.row
        element = row.element if row is not None else None

        if element is not None:
            found = param_text(element, name)
            if found:
                return found

        info = project_info(self.doc)
        if info is not None:
            found = param_text(info, name)
            if found:
                return found

        return self._derived(name)

    def _derived(self, name):
        row = self.row
        doc = self.doc
        if name == u'Sheet Number':
            return row.number if row is not None else u''
        if name in (u'Sheet Name', u'View Name'):
            return row.name if row is not None else u''
        if name == u'Sheet Size':
            # The bare size, not the Size column's label. The column says
            # "A1 landscape" to be useful to read; a file name that suddenly
            # gained " landscape" because the column got chattier would be a
            # nasty surprise on a re-issue.
            if row is None or row.size_info is None:
                return u''
            return to_text(row.size_info.name)
        if name == u'Sheet Orientation':
            if row is None or row.size_info is None:
                return u''
            return to_text(row.size_info.orientation())
        if name == u'View Type':
            return row.view_type if row is not None else u''
        if name == u'Current Revision':
            return row.revision if row is not None else u''
        if name.startswith(u'Current Revision ') and row is not None and row.is_sheet:
            field = {
                u'Current Revision Date': 'RevisionDate',
                u'Current Revision Description': 'Description',
                u'Current Revision Issued By': 'IssuedBy',
                u'Current Revision Issued To': 'IssuedTo',
            }.get(name)
            if field:
                return current_revision_field(doc, row.element, field)
        if name == u'Project File Name':
            try:
                import os
                path = to_text(getattr(doc, 'PathName', u''))
                if path:
                    return os.path.splitext(os.path.basename(path))[0]
                return to_text(getattr(doc, 'Title', u''))
            except Exception:
                return u''
        if name == u'Export Date' and self.stamp is not None:
            return self.stamp[0]
        if name == u'Export Time' and self.stamp is not None:
            return self.stamp[1]
        if name == u'User Name':
            return self.user_name
        return u''


def export_stamp():
    """Today's date and the time now, as (date, time) in file-safe form."""
    try:
        from System import DateTime
        now = DateTime.Now
        return (to_text(now.ToString('yyyy-MM-dd')),
                to_text(now.ToString('HHmm')))
    except Exception:
        return (u'', u'')


def current_user(app):
    try:
        return to_text(app.Username)
    except Exception:
        pass
    try:
        from System import Environment
        return to_text(Environment.UserName)
    except Exception:
        return u''


def preselected_rows(uidoc, rows):
    """Which rows were already selected in Revit when the tool opened.

    Returns the subset of rows whose element the user had picked, so the first
    page can isolate to exactly those. An empty answer means nothing relevant
    was selected and the full list should stand.
    """
    picked = set()
    ids = []
    try:
        for element_id in uidoc.Selection.GetElementIds():
            ids.append(element_id)
            picked.add(eid_value(element_id))
    except Exception:
        return []
    if not picked:
        return []

    matched = [row for row in rows if row.key in picked]
    if matched:
        return matched

    # Nothing in the selection is a sheet, but the selected elements may sit
    # on sheets - taking their owning sheets is what the user meant. Walk the
    # ElementId objects themselves rather than rebuilding them from integers:
    # ElementId's constructor takes an Int64 from 2026 and an int before that,
    # and which overload IronPython picks is not worth depending on.
    owners = set()
    try:
        doc = uidoc.Document
        for element_id in ids:
            element = doc.GetElement(element_id)
            if element is None:
                continue
            owner = eid_value(getattr(element, 'OwnerViewId', None))
            if owner:
                owners.add(owner)
    except Exception:
        pass
    if not owners:
        return []
    return [row for row in rows if row.key in owners]
