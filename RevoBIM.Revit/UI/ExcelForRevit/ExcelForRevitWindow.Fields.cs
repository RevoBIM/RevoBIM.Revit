// Excel for Revit: every field of ExcelForRevitWindow (port of efr_core.py ExcelForRevitWindow.__init__, lines 4984-5100,
// plus the attributes that other methods create first: Table, KeyIndex, FieldCols, GripHost).
// The other window parts use these by the naming rule and do not declare them again.
using System;
using System.Collections.Generic;
using System.Data;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Threading;
using ExternalEvent = Autodesk.Revit.UI.ExternalEvent;
using RevoBIM.Tools.ExcelForRevit;
using WGrid = System.Windows.Controls.Grid;
using UIDocument = Autodesk.Revit.UI.UIDocument;
using Document = Autodesk.Revit.DB.Document;
using FieldInfo = RevoBIM.Tools.ExcelForRevit.FieldInfo;

namespace RevoBIM.UI.ExcelForRevit
{
    /// <summary>
    /// One selected grid cell (Python: the dict {'pos', 'col', 'ridx', 'fidx'} that sel_cells() returns).
    /// Pos = position in the grid's current item order, Col = the DataGridColumn, Ridx = model row index,
    /// Fidx = field index. Used wherever the Python passed those dicts around (sel_cells, editable_selection,
    /// the fill source, the formula cells).
    /// </summary>
    public class SelCell
    {
        public int Pos;
        public DataGridColumn Col;
        public int Ridx;
        public int Fidx;
    }

    /// <summary>
    /// The Excel for Revit main window. A plain class that owns a WPF Window (loaded from ExcelForRevit.xaml);
    /// spread over several partial files.
    /// </summary>
    public partial class ExcelForRevitWindow
    {
        /// <summary>The window currently open (replaces the Python LIVE_* module keepalives); set by Show().</summary>
        public static ExcelForRevitWindow Live;

        // not ported: _proved / prove_alive / on_any_mouse (liveness proof of the IronPython engine). _shown is kept
        // because Show() sets it; nothing reads it.
        internal bool _shown;

        // ---- state first created in __init__ (efr_core.py 4984-5100) ----
        /// <summary>Why Stage() last turned a value away.</summary>
        internal string LastRefusal = "";
        /// <summary>Values Stage() turned away this batch.</summary>
        internal int Refused;
        /// <summary>The open workset list, if any.</summary>
        internal WorksetDropdown WsDropdown;
        /// <summary>Times the Workset hint has been shown.</summary>
        internal int _wsHints;
        internal UIDocument Uidoc;
        internal Document Doc;
        internal ScheduleModel Model;
        /// <summary>Grid column -> the schedule field it shows (the # and Id columns are absent).</summary>
        internal Dictionary<DataGridColumn, FieldInfo> ColField = new Dictionary<DataGridColumn, FieldInfo>();
        /// <summary>Each undo entry is the batch of old values: staged key -> the text it held (or Efr.ABSENT-style sentinel object).</summary>
        internal List<Dictionary<EditKey, object>> UndoStack = new List<Dictionary<EditKey, object>>();
        internal List<Dictionary<EditKey, object>> RedoStack = new List<Dictionary<EditKey, object>>();
        /// <summary>The batch being recorded (key -> old value or the ABSENT sentinel), or null.</summary>
        internal Dictionary<EditKey, object> _batch;
        internal bool Editing;
        internal bool _closingOk;
        internal bool _dirtyPaint = true;
        internal bool _filling;
        internal List<SelCell> _fillSrc;
        internal int _fillTarget = -1;
        internal DataGridColumn _fillCol;
        internal DispatcherTimer _scrollTimer;
        internal double _scrollOver;
        internal double _scrollOverX;
        internal double _scrollAccum;
        internal double _scrollAccumX;
        /// <summary>null, "select" or "fill".</summary>
        internal string _dragMode;
        /// <summary>Anchor position of a drag selection, or null.</summary>
        internal int? _selAnchor;
        internal int _selPos = -1;
        internal DataGridColumn _selCol;
        internal DataGridColumn _selCurCol;
        /// <summary>The rectangle extend_selection last drew: ((loRow, hiRow, loCol, hiCol), cells added), or null.</summary>
        internal ((int LoRow, int HiRow, int LoCol, int HiCol) Rect, int Added)? _selRect;
        /// <summary>A selection refresh is already queued.</summary>
        internal bool _selPending;
        /// <summary>Bottom-right selected cell once worked out: Efr.Stale (not worked out), null (none) or a boxed (int Pos, DataGridColumn Col).</summary>
        internal object _lastSel = Efr.Stale;
        /// <summary>(row count, {model row: grid position}), or null.</summary>
        internal (int Count, Dictionary<int, int> Map)? _posCache;
        /// <summary>Row containers the grid has realised.</summary>
        internal HashSet<DataGridRow> LiveRows = new HashSet<DataGridRow>();
        /// <summary>Realised rows still showing old colours.</summary>
        internal HashSet<DataGridRow> _dirtyRows = new HashSet<DataGridRow>();
        /// <summary>Container -> attempts before its cells existed.</summary>
        internal Dictionary<DataGridRow, int> _paintTries = new Dictionary<DataGridRow, int>();
        /// <summary>Containers last given a heading's height.</summary>
        internal HashSet<DataGridRow> _headerTall = new HashSet<DataGridRow>();
        /// <summary>Where the left button went down in the grid, or null.</summary>
        internal Point? _downAt;
        /// <summary>(ridx, field index) shown as copy source.</summary>
        internal HashSet<(int Ridx, int FieldIndex)> CopyMarks = new HashSet<(int Ridx, int FieldIndex)>();
        internal bool Grouping;
        /// <summary>ridx -> group number.</summary>
        internal Dictionary<int, int> GroupOf = new Dictionary<int, int>();
        /// <summary>Group number -> (label, row count).</summary>
        internal Dictionary<int, (string Label, int Count)> GroupLabels = new Dictionary<int, (string Label, int Count)>();
        /// <summary>Group number -> its row index in the table.</summary>
        internal Dictionary<int, int> GroupRow = new Dictionary<int, int>();
        /// <summary>Group numbers currently shut.</summary>
        internal HashSet<int> Collapsed = new HashSet<int>();
        internal Button BtnExpand;
        internal Button BtnExcel;
        internal Button BtnIsolate;
        internal Button BtnTheme;
        internal Border GroupBar;
        internal StackPanel ToolStrip;
        internal WGrid ToolGrid;
        internal DataGridColumn SortCol;
        internal FieldInfo SortField;
        internal bool SortDesc;
        /// <summary>ridx -> the values (one per sort level) the order was built on.</summary>
        internal Dictionary<int, string[]> SortSnapshot = new Dictionary<int, string[]>();
        /// <summary>[(field, descending)], primary first.</summary>
        internal List<(FieldInfo Field, bool Desc)> SortStack = new List<(FieldInfo Field, bool Desc)>();
        internal Button BtnGroup;
        internal bool _firstRenderDone;
        /// <summary>The filter behind the current snapshot.</summary>
        internal string ActiveClause = "";
        /// <summary>Field index -> keyword.</summary>
        internal Dictionary<int, string> ColFilters = new Dictionary<int, string>();
        /// <summary>Field index -> set of allowed values.</summary>
        internal Dictionary<int, HashSet<string>> ColPicks = new Dictionary<int, HashSet<string>>();
        /// <summary>Columns currently isolated to duplicates.</summary>
        internal HashSet<int> DupIsolated = new HashSet<int>();
        /// <summary>The tick filter each one had before (null value = none).</summary>
        internal Dictionary<int, HashSet<string>> DupSavedPicks = new Dictionary<int, HashSet<string>>();
        /// <summary>The column the grid menu was opened on.</summary>
        internal FieldInfo _menuCol;
        internal Dictionary<int, TextBox> HeaderBoxes = new Dictionary<int, TextBox>();
        internal Dictionary<int, Button> HeaderCarets = new Dictionary<int, Button>();
        internal Dictionary<int, TextBlock> HeaderTitles = new Dictionary<int, TextBlock>();
        internal Dictionary<int, (Border Badge, TextBlock Letter)> HeaderBadges = new Dictionary<int, (Border Badge, TextBlock Letter)>();
        internal Dictionary<int, Border> HeaderOutlines = new Dictionary<int, Border>();
        internal DispatcherTimer _filterTimer;
        internal FindReplace Finder;
        internal string LastFormula = "";
        internal Border FormulaBar;
        internal TextBox FormulaBox;
        internal TextBlock FormulaInk;
        internal TextBlock FormulaHint;
        internal List<SelCell> FormulaCells = new List<SelCell>();
        internal bool FormulaPick = true;
        internal Button BtnPick;
        /// <summary>Last-used values of the Sequence dialog (start, step, pad, prefix, suffix as strings, keep as bool).</summary>
        internal Dictionary<string, object> SeqSettings = new Dictionary<string, object>();
        /// <summary>Last-used values of the Prefix/Suffix dialog (prefix, suffix as strings, skip_empty, skip_have as bool).</summary>
        internal Dictionary<string, object> AffixSettings = new Dictionary<string, object>();
        /// <summary>Last-used values of the Highlight dialog ("colour", "mode", "scope" as strings).</summary>
        internal Dictionary<string, string> HlSettings = new Dictionary<string, string>();
        /// <summary>(ridx, field index) -> (colour name, mode).</summary>
        internal Dictionary<(int Ridx, int FieldIndex), (string Colour, string Mode)> CellHl = new Dictionary<(int Ridx, int FieldIndex), (string Colour, string Mode)>();
        /// <summary>ridx -> (colour name, mode).</summary>
        internal Dictionary<int, (string Colour, string Mode)> RowHl = new Dictionary<int, (string Colour, string Mode)>();
        /// <summary>field index -> (colour name, mode).</summary>
        internal Dictionary<int, (string Colour, string Mode)> ColHl = new Dictionary<int, (string Colour, string Mode)>();
        /// <summary>Test columns added so far.</summary>
        internal int Scratch;
        /// <summary>The "+" column that adds a test column.</summary>
        internal DataGridColumn PlusCol;
        /// <summary>(ridx, field index) staged by an Excel import.</summary>
        internal HashSet<(int Ridx, int FieldIndex)> Imported = new HashSet<(int Ridx, int FieldIndex)>();
        internal bool _importing;
        /// <summary>Resize grip thumb -> (horizontal, vertical) direction, each -1, 0 or 1.</summary>
        internal Dictionary<Thumb, (int Horiz, int Vert)> _grips = new Dictionary<Thumb, (int Horiz, int Vert)>();
        internal bool Applying;
        internal WorkHandler Handler;
        internal ExternalEvent Event;
        /// <summary>True when the window runs modeless (settings "modeless", default true; falls back to false if the ExternalEvent cannot be made).</summary>
        internal bool Modeless;
        /// <summary>(left, top, width, height) before a maximise, or null.</summary>
        internal (double Left, double Top, double Width, double Height)? RestoreRect;
        /// <summary>(top, height) before a vertical edge-stretch, or null.</summary>
        internal (double Top, double Height)? Vstretch;
        internal double _snapBreak;
        internal WrapPanel LegendHost;
        internal Button MaxBtn;
        internal WindowDrawer Drawer;

        // ---- attributes created by __init__'s setup calls (named in the XAML or built by other parts) ----
        /// <summary>The toolbar table: (button name, icon, label, tooltip, click handler).</summary>
        internal List<(string Name, string Icon, string Label, string Tip, RoutedEventHandler Handler)> ToolDefs;
        /// <summary>Toolbar button name -> button (only those that built).</summary>
        internal Dictionary<string, Button> ToolButtons = new Dictionary<string, Button>();

        internal Window Window;
        internal DataGrid Dg;
        internal WGrid GridHost;
        internal Border Handle;
        internal Border Preview;
        internal TextBlock Status;
        internal TextBlock Pending;
        internal Button BtnRevertSel;
        internal Button BtnApply;

        // first assigned by build_grid / build_drawer (G2's range)
        /// <summary>The bound table (DefaultView is the grid's ItemsSource).</summary>
        internal DataTable Table;
        /// <summary>(target, param) -> [(row, field index)] (Efr.BuildKeyIndex).</summary>
        internal Dictionary<EditKey, List<(RowInfo Row, int Field)>> KeyIndex;
        /// <summary>The field columns, in creation order.</summary>
        internal List<DataGridColumn> FieldCols = new List<DataGridColumn>();
        /// <summary>The overlay holding the resize grips (null when the layout has none).</summary>
        internal FrameworkElement GripHost;
    }
}

