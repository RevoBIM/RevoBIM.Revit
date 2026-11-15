using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using Autodesk.Revit.DB;
using Application = Autodesk.Revit.ApplicationServices.Application;
using Clipboard = System.Windows.Clipboard;
using Autodesk.Revit.UI;
using RevoBIM.UI.LegendCreator;
using static RevoBIM.Tools.LegendCreator.LgcCore;
using static RevoBIM.Tools.LegendCreator.LgcLogic;

namespace RevoBIM.Tools.LegendCreator
{
    /// <summary>
    /// Legend Creator - the debug report and its window. Shown when Debug is
    /// ticked and on any crash, copied to the clipboard first. Every part is
    /// guarded: it runs when something has already gone wrong.
    /// Port of lgc_report.py. The pyRevit-only lines (pyRevit and Python
    /// engine versions, API-by-name probes) become add-in and assembly lines:
    /// a compiled add-in cannot load at all if a Revit member it uses is gone.
    /// </summary>
    public static class LgcReport
    {
        // Set by the command at the start of a run.
        public static Application App;
        public static Document Doc;

        private static string Row(string label, object value) => "  " + label.PadRight(26) + value;

        private static IEnumerable<string> EnvironmentLines()
        {
            var lines = new List<string>();

            void Add(string label, Func<object> getter)
            {
                object value;
                try
                {
                    value = getter();
                }
                catch (Exception err)
                {
                    value = "unavailable - " + ErrText(err);
                }
                lines.Add(Row(label, value));
            }

            Assembly self = typeof(LgcReport).Assembly;
            Add("Tool", () => "Legend Creator " + LgcCore.Version);
            Add("Revit", () => App.VersionName);
            Add("Revit number / build", () => App.VersionNumber + " / " + App.VersionBuild);
            Add("Revit update", () => App.SubVersionNumber);
            Add("Revit language", () => App.Language);
            Add("Add-in", () => self.GetName().Name + " " + self.GetName().Version);
            Add(".NET", () => RuntimeInformation.FrameworkDescription);
            Add("Windows", () => Environment.OSVersion.VersionString);
            Add("Add-in folder", () => Path.GetDirectoryName(self.Location));
            Add("Document", () => Doc.Title);
            Add("Workshared / cloud", () => Doc.IsWorkshared + " / " + Doc.IsModelInCloud);
            Add("Active view", () => LgcModel.ElementName(Doc.ActiveView) + " (" + Doc.ActiveView.ViewType + ")");
            Add("Legend views", () => new FilteredElementCollector(Doc).OfClass(typeof(View)).Cast<View>()
                                         .Count(v => v.ViewType == ViewType.Legend && !v.IsTemplate));
            Add("Legend components", () => new FilteredElementCollector(Doc)
                                               .OfCategory(BuiltInCategory.OST_LegendComponents)
                                               .WhereElementIsNotElementType().GetElementCount());
            Add("Debug tick", () => DebugOn ? "on" : "off");
            return lines;
        }

        private static IEnumerable<string> ThemeLines()
        {
            string Read(string property)
            {
                try
                {
                    return LgcTheme.ThemeManagerValue(property)?.ToString() ?? "-";
                }
                catch (Exception err)
                {
                    return "MISSING - " + ErrText(err);
                }
            }
            return new[] { Row("UIThemeManager", "canvas " + Read("CurrentCanvasTheme") + ", ui " + Read("CurrentTheme")) };
        }

        private static IEnumerable<string> SettingsLines()
        {
            try
            {
                return File.ReadAllLines(SettingsFile, Encoding.UTF8)
                           .Where(l => l.Trim().Length > 0).Select(l => "  " + l).ToList();
            }
            catch (Exception err)
            {
                return new[] { "  (no settings file - " + ErrText(err) + ")" };
            }
        }

        /// <summary>The whole report as one block of text, most important part first.</summary>
        public static string BuildReport(string reason)
        {
            var output = new List<string>
            {
                "RevoBIM Legend Creator - debug report",
                "Why shown: " + reason,
                "Copy everything in this box and paste it into the chat.",
                "",
            };

            if (!string.IsNullOrEmpty(Crash)) output.AddRange(new[] { "== CRASH", Crash.TrimEnd(), "" });

            output.Add("== Environment");
            output.AddRange(EnvironmentLines());
            output.Add("");
            output.Add("== Revit theme");
            output.AddRange(ThemeLines());
            output.Add("");

            output.Add(string.Format(Inv, "== Errors absorbed ({0} distinct)", Order.Count));
            if (Order.Count == 0) output.Add("  none");
            foreach (var key in Order.Take(250))
                output.Add(string.Format(Inv, "  x{0,-4} {1}: {2}", Absorbed[key], key.Where, key.What));
            if (Order.Count > 250) output.Add(string.Format(Inv, "  ... {0} more", Order.Count - 250));
            output.Add("");

            output.Add("== Settings");
            output.AddRange(SettingsLines());
            output.Add("");
            output.Add("== What happened");
            output.AddRange(Lines);
            output.Add("");
            return string.Join("\n", output);
        }

        /// <summary>Clipboard first - the step most likely to get the report out even if the window fails.</summary>
        public static bool CopyToClipboard(string text)
        {
            for (int attempt = 0; attempt < 3; attempt++)
            {
                try
                {
                    Clipboard.SetText(text);
                    return true;
                }
                catch (Exception)
                {
                    Thread.Sleep(150);
                }
            }
            return false;
        }

        /// <summary>Record a crash, then show it. Always reported, Debug or not.</summary>
        public static void ReportCrash(Exception error, string stage)
        {
            Crash = error.ToString();
            Log("CRASH while trying to " + stage);
            Log(Crash);
            ShowDebugReport("the tool crashed while trying to " + stage, Theme ?? "dark");
        }

        /// <summary>Show the report, copied to the clipboard, saved when Debug is on.</summary>
        public static void ShowDebugReport(string reason, string themeName)
        {
            string report = BuildReport(reason);
            bool copied = CopyToClipboard(report);

            string savedTo = "";
            if (DebugOn)
            {
                try
                {
                    Directory.CreateDirectory(SettingsDir);
                    File.WriteAllText(ReportFile, report, new UTF8Encoding(false));
                    savedTo = ReportFile;
                }
                catch (Exception)
                {
                    savedTo = "";
                }
            }

            string fallback;
            try
            {
                var window = new LegendCreatorDebug(report, themeName, copied, savedTo, !string.IsNullOrEmpty(Crash));
                LgcTheme.ShowOverRevit(window);
                return;
            }
            catch (Exception err)
            {
                fallback = err.ToString();
            }

            string head = report.Length > 1800 ? report.Substring(0, 1800) : report;
            string note = copied
                ? "\n\n... (cut short here)\n\nThe full report is on your clipboard - paste it into the chat."
                : "\n\n... (cut short here)";
            TaskDialog.Show("RevoBIM - Legend Creator - debug",
                            head + note + "\n\nThe report window failed too:\n" +
                            (fallback.Length > 600 ? fallback.Substring(fallback.Length - 600) : fallback));
        }
    }
}
