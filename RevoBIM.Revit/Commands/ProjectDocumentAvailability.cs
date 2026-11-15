using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Button enabled only with a project document open - the C# form of
    /// pyRevit's "context: doc-project" in bundle.yaml.
    /// </summary>
    public class ProjectDocumentAvailability : IExternalCommandAvailability
    {
        public bool IsCommandAvailable(UIApplication app, CategorySet selectedCategories)
        {
            Document doc = app.ActiveUIDocument?.Document;
            return doc != null && !doc.IsFamilyDocument;
        }
    }
}
