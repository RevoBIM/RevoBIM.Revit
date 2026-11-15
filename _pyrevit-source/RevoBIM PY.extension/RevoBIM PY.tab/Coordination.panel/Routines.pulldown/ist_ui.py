# -*- coding: utf-8 -*-
u"""RevoBIM PY - Isolate Service Type : XAML loading, theming, chrome."""

import ist_clr  # noqa: F401

import os
import codecs

from System.IO import MemoryStream, File
from System.Text import Encoding
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption

import ist_core
import ist_theme

HERE = os.path.dirname(os.path.abspath(__file__))
THEME_FILE = os.path.join(HERE, u"IstTheme.xaml")


def _parse(path):
    handle = codecs.open(path, u"r", u"utf-8")
    try:
        text = handle.read()
    finally:
        handle.close()
    stream = MemoryStream(Encoding.UTF8.GetBytes(text))
    try:
        return XamlReader.Load(stream)
    finally:
        stream.Close()


def load_window(xaml_name, theme_name):
    u"""Parse a layout, merge IstTheme.xaml into it, then write the palette
    straight onto window.Resources.

    The dictionary is merged AFTER the layout is parsed, so a layout may only
    use DynamicResource - a StaticResource fails at load and shows up as a
    blank white pyRevit window."""
    window = _parse(os.path.join(HERE, xaml_name))
    try:
        window.Resources.MergedDictionaries.Add(_parse(THEME_FILE))
    except Exception:
        pass
    ist_theme.apply(window, theme_name)
    return window


def load_image(path):
    u"""No System.Uri - it moved assemblies and throws ImportError on 2025+.
    Bytes through a MemoryStream instead."""
    image = BitmapImage()
    image.BeginInit()
    image.StreamSource = MemoryStream(File.ReadAllBytes(path))
    image.CacheOption = BitmapCacheOption.OnLoad
    image.EndInit()
    return image


def wire_chrome(window, header_name=u"HeaderBar", close_name=u"CloseButton",
                version_name=u"VersionText", icon_name=u"HeaderIcon",
                icon_folder=u"Isolate Service Type.pushbutton"):
    u"""Drag by the header, close on the X, version top right, icon if there
    is one.  Everything decorative sits in a try/except so cosmetics can never
    take the tool down."""
    header = window.FindName(header_name)
    if header is not None:
        def _drag(sender, args):
            try:
                window.DragMove()
            except Exception:
                pass
        header.MouseLeftButtonDown += _drag

    close = window.FindName(close_name)
    if close is not None:
        def _close(sender, args):
            try:
                window.Close()
            except Exception:
                pass
        close.Click += _close

    label = window.FindName(version_name)
    if label is not None:
        try:
            label.Text = u"v" + ist_core.__version__
        except Exception:
            pass

    holder = window.FindName(icon_name)
    if holder is not None:
        try:
            icon_path = os.path.join(HERE, icon_folder, u"icon.png")
            if os.path.isfile(icon_path):
                holder.Source = load_image(icon_path)
        except Exception:
            pass


def owned_by_revit(window):
    u"""An unowned window slips behind Revit and reads as a crash."""
    try:
        from System.Windows.Interop import WindowInteropHelper
        from System.Diagnostics import Process
        helper = WindowInteropHelper(window)
        helper.Owner = Process.GetCurrentProcess().MainWindowHandle
    except Exception:
        pass


# ===========================================================================
# results
# ===========================================================================

def show_results(report, theme_name, title=None,
                 icon_folder=u"Isolate Service Type.pushbutton"):
    window = load_window(u"IstResults.xaml", theme_name)
    wire_chrome(window, icon_folder=icon_folder)
    owned_by_revit(window)

    heading = window.FindName(u"HeadingText")
    if heading is not None:
        if report.refused:
            heading.Text = u"Nothing {0}".format(report.verb)
        elif report.reset:
            heading.Text = u"View reset"
        else:
            heading.Text = u"{0} elements {1}".format(
                report.count, report.verb)

    body = window.FindName(u"BodyList")
    if body is not None:
        items = []
        if report.refused:
            items.append(report.refused)
        items.extend(report.lines)
        items.extend(report.notes)
        for line in items:
            body.Items.Add(line)

    ok = window.FindName(u"OkButton")
    if ok is not None:
        def _ok(sender, args):
            try:
                window.Close()
            except Exception:
                pass
        ok.Click += _ok

    if title is not None:
        try:
            window.FindName(u"ToolText").Text = title
        except Exception:
            pass

    window.ShowDialog()


def report_wanted(report, values):
    if getattr(report, u"cancelled", False):
        return False
    mode = (values.get(u"show_results", u"needed") or u"needed").strip().lower()
    if mode == u"never":
        return False
    if mode == u"always":
        return True
    return report.needs_look


# ===========================================================================
# a one-line question
# ===========================================================================

def ask_text(owner, theme_name, title, prompt, default=u"", hint=u"",
             ok=u"Save"):
    u"""A themed name box.  Returns the text, or None for Cancel / close.
    Enter answers, Escape cancels."""
    window = load_window(u"IstPrompt.xaml", theme_name)
    find = window.FindName
    find(u"PromptTitle").Text = title
    find(u"PromptText").Text = prompt
    find(u"PromptHint").Text = hint
    find(u"PromptOk").Content = ok
    box = find(u"PromptBox")
    box.Text = default or u""
    answer = [None]

    def _ok(sender, args):
        text = (box.Text or u"").strip()
        if text:
            answer[0] = text
            window.Close()

    def _cancel(sender, args):
        window.Close()

    def _keys(sender, args):
        name = u"{0}".format(args.Key)
        if name in (u"Return", u"Enter"):
            _ok(sender, args)
        elif name == u"Escape":
            _cancel(sender, args)

    find(u"PromptOk").Click += _ok
    find(u"PromptCancel").Click += _cancel
    find(u"CloseButton").Click += _cancel
    window.PreviewKeyDown += _keys
    header = find(u"HeaderBar")

    def _drag(sender, args):
        try:
            window.DragMove()
        except Exception:
            pass
    header.MouseLeftButtonDown += _drag
    try:
        window.Owner = owner
    except Exception:
        owned_by_revit(window)
    box.Focus()
    box.SelectAll()
    window.ShowDialog()
    return answer[0]
