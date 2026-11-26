using System;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.UI;
using RevoBIM.Tools.ViewManager;
using RevoBIM.UI.ViewManager;

namespace RevoBIM.Commands
{
    /// <summary>
    /// View Manager: Create Views (plan views from view templates x levels on one scope box), Dependent Views (dependents from
    /// scope boxes) and the View Reference Manager (every view in one grid, edited and staged, Excel round trip, title and
    /// detail number builders). Port of the pyRevit tool (version 1.13.1). The window is modeless: every read and write runs in
    /// an ExternalEvent. Code in Tools\ViewManager\, windows in UI\ViewManager\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class ViewManagerCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, Autodesk.Revit.DB.ElementSet elements)
        {
            string stage = "starting up";
            try
            {
                stage = "reaching Revit";
                if (data.Application.ActiveUIDocument == null)
                {
                    TaskDialog.Show("RevoBIM View Manager", "Open a project first.");
                    return Result.Cancelled;
                }
                stage = "opening the window";
                VmWindow.Open(data.Application);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                Report(stage, err.ToString());
                return Result.Failed;
            }
        }

        /// <summary>Says which stage failed, on screen and on disk.</summary>
        private static void Report(string stage, string errorText)
        {
            string text = "Stage: " + stage + "\n\n" + errorText;
            try
            {
                File.WriteAllText(VmCore.ErrorPath(), text + "\n\n" + VmCore.BuildInfo(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
            try
            {
                new TaskDialog("RevoBIM View Manager")
                {
                    MainInstruction = "View Manager stopped while: " + stage,
                    MainContent = "The details are saved in " + VmCore.ErrorPath(),
                    ExpandedContent = text.Length > 3500 ? text.Substring(text.Length - 3500) : text,
                }.Show();
            }
            catch (Exception)
            {
            }
        }
    }
}
