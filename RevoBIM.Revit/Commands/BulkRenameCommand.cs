using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.UI.BulkRename;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Bulk Rename: find and replace, add a prefix or add a suffix across the views, sheets, schedules,
    /// families and types selected in the Project Browser, with a live preview. Nothing is written until
    /// Apply. Runs from the ribbon (Coordination, Routines) and from the right-click menu when several
    /// Project Browser items are selected. Port of the pyRevit tool (version 1.1.0).
    /// Code in Tools\BulkRename\, windows in UI\BulkRename\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class BulkRenameCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            return BrnMain.Run(data.Application);
        }
    }
}
