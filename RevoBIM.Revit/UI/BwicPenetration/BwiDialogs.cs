using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.BwicPenetration;
using ComboBox = System.Windows.Controls.ComboBox;
using Visibility = System.Windows.Visibility;
using Grid = System.Windows.Controls.Grid;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.BwicPenetration
{
    /// <summary>Runs a selection on the Revit side for the modeless results window (a modeless window cannot touch the selection itself).</summary>
    internal sealed class SelectionHandler : IExternalEventHandler
    {
        public List<ElementId> Ids = new List<ElementId>();

        public void Execute(UIApplication uiapp)
        {
            try
            {
                UIDocument uidoc = uiapp.ActiveUIDocument;
                if (uidoc == null || Ids.Count == 0) return;
                var ids = new List<ElementId>(Ids);
                uidoc.Selection.SetElementIds(ids);
                try { uidoc.ShowElements(ids); } catch (Exception) { }
            }
            catch (Exception err)
            {
                BwicCore.DebugLog("could not select the flagged BWICs: " + err.Message);
            }
        }

        public string GetName() { return "RevoBIM BWIC select flagged"; }
    }

    /// <summary>What a global run did, and a way to get at anything needing a look. Modeless; only ever one.</summary>
    internal sealed class ResultsWindow : BwiWindowBase
    {
        private readonly ExternalEvent _selectEvent;
        private readonly SelectionHandler _selectHandler;
        private readonly List<ElementId> _reviewIds;

        public ResultsWindow(GlobalSummary summary, ExternalEvent selectEvent, SelectionHandler selectHandler)
        {
            _selectEvent = selectEvent;
            _selectHandler = selectHandler;
            Win = BwiUi.Load("results.xaml", new Dictionary<string, Action<object, RoutedEventArgs>>
            {
                { "select_click", G("select_click", (s, e) => SelectClick()) },
                { "shrink_click", G("shrink_click", (s, e) => Drawer.Toggle()) },
                { "drag_window", G("drag_window", HeaderDown) },
                { "close_click", G("close_click", (s, e) => Win.Close()) },
            });
            try { Find<TextBlock>("version_tb").Text = "v" + BwicCore.ToolVersion; } catch (Exception) { }
            _reviewIds = summary.ReviewIds ?? new List<ElementId>();
            Drawer = new Drawer(Win, Find<StackPanel>("header_pnl"), Find<Button>("shrink_btn"));
            Win.PreviewKeyDown += (s, e) => KeyDownDrawer(e, true);

            int review = summary.Review;
            Find<TextBlock>("placed_val").Text = summary.Placed.ToString();
            Find<TextBlock>("placed_cap").Text = "BWIC placed";
            Find<TextBlock>("review_val").Text = review.ToString();
            Find<TextBlock>("failed_val").Text = summary.Failed.ToString();

            Func<int, string, string> plural = (n, word) => n + " " + word + (n == 1 ? "" : "s");
            var detail = new List<string> { plural(summary.Groups, "group") + " across " + plural(summary.Walls, "wall") };
            if (summary.Skipped > 0) detail.Add(summary.Skipped + " already had a BWIC");
            if (summary.Duplicates > 0) detail.Add(plural(summary.Duplicates, "repeat opening") + " dropped");
            if (summary.Unmeasured > 0) detail.Add(plural(summary.Unmeasured, "service") + " not measurable at the wall");
            Find<TextBlock>("detail_tb").Text = string.Join(", ", detail) + ".";

            var warnTb = Find<TextBlock>("warn_tb");
            if (summary.Warnings != null && summary.Warnings.Count > 0)
            {
                var shown = summary.Warnings.Take(3).ToList();
                int extra = summary.Warnings.Count - shown.Count;
                warnTb.Text = "Revit messages dismissed: " + string.Join("; ", shown) + (extra > 0 ? " and " + extra + " more" : "");
            }
            else warnTb.Visibility = Visibility.Collapsed;

            var lines = new List<string>();
            if (!string.IsNullOrEmpty(summary.GroupName)) lines.Add("Overlapping BWICs are boxed in red, grouped as \"" + summary.GroupName + "\".");
            else if (review > 0) lines.Add("Overlapping BWICs were found but could not be marked in this view -- try a plan or section.");
            else lines.Add("No overlapping BWICs in this run.");
            if (!string.IsNullOrEmpty(summary.FailedGroupName)) lines.Add("Failures are boxed in amber, grouped as \"" + summary.FailedGroupName + "\".");
            Find<TextBlock>("note_tb").Text = string.Join(" ", lines);

            var selectBtn = Find<Button>("select_btn");
            if (_reviewIds.Count > 0) selectBtn.Content = "Select the " + _reviewIds.Count + " to review";
            else selectBtn.Visibility = Visibility.Collapsed;
        }

        private void SelectClick()
        {
            try
            {
                _selectHandler.Ids = _reviewIds;
                _selectEvent.Raise();
            }
            catch (Exception err)
            {
                BwicCore.DebugLog("could not raise the selection event: " + err.Message);
            }
        }

        public void Show()
        {
            BwiUi.OwnToRevit(Win);
            Win.Show();
        }
    }

    /// <summary>The settings behind the gear: wall type names, round-up figures, slab rule and the workset.</summary>
    internal sealed class SettingsWindow : BwiWindowBase
    {
        private static readonly string[][] RuleLabels =
        {
            new[] { "two_level", "Two levels (Base Level / Top Level + offsets)" },
            new[] { "single_level", "Single level (nearest level + height parameters)" },
        };

        private readonly Dictionary<string, string> _settings;
        private readonly Action<Dictionary<string, string>> _onApply;
        private List<string> _worksetNames = new List<string>();

        public SettingsWindow(Dictionary<string, string> settings, Action<Dictionary<string, string>> onApply, Drawer lift)
        {
            _settings = new Dictionary<string, string>(settings);
            _onApply = onApply;
            Win = BwiUi.Load("settings.xaml", new Dictionary<string, Action<object, RoutedEventArgs>>
            {
                { "apply_click", G("apply_click", (s, e) => ApplyClick()) },
                { "cancel_click", G("cancel_click", (s, e) => Win.Close()) },
                { "shrink_click", G("shrink_click", (s, e) => Drawer.Toggle()) },
                { "drag_window", G("drag_window", HeaderDown) },
            });
            // a dialog lifts its owner: shrinking Settings parks the tool window too
            Drawer = new Drawer(Win, Find<StackPanel>("header_pnl"), Find<Button>("shrink_btn"), null, lift);
            Win.PreviewKeyDown += (s, e) => KeyDownDrawer(e, true);
            Load();
        }

        private string Get(string key, string fallback)
        {
            string v;
            return _settings.TryGetValue(key, out v) && v != null ? v : fallback;
        }

        private void Load()
        {
            Find<TextBox>("w_round_tb").Text = Get("round_up", BwicCore.RoundUpMm.ToString("0"));
            Find<TextBox>("w_blk_tb").Text = Get("wall_type_blockwork", "BWIC - Blockwork");
            Find<TextBox>("w_fr_tb").Text = Get("wall_type_firerated", "BWIC - Fire Rated Wall");
            Find<TextBox>("s_round_tb").Text = Get("slab_round_up", "5");
            Find<TextBox>("s_heightextra_tb").Text = Get("slab_height_extra", "0");
            Find<TextBox>("s_diaround_tb").Text = Get("slab_circular_round", "10");
            Find<TextBox>("s_group_tb").Text = Get("slab_group_gap", "100");
            Find<TextBox>("s_pipegap_tb").Text = Get("slab_pipe_tray_gap", "150");
            Find<TextBox>("s_groupangle_tb").Text = Get("slab_group_angle", "15");
            Find<TextBox>("s_topheightextra_tb").Text = Get("slab_top_height_extra", "0");

            var rule = Find<ComboBox>("s_rule_cb");
            rule.Items.Clear();
            foreach (string[] r in RuleLabels) rule.Items.Add(r[1]);
            string wanted = Get("slab_rule", "two_level");
            int index = Array.FindIndex(RuleLabels, r => r[0] == wanted);
            rule.SelectedIndex = index >= 0 ? index : 0;
            rule.SelectionChanged += (s, e) => RuleChanged();
            LoadWorksets();
            RuleChanged();
        }

        /// <summary>Open to the left of the tool window, so neither covers the other; the right when there is no room.</summary>
        public void PlaceBeside(Window owner)
        {
            try
            {
                double scale = BwiUi.DpiScale(owner);
                double[] area = BwiUi.WorkingArea(scale);
                double width = !double.IsNaN(Win.Width) ? Win.Width : 470.0;
                double height = !double.IsNaN(Win.Height) ? Win.Height : 620.0;
                double left = owner.Left - width - 12;
                if (left < area[0]) left = owner.Left + owner.ActualWidth + 12;
                left = Math.Min(Math.Max(left, area[0]), area[0] + area[2] - width);
                double top = Math.Min(Math.Max(owner.Top, area[1]), area[1] + area[3] - height);
                Win.WindowStartupLocation = WindowStartupLocation.Manual;
                Win.Left = left;
                Win.Top = top;
            }
            catch (Exception) { }
        }

        private void LoadWorksets()
        {
            _worksetNames = new List<string>();
            try
            {
                Document doc = BwicCore.CurrentApp.ActiveUIDocument.Document;
                _worksetNames = BwicCore.ListWorksets(doc).Select(w => w.Name).ToList();
            }
            catch (Exception) { }
            var cb = Find<ComboBox>("s_workset_cb");
            cb.Items.Clear();
            cb.Items.Add("<active workset>");
            foreach (string name in _worksetNames) cb.Items.Add(name);
            cb.IsEnabled = _worksetNames.Count > 0;
            if (_worksetNames.Count == 0)
            {
                cb.SelectedIndex = 0;
                return;
            }
            string remembered = Get("workset", "");
            string chosen = _worksetNames.Contains(remembered) ? remembered
                : _worksetNames.FirstOrDefault(n => n.ToUpperInvariant().Contains(BwicCore.WorksetKeyword.ToUpperInvariant()));
            cb.SelectedIndex = chosen != null ? _worksetNames.IndexOf(chosen) + 1 : 0;
        }

        private string SelectedWorkset()
        {
            object value = Find<ComboBox>("s_workset_cb").SelectedItem;
            if (value == null || value.ToString().StartsWith("<")) return "";
            return value.ToString();
        }

        private string SelectedRule()
        {
            int index = Find<ComboBox>("s_rule_cb").SelectedIndex;
            return index >= 0 ? RuleLabels[index][0] : "two_level";
        }

        private void RuleChanged()
        {
            bool single = SelectedRule() == "single_level";
            Find<Border>("s_single_panel").Visibility = single ? Visibility.Visible : Visibility.Collapsed;
            Find<Border>("s_two_panel").Visibility = single ? Visibility.Collapsed : Visibility.Visible;
        }

        public override void Report(string message)
        {
            BwicCore.DebugLog("status: " + message);
            try { MessageBox.Show(message, "BWIC Penetration Settings"); } catch (Exception) { }
        }

        private string T(string name) { return Find<TextBox>(name).Text.Trim(); }

        private void ApplyClick()
        {
            var values = new Dictionary<string, string>(_settings);
            values["round_up"] = T("w_round_tb");
            values["wall_type_blockwork"] = T("w_blk_tb");
            values["wall_type_firerated"] = T("w_fr_tb");
            values["slab_rule"] = SelectedRule();
            values["slab_round_up"] = T("s_round_tb");
            values["slab_height_extra"] = T("s_heightextra_tb");
            values["slab_circular_round"] = T("s_diaround_tb");
            values["slab_group_gap"] = T("s_group_tb");
            values["slab_pipe_tray_gap"] = T("s_pipegap_tb");
            values["slab_group_angle"] = T("s_groupangle_tb");
            values["workset"] = SelectedWorkset();
            values["slab_top_height_extra"] = T("s_topheightextra_tb");
            BwicCore.WriteSettings(values);
            BwicCore.ApplySettings(values);
            _onApply(values);
            Win.Close();
        }
    }

    /// <summary>
    /// How one family sizes itself: its shape, and which of its parameters the tool writes each size and position to. The rows come from
    /// BwicFamilies.Roles, so the dialog can only offer a role the placement code knows how to fill.
    /// </summary>
    internal sealed class FamilySettingsWindow : BwiWindowBase
    {
        private static readonly string[] SizeRoles = { "through", "across", "height", "diameter", "plan_x", "plan_y" };

        private readonly string _slot, _family;
        private readonly List<string> _lengthNames, _allNames;
        private readonly Action<string, string, Dictionary<string, object>> _onSave;
        private Dictionary<string, object> _profile;
        private Dictionary<string, string> _worksets;
        private readonly Dictionary<string, ComboBox> _combos = new Dictionary<string, ComboBox>();
        private readonly Dictionary<string, ComboBox> _splitCombos = new Dictionary<string, ComboBox>();
        private readonly Dictionary<string, UIElement[]> _roleRows = new Dictionary<string, UIElement[]>();
        private List<string> _worksetValues = new List<string>();
        private string _worksetDrive;

        public FamilySettingsWindow(string slot, string family, Dictionary<string, object> profile, List<string> lengthNames, List<string> allNames,
                                    bool placed, System.Windows.Media.ImageSource preview, Drawer lift,
                                    Action<string, string, Dictionary<string, object>> onSave, List<string> worksets, string settingsWorkset)
        {
            _slot = slot;
            _family = family;
            _lengthNames = new List<string>(lengthNames);
            _allNames = new List<string>(allNames);
            _onSave = onSave;
            Win = BwiUi.Load("family_settings.xaml", new Dictionary<string, Action<object, RoutedEventArgs>>
            {
                { "cancel_click", G("cancel_click", (s, e) => Win.Close()) },
                { "save_click", G("save_click", (s, e) => { _onSave(_slot, _family, Gather()); Win.Close(); }) },
                { "shrink_click", G("shrink_click", (s, e) => Drawer.Toggle()) },
                { "suggest_click", G("suggest_click", (s, e) => SuggestClick()) },
                { "drag_window", G("drag_window", HeaderDown) },
            });

            string shapeText = BwicFamilies.Str(profile, "shape");
            var split = new Dictionary<string, object>();
            var srcSplit = BwicFamilies.Sub(profile, "split");
            if (srcSplit != null)
                foreach (var kv in srcSplit)
                {
                    var pair = kv.Value as Dictionary<string, object>;
                    split[kv.Key] = pair != null ? new Dictionary<string, object>(pair) : new Dictionary<string, object>();
                }
            var srcRoles = BwicFamilies.Sub(profile, "roles");
            string drive = BwicFamilies.Str(profile, "drive");
            _profile = new Dictionary<string, object>
            {
                { "shape", shapeText.Length > 0 ? shapeText : BwicFamilies.DefaultShape(slot) },
                { "radius", BwicFamilies.Bool(profile, "radius") },
                { "roles", srcRoles != null ? new Dictionary<string, object>(srcRoles) : new Dictionary<string, object>() },
                { "drive", drive.Length > 0 ? drive : BwicFamilies.Standard },
                { "split", split },
            };
            _worksets = BwicFamilies.ProfileWorksets(profile);

            Drawer = new Drawer(Win, Find<StackPanel>("header_pnl"), Find<Button>("shrink_btn"), null, lift);
            Win.PreviewKeyDown += (s, e) => KeyDownDrawer(e, true);

            Find<TextBlock>("fs_slot_tb").Text = BwicFamilies.Slots.First(x => x.Slot == slot).Label;
            Find<TextBlock>("fs_family_tb").Text = family;
            string note = placed ? "" : " Only its type parameters are visible until it has been placed once in this model -- a saved name it cannot see is kept.";
            Find<TextBlock>("fs_count_tb").Text = _lengthNames.Count + " length parameter" + (_lengthNames.Count == 1 ? "" : "s") + " found." + note;
            Find<Image>("fs_preview_img").Source = preview;
            Find<TextBlock>("fs_noprev_tb").Visibility = preview != null ? Visibility.Collapsed : Visibility.Visible;

            string[] shapes = BwicFamilies.SlotShapes[slot];
            var shapeCb = Find<ComboBox>("fs_shape_cb");
            foreach (string shape in shapes) shapeCb.Items.Add(shape == BwicFamilies.Rect ? "Rectangular" : "Round");
            int si = Array.IndexOf(shapes, (string)_profile["shape"]);
            shapeCb.SelectedIndex = si >= 0 ? si : 0;
            shapeCb.IsEnabled = shapes.Length > 1;
            var holds = Find<ComboBox>("fs_holds_cb");
            holds.Items.Add("Diameter");
            holds.Items.Add("Radius");
            holds.SelectedIndex = (bool)_profile["radius"] ? 1 : 0;
            Find<StackPanel>("fs_position_pnl").Visibility = slot.StartsWith("slab") ? Visibility.Visible : Visibility.Collapsed;

            bool splittable = BwicFamilies.SplitAxes.ContainsKey(slot);
            string splitLabel;
            if (!BwicFamilies.SplitLabel.TryGetValue(slot, out splitLabel)) splitLabel = "X+ / X-";
            Find<TextBlock>("fs_split_tab_tb").Text = splitLabel.Replace("-", "âˆ’");
            var driveTabs = Find<TabControl>("fs_drive_tabs");
            driveTabs.Visibility = splittable ? Visibility.Visible : Visibility.Collapsed;
            driveTabs.SelectedIndex = splittable && (string)_profile["drive"] == BwicFamilies.Split ? 1 : 0;

            double? own = BwicFamilies.ClearanceValue(profile.ContainsKey("clearance_mm") ? profile["clearance_mm"] : null);
            var clearanceTb = Find<TextBox>("fs_clearance_tb");
            clearanceTb.Text = BwicFamilies.G(own ?? BwicFamilies.DefaultClearanceMm);
            Find<TextBlock>("fs_clearance_tb_hint").Text = slot == "wall_circ" || slot == "slab_circ" ? "mm each side of the pipe" : "mm each side of the services";
            clearanceTb.TextChanged += (s, e) => Check();

            _worksetDrive = SelectedDrive();
            FillWorksets(worksets, settingsWorkset);
            BuildRows();
            shapeCb.SelectionChanged += (s, e) => { _profile = Gather(); BuildRows(); };
            holds.SelectionChanged += (s, e) => Check();
            driveTabs.SelectionChanged += (s, e) =>
            {
                if (e.OriginalSource != driveTabs) return;
                KeepWorkset();
                ShowWorkset(SelectedDrive());
                ShowDrive();
                Check();
            };
        }

        // ---------------------------------------------------------------- workset

        private void FillWorksets(List<string> worksets, string settingsWorkset)
        {
            string follow = BwicFamilies.FollowLabel;
            if (!string.IsNullOrEmpty(settingsWorkset)) follow = follow + "  (" + settingsWorkset + ")";
            _worksetValues = new List<string> { BwicFamilies.FollowSettings, BwicFamilies.ActiveWorkset };
            var labels = new List<string> { follow, BwicFamilies.ActiveLabel };
            foreach (string name in worksets)
            {
                _worksetValues.Add(name);
                labels.Add(name);
            }
            foreach (string saved in _worksets.Values.Where(v => v.Length > 0).Distinct().OrderBy(v => v, StringComparer.Ordinal))
            {
                if (!_worksetValues.Contains(saved))
                {
                    _worksetValues.Add(saved);
                    labels.Add(saved + "  (not in this model)");
                }
            }
            var cb = Find<ComboBox>("fs_workset_cb");
            cb.Items.Clear();
            foreach (string label in labels) cb.Items.Add(label);
            cb.IsEnabled = worksets.Count > 0 || _worksets.Values.Any(v => v.Length > 0);
            ShowWorkset(_worksetDrive);
        }

        private void ShowWorkset(string drive)
        {
            _worksetDrive = drive;
            string current;
            if (!_worksets.TryGetValue(drive, out current) || string.IsNullOrEmpty(current)) current = BwicFamilies.FollowSettings;
            int index = _worksetValues.IndexOf(current);
            Find<ComboBox>("fs_workset_cb").SelectedIndex = index >= 0 ? index : 0;
            bool splittable = BwicFamilies.SplitAxes.ContainsKey(_slot);
            string splitLabel;
            if (!BwicFamilies.SplitLabel.TryGetValue(_slot, out splitLabel)) splitLabel = "X+ / X-";
            string tab = drive == BwicFamilies.Split ? splitLabel.Replace("-", "âˆ’") : "Standard";
            Find<TextBlock>("fs_workset_head_tb").Text = splittable ? "Workset â€“ " + tab : "Workset";
            Find<TextBlock>("fs_workset_tb").Text = splittable ? "Used when this family is set to " + tab + ". Each sub tab keeps its own." : "";
        }

        private string SelectedWorkset()
        {
            int index = Find<ComboBox>("fs_workset_cb").SelectedIndex;
            return index >= 0 && index < _worksetValues.Count ? _worksetValues[index] : BwicFamilies.FollowSettings;
        }

        private void KeepWorkset() { _worksets[_worksetDrive] = SelectedWorkset(); }

        private Dictionary<string, object> GatheredWorksets()
        {
            KeepWorkset();
            var result = new Dictionary<string, object>();
            foreach (var kv in _worksets) result[kv.Key] = kv.Value;
            return result;
        }

        // ---------------------------------------------------------------- rows

        private string SelectedShape()
        {
            string[] shapes = BwicFamilies.SlotShapes[_slot];
            int index = Find<ComboBox>("fs_shape_cb").SelectedIndex;
            return index >= 0 && index < shapes.Length ? shapes[index] : shapes[0];
        }

        private static void PlaceIn(Grid grid, UIElement element, int row, int column, int span = 1)
        {
            Grid.SetRow(element, row);
            Grid.SetColumn(element, column);
            if (span > 1) Grid.SetColumnSpan(element, span);
            grid.Children.Add(element);
        }

        private static void ResetGrid(Grid grid)
        {
            grid.Children.Clear();
            grid.RowDefinitions.Clear();
            grid.ColumnDefinitions.Clear();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(165) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        }

        private ComboBox NamesCombo(List<string> source, string current, Thickness margin)
        {
            var combo = new ComboBox { Margin = margin, Style = (Style)Res("DarkCombo") };
            var names = new List<string>(source);
            if (current.Length > 0 && !names.Contains(current)) names.Insert(0, current);
            combo.Items.Add("<none>");
            foreach (string name in names) combo.Items.Add(name);
            combo.SelectedIndex = names.Contains(current) ? names.IndexOf(current) + 1 : 0;
            combo.SelectionChanged += (s, e) => Check();
            return combo;
        }

        private void BuildRows()
        {
            string shape = SelectedShape();
            bool roundShape = shape == BwicFamilies.Circ;
            var holds = Find<ComboBox>("fs_holds_cb");
            holds.Visibility = roundShape ? Visibility.Visible : Visibility.Collapsed;
            Find<TextBlock>("fs_holds_lbl").Visibility = holds.Visibility;
            var sizeGrid = Find<Grid>("fs_size_grid");
            var positionGrid = Find<Grid>("fs_position_grid");
            ResetGrid(sizeGrid);
            ResetGrid(positionGrid);
            _combos.Clear();
            _roleRows.Clear();
            var labelStyle = (Style)Res("FieldLabel");
            var dim = (Brush)Res("TextDim");
            var roles = BwicFamilies.Sub(_profile, "roles") ?? new Dictionary<string, object>();
            foreach (BwicRole role in BwicFamilies.RolesFor(_slot, shape))
            {
                Grid grid = SizeRoles.Contains(role.Key) ? sizeGrid : positionGrid;
                int row = grid.RowDefinitions.Count;
                grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                var left = new StackPanel { Margin = new Thickness(0, 0, 10, 8) };
                var title = new TextBlock { Text = role.Label + (role.Required ? "  *" : ""), Style = labelStyle };
                left.Children.Add(title);
                left.Children.Add(new TextBlock { Text = role.Help, FontSize = 10.5, Foreground = dim, TextWrapping = TextWrapping.Wrap });
                PlaceIn(grid, left, row, 0);
                var names = role.Kind == "length" ? _lengthNames : _allNames;
                ComboBox combo = NamesCombo(names, BwicFamilies.Str(roles, role.Key), new Thickness(0, 0, 0, 8));
                combo.VerticalAlignment = VerticalAlignment.Top;
                PlaceIn(grid, combo, row, 1);
                _combos[role.Key] = combo;
                _roleRows[role.Key] = new UIElement[] { left, combo };
            }
            BuildSplitRows();
            ShowDrive();
            Check();
        }

        /// <summary>Three groups (X = Width, Y = Length, Z = Height), each with a Minus and a Plus parameter.</summary>
        private void BuildSplitRows()
        {
            var grid = Find<Grid>("fs_split_grid");
            ResetGrid(grid);
            _splitCombos.Clear();
            if (!BwicFamilies.SplitAxes.ContainsKey(_slot)) return;
            var labelStyle = (Style)Res("FieldLabel");
            var dim = (Brush)Res("TextDim");
            var main = (Brush)Res("TextMain");
            var needed = BwicFamilies.RolesFor(_slot, SelectedShape()).Where(r => r.Required).Select(r => r.Key).ToList();
            var sizeWord = new Dictionary<string, string> { { "x", "width" }, { "y", "length" }, { "z", "height" } };
            var split = BwicFamilies.Sub(_profile, "split") ?? new Dictionary<string, object>();
            foreach (BwicSplitAxis axis in BwicFamilies.SplitAxes[_slot])
            {
                int row = grid.RowDefinitions.Count;
                grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                var head = new TextBlock
                {
                    Text = axis.Label + (needed.Contains(axis.Role) ? "  *" : ""), FontSize = 12.5, Foreground = main,
                    Margin = new Thickness(0, 4, 0, 1), FontWeight = FontWeights.SemiBold,
                };
                PlaceIn(grid, head, row, 0, 2);
                row++;
                grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                string what = "the overall " + sizeWord[axis.Axis];
                if (_slot == "wall_circ") what = "the thickness through the wall";
                else if (_slot == "slab_circ") what = "the thickness through the floor";
                PlaceIn(grid, new TextBlock
                {
                    Text = "Each side takes half " + what + ".", FontSize = 10.5, Foreground = dim, TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(0, 0, 0, 5),
                }, row, 0, 2);
                var pair = BwicFamilies.Sub(split, axis.Axis);
                foreach (var side in new[] { Tuple.Create("minus", "Minus side"), Tuple.Create("plus", "Plus side") })
                {
                    row = grid.RowDefinitions.Count;
                    grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                    PlaceIn(grid, new TextBlock { Text = axis.Axis.ToUpperInvariant() + " " + side.Item2, Margin = new Thickness(10, 0, 10, 6), Style = labelStyle }, row, 0);
                    ComboBox combo = NamesCombo(_lengthNames, BwicFamilies.Str(pair, side.Item1), new Thickness(0, 0, 0, 6));
                    PlaceIn(grid, combo, row, 1);
                    _splitCombos[axis.Axis + "|" + side.Item1] = combo;
                }
            }
        }

        private string SelectedDrive()
        {
            if (BwicFamilies.SplitAxes.ContainsKey(_slot) && Find<TabControl>("fs_drive_tabs").SelectedIndex == 1) return BwicFamilies.Split;
            return BwicFamilies.Standard;
        }

        private void ShowDrive()
        {
            bool split = SelectedDrive() == BwicFamilies.Split;
            Find<StackPanel>("fs_split_pnl").Visibility = split ? Visibility.Visible : Visibility.Collapsed;
            var standard = Find<StackPanel>("fs_standard_pnl");
            bool roundFamily = BwicFamilies.SlotShapes[_slot].Length == 1 && BwicFamilies.SlotShapes[_slot][0] == BwicFamilies.Circ;
            if (roundFamily)
            {
                standard.Visibility = Visibility.Visible;
                var covered = BwicFamilies.AxisRoles(_slot);
                foreach (var kv in _roleRows)
                {
                    Visibility shown = split && covered.Contains(kv.Key) ? Visibility.Collapsed : Visibility.Visible;
                    foreach (UIElement element in kv.Value) element.Visibility = shown;
                }
            }
            else standard.Visibility = split ? Visibility.Collapsed : Visibility.Visible;
        }

        private static string Picked(ComboBox combo)
        {
            object value = combo.SelectedItem;
            return value == null || value.ToString().StartsWith("<") ? "" : value.ToString();
        }

        /// <summary>The profile as the dialog now shows it; roles of the other shape are kept so switching back loses nothing.</summary>
        private Dictionary<string, object> Gather()
        {
            var roles = new Dictionary<string, object>(BwicFamilies.Sub(_profile, "roles") ?? new Dictionary<string, object>());
            foreach (var kv in _combos) roles[kv.Key] = Picked(kv.Value);
            var split = new Dictionary<string, object>();
            var src = BwicFamilies.Sub(_profile, "split");
            if (src != null)
                foreach (var kv in src)
                {
                    var pair = kv.Value as Dictionary<string, object>;
                    split[kv.Key] = pair != null ? new Dictionary<string, object>(pair) : new Dictionary<string, object>();
                }
            foreach (var kv in _splitCombos)
            {
                string[] parts = kv.Key.Split('|');
                if (!split.ContainsKey(parts[0])) split[parts[0]] = new Dictionary<string, object>();
                ((Dictionary<string, object>)split[parts[0]])[parts[1]] = Picked(kv.Value);
            }
            return new Dictionary<string, object>
            {
                { "shape", SelectedShape() },
                { "radius", Find<ComboBox>("fs_holds_cb").SelectedIndex == 1 },
                { "roles", roles },
                { "drive", SelectedDrive() },
                { "split", split },
                { "worksets", GatheredWorksets() },
                { "clearance_mm", Find<TextBox>("fs_clearance_tb").Text.Trim() },
            };
        }

        private void Check()
        {
            var found = BwicFamilies.Problems(_slot, Gather(), _lengthNames);
            var tb = Find<TextBlock>("fs_problems_tb");
            var bd = Find<Border>("fs_problems_bd");
            if (found.Count > 0)
            {
                tb.Text = string.Join("\n", found.Select(p => "â€¢ " + p));
                bd.Visibility = Visibility.Visible;
            }
            else
            {
                tb.Text = "";
                bd.Visibility = Visibility.Collapsed;
            }
        }

        private void SuggestClick()
        {
            var guess = BwicFamilies.SeedProfile(_slot, new Dictionary<string, string>(), _lengthNames, _allNames);
            guess["shape"] = SelectedShape();
            _profile = guess;
            Find<ComboBox>("fs_holds_cb").SelectedIndex = BwicFamilies.Bool(guess, "radius") ? 1 : 0;
            if (BwicFamilies.SplitAxes.ContainsKey(_slot))
                Find<TabControl>("fs_drive_tabs").SelectedIndex = BwicFamilies.Str(guess, "drive") == BwicFamilies.Split ? 1 : 0;
            BuildRows();
        }
    }
}
