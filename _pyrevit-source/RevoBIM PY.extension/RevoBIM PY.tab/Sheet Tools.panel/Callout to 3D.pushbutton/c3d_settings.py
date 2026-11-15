# -*- coding: utf-8 -*-
"""Callout to 3D - the settings window.

Nine groups down a rail on the left, each with its own icon, and the fields
for the chosen group built in code on the right inside a scroll viewer.  The
window carries its own resize grips and goes full screen, so a long group is
never trapped in a fixed height.
"""

import c3d_clr  # noqa: F401  assemblies first, always

import c3d_core as core
import c3d_model as model
import c3d_ui as ui
import theme as theme_module

from System.Windows import (                                                    # noqa: E402
    Thickness, VerticalAlignment, HorizontalAlignment, TextWrapping,
)
from System.Windows.Controls import (                                          # noqa: E402
    TextBlock, TextBox, CheckBox, ComboBox, Button, StackPanel, Orientation,
    Grid, ColumnDefinition,
)
from System.Windows.Shapes import Path as ShapePath                            # noqa: E402
from System.Windows.Media import Geometry, Stretch                             # noqa: E402
from System.Windows import GridLength, GridUnitType                            # noqa: E402

BLANK = "(the project default)"
BLANK_VP = "(the default viewport type)"

ICONS = {
    "views": "M 8,1 L 15,5 L 8,9 L 1,5 Z M 1,9 L 8,13 L 15,9",
    "3d": "M 8,1 L 14,4.5 L 14,11.5 L 8,15 L 2,11.5 L 2,4.5 Z M 8,1 L 8,8 M 2,4.5 L 8,8 L 14,4.5",
    "sections": "M 1,6 L 15,6 M 4,6 L 4,10 M 12,6 L 12,10 M 1,13 L 15,13",
    "naming": "M 2,2 L 9,2 L 14,8 L 9,14 L 2,14 Z M 5,7 L 6,7",
    "sheets": "M 3,1 L 13,1 L 13,15 L 3,15 Z M 5,4 L 11,4 M 5,7 L 11,7 M 5,10 L 9,10",
    "layout": "M 1,2 L 7,2 L 7,7 L 1,7 Z M 9,2 L 15,2 L 15,7 L 9,7 Z M 1,9 L 7,9 L 7,14 L 1,14 Z M 9,9 L 15,9 L 15,14 L 9,14 Z",
    "viewports": "M 1,3 L 15,3 L 15,13 L 1,13 Z M 1,6 L 15,6",
    "push": "M 1,8 L 9,8 M 6,5 L 9,8 L 6,11 M 11,2 L 15,2 L 15,14 L 11,14",
    "appearance": "M 8,1 A 7,7 0 1 1 8,15 A 7,7 0 1 1 8,1 Z M 8,1 L 8,15",
    "finding": "M 2,2 L 7,2 L 7,7 L 2,7 Z M 7,4.5 L 10,4.5 "
               "M 11,7 A 3,3 0 1 1 11,13 A 3,3 0 1 1 11,7 Z M 13.2,12.2 L 15,14",
}


def _choice(pairs):
    return [(value, label) for value, label in pairs]


GROUPS = [
    {
        "key": "finding", "name": "Finding callouts", "icon": "finding",
        "blurb": "how the table works out what is a callout",
        "fields": [
            ("choice", "scan_scope", "Look at", _choice([
                ("plans", "plan views only - fastest"),
                ("plans_sections", "plans, sections, elevations and details"),
                ("every", "every view in the project - slowest")])),
            ("note", "", "A callout of a plan is a plan view and a detail callout is a section view, so the first two cover every callout there is. Asking every "
                         "view in the project, one call at a time, is what makes the tool slow to open on a big model.", None),
            ("check", "route_viewer", "Read the view markers drawn in the parent views (fast) - "
                                      "a plan with a marker is a callout", None),
            ("check", "route_marker", "Read the callout marker elements (fast)", None),
            ("check", "route_type", "Match the view's own view family type name (fast)", None),
            ("check", "route_reference", "Ask the views what callouts they carry (slow)", None),
            ("check", "route_reference_always", "Run the slow one even when the others "
                                                "found something", None),
            ("note", "", "The order is a speed decision. The marker route is a quick "
                         "filter over one category and the type route is one cached "
                         "read per view; asking every view what callouts it carries is "
                         "an API call per view, and on a real model that is the whole "
                         "of the wait to open the tool. So it runs last, and only when "
                         "the other two came back empty. It is the only route that "
                         "fills in the Cut in column, so tick the box above if that "
                         "column matters more than the wait.", None),
            ("text", "type_contains", "That name contains", None),
            ("note", "", "Comma separated, and any one of them matching is enough. "
                         "This is the route that answers a model where the first "
                         "two come back empty - set it to whatever the callout view "
                         "family types are actually called. When nothing is found "
                         "at all, the status line reads out the type names that are "
                         "in the model so the token can be set from what is there "
                         "rather than guessed.", None),
            ("note", "", "The first two routes are callout-only by construction. "
                         "The third is only as good as the naming, and 'Every "
                         "cropped view' in the main window is a last resort that "
                         "makes no claim at all - a row from it says so.", None),
        ],
    },
    {
        "key": "views", "name": "Views and templates", "icon": "views",
        "blurb": "what the new views are built from",
        "fields": [
            ("combo3d", "3d_view_family_type", "3D view family type", "vft3d"),
            ("combo3d", "3d_template", "3D view template", "tpl3d"),
            ("combosec", "sec_view_family_type", "Section view family type", "vftsec"),
            ("combosec", "sec_template", "Section view template", "tplsec"),
            ("check", "template_follows_type", "Picking a view family type offers its "
                                               "own template", None),
            ("check", "template_list_all", "Offer every view template, not only the "
                                           "matching kind", None),
            ("note", "", "A template filed under Detail or Elevation applies to a "
                         "section perfectly well, so all three are offered as section "
                         "templates. The offered template is a starting point - pick "
                         "any other and it stays.", None),
            ("choice", "view_scale_rule", "New views take", _choice([
                ("match_callout", "the callout's own scale"),
                ("fixed", "a fixed scale")])),
            ("int", "view_scale_fixed", "That fixed scale, 1:", None),
            ("note", "", "A blank template box means the view family type's own "
                         "default template, which is what Revit itself would apply.", None),
        ],
    },
    {
        "key": "3d", "name": "The 3D view", "icon": "3d",
        "blurb": "the section box cut from the callout",
        "fields": [
            ("float", "3d_bottom_offset_mm", "Cut the box bottom below the bottom by (mm)", None),
            ("choice", "3d_top_rule", "The box is cut", _choice([
                ("view_range", "to the callout's own view range"),
                ("next_level", "from the level to the level above"),
                ("fixed", "from the level to a fixed height"),
                ("callout", "to the callout's own view depth")])),
            ("note", "", "The view range is what the callout plan actually shows, "
                         "so the 3D box and the sections show the same thing the "
                         "callout does. A plane set to unlimited says nothing "
                         "useful, and the level rule is used instead.", None),
            ("float", "3d_top_fixed_mm", "That fixed height (mm)", None),
            ("float", "3d_top_offset_mm", "Move the box top off the top by (mm)", None),
            ("note", "", "The top offset is measured from the top of the view range or "
                         "the level above. Negative stops the box short of it, which is "
                         "what keeps the slab over it out of the view; positive pushes "
                         "it through. It is not applied to the fixed height, which "
                         "already says where the top goes.", None),
            ("float", "3d_xy_margin_mm", "Section box crop offset - grow it past the callout "
                                         "in X and Y by (mm)", None),
            ("choice", "3d_orientation", "Point the view from the", _choice([
                ("se_iso", "south east"), ("sw_iso", "south west"),
                ("ne_iso", "north east"), ("nw_iso", "north west"),
                ("keep", "leave Revit's own default")])),
            ("float", "3d_pitch_degrees", "Looking down at this angle (degrees)", None),
            ("note", "", "The compass corner says which side the camera stands on and "
                         "the angle says how far above the callout it stands - 35 is "
                         "the true isometric, where a cube's three faces come out "
                         "equal. It always looks down.", None),
            ("check", "3d_crop_tight", "Crop the view tight round the section box", None),
            ("float", "3d_crop_margin_mm", "With this much air round it (mm)", None),
            ("check", "3d_crop_active", "Crop the view (ie \"do not crop view\" off)", None),
            ("check", "3d_crop_visible", "Show the crop region", None),
            ("note", "", "The crop is pulled in before the view is placed, so the "
                         "viewport is exactly the size of the callout rather than "
                         "whatever Revit thinks is visible.", None),
            ("check", "3d_section_box_visible", "Show the section box in the view", None),
        ],
    },
    {
        "key": "sections", "name": "Sections", "icon": "sections",
        "blurb": "defaults for the array; the main window overrides them per callout",
        "fields": [
            ("int", "sec_x_count", "X axis sections to start with", None),
            ("int", "sec_y_count", "Y axis sections to start with", None),
            ("float", "sec_depth_mm", "Cut depth (mm)", None),
            ("note", "", "The sections are cut over exactly the same band as "
                         "the 3D section box - the bottom and the top come "
                         "from the 3D group, so what the 3D shows and what "
                         "the sections cut cannot disagree.", None),
            ("choice", "sec_top_rule", "The top of a section is", _choice([
                ("match_3d", "the same as the 3D box"),
                ("fixed", "a fixed height above the level")])),
            ("float", "sec_side_margin_mm", "Run the section past the callout by (mm)", None),
            ("float", "sec_below_mm", "Sections reach below the bottom level by (mm)", None),
            ("float", "sec_above_mm", "Sections reach above the top of the band by (mm)", None),
            ("text", "sec_scale", "Section scale, e.g. 1:20 - blank for the same as the other "
                                  "views; a template that holds the scale wins", None),
            ("text", "3d_scale", "3D scale, e.g. 1:50 - blank for the same as the other views", None),
            ("text", "callout_scale", "Callout scale, e.g. 1:20 - blank to keep its own", None),
            ("check", "sec_crop_grids", "Cut the grids in each section down to its crop", None),
            ("float", "sec_grid_inset_mm", "Stop the grid ends this far inside the crop (mm)", None),
            ("check", "sec_tag_rooms", "Tag the rooms each section cuts that are not tagged", None),
            ("text", "sec_room_tag_type", "Room tag (Family : Type, blank for the default)", None),
            ("float", "sec_room_tag_lift_mm", "Room tag height above the floor (mm)", None),
            ("check", "sec_flip_x", "Turn the X axis sections round", None),
            ("check", "sec_flip_y", "Turn the Y axis sections round", None),
            ("check", "sec_title_on_sheet", "Write the axis label as the title on sheet", None),
            ("text", "sec_title_pattern", "That label reads", None),
            ("note", "", "Tokens: {label} is X1, X2, Y1 and so on, {axis} is just X or Y, {callout} is the callout name. The axis also goes into the view name.", None),
            ("check", "sec_far_clip_active", "Clip the far side at the cut depth", None),
        ],
    },
    {
        "key": "naming", "name": "Naming", "icon": "naming",
        "blurb": "new view names and the callout rename",
        "fields": [
            ("text", "view_name_pattern", "New view name", None),
            ("text", "kind_token_3d", "The {kind} token for a 3D", None),
            ("text", "kind_token_section", "The {kind} token for a section", None),
            ("check", "rename_callouts", "Rename the callout as well", None),
            ("text", "callout_rename_pattern", "Callout name", None),
            ("choice", "abbrev_source", "The abbreviation comes from", _choice([
                ("callout", "the callout's own view template"),
                ("new_template", "the new view's template")])),
            ("text", "abbrev_stopwords", "Words dropped from an abbreviation", None),
            ("int", "abbrev_max_tokens", "Most words kept in an abbreviation", None),
            ("choice", "abbrev_case", "Abbreviation case", _choice([
                ("camel", "camel case"), ("as_is", "as written"),
                ("upper", "upper case")])),
            ("check", "abbrev_drop_numeric", "Drop numbers from an abbreviation", None),
            ("choice", "level_token", "The {level} token is", _choice([
                ("name", "the level's full name"),
                ("short", "the shortest useful part of it")])),
            ("note", "", "Tokens: {kind} {level} {abbrev} {callout} {n} {nn}. "
                         "{n} counts up until the name is free.", None),
        ],
    },
    {
        "key": "sheets", "name": "Sheets", "icon": "sheets",
        "blurb": "numbering, naming and paper size",
        "fields": [
            ("text", "sheet_number_pattern", "Sheet number", None),
            ("text", "title_gap_mm", "Viewport titles this far under the view (mm, sheet) - "
                                     "blank leaves them where Revit puts them", None),
            ("int", "sheet_number_start", "Start numbering at", None),
            ("text", "sheet_name_pattern", "Sheet name", None),
            ("choice", "after_run", "Once the run has finished", _choice([
                ("ask", "ask whether to open the new sheets"),
                ("always", "open them without asking"),
                ("never", "leave them closed")])),
            ("choice", "sheet_group_rule", "One sheet per", _choice([
                ("per_callout", "callout"), ("per_level", "level")])),
            ("text", "sheet_sizes", "Paper sizes offered", None),
            ("text", "sheet_size_default", "Default paper size", None),
            ("sizemap", "sheet_titleblocks", "Title block family and type, per size", None),
            ("note", "", "One row per paper size offered above. Left is the family, "
                         "right is the type within it. Leave a row blank and the "
                         "first title block whose name carries that size is used.", None),
            ("choice", "callout_on_sheet", "A callout already on a sheet", _choice([
                ("report", "is left where it is and reported"),
                ("duplicate", "is duplicated with detailing and placed")])),
            ("note", "", "Tokens: {level} {abbrev} {callout} {n} {nn} {nnn} in the "
                         "number, and {d} for the detail count in the name.", None),
        ],
    },
    {
        "key": "layout", "name": "Sheet layout", "icon": "layout",
        "blurb": "where the viewports land",
        "fields": [
            ("float", "sheet_margin_left_mm", "Left margin (mm)", None),
            ("float", "sheet_margin_right_mm", "Right margin, clear of the title strip (mm)", None),
            ("float", "sheet_margin_top_mm", "Top margin (mm)", None),
            ("float", "sheet_margin_bottom_mm", "Bottom margin (mm)", None),
            ("float", "sheet_gap_mm", "Gap between the plan and the 3D (mm)", None),
            ("float", "section_gap_mm", "Gap between the sections (mm)", None),
            ("float", "section_min_gap_mm", "Squeeze that gap to no less than (mm)", None),
            ("float", "layout_pad_mm", "Clear air round every viewport (mm)", None),
            ("note", "", "The X sections go down the left of the sheet under the "
                         "plan and the Y sections down the right under the 3D, "
                         "each stacked below the last. The gap is squeezed to fit "
                         "as many in as will go; when they still run past the "
                         "bottom they carry on below it and the sheet is flagged "
                         "for a manual review rather than a view being shrunk or "
                         "dropped.", None),
        ],
    },
    {
        "key": "viewports", "name": "Viewport types", "icon": "viewports",
        "blurb": "the title bar each placed view gets",
        "fields": [
            ("combovp", "vp_type_callout", "The callout", "vp"),
            ("combovp", "vp_type_3d", "The 3D", "vp"),
            ("combovp", "vp_type_section", "Each section", "vp"),
            ("note", "", "The list is every viewport type in the project. Blank means "
                         "the type Revit would place by default.", None),
        ],
    },
    {
        "key": "push", "name": "Sheet name push", "icon": "push",
        "blurb": "the sheet name split into sheet parameters",
        "fields": [
            ("check", "push_enabled", "Push the sheet name into parameters", None),
            ("text", "push_separator", "Split the name on", None),
            ("paramrows", "push_params", "Parameters, in order", None),
            ("check", "push_overwrite", "Overwrite a value already there", None),
            ("check", "push_prove", "Read every value back to prove it landed", None),
            ("note", "", "The first piece of the name goes in the first parameter, the "
                         "second in the second, and so on. Spare pieces are reported.", None),
        ],
    },
    {
        "key": "appearance", "name": "Appearance", "icon": "appearance",
        "blurb": "theme and reporting",
        "fields": [
            ("choice", "theme", "Theme", _choice([
                ("auto", "follow Revit's canvas theme"),
                ("dark", "dark"), ("light", "light")])),
            ("choice", "results", "Show the results window", _choice([
                ("needed", "only when something needs a look"),
                ("always", "always"), ("never", "never")])),
            ("check", "remember_size", "Remember the window size", None),
        ],
    },
]


class SettingsWindow(object):
    def __init__(self, doc, settings=None, on_apply=None, owner=None):
        self.doc = doc
        self.values = dict(settings or core.load_settings())
        self.on_apply = on_apply
        self.controls = {}
        self.combos = {}
        self._follow_pairs = []
        self.group_buttons = {}
        self.current = GROUPS[0]["key"]
        self.palette = theme_module.resolve(self.values)
        self.lists = self._read_lists()

        self.window = ui.load_window("CalloutTo3DSettings.xaml")
        ui.apply_theme(self.window, self.palette)
        find = self.window.FindName
        self.find = find

        find("VersionText").Text = u"v{0}".format(core.__version__)
        ui.set_image(find("LogoImage"), "icon.png")
        self.egg = ui.EggWatcher(find("LogoZone"), self.window)
        self.chrome = ui.Chrome(self.window, find("HeaderBar"), find("GripGrid"),
                                find("ShrinkButton"))

        find("CloseButton").Click += self._on_cancel
        find("CancelButton").Click += self._on_cancel
        find("ApplyButton").Click += self._on_apply
        find("ResetButton").Click += self._on_reset
        find("ThemeChip").Click += self._on_theme
        find("FullScreenButton").Click += self._on_full
        self._update_theme_chip()

        self._build_rail()
        self._show_group(self.current)
        ui.set_owner(self.window, owner)

    # ------------------------------------------------------------------
    def _read_lists(self):
        doc = self.doc
        out = {"vft3d": [], "tpl3d": [], "vftsec": [], "tplsec": [], "tplall": [],
               "vp": [], "tb": [], "tbfam": [], "tbmap": [], "params": []}
        if doc is None:
            return out
        try:
            out["vft3d"] = [item["name"] for item in model.view_family_types(doc, "ThreeDimensional")]
            out["vftsec"] = [item["name"] for item in model.view_family_types(doc, "Section")]
            # one walk of the project for both kinds, not two
            template_cache = {}
            out["tpl3d"] = [item["name"] for item in
                            model.view_templates(doc, "3d", template_cache)]
            out["tplall"] = [item["name"] for item in
                             model.view_templates(doc, None, template_cache)]
            out["tplsec"] = [item["name"] for item in
                             model.view_templates(doc, "section", template_cache)]
            out["vp"] = [item["name"] for item in model.viewport_types(doc)]
            blocks = model.title_blocks(doc)
            out["tb"] = [item["name"] for item in blocks]
            out["tbfam"] = sorted(set([item["family"] for item in blocks
                                       if item["family"]]),
                                  key=lambda text: text.lower())
            out["tbmap"] = blocks
            out["params"] = model.sheet_parameters(doc)
        except Exception as err:
            core.log("settings list read failed: {0}".format(err))
        return out

    # ------------------------------------------------------------------
    def _icon(self, key):
        shape = ShapePath()
        try:
            shape.Data = Geometry.Parse(ICONS.get(key, ICONS["views"]))
        except Exception:
            return None
        shape.Width = 17
        shape.Height = 17
        shape.Stretch = Stretch.Uniform
        shape.StrokeThickness = 1.2
        try:
            shape.Stroke = self.window.TryFindResource("BlueBrush")
        except Exception:
            pass
        shape.VerticalAlignment = VerticalAlignment.Center
        return shape

    def _build_rail(self):
        rail = self.find("GroupRail")
        rail.Children.Clear()
        for group in GROUPS:
            button = Button()
            button.Tag = group["key"]
            try:
                button.Style = self.window.TryFindResource("RailButton")
            except Exception:
                pass
            panel = StackPanel()
            panel.Orientation = Orientation.Horizontal
            icon = self._icon(group["icon"])
            if icon is not None:
                panel.Children.Add(icon)
            label = TextBlock()
            label.Text = group["name"]
            label.Margin = Thickness(10, 0, 0, 0)
            label.VerticalAlignment = VerticalAlignment.Center
            panel.Children.Add(label)
            button.Content = panel
            button.Click += self._on_rail
            rail.Children.Add(button)
            self.group_buttons[group["key"]] = button

    def _on_rail(self, sender, args):
        self._collect()
        self._show_group(u"{0}".format(sender.Tag))

    def _mark_rail(self):
        for key, button in self.group_buttons.items():
            try:
                content = button.Content
                brush = self.window.TryFindResource(
                    "BlueBrush" if key == self.current else "TextBrush")
                for child in content.Children:
                    if isinstance(child, TextBlock):
                        child.Foreground = brush
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _row(self, label_text):
        grid = Grid()
        left = ColumnDefinition()
        left.Width = GridLength(300)
        right = ColumnDefinition()
        right.Width = GridLength(1, GridUnitType.Star)
        grid.ColumnDefinitions.Add(left)
        grid.ColumnDefinitions.Add(right)
        grid.Margin = Thickness(0, 5, 0, 5)
        label = TextBlock()
        label.Text = label_text
        label.TextWrapping = TextWrapping.Wrap
        label.VerticalAlignment = VerticalAlignment.Center
        label.Margin = Thickness(0, 0, 12, 0)
        try:
            label.Foreground = self.window.TryFindResource("TextBrush")
        except Exception:
            pass
        Grid.SetColumn(label, 0)
        grid.Children.Add(label)
        return grid

    def _text_box(self, value, width=None):
        box = TextBox()
        box.Text = u"{0}".format(value)
        try:
            box.Style = self.window.TryFindResource("ThemedTextBox")
        except Exception:
            pass
        if width:
            box.Width = width
            box.HorizontalAlignment = HorizontalAlignment.Left
        return box

    def _combo(self, values, selected, blank=None):
        combo = ComboBox()
        try:
            combo.Style = self.window.TryFindResource("ThemedComboBox")
        except Exception:
            pass
        ui.fill_combo(combo, values, selected if selected else blank, blank)
        return combo

    def _show_group(self, key):
        self.current = key
        group = None
        for candidate in GROUPS:
            if candidate["key"] == key:
                group = candidate
                break
        if group is None:
            return
        self.find("GroupTitle").Text = group["name"]
        self.find("GroupBlurb").Text = group["blurb"]
        host = self.find("GroupHost")
        host.Children.Clear()
        self.controls = {}
        self.combos = {}
        self._follow_pairs = []

        for kind, setting_key, label, extra in group["fields"]:
            if kind == "note":
                block = TextBlock()
                block.Text = label
                block.TextWrapping = TextWrapping.Wrap
                block.Margin = Thickness(0, 12, 0, 4)
                block.FontSize = 11.5
                try:
                    block.Foreground = self.window.TryFindResource("MutedBrush")
                except Exception:
                    pass
                host.Children.Add(block)
                continue

            if kind == "check":
                box = CheckBox()
                box.Content = label
                box.Margin = Thickness(0, 8, 0, 8)
                box.IsChecked = core.get_bool(self.values, setting_key)
                if setting_key == "template_list_all":
                    box.Click += self._on_list_all
                try:
                    box.Style = self.window.TryFindResource("ThemedCheckBox")
                except Exception:
                    pass
                host.Children.Add(box)
                self.controls[setting_key] = ("check", box)
                continue

            row = self._row(label)
            control = None
            if kind in ("text",):
                control = self._text_box(self.values.get(setting_key, ""))
                self.controls[setting_key] = ("text", control)
            elif kind in ("int", "float"):
                control = self._text_box(self.values.get(setting_key, ""), 120)
                self.controls[setting_key] = (kind, control)
            elif kind == "choice":
                labels = [text for value, text in extra]
                current = self.values.get(setting_key, "")
                shown = labels[0]
                for value, text in extra:
                    if value == current:
                        shown = text
                control = self._combo(labels, shown)
                self.controls[setting_key] = ("choice", control, extra)
            elif kind in ("combo3d", "combosec", "combovp"):
                source = list(self.lists.get(extra, []))
                if extra in ("tpl3d", "tplsec") and \
                        core.get_bool(self.values, "template_list_all", False):
                    for name in self.lists.get("tplall", []):
                        if name not in source:
                            source.append(name)
                    source.sort(key=lambda text: text.lower())
                blank = BLANK_VP if kind == "combovp" else BLANK
                control = self._combo(source, self.values.get(setting_key, ""), blank)
                self.controls[setting_key] = ("combo", control, blank)
                self.combos[setting_key] = control
                if setting_key in ("3d_view_family_type", "sec_view_family_type"):
                    self._follow_pairs.append(
                        (control, "3d" if setting_key.startswith("3d") else "section"))
            elif kind == "paramrows":
                control = self._param_rows(setting_key)
            elif kind == "sizemap":
                control = self._size_map(setting_key)

            if control is not None:
                Grid.SetColumn(control, 1)
                row.Children.Add(control)
            host.Children.Add(row)

        self._wire_template_following()
        self._mark_rail()

    def _on_list_all(self, sender, args):
        """Widening or narrowing the template lists changes what the combos
        hold, so the group is collected and drawn again."""
        try:
            self._collect()
            self._show_group(self.current)
        except Exception as err:
            core.log(u"template list could not be rebuilt: {0}".format(err))

    def _wire_template_following(self):
        """Hook each view family type combo to the template combo of its kind.

        Done once the group is built, because the template combo does not
        exist yet while the type combo is being made - which is why the first
        attempt at this, done inline, never fired.
        """
        for type_combo, kind in self._follow_pairs:
            template_combo = self.combos.get("3d_template" if kind == "3d" else "sec_template")
            if template_combo is None:
                continue

            def make(source, target, which):
                def handler(sender, args):
                    if not core.get_bool(self.values, "template_follows_type", True):
                        return
                    picked = ui.combo_value(source, BLANK) or ""
                    try:
                        name = model.default_template_name(self.doc, picked, which)
                    except Exception:
                        name = ""
                    if not name:
                        return
                    items = [u"{0}".format(item) for item in target.Items]
                    if name not in items:
                        target.Items.Add(name)
                        items.append(name)
                    target.SelectedIndex = items.index(name)
                return handler

            try:
                type_combo.SelectionChanged += make(type_combo, template_combo, kind)
            except Exception as err:
                core.log(u"template follow could not be wired: {0}".format(err))
        del self._follow_pairs[:]

    def _param_rows(self, setting_key):
        """One row per piece of the sheet name, each a dropdown of the sheet
        parameters actually in the project, with the position it fills written
        beside it.  Typing pipe separated names into a box was asking the user
        to know both the separator and the spelling."""
        outer = StackPanel()
        rows = StackPanel()
        outer.Children.Add(rows)
        chosen = [name for name in
                  (self.values.get(setting_key, "") or "").split("|") if name.strip()]
        available = self.lists.get("params", [])
        combos = []

        def draw():
            rows.Children.Clear()
            del combos[:]
            for index, name in enumerate(chosen):
                line = Grid()
                for width in (GridLength(34), GridLength(1, GridUnitType.Star),
                              GridLength(30)):
                    column = ColumnDefinition()
                    column.Width = width
                    line.ColumnDefinitions.Add(column)
                line.Margin = Thickness(0, 3, 0, 3)

                label = TextBlock()
                label.Text = u"{0}.".format(index + 1)
                label.VerticalAlignment = VerticalAlignment.Center
                try:
                    label.Foreground = self.window.TryFindResource("MutedBrush")
                except Exception:
                    pass
                Grid.SetColumn(label, 0)
                line.Children.Add(label)

                options = list(available)
                if name.strip() and name.strip() not in options:
                    # a parameter saved against another project, kept rather
                    # than dropped silently
                    options.insert(0, name.strip())
                combo = self._combo(options, name.strip())
                Grid.SetColumn(combo, 1)
                line.Children.Add(combo)
                combos.append(combo)

                remove = Button()
                remove.Content = u"\u00d7"
                remove.Width = 26
                try:
                    remove.Style = self.window.TryFindResource("GhostButton")
                except Exception:
                    pass

                def make_remove(position):
                    def handler(sender, args):
                        read_back()
                        if 0 <= position < len(chosen):
                            del chosen[position]
                        draw()
                    return handler

                remove.Click += make_remove(index)
                Grid.SetColumn(remove, 2)
                line.Children.Add(remove)
                rows.Children.Add(line)

            if not chosen:
                empty = TextBlock()
                empty.Text = ("nothing is being pushed - add a parameter below"
                              if available else
                              "no writable text parameters were found on the sheets "
                              "in this project")
                empty.Margin = Thickness(0, 4, 0, 4)
                empty.FontSize = 11.5
                try:
                    empty.Foreground = self.window.TryFindResource("MutedBrush")
                except Exception:
                    pass
                rows.Children.Add(empty)

        def read_back():
            for index, combo in enumerate(combos):
                if index < len(chosen):
                    chosen[index] = ui.combo_value(combo) or chosen[index]

        add = Button()
        add.Content = "Add a parameter"
        add.Margin = Thickness(0, 6, 0, 0)
        add.HorizontalAlignment = HorizontalAlignment.Left
        try:
            add.Style = self.window.TryFindResource("GhostButton")
        except Exception:
            pass

        def on_add(sender, args):
            read_back()
            chosen.append(available[0] if available else "")
            draw()

        add.Click += on_add
        outer.Children.Add(add)
        draw()
        self.controls[setting_key] = ("paramrows", combos, chosen, read_back)
        return outer


    def _size_map(self, setting_key):
        panel = StackPanel()
        mapping = core.get_map(self.values, setting_key)
        sizes = [size.strip() for size in
                 (self.values.get("sheet_sizes") or "A1").split("|") if size.strip()]
        combos = {}
        for size in sizes:
            line = Grid()
            label_column = ColumnDefinition()
            label_column.Width = GridLength(46)
            family_column = ColumnDefinition()
            family_column.Width = GridLength(1, GridUnitType.Star)
            type_column = ColumnDefinition()
            type_column.Width = GridLength(1, GridUnitType.Star)
            line.ColumnDefinitions.Add(label_column)
            line.ColumnDefinitions.Add(family_column)
            line.ColumnDefinitions.Add(type_column)
            line.Margin = Thickness(0, 3, 0, 3)
            label = TextBlock()
            label.Text = size
            label.VerticalAlignment = VerticalAlignment.Center
            try:
                label.Foreground = self.window.TryFindResource("MutedBrush")
            except Exception:
                pass
            Grid.SetColumn(label, 0)
            line.Children.Add(label)
            saved = mapping.get(size, "")
            saved_family, saved_type = "", ""
            if ":" in saved:
                saved_family, saved_type = [piece.strip() for piece in saved.split(":", 1)]
            elif saved:
                saved_type = saved.strip()

            families = list(self.lists.get("tbfam", []))
            family_combo = self._combo(families, saved_family, "(any family)")
            type_combo = self._combo(self._types_in(saved_family), saved_type,
                                     "(match the size in the name)")
            Grid.SetColumn(family_combo, 1)
            Grid.SetColumn(type_combo, 2)
            line.Children.Add(family_combo)
            line.Children.Add(type_combo)
            panel.Children.Add(line)

            def make_family_changed(family_box, type_box):
                def handler(sender, args):
                    chosen = ui.combo_value(family_box) or ""
                    keep = ui.combo_value(type_box) or ""
                    ui.fill_combo(type_box, self._types_in(chosen), keep,
                                  "(match the size in the name)")
                return handler

            try:
                family_combo.SelectionChanged += make_family_changed(family_combo, type_combo)
            except Exception:
                pass
            combos[size] = (family_combo, type_combo)
        self.controls[setting_key] = ("sizemap", combos)
        return panel

    def _types_in(self, family):
        """The title block types in one family, or all of them when no family
        has been picked."""
        family = (family or "").strip().lower()
        names = []
        for block in self.lists.get("tbmap", []):
            if family and (block.get("family") or "").strip().lower() != family:
                continue
            name = block.get("type_name") or ""
            if name and name not in names:
                names.append(name)
        return sorted(names, key=lambda text: text.lower())

    # ------------------------------------------------------------------
    def _collect(self):
        """Read the shown group back into the values.  Called on every group
        change so a switch does not throw the edits away."""
        for key, record in self.controls.items():
            kind = record[0]
            control = record[1]
            try:
                if kind == "check":
                    self.values[key] = "1" if control.IsChecked else "0"
                elif kind == "text":
                    self.values[key] = control.Text or ""
                elif kind == "int":
                    self.values[key] = u"{0}".format(core.get_int(
                        {key: control.Text}, key, core.get_int(core.DEFAULTS, key, 0)))
                elif kind == "float":
                    self.values[key] = u"{0}".format(core.get_float(
                        {key: control.Text}, key, core.get_float(core.DEFAULTS, key, 0.0)))
                elif kind == "choice":
                    pairs = record[2]
                    shown = ui.combo_value(control)
                    for value, text in pairs:
                        if text == shown:
                            self.values[key] = value
                            break
                elif kind == "combo":
                    self.values[key] = ui.combo_value(control, record[2])
                elif kind == "paramrows":
                    record[3]()                      # read the combos back first
                    names = [name.strip() for name in record[2] if name and name.strip()]
                    self.values[key] = "|".join(names)
                elif kind == "sizemap":
                    mapping = {}
                    for size, pair in control.items():
                        family_box, type_box = pair
                        family = ui.combo_value(family_box, "(any family)") or ""
                        type_name = ui.combo_value(
                            type_box, "(match the size in the name)") or ""
                        if family and type_name:
                            mapping[size] = u"{0}: {1}".format(family, type_name)
                        elif type_name:
                            mapping[size] = type_name
                        elif family:
                            # a family on its own still narrows it down
                            mapping[size] = u"{0}:".format(family)
                    core.set_map(self.values, key, mapping)
            except Exception as err:
                core.log("settings read of {0} failed: {1}".format(key, err))

    # ------------------------------------------------------------------
    def _on_theme(self, sender, args):
        order = ["auto", "dark", "light"]
        current = str(self.values.get("theme", "auto")).lower()
        index = order.index(current) if current in order else 0
        self.values["theme"] = order[(index + 1) % len(order)]
        self.palette = theme_module.resolve(self.values)
        ui.apply_theme(self.window, self.palette)
        self._update_theme_chip()
        self._show_group(self.current)

    def _update_theme_chip(self):
        wanted = str(self.values.get("theme", "auto")).lower()
        label = {"auto": "Auto", "dark": "Dark", "light": "Light"}.get(wanted, "Auto")
        if wanted == "auto":
            label = u"Auto ({0})".format(self.palette)
        try:
            self.find("ThemeChip").Content = label
        except Exception:
            pass

    def _on_full(self, sender, args):
        self.chrome.toggle_full_screen()

    def _on_reset(self, sender, args):
        if not ui.prompt("Back to defaults",
                         ["Every setting for Callout to 3D goes back to how it shipped.",
                          "", "Nothing in the model changes."],
                         self.palette, confirm=True, owner=self.window):
            return
        self.values = dict(core.DEFAULTS)
        self.palette = theme_module.resolve(self.values)
        ui.apply_theme(self.window, self.palette)
        self._update_theme_chip()
        self._show_group(self.current)
        self.find("StatusText").Text = "back to the defaults, not yet applied"

    def _on_cancel(self, sender, args):
        try:
            self.window.Close()
        except Exception:
            pass

    def _on_apply(self, sender, args):
        self._collect()
        if core.save_settings(self.values):
            self.find("StatusText").Text = u"saved to {0}".format(core.settings_path())
            if self.on_apply:
                try:
                    self.on_apply(dict(self.values))
                except Exception as err:
                    core.log("settings callback failed: {0}".format(err))
            try:
                self.window.Close()
            except Exception:
                pass
        else:
            self.find("StatusText").Text = "the settings file could not be written"

    def show(self, modal=True):
        if modal:
            self.window.ShowDialog()
        else:
            self.window.Show()
