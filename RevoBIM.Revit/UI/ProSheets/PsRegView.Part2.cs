using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Markup;
using System.Windows.Media;
using RevoBIM.Tools.ProSheets;
using UIApplication = Autodesk.Revit.UI.UIApplication;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsRegView
    {
        public partial class RegisterView
        {
            // ==================================================================
            // all, or included only
            // ==================================================================

            public void SetShow(string mode)
            {
                ShowMode = mode == "included" ? "included" : "all";
                Setting("reg_show", ShowMode);
                PaintShow();
                // A discipline with nothing in the register has no tab under
                // "Included only", so being on one moves you to All.
                if (ShowMode == "included" && Tabs.Count > 0 && !TabHasIncluded(TabIndex))
                {
                    SelectTab(0);
                }
                else
                {
                    ApplyFilters();
                    PaintTabStrip();
                }
                Say();
            }

            internal bool TabHasIncluded(int index)
            {
                if (!(0 <= index && index < Tabs.Count))
                    return false;
                var (label, members) = Tabs[index];
                return label == PsRegister.AllTab || members.Any(row => Included.Contains(Str(row.Key)));
            }

            internal bool TabShows(int index)
            {
                var (label, members) = Tabs[index];
                return PsRegister.TabShows(label, members, Included, ShowMode == "included", index == TabIndex);
            }

            internal void PaintShow()
            {
                bool onAll = ShowMode == "all";
                if (ShowAllButton != null)
                    Host.Styled(ShowAllButton, onAll ? "SwitchButtonOn" : "ChipButton");
                if (ShowIncludedButton != null)
                    Host.Styled(ShowIncludedButton, onAll ? "ChipButton" : "SwitchButtonOn");
            }

            // ==================================================================
            // the tab strip along the bottom
            // ==================================================================

            /// <summary>A tab per discipline: its tick box, its colour, its name and count.
            ///
            /// The tick box says whether the discipline gets a worksheet in the
            /// Excel export - ticked by default, and greyed while the discipline
            /// has nothing in the register, since an empty worksheet is never
            /// written. A CheckBox inside a Button handles its own click, so
            /// ticking it does not also switch tabs.</summary>
            internal void BuildTabStrip()
            {
                TabButtons = new List<Button>();
                TabChecks = new List<CheckBox>();
                TabTexts = new List<TextBlock>();
                if (TabStrip == null)
                    return;
                try
                {
                    TabStrip.Children.Clear();
                }
                catch (Exception)
                {
                    return;
                }
                bool several = Tabs.Count > 1;
                for (int index = 0; index < Tabs.Count; index++)
                {
                    string label = Tabs[index].Label;
                    var button = new Button();
                    Host.Styled(button, "SheetTab");
                    button.Click += MakeTabClick(index);
                    var panel = new StackPanel { Orientation = Orientation.Horizontal };
                    CheckBox check = null;
                    if (several)
                    {
                        // The All tab's tick adds an All worksheet, every
                        // discipline on one sheet; off until ticked.
                        check = new CheckBox
                        {
                            VerticalAlignment = VerticalAlignment.Center,
                            Margin = new Thickness(0, 0, 7, 0),
                            IsChecked = PsRegister.TabTicked(label, SkipTabs),
                        };
                        check.Click += MakeTabCheck(label);
                        panel.Children.Add(check);
                    }
                    if (DiscColour.ContainsKey(label))
                    {
                        var swatch = new Border
                        {
                            Width = 10,
                            Height = 10,
                            CornerRadius = new CornerRadius(2),
                            Margin = new Thickness(0, 0, 7, 0),
                            VerticalAlignment = VerticalAlignment.Center,
                            Tag = label,
                        };
                        panel.Children.Add(swatch);
                    }
                    var icon = TabIcon(label);
                    if (icon != null)
                        panel.Children.Add(icon);
                    var text = new TextBlock { VerticalAlignment = VerticalAlignment.Center };
                    panel.Children.Add(text);
                    button.Content = panel;
                    TabStrip.Children.Add(button);
                    TabButtons.Add(button);
                    TabChecks.Add(check);
                    TabTexts.Add(text);
                }
                PaintTabStrip();
            }

            /// <summary>A small icon saying what the tab holds (see PsRegister.TabIcon),
            /// drawn in the tab's own text colour so it follows the theme and the
            /// live tab. Null when the name says nothing known.</summary>
            internal UIElement TabIcon(string label)
            {
                string data = PsRegister.TabIcon(label);
                if (string.IsNullOrEmpty(data))
                    return null;
                try
                {
                    return XamlReader.Parse(string.Format(PsRegView.TabIconXaml, PsRegView.Presentation, data)) as UIElement;
                }
                catch (Exception)
                {
                    return null;
                }
            }

            internal RoutedEventHandler MakeTabClick(int index)
            {
                return (sender, args) => SelectTab(index);
            }

            internal void PaintTabStrip()
            {
                for (int index = 0; index < TabButtons.Count; index++)
                {
                    var button = TabButtons[index];
                    var (label, members) = Tabs[index];
                    bool active = index == TabIndex;
                    Host.Styled(button, active ? "SheetTabOn" : "SheetTab");
                    // The discipline's own colour, the one its heading wears on the
                    // All tab. The All tab keeps the plain tab colours.
                    if (DiscColour.TryGetValue(label, out string colour) && colour != null)
                    {
                        colour = ShownColour(label, 1, colour);
                        try
                        {
                            // A tint behind the tab, so its text reads on either
                            // theme and its hover still shows; the swatch is the
                            // solid colour the discipline's heading wears.
                            var (tint, _, solid) = Host.ShadeBrushes(colour);
                            button.Background = tint;
                            foreach (var child in ((Panel)button.Content).Children)
                            {
                                if (child is Border border)
                                    border.Background = solid;
                            }
                        }
                        catch (Exception)
                        {
                        }
                    }
                    int count = members.Count;
                    int done = members.Count(row => Included.Contains(Str(row.Key)));
                    PsUi.SetVisible(button, TabShows(index));
                    var text = index < TabTexts.Count ? TabTexts[index] : null;
                    if (text != null)
                    {
                        try
                        {
                            text.Text = string.Format("{0}   {1}/{2}", label, done, count);
                            // Bold on every tab - the live one is told by its bar.
                            text.FontWeight = FontWeights.Bold;
                        }
                        catch (Exception)
                        {
                        }
                    }
                    var check = index < TabChecks.Count ? TabChecks[index] : null;
                    if (check != null)
                    {
                        try
                        {
                            check.IsEnabled = done > 0;
                            check.ToolTip = done == 0
                                ? string.Format("Nothing from {0} is in the register, so it gets no worksheet.", label)
                                : label == PsRegister.AllTab
                                    ? "Ticked: an All worksheet comes first in the Excel " +
                                      "export, every discipline on one sheet under its " +
                                      "own heading. Unticked: one worksheet per " +
                                      "discipline only."
                                    : string.Format("Ticked: {0} gets a worksheet in the Excel export. " +
                                                    "Untick to leave it out.", label);
                        }
                        catch (Exception)
                        {
                        }
                    }
                    try
                    {
                        button.ToolTip = string.Format("{0}: {1} of {2} drawing{3} in the register",
                                                       label, done, count, Plural(count));
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }

            internal RoutedEventHandler MakeTabCheck(string label)
            {
                return (sender, args) =>
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
                    SkipTabs = PsRegister.TickTab(label, wanted, SkipTabs);
                    PsConfig.WriteRegisterSkipped(Host.Doc, SkipTabs);
                    if (label == PsRegister.AllTab)
                    {
                        Host.Say(string.Format("The Excel export {0} an All worksheet, every " +
                                               "discipline on one sheet, before the others.",
                                               wanted ? "gets" : "no longer gets"));
                        return;
                    }
                    Host.Say(string.Format("{0} {1} the Excel export.", label,
                                           wanted ? "is back in" : "is left out of"));
                };
            }

            /// <summary>After a palette swap: the colours here are brushes set in code.</summary>
            public void Repaint()
            {
                if (HeadingMode == PsRamp.Grey && Loaded)
                {
                    // Grey headings are greys of the theme: fill again.
                    SelectTab(TabIndex);
                    return;
                }
                PaintTabStrip();
                CommitEdits();
                try
                {
                    Grid.Items.Refresh();
                }
                catch (Exception)
                {
                }
            }

            public void SelectTab(int index)
            {
                if (Tabs.Count == 0)
                {
                    TabIndex = 0;
                    Fill(new List<PsRegister.RegisterRow>());
                    BuildColumns(new List<PsRegister.RegisterRow>());
                    Say();
                    return;
                }
                index = Math.Max(0, Math.Min(Tabs.Count - 1, index));
                TabIndex = index;
                TabLabel = Tabs[index].Label;
                var members = Tabs[index].Rows;
                Fill(members);
                BuildColumns(members);
                ApplyFilters();
                FitColumns();
                PaintTabStrip();
                PaintCollapseButton();
                PaintHeadingModeButton();
                PaintFreezeButton();
                SayNotes();
                Say();
            }

            // ==================================================================
            // filling the table
            // ==================================================================

            internal string HeadingText(int level, bool folded, string label)
            {
                string indent = level == 2 ? "      " : "";
                return indent + (folded ? PsRegView.Collapsed : PsRegView.Expanded) + label;
            }

            /// <summary>Close any edit the grid has open before the table is reshaped.
            ///
            /// A tick is an edit on its row until the grid commits it. Clearing or
            /// re-filtering the table underneath an open edit throws "Refresh is
            /// not allowed during an AddNew or EditItem transaction". Twice: once
            /// for the cell, once for the row.</summary>
            internal void CommitEdits()
            {
                if (Grid == null)
                    return;
                for (int step = 0; step < 2; step++)
                {
                    try
                    {
                        Grid.CommitEdit();
                    }
                    catch (Exception)
                    {
                        return;
                    }
                }
            }

            /// <summary>The rows for a tab, under their headings.
            ///
            /// The All tab is grouped by discipline and then by series inside each;
            /// a discipline's tab by series. Every heading carries a colour place
            /// for the row painter, and every drawing the place of the heading it
            /// sits directly under.</summary>
            internal void Fill(List<PsRegister.RegisterRow> members)
            {
                CommitEdits();
                bool byDiscipline = TabLabel == PsRegister.AllTab && Tabs.Count > 1;
                var tree = PsRegister.GroupTree(members, byDiscipline, !string.IsNullOrEmpty(SeriesParam));
                Suspend = true;
                try
                {
                    Table.Rows.Clear();
                    Groups = new Dictionary<int, List<string>>();
                    GroupPaths = new Dictionary<int, string>();
                    GroupParent = new Dictionary<int, int?>();
                    Order = 0;
                    Entries = new Dictionary<string, DataRow>(StringComparer.Ordinal);
                    PickedCells = new HashSet<(string Sheet, string Column)>();
                    CellAnchor = null;
                    // New rows carry the model's text: nothing staged is painted.
                    PendingFlags = new Dictionary<(string Sheet, string Column), string>();
                    // Project Browser Pro's colours: planned over the whole tab
                    // first, because a heading's shade depends on how many of its
                    // trade sit beside it.
                    var colours = HeadingColours(tree, byDiscipline);
                    int serial = 0;

                    string NextColour()
                    {
                        colours.TryGetValue(serial, out string found);
                        serial += 1;
                        return found ?? "";
                    }

                    foreach (var (label, rows, children) in tree)
                    {
                        if (label == null)
                        {
                            foreach (var row in rows)
                                AddDrawing(row, -1, "");
                            continue;
                        }
                        string colour = ShownColour(label, 1, NextColour());
                        int head = AddHeading(label, label, 1, null, colour, rows);
                        if (children == null || children.Count == 0)
                        {
                            foreach (var row in rows)
                                AddDrawing(row, head, colour);
                            continue;
                        }
                        foreach (var (inner, innerRows, _) in children)
                        {
                            string innerColour = ShownColour(inner, 2, NextColour());
                            int subHead = AddHeading(inner, label + "/" + inner, 2, head, innerColour, innerRows);
                            foreach (var row in innerRows)
                                AddDrawing(row, subHead, innerColour);
                        }
                    }
                    // Unfrozen, the issue data are the first rows of the tab.
                    if (IssueFields.Count > 0 && !IssueFrozen)
                        AddIssueRows();
                }
                finally
                {
                    Suspend = false;
                }
                SyncHeadings();
                PaintPending();
            }

            /// <summary>{discipline: hex}: the colour each discipline's heading wears
            /// on the All tab, and its own tab in the strip.</summary>
            public static Dictionary<string, string> DisciplineColours(List<string> labels)
            {
                var found = PsRamp.Plan(labels.Select((label, index) => (index, label, 1, (int?)null)).ToList());
                var result = new Dictionary<string, string>(StringComparer.Ordinal);
                for (int index = 0; index < labels.Count; index++)
                    result[labels[index]] = found[index];
                return result;
            }

            /// <summary>{n: hex} for the nth heading of tree, in the order Fill
            /// adds them.
            ///
            /// Disciplines on the All tab take the colours the tab strip shows.
            /// Series take their own trade where their name says one, otherwise
            /// the discipline's - the one above them, or the tab they are on.</summary>
            public Dictionary<int, string> HeadingColours(List<PsRegister.GroupNode> tree, bool byDiscipline)
            {
                var headings = new List<(int Id, string Label, int Level, int? Parent)>();
                foreach (var (label, _, children) in tree)
                {
                    if (label == null)
                        continue;
                    int top = headings.Count;
                    headings.Add((top, label, 1, null));
                    foreach (var (inner, _, _) in children ?? new List<PsRegister.GroupNode>())
                        headings.Add((headings.Count, inner, 2, top));
                }
                string inherit = byDiscipline ? null : TabLabel;
                var found = PsRamp.Plan(headings, inherit: inherit);
                if (byDiscipline)
                {
                    foreach (var (hid, label, level, _) in headings)
                    {
                        if (level == 1 && DiscColour.ContainsKey(label))
                            found[hid] = DiscColour[label];
                    }
                }
                return found;
            }

            internal int AddHeading(string label, string path, int level, int? parent, string place,
                                    List<PsRegister.RegisterRow> rows)
            {
                int groupId = GroupPaths.Count;
                Groups[groupId] = rows.Select(row => Str(row.Key)).ToList();
                GroupPaths[groupId] = path;
                GroupParent[groupId] = parent;
                var head = Table.NewRow();
                head["key"] = "";
                head["glabel"] = label ?? "";
                head["gpath"] = path ?? "";
                head["level"] = Str(level);
                head["gcolor"] = place ?? "";
                try
                {
                    head["gink"] = Host.InkBrush(place);
                }
                catch (Exception)
                {
                }
                head["num"] = HeadingText(level, false, label);
                head["ishead"] = "1";
                head["hid"] = Str(groupId);
                head["vis"] = "1";
                head["show"] = "1";
                head["ord"] = Order.ToString("000000", Inv);
                Table.Rows.Add(head);
                Order += 1;
                return groupId;
            }

            internal void AddDrawing(PsRegister.RegisterRow row, int groupId, string place)
            {
                var entry = Table.NewRow();
                string key = Str(row.Key);
                entry["sel"] = Included.Contains(key);
                entry["key"] = key;
                entry["num"] = row.Number ?? "";
                entry["name"] = row.Name ?? "";
                entry["size"] = row.Size ?? "";
                entry["scale"] = row.Scale ?? "";
                entry["rev"] = row.Current ?? "";
                entry["rdate"] = row.CurrentDate ?? "";
                entry["seq"] = row.CurrentSequence ?? "";
                entry["curkey"] = row.CurrentKey ?? "";
                entry["ishead"] = "0";
                entry["hid"] = Str(groupId);
                entry["glabel"] = "";
                entry["gpath"] = "";
                entry["level"] = "0";
                entry["gcolor"] = place ?? "";
                entry["vis"] = "1";
                entry["show"] = "1";
                entry["ord"] = Order.ToString("000000", Inv);
                foreach (var pair in row.Cells)
                {
                    try
                    {
                        entry[pair.Key] = pair.Value ?? "";
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
                Table.Rows.Add(entry);
                Entries[key] = entry;
                Order += 1;
            }

            /// <summary>A heading's band and its drawings' wash, as rows are realised.
            ///
            /// The Selection tab's colours, from the same helper. Set on every
            /// row, coloured or not: with recycling on, a container that was a
            /// heading a moment ago is handed to a drawing next, and skipping the
            /// reset leaves a stripe across the list.</summary>
            internal void PaintRow(object sender, DataGridRowEventArgs args)
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
                if (PaintIssueRow(row, entry))
                    return;
                string place;
                try
                {
                    place = Str(entry["gcolor"]);
                }
                catch (Exception)
                {
                    place = "";
                }
                try
                {
                    if (!place.StartsWith("#", StringComparison.Ordinal))
                    {
                        row.Background = Brushes.Transparent;
                        row.FontWeight = FontWeights.Normal;
                        return;
                    }
                    var (_, wash, head) = Host.ShadeBrushes(place);
                    if (IsHeading(entry))
                    {
                        row.Background = head;
                        row.FontWeight = FontWeights.Bold;
                    }
                    else
                    {
                        row.Background = wash;
                        row.FontWeight = FontWeights.Normal;
                    }
                }
                catch (Exception)
                {
                }
            }

            // ==================================================================
            // the columns
            // ==================================================================

            /// <summary>Every column a filter can be set on: the drawing columns and
            /// every revision, shown or not.</summary>
            internal List<string> FilterColumns()
            {
                var found = Identity.Where(entry => entry.Id != "sel").Select(entry => entry.Id).ToList();
                found.AddRange(Revisions.Select(revision => revision.Key));
                return found;
            }

            internal Dictionary<string, string> Values(DataRow entry)
            {
                var values = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (var column in FilterColumns())
                {
                    try
                    {
                        values[column] = Str(entry[column]).Trim();
                    }
                    catch (Exception)
                    {
                        values[column] = "";
                    }
                }
                return values;
            }

            /// <summary>The drawing columns. The revision columns follow the filter -
            /// see SyncRevisionColumns - so they are added by ApplyFilters.</summary>
            internal void BuildColumns(List<PsRegister.RegisterRow> members)
            {
                UsedColumns = new List<PsRegister.RevisionColumn>();
                Columns = new Dictionary<string, DataGridColumn>(StringComparer.Ordinal);
                FilterButtons = new Dictionary<string, Button>(StringComparer.Ordinal);
                SeqButtons = new Dictionary<string, Button>(StringComparer.Ordinal);
                IssueCells = new Dictionary<(string Column, string Field), Control>();
                IssueRows = new Dictionary<(string Column, string Field), Border>();
                IssuePieces = new Dictionary<string, Border>(StringComparer.Ordinal);
                BlockSpacers = new Dictionary<string, Border>(StringComparer.Ordinal);
                BuildIssueLabels();
                if (Grid == null)
                    return;
                HeaderTick = null;
                try
                {
                    Grid.Columns.Clear();
                }
                catch (Exception)
                {
                    return;
                }
                foreach (var (colId, title, floor) in Identity)
                {
                    try
                    {
                        var column = IdentityColumn(colId, title, floor);
                        Grid.Columns.Add(column);
                        Columns[colId] = column;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
                // Where the drawings end and the revisions begin; frozen with the
                // drawing columns, so the line stays put as the revisions scroll.
                try
                {
                    Grid.Columns.Add(DividerColumn());
                }
                catch (Exception)
                {
                }
                try
                {
                    Grid.FrozenColumnCount = Identity.Count + 1;
                }
                catch (Exception)
                {
                }
                PlusColumn = PlusColumnCore();
                try
                {
                    Grid.Columns.Add(PlusColumn);
                }
                catch (Exception)
                {
                }
            }

            /// <summary>Show the revision columns the view calls for, and only those.
            ///
            /// With Hide unused revisions on, the columns the drawings passing
            /// the filters actually carry; off, every revision in the project. A
            /// column with a filter of its own always stays, or a filter could
            /// hide the very column it would have to be cleared from. Only the
            /// revision columns are touched - the drawing columns' headings, and
            /// anything open in them, stay put.</summary>
            internal void SyncRevisionColumns()
            {
                var visible = new List<PsRegister.RegisterRow>();
                foreach (DataRow entry in Table.Rows)
                {
                    if (IsHeading(entry) || Str(entry["vis"]) != "1")
                        continue;
                    if (RowsByKey.TryGetValue(Str(entry["key"]), out var row))
                        visible.Add(row);
                }
                var wanted = PsRegister.RevisionsFor(Revisions, visible, HideUnused);
                var keep = new HashSet<string>(wanted.Select(column => column.Key), StringComparer.Ordinal);
                foreach (var pair in ColumnFilters)
                {
                    if (pair.Value != null && PsRegister.IsColumnKey(pair.Key))
                        keep.Add(pair.Key);
                }
                wanted = Revisions.OrderBy(one => one.Sequence).Where(column => keep.Contains(column.Key)).ToList();
                if (wanted.Select(c => c.Key).SequenceEqual(UsedColumns.Select(c => c.Key)))
                    return;
                if (Grid == null)
                {
                    UsedColumns = wanted;
                    return;
                }
                foreach (var column in UsedColumns)
                {
                    Columns.TryGetValue(column.Key, out var existing);
                    Columns.Remove(column.Key);
                    SeqButtons.Remove(column.Key);
                    ForgetIssuePiece(column.Key);
                    if (existing != null)
                    {
                        try
                        {
                            Grid.Columns.Remove(existing);
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
                foreach (var revision in wanted)
                {
                    try
                    {
                        var column = RevisionColumnCore(revision);
                        Grid.Columns.Add(column);
                        Columns[revision.Key] = column;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
                // The + stays last, after whatever revisions came and went.
                if (PlusColumn != null)
                {
                    try
                    {
                        Grid.Columns.Remove(PlusColumn);
                        Grid.Columns.Add(PlusColumn);
                    }
                    catch (Exception)
                    {
                    }
                }
                UsedColumns = wanted;
                FitRevisionColumns();
                PaintIssueEdges();
                PaintIssueBlock();
            }

            /// <summary>Every revision in the project, or only the ones the drawings on
            /// screen carry. Kept as reg_hide_unused; the Excel export follows.</summary>
            public void SetShowAllRevisions(bool showAll, bool quiet = false)
            {
                HideUnused = !showAll;
                Setting("reg_hide_unused", HideUnused ? "1" : "0");
                SyncRevisionColumns();
                PaintAllRevsButton();
                if (!quiet)
                {
                    Host.Say(string.Format("Showing {0}. The Excel export follows.",
                                           HideUnused ? "only the revisions the drawings on screen carry"
                                                      : "every revision in the project"));
                }
            }

            /// <summary>Solid orange while every revision is showing.</summary>
            internal void PaintAllRevsButton()
            {
                if (AllRevsButton == null)
                    return;
                try
                {
                    AllRevsButton.SetResourceReference(FrameworkElement.StyleProperty,
                                                       HideUnused ? "ChipButton" : "SwitchButtonOn");
                }
                catch (Exception)
                {
                }
            }

            internal DataGridColumn IdentityColumn(string colId, string title, int floor)
            {
                if (colId == "sel")
                {
                    var tickColumn = new DataGridTemplateColumn
                    {
                        CellTemplate = (DataTemplate)XamlReader.Parse(TickTemplate),
                        Width = new DataGridLength(floor),
                        MinWidth = floor,
                        CanUserResize = false,
                        CanUserSort = false,
                    };
                    var box = new CheckBox();
                    Host.Styled(box, "GridCheckBox");
                    box.ToolTip = "Include or leave out every drawing showing on this tab";
                    box.Click += HeaderTickCore;
                    HeaderTick = box;
                    tickColumn.Header = UnderBlock(box, colId);
                    PaintTicks();
                    return tickColumn;
                }

                var column = new DataGridTextColumn
                {
                    Binding = new Binding(colId),
                    Width = new DataGridLength(floor),
                    MinWidth = 40,
                    IsReadOnly = true,
                    CanUserSort = false,
                };
                if (colId == "rev")
                    column.ElementStyle = CurrentStyle();
                else if (Centred.Contains(colId))
                    column.ElementStyle = CentredStyle();
                var panel = new StackPanel { Orientation = Orientation.Vertical };
                var heading = new TextBlock { Text = title, Margin = new Thickness(0, 0, 0, 4) };
                panel.Children.Add(heading);
                panel.Children.Add(FilterButton(colId));
                column.Header = UnderBlock(panel, colId);
                return column;
            }

            internal DataGridColumn DividerColumn()
            {
                return new DataGridTemplateColumn
                {
                    Width = new DataGridLength(3),
                    MinWidth = 3,
                    CanUserResize = false,
                    CanUserSort = false,
                    IsReadOnly = true,
                    CellTemplate = (DataTemplate)XamlReader.Parse(string.Format(PsRegView.EmptyCell, PsRegView.Presentation)),
                    HeaderStyle = (Style)XamlReader.Parse(string.Format(PsRegView.DividerHeaderStyle, PsRegView.Presentation)),
                    CellStyle = (Style)XamlReader.Parse(string.Format(PsRegView.DividerCellStyle, PsRegView.Presentation)),
                };
            }

            /// <summary>The last column: a green + in its heading for a new revision.
            /// (Python _plus_column; named ...Core beside the PlusColumn field.)</summary>
            internal DataGridColumn PlusColumnCore()
            {
                var column = new DataGridTemplateColumn
                {
                    Width = new DataGridLength(44),
                    CanUserResize = false,
                    CanUserSort = false,
                    IsReadOnly = true,
                    CellTemplate = (DataTemplate)XamlReader.Parse(string.Format(PsRegView.EmptyCell, PsRegView.Presentation)),
                };
                var button = new Button();
                Host.Styled(button, "IconButton");
                button.VerticalAlignment = VerticalAlignment.Bottom;
                button.HorizontalAlignment = HorizontalAlignment.Center;
                button.ToolTip = "Add a revision. It shows in green once it is made.";
                button.Content = XamlReader.Parse(string.Format(PsRegView.PlusIcon, PsRegView.Presentation));
                button.Click += (sender, args) => NewRevision();
                column.Header = UnderBlock(button);
                return column;
            }

            /// <summary>The Add revision window, then the revision made - and back here
            /// with every revision showing and the new one washed green (see
            /// RevisionsWritten).</summary>
            public void NewRevision()
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
                // The window's answer, applied to the staging once it is in hand
                // (outside the try, as the Python does: only the window is guarded).
                Action add;
                try
                {
                    var answer = PsRevAddWin.Ask(staging, Host.ThemeName, Window, null,
                                                 "Made in the model as soon as you " +
                                                 "press Add, then shown in green.");
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
                    Host.Say("Add revision cancelled - nothing changed.");
                    return;
                }
                add();
                var plan = staging.Plan();

                // On Revit's thread.
                void Job(UIApplication uiapp)
                {
                    WriteRevisions(plan);
                }

                if (Host.Queue(Job))
                    Host.Say("Making the revision...");
            }

            /// <summary>(Python _revision_column.)</summary>
            internal DataGridColumn RevisionColumnCore(PsRegister.RevisionColumn revision)
            {
                var column = new DataGridTextColumn
                {
                    Binding = new Binding(revision.Key),
                    Width = new DataGridLength(RevisionFloor),
                    MinWidth = RevisionFloor,
                    IsReadOnly = true,
                    // Sortable only so the header click is reported. OnSorting turns
                    // it into an isolate and cancels the sort.
                    CanUserSort = true,
                    SortMemberPath = revision.Key,
                    ElementStyle = CellStyle(revision.Key),
                    Header = RevisionHeader(revision),
                };
                var wash = ColumnWash(revision.Key);
                if (wash != null)
                    column.CellStyle = wash;
                return column;
            }

            /// <summary>The date rotated up the header, the status letter, a filter box.
            ///
            /// LayoutTransform, not RenderTransform: a render transform does not
            /// change the space the element asks for, so the header row stays one
            /// line high and the rotated text spills over its neighbours.</summary>
            internal StackPanel RevisionHeader(PsRegister.RevisionColumn revision)
            {
                var panel = new StackPanel
                {
                    Orientation = Orientation.Vertical,
                    HorizontalAlignment = HorizontalAlignment.Stretch,
                };

                // The sequence number over the date, as Revit's own Sheet Issues /
                // Revisions dialog numbers it. On screen only - the RD9 sheet has
                // no row for it, so the Excel export leaves it out.
                //
                // It is a Button, so its click is its own: a Button handles the
                // press, which never reaches the heading's Sorting. Clicking it
                // picks the column for Isolate.
                var sequence = new Button();
                string seqText = PsRegister.SequenceText(revision.Sequence);
                sequence.Content = string.IsNullOrEmpty(seqText) ? "-" : seqText;
                sequence.HorizontalAlignment = HorizontalAlignment.Center;
                sequence.Margin = new Thickness(0, 0, 0, 3);
                sequence.ToolTip = string.Format("Sequence {0}. Click to pick this revision - " +
                                                 "Ctrl+click for several, Shift+click for a run " +
                                                 "- then Isolate sheets with this revision.", revision.Sequence);
                sequence.Click += MakeSeqClick(revision.Key);
                SeqButtons[revision.Key] = sequence;
                PaintSeqButton(revision.Key);
                panel.Children.Add(sequence);

                var date = new TextBlock
                {
                    Text = revision.Heading(),
                    FontSize = 11,
                    FontWeight = FontWeights.Normal,
                    LayoutTransform = new RotateTransform(-90),
                    HorizontalAlignment = HorizontalAlignment.Center,
                };
                panel.Children.Add(date);

                var letter = new TextBlock
                {
                    // A space rather than nothing, so every header keeps the same height
                    // whether or not its column has a letter.
                    Text = string.IsNullOrEmpty(revision.StatusLetter) ? " " : revision.StatusLetter,
                    FontWeight = FontWeights.Bold,
                    HorizontalAlignment = HorizontalAlignment.Center,
                    Margin = new Thickness(0, 4, 0, 4),
                };
                letter.SetResourceReference(TextBlock.ForegroundProperty, "BlueBrush");
                // The issue data above, then the letter and the filter at the foot,
                // level with the drawing columns' names and filters (1.52.0).
                if (BlockShown())
                    panel.Children.Add(IssuePiece(revision));
                var foot = new StackPanel { Orientation = Orientation.Vertical };
                foot.Children.Add(letter);
                foot.Children.Add(FilterButton(revision.Key));
                panel.Children.Add(Footer(foot));

                panel.ToolTip = string.Format("{0}\n\nClick the heading to show only the sheets " +
                                              "carrying this revision - Ctrl+click for more - and " +
                                              "again to show every sheet.\nClick the sequence " +
                                              "number to pick it; right-click for the revision " +
                                              "tools.", revision.Describe());
                return panel;
            }

            /// <summary>The filter under a heading: a button opening the value list.
            ///
            /// A Button inside a heading handles its own click, so pressing it
            /// never reaches the heading - which would include a revision.</summary>
            internal Button FilterButton(string colId)
            {
                var button = new Button { Margin = new Thickness(0, 0, 0, 0) };
                button.Click += MakeFilterOpen(colId, button);
                FilterButtons[colId] = button;
                PaintFilterButton(colId);
                return button;
            }

            internal void PaintFilterButton(string colId)
            {
                if (!FilterButtons.TryGetValue(colId, out var button) || button == null)
                    return;
                ColumnFilters.TryGetValue(colId, out var allowed);
                bool on = allowed != null;
                Host.Styled(button, on ? "FilterButtonOn" : "FilterButton");
                try
                {
                    button.Content = on ? string.Format("▾ {0}", allowed.Count) : "▾";
                    button.ToolTip = on
                        ? string.Format("Filtered to {0} value{1} - click to change", allowed.Count, Plural(allowed.Count))
                        : "Filter this column";
                }
                catch (Exception)
                {
                }
            }

            internal RoutedEventHandler MakeFilterOpen(string colId, Button button)
            {
                return (sender, args) => OpenFilter(colId, button);
            }

            /// <summary>The values on offer: what the other filters leave on this tab.
            ///
            /// A column's own filter is left out of its own list, or the values it
            /// is hiding would not be there to tick back on - Excel's rule.</summary>
            internal List<string> Choices(string colId)
            {
                var others = ColumnFilters.Where(pair => pair.Key != colId)
                                          .ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal);
                string needle = Needle();
                var found = new List<string>();
                foreach (DataRow entry in Table.Rows)
                {
                    if (!IsDrawing(entry))
                        continue;
                    var values = Values(entry);
                    if (!PassesView(entry, values, others, needle))
                        continue;
                    found.Add(values.TryGetValue(colId, out var value) ? value : "");
                }
                return PsRegister.FilterChoices(found);
            }

            /// <summary>The Excel list: search, All, None, every value, (Blanks), OK.</summary>
            internal void OpenFilter(string colId, Button button)
            {
                var choices = Choices(colId);
                ColumnFilters.TryGetValue(colId, out var allowed);

                string Raw(string value)
                {
                    return value == PsRegister.Blanks ? "" : value;
                }

                var popup = new Popup
                {
                    PlacementTarget = button,
                    Placement = PlacementMode.Bottom,
                    StaysOpen = false,
                    AllowsTransparency = true,
                };

                var shell = new Border();
                shell.SetResourceReference(Border.BackgroundProperty, "CardBg");
                shell.SetResourceReference(Border.BorderBrushProperty, "EdgeBrush");
                shell.BorderThickness = new Thickness(1);
                shell.CornerRadius = new CornerRadius(4);
                shell.Padding = new Thickness(8);
                shell.MinWidth = 210;
                var panel = new StackPanel();
                shell.Child = panel;

                var search = new TextBox();
                Host.Styled(search, "ColumnSearchBox");
                search.Tag = "Search";
                search.Margin = new Thickness(0, 0, 0, 6);
                panel.Children.Add(search);

                var bulk = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 6) };
                var every = new Button { Content = "All" };
                Host.Styled(every, "ChipButton");
                every.Margin = new Thickness(0, 0, 6, 0);
                var none = new Button { Content = "None" };
                Host.Styled(none, "ChipButton");
                bulk.Children.Add(every);
                bulk.Children.Add(none);
                panel.Children.Add(bulk);

                var scroll = new ScrollViewer
                {
                    MaxHeight = 280,
                    VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                };
                var listing = new StackPanel();
                scroll.Content = listing;
                panel.Children.Add(scroll);
                var boxes = new List<(string Value, CheckBox Box)>();
                foreach (var value in choices)
                {
                    var box = new CheckBox
                    {
                        Content = value,
                        Margin = new Thickness(0, 2, 0, 2),
                        IsChecked = allowed == null || allowed.Contains(Raw(value)),
                    };
                    listing.Children.Add(box);
                    boxes.Add((value, box));
                }
                if (boxes.Count == 0)
                    listing.Children.Add(new TextBlock { Text = "Nothing on this tab to filter." });

                var actions = new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    HorizontalAlignment = HorizontalAlignment.Right,
                    Margin = new Thickness(0, 8, 0, 0),
                };
                var ok = new Button { Content = "OK", MinWidth = 64 };
                Host.Styled(ok, "PrimaryButton");
                ok.Margin = new Thickness(0, 0, 6, 0);
                var cancel = new Button { Content = "Cancel", MinWidth = 64 };
                Host.Styled(cancel, "ChipButton");
                actions.Children.Add(ok);
                actions.Children.Add(cancel);
                panel.Children.Add(actions);
                popup.Child = shell;

                // Into the heading's own panel, so the list is in the window's
                // logical tree and its DynamicResource colours resolve. A popup
                // floating free of it renders with no theme at all.
                var holder = button.Parent as Panel;

                List<CheckBox> Shown()
                {
                    return boxes.Where(pair => pair.Box.Visibility == Visibility.Visible)
                                .Select(pair => pair.Box).ToList();
                }

                search.TextChanged += (sender, args) =>
                {
                    string term = (search.Text ?? "").Trim().ToLowerInvariant();
                    foreach (var (value, box) in boxes)
                    {
                        box.Visibility = (term.Length == 0 || value.ToLowerInvariant().Contains(term))
                            ? Visibility.Visible
                            : Visibility.Collapsed;
                    }
                };
                every.Click += (sender, args) =>
                {
                    foreach (var box in Shown())
                        box.IsChecked = true;
                };
                none.Click += (sender, args) =>
                {
                    foreach (var box in Shown())
                        box.IsChecked = false;
                };
                ok.Click += (sender, args) =>
                {
                    var ticked = new HashSet<string>(boxes.Where(pair => pair.Box.IsChecked == true)
                                                          .Select(pair => Raw(pair.Value)), StringComparer.Ordinal);
                    popup.IsOpen = false;
                    // Everything ticked is no filter at all - not a filter that
                    // happens to allow everything, which would still hide a value
                    // that turns up later.
                    SetFilter(colId, ticked.Count == boxes.Count ? null : ticked);
                };
                cancel.Click += (sender, args) => popup.IsOpen = false;
                popup.Closed += (sender, args) =>
                {
                    try
                    {
                        holder.Children.Remove(popup);
                    }
                    catch (Exception)
                    {
                    }
                };

                // A popup's events bubble back through its logical parent - the
                // heading. Unhandled, a click on the list's background reaches
                // the heading, and a heading click on a revision column isolates
                // the drawings that carry it. The controls inside handle their
                // own clicks first; whatever is left stops here.
                shell.MouseLeftButtonDown += Swallow;
                shell.MouseLeftButtonUp += Swallow;
                try
                {
                    holder.Children.Add(popup);
                }
                catch (Exception)
                {
                }
                popup.IsOpen = true;
                try
                {
                    search.Focus();
                }
                catch (Exception)
                {
                }
            }

            /// <summary>Set or clear one column's filter, then re-take the view.</summary>
            public void SetFilter(string colId, IEnumerable<string> allowed)
            {
                if (allowed == null)
                    ColumnFilters.Remove(colId);
                else
                    ColumnFilters[colId] = new HashSet<string>(allowed, StringComparer.Ordinal);
                PaintFilterButton(colId);
                ApplyFilters();
                Say();
            }

            public void ClearFilters()
            {
                foreach (var colId in ColumnFilters.Keys.ToList())
                {
                    ColumnFilters.Remove(colId);
                    PaintFilterButton(colId);
                }
                ApplyFilters();
            }

            /// <summary>The Reset filters button: every column filter off at once, and
            /// any Isolate with it - a view narrowed to one revision is a filter
            /// too, and the one most easily forgotten.</summary>
            public void ResetFilters()
            {
                int count = ColumnFilters.Count + (Isolated.Count > 0 ? 1 : 0);
                Isolated = new List<string>();
                ClearFilters();
                Say();
                if (count > 0)
                    Host.Say(string.Format("{0} column filter{1} cleared.", count, Plural(count)));
                else
                    Host.Say("No column filters to clear.");
            }

            /// <summary>Live while any column is filtered, with how many in brackets.</summary>
            internal void PaintResetButton()
            {
                int count = ColumnFilters.Count + (Isolated.Count > 0 ? 1 : 0);
                if (ResetButton != null)
                {
                    try
                    {
                        ResetButton.IsEnabled = count > 0;
                    }
                    catch (Exception)
                    {
                    }
                }
                PsUi.SetText(ResetText, count > 0 ? string.Format("Reset filters ({0})", count) : "Reset filters");
            }

            internal Style CellStyle(string columnKey)
            {
                if (!Styles.TryGetValue(columnKey, out var style) || style == null)
                {
                    style = (Style)XamlReader.Parse(string.Format(PsRegView.CellStyle, PsRegView.Presentation, columnKey));
                    Styles[columnKey] = style;
                }
                return style;
            }

            internal Style CurrentStyle()
            {
                if (!Styles.TryGetValue("__current", out var style) || style == null)
                {
                    style = (Style)XamlReader.Parse(string.Format(PsRegView.CurrentStyle, PsRegView.Presentation));
                    Styles["__current"] = style;
                }
                return style;
            }

            internal Style CentredStyle()
            {
                if (!Styles.TryGetValue("__centred", out var style) || style == null)
                {
                    style = (Style)XamlReader.Parse(string.Format(PsRegView.CentredStyle, PsRegView.Presentation));
                    Styles["__centred"] = style;
                }
                return style;
            }

            // ==================================================================
            // fitting the columns to their text
            // ==================================================================

            /// <summary>The width of a piece of text in pixels, as WPF will draw it.</summary>
            internal double Measure(object text, double size = 12, bool bold = false)
            {
                string value = Str(text);
                if (value.Length == 0)
                    return 0;
                var key = (value, size, bold);
                if (Measures.TryGetValue(key, out double found))
                    return found;
                double width;
                try
                {
                    var block = new TextBlock
                    {
                        Text = value,
                        FontFamily = new FontFamily("Segoe UI"),
                        FontSize = size,
                        FontWeight = bold ? FontWeights.Bold : FontWeights.Normal,
                    };
                    block.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
                    width = block.DesiredSize.Width;
                    if (width <= 0)
                        throw new ArgumentException(value);
                }
                catch (Exception)
                {
                    // Off WPF, or anything odd: a fair estimate for Segoe UI.
                    width = value.Length * size * (bold ? 0.62 : 0.55);
                }
                Measures[key] = width;
                return width;
            }

            /// <summary>Every column as wide as its widest text, measured once per tab.
            ///
            /// Over every drawing on the tab, not only the ones showing, so a
            /// filter or a collapsed series does not make the columns jump.</summary>
            internal void FitColumns()
            {
                if (Columns.Count == 0)
                    return;
                var data = Table.Rows.Cast<DataRow>().Where(entry => !IsHeading(entry)).ToList();
                var heads = Table.Rows.Cast<DataRow>().Where(entry => IsHeading(entry)).ToList();
                foreach (var (colId, title, floor) in Identity)
                {
                    if (!Columns.TryGetValue(colId, out var column) || column == null || colId == "sel")
                        continue;
                    var widths = data.Select(entry => Measure(entry[colId])).ToList();
                    if (colId == "num")
                    {
                        // The series headings live in this column, in blue at 14pt
                        // bold. Fitting the column to them is what makes them
                        // readable; 1.20.0 cut them off at the drawing number's
                        // width.
                        widths.AddRange(heads.Select(entry => Measure(entry["num"], 14, true) + 4));
                    }
                    double header = Measure(title, 12, true);
                    int ceiling = Ceilings.TryGetValue(colId, out int ceil) ? ceil : DefaultCeiling;
                    SetWidth(column, PsRegister.ColumnWidth(widths, header, floor, ceiling));
                }
                FitRevisionColumns();
            }

            internal void FitRevisionColumns()
            {
                var data = Table.Rows.Cast<DataRow>().Where(entry => !IsHeading(entry)).ToList();
                foreach (var revision in UsedColumns)
                {
                    if (!Columns.TryGetValue(revision.Key, out var column) || column == null)
                        continue;
                    // Bold, because the current revision is drawn bold.
                    var widths = data.Select(entry => Measure(entry[revision.Key], 12, true)).ToList();
                    double header = Measure(revision.StatusLetter, 12, true);
                    SetWidth(column, PsRegister.ColumnWidth(widths, header, RevisionFloor, RevisionCeiling));
                }
            }

            internal void SetWidth(DataGridColumn column, double pixels)
            {
                try
                {
                    column.Width = new DataGridLength(pixels);
                }
                catch (Exception)
                {
                }
            }
        }
    }
}
