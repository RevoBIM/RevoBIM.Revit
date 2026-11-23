using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.Align3D;
using RevoBIM.UI.Align3D;

namespace RevoBIM.Commands
{
    /// <summary>
    /// 3D Align: centre one pipe, duct, cable tray or conduit on another, in plan. Click a vertical, then another vertical (centred
    /// on it in X and Y) or a horizontal (its centreline run through the vertical's centre); click a horizontal, then a vertical (the
    /// vertical moves onto the horizontal's centreline). Nothing changes height or fall. Pre-select the first element to skip the
    /// first click. Keeps going until Escape. Port of the pyRevit tool (version 1.0.0); code in Tools\Align3D\, windows in UI\Align3D\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class Align3DCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "starting up";
            try
            {
                UIApplication uiapp = data.Application;
                if (uiapp.ActiveUIDocument == null)
                {
                    TaskDialog.Show("RevoBIM 3D Align", "Open a project first.");
                    return Result.Cancelled;
                }
                stage = "reading the settings";
                Dictionary<string, string> settings = A3dSettings.Load();
                var log = new A3dLog(A3dSettings.IsOn(settings, "debug"));
                stage = "running";
                List<A3dRow> rows = A3dEngine.Run(uiapp, settings, log);
                if (A3dEngine.ShouldShow(rows, A3dSettings.Get(settings, "show_results")))
                {
                    stage = "showing the results";
                    A3dWindows.ShowResults(rows, settings, uiapp);
                }
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                Align3DReport.Show(stage, err.ToString());
                return Result.Failed;
            }
        }
    }

    /// <summary>The 3D Align settings window, on its own button (pyRevit: Shift+Click on 3D Align).</summary>
    [Transaction(TransactionMode.Manual)]
    public class Align3DSettingsCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            try
            {
                A3dWindows.ShowSettings(data.Application, null);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                Align3DReport.Show("showing the settings", err.ToString());
                return Result.Failed;
            }
        }
    }

    internal static class Align3DReport
    {
        /// <summary>Says which stage failed, on screen and on disk.</summary>
        public static void Show(string stage, string text)
        {
            string message = "3D Align stopped while " + stage + ".\n\n" + text;
            try
            {
                Directory.CreateDirectory(A3dSettings.DataDir());
                File.WriteAllText(A3dSettings.ErrorPath(), message + "\n\n" + A3dSettings.BuildInfo(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
            try
            {
                TaskDialog.Show("3D Align", message);
            }
            catch (Exception)
            {
            }
        }
    }
}
