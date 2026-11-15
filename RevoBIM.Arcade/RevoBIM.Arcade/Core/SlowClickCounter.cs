namespace RevoBIM.Arcade.Core
{
    /// <summary>
    /// The logo easter-egg count, the same rule as the Revit side (egg_hook._Counter):
    /// three SLOW clicks, each 250 ms to 2000 ms after the last. Faster is a double click
    /// and restarts the run; slower and the run has gone cold. A repeated timestamp is the
    /// same physical click seen twice and is ignored. Pure logic: no WPF, so it is testable.
    /// </summary>
    public sealed class SlowClickCounter
    {
        public const int DefaultClicks = 3;
        public const int DefaultGapMinMs = 250;
        public const int DefaultGapMaxMs = 2000;

        readonly int _clicks, _min, _max;
        int _count;
        int? _last;
        int? _stamp;

        public SlowClickCounter(int clicks = DefaultClicks, int gapMinMs = DefaultGapMinMs, int gapMaxMs = DefaultGapMaxMs)
        {
            _clicks = clicks; _min = gapMinMs; _max = gapMaxMs;
        }

        public int Count => _count;

        /// <summary>Feed one click (milliseconds, any monotonic clock). True when the run completes.</summary>
        public bool Click(int timestampMs)
        {
            if (_stamp.HasValue && timestampMs == _stamp.Value) return false;
            _stamp = timestampMs;

            int? gap = _last.HasValue ? timestampMs - _last.Value : (int?)null;
            _last = timestampMs;

            if (gap == null || gap > _max || gap < _min)
            {
                _count = 1;
                return false;
            }

            _count++;
            if (_count >= _clicks)
            {
                _count = 0;
                _last = null;
                return true;
            }
            return false;
        }
    }
}
