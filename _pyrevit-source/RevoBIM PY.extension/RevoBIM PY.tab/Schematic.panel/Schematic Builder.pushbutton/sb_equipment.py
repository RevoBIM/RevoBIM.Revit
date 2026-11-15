# -*- coding: utf-8 -*-
"""Schematic Builder - the Equipment table.

Three columns: the equipment type (free text), the family and type in the
model it stands for, and the detail item family type that draws it on the
schematic. Rows are built as WPF elements in code, never bound.
"""
import sb_clr  # noqa: F401

import sb_ui
import sb_model
from sb_picker import PickerDialog
from sb_logic import (as_text, encode_pairs, row_families, pair_text, pairs_text,
                      transfer_summary, row_transfer_mode, decode_templates, ROW_WIDTH)
from sb_mapping import MappingDialog


NO_STRETCH = u"(do not stretch)"
TYPE_MARK = u"  (type)"

def family_text(family, type_name):
    return pair_text(family, type_name)


class EquipmentDialog(object):
    def __init__(self, owner, palette_name, rows, model, doc=None, shared_pairs=None,
                 settings=None):
        self.palette_name = palette_name
        self.model = model
        self.doc = doc
        self.settings = settings if settings is not None else {}
        self.shared_pairs = shared_pairs or []
        self.stretch_cache = {}
        self.filling = False
        self.result = None
        self.rows = [list(r) for r in rows] or [self.blank()]
        self.editors = []

        self.window, self.find, self.chrome = sb_ui.open_window("SbEquipment.xaml", palette_name, owner)

        self.lst = self.find("LstRows")
        self.txt_info = self.find("TxtInfo")
        self.txt_status = self.find("TxtStatus")
        self.find("BtnAddRow").Click += self.on_add
        self.find("BtnOk").Click += self.on_ok
        self.find("BtnCancel").Click += self.on_cancel
        self.fill()

    # -- rows ---------------------------------------------------------------

    def blank(self):
        return [u""] * ROW_WIDTH

    def fill(self):
        self.filling = True
        self.lst.Items.Clear()
        self.editors = []
        for index, row in enumerate(self.rows):
            while len(row) < ROW_WIDTH:
                row.append(u"")
            line = sb_ui.grid([sb_ui.star(0.9), sb_ui.star(1.3), sb_ui.star(1.3), sb_ui.star(1.0),
                               sb_ui.pixels(160), sb_ui.pixels(32)])
            equip = sb_ui.field(row[0], u"e.g. AHU, Extract fan, Toilet extract", margin=(0, 2, 8, 2))
            line.MinHeight = 32
            pairs = row_families(row)
            family_button = sb_ui.button(pairs_text(pairs) or u"pick one or more families...",
                                         style="BtnPick", margin=(0, 2, 8, 2))
            if len(pairs) > 1:
                sb_ui.tooltip(family_button,
                              u"\n".join([pair_text(f, t) for f, t in pairs]))
            detail_button = sb_ui.button(family_text(row[3], row[4]) or u"pick a detail item...",
                                         style="BtnPick", margin=(0, 2, 8, 2))
            stretch_box = sb_ui.combo(self.stretch_names(row), row[6] or NO_STRETCH,
                                      placeholder=u"do not stretch", editable=True,
                                      margin=(0, 2, 8, 2), search=True)
            stretch_box.SelectionChanged += self.make_stretch(index)
            params_button = sb_ui.button(
                transfer_summary(row, len(self.shared_pairs), self.templates()),
                style="BtnPick", margin=(0, 2, 8, 2))
            if row_transfer_mode(row) == "none":
                sb_ui.colour(params_button, "DimBrush")
            remove = sb_ui.button(u"\u2715", style="BtnMini")
            family_button.Click += self.make_family_pick(index)
            detail_button.Click += self.make_detail_pick(index)
            params_button.Click += self.make_params(index)
            remove.Click += self.make_remove(index)
            sb_ui.tooltip(remove, u"Remove this row")
            sb_ui.place(line, equip, 0)
            sb_ui.place(line, family_button, 1)
            sb_ui.place(line, detail_button, 2)
            sb_ui.place(line, stretch_box, 3)
            sb_ui.place(line, params_button, 4)
            sb_ui.place(line, remove, 5)
            self.lst.Items.Add(sb_ui.list_item(line))
            self.editors.append(equip)
        self.filling = False
        self.txt_info.Text = u"{0} row(s)".format(len(self.rows))

    def harvest(self):
        for index, editor in enumerate(self.editors):
            if index < len(self.rows):
                self.rows[index][0] = as_text(editor.Text).strip()

    def make_family_pick(self, index):
        def handler(sender, args):
            try:
                self.harvest()
                row = self.rows[index]
                picker = PickerDialog(self.window, self.palette_name,
                                      u"Families in the model - tick as many as this detail item stands for",
                                      self.model["families"], allow_family=True,
                                      multi=True, selected=row_families(row))
                choice = picker.show()
                if choice is None:
                    return
                row[1] = encode_pairs(choice)
                row[2] = u""
                if choice and not row[0]:
                    row[0] = choice[0][0]
                self.fill()
            except Exception:
                pass
        return handler

    def make_detail_pick(self, index):
        def handler(sender, args):
            try:
                self.harvest()
                row = self.rows[index]
                current = {"category": u"", "family": row[3], "type": row[4]}
                picker = PickerDialog(self.window, self.palette_name,
                                      u"Detail item on the schematic", self.model["details"],
                                      allow_family=False, current=current)
                choice = picker.show()
                if choice is None:
                    return
                if choice:
                    row[3] = choice["family"]
                    row[4] = choice["type"]
                else:
                    row[3] = u""
                    row[4] = u""
                self.fill()
            except Exception:
                pass
        return handler

    def templates(self):
        return decode_templates(self.settings.get("templates", u""))

    def stretch_names(self, row):
        """The detail item's length parameters, for stretching it to span its
        outgoing circuits. Read once per detail item type."""
        key = (as_text(row[3]), as_text(row[4]))
        if not key[0]:
            return [NO_STRETCH]
        if key not in self.stretch_cache:
            names = []
            try:
                instance_names, type_names = sb_model.dimension_params(self.doc, key[0], key[1])
            except Exception:
                instance_names, type_names = [], []
            names.extend(instance_names)
            for name in type_names:
                if name not in names:
                    names.append(name + TYPE_MARK)
            self.stretch_cache[key] = names
        return [NO_STRETCH] + self.stretch_cache[key]

    def make_stretch(self, index):
        def handler(sender, args):
            if self.filling:
                return
            try:
                name = sb_ui.combo_text(sender)
                if name.endswith(TYPE_MARK):
                    self.txt_status.Text = (u"'{0}' is a type parameter - stretching it would resize "
                                            u"every item of that type.".format(name[:-len(TYPE_MARK)]))
                    name = name[:-len(TYPE_MARK)]
                self.rows[index][6] = u"" if name.startswith(u"(") else name
            except Exception:
                pass
        return handler

    def make_params(self, index):
        def handler(sender, args):
            try:
                self.harvest()
                row = self.rows[index]
                if not row[3]:
                    self.txt_status.Text = u"Pick the detail item first - its parameters come off it."
                    return
                dialog = MappingDialog(self.window, self.palette_name, row, self.doc,
                                       self.shared_pairs, self.settings, self.model)
                field = dialog.show()
                if field is None:
                    return
                row[5] = field
                self.fill()
            except Exception:
                pass
        return handler

    def make_remove(self, index):
        def handler(sender, args):
            try:
                self.harvest()
                del self.rows[index]
                if not self.rows:
                    self.rows.append(self.blank())
                self.fill()
            except Exception:
                pass
        return handler

    # -- footer -------------------------------------------------------------

    def on_add(self, sender, args):
        try:
            self.harvest()
            self.rows.append(self.blank())
            self.fill()
            if self.editors:
                self.editors[-1].Focus()
        except Exception:
            pass

    def on_ok(self, sender, args):
        try:
            self.harvest()
            kept = []
            for row in self.rows:
                if not (row[0] or row[1] or row[3]):
                    continue
                if not row[0]:
                    pairs = row_families(row)
                    row[0] = pairs[0][0] if pairs else u""
                kept.append(row)
            incomplete = [r[0] for r in kept if not (row_families(r) and r[3])]
            if incomplete:
                self.txt_status.Text = u"Needs at least one family and a detail item: " + u", ".join(incomplete[:4])
                return
            self.result = kept
            self.window.Close()
        except Exception:
            pass

    def on_cancel(self, sender, args):
        self.window.Close()

    def show(self):
        self.window.ShowDialog()
        return self.result
