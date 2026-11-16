using System;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.ModelCleanup;
using RevoBIM.UI.ModelCleanup;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Model Cleanup: sync the model, save a detached copy, then remove links, unplaced views and purge the
    /// copy ready to send. The live model is never cleaned. The window is modeless; a second press of the
    /// ribbon button brings it back rather than opening another. Port of the pyRevit tool (version 2.0.0).
    /// Code in Tools\ModelCleanup\, windows in UI\ModelCleanup\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class ModelCleanupCommand : IExternalCommand
    {
        private const string Title = "Model Cleanup";

        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "reading the project";
            try
            {
                UIApplication uiapp = data.Application;
                if (uiapp == null || uiapp.ActiveUIDocument == null)
                {
                    TaskDialog.Show(Title, "Open a model first.");
                    return Result.Cancelled;
                }
                if (uiapp.ActiveUIDocument.Document.IsFamilyDocument)
                {
                    TaskDialog.Show(Title, "Model Cleanup works on project models, not families.");
                    return Result.Cancelled;
                }
                stage = "bringing back the open window";
                if (McuWindow.BringBackExisting()) return Result.Succeeded;
                stage = "building the window";
                var window = new McuWindow(uiapp);
                stage = "showing the window";
                window.Show();
                McuCore.Log("window open (modeless)");
                return Result.Succeeded;
            }
            catch (Exception error)
            {
                Report(stage, error);
                return Result.Failed;
            }
        }

        private static void Report(string stage, Exception error)
        {
            string text = McuCore.FormatException(error);
            McuCore.WriteError(stage, text);
            try
            {
                var dialog = new TaskDialog(Title)
                {
                    MainInstruction = "Model Cleanup stopped while " + stage + ".",
                    MainContent = "The full text is in\n" + McuCore.ErrorPath(),
                    ExpandedContent = text.Length > 3000 ? text.Substring(text.Length - 3000) : text,
                };
                dialog.Show();
            }
            catch (Exception) { }
        }
    }
}
