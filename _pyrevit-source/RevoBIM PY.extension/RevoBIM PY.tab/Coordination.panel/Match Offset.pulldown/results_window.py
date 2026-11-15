# -*- coding: utf-8 -*-
"""RevoBIM Match Offset - the results window.

Opened only when something needs a look, which is the default. A clean run
finishes with no dialog at all: the whole point of a pick-driven tool is that
it does not interrupt.

The rows are built as WPF elements in code rather than bound to Python
objects, because binding to IronPython objects is unreliable across engine
versions. Brushes go on with SetResourceReference so a theme swap on the open
window repaints them.
"""

import mo_clr  # noqa: F401

from System.Windows import (
    CornerRadius, GridLength, GridUnitType, TextWrapping, Thickness,
)
from System.Windows.Controls import (
    Border, ColumnDefinition, Grid, TextBlock,
)

import mo_ui
from mo_core import to_text


def _row(text, brush_key):
    """One reported line.

    A Grid, not a horizontal StackPanel. A horizontal StackPanel measures
    its children with infinite width, so a TextBlock inside one never wraps
    however TextWrapping is set - it just runs off the edge of the window
    and the end of the sentence is lost, which is exactly what happened to
    the one message in this tool that most needed reading.
    """
    shell = Border()
    shell.CornerRadius = CornerRadius(4)
    shell.Margin = Thickness(0, 0, 0, 6)
    shell.Padding = Thickness(10, 7, 10, 7)
    shell.SetResourceReference(Border.BackgroundProperty, 'CardBrush')

    inner = Grid()
    fixed_column = ColumnDefinition()
    fixed_column.Width = GridLength.Auto
    stretch_column = ColumnDefinition()
    stretch_column.Width = GridLength(1.0, GridUnitType.Star)
    inner.ColumnDefinitions.Add(fixed_column)
    inner.ColumnDefinitions.Add(stretch_column)

    tick = Border()
    tick.Width = 4
    tick.CornerRadius = CornerRadius(2)
    tick.Margin = Thickness(0, 0, 9, 0)
    tick.SetResourceReference(Border.BackgroundProperty, brush_key)
    Grid.SetColumn(tick, 0)

    label = TextBlock()
    label.Text = to_text(text)
    label.TextWrapping = TextWrapping.Wrap
    Grid.SetColumn(label, 1)

    inner.Children.Add(tick)
    inner.Children.Add(label)
    shell.Child = inner
    return shell


def show(report, settings, anchor_label=u""):
    """Put the run's notes and problems on screen."""
    window = mo_ui.load_window('MatchOffsetResults.xaml',
                               settings.get(u"theme", u"auto"))
    mo_ui.wire_header(window, settings)
    mo_ui.add_resize_grips(window)

    summary = window.FindName('SummaryLine')
    if report.problems:
        summary.Text = u"{0} matched, {1} to look at".format(
            report.matched, len(report.problems))
    else:
        summary.Text = u"{0} matched".format(report.matched)

    datum = window.FindName('DatumLine')
    datum.Text = report.datum_text or to_text(anchor_label)

    panel = window.FindName('ReportPanel')
    for text in report.problems:
        panel.Children.Add(_row(text, 'RedBrush'))
    for text in report.notes:
        panel.Children.Add(_row(text, 'MutedBrush'))
    if not report.problems and not report.notes:
        panel.Children.Add(_row(u"Nothing needed a look.", 'GreenBrush'))

    window.FindName('StatusText').Text = u"Each element is its own undo step."
    if getattr(report, 'debug', None) is not None:
        window.FindName('StatusText').Text = (
            u"Each element is its own undo step. The debug report opens "
            u"next.")

    def close(sender, args):
        window.Close()
    window.FindName('DoneButton').Click += close

    window.ShowDialog()
