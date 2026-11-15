# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM System Offset - the results window
#
# Results go in a themed window, not the pyRevit output
# window, and a windowless command reports only when
# something needs a look by default.
# ==========================================================

import so_clr  # noqa: F401  assembly references first

from System.Windows import Thickness, TextWrapping
from System.Windows.Controls import TextBlock, StackPanel, Border
from System.Windows.Media import SolidColorBrush

import so_core
import so_ui


def should_show(settings, records):
    """The rule lives in so_core, where it can be bench tested."""
    return so_core.needs_reporting(records)


def _line(window, text, key, bold=False, indent=0):
    block = TextBlock()
    block.Text = so_core.to_text(text)
    block.TextWrapping = TextWrapping.Wrap
    block.FontFamily = window.FontFamily
    block.FontSize = 12.5
    block.Margin = Thickness(indent, 2, 0, 2)
    try:
        brush = window.Resources[key]
        if isinstance(brush, SolidColorBrush):
            block.Foreground = brush
    except Exception:
        pass
    if bold:
        from System.Windows import FontWeights
        block.FontWeight = FontWeights.Bold
    return block


def show(records, settings, theme_setting='revit',
         tool_name=u'System Offset'):
    """Put the run in front of the user. Never raises."""
    try:
        window, applied = so_ui.load_window('SystemOffsetResults.xaml', theme_setting)
    except Exception as error:
        so_ui.report_error(u'The results window would not load', error)
        return

    name = window.FindName('ToolNameText')
    if name is not None:
        name.Text = tool_name

    so_ui.set_version(window)
    so_ui.load_icon(window)
    so_ui.attach_egg(window)
    so_ui.Chrome(window)
    so_ui.wire_theme_chip(window, theme_setting)

    done = len([r for r in records if r.get('ok')])
    failed = len(records) - done
    flagged = len([r for r in records
                   if r.get('ok') and r.get('problems')])

    summary = window.FindName('SummaryText')
    if summary is not None:
        if failed and done:
            summary.Text = u'{0} done, {1} not'.format(done, failed)
        elif failed:
            summary.Text = (u'Nothing was offset' if failed > 1
                            else u'That one could not be offset')
        elif flagged:
            summary.Text = (u'Done, but {0} needs a look'.format(
                u'one' if flagged == 1 else u'{0}'.format(flagged)))
        else:
            summary.Text = u'Done'

    # A run of clean offsets alongside one awkward one should
    # not make the reader hunt for the awkward one.
    records = so_core.worth_showing(records)

    panel = window.FindName('RowsPanel')
    if panel is not None:
        if not records:
            panel.Children.Add(_line(window, u'Nothing was picked.', 'MutedText'))
        for index, record in enumerate(records):
            block = StackPanel()
            title = u'{0}  -  element {1}'.format(
                (record.get('kind') or u'element').title(),
                record.get('element_id'))
            block.Children.Add(_line(window, title,
                                     'Green' if record.get('ok') else 'Red',
                                     bold=True))

            if record.get('ok'):
                # A routed run has no single offset distance or
                # direction to report, so it does not get an
                # offset's one-line summary - that is where
                # "0mm at 45 degrees" came from.
                if record.get('mode') != u'click':
                    block.Children.Add(_line(
                        window,
                        so_core.describe_run(record.get('distance_mm', 0.0),
                                             record.get('angle_deg', 45.0),
                                             record.get('direction', u'')),
                        'BodyText', indent=12))
            else:
                block.Children.Add(_line(window, record.get('reason', u''),
                                         'BodyText', indent=12))

            for trouble in record.get('problems', []):
                block.Children.Add(_line(window,
                                         u'- ' + so_core.to_text(trouble),
                                         'Orange', indent=12))

            for line in record.get('notes', []):
                block.Children.Add(_line(window, u'- ' + so_core.to_text(line),
                                         'MutedText', indent=12))

            if index < len(records) - 1:
                rule = Border()
                rule.Height = 1
                rule.Margin = Thickness(0, 9, 0, 9)
                try:
                    rule.Background = window.Resources['EdgeBrush']
                except Exception:
                    pass
                block.Children.Add(rule)

            panel.Children.Add(block)

    status = window.FindName('StatusText')
    if status is not None:
        status.Text = u'Settings: {0}'.format(so_core.settings_path())

    ok = window.FindName('OkButton')
    if ok is not None:
        ok.Click += so_ui.ui_safe(lambda s, a: window.Close())

    try:
        window.ShowDialog()
    except Exception as error:
        so_ui.report_error(u'The results window would not open', error)
