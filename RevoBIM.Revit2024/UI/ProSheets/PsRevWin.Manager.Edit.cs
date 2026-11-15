using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Threading;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsRevWin
    {
        public partial class RevisionManager
        {
            // ==================================================================
            // the table, from the staging
            // ==================================================================

            /// <summary>Rebuild every row. After an add, delete, move or merge.</summary>
            internal void Refill(IEnumerable<string> reselect = null)
            {
                Suspend = true;
                try
                {
                    Table.Rows.Clear();
                    Rows = new Dictionary<string, DataRow>(StringComparer.Ordinal);
                    foreach (var key in Staging.Order)
                    {
                        var entry = Staging.Entries[key];
                        var row = Table.NewRow();
                        row["key"] = key;
                        foreach (var field in PsRevisions.Fields)
                            row[field] = Db(entry.Fields.TryGetValue(field, out var value) ? value : null);
                        foreach (var column in Staging.Columns)
                        {
                            string value = PsRevisions.Staging.CustomValue(entry, column);
                            row["x_" + column.Id] = column.Kind == "yesno" ? (object)(value == "1") : value;
                        }
                        row["used"] = entry.Used.ToString(Inv);
                        row["unplaced"] = entry.Unplaced.ToString(Inv);
                        row["unplaced_tip"] = UnplacedTip(entry);
                        FillSeries(row, entry);
                        row["series_open"] = SeriesOpen;
                        row["sheets_tip"] = SheetsTip(entry);
                        Table.Rows.Add(row);
                        Rows[key] = row;
                    }
                }
                finally
                {
                    Suspend = false;
                }
                Refresh();
                if (reselect != null && reselect.Any())
                    Select(reselect);
            }

            /// <summary>{series: (fill, edge)} - one colour per series across the whole project,
            /// from the register's group palette, so BW-BUILDERSWORK is the same colour on every
            /// row.</summary>
            internal Dictionary<string, (Brush Fill, Brush Edge)> SeriesBrushes()
            {
                var names = new List<string>();
                foreach (var entry in Staging.Entries.Values)
                {
                    foreach (var name in entry.Series)
                    {
                        if (!names.Contains(name))
                            names.Add(name);
                    }
                }
                names = names.OrderBy(name => PsModel.NaturalKey(name)).ToList();
                var found = new Dictionary<string, (Brush Fill, Brush Edge)>(StringComparer.Ordinal);
                for (int index = 0; index < names.Count; index++)
                {
                    found[names[index]] = (
                        PsTheme.Brush(PsTheme.GroupColour(index, ThemeName)),
                        PsTheme.Brush(PsTheme.GroupColour(index, ThemeName, heading: true)));
                }
                return found;
            }

            internal void FillSeries(DataRow row, PsRevisions.Entry entry)
            {
                if (Colours == null)
                    Colours = SeriesBrushes();
                var chips = new List<object>();
                foreach (var name in entry.Series)
                {
                    var (fill, edge) = Colours.TryGetValue(name, out var found)
                        ? found
                        : ((Brush)PsTheme.Brush("#808080"), (Brush)PsTheme.Brush("#606060"));
                    chips.Add(Tuple.Create(name, fill, edge));
                }
                var head = new List<object>();
                if (chips.Count > 0)
                    head.Add(chips[0]);
                row["series"] = string.Join(", ", entry.Series);
                row["series_items"] = chips;
                row["series_head"] = head;
                row["series_more"] = entry.Series.Count > 1
                    ? "+" + (entry.Series.Count - 1).ToString(Inv) : "";
            }

            internal static void Put(DataRow row, string column, object value)
            {
                try
                {
                    if (Str(row[column]) == Str(value))
                        return;
                }
                catch (Exception)
                {
                }
                row[column] = Db(value);
            }

            internal static string UnplacedTip(PsRevisions.Entry entry)
            {
                if (entry.OffViews == null || entry.OffViews.Count == 0)
                    return "Every cloud of this revision is in a view on a sheet.";
                var lines = new List<string>
                {
                    string.Format(Inv, "{0} cloud{1} in views on no sheet - right-click > Find clouds on views to see them:",
                                  entry.Unplaced, entry.Unplaced == 1 ? "" : "s"),
                };
                foreach (var (_, name, count) in entry.OffViews.Take(20))
                    lines.Add(string.Format(Inv, "{0} ({1})", name, count));
                if (entry.OffViews.Count > 20)
                    lines.Add(string.Format(Inv, "and {0} more", entry.OffViews.Count - 20));
                return string.Join("\n", lines);
            }

            internal static string SheetsTip(PsRevisions.Entry entry)
            {
                if (entry.IsNew)
                    return "New - on no sheets yet";
                var lines = new List<string>
                {
                    string.Format(Inv, "On {0} sheet{1}, {2} cloud{3}",
                                  entry.Used, entry.Used == 1 ? "" : "s", entry.Clouds, entry.Clouds == 1 ? "" : "s"),
                };
                if (entry.Sheets != null && entry.Sheets.Count > 0)
                {
                    var shown = entry.Sheets.Take(25);
                    lines.Add(string.Join(", ", shown) +
                              (entry.Sheets.Count > 25 ? string.Format(Inv, " and {0} more", entry.Sheets.Count - 25) : ""));
                }
                return string.Join("\n", lines);
            }

            /// <summary>
            /// Every row's flags - and, unless a cell is mid-edit, its order and visibility - from the
            /// staging. Only values that differ are written. Re-sorting or re-filtering the view while
            /// the grid holds a row open for editing makes WPF throw, so an edit
            /// (<paramref name="layout"/> false) touches the flags and nothing the view sorts or
            /// filters on; the next search or move catches the rest up.
            /// </summary>
            internal void Refresh(bool layout = true)
            {
                var visible = layout
                    ? new HashSet<string>(Staging.Visible(Filters, Picks, FilterSheet()), StringComparer.Ordinal)
                    : null;
                Suspend = true;
                try
                {
                    for (int index = 0; index < Staging.Order.Count; index++)
                    {
                        string key = Staging.Order[index];
                        if (!Rows.TryGetValue(key, out var row) || row == null)
                            continue;
                        var entry = Staging.Entries[key];
                        var changed = Staging.Changed(key);
                        var values = Staging.Values(key);
                        // Not a column any more: the Sequence cell's tooltip.
                        Put(row, "pending", values["pending"]);
                        Put(row, "seq", values["seq"]);
                        Put(row, "live", entry.Live ? "1" : "0");
                        Put(row, "fresh", entry.IsNew && entry.Live ? "1" : "0");
                        if (layout)
                        {
                            Put(row, "ord", index.ToString("00000", Inv));
                            Put(row, "vis", visible.Contains(key) ? "1" : "0");
                        }
                        var fields = new List<string> { "seq" };
                        fields.AddRange(PsRevisions.Fields);
                        fields.AddRange(Staging.Columns.Select(column => "x_" + column.Id));
                        foreach (var field in fields)
                            Put(row, "c_" + field, changed.Contains(field) && entry.Live ? "1" : "0");
                    }
                }
                finally
                {
                    Suspend = false;
                }
                PaintSettings();
                PaintFooter();
            }

            internal void PaintSettings()
            {
                var changed = Staging.SettingsChanged();
                foreach (var radio in new[] { PerProject, PerSheet })
                {
                    if (radio == null)
                        continue;
                    try
                    {
                        radio.SetResourceReference(Control.ForegroundProperty,
                                                   changed.Contains("numbering") ? "GreenBrush" : "TextBrush");
                    }
                    catch (Exception)
                    {
                    }
                }
                if (ArcBox != null)
                {
                    try
                    {
                        ArcBox.SetResourceReference(Control.BorderBrushProperty,
                                                    changed.Contains("arc_mm") ? "GreenBrush" : "EdgeBrush");
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            internal void PaintFooter()
            {
                int count = Staging.ChangeCount();
                if (ApplyButton != null)
                {
                    try
                    {
                        ApplyButton.IsEnabled = count > 0;
                        ApplyButton.Content = count != 0 ? string.Format(Inv, "Apply ({0})", count) : "Apply";
                    }
                    catch (Exception)
                    {
                    }
                }
                int live = Staging.LiveOrder().Count;
                int shown = Staging.Visible(Filters, Picks, FilterSheet()).Count;
                int total = Staging.Order.Count;
                string text = string.Format(Inv, "{0} revision{1}", live, live == 1 ? "" : "s");
                if (shown != total)
                    text += string.Format(Inv, ", {0} showing", shown);
                text += ". " + (count != 0
                    ? string.Format(Inv, "{0} change{1} staged - nothing is written until Apply.", count, count == 1 ? "" : "s")
                    : "Nothing staged.");
                PsUi.SetText(Status, text);
            }

            /// <summary>The Python _say (Core: Say is the public one).</summary>
            internal void SayCore(string text)
            {
                PsUi.SetText(Status, text);
            }

            /// <summary>For whoever is driving the window - the external event job.</summary>
            public void Say(string text)
            {
                SayCore(text);
            }

            /// <summary>
            /// Run something on the window's thread. An external event's Execute runs on Revit's main
            /// thread, which is this window's thread too, so this is usually a straight call - but not
            /// a safe assumption to build on.
            /// </summary>
            public void OnUi(Action call)
            {
                try
                {
                    Window.Dispatcher.Invoke(call);
                    return;
                }
                catch (Exception)
                {
                }
                try
                {
                    call();
                }
                catch (Exception)
                {
                }
            }

            // ==================================================================
            // editing
            // ==================================================================

            internal void CellChanged(object sender, DataColumnChangeEventArgs args)
            {
                if (Suspend)
                    return;
                string field;
                DataRow row;
                try
                {
                    field = args.Column.ColumnName;
                    row = args.Row;
                }
                catch (Exception)
                {
                    return;
                }
                string key = Str(row["key"]);
                if (field.StartsWith("x_", StringComparison.Ordinal) && !field.StartsWith("c_", StringComparison.Ordinal))
                {
                    CustomChanged(row, key, field.Substring(2));
                    return;
                }
                if (!PsRevisions.Fields.Contains(field))
                    return;
                object value = row[field];
                if (value is DBNull)
                    value = null;
                if (field == "issued")
                    value = value is bool b ? b : value != null;
                var (ok, message) = Staging.SetField(key, field, value);
                if (!ok)
                {
                    Suspend = true;
                    try
                    {
                        row[field] = Db(Staging.Entries[key].Fields.TryGetValue(field, out var stored) ? stored : null);
                    }
                    finally
                    {
                        Suspend = false;
                    }
                    SayCore(message);
                    return;
                }
                var others = Others(key, field);
                if (others.Count > 0)
                    Spread(key, field, others);
                Refresh(layout: false);
            }

            internal void CustomChanged(DataRow row, string key, string columnId)
            {
                var column = Staging.Column(columnId);
                if (column == null)
                    return;
                object value = row["x_" + columnId];
                if (value is DBNull)
                    value = null;
                if (column.Kind == "yesno")
                    value = value is bool b ? b : value != null;
                var (ok, message) = Staging.SetCustom(key, columnId, value);
                if (!ok)
                {
                    string stored = PsRevisions.Staging.CustomValue(Staging.Entries[key], column);
                    Suspend = true;
                    try
                    {
                        row["x_" + columnId] = column.Kind == "yesno" ? (object)(stored == "1") : stored;
                    }
                    finally
                    {
                        Suspend = false;
                    }
                    SayCore(message);
                    return;
                }
                var others = Others(key, "x_" + columnId);
                if (others.Count > 0)
                    Spread(key, "x_" + columnId, others);
                Refresh(layout: false);
            }

            /// <summary>Refuse an edit Revit would refuse, before the editor opens.</summary>
            internal void BeginningEdit(object sender, DataGridBeginningEditEventArgs args)
            {
                // Following the selection holds off until the edit is committed: a jump mid-edit
                // would take the row out from under what is typed.
                Editing = true;
                string field, key;
                try
                {
                    field = args.Column.SortMemberPath ?? "";
                    key = Str(((DataRowView)args.Row.Item).Row["key"]);
                }
                catch (Exception)
                {
                    return;
                }
                if (!Staging.Entries.TryGetValue(key, out var entry) || entry == null)
                    return;
                string refusal = "";
                if (!entry.Live)
                {
                    refusal = "That revision is staged to go. Press Delete again with it selected to restore it.";
                }
                else if (field != "issued" && !field.StartsWith("x_", StringComparison.Ordinal) && Staging.Locked(key))
                {
                    refusal = string.Format("Revision {0} is issued, so Revit keeps it as it is. Untick Issued to edit it.",
                                            Seq(Staging.StagedSequence(key)));
                }
                if (refusal.Length > 0)
                {
                    try
                    {
                        args.Cancel = true;
                    }
                    catch (Exception)
                    {
                    }
                    SayCore(refusal);
                }
            }

            /// <summary>One click edits, as in Revit - unless Ctrl or Shift is down, which means the
            /// click is picking rows to move.</summary>
            internal void CurrentCell(object sender, EventArgs args)
            {
                if (PsUi.CtrlDown() || PsUi.ShiftDown())
                    return;
                try
                {
                    var column = GridControl.CurrentColumn;
                    if (column == null || column.IsReadOnly)
                        return;
                    GridControl.BeginEdit();
                }
                catch (Exception)
                {
                }
            }

            internal void Commit()
            {
                Editing = false;
                if (GridControl == null)
                    return;
                for (int step = 0; step < 2; step++)
                {
                    try
                    {
                        GridControl.CommitEdit();
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            internal List<string> Selected()
            {
                var keys = new List<string>();
                if (GridControl == null)
                    return keys;
                try
                {
                    foreach (var item in GridControl.SelectedItems)
                        keys.Add(Str(((DataRowView)item).Row["key"]));
                }
                catch (Exception)
                {
                }
                return Staging.Order.Where(key => keys.Contains(key)).ToList();
            }

            internal void Select(IEnumerable<string> keys, bool scroll = false)
            {
                if (GridControl == null)
                    return;
                var wanted = new HashSet<string>(keys, StringComparer.Ordinal);
                object found = null;
                try
                {
                    GridControl.SelectedItems.Clear();
                    foreach (var item in GridControl.Items)
                    {
                        if (wanted.Contains(Str(((DataRowView)item).Row["key"])))
                        {
                            GridControl.SelectedItems.Add(item);
                            if (found == null)
                                found = item;
                        }
                    }
                }
                catch (Exception)
                {
                }
                if (scroll && found != null)
                {
                    try
                    {
                        GridControl.ScrollIntoView(found);
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            internal void SelectionChanged(object sender, SelectionChangedEventArgs args)
            {
                var keys = Selected();
                bool restoring = keys.Count > 0 && keys.All(key => !Staging.Entries[key].Live);
                PsUi.SetText(DeleteText, restoring ? "Restore" : "Delete");
            }

            // ==================================================================
            // the side panel
            // ==================================================================

            /// <summary>Ask for everything about the new revision - where it goes first - then stage
            /// it there, green, and bring it into the middle of the grid. Not selected: a selected row
            /// is drawn blue, and the point is to see it is green and waiting for Apply.</summary>
            internal void Add(object sender, RoutedEventArgs args)
            {
                Commit();
                PsRevAddWin.Answer answer;
                try
                {
                    answer = PsRevAddWin.Ask(Staging, ThemeName, Window);
                }
                catch (Exception err)
                {
                    SayCore(string.Format("The Add revision window would not open: {0}", err.Message));
                    return;
                }
                if (answer == null)
                {
                    SayCore("Add revision cancelled.");
                    return;
                }
                string key = Staging.Add(answer.Position, answer.Fields, answer.Custom);
                Refill();
                try
                {
                    GridControl.SelectedItems.Clear();
                }
                catch (Exception)
                {
                }
                CentreOn(key);
                SayCore(string.Format("Revision added at sequence {0}, in green - it is created on Apply.",
                                      Seq(Staging.StagedSequence(key))));
            }

            internal Style FreshRowStyleCore()
            {
                var style = (Style)XamlReader.Parse(string.Format(FreshRowStyle, Presentation));
                try
                {
                    if (GridControl.TryFindResource("GridRow") is Style basis)
                        style.BasedOn = basis;
                }
                catch (Exception)
                {
                }
                return style;
            }

            /// <summary>The grid's own ScrollViewer, found by walking its visuals.</summary>
            internal ScrollViewer Scroller()
            {
                var pending = new List<DependencyObject> { GridControl };
                for (int step = 0; step < 400; step++)
                {
                    if (pending.Count == 0)
                        return null;
                    var node = pending[0];
                    pending.RemoveAt(0);
                    if (node is ScrollViewer viewer)
                        return viewer;
                    try
                    {
                        int count = VisualTreeHelper.GetChildrenCount(node);
                        for (int index = 0; index < count; index++)
                            pending.Add(VisualTreeHelper.GetChild(node, index));
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
                return null;
            }

            /// <summary>Scroll the row into the middle of the grid, not to an edge. After layout, so
            /// the viewport measured is the real one.</summary>
            internal void CentreOn(string key)
            {
                void Centre()
                {
                    int index = 0;
                    object found = null;
                    try
                    {
                        int at = 0;
                        foreach (var item in GridControl.Items)
                        {
                            index = at;
                            if (Str(((DataRowView)item).Row["key"]) == key)
                            {
                                found = item;
                                break;
                            }
                            at++;
                        }
                    }
                    catch (Exception)
                    {
                        return;
                    }
                    if (found == null)
                        return;
                    try
                    {
                        GridControl.ScrollIntoView(found);
                        GridControl.UpdateLayout();
                    }
                    catch (Exception)
                    {
                    }
                    var viewer = Scroller();
                    if (viewer == null)
                        return;
                    try
                    {
                        // The grid scrolls by row, so the offset is in rows.
                        viewer.ScrollToVerticalOffset(Math.Max(0.0, index - viewer.ViewportHeight / 2.0 + 0.5));
                    }
                    catch (Exception)
                    {
                    }
                }

                try
                {
                    Window.Dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(Centre));
                }
                catch (Exception)
                {
                    Centre();
                }
            }

            internal void Delete(object sender, RoutedEventArgs args)
            {
                Commit();
                var keys = Selected();
                if (keys.Count == 0)
                {
                    SayCore("Select the revisions to delete first.");
                    return;
                }
                bool restoring = keys.All(key => !Staging.Entries[key].Live);
                if (!restoring)
                {
                    var used = Staging.InUse(keys);
                    if (used.Count > 0 && !ConfirmDelete(used))
                    {
                        SayCore("Nothing deleted.");
                        return;
                    }
                }
                var (ok, message) = Staging.Delete(keys);
                Refill(keys.Where(key => Staging.Entries.ContainsKey(key)).ToList());
                SayCore(message);
            }

            internal bool ConfirmDelete(List<(int? Sequence, string Description, int Sheets, int Clouds, int Unplaced)> used)
            {
                var lines = new List<string>();
                foreach (var (sequence, description, sheets, clouds, unplaced) in used)
                {
                    lines.Add(string.Format(Inv, "Revision {0}{1}: on {2} sheet{3}, {4} cloud{5}{6}",
                        Seq(sequence), !string.IsNullOrEmpty(description) ? " - " + description : "",
                        sheets, sheets == 1 ? "" : "s",
                        clouds, clouds == 1 ? "" : "s",
                        unplaced != 0
                            ? string.Format(Inv, " ({0} in views on no sheet - right-click > Find clouds on views)", unplaced)
                            : ""));
                }
                string answer = new PsUi.Prompt(
                    title: "Revision Manager",
                    headline: string.Format(Inv, "{0} of these revision{1} in use.",
                                            used.Count, used.Count == 1 ? " is" : "s are"),
                    message: "Are you sure? Deleting a revision takes it off every sheet that carries it, and its revision clouds go with it. Nothing happens until Apply, and it can be restored until then.",
                    detail: string.Join("\n", lines),
                    primary: "Delete", secondary: "Keep",
                    themeName: ThemeName, owner: Window).Show();
                return answer == "primary";
            }

            internal void Move(int step)
            {
                Commit();
                var keys = Selected();
                if (keys.Count == 0)
                {
                    SayCore("Select the revisions to move. Ctrl or Shift click to select several.");
                    return;
                }
                if (Staging.Move(keys, step))
                {
                    Refill(keys);
                    SayCore(string.Format(Inv, "{0} revision{1} moved {2}.",
                                          keys.Count, keys.Count == 1 ? "" : "s", step < 0 ? "up" : "down"));
                }
                else
                {
                    SayCore(string.Format("Already at the {0}.", step < 0 ? "top" : "bottom"));
                }
            }

            internal void Merge(int step)
            {
                Commit();
                var keys = Selected();
                if (keys.Count != 1)
                {
                    SayCore("Select one revision to merge.");
                    return;
                }
                var (ok, message) = Staging.Merge(keys[0], step);
                if (ok)
                    Refill(keys);
                SayCore(message);
            }

            // ------------------------------------------------------------ columns
            /// <summary>The column dialog: null, an answer with Action "remove", or one with Action
            /// "save" and Name, Kind, Choices, Target, Parameter, Group.</summary>
            internal PsRevColWin.ColumnAnswer ColumnDialog(PsRevData.Column column = null, string group = "")
            {
                return new PsRevColWin.ColumnDialog(
                    Staging.Columns, column, target => Lookup(target),
                    ThemeName, Window, group).Show();
            }

            internal List<PsRevData.BoundParameter> Parameters()
            {
                try
                {
                    return ParameterReader != null
                        ? ParameterReader().ToList()
                        : new List<PsRevData.BoundParameter>();
                }
                catch (Exception)
                {
                    return new List<PsRevData.BoundParameter>();
                }
            }

            /// <summary>[(name, data)] the column dialog offers for a target.</summary>
            internal List<(string Name, string Data)> Lookup(string target)
            {
                return PsRevData.Usable(Parameters(), target);
            }

            /// <summary>The settings: the model's own columns and their mapping.</summary>
            internal void OpenSettings(object sender, RoutedEventArgs args)
            {
                Commit();
                PsRevSetWin.SettingsAnswer answer = new PsRevSetWin.SettingsDialog(
                    Staging.Columns, () => Parameters(), ThemeName, Window).Show();
                if (answer == null)
                    return;
                var problems = new List<string>();
                foreach (var (columnId, name, target, parameter) in answer.Columns)
                {
                    var column = Staging.Column(columnId);
                    if (column == null)
                        continue;
                    var (ok, message) = Staging.UpdateColumn(columnId, name, column.Choices, target, parameter);
                    if (!ok)
                        problems.Add(message);
                }
                Rebuild(Selected());
                if (problems.Count > 0)
                    SayCore(string.Join(" ", problems));
                else if (Staging.ColumnsChanged())
                    SayCore("Column settings staged - written on Apply.");
                if (answer.Action == "project_parameters")
                    ToProjectParameters();
            }

            /// <summary>Close, and have Revit open Project Parameters. Revit runs a posted command
            /// only once the tool hands control back, so the manager closes first. Staged changes
            /// are applied on the way out, or left - the user says which.</summary>
            internal void ToProjectParameters()
            {
                PsRevisions.Plan plan = null;
                if (Staging.Dirty())
                {
                    int count = Staging.ChangeCount();
                    string answer = new PsUi.Prompt(
                        title: "Revision Manager",
                        headline: "Project Parameters opens when this window closes.",
                        message: string.Format(Inv,
                            "{0} change{1} staged here. Apply them on the way out, or leave them? Close this message to stay in the manager.",
                            count, count == 1 ? " is" : "s are"),
                        primary: "Apply, then open", secondary: "Leave them, open",
                        themeName: ThemeName, owner: Window).Show();
                    if (answer == "primary")
                    {
                        plan = Staging.Plan();
                        if (PsRevisions.PlanIsEmpty(plan))
                            plan = null;
                    }
                    else if (answer != "secondary")
                    {
                        return;
                    }
                }
                PostCommand = "ProjectParameters";
                Result = plan;
                Close(plan != null);
            }

            internal void AddColumn(object sender, RoutedEventArgs args, string group = "")
            {
                Commit();
                var answer = ColumnDialog(null, group);
                if (answer == null || answer.Action != "save")
                    return;
                string name = answer.Name;
                var (ok, found) = Staging.AddColumn(
                    name, answer.Kind, answer.Choices,
                    answer.Target, answer.Parameter, answer.Group ?? "");
                if (!ok)
                {
                    SayCore(found);
                    return;
                }
                Rebuild(Selected());
                SayCore(string.Format("Column \"{0}\" added. It is saved to the model on Apply.", name));
            }

            internal RoutedEventHandler MakeEditColumn(string columnId)
            {
                return (sender, args) => EditColumn(columnId);
            }

            internal void EditColumn(string columnId)
            {
                Commit();
                var column = Staging.Column(columnId);
                if (column == null)
                    return;
                var answer = ColumnDialog(column);
                if (answer == null)
                    return;
                if (answer.Action == "remove")
                {
                    int filled = Staging.Entries.Values.Count(entry =>
                    {
                        string value = PsRevisions.Staging.CustomValue(entry, column);
                        return value != "" && value != "0";
                    });
                    if (filled != 0 && new PsUi.Prompt(
                            title: "Revision Manager",
                            headline: string.Format("Remove \"{0}\"?", column.Name),
                            message: string.Format(Inv,
                                "{0} revision{1} {2} a value in it. The column and its values leave the model on Apply; the parameters it was pushed into keep what they hold.",
                                filled, filled == 1 ? "" : "s", filled == 1 ? "has" : "have"),
                            primary: "Remove", secondary: "Keep",
                            themeName: ThemeName,
                            owner: Window).Show() != "primary")
                        return;
                    Staging.RemoveColumn(columnId);
                    Rebuild(Selected());
                    SayCore(string.Format("Column \"{0}\" removed on Apply.", column.Name));
                    return;
                }
                string name = answer.Name;
                var (ok, message) = Staging.UpdateColumn(
                    columnId, name, answer.Choices, answer.Target,
                    answer.Parameter, answer.Group);
                if (!ok)
                {
                    SayCore(message);
                    return;
                }
                Rebuild(Selected());
                SayCore(string.Format("Column \"{0}\" changed.", name));
            }

            /// <summary>Stage a push of every mapped column, with nothing else changed.</summary>
            internal void Push(object sender, RoutedEventArgs args)
            {
                Commit();
                var pushed = Staging.Columns.Where(column => column.Pushed).ToList();
                if (pushed.Count == 0)
                {
                    SayCore("No column is mapped to a parameter yet - use the pencil on a column's heading to map one.");
                    return;
                }
                Staging.PushRequested = true;
                Refresh();
                SayCore(string.Format(Inv, "{0} column{1} will be pushed on Apply: {2}.",
                    pushed.Count, pushed.Count == 1 ? "" : "s",
                    string.Join(", ", pushed.Select(column => string.Format("{0} -> \"{1}\"", column.Name, column.Parameter)))));
            }

            internal RoutedEventHandler MakeNumbering(string mode)
            {
                return (sender, args) =>
                {
                    if (Suspend)
                        return;
                    Staging.SetSetting("numbering", mode);
                    Refresh();
                };
            }

            internal void ArcChanged(object sender, TextChangedEventArgs args)
            {
                if (Suspend)
                    return;
                string text = (ArcBox.Text ?? "").Trim();
                if (!Staging.SetSetting("arc_mm", text))
                {
                    SayCore("Arc length has to be a number above 0, in mm.");
                    return;
                }
                Refresh();
            }

            /// <summary>Clear filters: every search box empty and every value list back to
            /// everything ticked.</summary>
            internal void ClearSearches(object sender, RoutedEventArgs args)
            {
                foreach (var box in SearchBoxes)
                {
                    try
                    {
                        box.Text = "";
                    }
                    catch (Exception)
                    {
                    }
                }
                foreach (var field in Picks.Keys.ToList())
                {
                    Picks.Remove(field);
                    PaintFilterButton(field);
                }
                Refresh();
            }

            /// <summary>Ctrl+Up and Ctrl+Down move the selection - not while a filter list is open,
            /// whose keys come through the grid on their way.</summary>
            internal void KeyDown(object sender, KeyEventArgs args)
            {
                if (FilterOpen)
                    return;
                var key = args.Key;
                if (!PsUi.CtrlDown() || (key != Key.Up && key != Key.Down))
                    return;
                Move(key == Key.Up ? -1 : 1);
                args.Handled = true;
            }

            // ==================================================================
            // theme, apply, cancel
            // ==================================================================

            internal void SayTheme()
            {
                PsUi.SetContent(ThemeChip, ThemeName == "light" ? "Light" : "Dark");
            }

            internal void ToggleTheme(object sender, RoutedEventArgs args)
            {
                ThemeName = ThemeName == "dark" ? "light" : "dark";
                try
                {
                    PsTheme.Apply(Window, ThemeName);
                }
                catch (Exception)
                {
                }
                SayTheme();
                // The series chips carry palette colours of their own.
                Commit();
                Colours = null;
                Refill(Selected());
            }

            // ------------------------------------------------- the right-click menu
            /// <summary>A right-click on a row not selected selects it first, so the menu acts on
            /// what is under the pointer.</summary>
            internal void RightPress(object sender, MouseButtonEventArgs args)
            {
                try
                {
                    var row = Ancestor<DataGridRow>(args.OriginalSource);
                    if (row == null || row.IsSelected)
                        return;
                    GridControl.SelectedItems.Clear();
                    row.IsSelected = true;
                }
                catch (Exception)
                {
                }
            }

            internal void RightRelease(object sender, MouseButtonEventArgs args)
            {
                try
                {
                    if (Ancestor<DataGridRow>(args.OriginalSource) == null)
                        return;
                    var menu = new ContextMenu();
                    menu.SetResourceReference(FrameworkElement.StyleProperty, "ThemedContextMenu");
                    foreach (var entry in MenuEntries())
                    {
                        if (entry == null)
                        {
                            menu.Items.Add(new Separator());
                            continue;
                        }
                        var (text, action, enabled) = entry.Value;
                        var item = new MenuItem();
                        item.SetResourceReference(FrameworkElement.StyleProperty, "ThemedMenuItem");
                        item.Header = text;
                        item.IsEnabled = enabled;
                        item.Click += MakeMenuClick(action);
                        menu.Items.Add(item);
                    }
                    menu.PlacementTarget = GridControl;
                    menu.IsOpen = true;
                    args.Handled = true;
                }
                catch (Exception)
                {
                }
            }

            /// <summary>The Python dispatches by method name (getattr); the two names it uses.</summary>
            internal RoutedEventHandler MakeMenuClick(string action)
            {
                return (sender, args) =>
                {
                    if (action == "find_clouds")
                        FindClouds();
                    else if (action == "delete_selected")
                        DeleteSelected();
                };
            }

            /// <summary>[(text, method name, enabled)], or null for a separator.</summary>
            public List<(string Text, string Action, bool Enabled)?> MenuEntries()
            {
                var keys = Selected();
                var entries = keys.Where(key => Staging.Entries.ContainsKey(key))
                                  .Select(key => Staging.Entries[key]).ToList();
                var (views, _) = ViewsReport(entries);
                int off = entries.Sum(entry => entry.Unplaced);
                return new List<(string Text, string Action, bool Enabled)?>
                {
                    (string.Format(Inv, "Find clouds on views ({0} view{1}{2})...",
                                   views.Count, views.Count == 1 ? "" : "s",
                                   off != 0 ? string.Format(Inv, ", {0} cloud{1} off sheets", off, off == 1 ? "" : "s") : ""),
                     "find_clouds", views.Count > 0),
                    null,
                    (entries.Count == 0 || entries.Any(one => one.Live) ? "Delete" : "Restore",
                     "delete_selected", entries.Count > 0),
                };
            }

            public void DeleteSelected()
            {
                Delete(null, null);
            }

            /// <summary>Open every view holding the selected revisions' clouds, with the clouds
            /// isolated in each.</summary>
            public void FindClouds()
            {
                Commit();
                var keys = Selected().Where(key => Staging.Entries.ContainsKey(key)).ToList();
                var entries = keys.Select(key => Staging.Entries[key]).ToList();
                var (views, lines) = ViewsReport(entries);
                if (views.Count == 0)
                {
                    SayCore("No clouds of those revisions in any view.");
                    return;
                }
                if (views.Count > OpenLimit && new PsUi.Prompt(
                        title: "Find clouds on views",
                        headline: string.Format(Inv, "Open {0} views?", views.Count),
                        message: "Each opens with the revision clouds isolated in it. That is a lot of views to have open at once.",
                        detail: string.Join("\n", lines),
                        primary: "Open them", secondary: "Cancel",
                        themeName: ThemeName,
                        owner: Window).Show() != "primary")
                    return;
                if (OnFind != null)
                {
                    SayCore(string.Format(Inv, "Opening {0} view{1}...", views.Count, views.Count == 1 ? "" : "s"));
                    OnFind(views);
                    return;
                }
                // Opened from the register: Revit is only reachable once this window has closed, so
                // the views open then.
                PsRevisions.Plan plan = null;
                if (Staging.Dirty())
                {
                    int count = Staging.ChangeCount();
                    string answer = new PsUi.Prompt(
                        title: "Find clouds on views",
                        headline: "The views open when this window closes.",
                        message: string.Format(Inv,
                            "{0} change{1} staged here. Apply them on the way out, or leave them? Close this message to stay.",
                            count, count == 1 ? " is" : "s are"),
                        primary: "Apply, then open", secondary: "Leave them, open",
                        themeName: ThemeName, owner: Window).Show();
                    if (answer == "primary")
                    {
                        plan = Staging.Plan();
                        if (PsRevisions.PlanIsEmpty(plan))
                            plan = null;
                    }
                    else if (answer != "secondary")
                    {
                        return;
                    }
                }
                FindRequest = views;
                Result = plan;
                Close(plan != null);
            }

            internal void Apply(object sender, RoutedEventArgs args)
            {
                Commit();
                var plan = Staging.Plan();
                if (PsRevisions.PlanIsEmpty(plan))
                {
                    SayCore("Nothing to apply.");
                    return;
                }
                Result = plan;
                if (OnApply != null)
                {
                    // Modeless: the window stays, the plan goes out through an external event, and
                    // the window is refreshed when it returns.
                    SayCore("Applying...");
                    OnApply(plan);
                    return;
                }
                Close(true);
            }

            internal void Cancel()
            {
                Commit();
                if (Staging.Dirty())
                {
                    int count = Staging.ChangeCount();
                    string answer = new PsUi.Prompt(
                        title: "Revision Manager",
                        headline: string.Format(Inv, "Discard {0} staged change{1}?", count, count == 1 ? "" : "s"),
                        message: "None of them have been written to the model.",
                        primary: "Discard", secondary: "Keep editing",
                        themeName: ThemeName, owner: Window).Show();
                    if (answer != "primary")
                        return;
                }
                Result = null;
                Close(false);
            }

            internal void Close(bool ok)
            {
                if (!Modeless)
                {
                    // Only a window shown with ShowDialog has a DialogResult; setting it on a
                    // modeless one throws.
                    try
                    {
                        Window.DialogResult = ok;
                    }
                    catch (Exception)
                    {
                    }
                }
                StopWatching();
                try
                {
                    Window.Close();
                }
                catch (Exception)
                {
                }
            }

            /// <summary>Shut the window from outside - the job that applied the last change with
            /// "reopen after Apply" turned off.</summary>
            public void CloseNow()
            {
                Close(true);
            }

            /// <summary>Take a freshly read staging, keeping the window as it is: the theme, the
            /// column order, the widths and the value filters all belong to the window, not to the
            /// model.</summary>
            public void Reload(PsRevisions.Staging staging, string status = "")
            {
                Staging = staging;
                Colours = null;
                Token = null;
                Rebuild();
                if (!string.IsNullOrEmpty(status))
                    SayCore(status);
            }

            /// <summary>Modal: returns the plan to write, or null. Also read PostCommand and
            /// FindRequest afterwards.</summary>
            public PsRevisions.Plan Show()
            {
                try
                {
                    Window.ShowDialog();
                }
                catch (Exception)
                {
                }
                return Result;
            }

            public RevisionManager ShowModeless()
            {
                Window.Show();
                return this;
            }
        }
    }
}
