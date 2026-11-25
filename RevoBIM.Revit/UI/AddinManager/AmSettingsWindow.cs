using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using RevoBIM.Tools.AddinManager;

using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.AddinManager
{
    /// <summary>The settings window. Modal: nothing in it needs anything picked in the model. Port of rba_settings.py.</summary>
    internal static class AmSettingsWindow
    {
        private static readonly string[][] GroupBy = { new[] { "tab", "Tab" }, new[] { "panel", "Panel" } };
        private static readonly string[][] Docks = { new[] { "left", "Left" }, new[] { "right", "Right" }, new[] { "floating", "Floating" } };
        private static readonly string[][] Themes = { new[] { "auto", "Auto - follow Revit" }, new[] { "dark", "Dark" }, new[] { "light", "Light" } };

        private static void Fill(ComboBox combo, string[][] pairs, string current)
        {
            combo.Items.Clear();
            int index = 0;
            for (int i = 0; i < pairs.Length; i++)
            {
                combo.Items.Add(pairs[i][1]);
                if (pairs[i][0] == (current ?? "").Trim().ToLowerInvariant()) index = i;
            }
            combo.SelectedIndex = index;
        }

        private static string Picked(ComboBox combo, string[][] pairs)
        {
            int at = combo.SelectedIndex;
            if (at < 0 || at >= pairs.Length) at = 0;
            return pairs[at][0];
        }

        /// <summary>Returns the edited settings, or null when cancelled.</summary>
        public static Dictionary<string, string> Show(Dictionary<string, string> settings, string theme, Window owner, List<string> allTabs)
        {
            Window window = AmXaml.Load<Window>("RbaSettings.xaml", theme);
            AmUi.Own(window, owner);
            Func<string, FrameworkElement> find = name => window.FindName(name) as FrameworkElement;

            ((TextBlock)find("VersionText")).Text = "v" + AmCore.Version;
            find("ShrinkBtn").Visibility = Visibility.Collapsed;   // a modal dialog has no drawer here

            ((TextBox)find("NameFilterBox")).Text = AmCore.Get(settings, "name_filter");
            var iconPairs = new List<string[]>();
            foreach (int size in AmCore.IconSizes) iconPairs.Add(new[] { size.ToString(), size + " px" });
            string[][] iconArray = iconPairs.ToArray();
            Fill((ComboBox)find("GroupByCombo"), GroupBy, AmCore.Get(settings, "group_by"));
            Fill((ComboBox)find("IconSizeCombo"), iconArray, AmCore.Get(settings, "icon_size"));
            Fill((ComboBox)find("ThemeCombo"), Themes, AmCore.Get(settings, "theme"));
            Fill((ComboBox)find("DockCombo"), Docks, AmCore.Get(settings, "dock"));

            ((CheckBox)find("TooltipsChk")).IsChecked = AmCore.AsBool(settings, "show_tooltips");
            ((CheckBox)find("PathsChk")).IsChecked = AmCore.AsBool(settings, "show_paths");
            ((CheckBox)find("BuiltInChk")).IsChecked = AmCore.AsBool(settings, "include_builtin");
            ((CheckBox)find("WatchChk")).IsChecked = AmCore.AsBool(settings, "watch");
            ((CheckBox)find("DebugChk")).IsChecked = AmCore.AsBool(settings, "debug");
            ((TextBox)find("WatchMsBox")).Text = AmCore.AsInt(settings, "watch_ms", 1500).ToString();
            ((TextBlock)find("FooterText")).Text = AmCore.SettingsPath();
            ((CheckBox)find("PathsChk")).Content = "Put the command id in the tooltip";

            // one tick per tab: unticked tabs are hidden from the panel
            var hidden = new HashSet<string>(AmCore.AsList(settings, "hidden_tabs"));
            var tabBoxes = new List<CheckBox>();
            var tabsPanel = (StackPanel)find("TabsPanel");
            foreach (string tab in allTabs ?? new List<string>())
            {
                var box = new CheckBox
                {
                    Content = tab,
                    Tag = AmCore.Normalise(tab).Replace("|", "/"),
                    IsChecked = !hidden.Contains(AmCore.Normalise(tab).Replace("|", "/")),
                };
                tabBoxes.Add(box);
                tabsPanel.Children.Add(box);
            }
            ((Button)find("TabsAllBtn")).Click += (s, a) => tabBoxes.ForEach(b => b.IsChecked = true);
            ((Button)find("TabsNoneBtn")).Click += (s, a) => tabBoxes.ForEach(b => b.IsChecked = false);

            Dictionary<string, string> result = null;
            Func<string, bool> ticked = name => ((CheckBox)find(name)).IsChecked == true;

            ((Button)find("ApplyBtn")).Click += (s, a) =>
            {
                var values = new Dictionary<string, string>(AmCore.Defaults);
                foreach (var pair in settings) values[pair.Key] = pair.Value;
                values["name_filter"] = ((TextBox)find("NameFilterBox")).Text.Trim();
                // keep any hidden tab that is not on the ribbon right now, so it stays hidden when its addin comes back
                var nowHidden = new HashSet<string>(hidden);
                foreach (CheckBox b in tabBoxes)
                {
                    string tag = (string)b.Tag;
                    if (b.IsChecked == true) nowHidden.Remove(tag); else nowHidden.Add(tag);
                }
                AmCore.SetList(values, "hidden_tabs", nowHidden);
                values["group_by"] = Picked((ComboBox)find("GroupByCombo"), GroupBy);
                values["icon_size"] = Picked((ComboBox)find("IconSizeCombo"), iconArray);
                values["theme"] = Picked((ComboBox)find("ThemeCombo"), Themes);
                values["dock"] = Picked((ComboBox)find("DockCombo"), Docks);
                values["show_tooltips"] = ticked("TooltipsChk") ? "1" : "0";
                values["show_paths"] = ticked("PathsChk") ? "1" : "0";
                values["include_builtin"] = ticked("BuiltInChk") ? "1" : "0";
                values["watch"] = ticked("WatchChk") ? "1" : "0";
                values["debug"] = ticked("DebugChk") ? "1" : "0";
                int ms;
                values["watch_ms"] = int.TryParse(((TextBox)find("WatchMsBox")).Text.Trim(), out ms)
                    ? Math.Max(400, ms).ToString() : AmCore.Defaults["watch_ms"];
                result = values;
                window.Close();
            };
            ((Button)find("CancelBtn")).Click += (s, a) => window.Close();
            ((Button)find("CloseBtn")).Click += (s, a) => window.Close();
            window.KeyDown += (s, a) => { if (!a.Handled && a.Key == Key.Escape) window.Close(); };
            find("HeaderBar").MouseLeftButtonDown += (s, a) => { try { window.DragMove(); } catch (Exception) { } };

            window.ShowDialog();
            return result;
        }
    }
}
