using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Threading;
using RevoBIM.Helpers;
using RevoBIM.Tools.AddinManager;

using Border = System.Windows.Controls.Border;
using Button = System.Windows.Controls.Button;
using Image = System.Windows.Controls.Image;
using Path = System.Windows.Shapes.Path;
using TextBox = System.Windows.Controls.TextBox;
using ToolTip = System.Windows.Controls.ToolTip;

namespace RevoBIM.UI.AddinManager
{
    /// <summary>
    /// The panel itself: one control, two hosts. Docked, it sits in the pane Revit was given at start up and Revit
    /// owns the frame. Floating, it is the whole of a borderless window (AmWindow). Rows are built in code.
    /// Port of rba_pane.py.
    /// </summary>
    internal sealed class AmPane
    {
        private const int SearchDebounceMs = 220;
        private const int ThemeRecheckMs = 2500;
        private const string ChevronClosed = "M 0,0 L 5,4.5 L 0,9 Z";
        private const string ChevronOpen = "M 0,1 L 9,1 L 4.5,7 Z";

        public readonly string Mode;                  // "pane" when Revit docks it, "window" when floating
        public readonly UserControl Control;
        public Window HostWindow;
        public Dictionary<string, string> Settings;
        public string ThemeName = "dark";
        public readonly List<Action<string>> ThemeListeners = new List<Action<string>>();
        public List<AmItem> Items = new List<AmItem>();
        public bool FirstReadDone;

        private readonly Dictionary<string, bool> collapsed = new Dictionary<string, bool>();
        private List<AmGroup> groups = new List<AmGroup>();
        private List<string> drawnKeys = new List<string>();
        private long settingsStamp;
        private string lastSignature = "";
        private bool eggArmed;

        private TextBox searchBox;
        private StackPanel listPanel;
        private TextBlock statusText;
        private Button themeBtn, foldBtn, favBtn, labelsBtn, footerBtn;
        private FrameworkElement searchRow, footer;
        private WrapPanel favPanel;
        private AmFavs favs;
        private DispatcherTimer searchTimer, watchTimer, themeTimer;

        public AmPane(string mode)
        {
            Mode = mode;
            Settings = AmCore.LoadSettings();
            AmCore.SetDebug(AmCore.AsBool(Settings, "debug"));
            AmCore.SaveSettings(Settings);
            foreach (string key in AmCore.AsList(Settings, "collapsed")) collapsed[key] = true;
            settingsStamp = AmCore.SettingsStamp();
            Control = AmXaml.Load<UserControl>("RevoBIMAddins.xaml", AmTheme.Resolve(AmCore.Get(Settings, "theme")));
            ThemeName = AmTheme.Resolve(AmCore.Get(Settings, "theme"));
            Wire();
            ApplyTheme();
            SetStatus("Reading the ribbon...");
        }

        // ------------------------------------------------------------------ wiring

        public T Find<T>(string name) where T : class { return Control.FindName(name) as T; }

        private void Wire()
        {
            searchBox = Find<TextBox>("SearchBox");
            listPanel = Find<StackPanel>("ListPanel");
            statusText = Find<TextBlock>("StatusText");
            themeBtn = Find<Button>("ThemeBtn");
            foldBtn = Find<Button>("FoldBtn");
            favBtn = Find<Button>("FavBtn");
            labelsBtn = Find<Button>("LabelsBtn");
            footerBtn = Find<Button>("FooterBtn");
            searchRow = Find<FrameworkElement>("SearchRow");
            footer = Find<FrameworkElement>("Footer");
            favPanel = Find<WrapPanel>("FavPanel");

            Find<TextBlock>("VersionText").Text = "v" + AmCore.Version;
            searchBox.TextChanged += (s, a) => { searchTimer.Stop(); searchTimer.Start(); };
            themeBtn.Click += (s, a) => OnThemeClick();
            Find<Button>("SettingsBtn").Click += (s, a) => OnSettingsClick();
            foldBtn.Click += (s, a) => OnFold();
            favBtn.Click += (s, a) => OnFavView();
            labelsBtn.Click += (s, a) => favs.ToggleLabels();
            Find<Button>("SmallerBtn").Click += (s, a) => StepIcon(-1);
            Find<Button>("BiggerBtn").Click += (s, a) => StepIcon(1);
            Find<Button>("RefreshBtn").Click += (s, a) => Rescan();
            footerBtn.Click += (s, a) => OnFooterClick();
            favs = new AmFavs(this, favPanel);
            ApplyFooter();

            Control.KeyDown += OnKey;
            Control.Loaded += (s, a) => OnLoaded();
            Control.IsVisibleChanged += (s, a) =>
            {
                try
                {
                    // docked only: a floating window has just read the ribbon as it opened
                    if (Mode == "pane" && FirstReadDone && (bool)a.NewValue) Rescan();
                }
                catch (Exception err) { AmCore.LogException("visible", err); }
            };

            searchTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(SearchDebounceMs) };
            searchTimer.Tick += (s, a) => { searchTimer.Stop(); Render(); };

            watchTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(Math.Max(400, AmCore.AsInt(Settings, "watch_ms", 1500))) };
            watchTimer.Tick += (s, a) => OnWatchTick();
            watchTimer.Start();

            themeTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(ThemeRecheckMs) };
            themeTimer.Tick += (s, a) => OnThemeTick();
            themeTimer.Start();
        }

        /// <summary>Arms the logo easter egg once there is a window to hang it on (a docked pane has none until it is shown).</summary>
        private void ArmEgg()
        {
            if (eggArmed) return;
            try
            {
                Window window = HostWindow ?? Window.GetWindow(Control);
                if (window == null) return;
                eggArmed = EggHook.Attach(window, () => ThemeName, Find<UIElement>("LogoBlock"));
            }
            catch (Exception err)
            {
                AmCore.LogException("egg", err);
            }
        }

        private void OnLoaded()
        {
            ArmEgg();
            if (FirstReadDone) return;
            FirstReadDone = true;
            Rescan();
        }

        public void Stop()
        {
            foreach (DispatcherTimer timer in new[] { watchTimer, themeTimer, searchTimer })
            {
                try { timer.Stop(); } catch (Exception) { }
            }
        }

        // ------------------------------------------------------------------ settings, theme

        public void SaveSettings()
        {
            AmCore.SaveSettings(Settings);
            settingsStamp = AmCore.SettingsStamp();
        }

        public object Res(string key)
        {
            try { return Control.TryFindResource(key); } catch (Exception) { return null; }
        }

        private Brush Brush(string key) { return Res(key) as Brush; }

        public void ApplyTheme()
        {
            string mode = AmCore.Get(Settings, "theme");
            ThemeName = AmTheme.Resolve(mode);
            AmTheme.Apply(Control, ThemeName);
            try
            {
                foreach (var pair in new[] { Tuple.Create("ThemeAutoGlyph", "auto"), Tuple.Create("ThemeDarkGlyph", "dark"), Tuple.Create("ThemeLightGlyph", "light") })
                    Find<UIElement>(pair.Item1).Visibility = mode == pair.Item2 ? Visibility.Visible : Visibility.Collapsed;
                themeBtn.ToolTip = mode == "dark" ? "Theme: Dark. Click for Light."
                                 : mode == "light" ? "Theme: Light. Click for Auto."
                                 : "Theme: Auto - follows Revit's canvas. Click for Dark.";
            }
            catch (Exception err) { AmCore.LogException("theme glyph", err); }
            foreach (Action<string> listener in ThemeListeners.ToList())
            {
                try { listener(ThemeName); } catch (Exception err) { AmCore.LogException("theme listener", err); }
            }
        }

        private void OnThemeClick()
        {
            try
            {
                Settings["theme"] = AmTheme.NextMode(AmCore.Get(Settings, "theme"));
                SaveSettings();
                ApplyTheme();
                Render();
            }
            catch (Exception err) { AmCore.LogException("on_theme_click", err); }
        }

        private void OnThemeTick()
        {
            try
            {
                if (AmCore.Get(Settings, "theme").ToLowerInvariant() != "auto") return;
                string wanted = AmTheme.Resolve("auto");
                if (wanted != ThemeName)
                {
                    AmCore.Log("theme: Revit moved to " + wanted);
                    ApplyTheme();
                    Render();
                }
            }
            catch (Exception err) { AmCore.LogException("on_theme_tick", err); }
        }

        public void ReloadSettings(bool fromDisk)
        {
            if (fromDisk) Settings = AmCore.LoadSettings();
            ApplyFooter();
            AmCore.SetDebug(AmCore.AsBool(Settings, "debug"));
            watchTimer.Interval = TimeSpan.FromMilliseconds(Math.Max(400, AmCore.AsInt(Settings, "watch_ms", 1500)));
            ApplyTheme();
            Rescan();
        }

        // ------------------------------------------------------------------ reading the ribbon

        public void Rescan()
        {
            try
            {
                Items = ScanNow();
                lastSignature = Signature(Items);
                ApplyQat();
                Render();
            }
            catch (Exception err)
            {
                AmCore.LogException("rescan", err);
                SetStatus("Could not read the ribbon - see the debug log");
            }
        }

        private List<AmItem> ScanNow()
        {
            List<AmItem> all = AmRibbon.Scan(AmCore.AsBool(Settings, "include_builtin"), AmCore.Get(Settings, "name_filter"));
            // a switched-off tab is not dropped: its buttons stay available to favourites, pins and search
            var hidden = new HashSet<string>(AmCore.AsList(Settings, "hidden_tabs"));
            foreach (AmItem item in all) item.Hidden = hidden.Contains(AmCore.Normalise(item.Tab).Replace("|", "/"));
            return all;
        }

        /// <summary>Every tab that has addin buttons, for the Settings tick list (hidden ones included).</summary>
        private List<string> AllTabs()
        {
            List<AmItem> all = AmRibbon.Scan(true, "");
            return all.Select(i => i.Tab).Distinct().ToList();
        }

        private static string Signature(List<AmItem> items)
        {
            return string.Join("\n", items.Select(i => i.CommandId + "|" + i.Title));
        }

        private void ApplyQat()
        {
            List<string> keys = AmCore.AsList(Settings, "qat");
            if (keys.Count == 0) return;
            try { AmRibbon.QatReapply(Items, keys); }
            catch (Exception err) { AmCore.LogException("apply_qat", err); }
        }

        private void OnWatchTick()
        {
            try
            {
                long stamp = AmCore.SettingsStamp();
                if (stamp != settingsStamp)
                {
                    settingsStamp = stamp;
                    AmCore.Log("watch: settings changed on disk, reloading");
                    ReloadSettings(true);
                    return;
                }
                if (!FirstReadDone || !AmCore.AsBool(Settings, "watch") || !Control.IsVisible) return;
                if (HostWindow != null && !HostWindow.IsVisible) return;
                List<AmItem> now = ScanNow();
                string signature = Signature(now);
                if (signature == lastSignature) return;
                AmCore.Log("watch: the ribbon changed, re-reading");
                lastSignature = signature;
                Items = now;
                ApplyQat();
                Render();
            }
            catch (Exception err) { AmCore.LogException("watch", err); }
        }

        // ------------------------------------------------------------------ pins

        public List<string> PinnedKeys() { return AmCore.AsList(Settings, "pinned"); }

        public void TogglePin(AmItem item)
        {
            List<string> keys = PinnedKeys();
            string note;
            if (keys.Contains(item.Key))
            {
                keys.RemoveAll(k => k == item.Key);
                note = item.Title + " unpinned";
            }
            else
            {
                keys.Add(item.Key);
                note = item.Title + " pinned to the top";
            }
            AmCore.SetList(Settings, "pinned", keys);
            SaveSettings();
            Render();
            SetStatus(note);
        }

        /// <summary>In the order they were pinned: a pinned list is arranged by hand.</summary>
        private List<AmItem> PinnedItems()
        {
            var byKey = new Dictionary<string, AmItem>();
            foreach (AmItem item in Items) byKey[item.Key] = item;
            var list = new List<AmItem>();
            foreach (string key in PinnedKeys())
            {
                AmItem found;
                if (byKey.TryGetValue(key, out found)) list.Add(found);
            }
            return list;
        }

        // ------------------------------------------------------------------ rendering

        public int IconSize()
        {
            int size = AmCore.AsInt(Settings, "icon_size", 32);
            return Array.IndexOf(AmCore.IconSizes, size) < 0 ? 32 : size;
        }

        public bool InFavourites() { return AmCore.Get(Settings, "view") == "favourites"; }

        public void Render()
        {
            ApplyView();
            if (InFavourites())
            {
                try
                {
                    int count = favs.Render();
                    SetStatus(count > 0 ? count + " favourite" + (count == 1 ? "" : "s") + " - drag to reorder" : "No favourites yet");
                }
                catch (Exception err) { AmCore.LogException("render favourites", err); }
                return;
            }
            try
            {
                listPanel.Children.Clear();
                string search = searchBox.Text ?? "";
                bool searching = search.Trim().Length > 0;
                List<AmItem> primary, secondary;
                AmRibbon.SearchSplit(searching ? Items : Items.Where(i => !i.Hidden).ToList(), search, out primary, out secondary);
                groups = AmRibbon.GroupItems(primary, AmCore.Get(Settings, "group_by"));
                int shown = 0;
                drawnKeys = new List<string>();

                List<AmItem> pinned = searching ? new List<AmItem>() : PinnedItems();
                if (pinned.Count > 0)
                {
                    var group = new AmGroup("__pinned__", "Pinned", "") { Items = pinned };
                    drawnKeys.Add(group.Key);
                    bool closed = collapsed.ContainsKey(group.Key) && collapsed[group.Key];
                    listPanel.Children.Add(BuildGroupHeader(group, closed, true));
                    if (!closed) foreach (AmItem item in pinned) listPanel.Children.Add(BuildRow(item, false));
                }
                foreach (AmGroup group in groups)
                {
                    drawnKeys.Add(group.Key);
                    bool closed = !searching && collapsed.ContainsKey(group.Key) && collapsed[group.Key];
                    listPanel.Children.Add(BuildGroupHeader(group, closed, false));
                    if (closed) continue;
                    foreach (AmItem item in group.Items)
                    {
                        listPanel.Children.Add(BuildRow(item, false));
                        shown++;
                    }
                }
                if (secondary.Count > 0)
                {
                    listPanel.Children.Add(BuildSectionHeader("Matches what they do", secondary.Count));
                    foreach (AmItem item in secondary)
                    {
                        listPanel.Children.Add(BuildRow(item, true));
                        shown++;
                    }
                }
                if (groups.Count == 0 && secondary.Count == 0) listPanel.Children.Add(BuildEmptyNote(searching));
                Report(shown, secondary.Count);
                UpdateFoldButton();
            }
            catch (Exception err)
            {
                AmCore.LogException("render", err);
            }
        }

        private void Report(int shown, int byDescription)
        {
            int total = Items.Count(i => !i.Hidden);
            var parts = new List<string>();
            if (shown != total)
            {
                parts.Add(shown + " of " + total + " addin buttons");
                if (byDescription > 0) parts.Add(byDescription + " by description");
            }
            else
            {
                parts.Add(total + " addin buttons in " + groups.Count + " groups");
            }
            SetStatus(string.Join("  -  ", parts));
        }

        public void SetStatus(string text)
        {
            try { statusText.Text = text ?? ""; } catch (Exception) { }
        }

        private FrameworkElement BuildSectionHeader(string text, int count)
        {
            var border = new Border
            {
                Background = Brush("BgWindow"),
                Padding = new Thickness(1, 6, 1, 4),
                Margin = new Thickness(0, 10, 0, 2),
                BorderBrush = Brush("BrdEdge"),
                BorderThickness = new Thickness(0, 1, 0, 0),
            };
            var stack = new StackPanel { Orientation = Orientation.Horizontal };
            stack.Children.Add(new Border
            {
                Width = 4,
                Height = 13,
                CornerRadius = new CornerRadius(2),
                Background = Brush("AccOrange"),
                Margin = new Thickness(0, 0, 7, 0),
                VerticalAlignment = VerticalAlignment.Center,
            });
            stack.Children.Add(new TextBlock
            {
                Text = text + "  (" + count + ")",
                Foreground = Brush("FgMuted"),
                FontFamily = new FontFamily("Segoe UI"),
                FontSize = 11.5,
                VerticalAlignment = VerticalAlignment.Center,
            });
            border.Child = stack;
            return border;
        }

        private FrameworkElement BuildEmptyNote(bool searching)
        {
            return new TextBlock
            {
                Text = searching ? "Nothing matches that." : "No addin buttons found on the ribbon. Open Settings to include buttons on Revit's own tabs.",
                TextWrapping = TextWrapping.Wrap,
                Foreground = Brush("FgMuted"),
                FontFamily = new FontFamily("Segoe UI"),
                FontSize = 12,
                Margin = new Thickness(6, 14, 6, 6),
            };
        }

        private FrameworkElement BuildGroupHeader(AmGroup group, bool closed, bool accent)
        {
            var border = new Border
            {
                Background = Brush("BgCard"),
                CornerRadius = new CornerRadius(3),
                Padding = new Thickness(7, 5, 7, 5),
                Margin = new Thickness(0, 7, 0, 2),
                Cursor = Cursors.Hand,
            };
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(14) });
            grid.ColumnDefinitions.Add(new ColumnDefinition());
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            var chevron = new Path
            {
                Data = Geometry.Parse(closed ? ChevronClosed : ChevronOpen),
                Fill = Brush(closed ? "AccOrange" : "FgMuted"),
                VerticalAlignment = VerticalAlignment.Center,
                HorizontalAlignment = HorizontalAlignment.Left,
            };
            Grid.SetColumn(chevron, 0);
            grid.Children.Add(chevron);

            var title = new TextBlock
            {
                Text = group.Title,
                Foreground = Brush(accent ? "AccOrange" : "FgText"),
                FontFamily = new FontFamily("Segoe UI"),
                FontSize = 12.5,
                FontWeight = FontWeights.SemiBold,
                TextTrimming = TextTrimming.CharacterEllipsis,
                VerticalAlignment = VerticalAlignment.Center,
            };
            Grid.SetColumn(title, 1);
            grid.Children.Add(title);

            var count = new TextBlock
            {
                Text = group.Items.Count.ToString(),
                Foreground = Brush("FgMuted"),
                FontFamily = new FontFamily("Segoe UI"),
                FontSize = 11,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(6, 0, 0, 0),
            };
            Grid.SetColumn(count, 2);
            grid.Children.Add(count);

            border.Child = grid;
            if (!string.IsNullOrEmpty(group.Subtitle)) border.ToolTip = new ToolTip { Content = group.Subtitle };
            string key = group.Key;
            border.MouseLeftButtonUp += (s, a) => ToggleGroup(key);
            return border;
        }

        private void ToggleGroup(string key)
        {
            collapsed[key] = !(collapsed.ContainsKey(key) && collapsed[key]);
            AmCore.SetList(Settings, "collapsed", collapsed.Where(p => p.Value).Select(p => p.Key));
            SaveSettings();
            Render();
        }

        private FrameworkElement BuildRow(AmItem item, bool detail)
        {
            int size = IconSize();
            var border = new Border
            {
                Background = Brush("BgWindow"),
                CornerRadius = new CornerRadius(3),
                Padding = new Thickness(7, 4, 7, 4),
                Margin = new Thickness(2, 1, 0, 1),
                Cursor = Cursors.Hand,
            };
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(size + 8) });
            grid.ColumnDefinitions.Add(new ColumnDefinition());

            FrameworkElement visual = IconFor(item, size);
            visual.HorizontalAlignment = HorizontalAlignment.Left;
            visual.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(visual, 0);
            grid.Children.Add(visual);

            var stack = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
            Grid.SetColumn(stack, 1);
            stack.Children.Add(new TextBlock
            {
                Text = item.Title,
                Foreground = Brush("FgText"),
                FontFamily = new FontFamily("Segoe UI"),
                FontSize = 12.5,
                TextTrimming = TextTrimming.CharacterEllipsis,
            });

            string snippet = "";
            if (detail)
            {
                snippet = item.Description.Length > 0 ? item.Description : item.Tooltip;
                if (snippet.Length > 90) snippet = snippet.Substring(0, 88) + "..";
            }
            string subText = snippet.Length > 0 ? snippet : item.Parent;
            if (subText.Length > 0)
            {
                stack.Children.Add(new TextBlock
                {
                    Text = subText,
                    Foreground = Brush("FgMuted"),
                    FontFamily = new FontFamily("Segoe UI"),
                    FontSize = 10.5,
                    TextTrimming = TextTrimming.CharacterEllipsis,
                });
            }
            grid.Children.Add(stack);
            border.Child = grid;

            if (AmCore.AsBool(Settings, "show_tooltips"))
            {
                var lines = new List<string>();
                if (item.Tooltip.Length > 0) lines.Add(item.Tooltip);
                lines.Add(item.Tab + " > " + item.Panel);
                if (AmCore.AsBool(Settings, "show_paths")) lines.Add(item.CommandId);
                border.ToolTip = new ToolTip { Content = string.Join("\n", lines) };
            }

            Brush hover = Brush("BgHover");
            Brush rest = Brush("BgWindow");
            border.MouseEnter += (s, a) => ((Border)s).Background = hover;
            border.MouseLeave += (s, a) => ((Border)s).Background = rest;
            border.MouseLeftButtonUp += (s, a) => Launch(item);
            border.MouseRightButtonUp += (s, a) => ShowMenu(border, item, a);
            return border;
        }

        public FrameworkElement IconFor(AmItem item, int size)
        {
            if (item.Icon != null)
            {
                return new Image { Source = item.Icon, Width = size, Height = size, Stretch = Stretch.Uniform };
            }
            return AmUi.InitialGlyph(item.Title, size, Brush("BgCard"), Brush("FgMuted"));
        }

        public void ShowMenu(FrameworkElement target, AmItem item, RoutedEventArgs args)
        {
            try
            {
                ContextMenu menu = AmMenu.Build(this, item);
                menu.PlacementTarget = target;
                menu.IsOpen = true;
                args.Handled = true;
            }
            catch (Exception err)
            {
                AmCore.LogException("row/context", err);
                SetStatus("The menu would not open - see the debug log");
            }
        }

        // ------------------------------------------------------------------ actions

        public void Launch(AmItem item)
        {
            string message;
            if (AmRibbon.Launch(item, out message)) SetStatus("Ran " + item.Title);
            else
            {
                // tools finish silently: a refusal goes to the footer and the debug log, never a dialog
                SetStatus(message);
                AmCore.Log("launch refused: " + message);
            }
        }

        public bool IsFavourite(AmItem item) { return favs.IsFavourite(item); }
        public void ToggleFavourite(AmItem item) { favs.Toggle(item); }

        private void ApplyView()
        {
            bool favourites = InFavourites();
            try
            {
                Visibility shown = Visibility.Visible, hidden = Visibility.Collapsed;
                searchRow.Visibility = favourites ? hidden : shown;
                listPanel.Visibility = favourites ? hidden : shown;
                favPanel.Visibility = favourites ? shown : hidden;
                foldBtn.Visibility = favourites ? hidden : shown;
                labelsBtn.Visibility = favourites ? shown : hidden;
                favBtn.Tag = favourites ? "on" : null;
                favBtn.ToolTip = favourites ? "Back to every addin" : "Favourites";
                bool labels = favs.LabelsShown();
                labelsBtn.Tag = labels ? "on" : null;
                labelsBtn.ToolTip = labels ? "Hide the names under favourites" : "Show the names under favourites";
            }
            catch (Exception err) { AmCore.LogException("apply_view", err); }
        }

        private void OnFavView()
        {
            Settings["view"] = InFavourites() ? "all" : "favourites";
            SaveSettings();
            Render();
        }

        private bool AnyOpen()
        {
            return drawnKeys.Any(k => !(collapsed.ContainsKey(k) && collapsed[k]));
        }

        private void UpdateFoldButton()
        {
            try
            {
                bool closing = AnyOpen();
                Find<UIElement>("FoldCloseGlyph").Visibility = closing ? Visibility.Visible : Visibility.Collapsed;
                Find<UIElement>("FoldOpenGlyph").Visibility = closing ? Visibility.Collapsed : Visibility.Visible;
                foldBtn.ToolTip = closing ? "Collapse every group" : "Expand every group";
            }
            catch (Exception err) { AmCore.LogException("fold button", err); }
        }

        private void OnFold()
        {
            if (AnyOpen()) foreach (string key in drawnKeys) collapsed[key] = true;
            else collapsed.Clear();
            AmCore.SetList(Settings, "collapsed", collapsed.Where(p => p.Value).Select(p => p.Key));
            SaveSettings();
            Render();
        }

        private void StepIcon(int direction)
        {
            int at = Array.IndexOf(AmCore.IconSizes, IconSize()) + direction;
            at = Math.Max(0, Math.Min(AmCore.IconSizes.Length - 1, at));
            Settings["icon_size"] = AmCore.IconSizes[at].ToString();
            SaveSettings();
            Render();
        }

        public void ApplyFooter()
        {
            bool shown = AmCore.AsBool(Settings, "show_footer");
            try
            {
                footer.Visibility = shown ? Visibility.Visible : Visibility.Collapsed;
                footerBtn.Tag = shown ? "on" : null;
                footerBtn.ToolTip = shown ? "Hide the status footer" : "Show the status footer";
            }
            catch (Exception err) { AmCore.LogException("apply_footer", err); }
        }

        private void OnFooterClick()
        {
            Settings["show_footer"] = AmCore.AsBool(Settings, "show_footer") ? "0" : "1";
            SaveSettings();
            ApplyFooter();
        }

        private void OnKey(object sender, KeyEventArgs args)
        {
            try
            {
                if (args.Key == Key.F5)
                {
                    Rescan();
                    args.Handled = true;
                }
                else if (args.Key == Key.Escape && !InFavourites())
                {
                    searchBox.Text = "";
                }
            }
            catch (Exception) { }
        }

        private void OnSettingsClick()
        {
            try
            {
                Dictionary<string, string> changed = AmSettingsWindow.Show(Settings, ThemeName, HostWindow ?? Window.GetWindow(Control), AllTabs());
                if (changed != null)
                {
                    Settings = changed;
                    SaveSettings();
                    ReloadSettings(false);
                }
            }
            catch (Exception err)
            {
                AmCore.LogException("on_settings_click", err);
                SetStatus("Settings would not open - see the debug log");
            }
        }
    }
}
