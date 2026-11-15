using System;
using System.Collections.Generic;
using System.Linq;

namespace RevoBIM.Arcade.Games.Snake
{
    /// <summary>The rules of Snake, no drawing and no timing, so they can be checked without a window.</summary>
    public sealed class SnakeModel
    {
        public const int Cols = 19, Rows = 21;

        public static readonly (int X, int Y) Up = (0, -1), Down = (0, 1), Left = (-1, 0), Right = (1, 0);

        readonly Random _random;

        /// <summary>Head first.</summary>
        public List<(int X, int Y)> Body { get; private set; }
        /// <summary>Where each segment was before the last step, for smooth drawing.</summary>
        public List<(int X, int Y)> Previous { get; private set; }
        public (int X, int Y) Direction { get; private set; } = Right;
        public (int X, int Y) Wanted { get; private set; } = Right;
        public (int X, int Y) Food { get; internal set; }
        public int Score { get; private set; }
        public bool Over { get; private set; }

        public SnakeModel(int? seed = null)
        {
            _random = seed.HasValue ? new Random(seed.Value) : new Random();
            int middle = Rows / 2;
            Body = new List<(int, int)> { (6, middle), (5, middle), (4, middle) };
            Previous = new List<(int, int)>(Body);
            PlaceFood();
        }

        /// <summary>Asks for a turn. A snake cannot double back on itself.</summary>
        public void Turn((int X, int Y) wanted)
        {
            if (Over) return;
            if (wanted.X + Direction.X == 0 && wanted.Y + Direction.Y == 0) return;
            Wanted = wanted;
        }

        /// <summary>One move. Returns true if the snake ate.</summary>
        public bool Step()
        {
            if (Over) return false;
            Direction = Wanted;
            var head = Body[0];
            var next = (X: head.X + Direction.X, Y: head.Y + Direction.Y);

            // The tail is about to move out of the way, so it is not an obstacle.
            if (next.X < 0 || next.X >= Cols || next.Y < 0 || next.Y >= Rows || Body.Take(Body.Count - 1).Contains(next))
            {
                Over = true;
                return false;
            }

            Previous = new List<(int, int)>(Body);
            Body.Insert(0, next);
            if (next == Food)
            {
                Score += 10;
                PlaceFood();
                return true;
            }
            Body.RemoveAt(Body.Count - 1);
            return false;
        }

        void PlaceFood()
        {
            var free = new List<(int X, int Y)>();
            for (int c = 0; c < Cols; c++)
                for (int r = 0; r < Rows; r++)
                    if (!Body.Contains((c, r))) free.Add((c, r));
            if (free.Count == 0) { Over = true; return; }
            Food = free[_random.Next(free.Count)];
        }
    }
}
