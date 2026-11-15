# -*- coding: utf-8 -*-
"""RevoBIM PY - Wires settings window.

Every control is built from `wires_core.SCHEMA`, so adding a setting - the
power rules still to come, above all - means adding one row to that table and
nothing else. Standalone and modal, tabbed so each section fits without
scrolling.
"""

import clr

for _asm in ('PresentationCore', 'PresentationFramework', 'WindowsBase',
             'mscorlib', 'RevitAPIUI'):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

from System.Windows.Controls import (
    CheckBox, TextBox, ComboBox, Button, StackPanel, TextBlock, Border, Grid,
    ColumnDefinition, ScrollViewer, Orientation, Control,
)
from System.Windows import Thickness, GridLength, GridUnitType, TextWrapping

import wires_core as core
import wires_ui as ui


class SettingsWindow(object):

    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.doc = None
        try:
            self.doc = uiapp.ActiveUIDocument.Document
        except Exception:
            self.doc = None
        self.window = ui.load_window('WiresSettings.xaml')
        self.controls = {}          # key -> (kind, control, extra)
        self.cache = {}
        self.lookup_notes = []
        self.tab_buttons = {}
        self.tab_panels = {}
        self.current_tab = None
        ui.dress_header(self.window, core.__version__)
        ui.owned_by_revit(self.window)
        self._build()
        self._fill(core.load_settings())
        self._wire_buttons()
        self._link_tag_dropdowns()
        self._show_tab(core.TABS[0])
        if self.lookup_notes:
            self._status(' '.join(self.lookup_notes))

    # -- lists that come out of the model ------------------------------------
    # Each of these keeps the reason it came back empty, so the dialog can say
    # "no wire tag family is loaded" rather than the flatly wrong "none in
    # this model" the first version showed for a model full of them.
    def _wire_type_labels(self):
        if self.doc is None:
            self._remember('No document is open, so wire types cannot be read.')
            return []
        if 'wire_types' not in self.cache:
            pairs, note = core.wire_types(self.doc)
            self.cache['wire_types'] = pairs
            if not pairs:
                self._remember('Wire types: {0}.'.format(note))
        return [label for label, _element in self.cache['wire_types']]

    def _tag_rows(self):
        if self.doc is None:
            return []
        if 'tag_rows' not in self.cache:
            rows, note = core.wire_tag_types(self.doc)
            self.cache['tag_rows'] = rows
            if not rows:
                self._remember('Wire tags: {0}.'.format(note))
        return self.cache['tag_rows']

    def _tag_family_labels(self):
        names = []
        for family, _name, _symbol in self._tag_rows():
            if family not in names:
                names.append(family)
        return names

    def _tag_type_labels(self, family):
        rows = self._tag_rows()
        if family:
            names = [name for fam, name, _symbol in rows if fam == family]
            if names:
                return names
        return [name for _fam, name, _symbol in rows]

    def _line_style_labels(self):
        if 'line_styles' not in self.cache:
            pairs = []
            if self.doc is not None:
                pairs, note = core.line_styles(self.doc)
                if not pairs:
                    self._remember('Line styles: {0}.'.format(note))
            self.cache['line_styles'] = [label for label, _style in pairs]
        return list(self.cache['line_styles'])

    def _parameter_labels(self):
        """Parameters carried by the lighting fittings in this model.

        The saved value is always offered even when nothing in the model
        carries it - the parameter may simply not have been added yet, and a
        dropdown that silently dropped the house standard would be worse than
        one that offers a name with nothing behind it.
        """
        if 'parameters' not in self.cache:
            names = []
            if self.doc is not None:
                settings = core.load_settings()
                categories = []
                keys = [k.strip() for k in str(settings.get(
                    'lighting_categories', 'lighting_fixtures')).split(',')]
                for key, _label, bic_name in core.CATEGORY_DEFS:
                    if key in keys:
                        bic = core.builtin_category(bic_name)
                        if bic is not None:
                            categories.append(bic)
                names = core.fitting_parameter_names(self.doc, categories)
                if not names:
                    self._remember('No lighting fitting parameters could be '
                                   'read - is there a lighting fixture in '
                                   'this model?')
            self.cache['parameters'] = names
        names = list(self.cache['parameters'])
        for wanted in (core.load_settings().get('emergency_parameter', ''),
                       core.DEFAULTS.get('emergency_parameter', '')):
            if wanted and wanted not in names:
                names.insert(0, wanted)
        return names

    def _remember(self, note):
        if note and note not in self.lookup_notes:
            self.lookup_notes.append(note)

    def _current(self, key):
        """The value a dropdown is sitting on right now."""
        entry = self.controls.get(key)
        if entry is None:
            return ''
        _kind, control, _extra = entry
        try:
            values = str(control.Tag or '').split('\x1f')
            index = control.SelectedIndex
            if 0 <= index < len(values):
                return values[index]
        except Exception:
            pass
        return ''

    # -- building ------------------------------------------------------------
    def _build(self):
        strip = self.window.FindName('TabStrip')
        body = self.window.FindName('TabBody')
        if strip is None or body is None:
            return

        for tab in core.TABS:
            button = Button()
            button.Content = tab
            try:
                button.Style = self.window.FindResource('TabBtn')
            except Exception:
                pass
            button.Tag = tab
            button.Click += self._on_tab
            strip.Children.Add(button)
            self.tab_buttons[tab] = button

            panel = self._build_tab(tab)
            panel.Visibility = ui.hidden()
            body.Children.Add(panel)
            self.tab_panels[tab] = panel

    def _build_tab(self, tab):
        """Two columns of sections, balanced by how many rows each holds."""
        sections = []
        for row in core.SCHEMA:
            if row[0] != tab:
                continue
            if not sections or sections[-1][0] != row[1]:
                sections.append((row[1], []))
            sections[-1][1].append(row)

        grid = Grid()
        left = ColumnDefinition()
        left.Width = GridLength(1, GridUnitType.Star)
        gap = ColumnDefinition()
        gap.Width = GridLength(14)
        right = ColumnDefinition()
        right.Width = GridLength(1, GridUnitType.Star)
        for column in (left, gap, right):
            grid.ColumnDefinitions.Add(column)

        columns = [StackPanel(), StackPanel()]
        weights = [0, 0]
        for name, rows in sections:
            side = 0 if weights[0] <= weights[1] else 1
            weights[side] += len(rows) + 2
            columns[side].Children.Add(self._build_section(name, rows, side))

        for index, panel in enumerate(columns):
            Grid.SetColumn(panel, 0 if index == 0 else 2)
            grid.Children.Add(panel)
        return grid

    def _build_section(self, name, rows, side):
        card = Border()
        ui.paint(card, Border.BackgroundProperty, 'Card')
        ui.paint(card, Border.BorderBrushProperty, 'Edge')
        card.BorderThickness = Thickness(1)
        card.CornerRadius = ui.corner(4)
        card.Padding = Thickness(12, 10, 12, 10)
        card.Margin = Thickness(0, 0, 0, 12)

        stack = StackPanel()

        heading = StackPanel()
        heading.Orientation = Orientation.Horizontal
        heading.Margin = Thickness(0, 0, 0, 6)
        tick = Border()
        tick.Width = 4
        tick.Height = 16
        tick.CornerRadius = ui.corner(2)
        tick.Margin = Thickness(0, 0, 8, 0)
        ui.paint(tick, Border.BackgroundProperty,
                 'Blue' if side == 0 else 'Orange')
        heading.Children.Add(tick)
        label = TextBlock()
        label.Text = name
        label.FontSize = 13
        ui.paint(label, TextBlock.ForegroundProperty, 'Fg')
        heading.Children.Add(label)
        stack.Children.Add(heading)

        for row in rows:
            for child in self._build_row(row):
                stack.Children.Add(child)

        card.Child = stack
        return card

    def _label_block(self, text):
        block = TextBlock()
        block.Text = text
        block.FontSize = 12
        ui.paint(block, TextBlock.ForegroundProperty, 'Fg')
        block.TextWrapping = TextWrapping.Wrap
        block.Margin = Thickness(0, 0, 8, 0)
        return block

    def _pair(self, label, control, width):
        grid = Grid()
        first = ColumnDefinition()
        first.Width = GridLength(1, GridUnitType.Star)
        second = ColumnDefinition()
        second.Width = GridLength(width)
        grid.ColumnDefinitions.Add(first)
        grid.ColumnDefinitions.Add(second)
        grid.Margin = Thickness(0, 3, 0, 3)
        block = self._label_block(label)
        Grid.SetColumn(block, 0)
        grid.Children.Add(block)
        Grid.SetColumn(control, 1)
        grid.Children.Add(control)
        return grid

    def _build_row(self, row):
        _tab, _section, kind, key, label, _default, extra = row
        made = []

        if kind == 'note':
            made.append(ui.hint(extra))
            return made

        if kind in ('check', 'warn'):
            box = CheckBox()
            box.Content = label
            if kind == 'warn':
                try:
                    box.Style = self.window.FindResource('CheckWarn')
                except Exception:
                    pass
            self.controls[key] = (kind, box, extra)
            made.append(box)

        elif kind in ('number', 'text'):
            field = TextBox()
            self.controls[key] = (kind, field, extra)
            made.append(self._pair(label, field, 90 if kind == 'number' else 150))

        elif kind in ('choice', 'wiretype', 'tagfamily', 'tagtype', 'parameter',
                      'linestyle'):
            combo = ComboBox()
            self.controls[key] = (kind, combo, extra)
            made.append(self._pair(label, combo, 200))

        elif kind == 'categories':
            made.append(self._label_block(label))
            frame = Border()
            ui.paint(frame, Border.BackgroundProperty, 'Field')
            ui.paint(frame, Border.BorderBrushProperty, 'Edge')
            frame.BorderThickness = Thickness(1)
            frame.CornerRadius = ui.corner(3)
            frame.Height = 116
            frame.Margin = Thickness(0, 3, 0, 3)
            viewer = ScrollViewer()
            viewer.Padding = Thickness(8, 6, 8, 6)
            panel = StackPanel()
            boxes = []
            for name, category_label, bic_name in core.CATEGORY_DEFS:
                box = CheckBox()
                available = core.builtin_category(bic_name) is not None
                box.Content = category_label if available else \
                    '{0}  (not on this release)'.format(category_label)
                box.IsEnabled = available
                boxes.append((name, box))
                panel.Children.Add(box)
            viewer.Content = panel
            frame.Child = viewer
            self.controls[key] = (kind, boxes, extra)
            made.append(frame)

        if extra and kind not in ('note',):
            if kind != 'choice' or '=' not in str(extra):
                made.append(ui.hint(extra))
        return made

    # -- choice options ------------------------------------------------------
    def _options_for(self, kind, extra):
        """[(value, label), ...] for a dropdown."""
        if kind == 'wiretype':
            labels = self._wire_type_labels()
            if not labels:
                return [('', 'None found - see the note below')]
            return [(label, label) for label in labels]
        if kind == 'tagfamily':
            labels = self._tag_family_labels()
            if not labels:
                return [('', 'No wire tag family loaded')]
            return [(label, label) for label in labels]
        if kind == 'tagtype':
            labels = self._tag_type_labels(self._current('wire_tag_family'))
            if not labels:
                return [('', 'No wire tag family loaded')]
            return [(label, label) for label in labels]
        if kind == 'parameter':
            return [(label, label) for label in self._parameter_labels()]
        if kind == 'linestyle':
            labels = self._line_style_labels()
            if not labels:
                return [('', 'No line styles found')]
            return [('', '<the view default>')] + \
                [(label, label) for label in labels]
        options = []
        for part in str(extra).split('|'):
            part = part.strip()
            if not part:
                continue
            if '=' in part:
                value, label = part.split('=', 1)
                options.append((value.strip(), label.strip()))
            else:
                options.append((part, part))
        return options

    # -- filling and reading -------------------------------------------------
    def _fill(self, settings):
        for key in self.controls:
            kind, control, extra = self.controls[key]
            value = str(settings.get(key, core.DEFAULTS.get(key, '')))
            try:
                if kind in ('check', 'warn'):
                    control.IsChecked = value.strip().lower() in (
                        'yes', 'true', '1', 'on')
                elif kind in ('number', 'text'):
                    control.Text = value
                elif kind in ('choice', 'wiretype', 'tagfamily', 'tagtype', 'parameter',
                      'linestyle'):
                    options = self._options_for(kind, extra)
                    control.Items.Clear()
                    control.Tag = '\x1f'.join([pair[0] for pair in options])
                    for _value, label in options:
                        control.Items.Add(label)
                    index = 0
                    for position, pair in enumerate(options):
                        if pair[0] == value:
                            index = position
                            break
                    control.SelectedIndex = index
                elif kind == 'categories':
                    wanted = [k.strip() for k in value.split(',') if k.strip()]
                    for name, box in control:
                        box.IsChecked = name in wanted
            except Exception:
                pass

    def _collect(self):
        settings = core.load_settings()
        for key in self.controls:
            kind, control, _extra = self.controls[key]
            try:
                if kind in ('check', 'warn'):
                    settings[key] = 'yes' if bool(control.IsChecked) else 'no'
                elif kind == 'number':
                    settings[key] = _number(control.Text,
                                            core.DEFAULTS.get(key, '0'))
                elif kind == 'text':
                    settings[key] = str(control.Text).strip()
                elif kind in ('choice', 'wiretype', 'tagfamily', 'tagtype', 'parameter',
                      'linestyle'):
                    values = str(control.Tag or '').split('\x1f')
                    index = control.SelectedIndex
                    if 0 <= index < len(values):
                        settings[key] = values[index]
                elif kind == 'categories':
                    ticked = [name for name, box in control
                              if bool(box.IsChecked) and box.IsEnabled]
                    if ticked:
                        settings[key] = ','.join(ticked)
            except Exception:
                pass
        return settings

    # -- behaviour -----------------------------------------------------------
    def _show_tab(self, tab):
        self.current_tab = tab
        for name in self.tab_panels:
            try:
                self.tab_panels[name].Visibility = \
                    ui.visible() if name == tab else ui.hidden()
            except Exception:
                pass
        for name in self.tab_buttons:
            button = self.tab_buttons[name]
            try:
                if name == tab:
                    ui.paint(button, Control.BorderBrushProperty, 'Blue')
                    ui.paint(button, Control.ForegroundProperty, 'Fg')
                else:
                    # back to the TabBtn style: no underline, muted text
                    button.ClearValue(Control.BorderBrushProperty)
                    button.ClearValue(Control.ForegroundProperty)
            except Exception:
                pass

    def _link_tag_dropdowns(self):
        """The type list follows the family - they are not independent."""
        entry = self.controls.get('wire_tag_family')
        if entry is None:
            return
        try:
            entry[1].SelectionChanged += self._on_tag_family
        except Exception:
            pass

    def _on_tag_family(self, sender, args):
        entry = self.controls.get('wire_tag_type')
        if entry is None:
            return
        _kind, combo, extra = entry
        wanted = self._current('wire_tag_type')
        options = self._options_for('tagtype', extra)
        try:
            combo.Items.Clear()
            combo.Tag = '\x1f'.join([pair[0] for pair in options])
            for _value, label in options:
                combo.Items.Add(label)
            index = 0
            for position, pair in enumerate(options):
                if pair[0] == wanted:
                    index = position
                    break
            combo.SelectedIndex = index
        except Exception:
            pass

    def _on_tab(self, sender, args):
        try:
            self._show_tab(str(sender.Tag))
        except Exception:
            pass

    def _status(self, text):
        try:
            label = self.window.FindName('StatusText')
            if label is not None:
                label.Text = text
        except Exception:
            pass

    def _wire_buttons(self):
        for name, handler in (('ApplyButton', self._on_apply),
                              ('CancelButton', self._on_cancel),
                              ('DefaultsButton', self._on_defaults),
                              ('ShortcutsButton', self._on_shortcuts)):
            try:
                button = self.window.FindName(name)
                if button is not None:
                    button.Click += handler
            except Exception:
                pass

    def _on_apply(self, sender, args):
        if core.save_settings(self._collect()):
            try:
                self.window.Close()
            except Exception:
                pass
        else:
            self._status('Could not write {0}'.format(core.SETTINGS_PATH))

    def _on_cancel(self, sender, args):
        try:
            self.window.Close()
        except Exception:
            pass

    def _on_defaults(self, sender, args):
        fresh = {}
        for key in core.DEFAULTS:
            fresh[key] = core.DEFAULTS[key]
        self._fill(fresh)
        self._status('Defaults loaded on every tab. Apply to keep them.')

    def _on_shortcuts(self, sender, args):
        """Close first, then post - a posted command waits on the modal."""
        try:
            self.window.Close()
        except Exception:
            pass
        try:
            from Autodesk.Revit.UI import RevitCommandId, PostableCommand
            command = RevitCommandId.LookupPostableCommandId(
                PostableCommand.KeyboardShortcuts)
            if command is not None:
                self.uiapp.PostCommand(command)
        except Exception:
            pass

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            pass


def _number(text, fallback):
    try:
        value = float(str(text).strip())
        if value < 0:
            return fallback
        return '{0:g}'.format(value)
    except Exception:
        return fallback


def show(uiapp):
    SettingsWindow(uiapp).show()
