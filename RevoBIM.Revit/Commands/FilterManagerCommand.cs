using System;
using System.IO;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.FilterManager;
using RevoBIM.UI.FilterManager;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Filter Manager: every view filter in the project (categories and rules, editable), a table of all filters
    /// with Excel import and export, and the Filter Pusher (push filters and their graphics from a view template
    /// or from the project into any number of view templates and views). The window is modeless; a second press of
    /// the ribbon button brings it back rather than opening another. Port of the pyRevit tool (version 3.31.0).
    /// Code in Tools\FilterManager\, windows in UI\FilterManager\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class FilterManagerCommand : IExternalCommand
    {
        private const string Title = "Filter Manager";

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
                    TaskDialog.Show(Title, "Filter Manager works on project models, not families.");
                    return Result.Cancelled;
                }

                string previous = FmCore.CrumbReset();
                string diedAt = FmCore.LastStage(previous);

                // already open? bring it forward rather than opening a second copy
                stage = "checking for an open window";
                FmCore.Crumb("launch: checking for an open window");
                var existing = FmWindowKeeper.Parked();
                if (existing != null)
                {
                    try
                    {
                        existing.Activate();
                        FmCore.Crumb("launch: brought the open window forward");
                        return Result.Succeeded;
                    }
                    catch (Exception) { FmWindowKeeper.Unpark(); }
                }

                stage = "building the window";
                FmCore.Crumb("launch: building the window");
                var window = new FmWindow(uiapp);

                if (!FmWindow.Modeless)
                {
                    stage = "showing the window";
                    FmCore.Crumb("launch: showing the window modally");
                    window.Win.ShowDialog();
                    FmCore.Crumb("launch: modal window closed");
                    return Result.Succeeded;
                }

                stage = "owning the window to Revit";
                FmCore.Crumb("launch: owning the window to Revit");
                FmWindowKeeper.OwnToRevit(window.Win, uiapp);

                FmWindowKeeper.Park(window.Win);
                stage = "showing the window";
                FmCore.Crumb("launch: showing the window");
                window.Win.Show();
                FmCore.Crumb("launch: window shown");

                if (!string.IsNullOrEmpty(diedAt) && diedAt.IndexOf("closed cleanly", StringComparison.Ordinal) < 0 &&
                    diedAt.IndexOf("shown", StringComparison.Ordinal) < 0)
                {
                    try
                    {
                        window.SetStatus("The previous run stopped at: " + diedAt + "   -   see " +
                                         Path.Combine(FmCore.SettingsFolder(), FmCore.BreadcrumbFile));
                    }
                    catch (Exception) { }
                }
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
            string text = error.ToString();
            FmCore.Crumb("launch failed while " + stage + ": " + error.Message);
            try
            {
                var dialog = new TaskDialog(Title)
                {
                    MainInstruction = "Filter Manager " + FmCore.Version + " could not start (while " + stage + ").",
                    MainContent = "Revit " + FmCore.RevitVersion() + "\n\n" + (text.Length > 1500 ? text.Substring(0, 1500) : text),
                    ExpandedContent = text.Length > 3000 ? text.Substring(text.Length - 3000) : text,
                };
                dialog.Show();
            }
            catch (Exception) { }
        }
    }
}
