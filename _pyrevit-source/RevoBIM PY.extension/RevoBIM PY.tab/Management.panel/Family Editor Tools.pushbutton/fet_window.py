# =========================================================================
# Family Editor Tools - the main window
#
# Modeless and owned to Revit's main window, so the family editor stays
# navigable while it is open.  Every write goes out through the
# ExternalEvent in fet_ops.  Nothing here waits for it: Revit raises the
# event on the thread this window lives on, so blocking to wait would be a
# deadlock.
# =========================================================================

import fet_clr  # noqa: F401  - assemblies first, always

import os

from System import Action, TimeSpan
from System.Windows import (GridLength, GridUnitType, Thickness,
                            VerticalAlignment, Visibility)
from System.Windows.Controls import (Border, Canvas, CheckBox,
                                     ColumnDefinition, ComboBox, ComboBoxItem,
                                     Grid, ListBoxItem, TextBlock, TextBox)
from System.Windows.Input import Key
from System.Windows.Media import DoubleCollection
from System.Windows.Shapes import Ellipse, Line as ShapeLine
from System.Windows.Threading import DispatcherTimer

import fet_core
import fet_model
import fet_ops
import fet_params_window
import fet_planes
import fet_ui
import settings_window
import theme

HERE = os.path.dirname(os.path.abspath(__file__))
SEARCH_DEBOUNCE_MS = 220

# A list is a row of live WPF controls, so drawing 663 of them costs real
# time.  Past this the list says so and asks for a narrower search rather
# than quietly taking a second to appear.
MAX_ROWS = 250

# The side rail.  Each entry is (settings key, tab x:Name, panel x:Name).
SECTIONS = (
    (u"builder", u"BuilderTab", u"BuilderPanel"),
    (u"planes", u"PlanesTab", u"PlanesPanel"),
    (u"flex", u"FlexTab", u"FlexPanel"),
    (u"icon", u"IconTab", u"IconPanel"),
)

RAIL_NOTES = {
    u"builder": u"Everything that goes into a family before any geometry "
                u"is drawn.",
    u"planes": u"Reference planes, equalised and labelled. The view opens "
               u"itself.",
    u"flex": u"Drive the family through its parameters. Nothing is left "
             u"changed.",
    u"icon": u"Build the preview view, then name and save the family.",
}

NAME_HINT = (u"Company, family type and discipline are the abbreviations set "
             u"in Family icon settings. Fill all four and Save family "
             u"appears.")

# The three preset tabs, as (kind, source combo, scan button, list, search).
SCAN_TABS = (
    (u"material", u"MaterialSourceCombo", u"MaterialScanButton",
     u"MaterialList", u"MaterialSearch", u"MaterialCountText",
     u"MaterialEmptyText"),
    (u"linestyle", u"LineSourceCombo", u"LineScanButton",
     u"LineList", u"LineSearch", u"LineCountText", u"LineEmptyText"),
    (u"text", u"AnnotationSourceCombo", u"AnnotationScanButton",
     u"TextTypeList", u"AnnotationSearch", u"AnnotationCountText", u""),
    (u"dimension", u"AnnotationSourceCombo", u"AnnotationScanButton",
     u"DimTypeList", u"AnnotationSearch", u"AnnotationCountText", u""),
)

PRESET_SOURCE = u"\x00presets"

# Written when the modeless window opens and cleared by the first handler
# that runs.  If it is still there at the next launch, every handler in the
# window was dead - which looks exactly like a broken tool and cannot
# report itself.
ALIVE_NOTE = os.path.join(fet_core.appdata_root(), u"fet_modeless_opened.txt")


def _note_opened():
    try:
        fet_core.ensure_dir(fet_core.appdata_root())
        handle = open(ALIVE_NOTE, u"wb")
        try:
            handle.write(u"opened".encode(u"utf-8"))
        finally:
            handle.close()
    except Exception:
        pass


def _clear_note():
    try:
        if os.path.isfile(ALIVE_NOTE):
            os.remove(ALIVE_NOTE)
    except Exception:
        pass


def handlers_were_dead():
    return os.path.isfile(ALIVE_NOTE)


class MainWindow(object):

    def __init__(self, uiapp, settings):
        self.uiapp = uiapp
        self.settings = settings
        self.palette_name = theme.resolve(
            fet_core._as_text(settings.get(u"theme", u"follow")))
        self.busy = False
        self.switching = False
        self.building = False

        self.section = fet_core._as_text(
            settings.get(u"last_section", u"builder"))
        if self.section not in [key for key, tab, panel in SECTIONS]:
            self.section = u"builder"
        self.layout_key = fet_core._as_text(
            settings.get(u"last_layout", u"centred_box"))
        if self.layout_key not in fet_planes.layout_keys():
            self.layout_key = fet_planes.layout_keys()[0]
        self.layout_params = fet_core.parse_layout_params(
            settings.get(u"layout_params", u""))
        self.plane_param_combos = {}

        self.staged_rows = []
        self.staged_source = u""
        self.family_params = []
        self.edits = {}
        self.swaps = {}                 # host parameter name -> staged GUID
        self.selected_new = u""
        self.selected_host = u""
        self.family_rows = {}           # parameter name -> its Border
        self._existing_cache = {}       # kind -> what the family already has
        self._shown_counts = {}         # kind -> how many the filter passed
        self._view_cache = {}           # layout view kind -> the view to open

        # Per tab: what was scanned, out of which model, and what is ticked.
        self.scans = {}
        self.ticks = {}
        for kind in (u"material", u"linestyle", u"text", u"dimension"):
            self.scans[kind] = []
            self.ticks[kind] = set()
        self.models = []
        self.last_trace = None
        self.thumbnail_view_id = None
        self.flex_params = []
        self.flex_ticks = set()
        self.flex_ends = {}             # parameter name -> (minimum, maximum)
        self.flex_rows = []

        self.handler, self.event = fet_ops.external_event()

        self.window = fet_ui.load_window(u"FamilyEditorTools.xaml",
                                         self.palette_name)
        self._wire()
        self._fill_templates()
        self._build_legend()
        self._fill_model_combos()
        self.read_family_parameters()
        self._load_presets_into(u"material")
        self._load_presets_into(u"linestyle")
        self._load_presets_into(u"text")
        self._load_presets_into(u"dimension")
        self._refresh_staged()
        self._show_source()
        self._refresh_planes_ui()
        self._refresh_icon_ui()
        self.read_flex_parameters()
        self._refresh_context()
        self._show_section(self.section)
        _note_opened()

    # =====================================================================
    # Wiring
    # =====================================================================
    def _wire(self):
        find = self.window.FindName
        self.find = find
        find(u"VersionText").Text = u"v" + fet_core.__version__
        self.status_text = find(u"StatusText")
        self.results_text = find(u"ResultsText")
        self.context_text = find(u"ContextText")

        icon = fet_ui.load_icon(os.path.join(HERE, u"icon.png"))
        if icon is not None:
            find(u"LogoImage").Source = icon

        self.chrome = fet_ui.Chrome(self.window, find(u"HeaderBar"),
                                    find(u"GripHost"), 980.0, 620.0)

        # Three slow clicks of the logo.
        fet_ui.attach_egg(find(u"LogoHost"), fet_core.TOOL_NAME)

        for key, tab, panel in SECTIONS:
            button = find(tab)
            # The section is carried on the button's own Tag, because
            # 'is' compares PYTHON object identity, not .NET identity, and
            # comparing a handler's sender that way never fires.
            button.Tag = key
            button.Checked += self.on_section

        find(u"CloseButton").Click += self.on_close
        find(u"FullButton").Click += self.on_full
        find(u"ThemeChip").Click += self.on_theme
        find(u"SettingsChip").Click += self.on_settings

        find(u"LoadSpfButton").Click += self.on_load_spf
        find(u"TemplateLoadButton").Click += self.on_template_load
        find(u"TemplateSaveButton").Click += self.on_template_save
        find(u"StagedClearButton").Click += self.on_staged_clear
        find(u"StagedRemoveButton").Click += self.on_staged_remove
        find(u"AddParamsButton").Click += self.on_add_params
        find(u"SwapButton").Click += self.on_swap
        find(u"StagedList").SelectionChanged += self.on_staged_selected

        find(u"FamilySearchBox").TextChanged += self.on_search_typed
        find(u"FamilyKindCombo").SelectionChanged += self.on_family_kind
        find(u"FamilyRefreshButton").Click += self.on_family_refresh
        find(u"FamilyApplyButton").Click += self.on_family_apply
        find(u"FamilyRevertButton").Click += self.on_family_revert
        find(u"FamilyParamList").SelectionChanged += self.on_family_selected

        find(u"MaterialScanButton").Click += self.on_scan
        find(u"MaterialDiagnoseButton").Click += self.on_diagnose
        find(u"LineScanButton").Click += self.on_scan
        find(u"AnnotationScanButton").Click += self.on_scan
        find(u"MaterialScanButton").Tag = u"material"
        find(u"LineScanButton").Tag = u"linestyle"
        find(u"AnnotationScanButton").Tag = u"text|dimension"

        for name, kinds in ((u"MaterialAllButton", u"material"),
                            (u"LineAllButton", u"linestyle"),
                            (u"AnnotationAllButton", u"text|dimension")):
            button = find(name)
            button.Tag = kinds
            button.Click += self.on_tick_all
        for name, kinds in ((u"MaterialNoneButton", u"material"),
                            (u"LineNoneButton", u"linestyle"),
                            (u"AnnotationNoneButton", u"text|dimension")):
            button = find(name)
            button.Tag = kinds
            button.Click += self.on_tick_none

        find(u"MaterialAddButton").Click += self.on_material_add
        find(u"LineAddButton").Click += self.on_line_add
        find(u"AnnotationAddButton").Click += self.on_annotation_add
        find(u"MaterialSearch").TextChanged += self.on_search_typed
        find(u"LineSearch").TextChanged += self.on_search_typed
        find(u"AnnotationSearch").TextChanged += self.on_search_typed

        find(u"FlexRefreshButton").Click += self.on_flex_refresh
        find(u"FlexAllButton").Click += self.on_flex_all
        find(u"FlexNoneButton").Click += self.on_flex_none
        find(u"FlexRunButton").Click += self.on_flex_run
        find(u"FlexCopyButton").Click += self.on_flex_copy
        find(u"FlexSearch").TextChanged += self.on_search_typed
        find(u"FlexStepsBox").TextChanged += self.on_flex_steps_typed
        find(u"FlexFaultsOnlyCheck").Click += self.on_flex_filter
        find(u"FlexAllTypesRadio").Checked += self.on_flex_filter
        find(u"FlexCurrentTypeRadio").Checked += self.on_flex_filter

        find(u"IconSettingsButton").Click += self.on_icon_settings
        find(u"IconApplyButton").Click += self.on_apply_image
        find(u"SaveFamilyButton").Click += self.on_save_family
        find(u"FamilyNameBox").TextChanged += self.on_name_typed
        for name in (u"CompanyCombo", u"TypeCombo", u"DisciplineCombo"):
            combo = find(name)
            combo.SelectionChanged += self.on_name_picked
            combo.AddHandler(TextBox.TextChangedEvent,
                             _text_changed(self.on_name_typed))

        find(u"PrevLayoutButton").Click += self.on_prev_layout
        find(u"NextLayoutButton").Click += self.on_next_layout
        find(u"PlanesApplyButton").Click += self.on_apply_planes
        find(u"PreviewCanvas").SizeChanged += self.on_preview_resized

        self.window.KeyDown += self.on_key
        self.window.Closed += self.on_closed

        self.search_timer = DispatcherTimer()
        self.search_timer.Interval = TimeSpan.FromMilliseconds(SEARCH_DEBOUNCE_MS)
        self.search_timer.Tick += self.on_search_due

        self._set_theme_chip()

        for name, key, default in ((u"WidthBox", u"width_mm", u"600"),
                                   (u"DepthBox", u"depth_mm", u"400"),
                                   (u"HeightBox", u"height_mm", u"900"),
                                   (u"ClearanceBox", u"clearance_mm", u"800"),
                                   (u"RadiusBox", u"radius_mm", u"300")):
            box = find(name)
            box.Text = fet_core._as_text(self.settings.get(key, default))
            box.TextChanged += self.on_size_typed

        find(u"FlexStepsBox").Text = fet_core._as_text(
            self.settings.get(u"flex_steps", u"3"))
        every = fet_core._as_text(self.settings.get(u"flex_types",
                                                    u"all")) == u"all"
        find(u"FlexAllTypesRadio").IsChecked = every
        find(u"FlexCurrentTypeRadio").IsChecked = not every

        find(u"LabelDimsCheck").IsChecked = fet_core.setting_on(
            self.settings, u"label_plane_dims")
        binding = fet_core._as_text(self.settings.get(u"plane_params_binding",
                                                      u"type"))
        find(u"PlaneInstanceRadio").IsChecked = (binding == u"instance")
        find(u"PlaneTypeRadio").IsChecked = (binding != u"instance")

    # =====================================================================
    # The side rail
    # =====================================================================
    def _show_section(self, wanted):
        u"""Setting IsChecked raises Checked, which comes straight back in
        here, so the handler is made a no-op while the tabs are set."""
        self.section = wanted
        self.switching = True
        try:
            for key, tab, panel in SECTIONS:
                on = (key == wanted)
                self.find(tab).IsChecked = on
                self.find(panel).Visibility = (Visibility.Visible if on
                                               else Visibility.Collapsed)
        finally:
            self.switching = False
        self.find(u"RailNoteText").Text = RAIL_NOTES.get(wanted, u"")
        if wanted == u"planes":
            self._refresh_planes_ui()
            self.set_status(u"Ready")
        elif wanted == u"flex":
            if not self.flex_params:
                self.read_flex_parameters()
            self.set_status(u"Ready")
        else:
            self.set_status(u"Ready")

    @fet_ui.ui_safe
    def on_section(self, sender, args):
        if self.switching:
            return
        wanted = fet_core._as_text(sender.Tag)
        if wanted not in [key for key, tab, panel in SECTIONS]:
            return
        self._show_section(wanted)
        self.settings[u"last_section"] = wanted
        fet_core.save_settings(self.settings)

    # =====================================================================
    # Status
    # =====================================================================
    def set_status(self, text, kind=u"muted"):
        _clear_note()
        try:
            self.status_text.Text = text
            key = {u"red": u"RedBrush", u"green": u"GreenBrush",
                   u"orange": u"OrangeBrush",
                   u"swap": u"SwapBrush"}.get(kind, u"MutedBrush")
            self.status_text.SetResourceReference(TextBlock.ForegroundProperty,
                                                  key)
        except Exception:
            pass

    def _refresh_context(self):
        doc = self._active_doc()
        if doc is None or not fet_model.is_family(doc):
            self.context_text.Text = u"Not in the family editor"
            return
        category = fet_model.family_category_name(doc)
        view = fet_model.active_view(_uidoc(self.uiapp))
        kind = fet_model.view_kind(view) or u"other"
        self.context_text.Text = u"{0}  -  {1}  -  {2} view".format(
            fet_model.family_name(doc), category or u"no category", kind)

    def _active_doc(self):
        try:
            return self.uiapp.ActiveUIDocument.Document
        except Exception:
            return None

    # =====================================================================
    # Running work through the ExternalEvent
    # =====================================================================
    def run_job(self, function, title, after=None):
        if self.busy:
            self.set_status(u"Still working on the last one", u"orange")
            return
        self.busy = True
        self.set_status(u"{0}...".format(title))

        def done(results):
            self._on_ui(lambda: self._finish(results, title, after))

        self.handler.queue(function, done)
        try:
            self.event.Raise()
        except Exception:
            self.busy = False
            self.set_status(u"Revit would not take the request", u"red")

    def _on_ui(self, function):
        try:
            self.window.Dispatcher.BeginInvoke(Action(function))
        except Exception:
            try:
                function()
            except Exception:
                pass

    def _finish(self, results, title, after=None):
        self.busy = False
        line = fet_ops.summary_line(results)
        tally = fet_ops.counts(results)
        kind = u"red" if tally[fet_ops.FAILED] else (
            u"orange" if tally[fet_ops.SKIPPED] else u"green")
        self.set_status(u"{0}: {1}".format(title, line), kind)
        self.results_text.Text = line
        self.read_family_parameters()
        self._refresh_staged()
        self._refresh_context()
        if after is not None:
            try:
                after(results)
            except Exception:
                fet_core.log(u"the after step failed")
        self._report(title, results)

    def _report(self, title, results):
        mode = fet_core._as_text(self.settings.get(u"show_results", u"needed"))
        if mode == u"never":
            return
        if mode == u"needed" and not fet_ops.needs_a_look(results):
            return
        lines = []
        for item in results or []:
            mark = {fet_ops.CREATED: u"+", fet_ops.EXISTING: u"=",
                    fet_ops.SKIPPED: u"-", fet_ops.FAILED: u"!"}.get(
                        item.status, u"?")
            text = u"{0} {1}".format(mark, item.subject)
            if item.message:
                text += u" - {0}".format(item.message)
            lines.append(text)
        if not lines:
            lines.append(u"Nothing to do.")
        fet_ui.Prompt(self.palette_name, self.window).say(
            title, u"\n".join(lines))

    def _doc_job(self, worker):
        u"""Wrap a worker so the document is read INSIDE the event, never
        from a handle captured when the window opened."""
        def job(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            return worker(uiapp, doc)
        return job

    # =====================================================================
    # Shared row furniture
    # =====================================================================
    def _chip(self, data_type):
        u"""The data type's colour, the same key on a staged parameter and
        on the family parameter it would replace - which is what makes a
        swap something you can match by eye."""
        chip = Border()
        chip.Width = 9.0
        chip.Height = 16.0
        chip.CornerRadius = _corner(2.0)
        chip.VerticalAlignment = VerticalAlignment.Center
        chip.SetResourceReference(Border.BackgroundProperty,
                                  fet_core.data_brush_key(data_type))
        label = fet_core.KIND_LABEL.get(fet_core.data_kind(data_type), u"Other")
        chip.ToolTip = u"{0}  ({1})".format(data_type or u"unknown", label)
        return chip

    def _binding_combo(self, selected, tag):
        combo = ComboBox()
        combo.Tag = tag
        combo.MinHeight = 26.0
        for key, label in ((u"type", u"Type"), (u"instance", u"Instance")):
            item = ComboBoxItem()
            item.Content = label
            item.Tag = key
            combo.Items.Add(item)
        combo.SelectedIndex = 1 if selected == u"instance" else 0
        return combo

    def _group_combo(self, selected_key, tag):
        u"""Only the current group goes in up front; the rest arrive when
        the list is opened.  Revit offers around two hundred parameter
        groups, and building all of them for every row is what made a
        family with a hundred parameters take a visible moment to draw."""
        combo = ComboBox()
        combo.Tag = tag
        combo.MinHeight = 26.0
        option = fet_model.group_by_key(selected_key)
        item = ComboBoxItem()
        item.Content = option.label if option else u"(no group)"
        item.Tag = option.key if option else u""
        combo.Items.Add(item)
        combo.SelectedIndex = 0
        combo.DropDownOpened += self.on_group_dropdown
        return combo

    @fet_ui.ui_safe
    def on_group_dropdown(self, sender, args):
        if sender.Items.Count > 1:
            return
        current = self._combo_key(sender)
        self.building = True
        try:
            sender.Items.Clear()
            chosen = 0
            for index, option in enumerate(fet_model.group_options()):
                item = ComboBoxItem()
                item.Content = option.label
                item.Tag = option.key
                sender.Items.Add(item)
                if option.key == current:
                    chosen = index
            sender.SelectedIndex = chosen
        finally:
            self.building = False

    def _combo_key(self, combo, fallback=u""):
        item = combo.SelectedItem
        if item is None:
            return fallback
        return fet_core._as_text(item.Tag)

    def _build_legend(self):
        panel = self.find(u"LegendPanel")
        panel.Children.Clear()
        caption = TextBlock()
        caption.Text = u"Data type"
        caption.VerticalAlignment = VerticalAlignment.Center
        caption.Margin = Thickness(0, 0, 8, 0)
        caption.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
        panel.Children.Add(caption)
        for kind in fet_core.KIND_ORDER:
            chip = Border()
            chip.Width = 9.0
            chip.Height = 9.0
            chip.CornerRadius = _corner(2.0)
            chip.VerticalAlignment = VerticalAlignment.Center
            chip.Margin = Thickness(8, 0, 4, 0)
            chip.SetResourceReference(Border.BackgroundProperty,
                                      fet_core.KIND_BRUSH[kind])
            panel.Children.Add(chip)
            label = TextBlock()
            label.Text = fet_core.KIND_LABEL[kind]
            label.FontSize = 10.5
            label.VerticalAlignment = VerticalAlignment.Center
            label.SetResourceReference(TextBlock.ForegroundProperty,
                                       u"MutedBrush")
            panel.Children.Add(label)

    # =====================================================================
    # The family's own parameters
    # =====================================================================
    def _forget_caches(self):
        self._existing_cache = {}
        self._view_cache = {}

    def _already_has(self, kind):
        u"""One collector run per kind per refresh cycle, not one per
        keystroke."""
        if kind not in self._existing_cache:
            doc = self._active_doc()
            self._existing_cache[kind] = (fet_model.existing_names(doc, kind)
                                          if doc else set())
        return self._existing_cache[kind]

    def read_family_parameters(self):
        self._forget_caches()
        doc = self._active_doc()
        self.family_params = fet_model.family_parameters(doc) if doc else []
        self.edits = {}
        names = set([row.name for row in self.family_params])
        # A swap whose host has gone is not a swap any more.
        for host in list(self.swaps.keys()):
            if host not in names:
                guid = self.swaps.pop(host)
                row = self._staged_by_guid(guid)
                if row is not None:
                    row.action = fet_core.ACTION_NEW
                    row.target = u""
        self.selected_host = u""
        self._fill_kind_filter()
        self._refresh_family_list()

    def _fill_kind_filter(self):
        combo = self.find(u"FamilyKindCombo")
        self.building = True
        try:
            previous = self._combo_key(combo)
            combo.Items.Clear()
            item = ComboBoxItem()
            item.Content = u"All data types"
            item.Tag = u""
            combo.Items.Add(item)
            chosen = 0
            kinds = fet_core.kinds_present(
                [row.data_type for row in self.family_params])
            for index, kind in enumerate(kinds, 1):
                entry = ComboBoxItem()
                entry.Content = fet_core.KIND_LABEL[kind]
                entry.Tag = kind
                combo.Items.Add(entry)
                if kind == previous:
                    chosen = index
            combo.SelectedIndex = chosen
        finally:
            self.building = False

    def _family_rows_shown(self):
        needle = self.find(u"FamilySearchBox").Text
        kind = self._combo_key(self.find(u"FamilyKindCombo"))
        out = []
        for row in self.family_params:
            if kind and fet_core.data_kind(row.data_type) != kind:
                continue
            hay = u" ".join([row.name, row.group_label, row.data_type,
                             row.formula, row.value_text])
            if fet_core.matches_search(hay, needle):
                out.append(row)
        return out

    def _refresh_family_list(self):
        listbox = self.find(u"FamilyParamList")
        self.building = True
        self.family_rows = {}
        try:
            listbox.Items.Clear()
            shown = self._family_rows_shown()
            for row in shown[:MAX_ROWS]:
                listbox.Items.Add(self._family_row(row))
        finally:
            self.building = False
        empty = self.find(u"FamilyEmptyText")
        if not self.family_params:
            empty.Text = u"No parameters read. Open a family and press Re-read."
        else:
            empty.Text = u"Nothing in this family matches that filter."
        empty.Visibility = (Visibility.Collapsed if shown
                            else Visibility.Visible)
        self._paint_matches()
        self._refresh_family_footer(len(shown))

    def _refresh_family_footer(self, shown=None):
        pending = len([e for e in self.edits.values() if e.touches_anything()])
        pending += len(self.swaps)
        if shown is None:
            shown = len(self._family_rows_shown())
        drawn = min(shown, MAX_ROWS)
        text = u"{0} of {1} shown".format(shown, len(self.family_params))
        if shown > MAX_ROWS:
            text = u"first {0} of {1} drawn - narrow the search".format(
                drawn, shown)
        self.find(u"FamilyCountText").Text = u"{0}, {1} waiting for Apply".format(
            text, pending)
        self.find(u"FamilyApplyButton").IsEnabled = bool(pending)
        self.find(u"FamilyRevertButton").IsEnabled = bool(pending)

    def _edit_for(self, name):
        edit = self.edits.get(name)
        if edit is None:
            edit = fet_core.ParamEdit(name)
            self.edits[name] = edit
        return edit

    def _family_row(self, row):
        shell = Border()
        shell.Padding = Thickness(4, 2, 4, 2)
        shell.CornerRadius = _corner(3.0)
        shell.BorderThickness = Thickness(1)
        shell.Background = None
        shell.Tag = row.name

        swapped_with = self.swaps.get(row.name, u"")
        if swapped_with:
            grid = _columns((16.0, u"*"))
            grid.Children.Add(self._chip(row.data_type))
            text = TextBlock()
            incoming = self._staged_by_guid(swapped_with)
            text.Text = u"{0}    will become    {1}   ({2})".format(
                row.name, incoming.name if incoming else u"?", row.binding)
            text.Margin = Thickness(4, 0, 4, 0)
            text.VerticalAlignment = VerticalAlignment.Center
            text.TextTrimming = _trim()
            text.SetResourceReference(TextBlock.ForegroundProperty, u"SwapBrush")
            Grid.SetColumn(text, 1)
            grid.Children.Add(text)
            shell.Child = grid
            shell.SetResourceReference(Border.BackgroundProperty, u"SwapRowBg")
        else:
            grid = _columns((16.0, u"*", 104.0, 150.0, u"*"))
            grid.Children.Add(self._chip(row.data_type))

            name = TextBox()
            name.Text = row.name
            name.Tag = row.name
            name.MinHeight = 26.0
            name.Margin = Thickness(4, 0, 4, 0)
            name.IsEnabled = not row.is_builtin
            name.TextChanged += self.on_family_name_typed
            Grid.SetColumn(name, 1)
            grid.Children.Add(name)

            binding = self._binding_combo(row.binding, row.name)
            binding.Margin = Thickness(0, 0, 4, 0)
            binding.IsEnabled = not row.is_builtin
            binding.SelectionChanged += self.on_family_binding
            Grid.SetColumn(binding, 2)
            grid.Children.Add(binding)

            group = self._group_combo(row.group_key, row.name)
            group.Margin = Thickness(0, 0, 4, 0)
            group.IsEnabled = not row.is_builtin
            group.SelectionChanged += self.on_family_group
            Grid.SetColumn(group, 3)
            grid.Children.Add(group)

            formula = TextBox()
            formula.Text = row.formula
            formula.Tag = row.name
            formula.MinHeight = 26.0
            formula.IsEnabled = bool(row.can_have_formula) and not row.is_reporting
            formula.TextChanged += self.on_family_formula
            Grid.SetColumn(formula, 4)
            grid.Children.Add(formula)
            shell.Child = grid

        item = ListBoxItem()
        item.Content = shell
        item.Tag = row.name
        item.Padding = Thickness(4, 2, 4, 2)
        notes = [row.data_type or u"unknown type"]
        if row.is_shared:
            notes.append(u"shared")
        if row.is_builtin:
            notes.append(u"built in - cannot be renamed, regrouped or rebound")
        if row.is_reporting:
            notes.append(u"reporting")
        if row.value_text:
            notes.append(u"current value {0}".format(row.value_text))
        item.ToolTip = u"\n".join(notes)
        self.family_rows[row.name] = shell
        return item

    def _paint_matches(self):
        u"""With a new parameter picked, the family parameters it could
        replace light up.  Same data type kind is the test - anything else
        is a swap that loses the formulas pointing at it."""
        wanted = u""
        if self.selected_new:
            row = self._staged_by_guid(self.selected_new)
            wanted = row.data_type if row is not None else u""
        for name, shell in self.family_rows.items():
            record = self._family_record(name)
            if record is None:
                continue
            if name in self.swaps:
                continue
            match = bool(wanted) and fet_core.swap_is_clean(wanted,
                                                            record.data_type)
            if match and not record.is_builtin:
                shell.SetResourceReference(Border.BackgroundProperty,
                                           u"MatchRowBg")
                shell.SetResourceReference(Border.BorderBrushProperty,
                                           fet_core.data_brush_key(
                                               record.data_type))
            else:
                shell.Background = None
                shell.BorderBrush = None

    @fet_ui.ui_safe
    def on_family_selected(self, sender, args):
        if self.building:
            return
        item = sender.SelectedItem
        self.selected_host = fet_core._as_text(item.Tag) if item else u""
        self._refresh_swap_button()

    @fet_ui.ui_safe
    def on_family_name_typed(self, sender, args):
        if self.building:
            return
        current = fet_core._as_text(sender.Tag)
        edit = self._edit_for(current)
        wanted = fet_core._as_text(sender.Text).strip()
        edit.new_name = wanted if wanted and wanted != current else None
        self._mark(sender, edit.renames)
        self._refresh_family_footer()

    @fet_ui.ui_safe
    def on_family_binding(self, sender, args):
        if self.building:
            return
        current = fet_core._as_text(sender.Tag)
        record = self._family_record(current)
        edit = self._edit_for(current)
        wanted = self._combo_key(sender, u"type")
        edit.binding = None if (record and wanted == record.binding) else wanted
        self._refresh_family_footer()

    @fet_ui.ui_safe
    def on_family_group(self, sender, args):
        if self.building:
            return
        current = fet_core._as_text(sender.Tag)
        record = self._family_record(current)
        edit = self._edit_for(current)
        wanted = self._combo_key(sender)
        edit.group = None if (record and wanted == record.group_key) else wanted
        self._refresh_family_footer()

    @fet_ui.ui_safe
    def on_family_formula(self, sender, args):
        if self.building:
            return
        current = fet_core._as_text(sender.Tag)
        record = self._family_record(current)
        edit = self._edit_for(current)
        wanted = fet_core._as_text(sender.Text)
        edit.formula = None if (record and wanted == record.formula) else wanted
        self._mark(sender, edit.formula is not None)
        self._refresh_family_footer()

    def _mark(self, sender, changed):
        try:
            sender.SetResourceReference(
                TextBox.ForegroundProperty,
                u"OrangeBrush" if changed else u"TextBrush")
        except Exception:
            pass

    def _family_record(self, name):
        for row in self.family_params:
            if row.name == name:
                return row
        return None

    @fet_ui.ui_safe
    def on_family_kind(self, sender, args):
        if self.building:
            return
        self._refresh_family_list()

    @fet_ui.ui_safe
    def on_family_refresh(self, sender, args):
        self.read_family_parameters()
        self._refresh_staged()
        self.set_status(u"{0} parameters read".format(len(self.family_params)))

    @fet_ui.ui_safe
    def on_family_revert(self, sender, args):
        self.edits = {}
        for host, guid in self.swaps.items():
            row = self._staged_by_guid(guid)
            if row is not None:
                row.action = fet_core.ACTION_NEW
                row.target = u""
        self.swaps = {}
        self._refresh_family_list()
        self._refresh_staged()
        self.set_status(u"Pending changes dropped")

    @fet_ui.ui_safe
    def on_family_apply(self, sender, args):
        edits = [e for e in self.edits.values() if e.touches_anything()]
        swap_rows = []
        for host, guid in self.swaps.items():
            row = self._staged_by_guid(guid)
            if row is not None and row.replaces:
                swap_rows.append(row)
        if not edits and not swap_rows:
            self.set_status(u"Nothing waiting", u"orange")
            return
        if swap_rows and (not self.staged_source or
                          not os.path.isfile(self.staged_source)):
            self.set_status(u"The shared parameter file those came from is "
                            u"no longer there", u"red")
            return

        lines = []
        for row in swap_rows:
            lines.append(u"{0}: replaced by {1}, kept as {2}".format(
                row.target, row.name, row.binding))
        for edit in edits:
            bits = []
            if edit.renames:
                bits.append(u"rename to '{0}'".format(edit.new_name))
            if edit.binding is not None:
                bits.append(u"make it {0}".format(edit.binding))
            if edit.group is not None:
                option = fet_model.group_by_key(edit.group)
                bits.append(u"move to {0}".format(
                    option.label if option else edit.group))
            if edit.formula is not None:
                bits.append(u"set the formula" if edit.formula.strip()
                            else u"clear the formula")
            lines.append(u"{0}: {1}".format(edit.current, u", ".join(bits)))
        if not fet_ui.Prompt(self.palette_name, self.window).ask(
                u"Apply these changes?",
                u"\n".join(lines) + u"\n\nNothing has been written yet."):
            return

        path = self.staged_source
        done_guids = [row.guid for row in swap_rows]

        def worker(uiapp, doc):
            return fet_ops.apply_parameter_changes(doc, uiapp.Application,
                                                   path, swap_rows, edits)

        self.swaps = {}
        self.staged_rows = [row for row in self.staged_rows
                            if row.guid not in done_guids]
        self.selected_new = u""
        self.run_job(self._doc_job(worker), u"Applying parameter changes")

    # =====================================================================
    # Staging, and the swap
    # =====================================================================
    @fet_ui.ui_safe
    def on_load_spf(self, sender, args):
        chooser = fet_params_window.SharedParamWindow(
            self.palette_name, self.settings, self.window)
        rows, path = chooser.show()
        self.settings = fet_core.load_settings()
        if not rows:
            return
        self.staged_source = path
        existing = set([row.guid for row in self.staged_rows])
        for row in rows:
            if row.guid not in existing:
                self.staged_rows.append(row)
                existing.add(row.guid)
        self._refresh_staged()
        self._show_source()
        self.set_status(u"{0} parameters staged".format(len(self.staged_rows)),
                        u"green")

    def _show_source(self):
        text = u"No file chosen yet"
        if self.staged_source:
            text = os.path.basename(self.staged_source)
            if not os.path.isfile(self.staged_source):
                text += u"  (missing)"
        self.find(u"SpfPathText").Text = text

    def _refresh_staged(self):
        listbox = self.find(u"StagedList")
        self.building = True
        try:
            listbox.Items.Clear()
            for row in self.staged_rows:
                listbox.Items.Add(self._staged_row(row))
        finally:
            self.building = False
        self.find(u"StagedEmptyText").Visibility = (
            Visibility.Collapsed if self.staged_rows else Visibility.Visible)
        waiting = len([row for row in self.staged_rows if not row.replaces])
        self.find(u"StagedCountText").Text = u"{0} staged, {1} to add".format(
            len(self.staged_rows), waiting)
        self.find(u"AddParamsButton").IsEnabled = bool(waiting)
        self._refresh_swap_button()

    def _staged_row(self, row):
        outer = Grid()
        outer.RowDefinitions.Add(_row_definition())
        outer.RowDefinitions.Add(_row_definition())

        top = _columns((16.0, u"*", 74.0))
        top.Children.Add(self._chip(row.data_type))

        name = TextBlock()
        name.Text = row.name
        name.Margin = Thickness(4, 0, 4, 0)
        name.VerticalAlignment = VerticalAlignment.Center
        name.TextTrimming = _trim()
        Grid.SetColumn(name, 1)
        top.Children.Add(name)

        kind = TextBlock()
        kind.Text = row.data_type
        kind.FontSize = 10.5
        kind.VerticalAlignment = VerticalAlignment.Center
        kind.TextTrimming = _trim()
        kind.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
        Grid.SetColumn(kind, 2)
        top.Children.Add(kind)
        Grid.SetRow(top, 0)
        outer.Children.Add(top)

        bottom = _columns((u"*", u"*"))
        bottom.Margin = Thickness(20, 3, 0, 0)
        if row.replaces:
            note = TextBlock()
            note.Text = u"replaces {0} - takes its {1} setting and group".format(
                row.target, row.binding)
            note.FontSize = 11.0
            note.TextTrimming = _trim()
            note.VerticalAlignment = VerticalAlignment.Center
            note.SetResourceReference(TextBlock.ForegroundProperty, u"SwapBrush")
            Grid.SetColumnSpan(note, 2)
            bottom.Children.Add(note)
        else:
            binding = self._binding_combo(row.binding, row.guid)
            binding.Margin = Thickness(0, 0, 4, 0)
            binding.SelectionChanged += self.on_staged_binding
            Grid.SetColumn(binding, 0)
            bottom.Children.Add(binding)

            group = self._group_combo(row.group, row.guid)
            group.SelectionChanged += self.on_staged_group
            Grid.SetColumn(group, 1)
            bottom.Children.Add(group)

        Grid.SetRow(bottom, 1)
        outer.Children.Add(bottom)

        item = ListBoxItem()
        item.Content = outer
        item.Tag = row.guid
        item.Padding = Thickness(6, 5, 6, 6)
        item.ToolTip = row.guid
        return item

    def _staged_by_guid(self, guid):
        for row in self.staged_rows:
            if row.guid == guid:
                return row
        return None

    @fet_ui.ui_safe
    def on_staged_binding(self, sender, args):
        if self.building:
            return
        row = self._staged_by_guid(fet_core._as_text(sender.Tag))
        if row is not None:
            row.binding = self._combo_key(sender, u"type")

    @fet_ui.ui_safe
    def on_staged_group(self, sender, args):
        if self.building:
            return
        row = self._staged_by_guid(fet_core._as_text(sender.Tag))
        if row is not None:
            row.group = self._combo_key(sender)

    @fet_ui.ui_safe
    def on_staged_selected(self, sender, args):
        if self.building:
            return
        selected = list(sender.SelectedItems)
        self.selected_new = (fet_core._as_text(selected[0].Tag)
                             if len(selected) == 1 else u"")
        self.find(u"StagedRemoveButton").IsEnabled = bool(selected)
        self._paint_matches()
        self._refresh_swap_button()

    def _refresh_swap_button(self):
        button = self.find(u"SwapButton")
        row = self._staged_by_guid(self.selected_new) if self.selected_new \
            else None
        if row is not None and row.replaces:
            button.Content = u"Cancel this swap"
            button.Visibility = Visibility.Visible
            return
        host = self._family_record(self.selected_host)
        ready = (row is not None and host is not None and
                 not host.is_builtin and self.selected_host not in self.swaps)
        button.Content = u"Swap parameters"
        button.Visibility = Visibility.Visible if ready else Visibility.Collapsed

    @fet_ui.ui_safe
    def on_swap(self, sender, args):
        u"""The new parameter takes the type or instance setting and the
        group of the parameter it replaces, because the swap is meant to
        leave the family behaving the way it already did."""
        row = self._staged_by_guid(self.selected_new)
        if row is None:
            return
        if row.replaces:
            self.swaps.pop(row.target, None)
            row.action = fet_core.ACTION_NEW
            row.target = u""
            self._refresh_staged()
            self._refresh_family_list()
            self.set_status(u"Swap cancelled")
            return
        host = self._family_record(self.selected_host)
        if host is None:
            return
        row.action = fet_core.ACTION_REPLACE
        row.target = host.name
        row.binding = host.binding
        if host.group_key:
            row.group = host.group_key
        self.swaps[host.name] = row.guid
        clean = fet_core.swap_is_clean(row.data_type, host.data_type)
        self._refresh_staged()
        self._refresh_family_list()
        message = u"{0} will replace {1} and keep its {2} setting".format(
            row.name, host.name, row.binding)
        if not clean:
            message += u" - different data types, so anything pointing at it " \
                       u"may not survive"
        self.set_status(message, u"swap" if clean else u"orange")

    @fet_ui.ui_safe
    def on_staged_remove(self, sender, args):
        listbox = self.find(u"StagedList")
        guids = set([fet_core._as_text(item.Tag)
                     for item in listbox.SelectedItems])
        if not guids:
            return
        for host in list(self.swaps.keys()):
            if self.swaps[host] in guids:
                self.swaps.pop(host)
        self.staged_rows = [row for row in self.staged_rows
                            if row.guid not in guids]
        self.selected_new = u""
        self._refresh_staged()
        self._refresh_family_list()
        self.set_status(u"{0} removed from staging".format(len(guids)))

    @fet_ui.ui_safe
    def on_staged_clear(self, sender, args):
        self.staged_rows = []
        self.staged_source = u""
        self.swaps = {}
        self.selected_new = u""
        self._refresh_staged()
        self._refresh_family_list()
        self._show_source()
        self.set_status(u"Staging cleared")

    @fet_ui.ui_safe
    def on_add_params(self, sender, args):
        rows = [row for row in self.staged_rows if not row.replaces]
        if not rows:
            self.set_status(u"Everything staged is part of a swap - those go "
                            u"in with Apply changes", u"orange")
            return
        if not self.staged_source or not os.path.isfile(self.staged_source):
            self.set_status(u"The shared parameter file those came from is "
                            u"no longer there", u"red")
            return
        path = self.staged_source
        settings = dict(self.settings)
        done = [row.guid for row in rows]

        def worker(uiapp, doc):
            return fet_ops.add_shared_parameters(doc, uiapp.Application,
                                                 path, rows, settings)
        self.staged_rows = [row for row in self.staged_rows
                            if row.guid not in done]
        self.run_job(self._doc_job(worker), u"Adding shared parameters")

    def _fill_templates(self):
        combo = self.find(u"TemplateCombo")
        combo.Items.Clear()
        for path in fet_core.list_templates():
            item = ComboBoxItem()
            item.Content = os.path.splitext(os.path.basename(path))[0]
            item.Tag = path
            combo.Items.Add(item)
        if combo.Items.Count:
            combo.SelectedIndex = 0
        else:
            combo.IsEnabled = False
            self.find(u"TemplateLoadButton").IsEnabled = False

    @fet_ui.ui_safe
    def on_template_load(self, sender, args):
        item = self.find(u"TemplateCombo").SelectedItem
        if item is None:
            self.set_status(u"No template picked", u"orange")
            return
        name, source, rows, problems = fet_core.load_template(
            fet_core._as_text(item.Tag))
        if not rows:
            self.set_status(u"That template holds no parameters", u"orange")
            return
        self.swaps = {}
        self.staged_rows = rows
        self.staged_source = source
        for row in rows:
            if row.replaces and self._family_record(row.target) is not None:
                self.swaps[row.target] = row.guid
            elif row.replaces:
                row.action = fet_core.ACTION_NEW
                row.target = u""
        self._refresh_staged()
        self._refresh_family_list()
        self._show_source()
        if source and not os.path.isfile(source):
            self.set_status(u"{0} loaded - but its shared parameter file has "
                            u"moved".format(name), u"orange")
        else:
            self.set_status(u"{0} loaded, {1} parameters".format(name,
                                                                 len(rows)),
                            u"green")

    @fet_ui.ui_safe
    def on_template_save(self, sender, args):
        if not self.staged_rows:
            self.set_status(u"Nothing staged to save", u"orange")
            return
        combo = self.find(u"TemplateCombo")
        name = u""
        if combo.SelectedItem is not None:
            name = fet_core._as_text(combo.SelectedItem.Content)
        if not name:
            name = u"Family setup"
        taken = [os.path.splitext(os.path.basename(p))[0]
                 for p in fet_core.list_templates()]
        name = fet_core.unique_name(name, [t for t in taken if t != name])
        path = fet_core.save_template(name, self.staged_source,
                                      self.staged_rows)
        self._fill_templates()
        self.set_status(u"Saved as {0}".format(os.path.basename(path)),
                        u"green")

    # =====================================================================
    # Scanning another open model
    # =====================================================================
    def _fill_model_combos(self):
        doc = self._active_doc()
        self.models = fet_model.open_documents(self.uiapp, doc)
        remembered = fet_core._as_text(
            self.settings.get(u"last_scan_source", u""))
        for name in (u"MaterialSourceCombo", u"LineSourceCombo",
                     u"AnnotationSourceCombo"):
            combo = self.find(name)
            self.building = True
            try:
                combo.Items.Clear()
                item = ComboBoxItem()
                item.Content = u"RevoBIM presets"
                item.Tag = PRESET_SOURCE
                combo.Items.Add(item)
                chosen = 0
                for index, model in enumerate(self.models, 1):
                    entry = ComboBoxItem()
                    entry.Content = (u"{0}  (this family)".format(model.title)
                                     if model.is_current else model.title)
                    entry.Tag = model.key
                    combo.Items.Add(entry)
                    if model.key == remembered:
                        chosen = index
                combo.SelectedIndex = chosen
            finally:
                self.building = False

    def _model_by_key(self, key):
        for model in self.models:
            if model.key == key:
                return model
        return None

    def _load_presets_into(self, kind):
        u"""The preset list is shown as a scan of its own, so the two
        sources behave identically from the list down."""
        items = []
        for preset in fet_core.load_presets(kind):
            detail = u"  ".join([bit for bit in
                                 (preset.get(u"class"), preset.get(u"font"),
                                  preset.get(u"pattern"), preset.get(u"tick"))
                                 if bit])
            items.append(fet_model.ScanItem(kind, preset.name, None, detail,
                                            dict(preset.values)))
        self.scans[kind] = items
        self.ticks[kind] = set()
        self._refresh_scan_list(kind)

    @fet_ui.ui_safe
    def on_scan(self, sender, args):
        kinds = fet_core._as_text(sender.Tag).split(u"|")
        combo_name = {u"material": u"MaterialSourceCombo",
                      u"linestyle": u"LineSourceCombo"}.get(
                          kinds[0], u"AnnotationSourceCombo")
        key = self._combo_key(self.find(combo_name), PRESET_SOURCE)
        if key == PRESET_SOURCE:
            for kind in kinds:
                self._load_presets_into(kind)
            self.set_status(u"Showing the RevoBIM preset list")
            return
        model = self._model_by_key(key)
        if model is None:
            self.set_status(u"That model is no longer open", u"orange")
            self._fill_model_combos()
            return
        self.settings[u"last_scan_source"] = key
        fet_core.save_settings(self.settings)
        self._forget_caches()
        total = 0
        for kind in kinds:
            items = fet_model.scan(model.doc, kind)
            self.scans[kind] = items
            self.ticks[kind] = set()
            self._refresh_scan_list(kind)
            total += len(items)
        self.set_status(u"{0} found in {1}".format(total, model.title),
                        u"green" if total else u"orange")

    def _scan_needle(self, kind):
        name = {u"material": u"MaterialSearch",
                u"linestyle": u"LineSearch"}.get(kind, u"AnnotationSearch")
        return self.find(name).Text

    def _scan_tab(self, kind):
        for row in SCAN_TABS:
            if row[0] == kind:
                return row
        return None

    def _refresh_scan_list(self, kind):
        tab = self._scan_tab(kind)
        if tab is None:
            return
        listbox = self.find(tab[3])
        needle = self._scan_needle(kind)
        already = self._already_has(kind)
        self.building = True
        shown = []
        try:
            listbox.Items.Clear()
            for item in self.scans.get(kind, []):
                if not fet_core.matches_search(item.searchable(), needle):
                    continue
                shown.append(item)
                if len(shown) > MAX_ROWS:
                    continue
                listbox.Items.Add(self._scan_row(kind, item,
                                                 item.name.lower() in already))
        finally:
            self.building = False
        self._shown_counts[kind] = len(shown)
        if tab[6]:
            empty = self.find(tab[6])
            empty.Text = (u"Pick a model at the top and press Scan."
                          if not self.scans.get(kind)
                          else u"Nothing found matches that search.")
            empty.Visibility = (Visibility.Collapsed if shown
                                else Visibility.Visible)
        self._refresh_scan_counts()

    def _count_text(self, kind):
        shown = self._shown_counts.get(kind, len(self.scans.get(kind, [])))
        text = u"{0} ticked of {1}".format(len(self.ticks[kind]),
                                           len(self.scans.get(kind, [])))
        if shown > MAX_ROWS:
            text += u"  -  first {0} of {1} drawn, narrow the search".format(
                MAX_ROWS, shown)
        return text

    def _refresh_scan_counts(self):
        self.find(u"MaterialCountText").Text = self._count_text(u"material")
        self.find(u"LineCountText").Text = self._count_text(u"linestyle")
        self.find(u"AnnotationCountText").Text = \
            u"{0} text and {1} dimension types ticked".format(
                len(self.ticks[u"text"]), len(self.ticks[u"dimension"]))

    def _scan_row(self, kind, item, already):
        grid = _columns((u"*", u"*"))
        check = CheckBox()
        check.Content = item.name
        check.IsChecked = item.name in self.ticks[kind]
        check.Tag = u"{0}|{1}".format(kind, item.name)
        check.VerticalAlignment = VerticalAlignment.Center
        # Still tickable when it is already here: a material sitting in
        # the family with no appearance asset can only be put right by
        # running it again.
        check.Checked += self.on_scan_tick
        check.Unchecked += self.on_scan_tick
        Grid.SetColumn(check, 0)
        grid.Children.Add(check)

        detail = TextBlock()
        if already:
            detail.Text = (u"already here - its appearance can still be "
                           u"brought over" if kind == u"material"
                           else u"already in this family")
        else:
            detail.Text = item.detail
        detail.VerticalAlignment = VerticalAlignment.Center
        detail.TextTrimming = _trim()
        detail.SetResourceReference(
            TextBlock.ForegroundProperty,
            u"GreenBrush" if already else u"MutedBrush")
        Grid.SetColumn(detail, 1)
        grid.Children.Add(detail)

        row = ListBoxItem()
        row.Content = grid
        row.Padding = Thickness(6, 3, 6, 3)
        return row

    @fet_ui.ui_safe
    def on_scan_tick(self, sender, args):
        if self.building:
            return
        kind, name = fet_core._as_text(sender.Tag).split(u"|", 1)
        if sender.IsChecked:
            self.ticks[kind].add(name)
        else:
            self.ticks[kind].discard(name)
        self._refresh_scan_counts()

    @fet_ui.ui_safe
    def on_tick_all(self, sender, args):
        for kind in fet_core._as_text(sender.Tag).split(u"|"):
            already = self._already_has(kind)
            if kind == u"material":
                self.ticks[kind] = set([item.name
                                        for item in self.scans[kind]])
            else:
                self.ticks[kind] = set([item.name for item in self.scans[kind]
                                        if item.name.lower() not in already])
            self._refresh_scan_list(kind)

    @fet_ui.ui_safe
    def on_tick_none(self, sender, args):
        for kind in fet_core._as_text(sender.Tag).split(u"|"):
            self.ticks[kind] = set()
            self._refresh_scan_list(kind)

    def _ticked(self, kind):
        return [item for item in self.scans.get(kind, [])
                if item.name in self.ticks[kind]]

    def _source_doc(self, kind):
        combo_name = {u"material": u"MaterialSourceCombo",
                      u"linestyle": u"LineSourceCombo"}.get(
                          kind, u"AnnotationSourceCombo")
        key = self._combo_key(self.find(combo_name), PRESET_SOURCE)
        if key == PRESET_SOURCE:
            return None
        model = self._model_by_key(key)
        return model.doc if model else None

    def _load_job(self, kind, title):
        items = self._ticked(kind)
        source = self._source_doc(kind)
        if not items:
            self.set_status(u"Nothing is ticked", u"orange")
            return None
        if source is None:
            presets = [fet_core.Preset(kind, item.extra) for item in items]

            def preset_worker(uiapp, doc):
                if kind == u"material":
                    return fet_ops.create_materials(doc, presets)
                if kind == u"linestyle":
                    return fet_ops.create_line_styles(doc, presets)
                if kind == u"text":
                    return fet_ops.create_text_types(doc, presets)
                return fet_ops.create_dimension_types(doc, presets)
            return preset_worker

        def copy_worker(uiapp, doc):
            return fet_ops.load_from_model(doc, source, kind, items)
        return copy_worker

    @fet_ui.ui_safe
    def on_diagnose(self, sender, args):
        items = self._ticked(u"material")
        source = self._source_doc(u"material")
        if not items:
            self.set_status(u"Tick the materials to diagnose first", u"orange")
            return
        if source is None:
            self.set_status(u"Pick an open model at the top - there is "
                            u"nothing to diagnose about the preset list",
                            u"orange")
            return
        if len(items) > 5:
            self.set_status(u"Tick five or fewer - the report is long",
                            u"orange")
            return
        self.run_job(self._doc_job(self._diagnose_worker(source, items)),
                     u"Diagnosing the material transfer", self._diagnose_done)

    def _diagnose_worker(self, source, items):
        def worker(uiapp, doc):
            trace, results = fet_ops.diagnose_materials(doc, source, items)
            self.last_trace = trace
            return results
        return worker

    def _diagnose_done(self, results):
        trace = self.last_trace
        self.last_trace = None
        if trace is None:
            return
        path = u""
        try:
            path = trace.write()
        except Exception:
            path = u""
        copied = False
        try:
            from System.Windows import Clipboard
            Clipboard.SetText(trace.to_text())
            copied = True
        except Exception:
            copied = False
        message = u"The report is {0} lines long.\n\n".format(len(trace.lines))
        if copied:
            message += u"It is on your clipboard - paste it straight into " \
                       u"the chat.\n\n"
        if path:
            message += u"It is also saved at:\n{0}".format(path)
        else:
            message += u"It could not be saved to a file."
        fet_ui.Prompt(self.palette_name, self.window).say(
            u"Material transfer diagnostics", message)

    @fet_ui.ui_safe
    def on_material_add(self, sender, args):
        items = self._ticked(u"material")
        source = self._source_doc(u"material")
        if items and source is not None and fet_core.setting_on(self.settings,
                                                                u"debug"):
            # With the trace switched on, the ordinary load IS the
            # diagnostic run - the same code path, described as it goes.
            self.run_job(self._doc_job(self._diagnose_worker(source, items)),
                         u"Loading materials", self._diagnose_done)
            return
        worker = self._load_job(u"material", u"materials")
        if worker:
            self.run_job(self._doc_job(worker), u"Loading materials")

    @fet_ui.ui_safe
    def on_line_add(self, sender, args):
        worker = self._load_job(u"linestyle", u"line styles")
        if worker:
            self.run_job(self._doc_job(worker), u"Loading line styles")

    @fet_ui.ui_safe
    def on_annotation_add(self, sender, args):
        text_worker = self._load_job(u"text", u"text types") \
            if self._ticked(u"text") else None
        dim_worker = self._load_job(u"dimension", u"dimension types") \
            if self._ticked(u"dimension") else None
        if text_worker is None and dim_worker is None:
            self.set_status(u"Nothing is ticked", u"orange")
            return

        def worker(uiapp, doc):
            results = []
            if text_worker:
                results.extend(text_worker(uiapp, doc))
            if dim_worker:
                results.extend(dim_worker(uiapp, doc))
            return results
        self.run_job(self._doc_job(worker), u"Loading annotation styles")

    # =====================================================================
    # Standard planes
    # =====================================================================
    def _sizes(self):
        find = self.find
        return {
            u"w": fet_core.to_number(find(u"WidthBox").Text, 600.0),
            u"d": fet_core.to_number(find(u"DepthBox").Text, 400.0),
            u"h": fet_core.to_number(find(u"HeightBox").Text, 900.0),
            u"c": fet_core.to_number(find(u"ClearanceBox").Text, 800.0),
            u"r": fet_core.to_number(find(u"RadiusBox").Text, 300.0),
        }

    def _refresh_planes_ui(self):
        find = self.find
        layout = fet_planes.get_layout(self.layout_key)
        find(u"LayoutNameText").Text = layout[u"name"]
        find(u"LayoutNoteText").Text = layout[u"note"]
        find(u"LayoutCountText").Text = u"{0} of {1}".format(
            fet_planes.layout_index(self.layout_key) + 1,
            len(fet_planes.LAYOUTS))

        used = fet_planes.params_used(self.layout_key)
        for key, box in ((u"w", u"WidthBox"), (u"d", u"DepthBox"),
                         (u"h", u"HeightBox"), (u"c", u"ClearanceBox"),
                         (u"r", u"RadiusBox")):
            find(box).IsEnabled = key in used or (
                key == u"d" and self.layout_key == u"crosshair")

        self._build_plane_params(used)

        wanted = layout[u"view"]
        view = fet_model.active_view(_uidoc(self.uiapp))
        ok, why = fet_model.view_is_suitable(view, wanted)
        if ok:
            find(u"LayoutViewText").Text = \
                u"Ready - the active view suits this layout."
            find(u"LayoutViewText").SetResourceReference(
                TextBlock.ForegroundProperty, u"GreenBrush")
        else:
            target = self._layout_view(wanted)
            if target is not None:
                find(u"LayoutViewText").Text = \
                    u"Set out will open '{0}' first.".format(
                        fet_ops.view_name(target))
                find(u"LayoutViewText").SetResourceReference(
                    TextBlock.ForegroundProperty, u"BlueBrush")
            else:
                find(u"LayoutViewText").Text = why[0].upper() + why[1:] + u"."
                find(u"LayoutViewText").SetResourceReference(
                    TextBlock.ForegroundProperty, u"OrangeBrush")
        find(u"PlanesApplyButton").IsEnabled = True
        self._draw_preview()

    def _layout_view(self, wanted):
        u"""Collecting every view in the family on each press of the arrow
        keys is wasted work - the answer only changes when the model
        does."""
        if wanted not in self._view_cache:
            doc = self._active_doc()
            self._view_cache[wanted] = fet_model.find_layout_view(
                doc, wanted, fet_planes.view_names_for(self.layout_key)) \
                if doc else None
        return self._view_cache[wanted]

    def _build_plane_params(self, used):
        u"""One row per parameter this page drives: the label, and a
        dropdown of the family's own length parameters.  A dimension can
        only drive a length, so nothing else is offered."""
        host = self.find(u"PlaneParamHost")
        host.Children.Clear()
        self.plane_param_combos = {}
        if not used:
            note = TextBlock()
            note.Text = u"This page places references only - nothing to drive."
            note.TextWrapping = _wrap()
            note.SetResourceReference(TextBlock.ForegroundProperty,
                                      u"MutedBrush")
            host.Children.Add(note)
            return
        available = fet_model.length_parameters_from(self.family_params)
        chosen = self.layout_params.get(self.layout_key, {})
        for key in used:
            grid = _columns((84.0, u"*"))
            grid.Margin = Thickness(0, 0, 0, 5)
            label = TextBlock()
            label.Text = fet_core.PLANE_PARAM_LABEL.get(key, key)
            label.VerticalAlignment = VerticalAlignment.Center
            Grid.SetColumn(label, 0)
            grid.Children.Add(label)

            combo = ComboBox()
            combo.Tag = key
            combo.MinHeight = 28.0
            default_name = fet_core.layout_param_name({}, self.layout_key,
                                                      key, self.settings)
            first = ComboBoxItem()
            first.Content = u"Create '{0}'".format(default_name)
            first.Tag = fet_core.CREATE_NEW
            combo.Items.Add(first)
            picked = 0
            wanted = chosen.get(key, u"")
            for index, record in enumerate(available, 1):
                entry = ComboBoxItem()
                entry.Content = u"{0}   ({1})".format(record.name,
                                                      record.binding)
                entry.Tag = record.name
                combo.Items.Add(entry)
                if record.name == wanted:
                    picked = index
            combo.SelectedIndex = picked
            combo.SelectionChanged += self.on_plane_param_picked
            Grid.SetColumn(combo, 1)
            grid.Children.Add(combo)
            host.Children.Add(grid)
            self.plane_param_combos[key] = combo

        note = TextBlock()
        note.TextWrapping = _wrap()
        note.FontSize = 11.0
        note.Margin = Thickness(0, 3, 0, 0)
        if [key for key in used
                if fet_core.assigned_param(self.layout_params,
                                           self.layout_key, key)]:
            note.Text = (u"A parameter picked here gets the dimension "
                         u"labelled with it, whatever the tick below says.")
            note.SetResourceReference(TextBlock.ForegroundProperty,
                                      u"GreenBrush")
        else:
            note.Text = (u"Leave one on Create and the tick below decides "
                         u"whether a parameter is made for it.")
            note.SetResourceReference(TextBlock.ForegroundProperty,
                                      u"MutedBrush")
        host.Children.Add(note)

    @fet_ui.ui_safe
    def on_plane_param_picked(self, sender, args):
        if self.building:
            return
        self.building = True
        key = fet_core._as_text(sender.Tag)
        value = self._combo_key(sender, fet_core.CREATE_NEW)
        page = self.layout_params.setdefault(self.layout_key, {})
        if value == fet_core.CREATE_NEW:
            page.pop(key, None)
        else:
            page[key] = value
        self.settings[u"layout_params"] = fet_core.format_layout_params(
            self.layout_params)
        fet_core.save_settings(self.settings)
        self.building = False
        self._build_plane_params(fet_planes.params_used(self.layout_key))

    def _draw_preview(self):
        canvas = self.find(u"PreviewCanvas")
        canvas.Children.Clear()
        width = canvas.ActualWidth
        height = canvas.ActualHeight
        if width < 20 or height < 20:
            return
        side = min(width, height)
        left = (width - side) * 0.5
        top = (height - side) * 0.5

        def place(value, base):
            return base + value * side

        for item in fet_planes.preview_items(self.layout_key, self._sizes()):
            if item[0] == u"plane":
                kind, x1, y1, x2, y2, style, name = item
                line = ShapeLine()
                line.X1 = place(x1, left)
                line.Y1 = place(y1, top)
                line.X2 = place(x2, left)
                line.Y2 = place(y2, top)
                line.StrokeThickness = 1.4 if style == u"face" else 1.0
                key = {u"centre": u"OrangeBrush",
                       u"weak": u"MutedBrush"}.get(style, u"BlueBrush")
                line.SetResourceReference(ShapeLine.StrokeProperty, key)
                if style != u"face":
                    line.StrokeDashArray = DoubleCollection([6.0, 4.0])
                canvas.Children.Add(line)
            elif item[0] == u"dim":
                kind, x1, y1, x2, y2, text, dim_kind = item
                line = ShapeLine()
                line.X1 = place(x1, left)
                line.Y1 = place(y1, top)
                line.X2 = place(x2, left)
                line.Y2 = place(y2, top)
                line.StrokeThickness = 1.0
                line.SetResourceReference(
                    ShapeLine.StrokeProperty,
                    u"GreenBrush" if dim_kind == u"eq" else u"TextBrush")
                canvas.Children.Add(line)
                if text:
                    label = TextBlock()
                    label.Text = text
                    label.FontSize = 10.5
                    label.SetResourceReference(
                        TextBlock.ForegroundProperty,
                        u"GreenBrush" if dim_kind == u"eq" else u"TextBrush")
                    Canvas.SetLeft(label, place((x1 + x2) * 0.5, left) - 18.0)
                    Canvas.SetTop(label, place((y1 + y2) * 0.5, top) - 15.0)
                    canvas.Children.Add(label)
            elif item[0] == u"tick":
                kind, x, y = item
                tick = ShapeLine()
                tick.X1 = place(x, left) - 3.0
                tick.Y1 = place(y, top) - 3.0
                tick.X2 = place(x, left) + 3.0
                tick.Y2 = place(y, top) + 3.0
                tick.StrokeThickness = 1.2
                tick.SetResourceReference(ShapeLine.StrokeProperty,
                                          u"GreenBrush")
                canvas.Children.Add(tick)
            elif item[0] == u"origin":
                kind, x, y = item
                dot = Ellipse()
                dot.Width = 7.0
                dot.Height = 7.0
                dot.SetResourceReference(Ellipse.FillProperty, u"OrangeBrush")
                Canvas.SetLeft(dot, place(x, left) - 3.5)
                Canvas.SetTop(dot, place(y, top) - 3.5)
                canvas.Children.Add(dot)

    @fet_ui.ui_safe
    def on_preview_resized(self, sender, args):
        self._draw_preview()

    def _step_layout(self, delta):
        self.layout_key = fet_planes.step_layout(self.layout_key, delta)
        self.settings[u"last_layout"] = self.layout_key
        fet_core.save_settings(self.settings)
        self._refresh_planes_ui()

    @fet_ui.ui_safe
    def on_prev_layout(self, sender, args):
        self._step_layout(-1)

    @fet_ui.ui_safe
    def on_next_layout(self, sender, args):
        self._step_layout(1)

    @fet_ui.ui_safe
    def on_size_typed(self, sender, args):
        self.search_timer.Stop()
        self.search_timer.Start()

    @fet_ui.ui_safe
    def on_apply_planes(self, sender, args):
        find = self.find
        sizes = self._sizes()
        settings = dict(self.settings)
        for key, name in ((u"w", u"width_mm"), (u"d", u"depth_mm"),
                          (u"h", u"height_mm"), (u"c", u"clearance_mm"),
                          (u"r", u"radius_mm")):
            settings[name] = u"{0:g}".format(sizes[key])
        settings[u"label_plane_dims"] = (u"on" if find(u"LabelDimsCheck").IsChecked
                                         else u"off")
        settings[u"plane_params_binding"] = (
            u"instance" if find(u"PlaneInstanceRadio").IsChecked else u"type")
        settings[u"last_layout"] = self.layout_key
        settings[u"layout_params"] = fet_core.format_layout_params(
            self.layout_params)
        self.settings = settings
        fet_core.save_settings(settings)

        layout_key = self.layout_key

        def worker(uiapp, doc):
            # The view is opened BEFORE any transaction starts - changing
            # the active view is a UI call and cannot happen inside one.
            view, note = fet_ops.activate_layout_view(uiapp, doc, layout_key)
            results = [note] if note is not None else []
            results.extend(fet_ops.apply_plane_layout(doc, view, layout_key,
                                                      settings))
            return results
        self.run_job(self._doc_job(worker), u"Setting out the family")



    # =====================================================================
    # Flex test
    # =====================================================================
    def read_flex_parameters(self):
        doc = self._active_doc()
        self.flex_params = fet_model.flexable_parameters(doc) if doc else []
        spread = self.settings.get(u"flex_spread", u"50")
        kept = {}
        for item in self.flex_params:
            if item.name in self.flex_ends:
                kept[item.name] = self.flex_ends[item.name]
            else:
                low, high = fet_core.flex_spread(item.value, spread)
                kept[item.name] = (u"{0:g}".format(low), u"{0:g}".format(high))
        self.flex_ends = kept
        self.flex_ticks = set([name for name in self.flex_ticks
                               if name in kept])
        self._refresh_flex_list()

    def _flex_shown(self):
        needle = self.find(u"FlexSearch").Text
        out = []
        for item in self.flex_params:
            hay = u" ".join([item.name, item.data_type])
            if fet_core.matches_search(hay, needle):
                out.append(item)
        return out

    def _refresh_flex_list(self):
        listbox = self.find(u"FlexList")
        self.building = True
        shown = []
        try:
            listbox.Items.Clear()
            shown = self._flex_shown()
            for item in shown[:MAX_ROWS]:
                listbox.Items.Add(self._flex_row(item))
        finally:
            self.building = False
        empty = self.find(u"FlexEmptyText")
        if not self.flex_params:
            empty.Text = (u"Nothing here can be flexed. A flex run drives "
                          u"numbers, so a parameter with a formula, a "
                          u"reporting parameter and a read only one are all "
                          u"left out.")
        else:
            empty.Text = u"Nothing matches that search."
        empty.Visibility = (Visibility.Collapsed if shown
                            else Visibility.Visible)
        self._refresh_flex_count()

    def _flex_row(self, item):
        grid = _columns((16.0, u"*", 78.0, 78.0))
        grid.Children.Add(self._chip(item.data_type))

        check = CheckBox()
        check.Content = item.name
        check.IsChecked = item.name in self.flex_ticks
        check.Tag = item.name
        check.VerticalAlignment = VerticalAlignment.Center
        check.Margin = Thickness(4, 0, 4, 0)
        check.Checked += self.on_flex_tick
        check.Unchecked += self.on_flex_tick
        Grid.SetColumn(check, 1)
        grid.Children.Add(check)

        low, high = self.flex_ends.get(item.name, (u"", u""))
        for index, pair in enumerate(((u"min", low), (u"max", high))):
            which, value = pair
            box = TextBox()
            box.Text = value
            box.Tag = u"{0}|{1}".format(which, item.name)
            box.MinHeight = 26.0
            box.Margin = Thickness(0, 0, 4, 0)
            box.TextChanged += self.on_flex_end_typed
            Grid.SetColumn(box, 2 + index)
            grid.Children.Add(box)

        row = ListBoxItem()
        row.Content = grid
        row.Padding = Thickness(6, 3, 6, 3)
        row.ToolTip = u"{0}\n{1} parameter, currently {2:g}".format(
            item.data_type or u"unknown type",
            u"instance" if item.is_instance else u"type", item.value)
        return row

    def _flex_specs(self):
        out = []
        for item in self.flex_params:
            if item.name not in self.flex_ticks:
                continue
            low, high = self.flex_ends.get(item.name, (u"", u""))
            out.append((item.name, low, high))
        return out

    def _flex_type_count(self):
        doc = self._active_doc()
        types = fet_model.family_types(doc) if doc else []
        if not self.find(u"FlexAllTypesRadio").IsChecked:
            return 1, len(types)
        return max(1, len(types)), len(types)

    def _refresh_flex_count(self):
        find = self.find
        specs = self._flex_specs()
        steps = fet_core.to_number(find(u"FlexStepsBox").Text, 3)
        driving, total_types = self._flex_type_count()
        count = fet_core.flex_test_count(driving, specs, steps)
        if not specs:
            find(u"FlexCountText").Text = u"Nothing ticked."
            find(u"FlexRunButton").IsEnabled = False
            return
        text = u"{0} parameters across {1} of {2} types - {3} rounds".format(
            len(specs), driving, max(total_types, 1), count)
        too_big = fet_core.flex_is_too_big(count)
        if too_big:
            text += u". That is too many - keep it to {0}.".format(
                fet_core.MAX_FLEX_TESTS)
        find(u"FlexCountText").Text = text
        find(u"FlexCountText").SetResourceReference(
            TextBlock.ForegroundProperty,
            u"OrangeBrush" if too_big else u"MutedBrush")
        find(u"FlexRunButton").IsEnabled = not too_big

    @fet_ui.ui_safe
    def on_flex_tick(self, sender, args):
        if self.building:
            return
        name = fet_core._as_text(sender.Tag)
        if sender.IsChecked:
            self.flex_ticks.add(name)
        else:
            self.flex_ticks.discard(name)
        self._refresh_flex_count()

    @fet_ui.ui_safe
    def on_flex_end_typed(self, sender, args):
        if self.building:
            return
        which, name = fet_core._as_text(sender.Tag).split(u"|", 1)
        low, high = self.flex_ends.get(name, (u"", u""))
        if which == u"min":
            low = fet_core._as_text(sender.Text)
        else:
            high = fet_core._as_text(sender.Text)
        self.flex_ends[name] = (low, high)
        self._refresh_flex_count()

    @fet_ui.ui_safe
    def on_flex_steps_typed(self, sender, args):
        if self.building:
            return
        self._refresh_flex_count()

    @fet_ui.ui_safe
    def on_flex_filter(self, sender, args):
        if self.building:
            return
        self._refresh_flex_count()
        self._refresh_flex_results()

    @fet_ui.ui_safe
    def on_flex_all(self, sender, args):
        self.flex_ticks = set([item.name for item in self._flex_shown()])
        self._refresh_flex_list()

    @fet_ui.ui_safe
    def on_flex_none(self, sender, args):
        self.flex_ticks = set()
        self._refresh_flex_list()

    @fet_ui.ui_safe
    def on_flex_refresh(self, sender, args):
        self.read_flex_parameters()
        self.set_status(u"{0} parameters can be flexed".format(
            len(self.flex_params)))

    @fet_ui.ui_safe
    def on_flex_run(self, sender, args):
        specs = self._flex_specs()
        if not specs:
            self.set_status(u"Tick what to drive first", u"orange")
            return
        find = self.find
        settings = dict(self.settings)
        settings[u"flex_steps"] = u"{0:g}".format(
            fet_core.to_number(find(u"FlexStepsBox").Text, 3))
        settings[u"flex_types"] = (u"all" if find(u"FlexAllTypesRadio").IsChecked
                                   else u"current")
        self.settings = settings
        fet_core.save_settings(settings)

        def worker(uiapp, doc):
            rows, results = fet_ops.run_flex(doc, specs, settings)
            self.flex_rows = rows
            return results

        def after(results):
            self._refresh_flex_results()
        self.run_job(self._doc_job(worker), u"Flexing the family", after)

    def _refresh_flex_results(self):
        find = self.find
        listbox = find(u"FlexResultList")
        faults_only = bool(find(u"FlexFaultsOnlyCheck").IsChecked)
        rows = [row for row in fet_core.flex_rows_sorted(self.flex_rows)
                if not (faults_only and row.status == fet_core.FLEX_OK)]
        self.building = True
        try:
            listbox.Items.Clear()
            for row in rows[:MAX_ROWS]:
                listbox.Items.Add(self._flex_result_row(row))
        finally:
            self.building = False
        empty = find(u"FlexResultEmptyText")
        if not self.flex_rows:
            empty.Text = (u"Nothing run yet. Tick the parameters to drive, "
                          u"set the ends, and press Flex this family.")
        else:
            empty.Text = u"Nothing went wrong."
        empty.Visibility = (Visibility.Collapsed if rows
                            else Visibility.Visible)
        find(u"FlexSummaryText").Text = fet_core.flex_summary(self.flex_rows)
        find(u"FlexCopyButton").IsEnabled = bool(self.flex_rows)

    def _flex_result_row(self, row):
        grid = _columns((74.0, u"*", 74.0, u"*"))
        status = TextBlock()
        status.Text = row.status
        status.VerticalAlignment = VerticalAlignment.Center
        status.SetResourceReference(
            TextBlock.ForegroundProperty,
            {fet_core.FLEX_BROKE: u"RedBrush",
             fet_core.FLEX_REFUSED: u"RedBrush",
             fet_core.FLEX_NOT_TAKEN: u"OrangeBrush",
             fet_core.FLEX_WARNED: u"OrangeBrush"}.get(row.status,
                                                       u"GreenBrush"))
        grid.Children.Add(status)

        name = TextBlock()
        name.Text = row.parameter
        name.VerticalAlignment = VerticalAlignment.Center
        name.TextTrimming = _trim()
        name.Margin = Thickness(4, 0, 4, 0)
        Grid.SetColumn(name, 1)
        grid.Children.Add(name)

        value = TextBlock()
        value.Text = (u"{0:g}".format(row.value)
                      if isinstance(row.value, float) else
                      fet_core._as_text(row.value))
        value.VerticalAlignment = VerticalAlignment.Center
        value.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
        Grid.SetColumn(value, 2)
        grid.Children.Add(value)

        where = TextBlock()
        where.Text = row.type_name
        where.VerticalAlignment = VerticalAlignment.Center
        where.TextTrimming = _trim()
        where.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
        Grid.SetColumn(where, 3)
        grid.Children.Add(where)

        item = ListBoxItem()
        item.Content = grid
        item.Padding = Thickness(6, 3, 6, 3)
        item.ToolTip = u"{0}\n{1}".format(
            fet_core.FLEX_MEANING.get(row.status, row.status),
            row.message or u"")
        return item

    @fet_ui.ui_safe
    def on_flex_copy(self, sender, args):
        if not self.flex_rows:
            return
        lines = [u"RevoBIM flex test - {0}".format(
            fet_model.family_name(self._active_doc()) or u"this family"),
            fet_core.flex_summary(self.flex_rows), u""]
        for row in fet_core.flex_rows_sorted(self.flex_rows):
            lines.append(u"{0}\t{1}\t{2}\t{3}\t{4}".format(
                row.status, row.type_name, row.parameter,
                fet_core._as_text(row.value), row.message))
        try:
            from System.Windows import Clipboard
            Clipboard.SetText(u"\n".join(lines))
            self.set_status(u"The report is on your clipboard", u"green")
        except Exception:
            self.set_status(u"The clipboard would not take it", u"orange")


    # =====================================================================
    # Family icon and name
    # =====================================================================
    def _refresh_icon_ui(self):
        find = self.find
        settings = self.settings
        view_name = fet_core._as_text(settings.get(u"icon_view_name",
                                                   u"Thumbnail View"))
        find(u"IconViewNameText").Text = u"Preview view: {0}".format(view_name)

        lines = []
        style = dict([(key, label) for label, key
                      in fet_core.DISPLAY_STYLES]).get(
            fet_core._as_text(settings.get(u"icon_3d_style")), u"?")
        view_type = dict([(key, label) for key, label, corner
                          in fet_core.VIEW_TYPES]).get(
            fet_core._as_text(settings.get(u"icon_view_type")), u"?")
        lines.append(u"{0}, {1} detail, 1 : {2}".format(
            style, settings.get(u"icon_3d_detail"),
            settings.get(u"icon_3d_scale")))
        lines.append(view_type)
        hidden = [label for key, label in fet_core.ICON_TICKS
                  if key.startswith(u"icon_hide")
                  and fet_core.setting_on(settings, key)]
        lines.append(u"")
        lines.append(u"Hiding: {0}".format(
            u", ".join([h.replace(u"Hide ", u"") for h in hidden])
            if hidden else u"nothing"))
        for key, label in ((u"icon_lock_orientation", u"Orientation locked"),
                           (u"icon_gradient", u"Gradient background"),
                           (u"icon_export_images", u"Image exported beside "
                                                   u"the family")):
            if fet_core.setting_on(settings, key):
                lines.append(label)
        if self.thumbnail_view_id is not None:
            lines.append(u"")
            lines.append(u"The view is built and will be saved as the "
                         u"family's preview.")
        find(u"IconSummaryText").Text = u"\n".join(lines)

        self._fill_name_combos()
        self._refresh_name_preview()

    def _fill_name_combos(self):
        self.building = True
        try:
            for name, list_key, last_key, label in fet_core.NAME_FIELDS:
                combo = self.find({u"company": u"CompanyCombo",
                                   u"type": u"TypeCombo",
                                   u"discipline": u"DisciplineCombo"}[name])
                current = fet_core._as_text(combo.Text) or \
                    fet_core._as_text(self.settings.get(last_key, u""))
                combo.Items.Clear()
                for code, description in fet_core.parse_abbreviations(
                        self.settings.get(list_key, u"")):
                    item = ComboBoxItem()
                    item.Content = (u"{0}   -   {1}".format(code, description)
                                    if description else code)
                    item.Tag = code
                    combo.Items.Add(item)
                combo.Text = current
        finally:
            self.building = False

    def _name_parts(self):
        find = self.find
        return [fet_core._as_text(find(u"CompanyCombo").Text),
                fet_core._as_text(find(u"TypeCombo").Text),
                fet_core._as_text(find(u"DisciplineCombo").Text),
                fet_core._as_text(find(u"FamilyNameBox").Text)]

    def _refresh_name_preview(self):
        find = self.find
        parts = self._name_parts()
        built = fet_core.build_family_name(parts)
        complete = fet_core.family_name_is_complete(parts)
        find(u"FamilyNamePreview").Text = (
            u"{0}.rfa".format(built) if built else u"nothing yet")
        find(u"FamilyNamePreview").SetResourceReference(
            TextBlock.ForegroundProperty,
            u"GreenBrush" if complete else u"MutedBrush")
        if complete:
            find(u"FamilyNameNote").Text = NAME_HINT
        else:
            find(u"FamilyNameNote").Text = (
                u"Fill all four boxes. " + NAME_HINT)
        find(u"SaveFamilyButton").Visibility = (
            Visibility.Visible if complete else Visibility.Collapsed)

    @fet_ui.ui_safe
    def on_name_typed(self, sender, args):
        if self.building:
            return
        self._refresh_name_preview()

    @fet_ui.ui_safe
    def on_name_picked(self, sender, args):
        u"""The dropdown shows 'BGL - Building Group'; only the code goes
        into the name."""
        if self.building:
            return
        item = sender.SelectedItem
        if item is not None:
            self.building = True
            try:
                sender.Text = fet_core._as_text(item.Tag)
            finally:
                self.building = False
        self._refresh_name_preview()

    @fet_ui.ui_safe
    def on_icon_settings(self, sender, args):
        u"""The same settings window, opened on the icon tab.  Two windows
        for one set of settings is two places for them to disagree."""
        self._open_settings(u"icon")

    @fet_ui.ui_safe
    def on_apply_image(self, sender, args):
        settings = dict(self.settings)

        def worker(uiapp, doc):
            view, results = fet_ops.build_thumbnail_view(doc, settings)
            if view is not None:
                self.thumbnail_view_id = view.Id
                fet_ops.show_view(uiapp, view)
            else:
                self.thumbnail_view_id = None
            return results

        def after(results):
            self._refresh_icon_ui()
        self.run_job(self._doc_job(worker), u"Building the thumbnail view",
                     after)

    @fet_ui.ui_safe
    def on_save_family(self, sender, args):
        parts = self._name_parts()
        if not fet_core.family_name_is_complete(parts):
            self.set_status(u"Fill all four name boxes first", u"orange")
            return
        built = fet_core.build_family_name(parts)
        from Microsoft.Win32 import SaveFileDialog
        dialog = SaveFileDialog()
        dialog.Title = u"Save the family"
        dialog.Filter = u"Revit families (*.rfa)|*.rfa"
        dialog.FileName = fet_core.safe_file_name(built) + u".rfa"
        folder = fet_core._as_text(self.settings.get(u"last_save_folder", u""))
        if folder and os.path.isdir(folder):
            dialog.InitialDirectory = folder
        if dialog.ShowDialog() != True:
            return
        path = dialog.FileName

        self.settings[u"last_save_folder"] = os.path.dirname(path)
        for index, entry in enumerate(fet_core.NAME_FIELDS):
            name, list_key, last_key, label = entry
            self.settings[last_key] = fet_core.clean_name_part(parts[index])
        self.settings[u"last_family_name"] = fet_core.clean_name_part(parts[3])
        fet_core.save_settings(self.settings)

        settings = dict(self.settings)
        view_id = self.thumbnail_view_id

        def worker(uiapp, doc):
            view = None
            if view_id is not None:
                view = doc.GetElement(view_id)
            if view is None:
                # Nobody pressed Apply image, so build the view first -
                # saving without one is how a family ends up with the
                # grey box for a preview.
                view, results = fet_ops.build_thumbnail_view(doc, settings)
                if view is not None:
                    self.thumbnail_view_id = view.Id
                    fet_ops.show_view(uiapp, view)
            else:
                results = []
                fet_ops.show_view(uiapp, view)
            results.extend(fet_ops.save_family(doc, path, view, settings))
            return results
        self.run_job(self._doc_job(worker), u"Saving the family")


    # =====================================================================
    # Chrome, theme, keys
    # =====================================================================
    def _set_theme_chip(self):
        chip = self.find(u"ThemeChip")
        chip.Content = u"Dark" if self.palette_name == u"dark" else u"Light"

    @fet_ui.ui_safe
    def on_theme(self, sender, args):
        u"""Switching by hand stops following Revit, because a person who
        has just picked a palette does not want it changed back."""
        self.palette_name = theme.other(self.palette_name)
        theme.apply(self.window, self.palette_name)
        self.settings[u"theme"] = self.palette_name
        fet_core.save_settings(self.settings)
        self._set_theme_chip()
        self._draw_preview()

    @fet_ui.ui_safe
    def on_settings(self, sender, args):
        self._open_settings(u"general")

    def _open_settings(self, tab):
        def applied(values):
            self.settings = values
            self.palette_name = theme.resolve(
                fet_core._as_text(values.get(u"theme", u"follow")),
                self.palette_name)
            theme.apply(self.window, self.palette_name)
            self._set_theme_chip()
            self._refresh_planes_ui()
            self._refresh_icon_ui()
        window = settings_window.SettingsWindow(
            self.settings, self.palette_name, self.window, applied, tab)
        window.show()

    @fet_ui.ui_safe
    def on_full(self, sender, args):
        self.chrome.toggle_full()

    @fet_ui.ui_safe
    def on_key(self, sender, args):
        if args.Key == Key.F11:
            self.chrome.toggle_full()
            args.Handled = True
        elif args.Key == Key.F5:
            self.settings = fet_core.load_settings()
            self._fill_model_combos()
            self.read_family_parameters()
            self._refresh_staged()
            self._refresh_context()
            self._refresh_planes_ui()
            self.set_status(u"Re-read")
            args.Handled = True
        elif args.Key == Key.Escape:
            if self.chrome.full:
                self.chrome.leave_full()
            else:
                self.window.Close()
            args.Handled = True

    @fet_ui.ui_safe
    def on_search_typed(self, sender, args):
        self.search_timer.Stop()
        self.search_timer.Start()

    @fet_ui.ui_safe
    def on_search_due(self, sender, args):
        self.search_timer.Stop()
        self._forget_caches()
        for kind in (u"material", u"linestyle", u"text", u"dimension"):
            self._refresh_scan_list(kind)
        self._refresh_family_list()
        self._refresh_flex_list()
        self._draw_preview()

    @fet_ui.ui_safe
    def on_close(self, sender, args):
        self.window.Close()

    def on_closed(self, sender, args):
        _clear_note()

    def show(self):
        try:
            fet_ui.own_to_revit(self.window, self.uiapp)
        except Exception:
            pass
        self.window.Show()
        self.set_status(u"Ready")


# =========================================================================
# Small WPF helpers
# =========================================================================

def _columns(widths):
    grid = Grid()
    for width in widths:
        column = ColumnDefinition()
        if width == u"*":
            column.Width = GridLength(1, GridUnitType.Star)
        else:
            column.Width = GridLength(float(width))
        grid.ColumnDefinitions.Add(column)
    return grid


def _row_definition():
    u"""Auto height, or the two lines of a staged row split the space
    evenly and the combos stretch to fill it."""
    from System.Windows.Controls import RowDefinition
    definition = RowDefinition()
    definition.Height = GridLength.Auto
    return definition


def _corner(radius):
    from System.Windows import CornerRadius
    return CornerRadius(radius)


def _trim():
    from System.Windows import TextTrimming
    return TextTrimming.CharacterEllipsis


def _wrap():
    from System.Windows import TextWrapping
    return TextWrapping.Wrap


def _text_changed(handler):
    u"""An editable ComboBox raises TextChanged from the TextBox inside its
    template, which is not reachable until the template is applied - so the
    handler is attached to the routed event on the ComboBox itself."""
    from System.Windows import RoutedEventHandler
    from System.Windows.Controls import TextChangedEventHandler
    _ = RoutedEventHandler
    return TextChangedEventHandler(handler)


def _uidoc(uiapp):
    try:
        return uiapp.ActiveUIDocument
    except Exception:
        return None
