# -*- coding: utf-8 -*-
"""Circuit Manager - the two prompts: a message box and the parameter picker.

Both are full RevoBIM windows: same header, theme chip and shrink drawer as
the main window. Shrinking a prompt takes the main window down with it, and
bringing it back brings the main window back behind it.
"""
import cm_clr  # noqa: F401

from System.Windows import Visibility, Thickness
from System.Windows.Controls import Button, CheckBox, TextBlock, StackPanel, \
    Orientation

import cm_logic
from cm_chrome import ThemedWindow


class MessageWindow(ThemedWindow):
    LAYOUT = 'Message.xaml'

    def __init__(self, owner, title, body, buttons):
        ThemedWindow.__init__(self, owner)
        self.choice = None
        self.find('title_text').Text = title
        self.find('body_text').Text = body
        panel = self.find('buttons_panel')
        for i, (label, style) in enumerate(buttons):
            btn = Button()
            tb = TextBlock()
            tb.Text = label
            btn.Content = tb
            btn.Margin = Thickness(8, 0, 0, 0)
            if style:
                btn.SetResourceReference(Button.StyleProperty, style)
            btn.Click += self._make_click(label)
            panel.Children.Add(btn)
            if i == len(buttons) - 1:
                btn.IsDefault = True

    def _make_click(self, label):
        def handler(sender, args):
            self.choice = label
            self.win.Close()
        return handler

    def on_key(self, args, key, ctrl, shift):
        if key == 'Escape':
            self.choice = None
            self.win.Close()
            args.Handled = True

    def show(self):
        self.win.ShowDialog()
        return self.choice


def ask(owner, title, body, buttons):
    """buttons: [(label, style key or None)] - the last is the default."""
    return MessageWindow(owner, title, body, buttons).show()


def tell(owner, title, body):
    return ask(owner, title, body, [(u'OK', 'GreenBtn')])


class ParamPicker(ThemedWindow):
    """Tick the circuit parameters to show as columns."""
    LAYOUT = 'ParamPicker.xaml'

    def __init__(self, owner, params, shown):
        ThemedWindow.__init__(self, owner)
        self.result = None
        self.items = []
        lst = self.find('list')
        for name, kind, writable in params:
            cb = CheckBox()
            cb.IsChecked = name in shown
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            t = TextBlock()
            t.Text = name
            row.Children.Add(t)
            hint = TextBlock()
            hint.Text = u'  editable' if writable else u'  read only'
            hint.SetResourceReference(TextBlock.ForegroundProperty,
                                      'Green' if writable else 'Hint')
            hint.FontSize = 11
            row.Children.Add(hint)
            cb.Content = row
            cb.Margin = Thickness(2, 2, 2, 2)
            cb.Checked += lambda s, a: self._count()
            cb.Unchecked += lambda s, a: self._count()
            lst.Items.Add(cb)
            self.items.append((name, cb))
        self.find('search_box').TextChanged += self._on_search
        self.find('all_btn').Click += lambda s, a: self._tick_shown(True)
        self.find('none_btn').Click += lambda s, a: self._tick_shown(False)
        self.find('ok_btn').Click += self._on_ok
        self.find('cancel_btn').Click += lambda s, a: self.win.Close()
        self._count()

    def _on_search(self, sender, args):
        term = self.find('search_box').Text
        for name, cb in self.items:
            cb.Visibility = Visibility.Visible \
                if cm_logic.matches_text(name, term) else Visibility.Collapsed

    def _tick_shown(self, value):
        """Acts on what the search is showing, the way Excel's list does."""
        for name, cb in self.items:
            if cb.Visibility == Visibility.Visible:
                cb.IsChecked = value

    def _count(self):
        n = len([1 for name, cb in self.items if cb.IsChecked])
        self.find('count_text').Text = u'{0} of {1} ticked'.format(
            n, len(self.items))

    def _on_ok(self, sender, args):
        self.result = [name for name, cb in self.items if cb.IsChecked]
        self.win.Close()

    def on_key(self, args, key, ctrl, shift):
        if key == 'Escape':
            self.win.Close()
            args.Handled = True

    def show(self):
        self.win.ShowDialog()
        return self.result
