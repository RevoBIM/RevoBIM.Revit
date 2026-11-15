using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media.Imaging;
using System.Xml;
using RevoBIM.Helpers;
using RevoBIM.Tools.Nudge;

namespace RevoBIM.UI.Nudge
{
    /// <summary>
    /// Nudge Settings: the increment, rounding and behaviour shared by Nudge Up and Nudge Down, plus the
    /// keyboard shortcuts written straight into Revit's shortcuts file. Port of the pyRevit window.
    /// </summary>
    public partial class NudgeSettingsWindow : Window
    {
        // (text box, ribbon button name used for the shortcut lookup, command label)
        private readonly (TextBox Box, string Button, string Label)[] commands;
        private readonly NudgeShortcuts shortcuts;

        public NudgeSettingsWindow(string revitVersionName)
        {
            InitializeComponent();
            commands = new[]
            {
                (ks_up, "RevoBIM_NudgeUp", "Nudge Up"),
                (ks_down, "RevoBIM_NudgeDown", "Nudge Down"),
                (ks_settings, "RevoBIM_NudgeSettings", "Nudge Settings"),
            };
            version_tb.Text = "v" + NudgeSettings.Version;
            LoadIcon();
            EggHook.Attach(this, () => "dark", tool_icon, brand_tb);
            Load();
            shortcuts = NudgeShortcuts.Open(revitVersionName);
            LoadShortcuts();
        }

        private void LoadIcon()
        {
            try
            {
                Assembly assembly = Assembly.GetExecutingAssembly();
                using (Stream stream = assembly.GetManifestResourceStream("RevoBIM.Resources.NudgeSettings.icon.png"))
                {
                    if (stream == null) return;
                    var image = new BitmapImage();
                    image.BeginInit();
                    image.StreamSource = stream;
                    image.CacheOption = BitmapCacheOption.OnLoad;
                    image.EndInit();
                    image.Freeze();
                    tool_icon.Source = image;
                }
            }
            catch (Exception)
            {
            }
        }

        // ------------------------------------------------------------ shortcuts

        private void LoadShortcuts()
        {
            if (shortcuts == null)
            {
                ks_note.Text = "Revit's shortcuts file has not been found. Open Keyboard Shortcuts (type KS), " +
                               "press OK once to create it, then come back here.";
                foreach (var c in commands) c.Box.IsEnabled = false;
                return;
            }

            var missing = new List<string>();
            foreach (var c in commands)
            {
                XmlElement item = shortcuts.Find(c.Button, c.Label);
                if (item == null)
                {
                    c.Box.IsEnabled = false;
                    missing.Add(c.Label);
                }
                else
                {
                    c.Box.Text = NudgeShortcuts.GetKeys(item);
                }
            }
            if (missing.Count > 0)
                ks_note.Text = "Revit has not registered " + string.Join(", ", missing) +
                               " yet. It only reads the ribbon at startup, so restart Revit fully, " +
                               "then reopen this window.";
        }

        /// <summary>Writes the three shortcuts. Returns a note to show, or null if nothing changed.</summary>
        private string SaveShortcuts()
        {
            if (shortcuts == null) return null;

            var changed = new List<string>();
            var clashed = new List<string>();
            foreach (var c in commands)
            {
                if (!c.Box.IsEnabled) continue;
                XmlElement item = shortcuts.Find(c.Button, c.Label);
                if (item == null) continue;
                string wanted = (c.Box.Text ?? "").Trim().ToUpperInvariant();
                if (wanted == NudgeShortcuts.GetKeys(item)) continue;
                clashed.AddRange(shortcuts.Clashes(wanted, item));
                NudgeShortcuts.SetKeys(item, wanted);
                changed.Add(c.Label);
            }
            if (changed.Count == 0) return null;

            if (!shortcuts.Save()) return "Settings saved, but the shortcuts file could not be written.";
            string note = "Shortcuts set. Restart Revit for them to take effect.";
            if (clashed.Count > 0) note += " Note " + clashed[0] + " already uses one of those keys.";
            return note;
        }

        // ---------------------------------------------------------------- state

        private static string Fmt(double value)
        {
            return Math.Abs(value - Math.Round(value)) < 1e-9
                ? ((long)Math.Round(value)).ToString(CultureInfo.InvariantCulture)
                : value.ToString("0.###", CultureInfo.InvariantCulture);
        }

        private void Load()
        {
            Show(NudgeSettings.Load());
        }

        private void Show(NudgeConfig cfg)
        {
            tb_step.Text = Fmt(cfg.StepMm);
            cb_snap.IsChecked = cfg.SnapEnabled;
            tb_snap.Text = Fmt(cfg.SnapMm > 0 ? cfg.SnapMm : new NudgeConfig().SnapMm);
            cb_keep.IsChecked = cfg.KeepSelection;
            cb_loop.IsChecked = cfg.RepeatLoop;
            cb_fittings.IsChecked = cfg.AllowFittings;
            cb_fab.IsChecked = cfg.AllowFabrication;
            cb_rods.IsChecked = cfg.RecutRods;

            Button[] chips = { chip_1, chip_2, chip_3, chip_4 };
            double[] presets = cfg.Presets != null && cfg.Presets.Length > 0 ? cfg.Presets : new NudgeConfig().Presets;
            for (int i = 0; i < chips.Length; i++)
            {
                bool visible = i < presets.Length;
                chips[i].Content = visible ? Fmt(presets[i]) : "";
                chips[i].Visibility = visible ? Visibility.Visible : Visibility.Collapsed;
            }
        }

        private static bool TryNumber(string text, out double value)
        {
            return double.TryParse((text ?? "").Trim().Replace(',', '.'), NumberStyles.Float,
                                   CultureInfo.InvariantCulture, out value);
        }

        private NudgeConfig Collect()
        {
            if (!TryNumber(tb_step.Text, out double step) || step <= 0) return null;
            if (!TryNumber(tb_snap.Text, out double snap) || snap < 0) return null;
            NudgeConfig current = NudgeSettings.Load();   // keeps the saved presets
            current.StepMm = step;
            current.SnapEnabled = cb_snap.IsChecked == true;
            current.SnapMm = snap;
            current.KeepSelection = cb_keep.IsChecked == true;
            current.RepeatLoop = cb_loop.IsChecked == true;
            current.AllowFittings = cb_fittings.IsChecked == true;
            current.AllowFabrication = cb_fab.IsChecked == true;
            current.RecutRods = cb_rods.IsChecked == true;
            return current;
        }

        // ------------------------------------------------------------- handlers

        private void header_drag(object sender, MouseButtonEventArgs args)
        {
            try
            {
                DragMove();
            }
            catch (Exception)
            {
            }
        }

        private void close_click(object sender, MouseButtonEventArgs args) => Close();

        private void preset_click(object sender, RoutedEventArgs args)
        {
            string value = ((sender as Button)?.Content as string ?? "").Trim();
            if (value.Length == 0) return;
            tb_step.Text = value;
            status_tb.Text = "Increment set to " + value + " mm. Press Save.";
        }

        private void reset_click(object sender, RoutedEventArgs args)
        {
            var defaults = new NudgeConfig();
            tb_step.Text = Fmt(defaults.StepMm);
            cb_snap.IsChecked = defaults.SnapEnabled;
            tb_snap.Text = Fmt(defaults.SnapMm);
            cb_keep.IsChecked = defaults.KeepSelection;
            cb_loop.IsChecked = defaults.RepeatLoop;
            cb_fittings.IsChecked = defaults.AllowFittings;
            cb_fab.IsChecked = defaults.AllowFabrication;
            cb_rods.IsChecked = defaults.RecutRods;
            status_tb.Text = "Back to defaults. Press Save to keep them.";
        }

        private void save_click(object sender, RoutedEventArgs args)
        {
            NudgeConfig cfg = Collect();
            if (cfg == null)
            {
                status_tb.Text = "The increment must be a positive number and the rounding must not be negative. Try 50 and 5.";
                return;
            }
            if (!NudgeSettings.Save(cfg))
            {
                status_tb.Text = "Could not write to " + NudgeSettings.FilePath + ".";
                return;
            }

            string note;
            try
            {
                note = SaveShortcuts();
            }
            catch (Exception)
            {
                note = "Settings saved, but the shortcuts could not be written.";
            }

            if (note != null)
            {
                // leave the window up so the restart message is actually read
                status_tb.Text = note;
                return;
            }
            Close();
        }
    }
}
