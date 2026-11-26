using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Data;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Threading;
using RevoBIM.Tools.ViewManager;

namespace RevoBIM.UI.ViewManager
{
    /// <summary>
    /// The grid behind the View Manager and View Range tabs: a tick column and a status column, a keyword box at the top of every
    /// column, dropdown cells, multi-level sort (click flips, shift adds a level, as in Excel for Revit), grouping under collapsible
    /// headings, and custom parameter columns. It owns no Revit code: edits go to the EditStore and the tab applies them.
    /// </summary>
    internal sealed class VmTableHost
    {
        private const string SortUp = "▲", SortDown = "▼";

        private const string StatusColumnXaml = @"<DataGridTemplateColumn xmlns=""http://schemas.microsoft.com/winfx/2006/xaml/presentation""
    Width=""30"" MinWidth=""30"" CanUserSort=""False"" CanUserResize=""False"" IsReadOnly=""True"">
  <DataGridTemplateColumn.CellTemplate>
    <DataTemplate>
      <TextBlock x:Name=""s"" xmlns:x=""http://schemas.microsoft.com/winfx/2006/xaml"" HorizontalAlignment=""Center"" VerticalAlignment=""Center"" FontWeight=""Bold"" Text=""&#x2713;"" Foreground=""{DynamicResource Green}""/>
      <DataTemplate.Triggers>
        <DataTrigger Binding=""{Binding [st]}"" Value=""m""><Setter TargetName=""s"" Property=""Text"" Value=""&#x270E;""/><Setter TargetName=""s"" Property=""Foreground"" Value=""{DynamicResource Orange}""/></DataTrigger>
        <DataTrigger Binding=""{Binding [st]}"" Value=""x""><Setter TargetName=""s"" Property=""Text"" Value=""&#x2715;""/><Setter TargetName=""s"" Property=""Foreground"" Value=""{DynamicResource Red}""/></DataTrigger>
      </DataTemplate.Triggers>
    </DataTemplate>
  </DataGridTemplateColumn.CellTemplate>
</DataGridTemplateColumn>";

        private const string CheckColumnXaml = @"<DataGridTemplateColumn xmlns=""http://schemas.microsoft.com/winfx/2006/xaml/presentation""
    Width=""34"" MinWidth=""34"" CanUserSort=""False"" CanUserResize=""False"">
  <DataGridTemplateColumn.CellTemplate>
    <DataTemplate>
      <CheckBox HorizontalAlignment=""Center"" VerticalAlignment=""Center""
                IsChecked=""{Binding [sel], Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}""/>
    </DataTemplate>
  </DataGridTemplateColumn.CellTemplate>
</DataGridTemplateColumn>";

        private const string TextColumnXaml = @"<DataGridTemplateColumn xmlns=""http://schemas.microsoft.com/winfx/2006/xaml/presentation""
    xmlns:x=""http://schemas.microsoft.com/winfx/2006/xaml""
    SortMemberPath=""c{i}"" Width=""{w}"" MinWidth=""60"" IsReadOnly=""{ro}"">
  <DataGridTemplateColumn.CellTemplate>
    <DataTemplate>
      <Border x:Name=""bd"" Background=""Transparent"" Padding=""7,0,7,0"" MinHeight=""26"">
        <TextBlock x:Name=""tx"" Text=""{Binding [c{i}]}"" VerticalAlignment=""Center"" TextAlignment=""{al}""
                   TextTrimming=""CharacterEllipsis""/>
      </Border>
      <DataTemplate.Triggers>
        <DataTrigger Binding=""{Binding [f{i}]}"" Value=""e"">
          <Setter TargetName=""bd"" Property=""Background"" Value=""{DynamicResource StagedWash}""/>
        </DataTrigger>
        <DataTrigger Binding=""{Binding [f{i}]}"" Value=""x"">
          <Setter TargetName=""bd"" Property=""Background"" Value=""{DynamicResource ErrorWash}""/>
        </DataTrigger>
        <DataTrigger Binding=""{Binding [f{i}]}"" Value=""r"">
          <Setter TargetName=""tx"" Property=""Foreground"" Value=""{DynamicResource Muted}""/>
          <Setter TargetName=""bd"" Property=""Background"" Value=""{DynamicResource Panel}""/>
        </DataTrigger>
      </DataTemplate.Triggers>
    </DataTemplate>
  </DataGridTemplateColumn.CellTemplate>
  <DataGridTemplateColumn.CellEditingTemplate>
    <DataTemplate>
      <TextBox Text=""{Binding [c{i}], Mode=TwoWay, UpdateSourceTrigger=LostFocus}""
               BorderThickness=""0"" Padding=""6,0,6,0"" VerticalContentAlignment=""Center""
               Background=""{DynamicResource Input}"" Foreground=""{DynamicResource Text}""/>
    </DataTemplate>
  </DataGridTemplateColumn.CellEditingTemplate>
</DataGridTemplateColumn>";

        private const string ComboColumnXaml = @"<DataGridTemplateColumn xmlns=""http://schemas.microsoft.com/winfx/2006/xaml/presentation""
    xmlns:x=""http://schemas.microsoft.com/winfx/2006/xaml""
    SortMemberPath=""c{i}"" Width=""{w}"" MinWidth=""80"" IsReadOnly=""True"">
  <DataGridTemplateColumn.CellTemplate>
    <DataTemplate>
      <Border x:Name=""bd"" Background=""Transparent"" Padding=""3,2,3,2"">
        <ComboBox x:Name=""cb"" ItemsSource=""{DynamicResource list_c{i}}"" Height=""22""
                  SelectedItem=""{Binding [c{i}], Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}""/>
      </Border>
      <DataTemplate.Triggers>
        <DataTrigger Binding=""{Binding [f{i}]}"" Value=""e"">
          <Setter TargetName=""bd"" Property=""Background"" Value=""{DynamicResource StagedWash}""/>
        </DataTrigger>
        <DataTrigger Binding=""{Binding [f{i}]}"" Value=""x"">
          <Setter TargetName=""bd"" Property=""Background"" Value=""{DynamicResource ErrorWash}""/>
        </DataTrigger>
        <DataTrigger Binding=""{Binding [f{i}]}"" Value=""r"">
          <Setter TargetName=""cb"" Property=""IsEnabled"" Value=""False""/>
        </DataTrigger>
      </DataTemplate.Triggers>
    </DataTemplate>
  </DataGridTemplateColumn.CellTemplate>
</DataGridTemplateColumn>";

        private const string PlusColumnXaml = @"<DataGridTemplateColumn xmlns=""http://schemas.microsoft.com/winfx/2006/xaml/presentation""
    Width=""46"" MinWidth=""46"" IsReadOnly=""True"" CanUserSort=""False"" CanUserResize=""False"" CanUserReorder=""False"">
  <DataGridTemplateColumn.CellTemplate>
    <DataTemplate><Border Background=""Transparent""/></DataTemplate>
  </DataGridTemplateColumn.CellTemplate>
</DataGridTemplateColumn>";

        private const string GroupStyleXaml = @"<GroupStyle xmlns=""http://schemas.microsoft.com/winfx/2006/xaml/presentation""
    xmlns:x=""http://schemas.microsoft.com/winfx/2006/xaml"">
  <GroupStyle.ContainerStyle>
    <Style TargetType=""GroupItem"">
      <Setter Property=""Template"">
        <Setter.Value>
          <ControlTemplate TargetType=""GroupItem"">
            <StackPanel>
              <ToggleButton x:Name=""gt"" IsChecked=""True"" Cursor=""Hand"" HorizontalContentAlignment=""Stretch"" Focusable=""False"">
                <ToggleButton.Template>
                  <ControlTemplate TargetType=""ToggleButton"">
                    <Border Background=""{DynamicResource HeadBar}"" Padding=""8,5,8,5"" BorderBrush=""{DynamicResource Line}"" BorderThickness=""0,0,0,1"">
                      <StackPanel Orientation=""Horizontal"">
                        <TextBlock x:Name=""arrow"" Text=""&#x25BE;"" Foreground=""{DynamicResource Orange}"" Width=""16"" FontSize=""13""/>
                        <ContentPresenter/>
                      </StackPanel>
                    </Border>
                    <ControlTemplate.Triggers>
                      <Trigger Property=""IsChecked"" Value=""False"">
                        <Setter TargetName=""arrow"" Property=""Text"" Value=""&#x25B8;""/>
                      </Trigger>
                    </ControlTemplate.Triggers>
                  </ControlTemplate>
                </ToggleButton.Template>
                <StackPanel Orientation=""Horizontal"">
                  <TextBlock Text=""{Binding Name}"" FontWeight=""SemiBold"" Foreground=""{DynamicResource Text}""/>
                  <TextBlock Text=""{Binding ItemCount, StringFormat='   ({0})'}"" Foreground=""{DynamicResource Muted}""/>
                </StackPanel>
              </ToggleButton>
              <ItemsPresenter x:Name=""items""/>
            </StackPanel>
            <ControlTemplate.Triggers>
              <Trigger SourceName=""gt"" Property=""IsChecked"" Value=""False"">
                <Setter TargetName=""items"" Property=""Visibility"" Value=""Collapsed""/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </GroupStyle.ContainerStyle>
</GroupStyle>";

        public sealed class SortEntry
        {
            public string Key;
            public bool Desc;
        }

        private readonly Window window;
        private readonly DataGrid grid;
        private readonly VmCore.EditStore store;
        private readonly Action<string, bool> say;

        public List<VmCore.Field> Fields = new List<VmCore.Field>();
        public Dictionary<VmCore.CellKey, string> Failed = new Dictionary<VmCore.CellKey, string>();
        public HashSet<string> Removable = new HashSet<string>();
        public HashSet<long> Checked = new HashSet<long>();
        public List<SortEntry> Sort = new List<SortEntry>();
        public bool Grouping;
        public string GlobalSearch = "";
        public bool HideUnchecked;
        public string TypeName;                          // the view type filter (a ViewType name), null for all
        public List<VmCore.TypeOption> TypeOptions = new List<VmCore.TypeOption>();
        public readonly Dictionary<string, string> ColumnFilters = new Dictionary<string, string>();
        public Action OnPlus;
        public Action<string> OnRemove;
        public Action OnChanged;                         // a cell was edited
        public Action OnSelection;                       // the ticks changed
        public Action OnShownChanged;                    // the rows shown changed (sort, filter, group)
        public Action OnFilterColumns;

        private DataTable table;
        private bool updating;
        private List<VmCore.RefRow> allRows = new List<VmCore.RefRow>();
        private List<VmCore.RefRow> shown = new List<VmCore.RefRow>();
        private readonly Dictionary<string, TextBlock> labelBlocks = new Dictionary<string, TextBlock>();
        private readonly DispatcherTimer filterTimer;
        private ICollectionView view;
        private CheckBox headerCheck;
        private bool settingHeader;

        public VmTableHost(Window window, DataGrid grid, VmCore.EditStore store, Action<string, bool> say)
        {
            this.window = window;
            this.grid = grid;
            this.store = store;
            this.say = say;
            filterTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(260) };
            filterTimer.Tick += (s, e) =>
            {
                filterTimer.Stop();
                try { Fill(); } catch (Exception) { }
            };
            grid.BeginningEdit += OnBeginEdit;
            grid.Sorting += OnSorting;
            grid.GroupStyle.Clear();
        }

        public List<VmCore.RefRow> Shown { get { return shown; } }

        // ---------------------------------------------------------------- values --

        private string Display(VmCore.Field f, string value)
        {
            return f.NoneLabel != null && value.Length == 0 ? f.NoneLabel : value;
        }

        private string Value(long viewId, VmCore.Field f)
        {
            return Display(f, store.Effective(viewId, f.Key));
        }

        private string Flag(long viewId, VmCore.Field f, HashSet<VmCore.CellKey> failed, IDictionary<VmCore.CellKey, string> conflicts)
        {
            return VmCore.CellFlag(store, failed, conflicts, viewId, f);
        }

        private string RowStatus(long viewId, HashSet<VmCore.CellKey> failed)
        {
            foreach (VmCore.Field f in Fields)
                if (failed.Contains(new VmCore.CellKey(viewId, f.Key))) return "x";
            foreach (VmCore.Field f in Fields)
                if (store.Edits.ContainsKey(new VmCore.CellKey(viewId, f.Key))) return "m";
            return "ok";
        }

        // ---------------------------------------------------------------- columns --

        private Brush Res(string key) { return (Brush)window.Resources[key]; }

        private object HeaderFor(VmCore.Field field, int index)
        {
            var panel = new StackPanel { Margin = new Thickness(0, 2, 0, 3), MinWidth = 50 };
            var top = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Center };
            var label = new TextBlock { Text = field.Label, VerticalAlignment = VerticalAlignment.Center };
            labelBlocks[field.Key] = label;
            top.Children.Add(label);
            if (Removable.Contains(field.Key))
            {
                var remove = new Button
                {
                    Content = "✕",
                    Style = (Style)window.FindResource("Flat"),
                    Foreground = Res("Muted"),
                    Margin = new Thickness(6, 0, 0, 0),
                    Padding = new Thickness(3, 0, 3, 0),
                    FontSize = 9,
                    ToolTip = "Remove this column",
                    Tag = field.Key,
                };
                remove.Click += (s, e) =>
                {
                    e.Handled = true;
                    try { if (OnRemove != null) OnRemove((string)((FrameworkElement)s).Tag); } catch (Exception) { }
                };
                top.Children.Add(remove);
            }
            panel.Children.Add(top);

            if (field.Kind == "vtype" && TypeOptions.Count > 0)
            {
                var combo = new ComboBox { Height = 22, Margin = new Thickness(0, 3, 0, 0), ToolTip = "Show one kind of view" };
                combo.Items.Add("All");
                int selected = 0;
                for (int i = 0; i < TypeOptions.Count; i++)
                {
                    combo.Items.Add(TypeOptions[i].Label + " (" + TypeOptions[i].Count + ")");
                    if (TypeOptions[i].Name == TypeName) selected = i + 1;
                }
                combo.SelectedIndex = selected;
                combo.SelectionChanged += (s, e) =>
                {
                    if (updating) return;
                    int at = combo.SelectedIndex;
                    TypeName = at <= 0 || at > TypeOptions.Count ? null : TypeOptions[at - 1].Name;
                    if (OnFilterColumns != null) OnFilterColumns();
                    Fill();
                };
                panel.Children.Add(combo);
            }
            else
            {
                string existing;
                var box = new TextBox
                {
                    Height = 22,
                    Margin = new Thickness(0, 3, 0, 0),
                    Padding = new Thickness(4, 0, 4, 0),
                    VerticalContentAlignment = VerticalAlignment.Center,
                    ToolTip = "Keyword search in this column",
                    Text = ColumnFilters.TryGetValue(field.Key, out existing) ? existing : "",
                    Tag = field.Key,
                };
                box.TextChanged += (s, e) =>
                {
                    if (updating) return;
                    ColumnFilters[(string)box.Tag] = box.Text ?? "";
                    filterTimer.Stop();
                    filterTimer.Start();
                };
                panel.Children.Add(box);
            }
            return panel;
        }

        private DataGridColumn MakeColumn(int index, VmCore.Field field)
        {
            bool combo = field.Dropdown || field.NoneLabel != null;
            string xaml = (combo ? ComboColumnXaml : TextColumnXaml)
                .Replace("{i}", index.ToString())
                .Replace("{w}", ((int)field.Width).ToString())
                .Replace("{ro}", field.Writable ? "False" : "True")
                .Replace("{al}", field.Numeric ? "Right" : "Left");
            var column = (DataGridColumn)XamlReader.Parse(xaml);
            column.Header = HeaderFor(field, index);
            return column;
        }

        /// <summary>The dropdown lists, as resources the combo cells look up.</summary>
        private void PublishLists()
        {
            for (int i = 0; i < Fields.Count; i++)
            {
                VmCore.Field f = Fields[i];
                if (!(f.Dropdown || f.NoneLabel != null)) continue;
                List<string> list;
                if (!store.Choices.TryGetValue(f.Key, out list)) list = new List<string>();
                grid.Resources["list_c" + i] = list.Select(v => Display(f, v)).ToList();
            }
        }

        /// <summary>Builds the columns and an empty table. Call when the columns change; Fill then loads the rows.</summary>
        public void BuildColumns(List<VmCore.RefRow> rows)
        {
            allRows = rows;
            updating = true;
            try
            {
                filterTimer.Stop();
                grid.ItemsSource = null;
                grid.Columns.Clear();
                labelBlocks.Clear();
                PublishLists();

                var t = new DataTable("grid");
                t.Columns.Add("sel", typeof(bool));
                t.Columns.Add("st", typeof(string));
                t.Columns.Add("vid", typeof(string));
                t.Columns.Add("g", typeof(string));

                var checkColumn = (DataGridColumn)XamlReader.Parse(CheckColumnXaml);
                headerCheck = new CheckBox { HorizontalAlignment = HorizontalAlignment.Center, ToolTip = "Tick every view shown" };
                headerCheck.Checked += (s, e) => { if (!settingHeader) SetAllChecked(true); };
                headerCheck.Unchecked += (s, e) => { if (!settingHeader) SetAllChecked(false); };
                checkColumn.Header = headerCheck;
                grid.Columns.Add(checkColumn);
                var statusColumn = (DataGridColumn)XamlReader.Parse(StatusColumnXaml);
                statusColumn.Header = new TextBlock { Text = "✎", Foreground = Res("Muted"), HorizontalAlignment = HorizontalAlignment.Center, ToolTip = "Unmodified, modified, or refused by Revit" };
                grid.Columns.Add(statusColumn);

                for (int i = 0; i < Fields.Count; i++)
                {
                    t.Columns.Add("c" + i, typeof(string));
                    t.Columns.Add("f" + i, typeof(string));
                    grid.Columns.Add(MakeColumn(i, Fields[i]));
                }
                if (OnPlus != null)
                {
                    var plus = (DataGridColumn)XamlReader.Parse(PlusColumnXaml);
                    var button = new Button
                    {
                        Content = "+",
                        Style = (Style)window.FindResource("Flat"),
                        FontSize = 18,
                        FontWeight = FontWeights.Bold,
                        Padding = new Thickness(8, 0, 8, 0),
                        ToolTip = "Add a parameter column",
                    };
                    button.Click += (s, e) => { try { OnPlus(); } catch (Exception) { } };
                    plus.Header = button;
                    grid.Columns.Add(plus);
                }
                t.ColumnChanged += OnColumnChanged;
                table = t;
            }
            finally
            {
                updating = false;
            }
            Fill();
        }

        // ---------------------------------------------------------------- filter, sort, group, fill --

        private bool Passes(VmCore.RefRow row, string[] words, Dictionary<string, string[]> colWords)
        {
            if (TypeName != null && row.TypeName != TypeName) return false;
            if (HideUnchecked && !Checked.Contains(row.ViewId)) return false;
            foreach (KeyValuePair<string, string[]> kv in colWords)
            {
                string value = store.Effective(row.ViewId, kv.Key).ToLowerInvariant();
                foreach (string w in kv.Value) if (!value.Contains(w)) return false;
            }
            if (words.Length > 0)
            {
                string hay = string.Join("\t", Fields.Select(f => store.Effective(row.ViewId, f.Key))).ToLowerInvariant();
                foreach (string w in words) if (!hay.Contains(w)) return false;
            }
            return true;
        }

        private static string[] Split(string text)
        {
            return (text ?? "").ToLowerInvariant().Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
        }

        private string GroupFieldKey()
        {
            if (Sort.Count > 0) return Sort[0].Key;
            return Fields.Count > 0 ? Fields[0].Key : "name";
        }

        private List<VmCore.RefRow> Ordered(List<VmCore.RefRow> rows)
        {
            List<SortEntry> keys = new List<SortEntry>(Sort);
            if (Grouping && keys.Count == 0 && Fields.Count > 0) keys.Add(new SortEntry { Key = Fields[0].Key });
            if (keys.Count == 0) return rows;
            var indexed = rows.Select((r, i) => new { r, i }).ToList();
            indexed.Sort((a, b) =>
            {
                foreach (SortEntry k in keys)
                {
                    int c = string.CompareOrdinal(VmCore.NaturalKey(store.Effective(a.r.ViewId, k.Key)), VmCore.NaturalKey(store.Effective(b.r.ViewId, k.Key)));
                    if (c != 0) return k.Desc ? -c : c;
                }
                return a.i.CompareTo(b.i);
            });
            return indexed.Select(t => t.r).ToList();
        }

        /// <summary>Reloads the rows through the filters, the sort and the grouping.</summary>
        public void Fill()
        {
            if (table == null) return;
            var colWords = new Dictionary<string, string[]>();
            foreach (KeyValuePair<string, string> kv in ColumnFilters)
            {
                string[] w = Split(kv.Value);
                if (w.Length > 0 && Fields.Any(f => f.Key == kv.Key)) colWords[kv.Key] = w;
            }
            string[] words = Split(GlobalSearch);
            shown = Ordered(allRows.Where(r => Passes(r, words, colWords)).ToList());

            updating = true;
            try
            {
                Dictionary<VmCore.CellKey, string> conflicts = store.Conflicts();
                var failedKeys = new HashSet<VmCore.CellKey>(Failed.Keys);
                string gkey = GroupFieldKey();
                VmCore.Field gfield = Fields.FirstOrDefault(f => f.Key == gkey);
                grid.ItemsSource = null;
                table.BeginLoadData();
                table.Rows.Clear();
                foreach (VmCore.RefRow row in shown)
                {
                    DataRow dr = table.NewRow();
                    dr["sel"] = Checked.Contains(row.ViewId);
                    dr["st"] = RowStatus(row.ViewId, failedKeys);
                    dr["vid"] = row.ViewId.ToString();
                    string g = gfield != null ? Value(row.ViewId, gfield) : store.Effective(row.ViewId, gkey);
                    dr["g"] = Grouping ? (g.Length == 0 ? "(blank)" : g) : "";
                    for (int i = 0; i < Fields.Count; i++)
                    {
                        dr["c" + i] = Value(row.ViewId, Fields[i]);
                        dr["f" + i] = Flag(row.ViewId, Fields[i], failedKeys, conflicts);
                    }
                    table.Rows.Add(dr);
                }
                table.EndLoadData();

                // the DataView keeps the order the rows were added in; groups stay together because the rows were ordered by the group key
                ICollectionView cv = CollectionViewSource.GetDefaultView(table.DefaultView);
                using (cv.DeferRefresh())
                {
                    cv.GroupDescriptions.Clear();
                    cv.SortDescriptions.Clear();
                    if (Grouping) cv.GroupDescriptions.Add(new PropertyGroupDescription("g"));
                }
                view = cv;
                grid.GroupStyle.Clear();
                if (Grouping) grid.GroupStyle.Add((GroupStyle)XamlReader.Parse(GroupStyleXaml));
                grid.ItemsSource = cv;
            }
            finally
            {
                updating = false;
            }
            MarkSort();
            SyncHeaderCheck();
            if (OnShownChanged != null) OnShownChanged();
        }

        /// <summary>Brings the flags, statuses and (optionally) the values in line with the store without rebuilding.</summary>
        public void Sync(bool values = true)
        {
            if (table == null) return;
            updating = true;
            try
            {
                Dictionary<VmCore.CellKey, string> conflicts = store.Conflicts();
                var failedKeys = new HashSet<VmCore.CellKey>(Failed.Keys);
                foreach (DataRow dr in table.Rows)
                {
                    long viewId = long.Parse((string)dr["vid"]);
                    string st = RowStatus(viewId, failedKeys);
                    if ((string)dr["st"] != st) dr["st"] = st;
                    for (int i = 0; i < Fields.Count; i++)
                    {
                        if (values)
                        {
                            string text = Value(viewId, Fields[i]);
                            if ((dr["c" + i] as string) != text) dr["c" + i] = text;
                        }
                        string flag = Flag(viewId, Fields[i], failedKeys, conflicts);
                        if ((dr["f" + i] as string) != flag) dr["f" + i] = flag;
                    }
                }
            }
            finally
            {
                updating = false;
            }
        }

        // ---------------------------------------------------------------- ticks --

        public List<long> CheckedIds()
        {
            return Checked.Where(id => store.Rows.ContainsKey(id)).OrderBy(id => id).ToList();
        }

        private void SyncHeaderCheck()
        {
            if (headerCheck == null) return;
            settingHeader = true;
            try
            {
                int ticked = shown.Count(r => Checked.Contains(r.ViewId));
                headerCheck.IsChecked = shown.Count > 0 && ticked == shown.Count;
            }
            finally
            {
                settingHeader = false;
            }
        }

        public void SetAllChecked(bool value)
        {
            foreach (VmCore.RefRow r in shown)
            {
                if (value) Checked.Add(r.ViewId);
                else Checked.Remove(r.ViewId);
            }
            if (table != null)
            {
                updating = true;
                try { foreach (DataRow dr in table.Rows) dr["sel"] = value; }
                finally { updating = false; }
            }
            if (HideUnchecked && !value) Fill();
            if (OnSelection != null) OnSelection();
        }

        // ---------------------------------------------------------------- sort and group --

        private void OnSorting(object sender, DataGridSortingEventArgs args)
        {
            try
            {
                args.Handled = true;
                string path = args.Column.SortMemberPath;
                if (string.IsNullOrEmpty(path) || !path.StartsWith("c")) return;
                int index;
                if (!int.TryParse(path.Substring(1), out index) || index < 0 || index >= Fields.Count) return;
                string key = Fields[index].Key;
                bool shift = (Keyboard.Modifiers & ModifierKeys.Shift) != 0;
                SortEntry existing = Sort.FirstOrDefault(s => s.Key == key);
                if (existing != null) existing.Desc = !existing.Desc;
                else if (shift && Sort.Count > 0)
                {
                    if (Sort.Count >= 4)
                    {
                        say("4 sort levels is as deep as it goes.", false);
                        return;
                    }
                    Sort.Add(new SortEntry { Key = key });
                }
                else
                {
                    Sort.Clear();
                    Sort.Add(new SortEntry { Key = key });
                }
                Fill();
                say(Sort.Count > 1
                    ? "Sorted by " + string.Join(", then ", Sort.Select(s => LabelOf(s.Key))) + "."
                    : "Sorted by " + LabelOf(Sort[0].Key) + ". Shift-click another heading to sort inside it.", false);
            }
            catch (Exception) { }
        }

        private string LabelOf(string key)
        {
            VmCore.Field f = Fields.FirstOrDefault(x => x.Key == key);
            return f != null ? f.Label : key;
        }

        public void ClearSort()
        {
            Sort.Clear();
            Fill();
        }

        private void MarkSort()
        {
            foreach (VmCore.Field f in Fields)
            {
                TextBlock block;
                if (!labelBlocks.TryGetValue(f.Key, out block)) continue;
                int at = Sort.FindIndex(s => s.Key == f.Key);
                string glyph = at < 0 ? "" : " " + (Sort[at].Desc ? SortDown : SortUp) + (Sort.Count > 1 ? (at + 1).ToString() : "");
                block.Text = f.Label + glyph;
            }
        }

        public void SetGrouping(bool on)
        {
            Grouping = on;
            Fill();
        }

        /// <summary>Opens or closes every group heading.</summary>
        public void ExpandAll(bool open)
        {
            foreach (ToggleButton tb in Descendants<ToggleButton>(grid))
            {
                if (tb.Name == "gt") tb.IsChecked = open;
            }
        }

        private static IEnumerable<T> Descendants<T>(DependencyObject parent) where T : DependencyObject
        {
            int count = VisualTreeHelper.GetChildrenCount(parent);
            for (int i = 0; i < count; i++)
            {
                DependencyObject child = VisualTreeHelper.GetChild(parent, i);
                var match = child as T;
                if (match != null) yield return match;
                foreach (T deeper in Descendants<T>(child)) yield return deeper;
            }
        }

        // ---------------------------------------------------------------- editing --

        private VmCore.Field FieldOfColumn(DataGridColumn column)
        {
            string key = column.SortMemberPath;
            if (string.IsNullOrEmpty(key) || !key.StartsWith("c")) return null;
            int index;
            return int.TryParse(key.Substring(1), out index) && index >= 0 && index < Fields.Count ? Fields[index] : null;
        }

        private static string CellText(object value)
        {
            return value == null || value is DBNull ? "" : value.ToString();
        }

        private void OnBeginEdit(object sender, DataGridBeginningEditEventArgs args)
        {
            try
            {
                VmCore.Field field = FieldOfColumn(args.Column);
                var item = args.Row.Item as DataRowView;
                if (field == null || item == null)
                {
                    args.Cancel = true;
                    return;
                }
                long viewId = long.Parse(CellText(item["vid"]));
                var failed = new HashSet<VmCore.CellKey>(Failed.Keys);
                if (VmCore.CellFlag(store, failed, null, viewId, field) == "r")
                {
                    args.Cancel = true;
                    VmCore.RefRow row;
                    string why;
                    if (store.Rows.TryGetValue(viewId, out row) && row.Locked.TryGetValue(field.Key, out why) && !string.IsNullOrEmpty(why)) say(why, false);
                }
            }
            catch (Exception) { }
        }

        private void OnColumnChanged(object sender, DataColumnChangeEventArgs args)
        {
            if (updating) return;
            string name = args.Column.ColumnName;
            long viewId;
            try { viewId = long.Parse(CellText(args.Row["vid"])); } catch (Exception) { return; }

            if (name == "sel")
            {
                bool on = args.Row["sel"] is bool && (bool)args.Row["sel"];
                if (on) Checked.Add(viewId);
                else Checked.Remove(viewId);
                SyncHeaderCheck();
                if (OnSelection != null) OnSelection();
                return;
            }
            if (!name.StartsWith("c")) return;
            VmCore.Field field;
            try { field = Fields[int.Parse(name.Substring(1))]; } catch (Exception) { return; }
            string text = CellText(args.Row[name]);
            if (field.NoneLabel != null && text == field.NoneLabel) text = "";
            string message;
            updating = true;
            try
            {
                string held;
                store.Stage(viewId, field.Key, text, out held, out message);
                Failed.Remove(new VmCore.CellKey(viewId, field.Key));
                args.Row[name] = Display(field, held);
            }
            finally
            {
                updating = false;
            }
            Sync(false);
            if (!string.IsNullOrEmpty(message)) say(message, true);
            if (OnChanged != null) OnChanged();
        }
    }
}
