using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Shapes;
using WKey = System.Windows.Input.Key;
using RevoBIM.Arcade.Core;

namespace RevoBIM.Arcade.Games.PacMan
{
    /// <summary>
    /// Pacman, ported from the pyRevit egg (games\pacman.py) with the same maze, speeds, ghost
    /// targeting and scoring. Logic runs on a fixed 33 ms step on the integer pixel grid the rules
    /// depend on; drawing happens every frame, interpolated between the last two steps.
    /// One life: losing is meant to be quick and often.
    /// </summary>
    public sealed class PacManGame : IArcadeGame
    {
        public string Key => "pacman";
        public string DisplayName => "Pacman";
        public string Icon => "M12,12 L20.66,7 A10,10 0 1 0 20.66,17 Z M13,5.5 a1.6,1.6 0 1 1 -0.01,0 Z";
        public string Hints => "Arrows / WASD move   P pause   R restart   Esc menu";

        // '#' wall   '.' pellet   'o' power pellet   '-' ghost house door
        // ' ' empty  'P' hero start   'G' ghost start
        internal static readonly string[] Maze =
        {
            "###################",
            "#........#........#",
            "#o##.###.#.###.##o#",
            "#.................#",
            "#.##.#.#####.#.##.#",
            "#....#...#...#....#",
            "####.###.#.###.####",
            "####.#.......#.####",
            "####.#.##-##.#.####",
            ".....#.#GGG#.#.....",
            "####.#.#####.#.####",
            "####.#.......#.####",
            "####.###.#.###.####",
            "#........#........#",
            "#.##.###.#.###.##.#",
            "#o.#.....P.....#.o#",
            "##.#.#.#####.#.#.##",
            "#....#...#...#....#",
            "#.####.#####.####.#",
            "#.................#",
            "###################",
        };

        internal const int Cell = 18, Half = 9;
        const double StepSeconds = 0.033;

        static readonly (int X, int Y) Up = (0, -1), Down = (0, 1), Left = (-1, 0), Right = (1, 0), Still = (0, 0);
        static readonly (int X, int Y)[] Dirs = { Up, Down, Left, Right };

        const int HeroSpeed = 3, GhostSpeed = 2, ScaredSpeed = 1, EyesSpeed = 6;
        const int Lives = 1;
        const int ScaredTicks = 240, ReadyTicks = 45, DeathTicks = 90;

        sealed class Spec
        {
            public Spec(string name, string brush, int release, int cornerCol, int cornerRow)
            { Name = name; Brush = brush; Release = release; Corner = (cornerCol, cornerRow); }
            public string Name, Brush; public int Release; public (int X, int Y) Corner;
        }

        static readonly Spec[] Specs =
        {
            new Spec("blinky", BrushKeys.Ghost1, 0, 17, 1),
            new Spec("pinky", BrushKeys.Ghost2, 60, 1, 1),
            new Spec("inky", BrushKeys.Ghost3, 150, 17, 19),
            new Spec("clyde", BrushKeys.Ghost4, 260, 1, 19),
        };

        static readonly (int Score, string Title)[] Ranks =
        {
            (0, "Setting Out Apprentice"), (400, "Draughtsperson, Second Class"), (1200, "Junior BIM Coordinator"),
            (2400, "MEP Coordinator"), (4000, "Clash Detective"), (6500, "Lead Services Engineer"),
            (9500, "Model Federation Overlord"),
        };

        static readonly string[] SignOffs =
        {
            "The ghosts have raised an RFI.", "Marked up in red and returned.", "Rejected at technical review.",
            "Superseded. Try P02.", "Clash count: 1. Yours.", "That one is going in the issue log.",
            "Please resubmit with a coordinated route.",
        };

        sealed class Mover
        {
            public int X, Y, PX, PY;
            public (int X, int Y) Dir, Want;
            // ghosts only
            public Spec? Spec; public int Index, HomeY, Timer;
            public bool Home, Released, Eyes;
            public Rectangle? Body; public Ellipse[] Eye = new Ellipse[2], Pupil = new Ellipse[2];
            public string BodyBrush = "";
        }

        enum Mode { Ready, Run, Dying, Over }

        readonly Random _random = new Random();
        readonly FixedStep _step = new FixedStep(StepSeconds);
        readonly int _cols = Maze[0].Length, _rows = Maze.Length;
        readonly Dictionary<(int, int), (char Kind, Ellipse Shape)> _pellets = new Dictionary<(int, int), (char, Ellipse)>();

        GameHost? _host;
        Mover _hero = new Mover();
        readonly List<Mover> _ghosts = new List<Mover>();
        Path? _heroShape;
        Border? _message;
        TextBlock? _again;

        (int Col, int Row) _heroCell, _houseCell, _doorCell;
        Mode _mode = Mode.Ready;
        int _wait, _frame, _paint, _scared, _chain;
        int _score, _level = 1, _lives = Lives, _eatenPellets, _eatenGhosts, _bestAtStart;
        bool _recorded, _overlay;
        string _signOff = SignOffs[0];

        // ---------------------------------------------------------------- shell contract

        public void Start(GameHost host)
        {
            _host = host;
            host.SetBoardSize(_cols * Cell, _rows * Cell);
            _heroCell = Find('P'); _houseCell = Find('G'); _doorCell = Find('-');
            _bestAtStart = host.Scores.Best();
            _wait = ReadyTicks;
            BuildBoard();
            Say("READY");
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
            if (_recorded || _score <= 0 || _host == null) return;
            _recorded = true;
            _host.Scores.Record(_score);
        }

        void Report() =>
            _host?.SetStatus($"Score {_score}    Level {_level}    Pellets {_eatenPellets}    Best {Math.Max(_bestAtStart, _score)}");

        void OnKey(WKey key)
        {
            if (_mode == Mode.Over) return;
            (int X, int Y)? want = key switch
            {
                WKey.Up or WKey.W => Up,
                WKey.Down or WKey.S => Down,
                WKey.Left or WKey.A => Left,
                WKey.Right or WKey.D => Right,
                _ => null,
            };
            if (want.HasValue) _hero.Want = want.Value;
        }

        void OnFrame(double dt)
        {
            _step.Advance(dt, LogicStep);
            Render(_mode == Mode.Ready ? 1.0 : _step.Alpha);
        }

        // ---------------------------------------------------------------- maze

        (int, int) Find(char c)
        {
            for (int r = 0; r < _rows; r++)
                for (int col = 0; col < _cols; col++)
                    if (Maze[r][col] == c) return (col, r);
            return (1, 1);
        }

        static int Mod(int a, int b) => ((a % b) + b) % b;
        static int FloorDiv(int a, int b) => (int)Math.Floor((double)a / b);
        static double Mod(double a, double b) => a - b * Math.Floor(a / b);

        char At(int col, int row) => row < 0 || row >= _rows ? '#' : Maze[row][Mod(col, _cols)];

        bool Walkable(int col, int row, bool ghost = false)
        {
            char c = At(col, row);
            if (c == '#') return false;
            if (c == '-') return ghost;
            return true;
        }

        (int X, int Y) Centre(int col, int row) => (col * Cell + Half, row * Cell + Half);

        (int Col, int Row) CellOf(Mover m) => (Mod(FloorDiv(m.X - Half, Cell), _cols), FloorDiv(m.Y - Half, Cell));

        bool Aligned(Mover m) => Mod(m.X - Half, Cell) == 0 && Mod(m.Y - Half, Cell) == 0;

        static int NextAlign(int value, int step)
        {
            int offset = Mod(value - Half, Cell);
            return step > 0 ? value + (offset != 0 ? Cell - offset : Cell) : value - (offset != 0 ? offset : Cell);
        }

        /// <summary>
        /// Move, but never past the next cell centre. Without the clamp a mover whose speed changes
        /// mid-cell (a ghost turning frightened, or into eyes) steps over the alignment point it
        /// decides on, and never turns again.
        /// </summary>
        void Advance(Mover m, int speed)
        {
            if (m.Dir == Still) return;
            if (m.Dir.X != 0)
            {
                int target = NextAlign(m.X, m.Dir.X), moved = m.X + m.Dir.X * speed;
                if ((m.Dir.X > 0 && moved > target) || (m.Dir.X < 0 && moved < target)) moved = target;
                m.X = moved;
            }
            else
            {
                int target = NextAlign(m.Y, m.Dir.Y), moved = m.Y + m.Dir.Y * speed;
                if ((m.Dir.Y > 0 && moved > target) || (m.Dir.Y < 0 && moved < target)) moved = target;
                m.Y = moved;
            }
            int width = _cols * Cell;
            if (m.X < 0) m.X += width; else if (m.X >= width) m.X -= width;
        }

        // ---------------------------------------------------------------- building

        void BuildBoard()
        {
            var host = _host!;
            host.Surface.Children.Clear();
            _pellets.Clear();
            _ghosts.Clear();
            _message = null; _again = null; _overlay = false;

            for (int r = 0; r < _rows; r++)
                for (int c = 0; c < _cols; c++)
                {
                    char ch = Maze[r][c];
                    if (ch == '#') Kit.Rect(host, c * Cell + 1, r * Cell + 1, Cell - 2, Cell - 2, BrushKeys.Maze, 4);
                    else if (ch == '-') Kit.Rect(host, c * Cell + 1, r * Cell + Half - 1, Cell - 2, 2, BrushKeys.Power);
                    else if (ch == '.' || ch == 'o')
                    {
                        var (cx, cy) = Centre(c, r);
                        var dot = Kit.Circle(host, cx, cy, ch == 'o' ? 4.5 : 1.8, ch == 'o' ? BrushKeys.Power : BrushKeys.Pellet);
                        _pellets[(c, r)] = (ch, dot);
                    }
                }

            _heroShape = new Path();
            host.Fill(_heroShape, BrushKeys.Hero);
            host.Surface.Children.Add(_heroShape);

            for (int i = 0; i < Specs.Length; i++)
            {
                var g = new Mover { Spec = Specs[i], Index = i };
                g.Body = Kit.Rect(host, 0, 0, Cell - 4, Cell - 4, Specs[i].Brush, 6);
                g.BodyBrush = Specs[i].Brush;
                for (int s = 0; s < 2; s++)
                {
                    g.Eye[s] = Kit.Circle(host, 0, 0, 2.5, BrushKeys.Eyes);
                    g.Pupil[s] = Kit.Circle(host, 0, 0, 1.2, BrushKeys.Pupil);
                }
                _ghosts.Add(g);
            }
            ResetMovers();
        }

        void ResetMovers()
        {
            var (hx, hy) = Centre(_heroCell.Col, _heroCell.Row);
            _hero = new Mover { X = hx, Y = hy, PX = hx, PY = hy, Dir = Left, Want = Left };
            foreach (var g in _ghosts)
            {
                var (gx, gy) = Centre(_houseCell.Col + (g.Index % 3), _houseCell.Row);
                g.X = gx; g.Y = gy; g.PX = gx; g.PY = gy; g.HomeY = gy;
                g.Dir = Up; g.Home = true; g.Released = false; g.Eyes = false; g.Timer = g.Spec!.Release;
            }
            _scared = 0; _chain = 0;
        }

        // ---------------------------------------------------------------- logic

        void LogicStep()
        {
            _frame++;
            if (_mode == Mode.Over) return;

            if (_mode == Mode.Ready || _mode == Mode.Dying)
            {
                if (--_wait > 0) return;
                if (_mode == Mode.Dying)
                {
                    if (_lives <= 0) { GameOver(); return; }
                    ResetMovers();
                    _mode = Mode.Ready; _wait = ReadyTicks;
                    Say("READY");
                    return;
                }
                _mode = Mode.Run;
                Say(null);
                return;
            }

            if (_scared > 0 && --_scared == 0) _chain = 0;

            Remember(_hero);
            foreach (var g in _ghosts) Remember(g);

            MoveHero();
            Eat();
            foreach (var g in _ghosts) MoveGhost(g);
            Collide();

            if (_pellets.Count == 0) NextLevel();
            Report();
        }

        static void Remember(Mover m) { m.PX = m.X; m.PY = m.Y; }

        void MoveHero()
        {
            var hero = _hero;
            if (Aligned(hero))
            {
                var (col, row) = CellOf(hero);
                var want = hero.Want;
                if (want != Still && Walkable(col + want.X, row + want.Y)) hero.Dir = want;
                var fwd = hero.Dir;
                if (!Walkable(col + fwd.X, row + fwd.Y)) hero.Dir = Still;
            }
            Advance(hero, HeroSpeed);
        }

        void MoveGhost(Mover g)
        {
            int speed = g.Eyes ? EyesSpeed : _scared > 0 ? ScaredSpeed : GhostSpeed;
            (int X, int Y) target;

            if (g.Home)
            {
                if (--g.Timer > 0)
                {
                    // Bob on the spot so the house does not look frozen. The offset is thrown away on
                    // release: a ghost a pixel off the grid never aligns again.
                    g.Y = g.HomeY + ((_frame / 12) % 2 == 1 ? 2 : -2);
                    return;
                }
                if (!g.Released)
                {
                    // Once only. Doing this every tick re-points the ghost at the ceiling each frame.
                    g.Y = g.HomeY; g.Dir = Up; g.Released = true;
                }
                target = _doorCell;
            }
            else if (g.Eyes) target = _houseCell;
            else target = Target(g);

            if (Aligned(g))
            {
                var (col, row) = CellOf(g);
                if (g.Home && row <= target.Y) { g.Home = false; g.Dir = Up; }
                if (g.Eyes && (col, row) == target)
                {
                    g.Eyes = false; g.Home = true; g.Released = false; g.Timer = 45;
                    return;
                }
                g.Dir = Choose(g, col, row, target);
            }
            Advance(g, speed);
        }

        (int X, int Y) Target(Mover g)
        {
            var (hc, hr) = CellOf(_hero);
            var (dx, dy) = _hero.Dir;
            if (_scared > 0) return g.Spec!.Corner;
            switch (g.Spec!.Name)
            {
                case "blinky": return (hc, hr);
                case "pinky": return (hc + dx * 4, hr + dy * 4);
                case "inky": return (hc + dx * 2, hr + dy * 2);
            }
            var (col, row) = CellOf(g);
            int far = Math.Abs(col - hc) + Math.Abs(row - hr);
            return far > 8 ? (hc, hr) : g.Spec.Corner;
        }

        (int X, int Y) Choose(Mover g, int col, int row, (int X, int Y) target)
        {
            var back = (-g.Dir.X, -g.Dir.Y);
            var options = new List<(int X, int Y)>();
            foreach (var o in Dirs)
            {
                if (o == back) continue;
                if (Walkable(col + o.X, row + o.Y, g.Eyes || g.Home)) options.Add(o);
            }
            if (options.Count == 0) return back;
            if (_scared > 0 && !g.Eyes) return options[_random.Next(options.Count)];
            var best = options[0];
            long bestGap = long.MaxValue;
            foreach (var o in options)
            {
                long gx = col + o.X - target.X, gy = row + o.Y - target.Y;
                long gap = gx * gx + gy * gy;
                if (gap < bestGap) { bestGap = gap; best = o; }
            }
            return best;
        }

        void Eat()
        {
            if (!Aligned(_hero)) return;
            var cell = CellOf(_hero);
            if (!_pellets.TryGetValue(cell, out var pellet)) return;
            _pellets.Remove(cell);
            _host!.Surface.Children.Remove(pellet.Shape);
            _eatenPellets++;
            if (pellet.Kind == 'o')
            {
                _score += 50; _scared = ScaredTicks; _chain = 0;
                foreach (var g in _ghosts)
                    if (!g.Eyes && !g.Home) g.Dir = (-g.Dir.X, -g.Dir.Y);
            }
            else _score += 10;
        }

        void Collide()
        {
            foreach (var g in _ghosts)
            {
                if (g.Eyes || g.Home) continue;
                if (Math.Abs(g.X - _hero.X) + Math.Abs(g.Y - _hero.Y) > Cell * 0.8) continue;
                if (_scared > 0)
                {
                    _chain++; _eatenGhosts++;
                    _score += 200 * (1 << (_chain - 1));
                    g.Eyes = true;
                    return;
                }
                // The death animation plays either way; on one life that is the only time it shows.
                _lives--;
                _mode = Mode.Dying; _wait = DeathTicks;
                return;
            }
        }

        void GameOver()
        {
            _mode = Mode.Over;
            _signOff = SignOffs[_random.Next(SignOffs.Length)];
            Say(null);
            RecordScore();
            Report();
        }

        void NextLevel()
        {
            _level++;
            BuildBoard();
            _mode = Mode.Ready; _wait = ReadyTicks;
            Say($"LEVEL {_level}");
        }

        // ---------------------------------------------------------------- drawing

        void Say(string? text)
        {
            var host = _host;
            if (host == null) return;
            if (_message != null) { host.Surface.Children.Remove(_message); _message = null; }
            if (text == null) return;
            _message = Kit.Banner(host, _rows * Cell / 2.0 + Cell * 3 - 14, text, 15, BrushKeys.Orange);
        }

        void Render(double alpha)
        {
            if (_host == null) return;
            _paint++;

            if (_mode == Mode.Over) { DrawOver(); return; }

            if (_mode == Mode.Dying)
            {
                DrawDeath();
                foreach (var g in _ghosts) ShowGhost(g, false);
                return;
            }

            DrawHero(alpha);
            foreach (var g in _ghosts) DrawGhost(g, alpha);
        }

        /// <summary>
        /// Where to draw a mover this frame. One that just came through the tunnel is a whole board
        /// width from where it was; interpolating that would fling it back across the screen.
        /// </summary>
        static (double X, double Y) Lerp(Mover m, double alpha)
        {
            if (Math.Abs(m.X - m.PX) > Cell || Math.Abs(m.Y - m.PY) > Cell) return (m.X, m.Y);
            return (m.PX + (m.X - m.PX) * alpha, m.PY + (m.Y - m.PY) * alpha);
        }

        static int AngleOf((int X, int Y) d) => d == Up ? 270 : d == Down ? 90 : d == Left ? 180 : 0;

        void DrawHero(double alpha)
        {
            var (x, y) = Lerp(_hero, alpha);
            // The mouth follows distance travelled, so it chews at the speed it moves and holds still when it stops.
            double mouth = _hero.Dir == Still ? 40 : Math.Abs(Mod((x + y) * 4, 140.0) - 70);
            _heroShape!.Data = Kit.Wedge(x, y, Half - 1, AngleOf(_hero.Dir) + mouth / 2.0, 360 - mouth);
            _heroShape.Visibility = Visibility.Visible;
        }

        void DrawDeath()
        {
            double gone = (double)(DeathTicks - _wait) / DeathTicks;
            double mouth = Math.Min(358.0, 40 + gone * 340.0);
            double radius = Math.Max(0.6, (Half - 1) * (1.0 - gone * 0.9));
            _heroShape!.Data = Kit.Wedge(_hero.X, _hero.Y, radius, AngleOf(_hero.Dir) + mouth / 2.0, 360 - mouth);
            _heroShape.Visibility = gone < 0.98 ? Visibility.Visible : Visibility.Hidden;
        }

        static void ShowGhost(Mover g, bool on)
        {
            var v = on ? Visibility.Visible : Visibility.Hidden;
            g.Body!.Visibility = v;
            for (int s = 0; s < 2; s++) { g.Eye[s].Visibility = v; g.Pupil[s].Visibility = v; }
        }

        void DrawGhost(Mover g, double alpha)
        {
            var (x, y) = Lerp(g, alpha);
            string brush;
            if (g.Eyes) brush = BrushKeys.MazeFill;
            else if (_scared > 0) brush = _scared < 60 && (_frame / 8) % 2 == 0 ? BrushKeys.ScaredEnd : BrushKeys.Scared;
            else brush = g.Spec!.Brush;
            if (brush != g.BodyBrush) { Kit.Refill(g.Body!, brush); g.BodyBrush = brush; }

            const double size = Cell - 4;
            // A slight bob so a ghost gliding down a corridor is not a sliding brick.
            double bob = ((_paint + g.Index * 9) / 16) % 2 == 1 ? 0.8 : -0.8;
            Kit.Place(g.Body!, x - size / 2.0, y - size / 2.0 + bob);
            for (int s = 0; s < 2; s++)
            {
                double ox = s == 0 ? -3.4 : 3.4;
                Kit.Place(g.Eye[s], x + ox - 2.5, y - 2 + bob - 2.5);
                Kit.Place(g.Pupil[s], x + ox + g.Dir.X * 1.1 - 1.2, y - 2 + bob + g.Dir.Y * 1.1 - 1.2);
            }
            ShowGhost(g, true);
        }

        void DrawOver()
        {
            var host = _host!;
            double width = host.BoardWidth, height = host.BoardHeight;
            if (!_overlay)
            {
                _overlay = true;
                bool beat = _score > _bestAtStart;
                host.Surface.Children.Add(OverlayRect(width, height));
                double top = height / 2.0 - 96;
                Kit.Banner(host, top, beat ? "NEW BEST" : "GAME OVER", 26, beat ? BrushKeys.Green : BrushKeys.Red, null);
                Kit.Banner(host, top + 42, $"{_score} points", 17, BrushKeys.Hero, null);
                Kit.Banner(host, top + 74, $"level {_level}  -  {_eatenPellets} pellets  -  {_eatenGhosts} ghosts eaten", 11, BrushKeys.Muted, null);
                Kit.Banner(host, top + 100, RankOf(_score), 14, BrushKeys.Blue, null);
                Kit.Banner(host, top + 126, _signOff, 11, BrushKeys.Muted, null);
                var again = Kit.Banner(host, top + 158, "press R to play again", 12, BrushKeys.Orange, null);
                _again = (TextBlock)again.Child;
            }
            // The prompt breathes rather than blinks: a hard blink at 60 fps is a strobe.
            if (_again != null) _again.Opacity = 0.55 + 0.45 * Kit.Wave(_paint);
        }

        static Rectangle OverlayRect(double w, double h)
        {
            var r = new Rectangle { Width = w, Height = h };
            r.SetResourceReference(Shape.FillProperty, BrushKeys.Veil);
            return r;
        }

        internal static string RankOf(int score)
        {
            string title = Ranks[0].Title;
            foreach (var (threshold, name) in Ranks) if (score >= threshold) title = name;
            return title;
        }
    }
}

