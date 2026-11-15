# -*- coding: utf-8 -*-
u"""RevoBIM Addin Manager - the right click menu, and the shortcut prompt."""

import rba_clr  # noqa: F401

import os
import re

from System.Diagnostics import Process
from System.Windows import Clipboard
from System.Windows import Visibility
from System.Windows.Controls import ContextMenu, MenuItem, Separator
from System.Windows.Input import Key, Keyboard, ModifierKeys

import rba_core
import rba_drawer
import rba_launch
import rba_qat
import rba_shortcuts
import rba_theme
import rba_ui

from rba_core import to_text, log, log_exception

MODIFIER_KEYS = (u"LeftCtrl", u"RightCtrl", u"LeftShift", u"RightShift",
                 u"LeftAlt", u"RightAlt", u"System", u"LWin", u"RWin")
MAX_SEQUENCE = 5


# ----------------------------------------------------------------------
# Revit version and the shortcuts file
# ----------------------------------------------------------------------

def revit_version():
    uiapp = rba_launch.get_uiapp()
    if uiapp is not None:
        try:
            return to_text(uiapp.Application.VersionNumber)
        except Exception:
            log_exception(u"menu/version")
    # No UIApplication yet: take the newest Revit folder that actually exists,
    # so the prompt still works rather than writing to a guess.
    base = os.environ.get(u"APPDATA")
    newest = u""
    if base:
        root = os.path.join(base, u"Autodesk", u"Revit")
        try:
            for name in sorted(os.listdir(root)):
                match = re.match(r"Autodesk Revit (\d{4})$", name)
                if match and os.path.isfile(
                        os.path.join(root, name, u"KeyboardShortcuts.xml")):
                    newest = match.group(1)
        except Exception:
            pass
    return newest


# ----------------------------------------------------------------------
# the menu
# ----------------------------------------------------------------------

def build(pane, item):
    u"""The context menu for one addin row."""
    menu = ContextMenu()
    # A menu opened by PlacementTarget has no logical parent, so it inherits
    # none of the panel's resources: merge Theme.xaml into it, or it draws as
    # the system menu - a white slab in a dark panel.
    rba_ui.merge_theme(menu)
    rba_theme.apply(menu, pane.theme_name)

    pinned = item.key in pane.pinned_keys()
    on_qat = item.key in rba_core.as_list(pane.settings, u"qat")
    favourite = pane.is_favourite(item)

    _add(menu, u"Remove from favourites" if favourite else u"Add to favourites",
         lambda: pane.toggle_favourite(item),
         tip=u"Favourites are the grid behind the star at the top")

    _add(menu, u"Unpin from the top" if pinned else u"Pin to the top",
         lambda: pane.toggle_pin(item),
         tip=u"Keeps it in a Pinned group at the top of this panel")

    _add(menu, u"Remove from Revit's Quick Access Toolbar" if on_qat
         else u"Add to Revit's Quick Access Toolbar",
         lambda: toggle_qat(pane, item),
         enabled=item.live,
         tip=(u"Revit keeps its own toolbar in a binary file with no API, so "
              u"this is put back each time the panel opens"))

    menu.Items.Add(Separator())

    keys = current_shortcut(item)
    label = u"Change the keyboard shortcut..." if keys else u"Assign a keyboard shortcut..."
    if keys:
        label = u"{0}   [{1}]".format(label, u", ".join(keys))
    _add(menu, label, lambda: assign_shortcut(pane, item), enabled=item.live)
    _add(menu, u"Open Revit's Keyboard Shortcuts", lambda: open_revit_shortcuts(pane, item))

    menu.Items.Add(Separator())

    _add(menu, u"Copy its name", lambda: copy_text(pane, item.title))
    _add(menu, u"Open its folder", lambda: open_folder(pane, item.folder))
    return menu


def _add(menu, header, action, enabled=True, tip=u""):
    entry = MenuItem()
    entry.Header = header
    entry.IsEnabled = bool(enabled)
    if tip:
        entry.ToolTip = tip

    def on_click(sender, args):
        try:
            action()
        except Exception:
            log_exception(u"menu/{0}".format(header))

    entry.Click += on_click
    menu.Items.Add(entry)
    return entry


# ----------------------------------------------------------------------
# actions
# ----------------------------------------------------------------------

def toggle_qat(pane, item):
    keys = rba_core.as_list(pane.settings, u"qat")
    ribbon_item = getattr(item, u"_ribbon_item", None)
    if item.key in keys:
        command_id = to_text(getattr(ribbon_item, u"Id", u"")) or item.command_id
        ok, message = rba_qat.remove(command_id)
        keys = [key for key in keys if key != item.key]
        rba_core.set_list(pane.settings, u"qat", keys)
        pane.save_settings()
        pane.set_status(message if not ok else
                        u"{0} taken off the Quick Access Toolbar".format(item.title))
        return
    if ribbon_item is None:
        pane.set_status(u"{0} is not on the ribbon, so it cannot go on the "
                        u"toolbar".format(item.title))
        return
    ok, message = rba_qat.add(ribbon_item, item.title)
    if not ok:
        pane.set_status(message)
        return
    keys.append(item.key)
    rba_core.set_list(pane.settings, u"qat", keys)
    pane.save_settings()
    pane.set_status(u"{0} added to the Quick Access Toolbar".format(item.title))


def copy_text(pane, text):
    try:
        Clipboard.SetText(to_text(text))
        pane.set_status(u"Copied: {0}".format(text))
    except Exception:
        log_exception(u"menu/clipboard")
        pane.set_status(u"The clipboard would not take it")


def open_folder(pane, folder):
    try:
        if folder and os.path.isdir(folder):
            Process.Start(u"explorer.exe", u'"{0}"'.format(folder))
        else:
            pane.set_status(u"That folder is not there any more")
    except Exception:
        log_exception(u"menu/folder")


def open_revit_shortcuts(pane, item):
    u"""Post Revit's own Keyboard Shortcuts dialog, name on the clipboard.

    Its list is long and has no way of being pointed at a command from
    outside, so the name goes on the clipboard to paste into its search box.
    Where the command cannot be posted, the menu path is named rather than the
    button doing nothing.
    """
    try:
        Clipboard.SetText(to_text(item.title))
    except Exception:
        pass
    uiapp = rba_launch.get_uiapp()
    try:
        from Autodesk.Revit.UI import RevitCommandId, PostableCommand
        command = RevitCommandId.LookupPostableCommandId(PostableCommand.KeyboardShortcuts)
        if uiapp is not None and command is not None:
            uiapp.PostCommand(command)
            pane.set_status(u"'{0}' copied - paste it into the search box".format(item.title))
            return
    except Exception:
        log_exception(u"menu/postable")
    pane.set_status(u"View > User Interface > Keyboard Shortcuts - '{0}' is on "
                    u"the clipboard".format(item.title))


def current_shortcut(item):
    try:
        path = rba_shortcuts.shortcuts_path(revit_version())
        if not os.path.isfile(path):
            return []
        return rba_shortcuts.current_keys(rba_shortcuts.read_file(path),
                                          to_text(item.command_id))
    except Exception:
        log_exception(u"menu/current_shortcut")
        return []


def assign_shortcut(pane, item):
    version = revit_version()
    path = rba_shortcuts.shortcuts_path(version)
    text = rba_shortcuts.read_file(path)
    if not text:
        pane.set_status(u"Revit's shortcut file is not at {0}".format(path))
        return

    command_id = to_text(item.command_id)
    if not command_id:
        pane.set_status(u"{0} has no command id, so Revit cannot bind a key to "
                        u"it".format(item.title))
        return

    result = prompt(pane, item, text, command_id)
    if result is None:
        return

    if result.get(u"revit"):
        open_revit_shortcuts(pane, item)
        return

    keys = to_text(result.get(u"keys", u""))
    paths = u"{0} > {1}".format(item.tab, item.panel)
    if result.get(u"clear"):
        existing = rba_shortcuts.current_keys(text, command_id)
        for one in existing:
            text = rba_shortcuts.remove(text, command_id, one)
        message = u"Shortcut removed from {0}".format(item.title)
    else:
        text = rba_shortcuts.upsert(text, command_id, item.title, paths, keys)
        message = u"{0} assigned to {1}".format(keys, item.title)

    if rba_shortcuts.write_file(path, text):
        pane.set_status(u"{0} - restart Revit for it to take effect".format(message))
    else:
        pane.set_status(u"Revit's shortcut file would not be written - see the "
                        u"debug log")


# ----------------------------------------------------------------------
# the prompt
# ----------------------------------------------------------------------

def key_token(key):
    u"""One key, as Revit writes it."""
    name = to_text(key)
    if len(name) == 1:
        return name.upper()
    match = re.match(r"^D(\d)$", name)
    if match:
        return match.group(1)
    match = re.match(r"^NumPad(\d)$", name)
    if match:
        return match.group(1)
    if re.match(r"^F\d{1,2}$", name):
        return name.upper()
    return u""


def prompt(pane, item, text, command_id):
    u"""Capture a shortcut, with a live conflict check.  Returns a dict or None."""
    window = rba_ui.load_xaml(u"RbaShortcut.xaml")
    rba_theme.apply(window, pane.theme_name)
    rba_ui.own(window, pane.host_window)
    find = window.FindName
    find(u"VersionText").Text = u"v" + rba_core.__version__

    # Attached BEFORE the capture handler below: both listen on
    # PreviewKeyDown, handlers run in the order they were added, and a parked
    # prompt must not record the keys pressed to bring it back. shortcut=False
    # because Ctrl+Shift+H is a perfectly good shortcut to assign, so while
    # the prompt is open that chord is captured rather than shrinking it.
    drawer = rba_drawer.attach(
        window, find(u"HeaderBar"),
        (find(u"ShrinkBtn"), find(u"ShrinkGlyph"), find(u"ExpandGlyph")),
        owner=pane.host_drawer, name=u"Shortcut", shortcut=False)

    items = rba_shortcuts.parse(text)
    existing = rba_shortcuts.current_keys(text, command_id)

    find(u"SubTitle").Text = u"Keyboard shortcut"
    find(u"TargetText").Text = item.title
    if existing:
        find(u"CurrentText").Text = u"Currently: {0}".format(u", ".join(existing))
    else:
        find(u"CurrentText").Text = u"No shortcut on it at the moment"
        find(u"ClearBtn").IsEnabled = False

    state = {u"tokens": [], u"result": None, u"clash": False}
    keys_text = find(u"KeysText")
    clash_panel = find(u"ClashPanel")
    apply_btn = find(u"ApplyBtn")

    def shown():
        return u"".join(state[u"tokens"]) if state[u"tokens"] else u""

    def refresh():
        value = shown()
        keys_text.Text = value if value else u"waiting..."
        conflicts = rba_shortcuts.find_conflicts(items, value, command_id) if value else []
        state[u"clash"] = bool(conflicts)
        if conflicts:
            clash_panel.Visibility = Visibility.Visible
            find(u"ClashTitle").Text = u"{0} is already taken".format(value)
            find(u"ClashDetail").Text = u"; ".join(
                [rba_shortcuts.describe(one) for one in conflicts[:3]])
            apply_btn.Content = u"Assign anyway"
        else:
            clash_panel.Visibility = Visibility.Collapsed
            apply_btn.Content = u"Assign"
        apply_btn.IsEnabled = bool(value)

    def on_key(sender, args):
        try:
            if args.Handled or drawer.shrunk:
                return
            # Held with Alt, WPF reports every key as Key.System and puts the
            # real one in SystemKey - read only Key and Alt shortcuts can
            # never be captured.
            key = args.SystemKey if args.Key == Key.System else args.Key
            name = to_text(key)
            if name in MODIFIER_KEYS:
                return
            args.Handled = True
            if key == Key.Escape:
                window.Close()
                return
            if key == Key.Back:
                state[u"tokens"] = []
                refresh()
                return
            if key == Key.Enter and shown():
                accept()
                return
            token = key_token(key)
            if not token:
                return
            modifiers = []
            live = Keyboard.Modifiers
            if live & ModifierKeys.Control:
                modifiers.append(u"Ctrl")
            if live & ModifierKeys.Shift:
                modifiers.append(u"Shift")
            if live & ModifierKeys.Alt:
                modifiers.append(u"Alt")
            if modifiers:
                # A combination replaces the sequence: Revit will not take
                # "VG" and "Ctrl+S" as one shortcut.
                state[u"tokens"] = [u"+".join(modifiers + [token])]
            else:
                if state[u"tokens"] and u"+" in state[u"tokens"][0]:
                    state[u"tokens"] = []
                if len(state[u"tokens"]) < MAX_SEQUENCE:
                    state[u"tokens"].append(token)
            refresh()
        except Exception:
            log_exception(u"prompt/key")

    def accept():
        state[u"result"] = {u"keys": shown()}
        window.Close()

    def on_apply(sender, args):
        if shown():
            accept()

    def on_clear(sender, args):
        state[u"result"] = {u"clear": True}
        window.Close()

    def on_revit(sender, args):
        state[u"result"] = {u"revit": True}
        window.Close()

    def on_cancel(sender, args):
        window.Close()

    def on_drag(sender, args):
        try:
            if args.ClickCount == 2 and drawer.on_header_double_click():
                return
            window.DragMove()
        except Exception:
            pass

    window.PreviewKeyDown += on_key
    find(u"ApplyBtn").Click += on_apply
    find(u"ClearBtn").Click += on_clear
    find(u"RevitBtn").Click += on_revit
    find(u"CancelBtn").Click += on_cancel
    find(u"CloseBtn").Click += on_cancel
    find(u"HeaderBar").MouseLeftButtonDown += on_drag

    refresh()
    window.ShowDialog()
    log(u"shortcut prompt returned {0}".format(state[u"result"]))
    return state[u"result"]
