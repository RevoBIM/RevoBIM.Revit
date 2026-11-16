using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using Autodesk.Revit.DB;
using RevoBIM.Tools.FilterManager;
using ComboBox = System.Windows.Controls.ComboBox;
using TextBox = System.Windows.Controls.TextBox;
using Panel = System.Windows.Controls.Panel;
using Visibility = System.Windows.Visibility;

using Grid = System.Windows.Controls.Grid;

namespace RevoBIM.UI.FilterManager
{
    // =======================================================================
    //  TAB 2 - FILTER MANAGER TABLE   (script.py 2568-2863 and 3327-3421)
    //  Every filter on one row block: its name, its categories stacked one
    //  under another, and one row per rule.
    //  This file: column widths, the header with its per-column search, sorting,
    //  which blocks are on show, and the debug strip.
    //  FmWindow.TableBlock.cs: one filter (hydrate, paint, cells).
    //  FmWindow.TableExcel.cs / FmWindow.TableApply.cs: Excel round trip, writing back.
    // =======================================================================
    public partial class FmWindow
    {
        // the status Revit answered the last write request with (the debug strip shows it)
        private string tableLastRequest = "nothing sent yet";

        // -- column widths --------------------------------------------------------
        private double TableColWidth(string key)
        {
            for (int index = 0; index < TableColumns.Length; index++)
            {
                if (TableColumns[index].Key == key) return ColumnWidths()[index];
            }
            return 100;
        }

        /// <summary>What each column is currently worth, in pixels.</summary>
        private double[] ColumnWidths()
        {
            if (widthsNow != null && widthsNow.Length > 0) return widthsNow;
            return TableColumns.Select(c => c.Width).ToArray();
        }

        /// <summary>Share the width of the page out, and remember the answer.</summary>
        private double[] MeasureColumns()
        {
            double available;
            try { available = pnlTableScroll.ViewportWidth; }
            catch (Exception) { available = 0; }
            if (double.IsNaN(available) || available <= 0) return ColumnWidths();

            // the border either side, and room for the vertical scrollbar
            available = available - 2;
            widthsNow = FmCore.DistributeWidths(
                TableColumns.Select(c => c.Width).ToArray(),
                TableColumns.Select(c => c.Share).ToArray(),
                available);
            return widthsNow;
        }

        /// <summary>
        /// Push the widths onto the heading row and every painted row. The grids are adjusted rather than
        /// rebuilt: a resize should not cost the whole table, and rebuilding would take the focus out of
        /// whatever cell is being typed in.
        /// </summary>
        private void ApplyColumnWidths()
        {
            double[] widths = MeasureColumns();
            double total = widths.Sum();

            var grids = new List<Grid>();
            if (header != null) grids.Add(header);
            foreach (FmBlock block in tableBlocks)
            {
                if (block.Grid != null) grids.Add(block.Grid);
            }

            foreach (Grid grid in grids)
            {
                try
                {
                    grid.Width = total;
                    for (int index = 0; index < Math.Min(widths.Length, grid.ColumnDefinitions.Count); index++)
                        grid.ColumnDefinitions[index].Width = FmUi.Pixels(widths[index]);
                }
                catch (Exception) { continue; }
            }
        }

        public void OnTableResized(object sender, RoutedEventArgs args) { ApplyColumnWidths(); }

        private double TableTotalWidth() { return ColumnWidths().Sum(); }

        /// <summary>Give a grid the widths the rest of the table is using (nothing is done until they are known).</summary>
        private void PlaceWidths(Grid grid)
        {
            if (grid == null || widthsNow == null || widthsNow.Length == 0) return;
            try
            {
                grid.Width = widthsNow.Sum();
                for (int index = 0; index < Math.Min(widthsNow.Length, grid.ColumnDefinitions.Count); index++)
                    grid.ColumnDefinitions[index].Width = FmUi.Pixels(widthsNow[index]);
            }
            catch (Exception) { }
        }

        /// <summary>Give a row the widths the rest of the table is using.</summary>
        private void TablePlaceWidths(FmBlock block) { PlaceWidths(block.Grid); }

        // -- the table, built once ------------------------------------------------
        /// <summary>
        /// Build a block per filter, once. The blocks hold pending edits, so rebuilding them on every
        /// keystroke in the search box would quietly throw away work. Filtering only decides which of them
        /// are on show.
        /// </summary>
        private void EnsureTableBlocks()
        {
            if (tableBlocks.Count > 0) return;
            tableBlocks = new List<FmBlock>();
            foreach (ParameterFilterElement pfe in allFilters)
            {
                try { tableBlocks.Add(TableBlock(pfe)); }
                catch (Exception) { continue; }
            }
        }

        private void BuildTableTab()
        {
            EnsureTableBlocks();
            if (header == null) RebuildHeader();
            FillTableRows();
            ApplyColumnWidths();
        }

        private void RebuildHeader()
        {
            pnlTableHead.Children.Clear();
            header = TableHeader();
            pnlTableHead.Children.Add(header);
            // a rebuilt heading starts where the rows are, not where they were a moment ago
            PlaceWidths(header);
            try { header.Margin = new Thickness(-pnlTableScroll.HorizontalOffset, 0, 0, 0); }
            catch (Exception) { }
        }

        /// <summary>Show the blocks that match, without touching the header.</summary>
        private void FillTableRows()
        {
            pnlTableRows.Children.Clear();
            tableVisible = new List<FmBlock>();

            bool unusedOnly = chkTblUnused.IsChecked == true;
            bool changedOnly = chkTblChanged.IsChecked == true;

            int shown = 0;
            int changed = 0;
            foreach (FmBlock block in tableBlocks)
            {
                if (block.Dirty) changed++;
                if (changedOnly && !block.Dirty) continue;
                if (unusedOnly && BlockUses(block) > 0) continue;
                if (!BlockMatches(block)) continue;
                Hydrate(block);
                pnlTableRows.Children.Add(block.Host);
                TablePlaceWidths(block);
                tableVisible.Add(block);
                shown++;
            }

            if (changed > 0)
                txtTblCount.Text = shown + " of " + tableBlocks.Count + " filters   -   " + changed + " edited";
            else
                txtTblCount.Text = shown + " of " + tableBlocks.Count + " filters";
            chkTblChanged.IsEnabled = changed > 0;
        }

        private static readonly string[] RuleColumns = { "parameter", "operator", "value" };

        /// <summary>How many views and view templates use this filter.</summary>
        private int BlockUses(FmBlock block)
        {
            if (!ReadFilterUsage) return 0;
            return UsageOf(block.Pfe.Id);
        }

        // -- searching ------------------------------------------------------------
        /// <summary>
        /// The searchable text of a block, worked out once and kept. deep asks for the rule columns as well,
        /// which means reading the filter's rules. Searching by name, use count or category never does that,
        /// so typing in those boxes stays cheap on a big project.
        /// </summary>
        private Dictionary<string, string> BlockText(FmBlock block, bool deep = false)
        {
            if (deep) Hydrate(block);
            if (block.Search != null) return block.Search;

            var categories = new List<string>();
            foreach (ElementId cid in block.Cats) categories.Add(FmFilters.CategoryName(Doc, cid) ?? "");

            var parameters = new List<string>();
            var operators = new List<string>();
            var values = new List<string>();
            foreach (FmRule rule in block.Rules)
            {
                if (rule.ParamId != null) parameters.Add(FmFilters.ParameterName(Doc, rule.ParamId));
                operators.Add(FmFilters.LabelOf(rule.Op));
                values.Add(RuleValueText(rule));
            }

            block.Search = new Dictionary<string, string>
            {
                { "name", block.Name },
                { "uses", BlockUses(block).ToString() },
                { "categories", string.Join(" ", categories) },
                { "parameter", string.Join(" ", parameters) },
                { "operator", string.Join(" ", operators) },
                { "value", string.Join(" ", values) },
            };
            return block.Search;
        }

        /// <summary>The box above the table, and the box under each column heading.</summary>
        private bool BlockMatches(FmBlock block)
        {
            bool deep = false;
            foreach (string k in RuleColumns)
            {
                string typed;
                if (columnSearch.TryGetValue(k, out typed) && !string.IsNullOrEmpty(typed)) { deep = true; break; }
            }
            Dictionary<string, string> text = BlockText(block, deep);

            // the box above the table searches the name and the categories, so
            // "tray duct" finds a tray filter on duct accessories
            if (!FmCore.ContainsAll(txtTblSearch.Text, new[] { text["name"], text["categories"], text["uses"] }))
                return false;

            foreach (string key in columnSearch.Keys.ToList())
            {
                string wanted = columnSearch[key];
                if (string.IsNullOrEmpty(wanted)) continue;
                if (key == "uses")
                {
                    if (!FmCore.UsesMatch(BlockUses(block), wanted)) return false;
                }
                else
                {
                    string haystack;
                    if (!text.TryGetValue(key, out haystack)) haystack = "";
                    if (!FmCore.ContainsAll(wanted, new[] { haystack })) return false;
                }
            }
            return true;
        }

        // -- the heading ----------------------------------------------------------
        /// <summary>
        /// Two rows: the headings, and a search box under each column. The same shape as the Excel tool - a
        /// keyword box sitting in the column it searches, rather than a row of boxes somewhere else.
        /// </summary>
        private Grid TableHeader()
        {
            var grid = new Grid();
            grid.Width = TableTotalWidth();
            grid.HorizontalAlignment = FmUi.Left();
            foreach (TableColumn column in TableColumns) grid.ColumnDefinitions.Add(FmUi.Col(pixels: column.Width));
            grid.RowDefinitions.Add(FmUi.Row());
            grid.RowDefinitions.Add(FmUi.Row());

            for (int index = 0; index < TableColumns.Length; index++)
            {
                TableColumn column = TableColumns[index];
                if (column.Key == "name" || column.Key == "uses")
                    TablePlace(grid, SortHeader(column.Key, column.Label), 0, index);
                else
                {
                    var label = new TextBlock
                    {
                        Text = column.Label,
                        FontSize = 10,
                        FontWeight = FontWeights.Bold,
                        Margin = new Thickness(8, 7, 6, 4),
                    };
                    label.SetResourceReference(TextBlock.ForegroundProperty, "Dim");
                    TablePlace(grid, label, 0, index);
                }

                if (columnSearch.ContainsKey(column.Key))
                    TablePlace(grid, ColumnSearchBox(column.Key), 1, index);
            }
            return grid;
        }

        /// <summary>A heading that sorts the table when it is clicked.</summary>
        private Button SortHeader(string key, string label)
        {
            string arrow = "";
            if (sortKey == key) arrow = sortAscending ? "  ^" : "  v";

            Button button = FmUi.NewButton(label + arrow, "Ghost", height: 22);
            button.FontSize = 10;
            button.Margin = new Thickness(4, 5, 4, 2);
            button.HorizontalAlignment = FmUi.Left();
            button.ToolTip = "Sort by " + label;

            string column = key;
            button.Click += FmUi.Safe((s, a) => SortTable(column), "sort_table");
            return button;
        }

        private TextBox ColumnSearchBox(string key)
        {
            var hints = new Dictionary<string, string>
            {
                { "name", "name" }, { "uses", "0, >2, 1-4" }, { "categories", "category" },
                { "parameter", "parameter" }, { "operator", "operator" }, { "value", "value" },
            };
            string current;
            columnSearch.TryGetValue(key, out current);
            string hint;
            if (!hints.TryGetValue(key, out hint)) hint = "";

            TextBox box = FmUi.NewTextBox(current ?? "", hint);
            box.Height = FmUi.CellHeight;
            box.FontSize = 11;
            box.Margin = new Thickness(4, 0, 4, 6);
            if (key == "uses")
                box.ToolTip = "A number, or >2, >=2, <5, <=1, <>0, or a range like 2-5";

            string column = key;
            box.TextChanged += FmUi.SafeText((s, a) =>
            {
                columnSearch[column] = ((TextBox)s).Text;
                searches["table"].Poke();
            }, "column search");
            return box;
        }

        /// <summary>Sort the blocks themselves, so the order survives a re-filter.</summary>
        private void SortTable(string key)
        {
            if (sortKey == key) sortAscending = !sortAscending;
            else
            {
                sortKey = key;
                sortAscending = true;
            }

            try
            {
                IEnumerable<FmBlock> sorted;
                if (key == "uses")
                {
                    sorted = sortAscending
                        ? tableBlocks.OrderBy(b => BlockUses(b)).ThenBy(b => SortName(b), StringComparer.Ordinal)
                        : tableBlocks.OrderByDescending(b => BlockUses(b)).ThenByDescending(b => SortName(b), StringComparer.Ordinal);
                }
                else
                {
                    sorted = sortAscending
                        ? tableBlocks.OrderBy(b => SortName(b), StringComparer.Ordinal)
                        : tableBlocks.OrderByDescending(b => SortName(b), StringComparer.Ordinal);
                }
                tableBlocks = sorted.ToList();
            }
            catch (Exception) { }
            // the heading shows which column is sorted, so it is drawn again
            RebuildHeader();
            BuildTableTab();
        }

        private static string SortName(FmBlock block) { return (block.Name ?? "").ToLowerInvariant(); }

        /// <summary>Place a cell.</summary>
        private static UIElement TablePlace(Grid grid, UIElement element, int row, int column)
        {
            Grid.SetRow(element, row);
            Grid.SetColumn(element, column);
            grid.Children.Add(element);
            return element;
        }

        // -- search box, filters, scrolling ---------------------------------------
        public void OnTblSearch(object sender, RoutedEventArgs args) { searches["table"].Poke(); }

        /// <summary>Keep the headings over their columns when the table scrolls.</summary>
        public void OnTableScrolled(object sender, RoutedEventArgs args)
        {
            try
            {
                if (header != null)
                {
                    ScrollViewer viewer = sender as ScrollViewer ?? pnlTableScroll;
                    header.Margin = new Thickness(-viewer.HorizontalOffset, 0, 0, 0);
                }
            }
            catch (Exception) { }
        }

        public void OnTblUnused(object sender, RoutedEventArgs args) { BuildTableTab(); }

        public void OnTblChangedOnly(object sender, RoutedEventArgs args) { BuildTableTab(); }

        // -- the debug strip ------------------------------------------------------
        public void OnToggleDebug(object sender, RoutedEventArgs args)
        {
            bool showing = pnlDebug.Visibility != Visibility.Collapsed;
            FmUi.SetVisible(pnlDebug, !showing);
            try
            {
                pnlDebugCaret.Data = FmUi.Geometry(!showing ? "M 0,0 L 9,0 L 4.5,7 Z" : "M 0,0 L 7,4.5 L 0,9 Z");
            }
            catch (Exception) { }
            if (!showing) RefreshDebug();
        }

        public void OnDebugRefresh(object sender, RoutedEventArgs args) { RefreshDebug(); }

        public void OnDebugCopy(object sender, RoutedEventArgs args)
        {
            try
            {
                Clipboard.SetText(txtDebug.Text);
                txtStatus.Text = "Debug details copied to the clipboard.";
            }
            catch (Exception)
            {
                txtStatus.Text = "The clipboard would not take it.";
            }
        }

        public void OnDebugOpen(object sender, RoutedEventArgs args) { FmCore.OpenExternally(FmCore.SettingsFolder()); }

        /// <summary>How many requests are queued for Revit and not yet run.</summary>
        private int QueuedWork()
        {
            try
            {
                FieldInfo field = typeof(FmActionHandler).GetField("_queue", BindingFlags.Instance | BindingFlags.NonPublic);
                var queue = field == null ? null : field.GetValue(runner.Handler) as System.Collections.ICollection;
                return queue == null ? 0 : queue.Count;
            }
            catch (Exception) { return 0; }
        }

        /// <summary>What the tool knows about itself, in one readable block.</summary>
        private void RefreshDebug()
        {
            var lines = new List<string>();
            lines.Add("RevoBIM Filter Manager " + FmCore.Version);
            string runtime;
            try { runtime = RuntimeInformation.FrameworkDescription; }
            catch (Exception) { runtime = Environment.Version.ToString(); }
            lines.Add("Revit " + FmCore.RevitVersion() + "   " + runtime);
            lines.Add("Model: " + Doc.Title);
            lines.Add("");

            lines.Add("SWITCHES");
            lines.Add("  MODELESS            " + (Modeless ? "True" : "False"));
            lines.Add("  READ_FILTER_USAGE   " + (ReadFilterUsage ? "True" : "False"));
            lines.Add("");

            lines.Add("WRITING");
            if (runner == null)
                lines.Add("  no runner - the tool cannot write at all");
            else
            {
                bool created = Modeless && runner.CreateError == null;
                bool direct = !Modeless || runner.CreateError != null;
                lines.Add("  ExternalEvent       " + (created ? "created" : "NOT created"));
                lines.Add("  running directly    " + (direct ? "True" : "False"));
                if (!string.IsNullOrEmpty(runner.CreateError))
                {
                    lines.Add("  creation failed:");
                    string[] parts = runner.CreateError.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
                    foreach (string line in parts.Skip(Math.Max(0, parts.Length - 4)))
                        lines.Add("      " + line);
                }
                lines.Add("  last answer         " + tableLastRequest);
                lines.Add("  queued and waiting  " + QueuedWork());
            }
            lines.Add("");

            lines.Add("WHAT IS LOADED");
            lines.Add("  filters             " + allFilters.Count);
            lines.Add("  view templates      " + templates.Count);
            lines.Add("  table blocks        " + tableBlocks.Count);
            lines.Add("  showing             " + tableVisible.Count);
            List<FmBlock> dirty = tableBlocks.Where(b => b.Dirty).ToList();
            lines.Add("  edited, not applied " + dirty.Count);
            foreach (FmBlock block in dirty.Take(10))
            {
                string what = string.Join(", ", block.Changes.OrderBy(c => c, StringComparer.Ordinal));
                if (what.Length == 0) what = "flagged";
                lines.Add("      " + block.Name + "   [" + what + "]");
            }
            lines.Add("");

            lines.Add("LAST RUN, most recent last");
            foreach (string line in FmCore.RecentCrumbs(14)) lines.Add("  " + line);
            lines.Add("");
            lines.Add("Files: " + FmCore.SettingsFolder());

            txtDebug.Text = string.Join("\n", lines);
        }
    }
}
