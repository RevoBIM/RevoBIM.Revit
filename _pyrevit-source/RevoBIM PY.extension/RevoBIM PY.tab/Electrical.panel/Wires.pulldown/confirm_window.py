# -*- coding: utf-8 -*-
"""RevoBIM PY - Wires: a themed yes/no.

Small enough to be a TaskDialog, but a TaskDialog is the one window in this
extension that would come up in Revit's own colours, so it gets the same
chrome as everything else.
"""

import wires_core as core
import wires_ui as ui


def ask(message, detail='', title='Wires', yes='Yes'):
    """True where the person said yes. Escape and the X both mean no."""
    try:
        window = ui.load_window('WiresConfirm.xaml')
    except Exception:
        return _plain_fallback(message, detail)

    ui.dress_header(window, core.__version__)
    ui.owned_by_revit(window)

    for name, text in (('ToolName', title), ('MessageText', message),
                       ('DetailText', detail)):
        try:
            label = window.FindName(name)
            if label is not None:
                label.Text = text
        except Exception:
            pass

    state = {'said': False}

    def _yes(sender, args):
        state['said'] = True
        try:
            window.Close()
        except Exception:
            pass

    def _no(sender, args):
        state['said'] = False
        try:
            window.Close()
        except Exception:
            pass

    for name, handler in (('YesButton', _yes), ('NoButton', _no)):
        try:
            button = window.FindName(name)
            if button is not None:
                button.Click += handler
        except Exception:
            pass
    try:
        button = window.FindName('YesButton')
        if button is not None and yes:
            button.Content = yes
    except Exception:
        pass

    try:
        window.ShowDialog()
    except Exception:
        return _plain_fallback(message, detail)
    return state['said']


def _plain_fallback(message, detail):
    """Revit's own dialog, where the themed one will not build."""
    try:
        import clr
        clr.AddReference('RevitAPIUI')
        from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons
        dialog = TaskDialog('RevoBIM Wires')
        dialog.MainInstruction = message
        dialog.MainContent = detail
        dialog.CommonButtons = (TaskDialogCommonButtons.Yes |
                                TaskDialogCommonButtons.Cancel)
        result = dialog.Show()
        return 'Yes' in str(result)
    except Exception:
        return False
