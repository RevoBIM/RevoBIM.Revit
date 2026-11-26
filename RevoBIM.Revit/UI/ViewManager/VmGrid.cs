using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Markup;
using RevoBIM.Tools.ViewManager;

namespace RevoBIM.UI.ViewManager
{
    /// <summary>
    /// One DataGrid over one EditStore (port of GridHost). Builds the table, keeps the cell looks right, and turns an edit in
    /// a cell into a staged edit - or puts the cell back and says why not. Each cell binds to its own entry in a DataTable,
    /// and a second entry beside it holds the flag the look is chosen from.
    /// </summary>
    internal sealed class VmGridHost
    {
        private const string ColumnXaml = @"<DataGridTemplateColumn
    xmlns=""http://schemas.microsoft.com/winfx/2006/xaml/presentation""
    xmlns:x=""http://schemas.microsoft.com/winfx/2006/xaml""
    SortMemberPath=""c{i}"" Width=""{w}"" MinWidth=""60"" IsReadOnly=""{ro}"">
  <DataGridTemplateColumn.CellTemplate>
    <DataTemplate>
      <Border x:Name=""bd"" Background=""Transparent"" Padding=""7,0,7,0"" MinHeight=""24"">
        <TextBlock x:Name=""tx"" Text=""{Binding [c{i}]}"" VerticalAlignment=""Center""
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

        private const string PlusColumnXaml = @"<DataGridTemplateColumn
    xmlns=""http://schemas.microsoft.com/winfx/2006/xaml/presentation""
    Width=""46"" MinWidth=""46"" IsReadOnly=""True"" CanUserSort=""False""
    CanUserResize=""False"" CanUserReorder=""False"">
  <DataGridTemplateColumn.CellTemplate>
    <DataTemplate><Border Background=""Transparent""/></DataTemplate>
  </DataGridTemplateColumn.CellTemplate>
</DataGridTemplateColumn>";

        private const string SortUp = " ▲";
        private const string SortDown = " ▼";

        private readonly Window window;
        private readonly DataGrid grid;
        private readonly VmCore.EditStore store;
        private readonly Action<string, bool> say;

        public List<VmCore.Field> Fields = new List<VmCore.Field>();
        public Func<long, string> Virtual;                       // view id -> preview text
        public Dictionary<VmCore.CellKey, string> Failed = new Dictionary<VmCore.CellKey, string>();
        public Dictionary<VmCore.CellKey, string> Conflicts = new Dictionary<VmCore.CellKey, string>();
        private DataTable table;
        private bool updating;
        public string SortKey;
        public bool SortDesc;
        public HashSet<string> Removable = new HashSet<string>();
        public HashSet<string> ChoiceKeys = new HashSet<string>();
        public Action<long, VmCore.Field> OnChoose;
        public List<long> DownSel = new List<long>();
        public Action<string> OnSort;
        public Action OnPlus;
        public Action<string> OnRemove;
        public Action OnChanged;
        public Action OnSelection;

        public VmGridHost(Window window, DataGrid grid, VmCore.EditStore store, Action<string, bool> say)
        {
            this.window = window;
            this.grid = grid;
            this.store = store;
            this.say = say;
            grid.BeginningEdit += OnBeginEdit;
            grid.Sorting += OnSorting;
            grid.SelectionChanged += OnSelected;
            grid.PreviewMouseLeftButtonDown += OnMouseDown;
        }

        // ---------------------------------------------------------------- values and looks --

        private string Value(long viewId, VmCore.Field field)
        {
            if (field.Kind == "preview") return Virtual != null ? Virtual(viewId) : "";
            return store.Effective(viewId, field.Key);
        }

        private string Flag(long viewId, VmCore.Field field)
        {
            if (field.Kind == "preview") return "r";
            return VmCore.CellFlag(store, Failed.Keys.ToList(), Conflicts, viewId, field);
        }

        private static string CellText(object value)
        {
            if (value == null || value is DBNull) return "";
            return value.ToString();
        }

        /// <summary>Bring every cell in line with the store without rebuilding.</summary>
        public void Sync(bool values = true)
        {
            if (table == null) return;
            updating = true;
            try
            {
                Conflicts = store.Conflicts();
                var failedKeys = new HashSet<VmCore.CellKey>(Failed.Keys);
                foreach (DataRow dr in table.Rows)
                {
                    long viewId = long.Parse((string)dr["vid"]);
                    for (int i = 0; i < Fields.Count; i++)
                    {
                        VmCore.Field field = Fields[i];
                        if (values)
                        {
                            string text = Value(viewId, field);
                            if (CellText(dr["c" + i]) != text) dr["c" + i] = text;
                        }
                        string flag = field.Kind == "preview" ? "r" : VmCore.CellFlag(store, failedKeys, Conflicts, viewId, field);
                        if (CellText(dr["f" + i]) != flag) dr["f" + i] = flag;
                    }
                }
            }
            finally
            {
                updating = false;
            }
        }

        // ---------------------------------------------------------------- building --

        private object HeaderElement(VmCore.Field field)
        {
            var panel = new StackPanel { Orientation = Orientation.Horizontal };
            string text = field.Label;
            if (SortKey == field.Key) text += SortDesc ? SortDown : SortUp;
            panel.Children.Add(new TextBlock { Text = text, VerticalAlignment = VerticalAlignment.Center });
            if (Removable.Contains(field.Key))
            {
                var button = new Button
                {
                    Content = "✕",
                    Style = (Style)window.FindResource("Flat"),
                    Foreground = (System.Windows.Media.Brush)window.Resources["Muted"],
                    Margin = new Thickness(8, 0, 0, 0),
                    Padding = new Thickness(4, 0, 4, 0),
                    FontSize = 10,
                    ToolTip = "Remove this column",
                    Tag = field.Key,
                };
                button.Click += OnRemoveClick;
                panel.Children.Add(button);
            }
            return panel;
        }

        private DataGridColumn MakeColumn(int index, VmCore.Field field)
        {
            string xaml = ColumnXaml.Replace("{i}", index.ToString()).Replace("{w}", ((int)field.Width).ToString()).Replace("{ro}", field.Writable ? "False" : "True");
            // the Replace above also touched the bindings' {Binding [c{i}]} - the braces around Binding are untouched
            var column = (DataGridColumn)XamlReader.Parse(xaml);
            column.Header = HeaderElement(field);
            return column;
        }

        private DataGridColumn MakePlusColumn()
        {
            var column = (DataGridColumn)XamlReader.Parse(PlusColumnXaml);
            var button = new Button
            {
                Content = "+",
                Style = (Style)window.FindResource("Flat"),
                FontSize = 18,
                FontWeight = FontWeights.Bold,
                Padding = new Thickness(8, 0, 8, 0),
                ToolTip = "Add a column",
            };
            button.Click += OnPlusClick;
            column.Header = button;
            return column;
        }

        public void Build(IEnumerable<VmCore.RefRow> rows)
        {
            updating = true;
            try
            {
                Conflicts = store.Conflicts();
                grid.ItemsSource = null;
                grid.Columns.Clear();
                var t = new DataTable("grid");
                for (int i = 0; i < Fields.Count; i++)
                {
                    t.Columns.Add("c" + i, typeof(string));
                    t.Columns.Add("f" + i, typeof(string));
                    grid.Columns.Add(MakeColumn(i, Fields[i]));
                }
                t.Columns.Add("vid", typeof(string));
                if (OnPlus != null) grid.Columns.Add(MakePlusColumn());
                var failedKeys = new HashSet<VmCore.CellKey>(Failed.Keys);
                t.BeginLoadData();
                foreach (VmCore.RefRow row in rows)
                {
                    DataRow dr = t.NewRow();
                    for (int i = 0; i < Fields.Count; i++)
                    {
                        dr["c" + i] = Value(row.ViewId, Fields[i]);
                        dr["f" + i] = Fields[i].Kind == "preview" ? "r" : VmCore.CellFlag(store, failedKeys, Conflicts, row.ViewId, Fields[i]);
                    }
                    dr["vid"] = row.ViewId.ToString();
                    t.Rows.Add(dr);
                }
                t.EndLoadData();
                t.ColumnChanged += OnColumnChanged;
                table = t;
                grid.ItemsSource = t.DefaultView;
            }
            finally
            {
                updating = false;
            }
        }

        public List<long> SelectedIds()
        {
            var ids = new List<long>();
            try
            {
                foreach (object item in grid.SelectedItems)
                {
                    var row = item as DataRowView;
                    long id;
                    if (row != null && long.TryParse(CellText(row["vid"]), out id)) ids.Add(id);
                }
            }
            catch (Exception) { }
            return ids;
        }

        // ---------------------------------------------------------------- events --

        private VmCore.Field FieldOfColumn(DataGridColumn column)
        {
            string key = column.SortMemberPath;
            if (string.IsNullOrEmpty(key) || !key.StartsWith("c")) return null;
            int index;
            if (!int.TryParse(key.Substring(1), out index) || index < 0 || index >= Fields.Count) return null;
            return Fields[index];
        }

        private void OnMouseDown(object sender, MouseButtonEventArgs args)
        {
            // A click inside a multi-selection collapses it to one row before the edit starts, so remember what was selected.
            try { DownSel = SelectedIds(); } catch (Exception) { DownSel = new List<long>(); }
        }

        private void OnBeginEdit(object sender, DataGridBeginningEditEventArgs args)
        {
            try
            {
                VmCore.Field field = FieldOfColumn(args.Column);
                if (field == null)
                {
                    args.Cancel = true;
                    return;
                }
                var item = args.Row.Item as DataRowView;
                if (item == null) return;
                long viewId = long.Parse(CellText(item["vid"]));
                if (ChoiceKeys.Contains(field.Key) && OnChoose != null)
                {
                    // a column with a fixed list opens the list, not a text box
                    args.Cancel = true;
                    if (Flag(viewId, field) == "r")
                    {
                        VmCore.RefRow row;
                        string why;
                        if (store.Rows.TryGetValue(viewId, out row) && row.Locked.TryGetValue(field.Key, out why) && !string.IsNullOrEmpty(why)) say(why, false);
                    }
                    else OnChoose(viewId, field);
                    return;
                }
                if (Flag(viewId, field) == "r")
                {
                    args.Cancel = true;
                    VmCore.RefRow row;
                    string why;
                    if (store.Rows.TryGetValue(viewId, out row) && row.Locked.TryGetValue(field.Key, out why) && !string.IsNullOrEmpty(why)) say(why, false);
                }
            }
            catch (Exception) { }
        }

        private void OnSorting(object sender, DataGridSortingEventArgs args)
        {
            try
            {
                args.Handled = true;
                VmCore.Field field = FieldOfColumn(args.Column);
                if (field != null && OnSort != null) OnSort(field.Key);
            }
            catch (Exception) { }
        }

        private void OnSelected(object sender, SelectionChangedEventArgs args)
        {
            try { if (OnSelection != null) OnSelection(); } catch (Exception) { }
        }

        private void OnPlusClick(object sender, RoutedEventArgs args)
        {
            try { if (OnPlus != null) OnPlus(); } catch (Exception) { }
        }

        private void OnRemoveClick(object sender, RoutedEventArgs args)
        {
            try
            {
                args.Handled = true;
                if (OnRemove != null) OnRemove((string)((FrameworkElement)sender).Tag);
            }
            catch (Exception) { }
        }

        private void OnColumnChanged(object sender, DataColumnChangeEventArgs args)
        {
            if (updating) return;
            string name = args.Column.ColumnName;
            if (!name.StartsWith("c")) return;
            VmCore.Field field;
            long viewId;
            try
            {
                int index = int.Parse(name.Substring(1));
                field = Fields[index];
                viewId = long.Parse(CellText(args.Row["vid"]));
            }
            catch (Exception) { return; }
            string text = CellText(args.Row[name]);
            string message;
            updating = true;
            try
            {
                string held;
                store.Stage(viewId, field.Key, text, out held, out message);
                Failed.Remove(new VmCore.CellKey(viewId, field.Key));
                args.Row[name] = held;
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
