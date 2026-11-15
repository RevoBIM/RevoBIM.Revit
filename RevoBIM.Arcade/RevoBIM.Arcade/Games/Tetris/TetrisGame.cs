using System;
using System.Windows.Controls;
using System.Windows.Shapes;
using WKey = System.Windows.Input.Key;
using RevoBIM.Arcade.Core;

namespace RevoBIM.Arcade.Games.Tetris
{
    /// <summary>
    /// Tetris. The rules live in <see cref="TetrisModel"/>; this class owns the timing (gravity, soft
    /// drop, lock delay, key repeat) and the drawing. Left/Right move, Up or X rotate, Z rotates back,
    /// Down soft-drops, Space hard-drops.
    /// </summary>
    public sealed class TetrisGame : IArcadeGame
    {
        public string Key => "tetris";
        public string DisplayName => "Tetris";
        public string Icon => "M2,4 h6 v6 h-6 z M9,4 h6 v6 h-6 z M16,4 h6 v6 h-6 z M9,11 h6 v6 h-6 z";
        public string Hints => "Left/Right move   Up rotate   Z back   Down soft   Space drop   P pause   R restart   Esc menu";

        const double CellSize = 24, Pad = 12, PanelX = Pad + TetrisModel.Cols * CellSize + 18;
        const double Das = 0.16, Arr = 0.045, SoftInterval = 0.04, LockDelay = 0.45;
        const int MaxLockResets = 15;

        static readonly string[] PieceBrush =
        {
            "", BrushKeys.Ghost3, BrushKeys.Hero, BrushKeys.Ghost2, BrushKeys.Green, BrushKeys.Red, BrushKeys.Blue, BrushKeys.Orange,
        };

        GameHost? _host;
        TetrisModel _model = new TetrisModel();
        Rectangle[,] _cells = new Rectangle[0, 0];
        int[,] _shown = new int[0, 0];
        readonly Rectangle[] _preview = new Rectangle[16];
        TextBlock? _scoreText, _linesText, _levelText;
        TextBlock? _again;

        double _fall, _lock, _hTimer, _hNext = Das;
        int _hHeld, _lockResets, _paint, _bestAtStart;
        bool _recorded, _overlay;

        public void Start(GameHost host)
        {
            _host = host;
            double w = PanelX + 130 + Pad, h = Pad * 2 + TetrisModel.Rows * CellSize;
            host.SetBoardSize(w, h);
            _model = new TetrisModel();
            _bestAtStart = host.Scores.Best();

            _cells = new Rectangle[TetrisModel.Rows, TetrisModel.Cols];
            _shown = new int[TetrisModel.Rows, TetrisModel.Cols];
            for (int r = 0; r < TetrisModel.Rows; r++)
                for (int c = 0; c < TetrisModel.Cols; c++)
                {
                    _cells[r, c] = Kit.Rect(host, Pad + c * CellSize + 1, Pad + r * CellSize + 1, CellSize - 2, CellSize - 2, BrushKeys.Card, 3);
                    _shown[r, c] = -1;
                }

            Kit.Label(host, PanelX, Pad, "NEXT", 12, BrushKeys.Muted, true);
            for (int i = 0; i < 16; i++)
                _preview[i] = Kit.Rect(host, PanelX + (i % 4) * 20, Pad + 28 + (i / 4) * 20, 18, 18, BrushKeys.Card, 3);
            Kit.Label(host, PanelX, 150, "SCORE", 12, BrushKeys.Muted, true);
            _scoreText = Kit.Label(host, PanelX, 168, "0", 22, BrushKeys.Text, true);
            Kit.Label(host, PanelX, 216, "LINES", 12, BrushKeys.Muted, true);
            _linesText = Kit.Label(host, PanelX, 234, "0", 22, BrushKeys.Text, true);
            Kit.Label(host, PanelX, 282, "LEVEL", 12, BrushKeys.Muted, true);
            _levelText = Kit.Label(host, PanelX, 300, "1", 22, BrushKeys.Text, true);

            host.Loop.Tick += OnFrame;
            host.Input.Pressed += OnKey;
            Draw();
        }

        public void Stop()
        {
            if (_host == null) return;
            _host.Loop.Tick -= OnFrame;
            _host.Input.Pressed -= OnKey;
            RecordScore();
            _host = null;
        }

        void RecordScore()
        {
            if (_recorded || _model.Score <= 0 || _host == null) return;
            _recorded = true;
            _host.Scores.Record(_model.Score);
        }

        // ---------------------------------------------------------------- input

        void OnKey(WKey key)
        {
            if (_model.Over) return;
            switch (key)
            {
                case WKey.Up: case WKey.W: case WKey.X:
                    if (_model.TryRotate(1)) Moved();
                    break;
                case WKey.Z:
                    if (_model.TryRotate(-1)) Moved();
                    break;
                case WKey.Space:
                    Landed(_model.HardDrop());
                    break;
            }
        }

        /// <summary>A successful move or turn restarts the lock timer, a limited number of times per piece.</summary>
        void Moved()
        {
            if (_model.Grounded && _lockResets < MaxLockResets) { _lock = 0; _lockResets++; }
        }

        void Landed(int cleared)
        {
            _fall = 0; _lock = 0; _lockResets = 0;
            if (_model.Over) GameOver();
        }

        void GameOver() => RecordScore();

        // ---------------------------------------------------------------- frame

        void OnFrame(double dt)
        {
            _paint++;
            if (!_model.Over) Update(dt);
            Draw();
        }

        void Update(double dt)
        {
            var input = _host!.Input;

            // sideways: one step on the press, then repeat after a short hold
            int dir = (input.Left ? -1 : 0) + (input.Right ? 1 : 0);
            if (dir != _hHeld)
            {
                _hHeld = dir; _hTimer = 0; _hNext = Das;
                if (dir != 0 && _model.TryMove(dir, 0)) Moved();
            }
            else if (dir != 0)
            {
                _hTimer += dt;
                while (_hTimer >= _hNext)
                {
                    _hTimer -= _hNext; _hNext = Arr;
                    if (_model.TryMove(dir, 0)) Moved();
                }
            }

            // gravity, faster while Down is held
            bool soft = input.Down;
            double interval = soft ? Math.Min(SoftInterval, _model.FallInterval) : _model.FallInterval;
            _fall += dt;
            while (_fall >= interval && !_model.Grounded)
            {
                _fall -= interval;
                if (_model.TryMove(0, 1) && soft) _model.AddSoftDrop(1);
            }

            if (_model.Grounded)
            {
                _fall = 0;   // no stored-up gravity to spend the moment the piece is free again
                _lock += dt;
                if (_lock >= LockDelay) Landed(_model.Lock());
            }
            else _lock = 0;
        }

        // ---------------------------------------------------------------- drawing

        void Draw()
        {
            var host = _host;
            if (host == null) return;

            // what to show in each cell: locked piece id, or the falling piece, or its landing shadow
            var show = new int[TetrisModel.Rows, TetrisModel.Cols];
            for (int r = 0; r < TetrisModel.Rows; r++)
                for (int c = 0; c < TetrisModel.Cols; c++) show[r, c] = _model.Grid[r, c];

            if (!_model.Over)
            {
                int landing = _model.LandingY();
                foreach (var (cx, cy) in TetrisModel.CellsOf(_model.Piece, _model.Rotation))
                {
                    int sy = landing + cy, sx = _model.X + cx;
                    if (sy >= 0 && sy < TetrisModel.Rows && show[sy, sx] == 0) show[sy, sx] = -_model.Piece;   // negative = shadow
                }
                foreach (var (cx, cy) in TetrisModel.CellsOf(_model.Piece, _model.Rotation))
                {
                    int sy = _model.Y + cy, sx = _model.X + cx;
                    if (sy >= 0 && sy < TetrisModel.Rows) show[sy, sx] = _model.Piece;
                }
            }

            for (int r = 0; r < TetrisModel.Rows; r++)
                for (int c = 0; c < TetrisModel.Cols; c++)
                {
                    int v = show[r, c];
                    if (v == _shown[r, c]) continue;
                    _shown[r, c] = v;
                    var cell = _cells[r, c];
                    int piece = Math.Abs(v);
                    Kit.Refill(cell, piece == 0 ? BrushKeys.Card : PieceBrush[piece]);
                    cell.Opacity = v < 0 ? 0.28 : 1.0;
                }

            DrawPreview();
            _scoreText!.Text = _model.Score.ToString();
            _linesText!.Text = _model.Lines.ToString();
            _levelText!.Text = _model.Level.ToString();
            host.SetStatus($"Score {_model.Score}    Lines {_model.Lines}    Level {_model.Level}    Best {Math.Max(_bestAtStart, _model.Score)}");

            if (_model.Over) DrawOver();
        }

        int _previewShown = -1;

        void DrawPreview()
        {
            if (_previewShown == _model.Next) return;
            _previewShown = _model.Next;
            foreach (var r in _preview) { Kit.Refill(r, BrushKeys.Card); }
            int n = _model.Next;
            if (n < 1) return;
            foreach (var (cx, cy) in TetrisModel.CellsOf(n, 0))
                Kit.Refill(_preview[cy * 4 + cx], PieceBrush[n]);
        }

        void DrawOver()
        {
            var host = _host!;
            if (!_overlay)
            {
                _overlay = true;
                bool beat = _model.Score > _bestAtStart;
                double gridW = TetrisModel.Cols * CellSize, top = host.BoardHeight / 2.0 - 70;
                var veil = new Rectangle { Width = gridW, Height = TetrisModel.Rows * CellSize };
                veil.SetResourceReference(Shape.FillProperty, BrushKeys.Veil);
                Kit.Place(veil, Pad, Pad);
                host.Surface.Children.Add(veil);

                // banners are board-wide strips; keep their text inside the grid by using a grid-sized host strip
                AddCentred(host, top, beat ? "NEW BEST" : "GAME OVER", 24, beat ? BrushKeys.Green : BrushKeys.Red, gridW);
                AddCentred(host, top + 40, $"{_model.Score} points", 16, BrushKeys.Hero, gridW);
                AddCentred(host, top + 70, $"{_model.Lines} lines  -  level {_model.Level}", 11, BrushKeys.Muted, gridW);
                _again = AddCentred(host, top + 104, "press R to play again", 12, BrushKeys.Orange, gridW);
            }
            if (_again != null) _again.Opacity = 0.55 + 0.45 * Kit.Wave(_paint);
        }

        static TextBlock AddCentred(GameHost host, double top, string text, double size, string brush, double width)
        {
            var t = new TextBlock
            {
                Text = text, FontFamily = new System.Windows.Media.FontFamily("Segoe UI"), FontSize = size,
                FontWeight = System.Windows.FontWeights.SemiBold, TextAlignment = System.Windows.TextAlignment.Center, Width = width,
            };
            host.Text(t, brush);
            Kit.Place(t, Pad, top);
            host.Surface.Children.Add(t);
            return t;
        }
    }
}
