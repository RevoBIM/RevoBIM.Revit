using System;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.FamilyFindReplace;
using RevoBIM.UI.FamilyFindReplace;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Family Find &amp; Replace: swap one loadable family for another across the model, keeping the insertion point,
    /// the instance parameters you choose, the circuits, tags and wires. In a drafting view, import symbols become
    /// detail items. Port of the pyRevit tool (version 1.8.0). The window is modeless, so Revit stays usable; every
    /// model change runs from the window's ExternalEvent, in transactions of its own. Code in Tools\FamilyFindReplace\,
    /// windows in UI\FamilyFindReplace\. A second click brings the open window forward.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class FamilyFindReplaceCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "starting up";
            try
            {
                stage = "reaching Revit";
                UIDocument uidoc = data.Application.ActiveUIDocument;
                if (uidoc == null || uidoc.Document == null)
                {
                    new TaskDialog("RevoBIM Family Find & Replace")
                    {
                        MainInstruction = "No project is open.",
                        MainContent = "Open the model you want to work in and run the tool again.",
                    }.Show();
                    return Result.Failed;
                }
                stage = "opening the window";
                FfrWindow.Launch(data.Application);
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
            string text = "Family Find & Replace could not start.\n\nStage: " + stage + "\n\n" + errorText;
            try
            {
                Directory.CreateDirectory(FfrCore.SettingsDir());
                File.WriteAllText(FfrCore.ErrorPath(), text + "\n\n" + FfrCore.BuildInfo(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
            try
            {
                new TaskDialog("RevoBIM Family Find & Replace")
                {
                    MainInstruction = "Family Find & Replace could not start",
                    MainContent = text,
                }.Show();
            }
            catch (Exception)
            {
            }
        }
    }
}
