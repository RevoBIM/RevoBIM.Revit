using System;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.CircuitManager;
using RevoBIM.UI.CircuitManager;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Circuit Manager: every electrical circuit in one Excel-style table, with Path Mode and Path Offset (and any
    /// writable circuit parameter) editable in bulk. Port of the pyRevit tool (version 1.0.1), staged like script.py:
    /// a failure names its stage, shows the text and writes it to %APPDATA%\RevoBIM\circuit_manager_last_error.txt.
    /// Modeless; writes go through an ExternalEvent. Code in Tools\CircuitManager\, windows in UI\CircuitManager\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class CircuitManagerCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "starting up";
            try
            {
                UIApplication uiapp = data.Application;
                stage = "reaching Revit";
                if (uiapp.ActiveUIDocument == null)
                {
                    Report(stage, "No document is open.");
                    return Result.Failed;
                }

                // one window at a time: bring the open one forward
                CmWindow existing = CmWindow.Current;
                if (existing != null)
                {
                    try
                    {
                        existing.Win.Activate();
                        if (existing.Drawer.Parked) existing.Drawer.Expand();
                        return Result.Succeeded;
                    }
                    catch (Exception)
                    {
                        CmWindow.Current = null;
                    }
                }

                stage = "reading the project and opening the window";
                CmSettings.Log("open: Revit " + uiapp.Application.VersionName + " " + uiapp.Application.VersionBuild + ", " + uiapp.ActiveUIDocument.Document.Title);
                var window = new CmWindow(uiapp);
                CmWindow.Current = window;
                window.Show();
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                CmWindow.Current = null;
                CmSettings.Log("error at stage '" + stage + "': " + err);
                Report(stage, err.ToString());
                return Result.Failed;
            }
        }

        /// <summary>Says which stage failed, on screen and on disk.</summary>
        private static void Report(string stage, string errorText)
        {
            string text = "Circuit Manager could not start.\n\nStage: " + stage + "\n\n" + errorText;
            try
            {
                Directory.CreateDirectory(CmSettings.Dir());
                File.WriteAllText(CmSettings.ErrorPath(), text + "\n\n" + CmSettings.BuildInfo(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
            try
            {
                new TaskDialog("RevoBIM Circuit Manager")
                {
                    MainInstruction = "Circuit Manager could not start",
                    MainContent = text.Length > 1800 ? text.Substring(0, 1800) : text,
                }.Show();
            }
            catch (Exception)
            {
            }
        }
    }
}
