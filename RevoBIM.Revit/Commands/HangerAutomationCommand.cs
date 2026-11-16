using System;
using System.IO;
using System.Runtime.CompilerServices;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.HangerAutomation;
using RevoBIM.UI.HangerAutomation;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Hanger Automation: Fabrication and family hangers - place, size, re-align and extend hangers on duct runs,
    /// with DW/144 spacing and chained dimensions. A modeless window with four tabs (FAB Hangers, Family Hangers,
    /// Family Floor Support, Service Type). Port of the pyRevit tool (version 1.16.0).
    /// Thin staged loader (script.py): a failure names its stage, shows the text and writes it to
    /// %APPDATA%\RevoBIM\hanger_automation_load_error.txt, so there is never a blank window.
    /// Code in Tools\HangerAutomation\, windows in UI\HangerAutomation\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class HangerAutomationCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "assemblies";
            try
            {
                stage = "modules";
                // the Python imported its modules here; touching the static classes surfaces a load failure in this stage
                foreach (Type t in new[] { typeof(FhaCore), typeof(FhaRevit), typeof(HfamCore), typeof(HcircCore), typeof(HsvcCore), typeof(FhaUi) })
                    RuntimeHelpers.RunClassConstructor(t.TypeHandle);
                stage = "window";
                FhaWindow.Show(data.Application);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                Report(stage, err.ToString());
                return Result.Failed;
            }
        }

        private static void Report(string stage, string text)
        {
            string msg = "Failed at stage: " + stage + "\n\n" + text;
            try
            {
                string path = FhaCore.LoadErrorPath();
                string folder = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(folder) && !Directory.Exists(folder)) Directory.CreateDirectory(folder);
                File.WriteAllText(path, msg, new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
            try
            {
                TaskDialog.Show("Hanger Automation", msg);
            }
            catch (Exception)
            {
            }
        }
    }
}
