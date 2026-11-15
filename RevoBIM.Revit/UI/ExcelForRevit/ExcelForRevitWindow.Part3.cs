using System;
using System.Collections.Generic;
using System.Data;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Documents;
using System.Windows.Input;
using RevoBIM.Tools.ExcelForRevit;
using static RevoBIM.Tools.ExcelForRevit.Efr;

namespace RevoBIM.UI.ExcelForRevit
{
    // Excel for Revit: the window, part 3. Port of efr_core.py lines 6668-7510:
    // the Excel round trip, the formula bar, legend, theme and window size,
    // highlights, test (scratch) columns and the small status/pending/position helpers.
    //
    // Efr.* functions are always called qualified: several window methods share a name
    // with a module function (SaveSettings, ThemeName), and an unqualified call would
    // bind to the window's own method group first.
    public partial class ExcelForRevitWindow
    {
        // -- Excel round trip ---------------------------------------------------

        /// <summary>
        /// The grid as plain values, in the order the grid is currently showing.
        /// Scratch columns are left out: they mean nothing outside this window and would
        /// come back as unmatched headings.
        /// </summary>
        public (List<ExportField> Fields, List<ExportRow> Rows) ExportPayload()
        {
            ScheduleModel model = Model;
            var fields = new List<ExportField>();
            var keep = new List<FieldInfo>();
            foreach (FieldInfo fi in model.Fields)
            {
                if (fi.Scratch)
                    continue;
                keep.Add(fi);
                fields.Add(new ExportField(fi.Name, fi.Letter, fi.IsType, fi.Supported, fi.Reason));
            }
            var rows = new List<ExportRow>();
            List<int> order = VisibleRowOrder();
            foreach (int ridx in order)
            {
                RowInfo row = model.Rows[ridx];
                var er = new ExportRow();
                er.Eid = Efr.ToText(Efr.EidValue(row.ElemId));
                foreach (FieldInfo fi in keep)
                {
                    CellInfo ci = row.Cells[fi.Index];
                    er.Values.Add(model.CurrentText(row, fi.Index));
                    er.Editable.Add(ci.Editable);
                    er.IsType.Add(ci.IsType);
                }
                rows.Add(er);
            }
            return (fields, rows);
        }

        /// <summary>Row indexes as the grid shows them, so the export matches the screen.</summary>
        public List<int> VisibleRowOrder()
        {
            var output = new List<int>();
            try
            {
                for (int i = 0; i < Dg.Items.Count; i++)
                {
                    object item = Dg.Items[i];
                    if (IsHeaderRow(item))
                        continue;
                    output.Add(Convert.ToInt32(((DataRowView)item)["ridx"]));
                }
            }
            catch (Exception)
            {
                output = Model.Rows.Select(r => r.Ridx).ToList();
            }
            return output;
        }

        /// <summary>Both directions behind one button, since they are the same job.</summary>
        public void OnExcel(object sender = null, EventArgs args = null)
        {
            var dlg = new ThemedDialog("Excel", 560, null, Window, C_GREEN);
            dlg.Add(EfrUi.Tb("Take this schedule out to a workbook, or bring an edited one back.",
                             C_TEXT, 12, false, true));
            TextBlock note = EfrUi.Tb("Only the round-trip export can be imported again — the "
                                      + "presentation layout carries no Revit IDs to match on.",
                                      C_MUTED, 11, false, true);
            note.Margin = new Thickness(0, 10, 0, 0);
            dlg.Add(note);
            dlg.AddButton("Cancel", "ghost", null);
            dlg.AddButton("Import from Excel", "orange", "import");
            dlg.AddButton("Export to Excel", "green", "export");
            dlg.Show();
            string choice = dlg.ResultText;
            if (choice == "export")
                OnExport();
            else if (choice == "import")
                OnImport();
        }

        public void OnExport(object sender = null, EventArgs args = null)
        {
            try
            {
                EfrUi.ExportDialog(this);
            }
            catch (Exception ex)
            {
                EfrUi.ThemedMessage("Export to Excel",
                                    "The export could not be run:\n\n" + ex,
                                    Window, C_RED, 700);
            }
        }

        public void OnImport(object sender = null, EventArgs args = null)
        {
            // not ported: the "Excel module could not be loaded" branch (the bridge is compiled in)
            string path = EfrUi.AskOpenPath();
            if (string.IsNullOrEmpty(path))
                return;
            List<List<string>> table;
            try
            {
                table = XlsxIo.ReadSheet(path, 0);
            }
            catch (Exception ex)
            {
                EfrUi.ThemedMessage("Import from Excel",
                                    "That workbook could not be read:\n\n" + ex,
                                    Window, C_RED, 700);
                return;
            }

            var payload = ExportPayload();
            List<ExportField> fields = payload.Fields;
            List<ExportRow> rows = payload.Rows;
            // the field list the import matches against is the same one the export
            // wrote, so a scratch column can never collide with a real heading
            List<FieldInfo> keep = Model.Fields.Where(fi => !fi.Scratch).ToList();
            var byEid = new Dictionary<string, ExportRow>(StringComparer.Ordinal);
            foreach (ExportRow row in rows)
                byEid[row.Eid] = row;

            ImportResult res;
            try
            {
                res = ExcelBridge.ParseImport(table, fields, byEid);
            }
            catch (Exception ex)
            {
                EfrUi.ThemedMessage("Import from Excel",
                                    "That workbook could not be matched to this schedule:\n\n" + ex,
                                    Window, C_RED, 700);
                return;
            }

            if (res.Errors.Count > 0)
            {
                EfrUi.ThemedMessage("Import from Excel", string.Join("\n\n", res.Errors),
                                    Window, C_RED, 680);
                return;
            }

            EfrUi.RememberFolder(path);
            if (Convert.ToString(EfrUi.ImportReport(this, res, path)) != "stage")
            {
                SetStatus("Import cancelled — nothing was staged.");
                return;
            }

            var index = new Dictionary<string, int>(StringComparer.Ordinal);
            foreach (RowInfo row in Model.Rows)
                index[Efr.ToText(Efr.EidValue(row.ElemId))] = row.Ridx;

            BeginBatch();
            _importing = true;
            int staged = 0;
            int turned = 0;
            foreach (var change in res.Changes)
            {
                int ridx;
                if (!index.TryGetValue(change.Eid, out ridx))
                    continue;
                int fidx = change.FieldIndex;
                int real = fidx < keep.Count ? keep[fidx].Index : fidx;
                if (Stage(ridx, real, change.New))
                {
                    Imported.Add((ridx, real));
                    staged++;
                }
                else
                {
                    turned++;
                }
            }
            _importing = false;
            EndBatch();
            BuildLegend();
            RepaintSoon();
            string msg = string.Format("Imported {0} change{1} from {2} — check the grid, then press APPLY.",
                                       staged, staged == 1 ? "" : "s", Path.GetFileName(path));
            msg += SkippedNote(turned, "not imported");
            SetStatus(msg);
        }

        // -- formula bar --------------------------------------------------------

        public void WireFormulaBar(Func<string, object> f)
        {
            FormulaBar = (Border)f("FormulaBar");
            FormulaBox = (TextBox)f("FormulaBox");
            FormulaInk = (TextBlock)f("FormulaInk");
            FormulaHint = (TextBlock)f("FormulaHint");
            BtnPick = (Button)f("BtnFormulaPick");
            try
            {
                BtnPick.Click += (s, a) => OnPickToggle();
            }
            catch (Exception)
            {
            }
            try
            {
                ((Button)f("BtnFormulaApply")).Click += (s, a) => OnFormulaApply();
            }
            catch (Exception)
            {
            }
            try
            {
                ((Button)f("BtnFormulaCancel")).Click += (s, a) => OnFormulaCancel();
            }
            catch (Exception)
            {
            }
            try
            {
                FormulaBox.TextChanged += (s, a) => OnFormulaChanged();
                FormulaBox.PreviewKeyDown += OnFormulaKey;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Open the bar on the current selection, or shut it if it is open.</summary>
        public void OnFormula(object sender = null, EventArgs args = null)
        {
            if (FormulaBar == null)
            {
                EfrUi.ThemedMessage("Formula",
                                    "The formula bar did not load with the window, so it "
                                    + "cannot be opened. Please report this.",
                                    Window, C_RED);
                return;
            }
            try
            {
                if (FormulaBar.Visibility == Visibility.Visible)
                {
                    CloseFormulaBar();
                    return;
                }
            }
            catch (Exception)
            {
            }
            // opens whether or not anything is selected: an empty bar that says
            // what it needs is better than a button that appears to do nothing
            FormulaCells = EditableSelection();
            FormulaPick = FormulaCells.Count > 0;
            ShowPickState();
            try
            {
                FormulaBar.Visibility = Visibility.Visible;
                FormulaBox.Text = !string.IsNullOrEmpty(LastFormula) ? LastFormula : "=";
                FormulaBox.CaretIndex = FormulaBox.Text.Length;
                FormulaBox.Focus();
            }
            catch (Exception)
            {
            }
            PaintFormula();
            ReflowToolbar();
        }

        public List<SelCell> EditableSelection()
        {
            var output = new List<SelCell>();
            foreach (SelCell c in SelCells())
            {
                try
                {
                    if (Model.Rows[c.Ridx].Cells[c.Fidx].Editable)
                        output.Add(c);
                }
                catch (Exception)
                {
                    continue;
                }
            }
            return output;
        }

        public void OnPickToggle(object sender = null, EventArgs args = null)
        {
            FormulaPick = !FormulaPick;
            if (FormulaPick)
            {
                List<SelCell> now = EditableSelection();
                if (now.Count > 0)
                    FormulaCells = now;
            }
            ShowPickState();
            PaintFormula();
        }

        public void ShowPickState()
        {
            if (BtnPick == null)
                return;
            try
            {
                BtnPick.Content = FormulaPick ? "Picking refs" : "Pick refs";
                BtnPick.Foreground = Efr.Brush(FormulaPick ? C_ORANGE : C_MUTED);
                BtnPick.ToolTip = FormulaPick
                    ? "Clicking a cell puts its reference in the formula — turn off "
                      + "to choose the cells to write into instead"
                    : "Clicking a cell selects it as a target — turn on to put cell "
                      + "references into the formula instead";
            }
            catch (Exception)
            {
            }
        }

        public void CloseFormulaBar()
        {
            FormulaCells = new List<SelCell>();
            FormulaPick = true;
            // kept as the Python has it: once closed, the pick button's label is no longer repainted
            BtnPick = null;
            try
            {
                FormulaBar.Visibility = Visibility.Collapsed;
            }
            catch (Exception)
            {
            }
            FocusGrid();
        }

        public void OnFormulaCancel(object sender = null, EventArgs args = null)
        {
            CloseFormulaBar();
            SetStatus("Formula cancelled.");
        }

        public bool FormulaOpen()
        {
            try
            {
                return FormulaBar.Visibility == Visibility.Visible;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public void OnFormulaChanged(object sender = null, EventArgs args = null)
        {
            PaintFormula();
        }

        public void OnFormulaKey(object sender, KeyEventArgs args)
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
            if (key == Key.Enter)
            {
                args.Handled = true;
                OnFormulaApply();
            }
            else if (key == Key.Escape)
            {
                args.Handled = true;
                OnFormulaCancel();
            }
        }

        /// <summary>Redraw the coloured text behind the editor, and preview a row.</summary>
        public void PaintFormula()
        {
            string text = "";
            try
            {
                text = FormulaBox.Text ?? "";
            }
            catch (Exception)
            {
            }
            try
            {
                FormulaInk.Inlines.Clear();
                var order = new List<string>();
                foreach (var span in Efr.FormulaSpans(text))
                {
                    var run = new Run(text.Substring(span.Start, span.Length));
                    if (span.Kind == "cell")
                    {
                        run.Foreground = Efr.Brush(Efr.FormulaRefColour(span.Key, order));
                        run.FontWeight = FontWeights.Bold;
                    }
                    else if (span.Kind == "func")
                    {
                        run.Foreground = Efr.Brush(C_ORANGE);
                        run.FontWeight = FontWeights.Bold;
                    }
                    else if (span.Kind == "text")
                    {
                        run.Foreground = Efr.Brush(C_EDIT_FG);
                    }
                    else if (span.Kind == "number")
                    {
                        run.Foreground = Efr.Brush(C_IMP_FG);
                    }
                    else if (span.Kind == "op")
                    {
                        run.Foreground = Efr.Brush(C_MUTED);
                    }
                    else
                    {
                        run.Foreground = Efr.Brush(C_TEXT);
                    }
                    FormulaInk.Inlines.Add(run);
                }
            }
            catch (Exception)
            {
            }
            PreviewFormula(text);
        }

        public void PreviewFormula(string text)
        {
            List<SelCell> cells = FormulaCells;
            if (cells == null || cells.Count == 0)
            {
                try
                {
                    FormulaHint.Text = "No cells picked to write into. Turn Pick refs off and "
                                       + "select the cells you want the result in.";
                    FormulaHint.Foreground = Efr.Brush(C_ORANGE);
                }
                catch (Exception)
                {
                }
                return;
            }
            try
            {
                if (Efr.ToText(text).Trim().TrimStart('=').Length == 0)
                {
                    FormulaHint.Text = "Type a formula, or click cells in the table to put their "
                                       + "references into it. A5 means that cell and follows the row "
                                       + "down; A$5 stays on row 5; a bare A is this row.";
                    FormulaHint.Foreground = Efr.Brush(C_MUTED);
                    return;
                }
            }
            catch (Exception)
            {
            }
            int ok = 0;
            string first = "";
            string error = "";
            for (int i = 0; i < cells.Count; i++)
            {
                IFormulaContext ctx = FormulaContext(cells[i], i + 1);
                string output;
                try
                {
                    output = Efr.EvaluateFormula(text, ctx);
                }
                catch (FormulaError err)
                {
                    error = err.Message;
                    break;
                }
                catch (Exception)
                {
                    error = "that formula could not be read";
                    break;
                }
                ok++;
                if (first.Length == 0)
                    first = output;
            }
            try
            {
                if (error.Length > 0)
                {
                    FormulaHint.Text = error;
                    FormulaHint.Foreground = Efr.Brush(C_FAIL_FG);
                }
                else
                {
                    FormulaHint.Text = string.Format("{0} → \"{1}\"   and {2} cell{3} in all",
                                                     "first cell", first, ok, ok == 1 ? "" : "s");
                    FormulaHint.Foreground = Efr.Brush(C_EDIT_FG);
                }
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Put a clicked cell's address into the formula at the caret.</summary>
        public bool InsertReference(int ridx, FieldInfo fi)
        {
            if (!FormulaOpen())
                return false;
            try
            {
                int rowNumber = Model.Rows[ridx].Ridx + 1;
                string reference = fi.Letter + rowNumber.ToString(System.Globalization.CultureInfo.InvariantCulture);
                TextBox box = FormulaBox;
                int at = box.CaretIndex;
                string text = box.Text ?? "";
                if (at > text.Length)
                    at = text.Length;
                box.Text = text.Substring(0, at) + reference + text.Substring(at);
                box.CaretIndex = at + reference.Length;
                box.Focus();
            }
            catch (Exception)
            {
                return false;
            }
            return true;
        }

        public void OnFormulaApply(object sender = null, EventArgs args = null)
        {
            string text = "";
            try
            {
                text = FormulaBox.Text ?? "";
            }
            catch (Exception)
            {
            }
            List<SelCell> cells = FormulaCells;
            if (cells == null || cells.Count == 0 || Efr.ToText(text).Trim().TrimStart('=').Length == 0)
                return;
            var values = new List<(SelCell Cell, string Value)>();
            for (int i = 0; i < cells.Count; i++)
            {
                IFormulaContext ctx = FormulaContext(cells[i], i + 1);
                try
                {
                    values.Add((cells[i], Efr.EvaluateFormula(text, ctx)));
                }
                catch (FormulaError err)
                {
                    FormulaHint.Text = err.Message;
                    FormulaHint.Foreground = Efr.Brush(C_FAIL_FG);
                    return;
                }
                catch (Exception)
                {
                    FormulaHint.Text = "that formula could not be read";
                    FormulaHint.Foreground = Efr.Brush(C_FAIL_FG);
                    return;
                }
            }
            LastFormula = text;
            BeginBatch();
            int n = 0;
            foreach (var item in values)
            {
                if (StageCell(item.Cell.Pos, item.Cell.Col, item.Value))
                    n++;
            }
            EndBatch();
            CloseFormulaBar();
            SetStatus(string.Format("Formula wrote {0} cell{1}.", n, n == 1 ? "" : "s"));
        }

        // -- legend, theme, window size ----------------------------------------

        /// <summary>The footer key. Rebuilt on a theme switch so it always matches.</summary>
        public void BuildLegend()
        {
            WrapPanel host = LegendHost;
            if (host == null)
                return;
            try
            {
                host.Children.Clear();
            }
            catch (Exception)
            {
                return;
            }
            TextBlock cap = EfrUi.Tb("Cell colours", C_MUTED, 11, true);
            cap.VerticalAlignment = VerticalAlignment.Center;
            cap.Margin = new Thickness(0, 0, 10, 0);
            host.Children.Add(cap);
            var entries = new List<(string Bg, string Fg, string Edge, string Label)>
            {
                (C_INST_BG, C_INST_FG, C_BLUE, "Instance parameter — edits this element only"),
                (C_TYPE_BG, C_TYPE_FG, C_ORANGE, "Type parameter — edits every element of that type"),
                (C_RO_BG, C_RO_FG, C_RO_FG, "Not editable — read only"),
                (C_EDIT_BG, C_EDIT_FG, C_GREEN, "Edited — not yet applied"),
                (C_FAIL_BG, C_FAIL_FG, C_RED, "Refused by Revit"),
            };
            if (Imported.Count > 0)
                entries.Add((C_IMP_BG, C_IMP_FG, C_IMP_FG, "Changed by the Excel import — not yet applied"));
            if (Scratch > 0)
                entries.Add((C_TEST_BG, C_TEST_FG, C_TEST_FG, "Test column — never written to the model"));
            foreach (var entry in entries)
            {
                var chip = new Border();
                chip.Background = Efr.Brush(entry.Bg);
                chip.BorderBrush = Efr.Brush(entry.Edge);
                chip.BorderThickness = new Thickness(1);
                chip.CornerRadius = new CornerRadius(2);
                chip.Padding = new Thickness(7, 2, 7, 2);
                chip.Margin = new Thickness(0, 0, 6, 3);
                chip.Child = EfrUi.Tb(entry.Label, entry.Fg, 11);
                host.Children.Add(chip);
            }
        }

        public void OnTheme(object sender = null, EventArgs args = null)
        {
            SetThemeTo(Efr.ThemeName == "dark" ? "light" : "dark");
        }

        public void SetThemeTo(string name)
        {
            Efr.SetTheme(name);
            ResourceDictionary res = Window.Resources;
            foreach (var item in EfrUi.PaletteBrushes())
            {
                try
                {
                    res[item.Key] = Efr.Brush(item.Colour);
                }
                catch (Exception)
                {
                }
            }
            // toolbar glyphs and labels
            foreach (Button btn in ToolButtons.Values)
            {
                if (btn == null)
                    continue;
                try
                {
                    var tag = EfrUi.IconTag(btn);
                    tag.Image.Source = EfrUi.ToolbarIcon(tag.IconName);
                    tag.Text.Foreground = Efr.Brush(C_TEXT);
                }
                catch (Exception)
                {
                }
            }
            try
            {
                foreach (Button button in new[] { BtnExcel, BtnIsolate })
                {
                    var tag = EfrUi.IconTag(button);
                    tag.Image.Source = EfrUi.ToolbarIcon(tag.IconName);
                    tag.Text.Foreground = Efr.Brush(C_TEXT);
                }
            }
            catch (Exception)
            {
            }
            ShowThemeState();
            // headers are built in code, so their brushes need setting by hand
            try
            {
                foreach (var box in HeaderBoxes.Values)
                    box.Foreground = Efr.Brush(C_TEXT);
            }
            catch (Exception)
            {
            }
            MarkFilteredColumns();
            MarkSortedColumn();
            ShowGroupState();
            ShowExpandState();
            // the cell editor is built in code, so it needs rebuilding by hand
            try
            {
                Style style = MakeEditStyle();
                foreach (DataGridColumn col in FieldCols)
                {
                    var textCol = col as DataGridTextColumn;
                    if (textCol != null)
                        textCol.EditingElementStyle = style;
                }
            }
            catch (Exception)
            {
            }
            BuildLegend();
            SaveSettings();
            _dirtyPaint = true;
            RepaintSoon();
            SetStatus(string.Format("Switched to the {0} canvas.", Efr.ThemeName));
        }

        /// <summary>What the egg asks for, so its games open in the right palette.</summary>
        public string ThemeName()
        {
            return Efr.ThemeName;
        }

        /// <summary>
        /// The chip names the canvas it is on; the tooltip names the switch. Both readings of a
        /// theme button are common (the mode you are in, the mode you would go to), so it says
        /// one and explains the other rather than leaving it ambiguous.
        /// </summary>
        public void ShowThemeState()
        {
            if (Drawer != null)
            {
                // the arrow carries a local brush, which a palette swap cannot
                // reach, so it is repainted alongside the chip
                Drawer.PaintButton();
            }
            if (BtnTheme == null)
                return;
            try
            {
                bool light = Efr.ThemeName == "light";
                BtnTheme.Content = light ? "Light" : "Dark";
                BtnTheme.ToolTip = light
                    ? "Light canvas — click for dark (Ctrl+Shift+T)"
                    : "Dark canvas — click for light (Ctrl+Shift+T)";
            }
            catch (Exception)
            {
            }
        }

        public void OnMaximise(object sender = null, EventArgs args = null)
        {
            if (Drawer != null && Drawer.Shrunk)
            {
                // F11 or a double-click on the parked bar means "bring it back",
                // not "fill the screen with a window nobody can see"
                Drawer.Expand();
                return;
            }
            Window w = Window;
            try
            {
                if (RestoreRect == null)
                {
                    Vstretch = null;
                    RestoreRect = (w.Left, w.Top, w.Width, w.Height);
                    var area = WindowWorkArea();
                    w.Left = area.Left;
                    w.Top = area.Top;
                    w.Width = area.Width;
                    w.Height = area.Height;
                    if (MaxBtn != null)
                    {
                        MaxBtn.Content = "❐";
                        MaxBtn.ToolTip = "Restore the window size (F11)";
                    }
                }
                else
                {
                    var rect = RestoreRect.Value;
                    RestoreRect = null;
                    w.Left = rect.Left;
                    w.Top = rect.Top;
                    w.Width = rect.Width;
                    w.Height = rect.Height;
                    if (MaxBtn != null)
                        MaxBtn.ToolTip = "Full screen (F11, or double-click the header)";
                }
            }
            catch (Exception)
            {
            }
            RepaintSoon();
        }

        // -- highlights ---------------------------------------------------------

        /// <summary>Cell beats row beats column, so a single cell can override a band. Null when none applies.</summary>
        public (string Colour, string Mode)? HighlightFor(int ridx, int fidx)
        {
            (string, string) hit;
            if (CellHl.TryGetValue((ridx, fidx), out hit))
                return hit;
            if (RowHl.TryGetValue(ridx, out hit))
                return hit;
            if (ColHl.TryGetValue(fidx, out hit))
                return hit;
            return null;
        }

        public void OnHighlight(object sender = null, EventArgs args = null)
        {
            try
            {
                EfrUi.HighlightDialog(this);
            }
            catch (Exception)
            {
                SetStatus("The highlight tool could not be opened.");
            }
        }

        public int ApplyHighlight(string colour, string mode, string scope)
        {
            List<SelCell> cells = SelCells();
            if (cells.Count == 0)
            {
                SetStatus("Select the cells to highlight first.");
                return 0;
            }
            int n = 0;
            if (scope == "rows")
            {
                foreach (int ridx in new HashSet<int>(cells.Select(c => c.Ridx)))
                {
                    RowHl[ridx] = (colour, mode);
                    n++;
                }
            }
            else if (scope == "cols")
            {
                foreach (int fidx in new HashSet<int>(cells.Select(c => c.Fidx)))
                {
                    ColHl[fidx] = (colour, mode);
                    n++;
                }
            }
            else
            {
                foreach (SelCell c in cells)
                {
                    CellHl[(c.Ridx, c.Fidx)] = (colour, mode);
                    n++;
                }
            }
            RepaintSoon();
            return n;
        }

        public int ClearHighlight(string scope)
        {
            List<SelCell> cells = SelCells();
            int n = 0;
            if (scope == "all")
            {
                n = CellHl.Count + RowHl.Count + ColHl.Count;
                CellHl.Clear();
                RowHl.Clear();
                ColHl.Clear();
            }
            else
            {
                foreach (SelCell c in cells)
                {
                    if (CellHl.Remove((c.Ridx, c.Fidx)))
                        n++;
                    if (RowHl.Remove(c.Ridx))
                        n++;
                    if (ColHl.Remove(c.Fidx))
                        n++;
                }
            }
            RepaintSoon();
            return n;
        }

        // -- scratch columns ----------------------------------------------------

        /// <summary>
        /// A last column carrying nothing but the green +. A DataGrid has nowhere to hang a
        /// control at the right of the header strip, so the + is the header of a column of its
        /// own. It stays last, and new scratch columns are inserted in front of it.
        /// </summary>
        public DataGridTextColumn AddColumnButton()
        {
            var col = new DataGridTextColumn();
            var button = new Button();
            button.Content = "+";
            button.ToolTip = "Add a test column — scratch space for building "
                             + "formulas, never written to the model";
            try
            {
                button.Style = (Style)Window.Resources["AddColBtn"];
            }
            catch (Exception)
            {
            }
            button.Click += (sender, args) => OnAddScratch();
            col.Header = button;
            col.Width = new DataGridLength(40, DataGridLengthUnitType.Pixel);
            col.CanUserSort = false;
            col.CanUserResize = false;
            col.IsReadOnly = true;
            Dg.Columns.Add(col);
            PlusCol = col;
            return col;
        }

        public void OnAddScratch()
        {
            if (AddScratchColumn())
            {
                SetStatus(string.Format("Added test column {0} — it takes formulas like any "
                                        + "other and is never written to the model.",
                                        Model.Fields[Model.Fields.Count - 1].Letter));
            }
        }

        public bool AddScratchColumn()
        {
            ScheduleModel model = Model;
            if (model.Fields.Count >= 60)
                return false;
            var fi = new FieldInfo();
            fi.Index = model.Fields.Count;
            fi.Col = "s" + Scratch.ToString(System.Globalization.CultureInfo.InvariantCulture);
            fi.Letter = Efr.ColLetter(fi.Index);
            fi.Name = "Test " + (Scratch + 1).ToString(System.Globalization.CultureInfo.InvariantCulture);
            fi.Scratch = true;
            fi.Supported = true;
            model.Fields.Add(fi);
            foreach (RowInfo row in model.Rows)
            {
                var ci = new CellInfo();
                ci.Editable = true;
                ci.Scratch = true;
                ci.Original = "";
                row.Cells.Add(ci);
            }
            try
            {
                Table.Columns.Add(fi.Col);
                foreach (RowInfo row in model.Rows)
                    Table.Rows[row.Ridx][fi.Col] = "";
            }
            catch (Exception)
            {
                return false;
            }
            var col = new DataGridTextColumn();
            col.Header = ColumnHeader(fi);
            col.Binding = new Binding(fi.Col);
            col.Width = new DataGridLength(150, DataGridLengthUnitType.Pixel);
            col.EditingElementStyle = MakeEditStyle();
            try
            {
                int at = Dg.Columns.IndexOf(PlusCol);
                if (at < 0)
                    at = Dg.Columns.Count;
                Dg.Columns.Insert(at, col);
            }
            catch (Exception)
            {
                Dg.Columns.Add(col);
            }
            ColField[col] = fi;
            FieldCols.Add(col);
            Scratch++;
            RefreshScratchHeaders();
            BuildLegend();
            RepaintSoon();
            return true;
        }

        public bool RemoveScratchColumn()
        {
            ScheduleModel model = Model;
            if (Scratch == 0)
                return false;
            FieldInfo fi = model.Fields[model.Fields.Count - 1];
            if (!fi.Scratch)
                return false;
            DataGridColumn col = null;
            foreach (var pair in ColField)
            {
                if (ReferenceEquals(pair.Value, fi))
                {
                    col = pair.Key;
                    break;
                }
            }
            try
            {
                if (col != null)
                {
                    Dg.Columns.Remove(col);
                    ColField.Remove(col);
                    FieldCols.Remove(col);
                }
                Table.Columns.Remove(fi.Col);
            }
            catch (Exception)
            {
            }
            model.Fields.RemoveAt(model.Fields.Count - 1);
            foreach (RowInfo row in model.Rows)
            {
                if (row.Cells.Count > 0)
                    row.Cells.RemoveAt(row.Cells.Count - 1);
                model.ScratchValues.Remove(EditKey.Scratch(row.Ridx, fi.Index));
            }
            foreach (int key in ColHl.Keys.ToList())
            {
                if (key >= fi.Index)
                    ColHl.Remove(key);
            }
            foreach (var key in CellHl.Keys.ToList())
            {
                if (key.Item2 >= fi.Index)
                    CellHl.Remove(key);
            }
            Scratch--;
            RefreshScratchHeaders();
            BuildLegend();
            RepaintSoon();
            return true;
        }

        /// <summary>
        /// Rebuild the test columns' headings, so the remove button sits on whichever one is now last.
        /// </summary>
        public void RefreshScratchHeaders()
        {
            try
            {
                foreach (var pair in ColField.ToList())
                {
                    if (pair.Value.Scratch)
                        pair.Key.Header = ColumnHeader(pair.Value);
                }
            }
            catch (Exception)
            {
            }
        }

        public Style MakeEditStyle()
        {
            var style = new Style(typeof(TextBox));
            style.Setters.Add(new Setter(TextBox.BackgroundProperty, Efr.Brush(C_EDITOR_BG)));
            style.Setters.Add(new Setter(TextBox.ForegroundProperty, Efr.Brush(C_EDITOR_FG)));
            style.Setters.Add(new Setter(TextBox.BorderBrushProperty, Efr.Brush(C_ORANGE)));
            style.Setters.Add(new Setter(TextBox.BorderThicknessProperty, new Thickness(1)));
            style.Setters.Add(new Setter(TextBox.PaddingProperty, new Thickness(4, 0, 0, 0)));
            style.Setters.Add(new Setter(TextBox.CaretBrushProperty, Efr.Brush(C_ORANGE)));
            return style;
        }

        public void SaveSettings()
        {
            try
            {
                Efr.SaveSettings(new Dictionary<string, object> { { "theme", Efr.ThemeName } });
            }
            catch (Exception)
            {
            }
        }

        // -- small utilities ----------------------------------------------------
        // not ported: prove_alive / on_any_mouse (the IronPython liveness proof)

        public void SetStatus(string text)
        {
            try
            {
                Status.Text = text;
            }
            catch (Exception)
            {
            }
        }

        public void UpdatePending()
        {
            int n = Model.Edits.Count;
            int levels = Model.LevelEdits.Count;
            try
            {
                if (n > 0 || levels > 0)
                {
                    var bits = new List<string>();
                    if (n > 0)
                        bits.Add(string.Format("{0} cell edit{1}", n, n == 1 ? "" : "s"));
                    if (levels > 0)
                        bits.Add(string.Format("{0} level change{1}", levels, levels == 1 ? "" : "s"));
                    Pending.Text = string.Format("{0} pending — nothing is written until APPLY",
                                                 string.Join(" and ", bits));
                    Pending.Foreground = Efr.Brush(C_EDIT_FG);
                }
                else
                {
                    Pending.Text = "No pending edits";
                    Pending.Foreground = Efr.Brush(C_MUTED);
                }
                BtnApply.IsEnabled = n > 0 || levels > 0;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// Where each model row sits in the grid as it is currently ordered. Walking every row
        /// costs three calls into .NET per row, and this was rebuilt on every scroll tick and
        /// every selection change, so it is kept until the view's order can have changed (the
        /// DataView reports every sort, filter and row change through ListChanged), with the
        /// row count checked as well as a second line of defence.
        /// </summary>
        public Dictionary<int, int> PosMap()
        {
            ItemCollection items = Dg.Items;
            int count = items.Count;
            if (_posCache != null && _posCache.Value.Count == count)
                return _posCache.Value.Map;
            var output = new Dictionary<int, int>();
            for (int i = 0; i < count; i++)
            {
                try
                {
                    output[Convert.ToInt32(((DataRowView)items[i])["ridx"])] = i;
                }
                catch (Exception)
                {
                }
            }
            _posCache = (count, output);
            return output;
        }

        /// <summary>The rows have been sorted, filtered, added to or edited.</summary>
        public void OnViewChanged(object sender = null, EventArgs args = null)
        {
            _posCache = null;
            _lastSel = Efr.Stale;
        }

        /// <summary>
        /// A column moved or was added, so the right-most selected cell may be a different one:
        /// the fill handle has to look again. A rebuild adds every column in turn, so this goes
        /// through the same once-per-burst queue as a selection change.
        /// </summary>
        public void OnColumnsChanged(object sender = null, EventArgs args = null)
        {
            OnSelectionChanged(sender, args);
        }
    }
}
