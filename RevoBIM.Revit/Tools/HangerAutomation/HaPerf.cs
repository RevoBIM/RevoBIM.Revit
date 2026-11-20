using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.HangerAutomation
{
    /// <summary>
    /// Lightweight per-phase timing for the debug log (Hanger Automation, family hanger and FAB paths).
    /// One line per hanger ("   timing: place 120 ms, fit 35 ms (rod 20), lock 410 ms (centre 380, bottom 30), commit 90 ms") and one
    /// total line per job. A phase named "a.b" is part of phase "a" and printed in its brackets. Does nothing when the
    /// debug log is off. Jobs run one at a time on Revit's API thread, so the state is static.
    /// </summary>
    public static class HaTiming
    {
        private static bool _on;
        private static readonly List<string> Order = new List<string>();
        private static readonly Dictionary<string, double> Cur = new Dictionary<string, double>(StringComparer.Ordinal);
        private static readonly List<string> TotalOrder = new List<string>();
        private static readonly Dictionary<string, double> Total = new Dictionary<string, double>(StringComparer.Ordinal);
        private static int _count;

        /// <summary>Start of a job: clears the totals; timing is on only when the debug log is.</summary>
        public static void BeginJob(FhaDebugLog log)
        {
            _on = log != null && log.Enabled;
            Order.Clear();
            Cur.Clear();
            TotalOrder.Clear();
            Total.Clear();
            _count = 0;
        }

        /// <summary>A timed phase: <c>using (HaTiming.Time("lock.centre")) { ... }</c>.</summary>
        public static Scope Time(string phase)
        {
            return new Scope(phase);
        }

        public struct Scope : IDisposable
        {
            private readonly string _name;
            private readonly long _t0;

            public Scope(string name)
            {
                _name = _on ? name : null;
                _t0 = _on ? Stopwatch.GetTimestamp() : 0;
            }

            public void Dispose()
            {
                if (_name == null) return;
                Add(_name, (Stopwatch.GetTimestamp() - _t0) * 1000.0 / Stopwatch.Frequency);
            }
        }

        private static void Add(string name, double ms)
        {
            double v;
            if (!Cur.TryGetValue(name, out v)) Order.Add(name);
            Cur[name] = v + ms;
        }

        private static string Line(List<string> order, Dictionary<string, double> vals)
        {
            var tops = new List<string>();
            foreach (string n in order)
            {
                int dot = n.IndexOf('.');
                string top = dot < 0 ? n : n.Substring(0, dot);
                if (!tops.Contains(top)) tops.Add(top);
            }
            var parts = new List<string>();
            foreach (string top in tops)
            {
                double ms;
                var kids = order.Where(n => n.StartsWith(top + ".", StringComparison.Ordinal)).ToList();
                if (!vals.TryGetValue(top, out ms)) ms = kids.Sum(k => vals[k]);
                string s = top + " " + Ms(ms);
                if (kids.Count > 0)
                    s += " (" + string.Join(", ", kids.Select(k => k.Substring(top.Length + 1) + " " + Ms(vals[k], false))) + ")";
                parts.Add(s);
            }
            return string.Join(", ", parts);
        }

        private static string Ms(double ms, bool unit = true)
        {
            return Math.Round(ms).ToString("0", CultureInfo.InvariantCulture) + (unit ? " ms" : "");
        }

        /// <summary>Writes this hanger's phases to the log (one line) and adds them to the job totals.</summary>
        public static void Flush(FhaDebugLog log, string label = null)
        {
            if (!_on || Order.Count == 0) return;
            log.Add("   timing: " + (label != null ? label + ": " : "") + Line(Order, Cur));
            foreach (string n in Order)
            {
                double v;
                if (!Total.TryGetValue(n, out v)) TotalOrder.Add(n);
                Total[n] = v + Cur[n];
            }
            _count++;
            Order.Clear();
            Cur.Clear();
        }

        /// <summary>The job's total line (the measured phases of every hanger flushed so far).</summary>
        public static void EndJob(FhaDebugLog log, string title)
        {
            if (!_on) return;
            Flush(log);
            if (_count == 0) return;
            double sum = 0;
            foreach (string n in TotalOrder)
                if (n.IndexOf('.') < 0) sum += Total[n];
            log.Add("timing total (" + title + "): " + _count.ToString(CultureInfo.InvariantCulture) + " hanger(s), "
                    + Ms(sum) + " measured: " + Line(TotalOrder, Total));
            _on = false;
        }
    }

    /// <summary>Per-job caches of values that cannot change while a job runs (cleared by HfamRevit.LogContext at every job start).</summary>
    public static class HaCache
    {
        public static Document LevelsDoc;
        public static List<HfamRevit.LevelElev> LevelList;
        public static readonly Dictionary<long, Section> Sections = new Dictionary<long, Section>();

        public static void Reset()
        {
            LevelsDoc = null;
            LevelList = null;
            Sections.Clear();
        }
    }
}
