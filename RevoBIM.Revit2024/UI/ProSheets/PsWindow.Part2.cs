using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Threading;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsWindow
    {
        public partial class ProSheetsWindow
        {
            // ==================================================================
            // the columns
            //
            // Every column on this grid is built in code from one ordered list,
            // including the six that used to be declared in XAML. That is what
            // makes "put the new one next to the one I right clicked" and
            // "remember where I left them" possible at all.
            // ==================================================================

            // id, heading, star width, minimum width
            //
            // Sheets and views are different lists of things and want different
            // columns. A view has no sheet number, no revision and no paper size.
            public static readonly List<(string Id, string Title, double Star, int Minimum)> SheetColumns =
                new List<(string, string, double, int)>
                {
                    ("sel", "", 0.0, 44),
                    ("num", "Sheet Number", 1.1, 120),
                    ("name", "Sheet Name", 2.0, 175),
                    ("rev", "Revision", 0.6, 85),
                    ("size", "Size", 1.0, 130),
                    ("fname", "Custom File Name", 2.2, 210),
                };

            public static readonly List<(string Id, string Title, double Star, int Minimum)> ViewColumns =
                new List<(string, string, double, int)>
                {
                    ("sel", "", 0.0, 44),
                    ("name", "View Name", 2.4, 200),
                    ("fname", "Custom File Name", 2.2, 210),
                };

            // Every id either set can produce, which is what an old template has
            // to be checked against before its saved order is trusted.
            public static readonly string[] KnownColumns = { "sel", "num", "name", "rev", "size", "fname" };

            public const string TickTemplate =
                "<DataTemplate " +
                "xmlns=\"http://schemas.microsoft.com/winfx/2006/xaml/presentation\">" +
                "<CheckBox Style=\"{DynamicResource GridCheckBox}\" " +
                "IsChecked=\"{Binding sel, Mode=TwoWay, " +
                "UpdateSourceTrigger=PropertyChanged}\"/>" +
                "</DataTemplate>";

            /// <summary>The fixed column set for 'sheets' or 'views'.</summary>
            public static List<(string Id, string Title, double Star, int Minimum)> ColumnsFor(string mode)
            {
                if ((mode ?? "") == "views")
                    return ViewColumns;
                return SheetColumns;
            }

            public static List<string> DefaultColumnOrder(string mode = "sheets")
            {
                return ColumnsFor(mode).Select(entry => entry.Id).ToList();
            }

            // Shown on every sheet list unless a template says otherwise. The
            // revision date is a value the tool derives; the other two are
            // whatever this office calls them, which is why they come from
            // settings rather than being written in here.
            public static readonly List<string> DefaultExtraColumns = new List<string> { "Current Revision Date" };

            /// <summary>
            /// The column order a list starts in, parameters included. Separate from
            /// DefaultColumnOrder, which stays the fixed set and nothing else.
            /// </summary>
            public static List<string> StartingColumns(string mode, IEnumerable<string> extras = null,
                                                       IEnumerable<string> browser = null)
            {
                var order = new List<string>(DefaultColumnOrder(mode));
                if (mode == "views")
                {
                    // Never the sheet parameters - no view has a value for them.
                    // The columns of Revit's Project Browser instead.
                    extras = browser;
                }
                var wanted = new List<string>();
                foreach (string name in extras ?? Enumerable.Empty<string>())
                {
                    string colId = "p:" + name;
                    if (!string.IsNullOrEmpty(name) && !wanted.Contains(colId))
                        wanted.Add(colId);
                }
                if (wanted.Count == 0)
                    return order;
                // In front of Custom File Name, which reads best last.
                int where = order.Contains("fname") ? order.IndexOf("fname") : order.Count;
                return order.Take(where).Concat(wanted).Concat(order.Skip(where)).ToList();
            }

            /// <summary>The parameter columns a sheet list starts with.</summary>
            public List<string> DefaultExtras()
            {
                var names = new List<string>(DefaultExtraColumns);
                foreach (string key in new[] { "param_series", "param_discipline" })
                {
                    string name = Settings.Text(key, "");
                    if (!string.IsNullOrEmpty(name) && !names.Contains(name))
                        names.Add(name);
                }
                return names;
            }

            /// <summary>
            /// Start on the sheet series unless the template says otherwise. The
            /// column is put back if it is missing rather than the sort being
            /// abandoned: you cannot sort on a column that is not there, so the
            /// answer is to put it there.
            /// </summary>
            internal bool ApplyDefaultSort()
            {
                if (SortStack.Count > 0)
                    return false;
                if (IsViewsMode())
                    return ApplyBrowserSort();
                string series = SeriesColumn();
                if (string.IsNullOrEmpty(series))
                    return false;
                if (!ColumnOrder.Contains(series))
                {
                    var order = new List<string>(ColumnOrder);
                    int where = order.Contains("fname") ? order.IndexOf("fname") : order.Count;
                    order.Insert(where, series);
                    ColumnOrder = order;
                }
                SortStack = new List<(string, bool)> { (series, false) };
                return true;
            }

            /// <summary>
            /// The Views list sorted the way Revit's Project Browser sorts it: by
            /// the first folder, then the second, and so on, then the view type,
            /// then the name. Any of those columns missing is put back, in front of
            /// Custom File Name.
            /// </summary>
            internal bool ApplyBrowserSort()
            {
                var names = new List<string>(BrowserNames ?? new List<string>());
                if (names.Count == 0)
                    return false;
                var wanted = names.Select(name => "p:" + name).ToList();
                var order = new List<string>(ColumnOrder);
                foreach (string colId in wanted)
                {
                    if (!order.Contains(colId))
                    {
                        int where = order.Contains("fname") ? order.IndexOf("fname") : order.Count;
                        order.Insert(where, colId);
                    }
                }
                ColumnOrder = order;
                var levels = wanted.Take(MaxSortLevels - 1);
                SortStack = levels.Select(colId => (colId, false)).ToList();
                SortStack.Add(("name", false));
                return true;
            }

            /// <summary>The column id the list sorts by out of the box, or null.</summary>
            public string SeriesColumn()
            {
                string name = Settings.Text("param_series", "");
                return !string.IsNullOrEmpty(name) ? "p:" + name : null;
            }

            // ------------------------------------------------------ sort memory
            // The sort and grouping last set by hand, per machine and per mode.
            public const string SortMemory = "sel_sort.";
            public const string GroupMemory = "sel_grouped.";

            /// <summary>(stack, grouped) last set in this mode, or null for never.</summary>
            internal (List<(string ColId, bool Descending)> Stack, bool Grouped)? RememberedSort(string mode = null)
            {
                mode = string.IsNullOrEmpty(mode) ? ModeName() : mode;
                var store = Settings?.Store;
                if (store == null || store.Count == 0)
                    return null;
                string key = SortMemory + mode;
                if (!store.ContainsKey(key))
                    return null;
                var stack = new List<(string ColId, bool Descending)>();
                foreach (string piece in PsConfig.GetList(store, key, new List<string>()))
                {
                    var (colId, direction) = Partition(piece ?? "", '|');
                    if (!string.IsNullOrEmpty(colId))
                        stack.Add((colId, direction == "desc"));
                }
                bool grouped = PsConfig.GetBool(store, GroupMemory + mode, true);
                return (stack, grouped);
            }

            /// <summary>Python str.partition: (head, tail) around the first separator.</summary>
            internal static (string Head, string Tail) Partition(string text, char separator)
            {
                int at = text.IndexOf(separator);
                if (at < 0)
                    return (text, "");
                return (text.Substring(0, at), text.Substring(at + 1));
            }

            /// <summary>Keep what is on screen as the sort this mode opens in next time.</summary>
            public bool RememberSort()
            {
                if (Settings == null)
                    return false;
                string mode = ModeName();
                try
                {
                    Settings.Set(SortMemory + mode, PsConfig.PutList(
                        SortStack.Select(pair => pair.ColId + "|" + (pair.Descending ? "desc" : "asc"))));
                    Settings.Set(GroupMemory + mode, Grouped ? "1" : "0");
                    Settings.Save();
                }
                catch (Exception)
                {
                    return false;
                }
                return true;
            }

            /// <summary>Back to the out of the box sort for this mode.</summary>
            public bool ForgetSort(string mode = null)
            {
                if (Settings == null)
                    return false;
                mode = string.IsNullOrEmpty(mode) ? ModeName() : mode;
                foreach (string key in new[] { SortMemory + mode, GroupMemory + mode })
                    Settings.Store.Remove(key);
                try
                {
                    Settings.Save();
                }
                catch (Exception)
                {
                }
                return true;
            }

            /// <summary>
            /// Put the remembered sort and grouping back. False when there is none.
            /// A remembered parameter column that is no longer on the list is put
            /// back in front of Custom File Name; a fixed column that does not belong
            /// to this mode is let go.
            /// </summary>
            internal bool RestoreSort(string mode = null)
            {
                mode = string.IsNullOrEmpty(mode) ? ModeName() : mode;
                var memory = RememberedSort(mode);
                if (memory == null)
                    return false;
                var (stack, grouped) = memory.Value;
                var order = new List<string>(ColumnOrder);
                var kept = new List<(string ColId, bool Descending)>();
                foreach (var (colId, down) in stack.Take(MaxSortLevels))
                {
                    if (!order.Contains(colId))
                    {
                        if (!colId.StartsWith("p:", StringComparison.Ordinal))
                            continue;
                        int where = order.Contains("fname") ? order.IndexOf("fname") : order.Count;
                        order.Insert(where, colId);
                    }
                    kept.Add((colId, down));
                }
                if (stack.Count > 0 && kept.Count == 0)
                    return false;
                ColumnOrder = order;
                SortStack = kept;
                Grouped = grouped;
                TemplateSort = "";
                // The tick follows without ToggleGrouping rebuilding the groups.
                SuspendGroupToggle = true;
                SetChecked(C("GroupCheck"), Grouped);
                SuspendGroupToggle = false;
                return true;
            }

            public List<(string Id, string Title, double Star, int Minimum)> FixedColumns()
            {
                return ColumnsFor(IsViewsMode() ? "views" : "sheets");
            }

            /// <summary>
            /// A saved column order made to fit the mode it is being used in. The
            /// fixed columns that do not belong are dropped, the ones that are
            /// missing are put back in their standard places, and the parameter
            /// columns - the user's actual work - are kept exactly where they were.
            /// </summary>
            internal List<string> SaneOrder(IEnumerable<string> saved, string mode = null)
            {
                mode = string.IsNullOrEmpty(mode) ? ModeName() : mode;
                List<string> wanted = DefaultColumnOrder(mode);
                var order = saved.Where(colId => IsParameterColumn(colId) || wanted.Contains(colId)).ToList();
                for (int index = 0; index < wanted.Count; index++)
                {
                    string colId = wanted[index];
                    if (order.Contains(colId))
                        continue;
                    // Put it back next to whichever of its neighbours survived,
                    // so 'sel' stays first and 'fname' stays last.
                    int where = 0;
                    for (int back = index - 1; back >= 0; back--)
                    {
                        string other = wanted[back];
                        if (order.Contains(other))
                        {
                            where = order.IndexOf(other) + 1;
                            break;
                        }
                    }
                    order.Insert(where, colId);
                }
                return order;
            }

            public static bool IsParameterColumn(string colId)
            {
                return (colId ?? "").StartsWith("p:", StringComparison.Ordinal);
            }

            public static string ParameterOf(string colId)
            {
                string text = colId ?? "";
                return text.Length > 2 ? text.Substring(2) : "";
            }

            /// <summary>The added parameter columns, in the order they appear.</summary>
            public List<string> ParameterColumns()
            {
                return ColumnOrder.Where(IsParameterColumn).Select(ParameterOf).ToList();
            }

            /// <summary>
            /// The DataTable column behind a grid column. A parameter column is c0,
            /// c1... and never the parameter's own name: a binding path cannot carry
            /// a space, a bracket or a hash.
            /// </summary>
            internal string DataKey(string colId)
            {
                if (!IsParameterColumn(colId))
                    return colId;
                int index = 0;
                foreach (string other in ColumnOrder)
                {
                    if (!IsParameterColumn(other))
                        continue;
                    if (other == colId)
                        return "c" + index.ToString(Inv);
                    index++;
                }
                return "c0";
            }

            internal string HeadingOf(string colId)
            {
                if (IsParameterColumn(colId))
                    return ParameterOf(colId);
                foreach (var (other, title, _, _) in FixedColumns())
                {
                    if (other == colId)
                        return title;
                }
                return colId;
            }

            internal void BuildColumns()
            {
                var grid = C<DataGrid>("SheetGrid");
                if (grid == null)
                    return;

                // The DataTable needs a column per parameter before the grid can
                // bind to one.
                try
                {
                    foreach (DataColumn column in Table.Columns.Cast<DataColumn>().ToList())
                    {
                        string name = column.ColumnName ?? "";
                        if (name.StartsWith("c", StringComparison.Ordinal) && name.Length > 1 &&
                            name.Substring(1).All(char.IsDigit))
                            Table.Columns.Remove(column);
                    }
                }
                catch (Exception)
                {
                }
                int count = ParameterColumns().Count;
                for (int index = 0; index < count; index++)
                {
                    try
                    {
                        Table.Columns.Add("c" + index.ToString(Inv), typeof(string));
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }

                SearchBoxes = new Dictionary<string, TextBox>(StringComparer.Ordinal);
                HeaderOutlines = new Dictionary<string, Border>(StringComparer.Ordinal);
                HeaderBadges = new Dictionary<string, TextBlock>(StringComparer.Ordinal);
                HeaderTick = null;
                try
                {
                    grid.Columns.Clear();
                }
                catch (Exception)
                {
                    return;
                }

                foreach (string colId in ColumnOrder.ToList())
                {
                    try
                    {
                        grid.Columns.Add(MakeColumn(colId));
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }

                PaintSortHeaders();
                ApplyColumnWidths(SavedWidths);
                FillParameterValues();
            }

            internal DataGridColumn MakeColumn(string colId)
            {
                double width = 1.0;
                double minimum = 110;
                foreach (var (other, _, star, least) in FixedColumns())
                {
                    if (other == colId)
                    {
                        width = star;
                        minimum = least;
                        break;
                    }
                }

                DataGridColumn column;
                if (colId == "sel")
                {
                    var tick = new DataGridTemplateColumn();
                    tick.CellTemplate = (DataTemplate)XamlReader.Parse(TickTemplate);
                    tick.Width = new DataGridLength(44);
                    tick.MinWidth = 44;
                    tick.CanUserResize = false;
                    tick.CanUserSort = false;
                    column = tick;
                }
                else
                {
                    var text = new DataGridTextColumn();
                    text.Binding = new Binding(DataKey(colId));
                    text.Width = StarWidth(width);
                    text.MinWidth = minimum;
                    text.IsReadOnly = true;
                    column = text;
                }

                // SortMemberPath is how the Sorting handler knows which column was
                // clicked without keeping a map of column objects alongside.
                column.SortMemberPath = colId;
                column.Header = HeaderFor(colId);
                return column;
            }

            /// <summary>
            /// A heading is a live element: title, sort badge and search box. The
            /// sort outline lives here in the content rather than in a header style,
            /// because a Border here takes any brush.
            /// </summary>
            internal Border HeaderFor(string colId)
            {
                var outline = new Border();
                outline.BorderThickness = new Thickness(2);
                outline.CornerRadius = new CornerRadius(2);
                outline.BorderBrush = Brushes.Transparent;
                outline.Padding = new Thickness(3, 2, 3, 3);
                HeaderOutlines[colId] = outline;

                var panel = new StackPanel();
                panel.Orientation = Orientation.Vertical;
                outline.Child = panel;

                var top = new Grid();
                top.ColumnDefinitions.Add(new ColumnDefinition());
                var badgeColumn = new ColumnDefinition();
                badgeColumn.Width = new GridLength(0, GridUnitType.Auto);
                top.ColumnDefinitions.Add(badgeColumn);

                if (colId == "sel")
                {
                    var box = new CheckBox();
                    Styled(box, "GridCheckBox");
                    box.ToolTip = "Tick or untick everything showing";
                    box.Click += HeaderTickClicked;
                    HeaderTick = box;
                    outline.Padding = new Thickness(0);
                    outline.Child = box;
                    return outline;
                }

                if (colId == "fname")
                {
                    var button = new Button();
                    button.Content = HeadingOf(colId);
                    Styled(button, "ChipButton");
                    button.ToolTip = "Choose which parameters make up the exported file name";
                    button.Click += OpenNameDialog;
                    button.HorizontalAlignment = HorizontalAlignment.Left;
                    Grid.SetColumn(button, 0);
                    top.Children.Add(button);
                }
                else
                {
                    var title = new TextBlock();
                    title.Text = HeadingOf(colId);
                    title.TextTrimming = TextTrimming.CharacterEllipsis;
                    title.VerticalAlignment = VerticalAlignment.Center;
                    Grid.SetColumn(title, 0);
                    top.Children.Add(title);
                }

                var badge = new TextBlock();
                badge.FontSize = 11;
                badge.FontWeight = FontWeights.Bold;
                badge.Margin = new Thickness(6, 0, 0, 0);
                badge.VerticalAlignment = VerticalAlignment.Center;
                badge.Visibility = Visibility.Collapsed;
                Grid.SetColumn(badge, 1);
                top.Children.Add(badge);
                HeaderBadges[colId] = badge;

                panel.Children.Add(top);

                var search = new TextBox();
                Styled(search, "ColumnSearchBox");
                search.Tag = "Search";
                search.Text = ColumnSearch.TryGetValue(colId, out string typed) ? typed : "";
                search.TextChanged += MakeColumnSearch(colId);
                // Clicking a heading sorts it, and that must not happen when the
                // click was aimed at the search box. Handling the preview stops the
                // sort, so the focus has to be given by hand.
                search.PreviewMouseLeftButtonDown += FocusSearch;
                panel.Children.Add(search);
                SearchBoxes[colId] = search;
                return outline;
            }

            /// <summary>
            /// Point an element at a keyed style, dynamically. Never
            /// element.Style = TryFindResource(key): a failed lookup assigns a local
            /// null, and a local null on Style stops WPF applying the implicit style
            /// as well. A resource reference also re-resolves when the palette is
            /// swapped.
            /// </summary>
            public bool Styled(FrameworkElement element, string key)
            {
                try
                {
                    element.SetResourceReference(FrameworkElement.StyleProperty, key);
                    return true;
                }
                catch (Exception)
                {
                    return false;
                }
            }

            internal void FocusSearch(object sender, MouseButtonEventArgs args)
            {
                try
                {
                    ((UIElement)sender).Focus();
                    args.Handled = true;
                }
                catch (Exception)
                {
                }
            }

            internal TextChangedEventHandler MakeColumnSearch(string colId)
            {
                return (sender, args) =>
                {
                    try
                    {
                        ColumnSearch[colId] = ((TextBox)sender).Text ?? "";
                    }
                    catch (Exception)
                    {
                        ColumnSearch[colId] = "";
                    }
                    DebounceFilters();
                };
            }

            /// <summary>Re-filtering on every keystroke is visibly slow at 400 sheets.</summary>
            internal void DebounceFilters()
            {
                try
                {
                    if (FilterTimer == null)
                    {
                        var timer = new DispatcherTimer();
                        timer.Interval = TimeSpan.FromMilliseconds(220);
                        timer.Tick += FilterTick;
                        FilterTimer = timer;
                    }
                    FilterTimer.Stop();
                    FilterTimer.Start();
                }
                catch (Exception)
                {
                    ApplyFilters();
                    RefreshCounts();
                }
            }

            internal void FilterTick(object sender, EventArgs args)
            {
                try
                {
                    FilterTimer.Stop();
                }
                catch (Exception)
                {
                }
                ApplyFilters();
                RefreshCounts();
            }

            internal DataGridLength StarWidth(double weight)
            {
                return new DataGridLength(weight, DataGridLengthUnitType.Star);
            }

            /// <summary>
            /// Read each added parameter for every row. One pass over the rows
            /// rather than one per column, because the lookup caches per row.
            /// </summary>
            internal void FillParameterValues()
            {
                List<string> names = ParameterColumns();
                if (names.Count == 0)
                    return;
                SuspendTicks = true;
                try
                {
                    foreach (DataRow entry in Table.Rows)
                    {
                        if (string.IsNullOrEmpty(S(entry["key"])))
                            continue;           // a group heading holds no sheet
                        if (!RowsByKey.TryGetValue(AsKey(S(entry["key"])), out PsModel.Row row) || row == null)
                            continue;
                        PsModel.RowLookup lookup = LookupFor(row);
                        for (int index = 0; index < names.Count; index++)
                        {
                            string dataKey = "c" + index.ToString(Inv);
                            try
                            {
                                entry[dataKey] = lookup.Invoke(names[index]) ?? "";
                            }
                            catch (Exception)
                            {
                                try { entry[dataKey] = ""; } catch (Exception) { }
                            }
                        }
                    }
                }
                finally
                {
                    SuspendTicks = false;
                }
            }

            // ------------------------------------------------------- sorting
            public const int MaxSortLevels = 6;

            /// <summary>
            /// Take the sort over from the DataGrid. The view is sorted on a hidden
            /// key column, so Handled is set and the order written instead. Plain
            /// click starts again from one level; shift-click adds a level, or flips
            /// one already in the stack, the way a spreadsheet does.
            /// </summary>
            internal void OnSorting(object sender, DataGridSortingEventArgs args)
            {
                string colId;
                try
                {
                    args.Handled = true;
                    colId = args.Column.SortMemberPath ?? "";
                }
                catch (Exception)
                {
                    return;
                }
                if (string.IsNullOrEmpty(colId))
                    return;

                var existing = Enumerable.Range(0, SortStack.Count).Where(i => SortStack[i].ColId == colId).ToList();
                if (PsUi.ShiftDown())
                {
                    if (existing.Count > 0)
                    {
                        int place = existing[0];
                        SortStack[place] = (colId, !SortStack[place].Descending);
                    }
                    else if (SortStack.Count < MaxSortLevels)
                    {
                        SortStack.Add((colId, false));
                    }
                    else
                    {
                        Say("Six sort levels is the limit.");
                        return;
                    }
                }
                else
                {
                    if (existing.Count > 0 && SortStack.Count == 1)
                        SortStack = new List<(string, bool)> { (colId, !SortStack[0].Descending) };
                    else
                        SortStack = new List<(string, bool)> { (colId, false) };
                }

                // A group number is a position in this sort's list of values and
                // means nothing in the next one, so anything collapsed under the
                // old sort has to be let go.
                Collapsed = new HashSet<int>();
                EnsureGrouped();

                ApplyOrder();
                ApplyGrouping();
                ApplyFilters();
                PaintSortHeaders();
                RememberSort();
                SaySort();
            }

            /// <summary>
            /// Sorting turns grouping on (was it off). The tick is set with its own
            /// handler suppressed, so ToggleGrouping does not rebuild the groups
            /// against the order this sort is about to replace.
            /// </summary>
            internal bool EnsureGrouped()
            {
                if (Grouped)
                    return false;
                Grouped = true;
                SuspendGroupToggle = true;
                try
                {
                    SetChecked(C("GroupCheck"), true);
                }
                finally
                {
                    SuspendGroupToggle = false;
                }
                return true;
            }

            internal void SaySort()
            {
                if (SortStack.Count == 0)
                {
                    Say("Not sorted. Click a heading to sort, shift click to add a second level.");
                    return;
                }
                var parts = new List<string>();
                foreach (var (colId, descending) in SortStack)
                    parts.Add(HeadingOf(colId) + " " + (descending ? "Z-A" : "A-Z"));
                string tail = "";
                if (Grouped && RunCount != 0)
                {
                    tail = string.Format(Inv, " {0} value{1} of {2}, each its own colour and each collapsible.",
                                         RunCount, Plural(RunCount), HeadingOf(SortStack[0].ColId));
                }
                else if (SortStack.Count < MaxSortLevels)
                {
                    tail = " Shift click a heading to add a level.";
                }
                Say("Sorted by " + string.Join(", then ", parts) + "." + tail);
            }

            /// <summary>Outline and badge each sorted heading in its level's colour.</summary>
            internal void PaintSortHeaders()
            {
                var levels = new Dictionary<string, (int Index, bool Descending)>(StringComparer.Ordinal);
                for (int index = 0; index < SortStack.Count; index++)
                    levels[SortStack[index].ColId] = (index, SortStack[index].Descending);

                foreach (var pair in HeaderOutlines.ToList())
                {
                    string colId = pair.Key;
                    Border outline = pair.Value;
                    HeaderBadges.TryGetValue(colId, out TextBlock badge);
                    if (!levels.TryGetValue(colId, out var found))
                    {
                        try
                        {
                            outline.BorderBrush = Brushes.Transparent;
                        }
                        catch (Exception)
                        {
                        }
                        if (badge != null)
                        {
                            try
                            {
                                badge.Visibility = Visibility.Collapsed;
                            }
                            catch (Exception)
                            {
                            }
                        }
                        continue;
                    }
                    SolidColorBrush brush = PsTheme.Brush(PsTheme.Colour(ThemeName, PsTheme.SortLevelKey(found.Index)));
                    try
                    {
                        outline.BorderBrush = brush;
                    }
                    catch (Exception)
                    {
                    }
                    if (badge != null)
                    {
                        try
                        {
                            badge.Text = (found.Index + 1).ToString(Inv) + (found.Descending ? "▼" : "▲");
                            badge.Foreground = brush;
                            badge.Visibility = Visibility.Visible;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
            }

            internal string SortValue(DataRow entry, string colId)
            {
                string key = ColumnOrder.Contains(colId) ? DataKey(colId) : "num";
                string value;
                try
                {
                    value = S(entry[key]);
                }
                catch (Exception)
                {
                    value = "";
                }
                if (key == "num")
                {
                    if (RowsByKey.TryGetValue(AsKey(S(entry["key"])), out PsModel.Row row) && row != null)
                        value = row.Number;
                }
                return value;
            }

            /// <summary>
            /// Write the sort key, so the view sorts on a decision not a value.
            /// Layered least significant first, relying on the sort being stable.
            /// Natural order throughout, so P-9 comes before P-10.
            /// </summary>
            internal void ApplyOrder()
            {
                List<DataRow> rows = Table.Rows.Cast<DataRow>().Where(entry => !string.IsNullOrEmpty(S(entry["key"]))).ToList();

                var stack = SortStack.Count > 0 ? SortStack : new List<(string ColId, bool Descending)> { ("num", false) };
                for (int level = stack.Count - 1; level >= 0; level--)
                {
                    var (colId, descending) = stack[level];
                    // Python's sort(reverse=True) keeps equal items in their order,
                    // as OrderByDescending does.
                    rows = descending
                        ? rows.OrderByDescending(entry => PsModel.NaturalKey(SortValue(entry, colId))).ToList()
                        : rows.OrderBy(entry => PsModel.NaturalKey(SortValue(entry, colId))).ToList();
                }

                SortedRows = rows;
                for (int index = 0; index < rows.Count; index++)
                    rows[index]["ord"] = index.ToString("D6", Inv) + "\x01";
            }

            // ------------------------------------------------------ grouping
            internal string GroupValue(DataRow entry)
            {
                if (SortStack.Count == 0)
                    return "";
                return SortValue(entry, SortStack[0].ColId);
            }

            // How long a run has to be to get a heading of its own. One, so every
            // distinct value gets a heading it can be collapsed by. Kept as a
            // constant so it is one edit to change.
            public const int MinRun = 1;

            /// <summary>
            /// [(label, start, count)] for each stretch of equal values. Consecutive,
            /// not distinct: after a sort those are the same thing.
            /// </summary>
            public static List<(string Label, int Start, int Count)> ValueRuns(IList<string> labels)
            {
                var runs = new List<(string Label, int Start, int Count)>();
                for (int index = 0; index < labels.Count; index++)
                {
                    string label = labels[index];
                    if (runs.Count > 0 && runs[runs.Count - 1].Label == label)
                    {
                        var last = runs[runs.Count - 1];
                        runs[runs.Count - 1] = (last.Label, last.Start, last.Count + 1);
                    }
                    else
                    {
                        runs.Add((label, index, 1));
                    }
                }
                return runs;
            }

            public static bool IsGroup(int count)
            {
                return count >= MinRun;
            }

            /// <summary>
            /// (cell, row wash, heading) brushes for the nth run. A colour of its
            /// own per run: each run's name picks its trade's ramp and the runs of
            /// one trade step dark to light down the list - see PlanRuns.
            /// </summary>
            internal (Brush Cell, Brush Wash, Brush Head) RunBrushes(int place)
            {
                return ShadeBrushes(RunHex(place));
            }

            /// <summary>
            /// A run's colour in the heading mode: its trade ramp, grey (two greys
            /// taking turns, so neighbouring runs still differ), or the colour picked
            /// for its value.
            /// </summary>
            internal string RunHex(int place)
            {
                List<string> colours = RunColours ?? new List<string>();
                string ramp;
                if (place >= 0 && place < colours.Count)
                    ramp = colours[place];
                else
                    ramp = PsRamp.Shade(PsRamp.Other, 0.0);
                List<string> labels = RunLabels ?? new List<string>();
                string label;
                int level;
                if (place >= 0 && place < labels.Count)
                {
                    label = labels[place];
                    level = place % 2 == 0 ? 1 : 2;
                }
                else
                {
                    label = "";
                    level = 1;
                }
                string custom = null;
                if (HeadingCustom != null && label != null)
                    HeadingCustom.TryGetValue(label, out custom);
                return PsRamp.ModeColour(HeadingMode ?? PsRamp.Coloured, ramp, level, ThemeName, custom);
            }

            /// <summary>One ramp colour per run, in list order (PsRamp.Plan).</summary>
            internal List<string> PlanRuns(IList<string> labels)
            {
                var headings = new List<(int Id, string Label, int Level, int? Parent)>();
                for (int index = 0; index < labels.Count; index++)
                    headings.Add((index, labels[index], 1, null));
                Dictionary<int, string> found = PsRamp.Plan(headings, ladder: PsRamp.SingleLevel);
                RunColours = Enumerable.Range(0, labels.Count).Select(index => found[index]).ToList();
                RunLabels = labels.Select(label => label ?? "").ToList();
                return RunColours;
            }

            /// <summary>
            /// (cell, row wash, heading) brushes for one heading colour. The heading
            /// is the solid colour; its members carry it at a fraction of its
            /// strength, through alpha, so the selection still shows through.
            /// </summary>
            public (Brush Cell, Brush Wash, Brush Head) ShadeBrushes(string hexText)
            {
                bool dark = ThemeName == "dark";
                Brush cell = PsTheme.Tinted(hexText, dark ? GroupCellDark : GroupCellLight);
                Brush wash = PsTheme.Tinted(hexText, dark ? GroupTintDark : GroupTintLight);
                return (cell, wash, PsTheme.Brush(hexText));
            }

            /// <summary>Black or white for text on a heading of this colour.</summary>
            public Brush InkBrush(string hexText)
            {
                return PsTheme.Brush(PsRamp.TextOn(hexText));
            }

            /// <summary>
            /// Colour each run of matching values and make it collapsible. Heading
            /// rows are appended to the end of the table, never inserted, and placed
            /// purely by their sort key - a heading sorts immediately above its own
            /// members because its key ends \x00 and theirs \x01.
            /// </summary>
            internal void ApplyGrouping()
            {
                SuspendTicks = true;
                try
                {
                    // Clear out last time's headings first.
                    foreach (DataRow entry in Table.Rows.Cast<DataRow>()
                                                  .Where(e => string.IsNullOrEmpty(S(e["key"]))).ToList())
                        Table.Rows.Remove(entry);

                    Groups = new Dictionary<int, List<DataRow>>();
                    RunCount = 0;
                    List<DataRow> sortedRows = SortedRows ?? new List<DataRow>();
                    if (!Grouped || SortStack.Count == 0)
                    {
                        foreach (DataRow entry in sortedRows)
                        {
                            entry["gid"] = "";
                            entry["grp"] = "";
                            entry["ishead"] = "";
                            entry["gbrush"] = Brushes.Transparent;
                        }
                        ApplyCellStyle();
                        return;
                    }

                    var labels = sortedRows.Select(entry =>
                    {
                        string value = GroupValue(entry);
                        return string.IsNullOrEmpty(value) ? "(blank)" : value;
                    }).ToList();

                    var headings = new List<(int Number, int Place)>();
                    var runs = ValueRuns(labels);
                    RunCount = runs.Count;
                    PlanRuns(runs.Select(run => run.Label).ToList());
                    for (int place = 0; place < runs.Count; place++)
                    {
                        var (_, start, count) = runs[place];
                        List<DataRow> members = sortedRows.Skip(start).Take(count).ToList();
                        int number = place + 1;
                        bool collapsible = IsGroup(count);
                        Brush cell = RunBrushes(place).Cell;
                        for (int index = 0; index < members.Count; index++)
                        {
                            DataRow entry = members[index];
                            entry["ord"] = number.ToString("D6", Inv) + "\x01" + index.ToString("D8", Inv);
                            entry["gid"] = collapsible ? number.ToString(Inv) : "";
                            entry["grp"] = place.ToString(Inv);
                            entry["ishead"] = "";
                            entry["gbrush"] = cell;
                        }
                        if (!collapsible)
                            continue;
                        Groups[number] = members;
                        headings.Add((number, place));
                    }

                    foreach (var (number, place) in headings)
                    {
                        DataRow heading = Table.NewRow();
                        heading["key"] = "";
                        heading["gid"] = number.ToString(Inv);
                        heading["grp"] = place.ToString(Inv);
                        heading["ishead"] = "1";
                        heading["vis"] = "1";
                        heading["show"] = "1";
                        // The pill carries the colour; a solid cell on top of it
                        // would square off its rounded corners.
                        heading["gbrush"] = Brushes.Transparent;
                        heading["gink"] = InkBrush(RunHex(place));
                        heading["ord"] = number.ToString("D6", Inv) + "\x00";
                        Table.Rows.Add(heading);
                    }
                    LabelGroups();
                    ApplyCellStyle();
                }
                finally
                {
                    SuspendTicks = false;
                    PaintCollapseButton();
                    // Headings are rebuilt unticked, so they have to be put back in
                    // step with members that were already ticked.
                    SyncGroupTicks();
                }
            }

            /// <summary>Light the Collapse all chip while there is something to collapse.</summary>
            internal void PaintCollapseButton()
            {
                var button = C<Button>("CollapseAllButton");
                if (button == null)
                    return;
                bool live = Grouped && Groups.Count > 0;
                Styled(button, live ? "ChipButtonOn" : "ChipButton");
                try
                {
                    button.IsEnabled = live;
                }
                catch (Exception)
                {
                }
                PsUi.SetContent(button, Collapsed.Count > 0 ? "Expand all" : "Collapse all");
            }

            /// <summary>
            /// Put the coloured cell style on the column that is sorted first. A
            /// column that is not the sorted one is given the plain style by name -
            /// never null, which lands as a local null on DataGridCell.Style and
            /// drops the cell to OS chrome (the white bar of 1.10.0).
            /// </summary>
            internal void ApplyCellStyle()
            {
                string wanted = (Grouped && SortStack.Count > 0) ? SortStack[0].ColId : null;

                Style plain = Resource("GridCell") as Style;
                Style grouped = Resource("GroupedCell") as Style;

                var grid = C<DataGrid>("SheetGrid");
                List<DataGridColumn> columns;
                try
                {
                    columns = grid.Columns.ToList();
                }
                catch (Exception)
                {
                    return;
                }
                foreach (DataGridColumn column in columns)
                {
                    try
                    {
                        string colId = column.SortMemberPath ?? "";
                        Style style = colId == wanted ? grouped : plain;
                        // Never assign the null a failed lookup returns.
                        if (style != null)
                            column.CellStyle = style;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }

            /// <summary>A keyed resource, or null. Never assign null to a Style.</summary>
            internal object Resource(string key)
            {
                try
                {
                    return Window.TryFindResource(key);
                }
                catch (Exception)
                {
                    return null;
                }
            }

            /// <summary>
            /// Write each heading's caption into the table, never onto the row: a
            /// local value on a recycled row container sticks to that container.
            /// </summary>
            internal void LabelGroups()
            {
                string word = IsViewsMode() ? "view" : "sheet";
                foreach (DataRow entry in Table.Rows)
                {
                    if (!IsHeading(entry))
                        continue;
                    int group = AsInt(entry["gid"]);
                    List<DataRow> members = Groups.TryGetValue(group, out var found) ? found : new List<DataRow>();
                    int shown = members.Count(m => S(m["vis"]) == "1");
                    string label = members.Count > 0 ? GroupValue(members[0]) : "";
                    bool shut = Collapsed.Contains(group);
                    entry["num"] = (shut ? "▸" : "▾") + "  " + (string.IsNullOrEmpty(label) ? "(blank)" : label);
                    entry["name"] = string.Format(Inv, "[ {0} ]  {1}   {2} {3}{4}",
                                                  shut ? "+" : "–",
                                                  shut ? "Expand" : "Collapse",
                                                  shown, word, Plural(shown));
                }
            }

            internal static int AsInt(object value)
            {
                return int.TryParse(S(value).Trim(), System.Globalization.NumberStyles.Integer, Inv, out int number) ? number : 0;
            }

            public void ToggleGrouping(object sender = null, RoutedEventArgs args = null)
            {
                if (SuspendGroupToggle)
                    return;
                Grouped = FlagOf("GroupCheck");
                if (Grouped && SortStack.Count == 0)
                {
                    // Grouping with nothing sorted groups on the sheet series where
                    // Setup names one, else the number.
                    string series = SeriesColumn();
                    if (!string.IsNullOrEmpty(series) && ColumnOrder.Contains(series) && !IsViewsMode())
                        SortStack = new List<(string, bool)> { (series, false) };
                    else
                        SortStack = new List<(string, bool)> { ("num", false) };
                    ApplyOrder();
                    PaintSortHeaders();
                }
                Collapsed = new HashSet<int>();
                ApplyGrouping();
                ApplyFilters();
                RefreshCounts();
                RememberSort();
                if (!Grouped)
                {
                    Say("Values are no longer coloured.");
                }
                else
                {
                    Say(string.Format(Inv,
                        "{0} value{1} of {2}, each with its own colour and heading. Click a heading to collapse it, " +
                        "or its tick box to tick the group.",
                        RunCount, Plural(RunCount), HeadingOf(SortStack[0].ColId)));
                }
            }

            public void CollapseAll(object sender = null, RoutedEventArgs args = null)
            {
                if (!Grouped)
                    return;
                if (Collapsed.Count > 0)
                    Collapsed = new HashSet<int>();
                else
                    Collapsed = new HashSet<int>(Groups.Keys);
                LabelGroups();
                ApplyFilters();
                RefreshCounts();
                PaintCollapseButton();
            }

            /// <summary>
            /// Whether a click on the grid should collapse a group. The tick box is
            /// the exception, and it has to be an exception here: this runs on
            /// PreviewMouseLeftButtonDown, before the CheckBox ever sees the click.
            /// </summary>
            public static bool WantsCollapse(bool grouped, bool onHeading, bool onCheckbox)
            {
                return grouped && onHeading && !onCheckbox;
            }

            /// <summary>
            /// A click on a group heading collapses or expands it. Also where the
            /// highlighted rows are noted down, because this is the only handler
            /// that runs before the click has been dealt with.
            /// </summary>
            internal void RowClick(object sender, MouseButtonEventArgs args)
            {
                object source;
                try
                {
                    source = args.OriginalSource;
                }
                catch (Exception)
                {
                    return;
                }
                if (UnderCheckbox(source))
                    TickSelection = SelectedKeys();
                else
                    TickSelection = new HashSet<string>(StringComparer.Ordinal);
                DataGridRow row;
                try
                {
                    row = RowUnder(source);
                }
                catch (Exception)
                {
                    row = null;
                }
                if (row == null)
                    return;
                DataRow entry;
                try
                {
                    entry = ((DataRowView)row.Item).Row;
                }
                catch (Exception)
                {
                    return;
                }
                if (!WantsCollapse(Grouped, IsHeading(entry), UnderCheckbox(source)))
                    return;
                int group = AsInt(entry["gid"]);
                if (Collapsed.Contains(group))
                    Collapsed.Remove(group);
                else
                    Collapsed.Add(group);
                LabelGroups();
                ApplyFilters();
                RefreshCounts();
                PaintCollapseButton();
                try
                {
                    args.Handled = true;
                }
                catch (Exception)
                {
                }
            }

            /// <summary>The keys of the rows highlighted in the grid right now.</summary>
            internal HashSet<string> SelectedKeys()
            {
                var found = new HashSet<string>(StringComparer.Ordinal);
                try
                {
                    foreach (object item in C<DataGrid>("SheetGrid").SelectedItems)
                    {
                        DataRow entry;
                        try
                        {
                            entry = ((DataRowView)item).Row;
                        }
                        catch (Exception)
                        {
                            continue;
                        }
                        if (IsHeading(entry))
                            continue;
                        string key = S(entry["key"]);
                        if (!string.IsNullOrEmpty(key))
                            found.Add(key);
                    }
                }
                catch (Exception)
                {
                    return new HashSet<string>(StringComparer.Ordinal);
                }
                return found;
            }

            /// <summary>
            /// Which rows a tick applies to. A tick on a row that is part of a
            /// highlighted block applies to the whole block; a tick on a row outside
            /// the block is just itself.
            /// </summary>
            public static HashSet<string> TickTargets(object changedKey, IEnumerable<string> selection)
            {
                string key = S(changedKey);
                var picked = new HashSet<string>((selection ?? Enumerable.Empty<string>()).Select(one => one ?? ""),
                                                 StringComparer.Ordinal);
                if (picked.Contains(key) && picked.Count > 1)
                    return picked;
                return new HashSet<string>(StringComparer.Ordinal) { key };
            }

            /// <summary>
            /// Whether the click landed inside a tick box. Walked from the clicked
            /// element outwards, because the thing hit is a bit of the CheckBox's
            /// template and only its parents say what it belongs to.
            /// </summary>
            public bool UnderCheckbox(object source)
            {
                object node = source;
                for (int step = 0; step < 10; step++)
                {
                    if (node == null)
                        return false;
                    if (node is CheckBox)
                        return true;
                    if (node is DataGridRow)
                        return false;
                    try
                    {
                        node = node is DependencyObject dep ? VisualTreeHelper.GetParent(dep) : null;
                    }
                    catch (Exception)
                    {
                        return false;
                    }
                }
                return false;
            }

            public DataGridRow RowUnder(object source)
            {
                object node = source;
                for (int step = 0; step < 14; step++)
                {
                    if (node == null)
                        return null;
                    if (node is DataGridRow row)
                        return row;
                    try
                    {
                        node = node is DependencyObject dep ? VisualTreeHelper.GetParent(dep) : null;
                    }
                    catch (Exception)
                    {
                        return null;
                    }
                }
                return null;
            }

            // How strongly a group's colour washes its member rows.
            public const int GroupTintDark = 34;
            public const int GroupTintLight = 26;
            // The sorted column's cell on a member row.
            public const int GroupCellDark = 110;
            public const int GroupCellLight = 80;

            /// <summary>
            /// Colour a group heading and wash its members, as rows are realised.
            /// Set on every row: with recycling on, a container that was a heading a
            /// moment ago becomes a data row.
            /// </summary>
            internal void PaintGroupRows(object sender, DataGridRowEventArgs args)
            {
                DataGridRow row;
                DataRow entry;
                try
                {
                    row = args.Row;
                    entry = ((DataRowView)row.Item).Row;
                }
                catch (Exception)
                {
                    return;
                }

                bool isHeading = false;
                int alternation = 0;
                bool coloured = false;
                try
                {
                    isHeading = S(entry["ishead"]) == "1";
                    alternation = AsInt(entry["grp"]);
                    // Every run is coloured now, so the wash follows "this row is in
                    // a run" - which "grp" carries.
                    coloured = !string.IsNullOrEmpty(S(entry["grp"]));
                }
                catch (Exception)
                {
                    isHeading = false;
                }

                if (isHeading)
                {
                    try
                    {
                        row.Background = RunBrushes(alternation).Head;
                        row.FontWeight = FontWeights.Bold;
                    }
                    catch (Exception)
                    {
                    }
                    return;
                }

                if (Grouped && coloured)
                {
                    try
                    {
                        row.Background = RunBrushes(alternation).Wash;
                        row.FontWeight = FontWeights.Normal;
                    }
                    catch (Exception)
                    {
                    }
                    return;
                }

                try
                {
                    row.Background = Brushes.Transparent;
                    row.FontWeight = FontWeights.Normal;
                }
                catch (Exception)
                {
                }
            }
        }
    }
}
