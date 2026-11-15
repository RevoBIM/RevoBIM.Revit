// Excel for Revit: window part 5a (efr_core.py 8421-8681): clipboard, context menu, paste, clear, fill down / series.
using System;
using System.Collections.Generic;
using System.Data;
using System.Globalization;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using RevoBIM.Tools.ExcelForRevit;
using static RevoBIM.Tools.ExcelForRevit.Efr;
using static RevoBIM.UI.ExcelForRevit.EfrUi;

namespace RevoBIM.UI.ExcelForRevit
{
    public partial class ExcelForRevitWindow
    {
        // -- clipboard ----------------------------------------------------------

        /// <summary>The model row index of a grid item (a DataRowView), Python int(item['ridx']).</summary>
        internal static int P5Ridx(object item)
        {
            return Convert.ToInt32(((DataRowView)item)["ridx"], CultureInfo.InvariantCulture);
        }

        /// <summary>Python walk_up: the first ancestor (or self) of this type, within 60 visual steps.</summary>
        internal static T P5WalkUp<T>(object element) where T : class
        {
            object node = element;
            int guard = 0;
            while (node != null && guard < 60)
            {
                T hit = node as T;
                if (hit != null) return hit;
                try
                {
                    node = VisualTreeHelper.GetParent((DependencyObject)node);
                }
                catch (Exception)
                {
                    return null;            // a content element has no visual parent
                }
                guard++;
            }
            return null;
        }

        /// <summary>Python cell_of: the DataGridCell that owns a generated cell element.</summary>
        internal static DataGridCell P5CellOf(FrameworkElement content)
        {
            if (content == null) return null;
            try
            {
                DataGridCell parent = content.Parent as DataGridCell;
                if (parent != null) return parent;
            }
            catch (Exception) { }
            return P5WalkUp<DataGridCell>(content);
        }

        private static string P5Plural(int n)
        {
            return n == 1 ? "" : "s";
        }

        public void OnCopy(object sender = null, EventArgs args = null)
        {
            var cells = SelCells();
            if (cells.Count == 0)
            {
                SetStatus("Nothing selected to copy.");
                return;
            }
            var grid = new Dictionary<(int, int), string>();
            var cols = new List<int>();
            var rows = new List<int>();
            foreach (var c in cells)
            {
                grid[(c.Pos, c.Col.DisplayIndex)] = TextAt(c.Pos, c.Col) ?? "";
                if (!cols.Contains(c.Col.DisplayIndex)) cols.Add(c.Col.DisplayIndex);
                if (!rows.Contains(c.Pos)) rows.Add(c.Pos);
            }
            cols.Sort();
            rows.Sort();
            var lines = new List<string>();
            foreach (int r in rows)
            {
                var parts = new List<string>();
                foreach (int cc in cols)
                {
                    string v;
                    parts.Add(grid.TryGetValue((r, cc), out v) ? v : "");
                }
                lines.Add(string.Join("\t", parts));
            }
            try
            {
                Clipboard.SetText(string.Join("\r\n", lines));
            }
            catch (Exception)
            {
                SetStatus("Could not reach the clipboard.");
                return;
            }
            SetCopyMarks(cells);
            SetStatus(string.Format(CultureInfo.InvariantCulture,
                "Copied {0} row{1} x {2} column{3} — select where it goes and press Ctrl+V. Escape clears it.",
                rows.Count, P5Plural(rows.Count), cols.Count, P5Plural(cols.Count)));
        }

        /// <summary>
        /// Show which cells the clipboard came from, the way Excel does.
        /// Kept as (row, field) rather than a screen position so the marks follow
        /// the data through a filter or a sort instead of pointing at whatever
        /// happens to be in that spot afterwards.
        /// </summary>
        public void SetCopyMarks(IEnumerable<SelCell> cells)
        {
            CopyMarks = new HashSet<(int, int)>(cells.Select(c => (c.Ridx, c.Fidx)));
            RepaintSoon();
        }

        public void ClearCopyMarks()
        {
            if (CopyMarks == null || CopyMarks.Count == 0) return;
            CopyMarks = new HashSet<(int, int)>();
            RepaintSoon();
        }

        /// <summary>Copy, then empty whatever of the selection can be emptied.</summary>
        public void OnCut(object sender = null, EventArgs args = null)
        {
            var cells = SelCells();
            if (cells.Count == 0)
            {
                SetStatus("Nothing selected to cut.");
                return;
            }
            OnCopy(null, null);
            BeginBatch();
            int n = 0;
            foreach (var c in cells)
            {
                if (StageCell(c.Pos, c.Col, "")) n++;
            }
            EndBatch();
            ClearCopyMarks();
            int skipped = cells.Count - n;
            string msg = string.Format(CultureInfo.InvariantCulture, "Cut {0} cell{1}.", n, P5Plural(n));
            if (skipped != 0)
                msg += SkippedNote(skipped, "copied but left alone");
            SetStatus(msg);
        }

        public void BeginEditCurrent()
        {
            try
            {
                Dg.BeginEdit();
            }
            catch (Exception) { }
        }

        /// <summary>
        /// Right-click selects the cell under the pointer unless it is already
        /// part of the selection: the Windows convention, and without it the menu
        /// would act on whatever was selected before.
        /// </summary>
        public void OnRightClick(object sender, MouseButtonEventArgs args)
        {
            try
            {
                IInputElement hit = Dg.InputHitTest(args.GetPosition(Dg));
                DataGridCell cell = P5WalkUp<DataGridCell>(hit);
                if (cell == null)
                {
                    // a heading: whichever menu opens should act on this column,
                    // not on the last cell that was right-clicked
                    DataGridColumnHeader header = P5WalkUp<DataGridColumnHeader>(hit);
                    if (header != null)
                    {
                        FieldInfo hf;
                        _menuCol = header.Column != null && ColField.TryGetValue(header.Column, out hf) ? hf : null;
                    }
                    return;
                }
                FieldInfo f;
                _menuCol = ColField.TryGetValue(cell.Column, out f) ? f : null;
                foreach (DataGridCellInfo info in Dg.SelectedCells)
                {
                    try
                    {
                        if (ReferenceEquals(info.Column, cell.Column) && ReferenceEquals(info.Item, cell.DataContext))
                            return;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
                Dg.SelectedCells.Clear();
                Dg.SelectedCells.Add(new DataGridCellInfo(cell.DataContext, cell.Column));
                Dg.CurrentCell = new DataGridCellInfo(cell.DataContext, cell.Column);
            }
            catch (Exception) { }
        }

        /// <summary>
        /// The right-click menu: the other half of what people expect from
        /// Windows, and the discoverable route to the same commands.
        /// </summary>
        public ContextMenu BuildContextMenu()
        {
            var menu = new ContextMenu();
            var items = new List<(string Label, string Gesture, RoutedEventHandler Handler)>();
            Action<string, string, RoutedEventHandler> add = (l, g, h) => items.Add((l, g, h));
            {
                add("Cut", "Ctrl+X", (s, e) => OnCut(s, e));
                add("Copy", "Ctrl+C", (s, e) => OnCopy(s, e));
                add("Paste", "Ctrl+V", (s, e) => OnPaste(s, e));
                add("Clear", "Delete", (s, e) => OnClear(s, e));
                add(null, null, null);
                add("Set Workset...", "F2", (s, e) => OnSetWorkset(s, e));
                add(null, null, null);
                add("Fill Down", "Ctrl+D", (s, e) => OnFillDown(s, e));
                add("Fill Series", "Ctrl+E", (s, e) => OnFillSeries(s, e));
                add(null, null, null);
                add("Undo", "Ctrl+Z", (s, e) => OnUndo(s, e));
                add("Redo", "Ctrl+Y", (s, e) => OnRedo(s, e));
                add(null, null, null);
                add("Formula...", "Ctrl+Shift+F", (s, e) => OnFormula(s, e));
                add("Number Sequence...", "Ctrl+Shift+N", (s, e) => OnSequence(s, e));
                add("Add Prefix / Suffix...", "Ctrl+Shift+P", (s, e) => OnAffix(s, e));
                add("Highlight...", "Ctrl+Shift+H", (s, e) => OnHighlight(s, e));
                add("Create Unique Sequence", null, (s, e) => OnUniqueSequence(s, e));
                add(null, null, null);
                add("Find and Replace...", "Ctrl+H", (s, e) => OnFind(s, e));
                add("Reapply filters", "F5", (s, e) => OnReapplyFilters(s, e));
                add("Clear all filters", null, (s, e) => OnClearFilters(s, e));
                add("Auto-fit columns", null, (s, e) => OnAutofit(s, e));
                add("Revert Selected Cells", null, (s, e) => OnRevertSelected(s, e));
                add(null, null, null);
                add("Keep Revit usable while this is open...", null, (s, e) => OnToggleModeless(s, e));
            }
            // the column's own duplicate commands lead the menu
            DuplicateItems(menu, () => _menuCol);
            menu.Items.Add(new Separator());
            foreach (var entry in items)
            {
                if (entry.Label == null)
                {
                    menu.Items.Add(new Separator());
                    continue;
                }
                var item = new MenuItem();
                item.Header = entry.Label;
                if (!string.IsNullOrEmpty(entry.Gesture))
                    item.InputGestureText = entry.Gesture;
                item.Click += entry.Handler;
                menu.Items.Add(item);
            }
            try
            {
                Dg.ContextMenu = menu;
            }
            catch (Exception) { }
            return menu;
        }

        public void OnPaste(object sender = null, EventArgs args = null)
        {
            string raw;
            try
            {
                raw = Clipboard.GetText();
            }
            catch (Exception)
            {
                raw = null;
            }
            if (string.IsNullOrEmpty(raw))
            {
                SetStatus("The clipboard is empty.");
                return;
            }
            var cells = SelCells();
            if (cells.Count == 0)
            {
                SetStatus("Select a cell to paste into.");
                return;
            }
            var block = new List<string[]>();
            foreach (string ln in raw.Replace("\r\n", "\n").Replace("\r", "\n").Split('\n'))
                block.Add(ln.Split('\t'));
            while (block.Count > 0 && block[block.Count - 1].Length == 1 && block[block.Count - 1][0] == "")
                block.RemoveAt(block.Count - 1);
            if (block.Count == 0) return;

            var colsSorted = OrderedFieldColumns();
            int anchorPos = cells[0].Pos;
            int anchorDisp = cells[0].Col.DisplayIndex;

            BeginBatch();
            int written = 0;
            int skipped = 0;
            if (block.Count == 1 && block[0].Length == 1 && cells.Count > 1)
            {
                // single value into every selected cell
                foreach (var c in cells)
                {
                    if (StageCell(c.Pos, c.Col, block[0][0])) written++;
                    else skipped++;
                }
            }
            else
            {
                var targets = DataPositions(anchorPos, true, block.Count);
                for (int dr = 0; dr < block.Count; dr++)
                {
                    if (dr >= targets.Count) break;
                    int pos = targets[dr];
                    string[] line = block[dr];
                    for (int dc = 0; dc < line.Length; dc++)
                    {
                        DataGridColumn col = null;
                        foreach (var cc in colsSorted)
                        {
                            if (cc.DisplayIndex == anchorDisp + dc)
                            {
                                col = cc;
                                break;
                            }
                        }
                        if (col == null) continue;
                        if (StageCell(pos, col, line[dc])) written++;
                        else skipped++;
                    }
                }
            }
            EndBatch();
            ClearCopyMarks();
            string msg = string.Format(CultureInfo.InvariantCulture, "Pasted {0} cell{1}.", written, P5Plural(written));
            if (skipped != 0)
                msg += SkippedNote(skipped);
            SetStatus(msg);
        }

        public void OnClear(object sender = null, EventArgs args = null)
        {
            var cells = SelCells();
            if (cells.Count == 0) return;
            BeginBatch();
            int n = 0;
            foreach (var c in cells)
            {
                if (StageCell(c.Pos, c.Col, "")) n++;
            }
            EndBatch();
            SetStatus(string.Format(CultureInfo.InvariantCulture, "Cleared {0} cell{1}.", n, P5Plural(n)));
        }

        // -- fill ---------------------------------------------------------------

        public void Fill(bool sequence)
        {
            var cells = SelCells();
            if (cells.Count < 2)
            {
                SetStatus("Select the seed cell and the cells to fill.");
                return;
            }
            var byCol = new Dictionary<int, List<SelCell>>();
            foreach (var c in cells)
            {
                List<SelCell> list;
                if (!byCol.TryGetValue(c.Col.DisplayIndex, out list))
                {
                    list = new List<SelCell>();
                    byCol[c.Col.DisplayIndex] = list;
                }
                list.Add(c);
            }
            BeginBatch();
            int n = 0;
            foreach (int disp in byCol.Keys.OrderBy(k => k))
            {
                var group = byCol[disp].OrderBy(d => d.Pos).ToList();
                DataGridColumn col = group[0].Col;
                string seed = TextAt(group[0].Pos, col) ?? "";
                BigInteger step = BigInteger.One;
                // a series of workset names would count its way into other,
                // real worksets and stage them without a word
                sequence = sequence && !WorksetCol(col);
                if (sequence && group.Count > 1)
                {
                    var a = SplitNumber(seed);
                    var b = SplitNumber(TextAt(group[1].Pos, col) ?? "");
                    if (a != null && b != null && (DigitsValue(b.Value.Digits) - DigitsValue(a.Value.Digits)) != 0)
                        step = DigitsValue(b.Value.Digits) - DigitsValue(a.Value.Digits);
                }
                for (int i = 0; i < group.Count - 1; i++)
                {
                    var c = group[i + 1];
                    string value = sequence ? SeriesValueBig(seed, step, i + 1) : seed;
                    if (StageCell(c.Pos, col, value)) n++;
                }
            }
            EndBatch();
            SetStatus(string.Format(CultureInfo.InvariantCulture, "{0} {1} cell{2}.",
                sequence ? "Sequenced" : "Filled", n, P5Plural(n)));
        }

        public void OnFillDown(object sender = null, EventArgs args = null)
        {
            Fill(false);
        }

        public void OnFillSeries(object sender = null, EventArgs args = null)
        {
            Fill(true);
        }
    }
}


