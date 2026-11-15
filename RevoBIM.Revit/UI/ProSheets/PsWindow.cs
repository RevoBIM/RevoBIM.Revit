using System;
using System.Collections.Generic;
using System.Data;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Threading;
using RevoBIM.Tools.ProSheets;
using Document = Autodesk.Revit.DB.Document;
using ExternalEvent = Autodesk.Revit.UI.ExternalEvent;
using IExternalEventHandler = Autodesk.Revit.UI.IExternalEventHandler;
using UIApplication = Autodesk.Revit.UI.UIApplication;
using UIDocument = Autodesk.Revit.UI.UIDocument;
using WpfWindow = System.Windows.Window;

namespace RevoBIM.UI.ProSheets
{
    /// <summary>
    /// The Pro Sheets Exporter window (port of ps_window.py).
    ///
    /// Modeless, owned to Revit's main window, so Revit stays fully navigable and
    /// editable while the tool is open. Everything that touches the Revit API on the
    /// way out goes through an ExternalEvent - a modeless window cannot start a
    /// transaction or call Document.Export directly.
    ///
    /// Never wait for an ExternalEvent from the window that raised it. Revit raises it
    /// on the same thread the window lives on, so blocking that thread to wait is a
    /// deadlock. The work is queued, the handler runs it, and everything the user sees
    /// is marshalled back onto the dispatcher.
    /// </summary>
    public static partial class PsWindow
    {
        internal static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        public const string NoTemplate = "(no template)";
        public const string RevitPdf = "Revit built-in PDF export";
        public const string NoSet = "(every sheet)";
        public const string DefaultDwgSetup = "(Revit default settings)";

        public static readonly List<(string Label, string Key)> RasterChoices = new List<(string, string)>
        {
            ("Low", "low"), ("Medium", "medium"), ("High", "high"), ("Presentation", "presentation"),
        };
        public static readonly List<(string Label, string Key)> ColourChoices = new List<(string, string)>
        {
            ("Color", "color"), ("Grayscale", "grayscale"), ("Black lines", "blackline"),
        };
        public static readonly List<(string Label, string Key)> MarginChoices = new List<(string, string)>
        {
            ("No Margin", "nomargin"), ("Printer Limit", "printerlimit"), ("User Defined", "usermargin"),
        };
        public static readonly List<(string Label, string Key)> DwgVersions = new List<(string, string)>
        {
            ("As the setup says", "default"), ("AutoCAD 2018", "R2018"), ("AutoCAD 2013", "R2013"),
            ("AutoCAD 2010", "R2010"), ("AutoCAD 2007", "R2007"), ("AutoCAD 2004", "R2004"),
        };

        public static readonly List<(string Label, string Key)> NwcParamChoices = new List<(string, string)>
        {
            ("All", "all"), ("Elements", "elements"), ("None", "none"),
        };
        public static readonly List<(string Label, string Key)> NwcCoordChoices = new List<(string, string)>
        {
            ("Shared", "shared"), ("Internal", "internal"),
        };

        public static readonly List<(string Label, string Key)> IfcVersionChoices =
            PsExport.IfcVersions.Select(v => (v.Label, v.Key)).ToList();
        public static readonly List<(string Label, string Key)> IfcFileTypeChoices =
            PsExport.IfcFileTypes.Select(v => (v.Label, v.Key)).ToList();
        public static readonly List<(string Label, string Key)> IfcDetailChoices =
            PsExport.IfcDetailLevels.Select(v => (v.Label, v.Key)).ToList();
        public static readonly List<(string Label, string Key)> IfcOriginChoices =
            PsExport.IfcOrigins.Select(v => (v.Label, v.Key)).ToList();
        public static readonly List<(string Label, string Key)> IfcBoundaryChoices = new List<(string, string)>
        {
            ("None", "0"), ("1st Level", "1"), ("2nd Level", "2"),
        };
        public static readonly List<(string Label, string Key)> IfcLinkedChoices = new List<(string, string)>
        {
            ("Do not export", "none"), ("Export as separate IFCs", "separate"),
        };
        public const string IfcInSession = "<In Session>";
        public const string IfcDefaultPhase = "Default phase to export";

        // ==========================================================================
        // the NWC and IFC fields
        //
        // profile key, control, kind, default. "kind" is 'flag', 'text', or a
        // choices list for a combo. One table drives reading the controls into a
        // profile and writing a profile back onto them, which is the only way
        // sixty tickboxes stay in step.
        // ==========================================================================

        /// <summary>One row of NWC_FIELDS / IFC_FIELDS. Kind is "flag", "text" or "choices".</summary>
        public class Field
        {
            public string Key;
            public string ControlName;
            public string Kind;
            public List<(string Label, string Key)> Choices;
            public bool FlagDefault;
            public string TextDefault;

            public static Field Flag(string key, string control, bool @default)
            {
                return new Field { Key = key, ControlName = control, Kind = "flag", FlagDefault = @default };
            }

            public static Field Text(string key, string control, string @default)
            {
                return new Field { Key = key, ControlName = control, Kind = "text", TextDefault = @default };
            }

            public static Field Combo(string key, string control, List<(string Label, string Key)> choices, string @default)
            {
                return new Field { Key = key, ControlName = control, Kind = "choices", Choices = choices, TextDefault = @default };
            }
        }

        public static readonly List<Field> NwcFields = new List<Field>
        {
            Field.Flag("nwc.parts", "NwcPartsCheck", false),
            Field.Flag("nwc.element_ids", "NwcElementIdsCheck", true),
            Field.Combo("nwc.parameters", "NwcParamsCombo", NwcParamChoices, "all"),
            Field.Flag("nwc.properties", "NwcPropertiesCheck", false),
            Field.Flag("nwc.linked_files", "NwcLinkedCheck", false),
            Field.Flag("nwc.room_as_attribute", "NwcRoomAttrCheck", true),
            Field.Flag("nwc.urls", "NwcUrlsCheck", true),
            Field.Combo("nwc.coordinates", "NwcCoordsCombo", NwcCoordChoices, "shared"),
            Field.Flag("nwc.divide_levels", "NwcLevelsCheck", true),
            Field.Flag("nwc.room_geometry", "NwcRoomGeomCheck", true),
            Field.Flag("nwc.find_materials", "NwcMaterialsCheck", true),
            Field.Flag("nwc.linked_cad", "NwcLinkedCadCheck", true),
            Field.Flag("nwc.lights", "NwcLightsCheck", false),
            Field.Text("nwc.faceting", "NwcFacetingBox", "1"),
        };

        public static readonly List<Field> IfcFields = new List<Field>
        {
            Field.Combo("ifc.version", "IfcVersionCombo", IfcVersionChoices, "IFC2x3CV2"),
            Field.Combo("ifc.file_type", "IfcFileTypeCombo", IfcFileTypeChoices, "ifc"),
            Field.Combo("ifc.space_boundaries", "IfcSpaceBoundCombo", IfcBoundaryChoices, "0"),
            Field.Combo("ifc.origin", "IfcOriginCombo", IfcOriginChoices, "shared"),
            Field.Flag("ifc.split_by_level", "IfcSplitCheck", false),
            Field.Flag("ifc.steel", "IfcSteelCheck", true),
            Field.Combo("ifc.linked_files", "IfcLinkedCombo", IfcLinkedChoices, "none"),
            Field.Flag("ifc.export_2d", "Ifc2dCheck", false),
            Field.Flag("ifc.visible_only", "IfcVisibleOnlyCheck", true),
            Field.Flag("ifc.rooms_in_3d", "IfcRoomsIn3dCheck", false),
            Field.Combo("ifc.detail", "IfcDetailCombo", IfcDetailChoices, "low"),
            Field.Flag("ifc.revit_psets", "IfcRevitPsetsCheck", false),
            Field.Flag("ifc.common_psets", "IfcCommonPsetsCheck", true),
            Field.Flag("ifc.base_quantities", "IfcQuantitiesCheck", false),
            Field.Flag("ifc.material_psets", "IfcMaterialPsetsCheck", false),
            Field.Flag("ifc.schedule_psets", "IfcSchedulePsetsCheck", false),
            Field.Flag("ifc.specific_schedules", "IfcSpecificSchedulesCheck", false),
            Field.Flag("ifc.user_psets", "IfcUserPsetsCheck", false),
            Field.Flag("ifc.type_properties", "IfcTypePropsCheck", false),
            Field.Text("ifc.user_psets_file", "IfcUserPsetsBox", ""),
            Field.Flag("ifc.parameter_map", "IfcParamMapCheck", false),
            Field.Text("ifc.parameter_map_file", "IfcParamMapBox", ""),
            Field.Flag("ifc.parts_as_elements", "IfcPartsAsElementsCheck", false),
            Field.Flag("ifc.solid_model", "IfcSolidModelCheck", false),
            Field.Flag("ifc.active_view_geometry", "IfcActiveViewGeomCheck", false),
            Field.Flag("ifc.family_type_reference", "IfcFamilyTypeRefCheck", false),
            Field.Flag("ifc.room_boundary_2d", "Ifc2dRoomBoundaryCheck", false),
            Field.Flag("ifc.site_elevation", "IfcSiteElevationCheck", false),
            Field.Flag("ifc.store_guid", "IfcStoreGuidCheck", false),
            Field.Flag("ifc.bounding_box", "IfcBoundingBoxCheck", false),
            Field.Flag("ifc.triangulation", "IfcTriangulationCheck", false),
            Field.Flag("ifc.type_name_only", "IfcTypeNameOnlyCheck", false),
            Field.Flag("ifc.visible_name", "IfcVisibleNameCheck", false),
        };

        // ==========================================================================
        // the format registry
        //
        // One row per format on the Format tab: the id used in the profile and in
        // the job folders, the controls that belong to it, and whether it can
        // actually be exported yet. Adding a format is one row plus its panel.
        // ==========================================================================

        // id, tick, tile, group, panel, label, live
        public static readonly List<(string Id, string Tick, string Tile, string Group, string Panel, string Label, bool Live)> Formats =
            new List<(string, string, string, string, string, string, bool)>
            {
                ("pdf", "PdfCheck", "PdfTile", "PdfGroup", "PdfPanel", "PDF", true),
                ("dwg", "DwgCheck", "DwgTile", "DwgGroup", "DwgPanel", "DWG", true),
                ("dwf", "DwfCheck", "DwfTile", "DwfGroup", "", "DWF", false),
                ("nwc", "NwcCheck", "NwcTile", "NwcGroup", "NwcPanel", "NWC", true),
                ("ifc", "IfcCheck", "IfcTile", "IfcGroup", "IfcPanel", "IFC", true),
            };

        // Formats that only make sense for a view, and only for a 3D one. Both
        // exporters are scoped to a single view: Navisworks has no concept of a
        // sheet at all, and an IFC of a drawing sheet would hold nothing.
        public static readonly string[] ViewOnlyFormats = { "nwc", "ifc" };

        public static List<string> LiveFormats()
        {
            return Formats.Where(row => row.Live).Select(row => row.Id).ToList();
        }

        public static (string Id, string Tick, string Tile, string Group, string Panel, string Label, bool Live)? FormatRow(string fmt)
        {
            foreach (var row in Formats)
            {
                if (row.Id == fmt)
                    return row;
            }
            return null;
        }

        public static string FormatLabel(string fmt)
        {
            var row = FormatRow(fmt);
            return row != null ? row.Value.Label : (fmt ?? "").ToUpperInvariant();
        }

        internal static int Pick(IList<(string Label, string Key)> choices, string stored, int defaultIndex = 0)
        {
            for (int index = 0; index < choices.Count; index++)
            {
                if (choices[index].Key == stored)
                    return index;
            }
            return defaultIndex;
        }

        // ==========================================================================
        // the external event
        // ==========================================================================

        /// <summary>Runs one queued export on Revit's API thread.</summary>
        public class ExportHandler : IExternalEventHandler
        {
            public Action<UIApplication> Work;

            public ExportHandler()
            {
                Work = null;
            }

            public void Execute(UIApplication uiapp)
            {
                Action<UIApplication> work = Work;
                Work = null;
                if (work == null)
                    return;
                try
                {
                    work(uiapp);
                }
                catch (Exception)
                {
                }
            }

            public string GetName()
            {
                return "RevoBIM Pro Sheets Exporter";
            }
        }

        // The window, the handler and the event are parked at class level: the
        // modeless window has to outlive the command that opened it.
        public static ProSheetsWindow Window;
        public static ExportHandler Handler;
        public static ExternalEvent Event;

        // ==========================================================================
        // entry point
        // ==========================================================================

        /// <summary>Open the tool, replacing any copy of it already on screen.</summary>
        public static ProSheetsWindow Show(UIApplication uiapp)
        {
            if (Window != null)
            {
                try
                {
                    Window.Window.Activate();
                    return Window;
                }
                catch (Exception)
                {
                    Window = null;
                }
            }

            if (Handler == null)
                Handler = new ExportHandler();
            if (Event == null)
                Event = ExternalEvent.Create(Handler);

            var built = new ProSheetsWindow(uiapp);

            try
            {
                built.Window.Closed += (sender, args) => { Window = null; };
            }
            catch (Exception)
            {
            }

            Window = built;
            built.Show();
            return built;
        }

        // ==========================================================================
        // the window
        // ==========================================================================

        public partial class ProSheetsWindow
        {
            // The tabs, by name. Nothing compares TabIndex() with a bare number.
            public const int TabSelection = 0;
            public const int TabRegister = 1;
            public const int TabFormat = 2;
            public const int TabCreate = 3;

            public UIApplication Uiapp;
            public UIDocument Uidoc;
            public Document Doc;
            public PsConfig.Settings Settings;
            // Two separate things: the mode the user chose, which is what gets
            // saved, and the palette that mode currently resolves to.
            public string ThemeMode;
            public string ThemeName;
            internal DispatcherTimer ThemeTimer;
            // Heading colours on the Selection tab: greyscale until changed;
            // colours picked for a heading are the project's, shared with the
            // Document Register.
            public string HeadingMode;
            public Dictionary<string, string> HeadingCustom = new Dictionary<string, string>(StringComparer.Ordinal);
            public List<string> RunLabels = new List<string>();
            public List<string> RunColours = new List<string>();

            public List<PsModel.Row> Rows = new List<PsModel.Row>();
            // The Views list's Project Browser columns - read with the views.
            public List<string> BrowserNames = new List<string>();
            public Dictionary<long, PsModel.Row> RowsByKey = new Dictionary<long, PsModel.Row>();
            public Dictionary<string, HashSet<long>> SheetSets = new Dictionary<string, HashSet<long>>(StringComparer.Ordinal);
            public Dictionary<string, string> IfcPhases = new Dictionary<string, string>(StringComparer.Ordinal);
            public List<string> PrinterList = new List<string>();
            public string PreferredPrinter = "";
            public bool NativePdf;
            internal (string Name, string Why)? PrinterRefused;
            public List<(string Name, string Group)> Catalogue = new List<(string Name, string Group)>();
            public List<PsNaming.Rule> Rules = PsNaming.DefaultRules();
            // Sheets and views are named independently: Rules is always the set
            // for the mode on screen, the other waits here.
            public Dictionary<string, List<PsNaming.Rule>> RulesByMode = new Dictionary<string, List<PsNaming.Rule>>(StringComparer.Ordinal)
            {
                { "sheets", PsNaming.DefaultRules("sheets") },
                { "views", PsNaming.DefaultRules("views") },
            };
            /// <summary>null when nothing is isolated.</summary>
            public HashSet<long> IsolatedKeys;
            public Dictionary<string, string> Profile = PsConfig.Defaults();
            public List<string> CombineOrder = new List<string>();

            public bool Exporting;
            // An Express Export run: no prompts, no report window.
            internal bool ExpressRun;
            public bool StopWanted;
            public PsExport.Report LastReport;
            internal string HuntedFolder = "";
            /// <summary>Python _issue_folder (renamed: clashes with the IssueFolder method).</summary>
            internal string IssueFolderCore = "";
            internal bool HuntFoundAny;
            internal HashSet<long> PreselectedKeys = new HashSet<long>();
            // One ordered list of every column on the Selection grid, fixed and
            // added alike.
            public List<string> ColumnOrder = DefaultColumnOrder("sheets");
            // The order each mode was last left in (and "<mode>.widths").
            public Dictionary<string, List<string>> ColumnOrders = new Dictionary<string, List<string>>(StringComparer.Ordinal);
            public Dictionary<string, string> ColumnSearch = new Dictionary<string, string>(StringComparer.Ordinal);
            public Dictionary<string, TextBox> SearchBoxes = new Dictionary<string, TextBox>(StringComparer.Ordinal);
            public CheckBox HeaderTick;
            public List<(string ColId, bool Descending)> SortStack = new List<(string ColId, bool Descending)>();
            public bool Grouped = true;
            public HashSet<int> Collapsed = new HashSet<int>();
            public Dictionary<int, List<DataRow>> Groups = new Dictionary<int, List<DataRow>>();
            internal bool SuspendGroupToggle;
            internal string TemplateSort = "";
            // The rows highlighted when a tick box was last clicked. Taken in
            // RowClick, because the grid may drop the selection before the tick
            // itself is reported.
            internal HashSet<string> TickSelection = new HashSet<string>(StringComparer.Ordinal);
            // Every run gets a colour; only the longer ones get a heading.
            public int RunCount;
            public Dictionary<string, Border> HeaderOutlines = new Dictionary<string, Border>(StringComparer.Ordinal);
            public Dictionary<string, TextBlock> HeaderBadges = new Dictionary<string, TextBlock>(StringComparer.Ordinal);
            internal List<DataRow> SortedRows = new List<DataRow>();
            internal List<string> SavedWidths = new List<string>();
            internal bool FirstFill = true;
            internal DispatcherTimer FilterTimer;
            internal string CurrentPrinter = "";
            internal double ExportStarted;
            internal int ExportTotal;
            internal int ProgressDone;
            internal bool SuspendTicks;
            internal bool Ready;
            internal EventHandler SettleHandler;

            public WpfWindow Window;
            public PsUi.Chrome Chrome;
            public PsUi.Zoom Zoom;
            public Dictionary<string, object> Ui = new Dictionary<string, object>(StringComparer.Ordinal);
            public PsRegView.RegisterView Register;
            public (string Date, string Time)? Stamp;
            public string UserName = "";
            public DataTable Table;
            public DataTable CreateTable;

            public ProSheetsWindow(UIApplication uiapp)
            {
                Uiapp = uiapp;
                Uidoc = uiapp.ActiveUIDocument;
                Doc = Uidoc.Document;

                Settings = new PsConfig.Settings();
                if (Settings.Migrated)
                {
                    // An older settings file brought up to this build's defaults.
                    // Written back at once so it only happens once.
                    try
                    {
                        Settings.Save();
                    }
                    catch (Exception)
                    {
                    }
                }
                ThemeMode = PsTheme.Mode(Settings.Text("theme_mode"));
                ThemeName = PsTheme.Resolve(ThemeMode);
                ThemeTimer = null;
                string savedMode = Settings.Text("sel_heading_mode", "");
                HeadingMode = PsRamp.HeadingMode(string.IsNullOrEmpty(savedMode) ? PsRamp.Grey : savedMode);
                try
                {
                    HeadingCustom = PsConfig.ReadHeadingColours(Doc) ?? new Dictionary<string, string>(StringComparer.Ordinal);
                }
                catch (Exception)
                {
                    HeadingCustom = new Dictionary<string, string>(StringComparer.Ordinal);
                }
                RunLabels = new List<string>();

                Window = PsUi.LoadWindow("ProSheets.xaml", ThemeName);
                Chrome = new PsUi.Chrome(Window, onClose: Close);
                // A shrunk bar is not dragged mid-export (see Chrome.Busy).
                Chrome.Busy = () => Exporting;
                // - and + in the header: the whole window smaller or bigger. Kept per machine.
                Zoom = new PsUi.Zoom(Window, Settings);
                // Three slow clicks on the logo open the RevoBIM Arcade, in the palette showing now.
                PsUi.AttachEgg(Window, () => ThemeName);
                PsUi.OwnToRevit(Window, uiapp);

                GrabControls();
                // Before anything that can reach OpenSetup - the first run setup
                // does, from the bottom of this method - because a saved setup tells
                // the register its parameters have changed.
                Register = new PsRegView.RegisterView(this);
                ReadModel();
                BuildTables();
                FillStaticCombos();
                Wire();
                LoadLastProfile();
                ApplyPreselection();
                RefreshAll();
                RestoreWindow();
                // A borderless, transparent window lays out once before its saved
                // size and the template's state settle; one more layout pass once it
                // is on screen does what a resize did.
                try
                {
                    SettleHandler = (sender, args) => SettleLayout(sender, args);
                    Window.ContentRendered += SettleHandler;
                }
                catch (Exception)
                {
                }
                StartThemeWatch();
                FirstRunSetup();
                // ps_context.audit(uiapp) not ported: the right-click menu is Revit 2025+ only.
            }

            // ==================================================================
            // controls
            // ==================================================================

            internal static readonly string[] ControlNames =
            {
                "MainTabs", "ThemeChip", "SetupButton", "ProfileCombo",
                "ProfileNewButton",
                "ProfileSaveButton", "ProfileDeleteButton",
                "ProfileImportButton", "ProfileExportButton", "StatusText",
                "Progress", "BackButton", "NextButton", "ExportButton",
                "CancelExportButton", "ExpressExportButton", "FooterButtons",
                "FooterDock",
                // selection
                "SheetsRadio", "ViewsRadio", "SheetSetCombo", "SaveSetButton",
                "SearchBox", "SelectAllButton", "SelectNoneButton",
                "InvertButton", "GroupCheck", "CollapseAllButton",
                "SelectionHeadingModeButton", "SelectionHeadingModeText",
                "ShowAllCheck", "IsolationNote",
                "OnSheetListCheck",
                "CustomNameButton", "SheetGrid", "SelectionHint",
                // format
                "FormatNote",
                "PdfCheck", "DwgCheck", "DwfCheck", "NwcCheck", "IfcCheck",
                "PdfTile", "DwgTile", "DwfTile", "NwcTile", "IfcTile",
                "PdfGroup", "DwgGroup", "DwfGroup", "NwcGroup", "IfcGroup",
                "PdfPanel", "DwgPanel", "NwcPanel", "IfcPanel",
                // NWC
                "NwcPartsCheck", "NwcElementIdsCheck", "NwcParamsCombo",
                "NwcPropertiesCheck", "NwcLinkedCheck", "NwcRoomAttrCheck",
                "NwcUrlsCheck", "NwcCoordsCombo", "NwcLevelsCheck",
                "NwcRoomGeomCheck", "NwcMaterialsCheck", "NwcLinkedCadCheck",
                "NwcLightsCheck", "NwcFacetingBox", "NwcCustomNameButton",
                "NwcAvailableNote",
                // IFC
                "IfcSetupCombo", "IfcVersionCombo", "IfcFileTypeCombo",
                "IfcPhaseCombo", "IfcSpaceBoundCombo", "IfcOriginCombo",
                "IfcSplitCheck", "IfcSteelCheck", "IfcHeaderButton",
                "IfcAddressButton", "IfcLinkedCombo", "Ifc2dCheck",
                "IfcVisibleOnlyCheck", "IfcRoomsIn3dCheck", "IfcDetailCombo",
                "IfcRevitPsetsCheck", "IfcCommonPsetsCheck",
                "IfcQuantitiesCheck", "IfcMaterialPsetsCheck",
                "IfcSchedulePsetsCheck", "IfcSpecificSchedulesCheck",
                "IfcUserPsetsCheck", "IfcTypePropsCheck", "IfcUserPsetsBox",
                "IfcUserPsetsBrowse", "IfcParamMapCheck", "IfcParamMapBox",
                "IfcParamMapBrowse", "IfcClassificationButton",
                "IfcPartsAsElementsCheck", "IfcSolidModelCheck",
                "IfcActiveViewGeomCheck", "IfcFamilyTypeRefCheck",
                "Ifc2dRoomBoundaryCheck", "IfcSiteElevationCheck",
                "IfcStoreGuidCheck", "IfcBoundingBoxCheck",
                "IfcTriangulationCheck", "IfcTypeNameOnlyCheck",
                "IfcVisibleNameCheck", "IfcImportSettingsButton",
                "IfcExportSettingsButton", "IfcCustomNameButton",
                "IfcAvailableNote",
                "PlaceCenterRadio", "PlaceOffsetRadio", "MarginCombo",
                "OffsetXBox", "OffsetYBox", "FitPageRadio", "ZoomRadio",
                "ZoomBox", "PrinterCombo", "PrinterNote",
                "MakeDefaultPrinterButton", "StagingBox", "StagingBrowseButton",
                "StagingNote", "VectorRadio", "RasterRadio",
                "RasterQualityCombo", "ColorsCombo", "ViewLinksBlueCheck",
                "HideRefPlanesCheck", "HideViewTagsCheck", "HideScopeBoxesCheck",
                "HideCropCheck", "HalftoneCheck", "MaskCoincidentCheck",
                "SeparateFilesRadio", "CombineRadio", "KeepPaperSizeCheck",
                "FormatCustomNameButton", "OrderButton", "DwgSetupCombo",
                "DwgSharedCoordsCheck", "DwgXrefCheck", "DwgXrefNote",
                "DwgVersionCombo",
                "DwgCustomNameButton",
                // create
                "RootFolderBox", "BrowseButton", "TokenBox", "AddTokenButton",
                "ProgressRow", "ProgressText",
                "PathPreview", "FolderPerFormatCheck", "OverwriteCheck",
                "OpenFolderCheck", "DebugCheck",
                "CreateSummary", "ClashWarning", "CreateGrid", "CreateHint",
            };

            internal void GrabControls()
            {
                Ui = new Dictionary<string, object>(StringComparer.Ordinal);
                foreach (string name in ControlNames)
                    Ui[name] = PsUi.Find(Window, name);
            }

            /// <summary>A grabbed control by name, or null (Python self.ui.get).</summary>
            public object C(string name)
            {
                return name != null && Ui.TryGetValue(name, out object found) ? found : null;
            }

            /// <summary>C(name) cast to a control type, or null.</summary>
            public T C<T>(string name) where T : class
            {
                return C(name) as T;
            }

            // ------------------------------------------- small typed helpers
            // (Python reached the same properties by duck typing.)

            /// <summary>Python u'{0}'.format(value) for a DataRow cell: DBNull and None are empty.</summary>
            internal static string S(object value)
            {
                if (value == null || value is DBNull)
                    return "";
                if (value is string text)
                    return text;
                return PsModel.ToText(value);
            }

            /// <summary>Python bool() of a tick cell.</summary>
            internal static bool B(object value)
            {
                return value is bool flag && flag;
            }

            internal static void SetEnabled(object control, bool enabled)
            {
                if (control is UIElement element)
                {
                    try
                    {
                        element.IsEnabled = enabled;
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            internal static void SetChecked(object control, bool? value)
            {
                if (control is ToggleButton toggle)
                {
                    try
                    {
                        toggle.IsChecked = value;
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            internal static bool SetTextValue(object control, string text)
            {
                try
                {
                    if (control is TextBox box)
                    {
                        box.Text = text ?? "";
                        return true;
                    }
                    if (control is ComboBox combo)
                    {
                        combo.Text = text ?? "";
                        return true;
                    }
                    if (control is TextBlock block)
                    {
                        block.Text = text ?? "";
                        return true;
                    }
                }
                catch (Exception)
                {
                }
                return false;
            }

            internal static string GetTextValue(object control)
            {
                if (control is TextBox box)
                    return box.Text;
                if (control is ComboBox combo)
                    return combo.Text;
                if (control is TextBlock block)
                    return block.Text;
                throw new InvalidOperationException("no Text on this control");
            }

            internal static double Now()
            {
                // Python time.time(): seconds since the epoch.
                return (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
            }

            internal static string Plural(int count)
            {
                return count == 1 ? "" : "s";
            }

            // ==================================================================
            // reading the model
            // ==================================================================

            internal void ReadModel()
            {
                string mode = IsViewsMode() ? "views" : "sheets";
                Rows = PsModel.ReadRows(Doc, mode);
                BrowserNames = new List<string>();
                if (mode == "views")
                    BrowserNames = PsModel.BrowserColumns(PsModel.BrowserFolderParameters(Doc, Rows));
                RowsByKey = new Dictionary<long, PsModel.Row>();
                foreach (PsModel.Row row in Rows)
                    RowsByKey[row.Key] = row;
                SheetSets = PsModel.ReadSheetSets(Doc);
                PsModel.TagRowsWithSets(Rows, SheetSets);
                Catalogue = PsModel.ParameterCatalogue(Doc, Rows);
                Stamp = PsModel.ExportStamp();
                UserName = PsModel.CurrentUser(Uiapp.Application);
            }

            internal bool IsViewsMode()
            {
                var radio = C<ToggleButton>("ViewsRadio");
                try
                {
                    return radio != null && radio.IsChecked == true;
                }
                catch (Exception)
                {
                    return false;
                }
            }

            internal string ModeName()
            {
                return IsViewsMode() ? "views" : "sheets";
            }

            public PsModel.RowLookup LookupFor(PsModel.Row row)
            {
                return new PsModel.RowLookup(Doc, row, Stamp, UserName);
            }

            // ==================================================================
            // the tables
            // ==================================================================

            internal void BuildTables()
            {
                Table = new DataTable("rows");
                Table.Columns.Add("sel", typeof(bool)).DefaultValue = false;
                foreach (string name in new[] { "num", "name", "rev", "size", "fname", "key",
                                                "vis", "show", "ord", "gid", "grp", "ishead" })
                    Table.Columns.Add(name, typeof(string));
                // The colour the sorted column's cell takes, carried on the row
                // because a run's colour depends on where it sits among the other
                // runs and no style trigger can know that. Always a real brush,
                // never left empty: a Setter handed DBNull cannot convert it to a
                // Brush and the cell loses its background altogether.
                Table.Columns.Add("gbrush", typeof(object)).DefaultValue = Brushes.Transparent;
                // A heading's text colour: black or white on its pill, by contrast
                // (PsRamp.TextOn). Read by GridCell's ishead trigger.
                Table.Columns.Add("gink", typeof(object)).DefaultValue = Brushes.Transparent;
                try
                {
                    Table.ColumnChanged += TickChanged;
                }
                catch (Exception)
                {
                }

                DataView view = Table.DefaultView;
                view.RowFilter = "[show] = '1'";
                view.Sort = "[ord] ASC";
                var grid = C<DataGrid>("SheetGrid");
                if (grid != null)
                {
                    try
                    {
                        grid.ItemsSource = view;
                    }
                    catch (Exception)
                    {
                    }
                }

                CreateTable = new DataTable("plan");
                foreach (string name in new[] { "num", "name", "size", "fmt", "fname", "folder", "key", "state" })
                    CreateTable.Columns.Add(name, typeof(string));
                var createGrid = C<DataGrid>("CreateGrid");
                if (createGrid != null)
                {
                    try
                    {
                        createGrid.ItemsSource = CreateTable.DefaultView;
                    }
                    catch (Exception)
                    {
                    }
                }

                grid = C<DataGrid>("SheetGrid");
                try
                {
                    grid.Columns.Clear();
                    grid.PreviewMouseRightButtonUp += HeaderRightClick;
                    grid.Sorting += OnSorting;
                    grid.PreviewMouseLeftButtonDown += RowClick;
                    grid.LoadingRow += PaintGroupRows;
                }
                catch (Exception)
                {
                }
                BuildColumns();
            }
        }
    }
}
