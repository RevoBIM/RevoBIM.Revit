using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.UI.ProSheets;

namespace RevoBIM.Commands
{
    /// <summary>
    /// "Open in ProSheets" from the right-click menu on views: Pro Sheets Exporter opens on the Views
    /// list with only the views selected in the Project Browser showing, and ticked. If the tool is
    /// already open it is brought to that state. Everything else is <see cref="ProSheetsExporterCommand"/>.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class ProSheetsViewsCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            PsWindow.ProSheetsWindow.OpenInViewsRequest = true;
            try
            {
                return new ProSheetsExporterCommand().Execute(data, ref message, elements);
            }
            finally
            {
                PsWindow.ProSheetsWindow.OpenInViewsRequest = false;
            }
        }
    }
}
