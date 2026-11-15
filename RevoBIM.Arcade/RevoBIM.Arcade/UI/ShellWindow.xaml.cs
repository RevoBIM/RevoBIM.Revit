using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using RevoBIM.Arcade.Core;
using RevoBIM.Arcade.Services;

namespace RevoBIM.Arcade.UI
{
    public partial class ShellWindow : Window
    {
        sealed class PickerItem
        {
            public string Key { get; set; } = "";
            public string DisplayName { get; set; } = "";
            public string BestText { get; set; } = "";
            public bool IsDefault { get; set; }
            public UIElement? Icon { get; set; }
            public string DefaultGlyph => IsDefault ? "\uE735" : "\uE734";

            public string DefaultTip => IsDefault
                ? "This game opens first. Click to clear it."
                : "Open this game first whenever the arcade starts.";
        }

        readonly LaunchOptions _options;
        readonly DrawerController _drawer;
        readonly SlowClickCounter _egg = new SlowClickCounter();

        IArcadeGame? _game;
        GameHost? _host;
        GameRegistry.Entry? _entry;

        public ShellWindow(LaunchOptions options)
        {
            _options = options;
            InitializeComponent();

            LoadLogo();

            _drawer = new DrawerController(this, HeaderBar, RootBorder, ShrinkButton, ShrinkGlyph, ExpandGlyph, Body, Footer);

            SourceInitialized += (s, e) => ScreenHelper.Place(this, _options.Owner);
            Loaded += OnLoaded;
            Closed += (s, e) => StopGame();
            Deactivated += (s, e) => _host?.Input.Reset();

            PreviewKeyDown += OnPreviewKeyDown;
            PreviewKeyUp += (s, e) => _host?.Input.KeyUp(e.Key == Key.System ? e.SystemKey : e.Key);

            HeaderBar.MouseLeftButtonDown += OnHeaderDown;
            LogoHit.PreviewMouseLeftButtonDown += OnLogoClick;
            CloseButton.Click += (s, e) => Close();
        }

        // ------------------------------------------------------------ start up

        void OnLoaded(object sender, RoutedEventArgs e)
        {
            // A game named on the command line wins; with none named, the saved default; else the picker.
            var (entry, note) = GameRegistry.ResolveStart(_options.GameKey, SettingsStore.Load().DefaultGame);
            if (entry != null) { OpenGame(entry); return; }
            ShowPicker(note);
        }

        /// <summary>A second launch handed us a request. Bring the window forward and act on it.</summary>
        public void HandleExternalRequest(string gameKey)
        {
            if (WindowState == WindowState.Minimized) WindowState = WindowState.Normal;
            if (_drawer.Shrunk) _drawer.Expand();
            Activate();
            Topmost = true; Topmost = false;   // the reliable way to come to the front

            if (string.IsNullOrEmpty(gameKey)) return;
            var entry = GameRegistry.Find(gameKey);
            if (entry != null) OpenGame(entry);
            else ShowPicker($"There is no game called '{gameKey}'. Pick one below.");
        }

        // ------------------------------------------------------------ games

        void OpenGame(GameRegistry.Entry entry)
        {
            StopGame();
            _entry = entry;
            try
            {
                var game = entry.Create();
                var host = new GameHost(entry.Key, ThemeService.Current, Board);
                host.SetBoardSize(640, 400);
                host.StatusChanged += text => StatusText.Text = text;

                _game = game; _host = host;
                StatusText.Text = "";
                HintText.Text = game.Hints;
                SetTitle("RevoBIM Arcade  -  " + game.DisplayName);
                PickerView.Visibility = Visibility.Collapsed;
                GameView.Visibility = Visibility.Visible;
                RestoreGameSize();

                game.Start(host);
                host.Loop.Start();

                var settings = SettingsStore.Load();
                settings.LastGame = entry.Key;
                SettingsStore.Save(settings);
            }
            catch (Exception ex)
            {
                StopGame();
                ShowPicker($"{entry.DisplayName} could not start: {ex.Message}");
            }
        }

        /// <summary>The header text and the taskbar title move together.</summary>
        void SetTitle(string text)
        {
            TitleText.Text = text;
            Title = text;
        }

        void StopGame()
        {
            var game = _game; var host = _host;
            _game = null; _host = null;
            if (game != null) { try { game.Stop(); } catch { /* a game must not stop the shell closing */ } }
            host?.Shutdown();
        }

        void ShowPicker(string note = "")
        {
            StopGame();
            _entry = null;
            SetTitle("RevoBIM Arcade");
            HintText.Text = "Click a game   Esc close";
            StatusText.Text = "";
            PickerNote.Text = note;
            PickerNote.Visibility = string.IsNullOrEmpty(note) ? Visibility.Collapsed : Visibility.Visible;

            FillPicker();

            GameView.Visibility = Visibility.Collapsed;
            PickerView.Visibility = Visibility.Visible;
            FitToPicker();
        }

        static UIElement? IconOf(GameRegistry.Entry entry)
        {
            try { return entry.Create().CreateIcon(); }
            catch { return null; }
        }

        // ---- window size: the picker crops to its cards, a game gets the size it last had

        Size _gameSize = new Size(760, 560);
        bool _fitted;

        /// <summary>Sizes the window to the picker's contents, keeping its centre where it was.</summary>
        void FitToPicker()
        {
            if (_drawer.Shrunk || WindowState != WindowState.Normal) return;
            PickerView.UpdateLayout();
            PickerPanel.Measure(new Size(PickerPanel.Width, double.PositiveInfinity));
            var work = ScreenHelper.WorkAreaOf(this);
            double chrome = HeaderBar.ActualHeight + Footer.ActualHeight + 2;
            double wantW = PickerPanel.Width + 44 + 2;           // ScrollViewer padding 22 each side, border 1 each side
            double wantH = chrome + PickerPanel.DesiredSize.Height + 36;   // padding 18 top and bottom
            if (!_fitted && ActualWidth > 0) _gameSize = new Size(ActualWidth, ActualHeight);
            Resize(wantW, Math.Min(wantH, work.Height * 0.9));
            _fitted = true;
        }

        void RestoreGameSize()
        {
            if (!_fitted || _drawer.Shrunk || WindowState != WindowState.Normal) { _fitted = false; return; }
            _fitted = false;
            Resize(_gameSize.Width, _gameSize.Height);
        }

        void Resize(double w, double h)
        {
            double oldW = ActualWidth, oldH = ActualHeight;
            var work = ScreenHelper.WorkAreaOf(this);
            Width = w; Height = h;
            if (oldW > 0)
            {
                Left = ScreenHelper.Clamp(Left + (oldW - w) / 2, work.Left, work.Right - w);
                Top = ScreenHelper.Clamp(Top + (oldH - h) / 2, work.Top, work.Bottom - h);
            }
        }

        void FillPicker()
        {
            var defaultKey = GameRegistry.Find(SettingsStore.Load().DefaultGame)?.Key;
            PickerList.ItemsSource = GameRegistry.All.Select(g =>
            {
                int best = new ScoreStore(g.Key).Best();
                return new PickerItem
                {
                    Key = g.Key, DisplayName = g.DisplayName, BestText = best > 0 ? $"Best {best}" : "No score yet",
                    IsDefault = g.Key == defaultKey, Icon = IconOf(g),
                };
            }).ToList();
        }

        /// <summary>Stars a game as the one that opens first, or clears the star if it already has it.</summary>
        void ToggleDefault(string? key)
        {
            if (string.IsNullOrEmpty(key)) return;
            var settings = SettingsStore.Load();
            settings.DefaultGame = string.Equals(settings.DefaultGame, key, StringComparison.OrdinalIgnoreCase) ? null : key;
            SettingsStore.Save(settings);
            if (_game == null) FillPicker();
        }
        void OnToggleDefault(object sender, RoutedEventArgs e)
        {
            if (sender is Button b && b.Tag is string key) ToggleDefault(key);
        }

        void OnPickGame(object sender, RoutedEventArgs e)
        {
            if (sender is Button b && b.Tag is string key)
            {
                var entry = GameRegistry.Find(key);
                if (entry != null) OpenGame(entry);
            }
        }

        // ------------------------------------------------------------ input

        void OnPreviewKeyDown(object sender, KeyEventArgs e)
        {
            var key = e.Key == Key.System ? e.SystemKey : e.Key;
            var mods = Keyboard.Modifiers;
            bool ctrl = (mods & ModifierKeys.Control) != 0, shift = (mods & ModifierKeys.Shift) != 0;

            if (_drawer.OnKey(key, ctrl, shift)) { e.Handled = true; return; }

            if (_game != null)
            {
                switch (key)
                {
                    case Key.Escape: ShowPicker(); e.Handled = true; return;
                    case Key.P when !e.IsRepeat:
                        _host!.Loop.TogglePause();
                        HintText.Text = _host.Loop.Paused ? "Paused   P resume" : _game.Hints;
                        e.Handled = true; return;
                    case Key.R when !e.IsRepeat:
                        if (_entry != null) OpenGame(_entry);
                        e.Handled = true; return;
                }
                _host!.Input.KeyDown(key, e.IsRepeat);
                if (key == Key.Left || key == Key.Right || key == Key.Up || key == Key.Down || key == Key.Space)
                    e.Handled = true;   // arrows must steer the game, not move focus
            }
            else if (key == Key.Escape)
            {
                Close();
                e.Handled = true;
            }
        }

        // ------------------------------------------------------------ header

        void OnHeaderDown(object sender, MouseButtonEventArgs e)
        {
            if (e.ClickCount == 2 && _drawer.OnHeaderDoubleClick()) { e.Handled = true; return; }
            if (e.ClickCount == 1 && !_drawer.Sliding)
            {
                try { DragMove(); } catch { /* button already released */ }
            }
        }

        /// <summary>Three slow clicks on the logo, the same count as the Revit side: back to the picker.</summary>
        void OnLogoClick(object sender, MouseButtonEventArgs e)
        {
            if (_egg.Click(e.Timestamp))
            {
                e.Handled = true;   // swallow only the click that fires, so dragging still works
                ShowPicker();
            }
        }

        void LoadLogo()
        {
            try
            {
                var uri = new Uri("pack://application:,,,/RevoBIM.Arcade;component/Resources/revobim.ico", UriKind.Absolute);
                var decoder = new IconBitmapDecoder(uri, BitmapCreateOptions.None, BitmapCacheOption.OnLoad);
                var best = decoder.Frames.OrderByDescending(f => f.PixelWidth).First();
                LogoImage.Source = best;
                Icon = best;
            }
            catch { /* a missing logo must not stop the arcade opening */ }
        }
    }
}

