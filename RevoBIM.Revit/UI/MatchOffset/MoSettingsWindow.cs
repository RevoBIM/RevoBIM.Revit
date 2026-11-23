using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Xml;
using Autodesk.Revit.UI;
using RevoBIM.Tools.MatchOffset;
using RevoBIM.Tools.Nudge;

using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.MatchOffset
{
    /// <summary>
    /// The settings window: standalone and modal, nothing is written until Apply. Three tabs (plain buttons swapping
    /// Visibility) so a section fits without scrolling. Port of settings_window.py. Keyboard shortcuts are written
    /// into Revit's KeyboardShortcuts.xml, matched by the button's id.
    /// </summary>
    internal sealed class MoSettingsWindow
    {
        private static readonly string[][] RoundModeChoices = { new[] { "up", "up to the next" }, new[] { "nearest", "to the nearest" }, new[] { "down", "down to the last" } };
        private static readonly string[][] RoundDatumChoices = { new[] { "level", "the offset from its level" }, new[] { "project", "the project elevation" } };
        private static readonly string[][] MeasureChoices = { new[] { "size", "the size parameters" }, new[] { "box", "the bounding box" } };
        private static readonly string[][] PointMeasureChoices = { new[] { "solid", "their real faces" }, new[] { "insertion", "their offset from level" }, new[] { "box", "their bounding box" } };
        private static readonly string[][] FabMeasureChoices = { new[] { "parameters", "top and bottom of part" }, new[] { "solid", "their real faces" }, new[] { "box", "their bounding box" } };
        private static readonly string[][] HangerTopChoices = { new[] { "bearing", "the face they bear on" }, new[] { "solid", "the top of their solids" }, new[] { "box", "their bounding box" } };
        private static readonly string[][] FramingChoices = { new[] { "top", "the top face it supports on" }, new[] { "solid", "its real faces" }, new[] { "box", "its bounding box" } };
        private static readonly string[][] SlopedChoices = { new[] { "skip", "are reported and left alone" }, new[] { "point", "are matched at the clicked point" } };
        private static readonly string[][] FittingChoices = { new[] { "skip", "are left for their pipes to move" }, new[] { "move", "are moved on their own" } };
        private static readonly string[][] ShowChoices = { new[] { "problems", "only if something needs a look" }, new[] { "always", "always" }, new[] { "never", "never" } };
        private static readonly string[][] SlopeSourceChoices = { new[] { "main", "the main's own fall" }, new[] { "fixed", "a fixed 1 in N" } };
        private static readonly string[][] SlopeDirectionChoices = { new[] { "towards", "towards the junction" }, new[] { "away", "away from the junction" }, new[] { "keep", "the way it already falls" } };
        private static readonly string[][] SlopeRepeatChoices = { new[] { "pairs", "ask for a new main" }, new[] { "main", "keep the same main" } };
        private static readonly string[][] SlopeJunctionChoices = { new[] { "auto", "tee or bend to suit" }, new[] { "none", "bring the ends together only" } };

        // (combo name, settings key, choices, default)
        private static readonly object[][] Combos =
        {
            new object[] { "RoundMode", "round_mode", RoundModeChoices, "up" },
            new object[] { "RoundDatum", "round_datum", RoundDatumChoices, "level" },
            new object[] { "MeasureMode", "measure", MeasureChoices, "size" },
            new object[] { "PointMeasure", "point_measure", PointMeasureChoices, "solid" },
            new object[] { "FabMeasure", "fab_measure", FabMeasureChoices, "parameters" },
            new object[] { "HangerTop", "fab_hanger_top", HangerTopChoices, "bearing" },
            new object[] { "FramingMeasure", "framing_measure", FramingChoices, "top" },
            new object[] { "SlopedMode", "sloped", SlopedChoices, "skip" },
            new object[] { "FittingMode", "connected_fittings", FittingChoices, "skip" },
            new object[] { "ShowResults", "show_results", ShowChoices, "problems" },
            new object[] { "SlopeSource", "slope_source", SlopeSourceChoices, "main" },
            new object[] { "SlopeDirection", "slope_direction", SlopeDirectionChoices, "towards" },
            new object[] { "SlopeFitting", "slope_fitting", SlopeJunctionChoices, "auto" },
            new object[] { "SlopeRepeat", "slope_repeat", SlopeRepeatChoices, "pairs" },
        };

        // (text box name, settings key, floor or null for "any number", default key)
        private static readonly object[][] Numbers =
        {
            new object[] { "RoundStep", "round_step_mm", 0.0 },
            new object[] { "SlopeTol", "slope_tol_deg", 0.0 },
            new object[] { "SlopeFixedN", "slope_fixed_n", 1.0 },
            new object[] { "SlopeSteep", "slope_steep_deg", 1.0 },
            new object[] { "SlopeLimit", "slope_limit", 1.0 },
            new object[] { "SlopeStub", "slope_stub_mm", 0.0 },
            new object[] { "SlopeLateral", "slope_inline_offset_mm", 0.0 },
        };

        private static readonly string[][] Checks =
        {
            new[] { "MoveSourceCheck", "move_source_on_round" }, new[] { "InsulationCheck", "include_insulation" },
            new[] { "PreselectCheck", "use_preselection" }, new[] { "RememberCheck", "remember_datum" },
            new[] { "SlopeMatchCheck", "slope_match_slope" }, new[] { "SlopeTrimCheck", "slope_trim" },
            new[] { "SlopeApparentCheck", "slope_apparent" }, new[] { "SlopeExtendCheck", "slope_extend_main" },
            new[] { "SlopeHandCheck", "slope_hand_fitting" }, new[] { "SlopeSquareCheck", "slope_square_branch" },
            new[] { "SlopeInLineCheck", "slope_in_line" }, new[] { "HangerRodsCheck", "fab_hanger_rods" },
            new[] { "DebugCheck", "debug_report" }, new[] { "SilentCheck", "silent" },
        };

        // (text box, settings key, ribbon button id, the button's name in Revit's shortcut list)
        private static readonly string[][] KeyBoxes =
        {
            new[] { "KeyBottom", "key_bottom", "RevoBIM_MatchOffsetBottom", "Match Offset Bottom" },
            new[] { "KeyMiddle", "key_middle", "RevoBIM_MatchOffsetMiddle", "Match Offset Middle" },
            new[] { "KeyTop", "key_top", "RevoBIM_MatchOffsetTop", "Match Offset Top" },
            new[] { "KeySlope", "key_slope", "RevoBIM_MatchOffsetSlope", "Match Offset Slope" },
        };

        private static readonly string[][] Tabs = { new[] { "TabOffset", "PanelOffset" }, new[] { "TabSlope", "PanelSlope" }, new[] { "TabPicking", "PanelPicking" } };

        private readonly UIApplication uiapp;
        private readonly Window window;
        private Dictionary<string, string> settings;
        private readonly Dictionary<string, CheckBox> categoryBoxes = new Dictionary<string, CheckBox>();
        private readonly Dictionary<string, TextBlock> categoryHeadings = new Dictionary<string, TextBlock>();

        public MoSettingsWindow(UIApplication uiapp)
        {
            this.uiapp = uiapp;
            settings = MoCore.LoadSettings();
            window = MoUi.LoadWindow("MatchOffsetSettings.xaml", MoCore.Get(settings, "theme"));
            Build();
        }

        private T F<T>(string name) where T : class { return (T)window.FindName(name); }

        private static bool CategoryExists(string bicName) { return MoModel.BuiltinCategory(bicName).HasValue; }

        private void Build()
        {
            MoUi.WireHeader(window, settings, ThemeChanged, armEgg: true);
            MoUi.OwnToRevit(window, uiapp);

            foreach (object[] number in Numbers) F<TextBox>((string)number[0]).Text = MoCore.Get(settings, (string)number[1]);
            foreach (object[] combo in Combos) Fill(F<ComboBox>((string)combo[0]), (string[][])combo[2], MoCore.Get(settings, (string)combo[1]));
            foreach (string[] check in Checks) F<CheckBox>(check[0]).IsChecked = MoCore.IsOn(settings, check[1]);
            foreach (string[] key in KeyBoxes) F<TextBox>(key[0]).Text = MoCore.Get(settings, key[1]);

            BuildCategories();

            // Handlers are bound here with += rather than in the XAML: a XAML-wired handler that silently fails to bind
            // leaves a window that looks right and does nothing.
            F<Button>("CategoryAll").Click += (s, a) => SetVisibleCategories(true);
            F<Button>("CategoryNone").Click += (s, a) => SetVisibleCategories(false);
            F<TextBox>("CategorySearch").TextChanged += (s, a) => FilterCategories();
            F<Button>("ApplyShortcuts").Click += (s, a) => ApplyShortcuts();
            F<Button>("OpenShortcuts").Click += (s, a) => OpenShortcuts();
            F<Button>("ApplyButton").Click += (s, a) => Apply();
            F<Button>("CloseFooter").Click += (s, a) => window.Close();
            foreach (string[] tab in Tabs)
            {
                string name = tab[0];
                F<Button>(name).Click += (s, a) => ShowTab(name);
            }

            ShowTab("TabOffset");
            Say("");
        }

        private static void Fill(ComboBox combo, string[][] choices, string value)
        {
            combo.Items.Clear();
            var values = new List<string>();
            int index = 0;
            for (int position = 0; position < choices.Length; position++)
            {
                values.Add(choices[position][0]);
                combo.Items.Add(choices[position][1]);
                if (choices[position][0] == value) index = position;
            }
            combo.Tag = values;
            combo.SelectedIndex = index;
        }

        private static string ComboValue(ComboBox combo, string fallback)
        {
            var values = combo.Tag as List<string>;
            int position = combo.SelectedIndex;
            return values != null && position >= 0 && position < values.Count ? values[position] : fallback;
        }

        private static string NumberOrDefault(string text, string key, double? floor)
        {
            double? value = MoCore.ParseNumber(text);
            if (!value.HasValue || (floor.HasValue && value.Value < floor.Value)) value = MoCore.ParseNumber(MoCore.Defaults[key], 0.0);
            return MoCore.FormatMm(value.Value, 2);
        }

        // ------------------------------------------------------------------ tabs

        private void ShowTab(string wanted)
        {
            foreach (string[] tab in Tabs)
            {
                bool active = tab[0] == wanted;
                F<UIElement>(tab[1]).Visibility = active ? Visibility.Visible : Visibility.Collapsed;
                F<Button>(tab[0]).SetResourceReference(Control.ForegroundProperty, active ? "BlueBrush" : "MutedBrush");
            }
        }

        /// <summary>The palette is swapped on the open window, so the lit tab has to be pointed at the new brush.</summary>
        private void ThemeChanged(string mode)
        {
            foreach (string[] tab in Tabs)
            {
                if (F<UIElement>(tab[1]).Visibility == Visibility.Visible)
                {
                    ShowTab(tab[0]);
                    return;
                }
            }
        }

        // ------------------------------------------------------------------ categories

        /// <summary>
        /// The category list under its own headings: forty-six ticks in one column is a list nobody reads. The keyword
        /// filter hides a heading whose whole group has been filtered away.
        /// </summary>
        private void BuildCategories()
        {
            var panel = F<StackPanel>("CategoryPanel");
            panel.Children.Clear();
            categoryBoxes.Clear();
            categoryHeadings.Clear();
            var chosen = new HashSet<string>(MoCore.EnabledCategories(settings));
            bool first = true;
            foreach (string group in MoCore.CategoryGroups)
            {
                List<MoCategory> rows = MoCore.CategoriesIn(group).Where(r => CategoryExists(r.Bic)).ToList();
                if (rows.Count == 0) continue;
                var heading = new TextBlock { Text = group, Margin = new Thickness(0, first ? 0 : 10, 0, 5) };
                heading.SetResourceReference(TextBlock.ForegroundProperty, "OrangeBrush");
                panel.Children.Add(heading);
                categoryHeadings[group] = heading;
                first = false;
                foreach (MoCategory row in rows)
                {
                    var box = new CheckBox { Content = row.Label, Margin = new Thickness(10, 0, 0, 6), IsChecked = chosen.Contains(row.Key), Tag = row.Key };
                    panel.Children.Add(box);
                    categoryBoxes[row.Key] = box;
                }
            }
        }

        private void SetVisibleCategories(bool ticked)
        {
            foreach (CheckBox box in categoryBoxes.Values)
                if (box.Visibility == Visibility.Visible) box.IsChecked = ticked;
        }

        private void FilterCategories()
        {
            string term = F<TextBox>("CategorySearch").Text.Trim().ToLowerInvariant();
            var showing = MoCore.CategoryGroups.ToDictionary(g => g, g => false);
            foreach (MoCategory def in MoCore.CategoryDefs)
            {
                CheckBox box;
                if (!categoryBoxes.TryGetValue(def.Key, out box)) continue;
                string text = def.Label.ToLowerInvariant();
                bool hit = term.Length == 0 || term.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries).All(w => text.Contains(w)) ||
                           def.Group.ToLowerInvariant().Contains(term);
                box.Visibility = hit ? Visibility.Visible : Visibility.Collapsed;
                if (hit) showing[def.Group] = true;
            }
            foreach (KeyValuePair<string, TextBlock> heading in categoryHeadings)
                heading.Value.Visibility = showing[heading.Key] ? Visibility.Visible : Visibility.Collapsed;
        }

        // ------------------------------------------------------------------ collecting and saving

        private void Say(string text)
        {
            try
            {
                F<TextBlock>("StatusText").Text = text;
            }
            catch (Exception)
            {
            }
        }

        private void SayShortcuts(string text)
        {
            try
            {
                F<TextBlock>("ShortcutStatus").Text = text;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>A key sequence as Revit writes it: upper case letters and digits, no spaces.</summary>
        private static string NormaliseKey(string text)
        {
            return new string((text ?? "").Where(char.IsLetterOrDigit).ToArray()).ToUpperInvariant();
        }

        private Dictionary<string, string> Collect()
        {
            var collected = new Dictionary<string, string>(settings);
            foreach (object[] number in Numbers)
                collected[(string)number[1]] = NumberOrDefault(F<TextBox>((string)number[0]).Text, (string)number[1], (double)number[2]);
            foreach (object[] combo in Combos)
                collected[(string)combo[1]] = ComboValue(F<ComboBox>((string)combo[0]), (string)combo[3]);
            foreach (string[] check in Checks)
                collected[check[1]] = MoCore.OnOff(F<CheckBox>(check[0]).IsChecked == true);
            foreach (string[] key in KeyBoxes)
                collected[key[1]] = NormaliseKey(F<TextBox>(key[0]).Text);

            List<string> keys = MoCore.CategoryDefs.Where(d => categoryBoxes.ContainsKey(d.Key) && categoryBoxes[d.Key].IsChecked == true)
                                                   .Select(d => d.Key).ToList();
            if (keys.Count == 0)
            {
                // Leaving the tool with nothing to pick is not a state worth saving, so Pipes comes straight back on.
                keys.Add("pipes");
                if (categoryBoxes.ContainsKey("pipes")) categoryBoxes["pipes"].IsChecked = true;
            }
            collected["categories"] = string.Join("|", keys);
            return collected;
        }

        private void Apply()
        {
            Dictionary<string, string> collected = Collect();
            if (!MoCore.SaveSettings(collected))
            {
                Say("Could not write the settings file.");
                return;
            }
            settings = collected;
            double step = MoCore.ParseNumber(MoCore.Get(settings, "round_step_mm"), 0.0);
            var parts = new List<string>();
            if (step > 0)
                parts.Add("offsets round to " + MoCore.FormatMm(step) + " mm and the first element clicked " +
                          (MoCore.IsOn(settings, "move_source_on_round") ? "moves onto the rounded value too" : "stays where it is"));
            if (!MoCore.IsOn(settings, "slope_trim"))
                parts.Add("the slope tool matches the fall and the height but does not trim or fit");
            else if (MoCore.IsOn(settings, "slope_match_slope"))
                parts.Add("the slope tool matches the fall and fits the junction");
            else
                parts.Add("the slope tool matches the height only, keeping each branch's own fall");
            if (MoCore.IsSilent(settings))
                parts.Add("nothing is put on screen at the end of a run, though the debug report is still written to disk");
            else if (MoCore.IsOn(settings, "debug_report"))
                parts.Add("a debug report opens after every run");
            Say("Saved. " + string.Join("; ", parts) + ".");
        }

        // ------------------------------------------------------------------ shortcuts

        private void OpenShortcuts()
        {
            try
            {
                RevitCommandId command = RevitCommandId.LookupPostableCommandId(PostableCommand.KeyboardShortcuts);
                uiapp.PostCommand(command);
                SayShortcuts("Revit's Keyboard Shortcuts dialog will open when this window closes.");
                window.Close();
            }
            catch (Exception err)
            {
                SayShortcuts("Revit would not open its shortcuts dialog: " + err.Message + ". It is under View > User Interface > Keyboard Shortcuts.");
            }
        }

        /// <summary>
        /// Writes the shortcuts into Revit's KeyboardShortcuts.xml. Revit reads that file at startup, so a shortcut written
        /// here takes effect next session, and opening Revit's own shortcuts dialog and pressing OK before then writes the
        /// whole file back from memory and throws the change away.
        /// </summary>
        private void ApplyShortcuts()
        {
            Dictionary<string, string> collected = Collect();
            MoCore.SaveSettings(collected);
            settings = collected;

            NudgeShortcuts file = NudgeShortcuts.Open(uiapp.Application.VersionName);
            if (file == null)
            {
                SayShortcuts("Revit has not written a shortcuts file yet, so there is nothing to edit. Open Revit's Keyboard Shortcuts dialog " +
                             "once and press OK - that writes the file with every command in it, these buttons included - then come back.");
                return;
            }

            var wanted = new List<string[]>();   // button id, name, keys
            foreach (string[] key in KeyBoxes)
            {
                string keys = MoCore.Get(settings, key[1]).Trim();
                if (keys.Length > 0) wanted.Add(new[] { key[2], key[3], keys });
            }
            if (wanted.Count == 0)
            {
                SayShortcuts("No key sequences are filled in.");
                return;
            }

            var missing = new List<string>();
            var clashes = new List<string>();
            var items = new List<XmlElement>();
            foreach (string[] want in wanted)
            {
                XmlElement item = file.Find(want[0], want[1]);
                items.Add(item);
                if (item == null)
                {
                    missing.Add(want[1]);
                    continue;
                }
                foreach (string clash in file.Clashes(want[2], item)) clashes.Add(want[2] + "  is on  " + clash);
            }

            bool clear = true;
            if (clashes.Count > 0)
            {
                string body = "These key sequences are already in use:\n\n  " + string.Join("\n  ", clashes) +
                              "\n\nTake them off those commands and give them to Match Offset?";
                bool? answer = MoUi.Message("Shortcuts already in use", body, MoCore.Get(settings, "theme"), window,
                                            "Remap to Match Offset", "Leave them alone", "Cancel");
                if (answer == null)
                {
                    SayShortcuts("Nothing was changed.");
                    return;
                }
                clear = answer.Value;
            }

            var lines = new List<string>();
            var assigned = new List<string>();
            var cleared = new List<string>();
            for (int index = 0; index < wanted.Count; index++)
            {
                if (items[index] == null) continue;
                if (clear) cleared.AddRange(file.TakeOff(wanted[index][2], items[index]).Select(n => n + " lost " + wanted[index][2]));
                NudgeShortcuts.SetKeys(items[index], wanted[index][2]);
                assigned.Add(wanted[index][1] + " -> " + wanted[index][2]);
            }
            if (assigned.Count > 0 && !file.Save())
            {
                SayShortcuts("Could not write Revit's shortcuts file.");
                return;
            }
            if (assigned.Count > 0) lines.Add("Assigned: " + string.Join("; ", assigned));
            if (cleared.Count > 0) lines.Add("Cleared: " + string.Join("; ", cleared));
            if (missing.Count > 0)
                lines.Add("Revit has no entry for " + string.Join(", ", missing) + " yet. Start Revit once with this add-in, open its shortcuts " +
                          "dialog, press OK, and apply again.");
            if (assigned.Count > 0) lines.Add("Restart Revit for these to take effect.");
            SayShortcuts(string.Join("  ", lines));
            MoCore.Log("shortcuts written");
        }

        public Dictionary<string, string> Show()
        {
            window.ShowDialog();
            return settings;
        }
    }
}
