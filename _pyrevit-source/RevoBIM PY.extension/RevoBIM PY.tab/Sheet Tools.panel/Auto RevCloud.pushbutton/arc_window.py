# -*- coding: utf-8 -*-
"""Auto RevCloud - the window: the links on the left, the views to check on
the right, revisions along the bottom, Compare in the footer."""
import os
import sys
import time

import arc_clr  # noqa: F401
import arc_compare
import arc_core
import arc_diff
import arc_model
import arc_ops
import arc_ui
import settings_window

from Microsoft.Win32 import OpenFileDialog
from System.Windows import GridLength, Visibility, Clipboard
from System.Diagnostics import Process

# The open window, parked here so the persistent engine keeps it alive.
OPEN = [None]

SHEET_WIDTHS = [28, 88, u"*", 74, 104, 104]


# ==========================================================================
# the sheet picker
# ==========================================================================

SHOW_OPTIONS = [(u"CloudAndTagVisible", u"Cloud and Tag"),
                (u"TagVisible", u"Tag only"),
                (u"Hidden", u"None")]

# The pre-2022 fallback, used only where the release has no numbering
# sequence elements to offer.
NUMBER_TYPES = [(u"Numeric", u"Numeric"),
                (u"Alphanumeric", u"Alphanumeric"),
                (u"None", u"None")]


class NewRevisionDialog(object):
    """The fields Revit's own Sheet Issues/Revisions dialog carries.

    Returns a details dict, or None. It creates nothing itself - see
    RevisionPicker.on_new for why a modal dialog must not.
    """

    def __init__(self, owner, sequences, next_sequence, palette, existing=None):
        self.palette = palette
        self.sequences = sequences
        self.existing = existing
        self.result = None
        self.window = arc_ui.load_window(u"ArcNewRevision.xaml")
        arc_ui.apply_palette(self.window, palette)
        self.find = self.window.FindName
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass
        arc_ui.Chrome(self.window, escape_closes=True)
        self.find(u"OkButton").Click += self.on_ok
        self.find(u"CancelButton").Click += self.on_cancel
        combo = self.find(u"NumberingCombo")
        combo.Items.Clear()
        if sequences:
            for _id, name in sequences:
                combo.Items.Add(name)
        else:
            for _key, label in NUMBER_TYPES:
                combo.Items.Add(label)
        combo.SelectedIndex = 0

        show = self.find(u"ShowCombo")
        show.Items.Clear()
        for _key, label in SHOW_OPTIONS:
            show.Items.Add(label)
        show.SelectedIndex = 0

        if existing:
            self.load_existing(existing, sequences)
        else:
            self.find(u"DateBox").Text = time.strftime(u"%d/%m/%Y")
            self.find(u"SequenceText").Text = u"{0} (set by Revit)".format(
                next_sequence)

    def load_existing(self, existing, sequences):
        """Fill the form from a revision already in the project."""
        self.find(u"TitleText").Text = u"Edit revision"
        self.find(u"OkButton").Content = u"Save"
        self.find(u"SequenceText").Text = u"{0}".format(existing.get(u"seq", u""))
        self.find(u"DateBox").Text = existing.get(u"date", u"")
        self.find(u"DescriptionBox").Text = existing.get(u"description", u"")
        self.find(u"IssuedByBox").Text = existing.get(u"issued_by", u"")
        self.find(u"IssuedToBox").Text = existing.get(u"issued_to", u"")
        self.find(u"IssuedCheck").IsChecked = bool(existing.get(u"issued"))

        wanted = arc_core.unicode_str(existing.get(u"visibility", u""))
        for index, (key, _label) in enumerate(SHOW_OPTIONS):
            if key == wanted:
                self.find(u"ShowCombo").SelectedIndex = index
                break

        sequence_id = existing.get(u"sequence_id", 0)
        if sequence_id and sequences:
            for index, (identifier, _name) in enumerate(sequences):
                if identifier == sequence_id:
                    self.find(u"NumberingCombo").SelectedIndex = index
                    break

        if existing.get(u"issued"):
            # Revit refuses edits to an issued revision, so say so before the
            # Save rather than reporting a list of fields that would not take.
            self.find(u"IssuedWarning").Text = (
                u"This revision is issued. Revit will refuse changes to it - "
                u"untick Issued to edit it, which is written first so the rest "
                u"can follow.")

    def on_ok(self, sender, args):
        description = arc_core.unicode_str(self.find(u"DescriptionBox").Text).strip()
        if not description:
            self.find(u"StatusText").Text = u"A revision needs a description."
            return
        index = max(0, self.find(u"NumberingCombo").SelectedIndex)
        details = {
            u"id": (self.existing or {}).get(u"id", 0),
            u"description": description,
            u"date": arc_core.unicode_str(self.find(u"DateBox").Text).strip(),
            u"issued_by": arc_core.unicode_str(self.find(u"IssuedByBox").Text).strip(),
            u"issued_to": arc_core.unicode_str(self.find(u"IssuedToBox").Text).strip(),
            u"issued": bool(self.find(u"IssuedCheck").IsChecked),
            u"visibility": SHOW_OPTIONS[max(0, self.find(u"ShowCombo").SelectedIndex)][0],
            u"sequence_id": self.sequences[index][0] if self.sequences else 0,
            u"number_type": None if self.sequences else NUMBER_TYPES[index][0],
        }
        self.result = details
        self.close()

    def on_cancel(self, sender, args):
        self.result = None
        self.close()

    def close(self):
        try:
            self.window.DialogResult = True
            return
        except Exception:
            pass
        try:
            self.window.Close()
        except Exception:
            pass

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            return None
        return self.result


class RevisionPicker(object):
    """Pick one revision, for assigning to a row or a set of rows.

    Issued revisions are listed but cannot be picked - Revit will not put a
    cloud on one, and finding that out per view after a five minute run is not
    a report.
    """

    def __init__(self, owner, rows, current, palette, title=None,
                 sequences=None):
        self.rows = [r for r in rows]
        self.palette = palette
        self.sequences = sequences or []
        self.next_sequence = max([r.get(u"seq", 0) for r in rows] or [0]) + 1
        self.result = None
        self.picked_id = current
        self.window = arc_ui.load_window(u"ArcRevisionPicker.xaml")
        arc_ui.apply_palette(self.window, palette)
        self.find = self.window.FindName
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass
        arc_ui.Chrome(self.window, escape_closes=True)
        self.list = self.find(u"RevList")
        self.find(u"OkButton").Click += self.on_ok
        self.find(u"CancelButton").Click += self.on_cancel
        self.find(u"ClearButton").Click += self.on_clear
        self.find(u"NewButton").Click += self.on_new
        self.find(u"EditButton").Click += self.on_edit
        if title:
            try:
                self.find(u"PickerTitle").Text = title
            except Exception:
                pass
        self.fill()

    def fill(self):
        self.list.Items.Clear()
        for row in self.rows:
            issued = row.get(u"issued")
            mark = u"\u25cf" if row[u"id"] == self.picked_id else u""
            item = arc_ui.make_row(
                self.window, [22, 60, u"*", 110, 70],
                [mark, row.get(u"seq", u""), row.get(u"description", u""),
                 row.get(u"date", u""), u"issued" if issued else u""],
                [u"OrangeBrush", u"MutedBrush", None, u"MutedBrush",
                 u"RedBrush" if issued else None])
            item.MouseLeftButtonUp += self.on_click
            self.list.Items.Add(item)

    def on_click(self, sender, args):
        try:
            index = self.list.SelectedIndex
        except Exception:
            return
        if index < 0 or index >= len(self.rows):
            return
        row = self.rows[index]
        if row.get(u"issued"):
            self.find(u"StatusText").Text = (
                u"That revision is issued - Revit will not add a cloud to it.")
            return
        self.picked_id = row[u"id"]
        self.fill()

    def on_ok(self, sender, args):
        self.result = (self.picked_id or 0)
        self.close()

    def on_clear(self, sender, args):
        """Back to whatever the rest of the rows are using."""
        self.result = 0
        self.close()

    def on_edit(self, sender, args):
        """Edit the highlighted revision. Same form, prefilled."""
        try:
            index = self.list.SelectedIndex
        except Exception:
            index = -1
        if index < 0 or index >= len(self.rows):
            self.find(u"StatusText").Text = u"Highlight a revision to edit it."
            return
        existing = self.rows[index]
        dialog = NewRevisionDialog(self.window, self.sequences,
                                   self.next_sequence, self.palette,
                                   existing=existing)
        details = dialog.show()
        if not details:
            return
        self.result = (u"edit", details)
        self.close()

    def on_new(self, sender, args):
        """Ask for the description and hand it back for the window to create.

        The picker does NOT create the revision itself. It is a modal dialog,
        and creating a revision is a model write that has to go out through
        the ExternalEvent - which Revit raises on this very thread. Blocking a
        modal dialog waiting for it is a deadlock, and this extension has
        written that down once already. So the details come back and the main
        window, which is not blocked, does the work.
        """
        dialog = NewRevisionDialog(self.window, self.sequences,
                                   self.next_sequence, self.palette)
        details = dialog.show()
        if not details:
            return
        self.result = (u"new", details)
        self.close()

    def on_cancel(self, sender, args):
        self.result = None
        self.close()

    def close(self):
        try:
            self.window.DialogResult = True
            return
        except Exception:
            pass
        try:
            self.window.Close()
        except Exception:
            pass

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            return None
        return self.result


class CategoryPicker(object):
    """Tick the categories to compare in one view.

    Selection is the ListBox's own Extended mode, so click, shift-click for a
    run and ctrl-click to add all behave the way Windows says they should
    without any of it being reimplemented - the tick follows the selection.
    """

    def __init__(self, owner, rows, chosen, palette, title=None):
        self.rows = rows
        self.shown = []
        self.result = None
        self.result_template = None
        self.palette = palette
        self.window = arc_ui.load_window(u"ArcCategoryPicker.xaml")
        arc_ui.apply_palette(self.window, palette)
        self.find = self.window.FindName
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass
        arc_ui.Chrome(self.window, escape_closes=True)
        self.list = self.find(u"CategoryList")
        self.find(u"SearchBox").TextChanged += self.safe(self.on_filter)
        self.find(u"AllButton").Click += self.safe(self.on_all)
        self.find(u"NoneButton").Click += self.safe(self.on_none)
        self.find(u"DefaultButton").Click += self.safe(self.on_default)
        self.find(u"SaveTemplateButton").Click += self.safe(self.on_save_template)
        self.find(u"DeleteTemplateButton").Click += self.safe(self.on_delete_template)
        self.find(u"OkButton").Click += self.safe(self.on_ok)
        self.find(u"CancelButton").Click += self.safe(self.on_cancel)
        self.chosen = set(arc_core.unicode_str(c).lower() for c in chosen)
        self.templates = arc_core.load_templates()
        self.applied = None      # the template the ticks came from, if any
        self.loading = False
        self.fill_templates()
        self.find(u"TemplateCombo").SelectionChanged += self.safe(self.on_template)
        if title:
            try:
                self.find(u"PickerTitle").Text = title
            except Exception:
                pass
        self.fill()

    def safe(self, handler):
        """Wrap a handler so a failure is reported, not swallowed.

        WPF eats an exception thrown inside an event closure. The button then
        does nothing at all and looks broken, with nothing anywhere saying
        why - which is exactly how "Use these does not close the window"
        presents. Every handler in this window goes through here.
        """
        def wrapped(sender, args, _handler=handler):
            try:
                _handler(sender, args)
            except Exception:
                try:
                    self.find(u"StatusText").Text = u"That did not work: {0}".format(
                        arc_core.describe_exception(sys.exc_info()[1]))
                except Exception:
                    pass
        return wrapped

    # ---- templates -----------------------------------------------------
    def fill_templates(self, select=None):
        """Rebuild the template list without the rebuild counting as a pick."""
        self.loading = True
        try:
            combo = self.find(u"TemplateCombo")
            combo.Items.Clear()
            combo.Items.Add(u"(none)")
            for name, _values in self.templates:
                combo.Items.Add(name)
            combo.SelectedIndex = 0
            if select:
                for index in range(combo.Items.Count):
                    if arc_core.unicode_str(combo.Items[index]) == select:
                        combo.SelectedIndex = index
                        break
        finally:
            self.loading = False

    def on_template(self, sender, args):
        if self.loading:
            return
        combo = self.find(u"TemplateCombo")
        if combo.SelectedIndex <= 0:
            return
        name = arc_core.unicode_str(combo.SelectedItem)
        values = arc_core.template_named(self.templates, name)
        if values is None:
            return
        self.chosen = set(arc_core.unicode_str(v).lower() for v in values)
        self.applied = name
        self.fill()

    def on_save_template(self, sender, args):
        picked = [r[u"name"] for r in self.rows
                  if r[u"name"].lower() in self.chosen]
        if not picked:
            self.find(u"StatusText").Text = u"Nothing is ticked to save."
            return
        name = arc_ui.ask_text(self.window, u"Save category template",
                               u"Name for this template:",
                               palette=self.palette)
        if not name:
            return
        self.templates = arc_core.put_template(self.templates, name, picked)
        if arc_core.save_templates(self.templates):
            self.applied = name.strip()
            self.fill_templates(select=name.strip())
            self.find(u"StatusText").Text = u"Saved '{0}' with {1} category(ies).".format(
                name.strip(), len(picked))
        else:
            self.find(u"StatusText").Text = u"That template could not be saved."

    def on_delete_template(self, sender, args):
        combo = self.find(u"TemplateCombo")
        if combo.SelectedIndex <= 0:
            self.find(u"StatusText").Text = u"Pick a template to delete first."
            return
        name = arc_core.unicode_str(combo.SelectedItem)
        self.templates = arc_core.drop_template(self.templates, name)
        arc_core.save_templates(self.templates)
        self.fill_templates()
        self.find(u"StatusText").Text = u"Deleted '{0}'.".format(name)

    def visible_rows(self):
        text = self.find(u"SearchBox").Text.strip().lower()
        words = [w for w in text.split() if w]
        out = []
        for row in self.rows:
            hay = row[u"name"].lower()
            if all(word in hay for word in words):
                out.append(row)
        return out

    def fill(self):
        self.list.Items.Clear()
        self.shown = self.visible_rows()
        for row in self.shown:
            ticked = row[u"name"].lower() in self.chosen
            item = arc_ui.make_row(
                self.window, [26, u"*"],
                [u"\u2713" if ticked else u"", row[u"name"]],
                [u"GreenBrush" if ticked else u"MutedBrush", None])
            item.MouseLeftButtonUp += self.safe(self.on_click)
            self.list.Items.Add(item)
        self.report()

    def report(self):
        ticked = len([r for r in self.rows if r[u"name"].lower() in self.chosen])
        self.find(u"StatusText").Text = (
            u"{0} ticked, {1} shown of {2} categories. Click to tick, "
            u"shift-click for a run.".format(
                ticked, len(self.shown), len(self.rows)))

    def on_click(self, sender, args):
        # The ListBox has already worked out the selection - click, shift for
        # a run, ctrl to add - so the tick just follows it.
        picked = []
        for index in range(len(self.shown)):
            try:
                if self.list.Items[index].IsSelected:
                    picked.append(self.shown[index][u"name"])
            except Exception:
                continue
        if not picked:
            return
        arc_compare.toggle_ticks(self.chosen, picked)
        # Ticking by hand means these are no longer that template's
        # categories, and the row must not go on claiming they are.
        self.applied = None
        self.fill()

    def on_filter(self, sender, args):
        self.fill()

    def on_all(self, sender, args):
        for row in self.visible_rows():
            self.chosen.add(row[u"name"].lower())
        self.applied = None
        self.fill()

    def on_none(self, sender, args):
        for row in self.visible_rows():
            self.chosen.discard(row[u"name"].lower())
        self.applied = None
        self.fill()

    def on_default(self, sender, args):
        self.chosen = set(n.lower() for n in arc_core.DEFAULT_CATEGORIES)
        self.applied = None
        self.fill()

    def on_ok(self, sender, args):
        # Reported in the model's own spelling, not lower case.
        self.result = [r[u"name"] for r in self.rows
                       if r[u"name"].lower() in self.chosen]
        self.result_template = self.applied
        self.close()

    def on_cancel(self, sender, args):
        self.result = None
        self.close()

    def close(self):
        """Close a modal window, both ways round.

        DialogResult is what actually ends a ShowDialog, and setting it closes
        the window on its own; Close() is the fallback for the case where the
        window was not shown modally. Doing only one of the two is a window
        that will not shut on somebody's machine.
        """
        try:
            self.window.DialogResult = True
            return
        except Exception:
            pass
        try:
            self.window.Close()
        except Exception:
            pass

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            return None
        return self.result


class SheetPicker(object):
    """Modal multi-select over sheets, or over views.  show() returns a list
    of row dicts or []."""

    def __init__(self, owner, all_sheets, already, palette, title=None):
        self.all_sheets = all_sheets
        self.already = set(already)
        self.result = []
        self.window = arc_ui.load_window(u"ArcSheetPicker.xaml")
        arc_ui.apply_palette(self.window, palette)
        self.find = self.window.FindName
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass
        arc_ui.Chrome(self.window, escape_closes=True)
        self.list = self.find(u"SheetList")
        self.find(u"SearchBox").TextChanged += self.on_filter
        self.find(u"HideAddedCheck").Click += self.on_filter
        self.find(u"AllButton").Click += self.on_all
        self.find(u"NoneButton").Click += self.on_none
        self.find(u"AddButton").Click += self.on_add
        self.find(u"CancelButton").Click += self.on_cancel
        self.list.MouseDoubleClick += self.on_add
        if title:
            try:
                self.find(u"PickerTitle").Text = title
            except Exception:
                pass
        self.fill()

    # ---- templates -----------------------------------------------------
    def visible_rows(self):
        text = self.find(u"SearchBox").Text.strip().lower()
        words = [w for w in text.split() if w]
        hide = bool(self.find(u"HideAddedCheck").IsChecked)
        rows = []
        for row in self.all_sheets:
            if hide and row[u"number"] in self.already:
                continue
            hay = (row[u"number"] + u" " + row[u"name"]).lower()
            if all(w in hay for w in words):
                rows.append(row)
        return rows

    def fill(self):
        self.list.Items.Clear()
        rows = self.visible_rows()
        for row in rows:
            item = arc_ui.make_row(self.window, [110, u"*"], [row[u"number"], row[u"name"]])
            item.Tag = row
            self.list.Items.Add(item)
        self.find(u"StatusText").Text = u"{0} sheet(s) shown. Click, shift-click for a run, ctrl-click to add or remove.".format(len(rows))

    def on_filter(self, sender, args):
        self.fill()

    def on_all(self, sender, args):
        self.list.SelectAll()

    def on_none(self, sender, args):
        self.list.UnselectAll()

    def on_add(self, sender, args):
        picked = []
        for item in self.list.SelectedItems:
            picked.append(dict(item.Tag))
        picked.sort(key=lambda r: arc_core.natural_key(r[u"number"]))
        self.result = picked
        self.window.Close()

    def on_cancel(self, sender, args):
        self.result = []
        self.window.Close()

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            return []
        return self.result


# ==========================================================================
# the main window
# ==========================================================================

class MainWindow(object):

    def __init__(self, uiapp, settings, icon_path):
        self.uiapp = uiapp
        self.settings = settings
        self.icon_path = icon_path
        self.sheet_rows = []
        self.revision_rows = []
        self.revision_id = 0
        self.all_sheets = []
        self.busy = False
        self.clouded_ids = []
        self.close_when_done = False
        self.debug_lines = []
        self.link_rows = []
        self.link_id = 0
        self.link_loading = False
        self.undo_stack = []
        self.pending_revision_rows = []
        self.syncing = False
        self.palette = arc_model.resolve_theme(settings.get(u"theme", u"auto"))
        self.theme_hooked = False

        self.window = arc_ui.load_window(u"AutoRevCloud.xaml")
        arc_ui.apply_palette(self.window, self.palette)
        self.find = self.window.FindName
        self.chrome = arc_ui.Chrome(self.window, on_close=self.on_close)
        arc_ui.set_owner(self.window, uiapp)
        self.handler, self.event = arc_ops.make_event()

        icon = arc_ui.load_icon(icon_path)
        if icon is not None:
            try:
                self.find(u"HeaderIcon").Source = icon
                self.window.Icon = icon
            except Exception:
                pass

        self.sheet_list = self.find(u"SheetList")
        self.wire()
        self.update_theme_chip()
        self.read_project()
        self.reload_links()
        self.hook_revit_theme()

    # ---- wiring --------------------------------------------------------
    def wire(self):
        f = self.find
        f(u"ThemeButton").Click += self.on_theme_toggle
        f(u"SettingsButton").Click += self.on_settings
        f(u"ReloadLinksButton").Click += self.on_reload_links
        f(u"LinkCombo").SelectionChanged += self.on_link_picked
        f(u"AddSheetsButton").Click += self.on_add_sheets
        f(u"AutoSelectButton").Click += self.on_add_views
        f(u"AddViewsButton").Click += self.on_add_loose_views
        f(u"SetCategoriesButton").Click += self.on_set_categories
        f(u"SetRevisionButton").Click += self.on_set_revision
        f(u"UndoButton").Click += self.on_undo
        f(u"SheetUpButton").Click += self.on_sheet_up
        f(u"SheetDownButton").Click += self.on_sheet_down
        f(u"SheetRemoveButton").Click += self.on_sheet_remove
        f(u"SheetClearButton").Click += self.on_sheet_clear
        f(u"CompareButton").Click += self.on_compare
        f(u"CompletedButton").Click += self.on_completed
        f(u"DebugToggle").Click += self.on_debug_toggle
        f(u"DebugCopyButton").Click += self.on_debug_copy
        f(u"DebugHideButton").Click += self.on_debug_hide
        f(u"DebugLogButton").Click += self.on_debug_log
        self.sheet_list.SelectionChanged += self.on_sheet_selected
        self.window.SizeChanged += self.on_size_changed
        self.attach_egg()

    def attach_egg(self):
        """Wire the shared RevoBIM easter egg onto the header logo.

        Standing wiring for every tool in the extension: name the logo, attach
        here, and let the bench rule fail a rebuild that forgets. Guarded end
        to end - the egg is decoration, and decoration must never be able to
        take a tool down, whether the package is missing, older than this
        interface, or throwing.
        """
        try:
            from revobim.egg import egg_hook
        except Exception:
            return
        try:
            targets = []
            for name in (u"RevoBimLogo", u"HeaderIcon"):
                try:
                    element = self.find(name)
                except Exception:
                    element = None
                if element is not None:
                    targets.append(element)
            if not targets:
                return
            egg_hook.attach(targets, host_window=self.window,
                            theme=lambda: self.palette)
        except Exception:
            pass

    def show(self):
        self.window.Show()

    def on_close(self):
        if self.busy:
            self.status(u"A compare is running - wait for it to finish.")
            return False
        return True

    # ---- theme ---------------------------------------------------------
    def update_theme_chip(self):
        """The chip shows the mode it is IN, not the one it would switch to.

        Three states, because two of them leave no way back to following
        Revit: once the chip has been pressed the tool stops tracking the
        canvas, and with a two-way toggle there is nothing that turns it back
        on short of Settings.
        """
        chip = self.find(u"ThemeButton")
        label = self.find(u"ThemeLabel")
        mode = self.settings.get(u"theme", u"auto")
        if mode == u"auto":
            label.Text = u"Auto"
            chip.ToolTip = u"Following Revit's canvas ({0}). Click for Dark.".format(
                self.palette)
        elif mode == u"dark":
            label.Text = u"Dark"
            chip.ToolTip = u"Held dark. Click for Light."
        else:
            label.Text = u"Light"
            chip.ToolTip = u"Held light. Click to follow Revit again."

    def set_palette(self, name):
        self.palette = name
        arc_ui.apply_palette(self.window, name)
        self.update_theme_chip()

    def on_theme_toggle(self, sender, args):
        order = {u"auto": u"dark", u"dark": u"light", u"light": u"auto"}
        new = order.get(self.settings.get(u"theme", u"auto"), u"auto")
        self.settings[u"theme"] = new
        self.set_palette(arc_model.resolve_theme(new))
        try:
            arc_core.save_settings(self.settings)
        except Exception:
            pass

    def hook_revit_theme(self):
        """Follow Revit's canvas theme when settings say auto (2024+)."""
        if self.theme_hooked:
            return
        try:
            self.uiapp.ThemeChanged += self.on_revit_theme
            self.theme_hooked = True
        except Exception:
            self.theme_hooked = False

    def on_revit_theme(self, sender, args):
        try:
            if self.settings.get(u"theme", u"auto") != u"auto":
                return
            wanted = arc_model.resolve_theme(u"auto")
            if wanted != self.palette:
                self.set_palette(wanted)
        except Exception:
            pass

    def on_settings(self, sender, args):
        if self.busy:
            return
        before = self.palette
        dialog = settings_window.SettingsWindow(
            self.window, self.settings, self.palette,
            on_theme_change=lambda key: self.set_palette(arc_model.resolve_theme(key)))
        result = dialog.show()
        if result is None:
            self.set_palette(before)
            return
        self.settings = result
        self.set_palette(arc_model.resolve_theme(result.get(u"theme", u"auto")))
        self.status(u"Settings saved.")
        self.refresh_ready()

    # ---- helpers -------------------------------------------------------
    def status(self, text):
        try:
            self.find(u"StatusText").Text = text
        except Exception:
            pass

    def doc(self):
        return self.uiapp.ActiveUIDocument.Document

    def read_project(self):
        try:
            self.all_sheets = arc_model.sheets(self.doc())
        except Exception as exc:
            self.all_sheets = []
            self.status(u"Could not read the sheets: {0}".format(exc))
        self.load_revisions()
        self.refresh_ready()

    def on_size_changed(self, sender, args):
        self.set_progress(self.progress_value)

    progress_value = 0.0

    def set_progress(self, fraction):
        self.progress_value = fraction
        try:
            fill = self.find(u"ProgressFill")
            # Measured off the track, not the shell: the band is inset, so
            # using the window width overshoots and the bar reads full early.
            width = self.find(u"ProgressTrack").ActualWidth
            fill.Width = max(0.0, min(1.0, fraction)) * width
        except Exception:
            pass

    # ---- the debug bar -------------------------------------------------
    def set_debug(self, text):
        self.debug_lines = text
        try:
            self.find(u"DebugText").Text = text
        except Exception:
            pass

    def debug_visible(self):
        try:
            return self.find(u"DebugPanel").Visibility == Visibility.Visible
        except Exception:
            return False

    def show_debug(self, showing):
        try:
            self.find(u"DebugPanel").Visibility = (
                Visibility.Visible if showing else Visibility.Collapsed)
            self.find(u"DebugRow").Height = (
                GridLength(240) if showing else GridLength(0))
        except Exception:
            pass

    def on_debug_toggle(self, sender, args):
        self.show_debug(not self.debug_visible())

    def on_debug_hide(self, sender, args):
        self.show_debug(False)

    def on_debug_copy(self, sender, args):
        try:
            Clipboard.SetText(self.debug_lines or u"(nothing to copy yet)")
            self.status(u"Run detail copied to the clipboard.")
        except Exception:
            self.status(u"Could not reach the clipboard - select the text and copy it.")

    def on_debug_log(self, sender, args):
        try:
            Process.Start(u"explorer.exe", arc_core.appdata_dir())
        except Exception:
            self.status(u"The log is at {0}".format(arc_core.log_path()))

    def build_debug(self, results, header):
        """Everything the run knows, in the order it happened."""
        lines = [header, u"", u"Auto RevCloud {0}".format(arc_core.__version__),
                 u"log: {0}".format(arc_core.log_path()), u""]
        for key in sorted(self.settings.keys()):
            if key == u"compare_categories":
                lines.append(u"  {0} = {1} categories".format(
                    key, len(arc_core.parse_categories(self.settings[key]))))
            else:
                lines.append(u"  {0} = {1}".format(key, self.settings[key]))
        lines.append(u"")
        for r in results:
            lines.append(u"{0}  vs  {1}".format(r.get(u"number"),
                                                 r.get(u"against")))
            if r.get(u"error"):
                lines.append(u"    FAILED: {0}".format(r[u"error"]))
            else:
                lines.append(u"    {0} cloud(s), {1} inside views".format(
                    r.get(u"clouds"), r.get(u"in_views")))
            for note in arc_core.collapse(r.get(u"notes", [])):
                lines.append(u"    ! {0}".format(note))
            for note in arc_core.collapse(r.get(u"info", [])):
                lines.append(u"      {0}".format(note))
            lines.append(u"")
        return u"\r\n".join(lines)

    def show_completed(self, showing):
        """The Completed button only exists once there is something to open."""
        try:
            button = self.find(u"CompletedButton")
            button.Visibility = Visibility.Visible if showing else Visibility.Collapsed
        except Exception:
            pass

    def on_completed(self, sender, args):
        """Completed is the end of the job: the tool closes either way.

        Answering no is "I do not want to look at them now", not "keep the
        window open" - there is nothing left to do with it once a run has
        finished and been reported.
        """
        if self.busy or not self.clouded_ids:
            return
        count = len(self.clouded_ids)
        try:
            sheets = arc_model.sheets_of_views(self.doc(), self.clouded_ids)
        except Exception:
            sheets = []
        if sheets:
            what = u"{0} view(s) were clouded, on {1} sheet(s):\n{2}".format(
                count, len(sheets),
                u", ".join(number for _id, number in sheets[:12]))
        else:
            what = u"{0} view(s) were clouded. None of them is on a sheet.".format(
                count)
        opening = arc_ui.prompt(self.window, u"Auto RevCloud",
                                u"{0}\n\nOpen the views and their sheets in "
                                u"Revit?".format(what),
                                yes_no=True, palette=self.palette)
        if not opening:
            self.close_tool()
            return
        # Closing is deferred until the job comes back: the window cannot be
        # torn down while a job holds a reference to it and is still calling
        # back into it on Revit's thread.
        # The views AND the sheets they print on - the cloud lives in the
        # view, but the sheet is what anybody actually wants to look at.
        # Sheets first, so a sheet is what is left in front at the end.
        to_open = [sheet_id for sheet_id, _n in sheets] + list(self.clouded_ids)
        self.close_when_done = True
        self.begin_busy(u"Opening {0} view(s) and sheet(s)...".format(len(to_open)))
        self.handler.job = arc_ops.OpenSheetsJob(self, to_open)
        self.event.Raise()

    def close_tool(self):
        """Close the window for real, whatever on_close would have said, and
        leave the user looking at Revit rather than at whatever Windows
        decides to activate next."""
        self.busy = False
        self.close_when_done = False
        # Activate BEFORE closing. This window is owned by Revit's main
        # window, so bringing it to the front brings Revit's whole window
        # group with it, and closing an active owned window hands activation
        # to its owner. Closing first and then trying to raise Revit is the
        # wrong way round: by then Windows has already picked the next window
        # in its own order, which after a file dialog is often Explorer.
        try:
            self.window.Activate()
        except Exception:
            pass
        try:
            self.window.Close()
        except Exception:
            pass
        arc_ui.focus_revit(None)

    def show_progress_band(self, showing):
        """The band takes no height until a run starts."""
        try:
            row = self.find(u"ProgressRow")
            row.Height = GridLength(46) if showing else GridLength(0)
        except Exception:
            pass
        if not showing:
            return
        for name in (u"ProgressCount", u"ProgressSheet", u"ProgressStage"):
            try:
                self.find(name).Text = u""
            except Exception:
                pass
        self.set_progress(0.0)

    # ---- the link ------------------------------------------------------
    def reload_links(self):
        """Every Revit link in the project, for the left hand list."""
        # self.doc is a method - the () matters, and leaving it off handed a
        # bound method to Revit, which failed inside and was swallowed. A
        # silent except here is what made "no links" look like "no links in
        # the project" instead of a bug.
        try:
            self.link_rows = arc_diff.link_instances(self.doc())
        except Exception:
            self.link_rows = []
            self.status(u"Could not read the links: {0}".format(
                arc_core.describe_exception(sys.exc_info()[1])))
        self.rebuild_links()
        if len(self.link_rows) == 1 and self.link_rows[0][u"loaded"]:
            self.link_id = self.link_rows[0][u"id"]
            self.rebuild_links()
        self.refresh_ready()

    def rebuild_links(self):
        """Fill the dropdown. Unloaded links are listed and marked rather than
        left out and then failing when one is picked."""
        combo = self.find(u"LinkCombo")
        self.link_loading = True
        try:
            combo.Items.Clear()
            combo.Items.Add(u"(pick the link holding the previous version)")
            for row in self.link_rows:
                label = row[u"name"]
                if not row[u"loaded"]:
                    label = u"{0}  - not loaded".format(label)
                combo.Items.Add(label)
            combo.SelectedIndex = 0
            for index, row in enumerate(self.link_rows):
                if row[u"id"] == self.link_id:
                    combo.SelectedIndex = index + 1
                    break
        finally:
            self.link_loading = False
        picked = self.link_row(self.link_id)
        self.find(u"LinkHint").Text = (
            picked[u"doc_title"] if picked and picked[u"doc_title"] else
            (u"{0} link(s)".format(len(self.link_rows)) if self.link_rows else
             u"no Revit links in this project"))

    def link_row(self, link_id):
        for row in self.link_rows:
            if row[u"id"] == link_id:
                return row
        return None

    def on_link_picked(self, sender, args):
        if self.link_loading or self.busy:
            return
        index = self.find(u"LinkCombo").SelectedIndex - 1
        if index < 0 or index >= len(self.link_rows):
            self.link_id = 0
            self.rebuild_links()
            self.refresh_ready()
            return
        row = self.link_rows[index]
        if not row[u"loaded"]:
            self.status(u"That link is not loaded, so there is nothing to "
                        u"read from it.")
            self.link_id = 0
        else:
            self.link_id = row[u"id"]
        self.rebuild_links()
        self.refresh_ready()

    def on_reload_links(self, sender, args):
        if self.busy:
            return
        self.reload_links()

    # ---- sheets --------------------------------------------------------
    def fill_sheets(self):
        # The list is rebuilt from scratch on every change, which throws the
        # selection away - so setting categories on five rows left nothing
        # selected to then set a revision on. Held across the rebuild by
        # index, since the rows themselves do not move.
        keep = []
        try:
            for index in range(self.sheet_list.Items.Count):
                if self.sheet_list.Items[index].IsSelected:
                    keep.append(index)
        except Exception:
            keep = []
        self.sheet_list.Items.Clear()
        for index, row in enumerate(self.sheet_rows):
            item = arc_ui.make_row(self.window, SHEET_WIDTHS,
                                   [index + 1, row[u"number"], row[u"name"],
                                    row.get(u"status") or u"", u"", u""],
                                   [u"MutedBrush", None, None,
                                    row.get(u"colour"), None, None])

            def pick_categories(sender, args, _row=row):
                self.choose_categories_for(self.rows_for(_row))

            def pick_revision(sender, args, _row=row):
                self.choose_revision_for(self.rows_for(_row))

            arc_ui.add_row_button(
                self.window, item, 4, self.category_label(row), pick_categories,
                tooltip=self.category_tip(row))
            arc_ui.add_row_button(
                self.window, item, 5, self.revision_label(row), pick_revision,
                tooltip=u"Which revision this view's clouds go on")
            self.sheet_list.Items.Add(item)
        for index in keep:
            try:
                if index < self.sheet_list.Items.Count:
                    self.sheet_list.Items[index].IsSelected = True
            except Exception:
                pass
        self.find(u"SheetCount").Text = u"({0})".format(len(self.sheet_rows))

    def category_label(self, row):
        """The template name if there is one - that is the useful fact.

        A count says how many; a name says which, and which is what somebody
        set. The count is the fallback for a hand-picked set that was never
        saved as a template.
        """
        if row.get(u"template"):
            return row[u"template"]
        own = row.get(u"categories")
        if own:
            return u"{0} cats".format(len(own))
        return u"Categories"

    def category_tip(self, row):
        if row.get(u"template"):
            return u"Template '{0}': {1}".format(
                row[u"template"], u", ".join(row.get(u"categories") or [])[:300])
        if row.get(u"categories"):
            return u", ".join(row[u"categories"])[:300]
        return (u"This view uses the categories from Settings - click to "
                u"choose different ones for it")

    def revision_label(self, row):
        if row.get(u"revision_id"):
            return row.get(u"revision_label") or u"revision"
        return u"(default)"

    # ---- undo ----------------------------------------------------------
    def snapshot(self, what):
        """Remember the table before a change, so it can be put back.

        The rows are copied one level deep - the values in them are strings,
        numbers and lists that are replaced rather than edited in place, so a
        shallow copy of each row is enough and a deep copy would only cost
        time. Bounded, because this is an undo for a few misclicks, not a
        history of the session.
        """
        try:
            rows = [dict(row) for row in self.sheet_rows]
        except Exception:
            return
        self.undo_stack.append((what, rows, self.link_id, self.revision_id))
        if len(self.undo_stack) > 40:
            self.undo_stack.pop(0)
        self.update_undo()

    def update_undo(self):
        try:
            button = self.find(u"UndoButton")
            button.IsEnabled = bool(self.undo_stack) and not self.busy
            if self.undo_stack:
                button.ToolTip = u"Undo: {0}".format(self.undo_stack[-1][0])
            else:
                button.ToolTip = u"Nothing to undo"
        except Exception:
            pass

    def on_undo(self, sender, args):
        if self.busy or not self.undo_stack:
            return
        what, rows, link_id, revision_id = self.undo_stack.pop()
        self.sheet_rows = rows
        self.link_id = link_id
        self.revision_id = revision_id
        self.rebuild_links()
        self.load_revisions()
        self.fill_both()
        self.refresh_ready()
        self.update_undo()
        self.status(u"Undone: {0}.".format(what))

    def rows_for(self, row):
        """The rows a row-button should act on.

        If the clicked row is part of a multi-row selection, the button acts
        on the whole selection - pressing a button on one of five highlighted
        rows and having it change only that row is the behaviour people report
        as "I cannot set them together". Outside a selection it acts on its
        own row alone, which is what a button sitting in that row should do.
        """
        picked = self.highlighted_rows()
        if len(picked) > 1 and any(r is row for r in picked):
            return picked
        return [row]

    def highlighted_rows(self):
        """Exactly what is highlighted, with no fallback."""
        picked = []
        try:
            for index in range(len(self.sheet_rows)):
                if self.sheet_list.Items[index].IsSelected:
                    picked.append(self.sheet_rows[index])
        except Exception:
            picked = []
        return picked

    def selected_rows(self):
        """The rows selected in the list, or all of them when none is.

        Nothing selected meaning everything is deliberate: setting the whole
        list is the normal case and should not need selecting it first.
        """
        return self.highlighted_rows() or list(self.sheet_rows)

    def on_set_revision(self, sender, args):
        if self.busy:
            return
        rows = self.selected_rows()
        if not rows:
            self.status(u"Add some sheets or views first.")
            return
        self.choose_revision_for(rows)

    def choose_revision_for(self, rows):
        """Set the revision these rows' clouds go on."""
        if self.busy or not rows:
            return
        self.snapshot(u"set the revision on {0} row(s)".format(len(rows)))
        if not self.revision_rows:
            self.status(u"No revisions in this project yet - add one below.")
            return
        current = rows[0].get(u"revision_id") or self.revision_id
        title = (rows[0].get(u"label") or u"Revision") if len(rows) == 1 else \
            u"{0} rows".format(len(rows))
        try:
            sequences = arc_diff.numbering_sequences(self.doc())
        except Exception:
            sequences = []
        picker = RevisionPicker(self.window, self.revision_rows, current,
                                self.palette, title=title, sequences=sequences)
        picked = picker.show()
        if picked is None:
            return
        if isinstance(picked, tuple) and picked and picked[0] == u"edit":
            self.pending_revision_rows = []
            self.begin_busy(u"Saving the revision...")
            self.handler.job = arc_ops.EditRevisionJob(self, picked[1])
            self.event.Raise()
            return
        if isinstance(picked, tuple) and picked and picked[0] == u"new":
            # Created out here, where nothing is blocking the ExternalEvent.
            self.pending_revision_rows = rows
            self.begin_busy(u"Creating the revision...")
            self.handler.job = arc_ops.AddRevisionJob(self, picked[1])
            self.event.Raise()
            return
        label = u""
        for row in self.revision_rows:
            if row[u"id"] == picked:
                label = u"{0} {1}".format(row.get(u"seq", u""),
                                          row.get(u"description", u""))[:22].strip()
                break
        for row in rows:
            if picked:
                row[u"revision_id"] = picked
                row[u"revision_label"] = label
            else:
                row.pop(u"revision_id", None)
                row.pop(u"revision_label", None)
        self.fill_both()
        self.refresh_ready()
        where = (rows[0].get(u"label") or rows[0][u"name"]) if len(rows) == 1 \
            else u"{0} rows".format(len(rows))
        self.status(u"{0} set for {1}.".format(
            label or u"The default revision", where))

    def on_set_categories(self, sender, args):
        """Assign categories to every selected row at once.

        Nothing selected means every row - picking a template and pressing
        this should be able to set the whole list without selecting it first,
        which is the normal case.
        """
        if self.busy:
            return
        rows = self.selected_rows()
        if not rows:
            self.status(u"Add some sheets or views first.")
            return
        self.choose_categories_for(rows)

    def choose_categories_for(self, rows):
        """Choose the categories for these rows, overriding the global list."""
        if self.busy or not rows:
            return
        self.snapshot(u"set the categories on {0} row(s)".format(len(rows)))
        try:
            choices = arc_diff.all_model_categories(self.doc())
        except Exception:
            choices = []
            self.status(u"Could not read the categories: {0}".format(
                arc_core.describe_exception(sys.exc_info()[1])))
        if not choices:
            self.status(u"No model categories found to choose from.")
            return
        current = rows[0].get(u"categories") or arc_core.parse_categories(
            self.settings.get(u"compare_categories", u""))
        title = (rows[0].get(u"label") or u"Categories") if len(rows) == 1 else \
            u"{0} rows".format(len(rows))
        picker = CategoryPicker(self.window, choices, current, self.palette,
                                title=title)
        picked = picker.show()
        if picked is None:
            self.status(u"Ready.")
            return
        # Matching the global list exactly means "no override" - otherwise a
        # row would keep a frozen copy and quietly stop following Settings.
        default = arc_core.parse_categories(
            self.settings.get(u"compare_categories", u""))
        same_as_default = (sorted(n.lower() for n in picked) ==
                           sorted(n.lower() for n in default))
        for row in rows:
            if same_as_default and not picker.result_template:
                row.pop(u"categories", None)
                row.pop(u"template", None)
            else:
                row[u"categories"] = list(picked)
                if picker.result_template:
                    row[u"template"] = picker.result_template
                else:
                    row.pop(u"template", None)
        self.fill_both()
        where = (rows[0].get(u"label") or rows[0][u"name"]) if len(rows) == 1 \
            else u"{0} rows".format(len(rows))
        self.status(u"{0} category(ies) set for {1}.".format(len(picked), where))

    def fill_both(self):
        self.fill_sheets()

    def on_add_sheets(self, sender, args):
        if self.busy:
            return
        if not self.all_sheets:
            self.read_project()
        picker = SheetPicker(self.window, self.all_sheets,
                             [r[u"number"] for r in self.sheet_rows], self.palette)
        picked = picker.show()
        if not picked:
            return
        # Anything already listed stays listed; a sheet picked twice is added
        # once.
        seen = set(r[u"id"] for r in self.sheet_rows)
        for row in picked:
            if row[u"id"] in seen:
                continue
            seen.add(row[u"id"])
            row = dict(row)
            row[u"status"] = u""
            self.sheet_rows.append(row)
        self.fill_both()
        self.status(u"{0} sheet(s) added. Use the views on them to expand each "
                    u"one into the views it carries.".format(len(picked)))
        self.refresh_ready()

    def on_add_loose_views(self, sender, args):
        """Views on their own, for anything not placed on a sheet."""
        if self.busy:
            return
        try:
            rows = arc_model.all_views(self.doc())
        except Exception:
            rows = []
            self.status(u"Could not read the views: {0}".format(
                arc_core.describe_exception(sys.exc_info()[1])))
        if not rows:
            self.status(u"No views in this project that could take a cloud.")
            return
        picker = SheetPicker(self.window, rows,
                             [r[u"id"] for r in self.sheet_rows], self.palette,
                             title=u"Pick views")
        picked = picker.show()
        if not picked:
            return
        seen = set(r[u"id"] for r in self.sheet_rows)
        for row in picked:
            if row[u"id"] in seen:
                continue
            seen.add(row[u"id"])
            row = dict(row)
            row[u"status"] = u""
            self.sheet_rows.append(row)
        self.fill_both()
        self.refresh_ready()

    def on_add_views(self, sender, args):
        """Expand the listed sheets into the views on them, now rather than at
        Compare, so the list can be trimmed by hand first."""
        if self.busy:
            return
        sheets = [r for r in self.sheet_rows if r.get(u"kind") == u"sheet"]
        if not sheets:
            self.status(u"Add some sheets first, then this pulls in the views on them.")
            return
        before = len(self.sheet_rows)
        try:
            self.sheet_rows = arc_model.expand_sheets(self.doc(), self.sheet_rows)
        except Exception:
            self.status(u"Could not read the views: {0}".format(
                arc_core.describe_exception(sys.exc_info()[1])))
            return
        self.fill_both()
        self.refresh_ready()
        self.status(u"{0} sheet(s) expanded into {1} view(s).".format(
            len(sheets), len(self.sheet_rows) - (before - len(sheets))))

    def on_sheet_up(self, sender, args):
        self.move(self.sheet_rows, self.sheet_list, -1, self.fill_both)

    def on_sheet_down(self, sender, args):
        self.move(self.sheet_rows, self.sheet_list, 1, self.fill_both)

    def on_sheet_remove(self, sender, args):
        indices = sorted([self.sheet_list.Items.IndexOf(i) for i in self.sheet_list.SelectedItems], reverse=True)
        for index in indices:
            if 0 <= index < len(self.sheet_rows):
                del self.sheet_rows[index]
        self.fill_both()
        self.refresh_ready()

    def on_sheet_clear(self, sender, args):
        self.sheet_rows = []
        self.fill_both()
        self.refresh_ready()

    # ---- selection sync between the two lists --------------------------

    def on_sheet_selected(self, sender, args):
        pass

    def selected_index(self, listbox):
        """The selected row's index, or -1."""
        try:
            return int(listbox.SelectedIndex)
        except Exception:
            return -1

    def move(self, rows, listbox, step, refill):
        """Shuffle the selected row up or down by one and keep it selected."""
        index = self.selected_index(listbox)
        if index < 0:
            return
        target = index + step
        if target < 0 or target >= len(rows):
            return
        rows[index], rows[target] = rows[target], rows[index]
        refill()
        try:
            listbox.SelectedIndex = target
        except Exception:
            pass

    def sync_selection(self, source, target):
        if self.syncing:
            return
        self.syncing = True
        try:
            index = source.SelectedIndex
            if 0 <= index < target.Items.Count:
                target.SelectedIndex = index
            elif index < 0:
                target.SelectedIndex = -1
        except Exception:
            pass
        finally:
            self.syncing = False

    # ---- revisions -----------------------------------------------------
    def relabel_revisions(self):
        """Refresh the labels rows show after a revision is edited.

        The row holds the id and a label made when it was picked; editing the
        description would otherwise leave every row showing the old wording.
        """
        by_id = {}
        for row in self.revision_rows:
            by_id[row[u"id"]] = u"{0} {1}".format(
                row.get(u"seq", u""), row.get(u"description", u""))[:22].strip()
        for row in self.sheet_rows:
            if row.get(u"revision_id") in by_id:
                row[u"revision_label"] = by_id[row[u"revision_id"]]

    def load_revisions(self):
        """Read the revisions. No list to fill any more - they are chosen per
        row through Set revision, which is where creating one lives too."""
        try:
            self.revision_rows = arc_model.revisions(self.doc())
        except Exception as exc:
            self.revision_rows = []
            self.status(u"Could not read the revisions: {0}".format(exc))
        # The rows carry the picked id themselves; the only default kept is
        # the newest un-issued one, so a row that has never been set has
        # something sensible to fall back to.
        if not any(r[u"id"] == self.revision_id for r in self.revision_rows):
            self.revision_id = 0
        if not self.revision_id:
            for row in reversed(self.revision_rows):
                if not row[u"issued"]:
                    self.revision_id = row[u"id"]
                    break

    # ---- readiness -----------------------------------------------------
    def refresh_ready(self):
        # A row with its own revision does not need the default one, so the
        # gate asks whether every row HAS a revision rather than whether the
        # strip at the bottom has been touched.
        every_row_has_one = bool(self.sheet_rows) and all(
            (row.get(u"revision_id") or self.revision_id)
            for row in self.sheet_rows)
        ready = (not self.busy and self.link_id != 0 and every_row_has_one)
        button = self.find(u"CompareButton")
        button.IsEnabled = ready
        if self.busy:
            return
        if ready:
            own = len([r for r in self.sheet_rows if r.get(u"revision_id")])
            extra = u", {0} on their own revision".format(own) if own else u""
            self.status(u"{0} view(s) ready{1}. Compare reads each one against "
                        u"the link and clouds what changed.".format(
                            len(self.sheet_rows), extra))
        elif self.link_id == 0:
            self.status(u"Pick the link holding the previous version of the model.")
        elif not self.sheet_rows:
            self.status(u"Add the sheets or views to check.")
        elif not every_row_has_one:
            self.status(u"Pick a revision - one at the bottom for everything, "
                        u"or per row with Set revision.")

    # ---- compare -------------------------------------------------------
    def on_compare(self, sender, args):
        if self.busy or not self.sheet_rows or self.revision_id == 0 or self.link_id == 0:
            return
        # Sheets expand into their views here, whether or not the button was
        # pressed - the comparison reads a view, and a sheet left in the list
        # should mean "all the views on it", not "skip this one".
        try:
            rows = arc_model.expand_sheets(self.doc(), self.sheet_rows)
        except Exception:
            rows = list(self.sheet_rows)
        if rows != self.sheet_rows:
            self.sheet_rows = rows
            self.fill_both()
        if not rows:
            self.status(u"Those sheets carry no views that can be compared.")
            return
        plan = [(row[u"id"], row[u"label"], row.get(u"categories"),
                 row.get(u"revision_id") or self.revision_id)
                for row in rows]
        self.show_completed(False)
        self.clouded_ids = []
        self.begin_busy(u"Starting...", band=True)
        self.handler.job = arc_ops.CompareJob(self, self.settings, plan,
                                              self.link_id, self.revision_id)
        self.event.Raise()

    def begin_busy(self, text, band=False):
        self.busy = True
        # Pumping the dispatcher to move the progress bar also pumps INPUT, so
        # every button in this window stays live during a run and a click
        # lands in the middle of it. Made hit-test-invisible for the duration.
        try:
            self.find(u"Shell").IsHitTestVisible = False
        except Exception:
            pass
        if band:
            self.show_progress_band(True)
        self.set_progress(0.0)
        self.status(text)
        try:
            self.find(u"Shell").IsHitTestVisible = False
        except Exception:
            pass
        self.find(u"CompareButton").IsEnabled = False
        arc_ui.pump(self.window)

    def end_busy(self, band=False):
        self.busy = False
        try:
            self.find(u"Shell").IsHitTestVisible = True
        except Exception:
            pass
        if band:
            self.show_progress_band(False)
        try:
            self.find(u"Shell").IsHitTestVisible = True
        except Exception:
            pass
        self.refresh_ready()

    # ---- called from the job on Revit's thread -------------------------
    def report_progress(self, fraction, text, sheet=None, index=None, total=None):
        """Move the bar and say what is being worked on.

        `text` is the stage (Reading the view / Reading the link / Comparing /
        Clouding),
        `sheet` names the sheet it is happening to. Both are shown in the band
        rather than only in the status line, so a long run says where it is
        without the user reading a one-line status at the far corner.
        """
        self.set_progress(fraction)
        try:
            if index is not None and total:
                self.find(u"ProgressCount").Text = u"Sheet {0} of {1}".format(index, total)
            if sheet is not None:
                self.find(u"ProgressSheet").Text = sheet
            self.find(u"ProgressStage").Text = u"{0}   {1:.0f}%".format(
                text, max(0.0, min(1.0, fraction)) * 100.0)
        except Exception:
            pass
        if sheet:
            self.status(u"{0} - {1}".format(text, sheet))
        else:
            self.status(text)
        arc_ui.pump(self.window)

    def report_row(self, index, text, colour):
        key = {u"green": u"GreenBrush", u"orange": u"OrangeBrush", u"red": u"RedBrush",
               u"muted": u"MutedBrush"}.get(colour, None)
        try:
            if index < len(self.sheet_rows):
                self.sheet_rows[index][u"status"] = text
                self.sheet_rows[index][u"colour"] = key
                arc_ui.set_cell(self.sheet_list.Items[index], 3, text, key)
        except Exception:
            pass

    def job_finished(self, job):
        self.end_busy(band=isinstance(job, arc_ops.CompareJob))
        if isinstance(job, arc_ops.EditRevisionJob):
            if job.error:
                self.status(u"Editing the revision failed - see the log.")
                arc_ui.prompt(self.window, u"Edit revision", job.error,
                              palette=self.palette)
                return
            self.load_revisions()
            self.relabel_revisions()
            self.fill_both()
            if job.notes:
                arc_ui.prompt(self.window, u"Edit revision",
                              u"Saved, but:\n\n  {0}".format(
                                  u"\n  ".join(job.notes)),
                              palette=self.palette)
            self.status(u"Revision updated.")
            return
        if isinstance(job, arc_ops.AddRevisionJob):
            if job.error:
                self.status(u"Adding the revision failed - see the log.")
                arc_ui.prompt(self.window, u"Add revision", job.error, palette=self.palette)
                return
            self.revision_id = job.new_id
            self.load_revisions()
            if job.notes:
                arc_ui.prompt(self.window, u"New revision",
                              u"The revision was created, but:\n\n  {0}".format(
                                  u"\n  ".join(job.notes)),
                              palette=self.palette)
            rows = self.pending_revision_rows
            self.pending_revision_rows = []
            if rows:
                # It was created from a row's Set revision button, so it goes
                # on those rows rather than only becoming the default.
                label = u""
                for entry in self.revision_rows:
                    if entry[u"id"] == job.new_id:
                        label = u"{0} {1}".format(
                            entry.get(u"seq", u""),
                            entry.get(u"description", u""))[:22].strip()
                        break
                for row in rows:
                    row[u"revision_id"] = job.new_id
                    row[u"revision_label"] = label
                self.fill_both()
                self.status(u"Revision added and set on {0} row(s).".format(
                    len(rows)))
            else:
                self.status(u"Revision added and selected.")
            self.refresh_ready()
            return
        if isinstance(job, arc_ops.CompareJob):
            self.set_progress(1.0)
            results = [r.as_dict() for r in job.results]
            if job.error:
                self.status(u"Compare failed - see the log.")
                arc_ui.prompt(self.window, u"Compare Sheets", job.error, palette=self.palette)
                return
            needs_look, text = arc_core.summarise(results)
            mode = self.settings.get(u"show_results", u"needed")
            self.status(text.split(u"\n")[0])
            self.set_debug(self.build_debug(results, text.split(u"\n")[0]))
            if [r for r in results if r.get(u"error")]:
                # A failure is exactly when somebody wants the detail, so it
                # opens itself rather than waiting to be found.
                self.show_debug(True)
            self.clouded_ids = [r.sheet_id for r in job.results
                                if r.clouds and r.sheet_id]
            self.show_completed(bool(self.clouded_ids))
            if mode == u"always" or (mode == u"needed" and needs_look):
                arc_ui.prompt(self.window, u"Compare Sheets - results", text, palette=self.palette)
            return
        if isinstance(job, arc_ops.OpenSheetsJob):
            if job.error:
                self.status(u"Opening the sheets failed - see the log.")
                arc_ui.prompt(self.window, u"Open sheets", job.error, palette=self.palette)
                if self.close_when_done:
                    self.close_tool()
                return
            if job.skipped:
                arc_ui.prompt(self.window, u"Open sheets",
                              u"Opened {0} sheet(s).\n\nNot opened:\n{1}".format(
                                  job.opened, u"\n".join(job.skipped)),
                              palette=self.palette)
            self.status(u"Opened {0} sheet(s) in Revit.".format(job.opened))
            if self.close_when_done:
                self.close_tool()
            return
