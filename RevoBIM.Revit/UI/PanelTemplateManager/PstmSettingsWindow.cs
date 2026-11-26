using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using RevoBIM.Helpers;
using RevoBIM.Tools.PanelTemplateManager;

using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using RadioButton = System.Windows.Controls.RadioButton;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.PanelTemplateManager
{
    /// <summary>The settings dialog (settings_window.py). Settings are global: which parameter holds the number of ways is a house standard, not a job by job thing.</summary>
    internal sealed class PstmSettingsWindow
    {
        private readonly Window w;
        private readonly List<string> paramNames, configNames;
        private Dictionary<string, string> settings;
        private string palette;

        public bool Saved;

        public PstmSettingsWindow(Window owner, Dictionary<string, string> settings, IEnumerable<string> paramNames, IEnumerable<string> configNames,
                                  IEnumerable<string> typeNames)
        {
            this.settings = new Dictionary<string, string>(settings);
            this.paramNames = paramNames.ToList();
            this.configNames = configNames.ToList();
            palette = PstmCore.Get(this.settings, "theme");
            w = PstmChrome.LoadWindow("PstmSettings.xaml", palette);
            WindowDrawer drawer = PstmChrome.MakeDrawer(w);
            PstmChrome.Adopt(w, owner, drawer);
            PstmChrome.SetText(w, "VersionText", "v" + PstmCore.Version);
            PstmChrome.SetIcon(w.FindName("ToolIcon") as Image);
            PstmChrome.WireDrag(w, (FrameworkElement)w.FindName("HeaderBar"), drawer);
            ((Button)w.FindName("CloseButton")).Click += (s, a) => Cancel();
            ((Button)w.FindName("CancelButton")).Click += (s, a) => Cancel();
            ((Button)w.FindName("SaveButton")).Click += (s, a) => Save();
            ((Button)w.FindName("DefaultsButton")).Click += (s, a) =>
            {
                this.settings = PstmCore.Defaults();
                palette = this.settings["theme"];
                PstmTheme.Apply(w, palette);
                Fill(typeNames.ToList());
                Preview();
            };
            Fill(typeNames.ToList());
            ((TextBox)w.FindName("WaysSearch")).TextChanged += (s, a) => Filter("WaysSearch", "WaysCombo");
            ((TextBox)w.FindName("PhasesSearch")).TextChanged += (s, a) => Filter("PhasesSearch", "PhasesCombo");
            ((ComboBox)w.FindName("ThemeCombo")).SelectionChanged += (s, a) =>
            {
                try
                {
                    string choice = (((ComboBox)w.FindName("ThemeCombo")).SelectedItem as string ?? "Dark").ToLowerInvariant();
                    palette = choice == "light" ? "light" : "dark";
                    PstmTheme.Apply(w, palette);
                }
                catch (Exception)
                {
                }
            };
            foreach (string name in new[] { "RuleLargest", "RuleFirst", "RuleKeyword" }) ((RadioButton)w.FindName(name)).Checked += (s, a) => Preview();
            ((TextBox)w.FindName("KeywordBox")).TextChanged += (s, a) => Preview();
            Preview();
        }

        private T C<T>(string name) where T : class
        {
            return w.FindName(name) as T;
        }

        private void Fill(List<string> typeNames)
        {
            Dictionary<string, string> s = settings;
            FillCombo("WaysCombo", paramNames, PstmCore.Get(s, "ways_param"));
            FillCombo("PhasesCombo", paramNames, PstmCore.Get(s, "phases_param"));
            var configs = new List<string> { "(All)" };
            configs.AddRange(configNames.Select(PstmModel.PrettyEnum));
            string want = PstmCore.Get(s, "default_config");
            FillCombo("DefaultConfigCombo", configs, want == "All" ? "(All)" : PstmModel.PrettyEnum(want));
            var types = new List<string> { "(All types)" };
            types.AddRange(typeNames);
            FillCombo("DefaultTypeCombo", types, PstmCore.Get(s, "default_schedule_type"));
            FillCombo("ThemeCombo", new List<string> { "Dark", "Light" }, PstmCore.Get(s, "theme") == "light" ? "Light" : "Dark");
            string rule = (PstmCore.Get(s, "name_number_rule") ?? "largest").ToLowerInvariant();
            C<RadioButton>("RuleLargest").IsChecked = rule == "largest";
            C<RadioButton>("RuleFirst").IsChecked = rule == "first";
            C<RadioButton>("RuleKeyword").IsChecked = rule == "keyword";
            C<TextBox>("KeywordBox").Text = PstmCore.Get(s, "name_number_keyword");
            C<TextBox>("PhasesFallbackBox").Text = PstmCore.Get(s, "phases_fallback");
            C<TextBox>("SlotStepBox").Text = PstmCore.Get(s, "slot_step");
            C<TextBox>("SlotMinBox").Text = PstmCore.Get(s, "slot_min");
            C<TextBox>("SlotMaxBox").Text = PstmCore.Get(s, "slot_max");
            C<CheckBox>("MatchTypeCheck").IsChecked = PstmCore.AsBool(PstmCore.Get(s, "match_schedule_type"), true);
            C<CheckBox>("ConfirmApplyCheck").IsChecked = PstmCore.AsBool(PstmCore.Get(s, "confirm_apply"), true);
            C<CheckBox>("RebuildScheduleCheck").IsChecked = PstmCore.AsBool(PstmCore.Get(s, "rebuild_schedule"), true);
        }

        private void FillCombo(string name, List<string> items, string selected)
        {
            var combo = C<ComboBox>(name);
            combo.Items.Clear();
            foreach (string item in items) combo.Items.Add(item);
            if (!string.IsNullOrEmpty(selected) && items.Contains(selected)) combo.SelectedItem = selected;
            else if (items.Count > 0) combo.SelectedIndex = 0;
        }

        private string Unpretty(string pretty)
        {
            if (pretty == "(All)") return "All";
            foreach (string name in configNames)
                if (PstmModel.PrettyEnum(name) == pretty) return name;
            return (pretty ?? "").Replace(" ", "");
        }

        private void Filter(string searchName, string comboName)
        {
            string text = (C<TextBox>(searchName).Text ?? "").Trim().ToLowerInvariant();
            var combo = C<ComboBox>(comboName);
            string keep = combo.SelectedItem as string;
            combo.Items.Clear();
            foreach (string item in paramNames)
                if (text.Length == 0 || item.ToLowerInvariant().Contains(text)) combo.Items.Add(item);
            if (keep != null && combo.Items.Cast<object>().Any(i => (i as string) == keep)) combo.SelectedItem = keep;
            else if (combo.Items.Count > 0) combo.SelectedIndex = 0;
        }

        private string NameRule()
        {
            if (C<RadioButton>("RuleFirst").IsChecked == true) return "first";
            if (C<RadioButton>("RuleKeyword").IsChecked == true) return "keyword";
            return "largest";
        }

        private void Preview()
        {
            try
            {
                string keyword = C<TextBox>("KeywordBox").Text;
                if (string.IsNullOrEmpty(keyword)) keyword = "way";
                const string sample = "BGL_Panel Schedule 36 Way TPN Rev 2";
                int? found = PstmCore.ExtractTemplateNumber(sample, NameRule(), keyword);
                PstmChrome.SetText(w, "NameRulePreview", "\"" + sample + "\" reads as " + (found != null ? found.Value.ToString() : "no number"));
            }
            catch (Exception)
            {
            }
        }

        private Dictionary<string, string> Collect()
        {
            var s = new Dictionary<string, string>(settings);
            // an empty combo means the search box has filtered everything out, not that the user cleared the setting
            string ways = C<ComboBox>("WaysCombo").SelectedItem as string ?? "";
            string phases = C<ComboBox>("PhasesCombo").SelectedItem as string ?? "";
            s["ways_param"] = ways.Length > 0 ? ways : PstmCore.Get(settings, "ways_param");
            s["phases_param"] = phases.Length > 0 ? phases : PstmCore.Get(settings, "phases_param");
            s["default_schedule_type"] = C<ComboBox>("DefaultTypeCombo").SelectedItem as string ?? "Branch Panel";
            s["phases_fallback"] = (C<TextBox>("PhasesFallbackBox").Text ?? "").Trim();
            s["name_number_rule"] = NameRule();
            string kw = (C<TextBox>("KeywordBox").Text ?? "way").Trim();
            s["name_number_keyword"] = kw.Length > 0 ? kw : "way";
            s["default_config"] = Unpretty(C<ComboBox>("DefaultConfigCombo").SelectedItem as string ?? "OneColumn");
            s["theme"] = palette;
            Func<string, int, string> num = (name, fallback) =>
            {
                int n = PstmCore.AsInt(C<TextBox>(name).Text, fallback);
                return (n != 0 ? n : fallback).ToString();
            };
            s["slot_step"] = num("SlotStepBox", 3);
            s["slot_min"] = num("SlotMinBox", 3);
            s["slot_max"] = num("SlotMaxBox", 120);
            s["match_schedule_type"] = C<CheckBox>("MatchTypeCheck").IsChecked == true ? "1" : "0";
            s["confirm_apply"] = C<CheckBox>("ConfirmApplyCheck").IsChecked == true ? "1" : "0";
            s["rebuild_schedule"] = C<CheckBox>("RebuildScheduleCheck").IsChecked == true ? "1" : "0";
            return s;
        }

        private void Save()
        {
            settings = Collect();
            PstmCore.SaveSettings(settings);
            Saved = true;
            PstmCore.Log("settings saved: ways '" + PstmCore.Get(settings, "ways_param") + "', phases '" + PstmCore.Get(settings, "phases_param") +
                         "', theme " + PstmCore.Get(settings, "theme") + ", rule " + PstmCore.Get(settings, "name_number_rule"));
            try { w.DialogResult = true; } catch (Exception) { w.Close(); }
        }

        private void Cancel()
        {
            Saved = false;
            try { w.DialogResult = false; } catch (Exception) { w.Close(); }
        }

        public bool Show(out Dictionary<string, string> values)
        {
            try
            {
                w.ShowDialog();
            }
            catch (Exception)
            {
            }
            values = settings;
            return Saved;
        }
    }
}
