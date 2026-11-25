using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using Autodesk.Revit.DB;
using RevoBIM.Helpers;
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
    /// The Routine Template Manager: Revit's Filters dialog, for workset assignment. A list of routine templates on the
    /// left, the categories each one ticks in the middle, and its rules on the right - AND / OR, nested sets, each rule
    /// limited to all the selected categories or to one of them, a parameter, an operator and a value. Modeless and
    /// owned by the main window. Port of wsm_routine.py.
    /// </summary>
    public class WsmRoutineManager
    {
        private const string AllLabel = "All Selected Categories";
        private const int MaxDepth = 4;

        private readonly WsmAssignTab _tab;
        private readonly WsmWindow _main;
        public Dictionary<string, WsmRules.Template> Library;
        private bool _closed;
        private WsmRules.Template _current;
        private int _suspend;
        private readonly Dictionary<string, List<ParamInfo>> _params = new Dictionary<string, List<ParamInfo>>();
        private readonly Dictionary<string, List<string>> _values = new Dictionary<string, List<string>>();
        private string _wanted;
        private Dictionary<string, CheckBox> _categoryBoxes = new Dictionary<string, CheckBox>();
        public readonly Window Window;
        private readonly WsmUi.Chrome _chrome;
        private readonly WsmUi.PickButton _forPicker;
        private readonly System.Windows.Threading.DispatcherTimer _saveTimer;

        private T W<T>(string name) where T : class { return Window.FindName(name) as T; }
        private void Safe(string where, Action action) { WsmUi.Try(() => Window, where, action); }

        public WsmRoutineManager(WsmAssignTab tab, string workset, string template)
        {
            _tab = tab; _main = tab.Main; Library = tab.Library;
            Window = WsmUi.LoadWindow("RoutineManager.xaml");
            _chrome = new WsmUi.Chrome(Window, W<FrameworkElement>("HeaderBar"), W<Panel>("GripLayer"), W<Button>("FullScreenButton"),
                new object[] { W<object>("ThemeButton"), W<object>("CloseButton"), W<object>("LogoBlock"), W<object>("DebugButton") }, W<Button>("ShrinkButton"));
            var icon = WsmUi.LoadIcon();
            if (icon != null) W<System.Windows.Controls.Image>("HeaderIcon").Source = icon;
            W<TextBlock>("VersionText").Text = "v" + WsmCore.Version;
            EggHook.Attach(Window, () => WsmUi.Current, W<UIElement>("LogoBlock"));
            Retheme();

            var choices = _main.Records.Select(r => new WsmUi.Choice(r.Name, r.Name, r.Count.ToString())).ToList();
            _forPicker = new WsmUi.PickButton(choices, workset, v => Safe("Choosing a workset", UpdateContext), true, "Choose a workset...");
            W<Panel>("ForHost").Children.Add(_forPicker.Element);

            _saveTimer = WsmUi.Debounce(500, SaveNow);
            Wire();
            string used = null;
            if (workset != null) tab.State.Routines.TryGetValue(workset, out used);
            FillTemplates(template ?? used);
            UpdateContext();
        }

        private void Wire()
        {
            W<Button>("CloseButton").Click += (s, a) => Window.Close();
            W<Button>("DoneButton").Click += (s, a) => Window.Close();
            W<Button>("ThemeButton").Click += (s, a) => Safe("Theme", _main.OnTheme);
            W<Button>("DebugButton").Click += (s, a) => Safe("Debug report", _main.OnDebugReport);
            W<TextBox>("TemplateSearch").TextChanged += (s, a) => Safe("Templates", () => FillTemplates(CurrentName()));
            W<ListBox>("TemplateList").SelectionChanged += (s, a) => Safe("Templates", OnPickTemplate);
            W<ListBox>("TemplateList").MouseDoubleClick += (s, a) => Safe("Rename", OnRename);
            W<Button>("NewButton").Click += (s, a) => Safe("New routine template", OnNew);
            W<Button>("DuplicateButton").Click += (s, a) => Safe("Duplicate", OnDuplicate);
            W<Button>("RenameButton").Click += (s, a) => Safe("Rename", OnRename);
            W<Button>("DeleteButton").Click += (s, a) => Safe("Delete", OnDelete);
            W<TextBox>("CategorySearch").TextChanged += (s, a) => Safe("Categories", FillCategories);
            W<CheckBox>("HideUncheckedCheck").Click += (s, a) => Safe("Categories", FillCategories);
            W<Button>("CheckAllButton").Click += (s, a) => Safe("Categories", () => CheckShown(true));
            W<Button>("CheckNoneButton").Click += (s, a) => Safe("Categories", () => CheckShown(false));
            W<Button>("RootAndButton").Click += (s, a) => Safe("Rules", () => SetMode(_current.Root, "and"));
            W<Button>("RootOrButton").Click += (s, a) => Safe("Rules", () => SetMode(_current.Root, "or"));
            W<Button>("AddRuleButton").Click += (s, a) => Safe("Rules", () => AddRule(_current.Root));
            W<Button>("AddSetButton").Click += (s, a) => Safe("Rules", () => AddSet(_current.Root));
            W<Button>("TestButton").Click += (s, a) => Safe("Test", OnTest);
            W<Button>("UseButton").Click += (s, a) => Safe("Use routine", OnUse);
            Window.Closing += (s, a) => Safe("Closing", SaveNow);
            Window.Closed += (s, a) =>
            {
                _closed = true;
                try { _saveTimer.Stop(); } catch (Exception) { }
                try { _main.Window.Activate(); } catch (Exception) { }
            };
        }

        public void Retheme()
        {
            try
            {
                WsmUi.ApplyPalette(Window, WsmUi.Current);
                W<TextBlock>("ThemeLabel").Text = _main.W<TextBlock>("ThemeLabel").Text;
                W<Button>("ThemeButton").ToolTip = _main.W<Button>("ThemeButton").ToolTip;
            }
            catch (Exception) { }
        }

        public void Show()
        {
            try { Window.Owner = _main.Window; } catch (Exception) { }
            Window.Show();
            Window.Activate();
        }

        public bool Alive() { return !_closed; }

        public void FocusOn(string workset, string template)
        {
            Safe("Routine Template Manager", () =>
            {
                if (!string.IsNullOrEmpty(workset)) { _forPicker.Value = workset; _forPicker.Refresh(); }
                string used = null;
                if (workset != null) _tab.State.Routines.TryGetValue(workset, out used);
                string name = template ?? used;
                if (!string.IsNullOrEmpty(name)) FillTemplates(name);
                UpdateContext();
                try
                {
                    WsmUi.WindowDrawer drawer = WsmUi.DrawerOf(Window);
                    if (drawer != null && drawer.Parked) drawer.Open();
                    Window.Activate();
                }
                catch (Exception) { }
            });
        }

        public void Close() { if (!_closed) Window.Close(); }

        private void Status(string text) { W<TextBlock>("StatusText").Text = WsmCore.Txt(text); }

        public void Reload()
        {
            Safe("Reload", () => { Library = _tab.Library; FillTemplates(CurrentName()); });
        }

        public List<string> DebugLines()
        {
            var lines = new List<string>
            {
                "open template: " + (_current != null ? _current.Name : "(none)"),
                "for workset: " + _forPicker.Value,
                "parameter reads pending: " + _wanted,
            };
            foreach (var pair in _params.OrderBy(p => p.Key, StringComparer.Ordinal))
            {
                lines.Add("parameters for " + pair.Key.Replace('\u0001', ',') + ": " + pair.Value.Count);
                lines.AddRange(pair.Value.Take(80).Select(p => "   " + p.Key + " | " + p.Label + " | " + p.Kind));
            }
            foreach (var pair in _values.OrderBy(p => p.Key, StringComparer.Ordinal))
                lines.Add("values of " + pair.Key.Replace('\u0001', ' ') + ": " + pair.Value.Count);
            lines.Add("status: " + W<TextBlock>("StatusText").Text);
            lines.Add("problems: " + W<TextBlock>("ProblemText").Text);
            return lines;
        }

        // ---------------------------------------------------------- templates

        private string CurrentName() { return _current != null ? _current.Name : null; }

        private void FillTemplates(string select)
        {
            var listing = W<ListBox>("TemplateList");
            string needle = WsmCore.Txt(W<TextBox>("TemplateSearch").Text);
            _suspend++;
            ListBoxItem chosen = null;
            try
            {
                listing.Items.Clear();
                foreach (string name in WsmCore.SortedNatural(Library.Keys))
                {
                    if (!WsmCore.TextMatch(name, needle) && name != select) continue;
                    WsmRules.Template template = Library[name];
                    var item = new ListBoxItem { Tag = name, ToolTip = WsmRules.Describe(template, 20) };
                    WsmUi.Style(item, "WsListItem");
                    var body = new StackPanel();
                    body.Children.Add(WsmUi.TextBlock(name, 12, "TextBrush", true));
                    string described = WsmRules.Describe(template);
                    TextBlock summary = WsmUi.TextBlock(described.Length > 0 ? described : "(empty)", 10, "MutedBrush");
                    body.Children.Add(summary);
                    var users = _tab.State.UsersOf(name);
                    if (users.Count > 0) body.Children.Add(WsmUi.TextBlock("used by " + string.Join(", ", users), 10, "BlueTextBrush"));
                    item.Content = body;
                    listing.Items.Add(item);
                    if (name == select) chosen = item;
                }
                if (chosen == null && listing.Items.Count > 0) chosen = (ListBoxItem)listing.Items[0];
                listing.SelectedItem = chosen;
            }
            finally { _suspend--; }
            LoadTemplate(chosen != null ? (string)chosen.Tag : null);
        }

        private void OnPickTemplate()
        {
            if (_suspend > 0) return;
            var item = W<ListBox>("TemplateList").SelectedItem as ListBoxItem;
            LoadTemplate(item != null ? (string)item.Tag : null);
        }

        private void LoadTemplate(string name)
        {
            WsmRules.Template template = null;
            if (name != null) Library.TryGetValue(name, out template);
            _current = template;
            bool on = _current != null;
            foreach (string key in new[] { "DuplicateButton", "RenameButton", "DeleteButton", "CheckAllButton", "CheckNoneButton", "AddRuleButton", "AddSetButton",
                                           "TestButton", "RootAndButton", "RootOrButton", "CategorySearch", "HideUncheckedCheck" })
                W<UIElement>(key).IsEnabled = on;
            W<TextBlock>("TestText").Text = "";
            FillCategories();
            BuildRules();
            RequestParams();
            UpdateContext();
        }

        /// <summary>The selected template's summary line, without rebuilding the list.</summary>
        private void RefreshListItem()
        {
            var item = W<ListBox>("TemplateList").SelectedItem as ListBoxItem;
            if (item == null || _current == null) return;
            try
            {
                var body = (StackPanel)item.Content;
                string described = WsmRules.Describe(_current);
                ((TextBlock)body.Children[1]).Text = described.Length > 0 ? described : "(empty)";
                item.ToolTip = WsmRules.Describe(_current, 20);
            }
            catch (Exception) { }
        }

        private string AskName(string title, string text, string defaultName)
        {
            while (true)
            {
                string name = WsmUi.PromptText(Window, title, text, defaultName, "OK");
                if (string.IsNullOrEmpty(name)) return null;
                name = name.Trim();
                var clash = Library.Keys.Where(n => string.Equals(n, name, StringComparison.OrdinalIgnoreCase)).ToList();
                if (clash.Count > 0 && !(_current != null && clash[0] == _current.Name && title == "Rename"))
                {
                    text = "'" + name + "' is taken - choose another name.";
                    defaultName = name;
                    continue;
                }
                return name;
            }
        }

        private void OnNew()
        {
            string name = AskName("New routine template", "Name the routine template:", WsmRules.UniqueName("New routine", Library.Keys));
            if (string.IsNullOrEmpty(name)) return;
            Library[name] = new WsmRules.Template(name);
            SaveNow();
            FillTemplates(name);
            Status("'" + name + "' made - tick its categories, then add rules.");
        }

        private void OnDuplicate()
        {
            if (_current == null) return;
            string name = AskName("Duplicate", "Name the copy:", WsmRules.UniqueName(_current.Name + " copy", Library.Keys));
            if (string.IsNullOrEmpty(name)) return;
            Library[name] = _current.Copy(name);
            SaveNow();
            FillTemplates(name);
        }

        private void OnRename()
        {
            if (_current == null) return;
            string old = _current.Name;
            string name = AskName("Rename", "New name for '" + old + "':", old);
            if (string.IsNullOrEmpty(name) || name == old) return;
            WsmRules.Template template = Library[old];
            Library.Remove(old);
            template.Name = name;
            Library[name] = template;
            SaveNow();
            _tab.LibraryChanged(new Dictionary<string, string> { { old, name } }, null);
            FillTemplates(name);
            Status("Renamed - worksets using it follow.");
        }

        private void OnDelete()
        {
            if (_current == null) return;
            string name = _current.Name;
            var users = _tab.State.UsersOf(name);
            string text = "Delete the routine template '" + name + "'?";
            if (users.Count > 0) text += " It comes off " + string.Join(", ", users) + ".";
            if (!WsmUi.Confirm(Window, "Delete", text, null, "Delete", "Keep", "WsRedButton", 480, 220)) return;
            Library.Remove(name);
            SaveNow();
            _tab.LibraryChanged(null, new[] { name });
            FillTemplates(null);
        }

        // ---------------------------------------------------------- categories

        private class CatLine { public string Key, Label; public int? Count; }

        /// <summary>Every model category in use, plus any the template ticks that this model does not have.</summary>
        private List<CatLine> CategoryLines()
        {
            var lines = _main.Scan.Entries.Where(e => e.Key.StartsWith("cat:")).Select(e => new CatLine { Key = e.Key, Label = e.Label, Count = e.Count }).ToList();
            var known = new HashSet<string>(lines.Select(l => l.Key));
            if (_current != null)
                foreach (string key in _current.Categories)
                    if (!known.Contains(key)) lines.Add(new CatLine { Key = key, Label = _current.CategoryLabel(key), Count = null });
            return WsmCore.StableSort(lines, (a, b) => WsmCore.NaturalCompare(a.Label, b.Label), false);
        }

        private void FillCategories()
        {
            var host = W<Panel>("CategoryHost");
            host.Children.Clear();
            _categoryBoxes = new Dictionary<string, CheckBox>();
            if (_current == null)
            {
                host.Children.Add(WsmUi.TextBlock("Choose or make a routine template.", 11, "MutedBrush", false, true));
                return;
            }
            string needle = WsmCore.Txt(W<TextBox>("CategorySearch").Text);
            bool hide = W<CheckBox>("HideUncheckedCheck").IsChecked == true;
            var ticked = new HashSet<string>(_current.Categories);
            _suspend++;
            try
            {
                foreach (CatLine line in CategoryLines())
                {
                    bool on = ticked.Contains(line.Key);
                    if (hide && !on) continue;
                    if (!WsmCore.TextMatch(line.Label, needle)) continue;
                    var box = new CheckBox { Margin = new Thickness(0, 3, 0, 3), IsChecked = on, Tag = Tuple.Create(line.Key, line.Label) };
                    WsmUi.Style(box, "WsCheck");
                    var content = new StackPanel { Orientation = Orientation.Horizontal };
                    content.Children.Add(WsmUi.TextBlock(line.Label, 12, "TextBrush"));
                    content.Children.Add(line.Count.HasValue ? WsmUi.TextBlock("   " + line.Count.Value, 11, "OrangeTextBrush") : WsmUi.TextBlock("   not in this model", 10, "MutedBrush"));
                    box.Content = content;
                    RoutedEventHandler handler = (s, a) => Safe("Categories", () =>
                    {
                        if (_suspend > 0 || _current == null) return;
                        var tag = (Tuple<string, string>)((CheckBox)s).Tag;
                        TickCategory(tag.Item1, tag.Item2, ((CheckBox)s).IsChecked == true);
                        CategoriesChanged();
                    });
                    box.Checked += handler;
                    box.Unchecked += handler;
                    _categoryBoxes[line.Key] = box;
                    host.Children.Add(box);
                }
            }
            finally { _suspend--; }
            if (_categoryBoxes.Count == 0) host.Children.Add(WsmUi.TextBlock("No categories match.", 11, "MutedBrush"));
        }

        private void TickCategory(string key, string label, bool on)
        {
            WsmRules.Template template = _current;
            if (on && !template.Categories.Contains(key))
            {
                template.Categories.Add(key);
                template.Labels[key] = label;
            }
            else if (!on && template.Categories.Contains(key))
            {
                template.Categories.Remove(key);
                foreach (WsmRules.Rule rule in WsmRules.WalkRules(template.Root))
                    if (rule.Scope == key) rule.Scope = WsmRules.AllCategories;
            }
        }

        private void CheckShown(bool on)
        {
            if (_current == null) return;
            foreach (var pair in _categoryBoxes.ToList())
                TickCategory(pair.Key, ((Tuple<string, string>)pair.Value.Tag).Item2, on);
            FillCategories();
            CategoriesChanged();
        }

        private void CategoriesChanged()
        {
            BuildRules();
            RequestParams();
            Edited();
        }

        // ---------------------------------------------------------- parameters

        private static string KeyOf(IEnumerable<string> keys) { return string.Join("\u0001", keys); }

        private List<string> ScopeKeys(WsmRules.Rule rule = null)
        {
            if (_current == null) return new List<string>();
            if (rule != null && rule.Scope.Length > 0 && _current.Categories.Contains(rule.Scope)) return new List<string> { rule.Scope };
            return _current.Categories.OrderBy(k => k, StringComparer.Ordinal).ToList();
        }

        /// <summary>Read the filterable parameters for a category set - once per set.</summary>
        private void RequestParams(List<string> keys = null)
        {
            keys = keys ?? ScopeKeys();
            if (keys.Count == 0) { W<TextBlock>("ParamStatus").Text = "Tick categories to choose parameters."; return; }
            string id = KeyOf(keys);
            if (_params.ContainsKey(id)) { W<TextBlock>("ParamStatus").Text = _params[id].Count + " parameters in common"; return; }
            if (_wanted == id) return;
            _wanted = id;
            W<TextBlock>("ParamStatus").Text = "Reading the parameters these categories share...";
            WsmWindow main = _main;
            var copy = keys.ToList();
            if (!main.RunJob("read parameters", uiapp => WsmRevit.FilterParameters(main.Doc, copy), found =>
            {
                _params[id] = (List<ParamInfo>)found;
                if (_wanted == id) _wanted = null;
                if (!_closed) { BuildRules(); RequestParams(); }
            }, "Reading parameters...")) _wanted = null;
        }

        private List<ParamInfo> ParamChoices(WsmRules.Rule rule)
        {
            List<string> keys = ScopeKeys(rule);
            string id = KeyOf(keys);
            List<ParamInfo> found;
            if (!_params.TryGetValue(id, out found)) RequestParams(keys);
            var choices = new List<ParamInfo>(found ?? new List<ParamInfo>());
            if (rule.Param.Length > 0 && !choices.Any(c => c.Key == rule.Param))
                choices.Insert(0, new ParamInfo { Key = rule.Param, Label = rule.Label.Length > 0 ? rule.Label : rule.Param, Kind = rule.Kind });
            return choices;
        }

        public void ValuesFor(WsmRules.Rule rule, Action<List<string>> show)
        {
            List<string> keys = ScopeKeys(rule);
            string id = KeyOf(keys) + "\u0001\u0001" + rule.Param;
            List<string> cached;
            if (_values.TryGetValue(id, out cached)) { show(cached); return; }
            WsmWindow main = _main;
            string param = rule.Param;
            main.RunJob("read values", uiapp => WsmRevit.SampleValues(main.Doc, keys, param), found =>
            {
                _values[id] = (List<string>)found;
                if (!_closed) show((List<string>)found);
            }, "Reading values...");
        }

        // ---------------------------------------------------------- rules

        private void SetMode(WsmRules.RuleSet node, string mode)
        {
            if (node == null) return;
            node.Mode = mode;
            BuildRules();
            Edited();
        }

        private void AddRule(WsmRules.RuleSet holder)
        {
            if (holder == null) return;
            holder.Items.Add(new WsmRules.Rule());
            BuildRules();
            Edited();
        }

        private void AddSet(WsmRules.RuleSet holder)
        {
            if (holder == null) return;
            holder.Items.Add(new WsmRules.RuleSet("and", new WsmRules.Node[] { new WsmRules.Rule() }));
            BuildRules();
            Edited();
        }

        private void Remove(WsmRules.RuleSet holder, WsmRules.Node node)
        {
            holder.Items.Remove(node);
            BuildRules();
            Edited();
        }

        private static void Segment(Button button, bool on) { WsmUi.Style(button, on ? "WsSegmentOn" : "WsSegment"); }

        private static Button RemoveButton(string tip)
        {
            var made = new Button
            {
                Content = "âˆ’", Width = 28, Height = 26, Padding = new Thickness(0), FontSize = 14, FontWeight = FontWeights.Bold,
                VerticalAlignment = VerticalAlignment.Center, ToolTip = tip,
            };
            WsmUi.Style(made, "WsRedButton");
            return made;
        }

        private void BuildRules()
        {
            var host = W<Panel>("RuleHost");
            host.Children.Clear();
            WsmRules.Template template = _current;
            if (template == null)
            {
                Segment(W<Button>("RootAndButton"), true);
                Segment(W<Button>("RootOrButton"), false);
                return;
            }
            Segment(W<Button>("RootAndButton"), template.Root.Mode == "and");
            Segment(W<Button>("RootOrButton"), template.Root.Mode == "or");
            if (template.Root.Items.Count == 0)
                host.Children.Add(WsmUi.TextBlock("No rules - every element of the ticked categories is caught. Add Rule to narrow it down, as in Revit's Filters.", 11, "MutedBrush", false, true));
            foreach (WsmRules.Node node in template.Root.Items.ToList()) host.Children.Add(NodeElement(template.Root, node, 0));
            ShowProblems();
        }

        private UIElement NodeElement(WsmRules.RuleSet holder, WsmRules.Node node, int depth)
        {
            var set = node as WsmRules.RuleSet;
            return set != null ? SetElement(holder, set, depth) : RuleElement(holder, (WsmRules.Rule)node);
        }

        private UIElement SetElement(WsmRules.RuleSet holder, WsmRules.RuleSet node, int depth)
        {
            var frame = new Border { BorderThickness = new Thickness(3, 1, 1, 1), CornerRadius = new CornerRadius(3), Padding = new Thickness(10, 6, 8, 8), Margin = new Thickness(0, 2, 0, 8) };
            WsmUi.Res(frame, Border.BackgroundProperty, "CardBrush");
            WsmUi.Res(frame, Border.BorderBrushProperty, "BlueBrush");
            var body = new StackPanel();
            var top = new Grid { Margin = new Thickness(0, 0, 0, 6) };
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var bar = new StackPanel { Orientation = Orientation.Horizontal };
            TextBlock label = WsmUi.TextBlock("Set", 11, "BlueTextBrush", true);
            label.Margin = new Thickness(0, 0, 10, 0);
            bar.Children.Add(label);
            foreach (var pair in new[] { Tuple.Create("and", "AND"), Tuple.Create("or", "OR") })
            {
                string mode = pair.Item1;
                var button = new Button { Content = pair.Item2, Margin = new Thickness(0, 0, 4, 0) };
                Segment(button, node.Mode == mode);
                button.Click += (s, a) => Safe("Rules", () => SetMode(node, mode));
                bar.Children.Add(button);
            }
            top.Children.Add(bar);
            Button drop = RemoveButton("Remove this set and its rules");
            drop.Click += (s, a) => Safe("Rules", () => Remove(holder, node));
            Grid.SetColumn(drop, 1);
            top.Children.Add(drop);
            body.Children.Add(top);
            foreach (WsmRules.Node item in node.Items.ToList()) body.Children.Add(NodeElement(node, item, depth + 1));
            var tools = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 4, 0, 0) };
            var more = new Button { Content = "+ Add Rule", Padding = new Thickness(10, 2, 10, 2), Margin = new Thickness(0, 0, 6, 0) };
            WsmUi.Style(more, "WsButton");
            more.Click += (s, a) => Safe("Rules", () => AddRule(node));
            tools.Children.Add(more);
            if (depth + 1 < MaxDepth)
            {
                var nested = new Button { Content = "+ Add Set", Padding = new Thickness(10, 2, 10, 2) };
                WsmUi.Style(nested, "WsButton");
                nested.Click += (s, a) => Safe("Rules", () => AddSet(node));
                tools.Children.Add(nested);
            }
            body.Children.Add(tools);
            frame.Child = body;
            return frame;
        }

        private UIElement RuleElement(WsmRules.RuleSet holder, WsmRules.Rule rule)
        {
            WsmRules.Template template = _current;
            var row = new Grid { Margin = new Thickness(0, 0, 0, 6) };
            foreach (double weight in new[] { 1.1, 1.4, 1.1, 1.3 })
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(weight, GridUnitType.Star), MinWidth = 90 });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(32), MinWidth = 32 });

            var scopes = new List<WsmUi.Choice> { new WsmUi.Choice(WsmRules.AllCategories, AllLabel) };
            scopes.AddRange(template.Categories.Select(k => new WsmUi.Choice(k, template.CategoryLabel(k))));
            var scope = new WsmUi.PickButton(scopes, rule.Scope, v => Safe("Rules", () =>
            {
                rule.Scope = WsmCore.Txt(v);
                BuildRules();
                RequestParams(ScopeKeys(rule));
                Edited();
            }), false, AllLabel);
            scope.Element.Margin = new Thickness(0, 0, 6, 0);
            row.Children.Add(scope.Element);

            List<ParamInfo> choices = ParamChoices(rule);
            var param = new WsmUi.PickButton(choices.Select(c => new WsmUi.Choice(c.Key, c.Label)), rule.Param.Length > 0 ? rule.Param : null, v => Safe("Rules", () =>
            {
                foreach (ParamInfo c in choices)
                {
                    if (c.Key != (string)v) continue;
                    rule.Param = c.Key; rule.Label = c.Label; rule.Kind = c.Kind;
                    if (!WsmRules.OpsFor(c.Kind).Contains(rule.Op)) rule.Op = WsmRules.OpsFor(c.Kind)[0];
                }
                BuildRules();
                Edited();
            }), true, choices.Count == 0 && ScopeKeys(rule).Count > 0 ? "Reading parameters..." : "(parameter)", null, 300);
            param.Element.Margin = new Thickness(0, 0, 6, 0);
            Grid.SetColumn(param.Element, 1);
            row.Children.Add(param.Element);

            var ops = WsmRules.OpsFor(rule.Kind).Select(op => new WsmUi.Choice(op, WsmRules.OpLabel(op)));
            var operatorPick = new WsmUi.PickButton(ops, rule.Op, v => Safe("Rules", () =>
            {
                rule.Op = (string)v;
                BuildRules();
                Edited();
            }));
            operatorPick.Element.Margin = new Thickness(0, 0, 6, 0);
            Grid.SetColumn(operatorPick.Element, 2);
            row.Children.Add(operatorPick.Element);

            if (WsmRules.NeedsValue(rule.Op))
            {
                var value = new ValueBox(this, rule);
                value.Element.Margin = new Thickness(0, 0, 6, 0);
                Grid.SetColumn(value.Element, 3);
                row.Children.Add(value.Element);
                if (rule.Kind == WsmRules.KindNumber || rule.Kind == WsmRules.KindInteger)
                    value.Box.ToolTip = "A number in the project's units - lengths as Revit shows them (mm in a metric project)";
            }

            Button drop = RemoveButton("Remove this rule");
            drop.HorizontalAlignment = HorizontalAlignment.Right;
            drop.Click += (s, a) => Safe("Rules", () => Remove(holder, rule));
            Grid.SetColumn(drop, 4);
            row.Children.Add(drop);
            return row;
        }

        private void ShowProblems()
        {
            if (_current == null) { W<TextBlock>("ProblemText").Text = ""; return; }
            var problems = WsmRules.TemplateProblems(_current);
            W<TextBlock>("ProblemText").Text = problems.Count > 0 ? "Not ready: " + string.Join("; ", problems) : "";
        }

        // ---------------------------------------------------------- saving

        public void Edited()
        {
            if (_current == null) return;
            W<TextBlock>("TestText").Text = "";
            ShowProblems();
            RefreshListItem();
            WsmUi.Kick(_saveTimer);
        }

        public void SaveNow()
        {
            try { _saveTimer.Stop(); } catch (Exception) { }
            if (!WsmRules.SaveLibrary(Library)) { Status("Could not save the routine templates."); return; }
            try { _tab.Changed(); } catch (Exception) { }
        }

        // ---------------------------------------------------------- test and use

        private void OnTest()
        {
            if (_current == null) return;
            var problems = WsmRules.TemplateProblems(_current);
            if (problems.Count > 0)
            {
                W<TextBlock>("TestText").Text = "";
                Status("Fix first: " + string.Join("; ", problems));
                return;
            }
            WsmRules.Template template = _current.Copy();
            WsmWindow main = _main;
            W<TextBlock>("TestText").Text = "Testing...";
            main.RunJob("test the routine", uiapp =>
            {
                Dictionary<long, ElementId> caught = WsmRevit.EvaluateTemplate(main.Doc, template);
                var on = new Dictionary<int, int>();
                foreach (ElementId id in caught.Values)
                {
                    Element element = main.Doc.GetElement(id);
                    if (element == null) continue;
                    int key;
                    try { key = WsmRevit.WsidValue(element.WorksetId); } catch (Exception) { continue; }
                    int n; on.TryGetValue(key, out n); on[key] = n + 1;
                }
                return Tuple.Create(caught.Count, on);
            }, result =>
            {
                var r = (Tuple<int, Dictionary<int, int>>)result;
                var names = main.Records.ToDictionary(x => x.Iid, x => x.Name);
                Func<int, string> nameOf = iid => { string n; return names.TryGetValue(iid, out n) ? n : iid.ToString(); };
                var spread = r.Item2.OrderByDescending(p => p.Value).ToList();
                var parts = spread.Take(4).Select(p => p.Value + " on " + nameOf(p.Key)).ToList();
                string more = spread.Count > 4 ? " +" + (spread.Count - 4) + " more" : "";
                W<TextBlock>("TestText").Text = r.Item1 + " element(s) caught" + (parts.Count > 0 ? "  Â·  " + string.Join(", ", parts) + more : "");
                W<TextBlock>("TestText").ToolTip = string.Join("\n", spread.Select(p => nameOf(p.Key) + ": " + p.Value));
            }, "Testing the routine...");
        }

        private void UpdateContext()
        {
            string workset = _forPicker.Value as string;
            string name = CurrentName();
            bool can = !string.IsNullOrEmpty(workset) && name != null;
            W<Button>("UseButton").IsEnabled = can;
            W<TextBlock>("UseLabel").Text = !string.IsNullOrEmpty(workset) ? "Use for " + workset : "Use for workset";
            string using_ = null;
            if (!string.IsNullOrEmpty(workset)) _tab.State.Routines.TryGetValue(workset, out using_);
            if (!string.IsNullOrEmpty(workset) && !string.IsNullOrEmpty(using_)) W<TextBlock>("ContextText").Text = workset + " uses '" + using_ + "'";
            else if (!string.IsNullOrEmpty(workset)) W<TextBlock>("ContextText").Text = "Choosing a routine for " + workset;
            else W<TextBlock>("ContextText").Text = "Templates are shared by every project";
        }

        private void OnUse()
        {
            string workset = _forPicker.Value as string;
            if (string.IsNullOrEmpty(workset) || _current == null) return;
            var problems = WsmRules.TemplateProblems(_current);
            if (problems.Count > 0 && !WsmUi.Confirm(Window, "Use routine",
                    "'" + _current.Name + "' is not ready (" + string.Join("; ", problems) + "). It is skipped at Apply until it is fixed - use it anyway?",
                    null, "Use it", "Cancel", "WsOrangeButton", 520, 230)) return;
            SaveNow();
            if (_tab.UseRoutine(workset, _current.Name))
            {
                Status(workset + " now uses '" + _current.Name + "'.");
                FillTemplates(_current.Name);
                UpdateContext();
            }
        }

        // ================================================================ the value box

        /// <summary>A value: a text box and a drop-down of the values the model has for the rule's parameter, fetched from Revit the first time it opens.</summary>
        private class ValueBox
        {
            private readonly WsmRoutineManager _manager;
            private readonly WsmRules.Rule _rule;
            public readonly Grid Element;
            public readonly TextBox Box;
            private readonly Popup _popup;

            public ValueBox(WsmRoutineManager manager, WsmRules.Rule rule)
            {
                _manager = manager; _rule = rule;
                Element = new Grid();
                Element.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                Element.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(26) });
                Box = new TextBox { Height = 30, Tag = "Value", Text = rule.Value };
                WsmUi.Style(Box, "WsTextBox");
                Box.TextChanged += (s, a) => manager.Safe("Rules", () =>
                {
                    _rule.Value = WsmCore.Txt(Box.Text);
                    _manager.Edited();
                });
                Element.Children.Add(Box);
                var drop = new Button { Content = "â–¾", Padding = new Thickness(0), Height = 26, Margin = new Thickness(2, 0, 0, 0), ToolTip = "Values the model has for this parameter" };
                WsmUi.Style(drop, "WsButton");
                drop.Click += (s, a) => manager.Safe("Rules", () =>
                {
                    if (_rule.Param.Length == 0) { _manager.Status("Pick a parameter first."); return; }
                    _manager.ValuesFor(_rule, ShowValues);
                });
                Grid.SetColumn(drop, 1);
                Element.Children.Add(drop);
                _popup = new Popup { PlacementTarget = Box, Placement = PlacementMode.Bottom, StaysOpen = false, AllowsTransparency = true };
                Element.Children.Add(_popup);
            }

            private void ShowValues(List<string> values)
            {
                var shell = new Border { BorderThickness = new Thickness(1), Padding = new Thickness(6), MinWidth = Math.Max(220.0, Element.ActualWidth) };
                WsmUi.Res(shell, Border.BackgroundProperty, "FieldBrush");
                WsmUi.Res(shell, Border.BorderBrushProperty, "ChromeBrush");
                ListBox listing = WsmUi.ThemedList(280);
                listing.BorderThickness = new Thickness(0);
                if (values.Count == 0)
                {
                    var item = new ListBoxItem { IsEnabled = false, Content = WsmUi.TextBlock("No values on these categories", 11, "MutedBrush") };
                    WsmUi.Style(item, "WsListItem");
                    listing.Items.Add(item);
                }
                foreach (string value in values)
                {
                    var item = new ListBoxItem { Tag = value, Content = WsmUi.TextBlock(value, 12, "TextBrush") };
                    WsmUi.Style(item, "WsListItem");
                    listing.Items.Add(item);
                }
                listing.SelectionChanged += (s, a) =>
                {
                    var item = listing.SelectedItem as ListBoxItem;
                    if (item == null || item.Tag == null) return;
                    Box.Text = (string)item.Tag;
                    _popup.IsOpen = false;
                };
                shell.Child = listing;
                _popup.Child = shell;
                _popup.IsOpen = true;
            }
        }
    }
}


