using System;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.AddinManager;
using RevoBIM.UI.AddinManager;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Addin Manager: every button any addin has put on Revit's ribbon, in one searchable dockable panel grouped by the
    /// addin's tab. Click to show the panel, click again to hide it. Port of the pyRevit tool "RevoBIM Addin Manager"
    /// (script.py); thin, the work is in Tools\AddinManager and UI\AddinManager.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class AddinManagerCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            string stage = "starting";
            try
            {
                stage = "showing the panel";
                string problem;
                if (!AmDock.Toggle(commandData.Application, out problem) && !string.IsNullOrEmpty(problem)) Report(stage, problem);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                Report(stage, err.ToString());
                return Result.Succeeded;
            }
        }

        /// <summary>Names the stage it failed in, in a dialog and in the last-error file.</summary>
        private static void Report(string stage, string detail)
        {
            string text = "Addin Manager failed while " + stage + ".\n\n" + detail;
            try
            {
                AmCore.EnsureRoot();
                System.IO.File.WriteAllText(AmCore.ErrorPath(), text, new System.Text.UTF8Encoding(false));
            }
            catch (Exception) { }
            AmCore.Log(text);
            try { TaskDialog.Show("Addin Manager", text); } catch (Exception) { }
        }
    }
}
