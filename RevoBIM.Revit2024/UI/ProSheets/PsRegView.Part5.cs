using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;
using RevoBIM.Tools.ProSheets;
using RvtDocument = Autodesk.Revit.DB.Document;
using RvtViewSheet = Autodesk.Revit.DB.ViewSheet;
using UIApplication = Autodesk.Revit.UI.UIApplication;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsRegView
    {
        /// <summary>One staged edit, written - the Python's (edit, picks, (done,
        /// skipped, errors), report) tuple. Done is the count; DonePairs the
        /// (sheet, revision element key) picks moved by a change or remove.
        /// A Skipped entry with a null Revision is an assign's (sheet, why).</summary>
        public class EditResult
        {
            public PsRegister.PendingEdit Edit;
            public Dictionary<string, HashSet<string>> Picks =
                new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
            public int Done;
            public HashSet<(string Sheet, string Revision)> DonePairs = new HashSet<(string Sheet, string Revision)>();
            public List<(string Sheet, string Revision, string Why)> Skipped =
                new List<(string Sheet, string Revision, string Why)>();
            public List<string> Errors = new List<string>();
            public PsRevisions.SwapReport Report = new PsRevisions.SwapReport();
        }

        public partial class RegisterView
        {
            // ==================================================================
            // revision changes waiting for Apply revisions
            // ==================================================================

            /// <summary>{sheet: columns carrying a revision} as the model has it.</summary>
            internal Dictionary<string, HashSet<string>> Present()
            {
                var found = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
                foreach (var pair in RowsByKey)
                {
                    found[pair.Key] = new HashSet<string>(
                        pair.Value.Cells.Where(cell => (cell.Value ?? "").Trim().Length > 0).Select(cell => cell.Key),
                        StringComparer.Ordinal);
                }
                return found;
            }

            /// <summary>Show the staged edits in the grid: s_ flags for the cell style
            /// (green +, red struck through) and the + text in a cell gaining a
            /// revision. Only the cells that differ from last time are written.</summary>
            internal void PaintPending()
            {
                var flags = Pending.Count > 0
                    ? Pending.Flags(Present())
                    : new Dictionary<(string Sheet, string Column), string>();
                var before = PendingFlags;
                Suspend = true;
                try
                {
                    var cells = new HashSet<(string Sheet, string Column)>(before.Keys);
                    cells.UnionWith(flags.Keys);
                    foreach (var cell in cells)
                    {
                        before.TryGetValue(cell, out var was);
                        flags.TryGetValue(cell, out var now);
                        if (was == now)
                            continue;
                        var (sheet, column) = cell;
                        if (!Entries.TryGetValue(sheet, out var entry) || entry == null)
                            continue;
                        string flag = now ?? "";
                        RowsByKey.TryGetValue(sheet, out var row);
                        string baseText = "";
                        if (row != null)
                            row.Cells.TryGetValue(column, out baseText);
                        try
                        {
                            entry[PsRegView.PendingPrefix + column] = flag;
                            entry[column] = flag == PsRegister.PendingAdd ? "+" : (baseText ?? "");
                        }
                        catch (Exception)
                        {
                            continue;
                        }
                    }
                }
                finally
                {
                    Suspend = false;
                }
                PendingFlags = flags;
                PaintPendingButtons();
                PaintIssueBlock();
                PaintIssueRows();
            }

            internal void PaintPendingButtons()
            {
                int count = Pending.Count;
                int cells = Pending.Edits.Sum(edit => PsRegister.PendingCells(edit));
                foreach (var (button, lit) in new[] { (UndoButton, count > 0), (RedoButton, Pending.Undone.Count > 0) })
                {
                    if (button != null)
                    {
                        try
                        {
                            button.IsEnabled = lit;
                            button.Opacity = lit ? 1.0 : 0.4;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
                // Bottom right: Apply goes green and Discard red once anything is
                // staged (PrimaryButton / DangerButton); grey until then.
                foreach (var button in new[] { ApplyRevsButton, DiscardButton })
                {
                    if (button != null)
                    {
                        try
                        {
                            button.IsEnabled = count > 0;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
                PsUi.SetText(ApplyRevsText, count > 0 ? string.Format("Apply revisions ({0})", cells) : "Apply revisions");
            }

            /// <summary>One line for an edit, for the status line and Apply's list.</summary>
            internal string Describe(PsRegister.PendingEdit edit)
            {
                int cells = PsRegister.PendingCells(edit);
                string plural = Plural(cells);
                if (edit.Kind == PsRegister.Meta)
                    return DescribeMeta(edit);
                if (edit.Kind == "assign")
                    return string.Format("{0} assigned to {1} sheet{2}", Labels(new[] { edit.Target }), cells, plural);
                if (edit.Kind == "change")
                    return string.Format("{0} cell{1} changed to {2}", cells, plural, Labels(new[] { edit.Target }));
                return string.Format("{0} cell{1} removed", cells, plural);
            }

            internal void Stage(PsRegister.PendingEdit edit)
            {
                Pending.Push(edit);
                string target = edit.Target;
                if (!string.IsNullOrEmpty(target) && !UsedColumns.Any(one => one.Key == target))
                {
                    // The column has to be on screen for its + to be seen.
                    SetShowAllRevisions(true, quiet: true);
                }
                PaintPending();
                Host.Say(string.Format("Staged: {0}. Nothing is written until Apply " +
                                       "revisions - Ctrl+Z undoes it.", Describe(edit)));
            }

            public void Undo()
            {
                var edit = Pending.Undo();
                if (edit == null)
                {
                    Host.Say("Nothing to undo.");
                    return;
                }
                SetPickedCells(new HashSet<(string Sheet, string Column)>());
                PaintPending();
                Host.Say(string.Format("Undone: {0}. Ctrl+Y does it again.", Describe(edit)));
            }

            public void Redo()
            {
                var edit = Pending.Redo();
                if (edit == null)
                {
                    Host.Say("Nothing to redo.");
                    return;
                }
                SetPickedCells(new HashSet<(string Sheet, string Column)>());
                PaintPending();
                Host.Say(string.Format("Redone: {0}.", Describe(edit)));
            }

            public void DiscardPending()
            {
                if (Pending.Count == 0)
                    return;
                int count = Pending.Count;
                Pending.Clear();
                SetPickedCells(new HashSet<(string Sheet, string Column)>());
                PaintPending();
                Host.Say(string.Format("{0} staged change{1} thrown away - Revit was never touched.",
                                       count, Plural(count)));
            }

            /// <summary>Ask before closing over staged changes. True to go on.</summary>
            public bool CanClose()
            {
                if (Pending.Count == 0)
                    return true;
                string answer = new PsUi.Prompt(
                    title: "Document Register",
                    headline: string.Format("{0} revision change{1} not applied.",
                                            Pending.Count, Pending.Count == 1 ? " is" : "s are"),
                    message: "Closing now throws them away; the sheets in Revit stay as they are.",
                    detail: string.Join("\n", Pending.Edits.Select(edit => Describe(edit))),
                    primary: "Discard and close", secondary: "Keep it open",
                    themeName: Host.ThemeName, owner: Window).Show();
                return answer == "primary";
            }

            /// <summary>Write every staged edit, in the order made, in one job.</summary>
            public void ApplyRevisions()
            {
                if (Pending.Count == 0)
                    return;
                var edits = new List<PsRegister.PendingEdit>(Pending.Edits);
                var removes = edits.Where(edit => edit.Kind == "remove").ToList();
                if (removes.Count > 0)
                {
                    string answer = new PsUi.Prompt(
                        title: "Apply revisions",
                        headline: string.Format("Apply {0} revision change{1}?", edits.Count, Plural(edits.Count)),
                        message: "Deletes the rev clouds from all associated views " +
                                 "on the sheet, for every revision staged to be " +
                                 "removed.\n\nA revision added to the sheet by hand " +
                                 "is taken off it too. A cloud that also shows on a " +
                                 "sheet not staged is asked about afterwards. " +
                                 "Issued revisions are left: Revit locks them.",
                        detail: string.Join("\n", edits.Select(edit => Describe(edit))),
                        primary: "Apply", secondary: "Cancel",
                        themeName: Host.ThemeName, owner: Window).Show();
                    if (answer != "primary")
                    {
                        Host.Say("Apply revisions cancelled - still staged.");
                        return;
                    }
                }
                var touched = new HashSet<string>(StringComparer.Ordinal);
                foreach (var edit in edits)
                {
                    touched.UnionWith(edit.Sheets ?? new List<string>());
                    touched.UnionWith((edit.Picks ?? new Dictionary<string, List<string>>()).Keys);
                }
                var sheets = SheetsFor(touched);
                var doc = Host.Doc;
                // Issue data edits are written together, in the order made, in a
                // transaction of their own: they are one store, not one per sheet.
                var meta = edits.Where(edit => edit.Kind == PsRegister.Meta).ToList();
                var others = edits.Where(edit => edit.Kind != PsRegister.Meta).ToList();
                var (changes, keysByUid) = IssueChanges(meta);

                // On Revit's thread: each edit in turn, each its own
                // transaction, so one Revit refuses does not undo the rest.
                void Job(UIApplication uiapp)
                {
                    var results = others.Select(edit => RunEdit(doc, edit, sheets, false)).ToList();
                    if (meta.Count > 0)
                        results.Add(RunMeta(doc, changes, keysByUid));
                    Host.OnUi(() => Applied(results, false));
                }

                if (Host.Queue(Job))
                {
                    Host.Say(string.Format("Writing {0} revision change{1}...", edits.Count, Plural(edits.Count)));
                }
            }

            /// <summary>{sheet key: its ViewSheet} for the keys the register holds a sheet for.</summary>
            internal Dictionary<string, RvtViewSheet> SheetsFor(IEnumerable<string> keys)
            {
                var sheets = new Dictionary<string, RvtViewSheet>(StringComparer.Ordinal);
                foreach (var key in keys)
                {
                    if (Elements.TryGetValue(key, out var element) && element is RvtViewSheet sheet)
                        sheets[key] = sheet;
                }
                return sheets;
            }

            /// <summary>The staged issue data, written. In Applied's shape.</summary>
            internal static EditResult RunMeta(RvtDocument doc, List<(string Uid, string ColumnId, object Value)> changes,
                                               Dictionary<string, long> keysByUid)
            {
                int done;
                List<string> problems;
                try
                {
                    (done, problems) = PsRevData.WriteChanges(doc, changes, keysByUid);
                }
                catch (Exception err)
                {
                    done = 0;
                    problems = new List<string> { string.Format("The issue data was not written: {0}", err.Message) };
                }
                return new EditResult
                {
                    Edit = new PsRegister.PendingEdit { Kind = PsRegister.Meta },
                    Done = done,
                    Errors = new List<string>(problems ?? new List<string>()),
                };
            }

            /// <summary>One staged edit, written. Returns (edit, picks in element keys,
            /// result, report).</summary>
            internal static EditResult RunEdit(RvtDocument doc, PsRegister.PendingEdit edit,
                                               Dictionary<string, RvtViewSheet> sheets, bool includeShared,
                                               Dictionary<string, HashSet<string>> picks = null)
            {
                var report = new PsRevisions.SwapReport();
                string target = PsRegister.ElementOf(edit.Target);
                if (picks == null)
                {
                    picks = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
                    foreach (var pair in edit.Picks ?? new Dictionary<string, List<string>>())
                    {
                        picks[pair.Key] = new HashSet<string>(pair.Value.Select(column => PsRegister.ElementOf(column)),
                                                              StringComparer.Ordinal);
                    }
                }
                var result = new EditResult { Edit = edit, Picks = picks, Report = report };
                try
                {
                    if (edit.Kind == "assign")
                    {
                        var (assigned, skipped, errors) = PsRevisions.AssignToSheets(
                            doc, new List<string>(edit.Sheets ?? new List<string>()), target, sheets);
                        result.Done = assigned.Count;
                        result.Skipped = skipped.Select(one => (one.Sheet, (string)null, one.Why)).ToList();
                        result.Errors = new List<string>(errors);
                    }
                    else if (edit.Kind == "change")
                    {
                        var (changed, skipped, errors) = PsRevisions.SwapOnSheets(doc, picks, target, sheets,
                                                                                  includeShared, report);
                        result.Done = changed.Count;
                        result.DonePairs = new HashSet<(string Sheet, string Revision)>(changed);
                        result.Skipped = new List<(string Sheet, string Revision, string Why)>(skipped);
                        result.Errors = new List<string>(errors);
                    }
                    else
                    {
                        var (changed, skipped, errors) = PsRevisions.RemoveOnSheets(doc, picks, sheets,
                                                                                    includeShared, report);
                        result.Done = changed.Count;
                        result.DonePairs = new HashSet<(string Sheet, string Revision)>(changed);
                        result.Skipped = new List<(string Sheet, string Revision, string Why)>(skipped);
                        result.Errors = new List<string>(errors);
                    }
                }
                catch (Exception err)
                {
                    result.Done = 0;
                    result.DonePairs = new HashSet<(string Sheet, string Revision)>();
                    result.Skipped = new List<(string Sheet, string Revision, string Why)>();
                    result.Errors = new List<string> { string.Format("Nothing was changed: {0}", err.Message) };
                }
                return result;
            }

            /// <summary>After Apply revisions: read the model, then ask about clouds
            /// that show on sheets not staged, then list what Revit refused.</summary>
            internal void Applied(List<EditResult> results, bool second)
            {
                Pending.Clear();
                PendingFlags = new Dictionary<(string Sheet, string Column), string>();
                Reload();
                var lines = new List<string>();
                int written = 0;
                var leftovers = new List<(PsRegister.PendingEdit Edit, Dictionary<string, HashSet<string>> Left)>();
                var shared = new List<(string Sheet, string Revision, string Cloud, List<string> Others)>();
                foreach (var result in results)
                {
                    written += result.Done;
                    foreach (var one in result.Skipped)
                    {
                        if (one.Revision == null)
                            lines.Add(string.Format("{0}: {1}", SheetLabel(one.Sheet), one.Why));
                        else
                            lines.Add(string.Format("{0}, {1}: {2}", SheetLabel(one.Sheet), ElementLabel(one.Revision), one.Why));
                    }
                    lines.AddRange(result.Errors);
                    var reportShared = result.Report?.Shared;
                    if (result.Edit.Kind == "assign" || second || reportShared == null || reportShared.Count == 0)
                        continue;
                    shared.AddRange(reportShared);
                    var finished = result.DonePairs;
                    var rest = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
                    foreach (var pair in result.Picks)
                    {
                        var left = new HashSet<string>(pair.Value.Where(old => !finished.Contains((pair.Key, old))),
                                                       StringComparer.Ordinal);
                        if (left.Count > 0)
                            rest[pair.Key] = left;
                    }
                    if (rest.Count > 0)
                        leftovers.Add((result.Edit, rest));
                }
                string summary = string.Format("{0} revision change{1} written.", written, Plural(written));
                if (leftovers.Count > 0)
                {
                    string mode = leftovers.All(pair => pair.Edit.Kind == "remove") ? "remove" : "change";
                    if (AskShared(mode, shared, summary))
                    {
                        Again(leftovers);
                        return;
                    }
                }
                if (lines.Count == 0)
                {
                    Host.Say(summary);
                    return;
                }
                Host.Say(string.Format("{0} {1} left as {2} {3}.", summary, lines.Count,
                                       lines.Count == 1 ? "it" : "they", lines.Count == 1 ? "was" : "were"));
                new PsUi.Prompt(
                    title: "Apply revisions",
                    headline: "Not everything could be written.",
                    message: summary + " The rest are listed below, with why; the " +
                             "register shows the model as it now is.",
                    detail: string.Join("\n", lines), primary: "Close",
                    themeName: Host.ThemeName, owner: Window).Show();
            }

            /// <summary>The second pass: only the cells still to do, shared clouds
            /// included.</summary>
            internal void Again(List<(PsRegister.PendingEdit Edit, Dictionary<string, HashSet<string>> Left)> leftovers)
            {
                var touched = new HashSet<string>(StringComparer.Ordinal);
                foreach (var (_, rest) in leftovers)
                    touched.UnionWith(rest.Keys);
                var sheets = SheetsFor(touched);
                var doc = Host.Doc;

                // On Revit's thread.
                void Job(UIApplication uiapp)
                {
                    var results = leftovers.Select(pair => RunEdit(doc, pair.Edit, sheets, true, pair.Left)).ToList();
                    Host.OnUi(() => Applied(results, true));
                }

                if (Host.Queue(Job))
                    Host.Say("Now the clouds shared with other sheets...");
            }

            /// <summary>Isolating a revision whose sheets are not in the set: switch to
            /// All sheets so they can be found. Returns how many were hidden.</summary>
            internal int RevealIsolated()
            {
                if (ShowMode != "included" || Isolated.Count == 0)
                    return 0;
                var hidden = PsRegister.OutsideSet(RowsByKey.Keys.ToList(), Isolated, Included, Filled);
                if (hidden.Count > 0)
                    SetShow("all");
                return hidden.Count;
            }

            // ==================================================================
            // folding the series away
            // ==================================================================

            /// <summary>The path of every heading on the tab on screen.</summary>
            internal List<string> TabGroups()
            {
                return GroupPaths.Values.ToList();
            }

            public void ToggleGroup(string path)
            {
                var key = (TabLabel, path);
                if (Collapsed.Contains(key))
                    Collapsed.Remove(key);
                else
                    Collapsed.Add(key);
                ApplyFilters();
                PaintCollapseButton();
                Say();
            }

            /// <summary>Whether a heading, or any heading above it, is folded away.</summary>
            internal bool Folded(int? groupId)
            {
                int steps = 0;
                while (groupId != null && GroupPaths.ContainsKey(groupId.Value) && steps < 4)
                {
                    if (Collapsed.Contains((TabLabel, GroupPaths[groupId.Value])))
                        return true;
                    GroupParent.TryGetValue(groupId.Value, out groupId);
                    steps += 1;
                }
                return false;
            }

            public void ToggleCollapseAll()
            {
                var labels = TabGroups();
                if (labels.Count == 0)
                    return;
                var folded = labels.Where(label => Collapsed.Contains((TabLabel, label))).ToList();
                if (folded.Count == labels.Count)
                {
                    foreach (var label in labels)
                        Collapsed.Remove((TabLabel, label));
                }
                else
                {
                    foreach (var label in labels)
                        Collapsed.Add((TabLabel, label));
                }
                ApplyFilters();
                PaintCollapseButton();
                Say();
            }

            internal void PaintCollapseButton()
            {
                var labels = TabGroups();
                PsUi.SetVisible(CollapseButton, labels.Count > 0);
                var folded = labels.Where(label => Collapsed.Contains((TabLabel, label))).ToList();
                bool everything = labels.Count > 0 && folded.Count == labels.Count;
                PsUi.SetText(CollapseText, everything ? "Expand all" : "Collapse all");
                PsUi.SetVisible(CollapseIcon, !everything);
                PsUi.SetVisible(ExpandIcon, everything);
            }

            // ==================================================================
            // filtering
            // ==================================================================

            internal void SearchChanged(object sender, TextChangedEventArgs args)
            {
                try
                {
                    if (SearchTimer == null)
                    {
                        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(SearchMs) };
                        timer.Tick += SearchTick;
                        SearchTimer = timer;
                    }
                    SearchTimer.Stop();
                    SearchTimer.Start();
                }
                catch (Exception)
                {
                    ApplyFilters();
                }
            }

            internal void SearchTick(object sender, EventArgs args)
            {
                try
                {
                    SearchTimer.Stop();
                }
                catch (Exception)
                {
                }
                ApplyFilters();
                Say();
            }

            internal string Needle()
            {
                try
                {
                    return (SearchBox.Text ?? "").Trim().ToLowerInvariant();
                }
                catch (Exception)
                {
                    return "";
                }
            }

            /// <summary>Search, column filters and Included only - everything but folding.</summary>
            internal bool PassesView(DataRow entry, Dictionary<string, string> values,
                                     IDictionary<string, HashSet<string>> filters, string needle)
            {
                if (!string.IsNullOrEmpty(needle))
                {
                    values.TryGetValue("num", out var num);
                    values.TryGetValue("name", out var name);
                    if (!((num ?? "") + " " + (name ?? "")).ToLowerInvariant().Contains(needle))
                        return false;
                }
                if (!PsRegister.Passes(values, filters))
                    return false;
                if (ShowMode == "included" && !Included.Contains(Str(entry["key"])))
                    return false;
                if (Isolated.Count > 0 &&
                    !Isolated.Any(key => values.TryGetValue(key, out var value) && !string.IsNullOrEmpty(value)))
                    return false;
                return true;
            }

            /// <summary>Take the filter decision once and write it into vis.
            ///
            /// show is then vis minus anything under a folded heading. Two
            /// reasons to hide a row need two flags: collapsed onto one, unfolding
            /// a series would bring back drawings the filter had removed.</summary>
            internal void ApplyFilters()
            {
                CommitEdits();
                string needle = Needle();
                var alive = new HashSet<int>();
                foreach (DataRow entry in Table.Rows)
                {
                    if (IsHeading(entry))
                        continue;
                    if (IsIssue(entry))
                    {
                        // Always there: a search or a filter narrows the drawings,
                        // not the issue data above them.
                        entry["vis"] = "1";
                        entry["show"] = "1";
                        continue;
                    }
                    bool visible = PassesView(entry, Values(entry), ColumnFilters, needle);
                    int? group = AsInt(entry["hid"]);
                    entry["vis"] = visible ? "1" : "0";
                    entry["show"] = (visible && !Folded(group)) ? "1" : "0";
                    if (visible)
                    {
                        while (group != null && group.Value >= 0)
                        {
                            alive.Add(group.Value);
                            GroupParent.TryGetValue(group.Value, out group);
                        }
                    }
                }
                // A heading stays while anything under it passes the filter, folded
                // or not - folding hides the drawings, not the way back to them. A
                // series heading goes with its discipline when that is folded.
                foreach (DataRow entry in Table.Rows)
                {
                    if (!IsHeading(entry))
                        continue;
                    int group = AsInt(entry["hid"]);
                    GroupParent.TryGetValue(group, out int? parent);
                    bool shown = alive.Contains(group) && !(parent != null && Folded(parent));
                    entry["show"] = shown ? "1" : "0";
                    entry["vis"] = entry["show"];
                    int level = AsInt(entry["level"]);
                    GroupPaths.TryGetValue(group, out var path);
                    string wanted = HeadingText(level, Collapsed.Contains((TabLabel, path)), Str(entry["glabel"]));
                    if (Str(entry["num"]) != wanted)
                        entry["num"] = wanted;
                }
                PaintTicks();
                PaintResetButton();
                SyncRevisionColumns();
                PaintPickButtons();
            }

            /// <summary>Heading ticks, and the one in the column heading, only where
            /// they mean something - see PsRegister.HeadingTicksShown.</summary>
            internal void PaintTicks()
            {
                bool drawings = false;
                foreach (DataRow entry in Table.Rows)
                {
                    if (IsDrawing(entry) && Str(entry["show"]) == "1")
                    {
                        drawings = true;
                        break;
                    }
                }
                bool shown = PsRegister.HeadingTicksShown(ShowMode == "included", drawings);
                string flag = shown ? "0" : "1";
                bool was = Suspend;
                Suspend = true;
                try
                {
                    foreach (DataRow entry in Table.Rows)
                    {
                        string wanted = IsHeading(entry) ? flag : (IsIssue(entry) ? "1" : "0");
                        if (Str(entry["hidetick"]) != wanted)
                            entry["hidetick"] = wanted;
                    }
                }
                finally
                {
                    Suspend = was;
                }
                if (HeaderTick != null)
                {
                    try
                    {
                        HeaderTick.Visibility = shown ? Visibility.Visible : Visibility.Hidden;
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            /// <summary>Whether the keyboard is in a text box.</summary>
            internal bool Typing()
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

            /// <summary>F5 re-reads; Escape lets go of picked revisions and cells;
            /// Ctrl+Z / Ctrl+Y undo and redo; Ctrl+PageUp and Ctrl+PageDown cycle the tabs.</summary>
            internal void KeyDown(object sender, KeyEventArgs args)
            {
                Key key;
                try
                {
                    key = args.Key;
                }
                catch (Exception)
                {
                    return;
                }
                if (key == Key.F5)
                {
                    Reload();
                    args.Handled = true;
                    return;
                }
                if (key == Key.Escape && (PickedCells.Count > 0 || PickedColumns.Count > 0))
                {
                    ClearPicks();
                    args.Handled = true;
                    return;
                }
                if (!PsUi.CtrlDown())
                    return;
                if ((key == Key.Z || key == Key.Y) && !Typing())
                {
                    // A search box keeps its own Ctrl+Z.
                    if (key == Key.Z)
                        Undo();
                    else
                        Redo();
                    args.Handled = true;
                    return;
                }
                if (key == Key.PageDown || key == Key.PageUp)
                {
                    int step = key == Key.PageDown ? 1 : -1;
                    int index = TabIndex + step;
                    while (0 <= index && index < Tabs.Count && !TabShows(index))
                        index += step;
                    if (0 <= index && index < Tabs.Count)
                        SelectTab(index);
                    args.Handled = true;
                }
            }

            // ==================================================================
            // the Excel register
            // ==================================================================

            /// <summary>Whether an Export run should write the register too.</summary>
            public bool AddToExport()
            {
                try
                {
                    return ExportCheck.IsChecked == true;
                }
                catch (Exception)
                {
                    return Host.Settings.Flag("reg_add_to_export", false);
                }
            }

            internal void ExportToggled(object sender, RoutedEventArgs args)
            {
                Setting("reg_add_to_export", AddToExport() ? "1" : "0");
                // The Create tab lists it as one more file the run will write.
                try
                {
                    Host.RefreshPlan();
                }
                catch (Exception)
                {
                }
            }

            /// <summary>The drawings in the register, in drawing number order.</summary>
            public List<PsRegister.RegisterRow> IncludedRows()
            {
                return Rows.Where(row => Included.Contains(Str(row.Key))).ToList();
            }

            public PsRegExport.Info ExportInfo()
            {
                var settings = Host.Settings;
                var info = new PsRegExport.Info();
                string title = settings.Text("reg_title", "");
                info.Title = string.IsNullOrEmpty(title) ? info.Title : title;
                string logo = settings.Text("reg_logo", "");
                info.Logo = !string.IsNullOrEmpty(logo) && System.IO.File.Exists(logo) ? logo : "";
                string client = settings.Text("reg_client_logo", "");
                info.ClientLogo = !string.IsNullOrEmpty(client) && System.IO.File.Exists(client) ? client : "";
                // Kept blank on purpose means no snapshot column, so the stored
                // text is used as it is rather than falling back to the default.
                info.Snapshot = (settings.Store.TryGetValue("reg_snapshot", out var snapshot) ? snapshot : info.Snapshot) ?? "";
                info.Legend = PsConfig.GetList(settings.Store, "reg_legend", info.Legend);
                // The Issued To / Method rows and each Issue Status come from the
                // Revision Manager's own columns, kept in the model.
                try
                {
                    var (columns, values) = PsRevData.Read(Host.Doc);
                    info.RevisionColumns = columns;
                    info.RevisionValues = values;
                }
                catch (Exception)
                {
                    info.RevisionColumns = new List<PsRevData.Column>();
                    info.RevisionValues = new Dictionary<string, Dictionary<string, string>>();
                }
                info.Footer = settings.Text("reg_footer", "");
                string paper = settings.Text("reg_paper", "");
                info.Paper = string.IsNullOrEmpty(paper) ? info.Paper : paper;
                info.SeriesParam = SeriesParam;
                info.HideUnused = HideUnused;
                info.Skip = new HashSet<string>(SkipTabs);
                var project = PsModel.ProjectInfo(Host.Doc);
                try
                {
                    info.ProjectNumber = PsModel.ToText(project.Number);
                    info.ProjectName = PsModel.ToText(project.Name);
                }
                catch (Exception)
                {
                }
                try
                {
                    info.ModelName = PsModel.ToText(Host.Doc.Title);
                }
                catch (Exception)
                {
                }
                return info;
            }

            /// <summary>"&lt;project&gt; - Document Register - YYYY-MM-DD.xlsx"</summary>
            public string FileName(DateTime? today = null)
            {
                var info = ExportInfo();
                string project = !string.IsNullOrEmpty(info.ProjectName) ? info.ProjectName
                    : !string.IsNullOrEmpty(info.ModelName) ? info.ModelName : "Project";
                return PsRegister.RegisterFileName(project, today);
            }

            /// <summary>(ok, message).</summary>
            public (bool Ok, string Message) WriteExcel(string path)
            {
                EnsureLoaded();
                var rows = IncludedRows();
                if (rows.Count == 0)
                {
                    return (false, "Nothing is in the register yet - tick the " +
                                   "drawings to include on the Document Register tab.");
                }
                var info = ExportInfo();
                if (PsRegExport.Worksheets(rows, info.Skip).Count == 0)
                {
                    return (false, "Every discipline with drawings in the register " +
                                   "is unticked on the tabs along the bottom, so " +
                                   "there is no worksheet to write.");
                }
                return PsRegExport.Write(path, Revisions, rows, info);
            }

            /// <summary>Write the register now, wherever the user says.</summary>
            public void ExportNow()
            {
                EnsureLoaded();
                if (Included.Count == 0)
                {
                    Host.Say("Tick at least one drawing to include first.");
                    return;
                }
                string path = PsUi.PickFile(true, "Export the Document Register", ".xlsx", FileName(), "Excel workbook");
                if (string.IsNullOrEmpty(path))
                    return;
                if (!path.ToLowerInvariant().EndsWith(".xlsx", StringComparison.Ordinal))
                    path += ".xlsx";
                var (ok, message) = WriteExcel(path);
                Host.Say(message);
                if (!ok)
                {
                    new PsUi.Prompt(
                        title: "Document Register",
                        headline: "The register was not written.",
                        message: message, primary: "Close",
                        themeName: Host.ThemeName, owner: Window).Show();
                    return;
                }
                string answer = new PsUi.Prompt(
                    title: "Document Register",
                    headline: "Document Register exported. Open the folder?",
                    message: path,
                    primary: "Open folder", secondary: "Not now",
                    themeName: Host.ThemeName, owner: Window).Show();
                if (answer == "primary")
                    PsExport.OpenFolder(System.IO.Path.GetDirectoryName(path), path);
            }

            /// <summary>Write the register alongside an export run's drawings.
            ///
            /// folder is the one above the run's PDF and DWG folders, decided
            /// by the window from the run's own plan - see register_folder. Called
            /// on Revit's thread from the run itself; never raises, and every step
            /// goes in the debug log, so "it was not there" can be told apart from
            /// "it went somewhere else".</summary>
            public bool ExportInto(string folder, PsExport.Report report)
            {
                string path = "";
                bool ok;
                string message;
                try
                {
                    PsExport.Debug(string.Format("Document Register: writing into \"{0}\"", folder));
                    if (string.IsNullOrEmpty(folder))
                    {
                        ok = false;
                        message = "The run had no folder to put the register in.";
                    }
                    else
                    {
                        path = System.IO.Path.Combine(folder, FileName());
                        (ok, message) = WriteExcel(path);
                    }
                }
                catch (Exception err)
                {
                    ok = false;
                    message = err.Message;
                }
                PsExport.Debug(string.Format("Document Register: {0} - {1}", ok ? "written" : "FAILED", !ok ? message : path));
                report.Add(new PsExport.Outcome("register", "Document Register", "xlsx", path, ok, message));
                return ok;
            }

            // ==================================================================
            // saying what is going on
            // ==================================================================

            internal void SaySource()
            {
                string disc = string.IsNullOrEmpty(DisciplineParam) ? "(not set)" : DisciplineParam;
                string series = string.IsNullOrEmpty(SeriesParam) ? "(not set)" : SeriesParam;
                PsUi.SetText(Source, string.Format("Tabs by {0}  ·  grouped by {1}", disc, series));
            }

            internal void SayNotes()
            {
                var notes = new List<string>(Warnings);
                if (Loaded && Rows.Count > 0)
                {
                    if (!string.IsNullOrEmpty(DisciplineParam) && !PsRegister.HasValues(Rows, row => row.Discipline))
                    {
                        notes.Add(string.Format("{0} has no value on any sheet, so every " +
                                                "drawing is on the All tab.", DisciplineParam));
                    }
                    if (!string.IsNullOrEmpty(SeriesParam) && !PsRegister.HasValues(Rows, row => row.Series))
                    {
                        notes.Add(string.Format("{0} has no value on any sheet, so the " +
                                                "drawings are not grouped.", SeriesParam));
                    }
                    if (Revisions.Count == 0)
                        notes.Add("No revisions in this model yet, so there are no revision columns.");
                }
                PsUi.SetText(Note, string.Join("  ", notes));
                PsUi.SetVisible(Note, notes.Count > 0);
            }

            internal void Say()
            {
                int total = Rows.Count;
                int everywhere = RowsByKey.Keys.Count(key => Included.Contains(key));
                var visible = VisibleKeys();
                int onTab = 0;
                int inTab = 0;
                if (Tabs.Count > 0 && 0 <= TabIndex && TabIndex < Tabs.Count)
                {
                    var members = Tabs[TabIndex].Rows;
                    onTab = members.Count;
                    inTab = members.Count(row => Included.Contains(Str(row.Key)));
                }
                PsUi.SetText(Summary, string.Format("{0} of {1} drawing{2} in the register  ·  {3} of {4} on this tab",
                                                    everywhere, total, Plural(total), inTab, onTab));
                if (HeaderTick != null)
                {
                    try
                    {
                        HeaderTick.IsChecked = visible.Count > 0 && visible.All(key => Included.Contains(key));
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            internal int AsInt(object value)
            {
                return int.TryParse(Str(value), System.Globalization.NumberStyles.AllowLeadingSign |
                                                System.Globalization.NumberStyles.AllowLeadingWhite |
                                                System.Globalization.NumberStyles.AllowTrailingWhite,
                                    Inv, out int number) ? number : -1;
            }
        }
    }
}
