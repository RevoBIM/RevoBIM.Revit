# -*- coding: utf-8 -*-
u"""Project Browser Pro - the Browser Organisation dialog for one tab.

Three ways to group: Revit's own browser organisation (whatever is current
in the project - the default for views and sheets), parameters chosen here
(up to six folder levels, top level first), or no grouping. Items inside
each folder sort by a chosen parameter, ascending or descending.

Switching from Revit's organisation to parameters fills the levels and the
sort with what Revit's organisation groups and sorts by, ready to change.
Below the lists, ticks choose which folder levels are coloured main
headings, however the tab is grouped.

Modal: it is a short decision, and nothing in Revit needs to be touched
while it is open. Nothing is saved until Apply.
"""
import pbp_clr  # noqa: F401
from System.Windows.Input import Key
from System.Windows.Controls import Button, StackPanel, TextBlock, Orientation, ContextMenu, MenuItem
from System.Windows import Thickness, VerticalAlignment, FrameworkElement

import pbp_ui
import pbp_theme
import pbp_palette
import pbp_log
import pbp_settings
from pbp_ui import find, safe
from pbp_compat import words, matches, to_text
from pbp_settings import normalise_org, DEFAULT_ORGS, MAX_LEVELS, describe_org, hex_colour
from pbp_tree import TAB_LABELS
from pbp_version import __version__


class OrganisationWindow(object):

    def __init__(self, tab, org, catalogue, revit_name, theme_name, revit_levels=None,
                 revit_sort=u'', groups=None, level_offset=0, org_key=None, title=None,
                 colours_only=False):
        self.tab = tab
        # Families: the grouping is fixed, only the heading colours change
        self.colours_only = bool(colours_only)
        # the organisation edited: the tab's own, or its favourites' (fav.views)
        self.org_key = org_key or tab
        self.org = normalise_org(org, self.org_key)
        self.catalogue = list(catalogue or [])
        self.revit_name = to_text(revit_name)
        self.revit_levels = [to_text(name) for name in (revit_levels or []) if name]
        self.revit_sort = to_text(revit_sort)
        # [(level, name, colour now, on a coloured level)] - every folder
        # value of the tab, every grouping level
        self.groups = list(groups or [])
        self.level_offset = int(level_offset or 0)
        self.group_level = None     # None: every level listed
        self.settings_folder = pbp_log.appdata_folder()
        self.settings = pbp_settings.load(self.settings_folder)
        self.custom = pbp_settings.custom_colours(self.settings)
        self.theme_name = theme_name
        self.result = None
        self.loading = True
        self.window = pbp_ui.load_xaml(u'Organisation.xaml')
        pbp_theme.apply(self.window, theme_name)
        w = self.window
        find(w, u'TitleText').Text = u'Browser Organisation \u00b7 ' + (title or TAB_LABELS.get(tab, tab))
        find(w, u'VersionText').Text = u'v' + __version__
        logo = pbp_ui.logo_image()
        if logo is not None:
            find(w, u'LogoImage').Source = logo
        self.source_revit = find(w, u'SourceRevit')
        self.source_custom = find(w, u'SourceCustom')
        self.source_none = find(w, u'SourceNone')
        self.custom_panel = find(w, u'CustomPanel')
        self.param_search = find(w, u'ParamSearch')
        self.param_list = find(w, u'ParamList')
        self.level_list = find(w, u'LevelList')
        self.sort_text = find(w, u'SortText')
        self.sort_box = find(w, u'SortBox')
        self.dir_button = find(w, u'DirButton')
        self.preview = find(w, u'PreviewText')
        self.add_level = find(w, u'AddLevel')
        self.remove_level = find(w, u'RemoveLevel')
        self.move_up = find(w, u'MoveUp')
        self.move_down = find(w, u'MoveDown')
        self.colour_ticks = [find(w, u'ColourLevel{0}'.format(level))
                             for level in range(1, MAX_LEVELS + 1)]
        self.group_list = find(w, u'GroupList')
        self.swatch_strip = find(w, u'SwatchStrip')
        self.level_filter = find(w, u'LevelFilter')
        self.group_names = []
        self._build_swatches()
        self._build_level_filter()
        find(w, u'AutoColour').Click += safe(self._auto_colour, u'org auto colour')
        find(w, u'AddColour').Click += safe(self._add_colour, u'org add colour')
        self.level_list.SelectionChanged += safe(self._level_picked, u'org level picked')

        has_revit = tab in (u'views', u'sheets') or bool(self.revit_name)
        find(w, u'RevitSourceText').Text = (
            u"Revit's browser organisation ({0})".format(self.revit_name or u'current')
            if has_revit else u"Revit's browser organisation (Revit has none for this list)")
        self.source_revit.IsEnabled = has_revit
        if not has_revit and self.org[u'source'] == u'revit':
            self.org[u'source'] = u'none'

        self.source_revit.Checked += safe(self._source, u'org source')
        self.source_custom.Checked += safe(self._source, u'org source')
        self.source_none.Checked += safe(self._source, u'org source')
        self.param_search.TextChanged += safe(self._fill_params, u'org search')
        self.param_list.MouseDoubleClick += safe(self._add, u'org add dbl')
        self.add_level.Click += safe(self._add, u'org add')
        self.remove_level.Click += safe(self._remove, u'org remove')
        self.move_up.Click += safe(self._up, u'org up')
        self.move_down.Click += safe(self._down, u'org down')
        find(w, u'SortBy').Click += safe(self._sort_by, u'org sort')
        find(w, u'ClearSort').Click += safe(self._clear_sort, u'org clear sort')
        self.dir_button.Click += safe(self._toggle_dir, u'org dir')
        for tick in self.colour_ticks:
            tick.Checked += safe(self._colours_changed, u'org colours')
            tick.Unchecked += safe(self._colours_changed, u'org colours')
        find(w, u'ResetButton').Click += safe(self._reset, u'org reset')
        find(w, u'ApplyButton').Click += safe(self._apply, u'org apply')
        find(w, u'CancelButton').Click += safe(self._cancel, u'org cancel')
        find(w, u'CloseButton').Click += safe(self._cancel, u'org close')
        find(w, u'Header').MouseLeftButtonDown += safe(self._drag, u'org drag')
        w.PreviewKeyDown += safe(self._key, u'org key')
        if self.colours_only:
            # the grouping stays; the coloured levels and colours are theirs
            for element in (find(w, u'SourcePanel'), self.custom_panel):
                element.IsEnabled = False
        self._load()

    # ---- state to screen ----
    def _load(self):
        self.loading = True
        source = self.org[u'source']
        self.source_revit.IsChecked = source == u'revit'
        self.source_custom.IsChecked = source == u'custom'
        self.source_none.IsChecked = source == u'none'
        for level, tick in enumerate(self.colour_ticks, 1):
            tick.IsChecked = level in self.org[u'colours']
        self.loading = False
        self._fill_groups()
        self._fill_params(None, None)
        self._fill_levels()
        self._refresh()

    def _fill_params(self, sender, args):
        wanted = words(self.param_search.Text)
        self.param_list.Items.Clear()
        for name in self.catalogue:
            if matches(name, wanted):
                self.param_list.Items.Add(name)

    def _fill_levels(self, select=None):
        self.level_list.Items.Clear()
        for index, name in enumerate(self.org[u'levels']):
            self.level_list.Items.Add(u'{0}.  {1}'.format(index + 1, name))
        if select is not None and 0 <= select < self.level_list.Items.Count:
            self.level_list.SelectedIndex = select

    def _refresh(self):
        source = self.org[u'source']
        if self.colours_only:
            self.preview.Text = (u'Always grouped Main group (1) \u203a Category (2) \u203a Family (3) '
                                 u'\u203a Type. Tick the levels drawn as coloured headings; pick a '
                                 u'group on the right and give it a colour (or right click a heading '
                                 u'in the browser).')
            return
        self.custom_panel.IsEnabled = source != u'revit'
        # A Border has no disabled look of its own, so the sort box would
        # stay bright inside a greyed-out panel; fade it with the lists.
        self.sort_box.Opacity = 1.0 if source != u'revit' else 0.45
        custom = source == u'custom'
        for element in (self.add_level, self.remove_level, self.move_up,
                        self.move_down, self.level_list):
            element.IsEnabled = custom
        self.sort_text.Text = self.org[u'sort'] or u'Name'
        self.dir_button.Content = u'Descending' if self.org[u'desc'] else u'Ascending'
        line = describe_org(self.org, self.revit_name)
        if source == u'revit':
            line += u'. Folders and sort order come from Revit; change them in Revit\'s own Browser Organization.'
        elif custom and len(self.org[u'levels']) >= MAX_LEVELS:
            line += u'. Six folder levels is the most.'
        self.preview.Text = line

    # ---- group colours ----
    def _build_swatches(self):
        u"""The colours to pick from: each trade's gradient, the group
        colours, nine greys, and the user's own (right click one to drop it)."""
        self.swatch_strip.Children.Clear()
        for colour in pbp_palette.choice_colours(self.custom):
            swatch = Button()
            pbp_ui.set_style(swatch, u'SwatchButton')
            swatch.Background = pbp_theme.brush(colour)
            swatch.Margin = Thickness(0, 0, 4, 4)
            mine = colour in self.custom
            swatch.ToolTip = colour + (u' - yours: right click to remove' if mine else u'')
            swatch.Click += safe(self._swatch(colour), u'org swatch')
            if mine:
                swatch.MouseRightButtonUp += safe(self._dropper(colour), u'org drop colour')
            self.swatch_strip.Children.Add(swatch)

    def _swatch(self, colour):
        return lambda sender, args: self._set_group_colour(colour)

    def _dropper(self, colour):
        def drop(sender, args):
            args.Handled = True
            self._remove_custom(colour)
        return drop

    def _save_custom(self):
        pbp_settings.set_custom_colours(self.settings, self.custom)
        pbp_settings.save(self.settings_folder, self.settings)
        self._build_swatches()

    def add_custom(self, colour):
        u"""Keep a colour with the choices, for every tab and every project."""
        colour = hex_colour(colour)
        if colour and colour not in self.custom:
            self.custom.append(colour)
            self._save_custom()
        return colour

    def _remove_custom(self, colour):
        if colour in self.custom:
            self.custom.remove(colour)
            self._save_custom()

    def _add_colour(self, sender, args):
        u"""Windows' own colour picker; the colour joins the choices and goes
        on the values picked, if any."""
        colour = pick_colour(self._picked_colour_hint())
        if not colour:
            return
        self.add_custom(colour)
        if self._picked_groups():
            self._set_group_colour(colour)

    def _picked_colour_hint(self):
        names = self._picked_groups()
        own = self.org[u'group_colours']
        for level, name in names:
            colour = own.get(pbp_settings.group_key(level, name))
            if colour:
                return colour
        return u''

    # the level filter: All, then one chip per grouping level present
    def _build_level_filter(self):
        self.level_filter.Children.Clear()
        levels = sorted(set(level for level, name, colour, coloured in self.groups))
        for level in [None] + levels:
            chip = Button()
            pbp_ui.set_style(chip, u'ChipButton')
            chip.Content = u'All' if level is None else u'Level {0}'.format(level)
            chip.Margin = Thickness(0, 0, 4, 4)
            chip.Padding = Thickness(7, 1, 7, 1)
            if level == self.group_level:
                chip.SetResourceReference(Button.BackgroundProperty, u'SelectBrush')
            chip.Click += safe(self._level_chooser(level), u'org level filter')
            self.level_filter.Children.Add(chip)

    def _level_chooser(self, level):
        return lambda sender, args: self.show_level(level)

    def show_level(self, level):
        u"""List one grouping level's values (None: every level)."""
        self.group_level = level
        self._build_level_filter()
        self._fill_groups()

    def _level_picked(self, sender, args):
        index = self.level_list.SelectedIndex
        if self.loading or index < 0:
            return
        self.show_level(index + 1 + self.level_offset)

    def _fill_groups(self, keep=None):
        u"""One row per folder value: its colour now, its name, its level -
        one level's values, or every level's."""
        self.group_list.Items.Clear()
        self.group_names = []
        own = self.org[u'group_colours']
        for level, name, automatic, coloured in self.groups:
            if self.group_level is not None and level != self.group_level:
                continue
            mine = own.get(pbp_settings.group_key(level, name)) or own.get(name)
            colour = mine or automatic
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            chip = Button()
            pbp_ui.set_style(chip, u'SwatchButton')
            if hex_colour(colour):
                chip.Background = pbp_theme.brush(hex_colour(colour))
            else:
                chip.SetResourceReference(Button.BackgroundProperty, u'DisabledBrush')
            chip.IsHitTestVisible = False
            chip.Width = chip.Height = 14
            row.Children.Add(chip)
            label = TextBlock()
            label.Text = name
            label.VerticalAlignment = VerticalAlignment.Center
            label.SetResourceReference(TextBlock.ForegroundProperty, u'TextBrush')
            row.Children.Add(label)
            note = TextBlock()
            note.Text = u'  level {0}{1}'.format(
                level, u' \u00b7 own colour' if mine else (u'' if coloured else u' \u00b7 not coloured'))
            note.FontSize = 10.5
            note.VerticalAlignment = VerticalAlignment.Center
            note.SetResourceReference(TextBlock.ForegroundProperty, u'MutedBrush')
            row.Children.Add(note)
            self.group_list.Items.Add(row)
            self.group_names.append((level, name))
            if keep and (level, name) in keep:
                self.group_list.SelectedItems.Add(row)

    def _picked_groups(self):
        names = []
        for item in self.group_list.SelectedItems:
            index = self.group_list.Items.IndexOf(item)
            if 0 <= index < len(self.group_names):
                names.append(self.group_names[index])
        return names

    def _set_group_colour(self, colour, names=None):
        names = self._picked_groups() if names is None else names
        if not names:
            self.preview.Text = u'Pick one or more values in the list first.'
            return
        for level, name in names:
            key = pbp_settings.group_key(level, name)
            if colour:
                self.org[u'group_colours'][key] = colour
            else:
                self.org[u'group_colours'].pop(key, None)
                self.org[u'group_colours'].pop(name, None)
        self._fill_groups(set(names))
        self._refresh()

    def _auto_colour(self, sender, args):
        self._set_group_colour(u'')

    # ---- handlers ----
    def _source(self, sender, args):
        if self.loading:
            return
        was = self.org[u'source']
        if self.source_revit.IsChecked:
            self.org[u'source'] = u'revit'
        elif self.source_custom.IsChecked:
            self.org[u'source'] = u'custom'
        else:
            self.org[u'source'] = u'none'
        if was == u'revit' and self.org[u'source'] == u'custom':
            self._take_revit()
        self._refresh()

    def _take_revit(self):
        u"""Start the manual organisation from Revit's: its grouping
        parameters as the folder levels, its sort parameter as the sort."""
        if self.revit_levels:
            self.org[u'levels'] = list(self.revit_levels[:MAX_LEVELS])
            self._fill_levels(0)
        if self.revit_sort:
            self.org[u'sort'] = self.revit_sort

    def _colours_changed(self, sender, args):
        if self.loading:
            return
        self.org[u'colours'] = [level for level, tick in enumerate(self.colour_ticks, 1)
                                if tick.IsChecked]
        self._refresh()

    def _picked(self):
        item = self.param_list.SelectedItem
        return to_text(item) if item is not None else u''

    def _add(self, sender, args):
        name = self._picked()
        if not name:
            return
        if self.org[u'source'] != u'custom':
            if self.org[u'source'] == u'revit':
                self._take_revit()
            self.org[u'source'] = u'custom'
            self._load()
        if name in self.org[u'levels'] or len(self.org[u'levels']) >= MAX_LEVELS:
            self._refresh()
            return
        self.org[u'levels'].append(name)
        self._fill_levels(len(self.org[u'levels']) - 1)
        self._refresh()

    def _remove(self, sender, args):
        index = self.level_list.SelectedIndex
        if 0 <= index < len(self.org[u'levels']):
            del self.org[u'levels'][index]
            self._fill_levels(min(index, len(self.org[u'levels']) - 1))
            self._refresh()

    def _move(self, step):
        index = self.level_list.SelectedIndex
        target = index + step
        levels = self.org[u'levels']
        if 0 <= index < len(levels) and 0 <= target < len(levels):
            levels[index], levels[target] = levels[target], levels[index]
            self._fill_levels(target)
            self._refresh()

    def _up(self, sender, args):
        self._move(-1)

    def _down(self, sender, args):
        self._move(1)

    def _sort_by(self, sender, args):
        name = self._picked()
        if name:
            self.org[u'sort'] = name
            self._refresh()

    def _clear_sort(self, sender, args):
        self.org[u'sort'] = u''
        self._refresh()

    def _toggle_dir(self, sender, args):
        self.org[u'desc'] = not self.org[u'desc']
        self._refresh()

    def _reset(self, sender, args):
        self.org = normalise_org(DEFAULT_ORGS.get(self.org_key), self.org_key)
        self._load()

    def _apply(self, sender, args):
        self.result = normalise_org(self.org, self.org_key)
        self.window.Close()

    def _cancel(self, sender, args):
        self.result = None
        self.window.Close()

    def _drag(self, sender, args):
        try:
            self.window.DragMove()
        except Exception:
            pass

    def _key(self, sender, args):
        if args.Key == Key.Escape:
            args.Handled = True
            self._cancel(None, None)

    def run(self):
        pbp_ui.own(self.window)
        self.window.ShowDialog()
        return self.result


def pick_colour(start=u''):
    u"""Windows' colour picker. '#RRGGBB', or u'' when cancelled."""
    try:
        from System.Windows.Forms import ColorDialog, DialogResult
        dialog = ColorDialog()
        dialog.FullOpen = True
        dialog.AnyColor = True
        if hex_colour(start):
            # starts on the value's own colour; a Drawing colour as an int ARGB
            dialog.Color = dialog.Color.FromArgb(int(u'FF' + hex_colour(start)[1:], 16) - (1 << 32))
        if dialog.ShowDialog() != DialogResult.OK:
            return u''
        colour = dialog.Color
        return u'#{0:02X}{1:02X}{2:02X}'.format(int(colour.R), int(colour.G), int(colour.B))
    except Exception:
        pbp_log.exc(u'colour picker')
        return u''


def ask(tab, org, catalogue, revit_name, theme_name, revit_levels=None, revit_sort=u'',
        groups=None, level_offset=0, org_key=None, title=None, colours_only=False):
    u"""tab: the type whose parameters and Revit organisation are offered.
    org_key: what is being organised when it is not that tab itself - the
    Favourites tab's 'fav.views' - and title the dialog names it by.
    colours_only: the grouping is fixed (Families); only colours change."""
    return OrganisationWindow(tab, org, catalogue, revit_name, theme_name,
                              revit_levels, revit_sort, groups, level_offset,
                              org_key, title, colours_only).run()
