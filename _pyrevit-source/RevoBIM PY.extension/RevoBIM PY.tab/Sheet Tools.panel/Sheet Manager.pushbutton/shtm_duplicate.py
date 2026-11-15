# -*- coding: utf-8 -*-
"""Create sheets from templates: the builder window.

Two tabs.

**Sheets and views** - pick the source sheets, say what text to find in their
numbers, names and view names, filter the project's view templates by family
and type, and push the ones wanted into the table on the right. Each row there
is one *set*: a full copy of the sources with that template on the views of its
type, and that row's replacement text and grouping values. Next lights up when
every set has what it needs and nothing would clash.

**Preview and create** - every sheet that will be made in one table, sorted and
grouped by the series parameter and banded in colour, re-sortable by clicking
any heading. Create runs it, each row going green as its sheet lands, with a
progress bar showing how much is left.

The window is modeless, because Revit only runs an external event while it is
idle and a modal dialog keeps it busy - and the rows cannot go green unless the
work happens while this window is open. It never writes: Create hands the job
to the main window, which raises the ExternalEvent it created in the command's
own API context.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import traceback

import shtm_batch
import shtm_core
import shtm_grid
import shtm_model
import shtm_plan
import shtm_rows
import shtm_ui
import shtm_vt
import theme
from shtm_ui import ui_safe, styled, text_block

from System.Windows import (
    Thickness, GridLength, GridUnitType, Visibility, VerticalAlignment,
    HorizontalAlignment, TextTrimming, TextWrapping, SystemParameters,
)
from System.Windows.Controls import (
    Grid, StackPanel, TextBlock, ColumnDefinition, RowDefinition, CheckBox,
    ListBoxItem, ComboBoxItem, Button, Border, Orientation, Control,
)
from System.Windows.Input import Key, Keyboard, ModifierKeys, Mouse, MouseButtonState
from System.Windows.Media import Brushes, RotateTransform
from System.Windows.Documents import Run, LineBreak, TextElement

# table-of-sets column widths, shared by the heading and every row so the two
# line up; the heading scrolls sideways with the rows
W_STRIPE = 10.0
W_TEMPLATE = 196.0
W_NUMBER = 118.0
W_NAME = 140.0
W_VIEW = 140.0
W_PARAM = 150.0
W_ACTIONS = 96.0
CELL_HEIGHT = 30.0

# row actions, in Segoe MDL2 Assets - on every Windows that runs Revit 2024+
GLYPH_COPY = u"\uE8C8"
GLYPH_STAR = u"\uE734"
GLYPH_STAR_FULL = u"\uE735"
GLYPH_REMOVE = u"\uE711"
PRESET_MARK = u"\u2605"

TABS = ["build", "preview"]

# each find's colour, the same everywhere: the key by its box, the bold text in
# the source list, and the set table's box that replaces it
FIND_COLOURS = {u"number": ("BlueBrush", "TintBlueBg"),
                u"name": ("OrangeBrush", "TintOrangeBg"),
                u"view": ("GreenBrush", "TintGreenBg")}
NO_PARAMETER = u"(none)"


class PreviewStore(object):
    """What the preview grid asks of a store: only the paint state. A sheet
    goes green when it lands and red if Revit would not make it."""

    def __init__(self):
        self.states = {}

    def get(self, sheet_id, column):
        return None

    def has(self, sheet_id, column):
        return False

    def state_of(self, sheet_id, column):
        return self.states.get(sheet_id)

    def value_of(self, sheet, column):
        return sheet["values"].get(column, u"")


class BuilderWindow(object):

    def __init__(self, doc, settings, sheets, picked_ids, mode, owner=None,
                 launch=None, theme_changed=None, get_settings=None,
                 template_job=None):
        self.doc = doc
        # sends a view template duplicate / rename / edit to Revit
        self.template_job = template_job
        self.template_editor = None
        # read through _settings(): the main window replaces its settings when
        # Settings is applied, and a copy taken here would later be saved back
        # over what was just applied
        self.settings = settings
        self.get_settings = get_settings
        self.sheets = list(sheets)
        self.mode = mode
        self.owner = owner
        self.launch = launch
        self.theme_changed = theme_changed
        self.ticked = set(picked_ids or [])
        # the sheets picked in the main table: the source list shows only
        # these until the tick above it is taken off
        self.picked_ids = set(picked_ids or [])
        # which of the three groups are open: the sources, to start with
        self.sections = {"sources": True, "templates": False, "sets": False}
        # the finds the source list was last painted with
        self.painted_finds = None
        self.rows = []
        self.batches = []
        self.records = []
        self.reasons = [u"starting"]
        self.current_tab = "build"
        self.running = False
        self.finished = False
        self.bulk = False
        self.landed = 0
        self.total = 0
        self.by_key = {}
        self.preview_rows = []
        self.preview_state = None
        self.store = PreviewStore()
        self.source_items = {}
        self.template_items = {}
        self.template_boxes = {}
        self.template_applies = {}
        self.template_marks = {}
        # the table of sets: picked cells, its rows' parts, and fill undo
        self.picked = []
        self.anchor = None
        self.fill_undo = []
        self.fill_picker = None
        self.header_hints = {}
        self.header_cells = {}
        self.cell_shells = {}
        self.cell_boxes = {}
        self.row_parts = {}
        self.row_state_list = []

        self.window = shtm_ui.load_window("ShtmDuplicate.xaml", mode)
        self.find = self.window.FindName
        self.chrome = shtm_ui.Chrome(self.window, busy=lambda: self.running)
        shtm_ui.load_icon(self.find("LogoImage"))
        shtm_ui.attach_egg(self.window, self.find("LogoHost"), lambda: self.mode)
        self.find("VersionText").Text = u"v{0}".format(shtm_core.__version__)
        self.find("ThemeChip").Content = theme.label(self.mode)

        self._read_model()
        self._fill_options()
        self._build_sources()
        self._build_template_filters()
        self._build_templates()
        self._build_fill_bar()
        self._build_confirm_header()
        self._build_confirm_rows()
        self._wire()
        self._build_name_push()
        self._fill_find_presets()
        self._paint_template_buttons()
        self._paint_sections()
        self.tab("build")
        self.refresh()

    # ============ reading ============

    def _read_model(self):
        self.views = shtm_model.read_views(self.doc)
        ids = [s["id"] for s in self.sheets]
        viewports, schedules = shtm_model.placed_on_sheets(self.doc, ids)
        self.placements = (
            [{"sheet": v["sheet"], "view": v["view"], "kind": "viewport",
              "id": v["id"]} for v in viewports] +
            [{"sheet": v["sheet"], "view": v["view"], "kind": "schedule",
              "id": v["id"]} for v in schedules])
        # the placements on each sheet, once - the source list repaints on
        # every find keystroke and must not scan every placement each time
        self.placed_by_sheet = {}
        for placed in self.placements:
            self.placed_by_sheet.setdefault(placed["sheet"], []).append(placed)
        self.templates = shtm_batch.template_records(
            shtm_model.view_templates(self.doc))
        self.view_names = [v["name"] for v in self.views.values()]
        self.all_numbers = []
        try:
            from Autodesk.Revit.DB import FilteredElementCollector, ViewSheet
            for sheet in FilteredElementCollector(self.doc).OfClass(ViewSheet):
                self.all_numbers.append(shtm_model.element_sheet_number(sheet))
        except Exception:
            self.all_numbers = [s["number"] for s in self.sheets]
        self.parameters = shtm_model.grouping_parameters(self.doc, self._settings())
        # which sheet parameters this project has, so a name-push parameter it
        # lacks can be said before Create rather than after
        try:
            self.sheet_param_names = set(shtm_model.sheet_parameter_names(self.doc))
        except Exception:
            self.sheet_param_names = set()
        self.keys = shtm_batch.cell_keys(self.parameters)
        self.project_values = {}
        for name in self.parameters:
            try:
                self.project_values[name] = shtm_model.project_values(self.doc, name)
            except Exception:
                self.project_values[name] = []

    def _settings(self):
        """The settings as they are now, not as they were when this window
        opened."""
        if self.get_settings is not None:
            try:
                current = self.get_settings()
                if current is not None:
                    return current
            except Exception:
                pass
        return self.settings

    def _name_slots(self):
        """The sheet name push parameters, in order, blanks kept in place:
        Settings > Push sheet names. Read each time, so a change in Settings
        while this window is open is picked up."""
        return shtm_core.split_slots(self._settings().get("name_parameters"))

    def _pushed_params(self):
        """The name push parameters when the tick is on and any are set, else
        None - which is what tells the build and the preview there is no push."""
        if not self.find("PushNamesBox").IsChecked:
            return None
        slots = self._name_slots()
        return slots if any(slots) else None

    def _delimiter(self):
        return shtm_core.delimiter_of(self._settings().get("name_delimiter"))

    # ---- the sheet names into sheet parameters, on the first page ----

    NAME_PARTS = (u"Part 1", u"Part 2", u"Part 3")

    def _build_name_push(self):
        """The tick, the delimiter and the three parameters, under Text to
        find. The same settings the Preview tick and Settings use: change one
        and the others follow."""
        host = self.find("NamePushHost")
        host.Children.Clear()
        self.name_pickers = []
        names = [NO_PARAMETER] + sorted(self.sheet_param_names or [],
                                        key=shtm_core.natural_key)
        slots = self._name_slots()
        for index, label in enumerate(self.NAME_PARTS):
            line = Grid()
            line.ColumnDefinitions.Add(_col(110))
            line.ColumnDefinitions.Add(_col(None))
            line.Margin = Thickness(0, 0, 0, 4)
            caption = text_block(label, "Lbl.Body")
            caption.VerticalAlignment = VerticalAlignment.Center
            line.Children.Add(caption)
            current = slots[index] if index < len(slots) and slots[index] else NO_PARAMETER
            offered = list(names)
            if current not in offered:
                offered.append(current)
            picker = shtm_ui.ValuePicker(offered, current, strict=True,
                                         placeholder=u"pick a sheet parameter",
                                         on_pick=lambda text: self._name_push_changed())
            Grid.SetColumn(picker.root, 1)
            line.Children.Add(picker.root)
            host.Children.Add(line)
            self.name_pickers.append(picker)
        self.syncing_names = True
        try:
            self.find("NameDelimiterBox").Text = self._delimiter()
            self.find("WriteNamesBox").IsChecked = bool(self.find("PushNamesBox").IsChecked)
        finally:
            self.syncing_names = False
        self._paint_name_push()

    def _name_push_changed(self):
        """A parameter picked or the delimiter typed: saved straight away, so
        the Preview, the run and Settings all see the same thing."""
        if getattr(self, "syncing_names", False):
            return
        chosen = []
        for picker in self.name_pickers:
            text = (picker.text or u"").strip()
            if text == NO_PARAMETER or text in chosen:
                text = u""
            chosen.append(text)
        settings = self._settings()
        settings["name_parameters"] = shtm_core.join_slots(chosen)
        settings["name_delimiter"] = shtm_core.delimiter_stored(
            self.find("NameDelimiterBox").Text)
        try:
            shtm_core.save_settings(settings)
        except Exception:
            pass
        self._paint_name_push()
        self.later()

    @ui_safe
    def _write_names_toggled(self, sender, event):
        """The tick here and the one on the Preview page are one setting."""
        if getattr(self, "syncing_names", False):
            return
        self.syncing_names = True
        try:
            on = bool(sender.IsChecked)
            for name in ("WriteNamesBox", "PushNamesBox"):
                box = self.find(name)
                if not box.Equals(sender):
                    box.IsChecked = on
        finally:
            self.syncing_names = False
        self._paint_name_push()
        self._push_names_changed(sender, event)

    def _paint_name_push(self):
        """Under the pickers: the first source sheet's name split out, so the
        result can be read before anything is made."""
        line = self.find("NamePushExample")
        on = bool(self.find("WriteNamesBox").IsChecked)
        self.find("NamePushBody").Opacity = 1.0 if on else 0.55
        slots = self._name_slots()
        mapped = [p for p in slots if p]
        if not mapped:
            line.Text = u"Pick at least one sheet parameter to write to."
            return
        # the new name, after the find and replace - what is really written;
        # the source's own name until a set makes one
        sample = u""
        if self.records:
            sample = self.records[0]["values"].get(shtm_batch.COL_NAME, u"")
        if not sample:
            sources = self.sources()
            sample = sources[0]["name"] if sources else u""
        if not sample:
            line.Text = u"Split on {0}, in order.".format(self._delimiter())
            return
        parts = shtm_batch.name_push_values(sample, slots, [], self._delimiter())
        line.Text = u"e.g.  {0}\n" .format(sample) + u"\n".join(
            [u"   {0}  \u2192  {1}".format(p, parts.get(p) or u"-") for p in mapped])

    def _preview_columns(self):
        return shtm_batch.preview_columns(self.parameters, self._pushed_params())

    def _paint_push_names(self):
        """The line beside the tick: which parameters, what the first new
        sheet's name will put in each, and any this project does not have."""
        box = self.find("PushNamesBox")
        note = self.find("PushNamesNote")
        mapped = [p for p in self._name_slots() if p]
        if not mapped:
            box.IsEnabled = False
            note.Text = (u"No sheet name parameters are set - choose them under "
                         u"Text to find on the first page, or in Settings.")
            note.SetResourceReference(TextBlock.ForegroundProperty, "OrangeBrush")
            return
        box.IsEnabled = not self.running and not self.finished
        missing = [p for p in mapped
                   if self.sheet_param_names and p not in self.sheet_param_names]
        warning = u""
        if missing:
            warning = u"   {0} {1} not a sheet parameter in this project - nothing " \
                      u"will be written to {2}.".format(
                          u", ".join(missing), u"is" if len(missing) == 1 else u"are",
                          u"it" if len(missing) == 1 else u"them")
        if not box.IsChecked:
            note.Text = u"Off - nothing is written to {0}.{1}".format(
                u", ".join(mapped), warning)
            note.SetResourceReference(TextBlock.ForegroundProperty,
                                      "OrangeBrush" if missing else "MutedBrush")
            return
        first = self.records[0] if self.records else None
        sample = first["values"].get(shtm_batch.COL_NAME, u"") if first else u""
        if sample:
            reserved = [b["grouping"].keys() for b in self.batches
                        if b["index"] == first.get("batch")]
            parts = shtm_batch.name_push_values(
                sample, self._name_slots(), list(reserved[0]) if reserved else [],
                self._delimiter())
            shown = u"   \u00b7   ".join([u"{0}: {1}".format(p, parts.get(p) or u"-")
                                         for p in mapped])
            note.Text = u"Split on {0} :   {1}   \u2192   {2}{3}".format(
                self._delimiter(), sample, shown, warning)
        else:
            note.Text = u"Split on {0} into {1}, in order.{2}".format(
                self._delimiter(), u", ".join(mapped), warning)
        note.SetResourceReference(TextBlock.ForegroundProperty,
                                  "OrangeBrush" if missing else "TextBrush")

    @ui_safe
    def _push_names_changed(self, sender, event):
        """The tick adds or takes away the name-part columns in the preview."""
        self.refresh()
        state = self.preview_state
        if state is not None:
            state.columns = self._preview_columns()
            state.drop_missing_sorts()
            self._group_preview()
            self._fill_preview(True)

    def _presets(self):
        return shtm_batch.presets_from_text(self._settings().get("template_presets"))

    def sources(self):
        """The ticked sheets, in drawing-number order."""
        picked = [s for s in self.sheets if s["id"] in self.ticked]
        picked.sort(key=lambda s: shtm_core.natural_key(s["number"]))
        return picked

    # ============ options ============

    def _fill_options(self):
        settings = self._settings()
        for name, key in [("NumFind", "dup_number_find"),
                          ("NameFind", "dup_name_find"),
                          ("ViewFind", "dup_view_find")]:
            self.find(name).Text = settings.get(key, u"")
        ticks = [
            ("MatchCase", "dup_sheet_match_case"),
            ("PushNamesBox", "dup_write_name_params"),
            ("CopySheetParams", "dup_copy_sheet_params"),
            ("CopyTitleblockParams", "dup_copy_titleblock_params"),
            ("RetainRoomNames", "dup_retain_room_names"),
            ("CopyGridExtents", "dup_grid_extents"),
            ("IncludeLegends", "dup_include_legends"),
            ("StripAnnotation", "dup_strip_annotation"),
            ("StripLines", "dup_strip_lines"),
            ("TagRooms", "dup_tag_rooms"),
            ("DupAllDependents", "dup_all_dependents"),
            ("PlaceNewParent", "dup_place_new_parent"),
        ]
        for name, key in ticks:
            self.find(name).IsChecked = shtm_core.as_bool(settings.get(key))
        detailing = shtm_core.as_bool(settings.get("dup_with_detailing"))
        self.find("DupWithDetailing").IsChecked = detailing
        self.find("DupPlain").IsChecked = not detailing
        for name, key in [("LegendMode", "dup_legends"),
                          ("ScheduleMode", "dup_schedules"),
                          ("DraftingMode", "dup_drafting")]:
            box = self.find(name)
            choices = shtm_core.MODE_CHOICES[key]
            box.Items.Clear()
            for choice in choices:
                box.Items.Add(_combo_item(shtm_core.MODE_LABELS[choice]))
            current = settings.get(key, choices[0])
            box.SelectedIndex = choices.index(current) if current in choices else 0
        self._paint_legend_mode()

    def _paint_legend_mode(self):
        """How a legend comes across only matters when legends come at all."""
        self.find("LegendMode").IsEnabled = bool(self.find("IncludeLegends").IsChecked)

    def _mode(self, control, key):
        choices = shtm_core.MODE_CHOICES[key]
        index = self.find(control).SelectedIndex
        if 0 <= index < len(choices):
            return choices[index]
        return choices[0]

    def options(self):
        return {
            "match_case": bool(self.find("MatchCase").IsChecked),
            "view_match_case": bool(self.find("MatchCase").IsChecked),
            "with_detailing": bool(self.find("DupWithDetailing").IsChecked),
            "retain_room_names": bool(self.find("RetainRoomNames").IsChecked),
            "grid_extents": bool(self.find("CopyGridExtents").IsChecked),
            # a dependent always brings its parent (1.9.0)
            "parents": True,
            "name_delimiter": shtm_core.delimiter_of(
                self._settings().get("name_delimiter")),
            "include_legends": bool(self.find("IncludeLegends").IsChecked),
            "strip_annotation": bool(self.find("StripAnnotation").IsChecked),
            "strip_lines": bool(self.find("StripLines").IsChecked),
            "tag_rooms": bool(self.find("TagRooms").IsChecked),
            "all_dependents": bool(self.find("DupAllDependents").IsChecked),
            "place_new_parent": bool(self.find("PlaceNewParent").IsChecked),
            "write_name_params": bool(self.find("PushNamesBox").IsChecked),
            "copy_sheet_params": bool(self.find("CopySheetParams").IsChecked),
            "copy_titleblock_params": bool(self.find("CopyTitleblockParams").IsChecked),
            # new sheets and views never carry revisions (1.9.0)
            "copy_revisions": False,
            "legends": self._mode("LegendMode", "dup_legends"),
            "schedules": self._mode("ScheduleMode", "dup_schedules"),
            "drafting": self._mode("DraftingMode", "dup_drafting"),
        }

    def finds(self):
        return {"number": self.find("NumFind").Text or u"",
                "name": self.find("NameFind").Text or u"",
                "view": self.find("ViewFind").Text or u"",
                "match_case": bool(self.find("MatchCase").IsChecked)}

    def _remember(self):
        settings = self._settings()
        finds = self.finds()
        options = self.options()
        settings["dup_number_find"] = finds["number"]
        settings["dup_name_find"] = finds["name"]
        settings["dup_view_find"] = finds["view"]
        settings["dup_sheet_match_case"] = shtm_core.bool_text(finds["match_case"])
        for key, option in [("dup_with_detailing", "with_detailing"),
                            ("dup_retain_room_names", "retain_room_names"),
                            ("dup_grid_extents", "grid_extents"),
                            ("dup_include_legends", "include_legends"),
                            ("dup_strip_annotation", "strip_annotation"),
                            ("dup_strip_lines", "strip_lines"),
                            ("dup_tag_rooms", "tag_rooms"),
                            ("dup_all_dependents", "all_dependents"),
                            ("dup_place_new_parent", "place_new_parent"),
                            ("dup_write_name_params", "write_name_params"),
                            ("dup_copy_sheet_params", "copy_sheet_params"),
                            ("dup_copy_titleblock_params", "copy_titleblock_params")]:
            settings[key] = shtm_core.bool_text(options[option])
        settings["dup_legends"] = options["legends"]
        settings["dup_schedules"] = options["schedules"]
        settings["dup_drafting"] = options["drafting"]
        try:
            shtm_core.save_settings(settings)
        except Exception:
            pass

    # ============ column one: sources ============

    def _build_sources(self):
        """One item per sheet, built once. The search hides items rather than
        rebuilding them, so a tick is never lost to a keystroke."""
        listing = self.find("SourceList")
        listing.Items.Clear()
        self.source_items = {}
        ordered = sorted(self.sheets, key=lambda s: shtm_core.natural_key(s["number"]))
        for sheet in ordered:
            box = CheckBox()
            styled(box, "Chk.Flat")
            # the label is painted with the finds: what each one catches shows
            # bold in its colour (see _paint_finds)
            label = TextBlock()
            label.TextTrimming = TextTrimming.CharacterEllipsis
            label.TextWrapping = TextWrapping.NoWrap
            box.Content = label
            box.ToolTip = u"{0}\n{1}".format(sheet["number"], sheet["name"])
            box.IsChecked = sheet["id"] in self.ticked
            box.Checked += self._source_ticked(sheet["id"], True)
            box.Unchecked += self._source_ticked(sheet["id"], False)
            item = ListBoxItem()
            styled(item, "Lst.Item")
            item.Content = box
            listing.Items.Add(item)
            self.source_items[sheet["id"]] = (item, box, sheet)
        self._paint_finds(self.finds(), force=True)
        bar = self.find("PickedOnlyBar")
        if self.picked_ids:
            bar.Visibility = Visibility.Visible
            self.find("PickedOnlyBox").Content = u"Only the {0} selected".format(
                shtm_core.plural(len(self.picked_ids), u"sheet"))
            self.find("PickedOnlyBox").IsChecked = True
        else:
            bar.Visibility = Visibility.Collapsed
        self._filter_sources()
        self._count_sources()

    def _source_ticked(self, sheet_id, on):
        @ui_safe
        def handler(sender, event):
            if on:
                self.ticked.add(sheet_id)
            else:
                self.ticked.discard(sheet_id)
            if self.bulk:
                return
            self._count_sources()
            self.later()
        return handler

    def _count_sources(self):
        text = u"{0} of {1} ticked".format(
            len(self.ticked), shtm_core.plural(len(self.sheets), u"sheet"))
        self.find("SourceCount").Text = text
        summary = text
        if self._picked_only():
            summary += u"   \u00b7   showing the {0} selected".format(
                len(self.picked_ids))
        self.find("SourcesSummary").Text = summary

    def use_picked(self, picked_ids):
        """Duplicate pressed again with other rows picked in the main table:
        those become the ticked sources and the list shows only them. Left
        alone while a run is going or once it has finished."""
        if self.running or self.finished or not picked_ids:
            return
        self.picked_ids = set(picked_ids)
        self.bulk = True
        try:
            for sheet_id in self.source_items:
                item, box, sheet = self.source_items[sheet_id]
                box.IsChecked = sheet_id in self.picked_ids
        finally:
            self.bulk = False
        self.ticked = set(self.picked_ids)
        self.find("PickedOnlyBar").Visibility = Visibility.Visible
        self.find("PickedOnlyBox").Content = u"Only the {0} selected".format(
            shtm_core.plural(len(self.picked_ids), u"sheet"))
        self.find("PickedOnlyBox").IsChecked = True
        self.open_section("sources")
        self._filter_sources()
        self._count_sources()
        self.refresh()

    def _picked_only(self):
        return bool(self.picked_ids) and bool(self.find("PickedOnlyBox").IsChecked)

    @ui_safe
    def _search_sources(self, sender, event):
        self._filter_sources()

    @ui_safe
    def _picked_only_changed(self, sender, event):
        self._filter_sources()
        self._count_sources()

    def _filter_sources(self):
        """The search and the selected-only tick together decide what the
        list shows. Hiding never unticks: a ticked sheet out of sight is still
        a source."""
        words = (self.find("SourceSearch").Text or u"").strip().lower().split()
        only = self._picked_only()
        for sheet_id in self.source_items:
            item, box, sheet = self.source_items[sheet_id]
            text = u"{0} {1}".format(sheet["number"], sheet["name"]).lower()
            shown = all(word in text for word in words)
            if only and sheet_id not in self.picked_ids:
                shown = False
            item.Visibility = Visibility.Visible if shown else Visibility.Collapsed

    # ---- the found text, highlighted ----

    def _paint_finds(self, finds, force=False):
        """Paint every source sheet's label with what the finds catch, and
        list the views on it underneath, so what will change can be read
        before anything is made.

        The sheet number find shows bold blue, the name find bold orange, and
        in each view the view find bold green. Under every view, muted, what
        the run does to it: a dependent says a copy of its parent comes too, a
        legend says whether it is left off or placed again as it is. A view
        that keeps its name is never marked as caught."""
        options = self.options()
        modes = (options.get("legends"), options.get("schedules"),
                 options.get("drafting"), options.get("include_legends"))
        key = (finds["number"], finds["name"], finds["view"], finds["match_case"],
               modes)
        if key == self.painted_finds and not force:
            return
        self.painted_finds = key
        case = finds["match_case"]
        for sheet_id in self.source_items:
            item, box, sheet = self.source_items[sheet_id]
            label = box.Content
            inlines = label.Inlines
            inlines.Clear()
            _add_spans(inlines, shtm_core.highlight_spans(
                sheet["number"], finds["number"], case), "BlueBrush")
            inlines.Add(Run(u"   "))
            _add_spans(inlines, shtm_core.highlight_spans(
                sheet["name"], finds["name"], case), "OrangeBrush")
            lines, more = shtm_batch.source_view_lines(
                sheet_id, self.placed_by_sheet.get(sheet_id, []), self.views, options,
                finds["view"], case)
            for line in lines:
                inlines.Add(LineBreak())
                lead = _small_run(u"      \u25B8  ", "MutedBrush")
                inlines.Add(lead)
                kept = line["action"] in (shtm_plan.REUSE, shtm_plan.SKIP)
                _add_spans(inlines, line["spans"], "FoundGreen", 11,
                           "MutedBrush" if kept else None)
                if line["note"]:
                    inlines.Add(_small_run(u"   \u00b7  " + line["note"], "MutedBrush"))
            if more:
                inlines.Add(LineBreak())
                inlines.Add(_small_run(u"      +{0} more view{1}".format(
                    more, u"" if more == 1 else u"s"), "MutedBrush"))
            if not lines:
                inlines.Add(LineBreak())
                inlines.Add(_small_run(u"      no views on this sheet", "MutedBrush"))

    # ---- the three groups ----

    def _toggle_section(self, key):
        @ui_safe
        def handler(sender, event):
            self.open_section(key, not self.sections.get(key))
        return handler

    def open_section(self, key, opened=True):
        self.sections[key] = bool(opened)
        self._paint_sections()

    def _paint_sections(self):
        """An open group shares the height with any other open one; a shut
        group is just its heading. The chevron points down when open."""
        weights = {"sources": 1.0, "templates": 1.0, "sets": 1.4}
        for key, name in (("sources", "Sources"), ("templates", "Templates"),
                          ("sets", "Sets")):
            opened = self.sections.get(key)
            self.find(name + "Body").Visibility = (Visibility.Visible if opened
                                                   else Visibility.Collapsed)
            row = self.find(name + "Row")
            row.Height = (GridLength(weights[key], GridUnitType.Star) if opened
                          else GridLength.Auto)
            self.find(name + "Chevron").RenderTransform = RotateTransform(
                90 if opened else 0)

    def _tick_shown(self, on):
        """Every box is set with the per-tick work held off, then the work is
        done once."""
        self.bulk = True
        try:
            for sheet_id in self.source_items:
                item, box, sheet = self.source_items[sheet_id]
                if on and item.Visibility != Visibility.Visible:
                    continue
                box.IsChecked = on
        finally:
            self.bulk = False
        self._count_sources()
        self.refresh()

    # ============ column two: view templates ============

    def _build_template_filters(self):
        family = self.find("FamilyFilter")
        family.Items.Clear()
        names = shtm_batch.families(self.templates)
        held = _combo_text(family)
        for name in names:
            family.Items.Add(_combo_item(name))
        # Plans to start with; whatever was showing when the list is re-read
        wanted = held if held in names else shtm_batch.default_family(self.templates)
        family.SelectedIndex = names.index(wanted) if wanted in names else 0
        self._fill_type_filter()

    def _fill_type_filter(self):
        box = self.find("TypeFilter")
        held = _combo_text(box)
        box.Items.Clear()
        names = shtm_batch.types_in(self.templates, _combo_text(self.find("FamilyFilter")))
        for name in names:
            box.Items.Add(_combo_item(name))
        box.SelectedIndex = names.index(held) if held in names else 0

    def _build_templates(self):
        header = self.find("TemplateHeader")
        header.ColumnDefinitions.Clear()
        header.Children.Clear()
        # the list always shows its scroll bar, so the heading stops short by
        # that much and its columns sit over the list's
        header.Margin = Thickness(4, 0, 4 + SystemParameters.VerticalScrollBarWidth, 4)
        # the family and type columns as wide as their longest entry
        # capped: the list does not scroll sideways, so any width given here
        # comes out of the template names
        family_w = min(120.0, max(82.0, _widest(
            [(t["family"], 12.5, False) for t in self.templates] + [(u"Family", 11, False)]) + 12))
        type_w = min(150.0, max(104.0, _widest(
            [(t["type"], 12.5, False) for t in self.templates] + [(u"Type", 11, False)]) + 12))
        self.template_widths = (None, family_w, type_w, 30, 18)
        for index, (label, width) in enumerate([(u"Template", None), (u"Family", family_w),
                                                (u"Type", type_w), (u"On", 30),
                                                (u"", 18)]):
            header.ColumnDefinitions.Add(_col(width))
            caption = text_block(label, "Lbl.Muted")
            caption.FontSize = 11
            if index == 0:
                caption.Margin = Thickness(24, 0, 0, 0)
            Grid.SetColumn(caption, index)
            header.Children.Add(caption)

        listing = self.find("TemplateList")
        listing.Items.Clear()
        self.template_items = {}
        self.template_boxes = {}
        self.template_applies = {}
        self.template_marks = {}
        for template in self.templates:
            line = Grid()
            for width in self.template_widths:
                line.ColumnDefinitions.Add(_col(width))
            box = CheckBox()
            styled(box, "Chk.Flat")
            box.Content = _trimmed(template["name"])
            box.ToolTip = template["name"]
            box.Checked += self._template_ticked(template["id"])
            box.Unchecked += ui_safe(lambda s, e: self._count_templates())
            Grid.SetColumn(box, 0)
            line.Children.Add(box)
            for column, text in ((1, template["family"]), (2, template["type"])):
                cell = text_block(text, "Lbl.Muted")
                cell.TextTrimming = TextTrimming.CharacterEllipsis
                cell.VerticalAlignment = VerticalAlignment.Center
                Grid.SetColumn(cell, column)
                line.Children.Add(cell)
            applies = text_block(u"", "Lbl.Muted")
            applies.VerticalAlignment = VerticalAlignment.Center
            applies.ToolTip = (u"How many of the views on the ticked source sheets "
                               u"this template would go on")
            Grid.SetColumn(applies, 3)
            line.Children.Add(applies)
            mark = text_block(u"", "Lbl.Body")
            mark.VerticalAlignment = VerticalAlignment.Center
            mark.SetResourceReference(TextBlock.ForegroundProperty, "OrangeBrush")
            Grid.SetColumn(mark, 4)
            line.Children.Add(mark)
            item = ListBoxItem()
            styled(item, "Lst.Item")
            item.Content = line
            item.ToolTip = (u"Double-click to add it as a set straight away")
            item.MouseDoubleClick += self._template_double_clicked(template)
            item.Tag = template["id"]
            listing.Items.Add(item)
            self.template_items[template["id"]] = (item, template)
            self.template_boxes[template["id"]] = box
            self.template_applies[template["id"]] = applies
            self.template_marks[template["id"]] = mark
        self._filter_templates()
        self._update_applies()
        self._paint_template_presets()

    # ---- duplicate, rename, edit a view template ----

    def _picked_template(self):
        """The template the buttons act on: the one clicked in the list, or
        failing that the only one ticked."""
        item = self.find("TemplateList").SelectedItem
        if item is not None and item.Tag in self.template_items:
            return self.template_items[item.Tag][1]
        ticked = [t for t in self.template_boxes if self.template_boxes[t].IsChecked]
        if len(ticked) == 1:
            return self.template_items[ticked[0]][1]
        return None

    def _paint_template_buttons(self, sender=None, event=None):
        on = self._picked_template() is not None and not self.running
        on = on and self.template_job is not None
        for name in ("TplDuplicateBtn", "TplRenameBtn", "TplEditBtn"):
            self.find(name).IsEnabled = on

    def _send_template_job(self, job, said):
        if self.template_job is None or not self.template_job(job):
            self.find("StatusText").Text = (u"Revit would not take the request - "
                                            u"nothing was changed")
            return
        self.find("StatusText").Text = said

    @ui_safe
    def _duplicate_template(self, sender, event):
        template = self._picked_template()
        if template is None:
            return
        taken = shtm_vt.taken_names(self.doc)
        name = shtm_ui.ask_text(
            self.mode, self.window, u"Duplicate view template",
            u"A copy of '{0}', with every setting and Include tick it has. "
            u"What should the copy be called?".format(template["name"]),
            shtm_core.copy_name(template["name"], set(taken)), u"Duplicate")
        if not name:
            return
        if name.strip().lower() in taken:
            shtm_ui.message(self.mode, self.window, u"That name is taken",
                            u"A view or template is already called '{0}'.".format(name))
            return
        self._send_template_job(
            {"action": "duplicate", "id": template["id"], "name": name,
             "done": self._template_done(template, u"duplicated")},
            u"duplicating {0}...".format(template["name"]))

    @ui_safe
    def _rename_template(self, sender, event):
        template = self._picked_template()
        if template is None:
            return
        name = shtm_ui.ask_text(
            self.mode, self.window, u"Rename view template",
            u"A new name for '{0}'.".format(template["name"]), template["name"],
            u"Rename")
        if not name or name == template["name"]:
            return
        taken = shtm_vt.taken_names(self.doc)
        # its own name does not count: "plan" to "Plan" is a rename
        taken.discard(template["name"].strip().lower())
        if name.strip().lower() in taken:
            shtm_ui.message(self.mode, self.window, u"That name is taken",
                            u"A view or template is already called '{0}'.".format(name))
            return
        self._send_template_job(
            {"action": "rename", "id": template["id"], "name": name,
             "done": self._template_done(template, u"renamed")},
            u"renaming {0}...".format(template["name"]))

    @ui_safe
    def _edit_template(self, sender, event):
        template = self._picked_template()
        if template is None or self.template_job is None:
            return
        if self.template_editor is not None:
            try:
                if self.template_editor.window.IsVisible:
                    self.template_editor.window.Close()
            except Exception:
                pass
        # a window that fails to open says why - 1.9.0's did nothing at all,
        # the error going only to the log
        try:
            editor = shtm_vt.TemplateEditor(
                self.doc, template["id"], self.template_job, self.mode, self.window,
                saved=lambda template_id, report: self._template_done(
                    template, u"edited")(report))
            self.template_editor = editor
            editor.show()
        except Exception:
            text = traceback.format_exc()
            shtm_ui.log(u"the view template editor would not open:\n" + text)
            shtm_ui.message(self.mode, self.window, u"The editor would not open",
                            u"Editing {0} failed before the window could open. "
                            u"Diagnostics in the main window collects this for "
                            u"sending back:\n\n{1}".format(template["name"],
                                                           text[-1500:]))

    def _template_done(self, template, verb):
        """After Revit has run a template job: re-read the templates, carry a
        rename through to the sets and the presets, and say what happened."""
        def done(report):
            problems = report.get("problems") or []
            if not report.get("ok"):
                self.find("StatusText").Text = u"{0} was not {1}: {2}".format(
                    template["name"], verb, u"; ".join(problems))
                return
            new_name = report.get("name")
            old_name = template["name"]
            said = u"{0} {1}".format(old_name, verb)
            if verb == "duplicated":
                said = u"{0} duplicated as {1}".format(old_name, new_name)
            elif new_name and new_name != old_name:
                said = u"{0} {1} - now {2}".format(old_name, verb, new_name)
            if verb == "renamed" or (verb == "edited" and new_name):
                self._carry_rename(template["id"], old_name, new_name)
                if new_name:
                    # a second rename from the same editor starts from this one
                    template["name"] = new_name
            self._reload_templates(select=report.get("id"))
            if report.get("refused"):
                said += u" - {0} would not take".format(
                    shtm_core.plural(len(report["refused"]), u"value"))
            self.find("StatusText").Text = said
        return done

    def _carry_rename(self, template_id, old, new):
        if not new or new == old:
            return
        for row in self.rows:
            if row.get("template_id") == template_id:
                row["template_name"] = new
        settings = self._settings()
        presets = shtm_batch.presets_from_text(settings.get("template_presets"))
        if old in presets and new not in presets:
            presets[new] = presets.pop(old)
            settings["template_presets"] = shtm_batch.presets_to_text(presets)
            try:
                shtm_core.save_settings(settings)
            except Exception:
                pass
        self._build_confirm_rows()

    def _reload_templates(self, select=None):
        """The template list read again, ticks kept, the new or renamed one
        picked and in view."""
        ticked = set([t for t in self.template_boxes if self.template_boxes[t].IsChecked])
        picked = self._picked_template()
        self.templates = shtm_batch.template_records(shtm_model.view_templates(self.doc))
        self._build_template_filters()
        self._build_templates()
        for template_id in ticked:
            box = self.template_boxes.get(template_id)
            if box is not None:
                box.IsChecked = True
        wanted = select or (picked["id"] if picked else None)
        entry = self.template_items.get(wanted)
        if entry is not None:
            item = entry[0]
            if item.Visibility != Visibility.Visible:
                # a copy the filters hide (family, type or search): show it
                self.find("TemplateSearch").Text = u""
                self.find("FamilyFilter").SelectedIndex = 0
                self.find("TypeFilter").SelectedIndex = 0
                self._filter_templates()
            self.find("TemplateList").SelectedItem = item
            try:
                self.find("TemplateList").ScrollIntoView(item)
            except Exception:
                pass
        self._paint_template_buttons()
        self.refresh()

    # ---- saved text to find ----

    def _find_presets(self):
        return shtm_batch.find_presets_from_text(self._settings().get("find_presets"))

    def _fill_find_presets(self, select=None):
        box = self.find("FindPresetBox")
        self.filling_presets = True
        try:
            box.Items.Clear()
            box.Items.Add(_combo_item(u"saved text to find..."))
            names = shtm_batch.sorted_names(self._find_presets().keys())
            for name in names:
                box.Items.Add(_combo_item(name))
            box.SelectedIndex = (names.index(select) + 1) if select in names else 0
        finally:
            self.filling_presets = False
        self.find("FindDeleteBtn").IsEnabled = box.SelectedIndex > 0

    @ui_safe
    def _find_preset_picked(self, sender, event):
        if getattr(self, "filling_presets", False):
            return
        box = self.find("FindPresetBox")
        self.find("FindDeleteBtn").IsEnabled = box.SelectedIndex > 0
        name = _combo_text(box)
        preset = self._find_presets().get(name)
        if box.SelectedIndex <= 0 or preset is None:
            return
        self.find("NumFind").Text = preset["number"]
        self.find("NameFind").Text = preset["name"]
        self.find("ViewFind").Text = preset["view"]
        self.find("MatchCase").IsChecked = preset["match_case"]
        self.find("StatusText").Text = u"text to find from '{0}'".format(name)
        self.later()

    @ui_safe
    def _save_find_preset(self, sender, event):
        finds = self.finds()
        if not any(finds[key] for key in shtm_batch.FIND_KEYS):
            shtm_ui.message(self.mode, self.window, u"Nothing to save",
                            u"Type some text to find first.")
            return
        box = self.find("FindPresetBox")
        current = _combo_text(box) if box.SelectedIndex > 0 else u""
        name = shtm_ui.ask_text(
            self.mode, self.window, u"Save text to find",
            u"Keep these under a name, to fill the boxes in one pick next time:\n\n"
            u"sheet numbers:  {0}\nsheet names:  {1}\nview names:  {2}\n"
            u"match case:  {3}".format(finds["number"] or u"-", finds["name"] or u"-",
                                       finds["view"] or u"-",
                                       u"yes" if finds["match_case"] else u"no"),
            current or finds["name"] or finds["number"], u"Save")
        if not name:
            return
        presets = self._find_presets()
        presets[name] = shtm_batch.find_preset(finds)
        settings = self._settings()
        settings["find_presets"] = shtm_batch.find_presets_to_text(presets)
        try:
            shtm_core.save_settings(settings)
        except Exception:
            pass
        self._fill_find_presets(select=name)
        self.find("StatusText").Text = u"text to find saved as '{0}'".format(name)

    @ui_safe
    def _delete_find_preset(self, sender, event):
        box = self.find("FindPresetBox")
        if box.SelectedIndex <= 0:
            return
        name = _combo_text(box)
        if not shtm_ui.confirm(self.mode, self.window, u"Delete saved text to find",
                               u"Delete '{0}'? The boxes keep what is in them.".format(name),
                               u"Delete"):
            return
        presets = self._find_presets()
        presets.pop(name, None)
        settings = self._settings()
        settings["find_presets"] = shtm_batch.find_presets_to_text(presets)
        try:
            shtm_core.save_settings(settings)
        except Exception:
            pass
        self._fill_find_presets()

    def presets_changed(self):
        """Settings has been applied: repaint everything that shows a preset -
        and the sheet name parameters, which Settings can change too."""
        try:
            self._build_name_push()
        except Exception:
            shtm_ui.log(u"could not rebuild the sheet name parameters")
        self._paint_template_presets()
        self._paint_row_states()

    def _paint_template_presets(self):
        """A star beside every template that has a preset, which says what it
        will fill in."""
        presets = self._presets()
        for template_id in self.template_marks:
            item, template = self.template_items[template_id]
            mark = self.template_marks[template_id]
            preset = presets.get(template["name"])
            if preset:
                mark.Text = PRESET_MARK
                mark.ToolTip = u"Preset: {0}".format(
                    shtm_batch.preset_summary(preset, self.parameters))
            else:
                mark.Text = u""
                mark.ToolTip = None

    def _template_ticked(self, template_id):
        """Ticking a template also picks it, so Duplicate, Rename and Edit act
        on the one just ticked rather than on a row clicked earlier."""
        @ui_safe
        def handler(sender, event):
            entry = self.template_items.get(template_id)
            if entry is not None:
                self.find("TemplateList").SelectedItem = entry[0]
            self._count_templates()
        return handler

    def _template_double_clicked(self, template):
        @ui_safe
        def handler(sender, event):
            if self.running:
                return
            self._add_sets([template])
            event.Handled = True
        return handler

    def _update_applies(self, sources=None):
        if sources is None:
            sources = self.sources()
        counts = shtm_batch.applies_counts(self.templates, sources,
                                           self.placements, self.views)
        for template_id in self.template_items:
            count = counts.get(template_id, 0)
            label = self.template_applies[template_id]
            label.Text = u"{0}".format(count) if sources else u""
            label.SetResourceReference(TextBlock.ForegroundProperty,
                                       "GreenBrush" if count else "MutedBrush")

    @ui_safe
    def _filter_templates(self, sender=None, event=None):
        family = _combo_text(self.find("FamilyFilter")) or shtm_batch.ALL
        type_name = _combo_text(self.find("TypeFilter")) or shtm_batch.ALL
        needle = self.find("TemplateSearch").Text or u""
        shown = set([t["id"] for t in shtm_batch.filter_templates(
            self.templates, family, type_name, needle)])
        for template_id in self.template_items:
            item, template = self.template_items[template_id]
            item.Visibility = (Visibility.Visible if template_id in shown
                               else Visibility.Collapsed)
        self._count_templates(len(shown))

    def _count_templates(self, shown=None):
        ticked = [t for t in self.template_boxes if self.template_boxes[t].IsChecked]
        if shown is None:
            shown = len([1 for t in self.template_items
                         if self.template_items[t][0].Visibility == Visibility.Visible])
        self.find("TemplateCount").Text = u"{0} shown of {1}, {2} ticked".format(
            shown, len(self.templates), len(ticked))
        if not self.templates:
            self.find("TemplateCount").Text = u"this project has no view templates"
        self.find("TemplatesSummary").Text = self.find("TemplateCount").Text
        self.find("PushBtn").IsEnabled = bool(ticked) and not self.running
        self._paint_template_buttons()

    @ui_safe
    def _family_changed(self, sender, event):
        self._fill_type_filter()
        self._filter_templates()

    @ui_safe
    def _push(self, sender, event):
        """The ticked templates become sets in the table on the right, in the
        order they are listed, and the ticks are cleared - a template still
        ticked after it has been added reads as not yet added."""
        chosen = []
        for template in self.templates:
            box = self.template_boxes.get(template["id"])
            if box is None or not box.IsChecked:
                continue
            chosen.append(template)
            box.IsChecked = False
        self._add_sets(chosen)
        if chosen:
            # done with the templates for now: shut them, the sets are open
            self.open_section("templates", False)

    def _add_sets(self, templates):
        """One new set per template, each filled from its preset when it has
        one."""
        if not templates:
            return
        sources = self.sources()
        presets = self._presets()
        from_preset = 0
        for template in templates:
            preset = presets.get(template["name"])
            self.rows.append(shtm_batch.new_row(template, sources, self.parameters,
                                                preset))
            if preset:
                from_preset += 1
        self.fill_undo = []
        self._build_confirm_rows()
        # the new sets are wanted in sight
        self.open_section("sets")
        self.refresh()
        said = u"{0} added".format(shtm_core.plural(len(templates), u"set"))
        if from_preset:
            said += u" - {0} filled in from {1}".format(
                from_preset, u"its preset" if from_preset == 1 else u"their presets")
        self.find("StatusText").Text = said
        try:
            self.find("ConfirmScroll").ScrollToEnd()
        except Exception:
            pass

    # ============ column three: the table of sets ============
    #
    # Every editable cell sits in a "shell" - a Border that lights up blue when
    # the cell is picked. Cells are named (row uid, key) so a name survives rows
    # being added, copied or taken out above it; the pure rules in shtm_batch
    # work on (row index, key), and _indexed() converts.
    #
    #   click            pick that cell (and put the cursor in it)
    #   ctrl-click       add or take out a cell
    #   shift-click      every cell between the last one picked and this one
    #   click a heading  the whole column; ctrl-click another heading to add it
    #   Ctrl+Enter       this cell's value into every picked cell
    #   Enter            down a row in the same column; Shift+Enter up
    #   Esc              back to just this cell

    def _widths(self):
        """Each column as wide as its heading and the longest thing in it, so
        nothing is cut off - never narrower than it used to be."""
        measured = getattr(self, "col_widths", None)
        if measured and len(measured) == 6 + len(self.parameters):
            return list(measured)
        return self._default_widths()

    def _default_widths(self):
        return ([W_STRIPE, W_TEMPLATE, W_NUMBER, W_NAME, W_VIEW] +
                [W_PARAM] * len(self.parameters) + [W_ACTIONS])

    def _measure_columns(self):
        """Work the widths out from the text that will be in each column:
        the heading (bold), its hint, and every row's value. True when they
        changed, so the heading has to be built again to match."""
        finds = self.finds()
        wanted = []
        template_texts = [(u"View template", 11.5, True), (u"and its set", 10.5, False)]
        for position, row in enumerate(self.rows):
            template_texts.append((row["template_name"], 12.5, False))
            template_texts.append((u"{0}  \u00b7  set {1}  \u00b7  from preset".format(
                row["type"], position + 1), 11, False))
        wanted.append(_widest(template_texts) + 14)
        for key in self.keys:
            if key in shtm_batch.FIXED_KEYS:
                texts = [(shtm_batch.cell_label(key), 11.5, True),
                         (u"replaces \u201c{0}\u201d".format(finds.get(key) or u""), 10.5,
                          False),
                         (u"no find text - kept as is", 10.5, False)]
                pad = 26
            else:
                texts = [(key, 11.5, True), (u"keeps each sheet's if blank", 10.5, False)]
                pad = 26 + 34   # the picker's caret
            for row in self.rows:
                texts.append((shtm_batch.cell_value(row, key), 12.5, False))
            wanted.append(_widest(texts) + pad)
        defaults = self._default_widths()
        widths = shtm_batch.fit_widths(defaults, [None] + wanted + [None])
        changed = widths != getattr(self, "col_widths", None)
        self.col_widths = widths
        return changed

    def _key_column(self, key):
        return 2 + self.keys.index(key)

    def _build_confirm_header(self):
        header = self.find("ConfirmHeader")
        header.ColumnDefinitions.Clear()
        header.Children.Clear()
        self.header_hints = {}
        self.header_cells = {}
        for width in self._widths():
            header.ColumnDefinitions.Add(_col(width))
        # the rows always show a vertical scroll bar; the heading carries the
        # same width at its end, so both scroll exactly as far sideways
        header.ColumnDefinitions.Add(_col(SystemParameters.VerticalScrollBarWidth))

        title = self._heading(u"View template", u"and its set", None)
        Grid.SetColumn(title, 1)
        header.Children.Add(title)
        for key in self.keys:
            if key in shtm_batch.FIXED_KEYS:
                cell = self._heading(shtm_batch.cell_label(key), u"", key)
                cell.Child.Children[0].SetResourceReference(
                    TextBlock.ForegroundProperty, FIND_COLOURS[key][0])
            else:
                # the full parameter name - the column is wide enough for it
                cell = self._heading(key, u"keeps each sheet's if blank", key)
                cell.ToolTip = u"{0}\nClick to pick the whole column".format(key)
            Grid.SetColumn(cell, self._key_column(key))
            header.Children.Add(cell)

    def _heading(self, text, hint, key):
        """A two-line column heading. The second line says what the column does
        - for the three replacements, what text it replaces, kept up to date as
        the find boxes change."""
        shell = Border()
        shell.Background = Brushes.Transparent
        shell.Padding = Thickness(4, 0, 6, 4)
        shell.CornerRadius = shtm_ui._corner(3)
        panel = StackPanel()
        caption = text_block(text, "Lbl.Section")
        caption.FontSize = 11.5
        caption.TextTrimming = TextTrimming.CharacterEllipsis
        panel.Children.Add(caption)
        line = text_block(hint, "Lbl.Muted")
        line.FontSize = 10.5
        line.TextTrimming = TextTrimming.CharacterEllipsis
        panel.Children.Add(line)
        shell.Child = panel
        if key is not None:
            shell.Cursor = _hand()
            if shell.ToolTip is None:
                shell.ToolTip = u"Click to pick the whole column"
            shell.MouseLeftButtonUp += self._heading_clicked(key)
            self.header_hints[key] = line
            self.header_cells[key] = shell
        return shell

    def _paint_headings(self, finds):
        """The second line of each replacement heading names what it replaces."""
        for key in shtm_batch.FIXED_KEYS:
            line = self.header_hints.get(key)
            if line is None:
                continue
            find = (finds.get(key) or u"").strip()
            if find:
                line.Text = u"replaces “{0}”".format(find)
                line.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush")
            elif key == u"number":
                line.Text = u"set the find text first"
                line.SetResourceReference(TextBlock.ForegroundProperty, "OrangeBrush")
            else:
                line.Text = u"no find text - kept as is"
                line.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush")

    def _build_confirm_rows(self):
        if self._measure_columns():
            self._build_confirm_header()
            self._paint_headings(self.finds())
        host = self.find("ConfirmHost")
        host.Children.Clear()
        self.cell_shells = {}
        self.cell_boxes = {}
        self.row_parts = {}
        for position, row in enumerate(self.rows):
            host.Children.Add(self._confirm_line(position, row))
        empty = not self.rows
        self.find("ConfirmEmpty").Visibility = (Visibility.Visible if empty
                                                else Visibility.Collapsed)
        self.find("ClearSetsBtn").IsEnabled = not empty and not self.running
        # a picked cell whose row has gone is not picked any more
        uids = set([r["uid"] for r in self.rows])
        self.picked = [c for c in self.picked if c[0] in uids]
        if self.anchor is not None and self.anchor[0] not in uids:
            self.anchor = None
        self._paint_picked()
        self._paint_row_states()

    def _confirm_line(self, position, row):
        uid = row["uid"]
        outer = Border()
        outer.SetResourceReference(Border.BorderBrushProperty, "EdgeBrush")
        outer.BorderThickness = Thickness(0, 0, 0, 1)
        outer.Padding = Thickness(0, 5, 0, 5)

        line = Grid()
        for width in self._widths():
            line.ColumnDefinitions.Add(_col(width))
        line.RowDefinitions.Add(_row_def())
        line.RowDefinitions.Add(_row_def())
        line.RowDefinitions.Add(_row_def())

        stripe = Border()
        stripe.Width = 4
        stripe.CornerRadius = shtm_ui._corner(2)
        stripe.HorizontalAlignment = HorizontalAlignment.Left
        Grid.SetRowSpan(stripe, 3)
        line.Children.Add(stripe)

        label = StackPanel()
        label.Margin = Thickness(2, 0, 8, 0)
        label.VerticalAlignment = VerticalAlignment.Center
        name = text_block(row["template_name"], "Lbl.Body")
        name.TextTrimming = TextTrimming.CharacterEllipsis
        name.ToolTip = row["template_name"]
        label.Children.Add(name)
        kind = text_block(u"{0}  ·  set {1}{2}".format(
            row["type"], position + 1,
            u"  ·  from preset" if row.get("from_preset") else u""), "Lbl.Muted")
        kind.FontSize = 11
        kind.TextTrimming = TextTrimming.CharacterEllipsis
        label.Children.Add(kind)
        Grid.SetColumn(label, 1)
        line.Children.Add(label)

        hints = {u"number": u"required", u"name": u"blank keeps it",
                 u"view": u"blank keeps it"}
        for key in self.keys:
            if key in shtm_batch.FIXED_KEYS:
                # in the colour of the find it replaces, the same colour the
                # source list paints that find in
                box = shtm_ui.text_box(hints[key], None, "Txt.Tinted")
                box.Text = shtm_batch.cell_value(row, key)
                accent, tint = FIND_COLOURS[key]
                box.SetResourceReference(Control.BackgroundProperty, tint)
                box.SetResourceReference(Control.BorderBrushProperty, accent)
                control = box
                focusable = box
            else:
                picker = shtm_ui.ValuePicker(
                    self.project_values.get(key, []),
                    shtm_batch.cell_value(row, key), placeholder=u"keep each sheet's")
                picker.box.Height = CELL_HEIGHT
                picker.caret.Height = CELL_HEIGHT
                picker.caret.MinHeight = 0
                control = picker.root
                focusable = picker.box
            focusable.Height = CELL_HEIGHT
            focusable.MinHeight = 0
            focusable.VerticalAlignment = VerticalAlignment.Center
            focusable.TextChanged += self._cell_typed(row, key)
            shell = Border()
            shell.BorderThickness = Thickness(2)
            shell.CornerRadius = shtm_ui._corner(5)
            shell.Margin = Thickness(0, 0, 4, 0)
            shell.BorderBrush = Brushes.Transparent
            shell.VerticalAlignment = VerticalAlignment.Center
            shell.Child = control
            shell.PreviewMouseLeftButtonDown += self._cell_pressed(uid, key)
            shell.PreviewKeyDown += self._cell_key(uid, key)
            shell.IsKeyboardFocusWithinChanged += self._cell_focused(uid, key)
            Grid.SetColumn(shell, self._key_column(key))
            line.Children.Add(shell)
            self.cell_shells[(uid, key)] = shell
            self.cell_boxes[(uid, key)] = focusable

        actions = StackPanel()
        actions.Orientation = Orientation.Horizontal
        actions.VerticalAlignment = VerticalAlignment.Center
        actions.Margin = Thickness(4, 0, 0, 0)
        for glyph, tip, handler in (
                (GLYPH_COPY, u"Add another set from the same template, with these "
                             u"values", self._copy_set(row)),
                (GLYPH_STAR, u"Keep these values as the preset for {0} - it will "
                             u"fill in by itself next time".format(row["template_name"]),
                 self._save_preset(row)),
                (GLYPH_REMOVE, u"Take this set out", self._remove_row(row))):
            action = Button()
            styled(action, "Btn.Glyph")
            action.FontFamily = _icon_font()
            action.FontSize = 12
            action.Content = glyph
            action.ToolTip = tip
            action.Click += handler
            actions.Children.Add(action)
        Grid.SetColumn(actions, len(self._widths()) - 1)
        line.Children.Add(actions)

        status = text_block(u"", "Lbl.Muted")
        status.FontSize = 11
        status.Margin = Thickness(2, 3, 0, 0)
        status.TextTrimming = TextTrimming.CharacterEllipsis
        Grid.SetRow(status, 1)
        Grid.SetColumn(status, 1)
        Grid.SetColumnSpan(status, len(self._widths()) - 2)
        line.Children.Add(status)

        # the view rename, under the sheet example
        views = text_block(u"", "Lbl.Muted")
        views.FontSize = 11
        views.Margin = Thickness(2, 1, 0, 0)
        views.TextTrimming = TextTrimming.CharacterEllipsis
        Grid.SetRow(views, 2)
        Grid.SetColumn(views, 1)
        Grid.SetColumnSpan(views, len(self._widths()) - 2)
        line.Children.Add(views)

        self.row_parts[uid] = (stripe, status, actions.Children[1], views)
        outer.Child = line
        return outer

    def _paint_row_states(self):
        """The stripe down each row and the line under it: green with its first
        sheet before and after when it is ready, orange with what is missing,
        red with why its sheets would clash."""
        states = getattr(self, "row_state_list", [])
        presets = self._presets()
        for index, row in enumerate(self.rows):
            parts = self.row_parts.get(row["uid"])
            if parts is None:
                continue
            stripe, status, star, views = parts
            state, text = states[index] if index < len(states) else ("todo", u"")
            examples = getattr(self, "view_example_list", [])
            example = examples[index] if index < len(examples) else u""
            views.Text = example if state == "ok" else u""
            views.ToolTip = example or None
            brush = {"ok": "GreenBrush", "bad": "RedBrush"}.get(state, "OrangeBrush")
            stripe.SetResourceReference(Border.BackgroundProperty, brush)
            status.Text = text
            status.ToolTip = text
            status.SetResourceReference(
                TextBlock.ForegroundProperty,
                "MutedBrush" if state == "ok" else brush)
            star.Content = (GLYPH_STAR_FULL if row["template_name"] in presets
                            else GLYPH_STAR)
            star.SetResourceReference(
                _foreground(),
                "OrangeBrush" if row["template_name"] in presets else "MutedBrush")

    # ---- picking cells ----

    def _indexed(self, cells):
        where = dict([(row["uid"], index) for index, row in enumerate(self.rows)])
        return [(where[uid], key) for uid, key in cells if uid in where]

    def _uided(self, cells):
        return [(self.rows[index]["uid"], key) for index, key in cells
                if 0 <= index < len(self.rows)]

    def _pick(self, cells, anchor=None):
        self.picked = list(cells)
        if anchor is not None:
            self.anchor = anchor
        self._paint_picked()

    def _cell_pressed(self, uid, key):
        @ui_safe
        def handler(sender, event):
            cell = (uid, key)
            modifiers = Keyboard.Modifiers
            if modifiers & ModifierKeys.Shift and self.anchor is not None:
                span = shtm_batch.cell_range(self._indexed([self.anchor])[0],
                                             self._indexed([cell])[0], self.keys)
                self._pick(self._uided(span))
                # the cursor stays where it was: shift-click picks, it does not
                # start selecting text in the box under the mouse
                event.Handled = True
                self._keep_keyboard(cell)
            elif modifiers & ModifierKeys.Control:
                self._pick(shtm_batch.toggle_cell(self.picked, cell), cell)
                event.Handled = True
                self._keep_keyboard(cell)
            else:
                self._pick([cell], cell)
        return handler

    def _keep_keyboard(self, cell):
        """A ctrl- or shift-click is handled before the box sees it, so the
        keyboard stays where it was. Inside the table that is right; anywhere
        else - a find box, say - the next keystrokes would land there, so the
        clicked cell takes the keyboard instead."""
        if self.find("ConfirmHost").IsKeyboardFocusWithin:
            return
        box = self.cell_boxes.get(cell)
        if box is not None:
            box.Focus()

    def _cell_focused(self, uid, key):
        """Tabbing into a cell picks it, the same as clicking it. A click is
        handled by _cell_pressed already - the mouse is still down when focus
        arrives - so it is left alone here."""
        @ui_safe
        def handler(sender, event):
            if not event.NewValue:
                return
            if Mouse.LeftButton == MouseButtonState.Pressed:
                return
            # only Tab: focus also comes back when the window is switched back
            # to from Revit, and that must not throw away a picked column
            if not Keyboard.IsKeyDown(Key.Tab):
                return
            if (uid, key) not in self.picked:
                self._pick([(uid, key)], (uid, key))
        return handler

    def _heading_clicked(self, key):
        @ui_safe
        def handler(sender, event):
            column = self._uided(shtm_batch.column_cells(len(self.rows), key))
            if Keyboard.Modifiers & ModifierKeys.Control:
                merged = list(self.picked)
                for cell in column:
                    if cell not in merged:
                        merged.append(cell)
                self._pick(merged)
            else:
                self._pick(column, column[0] if column else None)
        return handler

    def _paint_picked(self):
        picked = set(self.picked)
        for cell in self.cell_shells:
            shell = self.cell_shells[cell]
            if cell in picked:
                # the text colour, not blue: the number boxes are blue now
                shell.SetResourceReference(Border.BorderBrushProperty, "TextBrush")
            else:
                shell.BorderBrush = Brushes.Transparent
        keys = set([key for _uid, key in self.picked])
        for key in self.header_cells:
            shell = self.header_cells[key]
            whole = len(self.rows) > 0 and all(
                (row["uid"], key) in picked for row in self.rows)
            if whole:
                shell.SetResourceReference(Border.BackgroundProperty, "SelectionBrush")
            else:
                shell.Background = Brushes.Transparent
        self._paint_fill_bar(keys)

    def _paint_fill_bar(self, keys=None):
        if keys is None:
            keys = set([key for _uid, key in self.picked])
        label = self.find("FillLabel")
        if self.picked:
            label.Text = (u"{0} picked. Type a value and Apply, or Ctrl+Enter in a "
                          u"cell to copy its value to the rest.".format(
                              shtm_batch.selection_label(self._indexed(self.picked))))
            label.SetResourceReference(TextBlock.ForegroundProperty, "TextBrush")
        else:
            label.Text = (u"Pick cells to give them one value: click a cell, "
                          u"Ctrl-click or Shift-click to add more, or click a "
                          u"heading for the whole column.")
            label.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush")
        offered = []
        for key in keys:
            values = (self.project_values.get(key, []) if key not in
                      shtm_batch.FIXED_KEYS else [])
            for value in list(values) + [shtm_batch.cell_value(r, key) for r in self.rows]:
                if value and value not in offered:
                    offered.append(value)
        offered.sort(key=shtm_core.natural_key)
        if self.fill_picker is not None:
            self.fill_picker.set_values(offered)
        many = len(self.picked) > 1
        has = bool(self.picked) and not self.running
        self.find("FillApplyBtn").IsEnabled = has
        self.find("FillClearBtn").IsEnabled = has
        self.find("FillSeriesBtn").IsEnabled = has and many
        self.find("FillUndoBtn").IsEnabled = bool(self.fill_undo) and not self.running

    # ---- putting values into picked cells ----

    def _apply_cells(self, value):
        cells = self._indexed(self.picked)
        if not cells:
            return
        undo = shtm_batch.apply_value(self.rows, cells, value)
        self._after_fill(undo, u"{0} set to “{1}”".format(
            shtm_core.plural(len(undo), u"cell"), value) if value
            else u"{0} cleared".format(shtm_core.plural(len(undo), u"cell")))

    def _after_fill(self, undo, said):
        """Push the changed values into the boxes on screen, remember how to
        take them back, and work the sets out again."""
        if undo:
            # by uid, so a row added or removed since cannot misdirect it
            self.fill_undo.append([(self.rows[i]["uid"], k, old)
                                   for i, k, old in undo])
            del self.fill_undo[:-20]
        self._show_values(undo)
        self.find("StatusText").Text = said if undo else u"nothing needed changing"
        self._paint_fill_bar()
        self.later()

    def _show_values(self, changes):
        """The rows already hold the new values; this makes the boxes show
        them. Setting Text raises TextChanged, which writes the same value back
        - harmless, and it keeps one path from box to row."""
        for index, key, _old in changes or []:
            if not 0 <= index < len(self.rows):
                continue
            row = self.rows[index]
            box = self.cell_boxes.get((row["uid"], key))
            if box is not None:
                box.Text = shtm_batch.cell_value(row, key)

    @ui_safe
    def _fill_apply(self, sender, event):
        self._apply_cells(self.fill_picker.text if self.fill_picker else u"")

    @ui_safe
    def _fill_clear(self, sender, event):
        self._apply_cells(u"")

    @ui_safe
    def _fill_series(self, sender, event):
        undo = shtm_batch.fill_series_cells(self.rows, self._indexed(self.picked))
        self._after_fill(undo, u"{0} filled as a series".format(
            shtm_core.plural(len(undo), u"cell")))

    @ui_safe
    def _fill_undo(self, sender, event):
        if not self.fill_undo:
            return
        last = self.fill_undo.pop()
        where = dict([(row["uid"], index) for index, row in enumerate(self.rows)])
        undo = [(where[uid], key, old) for uid, key, old in last if uid in where]
        shtm_batch.undo_cells(self.rows, undo)
        self._show_values(undo)
        self.find("StatusText").Text = u"{0} put back".format(
            shtm_core.plural(len(undo), u"cell"))
        self._paint_fill_bar()
        self.later()

    def _cell_key(self, uid, key):
        @ui_safe
        def handler(sender, event):
            # a grouping cell's dropdown has a search box of its own, and its
            # keys route through this shell too - Enter there picks from the
            # list, it does not move down a row
            box = self.cell_boxes.get((uid, key))
            if box is None or not box.Equals(event.OriginalSource):
                return
            enter = event.Key in (Key.Enter, Key.Return)
            control = bool(Keyboard.Modifiers & ModifierKeys.Control)
            shift = bool(Keyboard.Modifiers & ModifierKeys.Shift)
            if enter and control:
                # Excel's Ctrl+Enter: this cell's value into every picked cell
                if (uid, key) not in self.picked:
                    self.picked.append((uid, key))
                    self._paint_picked()
                self._apply_cells(box.Text or u"")
                event.Handled = True
            elif enter:
                self._move(uid, key, -1 if shift else 1)
                event.Handled = True
            elif event.Key == Key.Escape and len(self.picked) > 1:
                self._pick([(uid, key)], (uid, key))
                event.Handled = True
        return handler

    def _move(self, uid, key, step):
        """Enter goes down a row in the same column, the way a spreadsheet
        does; Shift+Enter goes up."""
        indexes = [i for i, row in enumerate(self.rows) if row["uid"] == uid]
        if not indexes:
            return
        target = indexes[0] + step
        if not 0 <= target < len(self.rows):
            return
        cell = (self.rows[target]["uid"], key)
        box = self.cell_boxes.get(cell)
        if box is None:
            return
        self._pick([cell], cell)
        box.Focus()
        try:
            box.SelectAll()
        except Exception:
            pass

    def _cell_typed(self, row, key):
        @ui_safe
        def handler(sender, event):
            shtm_batch.set_cell(row, key, sender.Text or u"")
            self.later()
        return handler

    # ---- rows ----

    def _copy_set(self, row):
        @ui_safe
        def handler(sender, event):
            if self.running:
                return
            index = [i for i, r in enumerate(self.rows) if r is row]
            if not index:
                return
            copy = shtm_batch.copy_row(row)
            self.rows.insert(index[0] + 1, copy)
            self.fill_undo = []
            self._build_confirm_rows()
            self.refresh()
            self.find("StatusText").Text = (
                u"another set from {0} added below - change what differs".format(
                    row["template_name"]))
        return handler

    def _save_preset(self, row):
        @ui_safe
        def handler(sender, event):
            settings = self._settings()
            presets = shtm_batch.presets_from_text(settings.get("template_presets"))
            preset = shtm_batch.preset_from_row(row, self.parameters)
            name = row["template_name"]
            if shtm_batch.preset_is_empty(preset):
                self.find("StatusText").Text = (
                    u"nothing on this row to keep - type a value first")
                return
            replacing = name in presets
            presets[name] = shtm_batch.merge_preset(presets.get(name), preset,
                                                    self.parameters)
            settings["template_presets"] = shtm_batch.presets_to_text(presets)
            try:
                shtm_core.save_settings(settings)
            except Exception as exc:
                self.find("StatusText").Text = u"could not save the preset: {0}".format(exc)
                return
            self.find("StatusText").Text = u"{0} preset for {1}: {2}".format(
                u"Updated the" if replacing else u"Saved a",
                name, shtm_batch.preset_summary(presets[name], self.parameters))
            self._paint_row_states()
            self._paint_template_presets()
        return handler

    def _remove_row(self, row):
        @ui_safe
        def handler(sender, event):
            if self.running:
                return
            self.rows = [r for r in self.rows if r is not row]
            self.fill_undo = []
            self._build_confirm_rows()
            self.refresh()
        return handler

    @ui_safe
    def _clear_sets(self, sender, event):
        if self.running or not self.rows:
            return
        if not shtm_ui.confirm(self.mode, self.window, u"Remove all sets",
                               u"Take all {0} out of the table?".format(
                                   shtm_core.plural(len(self.rows), u"set")),
                               u"Remove them", u"Keep them"):
            return
        self.rows = []
        self.fill_undo = []
        self._build_confirm_rows()
        self.refresh()

    # ============ working it out ============

    def later(self):
        """Every keystroke and tick lands here; the work happens 250ms after
        the last one."""
        self.timer.Stop()
        self.timer.Start()

    def refresh(self):
        if self.running or self.finished:
            return
        sources = self.sources()
        finds = self.finds()
        self._update_applies(sources)
        self.batches, self.records = shtm_batch.build(
            sources, self.rows, finds, self.placements, self.views, self.options(),
            self.parameters, self.all_numbers, self.view_names,
            self._pushed_params())
        self.reasons = shtm_batch.readiness(sources, self.rows, finds, self.records)
        self.find("FindExample").Text = shtm_batch.example(sources, self.rows, finds)
        self.find("ConfirmCount").Text = u"{0}  \u00d7  {1}  =  {2}".format(
            shtm_core.plural(len(self.rows), u"set"),
            shtm_core.plural(len(sources), u"source sheet"),
            shtm_core.plural(len(self.records), u"new sheet"))
        self.find("SetsSummary").Text = (self.find("ConfirmCount").Text if self.rows
                                         else u"none yet - add view templates")
        self._paint_finds(finds)
        self.by_key = dict([(r["id"], r) for r in self.records])
        self.row_state_list = shtm_batch.row_states(self.rows, self.records, finds)
        self.view_example_list = shtm_batch.view_examples(self.rows, self.batches)
        self._paint_headings(finds)
        # a new find changes what the headings say, and so how wide they are
        measured = (finds["number"], finds["name"], finds["view"])
        if self.rows and measured != getattr(self, "measured_finds", None):
            self.measured_finds = measured
            if self._measure_columns():
                self._build_confirm_header()
                self._paint_headings(finds)
                self._build_confirm_rows()
        self._paint_row_states()
        self._paint_push_names()
        self._paint_name_push()
        self._paint_footer()
        if self.current_tab == "preview":
            self._fill_preview()

    def _paint_footer(self):
        ready = not self.reasons
        next_button = self.find("NextBtn")
        prev_button = self.find("PrevBtn")
        run_button = self.find("RunBtn")
        status = self.find("StatusText")

        if self.finished:
            next_button.Visibility = Visibility.Collapsed
            prev_button.Visibility = Visibility.Collapsed
            self.find("CancelBtn").Visibility = Visibility.Collapsed
            styled(run_button, "Btn.Green")
            run_button.Content = u"Close"
            run_button.IsEnabled = True
            return

        on_build = self.current_tab == "build"
        prev_button.IsEnabled = not on_build and not self.running
        next_button.Visibility = Visibility.Visible if on_build else Visibility.Collapsed
        next_button.IsEnabled = on_build and ready and not self.running
        # Next lights up the moment the sets are complete, and only then
        styled(next_button, "Btn.Green" if ready else "Btn.Flat")
        next_button.ToolTip = (u"See every sheet that will be made" if ready
                               else self.reasons[0])

        run_button.Visibility = (Visibility.Collapsed if on_build
                                 else Visibility.Visible)
        can_run = (not on_build) and ready and not self.running
        run_button.IsEnabled = can_run
        styled(run_button, "Btn.Green" if can_run else "Btn.Flat")
        run_button.Content = u"Create {0}".format(
            shtm_core.plural(len(self.records), u"sheet"))

        if self.running:
            return
        if ready:
            status.Text = u"{0} from {1} - ready".format(
                shtm_core.plural(len(self.records), u"new sheet"),
                shtm_core.plural(len(self.rows), u"set"))
            status.SetResourceReference(TextBlock.ForegroundProperty, "GreenBrush")
        else:
            status.Text = u"To go on: " + u"; ".join(self.reasons)
            status.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush")

    # ============ tabs ============

    def tab(self, which):
        if self.running:
            return
        if which == "preview" and self.reasons:
            self._paint_footer()
            return
        self.current_tab = which
        self.find("BuildPane").Visibility = (Visibility.Visible if which == "build"
                                             else Visibility.Collapsed)
        self.find("PreviewPane").Visibility = (Visibility.Visible if which == "preview"
                                               else Visibility.Collapsed)
        for key, name in (("build", "TabBuild"), ("preview", "TabPreview")):
            self.find(name).SetResourceReference(
                _foreground(), "OrangeBrush" if key == which else "MutedBrush")
        if which == "preview":
            self._start_preview()
        self._paint_footer()

    # ============ preview ============

    def _start_preview(self):
        """Sorted and grouped by the series parameter first, then by sheet
        number - the way the drawing register reads."""
        series = shtm_batch.series_parameter(self.parameters)
        state = shtm_rows.GridState()
        state.columns = self._preview_columns()
        state.sorts = [(series, True), (shtm_batch.COL_NUMBER, True)]
        # the sort the preview was left with last time, if its columns are here
        remembered = shtm_core.sorts_from_text(
            self._settings().get("preview_sorts"), state.columns)
        if remembered:
            state.sorts = remembered
        state.group_by_sort = False
        self.preview_state = state
        self._group_preview()
        self._fill_preview(True)

    def _group_preview(self):
        """The preview groups by whatever is the first sort - unless that column
        is unique to each sheet, where a group per row is no grouping at all."""
        state = self.preview_state
        primary = state.sorts[0][0] if state.sorts else None
        unique = (shtm_batch.COL_NUMBER, shtm_batch.COL_NAME, shtm_batch.COL_VIEWS,
                  shtm_batch.COL_STATUS)
        state.group_by = [primary] if primary and primary not in unique else []

    def _preview_changed(self, rebuild_columns=True):
        """A heading was clicked: regroup, and remember the sort for next time."""
        state = self.preview_state
        if state is None:
            return
        self._group_preview()
        settings = self._settings()
        text = shtm_core.sorts_to_text(state.sorts)
        if text != settings.get("preview_sorts", u""):
            settings["preview_sorts"] = text
            try:
                shtm_core.save_settings(settings)
            except Exception:
                pass
        self._fill_preview(rebuild_columns)

    def _fill_preview(self, rebuild_columns=False):
        state = self.preview_state
        if state is None:
            return
        grid = self.find("PreviewGrid")
        if rebuild_columns or not grid.Columns.Count:
            shtm_grid.build_columns(grid, state, self._preview_changed,
                                    self._preview_distinct, self.store)
        self.preview_rows, shown = shtm_grid.compute_rows(self.records, state)
        grid.ItemsSource = None
        grid.ItemsSource = self.preview_rows
        groups = len(set([r.band for r in self.preview_rows if r.band is not None]))
        lead = state.group_by[0] if state.group_by else None
        self.find("PreviewNote").Text = (
            u"{0} will be created{1}. Click any heading to sort by it - "
            u"shift-click for a second level; click a group heading to open or "
            u"close it.".format(
                shtm_core.plural(len(self.records), u"sheet"),
                u", in {0} by {1}".format(shtm_core.plural(groups, u"group"),
                                          _short(lead)) if lead else u""))

    def _preview_distinct(self, key, with_counts=False):
        counts = shtm_rows.values_allowed(self.records, self.preview_state, key)
        if with_counts:
            return counts
        return sorted(counts.keys(), key=shtm_core.natural_key)

    @ui_safe
    def _preview_click(self, sender, event):
        row = shtm_ui.hit_row(event.OriginalSource)
        if row is None:
            return
        item = row.Item
        if getattr(item, "kind", None) != "group":
            return
        collapsed = self.preview_state.collapsed
        if item.key in collapsed:
            collapsed.discard(item.key)
        else:
            collapsed.add(item.key)
        event.Handled = True
        self._fill_preview(False)

    def _expand_preview(self, collapse):
        state = self.preview_state
        if state is None:
            return
        if not collapse:
            state.collapsed = set()
        else:
            state.collapsed = set()
            keys = set([r.key for r in shtm_grid.compute_rows(self.records, state)[0]
                        if r.kind == "group"])
            state.collapsed = keys
        self._fill_preview(False)

    @ui_safe
    def _loading_row(self, sender, event):
        shtm_grid.paint_row(event.Row, event.Row.Item, False)

    # ============ create ============

    @ui_safe
    def _run(self, sender, event):
        if self.finished:
            self.window.Close()
            return
        if self.running or self.reasons or self.launch is None:
            return
        self.refresh()
        if self.reasons:
            return
        self._remember()
        live = [r for r in self.records if r.get("status") != "bad"]
        self.total = len(live)
        self.landed = 0
        self.store.states = {}
        job = {
            "batches": self.batches,
            "name_params": shtm_core.split_slots(
                self._settings().get("name_parameters")),
            "progress": self._progress,
            "on_sheet": self._landed,
            "done": self._finished,
        }
        self.running = True
        self._lock(True)
        self._show_progress(0, u"starting...")
        if not self.launch(job):
            self.running = False
            self._lock(False)
            self.find("ProgressBand").Visibility = Visibility.Collapsed
            self._paint_footer()

    def _lock(self, locked):
        self.find("BuildPane").IsEnabled = not locked
        self.find("TabBuild").IsEnabled = not locked
        self.find("TabPreview").IsEnabled = not locked
        self.find("CancelBtn").IsEnabled = not locked
        self.find("PrevBtn").IsEnabled = not locked
        self.find("PushNamesBox").IsEnabled = not locked
        if locked:
            self.find("RunBtn").IsEnabled = False
            self.find("StatusText").Text = u"creating - Revit is busy until it finishes"

    def _show_progress(self, percent, text):
        band = self.find("ProgressBand")
        band.Visibility = Visibility.Visible
        share = max(0, min(100, int(percent))) / 100.0
        try:
            self.find("ProgressFill").Width = max(0.0, band.ActualWidth) * share
        except Exception:
            pass
        self.find("ProgressText").Text = text

    def _progress(self, percent, done, total, label=u""):
        """Views are made before any sheet, so until the first sheet lands the
        bar says what Revit is doing rather than sitting at 0%."""
        try:
            whole = self.total or 1
            share = self.landed * 100 // whole
            self._show_progress(share, u"{0}%  -  {1} of {2} done  -  now {3} "
                                       u"{4} of {5}".format(
                                           share, self.landed,
                                           shtm_core.plural(whole, u"sheet"), label,
                                           done, total))
            shtm_ui.pump(self.window.Dispatcher)
        except Exception:
            pass

    def _landed(self, row, new_id, reason=u""):
        """One sheet has been made, or refused: paint its row and move the
        bar. Called inside the external event, between transactions."""
        try:
            key = row.get("key")
            record = self.by_key.get(key)
            # a rollback reports a sheet again, as not made: repaint it, but
            # it was already counted once
            if key not in self.store.states:
                self.landed += 1
            if record is not None:
                if new_id is not None:
                    self.store.states[key] = "created"
                    record["values"][shtm_batch.COL_STATUS] = u"created"
                else:
                    self.store.states[key] = "failed"
                    record["values"][shtm_batch.COL_STATUS] = (
                        u"not made - {0}".format(reason) if reason else u"not made")
            total = self.total or 1
            left = max(0, total - self.landed)
            percent = self.landed * 100 // total
            self._show_progress(percent, u"{0}%  -  {1} of {2} done, {3} to go".format(
                percent, self.landed, shtm_core.plural(total, u"sheet"), left))
            grid = self.find("PreviewGrid")
            grid.Items.Refresh()
            target = None
            for item in self.preview_rows:
                if item.kind == "sheet" and item.sheet is record:
                    target = item
                    break
            if target is not None:
                grid.ScrollIntoView(target)
            shtm_ui.pump(self.window.Dispatcher)
        except Exception as exc:
            shtm_ui.log(u"painting a created sheet failed: {0}".format(exc))

    def _finished(self, report):
        self.running = False
        self.finished = True
        made = 0
        for record in self.records:
            state = self.store.states.get(record["id"])
            if state == "created":
                made += 1
            elif state is None and record.get("status") != "bad":
                # a set rolled back as a whole never reported its sheets
                self.store.states[record["id"]] = "failed"
                record["values"][shtm_batch.COL_STATUS] = u"not made - see the results"
        total = len(self.records)
        self._show_progress(100 if made == total else made * 100 // (total or 1),
                            u"{0} of {1} created".format(
                                made, shtm_core.plural(total, u"sheet")))
        status = self.find("StatusText")
        if made == total:
            status.Text = (u"All {0} created.".format(shtm_core.plural(made, u"sheet"))
                           if made != 1 else u"The sheet was created.")
            status.SetResourceReference(TextBlock.ForegroundProperty, "GreenBrush")
        else:
            status.Text = (u"{0} of {1} created - the red rows were not made; "
                           u"their Status says why".format(
                               made, shtm_core.plural(total, u"sheet")))
            status.SetResourceReference(TextBlock.ForegroundProperty, "OrangeBrush")
        cleaned = [line[len(u"cleaned: "):] for line in (report or {}).get("debug", [])
                   if line.startswith(u"cleaned: ")]
        if cleaned:
            status.Text += u"   Taken off the new views: {0}.".format(cleaned[-1])
        try:
            self.find("PreviewGrid").Items.Refresh()
        except Exception:
            pass
        self.find("TabPreview").IsEnabled = True
        self._paint_footer()

    # ============ wiring ============

    def _wire(self):
        self.timer = shtm_ui.debounce(250, self.refresh)
        pairs = [
            ("CancelBtn", lambda s, e: self.window.Close()),
            ("TabBuild", lambda s, e: self.tab("build")),
            ("TabPreview", lambda s, e: self.tab("preview")),
            ("NextBtn", lambda s, e: self.tab("preview")),
            ("PrevBtn", lambda s, e: self.tab("build")),
            ("RunBtn", self._run),
            ("PushBtn", self._push),
            ("ClearSetsBtn", self._clear_sets),
            ("TickShownBtn", lambda s, e: self._tick_shown(True)),
            ("UntickBtn", lambda s, e: self._tick_shown(False)),
            ("OptionsToggle", self._toggle_options),
            ("ThemeChip", self._cycle_theme),
            ("PreviewExpandBtn", lambda s, e: self._expand_preview(False)),
            ("PreviewCollapseBtn", lambda s, e: self._expand_preview(True)),
            ("FillApplyBtn", self._fill_apply),
            ("FillSeriesBtn", self._fill_series),
            ("FillClearBtn", self._fill_clear),
            ("FillUndoBtn", self._fill_undo),
            ("TplDuplicateBtn", self._duplicate_template),
            ("TplRenameBtn", self._rename_template),
            ("TplEditBtn", self._edit_template),
            ("FindSaveBtn", self._save_find_preset),
            ("FindDeleteBtn", self._delete_find_preset),
        ]
        for name, action in pairs:
            try:
                self.find(name).Click += ui_safe(action)
            except Exception:
                shtm_ui.log(u"could not wire {0}".format(name))

        try:
            for key, name in (("sources", "SourcesHead"), ("templates", "TemplatesHead"),
                              ("sets", "SetsHead")):
                self.find(name).Click += self._toggle_section(key)
            self.find("PickedOnlyBox").Checked += self._picked_only_changed
            self.find("PickedOnlyBox").Unchecked += self._picked_only_changed
        except Exception:
            shtm_ui.log(u"could not wire the groups")
        try:
            self.find("TemplateList").SelectionChanged += ui_safe(
                self._paint_template_buttons)
            self.find("FindPresetBox").SelectionChanged += self._find_preset_picked
        except Exception:
            shtm_ui.log(u"could not wire the template buttons or saved finds")
        try:
            self.find("SourceSearch").TextChanged += ui_safe(self._search_sources)
            self.find("TemplateSearch").TextChanged += self._filter_templates
            self.find("FamilyFilter").SelectionChanged += self._family_changed
            self.find("TypeFilter").SelectionChanged += self._filter_templates
        except Exception:
            shtm_ui.log(u"could not wire the filters")
        try:
            for name in ("NumFind", "NameFind", "ViewFind"):
                self.find(name).TextChanged += ui_safe(lambda s, e: self.later())
            for name in ("MatchCase", "IncludeLegends", "DupAllDependents",
                         "PlaceNewParent", "DupWithDetailing", "DupPlain"):
                self.find(name).Checked += ui_safe(lambda s, e: self.later())
                self.find(name).Unchecked += ui_safe(lambda s, e: self.later())
            for name in ("LegendMode", "ScheduleMode", "DraftingMode"):
                self.find(name).SelectionChanged += ui_safe(lambda s, e: self.later())
            self.find("IncludeLegends").Checked += ui_safe(
                lambda s, e: self._paint_legend_mode())
            self.find("IncludeLegends").Unchecked += ui_safe(
                lambda s, e: self._paint_legend_mode())
        except Exception:
            shtm_ui.log(u"could not wire the find boxes")
        try:
            grid = self.find("PreviewGrid")
            grid.PreviewMouseLeftButtonDown += self._preview_click
            grid.LoadingRow += self._loading_row
            shtm_grid.wire_sorting(grid, _StateProxy(self), self._preview_changed)
        except Exception:
            shtm_ui.log(u"could not wire the preview")
        try:
            self.find("PushNamesBox").Checked += self._write_names_toggled
            self.find("PushNamesBox").Unchecked += self._write_names_toggled
            self.find("WriteNamesBox").Checked += self._write_names_toggled
            self.find("WriteNamesBox").Unchecked += self._write_names_toggled
            self.find("NameDelimiterBox").TextChanged += ui_safe(
                lambda s, e: self._name_push_changed())
        except Exception:
            shtm_ui.log(u"could not wire the sheet name push")
        try:
            self.find("ConfirmScroll").ScrollChanged += self._sync_header
        except Exception:
            shtm_ui.log(u"could not wire the table of sets' scrolling")
        self.window.Closing += self._closing

    @ui_safe
    def _sync_header(self, sender, event):
        """The heading sits outside the rows' scroll so it stays in view going
        down; going sideways it follows them.

        ScrollChanged bubbles: every text box in a row has a scroll viewer of
        its own, and typing past a cell's width scrolls it. Only the table's own
        scroll may move the heading."""
        if not sender.Equals(event.OriginalSource):
            return
        self.find("ConfirmHeaderScroll").ScrollToHorizontalOffset(event.HorizontalOffset)

    def _build_fill_bar(self):
        host = self.find("FillHost")
        host.Children.Clear()
        picker = shtm_ui.ValuePicker([], u"", placeholder=u"value for the picked cells")
        picker.box.Height = CELL_HEIGHT
        picker.box.MinHeight = 0
        picker.caret.Height = CELL_HEIGHT
        picker.caret.MinHeight = 0
        picker.box.KeyDown += self._fill_key
        host.Children.Add(picker.root)
        self.fill_picker = picker
        self._paint_fill_bar()

    @ui_safe
    def _fill_key(self, sender, event):
        """Enter in the fill box applies it, the same as the button."""
        if event.Key in (Key.Enter, Key.Return) and self.picked:
            self._apply_cells(sender.Text or u"")
            event.Handled = True

    @ui_safe
    def _toggle_options(self, sender, event):
        panel = self.find("OptionsPanel")
        opening = panel.Visibility != Visibility.Visible
        panel.Visibility = Visibility.Visible if opening else Visibility.Collapsed
        sender.Content = u"Options  ▾" if opening else u"Options  ▸"

    @ui_safe
    def _cycle_theme(self, sender, event):
        mode = theme.next_mode(self.mode)
        if self.theme_changed is not None:
            self.theme_changed(mode)
        else:
            self.apply_theme(mode)

    def apply_theme(self, mode):
        self.mode = mode
        theme.apply(self.window, mode)
        self.find("ThemeChip").Content = theme.label(mode)
        if self.current_tab == "preview":
            self._fill_preview(True)

    @ui_safe
    def _closing(self, sender, event):
        """Nothing closes this window while Revit is part way through it."""
        if self.running:
            event.Cancel = True
            return
        try:
            self.timer.Stop()
        except Exception:
            pass

    def show(self):
        if self.owner is not None:
            try:
                shtm_ui.bring_back(self.owner)
                self.window.Owner = self.owner
            except Exception:
                pass
        self.window.Show()
        return self.window


class _StateProxy(object):
    """wire_sorting is handed a state when it is wired, and the preview's
    state is replaced every time the preview is entered - so it is handed this
    instead, which always forwards to the current one."""

    def __init__(self, owner):
        self._owner = owner

    def toggle_sort(self, key, add_level=False):
        state = self._owner.preview_state
        if state is None:
            return False
        return state.toggle_sort(key, add_level)

    def __getattr__(self, name):
        state = self._owner.preview_state
        if state is None:
            raise AttributeError(name)
        return getattr(state, name)

    def __setattr__(self, name, value):
        if name == "_owner":
            object.__setattr__(self, name, value)
            return
        setattr(self._owner.preview_state, name, value)


# ====================== helpers ======================

def _row_def():
    definition = RowDefinition()
    definition.Height = GridLength(1, GridUnitType.Auto)
    return definition


def _hand():
    from System.Windows.Input import Cursors
    return Cursors.Hand


def _icon_font():
    """Segoe MDL2 Assets for the row actions, with Segoe UI Symbol behind it."""
    from System.Windows.Media import FontFamily
    return FontFamily(u"Segoe MDL2 Assets, Segoe UI Symbol")


def _small_run(text, brush):
    run = Run(text)
    run.FontSize = 11
    run.SetResourceReference(TextElement.ForegroundProperty, brush)
    return run


def _add_spans(inlines, spans, found_brush, size=None, plain_brush=None):
    """(piece, found) pairs as Runs: a found piece bold in `found_brush`."""
    from System.Windows import FontWeights
    for piece, found in spans:
        run = Run(piece)
        if size:
            run.FontSize = size
        if found:
            run.FontWeight = FontWeights.Bold
            run.SetResourceReference(TextElement.ForegroundProperty, found_brush)
        elif plain_brush:
            run.SetResourceReference(TextElement.ForegroundProperty, plain_brush)
        inlines.Add(run)


def _trimmed(text):
    """A long sheet or template name ends in an ellipsis at the edge of its
    list, rather than being cut through the middle of a letter."""
    block = TextBlock()
    block.Text = text
    block.TextTrimming = TextTrimming.CharacterEllipsis
    return block


def _combo_item(text):
    item = ComboBoxItem()
    item.Content = text
    styled(item, "Cmb.Item")
    return item


def _combo_text(box):
    try:
        item = box.SelectedItem
        if item is None:
            return u""
        return u"{0}".format(item.Content)
    except Exception:
        return u""


def _col(width):
    definition = ColumnDefinition()
    if width is None:
        definition.Width = GridLength(1, GridUnitType.Star)
    else:
        definition.Width = GridLength(float(width))
    return definition


def _widest(texts):
    """The width the widest of (text, size, bold) needs, measured by WPF the
    way it will be drawn - an estimate if measuring is not possible."""
    widest = 0.0
    for text, size, bold in texts:
        widest = max(widest, _text_width(text, size, bold))
    return widest


def _text_width(text, size, bold=False):
    text = u"{0}".format(text or u"")
    if not text:
        return 0.0
    try:
        from System.Windows import Size, FontWeights
        from System.Windows.Media import FontFamily
        block = TextBlock()
        block.Text = text
        block.FontSize = size
        block.FontFamily = FontFamily(u"Segoe UI")
        if bold:
            block.FontWeight = FontWeights.Bold
        block.Measure(Size(float("inf"), float("inf")))
        return float(block.DesiredSize.Width)
    except Exception:
        return len(text) * size * (0.62 if bold else 0.55)


def _short(parameter):
    """BGL_Sheet Discipline reads as Sheet Discipline in a narrow heading; the
    full name is in its tooltip."""
    text = u"{0}".format(parameter)
    if u"_" in text:
        text = text.split(u"_", 1)[1]
    return text.replace(u"_", u" ")


def _foreground():
    from System.Windows.Controls import Control
    return Control.ForegroundProperty
