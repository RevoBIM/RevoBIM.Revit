// Excel for Revit: window part 2 (efr_core.py 5796-6667): column filters, grouping, sorting,
// expand/collapse, toolbar reflow, the grid's table and columns, resize grips and the drawer.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Data;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Input;
using RevoBIM.Tools.ExcelForRevit;
using static RevoBIM.Tools.ExcelForRevit.Efr;
using static RevoBIM.UI.ExcelForRevit.EfrUi;

namespace RevoBIM.UI.ExcelForRevit
{
    public partial class ExcelForRevitWindow
    {
        // SNAP_BREAK_PX and SORT_LEVEL_MAX come from EfrUi (EfrDialogs2.cs, using static).
        // No fields are introduced in this part: everything is declared in ExcelForRevitWindow.Fields.cs.

        // -- column filters ----------------------------------------------------

        /// <summary>
        /// The values worth offering in this column's filter list.
        /// Only the rows the other columns' filters allow, so filtering by Level and then opening the
        /// System list offers the systems on that level rather than every system in the schedule.
        /// This column's own filter is left out of that, or a filter could only ever be narrowed and
        /// never widened again.
        /// </summary>
        public List<(string Value, int Count)> ColumnValues(FieldInfo fi)
        {
            string clause = FilterClause(fi.Index);
            HashSet<string> allowed = !string.IsNullOrEmpty(clause) ? RowsMatching(clause) : null;
            Dictionary<string, int> seen = new Dictionary<string, int>();
            List<string> order = new List<string>();     // first-seen order, like a Python dict
            foreach (RowInfo row in Model.Rows)
            {
                if (allowed != null && !allowed.Contains(ToText(row.Ridx))) continue;
                string value = Model.CurrentText(row, fi.Index);
                int n;
                if (seen.TryGetValue(value, out n)) seen[value] = n + 1;
                else { seen[value] = 1; order.Add(value); }
            }
            return order.OrderBy(v => NaturalKey(v)).Select(v => (v, seen[v])).ToList();
        }

        /// <summary>The number of values this column has that the other filters are hiding (0 = none).</summary>
        public int ColumnValuesLimited(FieldInfo fi)
        {
            try
            {
                int shown = ColumnValues(fi).Count;
                int total = new HashSet<string>(Model.Rows.Select(row => Model.CurrentText(row, fi.Index))).Count;
                return total - shown;
            }
            catch (Exception)
            {
                return 0;
            }
        }

        /// <summary>
        /// One RowFilter from the search box and every column filter.
        /// The filter is applied as a snapshot, the way Excel's autofilter behaves: whatever is on
        /// screen stays on screen until the filter is changed or re-applied. Without that, editing a
        /// cell in a filtered column makes its row stop matching and vanish the instant the value is
        /// committed (usually mid-fill, taking the cell being copied from with it).
        /// That falls out of filtering on a hidden `vis` flag rather than on the values themselves:
        /// editing a value column cannot change `vis`, so the row cannot move. Re-evaluating only
        /// happens here, when a filter actually changes or Reapply is pressed.
        /// </summary>
        public void ApplyFilters()
        {
            string clause = FilterClause();
            ActiveClause = clause;
            try
            {
                int count = Model.Rows.Count;
                if (string.IsNullOrEmpty(clause))
                {
                    for (int i = 0; i < count; i++)
                        SetFlag(Table.Rows[i], "vis", "1");
                }
                else
                {
                    HashSet<string> matching = RowsMatching(clause);
                    for (int i = 0; i < count; i++)
                    {
                        DataRow row = Table.Rows[i];
                        SetFlag(row, "vis", matching.Contains(ToText(row["ridx"])) ? "1" : "0");
                    }
                }
            }
            catch (Exception)
            {
                SetStatus("That filter could not be used.");
                return;
            }
            // a heading only belongs where its group still has rows
            if (Grouping) ApplySort();
            else RefreshShown();
            MarkFilteredColumns();
            ReportRows();
            PlaceHandle();
            RepaintSoon();
        }

        /// <summary>
        /// The real filter, before the snapshot is taken.
        /// `exclude` leaves one column's own filter out, which is what a filter dropdown needs: it
        /// should offer the values available under everything else, including the ones its own filter
        /// is currently hiding, or there would be no way to widen it again.
        /// </summary>
        public string FilterClause(int? exclude = null)
        {
            List<string> clauses = new List<string>();
            foreach (KeyValuePair<int, string> pair in ColFilters)
            {
                int index = pair.Key;
                if (exclude.HasValue && index == exclude.Value) continue;
                if (index < 0 || index >= Model.Fields.Count) continue;
                FieldInfo fi = Model.Fields[index];
                string text = ToText(pair.Value).Trim();
                if (text.Length == 0) continue;
                clauses.Add(string.Format(CultureInfo.InvariantCulture, "[{0}] LIKE '%{1}%'", fi.Col, SqlLikeEscape(text)));
            }

            foreach (KeyValuePair<int, HashSet<string>> pair in ColPicks)
            {
                int index = pair.Key;
                if (exclude.HasValue && index == exclude.Value) continue;
                if (index < 0 || index >= Model.Fields.Count) continue;
                FieldInfo fi = Model.Fields[index];
                HashSet<string> allowed = pair.Value;
                if (allowed == null) continue;
                if (allowed.Count == 0)
                {
                    clauses.Add("1 = 0");          // nothing ticked shows nothing
                    continue;
                }
                List<string> parts = new List<string>();
                foreach (string value in allowed)
                {
                    if (value == "")
                        parts.Add(string.Format(CultureInfo.InvariantCulture, "[{0}] = ''", fi.Col));
                    else
                        parts.Add(string.Format(CultureInfo.InvariantCulture, "[{0}] = '{1}'",
                                                fi.Col, ToText(value).Replace("'", "''")));
                }
                clauses.Add("(" + string.Join(" OR ", parts) + ")");
            }
            return string.Join(" AND ", clauses);
        }

        /// <summary>
        /// Row indexes (as text) the clause selects, worked out on a throwaway view.
        /// A second DataView leaves the grid's own view, and its sort, and the selection untouched
        /// while the question is asked.
        /// </summary>
        public HashSet<string> RowsMatching(string clause)
        {
            HashSet<string> output = new HashSet<string>();
            try
            {
                DataView probe = new DataView(Table);
                probe.RowFilter = !string.IsNullOrEmpty(clause)
                    ? string.Format(CultureInfo.InvariantCulture, "({0}) AND [ridx] <> ''", clause)
                    : "[ridx] <> ''";
                for (int i = 0; i < probe.Count; i++)
                    output.Add(ToText(probe[i]["ridx"]));
            }
            catch (Exception)
            {
            }
            return output;
        }

        /// <summary>Rows on screen that the filter would now drop, kept for editing.</summary>
        public int StaleRows()
        {
            if (string.IsNullOrEmpty(ActiveClause)) return 0;
            HashSet<string> matching = RowsMatching(ActiveClause);
            int n = 0;
            try
            {
                DataView view = Table.DefaultView;
                for (int i = 0; i < view.Count; i++)
                {
                    string rid = ToText(view[i]["ridx"]);
                    if (rid.Length > 0 && !matching.Contains(rid)) n++;
                }
            }
            catch (Exception)
            {
                return 0;
            }
            return n;
        }

        public void ReportRows()
        {
            int shown = Dg.Items.Count;
            int total = Model.Rows.Count;
            if (shown == total && string.IsNullOrEmpty(ActiveClause))
            {
                SetStatus(total.ToString(CultureInfo.InvariantCulture) + " rows.");
                return;
            }
            string msg = string.Format(CultureInfo.InvariantCulture, "{0} of {1} rows shown by the filters.", shown, total);
            int stale = StaleRows();
            if (stale > 0)
            {
                msg += string.Format(CultureInfo.InvariantCulture,
                    "  {0} no longer match{1} but {2} being kept visible — Reapply filters to drop {3}.",
                    stale, stale == 1 ? "es" : "", stale == 1 ? "is" : "are", stale == 1 ? "it" : "them");
            }
            SetStatus(msg);
        }

        /// <summary>Re-run the filter and let anything that no longer matches go.</summary>
        public void OnReapplyFilters(object sender = null, EventArgs args = null)
        {
            if (string.IsNullOrEmpty(ActiveClause) && !Grouping && SortStack.Count == 0)
            {
                SetStatus("There is nothing to reapply.");
                return;
            }
            if (string.IsNullOrEmpty(ActiveClause))
            {
                ApplySort();
                SetStatus(string.Format("Re-sorted{0}.", Grouping ? " and regrouped" : ""));
                return;
            }
            int before = Dg.Items.Count;
            ApplyFilters();
            ApplySort();
            int gone = before - Dg.Items.Count;
            if (gone > 0)
                SetStatus(string.Format(CultureInfo.InvariantCulture,
                    "Reapplied — {0} row{1} dropped out of the filter.", gone, gone == 1 ? "" : "s"));
            else
                SetStatus("Reapplied — every row still matches.");
        }

        /// <summary>A filtered column's caret goes orange, so it is obvious why rows are missing:
        /// a filter you cannot see is a filter you forget.</summary>
        public void MarkFilteredColumns()
        {
            foreach (KeyValuePair<int, Button> pair in HeaderCarets)
            {
                int index = pair.Key;
                string text;
                ColFilters.TryGetValue(index, out text);
                HashSet<string> picks;
                bool hasPicks = ColPicks.TryGetValue(index, out picks) && picks != null;
                bool active = ToText(text).Trim().Length > 0 || hasPicks;
                try
                {
                    pair.Value.Content = active ? "▼" : "▾";
                    pair.Value.Foreground = Brush(active ? C_ORANGE : C_MUTED);
                }
                catch (Exception)
                {
                }
            }
        }

        public void ClearAllFilters()
        {
            ColFilters = new Dictionary<int, string>();
            ColPicks = new Dictionary<int, HashSet<string>>();
            DupIsolated = new HashSet<int>();
            foreach (TextBox box in HeaderBoxes.Values)
            {
                try
                {
                    box.Text = "";
                }
                catch (Exception)
                {
                }
            }
            ApplyFilters();
        }

        // -- group headers -----------------------------------------------------

        /// <summary>Header rows carry no ridx: that is what marks them.</summary>
        public bool IsHeaderRow(object item)
        {
            try
            {
                DataRowView view = item as DataRowView;
                if (view == null) return false;
                return ToText(view["ridx"]) == "";
            }
            catch (Exception)
            {
                return false;
            }
        }

        public bool IsHeaderPos(int pos)
        {
            try
            {
                return IsHeaderRow(Dg.Items[pos]);
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// `count` real row positions from `start`, stepping over any headers.
        /// Group headings are decoration. A paste or a fill that ran across one would otherwise drop
        /// a value into it and lose that value, so the walk skips them without consuming anything.
        /// </summary>
        public List<int> DataPositions(int start, bool downward, int count)
        {
            List<int> output = new List<int>();
            int total;
            try
            {
                total = Dg.Items.Count;
            }
            catch (Exception)
            {
                return output;
            }
            int pos = start;
            int step = downward ? 1 : -1;
            while (output.Count < count && pos >= 0 && pos < total)
            {
                if (!IsHeaderPos(pos)) output.Add(pos);
                pos += step;
            }
            return output;
        }

        /// <summary>A different colour per group, cycling once the palette runs out.</summary>
        public (string Bg, string Fg) GroupColour(int order)
        {
            string name = HIGHLIGHT_COLOURS[order % HIGHLIGHT_COLOURS.Length];
            return HighlightColours(name);
        }

        public void OnGroupToggle(object sender = null, EventArgs args = null)
        {
            Grouping = !Grouping;
            ShowGroupState();
            if (Grouping && SortField == null)
            {
                // nothing sorted yet: group by the first column, which is what "the sorted column"
                // means when the user has not picked one
                try
                {
                    SortCol = FieldCols[0];
                    FieldInfo first;
                    ColField.TryGetValue(SortCol, out first);
                    SortField = first;
                    SortDesc = false;
                    SortStack = new List<(FieldInfo Field, bool Desc)> { (SortField, false) };
                    SortCol.SortDirection = ListSortDirection.Ascending;
                }
                catch (Exception)
                {
                }
            }
            if (!Grouping) Collapsed = new HashSet<int>();
            ApplySort();
            ShowExpandState();
            if (Grouping && SortField != null)
                SetStatus(string.Format("Grouped by {0} — click a heading to open or close it.", SortField.Name));
            else
                SetStatus("Grouping off.");
        }

        /// <summary>Orange label when grouping is on, ordinary when off.</summary>
        public void ShowGroupState()
        {
            if (BtnGroup == null) return;
            try
            {
                var tag = IconTag(BtnGroup);
                tag.Text.Text = Grouping ? "Grouped" : "Group";
                tag.Text.Foreground = Brush(Grouping ? C_ORANGE : C_TEXT);
            }
            catch (Exception)
            {
            }
        }

        // -- sorting -----------------------------------------------------------

        /// <summary>Take the sort over, so grouping can order the headings with it.</summary>
        public void OnSorting(object sender, DataGridSortingEventArgs args)
        {
            DataGridColumn col = args.Column;
            if (col == null) return;
            FieldInfo field;
            if (!ColField.TryGetValue(col, out field) || field == null) return;
            args.Handled = true;
            bool shift;
            try
            {
                shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift;
            }
            catch (Exception)
            {
                shift = false;
            }

            // clicking a column already in the sort flips its own direction;
            // anything else takes a place in it
            int existing = -1;
            for (int i = 0; i < SortStack.Count; i++)
            {
                if (ReferenceEquals(SortStack[i].Field, field))
                {
                    existing = i;
                    break;
                }
            }

            if (existing >= 0)
            {
                // a column already in the sort keeps its place and flips direction
                SortStack[existing] = (field, !SortStack[existing].Desc);
            }
            else if (shift && SortStack.Count > 0)
            {
                // shift keeps adding levels underneath, each a tie-break for the ones above it
                if (SortStack.Count >= SORT_LEVEL_MAX)
                {
                    SetStatus(string.Format(CultureInfo.InvariantCulture, "{0} sort levels is as deep as it goes.", SORT_LEVEL_MAX));
                    return;
                }
                SortStack = new List<(FieldInfo Field, bool Desc)>(SortStack) { (field, false) };
            }
            else
            {
                SortStack = new List<(FieldInfo Field, bool Desc)> { (field, false) };
            }

            SortCol = col;
            SortField = SortStack[0].Field;
            SortDesc = SortStack[0].Desc;
            foreach (DataGridColumn other in Dg.Columns)
            {
                try
                {
                    other.SortDirection = null;
                }
                catch (Exception)
                {
                }
            }
            foreach (var entry in SortStack)
            {
                foreach (KeyValuePair<DataGridColumn, FieldInfo> pair in ColField)
                {
                    if (ReferenceEquals(pair.Value, entry.Field))
                    {
                        try
                        {
                            pair.Key.SortDirection = entry.Desc ? ListSortDirection.Descending : ListSortDirection.Ascending;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
            }
            ApplySort();
            if (SortStack.Count > 1)
            {
                string names = string.Join(", then ", SortStack.Select(e => e.Field.Name));
                SetStatus(string.Format("Sorted by {0}. Shift-click another heading to sort inside that.", names));
            }
            else if (SortStack.Count > 0)
            {
                SetStatus(string.Format("Sorted by {0}. Shift-click another heading to sort inside it.", SortStack[0].Field.Name));
            }
        }

        /// <summary>Rebuild the headings, work out what is showing, and sort.</summary>
        public void ApplySort()
        {
            DataView view = Table.DefaultView;
            if (Grouping && SortField != null)
            {
                RebuildGroups();
                RefreshShown();
                try
                {
                    view.Sort = "[gkey] ASC";
                }
                catch (Exception)
                {
                }
            }
            else
            {
                ClearGroups();
                RefreshShown();
                try
                {
                    if (SortStack.Count > 0)
                    {
                        AssignSortKeys();
                        view.Sort = "[gkey] ASC";
                    }
                    else
                    {
                        SortSnapshot = new Dictionary<int, string[]>();
                        view.Sort = "";
                    }
                }
                catch (Exception)
                {
                }
            }
            MarkSortedColumn();
            PlaceHandle();
            RepaintSoon();
        }

        /// <summary>
        /// Sort by a key worked out once, not by the live value.
        /// A DataView sorted on a value column re-evaluates the moment that value changes, so typing
        /// into the sorted column makes the row jump away from the cursor before it can be finished
        /// (the same trap as filtering on the values). Writing the order into a key column freezes it
        /// until the sort is asked for again, and it lets the order be natural, so P10 follows P9
        /// rather than P1.
        /// </summary>
        public void AssignSortKeys()
        {
            if (SortStack.Count == 0) return;
            ScheduleModel model = Model;
            List<int> ordered = model.Rows.Select(row => row.Ridx).ToList();
            Dictionary<int, string[]> snapshot = new Dictionary<int, string[]>();
            foreach (RowInfo row in model.Rows)
                snapshot[row.Ridx] = SortStack.Select(e => model.CurrentText(row, e.Field.Index)).ToArray();

            // least significant level first, then the most significant, because a stable sort
            // layers that way, which is also how each level keeps its own direction, something one
            // composite key cannot do
            for (int level = SortStack.Count - 1; level >= 0; level--)
            {
                FieldInfo field = SortStack[level].Field;
                bool desc = SortStack[level].Desc;
                Func<int, NaturalKeyValue> key = ridx => NaturalKey(model.CurrentText(model.Rows[ridx], field.Index));
                ordered = desc ? ordered.OrderByDescending(key).ToList() : ordered.OrderBy(key).ToList();
            }

            for (int n = 0; n < ordered.Count; n++)
            {
                try
                {
                    Table.Rows[ordered[n]]["gkey"] = n.ToString("D8", CultureInfo.InvariantCulture);
                }
                catch (Exception)
                {
                }
            }
            SortSnapshot = snapshot;
        }

        /// <summary>Rows edited since the order was worked out, so still in their old place.</summary>
        public int SortStale()
        {
            if (SortSnapshot == null || SortSnapshot.Count == 0 || SortStack.Count == 0) return 0;
            ScheduleModel model = Model;
            int n = 0;
            foreach (RowInfo row in model.Rows)
            {
                string[] was;
                if (!SortSnapshot.TryGetValue(row.Ridx, out was)) continue;
                string[] now = SortStack.Select(e => model.CurrentText(row, e.Field.Index)).ToArray();
                if (!now.SequenceEqual(was)) n++;
            }
            return n;
        }

        /// <summary>
        /// `show` = passes the filters and its group is not collapsed.
        /// Two separate reasons a row can be hidden, kept in two separate places: `vis` is the
        /// filter's answer and nothing else touches it, so collapsing a group cannot quietly drop
        /// rows out of the filter snapshot, and expanding it again brings back exactly what the
        /// filter allowed.
        /// </summary>
        public void RefreshShown()
        {
            try
            {
                int count = Model.Rows.Count;
                for (int i = 0; i < count; i++)
                {
                    DataRow row = Table.Rows[i];
                    bool shown = ToText(row["vis"]) == "1";
                    if (shown && Collapsed.Count > 0)
                    {
                        int group;
                        if (GroupOf.TryGetValue(i, out group) && Collapsed.Contains(group))
                            shown = false;
                    }
                    SetFlag(row, "show", shown ? "1" : "0");
                }
                for (int i = count; i < Table.Rows.Count; i++)
                    SetFlag(Table.Rows[i], "show", "1");   // headings always show
                Table.DefaultView.RowFilter = "[show] = '1'";
            }
            catch (Exception)
            {
            }
        }

        // -- collapsing --------------------------------------------------------

        public bool ToggleGroup(int number)
        {
            if (Collapsed.Contains(number)) Collapsed.Remove(number);
            else Collapsed.Add(number);
            WriteHeaderText(number);
            RefreshShown();
            PlaceHandle();
            RepaintSoon();
            return !Collapsed.Contains(number);
        }

        public void SetAllGroups(bool collapsed)
        {
            if (!Grouping || GroupLabels.Count == 0)
            {
                SetStatus("Turn Group on first.");
                return;
            }
            if (collapsed) Collapsed = new HashSet<int>(GroupLabels.Keys);
            else Collapsed = new HashSet<int>();
            foreach (int number in GroupLabels.Keys.ToList())
                WriteHeaderText(number);
            RefreshShown();
            PlaceHandle();
            RepaintSoon();
            ShowExpandState();
            SetStatus(string.Format(CultureInfo.InvariantCulture, "{0} all {1} group{2}.",
                collapsed ? "Collapsed" : "Expanded", GroupLabels.Count, GroupLabels.Count == 1 ? "" : "s"));
        }

        /// <summary>One button for both, because there is only ever one sensible next move: if
        /// anything is open, close everything; otherwise open everything.</summary>
        public void OnExpandAll(object sender = null, EventArgs args = null)
        {
            if (!Grouping)
            {
                SetStatus("Grouping is off — there is nothing to collapse.");
                return;
            }
            bool anyOpen = Collapsed.Count < GroupLabels.Count;
            SetAllGroups(anyOpen);
        }

        /// <summary>
        /// Keep the icons and Sort Headings on one row while they both fit.
        /// When they stop fitting the icons drop to a row of their own underneath, rather than being
        /// clipped or pushing Sort Headings off the edge. The two thresholds differ by a margin so a
        /// window dragged slowly across the boundary settles instead of flickering between the two
        /// layouts.
        /// </summary>
        public void ReflowToolbar()
        {
            if (ToolStrip == null || GroupBar == null) return;
            double total, needed, aside;
            try
            {
                total = ToolGrid.ActualWidth;
                needed = ToolStrip.DesiredSize.Width;
                aside = GroupBar.ActualWidth + 16.0;
            }
            catch (Exception)
            {
                return;
            }
            if (total <= 0 || needed <= 0) return;
            bool stacked = (Grid.GetRow(ToolStrip) == 1);
            if (!stacked && needed + aside > total)
            {
                Grid.SetRow(ToolStrip, 1);
                Grid.SetColumn(ToolStrip, 0);
                Grid.SetColumnSpan(ToolStrip, 2);
                ToolStrip.Margin = new Thickness(0, 8, 0, 0);
            }
            else if (stacked && needed + aside + 24.0 <= total)
            {
                Grid.SetRow(ToolStrip, 0);
                Grid.SetColumn(ToolStrip, 0);
                Grid.SetColumnSpan(ToolStrip, 1);
                ToolStrip.Margin = new Thickness(0);
            }
        }

        /// <summary>Kept for the callers that ask for a relayout after the columns move.</summary>
        public void AlignGroupBar()
        {
            ReflowToolbar();
        }

        public void ShowExpandState()
        {
            if (BtnExpand == null) return;
            try
            {
                var tag = IconTag(BtnExpand);
                bool allShut = Grouping && GroupLabels.Count > 0 && Collapsed.Count >= GroupLabels.Count;
                tag.Text.Text = allShut ? "Expand All" : "Collapse All";
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Drop the heading rows. They live at the end of the table, so removing them cannot
        /// disturb `Table.Rows[ridx]` for the real rows.</summary>
        public void ClearGroups()
        {
            GroupOf = new Dictionary<int, int>();
            GroupRow = new Dictionary<int, int>();
            try
            {
                while (Table.Rows.Count > Model.Rows.Count)
                    Table.Rows.RemoveAt(Table.Rows.Count - 1);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>One heading row per run of equal values in the sorted column.</summary>
        public void RebuildGroups()
        {
            ClearGroups();
            FieldInfo fi = SortField;
            if (fi == null) return;
            ScheduleModel model = Model;

            Dictionary<string, List<int>> values = new Dictionary<string, List<int>>();
            List<string> firstSeen = new List<string>();     // insertion order, like a Python dict
            foreach (RowInfo row in model.Rows)
            {
                try
                {
                    if (ToText(Table.Rows[row.Ridx]["vis"]) != "1") continue;
                }
                catch (Exception)
                {
                    continue;
                }
                string text = model.CurrentText(row, fi.Index);
                List<int> list;
                if (!values.TryGetValue(text, out list))
                {
                    list = new List<int>();
                    values[text] = list;
                    firstSeen.Add(text);
                }
                list.Add(row.Ridx);
            }

            List<string> order = firstSeen.OrderBy(v => NaturalKey(v)).ToList();
            if (SortDesc) order.Reverse();

            // a group that keeps its label keeps its collapsed state across a refilter or a
            // re-sort, so reapplying a filter does not spring everything open again
            HashSet<string> wasShut = new HashSet<string>();
            foreach (int n in Collapsed)
            {
                (string Label, int Count) entry;
                if (GroupLabels.TryGetValue(n, out entry)) wasShut.Add(entry.Label);
            }
            GroupOf = new Dictionary<int, int>();
            GroupLabels = new Dictionary<int, (string Label, int Count)>();
            GroupRow = new Dictionary<int, int>();
            Collapsed = new HashSet<int>();
            for (int n = 0; n < order.Count; n++)
            {
                string value = order[n];
                string key = n.ToString("D6", CultureInfo.InvariantCulture);
                List<int> members = new List<int>(values[value]);
                // least significant first, so a stable sort layers them correctly
                for (int level = SortStack.Count - 1; level > 0; level--)
                {
                    FieldInfo sub = SortStack[level].Field;
                    bool subDesc = SortStack[level].Desc;
                    Func<int, NaturalKeyValue> subKey = r => NaturalKey(model.CurrentText(model.Rows[r], sub.Index));
                    members = subDesc ? members.OrderByDescending(subKey).ToList() : members.OrderBy(subKey).ToList();
                }
                for (int place = 0; place < members.Count; place++)
                {
                    int ridx = members[place];
                    try
                    {
                        Table.Rows[ridx]["gkey"] = key + "\u0001" + place.ToString("D8", CultureInfo.InvariantCulture);
                    }
                    catch (Exception)
                    {
                    }
                    GroupOf[ridx] = n;
                }
                try
                {
                    DataRow header = Table.NewRow();
                    header["ridx"] = "";
                    header["rn"] = "";
                    header["eid"] = "";
                    header["vis"] = "1";
                    header["gkey"] = key + "\u0000";
                    header["grp"] = ToText(n);
                    // the label goes in the first value column so it reads on the left; every
                    // other column is left empty
                    Table.Rows.Add(header);
                    GroupRow[n] = Table.Rows.Count - 1;
                }
                catch (Exception)
                {
                }
                string label = value != "" ? value : "(blank)";
                GroupLabels[n] = (label, values[value].Count);
                if (wasShut.Contains(label)) Collapsed.Add(n);
                WriteHeaderText(n);
            }

            // rows the filter is hiding still need a key, or the sort throws
            foreach (RowInfo row in model.Rows)
            {
                try
                {
                    if (ToText(Table.Rows[row.Ridx]["gkey"]).Length == 0)
                        Table.Rows[row.Ridx]["gkey"] = "zzzzzz";
                }
                catch (Exception)
                {
                }
            }
        }

        public int GroupIndexOfHeader(object item)
        {
            try
            {
                return int.Parse(ToText(((DataRowView)item)["grp"]), CultureInfo.InvariantCulture);
            }
            catch (Exception)
            {
                return 0;
            }
        }

        // -- the grid ----------------------------------------------------------

        public void BuildGrid()
        {
            ScheduleModel model = Model;
            DataTable table = new DataTable("schedule");
            foreach (string name in GRID_META_COLS)
                table.Columns.Add(name);
            foreach (FieldInfo fi in model.Fields)
                table.Columns.Add(fi.Col);

            // One call per row rather than one per cell. A whole row as an object[] is one call, and
            // BeginLoadData switches off the change notifications and index upkeep nobody is
            // listening to yet: the table is not bound until the end of this method.
            table.BeginLoadData();
            try
            {
                for (int n = 0; n < model.Rows.Count; n++)
                {
                    RowInfo row = model.Rows[n];
                    row.Ridx = n;
                    object[] values = GridRowValues(model, row, n);
                    table.Rows.Add(values);
                }
            }
            finally
            {
                table.EndLoadData();
            }

            Table = table;
            KeyIndex = BuildKeyIndex(model);

            Style editStyle = MakeEditStyle();

            Dg.Columns.Clear();
            ColField = new Dictionary<DataGridColumn, FieldInfo>();

            DataGridTextColumn c = new DataGridTextColumn();
            c.Header = "#";
            c.Binding = new Binding("rn");
            c.IsReadOnly = true;
            c.Width = new DataGridLength(46, DataGridLengthUnitType.Pixel);
            c.CanUserSort = false;
            Dg.Columns.Add(c);

            c = new DataGridTextColumn();
            c.Header = "Id";
            c.Binding = new Binding("eid");
            c.IsReadOnly = true;
            c.Width = new DataGridLength(78, DataGridLengthUnitType.Pixel);
            Dg.Columns.Add(c);

            FieldCols = new List<DataGridColumn>();
            for (int n = 0; n < model.Fields.Count; n++)
                model.Fields[n].Letter = ColLetter(n);
            HeaderBoxes = new Dictionary<int, TextBox>();
            HeaderCarets = new Dictionary<int, Button>();
            HeaderTitles = new Dictionary<int, TextBlock>();
            HeaderBadges = new Dictionary<int, (Border Badge, TextBlock Letter)>();
            HeaderOutlines = new Dictionary<int, Border>();
            foreach (FieldInfo fi in model.Fields)
            {
                DataGridTextColumn col = new DataGridTextColumn();
                col.Header = ColumnHeader(fi);
                col.Binding = new Binding(fi.Col);
                col.Width = new DataGridLength(150, DataGridLengthUnitType.Pixel);
                col.EditingElementStyle = editStyle;
                col.IsReadOnly = false;
                Dg.Columns.Add(col);
                ColField[col] = fi;
                FieldCols.Add(col);
            }

            AddColumnButton();
            Dg.ItemsSource = table.DefaultView;
            _posCache = null;
            _lastSel = Stale;
            try
            {
                // every sort, filter and edit is reported here, which is what lets the row
                // positions be remembered between scrolls
                table.DefaultView.ListChanged += OnViewChanged;
            }
            catch (Exception)
            {
            }
            _dirtyPaint = true;
        }

        public List<DataGridColumn> OrderedFieldColumns()
        {
            return FieldCols.OrderBy(c => c.DisplayIndex).ToList();
        }

        // -- resizing ----------------------------------------------------------

        /// <summary>A borderless AllowsTransparency window carries its own frame.</summary>
        public void WireGrips(Func<string, object> f)
        {
            _grips = new Dictionary<Thumb, (int, int)>();
            var specs = new (string Name, int Horiz, int Vert)[]
            {
                ("GripN", 0, -1), ("GripS", 0, 1),
                ("GripW", -1, 0), ("GripE", 1, 0),
                ("GripNW", -1, -1), ("GripNE", 1, -1),
                ("GripSW", -1, 1), ("GripSE", 1, 1),
            };
            foreach (var spec in specs)
            {
                try
                {
                    Thumb thumb = f(spec.Name) as Thumb;
                    if (thumb == null) continue;
                    _grips[thumb] = (spec.Horiz, spec.Vert);
                    thumb.DragDelta += OnGripDrag;
                    thumb.DragStarted += OnGripStart;
                    if (spec.Name == "GripN" || spec.Name == "GripS")
                    {
                        // preview, not MouseDoubleClick: a Thumb marks the mouse down handled to
                        // start its drag, which can swallow the double-click event entirely
                        thumb.PreviewMouseLeftButtonDown += OnEdgeDoubleClick;
                    }
                }
                catch (Exception)
                {
                    continue;
                }
            }
        }

        public void OnGripStart(object sender, DragStartedEventArgs args)
        {
            _snapBreak = 0.0;
        }

        /// <summary>Wire the shrink-to-taskbar control, the same one every dialog gets.</summary>
        public void BuildDrawer(Func<string, object> f)
        {
            GripHost = f("GripHost") as FrameworkElement;
            Button button = f("ShrinkBtn") as Button;
            Drawer = new WindowDrawer(Window, f("HeaderBar") as FrameworkElement, f("RootGrid") as FrameworkElement,
                                      button, OnDrawerState);
            try
            {
                button.Click += Drawer.Toggle;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// Park the resize grips with the window.
        /// They sit in an overlay spanning every row, so left behind they would line the parked bar
        /// with invisible drag handles and swallow clicks on the arrow that brings the window back.
        /// </summary>
        public void OnDrawerState(bool shrunk)
        {
            try
            {
                if (GripHost != null)
                    GripHost.Visibility = shrunk ? Visibility.Collapsed : Visibility.Visible;
            }
            catch (Exception)
            {
            }
            if (!shrunk)
            {
                // cell colours are painted onto realised rows, so the grid gets the same nudge it
                // gets after a maximise
                RepaintSoon();
            }
        }

        /// <summary>The working area of the screen this window is on, in WPF units.
        /// Shared with the drawer, which parks the window against the bottom of this same
        /// rectangle, so there is one answer rather than two.</summary>
        public (double Left, double Top, double Width, double Height) WindowWorkArea()
        {
            return ScreenWorkArea(Window);
        }

        /// <summary>Fill the screen height, keeping the width: the vertical half of a maximise,
        /// which is what a double-click on a window edge does.</summary>
        public void OnEdgeDoubleClick(object sender, MouseButtonEventArgs args)
        {
            if (Drawer != null && (Drawer.Shrunk || Drawer.Busy)) return;     // nothing to stretch while it is away
            try
            {
                if (args.ClickCount != 2) return;
                args.Handled = true;
            }
            catch (Exception)
            {
                return;
            }
            Window w = Window;
            try
            {
                if (Vstretch == null)
                {
                    var area = WindowWorkArea();
                    Vstretch = (w.Top, w.Height);
                    RestoreRect = null;
                    w.Top = area.Top;
                    w.Height = area.Height;
                    SetStatus("Stretched to the full height — double-click an edge again to put it back.");
                }
                else
                {
                    var back = Vstretch.Value;
                    Vstretch = null;
                    w.Top = back.Top;
                    w.Height = back.Height;
                }
            }
            catch (Exception)
            {
            }
            AlignGroupBar();
            PlaceHandle();
        }

        public void OnGripDrag(object sender, DragDeltaEventArgs args)
        {
            if (Drawer != null && (Drawer.Shrunk || Drawer.Busy)) return;      // the parked bar is not resizable
            Thumb thumb = sender as Thumb;
            (int, int) edges;
            if (thumb == null || !_grips.TryGetValue(thumb, out edges)) return;
            int horiz = edges.Item1;
            int vert = edges.Item2;
            Window w = Window;
            RestoreRect = null;

            if (Vstretch != null && vert != 0)
            {
                // Pulling a vertical edge away from the snap puts the window back to the height it
                // had before, rather than resizing from the stretched one. A few pixels of slack
                // first, so a twitch on the way to a sideways drag cannot undo the snap.
                _snapBreak += Math.Abs(args.VerticalChange);
                if (_snapBreak < SNAP_BREAK_PX) return;
                var back = Vstretch.Value;
                Vstretch = null;
                try
                {
                    // the edge under the cursor stays put; the opposite one moves
                    if (vert < 0)
                    {
                        w.Height = back.Height;
                    }
                    else
                    {
                        double bottom = w.Top + w.ActualHeight;
                        w.Top = bottom - back.Height;
                        w.Height = back.Height;
                    }
                }
                catch (Exception)
                {
                }
                SetStatus("Back to its own height.");
            }
            else if (Vstretch != null && horiz != 0)
            {
                // a sideways drag leaves the snap alone
            }

            try
            {
                double minW = w.MinWidth > 0 ? w.MinWidth : 320;
                double minH = w.MinHeight > 0 ? w.MinHeight : 240;
                double dx = args.HorizontalChange;
                double dy = args.VerticalChange;

                if (horiz > 0)
                {
                    w.Width = Math.Max(minW, w.ActualWidth + dx);
                }
                else if (horiz < 0)
                {
                    double newW = Math.Max(minW, w.ActualWidth - dx);
                    w.Left = w.Left + (w.ActualWidth - newW);
                    w.Width = newW;
                }

                if (vert > 0)
                {
                    w.Height = Math.Max(minH, w.ActualHeight + dy);
                }
                else if (vert < 0)
                {
                    double newH = Math.Max(minH, w.ActualHeight - dy);
                    w.Top = w.Top + (w.ActualHeight - newH);
                    w.Height = newH;
                }
            }
            catch (Exception)
            {
            }
            PlaceHandle();
        }
    }
}
