# -*- coding: utf-8 -*-
"""The Document Register tab: drawing it, choosing what is in it, exporting it.

Every sheet down the page and every revision across it, in the Drawing
Register's layout - frozen drawing columns on the left, one column per
revision with its date rotated up the header and the issue status letter
under it in blue, the sheet's current revision picked out in orange. One tab
per discipline along the bottom; series headings that collapse.

**A tick here means "in the register", not "print".** Printing is the
Selection tab's job, and 1.20.0 sharing one list of ticks between the two
turned out to be the wrong model: the drawings that belong on a register are
not the ones being printed today. So the register keeps its own list -
``self.included`` - and nothing here touches the Selection tab's ticks.

**What is included is driven by a Revit View/Sheet Set.** Choosing a set in
the drop-down ticks exactly the sheets in it. Changing the ticks makes the
set "dirty" and lights Apply, which writes the ticks back into the set
through the external event. **+** starts a new set: named first, ticked
second, written on Save. With no set chosen the ticks are kept per project in
a file of their own, as the sheets left *out* - so a sheet added to the model
later starts included rather than silently missing from the register.

**Nothing moves under the cursor.** Unticking a sheet while "Included only"
is showing turns it pale rather than whisking it away; the view catches up
on the next filter, toggle or F5. Same rule as every other RevoBIM table.

**A revision header is a button.** Clicking it isolates the sheets carrying
that revision (1.42.0 - before that it ticked them into the register, which
read as a change from a click meant as "show me"). Ctrl+click isolates
several; a second click shows every sheet. The Sorting event is where the
click arrives, and it is always cancelled: a register has one order.

**The sequence number at the top of a revision column picks it** (1.39.0) -
a Button, so its click is its own and never reaches the date's include.
Ctrl and Shift pick several, Excel's way. A picked column washes orange and
lights *Isolate sheets with this revision*, which shows only the drawings
carrying any of them until it is pressed again.

**A revision cell can be picked too.** Click one, Ctrl or Shift for more;
the cell turns into an orange chip and the picked-cell toolset appears:
*Change revision* and *Remove revision* (1.40.0).
Picking is the register's own state, on a ``p_<column>`` flag per row and a
DataTrigger - the grid's row selection is untouched, so the tick and the
multi-row include work exactly as before.

**Filters are Excel's.** The button under each heading opens a list of every
value in that column - what the other filters leave, the way Excel does it -
with "(Blanks)" at the end, All and None, a search box, and OK. Nothing is
applied until OK, so the grid does not reshape while the list is open.

**Headings are coloured like the Selection tab's groups**: a band on the
heading, a wash on its drawings, from the same palette. The All tab is
grouped by discipline and then by series; a discipline's colour is the same
on its heading, its swatch and its tab along the bottom.

**Columns fit their text.** Measured once per tab with a TextBlock and frozen
in pixels, between a floor that keeps the filter box usable and a ceiling.
Never left on Auto, which re-measures as rows are realised and shifts the
columns under the reader halfway down the list.
"""

import ps_refs  # noqa: F401  - must be first

import os

from System import Boolean, Object, String, TimeSpan
from System.Data import DataTable
from System.Windows import (CornerRadius, FontWeights, HorizontalAlignment,
                            Point, Size, TextTrimming, Thickness,
                            VerticalAlignment, Visibility)
from System.Windows.Controls import (Border, Button, Canvas, CheckBox,
                                     ContextMenu, Image,
                                     DataGridCell, DataGridLength,
                                     DataGridRow, DataGridTemplateColumn,
                                     DataGridTextColumn, MenuItem,
                                     Orientation, Separator,
                                     ScrollBarVisibility, ScrollViewer,
                                     StackPanel, TextBlock, TextBox,
                                     WrapPanel)
from System.Windows.Controls.Primitives import (DataGridColumnHeader,
                                                PlacementMode, Popup)
from System.Windows.Data import Binding
from System.Windows.Input import Cursors, Key, Keyboard
from System.Windows.Markup import XamlReader
from System.Windows.Media import (Brushes, FontFamily, RotateTransform,
                                  Stretch, VisualTreeHelper)
from System.Windows.Threading import DispatcherTimer

import ps_config
import ps_export
import ps_model
import ps_ramp
import ps_regexport
import ps_register
import ps_revdata
import ps_revaddwin
import ps_revisions
import ps_revswapwin
import ps_revwin
import ps_ui
import theme


PRESENTATION = 'http://schemas.microsoft.com/winfx/2006/xaml/presentation'

# The first entry in the set list: ticks made by hand, kept per project.
BY_HAND = u'(no set - tick by hand)'
# A set that has been named but not yet written to the model.
NEW_MARK = u'  (new, not saved)'

EXPANDED = u'▾  '
COLLAPSED = u'▸  '

# A revision cell: centred, orange and bold where it is the sheet's current
# revision, and faded where the sheet is not in the register. Parsed rather
# than built, because the orange has to be a DynamicResource to flip with the
# palette and a Setter built in code cannot carry one. One style per column,
# cached: the DataTrigger compares the row's "curkey" with this column's key.
CELL_STYLE = (
    u'<Style xmlns="{0}" TargetType="TextBlock">'
    u'<Setter Property="HorizontalAlignment" Value="Center"/>'
    u'<Setter Property="VerticalAlignment" Value="Center"/>'
    u'<Style.Triggers>'
    u'<DataTrigger Binding="{{Binding curkey}}" Value="{1}">'
    u'<Setter Property="Foreground" Value="{{DynamicResource OrangeBrush}}"/>'
    u'<Setter Property="FontWeight" Value="Bold"/>'
    u'</DataTrigger>'
    u'<DataTrigger Binding="{{Binding sel}}" Value="False">'
    u'<Setter Property="Opacity" Value="0.55"/>'
    u'</DataTrigger>'
    # Staged by the register and not yet applied: a cell gaining the
    # revision is green with a +, one losing it red and struck through.
    u'<DataTrigger Binding="{{Binding s_{1}}}" Value="add">'
    u'<Setter Property="Background" Value="{{DynamicResource GreenWashBrush}}"/>'
    u'<Setter Property="Foreground" Value="{{DynamicResource GreenBrush}}"/>'
    u'<Setter Property="FontWeight" Value="Bold"/>'
    u'<Setter Property="Padding" Value="6,1"/>'
    u'<Setter Property="Opacity" Value="1"/>'
    u'</DataTrigger>'
    u'<DataTrigger Binding="{{Binding s_{1}}}" Value="del">'
    u'<Setter Property="Foreground" Value="{{DynamicResource RedBrush}}"/>'
    u'<Setter Property="TextDecorations" Value="Strikethrough"/>'
    u'<Setter Property="Opacity" Value="1"/>'
    u'</DataTrigger>'
    # Picked for Change revision on sheet: a solid orange chip. Last, so it
    # wins over the two above - a picked cell has to look picked even on
    # the sheet's current revision, and even on a drawing left out.
    u'<DataTrigger Binding="{{Binding p_{1}}}" Value="1">'
    u'<Setter Property="Background" Value="{{DynamicResource OrangeBrush}}"/>'
    u'<Setter Property="Foreground" Value="{{DynamicResource OnOrangeBrush}}"/>'
    u'<Setter Property="FontWeight" Value="Bold"/>'
    u'<Setter Property="Padding" Value="6,1"/>'
    u'<Setter Property="Opacity" Value="1"/>'
    u'</DataTrigger>'
    u'</Style.Triggers>'
    u'</Style>')

# A revision column picked by its sequence number: an orange wash down the
# whole column. Parsed here, then BasedOn the grid's RegisterCell in code -
# a StaticResource cannot be resolved outside the window, and a CellStyle
# that is not based on it would lose the template and the muted rows.
PICKED_COLUMN_STYLE = (
    u'<Style xmlns="{0}" TargetType="DataGridCell">'
    u'<Setter Property="Background" Value="{{DynamicResource PickWashBrush}}"/>'
    u'</Style>')

# A revision just created through the Revision Manager: a green wash down
# its column, so the eye goes straight to it. Built like the picked wash.
FRESH_COLUMN_STYLE = (
    u'<Style xmlns="{0}" TargetType="DataGridCell">'
    u'<Setter Property="Background" Value="{{DynamicResource GreenWashBrush}}"/>'
    u'</Style>')

# The line where the drawing columns end and the revisions begin: a
# column of its own, three pixels of blue top to bottom. Its heading and its
# cells are templates with nothing in them but the colour - the register's
# own heading has padding, and a cell its gridline and margin.
DIVIDER_HEADER_STYLE = (
    u'<Style xmlns="{0}" TargetType="DataGridColumnHeader">'
    u'<Setter Property="Template"><Setter.Value>'
    u'<ControlTemplate TargetType="DataGridColumnHeader">'
    u'<Border Background="{{DynamicResource BlueBrush}}"/>'
    u'</ControlTemplate></Setter.Value></Setter></Style>')
DIVIDER_CELL_STYLE = (
    u'<Style xmlns="{0}" TargetType="DataGridCell">'
    u'<Setter Property="Template"><Setter.Value>'
    u'<ControlTemplate TargetType="DataGridCell">'
    u'<Border Background="{{DynamicResource BlueBrush}}"/>'
    u'</ControlTemplate></Setter.Value></Setter>'
    # Not across a heading's pill: it would cut it in two.
    u'<Style.Triggers><DataTrigger Binding="{{Binding ishead}}" Value="1">'
    u'<Setter Property="Opacity" Value="0"/></DataTrigger></Style.Triggers>'
    u'</Style>')
EMPTY_CELL = (u'<DataTemplate xmlns="{0}"><TextBlock/></DataTemplate>')

# The green + at the end of the revisions: a new revision.
# A discipline tab's icon; its fill follows the tab button's text colour.
TAB_ICON_XAML = (
    u'<Path xmlns="{0}" Width="14" Height="14" Stretch="Uniform"'
    u' Margin="0,0,7,0" VerticalAlignment="Center" IsHitTestVisible="False"'
    u' Fill="{{Binding Foreground, RelativeSource={{RelativeSource'
    u' FindAncestor, AncestorType=Button}}}}" Data="{1}"/>')

PLUS_ICON = (
    u'<Path xmlns="{0}" Width="14" Height="14" Stretch="Uniform"'
    u' Fill="{{DynamicResource GreenBrush}}"'
    u' Data="M 5,0 L 7,0 L 7,5 L 12,5 L 12,7 L 7,7 L 7,12 L 5,12 L 5,7 L 0,7'
    u' L 0,5 L 5,5 Z"/>')

# The key of an issue data row, when the block scrolls with the drawings
# (1.53.0): ISSUE_PREFIX + the Revision Manager column's id. Never a sheet.
ISSUE_PREFIX = u'issue:'

# The per-row flag that marks a revision cell picked: p_<column key>.
PICK_PREFIX = 'p_'

# The per-row flag that marks a revision cell staged and not yet applied:
# s_<column key>, 'add' or 'del' (see ps_register.pending_flags).
PENDING_PREFIX = 's_'

CENTRED_STYLE = (
    u'<Style xmlns="{0}" TargetType="TextBlock">'
    u'<Setter Property="HorizontalAlignment" Value="Center"/>'
    u'<Setter Property="VerticalAlignment" Value="Center"/>'
    u'</Style>')

# The Rev column: each drawing's current revision, bold and blue so it reads
# as the answer the row gives. Faded like the rest of the row where the
# drawing is out of the register - a fixed Foreground on the TextBlock would
# otherwise beat the cell's muted colour and the row would look half in.
CURRENT_STYLE = (
    u'<Style xmlns="{0}" TargetType="TextBlock">'
    u'<Setter Property="HorizontalAlignment" Value="Center"/>'
    u'<Setter Property="VerticalAlignment" Value="Center"/>'
    u'<Setter Property="FontWeight" Value="Bold"/>'
    u'<Setter Property="Foreground" Value="{{DynamicResource BlueBrush}}"/>'
    u'<Style.Triggers>'
    u'<DataTrigger Binding="{{Binding sel}}" Value="False">'
    u'<Setter Property="Opacity" Value="0.55"/>'
    u'</DataTrigger>'
    u'</Style.Triggers>'
    u'</Style>')


class RegisterView(object):

    # id, heading, the narrowest it may be. The floor is not cosmetic: a
    # heading carries a filter box, and a narrower column clips its own
    # controls.
    IDENTITY = [
        ('sel', u'', 44),
        ('num', u'Drawing No', 96),
        ('name', u'Drawing Title', 170),
        ('size', u'Size', 58),
        ('scale', u'Scale', 62),
        ('rev', u'Rev', 52),
        # The current revision's sequence number. On screen only: the RD9
        # sheet has no column for it, so the Excel export leaves it out.
        ('seq', u'Seq No', 60),
        ('rdate', u'Rev Date', 80),
    ]
    CENTRED = ('size', 'scale', 'rev', 'seq', 'rdate')
    CEILINGS = {'name': 720, 'num': 520}
    DEFAULT_CEILING = 360

    # Wide enough for "P02" in bold plus the cell padding, and for a filter
    # box you can type a letter into. 34px clipped the codes in 1.20.0.
    REVISION_FLOOR = 48
    REVISION_CEILING = 110

    SEARCH_MS = 220

    # The register's own tick: the Selection tab's, plus a trigger that
    # hides it on a row whose ``hidetick`` is 1. Hidden rather than
    # collapsed, so the column keeps its width and nothing shifts sideways.
    TICK_TEMPLATE = (
        u'<DataTemplate '
        u'xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
        u'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
        u'<CheckBox x:Name="Tick" Style="{DynamicResource GridCheckBox}" '
        u'IsChecked="{Binding sel, Mode=TwoWay, '
        u'UpdateSourceTrigger=PropertyChanged}"/>'
        u'<DataTemplate.Triggers>'
        u'<DataTrigger Binding="{Binding hidetick}" Value="1">'
        u'<Setter TargetName="Tick" Property="Visibility" Value="Hidden"/>'
        u'</DataTrigger>'
        u'</DataTemplate.Triggers>'
        u'</DataTemplate>')

    def __init__(self, host):
        self.host = host
        self.window = host.window
        self.grid = ps_ui.find(self.window, 'RegisterGrid')
        self.tab_strip = ps_ui.find(self.window, 'RegisterTabs')
        self.search_box = ps_ui.find(self.window, 'RegisterSearch')
        self.summary = ps_ui.find(self.window, 'RegisterSummary')
        self.source = ps_ui.find(self.window, 'RegisterSource')
        self.note = ps_ui.find(self.window, 'RegisterNote')
        self.root = ps_ui.find(self.window, 'RegisterRoot')
        self.set_combo = ps_ui.find(self.window, 'RegisterSetCombo')
        self.apply_button = ps_ui.find(self.window, 'RegisterApplyButton')
        self.show_all_button = ps_ui.find(self.window, 'RegisterShowAllButton')
        self.show_included_button = ps_ui.find(self.window,
                                               'RegisterShowIncludedButton')
        self.collapse_button = ps_ui.find(self.window, 'RegisterCollapseButton')
        self.heading_mode_button = ps_ui.find(self.window,
                                              'RegisterHeadingModeButton')
        self.heading_mode_text = ps_ui.find(self.window,
                                            'RegisterHeadingModeText')
        self.label_canvas = ps_ui.find(self.window, 'RegisterIssueLabels')
        self.freeze_button = ps_ui.find(self.window, 'RegisterFreezeButton')
        self.freeze_text = ps_ui.find(self.window, 'RegisterFreezeText')
        self.reset_button = ps_ui.find(self.window,
                                       'RegisterResetFiltersButton')
        self.reset_text = ps_ui.find(self.window, 'RegisterResetFiltersText')
        self.export_check = ps_ui.find(self.window, 'RegisterAddToExport')
        self.all_revs_button = ps_ui.find(self.window, 'RegisterAllRevsButton')
        self.collapse_text = ps_ui.find(self.window, 'RegisterCollapseText')
        self.collapse_icon = ps_ui.find(self.window, 'RegisterCollapseIcon')
        self.expand_icon = ps_ui.find(self.window, 'RegisterExpandIcon')
        self.isolate_button = ps_ui.find(self.window, 'RegisterIsolateButton')
        self.isolate_text = ps_ui.find(self.window, 'RegisterIsolateText')
        self.change_button = ps_ui.find(self.window,
                                        'RegisterChangeRevButton')
        self.change_text = ps_ui.find(self.window, 'RegisterChangeRevText')
        self.remove_button = ps_ui.find(self.window,
                                        'RegisterRemoveRevButton')
        self.create_button = ps_ui.find(self.window,
                                        'RegisterCreateRevButton')
        self.edit_button = ps_ui.find(self.window, 'RegisterEditRevButton')
        self.sheet_tools = ps_ui.find(self.window, 'RegisterSheetTools')
        self.sheet_tools_text = ps_ui.find(self.window,
                                           'RegisterSheetToolsText')
        self.assign_button = ps_ui.find(self.window,
                                        'RegisterAssignRevButton')
        self.cell_tools = ps_ui.find(self.window, 'RegisterCellTools')
        self.undo_button = ps_ui.find(self.window, 'RegisterUndoButton')
        self.redo_button = ps_ui.find(self.window, 'RegisterRedoButton')
        self.apply_revs_button = ps_ui.find(self.window,
                                            'RegisterApplyRevsButton')
        self.apply_revs_text = ps_ui.find(self.window, 'RegisterApplyRevsText')
        self.discard_button = ps_ui.find(self.window,
                                         'RegisterDiscardRevsButton')
        self.cell_tools_text = ps_ui.find(self.window,
                                          'RegisterCellToolsText')

        self.revisions = []
        self.rows = []
        self.rows_by_key = {}
        self.elements = {}
        self.tabs = []
        self.tab_buttons = []
        self.tab_checks = []
        self.tab_texts = []
        self.tab_index = 0
        self.tab_label = ps_register.ALL_TAB
        self.used_columns = []
        self.columns = {}
        # heading id -> the keys of every drawing under it, sub-groups too
        self.groups = {}
        # heading id -> "Mechanical" or "Mechanical/570": what folds
        self.group_paths = {}
        # heading id -> the heading above it, for a series under a discipline
        self.group_parent = {}
        # discipline -> its colour, shared by its heading, swatch and tab
        self.disc_colour = {}
        # disciplines unticked on the tab strip: no worksheet for them
        self.skip_tabs = set()
        self.filter_buttons = {}
        self.hide_unused = host.settings.flag('reg_hide_unused', True)
        self.loaded = False
        self.stale = True
        self.header_tick = None
        self.discipline_param = u''
        self.series_param = u''

        # What is in the register, and where that came from.
        self.included = set()
        self.set_name = u''
        self.set_new = False
        self.set_base = set()
        self.show_mode = host.settings.text('reg_show', u'all') or u'all'
        if self.show_mode not in ('all', 'included'):
            self.show_mode = 'all'
        # (tab label, heading path) pairs folded away
        self.collapsed = set()
        # column id -> the set of values its filter allows (u'' for a blank
        # cell); a column with no entry is not filtered
        self.column_filters = {}

        # Revision columns picked by their sequence number, in column order,
        # and the one a Shift+click runs from.
        self.picked_columns = []
        self._column_anchor = None
        # The column keys the view is isolated to: drawings carrying any.
        self.isolated = []
        # Revision cells picked: (sheet key, column key). A transient
        # selection - a new tab or a refresh starts it again.
        self.picked_cells = set()
        self._cell_anchor = None
        # sheet key -> its row in the table, to paint picked cells on
        self._entries = {}
        # column key -> the sequence-number button heading it
        self.seq_buttons = {}
        # The + column at the end of the revisions.
        self.plus_column = None
        # Revisions the Revision Manager has just created, washed green
        # until the register is next read.
        self.fresh_columns = set()
        # Sheet revision edits staged and not yet written, with Undo and
        # Redo; and what they last painted, {(sheet, column): 'add'|'del'}.
        self.pending = ps_register.PendingEdits()
        self._pending_flags = {}
        # The issue data under the revision headings (1.51.0): the
        # Revision Manager's Issue Status and Issued To / Method columns,
        # as rows - the Excel's block, live and editable.
        self.issue_fields = []
        # (column key, field id) -> the value stored in the model
        self.issue_stored = {}
        # column key -> the status most of its drawings carry, shown
        # faintly where no Issue Status is stored
        self.issue_derived = {}
        # (column key, field id) -> its CheckBox or TextBox in the heading
        self.issue_cells = {}
        # (column key, field id) -> the row Border behind it, for the wash
        self.issue_rows = {}
        # column key -> the framed block in its heading
        self.issue_pieces = {}
        self._issue_painting = False
        # The row names' block, laid over the drawing headings (1.52.0),
        # the spacer it lines up with, and where it was last put.
        self.label_block = None
        self.label_width = 0
        self._block_spacers = {}
        self._label_place = None
        # The register's name and the two logos, in the heading's free
        # space while the issue rows are frozen (1.54.0).
        self.brand = None
        self._brand_parts = None
        self._brand_place = None
        # Heading colours (1.52.0): the trade ramps, greys, or picked one
        # heading at a time - by heading name, kept per project.
        # Greyscale until changed (1.54.0).
        self.heading_mode = ps_ramp.heading_mode(
            host.settings.text('reg_heading_mode', u'') or ps_ramp.GREY)
        self.heading_custom = {}
        # The heading a right-click landed on, for the colour menu.
        self._menu_heading = None
        # The issue data frozen in the heading, or as rows at the top of the
        # drawings that scroll with them (1.53.0). Frozen every time the
        # tool opens (1.54.0): scrolling is for the session it was asked in.
        self.issue_frozen = True

        self._suspend = False
        self._suspend_combo = False
        self._tick_selection = set()
        self._search_timer = None
        self._styles = {}
        self._measures = {}
        self._warnings = []

        self.table = DataTable('register')
        self.table.Columns.Add('sel', Boolean).DefaultValue = False
        for name in ('key', 'num', 'name', 'size', 'scale', 'rev', 'seq',
                     'rdate',
                     'curkey', 'ishead', 'hid', 'glabel', 'gpath', 'gcolor',
                     'level', 'vis', 'show', 'ord', 'hidetick'):
            self.table.Columns.Add(name, String)
        # A heading's text colour, black or white on its pill (see
        # ps_ramp.text_on); GridCell's ishead trigger binds to it.
        self.table.Columns.Add('gink', Object).DefaultValue = \
            Brushes.Transparent
        self.view = self.table.DefaultView
        self.view.RowFilter = "[show] = '1'"
        self.view.Sort = '[ord] ASC'

        self._wire()

    # ==================================================================
    # wiring
    # ==================================================================

    def _wire(self):
        try:
            self.table.ColumnChanged += self._tick_changed
        except Exception:
            pass
        if self.heading_mode_button is not None:
            try:
                self.heading_mode_button.Click += \
                    lambda sender, args: self.cycle_heading_mode()
            except Exception:
                pass
        if self.freeze_button is not None:
            try:
                self.freeze_button.Click += \
                    lambda sender, args: self.toggle_issue_frozen()
            except Exception:
                pass
        if self.grid is not None:
            try:
                self.grid.LayoutUpdated += self._place_issue_labels
            except Exception:
                pass
        if self.grid is not None:
            try:
                self.grid.ItemsSource = self.view
                self.grid.Sorting += self._on_sorting
                self.grid.PreviewMouseLeftButtonDown += self._row_click
                self.grid.LoadingRow += self._paint_row
                self.grid.SelectionChanged += self._rows_selected
                self.grid.PreviewMouseRightButtonDown += self._right_press
                self.grid.PreviewMouseRightButtonUp += self._right_release
            except Exception:
                pass
        self._click(ps_ui.find(self.window, 'RegisterRefreshButton'),
                    lambda sender, args: self.reload())
        self._click(ps_ui.find(self.window, 'RegisterSetupButton'),
                    lambda sender, args: self.host.open_setup(
                        section='register'))
        self._click(ps_ui.find(self.window, 'RegisterApplyButton'),
                    lambda sender, args: self.apply_set())
        self._click(ps_ui.find(self.window, 'RegisterNewSetButton'),
                    lambda sender, args: self.new_set())
        self._click(ps_ui.find(self.window, 'RegisterExportButton'),
                    lambda sender, args: self.export_now())
        self._click(ps_ui.find(self.window, 'RevisionManagerButton'),
                    lambda sender, args: self.open_revision_manager())
        self._click(self.show_all_button,
                    lambda sender, args: self.set_show('all'))
        self._click(self.show_included_button,
                    lambda sender, args: self.set_show('included'))
        self._click(self.collapse_button,
                    lambda sender, args: self.toggle_collapse_all())
        self._click(self.reset_button,
                    lambda sender, args: self.reset_filters())
        self._click(self.isolate_button,
                    lambda sender, args: self.toggle_isolate())
        self._click(self.change_button,
                    lambda sender, args: self.change_revision())
        self._click(self.remove_button,
                    lambda sender, args: self.remove_revision())
        self._click(self.create_button,
                    lambda sender, args: self.create_revision())
        self._click(self.edit_button,
                    lambda sender, args: self.edit_revision())
        self._click(self.assign_button,
                    lambda sender, args: self.assign_revision())
        self._click(self.undo_button, lambda sender, args: self.undo())
        self._click(self.redo_button, lambda sender, args: self.redo())
        self._click(self.apply_revs_button,
                    lambda sender, args: self.apply_revisions())
        self._click(self.discard_button,
                    lambda sender, args: self.discard_pending())
        self._click(self.all_revs_button,
                    lambda sender, args: self.set_show_all_revisions(
                        self.hide_unused))
        # Ticked before the handler goes on, or setting it fires a save.
        if self.export_check is not None:
            try:
                self.export_check.IsChecked = self.host.settings.flag(
                    'reg_add_to_export', False)
                self.export_check.Checked += self._export_toggled
                self.export_check.Unchecked += self._export_toggled
            except Exception:
                pass
        self._paint_all_revs_button()
        try:
            self.set_combo.SelectionChanged += self._set_picked
        except Exception:
            pass
        try:
            self.search_box.TextChanged += self._search_changed
        except Exception:
            pass
        try:
            self.root.PreviewKeyDown += self._key_down
        except Exception:
            pass
        self._paint_show()

    def _click(self, control, handler):
        if control is None:
            return
        try:
            control.Click += handler
        except Exception:
            pass

    def _setting(self, key, value):
        try:
            self.host.settings.set(key, value)
            self.host.settings.save()
        except Exception:
            pass

    # ==================================================================
    # coming and going
    # ==================================================================

    def show(self):
        """The tab has come forward: read if needed, refresh the set list."""
        if self.stale or not self.loaded:
            self.reload()
        else:
            # The Selection tab can save a set while this one is away.
            self._fill_set_combo()
            self._apply_filters()
            self._say_notes()
            self._say()
        self.host.say(u'A tick here puts a drawing in the register export. '
                      u'Click a revision date to include every drawing that '
                      u'carries it; click a series heading to fold it away.')

    def ensure_loaded(self):
        if self.stale or not self.loaded:
            self.reload()

    def invalidate(self):
        """The model or the settings behind it changed; read again.

        At once when the register is on screen, otherwise the next time it
        is wanted - reading a register nobody is looking at is wasted time.
        """
        self.stale = True
        if self.host.on_register_tab():
            self.reload()

    def close(self):
        try:
            if self._search_timer is not None:
                self._search_timer.Stop()
        except Exception:
            pass

    # ==================================================================
    # reading
    # ==================================================================

    def reload(self):
        settings = self.host.settings
        self.discipline_param = settings.text('param_discipline', u'') or u''
        self.series_param = settings.text('param_series', u'') or u''
        self._warnings = []
        sheets = []
        try:
            sheets = self.host.sheet_rows()
            scale = settings.text('reg_scale_param', u'') \
                if settings.text('reg_scale_mode', u'') != \
                ps_config.SCALE_REVIT else u''
            self.revisions, self.rows = ps_register.read_register(
                self.host.doc, sheets, self.discipline_param,
                self.series_param, settings.text('reg_status_param', u''),
                scale)
        except Exception as err:
            self.revisions, self.rows = [], []
            self._warnings.append(
                u'The register could not be read: {0}'.format(err))
        self.rows_by_key = dict([(u'{0}'.format(row.key), row)
                                 for row in self.rows])
        # The green on new revisions lasts until the next read.
        self.fresh_columns = set()
        # Picks survive a refresh only where the revision still exists.
        known = set([revision.key for revision in self.revisions])
        self.picked_columns = [key for key in self.picked_columns
                               if key in known]
        self.isolated = [key for key in self.isolated if key in known]
        self._read_issue_data()
        try:
            self.heading_custom = ps_config.read_heading_colours(
                self.host.doc)
        except Exception:
            self.heading_custom = {}
        # Staged edits survive a read, minus any whose revision, sheet or
        # issue data column has gone from the model.
        self.pending.prune(known, set(self.rows_by_key),
                           set([field.id for field in self.issue_fields]))
        self.elements = dict([(u'{0}'.format(sheet.key), sheet.element)
                              for sheet in sheets
                              if getattr(sheet, 'is_sheet', False)])

        self._commit_edits()
        self._suspend = True
        try:
            self.table.Rows.Clear()
            self._reset_revision_columns()
        finally:
            self._suspend = False

        # A refresh in the middle of editing a set keeps the edits; there
        # is no reason F5 should throw away ticks nobody has applied yet.
        if self.loaded and self.dirty():
            self.included &= set(self.rows_by_key)
        else:
            wanted = self.set_name if self.loaded else \
                settings.text('reg_last_set', u'')
            self._adopt(wanted)

        self.tabs = ps_register.discipline_tabs(self.rows)
        self.skip_tabs = ps_config.read_register_skipped(self.host.doc)
        self.disc_colour = self.discipline_colours(
            [label for label, _members in self.tabs
             if label != ps_register.ALL_TAB])
        labels = [label for label, _members in self.tabs]
        # Stay on the same discipline across a refresh where it still
        # exists. Being thrown back to All every F5 is the kind of thing
        # that makes people stop pressing it.
        self.tab_index = labels.index(self.tab_label) \
            if self.tab_label in labels else 0
        self.loaded = True
        self.stale = False
        self._say_source()
        self._fill_set_combo()
        self._build_tab_strip()
        self.select_tab(self.tab_index)

    def _reset_revision_columns(self):
        """One table column per revision in the project.

        All of them, once per read. Which ones the grid shows is a per-tab
        decision; the table just has to be able to hold whatever any tab
        binds to.
        """
        try:
            for column in list(self.table.Columns):
                name = u'{0}'.format(column.ColumnName)
                flag = name[2:] if name[:2] in (PICK_PREFIX,
                                                PENDING_PREFIX) else u''
                if ps_register.is_column_key(name) or \
                        ps_register.is_column_key(flag):
                    self.table.Columns.Remove(column)
        except Exception:
            pass
        for revision in self.revisions:
            try:
                self.table.Columns.Add(revision.key, String)
                # The picked-cell flag beside it; see CELL_STYLE.
                self.table.Columns.Add(PICK_PREFIX + revision.key, String)
                # And whether a staged edit adds or removes it.
                self.table.Columns.Add(PENDING_PREFIX + revision.key, String)
            except Exception:
                continue

    # ==================================================================
    # what is included: View/Sheet Sets, or by hand
    # ==================================================================

    def all_keys(self):
        return set(self.rows_by_key)

    def dirty(self):
        """Whether the ticks differ from the set they came from.

        By hand there is nothing to apply - those ticks are saved as they
        are made. A new set is always dirty until it has been written.
        """
        if not self.set_name:
            return False
        if self.set_new:
            return True
        return self.included != self.set_base

    def _adopt(self, name):
        """Take the ticks from a saved set, or from the by-hand list."""
        sets = getattr(self.host, 'sheet_sets', {}) or {}
        keys = self.all_keys()
        self.set_new = False
        if name and name in sets:
            self.set_name = name
            members = set([u'{0}'.format(key) for key in sets[name]])
            self.included = members & keys
        else:
            self.set_name = u''
            excluded = ps_config.read_register_excluded(self.host.doc)
            self.included = set(keys) - (excluded or set())
        self.set_base = set(self.included)

    def _save_by_hand(self):
        if self.set_name:
            return
        ps_config.write_register_excluded(self.host.doc,
                                          self.all_keys() - self.included)

    def _fill_set_combo(self):
        sets = getattr(self.host, 'sheet_sets', {}) or {}
        names = sorted(sets.keys(), key=lambda one: one.lower())
        items = [BY_HAND] + names
        if self.set_new and self.set_name:
            items.append(self.set_name + NEW_MARK)
            selected = self.set_name + NEW_MARK
        else:
            selected = self.set_name or BY_HAND
        self._suspend_combo = True
        try:
            ps_ui.fill_combo(self.set_combo, items, selected=selected)
        finally:
            self._suspend_combo = False
        self._paint_apply()

    def _picked_name(self):
        text = ps_ui.combo_text(self.set_combo, BY_HAND)
        if text == BY_HAND:
            return u'', False
        if text.endswith(NEW_MARK):
            return text[:-len(NEW_MARK)], True
        return text, False

    def _leave_dirty_set(self):
        """Ask before throwing away ticks nobody has applied. True to go on."""
        if not self.dirty():
            return True
        answer = ps_ui.Prompt(
            title=u'Document Register',
            headline=u'"{0}" has changes that were not applied.'.format(
                self.set_name),
            message=u'The ticks changed since the set was last saved. '
                    u'Leaving it now throws those changes away; the set in '
                    u'Revit stays as it was.',
            primary=u'Discard changes', secondary=u'Keep editing',
            theme_name=self.host.theme_name, owner=self.window).show()
        return answer == 'primary'

    def _set_picked(self, sender, args):
        if self._suspend_combo:
            return
        name, staged = self._picked_name()
        if staged or (name == self.set_name and not self.set_new):
            return
        if not self._leave_dirty_set():
            self._fill_set_combo()          # put the old choice back
            return
        self._adopt(name)
        self._setting('reg_last_set', self.set_name)
        self._fill_set_combo()
        self.sync_ticks()
        self._apply_filters()
        self._paint_tab_strip()
        self._say()
        if self.set_name:
            self.host.say(u'"{0}" ticks {1} drawing{2}. Change the ticks and '
                          u'press Apply to write them back into the set.'
                          .format(self.set_name, len(self.included),
                                  u'' if len(self.included) == 1 else u's'))
        else:
            self.host.say(u'Ticking by hand: the ticks are kept for this '
                          u'project as you make them.')

    def apply_set(self):
        """Write the ticks back into the chosen set, through Revit's event."""
        if not self.set_name:
            self.host.say(u'Choose a View/Sheet Set to apply to, or + to start '
                          u'a new one. Ticks made by hand are already kept for '
                          u'this project.')
            return
        if not self.included:
            self.host.say(u'A View/Sheet Set cannot be empty - tick at least '
                          u'one drawing first.')
            return
        if not self.dirty():
            self.host.say(u'"{0}" already holds exactly these drawings.'
                          .format(self.set_name))
            return
        name = self.set_name
        included = set(self.included)
        sheets = [self.elements[key] for key in sorted(included)
                  if key in self.elements]
        if self.host._queue(
                lambda uiapp: self._do_apply(name, sheets, included)):
            self.host.say(u'Saving "{0}"...'.format(name))

    def _do_apply(self, name, sheets, included):
        """On Revit's thread. Views already in the set are kept."""
        ok, message = ps_model.save_view_sheet_set(
            self.host.doc, name, sheets, keep_other_views=True)

        def finish():
            self.host.refresh_sheet_sets()
            if ok and self.set_name == name:
                self.set_new = False
                self.set_base = set(included)
                self._setting('reg_last_set', name)
            self._fill_set_combo()
            self._say()
            self.host.say(message)
        self.host._on_ui(finish)
        return ok

    # ==================================================================
    # the Revision Manager
    # ==================================================================

    def open_revision_manager(self, focus=None):
        """Stage revision changes in the manager; write them on Apply.

        The manager is modal and stages only. Apply hands its plan back
        here, the plan is written through Revit's external event in one
        transaction, and the register reads the model again - so closing
        the manager with Apply lands back on an up-to-date register.
        """
        try:
            staging = ps_revisions.read(
                self.host.doc, self.host.settings.text('param_series', u''),
                self.host.settings.text('reg_status_param', u''))
        except Exception as err:
            self.host.say(u'The revisions could not be read: {0}'.format(err))
            return
        # Open on the revisions asked for (Edit revision), else on those of
        # any cloud selected in Revit; and know which sheet is open.
        uidoc = getattr(self.host, 'uidoc', None)
        if focus is None and self._picked_revisions():
            # A revision picked here - its column, or a cell - is the one
            # to open on.
            focus = self._picked_revisions()
        if focus is None and uidoc is not None:
            focus = ps_revisions.selected_revision_keys(uidoc)
        try:
            current_sheet = ps_revisions.sheet_number_of(uidoc.ActiveView)
        except Exception:
            current_sheet = None
        try:
            doc = self.host.doc
            manager = ps_revwin.RevisionManager(
                staging, self.host.theme_name, self.window,
                lambda: ps_revdata.bound_parameters(doc),
                settings=self.host.settings, focus=focus,
                current_sheet=current_sheet)
            plan = manager.show()
        except Exception as err:
            self.host.say(u'The Revision Manager would not open: {0}'
                          .format(err))
            return
        post = manager.post_command
        find = manager.find_request
        if not plan and not post and not find:
            self.host.say(u'Revision Manager closed - nothing changed.')
            return

        # One job, not two: the external event holds a single piece of
        # work, and a second _queue would replace the write. The write goes
        # first, so Project Parameters opens on a model that already has
        # the staged changes in it.
        def job(uiapp):
            if plan:
                self._write_revisions(plan)
            if post:
                ps_revwin.post_command(uiapp, post)
            if find:
                # Find clouds on views: open each view with the revision
                # clouds isolated in it.
                try:
                    result = ps_revisions.show_clouds(
                        uiapp.ActiveUIDocument, find)
                except Exception as err:
                    result = (0, 0, [u'{0}'.format(err)])
                self.host._on_ui(lambda: self.host.say(
                    ps_revisions.clouds_report(*result)))
        if self.host._queue(job):
            self.host.say(u'Applying the revision changes...' if plan else
                          u'Opening the views with the clouds in...' if find
                          else
                          u'Opening Revit\'s Project Parameters. Add the '
                          u'parameter there, then open the Revision Manager '
                          u'again to map it.')

    def _write_revisions(self, plan):
        """On Revit's thread."""
        done, errors = ps_revisions.write(self.host.doc, plan)
        self.host._on_ui(lambda: self._revisions_written(done, errors))
        return not errors

    def _revisions_written(self, done, errors):
        before = set([u'{0}'.format(revision.element_key)
                      for revision in self.revisions])
        self.reload()
        # New revisions are on no sheet yet, so with only the used ones
        # showing they would not be there at all. Show every revision, and
        # wash the new ones green down their whole column.
        fresh = [revision.key for revision in self.revisions
                 if u'{0}'.format(revision.element_key) not in before]
        if fresh:
            self.fresh_columns = set(fresh)
            if self.hide_unused:
                self.set_show_all_revisions(True, quiet=True)
            self._paint_picked_columns()
        summary = u'{0} revision change{1} applied.'.format(
            done, u'' if done == 1 else u's')
        if fresh:
            summary += u' {0} new revision{1}, in green.'.format(
                len(fresh), u'' if len(fresh) == 1 else u's')
        if not errors:
            self.host.say(summary)
            return
        self.host.say(u'{0} {1} could not be.'.format(summary, len(errors)))
        ps_ui.Prompt(
            title=u'Revision Manager',
            headline=u'{0} change{1} Revit would not make.'.format(
                len(errors), u'' if len(errors) == 1 else u's'),
            message=summary + u' The rest are listed below; the register '
                    u'shows the model as it now is.',
            detail=u'\n'.join(errors), primary=u'Close',
            theme_name=self.host.theme_name, owner=self.window).show()

    def new_set(self):
        """Name a new set, then tick it, then Save. Nothing written until then.

        Revit cannot hold an empty View/Sheet Set, so the set only exists
        here until it has something in it and Save is pressed.
        """
        name = ps_ui.ask_text(u'New View/Sheet Set',
                              u'What should the new set be called?', u'',
                              self.host.theme_name, self.window)
        name = u'{0}'.format(name or u'').strip()
        if not name:
            return
        taken = [one.lower() for one in
                 (getattr(self.host, 'sheet_sets', {}) or {})]
        if name.lower() in taken:
            self.host.say(u'There is already a set called "{0}" - choose it '
                          u'from the list to change it.'.format(name))
            return
        if not self._leave_dirty_set():
            return
        self.set_name = name
        self.set_new = True
        self.included = set()
        self.set_base = set()
        self._fill_set_combo()
        self.sync_ticks()
        self.set_show('all')
        self._paint_tab_strip()
        self._say()
        self.host.say(u'Tick the drawings for "{0}", then press Save new set. '
                      u'Nothing is written to the model until then.'
                      .format(name))

    def _paint_apply(self):
        button = self.apply_button
        if button is None:
            return
        if self.set_new:
            text, lit = u'Save new set', True
        elif self.dirty():
            text, lit = u'Apply  •', True
        else:
            text, lit = u'Apply', False
        try:
            button.Content = text
            button.IsEnabled = bool(self.set_name)
        except Exception:
            pass
        self.host._styled(button, 'ChipButtonOn' if lit else 'ChipButton')

    # ==================================================================
    # all, or included only
    # ==================================================================

    def set_show(self, mode):
        self.show_mode = 'included' if mode == 'included' else 'all'
        self._setting('reg_show', self.show_mode)
        self._paint_show()
        # A discipline with nothing in the register has no tab under
        # "Included only", so being on one moves you to All.
        if self.show_mode == 'included' and self.tabs and \
                not self._tab_has_included(self.tab_index):
            self.select_tab(0)
        else:
            self._apply_filters()
            self._paint_tab_strip()
        self._say()

    def _tab_has_included(self, index):
        if not (0 <= index < len(self.tabs)):
            return False
        label, members = self.tabs[index]
        return label == ps_register.ALL_TAB or bool(
            [row for row in members if u'{0}'.format(row.key) in self.included])

    def _tab_shows(self, index):
        label, members = self.tabs[index]
        return ps_register.tab_shows(label, members, self.included,
                                     self.show_mode == 'included',
                                     index == self.tab_index)

    def _paint_show(self):
        on_all = self.show_mode == 'all'
        if self.show_all_button is not None:
            self.host._styled(self.show_all_button,
                              'SwitchButtonOn' if on_all else 'ChipButton')
        if self.show_included_button is not None:
            self.host._styled(self.show_included_button,
                              'ChipButton' if on_all else 'SwitchButtonOn')

    # ==================================================================
    # the tab strip along the bottom
    # ==================================================================

    def _build_tab_strip(self):
        """A tab per discipline: its tick box, its colour, its name and count.

        The tick box says whether the discipline gets a worksheet in the
        Excel export - ticked by default, and greyed while the discipline
        has nothing in the register, since an empty worksheet is never
        written. A CheckBox inside a Button handles its own click, so
        ticking it does not also switch tabs.
        """
        self.tab_buttons = []
        self.tab_checks = []
        self.tab_texts = []
        if self.tab_strip is None:
            return
        try:
            self.tab_strip.Children.Clear()
        except Exception:
            return
        several = len(self.tabs) > 1
        for index, (label, _members) in enumerate(self.tabs):
            button = Button()
            self.host._styled(button, 'SheetTab')
            button.Click += self._make_tab_click(index)
            panel = StackPanel()
            panel.Orientation = Orientation.Horizontal
            check = None
            if several:
                # The All tab's tick adds an All worksheet, every
                # discipline on one sheet; off until ticked.
                check = CheckBox()
                check.VerticalAlignment = VerticalAlignment.Center
                check.Margin = Thickness(0, 0, 7, 0)
                check.IsChecked = ps_register.tab_ticked(label,
                                                         self.skip_tabs)
                check.Click += self._make_tab_check(label)
                panel.Children.Add(check)
            if label in self.disc_colour:
                swatch = Border()
                swatch.Width = 10
                swatch.Height = 10
                swatch.CornerRadius = CornerRadius(2)
                swatch.Margin = Thickness(0, 0, 7, 0)
                swatch.VerticalAlignment = VerticalAlignment.Center
                swatch.Tag = label
                panel.Children.Add(swatch)
            icon = self._tab_icon(label)
            if icon is not None:
                panel.Children.Add(icon)
            text = TextBlock()
            text.VerticalAlignment = VerticalAlignment.Center
            panel.Children.Add(text)
            button.Content = panel
            self.tab_strip.Children.Add(button)
            self.tab_buttons.append(button)
            self.tab_checks.append(check)
            self.tab_texts.append(text)
        self._paint_tab_strip()

    def _tab_icon(self, label):
        """A small icon saying what the tab holds (see ps_register.tab_icon),
        drawn in the tab's own text colour so it follows the theme and the
        live tab. None when the name says nothing known."""
        data = ps_register.tab_icon(label)
        if not data:
            return None
        try:
            return XamlReader.Parse(TAB_ICON_XAML.format(PRESENTATION, data))
        except Exception:
            return None

    def _make_tab_click(self, index):
        def handler(sender, args):
            self.select_tab(index)
        return handler

    def _paint_tab_strip(self):
        for index, button in enumerate(self.tab_buttons):
            label, members = self.tabs[index]
            active = index == self.tab_index
            self.host._styled(button, 'SheetTabOn' if active else 'SheetTab')
            # The discipline's own colour, the one its heading wears on the
            # All tab. The All tab keeps the plain tab colours.
            colour = self.disc_colour.get(label)
            if colour is not None:
                colour = self.shown_colour(label, 1, colour)
                try:
                    # A tint behind the tab, so its text reads on either
                    # theme and its hover still shows; the swatch is the
                    # solid colour the discipline's heading wears.
                    tint, _wash, solid = self.host._shade_brushes(colour)
                    button.Background = tint
                    for child in button.Content.Children:
                        if isinstance(child, Border):
                            child.Background = solid
                except Exception:
                    pass
            count = len(members)
            done = len([row for row in members
                        if u'{0}'.format(row.key) in self.included])
            ps_ui.set_visible(button, self._tab_shows(index))
            text = self.tab_texts[index] if index < len(self.tab_texts) \
                else None
            if text is not None:
                try:
                    text.Text = u'{0}   {1}/{2}'.format(label, done, count)
                    # Bold on every tab - the live one is told by its bar.
                    text.FontWeight = FontWeights.Bold
                except Exception:
                    pass
            check = self.tab_checks[index] if index < len(self.tab_checks) \
                else None
            if check is not None:
                try:
                    check.IsEnabled = done > 0
                    check.ToolTip = (
                        u'Nothing from {0} is in the register, so it gets no '
                        u'worksheet.'.format(label) if not done else
                        u'Ticked: an All worksheet comes first in the Excel '
                        u'export, every discipline on one sheet under its '
                        u'own heading. Unticked: one worksheet per '
                        u'discipline only.' if label == ps_register.ALL_TAB
                        else
                        u'Ticked: {0} gets a worksheet in the Excel export. '
                        u'Untick to leave it out.'.format(label))
                except Exception:
                    pass
            try:
                button.ToolTip = u'{0}: {1} of {2} drawing{3} in the ' \
                    u'register'.format(label, done, count,
                                       u'' if count == 1 else u's')
            except Exception:
                continue

    def _make_tab_check(self, label):
        def handler(sender, args):
            try:
                wanted = bool(sender.IsChecked)
            except Exception:
                wanted = True
            self.skip_tabs = ps_register.tick_tab(label, wanted,
                                                  self.skip_tabs)
            ps_config.write_register_skipped(self.host.doc, self.skip_tabs)
            if label == ps_register.ALL_TAB:
                self.host.say(u'The Excel export {0} an All worksheet, every '
                              u'discipline on one sheet, before the '
                              u'others.'.format(u'gets' if wanted
                                                else u'no longer gets'))
                return
            self.host.say(u'{0} {1} the Excel export.'.format(
                label, u'is back in' if wanted else u'is left out of'))
        return handler

    def repaint(self):
        """After a palette swap: the colours here are brushes set in code."""
        if self.heading_mode == ps_ramp.GREY and self.loaded:
            # Grey headings are greys of the theme: fill again.
            self.select_tab(self.tab_index)
            return
        self._paint_tab_strip()
        self._commit_edits()
        try:
            self.grid.Items.Refresh()
        except Exception:
            pass

    def select_tab(self, index):
        if not self.tabs:
            self.tab_index = 0
            self._fill([])
            self._build_columns([])
            self._say()
            return
        index = max(0, min(len(self.tabs) - 1, index))
        self.tab_index = index
        self.tab_label, members = self.tabs[index]
        self._fill(members)
        self._build_columns(members)
        self._apply_filters()
        self._fit_columns()
        self._paint_tab_strip()
        self._paint_collapse_button()
        self._paint_heading_mode_button()
        self._paint_freeze_button()
        self._say_notes()
        self._say()

    # ==================================================================
    # filling the table
    # ==================================================================

    def _heading_text(self, level, folded, label):
        indent = u'      ' if level == 2 else u''
        return indent + (COLLAPSED if folded else EXPANDED) + label

    def _commit_edits(self):
        """Close any edit the grid has open before the table is reshaped.

        A tick is an edit on its row until the grid commits it. Clearing or
        re-filtering the table underneath an open edit throws "Refresh is
        not allowed during an AddNew or EditItem transaction". Twice: once
        for the cell, once for the row.
        """
        if self.grid is None:
            return
        for _step in (0, 1):
            try:
                self.grid.CommitEdit()
            except Exception:
                return

    def _fill(self, members):
        """The rows for a tab, under their headings.

        The All tab is grouped by discipline and then by series inside each;
        a discipline's tab by series. Every heading carries a colour place
        for the row painter, and every drawing the place of the heading it
        sits directly under.
        """
        self._commit_edits()
        by_discipline = (self.tab_label == ps_register.ALL_TAB and
                         len(self.tabs) > 1)
        tree = ps_register.group_tree(members, by_discipline,
                                      bool(self.series_param))
        self._suspend = True
        try:
            self.table.Rows.Clear()
            self.groups = {}
            self.group_paths = {}
            self.group_parent = {}
            self._order = 0
            self._entries = {}
            self.picked_cells = set()
            self._cell_anchor = None
            # New rows carry the model's text: nothing staged is painted.
            self._pending_flags = {}
            # Project Browser Pro's colours: planned over the whole tab
            # first, because a heading's shade depends on how many of its
            # trade sit beside it.
            colours = self.heading_colours(tree, by_discipline)
            serial = [0]

            def next_colour():
                found = colours.get(serial[0], u'')
                serial[0] += 1
                return found

            for label, rows, children in tree:
                if label is None:
                    for row in rows:
                        self._add_drawing(row, -1, u'')
                    continue
                colour = self.shown_colour(label, 1, next_colour())
                head = self._add_heading(label, label, 1, None, colour, rows)
                if not children:
                    for row in rows:
                        self._add_drawing(row, head, colour)
                    continue
                for inner, inner_rows, _none in children:
                    inner_colour = self.shown_colour(inner, 2, next_colour())
                    sub_head = self._add_heading(
                        inner, label + u'/' + inner, 2, head, inner_colour,
                        inner_rows)
                    for row in inner_rows:
                        self._add_drawing(row, sub_head, inner_colour)
            # Unfrozen, the issue data are the first rows of the tab.
            if self.issue_fields and not self.issue_frozen:
                self._add_issue_rows()
        finally:
            self._suspend = False
        self._sync_headings()
        self._paint_pending()

    @staticmethod
    def discipline_colours(labels):
        """{discipline: hex}: the colour each discipline's heading wears
        on the All tab, and its own tab in the strip."""
        found = ps_ramp.plan([(index, label, 1, None)
                              for index, label in enumerate(labels)])
        return dict([(label, found[index])
                     for index, label in enumerate(labels)])

    def heading_colours(self, tree, by_discipline):
        """{n: hex} for the nth heading of ``tree``, in the order _fill
        adds them.

        Disciplines on the All tab take the colours the tab strip shows.
        Series take their own trade where their name says one, otherwise
        the discipline's - the one above them, or the tab they are on.
        """
        headings = []
        for label, _rows, children in tree:
            if label is None:
                continue
            top = len(headings)
            headings.append((top, label, 1, None))
            for inner, _inner_rows, _none in children or ():
                headings.append((len(headings), inner, 2, top))
        inherit = None if by_discipline else self.tab_label
        found = ps_ramp.plan(headings, inherit=inherit)
        if by_discipline:
            for hid, label, level, _parent in headings:
                if level == 1 and label in self.disc_colour:
                    found[hid] = self.disc_colour[label]
        return found

    def _add_heading(self, label, path, level, parent, place, rows):
        group_id = len(self.group_paths)
        self.groups[group_id] = [u'{0}'.format(row.key) for row in rows]
        self.group_paths[group_id] = path
        self.group_parent[group_id] = parent
        head = self.table.NewRow()
        head['key'] = u''
        head['glabel'] = label
        head['gpath'] = path
        head['level'] = u'{0}'.format(level)
        head['gcolor'] = u'{0}'.format(place)
        try:
            head['gink'] = self.host._ink_brush(place)
        except Exception:
            pass
        head['num'] = self._heading_text(level, False, label)
        head['ishead'] = u'1'
        head['hid'] = u'{0}'.format(group_id)
        head['vis'] = u'1'
        head['show'] = u'1'
        head['ord'] = u'{0:06d}'.format(self._order)
        self.table.Rows.Add(head)
        self._order += 1
        return group_id

    def _add_drawing(self, row, group_id, place):
        entry = self.table.NewRow()
        key = u'{0}'.format(row.key)
        entry['sel'] = key in self.included
        entry['key'] = key
        entry['num'] = row.number
        entry['name'] = row.name
        entry['size'] = row.size
        entry['scale'] = row.scale
        entry['rev'] = row.current
        entry['rdate'] = row.current_date
        entry['seq'] = getattr(row, 'current_sequence', u'') or u''
        entry['curkey'] = row.current_key
        entry['ishead'] = u'0'
        entry['hid'] = u'{0}'.format(group_id)
        entry['glabel'] = u''
        entry['gpath'] = u''
        entry['level'] = u'0'
        entry['gcolor'] = u'{0}'.format(place)
        entry['vis'] = u'1'
        entry['show'] = u'1'
        entry['ord'] = u'{0:06d}'.format(self._order)
        for column_key, text in row.cells.items():
            try:
                entry[column_key] = text
            except Exception:
                continue
        self.table.Rows.Add(entry)
        self._entries[key] = entry
        self._order += 1

    def _paint_row(self, sender, args):
        """A heading's band and its drawings' wash, as rows are realised.

        The Selection tab's colours, from the same helper. Set on every
        row, coloured or not: with recycling on, a container that was a
        heading a moment ago is handed to a drawing next, and skipping the
        reset leaves a stripe across the list.
        """
        try:
            row = args.Row
            entry = row.Item.Row
        except Exception:
            return
        if self._paint_issue_row(row, entry):
            return
        try:
            place = u'{0}'.format(entry['gcolor'])
        except Exception:
            place = u''
        try:
            if not place.startswith(u'#'):
                row.Background = Brushes.Transparent
                row.FontWeight = FontWeights.Normal
                return
            _cell, wash, head = self.host._shade_brushes(place)
            if self._is_heading(entry):
                row.Background = head
                row.FontWeight = FontWeights.Bold
            else:
                row.Background = wash
                row.FontWeight = FontWeights.Normal
        except Exception:
            pass

    # ==================================================================
    # the columns
    # ==================================================================

    def _filter_columns(self):
        """Every column a filter can be set on: the drawing columns and
        every revision, shown or not."""
        return [entry[0] for entry in self.IDENTITY if entry[0] != 'sel'] + \
            [revision.key for revision in self.revisions]

    def _values(self, entry):
        values = {}
        for column in self._filter_columns():
            try:
                values[column] = u'{0}'.format(entry[column] or u'').strip()
            except Exception:
                values[column] = u''
        return values

    def _build_columns(self, members):
        """The drawing columns. The revision columns follow the filter -
        see _sync_revision_columns - so they are added by _apply_filters."""
        self.used_columns = []
        self.columns = {}
        self.filter_buttons = {}
        self.seq_buttons = {}
        self.issue_cells = {}
        self.issue_rows = {}
        self.issue_pieces = {}
        self._block_spacers = {}
        self._build_issue_labels()
        if self.grid is None:
            return
        self.header_tick = None
        try:
            self.grid.Columns.Clear()
        except Exception:
            return
        for col_id, title, floor in self.IDENTITY:
            try:
                column = self._identity_column(col_id, title, floor)
                self.grid.Columns.Add(column)
                self.columns[col_id] = column
            except Exception:
                continue
        # Where the drawings end and the revisions begin; frozen with the
        # drawing columns, so the line stays put as the revisions scroll.
        try:
            self.grid.Columns.Add(self._divider_column())
        except Exception:
            pass
        try:
            self.grid.FrozenColumnCount = len(self.IDENTITY) + 1
        except Exception:
            pass
        self.plus_column = self._plus_column()
        try:
            self.grid.Columns.Add(self.plus_column)
        except Exception:
            pass

    def _sync_revision_columns(self):
        """Show the revision columns the view calls for, and only those.

        With Hide unused revisions on, the columns the drawings passing
        the filters actually carry; off, every revision in the project. A
        column with a filter of its own always stays, or a filter could
        hide the very column it would have to be cleared from. Only the
        revision columns are touched - the drawing columns' headings, and
        anything open in them, stay put.
        """
        visible = [self.rows_by_key[u'{0}'.format(entry['key'])]
                   for entry in self.table.Rows
                   if not self._is_heading(entry)
                   and u'{0}'.format(entry['vis']) == u'1'
                   and u'{0}'.format(entry['key']) in self.rows_by_key]
        wanted = ps_register.revisions_for(self.revisions, visible,
                                           self.hide_unused)
        keep = set([column.key for column in wanted])
        keep |= set([key for key, allowed in self.column_filters.items()
                     if allowed is not None and
                     ps_register.is_column_key(key)])
        wanted = [column for column in
                  sorted(self.revisions, key=lambda one: one.sequence)
                  if column.key in keep]
        if [c.key for c in wanted] == [c.key for c in self.used_columns]:
            return
        if self.grid is None:
            self.used_columns = wanted
            return
        for column in self.used_columns:
            existing = self.columns.pop(column.key, None)
            self.seq_buttons.pop(column.key, None)
            self._forget_issue_piece(column.key)
            if existing is not None:
                try:
                    self.grid.Columns.Remove(existing)
                except Exception:
                    pass
        for revision in wanted:
            try:
                column = self._revision_column(revision)
                self.grid.Columns.Add(column)
                self.columns[revision.key] = column
            except Exception:
                continue
        # The + stays last, after whatever revisions came and went.
        if self.plus_column is not None:
            try:
                self.grid.Columns.Remove(self.plus_column)
                self.grid.Columns.Add(self.plus_column)
            except Exception:
                pass
        self.used_columns = wanted
        self._fit_revision_columns()
        self._paint_issue_edges()
        self._paint_issue_block()

    def set_show_all_revisions(self, show_all, quiet=False):
        """Every revision in the project, or only the ones the drawings on
        screen carry. Kept as reg_hide_unused; the Excel export follows."""
        self.hide_unused = not show_all
        self._setting('reg_hide_unused', u'1' if self.hide_unused else u'0')
        self._sync_revision_columns()
        self._paint_all_revs_button()
        if not quiet:
            self.host.say(u'Showing {0}. The Excel export follows.'.format(
                u'only the revisions the drawings on screen carry'
                if self.hide_unused else u'every revision in the project'))

    def _paint_all_revs_button(self):
        """Solid orange while every revision is showing."""
        if self.all_revs_button is None:
            return
        try:
            self.all_revs_button.SetResourceReference(
                Button.StyleProperty,
                'ChipButton' if self.hide_unused else 'SwitchButtonOn')
        except Exception:
            pass

    def _identity_column(self, col_id, title, floor):
        if col_id == 'sel':
            column = DataGridTemplateColumn()
            column.CellTemplate = XamlReader.Parse(self.TICK_TEMPLATE)
            column.Width = DataGridLength(floor)
            column.MinWidth = floor
            column.CanUserResize = False
            column.CanUserSort = False
            box = CheckBox()
            self.host._styled(box, 'GridCheckBox')
            box.ToolTip = u'Include or leave out every drawing showing on ' \
                u'this tab'
            box.Click += self._header_tick
            self.header_tick = box
            column.Header = self._under_block(box, col_id)
            self._paint_ticks()
            return column

        column = DataGridTextColumn()
        column.Binding = Binding(col_id)
        column.Width = DataGridLength(floor)
        column.MinWidth = 40
        column.IsReadOnly = True
        column.CanUserSort = False
        if col_id == 'rev':
            column.ElementStyle = self._current_style()
        elif col_id in self.CENTRED:
            column.ElementStyle = self._centred_style()
        panel = StackPanel()
        panel.Orientation = Orientation.Vertical
        heading = TextBlock()
        heading.Text = title
        heading.Margin = Thickness(0, 0, 0, 4)
        panel.Children.Add(heading)
        panel.Children.Add(self._filter_button(col_id))
        column.Header = self._under_block(panel, col_id)
        return column

    def _divider_column(self):
        column = DataGridTemplateColumn()
        column.Width = DataGridLength(3)
        column.MinWidth = 3
        column.CanUserResize = False
        column.CanUserSort = False
        column.IsReadOnly = True
        column.CellTemplate = XamlReader.Parse(EMPTY_CELL.format(PRESENTATION))
        column.HeaderStyle = XamlReader.Parse(
            DIVIDER_HEADER_STYLE.format(PRESENTATION))
        column.CellStyle = XamlReader.Parse(
            DIVIDER_CELL_STYLE.format(PRESENTATION))
        return column

    def _plus_column(self):
        """The last column: a green + in its heading for a new revision."""
        column = DataGridTemplateColumn()
        column.Width = DataGridLength(44)
        column.CanUserResize = False
        column.CanUserSort = False
        column.IsReadOnly = True
        column.CellTemplate = XamlReader.Parse(EMPTY_CELL.format(PRESENTATION))
        button = Button()
        self.host._styled(button, 'IconButton')
        button.VerticalAlignment = VerticalAlignment.Bottom
        button.HorizontalAlignment = HorizontalAlignment.Center
        button.ToolTip = u'Add a revision. It shows in green once it is made.'
        button.Content = XamlReader.Parse(PLUS_ICON.format(PRESENTATION))
        button.Click += lambda sender, args: self.new_revision()
        column.Header = self._under_block(button)
        return column

    def new_revision(self):
        """The Add revision window, then the revision made - and back here
        with every revision showing and the new one washed green (see
        _revisions_written)."""
        try:
            staging = ps_revisions.read(
                self.host.doc, self.host.settings.text('param_series', u''),
                self.host.settings.text('reg_status_param', u''))
        except Exception as err:
            self.host.say(u'The revisions could not be read: {0}'.format(err))
            return
        try:
            answer = ps_revaddwin.ask(staging, self.host.theme_name,
                                      self.window, None,
                                      u'Made in the model as soon as you '
                                      u'press Add, then shown in green.')
        except Exception as err:
            self.host.say(u'The Add revision window would not open: {0}'
                          .format(err))
            return
        if not answer:
            self.host.say(u'Add revision cancelled - nothing changed.')
            return
        staging.add(answer['position'], answer['fields'], answer['custom'])
        plan = staging.plan()

        def job(uiapp):
            """On Revit's thread."""
            self._write_revisions(plan)

        if self.host._queue(job):
            self.host.say(u'Making the revision...')

    def _revision_column(self, revision):
        column = DataGridTextColumn()
        column.Binding = Binding(revision.key)
        column.Width = DataGridLength(self.REVISION_FLOOR)
        column.MinWidth = self.REVISION_FLOOR
        column.IsReadOnly = True
        # Sortable only so the header click is reported. _on_sorting turns
        # it into an include and cancels the sort.
        column.CanUserSort = True
        column.SortMemberPath = revision.key
        column.ElementStyle = self._cell_style(revision.key)
        column.Header = self._revision_header(revision)
        wash = self._column_wash(revision.key)
        if wash is not None:
            column.CellStyle = wash
        return column

    def _revision_header(self, revision):
        """The date rotated up the header, the status letter, a filter box.

        LayoutTransform, not RenderTransform: a render transform does not
        change the space the element asks for, so the header row stays one
        line high and the rotated text spills over its neighbours.
        """
        panel = StackPanel()
        panel.Orientation = Orientation.Vertical
        panel.HorizontalAlignment = HorizontalAlignment.Stretch

        # The sequence number over the date, as Revit's own Sheet Issues /
        # Revisions dialog numbers it. On screen only - the RD9 sheet has
        # no row for it, so the Excel export leaves it out.
        #
        # It is a Button, so its click is its own: a Button handles the
        # press, which never reaches the heading's Sorting - the date's
        # include. Clicking it picks the column for Isolate.
        sequence = Button()
        sequence.Content = ps_register.sequence_text(revision.sequence) or u'-'
        sequence.HorizontalAlignment = HorizontalAlignment.Center
        sequence.Margin = Thickness(0, 0, 0, 3)
        sequence.ToolTip = (u'Sequence {0}. Click to pick this revision - '
                            u'Ctrl+click for several, Shift+click for a run '
                            u'- then Isolate sheets with this revision.'
                            .format(revision.sequence))
        sequence.Click += self._make_seq_click(revision.key)
        self.seq_buttons[revision.key] = sequence
        self._paint_seq_button(revision.key)
        panel.Children.Add(sequence)

        date = TextBlock()
        date.Text = revision.heading()
        date.FontSize = 11
        date.FontWeight = FontWeights.Normal
        date.LayoutTransform = RotateTransform(-90)
        date.HorizontalAlignment = HorizontalAlignment.Center
        panel.Children.Add(date)

        letter = TextBlock()
        # A space rather than nothing, so every header keeps the same height
        # whether or not its column has a letter.
        letter.Text = revision.status_letter or u' '
        letter.FontWeight = FontWeights.Bold
        letter.HorizontalAlignment = HorizontalAlignment.Center
        letter.Margin = Thickness(0, 4, 0, 4)
        letter.SetResourceReference(TextBlock.ForegroundProperty, 'BlueBrush')
        # The issue data above, then the letter and the filter at the foot,
        # level with the drawing columns' names and filters (1.52.0).
        if self.block_shown():
            panel.Children.Add(self._issue_piece(revision))
        foot = StackPanel()
        foot.Orientation = Orientation.Vertical
        foot.Children.Add(letter)
        foot.Children.Add(self._filter_button(revision.key))
        panel.Children.Add(self._footer(foot))

        panel.ToolTip = (u'{0}\n\nClick the heading to show only the sheets '
                         u'carrying this revision - Ctrl+click for more - and '
                         u'again to show every sheet.\nClick the sequence '
                         u'number to pick it; right-click for the revision '
                         u'tools.'.format(revision.describe()))
        return panel

    def _filter_button(self, col_id):
        """The filter under a heading: a button opening the value list.

        A Button inside a heading handles its own click, so pressing it
        never reaches the heading - which would include a revision.
        """
        button = Button()
        button.Margin = Thickness(0, 0, 0, 0)
        button.Click += self._make_filter_open(col_id, button)
        self.filter_buttons[col_id] = button
        self._paint_filter_button(col_id)
        return button

    def _paint_filter_button(self, col_id):
        button = self.filter_buttons.get(col_id)
        if button is None:
            return
        allowed = self.column_filters.get(col_id)
        on = allowed is not None
        self.host._styled(button, 'FilterButtonOn' if on else 'FilterButton')
        try:
            button.Content = u'\u25be {0}'.format(len(allowed)) if on \
                else u'\u25be'
            button.ToolTip = (u'Filtered to {0} value{1} - click to change'
                              .format(len(allowed),
                                      u'' if len(allowed) == 1 else u's')
                              if on else u'Filter this column')
        except Exception:
            pass

    def _make_filter_open(self, col_id, button):
        def handler(sender, args):
            self._open_filter(col_id, button)
        return handler

    def _choices(self, col_id):
        """The values on offer: what the other filters leave on this tab.

        A column's own filter is left out of its own list, or the values it
        is hiding would not be there to tick back on - Excel's rule.
        """
        others = dict([(key, value) for key, value in
                       self.column_filters.items() if key != col_id])
        needle = self._needle()
        found = []
        for entry in self.table.Rows:
            if not self._is_drawing(entry):
                continue
            values = self._values(entry)
            if not self._passes_view(entry, values, others, needle):
                continue
            found.append(values.get(col_id, u''))
        return ps_register.filter_choices(found)

    def _open_filter(self, col_id, button):
        """The Excel list: search, All, None, every value, (Blanks), OK."""
        choices = self._choices(col_id)
        allowed = self.column_filters.get(col_id)

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
        shell.MinWidth = 210
        panel = StackPanel()
        shell.Child = panel

        search = TextBox()
        self.host._styled(search, 'ColumnSearchBox')
        search.Tag = u'Search'
        search.Margin = Thickness(0, 0, 0, 6)
        panel.Children.Add(search)

        bulk = StackPanel()
        bulk.Orientation = Orientation.Horizontal
        bulk.Margin = Thickness(0, 0, 0, 6)
        every = Button()
        every.Content = u'All'
        self.host._styled(every, 'ChipButton')
        every.Margin = Thickness(0, 0, 6, 0)
        none = Button()
        none.Content = u'None'
        self.host._styled(none, 'ChipButton')
        bulk.Children.Add(every)
        bulk.Children.Add(none)
        panel.Children.Add(bulk)

        scroll = ScrollViewer()
        scroll.MaxHeight = 280
        scroll.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        listing = StackPanel()
        scroll.Content = listing
        panel.Children.Add(scroll)
        boxes = []
        for value in choices:
            box = CheckBox()
            box.Content = value
            box.Margin = Thickness(0, 2, 0, 2)
            box.IsChecked = allowed is None or raw(value) in allowed
            listing.Children.Add(box)
            boxes.append((value, box))
        if not boxes:
            empty = TextBlock()
            empty.Text = u'Nothing on this tab to filter.'
            listing.Children.Add(empty)

        actions = StackPanel()
        actions.Orientation = Orientation.Horizontal
        actions.HorizontalAlignment = HorizontalAlignment.Right
        actions.Margin = Thickness(0, 8, 0, 0)
        ok = Button()
        ok.Content = u'OK'
        ok.MinWidth = 64
        self.host._styled(ok, 'PrimaryButton')
        ok.Margin = Thickness(0, 0, 6, 0)
        cancel = Button()
        cancel.Content = u'Cancel'
        cancel.MinWidth = 64
        self.host._styled(cancel, 'ChipButton')
        actions.Children.Add(ok)
        actions.Children.Add(cancel)
        panel.Children.Add(actions)
        popup.Child = shell

        def shown():
            return [box for _value, box in boxes
                    if box.Visibility == Visibility.Visible]

        def on_search(sender, args):
            term = u'{0}'.format(search.Text or u'').strip().lower()
            for value, box in boxes:
                box.Visibility = Visibility.Visible \
                    if (not term or term in value.lower()) \
                    else Visibility.Collapsed

        def on_every(sender, args):
            for box in shown():
                box.IsChecked = True

        def on_none(sender, args):
            for box in shown():
                box.IsChecked = False

        def on_ok(sender, args):
            ticked = set([raw(value) for value, box in boxes
                          if bool(box.IsChecked)])
            popup.IsOpen = False
            # Everything ticked is no filter at all - not a filter that
            # happens to allow everything, which would still hide a value
            # that turns up later.
            self.set_filter(col_id, None if len(ticked) == len(boxes)
                            else ticked)

        def on_cancel(sender, args):
            popup.IsOpen = False

        def on_closed(sender, args):
            try:
                holder.Children.Remove(popup)
            except Exception:
                pass

        def swallow(sender, args):
            # A popup's events bubble back through its logical parent - the
            # heading. Unhandled, a click on the list's background reaches
            # the heading, and a heading click on a revision column includes
            # every drawing that carries it. The controls inside handle their
            # own clicks first; whatever is left stops here.
            try:
                args.Handled = True
            except Exception:
                pass

        shell.MouseLeftButtonDown += swallow
        shell.MouseLeftButtonUp += swallow
        search.TextChanged += on_search
        every.Click += on_every
        none.Click += on_none
        ok.Click += on_ok
        cancel.Click += on_cancel
        popup.Closed += on_closed
        # Into the heading's own panel, so the list is in the window's
        # logical tree and its DynamicResource colours resolve. A popup
        # floating free of it renders with no theme at all.
        holder = button.Parent
        try:
            holder.Children.Add(popup)
        except Exception:
            pass
        popup.IsOpen = True
        try:
            search.Focus()
        except Exception:
            pass

    def set_filter(self, col_id, allowed):
        """Set or clear one column's filter, then re-take the view."""
        if allowed is None:
            self.column_filters.pop(col_id, None)
        else:
            self.column_filters[col_id] = set(allowed)
        self._paint_filter_button(col_id)
        self._apply_filters()
        self._say()

    def clear_filters(self):
        for col_id in list(self.column_filters.keys()):
            self.column_filters.pop(col_id, None)
            self._paint_filter_button(col_id)
        self._apply_filters()

    def reset_filters(self):
        """The Reset filters button: every column filter off at once, and
        any Isolate with it - a view narrowed to one revision is a filter
        too, and the one most easily forgotten."""
        count = len(self.column_filters) + (1 if self.isolated else 0)
        self.isolated = []
        self.clear_filters()
        self._say()
        if count:
            self.host.say(u'{0} column filter{1} cleared.'.format(
                count, u'' if count == 1 else u's'))
        else:
            self.host.say(u'No column filters to clear.')

    def _paint_reset_button(self):
        """Live while any column is filtered, with how many in brackets."""
        count = len(self.column_filters) + (1 if self.isolated else 0)
        if self.reset_button is not None:
            try:
                self.reset_button.IsEnabled = bool(count)
            except Exception:
                pass
        ps_ui.set_text(self.reset_text,
                       u'Reset filters ({0})'.format(count) if count
                       else u'Reset filters')

    def _cell_style(self, column_key):
        style = self._styles.get(column_key)
        if style is None:
            style = XamlReader.Parse(CELL_STYLE.format(PRESENTATION,
                                                       column_key))
            self._styles[column_key] = style
        return style

    def _current_style(self):
        style = self._styles.get('__current')
        if style is None:
            style = XamlReader.Parse(CURRENT_STYLE.format(PRESENTATION))
            self._styles['__current'] = style
        return style

    def _centred_style(self):
        style = self._styles.get('__centred')
        if style is None:
            style = XamlReader.Parse(CENTRED_STYLE.format(PRESENTATION))
            self._styles['__centred'] = style
        return style

    # ==================================================================
    # fitting the columns to their text
    # ==================================================================

    def _measure(self, text, size=12, bold=False):
        """The width of a piece of text in pixels, as WPF will draw it."""
        text = u'{0}'.format(text or u'')
        if not text:
            return 0
        key = (text, size, bold)
        found = self._measures.get(key)
        if found is not None:
            return found
        try:
            block = TextBlock()
            block.Text = text
            block.FontFamily = FontFamily(u'Segoe UI')
            block.FontSize = size
            block.FontWeight = FontWeights.Bold if bold \
                else FontWeights.Normal
            block.Measure(Size(float('inf'), float('inf')))
            width = float(block.DesiredSize.Width)
            if width <= 0:
                raise ValueError(text)
        except Exception:
            # Off WPF, or anything odd: a fair estimate for Segoe UI.
            width = len(text) * size * (0.62 if bold else 0.55)
        self._measures[key] = width
        return width

    def _fit_columns(self):
        """Every column as wide as its widest text, measured once per tab.

        Over every drawing on the tab, not only the ones showing, so a
        filter or a collapsed series does not make the columns jump.
        """
        if not self.columns:
            return
        data = [entry for entry in self.table.Rows
                if not self._is_heading(entry)]
        heads = [entry for entry in self.table.Rows if self._is_heading(entry)]
        for col_id, title, floor in self.IDENTITY:
            column = self.columns.get(col_id)
            if column is None or col_id == 'sel':
                continue
            widths = [self._measure(entry[col_id]) for entry in data]
            if col_id == 'num':
                # The series headings live in this column, in blue at 14pt
                # bold. Fitting the column to them is what makes them
                # readable; 1.20.0 cut them off at the drawing number's
                # width.
                widths += [self._measure(entry['num'], 14, True) + 4
                           for entry in heads]
            header = self._measure(title, 12, True)
            ceiling = self.CEILINGS.get(col_id, self.DEFAULT_CEILING)
            self._set_width(column, ps_register.column_width(
                widths, header, floor, ceiling))
        self._fit_revision_columns()

    def _fit_revision_columns(self):
        data = [entry for entry in self.table.Rows
                if not self._is_heading(entry)]
        for revision in self.used_columns:
            column = self.columns.get(revision.key)
            if column is None:
                continue
            # Bold, because the current revision is drawn bold.
            widths = [self._measure(entry[revision.key], 12, True)
                      for entry in data]
            header = self._measure(revision.status_letter, 12, True)
            self._set_width(column, ps_register.column_width(
                widths, header, self.REVISION_FLOOR, self.REVISION_CEILING))

    def _set_width(self, column, pixels):
        try:
            column.Width = DataGridLength(pixels)
        except Exception:
            pass

    # ==================================================================
    # including and leaving out
    # ==================================================================

    def _is_heading(self, entry):
        try:
            return u'{0}'.format(entry['ishead']) == u'1'
        except Exception:
            return False

    def _is_issue(self, entry):
        """An issue data row (unfrozen): in the table, never a drawing."""
        try:
            return u'{0}'.format(entry['key']).startswith(ISSUE_PREFIX)
        except Exception:
            return False

    def _is_drawing(self, entry):
        return not self._is_heading(entry) and not self._is_issue(entry)

    def _tick_changed(self, sender, args):
        try:
            if args.Column.ColumnName != 'sel':
                return
        except Exception:
            return
        if self._suspend:
            return
        try:
            entry = args.Row
            wanted = bool(entry['sel'])
        except Exception:
            return
        if self._is_issue(entry):
            return
        if self._is_heading(entry):
            # Hidden members included: a collapsed series is still a
            # series, and a heading that meant "all but the ones folded
            # away" would be a trap.
            keys = set(self.groups.get(self._as_int(entry['hid']), []))
        else:
            keys = self.host.tick_targets(u'{0}'.format(entry['key']),
                                          self._tick_selection)
        self._tick_selection = set()
        self.set_included(keys, wanted)

    def set_included(self, keys, wanted):
        """Put drawings in the register, or take them out.

        The register's own list - never the Selection tab's print ticks.
        Nothing is re-filtered here: a drawing unticked while "Included
        only" is showing turns pale rather than vanishing under the cursor.
        """
        keys = set([u'{0}'.format(key) for key in keys if key])
        if not keys:
            return
        if wanted:
            self.included |= keys
        else:
            self.included -= keys
        self._suspend = True
        try:
            for entry in self.table.Rows:
                if self._is_heading(entry):
                    continue
                if u'{0}'.format(entry['key']) in keys:
                    if bool(entry['sel']) != bool(wanted):
                        entry['sel'] = bool(wanted)
        finally:
            self._suspend = False
        self._sync_headings()
        self._save_by_hand()
        self._paint_apply()
        self._paint_tab_strip()
        self._say()

    def sync_ticks(self):
        """Put the included list onto the rows on screen."""
        self._suspend = True
        try:
            for entry in self.table.Rows:
                if not self._is_drawing(entry):
                    continue
                wanted = u'{0}'.format(entry['key']) in self.included
                if bool(entry['sel']) != wanted:
                    entry['sel'] = wanted
        finally:
            self._suspend = False
        self._sync_headings()
        self._paint_apply()
        self._say()

    def _sync_headings(self):
        """Each heading ticked when its whole series is in, with its count."""
        self._suspend = True
        try:
            for entry in self.table.Rows:
                if not self._is_heading(entry):
                    continue
                keys = self.groups.get(self._as_int(entry['hid']), [])
                done = len([key for key in keys if key in self.included])
                whole = bool(keys) and done == len(keys)
                if bool(entry['sel']) != whole:
                    entry['sel'] = whole
                entry['name'] = u'{0} drawing{1}, {2} in the register'.format(
                    len(keys), u'' if len(keys) == 1 else u's', done)
        finally:
            self._suspend = False

    def _visible_keys(self):
        found = []
        for entry in self.table.Rows:
            if not self._is_drawing(entry):
                continue
            if u'{0}'.format(entry['show']) == u'1':
                found.append(u'{0}'.format(entry['key']))
        return found

    def include_visible(self, wanted):
        self.set_included(self._visible_keys(), wanted)

    def _header_tick(self, sender, args):
        try:
            wanted = bool(sender.IsChecked)
        except Exception:
            wanted = True
        self.include_visible(wanted)

    def _on_sorting(self, sender, args):
        """A click on a revision's heading isolates the sheets carrying it.

        Ctrl+click adds the revision to what is isolated, or takes it away;
        a plain click on the one revision already isolated shows every sheet
        again. Before 1.42.0 this ticked those sheets into the register -
        a change to the register from a click that reads as "show me".
        The Sorting event is where the click arrives, and it is always
        cancelled: a register has one order.
        """
        try:
            args.Handled = True
            column_key = u'{0}'.format(args.Column.SortMemberPath or u'')
        except Exception:
            return
        if not ps_register.is_column_key(column_key):
            return
        order = [column.key for column in self.used_columns]
        if ps_ui.ctrl_down():
            wanted = set(self.isolated) ^ set([column_key])
        else:
            wanted = set() if self.isolated == [column_key] \
                else set([column_key])
        self.isolated = [key for key in order if key in wanted] + \
            [key for key in sorted(wanted) if key not in order]
        # The heading goes orange with it: what is isolated is what is
        # picked, so Isolate's button and the context menu agree.
        self.picked_columns = [key for key in order if key in wanted]
        self._column_anchor = column_key
        self._paint_picked_columns()
        revealed = self._reveal_isolated()
        if not revealed:
            self._apply_filters()
            self._say()
        if not self.isolated:
            self.host.say(u'Showing every sheet again.')
            return
        shown = len(self._visible_keys())
        self.host.say(u'Showing the {0} sheet{1} carrying {2}. Click the '
                      u'heading again to show every sheet.{3}'.format(
                          shown, u'' if shown == 1 else u's',
                          self._labels(self.isolated),
                          u' {0} of them {1} not in the set, so All sheets '
                          u'is on.'.format(revealed, u'is' if revealed == 1
                                           else u'are') if revealed
                          else u''))

    def _row_click(self, sender, args):
        """Note the highlighted rows; fold a series when its heading is hit.

        The highlighted rows are taken here because by the time the tick
        change is reported the DataGrid may have reduced the selection to
        the one row that was clicked. A click on the heading's own tick box
        ticks the series and never folds it.
        """
        try:
            source = args.OriginalSource
        except Exception:
            return
        if self.host._under_checkbox(source):
            self._tick_selection = self._selected_keys()
            return
        self._tick_selection = set()
        try:
            row = self.host._row_under(source)
            entry = row.Item.Row if row is not None else None
        except Exception:
            entry = None
        if entry is None:
            return
        if self._is_issue(entry):
            # Unfrozen issue data: a click ticks, or asks for the status.
            self._issue_row_click(entry, self._column_under(source))
            try:
                args.Handled = True
            except Exception:
                pass
            return
        if not self._is_heading(entry):
            # Not Handled: the grid still selects the row as it always did.
            # Picking a cell is the register's own state on top of that.
            self._cell_click(entry, self._column_under(source))
            return
        self.toggle_group(u'{0}'.format(entry['gpath']))
        try:
            args.Handled = True
        except Exception:
            pass

    def _selected_keys(self):
        found = set()
        try:
            for item in self.grid.SelectedItems:
                try:
                    entry = item.Row
                except Exception:
                    continue
                if not self._is_drawing(entry):
                    continue
                key = u'{0}'.format(entry['key'])
                if key:
                    found.add(key)
        except Exception:
            return set()
        return found

    # ==================================================================
    # picking revisions (Isolate) and revision cells (Change revision)
    # ==================================================================

    def _make_seq_click(self, column_key):
        def handler(sender, args):
            self.pick_column(column_key)
        return handler

    def pick_column(self, column_key):
        """A click on a column's sequence number - see column_picks."""
        order = [column.key for column in self.used_columns]
        self.picked_columns, self._column_anchor = ps_register.column_picks(
            self.picked_columns, column_key, self._column_anchor, order,
            ps_ui.ctrl_down(), ps_ui.shift_down())
        self._paint_picked_columns()
        self._paint_pick_buttons()
        if self.picked_columns:
            self.host.say(u'{0} picked. Isolate shows only the drawings '
                          u'carrying {1}.'.format(
                              self._labels(self.picked_columns),
                              u'it' if len(self.picked_columns) == 1
                              else u'any of them'))
        else:
            self.host.say(u'No revision picked.')

    def _paint_seq_button(self, column_key):
        button = self.seq_buttons.get(column_key)
        if button is None:
            return
        try:
            button.SetResourceReference(
                Button.StyleProperty,
                'SeqChipOn' if column_key in self.picked_columns
                else 'SeqChip')
        except Exception:
            pass

    def _picked_column_style(self):
        """The orange wash down a picked column, built on RegisterCell."""
        style = self._styles.get('__picked_column')
        if style is None:
            style = XamlReader.Parse(PICKED_COLUMN_STYLE.format(PRESENTATION))
            try:
                base = self.grid.TryFindResource('RegisterCell')
                if base is not None:
                    style.BasedOn = base
            except Exception:
                pass
            self._styles['__picked_column'] = style
        return style

    def _fresh_column_style(self):
        """The green wash down a newly created revision's column."""
        style = self._styles.get('__fresh_column')
        if style is None:
            style = XamlReader.Parse(FRESH_COLUMN_STYLE.format(PRESENTATION))
            try:
                base = self.grid.TryFindResource('RegisterCell')
                if base is not None:
                    style.BasedOn = base
            except Exception:
                pass
            self._styles['__fresh_column'] = style
        return style

    def _column_wash(self, column_key):
        """Picked (orange) beats new (green); neither is no wash."""
        if column_key in self.picked_columns:
            return self._picked_column_style()
        if column_key in self.fresh_columns:
            return self._fresh_column_style()
        return None

    def _paint_picked_columns(self):
        for column in self.used_columns:
            grid_column = self.columns.get(column.key)
            if grid_column is not None:
                try:
                    wash = self._column_wash(column.key)
                    if wash is not None:
                        grid_column.CellStyle = wash
                    else:
                        # Back to the grid's own RegisterCell.
                        grid_column.ClearValue(
                            DataGridTextColumn.CellStyleProperty)
                except Exception:
                    pass
            self._paint_seq_button(column.key)

    def toggle_isolate(self):
        """Show only the drawings carrying a picked revision - or, when
        isolated already, every drawing again. Never touches the model."""
        if self.isolated:
            self.isolated = []
            self._apply_filters()
            self._say()
            self.host.say(u'Showing every sheet again.')
            return
        if not self.picked_columns:
            return
        self.isolated = list(self.picked_columns)
        if not self._reveal_isolated():
            self._apply_filters()
            self._say()
        shown = len(self._visible_keys())
        self.host.say(u'Showing only the {0} sheet{1} carrying {2}. Show all '
                      u'sheets (or Reset filters) brings the rest back.'
                      .format(shown, u'' if shown == 1 else u's',
                              self._labels(self.isolated)))

    def _paint_pick_buttons(self):
        """Isolate lit while a revision is picked or the view is isolated;
        Change revision lit while a cell is picked. Solid orange when lit,
        like every other "on" in the tool; dimmed when there is nothing to
        do, so it reads as waiting rather than broken."""
        self._light(self.isolate_button,
                    bool(self.picked_columns) or bool(self.isolated))
        ps_ui.set_text(self.isolate_text, u'Show all sheets' if self.isolated
                       else (u'Isolate sheets with these revisions'
                             if len(self.picked_columns) > 1
                             else u'Isolate sheets with this revision'))
        count = len(self.picked_cells)
        sheets = len(set([sheet for sheet, _column in self.picked_cells]))
        ps_ui.set_visible(self.cell_tools, bool(count))
        ps_ui.set_text(self.cell_tools_text, u'{0} cell{1} on {2} sheet{3}'
                       .format(count, u'' if count == 1 else u's', sheets,
                               u'' if sheets == 1 else u's'))

    def _light(self, button, lit):
        if button is None:
            return
        try:
            button.IsEnabled = bool(lit)
            button.Opacity = 1.0 if lit else 0.5
            button.SetResourceReference(
                Button.StyleProperty,
                'SwitchButtonOn' if lit else 'ChipButton')
        except Exception:
            pass

    def _labels(self, column_keys):
        by_key = dict([(revision.key, revision) for revision in self.revisions])
        names = []
        for key in column_keys:
            revision = by_key.get(key)
            if revision is None:
                names.append(key)
                continue
            names.append(u'Seq {0}{1}'.format(
                revision.sequence, u' ({0})'.format(revision.date)
                if revision.date else u''))
        return u', '.join(names)

    def _element_label(self, element_key):
        for revision in self.revisions:
            if u'{0}'.format(revision.element_key) == \
                    u'{0}'.format(element_key):
                return self._labels([revision.key])
        return u'revision {0}'.format(element_key)

    def _sheet_label(self, sheet_key):
        row = self.rows_by_key.get(u'{0}'.format(sheet_key))
        return row.number if row is not None and row.number \
            else u'sheet {0}'.format(sheet_key)

    def _column_under(self, source):
        """The SortMemberPath of the cell a click landed in, or u''. A
        revision column's is its key."""
        node = source
        for _step in range(14):
            if node is None:
                return u''
            if isinstance(node, DataGridCell):
                try:
                    return u'{0}'.format(node.Column.SortMemberPath or u'')
                except Exception:
                    return u''
            try:
                node = VisualTreeHelper.GetParent(node)
            except Exception:
                # A Run inside a TextBlock is not a Visual; its parent is.
                node = getattr(node, 'Parent', None)
        return u''

    def _filled(self, sheet_key, column_key):
        """Whether the sheet carries the revision - staged edits
        included, so a cell staged in can be picked and one staged out
        cannot."""
        flag = self._pending_flags.get((u'{0}'.format(sheet_key),
                                        column_key))
        if flag:
            return flag == ps_register.PENDING_ADD
        row = self.rows_by_key.get(u'{0}'.format(sheet_key))
        return row is not None and bool(u'{0}'.format(
            row.cells.get(column_key, u'') or u'').strip())

    def _shown_rows(self):
        """The drawings in the order the grid shows them - what a
        Shift+click's block is measured along."""
        found = []
        try:
            for item in self.view:
                entry = item.Row
                if self._is_drawing(entry):
                    found.append(u'{0}'.format(entry['key']))
        except Exception:
            pass
        return found

    def _cell_click(self, entry, column_key):
        """A click on a drawing's row: a filled revision cell is picked (see
        cell_picks); a plain click anywhere else lets the picks go."""
        ctrl, shift = ps_ui.ctrl_down(), ps_ui.shift_down()
        sheet = u'{0}'.format(entry['key'])
        if not ps_register.is_column_key(column_key) or \
                not self._filled(sheet, column_key):
            if self.picked_cells and not ctrl and not shift:
                self._set_picked_cells(set())
            return
        picked, self._cell_anchor = ps_register.cell_picks(
            self.picked_cells, (sheet, column_key), self._cell_anchor,
            self._shown_rows(), [column.key for column in self.used_columns],
            self._filled, ctrl, shift)
        self._set_picked_cells(picked)

    def _set_picked_cells(self, picked):
        """Write the p_ flags that differ. They drive the cell style only -
        not the view's filter or order - so this is safe mid-edit."""
        before, after = set(self.picked_cells), set(picked)
        self._suspend = True
        try:
            for sheet, column_key in before - after:
                self._flag_cell(sheet, column_key, u'')
            for sheet, column_key in after - before:
                self._flag_cell(sheet, column_key, u'1')
        finally:
            self._suspend = False
        self.picked_cells = after
        self._paint_pick_buttons()
        if after:
            sheets = len(set([sheet for sheet, _column in after]))
            self.host.say(u'{0} revision cell{1} on {2} sheet{3} picked. '
                          u'Change revision on sheet moves them to another '
                          u'revision.'.format(
                              len(after), u'' if len(after) == 1 else u's',
                              sheets, u'' if sheets == 1 else u's'))

    def _flag_cell(self, sheet, column_key, value):
        entry = self._entries.get(sheet)
        if entry is None:
            return
        try:
            entry[PICK_PREFIX + column_key] = value
        except Exception:
            pass

    def clear_picks(self):
        """Escape: let go of every picked cell and revision. An Isolate in
        force stays - it has a button of its own to undo it."""
        self._set_picked_cells(set())
        self._cell_anchor = None
        if self.picked_columns:
            self.picked_columns = []
            self._column_anchor = None
            self._paint_picked_columns()
        self._paint_pick_buttons()
        self.host.say(u'Nothing picked.')

    def change_revision(self):
        """Change the picked cells to another revision - staged. Nothing is
        written until Apply revisions, which moves them on the sheets and
        in their clouds (ps_revisions.swap_on_sheets)."""
        if not self.picked_cells:
            return
        picks = self._picks_by_sheet()
        olds = set()
        for revisions in picks.values():
            olds |= revisions
        try:
            target = ps_revswapwin.choose(
                self.revisions, sorted(olds), len(picks),
                len(self.picked_cells), self.host.theme_name, self.window,
                note=(u'Staged: nothing changes in Revit until Apply '
                      u'revisions. Then a revision added by hand is swapped '
                      u'on the sheet, and its clouds move to the new '
                      u'revision. Issued revisions are locked by Revit and '
                      u'cannot be chosen.'))
        except Exception as err:
            self.host.say(u'The revision list would not open: {0}'.format(err))
            return
        if not target:
            self.host.say(u'Change revision on sheet cancelled - nothing '
                          u'changed.')
            return
        column = ps_register.column_key(target)
        chosen = {}
        for sheet, old in self.picked_cells:
            if old != column:
                chosen.setdefault(sheet, []).append(old)
        if not chosen:
            self.host.say(u'Every picked cell is that revision already.')
            return
        edit = {'kind': 'change', 'target': column,
                'picks': dict([(sheet, sorted(olds))
                               for sheet, olds in chosen.items()])}
        self._set_picked_cells(set())
        self._stage(edit)

    def _picks_by_sheet(self):
        """{sheet key: set of revision element keys} for the picked cells."""
        picks = {}
        for sheet, column_key in self.picked_cells:
            element = ps_register.element_of(column_key)
            if element:
                picks.setdefault(sheet, set()).add(element)
        return picks

    def remove_revision(self):
        """Take the picked revisions off their sheets - staged. Apply
        revisions asks first, because that is when the clouds are deleted."""
        if not self.picked_cells:
            return
        chosen = {}
        for sheet, column in self.picked_cells:
            chosen.setdefault(sheet, []).append(column)
        edit = {'kind': 'remove',
                'picks': dict([(sheet, sorted(columns))
                               for sheet, columns in chosen.items()])}
        self._set_picked_cells(set())
        self._stage(edit)

    def create_revision(self):
        """A new revision, onto the picked cells.

        The Add revision window opens with the sequence just after the
        latest revision picked. Once it is filled in, one job creates it,
        reads which revision is new from the model, and moves every picked
        cell onto it - sheets and clouds - exactly as Change revision does.
        """
        if not self.picked_cells:
            return
        picks = self._picks_by_sheet()
        try:
            staging = ps_revisions.read(
                self.host.doc, self.host.settings.text('param_series', u''),
                self.host.settings.text('reg_status_param', u''))
        except Exception as err:
            self.host.say(u'The revisions could not be read: {0}'.format(err))
            return
        olds = set()
        for revisions in picks.values():
            olds |= revisions
        after = [staging.staged_sequence(key) for key in olds
                 if key in staging.entries]
        after = [one for one in after if one]
        position = (max(after) + 1) if after else None
        columns = sorted(set([column for _sheet, column in self.picked_cells]))
        note = (u'Made as soon as you press Add. The {1} picked cell{2} '
                u'now on {0} are then staged onto it, shown green, until '
                u'Apply revisions.'.format(
                    self._labels(columns), len(self.picked_cells),
                    u'' if len(self.picked_cells) == 1 else u's'))
        try:
            answer = ps_revaddwin.ask(staging, self.host.theme_name,
                                      self.window, position, note)
        except Exception as err:
            self.host.say(u'The Add revision window would not open: {0}'
                          .format(err))
            return
        if not answer:
            self.host.say(u'Create new revision cancelled - nothing changed.')
            return
        staging.add(answer['position'], answer['fields'], answer['custom'])
        plan = staging.plan()
        chosen = {}
        for sheet, column in self.picked_cells:
            chosen.setdefault(sheet, []).append(column)
        chosen = dict([(sheet, sorted(columns))
                       for sheet, columns in chosen.items()])
        doc = self.host.doc

        def job(uiapp):
            """On Revit's thread: the revision is made now; the cells moving
            onto it are staged, for Apply revisions."""
            try:
                new, errors = ps_revisions.create_only(doc, plan)
            except Exception as err:
                new, errors = u'', [u'Nothing was changed: {0}'.format(err)]
            self.host._on_ui(lambda: self._created(new, errors, chosen))

        if self.host._queue(job):
            self.host.say(u'Creating the revision...')

    def _created(self, new, errors, chosen):
        """The new revision is in the model: show it green and stage the
        picked cells onto it."""
        self.reload()
        if not new:
            ps_ui.Prompt(
                title=u'Create new revision',
                headline=u'The new revision was not made.',
                message=u'No cell was staged onto it.',
                detail=u'\n'.join(errors), primary=u'Close',
                theme_name=self.host.theme_name, owner=self.window).show()
            return
        column = ps_register.column_key(new)
        self.fresh_columns = set([column])
        if self.hide_unused:
            self.set_show_all_revisions(True, quiet=True)
        self._paint_picked_columns()
        self._stage({'kind': 'change', 'target': column, 'picks': chosen})

    def edit_revision(self):
        """One revision picked: the Edit revision window. Several: the
        Revision Manager, opened on them."""
        keys = self._picked_revisions()
        if not keys:
            return
        if len(keys) == 1:
            self.edit_revision_box(keys[0])
            return
        self.open_revision_manager(focus=sorted(keys))

    def _picked_revisions(self):
        """The element keys of every revision picked - by its column, or by
        a cell - in column order."""
        columns = list(self.picked_columns)
        for _sheet, column in self.picked_cells:
            if column not in columns:
                columns.append(column)
        order = [column.key for column in self.used_columns]
        columns.sort(key=lambda key: order.index(key) if key in order
                     else len(order))
        return [ps_register.element_of(key) for key in columns
                if ps_register.element_of(key)]

    def edit_revision_box(self, element_key):
        """Every property of one revision in the Edit revision window;
        Apply writes it and the register reads the model again."""
        try:
            staging = ps_revisions.read(
                self.host.doc, self.host.settings.text('param_series', u''),
                self.host.settings.text('reg_status_param', u''))
        except Exception as err:
            self.host.say(u'The revisions could not be read: {0}'.format(err))
            return
        key = u'{0}'.format(element_key)
        if key not in staging.entries:
            self.host.say(u'That revision is no longer in the project.')
            return
        try:
            answer = ps_revaddwin.ask_edit(staging, key, self.host.theme_name,
                                           self.window)
        except Exception as err:
            self.host.say(u'The Edit revision window would not open: {0}'
                          .format(err))
            return
        if not answer:
            self.host.say(u'Edit revision cancelled - nothing changed.')
            return
        refusals = staging.edit(key, answer['fields'], answer['custom'])
        plan = staging.plan()
        if ps_revisions.plan_is_empty(plan):
            self.host.say(u' '.join(refusals) or u'Nothing to change.')
            return

        def job(uiapp):
            """On Revit's thread."""
            self._write_revisions(plan)

        if self.host._queue(job):
            self.host.say(u'Updating the revision...' + (
                u' ' + u' '.join(refusals) if refusals else u''))

    # ------------------------------------------- highlighted sheets
    def _rows_selected(self, sender, args):
        self._paint_sheet_tools()

    def _paint_sheet_tools(self):
        keys = self._selected_keys()
        ps_ui.set_visible(self.sheet_tools, bool(keys))
        ps_ui.set_text(self.sheet_tools_text, u'{0} sheet{1}'.format(
            len(keys), u'' if len(keys) == 1 else u's'))

    def assign_revision(self):
        """A revision onto every highlighted sheet, by hand - as Revit's
        Revisions on Sheet does. Staged until Apply revisions."""
        keys = sorted(self._selected_keys())
        if not keys:
            return
        labels = [self._sheet_label(key) for key in keys]
        try:
            target = ps_revswapwin.choose(
                self.revisions, [], len(keys), 0, self.host.theme_name,
                self.window,
                headline=u'Assign a revision to {0} sheet{1}'.format(
                    len(keys), u'' if len(keys) == 1 else u's'),
                from_text=u'Sheets: ' + u', '.join(labels[:8]) + (
                    u' and {0} more'.format(len(labels) - 8)
                    if len(labels) > 8 else u''),
                note=(u"Staged: added to each sheet by hand, as Revit's "
                      u'Revisions on Sheet does, when you press Apply '
                      u'revisions. A sheet already carrying it is left as it '
                      u'is. Issued revisions are locked by Revit and cannot '
                      u'be added.'),
                ok_text=u'Assign')
        except Exception as err:
            self.host.say(u'The revision list would not open: {0}'.format(err))
            return
        if not target:
            self.host.say(u'Assign revision cancelled - nothing changed.')
            return
        column = ps_register.column_key(target)
        sheets = [key for key in keys if not self._filled(key, column)]
        if not sheets:
            self.host.say(u'Every highlighted sheet carries {0} already.'
                          .format(self._element_label(target)))
            return
        self._stage({'kind': 'assign', 'target': column, 'sheets': sheets})

    def _hit(self, source, kind):
        node = source
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

    def _right_press(self, sender, args):
        """A right-click on something not picked picks it first - Excel's
        way - so the menu acts on what is under the pointer."""
        self._menu_heading = None
        try:
            source = args.OriginalSource
        except Exception:
            return
        header = self._hit(source, DataGridColumnHeader)
        if header is not None:
            try:
                key = u'{0}'.format(header.Column.SortMemberPath or u'')
            except Exception:
                key = u''
            if ps_register.is_column_key(key) and \
                    key not in self.picked_columns:
                self.picked_columns = [key]
                self._column_anchor = key
                self._paint_picked_columns()
                self._paint_pick_buttons()
            return
        row = self._hit(source, DataGridRow)
        if row is None:
            return
        try:
            entry = row.Item.Row
        except Exception:
            return
        if self._is_issue(entry):
            return
        if self._is_heading(entry):
            # The colour menu acts on this heading.
            try:
                self._menu_heading = u'{0}'.format(entry['glabel'])
            except Exception:
                self._menu_heading = None
            return
        sheet = u'{0}'.format(entry['key'])
        column = self._column_under(source)
        if ps_register.is_column_key(column) and \
                self._filled(sheet, column) and \
                (sheet, column) not in self.picked_cells:
            self._set_picked_cells(set([(sheet, column)]))
            self._cell_anchor = (sheet, column)
        if sheet not in self._selected_keys():
            try:
                self.grid.SelectedItems.Clear()
                self.grid.SelectedItems.Add(row.Item)
            except Exception:
                pass

    def _right_release(self, sender, args):
        try:
            menu = self._register_menu()
            menu.PlacementTarget = self.grid
            menu.IsOpen = True
            args.Handled = True
        except Exception:
            pass

    def _menu_item(self, text, handler):
        item = MenuItem()
        self.host._styled(item, 'ThemedMenuItem')
        item.Header = text
        item.Click += lambda sender, args: handler()
        return item

    def menu_entries(self):
        """[(text, action name)] for the right-click menu as things stand -
        None for a separator. What is offered depends only on what is
        highlighted and picked."""
        sheets = self._selected_keys()
        revisions = self._picked_revisions()
        entries = []
        heading = getattr(self, '_menu_heading', None)
        if heading:
            # A right-click on a heading: its colour first.
            entries.append((u'Colour "{0}"'.format(heading),
                            'heading_swatches'))
            entries.append((u'Custom colour...', 'custom_heading_colour'))
            custom = getattr(self, 'heading_custom', {}) or {}
            if heading in custom:
                entries.append((u'Reset this heading\'s colour',
                                'reset_heading_colour'))
            if custom:
                entries.append((u'Reset every heading colour',
                                'reset_heading_colours'))
            entries.append(None)
        if sheets:
            entries.append((u'Open sheet' if len(sheets) == 1 else
                            u'Open sheets', 'open_sheets'))
            entries.append((u'Assign revision to {0} selected sheet{1}...'
                            .format(len(sheets),
                                    u'' if len(sheets) == 1 else u's'),
                            'assign_revision'))
        if revisions:
            if entries:
                entries.append(None)
            entries.append((u'Edit revision...' if len(revisions) == 1 else
                            u'Edit {0} revisions in the Revision '
                            u'Manager...'.format(len(revisions)),
                            'edit_revision'))
        if self.picked_cells:
            entries.append((u'Create new revision...', 'create_revision'))
            entries.append((u'Change revision...', 'change_revision'))
            entries.append((u'Remove revision...', 'remove_revision'))
        if self.picked_columns or self.isolated:
            entries.append((u'Show all sheets' if self.isolated else
                            u'Isolate sheets with this revision',
                            'toggle_isolate'))
        pending = getattr(self, 'pending', None)
        if pending is not None and len(pending):
            if entries:
                entries.append(None)
            entries.append((u'Apply revisions ({0} staged)'.format(
                len(pending)), 'apply_revisions'))
            entries.append((u'Undo   Ctrl+Z', 'undo'))
        if entries:
            entries.append(None)
        entries.append((u'New revision...', 'new_revision'))
        entries.append((u'Revision Manager...', 'open_revision_manager'))
        return entries

    def highlighted_sheets(self):
        """The highlighted drawings' sheets, top of the register first."""
        found = []
        try:
            items = list(self.grid.SelectedItems)
        except Exception:
            return []
        elements = getattr(self, 'elements', None) or {}
        for item in items:
            try:
                entry = item.Row
            except Exception:
                continue
            if not self._is_drawing(entry):
                continue
            sheet = elements.get(u'{0}'.format(entry['key']))
            if sheet is None:
                continue
            try:
                place = self.grid.Items.IndexOf(item)
            except Exception:
                place = len(found)
            found.append((place, sheet))
        found.sort(key=lambda pair: pair[0])
        return [sheet for _place, sheet in found]

    def open_sheets(self):
        """Open sheets on the right-click: the highlighted drawings opened
        in Revit, and the window shrunk to the bottom of the screen."""
        return self.host.open_sheets(self.highlighted_sheets(), u'sheet')

    def _register_menu(self):
        menu = ContextMenu()
        self.host._styled(menu, 'ThemedContextMenu')
        for entry in self.menu_entries():
            if entry is None:
                menu.Items.Add(Separator())
                continue
            text, action = entry
            if action == 'heading_swatches':
                menu.Items.Add(self._swatch_item(text, menu))
                continue
            menu.Items.Add(self._menu_item(text, getattr(self, action)))
        return menu

    # ==================================================================
    # heading colours (1.52.0)
    # ==================================================================

    def shown_colour(self, label, level, ramp):
        """The colour a heading wears in the current mode."""
        return ps_ramp.mode_colour(
            self.heading_mode, ramp, level, self.host.theme_name,
            (getattr(self, 'heading_custom', None) or {}).get(label))

    def set_heading_mode(self, mode, quiet=False):
        self.heading_mode = ps_ramp.heading_mode(mode)
        self._setting('reg_heading_mode', self.heading_mode)
        self._paint_heading_mode_button()
        if self.loaded:
            self.select_tab(self.tab_index)
        if quiet:
            return
        if self.heading_mode == ps_ramp.CUSTOM and not self.heading_custom:
            self.host.say(u'Custom headers: right-click a heading to pick '
                          u'its colour. Until then they are grey.')
        else:
            self.host.say(u'{0}.'.format(
                ps_ramp.MODE_LABELS[self.heading_mode]))

    def cycle_heading_mode(self):
        """The header button: Coloured, Grey, Custom, round."""
        self.set_heading_mode(ps_ramp.next_mode(self.heading_mode))

    def _paint_heading_mode_button(self):
        """The mode's name. The button keeps its own colours
        (HeadingModeButton) whatever the mode."""
        ps_ui.set_text(self.heading_mode_text,
                       ps_ramp.MODE_LABELS.get(self.heading_mode, u''))

    def _paint_freeze_button(self):
        """Solid while frozen (the default); a plain chip while the rows
        scroll with the drawings."""
        frozen = bool(getattr(self, 'issue_frozen', True))
        ps_ui.set_text(self.freeze_text, u'Issue rows frozen' if frozen
                       else u'Issue rows scroll')
        if self.freeze_button is not None:
            try:
                self.freeze_button.SetResourceReference(
                    Button.StyleProperty,
                    'SwitchButtonOn' if frozen else 'ChipButton')
                self.freeze_button.Visibility = Visibility.Visible \
                    if self.issue_fields else Visibility.Collapsed
            except Exception:
                pass

    def toggle_issue_frozen(self):
        """Frozen in the heading, or rows that scroll; remembered."""
        self.set_issue_frozen(not self.issue_frozen)

    def set_issue_frozen(self, frozen):
        self.issue_frozen = bool(frozen)
        self._paint_freeze_button()
        if self.loaded:
            self.select_tab(self.tab_index)
        self.host.say(u'Issue Status, Issued To and Method frozen in the '
                      u'heading - they stay in view.' if self.issue_frozen
                      else u'Issue Status, Issued To and Method are rows at '
                      u'the top of the drawings now, and scroll with them. '
                      u'Click a box to tick it, a status to type it.')

    def set_heading_colour(self, label, colour):
        """One heading's own colour; Custom headers from now on."""
        if not label or not colour:
            return
        self.heading_custom[label] = colour
        self._save_heading_colours()
        if self.heading_mode != ps_ramp.CUSTOM:
            self.set_heading_mode(ps_ramp.CUSTOM, quiet=True)
        else:
            self.select_tab(self.tab_index)
        self.host.say(u'"{0}" is now {1}. Custom headers - the button '
                      u'cycles back to the trade colours.'.format(label,
                                                                 colour))

    def _save_heading_colours(self):
        try:
            ps_config.write_heading_colours(self.host.doc,
                                            self.heading_custom)
        except Exception as err:
            self.host.say(u'The heading colours could not be saved: {0}'
                          .format(err))
        # One set of colours for both tabs: the Selection tab's groups too.
        try:
            self.host.take_heading_colours(self.heading_custom)
        except Exception:
            pass

    def take_heading_colours(self, colours):
        """The project's heading colours, changed on the Selection tab."""
        self.heading_custom = dict(colours or {})
        if self.loaded:
            self.select_tab(self.tab_index)

    def custom_heading_colour(self):
        label = self._menu_heading
        if not label:
            return
        typed = ps_ui.ask_text(
            u'Heading colour', u'Colour for "{0}", as #RRGGBB:'.format(label),
            self.heading_custom.get(label, u'#'), self.host.theme_name,
            self.window)
        if typed is None:
            return
        colour = ps_ramp.parse_hex(typed)
        if colour is None:
            self.host.say(u'"{0}" is not a colour - type six hex digits, '
                          u'like #3FA75A.'.format(typed))
            return
        self.set_heading_colour(label, colour)

    def reset_heading_colour(self):
        label = self._menu_heading
        if label in self.heading_custom:
            del self.heading_custom[label]
            self._save_heading_colours()
            self.select_tab(self.tab_index)
            self.host.say(u'"{0}" is back to grey.'.format(label))

    def reset_heading_colours(self):
        if not self.heading_custom:
            return
        self.heading_custom = {}
        self._save_heading_colours()
        self.select_tab(self.tab_index)
        self.host.say(u'Every heading colour reset - they are grey again.')

    def _swatch_item(self, text, menu):
        """A row of swatches inside the menu - menus here have no
        submenus. A click picks the colour and closes the menu."""
        item = MenuItem()
        self.host._styled(item, 'ThemedMenuItem')
        item.StaysOpenOnClick = True
        panel = StackPanel()
        panel.Orientation = Orientation.Vertical
        title = TextBlock()
        title.Text = text
        title.Margin = Thickness(0, 0, 0, 4)
        panel.Children.Add(title)
        wrap = WrapPanel()
        wrap.Width = 6 * 24
        label = self._menu_heading
        for colour in ps_ramp.SWATCHES:
            swatch = Border()
            swatch.Width = 20
            swatch.Height = 20
            swatch.Margin = Thickness(2)
            swatch.CornerRadius = CornerRadius(3)
            swatch.BorderThickness = Thickness(1)
            swatch.SetResourceReference(Border.BorderBrushProperty,
                                        'EdgeBrush')
            swatch.Background = theme.brush(colour)
            swatch.ToolTip = colour
            swatch.Cursor = Cursors.Hand
            swatch.MouseLeftButtonUp += self._make_swatch_pick(label, colour,
                                                               menu)
            wrap.Children.Add(swatch)
        panel.Children.Add(wrap)
        item.Header = panel
        return item

    def _make_swatch_pick(self, label, colour, menu):
        def handler(sender, args):
            try:
                args.Handled = True
                menu.IsOpen = False
            except Exception:
                pass
            self.set_heading_colour(label, colour)
        return handler

    def _ask_shared(self, mode, shared, summary):
        """Clouds left because they also show on sheets nobody picked.

        Not an error: the cloud is drawn in a view that is on more than one
        sheet, and a cloud is one element - Revit cannot change or delete it
        for one sheet only. So say which other sheets, and ask.
        """
        by_cell = {}
        for sheet, old, cloud, others in shared:
            entry = by_cell.setdefault((sheet, old), [set(), set()])
            entry[0].add(cloud)
            entry[1] |= set(others)
        lines = []
        for (sheet, old), (clouds, others) in sorted(by_cell.items()):
            lines.append(u'{0}, {1}: {2} cloud{3}, also on {4}'.format(
                self._sheet_label(sheet), self._element_label(old),
                len(clouds), u'' if len(clouds) == 1 else u's',
                u', '.join(sorted([self._sheet_label(one)
                                   for one in others]))))
        count = len(set([cloud for _s, _o, cloud, _x in shared]))
        verb = u'Remove' if mode == 'remove' else u'Change'
        answer = ps_ui.Prompt(
            title={'remove': u'Remove revision',
                   'create': u'Create new revision'}.get(
                       mode, u'Change revision on sheet'),
            headline=u'{0} cloud{1} also show{2} on sheets you did not '
                     u'pick.'.format(count, u'' if count == 1 else u's',
                                     u's' if count == 1 else u''),
            message=(summary + u'\n\nThese clouds are drawn in a view that '
                     u'is on those other sheets as well. A cloud is one '
                     u'element: Revit cannot {0} it for one sheet only, so '
                     u'{1} it {1}s it on every sheet it shows on.'.format(
                         verb.lower(), u'removing' if mode == 'remove'
                         else u'changing')),
            detail=u'\n'.join(lines),
            primary=u'{0} on those sheets too'.format(verb),
            secondary=u'Leave them',
            theme_name=self.host.theme_name, owner=self.window).show()
        return answer == 'primary'

    # ==================================================================
    # issue data under the revision headings (1.51.0)
    #
    # The Excel register's block - Issue Status, then Issued to and how -
    # as rows across the bottom of the headings: always in view, lined
    # up with their revisions, and editable. A tick or a status typed here
    # is staged like any other revision change: on the same Undo / Redo,
    # written by Apply revisions into the Revision Manager's columns (and
    # any parameter those are mapped to).
    # ==================================================================

    BLOCK_STATUS_HEIGHT = 26
    BLOCK_ROW_HEIGHT = 21
    BLOCK_FRAME = 2
    # The heading's own padding (RegisterHeader: 5,6,5,5), reached past
    # so the block runs edge to edge and onto the heading's bottom.
    BLOCK_MARGIN = (-5, 6, -5, 6)
    # Every heading ends in a footer this tall - the drawing columns' name
    # and filter, a revision's letter and filter - so the block above it
    # sits level across them all.
    FOOTER_HEIGHT = 50

    def _read_issue_data(self):
        """The block's columns and what each revision has stored. Never
        raises: a model with nothing stored shows the default columns,
        empty."""
        try:
            columns, by_uid = ps_revdata.read(self.host.doc)
        except Exception as err:
            columns, by_uid = [], {}
            self._warnings.append(u'The issue data could not be read: {0}'
                                  .format(err))
        self.issue_fields = ps_revdata.issue_block(columns)
        self.issue_stored = {}
        self.issue_derived = {}
        for revision in self.revisions:
            row = by_uid.get(revision.uid) or {}
            for field in self.issue_fields:
                self.issue_stored[(revision.key, field.id)] = \
                    ps_revdata.stored_value(field, row.get(field.id))
            self.issue_derived[revision.key] = ps_revisions.common_status(
                [one.status for one in self.rows
                 if one.cells.get(revision.key)])

    def _block_heights(self):
        """Each row's height, in block order."""
        return [self.BLOCK_STATUS_HEIGHT if field.group == ps_revdata.STATUS
                else self.BLOCK_ROW_HEIGHT for field in self.issue_fields]

    def block_shown(self):
        """The block sits in the heading: there is issue data, and it is
        frozen. Unfrozen it is rows of the table instead."""
        return bool(self.issue_fields) and \
            bool(getattr(self, 'issue_frozen', True))

    def block_height(self):
        """The whole block, frame included - every heading's bottom."""
        if not self.block_shown():
            return 0
        return sum(self._block_heights()) + 2 * self.BLOCK_FRAME

    def _footer(self, content):
        """A heading's name and filter, at the foot, in a fixed height -
        directly above the drawings."""
        foot = Border()
        foot.Height = self.FOOTER_HEIGHT
        try:
            content.VerticalAlignment = VerticalAlignment.Bottom
        except Exception:
            pass
        foot.Child = content
        return foot

    def _under_block(self, content, col_id=None):
        """A drawing column's heading: room for the issue block at the
        same height as the revisions' block, then its name and filter at
        the foot, right above the drawings (1.52.0)."""
        panel = StackPanel()
        panel.Orientation = Orientation.Vertical
        if self.block_shown():
            spacer = Border()
            spacer.Height = self.block_height()
            spacer.Margin = Thickness(*self.BLOCK_MARGIN)
            panel.Children.Add(spacer)
            if col_id is not None:
                self._block_spacers[col_id] = spacer
        panel.Children.Add(self._footer(content))
        return panel

    def _block_frame(self, left, right):
        """The block's outer edge: the Excel's medium line top and bottom,
        and down whichever sides close it."""
        frame = Border()
        frame.BorderThickness = Thickness(left, self.BLOCK_FRAME, right,
                                          self.BLOCK_FRAME)
        frame.Margin = Thickness(*self.BLOCK_MARGIN)
        frame.SetResourceReference(Border.BorderBrushProperty, 'MutedBrush')
        frame.SetResourceReference(Border.BackgroundProperty, 'FieldBg')
        # A click on the block is its own: never the heading's include.
        frame.MouseLeftButtonDown += self._swallow
        frame.MouseLeftButtonUp += self._swallow
        rows = StackPanel()
        rows.Orientation = Orientation.Vertical
        frame.Child = rows
        return frame, rows

    def _block_row(self, height, edge, right=0):
        """One row of the block: a medium line under it between the
        Excel's sections, a thin one between rows of a group."""
        row = Border()
        row.Height = height
        bottom = {'frame': self.BLOCK_FRAME, 'line': 1}.get(edge, 0)
        row.BorderThickness = Thickness(0, 0, right, bottom)
        row.SetResourceReference(
            Border.BorderBrushProperty,
            'MutedBrush' if edge == 'frame' else 'GridLineBrush')
        return row

    @staticmethod
    def _swallow(sender, args):
        try:
            args.Handled = True
        except Exception:
            pass

    def _build_issue_labels(self):
        """Issue Status:, then each Issued To and Issued Method name, right
        aligned against the revisions; the group named once beside its
        first row. Laid over the drawing headings' free space on the
        RegisterIssueLabels canvas (1.52.0) rather than in a column of its
        own: the names need more width than Rev Date has, and a column
        would be an empty strip down every drawing."""
        self._label_place = None
        canvas = self.label_canvas
        if canvas is not None:
            try:
                canvas.Children.Clear()
            except Exception:
                pass
        self.label_block = None
        self._build_brand()
        if not self.block_shown() or canvas is None:
            return
        widest = 0
        frame, rows = self._block_frame(self.BLOCK_FRAME, 0)
        frame.Margin = Thickness(0)
        edges = ps_revdata.block_edges(self.issue_fields)
        heights = self._block_heights()
        group_seen = set()
        for field, edge, height in zip(self.issue_fields, edges, heights):
            row = self._block_row(height, edge)
            line = StackPanel()
            line.Orientation = Orientation.Horizontal
            line.HorizontalAlignment = HorizontalAlignment.Right
            line.VerticalAlignment = VerticalAlignment.Center
            caption = u''
            if field.group != ps_revdata.STATUS and \
                    field.group not in group_seen:
                group_seen.add(field.group)
                caption = u'Issued to' if field.group == \
                    ps_revdata.ISSUED_TO else u'Method'
            if caption:
                note = TextBlock()
                note.Text = caption
                note.FontSize = 10
                note.FontWeight = FontWeights.Normal
                note.Margin = Thickness(0, 0, 10, 0)
                note.VerticalAlignment = VerticalAlignment.Center
                note.SetResourceReference(TextBlock.ForegroundProperty,
                                          'MutedBrush')
                line.Children.Add(note)
            name = TextBlock()
            name.Text = field.name + (u':' if field.group ==
                                      ps_revdata.STATUS else u'')
            name.FontWeight = FontWeights.Bold
            name.Margin = Thickness(0, 0, 6, 0)
            name.VerticalAlignment = VerticalAlignment.Center
            line.Children.Add(name)
            row.Child = line
            if field.group == ps_revdata.STATUS:
                legend = self.host.settings.text('reg_legend', u'') or u''
                row.ToolTip = (u'Issue Status, per revision. Type one in '
                               u'under a revision; a faint status is the one '
                               u'most of its drawings carry.\n\n' +
                               u'\n'.join([part for part in
                                           legend.split(u'\t') if part]))
            else:
                row.ToolTip = (u'{0} - {1}. Tick under a revision; nothing '
                               u'is written until Apply revisions.'.format(
                                   ps_revdata.GROUP_LABELS.get(field.group,
                                                              u''),
                                   field.name))
            rows.Children.Add(row)
            widest = max(widest, self._measure(caption, 10) +
                         self._measure(name.Text, 12, True) + 28)
        self.label_width = max(110, widest)
        frame.Width = self.label_width
        frame.Height = self.block_height()
        frame.Visibility = Visibility.Hidden
        self.label_block = frame
        try:
            canvas.Children.Add(frame)
        except Exception:
            self.label_block = None

    def label_spot(self, right, top, width, shown):
        """(left, top) for the names' block: its right edge on the drawing
        headings' right edge - against the revisions - level with the
        block. None while the anchor is not on screen. Pure."""
        if not shown or width <= 0:
            return None
        return (float(right) - float(width), float(top))

    def _place_issue_labels(self, sender=None, args=None):
        """The overlays on the heading: the names' block, then the
        register's name and logos in the space left of it."""
        self._place_label_block()
        self._place_brand()

    # ------------------------------------------- the name and logos

    BRAND_TITLE_HEIGHT = 30

    def _build_brand(self):
        """The register's name over the company and client logos, from
        Settings - the Excel's title band, in the heading's free space.
        Frozen issue rows only: that is when the space is there to fill.
        Never hit-tested, so the headings under it still work."""
        self.brand = None
        self._brand_parts = None
        self._brand_place = None
        canvas = self.label_canvas
        if canvas is None or not getattr(self, 'issue_frozen', True):
            return
        settings = self.host.settings
        title = settings.text('reg_title', u'') or u''
        logos = []
        for key in ('reg_logo', 'reg_client_logo'):
            path = settings.text(key, u'') or u''
            if path and os.path.isfile(path):
                bitmap = ps_ui.load_bitmap(path)
                if bitmap is not None:
                    logos.append(bitmap)
        if not title and not logos:
            return
        panel = StackPanel()
        panel.Orientation = Orientation.Vertical
        panel.IsHitTestVisible = False
        name = TextBlock()
        name.Text = title
        name.FontSize = 18
        name.FontWeight = FontWeights.Bold
        name.TextTrimming = TextTrimming.CharacterEllipsis
        name.Height = self.BRAND_TITLE_HEIGHT
        name.SetResourceReference(TextBlock.ForegroundProperty, 'BlueBrush')
        panel.Children.Add(name)
        row = StackPanel()
        row.Orientation = Orientation.Horizontal
        images = []
        for bitmap in logos:
            image = Image()
            image.Source = bitmap
            image.Stretch = Stretch.Uniform
            image.HorizontalAlignment = HorizontalAlignment.Left
            image.VerticalAlignment = VerticalAlignment.Top
            image.Margin = Thickness(0, 0, 18, 0)
            row.Children.Add(image)
            images.append(image)
        panel.Children.Add(row)
        panel.Visibility = Visibility.Hidden
        try:
            canvas.Children.Add(panel)
        except Exception:
            return
        self.brand = panel
        self._brand_parts = (name, row, images)

    def brand_box(self, left, top, height, right, footer, margin=8):
        """(left, top, width, height) for the name and logos: the drawing
        headings' free space above their names, up to the issue block (or
        the last drawing heading). None when there is no room. Pure."""
        box_left = float(left) + margin
        box_top = float(top) + 6
        width = float(right) - margin * 2 - float(left)
        tall = float(height) - float(footer) - 6 - margin
        if width < 120 or tall < 40:
            return None
        return (box_left, box_top, width, tall)

    def logo_size(self, width, height, count, title_height, gap=18):
        """(width, height) each logo may take: the room under the name,
        split evenly between them; (0, 0) when nothing fits. Pure."""
        if not count:
            return (0.0, 0.0)
        tall = float(height) - float(title_height) - 4
        wide = (float(width) - gap * count) / float(count)
        if tall < 20 or wide < 30:
            return (0.0, 0.0)
        return (min(wide, 300.0), min(tall, 120.0))

    def _heading_of_column(self, col_id):
        """The DataGridColumnHeader a drawing column's heading sits in."""
        column = self.columns.get(col_id)
        node = getattr(column, 'Header', None) if column is not None \
            else None
        for _step in range(20):
            if node is None:
                return None
            if isinstance(node, DataGridColumnHeader):
                return node
            try:
                node = VisualTreeHelper.GetParent(node)
            except Exception:
                return None
        return None

    def _place_brand(self):
        brand = self.brand
        if brand is None or self.label_canvas is None:
            return
        first = self._heading_of_column(self.IDENTITY[0][0])
        last = self._heading_of_column(self.IDENTITY[-1][0])
        box = None
        try:
            if first is not None and last is not None and first.IsVisible:
                corner = first.TranslatePoint(Point(0, 0), self.label_canvas)
                end = last.TranslatePoint(Point(last.ActualWidth, 0),
                                          self.label_canvas)
                right = end.X
                if self.label_block is not None and \
                        self._label_place is not None:
                    right = min(right, self._label_place[0] - 8)
                box = self.brand_box(corner.X, corner.Y, first.ActualHeight,
                                     right, self.FOOTER_HEIGHT)
        except Exception:
            box = None
        if box is not None:
            box = tuple([int(round(value)) for value in box])
        if box == self._brand_place:
            return
        self._brand_place = box
        try:
            if box is None:
                brand.Visibility = Visibility.Hidden
                return
            left, top, width, height = box
            name, row, images = self._brand_parts
            brand.Width = width
            brand.Height = height
            name.MaxWidth = width
            wide, tall = self.logo_size(width, height, len(images),
                                        self.BRAND_TITLE_HEIGHT)
            for image in images:
                image.MaxWidth = wide
                image.MaxHeight = tall
                image.Visibility = Visibility.Visible if wide \
                    else Visibility.Collapsed
            Canvas.SetLeft(brand, left)
            Canvas.SetTop(brand, top)
            brand.Visibility = Visibility.Visible
        except Exception:
            pass

    def _place_label_block(self):
        """Keep the names' block on the last drawing heading's spacer.
        LayoutUpdated fires constantly, so it only moves on a change."""
        block = self.label_block
        anchor = self._block_spacers.get(self.IDENTITY[-1][0]) \
            if self._block_spacers else None
        if block is None or anchor is None or self.label_canvas is None:
            return
        try:
            shown = bool(anchor.IsVisible) and anchor.ActualWidth > 0
            corner = anchor.TranslatePoint(Point(anchor.ActualWidth, 0),
                                           self.label_canvas)
            spot = self.label_spot(corner.X, corner.Y, self.label_width,
                                   shown)
        except Exception:
            spot = None
        if spot is not None:
            spot = (int(round(spot[0])), int(round(spot[1])))
        if spot == self._label_place:
            return
        self._label_place = spot
        try:
            if spot is None:
                block.Visibility = Visibility.Hidden
                return
            Canvas.SetLeft(block, spot[0])
            Canvas.SetTop(block, spot[1])
            block.Visibility = Visibility.Visible
        except Exception:
            pass

    def _issue_piece(self, revision):
        """One revision's part of the block: its Issue Status in a box to
        type into, a tick per Issued To and Method column."""
        frame, rows = self._block_frame(0, 1)
        edges = ps_revdata.block_edges(self.issue_fields)
        heights = self._block_heights()
        for field, edge, height in zip(self.issue_fields, edges, heights):
            row = self._block_row(height, edge)
            cell = (revision.key, field.id)
            if field.group == ps_revdata.STATUS:
                box = TextBox()
                box.MinHeight = 0
                box.Padding = Thickness(1, 0, 1, 0)
                box.Margin = Thickness(2, 2, 2, 2)
                box.FontWeight = FontWeights.Bold
                box.HorizontalContentAlignment = HorizontalAlignment.Center
                box.SetResourceReference(TextBox.BorderBrushProperty,
                                         'GridLineBrush')
                box.Background = Brushes.Transparent
                box.Tag = self.issue_derived.get(revision.key, u'')
                box.ToolTip = (u'Issue Status for {0}. Type it and press '
                               u'Enter; staged until Apply revisions.'
                               .format(self._labels([revision.key])))
                box.LostKeyboardFocus += self._make_status_done(cell)
                box.KeyDown += self._make_status_key(cell)
                row.Child = box
            else:
                tick = CheckBox()
                self.host._styled(tick, 'GridCheckBox')
                tick.HorizontalAlignment = HorizontalAlignment.Center
                tick.VerticalAlignment = VerticalAlignment.Center
                tick.ToolTip = u'{0} - {1}'.format(
                    field.name, self._labels([revision.key]))
                tick.Click += self._make_issue_tick(cell)
                row.Child = tick
            self.issue_cells[cell] = row.Child
            self.issue_rows[cell] = row
            rows.Children.Add(row)
        self.issue_pieces[revision.key] = frame
        return frame

    def _forget_issue_piece(self, column_key):
        if not getattr(self, 'issue_cells', None):
            return
        self.issue_pieces.pop(column_key, None)
        for cell in [one for one in self.issue_cells if one[0] == column_key]:
            self.issue_cells.pop(cell, None)
            self.issue_rows.pop(cell, None)

    def _paint_issue_edges(self):
        """The last revision's piece closes the frame on the right."""
        last = self.used_columns[-1].key if self.used_columns else None
        for key, frame in (getattr(self, 'issue_pieces', None) or {}).items():
            try:
                frame.BorderThickness = Thickness(
                    0, self.BLOCK_FRAME,
                    self.BLOCK_FRAME if key == last else 1,
                    self.BLOCK_FRAME)
            except Exception:
                continue

    def issue_values(self):
        """{(column key, field id): value} - stored, with staged edits."""
        return ps_register.meta_values(self.issue_stored, self.pending.edits)

    def _paint_issue_block(self):
        """Every tick and status as stored-plus-staged; a staged one washed
        green. A box being typed in is left alone."""
        if not getattr(self, 'issue_cells', None):
            return
        values = self.issue_values()
        changed = ps_register.meta_changed(self.issue_stored,
                                           self.pending.edits)
        self._issue_painting = True
        try:
            for cell, control in self.issue_cells.items():
                value = values.get(cell, u'')
                try:
                    if isinstance(control, CheckBox):
                        control.IsChecked = value == u'1'
                    elif not control.IsKeyboardFocusWithin:
                        control.Text = value
                except Exception:
                    pass
                row = self.issue_rows.get(cell)
                if row is None:
                    continue
                try:
                    if cell in changed:
                        row.SetResourceReference(Border.BackgroundProperty,
                                                 'GreenWashBrush')
                    else:
                        row.ClearValue(Border.BackgroundProperty)
                except Exception:
                    pass
        finally:
            self._issue_painting = False

    def _field(self, field_id):
        for field in self.issue_fields:
            if field.id == field_id:
                return field
        return None

    def stage_issue(self, cell, value):
        """Stage one issue data value. Returns the edit, or None when it
        changes nothing or the column refuses it."""
        field = self._field(cell[1])
        if field is None:
            return None
        ok, stored = ps_revdata.normalise(field, value)
        if not ok:
            self.host.say(stored)
            self._paint_issue_block()
            return None
        stored = ps_revdata.stored_value(field, stored)
        if self.issue_values().get(cell, u'') == stored:
            return None
        edit = {'kind': ps_register.META, 'target': cell[0],
                'field': cell[1], 'value': stored}
        self._stage(edit)
        return edit

    def _make_issue_tick(self, cell):
        def handler(sender, args):
            if self._issue_painting:
                return
            try:
                ticked = bool(sender.IsChecked)
            except Exception:
                return
            self.stage_issue(cell, u'1' if ticked else u'0')
        return handler

    def _make_status_done(self, cell):
        def handler(sender, args):
            if self._issue_painting:
                return
            try:
                text = u'{0}'.format(sender.Text or u'')
            except Exception:
                return
            self.stage_issue(cell, text)
        return handler

    def _make_status_key(self, cell):
        """Enter stages what was typed; Escape puts the value back."""
        def handler(sender, args):
            try:
                key = args.Key
            except Exception:
                return
            if key in (Key.Enter, Key.Return):
                self.stage_issue(cell, u'{0}'.format(sender.Text or u''))
                try:
                    Keyboard.ClearFocus()
                except Exception:
                    pass
                args.Handled = True
            elif key == Key.Escape:
                try:
                    sender.Text = self.issue_values().get(cell, u'')
                    Keyboard.ClearFocus()
                except Exception:
                    pass
                args.Handled = True
        return handler

    # ---------------------------------------------- unfrozen: as rows

    def issue_cell_text(self, field, value):
        """What an issue data row shows in a revision's cell: the status
        as typed, or an x for a tick - the Excel's mark."""
        if field.kind == 'yesno':
            return u'x' if value == u'1' else u''
        return u'{0}'.format(value or u'')

    def _add_issue_rows(self):
        """The issue data as the first rows of the tab: the group named in
        Drawing No, the column in Drawing Title, a value per revision."""
        edges = ps_revdata.block_edges(self.issue_fields)
        seen = set()
        for index, field in enumerate(self.issue_fields):
            entry = self.table.NewRow()
            entry['key'] = ISSUE_PREFIX + field.id
            caption = u''
            if field.group != ps_revdata.STATUS and field.group not in seen:
                seen.add(field.group)
                caption = u'Issued to' if field.group == \
                    ps_revdata.ISSUED_TO else u'Issued method'
            entry['num'] = caption
            entry['name'] = field.name + (u':' if field.group ==
                                          ps_revdata.STATUS else u'')
            entry['ishead'] = u'0'
            entry['hid'] = u'-1'
            entry['glabel'] = u''
            entry['gpath'] = u''
            entry['gcolor'] = u''
            # Which line runs under it: see _paint_issue_row.
            entry['level'] = edges[index] or u'last'
            entry['vis'] = u'1'
            entry['show'] = u'1'
            entry['hidetick'] = u'1'
            # Ticked, though the tick is hidden: an unticked row is drawn
            # muted (RegisterCell), and these are never out of anything.
            entry['sel'] = True
            # Before every heading: '!' sorts ahead of the digits.
            entry['ord'] = u'!{0:03d}'.format(index)
            self.table.Rows.Add(entry)

    def _paint_issue_rows(self):
        """The issue rows' values - stored plus staged - and a green wash
        (the s_ flag 'add') on a staged one."""
        if not getattr(self, 'issue_fields', None) or \
                getattr(self, 'issue_frozen', True):
            return
        values = self.issue_values()
        changed = ps_register.meta_changed(self.issue_stored,
                                           self.pending.edits)
        fields = dict([(field.id, field) for field in self.issue_fields])
        was = self._suspend
        self._suspend = True
        try:
            for entry in self.table.Rows:
                if not self._is_issue(entry):
                    continue
                field = fields.get(u'{0}'.format(entry['key'])
                                   [len(ISSUE_PREFIX):])
                if field is None:
                    continue
                for revision in self.revisions:
                    cell = (revision.key, field.id)
                    text = self.issue_cell_text(field, values.get(cell, u''))
                    flag = ps_register.PENDING_ADD if cell in changed \
                        else u''
                    try:
                        if u'{0}'.format(entry[revision.key] or u'') != text:
                            entry[revision.key] = text
                        if u'{0}'.format(entry[PENDING_PREFIX + revision.key]
                                         or u'') != flag:
                            entry[PENDING_PREFIX + revision.key] = flag
                    except Exception:
                        continue
        finally:
            self._suspend = was

    def _issue_row_click(self, entry, column_key):
        """A click in an issue row: a tick flips, a status is asked for.
        Staged either way, like a tick in the frozen heading."""
        if not ps_register.is_column_key(column_key):
            return
        field = self._field(u'{0}'.format(entry['key'])[len(ISSUE_PREFIX):])
        if field is None:
            return
        cell = (column_key, field.id)
        now = self.issue_values().get(cell, u'')
        if field.kind == 'yesno':
            self.stage_issue(cell, u'0' if now == u'1' else u'1')
            return
        legend = self.host.settings.text('reg_legend', u'') or u''
        typed = ps_ui.ask_text(
            u'Issue Status', u'{0} for {1}:{2}'.format(
                field.name, self._labels([column_key]),
                u'\n' + u'   '.join([part for part in legend.split(u'\t')
                                     if part]) if legend else u''),
            now or self.issue_derived.get(column_key, u''),
            self.host.theme_name, self.window)
        if typed is None:
            return
        self.stage_issue(cell, typed)

    def _paint_issue_row(self, row, entry):
        """An issue row as the Excel block: the field colour, bold, the
        medium line under Issue Status and between the groups, a thin one
        between rows. Every other row has its line cleared - containers
        are recycled. True when the row was an issue row."""
        if not self._is_issue(entry):
            try:
                row.ClearValue(DataGridRow.BorderThicknessProperty)
                row.ClearValue(DataGridRow.BorderBrushProperty)
            except Exception:
                pass
            return False
        edge = u'{0}'.format(entry['level'])
        first = u'{0}'.format(entry['ord']) == u'!000'
        try:
            row.SetResourceReference(DataGridRow.BackgroundProperty,
                                     'FieldBg')
            row.FontWeight = FontWeights.Bold
            row.BorderThickness = Thickness(
                0, self.BLOCK_FRAME if first else 0, 0,
                1 if edge == 'line' else self.BLOCK_FRAME)
            row.SetResourceReference(
                DataGridRow.BorderBrushProperty,
                'GridLineBrush' if edge == 'line' else 'MutedBrush')
        except Exception:
            pass
        return True

    def _describe_meta(self, edit):
        field = self._field(edit.get('field'))
        name = field.name if field is not None else edit.get('field')
        value = edit.get('value', u'')
        if field is not None and field.kind == 'yesno':
            shown = u'ticked' if value == u'1' else u'unticked'
            return u'{0} {1} on {2}'.format(name, shown,
                                            self._labels([edit['target']]))
        return u'{0} on {1} set to {2}'.format(
            name, self._labels([edit['target']]), value or u'(blank)')

    def _issue_changes(self, edits):
        """The staged issue data as the store takes it: [(revision uid,
        column id, value)], and every revision's element key by uid for
        the parameter push."""
        uids = dict([(revision.key, revision.uid)
                     for revision in self.revisions])
        changes = [(uids.get(edit.get('target'), u''), edit.get('field'),
                    edit.get('value', u'')) for edit in edits]
        keys_by_uid = dict([(revision.uid, revision.element_key)
                            for revision in self.revisions if revision.uid])
        return changes, keys_by_uid

    # ==================================================================
    # revision changes waiting for Apply revisions
    # ==================================================================

    def _present(self):
        """{sheet: columns carrying a revision} as the model has it."""
        found = {}
        for key, row in self.rows_by_key.items():
            found[key] = set([column for column, text in row.cells.items()
                              if u'{0}'.format(text or u'').strip()])
        return found

    def _paint_pending(self):
        """Show the staged edits in the grid: s_ flags for the cell style
        (green +, red struck through) and the + text in a cell gaining a
        revision. Only the cells that differ from last time are written."""
        flags = self.pending.flags(self._present()) if len(self.pending) \
            else {}
        before = self._pending_flags
        self._suspend = True
        try:
            for cell in set(before) | set(flags):
                if before.get(cell) == flags.get(cell):
                    continue
                sheet, column = cell
                entry = self._entries.get(sheet)
                if entry is None:
                    continue
                flag = flags.get(cell, u'')
                row = self.rows_by_key.get(sheet)
                base = row.cells.get(column, u'') if row is not None \
                    else u''
                try:
                    entry[PENDING_PREFIX + column] = flag
                    entry[column] = u'+' if flag == ps_register.PENDING_ADD \
                        else base
                except Exception:
                    continue
        finally:
            self._suspend = False
        self._pending_flags = flags
        self._paint_pending_buttons()
        self._paint_issue_block()
        self._paint_issue_rows()

    def _paint_pending_buttons(self):
        count = len(self.pending)
        cells = sum([ps_register.pending_cells(edit)
                     for edit in self.pending.edits])
        for button, lit in ((self.undo_button, bool(count)),
                            (self.redo_button, bool(self.pending.undone))):
            if button is not None:
                try:
                    button.IsEnabled = lit
                    button.Opacity = 1.0 if lit else 0.4
                except Exception:
                    pass
        # Bottom right: Apply goes green and Discard red once anything is
        # staged (PrimaryButton / DangerButton); grey until then.
        for button in (self.apply_revs_button, self.discard_button):
            if button is not None:
                try:
                    button.IsEnabled = bool(count)
                except Exception:
                    pass
        ps_ui.set_text(self.apply_revs_text,
                       u'Apply revisions ({0})'.format(cells) if count
                       else u'Apply revisions')

    def _describe(self, edit):
        """One line for an edit, for the status line and Apply's list."""
        cells = ps_register.pending_cells(edit)
        plural = u'' if cells == 1 else u's'
        if edit.get('kind') == ps_register.META:
            return self._describe_meta(edit)
        if edit.get('kind') == 'assign':
            return u'{0} assigned to {1} sheet{2}'.format(
                self._labels([edit['target']]), cells, plural)
        if edit.get('kind') == 'change':
            return u'{0} cell{1} changed to {2}'.format(
                cells, plural, self._labels([edit['target']]))
        return u'{0} cell{1} removed'.format(cells, plural)

    def _stage(self, edit):
        self.pending.push(edit)
        target = edit.get('target')
        if target and target not in [one.key for one in self.used_columns]:
            # The column has to be on screen for its + to be seen.
            self.set_show_all_revisions(True, quiet=True)
        self._paint_pending()
        self.host.say(u'Staged: {0}. Nothing is written until Apply '
                      u'revisions - Ctrl+Z undoes it.'.format(
                          self._describe(edit)))

    def undo(self):
        edit = self.pending.undo()
        if edit is None:
            self.host.say(u'Nothing to undo.')
            return
        self._set_picked_cells(set())
        self._paint_pending()
        self.host.say(u'Undone: {0}. Ctrl+Y does it again.'.format(
            self._describe(edit)))

    def redo(self):
        edit = self.pending.redo()
        if edit is None:
            self.host.say(u'Nothing to redo.')
            return
        self._set_picked_cells(set())
        self._paint_pending()
        self.host.say(u'Redone: {0}.'.format(self._describe(edit)))

    def discard_pending(self):
        if not len(self.pending):
            return
        count = len(self.pending)
        self.pending.clear()
        self._set_picked_cells(set())
        self._paint_pending()
        self.host.say(u'{0} staged change{1} thrown away - Revit was never '
                      u'touched.'.format(count, u'' if count == 1 else u's'))

    def can_close(self):
        """Ask before closing over staged changes. True to go on."""
        if not len(self.pending):
            return True
        answer = ps_ui.Prompt(
            title=u'Document Register',
            headline=u'{0} revision change{1} not applied.'.format(
                len(self.pending), u' is' if len(self.pending) == 1
                else u's are'),
            message=u'Closing now throws them away; the sheets in Revit '
                    u'stay as they are.',
            detail=u'\n'.join([self._describe(edit)
                               for edit in self.pending.edits]),
            primary=u'Discard and close', secondary=u'Keep it open',
            theme_name=self.host.theme_name, owner=self.window).show()
        return answer == 'primary'

    def apply_revisions(self):
        """Write every staged edit, in the order made, in one job."""
        if not len(self.pending):
            return
        edits = list(self.pending.edits)
        removes = [edit for edit in edits if edit['kind'] == 'remove']
        if removes:
            answer = ps_ui.Prompt(
                title=u'Apply revisions',
                headline=u'Apply {0} revision change{1}?'.format(
                    len(edits), u'' if len(edits) == 1 else u's'),
                message=(u'Deletes the rev clouds from all associated views '
                         u'on the sheet, for every revision staged to be '
                         u'removed.\n\nA revision added to the sheet by hand '
                         u'is taken off it too. A cloud that also shows on a '
                         u'sheet not staged is asked about afterwards. '
                         u'Issued revisions are left: Revit locks them.'),
                detail=u'\n'.join([self._describe(edit) for edit in edits]),
                primary=u'Apply', secondary=u'Cancel',
                theme_name=self.host.theme_name, owner=self.window).show()
            if answer != 'primary':
                self.host.say(u'Apply revisions cancelled - still staged.')
                return
        touched = set()
        for edit in edits:
            touched |= set(edit.get('sheets') or [])
            touched |= set((edit.get('picks') or {}).keys())
        sheets = dict([(key, self.elements.get(key)) for key in touched
                       if self.elements.get(key) is not None])
        doc = self.host.doc
        # Issue data edits are written together, in the order made, in a
        # transaction of their own: they are one store, not one per sheet.
        meta = [edit for edit in edits
                if edit.get('kind') == ps_register.META]
        others = [edit for edit in edits
                  if edit.get('kind') != ps_register.META]
        changes, keys_by_uid = self._issue_changes(meta)

        def job(uiapp):
            """On Revit's thread: each edit in turn, each its own
            transaction, so one Revit refuses does not undo the rest."""
            results = [self._run_edit(doc, edit, sheets, False)
                       for edit in others]
            if meta:
                results.append(self._run_meta(doc, changes, keys_by_uid))
            self.host._on_ui(lambda: self._applied(results, False))

        if self.host._queue(job):
            self.host.say(u'Writing {0} revision change{1}...'.format(
                len(edits), u'' if len(edits) == 1 else u's'))

    @staticmethod
    def _run_meta(doc, changes, keys_by_uid):
        """The staged issue data, written. In _applied's shape: (edit,
        picks, (done, skipped, errors), report)."""
        try:
            done, problems = ps_revdata.write_changes(doc, changes,
                                                      keys_by_uid)
        except Exception as err:
            done, problems = 0, [u'The issue data was not written: {0}'
                                 .format(err)]
        return ({'kind': ps_register.META}, {},
                (range(done), [], list(problems)), {})

    @staticmethod
    def _run_edit(doc, edit, sheets, include_shared, picks=None):
        """One staged edit, written. Returns (edit, picks in element keys,
        result, report)."""
        report = {}
        target = ps_register.element_of(edit.get('target'))
        if picks is None:
            picks = {}
            for sheet, columns in (edit.get('picks') or {}).items():
                picks[sheet] = set([ps_register.element_of(column)
                                    for column in columns])
        try:
            if edit['kind'] == 'assign':
                result = ps_revisions.assign_to_sheets(
                    doc, list(edit['sheets']), target, sheets)
            elif edit['kind'] == 'change':
                result = ps_revisions.swap_on_sheets(doc, picks, target,
                                                     sheets, include_shared,
                                                     report)
            else:
                result = ps_revisions.remove_on_sheets(doc, picks, sheets,
                                                       include_shared, report)
        except Exception as err:
            result = ([], [], [u'Nothing was changed: {0}'.format(err)])
        return edit, picks, result, report

    def _applied(self, results, second):
        """After Apply revisions: read the model, then ask about clouds
        that show on sheets not staged, then list what Revit refused."""
        self.pending.clear()
        self._pending_flags = {}
        self.reload()
        lines, written, leftovers, shared = [], 0, [], []
        for edit, picks, (done, skipped, errors), report in results:
            written += len(done)
            for one in skipped:
                if len(one) == 2:
                    lines.append(u'{0}: {1}'.format(
                        self._sheet_label(one[0]), one[1]))
                else:
                    lines.append(u'{0}, {1}: {2}'.format(
                        self._sheet_label(one[0]),
                        self._element_label(one[1]), one[2]))
            lines.extend(errors)
            if edit['kind'] == 'assign' or second or \
                    not report.get('shared'):
                continue
            shared.extend(report['shared'])
            finished = set(done)
            rest = {}
            for sheet, olds in picks.items():
                left = set([old for old in olds
                            if (sheet, old) not in finished])
                if left:
                    rest[sheet] = left
            if rest:
                leftovers.append((edit, rest))
        summary = u'{0} revision change{1} written.'.format(
            written, u'' if written == 1 else u's')
        if leftovers:
            mode = 'remove' if all([edit['kind'] == 'remove'
                                    for edit, _rest in leftovers]) \
                else 'change'
            if self._ask_shared(mode, shared, summary):
                self._again(leftovers)
                return
        if not lines:
            self.host.say(summary)
            return
        self.host.say(u'{0} {1} left as {2} {3}.'.format(
            summary, len(lines), u'it' if len(lines) == 1 else u'they',
            u'was' if len(lines) == 1 else u'were'))
        ps_ui.Prompt(
            title=u'Apply revisions',
            headline=u'Not everything could be written.',
            message=summary + u' The rest are listed below, with why; the '
                    u'register shows the model as it now is.',
            detail=u'\n'.join(lines), primary=u'Close',
            theme_name=self.host.theme_name, owner=self.window).show()

    def _again(self, leftovers):
        """The second pass: only the cells still to do, shared clouds
        included."""
        touched = set()
        for _edit, rest in leftovers:
            touched |= set(rest.keys())
        sheets = dict([(key, self.elements.get(key)) for key in touched
                       if self.elements.get(key) is not None])
        doc = self.host.doc

        def job(uiapp):
            """On Revit's thread."""
            results = [self._run_edit(doc, edit, sheets, True, rest)
                       for edit, rest in leftovers]
            self.host._on_ui(lambda: self._applied(results, True))

        if self.host._queue(job):
            self.host.say(u'Now the clouds shared with other sheets...')

    def _reveal_isolated(self):
        """Isolating a revision whose sheets are not in the set: switch to
        All sheets so they can be found. Returns how many were hidden."""
        if self.show_mode != 'included' or not self.isolated:
            return 0
        hidden = ps_register.outside_set(
            list(self.rows_by_key.keys()), self.isolated, self.included,
            self._filled)
        if hidden:
            self.set_show('all')
        return len(hidden)

    # ==================================================================
    # folding the series away
    # ==================================================================

    def _tab_groups(self):
        """The path of every heading on the tab on screen."""
        return list(self.group_paths.values())

    def toggle_group(self, path):
        key = (self.tab_label, path)
        if key in self.collapsed:
            self.collapsed.discard(key)
        else:
            self.collapsed.add(key)
        self._apply_filters()
        self._paint_collapse_button()
        self._say()

    def _folded(self, group_id):
        """Whether a heading, or any heading above it, is folded away."""
        steps = 0
        while group_id is not None and group_id in self.group_paths \
                and steps < 4:
            if (self.tab_label, self.group_paths[group_id]) in self.collapsed:
                return True
            group_id = self.group_parent.get(group_id)
            steps += 1
        return False

    def toggle_collapse_all(self):
        labels = self._tab_groups()
        if not labels:
            return
        folded = [label for label in labels
                  if (self.tab_label, label) in self.collapsed]
        if len(folded) == len(labels):
            for label in labels:
                self.collapsed.discard((self.tab_label, label))
        else:
            for label in labels:
                self.collapsed.add((self.tab_label, label))
        self._apply_filters()
        self._paint_collapse_button()
        self._say()

    def _paint_collapse_button(self):
        labels = self._tab_groups()
        ps_ui.set_visible(self.collapse_button, bool(labels))
        folded = [label for label in labels
                  if (self.tab_label, label) in self.collapsed]
        everything = bool(labels) and len(folded) == len(labels)
        ps_ui.set_text(self.collapse_text,
                       u'Expand all' if everything else u'Collapse all')
        ps_ui.set_visible(self.collapse_icon, not everything)
        ps_ui.set_visible(self.expand_icon, everything)

    # ==================================================================
    # filtering
    # ==================================================================

    def _search_changed(self, sender, args):
        try:
            if self._search_timer is None:
                timer = DispatcherTimer()
                timer.Interval = TimeSpan.FromMilliseconds(self.SEARCH_MS)
                timer.Tick += self._search_tick
                self._search_timer = timer
            self._search_timer.Stop()
            self._search_timer.Start()
        except Exception:
            self._apply_filters()

    def _search_tick(self, sender, args):
        try:
            self._search_timer.Stop()
        except Exception:
            pass
        self._apply_filters()
        self._say()

    def _needle(self):
        try:
            return u'{0}'.format(self.search_box.Text or u'').strip().lower()
        except Exception:
            return u''

    def _passes_view(self, entry, values, filters, needle):
        """Search, column filters and Included only - everything but folding."""
        if needle and needle not in (values.get('num', u'') + u' ' +
                                     values.get('name', u'')).lower():
            return False
        if not ps_register.passes(values, filters):
            return False
        if self.show_mode == 'included' and \
                u'{0}'.format(entry['key']) not in self.included:
            return False
        if self.isolated and not [key for key in self.isolated
                                  if values.get(key)]:
            return False
        return True

    def _apply_filters(self):
        """Take the filter decision once and write it into ``vis``.

        ``show`` is then ``vis`` minus anything under a folded heading. Two
        reasons to hide a row need two flags: collapsed onto one, unfolding
        a series would bring back drawings the filter had removed.
        """
        self._commit_edits()
        needle = self._needle()
        alive = set()
        for entry in self.table.Rows:
            if self._is_heading(entry):
                continue
            if self._is_issue(entry):
                # Always there: a search or a filter narrows the drawings,
                # not the issue data above them.
                entry['vis'] = u'1'
                entry['show'] = u'1'
                continue
            visible = self._passes_view(entry, self._values(entry),
                                        self.column_filters, needle)
            group = self._as_int(entry['hid'])
            entry['vis'] = u'1' if visible else u'0'
            entry['show'] = u'1' if (visible and not self._folded(group)) \
                else u'0'
            if visible:
                while group is not None and group >= 0:
                    alive.add(group)
                    group = self.group_parent.get(group)
        # A heading stays while anything under it passes the filter, folded
        # or not - folding hides the drawings, not the way back to them. A
        # series heading goes with its discipline when that is folded.
        for entry in self.table.Rows:
            if not self._is_heading(entry):
                continue
            group = self._as_int(entry['hid'])
            parent = self.group_parent.get(group)
            shown = group in alive and not (parent is not None and
                                             self._folded(parent))
            entry['show'] = u'1' if shown else u'0'
            entry['vis'] = entry['show']
            level = self._as_int(entry['level'])
            wanted = self._heading_text(
                level, (self.tab_label, self.group_paths.get(group)) in
                self.collapsed, u'{0}'.format(entry['glabel']))
            if u'{0}'.format(entry['num']) != wanted:
                entry['num'] = wanted
        self._paint_ticks()
        self._paint_reset_button()
        self._sync_revision_columns()
        self._paint_pick_buttons()

    def _paint_ticks(self):
        """Heading ticks, and the one in the column heading, only where
        they mean something - see ps_register.heading_ticks_shown."""
        drawings = False
        for entry in self.table.Rows:
            if self._is_drawing(entry) and \
                    u'{0}'.format(entry['show']) == u'1':
                drawings = True
                break
        shown = ps_register.heading_ticks_shown(
            self.show_mode == 'included', drawings)
        flag = u'0' if shown else u'1'
        was = self._suspend
        self._suspend = True
        try:
            for entry in self.table.Rows:
                wanted = flag if self._is_heading(entry) else \
                    (u'1' if self._is_issue(entry) else u'0')
                if u'{0}'.format(entry['hidetick'] or u'') != wanted:
                    entry['hidetick'] = wanted
        finally:
            self._suspend = was
        if self.header_tick is not None:
            try:
                self.header_tick.Visibility = Visibility.Visible if shown \
                    else Visibility.Hidden
            except Exception:
                pass

    def _typing(self):
        """Whether the keyboard is in a text box."""
        try:
            return isinstance(Keyboard.FocusedElement, TextBox)
        except Exception:
            return False

    def _key_down(self, sender, args):
        """F5 re-reads; Escape lets go of picked revisions and cells;
        Ctrl+PageUp and Ctrl+PageDown cycle the tabs."""
        try:
            key = args.Key
        except Exception:
            return
        if key == Key.F5:
            self.reload()
            args.Handled = True
            return
        if key == Key.Escape and (self.picked_cells or self.picked_columns):
            self.clear_picks()
            args.Handled = True
            return
        if not ps_ui.ctrl_down():
            return
        if key in (Key.Z, Key.Y) and not self._typing():
            # A search box keeps its own Ctrl+Z.
            if key == Key.Z:
                self.undo()
            else:
                self.redo()
            args.Handled = True
            return
        if key in (Key.PageDown, Key.PageUp):
            step = 1 if key == Key.PageDown else -1
            index = self.tab_index + step
            while 0 <= index < len(self.tabs) and not self._tab_shows(index):
                index += step
            if 0 <= index < len(self.tabs):
                self.select_tab(index)
            args.Handled = True

    # ==================================================================
    # the Excel register
    # ==================================================================

    def add_to_export(self):
        """Whether an Export run should write the register too."""
        try:
            return bool(self.export_check.IsChecked)
        except Exception:
            return self.host.settings.flag('reg_add_to_export', False)

    def _export_toggled(self, sender, args):
        self._setting('reg_add_to_export', u'1' if self.add_to_export()
                      else u'0')
        # The Create tab lists it as one more file the run will write.
        try:
            self.host._refresh_plan()
        except Exception:
            pass

    def included_rows(self):
        """The drawings in the register, in drawing number order."""
        return [row for row in self.rows
                if u'{0}'.format(row.key) in self.included]

    def export_info(self):
        settings = self.host.settings
        info = ps_regexport.Info()
        info.title = settings.text('reg_title', u'') or info.title
        logo = settings.text('reg_logo', u'')
        info.logo = logo if logo and os.path.isfile(logo) else u''
        client = settings.text('reg_client_logo', u'')
        info.client_logo = client if client and os.path.isfile(client) \
            else u''
        # Kept blank on purpose means no snapshot column, so the stored
        # text is used as it is rather than falling back to the default.
        info.snapshot = settings.store.get('reg_snapshot',
                                           info.snapshot) or u''
        info.legend = ps_config.get_list(settings.store, 'reg_legend',
                                         info.legend)
        # The Issued To / Method rows and each Issue Status come from the
        # Revision Manager's own columns, kept in the model.
        try:
            info.revision_columns, info.revision_values = \
                ps_revdata.read(self.host.doc)
        except Exception:
            info.revision_columns, info.revision_values = [], {}
        info.footer = settings.text('reg_footer', u'')
        info.paper = settings.text('reg_paper', u'') or info.paper
        info.series_param = self.series_param
        info.hide_unused = self.hide_unused
        info.skip = set(self.skip_tabs)
        project = ps_model.project_info(self.host.doc)
        try:
            info.project_number = ps_model.to_text(project.Number)
            info.project_name = ps_model.to_text(project.Name)
        except Exception:
            pass
        try:
            info.model_name = ps_model.to_text(self.host.doc.Title)
        except Exception:
            pass
        return info

    def file_name(self, today=None):
        """<project> - Document Register - YYYY-MM-DD.xlsx"""
        info = self.export_info()
        project = info.project_name or info.model_name or u'Project'
        return ps_register.register_file_name(project, today)

    def write_excel(self, path):
        """(ok, message)."""
        self.ensure_loaded()
        rows = self.included_rows()
        if not rows:
            return False, (u'Nothing is in the register yet - tick the '
                           u'drawings to include on the Document Register '
                           u'tab.')
        info = self.export_info()
        if not ps_regexport.worksheets(rows, info.skip):
            return False, (u'Every discipline with drawings in the register '
                           u'is unticked on the tabs along the bottom, so '
                           u'there is no worksheet to write.')
        return ps_regexport.write(path, self.revisions, rows, info)

    def export_now(self):
        """Write the register now, wherever the user says."""
        self.ensure_loaded()
        if not self.included:
            self.host.say(u'Tick at least one drawing to include first.')
            return
        path = ps_ui.pick_file(True, u'Export the Document Register', '.xlsx',
                               self.file_name(), u'Excel workbook')
        if not path:
            return
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'
        ok, message = self.write_excel(path)
        self.host.say(message)
        if not ok:
            ps_ui.Prompt(
                title=u'Document Register',
                headline=u'The register was not written.',
                message=message, primary=u'Close',
                theme_name=self.host.theme_name, owner=self.window).show()
            return
        answer = ps_ui.Prompt(
            title=u'Document Register',
            headline=u'Document Register exported. Open the folder?',
            message=path,
            primary=u'Open folder', secondary=u'Not now',
            theme_name=self.host.theme_name, owner=self.window).show()
        if answer == 'primary':
            ps_export.open_folder(os.path.dirname(path), path)

    def export_into(self, folder, report):
        """Write the register alongside an export run's drawings.

        ``folder`` is the one above the run's PDF and DWG folders, decided
        by the window from the run's own plan - see register_folder. Called
        on Revit's thread from the run itself; never raises, and every step
        goes in the debug log, so "it was not there" can be told apart from
        "it went somewhere else".
        """
        path = u''
        try:
            ps_export.debug(u'Document Register: writing into "{0}"'
                            .format(folder))
            if not folder:
                ok, message = False, (u'The run had no folder to put the '
                                      u'register in.')
            else:
                path = os.path.join(folder, self.file_name())
                ok, message = self.write_excel(path)
        except Exception as err:
            ok, message = False, u'{0}'.format(err)
        ps_export.debug(u'Document Register: {0} - {1}'.format(
            u'written' if ok else u'FAILED', message if not ok else path))
        report.add(ps_export.Outcome(u'register', u'Document Register',
                                     u'xlsx', path, ok, message))
        return ok

    # ==================================================================
    # saying what is going on
    # ==================================================================

    def _say_source(self):
        disc = self.discipline_param or u'(not set)'
        series = self.series_param or u'(not set)'
        ps_ui.set_text(self.source, u'Tabs by {0}  ·  grouped by '
                                    u'{1}'.format(disc, series))

    def _say_notes(self):
        notes = list(self._warnings)
        if self.loaded and self.rows:
            if self.discipline_param and not ps_register.has_values(
                    self.rows, lambda row: row.discipline):
                notes.append(u'{0} has no value on any sheet, so every '
                             u'drawing is on the All tab.'.format(
                                 self.discipline_param))
            if self.series_param and not ps_register.has_values(
                    self.rows, lambda row: row.series):
                notes.append(u'{0} has no value on any sheet, so the '
                             u'drawings are not grouped.'.format(
                                 self.series_param))
            if not self.revisions:
                notes.append(u'No revisions in this model yet, so there are '
                             u'no revision columns.')
        ps_ui.set_text(self.note, u'  '.join(notes))
        ps_ui.set_visible(self.note, bool(notes))

    def _say(self):
        total = len(self.rows)
        everywhere = len([key for key in self.rows_by_key
                          if key in self.included])
        visible = self._visible_keys()
        on_tab = 0
        in_tab = 0
        if self.tabs and 0 <= self.tab_index < len(self.tabs):
            members = self.tabs[self.tab_index][1]
            on_tab = len(members)
            in_tab = len([row for row in members
                          if u'{0}'.format(row.key) in self.included])
        ps_ui.set_text(self.summary,
                       u'{0} of {1} drawing{2} in the register  ·  {3} of '
                       u'{4} on this tab'.format(
                           everywhere, total, u'' if total == 1 else u's',
                           in_tab, on_tab))
        if self.header_tick is not None:
            try:
                self.header_tick.IsChecked = bool(visible) and all(
                    [key in self.included for key in visible])
            except Exception:
                pass

    def _as_int(self, value):
        try:
            return int(u'{0}'.format(value))
        except Exception:
            return -1
