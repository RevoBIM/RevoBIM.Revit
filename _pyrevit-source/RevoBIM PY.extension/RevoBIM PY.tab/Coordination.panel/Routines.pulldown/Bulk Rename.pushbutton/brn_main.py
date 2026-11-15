# -*- coding: utf-8 -*-
"""The Bulk Rename window: tools on the left, the selected items on the right."""
import brn_clr  # noqa: F401  must stay first
import brn_core as core
import brn_dialogs
import brn_revit
from brn_chrome import ThemedWindow

from System import Action, AppDomain, Double, TimeSpan
from System.Windows import (
    FontWeights, FrameworkElement, GridLength, GridUnitType, Size,
    SizeToContent, SystemParameters, TextTrimming, TextWrapping, Thickness, VerticalAlignment,
    Visibility,
)
from System.Windows.Controls import Border, ColumnDefinition, Grid, TextBlock
from System.Windows.Documents import Run, TextElement
from System.Windows.Threading import DispatcherTimer

ROW_HEIGHT = 26.0
LIST_MAX_WIDTH = 640.0
WATCHDOG_SECONDS = 20
APP_KEY = 'RevoBIM.BulkRename.window.' + core.__version__


class RowView(object):
    """One line of the list. Only redrawn when its text or state moved."""

    def __init__(self, row):
        self.row = row
        self.signature = None
        self.border = Border()
        self.border.Height = ROW_HEIGHT
        self.border.Padding = Thickness(8, 0, 8, 0)
        grid = Grid()
        main = ColumnDefinition()
        main.Width = GridLength(1, GridUnitType.Star)
        grid.ColumnDefinitions.Add(main)
        side = ColumnDefinition()
        side.Width = GridLength(1, GridUnitType.Auto)
        grid.ColumnDefinitions.Add(side)
        self.text = TextBlock()
        self.text.VerticalAlignment = VerticalAlignment.Center
        self.text.TextTrimming = TextTrimming.CharacterEllipsis
        self.text.TextWrapping = TextWrapping.NoWrap
        self.context = TextBlock()
        self.context.VerticalAlignment = VerticalAlignment.Center
        self.context.Margin = Thickness(14, 0, 0, 0)
        self.context.FontSize = 11
        self.context.SetResourceReference(TextBlock.ForegroundProperty, 'Muted')
        Grid.SetColumn(self.context, 1)
        grid.Children.Add(self.text)
        grid.Children.Add(self.context)
        self.border.Child = grid

    def show(self, item, context):
        signature = (item.new, item.state, item.old, context)
        if signature == self.signature:
            return
        self.signature = signature
        self.context.Text = context
        inlines = self.text.Inlines
        inlines.Clear()
        if item.state == core.CHANGE:
            self.text.SetResourceReference(TextBlock.ForegroundProperty, 'Text')
            for piece, changed in item.segments:
                run = Run(piece)
                if changed:
                    run.SetResourceReference(TextElement.ForegroundProperty, 'Orange')
                    run.FontWeight = FontWeights.SemiBold
                inlines.Add(run)
            self.border.ToolTip = u'Was: {0}'.format(item.old)
        elif item.state in (core.CLASH, core.BAD):
            self.text.SetResourceReference(TextBlock.ForegroundProperty, 'Red')
            inlines.Add(Run(item.new or item.old))
            self.border.ToolTip = u'{0} - left alone. Now: {1}'.format(item.reason, item.old)
        else:
            self.text.SetResourceReference(TextBlock.ForegroundProperty, 'Text')
            inlines.Add(Run(item.old))
            self.border.ToolTip = item.old


class BulkRenameWindow(ThemedWindow):
    LAYOUT = 'BulkRename.xaml'

    def __init__(self, uiapp, settings, log, doc, rows, taken, left_out, runner,
                 parameters):
        ThemedWindow.__init__(self, uiapp, settings, log)
        self.doc = doc
        self.rows = rows
        self.taken = taken
        self.left_out = left_out
        self.runner = runner
        self.busy = False
        self.loading = False
        self.field = core.FIELD_NAME
        self.rules = {core.FIELD_NAME: core.Rules(), core.FIELD_NUMBER: core.Rules()}
        self.items = []
        self.has_sheets = any([r.has(core.FIELD_NUMBER) for r in rows])
        self.mixed = len(set([r.kind for r in rows])) > 1
        self.views = {}
        self.watchdog = None
        find = self.window.FindName
        self.find_box = find('FindBox')
        self.replace_box = find('ReplaceBox')
        self.case_box = find('CaseBox')
        self.prefix_box = find('PrefixBox')
        self.suffix_box = find('SuffixBox')
        self.list_host = find('ListHost')
        self.list_scroller = find('ListScroller')
        self.list_heading = find('ListHeading')
        self.status = find('StatusText')
        self.apply_btn = find('ApplyBtn')
        self.apply_text = find('ApplyText')
        self.clear_btn = find('ClearBtn')
        self.tab_name = find('TabName')
        self.tab_number = find('TabNumber')
        self.tab_name_text = find('TabNameText')
        self.tab_number_text = find('TabNumberText')
        self.debug_box = find('DebugBox')
        self.debug_box.IsChecked = settings.get('debug', '1') == '1'
        self.write_btn = find('WriteBtn')
        self.settings_btn = find('SettingsBtn')
        self.parameters = parameters
        self.write_btn.Visibility = (Visibility.Visible if self.has_sheets
                                     else Visibility.Collapsed)
        find('TabBar').Visibility = (Visibility.Visible if self.has_sheets
                                     else Visibility.Collapsed)
        self.build_list()
        self.fit()
        self.wire_tools()
        self.own_to_revit()
        self.refresh()

    # ---------- layout ----------
    def fit(self):
        """The window sizes itself to the list. Once drawn it goes back to a
        normal window, so typing cannot make it jump and the grips work."""
        self.list_scroller.MaxHeight = SystemParameters.WorkArea.Height * 0.75
        self.list_scroller.MaxWidth = LIST_MAX_WIDTH
        self.window.ContentRendered += self.safe(self.on_rendered)

    def on_rendered(self, sender, args):
        window = self.window
        width, height = window.ActualWidth, window.ActualHeight
        window.SizeToContent = SizeToContent.Manual
        window.Width, window.Height = width, height
        self.list_scroller.ClearValue(FrameworkElement.MaxHeightProperty)
        self.list_scroller.ClearValue(FrameworkElement.MaxWidthProperty)
        window.MinHeight = min(height, 300.0)
        self.find_box.Focus()

    def build_list(self):
        for row in self.rows:
            self.views[row.key] = RowView(row)

    def show_field(self):
        self.list_host.Children.Clear()
        for row in self.rows:
            if row.has(self.field):
                self.list_host.Children.Add(self.views[row.key].border)
        count = self.list_host.Children.Count
        text = core.plural(count, u'item') + u' selected'
        if self.left_out:
            text += u', {0} cannot be renamed here'.format(self.left_out)
        self.list_heading.Text = text

    # ---------- tools ----------
    def wire_tools(self):
        safe = self.safe
        for box in (self.find_box, self.replace_box, self.prefix_box, self.suffix_box):
            box.TextChanged += safe(self.on_rule_changed)
        self.case_box.Click += safe(self.on_rule_changed)
        self.tab_name.Checked += safe(lambda s, a: self.set_field(core.FIELD_NAME))
        self.tab_number.Checked += safe(lambda s, a: self.set_field(core.FIELD_NUMBER))
        self.apply_btn.Click += safe(self.on_apply)
        self.clear_btn.Click += safe(self.on_clear)
        self.write_btn.Click += safe(self.on_write)
        self.settings_btn.Click += safe(self.on_settings)
        self.debug_box.Click += safe(self.on_debug)
        self.show_field()

    def on_debug(self, sender, args):
        on = self.debug_box.IsChecked == True  # noqa: E712  nullable bool
        self.log.enabled = on
        self.settings['debug'] = '1' if on else '0'
        core.save_settings(self.settings)

    def on_rule_changed(self, sender, args):
        if self.loading:
            return
        rules = self.rules[self.field]
        rules.find = core.to_text(self.find_box.Text)
        rules.replace = core.to_text(self.replace_box.Text)
        rules.case = self.case_box.IsChecked == True  # noqa: E712
        rules.prefix = core.to_text(self.prefix_box.Text)
        rules.suffix = core.to_text(self.suffix_box.Text)
        self.refresh()

    def load_tools(self):
        rules = self.rules[self.field]
        self.loading = True
        try:
            self.find_box.Text = rules.find
            self.replace_box.Text = rules.replace
            self.case_box.IsChecked = rules.case
            self.prefix_box.Text = rules.prefix
            self.suffix_box.Text = rules.suffix
        finally:
            self.loading = False

    def set_field(self, field):
        if field == self.field:
            return
        self.field = field
        self.load_tools()
        self.show_field()
        self.refresh()
        self.widen_to_fit()

    def text_width(self, text, size, weight=None):
        if not text:
            return 0.0
        probe = TextBlock()
        probe.FontFamily = self.window.FontFamily
        probe.FontSize = size
        if weight is not None:
            probe.FontWeight = weight
        probe.Text = text
        probe.Measure(Size(Double.PositiveInfinity, Double.PositiveInfinity))
        return probe.DesiredSize.Width

    def widen_to_fit(self):
        """Measured on a loose TextBlock, so the rows' own layout is untouched.
        Only ever grows: the width stays for the next tab."""
        pairs = []
        for item in self.items:
            if item.field == self.field:
                pairs.append((self.text_width(item.final(), self.window.FontSize,
                                              FontWeights.SemiBold),
                              self.text_width(self.context_for(item), 11)))
        window = self.window
        extra = core.list_width(pairs) - self.list_scroller.ActualWidth
        area = self.work_area()
        left, width = core.widened(window.Left, window.ActualWidth, extra,
                                   area[0], area[2])
        if width != window.ActualWidth:
            self.full_bounds = None
            window.Left, window.Width = left, width
            self.log(u'widened to {0}'.format(width))

    def on_clear(self, sender, args):
        self.rules = {core.FIELD_NAME: core.Rules(), core.FIELD_NUMBER: core.Rules()}
        self.load_tools()
        self.refresh()

    # ---------- preview ----------
    def refresh(self):
        self.items = core.evaluate(self.rows, self.rules, self.taken)
        for item in self.items:
            if item.field == self.field:
                self.views[item.row.key].show(item, self.context_for(item))
        self.status.Text = core.status_line(self.items)
        count = len(core.changes(self.items))
        self.apply_text.Text = u'Apply ({0})'.format(count) if count else u'Apply'
        self.apply_btn.IsEnabled = count > 0 and not self.busy
        self.clear_btn.IsEnabled = not all([r.empty() for r in self.rules.values()])
        if self.has_sheets:
            self.tab_name_text.Text = self.tab_label(u'Sheet Name', core.FIELD_NAME)
            self.tab_number_text.Text = self.tab_label(u'Sheet Number', core.FIELD_NUMBER)

    def tab_label(self, title, field):
        count = len([i for i in core.changes(self.items) if i.field == field])
        return u'{0} ({1})'.format(title, count) if count else title

    def context_for(self, item):
        row = item.row
        if row.has(core.FIELD_NUMBER):
            other = core.FIELD_NUMBER if item.field == core.FIELD_NAME else core.FIELD_NAME
            return row.values[other]
        return row.kind if self.mixed else u''

    # ---------- apply ----------
    def on_apply(self, sender, args):
        if self.busy or not core.changes(self.items):
            return
        self.set_busy(True)
        self.status.Text = u'Renaming...'
        if self.runner.submit(self.job, self.on_refused):
            self.start_watchdog()

    def set_busy(self, busy):
        self.busy = busy
        self.apply_btn.IsEnabled = not busy and bool(core.changes(self.items))
        self.write_btn.IsEnabled = not busy

    # ---------- write sheet names ----------
    def on_settings(self, sender, args):
        if self.busy:
            return
        sheets = [r for r in self.rows if r.has(core.FIELD_NUMBER)]
        sample = sheets[0].values[core.FIELD_NAME] if sheets else u'NAME_ONE_TWO'
        brn_dialogs.SettingsWindow(self.uiapp, self.settings, self.log, self,
                                   self.parameters, sample).run()

    def on_write(self, sender, args):
        if self.busy:
            return
        if not core.sheet_writes(u'x', self.settings):
            self.on_settings(None, None)
            return
        waiting = len(core.changes(self.items))
        if waiting:
            go = brn_dialogs.ask(
                self.uiapp, self.settings, self.log,
                u'Apply the {0} first, then write the sheet names?'.format(
                    core.plural(waiting, u'change')),
                u'Apply and write', u'Cancel', owner=self)
            if not go:
                return
        self.set_busy(True)
        self.status.Text = u'Writing sheet names...'
        rename = bool(waiting)
        if self.runner.submit(lambda: self.write_job(rename), self.on_refused):
            self.start_watchdog()

    def write_job(self, rename):
        """Runs inside Revit's API context."""
        if not self.doc.IsValidObject:
            report = brn_revit.Report()
            report.failed.append((None, u'That model is no longer open'))
        else:
            report = brn_revit.rename_and_write(self.doc, self.rows, self.rules,
                                                self.settings, rename, self.log)
        self.window.Dispatcher.BeginInvoke(Action(lambda: self.after_write(report, rename)))

    def after_write(self, report, rename):
        try:
            self.stop_watchdog()
            self.set_busy(False)
            self.log(u'wrote {0}, failed {1}'.format(report.written, len(report.failed)))
            if report.taken is not None:
                self.taken = report.taken
            if rename:
                self.on_clear(None, None)
            self.status.Text = u'Sheet names written on {0}'.format(
                core.plural(report.written, u'sheet'))
            if report.failed:
                self.show_failed(report, u'{0} written, {1} not.'.format(
                    report.written, len(report.failed)))
        except Exception as error:
            self.log(u'after_write: {0}'.format(error))

    def show_failed(self, report, message):
        lines = []
        for row, reason in report.failed:
            name = row.values[core.FIELD_NAME] if row is not None else u'Sheet names'
            lines.append(u'{0}: {1}'.format(name, reason))
        brn_dialogs.tell(self.uiapp, self.settings, self.log, message,
                         title=u'Some not done', detail=u'\n'.join(lines), owner=self)

    def on_refused(self, answer):
        self.set_busy(False)
        self.status.Text = u'Revit would not take the rename ({0}). Try again.'.format(answer)

    def start_watchdog(self):
        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromSeconds(WATCHDOG_SECONDS)
        timer.Tick += self.safe(self.on_watchdog)
        timer.Start()
        self.watchdog = timer

    def stop_watchdog(self):
        if self.watchdog is not None:
            self.watchdog.Stop()
            self.watchdog = None

    def on_watchdog(self, sender, args):
        self.stop_watchdog()
        self.log(u'watchdog: Revit has not picked up the job')
        self.set_busy(False)
        self.status.Text = u'Revit is busy. The rename runs when it is free.'

    def job(self):
        """Runs inside Revit's API context."""
        if not self.doc.IsValidObject:
            report = brn_revit.Report()
            report.failed.append((None, u'That model is no longer open'))
        else:
            report = brn_revit.apply_job(self.doc, self.rows, self.rules, self.log)
        self.window.Dispatcher.BeginInvoke(Action(lambda: self.after_apply(report)))

    def after_apply(self, report):
        try:
            self.stop_watchdog()
            self.set_busy(False)
            self.log(u'applied {0}, failed {1}'.format(report.done, len(report.failed)))
            if not report.failed:
                self.force_close()
                return
            if report.taken is not None:
                self.taken = report.taken
            self.on_clear(None, None)
            count = len(report.failed)
            self.status.Text = u'{0} renamed, {1} not'.format(report.done, count)
            self.show_failed(report, u'{0} renamed, {1} left as it was.'.format(report.done, count))
        except Exception as error:
            self.log(u'after_apply: {0}'.format(error))

    # ---------- lifetime ----------
    def request_close(self):
        if self.busy:
            return
        if core.changes(self.items):
            leave = brn_dialogs.ask(
                self.uiapp, self.settings, self.log,
                u'Close without applying these changes?', u'Close', u'Keep editing',
                owner=self)
            if not leave:
                return
        self.window.Close()

    def force_close(self):
        self.window.Close()

    def on_closed(self):
        ThemedWindow.on_closed(self)
        self.stop_watchdog()
        core.save_settings(self.settings)
        try:
            AppDomain.CurrentDomain.SetData(APP_KEY, None)
        except Exception:
            pass
