using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using Microsoft.Win32;
using RevoBIM.Tools.ViewManager;

namespace RevoBIM.UI.ViewManager
{
    /// <summary>
    /// View Reference Manager tab (port of RefsTab): every view, the columns that matter, edits staged in the grid, Excel out
    /// and back, and the title and detail number builders.
    /// </summary>
    internal sealed class VmRefsTab : IVmBuilderHost
    {
        private readonly VmWindow owner;
        private readonly ComboBox typeCombo, filterCol, filterVal, setCol, setChoice, sheetCombo;
        private readonly TextBox searchBox, colSearch, setText, pickSearch;
        private readonly TextBlock summary, reportTitle, reportText, colNote, pickTitle, pickNote;
        private readonly Button btnBuilder, btnDetail, btnSet;
        private readonly FrameworkElement overlay, reportPanel, colPanel, pickPanel;
        private readonly StackPanel colList, pickList;

        private List<long> pickTargets = new List<long>();
        private string pickKey;
        private string sheetMode = "any";
        private string fcolKey;
        private string fval;
        private List<string> fvalValues = new List<string>();
        private List<string> setKeys = new List<string>();
        private List<string> setChoiceValues = new List<string>();
        private string pickerSig;

        private List<VmCore.RefRow> rows = new List<VmCore.RefRow>();
        private List<VmCore.RefRow> shown = new List<VmCore.RefRow>();
        private readonly VmCore.EditStore store = new VmCore.EditStore();
        public VmCore.EditStore Store { get { return store; } }
        private List<VmCore.Field> fields;
        private string typeName;
        private List<string> typeValues = new List<string>();
        private string search = "";
        private string sortKey = "name";
        private bool sortDesc;
        private bool loaded;
        private bool loading;
        private VmXlsx.ImportPlan plan;
        private List<VmRevit.ParamName> colNames = new List<VmRevit.ParamName>();
        private VmBuilderWindow builder;
        private readonly VmGridHost host;
        private readonly DispatcherTimer timer;

        public VmRefsTab(VmWindow owner)
        {
            this.owner = owner;
            Window w = owner.Window;
            typeCombo = (ComboBox)w.FindName("RfType");
            searchBox = (TextBox)w.FindName("RfSearch");
            summary = (TextBlock)w.FindName("RfSummary");
            btnBuilder = (Button)w.FindName("BtnRfBuilder");
            overlay = (FrameworkElement)w.FindName("RefOverlay");
            reportPanel = (FrameworkElement)w.FindName("RfReportPanel");
            reportTitle = (TextBlock)w.FindName("RfReportTitle");
            reportText = (TextBlock)w.FindName("RfReportText");
            colPanel = (FrameworkElement)w.FindName("RfColPanel");
            colNote = (TextBlock)w.FindName("RfColNote");
            colSearch = (TextBox)w.FindName("RfColSearch");
            colList = (StackPanel)w.FindName("RfColList");
            filterCol = (ComboBox)w.FindName("RfFilterCol");
            filterVal = (ComboBox)w.FindName("RfFilterVal");
            setCol = (ComboBox)w.FindName("RfSetCol");
            setText = (TextBox)w.FindName("RfSetText");
            setChoice = (ComboBox)w.FindName("RfSetChoice");
            btnSet = (Button)w.FindName("BtnRfSet");
            btnDetail = (Button)w.FindName("BtnRfDetail");
            sheetCombo = (ComboBox)w.FindName("RfSheet");
            pickPanel = (FrameworkElement)w.FindName("RfPickPanel");
            pickTitle = (TextBlock)w.FindName("RfPickTitle");
            pickNote = (TextBlock)w.FindName("RfPickNote");
            pickSearch = (TextBox)w.FindName("RfPickSearch");
            pickList = (StackPanel)w.FindName("RfPickList");

            fields = SavedFields();
            string saved = (VmCore.Get("ref_type") ?? "").Trim();
            typeName = saved.Length > 0 ? saved : null;

            host = new VmGridHost(w, (DataGrid)w.FindName("RefGrid"), Store, Say);
            host.OnSort = OnSort;
            host.OnPlus = OpenColumns;
            host.OnRemove = RemoveColumn;
            host.OnChanged = OnChanged;
            host.OnSelection = UpdateState;
            host.OnChoose = OpenChoice;

            timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(260) };
            timer.Tick += (s, e) => Guard("search timer", OnTimer);

            typeCombo.SelectionChanged += (s, e) => Guard("type", OnTypeChanged);
            searchBox.TextChanged += (s, e) => Guard("search", () => { timer.Stop(); timer.Start(); });
            btnBuilder.Click += (s, e) => Guard("builder", () => OpenBuilder("title"));
            btnDetail.Click += (s, e) => Guard("detail builder", () => OpenBuilder("detail"));
            sheetCombo.SelectionChanged += (s, e) => Guard("sheet filter", OnSheetMode);
            ((Button)w.FindName("RfPickClose")).Click += (s, e) => Guard("close", OnClosePanels);
            pickSearch.TextChanged += (s, e) => Guard("pick search", BuildPickList);
            foreach (string label in new[] { "All views", "On a sheet", "Not on a sheet" }) sheetCombo.Items.Add(label);
            sheetCombo.SelectedIndex = 0;
            ((Button)w.FindName("BtnRfPush")).Click += (s, e) => Guard("push", OnPush);
            ((Button)w.FindName("BtnRfPull")).Click += (s, e) => Guard("pull", OnPull);
            ((Button)w.FindName("RfReportStage")).Click += (s, e) => Guard("stage", OnStagePlan);
            ((Button)w.FindName("RfReportCancel")).Click += (s, e) => Guard("close", OnClosePanels);
            ((Button)w.FindName("RfColClose")).Click += (s, e) => Guard("close", OnClosePanels);
            colSearch.TextChanged += (s, e) => Guard("col search", BuildColumnList);
            filterCol.SelectionChanged += (s, e) => Guard("filter col", OnFilterCol);
            filterVal.SelectionChanged += (s, e) => Guard("filter val", OnFilterVal);
            setCol.SelectionChanged += (s, e) => Guard("set col", () => { if (!loading) ShowSetInput(); });
            btnSet.Click += (s, e) => Guard("set selected", OnSetSelected);
        }

        private void Guard(string name, Action a) { owner.Guard(name, a); }

        // ---------------------------------------------------------------- small things --

        private void Say(string message, bool error = false) { owner.SetStatus(message, error); }

        private List<VmCore.Field> SavedFields()
        {
            var list = new List<VmCore.Field>(VmCore.DefaultFields);
            var have = new HashSet<string>(list.Select(f => f.Key));
            foreach (string key in (VmCore.Get("ref_columns") ?? "").Split('|'))
            {
                if (key.Length == 0) continue;
                VmCore.Field field = VmCore.FieldFromKey(key);
                if (field != null && have.Add(field.Key)) list.Add(field);
            }
            return list;
        }

        private static bool IsDefault(string key)
        {
            return VmCore.DefaultFields.Any(d => d.Key == key);
        }

        private void SaveFields()
        {
            string[] extra = fields.Where(f => !IsDefault(f.Key)).Select(f => f.Key.Replace("|", "/")).ToArray();
            VmCore.Settings["ref_columns"] = string.Join("|", extra);
            VmCore.Settings["ref_type"] = typeName ?? "";
            string note;
            VmCore.SaveSettings(out note);
        }

        private List<string> ParamNames()
        {
            return fields.Where(f => f.Kind == "param").Select(f => f.Param).ToList();
        }

        // ---------------------------------------------------------------- loading --

        public void Activate()
        {
            if (!loaded) Reload();
            else UpdateState();
        }

        private void LoadRows(List<VmCore.RefRow> list)
        {
            rows = list;
            try
            {
                Store.Choices = VmRevit.CollectChoices(owner.Doc);
            }
            catch (Exception ex)
            {
                Store.Choices = new Dictionary<string, List<string>>();
                owner.Log.Add("choices failed: " + VmCore.Describe(ex));
            }
            Store.Load(list);
            host.ChoiceKeys = new HashSet<string>(Store.Choices.Keys);
        }

        public void Reload()
        {
            LoadRows(VmRevit.ReadViewRefs(owner.Doc, ParamNames(), owner.Log));
            loaded = true;
            RebuildTypes();
            RebuildGrid();
            Say("Read " + rows.Count + " view(s).");
        }

        private void RebuildTypes()
        {
            loading = true;
            try
            {
                List<VmCore.TypeOption> options = VmCore.TypeOptions(rows);
                typeValues = new List<string> { null };
                typeValues.AddRange(options.Select(o => o.Name));
                typeCombo.Items.Clear();
                typeCombo.Items.Add("All views (" + rows.Count + ")");
                foreach (VmCore.TypeOption o in options) typeCombo.Items.Add(o.Label + " (" + o.Count + ")");
                int index = typeValues.IndexOf(typeName);
                if (typeName != null && index >= 0) typeCombo.SelectedIndex = index;
                else
                {
                    typeName = null;
                    typeCombo.SelectedIndex = 0;
                }
            }
            finally
            {
                loading = false;
            }
        }

        private void RebuildGrid()
        {
            RefreshPickers();
            FillFilterValues();
            shown = VmCore.FilterAndSort(rows, Store, fields, typeName, search, sortKey, sortDesc,
                                         fval != null ? fcolKey : null, fval, sheetMode);
            host.Fields = fields;
            host.SortKey = sortKey;
            host.SortDesc = sortDesc;
            host.Removable = new HashSet<string>(fields.Where(f => !IsDefault(f.Key)).Select(f => f.Key));
            host.Build(shown);
            UpdateState();
        }

        public void UpdateState()
        {
            bool busy = owner.Busy;
            int selected = host.SelectedIds().Count;
            int edits = Store.Edits.Count;
            btnBuilder.IsEnabled = selected > 0 && !busy;
            btnDetail.IsEnabled = selected > 0 && !busy;
            btnSet.IsEnabled = selected > 0 && !busy;
            owner.BtnRfApply.IsEnabled = edits > 0 && !busy;
            owner.BtnRfRevert.IsEnabled = edits > 0 && !busy;
            owner.BtnRfApply.Content = edits > 0 ? "Apply to Revit (" + edits + ")" : "Apply to Revit";
            if (!busy)
                summary.Text = shown.Count + " of " + rows.Count + " view(s)   |   " + edits + " edit(s) staged   |   " + selected + " selected   |   double-click a cell, or press F2, to edit";
        }

        // ---------------------------------------------------------------- grid events --

        private void OnChanged()
        {
            Guard("changed", () =>
            {
                UpdateState();
                Say(Store.Edits.Count + " edit(s) staged - press Apply to Revit to write them.");
            });
        }

        private void OnTypeChanged()
        {
            if (loading) return;
            int index = typeCombo.SelectedIndex;
            if (index < 0 || index >= typeValues.Count) return;
            typeName = typeValues[index];
            SaveFields();
            RebuildGrid();
        }

        private void OnTimer()
        {
            timer.Stop();
            search = searchBox.Text ?? "";
            if (loaded) RebuildGrid();
        }

        private void OnSort(string key)
        {
            Guard("sort", () =>
            {
                if (sortKey == key) sortDesc = !sortDesc;
                else
                {
                    sortKey = key;
                    sortDesc = false;
                }
                RebuildGrid();
            });
        }

        // ---------------------------------------------------------------- choosing from a list: view template, viewport type --

        private void OpenChoice(long viewId, VmCore.Field field)
        {
            Guard("choice", () =>
            {
                List<long> selected = host.SelectedIds();
                List<long> before = new List<long>(host.DownSel ?? new List<long>());
                host.DownSel = new List<long>();
                if (before.Contains(viewId) && before.Count > selected.Count) selected = before;
                pickTargets = selected.Contains(viewId) ? selected : new List<long> { viewId };
                pickKey = field.Key;
                pickTitle.Text = field.Label;
                int count = pickTargets.Count;
                pickNote.Text = count > 1 ? "Applies to the " + count + " selected view(s)." : "Applies to this view.";
                pickSearch.Text = "";
                BuildPickList();
                ShowPanel("pick");
            });
        }

        private static string[] Words(string text)
        {
            return (text ?? "").ToLowerInvariant().Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
        }

        private void BuildPickList()
        {
            pickList.Children.Clear();
            string[] words = Words(pickSearch.Text);
            List<string> choices;
            if (pickKey == null || !Store.Choices.TryGetValue(pickKey, out choices)) choices = new List<string>();
            for (int index = 0; index < choices.Count; index++)
            {
                string value = choices[index];
                string label = value.Length > 0 ? value : "(none - remove the template)";
                if (words.Length > 0 && !words.All(w => label.ToLowerInvariant().Contains(w))) continue;
                var button = new Button { Style = (Style)owner.Window.FindResource("Flat"), Tag = index };
                button.Content = new TextBlock { Width = 370, TextAlignment = TextAlignment.Left, Text = label, Foreground = (System.Windows.Media.Brush)owner.Window.Resources["Text"] };
                button.Click += (s, e) => Guard("pick value", () => OnPickValue((int)((Button)s).Tag));
                pickList.Children.Add(button);
            }
        }

        private void OnPickValue(int index)
        {
            List<string> choices;
            if (!Store.Choices.TryGetValue(pickKey, out choices)) choices = new List<string>();
            HidePanels();
            if (index < 0 || index >= choices.Count) return;
            int done = 0;
            var refused = new List<string>();
            foreach (long viewId in pickTargets)
            {
                string held, message;
                if (Store.Stage(viewId, pickKey, choices[index], out held, out message)) done++;
                else if (!refused.Contains(message)) refused.Add(message);
            }
            host.Sync();
            UpdateState();
            string text = "Staged " + done + " view(s).";
            if (refused.Count > 0) text += " Refused: " + refused[0];
            Say(text + " Press Apply to Revit to write.", refused.Count > 0 && done == 0);
        }

        private void OnSheetMode()
        {
            int index = sheetCombo.SelectedIndex;
            sheetMode = index == 1 ? "on" : index == 2 ? "off" : "any";
            if (loaded) RebuildGrid();
        }

        // ---------------------------------------------------------------- filter by a column's value, and set a value on the selected rows --

        /// <summary>Keep the two column pickers in step with the columns shown.</summary>
        private void RefreshPickers()
        {
            string sig = string.Join("|", fields.Select(f => f.Key));
            if (sig == pickerSig) return;
            pickerSig = sig;
            loading = true;
            try
            {
                filterCol.Items.Clear();
                filterCol.Items.Add("No filter");
                foreach (VmCore.Field f in fields) filterCol.Items.Add(f.Label);
                List<string> keys = fields.Select(f => f.Key).ToList();
                if (fcolKey == null || !keys.Contains(fcolKey))
                {
                    fcolKey = null;
                    fval = null;
                }
                filterCol.SelectedIndex = fcolKey != null ? keys.IndexOf(fcolKey) + 1 : 0;
                setKeys = fields.Where(f => f.Writable).Select(f => f.Key).ToList();
                setCol.Items.Clear();
                foreach (VmCore.Field f in fields) if (f.Writable) setCol.Items.Add(f.Label);
                if (setKeys.Count > 0 && setCol.SelectedIndex < 0) setCol.SelectedIndex = 0;
            }
            finally
            {
                loading = false;
            }
            FillFilterValues();
            ShowSetInput();
        }

        private void FillFilterValues()
        {
            loading = true;
            try
            {
                filterVal.Items.Clear();
                fvalValues = new List<string>();
                if (fcolKey != null)
                {
                    foreach (string value in VmCore.DistinctValues(rows, Store, fcolKey, typeName))
                    {
                        fvalValues.Add(value);
                        filterVal.Items.Add(value.Length > 0 ? value : "(blank)");
                    }
                    int at = fval == null ? -1 : fvalValues.IndexOf(fval);
                    if (at >= 0) filterVal.SelectedIndex = at;
                    else fval = null;
                }
            }
            finally
            {
                loading = false;
            }
        }

        private void OnFilterCol()
        {
            if (loading) return;
            int index = filterCol.SelectedIndex;
            fcolKey = index > 0 && index <= fields.Count ? fields[index - 1].Key : null;
            fval = null;
            FillFilterValues();
            RebuildGrid();
        }

        private void OnFilterVal()
        {
            if (loading) return;
            int index = filterVal.SelectedIndex;
            if (index >= 0 && index < fvalValues.Count)
            {
                fval = fvalValues[index];
                RebuildGrid();
            }
        }

        private string SetKey()
        {
            int index = setCol.SelectedIndex;
            return index >= 0 && index < setKeys.Count ? setKeys[index] : null;
        }

        /// <summary>A column with a fixed list of values gets a dropdown; any other, a box.</summary>
        private void ShowSetInput()
        {
            string key = SetKey();
            List<string> choices = null;
            if (key != null && Store.Choices.ContainsKey(key)) choices = Store.Choices[key];
            bool has = choices != null && choices.Count > 0;
            setChoice.Items.Clear();
            setChoiceValues = new List<string>();
            if (has)
            {
                foreach (string value in choices)
                {
                    setChoiceValues.Add(value);
                    setChoice.Items.Add(value.Length > 0 ? value : "(none)");
                }
                setChoice.SelectedIndex = 0;
            }
            setChoice.Visibility = has ? Visibility.Visible : Visibility.Collapsed;
            setText.Visibility = has ? Visibility.Collapsed : Visibility.Visible;
        }

        private void OnSetSelected()
        {
            string key = SetKey();
            List<long> ids = host.SelectedIds();
            if (key == null || ids.Count == 0)
            {
                Say("Select the rows to change first.", true);
                return;
            }
            string value;
            if (setChoiceValues.Count > 0)
            {
                int index = setChoice.SelectedIndex;
                if (index < 0) return;
                value = setChoiceValues[index];
            }
            else value = setText.Text ?? "";
            int done = 0;
            var refused = new List<string>();
            foreach (long viewId in ids)
            {
                string held, message;
                if (Store.Stage(viewId, key, value, out held, out message)) done++;
                else if (!refused.Contains(message)) refused.Add(message);
            }
            host.Sync();
            UpdateState();
            VmCore.Field f = VmCore.FieldFromKey(key);
            string text = "Set " + (f != null ? f.Label : key) + " on " + done + " of " + ids.Count + " selected view(s).";
            if (refused.Count > 0) text += " Refused: " + refused[0];
            Say(text + " Press Apply to Revit to write.", refused.Count > 0 && done == 0);
        }

        // ---------------------------------------------------------------- columns --

        private void OpenColumns()
        {
            Guard("columns", () =>
            {
                if (!loaded) return;
                Say("Reading the parameters on these views...");
                colNames = VmRevit.ParameterNames(owner.Doc, rows, typeName);
                colNote.Text = "Parameters on " + (typeName != null ? VmCore.ViewTypeLabel(typeName) + " views" : "all views")
                    + ". Editable ones can be changed here and in Excel; read-only ones are shown for reference.";
                colSearch.Text = "";
                BuildColumnList();
                ShowPanel("columns");
                Say("Pick a column to add.");
            });
        }

        private void BuildColumnList()
        {
            colList.Children.Clear();
            string[] words = Words(colSearch.Text);
            var have = new HashSet<string>(fields.Select(f => f.Key));
            var entries = new List<Tuple<string, VmCore.Field, bool, string>>();
            foreach (VmCore.Field field in VmCore.ExtraFields) entries.Add(Tuple.Create(field.Label, field, false, "built in"));
            foreach (VmRevit.ParamName p in colNames)
                entries.Add(Tuple.Create(p.Name, VmCore.ParamField(p.Name), p.Editable, p.Editable ? "" : "read-only"));
            int count = 0;
            foreach (var entry in entries)
            {
                if (have.Contains(entry.Item2.Key)) continue;
                if (words.Length > 0 && !words.All(w => entry.Item1.ToLowerInvariant().Contains(w))) continue;
                var button = new Button
                {
                    Style = (Style)owner.Window.FindResource("Flat"),
                    HorizontalContentAlignment = HorizontalAlignment.Left,
                    Tag = entry.Item2.Key,
                };
                bool muted = !entry.Item3 && entry.Item4.Length > 0;
                button.Content = new TextBlock
                {
                    Width = 370,
                    TextAlignment = TextAlignment.Left,
                    Text = entry.Item1 + (entry.Item4.Length > 0 ? "    (" + entry.Item4 + ")" : ""),
                    Foreground = (System.Windows.Media.Brush)owner.Window.Resources[muted ? "Muted" : "Text"],
                };
                button.Click += (s, e) => Guard("pick column", () => OnPickColumn((string)((Button)s).Tag));
                colList.Children.Add(button);
                count++;
                if (count >= 400) break;
            }
        }

        private void OnPickColumn(string key)
        {
            VmCore.Field field = VmCore.FieldFromKey(key);
            if (field == null) return;
            HidePanels();
            if (fields.Any(f => f.Key == field.Key)) return;
            fields.Add(field);
            SaveFields();
            if (field.Kind == "param") Reload();
            else RebuildGrid();
            Say("Added the '" + field.Label + "' column.");
        }

        private void RemoveColumn(string key)
        {
            Guard("remove column", () =>
            {
                if (IsDefault(key)) return;
                fields = fields.Where(f => f.Key != key).ToList();
                foreach (VmCore.CellKey k in Store.Edits.Keys.Where(k => k.Key == key).ToList()) Store.Edits.Remove(k);
                if (sortKey == key)
                {
                    sortKey = "name";
                    sortDesc = false;
                }
                SaveFields();
                RebuildGrid();
            });
        }

        // ---------------------------------------------------------------- panels --

        private void ShowPanel(string which)
        {
            reportPanel.Visibility = which == "report" ? Visibility.Visible : Visibility.Collapsed;
            colPanel.Visibility = which == "columns" ? Visibility.Visible : Visibility.Collapsed;
            pickPanel.Visibility = which == "pick" ? Visibility.Visible : Visibility.Collapsed;
            overlay.Visibility = Visibility.Visible;
        }

        private void HidePanels()
        {
            overlay.Visibility = Visibility.Collapsed;
            reportPanel.Visibility = Visibility.Collapsed;
            colPanel.Visibility = Visibility.Collapsed;
            pickPanel.Visibility = Visibility.Collapsed;
        }

        private void OnClosePanels()
        {
            plan = null;
            HidePanels();
        }

        // ---------------------------------------------------------------- Excel --

        private void OnPush()
        {
            if (!loaded) return;
            var dialog = new SaveFileDialog
            {
                Filter = "Excel workbook (*.xlsx)|*.xlsx",
                DefaultExt = ".xlsx",
                OverwritePrompt = true,
                FileName = "View references - " + Regex.Replace(owner.Doc.Title ?? "project", "[\\\\/:*?\"<>|]+", "-") + ".xlsx",
            };
            if (dialog.ShowDialog(owner.Window) != true) return;
            string path = dialog.FileName;
            var headers = new List<string> { VmXlsx.IdHeader + " (do not edit)" };
            headers.AddRange(fields.Select(f => f.Label));
            var writable = new List<bool> { false };
            writable.AddRange(fields.Select(f => f.Writable));
            var body = new List<string[]>();
            foreach (VmCore.RefRow row in shown)
            {
                var line = new List<string> { row.ViewId.ToString() };
                line.AddRange(fields.Select(f => Store.Effective(row.ViewId, f.Key)));
                body.Add(line.ToArray());
            }
            try
            {
                VmXlsx.WriteFile(path, VmXlsx.Build(headers, writable, body));
            }
            catch (Exception ex)
            {
                Say("Could not write the workbook: " + VmCore.Describe(ex), true);
                return;
            }
            Say("Wrote " + body.Count + " view(s) to " + path);
            try { Process.Start(new ProcessStartInfo(path) { UseShellExecute = true }); } catch (Exception) { }
        }

        private void OnPull()
        {
            if (!loaded) return;
            var dialog = new OpenFileDialog { Filter = "Excel workbook (*.xlsx)|*.xlsx" };
            if (dialog.ShowDialog(owner.Window) != true) return;
            VmXlsx.ImportPlan made;
            try
            {
                Dictionary<string, string> parts = VmXlsx.ReadParts(dialog.FileName);
                string sheetName;
                Dictionary<int, Dictionary<int, string>> grid = VmXlsx.Parse(parts, out sheetName);
                made = VmXlsx.PlanImport(Store, fields, grid);
            }
            catch (InvalidOperationException ex)
            {
                Say(ex.Message, true);
                return;
            }
            catch (Exception ex)
            {
                Say("Could not read the workbook: " + VmCore.Describe(ex), true);
                return;
            }
            plan = made;
            reportTitle.Text = "Pull from Excel - " + Path.GetFileName(dialog.FileName);
            reportText.Text = VmXlsx.ImportReport(plan, Store);
            ShowPanel("report");
        }

        private void OnStagePlan()
        {
            VmXlsx.ImportPlan p = plan;
            plan = null;
            HidePanels();
            if (p == null) return;
            int staged = 0;
            foreach (VmXlsx.Change c in p.Changes)
            {
                string held, message;
                if (Store.Stage(c.ViewId, c.Key, c.New, out held, out message)) staged++;
            }
            host.Sync();
            UpdateState();
            Say("Staged " + staged + " change(s) from Excel. Press Apply to Revit to write them.");
        }

        // ---------------------------------------------------------------- the builders --

        private void OpenBuilder(string target)
        {
            if (builder != null)
            {
                try
                {
                    builder.Activate();
                    return;
                }
                catch (Exception) { builder = null; }
            }
            var ids = new HashSet<long>(host.SelectedIds());
            List<VmCore.RefRow> chosen = shown.Where(r => ids.Contains(r.ViewId)).ToList();
            if (chosen.Count == 0) return;
            builder = new VmBuilderWindow(this, owner, chosen, target);
            builder.Show();
        }

        public void BuilderClosed() { builder = null; }

        public void AcceptBuilder(List<VmCore.EditItem> changes)
        {
            int staged = 0;
            foreach (VmCore.EditItem c in changes)
            {
                string held, message;
                if (Store.Stage(c.ViewId, c.Key, c.Text, out held, out message)) staged++;
            }
            host.Sync();
            UpdateState();
            Say(staged + " edit(s) staged from the builder. Press Apply to Revit to write them.");
        }

        // ---------------------------------------------------------------- writing --

        public void Apply()
        {
            if (owner.Busy) return;
            Dictionary<VmCore.CellKey, string> clashes = Store.Conflicts();
            if (clashes.Count > 0)
            {
                host.Sync(false);
                Say(clashes.Count + " edit(s) would clash (red) - fix them first.", true);
                return;
            }
            List<VmCore.EditItem> items = Store.Items();
            if (items.Count == 0)
            {
                Say("Nothing is staged.");
                return;
            }
            owner.LogEnvironment("View references - " + items.Count + " edit(s)");
            host.Failed = new Dictionary<VmCore.CellKey, string>();
            owner.Queue(app => DoApply(items));
        }

        private void DoApply(List<VmCore.EditItem> items)
        {
            List<VmCore.CellKey> applied;
            Dictionary<VmCore.CellKey, string> failed;
            VmRevit.ApplyRefEdits(owner.Doc, items, owner.Log, out applied, out failed);
            owner.BackOnUi(() => AfterApply(items.Count, applied, failed));
        }

        private void AfterApply(int count, List<VmCore.CellKey> applied, Dictionary<VmCore.CellKey, string> failed)
        {
            host.Failed = new Dictionary<VmCore.CellKey, string>(failed);
            try
            {
                LoadRows(VmRevit.ReadViewRefs(owner.Doc, ParamNames(), owner.Log));
                RebuildTypes();
                RebuildGrid();
            }
            catch (Exception ex)
            {
                owner.Log.Add("re-read failed: " + VmCore.Describe(ex));
            }
            owner.InvalidateGridTabs(this);
            string message;
            if (failed.Count > 0)
            {
                VmCore.CellKey first = failed.Keys.OrderBy(k => k.View).ThenBy(k => k.Key, StringComparer.Ordinal).First();
                message = "Wrote " + applied.Count + " of " + count + " edit(s). " + failed.Count + " refused (red) - " + failed[first];
            }
            else message = "Wrote " + applied.Count + " edit(s) to the model.";
            owner.Finish(message, failed.Count > 0, failed.Count > 0);
        }

        public void Invalidate() { loaded = false; }

        public void Revert()
        {
            Store.Revert();
            host.Failed = new Dictionary<VmCore.CellKey, string>();
            host.Sync();
            UpdateState();
            Say("Staged edits cleared.");
        }

        public VmCore.EditStore StoreOf { get { return Store; } }
    }
}
