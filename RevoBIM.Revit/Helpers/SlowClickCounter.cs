namespace RevoBIM.Helpers
{
    /// <summary>
    /// The logo easter-egg count: three SLOW clicks, each 250 ms to 2000 ms after the last. Faster is
    /// a double click and restarts the run; slower and the run has gone cold. A repeated timestamp is
    /// the same physical click seen twice and is ignored. The same rule as the pyRevit egg_hook
    /// counter and as RevoBIM.Arcade's own logo. Pure logic, no WPF.
    /// </summary>
    public sealed class SlowClickCounter
    {
        public const int DefaultClicks = 3;
        public const int DefaultGapMinMs = 250;
        public const int DefaultGapMaxMs = 2000;

        private readonly int clicks;
        private readonly int min;
        private readonly int max;
        private int count;
        private int? last;
        private int? stamp;

        public SlowClickCounter(int clicks = DefaultClicks, int gapMinMs = DefaultGapMinMs, int gapMaxMs = DefaultGapMaxMs)
        {
            this.clicks = clicks;
            min = gapMinMs;
            max = gapMaxMs;
        }

        /// <summary>Feed one click (milliseconds on any monotonic clock). True when the run completes.</summary>
        public bool Click(int timestampMs)
        {
            if (stamp.HasValue && timestampMs == stamp.Value) return false;
            stamp = timestampMs;

            int? gap = last.HasValue ? timestampMs - last.Value : (int?)null;
            last = timestampMs;

            if (gap == null || gap > max || gap < min)
            {
                count = 1;
                return false;
            }

            count++;
            if (count >= clicks)
            {
                count = 0;
                last = null;
                return true;
            }
            return false;
        }
    }
}
