# -*- coding: utf-8 -*-
"""RevoBIM VlookUp - window loading, theming and the shared dialogs.

Theme.xaml is merged into each window after XamlReader has parsed the layout,
so every layout file may only reference brushes and styles with
DynamicResource. A StaticResource would fail at parse time and show up as a
blank white pyRevit window.
"""

import clr
import os

for _asm in ('PresentationCore', 'PresentationFramework', 'WindowsBase',
             'System.Xaml', 'System.Xml'):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

from System.IO import StringReader, MemoryStream, File
from System.Xml import XmlReader
from System.Windows.Markup import XamlReader
from System.Windows import Thickness, Visibility, TextWrapping
from System.Windows.Controls import TextBlock, StackPanel, Orientation, Border
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Input import Cursors

HERE = os.path.dirname(os.path.abspath(__file__))
THEME_FILE = os.path.join(HERE, 'Theme.xaml')


def _read_text(path):
    try:
        return File.ReadAllText(path)
    except Exception:
        handle = open(path, 'r')
        try:
            return handle.read()
        finally:
            handle.close()


def parse_xaml(path):
    return XamlReader.Load(XmlReader.Create(StringReader(_read_text(path))))


def load_theme():
    return parse_xaml(THEME_FILE)


def load_window(name, version=None, theme=None):
    """Parse a layout file, merge the theme, wire the chrome."""
    window = parse_xaml(os.path.join(HERE, name))
    try:
        window.Resources.MergedDictionaries.Add(theme if theme is not None else load_theme())
    except Exception:
        pass
    wire_chrome(window, version)
    return window


def wire_chrome(window, version=None):
    header = window.FindName('HeaderBar')
    if header is not None:
        def _drag(sender, args):
            try:
                window.DragMove()
            except Exception:
                pass
        header.MouseLeftButtonDown += _drag
        try:
            header.Cursor = Cursors.SizeAll
        except Exception:
            pass
    close_button = window.FindName('CloseBtn')
    if close_button is not None:
        def _close(sender, args):
            try:
                window.Close()
            except Exception:
                pass
        close_button.Click += _close
    label = window.FindName('VersionLabel')
    if label is not None and version:
        label.Text = u'v{0}'.format(version)


def set_icon(window, image_name='IconImage', file_name='icon.png'):
    """Icons never take a tool down - loaded from bytes, never System.Uri."""
    try:
        path = os.path.join(HERE, file_name)
        if not os.path.isfile(path):
            return
        image = BitmapImage()
        image.BeginInit()
        image.StreamSource = MemoryStream(File.ReadAllBytes(path))
        image.CacheOption = BitmapCacheOption.OnLoad
        image.EndInit()
        try:
            image.Freeze()
        except Exception:
            pass
        holder = window.FindName(image_name)
        if holder is not None:
            holder.Source = image
        try:
            window.Icon = image
        except Exception:
            pass
    except Exception:
        pass


def own_by_revit(window):
    """Keep the window above Revit rather than letting it slip behind."""
    try:
        clr.AddReference('System.Windows.Forms')
        from System.Windows.Interop import WindowInteropHelper
        import Autodesk.Windows as adwin
        helper = WindowInteropHelper(window)
        helper.Owner = adwin.ComponentManager.ApplicationWindow
    except Exception:
        pass


# ------------------------------------------------------------------ dialogs

def prompt(owner, title, message, ok_text='OK', cancel_text='Cancel',
           input_default=None, theme=None):
    """Themed confirm / text-entry box. Returns None, True or the text."""
    window = load_window('VlookUpPrompt.xaml', None, theme)
    window.FindName('TitleLabel').Text = title
    window.FindName('MessageLabel').Text = message
    box = window.FindName('InputBox')
    if input_default is None:
        box.Visibility = Visibility.Collapsed
    else:
        box.Visibility = Visibility.Visible
        box.Text = input_default
    ok_button = window.FindName('OkBtn')
    cancel_button = window.FindName('CancelBtn')
    ok_button.Content = ok_text
    cancel_button.Content = cancel_text
    state = {'value': None}

    def _ok(sender, args):
        state['value'] = box.Text if input_default is not None else True
        window.Close()

    ok_button.Click += _ok
    cancel_button.Click += lambda s, a: window.Close()
    if owner is not None:
        try:
            window.Owner = owner
        except Exception:
            pass
    else:
        own_by_revit(window)
    try:
        if input_default is not None:
            window.Loaded += lambda s, a: (box.Focus(), box.SelectAll())
    except Exception:
        pass
    window.ShowDialog()
    return state['value']


def pick_open_file(title='Choose a spreadsheet', start=None):
    try:
        from Microsoft.Win32 import OpenFileDialog
        dialog = OpenFileDialog()
        dialog.Title = title
        dialog.Filter = ('Spreadsheets|*.xlsx;*.xlsm;*.csv;*.txt;*.tsv|'
                         'Excel workbook (*.xlsx;*.xlsm)|*.xlsx;*.xlsm|'
                         'Delimited text (*.csv;*.txt;*.tsv)|*.csv;*.txt;*.tsv|'
                         'All files (*.*)|*.*')
        if start and os.path.isdir(os.path.dirname(start)):
            dialog.InitialDirectory = os.path.dirname(start)
        if dialog.ShowDialog():
            return dialog.FileName
    except Exception:
        pass
    return None


def pick_save_file(title='Save report', default_name='vlookup_report.txt'):
    try:
        from Microsoft.Win32 import SaveFileDialog
        dialog = SaveFileDialog()
        dialog.Title = title
        dialog.FileName = default_name
        dialog.Filter = 'Text file (*.txt)|*.txt|All files (*.*)|*.*'
        if dialog.ShowDialog():
            return dialog.FileName
    except Exception:
        pass
    return None


def copy_to_clipboard(text):
    try:
        from System.Windows import Clipboard
        Clipboard.SetText(text)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ results

def _text_block(window, text, style_key='BodyText', wrap=True, margin=None):
    block = TextBlock()
    block.Text = text
    try:
        block.Style = window.FindResource(style_key)
    except Exception:
        pass
    if wrap:
        block.TextWrapping = TextWrapping.Wrap
    if margin is not None:
        block.Margin = margin
    return block


def _section(window, panel, heading, lines, limit=200, orange=False):
    if not lines:
        return
    row = StackPanel()
    row.Orientation = Orientation.Horizontal
    row.Margin = Thickness(0, 10, 0, 4)
    tick = Border()
    try:
        tick.Style = window.FindResource('TickOrange' if orange else 'TickBlue')
    except Exception:
        pass
    row.Children.Add(tick)
    row.Children.Add(_text_block(
        window, heading, 'SectionLabelOrange' if orange else 'SectionLabelBlue', False))
    panel.Children.Add(row)
    shown = lines[:limit]
    for line in shown:
        panel.Children.Add(_text_block(window, u'\u2022  ' + line, 'MutedText', True,
                                       Thickness(6, 1, 0, 1)))
    if len(lines) > limit:
        panel.Children.Add(_text_block(
            window, u'\u2026 and {0} more'.format(len(lines) - limit),
            'MutedText', False, Thickness(6, 2, 0, 1)))


def show_results(owner, version, summary, sections, footer='', theme=None,
                 subtitle='VlookUp results'):
    """sections: list of (heading, [lines], orange flag)."""
    window = load_window('VlookUpResults.xaml', version, theme)
    window.FindName('SubTitleLabel').Text = subtitle
    window.FindName('SummaryLabel').Text = summary
    window.FindName('FooterLabel').Text = footer
    panel = window.FindName('BodyPanel')

    report_lines = [summary, '']
    for heading, lines, orange in sections:
        if not lines:
            continue
        _section(window, panel, heading, lines, 200, orange)
        report_lines.append(heading)
        for line in lines:
            report_lines.append(u'    ' + line)
        report_lines.append('')
    if not panel.Children.Count:
        panel.Children.Add(_text_block(window, u'Nothing needed a second look.', 'MutedText'))

    report = u'\n'.join(report_lines)

    def _copy(sender, args):
        copy_to_clipboard(report)
        window.FindName('FooterLabel').Text = u'Copied to the clipboard.'

    def _save(sender, args):
        path = pick_save_file()
        if not path:
            return
        try:
            handle = open(path, 'w')
            try:
                handle.write(report.encode('utf-8'))
            finally:
                handle.close()
            window.FindName('FooterLabel').Text = u'Saved to {0}'.format(path)
        except Exception as err:
            window.FindName('FooterLabel').Text = u'Could not save: {0}'.format(err)

    window.FindName('CopyBtn').Click += _copy
    window.FindName('SaveBtn').Click += _save
    window.FindName('OkBtn').Click += lambda s, a: window.Close()
    if owner is not None:
        try:
            window.Owner = owner
        except Exception:
            pass
    else:
        own_by_revit(window)
    window.ShowDialog()
