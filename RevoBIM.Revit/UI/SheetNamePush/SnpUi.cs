using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Xml;
using System.Xml.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.SheetNamePush;

using Color = System.Windows.Media.Color;
using Border = System.Windows.Controls.Border;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using Grid = System.Windows.Controls.Grid;
using TextBox = System.Windows.Controls.TextBox;
using Visibility = System.Windows.Visibility;

namespace RevoBIM.UI.SheetNamePush
{
    /// <summary>
    /// Loads the pyRevit XAML layouts verbatim. pyRevit wires handlers named in the XAML (Click="apply_click"); XamlReader cannot, so
    /// those attributes are lifted out before loading and wired afterwards by name to the handlers the window passes in.
    /// </summary>
    internal static class SnpXaml
    {
        private const string LayoutPrefix = "RevoBIM.UI.SheetNamePush.Layouts.";
        private const string ResourcePrefix = "RevoBIM.Resources.SheetNamePush.";
        private static readonly XNamespace X = "http://schemas.microsoft.com/winfx/2006/xaml";
        private static readonly Regex HandlerName = new Regex("^[a-z][a-z0-9]*(_[a-z0-9]+)+$", RegexOptions.Compiled);

        private sealed class Hook
        {
            public string Element, Event, Handler;
        }

        public static string ReadLayout(string file)
        {
            using (Stream stream = typeof(SnpXaml).Assembly.GetManifestResourceStream(LayoutPrefix + file))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + LayoutPrefix + file + " was not found");
                using (var reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        public static Window Load(string file, Dictionary<string, Action<object, RoutedEventArgs>> handlers)
        {
            XDocument doc = XDocument.Parse(ReadLayout(file), LoadOptions.PreserveWhitespace);
            var hooks = new List<Hook>();
            int counter = 0;
            foreach (XElement element in doc.Descendants().ToList())
            {
                foreach (XAttribute attr in element.Attributes().ToList())
                {
                    string ev = attr.Name.LocalName;
                    if (ev != "Click" && ev != "TextChanged" && ev != "MouseLeftButtonDown") continue;
                    if (!HandlerName.IsMatch(attr.Value)) continue;
                    string name = (string)element.Attribute(X + "Name");
                    if (string.IsNullOrEmpty(name))
                    {
                        name = "snpHook" + counter++;
                        element.SetAttributeValue(X + "Name", name);
                    }
                    hooks.Add(new Hook { Element = name, Event = ev, Handler = attr.Value });
                    attr.Remove();
                }
            }
            object loaded;
            using (XmlReader reader = XmlReader.Create(new StringReader(doc.ToString(System.Xml.Linq.SaveOptions.DisableFormatting))))
                loaded = XamlReader.Load(reader);
            var window = loaded as Window;
            if (window == null) throw new InvalidCastException(file + " is not a Window");

            foreach (Hook hook in hooks)
            {
                var target = window.FindName(hook.Element) as UIElement;
                Action<object, RoutedEventArgs> handler;
                if (target == null || !handlers.TryGetValue(hook.Handler, out handler))
                    throw new InvalidOperationException("could not wire " + hook.Handler + " (" + hook.Event + ") in " + file);
                if (hook.Event == "Click") target.AddHandler(ButtonBase.ClickEvent, new RoutedEventHandler((s, e) => handler(s, e)));
                else if (hook.Event == "TextChanged") target.AddHandler(TextBoxBase.TextChangedEvent, new TextChangedEventHandler((s, e) => handler(s, e)));
                else target.AddHandler(UIElement.MouseLeftButtonDownEvent, new MouseButtonEventHandler((s, e) => handler(s, e)));
            }
            return window;
        }

        public static BitmapImage Bitmap(string file)
        {
            try
            {
                using (Stream stream = typeof(SnpXaml).Assembly.GetManifestResourceStream(ResourcePrefix + file))
                {
                    if (stream == null) return null;
                    var bmp = new BitmapImage();
                    bmp.BeginInit();
                    bmp.StreamSource = stream;
                    bmp.CacheOption = BitmapCacheOption.OnLoad;
                    bmp.EndInit();
                    bmp.Freeze();
                    return bmp;
                }
            }
            catch (Exception)
            {
                return null;
            }
        }
    }

    /// <summary>Shared chrome: draggable header, icon, version. Every window is modal and owned by Revit or by the window that opened it.</summary>
    internal abstract class SnpWindowBase
    {
        public Window Win;
        protected readonly SnpCore.Log Log;

        protected SnpWindowBase(SnpCore.Log log) { Log = log; }

        protected T C<T>(string name) where T : class
        {
            var element = Win.FindName(name) as T;
            if (element == null) throw new InvalidOperationException("Layout is missing: " + name);
            return element;
        }

        protected T Find<T>(string name) where T : class { return Win.FindName(name) as T; }

        protected void Load(string file, string icon, Dictionary<string, Action<object, RoutedEventArgs>> handlers)
        {
            handlers["header_drag"] = (s, e) => { try { Win.DragMove(); } catch (Exception) { } };
            handlers["cancel_click"] = (s, e) => Cancel();
            Dictionary<string, Action<object, RoutedEventArgs>> guarded = handlers.ToDictionary(p => p.Key, p => Guard(p.Value));
            Win = SnpXaml.Load(file, guarded);
            var version = Find<TextBlock>("tb_version");
            if (version != null) version.Text = "v" + SnpCore.Version;
            var image = Find<Image>("img_icon");
            if (image != null)
            {
                BitmapImage bmp = SnpXaml.Bitmap(icon);
                if (bmp != null) image.Source = bmp;
            }
        }

        /// <summary>A WPF event swallows exceptions silently, so every wired handler writes them down.</summary>
        protected Action<object, RoutedEventArgs> Guard(Action<object, RoutedEventArgs> fn)
        {
            return (s, e) =>
            {
                try
                {
                    fn(s, e);
                }
                catch (Exception err)
                {
                    if (Log != null) Log.Write("error: handler failed: " + err);
                    try
                    {
                        Directory.CreateDirectory(SnpCore.DataDir());
                        File.WriteAllText(SnpCore.ErrorPath(), err.ToString());
                    }
                    catch (Exception)
                    {
                    }
                }
            };
        }

        protected virtual void Cancel()
        {
            try { Win.DialogResult = false; } catch (Exception) { }
            Win.Close();
        }

        public bool ShowModal(Window owner, UIApplication uiapp)
        {
            if (owner != null) Win.Owner = owner;
            else if (uiapp != null)
            {
                try { new WindowInteropHelper(Win).Owner = uiapp.MainWindowHandle; } catch (Exception) { }
            }
            return Win.ShowDialog() == true;
        }
    }

    // ---------------------------------------------------------------------------------- settings --

    internal sealed class SnpSettingsWindow : SnpWindowBase
    {
        private readonly Dictionary<string, string> cfg;
        private readonly ComboBox[] boxes;
        public bool Saved;

        public Dictionary<string, string> Settings { get { return cfg; } }

        public SnpSettingsWindow(Dictionary<string, string> current, Document doc, SnpCore.Log log) : base(log)
        {
            Load("settings.xaml", "icon.png", new Dictionary<string, Action<object, RoutedEventArgs>>
            {
                { "defaults_click", (s, e) => Defaults() },
                { "apply_click", (s, e) => Apply() },
            });
            cfg = new Dictionary<string, string>(current);
            boxes = new[] { C<ComboBox>("cb_p1"), C<ComboBox>("cb_p2"), C<ComboBox>("cb_p3") };
            string[] keys = { "param_1", "param_2", "param_3" };
            List<string> available = SnpCore.SheetTextParameters(doc);
            for (int i = 0; i < boxes.Length; i++)
            {
                string value;
                string currentValue = cfg.TryGetValue(keys[i], out value) ? value : "";
                var items = new List<string>(available);
                if (currentValue.Length > 0 && !items.Contains(currentValue)) items.Insert(0, currentValue);
                if (items.Count == 0) items.Add(currentValue);
                boxes[i].ItemsSource = items;
                boxes[i].SelectedItem = currentValue;
            }
            if (available.Count == 0)
                C<TextBlock>("tb_note").Text = "No writable text parameters were found on the sheets in this model. The saved names are kept - add the parameters to sheets and they will appear here.";
            Log.Write("settings: opened; " + available.Count + " writable sheet text parameter(s) found");
        }

        private void Defaults()
        {
            for (int i = 0; i < boxes.Length; i++)
            {
                var items = (boxes[i].ItemsSource as IEnumerable<string> ?? new string[0]).ToList();
                if (!items.Contains(SnpCore.DefaultParams[i]))
                {
                    items.Insert(0, SnpCore.DefaultParams[i]);
                    boxes[i].ItemsSource = items;
                }
                boxes[i].SelectedItem = SnpCore.DefaultParams[i];
            }
        }

        private void Apply()
        {
            var chosen = boxes.Select(b => b.SelectedItem == null ? "" : b.SelectedItem.ToString().Trim()).ToList();
            if (!chosen.Any(c => c.Length > 0))
            {
                C<TextBlock>("tb_note").Text = "Choose at least one target parameter.";
                return;
            }
            cfg["param_1"] = chosen[0];
            cfg["param_2"] = chosen[1];
            cfg["param_3"] = chosen[2];
            cfg["settings_version"] = SnpCore.SettingsVersion;
            SnpCore.SaveSettings(cfg);
            Log.Write("settings: saved targets '" + chosen[0] + "', '" + chosen[1] + "', '" + chosen[2] + "'");
            Saved = true;
            Win.DialogResult = true;
            Win.Close();
        }
    }

    // ---------------------------------------------------------------------------------- find / affix --

    /// <summary>The preview pane line: old text, an arrow, new text in orange.</summary>
    internal static class SnpPreview
    {
        public static UIElement Line(string before, string after)
        {
            var panel = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 2) };
            panel.Children.Add(new TextBlock { Text = before, FontSize = 11, Foreground = new SolidColorBrush(Color.FromRgb(0x9A, 0x9A, 0x9E)) });
            panel.Children.Add(new TextBlock { Text = "   →   ", FontSize = 11, Foreground = new SolidColorBrush(Color.FromRgb(0x9A, 0x9A, 0x9E)) });
            panel.Children.Add(new TextBlock
            {
                Text = after, FontSize = 11, FontWeight = FontWeights.SemiBold, Foreground = new SolidColorBrush(Color.FromRgb(0xE8, 0x91, 0x2D)),
            });
            return panel;
        }
    }

    internal abstract class SnpChangeWindow : SnpWindowBase
    {
        protected readonly List<SnpTarget> Targets;
        public Dictionary<long, Dictionary<string, string>> Changes = new Dictionary<long, Dictionary<string, string>>();

        protected SnpChangeWindow(SnpCore.Log log, List<SnpTarget> targets) : base(log) { Targets = targets; }

        protected void Init(string file, string icon, Action<string> extraWire, string emptyText)
        {
            Load(file, icon, new Dictionary<string, Action<object, RoutedEventArgs>>
            {
                { "preview_changed", (s, e) => Refresh() },
                { "apply_click", (s, e) => ApplyClick() },
            });
            C<TextBlock>("tb_scope").Text = "Applies to the " + Targets.Count + " sheet(s) currently ticked or shown.";
            this.emptyText = emptyText;
            Refresh();
        }

        private string emptyText = "";

        protected IEnumerable<string> Fields()
        {
            if (C<RadioButton>("rb_both").IsChecked == true) return new[] { "number", "name" };
            if (C<RadioButton>("rb_number").IsChecked == true) return new[] { "number" };
            return new[] { "name" };
        }

        protected abstract Dictionary<long, Dictionary<string, string>> Compute();

        private void Refresh()
        {
            try
            {
                Changes = Compute();
                var panel = C<StackPanel>("sp_preview");
                panel.Children.Clear();
                int shown = 0;
                foreach (SnpTarget t in Targets)
                {
                    Dictionary<string, string> row;
                    if (!Changes.TryGetValue(t.Id, out row)) continue;
                    foreach (string field in new[] { "number", "name" })
                    {
                        if (!row.ContainsKey(field)) continue;
                        panel.Children.Add(SnpPreview.Line(t.Get(field), row[field]));
                        shown++;
                    }
                    if (shown > 200) break;
                }
                C<TextBlock>("tb_status").Text = Changes.Count > 0 ? shown + " change(s) on " + Changes.Count + " sheet(s)." : emptyText;
            }
            catch (Exception err)
            {
                Log.Write("error: preview failed: " + err.Message);
            }
        }

        private void ApplyClick()
        {
            if (Changes.Count == 0)
            {
                C<TextBlock>("tb_status").Text = "Nothing to stage.";
                return;
            }
            Win.DialogResult = true;
            Win.Close();
        }

        protected override void Cancel()
        {
            Changes = new Dictionary<long, Dictionary<string, string>>();
            base.Cancel();
        }
    }

    internal sealed class SnpFindReplaceWindow : SnpChangeWindow
    {
        public SnpFindReplaceWindow(List<SnpTarget> targets, SnpCore.Log log) : base(log, targets)
        {
            Init("findreplace.xaml", "findreplace.png", null, "No matches.");
        }

        protected override Dictionary<long, Dictionary<string, string>> Compute()
        {
            string find = C<TextBox>("tb_find").Text ?? "";
            string repl = C<TextBox>("tb_replace").Text ?? "";
            if (find.Length == 0) return new Dictionary<long, Dictionary<string, string>>();
            bool matchCase = C<CheckBox>("cb_case").IsChecked == true;
            return SnpCore.Compute(Targets, Fields(), text => SnpCore.Replace(text, find, repl, matchCase));
        }
    }

    internal sealed class SnpAffixWindow : SnpChangeWindow
    {
        public SnpAffixWindow(List<SnpTarget> targets, SnpCore.Log log) : base(log, targets)
        {
            Init("affix.xaml", "affix.png", null, "Nothing to change.");
        }

        protected override Dictionary<long, Dictionary<string, string>> Compute()
        {
            string prefix = C<TextBox>("tb_prefix").Text ?? "";
            string suffix = C<TextBox>("tb_suffix").Text ?? "";
            if (prefix.Length == 0 && suffix.Length == 0) return new Dictionary<long, Dictionary<string, string>>();
            bool remove = C<CheckBox>("cb_remove").IsChecked == true;
            return SnpCore.Compute(Targets, Fields(), text => SnpCore.ApplyAffix(text, prefix, suffix, remove));
        }
    }

    // ---------------------------------------------------------------------------------- results --

    internal sealed class SnpResultsWindow : SnpWindowBase
    {
        private double numWidth = 120, nameWidth = 200;

        public SnpResultsWindow(List<SnpPushRow> rows, string modeLabel, int sheetCount, SnpCore.Log log) : base(log)
        {
            Load("results.xaml", "icon.png", new Dictionary<string, Action<object, RoutedEventArgs>>
            {
                { "close_click", (s, e) => Win.Close() },
            });
            int ok = 0, problems = 0;
            foreach (SnpPushRow row in rows)
                foreach (SnpPushResult r in row.Results)
                {
                    if (r.Status == "OK") ok++;
                    else if (r.Status != "skipped (no segment)") problems++;
                }
            C<TextBlock>("tb_summary").Text = sheetCount + " sheet(s) - " + ok + " parameter(s) written - text format: " + modeLabel;
            C<TextBlock>("tb_footer").Text = problems > 0 ? problems + " item(s) need a look" : "Everything written cleanly.";
            SizeColumns(rows);
            var panel = C<StackPanel>("sp_results");
            foreach (SnpPushRow row in rows)
                foreach (SnpPushResult r in row.Results)
                    panel.Children.Add(BuildRow(row.Number, row.Name, r));
            Log.Write("results: " + sheetCount + " sheet(s), " + ok + " written, " + problems + " need a look");
        }

        private void SizeColumns(List<SnpPushRow> rows)
        {
            try
            {
                int longestNum = rows.Count > 0 ? rows.Max(r => r.Number.Length) : 10;
                int longestName = rows.Count > 0 ? rows.Max(r => r.Name.Length) : 20;
                numWidth = Math.Min(Math.Max(longestNum * SnpCore.CharPx + 20, 110), 300);
                nameWidth = Math.Min(Math.Max(longestName * SnpCore.CharPx + 20, 180), 620);
                C<ColumnDefinition>("col_num").Width = new GridLength(numWidth);
                C<ColumnDefinition>("col_name").Width = new GridLength(nameWidth);
                double total = numWidth + nameWidth + 150 + 130 + 170 + 34 + 20;
                double screen = SystemParameters.WorkArea.Width - 80;
                Win.Width = Math.Max(620, Math.Min(total, screen));
            }
            catch (Exception)
            {
                numWidth = 120;
                nameWidth = 200;
            }
        }

        private static TextBlock Cell(string text, int column, Color? color, bool bold, bool wrap)
        {
            var tb = new TextBlock
            {
                Text = text ?? "", FontSize = 11, Margin = new Thickness(0, 0, 10, 0),
                Foreground = new SolidColorBrush(color ?? Color.FromRgb(0xE4, 0xE4, 0xE4)),
            };
            if (bold) tb.FontWeight = FontWeights.SemiBold;
            if (wrap) tb.TextWrapping = TextWrapping.Wrap;
            else tb.TextTrimming = TextTrimming.CharacterEllipsis;
            Grid.SetColumn(tb, column);
            return tb;
        }

        private Grid BuildRow(string number, string name, SnpPushResult r)
        {
            var grid = new Grid { Margin = new Thickness(6, 3, 6, 3) };
            foreach (GridLength w in new[]
            {
                new GridLength(numWidth), new GridLength(nameWidth), new GridLength(150), new GridLength(130), new GridLength(1, GridUnitType.Star),
            })
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = w });
            Color muted = Color.FromRgb(0x9A, 0x9A, 0x9E);
            Color statusColor = r.Status == "OK" ? Color.FromRgb(0x3F, 0xA7, 0x5A)
                : r.Status == "skipped (no segment)" ? Color.FromRgb(0xE8, 0x91, 0x2D) : Color.FromRgb(0xD9, 0x53, 0x4F);
            grid.Children.Add(Cell(number, 0, null, true, false));
            grid.Children.Add(Cell(name, 1, null, false, false));
            grid.Children.Add(Cell(r.Parameter, 2, muted, false, false));
            grid.Children.Add(Cell(r.Value ?? "-", 3, null, false, false));
            grid.Children.Add(Cell(r.Status, 4, statusColor, true, true));
            return grid;
        }
    }

    // ---------------------------------------------------------------------------------- main --

    internal sealed class SnpMainWindow : SnpWindowBase
    {
        private static readonly Brush BSel = Frozen(Color.FromRgb(0x2B, 0x54, 0x73));
        private static readonly Color CText = Color.FromRgb(0xE4, 0xE4, 0xE4);
        private static readonly Color CBlue = Color.FromRgb(0x4F, 0xA3, 0xE3);
        private static readonly Color COrange = Color.FromRgb(0xE8, 0x91, 0x2D);
        private static readonly Color CRed = Color.FromRgb(0xD9, 0x53, 0x4F);

        private readonly UIApplication uiapp;
        private readonly Document doc;
        private readonly List<SnpRecord> records;
        private readonly Dictionary<long, SnpRecord> byId;
        private readonly HashSet<long> preselected;
        private readonly HashSet<long> ticked;
        private HashSet<long> highlighted = new HashSet<long>();
        private long? anchor;
        private readonly Dictionary<long, Dictionary<string, string>> edits = new Dictionary<long, Dictionary<string, string>>();
        private bool isolated, dupesOnly, building;
        private List<long> visibleOrder = new List<long>();
        private double numWidth = 170;

        public Dictionary<string, string> Cfg;
        public string FormatMode;
        public bool Pushed;
        public List<ViewSheet> ResultSheets = new List<ViewSheet>();

        private static Brush Frozen(Color c)
        {
            var b = new SolidColorBrush(c);
            b.Freeze();
            return b;
        }

        public SnpMainWindow(UIApplication uiapp, Document doc, List<SnpRecord> records, HashSet<long> preselectedIds,
                             Dictionary<string, string> cfg, SnpCore.Log log) : base(log)
        {
            this.uiapp = uiapp;
            this.doc = doc;
            this.records = records;
            byId = records.ToDictionary(r => r.Id);
            preselected = new HashSet<long>(preselectedIds);
            ticked = new HashSet<long>(preselectedIds);
            isolated = preselected.Count > 0;
            Cfg = cfg;
            FormatMode = cfg["format_mode"];

            Load("ui.xaml", "icon.png", new Dictionary<string, Action<object, RoutedEventArgs>>
            {
                { "settings_click", (s, e) => SettingsClick() },
                { "filter_changed", (s, e) => RebuildRows() },
                { "tick_all_click", (s, e) => { foreach (SnpRecord r in VisibleRecords()) ticked.Add(r.Id); RebuildRows(); } },
                { "tick_none_click", (s, e) => { foreach (SnpRecord r in VisibleRecords()) ticked.Remove(r.Id); RebuildRows(); } },
                { "findreplace_click", (s, e) => FindReplaceClick() },
                { "affix_click", (s, e) => AffixClick() },
                { "revert_click", (s, e) => RevertClick() },
                { "show_all_click", (s, e) => { isolated = C<CheckBox>("cb_show_all").IsChecked != true; RebuildRows(); } },
                { "dupes_click", (s, e) => { dupesOnly = C<CheckBox>("cb_dupes_only").IsChecked == true; RebuildRows(); } },
                { "format_changed", (s, e) => FormatChanged() },
                { "apply_edits_click", (s, e) => ApplyEditsClick() },
                { "push_click", (s, e) => PushClick() },
            });

            foreach (var pair in new[] { Tuple.Create("img_gear", "gear.png"), Tuple.Create("img_find", "findreplace.png"), Tuple.Create("img_affix", "affix.png") })
            {
                var image = Find<Image>(pair.Item1);
                BitmapImage bmp = SnpXaml.Bitmap(pair.Item2);
                if (image != null && bmp != null) image.Source = bmp;
            }
            try { EggHook.Attach(Win, () => "dark", C<Image>("img_icon")); } catch (Exception) { }
            SizeColumns();

            if (FormatMode == "title") C<RadioButton>("rb_title").IsChecked = true;
            else if (FormatMode == "none") C<RadioButton>("rb_none").IsChecked = true;
            else C<RadioButton>("rb_upper").IsChecked = true;

            if (preselected.Count > 0)
            {
                var showAll = C<CheckBox>("cb_show_all");
                showAll.Visibility = Visibility.Visible;
                showAll.IsChecked = false;
                C<TextBlock>("tb_status").Text = preselected.Count + " sheet(s) selected in the Project Browser.";
            }
            else C<TextBlock>("tb_status").Text = "Showing all sheets. Double-click a cell to edit it.";
            Log.Write("window: " + records.Count + " sheet(s), " + preselected.Count + " preselected, format " + FormatMode +
                      ", targets '" + cfg["param_1"] + "', '" + cfg["param_2"] + "', '" + cfg["param_3"] + "'");
            RebuildRows();
        }

        // ---------------------------------------------------------------- current values --

        private string Current(SnpRecord rec, string field)
        {
            Dictionary<string, string> row;
            string value;
            return edits.TryGetValue(rec.Id, out row) && row.TryGetValue(field, out value) ? value : rec.Get(field);
        }

        private bool IsEdited(SnpRecord rec, string field)
        {
            Dictionary<string, string> row;
            return edits.TryGetValue(rec.Id, out row) && row.ContainsKey(field);
        }

        /// <summary>Sheet numbers used more than once, counting staged edits.</summary>
        private HashSet<string> DuplicateNumbers()
        {
            var seen = new Dictionary<string, int>();
            foreach (SnpRecord rec in records)
            {
                string num = Current(rec, "number").Trim().ToLowerInvariant();
                int n;
                seen[num] = seen.TryGetValue(num, out n) ? n + 1 : 1;
            }
            return new HashSet<string>(seen.Where(p => p.Value > 1 && p.Key.Length > 0).Select(p => p.Key));
        }

        private void SizeColumns()
        {
            try
            {
                int longest = records.Count > 0 ? records.Max(r => r.Number.Length) : 12;
                numWidth = Math.Min(Math.Max(longest * SnpCore.CharPx + 30, 130), 340);
                C<ColumnDefinition>("col_hdr_number").Width = new GridLength(numWidth);
            }
            catch (Exception)
            {
                numWidth = 170;
            }
        }

        // ---------------------------------------------------------------- filtering --

        private List<SnpRecord> VisibleRecords()
        {
            IEnumerable<SnpRecord> recs = records;
            if (isolated && preselected.Count > 0) recs = recs.Where(r => preselected.Contains(r.Id));
            if (dupesOnly)
            {
                HashSet<string> dupes = DuplicateNumbers();
                recs = recs.Where(r => dupes.Contains(Current(r, "number").Trim().ToLowerInvariant()));
            }
            string text = ((Find<TextBox>("tb_filter") == null ? "" : Find<TextBox>("tb_filter").Text) ?? "").Trim().ToLowerInvariant();
            if (text.Length > 0)
                recs = recs.Where(r => Current(r, "number").ToLowerInvariant().Contains(text) || Current(r, "name").ToLowerInvariant().Contains(text));
            return recs.ToList();
        }

        // ---------------------------------------------------------------- rows --

        private string CountText(int shown)
        {
            return shown + " shown / " + ticked.Count + " ticked / " + edits.Count + " edited / " + records.Count + " in project";
        }

        private void RebuildRows()
        {
            if (Win == null || Find<StackPanel>("sp_sheets") == null) return;
            building = true;
            try
            {
                var panel = C<StackPanel>("sp_sheets");
                panel.Children.Clear();
                List<SnpRecord> recs = VisibleRecords();
                visibleOrder = recs.Select(r => r.Id).ToList();
                HashSet<string> dupes = DuplicateNumbers();
                foreach (SnpRecord rec in recs) panel.Children.Add(BuildRow(rec, dupes));
                C<TextBlock>("tb_count").Text = CountText(recs.Count);
                RefreshApplyButton();
            }
            finally
            {
                building = false;
            }
        }

        private UIElement BuildRow(SnpRecord rec, HashSet<string> dupes)
        {
            var wrapper = new Border
            {
                CornerRadius = new CornerRadius(3), Padding = new Thickness(6, 3, 6, 3), Margin = new Thickness(0, 1, 0, 1),
                Background = highlighted.Contains(rec.Id) ? BSel : Brushes.Transparent, Tag = rec.Id,
            };
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(26) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(numWidth) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            var cb = new CheckBox { IsChecked = ticked.Contains(rec.Id), Tag = rec.Id };
            cb.Click += (s, e) => Run(() => RowTicked((CheckBox)s, e));
            Grid.SetColumn(cb, 0);
            grid.Children.Add(cb);

            bool isDupe = dupes.Contains(Current(rec, "number").Trim().ToLowerInvariant());
            grid.Children.Add(Cell(rec, "number", 1, isDupe));
            grid.Children.Add(Cell(rec, "name", 2, false));
            wrapper.Child = grid;
            wrapper.MouseLeftButtonDown += (s, e) => Run(() => RowClick((Border)s));
            return wrapper;
        }

        private void Run(Action fn)
        {
            try
            {
                fn();
            }
            catch (Exception err)
            {
                Log.Write("error: handler failed: " + err);
                try { C<TextBlock>("tb_status").Text = "Something went wrong - the details are in " + SnpCore.DebugPath(); } catch (Exception) { }
            }
        }

        /// <summary>A cell holding a TextBlock and a hidden TextBox editor.</summary>
        private UIElement Cell(SnpRecord rec, string field, int column, bool isDupe)
        {
            var host = new Grid();
            Grid.SetColumn(host, column);
            string value = Current(rec, field);
            var label = new TextBlock
            {
                Text = value, FontSize = 12, Margin = new Thickness(0, 0, 10, 0), TextTrimming = TextTrimming.CharacterEllipsis,
                VerticalAlignment = VerticalAlignment.Center,
            };
            if (isDupe)
            {
                label.Foreground = new SolidColorBrush(CRed);
                label.FontWeight = FontWeights.SemiBold;
                label.ToolTip = "This sheet number is already in use";
            }
            else if (IsEdited(rec, field))
            {
                label.Foreground = new SolidColorBrush(COrange);
                label.FontWeight = FontWeights.SemiBold;
                label.ToolTip = "Edited - was: " + rec.Get(field);
            }
            else if (field == "number")
            {
                label.Foreground = new SolidColorBrush(preselected.Contains(rec.Id) ? CBlue : CText);
                label.FontWeight = FontWeights.SemiBold;
            }
            else label.Foreground = new SolidColorBrush(CText);

            var editor = new TextBox { Text = value, Visibility = Visibility.Collapsed, Tag = Tuple.Create(rec.Id, field), VerticalAlignment = VerticalAlignment.Center };
            var style = Win.TryFindResource("CellEditor") as Style;
            if (style != null) editor.Style = style;
            editor.KeyDown += (s, e) => Run(() => EditorKey((TextBox)s, e));
            editor.LostFocus += (s, e) => Run(() => Commit((TextBox)s));

            host.Children.Add(label);
            host.Children.Add(editor);
            label.Tag = editor;
            label.MouseLeftButtonDown += (s, e) => Run(() => CellClick((TextBlock)s, e));
            return host;
        }

        // ---------------------------------------------------------------- interaction --

        private static bool ShiftDown() { return (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift; }
        private static bool CtrlDown() { return (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control; }

        /// <summary>Click anywhere on a row to highlight; shift extends, ctrl adds.</summary>
        private void RowClick(Border row)
        {
            if (building || !(row.Tag is long)) return;
            Select((long)row.Tag, ShiftDown(), CtrlDown());
        }

        /// <summary>Single click highlights, double click opens the editor.</summary>
        private void CellClick(TextBlock label, MouseButtonEventArgs args)
        {
            if (building) return;
            if (args.ClickCount >= 2)
            {
                var editor = (TextBox)label.Tag;
                label.Visibility = Visibility.Collapsed;
                editor.Visibility = Visibility.Visible;
                editor.Focus();
                editor.SelectAll();
                args.Handled = true;
                return;
            }
            // label -> host grid -> row grid -> border
            DependencyObject el = label;
            for (int i = 0; i < 3 && el != null; i++) el = LogicalTreeHelper.GetParent(el);
            var border = el as Border;
            if (border == null || !(border.Tag is long)) return;
            Select((long)border.Tag, ShiftDown(), CtrlDown());
            args.Handled = true;
        }

        /// <summary>Plain click replaces, ctrl adds or removes, shift extends a range.</summary>
        private void Select(long sid, bool shift, bool ctrl)
        {
            if (shift && anchor != null && visibleOrder.Contains(anchor.Value) && visibleOrder.Contains(sid))
            {
                int start = visibleOrder.IndexOf(anchor.Value), end = visibleOrder.IndexOf(sid);
                if (start > end)
                {
                    int t = start; start = end; end = t;
                }
                var block = new HashSet<long>(visibleOrder.Skip(start).Take(end - start + 1));
                // ctrl+shift adds the range to what is already highlighted
                if (ctrl) block.UnionWith(highlighted);
                highlighted = block;
            }
            else if (ctrl)
            {
                if (!highlighted.Remove(sid)) highlighted.Add(sid);
                anchor = sid;
            }
            else
            {
                highlighted = new HashSet<long> { sid };
                anchor = sid;
            }
            PaintHighlight();
            if (highlighted.Count > 1) C<TextBlock>("tb_status").Text = highlighted.Count + " row(s) highlighted - tick one of them to tick them all.";
            else if (highlighted.Count == 0) C<TextBlock>("tb_status").Text = "Nothing highlighted.";
        }

        private void PaintHighlight()
        {
            foreach (UIElement child in C<StackPanel>("sp_sheets").Children)
            {
                var border = child as Border;
                if (border != null && border.Tag is long) border.Background = highlighted.Contains((long)border.Tag) ? BSel : Brushes.Transparent;
            }
        }

        /// <summary>Ticking a highlighted row applies to the whole highlight.</summary>
        private void RowTicked(CheckBox box, RoutedEventArgs args)
        {
            if (building) return;
            long sid = (long)box.Tag;
            bool state = box.IsChecked == true;
            HashSet<long> targets = highlighted.Contains(sid) && highlighted.Count > 1 ? new HashSet<long>(highlighted) : new HashSet<long> { sid };
            foreach (long target in targets)
            {
                if (state) ticked.Add(target); else ticked.Remove(target);
            }
            if (targets.Count > 1)
            {
                RebuildRows();
                C<TextBlock>("tb_status").Text = targets.Count + " row(s) " + (state ? "ticked" : "unticked") + ".";
            }
            else C<TextBlock>("tb_count").Text = CountText(visibleOrder.Count);
            args.Handled = true;
        }

        // ---------------------------------------------------------------- editing --

        private void EditorKey(TextBox editor, KeyEventArgs args)
        {
            if (args.Key == Key.Enter)
            {
                Commit(editor);
                args.Handled = true;
            }
            else if (args.Key == Key.Escape)
            {
                editor.Visibility = Visibility.Collapsed;
                RebuildRows();
                args.Handled = true;
            }
        }

        private void Commit(TextBox editor)
        {
            if (building) return;
            var tag = editor.Tag as Tuple<long, string>;
            SnpRecord rec;
            if (tag == null || !byId.TryGetValue(tag.Item1, out rec)) return;
            string field = tag.Item2;
            string value = (editor.Text ?? "").Trim();
            string original = rec.Get(field);

            Dictionary<string, string> row;
            if (!edits.TryGetValue(rec.Id, out row)) row = new Dictionary<string, string>();
            if (value == original) row.Remove(field);
            else if (value.Length == 0)
            {
                C<TextBlock>("tb_status").Text = "A sheet " + field + " cannot be empty - left unchanged.";
                row.Remove(field);
            }
            else row[field] = value;

            if (row.Count > 0) edits[rec.Id] = row; else edits.Remove(rec.Id);
            Log.Write("edit: " + rec.Number + " " + field + " staged '" + value + "' (" + edits.Count + " sheet(s) staged)");
            RebuildRows();
        }

        private void RefreshApplyButton()
        {
            int pending = edits.Count;
            var button = C<Button>("btn_apply_edits");
            button.IsEnabled = pending > 0;
            button.Content = pending > 0 ? "Apply Edits (" + pending + ")" : "Apply Edits";
            // green signals staged, unwritten changes
            var style = Win.TryFindResource(pending > 0 ? "GreenButton" : "OrangeButton") as Style;
            if (style != null) button.Style = style;
        }

        private void RevertClick()
        {
            if (edits.Count == 0)
            {
                C<TextBlock>("tb_status").Text = "No staged edits to revert.";
                return;
            }
            int count = edits.Count;
            edits.Clear();
            RebuildRows();
            C<TextBlock>("tb_status").Text = "Reverted staged edits on " + count + " sheet(s).";
            Log.Write("revert: " + count + " sheet(s)");
        }

        private void ApplyEditsClick()
        {
            if (edits.Count == 0) return;
            HashSet<string> dupes = DuplicateNumbers();
            int clashing = edits.Count(p => p.Value.ContainsKey("number") && dupes.Contains(p.Value["number"].Trim().ToLowerInvariant()));
            if (clashing > 0)
            {
                C<TextBlock>("tb_status").Text = clashing + " staged sheet number(s) are already in use - fix the red rows first.";
                Log.Write("apply: refused, " + clashing + " staged number(s) clash");
                return;
            }

            int written = 0;
            var failed = new List<string>();
            using (var t = new Transaction(doc, "Sheet Name Push - Apply Edits"))
            {
                t.Start();
                try
                {
                    foreach (KeyValuePair<long, Dictionary<string, string>> pair in edits.ToList())
                    {
                        SnpRecord rec;
                        if (!byId.TryGetValue(pair.Key, out rec)) continue;
                        foreach (KeyValuePair<string, string> field in pair.Value)
                        {
                            try
                            {
                                if (SnpCore.WriteField(rec.Sheet, field.Key, field.Value))
                                {
                                    rec.Set(field.Key, field.Value);
                                    written++;
                                }
                                else failed.Add(rec.Number + " (" + field.Key + ")");
                            }
                            catch (Exception ex)
                            {
                                failed.Add(rec.Number + " (" + field.Key + "): " + ex.Message);
                            }
                        }
                    }
                    t.Commit();
                }
                catch (Exception err)
                {
                    try { if (t.HasStarted()) t.RollBack(); } catch (Exception) { }
                    Log.Write("error: apply edits rolled back: " + err.Message);
                    C<TextBlock>("tb_status").Text = "The edits could not be written and were rolled back: " + err.Message;
                    return;
                }
            }
            edits.Clear();
            RebuildRows();
            C<TextBlock>("tb_status").Text = failed.Count == 0
                ? "Applied " + written + " edit(s)."
                : "Applied " + written + ", " + failed.Count + " refused: " + string.Join("; ", failed.Take(3));
            Log.Write("apply: " + written + " written, " + failed.Count + " refused" + (failed.Count > 0 ? " [" + string.Join("; ", failed) + "]" : ""));
        }

        // ---------------------------------------------------------------- tools --

        /// <summary>Ticked sheets, or everything currently shown if none ticked.</summary>
        private List<SnpTarget> ToolTargets()
        {
            List<SnpRecord> tickedRecs = records.Where(r => ticked.Contains(r.Id)).ToList();
            List<SnpRecord> recs = tickedRecs.Count > 0 ? tickedRecs : VisibleRecords();
            return recs.Select(r => new SnpTarget { Id = r.Id, Number = Current(r, "number"), Name = Current(r, "name") }).ToList();
        }

        private void Stage(Dictionary<long, Dictionary<string, string>> changes)
        {
            foreach (KeyValuePair<long, Dictionary<string, string>> pair in changes)
            {
                SnpRecord rec;
                if (!byId.TryGetValue(pair.Key, out rec)) continue;
                Dictionary<string, string> staged;
                if (!edits.TryGetValue(pair.Key, out staged)) staged = new Dictionary<string, string>();
                foreach (KeyValuePair<string, string> field in pair.Value)
                {
                    if (field.Value == rec.Get(field.Key)) staged.Remove(field.Key);
                    else staged[field.Key] = field.Value;
                }
                if (staged.Count > 0) edits[pair.Key] = staged; else edits.Remove(pair.Key);
            }
            RebuildRows();
        }

        private void FindReplaceClick()
        {
            List<SnpTarget> targets = ToolTargets();
            if (targets.Count == 0)
            {
                C<TextBlock>("tb_status").Text = "Nothing to work on.";
                return;
            }
            var window = new SnpFindReplaceWindow(targets, Log);
            if (window.ShowModal(Win, uiapp) && window.Changes.Count > 0)
            {
                Stage(window.Changes);
                C<TextBlock>("tb_status").Text = "Staged find/replace on " + window.Changes.Count + " sheet(s) - press Apply Edits.";
                Log.Write("find/replace: staged on " + window.Changes.Count + " sheet(s)");
            }
        }

        private void AffixClick()
        {
            List<SnpTarget> targets = ToolTargets();
            if (targets.Count == 0)
            {
                C<TextBlock>("tb_status").Text = "Nothing to work on.";
                return;
            }
            var window = new SnpAffixWindow(targets, Log);
            if (window.ShowModal(Win, uiapp) && window.Changes.Count > 0)
            {
                Stage(window.Changes);
                C<TextBlock>("tb_status").Text = "Staged prefix/suffix on " + window.Changes.Count + " sheet(s) - press Apply Edits.";
                Log.Write("prefix/suffix: staged on " + window.Changes.Count + " sheet(s)");
            }
        }

        private void SettingsClick()
        {
            var window = new SnpSettingsWindow(Cfg, doc, Log);
            if (window.ShowModal(Win, uiapp) && window.Saved)
            {
                Cfg = window.Settings;
                C<TextBlock>("tb_status").Text = "Target parameters: " + Cfg["param_1"] + ", " + Cfg["param_2"] + ", " + Cfg["param_3"];
            }
        }

        private string ReadFormat()
        {
            if (C<RadioButton>("rb_title").IsChecked == true) return "title";
            if (C<RadioButton>("rb_none").IsChecked == true) return "none";
            return "upper";
        }

        /// <summary>Remembers the chosen format straight away, for the next run.</summary>
        private void FormatChanged()
        {
            FormatMode = ReadFormat();
            Cfg["format_mode"] = FormatMode;
            Cfg["settings_version"] = SnpCore.SettingsVersion;
            SnpCore.SaveSettings(Cfg);
            string label;
            C<TextBlock>("tb_status").Text = "Text format set to " + (SnpCore.ModeLabels.TryGetValue(FormatMode, out label) ? label : FormatMode) + " - remembered for next time.";
            Log.Write("format: " + FormatMode);
        }

        // ---------------------------------------------------------------- push --

        private void PushClick()
        {
            if (edits.Count > 0)
            {
                C<TextBlock>("tb_status").Text = "There are " + edits.Count + " staged edit(s) - apply or revert them before pushing.";
                return;
            }
            FormatMode = ReadFormat();
            Cfg["format_mode"] = FormatMode;
            SnpCore.SaveSettings(Cfg);
            ResultSheets = records.Where(r => ticked.Contains(r.Id)).Select(r => r.Sheet).ToList();
            if (ResultSheets.Count == 0)
            {
                C<TextBlock>("tb_status").Text = "Tick at least one sheet before pushing.";
                return;
            }
            Pushed = true;
            Log.Write("push: " + ResultSheets.Count + " sheet(s) ticked, format " + FormatMode);
            Win.DialogResult = true;
            Win.Close();
        }
    }
}
