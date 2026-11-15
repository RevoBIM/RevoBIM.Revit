// Excel for Revit: window part 5b (efr_core.py 8682-9352): fill handle geometry, drag auto-scroll,
// drag selection, double-click autofill and the fill handle itself.
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
using static RevoBIM.UI.ExcelForRevit.EfrUi;

namespace RevoBIM.UI.ExcelForRevit
{
    public partial class ExcelForRevitWindow
    {
        // -- drag fill handle ---------------------------------------------------

        /// <summary>(left, top, width, height) of a cell in GridHost coordinates, or null when it is not realised.</summary>
        public (double X, double Y, double W, double H)? CellRect(int pos, DataGridColumn col)
        {
            try
            {
                DataGridRow container = Dg.ItemContainerGenerator.ContainerFromIndex(pos) as DataGridRow;
                if (container == null) return null;
                FrameworkElement content = col.GetCellContent(container);
                if (content == null) return null;
                DataGridCell cell = P5CellOf(content);
                if (cell == null) return null;
                Point origin = cell.TransformToAncestor(GridHost).Transform(new Point(0, 0));
                return (origin.X, origin.Y, cell.ActualWidth, cell.ActualHeight);
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>
        /// The bottom-right selected cell as (position, column), or null.
        /// The fill handle only ever needs this one cell, but used to build and
        /// sort the entire selection to find it, on every scroll tick. It is
        /// found in a single pass and kept until the selection or the row order
        /// changes, so scrolling past a large selection costs nothing.
        /// </summary>
        public (int Pos, DataGridColumn Col)? LastSelected()
        {
            if (!ReferenceEquals(_lastSel, Stale))
                return _lastSel == null ? ((int, DataGridColumn)?)null : ((int, DataGridColumn))_lastSel;
            (int Pos, int Disp, DataGridColumn Col)? best = null;
            try
            {
                var pmap = PosMap();
                foreach (DataGridCellInfo info in Dg.SelectedCells)
                {
                    int pos;
                    DataGridColumn col;
                    int disp;
                    try
                    {
                        col = info.Column;
                        if (!ColField.ContainsKey(col)) continue;
                        if (!pmap.TryGetValue(P5Ridx(info.Item), out pos)) pos = -1;
                        if (pos < 0) continue;
                        disp = col.DisplayIndex;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                    // Python compares the (pos, display index) rank tuples
                    if (best == null || pos > best.Value.Pos || (pos == best.Value.Pos && disp > best.Value.Disp))
                        best = (pos, disp, col);
                }
            }
            catch (Exception)
            {
                best = null;
            }
            if (best == null)
            {
                _lastSel = null;
                return null;
            }
            (int, DataGridColumn) result = (best.Value.Pos, best.Value.Col);
            _lastSel = result;
            return result;
        }

        public void PlaceHandle()
        {
            try
            {
                var last = LastSelected();
                if (last == null)
                {
                    Handle.Visibility = Visibility.Collapsed;
                    return;
                }
                var rect = CellRect(last.Value.Pos, last.Value.Col);
                if (rect == null)
                {
                    Handle.Visibility = Visibility.Collapsed;
                    return;
                }
                Canvas.SetLeft(Handle, rect.Value.X + rect.Value.W - 5);
                Canvas.SetTop(Handle, rect.Value.Y + rect.Value.H - 5);
                Handle.Visibility = Visibility.Visible;
            }
            catch (Exception)
            {
                try
                {
                    Handle.Visibility = Visibility.Collapsed;
                }
                catch (Exception) { }
            }
        }

        /// <summary>
        /// (top, bottom) of the scrollable row area, in GridHost coordinates.
        /// The overshoot has to be measured against the viewport, not against
        /// the rows. A virtualising panel keeps rows realised a little beyond the
        /// visible area, so measuring against the last realised row meant dragging
        /// to the bottom of the window still landed inside a row, reported no
        /// overshoot, and never scrolled.
        /// </summary>
        public (double Top, double Bottom) RowArea()
        {
            double top;
            try
            {
                top = Dg.ColumnHeaderHeight;
            }
            catch (Exception)
            {
                top = 0.0;
            }
            if (top <= 0) top = 56.0;
            double bottom = top + 100.0;
            try
            {
                bottom = GridHost.ActualHeight;
            }
            catch (Exception) { }
            if (bottom <= top) bottom = top + 100.0;
            return (top, bottom);
        }

        /// <summary>
        /// (row index under the pointer, pixels past the edge of the viewport).
        /// Inside the grid the row comes from a hit test, which is cheap and
        /// exact. Outside it there is no row to find, so the overshoot is what
        /// matters and the timer walks the target along instead.
        /// </summary>
        public (int? Pos, double Over) RowAtY(double y, DataGridColumn col = null, Point? point = null)
        {
            var area = RowArea();
            double top = area.Top, bottom = area.Bottom;
            if (y < top + EDGE_INSET)
                return (null, y - (top + EDGE_INSET));          // negative: above
            if (y > bottom - EDGE_INSET)
                return (null, y - (bottom - EDGE_INSET));       // positive: below
            return (RowUnder(y, col, point), 0.0);
        }

        /// <summary>The row at this position inside the grid, or null.</summary>
        public int? RowUnder(double y, DataGridColumn col = null, Point? point = null)
        {
            if (point != null)
            {
                try
                {
                    IInputElement hit = Dg.InputHitTest(point.Value);
                    DataGridRow row = P5WalkUp<DataGridRow>(hit);
                    if (row != null)
                    {
                        int index = Dg.ItemContainerGenerator.IndexFromContainer(row);
                        if (index >= 0) return index;
                    }
                }
                catch (Exception) { }
            }
            // fall back to measuring, for the gaps a hit test lands in. Only a
            // realised row can be under the pointer, so only those are measured:
            // walking from the top of the schedule meant thousands of lookups for
            // a gridline-thin miss once the grid was scrolled a long way down.
            foreach (DataGridRow container in LiveRows.ToList())
            {
                try
                {
                    Point origin = container.TransformToAncestor(GridHost).Transform(new Point(0, 0));
                    if (origin.Y <= y && y < origin.Y + container.ActualHeight)
                    {
                        int index = Dg.ItemContainerGenerator.IndexFromContainer(container);
                        if (index >= 0) return index;
                    }
                }
                catch (Exception)
                {
                    continue;                      // detached while being recycled
                }
            }
            if (LiveRows.Count > 0) return null;
            col = col ?? _fillCol;
            if (col == null)
            {
                try
                {
                    col = Dg.Columns[0];
                }
                catch (Exception)
                {
                    return null;
                }
            }
            int count;
            try
            {
                count = Dg.Items.Count;
            }
            catch (Exception)
            {
                return null;
            }
            for (int i = 0; i < count; i++)
            {
                var rect = CellRect(i, col);
                if (rect == null) continue;                      // not realised: virtualised away
                if (rect.Value.Y <= y && y < rect.Value.Y + rect.Value.H) return i;
                if (rect.Value.Y > y) break;                     // rows are in order: stop early
            }
            return null;
        }

        // -- drag auto-scroll ---------------------------------------------------

        /// <summary>One timer serves both drags: the fill handle and a selection drag.</summary>
        public void StartDragScroll(string mode)
        {
            _dragMode = mode;
            _scrollOver = 0.0;
            _scrollOverX = 0.0;
            _scrollAccum = 0.0;
            _scrollAccumX = 0.0;
            if (_scrollTimer == null)
            {
                _scrollTimer = new DispatcherTimer();
                _scrollTimer.Interval = TimeSpan.FromMilliseconds(SCROLL_TICK_MS);
                _scrollTimer.Tick += OnDragScroll;
            }
            _scrollTimer.Start();
        }

        public void StopDragScroll()
        {
            _dragMode = null;
            _scrollOver = 0.0;
            _scrollOverX = 0.0;
            _scrollAccum = 0.0;
            _scrollAccumX = 0.0;
            try
            {
                if (_scrollTimer != null) _scrollTimer.Stop();
            }
            catch (Exception) { }
        }

        /// <summary>
        /// Advance by however many whole rows this tick has earned.
        /// The fraction is carried over, so a rate below one row per tick still
        /// scrolls instead of rounding to nothing.
        /// </summary>
        public void OnDragScroll(object sender, EventArgs args)
        {
            if (string.IsNullOrEmpty(_dragMode)) return;
            try
            {
                if (Mouse.LeftButton != MouseButtonState.Pressed)
                {
                    // released off the window, or over something that swallowed the
                    // event: a timer left running would scroll forever
                    if (_dragMode == "select")
                    {
                        StopDragScroll();
                        return;
                    }
                }
            }
            catch (Exception) { }
            ScrollSideways();
            double rate = ScrollRate(_scrollOver);
            if (rate <= 0)
            {
                _scrollAccum = 0.0;
                return;
            }
            _scrollAccum += rate * (SCROLL_TICK_MS / 1000.0);
            int steps = (int)_scrollAccum;
            if (steps < 1) return;
            _scrollAccum -= steps;
            if (_scrollOver < 0) steps = -steps;
            int count;
            try
            {
                count = Dg.Items.Count;
            }
            catch (Exception)
            {
                return;
            }
            if (_dragMode == "fill")
            {
                int target = Math.Max(0, Math.Min(count - 1, _fillTarget + steps));
                if (target == _fillTarget) return;
                _fillTarget = target;
                ScrollRowIntoView(target, _fillCol);
                DrawFillPreview();
            }
            else
            {
                int target = Math.Max(0, Math.Min(count - 1, _selPos + steps));
                _selPos = target;
                DataGridColumn col = _selCurCol ?? _selCol;
                ScrollRowIntoView(target, col);
                ExtendSelection(target, col);
            }
        }

        /// <summary>Pixels past the left or right edge of the grid.</summary>
        public double ColumnOvershoot(double x)
        {
            double width;
            try
            {
                width = GridHost.ActualWidth;
            }
            catch (Exception)
            {
                return 0.0;
            }
            if (x < EDGE_INSET) return x - EDGE_INSET;
            if (x > width - EDGE_INSET) return x - (width - EDGE_INSET);
            return 0.0;
        }

        /// <summary>Walk the current column sideways, for a drag past the side edge.</summary>
        public DataGridColumn StepColumn(int steps)
        {
            var cols = OrderedFieldColumns();
            if (cols.Count == 0) return null;
            DataGridColumn current = _selCurCol ?? _selCol;
            int i = cols.IndexOf(current);
            if (i < 0) i = 0;
            i = Math.Max(0, Math.Min(cols.Count - 1, i + steps));
            _selCurCol = cols[i];
            return cols[i];
        }

        /// <summary>Columns step more slowly than rows: they are much wider.</summary>
        public void ScrollSideways()
        {
            if (_dragMode != "select" || _scrollOverX == 0)
            {
                _scrollAccumX = 0.0;
                return;
            }
            double rate = ScrollRate(_scrollOverX) / 6.0;
            if (rate <= 0) return;
            _scrollAccumX += rate * (SCROLL_TICK_MS / 1000.0);
            int steps = (int)_scrollAccumX;
            if (steps < 1) return;
            _scrollAccumX -= steps;
            if (_scrollOverX < 0) steps = -steps;
            DataGridColumn col = StepColumn(steps);
            if (col != null)
            {
                ScrollRowIntoView(_selPos, col);
                ExtendSelection(_selPos, col);
            }
        }

        public void ScrollRowIntoView(int pos, DataGridColumn col)
        {
            try
            {
                object item = Dg.Items[pos];
                if (col != null)
                    Dg.ScrollIntoView(item, col);
                else
                    Dg.ScrollIntoView(item);
            }
            catch (Exception) { }
        }

        // -- selection drag -----------------------------------------------------

        /// <summary>
        /// Remember where a drag-select started, and arm the scroller.
        /// WPF handles the drag itself perfectly well while the pointer is inside
        /// the grid; it is only past the edge that it stops, so the timer does
        /// nothing until the overshoot is non-zero.
        /// </summary>
        public void OnGridMouseDown(object sender, MouseButtonEventArgs args)
        {
            if (_filling) return;
            try
            {
                if (args.ClickCount == 2)
                {
                    // the second click of a double-click belongs to the DataGrid:
                    // it is what starts a cell edit, and arming the drag scroller
                    // here is what stopped edits beginning at all, except in a
                    // Workset column, where the first click has already opened the
                    // list; handing this one to the grid would collapse the
                    // selection and open the list a second time
                    DoubleClickWorkset(args);
                    return;
                }
            }
            catch (Exception) { }
            try
            {
                _downAt = args.GetPosition(Dg);
            }
            catch (Exception)
            {
                _downAt = null;
            }
            try
            {
                IInputElement hit = Dg.InputHitTest(args.GetPosition(Dg));
                DataGridCell cell = P5WalkUp<DataGridCell>(hit);
                if (cell == null) return;
                if (FormulaOpen() && FormulaPick && !IsHeaderRow(cell.DataContext))
                {
                    FieldInfo fi;
                    if (ColField.TryGetValue(cell.Column, out fi) && fi != null)
                    {
                        for (int i = 0; i < Dg.Items.Count; i++)
                        {
                            if (ReferenceEquals(Dg.Items[i], cell.DataContext))
                            {
                                int ridx = P5Ridx(Dg.Items[i]);
                                if (InsertReference(ridx, fi))
                                    args.Handled = true;
                                return;
                            }
                        }
                    }
                }
                if (IsHeaderRow(cell.DataContext))
                {
                    // the whole heading is the button, so it is hard to miss
                    args.Handled = true;
                    int number = GroupIndexOfHeader(cell.DataContext);
                    bool opened = ToggleGroup(number);
                    string label = "";
                    var gl = GroupLabels;
                    if (gl.ContainsKey(number)) label = gl[number].Item1;
                    ShowExpandState();
                    SetStatus(string.Format(CultureInfo.InvariantCulture, "{0} {1}.",
                        opened ? "Opened" : "Closed", label));
                    return;
                }
                DataGridColumn col = cell.Column;
                if (!ColField.ContainsKey(col)) return;
                if (WorksetCol(col) && Dg.SelectedCells.Count > 1)
                {
                    bool plain = true;
                    try
                    {
                        plain = (Keyboard.Modifiers & (ModifierKeys.Control | ModifierKeys.Shift)) == 0;
                    }
                    catch (Exception)
                    {
                        plain = true;
                    }
                    if (plain && CellSelected(cell))
                    {
                        // Clicking inside a selection would collapse it to one
                        // cell. In the Workset column that click means "set all
                        // of these", so the selection is kept and the list opens.
                        args.Handled = true;
                        OpenWorksetDropdownSoon(cell);
                        return;
                    }
                }
                int pos;
                try
                {
                    pos = Dg.Items.IndexOf(cell.DataContext);
                }
                catch (Exception)
                {
                    pos = -1;
                    for (int i = 0; i < Dg.Items.Count; i++)
                    {
                        if (ReferenceEquals(Dg.Items[i], cell.DataContext))
                        {
                            pos = i;
                            break;
                        }
                    }
                }
                if (pos < 0) return;
                _selAnchor = pos;
                _selRect = null;        // a new drag draws its own rectangle
                _selPos = pos;
                _selCol = col;
                _selCurCol = col;
            }
            catch (Exception)
            {
                return;
            }
            StartDragScroll("select");
        }

        public void OnGridMouseMove(object sender, MouseEventArgs args)
        {
            if (_filling || _dragMode != "select") return;
            try
            {
                if (args.LeftButton != MouseButtonState.Pressed)
                {
                    StopDragScroll();
                    return;
                }
            }
            catch (Exception)
            {
                return;
            }
            Point p, point;
            try
            {
                p = args.GetPosition(GridHost);
                point = args.GetPosition(Dg);
            }
            catch (Exception)
            {
                return;
            }
            // nothing counts as a drag until the pointer has actually travelled:
            // rebuilding the selection on the tiny movement between the two clicks
            // of a double-click takes the cell out from under the edit
            if (!PastDragThreshold(point)) return;
            var hitRow = RowAtY(p.Y, _selCol, point);
            int? pos = hitRow.Pos;
            _scrollOver = hitRow.Over;
            _scrollOverX = ColumnOvershoot(p.X);
            try
            {
                // the column under the pointer first, so the rectangle drawn on
                // this move reaches it rather than catching up on the next; and on
                // every move, since the auto-scroll at the edges reads it too
                DataGridCell cell = P5WalkUp<DataGridCell>(Dg.InputHitTest(point));
                if (cell != null && ColField.ContainsKey(cell.Column))
                    _selCurCol = cell.Column;
            }
            catch (Exception) { }
            if (pos != null)
            {
                _selPos = pos.Value;
                bool adding = false;
                try
                {
                    adding = (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control;
                }
                catch (Exception)
                {
                    adding = false;
                }
                if (!adding)
                    ExtendSelection(pos.Value, _selCurCol ?? _selCol);
            }
        }

        /// <summary>Has the pointer moved far enough since the button went down?</summary>
        public bool PastDragThreshold(Point point)
        {
            if (_downAt == null) return true;
            double dx, dy, wide, tall;
            try
            {
                dx = Math.Abs(point.X - _downAt.Value.X);
                dy = Math.Abs(point.Y - _downAt.Value.Y);
                wide = SystemParameters.MinimumHorizontalDragDistance;
                tall = SystemParameters.MinimumVerticalDragDistance;
            }
            catch (Exception)
            {
                return true;
            }
            return dx >= wide || dy >= tall;
        }

        public void OnGridMouseUp(object sender, MouseButtonEventArgs args)
        {
            if (_dragMode == "select") StopDragScroll();
        }

        /// <summary>Anchor to here, as a rectangle across the columns dragged over.</summary>
        public void ExtendSelection(int pos, DataGridColumn col)
        {
            if (_selAnchor == null || col == null) return;
            try
            {
                var cols = OrderedFieldColumns();
                DataGridColumn anchorCol = _selCol ?? col;
                int a = cols.Contains(anchorCol) ? cols.IndexOf(anchorCol) : 0;
                int b = cols.Contains(col) ? cols.IndexOf(col) : a;
                int loC = Math.Min(a, b), hiC = Math.Max(a, b);
                int anchor = _selAnchor.Value;
                int loR = Math.Min(anchor, pos), hiR = Math.Max(anchor, pos);
                var rect = (loR, hiR, loC, hiC);
                if (_selRect != null && _selRect.Value.Rect == rect
                        && Dg.SelectedCells.Count == _selRect.Value.Added)
                {
                    // Most mouse moves stay inside the cell they started in, and
                    // rebuilding an identical rectangle on each one was the other
                    // half of what made a drag-select drag. Skipped only while
                    // the grid still holds exactly what was drawn: WPF runs its
                    // own drag selection inside the grid too, and when it has
                    // added the row number or id cells the count gives it away.
                    return;
                }
                _selRect = null;
                Dg.SelectedCells.Clear();
                int added = 0;
                for (int r = loR; r <= hiR; r++)
                {
                    object item = Dg.Items[r];
                    if (IsHeaderRow(item)) continue;
                    for (int ci = loC; ci <= hiC; ci++)
                    {
                        Dg.SelectedCells.Add(new DataGridCellInfo(item, cols[ci]));
                        added++;
                    }
                }
                // recorded only once the whole rectangle is in, so a failure
                // halfway cannot be mistaken for a finished selection next time
                _selRect = (rect, added);
                Dg.CurrentCell = new DataGridCellInfo(Dg.Items[pos], col);
            }
            catch (Exception) { }
        }

        /// <summary>
        /// The last data row of the block pos sits in.
        /// With grouping on that is the row before the next heading; with it off
        /// there are no headings, so it is the last row on the list. Either way it
        /// is where a double-click fill should stop.
        /// </summary>
        public int GroupEnd(int pos)
        {
            int last = pos;
            int total;
            try
            {
                total = Dg.Items.Count;
            }
            catch (Exception)
            {
                return last;
            }
            int p = pos + 1;
            while (p < total)
            {
                if (IsHeaderPos(p)) break;
                last = p;
                p++;
            }
            return last;
        }

        /// <summary>Excel's double-click autofill, stopped at the group heading.</summary>
        public void FillToGroupEnd()
        {
            var src = SelCells();
            if (src.Count == 0)
            {
                SetStatus("Select the cell to fill from first.");
                return;
            }
            var byCol = new Dictionary<int, List<SelCell>>();
            foreach (var c in src)
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
            int written = 0;
            int skipped = 0;
            int? reached = null;
            foreach (int disp in byCol.Keys.OrderBy(k => k))
            {
                var group = byCol[disp].OrderBy(d => d.Pos).ToList();
                DataGridColumn col = group[0].Col;
                int bottom = group[group.Count - 1].Pos;
                int target = GroupEnd(bottom);
                if (target <= bottom) continue;
                var dest = new List<int>();
                for (int p = bottom + 1; p <= target; p++)
                {
                    if (!IsHeaderPos(p)) dest.Add(p);
                }
                var seeds = group.Select(c => TextAt(c.Pos, col) ?? "").ToList();
                var values = FillValues(col, seeds, dest.Count, true);
                for (int i = 0; i < Math.Min(dest.Count, values.Count); i++)
                {
                    if (StageCell(dest[i], col, values[i])) written++;
                    else skipped++;
                }
                reached = target;
            }
            EndBatch();

            if (written == 0 && skipped == 0)
            {
                SetStatus(Grouping
                    ? "Nothing below to fill — already at the end of the group."
                    : "Nothing below to fill.");
                return;
            }
            string msg = string.Format(CultureInfo.InvariantCulture, "Filled {0} cell{1} down to the ",
                written, P5Plural(written));
            msg += Grouping ? "end of the group." : "end of the list.";
            if (skipped != 0)
                msg += SkippedNote(skipped);
            SetStatus(msg);
            if (reached != null)
                ScrollRowIntoView(reached.Value, src[src.Count - 1].Col);
        }

        public void OnHandleDown(object sender, MouseButtonEventArgs args)
        {
            var cells = SelCells();
            if (cells.Count == 0) return;
            bool dbl;
            try
            {
                dbl = args.ClickCount == 2;
            }
            catch (Exception)
            {
                dbl = false;
            }
            if (dbl)
            {
                // a double-click fills rather than drags, so no capture and no timer
                args.Handled = true;
                FillToGroupEnd();
                return;
            }
            _filling = true;
            _fillSrc = cells;
            _fillCol = cells[0].Col;
            _fillTarget = cells[cells.Count - 1].Pos;
            try
            {
                Handle.CaptureMouse();
            }
            catch (Exception) { }
            StartDragScroll("fill");
            args.Handled = true;
        }

        public void OnHandleMove(object sender, MouseEventArgs args)
        {
            if (!_filling) return;
            double y;
            Point point;
            try
            {
                y = args.GetPosition(GridHost).Y;
                point = args.GetPosition(Dg);
            }
            catch (Exception)
            {
                return;
            }
            var hitRow = RowAtY(y, _fillCol, point);
            _scrollOver = hitRow.Over;
            if (hitRow.Pos != null && !IsHeaderPos(hitRow.Pos.Value))
                _fillTarget = hitRow.Pos.Value;
            DrawFillPreview();
        }

        /// <summary>The orange outline over everything the drop would write.</summary>
        public void DrawFillPreview()
        {
            try
            {
                var src = _fillSrc;
                if (src == null || src.Count == 0) return;
                int target = _fillTarget;
                var first = src[0];
                var last = src[src.Count - 1];
                int topPos = Math.Min(first.Pos, target);
                int bottomPos = Math.Max(last.Pos, target);
                var top = CellRect(topPos, first.Col);
                var bottom = CellRect(bottomPos, last.Col);
                if (top == null || bottom == null)
                {
                    // the far end is scrolled out of view: clamp to what is drawn
                    top = top ?? CellRect(first.Pos, first.Col);
                    bottom = bottom ?? CellRect(last.Pos, last.Col);
                    if (top == null || bottom == null) return;
                }
                Canvas.SetLeft(Preview, top.Value.X);
                Canvas.SetTop(Preview, top.Value.Y);
                Preview.Width = Math.Max(1, bottom.Value.X + bottom.Value.W - top.Value.X);
                Preview.Height = Math.Max(1, bottom.Value.Y + bottom.Value.H - top.Value.Y);
                Preview.Visibility = Visibility.Visible;
                int n = Math.Abs(target - (target > last.Pos ? last.Pos : first.Pos));
                if (n != 0)
                    SetStatus(string.Format(CultureInfo.InvariantCulture,
                        "Fill {0} cell{1} — release to write, Escape to cancel.", n, P5Plural(n)));
            }
            catch (Exception) { }
        }

        public void CancelFill()
        {
            _filling = false;
            StopDragScroll();
            try
            {
                Handle.ReleaseMouseCapture();
            }
            catch (Exception) { }
            try
            {
                Preview.Visibility = Visibility.Collapsed;
            }
            catch (Exception) { }
        }

        public void OnHandleUp(object sender, MouseButtonEventArgs args)
        {
            if (!_filling) return;
            var src = _fillSrc;
            int target = _fillTarget;
            CancelFill();
            if (src == null || src.Count == 0 || target < 0) return;

            var byCol = new Dictionary<int, List<SelCell>>();
            foreach (var c in src)
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
            int written = 0;
            int skipped = 0;
            foreach (int disp in byCol.Keys.OrderBy(k => k))
            {
                var group = byCol[disp].OrderBy(d => d.Pos).ToList();
                DataGridColumn col = group[0].Col;
                int top = group[0].Pos;
                int bottom = group[group.Count - 1].Pos;
                var dest = new List<int>();
                bool downward;
                if (target > bottom)
                {
                    for (int p = bottom + 1; p <= target; p++)
                    {
                        if (!IsHeaderPos(p)) dest.Add(p);
                    }
                    downward = true;
                }
                else if (target < top)
                {
                    for (int p = top - 1; p >= target; p--)
                    {
                        if (!IsHeaderPos(p)) dest.Add(p);
                    }
                    downward = false;
                }
                else
                {
                    continue;
                }
                var seeds = group.Select(c => TextAt(c.Pos, col) ?? "").ToList();
                var values = FillValues(col, seeds, dest.Count, downward);
                for (int i = 0; i < Math.Min(dest.Count, values.Count); i++)
                {
                    if (StageCell(dest[i], col, values[i])) written++;
                    else skipped++;
                }
            }
            EndBatch();

            if (written != 0 || skipped != 0)
            {
                string msg = string.Format(CultureInfo.InvariantCulture, "Filled {0} cell{1}.", written, P5Plural(written));
                if (skipped != 0)
                    msg += SkippedNote(skipped);
                SetStatus(msg);
            }
            args.Handled = true;
        }
    }
}

