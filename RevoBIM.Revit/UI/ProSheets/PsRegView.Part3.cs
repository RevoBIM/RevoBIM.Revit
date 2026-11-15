using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Markup;
using System.Windows.Media;
using RevoBIM.Tools.ProSheets;
using RvtView = Autodesk.Revit.DB.View;
using UIApplication = Autodesk.Revit.UI.UIApplication;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsRegView
    {
        public partial class RegisterView
        {
            // ==================================================================
            // including and leaving out
            // ==================================================================

            internal bool IsHeading(DataRow entry)
            {
                try
                {
                    return Str(entry["ishead"]) == "1";
                }
                catch (Exception)
                {
                    return false;
                }
            }

            /// <summary>An issue data row (unfrozen): in the table, never a drawing.</summary>
            internal bool IsIssue(DataRow entry)
            {
                try
                {
                    return Str(entry["key"]).StartsWith(PsRegView.IssuePrefix, StringComparison.Ordinal);
                }
                catch (Exception)
                {
                    return false;
                }
            }

            internal bool IsDrawing(DataRow entry)
            {
                return !IsHeading(entry) && !IsIssue(entry);
            }

            internal static bool Ticked(DataRow entry)
            {
                try
                {
                    return entry["sel"] is bool b && b;
                }
                catch (Exception)
                {
                    return false;
                }
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
                if (Suspend)
                    return;
                DataRow entry;
                bool wanted;
                try
                {
                    entry = args.Row;
                    wanted = Ticked(entry);
                }
                catch (Exception)
                {
                    return;
                }
                if (IsIssue(entry))
                    return;
                IEnumerable<string> keys;
                if (IsHeading(entry))
                {
                    // Hidden members included: a collapsed series is still a
                    // series, and a heading that meant "all but the ones folded
                    // away" would be a trap.
                    keys = new HashSet<string>(Groups.TryGetValue(AsInt(entry["hid"]), out var members)
                                                   ? members : new List<string>(), StringComparer.Ordinal);
                }
                else
                {
                    keys = PsWindow.ProSheetsWindow.TickTargets(Str(entry["key"]), TickSelection);
                }
                TickSelection = new HashSet<string>(StringComparer.Ordinal);
                SetIncluded(keys, wanted);
            }

            /// <summary>Put drawings in the register, or take them out.
            ///
            /// The register's own list - never the Selection tab's print ticks.
            /// Nothing is re-filtered here: a drawing unticked while "Included
            /// only" is showing turns pale rather than vanishing under the cursor.</summary>
            public void SetIncluded(IEnumerable<string> keys, bool wanted)
            {
                var wantedKeys = new HashSet<string>((keys ?? Enumerable.Empty<string>())
                                                     .Where(key => !string.IsNullOrEmpty(key)).Select(key => Str(key)),
                                                     StringComparer.Ordinal);
                if (wantedKeys.Count == 0)
                    return;
                if (wanted)
                    Included.UnionWith(wantedKeys);
                else
                    Included.ExceptWith(wantedKeys);
                Suspend = true;
                try
                {
                    foreach (DataRow entry in Table.Rows)
                    {
                        if (IsHeading(entry))
                            continue;
                        if (wantedKeys.Contains(Str(entry["key"])))
                        {
                            if (Ticked(entry) != wanted)
                                entry["sel"] = wanted;
                        }
                    }
                }
                finally
                {
                    Suspend = false;
                }
                SyncHeadings();
                SaveByHand();
                PaintApply();
                PaintTabStrip();
                Say();
            }

            /// <summary>Put the included list onto the rows on screen.</summary>
            public void SyncTicks()
            {
                Suspend = true;
                try
                {
                    foreach (DataRow entry in Table.Rows)
                    {
                        if (!IsDrawing(entry))
                            continue;
                        bool wanted = Included.Contains(Str(entry["key"]));
                        if (Ticked(entry) != wanted)
                            entry["sel"] = wanted;
                    }
                }
                finally
                {
                    Suspend = false;
                }
                SyncHeadings();
                PaintApply();
                Say();
            }

            /// <summary>Each heading ticked when its whole series is in, with its count.</summary>
            internal void SyncHeadings()
            {
                Suspend = true;
                try
                {
                    foreach (DataRow entry in Table.Rows)
                    {
                        if (!IsHeading(entry))
                            continue;
                        var keys = Groups.TryGetValue(AsInt(entry["hid"]), out var members) ? members : new List<string>();
                        int done = keys.Count(key => Included.Contains(key));
                        bool whole = keys.Count > 0 && done == keys.Count;
                        if (Ticked(entry) != whole)
                            entry["sel"] = whole;
                        entry["name"] = string.Format("{0} drawing{1}, {2} in the register",
                                                      keys.Count, Plural(keys.Count), done);
                    }
                }
                finally
                {
                    Suspend = false;
                }
            }

            internal List<string> VisibleKeys()
            {
                var found = new List<string>();
                foreach (DataRow entry in Table.Rows)
                {
                    if (!IsDrawing(entry))
                        continue;
                    if (Str(entry["show"]) == "1")
                        found.Add(Str(entry["key"]));
                }
                return found;
            }

            public void IncludeVisible(bool wanted)
            {
                SetIncluded(VisibleKeys(), wanted);
            }

            /// <summary>The tick in the tick column's heading. (Python _header_tick;
            /// named ...Core beside the HeaderTick field.)</summary>
            internal void HeaderTickCore(object sender, RoutedEventArgs args)
            {
                bool wanted;
                try
                {
                    wanted = ((CheckBox)sender).IsChecked == true;
                }
                catch (Exception)
                {
                    wanted = true;
                }
                IncludeVisible(wanted);
            }

            /// <summary>A click on a revision's heading isolates the sheets carrying it.
            ///
            /// Ctrl+click adds the revision to what is isolated, or takes it away;
            /// a plain click on the one revision already isolated shows every sheet
            /// again. Before 1.42.0 this ticked those sheets into the register -
            /// a change to the register from a click that reads as "show me".
            /// The Sorting event is where the click arrives, and it is always
            /// cancelled: a register has one order.</summary>
            internal void OnSorting(object sender, DataGridSortingEventArgs args)
            {
                string columnKey;
                try
                {
                    args.Handled = true;
                    columnKey = Str(args.Column.SortMemberPath);
                }
                catch (Exception)
                {
                    return;
                }
                if (!PsRegister.IsColumnKey(columnKey))
                    return;
                var order = UsedColumns.Select(column => column.Key).ToList();
                HashSet<string> wanted;
                if (PsUi.CtrlDown())
                {
                    wanted = new HashSet<string>(Isolated, StringComparer.Ordinal);
                    wanted.SymmetricExceptWith(new[] { columnKey });
                }
                else
                {
                    wanted = (Isolated.Count == 1 && Isolated[0] == columnKey)
                        ? new HashSet<string>(StringComparer.Ordinal)
                        : new HashSet<string>(new[] { columnKey }, StringComparer.Ordinal);
                }
                Isolated = order.Where(key => wanted.Contains(key))
                                .Concat(wanted.OrderBy(key => key, StringComparer.Ordinal).Where(key => !order.Contains(key)))
                                .ToList();
                // The heading goes orange with it: what is isolated is what is
                // picked, so Isolate's button and the context menu agree.
                PickedColumns = order.Where(key => wanted.Contains(key)).ToList();
                ColumnAnchor = columnKey;
                PaintPickedColumns();
                int revealed = RevealIsolated();
                if (revealed == 0)
                {
                    ApplyFilters();
                    Say();
                }
                if (Isolated.Count == 0)
                {
                    Host.Say("Showing every sheet again.");
                    return;
                }
                int shown = VisibleKeys().Count;
                Host.Say(string.Format("Showing the {0} sheet{1} carrying {2}. Click the " +
                                       "heading again to show every sheet.{3}",
                                       shown, Plural(shown), Labels(Isolated),
                                       revealed > 0
                                           ? string.Format(" {0} of them {1} not in the set, so All sheets is on.",
                                                           revealed, revealed == 1 ? "is" : "are")
                                           : ""));
            }

            /// <summary>Note the highlighted rows; fold a series when its heading is hit.
            ///
            /// The highlighted rows are taken here because by the time the tick
            /// change is reported the DataGrid may have reduced the selection to
            /// the one row that was clicked. A click on the heading's own tick box
            /// ticks the series and never folds it.</summary>
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
                if (Host.UnderCheckbox(source))
                {
                    TickSelection = SelectedKeys();
                    return;
                }
                TickSelection = new HashSet<string>(StringComparer.Ordinal);
                DataRow entry;
                try
                {
                    var row = Host.RowUnder(source);
                    entry = row != null ? ((DataRowView)row.Item).Row : null;
                }
                catch (Exception)
                {
                    entry = null;
                }
                if (entry == null)
                    return;
                if (IsIssue(entry))
                {
                    // Unfrozen issue data: a click ticks, or asks for the status.
                    IssueRowClick(entry, ColumnUnder(source));
                    try
                    {
                        args.Handled = true;
                    }
                    catch (Exception)
                    {
                    }
                    return;
                }
                if (!IsHeading(entry))
                {
                    // Not Handled: the grid still selects the row as it always did.
                    // Picking a cell is the register's own state on top of that.
                    CellClick(entry, ColumnUnder(source));
                    return;
                }
                ToggleGroup(Str(entry["gpath"]));
                try
                {
                    args.Handled = true;
                }
                catch (Exception)
                {
                }
            }

            internal HashSet<string> SelectedKeys()
            {
                var found = new HashSet<string>(StringComparer.Ordinal);
                try
                {
                    foreach (var item in Grid.SelectedItems)
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
                        if (!IsDrawing(entry))
                            continue;
                        string key = Str(entry["key"]);
                        if (key.Length > 0)
                            found.Add(key);
                    }
                }
                catch (Exception)
                {
                    return new HashSet<string>(StringComparer.Ordinal);
                }
                return found;
            }

            // ==================================================================
            // picking revisions (Isolate) and revision cells (Change revision)
            // ==================================================================

            internal RoutedEventHandler MakeSeqClick(string columnKey)
            {
                return (sender, args) => PickColumn(columnKey);
            }

            /// <summary>A click on a column's sequence number - see PsRegister.ColumnPicks.</summary>
            public void PickColumn(string columnKey)
            {
                var order = UsedColumns.Select(column => column.Key).ToList();
                var (picked, anchor) = PsRegister.ColumnPicks(PickedColumns, columnKey, ColumnAnchor, order,
                                                              PsUi.CtrlDown(), PsUi.ShiftDown());
                PickedColumns = picked;
                ColumnAnchor = anchor;
                PaintPickedColumns();
                PaintPickButtons();
                if (PickedColumns.Count > 0)
                {
                    Host.Say(string.Format("{0} picked. Isolate shows only the drawings carrying {1}.",
                                           Labels(PickedColumns), PickedColumns.Count == 1 ? "it" : "any of them"));
                }
                else
                {
                    Host.Say("No revision picked.");
                }
            }

            internal void PaintSeqButton(string columnKey)
            {
                if (!SeqButtons.TryGetValue(columnKey, out var button) || button == null)
                    return;
                try
                {
                    button.SetResourceReference(FrameworkElement.StyleProperty,
                                                PickedColumns.Contains(columnKey) ? "SeqChipOn" : "SeqChip");
                }
                catch (Exception)
                {
                }
            }

            /// <summary>The orange wash down a picked column, built on RegisterCell.</summary>
            internal Style PickedColumnStyle()
            {
                if (!Styles.TryGetValue("__picked_column", out var style) || style == null)
                {
                    style = (Style)XamlReader.Parse(string.Format(PsRegView.PickedColumnStyle, PsRegView.Presentation));
                    try
                    {
                        if (Grid.TryFindResource("RegisterCell") is Style baseStyle)
                            style.BasedOn = baseStyle;
                    }
                    catch (Exception)
                    {
                    }
                    Styles["__picked_column"] = style;
                }
                return style;
            }

            /// <summary>The green wash down a newly created revision's column.</summary>
            internal Style FreshColumnStyle()
            {
                if (!Styles.TryGetValue("__fresh_column", out var style) || style == null)
                {
                    style = (Style)XamlReader.Parse(string.Format(PsRegView.FreshColumnStyle, PsRegView.Presentation));
                    try
                    {
                        if (Grid.TryFindResource("RegisterCell") is Style baseStyle)
                            style.BasedOn = baseStyle;
                    }
                    catch (Exception)
                    {
                    }
                    Styles["__fresh_column"] = style;
                }
                return style;
            }

            /// <summary>Picked (orange) beats new (green); neither is no wash.</summary>
            internal Style ColumnWash(string columnKey)
            {
                if (PickedColumns.Contains(columnKey))
                    return PickedColumnStyle();
                if (FreshColumns.Contains(columnKey))
                    return FreshColumnStyle();
                return null;
            }

            internal void PaintPickedColumns()
            {
                foreach (var column in UsedColumns)
                {
                    if (Columns.TryGetValue(column.Key, out var gridColumn) && gridColumn != null)
                    {
                        try
                        {
                            var wash = ColumnWash(column.Key);
                            if (wash != null)
                                gridColumn.CellStyle = wash;
                            else
                                // Back to the grid's own RegisterCell.
                                gridColumn.ClearValue(DataGridColumn.CellStyleProperty);
                        }
                        catch (Exception)
                        {
                        }
                    }
                    PaintSeqButton(column.Key);
                }
            }

            /// <summary>Show only the drawings carrying a picked revision - or, when
            /// isolated already, every drawing again. Never touches the model.</summary>
            public void ToggleIsolate()
            {
                if (Isolated.Count > 0)
                {
                    Isolated = new List<string>();
                    ApplyFilters();
                    Say();
                    Host.Say("Showing every sheet again.");
                    return;
                }
                if (PickedColumns.Count == 0)
                    return;
                Isolated = new List<string>(PickedColumns);
                if (RevealIsolated() == 0)
                {
                    ApplyFilters();
                    Say();
                }
                int shown = VisibleKeys().Count;
                Host.Say(string.Format("Showing only the {0} sheet{1} carrying {2}. Show all " +
                                       "sheets (or Reset filters) brings the rest back.",
                                       shown, Plural(shown), Labels(Isolated)));
            }

            /// <summary>Isolate lit while a revision is picked or the view is isolated;
            /// Change revision lit while a cell is picked. Solid orange when lit,
            /// like every other "on" in the tool; dimmed when there is nothing to
            /// do, so it reads as waiting rather than broken.</summary>
            internal void PaintPickButtons()
            {
                Light(IsolateButton, PickedColumns.Count > 0 || Isolated.Count > 0);
                PsUi.SetText(IsolateText, Isolated.Count > 0 ? "Show all sheets"
                    : (PickedColumns.Count > 1 ? "Isolate sheets with these revisions"
                                               : "Isolate sheets with this revision"));
                int count = PickedCells.Count;
                int sheets = PickedCells.Select(cell => cell.Sheet).Distinct().Count();
                PsUi.SetVisible(CellTools, count > 0);
                PsUi.SetText(CellToolsText, string.Format("{0} cell{1} on {2} sheet{3}",
                                                          count, Plural(count), sheets, Plural(sheets)));
            }

            internal void Light(Button button, bool lit)
            {
                if (button == null)
                    return;
                try
                {
                    button.IsEnabled = lit;
                    button.Opacity = lit ? 1.0 : 0.5;
                    button.SetResourceReference(FrameworkElement.StyleProperty, lit ? "SwitchButtonOn" : "ChipButton");
                }
                catch (Exception)
                {
                }
            }

            internal string Labels(IEnumerable<string> columnKeys)
            {
                var byKey = new Dictionary<string, PsRegister.RevisionColumn>(StringComparer.Ordinal);
                foreach (var revision in Revisions)
                    byKey[revision.Key] = revision;
                var names = new List<string>();
                foreach (var key in columnKeys)
                {
                    if (key == null || !byKey.TryGetValue(key, out var revision))
                    {
                        names.Add(key);
                        continue;
                    }
                    names.Add(string.Format("Seq {0}{1}", revision.Sequence,
                                            !string.IsNullOrEmpty(revision.Date)
                                                ? string.Format(" ({0})", revision.Date) : ""));
                }
                return string.Join(", ", names);
            }

            internal string ElementLabel(object elementKey)
            {
                foreach (var revision in Revisions)
                {
                    if (Str(revision.ElementKey) == Str(elementKey))
                        return Labels(new[] { revision.Key });
                }
                return string.Format("revision {0}", Str(elementKey));
            }

            internal string SheetLabel(object sheetKey)
            {
                RowsByKey.TryGetValue(Str(sheetKey), out var row);
                return row != null && !string.IsNullOrEmpty(row.Number)
                    ? row.Number
                    : string.Format("sheet {0}", Str(sheetKey));
            }

            /// <summary>One step up the tree: the visual parent, or - for a Run inside a
            /// TextBlock, which is not a Visual - its logical parent.</summary>
            internal static DependencyObject ParentOf(DependencyObject node)
            {
                try
                {
                    return VisualTreeHelper.GetParent(node);
                }
                catch (Exception)
                {
                    if (node is FrameworkContentElement content)
                        return content.Parent;
                    if (node is FrameworkElement element)
                        return element.Parent;
                    return null;
                }
            }

            /// <summary>The SortMemberPath of the cell a click landed in, or "". A
            /// revision column's is its key.</summary>
            internal string ColumnUnder(object source)
            {
                var node = source as DependencyObject;
                for (int step = 0; step < 14; step++)
                {
                    if (node == null)
                        return "";
                    if (node is DataGridCell cell)
                    {
                        try
                        {
                            return Str(cell.Column.SortMemberPath);
                        }
                        catch (Exception)
                        {
                            return "";
                        }
                    }
                    node = ParentOf(node);
                }
                return "";
            }

            /// <summary>Whether the sheet carries the revision - staged edits
            /// included, so a cell staged in can be picked and one staged out
            /// cannot.</summary>
            internal bool Filled(string sheetKey, string columnKey)
            {
                if (PendingFlags.TryGetValue((Str(sheetKey), columnKey), out string flag) && !string.IsNullOrEmpty(flag))
                    return flag == PsRegister.PendingAdd;
                RowsByKey.TryGetValue(Str(sheetKey), out var row);
                if (row == null)
                    return false;
                row.Cells.TryGetValue(columnKey ?? "", out var text);
                return (text ?? "").Trim().Length > 0;
            }

            /// <summary>The drawings in the order the grid shows them - what a
            /// Shift+click's block is measured along.</summary>
            internal List<string> ShownRows()
            {
                var found = new List<string>();
                try
                {
                    foreach (DataRowView item in View)
                    {
                        var entry = item.Row;
                        if (IsDrawing(entry))
                            found.Add(Str(entry["key"]));
                    }
                }
                catch (Exception)
                {
                }
                return found;
            }

            /// <summary>A click on a drawing's row: a filled revision cell is picked (see
            /// PsRegister.CellPicks); a plain click anywhere else lets the picks go.</summary>
            internal void CellClick(DataRow entry, string columnKey)
            {
                bool ctrl = PsUi.CtrlDown(), shift = PsUi.ShiftDown();
                string sheet = Str(entry["key"]);
                if (!PsRegister.IsColumnKey(columnKey) || !Filled(sheet, columnKey))
                {
                    if (PickedCells.Count > 0 && !ctrl && !shift)
                        SetPickedCells(new HashSet<(string Sheet, string Column)>());
                    return;
                }
                var (picked, anchor) = PsRegister.CellPicks(
                    PickedCells, (sheet, columnKey), CellAnchor, ShownRows(),
                    UsedColumns.Select(column => column.Key).ToList(), Filled, ctrl, shift);
                CellAnchor = anchor;
                SetPickedCells(picked);
            }

            /// <summary>Write the p_ flags that differ. They drive the cell style only -
            /// not the view's filter or order - so this is safe mid-edit.</summary>
            internal void SetPickedCells(IEnumerable<(string Sheet, string Column)> picked)
            {
                var before = new HashSet<(string Sheet, string Column)>(PickedCells);
                var after = new HashSet<(string Sheet, string Column)>(picked);
                Suspend = true;
                try
                {
                    foreach (var (sheet, columnKey) in before.Where(cell => !after.Contains(cell)))
                        FlagCell(sheet, columnKey, "");
                    foreach (var (sheet, columnKey) in after.Where(cell => !before.Contains(cell)))
                        FlagCell(sheet, columnKey, "1");
                }
                finally
                {
                    Suspend = false;
                }
                PickedCells = after;
                PaintPickButtons();
                if (after.Count > 0)
                {
                    int sheets = after.Select(cell => cell.Sheet).Distinct().Count();
                    Host.Say(string.Format("{0} revision cell{1} on {2} sheet{3} picked. " +
                                           "Change revision on sheet moves them to another revision.",
                                           after.Count, Plural(after.Count), sheets, Plural(sheets)));
                }
            }

            internal void FlagCell(string sheet, string columnKey, string value)
            {
                if (!Entries.TryGetValue(sheet, out var entry) || entry == null)
                    return;
                try
                {
                    entry[PsRegView.PickPrefix + columnKey] = value;
                }
                catch (Exception)
                {
                }
            }

            /// <summary>Escape: let go of every picked cell and revision. An Isolate in
            /// force stays - it has a button of its own to undo it.</summary>
            public void ClearPicks()
            {
                SetPickedCells(new HashSet<(string Sheet, string Column)>());
                CellAnchor = null;
                if (PickedColumns.Count > 0)
                {
                    PickedColumns = new List<string>();
                    ColumnAnchor = null;
                    PaintPickedColumns();
                }
                PaintPickButtons();
                Host.Say("Nothing picked.");
            }

            /// <summary>Change the picked cells to another revision - staged. Nothing is
            /// written until Apply revisions, which moves them on the sheets and
            /// in their clouds (PsRevisions.SwapOnSheets).</summary>
            public void ChangeRevision()
            {
                if (PickedCells.Count == 0)
                    return;
                var picks = PicksBySheet();
                var olds = new HashSet<string>(StringComparer.Ordinal);
                foreach (var revisions in picks.Values)
                    olds.UnionWith(revisions);
                string target;
                try
                {
                    target = Str(PsRevSwapWin.Choose(
                        Revisions, olds.OrderBy(one => one, StringComparer.Ordinal).ToList(), picks.Count,
                        PickedCells.Count, Host.ThemeName, Window,
                        note: "Staged: nothing changes in Revit until Apply " +
                              "revisions. Then a revision added by hand is swapped " +
                              "on the sheet, and its clouds move to the new " +
                              "revision. Issued revisions are locked by Revit and " +
                              "cannot be chosen."));
                }
                catch (Exception err)
                {
                    Host.Say(string.Format("The revision list would not open: {0}", err.Message));
                    return;
                }
                if (string.IsNullOrEmpty(target))
                {
                    Host.Say("Change revision on sheet cancelled - nothing changed.");
                    return;
                }
                string column = PsRegister.ColumnKey((object)target);
                var chosen = new Dictionary<string, List<string>>(StringComparer.Ordinal);
                foreach (var (sheet, old) in PickedCells)
                {
                    if (old != column)
                    {
                        if (!chosen.TryGetValue(sheet, out var list))
                            chosen[sheet] = list = new List<string>();
                        list.Add(old);
                    }
                }
                if (chosen.Count == 0)
                {
                    Host.Say("Every picked cell is that revision already.");
                    return;
                }
                var edit = new PsRegister.PendingEdit
                {
                    Kind = "change",
                    Target = column,
                    Picks = chosen.ToDictionary(pair => pair.Key,
                                                pair => pair.Value.OrderBy(one => one, StringComparer.Ordinal).ToList(),
                                                StringComparer.Ordinal),
                };
                SetPickedCells(new HashSet<(string Sheet, string Column)>());
                Stage(edit);
            }

            /// <summary>{sheet key: set of revision element keys} for the picked cells.</summary>
            internal Dictionary<string, HashSet<string>> PicksBySheet()
            {
                var picks = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
                foreach (var (sheet, columnKey) in PickedCells)
                {
                    string element = PsRegister.ElementOf(columnKey);
                    if (!string.IsNullOrEmpty(element))
                    {
                        if (!picks.TryGetValue(sheet, out var set))
                            picks[sheet] = set = new HashSet<string>(StringComparer.Ordinal);
                        set.Add(element);
                    }
                }
                return picks;
            }

            /// <summary>The picked cells as {sheet: [column keys, sorted]}.</summary>
            internal Dictionary<string, List<string>> PickedColumnsBySheet()
            {
                var chosen = new Dictionary<string, List<string>>(StringComparer.Ordinal);
                foreach (var (sheet, column) in PickedCells)
                {
                    if (!chosen.TryGetValue(sheet, out var list))
                        chosen[sheet] = list = new List<string>();
                    list.Add(column);
                }
                return chosen.ToDictionary(pair => pair.Key,
                                           pair => pair.Value.OrderBy(one => one, StringComparer.Ordinal).ToList(),
                                           StringComparer.Ordinal);
            }

            /// <summary>Take the picked revisions off their sheets - staged. Apply
            /// revisions asks first, because that is when the clouds are deleted.</summary>
            public void RemoveRevision()
            {
                if (PickedCells.Count == 0)
                    return;
                var edit = new PsRegister.PendingEdit { Kind = "remove", Picks = PickedColumnsBySheet() };
                SetPickedCells(new HashSet<(string Sheet, string Column)>());
                Stage(edit);
            }

            /// <summary>A new revision, onto the picked cells.
            ///
            /// The Add revision window opens with the sequence just after the
            /// latest revision picked. Once it is filled in, one job creates it,
            /// reads which revision is new from the model, and moves every picked
            /// cell onto it - sheets and clouds - exactly as Change revision does.</summary>
            public void CreateRevision()
            {
                if (PickedCells.Count == 0)
                    return;
                var picks = PicksBySheet();
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
                var olds = new HashSet<string>(StringComparer.Ordinal);
                foreach (var revisions in picks.Values)
                    olds.UnionWith(revisions);
                var after = olds.Where(key => staging.Entries.ContainsKey(key))
                                .Select(key => staging.StagedSequence(key))
                                .Where(one => one.HasValue && one.Value != 0)
                                .Select(one => one.Value)
                                .ToList();
                int? position = after.Count > 0 ? after.Max() + 1 : (int?)null;
                var columns = PickedCells.Select(cell => cell.Column).Distinct()
                                         .OrderBy(one => one, StringComparer.Ordinal).ToList();
                string note = string.Format("Made as soon as you press Add. The {1} picked cell{2} " +
                                            "now on {0} are then staged onto it, shown green, until " +
                                            "Apply revisions.", Labels(columns), PickedCells.Count,
                                            Plural(PickedCells.Count));
                Action add;
                try
                {
                    var answer = PsRevAddWin.Ask(staging, Host.ThemeName, Window, position, note);
                    add = answer == null ? (Action)null
                        : () => staging.Add(answer.Position, answer.Fields, answer.Custom);
                }
                catch (Exception err)
                {
                    Host.Say(string.Format("The Add revision window would not open: {0}", err.Message));
                    return;
                }
                if (add == null)
                {
                    Host.Say("Create new revision cancelled - nothing changed.");
                    return;
                }
                add();
                var plan = staging.Plan();
                var chosen = PickedColumnsBySheet();
                var doc = Host.Doc;

                // On Revit's thread: the revision is made now; the cells moving
                // onto it are staged, for Apply revisions.
                void Job(UIApplication uiapp)
                {
                    string made;
                    List<string> errors;
                    try
                    {
                        (made, errors) = PsRevisions.CreateOnly(doc, plan);
                    }
                    catch (Exception err)
                    {
                        made = "";
                        errors = new List<string> { string.Format("Nothing was changed: {0}", err.Message) };
                    }
                    Host.OnUi(() => Created(made, errors, chosen));
                }

                if (Host.Queue(Job))
                    Host.Say("Creating the revision...");
            }

            /// <summary>The new revision is in the model: show it green and stage the
            /// picked cells onto it.</summary>
            internal void Created(string made, List<string> errors, Dictionary<string, List<string>> chosen)
            {
                Reload();
                if (string.IsNullOrEmpty(made))
                {
                    new PsUi.Prompt(
                        title: "Create new revision",
                        headline: "The new revision was not made.",
                        message: "No cell was staged onto it.",
                        detail: string.Join("\n", errors ?? new List<string>()), primary: "Close",
                        themeName: Host.ThemeName, owner: Window).Show();
                    return;
                }
                string column = PsRegister.ColumnKey((object)made);
                FreshColumns = new HashSet<string>(new[] { column }, StringComparer.Ordinal);
                if (HideUnused)
                    SetShowAllRevisions(true, quiet: true);
                PaintPickedColumns();
                Stage(new PsRegister.PendingEdit { Kind = "change", Target = column, Picks = chosen });
            }

            /// <summary>One revision picked: the Edit revision window. Several: the
            /// Revision Manager, opened on them.</summary>
            public void EditRevision()
            {
                var keys = PickedRevisions();
                if (keys.Count == 0)
                    return;
                if (keys.Count == 1)
                {
                    EditRevisionBox(keys[0]);
                    return;
                }
                OpenRevisionManager(focus: keys.OrderBy(one => one, StringComparer.Ordinal).ToList());
            }

            /// <summary>The element keys of every revision picked - by its column, or by
            /// a cell - in column order.</summary>
            internal List<string> PickedRevisions()
            {
                var columns = new List<string>(PickedColumns);
                foreach (var (_, column) in PickedCells)
                {
                    if (!columns.Contains(column))
                        columns.Add(column);
                }
                var order = UsedColumns.Select(column => column.Key).ToList();
                columns = columns.OrderBy(key => order.Contains(key) ? order.IndexOf(key) : order.Count).ToList();
                return columns.Where(key => !string.IsNullOrEmpty(PsRegister.ElementOf(key)))
                              .Select(key => PsRegister.ElementOf(key)).ToList();
            }

            /// <summary>Every property of one revision in the Edit revision window;
            /// Apply writes it and the register reads the model again.</summary>
            public void EditRevisionBox(string elementKey)
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
                string key = Str(elementKey);
                if (!staging.Entries.ContainsKey(key))
                {
                    Host.Say("That revision is no longer in the project.");
                    return;
                }
                Func<List<string>> edit;
                try
                {
                    var answer = PsRevAddWin.AskEdit(staging, key, Host.ThemeName, Window);
                    edit = answer == null ? (Func<List<string>>)null
                        : () => staging.Edit(key, answer.Fields, answer.Custom);
                }
                catch (Exception err)
                {
                    Host.Say(string.Format("The Edit revision window would not open: {0}", err.Message));
                    return;
                }
                if (edit == null)
                {
                    Host.Say("Edit revision cancelled - nothing changed.");
                    return;
                }
                var refusals = edit() ?? new List<string>();
                var plan = staging.Plan();
                if (PsRevisions.PlanIsEmpty(plan))
                {
                    string joined = string.Join(" ", refusals);
                    Host.Say(joined.Length > 0 ? joined : "Nothing to change.");
                    return;
                }

                // On Revit's thread.
                void Job(UIApplication uiapp)
                {
                    WriteRevisions(plan);
                }

                if (Host.Queue(Job))
                {
                    Host.Say("Updating the revision..." +
                             (refusals.Count > 0 ? " " + string.Join(" ", refusals) : ""));
                }
            }

            // ------------------------------------------- highlighted sheets

            internal void RowsSelected(object sender, SelectionChangedEventArgs args)
            {
                PaintSheetTools();
            }

            internal void PaintSheetTools()
            {
                var keys = SelectedKeys();
                PsUi.SetVisible(SheetTools, keys.Count > 0);
                PsUi.SetText(SheetToolsText, string.Format("{0} sheet{1}", keys.Count, Plural(keys.Count)));
            }

            /// <summary>A revision onto every highlighted sheet, by hand - as Revit's
            /// Revisions on Sheet does. Staged until Apply revisions.</summary>
            public void AssignRevision()
            {
                var keys = SelectedKeys().OrderBy(one => one, StringComparer.Ordinal).ToList();
                if (keys.Count == 0)
                    return;
                var labels = keys.Select(key => SheetLabel(key)).ToList();
                string target;
                try
                {
                    target = Str(PsRevSwapWin.Choose(
                        Revisions, new List<string>(), keys.Count, 0, Host.ThemeName, Window,
                        headline: string.Format("Assign a revision to {0} sheet{1}", keys.Count, Plural(keys.Count)),
                        fromText: "Sheets: " + string.Join(", ", labels.Take(8)) +
                                  (labels.Count > 8 ? string.Format(" and {0} more", labels.Count - 8) : ""),
                        note: "Staged: added to each sheet by hand, as Revit's " +
                              "Revisions on Sheet does, when you press Apply " +
                              "revisions. A sheet already carrying it is left as it " +
                              "is. Issued revisions are locked by Revit and cannot " +
                              "be added.",
                        okText: "Assign"));
                }
                catch (Exception err)
                {
                    Host.Say(string.Format("The revision list would not open: {0}", err.Message));
                    return;
                }
                if (string.IsNullOrEmpty(target))
                {
                    Host.Say("Assign revision cancelled - nothing changed.");
                    return;
                }
                string column = PsRegister.ColumnKey((object)target);
                var sheets = keys.Where(key => !Filled(key, column)).ToList();
                if (sheets.Count == 0)
                {
                    Host.Say(string.Format("Every highlighted sheet carries {0} already.", ElementLabel(target)));
                    return;
                }
                Stage(new PsRegister.PendingEdit { Kind = "assign", Target = column, Sheets = sheets });
            }

            internal T Hit<T>(object source) where T : DependencyObject
            {
                var node = source as DependencyObject;
                for (int step = 0; step < 16; step++)
                {
                    if (node == null)
                        return null;
                    if (node is T found)
                        return found;
                    node = ParentOf(node);
                }
                return null;
            }

            /// <summary>A right-click on something not picked picks it first - Excel's
            /// way - so the menu acts on what is under the pointer.</summary>
            internal void RightPress(object sender, MouseButtonEventArgs args)
            {
                MenuHeading = null;
                object source;
                try
                {
                    source = args.OriginalSource;
                }
                catch (Exception)
                {
                    return;
                }
                var header = Hit<DataGridColumnHeader>(source);
                if (header != null)
                {
                    string key;
                    try
                    {
                        key = Str(header.Column.SortMemberPath);
                    }
                    catch (Exception)
                    {
                        key = "";
                    }
                    if (PsRegister.IsColumnKey(key) && !PickedColumns.Contains(key))
                    {
                        PickedColumns = new List<string> { key };
                        ColumnAnchor = key;
                        PaintPickedColumns();
                        PaintPickButtons();
                    }
                    return;
                }
                var row = Hit<DataGridRow>(source);
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
                if (IsIssue(entry))
                    return;
                if (IsHeading(entry))
                {
                    // The colour menu acts on this heading.
                    try
                    {
                        MenuHeading = Str(entry["glabel"]);
                    }
                    catch (Exception)
                    {
                        MenuHeading = null;
                    }
                    return;
                }
                string sheet = Str(entry["key"]);
                string column = ColumnUnder(source);
                if (PsRegister.IsColumnKey(column) && Filled(sheet, column) && !PickedCells.Contains((sheet, column)))
                {
                    SetPickedCells(new HashSet<(string Sheet, string Column)> { (sheet, column) });
                    CellAnchor = (sheet, column);
                }
                if (!SelectedKeys().Contains(sheet))
                {
                    try
                    {
                        Grid.SelectedItems.Clear();
                        Grid.SelectedItems.Add(row.Item);
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            internal void RightRelease(object sender, MouseButtonEventArgs args)
            {
                try
                {
                    var menu = RegisterMenu();
                    menu.PlacementTarget = Grid;
                    menu.IsOpen = true;
                    args.Handled = true;
                }
                catch (Exception)
                {
                }
            }

            internal MenuItem MenuItem(string text, Action handler)
            {
                var item = new MenuItem();
                Host.Styled(item, "ThemedMenuItem");
                item.Header = text;
                item.Click += (sender, args) => handler();
                return item;
            }

            /// <summary>[(text, action name)] for the right-click menu as things stand -
            /// null for a separator. What is offered depends only on what is
            /// highlighted and picked.</summary>
            public List<(string Text, string Action)?> MenuEntries()
            {
                var sheets = SelectedKeys();
                var revisions = PickedRevisions();
                var entries = new List<(string Text, string Action)?>();
                string heading = MenuHeading;
                if (!string.IsNullOrEmpty(heading))
                {
                    // A right-click on a heading: its colour first.
                    entries.Add((string.Format("Colour \"{0}\"", heading), "heading_swatches"));
                    entries.Add(("Custom colour...", "custom_heading_colour"));
                    var custom = HeadingCustom ?? new Dictionary<string, string>();
                    if (custom.ContainsKey(heading))
                        entries.Add(("Reset this heading's colour", "reset_heading_colour"));
                    if (custom.Count > 0)
                        entries.Add(("Reset every heading colour", "reset_heading_colours"));
                    entries.Add(null);
                }
                if (sheets.Count > 0)
                {
                    entries.Add((sheets.Count == 1 ? "Open sheet" : "Open sheets", "open_sheets"));
                    entries.Add((string.Format("Assign revision to {0} selected sheet{1}...",
                                               sheets.Count, Plural(sheets.Count)), "assign_revision"));
                }
                if (revisions.Count > 0)
                {
                    if (entries.Count > 0)
                        entries.Add(null);
                    entries.Add((revisions.Count == 1 ? "Edit revision..."
                                     : string.Format("Edit {0} revisions in the Revision Manager...", revisions.Count),
                                 "edit_revision"));
                }
                if (PickedCells.Count > 0)
                {
                    entries.Add(("Create new revision...", "create_revision"));
                    entries.Add(("Change revision...", "change_revision"));
                    entries.Add(("Remove revision...", "remove_revision"));
                }
                if (PickedColumns.Count > 0 || Isolated.Count > 0)
                {
                    entries.Add((Isolated.Count > 0 ? "Show all sheets" : "Isolate sheets with this revision",
                                 "toggle_isolate"));
                }
                if (Pending != null && Pending.Count > 0)
                {
                    if (entries.Count > 0)
                        entries.Add(null);
                    entries.Add((string.Format("Apply revisions ({0} staged)", Pending.Count), "apply_revisions"));
                    entries.Add(("Undo   Ctrl+Z", "undo"));
                }
                if (entries.Count > 0)
                    entries.Add(null);
                entries.Add(("New revision...", "new_revision"));
                entries.Add(("Revision Manager...", "open_revision_manager"));
                return entries;
            }

            /// <summary>The method a menu entry's action name stands for (Python getattr).</summary>
            internal Action ActionFor(string name)
            {
                switch (name)
                {
                    case "custom_heading_colour": return CustomHeadingColour;
                    case "reset_heading_colour": return ResetHeadingColour;
                    case "reset_heading_colours": return ResetHeadingColours;
                    case "open_sheets": return () => OpenSheets();
                    case "assign_revision": return AssignRevision;
                    case "edit_revision": return EditRevision;
                    case "create_revision": return CreateRevision;
                    case "change_revision": return ChangeRevision;
                    case "remove_revision": return RemoveRevision;
                    case "toggle_isolate": return ToggleIsolate;
                    case "apply_revisions": return ApplyRevisions;
                    case "undo": return Undo;
                    case "new_revision": return NewRevision;
                    case "open_revision_manager": return () => OpenRevisionManager();
                    default: return () => { };
                }
            }

            /// <summary>The highlighted drawings' sheets, top of the register first.</summary>
            public List<RvtView> HighlightedSheets()
            {
                var found = new List<(int Place, RvtView Sheet)>();
                List<object> items;
                try
                {
                    items = Grid.SelectedItems.Cast<object>().ToList();
                }
                catch (Exception)
                {
                    return new List<RvtView>();
                }
                var elements = Elements ?? new Dictionary<string, Autodesk.Revit.DB.Element>();
                foreach (var item in items)
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
                    if (!IsDrawing(entry))
                        continue;
                    elements.TryGetValue(Str(entry["key"]), out var element);
                    var sheet = element as RvtView;
                    if (sheet == null)
                        continue;
                    int place;
                    try
                    {
                        place = Grid.Items.IndexOf(item);
                    }
                    catch (Exception)
                    {
                        place = found.Count;
                    }
                    found.Add((place, sheet));
                }
                return found.OrderBy(pair => pair.Place).Select(pair => pair.Sheet).ToList();
            }

            /// <summary>Open sheets on the right-click: the highlighted drawings opened
            /// in Revit, and the window shrunk to the bottom of the screen.</summary>
            public bool OpenSheets()
            {
                return Host.OpenSheets(HighlightedSheets(), "sheet");
            }

            internal ContextMenu RegisterMenu()
            {
                var menu = new ContextMenu();
                Host.Styled(menu, "ThemedContextMenu");
                foreach (var entry in MenuEntries())
                {
                    if (entry == null)
                    {
                        menu.Items.Add(new Separator());
                        continue;
                    }
                    var (text, action) = entry.Value;
                    if (action == "heading_swatches")
                    {
                        menu.Items.Add(SwatchItem(text, menu));
                        continue;
                    }
                    menu.Items.Add(MenuItem(text, ActionFor(action)));
                }
                return menu;
            }
        }
    }
}
