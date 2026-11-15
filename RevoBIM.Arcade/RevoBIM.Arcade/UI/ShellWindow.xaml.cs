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
            var entry = GameRegistry.Find(_options.GameKey);
            if (entry != null) { OpenGame(entry); return; }

            var note = string.IsNullOrEmpty(_options.GameKey)
                ? ""
                : $"There is no game called '{_options.GameKey}'. Pick one below.";
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

            PickerList.ItemsSource = GameRegistry.All.Select(g =>
            {
                int best = new ScoreStore(g.Key).Best();
                return new PickerItem { Key = g.Key, DisplayName = g.DisplayName, BestText = best > 0 ? $"Best {best}" : "No score yet" };
            }).ToList();

            GameView.Visibility = Visibility.Collapsed;
            PickerView.Visibility = Visibility.Visible;
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
                ShowPicker("Back at the menu.");
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
