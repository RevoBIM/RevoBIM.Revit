using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.MatchOffset;
using RevoBIM.UI.MatchOffset;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Match Offset Bottom / Middle / Top: pick the element to take the offset from, then pick elements to put on it;
    /// Escape finishes. No window at all while it runs: the status prompt along the bottom of Revit is its only voice.
    /// Port of the pyRevit tool (version 1.18.0), staged like script.py: a failure names its stage, shows the text and
    /// writes it to %APPDATA%\RevoBIM\match_offset_last_error.txt. Code in Tools\MatchOffset\, windows in UI\MatchOffset\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class MatchOffsetBottomCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            return MatchOffsetRunner.RunAnchor(data, MoCore.AnchorBottom);
        }
    }

    [Transaction(TransactionMode.Manual)]
    public class MatchOffsetMiddleCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            return MatchOffsetRunner.RunAnchor(data, MoCore.AnchorMiddle);
        }
    }

    [Transaction(TransactionMode.Manual)]
    public class MatchOffsetTopCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            return MatchOffsetRunner.RunAnchor(data, MoCore.AnchorTop);
        }
    }

    /// <summary>Match Offset Slope: click the main, then click branches; each branch run goes onto the main's fall and lands on its centreline.</summary>
    [Transaction(TransactionMode.Manual)]
    public class MatchOffsetSlopeCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            return MatchOffsetRunner.RunSlope(data);
        }
    }

    /// <summary>Match Offset Settings: rounding, what can be picked, how results are reported, and the keyboard shortcuts.</summary>
    [Transaction(TransactionMode.Manual)]
    public class MatchOffsetSettingsCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            return MatchOffsetRunner.RunSettings(data);
        }
    }

    internal static class MatchOffsetRunner
    {
        /// <summary>Say where it died, in a dialog and on disk.</summary>
        private static void ReportFailure(string stage, string detail)
        {
            try
            {
                MoCore.Log("failed while " + stage + ": " + detail);
                MoCore.FlushLog();
            }
            catch (Exception)
            {
            }
            string text = "RevoBIM Match Offset failed while " + stage + ".\n\n" + detail;
            try
            {
                MoCore.EnsureDir();
                File.WriteAllText(MoCore.ErrorPath(), text, new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
            try
            {
                new TaskDialog("RevoBIM Match Offset") { MainInstruction = "Failed while " + stage, MainContent = detail }.Show();
            }
            catch (Exception)
            {
            }
        }

        private static void ClearFailure()
        {
            try
            {
                if (File.Exists(MoCore.ErrorPath())) File.Delete(MoCore.ErrorPath());
            }
            catch (Exception)
            {
            }
        }

        /// <summary>The results window unless the run is meant to be silent, then the debug report when its tick is on.</summary>
        private static void ShowOutcome(MoRunResult run, string label, UIApplication uiapp)
        {
            if (MoCore.IsSilent(run.Settings)) return;
            try
            {
                if (run.Report.ShouldShow(MoCore.Get(run.Settings, "show_results")))
                    MoResultsWindow.Show(run.Report, run.Settings, label, uiapp);
            }
            catch (Exception err)
            {
                MoCore.Log("results window failed: " + err.Message);
            }
            if (run.Report.Debug == null) return;
            try
            {
                MoDebugWindow.Show(run.Report.Debug, run.Settings, uiapp);
            }
            catch (Exception err)
            {
                MoCore.Log("debug window failed: " + err.Message);
                try
                {
                    run.Report.Debug.Save();
                }
                catch (Exception)
                {
                }
            }
        }

        public static Result RunAnchor(ExternalCommandData data, string anchor)
        {
            string stage = "starting up";
            try
            {
                UIApplication uiapp = data.Application;
                stage = "reading the project";
                if (uiapp.ActiveUIDocument == null)
                {
                    ReportFailure(stage, "There is no open project.");
                    return Result.Failed;
                }

                stage = "picking elements";
                MoRunResult run = MoRun.Run(uiapp, anchor);

                stage = "showing the results";
                ShowOutcome(run, MoCore.AnchorLabel(anchor), uiapp);
                ClearFailure();
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                ReportFailure(stage, err.ToString());
                return Result.Failed;
            }
        }

        public static Result RunSlope(ExternalCommandData data)
        {
            string stage = "starting up";
            try
            {
                UIApplication uiapp = data.Application;
                stage = "reading the project";
                if (uiapp.ActiveUIDocument == null)
                {
                    ReportFailure(stage, "There is no open project.");
                    return Result.Failed;
                }

                stage = "picking pipes";
                MoRunResult run = MosRun.Run(uiapp);

                stage = "showing the results";
                ShowOutcome(run, "Slope", uiapp);
                ClearFailure();
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                ReportFailure(stage, err.ToString());
                return Result.Failed;
            }
        }

        public static Result RunSettings(ExternalCommandData data)
        {
            string stage = "starting up";
            try
            {
                stage = "showing the window";
                new MoSettingsWindow(data.Application).Show();
                ClearFailure();
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                ReportFailure(stage, err.ToString());
                return Result.Failed;
            }
        }
    }
}
