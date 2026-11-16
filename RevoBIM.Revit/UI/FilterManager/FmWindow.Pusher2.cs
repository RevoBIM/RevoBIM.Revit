using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using Autodesk.Revit.DB;
using RevoBIM.Tools.FilterManager;
using ComboBox = System.Windows.Controls.ComboBox;
using TextBox = System.Windows.Controls.TextBox;
using Panel = System.Windows.Controls.Panel;
using View = Autodesk.Revit.DB.View;
using Visibility = System.Windows.Visibility;

using Grid = System.Windows.Controls.Grid;

namespace RevoBIM.UI.FilterManager
{
    /// <summary>One row of the staging table on the Filters sub-tab (the python dict {"id", "name", "pick", cells...}).</summary>
    public class FmStageRow
    {
        public ElementId Id;
        public string Name;
        public CheckBox Pick;
        public CheckBox Enabled, Visible, Halftone;
        public TextBox Transparency;
        public Button Projection, Surface, Cut, CutPattern;
        public Border Border;
    }

    // =======================================================================
    //  FILTER PUSHER, "Filters" sub-tab, part 2: the project filter list, the staging table,
    //  the properties table (python script.py 4861-5326). The push itself is in FmWindow.Pusher2Push.cs.
    // =======================================================================
    public partial class FmWindow
    {
        private static readonly Dictionary<string, string> OverrideTitles = new Dictionary<string, string>
        {
            { "projection", "Projection / Surface  -  Lines" },
            { "cut", "Cut  -  Lines" },
            { "surface", "Projection / Surface  -  Patterns" },
            { "cutpattern", "Cut  -  Patterns" },
        };

        private List<FmChoice> LinePatternList()
        {
            if (linePatterns == null) linePatterns = FmOverrides.LinePatterns(Doc);
            return linePatterns;
        }

        private List<FmChoice> FillPatternList()
        {
            if (fillPatterns == null) fillPatterns = FmOverrides.FillPatterns(Doc);
            return fillPatterns;
        }

        private List<Tuple<ElementId, string>> AllFilterPairs()
        {
            var pairs = new List<Tuple<ElementId, string>>();
            foreach (ParameterFilterElement f in allFilters)
            {
                try { pairs.Add(Tuple.Create(f.Id, f.Name)); }
                catch (Exception) { continue; }
            }
            return pairs;
        }

        private FmSpec SpecFor(ElementId filterId)
        {
            long key = FmCore.EidValue(filterId);
            FmSpec spec;
            if (!specs.TryGetValue(key, out spec))
            {
                spec = FmOverrides.NewSpec();
                specs[key] = spec;
            }
            return spec;
        }

        private bool IsStaged(ElementId filterId)
        {
            long target = FmCore.EidValue(filterId);
            return staged.Any(s => FmCore.EidValue(s.Item1) == target);
        }

        // -- left hand list -----------------------------------------------------
        private void FillAllFilters()
        {
            string search = txtAllFilterSearch.Text;
            lstAllFilters.Items.Clear();
            foreach (var pair in AllFilterPairs())
            {
                ElementId fid = pair.Item1;
                string nm = pair.Item2;
                if (!FmCore.RowVisible(nm, 0, search, false)) continue;
                bool isStaged = IsStaged(fid);
                string label = nm + (isStaged ? "   (staged)" : "");
                bool ticked;
                allPushState.TryGetValue(nm, out ticked);
                CheckBox cb = FmUi.NewCheckBox(label, fid, ticked);
                cb.IsEnabled = !isStaged;
                cb.Checked += FmUi.Safe(OnAllfilterTicked, "on_allfilter_ticked");
                cb.Unchecked += FmUi.Safe(OnAllfilterTicked, "on_allfilter_ticked");
                ListBoxItem item = FmUi.NewListItem("", fid);
                item.Content = cb;
                lstAllFilters.Items.Add(item);
            }
        }

        /// <summary>
        /// Read the ticks back, keyed off the element id. The label carries a "(staged)" suffix, so parsing the
        /// name back out of it would be one string edit away from silently losing a tick.
        /// </summary>
        private void HarvestAllFilters()
        {
            var names = new Dictionary<long, string>();
            foreach (var pair in AllFilterPairs()) names[FmCore.EidValue(pair.Item1)] = pair.Item2;
            foreach (object obj in lstAllFilters.Items)
            {
                try
                {
                    var item = obj as ListBoxItem;
                    string nm;
                    if (item != null && names.TryGetValue(FmCore.EidValue((ElementId)item.Tag), out nm))
                        allPushState[nm] = ((CheckBox)item.Content).IsChecked == true;
                }
                catch (Exception) { continue; }
            }
        }

        public void OnAllfilterSearch(object sender, RoutedEventArgs args)
        {
            HarvestAllFilters();
            searches["all"].Poke();
        }

        private void RunAllFilterSearch() { FillAllFilters(); }

        public void OnAllfilterTicked(object sender, RoutedEventArgs args)
        {
            HarvestAllFilters();
            RefreshFooter();
        }

        public void OnAllfiltersAll(object sender, RoutedEventArgs args)
        {
            foreach (object obj in lstAllFilters.Items)
            {
                try
                {
                    var cb = ((ListBoxItem)obj).Content as CheckBox;
                    if (cb != null && cb.IsEnabled) cb.IsChecked = true;
                }
                catch (Exception) { }
            }
            HarvestAllFilters();
            RefreshFooter();
        }

        public void OnAllfiltersNone(object sender, RoutedEventArgs args)
        {
            foreach (object obj in lstAllFilters.Items)
            {
                try
                {
                    var cb = ((ListBoxItem)obj).Content as CheckBox;
                    if (cb != null) cb.IsChecked = false;
                }
                catch (Exception) { }
            }
            HarvestAllFilters();
            RefreshFooter();
        }

        // -- the arrows ---------------------------------------------------------
        public void OnStageAdd(object sender, RoutedEventArgs args)
        {
            HarvestAllFilters();
            int added = 0;
            foreach (var pair in AllFilterPairs())
            {
                ElementId fid = pair.Item1;
                string nm = pair.Item2;
                bool ticked;
                if (!allPushState.TryGetValue(nm, out ticked) || !ticked) continue;
                if (IsStaged(fid)) continue;
                staged.Add(Tuple.Create(fid, nm));
                SpecFor(fid);
                stagedTicked[nm] = false;
                added++;
            }
            if (added == 0)
            {
                txtStatus.Text = "Tick a filter on the left first.";
                return;
            }
            foreach (string nm in allPushState.Keys.ToList()) allPushState[nm] = false;
            FillAllFilters();
            BuildPropsPanel();
            RefreshFooter();
            txtStatus.Text = "Added " + added + " filter(s) to the table.";
        }

        public void OnStageRemove(object sender, RoutedEventArgs args)
        {
            HarvestTable();
            var keep = new List<Tuple<ElementId, string>>();
            int gone = 0;
            foreach (var pair in staged)
            {
                bool ticked;
                if (stagedTicked.TryGetValue(pair.Item2, out ticked) && ticked) gone++;
                else keep.Add(pair);
            }
            if (gone == 0)
            {
                txtStatus.Text = "Tick a row in the table first.";
                return;
            }
            staged = keep;
            FillAllFilters();
            BuildPropsPanel();
            RefreshFooter();
            txtStatus.Text = "Removed " + gone + " row(s).";
        }

        // -- the table ----------------------------------------------------------
        /// <summary>A row per staged filter, laid out like Revit's own Filters tab.</summary>
        private void BuildPropsPanel()
        {
            pnlProps.Children.Clear();
            rowControls = new List<object>();

            if (staged.Count == 0)
            {
                txtPropTarget.Text = "Nothing staged yet.";
                pnlProps.Children.Add(FmUi.NewText(
                    "Tick filters on the left and press the green arrow to bring them in here.", "Dim", 11, false,
                    new Thickness(8, 8, 8, 8)));
                return;
            }

            txtPropTarget.Text = staged.Count + " filter(s) staged";
            pnlProps.Children.Add(StagingHeader());
            foreach (var pair in staged) pnlProps.Children.Add(TableRow(pair.Item1, pair.Item2));
        }

        private UIElement StagingHeader()
        {
            var outer = new Border();
            outer.Width = TableWidth();
            outer.Background = FmUi.PBrush("HeaderRow");
            outer.BorderBrush = FmUi.PBrush("Edge");
            outer.BorderThickness = new Thickness(0, 0, 0, 1);

            var grid = new Grid();
            foreach (var column in Columns) grid.ColumnDefinitions.Add(FmUi.Col(null, column.Item3));
            grid.RowDefinitions.Add(FmUi.Row());
            grid.RowDefinitions.Add(FmUi.Row());

            var groups = new[]
            {
                Tuple.Create(3, 5, "Projection / Surface"),
                Tuple.Create(6, 7, "Cut"),
            };
            var spanned = new HashSet<int>();
            foreach (var g in groups)
            {
                var label = new TextBlock();
                label.Text = g.Item3;
                label.FontSize = 10;
                label.FontWeight = FontWeights.Bold;
                label.HorizontalAlignment = HorizontalAlignment.Center;
                label.Margin = new Thickness(0, 4, 0, 2);
                label.SetResourceReference(TextBlock.ForegroundProperty, "Blue");
                Grid.SetRow(label, 0);
                Grid.SetColumn(label, g.Item1);
                Grid.SetColumnSpan(label, g.Item2 - g.Item1 + 1);
                grid.Children.Add(label);
                for (int c = g.Item1; c <= g.Item2; c++) spanned.Add(c);
            }

            for (int i = 0; i < Columns.Length; i++)
            {
                var tb = new TextBlock();
                tb.Text = Columns[i].Item2;
                tb.FontSize = 10;
                tb.FontWeight = FontWeights.Bold;
                tb.TextWrapping = TextWrapping.Wrap;
                tb.Margin = new Thickness(6, 3, 6, 5);
                if (i != 0) tb.HorizontalAlignment = HorizontalAlignment.Center;
                tb.SetResourceReference(TextBlock.ForegroundProperty, "Dim");
                Grid.SetColumn(tb, i);
                if (spanned.Contains(i)) Grid.SetRow(tb, 1);
                else
                {
                    Grid.SetRow(tb, 0);
                    Grid.SetRowSpan(tb, 2);
                }
                grid.Children.Add(tb);
            }

            outer.Child = grid;
            return outer;
        }

        private UIElement TableRow(ElementId fid, string name)
        {
            FmSpec spec = SpecFor(fid);
            var row = new FmStageRow { Id = fid, Name = name };

            var outer = new Border();
            outer.Width = TableWidth();
            outer.BorderBrush = FmUi.PBrush("EdgeFaint");
            outer.BorderThickness = new Thickness(0, 0, 0, 1);
            outer.Padding = new Thickness(0, 2, 0, 2);

            var grid = new Grid();
            foreach (var column in Columns) grid.ColumnDefinitions.Add(FmUi.Col(null, column.Item3));

            // name doubles as the row tick
            bool ticked;
            stagedTicked.TryGetValue(name, out ticked);
            CheckBox pick = FmUi.NewCheckBox(name, fid, ticked);
            pick.Margin = new Thickness(6, 3, 4, 3);
            pick.Checked += FmUi.Safe(OnRowTicked, "on_row_ticked");
            pick.Unchecked += FmUi.Safe(OnRowTicked, "on_row_ticked");
            row.Pick = pick;
            FmUi.Place(pick, grid, 0);

            row.Enabled = StageCell(spec, "enabled", grid, 1);
            row.Visible = StageCell(spec, "visible", grid, 2);
            row.Halftone = StageCell(spec, "halftone", grid, 8);

            row.Projection = OverrideButton(fid, name, "projection", spec);
            FmUi.Place(row.Projection, grid, 3);
            row.Surface = OverrideButton(fid, name, "surface", spec);
            FmUi.Place(row.Surface, grid, 4);
            row.Cut = OverrideButton(fid, name, "cut", spec);
            FmUi.Place(row.Cut, grid, 6);
            row.CutPattern = OverrideButton(fid, name, "cutpattern", spec);
            FmUi.Place(row.CutPattern, grid, 7);

            TextBox box = FmUi.NewTextBox(spec.Int("transparency").ToString(CultureInfo.InvariantCulture), "0-100", 56);
            box.HorizontalAlignment = HorizontalAlignment.Center;
            box.Margin = new Thickness(0, 3, 0, 3);
            box.TextChanged += FmUi.SafeText((s, a) => OnCellToggled(s, a), "on_cell_toggled");
            row.Transparency = box;
            FmUi.Place(box, grid, 5);

            outer.Child = grid;
            row.Border = outer;
            rowControls.Add(row);
            return outer;
        }

        private CheckBox StageCell(FmSpec spec, string key, Grid grid, int column)
        {
            CheckBox cb = FmUi.NewCheckBox("", null, spec.Bool(key));
            cb.HorizontalAlignment = HorizontalAlignment.Center;
            cb.Margin = new Thickness(0, 4, 0, 4);
            cb.Checked += FmUi.Safe(OnCellToggled, "on_cell_toggled");
            cb.Unchecked += FmUi.Safe(OnCellToggled, "on_cell_toggled");
            FmUi.Place(cb, grid, column);
            return cb;
        }

        private Button OverrideButton(ElementId fid, string name, string kind, FmSpec spec)
        {
            Button btn = FmUi.NewButton("", "Ghost", null, null, 24);
            btn.Margin = new Thickness(4, 3, 4, 3);
            btn.Content = OverridePreview(kind, spec);
            btn.Click += FmUi.Safe((s, a) => EditOverride(fid, name, kind, btn), "edit_override");
            return btn;
        }

        /// <summary>Python truthiness of a spec value: None, 0 and "" are false, anything else (a pattern id) is true.</summary>
        private static bool SpecSet(object value)
        {
            if (value == null) return false;
            var text = value as string;
            if (text != null) return text.Length > 0;
            if (value is int) return (int)value != 0;
            if (value is bool) return (bool)value;
            return true;
        }

        /// <summary>The six hex digits of a '#AARRGGBB' palette colour (python: pcolour(key)[3:]).</summary>
        private static string PaletteRgb(string key)
        {
            string c = FmUi.PColour(key) ?? "";
            return c.Length >= 9 ? c.Substring(3) : c.TrimStart('#');
        }

        /// <summary>A line sample, a colour swatch, or the word Override.</summary>
        private UIElement OverridePreview(string kind, FmSpec spec)
        {
            if (kind == "projection" || kind == "cut")
            {
                string ck = kind == "projection" ? "proj_colour" : "cut_colour";
                string wk = kind == "projection" ? "proj_weight" : "cut_weight";
                string pk = kind == "projection" ? "proj_pattern" : "cut_pattern";
                if (!(SpecSet(spec[ck]) || SpecSet(spec[wk]) || SpecSet(spec[pk]))) return OverrideLabel();
                var line = new Border();
                int weight = spec.Int(wk);
                if (weight == 0) weight = 2;
                line.Height = Math.Max(1, Math.Min(5, weight));
                line.Width = 62;
                line.VerticalAlignment = VerticalAlignment.Center;
                line.HorizontalAlignment = HorizontalAlignment.Center;
                string colour = spec.Str(ck);
                FmUi.PaintSwatch(line, string.IsNullOrEmpty(colour) ? PaletteRgb("Txt") : colour);
                return line;
            }

            string fg = kind == "surface" ? "surf_fg_colour" : "cut_fg_colour";
            string fp = kind == "surface" ? "surf_fg_pattern" : "cut_fg_pattern";
            string bg = kind == "surface" ? "surf_bg_colour" : "cut_bg_colour";
            string bp = kind == "surface" ? "surf_bg_pattern" : "cut_bg_pattern";
            if (!(SpecSet(spec[fg]) || SpecSet(spec[fp]) || SpecSet(spec[bg]) || SpecSet(spec[bp]))) return OverrideLabel();

            var block = new Border();
            block.Height = 15;
            block.Width = 62;
            block.BorderBrush = FmUi.PBrush("EdgeStrong");
            block.BorderThickness = new Thickness(1);
            string fill = spec.Str(fg);
            if (string.IsNullOrEmpty(fill)) fill = spec.Str(bg);
            FmUi.PaintSwatch(block, string.IsNullOrEmpty(fill) ? PaletteRgb("Dim") : fill);
            return block;
        }

        private UIElement OverrideLabel()
        {
            var tb = new TextBlock();
            tb.Text = "Override...";
            tb.FontSize = 10;
            tb.SetResourceReference(TextBlock.ForegroundProperty, "Dim");
            return tb;
        }

        /// <summary>
        /// Which rows an edit on this row applies to. Editing a ticked row edits every ticked row, so several
        /// filters can be set in one go. Editing a row that is not ticked touches only it.
        /// </summary>
        private List<ElementId> EditTargets(ElementId fid)
        {
            HarvestTable();
            var ticked = new List<ElementId>();
            foreach (var pair in staged)
            {
                bool t;
                if (stagedTicked.TryGetValue(pair.Item2, out t) && t) ticked.Add(pair.Item1);
            }
            long want = FmCore.EidValue(fid);
            if (ticked.Any(f => FmCore.EidValue(f) == want) && ticked.Count > 1) return ticked;
            return new List<ElementId> { fid };
        }

        private void EditOverride(ElementId fid, string name, string kind, Button button)
        {
            List<ElementId> targets = EditTargets(fid);
            FmSpec spec = SpecFor(fid);

            string subject, scope;
            if (targets.Count > 1)
            {
                subject = name + "  and " + (targets.Count - 1) + " other ticked filter(s)";
                scope = "This will be applied to all " + targets.Count + " ticked filters.";
            }
            else
            {
                subject = name;
                scope = "";
            }

            var dlg = new FmOverrideWindow(Doc, kind, spec, subject, LinePatternList(), FillPatternList(), scope);
            dlg.Owner = Win;
            dlg.ShowDialog();
            if (dlg.Result == null) return;

            foreach (ElementId target in targets)
            {
                FmSpec targetSpec = SpecFor(target);
                foreach (var kv in dlg.Result) targetSpec[kv.Key] = kv.Value;
            }

            if (targets.Count > 1)
            {
                BuildPropsPanel();
                string title;
                txtStatus.Text = "Set " + (OverrideTitles.TryGetValue(kind, out title) ? title : kind) + " on " + targets.Count +
                                 " ticked filter(s).";
            }
            else button.Content = OverridePreview(kind, spec);
        }

        public void OnRowTicked(object sender, RoutedEventArgs args) { HarvestTable(); }

        /// <summary>A cell edited on a ticked row is applied to every ticked row.</summary>
        public void OnCellToggled(object sender, RoutedEventArgs args)
        {
            HarvestTable();
            FmStageRow row = null;
            foreach (object obj in rowControls)
            {
                var candidate = obj as FmStageRow;
                if (candidate == null) continue;
                if (ReferenceEquals(candidate.Enabled, sender) || ReferenceEquals(candidate.Visible, sender) ||
                    ReferenceEquals(candidate.Halftone, sender) || ReferenceEquals(candidate.Transparency, sender))
                {
                    row = candidate;
                    break;
                }
            }
            if (row == null) return;

            var targets = new List<ElementId>();
            foreach (var pair in staged)
            {
                bool t;
                if (stagedTicked.TryGetValue(pair.Item2, out t) && t) targets.Add(pair.Item1);
            }
            if (targets.Count < 2) return;
            long rowId = FmCore.EidValue(row.Id);
            if (!targets.Any(f => FmCore.EidValue(f) == rowId)) return;

            FmSpec source = SpecFor(row.Id);
            foreach (ElementId target in targets)
            {
                if (FmCore.EidValue(target) == rowId) continue;
                FmSpec spec = SpecFor(target);
                foreach (string key in new[] { "enabled", "visible", "halftone", "transparency" }) spec[key] = source[key];
            }
            BuildPropsPanel();
        }

        /// <summary>Read every cell in the table back into the specs.</summary>
        private void HarvestTable()
        {
            foreach (object obj in rowControls.ToList())
            {
                var row = obj as FmStageRow;
                if (row == null) continue;
                try { stagedTicked[row.Name] = row.Pick.IsChecked == true; }
                catch (Exception) { }
                FmSpec spec = SpecFor(row.Id);
                try { spec["enabled"] = row.Enabled.IsChecked == true; }
                catch (Exception) { }
                try { spec["visible"] = row.Visible.IsChecked == true; }
                catch (Exception) { }
                try { spec["halftone"] = row.Halftone.IsChecked == true; }
                catch (Exception) { }
                try
                {
                    string text = (row.Transparency.Text ?? "").Trim();
                    int value = 0;
                    if (text.Length > 0 &&
                        !int.TryParse(text, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out value))
                        value = 0;
                    spec["transparency"] = Math.Max(0, Math.Min(100, value));
                }
                catch (Exception) { spec["transparency"] = 0; }
            }
        }

        // -- the three table buttons -------------------------------------------
        private List<Tuple<ElementId, string>> TickedRows()
        {
            HarvestTable();
            var rows = new List<Tuple<ElementId, string>>();
            foreach (var pair in staged)
            {
                bool t;
                if (stagedTicked.TryGetValue(pair.Item2, out t) && t) rows.Add(pair);
            }
            return rows;
        }

        public void OnCopyProps(object sender, RoutedEventArgs args)
        {
            var rows = TickedRows();
            if (rows.Count == 0)
            {
                txtStatus.Text = "Tick the row you want to copy from.";
                return;
            }
            FmSpec source = SpecFor(rows[0].Item1);
            long sourceId = FmCore.EidValue(rows[0].Item1);
            int n = 0;
            foreach (var pair in staged)
            {
                if (FmCore.EidValue(pair.Item1) == sourceId) continue;
                FmSpec target = SpecFor(pair.Item1);
                foreach (string k in source.Values.Keys.ToList()) target[k] = source[k];
                n++;
            }
            BuildPropsPanel();
            txtStatus.Text = "Copied '" + rows[0].Item2 + "' onto " + n + " other row(s).";
        }

        public void OnReadProps(object sender, RoutedEventArgs args)
        {
            var rows = TickedRows();
            if (rows.Count == 0)
            {
                txtStatus.Text = "Tick the rows you want to read into.";
                return;
            }
            if (host == null)
            {
                FmMessage.Alert("Pick a host view template on the Templates tab first, then this reads each filter's graphics out of it.");
                return;
            }
            var onHost = new HashSet<long>();
            try
            {
                foreach (ElementId f in host.GetFilters()) onHost.Add(FmCore.EidValue(f));
            }
            catch (Exception) { onHost = new HashSet<long>(); }

            int read = 0, missing = 0;
            foreach (var pair in rows)
            {
                long id = FmCore.EidValue(pair.Item1);
                if (onHost.Contains(id))
                {
                    specs[id] = FmOverrides.ReadOverrides(host, pair.Item1);
                    read++;
                }
                else missing++;
            }
            BuildPropsPanel();
            txtStatus.Text = "Read " + read + " row(s) from '" + host.Name + "'" +
                             (missing > 0 ? "; " + missing + " not on that template" : "") + ".";
        }

        public void OnResetProps(object sender, RoutedEventArgs args)
        {
            var rows = TickedRows();
            if (rows.Count == 0)
            {
                txtStatus.Text = "Tick the rows you want to reset.";
                return;
            }
            foreach (var pair in rows) specs[FmCore.EidValue(pair.Item1)] = FmOverrides.NewSpec();
            BuildPropsPanel();
            txtStatus.Text = "Reset " + rows.Count + " row(s).";
        }
    }
}

