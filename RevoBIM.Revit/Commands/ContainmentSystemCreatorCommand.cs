using System;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.ContainmentSystemCreator;
using RevoBIM.UI.ContainmentSystemCreator;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Containment System Creator: creates a complete containment service type (cable tray or conduit) in one go by duplicating
    /// an existing "with fittings" type with every fitting type it references, and edits existing ones across all their fittings.
    /// Port of the pyRevit tool (version 1.4.1). The window is modal and every change is one transaction, so a failure rolls the
    /// whole service back. Staged like script.py: a failure names its stage, shows the text and writes it to
    /// %APPDATA%\RevoBIM\containment_system_creator_last_error.txt. Code in Tools\ContainmentSystemCreator\, windows in
    /// UI\ContainmentSystemCreator\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class ContainmentSystemCreatorCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "starting up";
            try
            {
                UIApplication uiapp = data.Application;
                stage = "reaching Revit";
                Document doc = uiapp.ActiveUIDocument == null ? null : uiapp.ActiveUIDocument.Document;
                if (doc == null || doc.IsFamilyDocument)
                {
                    TaskDialog.Show("RevoBIM", "Open a project before running Containment System Creator.");
                    return Result.Cancelled;
                }
                CscLog.Write("open: Revit " + uiapp.Application.VersionName + " " + uiapp.Application.VersionBuild + ", " + doc.Title);
                stage = "reading the model and opening the window";
                new CscWindow(doc, uiapp).ShowDialog();
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                CscLog.Write("error at stage '" + stage + "': " + err);
                Report(stage, err.ToString());
                return Result.Failed;
            }
        }

        private static void Report(string stage, string errorText)
        {
            string text = "Containment System Creator could not start.\n\nStage: " + stage + "\n\n" + errorText;
            try
            {
                Directory.CreateDirectory(CscLog.Dir());
                File.WriteAllText(CscLog.ErrorPath(), text + "\n\n" + CscLog.BuildInfo(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
            try
            {
                new TaskDialog("RevoBIM Containment System Creator")
                {
                    MainInstruction = "Containment System Creator could not start",
                    MainContent = text.Length > 1800 ? text.Substring(0, 1800) : text,
                }.Show();
            }
            catch (Exception)
            {
            }
        }
    }
}
