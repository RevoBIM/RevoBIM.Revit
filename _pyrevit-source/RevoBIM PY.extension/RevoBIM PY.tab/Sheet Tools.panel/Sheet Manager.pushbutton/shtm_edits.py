# -*- coding: utf-8 -*-
"""Editing sheets in the table: the bulk edit dialog and the write.

The dialog produces pending edits and hands them to the window's EditStore;
nothing here touches Revit. The EditHandler is the one thing that does, and it
does it the way every write in this extension does: borrowed first, one
transaction with a failure sink, and every value read back afterwards.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import shtm_core
import shtm_edit
import shtm_model
import shtm_ui
from shtm_ui import ui_safe, styled

from System.Windows import Visibility
from System.Windows.Controls import ListBoxItem, CheckBox

from Autodesk.Revit.UI import IExternalEventHandler
from Autodesk.Revit.DB import TransactionStatus

import shtm_dup


# ====================== the write ======================

class EditHandler(IExternalEventHandler):
    """Writes the pending edits. One transaction: these are cell edits, and a
    half-applied find and replace is worse than none."""

    def __init__(self):
        self.job = None
        self.done = None

    def Execute(self, uiapp):
        job = self.job
        self.job = None
        if job is None:
            return
        report = {"written": 0, "problems": [], "debug": []}
        try:
            document, refused = shtm_ui.job_document(uiapp, job)
            if refused:
                raise Exception(refused)
            report = apply_edits(document, job["edits"], bool(job.get("debug")))
        except Exception as exc:
            report["problems"].append(u"the edits were not applied: {0}".format(exc))
        if self.done is not None:
            try:
                self.done(report)
            except Exception as exc:
                shtm_ui.log(u"edit results failed: {0}".format(exc))

    def GetName(self):
        return "RevoBIM Sheet Manager - apply edits"


def apply_edits(doc, edits, debug=False):
    report = {"written": 0, "problems": [], "debug": [], "notes": [],
              "refused": []}

    def trace(text):
        if debug:
            report["debug"].append(u"{0}".format(text))

    ids = sorted(set([e["id"] for e in edits]))
    trace(u"{0} edit(s) on {1} sheet(s)".format(len(edits), len(ids)))

    if shtm_model.is_workshared(doc):
        # borrow first, then ask again at the moment of writing - element
        # ownership and workset ownership are two different locks
        shtm_model.borrow(doc, ids)
        held = {}
        for sheet_id in ids:
            sheet = doc.GetElement(shtm_model.new_element_id(sheet_id))
            if sheet is None:
                continue
            reason = shtm_model.locked_by(doc, sheet)
            if reason:
                held[sheet_id] = reason
                report["problems"].append(
                    u"{0}: {1} - its edits were skipped".format(
                        shtm_model.element_sheet_number(sheet), reason))
        edits = [e for e in edits if e["id"] not in held]

    failures = []
    transaction = shtm_dup.start(doc, "RevoBIM - edit sheets", failures)
    try:
        for edit in edits:
            sheet = doc.GetElement(shtm_model.new_element_id(edit["id"]))
            if sheet is None:
                report["problems"].append(
                    u"sheet {0} could not be read".format(edit["id"]))
                continue
            column = edit["column"]
            value = edit["value"]
            label = shtm_model.element_sheet_number(sheet)
            trace(u"  {0} / {1}: '{2}' -> '{3}'".format(
                label, column, edit.get("was", u""), value))
            try:
                if column == shtm_edit.NUMBER:
                    sheet.SheetNumber = value
                elif column == shtm_edit.NAME:
                    if not shtm_dup.set_element_name(sheet, value):
                        report["problems"].append(
                            u"{0}: the name would not take".format(label))
                else:
                    ok, problem = shtm_dup.write_text(sheet, column, value)
                    if not ok:
                        report["problems"].append(u"{0}: {1}".format(label, problem))
            except Exception as exc:
                report["problems"].append(u"{0} / {1}: {2}".format(
                    label, column, shtm_dup._plainly(exc)))
        status = transaction.Commit()
    except Exception as exc:
        try:
            transaction.RollBack()
        except Exception:
            pass
        report["problems"].append(u"the edits were rolled back: {0}".format(
            shtm_dup._plainly(exc)))
        for line in failures:
            trace(u"  Revit said: {0}".format(line))
        return report
    for line in failures:
        trace(u"  Revit said: {0}".format(line))
    if status != TransactionStatus.Committed:
        report["problems"].append(u"Revit reported {0}{1}".format(
            status, shtm_dup._because(failures)))
        return report

    # ---- prove it ----
    try:
        doc.Regenerate()
    except Exception:
        pass
    wrong = 0
    for edit in edits:
        sheet = doc.GetElement(shtm_model.new_element_id(edit["id"]))
        if sheet is None:
            continue
        got = _read(sheet, edit["column"])
        if got == edit["value"]:
            report["written"] += 1
        else:
            wrong += 1
            reason = u"wrote '{0}' but read back '{1}'".format(edit["value"], got)
            report["problems"].append(u"{0} / {1}: {2}".format(
                shtm_model.element_sheet_number(sheet), edit["column"], reason))
            # the cell stays pending and paints strong red, so it can be
            # looked at rather than only read about in a results window
            report["refused"].append({"id": edit["id"], "column": edit["column"],
                                      "reason": reason})
    trace(u"{0} written, {1} did not take".format(report["written"], wrong))
    return report


def _read(sheet, column):
    try:
        if column == shtm_edit.NUMBER:
            return u"{0}".format(sheet.SheetNumber)
        if column == shtm_edit.NAME:
            return u"{0}".format(shtm_model.element_name(sheet))
        return shtm_model.param_text(shtm_model.find_parameter(sheet, column))
    except Exception:
        return None


# ====================== the dialog ======================

class EditDialog(object):
    """Find and replace, prefix and suffix, fill down - over the selected rows
    or every row shown, in the ticked columns, with a preview of what it would
    do before it is added to the pending edits."""

    def __init__(self, settings, columns, selected, shown, store, mode,
                 owner=None):
        self.columns = list(columns)
        self.selected = list(selected)
        self.shown = list(shown)
        self.store = store
        self.mode = mode
        self.owner = owner
        self.result = []
        self.tab_name = "replace"
        self.window = shtm_ui.load_window("ShtmEdit.xaml", mode)
        self.find = self.window.FindName
        self.chrome = shtm_ui.Chrome(self.window)
        shtm_ui.load_icon(self.find("LogoImage"))
        shtm_ui.attach_egg(self.window, self.find("LogoHost"), self.mode)
        self.find("VersionText").Text = u"v{0}".format(shtm_core.__version__)
        self.boxes = {}
        self._fill_columns()
        self._wire()

    def _fill_columns(self, needle=u""):
        listing = self.find("ColumnList")
        listing.Items.Clear()
        needle = (needle or u"").lower()
        for name in self.columns:
            if needle and needle not in name.lower():
                continue
            item = ListBoxItem()
            styled(item, "Lst.Item")
            box = self.boxes.get(name)
            if box is None:
                box = CheckBox()
                box.Content = name
                styled(box, "Chk.Flat")
                box.IsChecked = (name == shtm_edit.NAME)
                box.Checked += ui_safe(self._refresh)
                box.Unchecked += ui_safe(self._refresh)
                self.boxes[name] = box
            try:
                parent = box.Parent
                if parent is not None:
                    parent.Content = None
            except Exception:
                pass
            item.Content = box
            listing.Items.Add(item)

    def _wire(self):
        self.find("CloseBtn").Click += ui_safe(lambda s, e: self.window.Close())
        self.find("CancelBtn").Click += ui_safe(lambda s, e: self.window.Close())
        self.find("AddBtn").Click += ui_safe(self._add)
        self.find("TabReplace").Click += ui_safe(lambda s, e: self.tab("replace"))
        self.find("TabAffix").Click += ui_safe(lambda s, e: self.tab("affix"))
        self.find("TabFill").Click += ui_safe(lambda s, e: self.tab("fill"))

        scope_selected = self.find("ScopeSelected")
        scope_shown = self.find("ScopeShown")
        scope_selected.Content = u"The selected rows ({0})".format(len(self.selected))
        scope_shown.Content = u"Every row shown ({0})".format(len(self.shown))
        if self.selected:
            scope_selected.IsChecked = True
        else:
            scope_shown.IsChecked = True
            scope_selected.IsEnabled = False
        for control in (scope_selected, scope_shown):
            control.Checked += ui_safe(self._refresh)

        self.find("ColumnSearch").TextChanged += ui_safe(
            lambda s, e: self._fill_columns(s.Text))
        for name in ("FindBox", "ReplaceBox", "PrefixBox", "SuffixBox", "FillBox"):
            self.find(name).TextChanged += ui_safe(self._refresh)
        self.find("MatchCase").Checked += ui_safe(self._refresh)
        self.find("MatchCase").Unchecked += ui_safe(self._refresh)
        self.tab("replace")

    def tab(self, which):
        self.tab_name = which
        panes = {"replace": "ReplacePane", "affix": "AffixPane", "fill": "FillPane"}
        buttons = {"replace": "TabReplace", "affix": "TabAffix", "fill": "TabFill"}
        for key in panes:
            self.find(panes[key]).Visibility = (
                Visibility.Visible if key == which else Visibility.Collapsed)
        for key in buttons:
            self.find(buttons[key]).SetResourceReference(
                _foreground(), "OrangeBrush" if key == which else "MutedBrush")
        self._refresh(None, None)

    def _sheets(self):
        if self.find("ScopeSelected").IsChecked and self.selected:
            return self.selected
        return self.shown

    def _columns(self):
        return [name for name in self.columns
                if name in self.boxes and self.boxes[name].IsChecked]

    def _edits(self):
        sheets = self._sheets()
        columns = self._columns()
        if self.tab_name == "replace":
            return shtm_edit.find_replace(
                sheets, columns, self.find("FindBox").Text or u"",
                self.find("ReplaceBox").Text or u"",
                bool(self.find("MatchCase").IsChecked), self.store)
        if self.tab_name == "affix":
            return shtm_edit.affix(
                sheets, columns, self.find("PrefixBox").Text or u"",
                self.find("SuffixBox").Text or u"", self.store)
        edits = []
        for column in columns:
            edits.extend(shtm_edit.fill_down(
                sheets, column, self.find("FillBox").Text or u"", self.store))
        return edits

    @ui_safe
    def _refresh(self, sender, event):
        edits = self._edits()
        columns = self._columns()
        lines = []
        if not columns:
            lines.append(u"tick at least one column")
        elif not edits:
            lines.append(u"nothing would change")
        else:
            lines.append(u"{0} cell(s) would change:".format(len(edits)))
            lines.append(u"")
            for sheet_id, column, was, new in edits[:40]:
                lines.append(u"{0}".format(column))
                lines.append(u"   {0}".format(was))
                lines.append(u"   \u2192 {0}".format(new))
            if len(edits) > 40:
                lines.append(u"... and {0} more".format(len(edits) - 40))
        self.find("PreviewText").Text = u"\n".join(lines)
        button = self.find("AddBtn")
        button.IsEnabled = bool(edits)
        button.Content = (u"Add {0} edit(s)".format(len(edits)) if edits
                          else u"Add to pending edits")
        self.find("StatusText").Text = (
            u"{0} sheet(s) in scope, {1} column(s) ticked".format(
                len(self._sheets()), len(columns)))

    @ui_safe
    def _add(self, sender, event):
        self.result = self._edits()
        self.window.Close()

    def show(self):
        if self.owner is not None:
            try:
                shtm_ui.bring_back(self.owner)
                self.window.Owner = self.owner
            except Exception:
                pass
        self.window.ShowDialog()
        return self.result


def _foreground():
    from System.Windows.Controls import Control
    return Control.ForegroundProperty
