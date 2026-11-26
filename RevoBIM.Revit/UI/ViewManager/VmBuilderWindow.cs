using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using RevoBIM.Tools.ViewManager;

namespace RevoBIM.UI.ViewManager
{
    /// <summary>What a builder window needs from the tab that opened it: the staged values to start from, and a place to hand the result back.</summary>
    internal interface IVmBuilderHost
    {
        VmCore.EditStore Store { get; }
        void BuilderClosed();
        void AcceptBuilder(List<VmCore.EditItem> changes);
    }

    /// <summary>
    /// Title on Sheet Builder and Detail Number Builder (port of BuilderWindow): pick or build a ruleset, watch the preview,
    /// apply it, tidy by hand, and stage the result. A private store, so nothing here touches the list until OK.
    /// </summary>
    internal sealed class VmBuilderWindow
    {
        private readonly IVmBuilderHost tab;
        private readonly VmWindow owner;
        private readonly string target, noun;
        private readonly Window window;
        private readonly ComboBox setsCombo, sourceCombo, caseCombo;
        private readonly TextBox setName;
        private readonly CheckBox tidyBox;
        private readonly StackPanel rulesPanel;
        private readonly TextBlock problems, status;
        private readonly VmCore.EditStore store;
        private readonly List<VmCore.RefRow> mine = new List<VmCore.RefRow>();
        private readonly Dictionary<long, string> sourceName = new Dictionary<long, string>();
        private readonly Dictionary<long, string> sourceTitle = new Dictionary<long, string>();
        private readonly Dictionary<long, string> previews = new Dictionary<long, string>();
        private readonly VmGridHost host;
        private List<VmCore.Ruleset> allSets;
        private List<VmCore.Ruleset> rulesets;
        private VmCore.Ruleset current;
        private bool loading;
        public readonly VmChrome Chrome;

        public VmBuilderWindow(IVmBuilderHost tab, VmWindow owner, List<VmCore.RefRow> rows, string target)
        {
            this.tab = tab;
            this.owner = owner;
            this.target = target == "detail" ? "detail" : "title";
            noun = this.target == "detail" ? "detail number" : "title";
            window = VmUi.LoadLayout("Builder.xaml");
            string label = this.target == "detail" ? "Detail Number Builder" : "Title on Sheet Builder";
            try
            {
                window.Title = "RevoBIM - " + label;
                ((TextBlock)window.FindName("BldTitle")).Text = "  " + label;
            }
            catch (Exception) { }
            setsCombo = (ComboBox)window.FindName("BldSets");
            setName = (TextBox)window.FindName("BldSetName");
            sourceCombo = (ComboBox)window.FindName("BldSource");
            caseCombo = (ComboBox)window.FindName("BldCase");
            tidyBox = (CheckBox)window.FindName("BldTidy");
            rulesPanel = (StackPanel)window.FindName("BldRules");
            problems = (TextBlock)window.FindName("BldProblems");
            status = (TextBlock)window.FindName("BldStatus");

            // a private store: the same rows, valued as the list shows them now
            foreach (VmCore.RefRow row in rows)
            {
                var copy = new VmCore.RefRow(row.ViewId, row.TypeName)
                {
                    Values = new Dictionary<string, string>(row.Values),
                    Locked = new Dictionary<string, string>(row.Locked),
                    SheetId = row.SheetId,
                    ViewportId = row.ViewportId,
                };
                foreach (string key in new[] { "name", "title", "detail" }) copy.Values[key] = tab.Store.Effective(row.ViewId, key);
                mine.Add(copy);
                sourceName[row.ViewId] = copy.Values["name"];
                sourceTitle[row.ViewId] = copy.Values["title"];
            }
            store = new VmCore.EditStore(mine);

            var fields = new List<VmCore.Field>
            {
                new VmCore.Field("name", "View name", "name", false, 280), VmCore.FieldPreview, VmCore.FieldTitle,
                VmCore.FieldSheetNo, VmCore.FieldDetail, VmCore.FieldLevel,
            };
            host = new VmGridHost(window, (DataGrid)window.FindName("BldGrid"), store, Say);
            host.Fields = fields;
            host.Virtual = viewId => { string v; return previews.TryGetValue(viewId, out v) ? v : ""; };
            host.OnChanged = () => owner.Guard("builder edited", () => Say(store.Edits.Count + " edit(s) in this window. OK stages them in the list."));

            allSets = VmRulesets.Load();
            rulesets = allSets.Where(r => r.Target == this.target).ToList();
            current = rulesets[0].Copy();
            loading = true;
            foreach (string[] s in VmCore.SourceModes) sourceCombo.Items.Add(s[1]);
            foreach (string[] c in VmCore.CaseModes) caseCombo.Items.Add(c[1]);
            loading = false;

            try { window.Owner = owner.Window; } catch (Exception) { }
            ((FrameworkElement)window.FindName("BldHeader")).MouseLeftButtonDown += (s, e) => VmUi.DragMove(window);
            Chrome = new VmChrome(window, (Border)window.FindName("BldHeader"), (Button)window.FindName("BldShrink"));
            new VmThemed(window, BuildRules);
            ((Button)window.FindName("BldClose")).Click += (s, e) => window.Close();
            ((Button)window.FindName("BldCancel")).Click += (s, e) => window.Close();
            ((Button)window.FindName("BldOk")).Click += (s, e) => Guard("ok", OnOk);
            ((Button)window.FindName("BldApply")).Click += (s, e) => Guard("apply", OnApply);
            ((Button)window.FindName("BldReset")).Click += (s, e) => Guard("reset", () =>
            {
                store.Revert();
                host.Sync();
                Say("Edits cleared - the titles are back as the list has them.");
            });
            ((Button)window.FindName("BldAddRule")).Click += (s, e) => Guard("add rule", () =>
            {
                current.Rules.Add(VmCore.NewRule());
                BuildRules();
            });
            ((Button)window.FindName("BldSave")).Click += (s, e) => Guard("save", OnSave);
            ((Button)window.FindName("BldNew")).Click += (s, e) => Guard("new", () =>
            {
                current = new VmCore.Ruleset("New ruleset") { Target = this.target };
                current.Rules.Add(VmCore.NewRule());
                LoadCurrent();
                Say("A blank ruleset. Add rules, name it, then Save ruleset.");
            });
            ((Button)window.FindName("BldDelete")).Click += (s, e) => Guard("delete", OnDelete);
            setsCombo.SelectionChanged += (s, e) => Guard("pick set", OnSetPicked);
            sourceCombo.SelectionChanged += (s, e) => Guard("options", OnOptions);
            caseCombo.SelectionChanged += (s, e) => Guard("options", OnOptions);
            tidyBox.Checked += (s, e) => Guard("options", OnOptions);
            tidyBox.Unchecked += (s, e) => Guard("options", OnOptions);
            window.Closed += (s, e) =>
            {
                try { tab.BuilderClosed(); } catch (Exception) { }
            };

            FillSets(null);
            LoadCurrent();
            host.Build(mine);
            Say(mine.Count + " view(s). Build or pick a ruleset, check the preview, then Apply ruleset.");
        }

        private void Guard(string name, Action a) { owner.Guard(name, a); }

        // ---------------------------------------------------------------- small things --

        private void Say(string message, bool error = false)
        {
            try
            {
                status.Text = message;
                status.Foreground = (System.Windows.Media.Brush)window.Resources[error ? "Orange" : "Muted"];
            }
            catch (Exception) { }
        }

        public void Show() { window.Show(); }

        public void Activate()
        {
            try { if (Chrome.Mode == VmChrome.State.Shrunk) Chrome.Expand(); } catch (Exception) { }
            window.Activate();
        }

        // ---------------------------------------------------------------- rulesets --

        private void FillSets(string select)
        {
            loading = true;
            try
            {
                setsCombo.Items.Clear();
                int chosen = 0;
                for (int i = 0; i < rulesets.Count; i++)
                {
                    setsCombo.Items.Add(rulesets[i].Name);
                    if (select != null && string.Equals(rulesets[i].Name, select, StringComparison.OrdinalIgnoreCase)) chosen = i;
                }
                setsCombo.SelectedIndex = rulesets.Count > 0 ? chosen : -1;
            }
            finally
            {
                loading = false;
            }
        }

        private void LoadCurrent()
        {
            loading = true;
            try
            {
                setName.Text = current.Name;
                int source = Array.FindIndex(VmCore.SourceModes, s => s[0] == current.Source);
                int caseIndex = Array.FindIndex(VmCore.CaseModes, c => c[0] == current.Case);
                sourceCombo.SelectedIndex = source >= 0 ? source : 0;
                caseCombo.SelectedIndex = caseIndex >= 0 ? caseIndex : 0;
                tidyBox.IsChecked = current.Tidy;
            }
            finally
            {
                loading = false;
            }
            BuildRules();
            UpdatePreviews();
        }

        private void OnSetPicked()
        {
            if (loading) return;
            int index = setsCombo.SelectedIndex;
            if (index >= 0 && index < rulesets.Count)
            {
                current = rulesets[index].Copy();
                LoadCurrent();
                Say("Loaded '" + current.Name + "'.");
            }
        }

        private void OnOptions()
        {
            if (loading) return;
            current.Source = VmCore.SourceModes[Math.Max(0, sourceCombo.SelectedIndex)][0];
            current.Case = VmCore.CaseModes[Math.Max(0, caseCombo.SelectedIndex)][0];
            current.Tidy = tidyBox.IsChecked == true;
            UpdatePreviews();
        }

        private void OnSave()
        {
            string name = (setName.Text ?? "").Trim();
            if (name.Length == 0)
            {
                Say("Give the ruleset a name first.", true);
                return;
            }
            current.Name = name;
            current.Target = target;
            VmCore.Ruleset keep = current.Copy();
            bool replaced = false;
            for (int i = 0; i < allSets.Count; i++)
            {
                if (allSets[i].Target == target && string.Equals(allSets[i].Name, name, StringComparison.OrdinalIgnoreCase))
                {
                    allSets[i] = keep;
                    replaced = true;
                }
            }
            if (!replaced) allSets.Add(keep);
            rulesets = allSets.Where(r => r.Target == target).ToList();
            string why;
            bool ok = VmRulesets.Save(allSets, out why);
            FillSets(name);
            if (ok) Say("Saved '" + name + "' to " + VmCore.RulesetsPath());
            else Say("Could not save: " + why, true);
        }

        private void OnDelete()
        {
            int index = setsCombo.SelectedIndex;
            if (index < 0 || index >= rulesets.Count) return;
            VmCore.Ruleset gone = rulesets[index];
            string name = gone.Name;
            allSets = allSets.Where(r => !ReferenceEquals(r, gone)).ToList();
            if (!allSets.Any(r => r.Target == target))
            {
                var fresh = new VmCore.Ruleset("New ruleset") { Target = target };
                fresh.Rules.Add(VmCore.NewRule());
                allSets.Add(fresh);
            }
            rulesets = allSets.Where(r => r.Target == target).ToList();
            string why;
            VmRulesets.Save(allSets, out why);
            current = rulesets[0].Copy();
            FillSets(null);
            LoadCurrent();
            Say("Deleted '" + name + "'.");
        }

        // ---------------------------------------------------------------- rule rows --

        private void BuildRules()
        {
            rulesPanel.Children.Clear();
            for (int i = 0; i < current.Rules.Count; i++) rulesPanel.Children.Add(RuleRow(i, current.Rules[i]));
            if (current.Rules.Count == 0)
            {
                rulesPanel.Children.Add(new TextBlock
                {
                    Text = "No rules - the title will be the name as it is. Press + Add rule.",
                    Foreground = (System.Windows.Media.Brush)window.Resources["Muted"],
                    Margin = new Thickness(2, 2, 2, 8),
                });
            }
        }

        private UIElement RuleRow(int index, VmCore.Rule rule)
        {
            var grid = new Grid { Margin = new Thickness(0, 0, 0, 5) };
            foreach (double[] w in new[] { new[] { 34.0, 0 }, new[] { 112.0, 0 }, new[] { 1.0, 1 }, new[] { 22.0, 0 }, new[] { 1.0, 1 }, new[] { 44.0, 0 }, new[] { 28.0, 0 }, new[] { 28.0, 0 }, new[] { 28.0, 0 } })
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(w[0], w[1] > 0 ? GridUnitType.Star : GridUnitType.Pixel) });

            var use = new CheckBox { IsChecked = rule.On, VerticalAlignment = VerticalAlignment.Center, ToolTip = "Use this rule" };
            use.Checked += (s, e) => Toggle(() => rule.On = true);
            use.Unchecked += (s, e) => Toggle(() => rule.On = false);
            Grid.SetColumn(use, 0);
            grid.Children.Add(use);

            var mode = new ComboBox { Margin = new Thickness(0, 0, 8, 0) };
            foreach (string[] m in VmCore.RuleModes) mode.Items.Add(m[1]);
            int modeIndex = Array.FindIndex(VmCore.RuleModes, m => m[0] == rule.Mode);
            mode.SelectedIndex = modeIndex >= 0 ? modeIndex : 0;
            mode.ToolTip = "Text: the letters as typed.  Whole word: not inside a longer word.  Regex: a pattern; \\1 is a captured group.  Extract: keep only what the pattern finds (the replace text, or the first group).";
            mode.SelectionChanged += (s, e) =>
            {
                if (loading) return;
                int i = mode.SelectedIndex;
                if (i >= 0 && i < VmCore.RuleModes.Length)
                {
                    rule.Mode = VmCore.RuleModes[i][0];
                    Guard("preview", UpdatePreviews);
                }
            };
            Grid.SetColumn(mode, 1);
            grid.Children.Add(mode);

            var find = new TextBox { Text = rule.Find ?? "" };
            find.TextChanged += (s, e) => { if (!loading) { rule.Find = find.Text ?? ""; Guard("preview", UpdatePreviews); } };
            Grid.SetColumn(find, 2);
            grid.Children.Add(find);

            var arrow = new TextBlock
            {
                Text = "→",
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
                Foreground = (System.Windows.Media.Brush)window.Resources["Muted"],
            };
            Grid.SetColumn(arrow, 3);
            grid.Children.Add(arrow);

            var replace = new TextBox { Text = rule.Replace ?? "" };
            replace.TextChanged += (s, e) => { if (!loading) { rule.Replace = replace.Text ?? ""; Guard("preview", UpdatePreviews); } };
            Grid.SetColumn(replace, 4);
            grid.Children.Add(replace);

            var matchCase = new CheckBox { IsChecked = rule.MatchCase, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center, ToolTip = "Match case" };
            matchCase.Checked += (s, e) => Toggle(() => rule.MatchCase = true);
            matchCase.Unchecked += (s, e) => Toggle(() => rule.MatchCase = false);
            Grid.SetColumn(matchCase, 5);
            grid.Children.Add(matchCase);

            int offset = 0;
            foreach (object[] spec in new[] { new object[] { "▲", "Move up", -1 }, new object[] { "▼", "Move down", 1 }, new object[] { "✕", "Remove this rule", 0 } })
            {
                int step = (int)spec[2];
                var button = new Button { Content = spec[0], ToolTip = spec[1], Style = (Style)window.FindResource("Flat"), FontSize = 10 };
                button.Click += (s, e) => Guard("rule move", () => MoveRule(index, step));
                Grid.SetColumn(button, 6 + offset);
                grid.Children.Add(button);
                offset++;
            }
            return grid;
        }

        private void Toggle(Action set)
        {
            if (loading) return;
            set();
            Guard("preview", UpdatePreviews);
        }

        private void MoveRule(int index, int step)
        {
            List<VmCore.Rule> rules = current.Rules;
            if (step == 0)
            {
                if (index >= 0 && index < rules.Count) rules.RemoveAt(index);
            }
            else
            {
                int other = index + step;
                if (index >= 0 && index < rules.Count && other >= 0 && other < rules.Count)
                {
                    VmCore.Rule t = rules[index];
                    rules[index] = rules[other];
                    rules[other] = t;
                }
            }
            BuildRules();
            UpdatePreviews();
        }

        // ---------------------------------------------------------------- previews and applying --

        private string SourceText(long viewId)
        {
            string v;
            if (current.Source == "title") return sourceTitle.TryGetValue(viewId, out v) ? v : "";
            return sourceName.TryGetValue(viewId, out v) ? v : "";
        }

        private void UpdatePreviews()
        {
            var list = new List<string>();
            foreach (VmCore.Rule rule in current.Rules)
            {
                if (!rule.On) continue;
                string why;
                VmCore.CompileRule(rule, out why);
                if (why.Length > 0 && !list.Contains(why)) list.Add(why);
            }
            foreach (VmCore.RefRow row in mine)
                previews[row.ViewId] = VmCore.Rewrite(SourceText(row.ViewId), current.Rules, current.Case, current.Tidy, null);
            problems.Text = string.Join("  |  ", list);
            host.Sync();
        }

        private void OnApply()
        {
            List<long> chosen = host.SelectedIds();
            List<long> targets = chosen.Count > 0 ? chosen : mine.Select(r => r.ViewId).ToList();
            int done = 0, skipped = 0;
            foreach (long viewId in targets)
            {
                string text;
                if (!previews.TryGetValue(viewId, out text) || text.Length == 0)
                {
                    skipped++;
                    continue;
                }
                string held, message;
                if (store.Stage(viewId, target, text, out held, out message)) done++;
                else skipped++;
            }
            host.Sync();
            string extra = skipped > 0 ? " " + skipped + " left alone (no result, or the cell cannot be set - e.g. not on a sheet)." : "";
            Say("Wrote " + done + " " + noun + "(s) from the ruleset. Edit any cell by hand (double-click), then OK." + extra);
        }

        private void OnOk()
        {
            List<VmCore.EditItem> changes = store.Items();
            window.Close();
            if (changes.Count > 0) tab.AcceptBuilder(changes);
        }
    }
}
