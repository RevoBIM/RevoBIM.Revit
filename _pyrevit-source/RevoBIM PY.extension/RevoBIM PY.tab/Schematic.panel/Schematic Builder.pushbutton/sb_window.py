# -*- coding: utf-8 -*-
"""Schematic Builder - the main window.

Modeless and owned by Revit's main window. Every write goes out through the
ExternalEvent created in command context by script.py.
"""
import sb_clr  # noqa: F401

import traceback

import sb_ui
import sb_model
import theme
from sb_logic import (as_text, TABS, TAB_KEYS, decode_rows, encode_rows, save_settings,
                      next_view_name, level_rows, row_families, pair_text, pairs_text,
                      parse_transfer, transfer_summary, row_transfer_mode, decode_templates,
                      ROW_WIDTH)
from sb_core import write_error
from sb_settings import SettingsDialog
from sb_equipment import EquipmentDialog
from sb_married import MarriedTab

from System.Windows import Visibility, HorizontalAlignment, Thickness  # noqa: E402

BROWSER_ROWS = 3


def guard(func):
    """A UI handler must never throw: an unhandled exception is what pops
    pyRevit's blank output window and leaves the tool looking dead."""
    def wrapper(self, sender, args):
        try:
            return func(self, sender, args)
        except Exception:
            try:
                self.report_error(traceback.format_exc())
            except Exception:
                pass
    return wrapper


class MainWindow(object):
    def __init__(self, uidoc, settings, model, handler, ext_event):
        self.uidoc = uidoc
        self.doc = uidoc.Document
        self.settings = settings
        self.model = model
        self.handler = handler
        self.ext_event = ext_event
        self.busy = False
        self.filling_panels = False
        self.filling_browser = False
        self.tab = settings.get("active_tab", "ventilation")
        if self.tab not in TAB_KEYS + ["married"]:
            self.tab = "ventilation"
        self.browser_editors = {}     # tab -> [(param combo, value combo)]

        self.window, self.find, self.chrome = sb_ui.open_window(
            "SchematicBuilder.xaml", sb_ui.palette_for(settings), modal=False)
        window = self.window

        self.txt_status = self.find("TxtStatus")
        self.btn_create = self.find("BtnCreate")
        self.btn_theme = self.find("BtnTheme")

        self.find("BtnSettings").Click += self.on_settings
        self.find("BtnRefresh").Click += self.on_refresh
        self.btn_theme.Click += self.on_theme
        self.find("BtnEquipment").Click += self.make_equipment("ventilation")
        self.find("BtnEquipmentLv").Click += self.make_equipment("lv")
        self.find("BtnReadPanels").Click += self.on_read_panels
        self.find("ChkPanelsOnly").Click += self.on_panels_only
        self.find("CmbMainPanel").SelectionChanged += self.on_main_panel
        self.btn_create.Click += self.on_create
        window.Closed += self.on_closed
        for key in TAB_KEYS:
            self.find("Tab" + key.capitalize()).Click += self.make_tab(key)
        self.find("TabMarried").Click += self.make_tab("married")

        self.build_browser_rows()
        self.fill_equipment()
        self.fill_view_info()
        self.fill_panels()
        self.married = MarriedTab(self)
        self.show_tab(self.tab)
        self.update_theme_chip()

    # -- tabs ---------------------------------------------------------------

    def make_tab(self, key):
        def handler(sender, args):
            try:
                self.harvest_browser()
                self.show_tab(key)
                self.settings["active_tab"] = key
                save_settings(self.settings)
            except Exception:
                self.report_error(traceback.format_exc())
        return handler

    def show_tab(self, key):
        self.tab = key
        for tab_key, tab_label, prefix, built in TABS:
            page = self.find("Page" + tab_key.capitalize())
            page.Visibility = Visibility.Visible if tab_key == key else Visibility.Collapsed
            self.find("Tab" + tab_key.capitalize()).Tag = u"on" if tab_key == key else u""
            if not built:
                self.find("TxtPlaceholder" + tab_key.capitalize()).Text = (
                    u"{0} Schematic is a placeholder for now.\n\n"
                    u"The browser grouping above is remembered, and Create will make the named "
                    u"drafting view once this schematic type has been developed.".format(tab_label))
        self.find("PageMarried").Visibility = Visibility.Visible if key == "married" else Visibility.Collapsed
        self.find("TabMarried").Tag = u"on" if key == "married" else u""
        if key == "married":
            self.btn_create.IsEnabled = not self.busy
            self.btn_create.Content = u"Run template on ticked"
            self.set_status(u"Tick the married detail items, pick or build a template, then run it.")
            return
        built = dict([(t[0], t[3]) for t in TABS])[key]
        self.btn_create.IsEnabled = built and not self.busy
        self.btn_create.Content = u"Create" if built else u"Create (not built yet)"
        self.set_status(u"Ready." if built else u"This schematic type is a placeholder.")

    # -- browser grouping rows ------------------------------------------------

    def build_browser_rows(self):
        self.filling_browser = True
        names = self.model.get("view_params", [])
        values = self.model.get("view_values", {})
        for key in TAB_KEYS:
            panel = self.find("Browser" + key.capitalize())
            panel.Children.Clear()
            editors = []
            saved = decode_rows(self.settings.get("browser_" + key, u""), 2)
            while len(saved) < BROWSER_ROWS:
                saved.append([u"", u""])
            for index in range(BROWSER_ROWS):
                line = sb_ui.grid([sb_ui.pixels(110), sb_ui.pixels(300), sb_ui.pixels(80), sb_ui.star(1)])
                line.Margin = Thickness(0, 2, 0, 2)
                sb_ui.place(line, sb_ui.label(u"Parameter {0}".format(index + 1)), 0)
                param_combo = sb_ui.combo([u"(none)"] + list(names), saved[index][0] or u"(none)",
                                          placeholder=u"view parameter", margin=(0, 0, 10, 0))
                sb_ui.place(line, param_combo, 1)
                sb_ui.place(line, sb_ui.label(u"Value", dim=True), 2)
                value_combo = sb_ui.combo([], saved[index][1], placeholder=u"pick a value already used, or type one",
                                          editable=True, margin=(0, 0, 0, 0))
                sb_ui.place(line, value_combo, 3)
                self.fill_values(value_combo, saved[index][0], values, saved[index][1])
                param_combo.SelectionChanged += self.make_param_changed(value_combo)
                panel.Children.Add(line)
                editors.append((param_combo, value_combo))
            self.browser_editors[key] = editors
        self.filling_browser = False

    def fill_values(self, value_combo, param_name, values, keep):
        sb_ui.refill_searchable(value_combo, values.get(param_name, []), keep)

    def make_param_changed(self, value_combo):
        def handler(sender, args):
            if self.filling_browser:
                return
            try:
                name = sb_ui.combo_text(sender)
                current = sb_ui.combo_text(value_combo)
                self.fill_values(value_combo, name, self.model.get("view_values", {}), current)
            except Exception:
                pass
        return handler

    def harvest_browser(self):
        for key in self.browser_editors:
            rows = []
            for param_combo, value_combo in self.browser_editors[key]:
                name = sb_ui.combo_text(param_combo)
                if name.startswith(u"("):
                    name = u""
                rows.append([name, sb_ui.combo_text(value_combo)])
            self.settings["browser_" + key] = encode_rows(rows)

    # -- equipment ------------------------------------------------------------

    BUILT = ("ventilation", "lv")

    def suffix(self, tab):
        return u"" if tab == "ventilation" else tab.capitalize()

    def equipment_rows(self, tab="ventilation"):
        return decode_rows(self.settings.get("equipment_" + tab, u""), ROW_WIDTH)

    def shared_pairs(self):
        return parse_transfer(self.settings.get("transfer", u""))

    def fill_equipment(self):
        for tab in self.BUILT:
            self.fill_equipment_for(tab)

    def fill_equipment_for(self, tab):
        lst = self.find("LstEquipment" + self.suffix(tab))
        lst.Items.Clear()
        counts = {}
        for row in self.model.get("families", []):
            counts[(row["family"], row["type"])] = row["count"]
        loaded = set([(r["family"], r["type"]) for r in self.model.get("details", [])])
        rows = self.equipment_rows(tab)
        shared = len(self.shared_pairs())
        total = 0
        for row in rows:
            line = sb_ui.grid([sb_ui.star(1.0), sb_ui.star(1.5), sb_ui.star(1.5),
                               sb_ui.pixels(130), sb_ui.pixels(60)])
            line.MinHeight = 26
            name = sb_ui.label(row[0] or u"(unnamed)", margin=(0, 0, 6, 0))
            sb_ui.colour(name, "OrangeBrush")
            sb_ui.place(line, name, 0)
            pairs = row_families(row)
            families = sb_ui.label(pairs_text(pairs), margin=(0, 0, 6, 0))
            if len(pairs) > 1:
                sb_ui.tooltip(families, u"\n".join([pair_text(f, t) for f, t in pairs]))
            missing = [pair_text(f, t) for f, t in pairs if counts.get((f, t), 0) == 0]
            if missing:
                sb_ui.colour(families, "RedBrush")
                sb_ui.tooltip(families, u"No placed instances of:\n" + u"\n".join(missing))
            sb_ui.place(line, families, 1)
            detail = sb_ui.label(pair_text(row[3], row[4]), margin=(0, 0, 6, 0))
            if (row[3], row[4]) not in loaded:
                sb_ui.colour(detail, "RedBrush")
                sb_ui.tooltip(detail, u"This detail item is not loaded in the model any more.")
            sb_ui.place(line, detail, 2)
            mapping = sb_ui.label(transfer_summary(row, shared, decode_templates(
                self.settings.get("templates", u""))), dim=True, margin=(0, 0, 6, 0))
            if row_transfer_mode(row) == "none":
                sb_ui.tooltip(mapping, u"No parameters are written onto this equipment's detail items.")
            sb_ui.place(line, mapping, 3)
            count = 0
            for family, type_name in pairs:
                count += counts.get((family, type_name), 0)
            total += count
            qty = sb_ui.label(as_text(count), dim=True)
            if count == 0:
                sb_ui.colour(qty, "RedBrush")
            qty.HorizontalAlignment = HorizontalAlignment.Right
            sb_ui.place(line, qty, 4)
            lst.Items.Add(sb_ui.list_item(line))
        families_used = 0
        for row in rows:
            families_used += len(row_families(row))
        self.find("TxtEquipmentInfo" + self.suffix(tab)).Text = (
            u"{0} equipment type(s), {1} family selection(s)  |  {2} model element(s) will be drawn".format(
                len(rows), families_used, total)
            if rows else u"No equipment paired yet - press Equipment... to pair families with detail items.")

    @guard
    def on_panels_only(self, sender, args):
        """The same setting as Settings > LV, on the tab it applies to."""
        self.settings["lv_panels_only"] = u"1" if sender.IsChecked else u"0"
        save_settings(self.settings)
        self.fill_view_info()
        self.set_status(u"Every paired element will be placed." if not sender.IsChecked
                        else u"Only equipment with a panel schedule will be placed.")

    def fill_panels(self):
        """The Main LV picker: every electrical equipment instance in the model.

        Refilling raises SelectionChanged, so the handler is muted while it
        happens or the picker would save an empty choice over the real one."""
        self.filling_panels = True
        panels = self.model.get("panels", [])
        names = []
        for panel in panels:
            label = panel["label"]
            if not panel["scheduled"]:
                label += u"  (no panel schedule)"
            if label not in names:
                names.append(label)
        combo = self.find("CmbMainPanel")
        try:
            sb_ui.refill_searchable(combo, [u"(none)"] + names,
                                    self.settings.get("lv_main_panel") or u"(none)")
        finally:
            self.filling_panels = False

    @guard
    def on_read_panels(self, sender, args):
        self.model["panels"] = sb_model.read_panels(self.doc)
        self.fill_panels()
        scheduled = len([p for p in self.model["panels"] if p["scheduled"]])
        self.set_status(u"{0} electrical equipment instance(s), {1} with a panel schedule.".format(
            len(self.model["panels"]), scheduled))

    @guard
    def on_main_panel(self, sender, args):
        if self.filling_panels:
            return
        name = sb_ui.combo_text(sender)
        if name.startswith(u"("):
            name = u""
        self.settings["lv_main_panel"] = name.replace(u"  (no panel schedule)", u"")
        save_settings(self.settings)

    def fill_view_info(self):
        names = sb_model.read_view_names(self.doc)
        for tab in self.BUILT:
            self.find("TxtViewName" + tab.capitalize()).Text = u"next view will be named  {0}".format(
                next_view_name(self.settings.get("name_" + tab), names))
        levels = self.model.get("levels", [])
        rows = level_rows(self.settings, [l["name"] for l in levels])
        included = [u"{0} ({1})".format(name, abbr) for name, abbr, include in rows if include]
        skipped = len([r for r in rows if not r[2]])
        text = u"Level lines: {0}".format(u", ".join(included) if included else u"none ticked in Settings")
        if skipped:
            text += u"   ({0} unticked)".format(skipped)
        if self.settings.get("room_source") == u"element":
            room_from = u"element parameter '{0}'".format(self.settings.get("room_element_param") or u"not set")
        else:
            room_from = u"the room the element sits in ('{0}')".format(
                self.settings.get("room_name_param") or u"Name")
        text += u"   |   sheet {0}, scale 1:{1}   |   rooms from {2}".format(
            self.settings.get("sheet_size", u"A1"), self.settings.get("scale", u"1"), room_from)
        self.find("TxtLevelsVentilation").Text = text
        panels_only = self.settings.get("lv_panels_only", u"1") != u"0"
        self.find("ChkPanelsOnly").IsChecked = panels_only
        lv_text = text
        lv_text += (u"   |   only equipment with a panel schedule" if panels_only
                    else u"   |   every paired element, panel schedule or not")
        lv_text += u"   |   feeders {0}mm apart".format(self.settings.get("lv_line_gap_mm", u"18"))
        self.find("TxtLevelsLv").Text = lv_text

    # -- status -------------------------------------------------------------

    def set_status(self, text, is_issue=False):
        try:
            self.txt_status.Text = as_text(text)
            sb_ui.colour(self.txt_status, "OrangeBrush" if is_issue else "DimBrush")
        except Exception:
            pass

    def report_error(self, tb_text):
        body = write_error("window", tb_text)
        self.busy = False
        self.btn_create.IsEnabled = True
        last = tb_text.strip().splitlines()[-1] if tb_text.strip() else u"unknown error"
        self.set_status(last, True)
        try:
            sb_ui.show_message(self.window, sb_ui.palette_for(self.settings), u"Error", body,
                               subtitle=u"Something went wrong. The details are saved beside the settings file.",
                               modeless=True)
        except Exception:
            pass

    def update_theme_chip(self):
        self.btn_theme.Content = u"Light" if sb_ui.palette_for(self.settings) == u"dark" else u"Dark"

    # -- header events -------------------------------------------------------

    @guard
    def on_theme(self, sender, args):
        self.settings["theme"] = theme.other(sb_ui.palette_for(self.settings))
        sb_ui.repaint_all(self.settings["theme"])
        self.update_theme_chip()
        save_settings(self.settings)

    def equipment_param_names(self):
        """Parameter names off the paired equipment, to seed the room dropdown."""
        pairs = []
        for row in self.equipment_rows("ventilation") + self.equipment_rows("lv"):
            for pair in row_families(row):
                if pair not in pairs:
                    pairs.append(pair)
        if not pairs:
            return []
        try:
            instance_names, type_names = sb_model.family_param_names(self.doc, pairs)
        except Exception:
            return []
        names = list(instance_names)
        for name in type_names:
            if name not in names:
                names.append(name)
        return names

    @guard
    def on_settings(self, sender, args):
        self.harvest_browser()
        dialog = SettingsDialog(self.window, self.settings, self.model,
                                element_params=self.equipment_param_names())
        result = dialog.show()
        if result is None:
            return
        self.settings = result
        save_settings(self.settings)
        sb_ui.repaint_all(sb_ui.palette_for(self.settings))
        self.update_theme_chip()
        self.fill_view_info()
        self.married.show_param()
        self.set_status(u"Settings saved.")

    @guard
    def on_refresh(self, sender, args):
        self.harvest_browser()
        self.model = sb_model.read_project(self.doc)
        self.build_browser_rows()
        self.fill_equipment()
        self.fill_view_info()
        self.set_status(u"Model re-read: {0} families, {1} detail items, {2} levels.".format(
            len([r for r in self.model["families"] if r["type"] == u"*"]),
            len(self.model["details"]), len(self.model["levels"])))

    def make_equipment(self, tab):
        def handler(sender, args):
            try:
                dialog = EquipmentDialog(self.window, sb_ui.palette_for(self.settings),
                                         self.equipment_rows(tab), self.model,
                                         doc=self.doc, shared_pairs=self.shared_pairs(),
                                         settings=self.settings)
                rows = dialog.show()
                if rows is None:
                    return
                self.settings["equipment_" + tab] = encode_rows(rows)
                save_settings(self.settings)
                self.fill_equipment_for(tab)
            except Exception:
                self.report_error(traceback.format_exc())
        return handler

    @guard
    def on_create(self, sender, args):
        if self.busy:
            return
        self.harvest_browser()
        save_settings(self.settings)
        if self.tab == "married":
            job = self.married.job()
            if job is None:
                return
            self.raise_job(job, u"Applying the template - Revit will pause until it finishes...")
            return
        if self.tab in self.BUILT and not [r for r in self.equipment_rows(self.tab) if row_families(r) and r[3]]:
            proceed = sb_ui.show_message(
                self.window, sb_ui.palette_for(self.settings), u"No equipment paired",
                u"No equipment has been paired yet, so the view will only carry the level lines.\n\n"
                u"Create it anyway?", confirm=True)
            if not proceed:
                return
        job = {
            "tab": self.tab,
            "doc_title": as_text(self.doc.Title),
            "settings": dict(self.settings),
            "model": self.model,
        }
        self.raise_job(job, u"Building the schematic - Revit will pause until it finishes...")

    def raise_job(self, job, status):
        self.busy = True
        self.btn_create.IsEnabled = False
        self.set_status(status)
        self.handler.job = job
        self.handler.callback = self.on_done
        raised = as_text(self.ext_event.Raise())
        if raised not in (u"Accepted", u"Pending"):
            self.busy = False
            self.btn_create.IsEnabled = True
            self.set_status(u"Revit would not accept the request ({0}). Close the window and start again.".format(raised), True)

    def on_done(self, result):
        self.busy = False
        self.btn_create.IsEnabled = True
        result = result or {}
        ok = result.get("ok", False)
        issues = result.get("issues", 0)
        self.set_status(result.get("summary", u"Done."), (not ok) or issues > 0)
        try:
            if result.get("kind") == "template":
                self.married.after_run()
            else:
                self.fill_view_info()
        except Exception:
            pass
        mode = self.settings.get("show_results", u"issues")
        show = (not ok) or mode == u"always" or (mode == u"issues" and issues > 0)
        if show:
            body = u"\n".join(result.get("lines", []))
            if result.get("detail"):
                body += u"\n\n" + result["detail"]
            sb_ui.show_message(self.window, sb_ui.palette_for(self.settings),
                               u"Results" if ok else u"Failed", body,
                               subtitle=result.get("summary", u""), modeless=True)

    def on_closed(self, sender, args):
        try:
            self.harvest_browser()
            save_settings(self.settings)
        except Exception:
            pass

    def show(self):
        self.window.Show()
