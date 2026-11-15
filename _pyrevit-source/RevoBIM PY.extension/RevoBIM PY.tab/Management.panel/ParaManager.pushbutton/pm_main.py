# -*- coding: utf-8 -*-
"""The ParaManager window."""
import pm_clr
import clr
import os
import traceback

from System import Action, Boolean, Enum, Int32, String, TimeSpan
from System.Windows import (DataTemplate, FrameworkElementFactory, RoutedEventHandler,
                            Thickness, Visibility)
from System.Windows.Controls import (Button, ComboBox, DataGridColumn, DataGridLength,
                                     DataGridLengthUnitType, DataGridRow,
                                     DataGridTemplateColumn)
from System.Windows.Controls.Primitives import PlacementMode
from System.Windows.Data import Binding, BindingMode, IValueConverter, UpdateSourceTrigger
from System.Windows.Input import Cursors, Mouse
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Media import Geometry, VisualTreeHelper
from System.Windows.Shapes import Path
from System.Windows.Threading import DispatcherPriority, DispatcherTimer
from Microsoft.Win32 import OpenFileDialog, SaveFileDialog

import pm_chrome
import pm_core as core
import pm_dialogs as dialogs
import pm_revit
import pm_spfile as spfile
import pm_xlsx
from pm_dialogs import ask, ask_choice, ask_text, make_table, string_list, tell

HOLD = {}                # keeps the modeless window alive for the engine
P_EDIT = ('name', 'disc', 'ptype', 'group', 'scope')
S_EDIT = ('name', 'ptype', 'group', 'desc', 'user', 'shown', 'hide')
YES_NO = [u'Yes', u'No']


def yes_no(flag):
    return u'Yes' if flag == spfile.YES else u'No'


def flag_of(text):
    return spfile.YES if text == u'Yes' else spfile.NO


def set_cell(row, name, value):
    if core.to_text(row[name]) != core.to_text(value):
        row[name] = value


class SpecsFor(IValueConverter):
    """The Type of Parameter list follows the row's discipline."""

    def __init__(self, lists):
        self.lists = lists

    def Convert(self, value, target, parameter, culture):
        return self.lists.get(core.to_text(value), self.lists.get(u'Common'))

    def ConvertBack(self, value, target, parameter, culture):
        raise NotImplementedError()


class MainWindow(pm_chrome.ThemedWindow):
    def __init__(self, uiapp, settings):
        pm_chrome.ThemedWindow.__init__(self, 'ParaManager.xaml', u'ParaManager', settings)
        self.uiapp = uiapp
        self.doc = uiapp.ActiveUIDocument.Document
        self.data = {}
        self.recs = []
        self.by_id = {}
        self.rows = {}
        self.table = None
        self.view = None
        self.sp = None
        self.sp_rows = {}
        self.sp_cells = {}
        self.sp_table = None
        self.sp_view = None
        self.next_rid = 100000
        self.next_sp = 0
        self.busy = False
        self.loading = False
        self.sort_col = {}
        self.proved = False
        self.spec_lists = {}
        self.groups_file = core.groups_path()
        self.category_groups = core.load_category_groups(self.groups_file)
        self.runner = pm_revit.Runner(self.win.Dispatcher, self.on_stuck)
        for key, values in (('ScopeItems', [core.INSTANCE, core.TYPE]), ('YesNoItems', YES_NO),
                            ('DiscList', []), ('GroupItems', []), ('SpTypeItems', []),
                            ('SpGroupItems', [])):
            self.win.Resources[key] = string_list(values)
        self.win.Width = float(settings.get('width', 1290))
        self.win.Height = float(settings.get('height', 640))
        self.search_timer = DispatcherTimer()
        self.search_timer.Interval = TimeSpan.FromMilliseconds(220)
        self.search_timer.Tick += self.on_search_tick
        self.wire()
        self.e('DebugTick').IsChecked = settings.get('debug') == '1'
        self.reload()
        self.add_type_column()
        for name in ('ParamGrid', 'CatsGrid', 'SpGrid'):
            # a grid column is not in the element tree, so it cannot take a DynamicResource
            self.e(name).Columns[1].CellTemplate = self.win.FindResource('StateCell')

    # ---- wiring

    def wire(self):
        clicks = (('NextBtn', self.on_next), ('PrevBtn', self.on_prev), ('ApplyBtn', self.on_apply),
                  ('SaveBtn', self.on_save), ('AddParamBtn', self.on_add_param),
                  ('ImportExportBtn', self.on_import_export), ('ImportExportBtn2', self.on_import_export),
                  ('BatchBtn', self.on_batch), ('AssignBtn', self.on_assign),
                  ('LoadSpBtn', self.on_load_sp), ('AddSpBtn', self.on_add_sp),
                  ('GroupsBtn', self.on_groups), ('RenameBtn', self.on_rename),
                  ('BatchSpBtn', self.on_batch_sp), ('RefreshBtn', self.on_refresh),
                  ('TickAllP', self.on_tick_all), ('TickAllC', self.on_tick_all),
                  ('TickAllS', self.on_tick_all_sp), ('ShowExistingP', self.on_show_existing),
                  ('ShowExistingC', self.on_show_existing), ('DebugTick', self.on_debug))
        for name, handler in clicks:
            self.e(name).Click += handler
        for name in ('TabParams', 'TabCats', 'TabTransfer', 'TabFamilies', 'TabShared'):
            self.e(name).Checked += self.on_tab
        for name in ('SearchP', 'SearchC', 'SearchS'):
            self.e(name).TextChanged += self.on_search
        for name in ('KindP', 'KindC'):
            combo = self.e(name)
            combo.ItemsSource = string_list([core.KIND_ALL, core.KIND_SHARED, core.KIND_PROJECT])
            combo.SelectedIndex = 0
            combo.SelectionChanged += self.on_kind
        self.e('CatsGrid').AddHandler(Button.ClickEvent, RoutedEventHandler(self.on_row_categories))
        for name in ('ParamGrid', 'CatsGrid'):
            self.e(name).Sorting += self.on_sort_params
        self.e('SpGrid').Sorting += self.on_sort_shared
        self.e('SpGrid').PreviewMouseRightButtonUp += self.on_sp_right_click
        self.win.Closing += self.on_closing
        self.win.PreviewMouseMove += self.on_first_move

    def add_type_column(self):
        """Built in code: its list depends on the row, which needs a converter object."""
        factory = FrameworkElementFactory(clr.GetClrType(ComboBox))
        factory.SetValue(ComboBox.MarginProperty, Thickness(1.0))
        items = Binding('disc')
        items.Converter = SpecsFor(self.spec_lists)
        factory.SetBinding(ComboBox.ItemsSourceProperty, items)
        chosen = Binding('ptype')
        chosen.Mode = BindingMode.TwoWay
        chosen.UpdateSourceTrigger = UpdateSourceTrigger.PropertyChanged
        factory.SetBinding(ComboBox.SelectedItemProperty, chosen)
        factory.SetBinding(ComboBox.IsEnabledProperty, Binding('free'))
        template = DataTemplate()
        template.VisualTree = factory
        column = DataGridTemplateColumn()
        column.Header = u'Type of Parameter'
        column.SortMemberPath = 'ptype'
        column.MinWidth = 120
        column.Width = DataGridLength(1.3, DataGridLengthUnitType.Star)
        column.CellTemplate = template
        self.e('ParamGrid').Columns.Insert(5, column)

    # ---- reading the project

    def reload(self):
        Mouse.OverrideCursor = Cursors.Wait
        try:
            self.data = pm_revit.read_project(self.doc)
            self.recs = self.data['recs']
            self.spec_lists.clear()
            for disc in self.data['specs']:
                labels = sorted(self.data['specs'][disc], key=lambda t: t.lower())
                self.spec_lists[disc] = string_list(labels)
            self.win.Resources['DiscList'] = string_list(sorted(self.data['specs']))
            self.win.Resources['GroupItems'] = string_list(
                sorted(self.data['groups'], key=lambda t: t.lower()))
            self.build_table()
        finally:
            Mouse.OverrideCursor = None

    def build_table(self):
        self.loading = True
        table = make_table((('rid', Int32), ('tick', Boolean), ('state', String), ('name', String),
                            ('kind', String), ('disc', String), ('ptype', String),
                            ('group', String), ('scope', String), ('cats', String),
                            ('free', Boolean), ('vis', String), ('gkey', Int32)))
        self.by_id = {}
        self.rows = {}
        for rank, rec in enumerate(self.recs):
            self.add_row(table, rec, rank)
        table.ColumnChanged += self.on_param_cell
        self.table = table
        self.view = table.DefaultView
        self.view.RowFilter = "vis = '1'"
        self.view.Sort = 'gkey ASC'
        self.e('ParamGrid').ItemsSource = self.view
        self.e('CatsGrid').ItemsSource = self.view
        self.loading = False
        self.refilter()
        self.update_status()

    def add_row(self, table, rec, rank):
        row = table.NewRow()
        row['rid'] = rec.rid
        row['tick'] = rec.tick
        row['state'] = rec.state()
        row['name'] = rec.name
        row['kind'] = rec.kind
        row['disc'] = rec.disc
        row['ptype'] = rec.ptype
        row['group'] = rec.group
        row['scope'] = rec.scope
        row['cats'] = core.join_categories(rec.cats)
        row['free'] = rec.free
        row['vis'] = u'1'
        row['gkey'] = rank
        table.Rows.Add(row)
        self.by_id[rec.rid] = rec
        self.rows[rec.rid] = row
        return row

    # ---- the parameter table

    def on_param_cell(self, sender, args):
        if self.loading:
            return
        name = args.Column.ColumnName
        rec = self.by_id.get(int(args.Row['rid']))
        if rec is None:
            return
        if name == 'tick':
            rec.tick = bool(args.Row['tick'])
            return
        if name not in P_EDIT:
            return
        value = core.to_text(args.Row[name])
        allowed = rec.free or name in ('group', 'scope')
        if not allowed or (not value and name != 'name'):
            # a recycled combo can write a blank into the row it lands on
            self.quiet(args.Row, name, getattr(rec, name))
            return
        setattr(rec, name, value)
        if name == 'disc':
            first = self.spec_lists.get(value)
            rec.ptype = first[0] if first is not None and first.Count else u''
            self.quiet(args.Row, 'ptype', rec.ptype)
        self.mark(rec)

    def quiet(self, row, name, value):
        self.loading = True
        try:
            if core.to_text(row[name]) != core.to_text(value):
                row[name] = value
        finally:
            self.loading = False

    def mark(self, rec):
        self.quiet(self.rows[rec.rid], 'state', rec.state())
        self.update_status()

    def update_status(self):
        self.e('StatusText').Text = core.status_line(self.recs)
        plan = core.build_plan(self.recs)
        total = len(plan['create']) + len(plan['modify']) + len(plan['delete'])
        self.e('ApplyBtn').IsEnabled = total > 0
        self.e('ApplyBtn').Content = u'Apply ({0})'.format(total) if total else u'Apply'

    def filter_state(self):
        return (core.to_text(self.e('KindP').SelectedItem), self.e('SearchP').Text,
                bool(self.e('ShowExistingP').IsChecked))

    def refilter(self):
        kind, search, existing = self.filter_state()
        self.loading = True
        try:
            for rec in self.recs:
                flag = u'1' if core.rec_visible(rec, kind, search, existing) else u'0'
                set_cell(self.rows[rec.rid], 'vis', flag)
        finally:
            self.loading = False

    def visible_recs(self):
        return [r for r in self.recs if core.to_text(self.rows[r.rid]['vis']) == u'1']

    def on_tick_all(self, sender, args):
        value = bool(sender.IsChecked)
        for rec in self.visible_recs():
            self.rows[rec.rid]['tick'] = value

    def ticked(self):
        return [r for r in self.visible_recs() if r.tick]

    def on_kind(self, sender, args):
        other = self.e('KindC') if sender is self.e('KindP') else self.e('KindP')
        if other.SelectedIndex != sender.SelectedIndex:
            other.SelectedIndex = sender.SelectedIndex
        self.refilter()

    def on_show_existing(self, sender, args):
        value = bool(sender.IsChecked)
        self.e('ShowExistingP').IsChecked = value
        self.e('ShowExistingC').IsChecked = value
        self.refilter()

    def on_search(self, sender, args):
        if sender is self.e('SearchP') or sender is self.e('SearchC'):
            other = self.e('SearchC') if sender is self.e('SearchP') else self.e('SearchP')
            if other.Text != sender.Text:
                other.Text = sender.Text
        self.search_timer.Stop()
        self.search_timer.Start()

    def on_search_tick(self, sender, args):
        self.search_timer.Stop()
        self.refilter()
        self.refilter_sp()

    def next_sort(self, column):
        descending = self.sort_col.get('col') == column.SortMemberPath and not self.sort_col.get('desc')
        self.sort_col = {'col': column.SortMemberPath, 'desc': descending}
        try:
            prop = clr.GetClrType(DataGridColumn).GetProperty('SortDirection')
            kind = prop.PropertyType.GetGenericArguments()[0]
            column.SortDirection = Enum.Parse(kind, 'Descending' if descending else 'Ascending')
        except Exception:
            pass
        return descending

    def on_sort_params(self, sender, args):
        args.Handled = True
        field = args.Column.SortMemberPath
        descending = self.next_sort(args.Column)

        def value_of(rec):
            return core.join_categories(rec.cats) if field == 'cats' else getattr(rec, field)

        ranks = core.sort_ranks(self.recs, value_of, descending, lambda r: r.is_new)
        self.loading = True
        try:
            for index, rec in enumerate(self.recs):
                set_cell(self.rows[rec.rid], 'gkey', ranks[index])
        finally:
            self.loading = False

    # ---- add, import, batch

    def icon(self, data, brush_key):
        path = Path()
        path.Data = Geometry.Parse(data)
        path.StrokeThickness = 1.6
        path.Stroke = self.palette[brush_key]
        return path

    def open_menu(self, menu, button):
        menu.PlacementTarget = button
        menu.Placement = PlacementMode.Bottom
        menu.IsOpen = True

    def on_add_param(self, sender, args):
        menu = self.new_menu()
        self.menu_item(menu, u'New parameter', self.on_add_typed)
        self.menu_item(menu, u'From a shared parameter file', self.on_add_from_file)
        self.open_menu(menu, sender)

    def new_rid(self):
        self.next_rid += 1
        return self.next_rid

    def append_rec(self, rec):
        rec.tick = True
        self.recs.append(rec)
        self.add_row_live(rec)

    def add_row_live(self, rec):
        self.loading = True
        try:
            self.add_row(self.table, rec, len(self.recs) + 100000)
        finally:
            self.loading = False
        self.mark(rec)
        grid = self.e('ParamGrid' if self.e('TabParams').IsChecked else 'CatsGrid')
        self.win.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(
            lambda: grid.ScrollIntoView(grid.Items[grid.Items.Count - 1]) if grid.Items.Count else None))

    def on_add_typed(self, sender, args):
        name = core.next_free_name([r.name for r in self.recs])
        lists = self.data['specs']
        disc = u'Common' if u'Common' in lists else sorted(lists)[0]
        ptype = u'Text' if u'Text' in lists[disc] else sorted(lists[disc])[0]
        group = u'Other' if u'Other' in self.data['groups'] else sorted(self.data['groups'])[0]
        self.append_rec(core.Rec(self.new_rid(), name, core.KIND_SHARED, disc, ptype, group,
                                 core.INSTANCE, [], source=u'typed'))

    def on_add_from_file(self, sender, args):
        path = core.to_text(self.doc.Application.SharedParametersFilename)
        guids = set(r.guid.lower() for r in self.recs if r.guid)
        names = set(r.name.lower() for r in self.recs)
        chosen = dialogs.PickParamsWindow(self, path, guids, names).show()
        if not chosen:
            return
        source, rows = chosen
        group = u'Other' if u'Other' in self.data['groups'] else sorted(self.data['groups'])[0]
        common = self.spec_lists.get(u'Common')
        for row, _name in rows:
            label = spfile.type_label(row.dtype)
            if common is not None and not common.Contains(label):
                common.Add(label)
            self.append_rec(core.Rec(self.new_rid(), row.name, core.KIND_SHARED, u'Common',
                                     spfile.type_label(row.dtype), group, core.INSTANCE, [],
                                     guid=row.guid, source=u'file', sp_path=source))

    def on_import_export(self, sender, args):
        menu = self.new_menu()
        self.menu_item(menu, u'Export to Excel', self.on_export)
        self.menu_item(menu, u'Import from Excel', self.on_import)
        self.open_menu(menu, sender)

    def on_export(self, sender, args):
        dialog = SaveFileDialog()
        dialog.Filter = 'Excel workbook (*.xlsx)|*.xlsx'
        dialog.FileName = 'ParaManager parameters.xlsx'
        if not dialog.ShowDialog():
            return
        try:
            pm_xlsx.write_file(dialog.FileName, core.export_rows(self.recs))
            self.say(u'Exported to {0}'.format(dialog.FileName))
        except Exception as error:
            tell(self, u'Export', u'Could not write the file.\n\n{0}'.format(error))

    def on_import(self, sender, args):
        dialog = OpenFileDialog()
        dialog.Filter = 'Excel workbook (*.xlsx)|*.xlsx'
        if not dialog.ShowDialog():
            return
        try:
            rows = pm_xlsx.read_file(dialog.FileName)
        except Exception as error:
            tell(self, u'Import', u'Could not read the file.\n\n{0}'.format(error))
            return
        changes, notes = core.plan_import(rows, self.recs, self.data['groups'], self.data['cats'])
        text = [u'{0} parameter(s) will be staged. Nothing is written until Apply.'.format(len(changes))]
        if not ask(self, u'Import', u'\n'.join(text + notes[:60]), u'Stage'):
            return
        for rec, group, scope, cats in changes:
            row = self.rows[rec.rid]
            set_cell(row, 'group', group)
            set_cell(row, 'scope', scope)
            self.set_cats(rec, cats)

    def on_batch(self, sender, args):
        menu = self.new_menu()
        self.menu_item(menu, u'Set Group Under', self.on_batch_group)
        self.menu_item(menu, u'Set to Instance', self.on_batch_instance)
        self.menu_item(menu, u'Set to Type', self.on_batch_type)
        self.menu_item(menu, u'Delete', self.on_batch_delete)
        self.menu_item(menu, u'Restore', self.on_batch_restore)
        self.open_menu(menu, sender)

    def need_ticked(self):
        recs = self.ticked()
        if not recs:
            self.say(u'Tick some parameters first')
        return recs

    def on_batch_group(self, sender, args):
        recs = self.need_ticked()
        if not recs:
            return
        names = sorted(self.data['groups'], key=lambda t: t.lower())
        group = ask_choice(self, u'Group Under', u'Group {0} parameter(s) under:'.format(len(recs)), names)
        if group:
            for rec in recs:
                self.rows[rec.rid]['group'] = group

    def set_scope(self, scope):
        for rec in self.need_ticked():
            self.rows[rec.rid]['scope'] = scope

    def on_batch_instance(self, sender, args):
        self.set_scope(core.INSTANCE)

    def on_batch_type(self, sender, args):
        self.set_scope(core.TYPE)

    def on_batch_delete(self, sender, args):
        for rec in self.need_ticked():
            if rec.is_new:
                self.remove_rec(rec)
            else:
                rec.deleted = True
                self.mark(rec)

    def remove_rec(self, rec):
        self.recs.remove(rec)
        row = self.rows.pop(rec.rid)
        self.by_id.pop(rec.rid)
        self.loading = True
        try:
            self.table.Rows.Remove(row)
        finally:
            self.loading = False
        self.update_status()

    def on_batch_restore(self, sender, args):
        for rec in self.need_ticked():
            rec.deleted = False
            self.mark(rec)

    # ---- categories

    def on_assign(self, sender, args):
        recs = self.ticked() or self.selected_recs()
        if not recs:
            self.say(u'Tick some parameters first')
            return
        self.edit_categories(recs)

    def selected_recs(self):
        out = []
        for item in self.e('CatsGrid').SelectedItems:
            rec = self.by_id.get(int(item['rid']))
            if rec is not None:
                out.append(rec)
        return out

    def on_row_categories(self, sender, args):
        button = args.OriginalSource
        if core.to_text(getattr(button, 'Tag', None)) != u'cats':
            return
        rec = self.by_id.get(int(button.DataContext['rid']))
        if rec is None:
            return
        selected = self.selected_recs()
        self.edit_categories(selected if rec in selected and len(selected) > 1 else [rec])

    def edit_categories(self, recs):
        window = dialogs.CategoriesWindow(self, list(self.data['cats']), [r.cats for r in recs],
                                          self.category_groups, self.groups_file)
        chosen = window.show()
        if not chosen:
            return
        ticked, cleared = chosen
        for rec in recs:
            self.set_cats(rec, core.apply_category_choice(rec.cats, ticked, cleared))

    def set_cats(self, rec, cats):
        rec.cats = set(cats)
        self.quiet(self.rows[rec.rid], 'cats', core.join_categories(rec.cats))
        self.mark(rec)

    # ---- apply

    def set_progress(self, done, total):
        percent = int(100.0 * done / max(1, total))
        self.e('ProgBar').Value = percent
        self.e('ProgText').Text = u'Completed {0}%'.format(percent)

    def set_busy(self, flag):
        self.busy = flag
        self.e('Content').IsEnabled = not flag
        self.e('ApplyBtn').IsEnabled = not flag
        self.e('NextBtn').IsEnabled = not flag
        self.e('PrevBtn').IsEnabled = not flag

    def say(self, text):
        self.e('StatusText').Text = text

    def on_stuck(self):
        self.set_busy(False)
        self.say(u'Revit is busy: finish what is open in Revit and the change will run')

    def on_apply(self, sender, args):
        if self.busy:
            return
        errors = core.validate_plan(self.recs)
        if errors:
            tell(self, u'Before Apply', u'\n'.join(errors[:60]))
            return
        plan = core.build_plan(self.recs)
        if not ask(self, u'Apply', u'\n'.join(core.plan_lines(plan)), u'Apply'):
            return
        self.set_busy(True)
        self.set_progress(0, 1)
        doc = self.doc
        data = self.data

        def job(uiapp):
            return pm_revit.apply_plan(doc, plan, data, self.set_progress)

        if not self.runner.submit(job, self.after_apply):
            self.set_busy(False)
            self.say(u'Revit refused the request, try again')

    def after_apply(self, result):
        self.set_busy(False)
        core.log(u'Apply: {0}'.format(result), self.settings)
        self.reload()
        failed = result['failed']
        if failed:
            tell(self, u'Apply', u'{0} change(s) landed.\n\n{1}'.format(result['landed'], u'\n'.join(
                u'{0}: {1}'.format(name, reason) for name, reason in failed[:60])))
        self.set_progress(1, 1)
        self.say(u'{0} change(s) applied. {1}'.format(result['landed'], core.status_line(self.recs)))

    # ---- tabs

    def on_tab(self, sender, args):
        panels = (('TabParams', 'PanelParams'), ('TabCats', 'PanelCats'),
                  ('TabTransfer', 'PanelTransfer'), ('TabFamilies', 'PanelFamilies'),
                  ('TabShared', 'PanelShared'))
        for tab, panel in panels:
            element = self.e(panel)
            if element is not None:
                on = self.e(tab).IsChecked
                element.Visibility = Visibility.Visible if on else Visibility.Collapsed
        project = bool(self.e('TabParams').IsChecked or self.e('TabCats').IsChecked)
        shared = bool(self.e('TabShared').IsChecked)
        self.show(self.e('ApplyBtn'), project)
        self.show(self.e('NextBtn'), bool(self.e('TabParams').IsChecked))
        self.show(self.e('PrevBtn'), bool(self.e('TabCats').IsChecked))
        self.show(self.e('SaveBtn'), shared)
        if shared:
            self.update_sp_status()
        elif project:
            self.update_status()
        else:
            self.say(u'')

    def show(self, element, flag):
        element.Visibility = Visibility.Visible if flag else Visibility.Collapsed

    def on_next(self, sender, args):
        self.e('TabCats').IsChecked = True

    def on_prev(self, sender, args):
        self.e('TabParams').IsChecked = True

    # ---- shared editor

    def on_load_sp(self, sender, args):
        if not self.discard_ok():
            return
        dialog = OpenFileDialog()
        dialog.Filter = 'Shared parameter files (*.txt)|*.txt|All files (*.*)|*.*'
        folder = self.settings.get('last_sp_folder')
        if folder and os.path.isdir(folder):
            dialog.InitialDirectory = folder
        if dialog.ShowDialog():
            self.settings['last_sp_folder'] = os.path.dirname(dialog.FileName)
            self.load_sp(dialog.FileName)

    def discard_ok(self):
        if self.sp is None or not self.sp.is_dirty():
            return True
        return ask(self, u'Shared Editor', u'Discard the edits that have not been saved?', u'Discard')

    def load_sp(self, path):
        try:
            with open(path, 'rb') as src:
                sp = spfile.parse_bytes(src.read())
        except Exception as error:
            tell(self, u'Load SP File', u'Could not read the file.\n\n{0}'.format(error))
            return
        if not sp.cols:
            tell(self, u'Load SP File', u'That is not a shared parameter file: no *PARAM line.')
            return
        sp.path = path
        self.set_sp(sp)

    def set_sp(self, sp):
        self.sp = sp
        self.fill_sp_lists()
        self.loading = True
        table = make_table((('rid', Int32), ('tick', Boolean), ('state', String), ('name', String),
                            ('ptype', String), ('group', String), ('desc', String), ('user', String),
                            ('shown', String), ('guid', String), ('hide', String), ('vis', String),
                            ('gkey', Int32)))
        self.sp_rows = {}
        self.sp_cells = {}
        self.next_sp = 0
        self.sp_table = table
        for row in sp.rows:
            self.add_sp_cell(row)
        table.ColumnChanged += self.on_sp_cell
        self.sp_view = table.DefaultView
        self.sp_view.RowFilter = "vis = '1'"
        self.sp_view.Sort = 'gkey ASC'
        self.e('SpGrid').ItemsSource = self.sp_view
        self.loading = False
        self.e('TickAllS').IsChecked = True
        for name in ('GroupsBtn', 'RenameBtn', 'BatchSpBtn'):
            self.e(name).IsEnabled = True
        self.e('RefreshBtn').IsEnabled = bool(sp.path)
        self.refilter_sp()
        self.update_sp_status()

    def fill_sp_lists(self):
        tokens = [token for token, _label in spfile.SP_TYPES]
        labels = [spfile.type_label(t) for t in tokens]
        for row in self.sp.rows:
            if row.dtype not in tokens:
                tokens.append(row.dtype)
                labels.append(spfile.type_label(row.dtype))
        self.win.Resources['SpTypeItems'] = string_list(labels)
        self.win.Resources['SpGroupItems'] = string_list(
            sorted(g.name for g in self.sp.groups))

    def add_sp_cell(self, row):
        rid = self.next_sp
        self.next_sp += 1
        cell = self.sp_table.NewRow()
        cell['rid'] = rid
        cell['gkey'] = rid
        cell['vis'] = u'1'
        self.fill_sp_cell(cell, row)
        self.sp_table.Rows.Add(cell)
        self.sp_rows[rid] = row
        self.sp_cells[rid] = cell
        return cell

    def fill_sp_cell(self, cell, row):
        cell['tick'] = row.tick
        cell['state'] = row.state()
        cell['name'] = row.name
        cell['ptype'] = spfile.type_label(row.dtype)
        cell['group'] = self.sp.group_name(row.group_id)
        cell['desc'] = row.desc
        cell['user'] = yes_no(row.user)
        cell['shown'] = yes_no(row.visible)
        cell['guid'] = row.guid
        cell['hide'] = yes_no(row.hide)

    def on_sp_cell(self, sender, args):
        if self.loading:
            return
        name = args.Column.ColumnName
        row = self.sp_rows.get(int(args.Row['rid']))
        if row is None:
            return
        if name == 'tick':
            row.tick = bool(args.Row['tick'])
            return
        if name not in S_EDIT:
            return
        value = core.to_text(args.Row[name])
        if not value and name not in ('name', 'desc'):
            self.loading = True
            self.fill_sp_cell(args.Row, row)
            self.loading = False
            return
        if name == 'name':
            row.name = value
        elif name == 'desc':
            row.desc = value
        elif name == 'ptype':
            row.dtype = spfile.type_token(value)
        elif name == 'group':
            row.group_id = self.sp.group_id(value)
        elif name == 'user':
            row.user = flag_of(value)
        elif name == 'shown':
            row.visible = flag_of(value)
        elif name == 'hide':
            row.hide = flag_of(value)
        self.sp_mark(args.Row, row)

    def sp_mark(self, cell, row):
        self.quiet(cell, 'state', row.state())
        self.update_sp_status()

    def update_sp_status(self):
        if self.sp is None:
            self.say(u'Load a shared parameter file, or press Add Parameter to start a new one')
            self.e('SaveBtn').IsEnabled = False
            return
        text = u'File contains {0} Shared Parameters'.format(len(self.sp.live_rows()))
        dirty = self.sp.is_dirty()
        self.say(text + (u' | edits not saved' if dirty else u''))
        self.e('SaveBtn').IsEnabled = dirty

    def refilter_sp(self):
        if self.sp is None:
            return
        search = self.e('SearchS').Text
        self.loading = True
        try:
            for rid in self.sp_rows:
                row = self.sp_rows[rid]
                flag = u'1' if core.words_match(search, [
                    row.name, spfile.type_label(row.dtype), self.sp.group_name(row.group_id),
                    row.desc, row.guid]) else u'0'
                set_cell(self.sp_cells[rid], 'vis', flag)
        finally:
            self.loading = False

    def on_tick_all_sp(self, sender, args):
        value = bool(sender.IsChecked)
        for rid in self.sp_rows:
            if core.to_text(self.sp_cells[rid]['vis']) == u'1':
                self.sp_cells[rid]['tick'] = value

    def sp_ticked(self):
        return [rid for rid in sorted(self.sp_rows)
                if self.sp_rows[rid].tick and core.to_text(self.sp_cells[rid]['vis']) == u'1']

    def on_sort_shared(self, sender, args):
        args.Handled = True
        if self.sp is None:
            return
        field = args.Column.SortMemberPath
        descending = self.next_sort(args.Column)
        rids = sorted(self.sp_rows)
        cells = [self.sp_cells[r] for r in rids]
        ranks = core.sort_ranks(cells, lambda c: c[field], descending,
                                lambda c: core.to_text(c['state']) == u'new')
        self.loading = True
        try:
            for index, cell in enumerate(cells):
                set_cell(cell, 'gkey', ranks[index])
        finally:
            self.loading = False

    def scroll_sp_bottom(self):
        grid = self.e('SpGrid')
        self.win.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(
            lambda: grid.ScrollIntoView(grid.Items[grid.Items.Count - 1]) if grid.Items.Count else None))

    def append_sp(self, row):
        self.loading = True
        try:
            cell = self.add_sp_cell(row)
            cell['gkey'] = len(self.sp_rows) + 100000
        finally:
            self.loading = False
        self.update_sp_status()
        self.scroll_sp_bottom()

    def on_add_sp(self, sender, args):
        if self.sp is None:
            self.set_sp(spfile.blank())
        if not self.sp.groups:
            self.sp.add_group(u'General')
            self.fill_sp_lists()
        name = core.next_free_name([r.name for r in self.sp.live_rows()])
        self.append_sp(spfile.add_row(self.sp, name, self.sp.groups[0].gid))

    def on_groups(self, sender, args):
        dialogs.GroupsWindow(self, self.sp).show()
        self.fill_sp_lists()
        self.loading = True
        try:
            for rid in self.sp_rows:
                set_cell(self.sp_cells[rid], 'group', self.sp.group_name(self.sp_rows[rid].group_id))
                set_cell(self.sp_cells[rid], 'state', self.sp_rows[rid].state())
        finally:
            self.loading = False
        self.update_sp_status()

    def on_rename(self, sender, args):
        rids = self.sp_ticked()
        if not rids:
            self.say(u'Tick some parameters first')
            return
        chosen = dialogs.RenameWindow(self, [self.sp_rows[r].name for r in rids]).show()
        if chosen:
            find, replace, prefix, suffix = chosen
            for rid in rids:
                new = core.rename_preview(self.sp_rows[rid].name, find, replace, prefix, suffix)
                set_cell(self.sp_cells[rid], 'name', new)

    def on_refresh(self, sender, args):
        if self.discard_ok() and self.sp is not None and self.sp.path:
            self.load_sp(self.sp.path)

    def on_batch_sp(self, sender, args):
        menu = self.new_menu()
        self.menu_item(menu, u'Set Group', self.on_sp_set_group)
        self.menu_item(menu, u'Set User Modifiable', self.on_sp_set_user)
        self.menu_item(menu, u'Set Visibility', self.on_sp_set_shown)
        self.menu_item(menu, u'Set Hide When No Value', self.on_sp_set_hide)
        self.menu_item(menu, u'Duplicate', self.on_sp_batch_duplicate)
        self.menu_item(menu, u'New Guid', self.on_sp_batch_guid)
        self.menu_item(menu, u'Delete', self.on_sp_batch_delete)
        self.open_menu(menu, sender)

    def sp_set(self, column, title, choices):
        rids = self.sp_ticked()
        if not rids:
            self.say(u'Tick some parameters first')
            return
        value = ask_choice(self, title, u'Set {0} parameter(s) to:'.format(len(rids)), choices)
        if value:
            for rid in rids:
                set_cell(self.sp_cells[rid], column, value)

    def on_sp_set_group(self, sender, args):
        self.sp_set('group', u'Group', sorted(g.name for g in self.sp.groups))

    def on_sp_set_user(self, sender, args):
        self.sp_set('user', u'User Modifiable', YES_NO)

    def on_sp_set_shown(self, sender, args):
        self.sp_set('shown', u'Visibility', YES_NO)

    def on_sp_set_hide(self, sender, args):
        self.sp_set('hide', u'Hide When No Value', YES_NO)

    def on_sp_batch_duplicate(self, sender, args):
        self.sp_duplicate(self.sp_ticked())

    def on_sp_batch_guid(self, sender, args):
        self.sp_new_guid(self.sp_ticked())

    def on_sp_batch_delete(self, sender, args):
        self.sp_delete(self.sp_ticked())

    def sp_duplicate(self, rids):
        for rid in rids:
            self.append_sp(spfile.duplicate(self.sp, self.sp_rows[rid]))

    def sp_new_guid(self, rids):
        for rid in rids:
            row = self.sp_rows[rid]
            row.guid = spfile.new_guid()
            self.quiet(self.sp_cells[rid], 'guid', row.guid)
            self.sp_mark(self.sp_cells[rid], row)

    def sp_delete(self, rids):
        for rid in rids:
            row = self.sp_rows[rid]
            if row.item is None:
                self.sp.rows.remove(row)
                self.loading = True
                try:
                    self.sp_table.Rows.Remove(self.sp_cells.pop(rid))
                finally:
                    self.loading = False
                del self.sp_rows[rid]
            else:
                row.deleted = True
                self.sp_mark(self.sp_cells[rid], row)
        self.update_sp_status()

    def sp_restore(self, rids):
        for rid in rids:
            self.sp_rows[rid].deleted = False
            self.sp_mark(self.sp_cells[rid], self.sp_rows[rid])

    def on_sp_right_click(self, sender, args):
        """Handled on the button coming up, which is when Windows opens a context menu."""
        node = args.OriginalSource
        row = None
        while node is not None:
            if isinstance(node, DataGridRow):
                row = node
                break
            try:
                node = VisualTreeHelper.GetParent(node)
            except Exception:
                node = None
        if row is None or self.sp is None:
            return
        args.Handled = True
        rid = int(row.Item['rid'])
        grid = self.e('SpGrid')
        rids = [rid]
        if row.IsSelected and grid.SelectedItems.Count > 1:
            rids = [int(item['rid']) for item in grid.SelectedItems]
        self.sp_menu_rids = rids
        menu = self.new_menu()
        self.menu_item(menu, u'Duplicate Parameter', self.on_menu_duplicate,
                       self.icon('M0,4 H9 V13 H0 Z M4,4 V0 H13 V9 H9', 'Text'))
        if self.sp_rows[rid].deleted:
            self.menu_item(menu, u'Restore Parameter', self.on_menu_restore,
                           self.icon('M2,7 L6,11 L13,2', 'Green'))
        else:
            self.menu_item(menu, u'Delete Parameter', self.on_menu_delete,
                           self.icon('M1,1 L12,12 M12,1 L1,12', 'Red'))
        self.menu_item(menu, u'New Guid', self.on_menu_guid,
                       self.icon('M6.5,0 A6.5,6.5 0 1 0 6.5,13 A6.5,6.5 0 1 0 6.5,0 M4,4 V9 M7,4 V9 H8 A2.5,2.5 0 0 0 8,4 Z', 'Text'))
        menu.Placement = PlacementMode.MousePoint
        menu.IsOpen = True

    def on_menu_duplicate(self, sender, args):
        self.sp_duplicate(self.sp_menu_rids)

    def on_menu_delete(self, sender, args):
        self.sp_delete(self.sp_menu_rids)

    def on_menu_restore(self, sender, args):
        self.sp_restore(self.sp_menu_rids)

    def on_menu_guid(self, sender, args):
        self.sp_new_guid(self.sp_menu_rids)

    def on_save(self, sender, args):
        """Nothing reaches a file until here. The file is rebuilt as it came in, plus the edits."""
        self.e('SaveBtn').Focus()
        errors, warnings = spfile.validate(self.sp, core.name_problem)
        if errors:
            tell(self, u'Before Saving', u'\n'.join(errors[:60]))
            return
        if warnings and not ask(self, u'Save', u'\n'.join(warnings[:60]), u'Continue'):
            return
        dialog = SaveFileDialog()
        dialog.Filter = 'Shared parameter files (*.txt)|*.txt|All files (*.*)|*.*'
        dialog.OverwritePrompt = True
        if self.sp.path:
            dialog.InitialDirectory = os.path.dirname(self.sp.path)
            dialog.FileName = os.path.basename(self.sp.path)
        else:
            dialog.FileName = 'Shared Parameters.txt'
        if not dialog.ShowDialog():
            return
        path = dialog.FileName
        try:
            data = spfile.to_bytes(self.sp)
            check = spfile.parse_bytes(data)
            if len(check.rows) != len(self.sp.live_rows()):
                raise ValueError(u'the rebuilt file does not read back with the same parameters')
            if os.path.isfile(path):
                with open(path, 'rb') as src:
                    old = src.read()
                with open(path + '.bak', 'wb') as out:
                    out.write(old)
            with open(path, 'wb') as out:
                out.write(data)
        except Exception as error:
            tell(self, u'Save', u'Could not write the file. Your edits are still here.\n\n{0}'.format(error))
            return
        self.load_sp(path)
        self.say(u'Saved {0}. File contains {1} Shared Parameters'.format(
            path, len(self.sp.live_rows())))

    # ---- closing

    def escape_closes(self):
        return False

    def on_closing(self, sender, args):
        waiting = core.build_plan(self.recs)
        count = len(waiting['create']) + len(waiting['modify']) + len(waiting['delete'])
        unsaved = self.sp is not None and self.sp.is_dirty()
        if count or unsaved:
            text = u'Close without applying or saving your edits?'
            if self.drawer.parked:
                self.drawer.open()
            if not ask(self, u'ParaManager', text, u'Close'):
                args.Cancel = True
                return
        if not self.drawer.parked and self.full_saved is None:
            self.settings['width'] = str(int(self.win.ActualWidth))
            self.settings['height'] = str(int(self.win.ActualHeight))
        core.save_settings(core.settings_path(), self.settings)
        HOLD.clear()

    def on_debug(self, sender, args):
        self.settings['debug'] = '1' if self.e('DebugTick').IsChecked else '0'
        core.save_settings(core.settings_path(), self.settings)

    def on_first_move(self, sender, args):
        """Proof this engine is alive. See launch()."""
        if self.proved or not HOLD.get('shown'):
            return
        self.proved = True
        self.settings['open_note'] = ''
        core.save_settings(core.settings_path(), self.settings)


def launch(uiapp, here):
    settings = core.load_settings(core.settings_path())
    old = HOLD.get('window')
    if old is not None:
        try:
            old.win.Activate()
            return
        except Exception:
            HOLD.clear()
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None or uidoc.Document.IsFamilyDocument:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('ParaManager', 'Open a project first. Project parameters do not exist in a family.')
        return
    modal = False
    if settings.get('open_note'):
        from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogResult
        modal = TaskDialog.Show(
            'ParaManager', 'Last time the window opened but did not respond. Open it modal '
            'this time? Revit stays locked while it is open, and Apply will not run until it '
            'closes.', TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No) == TaskDialogResult.Yes
    window = MainWindow(uiapp, settings)
    WindowInteropHelper(window.win).Owner = uiapp.MainWindowHandle
    HOLD['window'] = window
    from pm_version import __version__
    settings['open_note'] = __version__
    core.save_settings(core.settings_path(), settings)
    window.update_status()
    if modal:
        window.win.ShowDialog()
        return
    window.win.Show()
    HOLD['shown'] = True
