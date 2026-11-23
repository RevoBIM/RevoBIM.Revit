using System;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.UnhideInView;
using RevoBIM.UI.UnhideInView;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Unhide in View: lists the elements hidden in each view (Hide in View > Elements) and the categories hidden in it,
    /// with a count of hidden elements for every view in the project. Tick elements, categories or whole views and Unhide.
    /// Port of the pyRevit tool (version 1.1.0). The window is modeless: every read and write runs in an ExternalEvent, and
    /// one Unhide is one undo step. Code in Tools\UnhideInView\, window in UI\UnhideInView\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class UnhideInViewCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "starting up";
            try
            {
                stage = "reaching Revit";
                if (data.Application.ActiveUIDocument == null)
                {
                    TaskDialog.Show("RevoBIM Unhide in View", "Open a project first.");
                    return Result.Cancelled;
                }
                stage = "opening the window";
                UivWindow.Open(data.Application);
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
                Directory.CreateDirectory(UivCore.SettingsDir());
                File.WriteAllText(UivCore.ErrorPath(), text + "\n\n" + UivCore.BuildInfo(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
            try
            {
                new TaskDialog("RevoBIM Unhide in View")
                {
                    MainInstruction = "Unhide in View stopped while: " + stage,
                    MainContent = "The details are saved in " + UivCore.ErrorPath(),
                    ExpandedContent = text.Length > 3500 ? text.Substring(text.Length - 3500) : text,
                }.Show();
            }
            catch (Exception)
            {
            }
        }
    }
}
