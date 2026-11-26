using System;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.PanelTemplateManager;
using RevoBIM.UI.PanelTemplateManager;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Panel Template Mngr (the Panel Schedule Template Manager): every panel in the project in one table with the panel schedule template it is using and
    /// parameter columns you choose, swap templates by hand or with Auto Assign (ways x phases), plus a Template Duplicator tab. Port of the pyRevit tool (version
    /// 1.9.0; 1.10.0 here moves its dark theme onto the slate shared by the other RevoBIM tools). Modeless; every write goes through an ExternalEvent. Staged like
    /// script.py: a failure names its stage, shows the text and writes it to %APPDATA%\RevoBIM\pstm_last_error.txt. Code in Tools\PanelTemplateManager\, windows in
    /// UI\PanelTemplateManager\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class PanelTemplateManagerCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "starting up";
            try
            {
                UIApplication uiapp = data.Application;
                stage = "reaching Revit";
                UIDocument uidoc = uiapp.ActiveUIDocument;
                if (uidoc == null || uidoc.Document == null)
                {
                    Report("open", "There is no open project in Revit.");
                    return Result.Failed;
                }
                PstmWindow existing = PstmWindow.Active;
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
                        PstmWindow.Active = null;
                    }
                }
                stage = "read the project";
                var window = new PstmWindow(uiapp, uidoc.Document);
                PstmWindow.Active = window;
                stage = "show its window";
                window.Show();
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                PstmWindow.Active = null;
                PstmCore.Log("error at stage '" + stage + "': " + err);
                Report(stage, err.ToString());
                return Result.Failed;
            }
        }

        /// <summary>Says why, on screen and on disk, rather than leaving a window that never opens.</summary>
        private static void Report(string stage, string detail)
        {
            string text = "RevoBIM Panel Template Mngr could not " + stage + ".\n\n" + detail;
            try
            {
                Directory.CreateDirectory(PstmCore.SettingsDir());
                File.WriteAllText(PstmCore.ErrorPath(), text + "\n\n" + PstmCore.BuildInfo(), new UTF8Encoding(false));
                text += "\n\nSaved to:\n" + PstmCore.ErrorPath();
            }
            catch (Exception)
            {
            }
            try
            {
                new TaskDialog("RevoBIM Panel Template Mngr") { MainContent = text.Length > 1800 ? text.Substring(0, 1800) : text }.Show();
            }
            catch (Exception)
            {
            }
        }
    }
}
