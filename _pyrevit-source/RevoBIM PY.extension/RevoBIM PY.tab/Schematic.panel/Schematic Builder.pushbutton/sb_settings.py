# -*- coding: utf-8 -*-
"""Schematic Builder - the Settings dialog (gear in the main header)."""
import sb_clr  # noqa: F401

import traceback

import sb_ui
import theme
from sb_logic import (as_text, to_int, to_float, TABS, SHEETS, LEVEL_LABEL_FORMATS,
                      SETTINGS_FILE, level_rows, abbreviate, encode_rows)

SET_TABS = ["General", "Views", "Rooms", "Standards", "Levels", "Spacing", "Params", "Lv"]

ROOM_SOURCES = [
    (u"room", u"the room the element sits in"),
    (u"element", u"a parameter on the element itself"),
]

from System.Windows import HorizontalAlignment, Visibility  # noqa: E402

RESULT_OPTIONS = [
    (u"issues", u"only if something needs a look"),
    (u"always", u"always"),
    (u"never", u"never"),
]


class SettingsDialog(object):
    def __init__(self, owner, settings, model, element_params=None):
        self.element_params = element_params or []
        self.settings = dict(settings)
        self.model = model
        self.result = None
        self.level_editors = []      # [(checkbox, name, abbr textbox)]

        self.window, self.find, self.chrome = sb_ui.open_window("SbSettings.xaml",
                                                                sb_ui.palette_for(settings), owner)
        self.find("TxtSettingsPath").Text = SETTINGS_FILE
        for key in SET_TABS:
            self.find("SetTab" + key).Click += self.make_tab(key)
        self.show_tab("General")

        self.find("BtnApply").Click += self.on_apply
        self.find("BtnCancel").Click += self.on_cancel
        self.find("BtnLevelsAll").Click += self.make_tick(True)
        self.find("BtnLevelsNone").Click += self.make_tick(False)
        self.find("BtnLevelsAuto").Click += self.on_auto
        self.find("CmbTheme").SelectionChanged += self.on_theme
        self.load()

    # -- load ---------------------------------------------------------------

    def load(self):
        s = self.settings
        find = self.find
        find("TxtScale").Text = as_text(s.get("scale", u"1"))
        find("TxtMargin").Text = as_text(s.get("margin_mm", u"20"))
        self.fill_combo("CmbSheet", sorted(SHEETS.keys()), s.get("sheet_size", u"A1"))
        self.fill_combo("CmbTheme", list(theme.MODES), s.get("theme", u"follow"))
        self.fill_combo("CmbResults", [o[1] for o in RESULT_OPTIONS],
                        dict(RESULT_OPTIONS).get(s.get("show_results", u"issues"), RESULT_OPTIONS[0][1]))
        find("ChkOpenView").IsChecked = s.get("open_view", u"1") != u"0"
        self.fill_combo("CmbRoomSource", [o[1] for o in ROOM_SOURCES],
                        dict(ROOM_SOURCES).get(s.get("room_source", u"room"), ROOM_SOURCES[0][1]))
        self.fill_combo("CmbRoomParam", self.model.get("room_params", []),
                        s.get("room_name_param", u"Name"), search=True)
        self.fill_combo("CmbRoomElementParam", self.element_params,
                        s.get("room_element_param", u""), search=True)
        find("CmbRoomSource").SelectionChanged += self.on_room_source
        self.on_room_source(None, None)

        for key, tab_label, prefix, built in TABS:
            find("TxtName" + key.capitalize()).Text = as_text(s.get("name_" + key, prefix))

        find("TxtTransfer").Text = as_text(s.get("transfer", u"")).replace(u"|", u"\n")
        find("TxtLinkParam").Text = as_text(s.get("link_param", u"BGL_Linked Element ID"))

        line_styles = sorted(self.model.get("line_styles", {}).keys(), key=lambda n: n.lower())
        text_types = sorted(self.model.get("text_types", {}).keys(), key=lambda n: n.lower())
        self.fill_combo("CmbLevelLine", line_styles, s.get("level_line_style") or self.guess(line_styles, u"level"))
        self.fill_combo("CmbRoomLine", line_styles, s.get("room_line_style") or self.guess(line_styles, u"room"))
        self.fill_combo("CmbLevelText", text_types, s.get("level_text_type") or (text_types[0] if text_types else u""))
        self.fill_combo("CmbRoomText", text_types, s.get("room_text_type") or (text_types[0] if text_types else u""))
        self.fill_combo("CmbLevelLabel", LEVEL_LABEL_FORMATS, s.get("level_label", u"{name}"))

        find("ChkLvPanelsOnly").IsChecked = s.get("lv_panels_only", u"1") != u"0"
        self.fill_combo("CmbCircuitLine", [u"(default)"] + line_styles,
                        s.get("lv_circuit_line_style") or u"(default)")
        find("TxtLvGap").Text = as_text(s.get("lv_line_gap_mm", u"18"))
        find("TxtLvLevelClear").Text = as_text(s.get("lv_level_clear_mm", u"30"))
        find("TxtLvJog").Text = as_text(s.get("lv_jog_mm", u"6"))
        find("TxtLvJogStep").Text = as_text(s.get("lv_jog_step_mm", u"4"))
        find("TxtLvLaneClear").Text = as_text(s.get("lv_lane_clear_mm", u"4"))
        find("TxtLvRowGap").Text = as_text(s.get("lv_row_gap_mm", u"28"))
        find("ChkLvStretchMain").IsChecked = s.get("lv_stretch_main", u"1") != u"0"
        find("TxtLvStretchOver").Text = as_text(s.get("lv_stretch_over_mm", u"9"))
        find("TxtRoomOffset").Text = as_text(s.get("room_offset_mm", u"10"))
        find("TxtRoomTextDx").Text = as_text(s.get("room_text_dx_mm", u"3"))
        find("TxtRoomTextDy").Text = as_text(s.get("room_text_dy_mm", u"3"))
        find("TxtItemGap").Text = as_text(s.get("item_gap_mm", u"5"))
        find("TxtRoomGap").Text = as_text(s.get("room_gap_mm", u"15"))
        find("TxtLevelClear").Text = as_text(s.get("level_clear_mm", u"8"))
        find("TxtTextGap").Text = as_text(s.get("text_gap_mm", u"2"))
        self.fill_levels()

    def make_tab(self, key):
        def handler(sender, args):
            try:
                self.show_tab(key)
            except Exception:
                pass
        return handler

    def show_tab(self, key):
        for name in SET_TABS:
            self.find("SetPage" + name).Visibility = (
                Visibility.Visible if name == key else Visibility.Collapsed)
            self.find("SetTab" + name).Tag = u"on" if name == key else u""

    def room_source(self):
        chosen = sb_ui.combo_text(self.find("CmbRoomSource"))
        for key, label in ROOM_SOURCES:
            if label == chosen:
                return key
        return u"room"

    def on_room_source(self, sender, args):
        try:
            from_element = self.room_source() == u"element"
            self.find("CmbRoomParam").IsEnabled = not from_element
            self.find("CmbRoomElementParam").IsEnabled = from_element
            if from_element:
                if self.element_params:
                    hint = u"{0} parameter(s) read off the paired equipment".format(len(self.element_params))
                else:
                    hint = u"no equipment paired yet - type the parameter name in"
            else:
                hint = u"equipment with no room is drawn without a room box"
            self.find("TxtRoomHint").Text = hint
        except Exception:
            pass

    def guess(self, names, word):
        for name in names:
            if word in name.lower():
                return name
        return names[0] if names else u""

    def fill_combo(self, name, items, selected, search=False):
        box = self.find(name)
        box.Items.Clear()
        for item in items:
            box.Items.Add(as_text(item))
        sb_ui.select_text(box, selected)
        if search:
            sb_ui.searchable(box, items)
        return box

    def fill_levels(self):
        lst = self.find("LstLevels")
        lst.Items.Clear()
        self.level_editors = []
        levels = self.model.get("levels", [])
        rows = level_rows(self.settings, [l["name"] for l in levels])
        elev_by_name = {}
        for level in levels:
            elev_by_name[level["name"]] = level.get("elev_mm", 0.0)
        for name, abbr, include in reversed(rows):      # top level first, as in the project browser
            line = sb_ui.grid([sb_ui.pixels(30), sb_ui.star(1), sb_ui.pixels(110), sb_ui.pixels(140)])
            tick = sb_ui.check(u"", include)
            sb_ui.place(line, tick, 0)
            sb_ui.place(line, sb_ui.label(name), 1)
            elev = sb_ui.label(u"{0:.0f} mm".format(elev_by_name.get(name, 0.0)), dim=True)
            elev.HorizontalAlignment = HorizontalAlignment.Left
            sb_ui.place(line, elev, 2)
            editor = sb_ui.field(abbr, u"abbr", margin=(0, 2, 8, 2))
            sb_ui.place(line, editor, 3)
            lst.Items.Add(sb_ui.list_item(line))
            self.level_editors.append((tick, name, editor))
        if not levels:
            lst.Items.Add(sb_ui.list_item(sb_ui.label(u"No levels found in this model.", dim=True)))

    # -- events -------------------------------------------------------------

    def make_tick(self, value):
        def handler(sender, args):
            for tick, name, editor in self.level_editors:
                tick.IsChecked = bool(value)
        return handler

    def on_auto(self, sender, args):
        for tick, name, editor in self.level_editors:
            editor.Text = abbreviate(name)

    def on_theme(self, sender, args):
        try:
            sb_ui.apply_palette(self.window, theme.resolve(sb_ui.combo_text(self.find("CmbTheme")),
                                                           sb_ui.canvas_theme()))
        except Exception:
            pass

    def on_cancel(self, sender, args):
        self.window.Close()

    def on_apply(self, sender, args):
        try:
            self.result = self.harvest()
            self.window.Close()
        except Exception:
            self.find("TxtSettingsPath").Text = traceback.format_exc().strip().splitlines()[-1]

    def harvest(self):
        s = dict(self.settings)
        find = self.find
        s["scale"] = as_text(max(1, to_int(find("TxtScale").Text, 1)))
        s["margin_mm"] = as_text(max(0.0, to_float(find("TxtMargin").Text, 20.0)))
        s["sheet_size"] = sb_ui.combo_text(find("CmbSheet")) or u"A1"
        s["theme"] = sb_ui.combo_text(find("CmbTheme")) or u"follow"
        chosen = sb_ui.combo_text(find("CmbResults"))
        s["show_results"] = u"issues"
        for key, label in RESULT_OPTIONS:
            if label == chosen:
                s["show_results"] = key
        s["open_view"] = u"1" if find("ChkOpenView").IsChecked else u"0"
        s["room_source"] = self.room_source()
        s["room_name_param"] = sb_ui.combo_text(find("CmbRoomParam")) or u"Name"
        s["room_element_param"] = sb_ui.combo_text(find("CmbRoomElementParam"))
        for key, tab_label, prefix, built in TABS:
            s["name_" + key] = as_text(find("TxtName" + key.capitalize()).Text).strip() or prefix
        s["link_param"] = as_text(find("TxtLinkParam").Text).strip()
        s["transfer"] = u"|".join([line.strip() for line in
                                  as_text(find("TxtTransfer").Text).replace(u"\r", u"").split(u"\n")
                                  if line.strip()])
        s["level_line_style"] = sb_ui.combo_text(find("CmbLevelLine"))
        s["room_line_style"] = sb_ui.combo_text(find("CmbRoomLine"))
        s["level_text_type"] = sb_ui.combo_text(find("CmbLevelText"))
        s["room_text_type"] = sb_ui.combo_text(find("CmbRoomText"))
        s["level_label"] = sb_ui.combo_text(find("CmbLevelLabel")) or u"{name}"
        s["lv_panels_only"] = u"1" if find("ChkLvPanelsOnly").IsChecked else u"0"
        circuit = sb_ui.combo_text(find("CmbCircuitLine"))
        s["lv_circuit_line_style"] = u"" if circuit.startswith(u"(") else circuit
        s["lv_line_gap_mm"] = as_text(to_float(find("TxtLvGap").Text, 18.0))
        s["lv_level_clear_mm"] = as_text(to_float(find("TxtLvLevelClear").Text, 30.0))
        s["lv_jog_mm"] = as_text(to_float(find("TxtLvJog").Text, 6.0))
        s["lv_jog_step_mm"] = as_text(to_float(find("TxtLvJogStep").Text, 4.0))
        s["lv_lane_clear_mm"] = as_text(to_float(find("TxtLvLaneClear").Text, 4.0))
        s["lv_row_gap_mm"] = as_text(to_float(find("TxtLvRowGap").Text, 28.0))
        s["lv_stretch_main"] = u"1" if find("ChkLvStretchMain").IsChecked else u"0"
        s["lv_stretch_over_mm"] = as_text(to_float(find("TxtLvStretchOver").Text, 9.0))
        s["room_offset_mm"] = as_text(to_float(find("TxtRoomOffset").Text, 10.0))
        s["room_text_dx_mm"] = as_text(to_float(find("TxtRoomTextDx").Text, 3.0))
        s["room_text_dy_mm"] = as_text(to_float(find("TxtRoomTextDy").Text, 3.0))
        s["item_gap_mm"] = as_text(to_float(find("TxtItemGap").Text, 5.0))
        s["room_gap_mm"] = as_text(to_float(find("TxtRoomGap").Text, 15.0))
        s["level_clear_mm"] = as_text(to_float(find("TxtLevelClear").Text, 8.0))
        s["text_gap_mm"] = as_text(to_float(find("TxtTextGap").Text, 2.0))
        rows = []
        for tick, name, editor in self.level_editors:
            abbr = as_text(editor.Text).strip() or abbreviate(name)
            rows.append([name, abbr, u"1" if tick.IsChecked else u"0"])
        s["levels"] = encode_rows(rows)
        return s

    def show(self):
        self.window.ShowDialog()
        return self.result
