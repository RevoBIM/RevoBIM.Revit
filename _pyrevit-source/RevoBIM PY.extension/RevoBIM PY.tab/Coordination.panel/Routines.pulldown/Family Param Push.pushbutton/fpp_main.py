# -*- coding: utf-8 -*-
"""The Family Param Push window. Left: families. Right: what was pushed across
and its parameter mappings. Holds no rules: those are in fpp_core."""
import fpp_clr  # noqa: F401  (must stay first)
import os

from System import Action, TimeSpan
from System.Windows import Visibility
from System.Windows.Controls import (DataGridLength, DataGridLengthUnitType,
                                     DataGridTemplateColumn, DataGridTextColumn,
                                     TextBlock)
from System.Windows.Controls.Primitives import ButtonBase
from System.Windows.Data import Binding
from System.Windows.Input import Key, Keyboard
from System.Windows.Threading import DispatcherPriority, DispatcherTimer

import fpp_core
import fpp_dialogs
import fpp_revit
from fpp_chrome import Table, ThemedWindow
from fpp_core import to_text
from fpp_replace import ReplaceTab


class FamilyParamPush(ThemedWindow):
    def __init__(self, uiapp, doc, families, settings, runner):
        self.uiapp = uiapp
        self.doc = doc
        self.families = families
        self.runner = runner
        self.picks = fpp_core.Picks()
        self.opened_left = set()
        self.opened_right = set()
        self.focus = []
        self.suspend = 0
        self.sel_pending = False
        self.busy = False
        self.armed = False
        self.dirty = False
        self.source_params = []
        self.target_params = []
        self.active = 'push'
        ThemedWindow.__init__(self, 'FamilyParamPush.xaml', settings)
        self.window.Width = float(settings.get('width', 1360))
        self.window.Height = float(settings.get('height', 860))
        self.bind_controls()
        self.build_tables()
        self.replace = ReplaceTab(self)
        self.wire()
        self.load_families()
        self.refresh_all()

    def sibling_names(self):
        return ['tab_strip', 'body_grid', 'body_replace', 'footer_bar']

    # ----- engine proof -----
    def prove_alive(self):
        if self.armed:
            self.armed = False
            fpp_core.write_text(fpp_core.note_path(), u'')

    def on_mouse_move(self, sender, args):
        self.prove_alive()

    def is_busy(self):
        return self.busy

    def on_error(self, text):
        last = to_text(text).strip().splitlines()
        self.set_status(u'Something went wrong: ' + (last[-1] if last else u''),
                        True)

    # ----- build -----
    def bind_controls(self):
        for name in ('combo_category', 'txt_search', 'txt_count', 'grid_left',
                     'grid_right', 'grid_source', 'grid_target', 'grid_maps',
                     'btn_push', 'btn_back', 'btn_add', 'btn_unmap',
                     'btn_reload', 'btn_run', 'txt_run', 'txt_status',
                     'txt_focus', 'search_source', 'search_target', 'tick_debug',
                     'tick_clear', 'combo_sets', 'btn_save_set',
                     'btn_load_set', 'btn_delete_set', 'btn_tab_push',
                     'btn_tab_replace', 'body_grid', 'body_replace',
                     'progress_band', 'progress_bar',
                     'txt_progress'):
            setattr(self, name, self.find(name))

    def tree_column(self, header, stars):
        column = DataGridTemplateColumn()
        column.Header = header
        column.CellTemplate = self.window.FindResource('TreeNameCell')
        column.Width = DataGridLength(stars, DataGridLengthUnitType.Star)
        column.MinWidth = 120
        return column

    def text_column(self, header, name, stars, minimum=60):
        column = DataGridTextColumn()
        column.Header = header
        column.Binding = Binding(name)
        column.Width = DataGridLength(stars, DataGridLengthUnitType.Star)
        column.MinWidth = minimum
        column.IsReadOnly = True
        return column

    def columns(self, grid, items):
        for item in items:
            grid.Columns.Add(item)

    def build_tables(self):
        self.columns(self.grid_left, [
            self.tree_column(u'Family / type', 3),
            self.text_column(u'Category', 'cat', 1.3),
            self.text_column(u'Placed', 'count', 0.5, 56)])
        self.columns(self.grid_right, [
            self.tree_column(u'Family / type', 3),
            self.text_column(u'Types', 'count', 0.7, 64),
            self.text_column(u'Mappings', 'note', 1, 96)])
        for grid in (self.grid_source, self.grid_target):
            self.columns(grid, [
                self.text_column(u'Parameter', 'name', 3, 120),
                self.text_column(u'Applies to', 'scope', 1, 64),
                self.text_column(u'Kind', 'kind', 0.9, 56),
                self.text_column(u'Value', 'sample', 1.5, 60)])
        self.columns(self.grid_maps, [
            self.text_column(u'Push from', 'source', 2, 120),
            self.text_column(u'Into', 'target', 2, 120),
            self.text_column(u'How', 'how', 2, 120),
            self.text_column(u'Families', 'count', 0.6, 60)])
        tree = ['key', 'kind', 'text', 'cat', 'count', 'open', 'picked', 'note']
        param = ['key', 'name', 'scope', 'kind', 'origin', 'sample']
        self.left = Table(self.grid_left, tree)
        self.right = Table(self.grid_right, tree)
        self.source = Table(self.grid_source, param, True)
        self.target = Table(self.grid_target, param, True)
        self.maps = Table(self.grid_maps,
                          ['key', 'source', 'target', 'how', 'count'])

    def wire(self):
        self.search_timer = DispatcherTimer()
        self.search_timer.Interval = TimeSpan.FromMilliseconds(220)
        self.search_timer.Tick += self.safe(self.on_search_tick)
        self.tick_debug.IsChecked = self.settings.get('debug') == '1'
        self.tick_clear.IsChecked = self.settings.get('clear_empty') == '1'
        self.window.PreviewMouseMove += self.on_mouse_move
        self.window.Closing += self.safe(self.on_closing)
        self.window.Closed += self.safe(self.on_closed)
        self.combo_category.SelectionChanged += self.safe(self.on_category)
        self.txt_search.TextChanged += self.safe(self.on_search)
        self.search_source.TextChanged += self.safe(self.on_param_search)
        self.search_target.TextChanged += self.safe(self.on_param_search)
        self.grid_left.SelectionChanged += self.safe(self.on_left_selection)
        self.grid_right.SelectionChanged += self.safe(self.on_right_selection)
        for grid in (self.grid_source, self.grid_target):
            grid.SelectionChanged += self.safe(self.on_param_selection)
        self.grid_maps.SelectionChanged += self.safe(self.on_maps_selection)
        self.grid_left.MouseDoubleClick += self.safe(self.on_left_double)
        self.grid_target.MouseDoubleClick += self.safe(self.on_add)
        for grid, handler in ((self.grid_left, self.on_left_caret),
                              (self.grid_right, self.on_right_caret)):
            grid.AddHandler(ButtonBase.ClickEvent, self.routed(handler))
        self.btn_push.Click += self.safe(self.on_push)
        self.btn_back.Click += self.safe(self.on_back)
        self.btn_add.Click += self.safe(self.on_add)
        self.btn_unmap.Click += self.safe(self.on_unmap)
        self.btn_reload.Click += self.safe(self.on_reload)
        self.btn_run.Click += self.safe(self.on_run)
        self.btn_tab_push.Click += self.safe(self.on_tab_push)
        self.btn_tab_replace.Click += self.safe(self.on_tab_replace)
        self.btn_save_set.Click += self.safe(self.on_save_set)
        self.btn_load_set.Click += self.safe(self.on_load_set)
        self.btn_delete_set.Click += self.safe(self.on_delete_set)
        self.combo_sets.SelectionChanged += self.safe(self.on_set_choice)
        self.tick_debug.Click += self.safe(self.on_ticks)
        self.tick_clear.Click += self.safe(self.on_ticks)

    def routed(self, handler):
        from System.Windows import RoutedEventHandler
        return RoutedEventHandler(self.safe(handler))

    # ----- tabs -----
    def show_tab(self, name):
        self.active = name
        replace = name == 'replace'
        self.body_grid.Visibility = Visibility.Collapsed if replace \
            else Visibility.Visible
        self.body_replace.Visibility = Visibility.Visible if replace \
            else Visibility.Collapsed
        self.tick_clear.Visibility = Visibility.Collapsed if replace \
            else Visibility.Visible
        self.btn_tab_push.Tag = u'' if replace else u'on'
        self.btn_tab_replace.Tag = u'on' if replace else u''
        if replace:
            self.replace.on_open()
        self.update_buttons()

    def on_tab_push(self, sender, args):
        self.show_tab('push')

    def on_tab_replace(self, sender, args):
        self.show_tab('replace')

    # ----- left list -----
    def load_families(self):
        self.suspend += 1
        chosen = to_text(self.combo_category.SelectedItem)
        options = fpp_core.category_options(self.families)
        self.combo_category.Items.Clear()
        for name in options:
            self.combo_category.Items.Add(name)
        self.combo_category.SelectedItem = chosen if chosen in options \
            else options[0]
        self.suspend -= 1

    def category(self):
        return to_text(self.combo_category.SelectedItem)

    def refresh_left(self):
        self.suspend += 1
        rows = fpp_core.family_rows(self.families, self.category(),
                                    self.txt_search.Text, self.opened_left,
                                    self.picks)
        self.left.fill(rows)
        self.suspend -= 1
        count = len([r for r in rows if r['kind'] == u'f'])
        self.txt_count.Text = u'{0} famil{1}'.format(
            count, u'y' if count == 1 else u'ies')
        self.update_buttons()

    def on_category(self, sender, args):
        if not self.suspend:
            self.refresh_left()

    def on_search(self, sender, args):
        self.search_timer.Stop()
        self.search_timer.Start()

    def on_search_tick(self, sender, args):
        self.search_timer.Stop()
        self.refresh_left()

    def on_left_selection(self, sender, args):
        if not self.suspend:
            self.update_buttons()

    def toggle(self, args, opened, refresh):
        source = args.OriginalSource
        if to_text(getattr(source, 'Name', u'')) != u'caret':
            return                      # a column heading is a ButtonBase too
        key = to_text(source.DataContext['key'])
        if key.startswith(u'f:'):
            fkey = key[2:]
            if fkey in opened:
                opened.discard(fkey)
            else:
                opened.add(fkey)
            refresh()
        args.Handled = True

    def on_left_caret(self, sender, args):
        self.toggle(args, self.opened_left, self.refresh_left)

    def on_right_caret(self, sender, args):
        self.toggle(args, self.opened_right, self.refresh_right)

    def on_left_double(self, sender, args):
        if self.left.keys():
            self.on_push(sender, args)

    # ----- pushing across -----
    def family_lookup(self):
        return dict([(f.key, f) for f in self.families])

    def on_push(self, sender, args):
        lookup = self.family_lookup()
        wanted = {}
        for key in self.left.keys():
            if key.startswith(u'f:'):
                fam = lookup.get(key[2:])
                if fam is not None:
                    wanted[fam.key] = (fam, [t.idv for t in fam.types])
        owners = dict([(t.idv, f) for f in self.families for t in f.types])
        for key in self.left.keys():
            if key.startswith(u't:'):
                fam = owners.get(int(key[2:]))
                if fam is not None and fam.key not in wanted:
                    wanted.setdefault(fam.key, (fam, []))
                    wanted[fam.key][1].append(int(key[2:]))
                elif fam is not None and fam.key in wanted \
                        and int(key[2:]) not in wanted[fam.key][1]:
                    wanted[fam.key][1].append(int(key[2:]))
        if not wanted:
            return
        for fam, ids in wanted.values():
            self.picks.add(fam, ids)
        self.dirty = True
        self.grid_left.UnselectAll()
        self.refresh_left()
        self.refresh_right([u'f:' + k for k in wanted])
        self.after_right()

    def on_back(self, sender, args):
        self.picks.remove_keys(self.right.keys())
        self.grid_right.UnselectAll()
        self.refresh_left()
        self.refresh_right()
        self.after_right()

    # ----- right list -----
    def refresh_right(self, keep=None):
        self.suspend += 1
        self.right.fill(fpp_core.picked_rows(self.picks, self.opened_right),
                        keep)
        self.suspend -= 1
        self.update_buttons()

    def on_right_selection(self, sender, args):
        if self.suspend:
            return
        self.update_buttons()
        if self.sel_pending:
            return
        self.sel_pending = True
        self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background,
                                           Action(self.after_right_queued))

    def after_right_queued(self):
        self.sel_pending = False
        self.safe(lambda s, a: self.after_right())()

    def after_right(self):
        self.focus = self.picks.family_keys_of(self.right.keys())
        names = [self.picks.items[k].fam.name for k in self.focus]
        if not names:
            self.txt_focus.Text = u'Select a family above to map its parameters'
        elif len(names) == 1:
            self.txt_focus.Text = names[0]
        else:
            self.txt_focus.Text = u'{0} families: what they share'.format(
                len(names))
        self.load_params()
        self.refresh_maps()

    def load_params(self, quiet=False):
        missing = [k for k in self.focus
                   if self.picks.items[k].params is None]
        if not missing:
            self.refresh_params()
            return
        if not quiet:
            self.set_status(u'Reading parameters...')
        picks = [self.picks.items[k] for k in missing]
        def work(uiapp):
            return [(p, fpp_revit.discover_params(self.live_doc(uiapp), p))
                    for p in picks]
        def done(result, error):
            if error:
                self.on_error(error)
                return
            for pick, found in result:
                pick.params = found
            if not quiet:
                self.set_status(u'Ready.')
            self.refresh_params()
        self.submit(u'parameters', work, done)

    def refresh_params(self):
        items = [self.picks.items[k].params for k in self.focus
                 if self.picks.items[k].params is not None]
        complete = len(items) == len(self.focus)
        lists = items if complete else []
        self.source_params = fpp_core.merge_params(lists)
        self.target_params = fpp_core.merge_params(lists, True)
        self.fill_params()

    def fill_params(self):
        self.suspend += 1
        self.source.fill(fpp_core.param_rows(fpp_core.filter_params(
            self.source_params, self.search_source.Text)))
        self.target.fill(fpp_core.param_rows(fpp_core.filter_params(
            self.target_params, self.search_target.Text)))
        self.suspend -= 1
        self.update_buttons()

    def on_param_search(self, sender, args):
        self.fill_params()

    def on_param_selection(self, sender, args):
        if not self.suspend:
            self.update_buttons()

    # ----- mappings -----
    def param_named(self, params, keys):
        for param in params:
            if param.key in keys:
                return param
        return None

    def on_add(self, sender, args):
        src = self.param_named(self.source_params, self.source.keys())
        tgt = self.param_named(self.target_params, self.target.keys())
        if src is None or tgt is None or not self.focus:
            return
        added, refusal = self.picks.add_mapping(self.focus, src, tgt)
        if added:
            self.dirty = True
        self.refresh_right(self.right.keys())
        self.refresh_maps()
        self.set_status(refusal or u'Mapped {0} to {1}.'.format(src.name,
                                                                tgt.name),
                        bool(refusal))

    def on_unmap(self, sender, args):
        self.picks.remove_mappings(self.focus, self.maps.keys())
        self.refresh_right(self.right.keys())
        self.refresh_maps()

    def refresh_maps(self):
        self.suspend += 1
        self.maps.fill(self.picks.mapping_rows(self.focus), [])
        self.suspend -= 1
        self.update_buttons()

    def on_maps_selection(self, sender, args):
        if not self.suspend:
            self.update_buttons()

    # ----- saved sets -----
    def chosen_set(self):
        return to_text(self.combo_sets.SelectedItem)

    def refresh_sets(self, chosen=None):
        self.suspend += 1
        names = fpp_core.list_sets()
        keep = chosen if chosen is not None else self.chosen_set()
        self.combo_sets.Items.Clear()
        for name in names:
            self.combo_sets.Items.Add(name)
        self.combo_sets.SelectedItem = keep if keep in names else None
        self.suspend -= 1
        self.update_buttons()

    def on_set_choice(self, sender, args):
        if not self.suspend:
            self.update_buttons()

    def on_save_set(self, sender, args):
        if not [p for p in self.picks.ordered() if p.mappings]:
            return
        name = fpp_dialogs.ask_text(self, u'Save Mappings',
                                    u'Name this set of mappings.',
                                    self.chosen_set())
        name = fpp_core.safe_name(name)
        if not name:
            return
        path = fpp_core.set_path(name)
        if name in fpp_core.list_sets() and not fpp_dialogs.ask(
                self, u'Save Mappings',
                u'"{0}" already exists. Replace it?'.format(name), u'Replace'):
            return
        if not fpp_core.write_text(path, fpp_core.set_text(self.picks)):
            self.set_status(u'Could not save "{0}".'.format(name), True)
            return
        self.dirty = False
        self.refresh_sets(name)
        self.set_status(u'Saved "{0}".'.format(name))

    def on_load_set(self, sender, args):
        name = self.chosen_set()
        if not name:
            return
        entries = fpp_core.parse_set(
            fpp_core.read_text(fpp_core.set_path(name)))
        loaded, missing = fpp_core.apply_set_picks(self.picks, self.families,
                                                   entries)
        needed = [pick for _entry, pick in loaded if pick.params is None]
        self.set_status(u'Loading "{0}"...'.format(name))
        def work(uiapp):
            return [(p, fpp_revit.discover_params(self.live_doc(uiapp), p))
                    for p in needed]
        def done(result, error):
            if error:
                self.on_error(error)
                return
            for pick, found in result:
                pick.params = found
            self.after_load(name, loaded, missing)
        self.submit(u'load set', work, done)

    def after_load(self, name, loaded, missing):
        added, problems = fpp_core.bind_set(self.picks, loaded)
        problems = missing + problems
        self.grid_left.UnselectAll()
        self.refresh_left()
        self.refresh_right([u'f:' + pick.fam.key for _entry, pick in loaded])
        self.after_right()
        self.dirty = False
        line = u'Loaded "{0}": {1} mapping{2} on {3} famil{4}.'.format(
            name, added, u'' if added == 1 else u's', len(loaded),
            u'y' if len(loaded) == 1 else u'ies')
        self.set_status(line, bool(problems))
        if problems:
            text = u'{0}\n\n{1}'.format(line, u'\n'.join(problems))
            fpp_dialogs.tell(self, u'Needs a look', text, text)

    def on_delete_set(self, sender, args):
        name = self.chosen_set()
        if not name or not fpp_dialogs.ask(
                self, u'Delete saved mappings',
                u'Delete "{0}"? Mappings on screen stay.'.format(name),
                u'Delete'):
            return
        os.remove(fpp_core.set_path(name))
        self.refresh_sets(u'')
        self.set_status(u'Deleted "{0}".'.format(name))

    # ----- state -----
    def refresh_all(self):
        self.refresh_sets()
        self.refresh_left()
        self.refresh_right()
        self.after_right()
        self.set_status(u'Ready.')

    def update_buttons(self):
        count = self.picks.mapping_count()
        self.btn_push.IsEnabled = bool(self.left.keys())
        self.btn_back.IsEnabled = bool(self.right.keys())
        self.btn_add.IsEnabled = bool(self.source.keys()) \
            and bool(self.target.keys()) and bool(self.focus)
        self.btn_unmap.IsEnabled = bool(self.maps.keys())
        self.btn_run.IsEnabled = count > 0 and not self.busy
        self.btn_save_set.IsEnabled = bool(
            [p for p in self.picks.ordered() if p.mappings])
        self.btn_load_set.IsEnabled = bool(self.chosen_set()) and not self.busy
        self.btn_delete_set.IsEnabled = bool(self.chosen_set())
        self.txt_run.Text = u'Run ({0})'.format(count) if count else u'Run'
        self.replace.update_buttons()

    def set_status(self, text, bad=False):
        self.txt_status.Text = text
        key = 'RedBrush' if bad else 'MutedBrush'
        self.txt_status.SetResourceReference(TextBlock.ForegroundProperty, key)

    def on_ticks(self, sender, args):
        self.settings['debug'] = u'1' if self.tick_debug.IsChecked else u'0'
        self.settings['clear_empty'] = u'1' if self.tick_clear.IsChecked \
            else u'0'
        fpp_core.save_settings(self.settings)

    # ----- jobs -----
    def live_doc(self, uiapp):
        """Element ids belong to the document they were read from."""
        doc = uiapp.ActiveUIDocument.Document
        if not doc.Equals(self.doc):
            raise ValueError(u'The active model is not the one this window '
                             u'read. Switch back, or close and reopen the '
                             u'tool.')
        return doc

    def submit(self, name, work, done):
        accepted = self.runner.submit(name, work, done, self.window.Dispatcher)
        if not accepted:
            self.busy = False
            self.update_buttons()
            self.set_status(u'Revit would not take the request. Try again.',
                            True)

    def on_reload(self, sender, args):
        def work(uiapp):
            return fpp_revit.read_model(self.live_doc(uiapp))
        def done(result, error):
            if error:
                self.on_error(error)
                return
            self.families = result
            self.picks.sync(self.families)
            self.load_families()
            self.refresh_all()
            self.replace.on_families()
        self.set_status(u'Reloading families...')
        self.submit(u'reload', work, done)

    def on_progress(self, percent, label):
        self.progress_bar.Value = percent
        self.txt_progress.Text = u'{0}%  {1}'.format(percent, to_text(label))
        self.repaint()

    def start_job(self):
        self.busy = True
        self.update_buttons()
        self.progress_band.Visibility = Visibility.Visible
        self.set_status(u'Waiting for Revit...')

    def end_job(self):
        self.busy = False
        self.progress_band.Visibility = Visibility.Collapsed
        self.update_buttons()

    def on_run(self, sender, args):
        if self.active == 'replace':
            self.replace.on_run()
            return
        if self.busy or not self.picks.ready():
            return
        self.start_job()
        clear = self.settings.get('clear_empty') == '1'
        picks = self.picks
        def work(uiapp):
            return fpp_revit.run_push(self.live_doc(uiapp), picks, clear,
                                      self.on_progress)
        self.submit(u'run', work, self.on_run_done)

    def on_run_done(self, rep, error):
        self.end_job()
        if error:
            self.on_error(error)
            fpp_dialogs.tell(self, u'Family Param Push', to_text(error), error)
            return
        self.dirty = False
        line = fpp_core.status_line(rep)
        problems = fpp_core.problem_lines(rep)
        fpp_core.log(self.settings, line)
        for problem in problems:
            fpp_core.log(self.settings, problem)
        self.set_status(line, bool(problems))
        self.reload_params()
        if problems:
            text = u'{0}\n\n{1}'.format(line, u'\n'.join(problems))
            fpp_dialogs.tell(self, u'Needs a look', text, text)

    def reload_params(self):
        for pick in self.picks.ordered():
            pick.params = None
        self.load_params(True)          # the result line stays on screen

    # ----- keys and closing -----
    def text_has_focus(self):
        focused = Keyboard.FocusedElement
        return focused in (self.txt_search, self.search_source,
                           self.search_target, self.replace.txt_rsearch,
                           self.replace.search_rsource,
                           self.replace.search_rtarget)

    def on_key(self, args):
        if args.Key == Key.Escape:
            if self.text_has_focus():
                Keyboard.FocusedElement.Text = u''
            elif self.full:
                self.leave_full()
            else:
                self.window.Close()
            args.Handled = True
        elif args.Key == Key.Delete and not self.text_has_focus():
            if self.active == 'replace':
                self.replace.on_delete_key()
            elif self.maps.keys():
                self.on_unmap(None, None)
            elif self.right.keys():
                self.on_back(None, None)
            args.Handled = True

    def on_closing(self, sender, args):
        if self.window.Tag == 'replace':
            return
        if self.busy:
            args.Cancel = True
            return
        if (self.dirty and self.picks.mapping_count()) \
                or self.replace.picks.mapping_count():
            if not fpp_dialogs.ask(self, u'Close Family Param Push?',
                                   u'Your mappings have not been run and will '
                                   u'be lost.', u'Close', u'Keep open'):
                args.Cancel = True

    def on_closed(self, sender, args):
        self.search_timer.Stop()
        self.drawer.settle()
        self.leave_full()
        self.settings['width'] = to_text(int(self.window.Width))
        self.settings['height'] = to_text(int(self.window.Height))
        fpp_core.save_settings(self.settings)
        fpp_core.write_text(fpp_core.note_path(), u'')
