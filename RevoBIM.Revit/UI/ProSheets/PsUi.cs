using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Xml;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    /// <summary>
    /// Window plumbing shared by every window in this tool. Port of ps_ui.py.
    ///
    /// Loading XAML, merging the theme, the borderless chrome, full screen, the
    /// resize grips, the logo, the easter egg, folder browsing and the message
    /// window. None of it knows anything about exporting.
    ///
    /// Split across PsUi.cs (this file), PsUi.Chrome.cs, PsUi.Prompt.cs and
    /// PsUi.SearchPicker.cs.
    /// </summary>
    public static partial class PsUi
    {
        /// <summary>The folder the add-in DLL was loaded from (the pyRevit bundle folder in the original).</summary>
        public static readonly string HereFolder = SafeAssemblyFolder();

        private static string SafeAssemblyFolder()
        {
            try
            {
                return Path.GetDirectoryName(typeof(PsUi).Assembly.Location) ?? "";
            }
            catch (Exception)
            {
                return "";
            }
        }

        public static string Here(params string[] parts)
        {
            var all = new List<string> { HereFolder };
            all.AddRange(parts ?? new string[0]);
            return Path.Combine(all.ToArray());
        }

        /// <summary>Prefix of the embedded layout resources (see the csproj).</summary>
        public const string LayoutResourcePrefix = "RevoBIM.UI.ProSheets.Layouts.";

        /// <summary>The tool icon, embedded from Resources\ProSheetsExporter\icon.png.</summary>
        public const string LogoResourceName = "RevoBIM.Resources.ProSheetsExporter.icon.png";

        // ==================================================================
        // loading XAML
        // ==================================================================

        /// <summary>
        /// Parse a layout file into a live object. A failure here is the classic
        /// blank window, so the exception is re-raised carrying the file name, the
        /// line and the column - "Theme.xaml line 214 column 19" rather than
        /// "it did not open". The layouts are embedded resources named
        /// RevoBIM.UI.ProSheets.Layouts.&lt;fileName&gt;.
        /// </summary>
        public static object LoadXaml(string fileName)
        {
            Stream stream = null;
            XmlReader reader = null;
            try
            {
                stream = typeof(PsUi).Assembly.GetManifestResourceStream(LayoutResourcePrefix + fileName);
                if (stream == null)
                    throw new FileNotFoundException("embedded resource " + LayoutResourcePrefix + fileName + " was not found");
                reader = XmlReader.Create(stream);
                return XamlReader.Load(reader);
            }
            catch (Exception err)
            {
                throw new Exception(string.Format("{0} would not parse: {1}", fileName, err.Message), err);
            }
            finally
            {
                if (reader != null)
                {
                    try
                    {
                        reader.Close();
                    }
                    catch (Exception)
                    {
                    }
                }
                if (stream != null)
                {
                    try
                    {
                        stream.Dispose();
                    }
                    catch (Exception)
                    {
                    }
                }
            }
        }

        public static ResourceDictionary ThemeDictionary()
        {
            object loaded = LoadXaml("Theme.xaml");
            if (!(loaded is ResourceDictionary dictionary))
                throw new Exception("Theme.xaml did not load as a ResourceDictionary");
            return dictionary;
        }

        /// <summary>A themed window from a layout file, not yet shown.</summary>
        public static Window LoadWindow(string fileName, string themeName = "dark")
        {
            object loaded = LoadXaml(fileName);
            if (!(loaded is Window window))
                throw new Exception(string.Format("{0} did not load as a Window", fileName));
            window.Resources.MergedDictionaries.Add(ThemeDictionary());
            PsTheme.Apply(window, themeName);
            SetVersion(window);
            SetLogo(window);
            return window;
        }

        /// <summary>FindName that returns null instead of throwing on a missing name.</summary>
        public static object Find(object window, string name)
        {
            try
            {
                if (window is FrameworkElement element) return element.FindName(name);
                if (window is FrameworkContentElement content) return content.FindName(name);
            }
            catch (Exception)
            {
            }
            return null;
        }

        /// <summary>Find, cast to the control type; null when missing or of another type.</summary>
        public static T Find<T>(object window, string name) where T : class
        {
            return Find(window, name) as T;
        }

        public static void SetVersion(Window window)
        {
            object label = Find(window, "VersionText");
            if (label != null)
            {
                try
                {
                    SetTextCore(label, "v" + PsVersion.Version);
                }
                catch (Exception)
                {
                }
            }
        }

        // ==================================================================
        // the logo
        // ==================================================================

        /// <summary>A loose icon next to the DLL, if one was deployed; the embedded one is used first.</summary>
        internal static string IconPath()
        {
            foreach (string name in new[] { "icon.png", "icon.large.png", "logo.png" })
            {
                string candidate = Here(name);
                if (File.Exists(candidate)) return candidate;
            }
            return null;
        }

        /// <summary>
        /// A BitmapImage from bytes. Never from a Uri (the Python avoided Uri
        /// because importing it threw on Revit 2025+; kept for parity).
        /// </summary>
        public static BitmapImage LoadBitmap(string path)
        {
            try
            {
                return LoadBitmap(new MemoryStream(File.ReadAllBytes(path)));
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>A frozen BitmapImage from a stream, which this disposes. Null on failure.</summary>
        public static BitmapImage LoadBitmap(Stream stream)
        {
            try
            {
                if (stream == null) return null;
                var image = new BitmapImage();
                image.BeginInit();
                image.CacheOption = BitmapCacheOption.OnLoad;
                image.StreamSource = stream;
                image.EndInit();
                try
                {
                    image.Freeze();
                }
                catch (Exception)
                {
                }
                return image;
            }
            catch (Exception)
            {
                return null;
            }
            finally
            {
                if (stream != null)
                {
                    try
                    {
                        stream.Dispose();
                    }
                    catch (Exception)
                    {
                    }
                }
            }
        }

        /// <summary>The tool icon: the embedded resource, else a loose file next to the DLL.</summary>
        public static BitmapImage LogoBitmap()
        {
            BitmapImage image = null;
            try
            {
                image = LoadBitmap(typeof(PsUi).Assembly.GetManifestResourceStream(LogoResourceName));
            }
            catch (Exception)
            {
            }
            if (image != null) return image;
            string path = IconPath();
            return string.IsNullOrEmpty(path) ? null : LoadBitmap(path);
        }

        /// <summary>Put the tool icon in the header. Cosmetic, so it swallows failures.</summary>
        public static void SetLogo(Window window)
        {
            try
            {
                if (!(Find(window, "LogoImage") is Image host)) return;
                BitmapImage image = LogoBitmap();
                if (image != null) host.Source = image;
            }
            catch (Exception)
            {
            }
        }

        // ==================================================================
        // the easter egg
        // ==================================================================

        /// <summary>
        /// The extension's easter egg lived in the shared revobim.egg Python
        /// package, which the C# add-in does not carry. A no-op that reports
        /// "not armed", as the Python does when the package is missing.
        /// (The Python's _argument_names helper existed only to call into it.)
        /// </summary>
        public static bool AttachEgg(Window window, string elementName = "LogoHost")
        {
            return false;
        }

        // ==================================================================
        // the size of the whole tool
        // ==================================================================

        /// <summary>The sizes the - and + step through. 100% is in the list, so a step always lands back on it.</summary>
        public static readonly double[] ZoomSteps = { 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6 };

        /// <summary>
        /// The next size along from current: direction 1 bigger, -1 smaller, 0
        /// back to 100%. A size between two steps snaps to the next one in the
        /// direction asked, and the ends hold.
        /// </summary>
        public static double ZoomStep(object current, int direction)
        {
            double value;
            if (!TryPyFloat(current, out value)) value = 1.0;
            if (direction == 0) return 1.0;
            if (direction > 0)
            {
                var bigger = ZoomSteps.Where(one => one > value + 0.001).ToList();
                return bigger.Count > 0 ? bigger[0] : ZoomSteps[ZoomSteps.Length - 1];
            }
            var smaller = ZoomSteps.Where(one => one < value - 0.001).ToList();
            return smaller.Count > 0 ? smaller[smaller.Count - 1] : ZoomSteps[0];
        }

        public static double ZoomClamp(object value)
        {
            double number;
            if (!TryPyFloat(value, out number)) return 1.0;
            return Math.Max(ZoomSteps[0], Math.Min(ZoomSteps[ZoomSteps.Length - 1], number));
        }

        public static string ZoomLabel(double scale)
        {
            return string.Format(CultureInfo.InvariantCulture, "{0}%",
                (int)Math.Round(scale * 100, MidpointRounding.AwayFromZero));
        }

        /// <summary>Python float(x): numbers as they are, text parsed invariant; false where float() would raise.</summary>
        internal static bool TryPyFloat(object value, out double number)
        {
            number = 0;
            switch (value)
            {
                case null:
                    return false;
                case double d:
                    number = d;
                    return true;
                case float f:
                    number = f;
                    return true;
                case int i:
                    number = i;
                    return true;
                case long l:
                    number = l;
                    return true;
                case decimal m:
                    number = (double)m;
                    return true;
                case bool b:
                    number = b ? 1 : 0;
                    return true;
            }
            return double.TryParse(Convert.ToString(value, CultureInfo.InvariantCulture).Trim(),
                NumberStyles.Float, CultureInfo.InvariantCulture, out number);
        }

        /// <summary>
        /// - and + in a window's header: the whole tool smaller or bigger.
        ///
        /// A LayoutTransform on the window's content, not a RenderTransform. A
        /// render transform only draws smaller - the layout still asks for the
        /// full size and the edges are cut off. A layout transform lays out as if
        /// the window were bigger and then draws it to fit, which is what "see
        /// more on a small screen" needs. Kept in settings under key.
        ///
        /// Looks for ZoomOutButton, ZoomResetButton and ZoomInButton; any missing
        /// is simply not wired. Ctrl+minus, Ctrl+plus and Ctrl+0 work too.
        /// </summary>
        public class Zoom
        {
            public Window Window;
            public PsConfig.Settings Settings;
            public string Key;
            public double Scale;
            public object ResetButton;

            public Zoom(Window window, PsConfig.Settings settings = null, string key = "ui_scale")
            {
                Window = window;
                Settings = settings;
                Key = key;
                Scale = 1.0;
                if (settings != null)
                {
                    try
                    {
                        string saved = settings.Text(key, "1");
                        Scale = ZoomClamp(string.IsNullOrEmpty(saved) ? "1" : saved);
                    }
                    catch (Exception)
                    {
                        Scale = 1.0;
                    }
                }
                ResetButton = Find(window, "ZoomResetButton");
                foreach (var (name, direction) in new[] { ("ZoomOutButton", -1), ("ZoomInButton", 1), ("ZoomResetButton", 0) })
                {
                    if (!(Find(window, name) is System.Windows.Controls.Primitives.ButtonBase button)) continue;
                    try
                    {
                        button.Click += MakeStep(direction);
                    }
                    catch (Exception)
                    {
                    }
                }
                try
                {
                    window.PreviewKeyDown += KeyPressed;
                }
                catch (Exception)
                {
                }
                Apply();
            }

            internal RoutedEventHandler MakeStep(int direction)
            {
                return (sender, args) => Step(direction);
            }

            internal void KeyPressed(object sender, KeyEventArgs args)
            {
                if (!CtrlDown()) return;
                System.Windows.Input.Key key;
                try
                {
                    key = args.Key;
                }
                catch (Exception)
                {
                    return;
                }
                int? direction = null;
                if (key == System.Windows.Input.Key.OemPlus || key == System.Windows.Input.Key.Add) direction = 1;
                else if (key == System.Windows.Input.Key.OemMinus || key == System.Windows.Input.Key.Subtract) direction = -1;
                else if (key == System.Windows.Input.Key.D0 || key == System.Windows.Input.Key.NumPad0) direction = 0;
                if (direction == null) return;
                Step(direction.Value);
                try
                {
                    args.Handled = true;
                }
                catch (Exception)
                {
                }
            }

            public void Step(int direction)
            {
                Scale = ZoomStep(Scale, direction);
                Apply();
                if (Settings != null)
                {
                    try
                    {
                        Settings.Set(Key, Scale.ToString("F2", CultureInfo.InvariantCulture));
                        Settings.Save();
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            public void Apply()
            {
                try
                {
                    ((FrameworkElement)Window.Content).LayoutTransform = new ScaleTransform(Scale, Scale);
                }
                catch (Exception)
                {
                }
                SetContent(ResetButton, ZoomLabel(Scale));
            }
        }

        // ==================================================================
        // working areas and placing windows
        // ==================================================================

        /// <summary>
        /// The usable bounds of whichever screen this window is on, in DIPs, or
        /// null. SystemParameters.WorkArea is the primary monitor's, so it puts a
        /// full screen window on the wrong display with more than one. Find the
        /// screen from the window handle, then divide by the DPI scale.
        /// </summary>
        public static (double Left, double Top, double Width, double Height)? WorkingArea(Window window)
        {
            try
            {
                IntPtr handle = new WindowInteropHelper(window).Handle;
                var screen = System.Windows.Forms.Screen.FromHandle(handle);
                var area = screen.WorkingArea;

                double scaleX = 1.0, scaleY = 1.0;
                try
                {
                    var presentation = PresentationSource.FromVisual(window);
                    if (presentation != null && presentation.CompositionTarget != null)
                    {
                        Matrix matrix = presentation.CompositionTarget.TransformToDevice;
                        scaleX = matrix.M11 != 0 ? matrix.M11 : 1.0;
                        scaleY = matrix.M22 != 0 ? matrix.M22 : 1.0;
                    }
                }
                catch (Exception)
                {
                    scaleX = scaleY = 1.0;
                }

                return (area.Left / scaleX, area.Top / scaleY, area.Width / scaleX, area.Height / scaleY);
            }
            catch (Exception)
            {
                try
                {
                    return (0.0, 0.0, SystemParameters.WorkArea.Width, SystemParameters.WorkArea.Height);
                }
                catch (Exception)
                {
                    return null;
                }
            }
        }

        /// <summary>
        /// A window's width: what its content needs, never wider than its screen
        /// less margin each side, never narrower than minimum.
        /// </summary>
        public static double SnugWidth(double needed, double areaWidth, double minimum = 0, double margin = 12)
        {
            return Math.Max(minimum, Math.Min(needed, areaWidth - 2 * margin));
        }

        /// <summary>(left, top) centring a window of this size on a working area.</summary>
        public static (double Left, double Top) Centred((double Left, double Top, double Width, double Height) area, double width, double height)
        {
            return (area.Left + (area.Width - width) / 2.0, area.Top + (area.Height - height) / 2.0);
        }

        /// <summary>0 to 1, quick at first and settling at the end - a drawer.</summary>
        public static double EaseOut(double progress)
        {
            progress = Math.Max(0.0, Math.Min(1.0, progress));
            return 1.0 - Math.Pow(1.0 - progress, 3);
        }

        /// <summary>
        /// Where a shrunk title bar sits: on the bottom of the screen's working
        /// area, above any bars already shrunk there (below, their heights), so a
        /// dialog and its owner stack rather than overlap.
        /// </summary>
        public static double ShrunkTop((double Left, double Top, double Width, double Height) area, double bar,
            IEnumerable<double> below = null, double margin = 8, double gap = 4)
        {
            double bottom = area.Top + area.Height - margin;
            foreach (double height in below ?? Enumerable.Empty<double>())
                bottom -= height + gap;
            return bottom - bar;
        }

        /// <summary>
        /// (top, height, saved) after a double-click on a window's top or bottom
        /// edge: the full height of its screen's working area, remembering where
        /// it was - or, when it is already stretched (saved), back to that.
        /// </summary>
        public static (double Top, double Height, (double Top, double Height)? Saved) FullHeight(
            (double Left, double Top, double Width, double Height) area, double top, double height,
            (double Top, double Height)? saved = null)
        {
            if (saved != null) return (saved.Value.Top, saved.Value.Height, null);
            return (area.Top, area.Height, (top, height));
        }

        /// <summary>
        /// The working area of the screen a window's owner is on: a WPF owner,
        /// Revit's main window by handle, or the primary screen.
        /// </summary>
        public static (double Left, double Top, double Width, double Height)? OwnerArea(Window owner = null, IntPtr? ownerHandle = null)
        {
            (double Left, double Top, double Width, double Height)? area = null;
            if (owner != null) area = WorkingArea(owner);
            else if (ownerHandle != null) area = HandleArea(ownerHandle.Value);
            if (area == null)
            {
                try
                {
                    Rect work = SystemParameters.WorkArea;
                    area = (work.Left, work.Top, work.Width, work.Height);
                }
                catch (Exception)
                {
                    area = null;
                }
            }
            return area;
        }

        /// <summary>
        /// Make window as wide as needed - its content - and no wider than its
        /// owner's screen, centred on it left to right. Where the screen is
        /// narrower, what does not fit scrolls.
        /// </summary>
        public static bool FitWidth(Window window, double needed, Window owner = null, IntPtr? ownerHandle = null, double margin = 12)
        {
            var found = OwnerArea(owner, ownerHandle);
            if (found == null) return false;
            var area = found.Value;
            try
            {
                double width = SnugWidth(needed, area.Width, window.MinWidth, margin);
                window.Width = width;
                window.Left = area.Left + (area.Width - width) / 2.0;
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// The working area, in DIPs, of the screen a window handle is on - for a
        /// window owned by Revit's main window rather than a WPF one.
        /// </summary>
        public static (double Left, double Top, double Width, double Height)? HandleArea(IntPtr handle)
        {
            try
            {
                var screen = System.Windows.Forms.Screen.FromHandle(handle);
                var area = screen.WorkingArea;
                double scale = 1.0;
                try
                {
                    scale = (double)System.Windows.Forms.Screen.PrimaryScreen.Bounds.Width / SystemParameters.PrimaryScreenWidth;
                    if (scale == 0 || double.IsNaN(scale) || double.IsInfinity(scale)) scale = 1.0;
                }
                catch (Exception)
                {
                    scale = 1.0;
                }
                return (area.Left / scale, area.Top / scale, area.Width / scale, area.Height / scale);
            }
            catch (Exception)
            {
                return null;
            }
        }

        // ==================================================================
        // owning the window to Revit
        // ==================================================================

        /// <summary>
        /// Make Revit's main window the owner of this one. An unowned modeless
        /// window slips behind Revit the moment Revit takes focus, and reads to the
        /// user as a crash. Owning it keeps it in front of Revit while leaving
        /// Revit completely usable underneath.
        /// </summary>
        public static bool OwnToRevit(Window window, Autodesk.Revit.UI.UIApplication uiapp)
        {
            IntPtr handle;
            try
            {
                handle = uiapp.MainWindowHandle;
            }
            catch (Exception)
            {
                return false;
            }
            try
            {
                var helper = new WindowInteropHelper(window);
                helper.Owner = handle;
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // ==================================================================
        // folder browsing
        // ==================================================================

        /// <summary>A folder picker. Returns the chosen path, or an empty string.</summary>
        public static string BrowseFolder(string start = "", string description = "Where should the export go?")
        {
            System.Windows.Forms.FolderBrowserDialog dialog = null;
            try
            {
                dialog = new System.Windows.Forms.FolderBrowserDialog();
                dialog.Description = description;
                dialog.ShowNewFolderButton = true;
                if (!string.IsNullOrEmpty(start) && Directory.Exists(start))
                    dialog.SelectedPath = start;
                if (dialog.ShowDialog() == System.Windows.Forms.DialogResult.OK)
                    return dialog.SelectedPath ?? "";
            }
            catch (Exception)
            {
            }
            finally
            {
                if (dialog != null)
                {
                    try
                    {
                        dialog.Dispose();
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            return "";
        }

        /// <summary>A file open or save dialog. Returns a path, or an empty string.</summary>
        public static string PickFile(bool save, string title, string extension, string startName = "",
            string label = "RevoBIM template bundle")
        {
            System.Windows.Forms.FileDialog dialog = null;
            try
            {
                if (save) dialog = new System.Windows.Forms.SaveFileDialog();
                else dialog = new System.Windows.Forms.OpenFileDialog();
                dialog.Title = title;
                dialog.Filter = string.Format("{1} (*{0})|*{0}|Text file (*.txt)|*.txt|All files (*.*)|*.*", extension, label);
                dialog.DefaultExt = (extension ?? "").TrimStart('.');
                if (!string.IsNullOrEmpty(startName)) dialog.FileName = startName;
                if (!save) ((System.Windows.Forms.OpenFileDialog)dialog).Multiselect = false;
                if (dialog.ShowDialog() == System.Windows.Forms.DialogResult.OK)
                    return dialog.FileName ?? "";
            }
            catch (Exception)
            {
            }
            finally
            {
                if (dialog != null)
                {
                    try
                    {
                        dialog.Dispose();
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            return "";
        }

        /// <summary>A one line text prompt, built from the message window. The trimmed text, or null on Cancel.</summary>
        public static string AskText(string title, string question, string start = "", string themeName = "dark", Window owner = null)
        {
            var prompt = new Prompt(title: title, headline: question, wantInput: true,
                inputText: start, primary: "OK", secondary: "Cancel",
                themeName: themeName, owner: owner);
            if (prompt.Show() == "primary")
                return (prompt.InputValue ?? "").Trim();
            return null;
        }

        // ==================================================================
        // reporting a failure the user can act on
        // ==================================================================

        /// <summary>
        /// Name the stage that failed, show the exception and its stack, and write
        /// it down (%APPDATA%\RevoBIM\logs\pro_sheets_exporter_last_error.txt).
        /// Getting this in front of the user is the difference between a blank
        /// window and a message naming the file, the line and the column.
        /// </summary>
        public static void ReportFailure(string stage, Exception error = null, string themeName = "dark")
        {
            // traceback.format_exc() -> the exception with its stack trace.
            string detail = error != null ? error.ToString() : "";
            string text = string.Format("Stage: {0}\n\n{1}\n\n{2}", stage, error != null ? error.Message : "", detail);
            string path;
            try
            {
                path = PsConfig.ErrorPath();
                File.WriteAllBytes(path, new UTF8Encoding(false).GetBytes(text));
            }
            catch (Exception)
            {
                path = "(the log file could not be written)";
            }

            try
            {
                new Prompt(title: "Pro Sheets Exporter",
                    headline: "The tool could not open.",
                    message: string.Format("It stopped at \"{0}\". The detail below is also saved to {1}", stage, path),
                    detail: text, primary: "Close",
                    themeName: themeName).Show();
                return;
            }
            catch (Exception)
            {
            }

            try
            {
                string shown = string.Format("Stopped at \"{0}\".\n\n{1}", stage, detail);
                if (shown.Length > 2000) shown = shown.Substring(0, 2000);
                Autodesk.Revit.UI.TaskDialog.Show("RevoBIM Pro Sheets Exporter", shown);
            }
            catch (Exception)
            {
                try
                {
                    Console.Error.Write(text);
                }
                catch (Exception)
                {
                }
            }
        }

        // ==================================================================
        // small conveniences
        // ==================================================================

        public static void SetVisible(object element, bool visible)
        {
            if (element == null) return;
            try
            {
                ((UIElement)element).Visibility = visible ? Visibility.Visible : Visibility.Collapsed;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>element.Text = u'{0}'.format(text). Null shows as "None", as in Python.</summary>
        public static void SetText(object element, object text)
        {
            if (element == null) return;
            try
            {
                SetTextCore(element, PyStr(text));
            }
            catch (Exception)
            {
            }
        }

        /// <summary>element.Content = u'{0}'.format(text). Null shows as "None", as in Python.</summary>
        public static void SetContent(object element, object text)
        {
            if (element == null) return;
            try
            {
                string value = PyStr(text);
                if (element is ContentControl control)
                {
                    control.Content = value;
                    return;
                }
                if (element is ContentPresenter presenter)
                {
                    presenter.Content = value;
                    return;
                }
                SetProperty(element, "Content", value);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Sets a Text property on any element that has one. Throws when it has none.</summary>
        internal static void SetTextCore(object element, string value)
        {
            switch (element)
            {
                case TextBlock block:
                    block.Text = value;
                    return;
                case TextBox box:
                    box.Text = value;
                    return;
                case Run run:
                    run.Text = value;
                    return;
                case ComboBox combo:
                    combo.Text = value;
                    return;
            }
            SetProperty(element, "Text", value);
        }

        private static void SetProperty(object element, string name, object value)
        {
            PropertyInfo property = element.GetType().GetProperty(name, BindingFlags.Public | BindingFlags.Instance);
            if (property == null || !property.CanWrite)
                throw new MissingMemberException(element.GetType().Name, name);
            property.SetValue(element, value);
        }

        /// <summary>
        /// Load a ComboBox and pick an entry without firing the change handler.
        /// The caller detaches its own handler; this only guarantees the order, so
        /// a selection made here is not mistaken for one the user made. Items are
        /// added as strings.
        /// </summary>
        public static void FillCombo(ComboBox combo, IEnumerable items, object selected = null, bool allowBlank = false,
            string blankText = "(none)")
        {
            if (combo == null) return;
            try
            {
                combo.Items.Clear();
                if (allowBlank) combo.Items.Add(blankText);
                if (items != null)
                {
                    foreach (object item in items)
                        combo.Items.Add(PyStr(item));
                }
                if (selected != null)
                {
                    string wanted = PyStr(selected);
                    for (int index = 0; index < combo.Items.Count; index++)
                    {
                        if (PyStr(combo.Items[index]) == wanted)
                        {
                            combo.SelectedIndex = index;
                            return;
                        }
                    }
                }
                if (combo.Items.Count > 0 && combo.SelectedIndex < 0)
                    combo.SelectedIndex = 0;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>The picked entry's text, or "" for nothing picked or the blank entry.</summary>
        public static string ComboText(ComboBox combo, string blankText = "(none)")
        {
            if (combo == null) return "";
            try
            {
                object value = combo.SelectedItem;
                if (value == null) return "";
                string text = PyStr(value);
                return text == blankText ? "" : text;
            }
            catch (Exception)
            {
                return "";
            }
        }

        public static bool CtrlDown()
        {
            try
            {
                return (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static bool ShiftDown()
        {
            try
            {
                return (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// Python's u'{0}'.format(value): null is "None", booleans "True"/"False",
        /// a float shows as Python 2 would ('297.0', '0.25'); anything else its
        /// invariant ToString.
        /// </summary>
        public static string PyStr(object value)
        {
            switch (value)
            {
                case null:
                    return "None";
                case string text:
                    return text;
                case bool flag:
                    return flag ? "True" : "False";
                case double number:
                    return PyFloat(number);
                case float single:
                    return PyFloat(single);
            }
            return Convert.ToString(value, CultureInfo.InvariantCulture) ?? "";
        }

        private static string PyFloat(double number)
        {
            if (double.IsNaN(number)) return "nan";
            if (double.IsPositiveInfinity(number)) return "inf";
            if (double.IsNegativeInfinity(number)) return "-inf";
            if (number == Math.Floor(number) && Math.Abs(number) < 1e16)
                return number.ToString("0.0", CultureInfo.InvariantCulture);
            return number.ToString("R", CultureInfo.InvariantCulture);
        }

        // ==================================================================
        // a box you type into to pick from a long list
        // ==================================================================

        /// <summary>The names holding every word typed, anywhere, in any case.</summary>
        public static List<string> WordsMatch(IEnumerable<string> names, string text)
        {
            string[] words = (text ?? "").ToLowerInvariant().Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            if (words.Length == 0) return names.ToList();
            return names.Where(name => words.All(word => (name ?? "None").ToLowerInvariant().Contains(word))).ToList();
        }
    }
}
