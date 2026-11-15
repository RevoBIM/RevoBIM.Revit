# -*- coding: utf-8 -*-
"""RevoBIM PY - window plumbing shared by the Panel Template Mngr.

XAML loading, theme merging, custom chrome, full screen, icon loading and the
themed prompt.  Nothing in here touches the Revit API, so it can be exercised on
the bench by import_check.py.

Runs on IronPython 2.7 and IronPython 3: no f-strings, no print statements.
"""

import os

import pstm_clr                                                  # noqa: F401

from System import IntPtr                                            # noqa: E402
from System.IO import FileStream, FileMode, FileAccess, MemoryStream, File  # noqa: E402
from System.Windows import Window, Rect                              # noqa: E402
from System.Windows.Markup import XamlReader                         # noqa: E402
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption  # noqa: E402
from System.Windows.Interop import WindowInteropHelper               # noqa: E402
from System.Windows import PresentationSource                        # noqa: E402
from System.Windows.Forms import Screen                              # noqa: E402

import theme as theme_mod
import pstm_drawer as drawer_mod


HERE = os.path.dirname(__file__)
THEME_FILE = 'Theme.xaml'


# ---------------------------------------------------------------------------
# XAML
# ---------------------------------------------------------------------------

def _parse(path):
    stream = FileStream(path, FileMode.Open, FileAccess.Read)
    try:
        return XamlReader.Load(stream)
    finally:
        stream.Close()


def load_theme_dictionary():
    return _parse(os.path.join(HERE, THEME_FILE))


def load_window(xaml_name, palette_name='dark'):
    """Parse a layout file, merge Theme.xaml into it, apply the palette.

    Theme.xaml is merged *after* XamlReader has parsed the layout, which is why
    a layout may only ever use DynamicResource - a StaticResource would fail at
    load, and a failed load is the blank white pyRevit window.
    """
    window = _parse(os.path.join(HERE, xaml_name))
    try:
        window.Resources.MergedDictionaries.Add(load_theme_dictionary())
    except Exception:
        pass
    theme_mod.apply(window, palette_name)
    return window


# ---------------------------------------------------------------------------
# Chrome
# ---------------------------------------------------------------------------

def wire_drag(window, header_element, drawer=None):
    """Let the header bar drag a WindowStyle=None window.

    With a drawer, a double click on the parked bar brings the window back
    instead of being taken as the start of a drag.
    """
    def _drag(sender, args):
        if drawer is not None and drawer.on_header_down(args):
            return
        try:
            window.DragMove()
        except Exception:
            pass
    try:
        header_element.MouseLeftButtonDown += _drag
    except Exception:
        pass


def own_by_revit(window, main_window_handle):
    """Float above Revit rather than slipping behind it.

    An unowned modeless window that disappears behind Revit reads to the user
    as though the tool has crashed.
    """
    try:
        helper = WindowInteropHelper(window)
        helper.Owner = IntPtr(int(main_window_handle))
        return True
    except Exception:
        return False


class FullScreen(object):
    """Full screen by bounds, not WindowState.Maximized.

    A borderless AllowsTransparency window maximised the normal way covers the
    task bar and lands on the wrong monitor.
    """

    def __init__(self, window):
        self.window = window
        self.saved = None

    @property
    def is_full(self):
        return self.saved is not None

    def _dpi(self):
        try:
            src = PresentationSource.FromVisual(self.window)
            m = src.CompositionTarget.TransformToDevice
            return (m.M11 or 1.0), (m.M22 or 1.0)
        except Exception:
            return 1.0, 1.0

    def toggle(self):
        if self.saved is None:
            self.enter()
        else:
            self.leave()
        return self.is_full

    def enter(self):
        w = self.window
        try:
            self.saved = Rect(w.Left, w.Top, w.Width, w.Height)
            helper = WindowInteropHelper(w)
            screen = Screen.FromHandle(helper.Handle)
            area = screen.WorkingArea
            sx, sy = self._dpi()
            w.Left = area.Left / sx
            w.Top = area.Top / sy
            w.Width = area.Width / sx
            w.Height = area.Height / sy
        except Exception:
            self.saved = None

    def leave(self):
        if self.saved is None:
            return
        w = self.window
        try:
            w.Left = self.saved.Left
            w.Top = self.saved.Top
            w.Width = self.saved.Width
            w.Height = self.saved.Height
        except Exception:
            pass
        self.saved = None


# ---------------------------------------------------------------------------
# Icons.  System.Uri moved assemblies between .NET Framework 4.8 (Revit 2024)
# and .NET 8 (Revit 2025+) and throws ImportError at module load, so images are
# read from bytes rather than from BitmapImage.UriSource.
# ---------------------------------------------------------------------------

def bitmap_from_file(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        data = File.ReadAllBytes(path)
        stream = MemoryStream(data)
        img = BitmapImage()
        img.BeginInit()
        img.CacheOption = BitmapCacheOption.OnLoad
        img.StreamSource = stream
        img.EndInit()
        try:
            img.Freeze()
        except Exception:
            pass
        return img
    except Exception:
        return None


def set_image(image_control, filename):
    """Point an Image control at a file beside this module.  Decorative, so it
    is allowed to fail quietly - cosmetics must never take a tool down."""
    try:
        img = bitmap_from_file(os.path.join(HERE, filename))
        if img is not None:
            image_control.Source = img
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Themed prompt.  Results are reported in a themed window, never in the pyRevit
# output window.
# ---------------------------------------------------------------------------

class Prompt(object):
    """A small themed dialog.  Returns the index of the button pressed, or -1."""

    def __init__(self, owner, palette_name, title, message,
                 buttons=None, accent='blue', version=''):
        self.result = -1
        self.window = load_window('PstmPrompt.xaml', palette_name)
        drawer_mod.adopt(self.window, owner)
        w = self.window
        self.drawer = drawer_mod.Drawer(w)
        try:
            w.FindName('TitleText').Text = title
            w.FindName('MessageText').Text = message
            w.FindName('VersionText').Text = version
        except Exception:
            pass

        tick = w.FindName('AccentTick')
        try:
            from System.Windows.Controls import Border
            key = {'red': 'RedBrush', 'orange': 'OrangeBrush',
                   'green': 'GreenBrush'}.get(accent, 'BlueBrush')
            # through the class: a dependency property is static, and reaching
            # it through the instance is not reliable across engines
            tick.SetResourceReference(Border.BackgroundProperty, key)
        except Exception:
            pass

        wire_drag(w, w.FindName('HeaderBar'), self.drawer)
        try:
            w.FindName('CloseButton').Click += self._cancel
        except Exception:
            pass

        self._buttons = buttons or ['OK']
        host = w.FindName('ButtonHost')
        from System.Windows.Controls import Button
        from System.Windows import Thickness
        for i, spec in enumerate(self._buttons):
            label, style = (spec if isinstance(spec, tuple) else (spec, 'default'))
            btn = Button()
            btn.Content = label
            btn.Margin = Thickness(6, 0, 0, 0)
            btn.MinWidth = 92
            btn.Tag = i
            if style != 'default':
                try:
                    btn.SetResourceReference(
                        Button.StyleProperty,
                        {'primary': 'PrimaryButton',
                         'danger': 'DangerButton',
                         'accent': 'AccentButton'}.get(style, 'GhostButton'))
                except Exception:
                    pass
            btn.Click += self._pick
            host.Children.Add(btn)

    def _pick(self, sender, args):
        try:
            self.result = int(sender.Tag)
        except Exception:
            self.result = -1
        self.window.DialogResult = True

    def _cancel(self, sender, args):
        self.result = -1
        self.window.DialogResult = False

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            pass
        return self.result


class Choose(object):
    """Pick one thing out of a list.  Returns the chosen item, or None."""

    def __init__(self, owner, palette_name, title, message, choices,
                 ok_text='OK', version='', preselect=0):
        self.result = None
        self.window = load_window('PstmChoose.xaml', palette_name)
        drawer_mod.adopt(self.window, owner)
        w = self.window
        self.w = w
        self.drawer = drawer_mod.Drawer(w)
        try:
            w.FindName('TitleText').Text = title
            w.FindName('MessageText').Text = message
            w.FindName('VersionText').Text = version
            w.FindName('OkButton').Content = ok_text
        except Exception:
            pass

        listbox = w.FindName('ChoiceList')
        for item in choices:
            listbox.Items.Add(item)
        if listbox.Items.Count:
            listbox.SelectedIndex = min(preselect, listbox.Items.Count - 1)
        listbox.MouseDoubleClick += self._accept

        wire_drag(w, w.FindName('HeaderBar'), self.drawer)
        w.FindName('CloseButton').Click += self._cancel
        w.FindName('CancelButton').Click += self._cancel
        w.FindName('OkButton').Click += self._accept

    def _accept(self, sender, args):
        chosen = self.w.FindName('ChoiceList').SelectedItem
        if chosen is None:
            return
        self.result = chosen
        try:
            self.window.DialogResult = True
        except Exception:
            self.window.Close()

    def _cancel(self, sender, args):
        self.result = None
        try:
            self.window.DialogResult = False
        except Exception:
            self.window.Close()

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            pass
        return self.result


def choose(owner, palette_name, title, message, choices, ok_text='OK',
           version='', preselect=0):
    return Choose(owner, palette_name, title, message, choices, ok_text,
                  version, preselect).show()


class RenameRow(object):
    """One line of the rename preview.

    Read through a converter, not a property path: WPF cannot be relied on to
    see a plain Python attribute, which is why every other grid in this tool
    binds to `.` and pulls the value out in Python.
    """

    def __init__(self, old, new, note):
        self.old = old
        self.new = new
        self.note = note

    def value(self, key):
        if key == 'old':
            return self.old
        if key == 'new':
            return self.new
        return self.note


class Rename(object):
    """Find and replace, prefix and suffix, over a set of names.

    The preview is the point of the window: a batch rename is hard to undo by
    hand, so every row shows what it would become before anything is written,
    and a clash or an emptied name says so instead of being found out halfway
    through the run.

    Returns a list of (old_name, new_name) for the names that actually change,
    or None if the window was cancelled.
    """

    def __init__(self, owner, palette_name, names, core, version=''):
        self.core = core
        self.names = list(names)
        self.result = None
        self.rows = []
        self.window = load_window('PstmRename.xaml', palette_name)
        drawer_mod.adopt(self.window, owner)
        w = self.window
        self.w = w
        self.drawer = drawer_mod.Drawer(w)
        w.FindName('VersionText').Text = version
        w.FindName('MessageText').Text = (
            '{0} template{1} selected.  Nothing is renamed until you press '
            'Rename.'.format(len(self.names),
                             '' if len(self.names) == 1 else 's'))

        self._build_preview_columns()

        for name in ('FindBox', 'ReplaceBox', 'PrefixBox', 'SuffixBox'):
            w.FindName(name).TextChanged += self._changed
        w.FindName('MatchCaseCheck').Click += self._changed
        w.FindName('DropMasterCheck').Click += self._changed

        wire_drag(w, w.FindName('HeaderBar'), self.drawer)
        w.FindName('CloseButton').Click += self._cancel
        w.FindName('CancelButton').Click += self._cancel
        w.FindName('OkButton').Click += self._accept
        self._refresh()

    # -- preview ----------------------------------------------------------
    def _build_preview_columns(self):
        import pstm_grid as grid_mod

        self._text_conv = grid_mod.RowConverter(self._cell_text)
        self._back_conv = grid_mod.RowConverter(lambda row, key: None)
        self._fore_conv = grid_mod.RowConverter(self._cell_fore)

        grid = self.w.FindName('PreviewGrid')
        for title, key, star, minimum in (('Now', 'old', 1.0, 150),
                                          ('After the rename', 'new', 1.0, 150),
                                          ('', 'note', 0.8, 90)):
            cell = grid_mod.text_cell_template(self._text_conv, self._back_conv,
                                               self._fore_conv, key)
            grid.Columns.Add(grid_mod.make_column(title, cell, minimum, key,
                                                  minimum, star, False))

    @staticmethod
    def _cell_text(row, key):
        try:
            return row.value(str(key))
        except Exception:
            return ''

    def _cell_fore(self, row, key):
        from System.Windows.Media import Brushes
        try:
            if row.note:
                return Brushes.IndianRed if str(key) != 'old' else Brushes.Gray
        except Exception:
            pass
        try:
            return self.window.FindResource('TextBrush')
        except Exception:
            return Brushes.Gray

    def _values(self):
        w = self.w
        return {
            'find': w.FindName('FindBox').Text or '',
            'replace': w.FindName('ReplaceBox').Text or '',
            'match_case': bool(w.FindName('MatchCaseCheck').IsChecked),
            'prefix': w.FindName('PrefixBox').Text or '',
            'suffix': w.FindName('SuffixBox').Text or '',
            'strip_master': bool(w.FindName('DropMasterCheck').IsChecked),
        }

    def _changed(self, sender, args):
        self._refresh()

    def _refresh(self):
        from System.Collections.Generic import List
        values = self._values()
        preview = self.core.preview_rename(self.names, **values)
        items = List[object]()
        changing = 0
        trouble = 0
        for old, new, note in preview:
            if note:
                trouble += 1
            elif new != old:
                changing += 1
            items.Add(RenameRow(old, new, note))
        self.w.FindName('PreviewGrid').ItemsSource = items
        self.rows = preview

        bits = []
        if changing:
            bits.append('{0} will be renamed'.format(changing))
        else:
            bits.append('nothing would change yet')
        if trouble:
            bits.append('{0} cannot be (see the notes)'.format(trouble))
        self.w.FindName('CountText').Text = ', '.join(bits) + '.'
        self.w.FindName('OkButton').IsEnabled = changing > 0

    # -- buttons ----------------------------------------------------------
    def _accept(self, sender, args):
        self.result = [(old, new) for old, new, note in self.rows
                       if not note and new != old]
        try:
            self.window.DialogResult = True
        except Exception:
            self.window.Close()

    def _cancel(self, sender, args):
        self.result = None
        try:
            self.window.DialogResult = False
        except Exception:
            self.window.Close()

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            pass
        return self.result


def rename(owner, palette_name, names, core, version=''):
    return Rename(owner, palette_name, names, core, version).show()


def ask(owner, palette_name, title, message, buttons=None, accent='blue', version=''):
    return Prompt(owner, palette_name, title, message, buttons, accent, version).show()


def info(owner, palette_name, title, message, version=''):
    return Prompt(owner, palette_name, title, message, ['Close'], 'blue', version).show()
