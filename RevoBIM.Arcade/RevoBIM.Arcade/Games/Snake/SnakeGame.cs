using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Media;
using System.Windows.Shapes;
using WKey = System.Windows.Input.Key;
using RevoBIM.Arcade.Core;

namespace RevoBIM.Arcade.Games.Snake
{
    /// <summary>
    /// Snake, ported from the pyRevit egg: 19 x 21 cells, 110 ms per move, +10 per food, the same ranks and
    /// sign-offs. Each segment is drawn sliding between the cell it left and the cell it is in.
    /// </summary>
    public sealed class SnakeGame : IArcadeGame
    {
        public string Key => "snake";
        public string DisplayName => "Snake";
        public string Hints => "Arrows / WASD turn   P pause   R restart   Esc menu";

        public System.Windows.UIElement? CreateIcon()
        {
            var box = IconKit.Box();
            const string Path = "M15,5.5 L8,5.5 Q4.2,5.5 4.2,9 Q4.2,12.2 8,12.2 L16,12.2 Q19.8,12.2 19.8,15.6 Q19.8,18.8 16,18.8 L8,18.8";
            box.Children.Add(new System.Windows.Shapes.Path { Data = Geometry.Parse(Path), Stroke = IconKit.Solid("#17692C"), StrokeThickness = 5.6,
                StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, StrokeLineJoin = PenLineJoin.Round });
            box.Children.Add(new System.Windows.Shapes.Path { Data = Geometry.Parse(Path), Stroke = IconKit.Vertical("#8BEA9C", "#2FB152"), StrokeThickness = 4.2,
                StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, StrokeLineJoin = PenLineJoin.Round });
            box.Children.Add(new System.Windows.Shapes.Path { Data = Geometry.Parse("M15,4.6 L8,4.6 Q5.2,4.6 5.2,7"), Stroke = IconKit.Solid("#66FFFFFF"), StrokeThickness = 0.9,
                StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
            // head
            box.Children.Add(IconKit.Dot(7.4, 18.8, 3.6, 3.2, IconKit.Glow("#E6FF8A", "#7BD84A", "#2C9A3C")));
            box.Children.Add(IconKit.Dot(6.6, 17.6, 1.0, 1.1, IconKit.Solid("#FFFFFF")));
            box.Children.Add(IconKit.Dot(9.0, 17.6, 1.0, 1.1, IconKit.Solid("#FFFFFF")));
            box.Children.Add(IconKit.Dot(6.7, 17.8, 0.5, 0.6, IconKit.Solid("#1B1B1B")));
            box.Children.Add(IconKit.Dot(9.1, 17.8, 0.5, 0.6, IconKit.Solid("#1B1B1B")));
            // apple
            box.Children.Add(IconKit.Dot(19.6, 5.2, 2.6, 2.6, IconKit.Glow("#FFB0A8", "#E5392F", "#9C1712")));
            box.Children.Add(IconKit.Shape("M19.6,2.8 Q21.4,1.2 22.6,2.2 Q21.2,3.6 19.6,2.8 Z", IconKit.Vertical("#8BEA9C", "#2FB152")));
            return IconKit.Wrap(box);
        }

        const int Cell = 18;
        const double StepSeconds = 0.110;

        static readonly (int Score, string Title)[] Ranks =
        {
            (0, "Cable Puller"), (60, "Containment Fitter"), (150, "Riser Wrangler"), (280, "Tray Tsar"), (450, "Lord of the Basket"),
        };

        static readonly string[] SignOffs =
        {
            "Route rejected by the ceiling void.", "Clashed with itself. Again.",
            "That is going to need a transition piece.", "Coordination comment: see attached.",
        };

        readonly FixedStep _step = new FixedStep(StepSeconds);
        readonly List<Rectangle> _segments = new List<Rectangle>();
        readonly Random _random = new Random();

        GameHost? _host;
        SnakeModel _model = new SnakeModel();
        Ellipse? _food;
        System.Windows.Controls.TextBlock? _again;
        int _paint, _bestAtStart;
        bool _recorded, _overlay;

        public void Start(GameHost host)
        {
            _host = host;
            host.SetBoardSize(SnakeModel.Cols * Cell, SnakeModel.Rows * Cell);
            _model = new SnakeModel();
            _bestAtStart = host.Scores.Best();

            Kit.Rect(host, 0, 0, host.BoardWidth, host.BoardHeight, BrushKeys.Field, 4);
            _food = Kit.Circle(host, 0, 0, Cell / 2.0 - 4, BrushKeys.Power);

            host.Loop.Tick += OnFrame;
            host.Input.Pressed += OnKey;
            Report();
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

        void Report() =>
            _host?.SetStatus($"Score {_model.Score}    Length {_model.Body.Count}    Best {Math.Max(_bestAtStart, _model.Score)}");

        void OnKey(WKey key)
        {
            switch (key)
            {
                case WKey.Up: case WKey.W: _model.Turn(SnakeModel.Up); break;
                case WKey.Down: case WKey.S: _model.Turn(SnakeModel.Down); break;
                case WKey.Left: case WKey.A: _model.Turn(SnakeModel.Left); break;
                case WKey.Right: case WKey.D: _model.Turn(SnakeModel.Right); break;
            }
        }

        void OnFrame(double dt)
        {
            _paint++;
            if (_model.Over) { DrawOver(); return; }

            if (_step.Advance(dt, () => _model.Step()) > 0)
            {
                Report();
                if (_model.Over) { RecordScore(); DrawOver(); return; }
            }
            Render(_step.Alpha);
        }

        /// <summary>A snake that jumps a whole cell every 110 ms reads as a slideshow, so each segment slides.</summary>
        void Render(double alpha)
        {
            var host = _host!;
            var body = _model.Body; var was = _model.Previous;

            while (_segments.Count < body.Count)
                _segments.Add(Kit.Rect(host, 0, 0, Cell - 4, Cell - 4, _segments.Count == 0 ? BrushKeys.Hero : BrushKeys.Green, 4));

            for (int i = 0; i < body.Count; i++)
            {
                var (col, row) = body[i];
                var (pc, pr) = i < was.Count ? was[i] : (col, row);
                Kit.Place(_segments[i], (pc + (col - pc) * alpha) * Cell + 2, (pr + (row - pr) * alpha) * Cell + 2);
            }

            Kit.Place(_food!, _model.Food.X * Cell + 4, _model.Food.Y * Cell + 4);
        }

        void DrawOver()
        {
            var host = _host;
            if (host == null) return;
            if (!_overlay)
            {
                _overlay = true;
                RecordScore();
                bool beat = _model.Score > _bestAtStart;
                var veil = new Rectangle { Width = host.BoardWidth, Height = host.BoardHeight };
                veil.SetResourceReference(Shape.FillProperty, BrushKeys.Veil);
                host.Surface.Children.Add(veil);
                double top = host.BoardHeight / 2.0 - 76;
                Kit.Banner(host, top, beat ? "NEW BEST" : "GAME OVER", 24, beat ? BrushKeys.Green : BrushKeys.Red, null);
                Kit.Banner(host, top + 40, $"{_model.Score} points   -   {_model.Body.Count} long", 14, BrushKeys.Hero, null);
                Kit.Banner(host, top + 70, RankOf(_model.Score), 14, BrushKeys.Blue, null);
                Kit.Banner(host, top + 96, SignOffs[_random.Next(SignOffs.Length)], 11, BrushKeys.Muted, null);
                _again = (System.Windows.Controls.TextBlock)Kit.Banner(host, top + 124, "press R to play again", 12, BrushKeys.Orange, null).Child;
            }
            if (_again != null) _again.Opacity = 0.55 + 0.45 * Kit.Wave(_paint);
        }

        internal static string RankOf(int score)
        {
            string title = Ranks[0].Title;
            foreach (var (threshold, name) in Ranks) if (score >= threshold) title = name;
            return title;
        }
    }
}
