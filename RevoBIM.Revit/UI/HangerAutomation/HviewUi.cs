using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using RevoBIM.Tools.HangerAutomation;

namespace RevoBIM.UI.HangerAutomation
{
    // Hanger Automation - prompts and the Dimension views picker. Port of hview_ui.py.
    //
    // Used by the Auto place tools when Dimension each run is ticked but the active view cannot take dimensions
    // (a 3D view): ask to skip or choose views, a picker with Sheets and Views tabs (house search, ticks,
    // highlight-and-tick), then after the run an offer to open the views or sheets that got dimensions.
    //
    // The jobs reach this through settings.Prompts (a DimViewsUI), so the Revit-side code never imports WPF.
    // Every window here carries a shrink drawer. Dialogs are modal (ShowDialog).

    /// <summary>One button of a Prompt: the key returned when pressed (null for "No thanks"), its label, whether it is the primary one.</summary>
    public sealed class PromptButton
    {
        public readonly string Key;
        public readonly string Label;
        public readonly bool Primary;

        public PromptButton(string key, string label, bool primary)
        {
            Key = key;
            Label = label;
            Primary = primary;
        }
    }

    // ===================================================================== prompt
    /// <summary>A themed question with buttons; Show() returns the key of the one pressed (null when closed with the X).</summary>
    public sealed class Prompt
    {
        public readonly IFhaHost O;
        public string Answer;
        public readonly Window Win;
        public readonly FhaDrawer Drawer;
        public readonly List<KeyValuePair<string, Button>> Buttons = new List<KeyValuePair<string, Button>>();

        public Prompt(IFhaHost owner, string title, string heading, string text, IEnumerable<PromptButton> buttons)
        {
            O = owner;
            Answer = null;
            Win = FhaUi.LoadXamlWindow("HangerPrompt.xaml");
            FhaUi.ApplyPalette(Win, owner != null ? owner.Mode : "auto");
            FhaUi.PlaceDialog(Win, owner);
            Drawer = FhaUi.DialogDrawer(Win, owner, (FrameworkElement)C("PromptHeader"), (ButtonBase)C("PromptShrinkBtn"),
                                        (UIElement)C("PromptShrinkIcon"), (UIElement)C("PromptExpandIcon"));
            ((TextBlock)C("PromptVerTxt")).Text = "v" + FhaCore.Version;
            ((TextBlock)C("PromptTitleTxt")).Text = title;
            ((TextBlock)C("PromptHeading")).Text = heading;
            ((TextBlock)C("PromptText")).Text = text;
            foreach (PromptButton pb in buttons)
            {
                var b = new Button();
                b.Content = pb.Label;
                b.Margin = FhaUi.MakeThickness(8, 0, 0, 0);
                if (pb.Primary) FhaUi.SetStyle(b, "Primary");
                b.Click += Clicker(pb.Key);
                ((Panel)C("PromptButtons")).Children.Add(b);
                Buttons.Add(new KeyValuePair<string, Button>(pb.Key, b));
            }
            ((ButtonBase)C("PromptCloseBtn")).Click += Close;
            ((UIElement)C("PromptHeader")).MouseLeftButtonDown += Drag;
        }

        public object C(string name)
        {
            return Win.FindName(name);
        }

        private RoutedEventHandler Clicker(string key)
        {
            return (sender, e) =>
            {
                Answer = key;
                Win.Close();
            };
        }

        private void Close(object sender, RoutedEventArgs e)
        {
            Answer = null;
            Win.Close();
        }

        private void Drag(object sender, System.Windows.Input.MouseButtonEventArgs e)
        {
            try
            {
                Win.DragMove();
            }
            catch (Exception)
            {
            }
        }

        public string Show()
        {
            Win.ShowDialog();
            return Answer;
        }
    }

    // ============================================================== view picker
    /// <summary>
    /// Sheets and Views tabs. rows: the plan / section views; sheets: the sheets carrying them. Show() returns the
    /// ticked views and sheets on Apply, null on Skip / close.
    /// </summary>
    public sealed class DimViewsDialog
    {
        private sealed class Box<T>
        {
            public readonly T Row;
            public readonly CheckBox Check;

            public Box(T row, CheckBox check)
            {
                Row = row;
                Check = check;
            }
        }

        public readonly IFhaHost O;
        public readonly List<ViewRow> Rows;
        public readonly List<SheetRow> Sheets;
        public DimChoice Result;
        private bool suspend;
        public string Tab;
        public readonly Window Win;
        public readonly FhaDrawer Drawer;
        // one CheckBox per row, kept for the life of the dialog so ticks survive searches
        private readonly List<Box<ViewRow>> viewBoxes;
        private readonly List<Box<SheetRow>> sheetBoxes;

        public DimViewsDialog(IFhaHost owner, IEnumerable<ViewRow> rows, IEnumerable<SheetRow> sheets, string intro = null)
        {
            O = owner;
            Rows = new List<ViewRow>(rows);
            Sheets = new List<SheetRow>(sheets);
            Result = null;
            suspend = false;
            Tab = "views";      // Views first, filtered to floor plans
            Win = FhaUi.LoadXamlWindow("HangerDimViews.xaml");
            FhaUi.ApplyPalette(Win, owner != null ? owner.Mode : "auto");
            FhaUi.PlaceDialog(Win, owner);
            Drawer = FhaUi.DialogDrawer(Win, owner, (FrameworkElement)C("DvHeader"), (ButtonBase)C("DvShrinkBtn"),
                                        (UIElement)C("DvShrinkIcon"), (UIElement)C("DvExpandIcon"));
            ((TextBlock)C("DvVerTxt")).Text = "v" + FhaCore.Version;
            if (!string.IsNullOrEmpty(intro)) ((TextBlock)C("DvIntroTxt")).Text = intro;
            // sorted by (not a plan type, natural name); OrderBy is stable, like the Python sort
            viewBoxes = Rows.OrderBy(r => Array.IndexOf(FhaCore.PlanViewTypes, r.Type) < 0)
                            .ThenBy(r => r.Name, FhaCore.NaturalComparer.Instance)
                            .Select(r => new Box<ViewRow>(r, MakeBox(FhaCore.ViewRowText(r)))).ToList();
            sheetBoxes = Sheets.OrderBy(r => r.Number, FhaCore.NaturalComparer.Instance)
                               .Select(r => new Box<SheetRow>(r, MakeBox(FhaCore.SheetRowText(r)))).ToList();
            ((TextBox)C("TxtSheetsSearch")).Text = "";
            ((TextBox)C("TxtViewsSearch")).Text = "";
            var kinds = (ComboBox)C("CmbViewsKind");
            foreach (KeyValuePair<string, string> kv in FhaCore.ViewKinds) kinds.Items.Add(kv.Value);
            kinds.SelectedIndex = 0;   // Floor plans
            ((TextBlock)C("TabDvSheetsTxt")).Text = "Sheets (" + Sheets.Count + ")";
            ((TextBlock)C("TabDvViewsTxt")).Text = "Views (" + Rows.Count + ")";
            Wire();
            Refill();
            ShowTab(Tab);
        }

        public object C(string name)
        {
            return Win.FindName(name);
        }

        private CheckBox MakeBox(string text)
        {
            var b = new CheckBox();
            b.Content = text;
            b.IsChecked = false;      // set before the handlers (a start value is not a tick)
            b.Checked += Ticked;
            b.Unchecked += Ticked;
            return b;
        }

        private void Wire()
        {
            ((ButtonBase)C("TabDvSheets")).Click += (s, e) => ShowTab("sheets");
            ((ButtonBase)C("TabDvViews")).Click += (s, e) => ShowTab("views");
            ((TextBoxBase)C("TxtSheetsSearch")).TextChanged += (s, e) => Refill();
            ((TextBoxBase)C("TxtViewsSearch")).TextChanged += (s, e) => Refill();
            ((Selector)C("CmbViewsKind")).SelectionChanged += (s, e) => Refill();
            ((ButtonBase)C("BtnSheetsTickShown")).Click += (s, e) => TickShown("Sheets", true);
            ((ButtonBase)C("BtnSheetsUntickShown")).Click += (s, e) => TickShown("Sheets", false);
            ((ButtonBase)C("BtnViewsTickShown")).Click += (s, e) => TickShown("Views", true);
            ((ButtonBase)C("BtnViewsUntickShown")).Click += (s, e) => TickShown("Views", false);
            ((ButtonBase)C("DvApply")).Click += Apply;
            ((ButtonBase)C("DvSkip")).Click += Skip;
            ((ButtonBase)C("DvCloseBtn")).Click += Skip;
            ((UIElement)C("DvHeader")).MouseLeftButtonDown += Drag;
        }

        // ---- tabs and lists
        public void ShowTab(string name)
        {
            Tab = name == "sheets" || name == "views" ? name : "sheets";
            bool sheets = Tab == "sheets";
            ((UIElement)C("SheetsPanel")).Visibility = sheets ? Visibility.Visible : Visibility.Collapsed;
            ((UIElement)C("ViewsPanel")).Visibility = sheets ? Visibility.Collapsed : Visibility.Visible;
            FhaUi.SetStyle((FrameworkElement)C("TabDvSheets"), sheets ? "TabActive" : "Tab");
            FhaUi.SetStyle((FrameworkElement)C("TabDvViews"), sheets ? "Tab" : "TabActive");
        }

        /// <summary>The check boxes the search (and kind filter) leave showing, in list order.</summary>
        private List<CheckBox> Shown(string which)
        {
            if (which == "Sheets")
            {
                var keep = new HashSet<SheetRow>(FhaCore.FilterSheetRows(Sheets, ((TextBox)C("TxtSheetsSearch")).Text ?? ""));
                return sheetBoxes.Where(b => keep.Contains(b.Row)).Select(b => b.Check).ToList();
            }
            int i = ((ComboBox)C("CmbViewsKind")).SelectedIndex;
            string kind = i >= 0 && i < FhaCore.ViewKinds.Count ? FhaCore.ViewKinds[i].Key : "floor";
            var keepViews = new HashSet<ViewRow>(FhaCore.FilterViewRows(Rows, ((TextBox)C("TxtViewsSearch")).Text ?? "", kind));
            return viewBoxes.Where(b => keepViews.Contains(b.Row)).Select(b => b.Check).ToList();
        }

        public void Refill()
        {
            foreach (string which in new[] { "Sheets", "Views" })
            {
                var lst = (ListBox)C("Lst" + which);
                lst.Items.Clear();
                foreach (CheckBox b in Shown(which)) lst.Items.Add(b);
            }
            Count();
        }

        public void TickShown(string which, bool on)
        {
            suspend = true;
            try
            {
                foreach (CheckBox b in Shown(which)) b.IsChecked = on;
            }
            finally
            {
                suspend = false;
            }
            Count();
        }

        /// <summary>Ticking a highlighted row ticks every highlighted row (house rule).</summary>
        private void Ticked(object sender, RoutedEventArgs e)
        {
            if (suspend) return;
            suspend = true;
            try
            {
                foreach (string which in new[] { "Sheets", "Views" })
                {
                    var lst = (ListBox)C("Lst" + which);
                    var sel = new List<object>();
                    if (lst.SelectedItems != null)
                        foreach (object x in lst.SelectedItems) sel.Add(x);
                    if (sel.Any(x => ReferenceEquals(x, sender)))
                    {
                        foreach (object x in sel) ((CheckBox)x).IsChecked = ((CheckBox)sender).IsChecked;
                    }
                }
            }
            catch (Exception)
            {
            }
            finally
            {
                suspend = false;
            }
            Count();
        }

        /// <summary>The ticked view keys and sheet keys.</summary>
        public void Picked(out List<long> views, out List<long> sheets)
        {
            views = viewBoxes.Where(b => b.Check.IsChecked == true).Select(b => b.Row.Key).ToList();
            sheets = sheetBoxes.Where(b => b.Check.IsChecked == true).Select(b => b.Row.Key).ToList();
        }

        public void Count()
        {
            List<long> views, sheets;
            Picked(out views, out sheets);
            List<long> total = FhaCore.ChosenViews(views, sheets, Sheets);
            try
            {
                ((TextBlock)C("SheetsCountTxt")).Text = sheets.Count + " of " + Sheets.Count + " ticked";
                ((TextBlock)C("ViewsCountTxt")).Text = views.Count + " of " + Rows.Count + " ticked";
                if (total.Count > 0)
                {
                    ((TextBlock)C("DvStatusTxt")).Text = sheets.Count + " sheet" + (sheets.Count == 1 ? "" : "s") + " and " +
                        views.Count + " view" + (views.Count == 1 ? "" : "s") + " ticked - dimensions go in " +
                        total.Count + " view" + (total.Count == 1 ? "" : "s");
                }
                else
                {
                    ((TextBlock)C("DvStatusTxt")).Text = "Nothing ticked - tick sheets or views, or Skip dimensions";
                }
                ((UIElement)C("DvApply")).IsEnabled = total.Count > 0;
            }
            catch (Exception)
            {
            }
        }

        // ---- close
        private void Apply(object sender, RoutedEventArgs e)
        {
            List<long> views, sheets;
            Picked(out views, out sheets);
            if (FhaCore.ChosenViews(views, sheets, Sheets).Count == 0) return;
            Result = new DimChoice { Views = views, Sheets = sheets };
            Win.Close();
        }

        private void Skip(object sender, RoutedEventArgs e)
        {
            Result = null;
            Win.Close();
        }

        private void Drag(object sender, System.Windows.Input.MouseButtonEventArgs e)
        {
            try
            {
                Win.DragMove();
            }
            catch (Exception)
            {
            }
        }

        public DimChoice Show()
        {
            Win.ShowDialog();
            return Result;
        }
    }

    // ================================================================ for jobs
    /// <summary>
    /// Handed to the jobs as settings.Prompts by the window: every question a job asks mid-run (dimension views,
    /// the floor support base, opening views).
    /// </summary>
    public sealed class DimViewsUI : IFhaPrompts
    {
        public readonly IFhaHost O;

        public DimViewsUI(IFhaHost owner)
        {
            O = owner;
        }

        /// <summary>null to skip, else the ticked views and sheets.</summary>
        public DimChoice ChooseDimViews(string viewName, List<ViewRow> rows, List<SheetRow> sheets)
        {
            if (rows == null || rows.Count == 0)
            {
                new Prompt(O, "Dimension views", "No plan or section views to dimension in",
                           "Dimension each run is ticked, but this model has no floor plans or sections. " +
                           "The hangers will be placed without dimensions.",
                           new[] { new PromptButton("ok", "OK", true) }).Show();
                return null;
            }
            string ans = new Prompt(O, "Dimension views", "Where should the run dimensions go?",
                                    "Dimension each run is ticked, but \"" + viewName + "\" is a 3D view - dimensions go in floor plans and " +
                                    "sections. Choose the sheets or views to put them in, or carry on without them.",
                                    new[]
                                    {
                                        new PromptButton("skip", "No - skip dimension placement", false),
                                        new PromptButton("choose", "Choose views...", true),
                                    }).Show();
            if (ans != "choose") return null;
            return new DimViewsDialog(O, rows, sheets ?? new List<SheetRow>()).Show();
        }

        /// <summary>
        /// Floor supports standing on a picked element: say what to click next. "pick" or "level" (the X stands them
        /// on the level too).
        /// </summary>
        public string AskBasePick(bool linked)
        {
            string where = linked ? "in the linked model " : "";
            return new Prompt(O, "Floor support base", "Now click the floor, roof or equipment the supports stand on",
                              "After you press Pick it, click it in Revit " + where + "- the status bar at the bottom left says what to " +
                              "click. " + (!linked ? "Click the link first, then the element inside it. " : "") +
                              "Each support is lifted onto its top surface and stays hosted on its level. " +
                              "Esc in Revit stands them on the level instead.",
                              new[]
                              {
                                  new PromptButton("level", "Stand on the level", false),
                                  new PromptButton("pick", "Pick it in Revit", true),
                              }).Show();
        }

        /// <summary>After the run: "sheets", "views" or null. views / sheets: names.</summary>
        public string AskOpen(int nRuns, List<string> views, List<string> sheets)
        {
            views = views ?? new List<string>();
            sheets = sheets ?? new List<string>();
            var buttons = new List<PromptButton> { new PromptButton(null, "No thanks", false) };
            if (views.Count > 0)
                buttons.Add(new PromptButton("views", "Open the " + views.Count + " view" + (views.Count == 1 ? "" : "s"), sheets.Count == 0));
            if (sheets.Count > 0)
                buttons.Add(new PromptButton("sheets", "Open the " + sheets.Count + " sheet" + (sheets.Count == 1 ? "" : "s"), true));
            List<string> source = sheets.Count > 0 ? sheets : views;
            List<string> names = source.Take(6).ToList();
            int more = source.Count - names.Count;
            return new Prompt(O, "Dimension views", "Done - " + nRuns + " run" + (nRuns == 1 ? "" : "s") + " dimensioned",
                              "Would you like to open the " + (sheets.Count > 0 ? "sheets" : "views") + " with the dimensions?\n" +
                              string.Join("\n", names) + (more > 0 ? "\n... and " + more + " more" : ""),
                              buttons).Show();
        }
    }
}
