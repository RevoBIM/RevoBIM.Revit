using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.FilterManager;
using Color = System.Windows.Media.Color;
using Ellipse = System.Windows.Shapes.Ellipse;
using Point = System.Windows.Point;
using ComboBox = System.Windows.Controls.ComboBox;
using Panel = System.Windows.Controls.Panel;
using TextBox = System.Windows.Controls.TextBox;
using Grid = System.Windows.Controls.Grid;
using Visibility = System.Windows.Visibility;
using Window = System.Windows.Window;

namespace RevoBIM.UI.FilterManager
{
    /// <summary>Message boxes (pyRevit forms.alert).</summary>
    public static class FmMessage
    {
        public static void Alert(string message, string title = FmCore.Title)
        {
            try
            {
                var d = new TaskDialog(title) { MainInstruction = title, MainContent = message, CommonButtons = TaskDialogCommonButtons.Close };
                d.Show();
            }
            catch (Exception) { MessageBox.Show(message, title); }
        }

        /// <summary>A Yes / No question; true on Yes.</summary>
        public static bool Confirm(string message, string title = FmCore.Title)
        {
            try
            {
                var d = new TaskDialog(title)
                {
                    MainInstruction = title,
                    MainContent = message,
                    CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No,
                    DefaultButton = TaskDialogResult.No,
                };
                return d.Show() == TaskDialogResult.Yes;
            }
            catch (Exception) { return MessageBox.Show(message, title, MessageBoxButton.YesNo) == MessageBoxResult.Yes; }
        }
    }

    /// <summary>
    /// Common to every Filter Manager window: loads a pyRevit layout, applies the palette, owns the drawer
    /// (shrink to the title bar) and the header drag. The layout's named elements are reached with Find.
    /// </summary>
    public abstract class FmWindowBase
    {
        public Window Win;
        public FmDrawer Drawer;

        protected void Init(string layout)
        {
            Win = FmXaml.Load<Window>(layout, this);
            FmUi.ApplyPalette(Win);
            Drawer = new FmDrawer(Win);
        }

        public T Find<T>(string name) where T : class
        {
            T found = Win.FindName(name) as T;
            if (found == null) throw new InvalidOperationException("the layout has no " + typeof(T).Name + " named " + name);
            return found;
        }

        public TextBlock Text(string name) { return Find<TextBlock>(name); }
        public TextBox Box(string name) { return Find<TextBox>(name); }
        public Button Btn(string name) { return Find<Button>(name); }
        public ComboBox Combo(string name) { return Find<ComboBox>(name); }
        public CheckBox Check(string name) { return Find<CheckBox>(name); }
        public ListBox List(string name) { return Find<ListBox>(name); }

        protected void SetVersion()
        {
            try { Text("txtVersion").Text = FmCore.Version; }
            catch (Exception) { }
        }

        public Window Owner { get { return Win.Owner; } set { try { Win.Owner = value; } catch (Exception) { } } }

        public void ShowDialog() { Win.ShowDialog(); }
        public void Close() { Win.Close(); }

        /// <summary>Slide down to the title bar, or back up again.</summary>
        public void OnShrink(object sender, RoutedEventArgs args) { Drawer.Toggle(); }

        public void OnDrag(object sender, MouseButtonEventArgs args)
        {
            if (FmDrawer.OnHeaderDown(Drawer, Win, args)) return;
            try { Win.DragMove(); }
            catch (Exception) { }
        }

        /// <summary>The tool's own icon, for the header image. Cosmetics can never take a tool down.</summary>
        public static void ApplyIcon(Image image)
        {
            try
            {
                if (image == null) return;
                var assembly = typeof(FmWindowBase).Assembly;
                using (Stream stream = assembly.GetManifestResourceStream("RevoBIM.Resources.FilterManager.icon.large.png")
                                       ?? assembly.GetManifestResourceStream("RevoBIM.Resources.FilterManager.icon.png"))
                {
                    if (stream == null) return;
                    var bmp = new BitmapImage();
                    bmp.BeginInit();
                    bmp.CacheOption = BitmapCacheOption.OnLoad;
                    bmp.StreamSource = stream;
                    bmp.EndInit();
                    bmp.Freeze();
                    image.Source = bmp;
                }
            }
            catch (Exception) { }
        }
    }

    // ===========================================================================
    //  Result window
    // ===========================================================================
    public class FmDoneWindow : FmWindowBase
    {
        private readonly string _logPath;

        public FmDoneWindow(string headline, string subtitle, string stats, string logTitle, IEnumerable<string> lines, string logPath)
        {
            Init("done.xaml");
            _logPath = logPath;
            ApplyIcon(Find<Image>("imgIcon"));
            SetVersion();
            Text("txtSubtitle").Text = "  " + subtitle;
            Text("txtHeadline").Text = headline;
            Text("txtStats").Text = stats;
            Text("txtLogTitle").Text = logTitle;
            var list = List("lstLog");
            foreach (string line in lines) list.Items.Add(line);
            Text("txtPath").Text = logPath ?? "";
        }

        public void OnOpenLog(object sender, RoutedEventArgs args)
        {
            if (string.IsNullOrEmpty(_logPath) || !FmCore.OpenExternally(_logPath))
                FmMessage.Alert("Could not open the log file:\n" + _logPath);
        }

        public void OnClose(object sender, RoutedEventArgs args) { Win.Close(); }
    }

    // ===========================================================================
    //  Create filter window
    // ===========================================================================
    public class FmCreateWindow : FmWindowBase
    {
        private readonly List<Tuple<ElementId, string>> _all;
        private readonly Dictionary<string, bool> _state = new Dictionary<string, bool>();
        private readonly Document _doc;
        /// <summary>(name, categories) once accepted; null when cancelled.</summary>
        public Tuple<string, List<ElementId>> Result;

        public FmCreateWindow(Document doc, List<Tuple<ElementId, string>> categories, string suggestedName)
        {
            Init("create.xaml");
            _doc = doc;
            SetVersion();
            _all = categories;
            Box("txtName").Text = suggestedName;
            foreach (var c in categories) _state[c.Item2] = false;
            Fill();
        }

        private void Fill()
        {
            string key = Box("txtCatSearch").Text.ToLowerInvariant().Trim();
            var list = List("lstCategories");
            list.Items.Clear();
            foreach (var c in _all)
            {
                if (key.Length > 0 && c.Item2.ToLowerInvariant().IndexOf(key, StringComparison.Ordinal) < 0) continue;
                bool on;
                CheckBox cb = FmUi.NewCheckBox(c.Item2, c.Item1, _state.TryGetValue(c.Item2, out on) && on);
                cb.Checked += FmUi.Safe(OnTick, "tick");
                cb.Unchecked += FmUi.Safe(OnTick, "tick");
                list.Items.Add(cb);
            }
            UpdateCount();
        }

        private void Harvest()
        {
            foreach (CheckBox item in List("lstCategories").Items.OfType<CheckBox>())
                _state[(string)item.Content] = item.IsChecked == true;
        }

        private void UpdateCount()
        {
            Text("txtCatCount").Text = _state.Values.Count(v => v) + " selected";
        }

        private void OnTick(object sender, RoutedEventArgs args) { Harvest(); UpdateCount(); }

        public void OnCatSearch(object sender, RoutedEventArgs args) { Harvest(); Fill(); }

        public void OnAll(object sender, RoutedEventArgs args)
        {
            foreach (CheckBox item in List("lstCategories").Items.OfType<CheckBox>()) item.IsChecked = true;
            Harvest();
            UpdateCount();
        }

        public void OnNone(object sender, RoutedEventArgs args)
        {
            foreach (CheckBox item in List("lstCategories").Items.OfType<CheckBox>()) item.IsChecked = false;
            Harvest();
            UpdateCount();
        }

        public void OnCancel(object sender, RoutedEventArgs args) { Result = null; Win.Close(); }

        public void OnOk(object sender, RoutedEventArgs args)
        {
            Harvest();
            string name = Box("txtName").Text.Trim();
            var picked = _all.Where(c => _state.ContainsKey(c.Item2) && _state[c.Item2]).Select(c => c.Item1).ToList();
            var warn = Text("txtWarn");
            if (name.Length == 0) { warn.Text = "Give the filter a name."; return; }
            if (picked.Count == 0) { warn.Text = "Pick at least one category."; return; }
            foreach (ParameterFilterElement f in FmFilters.GetAllFilters(_doc))
            {
                try
                {
                    if (string.Equals(f.Name, name, StringComparison.OrdinalIgnoreCase))
                    {
                        warn.Text = "A filter called that already exists.";
                        return;
                    }
                }
                catch (Exception) { }
            }
            Result = Tuple.Create(name, picked);
            Win.Close();
        }
    }

    // ===========================================================================
    //  Batch rename - find and replace, prefix and suffix, previewed first
    // ===========================================================================
    public class FmRenameWindow : FmWindowBase
    {
        private readonly List<KeyValuePair<object, string>> _rows;
        private readonly List<string> _existing;
        private List<FmRenameResult> _results = new List<FmRenameResult>();
        /// <summary>(key, new name) for every filter to rename, once accepted; null when cancelled.</summary>
        public List<KeyValuePair<object, string>> Result;

        public FmRenameWindow(List<KeyValuePair<object, string>> rows, List<string> existing)
        {
            Init("rename.xaml");
            SetVersion();
            _rows = rows;
            _existing = existing;
            Text("txtSubject").Text = rows.Count + " filter(s) selected";
            Refresh();
        }

        private void Refresh()
        {
            _results = FmNames.Plan(_rows, _existing, Box("txtFind").Text, Box("txtReplace").Text,
                                    Check("chkMatchCase").IsChecked == true, Box("txtPrefix").Text, Box("txtSuffix").Text);
            var panel = Find<StackPanel>("pnlPreview");
            panel.Children.Clear();
            foreach (FmRenameResult r in _results) panel.Children.Add(PreviewRow(r.Old, r.New, r.Problem));

            var blocking = FmNames.Blocking(_results);
            var changing = FmNames.Changing(_results);
            var warn = Text("txtWarn");
            if (blocking.Count > 0)
                warn.Text = blocking.Count + " row(s) need looking at - nothing will be written until they are fixed.";
            else if (changing.Count == 0) warn.Text = "Nothing would change yet.";
            else warn.Text = "";

            var apply = Btn("btnApplyRename");
            apply.IsEnabled = changing.Count > 0 && blocking.Count == 0;
            apply.Content = changing.Count > 0 ? "RENAME " + changing.Count : "RENAME";
        }

        private UIElement PreviewRow(string old, string @new, string problem)
        {
            var grid = new Grid { Margin = new Thickness(0, 0, 0, 3) };
            grid.ColumnDefinitions.Add(FmUi.Col(1));
            grid.ColumnDefinitions.Add(FmUi.Col(1));
            grid.ColumnDefinitions.Add(FmUi.Col(1.1));

            Func<string, string, TextBlock> cell = (text, key) =>
            {
                var block = new TextBlock { Text = text, FontSize = 11, TextTrimming = FmUi.Trim(), Margin = new Thickness(0, 0, 8, 0) };
                block.SetResourceReference(TextBlock.ForegroundProperty, key);
                return block;
            };

            FmUi.Place(cell(old, "Dim"), grid, 0);
            if (!string.IsNullOrEmpty(problem) && problem != "unchanged")
            {
                FmUi.Place(cell(@new, "Red"), grid, 1);
                FmUi.Place(cell(problem, "Red"), grid, 2);
            }
            else if (problem == "unchanged")
            {
                FmUi.Place(cell(@new, "Dim"), grid, 1);
                FmUi.Place(cell("unchanged", "Dim"), grid, 2);
            }
            else
            {
                FmUi.Place(cell(@new, "Orange"), grid, 1);
                FmUi.Place(cell("", "Dim"), grid, 2);
            }
            return grid;
        }

        public void OnRuleChanged(object sender, RoutedEventArgs args) { Refresh(); }

        public void OnCancel(object sender, RoutedEventArgs args) { Result = null; Win.Close(); }

        public void OnOk(object sender, RoutedEventArgs args)
        {
            var changing = FmNames.Changing(_results);
            if (changing.Count == 0 || FmNames.Blocking(_results).Count > 0) return;
            Result = changing.Select(r => new KeyValuePair<object, string>(r.Key, r.New)).ToList();
            Win.Close();
        }
    }

    // ===========================================================================
    //  Colour picker - the same shape as Revit's own colour dialog
    // ===========================================================================
    public class FmColourWindow : FmWindowBase
    {
        /// <summary>Kept for the session, like Revit's own row.</summary>
        public static readonly List<string> CustomColours = new List<string>();

        private const double FieldW = 236.0;
        private const double FieldH = 188.0;
        private const double LumH = 188.0;

        /// <summary>("colour", "RRGGBB") or ("none", null); null when cancelled.</summary>
        public Tuple<string, string> Result;

        private bool _loading = true;
        private int[] _original;
        private int[] _rgb;
        private int[] _hsl;
        private string _dragging;

        public FmColourWindow(string currentHex)
        {
            Init("colour.xaml");
            SetVersion();
            int[] start = FmColour.FromHex(currentHex) ?? new[] { 128, 128, 128 };
            _original = start;
            _rgb = start;
            _hsl = FmColour.RgbToHsl(start[0], start[1], start[2]);

            BuildSwatches(Find<Panel>("pnlBasic"), FmColour.BasicColours, 0);
            BuildSwatches(Find<Panel>("pnlCustom"), CustomColours, 8);

            FmUi.PaintSwatch(Find<Border>("pnlOriginal"), FmColour.ToHex(_original));
            PaintField();
            PaintLum();
            PushToBoxes();
            _loading = false;

            var field = Find<Border>("pnlField");
            field.MouseLeftButtonDown += FmUi.SafeMouse(OnFieldDown, "on_field_down");
            field.MouseMove += FmUi.SafeMouseMove(OnFieldMove, "on_field_move");
            field.MouseLeftButtonUp += FmUi.SafeMouse(OnFieldUp, "on_field_up");
            var lum = Find<Border>("pnlLum");
            lum.MouseLeftButtonDown += FmUi.SafeMouse(OnLumDown, "on_lum_down");
            lum.MouseMove += FmUi.SafeMouseMove(OnLumMove, "on_lum_move");
            lum.MouseLeftButtonUp += FmUi.SafeMouse(OnLumUp, "on_lum_up");
        }

        // -- swatch grids ---------------------------------------------------------
        private void BuildSwatches(Panel panel, IEnumerable<string> colours, int padTo)
        {
            panel.Children.Clear();
            var items = colours.ToList();
            while (items.Count < padTo) items.Add(null);
            foreach (string hexv in items)
            {
                var cell = new Border
                {
                    Width = 27, Height = 21, Margin = new Thickness(0, 0, 4, 4), BorderBrush = FmUi.PBrush("EdgeStrong"),
                    BorderThickness = new Thickness(1), Cursor = FmUi.CursorHand(),
                };
                FmUi.PaintSwatch(cell, hexv ?? FmUi.PColour("FieldDeep").Substring(3));
                if (hexv != null)
                {
                    string value = hexv;
                    cell.MouseLeftButtonDown += FmUi.SafeMouse((s, a) => SetRgb(FmColour.FromHex(value)), "pick swatch");
                }
                panel.Children.Add(cell);
            }
        }

        // -- the two gradients ----------------------------------------------------
        private void PaintField()
        {
            var stops = new GradientStopCollection();
            for (int i = 0; i < 7; i++)
            {
                double hue = (FmColour.HueMax / 6.0) * i;
                int[] c = FmColour.HslToRgb(hue, FmColour.SatMax, FmColour.LumMax / 2.0);
                stops.Add(new GradientStop(FmUi.Colour(c[0], c[1], c[2]), i / 6.0));
            }
            Find<Border>("pnlField").Background = new LinearGradientBrush(stops) { StartPoint = new Point(0, 0), EndPoint = new Point(1, 0) };

            var fade = new GradientStopCollection
            {
                new GradientStop(FmUi.Colour(128, 128, 128, 0), 0.0),
                new GradientStop(FmUi.Colour(128, 128, 128, 255), 1.0),
            };
            Find<Border>("pnlFieldShade").Background = new LinearGradientBrush(fade) { StartPoint = new Point(0, 0), EndPoint = new Point(0, 1) };
        }

        private void PaintLum()
        {
            int[] mid = FmColour.HslToRgb(_hsl[0], _hsl[1], FmColour.LumMax / 2.0);
            var stops = new GradientStopCollection
            {
                new GradientStop(FmUi.Colour(255, 255, 255), 0.0),
                new GradientStop(FmUi.Colour(mid[0], mid[1], mid[2]), 0.5),
                new GradientStop(FmUi.Colour(0, 0, 0), 1.0),
            };
            Find<Border>("pnlLum").Background = new LinearGradientBrush(stops) { StartPoint = new Point(0, 0), EndPoint = new Point(0, 1) };
        }

        private void PaintMarks()
        {
            var fieldMarks = Find<Canvas>("pnlFieldMarks");
            fieldMarks.Children.Clear();
            var ring = new Ellipse { Width = 11, Height = 11, Stroke = FmUi.PBrush("TabActiveTxt"), StrokeThickness = 2 };
            double x = (_hsl[0] / FmColour.HueMax) * FieldW;
            double y = (1.0 - (_hsl[1] / FmColour.SatMax)) * FieldH;
            Canvas.SetLeft(ring, x - 5.5);
            Canvas.SetTop(ring, y - 5.5);
            fieldMarks.Children.Add(ring);

            var lumMarks = Find<Canvas>("pnlLumMarks");
            lumMarks.Children.Clear();
            var arrow = new Polygon
            {
                Points = new PointCollection { new Point(0, 0), new Point(8, 5), new Point(0, 10) },
                Fill = FmUi.PBrush("Orange"),
            };
            double ly = (1.0 - (_hsl[2] / FmColour.LumMax)) * LumH;
            Canvas.SetLeft(arrow, 0);
            Canvas.SetTop(arrow, ly - 5);
            lumMarks.Children.Add(arrow);
        }

        // -- state ----------------------------------------------------------------
        private void SetRgb(int[] rgb)
        {
            if (rgb == null) return;
            _rgb = rgb;
            _hsl = FmColour.RgbToHsl(rgb[0], rgb[1], rgb[2]);
            AfterChange();
        }

        private void SetHsl(int[] hsl)
        {
            _hsl = hsl;
            _rgb = FmColour.HslToRgb(hsl[0], hsl[1], hsl[2]);
            AfterChange();
        }

        private void AfterChange() { PaintLum(); PushToBoxes(); }

        private void PushToBoxes()
        {
            _loading = true;
            try
            {
                Box("txtHue").Text = _hsl[0].ToString();
                Box("txtSat").Text = _hsl[1].ToString();
                Box("txtLum").Text = _hsl[2].ToString();
                Box("txtRed").Text = _rgb[0].ToString();
                Box("txtGreen").Text = _rgb[1].ToString();
                Box("txtBlue").Text = _rgb[2].ToString();
                Box("txtHex").Text = FmColour.ToHex(_rgb);
                Text("txtName").Text = "RGB " + _rgb[0] + "-" + _rgb[1] + "-" + _rgb[2];
                FmUi.PaintSwatch(Find<Border>("pnlNew"), FmColour.ToHex(_rgb));
                PaintMarks();
            }
            finally { _loading = false; }
        }

        private static int? ReadInt(TextBox box, int high)
        {
            int v;
            if (!int.TryParse(box.Text.Trim(), out v)) return null;
            return (int)FmColour.Clamp(v, 0, high);
        }

        public void OnHslTyped(object sender, RoutedEventArgs args)
        {
            if (_loading) return;
            int? h = ReadInt(Box("txtHue"), (int)FmColour.HueMax);
            int? s = ReadInt(Box("txtSat"), (int)FmColour.SatMax);
            int? l = ReadInt(Box("txtLum"), (int)FmColour.LumMax);
            if (h == null || s == null || l == null) return;
            SetHsl(new[] { h.Value, s.Value, l.Value });
        }

        public void OnRgbTyped(object sender, RoutedEventArgs args)
        {
            if (_loading) return;
            int? r = ReadInt(Box("txtRed"), 255);
            int? g = ReadInt(Box("txtGreen"), 255);
            int? b = ReadInt(Box("txtBlue"), 255);
            if (r == null || g == null || b == null) return;
            SetRgb(new[] { r.Value, g.Value, b.Value });
        }

        public void OnHexTyped(object sender, RoutedEventArgs args)
        {
            if (_loading) return;
            int[] rgb = FmColour.FromHex(Box("txtHex").Text);
            if (rgb != null) SetRgb(rgb);
        }

        // -- dragging on the gradients --------------------------------------------
        private void FieldFromPoint(MouseEventArgs args)
        {
            Point pos = args.GetPosition(Find<Border>("pnlField"));
            double hue = FmColour.Clamp(pos.X / FieldW, 0.0, 1.0) * FmColour.HueMax;
            double sat = (1.0 - FmColour.Clamp(pos.Y / FieldH, 0.0, 1.0)) * FmColour.SatMax;
            SetHsl(new[] { (int)Math.Round(hue, MidpointRounding.AwayFromZero), (int)Math.Round(sat, MidpointRounding.AwayFromZero), _hsl[2] });
        }

        private void LumFromPoint(MouseEventArgs args)
        {
            Point pos = args.GetPosition(Find<Border>("pnlLum"));
            double lum = (1.0 - FmColour.Clamp(pos.Y / LumH, 0.0, 1.0)) * FmColour.LumMax;
            SetHsl(new[] { _hsl[0], _hsl[1], (int)Math.Round(lum, MidpointRounding.AwayFromZero) });
        }

        private void OnFieldDown(object sender, MouseButtonEventArgs args)
        {
            _dragging = "field";
            try { Find<Border>("pnlField").CaptureMouse(); }
            catch (Exception) { }
            FieldFromPoint(args);
        }

        private void OnFieldMove(object sender, MouseEventArgs args) { if (_dragging == "field") FieldFromPoint(args); }

        private void OnFieldUp(object sender, MouseButtonEventArgs args)
        {
            _dragging = null;
            try { Find<Border>("pnlField").ReleaseMouseCapture(); }
            catch (Exception) { }
        }

        private void OnLumDown(object sender, MouseButtonEventArgs args)
        {
            _dragging = "lum";
            try { Find<Border>("pnlLum").CaptureMouse(); }
            catch (Exception) { }
            LumFromPoint(args);
        }

        private void OnLumMove(object sender, MouseEventArgs args) { if (_dragging == "lum") LumFromPoint(args); }

        private void OnLumUp(object sender, MouseButtonEventArgs args)
        {
            _dragging = null;
            try { Find<Border>("pnlLum").ReleaseMouseCapture(); }
            catch (Exception) { }
        }

        // -- buttons --------------------------------------------------------------
        public void OnAddCustom(object sender, RoutedEventArgs args)
        {
            string value = FmColour.ToHex(_rgb);
            if (!CustomColours.Contains(value))
            {
                CustomColours.Insert(0, value);
                while (CustomColours.Count > 16) CustomColours.RemoveAt(CustomColours.Count - 1);
            }
            BuildSwatches(Find<Panel>("pnlCustom"), CustomColours, 8);
        }

        public void OnNoOverride(object sender, RoutedEventArgs args) { Result = Tuple.Create("none", (string)null); Win.Close(); }
        public void OnCancel(object sender, RoutedEventArgs args) { Result = null; Win.Close(); }
        public void OnOk(object sender, RoutedEventArgs args) { Result = Tuple.Create("colour", FmColour.ToHex(_rgb)); Win.Close(); }
    }

    // ===========================================================================
    //  Line / pattern override dialog
    // ===========================================================================
    /// <summary>The same two dialogs Revit's own Filters tab opens from a cell.</summary>
    public class FmOverrideWindow : FmWindowBase
    {
        private static readonly Dictionary<string, string[]> LineKeys = new Dictionary<string, string[]>
        {
            { "projection", new[] { "proj_colour", "proj_weight", "proj_pattern" } },
            { "cut", new[] { "cut_colour", "cut_weight", "cut_pattern" } },
        };

        private static readonly Dictionary<string, string[]> PatternKeys = new Dictionary<string, string[]>
        {
            { "surface", new[] { "surf_fg_pattern", "surf_fg_colour", "surf_bg_pattern", "surf_bg_colour" } },
            { "cutpattern", new[] { "cut_fg_pattern", "cut_fg_colour", "cut_bg_pattern", "cut_bg_colour" } },
        };

        private static readonly Dictionary<string, string> Titles = new Dictionary<string, string>
        {
            { "projection", "Projection / Surface  -  Lines" },
            { "cut", "Cut  -  Lines" },
            { "surface", "Projection / Surface  -  Patterns" },
            { "cutpattern", "Cut  -  Patterns" },
        };

        private readonly Document _doc;
        private readonly string _kind;
        private readonly bool _isLines;
        private readonly List<FmChoice> _linePatterns;
        private readonly List<FmChoice> _fillPatterns;
        private string _lineColour, _fgColour, _bgColour;

        /// <summary>The edited keys (null values mean no override); null when cancelled. Keys are the spec keys of the kind.</summary>
        public Dictionary<string, object> Result;

        public FmOverrideWindow(Document doc, string kind, FmSpec spec, string subject, List<FmChoice> linePatterns,
                                List<FmChoice> fillPatterns, string scopeNote = "")
        {
            Init("override.xaml");
            _doc = doc;
            _kind = kind;
            _isLines = LineKeys.ContainsKey(kind);
            _linePatterns = linePatterns;
            _fillPatterns = fillPatterns;

            SetVersion();
            string title;
            Text("txtTitle").Text = "  " + (Titles.TryGetValue(kind, out title) ? title : "Override");
            Text("txtSubject").Text = subject;
            Text("txtScope").Text = scopeNote;

            FmUi.SetVisible(Find<UIElement>("pnlLines"), _isLines);
            FmUi.SetVisible(Find<UIElement>("pnlPatterns"), !_isLines);

            if (_isLines)
            {
                string[] k = LineKeys[kind];
                _lineColour = spec.Str(k[0]);
                LoadCombo(Combo("cboWeight"), FmOverrides.LineWeights(), spec[k[1]]);
                FillPatternCombo(Combo("cboLinePattern"), linePatterns, spec[k[2]], "");
                PaintColourButton(Btn("btnLineColour"), _lineColour);
                RefreshLinePreview();
            }
            else
            {
                string[] k = PatternKeys[kind];
                _fgColour = spec.Str(k[1]);
                _bgColour = spec.Str(k[3]);
                FillPatternCombo(Combo("cboFgPattern"), fillPatterns, spec[k[0]], "");
                FillPatternCombo(Combo("cboBgPattern"), fillPatterns, spec[k[2]], "");
                PaintColourButton(Btn("btnFgColour"), _fgColour);
                PaintColourButton(Btn("btnBgColour"), _bgColour);
                RefreshFillPreviews();
            }
        }

        // -- combos ---------------------------------------------------------------
        private static bool SameChoice(object a, object b)
        {
            if (a == null || b == null) return false;
            if (a is int && b is int) return (int)a == (int)b;
            var ia = a as ElementId;
            var ib = b as ElementId;
            return ia != null && ib != null && FmCore.EidValue(ia) == FmCore.EidValue(ib);
        }

        private void LoadCombo(ComboBox combo, List<FmChoice> source, object current)
        {
            combo.Items.Clear();
            int idx = 0;
            for (int i = 0; i < source.Count; i++)
            {
                combo.Items.Add(FmUi.ComboItem(source[i].Name, source[i].Value));
                if (source[i].Value == null && current == null) idx = i;
                else if (SameChoice(source[i].Value, current)) idx = i;
            }
            combo.SelectedIndex = idx;
        }

        /// <summary>Populate a pattern combo, narrowed by a keyword. The current value always stays in the list.</summary>
        private void FillPatternCombo(ComboBox combo, List<FmChoice> source, object current, string keyword)
        {
            string key = (keyword ?? "").ToLowerInvariant().Trim();
            var shown = new List<FmChoice>();
            foreach (FmChoice c in source)
            {
                bool keep = key.Length == 0 || c.Name.ToLowerInvariant().Contains(key);
                if (c.Value == null) keep = true;
                if (current != null && c.Value != null && SameChoice(c.Value, current)) keep = true;
                if (keep) shown.Add(c);
            }

            combo.Items.Clear();
            int idx = 0;
            for (int i = 0; i < shown.Count; i++)
            {
                combo.Items.Add(FmUi.ComboItem(shown[i].Name, shown[i].Value));
                if (shown[i].Value == null && current == null) idx = i;
                else if (shown[i].Value != null && current != null && SameChoice(shown[i].Value, current)) idx = i;
            }
            combo.SelectedIndex = combo.Items.Count > 0 ? idx : -1;
        }

        public void OnLinePatternSearch(object sender, RoutedEventArgs args)
        {
            var combo = Combo("cboLinePattern");
            FillPatternCombo(combo, _linePatterns, FmUi.ComboTag(combo), Box("txtLinePatSearch").Text);
        }

        public void OnFillPatternSearch(object sender, RoutedEventArgs args)
        {
            string keyword = Box("txtFillPatSearch").Text;
            var fg = Combo("cboFgPattern");
            var bg = Combo("cboBgPattern");
            FillPatternCombo(fg, _fillPatterns, FmUi.ComboTag(fg), keyword);
            FillPatternCombo(bg, _fillPatterns, FmUi.ComboTag(bg), keyword);
        }

        // -- previews -------------------------------------------------------------
        private string Stroke(string value)
        {
            return FmOverrides.ParseHex(value) != null ? "#FF" + value : FmUi.PColour("Txt");
        }

        private void RefreshLinePreview()
        {
            try
            {
                Find<Border>("pnlLinePreview").Child = FmUi.LinePatternPreview(
                    _doc, FmUi.ComboTag(Combo("cboLinePattern")) as ElementId, 130, 22, Stroke(_lineColour));
            }
            catch (Exception) { }
        }

        private void RefreshFillPreviews()
        {
            try
            {
                Find<Border>("pnlFgPreview").Child = FmUi.FillPatternPreview(
                    _doc, FmUi.ComboTag(Combo("cboFgPattern")) as ElementId, 130, 56, Stroke(_fgColour));
                Find<Border>("pnlBgPreview").Child = FmUi.FillPatternPreview(
                    _doc, FmUi.ComboTag(Combo("cboBgPattern")) as ElementId, 130, 56, Stroke(_bgColour));
            }
            catch (Exception) { }
        }

        public void OnLinePatternChanged(object sender, RoutedEventArgs args) { RefreshLinePreview(); }
        public void OnFgPatternChanged(object sender, RoutedEventArgs args) { RefreshFillPreviews(); }
        public void OnBgPatternChanged(object sender, RoutedEventArgs args) { RefreshFillPreviews(); }

        // -- colour buttons -------------------------------------------------------
        private void PaintColourButton(Button button, string value)
        {
            var panel = new StackPanel { Orientation = Orientation.Horizontal };
            var chip = new Border
            {
                Width = 26, Height = 16, Margin = new Thickness(0, 0, 8, 0), BorderBrush = FmUi.PBrush("EdgeStrong"),
                BorderThickness = new Thickness(1), VerticalAlignment = VerticalAlignment.Center,
            };
            FmUi.PaintSwatch(chip, value);
            panel.Children.Add(chip);

            var label = new TextBlock
            {
                Text = FmOverrides.ParseHex(value) != null ? "#" + value : "No override",
                VerticalAlignment = VerticalAlignment.Center,
                FontSize = 11,
            };
            label.SetResourceReference(TextBlock.ForegroundProperty, "Txt");
            panel.Children.Add(label);
            button.Content = panel;
        }

        private bool PickColour(string current, out string value)
        {
            var dlg = new FmColourWindow(current);
            dlg.Owner = Win;
            dlg.ShowDialog();
            if (dlg.Result == null) { value = current; return false; }
            value = dlg.Result.Item1 == "colour" ? dlg.Result.Item2 : null;
            return true;
        }

        public void OnPickLineColour(object sender, RoutedEventArgs args)
        {
            string v;
            if (!PickColour(_lineColour, out v)) return;
            _lineColour = v;
            PaintColourButton(Btn("btnLineColour"), v);
            RefreshLinePreview();
        }

        public void OnPickFgColour(object sender, RoutedEventArgs args)
        {
            string v;
            if (!PickColour(_fgColour, out v)) return;
            _fgColour = v;
            PaintColourButton(Btn("btnFgColour"), v);
            RefreshFillPreviews();
        }

        public void OnPickBgColour(object sender, RoutedEventArgs args)
        {
            string v;
            if (!PickColour(_bgColour, out v)) return;
            _bgColour = v;
            PaintColourButton(Btn("btnBgColour"), v);
            RefreshFillPreviews();
        }

        // -- window ---------------------------------------------------------------
        public void OnClear(object sender, RoutedEventArgs args)
        {
            var output = new Dictionary<string, object>();
            foreach (string k in _isLines ? LineKeys[_kind] : PatternKeys[_kind]) output[k] = null;
            Result = output;
            Win.Close();
        }

        public void OnCancel(object sender, RoutedEventArgs args) { Result = null; Win.Close(); }

        public void OnOk(object sender, RoutedEventArgs args)
        {
            var output = new Dictionary<string, object>();
            if (_isLines)
            {
                string[] k = LineKeys[_kind];
                output[k[0]] = FmOverrides.ParseHex(_lineColour) != null ? _lineColour : null;
                output[k[1]] = FmUi.ComboTag(Combo("cboWeight"));
                output[k[2]] = FmUi.ComboTag(Combo("cboLinePattern"));
            }
            else
            {
                string[] k = PatternKeys[_kind];
                output[k[0]] = FmUi.ComboTag(Combo("cboFgPattern"));
                output[k[2]] = FmUi.ComboTag(Combo("cboBgPattern"));
                output[k[1]] = FmOverrides.ParseHex(_fgColour) != null ? _fgColour : null;
                output[k[3]] = FmOverrides.ParseHex(_bgColour) != null ? _bgColour : null;
            }
            Result = output;
            Win.Close();
        }
    }
}
