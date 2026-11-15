// The Document Register tab: drawing it, choosing what is in it, exporting it.
//
// Every sheet down the page and every revision across it, in the Drawing
// Register's layout - frozen drawing columns on the left, one column per
// revision with its date rotated up the header and the issue status letter
// under it in blue, the sheet's current revision picked out in orange. One tab
// per discipline along the bottom; series headings that collapse.
//
// A tick here means "in the register", not "print". Printing is the
// Selection tab's job, and 1.20.0 sharing one list of ticks between the two
// turned out to be the wrong model: the drawings that belong on a register are
// not the ones being printed today. So the register keeps its own list -
// Included - and nothing here touches the Selection tab's ticks.
//
// What is included is driven by a Revit View/Sheet Set. Choosing a set in
// the drop-down ticks exactly the sheets in it. Changing the ticks makes the
// set "dirty" and lights Apply, which writes the ticks back into the set
// through the external event. + starts a new set: named first, ticked
// second, written on Save. With no set chosen the ticks are kept per project in
// a file of their own, as the sheets left *out* - so a sheet added to the model
// later starts included rather than silently missing from the register.
//
// Nothing moves under the cursor. Unticking a sheet while "Included only"
// is showing turns it pale rather than whisking it away; the view catches up
// on the next filter, toggle or F5. Same rule as every other RevoBIM table.
//
// A revision header is a button. Clicking it isolates the sheets carrying
// that revision (1.42.0). Ctrl+click isolates several; a second click shows
// every sheet. The Sorting event is where the click arrives, and it is always
// cancelled: a register has one order.
//
// The sequence number at the top of a revision column picks it (1.39.0) -
// a Button, so its click is its own and never reaches the date's include.
// Ctrl and Shift pick several, Excel's way.
//
// A revision cell can be picked too (1.40.0): the cell turns into an orange
// chip and the picked-cell toolset appears. Picking is the register's own
// state, on a p_<column> flag per row and a DataTrigger - the grid's row
// selection is untouched.
//
// Filters are Excel's. Headings are coloured like the Selection tab's groups.
// Columns fit their text: measured once per tab with a TextBlock and frozen
// in pixels, never left on Auto.

using System;
using System.Collections.Generic;
using System.Data;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using RevoBIM.Tools.ProSheets;
using RvtDocument = Autodesk.Revit.DB.Document;
using RvtElement = Autodesk.Revit.DB.Element;
using RvtView = Autodesk.Revit.DB.View;
using RvtViewSheet = Autodesk.Revit.DB.ViewSheet;
using UIApplication = Autodesk.Revit.UI.UIApplication;
using UIDocument = Autodesk.Revit.UI.UIDocument;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsRegView
    {
        public const string Presentation = "http://schemas.microsoft.com/winfx/2006/xaml/presentation";

        // The first entry in the set list: ticks made by hand, kept per project.
        public const string ByHand = "(no set - tick by hand)";
        // A set that has been named but not yet written to the model.
        public const string NewMark = "  (new, not saved)";

        public const string Expanded = "▾  ";
        public const string Collapsed = "▸  ";

        // A revision cell: centred, orange and bold where it is the sheet's current
        // revision, and faded where the sheet is not in the register. Parsed rather
        // than built, because the orange has to be a DynamicResource to flip with the
        // palette and a Setter built in code cannot carry one. One style per column,
        // cached: the DataTrigger compares the row's "curkey" with this column's key.
        public const string CellStyle =
            "<Style xmlns=\"{0}\" TargetType=\"TextBlock\">" +
            "<Setter Property=\"HorizontalAlignment\" Value=\"Center\"/>" +
            "<Setter Property=\"VerticalAlignment\" Value=\"Center\"/>" +
            "<Style.Triggers>" +
            "<DataTrigger Binding=\"{{Binding curkey}}\" Value=\"{1}\">" +
            "<Setter Property=\"Foreground\" Value=\"{{DynamicResource OrangeBrush}}\"/>" +
            "<Setter Property=\"FontWeight\" Value=\"Bold\"/>" +
            "</DataTrigger>" +
            "<DataTrigger Binding=\"{{Binding sel}}\" Value=\"False\">" +
            "<Setter Property=\"Opacity\" Value=\"0.55\"/>" +
            "</DataTrigger>" +
            // Staged by the register and not yet applied: a cell gaining the
            // revision is green with a +, one losing it red and struck through.
            "<DataTrigger Binding=\"{{Binding s_{1}}}\" Value=\"add\">" +
            "<Setter Property=\"Background\" Value=\"{{DynamicResource GreenWashBrush}}\"/>" +
            "<Setter Property=\"Foreground\" Value=\"{{DynamicResource GreenBrush}}\"/>" +
            "<Setter Property=\"FontWeight\" Value=\"Bold\"/>" +
            "<Setter Property=\"Padding\" Value=\"6,1\"/>" +
            "<Setter Property=\"Opacity\" Value=\"1\"/>" +
            "</DataTrigger>" +
            "<DataTrigger Binding=\"{{Binding s_{1}}}\" Value=\"del\">" +
            "<Setter Property=\"Foreground\" Value=\"{{DynamicResource RedBrush}}\"/>" +
            "<Setter Property=\"TextDecorations\" Value=\"Strikethrough\"/>" +
            "<Setter Property=\"Opacity\" Value=\"1\"/>" +
            "</DataTrigger>" +
            // Picked for Change revision on sheet: a solid orange chip. Last, so it
            // wins over the two above - a picked cell has to look picked even on
            // the sheet's current revision, and even on a drawing left out.
            "<DataTrigger Binding=\"{{Binding p_{1}}}\" Value=\"1\">" +
            "<Setter Property=\"Background\" Value=\"{{DynamicResource OrangeBrush}}\"/>" +
            "<Setter Property=\"Foreground\" Value=\"{{DynamicResource OnOrangeBrush}}\"/>" +
            "<Setter Property=\"FontWeight\" Value=\"Bold\"/>" +
            "<Setter Property=\"Padding\" Value=\"6,1\"/>" +
            "<Setter Property=\"Opacity\" Value=\"1\"/>" +
            "</DataTrigger>" +
            "</Style.Triggers>" +
            "</Style>";

        // A revision column picked by its sequence number: an orange wash down the
        // whole column. Parsed here, then BasedOn the grid's RegisterCell in code -
        // a StaticResource cannot be resolved outside the window, and a CellStyle
        // that is not based on it would lose the template and the muted rows.
        public const string PickedColumnStyle =
            "<Style xmlns=\"{0}\" TargetType=\"DataGridCell\">" +
            "<Setter Property=\"Background\" Value=\"{{DynamicResource PickWashBrush}}\"/>" +
            "</Style>";

        // A revision just created through the Revision Manager: a green wash down
        // its column, so the eye goes straight to it. Built like the picked wash.
        public const string FreshColumnStyle =
            "<Style xmlns=\"{0}\" TargetType=\"DataGridCell\">" +
            "<Setter Property=\"Background\" Value=\"{{DynamicResource GreenWashBrush}}\"/>" +
            "</Style>";

        // The line where the drawing columns end and the revisions begin: a
        // column of its own, three pixels of blue top to bottom. Its heading and its
        // cells are templates with nothing in them but the colour.
        public const string DividerHeaderStyle =
            "<Style xmlns=\"{0}\" TargetType=\"DataGridColumnHeader\">" +
            "<Setter Property=\"Template\"><Setter.Value>" +
            "<ControlTemplate TargetType=\"DataGridColumnHeader\">" +
            "<Border Background=\"{{DynamicResource BlueBrush}}\"/>" +
            "</ControlTemplate></Setter.Value></Setter></Style>";
        public const string DividerCellStyle =
            "<Style xmlns=\"{0}\" TargetType=\"DataGridCell\">" +
            "<Setter Property=\"Template\"><Setter.Value>" +
            "<ControlTemplate TargetType=\"DataGridCell\">" +
            "<Border Background=\"{{DynamicResource BlueBrush}}\"/>" +
            "</ControlTemplate></Setter.Value></Setter>" +
            // Not across a heading's pill: it would cut it in two.
            "<Style.Triggers><DataTrigger Binding=\"{{Binding ishead}}\" Value=\"1\">" +
            "<Setter Property=\"Opacity\" Value=\"0\"/></DataTrigger></Style.Triggers>" +
            "</Style>";
        public const string EmptyCell = "<DataTemplate xmlns=\"{0}\"><TextBlock/></DataTemplate>";

        // A discipline tab's icon; its fill follows the tab button's text colour.
        public const string TabIconXaml =
            "<Path xmlns=\"{0}\" Width=\"14\" Height=\"14\" Stretch=\"Uniform\"" +
            " Margin=\"0,0,7,0\" VerticalAlignment=\"Center\" IsHitTestVisible=\"False\"" +
            " Fill=\"{{Binding Foreground, RelativeSource={{RelativeSource" +
            " FindAncestor, AncestorType=Button}}}}\" Data=\"{1}\"/>";

        // The green + at the end of the revisions: a new revision.
        public const string PlusIcon =
            "<Path xmlns=\"{0}\" Width=\"14\" Height=\"14\" Stretch=\"Uniform\"" +
            " Fill=\"{{DynamicResource GreenBrush}}\"" +
            " Data=\"M 5,0 L 7,0 L 7,5 L 12,5 L 12,7 L 7,7 L 7,12 L 5,12 L 5,7 L 0,7" +
            " L 0,5 L 5,5 Z\"/>";

        // The key of an issue data row, when the block scrolls with the drawings
        // (1.53.0): IssuePrefix + the Revision Manager column's id. Never a sheet.
        public const string IssuePrefix = "issue:";

        // The per-row flag that marks a revision cell picked: p_<column key>.
        public const string PickPrefix = "p_";

        // The per-row flag that marks a revision cell staged and not yet applied:
        // s_<column key>, "add" or "del" (see PsRegister.PendingFlags).
        public const string PendingPrefix = "s_";

        public const string CentredStyle =
            "<Style xmlns=\"{0}\" TargetType=\"TextBlock\">" +
            "<Setter Property=\"HorizontalAlignment\" Value=\"Center\"/>" +
            "<Setter Property=\"VerticalAlignment\" Value=\"Center\"/>" +
            "</Style>";

        // The Rev column: each drawing's current revision, bold and blue so it reads
        // as the answer the row gives. Faded like the rest of the row where the
        // drawing is out of the register - a fixed Foreground on the TextBlock would
        // otherwise beat the cell's muted colour and the row would look half in.
        public const string CurrentStyle =
            "<Style xmlns=\"{0}\" TargetType=\"TextBlock\">" +
            "<Setter Property=\"HorizontalAlignment\" Value=\"Center\"/>" +
            "<Setter Property=\"VerticalAlignment\" Value=\"Center\"/>" +
            "<Setter Property=\"FontWeight\" Value=\"Bold\"/>" +
            "<Setter Property=\"Foreground\" Value=\"{{DynamicResource BlueBrush}}\"/>" +
            "<Style.Triggers>" +
            "<DataTrigger Binding=\"{{Binding sel}}\" Value=\"False\">" +
            "<Setter Property=\"Opacity\" Value=\"0.55\"/>" +
            "</DataTrigger>" +
            "</Style.Triggers>" +
            "</Style>";

        internal static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        /// <summary>u'{0}'.format(value or u'') for a table cell: DBNull and None are blank.</summary>
        internal static string Str(object value)
        {
            if (value == null || value is DBNull) return "";
            if (value is string s) return s;
            if (value is bool b) return b ? "True" : "False";
            if (value is IFormattable f) return f.ToString(null, Inv);
            return value.ToString() ?? "";
        }

        /// <summary>u'' if count == 1 else u's'.</summary>
        internal static string Plural(int count, string one = "", string many = "s")
        {
            return count == 1 ? one : many;
        }

        /// <summary>A Python truth test for a value of unknown type (a peer window's answer).</summary>
        internal static bool Truthy(object value)
        {
            if (value == null) return false;
            if (value is string s) return s.Length > 0;
            if (value is bool b) return b;
            if (value is int i) return i != 0;
            if (value is long l) return l != 0;
            if (value is System.Collections.ICollection c) return c.Count > 0;
            return true;
        }

        /// <summary>
        /// The Document Register view. Built once by the main window (PsWindow.ProSheetsWindow)
        /// with itself as host: <c>new PsRegView.RegisterView(this)</c>.
        /// </summary>
        public partial class RegisterView
        {
            // id, heading, the narrowest it may be. The floor is not cosmetic: a
            // heading carries a filter box, and a narrower column clips its own
            // controls.
            public static readonly List<(string Id, string Title, int Floor)> Identity =
                new List<(string Id, string Title, int Floor)>
                {
                    ("sel", "", 44),
                    ("num", "Drawing No", 96),
                    ("name", "Drawing Title", 170),
                    ("size", "Size", 58),
                    ("scale", "Scale", 62),
                    ("rev", "Rev", 52),
                    // The current revision's sequence number. On screen only: the RD9
                    // sheet has no column for it, so the Excel export leaves it out.
                    ("seq", "Seq No", 60),
                    ("rdate", "Rev Date", 80),
                };
            public static readonly string[] Centred = { "size", "scale", "rev", "seq", "rdate" };
            public static readonly Dictionary<string, int> Ceilings =
                new Dictionary<string, int>(StringComparer.Ordinal) { { "name", 720 }, { "num", 520 } };
            public const int DefaultCeiling = 360;

            // Wide enough for "P02" in bold plus the cell padding, and for a filter
            // box you can type a letter into. 34px clipped the codes in 1.20.0.
            public const int RevisionFloor = 48;
            public const int RevisionCeiling = 110;

            public const int SearchMs = 220;

            // The register's own tick: the Selection tab's, plus a trigger that
            // hides it on a row whose hidetick is 1. Hidden rather than
            // collapsed, so the column keeps its width and nothing shifts sideways.
            public const string TickTemplate =
                "<DataTemplate " +
                "xmlns=\"http://schemas.microsoft.com/winfx/2006/xaml/presentation\" " +
                "xmlns:x=\"http://schemas.microsoft.com/winfx/2006/xaml\">" +
                "<CheckBox x:Name=\"Tick\" Style=\"{DynamicResource GridCheckBox}\" " +
                "IsChecked=\"{Binding sel, Mode=TwoWay, " +
                "UpdateSourceTrigger=PropertyChanged}\"/>" +
                "<DataTemplate.Triggers>" +
                "<DataTrigger Binding=\"{Binding hidetick}\" Value=\"1\">" +
                "<Setter TargetName=\"Tick\" Property=\"Visibility\" Value=\"Hidden\"/>" +
                "</DataTrigger>" +
                "</DataTemplate.Triggers>" +
                "</DataTemplate>";

            public PsWindow.ProSheetsWindow Host;
            public Window Window;
            public DataGrid Grid;
            public Panel TabStrip;
            public TextBox SearchBox;
            public TextBlock Summary;
            public TextBlock Source;
            public TextBlock Note;
            public UIElement Root;
            public ComboBox SetCombo;
            public Button ApplyButton;
            public Button ShowAllButton;
            public Button ShowIncludedButton;
            public Button CollapseButton;
            public Button HeadingModeButton;
            public TextBlock HeadingModeText;
            public Canvas LabelCanvas;
            public Button FreezeButton;
            public TextBlock FreezeText;
            public Button ResetButton;
            public TextBlock ResetText;
            public CheckBox ExportCheck;
            public Button AllRevsButton;
            public TextBlock CollapseText;
            public FrameworkElement CollapseIcon;
            public FrameworkElement ExpandIcon;
            public Button IsolateButton;
            public TextBlock IsolateText;
            public Button ChangeButton;
            public TextBlock ChangeText;
            public Button RemoveButton;
            public Button CreateButton;
            public Button EditButton;
            public FrameworkElement SheetTools;
            public TextBlock SheetToolsText;
            public Button AssignButton;
            public FrameworkElement CellTools;
            public Button UndoButton;
            public Button RedoButton;
            public Button ApplyRevsButton;
            public TextBlock ApplyRevsText;
            public Button DiscardButton;
            public TextBlock CellToolsText;

            public List<PsRegister.RevisionColumn> Revisions = new List<PsRegister.RevisionColumn>();
            public List<PsRegister.RegisterRow> Rows = new List<PsRegister.RegisterRow>();
            public Dictionary<string, PsRegister.RegisterRow> RowsByKey =
                new Dictionary<string, PsRegister.RegisterRow>(StringComparer.Ordinal);
            public Dictionary<string, RvtElement> Elements = new Dictionary<string, RvtElement>(StringComparer.Ordinal);
            public List<(string Label, List<PsRegister.RegisterRow> Rows)> Tabs =
                new List<(string Label, List<PsRegister.RegisterRow> Rows)>();
            public List<Button> TabButtons = new List<Button>();
            public List<CheckBox> TabChecks = new List<CheckBox>();
            public List<TextBlock> TabTexts = new List<TextBlock>();
            public int TabIndex;
            public string TabLabel = PsRegister.AllTab;
            public List<PsRegister.RevisionColumn> UsedColumns = new List<PsRegister.RevisionColumn>();
            public Dictionary<string, DataGridColumn> Columns = new Dictionary<string, DataGridColumn>(StringComparer.Ordinal);
            // heading id -> the keys of every drawing under it, sub-groups too
            public Dictionary<int, List<string>> Groups = new Dictionary<int, List<string>>();
            // heading id -> "Mechanical" or "Mechanical/570": what folds
            public Dictionary<int, string> GroupPaths = new Dictionary<int, string>();
            // heading id -> the heading above it, for a series under a discipline
            public Dictionary<int, int?> GroupParent = new Dictionary<int, int?>();
            // discipline -> its colour, shared by its heading, swatch and tab
            public Dictionary<string, string> DiscColour = new Dictionary<string, string>(StringComparer.Ordinal);
            // disciplines unticked on the tab strip: no worksheet for them
            public HashSet<string> SkipTabs = new HashSet<string>(StringComparer.Ordinal);
            public Dictionary<string, Button> FilterButtons = new Dictionary<string, Button>(StringComparer.Ordinal);
            public bool HideUnused;
            public bool Loaded;
            public bool Stale = true;
            public CheckBox HeaderTick;
            public string DisciplineParam = "";
            public string SeriesParam = "";

            // What is in the register, and where that came from.
            public HashSet<string> Included = new HashSet<string>(StringComparer.Ordinal);
            public string SetName = "";
            public bool SetNew;
            public HashSet<string> SetBase = new HashSet<string>(StringComparer.Ordinal);
            public string ShowMode;
            // (tab label, heading path) pairs folded away
            public HashSet<(string Tab, string Path)> Collapsed = new HashSet<(string Tab, string Path)>();
            // column id -> the set of values its filter allows ("" for a blank
            // cell); a column with no entry is not filtered
            public Dictionary<string, HashSet<string>> ColumnFilters =
                new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);

            // Revision columns picked by their sequence number, in column order,
            // and the one a Shift+click runs from.
            public List<string> PickedColumns = new List<string>();
            internal string ColumnAnchor;
            // The column keys the view is isolated to: drawings carrying any.
            public List<string> Isolated = new List<string>();
            // Revision cells picked: (sheet key, column key). A transient
            // selection - a new tab or a refresh starts it again.
            public HashSet<(string Sheet, string Column)> PickedCells = new HashSet<(string Sheet, string Column)>();
            internal (string Sheet, string Column)? CellAnchor;
            // sheet key -> its row in the table, to paint picked cells on
            internal Dictionary<string, DataRow> Entries = new Dictionary<string, DataRow>(StringComparer.Ordinal);
            // column key -> the sequence-number button heading it
            public Dictionary<string, Button> SeqButtons = new Dictionary<string, Button>(StringComparer.Ordinal);
            // The + column at the end of the revisions.
            public DataGridColumn PlusColumn;
            // Revisions the Revision Manager has just created, washed green
            // until the register is next read.
            public HashSet<string> FreshColumns = new HashSet<string>(StringComparer.Ordinal);
            // Sheet revision edits staged and not yet written, with Undo and
            // Redo; and what they last painted, {(sheet, column): "add"|"del"}.
            public PsRegister.PendingEdits Pending = new PsRegister.PendingEdits();
            internal Dictionary<(string Sheet, string Column), string> PendingFlags =
                new Dictionary<(string Sheet, string Column), string>();
            // The issue data under the revision headings (1.51.0): the
            // Revision Manager's Issue Status and Issued To / Method columns,
            // as rows - the Excel's block, live and editable.
            public List<PsRevData.Column> IssueFields = new List<PsRevData.Column>();
            // (column key, field id) -> the value stored in the model
            public Dictionary<(string Column, string Field), string> IssueStored =
                new Dictionary<(string Column, string Field), string>();
            // column key -> the status most of its drawings carry, shown
            // faintly where no Issue Status is stored
            public Dictionary<string, string> IssueDerived = new Dictionary<string, string>(StringComparer.Ordinal);
            // (column key, field id) -> its CheckBox or TextBox in the heading
            public Dictionary<(string Column, string Field), Control> IssueCells =
                new Dictionary<(string Column, string Field), Control>();
            // (column key, field id) -> the row Border behind it, for the wash
            public Dictionary<(string Column, string Field), Border> IssueRows =
                new Dictionary<(string Column, string Field), Border>();
            // column key -> the framed block in its heading
            public Dictionary<string, Border> IssuePieces = new Dictionary<string, Border>(StringComparer.Ordinal);
            internal bool IssuePainting;
            // The row names' block, laid over the drawing headings (1.52.0),
            // the spacer it lines up with, and where it was last put.
            public Border LabelBlock;
            public double LabelWidth;
            internal Dictionary<string, Border> BlockSpacers = new Dictionary<string, Border>(StringComparer.Ordinal);
            internal (int Left, int Top)? LabelPlace;
            // The register's name and the two logos, in the heading's free
            // space while the issue rows are frozen (1.54.0).
            public StackPanel Brand;
            internal (TextBlock Name, StackPanel Row, List<Image> Images)? BrandParts;
            internal (int Left, int Top, int Width, int Height)? BrandPlace;
            // Heading colours (1.52.0): the trade ramps, greys, or picked one
            // heading at a time - by heading name, kept per project.
            // Greyscale until changed (1.54.0).
            public string HeadingMode;
            public Dictionary<string, string> HeadingCustom = new Dictionary<string, string>(StringComparer.Ordinal);
            // The heading a right-click landed on, for the colour menu.
            internal string MenuHeading;
            // The issue data frozen in the heading, or as rows at the top of the
            // drawings that scroll with them (1.53.0). Frozen every time the
            // tool opens (1.54.0): scrolling is for the session it was asked in.
            public bool IssueFrozen = true;

            internal bool Suspend;
            internal bool SuspendCombo;
            internal HashSet<string> TickSelection = new HashSet<string>(StringComparer.Ordinal);
            internal DispatcherTimer SearchTimer;
            internal Dictionary<string, Style> Styles = new Dictionary<string, Style>(StringComparer.Ordinal);
            internal Dictionary<(string Text, double Size, bool Bold), double> Measures =
                new Dictionary<(string Text, double Size, bool Bold), double>();
            internal List<string> Warnings = new List<string>();
            internal int Order;

            public DataTable Table;
            public DataView View;

            public RegisterView(PsWindow.ProSheetsWindow host)
            {
                Host = host;
                Window = host.Window;
                Grid = PsUi.Find<DataGrid>(Window, "RegisterGrid");
                TabStrip = PsUi.Find<Panel>(Window, "RegisterTabs");
                SearchBox = PsUi.Find<TextBox>(Window, "RegisterSearch");
                Summary = PsUi.Find<TextBlock>(Window, "RegisterSummary");
                Source = PsUi.Find<TextBlock>(Window, "RegisterSource");
                Note = PsUi.Find<TextBlock>(Window, "RegisterNote");
                Root = PsUi.Find<UIElement>(Window, "RegisterRoot");
                SetCombo = PsUi.Find<ComboBox>(Window, "RegisterSetCombo");
                ApplyButton = PsUi.Find<Button>(Window, "RegisterApplyButton");
                ShowAllButton = PsUi.Find<Button>(Window, "RegisterShowAllButton");
                ShowIncludedButton = PsUi.Find<Button>(Window, "RegisterShowIncludedButton");
                CollapseButton = PsUi.Find<Button>(Window, "RegisterCollapseButton");
                HeadingModeButton = PsUi.Find<Button>(Window, "RegisterHeadingModeButton");
                HeadingModeText = PsUi.Find<TextBlock>(Window, "RegisterHeadingModeText");
                LabelCanvas = PsUi.Find<Canvas>(Window, "RegisterIssueLabels");
                FreezeButton = PsUi.Find<Button>(Window, "RegisterFreezeButton");
                FreezeText = PsUi.Find<TextBlock>(Window, "RegisterFreezeText");
                ResetButton = PsUi.Find<Button>(Window, "RegisterResetFiltersButton");
                ResetText = PsUi.Find<TextBlock>(Window, "RegisterResetFiltersText");
                ExportCheck = PsUi.Find<CheckBox>(Window, "RegisterAddToExport");
                AllRevsButton = PsUi.Find<Button>(Window, "RegisterAllRevsButton");
                CollapseText = PsUi.Find<TextBlock>(Window, "RegisterCollapseText");
                CollapseIcon = PsUi.Find<FrameworkElement>(Window, "RegisterCollapseIcon");
                ExpandIcon = PsUi.Find<FrameworkElement>(Window, "RegisterExpandIcon");
                IsolateButton = PsUi.Find<Button>(Window, "RegisterIsolateButton");
                IsolateText = PsUi.Find<TextBlock>(Window, "RegisterIsolateText");
                ChangeButton = PsUi.Find<Button>(Window, "RegisterChangeRevButton");
                ChangeText = PsUi.Find<TextBlock>(Window, "RegisterChangeRevText");
                RemoveButton = PsUi.Find<Button>(Window, "RegisterRemoveRevButton");
                CreateButton = PsUi.Find<Button>(Window, "RegisterCreateRevButton");
                EditButton = PsUi.Find<Button>(Window, "RegisterEditRevButton");
                SheetTools = PsUi.Find<FrameworkElement>(Window, "RegisterSheetTools");
                SheetToolsText = PsUi.Find<TextBlock>(Window, "RegisterSheetToolsText");
                AssignButton = PsUi.Find<Button>(Window, "RegisterAssignRevButton");
                CellTools = PsUi.Find<FrameworkElement>(Window, "RegisterCellTools");
                UndoButton = PsUi.Find<Button>(Window, "RegisterUndoButton");
                RedoButton = PsUi.Find<Button>(Window, "RegisterRedoButton");
                ApplyRevsButton = PsUi.Find<Button>(Window, "RegisterApplyRevsButton");
                ApplyRevsText = PsUi.Find<TextBlock>(Window, "RegisterApplyRevsText");
                DiscardButton = PsUi.Find<Button>(Window, "RegisterDiscardRevsButton");
                CellToolsText = PsUi.Find<TextBlock>(Window, "RegisterCellToolsText");

                HideUnused = host.Settings.Flag("reg_hide_unused", true);
                ShowMode = host.Settings.Text("reg_show", "all");
                if (string.IsNullOrEmpty(ShowMode))
                    ShowMode = "all";
                if (ShowMode != "all" && ShowMode != "included")
                    ShowMode = "all";
                string mode = host.Settings.Text("reg_heading_mode", "");
                HeadingMode = PsRamp.HeadingMode(string.IsNullOrEmpty(mode) ? PsRamp.Grey : mode);

                Table = new DataTable("register");
                Table.Columns.Add("sel", typeof(bool)).DefaultValue = false;
                foreach (var name in new[] { "key", "num", "name", "size", "scale", "rev", "seq", "rdate",
                                             "curkey", "ishead", "hid", "glabel", "gpath", "gcolor",
                                             "level", "vis", "show", "ord", "hidetick" })
                    Table.Columns.Add(name, typeof(string));
                // A heading's text colour, black or white on its pill (see
                // PsRamp.TextOn); GridCell's ishead trigger binds to it.
                Table.Columns.Add("gink", typeof(object)).DefaultValue = Brushes.Transparent;
                View = Table.DefaultView;
                View.RowFilter = "[show] = '1'";
                View.Sort = "[ord] ASC";

                Wire();
            }

            // ==================================================================
            // wiring
            // ==================================================================

            internal void Wire()
            {
                try
                {
                    Table.ColumnChanged += TickChanged;
                }
                catch (Exception)
                {
                }
                if (HeadingModeButton != null)
                {
                    try { HeadingModeButton.Click += (sender, args) => CycleHeadingMode(); }
                    catch (Exception) { }
                }
                if (FreezeButton != null)
                {
                    try { FreezeButton.Click += (sender, args) => ToggleIssueFrozen(); }
                    catch (Exception) { }
                }
                if (Grid != null)
                {
                    try { Grid.LayoutUpdated += PlaceIssueLabels; }
                    catch (Exception) { }
                }
                if (Grid != null)
                {
                    try
                    {
                        Grid.ItemsSource = View;
                        Grid.Sorting += OnSorting;
                        Grid.PreviewMouseLeftButtonDown += RowClick;
                        Grid.LoadingRow += PaintRow;
                        Grid.SelectionChanged += RowsSelected;
                        Grid.PreviewMouseRightButtonDown += RightPress;
                        Grid.PreviewMouseRightButtonUp += RightRelease;
                    }
                    catch (Exception)
                    {
                    }
                }
                Click(PsUi.Find<Button>(Window, "RegisterRefreshButton"), (sender, args) => Reload());
                Click(PsUi.Find<Button>(Window, "RegisterSetupButton"), (sender, args) => Host.OpenSetup(section: "register"));
                Click(PsUi.Find<Button>(Window, "RegisterApplyButton"), (sender, args) => ApplySet());
                Click(PsUi.Find<Button>(Window, "RegisterNewSetButton"), (sender, args) => NewSet());
                Click(PsUi.Find<Button>(Window, "RegisterExportButton"), (sender, args) => ExportNow());
                Click(PsUi.Find<Button>(Window, "RevisionManagerButton"), (sender, args) => OpenRevisionManager());
                Click(ShowAllButton, (sender, args) => SetShow("all"));
                Click(ShowIncludedButton, (sender, args) => SetShow("included"));
                Click(CollapseButton, (sender, args) => ToggleCollapseAll());
                Click(ResetButton, (sender, args) => ResetFilters());
                Click(IsolateButton, (sender, args) => ToggleIsolate());
                Click(ChangeButton, (sender, args) => ChangeRevision());
                Click(RemoveButton, (sender, args) => RemoveRevision());
                Click(CreateButton, (sender, args) => CreateRevision());
                Click(EditButton, (sender, args) => EditRevision());
                Click(AssignButton, (sender, args) => AssignRevision());
                Click(UndoButton, (sender, args) => Undo());
                Click(RedoButton, (sender, args) => Redo());
                Click(ApplyRevsButton, (sender, args) => ApplyRevisions());
                Click(DiscardButton, (sender, args) => DiscardPending());
                Click(AllRevsButton, (sender, args) => SetShowAllRevisions(HideUnused));
                // Ticked before the handler goes on, or setting it fires a save.
                if (ExportCheck != null)
                {
                    try
                    {
                        ExportCheck.IsChecked = Host.Settings.Flag("reg_add_to_export", false);
                        ExportCheck.Checked += ExportToggled;
                        ExportCheck.Unchecked += ExportToggled;
                    }
                    catch (Exception)
                    {
                    }
                }
                PaintAllRevsButton();
                try { SetCombo.SelectionChanged += SetPicked; }
                catch (Exception) { }
                try { SearchBox.TextChanged += SearchChanged; }
                catch (Exception) { }
                try { Root.PreviewKeyDown += KeyDown; }
                catch (Exception) { }
                PaintShow();
            }

            internal void Click(Button control, RoutedEventHandler handler)
            {
                if (control == null)
                    return;
                try
                {
                    control.Click += handler;
                }
                catch (Exception)
                {
                }
            }

            internal void Setting(string key, object value)
            {
                try
                {
                    Host.Settings.Set(key, value);
                    Host.Settings.Save();
                }
                catch (Exception)
                {
                }
            }

            // ==================================================================
            // coming and going
            // ==================================================================

            /// <summary>The tab has come forward: read if needed, refresh the set list.</summary>
            public void Show()
            {
                if (Stale || !Loaded)
                {
                    Reload();
                }
                else
                {
                    // The Selection tab can save a set while this one is away.
                    FillSetCombo();
                    ApplyFilters();
                    SayNotes();
                    Say();
                }
                Host.Say("A tick here puts a drawing in the register export. " +
                         "Click a revision date to include every drawing that " +
                         "carries it; click a series heading to fold it away.");
            }

            public void EnsureLoaded()
            {
                if (Stale || !Loaded)
                    Reload();
            }

            /// <summary>The model or the settings behind it changed; read again.
            /// At once when the register is on screen, otherwise the next time it
            /// is wanted - reading a register nobody is looking at is wasted time.</summary>
            public void Invalidate()
            {
                Stale = true;
                if (Host.OnRegisterTab())
                    Reload();
            }

            public void Close()
            {
                try
                {
                    if (SearchTimer != null)
                        SearchTimer.Stop();
                }
                catch (Exception)
                {
                }
            }

            // ==================================================================
            // reading
            // ==================================================================

            public void Reload()
            {
                var settings = Host.Settings;
                DisciplineParam = settings.Text("param_discipline", "") ?? "";
                SeriesParam = settings.Text("param_series", "") ?? "";
                Warnings = new List<string>();
                var sheets = new List<PsModel.Row>();
                try
                {
                    sheets = new List<PsModel.Row>(Host.SheetRows());
                    string scale = settings.Text("reg_scale_mode", "") != PsConfig.ScaleRevit
                        ? settings.Text("reg_scale_param", "")
                        : "";
                    var read = PsRegister.ReadRegister(Host.Doc, sheets, DisciplineParam, SeriesParam,
                                                       settings.Text("reg_status_param", ""), scale);
                    Revisions = read.Revisions;
                    Rows = read.Rows;
                }
                catch (Exception err)
                {
                    Revisions = new List<PsRegister.RevisionColumn>();
                    Rows = new List<PsRegister.RegisterRow>();
                    Warnings.Add(string.Format("The register could not be read: {0}", err.Message));
                }
                RowsByKey = new Dictionary<string, PsRegister.RegisterRow>(StringComparer.Ordinal);
                foreach (var row in Rows)
                    RowsByKey[Str(row.Key)] = row;
                // The green on new revisions lasts until the next read.
                FreshColumns = new HashSet<string>(StringComparer.Ordinal);
                // Picks survive a refresh only where the revision still exists.
                var known = new HashSet<string>(Revisions.Select(revision => revision.Key), StringComparer.Ordinal);
                PickedColumns = PickedColumns.Where(key => known.Contains(key)).ToList();
                Isolated = Isolated.Where(key => known.Contains(key)).ToList();
                ReadIssueData();
                try
                {
                    HeadingCustom = new Dictionary<string, string>(PsConfig.ReadHeadingColours(Host.Doc) ??
                                                                   new Dictionary<string, string>(), StringComparer.Ordinal);
                }
                catch (Exception)
                {
                    HeadingCustom = new Dictionary<string, string>(StringComparer.Ordinal);
                }
                // Staged edits survive a read, minus any whose revision, sheet or
                // issue data column has gone from the model.
                Pending.Prune(known, new HashSet<string>(RowsByKey.Keys, StringComparer.Ordinal),
                              new HashSet<string>(IssueFields.Select(field => field.Id), StringComparer.Ordinal));
                Elements = new Dictionary<string, RvtElement>(StringComparer.Ordinal);
                foreach (var sheet in sheets)
                {
                    if (sheet != null && sheet.IsSheet)
                        Elements[Str(sheet.Key)] = sheet.Element;
                }

                CommitEdits();
                Suspend = true;
                try
                {
                    Table.Rows.Clear();
                    ResetRevisionColumns();
                }
                finally
                {
                    Suspend = false;
                }

                // A refresh in the middle of editing a set keeps the edits; there
                // is no reason F5 should throw away ticks nobody has applied yet.
                if (Loaded && Dirty())
                {
                    Included.IntersectWith(RowsByKey.Keys);
                }
                else
                {
                    string wanted = Loaded ? SetName : settings.Text("reg_last_set", "");
                    Adopt(wanted);
                }

                Tabs = PsRegister.DisciplineTabs(Rows);
                SkipTabs = new HashSet<string>(PsConfig.ReadRegisterSkipped(Host.Doc) ?? new HashSet<string>(),
                                               StringComparer.Ordinal);
                DiscColour = DisciplineColours(Tabs.Where(tab => tab.Label != PsRegister.AllTab)
                                                   .Select(tab => tab.Label).ToList());
                var labels = Tabs.Select(tab => tab.Label).ToList();
                // Stay on the same discipline across a refresh where it still
                // exists. Being thrown back to All every F5 is the kind of thing
                // that makes people stop pressing it.
                TabIndex = labels.Contains(TabLabel) ? labels.IndexOf(TabLabel) : 0;
                Loaded = true;
                Stale = false;
                SaySource();
                FillSetCombo();
                BuildTabStrip();
                SelectTab(TabIndex);
            }

            /// <summary>One table column per revision in the project.
            ///
            /// All of them, once per read. Which ones the grid shows is a per-tab
            /// decision; the table just has to be able to hold whatever any tab
            /// binds to.</summary>
            internal void ResetRevisionColumns()
            {
                try
                {
                    foreach (DataColumn column in Table.Columns.Cast<DataColumn>().ToList())
                    {
                        string name = Str(column.ColumnName);
                        string head = name.Length >= 2 ? name.Substring(0, 2) : name;
                        string flag = (head == PsRegView.PickPrefix || head == PsRegView.PendingPrefix)
                            ? name.Substring(2)
                            : "";
                        if (PsRegister.IsColumnKey(name) || PsRegister.IsColumnKey(flag))
                            Table.Columns.Remove(column);
                    }
                }
                catch (Exception)
                {
                }
                foreach (var revision in Revisions)
                {
                    try
                    {
                        Table.Columns.Add(revision.Key, typeof(string));
                        // The picked-cell flag beside it; see CellStyle.
                        Table.Columns.Add(PsRegView.PickPrefix + revision.Key, typeof(string));
                        // And whether a staged edit adds or removes it.
                        Table.Columns.Add(PsRegView.PendingPrefix + revision.Key, typeof(string));
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }

            // ==================================================================
            // what is included: View/Sheet Sets, or by hand
            // ==================================================================

            public HashSet<string> AllKeys()
            {
                return new HashSet<string>(RowsByKey.Keys, StringComparer.Ordinal);
            }

            /// <summary>Whether the ticks differ from the set they came from.
            ///
            /// By hand there is nothing to apply - those ticks are saved as they
            /// are made. A new set is always dirty until it has been written.</summary>
            public bool Dirty()
            {
                if (string.IsNullOrEmpty(SetName))
                    return false;
                if (SetNew)
                    return true;
                return !Included.SetEquals(SetBase);
            }

            internal Dictionary<string, HashSet<long>> SheetSets()
            {
                return Host.SheetSets ?? new Dictionary<string, HashSet<long>>();
            }

            /// <summary>Take the ticks from a saved set, or from the by-hand list.</summary>
            internal void Adopt(string name)
            {
                var sets = SheetSets();
                var keys = AllKeys();
                SetNew = false;
                if (!string.IsNullOrEmpty(name) && sets.ContainsKey(name))
                {
                    SetName = name;
                    var members = new HashSet<string>(sets[name].Select(key => Str(key)), StringComparer.Ordinal);
                    members.IntersectWith(keys);
                    Included = members;
                }
                else
                {
                    SetName = "";
                    var excluded = PsConfig.ReadRegisterExcluded(Host.Doc);
                    var included = new HashSet<string>(keys, StringComparer.Ordinal);
                    included.ExceptWith(excluded ?? new HashSet<string>());
                    Included = included;
                }
                SetBase = new HashSet<string>(Included, StringComparer.Ordinal);
            }

            internal void SaveByHand()
            {
                if (!string.IsNullOrEmpty(SetName))
                    return;
                var left = AllKeys();
                left.ExceptWith(Included);
                PsConfig.WriteRegisterExcluded(Host.Doc, left);
            }

            internal void FillSetCombo()
            {
                var sets = SheetSets();
                var names = sets.Keys.OrderBy(one => one.ToLowerInvariant(), StringComparer.Ordinal).ToList();
                var items = new List<string> { PsRegView.ByHand };
                items.AddRange(names);
                string selected;
                if (SetNew && !string.IsNullOrEmpty(SetName))
                {
                    items.Add(SetName + PsRegView.NewMark);
                    selected = SetName + PsRegView.NewMark;
                }
                else
                {
                    selected = string.IsNullOrEmpty(SetName) ? PsRegView.ByHand : SetName;
                }
                SuspendCombo = true;
                try
                {
                    PsUi.FillCombo(SetCombo, items, selected: selected);
                }
                finally
                {
                    SuspendCombo = false;
                }
                PaintApply();
            }

            internal (string Name, bool Staged) PickedName()
            {
                string text = PsUi.ComboText(SetCombo, PsRegView.ByHand);
                if (text == PsRegView.ByHand || string.IsNullOrEmpty(text))
                    return ("", false);
                if (text.EndsWith(PsRegView.NewMark, StringComparison.Ordinal))
                    return (text.Substring(0, text.Length - PsRegView.NewMark.Length), true);
                return (text, false);
            }

            /// <summary>Ask before throwing away ticks nobody has applied. True to go on.</summary>
            internal bool LeaveDirtySet()
            {
                if (!Dirty())
                    return true;
                string answer = new PsUi.Prompt(
                    title: "Document Register",
                    headline: string.Format("\"{0}\" has changes that were not applied.", SetName),
                    message: "The ticks changed since the set was last saved. " +
                             "Leaving it now throws those changes away; the set in " +
                             "Revit stays as it was.",
                    primary: "Discard changes", secondary: "Keep editing",
                    themeName: Host.ThemeName, owner: Window).Show();
                return answer == "primary";
            }

            internal void SetPicked(object sender, SelectionChangedEventArgs args)
            {
                if (SuspendCombo)
                    return;
                var (name, staged) = PickedName();
                if (staged || (name == SetName && !SetNew))
                    return;
                if (!LeaveDirtySet())
                {
                    FillSetCombo();          // put the old choice back
                    return;
                }
                Adopt(name);
                Setting("reg_last_set", SetName);
                FillSetCombo();
                SyncTicks();
                ApplyFilters();
                PaintTabStrip();
                Say();
                if (!string.IsNullOrEmpty(SetName))
                {
                    Host.Say(string.Format("\"{0}\" ticks {1} drawing{2}. Change the ticks and " +
                                           "press Apply to write them back into the set.",
                                           SetName, Included.Count, Plural(Included.Count)));
                }
                else
                {
                    Host.Say("Ticking by hand: the ticks are kept for this project as you make them.");
                }
            }

            /// <summary>Write the ticks back into the chosen set, through Revit's event.</summary>
            public void ApplySet()
            {
                if (string.IsNullOrEmpty(SetName))
                {
                    Host.Say("Choose a View/Sheet Set to apply to, or + to start " +
                             "a new one. Ticks made by hand are already kept for " +
                             "this project.");
                    return;
                }
                if (Included.Count == 0)
                {
                    Host.Say("A View/Sheet Set cannot be empty - tick at least one drawing first.");
                    return;
                }
                if (!Dirty())
                {
                    Host.Say(string.Format("\"{0}\" already holds exactly these drawings.", SetName));
                    return;
                }
                string name = SetName;
                var included = new HashSet<string>(Included, StringComparer.Ordinal);
                var sheets = included.OrderBy(key => key, StringComparer.Ordinal)
                                     .Where(key => Elements.ContainsKey(key))
                                     .Select(key => Elements[key] as RvtView)
                                     .ToList();
                if (Host.Queue(uiapp => DoApply(name, sheets, included)))
                    Host.Say(string.Format("Saving \"{0}\"...", name));
            }

            /// <summary>On Revit's thread. Views already in the set are kept.</summary>
            internal bool DoApply(string name, List<RvtView> sheets, HashSet<string> included)
            {
                var (ok, message) = PsModel.SaveViewSheetSet(Host.Doc, name, sheets, keepOtherViews: true);

                void Finish()
                {
                    Host.RefreshSheetSets();
                    if (ok && SetName == name)
                    {
                        SetNew = false;
                        SetBase = new HashSet<string>(included, StringComparer.Ordinal);
                        Setting("reg_last_set", name);
                    }
                    FillSetCombo();
                    Say();
                    Host.Say(message);
                }
                Host.OnUi(Finish);
                return ok;
            }

            // ==================================================================
            // the Revision Manager
            // ==================================================================

            /// <summary>Stage revision changes in the manager; write them on Apply.
            ///
            /// The manager is modal and stages only. Apply hands its plan back
            /// here, the plan is written through Revit's external event in one
            /// transaction, and the register reads the model again - so closing
            /// the manager with Apply lands back on an up-to-date register.</summary>
            public void OpenRevisionManager(List<string> focus = null)
            {
                PsRevisions.Staging staging;
                try
                {
                    staging = PsRevisions.Read(Host.Doc, Host.Settings.Text("param_series", ""),
                                               Host.Settings.Text("reg_status_param", ""));
                }
                catch (Exception err)
                {
                    Host.Say(string.Format("The revisions could not be read: {0}", err.Message));
                    return;
                }
                // Open on the revisions asked for (Edit revision), else on those of
                // any cloud selected in Revit; and know which sheet is open.
                UIDocument uidoc = Host.Uidoc;
                if (focus == null && PickedRevisions().Count > 0)
                {
                    // A revision picked here - its column, or a cell - is the one
                    // to open on.
                    focus = PickedRevisions();
                }
                if (focus == null && uidoc != null)
                    focus = PsRevisions.SelectedRevisionKeys(uidoc);
                string currentSheet;
                try
                {
                    currentSheet = PsRevisions.SheetNumberOf(uidoc.ActiveView);
                }
                catch (Exception)
                {
                    currentSheet = null;
                }
                PsRevWin.RevisionManager manager;
                PsRevisions.Plan plan;
                try
                {
                    var doc = Host.Doc;
                    manager = new PsRevWin.RevisionManager(
                        staging, Host.ThemeName, Window,
                        () => PsRevData.BoundParameters(doc),
                        settings: Host.Settings, focus: focus,
                        currentSheet: currentSheet);
                    plan = manager.Show();
                }
                catch (Exception err)
                {
                    Host.Say(string.Format("The Revision Manager would not open: {0}", err.Message));
                    return;
                }
                var post = manager.PostCommand;
                var find = manager.FindRequest;
                bool hasPlan = plan != null;
                bool hasPost = !string.IsNullOrEmpty(post);
                bool hasFind = find != null && find.Count > 0;
                if (!hasPlan && !hasPost && !hasFind)
                {
                    Host.Say("Revision Manager closed - nothing changed.");
                    return;
                }

                // One job, not two: the external event holds a single piece of
                // work, and a second Queue would replace the write. The write goes
                // first, so Project Parameters opens on a model that already has
                // the staged changes in it.
                void Job(UIApplication uiapp)
                {
                    if (hasPlan)
                        WriteRevisions(plan);
                    if (hasPost)
                        PsRevWin.PostCommand(uiapp, post);
                    if (hasFind)
                    {
                        // Find clouds on views: open each view with the revision
                        // clouds isolated in it.
                        (int Opened, int Isolated, List<string> Errors) result;
                        try
                        {
                            result = PsRevisions.ShowClouds(uiapp.ActiveUIDocument, find);
                        }
                        catch (Exception err)
                        {
                            result = (0, 0, new List<string> { err.Message });
                        }
                        Host.OnUi(() => Host.Say(PsRevisions.CloudsReport(result.Opened, result.Isolated, result.Errors)));
                    }
                }
                if (Host.Queue(Job))
                {
                    Host.Say(hasPlan ? "Applying the revision changes..." :
                             hasFind ? "Opening the views with the clouds in..." :
                             "Opening Revit's Project Parameters. Add the " +
                             "parameter there, then open the Revision Manager " +
                             "again to map it.");
                }
            }

            /// <summary>On Revit's thread.</summary>
            internal bool WriteRevisions(PsRevisions.Plan plan)
            {
                var (done, errors) = PsRevisions.Write(Host.Doc, plan);
                Host.OnUi(() => RevisionsWritten(done, errors));
                return errors == null || errors.Count == 0;
            }

            internal void RevisionsWritten(int done, List<string> errors)
            {
                errors = errors ?? new List<string>();
                var before = new HashSet<string>(Revisions.Select(revision => Str(revision.ElementKey)), StringComparer.Ordinal);
                Reload();
                // New revisions are on no sheet yet, so with only the used ones
                // showing they would not be there at all. Show every revision, and
                // wash the new ones green down their whole column.
                var fresh = Revisions.Where(revision => !before.Contains(Str(revision.ElementKey)))
                                     .Select(revision => revision.Key).ToList();
                if (fresh.Count > 0)
                {
                    FreshColumns = new HashSet<string>(fresh, StringComparer.Ordinal);
                    if (HideUnused)
                        SetShowAllRevisions(true, quiet: true);
                    PaintPickedColumns();
                }
                string summary = string.Format("{0} revision change{1} applied.", done, Plural(done));
                if (fresh.Count > 0)
                    summary += string.Format(" {0} new revision{1}, in green.", fresh.Count, Plural(fresh.Count));
                if (errors.Count == 0)
                {
                    Host.Say(summary);
                    return;
                }
                Host.Say(string.Format("{0} {1} could not be.", summary, errors.Count));
                new PsUi.Prompt(
                    title: "Revision Manager",
                    headline: string.Format("{0} change{1} Revit would not make.", errors.Count, Plural(errors.Count)),
                    message: summary + " The rest are listed below; the register " +
                             "shows the model as it now is.",
                    detail: string.Join("\n", errors), primary: "Close",
                    themeName: Host.ThemeName, owner: Window).Show();
            }

            /// <summary>Name a new set, then tick it, then Save. Nothing written until then.
            ///
            /// Revit cannot hold an empty View/Sheet Set, so the set only exists
            /// here until it has something in it and Save is pressed.</summary>
            public void NewSet()
            {
                string name = PsUi.AskText("New View/Sheet Set", "What should the new set be called?", "",
                                           Host.ThemeName, Window);
                name = (name ?? "").Trim();
                if (name.Length == 0)
                    return;
                var taken = SheetSets().Keys.Select(one => one.ToLowerInvariant()).ToList();
                if (taken.Contains(name.ToLowerInvariant()))
                {
                    Host.Say(string.Format("There is already a set called \"{0}\" - choose it " +
                                           "from the list to change it.", name));
                    return;
                }
                if (!LeaveDirtySet())
                    return;
                SetName = name;
                SetNew = true;
                Included = new HashSet<string>(StringComparer.Ordinal);
                SetBase = new HashSet<string>(StringComparer.Ordinal);
                FillSetCombo();
                SyncTicks();
                SetShow("all");
                PaintTabStrip();
                Say();
                Host.Say(string.Format("Tick the drawings for \"{0}\", then press Save new set. " +
                                       "Nothing is written to the model until then.", name));
            }

            internal void PaintApply()
            {
                var button = ApplyButton;
                if (button == null)
                    return;
                string text;
                bool lit;
                if (SetNew)
                {
                    text = "Save new set";
                    lit = true;
                }
                else if (Dirty())
                {
                    text = "Apply  •";
                    lit = true;
                }
                else
                {
                    text = "Apply";
                    lit = false;
                }
                try
                {
                    button.Content = text;
                    button.IsEnabled = !string.IsNullOrEmpty(SetName);
                }
                catch (Exception)
                {
                }
                Host.Styled(button, lit ? "ChipButtonOn" : "ChipButton");
            }
        }
    }
}
