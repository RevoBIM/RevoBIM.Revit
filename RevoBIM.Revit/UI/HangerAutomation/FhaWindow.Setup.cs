using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Threading;
using RevoBIM.Tools.HangerAutomation;
using ExternalEvent = Autodesk.Revit.UI.ExternalEvent;
using UIApplication = Autodesk.Revit.UI.UIApplication;

namespace RevoBIM.UI.HangerAutomation
{
    public sealed partial class FhaWindow
    {
        // ---- population
        private void FillLists()
        {
            var labels = new List<string>();
            var dims = DimTypeNames ?? new List<string>();
            try
            {
                Autodesk.Revit.DB.Document doc = UiApp.ActiveUIDocument.Document;
                labels = FhaRevit.HangerButtonLabels(doc);
            }
            catch (Exception)
            {
            }
            var cb = C<ComboBox>("CmbButton");
            cb.Items.Add("(automatic - matches the duct size)");
            foreach (string n in labels) cb.Items.Add(n);
            var cd = C<ComboBox>("CmbDimType");
            cd.Items.Add("(default dimension type)");
            foreach (string n in dims) cd.Items.Add(n);
            var cs = C<ComboBox>("CmbScope");
            cs.Items.Add("Selected run only");
            cs.Items.Add("Whole connected system");
            nButtons = labels.Count;
        }

        private void LoadControls()
        {
            FhaSettings s = Settings;
            foreach (string[] c in Checks) C<ToggleButton>(c[0]).IsChecked = FhaCore.AsBool(s, c[1]);
            C<TextBox>("TxtRadius").Text = Sget(s, "search_radius", "1500");
            C<TextBox>("TxtSpacing").Text = Sget(s, "spacing", "2000");
            Select(C<ComboBox>("CmbButton"), Sget(s, "button", ""));
            Select(C<ComboBox>("CmbDimType"), Sget(s, "dim_type", ""));
            C<ComboBox>("CmbScope").SelectedIndex = Sget(s, "scope", "run") == "system" ? 1 : 0;
            wsValues = FhaUi.FillWorksetCombo(C<ComboBox>("CmbWorkset"), Worksets, Sget(s, "workset", ""));
            if (nButtons == 0) C<TextBlock>("StatusTxt").Text = "No hanger buttons found in the loaded fabrication services";
        }

        private static void Select(ComboBox combo, string value)
        {
            for (int i = 0; i < combo.Items.Count; i++)
            {
                if (value.Length > 0 && (combo.Items[i] as string) == value)
                {
                    combo.SelectedIndex = i;
                    return;
                }
            }
            combo.SelectedIndex = 0;
        }

        private FhaSettings Gather()
        {
            var s = new FhaSettings(Settings);
            foreach (string[] c in Checks) s[c[1]] = C<ToggleButton>(c[0]).IsChecked == true ? "1" : "0";
            s["search_radius"] = FhaCore.NumText(FhaCore.ParseMm(C<TextBox>("TxtRadius").Text, 1500.0));
            s["spacing"] = FhaCore.NumText(Math.Max(100.0, FhaCore.ParseMm(C<TextBox>("TxtSpacing").Text, 2000.0)));
            var cb = C<ComboBox>("CmbButton");
            s["button"] = cb.SelectedIndex <= 0 ? "" : Convert.ToString(cb.SelectedItem);
            var cd = C<ComboBox>("CmbDimType");
            s["dim_type"] = cd.SelectedIndex <= 0 ? "" : Convert.ToString(cd.SelectedItem);
            s["scope"] = C<ComboBox>("CmbScope").SelectedIndex == 1 ? "system" : "run";
            if (wsValues.Count > 0) s["workset"] = FhaCore.WorksetValue(wsValues, C<ComboBox>("CmbWorkset").SelectedIndex);
            s["theme"] = Mode;
            s["active_tab"] = Tab;
            foreach (FamTab t in FamTabs()) t.Gather(s);
            if (Svc != null) Svc.Gather(s);
            return s;
        }

        /// <summary>The family tabs (Family Hangers, Family Floor Support).</summary>
        public List<FamTab> FamTabs()
        {
            var o = new List<FamTab>();
            if (Fam != null) o.Add(Fam);
            if (Flr != null) o.Add(Flr);
            return o;
        }

        /// <summary>One tab saved a family's settings: the other re-reads the file.</summary>
        public void FamilySettingsSaved(FamTab by)
        {
            foreach (FamTab t in FamTabs())
                if (!ReferenceEquals(t, by)) t.ReloadFamilies();
        }

        /// <summary>Python _save: gather every control, keep it, write the settings file.</summary>
        public void Save()
        {
            try
            {
                Settings = Gather();
                FhaCore.SaveSettings(Settings);
            }
            catch (Exception)
            {
            }
        }

        // ---- theme
        private void Theme()
        {
            string name = FhaUi.ApplyPalette(Win, Mode);
            ThemeName = name;
            string label = Mode == "auto" ? "Auto (" + name + ")" : Mode == "dark" ? "Dark" : "Light";
            ((ContentControl)C("ThemeBtn")).Content = label;
        }

        private void CycleTheme(object sender, RoutedEventArgs e)
        {
            try
            {
                Mode = FhaCore.NextMode(Mode);
                Theme();
                Save();
            }
            catch (Exception)
            {
            }
        }

        // ---- wiring (every handler guards itself: WPF swallows exceptions)
        private void Wire()
        {
            ((UIElement)C("HeaderBar")).MouseLeftButtonDown += HeaderDown;
            ((ButtonBase)C("ThemeBtn")).Click += CycleTheme;
            ((ButtonBase)C("FullBtn")).Click += FullClick;
            ((ButtonBase)C("ShrinkBtn")).Click += ShrinkClick;
            ((ButtonBase)C("CloseBtn")).Click += CloseClick;
            ((ButtonBase)C("BtnClose")).Click += CloseClick;
            ((ButtonBase)C("BtnCopyDebug")).Click += CopyDebug;
            ((ButtonBase)C("BtnInspectLock")).Click += InspectLockClick;
            ((ButtonBase)C("BtnRehost")).Click += RehostClick;
            ((ButtonBase)C("BtnExtend")).Click += ExtendClick;
            ((ButtonBase)C("BtnPlace")).Click += PlaceClick;
            ((ButtonBase)C("BtnRodCatsFab")).Click += RodCatsClick;
            ((ButtonBase)C("BtnFinish")).Click += FinishClick;
            FhaFinish.Listener = finishListener;
            ((ButtonBase)C("TabFab")).Click += TabFabClick;
            ((ButtonBase)C("TabFam")).Click += TabFamClick;
            ((ButtonBase)C("TabFloor")).Click += TabFloorClick;
            ((ButtonBase)C("TabSvc")).Click += TabSvcClick;
            Win.KeyDown += Key;
            Win.ContentRendered += ContentRendered;
            Win.Closed += Closed;
        }

        // ---- tabs
        private void ShowTab(string name)
        {
            Tab = TabRow(name) != null ? name : "fab";
            ApplyTab();
            Fit(false);
            if (Tab == "svc" && Svc != null) Svc.Shown();   // reads the hangers the first time
            if (built) Save();   // the open tab is remembered for next time
        }

        private void ApplyTab()
        {
            foreach (string[] t in Tabs)
            {
                bool on = t[0] == Tab;
                ((UIElement)C(t[2])).Visibility = on ? Visibility.Visible : Visibility.Collapsed;
                FhaUi.SetStyle((FrameworkElement)C(t[1]), on ? "TabActive" : "Tab");
            }
        }

        // ---- shrink to the taskbar (drawer)
        /// <summary>Everything below the title bar, collapsed while shrunk.</summary>
        private IEnumerable<UIElement> BodyParts()
        {
            var names = new List<string> { "TabsBar", "LogBox", "FinishCard", "FooterBar" };
            names.AddRange(Tabs.Select(t => t[2]));
            return names.Select(n => (UIElement)C(n)).ToList();
        }

        private void ShowBody()
        {
            foreach (string n in new[] { "TabsBar", "LogBox", "FooterBar" }) ((UIElement)C(n)).Visibility = Visibility.Visible;
            ApplyTab();
            // the Finish Selection card: back only if the window's saved height already holds it (SyncFinish does the rest once landed)
            if (finishReq != null && finishGrew > 0.0) ((UIElement)C("FinishCard")).Visibility = Visibility.Visible;
        }

        private void ShrinkClick(object sender, RoutedEventArgs e)
        {
            Drawer.Toggle();
        }

        /// <summary>
        /// A tool is opening or folding by <paramref name="delta"/>: slide the window with it so its bottom stays at
        /// the lowest tool - never taller than the screen allows (the tab scrolls then), never shorter than the minimum.
        /// </summary>
        public void ResizeForFold(double delta)
        {
            try
            {
                Window win = Win;
                string[] row = TabRow(Tab) ?? TabRow("fam");
                var sc = (ScrollViewer)C(row[2]);
                if (Chrome.Full || win.ActualHeight <= 0 || Drawer.Shrunk || Drawer.Moving) return;
                double now = foldContent != null ? foldContent.Value : ((FrameworkElement)sc.Content).ActualHeight;
                foldContent = now + delta;
                double have = sc.ViewportHeight != 0.0 ? sc.ViewportHeight : sc.ActualHeight;
                Rect wa = Chrome.WorkArea();
                double h, top;
                FhaCore.FitHeight(win.ActualHeight, have, foldContent.Value, win.MinHeight, win.Top, wa.Top,
                                  wa.Height * FhaUi.MaxScreen, out h, out top);
                if (Math.Abs(top - win.Top) > 0.5) win.Top = top;
                FhaUi.AnimateHeight(win, h, FoldResized);
            }
            catch (Exception)
            {
                foldContent = null;
            }
        }

        private void FoldResized()
        {
            foldContent = null;
        }

        /// <summary>Grow or shrink the window to show every tool on the open tab.</summary>
        public void Fit(bool growOnly)
        {
            if (Drawer != null && (Drawer.Shrunk || Drawer.Moving)) return;
            string[] row = TabRow(Tab) ?? TabRow("fab");
            Chrome.FitTo((ScrollViewer)C(row[2]), growOnly);
        }

        private void ContentRendered(object sender, EventArgs e)
        {
            Fit(false);
            // the window is on screen: now read the chosen families' previews (they were left out of the open to make it quicker)
            try
            {
                foreach (FamTab t in FamTabs()) t.OpenDoc = null;
                if (!Busy) (Tab == "floor" ? Flr : Fam).RetryPreview();
            }
            catch (Exception)
            {
            }
        }
    }
}
