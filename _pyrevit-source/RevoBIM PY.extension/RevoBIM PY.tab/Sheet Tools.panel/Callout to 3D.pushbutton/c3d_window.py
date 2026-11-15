# -*- coding: utf-8 -*-
"""Callout to 3D - the main window.

Modeless and owned by Revit's main window, so Revit stays navigable while it
is open and the window floats above Revit rather than slipping behind it.
Because it is modeless every write leaves through an ExternalEvent, which is
created in the command context and handed in.
"""

import c3d_clr  # noqa: F401  assemblies first, always

import time
import traceback

import c3d_core as core
import c3d_geom as geom
import c3d_grid as grid_module
import c3d_model as model
import c3d_ops as ops
import c3d_debug as debug
import c3d_preview as preview
import c3d_sheet as sheet_module
import c3d_settings as settings_module
import c3d_ui as ui
import theme as theme_module

from System import Action                                        # noqa: E402
from System.Windows import (                                     # noqa: E402
    Visibility, Thickness, VerticalAlignment, Point, CornerRadius,
)
from System.Windows.Controls import (                            # noqa: E402
    StackPanel, Orientation, TextBlock, Border, Button,
)
from System.Windows.Media import PointCollection                 # noqa: E402
from System.Windows.Shapes import Polygon                        # noqa: E402
from System.Windows.Threading import DispatcherPriority          # noqa: E402


# header controls that stand down for a run - ShrinkButton is deliberately
# not one of them, and a bench rule keeps it that way
ROOM_TAG_BLANK = "(the default room tag)"

# the viewport types in the sheet group, and the setting each one writes
VP_COMBOS = (("VpCalloutCombo", "vp_type_callout"), ("Vp3dCombo", "vp_type_3d"),
             ("VpSectionCombo", "vp_type_section"))

# the 3D section box offsets in the section array: box, setting, default
BOX_FIELDS = (("BoxSideBox", "3d_xy_margin_mm", 0.0), ("BoxTopBox", "3d_top_offset_mm", -200.0),
              ("BoxBottomBox", "3d_bottom_offset_mm", 50.0))

# the three scale boxes in the section array, and the setting each one writes
SCALE_COMBOS = (("CalloutScaleCombo", "callout_scale"), ("ThreeDScaleCombo", "3d_scale"),
                ("SecScaleCombo", "sec_scale"))

BUSY_DEAF = ("CreateButton", "SettingsChip", "ThemeChip", "FullScreenButton", "CloseButton")


class CalloutWindow(object):

    def __init__(self, uidoc, run_event, run_handler, open_event, open_handler):
        self.uidoc = uidoc
        self.doc = uidoc.Document
        self.run_event = run_event
        self.run_handler = run_handler
        self.open_event = open_event
        self.open_handler = open_handler
        self.settings = core.load_settings()
        self.palette = theme_module.resolve(self.settings)
        self.rows = []
        self.routes = {}
        self.busy = False
        self.plan = []
        self.flip_x = core.get_bool(self.settings, "sec_flip_x")
        self.flip_y = core.get_bool(self.settings, "sec_flip_y")
        self._preview_size = None
        self._sheet_size = None
        self._syncing = False        # set while the inline controls are being filled
        self.preset = self.settings.get("layout_preset", "columns")
        if self.preset not in geom.preset_keys() + [core.CUSTOM]:
            self.preset = "columns"
        if self.preset == core.CUSTOM and not core.custom_moves(self.settings):
            self.preset = self.settings.get("layout_custom_base", "columns")
        self.cards = []

        self.window = ui.load_window("CalloutTo3D.xaml")
        ui.apply_theme(self.window, self.palette)
        self.find = self.window.FindName

        self.find("VersionText").Text = u"v{0}".format(core.__version__)
        ui.set_image(self.find("LogoImage"), "icon.png")
        self.egg = ui.EggWatcher(self.find("LogoZone"), self.window)
        self.chrome = ui.Chrome(self.window, self.find("HeaderBar"), self.find("GripGrid"),
                                self.find("ShrinkButton"))
        self.chrome.drawer.busy = lambda: self.busy

        if core.get_bool(self.settings, "remember_size", True):
            try:
                self.window.Width = core.get_float(self.settings, "window_w", 1380.0)
                self.window.Height = core.get_float(self.settings, "window_h", 840.0)
            except Exception:
                pass

        self.table = grid_module.CalloutGrid(
            self.window, self.find("CalloutGrid"),
            on_change=self._on_table_change, on_select=self._on_row_selected)

        # what was selected in Revit as the tool opened - read now, in the
        # command context, before anything else can change it
        try:
            self.picked = model.selection_targets(uidoc)
        except Exception as err:
            core.log(u"the Revit selection could not be read: {0}".format(err))
            self.picked = {"keys": set(), "names": set(), "count": 0}
        self.picked_rows = []
        self.sheet_preview = sheet_module.SheetPreview(
            self.find("SheetCanvas"), self._on_box_moved, self._on_box_reset)
        self._wire()
        self._wire_groups()
        self._update_theme_chip()
        self.status("reading the model...")

    # ------------------------------------------------------------------
    def _wire(self):
        find = self.find
        find("CloseButton").Click += self._on_close
        find("FullScreenButton").Click += self._on_full
        find("ThemeChip").Click += self._on_theme
        find("SettingsChip").Click += self._on_settings
        find("RefreshButton").Click += self._on_refresh
        find("PlanButton").Click += self._on_plan
        find("CreateButton").Click += self._on_create
        find("OpenViewButton").Click += self._on_open_view
        find("AllButton").Click += self._on_all
        find("NoneButton").Click += self._on_none
        find("ApplyRowsButton").Click += self._on_apply_rows
        find("XUpButton").Click += self._make_step("XCountBox", 1, 0, 12)
        find("XDownButton").Click += self._make_step("XCountBox", -1, 0, 12)
        find("YUpButton").Click += self._make_step("YCountBox", 1, 0, 12)
        find("YDownButton").Click += self._make_step("YCountBox", -1, 0, 12)
        find("SearchBox").TextChanged += self._on_search
        find("ViewFilterCombo").SelectionChanged += self._on_view_filter
        find("NotOnSheetCheck").Click += self._on_not_on_sheet
        find("SelectedOnlyCheck").Click += self._on_not_on_sheet
        find("XCountBox").TextChanged += self._on_counts
        find("YCountBox").TextChanged += self._on_counts
        find("DepthBox").TextChanged += self._on_counts
        find("SizeCombo").SelectionChanged += self._on_counts
        find("FlipXButton").Click += self._on_flip_x
        find("FlipYButton").Click += self._on_flip_y
        find("PreviewCanvas").SizeChanged += self._on_canvas_size
        find("SheetCanvas").SizeChanged += self._on_canvas_size
        find("SecTypeCombo").SelectionChanged += self._on_section_type
        find("SecTemplateCombo").SelectionChanged += self._on_section_template
        find("NumberRuleBox").TextChanged += self._on_rules
        find("NameRuleBox").TextChanged += self._on_rules
        find("NumberStartBox").TextChanged += self._on_rules
        find("BelowBox").TextChanged += self._on_offsets
        for name in ("BoxSideBox", "BoxTopBox", "BoxBottomBox"):
            find(name).TextChanged += self._on_offsets
        find("TagRoomsCheck").Click += self._on_room_tags
        find("CropGridsCheck").Click += self._on_crop_grids
        for combo_name, _key in VP_COMBOS:
            find(combo_name).SelectionChanged += self._on_viewport_types
        find("TitleGapBox").TextChanged += self._on_title_gap
        find("SecScaleCombo").SelectionChanged += self._on_section_scale
        find("ThreeDScaleCombo").SelectionChanged += self._on_section_scale
        find("CalloutScaleCombo").SelectionChanged += self._on_section_scale
        find("RoomTagCombo").SelectionChanged += self._on_room_tags
        find("AboveBox").TextChanged += self._on_offsets
        find("PresetBackButton").Click += self._make_cycle(-1)
        find("PresetNextButton").Click += self._make_cycle(1)
        find("ResetMovesButton").Click += self._on_reset_moves
        self.window.SizeChanged += self._on_canvas_size
        self.window.Closing += self._on_closing

        find("XCountBox").Text = u"{0}".format(core.get_int(self.settings, "sec_x_count", 1))
        find("YCountBox").Text = u"{0}".format(core.get_int(self.settings, "sec_y_count", 1))
        find("DepthBox").Text = u"{0:.0f}".format(core.get_float(self.settings, "sec_depth_mm", 500.0))
        self.flip_x = core.get_bool(self.settings, "sec_flip_x")
        self.flip_y = core.get_bool(self.settings, "sec_flip_y")
        self._mark_flips()
        ui.fill_combo(find("ViewFilterCombo"), [label for _key, label in core.VIEW_FILTERS],
                      dict(core.VIEW_FILTERS)[core.view_filter(self.settings)])
        try:
            find("NotOnSheetCheck").IsChecked = core.get_bool(
                self.settings, "hide_on_sheet", True)
        except Exception:
            pass
        try:
            find("DebugCheck").IsChecked = core.get_bool(self.settings, "debug_report")
        except Exception:
            pass
        self._set_sheet_filter()
        sizes = [size.strip() for size in
                 (self.settings.get("sheet_sizes") or "A1").split("|") if size.strip()]
        ui.fill_combo(find("SizeCombo"), sizes, self.settings.get("sheet_size_default", "A1"))
        self._sync_inline()

    # ------------------------------------------------------------------
    # the three groups
    def _wire_groups(self):
        """Callout selection, Section array, Sheet settings and naming - each
        slides open and shut under its own header, and each has the settings
        that belong to it along its top."""
        opened = core.open_groups(self.settings)
        self.folds = {}
        for key, prefix, panel, grip in (("selection", "Selection", "CalloutGrid", "SelectionGrip"),
                                         ("array", "Array", "ArrayPanel", "ArrayGrip"),
                                         ("sheet", "Sheet", "SheetPanel", "SheetGrip")):
            self.folds[key] = ui.Fold(key, self.find(prefix + "Header"),
                                      self.find(prefix + "Body"), self.find(prefix + "Chevron"),
                                      key in opened, self._on_fold)
            target = self.find(panel)
            try:
                target.Height = core.group_height(self.settings, key)
            except Exception:
                pass
            ui.HeightGrip(self.find(grip), target, 160.0, 1400.0, self._make_height_keeper(key))
        self._build_cards()
        self._wire_docks()

    def _on_fold(self, key, opened):
        keys = [name for name, fold in self.folds.items() if fold.opened]
        self.settings["groups_open"] = core.groups_text(keys)
        if opened:
            # a group opened from shut has not been drawn at its real size
            self._preview_size = None
            self._sheet_size = None
            try:
                self.window.Dispatcher.BeginInvoke(
                    DispatcherPriority.Background, Action(self._draw_preview))
            except Exception:
                pass

    def _make_height_keeper(self, key):
        def keep(height):
            heights = core.get_map(self.settings, "group_heights")
            heights[key] = u"{0:.0f}".format(height)
            core.set_map(self.settings, "group_heights", heights)
        return keep

    def _sync_inline(self):
        """Fill the controls along the top of each group from the settings -
        once when the window opens and again after the Settings window, which
        edits the same keys."""
        self._syncing = True
        try:
            find = self.find
            try:
                types = [item["name"] for item in model.view_family_types(self.doc, "Section")]
            except Exception:
                types = []
            ui.fill_combo(find("SecTypeCombo"), types,
                          self.settings.get("sec_view_family_type", "") or settings_module.BLANK,
                          settings_module.BLANK)
            try:
                kind = None if core.get_bool(self.settings, "template_list_all") else "section"
                templates = [item["name"] for item in model.view_templates(self.doc, kind)]
            except Exception:
                templates = []
            ui.fill_combo(find("SecTemplateCombo"), templates,
                          self.settings.get("sec_template", "") or settings_module.BLANK,
                          settings_module.BLANK)
            find("NumberRuleBox").Text = self.settings.get("sheet_number_pattern") or \
                core.DEFAULTS["sheet_number_pattern"]
            find("NameRuleBox").Text = self.settings.get("sheet_name_pattern") or \
                core.DEFAULTS["sheet_name_pattern"]
            find("NumberStartBox").Text = u"{0}".format(
                core.get_int(self.settings, "sheet_number_start", 1))
            try:
                tags = [item["name"] for item in model.room_tag_types(self.doc)]
            except Exception:
                tags = []
            ui.fill_combo(find("RoomTagCombo"), tags,
                          self.settings.get("sec_room_tag_type", "") or ROOM_TAG_BLANK,
                          ROOM_TAG_BLANK)
            for combo_name, key in SCALE_COMBOS:
                own = core.parse_scale(self.settings.get(key, ""))
                ui.fill_combo(find(combo_name), [core.scale_text(s) for s in core.SCALES],
                              core.scale_text(own) if own else settings_module.BLANK,
                              settings_module.BLANK)
            find("TagRoomsCheck").IsChecked = core.get_bool(self.settings, "sec_tag_rooms", True)
            find("CropGridsCheck").IsChecked = core.get_bool(self.settings, "sec_crop_grids", True)
            try:
                kinds = [item["name"] for item in model.viewport_types(self.doc)]
            except Exception:
                kinds = []
            for combo_name, key in VP_COMBOS:
                ui.fill_combo(find(combo_name), kinds,
                              self.settings.get(key, "") or settings_module.BLANK_VP,
                              settings_module.BLANK_VP)
            find("TitleGapBox").Text = u"{0}".format(self.settings.get("title_gap_mm", "2"))
            find("RoomTagCombo").IsEnabled = core.get_bool(self.settings, "sec_tag_rooms", True)
            for box, key, fallback in BOX_FIELDS:
                find(box).Text = u"{0:.0f}".format(core.get_float(self.settings, key, fallback))
            find("BelowBox").Text = u"{0:.0f}".format(core.get_float(self.settings, "sec_below_mm", 0.0))
            find("AboveBox").Text = u"{0:.0f}".format(core.get_float(self.settings, "sec_above_mm", 0.0))
            find("TokenText").Text = (u"Number: " + core.NAMING_TOKENS["number"] +
                                      u"\nName: " + core.NAMING_TOKENS["name"])
        finally:
            self._syncing = False
        self._show_rules()

    def _on_section_type(self, sender, args):
        if self._syncing:
            return
        picked = ui.combo_value(self.find("SecTypeCombo"), settings_module.BLANK)
        self.settings["sec_view_family_type"] = picked
        if picked and core.get_bool(self.settings, "template_follows_type", True):
            # the type's own template, as the Settings window offers it
            try:
                name = model.default_template_name(self.doc, picked, "section")
            except Exception:
                name = ""
            if name:
                combo = self.find("SecTemplateCombo")
                items = [u"{0}".format(item) for item in combo.Items]
                if name not in items:
                    combo.Items.Add(name)
                    items.append(name)
                combo.SelectedIndex = items.index(name)
        self._update_summaries()
        self._build_plan_text()

    def _on_section_template(self, sender, args):
        if self._syncing:
            return
        self.settings["sec_template"] = ui.combo_value(
            self.find("SecTemplateCombo"), settings_module.BLANK)
        self._update_summaries()

    def _on_rules(self, sender, args):
        if self._syncing:
            return
        find = self.find
        self.settings["sheet_number_pattern"] = (find("NumberRuleBox").Text or "").strip()
        self.settings["sheet_name_pattern"] = (find("NameRuleBox").Text or "").strip()
        try:
            self.settings["sheet_number_start"] = u"{0}".format(
                max(1, int(float(find("NumberStartBox").Text or 1))))
        except Exception:
            pass
        self._show_rules()
        self._build_plan_text()

    def _on_section_scale(self, sender, args):
        """The three scale boxes - callout, 3D, sections - all land here."""
        if self._syncing:
            return
        for combo_name, key in SCALE_COMBOS:
            own = core.parse_scale(ui.combo_value(self.find(combo_name), settings_module.BLANK))
            self.settings[key] = u"{0}".format(own) if own else ""
        self._draw_preview()
        self._update_summaries()

    def _on_viewport_types(self, sender, args):
        """The viewport type - the title header - for the callout, the 3D and
        the sections, the same keys the Settings window edits."""
        if self._syncing:
            return
        for combo_name, key in VP_COMBOS:
            self.settings[key] = ui.combo_value(self.find(combo_name), settings_module.BLANK_VP)
        self._update_summaries()

    def _on_crop_grids(self, sender, args):
        if self._syncing:
            return
        self.settings["sec_crop_grids"] = "1" if bool(self.find("CropGridsCheck").IsChecked) else "0"
        self._update_summaries()

    def _on_title_gap(self, sender, args):
        """Empty is allowed - it means leave the titles alone - but half typed
        rubbish keeps what was there."""
        if self._syncing:
            return
        text = (self.find("TitleGapBox").Text or "").strip()
        if not text:
            self.settings["title_gap_mm"] = ""
            return
        try:
            self.settings["title_gap_mm"] = u"{0:g}".format(max(0.0, float(text)))
        except Exception:
            pass

    def _on_room_tags(self, sender, args):
        if self._syncing:
            return
        on = bool(self.find("TagRoomsCheck").IsChecked)
        self.settings["sec_tag_rooms"] = "1" if on else "0"
        self.settings["sec_room_tag_type"] = ui.combo_value(
            self.find("RoomTagCombo"), ROOM_TAG_BLANK)
        self.find("RoomTagCombo").IsEnabled = on
        self._update_summaries()

    def _on_offsets(self, sender, args):
        """The offsets in the section array: how far the sections reach below
        and above the band, and the 3D section box's own crop, top and bottom
        offsets - which the sections' band starts from."""
        if self._syncing:
            return
        for box, key in (("BelowBox", "sec_below_mm"), ("AboveBox", "sec_above_mm")) + \
                tuple([(name, key) for name, key, _fallback in BOX_FIELDS]):
            try:
                self.settings[key] = u"{0:.0f}".format(float(self.find(box).Text or 0))
            except Exception:
                pass                        # half typed - keep what was there
        self._draw_preview()

    def _rule_tokens(self):
        """The tokens the current callout would give, for the examples."""
        row = self._current_row()
        if row is None:
            return {"level": "L01", "abbrev": "Detail", "callout": "Callout 1"}
        try:
            template_name = ops.callout_template_name(self.doc, row) or \
                self.settings.get("3d_template") or ""
            abbrev = core.abbreviate_template(template_name, self.settings)
        except Exception:
            abbrev = ""
        return {"level": core.level_token(row.get("level_name") or "", self.settings),
                "abbrev": abbrev or "Detail", "callout": row.get("name") or ""}

    def _show_rules(self):
        """A live example under each rule, and a warning for any token that
        nothing will fill."""
        find = self.find
        number_rule = self.settings.get("sheet_number_pattern", "")
        name_rule = self.settings.get("sheet_name_pattern", "")
        # what the run itself works out wins when there is a plan - it has the
        # real abbreviation and knows which numbers are taken
        planned = self.plan[0] if self.plan else None
        if planned is not None:
            number, name = planned.get("sheet_number", ""), planned.get("sheet_name", "")
        else:
            number, name = core.naming_example(number_rule, name_rule, self._rule_tokens(),
                                               core.get_int(self.settings, "sheet_number_start", 1))
        for box, value, rule, allowed in (
                ("NumberExample", number, number_rule, core.SHEET_NUMBER_TOKENS),
                ("NameExample", name, name_rule, core.SHEET_NAME_TOKENS)):
            odd = core.unknown_tokens(rule, allowed)
            try:
                if odd:
                    find(box).Text = u"nothing fills {0}".format(
                        u", ".join([u"{" + token + u"}" for token in odd]))
                    find(box).Foreground = self.window.TryFindResource("RedBrush")
                else:
                    find(box).Text = u"e.g.  {0}".format(value)
                    find(box).Foreground = self.window.TryFindResource("MutedBrush")
            except Exception:
                pass
        self._update_summaries()

    # ------------------------------------------------------------------
    # the layout cards, the custom setout and the sheet preview
    def _card_keys(self):
        return geom.preset_keys() + [core.CUSTOM]

    def _label(self, key):
        """A card's title and the line under it."""
        if key == core.CUSTOM:
            base = self.settings.get("layout_custom_base", "columns")
            if not core.custom_moves(self.settings):
                return (u"Custom setout",
                        u"drag a box on the sheet to make one - every sheet the run makes uses it")
            return (u"Custom setout",
                    u"dragged from “{0}” - every sheet the run makes uses it"
                    .format(geom.preset_label(base)[0]))
        return geom.preset_label(key)

    def _build_cards(self):
        holder = self.find("PresetCards")
        holder.Children.Clear()
        self.cards = []
        for key in self._card_keys():
            border, surface = sheet_module.new_card()
            border.ToolTip = u"{0} - {1}".format(*self._label(key))
            border.MouseLeftButtonUp += self._make_pick(key)
            border.Margin = Thickness(0, 0, 8, 8)
            holder.Children.Add(border)
            self.cards.append((key, border, surface))
        self._draw_cards()

    def _draw_cards(self):
        row = self._current_row() or {}
        x_count = row.get("x_count", core.get_int(self.settings, "sec_x_count", 1))
        y_count = row.get("y_count", core.get_int(self.settings, "sec_y_count", 1))
        custom = core.custom_moves(self.settings)
        for key, border, surface in self.cards:
            chosen = key == self.preset
            sheet_module.card(surface, border, chosen)
            try:
                if key == core.CUSTOM:
                    sheet_module.draw_card(surface, self.settings.get("layout_custom_base", "columns"),
                                           x_count, y_count, chosen, custom, bool(custom))
                else:
                    sheet_module.draw_card(surface, key, x_count, y_count, chosen)
                border.ToolTip = u"{0} - {1}".format(*self._label(key))
            except Exception as err:
                core.log(u"layout card {0} would not draw: {1}".format(key, err))
        title, detail = self._label(self.preset)
        try:
            self.find("PresetTitle").Text = title
            self.find("PresetDetail").Text = detail
        except Exception:
            pass

    def _make_pick(self, key):
        def handler(sender, args):
            self._set_preset(key)
        return handler

    def _make_cycle(self, step):
        def handler(sender, args):
            keys = self._card_keys()
            if not core.custom_moves(self.settings):
                keys = geom.preset_keys()       # no setout yet, nothing to land on
            index = keys.index(self.preset) if self.preset in keys else 0
            self._set_preset(keys[(index + step) % len(keys)])
        return handler

    def _set_preset(self, key):
        if key == self.preset:
            return
        if key == core.CUSTOM and not core.custom_moves(self.settings):
            self.status(u"there is no custom setout yet - drag a box on the sheet to make one")
            return
        self.preset = key
        self.settings["layout_preset"] = key
        self._draw_sheet()
        self.status(u"layout: {0}".format(self._label(key)[0]))
        self._update_summaries()

    def _paper_for(self, size):
        """The title block's own paper size when one of that type has been
        placed before - read once per size - else the ISO sheet."""
        size = u"{0}".format(size or "A1").strip().upper()
        cache = getattr(self, "_paper_cache", None)
        if cache is None:
            cache = self._paper_cache = {}
        if size not in cache:
            found = None
            try:
                block = model.title_block_for_size(
                    self.doc, size, core.get_map(self.settings, "sheet_titleblocks"))
                found = model.title_block_size_mm(self.doc, block)
                name = block["name"] if block else u""
            except Exception:
                name = u""
            cache[size] = (found or model.PAPER_SIZES.get(size, (841.0, 594.0)), name,
                           found is not None)
        return cache[size]

    def _sheet_layout(self, row):
        """The sheet this callout will get, as the preview sees it: the title
        block, the margins and the cells, with the custom setout applied."""
        settings = self.settings
        size = row.get("size") or settings.get("sheet_size_default", "A1")
        paper = self._paper_for(size)[0]
        margins = (core.get_float(settings, "sheet_margin_left_mm", 15.0),
                   core.get_float(settings, "sheet_margin_right_mm", 120.0),
                   core.get_float(settings, "sheet_margin_top_mm", 15.0),
                   core.get_float(settings, "sheet_margin_bottom_mm", 15.0))
        extents = geom.extents_mm(row.get("frame")) if row.get("frame") else None
        if not extents:
            return paper, margins, None
        base, top = ops.section_band(row, settings)
        guess = geom.estimate_sizes(
            (extents[2] - extents[0]) / 2.0, (extents[3] - extents[1]) / 2.0,
            top - base, core.callout_scale_for(row, settings),
            core.get_float(settings, "sec_side_margin_mm", 250.0),
            row.get("x_count", 0), row.get("y_count", 0),
            crop_margin_mm=core.get_float(settings, "3d_crop_margin_mm", 150.0),
            section_scale=core.section_scale_for(row, settings),
            three_d_scale=core.three_d_scale_for(row, settings))
        pad = 2.0 * core.get_float(settings, "layout_pad_mm", 4.0)

        def padded(cell):
            return (cell[0] + pad, cell[1] + pad)

        callout = padded(guess["callout"])
        if row.get("sheet") is not None and \
                str(settings.get("callout_on_sheet", "report")).lower() != "duplicate":
            callout = None               # already on a sheet, so not placed again
        preset, moves = core.resolve_layout(dict(settings, layout_preset=self.preset),
                                            geom.preset_keys())
        layout = geom.layout_for(
            preset,
            (margins[0], margins[3], paper[0] - margins[0] - margins[1],
             paper[1] - margins[2] - margins[3]),
            callout, padded(guess["3d"]),
            [padded(cell) for cell in guess["x"]], [padded(cell) for cell in guess["y"]],
            core.get_float(settings, "sheet_gap_mm", 12.0),
            core.get_float(settings, "section_gap_mm", 6.0),
            core.get_float(settings, "section_min_gap_mm", 2.0))
        return paper, margins, geom.apply_moves(layout, moves)

    def _draw_sheet(self):
        row = self._current_row()
        canvas = self.find("SheetCanvas")
        try:
            if row is None:
                self.sheet_preview.draw((841.0, 594.0), (15.0, 120.0, 15.0, 15.0), None)
                caption = u""
            else:
                paper, margins, layout = self._sheet_layout(row)
                moved = core.custom_moves(self.settings).keys() \
                    if self.preset == core.CUSTOM else []
                self.sheet_preview.draw(paper, margins, layout, moved)
                size = row.get("size") or self.settings.get("sheet_size_default", "A1")
                _paper, block, measured = self._paper_for(size)
                caption = u"{0}\n{1} {2:.0f} x {3:.0f} mm{4}".format(
                    row.get("name", ""), block or size, paper[0], paper[1],
                    u"" if measured else u"  (ISO size - none of these placed yet)")
            self.find("SheetCaption").Text = caption
            self._sheet_size = (round(float(canvas.ActualWidth), 1),
                                round(float(canvas.ActualHeight), 1))
        except Exception as err:
            core.log(u"sheet preview failed: {0}".format(traceback.format_exc()))
            self.status(u"the sheet preview could not be drawn - {0}".format(err))
        self._draw_cards()

    def _on_box_moved(self, role, centre):
        """A box let go somewhere new: the layout becomes the custom setout.

        Dragging from one of the four layouts starts a fresh setout from it;
        dragging while already on the setout adds to it."""
        if self.preset != core.CUSTOM:
            self.settings["layout_custom_base"] = self.preset
            core.set_custom_moves(self.settings, {})
            self.preset = core.CUSTOM
            self.settings["layout_preset"] = core.CUSTOM
        moves = core.custom_moves(self.settings)
        moves[role] = (float(centre[0]), float(centre[1]))
        core.set_custom_moves(self.settings, moves)
        self._draw_sheet()
        self._update_summaries()
        self.status(u"custom setout: {0} at {1:.0f}, {2:.0f} mm - every sheet the run makes "
                    u"uses it".format(sheet_module.role_text(role), centre[0], centre[1]))

    def _on_box_reset(self, role):
        if self.preset != core.CUSTOM:
            return
        moves = core.custom_moves(self.settings)
        if role not in moves:
            return
        del moves[role]
        core.set_custom_moves(self.settings, moves)
        if not moves:
            self._clear_custom()
            return
        self._draw_sheet()
        self.status(u"{0} put back where the layout puts it".format(sheet_module.role_text(role)))

    def _on_reset_moves(self, sender, args):
        self._clear_custom()

    def _clear_custom(self):
        base = self.settings.get("layout_custom_base", "columns")
        core.set_custom_moves(self.settings, {})
        if self.preset == core.CUSTOM:
            self.preset = base if base in geom.preset_keys() else "columns"
            self.settings["layout_preset"] = self.preset
        self._draw_sheet()
        self._update_summaries()
        self.status(u"the custom setout is cleared - back to {0}".format(
            geom.preset_label(self.preset)[0]))

    # ------------------------------------------------------------------
    # headers that stay in sight, and opening a group to fill the window
    GROUP_TITLES = (("selection", "Selection", "Callout selection", "BlueBrush"),
                    ("array", "Array", "Section array", "OrangeBrush"),
                    ("sheet", "Sheet", "Sheet settings and naming", "GreenBrush"))

    def _wire_docks(self):
        """A copy of each group header for the top and the bottom of the
        scrolling area, shown while the real one is out of sight."""
        self.ghosts = {}
        for dock_name in ("TopDock", "BottomDock"):
            dock = self.find(dock_name)
            dock.Children.Clear()
            for key, _prefix, title, accent in self.GROUP_TITLES:
                ghost = self._ghost(key, title, accent)
                ghost[0].Visibility = Visibility.Collapsed
                dock.Children.Add(ghost[0])
                self.ghosts[(dock_name, key)] = ghost
        scroll = self.find("GroupScroll")
        scroll.ScrollChanged += self._on_scroll
        scroll.SizeChanged += self._on_scroll

    def _ghost(self, key, title, accent):
        frame = Border()
        frame.CornerRadius = CornerRadius(5)
        frame.BorderThickness = Thickness(1)
        frame.Margin = Thickness(0, 2, 0, 2)
        frame.SetResourceReference(Border.BackgroundProperty, "BarBrush")
        frame.SetResourceReference(Border.BorderBrushProperty, "FrameBrush")
        button = Button()
        button.SetResourceReference(Button.StyleProperty, "GroupHeader")
        button.ToolTip = u"Open this group to fill the window"
        line = StackPanel()
        line.Orientation = Orientation.Horizontal
        bar = Border()
        bar.Width, bar.Height = 4.0, 16.0
        bar.CornerRadius = CornerRadius(2)
        bar.SetResourceReference(Border.BackgroundProperty, accent)
        line.Children.Add(bar)
        name = TextBlock()
        name.Text = title
        name.Margin = Thickness(8, 0, 0, 0)
        name.SetResourceReference(TextBlock.StyleProperty, "SectionLabel")
        line.Children.Add(name)
        summary = TextBlock()
        summary.Margin = Thickness(14, 0, 0, 0)
        summary.VerticalAlignment = VerticalAlignment.Center
        summary.SetResourceReference(TextBlock.StyleProperty, "MutedText")
        line.Children.Add(summary)
        button.Content = line
        button.Click += self._make_full(key)
        frame.Child = button
        return frame, summary

    def _on_scroll(self, sender, args):
        self._update_docks()

    def _update_docks(self):
        scroll = self.find("GroupScroll")
        try:
            viewport = float(scroll.ViewportHeight or scroll.ActualHeight)
        except Exception:
            return
        tops, height = [], 40.0
        for key, prefix, _title, _accent in self.GROUP_TITLES:
            header = self.find(prefix + "Header")
            try:
                tops.append(float(header.TranslatePoint(Point(0, 0), scroll).Y))
                height = float(header.ActualHeight) or height
            except Exception:
                tops.append(0.0)
        sides = core.dock_sides(tops, height, viewport)
        for (key, prefix, _title, _accent), side in zip(self.GROUP_TITLES, sides):
            for dock_name, wanted in (("TopDock", "top"), ("BottomDock", "bottom")):
                frame, summary = self.ghosts[(dock_name, key)]
                frame.Visibility = Visibility.Visible if side == wanted else Visibility.Collapsed
                try:
                    summary.Text = self.find(prefix + "Summary").Text
                except Exception:
                    pass

    def _make_full(self, key):
        def handler(sender, args):
            self._open_full(key)
        return handler

    def _open_full(self, key):
        """Open a group, make its main panel fill the scrolling area, and
        scroll it to the top - what a click on a docked header does."""
        prefix = dict([(item[0], item[1]) for item in self.GROUP_TITLES])[key]
        panel = self.find({"selection": "CalloutGrid", "array": "ArrayPanel",
                           "sheet": "SheetPanel"}[key])
        group = self.find(prefix + "Group")
        scroll = self.find("GroupScroll")
        self.folds[key].open(instant=True)
        try:
            self.window.UpdateLayout()
            panel.Height = core.fill_height(scroll.ViewportHeight, group.ActualHeight,
                                            panel.ActualHeight)
            self.window.UpdateLayout()
            offset = scroll.VerticalOffset + group.TranslatePoint(Point(0, 0), scroll).Y - 6.0
            scroll.ScrollToVerticalOffset(max(0.0, offset))
        except Exception as err:
            core.log(u"group {0} could not fill the window: {1}".format(key, err))
        self._preview_size = None
        self._sheet_size = None
        self._draw_preview()

    def _update_summaries(self):
        """What each group holds, written on its header - so a shut group
        still says what it is set to."""
        find = self.find
        try:
            shown = len(self.table.visible)
            ticked = len(self.table.ticked())
            hidden = len(self.rows) - shown
            text = u"{0} on show, {1} ticked".format(shown, ticked)
            if hidden > 0:
                text += u", {0} hidden".format(hidden)
            find("SelectionSummary").Text = text
        except Exception:
            pass
        try:
            x_count, y_count, depth, size = self._band_values()
            kind = self.settings.get("sec_view_family_type") or "the project default type"
            template = self.settings.get("sec_template") or "its default template"
            reach = u""
            below = core.get_float(self.settings, "sec_below_mm", 0.0)
            above = core.get_float(self.settings, "sec_above_mm", 0.0)
            if below or above:
                reach = u", {0:.0f} below / {1:.0f} above".format(below, above)
            scales = []
            for key, kind in core.SCALE_KEYS:
                own = core.parse_scale(self.settings.get(key, ""))
                if own:
                    scales.append(u"{0} {1}".format(kind, core.scale_text(own)))
            if scales:
                reach += u", " + u" / ".join(scales)
            if core.get_bool(self.settings, "sec_crop_grids", True):
                reach += u", grids cropped"
            if core.get_bool(self.settings, "sec_tag_rooms", True):
                reach += u", rooms tagged"
            find("ArraySummary").Text = u"{0} X, {1} Y, {2:.0f}mm deep{3}  -  {4}, {5}".format(
                x_count, y_count, depth, reach, kind, template)
            text = u"{0}  -  {1}".format(size, self._label(self.preset)[0])
            if self.plan:
                text += u"  -  {0}  {1}".format(self.plan[0].get("sheet_number", ""),
                                                 self.plan[0].get("sheet_name", ""))
                if len(self.plan) > 1:
                    text += u"  and {0} more".format(len(self.plan) - 1)
            find("SheetSummary").Text = text
        except Exception:
            pass

    def _on_not_on_sheet(self, sender, args):
        self._set_sheet_filter()
        self.table.refresh()
        self._say_route()

    def _on_view_filter(self, sender, args):
        """Callouts only, callouts and floor plans, or floor plans only.  The
        plans are read the first time they are wanted, so going to them
        refreshes; coming back is only a filter."""
        picked = ui.combo_value(self.find("ViewFilterCombo"))
        mode = dict([(label, key) for key, label in core.VIEW_FILTERS]).get(picked, "callouts")
        before = core.view_filter(self.settings)
        self.settings["view_filter"] = mode
        if getattr(self, "table", None) is None or not getattr(self, "rows", None) and before == mode:
            return
        has_plans = any([not row.get("is_callout", True) for row in (self.rows or [])])
        if mode != "callouts" and not has_plans and before == "callouts":
            self._on_refresh(None, None)
            return
        self._set_sheet_filter()
        self.table.refresh()
        self._say_route()
        self._draw_preview()

    def _set_sheet_filter(self):
        """Hide the callouts that are already on a sheet.

        It is a prefilter on the table rather than a rebuild of the rows, so
        the ones being hidden are still there to be counted and the column tick
        lists only offer what is actually on show.
        """
        try:
            hide = bool(self.find("NotOnSheetCheck").IsChecked)
        except Exception:
            hide = True
        try:
            only_picked = bool(self.find("SelectedOnlyCheck").IsChecked) and bool(self.picked_rows)
        except Exception:
            only_picked = False
        if only_picked:
            # what was picked in Revit is shown whether it is on a sheet or
            # not, and whatever the Views box says - it was picked on purpose
            keys = set([row.get("key") for row in self.picked_rows])
            self.table.prefilter = lambda row: row.get("key") in keys
            return
        mode = core.view_filter(self.settings)
        if hide:
            self.table.prefilter = lambda row: not row.get("sheet") and core.keeps_view(row, mode)
        else:
            self.table.prefilter = lambda row: core.keeps_view(row, mode)

    def _apply_revit_selection(self):
        """The first read only: narrow the table to the callouts that were
        selected in the project browser or the view, and tick them."""
        if getattr(self, "_picked_done", False):
            return
        self._picked_done = True
        if not (self.picked["keys"] or self.picked["names"]):
            return
        self.picked_rows = core.match_selection(self.rows, self.picked["keys"], self.picked["names"])
        check = self.find("SelectedOnlyCheck")
        if not self.picked_rows:
            check.Visibility = Visibility.Collapsed
            check.IsChecked = False
            core.log(u"{0} element(s) were selected but none is a callout the tool found"
                     .format(self.picked["count"]))
            self._picked_note = (u" - nothing selected in Revit is one of these callouts, "
                                 u"so all are shown")
            return
        for row in self.picked_rows:
            row["checked"] = True
        check.Visibility = Visibility.Visible
        check.IsChecked = True
        check.Content = u"Selected in Revit ({0})".format(len(self.picked_rows))
        self._picked_note = (u" - showing the {0} selected in Revit; untick Selected in Revit "
                             u"for the rest".format(len(self.picked_rows)))

    # ------------------------------------------------------------------
    def _show_debug_report(self):
        """The whole debug report in its own window, ready to be copied out.

        Shown after a run when the tick is on: it is the state of things at the
        moment the run happened, which is what is worth sending on, and it is
        not worth reading before there is anything to explain.
        """
        rows = self._targets() or ([self._current_row()] if self._current_row() else [])
        try:
            text = debug.report(self.doc, [row for row in rows if row],
                                self.settings, self.routes)
        except Exception:
            text = u"the debug report itself threw:\n\n{0}".format(traceback.format_exc())
        try:
            ui.prompt("Debug report", text.splitlines(), self.palette,
                      confirm=False, owner=self.window, height=640, copyable=True)
        except Exception as err:
            core.log("the debug window would not open: {0}".format(err))
            self.status(u"the debug report is in {0}".format(core.log_path()))

    def _on_flip_x(self, sender, args):
        self._flip_axis("X")

    def _on_flip_y(self, sender, args):
        self._flip_axis("Y")

    def _flip_axis(self, axis):
        """Turn a whole axis round, on every row it applies to.

        Any single sections on that axis that were turned round by hand are
        cleared at the same time, or the button would appear to do nothing to
        them - the axis flip and the override would cancel out.
        """
        if axis == "X":
            self.flip_x = not self.flip_x
        else:
            self.flip_y = not self.flip_y
        state = self.flip_x if axis == "X" else self.flip_y

        rows = self._targets() or [self._current_row()]
        touched = 0
        for row in rows:
            if row is None:
                continue
            row["flip_x" if axis == "X" else "flip_y"] = state
            per = row.get("flips") or {}
            for label in list(per.keys()):
                if label.startswith(axis):
                    del per[label]
            row["flips"] = per
            touched += 1

        self._mark_flips()
        self.table.refresh()
        self._draw_preview()
        self.status(u"{0} sections {1} on {2} row(s)".format(
            axis, "turned round" if state else "back the way they were", touched))

    def _on_section_click(self, label):
        """One section turned round, on the row the preview is showing."""
        row = self._current_row()
        if row is None:
            return
        per = row.get("flips") or {}
        per[label] = not bool(per.get(label))
        if not per[label]:
            del per[label]                  # back to whatever the axis says
        row["flips"] = per
        self.table.refresh()
        self._draw_preview()
        self.status(u"{0} turned round on {1}".format(label, row.get("name", "")))

    def _on_cut_moved(self, label, fraction):
        """A cut line dragged in the preview, on the row the preview shows -
        or put back on the even spacing when the fraction is None."""
        row = self._current_row()
        if row is None:
            return
        cuts = dict(row.get("cuts") or {})
        if fraction is None:
            cuts.pop(label, None)
            message = u"{0} back on the even spacing".format(label)
        else:
            cuts[label] = fraction
            extents = geom.extents_mm(row.get("frame")) if row.get("frame") else None
            message = u"{0} moved".format(label)
            if extents:
                low, high = (extents[1], extents[3]) if label.startswith("X") else \
                    (extents[0], extents[2])
                message = u"{0} moved to {1:.0f}mm from the {2} edge".format(
                    label, (high - low) * fraction,
                    "bottom" if label.startswith("X") else "left")
        row["cuts"] = cuts
        self.table.refresh()
        self._draw_preview()
        self.status(u"{0} on {1}".format(message, row.get("name", "")))

    def _mark_flips(self):
        """The arrow on each button points the way that axis is looking, so the
        button says what is on rather than what pressing it would do.  Drawn
        from a Path rather than set in a symbol font, so it cannot come out as
        an empty box on a machine without that font."""
        for name, state, axis in (("FlipXButton", self.flip_x, "X"),
                                  ("FlipYButton", self.flip_y, "Y")):
            try:
                button = self.find(name)
            except Exception:
                continue
            try:
                button.Style = self.window.TryFindResource(
                    "AccentButton" if state else "GhostButton")
            except Exception:
                pass
            try:
                button.Content = self._flip_glyph(axis, state)
                button.ToolTip = (
                    u"{0} axis sections look {1} - click to turn them round"
                    .format(axis, self._look_word(axis, state)))
            except Exception:
                pass

    def _look_word(self, axis, state):
        if axis == "X":
            return "up the page" if not state else "down the page"
        return "left" if not state else "right"

    def _flip_glyph(self, axis, state):
        """A letter and an arrow, both drawn as shapes."""
        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        letter = TextBlock()
        letter.Text = axis
        letter.Margin = Thickness(0, 0, 4, 0)
        letter.VerticalAlignment = VerticalAlignment.Center
        panel.Children.Add(letter)

        arrow = Polygon()
        points = PointCollection()
        if axis == "X":
            # an up or down arrow, for a section that looks along Y
            if state:
                for point in ((0.0, 0.0), (8.0, 0.0), (4.0, 7.0)):
                    points.Add(Point(point[0], point[1]))
            else:
                for point in ((0.0, 7.0), (8.0, 7.0), (4.0, 0.0)):
                    points.Add(Point(point[0], point[1]))
        else:
            if state:
                for point in ((0.0, 0.0), (0.0, 8.0), (7.0, 4.0)):
                    points.Add(Point(point[0], point[1]))
            else:
                for point in ((7.0, 0.0), (7.0, 8.0), (0.0, 4.0)):
                    points.Add(Point(point[0], point[1]))
        arrow.Points = points
        arrow.VerticalAlignment = VerticalAlignment.Center
        try:
            arrow.Fill = self.window.TryFindResource(
                "OrangeBrush" if axis == "X" else "BlueBrush")
        except Exception:
            pass
        panel.Children.Add(arrow)
        return panel

    def _make_step(self, box_name, step, low, high):
        def handler(sender, args):
            box = self.find(box_name)
            try:
                value = int(float(box.Text or 0))
            except Exception:
                value = 0
            value = max(low, min(high, value + step))
            box.Text = u"{0}".format(value)
        return handler

    # ------------------------------------------------------------------
    def refresh(self):
        # floor plans that are not callouts are only read when they are asked
        # for - they are hundreds of views on a real model
        include = core.view_filter(self.settings) != "callouts"
        # dragged cuts and single-section flips are made by hand in the
        # preview - a refresh reads the rows afresh and must not drop them
        kept = dict([(row.get("key"), (row.get("cuts"), row.get("flips")))
                     for row in (self.rows or []) if row.get("cuts") or row.get("flips")])
        try:
            self.rows, self.routes = model.callout_rows(
                self.doc, self.settings, include, self._on_progress)
            for row in self.rows:
                if row.get("key") in kept:
                    cuts, flips = kept[row["key"]]
                    row["cuts"] = dict(cuts or {})
                    row["flips"] = dict(flips or {})
        except Exception as err:
            core.log(traceback.format_exc())
            self.rows, self.routes = [], {}
            self.status(u"the callouts could not be read - {0}".format(err))
        for row in self.rows:
            if not row.get("frame"):
                row["state"] = "problem"
                row["status"] = "no crop box to read"
        if getattr(self, "_picked_done", False) and self.picked_rows:
            # a refresh builds new rows - keep the picked set pointing at them
            self.picked_rows = core.match_selection(
                self.rows, self.picked["keys"], self.picked["names"])
        self._apply_revit_selection()
        self._set_sheet_filter()
        self.table.set_rows(self.rows)
        self._say_route()
        self._draw_preview()

    def _say_route(self):
        counts = self.routes or {}
        found = len(self.rows)
        if not found:
            self.status(self._nothing_found())
            return
        parts = []
        for key, label in (("viewer", "their markers"), ("reference", "referenced"),
                           ("marker", "callout heads"), ("type", "the type name"),
                           ("cropped", "plans")):
            if counts.get(key):
                parts.append(u"{0} from {1}".format(counts[key], label))
        text = u"{0} callout(s): {1}".format(found, u", ".join(parts))
        timings = (self.routes or {}).get("ms") or {}
        spent = sum([value for value in timings.values() if value > 0])
        if spent > 0:
            text += u" - read in {0:.1f}s".format(spent / 1000.0)
        if timings.get("reference") == -1.0:
            text += u" (the slow route was not needed)"
        hidden = found - len(self.table.visible)
        picked = False
        try:
            picked = bool(self.find("SelectedOnlyCheck").IsChecked) and bool(self.picked_rows)
        except Exception:
            pass
        if picked:
            text += getattr(self, "_picked_note", u"")
        elif hidden > 0:
            text += u" - {0} already on a sheet, hidden".format(hidden)
        if not picked and getattr(self, "_picked_note", u"").startswith(u" - nothing"):
            text += self._picked_note
        self.status(text)

    def status(self, text):
        try:
            self.find("StatusText").Text = text
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _current_row(self):
        row = self.table.selected_row()
        if row is not None:
            return row
        ticked = self.table.ticked()
        if ticked:
            return ticked[0]
        return self.table.visible[0] if self.table.visible else None

    def _on_row_selected(self, row):
        try:
            self.find("OpenViewButton").IsEnabled = row is not None
        except Exception:
            pass
        self._draw_preview()

    def _on_table_change(self):
        self._build_plan_text()
        self._update_summaries()

    def _on_search(self, sender, args):
        self.table.keyword = self.find("SearchBox").Text or ""
        self.table.refresh()

    def _on_counts(self, sender, args):
        """The band IS the control, so changing it changes the rows.

        It used to redraw the preview and nothing else: the counts lived on the
        rows, set when the table was read, and only "Set on ticked rows" moved
        them.  So the preview showed three sections, the run built two, and
        nothing said they disagreed.  The band now writes straight through to
        whatever it applies to.
        """
        self._apply_band_to_rows()
        self._draw_preview()

    def _band_targets(self):
        """What the band applies to: the ticked rows, or everything on show
        when nothing is ticked - the same rule as the Create button, so the
        preview cannot describe a different set from the run."""
        return self._targets() or list(self.table.visible)

    def _apply_band_to_rows(self):
        if getattr(self, "table", None) is None or not getattr(self, "rows", None):
            return                          # still being wired up
        try:
            x_count, y_count, depth, size = self._band_values()
        except Exception:
            return
        changed = core.apply_counts(self._band_targets(), x_count, y_count, depth, size)
        if changed:
            self.table.refresh()

    def _on_canvas_size(self, sender, args):
        """Redraw after the layout has settled, not during it.

        SizeChanged is raised inside the arrange pass, and reading ActualWidth
        there hands back the size the canvas is coming *from* rather than the
        one it is going to.  Growing then hid it - a later redraw fixed it up -
        but shrinking left the drawing at its full screen size with nothing to
        trigger another pass.  Queue the redraw at Render priority instead, and
        skip it when the size has not actually moved so this can never chase
        its own tail.
        """
        try:
            size = (round(float(sender.ActualWidth), 1), round(float(sender.ActualHeight), 1))
        except Exception:
            size = None
        try:
            self.window.Dispatcher.BeginInvoke(
                DispatcherPriority.Render, Action(self._redraw_if_resized))
        except Exception:
            self._draw_preview()
        return size

    def _redraw_if_resized(self):
        """Both previews: whichever has changed size is drawn again."""
        def size_of(name):
            try:
                canvas = self.find(name)
                return (round(float(canvas.ActualWidth), 1), round(float(canvas.ActualHeight), 1))
            except Exception:
                return None
        section = size_of("PreviewCanvas")
        if section is not None and section != getattr(self, "_preview_size", None):
            self._preview_size = section
            self._draw_preview()
            return                          # that draws the sheet as well
        sheet = size_of("SheetCanvas")
        if sheet is not None and sheet != getattr(self, "_sheet_size", None):
            self._sheet_size = sheet
            self._draw_sheet()

    def _nothing_found(self):
        """Say what is in the model rather than just that nothing matched.

        A model whose callouts neither route 1 nor route 2 can see is answered
        by the view family type name, and the only way to set that token is to
        know what the types are actually called - so read them out.
        """
        token = self.settings.get("type_contains", "Callout")
        try:
            tally = model.view_type_tally(self.doc)
        except Exception:
            tally = []
        core.log(u"nothing found; view family types present: {0}".format(
            u", ".join([u"{0} ({1})".format(name, count) for name, count in tally])))
        if not tally:
            return ("no callout views found, and no view family types could be "
                    "read either")
        shown = u", ".join([u"{0} ({1})".format(name, count)
                            for name, count in tally[:6]])
        if len(tally) > 6:
            shown += u" and {0} more".format(len(tally) - 6)
        return (u"no callout views found - nothing matches \u201c{0}\u201d. The view "
                u"family types in this model are: {1}. Set the token in "
                u"Settings > Finding callouts.").format(token, shown)

    def _band_values(self):
        try:
            x_count = max(0, int(float(self.find("XCountBox").Text or 0)))
        except Exception:
            x_count = 0
        try:
            y_count = max(0, int(float(self.find("YCountBox").Text or 0)))
        except Exception:
            y_count = 0
        try:
            depth = float(self.find("DepthBox").Text or 500)
        except Exception:
            depth = 500.0
        size = ui.combo_value(self.find("SizeCombo")) or \
            self.settings.get("sheet_size_default", "A1")
        return x_count, y_count, depth, size

    def _draw_preview(self):
        row = self._current_row()
        x_count, y_count, depth, _size = self._band_values()
        extents = geom.extents_mm(row.get("frame")) if row else None
        title = row.get("name") if row else ""
        try:
            canvas = self.find("PreviewCanvas")
            flip_x = self.flip_x if row is None else row.get("flip_x", self.flip_x)
            flip_y = self.flip_y if row is None else row.get("flip_y", self.flip_y)
            preview.draw(canvas, extents, x_count, y_count, flip_x, flip_y, title,
                         (row or {}).get("flips") or {}, self._on_section_click,
                         (row or {}).get("cuts") or {}, self._on_cut_moved)
            self._preview_size = (round(float(canvas.ActualWidth), 1),
                                  round(float(canvas.ActualHeight), 1))
        except Exception as err:
            core.log("preview failed: {0}".format(err))
        self._build_plan_text()
        self._draw_sheet()

    def _targets(self):
        ticked = self.table.ticked()
        if ticked:
            return ticked
        return self.table.selected_rows()

    def _build_plan_text(self):
        rows = self._targets()
        if not rows:
            try:
                self.find("PlanText").Text = ("Tick the callouts to run, then press "
                                              "Create views and sheets.")
            except Exception:
                pass
            self.plan = []
            return
        try:
            self.plan = ops.build_plan(self.doc, rows, self.settings)
            lines = ops.plan_lines(self.plan)
            self.find("PlanText").Text = u"\n".join(lines)
            self._show_rules()
        except Exception as err:
            core.log(traceback.format_exc())
            try:
                self.find("PlanText").Text = u"the plan could not be worked out - {0}".format(err)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _on_all(self, sender, args):
        for row in self.table.visible:
            row["checked"] = True
        self.table.refresh()

    def _on_none(self, sender, args):
        for row in self.rows:
            row["checked"] = False
        self.table.refresh()

    def _on_apply_rows(self, sender, args):
        x_count, y_count, depth, size = self._band_values()
        rows = self._targets() or self.table.visible
        for row in rows:
            row["x_count"] = x_count
            row["y_count"] = y_count
            row["depth_mm"] = depth
            row["size"] = size
            row["flip_x"] = self.flip_x
            row["flip_y"] = self.flip_y
        self.table.refresh()
        flipped = " ".join([axis for axis, state in
                            (("X", self.flip_x), ("Y", self.flip_y)) if state])
        self.status(u"set {0} X, {1} Y, {2:.0f}mm, {3}{4} on {5} row(s)".format(
            x_count, y_count, depth, size,
            u", flipped {0}".format(flipped) if flipped else "", len(rows)))
        self._draw_preview()

    def _on_open_view(self, sender, args):
        row = self.table.selected_row()
        if row is None:
            return
        try:
            self.open_handler.view_id = row["id"]
            self.open_event.Raise()
        except Exception as err:
            self.status(u"the view would not open - {0}".format(err))

    def _on_refresh(self, sender, args):
        self._set_busy(True)
        try:
            return self._refresh_now()
        finally:
            self._set_busy(False)

    def _refresh_now(self):
        """Refresh also takes a new Revit selection: pick callouts with the
        window open, press Refresh, and the table narrows to them."""
        try:
            fresh = model.selection_targets(self.uidoc)
        except Exception:
            fresh = None
        if fresh and (fresh["keys"] or fresh["names"]) and \
                (fresh["keys"], fresh["names"]) != (self.picked["keys"], self.picked["names"]):
            self.picked = fresh
            self.picked_rows = []
            self._picked_done = False
        self.refresh()

    def _on_plan(self, sender, args):
        rows = self._targets()
        if not rows:
            self.status("nothing ticked")
            return
        self._build_plan_text()
        ui.prompt("What Create would do now", ops.plan_lines(self.plan) or ["nothing"],
                  self.palette, confirm=False, owner=self.window)

    # ------------------------------------------------------------------
    def _on_create(self, sender, args):
        # the band writes through on every change, but a box still holding an
        # uncommitted keystroke would not have fired yet
        self._apply_band_to_rows()
        if self.busy:
            return
        rows = self._targets()
        if not rows:
            self.status("tick the callouts to run first")
            return
        for row in rows:
            if not row.get("frame"):
                self.status(u"{0} has no crop box, so it cannot be run".format(row["name"]))
                return

        self._build_plan_text()
        if not self.plan:
            self.status("nothing to do")
            return

        lines = ["This will create:", ""] + ops.plan_lines(self.plan)
        asked = self._band_values()
        rows = self._targets()
        odd = [row for row in rows
               if (row.get("x_count"), row.get("y_count")) != (asked[0], asked[1])]
        if odd:
            lines += ["", u"{0} row(s) do not carry the {1} X and {2} Y in the band "
                          u"- their own counts are used:".format(
                              len(odd), asked[0], asked[1])]
            for row in odd[:8]:
                lines.append(u"    {0}   {1} X, {2} Y".format(
                    row.get("name", ""), row.get("x_count", 0), row.get("y_count", 0)))
        hidden = self.table.ticked_out_of_sight()
        if hidden:
            lines += ["", u"{0} ticked callout(s) are filtered out of sight and "
                          u"will NOT be run:".format(len(hidden))]
            for row in hidden[:12]:
                lines.append(u"    {0}".format(row.get("name", "")))
            if len(hidden) > 12:
                lines.append(u"    and {0} more".format(len(hidden) - 12))
        if core.get_bool(self.settings, "sec_tag_rooms", True):
            lines += ["", u"Untagged rooms the new sections cut will be tagged with {0}.".format(
                self.settings.get("sec_room_tag_type") or "the project's default room tag")]
        below = core.get_float(self.settings, "sec_below_mm", 0.0)
        above = core.get_float(self.settings, "sec_above_mm", 0.0)
        if below or above:
            lines.append(u"Sections reach {0:.0f}mm below the bottom level and {1:.0f}mm "
                         u"above the top.".format(below, above))
        if self.preset == core.CUSTOM:
            lines += ["", u"Every sheet is laid out to the custom setout ({0} view(s) placed "
                          u"by hand).".format(len(core.custom_moves(self.settings)))]
        for key, kind in core.SCALE_KEYS:
            own = core.parse_scale(self.settings.get(key, ""))
            if own:
                lines.append(u"The {0} at {1} wherever its template leaves the scale "
                             u"unlocked.".format(kind, core.scale_text(own)))
        lines += ["", "Revit's undo will see the whole run as one step."]
        if not ui.prompt("Create views and sheets", lines, self.palette,
                         confirm=True, owner=self.window):
            return

        self.settings["layout_preset"] = self.preset
        self._set_busy(True)
        self._on_progress(0, len(self.plan), "starting")
        try:
            self.run_handler.groups = self.plan
            self.run_handler.settings = dict(self.settings)
            self.run_handler.on_done = self._on_done
            self.run_handler.on_progress = self._on_progress
            self.run_event.Raise()
        except Exception as err:
            core.log(traceback.format_exc())
            self._set_busy(False)
            self.status(u"the run would not start - {0}".format(err))

    def _set_busy(self, state):
        self.busy = bool(state)
        # The body and the other header controls go deaf; the shrink button
        # does not.  It is the one control somebody wants while a run holds
        # Revit - to put the window away and watch - and it touches nothing
        # but the window's own geometry.  Making the whole window
        # hit-test-dead used to take it down with everything else.
        live = not self.busy
        try:
            header = self.find("HeaderBar")
            for child in list(header.Parent.Children):
                if child is not header:
                    child.IsHitTestVisible = live
        except Exception:
            pass
        for name in BUSY_DEAF:
            try:
                self.find(name).IsEnabled = live
            except Exception:
                pass
        shown = Visibility.Visible if self.busy else Visibility.Collapsed
        for name in ("ProgressTrack", "ProgressText"):
            try:
                self.find(name).Visibility = shown
            except Exception:
                pass
        if not self.busy:
            try:
                self.find("ProgressFill").Width = 0
            except Exception:
                pass

    def _on_progress(self, done, total, message):
        """Move the bar and repaint.

        This is only ever called between transactions - see ops.run.  The pump
        is at Render priority, which processes Render and everything above it
        but NOT Input, which sits below: the bar repaints without real mouse
        and key messages being dispatched into a half finished run.
        """
        try:
            total = max(1, int(total))
            fraction = max(0.0, min(1.0, float(done) / float(total)))
        except Exception:
            fraction = 0.0
        try:
            track = self.find("ProgressTrack")
            width = float(track.ActualWidth or 0.0)
            if width <= 0:
                # the band was collapsed a moment ago, so it has not been
                # through a layout pass yet and has no width to scale by
                track.UpdateLayout()
                width = float(track.ActualWidth or 0.0)
            self.find("ProgressFill").Width = max(0.0, width * fraction)
        except Exception:
            pass
        try:
            self.find("ProgressText").Text = u"{0:.0f}%  {1}".format(fraction * 100.0, message)
        except Exception:
            pass
        self.status(u"working - {0}".format(message))
        try:
            self.window.Dispatcher.Invoke(DispatcherPriority.Render, Action(lambda: None))
        except Exception:
            pass

    def _keep_learned_sign(self, results):
        """The run works on a copy of the settings, so a direction the first
        section taught it has to be carried back and saved here - or the
        window writes its own stale copy over it on close."""
        learned = getattr(results, "learned_sign", None)
        if learned is None:
            return
        value = "1" if float(learned) > 0 else "-1"
        if self.settings.get("sec_sign") == value:
            return
        self.settings["sec_sign"] = value
        try:
            core.save_settings(self.settings)
            core.log(u"section direction learned and kept: {0}".format(value))
        except Exception as err:
            core.log(u"section direction could not be saved: {0}".format(err))

    def _on_done(self, results):
        """Called from Revit's thread at the end of the external event."""
        def finish():
            self._set_busy(False)
            self._keep_learned_sign(results)
            try:
                self.refresh()
            except Exception:
                pass
            summary = u"{0} view(s) on {1} sheet(s)".format(results.views, len(results.sheets))
            if results.failures:
                summary += u", {0} not done".format(len(results.failures))
            if results.warnings:
                summary += u", {0} worth a look".format(len(results.warnings))
            self.status(summary)
            mode = str(self.settings.get("results", "needed")).lower()
            if mode == "always" or (mode == "needed" and results.needs_a_look):
                ui.prompt("Callout to 3D", results.lines(), self.palette,
                          confirm=False, owner=self.window)
            try:
                if bool(self.find("DebugCheck").IsChecked):
                    self._show_debug_report()
            except Exception as err:
                core.log("the debug report was asked for but threw: {0}".format(err))
            self._offer_the_sheets(results)

        try:
            self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(finish))
        except Exception:
            try:
                finish()
            except Exception:
                core.log(traceback.format_exc())

    def _offer_the_sheets(self, results):
        """Ask, and if the answer is yes get out of the way first.

        The tool is closed before the sheets open rather than after: opening a
        sheet is a view change, and leaving a modeless window sitting over the
        drawing that was just asked for is not the point of asking.
        """
        ids = list(getattr(results, "sheet_ids", None) or [])
        if not ids:
            return
        mode = str(self.settings.get("after_run", "ask")).strip().lower()
        if mode == "never":
            return
        lines = [u"{0} sheet(s) were created:".format(len(ids)), ""]
        for number, name, count in results.sheets:
            lines.append(u"    {0}   {1}".format(number, name))
        lines += ["", "Open them now? The tool will close."]
        if mode != "always" and not ui.prompt(
                "Open the new sheets", lines, self.palette,
                confirm=True, owner=self.window,
                yes="Open them", no="Stay here"):
            return
        try:
            self.open_handler.view_ids = ids
            self.open_handler.view_id = None
            self.open_event.Raise()
        except Exception as err:
            core.log(traceback.format_exc())
            self.status(u"the sheets would not open - {0}".format(err))
            return
        try:
            self.window.Close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _on_settings(self, sender, args):
        def applied(values):
            self.settings = values
            self.palette = theme_module.resolve(self.settings)
            ui.apply_theme(self.window, self.palette)
            self._update_theme_chip()
            self.preset = values.get("layout_preset", self.preset)
            if self.preset not in geom.preset_keys() + [core.CUSTOM]:
                self.preset = "columns"
            self._paper_cache = None
            self._sync_inline()
            self.refresh()

        try:
            window = settings_module.SettingsWindow(
                self.doc, self.settings, applied, owner=self.window)
            window.show(modal=True)
        except Exception as err:
            core.log(traceback.format_exc())
            self.status(u"the settings window would not open - {0}".format(err))

    def _on_theme(self, sender, args):
        order = ["auto", "dark", "light"]
        current = str(self.settings.get("theme", "auto")).lower()
        index = order.index(current) if current in order else 0
        self.settings["theme"] = order[(index + 1) % len(order)]
        self.palette = theme_module.resolve(self.settings)
        ui.apply_theme(self.window, self.palette)
        self._update_theme_chip()
        core.save_settings(self.settings)
        self.table.refresh()
        self._draw_preview()
        self._draw_cards()

    def _update_theme_chip(self):
        wanted = str(self.settings.get("theme", "auto")).lower()
        label = {"auto": u"Auto ({0})".format(self.palette),
                 "dark": "Dark", "light": "Light"}.get(wanted, "Auto")
        try:
            self.find("ThemeChip").Content = label
        except Exception:
            pass

    def _on_full(self, sender, args):
        self.chrome.toggle_full_screen()

    def _on_close(self, sender, args):
        try:
            self.window.Close()
        except Exception:
            pass

    def _on_closing(self, sender, args):
        if self.busy:
            args.Cancel = True
            self.status("wait for the run to finish before closing")
            return
        # the band is remembered whatever "remember the window size" says -
        # they are different questions, and having to reset the section counts
        # every time the tool opens is the thing that grates
        try:
            x_count, y_count, depth, size = self._band_values()
            self.settings["sec_x_count"] = u"{0}".format(x_count)
            self.settings["sec_y_count"] = u"{0}".format(y_count)
            self.settings["sec_depth_mm"] = u"{0:.0f}".format(depth)
            self.settings["sheet_size_default"] = u"{0}".format(size)
            self.settings["sec_flip_x"] = "1" if self.flip_x else "0"
            self.settings["sec_flip_y"] = "1" if self.flip_y else "0"
            self.settings["hide_on_sheet"] = \
                "1" if bool(self.find("NotOnSheetCheck").IsChecked) else "0"
            self.settings["debug_report"] = \
                "1" if bool(self.find("DebugCheck").IsChecked) else "0"
            self.settings["layout_preset"] = self.preset
            self.settings["groups_open"] = core.groups_text(
                [key for key, fold in self.folds.items() if fold.opened])
        except Exception as err:
            core.log("could not read the band back: {0}".format(err))
        if core.get_bool(self.settings, "remember_size", True):
            try:
                # full screen leaves Width and Height as the working area, and
                # a window shown at Auto leaves them NaN - neither is worth
                # writing back over a good remembered size
                width = float(self.window.Width)
                height = float(self.window.Height)
                if width == width and height == height and width > 200 and height > 200:
                    self.settings["window_w"] = u"{0:.0f}".format(width)
                    self.settings["window_h"] = u"{0:.0f}".format(height)
            except Exception:
                pass
        try:
            core.save_settings(self.settings)
        except Exception as err:
            core.log("settings could not be saved on close: {0}".format(err))

    def show(self, uiapp=None):
        """Put the window up first and read the model afterwards.

        The read is the slow part on a real project, and doing it before the
        window appears means several seconds of nothing happening after the
        button is pressed - which reads as the tool having failed to start.
        Queued at Background priority, so the window is painted and responsive
        before the scan begins.
        """
        ui.own_to_revit(self.window, uiapp)
        self.window.Show()
        try:
            self.window.Dispatcher.BeginInvoke(
                DispatcherPriority.Background, Action(self._first_read))
        except Exception:
            self._first_read()

    def _first_read(self):
        started = time.time()
        self._set_busy(True)
        self._on_progress(0, 5, "reading the model")
        try:
            self.refresh()
        except Exception:
            core.log(traceback.format_exc())
            return
        finally:
            self._set_busy(False)
        core.log("first read took {0:.2f}s for {1} callout(s)".format(
            time.time() - started, len(self.rows)))
