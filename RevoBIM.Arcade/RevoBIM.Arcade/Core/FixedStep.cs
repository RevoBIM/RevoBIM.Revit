using System;

namespace RevoBIM.Arcade.Core
{
    /// <summary>
    /// Runs game logic on a fixed step while drawing every frame. A game calls
    /// <see cref="Advance"/> with the frame's dt, then draws at <see cref="Alpha"/> (0..1, how far
    /// the frame falls between the last two logic steps). That is what turns a 30-step-a-second
    /// grid game into 60 fps motion without touching its integer arithmetic.
    /// </summary>
    public sealed class FixedStep
    {
        readonly double _step;
        double _accumulated;

        public FixedStep(double stepSeconds)
        {
            if (stepSeconds <= 0) throw new ArgumentOutOfRangeException(nameof(stepSeconds));
            _step = stepSeconds;
        }

        public double Alpha => Math.Min(1.0, _accumulated / _step);

        /// <summary>Runs as many whole steps as dt covers (at most maxSteps) and returns how many ran.</summary>
        public int Advance(double dt, Action tick, int maxSteps = 6)
        {
            _accumulated += dt;
            int ran = 0;
            while (_accumulated >= _step && ran < maxSteps)
            {
                _accumulated -= _step;
                tick();
                ran++;
            }
            // Fell too far behind: drop the backlog rather than racing to catch up.
            if (ran == maxSteps && _accumulated >= _step) _accumulated = 0;
            return ran;
        }
    }
}
