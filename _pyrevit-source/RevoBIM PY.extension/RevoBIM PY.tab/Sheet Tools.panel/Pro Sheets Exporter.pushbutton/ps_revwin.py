# -*- coding: utf-8 -*-
"""The Revision Manager window: a view of a ps_revisions.Staging.

Opened from the Document Register's Revision Manager button. Modal: it
stages, and on Apply hands back a plan for the register to write through
the external event, then closes - which is "back to the register".

The grid is a DataTable like every other grid in the tool. Each cell's look
comes from flags on its row rather than from anything set on a container:
``c_<field>`` is 1 when that field is staged to change (green), ``live`` is 0
when the row is staged to be deleted or merged (red, struck through). Rows
are recycled as they scroll, so anything set on a container would wander.
"""

import ps_refs  # noqa: F401  - must be first

from System import Action, Boolean, Object, String, Tuple
from System.Collections.Generic import List
from System.Data import DataTable
from System.Windows import (CornerRadius, FontWeights, GridLength,
                            HorizontalAlignment,
                            Thickness, TextTrimming, TextWrapping,
                            VerticalAlignment, Visibility)
from System.Windows.Controls import (Border, Button, Canvas, CheckBox,
                                     ContextMenu, MenuItem, Separator,
                                     ColumnDefinition, DataGridCell,
                                     DataGridCellInfo, DataGridLength,
                                     DataGridLengthUnitType,
                                     DataGridRow, DataGridTemplateColumn,
                                     Grid, ListBox,
                                     ListBoxItem, Orientation, RadioButton,
                                     ScrollViewer, SelectionMode,
                                     StackPanel, TextBlock, TextBox)
from System.Windows.Controls.Primitives import PlacementMode, Popup
from System.Windows.Input import Key
from System.Windows.Markup import XamlReader
from System.Windows.Media import VisualTreeHelper
from System.Windows.Threading import DispatcherPriority

from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler

import ps_config
import ps_register
import ps_revaddwin
import ps_revcolwin
import ps_revdata
import ps_revisions
import ps_revsetwin
import ps_ui
import theme


PRESENTATION = 'http://schemas.microsoft.com/winfx/2006/xaml/presentation'

# The green + that adds a column, and the pencil on an extra column's heading.
PLUS_ICON = (
    u'<Path xmlns="{0}" Width="14" Height="14" Stretch="Uniform"'
    u' Fill="{{DynamicResource GreenBrush}}"'
    u' Data="M 5,0 L 7,0 L 7,5 L 12,5 L 12,7 L 7,7 L 7,12 L 5,12 L 5,7 L 0,7'
    u' L 0,5 L 5,5 Z"/>')
PENCIL_ICON = (
    u'<Path xmlns="{0}" Width="10" Height="10" Stretch="Uniform"'
    u' Fill="{{DynamicResource MutedBrush}}"'
    u' Data="M 8,0 L 11,3 L 3.5,10.5 L 0,11 L 0.5,7.5 Z"/>')

# A column that fits itself to its heading and its widest value.
AUTO = -1

# How narrow an auto column may get - the search box and its list button
# have to stay usable - and how wide, so one long value cannot push the
# rest off the right of the window.
AUTO_MIN = 78
AUTO_MAX = 300

# field, heading, width (AUTO = fit the text, 0 = take the rest), kind.
# Sheet series is the one fixed width: its chips wrap to the column, and a
# column that fits itself to its content has no edge for them to wrap at,
# so it would grow into one long line instead (see SERIES_TEMPLATE).
COLUMNS = [
    ('seq', u'Sequence', AUTO, 'read'),
    ('numbering', u'Numbering', AUTO, 'RevNumberingChoices'),
    ('date', u'Date', AUTO, 'text'),
    ('desc', u'Description', 0, 'text'),
    ('issued', u'Issued', AUTO, 'check'),
    ('issued_to', u'Issued to', AUTO, 'text'),
    ('issued_by', u'Issued by', AUTO, 'text'),
    ('show', u'Show', AUTO, 'RevShowChoices'),
    ('used', u'Used on sheets', AUTO, 'used'),
    ('series', u'Sheet series', 190, 'series'),
    # 1.46.0: clouds drawn in views that are on no sheet - why a revision
    # "on 0 sheets" can still say it is in use.
    ('unplaced', u'Clouds off sheets', AUTO, 'unplaced'),
]

# How many views Find clouds on views opens before asking first.
OPEN_LIMIT = 12

# A cell's text: green and bold while its field is staged to change, red
# and struck through while its row is staged to go.
TEXT_STYLE = (
    u'<TextBlock.Style><Style TargetType="TextBlock">'
    u'<Setter Property="VerticalAlignment" Value="Center"/>'
    u'<Setter Property="Padding" Value="3,1"/>'
    u'<Style.Triggers>'
    u'<DataTrigger Binding="{{Binding c_{0}}}" Value="1">'
    u'<Setter Property="Foreground" Value="{{DynamicResource GreenBrush}}"/>'
    u'<Setter Property="FontWeight" Value="Bold"/>'
    u'<Setter Property="Background" Value="{{DynamicResource GreenWashBrush}}"/>'
    u'</DataTrigger>'
    u'<DataTrigger Binding="{{Binding live}}" Value="0">'
    u'<Setter Property="Foreground" Value="{{DynamicResource RedBrush}}"/>'
    u'<Setter Property="TextDecorations" Value="Strikethrough"/>'
    u'<Setter Property="Background" Value="Transparent"/>'
    u'</DataTrigger>'
    u'</Style.Triggers></Style></TextBlock.Style>')

SHOW_TEMPLATE = (
    u'<DataTemplate xmlns="{0}"><TextBlock Text="{{Binding {1}}}"{2}>'
    u'{3}</TextBlock></DataTemplate>')

# The editors take the keyboard as they open, so one click on a cell is
# enough to start typing - as in Revit's own dialog.
TEXT_EDIT_TEMPLATE = (
    u'<DataTemplate xmlns="{0}" '
    u'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
    u'<Grid FocusManager.FocusedElement="{{Binding ElementName=Editor}}">'
    u'<TextBox x:Name="Editor" Text="{{Binding {1}, Mode=TwoWay}}"'
    u' VerticalContentAlignment="Center"/></Grid></DataTemplate>')

COMBO_EDIT_TEMPLATE = (
    u'<DataTemplate xmlns="{0}" '
    u'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
    u'<Grid FocusManager.FocusedElement="{{Binding ElementName=Editor}}">'
    u'<ComboBox x:Name="Editor" ItemsSource="{{DynamicResource {2}}}"'
    u' SelectedItem="{{Binding {1}, Mode=TwoWay, '
    u'UpdateSourceTrigger=PropertyChanged}}"/></Grid></DataTemplate>')

CHECK_TEMPLATE = (
    u'<DataTemplate xmlns="{0}">'
    u'<Border Padding="2,1" CornerRadius="2"><Border.Style>'
    u'<Style TargetType="Border">'
    u'<Setter Property="Background" Value="Transparent"/>'
    u'<Style.Triggers>'
    u'<DataTrigger Binding="{{Binding c_{1}}}" Value="1">'
    u'<Setter Property="Background" Value="{{DynamicResource GreenWashBrush}}"/>'
    u'<Setter Property="BorderBrush" Value="{{DynamicResource GreenBrush}}"/>'
    u'<Setter Property="BorderThickness" Value="1"/>'
    u'</DataTrigger>'
    # A row staged to go cannot be issued; the Border's IsEnabled carries
    # down to the tick inside it.
    u'<DataTrigger Binding="{{Binding live}}" Value="0">'
    u'<Setter Property="IsEnabled" Value="False"/>'
    u'<Setter Property="Opacity" Value="0.5"/>'
    u'</DataTrigger></Style.Triggers></Style></Border.Style>'
    u'<CheckBox HorizontalAlignment="Center"'
    u' Style="{{DynamicResource GridCheckBox}}"'
    u' IsChecked="{{Binding {1}, Mode=TwoWay, '
    u'UpdateSourceTrigger=PropertyChanged}}"/>'
    u'</Border></DataTemplate>')

# The Sheet series cell. A button with no chrome of its own, ticked into
# the row's series_open: closed it shows the first series and "+2", open it
# shows every series, one coloured chip each, wrapping to the column's
# width. Rows open expanded unless the user has collapsed them (the
# Collapse series button, kept as rev_series_open). All of it is in the
# template - rows are recycled as they scroll, and nothing set on a
# container from code would stay with its row.
SERIES_TEMPLATE = (
    u'<DataTemplate xmlns="{0}">'
    u'<ToggleButton Cursor="Hand" Focusable="False"'
    u' ToolTip="Click to fold or unfold this revision\'s sheet series"'
    u' IsChecked="{{Binding series_open, Mode=TwoWay, '
    u'UpdateSourceTrigger=PropertyChanged}}">'
    u'<ToggleButton.Template><ControlTemplate TargetType="ToggleButton">'
    u'<Border Background="Transparent" Padding="0,2">'
    u'<ContentPresenter/></Border></ControlTemplate>'
    u'</ToggleButton.Template>'
    # A DockPanel rather than a horizontal StackPanel: the chips get the
    # column's width, so the WrapPanel has an edge to wrap at.
    u'<DockPanel LastChildFill="True">'
    u'<TextBlock DockPanel.Dock="Right" Text="{{Binding series_more}}"'
    u' Margin="2,0,0,0" VerticalAlignment="Center" FontWeight="Bold">'
    u'<TextBlock.Style><Style TargetType="TextBlock">'
    u'<Setter Property="Foreground" Value="{{DynamicResource BlueBrush}}"/>'
    u'<Style.Triggers>'
    u'<DataTrigger Binding="{{Binding series_open}}" Value="True">'
    u'<Setter Property="Visibility" Value="Collapsed"/>'
    u'</DataTrigger></Style.Triggers></Style></TextBlock.Style></TextBlock>'
    u'<ItemsControl>'
    u'<ItemsControl.Style><Style TargetType="ItemsControl">'
    u'<Setter Property="ItemsSource" Value="{{Binding series_head}}"/>'
    u'<Style.Triggers>'
    u'<DataTrigger Binding="{{Binding series_open}}" Value="True">'
    u'<Setter Property="ItemsSource" Value="{{Binding series_items}}"/>'
    u'</DataTrigger></Style.Triggers></Style></ItemsControl.Style>'
    u'<ItemsControl.ItemsPanel><ItemsPanelTemplate>'
    u'<WrapPanel Orientation="Horizontal"/>'
    u'</ItemsPanelTemplate></ItemsControl.ItemsPanel>'
    u'<ItemsControl.ItemTemplate><DataTemplate>'
    u'<Border Background="{{Binding Item2}}" BorderBrush="{{Binding Item3}}"'
    u' BorderThickness="1" CornerRadius="3" Padding="6,1" Margin="0,1,4,1">'
    u'<TextBlock Text="{{Binding Item1}}" FontSize="11"'
    u' Foreground="{{DynamicResource TextBrush}}"/></Border>'
    u'</DataTemplate></ItemsControl.ItemTemplate></ItemsControl>'
    u'</DockPanel></ToggleButton></DataTemplate>')

USED_TEMPLATE = (
    u'<DataTemplate xmlns="{0}"><TextBlock Text="{{Binding used}}"'
    u' ToolTip="{{Binding sheets_tip}}" FontWeight="Bold"'
    u' VerticalAlignment="Center" Padding="3,1">'
    u'<TextBlock.Style><Style TargetType="TextBlock">'
    u'<Setter Property="Foreground" Value="{{DynamicResource BlueBrush}}"/>'
    u'<Style.Triggers>'
    u'<DataTrigger Binding="{{Binding used}}" Value="0">'
    u'<Setter Property="Foreground" Value="{{DynamicResource RedBrush}}"/>'
    u'</DataTrigger>'
    u'<DataTrigger Binding="{{Binding live}}" Value="0">'
    u'<Setter Property="TextDecorations" Value="Strikethrough"/>'
    u'</DataTrigger>'
    u'</Style.Triggers></Style></TextBlock.Style></TextBlock></DataTemplate>')

# Clouds off sheets: orange and bold where there are some, blank where
# there are none; the views they are in, on hover.
UNPLACED_TEMPLATE = (
    u'<DataTemplate xmlns="{0}"><TextBlock Text="{{Binding unplaced}}"'
    u' ToolTip="{{Binding unplaced_tip}}" FontWeight="Bold"'
    u' VerticalAlignment="Center" Padding="3,1">'
    u'<TextBlock.Style><Style TargetType="TextBlock">'
    u'<Setter Property="Foreground" Value="{{DynamicResource OrangeBrush}}"/>'
    u'<Style.Triggers>'
    u'<DataTrigger Binding="{{Binding unplaced}}" Value="0">'
    u'<Setter Property="Foreground" Value="{{DynamicResource MutedBrush}}"/>'
    u'<Setter Property="FontWeight" Value="Normal"/>'
    u'</DataTrigger>'
    u'</Style.Triggers></Style></TextBlock.Style></TextBlock></DataTemplate>')


def place_after(fields, saved, field, after):
    """A column new since the order was saved goes beside the one it
    follows, not at the far end."""
    if not saved or field in saved or field not in fields or \
            after not in fields:
        return list(fields)
    out = [one for one in fields if one != field]
    out.insert(out.index(after) + 1, field)
    return out


def views_report(entries):
    """(views, lines) for Find clouds on views: how many views hold the
    revisions' clouds, and one line per revision on where."""
    views = ps_revisions.views_to_open(entries)
    lines = []
    for entry in entries:
        count = len(entry.cloud_views or {})
        if count:
            lines.append(u'{0}: {1} cloud{2} in {3} view{4}{5}'.format(
                entry.fields.get('desc') or entry.key, entry.clouds,
                u'' if entry.clouds == 1 else u's', count,
                u'' if count == 1 else u's',
                u', {0} of them on no sheet'.format(len(entry.off_views))
                if entry.off_views else u''))
    return views, lines


# A revision added here and not yet applied: the whole row washed green,
# edged green, "ready to go on Apply". Parsed, then BasedOn the theme's
# GridRow in code - a StaticResource cannot resolve outside the window.
FRESH_ROW_STYLE = (
    u'<Style xmlns="{0}" TargetType="DataGridRow">'
    u'<Style.Triggers>'
    u'<DataTrigger Binding="{{Binding fresh}}" Value="1">'
    u'<Setter Property="Background" Value="{{DynamicResource GreenWashBrush}}"/>'
    u'<Setter Property="BorderBrush" Value="{{DynamicResource GreenBrush}}"/>'
    u'<Setter Property="BorderThickness" Value="0,1,0,1"/>'
    u'</DataTrigger>'
    u'</Style.Triggers></Style>')

# How wide each kind of extra column starts: fitted to its text, like the
# built-in ones.
CUSTOM_WIDTHS = {'text': AUTO, 'yesno': AUTO, 'number': AUTO, 'date': AUTO,
                 'choice': AUTO}


def fits(width):
    """Whether a column of this width sizes itself to its text."""
    return width == AUTO


def together(field, kind=None):
    """Whether an edit to ``field`` goes to every selected revision.

    Revit's own fields and the manager's columns do - except the Date, as
    the issue date of one revision is never right for several. Read-only
    columns (Sequence, Used on sheets, Sheet series) take no edit at all.
    """
    if field.startswith(u'x_'):
        return True
    return field in ps_revisions.FIELDS and \
        field not in ps_revisions.ALL_AT_ONCE_REFUSED


def jump_target(keys, order, current):
    """Which revision the list should go to for a selection in Revit.

    The first selected cloud's revision that the list actually holds, or
    None - and None when the list is already sitting on exactly that row,
    so a selection that has not moved never yanks the list about.
    """
    for key in keys or []:
        if key in (order or []):
            return None if list(current or []) == [key] else key
    return None


def column_order(fields, saved):
    """``fields`` in the order last saved: the saved ones first, as
    dragged, then any not in it (a column added since) where they were."""
    known = [field for field in saved if field in fields]
    seen = set(known)
    return known + [field for field in fields if field not in seen]


def keep_groups(fields, group_of):
    """The fields with each group's members side by side, where the first
    of them sits - a dragged order can split a group, and the band over a
    group only reads as one if its columns are together. ``group_of``
    gives a field's group, u'' for none."""
    out, placed = [], set()
    for field in fields:
        group = group_of(field)
        if not group:
            # Only grouped columns are moved. A column listed twice stays
            # listed twice, so the bench still sees that fault.
            out.append(field)
            continue
        if field in placed:
            continue
        for member in fields:
            if member not in placed and group_of(member) == group:
                out.append(member)
                placed.add(member)
    return out


# The Description column's floor, and its ceiling when the window opens; and
# the room a grid takes beyond its columns - the row headers and the
# vertical scroll bar.
DESCRIPTION_MIN = 240
DESCRIPTION_MAX = 480
GRID_SLACK = 24


def description_width(texts, per_char=7, padding=30):
    """The width Description opens at: its longest text, kept between
    DESCRIPTION_MIN and DESCRIPTION_MAX."""
    longest = max([len(u'{0}'.format(text or u'')) for text in texts] or [0])
    return max(DESCRIPTION_MIN, min(DESCRIPTION_MAX,
                                    longest * per_char + padding))


def needed_width(fixed, description, extra):
    """How wide the window wants to be: every sized column, Description,
    and the window's own chrome beside the grid."""
    return float(fixed) + float(description) + float(extra)


# The coloured strip over the headings: one band per kind of column, merged
# across every column of that kind that sits together, its name centred.
# (key, name, brush, whether its + adds a column of that kind)
STANDARD = 'standard'
CUSTOM = 'custom'
BANDS = [(STANDARD, u'Standard', 'SortL4', False),
         (CUSTOM, u'Custom', 'GreenBrush', True),
         (ps_revdata.STATUS, u'Issue Status', 'SortL5', False),
         (ps_revdata.ISSUED_TO, u'Issued To', 'BlueBrush', True),
         (ps_revdata.METHOD, u'Issued Method', 'OrangeBrush', True)]
BAND_INFO = dict([(key, (name, brush, adds))
                  for key, name, brush, adds in BANDS])


def band_runs(columns, band_of):
    """[(band, left, width)] - one run per stretch of side-by-side columns
    of one band. ``columns`` is [(field, width)] in the order shown; a
    column with no band (the + at the end) leaves a gap."""
    runs, x = [], 0.0
    for field, width in columns:
        band = band_of(field)
        if band and runs and runs[-1][0] == band and \
                abs(runs[-1][1] + runs[-1][2] - x) < 0.5:
            runs[-1] = (band, runs[-1][1], runs[-1][2] + width)
        elif band:
            runs.append((band, x, width))
        x += width
    return runs


class RevisionManager(object):
    """Modal. show() returns the plan to write, or None."""

    def __init__(self, staging, theme_name='dark', owner=None,
                 parameter_reader=None, status=u'', owner_handle=None,
                 settings=None, modeless=False, on_apply=None, focus=None,
                 current_sheet=None):
        self.staging = staging
        # The tool's settings, for the order the columns were dragged into.
        self.settings = settings
        # Modeless: Revit stays usable, Apply cannot write where it stands
        # (a modeless window is in no API context), and the window has to
        # outlive the command that opened it. on_apply takes the plan and
        # puts it through an external event; without one the window is
        # modal and show() hands the plan back to the caller instead.
        self.modeless = bool(modeless)
        self.on_apply = on_apply
        # Find clouds on views. Opened on its own (modeless), on_find takes
        # the revision keys and runs the job itself; opened from the
        # register (modal), the keys are left in find_request and the
        # window closes, so the register can run it.
        self.on_find = None
        self.find_request = None
        # Following the selection in Revit: on, and off while a cell is
        # being edited, so a half-typed value is never yanked away.
        self.follow = True
        self._watching = False
        self._uiapp = None
        self._editing = False
        self._token = None
        # The revisions a click in a multi-selection began on: an edit to
        # one of them goes to all of them (see together).
        self._multi = None
        # The sheet open in Revit (its number) or None, and whether the list
        # is filtered to it. The view's id spots a change of sheet.
        self.current_sheet = current_sheet
        self.sheet_filter = False
        self._view_token = None
        # Every Sheet series cell open (all series showing) or folded to
        # the first one and "+2" - as the user last left it.
        self.series_open = self._saved_series_open()
        # () -> the parameters bound to Sheets and Revision Clouds, read
        # from the model by whoever opened this; the column dialog and the
        # settings ask.
        self.parameter_reader = parameter_reader
        # A Revit command to run once this window has closed - set by the
        # settings' "Open Project Parameters", which cannot run while a
        # modal window is up.
        self.post_command = None
        self.theme_name = theme_name
        self.result = None
        self.filters = {}
        # field -> the set of values its filter list leaves ticked (u'' for
        # a blank cell); a column with no entry is not filtered
        self.picks = {}
        self.filter_buttons = {}
        # True while a filter list is open, so the grid's own keys (Ctrl+Up
        # moves revisions) leave the list's keys alone
        self._filter_open = False
        self.rows = {}
        self.search_boxes = []
        self._colours = None
        self._suspend = False

        self.window = ps_ui.load_window('ProSheetsRevisions.xaml', theme_name)
        self.chrome = ps_ui.Chrome(self.window, on_close=self._cancel)
        # The egg is armed on the main window only; see ps_ui.attach_egg.
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass
        elif owner_handle is not None:
            # Opened from its own ribbon button: owned by Revit's main
            # window, so it never slips behind Revit.
            try:
                from System.Windows.Interop import WindowInteropHelper
                WindowInteropHelper(self.window).Owner = owner_handle
            except Exception:
                pass
        # As wide as the columns need once they are measured, no wider than
        # the screen: see _fit_window. Hidden until then, so it does not
        # open at one width and jump to another.
        self._owner, self._owner_handle = owner, owner_handle
        # A double-click on the bottom bar stretches the window top to
        # bottom - the same toggle as the window's top and bottom edges
        # (ps_ui.Chrome.toggle_tall), so either undoes the other.
        footer = ps_ui.find(self.window, 'FooterBar')
        if footer is not None:
            try:
                footer.MouseLeftButtonDown += self._footer_click
            except Exception:
                pass
        try:
            self.window.Opacity = 0
            self.window.ContentRendered += self._fit_window
        except Exception:
            try:
                self.window.Opacity = 1
            except Exception:
                pass
        self._set_choices()

        self.grid = ps_ui.find(self.window, 'RevisionGrid')
        self.bands = ps_ui.find(self.window, 'RevisionBands')
        self._band_sig = None
        self._band_scroller = None
        self.status = ps_ui.find(self.window, 'StatusText')
        self.apply_button = ps_ui.find(self.window, 'ApplyButton')
        self.delete_text = ps_ui.find(self.window, 'RevDeleteText')
        self.per_project = ps_ui.find(self.window, 'RevPerProject')
        self.per_sheet = ps_ui.find(self.window, 'RevPerSheet')
        self.arc_box = ps_ui.find(self.window, 'RevArcBox')
        self.theme_chip = ps_ui.find(self.window, 'ThemeChip')
        self.series_button = ps_ui.find(self.window, 'RevSeriesToggleButton')
        self.follow_button = ps_ui.find(self.window, 'RevFollowButton')
        self.sheet_button = ps_ui.find(self.window, 'RevSheetFilterButton')
        self.sheet_text = ps_ui.find(self.window, 'RevSheetFilterText')
        self.follow = self._saved_follow()

        self.table = None
        self.view = None
        self._make_table()
        self._build_columns()
        self._fill_settings()
        self._wire()
        self._refill()
        self._paint_series_button()
        self._paint_follow_button()
        self._paint_sheet_button()
        if focus:
            self.focus(focus)
        self._say_theme()
        if status:
            self._say(status)
        elif ps_revisions.RevisionNumberingSequence is None:
            # Revit 2021 and older. The column is there, with nothing in it.
            self._say(u'This Revit has no revision numbering sequences - '
                      u'they arrived in Revit 2022 - so the Numbering '
                      u'column is empty and cannot be set.')

    # ==================================================================
    # building
    # ==================================================================

    def _set_choices(self):
        """The lists the combo editors offer, as resources on the window."""
        try:
            self.window.Resources['RevShowChoices'] = \
                List[String](ps_revisions.SHOW_LABELS)
            self.window.Resources['RevNumberingChoices'] = \
                List[String](self.staging.sequences)
            for column in self.staging.columns:
                if column.kind == 'choice':
                    self.window.Resources['RevChoices_' + column.id] = \
                        List[String]([u''] + column.choices)
        except Exception:
            pass

    def _make_table(self):
        """A fresh table for the staging's columns, extra ones included."""
        table = DataTable('revisions')
        table.Columns.Add('issued', Boolean).DefaultValue = False
        for name in ('key', 'pending', 'seq', 'ord', 'numbering', 'date',
                     'desc', 'issued_to', 'issued_by', 'show', 'used',
                     'sheets_tip', 'unplaced', 'unplaced_tip', 'live', 'vis', 'fresh', 'c_seq',
                     'c_numbering',
                     'c_date', 'c_desc', 'c_issued', 'c_issued_to',
                     'c_issued_by', 'c_show', 'series', 'series_more'):
            table.Columns.Add(name, String)
        table.Columns.Add('series_open', Boolean).DefaultValue = False
        table.Columns.Add('series_items', Object)
        table.Columns.Add('series_head', Object)
        for column in self.staging.columns:
            if column.kind == 'yesno':
                table.Columns.Add('x_' + column.id, Boolean).DefaultValue = \
                    False
            else:
                table.Columns.Add('x_' + column.id, String)
            table.Columns.Add('c_x_' + column.id, String)
        try:
            table.ColumnChanged += self._cell_changed
        except Exception:
            pass
        self.table = table
        self.view = table.DefaultView
        self.view.RowFilter = "[vis] = '1'"
        self.view.Sort = '[ord] ASC'

    def _rebuild(self, reselect=None):
        """After a column is added, changed or removed: new table, new
        grid columns, every row again. The searches start empty; a value
        filter stays on, unless its column has gone."""
        self._commit()
        self.filters = {}
        self.search_boxes = []
        self.filter_buttons = {}
        fields = set([entry[0] for entry in self._layout()])
        self.picks = dict([(field, allowed) for field, allowed in
                           self.picks.items() if field in fields])
        self._set_choices()
        self._make_table()
        self._build_columns()
        self._refill(reselect)

    def _layout(self):
        """(field, heading, width, kind, column): Revit's columns, then Used
        on sheets and Sheet series, then the user's own - in the order the
        user last dragged them into, where there is one."""
        out = [(field, title, width, kind, None)
               for field, title, width, kind in COLUMNS]
        for column in ps_revdata.group_order(self.staging.columns):
            kind = {'yesno': 'check', 'choice': 'RevChoices_' + column.id}.get(
                column.kind, 'text')
            out.append(('x_' + column.id, column.name,
                        CUSTOM_WIDTHS.get(column.kind, 160), kind, column))
        by_field = dict([(entry[0], entry) for entry in out])
        saved = self._saved_order()
        ordered = place_after(column_order([entry[0] for entry in out],
                                           saved), saved, 'unplaced',
                              'series')
        return [by_field[field] for field in
                keep_groups(ordered, self._group_of)]

    def _group_of(self, field):
        """The Issued To / Method group a grid field belongs to, or u''."""
        if not u'{0}'.format(field).startswith(u'x_'):
            return u''
        column = self.staging.column(field[2:])
        if column is None or column.group not in (ps_revdata.ISSUED_TO,
                                                  ps_revdata.METHOD):
            return u''
        return column.group

    # ------------------------------------------------------- column order
    def _saved_order(self):
        if self.settings is None:
            return []
        try:
            return [one for one in u'{0}'.format(
                self.settings.text('rev_column_order', u'') or u'').split(u',')
                if one]
        except Exception:
            return []

    def _column_moved(self, sender, args):
        """A heading dragged somewhere else: remember the order, per
        machine, for the next time the manager opens."""
        if self.settings is None or self.grid is None:
            return
        try:
            columns = sorted(list(self.grid.Columns),
                             key=lambda column: column.DisplayIndex)
            fields = [u'{0}'.format(column.SortMemberPath or u'')
                      for column in columns]
            self.settings.set('rev_column_order',
                              u','.join([field for field in fields if field]))
            self.settings.save()
        except Exception:
            pass

    # ------------------------------------------------- sheet series, open
    def _saved_series_open(self):
        if self.settings is None:
            return True
        try:
            return bool(self.settings.flag('rev_series_open', True))
        except Exception:
            return True

    def _toggle_series(self, sender, args):
        """Expand or collapse every Sheet series cell at once, and keep the
        choice for next time. A single cell still folds on its own click."""
        self._commit()
        self.series_open = not self.series_open
        self._suspend = True
        try:
            for row in self.rows.values():
                row['series_open'] = self.series_open
        finally:
            self._suspend = False
        if self.settings is not None:
            try:
                self.settings.set('rev_series_open',
                                  u'1' if self.series_open else u'0')
                self.settings.save()
            except Exception:
                pass
        self._paint_series_button()
        self._say(u'Every revision\'s sheet series {0}.'.format(
            u'listed in full' if self.series_open else u'folded to the first'))

    def _paint_series_button(self):
        ps_ui.set_content(self.series_button, u'Collapse series'
                          if self.series_open else u'Expand series')

    # --------------------------------------------- following the selection
    def _saved_follow(self):
        if self.settings is None:
            return True
        try:
            return bool(self.settings.flag('rev_follow_selection', True))
        except Exception:
            return True

    def watch_selection(self, uiapp):
        """Follow what is selected in Revit, through Idling.

        Idling is raised on Revit's own main thread inside a valid API
        context, which is the one place a modeless window is allowed to
        read the model. Reading the selection straight from a window
        handler is what throws "Attempting to modify the model outside of
        transaction" and its read-side cousins.
        """
        self._uiapp = uiapp
        try:
            uiapp.Idling += self._idling
            self._watching = True
        except Exception:
            self._watching = False
        try:
            self.window.Closed += self._on_closed
        except Exception:
            pass
        return self._watching

    def stop_watching(self, sender=None, args=None):
        """Hand Idling back. A handler left subscribed after its window has
        gone is a handler Revit calls into a dead engine."""
        if not self._watching:
            return
        self._watching = False
        try:
            self._uiapp.Idling -= self._idling
        except Exception:
            pass

    def _on_closed(self, sender, args):
        self.stop_watching()

    def _idling(self, sender, args):
        """Revit is idle, on its main thread, in a valid API context: the
        moment to see which sheet is open, and what is selected."""
        try:
            uidoc = sender.ActiveUIDocument
        except Exception:
            return
        if uidoc is None:
            return
        if not self._editing:
            self.track_sheet(uidoc)
        if not self.follow or self._editing:
            return
        token = ps_revisions.selection_token(uidoc)
        if token == self._token:
            return
        self._token = token
        if not token:
            return
        try:
            keys = ps_revisions.selected_revision_keys(uidoc)
        except Exception:
            return
        self.go_to(keys)

    def focus(self, keys):
        """Open on these revisions: selected, and the first brought into
        the middle of the grid. A revision cloud picked before opening, or
        Edit revision on the Document Register."""
        keys = [key for key in [u'{0}'.format(one) for one in keys or []]
                if key in self.staging.order]
        if not keys:
            return False
        self._select(keys)
        self._centre_on(keys[0])
        self._say(u'Showing {0}.'.format(u', '.join(
            [u'revision {0}'.format(self.staging.staged_sequence(key))
             for key in keys[:6]]) + (u' and {0} more'.format(len(keys) - 6)
                                       if len(keys) > 6 else u'')))
        return True

    # ------------------------------------------------- the current sheet
    def _filter_sheet(self):
        """The sheet number the list is filtered to, or None."""
        return self.current_sheet if self.sheet_filter and \
            self.current_sheet else None

    def track_sheet(self, uidoc):
        """Which sheet is open in Revit. From Idling: when the open view
        changes, light or grey the button, and re-filter if it is on."""
        try:
            view = uidoc.ActiveView
            token = u'{0}'.format(ps_revisions.ps_model.eid_value(view.Id))
        except Exception:
            return
        if token == self._view_token:
            return
        self._view_token = token
        sheet = ps_revisions.sheet_number_of(view)
        if sheet == self.current_sheet:
            return
        self.current_sheet = sheet
        self._paint_sheet_button()
        if self.sheet_filter:
            self._refresh()
            self._say(u'Revisions on sheet {0}.'.format(sheet) if sheet else
                      u'No sheet open in Revit - showing every revision. The '
                      u'filter comes back on the next sheet you open.')

    def _toggle_sheet_filter(self, sender, args):
        if not self.current_sheet:
            return
        self._commit()
        self.sheet_filter = not self.sheet_filter
        self._paint_sheet_button()
        self._refresh()
        count = len(self.staging.visible(self.filters, self.picks,
                                         self._filter_sheet()))
        self._say(u'{0} revision{1} on sheet {2}. It follows you as you change '
                  u'sheets.'.format(count, u'' if count == 1 else u's',
                                    self.current_sheet)
                  if self.sheet_filter else u'Showing every revision.')

    def _paint_sheet_button(self):
        """Grey with no sheet open, lit with one, solid orange while the
        list is filtered to it."""
        button = self.sheet_button
        if button is None:
            return
        on_sheet = bool(self.current_sheet)
        try:
            button.IsEnabled = on_sheet
            button.Opacity = 1.0 if on_sheet else 0.5
            button.SetResourceReference(
                Button.StyleProperty,
                'SwitchButtonOn' if on_sheet and self.sheet_filter else
                ('ChipButtonOn' if on_sheet else 'ChipButton'))
            button.ToolTip = (
                u'Show only the revisions on sheet {0}, the sheet open in '
                u'Revit. Follows you as you change sheets.'.format(
                    self.current_sheet) if on_sheet else
                u'Open a sheet in Revit to filter to its revisions.')
        except Exception:
            pass
        ps_ui.set_text(self.sheet_text,
                       u'Filtered to sheet {0}'.format(self.current_sheet)
                       if on_sheet and self.sheet_filter
                       else u'Filter revisions on current sheet')

    # ------------------------------------------- one value, many revisions
    @staticmethod
    def _ancestor(node, kind):
        for _step in range(16):
            if node is None:
                return None
            if isinstance(node, kind):
                return node
            try:
                node = VisualTreeHelper.GetParent(node)
            except Exception:
                node = getattr(node, 'Parent', None)
        return None

    def _is_tick(self, field):
        if field == 'issued':
            return True
        if field.startswith(u'x_'):
            column = self.staging.column(field[2:])
            return column is not None and column.kind == 'yesno'
        return False

    def _grid_press(self, sender, args):
        """A press inside a selection of several revisions.

        Noted first, before the grid narrows the selection to the one row:
        an edit begun here goes to every one of them (see together). For a
        text or a list cell the press is taken over and the editor opened
        directly, so the rows stay selected - visibly - while it is typed.
        A tick handles its own press; the rows are selected again after.
        """
        self._multi = None
        if ps_ui.ctrl_down() or ps_ui.shift_down():
            return
        try:
            source = args.OriginalSource
        except Exception:
            return
        cell = self._ancestor(source, DataGridCell)
        row = self._ancestor(source, DataGridRow)
        if cell is None or row is None:
            return
        try:
            key = u'{0}'.format(row.Item.Row['key'])
            field = u'{0}'.format(cell.Column.SortMemberPath or u'')
        except Exception:
            return
        keys = self._selected()
        if len(keys) < 2 or key not in keys or not together(field):
            return
        self._multi = list(keys)
        if self._is_tick(field) or cell.IsEditing:
            return
        try:
            args.Handled = True
            self.grid.CurrentCell = DataGridCellInfo(row.Item, cell.Column)
            self.grid.BeginEdit()
        except Exception:
            pass

    def _others(self, key, field):
        if not self._multi or key not in self._multi or not together(field):
            return []
        return [one for one in self._multi if one != key]

    def _spread(self, key, field, others):
        """Copy one revision's newly staged value onto the others selected
        with it, and show it in their rows."""
        if field.startswith(u'x_'):
            column_id = field[2:]
            column = self.staging.column(column_id)
            value = self.staging.custom_value(self.staging.entries[key],
                                              column)
            changed, refusals = self.staging.set_custom_many(
                others, column_id, value == u'1' if column.kind == 'yesno'
                else value)
        else:
            value = self.staging.entries[key].fields.get(field)
            changed, refusals = self.staging.set_field_many(others, field,
                                                            value)
        self._suspend = True
        try:
            for other in changed:
                row = self.rows.get(other)
                if row is None:
                    continue
                if field.startswith(u'x_'):
                    stored = self.staging.custom_value(
                        self.staging.entries[other], column)
                    row[field] = (stored == u'1') \
                        if column.kind == 'yesno' else stored
                else:
                    row[field] = self.staging.entries[other].fields.get(field)
        finally:
            self._suspend = False
        keep = list(self._multi or [])

        def reselect():
            self._select(keep)
        try:
            self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background,
                                               Action(reselect))
        except Exception:
            reselect()
        total = len(changed) + 1
        self._say(u'Set on {0} revisions.{1}'.format(
            total, (u' ' + u' '.join(refusals)) if refusals else u''))

    def go_to(self, keys):
        """Take the list to the first of these revisions that it holds."""
        target = jump_target(keys, self.staging.order, self._selected())
        if target is None:
            return False
        self._select([target], scroll=True)
        entry = self.staging.entries.get(target)
        self._say(u'Selected in Revit: revision {0}{1}.'.format(
            self.staging.staged_sequence(target) or u'?',
            u' - {0}'.format(entry.fields.get('desc')) if entry is not None
            and entry.fields.get('desc') else u''))
        return True

    def _toggle_follow(self, sender, args):
        self.follow = not self.follow
        if self.settings is not None:
            try:
                self.settings.set('rev_follow_selection',
                                  u'1' if self.follow else u'0')
                self.settings.save()
            except Exception:
                pass
        self._token = None
        self._paint_follow_button()
        self._say(u'Picking a revision cloud in Revit {0}.'.format(
            u'takes the list to its revision' if self.follow
            else u'no longer moves the list'))

    def _paint_follow_button(self):
        """Only of use while Revit is usable, so it is hidden when modal."""
        if self.follow_button is None:
            return
        ps_ui.set_visible(self.follow_button, self.modeless)
        try:
            self.follow_button.Content = u'Following selection' \
                if self.follow else u'Not following selection'
            self.follow_button.SetResourceReference(
                Button.StyleProperty,
                'ChipButtonOn' if self.follow else 'ChipButton')
        except Exception:
            pass

    def _reset_order(self, sender, args):
        if self.settings is not None:
            try:
                self.settings.set('rev_column_order', u'')
                self.settings.save()
            except Exception:
                pass
        self._rebuild(self._selected())
        self._say(u'Columns back in their first order.')

    def _fit_columns(self, sender, args):
        """Every fitting column back to its text. Dragging a heading's edge
        pins that column to a pixel width; this hands it back, and takes in
        anything typed since the grid was built."""
        self._commit()
        if self.grid is None:
            return
        wide = dict([(entry[0], entry[2]) for entry in self._layout()])
        fitted = 0
        for column in self.grid.Columns:
            field = u'{0}'.format(column.SortMemberPath or u'')
            if not fits(wide.get(field, 0)):
                continue
            try:
                column.Width = DataGridLength.Auto
                fitted += 1
            except Exception:
                pass
        self._say(u'{0} column{1} fitted to their text.'.format(
            fitted, u'' if fitted == 1 else u's'))

    def _build_columns(self):
        if self.grid is None:
            return
        try:
            self.grid.Columns.Clear()
            self.grid.ItemsSource = self.view
        except Exception:
            return
        try:
            self.grid.RowStyle = self._fresh_row_style()
        except Exception:
            pass
        layout = self._layout()
        self._band_sig = None
        for field, title, width, kind, extra in layout:
            column = DataGridTemplateColumn()
            # Read back in BeginningEdit to know which field is being
            # edited; nothing sorts on it, sorting is off.
            column.SortMemberPath = field
            tip = {'used': u' ToolTip="{Binding sheets_tip}"',
                   # What the Change column used to say - New, Edited,
                   # Delete, Merge into 3 - now only here.
                   'seq': u' ToolTip="{Binding pending}"'}.get(field, u'')
            column.CellTemplate = XamlReader.Parse(SHOW_TEMPLATE.format(
                PRESENTATION, field, tip, TEXT_STYLE.format(field)))
            if kind == 'series':
                column.IsReadOnly = True
                column.CellTemplate = XamlReader.Parse(
                    SERIES_TEMPLATE.format(PRESENTATION))
            elif kind == 'unplaced':
                column.IsReadOnly = True
                column.CellTemplate = XamlReader.Parse(
                    UNPLACED_TEMPLATE.format(PRESENTATION))
            elif kind == 'used':
                # Red where nothing carries the revision, blue where
                # something does - the first thing to look at before a
                # delete or a merge.
                column.IsReadOnly = True
                column.CellTemplate = XamlReader.Parse(USED_TEMPLATE.format(
                    PRESENTATION))
            elif kind == 'read':
                column.IsReadOnly = True
            elif kind == 'text':
                column.CellEditingTemplate = XamlReader.Parse(
                    TEXT_EDIT_TEMPLATE.format(PRESENTATION, field))
            elif kind == 'check':
                column.CellTemplate = XamlReader.Parse(
                    CHECK_TEMPLATE.format(PRESENTATION, field))
            else:
                column.CellEditingTemplate = XamlReader.Parse(
                    COMBO_EDIT_TEMPLATE.format(PRESENTATION, field, kind))
            if fits(width):
                # Auto, not SizeToCells: the heading - its title, its search
                # box and its list button - counts as well as the values.
                column.Width = DataGridLength.Auto
                column.MinWidth = AUTO_MIN
                column.MaxWidth = AUTO_MAX
            elif width:
                column.Width = DataGridLength(width)
            else:
                column.Width = DataGridLength(1, DataGridLengthUnitType.Star)
                # The floor it keeps when the window is narrower than the
                # columns: then the grid scrolls rather than squeezing it.
                column.MinWidth = DESCRIPTION_MIN
            column.Header = self._header(field, title, extra)
            self.grid.Columns.Add(column)
        self.grid.Columns.Add(self._plus_column())
        # The first column (Sequence, unless dragged) stays put while the
        # rest scroll, so a row can still be told apart on a small screen.
        try:
            self.grid.FrozenColumnCount = 1
        except Exception:
            pass

    def _plus_column(self):
        """The last column: nothing in it but a green + in its heading."""
        column = DataGridTemplateColumn()
        column.IsReadOnly = True
        column.Width = DataGridLength(44)
        column.CanUserResize = False
        column.CanUserReorder = False
        column.CellTemplate = XamlReader.Parse(
            u'<DataTemplate xmlns="{0}"><TextBlock/></DataTemplate>'.format(
                PRESENTATION))
        button = Button()
        button.SetResourceReference(Button.StyleProperty, 'IconButton')
        button.ToolTip = u'Add a column of your own'
        button.Content = XamlReader.Parse(PLUS_ICON.format(PRESENTATION))
        button.Click += self._add_column
        column.Header = button
        return column

    # ------------------------------------------------------- the bands
    # ------------------------------------------------- the window's height
    def _footer_click(self, sender, args):
        """A double-click on the bottom bar - not on its buttons -
        stretches the window to the full height of its screen, and a
        second one puts it back."""
        try:
            if args.ClickCount != 2:
                return
            if self._ancestor(args.OriginalSource, Button) is not None:
                return
        except Exception:
            return
        stretched = self.chrome.toggle_tall()
        try:
            args.Handled = True
        except Exception:
            pass
        if stretched is not None:
            self._say(u'Stretched to the full height of the screen - '
                      u'double-click the bar, or the top or bottom edge, '
                      u'again to put it back.' if stretched else
                      u'Back to its own height.')

    # ------------------------------------------------- the window's width
    def _fit_window(self, sender=None, args=None):
        """Once the columns have measured themselves: the window as wide
        as they need - Description at the width of its longest text - and
        no wider than the screen, where the grid's own scroll bar takes
        the rest. Shown either way."""
        try:
            self.window.ContentRendered -= self._fit_window
        except Exception:
            pass
        try:
            fixed = sum([float(column.ActualWidth) for column in
                         self.grid.Columns if not column.Width.IsStar])
            extra = float(self.window.ActualWidth) - \
                float(self.grid.ActualWidth) + GRID_SLACK
            ps_ui.fit_width(self.window, needed_width(
                fixed, self._description_width(), extra),
                self._owner, self._owner_handle)
        except Exception:
            pass
        finally:
            try:
                self.window.Opacity = 1
            except Exception:
                pass

    def _description_width(self):
        texts = [u'{0}'.format(entry.fields.get('desc') or u'')
                 for entry in self.staging.entries.values()]
        return description_width(texts)

    def _band_of(self, field):
        """Which band a grid field sits under: Standard for Revit's own
        fields and the manager's derived ones, then the user's columns by
        their kind. The + column has none."""
        field = u'{0}'.format(field or u'')
        if field in [entry[0] for entry in COLUMNS]:
            return STANDARD
        if field.startswith(u'x_'):
            column = self.staging.column(field[2:])
            if column is None:
                return u''
            return column.group or CUSTOM
        return u''

    def _paint_bands(self, sender=None, args=None):
        """Draw the band strip from the columns as they stand. Called on
        every layout pass, so it does nothing unless a width, the order or
        the scroll has changed since last time."""
        if self.bands is None or self.grid is None:
            return
        try:
            columns = sorted([column for column in self.grid.Columns
                              if column.Visibility == Visibility.Visible],
                             key=lambda column: column.DisplayIndex)
            pairs = [(u'{0}'.format(column.SortMemberPath or u''),
                      float(column.ActualWidth)) for column in columns]
            scroller = self._band_scroller or self._scroller()
            self._band_scroller = scroller
            offset = float(scroller.HorizontalOffset) if scroller else 0.0
            start = float(self.grid.RowHeaderActualWidth or 0.0) - offset
        except Exception:
            return
        signature = (tuple([(field, int(round(width)))
                            for field, width in pairs]), int(round(start)))
        if signature == self._band_sig:
            return
        self._band_sig = signature
        try:
            self.bands.Children.Clear()
        except Exception:
            return
        for band, left, width in band_runs(pairs, self._band_of):
            try:
                self.bands.Children.Add(self._band_strip(band, start + left,
                                                         width))
            except Exception:
                continue

    def _band_strip(self, band, left, width):
        name, brush, adds = BAND_INFO.get(band, (u'', 'BlueBrush', False))
        strip = Border()
        strip.SetResourceReference(Border.BackgroundProperty, brush)
        strip.CornerRadius = CornerRadius(3, 3, 0, 0)
        strip.Width = max(0.0, width - 2)
        strip.Height = 22
        strip.ToolTip = name
        Canvas.SetLeft(strip, left + 1)
        Canvas.SetTop(strip, 2)
        holder = Grid()
        label = TextBlock()
        label.Text = name.upper()
        label.FontWeight = FontWeights.Bold
        label.FontSize = 11
        label.TextTrimming = TextTrimming.CharacterEllipsis
        label.HorizontalAlignment = HorizontalAlignment.Center
        label.VerticalAlignment = VerticalAlignment.Center
        label.Margin = Thickness(4, 0, 24 if adds else 4, 0)
        label.SetResourceReference(TextBlock.ForegroundProperty,
                                   'OnOrangeBrush')
        holder.Children.Add(label)
        if adds:
            add = Button()
            add.SetResourceReference(Button.StyleProperty, 'IconButton')
            add.Width = 20
            add.Height = 18
            add.HorizontalAlignment = HorizontalAlignment.Right
            add.Margin = Thickness(0, 0, 2, 0)
            add.Content = XamlReader.Parse(PLUS_ICON.format(PRESENTATION))
            add.ToolTip = u'Add a {0} column'.format(name)
            add.Click += self._make_add_to_group(
                u'' if band == CUSTOM else band)
            holder.Children.Add(add)
        strip.Child = holder
        return strip

    def _make_add_to_group(self, group):
        def clicked(sender, args):
            self._add_column(sender, args, group)
        return clicked

    def _header(self, field, title, extra=None):
        panel = StackPanel()
        panel.Orientation = Orientation.Vertical
        heading = TextBlock()
        heading.Text = title
        if extra is None:
            panel.Children.Add(heading)
        else:
            # An extra column: its name, where it is pushed, and a pencil
            # to rename it, map it or remove it.
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            heading.SetResourceReference(TextBlock.ForegroundProperty,
                                         'GreenBrush')
            row.Children.Add(heading)
            edit = Button()
            edit.SetResourceReference(Button.StyleProperty, 'IconButton')
            edit.Width = 20
            edit.Height = 18
            edit.Margin = Thickness(4, 0, 0, 0)
            edit.Content = XamlReader.Parse(PENCIL_ICON.format(PRESENTATION))
            edit.ToolTip = u'Rename, change the choices, map to a parameter, ' \
                u'or remove "{0}"'.format(extra.name)
            edit.Click += self._make_edit_column(extra.id)
            row.Children.Add(edit)
            panel.Children.Add(row)
            panel.ToolTip = u'{0} column{1}'.format(
                ps_revdata.KIND_LABELS.get(extra.kind, u''),
                u' - pushed to "{0}" on {1}'.format(
                    extra.parameter, u'sheets' if extra.target == 'sheets'
                    else u'revision clouds') if extra.pushed else
                u' - kept in the model')
        # The search box, and beside it the list of every value in the
        # column - Excel's filter, as on the Document Register.
        line = Grid()
        line.Margin = Thickness(0, 4, 4, 0)
        for width in (None, 30):
            definition = ColumnDefinition()
            if width:
                definition.Width = GridLength(width)
            line.ColumnDefinitions.Add(definition)
        box = TextBox()
        box.SetResourceReference(TextBox.StyleProperty, 'ColumnSearchBox')
        box.ToolTip = u'Search this column'
        box.Margin = Thickness(0, 0, 3, 0)
        box.TextChanged += self._make_search(field)
        self.filters[field] = u''
        Grid.SetColumn(box, 0)
        line.Children.Add(box)
        self.search_boxes.append(box)
        line.Children.Add(self._filter_button(field))
        panel.Children.Add(line)
        return panel

    # ------------------------------------------------------ value filters
    def _filter_button(self, field):
        """The filter button under a heading. A Button handles its own
        press, so the heading never takes it as the start of a drag."""
        button = Button()
        button.Height = 20
        button.Click += self._make_filter_open(field, button)
        Grid.SetColumn(button, 1)
        self.filter_buttons[field] = button
        self._paint_filter_button(field)
        return button

    def _paint_filter_button(self, field):
        button = self.filter_buttons.get(field)
        if button is None:
            return
        allowed = self.picks.get(field)
        on = allowed is not None
        try:
            button.SetResourceReference(
                Button.StyleProperty, 'FilterButtonOn' if on else 'FilterButton')
            button.Content = u'\u25be{0}'.format(len(allowed)) if on \
                else u'\u25be'
            button.ToolTip = (u'Showing {0} value{1} - click to change'.format(
                len(allowed), u'' if len(allowed) == 1 else u's') if on
                else u'Pick which values to show')
        except Exception:
            pass

    def _make_filter_open(self, field, button):
        def handler(sender, args):
            self._open_filter(field, button)
        return handler

    def _value_chip(self, field, value):
        """How a value reads in the list: Sheet series as its coloured chip,
        the same as in the cell; everything else as text."""
        text = TextBlock()
        text.Text = value
        text.VerticalAlignment = VerticalAlignment.Center
        if field != 'series' or value == ps_register.BLANKS:
            return text
        if self._colours is None:
            self._colours = self._series_brushes()
        fill, edge = self._colours.get(value, (None, None))
        if fill is None:
            return text
        chip = Border()
        chip.Background = fill
        chip.BorderBrush = edge
        chip.BorderThickness = Thickness(1)
        chip.CornerRadius = CornerRadius(3)
        chip.Padding = Thickness(6, 0, 6, 0)
        text.FontSize = 11
        chip.Child = text
        return chip

    def _open_filter(self, field, button):
        """The list: search, All / None, Tick / Untick selected, every value
        with a tick, OK. Ctrl- and Shift-click select several values;
        ticking one of them, or Space, ticks them all."""
        self._commit()
        choices = self.staging.choices(field, self.filters, self.picks)
        allowed = self.picks.get(field)

        def raw(value):
            return u'' if value == ps_register.BLANKS else value

        popup = Popup()
        popup.PlacementTarget = button
        popup.Placement = PlacementMode.Bottom
        popup.StaysOpen = False
        popup.AllowsTransparency = True

        shell = Border()
        shell.SetResourceReference(Border.BackgroundProperty, 'CardBg')
        shell.SetResourceReference(Border.BorderBrushProperty, 'EdgeBrush')
        shell.BorderThickness = Thickness(1)
        shell.CornerRadius = CornerRadius(4)
        shell.Padding = Thickness(8)
        shell.MinWidth = 230
        shell.MaxWidth = 340
        panel = StackPanel()
        shell.Child = panel

        search = TextBox()
        search.SetResourceReference(TextBox.StyleProperty, 'ColumnSearchBox')
        search.Tag = u'Search'
        search.Margin = Thickness(0, 0, 0, 6)
        panel.Children.Add(search)

        bulk = StackPanel()
        bulk.Orientation = Orientation.Horizontal
        bulk.Margin = Thickness(0, 0, 0, 6)
        chips = []
        for label, tip in ((u'All', u'Tick every value listed'),
                           (u'None', u'Untick every value listed'),
                           (u'Tick selected', u'Tick the highlighted values'),
                           (u'Untick selected',
                            u'Untick the highlighted values')):
            chip = Button()
            chip.Content = label
            chip.ToolTip = tip
            chip.SetResourceReference(Button.StyleProperty, 'ChipButton')
            chip.Margin = Thickness(0, 0, 5, 0)
            bulk.Children.Add(chip)
            chips.append(chip)
        every, none, tick, untick = chips
        panel.Children.Add(bulk)

        listing = ListBox()
        listing.SelectionMode = SelectionMode.Extended
        listing.MaxHeight = 280
        listing.MinHeight = 60
        panel.Children.Add(listing)
        boxes = []                       # (value, ListBoxItem, CheckBox)
        for value in choices:
            item = ListBoxItem()
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            box = CheckBox()
            box.IsChecked = allowed is None or raw(value) in allowed
            box.Margin = Thickness(0, 0, 6, 0)
            box.VerticalAlignment = VerticalAlignment.Center
            row.Children.Add(box)
            row.Children.Add(self._value_chip(field, value))
            item.Content = row
            listing.Items.Add(item)
            boxes.append((value, item, box))
        if not boxes:
            empty = TextBlock()
            empty.Text = u'Nothing showing to filter.'
            empty.Margin = Thickness(4)
            panel.Children.Add(empty)

        hint = TextBlock()
        hint.SetResourceReference(TextBlock.StyleProperty, 'MutedText')
        hint.TextWrapping = TextWrapping.Wrap
        hint.Margin = Thickness(0, 6, 0, 0)
        hint.Text = (u'Ctrl or Shift + click to select several values, then '
                     u'tick one of them (or press Space) to tick them all.')
        panel.Children.Add(hint)

        actions = StackPanel()
        actions.Orientation = Orientation.Horizontal
        actions.HorizontalAlignment = HorizontalAlignment.Right
        actions.Margin = Thickness(0, 8, 0, 0)
        ok = Button()
        ok.Content = u'OK'
        ok.MinWidth = 64
        ok.SetResourceReference(Button.StyleProperty, 'PrimaryButton')
        ok.Margin = Thickness(0, 0, 6, 0)
        cancel = Button()
        cancel.Content = u'Cancel'
        cancel.MinWidth = 64
        cancel.SetResourceReference(Button.StyleProperty, 'ChipButton')
        actions.Children.Add(ok)
        actions.Children.Add(cancel)
        panel.Children.Add(actions)
        popup.Child = shell

        def shown():
            return [(item, box) for _value, item, box in boxes
                    if item.Visibility == Visibility.Visible]

        def selected():
            return [(item, box) for item, box in shown() if item.IsSelected]

        def set_all(pairs, state):
            for _item, box in pairs:
                box.IsChecked = state

        def on_search(sender, args):
            term = u'{0}'.format(search.Text or u'').strip().lower()
            for value, item, _box in boxes:
                item.Visibility = Visibility.Visible \
                    if (not term or term in value.lower()) \
                    else Visibility.Collapsed
                if item.Visibility != Visibility.Visible:
                    item.IsSelected = False

        def make_ticked(item):
            # A tick on one of several highlighted values ticks them all.
            def ticked(sender, args):
                group = selected()
                if item.IsSelected and len(group) > 1:
                    set_all(group, bool(sender.IsChecked))
            return ticked

        def on_list_key(sender, args):
            try:
                key = args.Key
            except Exception:
                return
            if key != Key.Space:
                return
            group = selected()
            if group:
                set_all(group, not all([bool(box.IsChecked)
                                        for _item, box in group]))
                args.Handled = True

        def on_ok(sender, args):
            ticked = set([raw(value) for value, _item, box in boxes
                          if bool(box.IsChecked)])
            if boxes and not ticked:
                self._say(u'Tick at least one value to show.')
                return
            popup.IsOpen = False
            # Everything ticked is no filter at all, so a value that turns
            # up later is not hidden by a list that never knew it.
            self.set_pick(field, None if len(ticked) == len(boxes)
                          else ticked)

        def on_cancel(sender, args):
            popup.IsOpen = False

        def on_shell_key(sender, args):
            try:
                key = args.Key
            except Exception:
                return
            if key == Key.Escape:
                popup.IsOpen = False
                args.Handled = True
            elif key == Key.Enter:
                on_ok(sender, args)
                args.Handled = True

        def on_closed(sender, args):
            self._filter_open = False
            try:
                holder.Children.Remove(popup)
            except Exception:
                pass

        def swallow(sender, args):
            # A popup's events bubble back through its logical parent - the
            # heading. Whatever the controls inside leave unhandled stops
            # here, or a press would start dragging the column.
            try:
                args.Handled = True
            except Exception:
                pass

        for _value, item, box in boxes:
            box.Click += make_ticked(item)
        shell.MouseLeftButtonDown += swallow
        shell.MouseLeftButtonUp += swallow
        shell.KeyDown += swallow
        shell.PreviewKeyDown += on_shell_key
        listing.PreviewKeyDown += on_list_key
        search.TextChanged += on_search
        every.Click += lambda sender, args: set_all(shown(), True)
        none.Click += lambda sender, args: set_all(shown(), False)
        tick.Click += lambda sender, args: set_all(selected(), True)
        untick.Click += lambda sender, args: set_all(selected(), False)
        ok.Click += on_ok
        cancel.Click += on_cancel
        popup.Closed += on_closed
        # Into the heading's own panel, so the list is in the window's
        # logical tree and its DynamicResource colours resolve.
        holder = button.Parent
        try:
            holder.Children.Add(popup)
        except Exception:
            pass
        self._filter_open = True
        popup.IsOpen = True
        try:
            search.Focus()
        except Exception:
            pass

    def set_pick(self, field, allowed):
        """Set or clear one column's value filter, then re-take the view."""
        if allowed is None:
            self.picks.pop(field, None)
        else:
            self.picks[field] = set(allowed)
        self._paint_filter_button(field)
        self._refresh()

    def _make_search(self, field):
        def changed(sender, args):
            try:
                self.filters[field] = u'{0}'.format(sender.Text or u'')
            except Exception:
                self.filters[field] = u''
            self._refresh()
        return changed

    def _fill_settings(self):
        self._suspend = True
        try:
            per_sheet = self.staging.settings['numbering'] == \
                ps_revisions.PER_SHEET
            if self.per_sheet is not None:
                self.per_sheet.IsChecked = per_sheet
            if self.per_project is not None:
                self.per_project.IsChecked = not per_sheet
            ps_ui.set_text(self.arc_box, self._arc_text(
                self.staging.settings['arc_mm']))
        finally:
            self._suspend = False

    @staticmethod
    def _arc_text(value):
        try:
            return u'{0:g}'.format(float(value))
        except Exception:
            return u''

    def _wire(self):
        try:
            self.table.ColumnChanged += self._cell_changed
        except Exception:
            pass
        if self.grid is not None:
            try:
                self.grid.BeginningEdit += self._beginning_edit
                self.grid.PreviewKeyDown += self._key_down
                self.grid.SelectionChanged += self._selection_changed
                self.grid.CurrentCellChanged += self._current_cell
                self.grid.ColumnReordered += self._column_moved
                self.grid.LayoutUpdated += self._paint_bands
                self.grid.PreviewMouseRightButtonDown += self._right_press
                self.grid.PreviewMouseRightButtonUp += self._right_release
                self.grid.PreviewMouseLeftButtonDown += self._grid_press
            except Exception:
                pass
        for name, handler in (
                ('RevAddButton', self._add),
                ('RevDeleteButton', self._delete),
                ('RevMoveUpButton', lambda sender, args: self._move(-1)),
                ('RevMoveDownButton', lambda sender, args: self._move(1)),
                ('RevMergeUpButton', lambda sender, args: self._merge(-1)),
                ('RevMergeDownButton', lambda sender, args: self._merge(1)),
                ('RevClearSearchButton', self._clear_searches),
                ('RevAddColumnButton', self._add_column),
                ('RevPushButton', self._push),
                ('RevSettingsButton', self._open_settings),
                ('RevFitColumnsButton', self._fit_columns),
                ('RevResetColumnsButton', self._reset_order),
                ('RevSeriesToggleButton', self._toggle_series),
                ('RevFollowButton', self._toggle_follow),
                ('RevSheetFilterButton', self._toggle_sheet_filter),
                ('ThemeChip', self._toggle_theme),
                ('ApplyButton', self._apply),
                ('CancelButton', lambda sender, args: self._cancel())):
            button = ps_ui.find(self.window, name)
            if button is None:
                continue
            try:
                button.Click += handler
            except Exception:
                continue
        for radio, mode in ((self.per_project, ps_revisions.PER_PROJECT),
                            (self.per_sheet, ps_revisions.PER_SHEET)):
            if radio is None:
                continue
            try:
                radio.Checked += self._make_numbering(mode)
            except Exception:
                pass
        if self.arc_box is not None:
            try:
                self.arc_box.TextChanged += self._arc_changed
            except Exception:
                pass

    # ==================================================================
    # the table, from the staging
    # ==================================================================

    def _refill(self, reselect=None):
        """Rebuild every row. After an add, delete, move or merge."""
        self._suspend = True
        try:
            self.table.Rows.Clear()
            self.rows = {}
            for key in self.staging.order:
                entry = self.staging.entries[key]
                row = self.table.NewRow()
                row['key'] = key
                for field in ps_revisions.FIELDS:
                    row[field] = entry.fields.get(field)
                for column in self.staging.columns:
                    value = self.staging.custom_value(entry, column)
                    row['x_' + column.id] = (value == u'1') \
                        if column.kind == 'yesno' else value
                row['used'] = u'{0}'.format(entry.used)
                row['unplaced'] = u'{0}'.format(entry.unplaced)
                row['unplaced_tip'] = self._unplaced_tip(entry)
                self._fill_series(row, entry)
                row['series_open'] = self.series_open
                row['sheets_tip'] = self._sheets_tip(entry)
                self.table.Rows.Add(row)
                self.rows[key] = row
        finally:
            self._suspend = False
        self._refresh()
        if reselect:
            self._select(reselect)

    def _series_brushes(self):
        """{series: (fill, edge)} - one colour per series across the whole
        project, from the register's group palette, so BW-BUILDERSWORK is
        the same colour on every row."""
        names = []
        for entry in self.staging.entries.values():
            for name in entry.series:
                if name not in names:
                    names.append(name)
        names.sort(key=ps_revisions.ps_model.natural_key)
        found = {}
        for index, name in enumerate(names):
            found[name] = (
                theme.brush(theme.group_colour(index, self.theme_name)),
                theme.brush(theme.group_colour(index, self.theme_name,
                                               heading=True)))
        return found

    def _fill_series(self, row, entry):
        if self._colours is None:
            self._colours = self._series_brushes()
        chips = List[Object]()
        for name in entry.series:
            fill, edge = self._colours.get(
                name, (theme.brush('#808080'), theme.brush('#606060')))
            chips.Add(Tuple.Create(name, fill, edge))
        head = List[Object]()
        if chips.Count:
            head.Add(chips[0])
        row['series'] = u', '.join(entry.series)
        row['series_items'] = chips
        row['series_head'] = head
        row['series_more'] = u'+{0}'.format(len(entry.series) - 1) \
            if len(entry.series) > 1 else u''

    @staticmethod
    def _put(row, column, value):
        try:
            if u'{0}'.format(row[column]) == u'{0}'.format(value):
                return
        except Exception:
            pass
        row[column] = value

    @staticmethod
    def _unplaced_tip(entry):
        if not entry.off_views:
            return u'Every cloud of this revision is in a view on a sheet.'
        lines = [u'{0} cloud{1} in views on no sheet - right-click > Find '
                 u'clouds on views to see them:'.format(
                     entry.unplaced, u'' if entry.unplaced == 1 else u's')]
        for _view, name, count in entry.off_views[:20]:
            lines.append(u'{0} ({1})'.format(name, count))
        if len(entry.off_views) > 20:
            lines.append(u'and {0} more'.format(len(entry.off_views) - 20))
        return u'\n'.join(lines)

    @staticmethod
    def _sheets_tip(entry):
        if entry.is_new:
            return u'New - on no sheets yet'
        lines = [u'On {0} sheet{1}, {2} cloud{3}'.format(
            entry.used, u'' if entry.used == 1 else u's', entry.clouds,
            u'' if entry.clouds == 1 else u's')]
        if entry.sheets:
            shown = entry.sheets[:25]
            lines.append(u', '.join(shown) +
                         (u' and {0} more'.format(len(entry.sheets) - 25)
                          if len(entry.sheets) > 25 else u''))
        return u'\n'.join(lines)

    def _refresh(self, layout=True):
        """Every row's flags - and, unless a cell is mid-edit, its order and
        visibility - from the staging.

        Only values that differ are written. Re-sorting or re-filtering the
        view while the grid holds a row open for editing makes WPF throw,
        so an edit (``layout`` False) touches the flags and nothing the view
        sorts or filters on; the next search or move catches the rest up.
        """
        visible = set(self.staging.visible(self.filters, self.picks,
                                           self._filter_sheet())) \
            if layout else None
        self._suspend = True
        try:
            for index, key in enumerate(self.staging.order):
                row = self.rows.get(key)
                if row is None:
                    continue
                entry = self.staging.entries[key]
                changed = self.staging.changed(key)
                values = self.staging.values(key)
                # Not a column any more: the Sequence cell's tooltip.
                self._put(row, 'pending', values['pending'])
                self._put(row, 'seq', values['seq'])
                self._put(row, 'live', u'1' if entry.live else u'0')
                self._put(row, 'fresh', u'1' if entry.is_new and entry.live
                          else u'0')
                if layout:
                    self._put(row, 'ord', u'{0:05d}'.format(index))
                    self._put(row, 'vis', u'1' if key in visible else u'0')
                for field in ['seq'] + ps_revisions.FIELDS + \
                        [u'x_' + column.id for column in self.staging.columns]:
                    self._put(row, 'c_' + field, u'1' if field in changed
                              and entry.live else u'0')
        finally:
            self._suspend = False
        self._paint_settings()
        self._paint_footer()

    def _paint_settings(self):
        changed = self.staging.settings_changed()
        for radio in (self.per_project, self.per_sheet):
            if radio is None:
                continue
            try:
                radio.SetResourceReference(
                    RadioButton.ForegroundProperty,
                    'GreenBrush' if 'numbering' in changed else 'TextBrush')
            except Exception:
                pass
        if self.arc_box is not None:
            try:
                self.arc_box.SetResourceReference(
                    TextBox.BorderBrushProperty,
                    'GreenBrush' if 'arc_mm' in changed else 'EdgeBrush')
            except Exception:
                pass

    def _paint_footer(self):
        count = self.staging.change_count()
        if self.apply_button is not None:
            try:
                self.apply_button.IsEnabled = count > 0
                self.apply_button.Content = u'Apply ({0})'.format(count) \
                    if count else u'Apply'
            except Exception:
                pass
        live = len(self.staging.live_order())
        shown = len(self.staging.visible(self.filters, self.picks,
                                         self._filter_sheet()))
        total = len(self.staging.order)
        text = u'{0} revision{1}'.format(live, u'' if live == 1 else u's')
        if shown != total:
            text += u', {0} showing'.format(shown)
        text += u'. ' + (u'{0} change{1} staged - nothing is written until '
                         u'Apply.'.format(count, u'' if count == 1 else u's')
                         if count else u'Nothing staged.')
        ps_ui.set_text(self.status, text)

    def _say(self, text):
        ps_ui.set_text(self.status, text)

    def say(self, text):
        """For whoever is driving the window - the external event job."""
        self._say(text)

    def on_ui(self, call):
        """Run something on the window's thread.

        An external event's Execute runs on Revit's main thread, which is
        this window's thread too, so this is usually a straight call - but
        not a safe assumption to build on.
        """
        try:
            self.window.Dispatcher.Invoke(Action(call))
            return
        except Exception:
            pass
        try:
            call()
        except Exception:
            pass

    # ==================================================================
    # editing
    # ==================================================================

    def _cell_changed(self, sender, args):
        if self._suspend:
            return
        try:
            field = args.Column.ColumnName
            row = args.Row
        except Exception:
            return
        key = u'{0}'.format(row['key'])
        if field.startswith(u'x_') and not field.startswith(u'c_'):
            self._custom_changed(row, key, field[2:])
            return
        if field not in ps_revisions.FIELDS:
            return
        value = row[field]
        if field == 'issued':
            try:
                value = bool(value)
            except Exception:
                value = False
        ok, message = self.staging.set_field(key, field, value)
        if not ok:
            self._suspend = True
            try:
                row[field] = self.staging.entries[key].fields.get(field)
            finally:
                self._suspend = False
            self._say(message)
            return
        others = self._others(key, field)
        if others:
            self._spread(key, field, others)
        self._refresh(layout=False)

    def _custom_changed(self, row, key, column_id):
        column = self.staging.column(column_id)
        if column is None:
            return
        value = row['x_' + column_id]
        if column.kind == 'yesno':
            try:
                value = bool(value)
            except Exception:
                value = False
        ok, message = self.staging.set_custom(key, column_id, value)
        if not ok:
            stored = self.staging.custom_value(self.staging.entries[key],
                                               column)
            self._suspend = True
            try:
                row['x_' + column_id] = (stored == u'1') \
                    if column.kind == 'yesno' else stored
            finally:
                self._suspend = False
            self._say(message)
            return
        others = self._others(key, u'x_' + column_id)
        if others:
            self._spread(key, u'x_' + column_id, others)
        self._refresh(layout=False)

    def _beginning_edit(self, sender, args):
        """Refuse an edit Revit would refuse, before the editor opens."""
        # Following the selection holds off until the edit is committed: a
        # jump mid-edit would take the row out from under what is typed.
        self._editing = True
        try:
            field = u'{0}'.format(args.Column.SortMemberPath or u'')
            key = u'{0}'.format(args.Row.Item.Row['key'])
        except Exception:
            return
        entry = self.staging.entries.get(key)
        if entry is None:
            return
        refusal = u''
        if not entry.live:
            refusal = u'That revision is staged to go. Press Delete again ' \
                u'with it selected to restore it.'
        elif field != 'issued' and not field.startswith(u'x_') and \
                self.staging.locked(key):
            refusal = u'Revision {0} is issued, so Revit keeps it as it is. ' \
                u'Untick Issued to edit it.'.format(
                    self.staging.staged_sequence(key))
        if refusal:
            try:
                args.Cancel = True
            except Exception:
                pass
            self._say(refusal)

    def _current_cell(self, sender, args):
        """One click edits, as in Revit - unless Ctrl or Shift is down,
        which means the click is picking rows to move."""
        if ps_ui.ctrl_down() or ps_ui.shift_down():
            return
        try:
            column = self.grid.CurrentColumn
            if column is None or column.IsReadOnly:
                return
            self.grid.BeginEdit()
        except Exception:
            pass

    def _commit(self):
        self._editing = False
        if self.grid is None:
            return
        for _step in range(2):
            try:
                self.grid.CommitEdit()
            except Exception:
                pass

    def _selected(self):
        keys = []
        if self.grid is None:
            return keys
        try:
            for item in self.grid.SelectedItems:
                keys.append(u'{0}'.format(item.Row['key']))
        except Exception:
            pass
        return [key for key in self.staging.order if key in keys]

    def _select(self, keys, scroll=False):
        if self.grid is None:
            return
        wanted = set(keys)
        found = None
        try:
            self.grid.SelectedItems.Clear()
            for item in self.grid.Items:
                if u'{0}'.format(item.Row['key']) in wanted:
                    self.grid.SelectedItems.Add(item)
                    if found is None:
                        found = item
        except Exception:
            pass
        if scroll and found is not None:
            try:
                self.grid.ScrollIntoView(found)
            except Exception:
                pass

    def _selection_changed(self, sender, args):
        keys = self._selected()
        restoring = bool(keys) and all(
            [not self.staging.entries[key].live for key in keys])
        ps_ui.set_text(self.delete_text, u'Restore' if restoring
                       else u'Delete')

    # ==================================================================
    # the side panel
    # ==================================================================

    def _add(self, sender, args):
        """Ask for everything about the new revision - where it goes
        first - then stage it there, green, and bring it into the middle of
        the grid. Not selected: a selected row is drawn blue, and the point
        is to see it is green and waiting for Apply."""
        self._commit()
        try:
            answer = ps_revaddwin.ask(self.staging, self.theme_name,
                                      self.window)
        except Exception as err:
            self._say(u'The Add revision window would not open: {0}'
                      .format(err))
            return
        if not answer:
            self._say(u'Add revision cancelled.')
            return
        key = self.staging.add(answer['position'], answer['fields'],
                               answer['custom'])
        self._refill()
        try:
            self.grid.SelectedItems.Clear()
        except Exception:
            pass
        self._centre_on(key)
        self._say(u'Revision added at sequence {0}, in green - it is created '
                  u'on Apply.'.format(self.staging.staged_sequence(key)))

    def _fresh_row_style(self):
        style = XamlReader.Parse(FRESH_ROW_STYLE.format(PRESENTATION))
        try:
            base = self.grid.TryFindResource('GridRow')
            if base is not None:
                style.BasedOn = base
        except Exception:
            pass
        return style

    def _scroller(self):
        """The grid's own ScrollViewer, found by walking its visuals."""
        pending = [self.grid]
        for _step in range(400):
            if not pending:
                return None
            node = pending.pop(0)
            if isinstance(node, ScrollViewer):
                return node
            try:
                for index in range(VisualTreeHelper.GetChildrenCount(node)):
                    pending.append(VisualTreeHelper.GetChild(node, index))
            except Exception:
                continue
        return None

    def _centre_on(self, key):
        """Scroll the row into the middle of the grid, not to an edge.
        After layout, so the viewport measured is the real one."""
        def centre():
            index, found = 0, None
            try:
                for index, item in enumerate(self.grid.Items):
                    if u'{0}'.format(item.Row['key']) == key:
                        found = item
                        break
            except Exception:
                return
            if found is None:
                return
            try:
                self.grid.ScrollIntoView(found)
                self.grid.UpdateLayout()
            except Exception:
                pass
            viewer = self._scroller()
            if viewer is None:
                return
            try:
                # The grid scrolls by row, so the offset is in rows.
                viewer.ScrollToVerticalOffset(
                    max(0.0, float(index) - float(viewer.ViewportHeight) / 2.0
                        + 0.5))
            except Exception:
                pass
        try:
            self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background,
                                               Action(centre))
        except Exception:
            centre()

    def _delete(self, sender, args):
        self._commit()
        keys = self._selected()
        if not keys:
            self._say(u'Select the revisions to delete first.')
            return
        restoring = all([not self.staging.entries[key].live for key in keys])
        if not restoring:
            used = self.staging.in_use(keys)
            if used and not self._confirm_delete(used):
                self._say(u'Nothing deleted.')
                return
        ok, message = self.staging.delete(keys)
        self._refill([key for key in keys if key in self.staging.entries])
        self._say(message)

    def _confirm_delete(self, used):
        lines = []
        for sequence, description, sheets, clouds, unplaced in used:
            lines.append(u'Revision {0}{1}: on {2} sheet{3}, {4} cloud{5}{6}'
                         .format(sequence, u' - ' + description if description
                                 else u'', sheets, u'' if sheets == 1 else u's',
                                 clouds, u'' if clouds == 1 else u's',
                                 u' ({0} in views on no sheet - right-click > '
                                 u'Find clouds on views)'.format(unplaced)
                                 if unplaced else u''))
        answer = ps_ui.Prompt(
            title=u'Revision Manager',
            headline=u'{0} of these revision{1} in use.'.format(
                len(used), u' is' if len(used) == 1 else u's are'),
            message=u'Are you sure? Deleting a revision takes it off every '
                    u'sheet that carries it, and its revision clouds go with '
                    u'it. Nothing happens until Apply, and it can be restored '
                    u'until then.',
            detail=u'\n'.join(lines),
            primary=u'Delete', secondary=u'Keep',
            theme_name=self.theme_name, owner=self.window).show()
        return answer == 'primary'

    def _move(self, step):
        self._commit()
        keys = self._selected()
        if not keys:
            self._say(u'Select the revisions to move. Ctrl or Shift click to '
                      u'select several.')
            return
        if self.staging.move(keys, step):
            self._refill(keys)
            self._say(u'{0} revision{1} moved {2}.'.format(
                len(keys), u'' if len(keys) == 1 else u's',
                u'up' if step < 0 else u'down'))
        else:
            self._say(u'Already at the {0}.'.format(
                u'top' if step < 0 else u'bottom'))

    def _merge(self, step):
        self._commit()
        keys = self._selected()
        if len(keys) != 1:
            self._say(u'Select one revision to merge.')
            return
        ok, message = self.staging.merge(keys[0], step)
        if ok:
            self._refill(keys)
        self._say(message)

    # ------------------------------------------------------------ columns
    def _column_dialog(self, column=None, group=u''):
        return ps_revcolwin.ColumnDialog(
            self.staging.columns, column, self._lookup,
            self.theme_name, self.window, group).show()

    def _parameters(self):
        try:
            return list(self.parameter_reader()) if self.parameter_reader \
                else []
        except Exception:
            return []

    def _lookup(self, target):
        """[(name, data)] the column dialog offers for a target."""
        return ps_revdata.usable(self._parameters(), target)

    def _open_settings(self, sender, args):
        """The settings: the model's own columns and their mapping."""
        self._commit()
        answer = ps_revsetwin.SettingsDialog(
            self.staging.columns, self._parameters, self.theme_name,
            self.window).show()
        if not answer:
            return
        problems = []
        for column_id, name, target, parameter in answer['columns']:
            column = self.staging.column(column_id)
            if column is None:
                continue
            ok, message = self.staging.update_column(
                column_id, name, column.choices, target, parameter)
            if not ok:
                problems.append(message)
        self._rebuild(self._selected())
        if problems:
            self._say(u' '.join(problems))
        elif self.staging.columns_changed():
            self._say(u'Column settings staged - written on Apply.')
        if answer.get('action') == 'project_parameters':
            self._to_project_parameters()

    def _to_project_parameters(self):
        """Close, and have Revit open Project Parameters.

        Revit runs a posted command only once the tool hands control back,
        so the manager closes first. Staged changes are applied on the way
        out, or left - the user says which.
        """
        plan = None
        if self.staging.dirty():
            answer = ps_ui.Prompt(
                title=u'Revision Manager',
                headline=u'Project Parameters opens when this window closes.',
                message=u'{0} change{1} staged here. Apply them on the way '
                        u'out, or leave them? Close this message to stay in '
                        u'the manager.'.format(
                            self.staging.change_count(),
                            u' is' if self.staging.change_count() == 1
                            else u's are'),
                primary=u'Apply, then open', secondary=u'Leave them, open',
                theme_name=self.theme_name, owner=self.window).show()
            if answer == 'primary':
                plan = self.staging.plan()
                if ps_revisions.plan_is_empty(plan):
                    plan = None
            elif answer != 'secondary':
                return
        self.post_command = 'ProjectParameters'
        self.result = plan
        self._close(plan is not None)

    def _add_column(self, sender, args, group=u''):
        self._commit()
        answer = self._column_dialog(None, group)
        if not answer or answer.get('action') != 'save':
            return
        ok, found = self.staging.add_column(
            answer['name'], answer['kind'], answer['choices'],
            answer['target'], answer['parameter'], answer.get('group', u''))
        if not ok:
            self._say(found)
            return
        self._rebuild(self._selected())
        self._say(u'Column "{0}" added. It is saved to the model on Apply.'
                  .format(answer['name']))

    def _make_edit_column(self, column_id):
        def clicked(sender, args):
            self._edit_column(column_id)
        return clicked

    def _edit_column(self, column_id):
        self._commit()
        column = self.staging.column(column_id)
        if column is None:
            return
        answer = self._column_dialog(column)
        if not answer:
            return
        if answer.get('action') == 'remove':
            filled = len([1 for entry in self.staging.entries.values()
                          if self.staging.custom_value(entry, column)
                          not in (u'', u'0')])
            if filled and ps_ui.Prompt(
                    title=u'Revision Manager',
                    headline=u'Remove "{0}"?'.format(column.name),
                    message=u'{0} revision{1} {2} a value in it. The column '
                            u'and its values leave the model on Apply; the '
                            u'parameters it was pushed into keep what they '
                            u'hold.'.format(filled,
                                            u'' if filled == 1 else u's',
                                            u'has' if filled == 1 else u'have'),
                    primary=u'Remove', secondary=u'Keep',
                    theme_name=self.theme_name,
                    owner=self.window).show() != 'primary':
                return
            self.staging.remove_column(column_id)
            self._rebuild(self._selected())
            self._say(u'Column "{0}" removed on Apply.'.format(column.name))
            return
        ok, message = self.staging.update_column(
            column_id, answer['name'], answer['choices'], answer['target'],
            answer['parameter'], answer.get('group'))
        if not ok:
            self._say(message)
            return
        self._rebuild(self._selected())
        self._say(u'Column "{0}" changed.'.format(answer['name']))

    def _push(self, sender, args):
        """Stage a push of every mapped column, with nothing else changed."""
        self._commit()
        pushed = [column for column in self.staging.columns if column.pushed]
        if not pushed:
            self._say(u'No column is mapped to a parameter yet - use the '
                      u'pencil on a column\'s heading to map one.')
            return
        self.staging.push_requested = True
        self._refresh()
        self._say(u'{0} column{1} will be pushed on Apply: {2}.'.format(
            len(pushed), u'' if len(pushed) == 1 else u's',
            u', '.join([u'{0} -> "{1}"'.format(column.name, column.parameter)
                        for column in pushed])))

    def _make_numbering(self, mode):
        def checked(sender, args):
            if self._suspend:
                return
            self.staging.set_setting('numbering', mode)
            self._refresh()
        return checked

    def _arc_changed(self, sender, args):
        if self._suspend:
            return
        text = u'{0}'.format(self.arc_box.Text or u'').strip()
        if not self.staging.set_setting('arc_mm', text):
            self._say(u'Arc length has to be a number above 0, in mm.')
            return
        self._refresh()

    def _clear_searches(self, sender, args):
        """Clear filters: every search box empty and every value list back
        to everything ticked."""
        for box in self.search_boxes:
            try:
                box.Text = u''
            except Exception:
                pass
        for field in list(self.picks.keys()):
            self.picks.pop(field, None)
            self._paint_filter_button(field)
        self._refresh()

    def _key_down(self, sender, args):
        """Ctrl+Up and Ctrl+Down move the selection - not while a filter
        list is open, whose keys come through the grid on their way."""
        if self._filter_open:
            return
        try:
            key = args.Key
        except Exception:
            return
        if not ps_ui.ctrl_down() or key not in (Key.Up, Key.Down):
            return
        self._move(-1 if key == Key.Up else 1)
        args.Handled = True

    # ==================================================================
    # theme, apply, cancel
    # ==================================================================

    def _say_theme(self):
        ps_ui.set_content(self.theme_chip, u'Light'
                          if self.theme_name == 'light' else u'Dark')

    def _toggle_theme(self, sender, args):
        self.theme_name = 'light' if self.theme_name == 'dark' else 'dark'
        try:
            theme.apply(self.window, self.theme_name)
        except Exception:
            pass
        self._say_theme()
        # The series chips carry palette colours of their own.
        self._commit()
        self._colours = None
        self._refill(self._selected())

    # ------------------------------------------------- the right-click menu
    def _right_press(self, sender, args):
        """A right-click on a row not selected selects it first, so the
        menu acts on what is under the pointer."""
        try:
            row = self._ancestor(args.OriginalSource, DataGridRow)
            if row is None or row.IsSelected:
                return
            self.grid.SelectedItems.Clear()
            row.IsSelected = True
        except Exception:
            pass

    def _right_release(self, sender, args):
        try:
            if self._ancestor(args.OriginalSource, DataGridRow) is None:
                return
            menu = ContextMenu()
            menu.SetResourceReference(ContextMenu.StyleProperty,
                                      'ThemedContextMenu')
            for entry in self.menu_entries():
                if entry is None:
                    menu.Items.Add(Separator())
                    continue
                text, action, enabled = entry
                item = MenuItem()
                item.SetResourceReference(MenuItem.StyleProperty,
                                          'ThemedMenuItem')
                item.Header = text
                item.IsEnabled = enabled
                item.Click += self._make_menu_click(action)
                menu.Items.Add(item)
            menu.PlacementTarget = self.grid
            menu.IsOpen = True
            args.Handled = True
        except Exception:
            pass

    def _make_menu_click(self, action):
        def clicked(sender, args):
            getattr(self, action)()
        return clicked

    def menu_entries(self):
        """[(text, method name, enabled)] or None for a separator."""
        keys = self._selected()
        entries = [self.staging.entries[key] for key in keys
                   if key in self.staging.entries]
        views, _lines = views_report(entries)
        off = sum([entry.unplaced for entry in entries])
        return [(u'Find clouds on views ({0} view{1}{2})...'.format(
                    len(views), u'' if len(views) == 1 else u's',
                    u', {0} cloud{1} off sheets'.format(
                        off, u'' if off == 1 else u's') if off else u''),
                 'find_clouds', bool(views)),
                None,
                (u'Delete' if not entries or
                 [one for one in entries if one.live] else u'Restore',
                 'delete_selected', bool(entries))]

    def delete_selected(self):
        self._delete(None, None)

    def find_clouds(self):
        """Open every view holding the selected revisions' clouds, with
        the clouds isolated in each."""
        self._commit()
        keys = [key for key in self._selected()
                if key in self.staging.entries]
        entries = [self.staging.entries[key] for key in keys]
        views, lines = views_report(entries)
        if not views:
            self._say(u'No clouds of those revisions in any view.')
            return
        if len(views) > OPEN_LIMIT and ps_ui.Prompt(
                title=u'Find clouds on views',
                headline=u'Open {0} views?'.format(len(views)),
                message=u'Each opens with the revision clouds isolated in '
                        u'it. That is a lot of views to have open at once.',
                detail=u'\n'.join(lines),
                primary=u'Open them', secondary=u'Cancel',
                theme_name=self.theme_name,
                owner=self.window).show() != 'primary':
            return
        if self.on_find is not None:
            self._say(u'Opening {0} view{1}...'.format(
                len(views), u'' if len(views) == 1 else u's'))
            self.on_find(views)
            return
        # Opened from the register: Revit is only reachable once this
        # window has closed, so the views open then.
        plan = None
        if self.staging.dirty():
            answer = ps_ui.Prompt(
                title=u'Find clouds on views',
                headline=u'The views open when this window closes.',
                message=u'{0} change{1} staged here. Apply them on the way '
                        u'out, or leave them? Close this message to stay.'
                        .format(self.staging.change_count(),
                                u' is' if self.staging.change_count() == 1
                                else u's are'),
                primary=u'Apply, then open', secondary=u'Leave them, open',
                theme_name=self.theme_name, owner=self.window).show()
            if answer == 'primary':
                plan = self.staging.plan()
                if ps_revisions.plan_is_empty(plan):
                    plan = None
            elif answer != 'secondary':
                return
        self.find_request = views
        self.result = plan
        self._close(plan is not None)

    def _apply(self, sender, args):
        self._commit()
        plan = self.staging.plan()
        if ps_revisions.plan_is_empty(plan):
            self._say(u'Nothing to apply.')
            return
        self.result = plan
        if self.on_apply is not None:
            # Modeless: the window stays, the plan goes out through an
            # external event, and the window is refreshed when it returns.
            self._say(u'Applying...')
            self.on_apply(plan)
            return
        self._close(True)

    def _cancel(self):
        self._commit()
        if self.staging.dirty():
            answer = ps_ui.Prompt(
                title=u'Revision Manager',
                headline=u'Discard {0} staged change{1}?'.format(
                    self.staging.change_count(),
                    u'' if self.staging.change_count() == 1 else u's'),
                message=u'None of them have been written to the model.',
                primary=u'Discard', secondary=u'Keep editing',
                theme_name=self.theme_name, owner=self.window).show()
            if answer != 'primary':
                return
        self.result = None
        self._close(False)

    def _close(self, ok):
        if not self.modeless:
            # Only a window shown with ShowDialog has a DialogResult;
            # setting it on a modeless one throws.
            try:
                self.window.DialogResult = bool(ok)
            except Exception:
                pass
        self.stop_watching()
        try:
            self.window.Close()
        except Exception:
            pass

    def close_now(self):
        """Shut the window from outside - the job that applied the last
        change with "reopen after Apply" turned off."""
        self._close(True)

    def reload(self, staging, status=u''):
        """Take a freshly read staging, keeping the window as it is: the
        theme, the column order, the widths and the value filters all
        belong to the window, not to the model."""
        self.staging = staging
        self._colours = None
        self._token = None
        self._rebuild()
        if status:
            self._say(status)

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            pass
        return self.result

    def show_modeless(self):
        try:
            self.window.Show()
        except Exception:
            raise
        return self


# ==========================================================================
# on its own, from the Revision Manager ribbon button
# ==========================================================================

class RevisionHandler(IExternalEventHandler):
    """Runs one queued revision job on Revit's API thread."""

    def __init__(self):
        self.work = None

    def Execute(self, uiapp):
        work = self.work
        self.work = None
        if work is None:
            return
        try:
            work(uiapp)
        except Exception:
            pass

    def GetName(self):
        return 'RevoBIM Revision Manager'


# Parked at module level for the reason ps_window parks its own: pyRevit's
# persistent engine collects whatever it does not consider referenced, and
# it would take the live window - and the Idling handler subscribed to
# Revit - with it.
MANAGER = None
HANDLER = None
EVENT = None


def run_standalone(uiapp):
    """The manager on its own, from its ribbon button, **modeless**: Revit
    stays fully usable while it is open.

    Modeless changes three things, and all three are the usual way a
    modeless Revit tool is wrong:

    - **Apply cannot write where it stands.** A modeless window is in no
      API context, so the plan goes out through an ``ExternalEvent`` and
      the window refreshes itself when the write comes back. The same rule
      as the main window's exports.
    - **The window has to outlive the command.** That is what
      ``__persistentengine__`` in this button's script.py buys, and what
      the module-level references above keep alive.
    - **Reading the model needs a valid context too.** Following the
      selection is done in Revit's ``Idling`` event, which is raised on
      Revit's main thread inside one.
    """
    global MANAGER, HANDLER, EVENT

    if MANAGER is not None:
        # Already open: bring it forward rather than opening a second one
        # over the same model with its own staged changes.
        try:
            MANAGER.window.Activate()
            return MANAGER
        except Exception:
            MANAGER = None
    if HANDLER is None:
        HANDLER = RevisionHandler()
    if EVENT is None:
        EVENT = ExternalEvent.Create(HANDLER)

    doc = uiapp.ActiveUIDocument.Document
    settings = None
    try:
        settings = ps_config.Settings()
        theme_name = theme.resolve(theme.mode(settings.text('theme_mode')))
    except Exception:
        theme_name = theme.resolve('follow')
    series_param, status_param, reopen = u'', u'', True
    if settings is not None:
        try:
            series_param = settings.text('param_series', u'')
            status_param = settings.text('reg_status_param', u'')
            # Modeless, "reopen after Apply" means "stay open, refreshed";
            # off, the window closes once the change is in.
            reopen = settings.flag('rev_reopen', True)
        except Exception:
            pass

    def reader():
        return ps_revdata.bound_parameters(doc)

    # Read here, in the command's own API context: the revision of any cloud
    # selected before opening, and the sheet open in Revit.
    uidoc = uiapp.ActiveUIDocument
    focus = ps_revisions.selected_revision_keys(uidoc)
    try:
        current_sheet = ps_revisions.sheet_number_of(uidoc.ActiveView)
    except Exception:
        current_sheet = None
    manager = RevisionManager(ps_revisions.read(doc, series_param,
                                                status_param),
                              theme_name, None, reader, u'',
                              uiapp.MainWindowHandle, settings,
                              modeless=True, focus=focus,
                              current_sheet=current_sheet)
    # Idling should not take the starting view or selection as a change.
    manager._token = ps_revisions.selection_token(uidoc)
    try:
        manager._view_token = u'{0}'.format(
            ps_revisions.ps_model.eid_value(uidoc.ActiveView.Id))
    except Exception:
        pass

    def apply_plan(plan):
        """Apply, from the window's thread. Nothing here touches Revit."""

        def job(event_uiapp):
            """On Revit's API thread, inside its context."""
            done, errors = ps_revisions.write(doc, plan)
            status = u'{0} change{1} applied to the model.'.format(
                done, u'' if done == 1 else u's')
            if errors:
                status += u' {0} could not be.'.format(len(errors))
            post = manager.post_command
            fresh = None
            if reopen and not post:
                # Read it back here, still inside the context.
                try:
                    fresh = ps_revisions.read(doc, series_param,
                                              status_param)
                except Exception:
                    fresh = None

            def back():
                if post or not reopen:
                    manager.close_now()
                elif fresh is not None:
                    manager.reload(fresh, status)
                else:
                    manager.say(status + u' Reopen the manager to see the '
                                u'model as it now is.')
                if errors:
                    ps_ui.Prompt(
                        title=u'Revision Manager',
                        headline=u'{0} change{1} Revit would not '
                                 u'make.'.format(
                                     len(errors),
                                     u'' if len(errors) == 1 else u's'),
                        message=u'The rest were applied.',
                        detail=u'\n'.join(errors), primary=u'Close',
                        theme_name=manager.theme_name).show()

            manager.on_ui(back)
            if post:
                # The window has gone; now Revit's own dialog.
                post_command(event_uiapp, post)

        HANDLER.work = job
        try:
            EVENT.Raise()
        except Exception as err:
            manager.say(u'Revit would not take the job: {0}'.format(err))

    manager.on_apply = apply_plan

    def find_clouds(views):
        """Find clouds on views, from the window's thread: open each view
        with its clouds isolated - on Revit's thread, through the event."""

        def job(event_uiapp):
            try:
                result = ps_revisions.show_clouds(
                    event_uiapp.ActiveUIDocument, views)
            except Exception as err:
                result = (0, 0, [u'{0}'.format(err)])
            manager.on_ui(lambda: manager.say(
                ps_revisions.clouds_report(*result)))

        HANDLER.work = job
        try:
            EVENT.Raise()
        except Exception as err:
            manager.say(u'Revit would not take the job: {0}'.format(err))

    manager.on_find = find_clouds

    def forget(sender, args):
        global MANAGER
        MANAGER = None
        try:
            if settings is not None:
                settings.set('theme_mode', manager.theme_name)
                settings.save()
        except Exception:
            pass

    try:
        manager.window.Closed += forget
    except Exception:
        pass

    MANAGER = manager
    manager.watch_selection(uiapp)
    manager.show_modeless()
    return manager


def post_command(uiapp, name):
    """Ask Revit to run one of its own commands - Project Parameters -
    as soon as the tool hands control back."""
    try:
        from Autodesk.Revit.UI import PostableCommand, RevitCommandId
        uiapp.PostCommand(RevitCommandId.LookupPostableCommandId(
            getattr(PostableCommand, name)))
        return True
    except Exception:
        return False
