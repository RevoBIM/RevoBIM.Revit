# -*- coding: utf-8 -*-
"""The themed prompt. Every question and result goes through this window, and
it shrinks like every other window."""
import fpp_clr  # noqa: F401  (must stay first)
from System.Windows import Clipboard, Visibility
from System.Windows.Controls import Button
from System.Windows.Input import Key

from fpp_chrome import ThemedWindow


class Prompt(ThemedWindow):
    def __init__(self, parent, title, message, buttons=None, copy_text=None,
                 input_text=None):
        self.answer = None
        self.copy_text = copy_text
        self.default = None
        ThemedWindow.__init__(self, 'Prompt.xaml', parent.settings, parent,
                              resizable=False)
        self.find('txt_title').Text = title
        self.find('txt_message').Text = message
        self.drawer.owner = parent.drawer
        parent.place_dialog(self.window)
        host = self.find('button_row')
        if copy_text:
            self.add_button(host, u'Copy', 'GhostBtn', self.on_copy)
        for label, value, style in buttons or [(u'OK', True, 'BlueBtn')]:
            host.Children.Add(self.make_button(label, value, style))
            if self.default is None:
                self.default = value
        self.window.Closed += self.safe(self.on_closed)
        self.input = None
        if input_text is not None:
            self.input = self.find('txt_input')
            self.input.Text = input_text
            self.input.Visibility = Visibility.Visible
            self.window.Loaded += self.safe(self.on_loaded)

    def on_loaded(self, sender, args):
        self.input.Focus()
        self.input.SelectAll()

    def sibling_names(self):
        return ['body_panel', 'footer_bar']

    def add_button(self, host, label, style, handler):
        button = Button()
        button.Content = label
        button.Style = self.window.FindResource(style)
        button.Click += self.safe(handler)
        host.Children.Add(button)

    def make_button(self, label, value, style):
        button = Button()
        button.Content = label
        button.Style = self.window.FindResource(style)
        def clicked(sender, args):
            self.answer = value
            self.window.Close()
        button.Click += self.safe(clicked)
        return button

    def on_copy(self, sender, args):
        Clipboard.SetText(self.copy_text)

    def on_key(self, args):
        if args.Key == Key.Escape:
            self.window.Close()
        elif args.Key == Key.Enter:
            self.answer = self.default
            self.window.Close()

    def on_closed(self, sender, args):
        self.drawer.settle()
        self.drawer.release_owner()

    def show(self):
        self.window.ShowDialog()
        return self.answer


def ask_text(parent, title, message, initial=u''):
    """The typed text, or None when cancelled."""
    prompt = Prompt(parent, title, message,
                    [(u'Save', True, 'GreenBtn'), (u'Cancel', False, 'GhostBtn')],
                    None, initial)
    return prompt.input.Text if prompt.show() else None


def tell(parent, title, message, copy_text=None):
    return Prompt(parent, title, message, None, copy_text).show()


def ask(parent, title, message, yes, no=u'Cancel'):
    buttons = [(yes, True, 'GreenBtn'), (no, False, 'GhostBtn')]
    return bool(Prompt(parent, title, message, buttons).show())
