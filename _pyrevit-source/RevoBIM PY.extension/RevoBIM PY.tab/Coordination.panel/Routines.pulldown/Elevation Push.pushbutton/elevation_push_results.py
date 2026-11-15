# -*- coding: utf-8 -*-
"""Themed results window for Elevation Push.

Every clr.AddReference happens here, at the top, before any System.*
name is touched -- pyRevit does not preload WPF into every engine, and
a namespace whose assembly was never referenced throws ImportError at
module load, which shows as a blank white pyRevit window with no
traceback in it.
"""

import clr

for _asm in ("PresentationFramework", "PresentationCore", "WindowsBase",
             "System.Xaml", "System.Windows.Forms"):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

import os

from System.IO import File, MemoryStream
from System.Windows import Thickness, HorizontalAlignment, VerticalAlignment
from System.Windows import TextWrapping, GridLength, GridUnitType, Window
from System.Windows import FontWeights, CornerRadius
from System.Windows.Controls import (Border, TextBlock, StackPanel, Grid,
                                     ColumnDefinition, RowDefinition,
                                     Orientation)
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, ColorConverter, FontFamily
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption

HERE = os.path.dirname(__file__)
XAML_PATH = os.path.join(HERE, "ElevationPushResults.xaml")

SEGOE = FontFamily("Segoe UI")

SHELL = "#232326"
CARD = "#2B2B2E"
FIELD = "#1C1C1F"
EDGE = "#3E3E42"
FG = "#E4E4E4"
MUTED = "#9A9A9E"
BLUE = "#4FA3E3"
ORANGE = "#E8912D"
GREEN = "#3FA75A"
RED = "#D9534F"


def brush(hex_colour):
    return SolidColorBrush(ColorConverter.ConvertFromString(hex_colour))


def _text(value, colour, size, bold=False, wrap=False):
    tb = TextBlock()
    tb.Text = value
    tb.Foreground = brush(colour)
    tb.FontFamily = SEGOE
    tb.FontSize = size
    if bold:
        tb.FontWeight = FontWeights.Bold
    if wrap:
        tb.TextWrapping = TextWrapping.Wrap
    tb.VerticalAlignment = VerticalAlignment.Center
    return tb


def _card(child, background=CARD, pad=(12, 10, 12, 10), margin=(0, 0, 0, 4)):
    b = Border()
    b.Background = brush(background)
    b.BorderBrush = brush(EDGE)
    b.BorderThickness = Thickness(1)
    b.CornerRadius = CornerRadius(6)
    b.Padding = Thickness(pad[0], pad[1], pad[2], pad[3])
    b.Margin = Thickness(margin[0], margin[1], margin[2], margin[3])
    b.Child = child
    return b


def section(panel, label, colour):
    """A section heading with the 4px coloured tick to its left."""
    row = StackPanel()
    row.Orientation = Orientation.Horizontal
    row.Margin = Thickness(0, 14, 0, 6)

    tick = Border()
    tick.Background = brush(colour)
    tick.Width = 4
    tick.Height = 15
    tick.Margin = Thickness(0, 0, 8, 0)
    row.Children.Add(tick)

    row.Children.Add(_text(label, FG, 13.5, bold=True))
    panel.Children.Add(row)


def rules_card(panel, rows):
    """One line per filter rule: category, the filter, the match count."""
    grid = Grid()
    for width, unit in ((2.2, GridUnitType.Star), (1.6, GridUnitType.Star),
                        (60, GridUnitType.Pixel)):
        cd = ColumnDefinition()
        cd.Width = GridLength(width, unit)
        grid.ColumnDefinitions.Add(cd)

    for index, (label, contains, count) in enumerate(rows):
        grid.RowDefinitions.Add(RowDefinition())

        name = _text(label, FG, 12.5)
        name.Margin = Thickness(0, 5, 0, 5)
        Grid.SetRow(name, index)
        Grid.SetColumn(name, 0)
        grid.Children.Add(name)

        rule = _text('contains "{}"'.format(contains), MUTED, 12.5)
        rule.Margin = Thickness(0, 5, 0, 5)
        Grid.SetRow(rule, index)
        Grid.SetColumn(rule, 1)
        grid.Children.Add(rule)

        num = _text(str(count), FG if count else MUTED, 12.5)
        num.HorizontalAlignment = HorizontalAlignment.Right
        num.Margin = Thickness(0, 5, 0, 5)
        Grid.SetRow(num, index)
        Grid.SetColumn(num, 2)
        grid.Children.Add(num)

    panel.Children.Add(_card(grid))


def stats_card(panel, matched, updated, skipped):
    """The three big numbers."""
    grid = Grid()
    for _ in range(3):
        cd = ColumnDefinition()
        cd.Width = GridLength(1, GridUnitType.Star)
        grid.ColumnDefinitions.Add(cd)

    chips = ((matched, "matched", BLUE),
             (updated, "updated", GREEN),
             (skipped, "skipped", ORANGE if skipped else MUTED))

    for index, (value, label, colour) in enumerate(chips):
        cell = StackPanel()
        cell.Margin = Thickness(0, 6, 0, 6)

        big = _text(str(value), colour, 24, bold=True)
        big.HorizontalAlignment = HorizontalAlignment.Center
        cell.Children.Add(big)

        small = _text(label, MUTED, 11.5)
        small.HorizontalAlignment = HorizontalAlignment.Center
        cell.Children.Add(small)

        Grid.SetColumn(cell, index)
        grid.Children.Add(cell)

    panel.Children.Add(_card(grid))


def skips_card(panel, rows):
    """Element id in orange, reason beside it."""
    grid = Grid()
    for width, unit in ((110, GridUnitType.Pixel), (1, GridUnitType.Star)):
        cd = ColumnDefinition()
        cd.Width = GridLength(width, unit)
        grid.ColumnDefinitions.Add(cd)

    for index, (eid, reason) in enumerate(rows):
        grid.RowDefinitions.Add(RowDefinition())

        ident = _text(str(eid), ORANGE, 12)
        ident.FontFamily = FontFamily("Consolas")
        ident.Margin = Thickness(0, 4, 0, 4)
        ident.VerticalAlignment = VerticalAlignment.Top
        Grid.SetRow(ident, index)
        Grid.SetColumn(ident, 0)
        grid.Children.Add(ident)

        why = _text(reason, FG, 12.5, wrap=True)
        why.Margin = Thickness(0, 4, 0, 4)
        Grid.SetRow(why, index)
        Grid.SetColumn(why, 1)
        grid.Children.Add(why)

    panel.Children.Add(_card(grid, background=FIELD))


def note(panel, text, colour=MUTED):
    tb = _text(text, colour, 12, wrap=True)
    tb.Margin = Thickness(2, 4, 2, 4)
    tb.VerticalAlignment = VerticalAlignment.Top
    panel.Children.Add(tb)


def param_line(panel, source_name, target_name):
    row = StackPanel()
    row.Orientation = Orientation.Horizontal
    row.Margin = Thickness(0, 2, 0, 2)
    row.Children.Add(_text(source_name, FG, 12.5))
    arrow = _text("  \u2192  ", BLUE, 13, bold=True)
    row.Children.Add(arrow)
    row.Children.Add(_text(target_name, FG, 12.5))
    panel.Children.Add(_card(row, background=FIELD, pad=(12, 8, 12, 8)))


def load_window(version):
    """Parse the layout and wire the chrome."""
    stream = None
    try:
        stream = MemoryStream(File.ReadAllBytes(XAML_PATH))
        window = XamlReader.Load(stream)
    finally:
        if stream is not None:
            try:
                stream.Close()
            except Exception:
                pass

    version_text = window.FindName("VersionText")
    if version_text is not None:
        version_text.Text = "v" + str(version)

    header = window.FindName("HeaderBar")
    if header is not None:
        def _drag(sender, args):
            try:
                window.DragMove()
            except Exception:
                pass
        header.MouseLeftButtonDown += _drag

    def _close(sender, args):
        try:
            window.Close()
        except Exception:
            pass

    for name in ("CloseBtn", "OkBtn"):
        button = window.FindName(name)
        if button is not None:
            button.Click += _close

    return window


def show_report(version, source_name, target_name, rule_rows,
                matched, updated, skipped, debug_names, owner_handle=None):
    """Build and show the whole report. Returns True if it displayed."""
    window = load_window(version)
    body = window.FindName("Body")

    param_line(body, source_name, target_name)

    section(body, "Filters", BLUE)
    rules_card(body, rule_rows)

    section(body, "Result", ORANGE)
    stats_card(body, matched, updated, len(skipped))

    if not matched:
        note(body, "Nothing matched the filters above, so nothing was "
                   "written.")

    if skipped:
        section(body, "Skipped", RED)
        skips_card(body, skipped)

        if debug_names is not None:
            eid, names = debug_names
            note(body, "Parameters available on element {}. Check the "
                       "names in the CONFIGURATION block at the top of "
                       "script.py against this list:".format(eid))
            note(body, ", ".join(names))

    status = window.FindName("StatusText")
    if status is not None:
        if skipped:
            status.Text = "{} updated, {} need a look".format(
                updated, len(skipped))
            status.Foreground = brush(ORANGE)
        elif matched:
            status.Text = "{} updated, nothing skipped".format(updated)
            status.Foreground = brush(GREEN)
        else:
            status.Text = "Nothing matched"

    if owner_handle is not None:
        try:
            from System.Windows.Interop import WindowInteropHelper
            WindowInteropHelper(window).Owner = owner_handle
        except Exception:
            pass

    window.ShowDialog()
    return True
