using System;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.BwicPenetration;
using RevoBIM.UI.BwicPenetration;

namespace RevoBIM.Commands
{
    /// <summary>
    /// BWIC Penetration: Wall, Slab and Global Placement tabs with Family settings, preview, step prompts and a results window.
    /// Port of the pyRevit tool (version 2.21.0). The window is modeless: every run goes through an ExternalEvent, and Esc in Revit
    /// returns to the window. Code in Tools\BwicPenetration\, windows in UI\BwicPenetration\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class BwicPenetrationCommand : IExternalCommand
    {
        // the one open window; a second click on the button brings it forward instead of opening another
        private static BwiMainWindow _open;

        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "starting up";
            try
            {
                stage = "reaching Revit";
                if (data.Application.ActiveUIDocument == null)
                {
                    TaskDialog.Show("RevoBIM BWIC Penetration", "Open a project first.");
                    return Result.Cancelled;
                }
                BwicCore.CurrentApp = data.Application;
                if (_open != null)
                {
                    try
                    {
                        if (_open.Win.IsLoaded)
                        {
                            _open.Drawer.RestoreNow();
                            _open.Win.Activate();
                            return Result.Succeeded;
                        }
                    }
                    catch (Exception) { }
                    _open = null;
                }
                stage = "opening the window";
                var window = new BwiMainWindow(data.Application);
                window.Win.Closed += (s, e) => { if (ReferenceEquals(_open, window)) _open = null; };
                _open = window;
                window.Show();
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
                Directory.CreateDirectory(BwicCore.DataDir());
                File.WriteAllText(BwicCore.ErrorPath(), "bwic_penetration " + BwicCore.ToolVersion + "\n" + text + "\n\n" + BwicCore.BuildInfo(), new UTF8Encoding(false));
            }
            catch (Exception) { }
            try
            {
                new TaskDialog("RevoBIM BWIC Penetration")
                {
                    MainInstruction = "BWIC Penetration stopped while: " + stage,
                    MainContent = "The details are saved in " + BwicCore.ErrorPath(),
                    ExpandedContent = text.Length > 3500 ? text.Substring(text.Length - 3500) : text,
                }.Show();
            }
            catch (Exception) { }
        }
    }
}
