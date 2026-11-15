using System;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.UI.ProSheets;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Express Export, from the right-click menu (Revit 2025+): the sheets selected in
    /// the Project Browser exported with the last Pro Sheets template, no prompts,
    /// a floating progress strip, and the folder opened at the end. See PsExpress.
    /// Staged like ProSheetsExporterCommand, so a failure names the stage it was on.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class ExpressExportCommand : IExternalCommand
    {
        private const string Title = "RevoBIM Express Export";

        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "finding the document";
            try
            {
                UIApplication uiapp = data?.Application;
                if (uiapp == null)
                    throw new InvalidOperationException("Revit did not hand over a UIApplication.");
                UIDocument uidoc = uiapp.ActiveUIDocument;
                if (uidoc == null || uidoc.Document == null)
                    throw new InvalidOperationException("Open a project before running this tool.");
                if (uidoc.Document.IsFamilyDocument)
                    throw new InvalidOperationException("This tool works on projects, not families.");

                stage = "exporting";
                PsExpress.Run(uiapp);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                string detail = err.Message + "\n\n" + err;
                string path = WriteLog("Stage: " + stage + "\n\n" + detail);
                try
                {
                    PsUi.ReportFailure(stage, err);
                    return Result.Failed;
                }
                catch (Exception)
                {
                }
                try
                {
                    string text = "RevoBIM Express Export stopped at \"" + stage + "\".\n\n" + detail +
                                  "\n\nWritten to " + path;
                    TaskDialog.Show(Title, text.Length > 3000 ? text.Substring(0, 3000) : text);
                }
                catch (Exception)
                {
                }
                return Result.Failed;
            }
        }

        private static string WriteLog(string text)
        {
            try
            {
                string folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                                             "RevoBIM", "logs");
                Directory.CreateDirectory(folder);
                string path = Path.Combine(folder, "pro_sheets_express_last_error.txt");
                File.WriteAllText(path, text, new UTF8Encoding(false));
                return path;
            }
            catch (Exception)
            {
                return "(the log file could not be written)";
            }
        }
    }
}
