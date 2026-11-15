// Port of efr_core.py lines 2688-3217 (schedule resolution and picker, screen_point, WorksetDropdown,
// FindReplace) and 3831-4131 (_hint, _field_row, CellToolDialog, sequence_dialog, affix_dialog).
//
// Everything here is built in code on top of ThemedDialog / the EfrUi toolkit. The dialogs that
// work on the grid take the window (`host`) and use its members by the naming rule:
//   host.Window, host.Model, host.Dg, host.WsDropdown, host.SeqSettings, host.AffixSettings,
//   host.SelCells(), host.OrderedFieldColumns(), host.TextAt(pos, col), host.SelectCell(pos, col),
//   host.BeginBatch(), host.StageCell(pos, col, text), host.EndBatch(), host.SkippedNote(n),
//   host.SetStatus(text), host.ApplyWorkset(targets, name).
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using DB = Autodesk.Revit.DB;
using RUI = Autodesk.Revit.UI;
using RevoBIM.Tools.ExcelForRevit;
using static RevoBIM.Tools.ExcelForRevit.Efr;

namespace RevoBIM.UI.ExcelForRevit
{
    public static partial class EfrUi
    {
        // ================================================== schedule resolution ======

        public static bool IsEditableSchedule(DB.Element v)
        {
            var sched = v as DB.ViewSchedule;
            if (sched == null)
                return false;
            try
            {
                if (sched.IsTemplate)
                    return false;
            }
            catch (Exception)
            {
            }
            try
            {
                if (sched.IsTitleblockRevisionSchedule)
                    return false;
            }
            catch (Exception)
            {
            }
            return true;
        }

        /// <summary>Active schedule view, else Project Browser selection, else a picker. Null when none chosen.</summary>
        public static DB.ViewSchedule ResolveSchedule(RUI.UIDocument uidoc, DB.Document doc)
        {
            try
            {
                DB.View av = uidoc.ActiveView;
                if (IsEditableSchedule(av))
                    return (DB.ViewSchedule)av;
            }
            catch (Exception)
            {
            }
            try
            {
                foreach (DB.ElementId eid in uidoc.Selection.GetElementIds())
                {
                    DB.Element e = doc.GetElement(eid);
                    if (IsEditableSchedule(e))
                        return (DB.ViewSchedule)e;
                }
            }
            catch (Exception)
            {
            }
            return PickSchedule(doc);
        }

        /// <summary>The nearest ancestor of `element` (itself included) that is a T, or null (Python walk_up, guard 60).</summary>
        private static T WalkUpTo<T>(object element) where T : class
        {
            object node = element;
            int guard = 0;
            while (node != null && guard < 60)
            {
                var found = node as T;
                if (found != null)
                    return found;
                try
                {
                    var dep = node as DependencyObject;
                    if (dep == null)
                        return null;
                    node = VisualTreeHelper.GetParent(dep);
                }
                catch (Exception)
                {
                    return null;
                }
                guard++;
            }
            return null;
        }

        /// <summary>The themed list of every schedule in the model; returns the one chosen, or null.</summary>
        public static DB.ViewSchedule PickSchedule(DB.Document doc)
        {
            var scheds = new List<DB.ViewSchedule>();
            try
            {
                foreach (DB.Element v in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewSchedule)))
                {
                    if (IsEditableSchedule(v))
                        scheds.Add((DB.ViewSchedule)v);
                }
            }
            catch (Exception)
            {
            }
            if (scheds.Count == 0)
            {
                ThemedMessage("Excel for Revit", "There are no schedules in this model.");
                return null;
            }

            // names read once: asking Revit for every schedule's name again on each
            // keystroke in the search box was most of what the box cost
            var named = scheds.Select(v => (View: v, Name: ElemName(v)))
                              .OrderBy(p => NaturalKey(p.Name))
                              .ToList();
            var lowered = named.Select(p => p.Name.ToLowerInvariant()).ToList();

            // sized to its content: at a fixed 520px the list and its hint overran the
            // body, and the dialog grew a second scrollbar around the first
            var dlg = new ThemedDialog("Excel for Revit", 560, null, null, C_ORANGE);
            dlg.Add(Tb("No schedule was active or selected. Pick one to open.", C_MUTED, 12, false, true));
            TextBox box = DarkTextbox(500);
            box.Tag = "Search schedules";            // the placeholder, while it is empty
            box.Margin = new Thickness(0, 10, 0, 8);
            dlg.Add(box);
            var lst = new ListBox();
            lst.Height = 340;
            lst.Background = Brush(C_FIELD);
            lst.Foreground = Brush(C_TEXT);
            lst.BorderBrush = Brush(C_EDGE);
            lst.BorderThickness = new Thickness(1);
            dlg.Add(lst);
            TextBlock hint = Tb("Double-click a schedule, or press Enter, to open it.", C_MUTED, 11);
            hint.Margin = new Thickness(0, 6, 0, 0);
            dlg.Add(hint);

            var items = new List<DB.ViewSchedule>();
            DB.ViewSchedule resultView = null;

            Action<string> fill = term =>
            {
                term = (term ?? "").ToLowerInvariant();
                lst.Items.Clear();
                items.Clear();
                for (int n = 0; n < named.Count; n++)
                {
                    if (term.Length > 0 && lowered[n].IndexOf(term, StringComparison.Ordinal) < 0)
                        continue;
                    items.Add(named[n].View);
                    lst.Items.Add(named[n].Name);
                }
                if (items.Count > 0)
                    lst.SelectedIndex = 0;          // Enter always has something to open
            };
            fill("");

            box.TextChanged += (sender, args) => fill(box.Text);

            Action openSelected = () =>
            {
                int i = lst.SelectedIndex;
                if (i >= 0 && i < items.Count)
                {
                    resultView = items[i];
                    dlg.CloseWith("open");
                }
            };

            lst.MouseDoubleClick += (sender, args) =>
            {
                // only a double-click that lands on a schedule opens it; one on the
                // scrollbar or the empty space under a short list does nothing
                ListBoxItem hit = WalkUpTo<ListBoxItem>(args.OriginalSource);
                if (hit == null)
                    return;
                args.Handled = true;
                openSelected();
            };

            dlg.Window.PreviewKeyDown += (sender, args) =>
            {
                Key key = args.Key;
                if (key == Key.Enter || key == Key.Return)
                {
                    if (Keyboard.FocusedElement is Button)
                        return;          // Tab to Cancel then Enter means Cancel
                    args.Handled = true;
                    openSelected();
                }
                else if (key == Key.Escape)
                {
                    args.Handled = true;
                    dlg.CloseWith(null);
                }
                else if (key == Key.Down && box.IsKeyboardFocusWithin)
                {
                    // from the search box straight into the list, as a combo would
                    args.Handled = true;
                    if (lst.Items.Count > 0)
                    {
                        if (lst.SelectedIndex < 0)
                            lst.SelectedIndex = 0;
                        try
                        {
                            var item = lst.ItemContainerGenerator.ContainerFromIndex(lst.SelectedIndex) as UIElement;
                            (item ?? lst).Focus();
                        }
                        catch (Exception)
                        {
                            lst.Focus();
                        }
                    }
                }
            };

            dlg.Window.ContentRendered += (sender, args) =>
            {
                try
                {
                    box.Focus();
                }
                catch (Exception)
                {
                }
            };

            dlg.AddButton("Cancel", "ghost", null);
            dlg.AddButton("Open", "green", "open", false, openSelected);
            dlg.Show();
            return resultView;
        }

        // ======================================================== find and replace ===

        /// <summary>
        /// A point on `element`, as a position on screen in WPF units: what a window's
        /// Left and Top take. PointToScreen answers in device pixels.
        /// </summary>
        public static Point ScreenPoint(Visual element, double x, double y)
        {
            Point pt = element.PointToScreen(new Point(x, y));
            try
            {
                PresentationSource source = PresentationSource.FromVisual(element);
                if (source != null)
                    pt = source.CompositionTarget.TransformFromDevice.Transform(pt);
            }
            catch (Exception)
            {
            }
            return pt;
        }

        // ================================================== dialog body helpers ======

        public static TextBlock Hint(string text)
        {
            TextBlock tb = Tb(text, C_MUTED, 11, false, true);
            tb.Margin = new Thickness(0, 6, 0, 0);
            return tb;
        }

        /// <summary>Label above a control, as one block for the dialog body.</summary>
        public static StackPanel FieldRow(string label, UIElement control, string note = null)
        {
            var panel = new StackPanel();
            panel.Margin = new Thickness(0, 10, 0, 0);
            TextBlock cap = Tb(label, C_TEXT, 12, true);
            cap.Margin = new Thickness(0, 0, 0, 4);
            panel.Children.Add(cap);
            panel.Children.Add(control);
            if (!string.IsNullOrEmpty(note))
                panel.Children.Add(Hint(note));
            return panel;
        }

        // ----------------------------------------------------------- small shared parsers

        /// <summary>Python int(float(text)): false when it is not a number (or not finite).</summary>
        private static bool TryIntOfFloat(string text, out long value)
        {
            value = 0;
            double d;
            if (!double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out d))
                return false;
            if (double.IsNaN(d) || double.IsInfinity(d) || Math.Abs(d) >= 9.2e18)
                return false;
            value = (long)Math.Truncate(d);
            return true;
        }

        private static string SavedText(Dictionary<string, object> saved, string key, string fallback)
        {
            object v;
            if (saved != null && saved.TryGetValue(key, out v) && v != null)
                return ToText(v);
            return fallback;
        }

        private static bool SavedBool(Dictionary<string, object> saved, string key, bool fallback)
        {
            object v;
            if (saved != null && saved.TryGetValue(key, out v) && v != null)
            {
                if (v is bool)
                    return (bool)v;
                string s = ToText(v);
                return s.Length > 0 && s != "False" && s != "0";
            }
            return fallback;
        }

        // ================================================== number sequence ======

        /// <summary>Number the selection: start, step, padding, prefix and suffix.</summary>
        public static void SequenceDialog(ExcelForRevitWindow host)
        {
            var tool = new CellToolDialog(host, "Number Sequence", 600);
            List<SelCell> cells = tool.Writable();
            if (cells.Count == 0)
            {
                ThemedMessage("Number Sequence", "Select the editable cells to number first.", host.Window);
                return;
            }

            tool.Dlg.Add(Tb("The selection is numbered top to bottom. Where the selection "
                            + "covers more than one column, each column starts again.",
                            C_TEXT, 12, false, true));

            Dictionary<string, object> saved = host.SeqSettings;
            TextBox start = DarkTextbox(110, SavedText(saved, "start", "001"));
            TextBox step = DarkTextbox(110, SavedText(saved, "step", "1"));
            TextBox pad = DarkTextbox(110, SavedText(saved, "pad", "0"));
            TextBox prefix = DarkTextbox(240, SavedText(saved, "prefix", ""));
            TextBox suffix = DarkTextbox(240, SavedText(saved, "suffix", ""));
            CheckBox keep = DarkCheck("Keep the existing cell text in front of the number",
                                      SavedBool(saved, "keep", false));

            var numbers = new StackPanel();
            numbers.Orientation = Orientation.Horizontal;
            var numberRows = new List<(string Label, UIElement Ctrl)>
            {
                ("Start", start), ("Step", step), ("Pad to digits", pad),
            };
            foreach (var item in numberRows)
            {
                StackPanel block = FieldRow(item.Label, item.Ctrl);
                block.Margin = new Thickness(0, 10, 16, 0);
                numbers.Children.Add(block);
            }
            tool.Dlg.Add(numbers);
            tool.Dlg.Add(Hint(
                "Leading zeros in the start number set the width: 001 gives 001, 002, "
                + "003 and rolls on to 010 and 100; 01 gives 01, 02, 03. Pad to digits is "
                + "there to force a wider field than the start number implies — leave it "
                + "at 0 to take the width from the start number."));

            var texts = new StackPanel();
            texts.Orientation = Orientation.Horizontal;
            StackPanel tb1 = FieldRow("Prefix", prefix);
            tb1.Margin = new Thickness(0, 10, 16, 0);
            texts.Children.Add(tb1);
            texts.Children.Add(FieldRow("Suffix", suffix));
            tool.Dlg.Add(texts);

            keep.Margin = new Thickness(0, 12, 0, 0);
            tool.Dlg.Add(keep);
            tool.AddPreview();

            var values = new List<(SelCell Cell, string Text)>();
            bool ok = false;

            Action recompute = () =>
            {
                string rawStart = ToText(start.Text).Trim();
                if (rawStart.Length == 0)
                    rawStart = "1";
                long s0, st, pd;
                string stepText = ToText(step.Text).Trim();
                string padText = ToText(pad.Text).Trim();
                if (!TryIntOfFloat(rawStart, out s0)
                    || !TryIntOfFloat(stepText.Length > 0 ? stepText : "1", out st)
                    || !TryIntOfFloat(padText.Length > 0 ? padText : "0", out pd))
                {
                    ok = false;
                    tool.SetPreview(new List<string> { "Start, step and padding must be whole numbers." }, C_FAIL_FG);
                    return;
                }
                // 001 means three digits, 01 means two: the start number carries the
                // width, and the pad box can only widen it further
                string startDigits = rawStart.StartsWith("-", StringComparison.Ordinal) ? rawStart.Substring(1) : rawStart;
                if (startDigits.StartsWith("0", StringComparison.Ordinal) && startDigits.Length > 1)
                    pd = Math.Max(pd, startDigits.Length);

                var byCol = new Dictionary<int, List<SelCell>>();
                foreach (SelCell cell in cells)
                {
                    int disp = cell.Col.DisplayIndex;
                    List<SelCell> list;
                    if (!byCol.TryGetValue(disp, out list))
                    {
                        list = new List<SelCell>();
                        byCol[disp] = list;
                    }
                    list.Add(cell);
                }
                var fresh = new List<(SelCell Cell, string Text)>();
                foreach (int disp in byCol.Keys.OrderBy(k => k))
                {
                    List<SelCell> group = byCol[disp].OrderBy(d => d.Pos).ToList();
                    for (int i = 0; i < group.Count; i++)
                    {
                        string body = (s0 + st * i).ToString(CultureInfo.InvariantCulture);
                        if (pd > 0)
                        {
                            bool neg = body.StartsWith("-", StringComparison.Ordinal);
                            string digits = neg ? body.Substring(1) : body;
                            if (digits.Length < pd)
                                digits = new string('0', (int)pd - digits.Length) + digits;
                            body = (neg ? "-" : "") + digits;
                        }
                        string text = ToText(prefix.Text) + body + ToText(suffix.Text);
                        if (keep.IsChecked == true)
                            text = ToText(host.TextAt(group[i].Pos, group[i].Col)) + text;
                        fresh.Add((group[i], text));
                    }
                }
                values = fresh;
                ok = values.Count > 0;
                var lines = values.Take(4).Select(v => v.Text).ToList();
                if (values.Count > lines.Count)
                    lines.Add(string.Format(CultureInfo.InvariantCulture, "... {0} cells in total", values.Count));
                tool.SetPreview(lines, C_EDIT_FG);
            };

            foreach (TextBox ctrl in new[] { start, step, pad, prefix, suffix })
                ctrl.TextChanged += (sender, args) => recompute();
            keep.Checked += (sender, args) => recompute();
            keep.Unchecked += (sender, args) => recompute();
            recompute();

            Action applyNow = () =>
            {
                recompute();
                if (!ok)
                    return;
                host.SeqSettings = new Dictionary<string, object>
                {
                    { "start", ToText(start.Text) }, { "step", ToText(step.Text) },
                    { "pad", ToText(pad.Text) }, { "prefix", ToText(prefix.Text) },
                    { "suffix", ToText(suffix.Text) }, { "keep", keep.IsChecked == true },
                };
                int n = tool.Write(values);
                host.SetStatus(string.Format(CultureInfo.InvariantCulture, "Numbered {0} cell{1}.", n, n == 1 ? "" : "s"));
                tool.Dlg.CloseWith("apply");
            };

            tool.Dlg.AddButton("Cancel", "ghost", "cancel");
            tool.Dlg.AddButton(string.Format(CultureInfo.InvariantCulture, "Number {0} cell{1}",
                cells.Count, cells.Count == 1 ? "" : "s"), "green", "apply", false, applyNow);
            tool.Dlg.Show();
        }

        // ================================================== add prefix / suffix ======

        /// <summary>Add a prefix and/or suffix to what the selected cells already hold.</summary>
        public static void AffixDialog(ExcelForRevitWindow host)
        {
            var tool = new CellToolDialog(host, "Add Prefix / Suffix", 600);
            List<SelCell> cells = tool.Writable();
            if (cells.Count == 0)
            {
                ThemedMessage("Add Prefix / Suffix", "Select the editable cells to add to first.", host.Window);
                return;
            }

            tool.Dlg.Add(Tb("The text is wrapped around whatever each selected cell already "
                            + "holds. Nothing is written until APPLY on the main window.",
                            C_TEXT, 12, false, true));

            Dictionary<string, object> saved = host.AffixSettings;
            TextBox prefix = DarkTextbox(260, SavedText(saved, "prefix", ""));
            TextBox suffix = DarkTextbox(260, SavedText(saved, "suffix", ""));
            CheckBox skipEmpty = DarkCheck("Leave empty cells alone", SavedBool(saved, "skip_empty", true));
            CheckBox skipHave = DarkCheck("Skip cells that already start with the prefix",
                                          SavedBool(saved, "skip_have", true));

            var row = new StackPanel();
            row.Orientation = Orientation.Horizontal;
            StackPanel block = FieldRow("Prefix", prefix);
            block.Margin = new Thickness(0, 10, 16, 0);
            row.Children.Add(block);
            row.Children.Add(FieldRow("Suffix", suffix));
            tool.Dlg.Add(row);

            skipEmpty.Margin = new Thickness(0, 12, 0, 0);
            skipHave.Margin = new Thickness(0, 6, 0, 0);
            tool.Dlg.Add(skipEmpty);
            tool.Dlg.Add(skipHave);
            tool.AddPreview();

            var values = new List<(SelCell Cell, string Text)>();
            int skippedCount = 0;

            Action recompute = () =>
            {
                string pre = ToText(prefix.Text);
                string suf = ToText(suffix.Text);
                var fresh = new List<(SelCell Cell, string Text)>();
                int skipped = 0;
                foreach (SelCell cell in cells)
                {
                    string current = ToText(host.TextAt(cell.Pos, cell.Col));
                    if (skipEmpty.IsChecked == true && current.Trim().Length == 0)
                    {
                        skipped++;
                        continue;
                    }
                    if (skipHave.IsChecked == true && pre.Length > 0 && current.StartsWith(pre, StringComparison.Ordinal))
                    {
                        skipped++;
                        continue;
                    }
                    fresh.Add((cell, pre + current + suf));
                }
                values = fresh;
                skippedCount = skipped;
                var lines = new List<string>();
                foreach (var v in values.Take(4))
                {
                    string shown = ToText(host.TextAt(v.Cell.Pos, v.Cell.Col));
                    lines.Add((shown.Length > 0 ? shown : "(empty)") + "  ->  " + v.Text);
                }
                if (values.Count > lines.Count)
                    lines.Add(string.Format(CultureInfo.InvariantCulture, "... {0} cells in total", values.Count));
                if (skipped > 0)
                    lines.Add(string.Format(CultureInfo.InvariantCulture, "{0} cell{1} left alone", skipped, skipped == 1 ? "" : "s"));
                tool.SetPreview(lines, values.Count > 0 ? C_EDIT_FG : C_MUTED);
            };

            prefix.TextChanged += (sender, args) => recompute();
            suffix.TextChanged += (sender, args) => recompute();
            foreach (CheckBox chk in new[] { skipEmpty, skipHave })
            {
                chk.Checked += (sender, args) => recompute();
                chk.Unchecked += (sender, args) => recompute();
            }
            recompute();

            Action applyNow = () =>
            {
                recompute();
                if (values.Count == 0)
                    return;
                host.AffixSettings = new Dictionary<string, object>
                {
                    { "prefix", ToText(prefix.Text) }, { "suffix", ToText(suffix.Text) },
                    { "skip_empty", skipEmpty.IsChecked == true }, { "skip_have", skipHave.IsChecked == true },
                };
                int n = tool.Write(values);
                string extra = "";
                if (skippedCount > 0)
                    extra = string.Format(CultureInfo.InvariantCulture, ", {0} left alone", skippedCount);
                host.SetStatus(string.Format(CultureInfo.InvariantCulture, "Prefix / suffix wrote {0} cell{1}{2}.",
                    n, n == 1 ? "" : "s", extra));
                tool.Dlg.CloseWith("apply");
            };

            tool.Dlg.AddButton("Cancel", "ghost", "cancel");
            tool.Dlg.AddButton("Add to selection", "green", "apply", false, applyNow);
            tool.Dlg.Show();
        }
    }

    /// <summary>Shared frame for the three cell tools: a live preview over the selection.</summary>
    public class CellToolDialog
    {
        public ExcelForRevitWindow Host;
        public List<SelCell> Cells;
        public ThemedDialog Dlg;
        public TextBlock Preview;
        public int Applied;

        public CellToolDialog(ExcelForRevitWindow host, string subtitle, double width = 620)
        {
            Host = host;
            Cells = host.SelCells();
            Dlg = new ThemedDialog(subtitle, width, null, host.Window, C_ORANGE);
            Preview = EfrUi.Tb("", C_MUTED, 11, false, true);
            Preview.FontFamily = new FontFamily("Consolas");
            Applied = 0;
        }

        /// <summary>Selected cells that can actually take a value, in visual order.</summary>
        public List<SelCell> Writable()
        {
            var output = new List<SelCell>();
            foreach (SelCell c in Cells)
            {
                try
                {
                    if (Host.Model.Rows[c.Ridx].Cells[c.Fidx].Editable)
                        output.Add(c);
                }
                catch (Exception)
                {
                    continue;
                }
            }
            return output;
        }

        public void AddPreview()
        {
            var box = new Border();
            box.Background = Brush(C_FIELD);
            box.BorderBrush = Brush(C_EDGE);
            box.BorderThickness = new Thickness(1);
            box.CornerRadius = new CornerRadius(3);
            box.Padding = new Thickness(10, 8, 10, 8);
            box.Margin = new Thickness(0, 12, 0, 0);
            var inner = new StackPanel();
            TextBlock cap = EfrUi.Tb("Preview", C_BLUE, 11, true);
            cap.Margin = new Thickness(0, 0, 0, 4);
            inner.Children.Add(cap);
            inner.Children.Add(Preview);
            box.Child = inner;
            Dlg.Add(box);
        }

        /// <param name="colour">null = C_MUTED.</param>
        public void SetPreview(IList<string> lines, string colour = null)
        {
            try
            {
                Preview.Text = (lines != null && lines.Count > 0) ? string.Join("\n", lines) : "—";
                Preview.Foreground = Brush(colour ?? C_MUTED);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>values: (cell, text) pairs, staged as one undo batch. Returns how many were staged.</summary>
        public int Write(IList<(SelCell Cell, string Text)> values)
        {
            ExcelForRevitWindow host = Host;
            host.BeginBatch();
            int n = 0;
            foreach (var item in values)
            {
                if (host.StageCell(item.Cell.Pos, item.Cell.Col, item.Text))
                    n++;
            }
            host.EndBatch();
            Applied = n;
            return n;
        }
    }

    /// <summary>Find and Replace over the grid: a modeless themed dialog.</summary>
    public class FindReplace
    {
        public ExcelForRevitWindow Host;
        public ThemedDialog Dlg;
        public TextBox FindBox;
        public TextBox ReplBox;
        public CheckBox Cs;
        public CheckBox Whole;
        public CheckBox Selonly;
        public TextBlock Status;

        // the cell Find Next last landed on: (position, column); (-1, none) before the first find
        private int _lastPos = -1;
        private object _lastCol;

        public FindReplace(ExcelForRevitWindow host)
        {
            Host = host;
            var dlg = new ThemedDialog("Find and Replace", 520, null, host.Window);
            Dlg = dlg;
            dlg.Add(EfrUi.Tb("Find what", C_MUTED, 11));
            FindBox = EfrUi.DarkTextbox(470);
            dlg.Add(FindBox);
            TextBlock lbl = EfrUi.Tb("Replace with", C_MUTED, 11);
            lbl.Margin = new Thickness(0, 10, 0, 0);
            dlg.Add(lbl);
            ReplBox = EfrUi.DarkTextbox(470);
            dlg.Add(ReplBox);

            var opts = new StackPanel();
            opts.Orientation = Orientation.Horizontal;
            opts.Margin = new Thickness(0, 12, 0, 0);
            Cs = EfrUi.DarkCheck("Match case");
            Whole = EfrUi.DarkCheck("Whole cell");
            Selonly = EfrUi.DarkCheck("Selection only");
            opts.Children.Add(Cs);
            opts.Children.Add(Whole);
            opts.Children.Add(Selonly);
            dlg.Add(opts);

            Status = EfrUi.Tb("", C_MUTED, 11, false, true);
            Status.Margin = new Thickness(0, 10, 0, 0);
            dlg.Add(Status);

            dlg.AddButton("Close", "ghost", null);
            dlg.AddButton("Find Next", "ghost", null, false, FindNext);
            dlg.AddButton("Replace", "orange", null, false, ReplaceOne);
            dlg.AddButton("Replace All", "green", null, false, ReplaceAll);
        }

        public void Show()
        {
            try
            {
                Dlg.Window.Show();
                FindBox.Focus();
            }
            catch (Exception)
            {
            }
        }

        private bool Match(string text, string term)
        {
            if (string.IsNullOrEmpty(term))
                return false;
            string a = text, b = term;
            if (Cs.IsChecked != true)
            {
                a = a.ToLowerInvariant();
                b = b.ToLowerInvariant();
            }
            if (Whole.IsChecked == true)
                return a == b;
            return a.IndexOf(b, StringComparison.Ordinal) >= 0;
        }

        private string Replaced(string text, string term, string repl)
        {
            if (Whole.IsChecked == true)
                return repl;
            if (Cs.IsChecked == true)
                return text.Replace(term, repl);
            var output = new System.Text.StringBuilder();
            string lowT = text.ToLowerInvariant();
            string lowTerm = term.ToLowerInvariant();
            int i = 0;
            while (true)
            {
                int j = i <= lowT.Length ? lowT.IndexOf(lowTerm, i, StringComparison.Ordinal) : -1;
                if (j < 0)
                {
                    if (i < text.Length)
                        output.Append(text, i, text.Length - i);
                    break;
                }
                output.Append(text, i, j - i).Append(repl);
                i = j + term.Length;
            }
            return output.ToString();
        }

        private List<(int Pos, DataGridColumn Col)> Scope()
        {
            ExcelForRevitWindow host = Host;
            if (Selonly.IsChecked == true)
            {
                List<SelCell> cells = host.SelCells();
                if (cells != null && cells.Count > 0)
                    return cells.Select(c => (c.Pos, c.Col)).ToList();
            }
            var output = new List<(int Pos, DataGridColumn Col)>();
            var cols = host.OrderedFieldColumns();
            for (int i = 0; i < host.Dg.Items.Count; i++)
            {
                foreach (DataGridColumn col in cols)
                    output.Add((i, col));
            }
            return output;
        }

        public void FindNext()
        {
            string term = FindBox.Text;
            if (string.IsNullOrEmpty(term))
            {
                Status.Text = "Type something to find.";
                return;
            }
            var scope = Scope();
            int start = 0;
            for (int n = 0; n < scope.Count; n++)
            {
                if (scope[n].Pos == _lastPos && ReferenceEquals(scope[n].Col, _lastCol))
                {
                    start = n + 1;
                    break;
                }
            }
            for (int n = 0; n < scope.Count; n++)
            {
                var item = scope[(start + n) % scope.Count];
                string text = Host.TextAt(item.Pos, item.Col);
                if (text != null && Match(text, term))
                {
                    Host.SelectCell(item.Pos, item.Col);
                    _lastPos = item.Pos;
                    _lastCol = item.Col;
                    Status.Text = string.Format(CultureInfo.InvariantCulture, "Found in row {0}.", item.Pos + 1);
                    return;
                }
            }
            Status.Text = "No match.";
        }

        public void ReplaceOne()
        {
            string term = FindBox.Text;
            if (string.IsNullOrEmpty(term))
                return;
            List<SelCell> cells = Host.SelCells();
            if (cells != null && cells.Count > 0)
            {
                SelCell c = cells[0];
                string text = Host.TextAt(c.Pos, c.Col);
                if (text != null && Match(text, term))
                {
                    Host.BeginBatch();
                    Host.StageCell(c.Pos, c.Col, Replaced(text, term, ReplBox.Text));
                    Host.EndBatch();
                    Status.Text = "Replaced 1 cell.";
                }
            }
            FindNext();
        }

        public void ReplaceAll()
        {
            string term = FindBox.Text;
            if (string.IsNullOrEmpty(term))
                return;
            string repl = ReplBox.Text;
            var scope = Scope();
            Host.BeginBatch();
            int count = 0;
            int skipped = 0;
            foreach (var item in scope)
            {
                string text = Host.TextAt(item.Pos, item.Col);
                if (text == null || !Match(text, term))
                    continue;
                if (!Host.StageCell(item.Pos, item.Col, Replaced(text, term, repl)))
                {
                    skipped++;
                    continue;
                }
                count++;
            }
            Host.EndBatch();
            string msg = string.Format(CultureInfo.InvariantCulture, "Replaced {0} cell{1}.", count, count == 1 ? "" : "s");
            if (skipped > 0)
                msg += Host.SkippedNote(skipped);
            Status.Text = msg;
            Host.SetStatus(msg);
        }
    }

    /// <summary>
    /// The list of worksets that opens from a Workset cell.
    ///
    /// A small borderless window owned by the main window, not a WPF Popup: a text
    /// box inside a Popup is unreliable at taking typing in a modeless window that
    /// another application hosts, and the search box here has to. It is a
    /// dropdown, not a window of its own, so it closes when anything else is
    /// clicked and carries no title bar or shrink button.
    ///
    /// Choosing a workset stages it on every cell it was opened for (the whole
    /// selection in the Workset column) through the same Stage() as every other
    /// edit, so it colours green, undoes in one step and waits for APPLY.
    /// </summary>
    public class WorksetDropdown
    {
        public const int LIST_MAX = 300;
        public const int ROW_PX = 24;
        public const double GRACE_S = 0.6;        // about a double-click: a click this soon is its second half

        public ExcelForRevitWindow Host;
        public List<(int Ridx, int Field)> Targets;
        public List<string> Names;
        public List<string> Shown;
        public bool Closed;
        public Window Window;
        public TextBox Box;
        public ListBox Lst;
        public string Seed;

        private DateTime _openedAt = DateTime.MinValue;
        private bool _opened;

        /// <param name="targets">(row index, field index) of every cell the choice goes to.</param>
        /// <param name="current">The workset all targets hold now, or null when they differ.</param>
        /// <param name="seed">What was typed on the cell; it opens the search box with this.</param>
        public WorksetDropdown(ExcelForRevitWindow host, List<(int Ridx, int Field)> targets,
            IEnumerable<string> names, string current, string seed = "")
        {
            Host = host;
            Targets = targets;
            Names = new List<string>(names);
            Shown = new List<string>(Names);
            Closed = false;

            var w = new Window();
            w.WindowStyle = WindowStyle.None;
            w.AllowsTransparency = true;
            w.Background = Brush("#00000000");
            w.ShowInTaskbar = false;
            w.ResizeMode = ResizeMode.NoResize;
            w.SizeToContent = SizeToContent.Height;
            w.FontFamily = new FontFamily("Segoe UI");
            w.FontSize = 12;
            EfrUi.ThemeWindow(w);
            Window = w;

            var shell = new Border();
            shell.Background = Brush(C_FIELD);
            shell.BorderBrush = Brush(C_EDGE_SOFT);
            shell.BorderThickness = new Thickness(1);
            shell.CornerRadius = new CornerRadius(4);
            shell.Padding = new Thickness(8);
            var body = new StackPanel();
            shell.Child = body;
            w.Content = shell;

            int count = targets.Select(t => t.Ridx).Distinct().Count();
            TextBlock head = EfrUi.Tb(string.Format(CultureInfo.InvariantCulture, "Workset for {0} row{1}",
                count, count == 1 ? "" : "s"), C_MUTED, 11);
            head.Margin = new Thickness(2, 0, 0, 6);
            body.Children.Add(head);

            var box = new TextBox();
            box.Tag = "Search worksets";
            box.Margin = new Thickness(0, 0, 0, 6);
            body.Children.Add(box);
            Box = box;

            var lst = new ListBox();
            lst.MaxHeight = LIST_MAX;
            body.Children.Add(lst);
            Lst = lst;

            TextBlock hint = EfrUi.Tb("Click to set  ·  Enter  ·  Esc to cancel", C_MUTED, 10);
            hint.Margin = new Thickness(2, 6, 0, 0);
            body.Children.Add(hint);

            Fill("");
            int at = current != null ? Shown.IndexOf(current) : -1;
            if (at >= 0)
                lst.SelectedIndex = at;
            else if (Shown.Count > 0)
                lst.SelectedIndex = 0;

            box.TextChanged += (sender, args) => Fill(Box.Text);
            lst.PreviewMouseLeftButtonUp += OnClick;
            w.PreviewKeyDown += OnKeys;
            w.Deactivated += OnDeactivated;
            w.Closed += OnClosed;
            Seed = ToText(seed ?? "");
        }

        public void Fill(string term)
        {
            string t = ToText(term).Trim().ToLowerInvariant();
            Shown = Names.Where(n => t.Length == 0 || n.ToLowerInvariant().IndexOf(t, StringComparison.Ordinal) >= 0).ToList();
            Lst.Items.Clear();
            foreach (string name in Shown)
                Lst.Items.Add(name);
            if (Shown.Count > 0)
                Lst.SelectedIndex = 0;
        }

        private void OnClick(object sender, MouseButtonEventArgs args)
        {
            ListBoxItem item = WalkUpTo(args.OriginalSource);
            if (item == null)
                return;                          // the scrollbar, or empty space
            int index;
            try
            {
                index = Lst.ItemContainerGenerator.IndexFromContainer(item);
            }
            catch (Exception)
            {
                index = -1;
            }
            if (index >= 0 && index < Shown.Count)
            {
                args.Handled = true;
                Choose(Shown[index]);
            }
        }

        private static ListBoxItem WalkUpTo(object element)
        {
            object node = element;
            int guard = 0;
            while (node != null && guard < 60)
            {
                var found = node as ListBoxItem;
                if (found != null)
                    return found;
                try
                {
                    var dep = node as DependencyObject;
                    if (dep == null)
                        return null;
                    node = VisualTreeHelper.GetParent(dep);
                }
                catch (Exception)
                {
                    return null;
                }
                guard++;
            }
            return null;
        }

        private void OnKeys(object sender, KeyEventArgs args)
        {
            Key key = args.Key;
            if (key == Key.Escape)
            {
                args.Handled = true;
                Close();
            }
            else if (key == Key.Enter || key == Key.Return)
            {
                args.Handled = true;
                int i = Lst.SelectedIndex;
                if (i >= 0 && i < Shown.Count)
                    Choose(Shown[i]);
            }
            else if (key == Key.Down && Box.IsKeyboardFocusWithin && Shown.Count > 0)
            {
                args.Handled = true;
                FocusItem(Math.Max(Lst.SelectedIndex, 0));
            }
            else if (key == Key.Up && Lst.IsKeyboardFocusWithin && Lst.SelectedIndex <= 0)
            {
                args.Handled = true;
                Box.Focus();
            }
        }

        public void FocusItem(int index)
        {
            Lst.SelectedIndex = index;
            try
            {
                var item = Lst.ItemContainerGenerator.ContainerFromIndex(index) as UIElement;
                (item ?? Lst).Focus();
            }
            catch (Exception)
            {
                Lst.Focus();
            }
        }

        public void Choose(string name)
        {
            var targets = Targets;
            Close();
            Host.ApplyWorkset(targets, name);
            try
            {
                Host.Window.Activate();
            }
            catch (Exception)
            {
            }
        }

        private void OnDeactivated(object sender, EventArgs args)
        {
            // A click anywhere else closes it, as a dropdown does, after the
            // deactivation has finished, not from inside it. Except straight
            // after opening: the second click of the double-click that opened it
            // lands on the grid, and closing then reopening it is a flicker. The
            // grid hands that click back through Reclaim(); anything else is
            // caught by the check once the moment has passed.
            if (_opened && (DateTime.UtcNow - _openedAt).TotalSeconds < GRACE_S)
            {
                try
                {
                    var timer = new DispatcherTimer();
                    timer.Interval = TimeSpan.FromMilliseconds(GRACE_S * 1000);
                    timer.Tick += (s2, a2) =>
                    {
                        timer.Stop();
                        if (!Closed && !Window.IsActive)
                            Close();
                    };
                    timer.Start();
                    return;
                }
                catch (Exception)
                {
                }
            }
            try
            {
                Window.Dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(Close));
            }
            catch (Exception)
            {
                Close();
            }
        }

        /// <summary>Take the focus back after the second click of a double-click.</summary>
        public void Reclaim()
        {
            try
            {
                Window.Activate();
                Box.Focus();
            }
            catch (Exception)
            {
            }
        }

        private void OnClosed(object sender, EventArgs args)
        {
            Closed = true;
            if (ReferenceEquals(Host.WsDropdown, this))
                Host.WsDropdown = null;
        }

        public void Close()
        {
            if (Closed)
                return;
            Closed = true;
            try
            {
                Window.Close();
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// Open under the cell (top..bottom in screen units), or above it when
        /// there is no room below, kept on the screen the grid is on.
        /// </summary>
        public void ShowAt(double left, double top, double bottom, double width)
        {
            Window w = Window;
            w.Width = Math.Max(260.0, width);
            int rows = Math.Min(Names.Count, LIST_MAX / ROW_PX);
            double est = 110.0 + rows * ROW_PX;
            var area = EfrUi.ScreenWorkArea(Host.Window);
            double y = bottom;
            if (y + est > area.Top + area.Height && top - est >= area.Top)
                y = top - est;
            double x = Math.Min(Math.Max(left, area.Left), area.Left + area.Width - w.Width);
            w.Left = x;
            w.Top = y;
            try
            {
                w.Owner = Host.Window;
            }
            catch (Exception)
            {
            }
            _openedAt = DateTime.UtcNow;
            _opened = true;
            w.Show();
            try
            {
                w.Activate();
            }
            catch (Exception)
            {
            }
            Box.Focus();
            if (!string.IsNullOrEmpty(Seed))
            {
                // typing on a Workset cell opens this with what was typed
                Box.Text = Seed;
                Box.CaretIndex = Seed.Length;
            }
        }
    }
}
