using System;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.UI.FamilyThumbnail;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Family Thumbnail (port of the pyRevit tool, version 1.5.1): three buttons in one pulldown. Update Current makes the thumbnail
    /// of the family open in the Family Editor, Update Batch does it for ticked families of a project and loads them back, Settings
    /// holds the appearance and export options. Flows in UI\FamilyThumbnail\FtFlow.cs, the work in Tools\FamilyThumbnail\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class FamilyThumbnailCurrentCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            try
            {
                FtFlow.UpdateCurrent(data.Application);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                FtFlow.Report("run", err);
                return Result.Failed;
            }
        }
    }

    [Transaction(TransactionMode.Manual)]
    public class FamilyThumbnailBatchCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            try
            {
                FtFlow.UpdateBatch(data.Application);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                FtFlow.Report("run", err);
                return Result.Failed;
            }
        }
    }

    [Transaction(TransactionMode.Manual)]
    public class FamilyThumbnailSettingsCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            try
            {
                FtFlow.Settings(data.Application);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                FtFlow.Report("run", err);
                return Result.Failed;
            }
        }
    }

    /// <summary>Button enabled only while a family is open in the Family Editor: the C# form of pyRevit's "context: doc-family".</summary>
    public class FamilyDocumentAvailability : IExternalCommandAvailability
    {
        public bool IsCommandAvailable(UIApplication app, CategorySet selectedCategories)
        {
            Document doc = app.ActiveUIDocument?.Document;
            return doc != null && doc.IsFamilyDocument;
        }
    }
}
