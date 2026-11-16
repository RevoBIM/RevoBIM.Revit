using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using Autodesk.Revit.DB;
using RevoBIM.Tools.FilterManager;
using ComboBox = System.Windows.Controls.ComboBox;
using TextBox = System.Windows.Controls.TextBox;
using Panel = System.Windows.Controls.Panel;
using Grid = System.Windows.Controls.Grid;
using Point = System.Windows.Point;
using View = Autodesk.Revit.DB.View;
using Visibility = System.Windows.Visibility;

namespace RevoBIM.UI.FilterManager
{
    /// <summary>
    /// Filter Pusher, first half (script.py 4158-4860): view templates and the host list, the "Filters to push"
    /// table, the overwrite menu, the target templates list and the Target Views sub-tab.
    /// </summary>
    public partial class FmWindow
    {
        // =======================================================================
        //  TAB 2 - FILTER PUSHER
        // =======================================================================
        private void ReloadTemplates(ElementId keepHost = null)
        {
            templates = FmFilters.GetViewTemplates(Doc);
            templateCounts = FmFilters.TemplateFilterCounts(Doc, templates);
            var names = new HashSet<string>();
            foreach (View t in templates)
            {
                try { names.Add(t.Name); }
                catch (Exception) { }
            }
            foreach (string nm in targetState.Keys.ToList())
                if (!names.Contains(nm)) targetState.Remove(nm);
            foreach (string nm in names)
                if (!targetState.ContainsKey(nm)) targetState[nm] = false;

            host = null;
            if (keepHost != null)
            {
                foreach (View t in templates)
                {
                    if (FmCore.EidValue(t.Id) == FmCore.EidValue(keepHost))
                    {
                        host = t;
                        break;
                    }
                }
            }

            if (host == null)
            {
                hostFilters = new List<Tuple<ElementId, string>>();
                pushState = new Dictionary<string, bool>();
                txtHostName.Text = "- no host template selected -";
            }
            else
            {
                hostFilters = FmFilters.GetTemplateFilters(Doc, host);
                txtHostName.Text = host.Name;
            }

            var live = new HashSet<string>();
            foreach (var pair in AllFilterPairs()) live.Add(pair.Item2);
            foreach (string nm in allPushState.Keys.ToList())
                if (!live.Contains(nm)) allPushState.Remove(nm);

            FillHosts();
            FillPushFilters();
            FillAllFilters();
            FillTargets();
            if (viewsLoaded) LoadTargetViews();
        }

        private void FillHosts()
        {
            string search = txtHostSearch.Text;
            lstHosts.Items.Clear();
            foreach (View t in templates)
            {
                if (!FmCore.RowVisible(t.Name, 0, search, false)) continue;
                int count;
                templateCounts.TryGetValue(FmCore.EidValue(t.Id), out count);
                ListBoxItem item = FmUi.NewListItem(t.Name + "   (" + count + " filters)", t);
                lstHosts.Items.Add(item);
                if (host != null && FmCore.EidValue(t.Id) == FmCore.EidValue(host.Id))
                    item.IsSelected = true;
            }
        }

        public void OnHostSearch(object sender, RoutedEventArgs args)
        {
            searches["hosts"].Poke();
        }

        public void OnHostChanged(object sender, RoutedEventArgs args)
        {
            var item = lstHosts.SelectedItem as ListBoxItem;
            if (item == null) return;
            host = item.Tag as View;
            if (host == null) return;
            hostFilters = FmFilters.GetTemplateFilters(Doc, host);
            pushState = new Dictionary<string, bool>();
            pushGroups = new Dictionary<string, Dictionary<string, bool>>();
            foreach (var pair in hostFilters) pushState[pair.Item2] = false;
            txtHostName.Text = host.Name;
            FillPushFilters();
            FillTargets();
            RefreshFooter();
        }

        // -- "Filters to push": a row per host filter, a tick per setting ----
        //  Settings columns are a fixed narrow width with their headings turned
        //  on end. The name column takes everything else, so the ticks sit
        //  hard against the right whatever the window's size.
        private const double PushCell = 30;
        private const double PushNameMin = 120;

        private Dictionary<string, bool> PushGroupsFor(string fname)
        {
            Dictionary<string, bool> groups;
            if (!pushGroups.TryGetValue(fname, out groups))
            {
                groups = FmOverrides.AllGroups(true);
                pushGroups[fname] = groups;
            }
            return groups;
        }

        private void PushColumns(Grid grid)
        {
            ColumnDefinition nameCol = FmUi.Col(widthStar: 1);
            nameCol.MinWidth = PushNameMin;
            grid.ColumnDefinitions.Add(nameCol);
            foreach (var g in FmOverrides.PushGroups)
                grid.ColumnDefinitions.Add(FmUi.Col(pixels: PushCell));
        }

        private Grid pushHeaderGrid;

        private void BuildPushHeader()
        {
            var grid = new Grid();
            PushColumns(grid);

            var name = new TextBlock
            {
                Text = "Filter",
                FontSize = 11,
                FontWeight = FontWeights.Bold,
                VerticalAlignment = VerticalAlignment.Bottom,
                Margin = new Thickness(6, 0, 10, 6),
            };
            name.SetResourceReference(TextBlock.ForegroundProperty, "Dim");
            FmUi.Place(name, grid, 0);

            int i = 0;
            foreach (var group in FmOverrides.PushGroups)
            {
                string key = group.Item1;
                string label = group.Item2;
                var cell = new Border
                {
                    BorderThickness = new Thickness(1, 0, 0, 0),
                    Cursor = Cursors.Hand,
                    ToolTip = label + "\nClick to tick or untick it on the selected rows (every row when none is selected).",
                };
                cell.SetResourceReference(Border.BorderBrushProperty, "EdgeFaint");
                cell.SetResourceReference(Border.BackgroundProperty, "HeaderRow");
                var text = new TextBlock
                {
                    Text = label,
                    FontSize = 10,
                    FontWeight = FontWeights.Bold,
                    LayoutTransform = new RotateTransform(-90),
                    HorizontalAlignment = HorizontalAlignment.Center,
                    VerticalAlignment = VerticalAlignment.Bottom,
                    Margin = new Thickness(0, 6, 0, 6),
                };
                text.SetResourceReference(TextBlock.ForegroundProperty, "Dim");
                cell.Child = text;

                cell.MouseLeftButtonUp += FmUi.SafeMouse((s, a) => TogglePushColumn(key), "toggle_push_column");
                FmUi.Place(cell, grid, i + 1);
                i++;
            }

            pnlPushHeader.Child = grid;
            pushHeaderGrid = grid;
            SyncPushHeader();
        }

        private ListBoxItem BuildPushRow(ElementId fid, string fname)
        {
            Dictionary<string, bool> groups = PushGroupsFor(fname);
            var grid = new Grid();
            PushColumns(grid);

            // the tick and the name are separate, so clicking the name selects
            // the row (Ctrl/Shift for several) rather than ticking it
            var cell = new DockPanel { Margin = new Thickness(0, 2, 6, 2) };
            bool picked;
            pushState.TryGetValue(fname, out picked);
            CheckBox pick = FmUi.NewCheckBox("", fname, picked);
            pick.ToolTip = "Push this filter";
            pick.VerticalAlignment = VerticalAlignment.Center;
            pick.Checked += FmUi.Safe(OnPushTicked, "on_push_ticked");
            pick.Unchecked += FmUi.Safe(OnPushTicked, "on_push_ticked");
            DockPanel.SetDock(pick, Dock.Left);
            cell.Children.Add(pick);
            var label = new TextBlock
            {
                Text = fname,
                ToolTip = fname,
                Margin = new Thickness(4, 0, 0, 0),
                VerticalAlignment = VerticalAlignment.Center,
                TextTrimming = TextTrimming.CharacterEllipsis,
            };
            cell.Children.Add(label);
            FmUi.Place(cell, grid, 0);

            var cells = new Dictionary<string, CheckBox>();
            int i = 0;
            foreach (var group in FmOverrides.PushGroups)
            {
                string key = group.Item1;
                bool on;
                if (!groups.TryGetValue(key, out on)) on = true;
                CheckBox cb = FmUi.NewCheckBox("", Tuple.Create(fname, key), on);
                try { cb.Style = (Style)Win.FindResource("CellCheck"); }
                catch (Exception) { }
                cb.HorizontalAlignment = HorizontalAlignment.Center;
                cb.VerticalAlignment = VerticalAlignment.Center;
                cb.ToolTip = "Push " + group.Item2;
                cb.Checked += FmUi.Safe(OnPushCell, "on_push_cell");
                cb.Unchecked += FmUi.Safe(OnPushCell, "on_push_cell");
                FmUi.Place(cb, grid, i + 1);
                cells[key] = cb;
                i++;
            }

            var item = new ListBoxItem
            {
                Content = grid,
                Tag = fname,
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
            };
            pushRows.Add(new FmPushRow { Name = fname, Id = fid, Item = item, Grid = grid, Pick = pick, Cells = cells });
            return item;
        }

        private void FillPushFilters()
        {
            string search = txtFilterSearch.Text;
            lstPushFilters.Items.Clear();
            pushRows = new List<FmPushRow>();
            BuildPushHeader();
            foreach (var pair in hostFilters)
            {
                if (!FmCore.RowVisible(pair.Item2, 0, search, false)) continue;
                lstPushFilters.Items.Add(BuildPushRow(pair.Item1, pair.Item2));
            }
        }

        private FmPushRow PushRowNamed(string fname)
        {
            foreach (FmPushRow row in pushRows)
                if (row.Name == fname) return row;
            return null;
        }

        private List<string> SelectedPushNames()
        {
            var names = new List<string>();
            foreach (object o in lstPushFilters.SelectedItems)
            {
                try
                {
                    var item = o as ListBoxItem;
                    if (item != null && item.Tag is string) names.Add((string)item.Tag);
                }
                catch (Exception) { continue; }
            }
            return names;
        }

        /// <summary>
        /// Ticking inside a selected row ticks every selected row; ticking
        /// in a row that is not selected touches only that row.
        /// </summary>
        private List<string> PushEditTargets(string fname)
        {
            List<string> selected = SelectedPushNames();
            if (selected.Contains(fname) && selected.Count > 1) return selected;
            return new List<string> { fname };
        }

        private void SetPushCell(IEnumerable<string> names, string key, bool value)
        {
            bulk = true;
            try
            {
                foreach (string nm in names)
                {
                    PushGroupsFor(nm)[key] = value;
                    FmPushRow row = PushRowNamed(nm);
                    if (row != null) row.Cells[key].IsChecked = value;
                }
            }
            finally { bulk = false; }
        }

        private void SetPushPick(IEnumerable<string> names, bool value)
        {
            bulk = true;
            try
            {
                foreach (string nm in names)
                {
                    pushState[nm] = value;
                    FmPushRow row = PushRowNamed(nm);
                    if (row != null) row.Pick.IsChecked = value;
                }
            }
            finally { bulk = false; }
        }

        public void OnPushCell(object sender, RoutedEventArgs args)
        {
            if (bulk) return;
            var box = (CheckBox)sender;
            var tag = (Tuple<string, string>)box.Tag;
            SetPushCell(PushEditTargets(tag.Item1), tag.Item2, box.IsChecked == true);
            RefreshFooter();
        }

        private void TogglePushColumn(string key)
        {
            List<string> names = SelectedPushNames();
            if (names.Count == 0) names = pushRows.Select(r => r.Name).ToList();
            if (names.Count == 0) return;
            bool allOn = true;
            foreach (string nm in names)
            {
                bool on;
                if (!PushGroupsFor(nm).TryGetValue(key, out on)) on = true;
                if (!on) { allOn = false; break; }
            }
            SetPushCell(names, key, !allOn);
            RefreshFooter();
        }

        /// <summary>
        /// Keep the heading cells over their ticks.
        ///
        /// The rows sit inside the list's scroll viewer and the heading does
        /// not, so when the vertical scrollbar shows the rows lose its width
        /// and the heading has to give up the same amount on its right.
        /// </summary>
        private void SyncPushHeader()
        {
            ScrollViewer viewer = PushScroller();
            double gap = 0.0;
            if (viewer != null)
            {
                try { gap = Math.Max(0.0, viewer.ActualWidth - viewer.ViewportWidth); }
                catch (Exception) { gap = 0.0; }
            }
            try { pnlPushHeader.Padding = new Thickness(6, 0, 6 + gap, 0); }
            catch (Exception) { }
        }

        /// <summary>The ScrollViewer inside lstPushFilters' template, found once.</summary>
        private ScrollViewer PushScroller()
        {
            var viewer = pushViewer as ScrollViewer;
            if (viewer != null) return viewer;
            var stack = new Stack<DependencyObject>();
            stack.Push(lstPushFilters);
            while (stack.Count > 0)
            {
                DependencyObject node = stack.Pop();
                var found = node as ScrollViewer;
                if (found != null)
                {
                    pushViewer = found;
                    found.ScrollChanged += (s, a) => FmUi.Guard("sync_push_header", SyncPushHeader);
                    return found;
                }
                try
                {
                    int n = VisualTreeHelper.GetChildrenCount(node);
                    for (int i = 0; i < n; i++) stack.Push(VisualTreeHelper.GetChild(node, i));
                }
                catch (Exception) { continue; }
            }
            return null;
        }

        private void HarvestPush()
        {
            foreach (FmPushRow row in pushRows) pushState[row.Name] = row.Pick.IsChecked == true;
        }

        public void OnPfilterSearch(object sender, RoutedEventArgs args)
        {
            HarvestPush();
            searches["push"].Poke();
        }

        private void RunPushFilterSearch()
        {
            FillPushFilters();
        }

        public void OnPushTicked(object sender, RoutedEventArgs args)
        {
            if (bulk) return;
            var box = (CheckBox)sender;
            SetPushPick(PushEditTargets((string)box.Tag), box.IsChecked == true);
            RefreshFooter();
        }

        public void OnPfiltersAll(object sender, RoutedEventArgs args)
        {
            SetPushPick(pushRows.Select(r => r.Name).ToList(), true);
            RefreshFooter();
        }

        public void OnPfiltersNone(object sender, RoutedEventArgs args)
        {
            SetPushPick(pushRows.Select(r => r.Name).ToList(), false);
            RefreshFooter();
        }

        // -- overwrite mode -------------------------------------------------------
        private static string OverwriteLabel(string mode)
        {
            if (mode == "all") return "Overwrite Target All";
            if (mode == "new") return "Overwrite Target New Only";
            return mode;
        }

        public void OnOverwriteMenu(object sender, RoutedEventArgs args)
        {
            var button = sender as Button;
            if (button == null) return;
            ContextMenu menu = button.ContextMenu;
            if (menu == null) return;
            foreach (object o in menu.Items)
            {
                try
                {
                    var item = (MenuItem)o;
                    string mode = item.Tag as string;
                    var row = new StackPanel { Orientation = Orientation.Horizontal };
                    var dot = new Border
                    {
                        Width = 9,
                        Height = 9,
                        CornerRadius = new CornerRadius(5),
                        BorderThickness = new Thickness(1),
                        Margin = new Thickness(0, 0, 8, 0),
                        VerticalAlignment = VerticalAlignment.Center,
                    };
                    dot.SetResourceReference(Border.BorderBrushProperty, "Orange");
                    if (mode == overwriteMode) dot.SetResourceReference(Border.BackgroundProperty, "Orange");
                    var text = new TextBlock { Text = OverwriteLabel(mode) };
                    row.Children.Add(dot);
                    row.Children.Add(text);
                    item.Header = row;
                }
                catch (Exception) { continue; }
            }
            menu.PlacementTarget = button;
            menu.Placement = PlacementMode.Bottom;
            menu.IsOpen = true;
        }

        public void OnOverwritePick(object sender, RoutedEventArgs args)
        {
            var item = sender as FrameworkElement;
            overwriteMode = item != null && (item.Tag as string) == "new" ? "new" : "all";
            string label = OverwriteLabel(overwriteMode);
            foreach (TextBlock box in new[] { txtOverwriteA, txtOverwriteB })
            {
                try { box.Text = label; }
                catch (Exception) { continue; }
            }
            RefreshFooter();
        }

        private void FillTargets()
        {
            string search = txtTargetSearch.Text;
            lstTargets.Items.Clear();
            bool hasHost = host != null;
            long hostVal = hasHost ? FmCore.EidValue(host.Id) : 0;
            foreach (View t in templates)
            {
                if (hasHost && FmCore.EidValue(t.Id) == hostVal) continue;
                if (!FmCore.RowVisible(t.Name, 0, search, false)) continue;
                bool on;
                targetState.TryGetValue(t.Name, out on);
                CheckBox cb = FmUi.NewCheckBox(t.Name, t, on);
                cb.Checked += FmUi.Safe(OnTargetTicked, "on_target_ticked");
                cb.Unchecked += FmUi.Safe(OnTargetTicked, "on_target_ticked");
                lstTargets.Items.Add(cb);
            }
        }

        private void HarvestTargets()
        {
            foreach (object o in lstTargets.Items)
            {
                var item = o as CheckBox;
                if (item == null) continue;
                string name = item.Content as string;
                if (name != null) targetState[name] = item.IsChecked == true;
            }
        }

        public void OnTargetSearch(object sender, RoutedEventArgs args)
        {
            HarvestTargets();
            searches["targets"].Poke();
        }

        public void OnTargetTicked(object sender, RoutedEventArgs args)
        {
            HarvestTargets();
            RefreshFooter();
        }

        public void OnTargetsAll(object sender, RoutedEventArgs args)
        {
            foreach (object o in lstTargets.Items)
            {
                var item = o as CheckBox;
                if (item != null) item.IsChecked = true;
            }
            HarvestTargets();
            RefreshFooter();
        }

        public void OnTargetsNone(object sender, RoutedEventArgs args)
        {
            foreach (object o in lstTargets.Items)
            {
                var item = o as CheckBox;
                if (item != null) item.IsChecked = false;
            }
            HarvestTargets();
            RefreshFooter();
        }

        // -- column three: Target View Templates / Target Views ---------------
        /// <summary>
        /// 0 = view templates, 1 = ordinary views. Ticks on both are kept,
        /// and a push goes to everything ticked on either.
        /// </summary>
        private void SelectTargetTab(int index)
        {
            tgtIndex = index;
            btnTgtTemplates.Tag = index == 0 ? "on" : "off";
            btnTgtViews.Tag = index == 1 ? "on" : "off";
            FmUi.SetVisible(pnlTgtTemplates, index == 0);
            FmUi.SetVisible(pnlTgtViews, index == 1);
            if (index == 1 && !viewsLoaded) LoadTargetViews();
            RefreshFooter();
        }

        public void OnTgtTemplates(object sender, RoutedEventArgs args) { SelectTargetTab(0); }

        public void OnTgtViews(object sender, RoutedEventArgs args) { SelectTargetTab(1); }

        /// <summary>
        /// Read the project's views. Done on first opening the tab, not at
        /// start-up: a large model has thousands of views.
        /// </summary>
        private void LoadTargetViews()
        {
            HarvestViews();
            viewRows = FmFilters.GetFilterableViews(Doc);
            viewsLoaded = true;
            var live = new HashSet<long>(viewRows.Select(r => r.Idv));
            foreach (long key in viewState.Keys.ToList())
                if (!live.Contains(key)) viewState.Remove(key);
            // hidden types that no longer exist stop mattering; new types arrive
            // ticked, because only the unticked ones are remembered
            var keys = new HashSet<string>(viewRows.Select(r => FmCore.TypeKey(r)));
            var kept = new HashSet<string>();
            foreach (string k in typesHidden)
                if (keys.Contains(k)) kept.Add(k);
            typesHidden = kept;
            BuildViewTypeMenu();
            FillTargetViews();
        }

        // -- the view-type dropdown --------------------------------------------
        private void BuildViewTypeMenu()
        {
            stkViewTypes.Children.Clear();
            List<Tuple<string, string, int>> entries = FmCore.ViewTypeEntries(viewRows);
            foreach (var entry in entries)
            {
                CheckBox cb = FmUi.NewCheckBox(entry.Item2 + "   " + entry.Item3, entry.Item1, !typesHidden.Contains(entry.Item1));
                cb.Margin = new Thickness(0, 2, 0, 2);
                cb.Checked += FmUi.Safe(OnViewTypeTicked, "on_view_type_ticked");
                cb.Unchecked += FmUi.Safe(OnViewTypeTicked, "on_view_type_ticked");
                stkViewTypes.Children.Add(cb);
            }
            txtViewTypes.Text = FmCore.DropdownCaption(entries.Count, typesHidden.Count);
        }

        private static double PopNow() { return DateTime.UtcNow.Ticks / 10000000.0; }

        public void OnViewTypesOpen(object sender, RoutedEventArgs args)
        {
            if (!popWired)
            {
                popWired = true;
                popViewTypes.Closed += FmUi.SafeEvent(ViewTypesClosed, "view_types_closed");
            }
            // the click that closes the popup by landing on the button would
            // otherwise open it straight back up
            if (PopNow() - popClosedAt < 0.3) return;
            try
            {
                popViewTypes.PlacementTarget = btnViewTypes;
                popViewTypes.MinWidth = Math.Max(260, btnViewTypes.ActualWidth);
            }
            catch (Exception) { }
            popViewTypes.IsOpen = !popViewTypes.IsOpen;
        }

        private void ViewTypesClosed(object sender, EventArgs args)
        {
            popClosedAt = PopNow();
        }

        private void ReadViewTypeTicks()
        {
            var hidden = new HashSet<string>();
            foreach (object o in stkViewTypes.Children)
            {
                var cb = o as CheckBox;
                if (cb != null && cb.IsChecked != true) hidden.Add((string)cb.Tag);
            }
            typesHidden = hidden;
            txtViewTypes.Text = FmCore.DropdownCaption(stkViewTypes.Children.Count, hidden.Count);
        }

        public void OnViewTypeTicked(object sender, RoutedEventArgs args)
        {
            if (bulk) return;
            HarvestViews();
            ReadViewTypeTicks();
            searches["views"].Poke();
        }

        private void SetAllViewTypes(bool ticked)
        {
            bulk = true;
            try
            {
                foreach (object o in stkViewTypes.Children)
                {
                    var cb = o as CheckBox;
                    if (cb != null) cb.IsChecked = ticked;
                }
            }
            finally { bulk = false; }
            HarvestViews();
            ReadViewTypeTicks();
            FillTargetViews();
        }

        public void OnViewTypesAll(object sender, RoutedEventArgs args) { SetAllViewTypes(true); }

        public void OnViewTypesNone(object sender, RoutedEventArgs args) { SetAllViewTypes(false); }

        private void FillTargetViews()
        {
            string search = txtViewSearch.Text;
            bool hideLocked = chkHideLocked.IsChecked == true;
            HashSet<long> only = null;
            if (viewsOnlySelected)
            {
                only = new HashSet<long>();
                foreach (var kv in viewState)
                    if (kv.Value) only.Add(kv.Key);
            }
            lstTargetViews.Items.Clear();
            int shown = 0;
            foreach (FmViewRow row in viewRows)
            {
                if (!FmCore.ViewRowVisible(row, typesHidden, search, hideLocked, only)) continue;
                string text = row.Name + "    [" + row.Type + "]";
                if (row.Locked) text += "   - template: " + row.Template;
                bool on;
                viewState.TryGetValue(row.Idv, out on);
                CheckBox cb = FmUi.NewCheckBox(text, row.Idv, !row.Locked && on);
                if (row.Locked)
                {
                    cb.IsEnabled = false;
                    cb.ToolTip = "Filters on this view are set by its view template '" + row.Template +
                                 "'. Push to the template, or untick V/G Filters in that template.";
                }
                else if (!string.IsNullOrEmpty(row.Template))
                {
                    cb.ToolTip = "Template '" + row.Template + "' leaves filters to the view";
                }
                cb.Checked += FmUi.Safe(OnViewTicked, "on_view_ticked");
                cb.Unchecked += FmUi.Safe(OnViewTicked, "on_view_ticked");
                lstTargetViews.Items.Add(cb);
                shown++;
            }
            txtViewCount.Text = shown + " of " + viewRows.Count + " views";
        }

        // -- Current view / Show only selected -------------------------------
        /// <summary>
        /// Tick the view open in Revit now and make sure the list shows it,
        /// whatever the dropdown, search or "only selected" would say.
        /// </summary>
        public void OnCurrentView(object sender, RoutedEventArgs args)
        {
            View view;
            bool sameDoc;
            try
            {
                var uidocNow = UiApp.ActiveUIDocument;
                view = uidocNow != null ? uidocNow.ActiveView : null;
                sameDoc = uidocNow != null && uidocNow.Document.Equals(Doc);
            }
            catch (Exception)
            {
                view = null;
                sameDoc = false;
            }
            if (view == null || !sameDoc)
            {
                txtStatus.Text = "The active view is in another project - switch back to " + Doc.Title + ".";
                return;
            }
            if (!viewsLoaded) LoadTargetViews();
            HarvestViews();

            long idv = FmCore.EidValue(view.Id);
            FmViewRow row = null;
            foreach (FmViewRow r in viewRows)
            {
                if (r.Idv == idv)
                {
                    row = r;
                    break;
                }
            }
            string name = FmFilters.ElementName(Doc, view, "(view)");
            if (row == null)
            {
                txtStatus.Text = "'" + name + "' cannot take filters (sheets, schedules and view templates are not targets).";
                return;
            }

            // make sure nothing is hiding it
            string key = FmCore.TypeKey(row);
            if (typesHidden.Contains(key))
            {
                typesHidden.Remove(key);
                BuildViewTypeMenu();
            }
            if (!FmCore.ViewRowVisible(row, null, txtViewSearch.Text)) txtViewSearch.Text = "";
            if (row.Locked && chkHideLocked.IsChecked == true) chkHideLocked.IsChecked = false;

            if (row.Locked)
            {
                FillTargetViews();
                SelectViewItem(idv);
                txtStatus.Text = "'" + name + "' takes its filters from the template '" + row.Template +
                                 "' - tick that on Target View Templates instead.";
                return;
            }

            viewState[idv] = true;
            FillTargetViews();
            SelectViewItem(idv);
            RefreshFooter();
            txtStatus.Text = "Ticked the current view: " + name;
        }

        private void SelectViewItem(long idv)
        {
            foreach (object o in lstTargetViews.Items)
            {
                var item = o as FrameworkElement;
                if (item != null && item.Tag is long && (long)item.Tag == idv)
                {
                    lstTargetViews.SelectedItem = o;
                    lstTargetViews.ScrollIntoView(o);
                    return;
                }
            }
        }

        public void OnOnlySelected(object sender, RoutedEventArgs args)
        {
            HarvestViews();
            viewsOnlySelected = !viewsOnlySelected;
            PaintOnlySelected();
            FillTargetViews();
        }

        private void PaintOnlySelected()
        {
            bool on = viewsOnlySelected;
            txtOnlySelected.Text = on ? "Showing only selected" : "Show only selected";
            Button btn = btnOnlySelected;
            if (on)
            {
                btn.SetResourceReference(Button.BackgroundProperty, "Sel");
                btn.SetResourceReference(Button.BorderBrushProperty, "Orange");
            }
            else
            {
                btn.SetResourceReference(Button.BackgroundProperty, "Btn");
                btn.SetResourceReference(Button.BorderBrushProperty, "Edge");
            }
        }

        private void HarvestViews()
        {
            foreach (object o in lstTargetViews.Items)
            {
                var item = o as CheckBox;
                if (item != null && item.IsEnabled && item.Tag is long)
                    viewState[(long)item.Tag] = item.IsChecked == true;
            }
        }

        private List<FmViewRow> TickedViewRows()
        {
            var rows = new List<FmViewRow>();
            foreach (FmViewRow r in viewRows)
            {
                bool on;
                if (!r.Locked && viewState.TryGetValue(r.Idv, out on) && on) rows.Add(r);
            }
            return rows;
        }

        public void OnViewSearch(object sender, RoutedEventArgs args)
        {
            HarvestViews();
            searches["views"].Poke();
        }

        public void OnViewTicked(object sender, RoutedEventArgs args)
        {
            HarvestViews();
            RefreshFooter();
        }

        public void OnHideLocked(object sender, RoutedEventArgs args)
        {
            HarvestViews();
            FillTargetViews();
        }

        public void OnViewsAll(object sender, RoutedEventArgs args)
        {
            foreach (object o in lstTargetViews.Items)
            {
                var item = o as CheckBox;
                if (item != null && item.IsEnabled) item.IsChecked = true;
            }
            HarvestViews();
            RefreshFooter();
        }

        public void OnViewsNone(object sender, RoutedEventArgs args)
        {
            foreach (object o in lstTargetViews.Items)
            {
                var item = o as CheckBox;
                if (item != null) item.IsChecked = false;
            }
            HarvestViews();
            RefreshFooter();
        }

        // -- the "Filters" source sub-tab ---------------------------------------
        //  Left: every filter in the project, ticked and moved across with the
        //  arrow. Middle: a table of the staged filters laid out like Revit's own
        //  Filters tab, with each cell editable.
        /// <summary>The staging table's columns: key, heading, width.</summary>
        public static readonly Tuple<string, string, double>[] Columns =
        {
            Tuple.Create("name", "Name", 206.0),
            Tuple.Create("enable", "Enable Filter", 76.0),
            Tuple.Create("visible", "Visibility", 66.0),
            Tuple.Create("projection", "Lines", 94.0),
            Tuple.Create("surface", "Patterns", 94.0),
            Tuple.Create("transparency", "Transparency", 82.0),
            Tuple.Create("cut", "Lines", 94.0),
            Tuple.Create("cutpattern", "Patterns", 94.0),
            Tuple.Create("halftone", "Halftone", 62.0),
        };

        /// <summary>
        /// The table is laid out to its own natural width, so the panel it
        /// sits in is sized to that rather than the table being scrolled.
        /// </summary>
        private double TableWidth()
        {
            double sum = 0.0;
            foreach (var c in Columns) sum += c.Item3;
            return sum;
        }
    }
}
