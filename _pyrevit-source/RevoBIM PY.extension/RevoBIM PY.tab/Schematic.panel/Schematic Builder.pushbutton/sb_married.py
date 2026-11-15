# -*- coding: utf-8 -*-
"""Schematic Builder - the Married Element List tab.

Every detail item in the project that carries a model element's id in the
linked element ID parameter, with the drafting view it sits on and the
element it is married to. A named template of from/to parameter pairs can
be run over the ticked ones: the model element is found again by that id
and its values pushed onto the detail item.

This tab works the other way round from the rest of the tool - it reads
what earlier runs created - which is why it is green rather than orange.
"""
import sb_clr  # noqa: F401

import traceback

import sb_ui
import sb_model
from sb_logic import (as_text, TOKENS, decode_templates, encode_templates, upsert_template,
                      remove_template, template_pairs, decode_assignments, encode_assignments,
                      batch_by_template, save_settings)


NONE = u"(none)"


class MarriedTab(object):
    def __init__(self, owner):
        self.owner = owner              # the MainWindow
        self.find = owner.find
        self.doc = owner.doc
        self.rows = []
        self.shown = []
        self.ticks = []
        self.chosen = set()             # detail ids ticked
        self.editors = []
        self.assignments = {}           # detail id -> template name, saved per project
        self.cells = []                 # the per-row template dropdowns
        self.filling = False            # so rebuilding the list does not fire the cells
        self.from_names = list(TOKENS)
        self.to_names = []
        self.read_once = False

        self.lst = self.find("LstMarried")
        self.lst_template = self.find("LstTemplate")
        self.txt_info = self.find("TxtMarriedInfo")
        self.txt_template_info = self.find("TxtTemplateInfo")
        self.txt_search = self.find("TxtMarriedSearch")
        self.cmb_template = self.find("CmbTemplate")

        self.find("BtnMarriedRefresh").Click += self.on_refresh
        self.find("BtnMarriedAll").Click += self.on_all
        self.find("BtnMarriedNone").Click += self.on_none
        self.find("BtnMarriedAssign").Click += self.on_assign
        self.find("BtnMarriedUnassign").Click += self.on_unassign
        self.txt_search.TextChanged += self.on_search
        self.lst.MouseDoubleClick += self.on_double_click
        self.find("BtnTemplateNew").Click += self.on_new
        self.find("BtnTemplateSave").Click += self.on_save
        self.find("BtnTemplateSaveAs").Click += self.on_save_as
        self.find("BtnTemplateDelete").Click += self.on_delete
        self.find("BtnTemplateAdd").Click += self.on_add
        self.cmb_template.SelectionChanged += self.on_template_picked

        self.assignments = decode_assignments(self.settings().get("assignments", u""),
                                              as_text(self.doc.Title))
        self.fill_template_names(self.settings().get("active_template", u""))
        self.load_template(self.settings().get("active_template", u""))
        self.show_param()
        self.txt_info.Text = u"Press 'Read the model' to list the married detail items."

    def settings(self):
        return self.owner.settings

    def link_param(self):
        return as_text(self.settings().get("link_param", u"")).strip()

    def show_param(self):
        self.find("TxtMarriedParam").Text = (
            u"found through '{0}'".format(self.link_param()) if self.link_param()
            else u"no linked element ID parameter is named in Settings")

    # -- the list -------------------------------------------------------------

    def refresh(self):
        self.show_param()
        self.rows = sb_model.read_married(self.doc, self.link_param())
        self.read_once = True
        try:
            from_names, to_names = sb_model.married_param_names(self.doc, self.rows)
        except Exception:
            from_names, to_names = [], []
        merged = list(TOKENS)
        for name in from_names:
            if name not in merged:
                merged.append(name)
        self.from_names = merged
        self.to_names = to_names
        live = set([r["detail_id"] for r in self.rows])
        self.chosen = set([d for d in self.chosen if d in live])
        # an assignment to a detail item that has been deleted is dropped
        gone = [d for d in self.assignments if d not in live]
        if gone:
            for detail_id in gone:
                del self.assignments[detail_id]
            self.save_assignments()
        self.fill()
        self.fill_template()

    def key_of(self, row):
        return row["detail_id"]

    def harvest_ticks(self):
        for index, row in enumerate(self.shown):
            if index >= len(self.ticks):
                break
            if self.ticks[index].IsChecked:
                self.chosen.add(row["detail_id"])
            else:
                self.chosen.discard(row["detail_id"])

    def fill(self):
        self.filling = True
        self.lst.Items.Clear()
        self.shown = []
        self.ticks = []
        self.cells = []
        needle = as_text(self.txt_search.Text).strip().lower()
        for row in self.rows:
            haystack = u" ".join([row["view"], row["detail"], row["model"], row["link_text"], row["status"]]).lower()
            if needle and [w for w in needle.split() if w not in haystack]:
                continue
            self.shown.append(row)
        for row in self.shown:
            line = sb_ui.grid([sb_ui.pixels(26), sb_ui.star(1.1), sb_ui.star(1.2), sb_ui.pixels(70),
                               sb_ui.star(1.5), sb_ui.pixels(140), sb_ui.pixels(130)])
            tick = sb_ui.check(u"", row["detail_id"] in self.chosen)
            tick.Click += self.make_tick(row["detail_id"])
            sb_ui.place(line, tick, 0)
            self.ticks.append(tick)
            view = sb_ui.label(row["view"], margin=(0, 0, 6, 0))
            sb_ui.colour(view, "BlueBrush")
            sb_ui.place(line, view, 1)
            detail = sb_ui.label(row["detail"], margin=(0, 0, 6, 0))
            sb_ui.tooltip(detail, u"Detail item id {0}".format(row["detail_id"]))
            sb_ui.place(line, detail, 2)
            sb_ui.place(line, sb_ui.label(row["link_text"], dim=True, margin=(0, 0, 6, 0)), 3)
            model = sb_ui.label(row["model"] or u"-", margin=(0, 0, 6, 0))
            sb_ui.place(line, model, 4)
            assigned = self.assignments.get(row["detail_id"], u"")
            cell = sb_ui.combo(self.template_choices(assigned), assigned or NONE,
                               placeholder=u"none", margin=(0, 1, 6, 1))
            cell.Height = 22
            if assigned and not template_pairs(self.templates(), assigned):
                sb_ui.colour(cell, "RedBrush")
                sb_ui.tooltip(cell, u"There is no template called '{0}' any more.".format(assigned))
            sb_ui.tooltip(cell, u"Pick a template for this detail item. With several rows selected "
                                u"it is given to all of them.")
            cell.SelectionChanged += self.make_cell_changed(row["detail_id"])
            sb_ui.place(line, cell, 5)
            self.cells.append(cell)
            status = sb_ui.label(row["status"], dim=(row["status"] == u"ok"))
            if row["status"] != u"ok":
                sb_ui.colour(status, "RedBrush")
            sb_ui.place(line, status, 6)
            self.lst.Items.Add(sb_ui.list_item(line))
        self.filling = False
        self.report()

    def template_choices(self, keep):
        """Every saved template, plus a way to clear the cell. A name that no
        longer exists is still offered while it is on a row, so the cell shows
        the truth rather than quietly reading empty."""
        names = [NONE] + [name for name, pairs in self.templates()]
        if keep and keep not in names:
            names.append(keep)
        return names

    def selected_ids(self):
        """The detail ids of the highlighted rows."""
        ids = []
        try:
            for item in self.lst.SelectedItems:
                index = self.lst.Items.IndexOf(item)
                if 0 <= index < len(self.shown):
                    ids.append(self.shown[index]["detail_id"])
        except Exception:
            pass
        return ids

    def target_ids(self):
        """What an assignment applies to: everything ticked and everything
        highlighted, so either way of picking rows works."""
        self.harvest_ticks()
        ids = set(self.chosen)
        ids.update(self.selected_ids())
        return ids

    def assign(self, detail_ids, name, rebuild=True):
        for detail_id in detail_ids:
            if name:
                self.assignments[detail_id] = name
            elif detail_id in self.assignments:
                del self.assignments[detail_id]
        self.save_assignments()
        if rebuild:
            self.fill()
        else:
            self.show_cells()

    def make_tick(self, detail_id):
        """Ticking one box of a selection ticks the whole selection - the same
        rule the template cell follows, so the two behave alike."""
        def handler(sender, args):
            if self.filling:
                return
            try:
                wanted = bool(sender.IsChecked)
                selected = self.selected_ids()
                targets = selected if detail_id in selected and len(selected) > 1 else [detail_id]
                self.filling = True
                try:
                    for index, row in enumerate(self.shown):
                        if row["detail_id"] in targets and index < len(self.ticks):
                            self.ticks[index].IsChecked = wanted
                finally:
                    self.filling = False
                self.harvest_ticks()
                self.report()
                if len(targets) > 1:
                    self.txt_info.Text = u"{0} detail item(s) {1}.".format(
                        len(targets), u"ticked" if wanted else u"unticked")
            except Exception:
                pass
        return handler

    def show_cells(self):
        """Put the assignments back onto the row dropdowns without rebuilding
        the list - a cell handler must not destroy the control it came from."""
        self.filling = True
        try:
            for index, row in enumerate(self.shown):
                if index >= len(self.cells):
                    break
                wanted = self.assignments.get(row["detail_id"], u"") or NONE
                if sb_ui.combo_text(self.cells[index]) != wanted:
                    sb_ui.select_text(self.cells[index], wanted)
        finally:
            self.filling = False
        self.report()

    def make_cell_changed(self, detail_id):
        def handler(sender, args):
            if self.filling:
                return
            try:
                name = sb_ui.combo_text(sender)
                if name == NONE:
                    name = u""
                # a cell changed inside a selection sets the whole selection
                selected = self.selected_ids()
                targets = selected if detail_id in selected else [detail_id]
                self.assign(targets, name, rebuild=False)
                self.txt_info.Text = (
                    u"'{0}' assigned to {1} detail item(s).".format(name, len(targets)) if name
                    else u"Template cleared from {0} detail item(s).".format(len(targets)))
            except Exception:
                pass
        return handler

    def report(self):
        broken = len([r for r in self.rows if r["status"] != u"ok"])
        text = u"{0} of {1} shown   |   {2} ticked".format(len(self.shown), len(self.rows), len(self.chosen))
        assigned = len([r for r in self.rows if self.assignments.get(r["detail_id"])])
        if assigned:
            names = sorted(set([self.assignments[r["detail_id"]] for r in self.rows
                                if self.assignments.get(r["detail_id"])]))
            text += u"   |   {0} assigned a template ({1})".format(assigned, u", ".join(names[:3]))
        if broken:
            text += u"   |   {0} whose model element cannot be found".format(broken)
        views = len(set([r["view_id"] for r in self.rows]))
        if self.rows:
            text += u"   |   across {0} drafting view(s)".format(views)
        self.txt_info.Text = text

    def save_assignments(self):
        self.settings()["assignments"] = encode_assignments(
            self.settings().get("assignments", u""), as_text(self.doc.Title), self.assignments)
        save_settings(self.settings())

    # -- templates --------------------------------------------------------------

    def templates(self):
        return decode_templates(self.settings().get("templates", u""))

    def fill_template_names(self, keep):
        self.filling = True
        self.cmb_template.Items.Clear()
        for name, pairs in self.templates():
            self.cmb_template.Items.Add(name)
        sb_ui.select_text(self.cmb_template, keep)
        self.filling = False

    def load_template(self, name):
        pairs = template_pairs(self.templates(), name)
        self.pairs = pairs if pairs else [(u"Mark", u"Mark")]
        self.fill_template()

    def fill_template(self):
        self.lst_template.Items.Clear()
        self.editors = []
        for source, target in self.pairs:
            line = sb_ui.grid([sb_ui.star(1), sb_ui.pixels(34), sb_ui.star(1), sb_ui.pixels(32)])
            line.MinHeight = 32
            from_box = sb_ui.combo(self.from_names, source, placeholder=u"parameter or {token}",
                                   editable=True, margin=(0, 2, 8, 2), search=True)
            arrow = sb_ui.label(u"\u2192", dim=True)
            to_box = sb_ui.combo(self.to_names, target, placeholder=u"instance parameter on the detail item",
                                 editable=True, margin=(0, 2, 8, 2), search=True)
            remove = sb_ui.button(u"\u2715", style="BtnMini")
            remove.Click += self.make_remove(len(self.editors))
            sb_ui.place(line, from_box, 0)
            sb_ui.place(line, arrow, 1)
            sb_ui.place(line, to_box, 2)
            sb_ui.place(line, remove, 3)
            self.lst_template.Items.Add(sb_ui.list_item(line))
            self.editors.append((from_box, to_box))
        hint = u"{0} row(s).".format(len(self.editors))
        if not self.read_once:
            hint += (u" Press 'Read the model' to fill the dropdowns with the parameters of the "
                     u"married elements' categories.")
        else:
            hint += (u" From: {0} parameter(s) on the model elements' categories.  To: {1} on the "
                     u"detail items'. Open a dropdown for the full list, type to narrow it, or type "
                     u"a name that is not in it.".format(len(self.from_names) - len(TOKENS),
                                                        len(self.to_names)))
        self.txt_template_info.Text = hint

    def harvest_template(self):
        pairs = []
        for from_box, to_box in self.editors:
            source = sb_ui.combo_text(from_box)
            target = sb_ui.combo_text(to_box)
            if source or target:
                pairs.append((source, target))
        self.pairs = pairs
        return [(s, t) for s, t in pairs if s and t]

    def make_remove(self, index):
        def handler(sender, args):
            try:
                self.harvest_template()
                if index < len(self.pairs):
                    del self.pairs[index]
                if not self.pairs:
                    self.pairs = [(u"", u"")]
                self.fill_template()
            except Exception:
                pass
        return handler

    # -- events -----------------------------------------------------------------

    def on_refresh(self, sender, args):
        try:
            self.harvest_ticks()
            self.refresh()
            self.owner.set_status(u"{0} married detail item(s) found.".format(len(self.rows)))
        except Exception:
            self.owner.report_error(traceback.format_exc())

    def on_search(self, sender, args):
        try:
            self.harvest_ticks()
            self.fill()
        except Exception:
            pass

    def on_all(self, sender, args):
        try:
            for tick in self.ticks:
                tick.IsChecked = True
            self.harvest_ticks()
            self.report()
        except Exception:
            pass

    def on_none(self, sender, args):
        try:
            for tick in self.ticks:
                tick.IsChecked = False
            self.harvest_ticks()
            self.report()
        except Exception:
            pass

    def on_assign(self, sender, args):
        try:
            self.harvest_ticks()
            name = sb_ui.combo_text(self.cmb_template)
            if not name:
                self.txt_info.Text = u"Pick or name a template below first."
                return
            if not template_pairs(self.templates(), name):
                self.txt_info.Text = u"'{0}' is not saved yet - press Save under the template first.".format(name)
                return
            targets = self.target_ids()
            if not targets:
                self.txt_info.Text = u"Tick or highlight the detail items to assign it to."
                return
            self.assign(targets, name)
            self.txt_info.Text = u"'{0}' assigned to {1} detail item(s).".format(name, len(targets))
        except Exception:
            pass

    def on_unassign(self, sender, args):
        try:
            targets = self.target_ids()
            cleared = len([d for d in targets if d in self.assignments])
            self.assign(targets, u"")
            self.txt_info.Text = u"Template cleared from {0} detail item(s).".format(cleared)
        except Exception:
            pass

    def on_double_click(self, sender, args):
        try:
            index = self.lst.SelectedIndex
            if 0 <= index < len(self.ticks):
                self.ticks[index].IsChecked = not self.ticks[index].IsChecked
                self.harvest_ticks()
                self.report()
        except Exception:
            pass

    def on_template_picked(self, sender, args):
        if self.filling:
            return
        try:
            name = sb_ui.combo_text(self.cmb_template)
            if name and template_pairs(self.templates(), name):
                self.load_template(name)
                self.settings()["active_template"] = name
                save_settings(self.settings())
        except Exception:
            pass

    def on_new(self, sender, args):
        try:
            self.cmb_template.Text = u""
            self.pairs = [(u"", u"")]
            self.fill_template()
            self.txt_template_info.Text = (u"New template. Fill the rows in, type a name in the box, "
                                           u"then press Save.")
            try:
                self.cmb_template.Focus()
            except Exception:
                pass
        except Exception:
            pass

    def on_save_as(self, sender, args):
        try:
            name = sb_ui.combo_text(self.cmb_template)
            if not name:
                self.txt_template_info.Text = u"Type the new template's name in the box first."
                return
            if template_pairs(self.templates(), name):
                self.txt_template_info.Text = (u"'{0}' already exists - change the name to keep both, "
                                               u"or press Save to replace it.".format(name))
                return
            self.save_template(name)
        except Exception:
            pass

    def save_template(self, name):
        pairs = self.harvest_template()
        if not pairs:
            self.txt_template_info.Text = u"Fill in at least one complete row before saving."
            return
        templates = upsert_template(self.templates(), name, pairs)
        self.settings()["templates"] = encode_templates(templates)
        self.settings()["active_template"] = name
        save_settings(self.settings())
        self.fill_template_names(name)
        self.fill_template()
        self.fill()          # the cell dropdowns pick up the new name
        self.txt_template_info.Text = u"Saved '{0}' with {1} row(s).".format(name, len(pairs))

    def on_save(self, sender, args):
        try:
            name = sb_ui.combo_text(self.cmb_template)
            if not name:
                self.txt_template_info.Text = u"Give the template a name first."
                return
            self.save_template(name)
        except Exception:
            pass

    def on_delete(self, sender, args):
        try:
            name = sb_ui.combo_text(self.cmb_template)
            if not name or not template_pairs(self.templates(), name):
                self.txt_template_info.Text = u"Pick a saved template to delete."
                return
            if not sb_ui.show_message(self.owner.window, sb_ui.palette_for(self.settings()),
                                      u"Delete template", u"Delete the template '{0}'?".format(name),
                                      confirm=True):
                return
            self.settings()["templates"] = encode_templates(remove_template(self.templates(), name))
            self.settings()["active_template"] = u""
            save_settings(self.settings())
            self.fill_template_names(u"")
            self.cmb_template.Text = u""
            self.pairs = [(u"", u"")]
            self.fill_template()
            self.fill()
        except Exception:
            pass

    def on_add(self, sender, args):
        try:
            self.harvest_template()
            self.pairs.append((u"", u""))
            self.fill_template()
        except Exception:
            pass

    # -- the run ----------------------------------------------------------------

    def job(self):
        """The job for the ExternalEvent, or None with the reason in the status line.

        Each ticked item runs the template assigned to it; anything with no
        assignment runs the one on screen."""
        self.harvest_ticks()
        self.harvest_template()
        if not self.read_once:
            self.owner.set_status(u"Read the model first.", True)
            return None
        targets = [r["detail_id"] for r in self.rows if r["detail_id"] in self.chosen and r["status"] == u"ok"]
        skipped = len([r for r in self.rows if r["detail_id"] in self.chosen and r["status"] != u"ok"])
        if not targets:
            self.owner.set_status(u"Tick the detail items to run a template on.", True)
            return None
        fallback = sb_ui.combo_text(self.cmb_template)
        if not template_pairs(self.templates(), fallback):
            fallback = u""
        batches, orphans = batch_by_template(targets, self.assignments, self.templates(), fallback)
        if not batches:
            self.owner.set_status(u"None of the ticked items has a template - assign one, or save "
                                  u"the template below and pick it.", True)
            return None
        notes = []
        if skipped:
            notes.append(u"{0} with no model element".format(skipped))
        if orphans:
            notes.append(u"{0} with no template".format(len(orphans)))
        if notes:
            self.owner.set_status(u"Left out: " + u", ".join(notes), True)
        return {
            "tab": "married",
            "doc_title": as_text(self.doc.Title),
            "settings": dict(self.settings()),
            "model": self.owner.model,
            "batches": batches,
            "orphans": orphans,
        }

    def after_run(self):
        try:
            self.refresh()
        except Exception:
            pass
