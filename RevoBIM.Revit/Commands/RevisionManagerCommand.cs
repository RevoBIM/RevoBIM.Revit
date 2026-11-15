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
    /// Revision Manager: manage the project's revisions - add, edit, reorder, merge and delete, with
    /// how many sheets use each one, a search on every column, and columns of your own such as
    /// Revision notes, pushed into sheet or revision cloud parameters if you map them. Opens
    /// modeless: Revit stays fully usable while it is open, and picking a revision cloud in a view
    /// takes the list to its revision. Nothing is written until Apply.
    ///
    /// Port of the Revision Manager button's loader (script.py). The manager is part of Pro Sheets
    /// Exporter (PsRevWin) and this command only opens it on its own. Staged like the Pro Sheets
    /// loader: a failure names the stage it was on rather than leaving a blank window.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class RevisionManagerCommand : IExternalCommand
    {
        private const string Title = "RevoBIM Revision Manager";

        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "finding Pro Sheets Exporter";
            Action<string, Exception> reporter = null;
            try
            {
                // The Python checks the Pro Sheets Exporter folder is there and references its
                // assemblies; both are compiled into this add-in, so those stages cannot fail.
                stage = "referencing assemblies";
                stage = "loading the tool";
                reporter = (failedStage, error) => PsUi.ReportFailure(failedStage, error);

                stage = "finding the document";
                UIApplication uiapp = data?.Application;
                if (uiapp == null)
                    throw new InvalidOperationException("Revit did not hand over a UIApplication.");
                UIDocument uidoc = uiapp.ActiveUIDocument;
                if (uidoc == null || uidoc.Document == null)
                    throw new InvalidOperationException("Open a project before running this tool.");
                if (uidoc.Document.IsFamilyDocument)
                    throw new InvalidOperationException("Revisions belong to projects, not families.");

                stage = "running the Revision Manager";
                // Here, in the command's API context: RunStandalone creates the ExternalEvent the
                // modeless window applies through, and reads the starting selection and sheet.
                PsRevWin.RunStandalone(uiapp);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                string detail = string.Format("{0}\n\n{1}", err.Message, err);
                string path = WriteLog(string.Format("Stage: {0}\n\n{1}", stage, detail));
                if (reporter != null)
                {
                    try
                    {
                        reporter(stage, err);
                        return Result.Cancelled;
                    }
                    catch (Exception)
                    {
                    }
                }
                Fallback(stage, string.Format("{0}\n\nWritten to {1}", detail, path));
                // Cancelled, not Failed: the failure has been reported above, and Failed would have
                // Revit put up an error dialog of its own on top of it.
                return Result.Cancelled;
            }
        }

        private static void Fallback(string stage, string detail)
        {
            string text = string.Format("RevoBIM Revision Manager stopped at \"{0}\".\n\n{1}", stage, detail);
            try
            {
                TaskDialog.Show(Title, text.Length > 3000 ? text.Substring(0, 3000) : text);
                return;
            }
            catch (Exception)
            {
            }
            try
            {
                Console.Error.Write(text);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>%APPDATA%\RevoBIM\logs\revision_manager_last_error.txt, UTF-8 without BOM.
        /// Returns its path, or why it could not be written.</summary>
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
                string path = Path.Combine(folder, "revision_manager_last_error.txt");
                File.WriteAllBytes(path, new UTF8Encoding(false).GetBytes(text));
                return path;
            }
            catch (Exception)
            {
                return "(the log file could not be written)";
            }
        }
    }
}
