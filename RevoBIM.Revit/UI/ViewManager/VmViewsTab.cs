using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;
using RevoBIM.Tools.ViewManager;

namespace RevoBIM.UI.ViewManager
{
    /// <summary>
    /// The View Manager tab: every view in one grid - name, view type, detail number, view template (a dropdown), title on sheet and
    /// any parameter you add - with a tick column, a keyword box on every column, multi-level sort and grouping. Edits are staged and
    /// written together; a ruleset builder rewrites titles and detail numbers, and the list goes to Excel and back.
    /// </summary>
    internal sealed class VmViewsTab : VmGridTab
    {
        private static readonly VmCore.Field FName = new VmCore.Field("name", "View Name", "name", true, 280);
        private static readonly VmCore.Field FType = new VmCore.Field("vtype", "View Type", "vtype", false, 150);
        private static readonly VmCore.Field FDetail = new VmCore.Field("detail", "Detail Number", "detail", true, 130);
        private static readonly VmCore.Field FTemplate = new VmCore.Field("template", "View Template", "template", true, 240) { NoneLabel = "<None>" };
        private static readonly VmCore.Field FTitle = new VmCore.Field("title", "Title on Sheet", "title", true, 280);
        private static readonly VmCore.Field FViewport = new VmCore.Field("vptype", "Viewport Type", "vptype", true, 200) { Dropdown = true };
        private static readonly VmCore.Field FLevel = new VmCore.Field("level", "Associated Level", "level", false, 170);
        private static readonly VmCore.Field FSheetNo = new VmCore.Field("sheetno", "Sheet Number", "sheetno", false, 130);
        private static readonly VmCore.Field FSheetName = new VmCore.Field("sheetname", "Sheet Name", "sheetname", false, 200);
        private static readonly VmCore.Field FId = new VmCore.Field("vid", "Element ID", "vid", false, 100);

        private static readonly VmCore.Field[] Defaults = { FName, FType, FDetail, FTemplate, FTitle };
        private static readonly VmCore.Field[] Offered = { FLevel, FSheetNo, FSheetName, FViewport, FId };

        private readonly Button btnRename;
        private readonly FrameworkElement setPanel;
        private readonly ComboBox setCol, setChoice;
        private readonly TextBox setText;
        private readonly TextBlock setNote;
        private List<string> setKeys = new List<string>();
        private List<string> setChoiceValues = new List<string>();

        public VmViewsTab(VmWindow owner) : base(owner, "Vw", "vw_columns")
        {
            btnRename = Find<Button>("Rename");
            setPanel = Find<FrameworkElement>("SetPanel");
            setCol = Find<ComboBox>("SetCol");
            setChoice = Find<ComboBox>("SetChoice");
            setText = Find<TextBox>("SetText");
            setNote = Find<TextBlock>("SetNote");

            Find<Button>("Batch").Click += (s, e) => Guard("batch", () => DropMenu(Find<Button>("Batch"),
                Item("Set a value on the ticked views...", OpenSet),
                Item("Untick every view", () => { Host.SetAllChecked(false); Host.Fill(); }),
                Item("Clear the staged edits", Revert)));
            Find<Button>("Excel").Click += (s, e) => Guard("excel", () => DropMenu(Find<Button>("Excel"),
                Item("Push to Excel...", Push),
                Item("Pull from Excel...", Pull)));
            btnRename.Click += (s, e) => Guard("rename", () => DropMenu(btnRename,
                Item("Title on Sheet builder...", () => OpenBuilder("title")),
                Item("Detail Number builder...", () => OpenBuilder("detail"))));
            Find<Button>("SetClose").Click += (s, e) => Guard("close", HidePanels);
            Find<Button>("SetGo").Click += (s, e) => Guard("set", StageSet);
            setCol.SelectionChanged += (s, e) => Guard("set col", ShowSetInput);
        }

        protected override IList<VmCore.Field> DefaultFields { get { return Defaults; } }
        protected override IList<VmCore.Field> OfferedFields { get { return Offered; } }
        protected override IEnumerable<FrameworkElement> AllPanels { get { return new[] { ColPanel, setPanel }; } }

        protected override List<VmCore.RefRow> ReadRows(List<string> paramNames)
        {
            List<VmCore.RefRow> rows = VmRevit.ReadViewRefs(Owner.Doc, paramNames, Owner.Log);
            try
            {
                Edits.Choices = VmRevit.CollectChoices(Owner.Doc);
            }
            catch (Exception ex)
            {
                Edits.Choices = new Dictionary<string, List<string>>();
                Owner.Log.Add("choices failed: " + VmCore.Describe(ex));
            }
            return rows;
        }

        protected override void ApplyItems(List<VmCore.EditItem> items, out List<VmCore.CellKey> applied, out Dictionary<VmCore.CellKey, string> failed)
        {
            VmRevit.ApplyRefEdits(Owner.Doc, items, Owner.Log, out applied, out failed);
        }

        protected override string SummaryText(int shown, int total, int ticked, int edits)
        {
            int rowsEdited = Edits.Edits.Keys.Select(k => k.View).Distinct().Count();
            string head = shown == total ? "Selected: " + ticked + " of " + total : "Showing " + shown + " of " + total + " | Selected: " + ticked;
            return head + " | Unmodified: " + (total - rowsEdited) + " | Modified: " + rowsEdited;
        }

        protected override void AfterState(bool busy)
        {
            btnRename.IsEnabled = Host.CheckedIds().Count > 0 && !busy;
        }

        // ---------------------------------------------------------------- set a value on the ticked views --

        private void OpenSet()
        {
            if (!Loaded) return;
            List<long> ticked = Host.CheckedIds();
            if (ticked.Count == 0)
            {
                Say("Tick the views to change first.", true);
                return;
            }
            setNote.Text = "Stages one value on the " + ticked.Count + " ticked view(s). Nothing is written until Apply to Revit.";
            setKeys = Fields.Where(f => f.Writable).Select(f => f.Key).ToList();
            setCol.Items.Clear();
            foreach (VmCore.Field f in Fields) if (f.Writable) setCol.Items.Add(f.Label);
            if (setKeys.Count > 0) setCol.SelectedIndex = 0;
            ShowSetInput();
            ShowPanel(setPanel);
        }

        private string SetKey()
        {
            int i = setCol.SelectedIndex;
            return i >= 0 && i < setKeys.Count ? setKeys[i] : null;
        }

        private void ShowSetInput()
        {
            string key = SetKey();
            List<string> choices = null;
            if (key != null) Edits.Choices.TryGetValue(key, out choices);
            bool has = choices != null && choices.Count > 0;
            VmCore.Field field = Fields.FirstOrDefault(f => f.Key == key);
            setChoice.Items.Clear();
            setChoiceValues = new List<string>();
            if (has)
            {
                foreach (string v in choices)
                {
                    setChoiceValues.Add(v);
                    setChoice.Items.Add(v.Length == 0 ? (field != null && field.NoneLabel != null ? field.NoneLabel : "(none)") : v);
                }
                setChoice.SelectedIndex = 0;
            }
            setChoice.Visibility = has ? Visibility.Visible : Visibility.Collapsed;
            setText.Visibility = has ? Visibility.Collapsed : Visibility.Visible;
        }

        private void StageSet()
        {
            string key = SetKey();
            List<long> ids = Host.CheckedIds();
            if (key == null || ids.Count == 0) return;
            string value;
            if (setChoiceValues.Count > 0)
            {
                int i = setChoice.SelectedIndex;
                if (i < 0) return;
                value = setChoiceValues[i];
            }
            else value = setText.Text ?? "";
            int done = 0;
            var refused = new List<string>();
            foreach (long id in ids)
            {
                string held, message;
                if (Edits.Stage(id, key, value, out held, out message)) done++;
                else if (!refused.Contains(message)) refused.Add(message);
            }
            HidePanels();
            Host.Fill();
            string text = "Staged " + done + " of " + ids.Count + " ticked view(s).";
            if (refused.Count > 0) text += " Refused: " + refused[0];
            Say(text + " Press Apply to Revit to write.", refused.Count > 0 && done == 0);
        }

        // ---------------------------------------------------------------- Excel --

        private void Push()
        {
            if (!Loaded) return;
            var dialog = new SaveFileDialog
            {
                Filter = "Excel workbook (*.xlsx)|*.xlsx",
                DefaultExt = ".xlsx",
                OverwritePrompt = true,
                FileName = "Views - " + Regex.Replace(Owner.Doc.Title ?? "project", "[\\\\/:*?\"<>|]+", "-") + ".xlsx",
            };
            if (dialog.ShowDialog(Win) != true) return;
            var headers = new List<string> { VmXlsx.IdHeader + " (do not edit)" };
            headers.AddRange(Fields.Select(f => f.Label));
            var writable = new List<bool> { false };
            writable.AddRange(Fields.Select(f => f.Writable));
            var body = new List<string[]>();
            foreach (VmCore.RefRow row in Host.Shown)
            {
                var line = new List<string> { row.ViewId.ToString() };
                line.AddRange(Fields.Select(f => Edits.Effective(row.ViewId, f.Key)));
                body.Add(line.ToArray());
            }
            try
            {
                VmXlsx.WriteFile(dialog.FileName, VmXlsx.Build(headers, writable, body));
            }
            catch (Exception ex)
            {
                Say("Could not write the workbook: " + VmCore.Describe(ex), true);
                return;
            }
            Say("Wrote " + body.Count + " view(s) to " + dialog.FileName, false);
            try { Process.Start(new ProcessStartInfo(dialog.FileName) { UseShellExecute = true }); } catch (Exception) { }
        }

        private void Pull()
        {
            if (!Loaded) return;
            var dialog = new OpenFileDialog { Filter = "Excel workbook (*.xlsx)|*.xlsx" };
            if (dialog.ShowDialog(Win) != true) return;
            VmXlsx.ImportPlan plan;
            try
            {
                string sheet;
                Dictionary<int, Dictionary<int, string>> grid = VmXlsx.Parse(VmXlsx.ReadParts(dialog.FileName), out sheet);
                plan = VmXlsx.PlanImport(Edits, Fields, grid);
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
            string report = VmXlsx.ImportReport(plan, Edits);
            if (plan.Changes.Count == 0)
            {
                MessageBox.Show(Win, report, "Pull from Excel - " + Path.GetFileName(dialog.FileName), MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }
            if (MessageBox.Show(Win, report + "\n\nStage these changes?", "Pull from Excel - " + Path.GetFileName(dialog.FileName), MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
            int staged = 0;
            foreach (VmXlsx.Change c in plan.Changes)
            {
                string held, message;
                if (Edits.Stage(c.ViewId, c.Key, c.New, out held, out message)) staged++;
            }
            Host.Fill();
            Say("Staged " + staged + " change(s) from Excel. Press Apply to Revit to write them.", false);
        }
    }
}
