# -*- coding: utf-8 -*-
u"""RevoBIM Addin Manager - the settings window.

Modal: nothing in it needs anything picked in the model, and modal cannot fail
the way a modeless window can. It still shrinks to the taskbar like every
RevoBIM window - and takes the floating Addin Manager down with it first, so
the model can be seen - but Revit stays locked until it is answered, because
that is what modal means and a drawer does not change it.
"""

import rba_clr  # noqa: F401

import rba_core
import rba_drawer
import rba_theme
import rba_ui

from rba_core import to_text, log_exception

GROUP_BY = [(u"panel", u"Panel"), (u"tab", u"Tab"), (u"extension", u"Extension")]
DOCKS = [(u"left", u"Left"), (u"right", u"Right"), (u"floating", u"Floating")]
THEMES = [(u"auto", u"Auto - follow Revit"), (u"dark", u"Dark"), (u"light", u"Light")]


def _fill(combo, pairs, current):
    combo.Items.Clear()
    index = 0
    for position, pair in enumerate(pairs):
        combo.Items.Add(pair[1])
        if pair[0] == to_text(current).strip().lower():
            index = position
    combo.SelectedIndex = index


def _picked(combo, pairs):
    position = combo.SelectedIndex
    if position < 0 or position >= len(pairs):
        position = 0
    return pairs[position][0]


def show(settings, theme_name, owner=None, owner_drawer=None):
    u"""Returns the edited settings dict, or None when cancelled."""
    window = rba_ui.load_xaml(u"RbaSettings.xaml")
    rba_theme.apply(window, theme_name)
    rba_ui.own(window, owner)

    find = window.FindName
    result = {u"values": None}
    drawers = []

    find(u"VersionText").Text = u"v" + rba_core.__version__

    folders_box = find(u"FoldersBox")
    folders_box.Text = u"\r\n".join(
        [part.strip() for part in to_text(settings.get(u"folders", u"")).split(u"|") if part.strip()])
    find(u"NameFilterBox").Text = to_text(settings.get(u"name_filter", u""))

    icon_pairs = [(to_text(size), u"{0} px".format(size)) for size in rba_core.ICON_SIZES]
    _fill(find(u"GroupByCombo"), GROUP_BY, settings.get(u"group_by", u"panel"))
    _fill(find(u"IconSizeCombo"), icon_pairs, settings.get(u"icon_size", u"32"))
    _fill(find(u"ThemeCombo"), THEMES, settings.get(u"theme", u"auto"))
    _fill(find(u"DockCombo"), DOCKS, settings.get(u"dock", u"left"))

    find(u"TooltipsChk").IsChecked = rba_core.as_bool(settings, u"show_tooltips")
    find(u"PathsChk").IsChecked = rba_core.as_bool(settings, u"show_paths")
    find(u"HideUnloadedChk").IsChecked = rba_core.as_bool(settings, u"hide_unloaded")
    find(u"WatchChk").IsChecked = rba_core.as_bool(settings, u"watch")
    find(u"DebugChk").IsChecked = rba_core.as_bool(settings, u"debug")
    find(u"WatchMsBox").Text = to_text(rba_core.as_int(settings, u"watch_ms", 1500))
    find(u"FooterText").Text = rba_core.settings_path()

    def on_drag(sender, args):
        try:
            if args.ClickCount == 2 and drawers and drawers[0].on_header_double_click():
                return
            window.DragMove()
        except Exception:
            pass

    def on_browse(sender, args):
        folder = _browse()
        if folder:
            existing = [line.strip() for line in folders_box.Text.splitlines() if line.strip()]
            if folder not in existing:
                existing.append(folder)
            folders_box.Text = u"\r\n".join(existing)

    def on_clear(sender, args):
        folders_box.Text = u""

    def on_apply(sender, args):
        values = {}
        for key in rba_core.DEFAULTS:
            values[key] = settings.get(key, rba_core.DEFAULTS[key])
        folders = [line.strip() for line in folders_box.Text.splitlines() if line.strip()]
        values[u"folders"] = u"|".join(folders)
        values[u"name_filter"] = to_text(find(u"NameFilterBox").Text).strip()
        values[u"group_by"] = _picked(find(u"GroupByCombo"), GROUP_BY)
        values[u"icon_size"] = _picked(find(u"IconSizeCombo"), icon_pairs)
        values[u"theme"] = _picked(find(u"ThemeCombo"), THEMES)
        values[u"dock"] = _picked(find(u"DockCombo"), DOCKS)
        values[u"show_tooltips"] = u"1" if find(u"TooltipsChk").IsChecked else u"0"
        values[u"show_paths"] = u"1" if find(u"PathsChk").IsChecked else u"0"
        values[u"hide_unloaded"] = u"1" if find(u"HideUnloadedChk").IsChecked else u"0"
        values[u"watch"] = u"1" if find(u"WatchChk").IsChecked else u"0"
        values[u"debug"] = u"1" if find(u"DebugChk").IsChecked else u"0"
        try:
            values[u"watch_ms"] = to_text(max(400, int(to_text(find(u"WatchMsBox").Text).strip())))
        except Exception:
            values[u"watch_ms"] = rba_core.DEFAULTS[u"watch_ms"]
        result[u"values"] = values
        window.Close()

    def on_cancel(sender, args):
        window.Close()

    def on_key(sender, args):
        # The drawer sees keys first (PreviewKeyDown) and marks the ones it
        # takes while parked, so Escape here only ever reaches an open window.
        try:
            if args.Handled:
                return
            if rba_core.to_text(args.Key) == u"Escape":
                window.Close()
        except Exception:
            pass

    drawers.append(rba_drawer.attach(
        window, find(u"HeaderBar"),
        (find(u"ShrinkBtn"), find(u"ShrinkGlyph"), find(u"ExpandGlyph")),
        owner=owner_drawer, name=u"Settings"))
    window.KeyDown += on_key
    find(u"HeaderBar").MouseLeftButtonDown += on_drag
    find(u"BrowseBtn").Click += on_browse
    find(u"ClearFoldersBtn").Click += on_clear
    find(u"ApplyBtn").Click += on_apply
    find(u"CancelBtn").Click += on_cancel
    find(u"CloseBtn").Click += on_cancel

    window.ShowDialog()
    return result[u"values"]


def _browse():
    try:
        from System.Windows.Forms import FolderBrowserDialog, DialogResult
        dialog = FolderBrowserDialog()
        dialog.Description = u"Pick a folder holding pyRevit extensions"
        dialog.ShowNewFolderButton = False
        if dialog.ShowDialog() == DialogResult.OK:
            return to_text(dialog.SelectedPath)
    except Exception:
        log_exception(u"browse")
    return u""
