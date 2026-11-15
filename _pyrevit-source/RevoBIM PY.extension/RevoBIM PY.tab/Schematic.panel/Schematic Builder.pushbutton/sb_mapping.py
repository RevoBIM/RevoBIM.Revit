# -*- coding: utf-8 -*-
"""Schematic Builder - the parameter template window.

One window for every parameter mapping in the tool. The templates on the
left are the same ones the Married Element List uses, so a mapping built
once is available everywhere; the rows on the right are the template being
edited. An equipment row then points at a template by name, writes nothing,
or falls back to the shared list in Settings.

Each row picks a **category** first and the *from* dropdown then offers that
category's own parameters, which is what makes a list of several hundred
usable. Both parameter boxes are searchable and accept a typed name.
"""
import sb_clr  # noqa: F401

import sb_ui
import sb_model
from sb_logic import (as_text, TOKENS, decode_templates, encode_templates, upsert_template,
                      remove_template, template_pairs, row_transfer_mode, row_transfer_pairs,
                      row_template_name, encode_row_template, TRANSFER_NONE, save_settings)


TOKEN_CATEGORY = u"(tokens and anything)"

MODES = [
    ("template", u"the template picked on the left"),
    ("inherit", u"the shared list from Settings"),
    ("none", u"nothing - skip the transfer for this equipment"),
]


class MappingDialog(object):
    """Returns the encoded transfer field for the equipment row, or None."""

    def __init__(self, owner, palette_name, row, doc, shared_pairs, settings, model=None):
        self.row = row
        self.doc = doc
        self.settings = settings
        self.model = model or {}
        self.result = None
        self.filling = False
        self.editors = []
        self.names = []
        self.to_names = []
        self.pairs = []
        self.current = u""

        self.window, self.find, self.chrome = sb_ui.open_window("SbMapping.xaml", palette_name, owner)
        self.find("TxtTitle").Text = u"Parameter templates"
        self.find("TxtEquipment").Text = as_text(row[0]) or u"(unnamed equipment)"

        self.lst = self.find("LstRows")
        self.lst_templates = self.find("LstTemplates")
        self.cmb_mode = self.find("CmbMode")
        self.txt_info = self.find("TxtInfo")
        self.txt_name = self.find("TxtTemplateName")
        for key, label in MODES:
            self.cmb_mode.Items.Add(label)
        mode = row_transfer_mode(row)
        if mode == "custom":
            mode = "template"          # a pre-template row: offer to save it as one
        self.set_mode(mode)
        self.cmb_mode.SelectionChanged += self.on_mode
        self.lst_templates.SelectionChanged += self.on_pick_template
        self.find("BtnAddRow").Click += self.on_add
        self.find("BtnNew").Click += self.on_new
        self.find("BtnSave").Click += self.on_save
        self.find("BtnSaveAs").Click += self.on_save_as
        self.find("BtnDelete").Click += self.on_delete
        self.find("BtnOk").Click += self.on_ok
        self.find("BtnCancel").Click += self.on_cancel

        self.read_names()
        self.current = row_template_name(row)
        self.pairs = (template_pairs(self.templates(), self.current)
                      or row_transfer_pairs(row) or list(shared_pairs) or [(u"Mark", u"Mark")])
        self.fill_templates()
        self.fill()

    # -- what the drop-downs offer ---------------------------------------------

    def read_names(self):
        by_category = self.model.get("category_params") or {}
        if not by_category:
            try:
                by_category = sb_model.params_by_category(self.doc)
            except Exception:
                by_category = {}
        self.by_category = by_category
        merged = set()
        for name in by_category:
            merged |= set(by_category[name])
        self.names = sorted(merged, key=lambda n: n.lower())
        try:
            det_instance, det_type, sampled = sb_model.detail_param_names(
                self.doc, as_text(self.row[3]), as_text(self.row[4]))
        except Exception:
            det_instance, det_type, sampled = [], [], False
        self.to_names = list(det_instance)
        self.find("TxtSources").Text = (
            u"From: pick a category to narrow the parameters to that category's own, or "
            u"'{0}' for the tokens and every parameter in the project ({1}).   "
            u"To: {2} instance parameter(s) on {3}.   Type in any box to search by keyword.".format(
                TOKEN_CATEGORY, len(self.names), len(self.to_names),
                as_text(self.row[3]) or u"the detail item"))

    def categories(self):
        return [TOKEN_CATEGORY] + sorted(self.by_category.keys(), key=lambda n: n.lower())

    def from_names(self, category):
        if not category or category == TOKEN_CATEGORY:
            return list(TOKENS) + self.names
        return list(TOKENS) + list(self.by_category.get(category, []))

    def category_for(self, source):
        """The category a saved source parameter belongs to, if only one does."""
        if not source or source.startswith(u"{"):
            return TOKEN_CATEGORY
        owners = [name for name in self.by_category if source in self.by_category[name]]
        return owners[0] if len(owners) == 1 else TOKEN_CATEGORY

    # -- templates --------------------------------------------------------------

    def templates(self):
        return decode_templates(self.settings.get("templates", u""))

    def fill_templates(self):
        self.lst_templates.Items.Clear()
        self.template_names = [name for name, pairs in self.templates()]
        for name in self.template_names:
            count = len(template_pairs(self.templates(), name))
            line = sb_ui.grid([sb_ui.star(1), sb_ui.pixels(40)])
            sb_ui.place(line, sb_ui.label(name), 0)
            sb_ui.place(line, sb_ui.label(u"{0}".format(count), dim=True), 1)
            self.lst_templates.Items.Add(sb_ui.list_item(line))
        if self.current in self.template_names:
            self.lst_templates.SelectedIndex = self.template_names.index(self.current)
        self.txt_name.Text = self.current

    def on_pick_template(self, sender, args):
        try:
            index = self.lst_templates.SelectedIndex
            if index < 0 or index >= len(self.template_names):
                return
            self.current = self.template_names[index]
            self.txt_name.Text = self.current
            self.pairs = template_pairs(self.templates(), self.current) or [(u"", u"")]
            self.set_mode("template")
            self.fill()
        except Exception:
            pass

    def save_named(self, name):
        pairs = [(s, t) for s, t in self.harvest() if s and t]
        if not name:
            self.txt_info.Text = u"Give the template a name first."
            return False
        if not pairs:
            self.txt_info.Text = u"Fill in at least one complete row before saving."
            return False
        self.settings["templates"] = encode_templates(upsert_template(self.templates(), name, pairs))
        self.settings["active_template"] = name
        save_settings(self.settings)
        self.current = name
        self.fill_templates()
        self.txt_info.Text = u"Saved '{0}' with {1} row(s).".format(name, len(pairs))
        return True

    # -- rows -------------------------------------------------------------------

    def fill(self):
        self.filling = True
        self.lst.Items.Clear()
        self.editors = []
        editable = self.mode() == "template"
        for source, target in self.pairs:
            line = sb_ui.grid([sb_ui.star(1.1), sb_ui.star(1.4), sb_ui.pixels(34),
                               sb_ui.star(1.4), sb_ui.pixels(32)])
            line.MinHeight = 32
            category = self.category_for(source)
            cat_box = sb_ui.combo(self.categories(), category, placeholder=u"category",
                                  editable=True, margin=(0, 2, 8, 2), search=True)
            from_box = sb_ui.combo(self.from_names(category), source, placeholder=u"parameter or {token}",
                                   editable=True, margin=(0, 2, 8, 2), search=True)
            arrow = sb_ui.label(u"\u2192", dim=True)
            to_box = sb_ui.combo(self.to_names, target, placeholder=u"instance parameter",
                                 editable=True, margin=(0, 2, 8, 2), search=True)
            remove = sb_ui.button(u"\u2715", style="BtnMini")
            cat_box.SelectionChanged += self.make_category_changed(from_box)
            remove.Click += self.make_remove(len(self.editors))
            for control in (cat_box, from_box, to_box, remove):
                control.IsEnabled = editable
            sb_ui.place(line, cat_box, 0)
            sb_ui.place(line, from_box, 1)
            sb_ui.place(line, arrow, 2)
            sb_ui.place(line, to_box, 3)
            sb_ui.place(line, remove, 4)
            self.lst.Items.Add(sb_ui.list_item(line))
            self.editors.append((cat_box, from_box, to_box))
        self.filling = False
        self.find("BtnAddRow").IsEnabled = editable
        self.report()

    def make_category_changed(self, from_box):
        def handler(sender, args):
            if self.filling:
                return
            try:
                category = sb_ui.combo_text(sender)
                keep = sb_ui.combo_text(from_box)
                names = self.from_names(category)
                sb_ui.refill_searchable(from_box, names, keep if keep in names else u"")
            except Exception:
                pass
        return handler

    def harvest(self):
        pairs = []
        for cat_box, from_box, to_box in self.editors:
            source = sb_ui.combo_text(from_box)
            target = sb_ui.combo_text(to_box)
            if source or target:
                pairs.append((source, target))
        self.pairs = pairs
        return pairs

    def make_remove(self, index):
        def handler(sender, args):
            try:
                self.harvest()
                if index < len(self.pairs):
                    del self.pairs[index]
                if not self.pairs:
                    self.pairs = [(u"", u"")]
                self.fill()
            except Exception:
                pass
        return handler

    def mode(self):
        chosen = sb_ui.combo_text(self.cmb_mode)
        for key, label in MODES:
            if label == chosen:
                return key
        return "template"

    def set_mode(self, key):
        for index, pair in enumerate(MODES):
            if pair[0] == key:
                self.cmb_mode.SelectedIndex = index

    def report(self):
        mode = self.mode()
        if mode == "none":
            self.txt_info.Text = u"Nothing is written onto this equipment's detail items."
        elif mode == "inherit":
            self.txt_info.Text = u"The shared list in Settings is used; the template below is left alone."
        else:
            self.txt_info.Text = (u"{0} row(s) in '{1}'. Save the template, then OK sets it on this "
                                  u"equipment.".format(len(self.editors), self.current or u"unnamed"))

    # -- events -----------------------------------------------------------------

    def on_mode(self, sender, args):
        try:
            if self.editors:
                self.harvest()
            self.fill()
        except Exception:
            pass

    def on_add(self, sender, args):
        try:
            self.harvest()
            self.pairs.append((u"", u""))
            self.fill()
        except Exception:
            pass

    def on_new(self, sender, args):
        try:
            self.current = u""
            self.txt_name.Text = u""
            self.pairs = [(u"", u"")]
            self.lst_templates.SelectedIndex = -1
            self.set_mode("template")
            self.fill()
            self.txt_info.Text = u"New template: fill the rows in, name it, then Save."
        except Exception:
            pass

    def on_save(self, sender, args):
        try:
            self.save_named(as_text(self.txt_name.Text).strip())
            self.fill()
        except Exception:
            pass

    def on_save_as(self, sender, args):
        try:
            name = as_text(self.txt_name.Text).strip()
            if template_pairs(self.templates(), name):
                self.txt_info.Text = (u"'{0}' already exists - change the name to keep both, or press "
                                      u"Save to replace it.".format(name))
                return
            self.save_named(name)
            self.fill()
        except Exception:
            pass

    def on_delete(self, sender, args):
        try:
            name = as_text(self.txt_name.Text).strip()
            if not template_pairs(self.templates(), name):
                self.txt_info.Text = u"Pick a saved template to delete."
                return
            self.settings["templates"] = encode_templates(remove_template(self.templates(), name))
            save_settings(self.settings)
            self.current = u""
            self.pairs = [(u"", u"")]
            self.fill_templates()
            self.fill()
        except Exception:
            pass

    def on_ok(self, sender, args):
        try:
            mode = self.mode()
            if mode == "none":
                self.result = TRANSFER_NONE
            elif mode == "inherit":
                self.result = u""
            else:
                name = as_text(self.txt_name.Text).strip()
                if not template_pairs(self.templates(), name):
                    if not self.save_named(name):
                        return
                self.settings["active_template"] = name
                self.result = encode_row_template(name)
            self.window.Close()
        except Exception:
            pass

    def on_cancel(self, sender, args):
        self.window.Close()

    def show(self):
        self.window.ShowDialog()
        return self.result
