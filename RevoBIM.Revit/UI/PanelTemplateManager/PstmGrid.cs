using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;

using Binding = System.Windows.Data.Binding;
using Border = System.Windows.Controls.Border;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using Orientation = System.Windows.Controls.Orientation;
using Popup = System.Windows.Controls.Primitives.Popup;
using TextBox = System.Windows.Controls.TextBox;
using Visibility = System.Windows.Visibility;

namespace RevoBIM.UI.PanelTemplateManager
{
    /// <summary>Hands the whole row object to a callable with the column key (pstm_grid.RowConverter).</summary>
    internal sealed class RowConverter : IValueConverter
    {
        private readonly Func<object, string, object> fn;

        public RowConverter(Func<object, string, object> fn)
        {
            this.fn = fn;
        }

        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            try
            {
                return fn(value, parameter as string);
            }
            catch (Exception)
            {
                return null;
            }
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            return null;
        }
    }

    /// <summary>
    /// The grids. Every column is a DataGridTemplateColumn whose binding is "." with an IValueConverter and the column key as ConverterParameter,
    /// which is what makes a set of columns that do not exist until the model is read possible at all. The cell converters read their brushes
    /// from the window at conversion time, so a palette switch just needs the rows refreshed.
    /// </summary>
    internal static class PstmGrid
    {
        public const string NoValue = "(blank)";

        private static Binding Bind(IValueConverter converter, string key)
        {
            return new Binding(".") { Converter = converter, ConverterParameter = key, Mode = BindingMode.OneWay };
        }

        public static DataTemplate TextCellTemplate(IValueConverter textConv, IValueConverter backConv, IValueConverter foreConv, string key,
                                                    IValueConverter boldConv = null)
        {
            var border = new FrameworkElementFactory(typeof(Border));
            border.SetBinding(Border.BackgroundProperty, Bind(backConv, key));
            border.SetValue(Border.PaddingProperty, new Thickness(7, 0, 7, 0));
            var block = new FrameworkElementFactory(typeof(TextBlock));
            block.SetBinding(TextBlock.TextProperty, Bind(textConv, key));
            block.SetBinding(TextBlock.ForegroundProperty, Bind(foreConv, key));
            if (boldConv != null) block.SetBinding(TextBlock.FontWeightProperty, Bind(boldConv, key));
            block.SetValue(FrameworkElement.VerticalAlignmentProperty, VerticalAlignment.Center);
            block.SetValue(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis);
            block.SetBinding(FrameworkElement.ToolTipProperty, Bind(textConv, key));
            border.AppendChild(block);
            return new DataTemplate { VisualTree = border };
        }

        /// <summary>
        /// The swap dropdown in every row. Both handlers are attached to the factory, not to the grid: Loaded is a Direct routed event, so a handler
        /// registered on the DataGrid is never called for a cell's ComboBox.
        /// </summary>
        public static DataTemplate ComboCellTemplate(IValueConverter backConv, string key, RoutedEventHandler onLoaded, SelectionChangedEventHandler onChanged)
        {
            var border = new FrameworkElementFactory(typeof(Border));
            border.SetBinding(Border.BackgroundProperty, Bind(backConv, key));
            border.SetValue(Border.PaddingProperty, new Thickness(4, 1, 4, 1));
            var combo = new FrameworkElementFactory(typeof(ComboBox));
            combo.SetValue(FrameworkElement.HeightProperty, 30.0);
            combo.SetValue(ComboBox.MaxDropDownHeightProperty, 320.0);
            if (onLoaded != null) combo.AddHandler(FrameworkElement.LoadedEvent, onLoaded);
            if (onChanged != null) combo.AddHandler(Selector.SelectionChangedEvent, onChanged);
            border.AppendChild(combo);
            return new DataTemplate { VisualTree = border };
        }

        /// <summary>A column sized in stars shares the grid's width and grows with the window.</summary>
        public static DataGridTemplateColumn MakeColumn(object header, DataTemplate cell, double? width, string key, double minWidth = 70, double? star = null, bool sortable = true)
        {
            var column = new DataGridTemplateColumn { Header = header, CellTemplate = cell, MinWidth = minWidth };
            if (star != null && star.Value != 0) column.Width = new DataGridLength(star.Value, DataGridLengthUnitType.Star);
            else if (width != null && width.Value != 0) column.Width = new DataGridLength(width.Value, DataGridLengthUnitType.Pixel);
            else column.Width = new DataGridLength(1.0, DataGridLengthUnitType.Star);
            try
            {
                if (sortable) column.SortMemberPath = key;
                else column.CanUserSort = false;
            }
            catch (Exception)
            {
            }
            return column;
        }
    }

    /// <summary>A column heading: a label (or a parameter picker), a keyword search box and an Excel style tick filter.</summary>
    internal sealed class ColumnHeader
    {
        private readonly Action onSearch;
        private readonly Action<string, string> onParamChange;
        private readonly Action<ColumnHeader> onFilterOpen;

        public readonly string Key;
        public TextBox SearchBox;
        public ComboBox ParamCombo;
        public ToggleButton Toggle;
        public Popup Popup;
        public HashSet<string> Allowed;   // null = no filter on this column
        public bool Suppress;
        public readonly StackPanel Content;

        public ColumnHeader(string key, string title, Action onSearch, Action<ColumnHeader> onFilterOpen = null, List<string> paramItems = null,
                            Action<string, string> onParamChange = null, bool searchable = true)
        {
            Key = key;
            this.onSearch = onSearch;
            this.onParamChange = onParamChange;
            this.onFilterOpen = onFilterOpen;

            var panel = new StackPanel { Orientation = Orientation.Vertical, Margin = new Thickness(0) };
            var top = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 3) };
            if (paramItems != null)
            {
                var combo = new ComboBox { Height = 32, MinWidth = 84, HorizontalAlignment = HorizontalAlignment.Stretch, MaxDropDownHeight = 340, Tag = "pick a parameter" };
                foreach (string item in paramItems) combo.Items.Add(item);
                combo.SelectionChanged += OnParamChanged;
                ParamCombo = combo;
                top.Children.Add(combo);
            }
            else
            {
                top.Children.Add(new TextBlock { Text = title, VerticalAlignment = VerticalAlignment.Center });
            }
            if (onFilterOpen != null)
            {
                var toggle = new ToggleButton { Margin = new Thickness(4, 0, 0, 0) };
                toggle.SetResourceReference(FrameworkElement.StyleProperty, "FilterCaret");
                toggle.Checked += (s, a) =>
                {
                    if (this.onFilterOpen != null) this.onFilterOpen(this);
                };
                toggle.Unchecked += (s, a) =>
                {
                    if (Popup != null)
                    {
                        try { Popup.IsOpen = false; } catch (Exception) { }
                    }
                };
                Toggle = toggle;
                top.Children.Add(toggle);
            }
            panel.Children.Add(top);
            if (searchable)
            {
                var box = new TextBox { Height = 32, Tag = "search" };
                box.TextChanged += (s, a) =>
                {
                    if (Suppress) return;
                    if (this.onSearch != null) this.onSearch();
                };
                SearchBox = box;
                panel.Children.Add(box);
            }
            Content = panel;
        }

        private void OnParamChanged(object sender, SelectionChangedEventArgs args)
        {
            NameTooltip();
            if (Suppress) return;
            if (onParamChange != null) onParamChange(Key, ParamCombo.SelectedItem as string ?? "");
        }

        private void NameTooltip()
        {
            try
            {
                string chosen = ParamCombo.SelectedItem as string ?? "";
                ParamCombo.ToolTip = chosen.Length > 0 ? chosen : "Pick a parameter for this column";
            }
            catch (Exception)
            {
            }
        }

        public string SearchText
        {
            get { return SearchBox == null ? "" : (SearchBox.Text ?? "").Trim().ToLowerInvariant(); }
        }

        public void SetParam(string name)
        {
            if (ParamCombo == null) return;
            Suppress = true;
            try
            {
                if (!string.IsNullOrEmpty(name) && ParamCombo.Items.Cast<object>().Any(i => (i as string) == name)) ParamCombo.SelectedItem = name;
                else ParamCombo.SelectedIndex = -1;
            }
            finally
            {
                Suppress = false;
            }
            NameTooltip();
        }

        public void Clear()
        {
            Suppress = true;
            try
            {
                if (SearchBox != null) SearchBox.Text = "";
            }
            finally
            {
                Suppress = false;
            }
            Allowed = null;
            Mark();
        }

        public void Mark()
        {
            if (Toggle == null) return;
            try
            {
                Toggle.SetResourceReference(Control.ForegroundProperty, Allowed != null ? "OrangeBrush" : "MutedBrush");
            }
            catch (Exception)
            {
            }
        }

        public bool Passes(string text)
        {
            string value = text ?? "";
            string needle = SearchText;
            if (needle.Length > 0 && value.ToLowerInvariant().IndexOf(needle, StringComparison.Ordinal) < 0) return false;
            if (Allowed != null && !Allowed.Contains(value.Length > 0 ? value : PstmGrid.NoValue)) return false;
            return true;
        }
    }

    /// <summary>
    /// The tick list behind a column header's caret. Ticking follows Excel's autofilter: everything ticked means no filter, unticking
    /// narrows, nothing ticked shows nothing.
    /// </summary>
    internal sealed class TickFilter
    {
        private readonly ColumnHeader header;
        private readonly Action onApply;
        private readonly TextBox search;
        private readonly StackPanel host;
        private readonly List<CheckBox> checks = new List<CheckBox>();

        public readonly Popup Popup;

        public TickFilter(ColumnHeader header, IEnumerable<string> values, Action onApply)
        {
            this.header = header;
            this.onApply = onApply;
            Popup = new Popup { StaysOpen = false, AllowsTransparency = true, Placement = PlacementMode.Bottom, PlacementTarget = header.Toggle };
            Popup.Closed += (s, a) =>
            {
                try
                {
                    if (this.header.Toggle != null) this.header.Toggle.IsChecked = false;
                }
                catch (Exception)
                {
                }
            };
            var border = new Border { CornerRadius = new CornerRadius(4.0), BorderThickness = new Thickness(1), Padding = new Thickness(8), MinWidth = 210 };
            border.SetResourceReference(Border.BackgroundProperty, "PopupBg");
            border.SetResourceReference(Border.BorderBrushProperty, "WindowEdge");
            var panel = new StackPanel();
            search = new TextBox { Height = 30, Margin = new Thickness(0, 0, 0, 5) };
            search.TextChanged += (s, a) => Search();
            panel.Children.Add(search);
            var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 5) };
            var allBtn = new Button { Content = "All", Margin = new Thickness(0, 0, 4, 0) };
            allBtn.SetResourceReference(FrameworkElement.StyleProperty, "GhostButton");
            allBtn.Click += (s, a) => SetVisible(true);
            var noneBtn = new Button { Content = "None" };
            noneBtn.SetResourceReference(FrameworkElement.StyleProperty, "GhostButton");
            noneBtn.Click += (s, a) => SetVisible(false);
            row.Children.Add(allBtn);
            row.Children.Add(noneBtn);
            panel.Children.Add(row);
            var scroller = new ScrollViewer
            {
                MaxHeight = 260,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
            };
            host = new StackPanel();
            scroller.Content = host;
            panel.Children.Add(scroller);
            var applyBtn = new Button { Content = "Filter", Margin = new Thickness(0, 6, 0, 0) };
            applyBtn.Click += (s, a) => Apply();
            panel.Children.Add(applyBtn);
            border.Child = panel;
            Popup.Child = border;

            HashSet<string> allowed = header.Allowed;
            foreach (string value in values)
            {
                var box = new CheckBox { Content = value, Margin = new Thickness(0, 2, 0, 2), IsChecked = allowed == null || allowed.Contains(value) };
                checks.Add(box);
                host.Children.Add(box);
            }
        }

        public void Show()
        {
            Popup.IsOpen = true;
        }

        private void Search()
        {
            string needle = (search.Text ?? "").Trim().ToLowerInvariant();
            foreach (CheckBox box in checks)
            {
                bool visible = needle.Length == 0 || ((box.Content as string) ?? "").ToLowerInvariant().Contains(needle);
                box.Visibility = visible ? Visibility.Visible : Visibility.Collapsed;
            }
        }

        private void SetVisible(bool value)
        {
            foreach (CheckBox box in checks)
                if (box.Visibility == Visibility.Visible) box.IsChecked = value;
        }

        private void Apply()
        {
            var ticked = new HashSet<string>(checks.Where(b => b.IsChecked == true).Select(b => (string)b.Content));
            if (ticked.Count == checks.Count) header.Allowed = null;   // everything ticked means no filter
            else header.Allowed = ticked;
            header.Mark();
            Popup.IsOpen = false;
            if (onApply != null) onApply();
        }
    }
}
