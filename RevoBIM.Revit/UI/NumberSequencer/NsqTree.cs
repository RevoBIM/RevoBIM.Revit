using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using Path = System.Windows.Shapes.Path;
using RevoBIM.Tools.NumberSequencer;

namespace RevoBIM.UI.NumberSequencer
{
    /// <summary>
    /// The Category > Family > Type tree with ticks (port of nsq_tree.py). Used by both tabs. Unticked types are
    /// walked through but take no number. Categories start open, families closed; each family gets its own
    /// colour, shared by its types.
    /// </summary>
    public class FamilyTree
    {
        private const string ArrowRight = "M0,0 L4,4 L0,8";
        private const string ArrowDown = "M0,0 L4,4 L8,0";

        private readonly Panel _host;
        private readonly TextBlock _countText;
        private readonly TextBox _search;
        private readonly Func<string> _mode;
        private readonly HashSet<string> _skipped;
        private readonly Action _onChanged;
        private readonly Action<List<long>> _onSelect;
        private List<NsqCore.TreeRow> _rows = new List<NsqCore.TreeRow>();
        private int _total;
        private HashSet<string> _expanded = new HashSet<string>();
        private HashSet<string> _collapsed = new HashSet<string>();
        private readonly Dictionary<string, int> _colours = new Dictionary<string, int>();
        private readonly List<KeyValuePair<CheckBox, List<string>>> _boxes = new List<KeyValuePair<CheckBox, List<string>>>();

        public FamilyTree(Panel host, TextBlock countText, TextBox search, Func<string> mode, HashSet<string> skipped,
                          Action onChanged, Action<List<long>> onSelect)
        {
            _host = host; _countText = countText; _search = search; _mode = mode; _skipped = skipped;
            _onChanged = onChanged; _onSelect = onSelect;
        }

        public void SetRows(IEnumerable<NsqCore.TreeRow> rows, int? total = null, bool reset = false)
        {
            _rows = rows.ToList();
            _total = total ?? _rows.Count;
            if (reset)
            {
                _expanded = new HashSet<string>();
                _collapsed = new HashSet<string>();
                _colours.Clear();
            }
        }

        public HashSet<string> TypeKeys()
        {
            return new HashSet<string>(_rows.Select(r => NsqCore.TypeKey(r.Category, r.Family, r.Type)));
        }

        private string ColourFor(string cat, string fam)
        {
            string key = cat + "\u0001" + fam;
            if (!_colours.ContainsKey(key)) _colours[key] = _colours.Count;
            return NsqCore.GroupColour(_colours[key], _mode());
        }

        private bool IsOpen(string expandId)
        {
            // categories start open, families start closed
            if (expandId.StartsWith("c\u0001")) return !_collapsed.Contains(expandId);
            return _expanded.Contains(expandId);
        }

        public void Build()
        {
            _host.Children.Clear();
            _boxes.Clear();
            if (_rows.Count == 0) { _countText.Text = ""; return; }
            string query = _search.Text ?? "";
            bool searching = query.Trim().Length > 0;
            List<CategoryNode> tree = NsqCore.BuildTree(_rows);
            foreach (CategoryNode cat in tree)
                foreach (FamilyNode fam in cat.Families) ColourFor(cat.Name, fam.Name);   // over the whole tree, so a search never recolours
            foreach (CategoryNode cat in tree)
            {
                var famBlocks = new List<KeyValuePair<FamilyNode, List<TypeNode>>>();
                foreach (FamilyNode fam in cat.Families)
                {
                    var types = fam.Types.Where(t => NsqCore.Matches(cat.Name + " " + fam.Name + " " + t.Name, query)).ToList();
                    if (types.Count > 0) famBlocks.Add(new KeyValuePair<FamilyNode, List<TypeNode>>(fam, types));
                }
                if (famBlocks.Count == 0) continue;
                var catKeys = famBlocks.SelectMany(fb => fb.Value).Select(t => t.Key).ToList();
                string catId = "c\u0001" + cat.Name;
                int catCount = famBlocks.SelectMany(fb => fb.Value).Sum(t => t.Ids.Count);
                var catIds = famBlocks.SelectMany(fb => fb.Value).SelectMany(t => t.Ids).ToList();
                StackPanel body;
                StackPanel outer = Row(0, cat.Name, catCount, null, catKeys, catId, searching || IsOpen(catId), catIds, out body);
                _host.Children.Add(outer);
                foreach (var fb in famBlocks)
                {
                    FamilyNode fam = fb.Key;
                    string colour = ColourFor(cat.Name, fam.Name);
                    string famId = "f\u0001" + cat.Name + "\u0001" + fam.Name;
                    var famIds = fb.Value.SelectMany(t => t.Ids).ToList();
                    StackPanel fBody;
                    StackPanel fOuter = Row(1, fam.Name, famIds.Count, colour, fb.Value.Select(t => t.Key).ToList(), famId,
                                            searching || IsOpen(famId), famIds, out fBody);
                    body.Children.Add(fOuter);
                    foreach (TypeNode t in fb.Value)
                    {
                        StackPanel tBody;
                        StackPanel tOuter = Row(2, t.Name, t.Ids.Count, colour, new List<string> { t.Key }, null, false, t.Ids, out tBody);
                        fBody.Children.Add(tOuter);
                    }
                }
            }
            _countText.Text = _total + " elements";
            Sync();
        }

        private StackPanel Row(int level, string text, int count, string colour, List<string> keys, string expandId, bool isOpen,
                               List<long> elemKeys, out StackPanel body)
        {
            var outer = new StackPanel();
            var head = new Border
            {
                CornerRadius = new CornerRadius(3),
                Margin = new Thickness(0, 1, 0, 1),
                Padding = new Thickness(4 + level * 18, 3, 8, 3),
            };
            if (colour != null) head.Background = NsqUi.Brush(colour, level == 1 ? 0x38 : 0x18);
            else head.SetResourceReference(Border.BackgroundProperty, "Card");
            var grid = new Grid();
            foreach (double w in new double[] { 18, 22, 10 }) grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(w) });
            grid.ColumnDefinitions.Add(new ColumnDefinition());
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            Path arrow = null;
            if (expandId != null)
            {
                arrow = new Path
                {
                    Data = Geometry.Parse(isOpen ? ArrowDown : ArrowRight),
                    StrokeThickness = 1.6,
                    VerticalAlignment = VerticalAlignment.Center,
                    Margin = new Thickness(3, 0, 0, 0),
                };
                arrow.SetResourceReference(Shape.StrokeProperty, "Muted");
                Grid.SetColumn(arrow, 0);
                grid.Children.Add(arrow);
            }

            var cb = new CheckBox { IsThreeState = false };
            Grid.SetColumn(cb, 1);
            grid.Children.Add(cb);

            if (colour != null)
            {
                var bar = new Border
                {
                    Width = level == 1 ? 4 : 3,
                    Height = 14,
                    CornerRadius = new CornerRadius(1),
                    Background = NsqUi.Brush(colour),
                };
                Grid.SetColumn(bar, 2);
                grid.Children.Add(bar);
            }

            var name = new TextBlock { Text = text, Margin = new Thickness(4, 0, 6, 0) };
            name.SetResourceReference(TextBlock.ForegroundProperty, "Text");
            if (level == 0) { name.FontWeight = FontWeights.SemiBold; name.FontSize = 13; }
            else if (level == 1) name.FontWeight = FontWeights.SemiBold;
            Grid.SetColumn(name, 3);
            grid.Children.Add(name);

            var cnt = new TextBlock { Text = count.ToString() };
            cnt.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
            Grid.SetColumn(cnt, 4);
            grid.Children.Add(cnt);

            head.Child = grid;
            outer.Children.Add(head);
            body = new StackPanel();
            NsqUi.Show(body, isOpen);
            outer.Children.Add(body);

            _boxes.Add(new KeyValuePair<CheckBox, List<string>>(cb, new List<string>(keys)));
            var tick = TickHandler(cb, new List<string>(keys));
            cb.Click += (s, e) => TryRun("tick", () => tick(s, e));
            StackPanel bodyRef = body;
            Path arrowRef = arrow;
            var headFn = HeadHandler(expandId, bodyRef, arrowRef, elemKeys);
            head.MouseLeftButtonDown += (s, e) => TryRun("head", () => headFn(s, e));
            head.ToolTip = expandId != null ? "Click to expand or collapse, double-click to select in Revit" : "Double-click to select in Revit";
            return outer;
        }

        public Action<string, Action> TryRun = (name, a) => a();

        private Action<object, RoutedEventArgs> TickHandler(CheckBox cb, List<string> keys)
        {
            return (sender, e) =>
            {
                // a mixed box ticks everything; otherwise follow the box
                bool? before = NsqCore.GroupState(keys, _skipped);
                bool on = before == null ? true : cb.IsChecked == true;
                foreach (string k in keys) { if (on) _skipped.Remove(k); else _skipped.Add(k); }
                Sync();
                _onChanged();
            };
        }

        private Action<object, MouseButtonEventArgs> HeadHandler(string expandId, StackPanel body, Path arrow, List<long> elemKeys)
        {
            return (sender, e) =>
            {
                if (e.ClickCount == 2) { _onSelect(elemKeys); e.Handled = true; return; }
                if (expandId == null) return;
                bool opening = body.Visibility != Visibility.Visible;
                SetOpen(expandId, opening, body, arrow);
                e.Handled = true;
            };
        }

        private void SetOpen(string expandId, bool opening, StackPanel body, Path arrow)
        {
            if (opening) { _expanded.Add(expandId); _collapsed.Remove(expandId); }
            else { _expanded.Remove(expandId); _collapsed.Add(expandId); }
            NsqUi.Show(body, opening);
            if (arrow != null) arrow.Data = Geometry.Parse(opening ? ArrowDown : ArrowRight);
        }

        public void Sync()
        {
            foreach (var kv in _boxes) kv.Key.IsChecked = NsqCore.GroupState(kv.Value, _skipped);
        }

        private List<string> AllIds()
        {
            var o = new List<string>();
            foreach (CategoryNode cat in NsqCore.BuildTree(_rows))
            {
                o.Add("c\u0001" + cat.Name);
                foreach (FamilyNode fam in cat.Families) o.Add("f\u0001" + cat.Name + "\u0001" + fam.Name);
            }
            return o;
        }

        public void ExpandAll()
        {
            _collapsed = new HashSet<string>();
            _expanded = new HashSet<string>(AllIds());
            Build();
        }

        public void CollapseAll()
        {
            _expanded = new HashSet<string>();
            _collapsed = new HashSet<string>(AllIds());
            Build();
        }

        public void TickAll()
        {
            foreach (string k in TypeKeys()) _skipped.Remove(k);
            Sync();
            _onChanged();
        }

        public void UntickAll()
        {
            foreach (string k in TypeKeys()) _skipped.Add(k);
            Sync();
            _onChanged();
        }
    }
}

