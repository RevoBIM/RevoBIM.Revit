using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Commands
{
    /// <summary>Availability for buttons that need no document, such as About: enabled even with nothing open.</summary>
    public class AlwaysAvailable : IExternalCommandAvailability
    {
        public bool IsCommandAvailable(UIApplication app, CategorySet selectedCategories) => true;
    }
}
