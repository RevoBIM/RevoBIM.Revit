# -*- coding: utf-8 -*-

"""Legend Creator - writing the legends.

Legend views, components, filled region types, line styles and patterns,
swatches and text; the quiet transactions and dialog suppression around them;
opening the result and finding it in the Project Browser.
"""

from pyrevit import DB, forms, revit

import lgc_clr  # noqa: F401 - references first, before any System import
from System.Collections.Generic import List

from lgc_logic import (CENTRELINE_NAME, CENTRELINE_OVERHANG,
                       CENTRELINE_PATTERN_NAME, CENTRELINE_RGB,
                       CENTRELINE_SEGMENTS, CLEARABLE_CATEGORIES,
                       COMBINED_NAME, DEFAULT_LINE_WEIGHT, VIEW_PREFIX,
                       apply_case, channel, clamp_weight, safe_style_name,
                       to_internal, unique_view_name)
from lgc_core import eid_value, err_text, log, swallowed
from lgc_model import (category_id_set, element_name, family_type_label,
                       param_text)

# The active document, bound by lgc_app.bind_document() at the start of every
# run - never captured at import, which pyRevit may cache across runs and
# models.
doc = None


# Revit's own dialogs are answered for the duration of a run, and warnings
# deleted, so the only thing the user sees afterwards is the summary window.
_DIALOGS = {'hooked': False, 'active': False, 'seen': []}


def _on_dialog(sender, args):
    """Answer whatever Revit raises mid-run, and note what it was."""
    if not _DIALOGS['active']:
        return
    try:
        _DIALOGS['seen'].append(u'{0}'.format(args.DialogId))
    except Exception:
        swallowed()
    for result in (1, 6, 2):          # OK, Yes, Cancel - first that is taken
        try:
            args.OverrideResult(result)
            return
        except Exception:
            swallowed()
            continue


def suppress_dialogs(on):
    """Hook once and switch with a flag.

    Unsubscribing an IronPython bound method from a .NET event is not
    reliable - each attribute access makes a fresh delegate - so the handler
    stays attached for the session and the flag decides whether it acts.
    """
    if on and not _DIALOGS['hooked']:
        try:
            from pyrevit import HOST_APP
            HOST_APP.uiapp.DialogBoxShowing += _on_dialog
            _DIALOGS['hooked'] = True
        except Exception:
            swallowed()
    _DIALOGS['active'] = bool(on)
    if on:
        _DIALOGS['seen'] = []


class WarningSwallower(DB.IFailuresPreprocessor):
    """Deletes warnings so none of them stops to ask."""

    def PreprocessFailures(self, accessor):
        try:
            accessor.DeleteAllWarnings()
        except Exception:
            swallowed()
        return DB.FailureProcessingResult.Continue


def quiet_transaction(trans):
    try:
        options = trans.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        trans.SetFailureHandlingOptions(options)
    except Exception:
        swallowed()
    return trans


# ---------------------------------------------------------------------------
# Legend construction
# ---------------------------------------------------------------------------
def clear_legend(view):
    """Delete the drafting content a duplicated legend inherited.

    Deliberately narrow. Never touches the view, its SketchPlane, or anything
    without a category - a view-scoped collector returns those too, and
    deleting the work plane corrupts the view badly enough to crash Revit
    at native level the next time an element is created in it.
    """
    allowed = category_id_set(CLEARABLE_CATEGORIES)
    victims = List[DB.ElementId]()

    for element in DB.FilteredElementCollector(doc, view.Id)\
                     .WhereElementIsNotElementType():
        if element is None or element.Id == view.Id:
            continue
        if isinstance(element, DB.View) or isinstance(element, DB.SketchPlane):
            continue
        try:
            if not element.ViewSpecific or element.OwnerViewId != view.Id:
                continue
        except Exception:
            swallowed()
            continue
        category = element.Category
        if category is None or eid_value(category.Id) not in allowed:
            continue
        victims.Add(element.Id)

    if victims.Count:
        try:
            doc.Delete(victims)
        except Exception:
            swallowed()


def clone_component(seed_view, seed_component, target_view):
    ids = List[DB.ElementId]()
    ids.Add(seed_component.Id)
    copied = DB.ElementTransformUtils.CopyElements(
        seed_view, ids, target_view, DB.Transform.Identity,
        DB.CopyPasteOptions())
    for new_id in copied:
        return doc.GetElement(new_id)
    return None


def place_component(seed_view, seed_component, view, type_id,
                    x_position, y_position):
    """Clone a legend component, point it at type_id, centre it on x, y."""
    component = clone_component(seed_view, seed_component, view)
    if component is None:
        return None

    param = component.get_Parameter(DB.BuiltInParameter.LEGEND_COMPONENT)
    if param is None or param.IsReadOnly:
        doc.Delete(component.Id)
        return None
    param.Set(type_id)
    doc.Regenerate()

    box = component.get_BoundingBox(view)
    if box:
        centre_x = (box.Min.X + box.Max.X) / 2.0
        centre_y = (box.Min.Y + box.Max.Y) / 2.0
    else:
        centre_x = centre_y = 0.0

    DB.ElementTransformUtils.MoveElement(
        doc, component.Id,
        DB.XYZ(x_position - centre_x, y_position - centre_y, 0.0))
    return component


def make_legend_view(seed_view, name, taken, scale):
    """Duplicate the seed legend, rename it, scale it, and empty it."""
    option = DB.ViewDuplicateOption.Duplicate
    if not seed_view.CanViewBeDuplicated(option):
        return None

    view = doc.GetElement(seed_view.Duplicate(option))
    try:
        view.Name = unique_view_name(name, taken)
    except Exception:
        try:
            DB.Element.Name.SetValue(view, unique_view_name(name, taken))
        except Exception:
            swallowed()
    try:
        view.Scale = int(scale)
    except Exception:
        swallowed()

    clear_legend(view)
    return view


def populate_legend(view, infos, seed_view, seed_component, opts):
    """Fill a legend with one column per CategoryInfo.

    Returns (placed count, list of (label, reason) skipped).
    """
    spacing = to_internal(opts['row_spacing'])
    offset = to_internal(opts['text_offset'])
    column_gap = to_internal(opts['column_spacing'])

    skipped = []
    columns = []          # [(column_x, [(component, y, text)])]

    for column_index, info in enumerate(infos):
        column_x = column_gap * column_index
        placed = []
        row = 0
        for type_id in info.type_ids:
            element_type = doc.GetElement(type_id)
            if element_type is None:
                continue
            label = family_type_label(element_type)
            try:
                component = place_component(seed_view, seed_component, view,
                                            type_id, column_x, -spacing * row)
            except Exception as err:
                skipped.append((label, err_text(err)))
                continue
            if component is None:
                skipped.append(
                    (label, 'type cannot be shown as a legend component'))
                continue

            text = apply_case(param_text(element_type, opts['name_param']),
                              opts['text_case'])
            placed.append((component, -spacing * row, text))
            row += 1
        columns.append((column_x, placed))

    doc.Regenerate()

    total = 0
    for column_x, placed in columns:
        if not placed:
            continue
        total += len(placed)

        # One text column per category, measured off the widest component in
        # that column so the labels line up instead of running ragged.
        text_x = column_x
        for component, _y, _text in placed:
            box = component.get_BoundingBox(view)
            if box:
                text_x = max(text_x, box.Max.X)
        text_x += offset

        for component, y_position, text in placed:
            options = DB.TextNoteOptions(opts['text_type_id'])
            options.HorizontalAlignment = DB.HorizontalTextAlignment.Left
            try:
                options.VerticalAlignment = DB.VerticalTextAlignment.Middle
            except Exception:
                swallowed()
            DB.TextNote.Create(doc, view.Id,
                               DB.XYZ(text_x, y_position, 0.0),
                               text, options)

    return total, skipped


def solid_fill_pattern_id():
    for pattern in DB.FilteredElementCollector(doc)\
                     .OfClass(DB.FillPatternElement):
        try:
            fill = pattern.GetFillPattern()
            if fill.IsSolidFill:
                return pattern.Id
        except Exception:
            swallowed()
            continue
    return None


def usable_pattern_id(pattern_id, fallback_id):
    """A filled region wants a drafting pattern. A filter may hand back a
    model one, which Revit refuses, so it is checked before being used."""
    if pattern_id is None:
        return fallback_id
    pattern = doc.GetElement(pattern_id)
    if pattern is None:
        return fallback_id
    try:
        fill = pattern.GetFillPattern()
        if fill.Target == DB.FillPatternTarget.Drafting:
            return pattern_id
    except Exception:
        swallowed()
    return fallback_id


def find_filled_region_type(name):
    for region_type in DB.FilteredElementCollector(doc)\
                         .OfClass(DB.FilledRegionType):
        if element_name(region_type) == name:
            return region_type
    return None


def seed_filled_region_type():
    return DB.FilteredElementCollector(doc)\
             .OfClass(DB.FilledRegionType).FirstElement()


def apply_region_style(region_type, colour, pattern_id, weight):
    """Write colour, pattern and line weight onto a filled region type.

    Written unconditionally rather than only on a difference: a re-run is
    meant to bring an existing type up to date, so anything changed by hand
    is overwritten. The comparison is kept only to say what moved.
    """
    changed = []

    if colour is not None:
        wanted = tuple(channel(c) for c in colour)
        try:
            current = region_type.ForegroundPatternColor
            current_rgb = None
            if current is not None and current.IsValid:
                current_rgb = (channel(current.Red), channel(current.Green),
                               channel(current.Blue))
            region_type.ForegroundPatternColor = DB.Color(wanted[0],
                                                          wanted[1],
                                                          wanted[2])
            if current_rgb != wanted:
                changed.append('colour')
        except Exception:
            swallowed()

    if pattern_id is not None:
        try:
            was = eid_value(region_type.ForegroundPatternId)
            region_type.ForegroundPatternId = pattern_id
            if was != eid_value(pattern_id):
                changed.append('pattern')
        except Exception:
            swallowed()

    try:
        was = region_type.LineWeight
        region_type.LineWeight = weight
        if was != weight:
            changed.append('line weight')
    except Exception:
        swallowed()

    try:
        if region_type.IsMasking:
            region_type.IsMasking = False
            changed.append('masking off')
    except Exception:
        swallowed()

    return changed


def region_type_for(entry, prefix, fallback_pattern_id, weight):
    """Find or make LEG_CONT_<name>, and bring its colour and pattern up to
    date. Returns (FilledRegionType, what happened)."""
    name = prefix + entry.label
    pattern_id = usable_pattern_id(entry.pattern_id, fallback_pattern_id)

    existing = find_filled_region_type(name)
    if existing is not None:
        changed = apply_region_style(existing, entry.colour, pattern_id,
                                     weight)
        return existing, ('overwritten: ' + ', '.join(changed)) if changed \
            else 'overwritten, nothing differed'

    seed = seed_filled_region_type()
    if seed is None:
        return None, 'this project has no filled region type to copy'
    try:
        created = seed.Duplicate(name)
    except Exception as err:
        return None, 'could not create the type: {0}'.format(
            err_text(err))
    apply_region_style(created, entry.colour, pattern_id, weight)
    return created, 'created'


def find_line_subcategory(name):
    try:
        lines = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
    except Exception:
        swallowed()
        return None, None
    try:
        for sub in lines.SubCategories:
            if element_name(sub) == name:
                return lines, sub
    except Exception:
        swallowed()
    return lines, None


def find_line_pattern(name):
    for element in DB.FilteredElementCollector(doc)\
                     .OfClass(DB.LinePatternElement):
        if element_name(element) == name:
            return element
    return None


def centreline_pattern_id():
    """The dashed centre pattern, created or brought up to date.

    Segment lengths are paper millimetres - that is how Revit defines a line
    pattern - so they are converted from mm the same way, but they do not
    scale with the view the way the swatch does.
    """
    try:
        segment_type = DB.LinePatternSegmentType
    except Exception:
        swallowed()
        return None

    segments = List[DB.LinePatternSegment]()
    for kind, length in CENTRELINE_SEGMENTS:
        member = getattr(segment_type, 'Dash' if kind == 'dash' else 'Space',
                         None)
        if member is None:
            return None
        segments.Add(DB.LinePatternSegment(member, to_internal(length)))

    pattern = DB.LinePattern(CENTRELINE_PATTERN_NAME)
    pattern.SetSegments(segments)

    existing = find_line_pattern(CENTRELINE_PATTERN_NAME)
    if existing is not None:
        try:
            existing.SetLinePattern(pattern)
        except Exception:
            swallowed()               # keep whatever is already there
        return existing.Id

    try:
        return DB.LinePatternElement.Create(doc, pattern).Id
    except Exception:
        swallowed()
        return None


def apply_line_style(sub, colour, weight):
    """Write colour and line weight onto a line subcategory, always."""
    changed = []

    if colour is not None:
        wanted = tuple(channel(c) for c in colour)
        try:
            current = sub.LineColor
            current_rgb = None
            if current is not None and current.IsValid:
                current_rgb = (channel(current.Red), channel(current.Green),
                               channel(current.Blue))
            sub.LineColor = DB.Color(wanted[0], wanted[1], wanted[2])
            if current_rgb != wanted:
                changed.append('colour')
        except Exception:
            swallowed()

    try:
        was = sub.GetLineWeight(DB.GraphicsStyleType.Projection)
        sub.SetLineWeight(weight, DB.GraphicsStyleType.Projection)
        if was != weight:
            changed.append('line weight')
    except Exception:
        swallowed()

    return changed


def centreline_style(weight):
    """One grey line style, shared by every swatch that wants a centreline."""
    lines, sub = find_line_subcategory(CENTRELINE_NAME)
    if lines is None:
        return None
    if sub is None:
        try:
            sub = doc.Settings.Categories.NewSubcategory(lines,
                                                         CENTRELINE_NAME)
        except Exception:
            swallowed()
            return None
    apply_line_style(sub, CENTRELINE_RGB, weight)
    pattern_id = centreline_pattern_id()
    if pattern_id is not None:
        try:
            sub.SetLinePatternId(pattern_id, DB.GraphicsStyleType.Projection)
        except Exception:
            swallowed()

    try:
        return sub.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
    except Exception:
        swallowed()
        return None


def line_style_for(entry, prefix, weight):
    """Find or make a line style carrying the system's own colour.

    A duct or pipe reads as an outline, not a fill, so the swatch is four
    detail lines. Their colour comes from the line style, which is a
    subcategory of Lines - there is no per-curve colour override.

    An existing style of the same name is overwritten rather than left as
    found, so a re-run brings it back in line with the model.
    """
    name = safe_style_name(prefix + (entry.key or entry.label))
    lines, sub = find_line_subcategory(name)
    if lines is None:
        return None, 'the Lines category is not available'

    created = False
    if sub is None:
        try:
            sub = doc.Settings.Categories.NewSubcategory(lines, name)
            created = True
        except Exception as err:
            return None, 'could not create the line style: {0}'.format(
                err_text(err))

    changed = apply_line_style(sub, entry.colour, weight)

    try:
        style = sub.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
    except Exception:
        swallowed()
        style = None
    if style is None:
        return None, 'the line style has no projection graphics style'

    if created:
        return style, 'created'
    if changed:
        return style, 'overwritten: ' + ', '.join(changed)
    return style, 'overwritten, nothing differed'


def draw_outline_swatch(view, style, x0, y0, x1, y1):
    """Four detail lines, so the swatch is an outline with no fill."""
    corners = [DB.XYZ(x0, y0, 0.0), DB.XYZ(x1, y0, 0.0),
               DB.XYZ(x1, y1, 0.0), DB.XYZ(x0, y1, 0.0)]
    for index in range(4):
        line = DB.Line.CreateBound(corners[index], corners[(index + 1) % 4])
        curve = doc.Create.NewDetailCurve(view, line)
        if style is not None:
            try:
                curve.LineStyle = style
            except Exception:
                swallowed()


def draw_centreline(view, style, x0, x1, y, overhang):
    """The grey line through the middle, running past both ends."""
    line = DB.Line.CreateBound(DB.XYZ(x0 - overhang, y, 0.0),
                               DB.XYZ(x1 + overhang, y, 0.0))
    curve = doc.Create.NewDetailCurve(view, line)
    if style is not None:
        try:
            curve.LineStyle = style
        except Exception:
            swallowed()


def rectangle_loop(x0, y0, x1, y1):
    points = [DB.XYZ(x0, y0, 0.0), DB.XYZ(x1, y0, 0.0),
              DB.XYZ(x1, y1, 0.0), DB.XYZ(x0, y1, 0.0)]
    loop = DB.CurveLoop()
    for index in range(4):
        loop.Append(DB.Line.CreateBound(points[index], points[(index + 1) % 4]))
    loops = List[DB.CurveLoop]()
    loops.Add(loop)
    return loops


def place_heading(view, text, x, y, type_id):
    options = DB.TextNoteOptions(type_id)
    options.HorizontalAlignment = DB.HorizontalTextAlignment.Left
    note = DB.TextNote.Create(doc, view.Id, DB.XYZ(x, y, 0.0), text, options)
    # The house heading is underlined. Formatted text is a 2019+ API and is
    # cosmetic, so a release without it loses the underline, not the heading.
    try:
        formatted = note.GetFormattedText()
        formatted.SetUnderlineStatus(True)
        note.SetFormattedText(formatted)
    except Exception:
        swallowed()
    return note


def build_system_legend(view, entries, opts):
    """Draw the swatches, the labels and a header per group.

    Groups run down the view one after another, each under its own header.
    An ungrouped kind is simply one group carrying the kind's heading.
    """
    width = to_internal(opts['swatch_w'])
    height = to_internal(opts['swatch_h'])
    pitch = to_internal(opts['row_pitch'])
    gap = to_internal(opts['text_gap'])
    head_gap = to_internal(opts['heading_gap'])

    outline = opts.get('style') == 'outline'
    wants_centreline = bool(opts.get('centreline'))
    overhang = height * CENTRELINE_OVERHANG

    weight = clamp_weight(opts.get('line_weight', DEFAULT_LINE_WEIGHT))
    fallback_pattern = None if outline else solid_fill_pattern_id()
    centre_style = centreline_style(weight) if wants_centreline else None
    if wants_centreline and centre_style is None:
        opts.setdefault('notes', []).append(
            'the grey centreline style could not be created - swatches are '
            'drawn without it')

    placed = 0
    skipped = []
    notes = list(opts.get('notes', []))
    cursor = 0.0                      # runs downward as the legend is built

    for header, group in opts['groups']:
        drawn = []
        for entry in group:
            if outline:
                style, outcome = line_style_for(entry,
                                                opts['region_prefix'],
                                                weight)
                region_type = None
                if style is None:
                    skipped.append((entry.label, outcome))
                    continue
            else:
                style = None
                region_type, outcome = region_type_for(
                    entry, opts['region_prefix'], fallback_pattern,
                    weight)
                if region_type is None:
                    skipped.append((entry.label, outcome))
                    continue
            notes.append('{0}{1} - {2}'.format(
                opts['region_prefix'], entry.key or entry.label, outcome))
            drawn.append((entry, style, region_type))

        if not drawn:
            continue

        # the header sits above the first swatch of its own group
        place_heading(view, header, 0.0, cursor, opts['head_type_id'])
        cursor -= head_gap

        for index, (entry, style, region_type) in enumerate(drawn):
            top = cursor - pitch * index
            middle = top - height / 2.0
            try:
                if outline:
                    draw_outline_swatch(view, style, 0.0, top - height,
                                        width, top)
                    if centre_style is not None:
                        draw_centreline(view, centre_style, 0.0, width,
                                        middle, overhang)
                else:
                    DB.FilledRegion.Create(doc, region_type.Id, view.Id,
                                           rectangle_loop(0.0, top - height,
                                                          width, top))
            except Exception as err:
                skipped.append((entry.label, err_text(err)))
                continue

            label = entry.label.upper() if opts['upper'] else entry.label
            options = DB.TextNoteOptions(opts['text_type_id'])
            options.HorizontalAlignment = DB.HorizontalTextAlignment.Left
            try:
                options.VerticalAlignment = DB.VerticalTextAlignment.Middle
            except Exception:
                swallowed()
            DB.TextNote.Create(doc, view.Id,
                               DB.XYZ(width + gap, middle, 0.0),
                               label, options)
            placed += 1

        cursor -= pitch * len(drawn)
        cursor -= head_gap            # breathing room before the next header

    return placed, skipped, notes


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run_batch(infos, opts, seed_view, seed_component, taken):
    """Build the legends. One transaction per legend inside a group."""
    results = []
    jobs = [(COMBINED_NAME, infos)] if (opts['combined'] and len(infos) > 1) \
        else [(VIEW_PREFIX + info.name, [info]) for info in infos]

    group = DB.TransactionGroup(doc, 'Create WIP legends')
    group.Start()
    try:
        with forms.ProgressBar(title='Legend {value} of {max_value}',
                               cancellable=True) as progress:
            for index, (name, members) in enumerate(jobs, 1):
                if progress.cancelled:
                    break
                trans = quiet_transaction(DB.Transaction(doc, name))
                trans.Start()
                try:
                    view = make_legend_view(seed_view, name, taken,
                                            opts['scale'])
                    if view is None:
                        raise Exception('the seed legend cannot be duplicated')
                    count, skipped = populate_legend(
                        view, members, seed_view, seed_component, opts)
                    trans.Commit()
                    results.append((name, view, count, skipped))
                except Exception as err:
                    if trans.HasStarted():
                        trans.RollBack()
                    results.append((name, None, 0, [('-', err_text(err))]))
                progress.update_progress(index, len(jobs))
        group.Assimilate()
    except Exception:
        group.RollBack()
        raise
    return results


def open_view(view):
    """Make the new legend the active view, and prove it took.

    Called after the transaction has committed - changing the active view
    inside an open transaction throws - and read back afterwards, because
    assigning ActiveView is a void call that can quietly do nothing.
    """
    if view is None:
        return False
    try:
        uidoc = revit.uidoc
    except Exception:
        swallowed()
        uidoc = None
    if uidoc is None:
        return False

    for attempt in ('assign', 'request'):
        try:
            if attempt == 'assign':
                uidoc.ActiveView = view
            else:
                # Queued rather than immediate, so it is the fallback: it
                # applies when the command returns, not now.
                uidoc.RequestViewChange(view)
        except Exception:
            swallowed()
            continue
        try:
            if eid_value(uidoc.ActiveView.Id) == eid_value(view.Id):
                try:
                    uidoc.RefreshActiveView()
                except Exception:
                    swallowed()
                return True
        except Exception:
            swallowed()
    return False


def show_project_browser():
    """Make sure the Project Browser pane is open - it can be closed, and a
    selection in a hidden pane takes nobody anywhere."""
    try:
        import Autodesk.Revit.UI as revit_ui
        from pyrevit import HOST_APP
        panes = getattr(revit_ui, 'DockablePanes', None)
        builtin = getattr(panes, 'BuiltInDockablePanes', None)
        pane_id = getattr(builtin, 'ProjectBrowser', None)
        if pane_id is None:
            return False
        pane = HOST_APP.uiapp.GetDockablePane(pane_id)
        if not pane.IsShown():
            pane.Show()
        return bool(pane.IsShown())
    except Exception as err:
        log(u'   browser pane: {0}'.format(err_text(err)))
        return False


def select_element(view):
    """Select the view as an element, and read the selection back."""
    try:
        uidoc = revit.uidoc
        ids = List[DB.ElementId]()
        ids.Add(view.Id)
        uidoc.Selection.SetElementIds(ids)
        wanted = eid_value(view.Id)
        return any(eid_value(i) == wanted
                   for i in uidoc.Selection.GetElementIds())
    except Exception as err:
        log(u'   select view: {0}'.format(err_text(err)))
        return False


def _uia_select(handle, name, legends_label):
    """Find the legend in the Project Browser tree, scroll to it, select it.

    UI Automation, because the API has no Project Browser call: it can
    select a view as an element, but whether the browser follows has varied
    by release, and it never scrolls to it. Returns whether the tree item
    reports itself selected afterwards - the browser\'s own word, not ours.
    """
    from System.Windows.Automation import (AutomationElement, AndCondition,
                                           ControlType, ExpandCollapsePattern,
                                           ExpandCollapseState,
                                           PropertyCondition,
                                           ScrollItemPattern,
                                           SelectionItemPattern, TreeScope)
    root = AutomationElement.FromHandle(handle)
    if root is None:
        return False

    def tree_item(label):
        return AndCondition(
            PropertyCondition(AutomationElement.ControlTypeProperty,
                              ControlType.TreeItem),
            PropertyCondition(AutomationElement.NameProperty, label))

    scope = root
    group = root.FindFirst(TreeScope.Descendants, tree_item(legends_label))
    if group is not None:
        # A collapsed node hides its children from UI Automation entirely,
        # so the Legends group is opened before looking inside it.
        try:
            expand = group.GetCurrentPattern(ExpandCollapsePattern.Pattern)
            if expand.Current.ExpandCollapseState != \
                    ExpandCollapseState.Expanded:
                expand.Expand()
        except Exception:
            swallowed()
        scope = group

    target = scope.FindFirst(TreeScope.Descendants, tree_item(name))
    if target is None and scope is not root:
        target = root.FindFirst(TreeScope.Descendants, tree_item(name))
    if target is None:
        return False

    try:
        target.GetCurrentPattern(ScrollItemPattern.Pattern).ScrollIntoView()
    except Exception:
        swallowed()
    selector = target.GetCurrentPattern(SelectionItemPattern.Pattern)
    selector.Select()
    return bool(selector.Current.IsSelected)


BROWSER_TIMEOUT_S = 4.0


def select_in_browser_tree(view):
    """Run the UI Automation search off the UI thread, pumping meanwhile.

    UI Automation must not run on the thread that owns the window it is
    reading - the provider answers on that thread, and a client blocking it
    waits for ever. So the search runs on a worker thread while this thread
    keeps Revit\'s message loop turning, and gives up after a few seconds
    rather than risk a hang. Returns True, False, or None when it timed out.
    """
    try:
        from pyrevit import HOST_APP
        handle = HOST_APP.uiapp.MainWindowHandle
    except Exception as err:
        log(u'   browser tree: no main window - {0}'.format(err_text(err)))
        return False

    try:
        from System import Action, TimeSpan
        from System.Threading import ApartmentState, Thread, ThreadStart
        from System.Windows.Threading import (Dispatcher, DispatcherFrame,
                                              DispatcherPriority,
                                              DispatcherTimer)
    except Exception as err:
        log(u'   browser tree: threading unavailable - {0}'.format(
            err_text(err)))
        return False

    dispatcher = Dispatcher.CurrentDispatcher
    frame = DispatcherFrame()
    box = {'result': None, 'error': None, 'done': False}

    def stop():
        frame.Continue = False

    def work():
        try:
            box['result'] = _uia_select(handle, element_name(view), 'Legends')
        except Exception as err:
            box['error'] = err_text(err)
        finally:
            box['done'] = True
            try:
                dispatcher.BeginInvoke(DispatcherPriority.Normal,
                                       Action(stop))
            except Exception:
                swallowed()

    def timed_out(sender, args):
        timer.Stop()
        stop()

    timer = DispatcherTimer()
    timer.Interval = TimeSpan.FromSeconds(BROWSER_TIMEOUT_S)
    timer.Tick += timed_out

    worker = Thread(ThreadStart(work))
    worker.IsBackground = True
    worker.SetApartmentState(ApartmentState.MTA)
    worker.Start()
    timer.Start()
    try:
        Dispatcher.PushFrame(frame)
    finally:
        timer.Stop()

    if box['error']:
        log(u'   browser tree: {0}'.format(box['error']))
    if not box['done']:
        log(u'   browser tree: gave up after {0}s'.format(BROWSER_TIMEOUT_S))
        return None
    return box['result']


def reveal_in_browser(view):
    """Take the user to a legend in the Project Browser.

    Three steps, each checked: the pane is shown, the view is selected as an
    element, and the browser tree itself is scrolled to the item and reports
    it selected. Each one's outcome is logged, because which of them a given
    Revit release honours is exactly the thing that varies.
    """
    if view is None:
        return False
    shown = show_project_browser()
    selected = select_element(view)
    in_tree = select_in_browser_tree(view)
    log(u'browser: pane shown {0}, view selected {1}, tree item selected '
        u'{2}'.format(shown, selected, in_tree))
    return bool(in_tree) or selected


def run_system(entries, opts, seed_view, taken):
    """Build the one system colour legend. Its own transaction."""
    trans = quiet_transaction(
        DB.Transaction(doc, 'Create system colour legend'))
    trans.Start()
    try:
        view = make_legend_view(seed_view, opts['view_name'], taken,
                                opts['scale'])
        if view is None:
            raise Exception('the seed legend cannot be duplicated')
        placed, skipped, notes = build_system_legend(view, entries, opts)
        trans.Commit()
        return view, placed, skipped, notes
    except Exception as err:
        if trans.HasStarted():
            trans.RollBack()
        return None, 0, [('-', err_text(err))], []
