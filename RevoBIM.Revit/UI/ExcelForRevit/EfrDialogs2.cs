// Port of efr_core.py lines 4327-4979: the highlight, export, import-report, column tick-filter
// and Set Level dialogs, plus the small module helpers that follow them (sort_level_colour,
// scroll_rate, cell_of, walk_up) and the drag auto-scroll / autofit constants.
//
// Window members used (by the naming rule, owned by the ExcelForRevitWindow parts):
//   host.Window, host.Model, host.Doc, host.HlSettings (Dictionary<string,string>),
//   host.ColPicks (Dictionary<int, HashSet<string>>), host.SelCells(), host.SelectedRows(),
//   host.ApplyHighlight(colour, mode, scope) -> int, host.ClearHighlight(string) -> int,
//   host.SetStatus(string), host.ExportPayload() -> (List<ExportField>, List<ExportRow>),
//   host.ColumnValues(fi) -> list of (value, count), host.ColumnValuesLimited(fi) -> int,
//   host.StaleRows() -> int, host.ApplyFilters(), host.LevelOfRow(ridx) -> eid value or null,
//   host.StageLevels(rows, level) -> int.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using Level = Autodesk.Revit.DB.Level;
using RevoBIM.Tools.ExcelForRevit;
using static RevoBIM.Tools.ExcelForRevit.Efr;
using WGrid = System.Windows.Controls.Grid;
using WBorder = System.Windows.Controls.Border;

namespace RevoBIM.UI.ExcelForRevit
{
    public static partial class EfrUi
    {
        // ------------------------------------------------------- drag auto-scroll ----
        //
        // Excel scrolls while you hold a drag past the edge of the grid, and the further
        // past you go the faster it runs. The curve: nothing inside a small dead zone, a
        // gentle rate the moment you cross it, then accelerating to a fast rate over a
        // couple of hundred pixels. Rates are rows per second, so they are independent of
        // the timer interval, and the leftover fraction is carried between ticks (otherwise
        // a rate below one row per tick would round to zero and never scroll at all).

        public const double EDGE_INSET = 8.0;            // start scrolling just inside the edge, like Excel

        public const double AUTOFIT_MIN = 124.0;         // a header carries a filter box, a caret and an outline
        public const double AUTOFIT_MAX = 380.0;         // one long comments field must not push the rest off
        public const double AUTOFIT_PAD = 8.0;           // breathing room either side of the measured text

        public const double SNAP_BREAK_PX = 6.0;         // slack before a drag undoes a vertical snap

        public const int SCROLL_TICK_MS = 33;            // ~30 a second, smooth without being busy
        public const double SCROLL_DEAD_PX = 4.0;        // slack so a drag along the edge does not creep
        public const double SCROLL_MIN_RATE = 7.0;       // rows a second just past the edge
        public const double SCROLL_MAX_RATE = 95.0;      // rows a second when dragged well past it
        public const double SCROLL_RAMP_PX = 200.0;      // distance over which it reaches full speed
        public const double SCROLL_CURVE = 1.45;         // >1 keeps the slow end fine and the fast end fast

        // Each level of a sort gets its own colour, resolved at paint time so it follows the
        // theme. Orange is the primary because that is the accent the rest of the tool uses
        // for "this is the one that matters".
        public static readonly string[] SORT_LEVEL_COLOURS =
            { "C_ORANGE", "C_BLUE", "C_GREEN", "C_TEST_FG", "C_IMP_FG", "C_COPY_FG" };
        public const int SORT_LEVEL_MAX = 6;

        public static string SortLevelColour(int level)
        {
            string name = SORT_LEVEL_COLOURS[((level % SORT_LEVEL_COLOURS.Length) + SORT_LEVEL_COLOURS.Length)
                                             % SORT_LEVEL_COLOURS.Length];
            switch (name)
            {
                case "C_ORANGE": return C_ORANGE;
                case "C_BLUE": return C_BLUE;
                case "C_GREEN": return C_GREEN;
                case "C_TEST_FG": return C_TEST_FG;
                case "C_IMP_FG": return C_IMP_FG;
                case "C_COPY_FG": return C_COPY_FG;
                default: return "#E8912D";
            }
        }

        /// <summary>Rows per second for a pointer this many pixels past the grid edge.</summary>
        public static double ScrollRate(double overshoot)
        {
            double distance = Math.Abs(overshoot);
            if (double.IsNaN(distance) || double.IsInfinity(distance))
                return 0.0;
            if (distance <= SCROLL_DEAD_PX)
                return 0.0;
            double t = (distance - SCROLL_DEAD_PX) / SCROLL_RAMP_PX;
            if (t > 1.0)
                t = 1.0;
            return SCROLL_MIN_RATE + (SCROLL_MAX_RATE - SCROLL_MIN_RATE) * Math.Pow(t, SCROLL_CURVE);
        }

        // ------------------------------------------------------------ visual tree ----

        /// <summary>DataGridCell that owns a generated cell element.</summary>
        public static DataGridCell CellOf(DependencyObject content)
        {
            if (content == null)
                return null;
            try
            {
                var fe = content as FrameworkElement;
                if (fe != null)
                {
                    var cell = fe.Parent as DataGridCell;
                    if (cell != null)
                        return cell;
                }
            }
            catch (Exception)
            {
            }
            return WalkUp<DataGridCell>(content);
        }

        /// <summary>The element itself or its nearest visual ancestor of type T (at most 60 steps up).</summary>
        public static T WalkUp<T>(DependencyObject element) where T : DependencyObject
        {
            return WalkUp(element, typeof(T)) as T;
        }

        public static DependencyObject WalkUp(DependencyObject element, Type wanted)
        {
            DependencyObject node = element;
            int guard = 0;
            while (node != null && guard < 60)
            {
                if (wanted.IsInstanceOfType(node))
                    return node;
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

        // -------------------------------------------------------------- highlight ----

        /// <summary>Colour cells, whole rows or whole columns. Keyed on the data, not the view.</summary>
        public static void HighlightDialog(ExcelForRevitWindow host)
        {
            var dlg = new ThemedDialog("Highlight", 560, null, host.Window, C_ORANGE);
            var cells = host.SelCells();

            dlg.Add(Tb("Highlights are held against the element and the column, so they "
                       + "stay with the data when the grid is filtered, sorted or "
                       + "reloaded. They are a working aid — nothing is written to the "
                       + "model, and a staged edit or a refusal still shows through.",
                       C_TEXT, 12, false, true));

            var saved = host.HlSettings ?? new Dictionary<string, string>();
            var state = new Dictionary<string, string>
            {
                { "colour", SavedOr(saved, "colour", "Yellow") },
                { "mode", SavedOr(saved, "mode", "fill") },
                { "scope", SavedOr(saved, "scope", "cells") },
            };

            var swatchRow = new WrapPanel();
            swatchRow.Margin = new Thickness(0, 12, 0, 0);
            var swatches = new Dictionary<string, WBorder>();

            Action<string> selectColour = name =>
            {
                state["colour"] = name;
                foreach (var kv in swatches)
                {
                    kv.Value.BorderThickness = new Thickness(kv.Key == name ? 3 : 1);
                    kv.Value.BorderBrush = Brush(kv.Key == name ? C_TEXT : C_EDGE);
                }
            };

            Func<string, WBorder> makeSwatch = name =>
            {
                var hc = HighlightColours(name);
                var b = new WBorder();
                b.Background = Brush(hc.Bg);
                b.BorderBrush = Brush(C_EDGE);
                b.BorderThickness = new Thickness(1);
                b.CornerRadius = new CornerRadius(3);
                b.Width = 60;
                b.Height = 34;
                b.Margin = new Thickness(0, 0, 6, 6);
                b.Cursor = Cursors.Hand;
                TextBlock label = Tb(name, hc.Fg, 11, true);
                label.HorizontalAlignment = HorizontalAlignment.Center;
                label.VerticalAlignment = VerticalAlignment.Center;
                b.Child = label;
                b.MouseLeftButtonUp += (sender, args) => selectColour(name);
                swatches[name] = b;
                return b;
            };

            foreach (string name in HIGHLIGHT_COLOURS)
                swatchRow.Children.Add(makeSwatch(name));
            dlg.Add(FieldRow("Colour", swatchRow));
            selectColour(state["colour"]);

            Func<string, string[][], string, StackPanel> radioGroup = (label, options, key) =>
            {
                var panel = new StackPanel();
                panel.Orientation = Orientation.Horizontal;
                foreach (string[] opt in options)
                {
                    string value = opt[0];
                    var rb = new RadioButton();
                    rb.Content = opt[1];
                    rb.Foreground = Brush(C_TEXT);
                    rb.Margin = new Thickness(0, 0, 16, 0);
                    rb.GroupName = key;
                    rb.IsChecked = (state[key] == value);
                    rb.Checked += (sender, args) => { state[key] = value; };
                    panel.Children.Add(rb);
                }
                return panel;
            };

            dlg.Add(FieldRow("Apply to", radioGroup("Apply to", new[]
            {
                new[] { "cells", "Selected cells" },
                new[] { "rows", "Whole rows" },
                new[] { "cols", "Whole columns" },
            }, "scope")));
            dlg.Add(FieldRow("Style", radioGroup("Style", new[]
            {
                new[] { "fill", "Fill" },
                new[] { "text", "Text colour" },
                new[] { "both", "Fill and text" },
            }, "mode")));

            int cellCount = cells.Count();
            TextBlock count = Tb(string.Format(CultureInfo.InvariantCulture, "{0} cell{1} selected.",
                                               cellCount, cellCount == 1 ? "" : "s"),
                                 C_MUTED, 11, false, true);
            count.Margin = new Thickness(0, 12, 0, 0);
            dlg.Add(count);

            Action doApply = () =>
            {
                host.HlSettings = new Dictionary<string, string>(state);
                int n = host.ApplyHighlight(state["colour"], state["mode"], state["scope"]);
                if (n != 0)
                {
                    string scope = state["scope"];
                    string noun = scope == "cells" ? "cell" : scope == "rows" ? "row" : "column";
                    host.SetStatus(string.Format(CultureInfo.InvariantCulture, "Highlighted {0} {1}{2} in {3}.",
                                                 n, noun, n == 1 ? "" : "s", state["colour"].ToLowerInvariant()));
                }
            };

            Action doClearSel = () =>
            {
                int n = host.ClearHighlight("selection");
                host.SetStatus(string.Format(CultureInfo.InvariantCulture, "Cleared {0} highlight{1}.",
                                             n, n == 1 ? "" : "s"));
            };

            Action doClearAll = () =>
            {
                int n = host.ClearHighlight("all");
                host.SetStatus(string.Format(CultureInfo.InvariantCulture, "Cleared all {0} highlight{1}.",
                                             n, n == 1 ? "" : "s"));
            };

            dlg.AddButton("Close", "ghost", "close");
            dlg.AddButton("Clear all", "red", null, false, doClearAll);
            dlg.AddButton("Clear from selection", "orange", null, false, doClearSel);
            dlg.AddButton("Highlight", "green", null, false, doApply);
            dlg.Show();
        }

        private static string SavedOr(Dictionary<string, string> saved, string key, string fallback)
        {
            string v;
            return saved.TryGetValue(key, out v) && v != null ? v : fallback;
        }

        // ----------------------------------------------------------------- export ----

        /// <summary>Pick which of the two exports, then Save As.</summary>
        public static void ExportDialog(ExcelForRevitWindow host)
        {
            if (!string.IsNullOrEmpty(ExcelError))
            {
                ThemedMessage("Export to Excel",
                              "The Excel module could not be loaded:\n\n" + ExcelError,
                              host.Window, C_RED, 680);
                return;
            }

            var dlg = new ThemedDialog("Export to Excel", 680, null, host.Window, C_ORANGE);
            dlg.Add(Tb("Two exports, for two different jobs.", C_TEXT, 12, false, true));

            string kindSaved = GetString(LoadSettings(), "excel_export_kind", "round");
            var state = new Dictionary<string, string> { { "kind", string.IsNullOrEmpty(kindSaved) ? "round" : kindSaved } };
            var picks = new Dictionary<string, WBorder>();

            Action<string> choose = kind =>
            {
                state["kind"] = kind;
                foreach (var kv in picks)
                {
                    bool on = (kv.Key == kind);
                    kv.Value.BorderBrush = Brush(on ? C_GREEN : C_EDGE);
                    kv.Value.BorderThickness = new Thickness(on ? 2 : 1);
                    kv.Value.Background = Brush(on ? C_EDIT_BG : C_FIELD);
                }
            };

            Func<string, string, string, WBorder> card = (kind, title, lines) =>
            {
                var b = new WBorder();
                b.CornerRadius = new CornerRadius(4);
                b.Padding = new Thickness(12, 10, 12, 10);
                b.Margin = new Thickness(0, 10, 0, 0);
                b.Cursor = Cursors.Hand;
                var stack = new StackPanel();
                stack.Children.Add(Tb(title, C_TEXT, 13, true));
                TextBlock body = Tb(lines, C_MUTED, 11.5, false, true);
                body.Margin = new Thickness(0, 5, 0, 0);
                stack.Children.Add(body);
                b.Child = stack;
                b.MouseLeftButtonUp += (sender, args) => choose(kind);
                picks[kind] = b;
                return b;
            };

            dlg.Add(card("round", "Round trip — edit in Excel and bring it back",
                         "A flat list with a Revit ID column, filters on, and every value "
                         + "column coloured the way this grid colours it: blue for instance "
                         + "parameters, orange for type parameters, red for anything read "
                         + "only. Sort and filter it in Excel as much as you like — rows "
                         + "come back matched on the Revit ID, not on their position. A "
                         + "second sheet carries the legend."));
            dlg.Add(card("clean", "Presentation — a clean sheet to issue",
                         "Title band, headers, borders, banded rows, column widths sized "
                         + "to the content and text wrapped where it needs to be. Numbers "
                         + "come through as numbers so Excel can total them. One "
                         + "direction only: it carries no Revit IDs and cannot be "
                         + "imported back."));
            choose(state["kind"]);

            dlg.AddButton("Cancel", "ghost", "cancel");
            dlg.AddButton("Choose a location...", "green", "go");
            if (dlg.ResultTextAfterShow() != "go")
                return;

            string kindPicked = state["kind"];
            SaveSettings(new Dictionary<string, object> { { "excel_export_kind", kindPicked } });
            ScheduleModel model = host.Model;
            string name = ElemName(model.Sched);
            string suffix = kindPicked == "clean" ? "" : " (editable)";
            string path = AskSavePath(name + suffix);
            if (string.IsNullOrEmpty(path))
                return;
            if (!path.ToLowerInvariant().EndsWith(".xlsx", StringComparison.Ordinal))
                path += ".xlsx";

            var payload = host.ExportPayload();
            List<ExportField> fields = payload.Item1;
            List<ExportRow> rows = payload.Item2;
            string docTitle;
            try
            {
                docTitle = ToText(host.Doc.Title);
            }
            catch (Exception)
            {
                docTitle = "";
            }
            int count;
            try
            {
                if (kindPicked == "clean")
                    count = ExcelBridge.ExportPresentation(path, name, fields, rows, docTitle);
                else
                    count = ExcelBridge.ExportRoundTrip(path, name, fields, rows, docTitle);
            }
            catch (Exception ex)
            {
                ThemedMessage("Export to Excel",
                              "The workbook could not be written:\n\n" + ex,
                              host.Window, C_RED, 700);
                return;
            }

            RememberFolder(path);
            host.SetStatus(string.Format(CultureInfo.InvariantCulture, "Exported {0} rows to {1}.",
                                         count, Path.GetFileName(path)));

            var done = new ThemedDialog("Exported", 620, null, host.Window, C_GREEN);
            done.Add(Tb(string.Format(CultureInfo.InvariantCulture, "{0} row{1} exported",
                                      count, count == 1 ? "" : "s"), C_GREEN, 22, true));
            TextBlock where = Tb(path, C_MUTED, 11, false, true);
            where.Margin = new Thickness(0, 8, 0, 0);
            done.Add(where);
            TextBlock note;
            if (kindPicked == "round")
                note = Tb("Edit the coloured columns, save, then use Import from Excel "
                          + "on the toolbar. Read-only columns are ignored on the way back.",
                          C_TEXT, 12, false, true);
            else
                note = Tb("This layout is for issuing. Use the round-trip export if you "
                          + "want to edit in Excel and bring the changes back.",
                          C_TEXT, 12, false, true);
            note.Margin = new Thickness(0, 12, 0, 0);
            done.Add(note);
            done.AddButton("Close", "ghost", "close");
            done.AddButton("Open file location", "green", "open");
            if (done.ResultTextAfterShow() == "open")
                RevealInExplorer(path);
        }

        /// <summary>Show a dialog and return its Result as text (null when closed without a button).</summary>
        private static string ResultTextAfterShow(this ThemedDialog dlg)
        {
            dlg.Show();
            return dlg.ResultText;
        }

        // ----------------------------------------------------------------- import ----

        /// <summary>
        /// What the file would do, before anything is staged. Returns "stage" when the user
        /// chose to stage the changes, otherwise "cancel" (or null if closed without a button).
        /// </summary>
        public static string ImportReport(ExcelForRevitWindow host, ImportResult res, string path)
        {
            int ok = res.Changes.Count;
            string accent = ok != 0 ? C_GREEN : C_ORANGE;
            var dlg = new ThemedDialog("Import from Excel", 700, null, host.Window, accent);

            dlg.Add(Tb(string.Format(CultureInfo.InvariantCulture, "{0} change{1} found",
                                     ok, ok == 1 ? "" : "s"), accent, 24, true));
            TextBlock sub = Tb(Path.GetFileName(path), C_MUTED, 11, false, true);
            sub.Margin = new Thickness(0, 6, 0, 0);
            dlg.Add(sub);

            var lines = new List<string>
            {
                string.Format(CultureInfo.InvariantCulture, "{0} row{1} read, {2} matched this schedule.",
                              res.RowsSeen, res.RowsSeen == 1 ? "" : "s",
                              res.RowsSeen - res.UnmatchedRows.Count),
                string.Format(CultureInfo.InvariantCulture, "{0} value{1} already matched the model and were left alone.",
                              res.Unchanged, res.Unchanged == 1 ? "" : "s"),
                string.Format(CultureInfo.InvariantCulture, "{0} column{1} matched by heading.",
                              res.MatchedCols.Count, res.MatchedCols.Count == 1 ? "" : "s"),
            };
            TextBlock body = Tb(string.Join("\n", lines), C_TEXT, 12, false, true);
            body.Margin = new Thickness(0, 12, 0, 0);
            dlg.Add(body);

            Action<string, string, int, Func<int, string>> block = (title, colour, total, formatter) =>
            {
                if (total == 0)
                    return;
                TextBlock cap = Tb(title, colour, 12, true, true);
                cap.Margin = new Thickness(0, 14, 0, 6);
                dlg.Add(cap);
                var box = new WBorder();
                box.Background = Brush(C_FIELD);
                box.BorderBrush = Brush(C_EDGE);
                box.BorderThickness = new Thickness(1);
                box.CornerRadius = new CornerRadius(3);
                box.Padding = new Thickness(8);
                var sv = new ScrollViewer();
                sv.MaxHeight = 150;
                sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto;
                var stack = new StackPanel();
                int shown = Math.Min(total, 200);
                for (int i = 0; i < shown; i++)
                {
                    TextBlock t = Tb(formatter(i), C_MUTED, 11, false, true);
                    t.Margin = new Thickness(0, 1, 0, 1);
                    stack.Children.Add(t);
                }
                if (total > 200)
                    stack.Children.Add(Tb(string.Format(CultureInfo.InvariantCulture, "... and {0} more", total - 200),
                                          C_MUTED, 11, false, true));
                sv.Content = stack;
                box.Child = sv;
                dlg.Add(box);
            };

            block("Will be staged:", C_GREEN, res.Changes.Count, i =>
            {
                var c = res.Changes[i];
                return c.Eid + "  •  " + host.Model.Fields[c.FieldIndex].Name + ":  "
                       + (string.IsNullOrEmpty(c.Old) ? "(empty)" : c.Old) + "  →  "
                       + (string.IsNullOrEmpty(c.New) ? "(empty)" : c.New);
            });
            block("Ignored — the parameter is read only in Revit:", C_RO_FG, res.SkippedReadonly.Count, i =>
            {
                var c = res.SkippedReadonly[i];
                return c.Eid + "  •  " + c.FieldName;
            });
            block("Ignored — no element with that Revit ID in this schedule:", C_RED, res.UnmatchedRows.Count,
                  i => ToText(res.UnmatchedRows[i]));
            block("Ignored — no column of that name in this schedule:", C_RED, res.UnmatchedCols.Count,
                  i => ToText(res.UnmatchedCols[i]));

            TextBlock tail = Tb("Nothing is written to the model yet. Staged changes show green "
                                + "in the grid; press APPLY when you are happy with them.",
                                C_TEXT, 12, false, true);
            tail.Margin = new Thickness(0, 14, 0, 0);
            dlg.Add(tail);

            dlg.AddButton("Cancel", "ghost", "cancel");
            if (ok != 0)
                dlg.AddButton(string.Format(CultureInfo.InvariantCulture, "Stage {0} change{1}", ok, ok == 1 ? "" : "s"),
                              "green", "stage");
            else
                dlg.AddButton("Close", "green", "cancel");
            dlg.Show();
            return dlg.ResultText;
        }

        // ------------------------------------------------------------ tick filter ----

        /// <summary>
        /// Excel's autofilter: everything ticked means no filter, unticking narrows.
        /// Writes the result straight into host.ColPicks and calls host.ApplyFilters();
        /// returns nothing (the Python returned None).
        /// </summary>
        public static void TickFilterDialog(ExcelForRevitWindow host, FieldInfo fi)
        {
            var values = host.ColumnValues(fi);
            var dlg = new ThemedDialog("Filter — " + fi.Name, 460, null, host.Window, C_ORANGE);
            int hidden = host.ColumnValuesLimited(fi);
            if (hidden != 0)
            {
                int shown = values.Count();
                TextBlock limited = Tb(string.Format(CultureInfo.InvariantCulture,
                                                     "Showing the {0} value{1} the other columns' filters "
                                                     + "allow. {2} more {3} in this column but filtered out "
                                                     + "elsewhere.",
                                                     shown, shown == 1 ? "" : "s", hidden,
                                                     hidden == 1 ? "is" : "are"),
                                       C_BLUE, 11, false, true);
                limited.Margin = new Thickness(0, 0, 0, 8);
                dlg.Add(limited);
            }

            int stale = host.StaleRows();
            if (stale != 0)
            {
                TextBlock note = Tb(string.Format(CultureInfo.InvariantCulture,
                                                  "{0} row{1} on screen no longer match{2} the current filters. "
                                                  + "They are kept visible so they can still be edited and copied "
                                                  + "from; applying here reapplies everything.",
                                                  stale, stale == 1 ? "" : "s", stale == 1 ? "es" : ""),
                                    C_ORANGE, 11, false, true);
                note.Margin = new Thickness(0, 0, 0, 8);
                dlg.Add(note);
            }

            HashSet<string> current;
            if (!host.ColPicks.TryGetValue(fi.Index, out current))
                current = null;
            var boxes = new List<(string Value, CheckBox Chk, string Label)>();

            TextBox search = DarkTextbox(400);
            search.Tag = "Search these values";
            dlg.Add(FieldRow("", search));

            var holder = new WBorder();
            holder.Background = Brush(C_FIELD);
            holder.BorderBrush = Brush(C_EDGE);
            holder.BorderThickness = new Thickness(1);
            holder.CornerRadius = new CornerRadius(3);
            holder.Padding = new Thickness(6);
            holder.Margin = new Thickness(0, 8, 0, 0);
            var sv = new ScrollViewer();
            sv.MaxHeight = 320;
            sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto;
            var stack = new StackPanel();
            foreach (var vc in values)
            {
                string value = vc.Item1;
                CheckBox chk = DarkCheck("", true);
                string label = value == "" ? "(blank)" : value;
                chk.Content = label + "   · " + vc.Item2.ToString(CultureInfo.InvariantCulture);
                chk.IsChecked = (current == null) || current.Contains(value);
                chk.Margin = new Thickness(0, 1, 0, 1);
                chk.Tag = value;
                stack.Children.Add(chk);
                boxes.Add((value, chk, ToText(label).ToLowerInvariant()));
            }
            sv.Content = stack;
            holder.Child = sv;

            TextBlock tally = Tb("", C_MUTED, 11);
            tally.VerticalAlignment = VerticalAlignment.Center;
            tally.Margin = new Thickness(12, 0, 0, 0);

            Func<int> countTicked = () =>
            {
                int ticked = 0;
                foreach (var b in boxes)
                {
                    if (b.Chk.IsChecked == true)
                        ticked++;
                }
                tally.Text = string.Format(CultureInfo.InvariantCulture, "{0} of {1} ticked", ticked, boxes.Count);
                return ticked;
            };

            var bar = new StackPanel();
            bar.Orientation = Orientation.Horizontal;
            bar.Margin = new Thickness(0, 8, 0, 0);
            Button btnAll = StyledButton("Select all", "ghost");
            Button btnNone = StyledButton("Untick all", "ghost");
            btnNone.Margin = new Thickness(8, 0, 0, 0);
            bar.Children.Add(btnAll);
            bar.Children.Add(btnNone);
            bar.Children.Add(tally);
            dlg.Add(bar);
            dlg.Add(holder);

            foreach (var b in boxes)
            {
                b.Chk.Checked += (sender, args) => countTicked();
                b.Chk.Unchecked += (sender, args) => countTicked();
            }

            search.TextChanged += (sender, args) =>
            {
                string term = ToText(search.Text).Trim().ToLowerInvariant();
                foreach (var b in boxes)
                    b.Chk.Visibility = (term.Length == 0 || b.Label.Contains(term))
                        ? Visibility.Visible : Visibility.Collapsed;
            };

            // Only what the search box is showing, so a search narrows what the two buttons
            // act on rather than them always taking the whole list.
            Action<bool> setVisible = state =>
            {
                foreach (var b in boxes)
                {
                    if (b.Chk.Visibility == Visibility.Visible)
                        b.Chk.IsChecked = state;
                }
                countTicked();
            };

            btnAll.Click += (sender, args) => setVisible(true);
            btnNone.Click += (sender, args) => setVisible(false);
            countTicked();

            Action doClear = () =>
            {
                host.ColPicks.Remove(fi.Index);
                host.ApplyFilters();
                host.SetStatus("Filter cleared on " + fi.Name + ".");
            };

            Action doApply = () =>
            {
                var picked = new HashSet<string>();
                foreach (var b in boxes)
                {
                    if (b.Chk.IsChecked == true)
                        picked.Add(b.Value);
                }
                if (picked.Count == boxes.Count)
                    host.ColPicks.Remove(fi.Index);   // everything ticked is no filter
                else
                    host.ColPicks[fi.Index] = picked;
                host.ApplyFilters();
            };

            dlg.AddButton("Clear", "orange", "close", true, doClear);
            dlg.AddButton("Apply", "green", "close", true, doApply);
            dlg.Show();
        }

        // -------------------------------------------------------------- set level ----

        /// <summary>
        /// Pick a level for the selected elements, staged like any other edit
        /// (calls host.StageLevels(rows, level) then host.SetStatus). Returns nothing.
        /// </summary>
        public static void SetLevelDialog(ExcelForRevitWindow host)
        {
            var rows = host.SelectedRows();
            if (!rows.Any())
            {
                ThemedMessage("Set Level",
                              "Select cells on the rows you want to re-level first.\n\n"
                              + "One cell anywhere on a row is enough — the whole "
                              + "element is what moves.", host.Window);
                return;
            }

            List<Level> levels = ProjectLevels(host.Doc);
            if (levels == null || levels.Count == 0)
            {
                ThemedMessage("Set Level", "This project has no levels.", host.Window, C_RED);
                return;
            }

            var dlg = new ThemedDialog("Set Level", 560, null, host.Window, C_ORANGE);
            int rowCount = rows.Count();
            dlg.Add(Tb(string.Format(CultureInfo.InvariantCulture,
                                     "{0} element{1} selected. Pick the level they should belong to.",
                                     rowCount, rowCount == 1 ? "" : "s"),
                       C_TEXT, 13, true, true));
            TextBlock note = Tb("Nothing moves. The position is measured before and after, and "
                                + "any shift the level change causes is undone, so the elements "
                                + "stay exactly where they are in the model and only their level "
                                + "changes.", C_MUTED, 11.5, false, true);
            note.Margin = new Thickness(0, 8, 0, 0);
            dlg.Add(note);

            var holder = new WBorder();
            holder.Background = Brush(C_FIELD);
            holder.BorderBrush = Brush(C_EDGE);
            holder.BorderThickness = new Thickness(1);
            holder.CornerRadius = new CornerRadius(3);
            holder.Padding = new Thickness(6);
            holder.Margin = new Thickness(0, 12, 0, 0);
            var sv = new ScrollViewer();
            sv.MaxHeight = 300;
            sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto;
            var stack = new StackPanel();

            Level chosen = null;
            var cards = new Dictionary<long, WBorder>();

            Action<Level> choose = lvl =>
            {
                chosen = lvl;
                long key = EidValue(lvl.Id);
                foreach (var kv in cards)
                {
                    bool on = (kv.Key == key);
                    kv.Value.Background = Brush(on ? C_EDIT_BG : C_CARD);
                    kv.Value.BorderBrush = Brush(on ? C_GREEN : C_EDGE);
                }
            };

            foreach (Level level in levels)
            {
                var card = new WBorder();
                card.Background = Brush(C_CARD);
                card.BorderBrush = Brush(C_EDGE);
                card.BorderThickness = new Thickness(1);
                card.CornerRadius = new CornerRadius(3);
                card.Padding = new Thickness(9, 6, 9, 6);
                card.Margin = new Thickness(0, 0, 0, 4);
                card.Cursor = Cursors.Hand;
                var inner = new WGrid();
                inner.ColumnDefinitions.Add(new ColumnDefinition());
                var right = new ColumnDefinition();
                right.Width = new GridLength(110);
                inner.ColumnDefinitions.Add(right);
                string levelName = ElemName(level);
                TextBlock name = Tb(string.IsNullOrEmpty(levelName) ? "Level" : levelName, C_TEXT, 12.5, true);
                WGrid.SetColumn(name, 0);
                inner.Children.Add(name);
                double mm;
                try
                {
                    mm = level.Elevation * 304.8;
                }
                catch (Exception)
                {
                    mm = 0.0;
                }
                // IronPython 2 rounds half away from zero
                TextBlock elev = Tb(((long)Math.Round(mm, MidpointRounding.AwayFromZero)).ToString(CultureInfo.InvariantCulture) + " mm",
                                    C_MUTED, 11.5);
                elev.HorizontalAlignment = HorizontalAlignment.Right;
                WGrid.SetColumn(elev, 1);
                inner.Children.Add(elev);
                card.Child = inner;

                Level lv = level;
                card.MouseLeftButtonUp += (sender, args) => choose(lv);
                cards[EidValue(level.Id)] = card;
                stack.Children.Add(card);
            }

            sv.Content = stack;
            holder.Child = sv;
            dlg.Add(holder);

            // start on the level the selection already shares, where they share one
            try
            {
                var current = new HashSet<object>();
                foreach (var r in rows)
                    current.Add(host.LevelOfRow(r));
                if (current.Count == 1)
                {
                    object only = current.First();
                    if (only != null)
                    {
                        long onlyId = Convert.ToInt64(only, CultureInfo.InvariantCulture);
                        foreach (Level level in levels)
                        {
                            if (EidValue(level.Id) == onlyId)
                            {
                                choose(level);
                                break;
                            }
                        }
                    }
                }
            }
            catch (Exception)
            {
            }

            Action doOk = () =>
            {
                Level level = chosen;
                if (level == null)
                    return;
                int n = host.StageLevels(rows, level);
                host.SetStatus(string.Format(CultureInfo.InvariantCulture,
                                             "{0} element{1} set to {2} — nothing is written until APPLY.",
                                             n, n == 1 ? "" : "s", ElemName(level)));
            };

            dlg.AddButton("Cancel", "ghost", null);
            dlg.AddButton("OK", "green", "ok", true, doOk);
            dlg.Show();
        }
    }
}
