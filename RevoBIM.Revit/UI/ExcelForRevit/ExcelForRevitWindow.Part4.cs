// Excel for Revit: window part 4 (port of efr_core.py lines 7511-8420):
// selection helpers, staging (the gate every value passes), worksets, the cell
// colouring engine (repaint / paint_container), grid events and the keyboard handler.
using System;
using System.Collections.Generic;
using System.Data;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using RevoBIM.Tools.ExcelForRevit;
using static RevoBIM.Tools.ExcelForRevit.Efr;

namespace RevoBIM.Tools.ExcelForRevit
{
    public static partial class Efr
    {
        /// <summary>Python _ABSENT: "this key had no staged value" in an undo / redo batch (stored in a
        /// Dictionary&lt;EditKey, object&gt; beside real string values). Declared here because Stage() is the first user.</summary>
        public static readonly object Absent = new object();
    }
}

namespace RevoBIM.UI.ExcelForRevit
{
    // SelCell (the dict sel_cells returns) is declared in ExcelForRevitWindow.Fields.cs.
    public partial class ExcelForRevitWindow
    {
        // ---- small private helpers of this part ----

        /// <summary>int(item['ridx']) for a grid item; throws (like the Python) when the item has none, e.g. a group heading.</summary>
        private static int RidxOf(object item)
        {
            DataRowView drv = (DataRowView)item;
            return int.Parse(ToText(drv["ridx"]), CultureInfo.InvariantCulture);
        }

        /// <summary>self.col_field.get(col): null for a column that is not a schedule field (or null).</summary>
        private FieldInfo FieldOf(DataGridColumn col)
        {
            if (col == null) return null;
            FieldInfo fi;
            return ColField.TryGetValue(col, out fi) ? fi : null;
        }

        /// <summary>walk_up(element, DataGridCell): the DataGridCell that holds this visual, or null.</summary>
        private static DataGridCell FindCell(DependencyObject element)
        {
            DependencyObject node = element;
            int guard = 0;
            while (node != null && guard < 60)
            {
                DataGridCell hit = node as DataGridCell;
                if (hit != null) return hit;
                try
                {
                    node = VisualTreeHelper.GetParent(node);
                }
                catch (Exception)
                {
                    return null;
                }
                guard++;
            }
            return null;
        }

        // ---- selection ----------------------------------------------------

        public List<SelCell> SelCells()
        {
            List<SelCell> output = new List<SelCell>();
            try
            {
                Dictionary<int, int> pmap = PosMap();
                foreach (DataGridCellInfo ci in Dg.SelectedCells)
                {
                    try
                    {
                        DataGridColumn col = ci.Column;
                        FieldInfo fi = FieldOf(col);
                        if (fi == null) continue;
                        int ridx = RidxOf(ci.Item);
                        int pos;
                        if (!pmap.TryGetValue(ridx, out pos)) pos = -1;
                        output.Add(new SelCell { Pos = pos, Col = col, Ridx = ridx, Fidx = fi.Index });
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }
            catch (Exception) { }
            // stable sort: position, then the column's place on screen
            return output.Where(d => d.Pos >= 0)
                         .OrderBy(d => d.Pos)
                         .ThenBy(d => d.Col.DisplayIndex)
                         .ToList();
        }

        /// <summary>The text a grid cell shows (staged value else the model's), or null for a non-field column / unreadable row.</summary>
        public string TextAt(int pos, DataGridColumn col)
        {
            FieldInfo fi = FieldOf(col);
            if (fi == null) return null;
            int ridx;
            try
            {
                ridx = RidxOf(Dg.Items[pos]);
            }
            catch (Exception)
            {
                return null;
            }
            return Model.CurrentText(Model.Rows[ridx], fi.Index);
        }

        public void SelectCell(int pos, DataGridColumn col)
        {
            try
            {
                object item = Dg.Items[pos];
                DataGridCellInfo info = new DataGridCellInfo(item, col);
                Dg.SelectedCells.Clear();
                Dg.SelectedCells.Add(info);
                Dg.CurrentCell = info;
                Dg.ScrollIntoView(item, col);
            }
            catch (Exception) { }
        }

        // ---- staged edits -------------------------------------------------

        public void BeginBatch()
        {
            _batch = new Dictionary<EditKey, object>();
            LastRefusal = "";
            Refused = 0;
        }

        // ---- worksets -----------------------------------------------------

        public bool WorksetCol(DataGridColumn col)
        {
            FieldInfo fi = FieldOf(col);
            return fi != null && Model.WorksetFields.Contains(fi.Index);
        }

        /// <summary>The editable Workset cells a choice will be staged on, as (row, field) pairs: every one in the
        /// selection, or just the cell that was clicked when it is not part of the selection.</summary>
        public List<(int Ridx, int Field)> WorksetTargets(DataGridCell cell = null)
        {
            List<(int Ridx, int Field)> output = new List<(int Ridx, int Field)>();
            HashSet<(int, int)> seen = new HashSet<(int, int)>();
            bool clickedIn = false;
            foreach (DataGridCellInfo info in Dg.SelectedCells)
            {
                FieldInfo fi;
                int ridx;
                try
                {
                    fi = FieldOf(info.Column);
                    if (fi == null || !Model.WorksetFields.Contains(fi.Index))
                        continue;
                    ridx = RidxOf(info.Item);
                    if (cell != null && ReferenceEquals(info.Item, cell.DataContext)
                            && ReferenceEquals(info.Column, cell.Column))
                        clickedIn = true;
                }
                catch (Exception)
                {
                    continue;
                }
                (int, int) pair = (ridx, fi.Index);
                if (seen.Contains(pair)) continue;
                seen.Add(pair);
                if (Model.Rows[ridx].Cells[fi.Index].Editable)
                    output.Add((ridx, fi.Index));
            }
            if (cell != null && !clickedIn)
            {
                output = new List<(int Ridx, int Field)>();
                try
                {
                    FieldInfo fi = FieldOf(cell.Column);
                    int ridx = RidxOf(cell.DataContext);
                    if (Model.Rows[ridx].Cells[fi.Index].Editable)
                        output.Add((ridx, fi.Index));
                }
                catch (Exception) { }
            }
            return output;
        }

        /// <summary>Is this cell in the selection? Asked of the collection itself, not a loop over a selection
        /// that can run to a hundred thousand cells after Ctrl+A.</summary>
        public bool CellSelected(DataGridCell cell)
        {
            try
            {
                return Dg.SelectedCells.Contains(new DataGridCellInfo(cell.DataContext, cell.Column));
            }
            catch (Exception) { }
            foreach (DataGridCellInfo info in Dg.SelectedCells)
            {
                try
                {
                    if (ReferenceEquals(info.Item, cell.DataContext) && ReferenceEquals(info.Column, cell.Column))
                        return true;
                }
                catch (Exception)
                {
                    continue;
                }
            }
            return false;
        }

        /// <summary>The second click of a double-click on a Workset cell. True when it was dealt with here.</summary>
        public bool DoubleClickWorkset(MouseButtonEventArgs args)
        {
            DataGridCell cell;
            try
            {
                cell = FindCell(Dg.InputHitTest(args.GetPosition(Dg)) as DependencyObject);
            }
            catch (Exception)
            {
                cell = null;
            }
            if (cell == null || !WorksetCol(cell.Column))
                return false;
            args.Handled = true;
            WorksetDropdown drop = WsDropdown;
            if (drop != null && !drop.Closed)
                drop.Reclaim();
            else
                OpenWorksetDropdownSoon(cell);
            return true;
        }

        /// <summary>The DataGridCell of the current cell, if it is on screen.</summary>
        public DataGridCell CurrentCellElement()
        {
            try
            {
                DataGridCellInfo current = Dg.CurrentCell;
                DataGridRow container = (DataGridRow)Dg.ItemContainerGenerator.ContainerFromItem(current.Item);
                FrameworkElement content = current.Column.GetCellContent(container);
                return FindCell(content);
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>Open the list once the grid has finished with the click or key that asked for it: opened from
        /// inside the grid's own handling, the mouse release lands on the main window and takes the focus back.</summary>
        public void OpenWorksetDropdownSoon(DataGridCell cell = null, string seed = "")
        {
            Action open = () => OpenWorksetDropdown(cell, seed);
            try
            {
                Window.Dispatcher.BeginInvoke(DispatcherPriority.Background, open);
            }
            catch (Exception)
            {
                open();
            }
        }

        public void OpenWorksetDropdown(DataGridCell cell = null, string seed = "")
        {
            ScheduleModel model = Model;
            if (model.WorksetFields.Count == 0)
            {
                SetStatus("This schedule has no Workset column.");
                return;
            }
            if (model.Worksets.Count == 0)
            {
                SetStatus("Not a workshared model — there are no worksets to choose from.");
                return;
            }
            List<(int Ridx, int Field)> targets = WorksetTargets(cell);
            if (targets.Count == 0)
            {
                SetStatus("Select one or more cells in the Workset column first — read-only ones are left out.");
                return;
            }
            if (WsDropdown != null)
                WsDropdown.Close();
            HashSet<string> values = new HashSet<string>();
            foreach (var t in targets)
                values.Add(model.CurrentText(model.Rows[t.Ridx], t.Field));
            string current = values.Count == 1 ? values.First() : null;
            List<string> names = model.Worksets.Select(w => w.Name).ToList();
            WorksetDropdown drop = new WorksetDropdown(this, targets, names, current, seed);
            WsDropdown = drop;
            if (cell == null)
                cell = CurrentCellElement();
            try
            {
                if (cell != null)
                {
                    Point topLeft = EfrUi.ScreenPoint(cell, 0, 0);
                    Point bottom = EfrUi.ScreenPoint(cell, 0, cell.ActualHeight);
                    drop.ShowAt(topLeft.X, topLeft.Y, bottom.Y, cell.ActualWidth);
                }
                else
                {
                    Point pointer = Mouse.GetPosition(Dg);
                    Point at = EfrUi.ScreenPoint(Dg, pointer.X, pointer.Y);
                    drop.ShowAt(at.X, at.Y, at.Y, 260);
                }
            }
            catch (Exception)
            {
                WsDropdown = null;
                SetStatus("Could not open the workset list.");
            }
        }

        /// <summary>Stage one workset on every target cell, as one undo step.</summary>
        public void ApplyWorkset(List<(int Ridx, int Field)> targets, string name)
        {
            BeginBatch();
            int done = 0, skipped = 0;
            foreach (var t in targets)
            {
                if (Stage(t.Ridx, t.Field, name))
                    done++;
                else
                    skipped++;
            }
            EndBatch();
            int rows = new HashSet<int>(targets.Select(t => t.Ridx)).Count;
            string msg = "Workset \"" + name + "\" staged on " + rows.ToString(CultureInfo.InvariantCulture)
                + " row" + (rows == 1 ? "" : "s") + ".";
            msg += SkippedNote(skipped);
            msg += "  Nothing moves in the model until APPLY.";
            SetStatus(msg);
        }

        public void OnSetWorkset(object sender = null, EventArgs args = null)
        {
            OpenWorksetDropdownSoon(null);
        }

        /// <summary>What a fill writes: the ordinary series, or a straight copy in a Workset column, where counting
        /// would invent workset names.</summary>
        public List<string> FillValues(DataGridColumn col, IList<string> seeds, int count, bool downward)
        {
            FieldInfo fi = FieldOf(col);
            if (fi != null && Model.WorksetFields.Contains(fi.Index))
                return FillCopyOnly(seeds, count, downward);
            return FillPlan(seeds, count, downward);
        }

        /// <summary>"  N cells left alone." - saying why, when the reason is not simply that they are read only
        /// (a workset name that is not a workset, say).</summary>
        public string SkippedNote(int skipped, string verb = "left alone")
        {
            if (skipped == 0) return "";
            int refused = Math.Min(Refused, skipped);
            int readOnly = skipped - refused;
            string output = "";
            if (readOnly != 0)
                output += "  " + readOnly.ToString(CultureInfo.InvariantCulture) + " read-only cell"
                    + (readOnly == 1 ? "" : "s") + " " + verb + ".";
            if (refused != 0)
                output += "  " + refused.ToString(CultureInfo.InvariantCulture) + " refused — " + LastRefusal
                    + (refused > 1 ? " (and others)" : "") + ".";
            return output;
        }

        public void EndBatch()
        {
            if (_batch != null && _batch.Count > 0)
            {
                UndoStack.Add(_batch);
                RedoStack.Clear();
            }
            _batch = null;
            UpdatePending();
            RepaintSoon();
            NoteStale();
        }

        /// <summary>Say when edits have left rows out of the filter or out of order. Both are deliberate (a row
        /// must not move or vanish while it is being typed into) but silence would make them look like bugs.</summary>
        public void NoteStale()
        {
            List<string> parts = new List<string>();
            if (!string.IsNullOrEmpty(ActiveClause))
            {
                int n = StaleRows();
                if (n != 0)
                    parts.Add(n.ToString(CultureInfo.InvariantCulture) + " row" + (n == 1 ? "" : "s")
                        + " no longer match" + (n == 1 ? "es" : "") + " the filter");
            }
            int sorted = SortStale();
            if (sorted != 0)
                parts.Add(sorted.ToString(CultureInfo.InvariantCulture) + " row" + (sorted == 1 ? "" : "s") + " "
                    + (sorted == 1 ? "is" : "are") + " out of sort order");
            if (parts.Count == 0) return;
            SetStatus(string.Join(", and ", parts) + " — left in place so they can be edited. F5 to reapply.");
        }

        /// <summary>The gate every value passes. True when the value was staged.</summary>
        public bool Stage(int ridx, int fidx, string text)
        {
            ScheduleModel model = Model;
            RowInfo row;
            try
            {
                row = model.Rows[ridx];
            }
            catch (Exception)
            {
                return false;
            }
            CellInfo cell = row.Cells[fidx];
            if (!cell.Editable)
                return false;
            if (model.WorksetFields.Contains(fidx))
            {
                // only a workset that exists, spelled the way the model spells it
                var found = WorksetNamed(model.Worksets, text);
                if (found == null)
                {
                    string typed = ToText(text).Trim();
                    LastRefusal = typed.Length > 0
                        ? "\"" + typed + "\" is not a workset in this model"
                        : "a Workset cell cannot be left blank";
                    Refused++;
                    return false;
                }
                text = found.Value.Name;
            }
            EditKey key = model.KeyOf(row, fidx);
            if (key == null)
                return false;
            Dictionary<EditKey, string> store = model.StoreFor(key);
            text = ToText(text);
            if (_batch != null && !_batch.ContainsKey(key))
            {
                string prior;
                _batch[key] = store.TryGetValue(key, out prior) ? (object)prior : Absent;
            }
            if (text == cell.Original)
                store.Remove(key);
            else
                store[key] = text;
            model.Failed.Remove(key);
            if (!_importing)
                Imported.Remove((ridx, fidx));
            PushToTable(key);
            return true;
        }

        public bool StageCell(int pos, DataGridColumn col, string text)
        {
            FieldInfo fi = FieldOf(col);
            if (fi == null) return false;
            int ridx;
            try
            {
                ridx = RidxOf(Dg.Items[pos]);
            }
            catch (Exception)
            {
                return false;
            }
            return Stage(ridx, fi.Index, text);
        }

        /// <summary>Mirror a staged value into every grid cell that shows it.</summary>
        public void PushToTable(EditKey key)
        {
            ScheduleModel model = Model;
            if (key != null && key.IsScratch)
            {
                try
                {
                    RowInfo row = model.Rows[key.Ridx];
                    Table.Rows[row.Ridx][model.Fields[key.FieldIndex].Col] = model.CurrentText(row, key.FieldIndex);
                }
                catch (Exception) { }
                return;
            }
            List<(RowInfo Row, int Field)> shown;
            if (key == null || !KeyIndex.TryGetValue(key, out shown))
                return;
            foreach (var rf in shown)
            {
                try
                {
                    Table.Rows[rf.Row.Ridx][model.Fields[rf.Field].Col] = model.CurrentText(rf.Row, rf.Field);
                }
                catch (Exception) { }
            }
        }

        // ---- repaint ------------------------------------------------------

        public void RepaintSoon()
        {
            _dirtyPaint = true;
            try
            {
                Window.Dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(Repaint));
            }
            catch (Exception)
            {
                Repaint();
            }
        }

        /// <summary>Colour every row that is on screen. Only the realised rows are visited: the grid reports which
        /// containers exist through LoadingRow and UnloadingRow, so that set is kept instead of asking the grid
        /// for every row of a 5,000-row schedule.</summary>
        public void Repaint()
        {
            _dirtyPaint = false;
            List<DataGridRow> rows = new List<DataGridRow>(LiveRows);
            if (rows.Count == 0)
            {
                RepaintScan();
                return;
            }
            _dirtyRows.Clear();
            foreach (DataGridRow container in rows)
            {
                if (!PaintContainer(container))
                    _dirtyRows.Add(container);
            }
        }

        /// <summary>Colour only the rows that have just been realised. Scrolling recycles a handful of containers
        /// for new rows; those come through LoadingRow and are the only ones whose colours are stale. A row whose
        /// cells are not generated yet stays queued for the next layout pass, a few times at most.</summary>
        public void RepaintDirty()
        {
            List<DataGridRow> rows = new List<DataGridRow>(_dirtyRows);
            _dirtyRows.Clear();
            foreach (DataGridRow container in rows)
            {
                if (!LiveRows.Contains(container))
                    continue;
                if (PaintContainer(container))
                {
                    _paintTries.Remove(container);
                    continue;
                }
                int tries;
                _paintTries.TryGetValue(container, out tries);
                tries++;
                if (tries < PaintRetries)
                {
                    _paintTries[container] = tries;
                    _dirtyRows.Add(container);
                }
                else
                {
                    _paintTries.Remove(container);
                }
            }
        }

        /// <summary>The old full walk, kept only for when no rows have been reported, so a grid whose row events
        /// never arrived still gets its colours.</summary>
        public void RepaintScan()
        {
            DataGrid dg = Dg;
            int count;
            try
            {
                count = dg.Items.Count;
            }
            catch (Exception)
            {
                return;
            }
            for (int i = 0; i < count; i++)
            {
                DataGridRow container;
                try
                {
                    container = dg.ItemContainerGenerator.ContainerFromIndex(i) as DataGridRow;
                }
                catch (Exception)
                {
                    continue;
                }
                if (container != null)
                    PaintContainer(container);
            }
        }

        /// <summary>Colour one realised row. True when every cell was there to paint.</summary>
        public bool PaintContainer(DataGridRow container)
        {
            DataGrid dg = Dg;
            ScheduleModel model = Model;
            object item;
            try
            {
                item = container.Item;
            }
            catch (Exception)
            {
                return true;
            }
            if (IsHeaderRow(item))
            {
                PaintHeaderRow(dg, container, item);
                return true;
            }
            if (_headerTall.Contains(container))
            {
                // A recycled heading container keeps the height it was given as a heading (a local value survives
                // recycling), so an ordinary row handed this container came out 30px tall partway down a grouped
                // table. Given back to the row's own sizing.
                _headerTall.Remove(container);
                try
                {
                    container.Height = double.NaN;
                }
                catch (Exception) { }
            }
            int ridx;
            RowInfo row;
            try
            {
                ridx = RidxOf(item);
                row = model.Rows[ridx];
            }
            catch (Exception)
            {
                return true;                    // nothing of ours in this row
            }
            bool complete = true;
            foreach (DataGridColumn col in dg.Columns)
            {
                try
                {
                    FrameworkElement content = col.GetCellContent(container);
                    if (content == null)
                    {
                        complete = false;       // not generated yet; try again
                        continue;
                    }
                    DataGridCell cell = EfrUi.CellOf(content);
                    if (cell == null)
                        continue;
                    FieldInfo fi = FieldOf(col);
                    if (fi == null)
                    {
                        // the row number and id columns; an element waiting for a new level is flagged here,
                        // since the level itself may not be one of the schedule's columns
                        bool pendingLevel = model.LevelEdits.ContainsKey(ridx);
                        cell.Tag = Brush(pendingLevel ? C_EDIT_BG : C_INDEX_BG);
                        cell.Foreground = Brush(pendingLevel ? C_EDIT_FG : C_MUTED);
                        cell.FontWeight = pendingLevel ? FontWeights.SemiBold : FontWeights.Normal;
                        cell.ToolTip = pendingLevel
                            ? "Level will be set to \"" + model.LevelEdits[ridx].LevelName + "\" on APPLY"
                            : null;
                        continue;
                    }
                    CellInfo ci = row.Cells[fi.Index];
                    EditKey key = model.KeyOf(row, fi.Index);
                    bool scratch = ci.Scratch;
                    string bg, fg;
                    bool bold;
                    if (key != null && model.Failed.Contains(key))
                    {
                        bg = C_FAIL_BG; fg = C_FAIL_FG; bold = true;
                    }
                    else if (!scratch && key != null && model.Edits.ContainsKey(key))
                    {
                        if (Imported.Contains((ridx, fi.Index)))
                        {
                            bg = C_IMP_BG; fg = C_IMP_FG; bold = true;
                        }
                        else
                        {
                            bg = C_EDIT_BG; fg = C_EDIT_FG; bold = true;
                        }
                    }
                    else if (scratch)
                    {
                        bg = C_TEST_BG; fg = C_TEST_FG; bold = false;
                    }
                    else if (CopyMarks.Contains((ridx, fi.Index)))
                    {
                        // the clipboard source, until it is pasted or cleared
                        bg = C_COPY_BG; fg = C_COPY_FG; bold = false;
                    }
                    else if (!ci.Editable)
                    {
                        bg = C_RO_BG; fg = C_RO_FG; bold = false;
                    }
                    else if (ci.IsType)
                    {
                        bg = C_TYPE_BG; fg = C_TYPE_FG; bold = false;
                    }
                    else
                    {
                        bg = C_INST_BG; fg = C_INST_FG; bold = false;
                    }
                    // a highlight sits over the resting states but never hides a staged edit or a refusal
                    var hl = HighlightFor(ridx, fi.Index);
                    if (hl != null && !(key != null && (model.Failed.Contains(key)
                            || (!scratch && model.Edits.ContainsKey(key)))))
                    {
                        var hlc = HighlightColours(hl.Value.Item1);
                        string hlMode = hl.Value.Item2;
                        if (hlMode == "fill" || hlMode == "both")
                            bg = hlc.Bg;
                        if (hlMode == "text" || hlMode == "both")
                        {
                            fg = hlc.Fg;
                            bold = true;
                        }
                    }
                    cell.Tag = Brush(bg);
                    cell.Foreground = Brush(fg);
                    cell.FontWeight = bold ? FontWeights.SemiBold : FontWeights.Normal;
                    if (scratch)
                        cell.ToolTip = "Test column — scratch space for formulas, never written to the model";
                    else if (!ci.Editable)
                        cell.ToolTip = string.IsNullOrEmpty(ci.Reason) ? "read only" : ci.Reason;
                    else if (ci.IsType)
                        cell.ToolTip = "Type parameter — changing it changes every element of this type";
                    else
                        cell.ToolTip = null;
                }
                catch (Exception)
                {
                    continue;
                }
            }
            return complete;
        }

        /// <summary>A group heading: the whole row in the group's colour, label at left, and the open / shut button
        /// in the column beside it. Purely visual: it holds no element, takes no edit, and every operation steps
        /// over it.</summary>
        public void PaintHeaderRow(DataGrid dg, DataGridRow container, object item)
        {
            int number = GroupIndexOfHeader(item);
            var colours = GroupColour(number);
            string bg = colours.Item1, fg = colours.Item2;
            bool shut = Collapsed.Contains(number);
            try
            {
                container.Height = 30;
                _headerTall.Add(container);
            }
            catch (Exception) { }
            foreach (DataGridColumn col in dg.Columns)
            {
                try
                {
                    FrameworkElement content = col.GetCellContent(container);
                    if (content == null)
                        continue;
                    DataGridCell cell = EfrUi.CellOf(content);
                    if (cell == null)
                        continue;
                    cell.Tag = Brush(bg);
                    cell.Foreground = Brush(fg);
                    cell.FontWeight = FontWeights.Bold;
                    cell.ToolTip = shut ? "Click to open this group" : "Click to close this group";
                }
                catch (Exception)
                {
                    continue;
                }
            }
        }

        /// <summary>The heading's label and its open / shut button, written into the table so the normal binding
        /// shows them. Not written onto the TextBlock: a local value on a bound property sticks to that element,
        /// and with recycling on the element is later reused for a real row, leaving a group label in the data.</summary>
        public void WriteHeaderText(int number)
        {
            int index;
            if (!GroupRow.TryGetValue(number, out index) || FieldCols.Count == 0)
                return;
            string label = "";
            int count = 0;
            var lc = default((string, int));
            if (GroupLabels.TryGetValue(number, out lc))
            {
                label = lc.Item1;
                count = lc.Item2;
            }
            bool shut = Collapsed.Contains(number);
            string text = (shut ? "▸" : "▾") + "  " + label;
            if (count != 0)
                text += "   · " + count.ToString(CultureInfo.InvariantCulture) + " row" + (count == 1 ? "" : "s");
            try
            {
                DataRow row = Table.Rows[index];
                row[ColField[FieldCols[0]].Col] = text;
                if (FieldCols.Count > 1)
                    row[ColField[FieldCols[1]].Col] = shut ? "[ + ]  Expand" : "[ − ]  Collapse";
            }
            catch (Exception) { }
        }

        // ---- grid events --------------------------------------------------

        public void OnHeaderClick(object sender, MouseButtonEventArgs args)
        {
            try
            {
                if (args.ClickCount == 2)
                {
                    OnMaximise(null, null);
                    return;
                }
            }
            catch (Exception) { }
            bool shrunk = Drawer != null && (Drawer.Shrunk || Drawer.Busy);
            if (Vstretch != null && !shrunk)
            {
                // carrying the parked bar around must not restore the height it had before a vertical stretch;
                // that would blow the drawer open halfway through the drag
                double height = Vstretch.Value.Item2;
                Vstretch = null;
                try
                {
                    Window.Height = height;
                }
                catch (Exception) { }
            }
            try
            {
                Window.DragMove();
            }
            catch (Exception) { }
        }

        public void OnCurrentCellChanged(object sender, EventArgs args)
        {
            // moving off a cell always ends any edit; belt and braces for the flag
            if (!TextHasFocus())
                Editing = false;
        }

        public void OnBeginEdit(object sender, DataGridBeginningEditEventArgs args)
        {
            Editing = true;
            try
            {
                if (IsHeaderRow(args.Row.Item))
                {
                    args.Cancel = true;
                    Editing = false;
                    return;
                }
            }
            catch (Exception) { }
            try
            {
                FieldInfo fi = FieldOf(args.Column);
                int ridx = RidxOf(args.Row.Item);
                if (fi == null || !Model.Rows[ridx].Cells[fi.Index].Editable)
                {
                    args.Cancel = true;
                    Editing = false;
                    string reason = "this column is read only";
                    try
                    {
                        string r = Model.Rows[ridx].Cells[fi.Index].Reason;
                        if (!string.IsNullOrEmpty(r)) reason = r;
                    }
                    catch (Exception) { }
                    SetStatus("Not editable — " + reason);
                    return;
                }
                if (Model.WorksetFields.Contains(fi.Index))
                {
                    // a Workset cell is chosen from a list, not typed into; what was typed, if editing began
                    // with a key, seeds its search
                    args.Cancel = true;
                    Editing = false;
                    string seed = "";
                    try
                    {
                        TextCompositionEventArgs typed = args.EditingEventArgs as TextCompositionEventArgs;
                        if (typed != null)
                            seed = ToText(typed.Text ?? "");
                    }
                    catch (Exception)
                    {
                        seed = "";
                    }
                    DataGridCell cell = null;
                    try
                    {
                        cell = FindCell(args.Column.GetCellContent(args.Row));
                    }
                    catch (Exception)
                    {
                        cell = null;
                    }
                    OpenWorksetDropdownSoon(cell, seed);
                }
            }
            catch (Exception)
            {
                Editing = false;
            }
        }

        public void OnCellEditEnding(object sender, DataGridCellEditEndingEventArgs args)
        {
            Editing = false;
            FieldInfo fi;
            int ridx;
            string text;
            try
            {
                if (args.EditAction != DataGridEditAction.Commit)
                    return;
                fi = FieldOf(args.Column);
                if (fi == null)
                    return;
                ridx = RidxOf(args.Row.Item);
                text = ((TextBox)args.EditingElement).Text;
            }
            catch (Exception)
            {
                return;
            }

            Action commit = () =>
            {
                BeginBatch();
                bool ok = Stage(ridx, fi.Index, text);
                EndBatch();
                if (!ok)
                {
                    try
                    {
                        Table.Rows[ridx][fi.Col] = Model.CurrentText(Model.Rows[ridx], fi.Index);
                    }
                    catch (Exception) { }
                    SetStatus("That cell is read only — the value was put back.");
                    return;
                }
                RowInfo row = Model.Rows[ridx];
                if (row.Cells[fi.Index].IsType)
                {
                    int n = 0;
                    EditKey key = Model.KeyOf(row, fi.Index);
                    List<(RowInfo Row, int Field)> shared;
                    if (key != null && KeyIndex.TryGetValue(key, out shared))
                        n = shared.Count;
                    if (n > 1)
                        SetStatus("Type parameter — " + n.ToString(CultureInfo.InvariantCulture) + " scheduled rows share this value.");
                }
            };
            try
            {
                Window.Dispatcher.BeginInvoke(DispatcherPriority.Background, commit);
            }
            catch (Exception)
            {
                commit();
            }
        }

        /// <summary>Queue one refresh for a whole burst of selection changes. The grid raises this once per cell
        /// added or removed, and a drag rebuilds its rectangle cell by cell, so every event in a burst just marks
        /// the selection stale and the work runs once, after the burst, when the dispatcher next has time.</summary>
        public void OnSelectionChanged(object sender = null, EventArgs args = null)
        {
            _lastSel = Stale;
            if (_selPending)
                return;
            _selPending = true;
            try
            {
                Window.Dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(AfterSelection));
            }
            catch (Exception)
            {
                AfterSelection();
            }
        }

        /// <summary>Say, the first few times, that a Workset cell has a list behind it: nothing else on screen does.</summary>
        public void HintWorkset()
        {
            if (_wsHints >= 3 || Model.WorksetFields.Count == 0)
                return;
            try
            {
                // one cell only: a paste or fill that leaves a selection behind has its own message
                if (Dg.SelectedCells.Count != 1)
                    return;
                if (!WorksetCol(Dg.CurrentCell.Column))
                    return;
            }
            catch (Exception)
            {
                return;
            }
            _wsHints++;
            SetStatus("Workset — click the cell again, or press F2, to choose from the worksets. " +
                      "Select several rows first to set them all at once.");
        }

        /// <summary>Is any selected cell one a command can act on? Usually answered by the first cell; the row
        /// number and id columns do not count.</summary>
        public bool AnyFieldSelected()
        {
            foreach (DataGridCellInfo info in Dg.SelectedCells)
            {
                try
                {
                    if (FieldOf(info.Column) != null)
                        return true;
                }
                catch (Exception)
                {
                    continue;
                }
            }
            return false;
        }

        public void AfterSelection()
        {
            _selPending = false;
            HintWorkset();
            try
            {
                BtnRevertSel.IsEnabled = AnyFieldSelected();
            }
            catch (Exception) { }
            // with the formula bar open and not picking references, the cells the result goes into follow the
            // selection, so they can be chosen after the bar is opened rather than only before
            try
            {
                if (FormulaOpen() && !FormulaPick)
                {
                    FormulaCells = EditableSelection();
                    PaintFormula();
                }
            }
            catch (Exception) { }
            PlaceHandle();
        }

        /// <summary>A container has been prepared for a row (new, or recycled from one that scrolled away), so its
        /// colours belong to the old row.</summary>
        public void OnLoadingRow(object sender, DataGridRowEventArgs args)
        {
            try
            {
                DataGridRow container = args.Row;
                LiveRows.Add(container);
                _dirtyRows.Add(container);
            }
            catch (Exception)
            {
                _dirtyPaint = true;
            }
        }

        public void OnUnloadingRow(object sender, DataGridRowEventArgs args)
        {
            try
            {
                DataGridRow container = args.Row;
                LiveRows.Remove(container);
                _dirtyRows.Remove(container);
                _paintTries.Remove(container);
            }
            catch (Exception) { }
        }

        public void OnScroll(object sender, ScrollChangedEventArgs args)
        {
            // No repaint here. Vertical scrolling hands recycled containers to new rows, and every one of them
            // comes through LoadingRow; column virtualisation is off, so a sideways scroll realises nothing new.
            PlaceHandle();
        }

        public void OnLayoutUpdated(object sender, EventArgs args)
        {
            // raised for every layout pass anywhere in the window, so the common case (nothing to do) has to
            // cost two field reads and no more
            if (_dirtyPaint)
                Repaint();
            else if (_dirtyRows.Count > 0)
                RepaintDirty();
        }

        /// <summary>True when a text box owns the keyboard. Windows shortcuts belong to whatever has focus: inside
        /// the search box or a cell editor, Ctrl+C, Ctrl+V, Delete and Backspace are the text box's, not the grid's.</summary>
        public bool TextHasFocus()
        {
            try
            {
                return Keyboard.FocusedElement is TextBox;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Edit state read from the grid, not only from our own flag. The flag alone could stick True if
        /// BeginningEdit threw, and every shortcut in the window would go dead.</summary>
        public bool IsEditing()
        {
            if (TextHasFocus())
                return true;
            return Editing;
        }

        public void FocusGrid()
        {
            try
            {
                Dg.Focus();
            }
            catch (Exception) { }
        }

        public void OnKey(object sender, KeyEventArgs args)
        {
            bool ctrl = (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control;
            bool shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift;
            Key key = args.Key;
            if (ctrl && shift && key == Key.H)
            {
                args.Handled = true;
                if (Drawer != null)
                    Drawer.Toggle();
                return;
            }
            if (Drawer != null && Drawer.Shrunk)
            {
                // while it is parked the only keys that can mean anything are the two that bring it back;
                // Escape must not reach the close prompt
                if (key == Key.Escape || key == Key.Enter || key == Key.F11)
                {
                    args.Handled = true;
                    Drawer.Expand();
                }
                return;
            }
            if (key == Key.F11)
            {
                args.Handled = true;
                OnMaximise(null, null);
                return;
            }
            if (key == Key.F5)
            {
                args.Handled = true;
                OnReapplyFilters(null, null);
                return;
            }

            bool inText = TextHasFocus();
            if (key == Key.Escape && _filling)
            {
                args.Handled = true;
                CancelFill();
                SetStatus("Fill cancelled.");
                return;
            }
            if (key == Key.Escape && CopyMarks.Count > 0 && !inText)
            {
                args.Handled = true;
                ClearCopyMarks();
                SetStatus("Copy cleared.");
                return;
            }
            if (key == Key.Escape)
            {
                if (Editing || inText)
                {
                    // leave the editor or the filter box, not the tool
                    if (inText && !Editing)
                    {
                        args.Handled = true;
                        try
                        {
                            IInputElement focused = Keyboard.FocusedElement;
                            foreach (var box in HeaderBoxes.Values)
                            {
                                if (ReferenceEquals(box, focused) && !string.IsNullOrEmpty(box.Text))
                                {
                                    box.Text = "";
                                    break;
                                }
                            }
                        }
                        catch (Exception) { }
                        FocusGrid();
                    }
                    return;
                }
                args.Handled = true;
                Window.Close();
                return;
            }

            if (IsEditing())
            {
                // a text box has the keyboard: let Windows do its own thing, and only keep the shortcuts that
                // cannot mean anything to a text box
                if (ctrl && shift && key == Key.T)
                {
                    args.Handled = true;
                    OnTheme(null, null);
                }
                else if (ctrl && key == Key.S)
                {
                    args.Handled = true;
                    OnApply(null, null);
                }
                return;
            }

            if (key == Key.F2)
            {
                args.Handled = true;
                BeginEditCurrent();
            }
            else if (ctrl && key == Key.X)
            {
                args.Handled = true;
                OnCut(null, null);
            }
            else if (ctrl && key == Key.C)
            {
                args.Handled = true;
                OnCopy(null, null);
            }
            else if (ctrl && key == Key.V)
            {
                args.Handled = true;
                OnPaste(null, null);
            }
            else if (ctrl && key == Key.D)
            {
                args.Handled = true;
                OnFillDown(null, null);
            }
            else if (ctrl && shift && key == Key.E)
            {
                args.Handled = true;
                OnExport(null, null);
            }
            else if (ctrl && shift && key == Key.I)
            {
                args.Handled = true;
                OnImport(null, null);
            }
            else if (ctrl && key == Key.E)
            {
                args.Handled = true;
                OnFillSeries(null, null);
            }
            else if (ctrl && shift && key == Key.F)
            {
                args.Handled = true;
                OnFormula(null, null);
            }
            else if (ctrl && shift && key == Key.N)
            {
                args.Handled = true;
                OnSequence(null, null);
            }
            else if (ctrl && shift && key == Key.P)
            {
                args.Handled = true;
                OnAffix(null, null);
            }
            else if (ctrl && shift && key == Key.H)
            {
                args.Handled = true;
                OnHighlight(null, null);
            }
            else if (ctrl && shift && key == Key.T)
            {
                args.Handled = true;
                OnTheme(null, null);
            }
            else if (ctrl && (key == Key.H || key == Key.F))
            {
                args.Handled = true;
                OnFind(null, null);
            }
            else if (ctrl && (key == Key.Y || (shift && key == Key.Z)))
            {
                args.Handled = true;
                OnRedo(null, null);
            }
            else if (ctrl && key == Key.Z)
            {
                args.Handled = true;
                OnUndo(null, null);
            }
            else if (ctrl && key == Key.S)
            {
                args.Handled = true;
                OnApply(null, null);
            }
            else if (key == Key.Delete || key == Key.Back)
            {
                args.Handled = true;
                OnClear(null, null);
            }
        }
    }
}
