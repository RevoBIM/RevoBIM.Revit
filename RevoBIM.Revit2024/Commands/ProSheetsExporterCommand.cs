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
    /// Pro Sheets Exporter: batch export sheets and views to PDF and DWG, with custom
    /// file naming from sheet parameters, parameter-driven output folders and saved
    /// templates per project. Opens modeless: Revit stays fully usable while it is
    /// open, and sheets selected before launching arrive already isolated.
    ///
    /// Port of the pyRevit loader (script.py): the tool is brought up in stages, each
    /// named, so a failure reports the stage it was on rather than a blank window.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class ProSheetsExporterCommand : IExternalCommand
    {
        private const string Title = "RevoBIM Pro Sheets Exporter";

        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "referencing assemblies";
            Action<string, Exception> reporter = null;
            try
            {
                // ps_refs is not ported: the assemblies are referenced at build time.
                stage = "loading the tool";
                reporter = (where, err) => PsUi.ReportFailure(where, err);

                stage = "finding the document";
                UIApplication uiapp = data?.Application;
                if (uiapp == null)
                    throw new InvalidOperationException("Revit did not hand over a UIApplication.");
                UIDocument uidoc = uiapp.ActiveUIDocument;
                if (uidoc == null || uidoc.Document == null)
                    throw new InvalidOperationException("Open a project before running this tool.");
                if (uidoc.Document.IsFamilyDocument)
                    throw new InvalidOperationException("This tool works on projects, not families.");

                // The "checking for an Express print" stage is not ported: it answered
                // Project Browser Pro's Express button (ps_express), and PBP is not
                // converted.

                stage = "building the window";
                PsWindow.Show(uiapp);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                string detail = err.Message + "\n\n" + err;
                string path = WriteLog("Stage: " + stage + "\n\n" + detail);
                if (reporter != null)
                {
                    try
                    {
                        reporter(stage, err);
                        return Result.Failed;
                    }
                    catch (Exception)
                    {
                    }
                }
                Fallback(stage, detail + "\n\nWritten to " + path);
                return Result.Failed;
            }
        }

        /// <summary>Report a failure with no help from the tool's own modules.</summary>
        private static void Fallback(string stage, string detail)
        {
            string text = "RevoBIM Pro Sheets Exporter stopped at \"" + stage + "\".\n\n" + detail;
            try
            {
                TaskDialog.Show(Title, text.Length > 3000 ? text.Substring(0, 3000) : text);
            }
            catch (Exception)
            {
            }
        }

        private static string WriteLog(string text)
        {
            string root;
            try
            {
                root = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            }
            catch (Exception)
            {
                root = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            }
            try
            {
                string folder = Path.Combine(root, "RevoBIM", "logs");
                if (!Directory.Exists(folder))
                    Directory.CreateDirectory(folder);
                string path = Path.Combine(folder, "pro_sheets_exporter_last_error.txt");
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
