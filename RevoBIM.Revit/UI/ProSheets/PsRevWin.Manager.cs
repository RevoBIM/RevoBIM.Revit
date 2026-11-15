using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Threading;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsRevWin
    {
        /// <summary>
        /// The Revision Manager window. Modal from the Document Register: Show() returns the plan to
        /// write, or null. Modeless from its own ribbon button (see RunStandalone).
        ///
        /// Naming notes (deviations from the mechanical mapping, to avoid clashes):
        /// self.grid -> GridControl (a field named Grid would hide the WPF Grid type used here),
        /// self.bands -> BandCanvas (PsRevWin.Bands is the module constant), self._say -> SayCore
        /// (self.say is the public Say).
        /// </summary>
        public partial class RevisionManager
        {
            public PsRevisions.Staging Staging;
            /// <summary>The tool's settings, for the order the columns were dragged into.</summary>
            public PsConfig.Settings Settings;
            // Modeless: Revit stays usable, Apply cannot write where it stands (a modeless window is
            // in no API context), and the window has to outlive the command that opened it. OnApply
            // takes the plan and puts it through an external event; without one the window is modal
            // and Show() hands the plan back to the caller instead.
            public bool Modeless;
            public Action<PsRevisions.Plan> OnApply;
            // Find clouds on views. Opened on its own (modeless), OnFind takes the views and runs the
            // job itself; opened from the register (modal), the views are left in FindRequest and the
            // window closes, so the register can run it.
            public Action<Dictionary<string, List<string>>> OnFind;
            public Dictionary<string, List<string>> FindRequest;
            // Following the selection in Revit: on, and off while a cell is being edited, so a
            // half-typed value is never yanked away.
            public bool Follow;
            internal bool Watching;
            internal Autodesk.Revit.UI.UIApplication Uiapp;
            internal bool Editing;
            internal string Token;
            // The revisions a click in a multi-selection began on: an edit to one of them goes to
            // all of them (see Together).
            internal List<string> Multi;
            // The sheet open in Revit (its number) or null, and whether the list is filtered to it.
            // The view's id spots a change of sheet.
            public string CurrentSheet;
            public bool SheetFilter;
            internal string ViewToken;
            // Every Sheet series cell open (all series showing) or folded to the first one and "+2" -
            // as the user last left it.
            public bool SeriesOpen;
            // () -> the parameters bound to Sheets and Revision Clouds, read from the model by
            // whoever opened this; the column dialog and the settings ask.
            public Func<IEnumerable<PsRevData.BoundParameter>> ParameterReader;
            // A Revit command to run once this window has closed - set by the settings' "Open Project
            // Parameters", which cannot run while a modal window is up.
            public string PostCommand;
            public string ThemeName;
            public PsRevisions.Plan Result;
            public Dictionary<string, string> Filters = new Dictionary<string, string>(StringComparer.Ordinal);
            // field -> the set of values its filter list leaves ticked ("" for a blank cell); a
            // column with no entry is not filtered
            public Dictionary<string, HashSet<string>> Picks = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
            public Dictionary<string, Button> FilterButtons = new Dictionary<string, Button>(StringComparer.Ordinal);
            // True while a filter list is open, so the grid's own keys (Ctrl+Up moves revisions)
            // leave the list's keys alone
            internal bool FilterOpen;
            public Dictionary<string, DataRow> Rows = new Dictionary<string, DataRow>(StringComparer.Ordinal);
            public List<TextBox> SearchBoxes = new List<TextBox>();
            internal Dictionary<string, (Brush Fill, Brush Edge)> Colours;
            internal bool Suspend;

            public Window Window;
            public PsUi.Chrome Chrome;
            internal Window Owner;
            internal IntPtr? OwnerHandle;

            public DataGrid GridControl;
            public Canvas BandCanvas;
            internal string BandSig;
            internal ScrollViewer BandScroller;
            public TextBlock Status;
            public Button ApplyButton;
            public TextBlock DeleteText;
            public RadioButton PerProject;
            public RadioButton PerSheet;
            public TextBox ArcBox;
            public ContentControl ThemeChip;
            public Button SeriesButton;
            public Button FollowButton;
            public Button SheetButton;
            public TextBlock SheetText;

            public DataTable Table;
            public DataView View;

            public RevisionManager(PsRevisions.Staging staging, string themeName = "dark", Window owner = null,
                                   Func<IEnumerable<PsRevData.BoundParameter>> parameterReader = null,
                                   string status = "", IntPtr? ownerHandle = null,
                                   PsConfig.Settings settings = null, bool modeless = false,
                                   Action<PsRevisions.Plan> onApply = null, IEnumerable<string> focus = null,
                                   string currentSheet = null)
            {
                Staging = staging;
                Settings = settings;
                Modeless = modeless;
                OnApply = onApply;
                OnFind = null;
                FindRequest = null;
                Follow = true;
                Watching = false;
                Uiapp = null;
                Editing = false;
                Token = null;
                Multi = null;
                CurrentSheet = currentSheet;
                SheetFilter = false;
                ViewToken = null;
                SeriesOpen = SavedSeriesOpen();
                ParameterReader = parameterReader;
                PostCommand = null;
                ThemeName = themeName;
                Result = null;
                Filters = new Dictionary<string, string>(StringComparer.Ordinal);
                Picks = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
                FilterButtons = new Dictionary<string, Button>(StringComparer.Ordinal);
                FilterOpen = false;
                Rows = new Dictionary<string, DataRow>(StringComparer.Ordinal);
                SearchBoxes = new List<TextBox>();
                Colours = null;
                Suspend = false;

                Window = PsUi.LoadWindow("ProSheetsRevisions.xaml", themeName);
                Chrome = new PsUi.Chrome(Window, () => Cancel());
                // The egg is armed on the main window only. Opened from Pro Sheets (owner given) this is a
                // secondary window and the egg stays on Pro Sheets; opened from its own ribbon button it
                // is the main window, so its logo opens the arcade.
                if (owner == null) PsUi.AttachEgg(Window, () => ThemeName);
                if (owner != null)
                {
                    try
                    {
                        Window.Owner = owner;
                    }
                    catch (Exception)
                    {
                    }
                }
                else if (ownerHandle != null)
                {
                    // Opened from its own ribbon button: owned by Revit's main window, so it never
                    // slips behind Revit.
                    try
                    {
                        new WindowInteropHelper(Window).Owner = ownerHandle.Value;
                    }
                    catch (Exception)
                    {
                    }
                }
                // As wide as the columns need once they are measured, no wider than the screen: see
                // FitWindow. Hidden until then, so it does not open at one width and jump to another.
                Owner = owner;
                OwnerHandle = ownerHandle;
                // A double-click on the bottom bar stretches the window top to bottom - the same
                // toggle as the window's top and bottom edges (PsUi.Chrome.ToggleTall), so either
                // undoes the other.
                if (PsUi.Find(Window, "FooterBar") is UIElement footer)
                {
                    try
                    {
                        footer.MouseLeftButtonDown += FooterClick;
                    }
                    catch (Exception)
                    {
                    }
                }
                try
                {
                    Window.Opacity = 0;
                    Window.ContentRendered += FitWindow;
                }
                catch (Exception)
                {
                    try
                    {
                        Window.Opacity = 1;
                    }
                    catch (Exception)
                    {
                    }
                }
                SetChoices();

                GridControl = PsUi.Find(Window, "RevisionGrid") as DataGrid;
                BandCanvas = PsUi.Find(Window, "RevisionBands") as Canvas;
                BandSig = null;
                BandScroller = null;
                Status = PsUi.Find(Window, "StatusText") as TextBlock;
                ApplyButton = PsUi.Find(Window, "ApplyButton") as Button;
                DeleteText = PsUi.Find(Window, "RevDeleteText") as TextBlock;
                PerProject = PsUi.Find(Window, "RevPerProject") as RadioButton;
                PerSheet = PsUi.Find(Window, "RevPerSheet") as RadioButton;
                ArcBox = PsUi.Find(Window, "RevArcBox") as TextBox;
                ThemeChip = PsUi.Find(Window, "ThemeChip") as ContentControl;
                SeriesButton = PsUi.Find(Window, "RevSeriesToggleButton") as Button;
                FollowButton = PsUi.Find(Window, "RevFollowButton") as Button;
                SheetButton = PsUi.Find(Window, "RevSheetFilterButton") as Button;
                SheetText = PsUi.Find(Window, "RevSheetFilterText") as TextBlock;
                Follow = SavedFollow();

                Table = null;
                View = null;
                MakeTable();
                BuildColumns();
                FillSettings();
                Wire();
                Refill();
                PaintSeriesButton();
                PaintFollowButton();
                PaintSheetButton();
                if (focus != null && focus.Any())
                    Focus(focus);
                SayTheme();
                if (!string.IsNullOrEmpty(status))
                    SayCore(status);
                // The Python warns here when Revit has no RevisionNumberingSequence (2021 and older);
                // Revit 2024 always has it, so that branch is gone.
            }

            // ==================================================================
            // building
            // ==================================================================

            /// <summary>The lists the combo editors offer, as resources on the window.</summary>
            internal void SetChoices()
            {
                try
                {
                    Window.Resources["RevShowChoices"] = new List<string>(PsRevisions.ShowLabels);
                    Window.Resources["RevNumberingChoices"] = new List<string>(Staging.Sequences);
                    foreach (var column in Staging.Columns)
                    {
                        if (column.Kind == "choice")
                        {
                            var choices = new List<string> { "" };
                            choices.AddRange(column.Choices ?? new List<string>());
                            Window.Resources["RevChoices_" + column.Id] = choices;
                        }
                    }
                }
                catch (Exception)
                {
                }
            }

            /// <summary>A fresh table for the staging's columns, extra ones included.</summary>
            internal void MakeTable()
            {
                var table = new DataTable("revisions");
                table.Columns.Add("issued", typeof(bool)).DefaultValue = false;
                foreach (var name in new[]
                         {
                             "key", "pending", "seq", "ord", "numbering", "date",
                             "desc", "issued_to", "issued_by", "show", "used",
                             "sheets_tip", "unplaced", "unplaced_tip", "live", "vis", "fresh", "c_seq",
                             "c_numbering",
                             "c_date", "c_desc", "c_issued", "c_issued_to",
                             "c_issued_by", "c_show", "series", "series_more",
                         })
                    table.Columns.Add(name, typeof(string));
                table.Columns.Add("series_open", typeof(bool)).DefaultValue = false;
                table.Columns.Add("series_items", typeof(object));
                table.Columns.Add("series_head", typeof(object));
                foreach (var column in Staging.Columns)
                {
                    if (column.Kind == "yesno")
                        table.Columns.Add("x_" + column.Id, typeof(bool)).DefaultValue = false;
                    else
                        table.Columns.Add("x_" + column.Id, typeof(string));
                    table.Columns.Add("c_x_" + column.Id, typeof(string));
                }
                try
                {
                    table.ColumnChanged += CellChanged;
                }
                catch (Exception)
                {
                }
                Table = table;
                View = table.DefaultView;
                View.RowFilter = "[vis] = '1'";
                View.Sort = "[ord] ASC";
            }

            /// <summary>After a column is added, changed or removed: new table, new grid columns,
            /// every row again. The searches start empty; a value filter stays on, unless its column
            /// has gone.</summary>
            internal void Rebuild(IEnumerable<string> reselect = null)
            {
                Commit();
                Filters = new Dictionary<string, string>(StringComparer.Ordinal);
                SearchBoxes = new List<TextBox>();
                FilterButtons = new Dictionary<string, Button>(StringComparer.Ordinal);
                var fields = new HashSet<string>(Layout().Select(entry => entry.Field), StringComparer.Ordinal);
                Picks = Picks.Where(pair => fields.Contains(pair.Key))
                             .ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal);
                SetChoices();
                MakeTable();
                BuildColumns();
                Refill(reselect);
            }

            /// <summary>(field, heading, width, kind, column): Revit's columns, then Used on sheets
            /// and Sheet series, then the user's own - in the order the user last dragged them into,
            /// where there is one.</summary>
            internal List<(string Field, string Heading, int Width, string Kind, PsRevData.Column Column)> Layout()
            {
                var output = PsRevWin.Columns
                    .Select(c => (c.Field, c.Heading, c.Width, c.Kind, (PsRevData.Column)null))
                    .ToList();
                foreach (var column in PsRevData.GroupOrder(Staging.Columns))
                {
                    string kind = column.Kind == "yesno" ? "check"
                        : column.Kind == "choice" ? "RevChoices_" + column.Id : "text";
                    output.Add(("x_" + column.Id, column.Name,
                                CustomWidths.TryGetValue(column.Kind ?? "", out var w) ? w : 160, kind, column));
                }
                var byField = new Dictionary<string, (string, string, int, string, PsRevData.Column)>(StringComparer.Ordinal);
                foreach (var entry in output)
                    byField[entry.Item1] = entry;
                var saved = SavedOrder();
                var ordered = PlaceAfter(ColumnOrder(output.Select(entry => entry.Item1).ToList(), saved),
                                         saved, "unplaced", "series");
                return KeepGroups(ordered, GroupOf).Select(field => byField[field])
                    .Select(e => (e.Item1, e.Item2, e.Item3, e.Item4, e.Item5)).ToList();
            }

            /// <summary>The Issued To / Method group a grid field belongs to, or "".</summary>
            internal string GroupOf(string field)
            {
                if (!Str(field).StartsWith("x_", StringComparison.Ordinal))
                    return "";
                var column = Staging.Column(field.Substring(2));
                if (column == null || (column.Group != PsRevData.IssuedTo && column.Group != PsRevData.Method))
                    return "";
                return column.Group;
            }

            // ------------------------------------------------------- column order
            internal List<string> SavedOrder()
            {
                if (Settings == null)
                    return new List<string>();
                try
                {
                    return (Settings.Text("rev_column_order", "") ?? "").Split(',')
                        .Where(one => one.Length > 0).ToList();
                }
                catch (Exception)
                {
                    return new List<string>();
                }
            }

            /// <summary>A heading dragged somewhere else: remember the order, per machine, for the
            /// next time the manager opens.</summary>
            internal void ColumnMoved(object sender, DataGridColumnEventArgs args)
            {
                if (Settings == null || GridControl == null)
                    return;
                try
                {
                    var columns = GridControl.Columns.OrderBy(column => column.DisplayIndex).ToList();
                    var fields = columns.Select(column => column.SortMemberPath ?? "").ToList();
                    Settings.Set("rev_column_order", string.Join(",", fields.Where(field => field.Length > 0)));
                    Settings.Save();
                }
                catch (Exception)
                {
                }
            }

            // ------------------------------------------------- sheet series, open
            internal bool SavedSeriesOpen()
            {
                if (Settings == null)
                    return true;
                try
                {
                    return Settings.Flag("rev_series_open", true);
                }
                catch (Exception)
                {
                    return true;
                }
            }

            /// <summary>Expand or collapse every Sheet series cell at once, and keep the choice for
            /// next time. A single cell still folds on its own click.</summary>
            internal void ToggleSeries(object sender, RoutedEventArgs args)
            {
                Commit();
                SeriesOpen = !SeriesOpen;
                Suspend = true;
                try
                {
                    foreach (var row in Rows.Values)
                        row["series_open"] = SeriesOpen;
                }
                finally
                {
                    Suspend = false;
                }
                if (Settings != null)
                {
                    try
                    {
                        Settings.Set("rev_series_open", SeriesOpen ? "1" : "0");
                        Settings.Save();
                    }
                    catch (Exception)
                    {
                    }
                }
                PaintSeriesButton();
                SayCore(string.Format("Every revision's sheet series {0}.",
                                      SeriesOpen ? "listed in full" : "folded to the first"));
            }

            internal void PaintSeriesButton()
            {
                PsUi.SetContent(SeriesButton, SeriesOpen ? "Collapse series" : "Expand series");
            }

            // --------------------------------------------- following the selection
            internal bool SavedFollow()
            {
                if (Settings == null)
                    return true;
                try
                {
                    return Settings.Flag("rev_follow_selection", true);
                }
                catch (Exception)
                {
                    return true;
                }
            }

            /// <summary>
            /// Follow what is selected in Revit, through Idling. Idling is raised on Revit's own main
            /// thread inside a valid API context, which is the one place a modeless window is allowed
            /// to read the model. Reading the selection straight from a window handler is what throws
            /// "Attempting to modify the model outside of transaction" and its read-side cousins.
            /// </summary>
            public bool WatchSelection(Autodesk.Revit.UI.UIApplication uiapp)
            {
                Uiapp = uiapp;
                try
                {
                    uiapp.Idling += Idling;
                    Watching = true;
                }
                catch (Exception)
                {
                    Watching = false;
                }
                try
                {
                    Window.Closed += OnClosed;
                }
                catch (Exception)
                {
                }
                return Watching;
            }

            /// <summary>Hand Idling back. A handler left subscribed after its window has gone is a
            /// handler Revit calls into a dead window.</summary>
            public void StopWatching(object sender = null, EventArgs args = null)
            {
                if (!Watching)
                    return;
                Watching = false;
                try
                {
                    Uiapp.Idling -= Idling;
                }
                catch (Exception)
                {
                }
            }

            internal void OnClosed(object sender, EventArgs args)
            {
                StopWatching();
            }

            /// <summary>Revit is idle, on its main thread, in a valid API context: the moment to see
            /// which sheet is open, and what is selected.</summary>
            internal void Idling(object sender, Autodesk.Revit.UI.Events.IdlingEventArgs args)
            {
                Autodesk.Revit.UI.UIDocument uidoc;
                try
                {
                    uidoc = ((Autodesk.Revit.UI.UIApplication)sender).ActiveUIDocument;
                }
                catch (Exception)
                {
                    return;
                }
                if (uidoc == null)
                    return;
                if (!Editing)
                    TrackSheet(uidoc);
                if (!Follow || Editing)
                    return;
                string token = PsRevisions.SelectionToken(uidoc);
                if (token == Token)
                    return;
                Token = token;
                if (string.IsNullOrEmpty(token))
                    return;
                List<string> keys;
                try
                {
                    keys = PsRevisions.SelectedRevisionKeys(uidoc);
                }
                catch (Exception)
                {
                    return;
                }
                GoTo(keys);
            }

            /// <summary>Open on these revisions: selected, and the first brought into the middle of
            /// the grid. A revision cloud picked before opening, or Edit revision on the Document
            /// Register.</summary>
            public bool Focus(IEnumerable<string> keys)
            {
                var list = (keys ?? Enumerable.Empty<string>()).Select(one => Str(one))
                    .Where(key => Staging.Order.Contains(key)).ToList();
                if (list.Count == 0)
                    return false;
                Select(list);
                CentreOn(list[0]);
                SayCore(string.Format("Showing {0}.",
                    string.Join(", ", list.Take(6).Select(key => "revision " + Seq(Staging.StagedSequence(key)))) +
                    (list.Count > 6 ? string.Format(Inv, " and {0} more", list.Count - 6) : "")));
                return true;
            }

            // ------------------------------------------------- the current sheet
            /// <summary>The sheet number the list is filtered to, or null.</summary>
            internal string FilterSheet()
            {
                return SheetFilter && !string.IsNullOrEmpty(CurrentSheet) ? CurrentSheet : null;
            }

            /// <summary>Which sheet is open in Revit. From Idling: when the open view changes, light
            /// or grey the button, and re-filter if it is on.</summary>
            public void TrackSheet(Autodesk.Revit.UI.UIDocument uidoc)
            {
                Autodesk.Revit.DB.View view;
                string token;
                try
                {
                    view = uidoc.ActiveView;
                    token = PsModel.EidValue(view.Id).ToString(Inv);
                }
                catch (Exception)
                {
                    return;
                }
                if (token == ViewToken)
                    return;
                ViewToken = token;
                string sheet = PsRevisions.SheetNumberOf(view);
                if (sheet == CurrentSheet)
                    return;
                CurrentSheet = sheet;
                PaintSheetButton();
                if (SheetFilter)
                {
                    Refresh();
                    SayCore(!string.IsNullOrEmpty(sheet)
                        ? string.Format("Revisions on sheet {0}.", sheet)
                        : "No sheet open in Revit - showing every revision. The filter comes back on the next sheet you open.");
                }
            }

            internal void ToggleSheetFilter(object sender, RoutedEventArgs args)
            {
                if (string.IsNullOrEmpty(CurrentSheet))
                    return;
                Commit();
                SheetFilter = !SheetFilter;
                PaintSheetButton();
                Refresh();
                int count = Staging.Visible(Filters, Picks, FilterSheet()).Count;
                SayCore(SheetFilter
                    ? string.Format(Inv, "{0} revision{1} on sheet {2}. It follows you as you change sheets.",
                                    count, count == 1 ? "" : "s", CurrentSheet)
                    : "Showing every revision.");
            }

            /// <summary>Grey with no sheet open, lit with one, solid orange while the list is
            /// filtered to it.</summary>
            internal void PaintSheetButton()
            {
                var button = SheetButton;
                if (button == null)
                    return;
                bool onSheet = !string.IsNullOrEmpty(CurrentSheet);
                try
                {
                    button.IsEnabled = onSheet;
                    button.Opacity = onSheet ? 1.0 : 0.5;
                    button.SetResourceReference(FrameworkElement.StyleProperty,
                        onSheet && SheetFilter ? "SwitchButtonOn" : (onSheet ? "ChipButtonOn" : "ChipButton"));
                    button.ToolTip = onSheet
                        ? string.Format("Show only the revisions on sheet {0}, the sheet open in Revit. Follows you as you change sheets.",
                                        CurrentSheet)
                        : "Open a sheet in Revit to filter to its revisions.";
                }
                catch (Exception)
                {
                }
                PsUi.SetText(SheetText, onSheet && SheetFilter
                    ? string.Format("Filtered to sheet {0}", CurrentSheet)
                    : "Filter revisions on current sheet");
            }

            // ------------------------------------------- one value, many revisions
            internal static T Ancestor<T>(object node) where T : class
            {
                for (int step = 0; step < 16; step++)
                {
                    if (node == null)
                        return null;
                    if (node is T found)
                        return found;
                    try
                    {
                        node = VisualTreeHelper.GetParent((DependencyObject)node);
                    }
                    catch (Exception)
                    {
                        node = node is FrameworkContentElement content ? content.Parent
                            : node is FrameworkElement element ? element.Parent : null;
                    }
                }
                return null;
            }

            internal bool IsTick(string field)
            {
                if (field == "issued")
                    return true;
                if (field.StartsWith("x_", StringComparison.Ordinal))
                {
                    var column = Staging.Column(field.Substring(2));
                    return column != null && column.Kind == "yesno";
                }
                return false;
            }

            /// <summary>
            /// A press inside a selection of several revisions. Noted first, before the grid narrows
            /// the selection to the one row: an edit begun here goes to every one of them (see
            /// Together). For a text or a list cell the press is taken over and the editor opened
            /// directly, so the rows stay selected - visibly - while it is typed. A tick handles its
            /// own press; the rows are selected again after.
            /// </summary>
            internal void GridPress(object sender, MouseButtonEventArgs args)
            {
                Multi = null;
                if (PsUi.CtrlDown() || PsUi.ShiftDown())
                    return;
                object source;
                try
                {
                    source = args.OriginalSource;
                }
                catch (Exception)
                {
                    return;
                }
                var cell = Ancestor<DataGridCell>(source);
                var row = Ancestor<DataGridRow>(source);
                if (cell == null || row == null)
                    return;
                string key, field;
                try
                {
                    key = Str(((DataRowView)row.Item).Row["key"]);
                    field = cell.Column.SortMemberPath ?? "";
                }
                catch (Exception)
                {
                    return;
                }
                var keys = Selected();
                if (keys.Count < 2 || !keys.Contains(key) || !Together(field))
                    return;
                Multi = new List<string>(keys);
                if (IsTick(field) || cell.IsEditing)
                    return;
                try
                {
                    args.Handled = true;
                    GridControl.CurrentCell = new DataGridCellInfo(row.Item, cell.Column);
                    GridControl.BeginEdit();
                }
                catch (Exception)
                {
                }
            }

            internal List<string> Others(string key, string field)
            {
                if (Multi == null || Multi.Count == 0 || !Multi.Contains(key) || !Together(field))
                    return new List<string>();
                return Multi.Where(one => one != key).ToList();
            }

            /// <summary>Copy one revision's newly staged value onto the others selected with it, and
            /// show it in their rows.</summary>
            internal void Spread(string key, string field, List<string> others)
            {
                List<string> changed, refusals;
                PsRevData.Column column = null;
                if (field.StartsWith("x_", StringComparison.Ordinal))
                {
                    string columnId = field.Substring(2);
                    column = Staging.Column(columnId);
                    string value = PsRevisions.Staging.CustomValue(Staging.Entries[key], column);
                    (changed, refusals) = Staging.SetCustomMany(
                        others, columnId, column.Kind == "yesno" ? (object)(value == "1") : value);
                }
                else
                {
                    Staging.Entries[key].Fields.TryGetValue(field, out var value);
                    (changed, refusals) = Staging.SetFieldMany(others, field, value);
                }
                Suspend = true;
                try
                {
                    foreach (var other in changed)
                    {
                        if (!Rows.TryGetValue(other, out var row) || row == null)
                            continue;
                        if (field.StartsWith("x_", StringComparison.Ordinal))
                        {
                            string stored = PsRevisions.Staging.CustomValue(Staging.Entries[other], column);
                            row[field] = column.Kind == "yesno" ? (object)(stored == "1") : stored;
                        }
                        else
                        {
                            row[field] = Db(Staging.Entries[other].Fields.TryGetValue(field, out var v) ? v : null);
                        }
                    }
                }
                finally
                {
                    Suspend = false;
                }
                var keep = new List<string>(Multi ?? new List<string>());

                void Reselect()
                {
                    Select(keep);
                }

                try
                {
                    Window.Dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(Reselect));
                }
                catch (Exception)
                {
                    Reselect();
                }
                int total = changed.Count + 1;
                SayCore(string.Format(Inv, "Set on {0} revisions.{1}",
                                      total, refusals.Count > 0 ? " " + string.Join(" ", refusals) : ""));
            }

            /// <summary>Take the list to the first of these revisions that it holds.</summary>
            public bool GoTo(IEnumerable<string> keys)
            {
                string target = JumpTarget(keys, Staging.Order, Selected());
                if (target == null)
                    return false;
                Select(new List<string> { target }, scroll: true);
                Staging.Entries.TryGetValue(target, out var entry);
                int? sequence = Staging.StagedSequence(target);
                string desc = entry != null ? Str(entry.Fields.TryGetValue("desc", out var d) ? d : null) : "";
                SayCore(string.Format("Selected in Revit: revision {0}{1}.",
                    sequence.HasValue && sequence.Value != 0 ? sequence.Value.ToString(Inv) : "?",
                    desc.Length > 0 ? " - " + desc : ""));
                return true;
            }

            internal void ToggleFollow(object sender, RoutedEventArgs args)
            {
                Follow = !Follow;
                if (Settings != null)
                {
                    try
                    {
                        Settings.Set("rev_follow_selection", Follow ? "1" : "0");
                        Settings.Save();
                    }
                    catch (Exception)
                    {
                    }
                }
                Token = null;
                PaintFollowButton();
                SayCore(string.Format("Picking a revision cloud in Revit {0}.",
                    Follow ? "takes the list to its revision" : "no longer moves the list"));
            }

            /// <summary>Only of use while Revit is usable, so it is hidden when modal.</summary>
            internal void PaintFollowButton()
            {
                if (FollowButton == null)
                    return;
                PsUi.SetVisible(FollowButton, Modeless);
                try
                {
                    FollowButton.Content = Follow ? "Following selection" : "Not following selection";
                    FollowButton.SetResourceReference(FrameworkElement.StyleProperty,
                                                      Follow ? "ChipButtonOn" : "ChipButton");
                }
                catch (Exception)
                {
                }
            }

            internal void ResetOrder(object sender, RoutedEventArgs args)
            {
                if (Settings != null)
                {
                    try
                    {
                        Settings.Set("rev_column_order", "");
                        Settings.Save();
                    }
                    catch (Exception)
                    {
                    }
                }
                Rebuild(Selected());
                SayCore("Columns back in their first order.");
            }

            /// <summary>Every fitting column back to its text. Dragging a heading's edge pins that
            /// column to a pixel width; this hands it back, and takes in anything typed since the
            /// grid was built.</summary>
            internal void FitColumns(object sender, RoutedEventArgs args)
            {
                Commit();
                if (GridControl == null)
                    return;
                var wide = new Dictionary<string, int>(StringComparer.Ordinal);
                foreach (var entry in Layout())
                    wide[entry.Field] = entry.Width;
                int fitted = 0;
                foreach (var column in GridControl.Columns)
                {
                    string field = column.SortMemberPath ?? "";
                    if (!Fits(wide.TryGetValue(field, out var width) ? width : 0))
                        continue;
                    try
                    {
                        column.Width = DataGridLength.Auto;
                        fitted += 1;
                    }
                    catch (Exception)
                    {
                    }
                }
                SayCore(string.Format(Inv, "{0} column{1} fitted to their text.", fitted, fitted == 1 ? "" : "s"));
            }

            internal void BuildColumns()
            {
                if (GridControl == null)
                    return;
                try
                {
                    GridControl.Columns.Clear();
                    GridControl.ItemsSource = View;
                }
                catch (Exception)
                {
                    return;
                }
                try
                {
                    GridControl.RowStyle = FreshRowStyleCore();
                }
                catch (Exception)
                {
                }
                var layout = Layout();
                BandSig = null;
                foreach (var (field, title, width, kind, extra) in layout)
                {
                    var column = new DataGridTemplateColumn();
                    // Read back in BeginningEdit to know which field is being edited; nothing sorts
                    // on it, sorting is off.
                    column.SortMemberPath = field;
                    // seq: what the Change column used to say - New, Edited, Delete, Merge into 3 -
                    // now only here.
                    string tip = field == "used" ? " ToolTip=\"{Binding sheets_tip}\""
                        : field == "seq" ? " ToolTip=\"{Binding pending}\"" : "";
                    column.CellTemplate = (DataTemplate)XamlReader.Parse(string.Format(
                        ShowTemplate, Presentation, field, tip, string.Format(TextStyle, field)));
                    if (kind == "series")
                    {
                        column.IsReadOnly = true;
                        column.CellTemplate = (DataTemplate)XamlReader.Parse(string.Format(SeriesTemplate, Presentation));
                    }
                    else if (kind == "unplaced")
                    {
                        column.IsReadOnly = true;
                        column.CellTemplate = (DataTemplate)XamlReader.Parse(string.Format(UnplacedTemplate, Presentation));
                    }
                    else if (kind == "used")
                    {
                        // Red where nothing carries the revision, blue where something does - the
                        // first thing to look at before a delete or a merge.
                        column.IsReadOnly = true;
                        column.CellTemplate = (DataTemplate)XamlReader.Parse(string.Format(UsedTemplate, Presentation));
                    }
                    else if (kind == "read")
                    {
                        column.IsReadOnly = true;
                    }
                    else if (kind == "text")
                    {
                        column.CellEditingTemplate = (DataTemplate)XamlReader.Parse(
                            string.Format(TextEditTemplate, Presentation, field));
                    }
                    else if (kind == "check")
                    {
                        column.CellTemplate = (DataTemplate)XamlReader.Parse(
                            string.Format(CheckTemplate, Presentation, field));
                    }
                    else
                    {
                        column.CellEditingTemplate = (DataTemplate)XamlReader.Parse(
                            string.Format(ComboEditTemplate, Presentation, field, kind));
                    }
                    if (Fits(width))
                    {
                        // Auto, not SizeToCells: the heading - its title, its search box and its list
                        // button - counts as well as the values.
                        column.Width = DataGridLength.Auto;
                        column.MinWidth = AutoMin;
                        column.MaxWidth = AutoMax;
                    }
                    else if (width != 0)
                    {
                        column.Width = new DataGridLength(width);
                    }
                    else
                    {
                        column.Width = new DataGridLength(1, DataGridLengthUnitType.Star);
                        // The floor it keeps when the window is narrower than the columns: then the
                        // grid scrolls rather than squeezing it.
                        column.MinWidth = DescriptionMin;
                    }
                    column.Header = Header(field, title, extra);
                    GridControl.Columns.Add(column);
                }
                GridControl.Columns.Add(PlusColumn());
                // The first column (Sequence, unless dragged) stays put while the rest scroll, so a
                // row can still be told apart on a small screen.
                try
                {
                    GridControl.FrozenColumnCount = 1;
                }
                catch (Exception)
                {
                }
            }

            /// <summary>The last column: nothing in it but a green + in its heading.</summary>
            internal DataGridTemplateColumn PlusColumn()
            {
                var column = new DataGridTemplateColumn();
                column.IsReadOnly = true;
                column.Width = new DataGridLength(44);
                column.CanUserResize = false;
                column.CanUserReorder = false;
                column.CellTemplate = (DataTemplate)XamlReader.Parse(string.Format(
                    "<DataTemplate xmlns=\"{0}\"><TextBlock/></DataTemplate>", Presentation));
                var button = new Button();
                button.SetResourceReference(FrameworkElement.StyleProperty, "IconButton");
                button.ToolTip = "Add a column of your own";
                button.Content = XamlReader.Parse(string.Format(PlusIcon, Presentation));
                button.Click += (s, a) => AddColumn(s, a);
                column.Header = button;
                return column;
            }

            // ------------------------------------------------- the window's height
            /// <summary>A double-click on the bottom bar - not on its buttons - stretches the window
            /// to the full height of its screen, and a second one puts it back.</summary>
            internal void FooterClick(object sender, MouseButtonEventArgs args)
            {
                try
                {
                    if (args.ClickCount != 2)
                        return;
                    if (Ancestor<Button>(args.OriginalSource) != null)
                        return;
                }
                catch (Exception)
                {
                    return;
                }
                bool? stretched = Chrome.ToggleTall();
                try
                {
                    args.Handled = true;
                }
                catch (Exception)
                {
                }
                if (stretched != null)
                {
                    SayCore(stretched.Value
                        ? "Stretched to the full height of the screen - double-click the bar, or the top or bottom edge, again to put it back."
                        : "Back to its own height.");
                }
            }

            // ------------------------------------------------- the window's width
            /// <summary>Once the columns have measured themselves: the window as wide as they need -
            /// Description at the width of its longest text - and no wider than the screen, where the
            /// grid's own scroll bar takes the rest. Shown either way.</summary>
            internal void FitWindow(object sender = null, EventArgs args = null)
            {
                try
                {
                    Window.ContentRendered -= FitWindow;
                }
                catch (Exception)
                {
                }
                try
                {
                    double @fixed = GridControl.Columns.Where(column => !column.Width.IsStar)
                        .Sum(column => column.ActualWidth);
                    double extra = Window.ActualWidth - GridControl.ActualWidth + GridSlack;
                    PsUi.FitWidth(Window, NeededWidth(@fixed, DescriptionWidthCore(), extra), Owner, OwnerHandle);
                }
                catch (Exception)
                {
                }
                finally
                {
                    try
                    {
                        Window.Opacity = 1;
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            /// <summary>The Python _description_width (Core: the module has DescriptionWidth).</summary>
            internal int DescriptionWidthCore()
            {
                var texts = Staging.Entries.Values
                    .Select(entry => Str(entry.Fields.TryGetValue("desc", out var d) ? d : null)).ToList();
                return DescriptionWidth(texts);
            }

            /// <summary>Which band a grid field sits under: Standard for Revit's own fields and the
            /// manager's derived ones, then the user's columns by their kind. The + column has
            /// none.</summary>
            internal string BandOf(string field)
            {
                field = field ?? "";
                if (PsRevWin.Columns.Any(entry => entry.Field == field))
                    return Standard;
                if (field.StartsWith("x_", StringComparison.Ordinal))
                {
                    var column = Staging.Column(field.Substring(2));
                    if (column == null)
                        return "";
                    return !string.IsNullOrEmpty(column.Group) ? column.Group : Custom;
                }
                return "";
            }

            /// <summary>Draw the band strip from the columns as they stand. Called on every layout
            /// pass, so it does nothing unless a width, the order or the scroll has changed since last
            /// time.</summary>
            internal void PaintBands(object sender = null, EventArgs args = null)
            {
                if (BandCanvas == null || GridControl == null)
                    return;
                List<(string Field, double Width)> pairs;
                double start;
                try
                {
                    var columns = GridControl.Columns.Where(column => column.Visibility == Visibility.Visible)
                        .OrderBy(column => column.DisplayIndex).ToList();
                    pairs = columns.Select(column => (column.SortMemberPath ?? "", column.ActualWidth)).ToList();
                    var scroller = BandScroller ?? Scroller();
                    BandScroller = scroller;
                    double offset = scroller != null ? scroller.HorizontalOffset : 0.0;
                    double header = GridControl.RowHeaderActualWidth;
                    start = (double.IsNaN(header) ? 0.0 : header) - offset;
                }
                catch (Exception)
                {
                    return;
                }
                string signature = string.Join(";", pairs.Select(pair =>
                                       pair.Field + ":" + ((long)Math.Round(pair.Width)).ToString(Inv))) +
                                   "|" + ((long)Math.Round(start)).ToString(Inv);
                if (signature == BandSig)
                    return;
                BandSig = signature;
                try
                {
                    BandCanvas.Children.Clear();
                }
                catch (Exception)
                {
                    return;
                }
                foreach (var (band, left, width) in BandRuns(pairs, BandOf))
                {
                    try
                    {
                        BandCanvas.Children.Add(BandStrip(band, start + left, width));
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }

            internal Border BandStrip(string band, double left, double width)
            {
                var (name, brush, adds) = BandInfo.TryGetValue(band, out var info) ? info : ("", "BlueBrush", false);
                var strip = new Border();
                strip.SetResourceReference(Border.BackgroundProperty, brush);
                strip.CornerRadius = new CornerRadius(3, 3, 0, 0);
                strip.Width = Math.Max(0.0, width - 2);
                strip.Height = 22;
                strip.ToolTip = name;
                Canvas.SetLeft(strip, left + 1);
                Canvas.SetTop(strip, 2);
                var holder = new Grid();
                var label = new TextBlock();
                label.Text = name.ToUpperInvariant();
                label.FontWeight = FontWeights.Bold;
                label.FontSize = 11;
                label.TextTrimming = TextTrimming.CharacterEllipsis;
                label.HorizontalAlignment = HorizontalAlignment.Center;
                label.VerticalAlignment = VerticalAlignment.Center;
                label.Margin = new Thickness(4, 0, adds ? 24 : 4, 0);
                label.SetResourceReference(TextBlock.ForegroundProperty, "OnOrangeBrush");
                holder.Children.Add(label);
                if (adds)
                {
                    var add = new Button();
                    add.SetResourceReference(FrameworkElement.StyleProperty, "IconButton");
                    add.Width = 20;
                    add.Height = 18;
                    add.HorizontalAlignment = HorizontalAlignment.Right;
                    add.Margin = new Thickness(0, 0, 2, 0);
                    add.Content = XamlReader.Parse(string.Format(PlusIcon, Presentation));
                    add.ToolTip = string.Format("Add a {0} column", name);
                    add.Click += MakeAddToGroup(band == Custom ? "" : band);
                    holder.Children.Add(add);
                }
                strip.Child = holder;
                return strip;
            }

            internal RoutedEventHandler MakeAddToGroup(string group)
            {
                return (sender, args) => AddColumn(sender, args, group);
            }

            internal StackPanel Header(string field, string title, PsRevData.Column extra = null)
            {
                var panel = new StackPanel();
                panel.Orientation = Orientation.Vertical;
                var heading = new TextBlock();
                heading.Text = title;
                if (extra == null)
                {
                    panel.Children.Add(heading);
                }
                else
                {
                    // An extra column: its name, where it is pushed, and a pencil to rename it, map it
                    // or remove it.
                    var row = new StackPanel();
                    row.Orientation = Orientation.Horizontal;
                    heading.SetResourceReference(TextBlock.ForegroundProperty, "GreenBrush");
                    row.Children.Add(heading);
                    var edit = new Button();
                    edit.SetResourceReference(FrameworkElement.StyleProperty, "IconButton");
                    edit.Width = 20;
                    edit.Height = 18;
                    edit.Margin = new Thickness(4, 0, 0, 0);
                    edit.Content = XamlReader.Parse(string.Format(PencilIcon, Presentation));
                    edit.ToolTip = string.Format("Rename, change the choices, map to a parameter, or remove \"{0}\"",
                                                 extra.Name);
                    edit.Click += MakeEditColumn(extra.Id);
                    row.Children.Add(edit);
                    panel.Children.Add(row);
                    panel.ToolTip = string.Format("{0} column{1}",
                        PsRevData.KindLabels.TryGetValue(extra.Kind ?? "", out var label) ? label : "",
                        extra.Pushed
                            ? string.Format(" - pushed to \"{0}\" on {1}", extra.Parameter,
                                            extra.Target == "sheets" ? "sheets" : "revision clouds")
                            : " - kept in the model");
                }
                // The search box, and beside it the list of every value in the column - Excel's
                // filter, as on the Document Register.
                var line = new Grid();
                line.Margin = new Thickness(0, 4, 4, 0);
                foreach (var width in new double?[] { null, 30 })
                {
                    var definition = new ColumnDefinition();
                    if (width.HasValue)
                        definition.Width = new GridLength(width.Value);
                    line.ColumnDefinitions.Add(definition);
                }
                var box = new TextBox();
                box.SetResourceReference(FrameworkElement.StyleProperty, "ColumnSearchBox");
                box.ToolTip = "Search this column";
                box.Margin = new Thickness(0, 0, 3, 0);
                box.TextChanged += MakeSearch(field);
                Filters[field] = "";
                Grid.SetColumn(box, 0);
                line.Children.Add(box);
                SearchBoxes.Add(box);
                line.Children.Add(FilterButton(field));
                panel.Children.Add(line);
                return panel;
            }

            // ------------------------------------------------------ value filters
            /// <summary>The filter button under a heading A Button
            /// handles its own press, so the heading never takes it as the start of a drag.</summary>
            internal Button FilterButton(string field)
            {
                var button = new Button();
                button.Height = 20;
                button.Click += MakeFilterOpen(field, button);
                Grid.SetColumn(button, 1);
                FilterButtons[field] = button;
                PaintFilterButton(field);
                return button;
            }

            internal void PaintFilterButton(string field)
            {
                if (!FilterButtons.TryGetValue(field, out var button) || button == null)
                    return;
                Picks.TryGetValue(field, out var allowed);
                bool on = allowed != null;
                try
                {
                    button.SetResourceReference(FrameworkElement.StyleProperty, on ? "FilterButtonOn" : "FilterButton");
                    button.Content = on ? "▾" + allowed.Count.ToString(Inv) : "▾";
                    button.ToolTip = on
                        ? string.Format(Inv, "Showing {0} value{1} - click to change", allowed.Count,
                                        allowed.Count == 1 ? "" : "s")
                        : "Pick which values to show";
                }
                catch (Exception)
                {
                }
            }

            internal RoutedEventHandler MakeFilterOpen(string field, Button button)
            {
                return (sender, args) => OpenFilter(field, button);
            }

            /// <summary>How a value reads in the list: Sheet series as its coloured chip, the same as
            /// in the cell; everything else as text.</summary>
            internal UIElement ValueChip(string field, string value)
            {
                var text = new TextBlock();
                text.Text = value;
                text.VerticalAlignment = VerticalAlignment.Center;
                if (field != "series" || value == PsRegister.Blanks)
                    return text;
                if (Colours == null)
                    Colours = SeriesBrushes();
                if (!Colours.TryGetValue(value, out var colours) || colours.Fill == null)
                    return text;
                var chip = new Border();
                chip.Background = colours.Fill;
                chip.BorderBrush = colours.Edge;
                chip.BorderThickness = new Thickness(1);
                chip.CornerRadius = new CornerRadius(3);
                chip.Padding = new Thickness(6, 0, 6, 0);
                text.FontSize = 11;
                chip.Child = text;
                return chip;
            }

            /// <summary>The list: search, All / None, Tick / Untick selected, every value with a
            /// tick, OK. Ctrl- and Shift-click select several values; ticking one of them, or Space,
            /// ticks them all.</summary>
            internal void OpenFilter(string field, Button button)
            {
                Commit();
                var choices = Staging.Choices(field, Filters, Picks);
                Picks.TryGetValue(field, out var allowed);

                string Raw(string value)
                {
                    return value == PsRegister.Blanks ? "" : value;
                }

                var popup = new Popup();
                popup.PlacementTarget = button;
                popup.Placement = PlacementMode.Bottom;
                popup.StaysOpen = false;
                popup.AllowsTransparency = true;

                var shell = new Border();
                shell.SetResourceReference(Border.BackgroundProperty, "CardBg");
                shell.SetResourceReference(Border.BorderBrushProperty, "EdgeBrush");
                shell.BorderThickness = new Thickness(1);
                shell.CornerRadius = new CornerRadius(4);
                shell.Padding = new Thickness(8);
                shell.MinWidth = 230;
                shell.MaxWidth = 340;
                var panel = new StackPanel();
                shell.Child = panel;

                var search = new TextBox();
                search.SetResourceReference(FrameworkElement.StyleProperty, "ColumnSearchBox");
                search.Tag = "Search";
                search.Margin = new Thickness(0, 0, 0, 6);
                panel.Children.Add(search);

                var bulk = new StackPanel();
                bulk.Orientation = Orientation.Horizontal;
                bulk.Margin = new Thickness(0, 0, 0, 6);
                var chips = new List<Button>();
                foreach (var (label, tip) in new[]
                         {
                             ("All", "Tick every value listed"),
                             ("None", "Untick every value listed"),
                             ("Tick selected", "Tick the highlighted values"),
                             ("Untick selected", "Untick the highlighted values"),
                         })
                {
                    var chip = new Button();
                    chip.Content = label;
                    chip.ToolTip = tip;
                    chip.SetResourceReference(FrameworkElement.StyleProperty, "ChipButton");
                    chip.Margin = new Thickness(0, 0, 5, 0);
                    bulk.Children.Add(chip);
                    chips.Add(chip);
                }
                Button every = chips[0], none = chips[1], tick = chips[2], untick = chips[3];
                panel.Children.Add(bulk);

                var listing = new ListBox();
                listing.SelectionMode = SelectionMode.Extended;
                listing.MaxHeight = 280;
                listing.MinHeight = 60;
                panel.Children.Add(listing);
                var boxes = new List<(string Value, ListBoxItem Item, CheckBox Box)>();
                foreach (var value in choices)
                {
                    var item = new ListBoxItem();
                    var row = new StackPanel();
                    row.Orientation = Orientation.Horizontal;
                    var box = new CheckBox();
                    box.IsChecked = allowed == null || allowed.Contains(Raw(value));
                    box.Margin = new Thickness(0, 0, 6, 0);
                    box.VerticalAlignment = VerticalAlignment.Center;
                    row.Children.Add(box);
                    row.Children.Add(ValueChip(field, value));
                    item.Content = row;
                    listing.Items.Add(item);
                    boxes.Add((value, item, box));
                }
                if (boxes.Count == 0)
                {
                    var empty = new TextBlock();
                    empty.Text = "Nothing showing to filter.";
                    empty.Margin = new Thickness(4);
                    panel.Children.Add(empty);
                }

                var hint = new TextBlock();
                hint.SetResourceReference(FrameworkElement.StyleProperty, "MutedText");
                hint.TextWrapping = TextWrapping.Wrap;
                hint.Margin = new Thickness(0, 6, 0, 0);
                hint.Text = "Ctrl or Shift + click to select several values, then tick one of them (or press Space) to tick them all.";
                panel.Children.Add(hint);

                var actions = new StackPanel();
                actions.Orientation = Orientation.Horizontal;
                actions.HorizontalAlignment = HorizontalAlignment.Right;
                actions.Margin = new Thickness(0, 8, 0, 0);
                var ok = new Button();
                ok.Content = "OK";
                ok.MinWidth = 64;
                ok.SetResourceReference(FrameworkElement.StyleProperty, "PrimaryButton");
                ok.Margin = new Thickness(0, 0, 6, 0);
                var cancel = new Button();
                cancel.Content = "Cancel";
                cancel.MinWidth = 64;
                cancel.SetResourceReference(FrameworkElement.StyleProperty, "ChipButton");
                actions.Children.Add(ok);
                actions.Children.Add(cancel);
                panel.Children.Add(actions);
                popup.Child = shell;

                Panel holder = null;

                List<(ListBoxItem Item, CheckBox Box)> Shown()
                {
                    return boxes.Where(one => one.Item.Visibility == Visibility.Visible)
                        .Select(one => (one.Item, one.Box)).ToList();
                }

                List<(ListBoxItem Item, CheckBox Box)> SelectedPairs()
                {
                    return Shown().Where(pair => pair.Item.IsSelected).ToList();
                }

                void SetAll(List<(ListBoxItem Item, CheckBox Box)> pairs, bool state)
                {
                    foreach (var pair in pairs)
                        pair.Box.IsChecked = state;
                }

                void OnSearch(object sender, TextChangedEventArgs args)
                {
                    string term = (search.Text ?? "").Trim().ToLowerInvariant();
                    foreach (var (value, item, _) in boxes)
                    {
                        item.Visibility = term.Length == 0 || value.ToLowerInvariant().Contains(term)
                            ? Visibility.Visible : Visibility.Collapsed;
                        if (item.Visibility != Visibility.Visible)
                            item.IsSelected = false;
                    }
                }

                // A tick on one of several highlighted values ticks them all.
                RoutedEventHandler MakeTicked(ListBoxItem item)
                {
                    return (sender, args) =>
                    {
                        var group = SelectedPairs();
                        if (item.IsSelected && group.Count > 1)
                            SetAll(group, ((CheckBox)sender).IsChecked == true);
                    };
                }

                void OnListKey(object sender, KeyEventArgs args)
                {
                    if (args.Key != Key.Space)
                        return;
                    var group = SelectedPairs();
                    if (group.Count > 0)
                    {
                        SetAll(group, !group.All(pair => pair.Box.IsChecked == true));
                        args.Handled = true;
                    }
                }

                void OnOk(object sender, RoutedEventArgs args)
                {
                    var ticked = new HashSet<string>(boxes.Where(one => one.Box.IsChecked == true)
                                                          .Select(one => Raw(one.Value)), StringComparer.Ordinal);
                    if (boxes.Count > 0 && ticked.Count == 0)
                    {
                        SayCore("Tick at least one value to show.");
                        return;
                    }
                    popup.IsOpen = false;
                    // Everything ticked is no filter at all, so a value that turns up later is not
                    // hidden by a list that never knew it.
                    SetPick(field, ticked.Count == boxes.Count ? null : ticked);
                }

                void OnCancel(object sender, RoutedEventArgs args)
                {
                    popup.IsOpen = false;
                }

                void OnShellKey(object sender, KeyEventArgs args)
                {
                    if (args.Key == Key.Escape)
                    {
                        popup.IsOpen = false;
                        args.Handled = true;
                    }
                    else if (args.Key == Key.Enter)
                    {
                        OnOk(sender, args);
                        args.Handled = true;
                    }
                }

                void OnClosed(object sender, EventArgs args)
                {
                    FilterOpen = false;
                    try
                    {
                        holder?.Children.Remove(popup);
                    }
                    catch (Exception)
                    {
                    }
                }

                // A popup's events bubble back through its logical parent - the heading. Whatever
                // the controls inside leave unhandled stops here, or a press would start dragging
                // the column.
                void Swallow(object sender, RoutedEventArgs args)
                {
                    try
                    {
                        args.Handled = true;
                    }
                    catch (Exception)
                    {
                    }
                }

                foreach (var (_, item, box) in boxes)
                    box.Click += MakeTicked(item);
                shell.MouseLeftButtonDown += (s, a) => Swallow(s, a);
                shell.MouseLeftButtonUp += (s, a) => Swallow(s, a);
                shell.KeyDown += (s, a) => Swallow(s, a);
                shell.PreviewKeyDown += OnShellKey;
                listing.PreviewKeyDown += OnListKey;
                search.TextChanged += OnSearch;
                every.Click += (s, a) => SetAll(Shown(), true);
                none.Click += (s, a) => SetAll(Shown(), false);
                tick.Click += (s, a) => SetAll(SelectedPairs(), true);
                untick.Click += (s, a) => SetAll(SelectedPairs(), false);
                ok.Click += OnOk;
                cancel.Click += OnCancel;
                popup.Closed += OnClosed;
                // Into the heading's own panel, so the list is in the window's logical tree and its
                // DynamicResource colours resolve.
                holder = button.Parent as Panel;
                try
                {
                    holder?.Children.Add(popup);
                }
                catch (Exception)
                {
                }
                FilterOpen = true;
                popup.IsOpen = true;
                try
                {
                    search.Focus();
                }
                catch (Exception)
                {
                }
            }

            /// <summary>Set or clear one column's value filter, then re-take the view.</summary>
            public void SetPick(string field, IEnumerable<string> allowed)
            {
                if (allowed == null)
                    Picks.Remove(field);
                else
                    Picks[field] = new HashSet<string>(allowed, StringComparer.Ordinal);
                PaintFilterButton(field);
                Refresh();
            }

            internal TextChangedEventHandler MakeSearch(string field)
            {
                return (sender, args) =>
                {
                    try
                    {
                        Filters[field] = ((TextBox)sender).Text ?? "";
                    }
                    catch (Exception)
                    {
                        Filters[field] = "";
                    }
                    Refresh();
                };
            }

            internal void FillSettings()
            {
                Suspend = true;
                try
                {
                    bool perSheet = Str(Staging.Settings.TryGetValue("numbering", out var n) ? n : null) ==
                                    PsRevisions.PerSheet;
                    if (PerSheet != null)
                        PerSheet.IsChecked = perSheet;
                    if (PerProject != null)
                        PerProject.IsChecked = !perSheet;
                    PsUi.SetText(ArcBox, ArcText(Staging.Settings.TryGetValue("arc_mm", out var arc) ? arc : null));
                }
                finally
                {
                    Suspend = false;
                }
            }

            /// <summary>u'{0:g}'.format(float(value)), or "" when it is no number.</summary>
            internal static string ArcText(object value)
            {
                try
                {
                    double number = value is double d ? d
                        : value is IConvertible ? Convert.ToDouble(value, Inv)
                        : double.Parse(Str(value), Inv);
                    // Python's general format: 6 significant digits, no trailing zeros.
                    return number.ToString("G6", Inv).Replace("E", "e");
                }
                catch (Exception)
                {
                    return "";
                }
            }

            internal void Wire()
            {
                // As in the Python, the table's ColumnChanged is subscribed here as well as in
                // MakeTable, so on the first table it runs twice per change (idempotent: the second
                // pass stages the same value again).
                try
                {
                    Table.ColumnChanged += CellChanged;
                }
                catch (Exception)
                {
                }
                if (GridControl != null)
                {
                    try
                    {
                        GridControl.BeginningEdit += BeginningEdit;
                        GridControl.PreviewKeyDown += KeyDown;
                        GridControl.SelectionChanged += SelectionChanged;
                        GridControl.CurrentCellChanged += CurrentCell;
                        GridControl.ColumnReordered += ColumnMoved;
                        GridControl.LayoutUpdated += PaintBands;
                        GridControl.PreviewMouseRightButtonDown += RightPress;
                        GridControl.PreviewMouseRightButtonUp += RightRelease;
                        GridControl.PreviewMouseLeftButtonDown += GridPress;
                    }
                    catch (Exception)
                    {
                    }
                }
                foreach (var (name, handler) in new (string, RoutedEventHandler)[]
                         {
                             ("RevAddButton", Add),
                             ("RevDeleteButton", Delete),
                             ("RevMoveUpButton", (s, a) => Move(-1)),
                             ("RevMoveDownButton", (s, a) => Move(1)),
                             ("RevMergeUpButton", (s, a) => Merge(-1)),
                             ("RevMergeDownButton", (s, a) => Merge(1)),
                             ("RevClearSearchButton", ClearSearches),
                             ("RevAddColumnButton", (s, a) => AddColumn(s, a)),
                             ("RevPushButton", Push),
                             ("RevSettingsButton", OpenSettings),
                             ("RevFitColumnsButton", FitColumns),
                             ("RevResetColumnsButton", ResetOrder),
                             ("RevSeriesToggleButton", ToggleSeries),
                             ("RevFollowButton", ToggleFollow),
                             ("RevSheetFilterButton", ToggleSheetFilter),
                             ("ThemeChip", ToggleTheme),
                             ("ApplyButton", Apply),
                             ("CancelButton", (s, a) => Cancel()),
                         })
                {
                    if (!(PsUi.Find(Window, name) is ButtonBase button))
                        continue;
                    try
                    {
                        button.Click += handler;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
                foreach (var (radio, mode) in new[] { (PerProject, PsRevisions.PerProject), (PerSheet, PsRevisions.PerSheet) })
                {
                    if (radio == null)
                        continue;
                    try
                    {
                        radio.Checked += MakeNumbering(mode);
                    }
                    catch (Exception)
                    {
                    }
                }
                if (ArcBox != null)
                {
                    try
                    {
                        ArcBox.TextChanged += ArcChanged;
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            /// <summary>null as DBNull, for a DataRow cell.</summary>
            internal static object Db(object value)
            {
                return value ?? DBNull.Value;
            }
        }
    }
}
