# -*- coding: utf-8 -*-
"""The Pro Sheets Exporter window.

Modeless, owned to Revit's main window, so Revit stays fully navigable and
editable while the tool is open. Everything that touches the Revit API on the
way out goes through an ``ExternalEvent`` - a modeless window cannot start a
transaction or call ``Document.Export`` directly.

**Never wait for an ExternalEvent from the window that raised it.** Revit
raises it on the same thread the window lives on, so blocking that thread to
wait is a deadlock: the handler never gets a turn and the tool looks dead.
The work is queued, the handler runs it, and everything the user sees is
marshalled back onto the dispatcher.
"""

import ps_refs  # noqa: F401  - must be first

import os
import time

from System import Action, Boolean, Object, String
from System.Data import DataTable
from System import TimeSpan
from System.Windows import (CornerRadius, FontWeights, FrameworkElement,
                            GridLength, GridUnitType, HorizontalAlignment,
                            TextTrimming, Thickness, VerticalAlignment,
                            Visibility)
from System.Windows.Controls import (Border, Button, CheckBox, ColumnDefinition,
                                     ContextMenu, DataGridLength, WrapPanel,
                                     DataGridLengthUnitType, DataGridRow,
                                     DataGridTemplateColumn,
                                     DataGridTextColumn, Grid, MenuItem,
                                     Orientation, Separator, StackPanel,
                                     TextBlock, TextBox)
from System.Windows.Controls.Primitives import DataGridColumnHeader
from System.Windows.Threading import DispatcherTimer
from System.Windows.Data import Binding
from System.Windows.Markup import XamlReader
from System.Windows.Media import Brushes, VisualTreeHelper

from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler

import ps_config
import ps_context
import ps_export
import ps_model
import ps_namewin
import ps_naming
import ps_orderwin
import ps_paths
import ps_pickwin
import ps_ramp
import ps_register
import ps_revisions
import ps_regview
import ps_setupwin
import ps_tokenwin
import ps_ui
import theme


NO_TEMPLATE = u'(no template)'
REVIT_PDF = u'Revit built-in PDF export'
NO_SET = u'(every sheet)'
DEFAULT_DWG_SETUP = u'(Revit default settings)'

RASTER_CHOICES = [(u'Low', 'low'), (u'Medium', 'medium'),
                  (u'High', 'high'), (u'Presentation', 'presentation')]
COLOUR_CHOICES = [(u'Color', 'color'), (u'Grayscale', 'grayscale'),
                  (u'Black lines', 'blackline')]
MARGIN_CHOICES = [(u'No Margin', 'nomargin'),
                  (u'Printer Limit', 'printerlimit'),
                  (u'User Defined', 'usermargin')]
DWG_VERSIONS = [(u'As the setup says', 'default'), (u'AutoCAD 2018', 'R2018'),
                (u'AutoCAD 2013', 'R2013'), (u'AutoCAD 2010', 'R2010'),
                (u'AutoCAD 2007', 'R2007'), (u'AutoCAD 2004', 'R2004')]

NWC_PARAM_CHOICES = [(u'All', 'all'), (u'Elements', 'elements'),
                     (u'None', 'none')]
NWC_COORD_CHOICES = [(u'Shared', 'shared'), (u'Internal', 'internal')]

IFC_VERSION_CHOICES = [(label, key)
                       for key, label, _names in ps_export.IFC_VERSIONS]
IFC_FILE_TYPE_CHOICES = [(label, key)
                         for key, label, _suffix in ps_export.IFC_FILE_TYPES]
IFC_DETAIL_CHOICES = [(label, key)
                      for key, label, _lod in ps_export.IFC_DETAIL_LEVELS]
IFC_ORIGIN_CHOICES = [(label, key)
                      for key, label, _value in ps_export.IFC_ORIGINS]
IFC_BOUNDARY_CHOICES = [(u'None', '0'), (u'1st Level', '1'),
                        (u'2nd Level', '2')]
IFC_LINKED_CHOICES = [(u'Do not export', 'none'),
                      (u'Export as separate IFCs', 'separate')]
IFC_IN_SESSION = u'<In Session>'
IFC_DEFAULT_PHASE = u'Default phase to export'


# ==========================================================================
# the NWC and IFC fields
#
# profile key, control, kind, default. "kind" is 'flag', 'text', or a
# choices list for a combo. One table drives reading the controls into a
# profile and writing a profile back onto them, which is the only way
# sixty tickboxes stay in step - the PDF panel above is hand written both
# ways and every option added to it has had to be added twice.
# ==========================================================================

NWC_FIELDS = [
    ('nwc.parts', 'NwcPartsCheck', 'flag', False),
    ('nwc.element_ids', 'NwcElementIdsCheck', 'flag', True),
    ('nwc.parameters', 'NwcParamsCombo', NWC_PARAM_CHOICES, 'all'),
    ('nwc.properties', 'NwcPropertiesCheck', 'flag', False),
    ('nwc.linked_files', 'NwcLinkedCheck', 'flag', False),
    ('nwc.room_as_attribute', 'NwcRoomAttrCheck', 'flag', True),
    ('nwc.urls', 'NwcUrlsCheck', 'flag', True),
    ('nwc.coordinates', 'NwcCoordsCombo', NWC_COORD_CHOICES, 'shared'),
    ('nwc.divide_levels', 'NwcLevelsCheck', 'flag', True),
    ('nwc.room_geometry', 'NwcRoomGeomCheck', 'flag', True),
    ('nwc.find_materials', 'NwcMaterialsCheck', 'flag', True),
    ('nwc.linked_cad', 'NwcLinkedCadCheck', 'flag', True),
    ('nwc.lights', 'NwcLightsCheck', 'flag', False),
    ('nwc.faceting', 'NwcFacetingBox', 'text', '1'),
]

IFC_FIELDS = [
    ('ifc.version', 'IfcVersionCombo', IFC_VERSION_CHOICES, 'IFC2x3CV2'),
    ('ifc.file_type', 'IfcFileTypeCombo', IFC_FILE_TYPE_CHOICES, 'ifc'),
    ('ifc.space_boundaries', 'IfcSpaceBoundCombo', IFC_BOUNDARY_CHOICES, '0'),
    ('ifc.origin', 'IfcOriginCombo', IFC_ORIGIN_CHOICES, 'shared'),
    ('ifc.split_by_level', 'IfcSplitCheck', 'flag', False),
    ('ifc.steel', 'IfcSteelCheck', 'flag', True),
    ('ifc.linked_files', 'IfcLinkedCombo', IFC_LINKED_CHOICES, 'none'),
    ('ifc.export_2d', 'Ifc2dCheck', 'flag', False),
    ('ifc.visible_only', 'IfcVisibleOnlyCheck', 'flag', True),
    ('ifc.rooms_in_3d', 'IfcRoomsIn3dCheck', 'flag', False),
    ('ifc.detail', 'IfcDetailCombo', IFC_DETAIL_CHOICES, 'low'),
    ('ifc.revit_psets', 'IfcRevitPsetsCheck', 'flag', False),
    ('ifc.common_psets', 'IfcCommonPsetsCheck', 'flag', True),
    ('ifc.base_quantities', 'IfcQuantitiesCheck', 'flag', False),
    ('ifc.material_psets', 'IfcMaterialPsetsCheck', 'flag', False),
    ('ifc.schedule_psets', 'IfcSchedulePsetsCheck', 'flag', False),
    ('ifc.specific_schedules', 'IfcSpecificSchedulesCheck', 'flag', False),
    ('ifc.user_psets', 'IfcUserPsetsCheck', 'flag', False),
    ('ifc.type_properties', 'IfcTypePropsCheck', 'flag', False),
    ('ifc.user_psets_file', 'IfcUserPsetsBox', 'text', ''),
    ('ifc.parameter_map', 'IfcParamMapCheck', 'flag', False),
    ('ifc.parameter_map_file', 'IfcParamMapBox', 'text', ''),
    ('ifc.parts_as_elements', 'IfcPartsAsElementsCheck', 'flag', False),
    ('ifc.solid_model', 'IfcSolidModelCheck', 'flag', False),
    ('ifc.active_view_geometry', 'IfcActiveViewGeomCheck', 'flag', False),
    ('ifc.family_type_reference', 'IfcFamilyTypeRefCheck', 'flag', False),
    ('ifc.room_boundary_2d', 'Ifc2dRoomBoundaryCheck', 'flag', False),
    ('ifc.site_elevation', 'IfcSiteElevationCheck', 'flag', False),
    ('ifc.store_guid', 'IfcStoreGuidCheck', 'flag', False),
    ('ifc.bounding_box', 'IfcBoundingBoxCheck', 'flag', False),
    ('ifc.triangulation', 'IfcTriangulationCheck', 'flag', False),
    ('ifc.type_name_only', 'IfcTypeNameOnlyCheck', 'flag', False),
    ('ifc.visible_name', 'IfcVisibleNameCheck', 'flag', False),
]


# ==========================================================================
# the format registry
#
# One row per format on the Format tab: the id used in the profile and in
# the job folders, the three controls that belong to it, and whether it
# can actually be exported yet. Before 1.8.0 this lived as pairs of
# hardcoded control names in six different methods, which is how DGN and
# IMG ended up drawn but unreachable. Adding a format is now one row plus
# its panel.
# ==========================================================================

# id, tick, tile, group, panel, label, live
FORMATS = [
    ('pdf', 'PdfCheck', 'PdfTile', 'PdfGroup', 'PdfPanel', u'PDF', True),
    ('dwg', 'DwgCheck', 'DwgTile', 'DwgGroup', 'DwgPanel', u'DWG', True),
    ('dwf', 'DwfCheck', 'DwfTile', 'DwfGroup', '', u'DWF', False),
    ('nwc', 'NwcCheck', 'NwcTile', 'NwcGroup', 'NwcPanel', u'NWC', True),
    ('ifc', 'IfcCheck', 'IfcTile', 'IfcGroup', 'IfcPanel', u'IFC', True),
]

# Formats that only make sense for a view, and only for a 3D one. Both
# exporters are scoped to a single view: Navisworks has no concept of a
# sheet at all, and an IFC of a drawing sheet would hold nothing.
VIEW_ONLY_FORMATS = ('nwc', 'ifc')


def live_formats():
    return [row[0] for row in FORMATS if row[6]]


def format_row(fmt):
    for row in FORMATS:
        if row[0] == fmt:
            return row
    return None


def format_label(fmt):
    row = format_row(fmt)
    return row[5] if row is not None else u'{0}'.format(fmt).upper()


def _pick(choices, stored, default_index=0):
    for index, pair in enumerate(choices):
        if pair[1] == stored:
            return index
    return default_index


# ==========================================================================
# the external event
# ==========================================================================

class ExportHandler(IExternalEventHandler):
    """Runs one queued export on Revit's API thread."""

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
        return 'RevoBIM Pro Sheets Exporter'


# The window, the handler and the event all have to be parked at module
# level: pyRevit's persistent engine will collect anything it does not
# consider referenced, and it takes the live window with it.
WINDOW = None
HANDLER = None
EVENT = None


# ==========================================================================
# the window
# ==========================================================================

class ProSheetsWindow(object):

    # The tabs, by name. Nothing compares _tab_index() with a bare number:
    # 1.20.0 put the Document Register second, and every "2" in this file
    # that meant Create would have quietly started meaning Format - the
    # Export button on the wrong page, the run opening the wrong tab. The
    # bench rule tab_indices fails on a literal.
    TAB_SELECTION = 0
    TAB_REGISTER = 1
    TAB_FORMAT = 2
    TAB_CREATE = 3

    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.uidoc = uiapp.ActiveUIDocument
        self.doc = self.uidoc.Document

        self.settings = ps_config.Settings()
        if getattr(self.settings, 'migrated', False):
            # An older settings file brought up to this build's
            # defaults. Written back at once so it only happens once.
            try:
                self.settings.save()
            except Exception:
                pass
        # Two separate things: the mode the user chose, which is what gets
        # saved, and the palette that mode currently resolves to. Before
        # 1.10.0 only the palette was kept, so the first click on the chip
        # pinned the window for good and it never followed Revit again.
        self.theme_mode = theme.mode(self.settings.text('theme_mode'))
        self.theme_name = theme.resolve(self.theme_mode)
        self._theme_timer = None
        # Heading colours on the Selection tab (1.54.0): greyscale until
        # changed; colours picked for a heading are the project's, shared
        # with the Document Register.
        self.heading_mode = ps_ramp.heading_mode(
            self.settings.text('sel_heading_mode', u'') or ps_ramp.GREY)
        try:
            self.heading_custom = ps_config.read_heading_colours(self.doc)
        except Exception:
            self.heading_custom = {}
        self.run_labels = []

        self.rows = []
        # The Views list's Project Browser columns (see
        # ps_model.browser_columns) - read with the views.
        self.browser_names = []
        self.rows_by_key = {}
        self.sheet_sets = {}
        self.ifc_phases = {}
        self.printer_list = []
        self.preferred_printer = u''
        self.native_pdf = False
        self._printer_refused = None
        self.catalogue = []
        self.rules = ps_naming.default_rules()
        # Sheets and views are named independently: self.rules is always the
        # set for the mode on screen, the other waits here.
        self.rules_by_mode = {'sheets': ps_naming.default_rules('sheets'),
                              'views': ps_naming.default_rules('views')}
        self.isolated_keys = None
        self.profile = ps_config.defaults()
        self.combine_order = []

        self.exporting = False
        # An Express Export run: no prompts, no report window.
        self._express_run = False
        self.stop_wanted = False
        self.last_report = None
        self._hunted_folder = u''
        self._issue_folder = u''
        self._hunt_found_any = False
        self._preselected_keys = set()
        # One ordered list of every column on the Selection grid, fixed
        # and added alike. See the columns section for why.
        self.column_order = ProSheetsWindow.default_column_order('sheets')
        # Filled in properly once the settings are readable; see
        # _apply_profile, which is where a template gets its say.

        # The order each mode was last left in, so switching to Views and
        # back does not throw away the columns added to either.
        self.column_orders = {}
        self.column_search = {}
        self.search_boxes = {}
        self.header_tick = None
        self.sort_stack = []
        self.grouped = True
        self.collapsed = set()
        self.groups = {}
        self._suspend_group_toggle = False
        self._template_sort = u''
        # The rows highlighted when a tick box was last clicked. Taken
        # in _row_click, because the grid may drop the selection before
        # the tick itself is reported.
        self._tick_selection = set()
        # Every run gets a colour; only the longer ones get a heading, so
        # "how many groups" has two honest answers and the status line
        # needs both.
        self.run_count = 0
        self.header_outlines = {}
        self.header_badges = {}
        self._sorted_rows = []
        self._saved_widths = []
        self._first_fill = True
        self._filter_timer = None
        self._current_printer = u''
        self._export_started = 0.0
        self._export_total = 0
        self._progress_done = 0

        self.window = ps_ui.load_window('ProSheets.xaml', self.theme_name)
        self.chrome = ps_ui.Chrome(self.window, on_close=self.close)
        # A shrunk bar is not dragged mid-export (see Chrome.busy).
        self.chrome.busy = lambda: bool(self.exporting)
        # - and + in the header: the whole window smaller to see more on a
        # small screen, or bigger to read it. Kept per machine.
        self.zoom = ps_ui.Zoom(self.window, self.settings)
        ps_ui.attach_egg(self.window)
        ps_ui.own_to_revit(self.window, uiapp)

        self._grab_controls()
        # Before anything that can reach open_setup - the first run setup
        # does, from the bottom of this method - because a saved setup
        # tells the register its parameters have changed.
        self.register = ps_regview.RegisterView(self)
        self._read_model()
        self._build_tables()
        self._fill_static_combos()
        self._wire()
        self._load_last_profile()
        self._apply_preselection()
        self._refresh_all()
        self.restore_window()
        # A borderless, transparent window lays out once before its saved
        # size and the template's state settle; the footer could open with
        # Back and Next squeezed off the end until the first resize. One
        # more layout pass once it is on screen does what the resize did.
        try:
            self.window.ContentRendered += self._settle_layout
        except Exception:
            pass
        self._start_theme_watch()
        self._first_run_setup()
        # Writes a line to the context menu log if "Print in ProSheets" should
        # be registered and is not - see the second anchor note in
        # ps_context. Never throws and never says anything on screen.
        ps_context.audit(uiapp)

    # ==================================================================
    # controls
    # ==================================================================

    def _grab_controls(self):
        names = [
            'MainTabs', 'ThemeChip', 'SetupButton', 'ProfileCombo',
            'ProfileNewButton',
            'ProfileSaveButton', 'ProfileDeleteButton',
            'ProfileImportButton', 'ProfileExportButton', 'StatusText',
            'Progress', 'BackButton', 'NextButton', 'ExportButton',
            'CancelExportButton', 'ExpressExportButton', 'FooterButtons',
            'FooterDock',
            # selection
            'SheetsRadio', 'ViewsRadio', 'SheetSetCombo', 'SaveSetButton',
            'SearchBox', 'SelectAllButton', 'SelectNoneButton',
            'InvertButton', 'GroupCheck', 'CollapseAllButton',
            'SelectionHeadingModeButton', 'SelectionHeadingModeText',
            'ShowAllCheck', 'IsolationNote',
            'OnSheetListCheck',
            'CustomNameButton', 'SheetGrid', 'SelectionHint',
            # format
            'FormatNote',
            'PdfCheck', 'DwgCheck', 'DwfCheck', 'NwcCheck', 'IfcCheck',
            'PdfTile', 'DwgTile', 'DwfTile', 'NwcTile', 'IfcTile',
            'PdfGroup', 'DwgGroup', 'DwfGroup', 'NwcGroup', 'IfcGroup',
            'PdfPanel', 'DwgPanel', 'NwcPanel', 'IfcPanel',
            # NWC
            'NwcPartsCheck', 'NwcElementIdsCheck', 'NwcParamsCombo',
            'NwcPropertiesCheck', 'NwcLinkedCheck', 'NwcRoomAttrCheck',
            'NwcUrlsCheck', 'NwcCoordsCombo', 'NwcLevelsCheck',
            'NwcRoomGeomCheck', 'NwcMaterialsCheck', 'NwcLinkedCadCheck',
            'NwcLightsCheck', 'NwcFacetingBox', 'NwcCustomNameButton',
            'NwcAvailableNote',
            # IFC
            'IfcSetupCombo', 'IfcVersionCombo', 'IfcFileTypeCombo',
            'IfcPhaseCombo', 'IfcSpaceBoundCombo', 'IfcOriginCombo',
            'IfcSplitCheck', 'IfcSteelCheck', 'IfcHeaderButton',
            'IfcAddressButton', 'IfcLinkedCombo', 'Ifc2dCheck',
            'IfcVisibleOnlyCheck', 'IfcRoomsIn3dCheck', 'IfcDetailCombo',
            'IfcRevitPsetsCheck', 'IfcCommonPsetsCheck',
            'IfcQuantitiesCheck', 'IfcMaterialPsetsCheck',
            'IfcSchedulePsetsCheck', 'IfcSpecificSchedulesCheck',
            'IfcUserPsetsCheck', 'IfcTypePropsCheck', 'IfcUserPsetsBox',
            'IfcUserPsetsBrowse', 'IfcParamMapCheck', 'IfcParamMapBox',
            'IfcParamMapBrowse', 'IfcClassificationButton',
            'IfcPartsAsElementsCheck', 'IfcSolidModelCheck',
            'IfcActiveViewGeomCheck', 'IfcFamilyTypeRefCheck',
            'Ifc2dRoomBoundaryCheck', 'IfcSiteElevationCheck',
            'IfcStoreGuidCheck', 'IfcBoundingBoxCheck',
            'IfcTriangulationCheck', 'IfcTypeNameOnlyCheck',
            'IfcVisibleNameCheck', 'IfcImportSettingsButton',
            'IfcExportSettingsButton', 'IfcCustomNameButton',
            'IfcAvailableNote',
            'PlaceCenterRadio', 'PlaceOffsetRadio', 'MarginCombo',
            'OffsetXBox', 'OffsetYBox', 'FitPageRadio', 'ZoomRadio',
            'ZoomBox', 'PrinterCombo', 'PrinterNote',
            'MakeDefaultPrinterButton', 'StagingBox', 'StagingBrowseButton',
            'StagingNote', 'VectorRadio', 'RasterRadio',
            'RasterQualityCombo', 'ColorsCombo', 'ViewLinksBlueCheck',
            'HideRefPlanesCheck', 'HideViewTagsCheck', 'HideScopeBoxesCheck',
            'HideCropCheck', 'HalftoneCheck', 'MaskCoincidentCheck',
            'SeparateFilesRadio', 'CombineRadio', 'KeepPaperSizeCheck',
            'FormatCustomNameButton', 'OrderButton', 'DwgSetupCombo',
            'DwgSharedCoordsCheck', 'DwgXrefCheck', 'DwgXrefNote',
            'DwgVersionCombo',
            'DwgCustomNameButton',
            # create
            'RootFolderBox', 'BrowseButton', 'TokenBox', 'AddTokenButton',
            'ProgressRow', 'ProgressText',
            'PathPreview', 'FolderPerFormatCheck', 'OverwriteCheck',
            'OpenFolderCheck', 'DebugCheck',
            'CreateSummary', 'ClashWarning', 'CreateGrid', 'CreateHint',
        ]
        self.ui = {}
        for name in names:
            self.ui[name] = ps_ui.find(self.window, name)

    def c(self, name):
        return self.ui.get(name)

    # ==================================================================
    # reading the model
    # ==================================================================

    def _read_model(self):
        mode = 'views' if self._is_views_mode() else 'sheets'
        self.rows = ps_model.read_rows(self.doc, mode)
        self.browser_names = []
        if mode == 'views':
            self.browser_names = ps_model.browser_columns(
                ps_model.browser_folder_parameters(self.doc, self.rows))
        self.rows_by_key = dict([(row.key, row) for row in self.rows])
        self.sheet_sets = ps_model.read_sheet_sets(self.doc)
        ps_model.tag_rows_with_sets(self.rows, self.sheet_sets)
        self.catalogue = ps_model.parameter_catalogue(self.doc, self.rows)
        self.stamp = ps_model.export_stamp()
        self.user_name = ps_model.current_user(self.uiapp.Application)

    def _is_views_mode(self):
        radio = self.c('ViewsRadio')
        try:
            return bool(radio is not None and radio.IsChecked)
        except Exception:
            return False

    def _mode_name(self):
        return 'views' if self._is_views_mode() else 'sheets'

    def lookup_for(self, row):
        return ps_model.RowLookup(self.doc, row, self.stamp, self.user_name)

    # ==================================================================
    # the tables
    # ==================================================================

    def _build_tables(self):
        self.table = DataTable('rows')
        self.table.Columns.Add('sel', Boolean).DefaultValue = False
        for name in ('num', 'name', 'rev', 'size', 'fname', 'key',
                     'vis', 'show', 'ord', 'gid', 'grp', 'ishead'):
            self.table.Columns.Add(name, String)
        # The colour the sorted column's cell takes, carried on the row
        # because a run's colour depends on where it sits among the other
        # runs and no style trigger can know that. Always a real brush,
        # never left empty: a Setter handed DBNull cannot convert it to a
        # Brush and the cell loses its background altogether.
        self.table.Columns.Add('gbrush', Object).DefaultValue = \
            Brushes.Transparent
        # A heading's text colour: black or white on its pill, by contrast
        # (ps_ramp.text_on). Read by GridCell's ishead trigger.
        self.table.Columns.Add('gink', Object).DefaultValue = \
            Brushes.Transparent
        try:
            self.table.ColumnChanged += self._tick_changed
        except Exception:
            pass

        view = self.table.DefaultView
        view.RowFilter = "[show] = '1'"
        view.Sort = '[ord] ASC'
        grid = self.c('SheetGrid')
        if grid is not None:
            try:
                grid.ItemsSource = view
            except Exception:
                pass

        self.create_table = DataTable('plan')
        for name in ('num', 'name', 'size', 'fmt', 'fname', 'folder',
                     'key', 'state'):
            self.create_table.Columns.Add(name, String)
        create_grid = self.c('CreateGrid')
        if create_grid is not None:
            try:
                create_grid.ItemsSource = self.create_table.DefaultView
            except Exception:
                pass

        grid = self.c('SheetGrid')
        try:
            grid.Columns.Clear()
            grid.PreviewMouseRightButtonUp += self._header_right_click
            grid.Sorting += self._on_sorting
            grid.PreviewMouseLeftButtonDown += self._row_click
            grid.LoadingRow += self._paint_group_rows
        except Exception:
            pass
        self._build_columns()

    # ==================================================================
    # the columns
    #
    # Every column on this grid is built in code from one ordered list,
    # including the six that used to be declared in XAML. That is what
    # makes "put the new one next to the one I right clicked" and
    # "remember where I left them" possible at all: with the fixed ones in
    # the layout and the added ones appended afterwards, a parameter
    # column could only ever go on the far right.
    # ==================================================================

    # id, heading, star width, minimum width
    #
    # Sheets and views are different lists of things and want different
    # columns. A view has no sheet number, no revision and no paper size,
    # so in Views mode those three headings were three empty columns
    # taking up half the grid. Views start with the two that matter and
    # everything else is a parameter column the user adds.
    SHEET_COLUMNS = [
        ('sel', u'', 0.0, 44),
        ('num', u'Sheet Number', 1.1, 120),
        ('name', u'Sheet Name', 2.0, 175),
        ('rev', u'Revision', 0.6, 85),
        ('size', u'Size', 1.0, 130),
        ('fname', u'Custom File Name', 2.2, 210),
    ]

    VIEW_COLUMNS = [
        ('sel', u'', 0.0, 44),
        ('name', u'View Name', 2.4, 200),
        ('fname', u'Custom File Name', 2.2, 210),
    ]

    # Every id either set can produce, which is what an old template has
    # to be checked against before its saved order is trusted.
    KNOWN_COLUMNS = ('sel', 'num', 'name', 'rev', 'size', 'fname')

    TICK_TEMPLATE = (
        u'<DataTemplate '
        u'xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">'
        u'<CheckBox Style="{DynamicResource GridCheckBox}" '
        u'IsChecked="{Binding sel, Mode=TwoWay, '
        u'UpdateSourceTrigger=PropertyChanged}"/>'
        u'</DataTemplate>')

    @staticmethod
    def columns_for(mode):
        """The fixed column set for 'sheets' or 'views'."""
        if u'{0}'.format(mode) == 'views':
            return ProSheetsWindow.VIEW_COLUMNS
        return ProSheetsWindow.SHEET_COLUMNS

    @staticmethod
    def default_column_order(mode='sheets'):
        return [entry[0] for entry in ProSheetsWindow.columns_for(mode)]

    # Shown on every sheet list unless a template says otherwise. The
    # revision date is a value the tool derives; the other two are
    # whatever this office calls them, which is why they come from
    # settings rather than being written in here.
    DEFAULT_EXTRA_COLUMNS = ['Current Revision Date']

    @staticmethod
    def starting_columns(mode, extras=None, browser=None):
        """The column order a list starts in, parameters included.

        Separate from default_column_order, which stays the fixed set
        and nothing else: _sane_order uses that to decide which fixed
        columns belong to a mode, and a parameter column in there would
        be re-added every time somebody removed one.
        """
        order = list(ProSheetsWindow.default_column_order(mode))
        if mode == 'views':
            # Never the sheet parameters - no view has a value for them.
            # The columns of Revit's Project Browser instead: its folder
            # parameters, then the view type.
            extras = browser
        wanted = []
        for name in (extras or []):
            col_id = u'p:{0}'.format(name)
            if name and col_id not in wanted:
                wanted.append(col_id)
        if not wanted:
            return order
        # In front of Custom File Name, which reads best last.
        where = order.index('fname') if 'fname' in order else len(order)
        return order[:where] + wanted + order[where:]

    def default_extras(self):
        """The parameter columns a sheet list starts with."""
        names = list(self.DEFAULT_EXTRA_COLUMNS)
        for key in ('param_series', 'param_discipline'):
            name = self.settings.text(key, u'')
            if name and name not in names:
                names.append(name)
        return names

    def _apply_default_sort(self):
        """Start on the sheet series unless the template says otherwise.

        The column is put back if it is missing rather than the sort
        being abandoned. A template saved before 1.18.0 carries a
        column list without the series in it, and the old behaviour -
        skip the sort when the column is absent - meant that anybody
        with a template from last week opened unsorted and had no way
        of telling why. You cannot sort on a column that is not there,
        so the answer is to put it there.
        """
        if self.sort_stack:
            return False
        views = getattr(self, '_is_views_mode', None)
        if views is not None and views():
            return self._apply_browser_sort()
        series = self.series_column()
        if not series:
            return False
        if series not in self.column_order:
            order = list(self.column_order)
            where = order.index('fname') if 'fname' in order else len(order)
            order.insert(where, series)
            self.column_order = order
        self.sort_stack = [(series, False)]
        return True

    def _apply_browser_sort(self):
        """The Views list sorted the way Revit's Project Browser sorts it:
        by the first folder, then the second, and so on, then the view
        type, then the name. Any of those columns missing is put back, in
        front of Custom File Name."""
        names = list(getattr(self, 'browser_names', None) or [])
        if not names:
            return False
        wanted = [u'p:{0}'.format(name) for name in names]
        order = list(self.column_order)
        for col_id in wanted:
            if col_id not in order:
                where = order.index('fname') if 'fname' in order \
                    else len(order)
                order.insert(where, col_id)
        self.column_order = order
        levels = wanted[:self.MAX_SORT_LEVELS - 1]
        self.sort_stack = [(col_id, False) for col_id in levels] + \
            [('name', False)]
        return True

    def series_column(self):
        """The column id the list sorts by out of the box, or None."""
        name = self.settings.text('param_series', u'')
        return u'p:{0}'.format(name) if name else None

    # ------------------------------------------------------ sort memory
    # The sort and grouping last set by hand, per machine and per mode.
    # Out of the box Sheets opens grouped on the sheet series (once Setup
    # names one) and Views the way the Project Browser has it; from the
    # first change on, the list opens the way it was left.
    SORT_MEMORY = 'sel_sort.'
    GROUP_MEMORY = 'sel_grouped.'

    def _remembered_sort(self, mode=None):
        """(stack, grouped) last set in this mode, or None for never."""
        mode = mode or self._mode_name()
        store = getattr(getattr(self, 'settings', None), 'store', None)
        if not store:
            return None
        key = self.SORT_MEMORY + mode
        if key not in store:
            return None
        stack = []
        for piece in ps_config.get_list(store, key, []):
            col_id, _, direction = u'{0}'.format(piece).partition(u'|')
            if col_id:
                stack.append((col_id, direction == 'desc'))
        grouped = ps_config.get_bool(store, self.GROUP_MEMORY + mode, True)
        return stack, grouped

    def remember_sort(self):
        """Keep what is on screen as the sort this mode opens in next time."""
        settings = getattr(self, 'settings', None)
        if settings is None:
            return False
        mode = self._mode_name()
        try:
            settings.set(self.SORT_MEMORY + mode, ps_config.put_list(
                [u'{0}|{1}'.format(col_id, 'desc' if down else 'asc')
                 for col_id, down in self.sort_stack]))
            settings.set(self.GROUP_MEMORY + mode,
                         '1' if self.grouped else '0')
            settings.save()
        except Exception:
            return False
        return True

    def forget_sort(self, mode=None):
        """Back to the out of the box sort for this mode."""
        settings = getattr(self, 'settings', None)
        if settings is None:
            return False
        mode = mode or self._mode_name()
        for key in (self.SORT_MEMORY + mode, self.GROUP_MEMORY + mode):
            settings.store.pop(key, None)
        try:
            settings.save()
        except Exception:
            pass
        return True

    def _restore_sort(self, mode=None):
        """Put the remembered sort and grouping back. False when there is none.

        A remembered parameter column that is no longer on the list is put
        back in front of Custom File Name, the same as the series column -
        you cannot sort on a column that is not there. A fixed column that
        does not belong to this mode is let go.
        """
        mode = mode or self._mode_name()
        memory = self._remembered_sort(mode)
        if memory is None:
            return False
        stack, grouped = memory
        order = list(self.column_order)
        kept = []
        for col_id, down in stack[:self.MAX_SORT_LEVELS]:
            if col_id not in order:
                if not col_id.startswith(u'p:'):
                    continue
                where = order.index('fname') if 'fname' in order \
                    else len(order)
                order.insert(where, col_id)
            kept.append((col_id, down))
        if stack and not kept:
            return False
        self.column_order = order
        self.sort_stack = kept
        self.grouped = bool(grouped)
        self._template_sort = u''
        # The tick follows without toggle_grouping rebuilding the groups.
        self._suspend_group_toggle = True
        try:
            self.c('GroupCheck').IsChecked = self.grouped
        except Exception:
            pass
        self._suspend_group_toggle = False
        return True

    def fixed_columns(self):
        return self.columns_for('views' if self._is_views_mode() else 'sheets')

    def _sane_order(self, saved, mode=None):
        """A saved column order made to fit the mode it is being used in.

        A template saved against sheets carries Sheet Number, Revision and
        Size; none of those exist on a view. Rather than refuse the
        template, the fixed columns that do not belong are dropped, the
        ones that are missing are put back in their standard places, and
        the parameter columns - which are the user's actual work - are
        kept exactly where they were.
        """
        mode = mode or self._mode_name()
        wanted = self.default_column_order(mode)
        order = [col_id for col_id in saved
                 if self.is_parameter_column(col_id) or col_id in wanted]
        for index, col_id in enumerate(wanted):
            if col_id in order:
                continue
            # Put it back next to whichever of its neighbours survived,
            # so 'sel' stays first and 'fname' stays last.
            before = wanted[:index]
            where = 0
            for other in reversed(before):
                if other in order:
                    where = order.index(other) + 1
                    break
            order.insert(where, col_id)
        return order

    @staticmethod
    def is_parameter_column(col_id):
        return u'{0}'.format(col_id).startswith(u'p:')

    @staticmethod
    def parameter_of(col_id):
        return u'{0}'.format(col_id)[2:]

    def parameter_columns(self):
        """The added parameter columns, in the order they appear."""
        return [self.parameter_of(col_id) for col_id in self.column_order
                if self.is_parameter_column(col_id)]

    def _data_key(self, col_id):
        """The DataTable column behind a grid column.

        A parameter column is c0, c1... and never the parameter's own name:
        a binding path cannot carry a space, a bracket or a hash, and
        BGL_Sheet Discipline has one of those in it.
        """
        if not self.is_parameter_column(col_id):
            return col_id
        index = 0
        for other in self.column_order:
            if not self.is_parameter_column(other):
                continue
            if other == col_id:
                return 'c{0}'.format(index)
            index += 1
        return 'c0'

    def _heading_of(self, col_id):
        if self.is_parameter_column(col_id):
            return self.parameter_of(col_id)
        for other, title, _width, _minimum in self.fixed_columns():
            if other == col_id:
                return title
        return col_id

    def _build_columns(self):
        grid = self.c('SheetGrid')
        if grid is None:
            return

        # The DataTable needs a column per parameter before the grid can
        # bind to one.
        try:
            for column in list(self.table.Columns):
                name = u'{0}'.format(column.ColumnName)
                if name.startswith('c') and name[1:].isdigit():
                    self.table.Columns.Remove(column)
        except Exception:
            pass
        for index in range(len(self.parameter_columns())):
            try:
                self.table.Columns.Add('c{0}'.format(index), String)
            except Exception:
                continue

        self.search_boxes = {}
        self.header_outlines = {}
        self.header_badges = {}
        self.header_tick = None
        try:
            grid.Columns.Clear()
        except Exception:
            return

        for col_id in list(self.column_order):
            try:
                grid.Columns.Add(self._make_column(col_id))
            except Exception:
                continue

        self._paint_sort_headers()
        self.apply_column_widths(self._saved_widths)
        self._fill_parameter_values()

    def _make_column(self, col_id):
        width, minimum = 1.0, 110
        for other, _title, star, least in self.fixed_columns():
            if other == col_id:
                width, minimum = star, least
                break

        if col_id == 'sel':
            column = DataGridTemplateColumn()
            column.CellTemplate = XamlReader.Parse(self.TICK_TEMPLATE)
            column.Width = DataGridLength(44)
            column.MinWidth = 44
            column.CanUserResize = False
            column.CanUserSort = False
        else:
            column = DataGridTextColumn()
            column.Binding = Binding(self._data_key(col_id))
            column.Width = self._star_width(width)
            column.MinWidth = minimum
            column.IsReadOnly = True

        # SortMemberPath is how the Sorting handler knows which column was
        # clicked without keeping a map of column objects alongside.
        column.SortMemberPath = col_id
        column.Header = self._header_for(col_id)
        return column

    def _header_for(self, col_id):
        """A heading is a live element: title, sort badge and search box.

        The sort outline lives here in the content rather than in a header
        style. A style per level per direction would be twelve styles and
        still could not colour an arbitrary level, whereas a Border here
        takes any brush.
        """
        outline = Border()
        outline.BorderThickness = Thickness(2)
        outline.CornerRadius = CornerRadius(2)
        outline.BorderBrush = Brushes.Transparent
        outline.Padding = Thickness(3, 2, 3, 3)
        self.header_outlines[col_id] = outline

        panel = StackPanel()
        panel.Orientation = Orientation.Vertical
        outline.Child = panel

        top = Grid()
        top.ColumnDefinitions.Add(ColumnDefinition())
        badge_column = ColumnDefinition()
        badge_column.Width = GridLength(0, GridUnitType.Auto)
        top.ColumnDefinitions.Add(badge_column)

        if col_id == 'sel':
            box = CheckBox()
            self._styled(box, 'GridCheckBox')
            box.ToolTip = 'Tick or untick everything showing'
            box.Click += self._header_tick
            self.header_tick = box
            outline.Padding = Thickness(0)
            outline.Child = box
            return outline

        if col_id == 'fname':
            button = Button()
            button.Content = self._heading_of(col_id)
            self._styled(button, 'ChipButton')
            button.ToolTip = ('Choose which parameters make up the '
                              'exported file name')
            button.Click += self.open_name_dialog
            button.HorizontalAlignment = HorizontalAlignment.Left
            Grid.SetColumn(button, 0)
            top.Children.Add(button)
        else:
            title = TextBlock()
            title.Text = self._heading_of(col_id)
            title.TextTrimming = TextTrimming.CharacterEllipsis
            title.VerticalAlignment = VerticalAlignment.Center
            Grid.SetColumn(title, 0)
            top.Children.Add(title)

        badge = TextBlock()
        badge.FontSize = 11
        badge.FontWeight = FontWeights.Bold
        badge.Margin = Thickness(6, 0, 0, 0)
        badge.VerticalAlignment = VerticalAlignment.Center
        badge.Visibility = Visibility.Collapsed
        Grid.SetColumn(badge, 1)
        top.Children.Add(badge)
        self.header_badges[col_id] = badge

        panel.Children.Add(top)

        search = TextBox()
        self._styled(search, 'ColumnSearchBox')
        search.Tag = u'Search'
        search.Text = self.column_search.get(col_id, u'')
        search.TextChanged += self._make_column_search(col_id)
        # Clicking a heading sorts it, and that must not happen when the
        # click was aimed at the search box. Handling the preview stops the
        # sort, so the focus has to be given by hand.
        search.PreviewMouseLeftButtonDown += self._focus_search
        panel.Children.Add(search)
        self.search_boxes[col_id] = search
        return outline

    def _styled(self, element, key):
        """Point an element at a keyed style, dynamically.

        Never ``element.Style = TryFindResource(key)``. When that lookup
        comes back empty the assignment is a local null, and a local value
        on Style stops WPF applying the implicit style as well - so a
        Button drops all the way to the OS chrome and renders as a light
        grey lozenge in the middle of a dark header. That is exactly what
        went wrong with the Custom File Name heading in 1.6.0.

        A resource reference also re-resolves when the palette is swapped,
        which a one-off lookup does not.
        """
        try:
            element.SetResourceReference(FrameworkElement.StyleProperty, key)
            return True
        except Exception:
            return False

    def _focus_search(self, sender, args):
        try:
            sender.Focus()
            args.Handled = True
        except Exception:
            pass

    def _make_column_search(self, col_id):
        def handler(sender, args):
            try:
                self.column_search[col_id] = u'{0}'.format(sender.Text or u'')
            except Exception:
                self.column_search[col_id] = u''
            self._debounce_filters()
        return handler

    def _debounce_filters(self):
        """Re-filtering on every keystroke is visibly slow at 400 sheets."""
        try:
            if self._filter_timer is None:
                timer = DispatcherTimer()
                timer.Interval = TimeSpan.FromMilliseconds(220)
                timer.Tick += self._filter_tick
                self._filter_timer = timer
            self._filter_timer.Stop()
            self._filter_timer.Start()
        except Exception:
            self._apply_filters()
            self._refresh_counts()

    def _filter_tick(self, sender, args):
        try:
            self._filter_timer.Stop()
        except Exception:
            pass
        self._apply_filters()
        self._refresh_counts()

    def _star_width(self, weight):
        return DataGridLength(weight, DataGridLengthUnitType.Star)

    def _fill_parameter_values(self):
        """Read each added parameter for every row.

        One pass over the rows rather than one per column, because the
        lookup caches per row and building it is the expensive part.
        """
        names = self.parameter_columns()
        if not names:
            return
        self._suspend_ticks = True
        try:
            for entry in self.table.Rows:
                if not u'{0}'.format(entry['key']):
                    continue           # a group heading holds no sheet
                row = self.rows_by_key.get(
                    self._as_key(u'{0}'.format(entry['key'])))
                if row is None:
                    continue
                lookup = self.lookup_for(row)
                for index, parameter in enumerate(names):
                    try:
                        entry['c{0}'.format(index)] = lookup(parameter)
                    except Exception:
                        entry['c{0}'.format(index)] = u''
        finally:
            self._suspend_ticks = False

    # ------------------------------------------------------- sorting
    MAX_SORT_LEVELS = 6

    def _on_sorting(self, sender, args):
        """Take the sort over from the DataGrid.

        The view is sorted on a hidden key column, so letting the grid sort
        on a value column would fight it - and a view sorted on a value
        re-evaluates the moment that value changes, sliding the row being
        worked on out from under the cursor. Handled is set and the order
        written instead.

        Plain click starts again from one level. Shift-click adds a level,
        or flips one already in the stack, the way a spreadsheet does.
        """
        try:
            args.Handled = True
            col_id = u'{0}'.format(args.Column.SortMemberPath)
        except Exception:
            return
        if not col_id:
            return

        existing = [index for index, pair in enumerate(self.sort_stack)
                    if pair[0] == col_id]
        if ps_ui.shift_down():
            if existing:
                place = existing[0]
                self.sort_stack[place] = (col_id, not self.sort_stack[place][1])
            elif len(self.sort_stack) < self.MAX_SORT_LEVELS:
                self.sort_stack.append((col_id, False))
            else:
                self.say(u'Six sort levels is the limit.')
                return
        else:
            if existing and len(self.sort_stack) == 1:
                self.sort_stack = [(col_id, not self.sort_stack[0][1])]
            else:
                self.sort_stack = [(col_id, False)]

        # A group number is a position in this sort's list of values and
        # means nothing in the next one, so anything collapsed under the
        # old sort has to be let go. Keeping the set would reopen the
        # list with unrelated groups shut for no visible reason.
        self.collapsed = set()
        self._ensure_grouped()

        self._apply_order()
        self._apply_grouping()
        self._apply_filters()
        self._paint_sort_headers()
        self.remember_sort()
        self._say_sort()

    def _ensure_grouped(self):
        """Sorting turns grouping on. (was it off).

        Sorting a column and colouring its matching values are the same
        intent - you sort by discipline to see the disciplines - so
        finding the colours off because of something done twenty minutes
        ago is a surprise. The tick box stays, for the case where
        grouping is genuinely in the way.

        The tick is set with its own handler suppressed: letting
        toggle_grouping run here would rebuild the groups against the
        order this sort is about to replace, and clear the collapsed set
        a second time.
        """
        if self.grouped:
            return False
        self.grouped = True
        self._suspend_group_toggle = True
        try:
            self.c('GroupCheck').IsChecked = True
        except Exception:
            pass
        finally:
            self._suspend_group_toggle = False
        return True

    def _say_sort(self):
        if not self.sort_stack:
            self.say(u'Not sorted. Click a heading to sort, shift click to '
                     u'add a second level.')
            return
        parts = []
        for col_id, descending in self.sort_stack:
            parts.append(u'{0} {1}'.format(
                self._heading_of(col_id),
                u'Z-A' if descending else u'A-Z'))
        tail = u''
        if self.grouped and self.run_count:
            tail = u' {0} value{1} of {2}, each its own colour and each ' \
                   u'collapsible.'.format(
                       self.run_count,
                       u'' if self.run_count == 1 else u's',
                       self._heading_of(self.sort_stack[0][0]))
        elif len(self.sort_stack) < self.MAX_SORT_LEVELS:
            tail = u' Shift click a heading to add a level.'
        self.say(u'Sorted by {0}.{1}'.format(u', then '.join(parts), tail))

    def _paint_sort_headers(self):
        """Outline and badge each sorted heading in its level's colour."""
        levels = {}
        for index, pair in enumerate(self.sort_stack):
            levels[pair[0]] = (index, pair[1])

        for col_id, outline in self.header_outlines.items():
            badge = self.header_badges.get(col_id)
            found = levels.get(col_id)
            if found is None:
                try:
                    outline.BorderBrush = Brushes.Transparent
                except Exception:
                    pass
                if badge is not None:
                    try:
                        badge.Visibility = Visibility.Collapsed
                    except Exception:
                        pass
                continue
            index, descending = found
            brush = theme.brush(theme.colour(self.theme_name,
                                             theme.sort_level_key(index)))
            try:
                outline.BorderBrush = brush
            except Exception:
                pass
            if badge is not None:
                try:
                    badge.Text = u'{0}{1}'.format(
                        index + 1, u'\u25bc' if descending else u'\u25b2')
                    badge.Foreground = brush
                    badge.Visibility = Visibility.Visible
                except Exception:
                    pass

    def _sort_value(self, entry, col_id):
        key = self._data_key(col_id) if col_id in self.column_order else 'num'
        try:
            value = u'{0}'.format(entry[key] or u'')
        except Exception:
            value = u''
        if key == 'num':
            row = self.rows_by_key.get(
                self._as_key(u'{0}'.format(entry['key'])))
            if row is not None:
                value = row.number
        return value

    def _apply_order(self):
        """Write the sort key, so the view sorts on a decision not a value.

        Layered **least significant first**, relying on the sort being
        stable. One composite key cannot do it, because then only the whole
        thing can be reversed rather than each level on its own.

        Natural order throughout, so P-9 comes before P-10 rather than
        after P-100.
        """
        rows = [entry for entry in self.table.Rows
                if u'{0}'.format(entry['key'])]

        stack = self.sort_stack or [('num', False)]
        for level in range(len(stack) - 1, -1, -1):
            col_id, descending = stack[level]
            rows.sort(
                key=lambda entry, c=col_id: ps_model.natural_key(
                    self._sort_value(entry, c)),
                reverse=bool(descending))

        self._sorted_rows = rows
        for index, entry in enumerate(rows):
            entry['ord'] = u'{0:06d}'.format(index) + u'\x01'

    # ------------------------------------------------------ grouping
    def _group_value(self, entry):
        if not self.sort_stack:
            return u''
        return self._sort_value(entry, self.sort_stack[0][0])

    # How long a run has to be to get a heading of its own. One, so
    # every distinct value gets a heading it can be collapsed by,
    # including the values that turn up once.
    #
    # The cost is real and worth knowing: sorting by a column where
    # nothing repeats, Sheet Number being the obvious one, puts a
    # heading above every row and doubles the length of the list. That
    # is the sort somebody does to find one sheet, so it is the sort
    # where grouping is least useful - untick Group matching values for
    # it. Kept as a constant rather than written into the loop so it is
    # one edit to change.
    MIN_RUN = 1

    @staticmethod
    def value_runs(labels):
        """[(label, start, count)] for each stretch of equal values.

        Consecutive, not distinct: after a sort those are the same thing,
        and a stretch of touching rows is what the eye reads as a block.
        Kept free of the table and of WPF so the bench can hold it to a
        table of cases.
        """
        runs = []
        for index, label in enumerate(labels):
            if runs and runs[-1][0] == label:
                runs[-1][2] += 1
            else:
                runs.append([label, index, 1])
        return [(label, start, count) for label, start, count in runs]

    @staticmethod
    def is_group(count):
        return count >= ProSheetsWindow.MIN_RUN

    def _run_brushes(self, place):
        """(cell, row wash, heading) brushes for the nth run.

        A colour of its own per run, rather than two strengths of the
        sort level's colour alternating. Alternating did the whole job
        while only repeated values were coloured; now that a value
        appearing once gets a colour too, what tells two neighbours
        apart has to be the colour itself.

        From 1.48.0 the colours are Project Browser Pro's: each run's
        name picks its trade's ramp (electrical greens, mechanical blues,
        plumbing browns, everything else violets) and the runs of one
        trade step dark to light down the list - see _plan_runs.
        """
        return self._shade_brushes(self._run_hex(place))

    def _run_hex(self, place):
        """A run's colour in the heading mode (1.54.0): its trade ramp,
        grey (two greys taking turns, so neighbouring runs still differ),
        or the colour picked for its value."""
        colours = getattr(self, 'run_colours', None) or []
        try:
            ramp = colours[int(place)]
        except Exception:
            ramp = ps_ramp.shade(ps_ramp.OTHER, 0.0)
        labels = getattr(self, 'run_labels', None) or []
        try:
            label = labels[int(place)]
            level = 1 if int(place) % 2 == 0 else 2
        except Exception:
            label, level = u'', 1
        return ps_ramp.mode_colour(
            getattr(self, 'heading_mode', ps_ramp.COLOURED), ramp, level,
            self.theme_name,
            (getattr(self, 'heading_custom', None) or {}).get(label))

    def _plan_runs(self, labels):
        """One ramp colour per run, in list order (ps_ramp.plan)."""
        found = ps_ramp.plan(
            [(index, label, 1, None) for index, label in enumerate(labels)],
            ladder=ps_ramp.SINGLE_LEVEL)
        self.run_colours = [found[index] for index in range(len(labels))]
        self.run_labels = [u'{0}'.format(label) for label in labels]
        return self.run_colours

    def _shade_brushes(self, hex_text):
        """(cell, row wash, heading) brushes for one heading colour.

        The heading is the solid colour - the same on both themes, as in
        Project Browser Pro. Its members carry it at a fraction of its
        strength, through alpha, so the selection still shows through.
        """
        dark = self.theme_name == 'dark'
        cell = theme.tinted(hex_text, self.GROUP_CELL_DARK if dark
                            else self.GROUP_CELL_LIGHT)
        wash = theme.tinted(hex_text, self.GROUP_TINT_DARK if dark
                            else self.GROUP_TINT_LIGHT)
        return cell, wash, theme.brush(hex_text)

    def _ink_brush(self, hex_text):
        """Black or white for text on a heading of this colour."""
        return theme.brush(ps_ramp.text_on(hex_text))

    def _apply_grouping(self):
        """Colour each run of matching values and make it collapsible.

        A "run" is what it says: rows next to each other whose value in
        the first sorted column is the same. Runs rather than a dictionary
        of distinct values, because after a sort those are the same thing
        and a run is what the eye actually sees.

        **A run of one is not a group.** Sorting by Sheet Number, where
        every value is unique, would otherwise produce four hundred
        headings and four hundred groups of one - which is how automatic
        grouping usually manages to be worse than none. Singletons keep
        their place in the order and are left plain.

        Heading rows are **appended to the end of the table, never
        inserted**: half this window addresses rows by position, and
        inserting a heading mid-table shifts every index after it. They are
        placed purely by their sort key - a heading sorts immediately above
        its own members because its key ends \x00 and theirs \x01.
        """
        self._suspend_ticks = True
        try:
            # Clear out last time's headings first.
            for entry in [e for e in self.table.Rows
                          if not u'{0}'.format(e['key'])]:
                self.table.Rows.Remove(entry)

            self.groups = {}
            self.run_count = 0
            sorted_rows = getattr(self, '_sorted_rows', [])
            if not self.grouped or not self.sort_stack:
                for entry in sorted_rows:
                    entry['gid'] = u''
                    entry['grp'] = u''
                    entry['ishead'] = u''
                    entry['gbrush'] = Brushes.Transparent
                self._apply_cell_style()
                return

            labels = [self._group_value(entry) or u'(blank)'
                      for entry in sorted_rows]

            headings = []
            runs = self.value_runs(labels)
            self.run_count = len(runs)
            self._plan_runs([run[0] for run in runs])
            for place, run in enumerate(runs):
                _label, start, count = run
                members = sorted_rows[start:start + count]
                number = place + 1
                collapsible = self.is_group(count)
                cell, _wash, _head = self._run_brushes(place)
                for index, entry in enumerate(members):
                    entry['ord'] = u'{0:06d}'.format(number) + u'\x01' + \
                        u'{0:08d}'.format(index)
                    entry['gid'] = (u'{0}'.format(number) if collapsible
                                    else u'')
                    entry['grp'] = u'{0}'.format(place)
                    entry['ishead'] = u''
                    entry['gbrush'] = cell
                if not collapsible:
                    continue
                self.groups[number] = members
                headings.append((number, place))

            for number, place in headings:
                heading = self.table.NewRow()
                heading['key'] = u''
                heading['gid'] = u'{0}'.format(number)
                heading['grp'] = u'{0}'.format(place)
                heading['ishead'] = u'1'
                heading['vis'] = '1'
                heading['show'] = '1'
                # The pill carries the colour; a solid cell on top of it
                # would square off its rounded corners.
                heading['gbrush'] = Brushes.Transparent
                heading['gink'] = self._ink_brush(self._run_hex(place))
                heading['ord'] = u'{0:06d}'.format(number) + u'\x00'
                self.table.Rows.Add(heading)
            self._label_groups()
            self._apply_cell_style()
        finally:
            self._suspend_ticks = False
            self._paint_collapse_button()
            # Headings are rebuilt unticked, so they have to be put back
            # in step with members that were already ticked before the
            # sort that made these groups.
            self._sync_group_ticks()

    def _paint_collapse_button(self):
        """Light the Collapse all chip while there is something to collapse.

        Off it reads as one more grey chip in a row of grey chips, which
        is the wrong signal for the only control on the toolbar whose
        state changes what the list looks like.
        """
        button = self.c('CollapseAllButton')
        if button is None:
            return
        live = bool(self.grouped and self.groups)
        # Both keys exist in Theme.xaml, so neither lookup can come back
        # empty - but _styled is used anyway, because assigning a style
        # by value is the mistake that keeps costing releases.
        self._styled(button, 'ChipButtonOn' if live else 'ChipButton')
        try:
            button.IsEnabled = live
        except Exception:
            pass
        ps_ui.set_content(button,
                          u'Expand all' if self.collapsed else u'Collapse all')

    def _apply_cell_style(self):
        """Put the coloured cell style on the column that is sorted first.

        Only that column: the run is a run of *its* values, and colouring
        every cell in the row that strongly would leave nothing readable.
        The rest of the row gets the wash, in _paint_group_rows.
        """
        wanted = self.sort_stack[0][0] if (self.grouped and self.sort_stack) \
            else None

        # Both styles are looked up, and a column that is not the sorted
        # one is given the plain one **by name**.
        #
        # Not None. Setting CellStyle back to None is what put a white bar
        # across the selected row in 1.10.0: DataGrid pushes the column's
        # CellStyle down onto every cell, so a null there lands as a local
        # null on DataGridCell.Style - and a local null on Style stops WPF
        # applying the implicit style as well, dropping the cell to OS
        # chrome. An unstyled cell is transparent and invisible against a
        # dark grid until it is selected, at which point it paints itself
        # with the system highlight. Hence: white, only on the selected
        # row, only once a sort had assigned a style to some other column.
        #
        # This is the same fault as the Custom File Name heading in 1.6.0,
        # by the same mechanism. See _styled for the other half of it.
        plain = self._resource('GridCell')
        grouped = self._resource('GroupedCell')

        grid = self.c('SheetGrid')
        try:
            columns = list(grid.Columns)
        except Exception:
            return
        for column in columns:
            try:
                col_id = u'{0}'.format(column.SortMemberPath)
                style = grouped if col_id == wanted else plain
                # Never assign the null a failed lookup returns; leaving
                # the property untouched keeps the implicit style.
                if style is not None:
                    column.CellStyle = style
            except Exception:
                continue

    def _resource(self, key):
        """A keyed resource, or None. Never assign None to a Style."""
        try:
            return self.window.TryFindResource(key)
        except Exception:
            return None

    def _label_groups(self):
        """Write each heading's caption into the table, never onto the row.

        Setting it as a local value on a recycled row container sticks to
        that container, and VirtualizationMode=Recycling hands it to a real
        data row later - so a group label turns up in the middle of the
        sheets.
        """
        word = u'view' if self._is_views_mode() else u'sheet'
        for entry in self.table.Rows:
            if not self._is_heading(entry):
                continue
            group = self._as_int(entry['gid'])
            members = self.groups.get(group, [])
            shown = len([m for m in members if u'{0}'.format(m['vis']) == '1'])
            label = self._group_value(members[0]) if members else u''
            entry['num'] = u'{0}  {1}'.format(
                u'\u25b8' if group in self.collapsed else u'\u25be',
                label or u'(blank)')
            entry['name'] = u'[ {0} ]  {1}   {2} {3}{4}'.format(
                u'+' if group in self.collapsed else u'\u2013',
                u'Expand' if group in self.collapsed else u'Collapse',
                shown, word, u'' if shown == 1 else u's')

    def _as_int(self, value):
        try:
            return int(u'{0}'.format(value))
        except Exception:
            return 0

    def toggle_grouping(self, sender=None, args=None):
        if getattr(self, '_suspend_group_toggle', False):
            return
        self.grouped = self._flag_of('GroupCheck')
        if self.grouped and not self.sort_stack:
            # Grouping with nothing sorted groups on the sheet series where
            # Setup names one, else the number.
            series = self.series_column()
            if series and series in self.column_order \
                    and not self._is_views_mode():
                self.sort_stack = [(series, False)]
            else:
                self.sort_stack = [('num', False)]
            self._apply_order()
            self._paint_sort_headers()
        self.collapsed = set()
        self._apply_grouping()
        self._apply_filters()
        self._refresh_counts()
        self.remember_sort()
        if not self.grouped:
            self.say(u'Values are no longer coloured.')
        else:
            self.say(u'{0} value{1} of {2}, each with its own colour and '
                     u'heading. Click a heading to collapse it, or its tick '
                     u'box to tick the group.'.format(
                         self.run_count,
                         u'' if self.run_count == 1 else u's',
                         self._heading_of(self.sort_stack[0][0])))

    def collapse_all(self, sender=None, args=None):
        if not self.grouped:
            return
        if self.collapsed:
            self.collapsed = set()
        else:
            self.collapsed = set(self.groups.keys())
        self._label_groups()
        self._apply_filters()
        self._refresh_counts()
        self._paint_collapse_button()

    @staticmethod
    def wants_collapse(grouped, on_heading, on_checkbox):
        """Whether a click on the grid should collapse a group.

        The tick box is the exception, and it has to be an exception
        here rather than in the tick box's own handler: this runs on
        PreviewMouseLeftButtonDown, which fires before the CheckBox ever
        sees the click, and it sets Handled to stop the click also
        selecting the row. A heading whose tick box swallowed the click
        into a collapse is what 1.11.1 shipped - the tick could not be
        reached at all.
        """
        return bool(grouped and on_heading and not on_checkbox)

    def _row_click(self, sender, args):
        """A click on a group heading collapses or expands it.

        Also where the highlighted rows are noted down, because this is
        the only handler that runs *before* the click has been dealt
        with. By the time the tick has changed, the DataGrid may well
        have reduced the selection to the row that was clicked, and the
        other highlighted rows are gone.
        """
        try:
            source = args.OriginalSource
        except Exception:
            return
        if self._under_checkbox(source):
            self._tick_selection = self._selected_keys()
        else:
            self._tick_selection = set()
        try:
            row = self._row_under(source)
        except Exception:
            row = None
        if row is None:
            return
        try:
            entry = row.Item.Row
        except Exception:
            return
        if not self.wants_collapse(self.grouped, self._is_heading(entry),
                                   self._under_checkbox(source)):
            return
        group = self._as_int(entry['gid'])
        if group in self.collapsed:
            self.collapsed.discard(group)
        else:
            self.collapsed.add(group)
        self._label_groups()
        self._apply_filters()
        self._refresh_counts()
        self._paint_collapse_button()
        try:
            args.Handled = True
        except Exception:
            pass

    def _selected_keys(self):
        """The keys of the rows highlighted in the grid right now."""
        found = set()
        try:
            for item in self.c('SheetGrid').SelectedItems:
                try:
                    entry = item.Row
                except Exception:
                    continue
                if self._is_heading(entry):
                    continue
                key = u'{0}'.format(entry['key'])
                if key:
                    found.add(key)
        except Exception:
            return set()
        return found

    @staticmethod
    def tick_targets(changed_key, selection):
        """Which rows a tick applies to.

        A tick on a row that is part of a highlighted block applies to
        the whole block, the way a spreadsheet does. A tick on a row
        outside the block is just itself - otherwise ticking one sheet
        while something else happened to be highlighted elsewhere would
        quietly tick that too.
        """
        key = u'{0}'.format(changed_key)
        picked = set([u'{0}'.format(one) for one in (selection or set())])
        if key in picked and len(picked) > 1:
            return picked
        return set([key])

    def _under_checkbox(self, source):
        """Whether the click landed inside a tick box.

        Walked from the clicked element outwards rather than asked of
        the cell, because the thing that was hit is a bit of the
        CheckBox's template - a Border or a Path - and only its parents
        say what it belongs to.
        """
        node = source
        for _step in range(10):
            if node is None:
                return False
            if isinstance(node, CheckBox):
                return True
            if isinstance(node, DataGridRow):
                return False
            try:
                node = VisualTreeHelper.GetParent(node)
            except Exception:
                return False
        return False

    def _row_under(self, source):
        node = source
        for _step in range(14):
            if node is None:
                return None
            if isinstance(node, DataGridRow):
                return node
            try:
                node = VisualTreeHelper.GetParent(node)
            except Exception:
                return None
        return None

    # How strongly a group's colour washes its member rows. Full strength
    # on the heading, a wash underneath: enough to follow a group down the
    # page, not enough to fight the text.
    GROUP_TINT_DARK = 34
    GROUP_TINT_LIGHT = 26
    # The sorted column's cell on a member row: the run's colour at a
    # strength the theme's own text still reads on.
    GROUP_CELL_DARK = 110
    GROUP_CELL_LIGHT = 80

    def _paint_group_rows(self, sender, args):
        """Colour a group heading and wash its members, as rows are realised.

        Set on **every** row, not only the coloured ones: with recycling
        on, a container that was a heading a moment ago becomes a data row,
        and skipping the reset leaves a stripe across the sheets.
        """
        row = None
        entry = None
        try:
            row = args.Row
            entry = row.Item.Row
        except Exception:
            return

        is_heading = False
        alternation = 0
        coloured = False
        try:
            # A heading is a row with no key. Asking whether "grp" is set
            # is what it used to do, and that stopped being the same
            # question once member rows carried an alternation index too.
            is_heading = u'{0}'.format(entry['ishead']) == '1'
            alternation = self._as_int(entry['grp'])
            # Every run is coloured now, so the wash follows "this row is
            # in a run" - which "grp" carries - rather than "this run has
            # a heading", which only the longer ones do.
            coloured = bool(u'{0}'.format(entry['grp']))
        except Exception:
            is_heading = False

        if is_heading:
            try:
                _cell, _wash, head = self._run_brushes(alternation)
                row.Background = head
                row.FontWeight = FontWeights.Bold
            except Exception:
                pass
            return

        if self.grouped and coloured:
            try:
                _cell, wash, _head = self._run_brushes(alternation)
                row.Background = wash
                row.FontWeight = FontWeights.Normal
            except Exception:
                pass
            return

        try:
            row.Background = Brushes.Transparent
            row.FontWeight = FontWeights.Normal
        except Exception:
            pass

    # ==================================================================
    # remembering the window and the column widths
    # ==================================================================

    def column_widths(self):
        """Each column's width, as a star weight or as pixels.

        Which of the two matters. A column the user has never touched stays
        star sized so it keeps growing with the window; one they have
        dragged becomes an absolute width, because that is what dragging
        it meant. Saving everything as pixels would quietly stop the table
        stretching, and saving everything as stars would throw the drag
        away.
        """
        out = []
        grid = self.c('SheetGrid')
        if grid is None:
            return out
        try:
            for column in grid.Columns:
                col_id = u'{0}'.format(column.SortMemberPath)
                if not col_id:
                    continue
                width = column.Width
                if width.UnitType == DataGridLengthUnitType.Star:
                    out.append(u'{0}|star|{1:.4f}'.format(col_id,
                                                             float(width.Value)))
                else:
                    out.append(u'{0}|px|{1:.1f}'.format(
                        col_id, float(column.ActualWidth or width.Value)))
        except Exception:
            pass
        return out

    def apply_column_widths(self, saved):
        grid = self.c('SheetGrid')
        if grid is None or not saved:
            return
        wanted = {}
        for piece in saved:
            parts = u'{0}'.format(piece).split(u'|')
            if len(parts) != 3:
                continue
            try:
                wanted[parts[0]] = (parts[1], float(parts[2]))
            except Exception:
                continue
        try:
            for column in grid.Columns:
                col_id = u'{0}'.format(column.SortMemberPath)
                found = wanted.get(col_id)
                if not found:
                    continue
                kind, value = found
                if value <= 0:
                    continue
                if kind == 'star':
                    column.Width = DataGridLength(
                        value, DataGridLengthUnitType.Star)
                else:
                    column.Width = DataGridLength(value)
        except Exception:
            pass

    def remember_window(self):
        """Window size and column widths, into the global settings.

        Per machine, because a size that suits a 4K panel is wrong on a
        laptop. A template carries them too, for anyone who wants a
        template to set up the whole view - but the global one is what a
        plain launch uses.
        """
        try:
            # The size it was left at, not the shrunk title bar's.
            width, height = self.chrome.true_size()
            self.settings.set('window_width', int(width))
            self.settings.set('window_height', int(height))
        except Exception:
            pass
        try:
            self.settings.set('column_widths',
                              ps_config.put_list(self.column_widths()))
        except Exception:
            pass
        self.settings.save()

    def _settle_layout(self, sender=None, args=None):
        """Once, after the window is first drawn: measure the footer and the
        whole window again (1.56.1)."""
        try:
            self.window.ContentRendered -= self._settle_layout
        except Exception:
            pass
        for name in ('FooterButtons', 'FooterDock'):
            control = self.c(name)
            if control is None:
                continue
            try:
                control.InvalidateMeasure()
            except Exception:
                pass
        try:
            self.window.Content.InvalidateMeasure()
            self.window.UpdateLayout()
        except Exception:
            pass
        return True

    def restore_window(self):
        try:
            width = self.settings.number('window_width')
            height = self.settings.number('window_height')
            if width >= self.window.MinWidth:
                self.window.Width = width
            if height >= self.window.MinHeight:
                self.window.Height = height
        except Exception:
            pass

    # ------------------------------------------- adding and removing    # ------------------------------------------- adding and removing
    def add_columns(self, sender=None, args=None, after=None):
        sample_row = self._first_ticked_row() or (self.rows[0] if self.rows else None)
        lookup = self.lookup_for(sample_row) if sample_row is not None else None
        label = u''
        if sample_row is not None:
            label = sample_row.number or sample_row.name
        chosen = ps_pickwin.pick(
            self.catalogue, lookup, self.theme_name, self.window,
            u'Add columns', self.parameter_columns(), label)
        if not chosen:
            return

        # Land beside the heading that was right clicked, not on the far
        # right: somebody adding Discipline next to Sheet Number wants to
        # read them together.
        where = len(self.column_order)
        if after in self.column_order:
            where = self.column_order.index(after) + 1
        for offset, name in enumerate(chosen):
            col_id = u'p:{0}'.format(name)
            if col_id in self.column_order:
                continue
            self.column_order.insert(where + offset, col_id)

        self._build_columns()
        self._apply_filters()
        self.say(u'{0} column{1} added. Right click a heading to remove '
                 u'one.'.format(len(chosen), u'' if len(chosen) == 1 else u's'))

    def remove_column(self, col_id):
        if col_id not in self.column_order:
            return
        self.column_order.remove(col_id)
        self.column_search.pop(col_id, None)
        self.sort_stack = [pair for pair in self.sort_stack
                           if pair[0] != col_id]
        self._build_columns()
        self._apply_filters()
        self.say(u'"{0}" removed.'.format(self._heading_of(col_id)))

    def reset_columns(self, sender=None, args=None):
        self.column_order = self.starting_columns(self._mode_name(),
                                                  self.default_extras(),
                                                  self.browser_names)
        self.column_search = {}
        self.sort_stack = []
        self.forget_sort()
        self._apply_default_sort()
        self.grouped = True
        self.collapsed = set()
        try:
            self.c('GroupCheck').IsChecked = True
        except Exception:
            pass
        self._build_columns()
        self._apply_order()
        self._apply_grouping()
        self._apply_filters()
        self.say(u'Back to the standard columns.')

    def clear_column_searches(self, sender=None, args=None):
        self.column_search = {}
        for box in self.search_boxes.values():
            try:
                box.Text = u''
            except Exception:
                continue
        self._apply_filters()
        self._refresh_counts()

    # ------------------------------------------------- the heading menu
    def _header_right_click(self, sender, args):
        """Right click on a column heading opens the column menu.

        Watched on the grid rather than on each heading, because the
        headings are rebuilt every time a column is added or moved and
        per-heading wiring would have to be redone every time too.
        """
        try:
            header = self._header_under(args.OriginalSource)
        except Exception:
            header = None
        if header is None:
            self._heading_right_click(args)
            return
        col_id = u''
        try:
            col_id = u'{0}'.format(header.Column.SortMemberPath)
        except Exception:
            col_id = u''
        try:
            menu = self._column_menu(col_id)
            menu.PlacementTarget = header
            menu.IsOpen = True
            args.Handled = True
        except Exception:
            pass

    # ------------------------------------------- heading colours (1.54.0)

    def _heading_right_click(self, args):
        """A right-click on a group heading: its colour menu."""
        try:
            row = self._row_under(args.OriginalSource)
            entry = row.Item.Row if row is not None else None
        except Exception:
            entry = None
        if entry is None:
            return
        if u'{0}'.format(entry['ishead']) != u'1':
            self._row_right_click(row, args)
            return
        try:
            label = self.run_labels[self._as_int(entry['grp'])]
        except Exception:
            return
        try:
            menu = self._heading_colour_menu(label)
            menu.PlacementTarget = self.c('SheetGrid')
            menu.IsOpen = True
            args.Handled = True
        except Exception:
            pass

    # ------------------------------------------- open sheets (1.55.0)

    def _row_right_click(self, row, args):
        """A right-click on a sheet: Open sheets for what is highlighted.

        A row not already highlighted is highlighted on its own first -
        Excel's way - so the menu acts on what is under the pointer.
        """
        grid = self.c('SheetGrid')
        try:
            if row is not None and not bool(row.IsSelected):
                grid.SelectedItems.Clear()
                grid.SelectedItems.Add(row.Item)
        except Exception:
            pass
        entries = self.row_menu_entries(len(self.highlighted_rows()))
        if not entries:
            return
        try:
            menu = ContextMenu()
            self._styled(menu, 'ThemedContextMenu')
            for text, action in entries:
                item = self._menu_item()
                item.Header = text
                item.Click += self._make_row_action(action)
                menu.Items.Add(item)
            menu.PlacementTarget = grid
            menu.IsOpen = True
            args.Handled = True
        except Exception:
            pass

    def row_menu_entries(self, count):
        """[(text, action)] for a right-click on highlighted sheets."""
        if count <= 0:
            return []
        word = u'view' if self._is_views_mode() else u'sheet'
        return [(u'Open {0}{1}'.format(word, u'' if count == 1 else u's'),
                 'open_highlighted')]

    def _make_row_action(self, action):
        def handler(sender, args):
            if action == 'open_highlighted':
                self.open_highlighted()
        return handler

    def highlighted_rows(self):
        """The highlighted sheets (not headings), top of the list first."""
        grid = self.c('SheetGrid')
        found = []
        try:
            items = list(grid.SelectedItems)
        except Exception:
            return []
        for item in items:
            try:
                entry = item.Row
                if u'{0}'.format(entry['ishead']) == u'1':
                    continue
                row = self.rows_by_key.get(
                    self._as_key(u'{0}'.format(entry['key'])))
            except Exception:
                continue
            if row is None:
                continue
            try:
                place = grid.Items.IndexOf(item)
            except Exception:
                place = len(found)
            found.append((place, row))
        found.sort(key=lambda pair: pair[0])
        return [row for _place, row in found]

    def open_highlighted(self):
        rows = self.highlighted_rows()
        word = u'view' if self._is_views_mode() else u'sheet'
        return self.open_sheets([row.element for row in rows], word)

    def open_sheets(self, views, word=u'sheet'):
        """Open the sheets in Revit, then shrink the window to the bottom of
        the screen so they can be seen. Used by Selection and the Document
        Register alike."""
        views = [view for view in (views or []) if view is not None]
        if not views:
            self.say(u'Highlight the {0}s to open first.'.format(word))
            return False
        if getattr(self, 'exporting', False):
            self.say(u'Wait for the export to finish before opening '
                     u'{0}s.'.format(word))
            return False

        def job(uiapp):
            try:
                result = ps_revisions.open_views(uiapp.ActiveUIDocument,
                                                 views)
            except Exception as err:
                result = (0, [u'{0}'.format(err)])
            self._on_ui(lambda: self.say(
                ps_revisions.opened_report(result[0], result[1], word)))
        if not self._queue(job):
            return False
        self.say(u'Opening {0} {1}{2}...'.format(
            len(views), word, u'' if len(views) == 1 else u's'))
        try:
            self.chrome.shrink()
        except Exception:
            pass
        return True

    def heading_menu_entries(self, label):
        """[(text, action)] for a heading's colour menu. Pure enough for
        the bench."""
        custom = getattr(self, 'heading_custom', {}) or {}
        entries = [(u'Colour "{0}"'.format(label), 'swatches'),
                   (u'Custom colour...', 'custom')]
        if label in custom:
            entries.append((u'Reset this heading\'s colour', 'reset'))
        if custom:
            entries.append((u'Reset every heading colour', 'reset_all'))
        return entries

    def _heading_colour_menu(self, label):
        menu = ContextMenu()
        self._styled(menu, 'ThemedContextMenu')
        for text, action in self.heading_menu_entries(label):
            if action == 'swatches':
                menu.Items.Add(self._swatch_item(text, label, menu))
                continue
            item = self._menu_item()
            item.Header = text
            item.Click += self._make_heading_action(action, label)
            menu.Items.Add(item)
        return menu

    def _make_heading_action(self, action, label):
        def handler(sender, args):
            if action == 'custom':
                typed = ps_ui.ask_text(
                    u'Heading colour',
                    u'Colour for "{0}", as #RRGGBB:'.format(label),
                    self.heading_custom.get(label, u'#'), self.theme_name,
                    self.window)
                if typed is None:
                    return
                colour = ps_ramp.parse_hex(typed)
                if colour is None:
                    self.say(u'"{0}" is not a colour - type six hex digits, '
                             u'like #3FA75A.'.format(typed))
                    return
                self.set_heading_colour(label, colour)
            elif action == 'reset':
                colours = dict(self.heading_custom)
                colours.pop(label, None)
                self._keep_heading_colours(colours)
                self.say(u'"{0}" is back to grey.'.format(label))
            elif action == 'reset_all':
                self._keep_heading_colours({})
                self.say(u'Every heading colour reset.')
        return handler

    def _swatch_item(self, text, label, menu):
        item = self._menu_item()
        item.StaysOpenOnClick = True
        panel = StackPanel()
        panel.Orientation = Orientation.Vertical
        title = TextBlock()
        title.Text = text
        title.Margin = Thickness(0, 0, 0, 4)
        panel.Children.Add(title)
        wrap = WrapPanel()
        wrap.Width = 6 * 24
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

    def set_heading_colour(self, label, colour):
        """One heading's colour; Custom headers from now on."""
        colours = dict(self.heading_custom)
        colours[label] = colour
        if self.heading_mode != ps_ramp.CUSTOM:
            self.heading_mode = ps_ramp.CUSTOM
            self.settings.set('sel_heading_mode', self.heading_mode)
            self.settings.save()
        self._keep_heading_colours(colours)
        self.say(u'"{0}" is now {1}. Custom headers - the button cycles '
                 u'back to grey.'.format(label, colour))

    def _keep_heading_colours(self, colours):
        """Save the project's heading colours, and hand them to the
        register too: one set of colours for both tabs."""
        try:
            ps_config.write_heading_colours(self.doc, colours)
        except Exception as err:
            self.say(u'The heading colours could not be saved: {0}'
                     .format(err))
        self.take_heading_colours(colours)
        try:
            self.register.take_heading_colours(colours)
        except Exception:
            pass

    def take_heading_colours(self, colours):
        """The project's heading colours, changed on either tab."""
        self.heading_custom = dict(colours or {})
        self._repaint_headings()

    def cycle_heading_mode(self, sender=None, args=None):
        """The button: Coloured, Grey, Custom, round."""
        self.heading_mode = ps_ramp.next_mode(self.heading_mode)
        self.settings.set('sel_heading_mode', self.heading_mode)
        self.settings.save()
        self._repaint_headings()
        if self.heading_mode == ps_ramp.CUSTOM and not self.heading_custom:
            self.say(u'Custom headers: right-click a heading to pick its '
                     u'colour. Until then they are grey.')
        else:
            self.say(u'{0}.'.format(ps_ramp.MODE_LABELS[self.heading_mode]))

    def _repaint_headings(self):
        ps_ui.set_text(self.c('SelectionHeadingModeText'),
                       ps_ramp.MODE_LABELS.get(self.heading_mode, u''))
        try:
            self._apply_grouping()
            self._apply_filters()
            self.c('SheetGrid').Items.Refresh()
        except Exception:
            pass

    def _header_under(self, source):
        """Walk up from whatever was clicked to its column heading."""
        node = source
        for _step in range(12):
            if node is None:
                return None
            if isinstance(node, DataGridColumnHeader):
                return node
            try:
                node = VisualTreeHelper.GetParent(node)
            except Exception:
                return None
        return None

    def _column_menu(self, col_id):
        menu = ContextMenu()
        self._styled(menu, 'ThemedContextMenu')

        add = self._menu_item()
        add.Header = u'Add column...'
        add.Click += self._make_add_after(col_id)
        menu.Items.Add(add)

        if self.is_parameter_column(col_id):
            remove = self._menu_item()
            remove.Header = u'Remove "{0}"'.format(self._heading_of(col_id))
            remove.Click += self._make_remove(col_id)
            menu.Items.Add(remove)

        if any(self.column_search.values()):
            menu.Items.Add(Separator())
            clear = self._menu_item()
            clear.Header = u'Clear every column search'
            clear.Click += self.clear_column_searches
            menu.Items.Add(clear)

        if self.parameter_columns() or self.sort_stack:
            menu.Items.Add(Separator())
            reset = self._menu_item()
            reset.Header = u'Back to the standard columns'
            reset.Click += self.reset_columns
            menu.Items.Add(reset)
        return menu

    def _menu_item(self):
        item = MenuItem()
        self._styled(item, 'ThemedMenuItem')
        return item

    def _make_add_after(self, col_id):
        def handler(sender, args):
            self.add_columns(after=col_id)
        return handler

    def _make_remove(self, col_id):
        def handler(sender, args):
            self.remove_column(col_id)
        return handler

    def _tick_changed(self, sender, args):
        try:
            if args.Column.ColumnName != 'sel':
                return
        except Exception:
            return
        if getattr(self, '_suspend_ticks', False):
            return

        entry = None
        try:
            entry = args.Row
        except Exception:
            entry = None

        if entry is not None and self._is_heading(entry):
            # The tick on a group heading ticks the group. It sits in the
            # same column as every other tick and is bound to the same
            # field, so it arrives here like any other change and is
            # turned into the group's worth of changes.
            self._tick_group(entry)
        elif entry is not None and self._spread_tick(entry):
            self._sync_group_ticks()
        else:
            # And the other direction: tick the last unticked sheet in a
            # group by hand and its heading should agree, or the heading
            # is telling you something that is no longer true.
            self._sync_group_ticks()

        self._refresh_counts()
        self._refresh_plan()

    def _spread_tick(self, changed):
        """Push a tick out across the rows highlighted with it.

        Returns whether it went anywhere. The highlighted keys were
        taken in _row_click, before the DataGrid had a chance to
        collapse the selection onto the row being clicked.
        """
        picked = getattr(self, '_tick_selection', set())
        # One use only. Ticking by keyboard, or a second tick without a
        # fresh click, is one row's business.
        self._tick_selection = set()
        if not picked:
            return False
        try:
            key = u'{0}'.format(changed['key'])
            wanted = bool(changed['sel'])
        except Exception:
            return False
        targets = self.tick_targets(key, picked)
        if len(targets) < 2:
            return False

        self._suspend_ticks = True
        moved = 0
        try:
            for entry in self.table.Rows:
                if self._is_heading(entry):
                    continue
                if u'{0}'.format(entry['key']) not in targets:
                    continue
                if bool(entry['sel']) != wanted:
                    entry['sel'] = wanted
                    moved += 1
        except Exception:
            pass
        finally:
            self._suspend_ticks = False
        if moved:
            self.say(u'{0} highlighted {1}s {2}.'.format(
                len(targets),
                u'view' if self._is_views_mode() else u'sheet',
                u'ticked' if wanted else u'unticked'))
        return True

    def _is_heading(self, entry):
        try:
            return u'{0}'.format(entry['ishead']) == '1'
        except Exception:
            return False

    def _tick_group(self, heading):
        """Push a heading's tick down onto every member of its group."""
        group = self._as_int(heading['gid'])
        members = self.groups.get(group, [])
        if not members:
            return
        try:
            wanted = bool(heading['sel'])
        except Exception:
            return
        self._suspend_ticks = True
        try:
            for entry in members:
                # Hidden members included. A collapsed group is still a
                # group, and ticking its heading meaning "all but the
                # ones you cannot see" would be a trap.
                entry['sel'] = wanted
        finally:
            self._suspend_ticks = False

    def _sync_group_ticks(self):
        """Each heading's tick reflects whether its whole group is ticked.

        No early return when there are no groups. A heading whose group
        has gone is exactly the row that would otherwise keep a tick
        nothing stands behind, and skipping the walk to save a few
        microseconds is what leaves it there.
        """
        self._suspend_ticks = True
        try:
            for entry in self.table.Rows:
                if not self._is_heading(entry):
                    continue
                members = self.groups.get(self._as_int(entry['gid']), [])
                whole = bool(members) and all(
                    [bool(member['sel']) for member in members])
                if bool(entry['sel']) != whole:
                    entry['sel'] = whole
        except Exception:
            pass
        finally:
            self._suspend_ticks = False

    def _header_tick(self, sender, args):
        try:
            wanted = bool(sender.IsChecked)
        except Exception:
            wanted = True
        self._set_all(wanted, visible_only=True)

    # ==================================================================
    # what the Document Register tab asks of the window
    #
    # The register keeps its own list of what is in it - a tick there is
    # "in the register", not "print" - so all it needs from here is the
    # sheets, and to know when it is on screen.
    # ==================================================================

    def on_register_tab(self):
        return self._tab_index() == self.TAB_REGISTER

    def sheet_rows(self):
        """Every sheet, read the way the Selection tab reads them.

        The rows already in hand when the Selection tab is on sheets, so
        the title blocks are not read twice; read afresh when it is on
        views, because the register is a list of sheets either way.
        """
        if not self._is_views_mode():
            return list(self.rows)
        return ps_model.read_rows(self.doc, 'sheets')

    # ==================================================================
    # filling the table
    # ==================================================================

    def _fill_table(self):
        self._suspend_ticks = True
        try:
            ticked = self._ticked_keys()
            # First fill after the tool opens: whatever was selected in
            # Revit arrives ticked. This used to run before the rows
            # existed, so it ticked nothing at all and the sheets came in
            # isolated but unticked.
            if self._first_fill and self._preselected_keys:
                ticked = ticked | set([u'{0}'.format(key) for key
                                       in self._preselected_keys])
            self.table.Rows.Clear()
            for index, row in enumerate(self.rows):
                entry = self.table.NewRow()
                entry['sel'] = (u'{0}'.format(row.key) in ticked)
                entry['num'] = row.number
                entry['name'] = row.name
                entry['rev'] = row.revision
                entry['size'] = row.size
                entry['fname'] = u''
                entry['key'] = u'{0}'.format(row.key)
                entry['vis'] = '1'
                entry['show'] = '1'
                entry['gid'] = u''
                entry['grp'] = u''
                entry['ord'] = u'{0:06d}'.format(index) + u'\x01'
                self.table.Rows.Add(entry)
            self._first_fill = False
        finally:
            self._suspend_ticks = False

    def _ticked_keys(self):
        found = set()
        try:
            for entry in self.table.Rows:
                if bool(entry['sel']) and u'{0}'.format(entry['key']):
                    found.add(u'{0}'.format(entry['key']))
        except Exception:
            pass
        return found

    def _as_key(self, text):
        try:
            return int(text)
        except Exception:
            return text

    def _apply_filters(self):
        """Take the filter decision once and write it into ``vis``.

        ``show`` is then ``vis`` minus anything inside a collapsed group.
        Two reasons to hide a row need two flags: collapsed onto one,
        reopening a group resurrects the rows the filter had removed.
        """
        try:
            needle = u'{0}'.format(self.c('SearchBox').Text or u'').strip().lower()
        except Exception:
            needle = u''
        set_name = ps_ui.combo_text(self.c('SheetSetCombo'), NO_SET)
        members = self.sheet_sets.get(set_name) if set_name else None
        try:
            on_list_only = bool(self.c('OnSheetListCheck').IsChecked)
        except Exception:
            on_list_only = False

        shown = 0
        for entry in self.table.Rows:
            if not u'{0}'.format(entry['key']):
                continue                       # a heading, decided below
            key = self._as_key(u'{0}'.format(entry['key']))
            row = self.rows_by_key.get(key)
            visible = True

            if self.isolated_keys is not None and key not in self.isolated_keys:
                visible = False
            if visible and members is not None and key not in members:
                visible = False
            if visible and on_list_only and row is not None and row.is_sheet:
                if not row.on_sheet_list:
                    visible = False
            if visible and needle:
                parts = [
                    u'{0}'.format(entry['num'] or u''),
                    u'{0}'.format(entry['name'] or u''),
                    u'{0}'.format(entry['fname'] or u''),
                ]
                # Anything the user put on the grid is something they may
                # want to search by; a column you can see but not find in
                # is half a feature.
                for index in range(len(self.parameter_columns())):
                    try:
                        parts.append(u'{0}'.format(
                            entry['c{0}'.format(index)] or u''))
                    except Exception:
                        continue
                if needle not in u' '.join(parts).lower():
                    visible = False

            # Then each column's own box, Excel style: every one of them
            # has to match, so they narrow rather than widen.
            if visible:
                for col_id, term in self.column_search.items():
                    term = u'{0}'.format(term or u'').strip().lower()
                    if not term:
                        continue
                    try:
                        cell = u'{0}'.format(
                            entry[self._data_key(col_id)] or u'').lower()
                    except Exception:
                        cell = u''
                    if term not in cell:
                        visible = False
                        break

            entry['vis'] = '1' if visible else '0'
            group = self._as_int(entry['gid']) if self.grouped else 0
            entry['show'] = ('1' if (visible and group not in self.collapsed)
                             else '0')
            if visible:
                shown += 1

        # A heading shows when its group still has anything in it, whether
        # or not the group is collapsed - collapsing hides the members, not
        # the way back to them.
        if self.grouped:
            for entry in self.table.Rows:
                if u'{0}'.format(entry['key']):
                    continue
                group = self._as_int(entry['gid'])
                alive = [m for m in self.groups.get(group, [])
                         if u'{0}'.format(m['vis']) == '1']
                entry['vis'] = '1' if alive else '0'
                entry['show'] = entry['vis']
            self._label_groups()

        ps_ui.set_visible(self.c('CollapseAllButton'), bool(self.grouped))
        ps_ui.set_visible(self.c('SelectionHeadingModeButton'),
                          bool(self.grouped))
        return shown

    def _set_all(self, wanted, visible_only=True):
        self._suspend_ticks = True
        try:
            for entry in self.table.Rows:
                # A heading occupies a row position but holds no sheet.
                # Anything walking positions has to step over it, or a
                # tick-all lands on decoration and is lost.
                if not u'{0}'.format(entry['key']):
                    continue
                if visible_only and u'{0}'.format(entry['show']) != '1':
                    continue
                entry['sel'] = bool(wanted)
        finally:
            self._suspend_ticks = False
        self._sync_group_ticks()
        self._refresh_counts()
        self._refresh_plan()

    def _invert(self):
        self._suspend_ticks = True
        try:
            for entry in self.table.Rows:
                if not u'{0}'.format(entry['key']):
                    continue
                if u'{0}'.format(entry['show']) != '1':
                    continue
                entry['sel'] = not bool(entry['sel'])
        finally:
            self._suspend_ticks = False
        self._sync_group_ticks()
        self._refresh_counts()
        self._refresh_plan()

    # ==================================================================
    # combos that never change
    # ==================================================================

    def _fill_static_combos(self):
        ps_ui.fill_combo(self.c('MarginCombo'),
                         [pair[0] for pair in MARGIN_CHOICES])
        ps_ui.fill_combo(self.c('RasterQualityCombo'),
                         [pair[0] for pair in RASTER_CHOICES])
        ps_ui.fill_combo(self.c('ColorsCombo'),
                         [pair[0] for pair in COLOUR_CHOICES])
        ps_ui.fill_combo(self.c('DwgVersionCombo'),
                         [pair[0] for pair in DWG_VERSIONS])

        self.native_pdf = ps_export.native_pdf_available(self.doc)
        printers = [REVIT_PDF] if self.native_pdf else []
        printers.extend(ps_export.list_printers())
        self.printer_list = printers
        # Picked out once, here, rather than searched for every time the
        # dropdown changes. See KNOWN_PRINTERS in ps_export for why this
        # one driver gets special treatment.
        self.preferred_printer = ps_export.preferred_printer(printers)
        ps_ui.fill_combo(self.c('PrinterCombo'), printers)

        setups = [DEFAULT_DWG_SETUP] + ps_export.list_dwg_setups(self.doc)
        ps_ui.fill_combo(self.c('DwgSetupCombo'), setups)

        for control_name, choices in (
                ('NwcParamsCombo', NWC_PARAM_CHOICES),
                ('NwcCoordsCombo', NWC_COORD_CHOICES),
                ('IfcVersionCombo', IFC_VERSION_CHOICES),
                ('IfcFileTypeCombo', IFC_FILE_TYPE_CHOICES),
                ('IfcSpaceBoundCombo', IFC_BOUNDARY_CHOICES),
                ('IfcOriginCombo', IFC_ORIGIN_CHOICES),
                ('IfcDetailCombo', IFC_DETAIL_CHOICES),
                ('IfcLinkedCombo', IFC_LINKED_CHOICES)):
            ps_ui.fill_combo(self.c(control_name),
                             [pair[0] for pair in choices])

        self.ifc_phases = ps_model.read_phases(self.doc)
        ps_ui.fill_combo(self.c('IfcPhaseCombo'), self.ifc_phase_names(),
                         selected=IFC_DEFAULT_PHASE)
        self._fill_ifc_setups()

        self._fill_sheet_sets()
        self._fill_profiles()

    def ifc_phase_names(self):
        return [IFC_DEFAULT_PHASE] + sorted(self.ifc_phases.keys(),
                                            key=lambda n: n.lower())

    def _fill_ifc_setups(self, selected=None):
        names = [IFC_IN_SESSION] + ps_config.ifc_setup_names()
        combo = self.c('IfcSetupCombo')
        try:
            combo.SelectionChanged -= self._ifc_setup_changed
        except Exception:
            pass
        ps_ui.fill_combo(combo, names, selected=selected or IFC_IN_SESSION)
        try:
            combo.SelectionChanged += self._ifc_setup_changed
        except Exception:
            pass

    def _fill_sheet_sets(self):
        names = [NO_SET] + sorted(self.sheet_sets.keys(),
                                  key=lambda n: n.lower())
        ps_ui.fill_combo(self.c('SheetSetCombo'), names, selected=NO_SET)

    def _fill_profiles(self, selected=None):
        names = [NO_TEMPLATE] + ps_config.profile_names(self.doc)
        combo = self.c('ProfileCombo')
        try:
            combo.SelectionChanged -= self._profile_changed
        except Exception:
            pass
        ps_ui.fill_combo(combo, names, selected=selected or NO_TEMPLATE)
        try:
            combo.SelectionChanged += self._profile_changed
        except Exception:
            pass

    # ==================================================================
    # wiring
    # ==================================================================

    def _wire(self):
        clicks = [
            ('ThemeChip', self.toggle_theme),
            ('SetupButton', lambda s, a: self.open_setup()),
            ('ProfileNewButton', self.new_profile),
            ('ProfileSaveButton', self.save_profile),
            ('ProfileDeleteButton', self.delete_profile),
            ('ProfileImportButton', self.import_templates),
            ('ProfileExportButton', self.export_templates),
            ('SelectAllButton', lambda s, a: self._set_all(True)),
            ('SelectNoneButton', lambda s, a: self._set_all(False)),
            ('InvertButton', lambda s, a: self._invert()),
            ('CollapseAllButton', self.collapse_all),
            ('SelectionHeadingModeButton', self.cycle_heading_mode),
            ('SaveSetButton', self.save_sheet_set),
            ('CustomNameButton', self.open_name_dialog),
            ('FormatCustomNameButton', self.open_name_dialog),
            ('DwgCustomNameButton', self.open_name_dialog),
            ('OrderButton', self.open_order_dialog),
            ('BrowseButton', self.browse_root),
            ('StagingBrowseButton', self.browse_staging),
            ('AddTokenButton', self.add_token),
            ('MakeDefaultPrinterButton', self.make_default_printer),
            ('NwcCustomNameButton', self.open_name_dialog),
            ('IfcCustomNameButton', self.open_name_dialog),
            ('IfcUserPsetsBrowse',
             lambda s, a: self.browse_into(
                 'IfcUserPsetsBox', u'User defined property sets',
                 '.txt', u'Property set definitions')),
            ('IfcParamMapBrowse',
             lambda s, a: self.browse_into(
                 'IfcParamMapBox', u'Parameter mapping table',
                 '.txt', u'Parameter mapping table')),
            ('IfcHeaderButton', self.explain_ifc_header),
            ('IfcAddressButton', self.explain_ifc_address),
            ('IfcClassificationButton', self.explain_ifc_classification),
            ('IfcImportSettingsButton', self.import_ifc_settings),
            ('IfcExportSettingsButton', self.export_ifc_settings),
            ('BackButton', self.go_back),
            ('NextButton', self.go_next),
            ('ExportButton', self.start_export),
            ('ExpressExportButton', self.express_export),
            ('CancelExportButton', self.stop_export),
        ]
        for name, handler in clicks:
            control = self.c(name)
            if control is None:
                continue
            try:
                control.Click += handler
            except Exception:
                continue

        for name in ('SearchBox',):
            box = self.c(name)
            if box is not None:
                try:
                    box.TextChanged += self._search_changed
                except Exception:
                    pass

        box = self.c('StagingBox')
        if box is not None:
            try:
                box.TextChanged += self._staging_changed
            except Exception:
                pass

        for name in ('RootFolderBox', 'TokenBox'):
            box = self.c(name)
            if box is not None:
                try:
                    box.TextChanged += self._path_changed
                except Exception:
                    pass

        combo = self.c('SheetSetCombo')
        if combo is not None:
            try:
                combo.SelectionChanged += self._filter_changed
            except Exception:
                pass

        printer = self.c('PrinterCombo')
        if printer is not None:
            try:
                printer.SelectionChanged += self._printer_changed
            except Exception:
                pass

        for name in ('SheetsRadio', 'ViewsRadio'):
            radio = self.c(name)
            if radio is not None:
                try:
                    radio.Checked += self._mode_changed
                except Exception:
                    pass

        for name in ('PlaceCenterRadio', 'PlaceOffsetRadio'):
            radio = self.c(name)
            if radio is not None:
                try:
                    radio.Checked += self._placement_changed
                except Exception:
                    pass

        for name in ('SeparateFilesRadio', 'CombineRadio'):
            radio = self.c(name)
            if radio is not None:
                try:
                    radio.Checked += self._combine_changed
                except Exception:
                    pass

        box = self.c('DwgXrefCheck')
        if box is not None:
            try:
                box.Checked += self._xref_changed
                box.Unchecked += self._xref_changed
            except Exception:
                pass

        # Every format's tick and tile in one pass, from the registry, so a
        # new format cannot be added to the tab and left unwired.
        for fmt, tick, tile, _group, _panel, _label, _live in FORMATS:
            box = self.c(tick)
            if box is not None:
                try:
                    box.Checked += self._format_changed
                    box.Unchecked += self._format_changed
                except Exception:
                    pass
            button = self.c(tile)
            if button is not None:
                try:
                    button.Click += self._make_tile_click(fmt)
                except Exception:
                    pass

        # The two property-set file pickers only make sense when their own
        # tickbox is on, and Revit's own dialog greys them the same way.
        for box_name, targets in (
                ('IfcUserPsetsCheck',
                 ('IfcUserPsetsBox', 'IfcUserPsetsBrowse',
                  'IfcTypePropsCheck')),
                ('IfcParamMapCheck',
                 ('IfcParamMapBox', 'IfcParamMapBrowse')),
                ('IfcSchedulePsetsCheck', ('IfcSpecificSchedulesCheck',)),
                ('Ifc2dRoomBoundaryCheck', ('IfcSiteElevationCheck',))):
            box = self.c(box_name)
            if box is None:
                continue
            handler = self._make_dependants(box_name, targets)
            try:
                box.Checked += handler
                box.Unchecked += handler
            except Exception:
                pass

        box = self.c('GroupCheck')
        if box is not None:
            try:
                box.Checked += self.toggle_grouping
                box.Unchecked += self.toggle_grouping
            except Exception:
                pass

        box = self.c('ShowAllCheck')
        if box is not None:
            try:
                box.Checked += self._show_all_changed
                box.Unchecked += self._show_all_changed
            except Exception:
                pass

        box = self.c('OnSheetListCheck')
        if box is not None:
            try:
                box.Checked += self._filter_changed
                box.Unchecked += self._filter_changed
            except Exception:
                pass

        for name in ('FolderPerFormatCheck',):
            box = self.c(name)
            if box is not None:
                try:
                    box.Checked += self._path_changed
                    box.Unchecked += self._path_changed
                except Exception:
                    pass

        # Offering to open the folder, and the debug log, are global
        # settings rather than part of a template: they are about how you
        # like to work, not about this job.
        for name, key in (('OpenFolderCheck', 'open_folder_after_export'),
                          ('DebugCheck', 'debug'),
                          ('SuppressCheck', 'suppress_dialogs')):
            box = self.c(name)
            if box is None:
                continue
            try:
                box.IsChecked = self.settings.flag(key)
                box.Checked += self._make_setting_saver(key)
                box.Unchecked += self._make_setting_saver(key)
            except Exception:
                continue

        tabs = self.c('MainTabs')
        if tabs is not None:
            try:
                tabs.SelectionChanged += self._tab_changed
            except Exception:
                pass

    # -------------------------------------------------------- handlers
    def _make_setting_saver(self, key):
        def handler(sender, args):
            try:
                self.settings.set(key, '1' if sender.IsChecked else '0')
                self.settings.save()
            except Exception:
                pass
            if key == 'debug':
                self.say(u'Debug log on. The next export writes a blow-by-blow '
                         u'log beside the tool\'s error log.'
                         if self._flag_of('DebugCheck')
                         else u'Debug log off.')
        return handler

    def _search_changed(self, sender, args):
        self._apply_filters()
        self._refresh_counts()

    def _filter_changed(self, sender, args):
        self._apply_filters()
        self._refresh_counts()
        self._refresh_plan()

    def _mode_changed(self, sender, args):
        if not getattr(self, '_ready', False):
            return
        self.isolated_keys = None
        ps_ui.set_visible(self.c('IsolationChip'), False)
        # Sheets and views carry different columns, so the order in hand
        # belongs to the mode being left. Park it, take the other one, and
        # drop any sort or search aimed at a column that no longer exists.
        self._park_columns(self._other_mode())
        self._park_rules(self._other_mode())
        self._read_model()
        self._adopt_columns(self._mode_name())
        self._adopt_rules(self._mode_name())
        self._fill_table()
        self._refresh_all()

    def _other_mode(self):
        return 'sheets' if self._is_views_mode() else 'views'

    def _park_rules(self, mode):
        sets = getattr(self, 'rules_by_mode', None)
        if sets is None:
            sets = self.rules_by_mode = {}
        sets[mode] = list(self.rules)

    def _adopt_rules(self, mode):
        sets = getattr(self, 'rules_by_mode', None) or {}
        self.rules = list(sets.get(mode) or ps_naming.default_rules(mode))

    def _park_columns(self, mode):
        self.column_orders[mode] = list(self.column_order)
        self.column_orders[mode + '.widths'] = self.column_widths()

    def _adopt_columns(self, mode):
        order = self.column_orders.get(mode)
        if not order:
            order = self.starting_columns(mode, self.default_extras(),
                                          self.browser_names)
        self.column_order = list(order)
        self._saved_widths = self.column_orders.get(mode + '.widths', [])
        live = set(self.column_order)
        self.sort_stack = [pair for pair in self.sort_stack if pair[0] in live]
        for col_id in list(self.column_search.keys()):
            if col_id not in live:
                self.column_search.pop(col_id, None)
        # The sort that belonged to the other list has gone. This one
        # opens the way it was left, or - never touched - the way it comes
        # out of the box: Views as the Project Browser has it, Sheets
        # grouped on the sheet series.
        if not self._restore_sort(mode):
            if mode == 'views' or getattr(self, '_ready', False):
                self.sort_stack = []
            self._apply_default_sort()
        self._build_columns()

    def _placement_changed(self, sender, args):
        offset = False
        try:
            offset = bool(self.c('PlaceOffsetRadio').IsChecked)
        except Exception:
            pass
        for name in ('MarginCombo', 'OffsetXBox', 'OffsetYBox'):
            control = self.c(name)
            if control is not None:
                try:
                    control.IsEnabled = offset
                except Exception:
                    pass

    def _combine_changed(self, sender, args):
        combine = False
        try:
            combine = bool(self.c('CombineRadio').IsChecked)
        except Exception:
            pass
        button = self.c('OrderButton')
        if button is not None:
            try:
                button.IsEnabled = combine
            except Exception:
                pass
        keep = self.c('KeepPaperSizeCheck')
        if keep is not None:
            try:
                keep.IsEnabled = combine
            except Exception:
                pass
        self._refresh_plan()

    def _format_changed(self, sender, args):
        self._refresh_plan()
        self._say_formats()

    def _printer_changed(self, sender, args):
        name = ps_ui.combo_text(self.c('PrinterCombo'))
        note = self.c('PrinterNote')
        driver = bool(name) and name != REVIT_PDF
        known = ps_export.known_printer(name) if driver else None
        if not driver:
            text = (u"Revit's own exporter needs no printer set up and keeps "
                    u"each sheet at its own size.")
            # Say it is there rather than leave it to be found. Somebody
            # with ProSheets installed has already paid for a driver that
            # does not prompt.
            if self.preferred_printer:
                text += (u'  "{0}" is installed on this machine, which is '
                         u'the one driver here that is already set up for '
                         u'unattended export.'.format(self.preferred_printer))
            ps_ui.set_text(note, text)
        elif known is not None:
            description, needs_staging = known
            text = u'"{0}" is {1}.'.format(name, description)
            if needs_staging:
                text += (u'  It is still PDF24 underneath, so it writes to '
                         u'PDF24\'s own output folder rather than to the '
                         u'path Revit asks for - set "Driver saves to" '
                         u'below, or run one sheet and let the report find '
                         u'the folder for you.')
            ps_ui.set_text(note, text)
        else:
            ps_ui.set_text(note, u'Sheets print through "{0}". Its own '
                                 u'settings decide compression and quality; '
                                 u'it must be set not to ask for a file name.'
                                 .format(name))
        # Where a driver saves is a fact about the driver, not about the
        # job, so it is remembered per printer and follows the dropdown.
        # Keeping it in the template was wrong: switching from PDF24 to
        # another driver silently carried the wrong folder over, or none at
        # all, and the run failed for a reason that looked like nothing.
        previous = self._current_printer
        if previous and previous != name:
            self._remember_staging(previous, self._text_of('StagingBox'))
        if name != previous:
            self._current_printer = name
            if driver:
                remembered = self._recall_staging(name)
                try:
                    self.c('StagingBox').Text = remembered
                except Exception:
                    pass

        for control_name in ('StagingBox', 'StagingBrowseButton'):
            control = self.c(control_name)
            if control is not None:
                try:
                    control.IsEnabled = driver
                except Exception:
                    pass
        self._say_staging()

    def _say_staging(self):
        note = self.c('StagingNote')
        printer = ps_ui.combo_text(self.c('PrinterCombo'))
        staging = self._text_of('StagingBox')
        if not printer or printer == REVIT_PDF:
            ps_ui.set_text(note, u'Not needed: the built-in exporter writes '
                                 u'straight to the file name you asked for.')
        elif staging:
            if self._busy_folder(staging):
                ps_ui.set_text(note,
                               u'Careful: that is a folder you use. Anything '
                               u'that collects PDFs takes whatever new PDF '
                               u'appears while a run is going, so a PDF saved '
                               u'there by anything else mid-run would be '
                               u'renamed and moved with the sheets. A folder '
                               u'of its own is safer.')
            else:
                ps_ui.set_text(note,
                               u'Each sheet is collected from that folder and '
                               u'renamed. "{0}" still has to be set to save '
                               u'there on its own rather than asking - it '
                               u'names the file, this tool renames it.'
                               .format(printer))
        else:
            ps_ui.set_text(note,
                           u'Empty means the driver is expected to take the '
                           u'path Revit gives it. If nothing lands, "{0}" is '
                           u'saving where its own settings say - point this '
                           u'at that folder.'.format(printer))

    def _staging_key(self, printer):
        return ps_config.staging_key(printer)

    def _remember_staging(self, printer, folder):
        if not printer or printer == REVIT_PDF:
            return
        try:
            self.settings.set(self._staging_key(printer), folder or u'')
            self.settings.save()
        except Exception:
            pass

    def _recall_staging(self, printer):
        if not printer or printer == REVIT_PDF:
            return u''
        try:
            return self.settings.text(self._staging_key(printer), u'')
        except Exception:
            return u''

    def _busy_folder(self, path):
        """Is this a folder the user keeps things in, rather than a staging one?

        Collecting works by taking whatever new PDF turns up, so pointing it
        at the Desktop means a PDF saved there by anything else during a run
        gets renamed and filed with the sheets.
        """
        try:
            wanted = os.path.normcase(os.path.normpath(path)).rstrip('\\/')
        except Exception:
            return False
        if not wanted:
            return False
        env = os.environ
        risky = []
        for base in (env.get('USERPROFILE', ''), env.get('OneDrive', ''),
                     env.get('OneDriveCommercial', '')):
            if not base:
                continue
            risky.append(base)
            for leaf in ('Desktop', 'Documents', 'Downloads', 'Pictures'):
                risky.append(os.path.join(base, leaf))
        for candidate in risky:
            try:
                if os.path.normcase(os.path.normpath(candidate)).rstrip('\\/') == wanted:
                    return True
            except Exception:
                continue
        return False

    def browse_staging(self, sender=None, args=None):
        chosen = ps_ui.browse_folder(
            self._text_of('StagingBox'),
            u'Where does the driver save its PDFs?')
        if chosen:
            try:
                self.c('StagingBox').Text = chosen
            except Exception:
                pass

    def _xref_changed(self, sender, args):
        ps_ui.set_text(
            self.c('DwgXrefNote'),
            u'On: views and links become XREFs beside the DWG.'
            if self._flag_of('DwgXrefCheck')
            else u'Off: links and views are bound into the DWG.')

    def _staging_changed(self, sender, args):
        self._say_staging()
        self._remember_staging(ps_ui.combo_text(self.c('PrinterCombo')),
                               self._text_of('StagingBox'))

    def _path_changed(self, sender, args):
        self._refresh_plan()

    def _tab_changed(self, sender, args):
        try:
            if args.OriginalSource is not sender:
                return
        except Exception:
            pass
        self._say_step()
        index = self._tab_index()
        if index == self.TAB_REGISTER:
            self.register.show()
        elif index == self.TAB_CREATE:
            self._refresh_plan()

    # ==================================================================
    # theme
    # ==================================================================

    # Follow first, because the house standard is to match Revit's canvas.
    # The two pinned modes are there for the case Revit cannot answer for:
    # a second monitor, a projector, somebody who simply prefers the other
    # one.
    THEME_MODES = ['follow', 'dark', 'light']

    # How often the canvas is re-read while following. Two seconds is
    # under the threshold where a person notices the window is behind
    # Revit, and it is a property read, not a round trip.
    THEME_WATCH_MS = 2000

    def _start_theme_watch(self):
        """Re-read Revit's canvas theme while the window is open.

        A timer rather than Revit's own theme changed event on purpose.
        Unsubscribing an IronPython bound method from a .NET event does
        not reliably work - each attribute access makes a fresh delegate,
        so the -= removes nothing - and a modeless window that leaks a
        handler onto the application outlives itself. A DispatcherTimer
        stops when it is told to.
        """
        try:
            timer = DispatcherTimer()
            timer.Interval = TimeSpan.FromMilliseconds(self.THEME_WATCH_MS)
            timer.Tick += self._theme_tick
            timer.Start()
            self._theme_timer = timer
        except Exception:
            self._theme_timer = None

    def _theme_tick(self, sender=None, args=None):
        if self.theme_mode != 'follow':
            return
        try:
            wanted = theme.detect_revit_theme(self.theme_name)
        except Exception:
            return
        if wanted and wanted != self.theme_name:
            self._wear_theme(wanted)
            self._say_theme()

    def _wear_theme(self, name):
        """Put a palette on the live window, repainting what code drew."""
        self.theme_name = name
        theme.apply(self.window, self.theme_name)
        # The sort outlines, the run colours and the group row washes are
        # brushes set in code, so they do not follow a palette swap on
        # their own.
        self._paint_sort_headers()
        self._apply_grouping()
        self._apply_filters()
        try:
            self.c('SheetGrid').Items.Refresh()
        except Exception:
            pass
        # The register's heading bands, washes and tab colours are set in
        # code too.
        try:
            self.register.repaint()
        except Exception:
            pass

    def toggle_theme(self, sender=None, args=None):
        """Cycle Auto, Dark, Light."""
        try:
            place = self.THEME_MODES.index(self.theme_mode)
        except Exception:
            place = 0
        self.theme_mode = self.THEME_MODES[(place + 1) % len(self.THEME_MODES)]
        self._wear_theme(theme.resolve(self.theme_mode, self.theme_name))
        self._say_theme()
        self.settings.set('theme_mode', self.theme_mode)
        self.settings.save()

    def _first_run_setup(self):
        """Offer setup the first time this machine opens the tool."""
        try:
            if not ps_setupwin.needed(self.settings):
                return
            self.open_setup(first_run=True)
        except Exception:
            pass

    def open_setup(self, sender=None, args=None, first_run=False,
                   section=None):
        """The per machine settings, on demand or on a first run.

        ``section`` scrolls straight to one part of the window - the
        register's Settings button opens it at the register's own section.
        """
        series_before = self.series_column()
        try:
            saved = ps_setupwin.run(self.doc, self.settings, self.theme_name,
                                    self.window, first_run, self.catalogue,
                                    focus=section)
        except Exception:
            return
        if not saved:
            return
        # Push what was chosen onto the live window rather than waiting
        # for a reopen; somebody who has just said "use Revit's own
        # exporter" should see it selected.
        printer = self.settings.text('default_printer') or u''
        ps_ui.fill_combo(self.c('PrinterCombo'), self.printer_list,
                         selected=printer or REVIT_PDF)
        if printer:
            staging = self._recall_staging(printer)
            if staging:
                try:
                    self.c('StagingBox').Text = staging
                except Exception:
                    pass
        if not self._text_of('RootFolderBox'):
            try:
                self.c('RootFolderBox').Text = self.settings.text(
                    'default_root', u'')
            except Exception:
                pass
        self._printer_changed(None, None)
        # The series and discipline columns come from setup, so the
        # list has to be rebuilt around whatever was just chosen.
        self.column_orders = {}
        self._adopt_columns(self._mode_name())
        series = self.series_column()
        if series and series in self.column_order and not self.sort_stack:
            self.sort_stack = [(series, False)]
        # A sheet series named (or changed) just now is what the Sheets list
        # groups on first, whatever it was left sorted by before.
        if series and series != series_before and not self._is_views_mode():
            self.sort_stack = [(series, False)] + [
                pair for pair in self.sort_stack
                if pair[0] != series][:self.MAX_SORT_LEVELS - 1]
            if series not in self.column_order:
                order = list(self.column_order)
                where = order.index('fname') if 'fname' in order \
                    else len(order)
                order.insert(where, series)
                self.column_order = order
                self._build_columns()
            self._ensure_grouped()
            self.collapsed = set()
            self.remember_sort()
        self._apply_order()
        self._apply_grouping()
        self._apply_filters()
        self._paint_sort_headers()
        self._refresh_plan()
        # The register's tabs and headings come from the same two
        # parameters, so it reads again too.
        self.register.invalidate()
        self.say(u'Setup saved for this machine.')

    def _say_theme(self):
        if self.theme_mode == 'follow':
            label = u'Auto ({0})'.format(self.theme_name)
            tip = (u'Following Revit. Click to pin this window to dark '
                   u'whatever Revit does.')
        elif self.theme_mode == 'dark':
            label = u'Dark'
            tip = u'Pinned to dark. Click for light.'
        else:
            label = u'Light'
            tip = u'Pinned to light. Click to follow Revit again.'
        ps_ui.set_content(self.c('ThemeChip'), label)
        try:
            self.c('ThemeChip').ToolTip = tip
        except Exception:
            pass

    # ==================================================================
    # the pre-selection
    # ==================================================================

    def _apply_preselection(self):
        """Isolate to whatever was selected in Revit before the tool opened."""
        picked = ps_model.preselected_rows(self.uidoc, self.rows)
        if not picked:
            return
        self._preselected_keys = set([row.key for row in picked])
        self.isolated_keys = set(self._preselected_keys)
        ps_ui.set_visible(self.c('ShowAllCheck'), True)
        try:
            self.c('ShowAllCheck').IsChecked = False
        except Exception:
            pass
        self._say_isolation()

    def _show_all_changed(self, sender, args):
        """Show everything, or go back to the Revit selection.

        What is ticked is never touched by this. The point of arriving with
        your selection ticked is that you can widen the view to add one more
        sheet without losing the twelve you came in with.
        """
        if self._flag_of('ShowAllCheck'):
            self.isolated_keys = None
        else:
            self.isolated_keys = set(self._preselected_keys)
        self._apply_filters()
        self._refresh_counts()
        self._say_isolation()

    def _say_isolation(self):
        note = self.c('IsolationNote')
        count = len(self._preselected_keys)
        if not count:
            ps_ui.set_visible(note, False)
            return
        if self.isolated_keys is None:
            ps_ui.set_text(note, u'{0} sheet{1} came from your Revit '
                                 u'selection and stay ticked'.format(
                                     count, u'' if count == 1 else u's'))
        else:
            ps_ui.set_text(note, u'Showing your {0} selected sheet{1}'.format(
                count, u'' if count == 1 else u's'))
        ps_ui.set_visible(note, True)

    def clear_isolation(self, sender=None, args=None):
        try:
            self.c('ShowAllCheck').IsChecked = True
        except Exception:
            self.isolated_keys = None
            self._apply_filters()
            self._refresh_counts()

    # ==================================================================
    # profiles
    # ==================================================================

    def _load_last_profile(self):
        self._ready = False
        name = u''
        if self.settings.flag('remember_last_profile', True):
            name = self.settings.text('last_profile')
        available = ps_config.profile_names(self.doc)
        if name and name in available:
            self.profile = ps_config.load_profile(self.doc, name)
            self._fill_profiles(selected=name)
        else:
            self.profile = ps_config.defaults()
            default_printer = self.settings.text('default_printer')
            # Nothing but an explicit choice goes in here.
            #
            # 1.9.1 filled this with a known driver whenever it found
            # one, on the grounds that somebody with ProSheets installed
            # wants ProSheets' PDF settings. That is right for a machine
            # already set up for it and wrong for a fresh one, because a
            # driver writes nothing at all until "Driver saves to" is
            # filled in - so a new user's first run failed on every
            # sheet with "no file appeared" and no hint as to why. The
            # driver is offered in the setup window instead, with the
            # folder it needs on the same screen.
            if default_printer:
                self.profile['pdf.printer'] = default_printer
        self._apply_profile(self.profile)
        # The sort and grouping set by hand last time win over the
        # template's; the template's still apply when it is picked.
        if self._restore_sort():
            self._build_columns()
        self._ready = True

    def _profile_changed(self, sender, args):
        name = ps_ui.combo_text(self.c('ProfileCombo'), NO_TEMPLATE)
        if not name:
            return
        self.profile = ps_config.load_profile(self.doc, name)
        self._apply_profile(self.profile)
        self.settings.set('last_profile', name)
        self.settings.save()
        self.remember_sort()
        self._refresh_all()
        self.say(u'Template "{0}" loaded.'.format(name))

    def _apply_profile(self, profile):
        """Push a profile dictionary onto the controls."""
        def flag(key, control_name, default=False):
            control = self.c(control_name)
            if control is None:
                return
            try:
                control.IsChecked = ps_config.get_bool(profile, key, default)
            except Exception:
                pass

        def text(key, control_name, default=u''):
            control = self.c(control_name)
            if control is None:
                return
            try:
                control.Text = ps_config.get_text(profile, key, default)
            except Exception:
                pass

        # Mode first: it decides which column set the saved order below is
        # even allowed to be. A template saved in Views mode holding
        # "name, fname, p:Detail Level" is nonsense against the sheet
        # columns and would leave the grid with no Sheet Number.
        wanted_mode = ps_config.get_text(profile, 'mode', 'sheets')
        if wanted_mode not in ('sheets', 'views'):
            wanted_mode = 'sheets'
        if wanted_mode != self._mode_name():
            try:
                self.c('ViewsRadio').IsChecked = (wanted_mode == 'views')
                self.c('SheetsRadio').IsChecked = (wanted_mode != 'views')
            except Exception:
                pass
            # Flipping the radio raises _mode_changed, which does the
            # re-read and the column swap itself - but only once the
            # window is up. At startup it returns early, so the read has
            # to happen here or the grid shows sheets under view
            # headings.
            if not getattr(self, '_ready', False):
                self._read_model()

        formats = set(ps_config.get_list(profile, 'formats', ['pdf']))
        for fmt, tick, _tile, _group, _panel, _label, live in FORMATS:
            box = self.c(tick)
            if box is None:
                continue
            try:
                box.IsChecked = bool(live and fmt in formats)
            except Exception:
                continue

        placement = ps_config.get_text(profile, 'pdf.placement', 'center')
        try:
            self.c('PlaceCenterRadio').IsChecked = (placement != 'offset')
            self.c('PlaceOffsetRadio').IsChecked = (placement == 'offset')
        except Exception:
            pass
        text('pdf.offset_x', 'OffsetXBox', '0.00')
        text('pdf.offset_y', 'OffsetYBox', '0.00')

        zoom_mode = ps_config.get_text(profile, 'pdf.zoom_mode', 'zoom')
        try:
            self.c('FitPageRadio').IsChecked = (zoom_mode == 'fit')
            self.c('ZoomRadio').IsChecked = (zoom_mode != 'fit')
        except Exception:
            pass
        text('pdf.zoom', 'ZoomBox', '100')

        hidden = ps_config.get_text(profile, 'pdf.hidden_line', 'vector')
        try:
            self.c('VectorRadio').IsChecked = (hidden != 'raster')
            self.c('RasterRadio').IsChecked = (hidden == 'raster')
        except Exception:
            pass

        self._set_combo_index('MarginCombo', MARGIN_CHOICES,
                              ps_config.get_text(profile, 'pdf.margin', 'nomargin'))
        self._set_combo_index('RasterQualityCombo', RASTER_CHOICES,
                              ps_config.get_text(profile, 'pdf.raster_quality', 'high'))
        self._set_combo_index('ColorsCombo', COLOUR_CHOICES,
                              ps_config.get_text(profile, 'pdf.colors', 'color'))
        self._set_combo_index('DwgVersionCombo', DWG_VERSIONS,
                              ps_config.get_text(profile, 'dwg.version', 'default'))

        flag('pdf.view_links_blue', 'ViewLinksBlueCheck', True)
        flag('pdf.hide_ref_planes', 'HideRefPlanesCheck', True)
        flag('pdf.hide_unreferenced_tags', 'HideViewTagsCheck', True)
        flag('pdf.hide_scope_boxes', 'HideScopeBoxesCheck', True)
        flag('pdf.hide_crop_boundaries', 'HideCropCheck', True)
        flag('pdf.replace_halftone', 'HalftoneCheck', False)
        flag('pdf.mask_coincident', 'MaskCoincidentCheck', False)
        flag('pdf.keep_paper_size', 'KeepPaperSizeCheck', True)
        flag('dwg.shared_coords', 'DwgSharedCoordsCheck', True)
        flag('dwg.external_refs', 'DwgXrefCheck', False)
        flag('out.folder_per_format', 'FolderPerFormatCheck', True)
        flag('out.overwrite', 'OverwriteCheck', True)
        flag('filter.active_only', 'OnSheetListCheck', False)
        flag('run.suppress_dialogs', 'SuppressCheck',
             self.settings.flag('suppress_dialogs'))
        flag('run.open_folder', 'OpenFolderCheck',
             self.settings.flag('open_folder_after_export', True))
        flag('run.debug', 'DebugCheck', self.settings.flag('debug'))

        combine = ps_config.get_bool(profile, 'pdf.combine', False)
        try:
            self.c('CombineRadio').IsChecked = combine
            self.c('SeparateFilesRadio').IsChecked = not combine
        except Exception:
            pass

        asked = ps_config.get_text(profile, 'pdf.printer', u'')
        printer, refused, why = self.usable_printer(
            asked,
            ps_config.get_text(profile, 'pdf.staging', u'')
            or self._recall_staging(asked),
            self.printer_list, self.native_pdf,
            self.settings.flag('prefer_native_pdf', True))
        ps_ui.fill_combo(self.c('PrinterCombo'), self.printer_list,
                         selected=printer or REVIT_PDF)
        if refused:
            self._printer_refused = (refused, why)

        setup = ps_config.get_text(profile, 'dwg.setup', u'')
        combo = self.c('DwgSetupCombo')
        if combo is not None:
            ps_ui.fill_combo(combo,
                             [DEFAULT_DWG_SETUP] + ps_export.list_dwg_setups(self.doc),
                             selected=setup or DEFAULT_DWG_SETUP)

        self._write_fields(profile, NWC_FIELDS)
        self._write_fields(profile, IFC_FIELDS)
        wanted_phase = ps_config.get_text(profile, 'ifc.phase', u'')
        ps_ui.fill_combo(self.c('IfcPhaseCombo'), self.ifc_phase_names(),
                         selected=wanted_phase or IFC_DEFAULT_PHASE)
        ps_ui.fill_combo(self.c('IfcSetupCombo'),
                         [IFC_IN_SESSION] + ps_config.ifc_setup_names(),
                         selected=IFC_IN_SESSION)
        self._refresh_dependants()

        text('pdf.staging', 'StagingBox')
        text('out.root', 'RootFolderBox')
        text('out.tokens', 'TokenBox')
        if not self._text_of('RootFolderBox'):
            try:
                self.c('RootFolderBox').Text = self.settings.text(
                    'default_root', u'')
            except Exception:
                pass

        self.column_orders = {}
        saved = [name for name in ps_config.get_list(profile, 'cols', [])
                 if name]
        # Saved as the full ordered list from 1.6.0 on. An older template
        # holds only the parameter names, so those go on the end where
        # they used to be rather than being thrown away.
        if saved and all(name in ('sel', 'num', 'name', 'rev', 'size',
                                  'fname') or name.startswith('p:')
                         for name in saved):
            self.column_order = self._sane_order(saved)
        else:
            self.column_order = self.starting_columns(
                self._mode_name(), self.default_extras(),
                self.browser_names) \
                + [u'p:{0}'.format(name) for name in saved]
        self.sort_stack = []
        for piece in ps_config.get_list(profile, 'sort.stack', []):
            if not piece:
                continue
            col_id, _, direction = piece.partition(u'|')
            if col_id:
                self.sort_stack.append((col_id, direction == 'desc'))
        self._apply_default_sort()
        self.grouped = ps_config.get_bool(profile, 'sort.grouped', True)
        for key, prop in (('win.width', 'Width'), ('win.height', 'Height')):
            value = ps_config.get_int(profile, key, 0)
            if value <= 0:
                continue
            try:
                least = (self.window.MinWidth if prop == 'Width'
                         else self.window.MinHeight)
                if value >= least:
                    setattr(self.window, prop, float(value))
            except Exception:
                continue
        # A template's widths win when it has any; otherwise whatever this
        # machine was left at last time.
        self._saved_widths = ps_config.get_list(profile, 'colwidths', []) \
            or ps_config.get_list(self.settings.store, 'column_widths', [])
        try:
            self.c('GroupCheck').IsChecked = self.grouped
        except Exception:
            pass
        self._build_columns()
        self._template_sort = u''
        if self.sort_stack:
            first = self.sort_stack[0][0]
            series = self.series_column()
            if series and first != series:
                self._template_sort = self._heading_of(first)
        self.rules_by_mode = ps_naming.rules_by_mode(profile)
        self._adopt_rules(self._mode_name())
        self.combine_order = ps_config.get_list(profile, 'pdf.order', [])

        self._placement_changed(None, None)
        self._combine_changed(None, None)
        self._xref_changed(None, None)
        self._printer_changed(None, None)
        refused = getattr(self, '_printer_refused', None)
        if refused:
            self._printer_refused = None
            name, why = refused
            if why == 'prefer-native':
                self.say(u'This template asks for "{0}", but this machine '
                         u'is set to use {1} - which needs no driver, no '
                         u'folder and no setup. Untick that in Set up if '
                         u'you want the driver.'.format(name, REVIT_PDF))
            elif why == 'not-installed':
                self.say(u'This template asks for "{0}", which is not '
                         u'installed here, so it would write nothing - '
                         u'switched to {1}.'.format(name, REVIT_PDF))
            else:
                self.say(u'This template asks for "{0}", which has no '
                         u'"Driver saves to" folder set on this machine, so '
                         u'it would write nothing - switched to {1}. Set up '
                         u'puts it back.'.format(name, REVIT_PDF))
        self._say_theme()

    def _set_combo_index(self, control_name, choices, stored):
        combo = self.c(control_name)
        if combo is None:
            return
        try:
            combo.SelectedIndex = _pick(choices, stored)
        except Exception:
            pass

    def _combo_value(self, control_name, choices, default):
        combo = self.c(control_name)
        try:
            index = combo.SelectedIndex
            if 0 <= index < len(choices):
                return choices[index][1]
        except Exception:
            pass
        return default

    def _read_field(self, profile, key, control_name, kind, default):
        """One field, control to profile. See NWC_FIELDS for the table."""
        if kind == 'flag':
            control = self.c(control_name)
            try:
                profile[key] = '1' if control.IsChecked else '0'
            except Exception:
                profile[key] = '1' if default else '0'
        elif kind == 'text':
            profile[key] = self._text_of(control_name, default)
        else:
            profile[key] = self._combo_value(control_name, kind, default)

    def _write_field(self, profile, key, control_name, kind, default):
        """One field, profile to control."""
        control = self.c(control_name)
        if control is None:
            return
        if kind == 'flag':
            try:
                control.IsChecked = ps_config.get_bool(profile, key, default)
            except Exception:
                pass
        elif kind == 'text':
            try:
                control.Text = ps_config.get_text(profile, key, default)
            except Exception:
                pass
        else:
            self._set_combo_index(control_name, kind,
                                  ps_config.get_text(profile, key, default))

    def _read_fields(self, profile, fields):
        for key, control_name, kind, default in fields:
            self._read_field(profile, key, control_name, kind, default)

    def _write_fields(self, profile, fields):
        for key, control_name, kind, default in fields:
            self._write_field(profile, key, control_name, kind, default)

    def _collect_profile(self):
        """Read the controls back into a profile dictionary."""
        profile = ps_config.defaults()

        def flag(key, control_name, default=False):
            control = self.c(control_name)
            try:
                profile[key] = '1' if control.IsChecked else '0'
            except Exception:
                profile[key] = '1' if default else '0'

        def text(key, control_name, default=u''):
            control = self.c(control_name)
            try:
                profile[key] = u'{0}'.format(control.Text or default)
            except Exception:
                profile[key] = default

        profile['mode'] = 'views' if self._is_views_mode() else 'sheets'
        profile['formats'] = ps_config.put_list(self.chosen_formats())

        try:
            profile['pdf.placement'] = ('offset'
                                        if self.c('PlaceOffsetRadio').IsChecked
                                        else 'center')
        except Exception:
            profile['pdf.placement'] = 'center'
        profile['pdf.margin'] = self._combo_value('MarginCombo',
                                                  MARGIN_CHOICES, 'nomargin')
        text('pdf.offset_x', 'OffsetXBox', '0.0')
        text('pdf.offset_y', 'OffsetYBox', '0.0')
        try:
            profile['pdf.zoom_mode'] = ('fit' if self.c('FitPageRadio').IsChecked
                                        else 'zoom')
        except Exception:
            profile['pdf.zoom_mode'] = 'zoom'
        text('pdf.zoom', 'ZoomBox', '100')
        try:
            profile['pdf.hidden_line'] = ('raster'
                                          if self.c('RasterRadio').IsChecked
                                          else 'vector')
        except Exception:
            profile['pdf.hidden_line'] = 'vector'
        profile['pdf.raster_quality'] = self._combo_value(
            'RasterQualityCombo', RASTER_CHOICES, 'high')
        profile['pdf.colors'] = self._combo_value(
            'ColorsCombo', COLOUR_CHOICES, 'color')

        flag('pdf.view_links_blue', 'ViewLinksBlueCheck', True)
        flag('pdf.hide_ref_planes', 'HideRefPlanesCheck', True)
        flag('pdf.hide_unreferenced_tags', 'HideViewTagsCheck', True)
        flag('pdf.hide_scope_boxes', 'HideScopeBoxesCheck', True)
        flag('pdf.hide_crop_boundaries', 'HideCropCheck', True)
        flag('pdf.replace_halftone', 'HalftoneCheck', False)
        flag('pdf.mask_coincident', 'MaskCoincidentCheck', False)
        flag('pdf.keep_paper_size', 'KeepPaperSizeCheck', True)
        try:
            profile['pdf.combine'] = '1' if self.c('CombineRadio').IsChecked else '0'
        except Exception:
            profile['pdf.combine'] = '0'

        printer = ps_ui.combo_text(self.c('PrinterCombo'))
        profile['pdf.printer'] = u'' if printer == REVIT_PDF else printer

        setup = ps_ui.combo_text(self.c('DwgSetupCombo'))
        profile['dwg.setup'] = u'' if setup == DEFAULT_DWG_SETUP else setup
        profile['dwg.version'] = self._combo_value('DwgVersionCombo',
                                                   DWG_VERSIONS, 'default')
        flag('dwg.shared_coords', 'DwgSharedCoordsCheck', True)
        flag('dwg.external_refs', 'DwgXrefCheck', False)

        self._read_fields(profile, NWC_FIELDS)
        self._read_fields(profile, IFC_FIELDS)
        phase = ps_ui.combo_text(self.c('IfcPhaseCombo'), IFC_DEFAULT_PHASE)
        profile['ifc.phase'] = u'' if phase == IFC_DEFAULT_PHASE else phase
        profile['ifc.phase_id'] = self.ifc_phases.get(phase, u'')

        text('pdf.staging', 'StagingBox')
        text('out.root', 'RootFolderBox')
        text('out.tokens', 'TokenBox')
        flag('out.folder_per_format', 'FolderPerFormatCheck', True)
        flag('out.overwrite', 'OverwriteCheck', True)
        flag('filter.active_only', 'OnSheetListCheck', False)
        flag('run.suppress_dialogs', 'SuppressCheck', False)
        flag('run.open_folder', 'OpenFolderCheck', True)
        flag('run.debug', 'DebugCheck', False)

        set_name = ps_ui.combo_text(self.c('SheetSetCombo'), NO_SET)
        profile['filter.sheet_set'] = u'' if set_name == NO_SET else set_name

        profile['selected'] = ps_config.put_list(sorted(self._ticked_keys()))
        profile['pdf.order'] = ps_config.put_list(self.combine_order)
        profile['cols'] = ps_config.put_list(self.column_order)
        profile['sort.stack'] = ps_config.put_list(
            [u'{0}|{1}'.format(col_id, 'desc' if down else 'asc')
             for col_id, down in self.sort_stack])
        profile['sort.grouped'] = '1' if self.grouped else '0'
        profile['colwidths'] = ps_config.put_list(self.column_widths())
        try:
            width, height = self.chrome.true_size()
            profile['win.width'] = u'{0}'.format(int(width))
            profile['win.height'] = u'{0}'.format(int(height))
        except Exception:
            pass
        self._park_rules(self._mode_name())
        ps_naming.store_rules_by_mode(self.rules_by_mode, profile)
        return profile

    def new_profile(self, sender=None, args=None):
        name = ps_ui.ask_text(u'Save a template',
                              u'What should this template be called?',
                              u'Standard issue', self.theme_name, self.window)
        if not name:
            return
        name = ps_config.safe_name(name, 'template')
        profile = self._collect_profile()
        if ps_config.save_profile(self.doc, name, profile):
            self.profile = profile
            self._fill_profiles(selected=name)
            self.settings.set('last_profile', name)
            self.settings.save()
            self.say(u'Template "{0}" saved against this project.'.format(name))
        else:
            self.say(u'That template could not be written. Check %APPDATA%.')

    def save_profile(self, sender=None, args=None):
        name = ps_ui.combo_text(self.c('ProfileCombo'), NO_TEMPLATE)
        if not name:
            self.new_profile()
            return
        profile = self._collect_profile()
        if ps_config.save_profile(self.doc, name, profile):
            self.profile = profile
            self.say(u'Template "{0}" updated.'.format(name))
        else:
            self.say(u'That template could not be written. Check %APPDATA%.')

    def delete_profile(self, sender=None, args=None):
        name = ps_ui.combo_text(self.c('ProfileCombo'), NO_TEMPLATE)
        if not name:
            return
        answer = ps_ui.Prompt(
            title=u'Delete a template',
            headline=u'Delete "{0}"?'.format(name),
            message=u'This only removes the saved settings. Nothing that has '
                    u'already been exported is touched.',
            primary=u'Delete', secondary=u'Keep it',
            theme_name=self.theme_name, owner=self.window).show()
        if answer != 'primary':
            return
        ps_config.delete_profile(self.doc, name)
        self._fill_profiles()
        self.say(u'Template "{0}" deleted.'.format(name))

    # ==================================================================
    # templates as files
    # ==================================================================

    def export_templates(self, sender=None, args=None):
        """Write every template for this project into one file."""
        names = ps_config.profile_names(self.doc)
        current = ps_ui.combo_text(self.c('ProfileCombo'), NO_TEMPLATE)
        bundle = {}
        for name in names:
            bundle[name] = ps_config.load_profile(self.doc, name)
        # What is on screen but never saved would be silently lost, so it
        # goes in under the loaded name, or under a plain one if there is
        # no loaded template at all.
        live = self._collect_profile()
        bundle[current or u'Current settings'] = live

        if not bundle:
            self.say(u'There is nothing to save yet.')
            return

        suggested = u'{0} templates{1}'.format(
            ps_config.project_key(self.doc), ps_config.BUNDLE_EXTENSION)
        path = ps_ui.pick_file(True, u'Save templates to a file',
                               ps_config.BUNDLE_EXTENSION, suggested)
        if not path:
            return
        if ps_config.write_bundle(path, bundle):
            self.say(u'{0} template{1} written to {2}'.format(
                len(bundle), u'' if len(bundle) == 1 else u's', path))
        else:
            self.say(u'That file could not be written.')

    def import_templates(self, sender=None, args=None):
        """Load templates from a file, merging or replacing."""
        path = ps_ui.pick_file(False, u'Load templates from a file',
                               ps_config.BUNDLE_EXTENSION)
        if not path:
            return
        incoming = ps_config.read_bundle(path)
        if not incoming:
            ps_ui.Prompt(
                title=u'Load templates',
                headline=u'Nothing in that file looked like a template.',
                message=u'A bundle is plain text with a line reading '
                        u'@template=<name> before each one. {0}'.format(path),
                primary=u'Close', theme_name=self.theme_name,
                owner=self.window).show()
            return

        existing = ps_config.profile_names(self.doc)
        clashes = [name for name in incoming if name in existing]

        if existing:
            detail = [u'Coming in:']
            for name in sorted(incoming.keys(), key=lambda n: n.lower()):
                mark = u'  (name already used)' if name in existing else u''
                detail.append(u'   {0}{1}'.format(name, mark))
            detail.append(u'')
            detail.append(u'Already here:')
            for name in existing:
                detail.append(u'   {0}'.format(name))

            answer = ps_ui.Prompt(
                title=u'Load templates',
                headline=u'{0} template{1} in that file.'.format(
                    len(incoming), u'' if len(incoming) == 1 else u's'),
                message=(u'Merge keeps what you already have and brings '
                         u'these in alongside; {0} Replace all removes the '
                         u'{1} template{2} already saved against this '
                         u'project first.'.format(
                             u'a repeated name gains (1), (2) and so on.'
                             if clashes else u'',
                             len(existing),
                             u'' if len(existing) == 1 else u's')),
                detail=u'\n'.join(detail),
                primary=u'Merge', secondary=u'Replace all',
                theme_name=self.theme_name, owner=self.window).show()
            if answer is None:
                return
            replacing = (answer == 'secondary')
        else:
            replacing = False

        if replacing:
            for name in existing:
                ps_config.delete_profile(self.doc, name)
            existing = []

        taken = list(existing)
        written = 0
        renamed = []
        for name in sorted(incoming.keys(), key=lambda n: n.lower()):
            final = ps_config.unique_template_name(taken, name)
            if final != name:
                renamed.append((name, final))
            if ps_config.save_profile(self.doc, final, incoming[name]):
                taken.append(final)
                written += 1

        self._fill_profiles()
        message = u'{0} template{1} loaded.'.format(
            written, u'' if written == 1 else u's')
        if renamed:
            message += u' {0} renamed to avoid a clash: {1}.'.format(
                len(renamed),
                u', '.join([u'{0} -> {1}'.format(a, b)
                            for a, b in renamed[:4]]))
        self.say(message)

    # ==================================================================
    # naming
    # ==================================================================

    def open_name_dialog(self, sender=None, args=None):
        sample_row = self._first_ticked_row() or (self.rows[0] if self.rows else None)
        lookup = self.lookup_for(sample_row) if sample_row is not None else None
        label = u''
        if sample_row is not None:
            label = sample_row.number or sample_row.name
        mode = self._mode_name()
        dialog = ps_namewin.CustomNameWindow(
            self.catalogue, lookup, self.rules, self.theme_name,
            self.window, label, mode=mode)
        chosen = dialog.show()
        if chosen is None:
            return
        self.rules = chosen
        self._park_rules(mode)
        self._refresh_names()
        self._refresh_plan()
        self.say(u'File naming for {0} updated.'.format(
            u'views' if mode == 'views' else u'sheets'))

    def _first_ticked_row(self):
        for entry in self.table.Rows:
            if bool(entry['sel']):
                return self.rows_by_key.get(
                    self._as_key(u'{0}'.format(entry['key'])))
        return None

    def _refresh_names(self):
        """Write every row's file name into the table."""
        self._suspend_ticks = True
        try:
            for entry in self.table.Rows:
                row = self.rows_by_key.get(
                    self._as_key(u'{0}'.format(entry['key'])))
                if row is None:
                    continue
                name = ps_naming.build_name(self.rules, self.lookup_for(row),
                                            row.number or row.name or u'sheet')
                entry['fname'] = name
                row.custom_name = name
        finally:
            self._suspend_ticks = False

    # ==================================================================
    # the plan
    # ==================================================================

    def chosen_formats(self):
        """Every ticked format that can actually be written right now.

        A format whose tile is greyed - NWC with no 3D view ticked, say -
        is left out even if its box is still ticked from a template, so
        the plan and the file count never promise a file the run cannot
        produce.
        """
        found = []
        allowed = self._available_formats()
        for fmt, tick, _tile, _group, _panel, _label, live in FORMATS:
            if not live or fmt not in allowed:
                continue
            box = self.c(tick)
            try:
                if box is not None and box.IsChecked:
                    found.append(fmt)
            except Exception:
                continue
        return found

    def _available_formats(self):
        """Which formats the current selection allows.

        NWC and IFC are exported per view and Navisworks only understands
        a 3D one, so in Sheets mode neither is reachable and in Views mode
        they wait for a 3D view to be ticked.
        """
        allowed = set([fmt for fmt in live_formats()
                       if fmt not in VIEW_ONLY_FORMATS])
        if not self._is_views_mode():
            return allowed
        if self._has_ticked_3d():
            allowed.update(VIEW_ONLY_FORMATS)
        return allowed

    def _has_ticked_3d(self):
        for row in self.ticked_rows():
            if ps_model.is_three_d(row):
                return True
        return False

    def ticked_rows(self):
        """Every ticked row, in the order the Selection tab sorts them.

        Hidden rows included. Up to 1.19.2 this walked the table's
        DefaultView, which is filtered to the rows showing - so a sheet
        ticked inside a collapsed group, or ticked and then searched out of
        sight, counted as ticked on the status line and was silently left
        out of the export. With the Document Register ticking sheets the
        Selection tab may well be hiding, that stopped being an edge case.
        Ticked means printed; what is on screen has no say in it.
        """
        found = []
        try:
            entries = self.table.Select(u'', u'[ord] ASC')
        except Exception:
            entries = []
        for entry in entries:
            try:
                if not bool(entry['sel']):
                    continue
                key = u'{0}'.format(entry['key'])
            except Exception:
                continue
            if not key:
                continue                       # a group heading
            row = self.rows_by_key.get(self._as_key(key))
            if row is not None:
                found.append(row)
        return found

    def plan_jobs(self):
        """Every ticked row turned into a Job, with clashes already resolved.

        Two sheets whose chosen parameters happen to match would otherwise
        export one file and overwrite it with the other, and the count at
        the end would still say two. ``unique_names`` settles it, and the
        clash is reported rather than fixed silently.
        """
        formats = self.chosen_formats()
        rows = self.ticked_rows()
        if not rows or not formats:
            return [], {}

        root = self._text_of('RootFolderBox')
        tokens = self._text_of('TokenBox')
        per_format = self._flag_of('FolderPerFormatCheck', True)

        pairs = []
        for row in rows:
            lookup = self.lookup_for(row)
            # In Views mode row.number carries the view type, so the
            # fallback has to be the name; "ThreeD.pdf" is not a file
            # anybody asked for.
            fallback = ((row.name or row.number) if not row.is_sheet
                        else (row.number or row.name))
            name = ps_naming.build_name(self.rules, lookup,
                                        fallback or u'sheet')
            pairs.append((row.key, name))
        clashes = ps_naming.clashes(pairs)
        settled = dict(ps_naming.unique_names(pairs))

        jobs = []
        for row in rows:
            lookup = self.lookup_for(row)
            folders = {}
            for fmt in formats:
                folders[fmt] = ps_paths.full_folder(
                    root, tokens, lookup,
                    fmt.upper() if per_format else None)
            jobs.append(ps_export.Job(
                key=row.key,
                label=u'{0} {1}'.format(row.number, row.name).strip(),
                element_id=row.element_id,
                base_name=settled.get(row.key, row.number or u'sheet'),
                folders=folders,
                size_info=row.size_info,
                view=row.element))
        return jobs, clashes

    def register_folder(self, jobs, formats):
        """Where the register goes with a run: the issue folder.

        From 1.27.0 that is the folder before the sheet series level - the
        dated folder on the house template - because the register covers
        every series in the issue. With one series ticked, "the folder above
        PDF" was that series' own folder, which is where 1.26.0 put it.
        Without a series level in the tokens, the folder above the PDF and
        DWG folders, as before.

        Worked out from the plan rather than from what the run wrote, so the
        Create list can show it before anything is written and a run that
        failed half way still puts the register in the same place.
        """
        folders = []
        for job in jobs or ():
            for fmt in formats or ():
                folder = job.folders.get(fmt, u'')
                if folder:
                    folders.append(folder)
        if not folders:
            # Nothing ticked: the register on its own, in the issue folder
            # the tokens name without a sheet.
            return self.register_alone_folder()
        cut = ps_paths.issue_cut(self._text_of('RootFolderBox'),
                                 self._text_of('TokenBox'), folders,
                                 self.settings.text('param_series', u''))
        if cut:
            return cut
        found = ps_register.register_folder(
            folders, self._flag_of('FolderPerFormatCheck', True))
        return found or self._text_of('RootFolderBox')

    def register_alone_folder(self):
        """Where the register goes when it is the only thing written."""
        try:
            lookup = self.lookup_for(None)
        except Exception:
            lookup = lambda name: u''
        return ps_paths.project_folder(
            self._text_of('RootFolderBox'), self._text_of('TokenBox'),
            lookup, self.settings.text('param_series', u''))

    def register_alone(self, jobs):
        """Whether a run is the Document Register by itself: nothing
        ticked, and the register tab asking to be added to the export."""
        try:
            return (not jobs) and bool(self.register.add_to_export())
        except Exception:
            return False

    def issue_folder(self, jobs, formats):
        """Where "Open folder" goes after a run: the issue, not one series.

        The folder before the sheet series level of the folder tokens -
        the dated folder, on the house template - worked out from the
        folders the plan built. Without a series level, the folder above
        the PDF and DWG folders, as the register uses.
        """
        folders = [job.folders.get(fmt, u'') for job in jobs or ()
                   for fmt in formats or ()]
        found = ps_paths.issue_cut(self._text_of('RootFolderBox'),
                                   self._text_of('TokenBox'), folders,
                                   self.settings.text('param_series', u''))
        return found or self.register_folder(jobs, formats)

    def _file_count(self, jobs, formats):
        """How many files a run will actually write.

        Not jobs times formats: NWC and IFC only take the 3D views out of
        the ticked rows, and a combined PDF is one file however many
        sheets went into it. A count that overstates is worse than no
        count, because it is the number the progress bar divides by.
        """
        if not jobs or not formats:
            return 0
        solid = len([job for job in jobs
                     if ps_model.is_three_d(self.rows_by_key.get(job.key))])
        total = 0
        for fmt in formats:
            if fmt in VIEW_ONLY_FORMATS:
                total += solid
            elif fmt == 'pdf' and self._flag_of('CombineRadio'):
                total += 1
            else:
                total += len(jobs)
        return total

    def _suffix_for(self, fmt):
        """The extension a format will actually land under.

        IFC is the reason this is not just a dot and the format id: the
        file type dropdown decides between .ifc, .ifcXML and .ifcZIP, and
        a preview promising .ifc for a zipped export would be wrong.
        """
        if fmt == 'ifc':
            return ps_export.ifc_extension(self._collect_ifc())
        return u'.{0}'.format(fmt)

    def _collect_ifc(self):
        """Just the IFC keys, for anything that needs them before a run."""
        profile = {}
        for key, control_name, kind, default in IFC_FIELDS:
            self._read_field(profile, key, control_name, kind, default)
        return profile

    def _text_of(self, control_name, default=u''):
        control = self.c(control_name)
        try:
            return u'{0}'.format(control.Text or default)
        except Exception:
            return default

    def _flag_of(self, control_name, default=False):
        control = self.c(control_name)
        try:
            return bool(control.IsChecked)
        except Exception:
            return default

    def _refresh_plan(self):
        # Ticking a 3D view is what makes NWC and IFC reachable, so the
        # tiles are re-judged here rather than on a mode change alone -
        # this is the one method every path that changes the selection
        # already ends in.
        self._refresh_format_tiles()
        self._refresh_create_columns()
        jobs, clashes = self.plan_jobs()
        formats = self.chosen_formats()

        self.create_table.Rows.Clear()
        for job in jobs:
            row = self.rows_by_key.get(job.key)
            entry = self.create_table.NewRow()
            entry['num'] = row.number if row is not None else job.label
            entry['name'] = row.name if row is not None else u''
            entry['size'] = row.size if row is not None else u''
            entry['fmt'] = u', '.join([format_label(f) for f in formats])
            entry['fname'] = job.base_name
            entry['folder'] = job.folders.get(formats[0], u'') if formats else u''
            entry['key'] = u'{0}'.format(job.key)
            entry['state'] = u''
            self.create_table.Rows.Add(entry)

        # The Document Register, when the register tab says to add it: one
        # more file the run writes, listed with the rest so it can be seen
        # going in - and turning green or red like them, because its
        # outcome carries the same "register" key as this row.
        alone = self.register_alone(jobs)
        with_register = alone or (bool(jobs) and
                                  self.register.add_to_export())
        if with_register:
            entry = self.create_table.NewRow()
            entry['num'] = u''
            entry['name'] = u'Document Register'
            entry['size'] = u''
            entry['fmt'] = u'XLSX'
            entry['fname'] = os.path.splitext(self.register.file_name())[0]
            entry['folder'] = self.register_folder(jobs, formats)
            entry['key'] = u'register'
            entry['state'] = u''
            self.create_table.Rows.Add(entry)

        count = len(jobs)
        file_count = self._file_count(jobs, formats)
        word = u'view' if self._is_views_mode() else u'sheet'
        ps_ui.set_text(self.c('CreateSummary'),
                       u'{0} {1}{2} ticked, {3} file{4} to write{5}.'.format(
                           count, word, u'' if count == 1 else u's',
                           file_count, u'' if file_count == 1 else u's',
                           u', plus the Document Register' if with_register
                           else u'')
                       if count else
                       (u'No sheets ticked - Export writes the Document '
                        u'Register on its own.' if alone
                        else u'Nothing ticked yet.'))

        if clashes:
            ps_ui.set_text(self.c('ClashWarning'),
                           u'{0} name{1} repeated - "(2)" was added so nothing '
                           u'is overwritten.'.format(
                               len(clashes), u'' if len(clashes) == 1 else u's'))
        else:
            ps_ui.set_text(self.c('ClashWarning'), u'')

        preview = self.c('PathPreview')
        if jobs and formats:
            first = jobs[0]
            folder = first.folders.get(formats[0], u'')
            ps_ui.set_text(preview,
                           os.path.join(folder, first.base_name
                                        + self._suffix_for(formats[0])))
        elif not self._text_of('RootFolderBox'):
            ps_ui.set_text(preview,
                           u'Choose a root folder to see where the first '
                           u'sheet lands.')
        elif alone:
            ps_ui.set_text(preview, os.path.join(
                self.register_folder([], formats), self.register.file_name()))
        else:
            ps_ui.set_text(preview, u'Nothing ticked yet.')

        self._say_export_ready(jobs, formats)

    def _say_export_ready(self, jobs, formats):
        button = self.c('ExportButton')
        ready = ((bool(jobs) and bool(formats)) or self.register_alone(jobs)) \
            and bool(self._text_of('RootFolderBox'))
        if button is not None:
            try:
                button.IsEnabled = ready and not self.exporting
            except Exception:
                pass

    def _say_formats(self):
        formats = self.chosen_formats()
        if not formats:
            self.say(u'No format ticked, so there is nothing to write.')
        else:
            self.say(u'Exporting as {0}.'.format(
                u' and '.join([format_label(f) for f in formats])))

    # ==================================================================
    # panels, tabs and counts
    # ==================================================================

    def show_panel(self, which):
        for fmt, _tick, _tile, _group, panel, _label, _live in FORMATS:
            if not panel:
                continue
            ps_ui.set_visible(self.c(panel), fmt == which)

    def _refresh_create_columns(self):
        """The Create list follows the mode the same way the first tab does.

        A view has no sheet number and no paper size, so those two
        headings would be a column of view types under the word "Sheet"
        and a column of nothing under "Size".
        """
        grid = self.c('CreateGrid')
        views = self._is_views_mode()
        try:
            columns = list(grid.Columns)
        except Exception:
            return
        if len(columns) < 3:
            return
        try:
            columns[0].Header = u'View type' if views else u'Sheet'
            columns[2].Visibility = (Visibility.Collapsed if views
                                     else Visibility.Visible)
        except Exception:
            pass

    def _make_tile_click(self, fmt):
        def handler(sender, args):
            self.show_panel(fmt)
        return handler

    def _make_dependants(self, box_name, targets):
        def handler(sender, args):
            self._apply_dependants(box_name, targets)
        return handler

    def _apply_dependants(self, box_name, targets):
        on = self._flag_of(box_name, False)
        for name in targets:
            control = self.c(name)
            if control is None:
                continue
            try:
                control.IsEnabled = on
            except Exception:
                continue

    def _refresh_dependants(self):
        self._apply_dependants('IfcUserPsetsCheck',
                               ('IfcUserPsetsBox', 'IfcUserPsetsBrowse',
                                'IfcTypePropsCheck'))
        self._apply_dependants('IfcParamMapCheck',
                               ('IfcParamMapBox', 'IfcParamMapBrowse'))
        self._apply_dependants('IfcSchedulePsetsCheck',
                               ('IfcSpecificSchedulesCheck',))
        self._apply_dependants('Ifc2dRoomBoundaryCheck',
                               ('IfcSiteElevationCheck',))

    def _refresh_format_tiles(self):
        """Grey the tiles the current selection cannot reach, and say why.

        The tick is left alone rather than cleared: somebody who ticks
        NWC, then switches to Sheets to check something, should find NWC
        still ticked when they switch back.
        """
        allowed = self._available_formats()
        for fmt, tick, tile, group, _panel, _label, live in FORMATS:
            usable = bool(live and fmt in allowed)
            for name, dim in ((tick, False), (tile, False), (group, True)):
                control = self.c(name)
                if control is None:
                    continue
                try:
                    control.IsEnabled = usable
                    if dim:
                        control.Opacity = 1.0 if usable else 0.45
                except Exception:
                    continue

        blocked = [format_label(fmt) for fmt in VIEW_ONLY_FORMATS
                   if fmt not in allowed]
        if not blocked:
            message = u''
        elif not self._is_views_mode():
            message = (u'{0} export one 3D view at a time, so they wait for '
                       u'Views above rather than Sheets.'
                       .format(u' and '.join(blocked)))
        else:
            message = (u'Tick a 3D view to turn {0} on. Navisworks has no '
                       u'idea what a plan is, and an IFC of one would hold '
                       u'nothing.'.format(u' and '.join(blocked)))
        reserved = [row[5] for row in FORMATS if not row[6]]
        if reserved:
            extra = u'{0} {1} reserved for a later version.'.format(
                u' and '.join(reserved),
                u'is' if len(reserved) == 1 else u'are')
            message = (message + u'  ' + extra).strip() if message else extra
        ps_ui.set_text(self.c('FormatNote'), message)

        for name, fmt in (('NwcAvailableNote', 'nwc'),
                          ('IfcAvailableNote', 'ifc')):
            ps_ui.set_text(
                self.c(name),
                u'' if fmt in allowed
                else u'Greyed out until a 3D view is ticked on the '
                     u'Selection tab.')

    def _tab_index(self):
        tabs = self.c('MainTabs')
        try:
            return tabs.SelectedIndex
        except Exception:
            return 0

    def _set_tab(self, index):
        tabs = self.c('MainTabs')
        try:
            tabs.SelectedIndex = max(self.TAB_SELECTION,
                                     min(self.TAB_CREATE, index))
        except Exception:
            pass

    def go_back(self, sender=None, args=None):
        self._set_tab(self._tab_index() - 1)

    def go_next(self, sender=None, args=None):
        self._set_tab(self._tab_index() + 1)

    def _say_step(self):
        index = self._tab_index()
        back = self.c('BackButton')
        nxt = self.c('NextButton')
        export = self.c('ExportButton')
        try:
            back.IsEnabled = index > self.TAB_SELECTION
        except Exception:
            pass
        ps_ui.set_visible(nxt, index < self.TAB_CREATE)
        ps_ui.set_visible(export, index == self.TAB_CREATE)
        # Express Export lives on Selection: tick, press, done.
        ps_ui.set_visible(self.c('ExpressExportButton'),
                          index == self.TAB_SELECTION)

    def _refresh_counts(self):
        shown = 0
        ticked = 0
        out_of_sight = 0
        for entry in self.table.Rows:
            if not u'{0}'.format(entry['key']):
                continue
            if u'{0}'.format(entry['vis']) == '1':
                shown += 1
            if bool(entry['sel']):
                ticked += 1
                if u'{0}'.format(entry['show']) != '1':
                    out_of_sight += 1
        total = len(self.rows)
        word = u'view' if self._is_views_mode() else u'sheet'
        text = u'{0} of {1} {2}{3} showing, {4} ticked.'.format(
            shown, total, word, u'' if total == 1 else u's', ticked)
        if out_of_sight:
            # Ticked is printed, whatever the filter is hiding - so say
            # so, or a tick made on the Document Register tab looks like
            # it went nowhere.
            text = u'{0} {1} of them {2} out of sight and will still be ' \
                   u'exported.'.format(text, out_of_sight,
                                       u'is' if out_of_sight == 1 else u'are')
        self.say(text)
        if self.header_tick is not None:
            try:
                self.header_tick.IsChecked = (shown > 0 and ticked >= shown)
            except Exception:
                pass

    def _say_template_sort(self):
        """Say when a template's own sort is what is on screen.

        Otherwise the list opens in an order nobody asked for this
        week and there is nothing to explain it.
        """
        name = getattr(self, '_template_sort', u'')
        if not name:
            return False
        self.say(u'This template was saved sorted by {0}, so that is what '
                 u'it opened in. Sort by {1} and save the template again to '
                 u'make that the one it remembers.'.format(
                     name, self._heading_of(self.series_column() or u'')))
        return True

    def _refresh_all(self):
        self._fill_table()
        self._fill_parameter_values()
        self._refresh_names()
        self._apply_order()
        self._apply_grouping()
        self._apply_filters()
        self._paint_sort_headers()
        self._refresh_counts()
        self._refresh_dependants()
        self._refresh_plan()
        if not self._say_template_sort():
            self._say_step()
        self.show_panel('pdf')

    def say(self, text):
        ps_ui.set_text(self.c('StatusText'), text)

    # ==================================================================
    # small actions
    # ==================================================================

    # ------------------------------------------------ IFC odds and ends
    def browse_into(self, control_name, title, extension, label):
        chosen = ps_ui.pick_file(False, title, extension, label=label)
        if not chosen:
            return
        control = self.c(control_name)
        try:
            control.Text = chosen
        except Exception:
            pass

    def _ifc_setup_changed(self, sender=None, args=None):
        name = ps_ui.combo_text(self.c('IfcSetupCombo'), IFC_IN_SESSION)
        if not name or name == IFC_IN_SESSION:
            return
        values = ps_config.read_ifc_setup(ps_config.ifc_setup_path(name))
        if not values:
            self.say(u'"{0}" holds no IFC settings.'.format(name))
            return
        merged = dict(ps_config.defaults())
        merged.update(values)
        self._write_fields(merged, IFC_FIELDS)
        self._refresh_dependants()
        self._refresh_plan()
        self.say(u'IFC setup "{0}" loaded.'.format(name))

    def export_ifc_settings(self, sender=None, args=None):
        name = ps_ui.ask_text(u'Save the IFC setup',
                              u'What should this setup be called?',
                              u'House IFC 2x3', self.theme_name, self.window)
        if not name:
            return
        name = ps_config.safe_name(name, 'setup')
        path = ps_config.ifc_setup_path(name)
        if ps_config.write_ifc_setup(path, self._collect_ifc()):
            self._fill_ifc_setups(selected=name)
            self.say(u'IFC setup saved as "{0}".'.format(name))
        else:
            self.say(u'That IFC setup could not be written.')

    def import_ifc_settings(self, sender=None, args=None):
        chosen = ps_ui.pick_file(
            False, u'Load an IFC setup', ps_config.IFC_SETUP_EXTENSION,
            label=u'RevoBIM IFC setup')
        if not chosen:
            return
        values = ps_config.read_ifc_setup(chosen)
        if not values:
            ps_ui.Prompt(
                title=u'IFC setup',
                headline=u'That file holds no IFC settings.',
                message=u'A setup file is the plain text one this tool '
                        u'writes, with keys beginning "ifc.". Revit\'s own '
                        u'exported IFC setup is a different format and '
                        u'cannot be read here.',
                detail=chosen, primary=u'Close',
                theme_name=self.theme_name, owner=self.window).show()
            return
        merged = dict(ps_config.defaults())
        merged.update(values)
        self._write_fields(merged, IFC_FIELDS)
        self._refresh_dependants()

        # Keep a copy so it shows in the Current Setup list next time,
        # rather than only living wherever it was picked up from.
        name = ps_config.safe_name(
            os.path.splitext(os.path.basename(chosen))[0], 'setup')
        taken = ps_config.ifc_setup_names()
        name = ps_config.unique_template_name(taken, name)
        ps_config.write_ifc_setup(ps_config.ifc_setup_path(name), merged)
        self._fill_ifc_setups(selected=name)
        self._refresh_plan()
        self.say(u'IFC setup "{0}" loaded and kept.'.format(name))

    def explain_ifc_header(self, sender=None, args=None):
        self._explain(
            u'File Header Information',
            u'This comes from the model, not from here.',
            u'Revit keeps the IFC file header - the description, the '
            u'author, the organisation and the authorisation - against '
            u'the project itself, and the exporter reads it straight from '
            u'there. There is no API to override it per run, so a value '
            u'typed here would be a value quietly thrown away.',
            u'Set it once in Revit: File > Export > Options > IFC Options, '
            u'or the File Header Information button on Revit\'s own IFC '
            u'export dialog. Every export from this tool then carries it.')

    def explain_ifc_address(self, sender=None, args=None):
        self._explain(
            u'Project Address',
            u'This comes from the model, not from here.',
            u'The IFC postal address is Revit\'s own Project Address, '
            u'stored on the project information. The exporter reads it '
            u'from there and the API offers no per-run override.',
            u'Manage > Project Information > Project Address, or the '
            u'Project Address button on Revit\'s own IFC export dialog.')

    def explain_ifc_classification(self, sender=None, args=None):
        self._explain(
            u'Classification Settings',
            u'This comes from the model, not from here.',
            u'Classification name, source, edition, edition date and '
            u'location are stored against the project by Revit\'s IFC '
            u'exporter and reused on every export, including this one. '
            u'They are not among the named options the exporter accepts '
            u'per run.',
            u'Set them once on Revit\'s own IFC export dialog, under '
            u'Classification Settings. Uniclass or NRM entered there '
            u'comes through on the files this tool writes.')

    def _explain(self, title, headline, message, detail):
        ps_ui.Prompt(title=title, headline=headline, message=message,
                     detail=detail, primary=u'Close',
                     theme_name=self.theme_name, owner=self.window).show()

    def browse_root(self, sender=None, args=None):
        start = self._text_of('RootFolderBox')
        if not start:
            try:
                start = os.path.dirname(self.doc.PathName or u'')
            except Exception:
                start = u''
        chosen = ps_ui.browse_folder(start)
        if chosen:
            box = self.c('RootFolderBox')
            try:
                box.Text = chosen
            except Exception:
                pass

    def add_token(self, sender=None, args=None):
        """The folder picker. Deliberately not the file naming dialog.

        Naming a file and building a folder tree are different jobs: a name
        is one string with prefixes and separators, a path is a stack of
        levels. Borrowing the naming dialog for this offered four columns
        that mean nothing to a folder and no way to say "new level down".
        """
        sample_row = self._first_ticked_row() or (self.rows[0] if self.rows else None)
        lookup = self.lookup_for(sample_row) if sample_row is not None else None
        label = u''
        if sample_row is not None:
            label = sample_row.number or sample_row.name
        chosen = ps_tokenwin.pick(
            self.catalogue, lookup, self._text_of('TokenBox'),
            self.theme_name, self.window, label)
        if chosen is None:
            return
        try:
            self.c('TokenBox').Text = chosen
        except Exception:
            pass

    def make_default_printer(self, sender=None, args=None):
        name = ps_ui.combo_text(self.c('PrinterCombo'))
        self.settings.set('default_printer', u'' if name == REVIT_PDF else name)
        self.settings.save()
        self.say(u'"{0}" is now the default for new templates.'.format(name))

    def open_order_dialog(self, sender=None, args=None):
        jobs, _clashes = self.plan_jobs()
        if not jobs:
            self.say(u'Nothing ticked to order.')
            return
        entries = [(u'{0}'.format(job.key), job.label) for job in jobs]
        if self.combine_order:
            position = dict([(key, index) for index, key
                             in enumerate(self.combine_order)])
            entries.sort(key=lambda pair: position.get(pair[0], 10 ** 6))
        dialog = ps_orderwin.OrderWindow(entries, self.theme_name, self.window)
        chosen = dialog.show()
        if chosen is None:
            return
        self.combine_order = chosen
        self.say(u'Page order set for the combined file.')

    def save_sheet_set(self, sender=None, args=None):
        """Save the ticked sheets as a Revit View/Sheet Set.

        This writes to the model, so it goes out through the external event
        like everything else - a modeless window cannot start a transaction.
        """
        rows = self.ticked_rows()
        if not rows:
            self.say(u'Tick some sheets first.')
            return
        name = ps_ui.ask_text(u'Save a View/Sheet Set',
                              u'What should the set be called?',
                              u'RevoBIM export set', self.theme_name,
                              self.window)
        if not name:
            return
        views = [row.element for row in rows]
        self._queue(lambda uiapp: self._do_save_set(uiapp, name, views))

    def _do_save_set(self, uiapp, name, views):
        """Write the set on Revit's thread, then refresh both tabs' lists."""
        sheets = [view for view in views if view is not None]
        # The Selection tab's set is exactly what is ticked there, views
        # included, so nothing already in the set is kept.
        ok, message = ps_model.save_view_sheet_set(
            self.doc, name, sheets, keep_other_views=False)

        def finish():
            self.refresh_sheet_sets()
            self.say(message)
        self._on_ui(finish)
        return ok

    def refresh_sheet_sets(self):
        """Read the View/Sheet Sets again, for the Selection tab's filter
        and for the Document Register's set list alike."""
        self.sheet_sets = ps_model.read_sheet_sets(self.doc)
        ps_model.tag_rows_with_sets(self.rows, self.sheet_sets)
        self._fill_sheet_sets()

    # ==================================================================
    # exporting
    # ==================================================================

    def _queue(self, work):
        if HANDLER is None or EVENT is None:
            self.say(u'The Revit event is not available; reopen the tool.')
            return False
        HANDLER.work = work
        try:
            EVENT.Raise()
            return True
        except Exception as err:
            self.say(u'Revit would not take the job: {0}'.format(err))
            return False

    def _on_ui(self, call):
        """Marshal a callable onto the window's thread, then let it repaint.

        The catch that made the progress bar look broken: the export runs
        inside an ExternalEvent, and Revit raises those **on its own main
        thread - which is the thread this window lives on**. So setting
        ProgressBar.Value works, and then nothing renders, because the
        message pump is sitting inside the export loop and will not run a
        layout pass until the whole run is over. The bar jumped from empty
        to full and the elapsed time only ever showed the total.

        Pumping afterwards is what fixes it. Invoking an empty delegate at
        Background priority runs everything queued above Background first,
        Render included, and returns. It is WPF's DoEvents, and it is only
        safe here because there is nothing re-entrant to hit: the buttons
        that could start another run are disabled for the duration.
        """
        try:
            self.window.Dispatcher.Invoke(Action(call))
        except Exception:
            try:
                call()
            except Exception:
                pass
        self._pump()

    def _pump(self):
        """Let the window draw. See _on_ui for why this is needed at all."""
        try:
            from System.Windows.Threading import DispatcherPriority
            self.window.Dispatcher.Invoke(DispatcherPriority.Background,
                                          Action(lambda: None))
        except Exception:
            pass

    def start_export(self, sender=None, args=None):
        if self.exporting:
            return
        # The full Export always asks and reports, whatever an Express run
        # that never reached Revit left behind.
        self._express_run = False
        jobs, clashes = self.plan_jobs()
        formats = self.chosen_formats()
        if self.register_alone(jobs):
            self._start_register_alone()
            return
        if not jobs or not formats:
            self.say(u'Tick some sheets and at least one format first.')
            return

        # The one check that has to happen before a run rather than be
        # reported after it. A driver with no staging folder cannot
        # produce a single file, and the only symptom is "no file
        # appeared" once per sheet - which reads like a Revit problem
        # and is not. Suppress dialogs does not silence this: it is not
        # a Revit dialog, it is the run refusing to start.
        blocker = self._pdf_blocker(formats)
        if blocker:
            answer = ps_ui.Prompt(
                title=u'Export',
                headline=u'This would not write a single PDF.',
                message=blocker,
                detail=u'Revit\'s own exporter needs nothing set up, writes '
                       u'the exact file name asked for and keeps each sheet '
                       u'at its own size. It is also the faster of the two.',
                primary=u'Use Revit\'s own exporter',
                secondary=u'Open setup',
                theme_name=self.theme_name, owner=self.window).show()
            if answer == 'primary':
                ps_ui.fill_combo(self.c('PrinterCombo'), self.printer_list,
                                 selected=REVIT_PDF)
                self._printer_changed(None, None)
                self.say(u'Switched to Revit\'s own exporter. Press Export '
                         u'again.')
            elif answer == 'secondary':
                self.open_setup()
            return

        root = self._text_of('RootFolderBox')
        ok, error = ps_paths.writable(root)
        if not ok:
            ps_ui.Prompt(
                title=u'Export', headline=u'That folder cannot be written to.',
                message=u'{0}\n\n{1}'.format(root, error),
                primary=u'Close', theme_name=self.theme_name,
                owner=self.window).show()
            return

        profile = self._collect_profile()
        quiet = self._flag_of('SuppressCheck')
        if not quiet:
            detail = self._confirmation_detail(jobs, formats, clashes)
            answer = ps_ui.Prompt(
                title=u'Export',
                headline=u'Write {0} file{1}?'.format(
                    self._file_count(jobs, formats),
                    u'' if self._file_count(jobs, formats) == 1 else u's'),
                message=u'Nothing has been written yet. This is exactly what '
                        u'will happen.',
                detail=detail, primary=u'Export', secondary=u'Go back',
                theme_name=self.theme_name, owner=self.window).show()
            if answer != 'primary':
                return
        self._launch_export(jobs, formats, profile, quiet)

    def _launch_export(self, jobs, formats, profile, quiet):
        """Start a planned run on Revit's thread. Export and Express Export
        both end here, so the two can never drift apart."""
        self._hunted_folder = u''
        # Decided now, from the plan: the folder names carry the time, and
        # the report comes a minute or an hour later.
        try:
            self._issue_folder = self.issue_folder(jobs, formats)
        except Exception:
            self._issue_folder = u''
        self._mark_plan_pending()
        ps_export.debug_reset()
        if quiet:
            ps_export.begin_suppression(self.uiapp)
        ps_export.debug(u'RevoBIM Pro Sheets Exporter debug log')
        chosen_printer = ps_ui.combo_text(self.c('PrinterCombo')) or REVIT_PDF
        ps_export.debug(u'{0} sheet(s), formats {1}, printer "{2}"'.format(
            len(jobs), u'+'.join(formats), chosen_printer))
        if ps_export.known_printer(chosen_printer) is not None:
            ps_export.debug(u'that printer is a known good driver, so a '
                            u'missing file is a staging folder problem '
                            u'rather than a Save As dialog')
        elif self.preferred_printer and chosen_printer != self.preferred_printer:
            ps_export.debug(u'"{0}" is also installed and is set up for '
                            u'unattended export'
                            .format(self.preferred_printer))

        self._begin_progress(self._file_count(jobs, formats))
        self._queue(lambda uiapp: self._do_export(uiapp, jobs, formats, profile))

    # ------------------------------------------- Express Export (1.56.0)

    def express_export(self, sender=None, args=None):
        """Express Export, from the Selection tab: the ticked sheets
        written with the template's settings as they stand, past Format and
        Create, with no question asked before, during or after the run.

        What would have been a prompt is decided instead and said on the
        status line: a print driver with nowhere to collect from runs
        through Revit's own exporter, Revit's dialogs are answered
        automatically, and at the end the folder opens if the template asks
        for that. A run that cannot happen at all - nothing ticked, no
        format, a folder that cannot be written - says why and stops.
        """
        if self.exporting:
            return False
        jobs, _clashes = self.plan_jobs()
        formats = self.chosen_formats()
        alone = self.register_alone(jobs)
        if not alone and (not jobs or not formats):
            self.say(u'Express Export: tick some {0}s, and a format in the '
                     u'template, first.'.format(
                         u'view' if self._is_views_mode() else u'sheet'))
            return False
        root = self._text_of('RootFolderBox')
        if not root:
            self.say(u'Express Export: the template has no root folder. Set '
                     u'one on the Create tab.')
            return False
        ok, error = ps_paths.writable(root)
        if not ok:
            self.say(u'Express Export: {0} cannot be written to - {1}'
                     .format(root, error))
            return False
        switched = False
        if not alone and self._pdf_blocker(formats):
            ps_ui.fill_combo(self.c('PrinterCombo'), self.printer_list,
                             selected=REVIT_PDF)
            self._printer_changed(None, None)
            switched = True
        self._express_run = True
        if alone:
            self._start_register_alone()
        else:
            self._launch_export(jobs, formats, self._collect_profile(), True)
        if switched:
            self.say(u'Express Export: the print driver has no "Driver saves '
                     u'to" folder, so Revit\'s own exporter is writing the '
                     u'PDFs.')
        return True

    def _express_finished(self, report):
        """The end of an Express Export: no report window. The summary goes
        on the status line, and the folder opens when the template says so."""
        self._express_run = False
        self._end_progress()
        try:
            report.debug_path = self._write_debug_log() or report.debug_path
        except Exception:
            pass
        text = report.summary()
        failed = report.failed()
        if failed:
            text = u'{0} Not written: {1}{2}'.format(
                text, u', '.join([u'{0} [{1}]'.format(o.label, o.fmt)
                                  for o in failed[:3]]),
                u' and {0} more'.format(len(failed) - 3)
                if len(failed) > 3 else u'')
        if report.folders() and self._flag_of('OpenFolderCheck', True):
            target = self.folder_to_open(report)
            try:
                ps_export.open_folder(target)
            except Exception:
                pass
        self.say(text)
        return text

    def _start_register_alone(self):
        """Export with nothing ticked and Add to export on: the register
        by itself, through the same run, report and Open folder as any
        other - so it lands in the issue folder and turns green on the
        Create list like a drawing does."""
        root = self._text_of('RootFolderBox')
        ok, error = ps_paths.writable(root)
        if not ok:
            ps_ui.Prompt(
                title=u'Export', headline=u'That folder cannot be written to.',
                message=u'{0}\n\n{1}'.format(root, error),
                primary=u'Close', theme_name=self.theme_name,
                owner=self.window).show()
            return
        profile = self._collect_profile()
        self._hunted_folder = u''
        try:
            self._issue_folder = self.register_folder([], [])
        except Exception:
            self._issue_folder = u''
        self._mark_plan_pending()
        ps_export.debug_reset()
        ps_export.debug(u'RevoBIM Pro Sheets Exporter debug log')
        ps_export.debug(u'no sheets ticked: the Document Register on its own')
        if getattr(self, '_express_run', False):
            ps_export.begin_suppression(self.uiapp)
        self._begin_progress(1)
        self._queue(lambda uiapp: self._do_export(uiapp, [], [], profile))

    @staticmethod
    def usable_printer(wanted, staging, installed, native,
                       prefer_native=True):
        """(printer to use, the one refused, why).

        A template carries the printer it was saved with, which is the
        right thing for a template to do and the wrong thing to obey
        blindly. A driver is a fact about a machine: the one named may
        not be installed here, and even where it is, it writes nothing
        until this machine has been told which folder it saves into.
        Either way the run would fail on every sheet.

        From 1.16.0 there is a third reason, and it is the default:
        this machine prefers Revit's own exporter. A driver costs a
        spooler round trip, paper size matching and a folder to collect
        from, in exchange for the driver's own output settings - worth
        it where a house standard lives in the driver, not worth it
        otherwise. So the driver is opt in per machine, and a template
        asking for one does not override that.

        Where there is no built-in exporter to fall back to - Revit
        2021 and earlier - the driver is kept whatever else is true,
        because a broken driver beats no route at all and the report
        will explain itself.
        """
        name = u'{0}'.format(wanted or u'')
        if not name:
            return u'', u'', u''
        if not native:
            return name, u'', u''
        if prefer_native:
            return u'', name, 'prefer-native'
        here = set([u'{0}'.format(one) for one in (installed or [])])
        if name not in here:
            return u'', name, 'not-installed'
        if not u'{0}'.format(staging or u'').strip():
            return u'', name, 'no-folder'
        return name, u'', u''

    @staticmethod
    def pdf_blocked(formats, printer, staging):
        """Whether a PDF run cannot possibly write a file.

        True for exactly one case, and it is the one that cost a whole
        test run on somebody else's machine: a print driver selected
        with no folder to collect from. Revit's own exporter never
        blocks, and neither does a run with no PDF in it.
        """
        if 'pdf' not in (formats or []):
            return False
        name = u'{0}'.format(printer or u'')
        if not name or name == REVIT_PDF:
            return False
        return not u'{0}'.format(staging or u'').strip()

    def _pdf_blocker(self, formats):
        """Why a PDF run cannot produce anything, or an empty string."""
        printer = ps_ui.combo_text(self.c('PrinterCombo'))
        if not self.pdf_blocked(formats, printer,
                                self._text_of('StagingBox')):
            return u''
        return (u'"{0}" is a print driver. A driver saves where it is '
                u'configured to save, not to the path Revit asks for, so '
                u'the tool collects each file from that folder and renames '
                u'it - and "Driver saves to" on the Format tab is empty, so '
                u'there is nothing to collect from. Every sheet would fail '
                u'with "no file appeared".'.format(printer))

    def _confirmation_detail(self, jobs, formats, clashes):
        lines = []
        lines.append(u'Formats : {0}'.format(
            u', '.join([format_label(f) for f in formats])))
        printer = ps_ui.combo_text(self.c('PrinterCombo'))
        lines.append(u'PDF via : {0}'.format(printer or REVIT_PDF))
        lines.append(u'Naming  : {0}'.format(ps_naming.preview(self.rules)))
        lines.append(u'')
        # Said before the run, not after it. A driver that asks where to save
        # turns a 200 sheet issue into 200 dialogs, and finding that out on
        # sheet one is much cheaper than finding it out at the end.
        if 'pdf' in formats and printer and printer != REVIT_PDF:
            staging = self._text_of('StagingBox')
            if staging:
                lines.append(u'Collecting from : {0}'.format(staging))
                if ps_export.known_printer(printer) is not None:
                    lines.append(u'"{0}" is already set not to ask where to '
                                 u'save, so the only thing to check is that '
                                 u'the folder above is the one it writes '
                                 u'to.'.format(printer))
                else:
                    lines.append(u'"{0}" must be set to save there on its '
                                 u'own. If it asks where to save instead, '
                                 u'nothing will be collected and every sheet '
                                 u'will be reported as a failure.'
                                 .format(printer))
                if self._busy_folder(staging):
                    lines.append(u'')
                    lines.append(u'CAREFUL: that is a folder you use for '
                                 u'other things. Collecting takes whatever '
                                 u'new PDF appears while the run is going, so '
                                 u'anything else that saves a PDF there in '
                                 u'the next few minutes will be renamed and '
                                 u'filed with your sheets. A folder of its '
                                 u'own avoids that.')
            else:
                lines.append(u'"{0}" is a print driver, so the file names '
                             u'above only happen if it takes the path Revit '
                             u'gives it. A driver set to ask where to save '
                             u'will prompt once per sheet and nothing will '
                             u'land. Test on two or three sheets before a '
                             u'full issue, or use "{1}", which needs no '
                             u'driver.'.format(printer, REVIT_PDF))
            lines.append(u'')
        if clashes:
            lines.append(u'These names were repeated and had a number added:')
            for name in sorted(clashes.keys())[:10]:
                lines.append(u'   {0}'.format(name))
            lines.append(u'')
        for job in jobs[:200]:
            solid = ps_model.is_three_d(self.rows_by_key.get(job.key))
            for fmt in formats:
                if fmt in VIEW_ONLY_FORMATS and not solid:
                    continue
                lines.append(os.path.join(job.folders.get(fmt, u''),
                                          job.base_name
                                          + self._suffix_for(fmt)))
        if len(jobs) > 200:
            lines.append(u'... and {0} more'.format(len(jobs) - 200))
        return u'\n'.join(lines)

    def _mark_plan_pending(self):
        """Clear last run's colours off the Create list."""
        try:
            for entry in self.create_table.Rows:
                entry['state'] = u''
        except Exception:
            pass

    @staticmethod
    def plan_state(was, good):
        """The colour a Create row should end up in.

        A failure wins over a success on the same row and is never
        undone. With two formats ticked, the one that did not appear is
        the thing worth seeing - a row that went green because the DWG
        landed, while its PDF did not, is a row that lies.
        """
        if u'{0}'.format(was) == 'failed':
            return 'failed'
        return 'done' if good else 'failed'

    def _mark_plan(self, outcome):
        """Colour one row of the Create list as each file lands.

        Called from Revit's thread as the run goes, so it is marshalled
        across. A failure wins over a success on the same row: with two
        formats ticked, one of them not appearing is the thing worth
        seeing, not the one that did.
        """
        try:
            key = u'{0}'.format(getattr(outcome, 'key', u''))
            good = bool(getattr(outcome, 'ok', False))
        except Exception:
            return
        if not key:
            return

        def paint():
            try:
                for entry in self.create_table.Rows:
                    if u'{0}'.format(entry['key']) != key:
                        continue
                    wanted = self.plan_state(entry['state'], good)
                    if u'{0}'.format(entry['state']) != wanted:
                        entry['state'] = wanted
                    return
            except Exception:
                pass
        self._on_ui(paint)

    def _begin_progress(self, total):
        self.exporting = True
        self.stop_wanted = False
        self._export_started = time.time()
        self._export_total = max(1, total)
        self._progress_done = 0
        bar = self.c('Progress')
        if bar is not None:
            try:
                bar.Minimum = 0
                bar.Maximum = self._export_total
                bar.Value = 0
            except Exception:
                pass
        # The Create list is what turns green as the run goes, so it is
        # the tab to be on for it.
        # Express Export stays where it was pressed: the bar is in the
        # footer, and passing the pages by is the point of it.
        if not getattr(self, '_express_run', False):
            self._set_tab(self.TAB_CREATE)
        ps_ui.set_text(self.c('ProgressText'), u'0%')
        ps_ui.set_visible(self.c('ProgressRow'), True)
        ps_ui.set_visible(self.c('CancelExportButton'), True)
        for name in ('ExportButton', 'BackButton', 'NextButton',
                     'ExpressExportButton'):
            control = self.c(name)
            try:
                control.IsEnabled = False
            except Exception:
                pass
        self.say(u'Exporting...')
        # Draw the bar before the first sheet rather than after it.
        self._pump()

    def _end_progress(self):
        self.exporting = False
        ps_ui.set_visible(self.c('ProgressRow'), False)
        ps_ui.set_visible(self.c('CancelExportButton'), False)
        for name in ('BackButton', 'NextButton', 'ExpressExportButton'):
            control = self.c(name)
            try:
                control.IsEnabled = True
            except Exception:
                pass
        self._say_step()
        self._refresh_plan()

    def stop_export(self, sender=None, args=None):
        self.stop_wanted = True
        self.say(u'Stopping after the file being written...')

    @staticmethod
    def _clock(seconds):
        """Seconds as m:ss, or h:mm:ss once it is worth the extra field."""
        try:
            seconds = int(max(0, round(seconds)))
        except Exception:
            return u'--'
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        if hours:
            return u'{0}:{1:02d}:{2:02d}'.format(hours, minutes, secs)
        return u'{0}:{1:02d}'.format(minutes, secs)

    def _progress(self, index, total, label, fmt):
        """Called from Revit's thread as each file starts. Marshalled to the UI.

        The estimate is the mean of what has actually happened so far, not a
        per-sheet guess: sheets vary wildly and an average over the run is
        the only honest number. It says nothing at all until one file has
        finished, because an estimate from a sample of none is a fiction.

        The count is kept here rather than taken from ``index``, which is
        each exporter's own position in its own list. With two formats
        ticked the second run starts at 1 again, and the bar used to slide
        back to the left halfway through.
        """
        done = self._progress_done
        self._progress_done += 1

        def update():
            bar = self.c('Progress')
            if bar is not None:
                try:
                    bar.Maximum = max(1, self._export_total)
                    bar.Value = min(bar.Maximum, done)
                except Exception:
                    pass

            elapsed = time.time() - (self._export_started or time.time())
            percent = int(round(100.0 * done / max(1, self._export_total)))

            parts = [u'{0}%'.format(percent), self._clock(elapsed)]
            if done >= 1 and elapsed > 0:
                each = elapsed / float(done)
                left = each * (self._export_total - done)
                parts.append(u'~{0} left'.format(self._clock(left)))
                try:
                    from System import DateTime
                    finish = DateTime.Now.AddSeconds(left)
                    parts.append(u'done ~{0}'.format(
                        ps_model.to_text(finish.ToString('HH:mm'))))
                except Exception:
                    pass
            ps_ui.set_text(self.c('ProgressText'), u'  '.join(parts))

            self.say(u'{0} {1} of {2} : {3}'.format(fmt, index, total, label))
        self._on_ui(update)

    def _should_stop(self):
        return self.stop_wanted

    def _do_export(self, uiapp, jobs, formats, profile):
        """The whole run, on Revit's API thread."""
        from System.Diagnostics import Stopwatch
        watch = Stopwatch.StartNew()
        report = ps_export.Report()
        report.on_add = self._mark_plan

        try:
            if 'pdf' in formats:
                printer = ps_config.get_text(profile, 'pdf.printer', u'')
                combine = ps_config.get_bool(profile, 'pdf.combine', False)
                ordered = self._ordered(jobs)
                if combine and not printer:
                    name = self._combined_name(ordered)
                    ps_export.export_pdf_combined(
                        self.doc, ordered, profile, name,
                        progress=self._progress, report=report)
                elif combine and printer:
                    report.note(u'A combined PDF is only written through '
                                u'Revit\'s own exporter, so the sheets were '
                                u'written as separate files.')
                    self._pdf_run(ordered, profile, printer, report)
                else:
                    self._pdf_run(ordered, profile, printer, report)

            if 'dwg' in formats and not report.cancelled:
                ps_export.export_dwg(
                    self.doc, jobs, profile, progress=self._progress,
                    should_stop=self._should_stop, report=report)

            # NWC and IFC only ever see the 3D views out of the ticked
            # rows. The tiles are greyed unless one is ticked, but a run
            # of eight views with one 3D among them is perfectly normal
            # and the other seven are simply not Navisworks' business.
            if not report.cancelled and ('nwc' in formats or 'ifc' in formats):
                solid = [job for job in jobs
                         if ps_model.is_three_d(self.rows_by_key.get(job.key))]
                skipped = len(jobs) - len(solid)
                if skipped:
                    report.note(u'{0} of the ticked views {1} not 3D, so {2} '
                                u'skipped {3}.'.format(
                                    skipped,
                                    u'is' if skipped == 1 else u'are',
                                    u'it was' if skipped == 1
                                    else u'they were',
                                    u' and '.join(
                                        [format_label(f) for f in formats
                                         if f in VIEW_ONLY_FORMATS])))
                if 'nwc' in formats and not report.cancelled:
                    ps_export.export_nwc(
                        self.doc, solid, profile, progress=self._progress,
                        should_stop=self._should_stop, report=report)
                if 'ifc' in formats and not report.cancelled:
                    ps_export.export_ifc(
                        self.doc, solid, profile, progress=self._progress,
                        should_stop=self._should_stop, report=report)
        except Exception as err:
            report.note(u'The run stopped early: {0}'.format(err))

        # The Document Register goes with the issue it describes, into the
        # folder the drawings went to - when the register tab says so.
        try:
            if not report.cancelled and self.register.add_to_export():
                self.register.export_into(
                    self.register_folder(jobs, formats), report)
            elif report.cancelled and self.register.add_to_export():
                report.note(u'The Document Register was not written: the '
                            u'run was cancelled.')
        except Exception as err:
            report.note(u'The Document Register was not written: {0}'
                        .format(err))

        try:
            watch.Stop()
            report.seconds = watch.ElapsedMilliseconds / 1000.0
        except Exception:
            report.seconds = 0.0

        # Always turned off, even where the run threw: leaving Revit's
        # dialogs answered automatically after the tool has finished would
        # be a genuinely dangerous thing to forget.
        quieted = ps_export.end_suppression()
        if quieted:
            report.note(u'{0} Revit dialog(s) were answered automatically '
                        u'while exporting.'.format(len(quieted)))

        report.debug_path = self._write_debug_log()

        self.last_report = report
        self._on_ui(lambda: self._show_report(report))

    def _pdf_run(self, jobs, profile, printer, report):
        if printer:
            ps_export.export_pdf_printer(
                self.doc, jobs, profile, printer, progress=self._progress,
                should_stop=self._should_stop, report=report)
        else:
            ps_export.export_pdf_native(
                self.doc, jobs, profile, progress=self._progress,
                should_stop=self._should_stop, report=report)

    def _ordered(self, jobs):
        if not self.combine_order:
            return jobs
        position = dict([(key, index) for index, key
                         in enumerate(self.combine_order)])
        return sorted(jobs,
                      key=lambda job: position.get(u'{0}'.format(job.key),
                                                   10 ** 6))

    def _combined_name(self, jobs):
        try:
            base = os.path.splitext(os.path.basename(self.doc.PathName))[0]
        except Exception:
            base = u''
        if not base:
            base = u'Sheets'
        return ps_naming.sanitise(u'{0} - {1} sheets'.format(base, len(jobs)))

    def _write_debug_log(self):
        """Put the run's debug lines somewhere the user can send them on.

        Beside the error log, so there is one folder to look in rather than
        two, and overwritten each run rather than appended to, because a log
        that grows forever is a log nobody opens.
        """
        try:
            path = os.path.join(os.path.dirname(ps_config.error_path()),
                                'pro_sheets_exporter_debug.txt')
            handle = open(path, 'wb')
            try:
                handle.write(ps_export.debug_text().encode('utf-8'))
            finally:
                handle.close()
            return path
        except Exception:
            return u''

    def _hunt_for_driver_folder(self, written, failed, report=None):
        """Where did the driver put them? Only asked when it matters.

        The window is the run's own duration plus a margin, not a flat few
        minutes: a PDF somebody saved before the export started is not
        evidence of anything, and offering it as the driver's folder would
        be worse than offering nothing.
        """
        if written or not failed:
            return []
        printer = ps_ui.combo_text(self.c('PrinterCombo'))
        if not printer or printer == REVIT_PDF:
            return []
        # Scanned even when a staging folder IS set, which it did not
        # used to be. A folder that is set but wrong looks exactly like
        # a driver that is prompting, and the tool was reporting the
        # second while the file sat in the first. Where the PDF actually
        # landed is the answer to both, and it is knowable.
        window = 90.0
        try:
            if report is not None and report.seconds:
                window = max(60.0, float(report.seconds) + 30.0)
        except Exception:
            window = 90.0
        try:
            found = ps_export.find_recent_pdfs(window)
            self._hunted_folder = u''
            staging = self._text_of('StagingBox')
            folders = []
            for path in found:
                folder = os.path.dirname(path)
                # The staging folder itself is not news. What matters is
                # a PDF somewhere the tool was not told to look.
                if staging and ps_paths.same_folder(folder, staging):
                    continue
                if folder not in folders:
                    folders.append(folder)
            if len(folders) == 1:
                self._hunted_folder = folders[0]
        except Exception:
            return []
        return found

    def _show_debug_window(self, report):
        """The debug log in its own window, ready to be copied.

        A log is only useful if it can be got out of the machine, and
        selecting text out of a report pane that is already holding the
        results is fiddly. Its own window, with Copy, is the whole feature.
        """
        text = ps_export.debug_text()
        if not text:
            return
        ps_ui.Prompt(
            title=u'Debug log',
            headline=u'What the tool asked Revit and the driver to do',
            message=u'In order, with timings. Press Copy detail to put the '
                    u'whole thing on the clipboard. It is also saved to '
                    u'{0}'.format(report.debug_path or u'(not saved)'),
            detail=text,
            primary=u'Close',
            theme_name=self.theme_name, owner=self.window).show()

    def _report_message(self, written, failed):
        """The line under the headline: what it means and what to do next.

        This sits in the wrapping part of the window, not in the monospace
        detail pane, because it is the sentence the user actually has to
        read and act on.
        """
        printer = ps_ui.combo_text(self.c('PrinterCombo'))
        driver_silent = [o for o in failed if 'no file appeared' in o.message]

        if failed and not written and driver_silent and printer \
                and printer != REVIT_PDF:
            staging = self._text_of('StagingBox')
            hunted = getattr(self, '_hunted_folder', u'')
            if staging and hunted:
                return (u'"{0}" wrote its PDF to {1}, not to the folder it '
                        u'was told to collect from ({2}). "Driver saves to" '
                        u'has to be the folder the **driver** is configured '
                        u'to save into - it tells the tool where to look, '
                        u'it cannot tell the driver where to put things. '
                        u'Point it at {1}, or use "{3}", which needs no '
                        u'folder at all.'.format(printer, hunted, staging,
                                                 REVIT_PDF))
            if staging:
                return (u'"{0}" took the job and no new PDF appeared in the '
                        u'staging folder, or anywhere else the tool can '
                        u'see. So it is sitting on a prompt of its own - '
                        u'the PDF24 assistant window opens behind Revit and '
                        u'waits - or the job was dropped. Check for a '
                        u'window behind Revit, turn on automatic saving in '
                        u'the driver, or use "{1}", which needs no driver '
                        u'at all and is the faster of the two.'
                        .format(printer, REVIT_PDF))
            if not hunted and not getattr(self, '_hunt_found_any', False):
                return (u'"{0}" took the job, reported no error, and no PDF '
                        u'appeared anywhere the tool can see. So the driver '
                        u'is most likely sitting on a prompt, or its own '
                        u'settings are sending the job somewhere unusual. '
                        u'Check it saves automatically, then set "Driver '
                        u'saves to" to that folder - or use "{1}", which '
                        u'needs no driver at all.'.format(printer, REVIT_PDF))
            if hunted:
                return (u'"{0}" took the job but wrote nothing to the path '
                        u'above. It looks like it saved to {1} instead - that '
                        u'is where PDFs have just appeared. Press "Use that '
                        u'folder" and the sheets will be collected from there '
                        u'and renamed on the next run.'.format(printer, hunted))
            return (u'Revit handed the job to "{0}" and it was accepted, but '
                    u'nothing arrived at the path above. Some drivers cannot '
                    u'take a path from Revit at all - they collect the job '
                    u'through their own port and save where their own '
                    u'settings say. Set "Driver saves to" on the Format tab '
                    u'to that folder and the sheets will be collected and '
                    u'renamed, or use "{1}", which needs no driver.'
                    .format(printer, REVIT_PDF))
        if failed and not written:
            return (u'Nothing was written. The reason for each sheet is '
                    u'below.')
        if failed:
            return (u'Every file was checked for on disk afterwards, so the '
                    u'count is the files that exist, not the calls Revit '
                    u'accepted. The ones that did not arrive are listed '
                    u'first, with the reason under each.')
        return (u'Every file was checked for on disk afterwards, so this '
                u'count is the files that exist, not the calls Revit '
                u'accepted.')

    def _show_report(self, report):
        if getattr(self, '_express_run', False):
            self._express_finished(report)
            return
        self._end_progress()
        written = report.written()
        failed = report.failed()

        # The failure reason goes on its own line under the sheet it belongs
        # to, rather than trailing off the end of it. A reason is a sentence
        # and wants the full width; a label is a label.
        lines = []
        if failed:
            lines.append(u'Did not write:')
            for outcome in failed:
                lines.append(u'   {0}  [{1}]'.format(outcome.label, outcome.fmt))
                if outcome.message:
                    lines.append(u'      {0}'.format(outcome.message))
            lines.append(u'')
        if report.notes:
            lines.append(u'Notes:')
            for note in report.notes:
                lines.append(u'   {0}'.format(note))
            lines.append(u'')
        # An empty "Written:" heading over nothing reads as a bug in the
        # report rather than as an export that wrote nothing.
        if written:
            lines.append(u'Written:')
            for outcome in written:
                lines.append(u'   {0}'.format(outcome.path))

        # When a driver took the job and nothing landed, go and look for
        # where it actually put the files rather than asking the user to.
        hunted = self._hunt_for_driver_folder(written, failed, report)
        self._hunt_found_any = bool(hunted)
        if hunted:
            lines.append(u'')
            lines.append(u'PDFs written in the last few minutes:')
            for path in hunted[:12]:
                lines.append(u'   {0}'.format(path))
            if len(hunted) > 12:
                lines.append(u'   ... and {0} more'.format(len(hunted) - 12))
            lines.append(u'')
            lines.append(u'If those are your sheets, that folder is what '
                         u'"Driver saves to" on the Format tab wants.')

        # The scan above runs after the log was first written, so write it
        # again - what the scan saw is the most useful part of it.
        report.debug_path = self._write_debug_log() or report.debug_path
        if report.debug_path:
            lines.append(u'')
            lines.append(u'Debug log saved to {0}'.format(report.debug_path))

        folders = report.folders()
        ask_to_open = folders and self._flag_of('OpenFolderCheck', True)
        offer_folder = (not folders) and getattr(self, '_hunted_folder', u'')

        # When the user has asked to be offered the folder, the offer is the
        # main button and answering it is one click. When they have not, the
        # folder is still reachable but Close is what the window is for.
        prompt = ps_ui.Prompt(
            title=u'Export finished',
            headline=report.summary(),
            message=self._report_message(written, failed),
            detail=u'\n'.join(lines).rstrip(),
            primary=u'Open folder' if ask_to_open else u'Close',
            secondary=u'Close' if ask_to_open else None,
            extra=(u'Use that folder' if offer_folder else
                   (None if ask_to_open else
                    (u'Open folder' if folders else None))),
            theme_name=self.theme_name, owner=self.window)

        target = self.folder_to_open(report)

        def open_it(sender, args):
            ps_export.open_folder(target)

        def take_folder(sender, args):
            try:
                self.c('StagingBox').Text = self._hunted_folder
                self._remember_staging(
                    ps_ui.combo_text(self.c('PrinterCombo')),
                    self._hunted_folder)
                sender.Content = u'Set'
            except Exception:
                pass

        if offer_folder:
            prompt.on_extra(take_folder)
        elif folders and not ask_to_open:
            prompt.on_extra(open_it)

        answer = prompt.show()
        if self._flag_of('DebugCheck'):
            self._show_debug_window(report)
        if ask_to_open and answer == 'primary':
            ps_export.open_folder(target)
            self.say(u'{0} opened.'.format(target))
            return
        self.say(report.summary())

    def folder_to_open(self, report):
        """The issue folder the run was planned into, where it exists.

        Before 1.24.0 this was the deepest folder written - one sheet
        series' PDF folder - and every other series meant climbing back
        out. Falls back to that when the issue folder is not on disk.
        """
        planned = getattr(self, '_issue_folder', u'') or u''
        if planned and os.path.isdir(planned):
            return planned
        deep_folder, _deep_file = ps_export.deepest_written(report)
        folders = report.folders()
        return deep_folder or (folders[0] if folders else planned)

    # ==================================================================
    # closing
    # ==================================================================

    def close(self):
        # Revision changes staged on the Document Register and not applied.
        try:
            if not self.register.can_close():
                return
        except Exception:
            pass
        if self.exporting:
            answer = ps_ui.Prompt(
                title=u'Export running',
                headline=u'An export is still running.',
                message=u'Closing now stops it after the file being written.',
                primary=u'Stop and close', secondary=u'Keep it open',
                theme_name=self.theme_name, owner=self.window).show()
            if answer != 'primary':
                return
            self.stop_wanted = True
        try:
            if self._theme_timer is not None:
                self._theme_timer.Stop()
        except Exception:
            pass
        try:
            self.register.close()
        except Exception:
            pass
        try:
            # The mode, not the palette. Saving the palette is what pinned
            # the window the first time somebody touched the chip.
            self.settings.set('theme_mode', self.theme_mode)
            self.remember_window()
        except Exception:
            pass
        try:
            self.window.Close()
        except Exception:
            pass

    def show(self):
        try:
            self.window.Show()
        except Exception:
            raise


# ==========================================================================
# entry point
# ==========================================================================

def show(uiapp):
    """Open the tool, replacing any copy of it already on screen."""
    global WINDOW, HANDLER, EVENT

    if WINDOW is not None:
        try:
            WINDOW.window.Activate()
            return WINDOW
        except Exception:
            WINDOW = None

    if HANDLER is None:
        HANDLER = ExportHandler()
    if EVENT is None:
        EVENT = ExternalEvent.Create(HANDLER)

    built = ProSheetsWindow(uiapp)

    def forget(sender, args):
        global WINDOW
        WINDOW = None

    try:
        built.window.Closed += forget
    except Exception:
        pass

    WINDOW = built
    built.show()
    return built
