# -*- coding: utf-8 -*-
"""RevoBIM PY - Wires results window.

Results are reported here, not in the pyRevit output window, and by default
only when something needs a look.
"""

import wires_core as core
import wires_ui as ui


def should_show(report, settings):
    if report is None:
        return False
    mode = str(settings.get('show_results', 'needed')).strip().lower()
    if mode == 'never':
        return False
    if mode == 'always':
        return True
    return report.needs_a_look()


def show(report, settings, force=False, uiapp=None):
    """Display the report. Returns False where nothing was shown."""
    if report is None:
        return False
    if not force and not should_show(report, settings):
        return False

    try:
        window = ui.load_window('WiresResults.xaml')
    except Exception:
        # A themed window that will not build must never mean the tool looks
        # like it did nothing. Say it plainly instead.
        return _plain_fallback(report)

    ui.dress_header(window, core.__version__)
    ui.owned_by_revit(window)

    try:
        name = window.FindName('ToolName')
        if name is not None:
            name.Text = report.title
    except Exception:
        pass

    try:
        summary = window.FindName('SummaryText')
        if summary is not None:
            summary.Text = report.summary()
    except Exception:
        pass

    try:
        panel = window.FindName('LineList')
        if panel is not None:
            if not report.lines:
                panel.Children.Add(ui.report_row(
                    'note', 'Nothing needed doing to the wires selected.'))
            for kind, text in report.lines:
                panel.Children.Add(ui.report_row(kind, text))
    except Exception:
        pass

    try:
        status = window.FindName('StatusText')
        if status is not None:
            status.Text = 'Settings: {0}'.format(core.SETTINGS_PATH)
    except Exception:
        pass

    try:
        debug_button = window.FindName('DebugButton')
        if debug_button is not None:
            if not core._settings_bool(settings, 'debug_report'):
                debug_button.Visibility = ui.hidden()
            else:
                def _debug(sender, args):
                    _write_debug(window, uiapp, settings, report)
                debug_button.Click += _debug
    except Exception:
        pass

    try:
        ok_button = window.FindName('OkButton')
        if ok_button is not None:
            def _close(sender, args):
                try:
                    window.Close()
                except Exception:
                    pass
            ok_button.Click += _close
    except Exception:
        pass

    try:
        window.ShowDialog()
    except Exception:
        return _plain_fallback(report)
    return True


def _write_debug(window, uiapp, settings, report):
    """Write the report to disk and put it on the clipboard."""
    status = None
    try:
        status = window.FindName('StatusText')
    except Exception:
        status = None
    try:
        text = core.debug_report(uiapp, settings, report)
    except Exception as error:
        if status is not None:
            status.Text = 'Could not build the debug report: {0}'.format(error)
        return
    path = core.write_debug_report(text)
    copied = False
    try:
        import clr
        for name in ('PresentationCore', 'PresentationFramework',
                     'WindowsBase'):
            try:
                clr.AddReference(name)
            except Exception:
                pass
        from System.Windows import Clipboard
        Clipboard.SetText(text)
        copied = True
    except Exception:
        copied = False
    if status is None:
        return
    if path and copied:
        status.Text = 'Debug report copied to the clipboard and written to ' \
                      '{0}'.format(path)
    elif path:
        status.Text = 'Debug report written to {0}'.format(path)
    elif copied:
        status.Text = 'Debug report copied to the clipboard'
    else:
        status.Text = 'Could not write or copy the debug report'


def as_text(report):
    lines = [report.summary(), '']
    for kind, text in report.lines:
        marker = {'ok': '  ', 'info': '  ', 'note': '- ',
                  'skip': '! '}.get(kind, '  ')
        lines.append(marker + text)
    return '\n'.join(lines)


def _plain_fallback(report):
    """Revit's own dialog, where the themed one could not be built."""
    try:
        import clr
        clr.AddReference('RevitAPIUI')
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('RevoBIM ' + report.title, as_text(report))
        return True
    except Exception:
        return False
