using System;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.WorksetManagement;
using RevoBIM.UI.WorksetManagement;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Workset Management: manage worksets in a sortable, filterable table (rename in bulk, delete or merge several at once,
    /// create through Excel), see them in a 3D view coloured by workset, work on scope boxes, and assign elements onto worksets
    /// in order - by category or by routine templates built like Revit's view filters. The window is modeless; every model
    /// change runs from its ExternalEvent. Port of the pyRevit tool (version 3.1.0). Code in Tools\WorksetManagement\, windows
    /// in UI\WorksetManagement\. A second press of the ribbon button brings the open window back.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class WorksetManagementCommand : IExternalCommand
    {
        private const string Title = "Workset Management";

        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "reading the document";
            try
            {
                UIApplication uiapp = data.Application;
                UIDocument uidoc = uiapp.ActiveUIDocument;
                if (uidoc == null)
                {
                    Info("Open a project first.");
                    return Result.Cancelled;
                }
                Document document = uidoc.Document;
                if (document.IsFamilyDocument)
                {
                    Info("Worksets live in projects - open a project, not a family.");
                    return Result.Cancelled;
                }
                if (!WsmRevit.IsWorkshared(document))
                {
                    Info("This model is not workshared, so it has no worksets yet.\n\nCollaborate > Collaborate turns worksharing on; then run Workset Management again.");
                    return Result.Cancelled;
                }

                stage = "checking for an open window";
                if (BringForward(document)) return Result.Succeeded;

                stage = "building and showing the window";
                var window = new WsmWindow(uiapp, document);
                window.ShowWindow();
                stage = "finished (v" + WsmCore.Version + ")";
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                Report(stage, err.ToString());
                return Result.Failed;
            }
        }

        /// <summary>The window already open for this model comes to the front. One open on another model is closed (it asks first if anything is staged).</summary>
        private static bool BringForward(Document document)
        {
            try
            {
                WsmWindow existing = WsmWindow.Open;
                if (existing == null || !existing.Window.IsLoaded) return false;
                string here = string.IsNullOrEmpty(document.PathName) ? document.Title : document.PathName;
                string there = string.IsNullOrEmpty(existing.Doc.PathName) ? existing.Doc.Title : existing.Doc.PathName;
                if (here == there)
                {
                    WsmUi.WindowDrawer drawer = WsmUi.DrawerOf(existing.Window);
                    if (drawer != null && drawer.Parked) drawer.Open();
                    existing.Window.Activate();
                    return true;
                }
                existing.Window.Close();
                return existing.Window.IsLoaded;
            }
            catch (Exception) { return false; }
        }

        private static void Info(string text)
        {
            new TaskDialog("RevoBIM - " + Title) { MainContent = text }.Show();
        }

        private static void Report(string stage, string detail)
        {
            string text = Title + " stopped while " + stage + ".\n\n" + detail;
            try
            {
                Directory.CreateDirectory(WsmCore.AppDataDir);
                File.WriteAllText(WsmCore.LoadErrorPath, text + "\n\n" + WsmCore.BuildInfo(), new UTF8Encoding(false));
            }
            catch (Exception) { }
            try { new TaskDialog("RevoBIM - " + Title) { MainInstruction = Title + " could not start", MainContent = text }.Show(); }
            catch (Exception) { }
        }
    }
}
