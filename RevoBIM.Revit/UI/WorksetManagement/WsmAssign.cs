using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using Autodesk.Revit.DB;
using RevoBIM.Tools.WorksetManagement;
using Grid = System.Windows.Controls.Grid;
using Panel = System.Windows.Controls.Panel;
using Visibility = System.Windows.Visibility;
using TextBox = System.Windows.Controls.TextBox;
using Image = System.Windows.Controls.Image;
using Binding = System.Windows.Data.Binding;

namespace RevoBIM.UI.WorksetManagement
{
    /// <summary>
    /// The Workset Assigner tab: one row per workset, in the order they are applied - top wins. Each workset takes EITHER ticked
    /// categories OR one routine template, never both. The working state (order, ticks, routines) is kept per project between
    /// sessions; Save routine / Load routine write and read it as a .wsroutine file. Port of wsm_assign.py.
    /// </summary>
    public class WsmAssignRow
    {
        private const double RowGap = 5.0;
        private const double DrawerItemWidth = 250.0;
        private const string ExpandGlyph = "â–¸", CollapseGlyph = "â–¾", GripGlyph = "â‰¡";
        // (width, star) - must match AssignHeadings in WorksetManagement.xaml
        private static readonly double[] ColWidths = { 22, 28, 24, 2.2, 86, 2.6, 2.1 };
        private static readonly bool[] ColStar = { false, false, false, true, false, true, true };
        private static readonly Dictionary<int, double> MinWidths = new Dictionary<int, double> { { 3, 170 }, { 5, 190 }, { 6, 170 } };

        public readonly WsmAssignTab Tab;
        public readonly WorksetRecord Record;
        public readonly string Name;
        public readonly Border Card;
        private Dictionary<string, CheckBox> _boxes = new Dictionary<string, CheckBox>();
        private Dictionary<string, CheckBox> _drawerBoxes = new Dictionary<string, CheckBox>();
        private bool _suspend;
        private StackPanel _listPanel;
        private readonly TextBlock _grip, _number, _arrow, _label;
        private readonly Grid _routineHost;
        private readonly ToggleButton _toggle;
        private readonly Popup _popup;
        private readonly Border _drawer;
        public readonly WsmUi.HeightDrawer Slider;
        private Button _applyButton;
        private TextBlock _applyLabel;

        public static void GridColumns(Grid grid)
        {
            for (int i = 0; i < ColWidths.Length; i++)
            {
                var column = new ColumnDefinition { Width = new GridLength(ColWidths[i], ColStar[i] ? GridUnitType.Star : GridUnitType.Pixel) };
                double min;
                if (MinWidths.TryGetValue(i, out min)) column.MinWidth = min;
                grid.ColumnDefinitions.Add(column);
            }
        }

        private static T Place<T>(Grid grid, T element, int column, int row = 0, int span = 1) where T : UIElement
        {
            Grid.SetColumn(element, column);
            Grid.SetRow(element, row);
            if (span > 1) Grid.SetColumnSpan(element, span);
            grid.Children.Add(element);
            return element;
        }

        public static Button SmallButton(string text, string key = "WsButton", string tip = null)
        {
            var made = new Button { Content = text, Padding = new Thickness(10, 2, 10, 2), Height = 26, VerticalAlignment = VerticalAlignment.Center };
            WsmUi.Style(made, key);
            if (tip != null) made.ToolTip = tip;
            return made;
        }

        private WsmCore.ModelScan Scan { get { return Tab.Main.Scan; } }
        private WsmRules.AssignState State { get { return Tab.State; } }
        private HashSet<string> Selected()
        {
            HashSet<string> set;
            return State.Categories.TryGetValue(Name, out set) ? set : new HashSet<string>();
        }

        public WsmAssignRow(WsmAssignTab tab, WorksetRecord record)
        {
            Tab = tab; Record = record; Name = record.Name;
            Card = new Border
            {
                BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(4), Margin = new Thickness(0, 0, 0, RowGap),
                Padding = new Thickness(1, 5, 10, 5), Tag = record.Name,
            };
            WsmUi.Res(Card, Border.BackgroundProperty, "CardBrush");
            WsmUi.Res(Card, Border.BorderBrushProperty, "EdgeBrush");
            Card.MouseRightButtonUp += (s, a) => Tab.Main.Safe("the assigner", () => OnRowMenu(a));

            var outer = new Grid();
            outer.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            outer.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            Card.Child = outer;
            var line = new Grid();
            GridColumns(line);
            outer.Children.Add(line);

            _grip = WsmUi.TextBlock(GripGlyph, 16, "MutedBrush", true);
            _grip.HorizontalAlignment = HorizontalAlignment.Center;
            _grip.Cursor = Cursors.SizeNS;
            _grip.Background = WsmUi.Brush("#00000000");
            _grip.ToolTip = "Drag up or down - higher worksets are applied first and win";
            _grip.MouseLeftButtonDown += (s, a) => Tab.Main.Safe("the assigner", () =>
            {
                a.Handled = true;
                if (WsmCore.Txt(Tab.Main.W<TextBox>("AssignSearch").Text).Trim().Length > 0)
                {
                    Tab.Main.Status("Clear the workset filter to drag - the order covers every workset.");
                    return;
                }
                Tab.DragStart(this);
                _grip.CaptureMouse();
            });
            _grip.MouseMove += (s, a) => Tab.Main.Safe("the assigner", () => { if (ReferenceEquals(Tab.Dragging, this)) Tab.DragMove(a); });
            _grip.MouseLeftButtonUp += (s, a) => Tab.Main.Safe("the assigner", () =>
            {
                if (ReferenceEquals(Tab.Dragging, this)) { a.Handled = true; _grip.ReleaseMouseCapture(); }     // LostMouseCapture finishes
            });
            _grip.LostMouseCapture += (s, a) => Tab.Main.Safe("the assigner", () => { if (ReferenceEquals(Tab.Dragging, this)) Tab.DragEnd(); });
            Place(line, _grip, 0);

            _number = WsmUi.TextBlock("", 11, "MutedBrush", true);
            _number.HorizontalAlignment = HorizontalAlignment.Center;
            Place(line, _number, 1);

            _arrow = WsmUi.TextBlock(ExpandGlyph, 13, "BlueTextBrush", true);
            _arrow.HorizontalAlignment = HorizontalAlignment.Center;
            _arrow.Cursor = Cursors.Hand;
            _arrow.Background = WsmUi.Brush("#00000000");
            _arrow.ToolTip = "Show the categories on this workset";
            _arrow.MouseLeftButtonUp += (s, a) => Tab.Main.Safe("the assigner", ToggleDrawer);
            Place(line, _arrow, 2);

            var title = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(4, 0, 0, 0) };
            string colour;
            title.Children.Add(WsmUi.Swatch(Tab.Main.Colours.TryGetValue(record.Iid, out colour) ? colour : WsmCore.NoColour));
            TextBlock name = WsmUi.TextBlock(record.Name, 12, "TextBrush", true);
            name.ToolTip = record.Name;
            title.Children.Add(name);
            title.Cursor = Cursors.Hand;
            title.Background = WsmUi.Brush("#00000000");
            title.MouseLeftButtonUp += (s, a) => Tab.Main.Safe("the assigner", ToggleDrawer);
            Place(line, title, 3);

            TextBlock count = WsmUi.TextBlock(record.Count.ToString(), 12, "OrangeTextBrush", true);
            count.HorizontalAlignment = HorizontalAlignment.Right;
            count.Margin = new Thickness(0, 0, 12, 0);
            Place(line, count, 4);

            // categories picker
            var holder = new Grid { Margin = new Thickness(0, 0, 8, 0) };
            _toggle = new ToggleButton { HorizontalAlignment = HorizontalAlignment.Stretch };
            WsmUi.Style(_toggle, "WsDropToggle");
            _label = WsmUi.TextBlock("", 12, "MutedBrush");
            _toggle.Content = _label;
            _toggle.Checked += (s, a) => Tab.Main.Safe("Opening the category list", () => { BuildPopup(); _popup.IsOpen = true; });
            _toggle.Unchecked += (s, a) => _popup.IsOpen = false;
            holder.Children.Add(_toggle);
            _popup = new Popup { PlacementTarget = _toggle, Placement = PlacementMode.Bottom, StaysOpen = false, AllowsTransparency = true };
            _popup.Closed += (s, a) => _toggle.IsChecked = false;
            holder.Children.Add(_popup);      // in the logical tree, so styles resolve
            Place(line, holder, 5);

            _routineHost = new Grid { Margin = new Thickness(8, 0, 0, 0) };
            Place(line, _routineHost, 6);

            _drawer = new Border
            {
                BorderThickness = new Thickness(0, 1, 0, 0), Margin = new Thickness(9, 6, 0, 0), Padding = new Thickness(12, 8, 4, 6),
                Visibility = Visibility.Collapsed, ClipToBounds = true,
            };
            WsmUi.Res(_drawer, Border.BackgroundProperty, "FieldBrush");
            WsmUi.Res(_drawer, Border.BorderBrushProperty, "EdgeBrush");
            _drawer.MouseRightButtonUp += (s, a) => Tab.Main.Safe("the assigner", () => OnDrawerMenu(a));
            Grid.SetRow(_drawer, 1);
            outer.Children.Add(_drawer);
            // measured at the width it will open to: card less its padding and edge
            Slider = new WsmUi.HeightDrawer(_drawer, () => Card.ActualWidth - 13.0);
            Refresh();
        }

        // ---------------------------------------------------------- state

        /// <summary>Label of the picker and the routine cell, from the state.</summary>
        public void Refresh()
        {
            string mode = State.Mode(Name);
            if (mode == WsmRules.ModeRoutine)
            {
                _toggle.IsEnabled = false;
                _label.Text = "Using a routine";
                WsmUi.Res(_label, TextBlock.ForegroundProperty, "DisabledBrush");
                _toggle.ToolTip = "Take the routine off to tick categories instead";
            }
            else
            {
                _toggle.IsEnabled = true;
                int count = WsmCore.SelectionCount(Selected(), Scan);
                if (count > 0)
                {
                    _label.Text = count + " selected";
                    WsmUi.Res(_label, TextBlock.ForegroundProperty, "BlueTextBrush");
                    var names = new List<string>();
                    foreach (string key in Selected().OrderBy(k => k, StringComparer.Ordinal))
                    {
                        WsmCore.CategoryEntry entry;
                        if (!Scan.ByKey.TryGetValue(key, out entry) || (entry.ParentKey != null && Selected().Contains(entry.ParentKey))) continue;
                        names.Add(entry.ParentKey == null ? entry.Label : Scan.ByKey[entry.ParentKey].Label + " / " + entry.Label);
                    }
                    _toggle.ToolTip = names.Count > 0 ? string.Join("\n", names) : null;
                }
                else
                {
                    _label.Text = "Select categories...";
                    WsmUi.Res(_label, TextBlock.ForegroundProperty, "MutedBrush");
                    _toggle.ToolTip = null;
                }
            }
            BuildRoutineCell(mode);
        }

        private void BuildRoutineCell(string mode)
        {
            _routineHost.Children.Clear();
            if (mode != WsmRules.ModeRoutine)
            {
                Button button = SmallButton("Routine Template", "WsButton", "Pick or make a routine template for this workset");
                button.HorizontalAlignment = HorizontalAlignment.Left;
                button.Click += (s, a) => Tab.Main.Safe("the assigner", () => Tab.OpenManager(Name, null));
                _routineHost.Children.Add(button);
                return;
            }
            string name = State.Routines[Name];
            WsmRules.Template template;
            bool known = Tab.Library.TryGetValue(name, out template);
            var chip = new Border
            {
                BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(12), Padding = new Thickness(10, 2, 4, 2),
                HorizontalAlignment = HorizontalAlignment.Left, Cursor = Cursors.Hand,
            };
            WsmUi.Res(chip, Border.BackgroundProperty, known ? "FieldBrush" : "RedSoftBrush");
            WsmUi.Res(chip, Border.BorderBrushProperty, known ? "BlueBrush" : "RedBrush");
            var line = new StackPanel { Orientation = Orientation.Horizontal };
            TextBlock text = WsmUi.TextBlock(known ? name : name + " (missing)", 12, known ? "BlueTextBrush" : "RedBrush", true);
            text.MaxWidth = 220;
            line.Children.Add(text);
            var remove = new Button { Content = "âœ•", Width = 22, Height = 22, FontSize = 10, Margin = new Thickness(6, 0, 0, 0), ToolTip = "Take the routine off this workset" };
            WsmUi.Style(remove, "WsCloseButton");
            remove.Click += (s, a) => Tab.Main.Safe("the assigner", () =>
            {
                a.Handled = true;
                State.SetRoutine(Name, null);
                Tab.Changed(this);
            });
            line.Children.Add(remove);
            chip.Child = line;
            chip.ToolTip = known ? WsmRules.Describe(template) : "Not in your routine templates - load the routine file again, or pick another.";
            chip.MouseLeftButtonUp += (s, a) => Tab.Main.Safe("the assigner", () => Tab.OpenManager(Name, name));
            _routineHost.Children.Add(chip);
        }

        public void SetNumber(int number) { _number.Text = number.ToString(); }

        // ---------------------------------------------------------- category picker

        private void BuildPopup()
        {
            var shell = new Border { BorderThickness = new Thickness(1), Padding = new Thickness(8), MinWidth = Math.Max(340.0, _toggle.ActualWidth) };
            WsmUi.Res(shell, Border.BackgroundProperty, "FieldBrush");
            WsmUi.Res(shell, Border.BorderBrushProperty, "ChromeBrush");
            var outer = new StackPanel();
            var search = new TextBox { Tag = "Search categories", Height = 30, Margin = new Thickness(0, 0, 0, 6) };
            WsmUi.Style(search, "WsTextBox");
            search.TextChanged += (s, a) => Tab.Main.Safe("the assigner", () => FillList(search.Text));
            outer.Children.Add(search);
            _listPanel = new StackPanel();
            outer.Children.Add(new ScrollViewer
            {
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, MaxHeight = 380, Content = _listPanel,
            });
            TextBlock hint = WsmUi.TextBlock("A category ticked on another workset is not offered here.", 10, "MutedBrush", false, true);
            hint.Margin = new Thickness(2, 6, 2, 0);
            outer.Children.Add(hint);
            shell.Child = outer;
            _popup.Child = shell;
            FillList("");
            WsmUi.Later(Tab.Main.Window, () => search.Focus());
        }

        private void FillList(string needle)
        {
            _listPanel.Children.Clear();
            _boxes = new Dictionary<string, CheckBox>();
            var lines = WsmCore.PickerLines(Name, Tab.Claims, Scan, needle);
            foreach (WsmCore.PickerLine item in lines)
            {
                WsmCore.CategoryEntry entry = item.Entry;
                var box = new CheckBox { Margin = new Thickness(2 + item.Depth * 20, 3, 2, 3), IsChecked = Selected().Contains(entry.Key), IsEnabled = item.Enabled, Tag = entry.Key };
                WsmUi.Style(box, "WsCheck");
                if (!item.Enabled) box.ToolTip = "Some of its Service Types are on another workset - tick them one by one.";
                var line = new StackPanel { Orientation = Orientation.Horizontal };
                line.Children.Add(WsmUi.TextBlock(entry.Label, 12, item.Depth > 0 ? "MutedBrush" : "TextBrush", item.Depth == 0));
                line.Children.Add(WsmUi.TextBlock("   " + entry.Count, 11, "OrangeTextBrush"));
                box.Content = line;
                box.Checked += OnTick;
                box.Unchecked += OnTick;
                _boxes[entry.Key] = box;
                _listPanel.Children.Add(box);
            }
            if (lines.Count == 0) _listPanel.Children.Add(WsmUi.TextBlock("Nothing left to assign.", 11, "MutedBrush"));
        }

        private void OnTick(object sender, RoutedEventArgs args)
        {
            if (_suspend) return;
            _suspend = true;
            try
            {
                var box = (CheckBox)sender;
                HashSet<string> updated = WsmCore.Toggle(Selected(), WsmCore.Txt(box.Tag), box.IsChecked == true, Scan);
                State.SetCategories(Name, updated);
                foreach (var pair in _boxes)
                {
                    bool want = updated.Contains(pair.Key);
                    if ((pair.Value.IsChecked == true) != want) pair.Value.IsChecked = want;
                }
                Tab.Changed(this);
            }
            catch (Exception err) { WsmUi.Report(Tab.Main.Window, "Selection", err); }
            finally { _suspend = false; }
        }

        // ---------------------------------------------------------- the drawer

        public bool IsOpen { get { return Slider.IsOpen; } }

        public void ToggleDrawer()
        {
            if (Slider.IsOpen)
            {
                Slider.Close();
                _arrow.Text = ExpandGlyph;
                Tab.OpenRows.Remove(Name);
            }
            else
            {
                FillDrawer();
                Slider.Open();
                _arrow.Text = CollapseGlyph;
                Tab.OpenRows.Add(Name);
            }
        }

        /// <summary>Open without the slide - after a re-read, for rows that were open.</summary>
        public void ShowOpen()
        {
            FillDrawer();
            Slider.IsOpen = true;
            _drawer.Visibility = Visibility.Visible;
            _arrow.Text = CollapseGlyph;
        }

        private List<string> Picked() { return _drawerBoxes.Where(p => p.Value.IsChecked == true).Select(p => p.Key).ToList(); }

        private void FillDrawer()
        {
            var keep = new HashSet<string>(Picked());
            _drawerBoxes = new Dictionary<string, CheckBox>();
            var outer = new StackPanel();
            var categories = Record.Categories;
            var top = new Grid();
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            int total = categories.Sum(c => c.Value);
            top.Children.Add(WsmUi.TextBlock(categories.Count > 0
                ? categories.Count + " categor" + (categories.Count == 1 ? "y" : "ies") + " on this workset  Â·  " + total + " elements"
                : "No elements on this workset.", 11, "MutedBrush", true));
            var tools = new StackPanel { Orientation = Orientation.Horizontal };
            if (categories.Count > 0)
            {
                Button every = SmallButton("All", "WsButton", "Tick every category");
                every.Margin = new Thickness(0, 0, 6, 0);
                every.Click += (s, a) => Tab.Main.Safe("the assigner", () => TickAll(true));
                tools.Children.Add(every);
                Button none = SmallButton("None", "WsButton", "Untick every category");
                none.Margin = new Thickness(0, 0, 10, 0);
                none.Click += (s, a) => Tab.Main.Safe("the assigner", () => TickAll(false));
                tools.Children.Add(none);
                _applyButton = new Button { Padding = new Thickness(12, 3, 12, 3), Height = 28 };
                WsmUi.Style(_applyButton, "WsOrangeButton");
                var content = new StackPanel { Orientation = Orientation.Horizontal };
                TextBlock icon = WsmUi.TextBlock("â‡„", 13, "OnAccentBrush", true);
                icon.Margin = new Thickness(0, 0, 6, 0);
                content.Children.Add(icon);
                _applyLabel = WsmUi.TextBlock("Apply selected to workset", 12, "OnAccentBrush", true);
                content.Children.Add(_applyLabel);
                _applyButton.Content = content;
                _applyButton.ToolTip = "Move the ticked categories' elements from this workset onto another one, now";
                _applyButton.Click += (s, a) => Tab.Main.Safe("the assigner", ApplySelected);
                tools.Children.Add(_applyButton);
            }
            else _applyButton = null;
            Grid.SetColumn(tools, 1);
            top.Children.Add(tools);
            top.Margin = new Thickness(0, 0, 0, 8);
            outer.Children.Add(top);

            if (categories.Count > 0)
            {
                double biggest = categories[0].Value == 0 ? 1.0 : categories[0].Value;
                var wrap = new WrapPanel { Orientation = Orientation.Horizontal };
                var known = Scan.CategoryIds;
                foreach (var item in categories)
                {
                    string name = item.Key; int count = item.Value;
                    var box = new CheckBox { Width = DrawerItemWidth, Margin = new Thickness(0, 0, 18, 6), Tag = name };
                    WsmUi.Style(box, "WsCheck");
                    bool usable = name != WsmCore.NoCategory && known.ContainsKey(name);
                    box.IsEnabled = usable;
                    if (!usable) box.ToolTip = "Elements with no category can't be picked out by category.";
                    box.IsChecked = usable && keep.Contains(name);
                    var cell = new Grid { Width = DrawerItemWidth - 26 };
                    cell.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                    cell.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                    cell.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                    cell.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                    TextBlock label = WsmUi.TextBlock(name, 12, "TextBrush");
                    label.ToolTip = name;
                    cell.Children.Add(label);
                    TextBlock number = WsmUi.TextBlock(count.ToString(), 12, "OrangeTextBrush", true);
                    number.Margin = new Thickness(8, 0, 0, 0);
                    Grid.SetColumn(number, 1);
                    cell.Children.Add(number);
                    var track = new Border { Height = 3, CornerRadius = new CornerRadius(1.5), Margin = new Thickness(0, 3, 0, 0) };
                    WsmUi.Res(track, Border.BackgroundProperty, "EdgeBrush");
                    Grid.SetRow(track, 1); Grid.SetColumnSpan(track, 2);
                    cell.Children.Add(track);
                    var fill = new Border
                    {
                        Height = 3, CornerRadius = new CornerRadius(1.5), HorizontalAlignment = HorizontalAlignment.Left,
                        Width = Math.Max(2.0, (DrawerItemWidth - 26) * count / biggest), Margin = new Thickness(0, 3, 0, 0),
                    };
                    WsmUi.Res(fill, Border.BackgroundProperty, "OrangeBrush");
                    Grid.SetRow(fill, 1); Grid.SetColumnSpan(fill, 2);
                    cell.Children.Add(fill);
                    box.Content = cell;
                    box.Checked += (s, a) => UpdateApply();
                    box.Unchecked += (s, a) => UpdateApply();
                    _drawerBoxes[name] = box;
                    wrap.Children.Add(box);
                }
                outer.Children.Add(wrap);
            }
            _drawer.Child = outer;
            UpdateApply();
        }

        private void TickAll(bool on)
        {
            foreach (CheckBox box in _drawerBoxes.Values) if (box.IsEnabled) box.IsChecked = on;
            UpdateApply();
        }

        private void UpdateApply()
        {
            if (_applyButton == null) return;
            List<string> picked = Picked();
            _applyButton.IsEnabled = picked.Count > 0;
            var set = new HashSet<string>(picked);
            int count = Record.Categories.Where(c => set.Contains(c.Key)).Sum(c => c.Value);
            _applyLabel.Text = picked.Count > 0 ? "Apply selected to workset (" + count + ")" : "Apply selected to workset";
        }

        public void ApplySelected()
        {
            List<string> picked = Picked();
            if (picked.Count == 0) { Tab.Main.Status("Tick some categories in the drawer first."); return; }
            Tab.MoveCategories(this, picked);
        }

        private void OnDrawerMenu(MouseButtonEventArgs args)
        {
            args.Handled = true;
            if (_drawerBoxes.Count == 0) return;
            var hit = WsmUi.Ancestor<CheckBox>(args.OriginalSource);
            if (hit != null && hit.IsEnabled && hit.IsChecked != true && Picked().Count == 0) hit.IsChecked = true;   // right-click with nothing ticked takes the line
            List<string> picked = Picked();
            ContextMenu menu = WsmUi.ThemedMenu(Tab.Main.Window, new[]
            {
                new WsmUi.MenuEntry(picked.Count > 0 ? "Apply selected to workset..." : "Apply selected to workset (tick some first)", (s, a) => ApplySelected(), picked.Count > 0),
                WsmUi.MenuEntry.Rule(),
                new WsmUi.MenuEntry("Tick all", (s, a) => TickAll(true)),
                new WsmUi.MenuEntry("Tick none", (s, a) => TickAll(false), picked.Count > 0),
            });
            menu.PlacementTarget = _drawer;
            menu.IsOpen = true;
        }

        // ---------------------------------------------------------- row menu

        private void OnRowMenu(MouseButtonEventArgs args)
        {
            if (args.Handled) return;
            args.Handled = true;
            WsmAssignTab tab = Tab;
            var order = tab.State.Order;
            int index = Math.Max(0, order.IndexOf(Name));
            int last = order.Count - 1;
            string mode = tab.State.Mode(Name);
            var items = new List<WsmUi.MenuEntry>();
            if (IsOpen && Picked().Count > 0)
            {
                items.Add(new WsmUi.MenuEntry("Apply selected to workset...", (s, a) => ApplySelected()));
                items.Add(WsmUi.MenuEntry.Rule());
            }
            items.Add(new WsmUi.MenuEntry("Move to top", (s, a) => tab.Move(Name, 0), index > 0));
            items.Add(new WsmUi.MenuEntry("Move up", (s, a) => tab.Move(Name, index - 1), index > 0));
            items.Add(new WsmUi.MenuEntry("Move down", (s, a) => tab.Move(Name, index + 1), index < last));
            items.Add(new WsmUi.MenuEntry("Move to bottom", (s, a) => tab.Move(Name, last), index < last));
            items.Add(WsmUi.MenuEntry.Rule());
            items.Add(new WsmUi.MenuEntry(IsOpen ? "Hide categories" : "Show categories on this workset", (s, a) => ToggleDrawer()));
            items.Add(new WsmUi.MenuEntry("Routine Template...", (s, a) => tab.OpenManager(Name, null)));
            items.Add(new WsmUi.MenuEntry("Clear this workset", (s, a) => tab.ClearRow(Name), mode != WsmRules.ModeNone));
            ContextMenu menu = WsmUi.ThemedMenu(tab.Main.Window, items);
            menu.PlacementTarget = Card;
            menu.IsOpen = true;
        }

        /// <summary>Show where a dragged row would land: "top", "bottom" or null.</summary>
        public void Mark(string where)
        {
            if (where == null)
            {
                Card.BorderThickness = new Thickness(1);
                WsmUi.Res(Card, Border.BorderBrushProperty, "EdgeBrush");
                Card.Margin = new Thickness(0, 0, 0, RowGap);
            }
            else if (where == "top")
            {
                Card.BorderThickness = new Thickness(1, 3, 1, 1);
                WsmUi.Res(Card, Border.BorderBrushProperty, "BlueBrush");
                Card.Margin = new Thickness(0, -2, 0, RowGap);
            }
            else
            {
                Card.BorderThickness = new Thickness(1, 1, 1, 3);
                WsmUi.Res(Card, Border.BorderBrushProperty, "BlueBrush");
                Card.Margin = new Thickness(0, 0, 0, RowGap - 2);
            }
        }

        public static double Gap { get { return RowGap; } }
    }

    public class WsmAssignTab
    {
        private const double ScrollEdge = 28.0, ScrollStep = 14.0;
        private const string FileFilter = "Workset routine (*.wsroutine)|*.wsroutine|All files (*.*)|*.*";

        public readonly WsmWindow Main;
        public List<WsmAssignRow> Rows = new List<WsmAssignRow>();
        private Dictionary<string, WsmAssignRow> _byName = new Dictionary<string, WsmAssignRow>();
        public readonly HashSet<string> OpenRows = new HashSet<string>();
        public Dictionary<string, string> Claims = new Dictionary<string, string>();
        public WsmAssignRow Dragging;
        private int? _dropAt;
        public WsmRoutineManager Manager;
        public Dictionary<string, WsmRules.Template> Library;
        public WsmRules.AssignState State = new WsmRules.AssignState();
        private bool _loadedState;
        private readonly System.Windows.Threading.DispatcherTimer _saveTimer;

        public WsmAssignTab(WsmWindow main)
        {
            Main = main;
            Library = WsmRules.LoadLibrary();
            _saveTimer = WsmUi.Debounce(400, SaveNow);
            ((TextBox)main.W<TextBox>("AssignSearch")).TextChanged += (s, a) => Main.Safe("the assigner", FilterRows);
            main.W<Button>("RefreshAssignButton").Click += (s, a) => Main.Safe("Refresh", Main.OnRefresh);
            main.W<Button>("SortAssignButton").Click += (s, a) => Main.Safe("the assigner", OnSort);
            main.W<Button>("SaveRoutineButton").Click += (s, a) => Main.Safe("Save routine", OnSaveRoutine);
            main.W<Button>("LoadRoutineButton").Click += (s, a) => Main.Safe("Load routine", OnLoadRoutine);
            main.W<Button>("RoutineManagerButton").Click += (s, a) => Main.Safe("the assigner", () => OpenManager(null, null));
            main.W<Button>("ClearAssignButton").Click += (s, a) => Main.Safe("the assigner", OnClear);
            main.W<Button>("ApplyAssignButton").Click += (s, a) => Main.Safe("the assigner", OnApply);
        }

        public static WsmRules.AssignState CopyState(WsmRules.AssignState state)
        {
            var made = new WsmRules.AssignState { Order = new List<string>(state.Order), Routines = new Dictionary<string, string>(state.Routines) };
            foreach (var pair in state.Categories) made.Categories[pair.Key] = new HashSet<string>(pair.Value);
            return made;
        }

        // ---------------------------------------------------------- reading

        public List<string> Names() { return Main.Records.Select(r => r.Name).ToList(); }

        /// <summary>After every read: keep the state for worksets still here, put the rows back in order, reopen the drawers that were open.</summary>
        public void Refresh()
        {
            List<string> names = Names();
            if (!_loadedState)
            {
                State = WsmRules.LoadState(Main.Title, names, Library);
                _loadedState = true;
            }
            var known = new HashSet<string>(Main.Scan.ByKey.Keys);
            foreach (string workset in State.Categories.Keys.ToList())
            {
                if (!names.Contains(workset)) { State.Categories.Remove(workset); continue; }
                State.SetCategories(workset, State.Categories[workset].Where(known.Contains).ToList());
            }
            foreach (string workset in State.Routines.Keys.ToList())
                if (!names.Contains(workset)) State.Routines.Remove(workset);
            State.Order = WsmRules.SyncOrder(State.Order, names);
            OpenRows.RemoveWhere(n => !names.Contains(n));
            RebuildClaims();
            BuildRows();
        }

        private void RebuildClaims() { Claims = WsmCore.BuildClaims(State.Categories, Main.Scan); }

        private void BuildRows()
        {
            var host = Main.W<Panel>("AssignHost");
            host.Children.Clear();
            Rows = new List<WsmAssignRow>();
            _byName = new Dictionary<string, WsmAssignRow>();
            var records = new Dictionary<string, WorksetRecord>();
            foreach (WorksetRecord r in Main.Records) records[r.Name] = r;
            if (records.Count == 0)
            {
                host.Children.Add(WsmUi.TextBlock("No worksets in this model.", 12, "MutedBrush"));
                UpdateStatus();
                return;
            }
            foreach (string name in State.Order)
            {
                WorksetRecord record;
                if (!records.TryGetValue(name, out record)) continue;
                var row = new WsmAssignRow(this, record);
                Rows.Add(row);
                _byName[name] = row;
                host.Children.Add(row.Card);
                if (OpenRows.Contains(name)) row.ShowOpen();
            }
            NumberRows();
            UpdateSortLabel();
            FilterRows();
            UpdateStatus();
        }

        private void NumberRows() { for (int i = 0; i < Rows.Count; i++) Rows[i].SetNumber(i + 1); }

        private void FilterRows()
        {
            string needle = WsmCore.Txt(Main.W<TextBox>("AssignSearch").Text);
            foreach (WsmAssignRow row in Rows)
                row.Card.Visibility = WsmCore.TextMatch(row.Name, needle) ? Visibility.Visible : Visibility.Collapsed;
        }

        // ---------------------------------------------------------- changes

        public void Changed(WsmAssignRow row = null)
        {
            RebuildClaims();
            if (row != null) row.Refresh(); else foreach (WsmAssignRow each in Rows) each.Refresh();
            UpdateStatus();
            SaveLater();
        }

        public void SaveLater() { WsmUi.Kick(_saveTimer); }

        public void SaveNow()
        {
            try { _saveTimer.Stop(); } catch (Exception) { }
            if (_loadedState) WsmRules.SaveState(Main.Title, State);
        }

        public void UpdateStatus()
        {
            var active = State.Active();
            int byRoutine = active.Count(w => State.Mode(w) == WsmRules.ModeRoutine);
            int byCategories = active.Count - byRoutine;
            Main.W<TextBlock>("ApplyAssignLabel").Text = active.Count > 0 ? "Apply to worksets (" + active.Count + ")" : "Apply to worksets";
            Main.W<Button>("ApplyAssignButton").IsEnabled = active.Count > 0;
            Main.W<Button>("ClearAssignButton").IsEnabled = active.Count > 0;
            if (Main.Tab != "assign") return;
            if (active.Count > 0)
                Main.Status(active.Count + " workset(s) set up - " + byCategories + " by categories, " + byRoutine + " by routine. Applied top to bottom; a workset higher up keeps what it catches.");
            else
                Main.Status(Main.Records.Count + " worksets, " + Main.Scan.Total + " model elements in " + Main.Scan.Entries.Count + " categories. Tick categories or give a workset a routine.");
        }

        public void Move(string name, int index)
        {
            State.Order = WsmRules.MoveItem(State.Order, name, index);
            Reorder();
        }

        private void OnSort()
        {
            var ascending = WsmCore.SortedNatural(State.Order);
            if (State.Order.SequenceEqual(ascending))
            {
                ascending.Reverse();
                State.Order = ascending;
                Main.Status("Worksets in name order, Z-A - applied in this order.");
            }
            else
            {
                State.Order = ascending;
                Main.Status("Worksets in name order, A-Z - applied in this order.");
            }
            Reorder();
        }

        private void Reorder()
        {
            var host = Main.W<Panel>("AssignHost");
            host.Children.Clear();
            Rows = State.Order.Where(_byName.ContainsKey).Select(n => _byName[n]).ToList();
            foreach (WsmAssignRow row in Rows) host.Children.Add(row.Card);
            NumberRows();
            UpdateSortLabel();
            SaveLater();
        }

        private void UpdateSortLabel()
        {
            Main.W<TextBlock>("SortAssignLabel").Text = State.Order.SequenceEqual(WsmCore.SortedNatural(State.Order)) ? "Sort Z-A" : "Sort A-Z";
        }

        public void ClearRow(string name)
        {
            State.Clear(name);
            WsmAssignRow row;
            Changed(_byName.TryGetValue(name, out row) ? row : null);
        }

        private void OnClear()
        {
            if (State.Active().Count == 0) return;
            if (!WsmUi.Confirm(Main.Window, "Clear all", "Untick every category and take every routine off? The order is kept.", null, "Clear all", "Keep", "WsRedButton", 460, 210)) return;
            State.Clear();
            Changed();
        }

        // ---------------------------------------------------------- dragging

        public void DragStart(WsmAssignRow row)
        {
            Dragging = row; _dropAt = null;
            row.Card.Opacity = 0.55;
        }

        public void DragMove(MouseEventArgs args)
        {
            var host = Main.W<Panel>("AssignHost");
            var scroller = Main.W<ScrollViewer>("AssignScroller");
            try
            {
                double edge = args.GetPosition(scroller).Y;
                if (edge < ScrollEdge) scroller.ScrollToVerticalOffset(Math.Max(0.0, scroller.VerticalOffset - ScrollStep));
                else if (edge > scroller.ActualHeight - ScrollEdge) scroller.ScrollToVerticalOffset(scroller.VerticalOffset + ScrollStep);
            }
            catch (Exception) { }
            var heights = Rows.Select(r => r.Card.ActualHeight + WsmAssignRow.Gap).ToList();
            int index = WsmRules.DropIndex(heights, args.GetPosition(host).Y);
            if (_dropAt == index) return;
            _dropAt = index;
            foreach (WsmAssignRow row in Rows) row.Mark(null);
            int current = Rows.IndexOf(Dragging);
            if (index == current || index == current + 1) return;          // would land where it is
            if (index < Rows.Count) Rows[index].Mark("top");
            else if (Rows.Count > 0) Rows[Rows.Count - 1].Mark("bottom");
        }

        public void DragEnd()
        {
            WsmAssignRow row = Dragging; Dragging = null;
            int? index = _dropAt; _dropAt = null;
            foreach (WsmAssignRow each in Rows) each.Mark(null);
            if (row == null) return;
            row.Card.Opacity = 1.0;
            if (!index.HasValue) return;
            var before = new List<string>(State.Order);
            State.Order = WsmRules.Landing(State.Order, row.Name, index.Value);
            if (!State.Order.SequenceEqual(before))
            {
                Reorder();
                Main.Status(row.Name + " is now number " + (State.Order.IndexOf(row.Name) + 1) + " - applied in this order.");
            }
        }

        // ---------------------------------------------------------- routines

        public void OpenManager(string workset, string template)
        {
            try
            {
                if (Manager != null && Manager.Alive()) { Manager.FocusOn(workset, template); return; }
                Manager = new WsmRoutineManager(this, workset, template);
                Manager.Show();
            }
            catch (Exception err) { WsmUi.Report(Main.Window, "Opening the Routine Template Manager", err); }
        }

        /// <summary>From the manager: put a routine on a workset - replacing its ticks, after asking.</summary>
        public bool UseRoutine(string workset, string name)
        {
            if (!_byName.ContainsKey(workset)) return false;
            Window owner = Manager != null && Manager.Alive() ? Manager.Window : Main.Window;
            if (State.Mode(workset) == WsmRules.ModeCategories)
            {
                int count = WsmCore.SelectionCount(State.Categories[workset], Main.Scan);
                if (!WsmUi.Confirm(owner, "Routine Template",
                        workset + " has " + count + " ticked categor" + (count == 1 ? "y" : "ies") + ". A workset takes either ticked categories or a routine - replace the ticks with '" + name + "'?",
                        null, "Use the routine", "Keep the ticks", "WsOrangeButton", 520, 230)) return false;
            }
            State.SetRoutine(workset, name);
            Changed(_byName[workset]);
            Main.Status(workset + " will use the routine '" + name + "'.");
            return true;
        }

        /// <summary>The manager saved the library: follow renames, drop deleted ones.</summary>
        public void LibraryChanged(Dictionary<string, string> renamed = null, IEnumerable<string> dropped = null)
        {
            if (renamed != null) foreach (var pair in renamed) State.RenameTemplate(pair.Key, pair.Value);
            if (dropped != null) foreach (string name in dropped) State.DropTemplate(name);
            Changed();
        }

        // ---------------------------------------------------------- apply in order

        private void OnApply()
        {
            if (State.Active().Count == 0) { Main.Status("Nothing set up - tick categories or give a workset a routine."); return; }
            WsmRules.AssignState state = CopyState(State);
            var library = new Dictionary<string, WsmRules.Template>(Library);
            WsmWindow main = Main;
            main.RunJob("work out the moves", uiapp =>
            {
                WsmCore.Log log = main.NewLog();
                WsmCore.ModelScan scan;
                List<WorksetRecord> records = WsmRevit.ReadModel(main.Doc, main.Settings, out scan);
                AssignPreview preview = WsmRevit.AssignPreviewFor(main.Doc, scan, state, library, log);
                log.Write("Workset Assigner - preview");
                return new object[] { preview, records, scan };
            }, payload =>
            {
                var p = (object[])payload;
                main.ApplyRead((List<WorksetRecord>)p[1], (WsmCore.ModelScan)p[2], true);
                ConfirmApply((AssignPreview)p[0]);
            }, "Working out what moves - top to bottom...");
        }

        private void ConfirmApply(AssignPreview preview)
        {
            var lines = new List<string>(preview.Lines);
            if (preview.Problems.Count > 0)
            {
                lines.Add("");
                lines.Add("Left out:");
                lines.AddRange(preview.Problems.Select(p => "   " + p));
            }
            if (preview.Total == 0)
            {
                var all = new List<string> { "Nothing to move - every element is already on its workset.", "" };
                all.AddRange(lines);
                WsmUi.Message(Main.Window, "Workset Assigner", all, 620, 380);
                Main.Status("Nothing to move.");
                return;
            }
            if (!WsmUi.Confirm(Main.Window, "Apply to worksets", preview.Total + " element(s) will move, worked out top to bottom:", lines,
                               "Move " + preview.Total, "Cancel", "WsGreenButton", 680, 460))
            {
                Main.Status("Nothing moved.");
                return;
            }
            List<AssignMove> moves = preview.Moves;
            bool auto = Main.AutoEditable();
            WsmWindow main = Main;
            main.RunJob("apply to worksets", uiapp =>
            {
                WsmCore.Log log = main.NewLog();
                AssignResult result = WsmRevit.ApplyAssignments(main.Doc, moves, auto, log);
                log.Write("Workset Assigner - apply");
                WsmCore.ModelScan scan = null;
                List<WorksetRecord> records = result.Error.Length > 0 ? null : WsmRevit.ReadModel(main.Doc, main.Settings, out scan);
                return new object[] { result, records, scan };
            }, payload =>
            {
                var p = (object[])payload;
                Report((AssignResult)p[0], (List<WorksetRecord>)p[1], (WsmCore.ModelScan)p[2], "Workset Assigner");
            }, "Moving elements onto worksets...");
        }

        /// <summary>'Apply selected to workset' in a drawer: straight onto another workset, no staging.</summary>
        public void MoveCategories(WsmAssignRow row, List<string> picked)
        {
            WsmWindow main = Main;
            var choices = main.Records.Where(r => r.Iid != row.Record.Iid).Select(r =>
            {
                string colour;
                return new WsmUi.WorksetChoice { Iid = r.Iid, Name = r.Name, Count = r.Count, Colour = main.Colours.TryGetValue(r.Iid, out colour) ? colour : WsmCore.NoColour };
            }).ToList();
            if (choices.Count == 0) { main.Status("There is no other workset to move them to."); return; }
            var set = new HashSet<string>(picked);
            int count = row.Record.Categories.Where(c => set.Contains(c.Key)).Sum(c => c.Value);
            int? target = WsmUi.ChooseWorkset(Main.Window, "Apply selected to workset",
                "Move " + count + " element(s) in " + picked.Count + " categor" + (picked.Count == 1 ? "y" : "ies") + " from " + row.Name + " onto:", choices, "Move here");
            if (!target.HasValue) return;
            string targetName = choices.First(c => c.Iid == target.Value).Name;
            int source = row.Record.Iid, targetIid = target.Value;
            var categoryIds = picked.Where(main.Scan.CategoryIds.ContainsKey).Select(n => (ElementId)main.Scan.CategoryIds[n]).ToList();
            bool auto = main.AutoEditable();
            main.RunJob("apply selected to workset", uiapp =>
            {
                WsmCore.Log log = main.NewLog();
                List<ElementId> ids = WsmRevit.ElementsOnWorkset(main.Doc, source, categoryIds);
                var move = new AssignMove { WsIid = targetIid, WsName = targetName, Ids = ids };
                AssignResult result = WsmRevit.ApplyAssignments(main.Doc, new List<AssignMove> { move }, auto, log);
                log.Write("Apply selected to workset");
                WsmCore.ModelScan scan = null;
                List<WorksetRecord> records = result.Error.Length > 0 ? null : WsmRevit.ReadModel(main.Doc, main.Settings, out scan);
                return new object[] { result, records, scan };
            }, payload =>
            {
                var p = (object[])payload;
                Report((AssignResult)p[0], (List<WorksetRecord>)p[1], (WsmCore.ModelScan)p[2], "Apply selected to workset");
            }, "Moving " + string.Join(", ", picked) + " onto " + targetName + "...");
        }

        private void Report(AssignResult result, List<WorksetRecord> records, WsmCore.ModelScan scan, string title)
        {
            if (result.Error.Length > 0)
            {
                WsmUi.Message(Main.Window, title, new[] { "Nothing was written.", "", result.Error }, 520, 280);
                Main.Status("Rolled back: " + result.Error);
                return;
            }
            Main.ApplyRead(records, scan, true);
            var lines = new List<string> { result.Moved + " element(s) moved, " + result.Already + " already on the right workset.", "" };
            lines.AddRange(result.Lines);
            bool trouble = result.Owned > 0 || result.NotBorrowed > 0 || result.Refused > 0;
            if (trouble) lines.Add("");
            if (result.Owned > 0)
            {
                string owners = string.Join(", ", result.Owners.OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => p.Key + " (" + p.Value + ")"));
                lines.Add(result.Owned + " element(s) are borrowed by someone else and were left alone: " + owners + ".");
            }
            if (result.NotBorrowed > 0)
                lines.Add(result.NotBorrowed + " element(s) could not be borrowed - usually they changed in central since you last synchronised.");
            if (result.Refused > 0)
                lines.Add(result.Refused + " element(s) would not take a workset - group members and elements hosted by another are the usual reason.");
            string show; Main.Settings.TryGetValue("show_results", out show);
            if (show == "always" || (show != "never" && trouble)) WsmUi.Message(Main.Window, title, lines);
            Main.Status(result.Moved + " element(s) moved.");
        }

        // ---------------------------------------------------------- routine files

        private string SettingDir(string key)
        {
            string folder; Main.Settings.TryGetValue(key, out folder);
            return !string.IsNullOrEmpty(folder) && Directory.Exists(folder) ? folder : null;
        }

        private void OnSaveRoutine()
        {
            if (State.Active().Count == 0 &&
                !WsmUi.Confirm(Main.Window, "Save routine", "Nothing is ticked and no routine is set - save just the order?", null, "Save", "Cancel", "WsOrangeButton", 460, 210)) return;
            var dialog = new Microsoft.Win32.SaveFileDialog
            {
                Title = "Save the workset routine", Filter = FileFilter, DefaultExt = WsmRules.FileExtension,
                FileName = WsmCore.ProjectKey(Main.Title) + " - Workset routine" + WsmRules.FileExtension,
            };
            string folder = SettingDir("last_routine_dir");
            if (folder != null) dialog.InitialDirectory = folder;
            if (dialog.ShowDialog(Main.Window) != true) return;
            string path = dialog.FileName;
            var lines = WsmRules.RoutineLines(State, Library, Main.Title, DateTime.Now.ToString("yyyy-MM-dd HH:mm"));
            if (!WsmCore.WriteLines(path, lines)) { Main.Status("Could not write " + path + "."); return; }
            Main.Settings["last_routine_dir"] = Path.GetDirectoryName(path);
            Main.SaveSettings();
            Main.Status("Routine saved to " + path + ".");
        }

        private void OnLoadRoutine()
        {
            var dialog = new Microsoft.Win32.OpenFileDialog { Title = "Open a workset routine", Filter = FileFilter };
            string folder = SettingDir("last_routine_dir");
            if (folder != null) dialog.InitialDirectory = folder;
            if (dialog.ShowDialog(Main.Window) != true) return;
            string path = dialog.FileName;
            WsmRules.RoutineFile parsed = WsmRules.ParseRoutine(WsmCore.ReadLines(path));
            if (parsed.Rows.Count == 0)
            {
                var text = new List<string> { "Could not read that file:", "" };
                text.AddRange(parsed.Problems);
                WsmUi.Message(Main.Window, "Load routine", text, 560, 300);
                return;
            }
            List<string> names = Names();
            Dictionary<string, string> mapping = WsmRules.SuggestMapping(parsed.Rows.Select(r => r.Workset).ToList(), names);
            bool exact = parsed.Rows.All(r => { string m; return mapping.TryGetValue(r.Workset, out m) && m == r.Workset; });
            if (!exact)
            {
                mapping = MapWorksets(Main.Window, parsed, mapping, Main);
                if (mapping == null) return;
            }
            if (State.Active().Count > 0 &&
                !WsmUi.Confirm(Main.Window, "Load routine", "This replaces the ticks, routines and order you have now.", null, "Load", "Cancel", "WsOrangeButton", 460, 210)) return;
            Dictionary<string, string> renamed = WsmRules.MergeTemplates(Library, parsed.Templates);
            if (parsed.Templates.Count > 0) WsmRules.SaveLibrary(Library);
            State.Clear();
            List<string> skipped = WsmRules.ApplyRoutine(State, parsed, mapping, renamed, new HashSet<string>(Main.Scan.ByKey.Keys), names);
            Main.Settings["last_routine_dir"] = Path.GetDirectoryName(path);
            Main.SaveSettings();
            RebuildClaims();
            BuildRows();
            SaveLater();
            if (Manager != null && Manager.Alive()) Manager.Reload();
            var notes = new List<string>(skipped);
            notes.AddRange(parsed.Problems);
            var brought = renamed.Where(p => p.Key != p.Value).OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => p.Key + " (as '" + p.Value + "')").ToList();
            if (brought.Count > 0) notes.Add("Routine templates that clashed with yours came in as: " + string.Join(", ", brought));
            if (notes.Count > 0)
            {
                var text = new List<string> { "Loaded, except:" };
                text.AddRange(notes.Select(n => "   " + n));
                WsmUi.Message(Main.Window, "Load routine", text, 600, 360);
            }
            Main.Status("Routine loaded from " + Path.GetFileName(path) + " - press Apply to worksets to write it.");
        }

        public void Closing()
        {
            SaveNow();
            if (Manager != null) { try { Manager.Close(); } catch (Exception) { } }
        }

        // ================================================================ mapping

        /// <summary>Some worksets in the file are not in this model by name: choose a workset here for each, or skip it.</summary>
        public static Dictionary<string, string> MapWorksets(Window owner, WsmRules.RoutineFile parsed, Dictionary<string, string> suggested, WsmWindow main)
        {
            var dialog = new WsmUi.Dialog(owner, "Match the worksets", 720, 600);
            dialog.Text("The routine came from " + (parsed.Project.Length > 0 ? parsed.Project : "another model") + ". Choose which workset in this model takes each one - matched ones are filled in for you.");
            var choices = new List<WsmUi.Choice> { new WsmUi.Choice(null, "(skip)") };
            choices.AddRange(main.Records.Select(r => new WsmUi.Choice(r.Name, r.Name, r.Count + " elements")));
            var pickers = new Dictionary<string, WsmUi.PickButton>();
            var table = new Grid();
            table.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            table.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(26) });
            table.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            table.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            foreach (var heading in new[] { Tuple.Create(0, "In the file"), Tuple.Create(2, "In this model") })
            {
                TextBlock block = WsmUi.TextBlock(heading.Item2, 11, "MutedBrush", true);
                block.Margin = new Thickness(0, 0, 0, 6);
                Grid.SetColumn(block, heading.Item1);
                table.Children.Add(block);
            }
            for (int index = 0; index < parsed.Rows.Count; index++)
            {
                WsmRules.RoutineRow row = parsed.Rows[index];
                table.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                var left = new StackPanel { Margin = new Thickness(0, 3, 0, 3), VerticalAlignment = VerticalAlignment.Center };
                left.Children.Add(WsmUi.TextBlock(row.Workset, 12, "TextBrush", true));
                string what = row.Mode == WsmRules.ModeCategories ? row.Keys.Count + " categor" + (row.Keys.Count == 1 ? "y" : "ies")
                            : row.Mode == WsmRules.ModeRoutine ? "routine: " + row.Routine : "nothing set - order only";
                left.Children.Add(WsmUi.TextBlock(what, 11, "MutedBrush"));
                Grid.SetRow(left, index + 1);
                table.Children.Add(left);
                TextBlock arrow = WsmUi.TextBlock("â†’", 14, "BlueTextBrush", true);
                arrow.HorizontalAlignment = HorizontalAlignment.Center;
                Grid.SetRow(arrow, index + 1); Grid.SetColumn(arrow, 1);
                table.Children.Add(arrow);
                string current;
                suggested.TryGetValue(row.Workset, out current);
                var picker = new WsmUi.PickButton(choices, current, search: true, placeholder: "(skip)");
                picker.Element.Margin = new Thickness(0, 3, 0, 3);
                picker.Element.VerticalAlignment = VerticalAlignment.Center;
                Grid.SetRow(picker.Element, index + 1); Grid.SetColumn(picker.Element, 2);
                table.Children.Add(picker.Element);
                pickers[row.Workset] = picker;
            }
            dialog.Add(table);
            TextBlock warning = WsmUi.TextBlock("", 11, "RedBrush", false, true);
            warning.Margin = new Thickness(0, 8, 0, 0);
            dialog.Add(warning);
            dialog.Button("Cancel", "WsButton", (s, a) => dialog.CloseWith(null));
            dialog.Button("Load", "WsGreenButton", (s, a) =>
            {
                var mapping = pickers.ToDictionary(p => p.Key, p => p.Value.Value as string);
                var problems = WsmRules.MappingProblems(mapping);
                if (problems.Count > 0)
                {
                    warning.Text = "One workset here can take only one from the file: " + string.Join("; ", problems);
                    return;
                }
                dialog.CloseWith(mapping);
            }, 120);
            return dialog.Show() as Dictionary<string, string>;
        }
    }
}


