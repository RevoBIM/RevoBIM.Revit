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

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsRegView
    {
        public partial class RegisterView
        {
            // ==================================================================
            // heading colours (1.52.0)
            // ==================================================================

            /// <summary>The colour a heading wears in the current mode.</summary>
            public string ShownColour(string label, int level, string ramp)
            {
                string custom = null;
                if (label != null && HeadingCustom != null)
                    HeadingCustom.TryGetValue(label, out custom);
                return PsRamp.ModeColour(HeadingMode, ramp, level, Host.ThemeName, custom);
            }

            public void SetHeadingMode(string mode, bool quiet = false)
            {
                HeadingMode = PsRamp.HeadingMode(mode);
                Setting("reg_heading_mode", HeadingMode);
                PaintHeadingModeButton();
                if (Loaded)
                    SelectTab(TabIndex);
                if (quiet)
                    return;
                if (HeadingMode == PsRamp.Custom && HeadingCustom.Count == 0)
                {
                    Host.Say("Custom headers: right-click a heading to pick " +
                             "its colour. Until then they are grey.");
                }
                else
                {
                    Host.Say(string.Format("{0}.", PsRamp.ModeLabels[HeadingMode]));
                }
            }

            /// <summary>The header button: Coloured, Grey, Custom, round.</summary>
            public void CycleHeadingMode()
            {
                SetHeadingMode(PsRamp.NextMode(HeadingMode));
            }

            /// <summary>The mode's name. The button keeps its own colours
            /// (HeadingModeButton) whatever the mode.</summary>
            internal void PaintHeadingModeButton()
            {
                PsUi.SetText(HeadingModeText, PsRamp.ModeLabels.TryGetValue(HeadingMode, out var text) ? text : "");
            }

            /// <summary>Solid while frozen (the default); a plain chip while the rows
            /// scroll with the drawings.</summary>
            internal void PaintFreezeButton()
            {
                bool frozen = IssueFrozen;
                PsUi.SetText(FreezeText, frozen ? "Issue rows frozen" : "Issue rows scroll");
                if (FreezeButton != null)
                {
                    try
                    {
                        FreezeButton.SetResourceReference(FrameworkElement.StyleProperty,
                                                          frozen ? "SwitchButtonOn" : "ChipButton");
                        FreezeButton.Visibility = IssueFields.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            /// <summary>Frozen in the heading, or rows that scroll; remembered.</summary>
            public void ToggleIssueFrozen()
            {
                SetIssueFrozen(!IssueFrozen);
            }

            public void SetIssueFrozen(bool frozen)
            {
                IssueFrozen = frozen;
                PaintFreezeButton();
                if (Loaded)
                    SelectTab(TabIndex);
                Host.Say(IssueFrozen
                    ? "Issue Status, Issued To and Method frozen in the heading - they stay in view."
                    : "Issue Status, Issued To and Method are rows at " +
                      "the top of the drawings now, and scroll with them. " +
                      "Click a box to tick it, a status to type it.");
            }

            /// <summary>One heading's own colour; Custom headers from now on.</summary>
            public void SetHeadingColour(string label, string colour)
            {
                if (string.IsNullOrEmpty(label) || string.IsNullOrEmpty(colour))
                    return;
                HeadingCustom[label] = colour;
                SaveHeadingColours();
                if (HeadingMode != PsRamp.Custom)
                    SetHeadingMode(PsRamp.Custom, quiet: true);
                else
                    SelectTab(TabIndex);
                Host.Say(string.Format("\"{0}\" is now {1}. Custom headers - the button " +
                                       "cycles back to the trade colours.", label, colour));
            }

            internal void SaveHeadingColours()
            {
                try
                {
                    PsConfig.WriteHeadingColours(Host.Doc, HeadingCustom);
                }
                catch (Exception err)
                {
                    Host.Say(string.Format("The heading colours could not be saved: {0}", err.Message));
                }
                // One set of colours for both tabs: the Selection tab's groups too.
                try
                {
                    Host.TakeHeadingColours(HeadingCustom);
                }
                catch (Exception)
                {
                }
            }

            /// <summary>The project's heading colours, changed on the Selection tab.</summary>
            public void TakeHeadingColours(IDictionary<string, string> colours)
            {
                HeadingCustom = colours != null
                    ? new Dictionary<string, string>(colours, StringComparer.Ordinal)
                    : new Dictionary<string, string>(StringComparer.Ordinal);
                if (Loaded)
                    SelectTab(TabIndex);
            }

            public void CustomHeadingColour()
            {
                string label = MenuHeading;
                if (string.IsNullOrEmpty(label))
                    return;
                string typed = PsUi.AskText(
                    "Heading colour", string.Format("Colour for \"{0}\", as #RRGGBB:", label),
                    HeadingCustom.TryGetValue(label, out var now) ? now : "#", Host.ThemeName, Window);
                if (typed == null)
                    return;
                string colour = PsRamp.ParseHex(typed);
                if (colour == null)
                {
                    Host.Say(string.Format("\"{0}\" is not a colour - type six hex digits, like #3FA75A.", typed));
                    return;
                }
                SetHeadingColour(label, colour);
            }

            public void ResetHeadingColour()
            {
                string label = MenuHeading;
                if (label != null && HeadingCustom.ContainsKey(label))
                {
                    HeadingCustom.Remove(label);
                    SaveHeadingColours();
                    SelectTab(TabIndex);
                    Host.Say(string.Format("\"{0}\" is back to grey.", label));
                }
            }

            public void ResetHeadingColours()
            {
                if (HeadingCustom.Count == 0)
                    return;
                HeadingCustom = new Dictionary<string, string>(StringComparer.Ordinal);
                SaveHeadingColours();
                SelectTab(TabIndex);
                Host.Say("Every heading colour reset - they are grey again.");
            }

            /// <summary>A row of swatches inside the menu - menus here have no
            /// submenus. A click picks the colour and closes the menu.</summary>
            internal MenuItem SwatchItem(string text, ContextMenu menu)
            {
                var item = new MenuItem();
                Host.Styled(item, "ThemedMenuItem");
                item.StaysOpenOnClick = true;
                var panel = new StackPanel { Orientation = Orientation.Vertical };
                var title = new TextBlock { Text = text, Margin = new Thickness(0, 0, 0, 4) };
                panel.Children.Add(title);
                var wrap = new WrapPanel { Width = 6 * 24 };
                string label = MenuHeading;
                foreach (var colour in PsRamp.Swatches)
                {
                    var swatch = new Border
                    {
                        Width = 20,
                        Height = 20,
                        Margin = new Thickness(2),
                        CornerRadius = new CornerRadius(3),
                        BorderThickness = new Thickness(1),
                    };
                    swatch.SetResourceReference(Border.BorderBrushProperty, "EdgeBrush");
                    swatch.Background = PsTheme.Brush(colour);
                    swatch.ToolTip = colour;
                    swatch.Cursor = Cursors.Hand;
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

            /// <summary>Clouds left because they also show on sheets nobody picked.
            ///
            /// Not an error: the cloud is drawn in a view that is on more than one
            /// sheet, and a cloud is one element - Revit cannot change or delete it
            /// for one sheet only. So say which other sheets, and ask.</summary>
            internal bool AskShared(string mode,
                                    List<(string Sheet, string Revision, string Cloud, List<string> Others)> shared,
                                    string summary)
            {
                var byCell = new Dictionary<(string Sheet, string Old), (HashSet<string> Clouds, HashSet<string> Others)>();
                foreach (var (sheet, old, cloud, others) in shared)
                {
                    if (!byCell.TryGetValue((sheet, old), out var entry))
                    {
                        entry = (new HashSet<string>(StringComparer.Ordinal), new HashSet<string>(StringComparer.Ordinal));
                        byCell[(sheet, old)] = entry;
                    }
                    entry.Clouds.Add(cloud);
                    entry.Others.UnionWith(others ?? new List<string>());
                }
                var lines = new List<string>();
                foreach (var pair in byCell.OrderBy(pair => pair.Key.Sheet, StringComparer.Ordinal)
                                           .ThenBy(pair => pair.Key.Old, StringComparer.Ordinal))
                {
                    var (sheet, old) = pair.Key;
                    var (clouds, others) = pair.Value;
                    lines.Add(string.Format("{0}, {1}: {2} cloud{3}, also on {4}",
                                            SheetLabel(sheet), ElementLabel(old), clouds.Count, Plural(clouds.Count),
                                            string.Join(", ", others.Select(one => SheetLabel(one))
                                                                    .OrderBy(one => one, StringComparer.Ordinal))));
                }
                int count = shared.Select(one => one.Cloud).Distinct().Count();
                string verb = mode == "remove" ? "Remove" : "Change";
                string title = mode == "remove" ? "Remove revision"
                    : mode == "create" ? "Create new revision"
                    : "Change revision on sheet";
                string answer = new PsUi.Prompt(
                    title: title,
                    headline: string.Format("{0} cloud{1} also show{2} on sheets you did not pick.",
                                            count, Plural(count), count == 1 ? "s" : ""),
                    message: summary + string.Format("\n\nThese clouds are drawn in a view that " +
                                                     "is on those other sheets as well. A cloud is one " +
                                                     "element: Revit cannot {0} it for one sheet only, so " +
                                                     "{1} it {1}s it on every sheet it shows on.",
                                                     verb.ToLowerInvariant(),
                                                     mode == "remove" ? "removing" : "changing"),
                    detail: string.Join("\n", lines),
                    primary: string.Format("{0} on those sheets too", verb),
                    secondary: "Leave them",
                    themeName: Host.ThemeName, owner: Window).Show();
                return answer == "primary";
            }

            // ==================================================================
            // issue data under the revision headings (1.51.0)
            //
            // The Excel register's block - Issue Status, then Issued to and how -
            // as rows across the bottom of the headings: always in view, lined
            // up with their revisions, and editable. A tick or a status typed here
            // is staged like any other revision change: on the same Undo / Redo,
            // written by Apply revisions into the Revision Manager's columns (and
            // any parameter those are mapped to).
            // ==================================================================

            public const double BlockStatusHeight = 26;
            public const double BlockRowHeight = 21;
            public const double BlockFrame = 2;
            // The heading's own padding (RegisterHeader: 5,6,5,5), reached past
            // so the block runs edge to edge and onto the heading's bottom.
            public static readonly Thickness BlockMargin = new Thickness(-5, 6, -5, 6);
            // Every heading ends in a footer this tall - the drawing columns' name
            // and filter, a revision's letter and filter - so the block above it
            // sits level across them all.
            public const double FooterHeight = 50;

            /// <summary>The block's columns and what each revision has stored. Never
            /// raises: a model with nothing stored shows the default columns,
            /// empty.</summary>
            internal void ReadIssueData()
            {
                List<PsRevData.Column> columns;
                Dictionary<string, Dictionary<string, string>> byUid;
                try
                {
                    (columns, byUid) = PsRevData.Read(Host.Doc);
                }
                catch (Exception err)
                {
                    columns = new List<PsRevData.Column>();
                    byUid = new Dictionary<string, Dictionary<string, string>>();
                    Warnings.Add(string.Format("The issue data could not be read: {0}", err.Message));
                }
                IssueFields = PsRevData.IssueBlock(columns ?? new List<PsRevData.Column>());
                IssueStored = new Dictionary<(string Column, string Field), string>();
                IssueDerived = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (var revision in Revisions)
                {
                    Dictionary<string, string> row = null;
                    if (byUid != null && revision.Uid != null)
                        byUid.TryGetValue(revision.Uid, out row);
                    row = row ?? new Dictionary<string, string>();
                    foreach (var field in IssueFields)
                    {
                        row.TryGetValue(field.Id, out var value);
                        IssueStored[(revision.Key, field.Id)] = PsRevData.StoredValue(field, value);
                    }
                    IssueDerived[revision.Key] = PsRevisions.CommonStatus(
                        Rows.Where(one => one.Cells.TryGetValue(revision.Key, out var cell) && !string.IsNullOrEmpty(cell))
                            .Select(one => one.Status));
                }
            }

            /// <summary>Each row's height, in block order.</summary>
            internal List<double> BlockHeights()
            {
                return IssueFields.Select(field => field.Group == PsRevData.Status ? BlockStatusHeight : BlockRowHeight)
                                  .ToList();
            }

            /// <summary>The block sits in the heading: there is issue data, and it is
            /// frozen. Unfrozen it is rows of the table instead.</summary>
            public bool BlockShown()
            {
                return IssueFields.Count > 0 && IssueFrozen;
            }

            /// <summary>The whole block, frame included - every heading's bottom.</summary>
            public double BlockHeight()
            {
                if (!BlockShown())
                    return 0;
                return BlockHeights().Sum() + 2 * BlockFrame;
            }

            /// <summary>A heading's name and filter, at the foot, in a fixed height -
            /// directly above the drawings.</summary>
            internal Border Footer(FrameworkElement content)
            {
                var foot = new Border { Height = FooterHeight };
                try
                {
                    content.VerticalAlignment = VerticalAlignment.Bottom;
                }
                catch (Exception)
                {
                }
                foot.Child = content;
                return foot;
            }

            /// <summary>A drawing column's heading: room for the issue block at the
            /// same height as the revisions' block, then its name and filter at
            /// the foot, right above the drawings (1.52.0).</summary>
            internal StackPanel UnderBlock(FrameworkElement content, string colId = null)
            {
                var panel = new StackPanel { Orientation = Orientation.Vertical };
                if (BlockShown())
                {
                    var spacer = new Border { Height = BlockHeight(), Margin = BlockMargin };
                    panel.Children.Add(spacer);
                    if (colId != null)
                        BlockSpacers[colId] = spacer;
                }
                panel.Children.Add(Footer(content));
                return panel;
            }

            /// <summary>The block's outer edge: the Excel's medium line top and bottom,
            /// and down whichever sides close it. (Python _block_frame; named ...Core
            /// beside the BlockFrame constant.)</summary>
            internal (Border Frame, StackPanel Rows) BlockFrameCore(double left, double right)
            {
                var frame = new Border
                {
                    BorderThickness = new Thickness(left, BlockFrame, right, BlockFrame),
                    Margin = BlockMargin,
                };
                frame.SetResourceReference(Border.BorderBrushProperty, "MutedBrush");
                frame.SetResourceReference(Border.BackgroundProperty, "FieldBg");
                // A click on the block is its own: never the heading's include.
                frame.MouseLeftButtonDown += Swallow;
                frame.MouseLeftButtonUp += Swallow;
                var rows = new StackPanel { Orientation = Orientation.Vertical };
                frame.Child = rows;
                return (frame, rows);
            }

            /// <summary>One row of the block: a medium line under it between the
            /// Excel's sections, a thin one between rows of a group.</summary>
            internal Border BlockRow(double height, string edge, double right = 0)
            {
                var row = new Border { Height = height };
                double bottom = edge == "frame" ? BlockFrame : edge == "line" ? 1 : 0;
                row.BorderThickness = new Thickness(0, 0, right, bottom);
                row.SetResourceReference(Border.BorderBrushProperty, edge == "frame" ? "MutedBrush" : "GridLineBrush");
                return row;
            }

            internal static void Swallow(object sender, MouseButtonEventArgs args)
            {
                try
                {
                    args.Handled = true;
                }
                catch (Exception)
                {
                }
            }

            /// <summary>Issue Status:, then each Issued To and Issued Method name, right
            /// aligned against the revisions; the group named once beside its
            /// first row. Laid over the drawing headings' free space on the
            /// RegisterIssueLabels canvas (1.52.0) rather than in a column of its
            /// own: the names need more width than Rev Date has, and a column
            /// would be an empty strip down every drawing.</summary>
            internal void BuildIssueLabels()
            {
                LabelPlace = null;
                var canvas = LabelCanvas;
                if (canvas != null)
                {
                    try
                    {
                        canvas.Children.Clear();
                    }
                    catch (Exception)
                    {
                    }
                }
                LabelBlock = null;
                BuildBrand();
                if (!BlockShown() || canvas == null)
                    return;
                double widest = 0;
                var (frame, rows) = BlockFrameCore(BlockFrame, 0);
                frame.Margin = new Thickness(0);
                var edges = PsRevData.BlockEdges(IssueFields);
                var heights = BlockHeights();
                var groupSeen = new HashSet<string>(StringComparer.Ordinal);
                for (int index = 0; index < IssueFields.Count && index < edges.Count && index < heights.Count; index++)
                {
                    var field = IssueFields[index];
                    var row = BlockRow(heights[index], edges[index]);
                    var line = new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        HorizontalAlignment = HorizontalAlignment.Right,
                        VerticalAlignment = VerticalAlignment.Center,
                    };
                    string caption = "";
                    if (field.Group != PsRevData.Status && !groupSeen.Contains(field.Group ?? ""))
                    {
                        groupSeen.Add(field.Group ?? "");
                        caption = field.Group == PsRevData.IssuedTo ? "Issued to" : "Method";
                    }
                    if (caption.Length > 0)
                    {
                        var note = new TextBlock
                        {
                            Text = caption,
                            FontSize = 10,
                            FontWeight = FontWeights.Normal,
                            Margin = new Thickness(0, 0, 10, 0),
                            VerticalAlignment = VerticalAlignment.Center,
                        };
                        note.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush");
                        line.Children.Add(note);
                    }
                    var name = new TextBlock
                    {
                        Text = field.Name + (field.Group == PsRevData.Status ? ":" : ""),
                        FontWeight = FontWeights.Bold,
                        Margin = new Thickness(0, 0, 6, 0),
                        VerticalAlignment = VerticalAlignment.Center,
                    };
                    line.Children.Add(name);
                    row.Child = line;
                    if (field.Group == PsRevData.Status)
                    {
                        string legend = Host.Settings.Text("reg_legend", "") ?? "";
                        row.ToolTip = "Issue Status, per revision. Type one in " +
                                      "under a revision; a faint status is the one " +
                                      "most of its drawings carry.\n\n" +
                                      string.Join("\n", legend.Split('\t').Where(part => part.Length > 0));
                    }
                    else
                    {
                        PsRevData.GroupLabels.TryGetValue(field.Group ?? "", out var groupLabel);
                        row.ToolTip = string.Format("{0} - {1}. Tick under a revision; nothing " +
                                                    "is written until Apply revisions.",
                                                    groupLabel ?? "", field.Name);
                    }
                    rows.Children.Add(row);
                    widest = Math.Max(widest, Measure(caption, 10) + Measure(name.Text, 12, true) + 28);
                }
                LabelWidth = Math.Max(110, widest);
                frame.Width = LabelWidth;
                frame.Height = BlockHeight();
                frame.Visibility = Visibility.Hidden;
                LabelBlock = frame;
                try
                {
                    canvas.Children.Add(frame);
                }
                catch (Exception)
                {
                    LabelBlock = null;
                }
            }

            /// <summary>(left, top) for the names' block: its right edge on the drawing
            /// headings' right edge - against the revisions - level with the
            /// block. Null while the anchor is not on screen. Pure.</summary>
            public (double Left, double Top)? LabelSpot(double right, double top, double width, bool shown)
            {
                if (!shown || width <= 0)
                    return null;
                return (right - width, top);
            }

            /// <summary>The overlays on the heading: the names' block, then the
            /// register's name and logos in the space left of it.</summary>
            internal void PlaceIssueLabels(object sender = null, EventArgs args = null)
            {
                PlaceLabelBlock();
                PlaceBrand();
            }

            // ------------------------------------------- the name and logos

            public const double BrandTitleHeight = 30;

            /// <summary>The register's name over the company and client logos, from
            /// Settings - the Excel's title band, in the heading's free space.
            /// Frozen issue rows only: that is when the space is there to fill.
            /// Never hit-tested, so the headings under it still work.</summary>
            internal void BuildBrand()
            {
                Brand = null;
                BrandParts = null;
                BrandPlace = null;
                var canvas = LabelCanvas;
                if (canvas == null || !IssueFrozen)
                    return;
                var settings = Host.Settings;
                string title = settings.Text("reg_title", "") ?? "";
                var logos = new List<System.Windows.Media.Imaging.BitmapImage>();
                foreach (var key in new[] { "reg_logo", "reg_client_logo" })
                {
                    string path = settings.Text(key, "") ?? "";
                    if (path.Length > 0 && System.IO.File.Exists(path))
                    {
                        var bitmap = PsUi.LoadBitmap(path);
                        if (bitmap != null)
                            logos.Add(bitmap);
                    }
                }
                if (title.Length == 0 && logos.Count == 0)
                    return;
                var panel = new StackPanel { Orientation = Orientation.Vertical, IsHitTestVisible = false };
                var name = new TextBlock
                {
                    Text = title,
                    FontSize = 18,
                    FontWeight = FontWeights.Bold,
                    TextTrimming = TextTrimming.CharacterEllipsis,
                    Height = BrandTitleHeight,
                };
                name.SetResourceReference(TextBlock.ForegroundProperty, "BlueBrush");
                panel.Children.Add(name);
                var row = new StackPanel { Orientation = Orientation.Horizontal };
                var images = new List<Image>();
                foreach (var bitmap in logos)
                {
                    var image = new Image
                    {
                        Source = bitmap,
                        Stretch = Stretch.Uniform,
                        HorizontalAlignment = HorizontalAlignment.Left,
                        VerticalAlignment = VerticalAlignment.Top,
                        Margin = new Thickness(0, 0, 18, 0),
                    };
                    row.Children.Add(image);
                    images.Add(image);
                }
                panel.Children.Add(row);
                panel.Visibility = Visibility.Hidden;
                try
                {
                    canvas.Children.Add(panel);
                }
                catch (Exception)
                {
                    return;
                }
                Brand = panel;
                BrandParts = (name, row, images);
            }

            /// <summary>(left, top, width, height) for the name and logos: the drawing
            /// headings' free space above their names, up to the issue block (or
            /// the last drawing heading). Null when there is no room. Pure.</summary>
            public (double Left, double Top, double Width, double Height)? BrandBox(
                double left, double top, double height, double right, double footer, double margin = 8)
            {
                double boxLeft = left + margin;
                double boxTop = top + 6;
                double width = right - margin * 2 - left;
                double tall = height - footer - 6 - margin;
                if (width < 120 || tall < 40)
                    return null;
                return (boxLeft, boxTop, width, tall);
            }

            /// <summary>(width, height) each logo may take: the room under the name,
            /// split evenly between them; (0, 0) when nothing fits. Pure.</summary>
            public (double Width, double Height) LogoSize(double width, double height, int count, double titleHeight,
                                                          double gap = 18)
            {
                if (count == 0)
                    return (0.0, 0.0);
                double tall = height - titleHeight - 4;
                double wide = (width - gap * count) / count;
                if (tall < 20 || wide < 30)
                    return (0.0, 0.0);
                return (Math.Min(wide, 300.0), Math.Min(tall, 120.0));
            }

            /// <summary>The DataGridColumnHeader a drawing column's heading sits in.</summary>
            internal DataGridColumnHeader HeadingOfColumn(string colId)
            {
                Columns.TryGetValue(colId, out var column);
                var node = column != null ? column.Header as DependencyObject : null;
                for (int step = 0; step < 20; step++)
                {
                    if (node == null)
                        return null;
                    if (node is DataGridColumnHeader header)
                        return header;
                    try
                    {
                        node = VisualTreeHelper.GetParent(node);
                    }
                    catch (Exception)
                    {
                        return null;
                    }
                }
                return null;
            }

            internal static int Round(double value)
            {
                return (int)Math.Round(value, MidpointRounding.AwayFromZero);
            }

            internal void PlaceBrand()
            {
                var brand = Brand;
                if (brand == null || LabelCanvas == null)
                    return;
                var first = HeadingOfColumn(Identity[0].Id);
                var last = HeadingOfColumn(Identity[Identity.Count - 1].Id);
                (double Left, double Top, double Width, double Height)? box = null;
                try
                {
                    if (first != null && last != null && first.IsVisible)
                    {
                        var corner = first.TranslatePoint(new Point(0, 0), LabelCanvas);
                        var end = last.TranslatePoint(new Point(last.ActualWidth, 0), LabelCanvas);
                        double right = end.X;
                        if (LabelBlock != null && LabelPlace != null)
                            right = Math.Min(right, LabelPlace.Value.Left - 8);
                        box = BrandBox(corner.X, corner.Y, first.ActualHeight, right, FooterHeight);
                    }
                }
                catch (Exception)
                {
                    box = null;
                }
                (int Left, int Top, int Width, int Height)? place = null;
                if (box != null)
                    place = (Round(box.Value.Left), Round(box.Value.Top), Round(box.Value.Width), Round(box.Value.Height));
                if (Nullable.Equals(place, BrandPlace))
                    return;
                BrandPlace = place;
                try
                {
                    if (place == null)
                    {
                        brand.Visibility = Visibility.Hidden;
                        return;
                    }
                    var (left, top, width, height) = place.Value;
                    var (name, row, images) = BrandParts.Value;
                    brand.Width = width;
                    brand.Height = height;
                    name.MaxWidth = width;
                    var (wide, tall) = LogoSize(width, height, images.Count, BrandTitleHeight);
                    foreach (var image in images)
                    {
                        image.MaxWidth = wide;
                        image.MaxHeight = tall;
                        image.Visibility = wide != 0 ? Visibility.Visible : Visibility.Collapsed;
                    }
                    Canvas.SetLeft(brand, left);
                    Canvas.SetTop(brand, top);
                    brand.Visibility = Visibility.Visible;
                }
                catch (Exception)
                {
                }
            }

            /// <summary>Keep the names' block on the last drawing heading's spacer.
            /// LayoutUpdated fires constantly, so it only moves on a change.</summary>
            internal void PlaceLabelBlock()
            {
                var block = LabelBlock;
                Border anchor = null;
                if (BlockSpacers.Count > 0)
                    BlockSpacers.TryGetValue(Identity[Identity.Count - 1].Id, out anchor);
                if (block == null || anchor == null || LabelCanvas == null)
                    return;
                (double Left, double Top)? spot;
                try
                {
                    bool shown = anchor.IsVisible && anchor.ActualWidth > 0;
                    var corner = anchor.TranslatePoint(new Point(anchor.ActualWidth, 0), LabelCanvas);
                    spot = LabelSpot(corner.X, corner.Y, LabelWidth, shown);
                }
                catch (Exception)
                {
                    spot = null;
                }
                (int Left, int Top)? place = null;
                if (spot != null)
                    place = (Round(spot.Value.Left), Round(spot.Value.Top));
                if (Nullable.Equals(place, LabelPlace))
                    return;
                LabelPlace = place;
                try
                {
                    if (place == null)
                    {
                        block.Visibility = Visibility.Hidden;
                        return;
                    }
                    Canvas.SetLeft(block, place.Value.Left);
                    Canvas.SetTop(block, place.Value.Top);
                    block.Visibility = Visibility.Visible;
                }
                catch (Exception)
                {
                }
            }

            /// <summary>One revision's part of the block: its Issue Status in a box to
            /// type into, a tick per Issued To and Method column.</summary>
            internal Border IssuePiece(PsRegister.RevisionColumn revision)
            {
                var (frame, rows) = BlockFrameCore(0, 1);
                var edges = PsRevData.BlockEdges(IssueFields);
                var heights = BlockHeights();
                for (int index = 0; index < IssueFields.Count && index < edges.Count && index < heights.Count; index++)
                {
                    var field = IssueFields[index];
                    var row = BlockRow(heights[index], edges[index]);
                    var cell = (revision.Key, field.Id);
                    Control control;
                    if (field.Group == PsRevData.Status)
                    {
                        var box = new TextBox
                        {
                            MinHeight = 0,
                            Padding = new Thickness(1, 0, 1, 0),
                            Margin = new Thickness(2, 2, 2, 2),
                            FontWeight = FontWeights.Bold,
                            HorizontalContentAlignment = HorizontalAlignment.Center,
                        };
                        box.SetResourceReference(Control.BorderBrushProperty, "GridLineBrush");
                        box.Background = Brushes.Transparent;
                        box.Tag = IssueDerived.TryGetValue(revision.Key, out var derived) ? derived : "";
                        box.ToolTip = string.Format("Issue Status for {0}. Type it and press " +
                                                    "Enter; staged until Apply revisions.",
                                                    Labels(new[] { revision.Key }));
                        box.LostKeyboardFocus += MakeStatusDone(cell);
                        box.KeyDown += MakeStatusKey(cell);
                        control = box;
                    }
                    else
                    {
                        var tick = new CheckBox();
                        Host.Styled(tick, "GridCheckBox");
                        tick.HorizontalAlignment = HorizontalAlignment.Center;
                        tick.VerticalAlignment = VerticalAlignment.Center;
                        tick.ToolTip = string.Format("{0} - {1}", field.Name, Labels(new[] { revision.Key }));
                        tick.Click += MakeIssueTick(cell);
                        control = tick;
                    }
                    row.Child = control;
                    IssueCells[cell] = control;
                    IssueRows[cell] = row;
                    rows.Children.Add(row);
                }
                IssuePieces[revision.Key] = frame;
                return frame;
            }

            internal void ForgetIssuePiece(string columnKey)
            {
                if (IssueCells == null || IssueCells.Count == 0)
                    return;
                IssuePieces.Remove(columnKey);
                foreach (var cell in IssueCells.Keys.Where(one => one.Column == columnKey).ToList())
                {
                    IssueCells.Remove(cell);
                    IssueRows.Remove(cell);
                }
            }

            /// <summary>The last revision's piece closes the frame on the right.</summary>
            internal void PaintIssueEdges()
            {
                string last = UsedColumns.Count > 0 ? UsedColumns[UsedColumns.Count - 1].Key : null;
                foreach (var pair in IssuePieces ?? new Dictionary<string, Border>())
                {
                    try
                    {
                        pair.Value.BorderThickness = new Thickness(0, BlockFrame, pair.Key == last ? BlockFrame : 1,
                                                                   BlockFrame);
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }

            /// <summary>{(column key, field id): value} - stored, with staged edits.</summary>
            public Dictionary<(string Column, string Field), string> IssueValues()
            {
                return PsRegister.MetaValues(IssueStored, Pending.Edits);
            }

            /// <summary>Every tick and status as stored-plus-staged; a staged one washed
            /// green. A box being typed in is left alone.</summary>
            internal void PaintIssueBlock()
            {
                if (IssueCells == null || IssueCells.Count == 0)
                    return;
                var values = IssueValues();
                var changed = PsRegister.MetaChanged(IssueStored, Pending.Edits);
                IssuePainting = true;
                try
                {
                    foreach (var pair in IssueCells)
                    {
                        var cell = pair.Key;
                        var control = pair.Value;
                        string value = values.TryGetValue(cell, out var found) ? found : "";
                        try
                        {
                            if (control is CheckBox box)
                                box.IsChecked = value == "1";
                            else if (control is TextBox text && !text.IsKeyboardFocusWithin)
                                text.Text = value;
                        }
                        catch (Exception)
                        {
                        }
                        if (!IssueRows.TryGetValue(cell, out var row) || row == null)
                            continue;
                        try
                        {
                            if (changed.Contains(cell))
                                row.SetResourceReference(Border.BackgroundProperty, "GreenWashBrush");
                            else
                                row.ClearValue(Border.BackgroundProperty);
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
                finally
                {
                    IssuePainting = false;
                }
            }

            internal PsRevData.Column Field(string fieldId)
            {
                foreach (var field in IssueFields)
                {
                    if (field.Id == fieldId)
                        return field;
                }
                return null;
            }

            /// <summary>Stage one issue data value. Returns the edit, or null when it
            /// changes nothing or the column refuses it.</summary>
            public PsRegister.PendingEdit StageIssue((string Column, string Field) cell, string value)
            {
                var field = Field(cell.Field);
                if (field == null)
                    return null;
                var (ok, stored) = PsRevData.Normalise(field, value);
                if (!ok)
                {
                    Host.Say(stored);
                    PaintIssueBlock();
                    return null;
                }
                stored = PsRevData.StoredValue(field, stored);
                if ((IssueValues().TryGetValue(cell, out var now) ? now : "") == stored)
                    return null;
                var edit = new PsRegister.PendingEdit
                {
                    Kind = PsRegister.Meta,
                    Target = cell.Column,
                    Field = cell.Field,
                    Value = stored,
                };
                Stage(edit);
                return edit;
            }

            internal RoutedEventHandler MakeIssueTick((string Column, string Field) cell)
            {
                return (sender, args) =>
                {
                    if (IssuePainting)
                        return;
                    bool ticked;
                    try
                    {
                        ticked = ((CheckBox)sender).IsChecked == true;
                    }
                    catch (Exception)
                    {
                        return;
                    }
                    StageIssue(cell, ticked ? "1" : "0");
                };
            }

            internal KeyboardFocusChangedEventHandler MakeStatusDone((string Column, string Field) cell)
            {
                return (sender, args) =>
                {
                    if (IssuePainting)
                        return;
                    string text;
                    try
                    {
                        text = ((TextBox)sender).Text ?? "";
                    }
                    catch (Exception)
                    {
                        return;
                    }
                    StageIssue(cell, text);
                };
            }

            /// <summary>Enter stages what was typed; Escape puts the value back.</summary>
            internal KeyEventHandler MakeStatusKey((string Column, string Field) cell)
            {
                return (sender, args) =>
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
                    var box = (TextBox)sender;
                    if (key == Key.Enter || key == Key.Return)
                    {
                        StageIssue(cell, box.Text ?? "");
                        try
                        {
                            Keyboard.ClearFocus();
                        }
                        catch (Exception)
                        {
                        }
                        args.Handled = true;
                    }
                    else if (key == Key.Escape)
                    {
                        try
                        {
                            box.Text = IssueValues().TryGetValue(cell, out var now) ? now : "";
                            Keyboard.ClearFocus();
                        }
                        catch (Exception)
                        {
                        }
                        args.Handled = true;
                    }
                };
            }

            // ---------------------------------------------- unfrozen: as rows

            /// <summary>What an issue data row shows in a revision's cell: the status
            /// as typed, or an x for a tick - the Excel's mark.</summary>
            public string IssueCellText(PsRevData.Column field, string value)
            {
                if (field.Kind == "yesno")
                    return value == "1" ? "x" : "";
                return value ?? "";
            }

            /// <summary>The issue data as the first rows of the tab: the group named in
            /// Drawing No, the column in Drawing Title, a value per revision.</summary>
            internal void AddIssueRows()
            {
                var edges = PsRevData.BlockEdges(IssueFields);
                var seen = new HashSet<string>(StringComparer.Ordinal);
                for (int index = 0; index < IssueFields.Count; index++)
                {
                    var field = IssueFields[index];
                    var entry = Table.NewRow();
                    entry["key"] = PsRegView.IssuePrefix + field.Id;
                    string caption = "";
                    if (field.Group != PsRevData.Status && !seen.Contains(field.Group ?? ""))
                    {
                        seen.Add(field.Group ?? "");
                        caption = field.Group == PsRevData.IssuedTo ? "Issued to" : "Issued method";
                    }
                    entry["num"] = caption;
                    entry["name"] = field.Name + (field.Group == PsRevData.Status ? ":" : "");
                    entry["ishead"] = "0";
                    entry["hid"] = "-1";
                    entry["glabel"] = "";
                    entry["gpath"] = "";
                    entry["gcolor"] = "";
                    // Which line runs under it: see PaintIssueRow.
                    string edge = index < edges.Count ? edges[index] : null;
                    entry["level"] = string.IsNullOrEmpty(edge) ? "last" : edge;
                    entry["vis"] = "1";
                    entry["show"] = "1";
                    entry["hidetick"] = "1";
                    // Ticked, though the tick is hidden: an unticked row is drawn
                    // muted (RegisterCell), and these are never out of anything.
                    entry["sel"] = true;
                    // Before every heading: '!' sorts ahead of the digits.
                    entry["ord"] = "!" + index.ToString("000", Inv);
                    Table.Rows.Add(entry);
                }
            }

            /// <summary>The issue rows' values - stored plus staged - and a green wash
            /// (the s_ flag "add") on a staged one.</summary>
            internal void PaintIssueRows()
            {
                if (IssueFields == null || IssueFields.Count == 0 || IssueFrozen)
                    return;
                var values = IssueValues();
                var changed = PsRegister.MetaChanged(IssueStored, Pending.Edits);
                var fields = new Dictionary<string, PsRevData.Column>(StringComparer.Ordinal);
                foreach (var field in IssueFields)
                    fields[field.Id] = field;
                bool was = Suspend;
                Suspend = true;
                try
                {
                    foreach (DataRow entry in Table.Rows)
                    {
                        if (!IsIssue(entry))
                            continue;
                        if (!fields.TryGetValue(Str(entry["key"]).Substring(PsRegView.IssuePrefix.Length), out var field))
                            continue;
                        foreach (var revision in Revisions)
                        {
                            var cell = (revision.Key, field.Id);
                            string text = IssueCellText(field, values.TryGetValue(cell, out var value) ? value : "");
                            string flag = changed.Contains(cell) ? PsRegister.PendingAdd : "";
                            try
                            {
                                if (Str(entry[revision.Key]) != text)
                                    entry[revision.Key] = text;
                                if (Str(entry[PsRegView.PendingPrefix + revision.Key]) != flag)
                                    entry[PsRegView.PendingPrefix + revision.Key] = flag;
                            }
                            catch (Exception)
                            {
                                continue;
                            }
                        }
                    }
                }
                finally
                {
                    Suspend = was;
                }
            }

            /// <summary>A click in an issue row: a tick flips, a status is asked for.
            /// Staged either way, like a tick in the frozen heading.</summary>
            internal void IssueRowClick(DataRow entry, string columnKey)
            {
                if (!PsRegister.IsColumnKey(columnKey))
                    return;
                var field = Field(Str(entry["key"]).Substring(PsRegView.IssuePrefix.Length));
                if (field == null)
                    return;
                var cell = (columnKey, field.Id);
                string now = IssueValues().TryGetValue(cell, out var found) ? found : "";
                if (field.Kind == "yesno")
                {
                    StageIssue(cell, now == "1" ? "0" : "1");
                    return;
                }
                string legend = Host.Settings.Text("reg_legend", "") ?? "";
                string typed = PsUi.AskText(
                    "Issue Status",
                    string.Format("{0} for {1}:{2}", field.Name, Labels(new[] { columnKey }),
                                  legend.Length > 0
                                      ? "\n" + string.Join("   ", legend.Split('\t').Where(part => part.Length > 0))
                                      : ""),
                    now.Length > 0 ? now : (IssueDerived.TryGetValue(columnKey, out var derived) ? derived : ""),
                    Host.ThemeName, Window);
                if (typed == null)
                    return;
                StageIssue(cell, typed);
            }

            /// <summary>An issue row as the Excel block: the field colour, bold, the
            /// medium line under Issue Status and between the groups, a thin one
            /// between rows. Every other row has its line cleared - containers
            /// are recycled. True when the row was an issue row.</summary>
            internal bool PaintIssueRow(DataGridRow row, DataRow entry)
            {
                if (!IsIssue(entry))
                {
                    try
                    {
                        row.ClearValue(Control.BorderThicknessProperty);
                        row.ClearValue(Control.BorderBrushProperty);
                    }
                    catch (Exception)
                    {
                    }
                    return false;
                }
                string edge = Str(entry["level"]);
                bool first = Str(entry["ord"]) == "!000";
                try
                {
                    row.SetResourceReference(Control.BackgroundProperty, "FieldBg");
                    row.FontWeight = FontWeights.Bold;
                    row.BorderThickness = new Thickness(0, first ? BlockFrame : 0, 0, edge == "line" ? 1 : BlockFrame);
                    row.SetResourceReference(Control.BorderBrushProperty, edge == "line" ? "GridLineBrush" : "MutedBrush");
                }
                catch (Exception)
                {
                }
                return true;
            }

            internal string DescribeMeta(PsRegister.PendingEdit edit)
            {
                var field = Field(edit.Field);
                string name = field != null ? field.Name : edit.Field;
                string value = edit.Value ?? "";
                if (field != null && field.Kind == "yesno")
                {
                    string shown = value == "1" ? "ticked" : "unticked";
                    return string.Format("{0} {1} on {2}", name, shown, Labels(new[] { edit.Target }));
                }
                return string.Format("{0} on {1} set to {2}", name, Labels(new[] { edit.Target }),
                                     value.Length > 0 ? value : "(blank)");
            }

            /// <summary>The staged issue data as the store takes it: [(revision uid,
            /// column id, value)], and every revision's element key by uid for
            /// the parameter push.</summary>
            internal (List<(string Uid, string ColumnId, object Value)> Changes, Dictionary<string, long> KeysByUid)
                IssueChanges(IEnumerable<PsRegister.PendingEdit> edits)
            {
                var uids = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (var revision in Revisions)
                    uids[revision.Key] = revision.Uid;
                var changes = edits.Select(edit => (
                    (edit.Target != null && uids.TryGetValue(edit.Target, out var uid)) ? (uid ?? "") : "",
                    edit.Field,
                    (object)(edit.Value ?? ""))).ToList();
                var keysByUid = new Dictionary<string, long>(StringComparer.Ordinal);
                foreach (var revision in Revisions)
                {
                    if (!string.IsNullOrEmpty(revision.Uid))
                        keysByUid[revision.Uid] = revision.ElementKey;
                }
                return (changes, keysByUid);
            }
        }
    }
}
