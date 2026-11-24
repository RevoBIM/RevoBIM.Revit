using System;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.NumberSequencer;
using RevoBIM.UI.NumberSequencer;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Number Sequencer: numbers every element along a duct, pipe or fabrication system into a parameter you
    /// choose - branches first, then on up the main - and can tag each numbered element. Two tabs: Sequencer
    /// (tab-select or pick systems) and System Selector (every system in the active view, ordered in a table,
    /// isolated and coloured, then Run). Modeless: Revit stays usable behind the window. Port of the pyRevit tool
    /// (version 1.13.2), staged like script.py: a failure names its stage, shows the text and writes it to
    /// %APPDATA%\RevoBIM\number_sequencer_last_error.txt. Code in Tools\NumberSequencer\, windows in UI\NumberSequencer\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class NumberSequencerCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "starting up";
            try
            {
                UIApplication uiapp = data.Application;
                stage = "reaching Revit";
                if (uiapp.ActiveUIDocument == null || uiapp.ActiveUIDocument.Document == null)
                {
                    Report(stage, "No document is open.");
                    return Result.Failed;
                }
                stage = "reading the project and showing the window";
                SequencerWindow.Launch(uiapp);
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
            string text = "RevoBIM Number Sequencer failed while loading (" + stage + ").\n\n" + errorText;
            try
            {
                Directory.CreateDirectory(NsqCore.SettingsDir());
                File.WriteAllText(NsqCore.ErrorPath(), text + "\n\n" + NsqCore.BuildInfo(), new UTF8Encoding(false));
            }
            catch (Exception) { }
            try
            {
                new TaskDialog("RevoBIM Number Sequencer") { MainInstruction = "Number Sequencer could not start", MainContent = text }.Show();
            }
            catch (Exception) { }
        }
    }
}
