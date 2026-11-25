using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Threading;
using RevoBIM.Tools.FilterManager;
using WpfColor = System.Windows.Media.Color;

namespace RevoBIM.UI.FilterManager
{
    /// <summary>
    /// Filter Manager: themed widget builders and window plumbing. Port of fm_ui.py. Rows are built as WPF
    /// elements in code (nothing is bound), and every handler is wrapped so an error is reported, not swallowed.
    /// </summary>
    public static class FmUi
    {
        // a line of Segoe UI 12 needs about 17px; the box has to hold that plus its padding (5 top and bottom)
        // and its border, so 30 is the floor and a cell is given a little more than the floor
        public const double MinTextBoxHeight = 32;
        // every cell in a table row is this tall, so a row reads as one row
        public const double CellHeight = 34;

        // ---------------------------------------------------------------------------
        //  Widgets
        // ---------------------------------------------------------------------------
        public static CheckBox NewCheckBox(string text, object tag, bool isChecked = false)
        {
            return new CheckBox { Content = text, Tag = tag, IsChecked = isChecked };
        }

        public static ListBoxItem NewListItem(string text, object tag)
        {
            return new ListBoxItem { Content = text, Tag = tag };
        }

        public static ComboBoxItem ComboItem(string text, object tag = null)
        {
            return new ComboBoxItem { Content = text, Tag = tag };
        }

        /// <summary>items: display strings. tags: matching payloads, kept on the item.</summary>
        public static ComboBox NewCombo(IList<string> items, int selectedIndex = -1, double? width = null,
                                        IList<object> tags = null, double? height = null)
        {
            var cb = new ComboBox { MinHeight = MinTextBoxHeight };
            if (height.HasValue) cb.Height = height.Value;
            for (int i = 0; i < items.Count; i++)
            {
                var it = new ComboBoxItem { Content = items[i] };
                if (tags != null && i < tags.Count) it.Tag = tags[i];
                cb.Items.Add(it);
            }
            if (selectedIndex >= 0 && selectedIndex < cb.Items.Count) cb.SelectedIndex = selectedIndex;
            if (width.HasValue) cb.Width = width.Value;
            return cb;
        }

        public static object ComboTag(ComboBox combo)
        {
            try
            {
                var item = combo.SelectedItem as ComboBoxItem;
                if (item != null) return item.Tag;
            }
            catch (Exception) { }
            return null;
        }

        public static string ComboText(ComboBox combo)
        {
            try
            {
                var item = combo.SelectedItem as ComboBoxItem;
                if (item != null) return item.Content as string ?? (item.Content == null ? "" : item.Content.ToString());
            }
            catch (Exception) { }
            return "";
        }

        public static bool SelectByTag(ComboBox combo, object wanted, Func<object, object, bool> compare = null)
        {
            for (int i = 0; i < combo.Items.Count; i++)
            {
                var item = combo.Items[i] as ComboBoxItem;
                if (item == null) continue;
                bool hit = compare == null ? Equals(item.Tag, wanted) : compare(item.Tag, wanted);
                if (hit)
                {
                    combo.SelectedIndex = i;
                    return true;
                }
            }
            return false;
        }

        public static TextBox NewTextBox(string text = "", string placeholder = null, double? width = null)
        {
            var tb = new TextBox { Text = text ?? "" };
            if (!string.IsNullOrEmpty(placeholder)) tb.Tag = placeholder;
            if (width.HasValue) tb.Width = width.Value;
            tb.MinHeight = MinTextBoxHeight;
            tb.VerticalContentAlignment = VerticalAlignment.Center;
            return tb;
        }

        public static TextBlock NewText(string text, string brushKey = null, double size = 12, bool bold = false, Thickness? margin = null)
        {
            var tb = new TextBlock { Text = text, FontSize = size };
            if (bold) tb.FontWeight = FontWeights.Bold;
            if (margin.HasValue) tb.Margin = margin.Value;
            if (!string.IsNullOrEmpty(brushKey))
            {
                try { tb.SetResourceReference(TextBlock.ForegroundProperty, brushKey); }
                catch (Exception) { }
            }
            return tb;
        }

        public static Button NewButton(string text, string styleKey, RoutedEventHandler click = null,
                                       double? width = null, double? height = null, object tag = null)
        {
            var b = new Button { Content = text };
            if (tag != null) b.Tag = tag;
            try { b.SetResourceReference(FrameworkElement.StyleProperty, styleKey); }
            catch (Exception) { }
            if (width.HasValue) b.Width = width.Value;
            if (height.HasValue) b.Height = height.Value;
            if (click != null) b.Click += click;
            return b;
        }

        public static ColumnDefinition Col(double? widthStar = null, double? pixels = null)
        {
            var c = new ColumnDefinition();
            c.Width = pixels.HasValue ? new GridLength(pixels.Value) : new GridLength(widthStar ?? 1, GridUnitType.Star);
            return c;
        }

        public static RowDefinition Row(double? pixels = null)
        {
            var r = new RowDefinition();
            r.Height = pixels.HasValue ? new GridLength(pixels.Value) : GridLength.Auto;
            return r;
        }

        public static T Place<T>(T element, Grid grid, int column) where T : UIElement
        {
            Grid.SetColumn(element, column);
            grid.Children.Add(element);
            return element;
        }

        public static Grid NewGrid(Thickness? margin = null)
        {
            var g = new Grid();
            if (margin.HasValue) g.Margin = margin.Value;
            return g;
        }

        public static void SetVisible(UIElement element, bool visible)
        {
            if (element != null) element.Visibility = visible ? Visibility.Visible : Visibility.Collapsed;
        }

        public static GridLength Star(double value) { return new GridLength(Math.Max(0.0001, value), GridUnitType.Star); }
        public static GridLength Pixels(double value) { return new GridLength(Math.Max(0.0, value)); }
        public static TextTrimming Trim() { return TextTrimming.CharacterEllipsis; }
        public static HorizontalAlignment Left() { return HorizontalAlignment.Left; }
        public static HorizontalAlignment Centre() { return HorizontalAlignment.Center; }
        public static Cursor CursorHand() { return Cursors.Hand; }
        public static Geometry Geometry(string pathData) { return System.Windows.Media.Geometry.Parse(pathData); }

        public static WpfColor Colour(int r, int g, int b, int a = 255)
        {
            return WpfColor.FromArgb((byte)a, (byte)r, (byte)g, (byte)b);
        }

        /// <summary>A SolidColorBrush from '#AARRGGBB' or '#RRGGBB'.</summary>
        public static SolidColorBrush Brush(string hex)
        {
            string s = (hex ?? "").Trim().TrimStart('#');
            try
            {
                if (s.Length == 8)
                    return new SolidColorBrush(WpfColor.FromArgb(Convert.ToByte(s.Substring(0, 2), 16), Convert.ToByte(s.Substring(2, 2), 16),
                                                                 Convert.ToByte(s.Substring(4, 2), 16), Convert.ToByte(s.Substring(6, 2), 16)));
                if (s.Length == 6)
                    return new SolidColorBrush(WpfColor.FromRgb(Convert.ToByte(s.Substring(0, 2), 16), Convert.ToByte(s.Substring(2, 2), 16),
                                                                Convert.ToByte(s.Substring(4, 2), 16)));
            }
            catch (Exception) { }
            return new SolidColorBrush(WpfColor.FromRgb(38, 38, 38));
        }

        // ---------------------------------------------------------------------------
        //  Palette
        // ---------------------------------------------------------------------------
        /// <summary>A hex colour from the palette currently in force.</summary>
        public static string PColour(string key) { return FmTheme.Get(key); }
        public static SolidColorBrush PBrush(string key) { return Brush(FmTheme.Get(key)); }

        /// <summary>
        /// Write the palette straight onto the window's own resources. The layouts reference the keys with
        /// DynamicResource, so the whole window repaints with no reload and no loss of state.
        /// </summary>
        public static void ApplyPalette(Window window)
        {
            foreach (var kv in FmTheme.Current)
            {
                try { window.Resources[kv.Key] = Brush(kv.Value); }
                catch (Exception) { }
            }
        }

        public static double MeasureText(string text, double fontSize = 12.0, bool bold = false)
        {
            try
            {
                var block = new TextBlock { Text = text ?? "", FontSize = fontSize };
                if (bold) block.FontWeight = FontWeights.Bold;
                block.Measure(new Size(10000, 10000));
                return block.DesiredSize.Width;
            }
            catch (Exception) { return (text ?? "").Length * fontSize * 0.55; }
        }

        // ---------------------------------------------------------------------------
        //  Swatches and small composites
        // ---------------------------------------------------------------------------
        public static Border Swatch(string hexText)
        {
            var b = new Border { Width = 26, Height = 22, BorderThickness = new Thickness(1), Margin = new Thickness(4, 0, 0, 0) };
            try { b.BorderBrush = PBrush("EdgeStrong"); }
            catch (Exception) { }
            PaintSwatch(b, hexText);
            return b;
        }

        public static bool PaintSwatch(Border border, string hexText)
        {
            try
            {
                string s = (hexText ?? "").Trim().TrimStart('#');
                if (s.Length == 6)
                {
                    border.Background = new SolidColorBrush(WpfColor.FromRgb(Convert.ToByte(s.Substring(0, 2), 16),
                        Convert.ToByte(s.Substring(2, 2), 16), Convert.ToByte(s.Substring(4, 2), 16)));
                    return true;
                }
            }
            catch (Exception) { }
            try { border.Background = PBrush("Field"); }
            catch (Exception) { }
            return false;
        }

        /// <summary>A label with a 4px coloured tick to its left.</summary>
        public static StackPanel SectionHeader(string text, string accentKey = "Blue")
        {
            var panel = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 10, 0, 6) };
            var tick = new Border { Width = 4, Height = 15, Margin = new Thickness(0, 0, 7, 0) };
            try { tick.SetResourceReference(Border.BackgroundProperty, accentKey); }
            catch (Exception) { }
            panel.Children.Add(tick);
            var label = new TextBlock { Text = text, FontWeight = FontWeights.Bold, FontSize = 11 };
            try { label.SetResourceReference(TextBlock.ForegroundProperty, "Txt"); }
            catch (Exception) { }
            panel.Children.Add(label);
            return panel;
        }

        /// <summary>A label on the left and a row of controls filling the rest.</summary>
        public static Grid LabelledRow(string labelText, IEnumerable<UIElement> controls, double labelWidth = 118)
        {
            var grid = new Grid { Margin = new Thickness(0, 0, 0, 5) };
            grid.ColumnDefinitions.Add(Col(pixels: labelWidth));
            grid.ColumnDefinitions.Add(Col(1));
            var label = new TextBlock { Text = labelText, VerticalAlignment = VerticalAlignment.Center, FontSize = 11 };
            try { label.SetResourceReference(TextBlock.ForegroundProperty, "Dim"); }
            catch (Exception) { }
            Place(label, grid, 0);
            var holder = new StackPanel { Orientation = Orientation.Horizontal };
            foreach (UIElement c in controls) holder.Children.Add(c);
            Place(holder, grid, 1);
            return grid;
        }

        // ---------------------------------------------------------------------------
        //  Screens, DPI and full screen
        // ---------------------------------------------------------------------------
        /// <summary>(x, y) device pixels per WPF unit for the screen the window is on.</summary>
        public static Point DpiScale(Window window)
        {
            try
            {
                PresentationSource src = PresentationSource.FromVisual(window);
                if (src != null)
                {
                    Matrix m = src.CompositionTarget.TransformToDevice;
                    return new Point(m.M11 != 0 ? m.M11 : 1.0, m.M22 != 0 ? m.M22 : 1.0);
                }
            }
            catch (Exception) { }
            return new Point(1.0, 1.0);
        }

        /// <summary>(left, top, width, height) in WPF units of the screen holding the window.</summary>
        public static Rect WorkingArea(Window window)
        {
            try
            {
                IntPtr handle = new WindowInteropHelper(window).Handle;
                System.Drawing.Rectangle area = System.Windows.Forms.Screen.FromHandle(handle).WorkingArea;
                Point s = DpiScale(window);
                return new Rect(area.Left / s.X, area.Top / s.Y, area.Width / s.X, area.Height / s.Y);
            }
            catch (Exception) { }
            try
            {
                Rect r = SystemParameters.WorkArea;
                return new Rect(r.Left, r.Top, r.Width, r.Height);
            }
            catch (Exception) { return new Rect(0, 0, 1280, 800); }
        }

        /// <summary>The mouse position in WPF units.</summary>
        public static Point CursorOnScreen(Window window)
        {
            try
            {
                System.Drawing.Point p = System.Windows.Forms.Cursor.Position;
                Point s = DpiScale(window);
                return new Point(p.X / s.X, p.Y / s.Y);
            }
            catch (Exception) { }
            try
            {
                Point p = Mouse.GetPosition(window);
                return new Point(window.Left + p.X, window.Top + p.Y);
            }
            catch (Exception) { return new Point(window.Left, window.Top); }
        }

        /// <summary>
        /// Full screen and vertical maximise by bounds, not WindowState: maximising a borderless window the
        /// normal way covers the task bar and lands on the wrong monitor.
        /// </summary>
        public class ScreenState
        {
            private readonly Window _window;
            private double[] _saved;       // bounds before full screen
            private double[] _savedV;      // bounds before vertical maximise
            private double[] _savedMin;    // minimums before they were relaxed
            public bool Full;
            public bool Vertical;

            public ScreenState(Window window) { _window = window; }

            /// <summary>Let the window shrink below its usual minimum (WPF honours MinWidth over anything else).</summary>
            private void RelaxMinimums(double width, double height)
            {
                Window w = _window;
                if (_savedMin == null) _savedMin = new[] { w.MinWidth, w.MinHeight };
                w.MinWidth = FmCore.ShrinkToFit(w.Width, w.MinWidth, width).Item2;
                w.MinHeight = FmCore.ShrinkToFit(w.Height, w.MinHeight, height).Item2;
            }

            private void RestoreMinimums()
            {
                if (_savedMin == null) return;
                try { _window.MinWidth = _savedMin[0]; _window.MinHeight = _savedMin[1]; }
                catch (Exception) { }
                _savedMin = null;
            }

            /// <summary>Bring the window onto the screen it opened on, whatever its size.</summary>
            public void FitToScreen()
            {
                Window w = _window;
                Rect a = WorkingArea(w);
                if (a.Width <= 0 || a.Height <= 0) return;
                if (w.Width <= a.Width && w.Height <= a.Height && w.MinWidth <= a.Width && w.MinHeight <= a.Height) return;

                RelaxMinimums(a.Width, a.Height);
                double newW = FmCore.ShrinkToFit(w.Width, w.MinWidth, a.Width).Item1;
                double newH = FmCore.ShrinkToFit(w.Height, w.MinHeight, a.Height).Item1;
                w.Width = newW;
                w.Height = newH;
                w.Left = Math.Max(a.Left, Math.Min(w.Left, a.Left + a.Width - newW));
                w.Top = Math.Max(a.Top, Math.Min(w.Top, a.Top + a.Height - newH));
            }

            private double[] Bounds() { return new[] { _window.Left, _window.Top, _window.Width, _window.Height }; }

            private void Restore(double[] b)
            {
                _window.Left = b[0]; _window.Top = b[1]; _window.Width = b[2]; _window.Height = b[3];
            }

            public void EnterFull()
            {
                if (Full) return;
                _saved = Bounds();
                Rect a = WorkingArea(_window);
                RelaxMinimums(a.Width, a.Height);
                _window.Left = a.Left; _window.Top = a.Top; _window.Width = a.Width; _window.Height = a.Height;
                Full = true;
                Vertical = false;
            }

            public void ExitFull()
            {
                if (!Full) return;
                // the minimums go back first, or restoring the old bounds would be clamped by the relaxed ones
                RestoreMinimums();
                if (_saved != null) Restore(_saved);
                Full = false;
            }

            public void ToggleFull()
            {
                if (Full) ExitFull(); else EnterFull();
            }

            /// <summary>Expand up and down only, keeping the left edge and the width.</summary>
            public void ToggleVertical()
            {
                if (Full) { ExitFull(); return; }
                Window w = _window;
                if (Vertical && _savedV != null)
                {
                    RestoreMinimums();
                    Restore(_savedV);
                    Vertical = false;
                    return;
                }
                _savedV = Bounds();
                Rect a = WorkingArea(w);
                RelaxMinimums(a.Width, a.Height);
                w.Top = a.Top;
                w.Height = a.Height;
                Vertical = true;
            }

            /// <summary>Leave full screen for a drag, keeping the cursor on the title bar.</summary>
            public void BreakOut(MouseButtonEventArgs args)
            {
                if (!Full) return;
                Window w = _window;
                double fraction = 0.5, offsetY = 18.0;
                try
                {
                    Point pos = args.GetPosition(w);
                    if (w.ActualWidth > 0) fraction = Math.Max(0.0, Math.Min(1.0, pos.X / w.ActualWidth));
                    offsetY = pos.Y;
                }
                catch (Exception) { }

                Point screen = CursorOnScreen(w);
                ExitFull();
                try
                {
                    w.Left = screen.X - (fraction * w.Width);
                    w.Top = screen.Y - offsetY;
                }
                catch (Exception) { }
            }
        }

        // ===========================================================================
        //  Pattern previews
        // ===========================================================================
        /// <summary>A sample of a line pattern, drawn from its own segment list.</summary>
        public static Canvas LinePatternPreview(Autodesk.Revit.DB.Document doc, Autodesk.Revit.DB.ElementId patternId,
                                                double width = 120.0, double height = 18.0, string stroke = null)
        {
            stroke = stroke ?? PColour("Txt");
            var canvas = new Canvas { Width = width, Height = height, Background = PBrush("FieldDeep") };

            Canvas Solid()
            {
                canvas.Children.Add(new Line
                {
                    X1 = 4, Y1 = height / 2.0, X2 = width - 4, Y2 = height / 2.0,
                    Stroke = Brush(stroke), StrokeThickness = 1.6,
                });
                return canvas;
            }

            if (patternId == null) return Solid();

            var segments = new List<Tuple<string, double>>();
            try
            {
                var element = doc.GetElement(patternId) as Autodesk.Revit.DB.LinePatternElement;
                Autodesk.Revit.DB.LinePattern pattern = element.GetLinePattern();
                foreach (Autodesk.Revit.DB.LinePatternSegment s in pattern.GetSegments())
                    segments.Add(Tuple.Create(s.Type.ToString(), Math.Abs(s.Length)));
            }
            catch (Exception) { return Solid(); }

            double total = segments.Sum(s => s.Item2);
            if (segments.Count == 0 || total <= 0) return Solid();

            double usable = width - 8;
            const double repeats = 3.0;
            double scale = usable / (total * repeats);

            double x = 4.0;
            int guard = 0;
            while (x < width - 4 && guard < 400)
            {
                foreach (var seg in segments)
                {
                    double step = seg.Item2 * scale;
                    if (step <= 0) step = 1.0;
                    if (!seg.Item1.Contains("Space"))
                    {
                        var line = new Line { X1 = x, X2 = Math.Min(x + step, width - 4), Y1 = height / 2.0, Y2 = height / 2.0,
                                              Stroke = Brush(stroke), StrokeThickness = 1.6 };
                        if (seg.Item1.Contains("Dot")) line.X2 = Math.Min(x + 1.6, width - 4);
                        canvas.Children.Add(line);
                    }
                    x += step;
                    guard++;
                    if (x >= width - 4) break;
                }
            }
            return canvas;
        }

        /// <summary>A sample of a fill pattern, drawn from its own fill grids.</summary>
        public static Canvas FillPatternPreview(Autodesk.Revit.DB.Document doc, Autodesk.Revit.DB.ElementId patternId,
                                                double width = 120.0, double height = 52.0, string stroke = null)
        {
            stroke = stroke ?? PColour("Txt");
            var canvas = new Canvas { Width = width, Height = height, Background = PBrush("FieldDeep"), ClipToBounds = true };
            if (patternId == null) return canvas;

            var grids = new List<Tuple<double, double>>();
            bool solidFill = false;
            try
            {
                var element = doc.GetElement(patternId) as Autodesk.Revit.DB.FillPatternElement;
                Autodesk.Revit.DB.FillPattern pattern = element.GetFillPattern();
                solidFill = pattern.IsSolidFill;
                foreach (Autodesk.Revit.DB.FillGrid g in pattern.GetFillGrids())
                    grids.Add(Tuple.Create(g.Angle, g.Offset));
            }
            catch (Exception) { return canvas; }

            if (solidFill)
            {
                canvas.Background = Brush(stroke);
                return canvas;
            }
            if (grids.Count == 0) return canvas;

            List<double> offsets = grids.Where(g => g.Item2 > 0).Select(g => g.Item2).ToList();
            if (offsets.Count == 0) return canvas;
            double scale = (height / 6.0) / offsets.Min();
            scale = Math.Max(4.0, Math.Min(scale, 400.0));

            double span = Math.Sqrt(width * width + height * height);
            foreach (var grid in grids)
            {
                double step = grid.Item2 * scale;
                if (step < 3.0) step = 3.0;
                double dx = Math.Cos(grid.Item1), dy = Math.Sin(grid.Item1);
                double nx = -dy, ny = dx;
                int count = (int)(span / step) + 2;
                for (int i = -count; i <= count; i++)
                {
                    double cx = width / 2.0 + nx * step * i;
                    double cy = height / 2.0 + ny * step * i;
                    canvas.Children.Add(new Line
                    {
                        X1 = cx - dx * span, Y1 = cy - dy * span, X2 = cx + dx * span, Y2 = cy + dy * span,
                        Stroke = Brush(stroke), StrokeThickness = 0.9,
                    });
                }
            }
            return canvas;
        }

        // ===========================================================================
        //  Handler guard: an unhandled exception in a WPF handler propagates onto Revit's UI thread, so every
        //  handler goes through one of these. An error is reported (named) and never swallowed.
        // ===========================================================================
        private static Action<string, string> _reporter;

        public static void SetHandlerReporter(Action<string, string> fn) { _reporter = fn; }

        public static void Report(string name, Exception error)
        {
            string text = error is System.Reflection.TargetInvocationException && error.InnerException != null
                ? error.InnerException.ToString() : error.ToString();
            var reporter = _reporter;
            if (reporter != null)
            {
                try { reporter(name, text); return; }
                catch (Exception) { }
            }
            FmCore.Crumb("handler " + name + " failed: " + error.Message);
        }

        public static RoutedEventHandler Safe(Action<object, RoutedEventArgs> fn, string name = "handler")
        {
            return (s, a) => { try { fn(s, a); } catch (Exception ex) { Report(name, ex); } };
        }

        public static SelectionChangedEventHandler SafeSelection(Action<object, SelectionChangedEventArgs> fn, string name = "handler")
        {
            return (s, a) => { try { fn(s, a); } catch (Exception ex) { Report(name, ex); } };
        }

        public static TextChangedEventHandler SafeText(Action<object, TextChangedEventArgs> fn, string name = "handler")
        {
            return (s, a) => { try { fn(s, a); } catch (Exception ex) { Report(name, ex); } };
        }

        public static MouseButtonEventHandler SafeMouse(Action<object, MouseButtonEventArgs> fn, string name = "handler")
        {
            return (s, a) => { try { fn(s, a); } catch (Exception ex) { Report(name, ex); } };
        }

        public static MouseEventHandler SafeMouseMove(Action<object, MouseEventArgs> fn, string name = "handler")
        {
            return (s, a) => { try { fn(s, a); } catch (Exception ex) { Report(name, ex); } };
        }

        public static KeyEventHandler SafeKey(Action<object, KeyEventArgs> fn, string name = "handler")
        {
            return (s, a) => { try { fn(s, a); } catch (Exception ex) { Report(name, ex); } };
        }

        public static EventHandler SafeEvent(Action<object, EventArgs> fn, string name = "handler")
        {
            return (s, a) => { try { fn(s, a); } catch (Exception ex) { Report(name, ex); } };
        }

        public static DragDeltaEventHandler SafeDrag(Action<object, DragDeltaEventArgs> fn, string name = "handler")
        {
            return (s, a) => { try { fn(s, a); } catch (Exception ex) { Report(name, ex); } };
        }

        public static SizeChangedEventHandler SafeSize(Action<object, SizeChangedEventArgs> fn, string name = "handler")
        {
            return (s, a) => { try { fn(s, a); } catch (Exception ex) { Report(name, ex); } };
        }

        /// <summary>Run something, reporting (not throwing) any failure.</summary>
        public static void Guard(string name, Action fn)
        {
            try { fn(); }
            catch (Exception ex) { Report(name, ex); }
        }

        // ===========================================================================
        //  Revit's own theme, for the Auto palette
        // ===========================================================================
        /// <summary>"dark" or "light" from what Revit is showing, or null if unknown.</summary>
        public static string RevitTheme()
        {
            try
            {
                string value = RevoBIM.Helpers.RevitCompat.CanvasTheme().ToString().ToLowerInvariant();
                if (value.Contains("dark")) return "dark";
                if (value.Contains("light")) return "light";
            }
            catch (Exception) { }
            try
            {
                string value = Autodesk.Revit.UI.UIThemeManager.CurrentTheme.ToString().ToLowerInvariant();
                if (value.Contains("dark")) return "dark";
                if (value.Contains("light")) return "light";
            }
            catch (Exception) { }
            try
            {
                using (Microsoft.Win32.RegistryKey key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(
                    "Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize"))
                {
                    if (key != null)
                    {
                        object value = key.GetValue("AppsUseLightTheme");
                        if (value != null) return Convert.ToInt32(value) == 1 ? "light" : "dark";
                    }
                }
            }
            catch (Exception) { }
            return null;
        }
    }

    /// <summary>
    /// Run something once the typing stops, rather than per keystroke: a search box that rebuilds a list on every
    /// key press does the work five or six times for a word nobody has finished typing.
    /// </summary>
    public class FmDebounce
    {
        private readonly Action _action;
        private readonly DispatcherTimer _timer;

        public FmDebounce(Action action, int milliseconds = 220)
        {
            _action = action;
            _timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(milliseconds) };
            _timer.Tick += (s, a) =>
            {
                _timer.Stop();
                try { _action(); }
                catch (Exception ex) { FmUi.Report("search", ex); }
            };
        }

        public void Poke()
        {
            try { _timer.Stop(); _timer.Start(); }
            catch (Exception) { _action(); }
        }

        public void Cancel()
        {
            try { _timer.Stop(); }
            catch (Exception) { }
        }
    }
}
