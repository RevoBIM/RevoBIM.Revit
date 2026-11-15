using System;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.UI.ExcelForRevit;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Excel for Revit: opens the active or selected schedule as an editable spreadsheet grid.
    /// Nothing is written to the model until APPLY, which runs every edit in one transaction.
    /// Port of the pyRevit tool (script.py + efr_core.py), version 1.20.0. The staged flow
    /// (finding the schedule, reading it, building and showing the window) lives in
    /// <see cref="EfrMain.Run"/>; this class only hands over Revit's UIApplication.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class ExcelForRevitCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            try
            {
                return EfrMain.Run(data.Application);
            }
            catch (Exception err)
            {
                // EfrMain reports its own staged failures; this is only the last line of defence.
                try
                {
                    TaskDialog.Show("Excel for Revit", "Excel for Revit could not start.\n\n" + err);
                }
                catch (Exception)
                {
                }
                return Result.Failed;
            }
        }
    }
}
