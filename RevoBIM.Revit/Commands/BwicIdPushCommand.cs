using System;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.BwicIdPush;

namespace RevoBIM.Commands
{
    /// <summary>
    /// BWIC ID Push: click a Generic Model element in a linked model (reads CLM_BWIC ID), then an element in this model (writes
    /// BGL_BWIC ID). Repeats until Escape and finishes silently. Port of the pyRevit tool (version 1.2.0); code in Tools\BwicIdPush\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class BwicIdPushCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            try
            {
                UIDocument uidoc = data.Application.ActiveUIDocument;
                if (uidoc == null)
                {
                    TaskDialog.Show("RevoBIM BWIC ID Push", "Open a project first.");
                    return Result.Cancelled;
                }
                BwicIdPushRun.Run(uidoc);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                string text = "BWIC ID Push stopped.\n\n" + err + "\n\n" + BwicIdPushRun.BuildInfo();
                try
                {
                    Directory.CreateDirectory(BwicIdPushRun.DataDir());
                    File.WriteAllText(BwicIdPushRun.ErrorPath(), text, new UTF8Encoding(false));
                }
                catch (Exception)
                {
                }
                TaskDialog.Show("RevoBIM BWIC ID Push", text);
                return Result.Failed;
            }
        }
    }
}
