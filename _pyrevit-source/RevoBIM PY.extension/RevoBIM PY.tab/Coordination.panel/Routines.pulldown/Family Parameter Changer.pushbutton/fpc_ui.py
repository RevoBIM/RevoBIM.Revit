# -*- coding: utf-8 -*-
"""RevoBIM PY - Family Parameter Changer - UI.

XAML loading, window chrome (drag, resize grips, full screen), theming,
the category-grouped family list, the parameter table, the shared
parameter picker and the Apply flow.

Rows are built as WPF elements in code rather than bound to Python
objects - the same call Fire Damper Wall Type Push made, because binding
to IronPython objects is unreliable across engine versions.
"""
import fpc_clr  # noqa - assemblies referenced before anything below

import os

from System import Action
from System.IO import File, MemoryStream, StringReader
from System.Windows import (
    Thickness, CornerRadius, GridLength, GridUnitType, Visibility,
    TextWrapping, TextTrimming, VerticalAlignment,
)
from System.Windows.Controls import (
    Border, Grid, ColumnDefinition, TextBlock, Button, StackPanel, Orientation,
)
from System.Windows.Input import Cursors
from System.Windows.Markup import XamlReader
from System.Windows.Media import Stretch
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Shapes import Path as ShapePath
from System.Windows.Media import Geometry
from System.Xml import XmlReader

import fpc_core
import fpc_model
import theme as theme_mod


# ==================== xaml loading ====================

def load_xaml(path):
    f = open(path, 'r')
    try:
        text = f.read()
    finally:
        f.close()
    return XamlReader.Load(XmlReader.Create(StringReader(text)))


def _theme_dict(this_dir):
    return load_xaml(os.path.join(this_dir, 'Theme.xaml'))


def dress(window, this_dir, theme_name):
    """Merges Theme.xaml in after the layout has parsed, then writes the
    palette onto window.Resources. Layouts may only use DynamicResource
    for exactly this reason."""
    window.Resources.MergedDictionaries.Add(_theme_dict(this_dir))
    theme_mod.apply(window, theme_name)
    stamp = window.FindName('VersionText')
    if stamp is not None:
        stamp.Text = u'v{0}'.format(fpc_core.__version__)
    return window


def load_icon(path):
    """Images load from bytes through a MemoryStream, never from
    BitmapImage.UriSource - System.Uri moved assemblies in Revit 2025 and
    `from System import Uri` throws ImportError at module load there."""
    image = BitmapImage()
    image.BeginInit()
    image.StreamSource = MemoryStream(File.ReadAllBytes(path))
    image.CacheOption = BitmapCacheOption.OnLoad
    image.EndInit()
    image.Freeze()
    return image


def set_header_icon(window, this_dir):
    # Cosmetics can never take a tool down.
    try:
        target = window.FindName('HeaderIcon')
        if target is None:
            return
        icon_path = os.path.join(this_dir, 'icon.png')
        if os.path.isfile(icon_path):
            target.Source = load_icon(icon_path)
            target.Stretch = Stretch.Uniform
    except Exception:
        pass


# ==================== chrome ====================

def _hwnd(window):
    from System.Windows.Interop import WindowInteropHelper
    return WindowInteropHelper(window).Handle


def own_to_revit(window, uiapp):
    try:
        from System.Windows.Interop import WindowInteropHelper
        WindowInteropHelper(window).Owner = uiapp.MainWindowHandle
    except Exception:
        pass


def wire_drag(window):
    header = window.FindName('HeaderBar')
    if header is None:
        return
    def _drag(sender, e):
        try:
            window.DragMove()
        except Exception:
            pass
    header.MouseLeftButtonDown += _drag


def wire_close(window, close_action=None):
    btn = window.FindName('CloseButton')
    if btn is None:
        return
    def _close(sender, e):
        if close_action is not None:
            close_action()
        else:
            window.Close()
    btn.Click += _close


def wire_resize(window):
    edges = {
        'ThumbTop': 'T', 'ThumbBottom': 'B', 'ThumbLeft': 'L', 'ThumbRight': 'R',
        'ThumbTopLeft': 'TL', 'ThumbTopRight': 'TR',
        'ThumbBottomLeft': 'BL', 'ThumbBottomRight': 'BR',
    }

    def make_handler(edge):
        def handler(sender, e):
            try:
                left, top = window.Left, window.Top
                width, height = window.Width, window.Height
                if 'L' in edge:
                    new_w = width - e.HorizontalChange
                    if new_w < window.MinWidth:
                        new_w = window.MinWidth
                    left = left + (width - new_w)
                    width = new_w
                if 'R' in edge:
                    width = width + e.HorizontalChange
                    if width < window.MinWidth:
                        width = window.MinWidth
                if 'T' in edge:
                    new_h = height - e.VerticalChange
                    if new_h < window.MinHeight:
                        new_h = window.MinHeight
                    top = top + (height - new_h)
                    height = new_h
                if 'B' in edge:
                    height = height + e.VerticalChange
                    if height < window.MinHeight:
                        height = window.MinHeight
                window.Left, window.Top = left, top
                window.Width, window.Height = width, height
            except Exception:
                pass
        return handler

    for name in edges:
        thumb = window.FindName(name)
        if thumb is not None:
            thumb.DragDelta += make_handler(edges[name])


def wire_fullscreen(window):
    """Full screen by bounds, not WindowState.Maximized - a borderless
    AllowsTransparency window maximised the normal way covers the taskbar
    and lands on the wrong monitor."""
    state = {'full': False, 'bounds': None}

    def toggle(sender=None, e=None):
        if not state['full']:
            state['bounds'] = (window.Left, window.Top, window.Width, window.Height)
            dpi_x, dpi_y = 1.0, 1.0
            try:
                from System.Windows import PresentationSource
                source = PresentationSource.FromVisual(window)
                if source is not None:
                    dpi_x = source.CompositionTarget.TransformToDevice.M11
                    dpi_y = source.CompositionTarget.TransformToDevice.M22
            except Exception:
                pass
            try:
                import System.Windows.Forms as WinForms
                area = WinForms.Screen.FromHandle(_hwnd(window)).WorkingArea
                window.Left = area.Left / dpi_x
                window.Top = area.Top / dpi_y
                window.Width = area.Width / dpi_x
                window.Height = area.Height / dpi_y
                state['full'] = True
            except Exception:
                state['bounds'] = None
        else:
            if state['bounds'] is not None:
                b = state['bounds']
                window.Left, window.Top, window.Width, window.Height = b[0], b[1], b[2], b[3]
            state['full'] = False

    btn = window.FindName('FullScreenButton')
    if btn is not None:
        btn.Click += toggle

    header = window.FindName('HeaderBar')
    if header is not None:
        def dbl(sender, e):
            if e.ClickCount == 2:
                toggle()
        header.MouseLeftButtonDown += dbl

    return toggle


# ==================== small builders ====================

def _text(value, size=12.5, brush='TextBrush', bold=False):
    tb = TextBlock()
    tb.Text = value
    tb.FontSize = size
    tb.SetResourceReference(TextBlock.ForegroundProperty, brush)
    if bold:
        from System.Windows import FontWeights
        tb.FontWeight = FontWeights.SemiBold
    return tb


def _chevron(expanded):
    """Collapse/expand arrow drawn from a Path, never a symbol font - a
    machine without that font renders an empty box."""
    path = ShapePath()
    if expanded:
        path.Data = Geometry.Parse('M0,2 L5,7 L10,2')
    else:
        path.Data = Geometry.Parse('M2,0 L7,5 L2,10')
    path.StrokeThickness = 1.6
    path.SetResourceReference(ShapePath.StrokeProperty, 'MutedTextBrush')
    path.VerticalAlignment = VerticalAlignment.Center
    path.Width = 11
    path.Height = 11
    return path


# ==================== controller ====================
# ==================== controller ====================

class MainController(object):

    def __init__(self, window, this_dir, families, doc, handler, ext_event,
                 settings, theme_name, uiapp):
        self.window = window
        self.this_dir = this_dir
        self.families = families
        self.doc = doc
        self.handler = handler
        self.ext_event = ext_event
        self.settings = settings
        self.theme_name = theme_name
        self.uiapp = uiapp

        # every attribute initialised here, before any method can read it
        self.selected_key = None
        self.pending = {}
        self.family_rows = {}
        self.family_subs = {}
        self.category_tails = {}
        self.category_members = {}
        self.collapsed = set()
        self.busy = False
        self.cancel_requested = False
        self.close_after_run = False
        self.run_total = 0
        self.run_done = 0
        self.run_results = []
        self.run_keys = []
        self.toggle_fullscreen = None
        self.family_timer = None
        self.param_timer = None

        find = self.window.FindName
        self.family_panel = find('FamilyListPanel')
        self.param_panel = find('ParamListPanel')
        self.family_search = find('FamilySearchBox')
        self.param_search = find('ParamSearchBox')
        self.selected_header = find('SelectedFamilyHeader')
        self.status_text = find('StatusText')
        self.apply_btn = find('ApplyButton')
        self.cancel_btn = find('CancelRunButton')
        self.refresh_btn = find('RefreshButton')
        self.clear_btn = find('ClearPendingButton')
        self.theme_btn = find('ThemeToggleButton')
        self.expand_btn = find('ExpandAllButton')
        self.bulk_btn = find('BulkButton')
        self.settings_btn = find('SettingsButton')
        self.body_grid = find('BodyGrid')
        self.progress_strip = find('ProgressStrip')
        self.progress_done = find('ProgressDone')
        self.progress_rest = find('ProgressRest')
        self.progress_text = find('ProgressText')

    # ---------- wiring ----------

    def wire(self):
        set_header_icon(self.window, self.this_dir)
        wire_drag(self.window)
        wire_close(self.window, close_action=self.on_close)
        wire_resize(self.window)
        self.toggle_fullscreen = wire_fullscreen(self.window)

        self.family_timer = self._debounce(250, self._family_search_now)
        self.param_timer = self._debounce(250, self._param_search_now)
        self.family_search.TextChanged += lambda s, e: self._restart(self.family_timer)
        self.param_search.TextChanged += lambda s, e: self._restart(self.param_timer)

        self.apply_btn.Click += self._on_apply
        self.cancel_btn.Click += self._on_cancel
        self.refresh_btn.Click += self._on_refresh
        self.clear_btn.Click += self._on_clear
        self.theme_btn.Click += self._on_theme_toggle
        self.expand_btn.Click += self._on_expand_all
        self.bulk_btn.Click += self._on_bulk
        self.settings_btn.Click += self._on_settings
        self.window.KeyDown += self._on_key

        self._sync_theme_chip()
        self.rebuild_family_list()
        self._refresh_footer()

    def _debounce(self, milliseconds, action):
        """A DispatcherTimer that fires `action` once, `milliseconds` after
        the last restart - so typing in a search box re-filters once per
        pause rather than once per keystroke."""
        from System import TimeSpan
        from System.Windows.Threading import DispatcherTimer
        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromMilliseconds(milliseconds)

        def _tick(sender, e):
            timer.Stop()
            try:
                action()
            except Exception:
                pass
        timer.Tick += _tick
        return timer

    def _restart(self, timer):
        timer.Stop()
        timer.Start()

    def _on_key(self, sender, e):
        try:
            from System.Windows.Input import Key
            if e.Key == Key.F11 and self.toggle_fullscreen is not None:
                self.toggle_fullscreen()
            elif e.Key == Key.F5:
                self._on_refresh(None, None)
        except Exception:
            pass

    def set_status(self, text):
        self.status_text.Text = text

    # ---------- family list, grouped by category ----------

    def _categories(self):
        seen = []
        for fam in self.families:
            if fam['category'] not in seen:
                seen.append(fam['category'])
        return seen

    def _grouped(self, filter_text):
        """[(category, [family, ...]), ...] in category order with the
        filter applied. A category whose own name matches keeps all of
        its families."""
        ft = filter_text.strip().lower()
        order = []
        index = {}
        for fam in self.families:
            cat = fam['category']
            if ft and ft not in fam['name'].lower() and ft not in cat.lower():
                continue
            if cat not in index:
                index[cat] = []
                order.append(cat)
            index[cat].append(fam)
        return [(cat, index[cat]) for cat in order]

    def _queued_count(self, key):
        return len(self.pending.get(key, {}).get('changes', {}))

    def _category_queued(self, category):
        total = 0
        for fam in self.category_members.get(category, []):
            total += self._queued_count(fam['key'])
        return total

    def _tail_text(self, category, count):
        queued = self._category_queued(category)
        if queued:
            return u'{0} queued  .  {1}'.format(queued, count), 'OrangeBrush'
        return u'{0}'.format(count), 'MutedTextBrush'

    def _category_header(self, category, members, expanded):
        outer = Border()
        outer.Padding = Thickness(7, 6, 8, 6)
        outer.Margin = Thickness(0, 0, 0, 2)
        outer.CornerRadius = CornerRadius(4)
        outer.Cursor = Cursors.Hand
        outer.SetResourceReference(Border.BackgroundProperty, 'FieldBg')

        grid = Grid()
        chev_col = ColumnDefinition()
        chev_col.Width = GridLength.Auto
        name_col = ColumnDefinition()
        name_col.Width = GridLength(1.0, GridUnitType.Star)
        count_col = ColumnDefinition()
        count_col.Width = GridLength.Auto
        grid.ColumnDefinitions.Add(chev_col)
        grid.ColumnDefinitions.Add(name_col)
        grid.ColumnDefinitions.Add(count_col)

        chev = _chevron(expanded)
        Grid.SetColumn(chev, 0)
        grid.Children.Add(chev)

        label = _text(category, 12.5, 'BlueBrush', bold=True)
        label.Margin = Thickness(7, 0, 6, 0)
        label.TextTrimming = TextTrimming.CharacterEllipsis
        label.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(label, 1)
        grid.Children.Add(label)

        text, brush = self._tail_text(category, len(members))
        tail = _text(text, 10.5, brush)
        tail.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(tail, 2)
        grid.Children.Add(tail)
        self.category_tails[category] = (tail, len(members))

        outer.Child = grid

        def _toggle(sender, e):
            if self.busy:
                return
            if category in self.collapsed:
                self.collapsed.discard(category)
            else:
                self.collapsed.add(category)
            self.rebuild_family_list(self.family_search.Text)
        outer.MouseLeftButtonUp += _toggle
        return outer

    def _sub_text(self, fam):
        queued = self._queued_count(fam['key'])
        if fam.get('blocked'):
            return u'{0} - cannot be rebound'.format(fam['blocked']), 'RedBrush'
        if queued:
            return u'{0} parameter(s) queued'.format(queued), 'OrangeBrush'
        return u'{0} parameter(s)'.format(len(fam['params'])), 'MutedTextBrush'

    def _family_row(self, fam):
        key = fam['key']
        outer = Border()
        outer.Padding = Thickness(8, 5, 8, 5)
        outer.Margin = Thickness(16, 0, 0, 2)
        outer.CornerRadius = CornerRadius(4)
        outer.Cursor = Cursors.Hand
        outer.BorderThickness = Thickness(1)

        stack = StackPanel()
        name_tb = _text(fam['name'], 12.5, 'TextBrush')
        name_tb.TextTrimming = TextTrimming.CharacterEllipsis
        stack.Children.Add(name_tb)

        text, brush = self._sub_text(fam)
        sub = _text(text, 10.5, brush)
        stack.Children.Add(sub)
        outer.Child = stack

        def _click(sender, e):
            if self.busy:
                return
            self.select_family(fam)
        outer.MouseLeftButtonUp += _click

        self.family_rows[key] = outer
        self.family_subs[key] = sub
        self._paint_family_row(key)
        return outer

    def _paint_family_row(self, key):
        """Repaints one family row from current state - selection,
        queued changes - without rebuilding the list."""
        row = self.family_rows.get(key)
        if row is None:
            return
        if key == self.selected_key:
            row.SetResourceReference(Border.BackgroundProperty, 'SelectionBrush')
        else:
            row.SetResourceReference(Border.BackgroundProperty, 'CardBg')
        if self._queued_count(key):
            row.SetResourceReference(Border.BorderBrushProperty, 'OrangeBrush')
        else:
            row.SetResourceReference(Border.BorderBrushProperty, 'CardBg')
        sub = self.family_subs.get(key)
        fam = self._find_family(key)
        if sub is not None and fam is not None:
            text, brush = self._sub_text(fam)
            sub.Text = text
            sub.SetResourceReference(TextBlock.ForegroundProperty, brush)

    def _paint_category(self, category):
        entry = self.category_tails.get(category)
        if entry is None:
            return
        tail, count = entry
        text, brush = self._tail_text(category, count)
        tail.Text = text
        tail.SetResourceReference(TextBlock.ForegroundProperty, brush)

    def rebuild_family_list(self, filter_text=u''):
        self.family_panel.Children.Clear()
        self.family_rows = {}
        self.family_subs = {}
        self.category_tails = {}
        self.category_members = {}
        groups = self._grouped(filter_text)
        searching = bool(filter_text.strip())

        for category, members in groups:
            self.category_members[category] = members
            expanded = searching or category not in self.collapsed
            self.family_panel.Children.Add(self._category_header(category, members, expanded))
            if not expanded:
                continue
            for fam in members:
                self.family_panel.Children.Add(self._family_row(fam))

        if not groups:
            empty = _text(u'No family matches that search.', 12, 'MutedTextBrush')
            empty.Margin = Thickness(8, 8, 8, 8)
            empty.TextWrapping = TextWrapping.Wrap
            self.family_panel.Children.Add(empty)

    def _family_search_now(self):
        self.rebuild_family_list(self.family_search.Text)

    def _on_expand_all(self, sender, e):
        if self.busy:
            return
        if self.collapsed:
            self.collapsed = set()
            self.expand_btn.Content = u'Collapse all'
        else:
            self.collapsed = set(self._categories())
            self.expand_btn.Content = u'Expand all'
        self.rebuild_family_list(self.family_search.Text)

    # ---------- parameter table ----------

    def _find_family(self, key):
        if key is None:
            return None
        for fam in self.families:
            if fam['key'] == key:
                return fam
        return None

    def select_family(self, fam):
        previous = self.selected_key
        self.selected_key = fam['key']
        self._paint_family_row(previous)
        self._paint_family_row(self.selected_key)
        self.selected_header.Text = u'{0}   -   {1}'.format(fam['name'], fam['category'])
        self.param_search.Text = u''
        self.rebuild_param_table()

    def _param_row(self, fam, prow):
        outer = Border()
        outer.Padding = Thickness(8, 6, 8, 6)
        outer.Margin = Thickness(0, 0, 0, 2)
        outer.CornerRadius = CornerRadius(4)
        outer.BorderThickness = Thickness(1)
        outer.SetResourceReference(Border.BackgroundProperty, 'CardBg')
        outer.SetResourceReference(Border.BorderBrushProperty, 'CardBg')
        if prow.get('storage'):
            outer.ToolTip = u'{0}  .  {1}'.format(prow['name'], prow['storage'])

        grid = Grid()
        for star, minimum in ((2.2, 130), (0.8, 62), (2.2, 140), (1.7, 150)):
            cd = ColumnDefinition()
            cd.Width = GridLength(star, GridUnitType.Star)
            cd.MinWidth = minimum
            grid.ColumnDefinitions.Add(cd)

        name_tb = _text(prow['name'], 12.5, 'TextBrush')
        name_tb.TextTrimming = TextTrimming.CharacterEllipsis
        name_tb.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(name_tb, 0)
        grid.Children.Add(name_tb)

        kind_tb = _text(u'Type' if prow['is_type'] else u'Instance', 11.5, 'MutedTextBrush')
        kind_tb.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(kind_tb, 1)
        grid.Children.Add(kind_tb)

        if prow['is_shared']:
            bound = _text(u'Shared parameter', 11.5, 'GreenBrush')
        else:
            bound = _text(u'Family parameter', 11.5, 'MutedTextBrush')
        bound.TextWrapping = TextWrapping.Wrap
        bound.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(bound, 2)
        grid.Children.Add(bound)

        actions = StackPanel()
        actions.Orientation = Orientation.Horizontal
        actions.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(actions, 3)

        pick_btn = Button()
        pick_btn.Content = u'Rebind...'
        pick_btn.Padding = Thickness(9, 3, 9, 3)
        pick_btn.FontSize = 11.5
        pick_btn.SetResourceReference(Button.StyleProperty, 'GhostButtonStyle')

        status_tb = _text(u'', 11, 'OrangeBrush')
        status_tb.Margin = Thickness(7, 0, 0, 0)
        status_tb.VerticalAlignment = VerticalAlignment.Center
        status_tb.TextTrimming = TextTrimming.CharacterEllipsis

        if fam.get('blocked'):
            pick_btn.IsEnabled = False
            pick_btn.ToolTip = u'This family cannot be rebound: {0}.'.format(fam['blocked'])
        else:
            def _pick(sender, e):
                if self.busy:
                    return
                self.pick_for_row(fam, prow, outer, status_tb, pick_btn)
            pick_btn.Click += _pick

        actions.Children.Add(pick_btn)
        actions.Children.Add(status_tb)
        grid.Children.Add(actions)

        outer.Child = grid
        return outer, status_tb, pick_btn

    def rebuild_param_table(self, filter_text=u''):
        self.param_panel.Children.Clear()
        fam = self._find_family(self.selected_key)
        if fam is None:
            hint = _text(u'Select a family on the left to list its parameters.', 12, 'MutedTextBrush')
            hint.Margin = Thickness(8, 8, 8, 8)
            hint.TextWrapping = TextWrapping.Wrap
            self.param_panel.Children.Add(hint)
            return

        if fam.get('blocked'):
            note = _text(u'This family is {0} and cannot be opened for editing, so its parameters cannot be rebound.'.format(
                fam['blocked']), 12, 'RedBrush')
            note.Margin = Thickness(8, 8, 8, 4)
            note.TextWrapping = TextWrapping.Wrap
            self.param_panel.Children.Add(note)

        ft = filter_text.strip().lower()
        shown = 0
        queued = self.pending.get(self.selected_key, {}).get('changes', {})
        for prow in fam['params']:
            if ft and ft not in prow['name'].lower():
                continue
            outer, status_tb, pick_btn = self._param_row(fam, prow)
            self.param_panel.Children.Add(outer)
            shown += 1
            change = queued.get(prow['name'])
            if change is not None:
                self._mark_pending(outer, status_tb, pick_btn, change['shared_name'])

        if shown == 0:
            empty = _text(u'No parameter matches that search.', 12, 'MutedTextBrush')
            empty.Margin = Thickness(8, 8, 8, 8)
            self.param_panel.Children.Add(empty)

    def _param_search_now(self):
        self.rebuild_param_table(self.param_search.Text)

    def _mark_pending(self, outer, status_tb, pick_btn, shared_name):
        outer.SetResourceReference(Border.BackgroundProperty, 'FieldBg')
        outer.SetResourceReference(Border.BorderBrushProperty, 'OrangeBrush')
        status_tb.Text = shared_name
        pick_btn.Content = u'Change...'

    # ---------- picking ----------

    def pick_for_row(self, fam, prow, outer, status_tb, pick_btn):
        chosen = pick_shared_parameter(self.window, self.this_dir, self.theme_name, self.uiapp)
        if chosen is None:
            return
        key = fam['key']
        if key not in self.pending:
            self.pending[key] = {'family_name': fam['name'], 'changes': {}}
        name = fpc_core.shared_param_display_name(chosen)
        self.pending[key]['changes'][prow['name']] = {
            'param_name': prow['name'],
            'shared_guid': fpc_core.shared_param_guid(chosen),
            'shared_name': name,
        }
        self._mark_pending(outer, status_tb, pick_btn, name)
        # repaint only what changed - not the whole list
        self._paint_family_row(key)
        self._paint_category(fam['category'])
        self._refresh_footer()

    def _pending_total(self):
        total = 0
        for key in self.pending:
            total += len(self.pending[key]['changes'])
        return total

    def _refresh_footer(self):
        total = self._pending_total()
        self.apply_btn.IsEnabled = total > 0 and not self.busy
        self.clear_btn.IsEnabled = total > 0 and not self.busy
        if self.busy:
            return
        if total:
            self.set_status(u'{0} parameter(s) queued across {1} famil(y/ies). Nothing is written until Apply.'.format(
                total, len(self.pending)))
        else:
            self.set_status(u'{0} families in {1} categories.'.format(
                len(self.families), len(self._categories())))

    def _on_clear(self, sender, e):
        if self.busy:
            return
        self.pending = {}
        self.rebuild_family_list(self.family_search.Text)
        self.rebuild_param_table(self.param_search.Text)
        self._refresh_footer()

    # ---------- bulk ----------

    def _on_bulk(self, sender, e):
        if self.busy:
            return
        plan = pick_bulk(self.window, self.this_dir, self.theme_name, self.uiapp,
                         self.families, self._categories(), self.settings)
        if plan is None:
            return
        targets, param_name, guid, shared_name = plan
        for fam in targets:
            key = fam['key']
            if key not in self.pending:
                self.pending[key] = {'family_name': fam['name'], 'changes': {}}
            self.pending[key]['changes'][param_name] = {
                'param_name': param_name, 'shared_guid': guid, 'shared_name': shared_name,
            }
        self.rebuild_family_list(self.family_search.Text)
        self.rebuild_param_table(self.param_search.Text)
        self._refresh_footer()
        self.set_status(u'Queued "{0}" -> {1} on {2} famil(y/ies). Nothing is written until Apply.'.format(
            param_name, shared_name, len(targets)))

    # ---------- settings ----------

    def _on_settings(self, sender, e):
        if self.busy:
            return
        changed = show_settings(self.window, self.this_dir, self.theme_name, self.settings)
        if not changed:
            return
        fpc_core.save_settings(self.settings)
        if self.settings.get('theme', 'dark') != self.theme_name:
            self.theme_name = self.settings.get('theme', 'dark')
            theme_mod.apply(self.window, self.theme_name)
            self._sync_theme_chip()

    # ---------- theme ----------

    def _sync_theme_chip(self):
        self.theme_btn.Content = u'Light' if self.theme_name == 'dark' else u'Dark'

    def _on_theme_toggle(self, sender, e):
        self.theme_name = theme_mod.other(self.theme_name)
        theme_mod.apply(self.window, self.theme_name)
        self._sync_theme_chip()
        self.settings['theme'] = self.theme_name
        fpc_core.save_settings(self.settings)

    # ---------- refresh ----------

    def _on_refresh(self, sender, e):
        if self.busy:
            return
        self.set_status(u'Reading families...')
        self.families = fpc_model.scan_families(self.doc)
        if self._find_family(self.selected_key) is None:
            self.selected_key = None
            self.selected_header.Text = u'Select a family on the left'
        self.rebuild_family_list(self.family_search.Text)
        self.rebuild_param_table(self.param_search.Text)
        self._refresh_footer()

    # ---------- the run: one family per ExternalEvent ----------

    def _preview_lines(self):
        lines = []
        for key in self.pending:
            job = self.pending[key]
            for pname in sorted(job['changes'].keys()):
                lines.append(u'{0}   .   {1}   ->   {2}'.format(
                    job['family_name'], pname, job['changes'][pname]['shared_name']))
        return sorted(lines)

    def _set_busy_ui(self, busy):
        """While a run is on, the body is made hit-test-invisible so a
        click cannot land in a list that is about to be rebuilt, and the
        footer swaps Apply for Cancel."""
        self.busy = busy
        self.body_grid.IsHitTestVisible = not busy
        self.refresh_btn.IsEnabled = not busy
        self.expand_btn.IsEnabled = not busy
        self.bulk_btn.IsEnabled = not busy
        self.settings_btn.IsEnabled = not busy
        self.theme_btn.IsEnabled = not busy
        self.cancel_btn.Visibility = Visibility.Visible if busy else Visibility.Collapsed
        self.cancel_btn.IsEnabled = busy
        self.progress_strip.Visibility = Visibility.Visible if busy else Visibility.Collapsed
        self.progress_text.Visibility = Visibility.Visible if busy else Visibility.Collapsed
        self._refresh_footer()

    def _update_progress(self, current_name):
        done = self.run_done
        total = self.run_total if self.run_total else 1
        self.progress_done.Width = GridLength(float(done), GridUnitType.Star)
        self.progress_rest.Width = GridLength(float(max(total - done, 0)), GridUnitType.Star)
        percent = int(round(100.0 * done / total))
        self.progress_text.Text = u'{0}%'.format(percent)
        ok_count = 0
        fail_count = 0
        for r in self.run_results:
            if r.get('info'):
                continue
            if r.get('ok'):
                ok_count += 1
            else:
                fail_count += 1
        if done < self.run_total and not self.cancel_requested:
            nxt = self.handler.queue[0]['family_name'] if self.handler.queue else current_name
            self.set_status(u'Family {0} of {1}  .  {2}  .  {3} rebound, {4} failed  .  next: {5}'.format(
                done, self.run_total, current_name, ok_count, fail_count, nxt))
        else:
            self.set_status(u'Family {0} of {1}  .  {2}  .  {3} rebound, {4} failed'.format(
                done, self.run_total, current_name, ok_count, fail_count))

    def _on_apply(self, sender, e):
        if self.busy:
            return
        total = self._pending_total()
        if total == 0:
            return
        if self.settings.get('confirm_before_apply', 'on') == 'on':
            ok = show_confirm(
                self.window, self.this_dir, self.theme_name,
                u'Apply {0} rebind(s) across {1} famil(y/ies)'.format(total, len(self.pending)),
                self._preview_lines(),
                u'Apply', u'Cancel')
            if not ok:
                return

        queue = []
        for key in self.pending:
            fam = self._find_family(key)
            if fam is None or fam.get('blocked'):
                continue
            job = self.pending[key]
            queue.append({
                'family_id': fam['id'],
                'family_key': key,
                'family_name': job['family_name'],
                'sample_instance_id': fam.get('sample_instance_id'),
                'changes': list(job['changes'].values()),
            })
        if not queue:
            self.set_status(u'Nothing to apply.')
            return

        self.cancel_requested = False
        self.close_after_run = False
        self.run_total = len(queue)
        self.run_done = 0
        self.run_results = []
        self.run_keys = [j['family_key'] for j in queue]
        self._set_busy_ui(True)
        self.progress_done.Width = GridLength(0.0, GridUnitType.Star)
        self.progress_rest.Width = GridLength(1.0, GridUnitType.Star)
        self.progress_text.Text = u'0%'
        self.set_status(u'Family 1 of {0}  .  {1}'.format(len(queue), queue[0]['family_name']))

        self.handler.queue = queue
        try:
            self.handler.doc_title = self.doc.Title
        except Exception:
            self.handler.doc_title = None
        self.handler.on_step = self._on_family_step
        if self.settings.get('write_log', 'on') == 'on':
            lines = [u'=== run started: {0} rebind(s) across {1} famil(y/ies) in "{2}"'.format(
                total, len(queue), self.handler.doc_title or u'?')]
            lines.extend(self._preview_lines())
            fpc_core.append_log(lines)
        self.ext_event.Raise()

    def _on_family_step(self, job, results):
        """Called by the handler at the end of each Execute, on Revit's
        thread - which is also the window's thread. UI state is updated
        here; the next Raise and the finish are deferred to the
        dispatcher so they happen after this Execute has returned and
        the window has had a chance to paint."""
        self.run_done += 1
        self.run_results.extend(results)
        try:
            self._update_progress(job.get('family_name', u''))
        except Exception:
            pass
        if self.cancel_requested or not self.handler.queue:
            self._defer(self._finish_run)
        else:
            self._defer(self._raise_next)

    def _defer(self, fn):
        from System.Windows.Threading import DispatcherPriority
        try:
            self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(fn))
        except Exception:
            fn()

    def _raise_next(self):
        if not self.busy or self.cancel_requested:
            self._finish_run()
            return
        try:
            self.ext_event.Raise()
        except Exception as ex:
            self.run_results.append({'family': u'', 'param': u'', 'ok': False,
                                     'message': u'Could not raise the next step: {0}'.format(ex)})
            self._finish_run()

    def _on_cancel(self, sender, e):
        if not self.busy:
            return
        self.cancel_requested = True
        self.cancel_btn.IsEnabled = False
        self.set_status(u'Cancelling after the current family...')

    def _finish_run(self):
        if not self.busy:
            return
        skipped = len(self.handler.queue)
        self.handler.queue = []
        self.handler.on_step = None

        ok_count = 0
        fail_count = 0
        for r in self.run_results:
            if r.get('info'):
                continue
            if r.get('ok'):
                ok_count += 1
            else:
                fail_count += 1

        # only the families that were touched are re-read
        touched = self.run_keys[:self.run_done]
        try:
            self.families = fpc_model.rescan(self.doc, self.families, touched)
        except Exception:
            self.families = fpc_model.scan_families(self.doc)

        for key in touched:
            self.pending.pop(key, None)

        self._set_busy_ui(False)
        self.rebuild_family_list(self.family_search.Text)
        self.rebuild_param_table(self.param_search.Text)
        self._refresh_footer()

        summary = u'{0} rebound, {1} failed'.format(ok_count, fail_count)
        if skipped:
            summary = summary + u', {0} famil(y/ies) not started (cancelled)'.format(skipped)
        self.set_status(summary + u'.')

        if self.settings.get('write_log', 'on') == 'on':
            lines = [fpc_core.format_result_line(r) for r in self.run_results]
            lines.append(u'=== run finished: ' + summary)
            fpc_core.append_log(lines)

        if fail_count or skipped:
            show_report(self.window, self.this_dir, self.theme_name, self.run_results)

        if self.close_after_run:
            self.window.Close()

    def on_close(self):
        if self.busy:
            # never tear the window out from under an open family editor
            self.cancel_requested = True
            self.close_after_run = True
            self.cancel_btn.IsEnabled = False
            self.set_status(u'Closing after the current family...')
            return
        try:
            self.settings['theme'] = self.theme_name
            fpc_core.save_settings(self.settings)
        except Exception:
            pass
        self.window.Close()

# ==================== shared parameter picker ====================

def pick_shared_parameter(owner, this_dir, theme_name, uiapp):
    window = load_xaml(os.path.join(this_dir, 'FpcSharedParamPicker.xaml'))
    dress(window, this_dir, theme_name)
    window.Owner = owner
    wire_drag(window)

    find = window.FindName
    close_btn = find('CloseButton')
    cancel_btn = find('CancelButton')
    ok_btn = find('OkButton')
    browse_btn = find('BrowseFileButton')
    search_box = find('SearchBox')
    list_panel = find('DefinitionListPanel')
    info_text = find('InfoText')

    app_obj = uiapp.Application
    result = {'value': None}
    selected = {'def': None}
    all_defs = []

    def load_defs():
        del all_defs[:]
        groups, err = fpc_core.read_shared_parameter_file(app_obj)
        for group_name, defs in groups:
            for d in defs:
                all_defs.append((group_name, d))
        if err:
            info_text.Text = err
        else:
            info_text.Text = u'{0} definition(s) across {1} group(s).'.format(
                len(all_defs), len(groups))

    def rebuild(filter_text=u''):
        list_panel.Children.Clear()
        ft = filter_text.strip().lower()
        for group_name, d in all_defs:
            dname = fpc_core.shared_param_display_name(d)
            if ft and ft not in dname.lower() and ft not in group_name.lower():
                continue
            row = Border()
            row.Padding = Thickness(8, 6, 8, 6)
            row.Margin = Thickness(0, 0, 0, 2)
            row.CornerRadius = CornerRadius(4)
            row.Cursor = Cursors.Hand
            row.SetResourceReference(Border.BackgroundProperty, 'FieldBg')
            stack = StackPanel()
            stack.Children.Add(_text(dname, 12.5, 'TextBrush'))
            stack.Children.Add(_text(group_name, 10.5, 'MutedTextBrush'))
            row.Child = stack

            def make_click(d_ref, row_ref):
                def _c(sender, e):
                    selected['def'] = d_ref
                    for child in list_panel.Children:
                        child.SetResourceReference(Border.BackgroundProperty, 'FieldBg')
                    row_ref.SetResourceReference(Border.BackgroundProperty, 'SelectionBrush')
                    ok_btn.IsEnabled = True
                return _c
            row.MouseLeftButtonUp += make_click(d, row)
            list_panel.Children.Add(row)

        if list_panel.Children.Count == 0:
            empty = _text(u'Nothing matches that search.', 12, 'MutedTextBrush')
            empty.Margin = Thickness(8, 8, 8, 8)
            list_panel.Children.Add(empty)

    load_defs()
    rebuild()

    def _search(sender, e):
        rebuild(search_box.Text)

    def _cancel(sender, e):
        result['value'] = None
        window.Close()

    def _ok(sender, e):
        result['value'] = selected['def']
        window.Close()

    def _browse(sender, e):
        try:
            import System.Windows.Forms as WinForms
            dlg = WinForms.OpenFileDialog()
            dlg.Filter = u'Shared parameter files (*.txt)|*.txt|All files (*.*)|*.*'
            if dlg.ShowDialog() == WinForms.DialogResult.OK:
                app_obj.SharedParametersFilename = dlg.FileName
                selected['def'] = None
                ok_btn.IsEnabled = False
                load_defs()
                rebuild(search_box.Text)
        except Exception as ex:
            info_text.Text = u'Could not set the shared parameter file: {0}'.format(ex)

    search_box.TextChanged += _search
    close_btn.Click += _cancel
    cancel_btn.Click += _cancel
    ok_btn.Click += _ok
    browse_btn.Click += _browse

    window.ShowDialog()
    return result['value']


# ==================== confirm / report ====================

def _message_window(owner, this_dir, theme_name, title):
    window = load_xaml(os.path.join(this_dir, 'FpcMessage.xaml'))
    dress(window, this_dir, theme_name)
    window.Owner = owner
    wire_drag(window)
    window.FindName('TitleText').Text = title
    return window


def show_confirm(owner, this_dir, theme_name, title, lines, primary_text, secondary_text):
    window = _message_window(owner, this_dir, theme_name, title)
    body = window.FindName('BodyPanel')

    lead = _text(u'This will be written to the model when you press Apply:', 12, 'MutedTextBrush')
    lead.Margin = Thickness(0, 0, 0, 8)
    lead.TextWrapping = TextWrapping.Wrap
    body.Children.Add(lead)

    for line in lines:
        tb = _text(line, 11.5, 'TextBrush')
        tb.TextWrapping = TextWrapping.Wrap
        tb.Margin = Thickness(0, 0, 0, 4)
        body.Children.Add(tb)

    primary = window.FindName('PrimaryButton')
    secondary = window.FindName('SecondaryButton')
    primary.Content = primary_text
    secondary.Content = secondary_text

    result = {'value': False}

    def _yes(sender, e):
        result['value'] = True
        window.Close()

    def _no(sender, e):
        result['value'] = False
        window.Close()

    primary.Click += _yes
    secondary.Click += _no
    window.ShowDialog()
    return result['value']


def show_report(owner, this_dir, theme_name, results):
    window = _message_window(owner, this_dir, theme_name, u'Results')
    body = window.FindName('BodyPanel')
    for r in results:
        ok = r.get('ok')
        if r.get('param'):
            line = u'{0}  .  {1}  -  {2}'.format(r.get('family', u''), r.get('param', u''), r.get('message', u''))
        else:
            line = u'{0}  -  {1}'.format(r.get('family', u''), r.get('message', u''))
        if r.get('info'):
            brush = 'MutedTextBrush'
        else:
            brush = 'GreenBrush' if ok else 'RedBrush'
        tb = _text(line, 11.5, brush)
        tb.TextWrapping = TextWrapping.Wrap
        tb.Margin = Thickness(0, 0, 0, 4)
        body.Children.Add(tb)

    secondary = window.FindName('SecondaryButton')
    secondary.Content = u'Copy report'

    def _copy(sender, e):
        try:
            from System.Windows import Clipboard
            Clipboard.SetText(u'\r\n'.join(fpc_core.format_result_line(r) for r in results))
            secondary.Content = u'Copied'
        except Exception:
            secondary.Content = u'Could not copy'
    secondary.Click += _copy

    primary = window.FindName('PrimaryButton')
    primary.Content = u'Close'
    primary.Click += lambda s, e: window.Close()
    window.ShowDialog()


# ==================== bulk rebind dialog ====================

def pick_bulk(owner, this_dir, theme_name, uiapp, families, categories, settings):
    """Returns (target_families, param_name, shared_guid, shared_name) or
    None. The planning itself is fpc_core.plan_bulk, which is pure and
    tested on the bench; this function only collects the three choices."""
    window = load_xaml(os.path.join(this_dir, 'FpcBulk.xaml'))
    dress(window, this_dir, theme_name)
    window.Owner = owner
    wire_drag(window)

    find = window.FindName
    scope_panel = find('ScopePanel')
    param_panel = find('ParamPanel')
    param_search = find('ParamSearchBox')
    shared_text = find('SharedParamText')
    choose_btn = find('ChooseSharedButton')
    skip_check = find('SkipAlreadyBoundCheck')
    preview = find('PreviewText')
    queue_btn = find('QueueButton')
    cancel_btn = find('CancelButton')
    close_btn = find('CloseButton')

    skip_check.IsChecked = settings.get('bulk_skip_already_bound', 'on') == 'on'

    state = {'scope': fpc_core.BULK_ALL, 'param': None, 'def': None,
             'guid': None, 'shared_name': None, 'result': None}
    scope_rows = {}
    param_rows = {}

    def _row(padding=(8, 6, 8, 6)):
        b = Border()
        b.Padding = Thickness(padding[0], padding[1], padding[2], padding[3])
        b.Margin = Thickness(0, 0, 0, 2)
        b.CornerRadius = CornerRadius(4)
        b.Cursor = Cursors.Hand
        b.SetResourceReference(Border.BackgroundProperty, 'FieldBg')
        return b

    def _paint_selection(rows, chosen):
        for name in rows:
            key = 'SelectionBrush' if name == chosen else 'FieldBg'
            rows[name].SetResourceReference(Border.BackgroundProperty, key)

    def _refresh_preview():
        if state['param'] is None or state['guid'] is None:
            queue_btn.IsEnabled = False
            missing = []
            if state['param'] is None:
                missing.append(u'a parameter')
            if state['guid'] is None:
                missing.append(u'a shared parameter')
            preview.Text = u'Pick {0}.'.format(u' and '.join(missing))
            preview.SetResourceReference(TextBlock.ForegroundProperty, 'MutedTextBrush')
            return
        targets, skipped = fpc_core.plan_bulk(
            families, state['scope'], state['param'], state['guid'],
            skip_already_bound=bool(skip_check.IsChecked))
        queue_btn.IsEnabled = len(targets) > 0
        scope_label = u'all families' if state['scope'] == fpc_core.BULK_ALL else state['scope']
        text = u'Queues "{0}" -> {1} on {2} famil(y/ies) in {3}'.format(
            state['param'], state['shared_name'], len(targets), scope_label)
        if skipped:
            text = text + u'  .  {0} skipped'.format(len(skipped))
        preview.Text = text
        preview.SetResourceReference(TextBlock.ForegroundProperty,
                                     'OrangeBrush' if targets else 'RedBrush')

    def _build_params(filter_text=u''):
        param_panel.Children.Clear()
        param_rows.clear()
        census = fpc_core.parameter_census(families, state['scope'])
        ft = filter_text.strip().lower()
        names = sorted(census.keys(), key=lambda n: n.lower())
        shown = 0
        for name in names:
            if ft and ft not in name.lower():
                continue
            entry = census[name]
            row = _row((8, 5, 8, 5))
            grid = Grid()
            for star in (2.4, 1.0, 1.0, 1.0):
                cd = ColumnDefinition()
                cd.Width = GridLength(star, GridUnitType.Star)
                grid.ColumnDefinitions.Add(cd)
            cells = [
                _text(name, 12.5, 'TextBrush'),
                _text(u'{0}'.format(entry['families']), 11.5, 'MutedTextBrush'),
                _text(u'{0}'.format(entry['shared']), 11.5, 'GreenBrush' if entry['shared'] else 'MutedTextBrush'),
                _text(u'{0}'.format(entry['unshared']), 11.5, 'OrangeBrush' if entry['unshared'] else 'MutedTextBrush'),
            ]
            cells[0].TextTrimming = TextTrimming.CharacterEllipsis
            for i, cell in enumerate(cells):
                cell.VerticalAlignment = VerticalAlignment.Center
                Grid.SetColumn(cell, i)
                grid.Children.Add(cell)
            row.Child = grid

            def make_click(pname):
                def _c(sender, e):
                    state['param'] = pname
                    _paint_selection(param_rows, pname)
                    _refresh_preview()
                return _c
            row.MouseLeftButtonUp += make_click(name)
            param_rows[name] = row
            param_panel.Children.Add(row)
            shown += 1
        if state['param'] in param_rows:
            _paint_selection(param_rows, state['param'])
        elif state['param'] is not None:
            # the chosen parameter is not in this scope
            state['param'] = None
        if shown == 0:
            empty = _text(u'No parameter in this scope matches.', 12, 'MutedTextBrush')
            empty.Margin = Thickness(8, 8, 8, 8)
            param_panel.Children.Add(empty)

    def _build_scope():
        scope_panel.Children.Clear()
        scope_rows.clear()
        counts = {}
        for fam in families:
            counts[fam['category']] = counts.get(fam['category'], 0) + 1
        entries = [(fpc_core.BULK_ALL, len(families))] + [(c, counts[c]) for c in categories]
        for name, count in entries:
            row = _row()
            grid = Grid()
            name_col = ColumnDefinition()
            name_col.Width = GridLength(1.0, GridUnitType.Star)
            count_col = ColumnDefinition()
            count_col.Width = GridLength.Auto
            grid.ColumnDefinitions.Add(name_col)
            grid.ColumnDefinitions.Add(count_col)
            is_all = name == fpc_core.BULK_ALL
            label = _text(u'All families' if is_all else name, 12.5,
                          'OrangeBrush' if is_all else 'BlueBrush', bold=True)
            label.TextTrimming = TextTrimming.CharacterEllipsis
            Grid.SetColumn(label, 0)
            grid.Children.Add(label)
            tail = _text(u'{0}'.format(count), 10.5, 'MutedTextBrush')
            tail.VerticalAlignment = VerticalAlignment.Center
            Grid.SetColumn(tail, 1)
            grid.Children.Add(tail)
            row.Child = grid

            def make_click(scope_name):
                def _c(sender, e):
                    state['scope'] = scope_name
                    _paint_selection(scope_rows, scope_name)
                    _build_params(param_search.Text)
                    _refresh_preview()
                return _c
            row.MouseLeftButtonUp += make_click(name)
            scope_rows[name] = row
            scope_panel.Children.Add(row)
        _paint_selection(scope_rows, state['scope'])

    def _choose(sender, e):
        chosen = pick_shared_parameter(window, this_dir, theme_name, uiapp)
        if chosen is None:
            return
        state['def'] = chosen
        state['guid'] = fpc_core.shared_param_guid(chosen)
        state['shared_name'] = fpc_core.shared_param_display_name(chosen)
        shared_text.Text = state['shared_name']
        shared_text.SetResourceReference(TextBlock.ForegroundProperty, 'GreenBrush')
        _refresh_preview()

    def _queue(sender, e):
        targets, _skipped = fpc_core.plan_bulk(
            families, state['scope'], state['param'], state['guid'],
            skip_already_bound=bool(skip_check.IsChecked))
        settings['bulk_skip_already_bound'] = 'on' if skip_check.IsChecked else 'off'
        fpc_core.save_settings(settings)
        state['result'] = (targets, state['param'], state['guid'], state['shared_name'])
        window.Close()

    def _cancel(sender, e):
        state['result'] = None
        window.Close()

    choose_btn.Click += _choose
    queue_btn.Click += _queue
    cancel_btn.Click += _cancel
    close_btn.Click += _cancel
    skip_check.Click += lambda s, e: _refresh_preview()
    param_search.TextChanged += lambda s, e: _build_params(param_search.Text)

    _build_scope()
    _build_params()
    _refresh_preview()
    window.ShowDialog()
    return state['result']


# ==================== settings dialog ====================

def show_settings(owner, this_dir, theme_name, settings):
    """Edits `settings` in place and returns True if Apply was pressed."""
    window = load_xaml(os.path.join(this_dir, 'FpcSettings.xaml'))
    dress(window, this_dir, theme_name)
    window.Owner = owner
    wire_drag(window)

    find = window.FindName
    light = find('LightThemeCheck')
    confirm = find('ConfirmCheck')
    skip_bound = find('SkipBoundCheck')
    log = find('LogCheck')
    log_path = find('LogPathText')
    open_log = find('OpenLogButton')
    apply_btn = find('ApplyButton')
    cancel_btn = find('CancelButton')
    close_btn = find('CloseButton')

    light.IsChecked = settings.get('theme', 'dark') == 'light'
    confirm.IsChecked = settings.get('confirm_before_apply', 'on') == 'on'
    skip_bound.IsChecked = settings.get('bulk_skip_already_bound', 'on') == 'on'
    log.IsChecked = settings.get('write_log', 'on') == 'on'
    log_path.Text = fpc_core.LOG_PATH

    result = {'applied': False}

    def _apply(sender, e):
        settings['theme'] = 'light' if light.IsChecked else 'dark'
        settings['confirm_before_apply'] = 'on' if confirm.IsChecked else 'off'
        settings['bulk_skip_already_bound'] = 'on' if skip_bound.IsChecked else 'off'
        settings['write_log'] = 'on' if log.IsChecked else 'off'
        result['applied'] = True
        window.Close()

    def _cancel(sender, e):
        window.Close()

    def _open_log(sender, e):
        try:
            import System.Diagnostics as Diagnostics
            folder = os.path.dirname(fpc_core.LOG_PATH)
            if not os.path.isdir(folder):
                os.makedirs(folder)
            Diagnostics.Process.Start(folder)
        except Exception:
            pass

    apply_btn.Click += _apply
    cancel_btn.Click += _cancel
    close_btn.Click += _cancel
    open_log.Click += _open_log
    window.ShowDialog()
    return result['applied']


# ==================== entry ====================

def build_window(this_dir, families, doc, handler, ext_event, uiapp):
    settings = fpc_core.load_settings()
    theme_name = settings.get('theme', 'dark')

    window = load_xaml(os.path.join(this_dir, 'FamilyParameterChanger.xaml'))
    dress(window, this_dir, theme_name)
    own_to_revit(window, uiapp)

    controller = MainController(window, this_dir, families, doc, handler,
                                ext_event, settings, theme_name, uiapp)
    controller.wire()
    return window
