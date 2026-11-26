using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using RevoBIM.Tools.ViewManager;

namespace RevoBIM.UI.ViewManager
{
    /// <summary>
    /// The View Range tab: the top, cut plane, bottom and view depth of every plan view as a level and an offset, edited in the cells
    /// or on every ticked view at once, with the same column search, sort, grouping and parameter columns as the View Manager tab.
    /// Edits are staged and written together, a view at a time; one Revit refuses is named and the others still land.
    /// </summary>
    internal sealed class VmRangeTab : VmGridTab
    {
        private readonly Button btnBatch;
        private readonly CheckBox hide;
        private readonly FrameworkElement batchPanel;
        private readonly ComboBox[] levelBoxes = new ComboBox[4];
        private readonly TextBox[] offsetBoxes = new TextBox[4];
        private readonly TextBlock batchNote, info;
        private List<string> levelChoices = new List<string>();

        public VmRangeTab(VmWindow owner) : base(owner, "Rg", "rg_columns")
        {
            btnBatch = Find<Button>("Batch");
            hide = Find<CheckBox>("Hide");
            batchPanel = Find<FrameworkElement>("BatchPanel");
            batchNote = Find<TextBlock>("BatchNote");
            info = Find<TextBlock>("Info");
            for (int i = 0; i < 4; i++)
            {
                levelBoxes[i] = Win.FindName("RgBL" + i) as ComboBox;
                offsetBoxes[i] = Win.FindName("RgBO" + i) as TextBox;
            }
            Edits.Validate = VmRange.ValidateCell;
            string unit = VmRange.UnitLabel(owner.Doc);
            info.ToolTip = "Offsets are in the project's length unit" + (unit.Length > 0 ? " (" + unit + ")" : "")
                + ". Levels can be a project level, Unlimited, Level Above or Level Below. The cut plane level is shown for reference. "
                + "A view whose view template controls the view range is locked - change the template instead.";
            Find<TextBlock>("BatchOffHead").Text = unit.Length > 0 ? "Offset (" + unit + ")" : "Offset";

            btnBatch.Click += (s, e) => Guard("batch", OpenBatch);
            Find<Button>("BatchClose").Click += (s, e) => Guard("close", HidePanels);
            Find<Button>("BatchGo").Click += (s, e) => Guard("stage", StageBatch);
            hide.Checked += (s, e) => Guard("hide", () => { Host.HideUnchecked = true; if (Loaded) Host.Fill(); });
            hide.Unchecked += (s, e) => Guard("hide", () => { Host.HideUnchecked = false; if (Loaded) Host.Fill(); });
        }

        protected override IList<VmCore.Field> DefaultFields { get { return VmRange.DefaultFields; } }
        protected override IEnumerable<FrameworkElement> AllPanels { get { return new[] { ColPanel, batchPanel }; } }

        protected override List<VmCore.RefRow> ReadRows(List<string> paramNames)
        {
            Dictionary<string, List<string>> choices;
            List<VmCore.RefRow> rows = VmRange.ReadRows(Owner.Doc, paramNames, Owner.Log, out choices);
            Edits.Choices = choices;
            levelChoices = choices.ContainsKey(VmRange.KeyTop) ? choices[VmRange.KeyTop] : new List<string>();
            return rows;
        }

        private static readonly HashSet<string> RangeKeys = new HashSet<string>
        {
            VmRange.KeyTop, VmRange.KeyTopOff, VmRange.KeyCut, VmRange.KeyCutOff, VmRange.KeyBot, VmRange.KeyBotOff, VmRange.KeyDep, VmRange.KeyDepOff,
        };

        protected override void ApplyItems(List<VmCore.EditItem> items, out List<VmCore.CellKey> applied, out Dictionary<VmCore.CellKey, string> failed)
        {
            List<VmCore.EditItem> range = items.Where(i => RangeKeys.Contains(i.Key)).ToList();
            List<VmCore.EditItem> rest = items.Where(i => !RangeKeys.Contains(i.Key)).ToList();
            applied = new List<VmCore.CellKey>();
            failed = new Dictionary<VmCore.CellKey, string>();
            if (range.Count > 0)
            {
                List<VmCore.CellKey> a;
                Dictionary<VmCore.CellKey, string> f;
                VmRange.ApplyRangeEdits(Owner.Doc, range, Owner.Log, out a, out f);
                applied.AddRange(a);
                foreach (KeyValuePair<VmCore.CellKey, string> kv in f) failed[kv.Key] = kv.Value;
            }
            if (rest.Count > 0)
            {
                List<VmCore.CellKey> a;
                Dictionary<VmCore.CellKey, string> f;
                VmRevit.ApplyRefEdits(Owner.Doc, rest, Owner.Log, out a, out f);
                applied.AddRange(a);
                foreach (KeyValuePair<VmCore.CellKey, string> kv in f) failed[kv.Key] = kv.Value;
            }
        }

        protected override string SummaryText(int shown, int total, int ticked, int edits)
        {
            string head = shown == total ? "Total Views: " + total : "Showing " + shown + " of " + total + " views";
            return head + " | Selected Views: " + ticked + " | Edits staged: " + edits;
        }

        protected override void AfterState(bool busy)
        {
            btnBatch.IsEnabled = Host.CheckedIds().Count > 0 && !busy;
        }

        // ---------------------------------------------------------------- batch view range change --

        private void OpenBatch()
        {
            if (!Loaded) return;
            List<long> ticked = Host.CheckedIds();
            if (ticked.Count == 0)
            {
                Say("Tick the views to change first.", true);
                return;
            }
            batchNote.Text = "Sets the same values on the " + ticked.Count + " ticked view(s). Leave a level at (no change), or an offset empty, to keep what each view has. Nothing is written until Apply to Revit.";
            foreach (int i in new[] { 0, 2, 3 })
            {
                levelBoxes[i].Items.Clear();
                levelBoxes[i].Items.Add("(no change)");
                foreach (string l in levelChoices) levelBoxes[i].Items.Add(l);
                levelBoxes[i].SelectedIndex = 0;
            }
            foreach (TextBox b in offsetBoxes) b.Text = "";
            ShowPanel(batchPanel);
        }

        private void StageBatch()
        {
            List<long> ids = Host.CheckedIds();
            if (ids.Count == 0) return;
            string[] levelKeys = { VmRange.KeyTop, null, VmRange.KeyBot, VmRange.KeyDep };
            string[] offsetKeys = { VmRange.KeyTopOff, VmRange.KeyCutOff, VmRange.KeyBotOff, VmRange.KeyDepOff };
            int done = 0;
            var refused = new List<string>();
            foreach (long id in ids)
            {
                for (int i = 0; i < 4; i++)
                {
                    if (levelKeys[i] != null && levelBoxes[i].SelectedIndex > 0)
                        Stage(id, levelKeys[i], (string)levelBoxes[i].SelectedItem, ref done, refused);
                    string off = (offsetBoxes[i].Text ?? "").Trim();
                    if (off.Length > 0) Stage(id, offsetKeys[i], off, ref done, refused);
                }
            }
            HidePanels();
            Host.Fill();
            string text = "Staged " + done + " value(s) on " + ids.Count + " ticked view(s).";
            if (refused.Count > 0) text += " Some were refused - " + refused[0];
            Say(text + " Press Apply to Revit to write.", done == 0 && refused.Count > 0);
        }

        private void Stage(long id, string key, string text, ref int done, List<string> refused)
        {
            string held, message;
            if (Edits.Stage(id, key, text, out held, out message)) done++;
            else if (!refused.Contains(message)) refused.Add(message);
        }
    }
}
