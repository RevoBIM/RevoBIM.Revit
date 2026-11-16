using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using RevoBIM.Tools.HangerAutomation;

namespace RevoBIM.UI.HangerAutomation
{
    // Hanger Automation - the Hanger rules dialog and the Family settings dialog. Port of hfam_ui.py (RulesDialog,
    // FamSettingsDialog). FamTab is in HfamUi.cs.

    // ================================================================ rules
    /// <summary>The rules for hanging several services together.</summary>
    public sealed class RulesDialog
    {
        public readonly IFhaHost O;
        public bool Ok;
        public Dictionary<string, string> Result;
        public readonly Window Win;
        public readonly FhaDrawer Drawer;

        public RulesDialog(IFhaHost owner, IDictionary<string, string> settings)
        {
            O = owner;
            Ok = false;
            Result = null;
            Win = FhaUi.LoadXamlWindow("HangerRules.xaml");
            FhaUi.ApplyPalette(Win, owner.Mode);
            FhaUi.PlaceDialog(Win, owner);
            Drawer = FhaUi.DialogDrawer(Win, owner, (FrameworkElement)C("RulesHeader"), (ButtonBase)C("RulesShrinkBtn"),
                                        (UIElement)C("RulesShrinkIcon"), (UIElement)C("RulesExpandIcon"));
            ((TextBlock)C("RulesVerTxt")).Text = "v" + FhaCore.Version;
            ((TextBox)C("RulesZ")).Text = Sget(settings, "fam_group_z", "50");
            ((TextBox)C("RulesGap")).Text = Sget(settings, "fam_group_gap", "500");
            ((TextBox)C("RulesAngle")).Text = Sget(settings, "fam_group_angle", "2");
            List<string> keys = HfamCore.Centres.Select(c => c.Key).ToList();
            foreach (KeyValuePair<string, string> kv in HfamCore.Centres) ((ComboBox)C("RulesCentre")).Items.Add(kv.Value);
            string cur = Sget(settings, "fam_group_centre", "mean");
            ((ComboBox)C("RulesCentre")).SelectedIndex = keys.Contains(cur) ? keys.IndexOf(cur) : 0;
            ((ButtonBase)C("RulesSave")).Click += Save;
            ((ButtonBase)C("RulesCancel")).Click += Cancel;
            ((ButtonBase)C("RulesCloseBtn")).Click += Cancel;
            ((UIElement)C("RulesHeader")).MouseLeftButtonDown += Drag;
        }

        private static string Sget(IDictionary<string, string> s, string key, string dflt)
        {
            string v;
            return s != null && s.TryGetValue(key, out v) && v != null ? v : dflt;
        }

        public object C(string name)
        {
            return Win.FindName(name);
        }

        private void Drag(object sender, MouseButtonEventArgs e)
        {
            try
            {
                Win.DragMove();
            }
            catch (Exception)
            {
            }
        }

        private void Save(object sender, RoutedEventArgs e)
        {
            try
            {
                int i = ((ComboBox)C("RulesCentre")).SelectedIndex;
                Result = new Dictionary<string, string>(StringComparer.Ordinal)
                {
                    { "fam_group_z", FhaCore.NumText(FhaCore.ParseMm(((TextBox)C("RulesZ")).Text, 50.0)) },
                    { "fam_group_gap", FhaCore.NumText(FhaCore.ParseMm(((TextBox)C("RulesGap")).Text, 500.0)) },
                    { "fam_group_angle", FhaCore.NumText(Math.Min(45.0, FhaCore.ParseMm(((TextBox)C("RulesAngle")).Text, 2.0))) },
                    { "fam_group_centre", i >= 0 && i < HfamCore.Centres.Count ? HfamCore.Centres[i].Key : "mean" },
                };
                Ok = true;
            }
            catch (Exception)
            {
                Ok = false;
            }
            Win.Close();
        }

        private void Cancel(object sender, RoutedEventArgs e)
        {
            Win.Close();
        }

        public bool Show()
        {
            Win.ShowDialog();
            return Ok;
        }
    }

    // ============================================================== family settings
    /// <summary>
    /// Which parameters stretch the hanger, which is the drop rod (hangers) or the first bar offset and support
    /// height (floor supports), which way the width runs and where the rod stops - saved per family.
    /// </summary>
    public sealed class FamSettingsDialog
    {
        private static readonly string[] FloorRows = { "DlgFirstBarLbl", "DlgFirstBar", "DlgHeightLbl", "DlgHeight", "DlgHeightClearLbl", "DlgHeightClear" };
        private static readonly string[] HangRows = { "DlgRodLbl", "DlgRod", "DlgSoffitLbl", "DlgSoffit" };

        // rows of the Circular System Based tab that belong to one family tab only
        private static readonly string[] CircFloorRows = { "DlgCircHeightLbl", "DlgCircHeight" };   // floor supports: support height
        private static readonly string[] CircHangRows = { "DlgCircRodLbl", "DlgCircRod", "DlgCircSoffitLbl", "DlgCircSoffit" };   // hangers: drop rod
        private const string CircHangNote = "The hanger goes on the service's level with its reference on the centreline of the pipe, round " +
                                            "duct or round FAB duct where it hangs (so it follows a sloping pipe), turned so the service runs " +
                                            "along the axis chosen. The diameter parameter takes the service's diameter (with its insulation " +
                                            "when the hanger goes round it) and the drop rod runs from the centreline up to the level or " +
                                            "structure above. Rectangular services are skipped, and each hanger goes round one service.";

        public readonly IFhaHost O;
        public readonly FamTypeItem Item;
        public readonly FamConfig Cfg;
        public readonly bool Floor;
        public bool Ok;
        public FamConfig Result;
        public readonly Window Win;
        public readonly FhaDrawer Drawer;
        public string Style;

        public FamSettingsDialog(IFhaHost owner, FamTypeItem item, FamConfig cfg, IList<string> names, string source, string mode = "hang")
        {
            O = owner;
            Item = item;
            Cfg = cfg;
            Floor = mode == "floor";
            Ok = false;
            Result = null;
            Win = FhaUi.LoadXamlWindow("HangerFamilySettings.xaml");
            FhaUi.ApplyPalette(Win, owner.Mode);
            FhaUi.PlaceDialog(Win, owner);
            Drawer = FhaUi.DialogDrawer(Win, owner, (FrameworkElement)C("DlgHeader"), (ButtonBase)C("DlgShrinkBtn"),
                                        (UIElement)C("DlgShrinkIcon"), (UIElement)C("DlgExpandIcon"));
            T("DlgFamilyTxt").Text = item.Family + " : " + item.Type;
            T("DlgSourceTxt").Text = names != null && names.Count > 0 ? "Parameters read from " + source + "." :
                                                                          "No parameters could be read (" + (!string.IsNullOrEmpty(source) ? source : "?") + ").";
            T("DlgVerTxt").Text = "v" + FhaCore.Version;
            Fill((ComboBox)C("DlgLeft"), names, cfg.Get("left", ""));
            Fill((ComboBox)C("DlgRight"), names, cfg.Get("right", ""));
            Fill((ComboBox)C("DlgRod"), names, cfg.Get("rod", ""));
            Fill((ComboBox)C("DlgFirstBar"), names, cfg.Get("first_bar", ""));
            Fill((ComboBox)C("DlgHeight"), names, cfg.Get("height", ""));
            Fill((ComboBox)C("DlgDia"), names, cfg.Get("dia", ""));
            Fill((ComboBox)C("DlgCircHeight"), names, cfg.Get("circ_height", ""));
            Fill((ComboBox)C("DlgCircRod"), names, cfg.Get("rod", ""));
            FillPairs((ComboBox)C("DlgCircAxis"), HfamCore.RunAxes, cfg.Get("circ_axis", "X"));
            FillPairs((ComboBox)C("DlgCircSoffit"), HfamCore.Soffits, cfg.Get("soffit", "level"));
            Style = cfg.Get("style", "rect");
            ((TextBox)C("DlgHeightClear")).Text = cfg.Get("height_clear", "0");
            foreach (string n in Floor ? HangRows : FloorRows) ((UIElement)C(n)).Visibility = Visibility.Collapsed;
            // both tabs: Rectangular (Floor Based / Hanger System) and Circular System Based
            ((UIElement)C("DlgStyleTabs")).Visibility = Visibility.Visible;
            ((ButtonBase)C("DlgTabRect")).Click += (s, e) => ShowStyle("rect");
            ((ButtonBase)C("DlgTabCirc")).Click += (s, e) => ShowStyle("circ");
            foreach (string n in !Floor ? CircFloorRows : CircHangRows) ((UIElement)C(n)).Visibility = Visibility.Collapsed;
            if (!Floor)
            {
                T("DlgTabRectTxt").Text = "Rectangular Hanger System";
                ((FrameworkElement)C("DlgTabRect")).ToolTip = "A bearer under the service, stretched to its width, on drop rods";
                ((FrameworkElement)C("DlgTabCirc")).ToolTip = "A ring round a pipe or round duct, hung on a drop rod";
                T("DlgCircNoteTxt").Text = CircHangNote;
            }
            ShowStyle(Style);
            if (Floor)
            {
                T("DlgTitleTxt").Text = "Floor support family settings";
                T("DlgNoteTxt").Text = "The support stands on the service's level. The first bar offset is set to the " +
                                       "service invert above that level and the support height to the service's depth " +
                                       "(both with insulation when the support goes round it), plus the clearance above. " +
                                       "Each width parameter is half the service width plus the clearance.";
            }
            FillPairs((ComboBox)C("DlgAxis"), HfamCore.Axes, cfg.Get("axis", "X"));
            FillPairs((ComboBox)C("DlgSoffit"), HfamCore.Soffits, cfg.Get("soffit", "level"));
            ((TextBox)C("DlgClear")).Text = cfg.Get("clearance", "0");
            ((ToggleButton)C("DlgSwap")).IsChecked = cfg.Get("swap", "0") == "1";
            ((ButtonBase)C("DlgSave")).Click += Save;
            ((ButtonBase)C("DlgCancel")).Click += Cancel;
            ((ButtonBase)C("DlgCloseBtn")).Click += Cancel;
            ((UIElement)C("DlgHeader")).MouseLeftButtonDown += Drag;
        }

        public object C(string name)
        {
            return Win.FindName(name);
        }

        private TextBlock T(string name)
        {
            return (TextBlock)C(name);
        }

        /// <summary>Rectangular Floor Based / Circular System Based: the tab showing is the style the family is saved as.</summary>
        public void ShowStyle(string style)
        {
            Style = style == "rect" || style == "circ" ? style : "rect";
            bool circ = Style == "circ";
            ((UIElement)C("DlgRectPanel")).Visibility = circ ? Visibility.Collapsed : Visibility.Visible;
            ((UIElement)C("DlgCircPanel")).Visibility = circ ? Visibility.Visible : Visibility.Collapsed;
            FhaUi.SetStyle((FrameworkElement)C("DlgTabRect"), circ ? "Tab" : "TabActive");
            FhaUi.SetStyle((FrameworkElement)C("DlgTabCirc"), circ ? "TabActive" : "Tab");
        }

        private static void Fill(ComboBox combo, IEnumerable<string> names, string value)
        {
            var items = new List<string> { FamTab.NoneLabel };
            if (names != null) items.AddRange(names);
            if (value.Length > 0 && !items.Contains(value)) items.Add(value);
            foreach (string n in items) combo.Items.Add(n);
            int i = items.IndexOf(value);
            combo.SelectedIndex = i >= 0 ? i : 0;
        }

        private static void FillPairs(ComboBox combo, IList<KeyValuePair<string, string>> pairs, string value)
        {
            List<string> keys = pairs.Select(p => p.Key).ToList();
            foreach (KeyValuePair<string, string> p in pairs) combo.Items.Add(p.Value);
            int i = keys.IndexOf(value);
            combo.SelectedIndex = i >= 0 ? i : 0;
        }

        private static string Value(ComboBox combo)
        {
            string v = Convert.ToString(combo.SelectedItem) ?? "";
            return v == FamTab.NoneLabel ? "" : v;
        }

        private void Drag(object sender, MouseButtonEventArgs e)
        {
            try
            {
                Win.DragMove();
            }
            catch (Exception)
            {
            }
        }

        private void Save(object sender, RoutedEventArgs e)
        {
            // a circular hanger keeps its drop rod rows on its own tab
            bool circHang = Style == "circ" && !Floor;
            string rodBox = circHang ? "DlgCircRod" : "DlgRod";
            string soffitBox = circHang ? "DlgCircSoffit" : "DlgSoffit";
            try
            {
                Result = new FamConfig
                {
                    Left = Value((ComboBox)C("DlgLeft")),
                    Right = Value((ComboBox)C("DlgRight")),
                    Rod = Value((ComboBox)C(rodBox)),
                    Axis = HfamCore.Axes[Math.Max(0, ((ComboBox)C("DlgAxis")).SelectedIndex)].Key,
                    Soffit = HfamCore.Soffits[Math.Max(0, ((ComboBox)C(soffitBox)).SelectedIndex)].Key,
                    Clearance = FhaCore.NumText(FhaCore.ParseMm(((TextBox)C("DlgClear")).Text, 0.0)),
                    Swap = ((ToggleButton)C("DlgSwap")).IsChecked == true ? "1" : "0",
                    FirstBar = Value((ComboBox)C("DlgFirstBar")),
                    Height = Value((ComboBox)C("DlgHeight")),
                    HeightClear = FhaCore.NumText(FhaCore.ParseMm(((TextBox)C("DlgHeightClear")).Text, 0.0)),
                    Style = Style,
                    Dia = Value((ComboBox)C("DlgDia")),
                    CircHeight = Value((ComboBox)C("DlgCircHeight")),
                    CircAxis = HfamCore.RunAxes[Math.Max(0, ((ComboBox)C("DlgCircAxis")).SelectedIndex)].Key,
                };
                Ok = true;
            }
            catch (Exception)
            {
                Ok = false;
            }
            Win.Close();
        }

        private void Cancel(object sender, RoutedEventArgs e)
        {
            Win.Close();
        }

        public bool Show()
        {
            Win.ShowDialog();
            return Ok;
        }
    }
}
