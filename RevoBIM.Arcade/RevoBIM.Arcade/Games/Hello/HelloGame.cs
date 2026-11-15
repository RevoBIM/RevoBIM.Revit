using System;
using System.Windows.Controls;
using System.Windows.Shapes;
using WKey = System.Windows.Input.Key;
using RevoBIM.Arcade.Core;

namespace RevoBIM.Arcade.Games.Hello
{
    /// <summary>
    /// The placeholder game: a square that bounces round the board. It exists to prove the
    /// registry, launch path, loop, input, theme brushes and score storage work end to end.
    /// Arrow keys steer it; each bounce scores a point.
    /// </summary>
    public sealed class HelloGame : IArcadeGame
    {
        const double Size = 44, Speed = 190;

        public string Key => "hello";
        public string DisplayName => "Hello";
        public string Icon => "M4,4 h16 v16 h-16 z";
        public string Hints => "Arrows steer   P pause   R restart   Esc menu";

        GameHost? _host;
        Rectangle? _square;
        double _x = 60, _y = 60, _vx = Speed, _vy = Speed * 0.65;
        int _bounces;

        public void Start(GameHost host)
        {
            _host = host;
            host.SetBoardSize(640, 360);

            _square = new Rectangle { Width = Size, Height = Size, RadiusX = 6, RadiusY = 6 };
            host.Fill(_square, "HeroBrush");
            host.Surface.Children.Add(_square);

            var label = new TextBlock { Text = "Hello, RevoBIM", FontFamily = new System.Windows.Media.FontFamily("Segoe UI"), FontSize = 14 };
            host.Text(label, "MutedBrush");
            Canvas.SetLeft(label, 12); Canvas.SetTop(label, 8);
            host.Surface.Children.Add(label);

            host.Loop.Tick += OnTick;
            host.Input.Pressed += OnKey;
            Report();
        }

        void OnTick(double dt)
        {
            if (_host == null || _square == null) return;

            _x += _vx * dt; _y += _vy * dt;
            double maxX = _host.BoardWidth - Size, maxY = _host.BoardHeight - Size;

            if (_x < 0) { _x = 0; _vx = Math.Abs(_vx); Bounce(); }
            else if (_x > maxX) { _x = maxX; _vx = -Math.Abs(_vx); Bounce(); }
            if (_y < 0) { _y = 0; _vy = Math.Abs(_vy); Bounce(); }
            else if (_y > maxY) { _y = maxY; _vy = -Math.Abs(_vy); Bounce(); }

            Canvas.SetLeft(_square, _x);
            Canvas.SetTop(_square, _y);
        }

        // The IArcadeGame.Key property hides the Key enum inside a game, hence the alias.
        void OnKey(WKey key)
        {
            switch (key)
            {
                case WKey.Left: case WKey.A: _vx = -Math.Abs(_vx); break;
                case WKey.Right: case WKey.D: _vx = Math.Abs(_vx); break;
                case WKey.Up: case WKey.W: _vy = -Math.Abs(_vy); break;
                case WKey.Down: case WKey.S: _vy = Math.Abs(_vy); break;
            }
        }

        void Bounce() { _bounces++; Report(); }

        void Report() => _host?.SetStatus($"Bounces {_bounces}    Best {Math.Max(_host.Scores.Best(), _bounces)}");

        public void Stop()
        {
            if (_host != null)
            {
                _host.Loop.Tick -= OnTick;
                _host.Input.Pressed -= OnKey;
                if (_bounces > 0) _host.Scores.Record(_bounces);
            }
            _host = null; _square = null;
        }
    }
}
