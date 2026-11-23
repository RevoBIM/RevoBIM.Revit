using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Threading;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.FindInView;

using Binding = System.Windows.Data.Binding;
using Grid = System.Windows.Controls.Grid;
using Panel = System.Windows.Controls.Panel;
using TextBox = System.Windows.Controls.TextBox;
using Visibility = System.Windows.Visibility;

namespace RevoBIM.UI.FindInView
{
    /// <summary>The grid binds the row object itself with the column key as ConverterParameter.</summary>
    internal sealed class FivCellConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            var row = value as ViewRow;
            return row == null ? "" : row.Cell(parameter as string ?? "");
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            return null;
        }
    }

    /// <summary>
    /// The main Find in View window: the selection and filters on the left, the views on the right.
    /// Port of FindInViewWindow in fiv_window.py. Modal: nothing has to be picked in the model while it is
    /// open, and the active view cannot be changed with a modal dialog up anyway - so the window closes
    /// first and the view is opened afterwards by the command.
    /// </summary>
    internal sealed class FivWindow
    {
        private static readonly object[][] Columns =
        {
            new object[] { "name", "View", 3.0, 200.0 },
            new object[] { "type", "Type", 1.2, 110.0 },
            new object[] { "level", "Level", 1.0, 80.0 },
            new object[] { "scale", "Scale", 0.7, 62.0 },
        };

        private static readonly string[] IdLabels = { "Id", "Ids" };
        private const string CopyTip = "Copy to the clipboard, ready for Revit's Select Elements by ID";

        private readonly UIDocument uidoc;
        private readonly UIApplication uiapp;
        private readonly Dictionary<string, string> settings;
        private readonly List<ViewRow> rows;
        private readonly bool alreadyTiled;
        private readonly HashSet<long> openViewIds;
        private readonly bool reuseTile;
        private readonly Window window;
        private readonly FivChrome chrome;
        private readonly FivDrawer drawer;
        private readonly FivCellConverter cellConverter = new FivCellConverter();
        private readonly Dictionary<string, CheckBox> typeBoxes = new Dictionary<string, CheckBox>();

        private string themeMode;
        private string palette;
        private string sortKey = "name";
        private bool sortAscending = true;
        private bool restoredSelection;
        private string hiddenLastView = "";
        private List<string> typeLabels = new List<string>();
        private bool whereOpen;
        private DispatcherTimer copyTimer;
        private List<string> selectionLevels = new List<string>();

        public ViewRow ResultRow;
        public List<Element> Elements;
        public List<ElementId> ElementIds;
        public List<ElementId> CategoryIds;
        public List<string> CategoryNames;

        public FivWindow(UIDocument uidoc, UIApplication uiapp, Dictionary<string, string> settings, List<ViewRow> rows,
                         List<Element> elements, List<ElementId> elementIds, List<ElementId> categoryIds,
                         List<string> categoryNames, bool alreadyTiled, IEnumerable<long> openViewIds)
        {
            this.uidoc = uidoc;
            this.uiapp = uiapp;
            this.settings = settings;
            this.rows = rows;
            Elements = elements;
            ElementIds = elementIds;
            CategoryIds = categoryIds;
            CategoryNames = categoryNames;
            this.alreadyTiled = alreadyTiled;
            this.openViewIds = new HashSet<long>(openViewIds ?? new long[0]);
            reuseTile = FivCore.AsBool(FivCore.Get(settings, "reuse_tile"), true);
            themeMode = FivCore.CleanThemeMode(FivCore.Get(settings, "theme_mode"));
            palette = FivUi.PaletteFor(settings);
            // the levels the selection sits on: the list opens narrowed to the plans cut at them, and Show all views lifts it
            selectionLevels = ReadLevels();

            window = FivXaml.LoadWindow("FindInView.xaml", palette);
            var header = F<Border>("HeaderBar");
            chrome = new FivChrome(window, header);
            drawer = new FivDrawer(window, header, F<Panel>("RootGrid"), F<Button>("ShrinkBtn"), F<UIElement>("PathShrink"),
                                   F<UIElement>("PathExpand"), F<Border>("RootBorder"), F<UIElement>("GripLayer"));
            chrome.Drawer = drawer;

            BuildChrome();
            BuildTypes();
            BuildColumns();
            RestoreChoices();
            Wire();
            DescribeSelection();
            DescribeLevels();
            Refresh();
        }

        private T F<T>(string name) where T : class
        {
            return (T)window.FindName(name);
        }

        // ------------------------------------------------------------------------------ levels --

        private List<string> ReadLevels()
        {
            try
            {
                return FivModel.SelectionLevels(uidoc.Document, Elements);
            }
            catch (Exception)
            {
                return new List<string>();
            }
        }

        private ISet<string> LevelFilter()
        {
            if (selectionLevels.Count == 0) return null;
            if (F<CheckBox>("ChkShowAll").IsChecked == true) return null;
            return new HashSet<string>(selectionLevels);
        }

        /// <summary>Says what the list is narrowed to, so a short list is explained.</summary>
        private void DescribeLevels()
        {
            var note = F<TextBlock>("LevelNote");
            var tick = F<CheckBox>("ChkShowAll");
            if (Elements.Count == 0)
            {
                // nothing selected - nothing to narrow by, and no tick to offer
                F<UIElement>("LevelBar").Visibility = Visibility.Collapsed;
                return;
            }
            F<UIElement>("LevelBar").Visibility = Visibility.Visible;
            if (selectionLevels.Count == 0)
            {
                note.Text = "The selection has no level, so every view is shown.";
                note.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush");
                tick.IsEnabled = false;
                return;
            }
            tick.IsEnabled = true;
            string names = string.Join(", ", selectionLevels.Take(4));
            if (selectionLevels.Count > 4) names += " +" + (selectionLevels.Count - 4);
            if (tick.IsChecked == true)
            {
                note.Text = "Showing every view. Untick to see only plans on " + names + ".";
                note.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush");
            }
            else
            {
                note.Text = "Plans on " + names;
                note.SetResourceReference(TextBlock.ForegroundProperty, "OrangeBrush");
            }
        }

        // ------------------------------------------------------------------------------- setup --

        private void BuildChrome()
        {
            F<TextBlock>("VersionText").Text = "v" + FivCore.Version;
            F<TextBlock>("TitleTool").Text = FivCore.ToolName;
            var icon = F<Image>("HeaderIcon");
            FivXaml.LoadIcon(icon);
            EggHook.Attach(window, () => palette, icon);
            var grips = new Dictionary<string, Thumb>();
            foreach (string name in new[] { "N", "S", "E", "W", "NE", "NW", "SE", "SW" })
            {
                try
                {
                    grips[name] = F<Thumb>("Grip" + name);
                }
                catch (Exception)
                {
                    grips[name] = null;
                }
            }
            chrome.AttachGrips(grips);
            LabelThemeChip();
        }

        /// <summary>The chip names the MODE it is in; the tooltip says what Auto read Revit's canvas as.</summary>
        private void LabelThemeChip()
        {
            try
            {
                var chip = F<Button>("ThemeChip");
                chip.Content = FivCore.ThemeChip(themeMode);
                if (themeMode == "follow")
                {
                    string reading = FivUi.RevitTheme();
                    chip.ToolTip = reading != null
                        ? "Following Revit - the canvas is " + reading + ". Click for Dark, Light, then back to Auto."
                        : "Following Revit, but this release will not say which theme it is in, so dark is used. Click for Dark, Light, Auto.";
                }
                else
                {
                    chip.ToolTip = "Fixed to " + FivCore.ThemeChip(themeMode) + ". Click to change; Auto follows Revit.";
                }
            }
            catch (Exception)
            {
            }
        }

        /// <summary>One tick box per view type actually present in this project.</summary>
        private void BuildTypes()
        {
            typeLabels = FivModel.ViewTypesPresent(rows);
            List<string> wanted = FivCore.UnpackList(FivCore.Get(settings, "view_types"));
            foreach (string label in typeLabels)
            {
                var box = new CheckBox
                {
                    Content = label,
                    IsChecked = wanted.Count == 0 || wanted.Contains(label),
                    Margin = new Thickness(2, 1, 2, 1),
                };
                try
                {
                    box.SetResourceReference(FrameworkElement.StyleProperty, "ThemedCheckBox");
                }
                catch (Exception)
                {
                }
                box.Checked += (s, a) => TypeToggled();
                box.Unchecked += (s, a) => TypeToggled();
                typeBoxes[label] = box;
            }
            FillTypeList("");
        }

        private void FillTypeList(string query)
        {
            var list = F<ListBox>("ViewTypeList");
            list.Items.Clear();
            foreach (string label in typeLabels)
                if (FivCore.MatchesKeywords(label, query)) list.Items.Add(typeBoxes[label]);
            UpdateTypeCount();
        }

        private void UpdateTypeCount()
        {
            F<TextBlock>("TypeCountText").Text = TickedTypes().Count + " of " + typeLabels.Count;
        }

        private void BuildColumns()
        {
            var grid = F<DataGrid>("ViewGrid");
            grid.Columns.Clear();
            foreach (object[] spec in Columns)
            {
                string key = (string)spec[0];
                var factory = new FrameworkElementFactory(typeof(TextBlock));
                factory.SetBinding(TextBlock.TextProperty, new Binding(".") { Converter = cellConverter, ConverterParameter = key });
                factory.SetValue(FrameworkElement.VerticalAlignmentProperty, VerticalAlignment.Center);
                factory.SetValue(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis);
                var column = new DataGridTemplateColumn
                {
                    Header = (string)spec[1],
                    CellTemplate = new DataTemplate { VisualTree = factory },
                    SortMemberPath = key,
                    // star sized with a minimum, never fixed pixels
                    Width = new DataGridLength((double)spec[2], DataGridLengthUnitType.Star),
                    MinWidth = (double)spec[3],
                };
                grid.Columns.Add(column);
            }
        }

        private void RestoreChoices()
        {
            F<CheckBox>("ChkOpenTiled").IsChecked = FivCore.AsBool(FivCore.Get(settings, "open_tiled"));
            F<CheckBox>("ChkUnhide").IsChecked = FivCore.AsBool(FivCore.Get(settings, "unhide_categories"), true);
            F<CheckBox>("ChkZoomHere").IsChecked = FivCore.AsBool(FivCore.Get(settings, "zoom_here"), true);
            SetWhere(FivCore.AsBool(FivCore.Get(settings, "where_open")));
            DescribeTiling();
            if (FivCore.AsBool(FivCore.Get(settings, "remember_search"))) F<TextBox>("SearchBox").Text = FivCore.Get(settings, "search");

            int width = FivCore.AsInt(FivCore.Get(settings, "window_width"), 1040);
            int height = FivCore.AsInt(FivCore.Get(settings, "window_height"), 860);
            if (height == FivCore.OldWindowHeight) height = 860;
            try
            {
                // never taller than the screen can hold
                height = Math.Min(height, (int)SystemParameters.WorkArea.Height - 24);
            }
            catch (Exception)
            {
            }
            if (width >= window.MinWidth) window.Width = width;
            if (height >= window.MinHeight) window.Height = height;
            int panel = FivCore.AsInt(FivCore.Get(settings, "panel_width"), 300);
            if (panel > 0)
            {
                F<ColumnDefinition>("PanelColumn").Width = new GridLength(panel, GridUnitType.Star);
                F<ColumnDefinition>("ListColumn").Width = new GridLength(Math.Max(width - panel, 380), GridUnitType.Star);
            }
        }

        private void Wire()
        {
            F<Button>("CloseBtn").Click += (s, a) => Close();
            F<Button>("CancelBtn").Click += (s, a) => Close();
            F<Button>("ThemeChip").Click += (s, a) => ChangeTheme();
            F<Button>("FullScreenBtn").Click += (s, a) => chrome.ToggleFullScreen();
            F<Button>("ShowMeBtn").Click += (s, a) => ShowMe();
            F<Button>("TypeAll").Click += (s, a) => { foreach (CheckBox box in typeBoxes.Values) box.IsChecked = true; };
            F<Button>("TypeNone").Click += (s, a) => { foreach (CheckBox box in typeBoxes.Values) box.IsChecked = false; };
            F<TextBox>("TypeSearch").TextChanged += (s, a) => FillTypeList(F<TextBox>("TypeSearch").Text ?? "");
            F<TextBox>("SearchBox").TextChanged += (s, a) => Refresh();
            F<CheckBox>("ChkShowAll").Checked += (s, a) => ShowAllChanged();
            F<CheckBox>("ChkShowAll").Unchecked += (s, a) => ShowAllChanged();
            F<TextBox>("IdBox").TextChanged += (s, a) => IdTyped();
            F<Button>("FindIdBtn").Click += (s, a) => FindId();
            F<CheckBox>("ChkOpenTiled").Checked += (s, a) => { DescribeTiling(); UpdateShowMe(); };
            F<CheckBox>("ChkOpenTiled").Unchecked += (s, a) => { DescribeTiling(); UpdateShowMe(); };
            F<Button>("WhereHeader").Click += (s, a) => SetWhere(!whereOpen);
            foreach (string name in new[] { "ChkOpenTiled", "ChkZoomHere", "ChkUnhide" })
            {
                F<CheckBox>(name).Checked += (s, a) => UpdateWhereSummary();
                F<CheckBox>(name).Unchecked += (s, a) => UpdateWhereSummary();
            }
            // the list is as tall as its contents and the whole left panel scrolls, so the wheel over it
            // has to scroll the panel - a ListBox swallows it
            F<ListBox>("ViewTypeList").PreviewMouseWheel += (s, a) =>
            {
                try
                {
                    var scroll = F<ScrollViewer>("LeftScroll");
                    scroll.ScrollToVerticalOffset(scroll.VerticalOffset - a.Delta);
                    a.Handled = true;
                }
                catch (Exception)
                {
                }
            };

            var grid = F<DataGrid>("ViewGrid");
            grid.SelectionChanged += (s, a) => { UpdateShowMe(); DescribeTiling(); };
            grid.MouseDoubleClick += (s, a) =>
            {
                if (grid.SelectedItem != null) ShowMe();
            };
            grid.Sorting += OnSorting;

            window.PreviewKeyDown += OnKey;
            window.Loaded += (s, a) => OnLoaded();
        }

        // ------------------------------------------------------------------- the selection card --

        private void DescribeSelection()
        {
            DescribeProperties();
            if (Elements.Count == 0)
            {
                F<TextBlock>("SelectionText").Text = "Nothing selected. Show Me will open the view without zooming, or find an element by id below.";
                return;
            }
            Dictionary<string, int> counts = FivModel.CategoryCounts(Elements);
            var parts = counts.Keys.OrderBy(k => k, StringComparer.Ordinal).Select(k => counts[k] + " x " + k).ToList();
            string text = FivCore.Plural(Elements.Count, "element") + " selected";
            if (parts.Count > 0) text += "\n" + string.Join("\n", parts);
            F<TextBlock>("SelectionText").Text = text;
        }

        /// <summary>The properties panel, built as WPF elements in code and rebuilt whenever the selection changes.</summary>
        private void DescribeProperties()
        {
            var panel = F<StackPanel>("PropsPanel");
            var card = F<Border>("PropsCard");
            panel.Children.Clear();
            if (Elements.Count == 0)
            {
                card.Visibility = Visibility.Collapsed;
                return;
            }

            List<Tuple<string, string, string>> props;
            try
            {
                props = FivModel.SelectionProperties(uidoc.Document, Elements);
            }
            catch (Exception err)
            {
                props = new List<Tuple<string, string, string>> { Tuple.Create("Properties", "could not be read: " + err.Message, "") };
            }

            foreach (var item in props)
            {
                string label = item.Item1, value = item.Item2, note = item.Item3;
                var row = new Grid { Margin = new Thickness(0, 1, 0, 1) };
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(74) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

                var name = new TextBlock { Text = label, FontSize = 11.5 };
                name.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush");
                Grid.SetColumn(name, 0);

                UIElement reading;
                if (IdLabels.Contains(label))
                {
                    reading = IdCell(string.IsNullOrEmpty(value) ? "-" : value, label == "Id");
                }
                else
                {
                    var text = new TextBlock { Text = string.IsNullOrEmpty(value) ? "-" : value, FontSize = 12, TextWrapping = TextWrapping.Wrap };
                    // the level is what this panel is for, so it reads as the answer
                    text.SetResourceReference(TextBlock.ForegroundProperty, label.StartsWith("Level") ? "OrangeBrush" : "TextBrush");
                    reading = text;
                }
                Grid.SetColumn(reading, 1);
                row.Children.Add(name);
                row.Children.Add(reading);
                panel.Children.Add(row);

                if (note.Length > 0)
                {
                    var aside = new TextBlock { Text = note, FontSize = 10.5, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(74, 0, 0, 3) };
                    aside.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush");
                    panel.Children.Add(aside);
                }
            }
            card.Visibility = Visibility.Visible;
        }

        /// <summary>The id in blue, bold and a size up, with a Copy button beside it.</summary>
        private UIElement IdCell(string text, bool single)
        {
            var cell = new Grid();
            cell.ColumnDefinitions.Add(new ColumnDefinition { Width = single ? GridLength.Auto : new GridLength(1, GridUnitType.Star) });
            cell.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            if (single) cell.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            var reading = new TextBlock
            {
                Text = text,
                FontSize = 14.5,
                FontWeight = FontWeights.Bold,
                TextWrapping = TextWrapping.Wrap,
                VerticalAlignment = VerticalAlignment.Center,
            };
            reading.SetResourceReference(TextBlock.ForegroundProperty, "BlueBrush");
            Grid.SetColumn(reading, 0);

            var icon = new Path { Width = 14, Height = 14, StrokeThickness = 1.3, Data = Geometry.Parse(FivCore.CopyIcon) };
            icon.SetResourceReference(Shape.StrokeProperty, "MutedBrush");
            var copy = new Button
            {
                Content = icon,
                Margin = new Thickness(10, 0, 0, 0),
                Padding = new Thickness(7, 3, 7, 3),
                VerticalAlignment = VerticalAlignment.Center,
                ToolTip = CopyTip,
            };
            copy.SetResourceReference(FrameworkElement.StyleProperty, "ChipButton");
            copy.Click += (s, a) => CopyIds(copy, icon);
            Grid.SetColumn(copy, 1);

            cell.Children.Add(reading);
            cell.Children.Add(copy);
            return cell;
        }

        private void CopyIds(Button button, Path icon)
        {
            string text = FivModel.SelectionIdText(Elements);
            bool done = text.Length > 0 && FivUi.CopyText(text);
            FivLog.Write("copy: " + Elements.Count + " ids -> " + (done ? "copied" : "not copied"));
            icon.Data = Geometry.Parse(done ? FivCore.CopiedIcon : FivCore.NotCopiedIcon);
            icon.SetResourceReference(Shape.StrokeProperty, done ? "GreenBrush" : "RedBrush");
            button.ToolTip = done ? "Copied" : "Not copied - the clipboard was busy, try again";
            try
            {
                if (copyTimer != null) copyTimer.Stop();
            }
            catch (Exception)
            {
            }
            var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(FivCore.CopyFlashMs) };
            copyTimer = timer;
            timer.Tick += (s, a) =>
            {
                try
                {
                    timer.Stop();
                    icon.Data = Geometry.Parse(FivCore.CopyIcon);
                    icon.SetResourceReference(Shape.StrokeProperty, "MutedBrush");
                    button.ToolTip = CopyTip;
                }
                catch (Exception)
                {
                }
            };
            timer.Start();
        }

        // --------------------------------------------------------------------- where it opens --

        private void SetWhere(bool opened)
        {
            whereOpen = opened;
            F<UIElement>("WherePanel").Visibility = opened ? Visibility.Visible : Visibility.Collapsed;
            F<UIElement>("PathWhereOpen").Visibility = opened ? Visibility.Visible : Visibility.Collapsed;
            F<UIElement>("PathWhereClosed").Visibility = opened ? Visibility.Collapsed : Visibility.Visible;
            UpdateWhereSummary();
        }

        /// <summary>Shut, the header still says how many of the options are on.</summary>
        private void UpdateWhereSummary()
        {
            var switches = new List<bool>
            {
                F<CheckBox>("ChkOpenTiled").IsChecked == true,
                F<CheckBox>("ChkZoomHere").IsChecked == true,
                F<CheckBox>("ChkUnhide").IsChecked == true,
            };
            F<TextBlock>("WhereSummary").Text = whereOpen ? "" : FivCore.WhereSummary(switches);
        }

        // --------------------------------------------------------------------------- by id --

        private void IdTyped()
        {
            F<Button>("FindIdBtn").IsEnabled = FivCore.ParseIds(F<TextBox>("IdBox").Text).Count > 0;
        }

        /// <summary>
        /// Selects an element by id without leaving the tool. It becomes the selection Revit shows the
        /// properties for AND the selection Show Me will zoom to.
        /// </summary>
        private void FindId()
        {
            List<string> tokens = FivCore.ParseIds(F<TextBox>("IdBox").Text);
            if (tokens.Count == 0) return;
            List<Element> elements;
            List<ElementId> ids;
            List<string> missing;
            FivModel.FindByIds(uidoc.Document, tokens, out elements, out ids, out missing);
            FivLog.Write("find-id: typed " + tokens.Count + ", found " + elements.Count + ", missing [" + string.Join(", ", missing) + "]");
            if (elements.Count == 0)
            {
                F<TextBlock>("IdStatus").Text = "Nothing in this model has " + (tokens.Count == 1 ? "that id" : "those ids") + ".";
                return;
            }

            Elements = elements;
            ElementIds = ids;
            List<ElementId> categoryIds;
            List<string> categoryNames;
            FivModel.CategoriesOf(elements, out categoryIds, out categoryNames);
            CategoryIds = categoryIds;
            CategoryNames = categoryNames;
            FivModel.SelectElements(uidoc, ids);
            try
            {
                uidoc.RefreshActiveView();
            }
            catch (Exception)
            {
            }

            string note = "Selected " + FivCore.Plural(elements.Count, "element") + " in Revit.";
            if (missing.Count > 0)
                note += " Not in this model: " + string.Join(", ", missing.Take(6)) + (missing.Count > 6 ? "..." : "");
            F<TextBlock>("IdStatus").Text = note;
            DescribeSelection();
            // a new selection can sit on a different level: narrow the list to it
            selectionLevels = ReadLevels();
            DescribeLevels();
            Refresh();
            UpdateStatus();
            UpdateShowMe();
        }

        // ------------------------------------------------------------------------- filters --

        private List<string> TickedTypes()
        {
            return typeLabels.Where(l => typeBoxes.ContainsKey(l) && typeBoxes[l].IsChecked == true).ToList();
        }

        private List<ViewRow> VisibleRows()
        {
            var ticked = new HashSet<string>(TickedTypes());
            string query = F<TextBox>("SearchBox").Text ?? "";
            ISet<string> levels = LevelFilter();
            IEnumerable<ViewRow> found = rows.Where(r => FivModel.PassesFilters(r, ticked, query, levels));
            string key = sortKey;
            Comparison<ViewRow> compare = (a, b) => FivCore.NaturalCompare(a.Cell(key), b.Cell(key));
            var comparer = Comparer<ViewRow>.Create(compare);
            // stable, like the Python sort it replaces
            return (sortAscending ? found.OrderBy(r => r, comparer) : found.OrderByDescending(r => r, comparer)).ToList();
        }

        private void Refresh()
        {
            var grid = F<DataGrid>("ViewGrid");
            object previous = grid.SelectedItem;
            List<ViewRow> visible = VisibleRows();
            grid.ItemsSource = visible;

            if (previous != null && visible.Contains((ViewRow)previous))
            {
                grid.SelectedItem = previous;
            }
            else if (visible.Count > 0 && !restoredSelection)
            {
                // the last view used is re-selected once, on open - not on every refresh, or it would
                // fight the user every time a filter moves
                restoredSelection = true;
                long wantedId = FivCore.AsInt(FivCore.Get(settings, "last_view_id"), 0);
                string wantedName = FivCore.Get(settings, "last_view");
                ViewRow remembered = FivModel.FindRemembered(visible, wantedId, wantedName);
                if (remembered != null)
                {
                    grid.SelectedItem = remembered;
                    ScrollToSelection();
                }
                else
                {
                    // in the project but filtered out is worth saying, rather than leaving the list looking arbitrary
                    ViewRow hidden = FivModel.FindRemembered(rows, wantedId, wantedName);
                    hiddenLastView = hidden != null ? hidden.Name : "";
                }
            }

            F<TextBlock>("CountText").Text = visible.Count + " of " + rows.Count;
            UpdateStatus();
            UpdateShowMe();
        }

        private void UpdateStatus()
        {
            var parts = new List<string>
            {
                Elements.Count == 0 ? "nothing selected" : FivCore.Plural(Elements.Count, "element") + " selected",
            };
            if (CategoryNames.Count > 0) parts.Add(FivCore.Plural(CategoryNames.Count, "category", "categories"));
            F<TextBlock>("StatusText").Text = string.Join("   |   ", parts);
        }

        /// <summary>The button goes green the moment there is a view to go to.</summary>
        private void UpdateShowMe()
        {
            var row = F<DataGrid>("ViewGrid").SelectedItem as ViewRow;
            F<Button>("ShowMeBtn").IsEnabled = row != null;
            var hint = F<TextBlock>("HintText");
            if (row != null)
            {
                string beside = F<CheckBox>("ChkOpenTiled").IsChecked == true ? " beside the current view" : "";
                string ending = Elements.Count > 0 ? " and zooms to the selection." : ".";
                hint.Text = "Show Me opens \"" + row.Name + "\"" + beside + ending;
            }
            else if (hiddenLastView.Length > 0)
            {
                hint.Text = "The view you used last, \"" + hiddenLastView + "\", is not on the selection's level or is hidden by the " +
                            "view types or the search. Tick Show all views to see it.";
            }
            else
            {
                hint.Text = "Pick a view. Double click one to go straight to it.";
            }
        }

        private void TypeToggled()
        {
            UpdateTypeCount();
            Refresh();
        }

        private void ShowAllChanged()
        {
            DescribeLevels();
            Refresh();
        }

        private bool TargetAlreadyOpen()
        {
            var row = F<DataGrid>("ViewGrid").SelectedItem as ViewRow;
            return row != null && openViewIds.Contains(row.ViewId.Value);
        }

        /// <summary>Says plainly what tiling will do, including what it closes.</summary>
        private void DescribeTiling()
        {
            string text;
            if (F<CheckBox>("ChkOpenTiled").IsChecked == true)
            {
                if (alreadyTiled && TargetAlreadyOpen())
                    text = "That view is already open in its own tile. It is just brought forward - nothing closes and nothing re-tiles.";
                else if (alreadyTiled && reuseTile)
                    text = "Revit is already tiled. The first tile that is not the one you came from is closed and the view opens in its place. Your layout is not re-tiled.";
                else if (openViewIds.Count > 1)
                    text = "More than one view is open, so the layout is left alone and the view opens into it.";
                else
                    text = "The view you came from is the only one open, so it stays open and Revit tiles the two side by side.";
            }
            else
            {
                text = "The view opens over the one you came from, as Revit normally does.";
            }
            F<TextBlock>("TileHint").Text = text;
        }

        /// <summary>Brings the selected row into view; the layout is forced first because a DataGrid will not scroll to something it has not laid out.</summary>
        private void ScrollToSelection()
        {
            var grid = F<DataGrid>("ViewGrid");
            object row = grid.SelectedItem;
            if (row == null) return;
            try
            {
                grid.UpdateLayout();
            }
            catch (Exception)
            {
            }
            try
            {
                grid.ScrollIntoView(row);
            }
            catch (Exception)
            {
            }
        }

        private void OnLoaded()
        {
            ScrollToSelection();
            // typing is the usual next move - an id when there is nothing selected yet, a view name when there is
            TextBox box = FivCore.FirstField(Elements.Count > 0) == FivCore.FieldId ? F<TextBox>("IdBox") : F<TextBox>("SearchBox");
            try
            {
                box.Focus();
                Keyboard.Focus(box);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Sorts the row list and cancels the event: the grid binds row objects, not properties.</summary>
        private void OnSorting(object sender, DataGridSortingEventArgs args)
        {
            try
            {
                string key = args.Column.SortMemberPath;
                if (key == sortKey)
                {
                    sortAscending = !sortAscending;
                }
                else
                {
                    sortKey = key;
                    sortAscending = true;
                }
                args.Column.SortDirection = sortAscending ? ListSortDirection.Ascending : ListSortDirection.Descending;
                args.Handled = true;
                Refresh();
            }
            catch (Exception)
            {
            }
        }

        private void ChangeTheme()
        {
            themeMode = FivCore.NextThemeMode(themeMode);
            palette = FivCore.ResolvePalette(themeMode, FivUi.RevitTheme());
            FivTheme.Apply(window, palette);
            LabelThemeChip();
            BuildColumns();
            Refresh();
        }

        private void OnKey(object sender, KeyEventArgs args)
        {
            try
            {
                if (drawer.Shrunk)
                {
                    // nothing but reopening, while the window is out of sight
                    if (args.Key == Key.Escape || args.Key == Key.Enter || args.Key == Key.F11 || FivUi.IsShrinkKey(args))
                    {
                        drawer.Expand();
                        args.Handled = true;
                    }
                    return;
                }
                if (FivUi.IsShrinkKey(args))
                {
                    drawer.Toggle();
                    args.Handled = true;
                }
                else if (args.Key == Key.Escape)
                {
                    if (chrome.FullScreen) chrome.ToggleFullScreen();
                    else Close();
                }
                else if (args.Key == Key.F11)
                {
                    chrome.ToggleFullScreen();
                }
                else if (args.Key == Key.Enter)
                {
                    // Enter in the id box means Find, not Show Me
                    if (F<TextBox>("IdBox").IsKeyboardFocusWithin)
                    {
                        if (F<Button>("FindIdBtn").IsEnabled) FindId();
                        args.Handled = true;
                    }
                    else if (F<Button>("ShowMeBtn").IsEnabled)
                    {
                        ShowMe();
                    }
                }
            }
            catch (Exception)
            {
            }
        }

        private void ShowMe()
        {
            var row = F<DataGrid>("ViewGrid").SelectedItem as ViewRow;
            if (row == null) return;
            ResultRow = row;
            settings["last_view"] = row.Name;
            settings["last_view_id"] = row.ViewId.Value.ToString();
            FivLog.Write("show-me: '" + row.Name + "' (" + row.ViewId.Value + ", " + row.TypeLabel + ") with " + Elements.Count + " element(s)");
            Save();
            window.Close();
        }

        private void Close()
        {
            drawer.RestoreNow();
            Save();
            window.Close();
        }

        // ----------------------------------------------------------------------------- settings --

        private void Save()
        {
            try
            {
                settings["theme_mode"] = themeMode;
                List<string> ticked = TickedTypes();
                settings["view_types"] = ticked.Count == typeLabels.Count ? "" : FivCore.PackList(ticked);
                settings["open_tiled"] = F<CheckBox>("ChkOpenTiled").IsChecked == true ? "1" : "0";
                settings["unhide_categories"] = F<CheckBox>("ChkUnhide").IsChecked == true ? "1" : "0";
                settings["zoom_here"] = F<CheckBox>("ChkZoomHere").IsChecked == true ? "1" : "0";
                settings["where_open"] = whereOpen ? "1" : "0";
                if (FivCore.AsBool(FivCore.Get(settings, "remember_search"))) settings["search"] = F<TextBox>("SearchBox").Text ?? "";
                if (!chrome.FullScreen)
                {
                    settings["window_width"] = ((int)window.Width).ToString();
                    // parked, the window IS the bar - saving that height would reopen the tool as a 60 pixel sliver next time
                    settings["window_height"] = ((int)drawer.TrueHeight()).ToString();
                    int panel = (int)F<ColumnDefinition>("PanelColumn").ActualWidth;
                    if (panel > 0) settings["panel_width"] = panel.ToString();
                }
                FivCore.SaveSettings(settings);
            }
            catch (Exception)
            {
            }
        }

        // ------------------------------------------------------------------------------- run --

        public ViewRow Show()
        {
            FivUi.OwnToRevit(window, uiapp);
            window.ShowDialog();
            return ResultRow;
        }
    }
}
