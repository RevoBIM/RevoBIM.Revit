using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.MatchOffset
{
    /// <summary>
    /// The debug report: the numbers that produced a move, the case the geometry was classified as and Revit's own
    /// words about why it refused. Written to %AppData%\RevoBIM\match_offset_debug.txt after every run. Port of
    /// mo_debug.py; the header also says which build is loaded.
    /// </summary>
    public sealed class MoRecorder
    {
        public readonly string Tool;
        public readonly List<string> Lines = new List<string>();
        public readonly List<string> Failures = new List<string>();
        public readonly List<string> Exceptions = new List<string>();
        public readonly DateTime Started = DateTime.Now;
        public int Matched, Problems;

        public MoRecorder(string tool = "Match Offset")
        {
            Tool = tool;
        }

        /// <summary>Internal feet as millimetres, which is how it is read on a drawing.</summary>
        public static string Mm(double ft, int places = 1)
        {
            return (ft * MoCore.MmPerFt).ToString("F" + places, System.Globalization.CultureInfo.InvariantCulture);
        }

        public static string Pt(MosPt point, int places = 1)
        {
            if (point == null) return "none";
            return "(" + Mm(point.X, places) + ", " + Mm(point.Y, places) + ", " + Mm(point.Z, places) + ") mm";
        }

        /// <summary>A gradient the way it gets said out loud.</summary>
        public static string Fall(double? grad)
        {
            if (!grad.HasValue) return "none";
            double value = grad.Value;
            if (Math.Abs(value) < 1e-7) return "level";
            return "1 in " + (1.0 / Math.Abs(value)).ToString("F1", System.Globalization.CultureInfo.InvariantCulture) + " " +
                   (value < 0 ? "falling" : "rising") + " (" + value.ToString("+0.000000;-0.000000", System.Globalization.CultureInfo.InvariantCulture) + ")";
        }

        public void Section(string title)
        {
            Lines.Add("");
            Lines.Add(("== " + title + " ").PadRight(66, '='));
        }

        public void Line(string text = "") { Lines.Add(text ?? ""); }

        public void Pair(string key, object value)
        {
            Lines.Add("  " + (key ?? "").PadRight(34) + (value == null ? "" : value.ToString()));
        }

        /// <summary>One of Revit's own failure messages, in Revit's own words.</summary>
        public void Failure(string severity, string description)
        {
            string text = severity + ": " + description;
            Failures.Add(text);
            Lines.Add("  REVIT SAID  " + text);
        }

        public void BlewUp(string where, string detail)
        {
            Exceptions.Add(where + "\n" + detail);
            Lines.Add("  THREW       " + where);
            foreach (string piece in (detail ?? "").Replace("\r\n", "\n").Split('\n')) Lines.Add("              " + piece);
        }

        public void Header(UIApplication uiapp, Document doc, Dictionary<string, string> settings)
        {
            Section("run");
            Pair("tool", Tool);
            Pair("version", MoCore.Version);
            Pair("build", MoCore.BuildInfo());
            Pair("when", Started.ToString("yyyy-MM-dd HH:mm:ss"));
            try
            {
                Pair("Revit", uiapp.Application.VersionNumber + " build " + uiapp.Application.VersionBuild);
            }
            catch (Exception)
            {
                Pair("Revit", "could not be read");
            }
            try
            {
                Pair("document", doc.Title);
                Pair("workshared", doc.IsWorkshared);
            }
            catch (Exception)
            {
                Pair("document", "could not be read");
            }

            Section("settings");
            foreach (string key in MoCore.Defaults.Keys.OrderBy(k => k, StringComparer.Ordinal))
            {
                string value = MoCore.Get(settings, key);
                string mark = value == MoCore.Defaults[key] ? "" : "   <- changed";
                if (key == "categories")
                {
                    value = (value.Length == 0 ? 0 : value.Split('|').Length) + " categories";
                    mark = "";
                }
                Pair(key, value + mark);
            }
        }

        public void Tail(MoReport report)
        {
            Matched = report.Matched;
            Problems = report.Problems.Count;
            Section("result");
            Pair("matched", report.Matched);
            Pair("problems", report.Problems.Count);
            foreach (string text in report.Problems) Line("  PROBLEM     " + text);
            foreach (string text in report.Notes) Line("  note        " + text);
            if (Failures.Count > 0) Pair("Revit failures", Failures.Count);
            Line();
            Line("Copy all of this and send it over.");
        }

        public string Text() { return string.Join("\n", Lines) + "\n"; }

        /// <summary>Also on disk, because a window that is closed is a report lost. Returns the path, or "".</summary>
        public string Save()
        {
            try
            {
                MoCore.EnsureDir();
                string path = MoCore.DebugPath();
                File.WriteAllText(path, Text(), new UTF8Encoding(false));
                return path;
            }
            catch (Exception)
            {
                return "";
            }
        }
    }
}
