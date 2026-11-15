using System;
using System.Collections.Generic;

namespace RevoBIM.Arcade.Games.Tetris
{
    /// <summary>
    /// The rules of Tetris with no drawing and no timing, so they can be checked without a window.
    /// Pieces are 1..7 (I O T S Z J L); a grid cell of 0 is empty. 7-bag randomiser, simple wall kicks,
    /// guideline line-clear scoring (40 / 100 / 300 / 1200 times the level).
    /// </summary>
    public sealed class TetrisModel
    {
        public const int Cols = 10, Rows = 20;

        // Cells of each piece in its box, clockwise rotations built once. Index 1..7.
        static readonly int[] BoxSize = { 0, 4, 2, 3, 3, 3, 3, 3 };   // must come before Shapes: static initialisers run in order
        static readonly (int X, int Y)[][][] Shapes = BuildShapes();

        static (int X, int Y)[][][] BuildShapes()
        {
            var bases = new (int X, int Y)[][]
            {
                new (int, int)[0],
                new[] { (0, 1), (1, 1), (2, 1), (3, 1) },   // I
                new[] { (0, 0), (1, 0), (0, 1), (1, 1) },   // O
                new[] { (1, 0), (0, 1), (1, 1), (2, 1) },   // T
                new[] { (1, 0), (2, 0), (0, 1), (1, 1) },   // S
                new[] { (0, 0), (1, 0), (1, 1), (2, 1) },   // Z
                new[] { (0, 0), (0, 1), (1, 1), (2, 1) },   // J
                new[] { (2, 0), (0, 1), (1, 1), (2, 1) },   // L
            };
            var all = new (int X, int Y)[8][][];
            for (int p = 0; p < 8; p++)
            {
                all[p] = new (int X, int Y)[4][];
                var cells = bases[p];
                for (int r = 0; r < 4; r++)
                {
                    all[p][r] = cells;
                    if (p == 0) continue;
                    int n = BoxSize[p];
                    var turned = new (int X, int Y)[cells.Length];
                    for (int i = 0; i < cells.Length; i++) turned[i] = (n - 1 - cells[i].Y, cells[i].X);   // 90 degrees clockwise
                    cells = turned;
                }
            }
            return all;
        }

        public static (int X, int Y)[] CellsOf(int piece, int rotation) => Shapes[piece][((rotation % 4) + 4) % 4];

        readonly Random _random;
        readonly Queue<int> _bag = new Queue<int>();

        public int[,] Grid { get; } = new int[Rows, Cols];
        public int Piece { get; private set; }
        public int Rotation { get; private set; }
        public int X { get; private set; }
        public int Y { get; private set; }
        public int Next { get; private set; }
        public int Score { get; private set; }
        public int Lines { get; private set; }
        public int Level => Lines / 10 + 1;
        public bool Over { get; private set; }

        public TetrisModel(int? seed = null)
        {
            _random = seed.HasValue ? new Random(seed.Value) : new Random();
            Next = Draw();
            Spawn();
        }

        int Draw()
        {
            if (_bag.Count == 0)
            {
                var pieces = new List<int> { 1, 2, 3, 4, 5, 6, 7 };
                for (int i = pieces.Count - 1; i > 0; i--)
                {
                    int j = _random.Next(i + 1);
                    (pieces[i], pieces[j]) = (pieces[j], pieces[i]);
                }
                foreach (var p in pieces) _bag.Enqueue(p);
            }
            return _bag.Dequeue();
        }

        /// <summary>Puts the next piece at the top. Over becomes true when there is no room for it.</summary>
        public void Spawn()
        {
            Piece = Next;
            Next = Draw();
            Rotation = 0;
            X = (Cols - BoxSize[Piece]) / 2;
            Y = Piece == 1 ? -1 : 0;   // the I piece sits on the second row of its box
            if (!Fits(Piece, Rotation, X, Y)) Over = true;
        }

        public bool Fits(int piece, int rotation, int x, int y)
        {
            foreach (var (cx, cy) in CellsOf(piece, rotation))
            {
                int gx = x + cx, gy = y + cy;
                if (gx < 0 || gx >= Cols || gy < 0 || gy >= Rows) return false;
                if (Grid[gy, gx] != 0) return false;
            }
            return true;
        }

        public bool TryMove(int dx, int dy)
        {
            if (Over || !Fits(Piece, Rotation, X + dx, Y + dy)) return false;
            X += dx; Y += dy;
            return true;
        }

        static readonly (int X, int Y)[] Kicks = { (0, 0), (-1, 0), (1, 0), (0, -1), (-2, 0), (2, 0), (0, 1), (0, 2) };   // the last two: an I piece turning upright at the very top

        /// <summary>Rotates clockwise (direction 1) or back (-1), nudging off a wall or the stack when it can.</summary>
        public bool TryRotate(int direction)
        {
            if (Over) return false;
            int rotation = ((Rotation + direction) % 4 + 4) % 4;
            foreach (var (kx, ky) in Kicks)
            {
                if (!Fits(Piece, rotation, X + kx, Y + ky)) continue;
                Rotation = rotation; X += kx; Y += ky;
                return true;
            }
            return false;
        }

        public bool Grounded => Over || !Fits(Piece, Rotation, X, Y + 1);

        /// <summary>The row the piece would land on if dropped now.</summary>
        public int LandingY()
        {
            int y = Y;
            while (Fits(Piece, Rotation, X, y + 1)) y++;
            return y;
        }

        /// <summary>Drops the piece to the floor, locks it, and returns the lines cleared.</summary>
        public int HardDrop()
        {
            if (Over) return 0;
            int y = LandingY();
            Score += (y - Y) * 2;
            Y = y;
            return Lock();
        }

        /// <summary>Writes the piece into the grid, clears full rows, scores, and brings in the next piece.</summary>
        public int Lock()
        {
            if (Over) return 0;
            foreach (var (cx, cy) in CellsOf(Piece, Rotation)) Grid[Y + cy, X + cx] = Piece;
            int cleared = ClearRows();
            if (cleared > 0)
            {
                int[] award = { 0, 40, 100, 300, 1200 };
                Score += award[cleared] * Level;   // scored at the level the lines were cleared on
                Lines += cleared;
            }
            Spawn();
            return cleared;
        }

        public void AddSoftDrop(int cells) => Score += cells;

        int ClearRows()
        {
            int cleared = 0;
            for (int row = Rows - 1; row >= 0; row--)
            {
                bool full = true;
                for (int c = 0; c < Cols; c++) if (Grid[row, c] == 0) { full = false; break; }
                if (!full) continue;
                for (int r = row; r > 0; r--)
                    for (int c = 0; c < Cols; c++) Grid[r, c] = Grid[r - 1, c];
                for (int c = 0; c < Cols; c++) Grid[0, c] = 0;
                cleared++;
                row++;   // the rows moved down; look at this one again
            }
            return cleared;
        }

        /// <summary>Seconds per gravity step at the current level.</summary>
        public double FallInterval => Math.Max(0.05, 0.8 * Math.Pow(0.85, Level - 1));
    }
}

