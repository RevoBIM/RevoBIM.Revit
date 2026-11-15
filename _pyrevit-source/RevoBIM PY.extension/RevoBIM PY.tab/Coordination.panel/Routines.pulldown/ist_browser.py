# -*- coding: utf-8 -*-
u"""RevoBIM PY - Hide Service Type : the category list window.

The data is ist_browse; this module only draws it.  Rows are made when their
parent is first opened rather than all at once, so a view of seven thousand
pipes opens as quickly as an empty one, and a linked model is not read at all
until its row is opened.
"""

import ist_clr  # noqa: F401

from System.Windows import (
    FontWeights,
    FrameworkElement,
    Thickness,
    VerticalAlignment,
    Visibility,
)
from System.Windows.Controls import (
    CheckBox,
    Orientation,
    StackPanel,
    TextBlock,
    TreeViewItem,
)
from System.Windows.Input import Cursors, Mouse

import ist_browse
import ist_core
import ist_templates
import ist_theme
import ist_ui

NEW_SELECTION = u"(new selection)"

ICON_FOLDER = u"Hide Service Type.pushbutton"


class BrowserWindow(object):

    def __init__(self, uidoc, values, host_root, links_root, preselect=None):
        self.uidoc = uidoc
        self.doc = uidoc.Document
        self.view = self.doc.ActiveView
        self.values = values
        self.host_root = host_root
        self.links_root = links_root
        self.filterable = None
        self.result = None
        self.template = None       # the template the ticks came from
        self.dirty = False         # ticked by hand since it was applied
        self._filling = False
        self.theme = (values.get(u"theme") or u"dark").strip().lower()

        self.window = ist_ui.load_window(u"IstBrowser.xaml", self.theme)
        ist_ui.wire_chrome(self.window, icon_folder=ICON_FOLDER)
        ist_ui.owned_by_revit(self.window)
        self.find = self.window.FindName

        tree = self.find(u"Tree")
        self.tops = [host_root, links_root]
        for node in self.tops:
            tree.Items.Add(self._item(node))
        host_root.ui.IsExpanded = True
        links_root.ui.IsExpanded = True

        self._wire()
        self._fill_templates(preselect)
        self._status()

    # -- templates -----------------------------------------------------------
    def _fill_templates(self, select=None):
        combo = self.find(u"TemplateCombo")
        if combo is None:
            return
        self._filling = True
        try:
            combo.Items.Clear()
            combo.Items.Add(NEW_SELECTION)
            for name in ist_templates.names():
                combo.Items.Add(name)
            if select and select in ist_templates.names():
                combo.SelectedItem = select
            else:
                combo.SelectedIndex = 0
        finally:
            self._filling = False
        if select and combo.SelectedIndex > 0:
            self._use_template(select)
        self._template_buttons()

    def _template_buttons(self):
        combo = self.find(u"TemplateCombo")
        delete = self.find(u"DeleteTemplateButton")
        if delete is not None and combo is not None:
            delete.IsEnabled = combo.SelectedIndex > 0

    def _loader(self, node):
        u"""A template reaching into a link that has not been opened yet."""
        Mouse.OverrideCursor = Cursors.Wait
        try:
            if self.filterable is None:
                self.filterable = ist_browse.filterable_category_ints()
            ist_browse.load_link(node, self.doc, self.view, self.values,
                                 self.host_root, self.filterable)
        finally:
            Mouse.OverrideCursor = None
        if node.ui is not None:
            node.ui.Header = self._row(node)

    def _use_template(self, name):
        template = ist_templates.get(name)
        if template is None:
            return
        _, missing = ist_templates.apply_rows(
            self.host_root, self.links_root, template.get(u"rows"),
            self.values, self._loader)
        self.template = name
        self.dirty = False
        self._sync()
        summary = self._status()
        if missing:
            label = self.find(u"StatusText")
            if label is not None:
                label.Text = (u"{0}  \u00b7  {1} template row{2} not in this "
                              u"view: {3}").format(
                    label.Text, len(missing),
                    u"" if len(missing) == 1 else u"s",
                    u"; ".join(ist_templates.describe_row(r)
                               for r in missing[:3]))
        return summary

    def _template_changed(self, sender, args):
        if self._filling:
            return
        self._template_buttons()
        if sender.SelectedIndex <= 0:
            self.template = None
            self._clear(None, None)
            return
        self._use_template(u"{0}".format(sender.SelectedItem))

    def _save_template(self, sender, args):
        rows = ist_templates.rows_from(self.host_root, self.links_root)
        if not rows:
            self._say(u"Tick what the template should hide first.")
            return
        name = ist_ui.ask_text(
            self.window, self.theme, u"Save template",
            u"Name this hide selection",
            default=self.template or u"",
            hint=(u"{0} row{1}. It names categories, services, families and "
                  u"types - not elements - so it works in any view. The same "
                  u"name replaces that template.").format(
                      len(rows), u"" if len(rows) == 1 else u"s"))
        if not name:
            return
        if ist_templates.put(name, rows):
            self._fill_templates(None)
            self._filling = True
            try:
                self.find(u"TemplateCombo").SelectedItem = name
            finally:
                self._filling = False
            self.template = name
            self.dirty = False
            self._template_buttons()
            self._status()
            self._say(u"Saved {0}.".format(name), append=True)
        else:
            self._say(u"Could not write {0}".format(
                ist_templates.TEMPLATES_PATH))

    def _delete_template(self, sender, args):
        combo = self.find(u"TemplateCombo")
        if combo is None or combo.SelectedIndex <= 0:
            return
        name = u"{0}".format(combo.SelectedItem)
        ist_templates.remove(name)
        self.template = None
        self._fill_templates(None)
        self._say(u"Deleted {0}. The ticks are left as they were.".format(
            name), append=True)

    def _say(self, text, append=False):
        label = self.find(u"StatusText")
        if label is None:
            return
        if append and label.Text:
            label.Text = u"{0}  \u00b7  {1}".format(label.Text, text)
        else:
            label.Text = text

    # -- rows ----------------------------------------------------------------
    def _text(self, text, brush, size=12.5, left=0, bold=False):
        block = TextBlock()
        block.Text = text
        block.FontSize = size
        block.Margin = Thickness(left, 0, 0, 0)
        block.VerticalAlignment = VerticalAlignment.Center
        try:
            block.SetResourceReference(TextBlock.ForegroundProperty, brush)
        except Exception:
            pass
        if bold:
            block.FontWeight = FontWeights.SemiBold
        return block

    def _row(self, node):
        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        box = CheckBox()
        try:
            box.SetResourceReference(FrameworkElement.StyleProperty, u"IstCheck")
        except Exception:
            pass
        box.Margin = Thickness(0, 0, 6, 0)
        box.IsChecked = node.checked
        box.Click += self._click_handler(node)
        node.box = box
        panel.Children.Add(box)

        muted = node.label.startswith(u"(")
        panel.Children.Add(self._text(
            node.label, u"MutedBrush" if muted else u"TextBrush",
            bold=node.kind in (u"source", u"root")))
        if node.count:
            panel.Children.Add(self._text(u"{0}".format(node.count),
                                          u"BlueBrush", 12, left=10))
        if node.collateral:
            extra = self._text(u"+{0} in this model".format(node.collateral),
                               u"OrangeBrush", 11.5, left=10)
            extra.ToolTip = (u"A filter cannot tell a link from this model: "
                             u"hiding this row also hides {0} element{1} of "
                             u"this model in the view.").format(
                                 node.collateral,
                                 u"" if node.collateral == 1 else u"s")
            panel.Children.Add(extra)
        if node.kind == u"source" and not node.loaded:
            panel.Children.Add(self._text(u"open to read", u"MutedBrush",
                                          11, left=10))
        if node.note:
            panel.Children.Add(self._text(node.note, u"MutedBrush", 11,
                                          left=10))
        return panel

    def _placeholder(self, text=u"..."):
        item = TreeViewItem()
        item.Header = self._text(text, u"MutedBrush", 11.5)
        return item

    def _item(self, node):
        item = TreeViewItem()
        node.ui = item
        node.populated = False
        item.Header = self._row(node)
        if node.children or not node.loaded:
            item.Items.Add(self._placeholder())
            item.Expanded += self._expand_handler(node)
        elif node.kind == u"root":
            item.Items.Add(self._placeholder(
                u"no loaded links are drawn in this view"))
        return item

    def _populate(self, node):
        if getattr(node, u"populated", False):
            return
        if not node.loaded:
            Mouse.OverrideCursor = Cursors.Wait
            try:
                if self.filterable is None:
                    self.filterable = ist_browse.filterable_category_ints()
                ist_browse.load_link(node, self.doc, self.view, self.values,
                                     self.host_root, self.filterable)
            finally:
                Mouse.OverrideCursor = None
            node.ui.Header = self._row(node)
        node.ui.Items.Clear()
        for child in node.children:
            node.ui.Items.Add(self._item(child))
        if not node.children:
            node.ui.Items.Add(self._placeholder(u"nothing that can be hidden"))
        node.populated = True

    def _expand_handler(self, node):
        def handler(sender, args):
            try:
                # Expanded bubbles: only answer for this row, not a child's.
                if not args.OriginalSource.Equals(sender):
                    return
                self._populate(node)
            except Exception:
                pass
        return handler

    # -- ticking -------------------------------------------------------------
    def _click_handler(self, node):
        def handler(sender, args):
            # Decided from the row, not the box: WPF turns a part-ticked box
            # into an empty one on click, where a part-ticked category should
            # tick everything under it.
            ist_browse.set_checked(node, node.checked is not True)
            self.dirty = True
            self._sync()
            self._status()
        return handler

    def _sync(self):
        for top in self.tops:
            for node in top.walk():
                box = getattr(node, u"box", None)
                if box is not None:
                    box.IsChecked = node.checked

    def _status(self):
        summary = ist_browse.summarise(self.host_root, self.links_root)
        parts = []
        if summary[u"host_ids"]:
            parts.append(u"This model: {0}".format(len(summary[u"host_ids"])))
        if summary[u"whole_links"]:
            parts.append(u"whole links: {0}".format(len(summary[u"whole_links"])))
        if summary[u"filters"]:
            count = sum(n.count for n in summary[u"filters"])
            parts.append(u"linked: {0} in {1} filter{2}".format(
                count, len(summary[u"filters"]),
                u"" if len(summary[u"filters"]) == 1 else u"s"))
        if summary[u"collateral"]:
            parts.append(u"+{0} of this model by those filters".format(
                summary[u"collateral"]))
        label = self.find(u"StatusText")
        if label is not None:
            label.Text = u"  ·  ".join(parts) if parts else u"Nothing ticked."
        button = self.find(u"HideButton")
        if button is not None:
            button.IsEnabled = not summary[u"empty"]
        return summary

    # -- search --------------------------------------------------------------
    def _matches(self, node, text):
        if text in node.label.lower():
            return True
        if not node.loaded:
            return False
        for child in node.children:
            if self._matches(child, text):
                return True
        return False

    def _apply(self, node, text, forced):
        if node.ui is None:
            return False
        if not text:
            node.ui.Visibility = Visibility.Visible
            if node.populated:
                for child in node.children:
                    self._apply(child, text, False)
            return True
        mine = forced or text in node.label.lower()
        hit = False
        if node.loaded and node.children:
            deeper = [c for c in node.children if self._matches(c, text)]
            if deeper:
                self._populate(node)
                node.ui.IsExpanded = True
            if node.populated:
                for child in node.children:
                    if self._apply(child, text, mine):
                        hit = True
        visible = mine or hit
        node.ui.Visibility = Visibility.Visible if visible \
            else Visibility.Collapsed
        return visible

    def _search(self, sender, args):
        text = (sender.Text or u"").strip().lower()
        for top in self.tops:
            self._apply(top, text, False)
            top.ui.Visibility = Visibility.Visible

    # -- buttons -------------------------------------------------------------
    def _expand_all(self, sender, args):
        for node in [self.host_root] + list(self.host_root.children):
            self._populate(node)
            node.ui.IsExpanded = True
        for top in self.tops:
            for node in top.walk():
                if node.ui is not None and node.populated:
                    node.ui.IsExpanded = True

    def _collapse_all(self, sender, args):
        for top in self.tops:
            for node in top.walk():
                if node.ui is not None and node is not top:
                    node.ui.IsExpanded = False

    def _clear(self, sender, args):
        for top in self.tops:
            for node in top.walk():
                node.checked = False
        self._sync()
        self._status()

    def _toggle_theme(self, sender, args):
        self.theme = u"light" if self.theme == u"dark" else u"dark"
        ist_theme.apply(self.window, self.theme)
        try:
            sender.Content = u"Light" if self.theme == u"dark" else u"Dark"
        except Exception:
            pass
        values = ist_core.load_settings()
        values[u"theme"] = self.theme
        ist_core.save_settings(values)

    def _hide(self, sender, args):
        self.result = self._status()
        # A template ticked and left as it was is the one to remember; one
        # changed by hand is a new selection until it is saved.
        self.result[u"template"] = self.template if (
            self.template and not self.dirty) else None
        self.window.Close()

    def _reset(self, sender, args):
        self.result = {u"reset": True}
        self.window.Close()

    def _cancel(self, sender, args):
        self.result = None
        self.window.Close()

    def _wire(self):
        pairs = [
            (u"HideButton", self._hide),
            (u"ResetButton", self._reset),
            (u"CancelButton", self._cancel),
            (u"ExpandButton", self._expand_all),
            (u"CollapseButton", self._collapse_all),
            (u"ClearButton", self._clear),
            (u"ThemeChip", self._toggle_theme),
            (u"SaveTemplateButton", self._save_template),
            (u"DeleteTemplateButton", self._delete_template),
        ]
        for name, handler in pairs:
            control = self.find(name)
            if control is not None:
                control.Click += handler
        search = self.find(u"SearchBox")
        if search is not None:
            search.TextChanged += self._search
        combo = self.find(u"TemplateCombo")
        if combo is not None:
            combo.SelectionChanged += self._template_changed
        chip = self.find(u"ThemeChip")
        if chip is not None:
            chip.Content = u"Light" if self.theme == u"dark" else u"Dark"
        reset = self.find(u"ResetButton")
        if reset is not None:
            reset.IsEnabled = ist_core.needs_reset(self.doc, self.view)

    def show(self):
        self.window.ShowDialog()
        return self.result


def _view_ok(view, report):
    try:
        usable = view.CanUseTemporaryVisibilityModes()
    except Exception:
        usable = False
    if not usable:
        report.refused = (u"This view will not take Temporary Hide/Isolate - "
                          u"a sheet, a schedule or a view template.")
    return usable


def run(uidoc, values, report, preselect=None):
    u"""Read the view, show the list, hand back what was ticked.

    Returns ist_browse.summarise() output (with "template" set when the ticks
    came from a template left unchanged), {"reset": True}, or None when the
    window was closed without a choice (or the view cannot take it, in which
    case `report.refused` says why).  `preselect` opens it with that
    template ticked."""
    doc = uidoc.Document
    view = doc.ActiveView
    if not _view_ok(view, report):
        return None
    Mouse.OverrideCursor = Cursors.Wait
    try:
        host_root = ist_browse.build_host(doc, view, values)
        links_root = ist_browse.build_links_root(doc, view)
    finally:
        Mouse.OverrideCursor = None
    window = BrowserWindow(uidoc, values, host_root, links_root, preselect)
    return window.show()


def run_template(uidoc, values, report, name):
    u"""Hide a template in the active view without showing the list."""
    doc = uidoc.Document
    view = doc.ActiveView
    if not _view_ok(view, report):
        return None
    Mouse.OverrideCursor = Cursors.Wait
    try:
        summary, missing, error = ist_templates.plan_from_template(
            doc, view, values, name)
    finally:
        Mouse.OverrideCursor = None
    if error:
        report.refused = error
        return None
    if missing:
        report.note(u"{0} row{1} of {2} not in this view: {3}".format(
            len(missing), u"" if len(missing) == 1 else u"s", name,
            u"; ".join(ist_templates.describe_row(r) for r in missing)))
    if summary.get(u"empty"):
        report.refused = u"Nothing in {0} is in this view.".format(name)
        return None
    return summary
