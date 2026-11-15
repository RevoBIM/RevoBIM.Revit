# -*- coding: utf-8 -*-
"""Schematic Builder - the pick-a-family dialog.

One dialog serves both columns of the Equipment table:

- **model families**, multi-select, so several families can share one detail
  item. Tick them; the ticks survive changing the filter, so a selection can
  be built up across several searches.
- **detail item families**, single pick.

Filter by category, keyword, used-only, and split by type or take a whole
family.
"""
import sb_clr  # noqa: F401

import sb_ui
from sb_logic import as_text, natural_key

from System.Windows import HorizontalAlignment, Visibility  # noqa: E402


class PickerDialog(object):
    """rows: [{'category','family','type','count','type_id'}]; type '*' = all types.

    Single mode returns the chosen row dict, {} for Clear, None for Cancel.
    Multi mode returns a list of (family, type) pairs, [] for Clear, None for
    Cancel."""

    def __init__(self, owner, palette_name, title, rows, allow_family=True, current=None,
                 multi=False, selected=None):
        self.rows = rows
        self.allow_family = allow_family
        self.multi = bool(multi)
        self.result = None
        self.picked = False
        self.shown = []
        self.ticks = []
        self.chosen = []               # [(family, type)] in the order they were ticked
        for pair in (selected or []):
            key = (as_text(pair[0]), as_text(pair[1]) or u"*")
            if key[0] and key not in self.chosen:
                self.chosen.append(key)

        self.window, self.find, self.chrome = sb_ui.open_window("SbPicker.xaml", palette_name, owner,
                                                                close_on_escape=True)
        self.find("TxtTitle").Text = as_text(title)

        self.lst = self.find("LstRows")
        self.txt_search = self.find("TxtSearch")
        self.cmb_category = self.find("CmbCategory")
        self.chk_used = self.find("ChkUsed")
        self.chk_types = self.find("ChkTypes")
        self.txt_info = self.find("TxtInfo")
        self.btn_all = self.find("BtnAll")
        self.btn_none = self.find("BtnNone")

        categories = sorted(set([r["category"] for r in rows]), key=lambda c: c.lower())
        self.cmb_category.Items.Add(u"(all categories)")
        for cat in categories:
            self.cmb_category.Items.Add(cat)
        self.cmb_category.SelectedIndex = 0
        if current and current.get("category") in categories:
            sb_ui.select_text(self.cmb_category, current["category"])

        self.chk_used.IsChecked = True
        split = True
        if self.multi:
            # open on whichever shape most of the ticked pairs are in
            whole = len([p for p in self.chosen if p[1] == u"*"])
            split = whole <= (len(self.chosen) - whole)
        elif current and current.get("type") == u"*":
            split = False
        self.chk_types.IsChecked = split
        if not allow_family:
            self.chk_types.IsChecked = True
            self.chk_types.IsEnabled = False

        if self.multi:
            self.find("TxtHint").Text = (
                u"tick every family this detail item stands for - double-click a row to tick it")
            self.find("BtnOk").Content = u"Use ticked"
        else:
            self.btn_all.Visibility = Visibility.Collapsed
            self.btn_none.Visibility = Visibility.Collapsed

        self.txt_search.TextChanged += self.on_filter
        self.cmb_category.SelectionChanged += self.on_filter
        self.chk_used.Click += self.on_filter
        self.chk_types.Click += self.on_filter
        self.btn_all.Click += self.on_all
        self.btn_none.Click += self.on_none
        self.lst.MouseDoubleClick += self.on_double_click
        self.find("BtnOk").Click += self.on_ok
        self.find("BtnClear").Click += self.on_clear
        self.find("BtnCancel").Click += self.on_cancel
        self.fill()
        try:
            self.txt_search.Focus()
        except Exception:
            pass

    # -- ticks --------------------------------------------------------------

    def key_of(self, row):
        return (row["family"], row["type"])

    def harvest_ticks(self):
        """Read the ticks of the rows on screen back into the selection,
        leaving anything ticked under a different filter alone."""
        if not self.multi:
            return
        for index, row in enumerate(self.shown):
            if index >= len(self.ticks):
                break
            key = self.key_of(row)
            if self.ticks[index].IsChecked:
                if key not in self.chosen:
                    self.chosen.append(key)
            elif key in self.chosen:
                self.chosen.remove(key)

    # -- list ---------------------------------------------------------------

    def fill(self):
        self.lst.Items.Clear()
        self.shown = []
        self.ticks = []
        needle = as_text(self.txt_search.Text).strip().lower()
        category = sb_ui.combo_text(self.cmb_category)
        if category.startswith(u"("):
            category = u""
        used_only = bool(self.chk_used.IsChecked)
        by_type = bool(self.chk_types.IsChecked)
        for row in self.rows:
            if by_type and row["type"] == u"*":
                continue
            if not by_type and row["type"] != u"*":
                continue
            if category and row["category"] != category:
                continue
            if used_only and row["count"] <= 0:
                continue
            haystack = (row["category"] + u" " + row["family"] + u" " + row["type"]).lower()
            if needle and any([word not in haystack for word in needle.split()]):
                continue
            self.shown.append(row)
        self.shown.sort(key=lambda r: (r["category"].lower(), r["family"].lower(), natural_key(r["type"])))
        for row in self.shown:
            line = sb_ui.grid([sb_ui.pixels(26), sb_ui.pixels(150), sb_ui.star(1),
                               sb_ui.pixels(200), sb_ui.pixels(50)])
            if self.multi:
                tick = sb_ui.check(u"", self.key_of(row) in self.chosen)
                sb_ui.place(line, tick, 0)
                self.ticks.append(tick)
            cat_label = sb_ui.label(row["category"], margin=(0, 0, 6, 0))
            sb_ui.colour(cat_label, "BlueBrush")
            sb_ui.place(line, cat_label, 1)
            sb_ui.place(line, sb_ui.label(row["family"], margin=(0, 0, 6, 0)), 2)
            type_text = u"(all types)" if row["type"] == u"*" else row["type"]
            sb_ui.place(line, sb_ui.label(type_text, dim=True, margin=(0, 0, 6, 0)), 3)
            qty = sb_ui.label(as_text(row["count"]), dim=True)
            if row["count"] == 0:
                sb_ui.colour(qty, "RedBrush")
            qty.HorizontalAlignment = HorizontalAlignment.Right
            sb_ui.place(line, qty, 4)
            self.lst.Items.Add(sb_ui.list_item(line))
        self.report()

    def report(self):
        text = u"{0} of {1} shown".format(len(self.shown), len(self.rows))
        if self.multi:
            on_screen = [self.key_of(r) for r in self.shown]
            hidden = len([p for p in self.chosen if p not in on_screen])
            text += u"   |   {0} ticked".format(len(self.chosen))
            if hidden:
                text += u" ({0} not on screen under this filter)".format(hidden)
        self.txt_info.Text = text

    # -- events -------------------------------------------------------------

    def on_filter(self, sender, args):
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

    def on_double_click(self, sender, args):
        try:
            index = self.lst.SelectedIndex
            if index < 0 or index >= len(self.shown):
                return
            if self.multi:
                self.ticks[index].IsChecked = not self.ticks[index].IsChecked
                self.harvest_ticks()
                self.report()
            else:
                self.on_ok(sender, args)
        except Exception:
            pass

    def on_ok(self, sender, args):
        try:
            if self.multi:
                self.harvest_ticks()
                if not self.chosen:
                    self.txt_info.Text = u"Nothing ticked - tick a family, or press Clear to empty this row."
                    return
                self.result = list(self.chosen)
            else:
                index = self.lst.SelectedIndex
                if index < 0 or index >= len(self.shown):
                    self.txt_info.Text = u"Highlight a row first."
                    return
                self.result = self.shown[index]
            self.picked = True
            self.window.Close()
        except Exception:
            pass

    def on_clear(self, sender, args):
        self.result = [] if self.multi else {}
        self.picked = True
        self.window.Close()

    def on_cancel(self, sender, args):
        self.window.Close()

    def show(self):
        self.window.ShowDialog()
        return self.result if self.picked else None
