using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using RevoBIM.Tools.ProSheets;
using Element = Autodesk.Revit.DB.Element;
using View = Autodesk.Revit.DB.View;
using WpfMenuItem = System.Windows.Controls.MenuItem;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsWindow
    {
        public partial class ProSheetsWindow
        {
            // ==================================================================
            // remembering the window and the column widths
            // ==================================================================

            /// <summary>
            /// Each column's width, as a star weight or as pixels. A column the user
            /// has never touched stays star sized so it keeps growing with the
            /// window; one they have dragged becomes an absolute width.
            /// </summary>
            public List<string> ColumnWidths()
            {
                var output = new List<string>();
                var grid = C<DataGrid>("SheetGrid");
                if (grid == null)
                    return output;
                try
                {
                    foreach (DataGridColumn column in grid.Columns)
                    {
                        string colId = column.SortMemberPath ?? "";
                        if (string.IsNullOrEmpty(colId))
                            continue;
                        DataGridLength width = column.Width;
                        if (width.UnitType == DataGridLengthUnitType.Star)
                        {
                            output.Add(colId + "|star|" + width.Value.ToString("0.0000", Inv));
                        }
                        else
                        {
                            double actual = column.ActualWidth;
                            double value = actual != 0 && !double.IsNaN(actual) ? actual : width.Value;
                            output.Add(colId + "|px|" + value.ToString("0.0", Inv));
                        }
                    }
                }
                catch (Exception)
                {
                }
                return output;
            }

            public void ApplyColumnWidths(IEnumerable<string> saved)
            {
                var grid = C<DataGrid>("SheetGrid");
                List<string> pieces = saved?.ToList() ?? new List<string>();
                if (grid == null || pieces.Count == 0)
                    return;
                var wanted = new Dictionary<string, (string Kind, double Value)>(StringComparer.Ordinal);
                foreach (string piece in pieces)
                {
                    string[] parts = (piece ?? "").Split('|');
                    if (parts.Length != 3)
                        continue;
                    if (!PsConfig.TryPyFloat(parts[2], out double number))
                        continue;
                    wanted[parts[0]] = (parts[1], number);
                }
                try
                {
                    foreach (DataGridColumn column in grid.Columns)
                    {
                        string colId = column.SortMemberPath ?? "";
                        if (!wanted.TryGetValue(colId, out var found))
                            continue;
                        var (kind, value) = found;
                        if (value <= 0)
                            continue;
                        if (kind == "star")
                            column.Width = new DataGridLength(value, DataGridLengthUnitType.Star);
                        else
                            column.Width = new DataGridLength(value);
                    }
                }
                catch (Exception)
                {
                }
            }

            /// <summary>
            /// Window size and column widths, into the global settings. Per machine,
            /// because a size that suits a 4K panel is wrong on a laptop.
            /// </summary>
            public void RememberWindow()
            {
                try
                {
                    // The size it was left at, not the shrunk title bar's.
                    var (width, height) = Chrome.TrueSize();
                    Settings.Set("window_width", (int)width);
                    Settings.Set("window_height", (int)height);
                }
                catch (Exception)
                {
                }
                try
                {
                    Settings.Set("column_widths", PsConfig.PutList(ColumnWidths()));
                }
                catch (Exception)
                {
                }
                Settings.Save();
            }

            /// <summary>Once, after the window is first drawn: measure the footer and the whole window again.</summary>
            internal bool SettleLayout(object sender = null, EventArgs args = null)
            {
                try
                {
                    if (SettleHandler != null)
                        Window.ContentRendered -= SettleHandler;
                }
                catch (Exception)
                {
                }
                foreach (string name in new[] { "FooterButtons", "FooterDock" })
                {
                    if (!(C(name) is UIElement control))
                        continue;
                    try
                    {
                        control.InvalidateMeasure();
                    }
                    catch (Exception)
                    {
                    }
                }
                try
                {
                    ((UIElement)Window.Content).InvalidateMeasure();
                    Window.UpdateLayout();
                }
                catch (Exception)
                {
                }
                ScrollToPreselection();
                return true;
            }

            public void RestoreWindow()
            {
                try
                {
                    int width = Settings.Number("window_width");
                    int height = Settings.Number("window_height");
                    if (width >= Window.MinWidth)
                        Window.Width = width;
                    if (height >= Window.MinHeight)
                        Window.Height = height;
                }
                catch (Exception)
                {
                }
            }

            // ------------------------------------------- adding and removing
            public void AddColumns(object sender = null, RoutedEventArgs args = null, string after = null)
            {
                PsModel.Row sampleRow = FirstTickedRow() ?? (Rows.Count > 0 ? Rows[0] : null);
                PsModel.RowLookup lookup = sampleRow != null ? LookupFor(sampleRow) : null;
                string label = "";
                if (sampleRow != null)
                    label = !string.IsNullOrEmpty(sampleRow.Number) ? sampleRow.Number : sampleRow.Name;
                List<string> chosen = PsPickWin.Pick(Catalogue, lookup, ThemeName, Window,
                                                     "Add columns", ParameterColumns(), label);
                if (chosen == null || chosen.Count == 0)
                    return;

                // Land beside the heading that was right clicked, not on the far right.
                int where = ColumnOrder.Count;
                if (after != null && ColumnOrder.Contains(after))
                    where = ColumnOrder.IndexOf(after) + 1;
                for (int offset = 0; offset < chosen.Count; offset++)
                {
                    string colId = "p:" + chosen[offset];
                    if (ColumnOrder.Contains(colId))
                        continue;
                    ColumnOrder.Insert(Math.Min(where + offset, ColumnOrder.Count), colId);
                }

                BuildColumns();
                ApplyFilters();
                Say(string.Format(Inv, "{0} column{1} added. Right click a heading to remove one.",
                                  chosen.Count, Plural(chosen.Count)));
            }

            public void RemoveColumn(string colId)
            {
                if (!ColumnOrder.Contains(colId))
                    return;
                ColumnOrder.Remove(colId);
                ColumnSearch.Remove(colId);
                SortStack = SortStack.Where(pair => pair.ColId != colId).ToList();
                BuildColumns();
                ApplyFilters();
                Say("\"" + HeadingOf(colId) + "\" removed.");
            }

            public void ResetColumns(object sender = null, RoutedEventArgs args = null)
            {
                ColumnOrder = StartingColumns(ModeName(), DefaultExtras(), BrowserNames);
                ColumnSearch = new Dictionary<string, string>(StringComparer.Ordinal);
                SortStack = new List<(string ColId, bool Descending)>();
                ForgetSort();
                ApplyDefaultSort();
                Grouped = true;
                Collapsed = new HashSet<int>();
                SetChecked(C("GroupCheck"), true);
                BuildColumns();
                ApplyOrder();
                ApplyGrouping();
                ApplyFilters();
                Say("Back to the standard columns.");
            }

            public void ClearColumnSearches(object sender = null, RoutedEventArgs args = null)
            {
                ColumnSearch = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (TextBox box in SearchBoxes.Values.ToList())
                {
                    try
                    {
                        box.Text = "";
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
                ApplyFilters();
                RefreshCounts();
            }

            // ------------------------------------------------- the heading menu

            /// <summary>
            /// Right click on a column heading opens the column menu. Watched on the
            /// grid rather than on each heading, because the headings are rebuilt
            /// every time a column is added or moved.
            /// </summary>
            internal void HeaderRightClick(object sender, MouseButtonEventArgs args)
            {
                DataGridColumnHeader header;
                try
                {
                    header = HeaderUnder(args.OriginalSource);
                }
                catch (Exception)
                {
                    header = null;
                }
                if (header == null)
                {
                    HeadingRightClick(args);
                    return;
                }
                string colId;
                try
                {
                    colId = header.Column?.SortMemberPath ?? "";
                }
                catch (Exception)
                {
                    colId = "";
                }
                try
                {
                    ContextMenu menu = ColumnMenu(colId);
                    menu.PlacementTarget = header;
                    menu.IsOpen = true;
                    args.Handled = true;
                }
                catch (Exception)
                {
                }
            }

            // ------------------------------------------- heading colours

            /// <summary>A right-click on a group heading: its colour menu.</summary>
            internal void HeadingRightClick(MouseButtonEventArgs args)
            {
                DataGridRow row = null;
                DataRow entry;
                try
                {
                    row = RowUnder(args.OriginalSource);
                    entry = row != null ? ((DataRowView)row.Item).Row : null;
                }
                catch (Exception)
                {
                    entry = null;
                }
                if (entry == null)
                    return;
                if (S(entry["ishead"]) != "1")
                {
                    RowRightClick(row, args);
                    return;
                }
                string label;
                try
                {
                    label = RunLabels[AsInt(entry["grp"])];
                }
                catch (Exception)
                {
                    return;
                }
                try
                {
                    ContextMenu menu = HeadingColourMenu(label);
                    menu.PlacementTarget = C<UIElement>("SheetGrid");
                    menu.IsOpen = true;
                    args.Handled = true;
                }
                catch (Exception)
                {
                }
            }

            // ------------------------------------------- open sheets

            /// <summary>
            /// A right-click on a sheet: Open sheets for what is highlighted. A row
            /// not already highlighted is highlighted on its own first - Excel's way.
            /// </summary>
            internal void RowRightClick(DataGridRow row, MouseButtonEventArgs args)
            {
                var grid = C<DataGrid>("SheetGrid");
                try
                {
                    if (row != null && !row.IsSelected)
                    {
                        grid.SelectedItems.Clear();
                        grid.SelectedItems.Add(row.Item);
                    }
                }
                catch (Exception)
                {
                }
                var entries = RowMenuEntries(HighlightedRows().Count);
                if (entries.Count == 0)
                    return;
                try
                {
                    var menu = new ContextMenu();
                    Styled(menu, "ThemedContextMenu");
                    foreach (var (text, action) in entries)
                    {
                        WpfMenuItem item = MenuItem();
                        item.Header = text;
                        item.Click += MakeRowAction(action);
                        menu.Items.Add(item);
                    }
                    menu.PlacementTarget = grid;
                    menu.IsOpen = true;
                    args.Handled = true;
                }
                catch (Exception)
                {
                }
            }

            /// <summary>[(text, action)] for a right-click on highlighted sheets.</summary>
            public List<(string Text, string Action)> RowMenuEntries(int count)
            {
                if (count <= 0)
                    return new List<(string, string)>();
                string word = IsViewsMode() ? "view" : "sheet";
                return new List<(string, string)> { ("Open " + word + Plural(count), "open_highlighted") };
            }

            internal RoutedEventHandler MakeRowAction(string action)
            {
                return (sender, args) =>
                {
                    if (action == "open_highlighted")
                        OpenHighlighted();
                };
            }

            /// <summary>The highlighted sheets (not headings), top of the list first.</summary>
            public List<PsModel.Row> HighlightedRows()
            {
                var grid = C<DataGrid>("SheetGrid");
                var found = new List<(int Place, PsModel.Row Row)>();
                List<object> items;
                try
                {
                    items = grid.SelectedItems.Cast<object>().ToList();
                }
                catch (Exception)
                {
                    return new List<PsModel.Row>();
                }
                foreach (object item in items)
                {
                    PsModel.Row row;
                    try
                    {
                        DataRow entry = ((DataRowView)item).Row;
                        if (S(entry["ishead"]) == "1")
                            continue;
                        RowsByKey.TryGetValue(AsKey(S(entry["key"])), out row);
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                    if (row == null)
                        continue;
                    int place;
                    try
                    {
                        place = grid.Items.IndexOf(item);
                    }
                    catch (Exception)
                    {
                        place = found.Count;
                    }
                    found.Add((place, row));
                }
                return found.OrderBy(pair => pair.Place).Select(pair => pair.Row).ToList();
            }

            public bool OpenHighlighted()
            {
                List<PsModel.Row> rows = HighlightedRows();
                string word = IsViewsMode() ? "view" : "sheet";
                return OpenSheets(rows.Select(row => row.Element), word);
            }

            /// <summary>
            /// Open the sheets in Revit, then shrink the window to the bottom of the
            /// screen so they can be seen. Used by Selection and the Document
            /// Register alike.
            /// </summary>
            public bool OpenSheets(IEnumerable<Element> views, string word = "sheet")
            {
                List<Element> wanted = (views ?? Enumerable.Empty<Element>()).Where(view => view != null).ToList();
                if (wanted.Count == 0)
                {
                    Say("Highlight the " + word + "s to open first.");
                    return false;
                }
                if (Exporting)
                {
                    Say("Wait for the export to finish before opening " + word + "s.");
                    return false;
                }

                Action<Autodesk.Revit.UI.UIApplication> job = uiapp =>
                {
                    (int Opened, List<string> Errors) result;
                    try
                    {
                        result = PsRevisions.OpenViews(uiapp.ActiveUIDocument, wanted.OfType<View>());
                    }
                    catch (Exception err)
                    {
                        result = (0, new List<string> { err.Message });
                    }
                    OnUi(() => Say(PsRevisions.OpenedReport(result.Opened, result.Errors, word)));
                };
                if (!Queue(job))
                    return false;
                Say(string.Format(Inv, "Opening {0} {1}{2}...", wanted.Count, word, Plural(wanted.Count)));
                try
                {
                    Chrome.Shrink();
                }
                catch (Exception)
                {
                }
                return true;
            }

            /// <summary>[(text, action)] for a heading's colour menu.</summary>
            public List<(string Text, string Action)> HeadingMenuEntries(string label)
            {
                var custom = HeadingCustom ?? new Dictionary<string, string>(StringComparer.Ordinal);
                var entries = new List<(string, string)>
                {
                    ("Colour \"" + label + "\"", "swatches"),
                    ("Custom colour...", "custom"),
                };
                if (label != null && custom.ContainsKey(label))
                    entries.Add(("Reset this heading's colour", "reset"));
                if (custom.Count > 0)
                    entries.Add(("Reset every heading colour", "reset_all"));
                return entries;
            }

            internal ContextMenu HeadingColourMenu(string label)
            {
                var menu = new ContextMenu();
                Styled(menu, "ThemedContextMenu");
                foreach (var (text, action) in HeadingMenuEntries(label))
                {
                    if (action == "swatches")
                    {
                        menu.Items.Add(SwatchItem(text, label, menu));
                        continue;
                    }
                    WpfMenuItem item = MenuItem();
                    item.Header = text;
                    item.Click += MakeHeadingAction(action, label);
                    menu.Items.Add(item);
                }
                return menu;
            }

            internal RoutedEventHandler MakeHeadingAction(string action, string label)
            {
                return (sender, args) =>
                {
                    if (action == "custom")
                    {
                        string typed = PsUi.AskText(
                            "Heading colour",
                            "Colour for \"" + label + "\", as #RRGGBB:",
                            HeadingCustom.TryGetValue(label, out string current) ? current : "#",
                            ThemeName, Window);
                        if (typed == null)
                            return;
                        string colour = PsRamp.ParseHex(typed);
                        if (colour == null)
                        {
                            Say("\"" + typed + "\" is not a colour - type six hex digits, like #3FA75A.");
                            return;
                        }
                        SetHeadingColour(label, colour);
                    }
                    else if (action == "reset")
                    {
                        var colours = new Dictionary<string, string>(HeadingCustom, StringComparer.Ordinal);
                        colours.Remove(label);
                        KeepHeadingColours(colours);
                        Say("\"" + label + "\" is back to grey.");
                    }
                    else if (action == "reset_all")
                    {
                        KeepHeadingColours(new Dictionary<string, string>(StringComparer.Ordinal));
                        Say("Every heading colour reset.");
                    }
                };
            }

            internal WpfMenuItem SwatchItem(string text, string label, ContextMenu menu)
            {
                WpfMenuItem item = MenuItem();
                item.StaysOpenOnClick = true;
                var panel = new StackPanel();
                panel.Orientation = Orientation.Vertical;
                var title = new TextBlock();
                title.Text = text;
                title.Margin = new Thickness(0, 0, 0, 4);
                panel.Children.Add(title);
                var wrap = new WrapPanel();
                wrap.Width = 6 * 24;
                foreach (string colour in PsRamp.Swatches)
                {
                    var swatch = new Border();
                    swatch.Width = 20;
                    swatch.Height = 20;
                    swatch.Margin = new Thickness(2);
                    swatch.CornerRadius = new CornerRadius(3);
                    swatch.BorderThickness = new Thickness(1);
                    swatch.SetResourceReference(Border.BorderBrushProperty, "EdgeBrush");
                    swatch.Background = PsTheme.Brush(colour);
                    swatch.ToolTip = colour;
                    swatch.MouseLeftButtonUp += MakeSwatchPick(label, colour, menu);
                    wrap.Children.Add(swatch);
                }
                panel.Children.Add(wrap);
                item.Header = panel;
                return item;
            }

            internal MouseButtonEventHandler MakeSwatchPick(string label, string colour, ContextMenu menu)
            {
                return (sender, args) =>
                {
                    try
                    {
                        args.Handled = true;
                        menu.IsOpen = false;
                    }
                    catch (Exception)
                    {
                    }
                    SetHeadingColour(label, colour);
                };
            }

            /// <summary>One heading's colour; Custom headers from now on.</summary>
            public void SetHeadingColour(string label, string colour)
            {
                var colours = new Dictionary<string, string>(HeadingCustom, StringComparer.Ordinal);
                colours[label] = colour;
                if (HeadingMode != PsRamp.Custom)
                {
                    HeadingMode = PsRamp.Custom;
                    Settings.Set("sel_heading_mode", HeadingMode);
                    Settings.Save();
                }
                KeepHeadingColours(colours);
                Say("\"" + label + "\" is now " + colour + ". Custom headers - the button cycles back to grey.");
            }

            /// <summary>
            /// Save the project's heading colours, and hand them to the register
            /// too: one set of colours for both tabs.
            /// </summary>
            internal void KeepHeadingColours(Dictionary<string, string> colours)
            {
                try
                {
                    PsConfig.WriteHeadingColours(Doc, colours);
                }
                catch (Exception err)
                {
                    Say("The heading colours could not be saved: " + err.Message);
                }
                TakeHeadingColours(colours);
                try
                {
                    Register.TakeHeadingColours(colours);
                }
                catch (Exception)
                {
                }
            }

            /// <summary>The project's heading colours, changed on either tab.</summary>
            public void TakeHeadingColours(IDictionary<string, string> colours)
            {
                HeadingCustom = colours != null
                    ? new Dictionary<string, string>(colours, StringComparer.Ordinal)
                    : new Dictionary<string, string>(StringComparer.Ordinal);
                RepaintHeadings();
            }

            /// <summary>The button: Coloured, Grey, Custom, round.</summary>
            public void CycleHeadingMode(object sender = null, RoutedEventArgs args = null)
            {
                HeadingMode = PsRamp.NextMode(HeadingMode);
                Settings.Set("sel_heading_mode", HeadingMode);
                Settings.Save();
                RepaintHeadings();
                if (HeadingMode == PsRamp.Custom && HeadingCustom.Count == 0)
                    Say("Custom headers: right-click a heading to pick its colour. Until then they are grey.");
                else
                    Say(PsRamp.ModeLabels[HeadingMode] + ".");
            }

            internal void RepaintHeadings()
            {
                PsUi.SetText(C("SelectionHeadingModeText"),
                             PsRamp.ModeLabels.TryGetValue(HeadingMode ?? "", out string label) ? label : "");
                try
                {
                    ApplyGrouping();
                    ApplyFilters();
                    C<DataGrid>("SheetGrid").Items.Refresh();
                }
                catch (Exception)
                {
                }
            }

            /// <summary>Walk up from whatever was clicked to its column heading.</summary>
            internal DataGridColumnHeader HeaderUnder(object source)
            {
                object node = source;
                for (int step = 0; step < 12; step++)
                {
                    if (node == null)
                        return null;
                    if (node is DataGridColumnHeader header)
                        return header;
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

            internal ContextMenu ColumnMenu(string colId)
            {
                var menu = new ContextMenu();
                Styled(menu, "ThemedContextMenu");

                WpfMenuItem add = MenuItem();
                add.Header = "Add column...";
                add.Click += MakeAddAfter(colId);
                menu.Items.Add(add);

                if (IsParameterColumn(colId))
                {
                    WpfMenuItem remove = MenuItem();
                    remove.Header = "Remove \"" + HeadingOf(colId) + "\"";
                    remove.Click += MakeRemove(colId);
                    menu.Items.Add(remove);
                }

                if (ColumnSearch.Values.Any(value => !string.IsNullOrEmpty(value)))
                {
                    menu.Items.Add(new Separator());
                    WpfMenuItem clear = MenuItem();
                    clear.Header = "Clear every column search";
                    clear.Click += ClearColumnSearches;
                    menu.Items.Add(clear);
                }

                if (ParameterColumns().Count > 0 || SortStack.Count > 0)
                {
                    menu.Items.Add(new Separator());
                    WpfMenuItem reset = MenuItem();
                    reset.Header = "Back to the standard columns";
                    reset.Click += ResetColumns;
                    menu.Items.Add(reset);
                }
                return menu;
            }

            internal WpfMenuItem MenuItem()
            {
                var item = new WpfMenuItem();
                Styled(item, "ThemedMenuItem");
                return item;
            }

            internal RoutedEventHandler MakeAddAfter(string colId)
            {
                return (sender, args) => AddColumns(after: colId);
            }

            internal RoutedEventHandler MakeRemove(string colId)
            {
                return (sender, args) => RemoveColumn(colId);
            }

            internal void TickChanged(object sender, DataColumnChangeEventArgs args)
            {
                try
                {
                    if (args.Column.ColumnName != "sel")
                        return;
                }
                catch (Exception)
                {
                    return;
                }
                if (SuspendTicks)
                    return;

                DataRow entry;
                try
                {
                    entry = args.Row;
                }
                catch (Exception)
                {
                    entry = null;
                }

                if (entry != null && IsHeading(entry))
                {
                    // The tick on a group heading ticks the group. It arrives here
                    // like any other change and is turned into the group's worth.
                    TickGroup(entry);
                }
                else if (entry != null && SpreadTick(entry))
                {
                    SyncGroupTicks();
                }
                else
                {
                    // And the other direction: tick the last unticked sheet in a
                    // group by hand and its heading should agree.
                    SyncGroupTicks();
                }

                RefreshCounts();
                RefreshPlan();
            }

            /// <summary>
            /// Push a tick out across the rows highlighted with it. Returns whether
            /// it went anywhere. The highlighted keys were taken in RowClick.
            /// </summary>
            internal bool SpreadTick(DataRow changed)
            {
                HashSet<string> picked = TickSelection ?? new HashSet<string>(StringComparer.Ordinal);
                // One use only. Ticking by keyboard, or a second tick without a
                // fresh click, is one row's business.
                TickSelection = new HashSet<string>(StringComparer.Ordinal);
                if (picked.Count == 0)
                    return false;
                string key;
                bool wanted;
                try
                {
                    key = S(changed["key"]);
                    wanted = B(changed["sel"]);
                }
                catch (Exception)
                {
                    return false;
                }
                HashSet<string> targets = TickTargets(key, picked);
                if (targets.Count < 2)
                    return false;

                SuspendTicks = true;
                int moved = 0;
                try
                {
                    foreach (DataRow entry in Table.Rows)
                    {
                        if (IsHeading(entry))
                            continue;
                        if (!targets.Contains(S(entry["key"])))
                            continue;
                        if (B(entry["sel"]) != wanted)
                        {
                            entry["sel"] = wanted;
                            moved++;
                        }
                    }
                }
                catch (Exception)
                {
                }
                finally
                {
                    SuspendTicks = false;
                }
                if (moved != 0)
                {
                    Say(string.Format(Inv, "{0} highlighted {1}s {2}.", targets.Count,
                                      IsViewsMode() ? "view" : "sheet", wanted ? "ticked" : "unticked"));
                }
                return true;
            }

            internal bool IsHeading(DataRow entry)
            {
                try
                {
                    return S(entry["ishead"]) == "1";
                }
                catch (Exception)
                {
                    return false;
                }
            }

            /// <summary>Push a heading's tick down onto every member of its group.</summary>
            internal void TickGroup(DataRow heading)
            {
                int group = AsInt(heading["gid"]);
                if (!Groups.TryGetValue(group, out List<DataRow> members) || members.Count == 0)
                    return;
                bool wanted;
                try
                {
                    wanted = B(heading["sel"]);
                }
                catch (Exception)
                {
                    return;
                }
                SuspendTicks = true;
                try
                {
                    foreach (DataRow entry in members)
                    {
                        // Hidden members included. A collapsed group is still a group.
                        entry["sel"] = wanted;
                    }
                }
                finally
                {
                    SuspendTicks = false;
                }
            }

            /// <summary>
            /// Each heading's tick reflects whether its whole group is ticked. No
            /// early return when there are no groups: a heading whose group has gone
            /// is exactly the row that would otherwise keep a stale tick.
            /// </summary>
            internal void SyncGroupTicks()
            {
                SuspendTicks = true;
                try
                {
                    foreach (DataRow entry in Table.Rows)
                    {
                        if (!IsHeading(entry))
                            continue;
                        List<DataRow> members = Groups.TryGetValue(AsInt(entry["gid"]), out var found)
                            ? found : new List<DataRow>();
                        bool whole = members.Count > 0 && members.All(member => B(member["sel"]));
                        if (B(entry["sel"]) != whole)
                            entry["sel"] = whole;
                    }
                }
                catch (Exception)
                {
                }
                finally
                {
                    SuspendTicks = false;
                }
            }

            /// <summary>Python _header_tick (renamed: clashes with the HeaderTick attribute).</summary>
            internal void HeaderTickClicked(object sender, RoutedEventArgs args)
            {
                bool wanted;
                try
                {
                    wanted = ((ToggleButton)sender).IsChecked == true;
                }
                catch (Exception)
                {
                    wanted = true;
                }
                SetAll(wanted, visibleOnly: true);
            }

            // ==================================================================
            // what the Document Register tab asks of the window
            //
            // The register keeps its own list of what is in it, so all it needs
            // from here is the sheets, and to know when it is on screen.
            // ==================================================================

            public bool OnRegisterTab()
            {
                return TabIndex() == TabRegister;
            }

            /// <summary>
            /// Every sheet, read the way the Selection tab reads them: the rows
            /// already in hand when on sheets, read afresh when on views.
            /// </summary>
            public List<PsModel.Row> SheetRows()
            {
                if (!IsViewsMode())
                    return new List<PsModel.Row>(Rows);
                return PsModel.ReadRows(Doc, "sheets");
            }
        }
    }
}
