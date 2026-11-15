# -*- coding: utf-8 -*-
"""RevoBIM - DWG Block Replace

Swap the instances of a partially exploded imported DWG for a Revit Detail
Item or Generic Annotation family type, picking both ends of the swap
straight out of the view.

Workflow
    1. Click "Pick a DWG block in the view" and click one of the CAD blocks.
       Every instance of that same block in the active view is gathered and
       highlighted.
    2. Click "Pick the replacement element in the view" and click an element
       that is already the family and type you want. (Or set it from the
       dropdowns.)
    3. Hit REPLACE. Each new element lands on the centre point (or the block
       insertion point) of its CAD block, rotated to match the block.
    4. Nudge them all by 90 degrees or a specified amount if needed.
    5. ESC cancels a pick. ESC with the window focused, or Finish, ends the
       tool.

Tested against Revit 2024 / pyRevit 2.7 (IronPython 2.7 engine).
"""

__title__ = "DWG Block\nReplace"
__author__ = "RevoBIM"
__doc__ = ("Pick a DWG block in the view, pick the family you want instead, "
           "and swap every instance of that block in the view.")

# the modeless window needs the engine to stay alive after the script ends
__persistentengine__ = True

import os
import math
import traceback

from pyrevit import forms
from pyrevit import script

from System import Uri, AppDomain
from System.Collections.Generic import List
from System.Windows.Input import Key
from System.Windows.Media import Color, SolidColorBrush
from System.Windows.Media.Imaging import BitmapImage

from Autodesk.Revit.DB import (
    BuiltInCategory, ElementId, ElementTransformUtils, FamilyInstance,
    FamilySymbol, FilteredElementCollector, ImportInstance, Line, Transaction,
    ViewType, XYZ
)
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

logger = script.get_logger()

UIDOC = __revit__.ActiveUIDocument                 # noqa
DOC = UIDOC.Document if UIDOC else None            # noqa

TOOL_DIR = os.path.dirname(__file__)
XAML_FILE = os.path.join(TOOL_DIR, "ui.xaml")
ICON_FILE = os.path.join(TOOL_DIR, "icon.png")

WINDOW_SLOT = "RevoBIM.DWGBlockReplace.Window"

CATEGORIES = [
    ("Detail Items", BuiltInCategory.OST_DetailComponents),
    ("Generic Annotations", BuiltInCategory.OST_GenericAnnotation),
]
CATEGORY_IDS = dict(
    (ElementId(bic).IntegerValue, label) for label, bic in CATEGORIES
)

PLAN_LIKE = (
    ViewType.DraftingView, ViewType.FloorPlan, ViewType.CeilingPlan,
    ViewType.EngineeringPlan, ViewType.AreaPlan, ViewType.Legend,
)

MM = 1.0 / 304.8            # millimetre in feet
SIZE_TOL = 2.0 * MM         # block size match tolerance

BRUSH_BLUE = SolidColorBrush(Color.FromRgb(79, 163, 227))
BRUSH_ORANGE = SolidColorBrush(Color.FromRgb(232, 135, 60))


def ui_safe(func):
    """Never let a Python exception escape into the WPF dispatcher.

    An unhandled exception in a XAML wired handler runs on Revit's own UI
    thread and takes Revit down with it, so every handler is wrapped.
    """
    def wrapper(self, *args):
        try:
            return func(self, *args)
        except Exception:
            logger.error(traceback.format_exc())
            try:
                self.status("Something went wrong - see the pyRevit output.",
                            ok=False)
            except Exception:
                pass
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


# ---------------------------------------------------------------------------
# External event plumbing - anything touching the Revit API is queued here so
# the modeless window never calls the API out of context.
# ---------------------------------------------------------------------------
class QueuedEventHandler(IExternalEventHandler):
    def __init__(self):
        self.queue = []

    def enqueue(self, func):
        self.queue.append(func)

    def Execute(self, uiapp):
        while self.queue:
            action = self.queue.pop(0)
            try:
                action(uiapp)
            except OperationCanceledException:
                pass
            except Exception:
                logger.error(traceback.format_exc())

    def GetName(self):
        return "RevoBIM DWG Block Replace"


# ---------------------------------------------------------------------------
# Selection filters
# ---------------------------------------------------------------------------
class ImportFilter(ISelectionFilter):
    def AllowElement(self, element):
        try:
            return isinstance(element, ImportInstance)
        except Exception:
            return False

    def AllowReference(self, reference, position):
        return False


class ReplacementFilter(ISelectionFilter):
    def AllowElement(self, element):
        try:
            if isinstance(element, ImportInstance):
                return False
            if not isinstance(element, FamilyInstance):
                return False
            category = element.Category
            if category is None:
                return False
            return category.Id.IntegerValue in CATEGORY_IDS
        except Exception:
            return False

    def AllowReference(self, reference, position):
        return False


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def _bbox(element, view):
    try:
        box = element.get_BoundingBox(view)
    except Exception:
        box = None
    if box is None:
        try:
            box = element.get_BoundingBox(None)
        except Exception:
            box = None
    return box


def _bbox_centre(element, view):
    box = _bbox(element, view)
    if box is None:
        return None
    return XYZ((box.Min.X + box.Max.X) / 2.0,
               (box.Min.Y + box.Max.Y) / 2.0,
               (box.Min.Z + box.Max.Z) / 2.0)


def _bbox_size(element, view):
    box = _bbox(element, view)
    if box is None:
        return None
    return (abs(box.Max.X - box.Min.X), abs(box.Max.Y - box.Min.Y))


def _instance_transform(element):
    for name in ("GetTransform", "GetTotalTransform"):
        try:
            return getattr(element, name)()
        except Exception:
            continue
    return None


def _origin_is_usable(origin, element, view):
    if origin is None:
        return False
    box = _bbox(element, view)
    if box is None:
        return False
    pad = 1.0
    return (box.Min.X - pad <= origin.X <= box.Max.X + pad and
            box.Min.Y - pad <= origin.Y <= box.Max.Y + pad)


def read_block(element, view, use_origin):
    """Return (point, angle_radians, rotation_found, mirrored)."""
    point = _bbox_centre(element, view)
    transform = _instance_transform(element)
    angle = 0.0
    rotation_found = False
    mirrored = False

    if transform is not None:
        try:
            basis_x = transform.BasisX
            if abs(basis_x.X) > 1e-9 or abs(basis_x.Y) > 1e-9:
                angle = math.atan2(basis_x.Y, basis_x.X)
                rotation_found = abs(angle) > 1e-9
        except Exception:
            pass
        try:
            mirrored = bool(transform.HasReflection)
        except Exception:
            mirrored = False
        if use_origin:
            try:
                if _origin_is_usable(transform.Origin, element, view):
                    point = transform.Origin
            except Exception:
                pass

    if point is None:
        return None, 0.0, False, False

    if view.ViewType in PLAN_LIKE:
        point = XYZ(point.X, point.Y, 0.0)

    return point, angle, rotation_found, mirrored


def rotation_axis(view):
    if view.ViewType in PLAN_LIKE:
        return XYZ.BasisZ
    try:
        direction = view.ViewDirection
        if direction is not None and not direction.IsZeroLength():
            return direction
    except Exception:
        pass
    return XYZ.BasisZ


def rotate_element(doc, element, angle, view):
    if abs(angle) < 1e-9:
        return
    point = None
    location = element.Location
    if location is not None and hasattr(location, "Point"):
        point = location.Point
    if point is None:
        point = _bbox_centre(element, view)
    if point is None:
        return
    axis = Line.CreateBound(point, point.Add(rotation_axis(view)))
    ElementTransformUtils.RotateElement(doc, element.Id, axis, angle)


# ---------------------------------------------------------------------------
# Block identity
# ---------------------------------------------------------------------------
def element_name(element):
    if element is None:
        return None
    try:
        name = element.Name
    except Exception:
        return None
    return name or None


def block_key(doc, element):
    """Identity used to find the sibling instances of a CAD block."""
    category = "?"
    try:
        if element.Category is not None:
            category = element.Category.Name
    except Exception:
        pass

    type_name = None
    try:
        type_id = element.GetTypeId()
        if type_id is not None and type_id != ElementId.InvalidElementId:
            type_name = element_name(doc.GetElement(type_id))
    except Exception:
        type_name = None

    if not type_name:
        type_name = element_name(element) or "(unnamed)"

    return (category, type_name)


def blocks_in_view(doc, view, key, reference=None, match_size=False):
    found = []
    ref_size = _bbox_size(reference, view) if (match_size and reference) else None

    collector = FilteredElementCollector(doc, view.Id).OfClass(ImportInstance)
    for element in collector:
        try:
            if block_key(doc, element) != key:
                continue
            if ref_size is not None:
                size = _bbox_size(element, view)
                if size is None:
                    continue
                if (abs(size[0] - ref_size[0]) > SIZE_TOL or
                        abs(size[1] - ref_size[1]) > SIZE_TOL):
                    continue
            found.append(element.Id)
        except Exception:
            continue
    return found


# ---------------------------------------------------------------------------
# Model queries
# ---------------------------------------------------------------------------
def collect_symbols(doc):
    """{category label: {family name: [(type name, ElementId), ...]}}"""
    data = {}
    for label, bic in CATEGORIES:
        families = {}
        collector = (FilteredElementCollector(doc)
                     .OfClass(FamilySymbol)
                     .OfCategory(bic)
                     .WhereElementIsElementType())
        for symbol in collector:
            try:
                family = symbol.Family
                if family is None:
                    continue
                fam_name = family.Name
                type_name = symbol.Name
                if not fam_name or not type_name:
                    continue
            except Exception:
                continue
            families.setdefault(fam_name, []).append((type_name, symbol.Id))
        for fam_name in families:
            families[fam_name].sort(key=lambda item: item[0].lower())
        data[label] = families
    return data


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------
class BlockReplaceWindow(forms.WPFWindow):
    def __init__(self, handler, external_event):
        forms.WPFWindow.__init__(self, XAML_FILE)

        self.handler = handler
        self.external_event = external_event

        self.symbol_data = {}
        self.family_names = []
        self.block_ids = []
        self.block_label = ""
        self.placed_all = []
        self.placed_last = []
        self.picking = False
        self._syncing = False

        self._load_logo()

        self.CategoryCombo.Items.Clear()
        self.CategoryCombo.Items.Add("All")
        for label, _bic in CATEGORIES:
            self.CategoryCombo.Items.Add(label)
        self.CategoryCombo.SelectedIndex = 0

        # the initial load runs inside a valid API context (script start up)
        self.symbol_data = collect_symbols(DOC)
        self._fill_family_list()
        self._refresh_replace_state()

        self.Closed += self.on_closed

    # ----------------------------------------------------------- utilities
    def _load_logo(self):
        try:
            if os.path.exists(ICON_FILE):
                self.LogoImage.Source = BitmapImage(Uri(ICON_FILE))
        except Exception:
            logger.debug("Header icon could not be loaded.")

    def status(self, message, ok=True):
        self.StatusText.Text = message
        self.StatusText.Foreground = BRUSH_BLUE if ok else BRUSH_ORANGE

    def queue(self, action):
        try:
            self.handler.enqueue(action)
            self.external_event.Raise()
        except Exception:
            logger.error(traceback.format_exc())
            self.status("Revit did not accept the request - try again.", ok=False)

    def set_picking(self, picking):
        self.picking = picking
        self.PickBlockButton.IsEnabled = not picking
        self.PickTargetButton.IsEnabled = not picking
        if not picking:
            self._refresh_replace_state()
        else:
            self.ReplaceButton.IsEnabled = False

    def _refresh_replace_state(self):
        ready = bool(self.block_ids) and self.selected_symbol_id() is not None
        self.ReplaceButton.IsEnabled = ready

    # -------------------------------------------------------- family lists
    def _active_categories(self):
        selected = self.CategoryCombo.SelectedItem
        if selected is None or selected == "All":
            return [label for label, _bic in CATEGORIES]
        return [selected]

    def _fill_family_list(self):
        needle = (self.SearchBox.Text or "").strip().lower()
        names = set()
        for label in self._active_categories():
            for fam_name in self.symbol_data.get(label, {}):
                if not needle or needle in fam_name.lower():
                    names.add(fam_name)

        self.family_names = sorted(names, key=lambda name: name.lower())
        self.FamilyCombo.Items.Clear()
        for name in self.family_names:
            self.FamilyCombo.Items.Add(name)
        if self.family_names:
            self.FamilyCombo.SelectedIndex = 0
        else:
            self.TypeCombo.Items.Clear()

    def _fill_type_list(self):
        self.TypeCombo.Items.Clear()
        fam_name = self.FamilyCombo.SelectedItem
        if not fam_name:
            return
        seen = []
        for label in self._active_categories():
            for type_name, _sid in self.symbol_data.get(label, {}).get(fam_name, []):
                if type_name not in seen:
                    seen.append(type_name)
        for type_name in sorted(seen, key=lambda name: name.lower()):
            self.TypeCombo.Items.Add(type_name)
        if self.TypeCombo.Items.Count:
            self.TypeCombo.SelectedIndex = 0

    def selected_symbol_id(self):
        fam_name = self.FamilyCombo.SelectedItem
        type_name = self.TypeCombo.SelectedItem
        if not fam_name or not type_name:
            return None
        for label in self._active_categories():
            for name, symbol_id in self.symbol_data.get(label, {}).get(fam_name, []):
                if name == type_name:
                    return symbol_id
        return None

    def sync_combos_to(self, fam_name, type_name):
        """Drive the dropdowns from an element picked in the view."""
        self._syncing = True
        try:
            self.CategoryCombo.SelectedIndex = 0        # All
            self.SearchBox.Text = ""
            self._fill_family_list()
            if fam_name in self.family_names:
                self.FamilyCombo.SelectedItem = fam_name
            self._fill_type_list()
            for index in range(self.TypeCombo.Items.Count):
                if self.TypeCombo.Items[index] == type_name:
                    self.TypeCombo.SelectedIndex = index
                    break
        finally:
            self._syncing = False

    def _describe_target(self):
        fam_name = self.FamilyCombo.SelectedItem
        type_name = self.TypeCombo.SelectedItem
        if fam_name and type_name:
            self.TargetText.Text = "{0}\n{1}".format(fam_name, type_name)
        else:
            self.TargetText.Text = "Nothing picked yet."

    def _rotation_targets(self, uidoc):
        doc = uidoc.Document
        if self.UseSelectionChk.IsChecked:
            ids = list(uidoc.Selection.GetElementIds())
        elif self.LastBatchChk.IsChecked:
            ids = list(self.placed_last)
        else:
            ids = list(self.placed_all)
        return [eid for eid in ids if doc.GetElement(eid) is not None]

    # ------------------------------------------------------- API callbacks
    def act_pick_block(self, uiapp):
        uidoc = uiapp.ActiveUIDocument
        if uidoc is None:
            return
        doc = uidoc.Document
        view = doc.ActiveView

        try:
            reference = uidoc.Selection.PickObject(
                ObjectType.Element, ImportFilter(),
                "Click one of the DWG blocks (Esc to cancel)")
        except OperationCanceledException:
            self.set_picking(False)
            self.status("Pick cancelled.")
            return
        except Exception:
            logger.error(traceback.format_exc())
            self.set_picking(False)
            self.status("Could not pick that element.", ok=False)
            return

        element = doc.GetElement(reference.ElementId)
        if element is None:
            self.set_picking(False)
            return

        key = block_key(doc, element)
        if self.AllInViewChk.IsChecked:
            ids = blocks_in_view(doc, view, key, element,
                                 bool(self.MatchSizeChk.IsChecked))
        else:
            ids = [element.Id]

        self.block_ids = ids
        self.block_label = key[1]

        selection = List[ElementId]()
        for eid in ids:
            selection.Add(eid)
        try:
            uidoc.Selection.SetElementIds(selection)
        except Exception:
            logger.debug("Could not highlight the blocks.")

        self.BlockText.Text = "{0}\n{1} instance(s) in this view".format(
            key[1], len(ids))
        self.set_picking(False)
        self.status("Now pick the element you want them swapped for.")

    def act_use_selection(self, uiapp):
        uidoc = uiapp.ActiveUIDocument
        if uidoc is None:
            return
        doc = uidoc.Document
        ids = []
        others = 0
        for eid in uidoc.Selection.GetElementIds():
            element = doc.GetElement(eid)
            if isinstance(element, ImportInstance):
                ids.append(eid)
            elif element is not None:
                others += 1

        self.block_ids = ids
        self.block_label = "current selection"
        if ids:
            text = "Current Revit selection\n{0} DWG block(s)".format(len(ids))
            if others:
                text += "  ({0} other element(s) ignored)".format(others)
        else:
            text = "No DWG blocks in the current selection."
        self.BlockText.Text = text
        self._refresh_replace_state()

    def act_pick_replacement(self, uiapp):
        uidoc = uiapp.ActiveUIDocument
        if uidoc is None:
            return
        doc = uidoc.Document

        try:
            reference = uidoc.Selection.PickObject(
                ObjectType.Element, ReplacementFilter(),
                "Click a detail item or generic annotation to copy (Esc to cancel)")
        except OperationCanceledException:
            self.set_picking(False)
            self.status("Pick cancelled.")
            return
        except Exception:
            logger.error(traceback.format_exc())
            self.set_picking(False)
            self.status("Could not pick that element.", ok=False)
            return

        element = doc.GetElement(reference.ElementId)
        symbol = getattr(element, "Symbol", None)
        if symbol is None:
            self.set_picking(False)
            self.status("That element has no family type to copy.", ok=False)
            return

        try:
            fam_name = symbol.Family.Name
            type_name = symbol.Name
        except Exception:
            self.set_picking(False)
            self.status("Could not read that family type.", ok=False)
            return

        # make sure the picked family is in the cached list
        if fam_name not in self.family_names:
            self.symbol_data = collect_symbols(doc)

        self.sync_combos_to(fam_name, type_name)
        self._describe_target()
        self.set_picking(False)
        self.status("Ready - press REPLACE.")

    def act_reload_families(self, uiapp):
        uidoc = uiapp.ActiveUIDocument
        if uidoc is None:
            return
        self.symbol_data = collect_symbols(uidoc.Document)
        self._fill_family_list()
        self._describe_target()
        self._refresh_replace_state()
        self.status("Family list reloaded from the active model.")

    def act_replace(self, uiapp):
        uidoc = uiapp.ActiveUIDocument
        if uidoc is None:
            return
        doc = uidoc.Document
        view = doc.ActiveView

        elements = []
        for eid in self.block_ids:
            element = doc.GetElement(eid)
            if isinstance(element, ImportInstance):
                elements.append(element)

        if not elements:
            self.status("Those DWG blocks are gone - pick again.", ok=False)
            self.block_ids = []
            self._refresh_replace_state()
            return

        symbol_id = self.selected_symbol_id()
        symbol = doc.GetElement(symbol_id) if symbol_id else None
        if symbol is None:
            self.status("Pick the replacement family first.", ok=False)
            return

        use_origin = bool(self.PtOriginRadio.IsChecked)
        match_rotation = bool(self.MatchRotChk.IsChecked)
        delete_originals = bool(self.DeleteChk.IsChecked)

        placed = []
        failed = 0
        no_rotation = 0
        mirrored = 0

        transaction = Transaction(doc, "RevoBIM - DWG Block Replace")
        transaction.Start()
        try:
            if not symbol.IsActive:
                symbol.Activate()
                doc.Regenerate()

            to_delete = List[ElementId]()

            for element in elements:
                point, angle, found, is_mirrored = read_block(
                    element, view, use_origin)
                if point is None:
                    failed += 1
                    continue
                if is_mirrored:
                    mirrored += 1
                if not found:
                    no_rotation += 1

                try:
                    instance = doc.Create.NewFamilyInstance(point, symbol, view)
                except Exception:
                    logger.debug(traceback.format_exc())
                    failed += 1
                    continue

                if match_rotation and abs(angle) > 1e-9:
                    try:
                        rotate_element(doc, instance, angle, view)
                    except Exception:
                        logger.debug(traceback.format_exc())

                placed.append(instance.Id)
                to_delete.Add(element.Id)

            if delete_originals and to_delete.Count:
                doc.Delete(to_delete)

            transaction.Commit()
        except Exception:
            logger.error(traceback.format_exc())
            try:
                if transaction.HasStarted():
                    transaction.RollBack()
            except Exception:
                pass
            self.status("Replace failed - see the pyRevit output.", ok=False)
            return

        self.placed_last = placed
        self.placed_all.extend(placed)
        if delete_originals:
            self.block_ids = []
            self.BlockText.Text = "Nothing picked yet."

        if self.SelectNewChk.IsChecked and placed:
            new_ids = List[ElementId]()
            for eid in placed:
                new_ids.Add(eid)
            try:
                uidoc.Selection.SetElementIds(new_ids)
            except Exception:
                pass

        message = "Placed {0} element(s).".format(len(placed))
        if failed:
            message += " {0} could not be placed.".format(failed)
        if no_rotation:
            message += " {0} had no readable rotation.".format(no_rotation)
        if mirrored:
            message += " {0} mirrored block(s) - check those.".format(mirrored)
        self.status(message, ok=(failed == 0))
        self._refresh_replace_state()

    def act_rotate(self, uiapp, degrees):
        uidoc = uiapp.ActiveUIDocument
        if uidoc is None:
            return
        doc = uidoc.Document
        view = doc.ActiveView

        ids = self._rotation_targets(uidoc)
        if not ids:
            self.status("Nothing to rotate yet.", ok=False)
            return

        angle = math.radians(degrees)
        done = 0
        transaction = Transaction(doc, "RevoBIM - Rotate Replaced Elements")
        transaction.Start()
        try:
            for eid in ids:
                element = doc.GetElement(eid)
                if element is None:
                    continue
                try:
                    rotate_element(doc, element, angle, view)
                    done += 1
                except Exception:
                    logger.debug(traceback.format_exc())
            transaction.Commit()
        except Exception:
            logger.error(traceback.format_exc())
            try:
                if transaction.HasStarted():
                    transaction.RollBack()
            except Exception:
                pass
            self.status("Rotation failed - see the pyRevit output.", ok=False)
            return

        self.status("Rotated {0} element(s) by {1} degrees.".format(done, degrees))

    # -------------------------------------------------------- UI callbacks
    @ui_safe
    def on_header_drag(self, sender, args):
        try:
            self.DragMove()
        except Exception:
            pass

    @ui_safe
    def on_pick_block(self, sender, args):
        self.set_picking(True)
        self.status("Click a DWG block in the view...")
        self.queue(self.act_pick_block)

    @ui_safe
    def on_use_selection(self, sender, args):
        self.queue(self.act_use_selection)

    @ui_safe
    def on_pick_replacement(self, sender, args):
        self.set_picking(True)
        self.status("Click the element you want to swap in...")
        self.queue(self.act_pick_replacement)

    @ui_safe
    def on_reload_families(self, sender, args):
        self.queue(self.act_reload_families)

    @ui_safe
    def on_category_changed(self, sender, args):
        if self._syncing or not hasattr(self, "symbol_data"):
            return
        self._fill_family_list()

    @ui_safe
    def on_search_changed(self, sender, args):
        if self._syncing or not hasattr(self, "symbol_data"):
            return
        self._fill_family_list()

    @ui_safe
    def on_family_changed(self, sender, args):
        if self._syncing:
            return
        self._fill_type_list()

    @ui_safe
    def on_type_changed(self, sender, args):
        if self._syncing:
            return
        self._describe_target()
        self._refresh_replace_state()

    @ui_safe
    def on_replace(self, sender, args):
        self.status("Replacing...")
        self.queue(self.act_replace)

    @ui_safe
    def on_rot_plus90(self, sender, args):
        self.queue(lambda uiapp: self.act_rotate(uiapp, 90.0))

    @ui_safe
    def on_rot_minus90(self, sender, args):
        self.queue(lambda uiapp: self.act_rotate(uiapp, -90.0))

    @ui_safe
    def on_rot_custom(self, sender, args):
        try:
            degrees = float((self.AngleBox.Text or "").strip())
        except ValueError:
            self.status("That rotation value is not a number.", ok=False)
            return
        self.queue(lambda uiapp: self.act_rotate(uiapp, degrees))

    @ui_safe
    def on_key_down(self, sender, args):
        if args.Key == Key.Escape and not self.picking:
            args.Handled = True
            self.Close()

    @ui_safe
    def on_finish(self, sender, args):
        self.Close()

    @ui_safe
    def on_closed(self, sender, args):
        self.handler.queue = []
        try:
            AppDomain.CurrentDomain.SetData(WINDOW_SLOT, None)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Start up
# ---------------------------------------------------------------------------
def close_previous():
    """Only ever one window, so a second run cannot leave an orphan behind."""
    try:
        previous = AppDomain.CurrentDomain.GetData(WINDOW_SLOT)
    except Exception:
        previous = None
    if previous is None:
        return
    try:
        previous.Close()
    except Exception:
        pass
    try:
        AppDomain.CurrentDomain.SetData(WINDOW_SLOT, None)
    except Exception:
        pass


BLOCKED_VIEWS = (ViewType.Schedule, ViewType.ProjectBrowser,
                 ViewType.SystemBrowser, ViewType.Legend,
                 ViewType.DrawingSheet)

if UIDOC is None or DOC is None or DOC.ActiveView is None:
    forms.alert("Open the view holding the exploded DWG first.",
                title="RevoBIM - DWG Block Replace")
elif DOC.ActiveView.ViewType in BLOCKED_VIEWS:
    forms.alert("Open the drafting view (or model view) that holds the "
                "exploded DWG, then run the tool again.",
                title="RevoBIM - DWG Block Replace")
else:
    close_previous()
    HANDLER = QueuedEventHandler()
    EXT_EVENT = ExternalEvent.Create(HANDLER)
    WINDOW = BlockReplaceWindow(HANDLER, EXT_EVENT)
    AppDomain.CurrentDomain.SetData(WINDOW_SLOT, WINDOW)
    WINDOW.show()
