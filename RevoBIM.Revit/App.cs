using System;
using System.IO;
using System.Reflection;
using System.Windows.Media.Imaging;
using Autodesk.Revit.UI;

namespace RevoBIM
{
    /// <summary>Entry point: builds the RevoBIM ribbon tab when Revit starts.</summary>
    public class App : IExternalApplication
    {
        private const string TabName = "RevoBIM";

        public Result OnStartup(UIControlledApplication app)
        {
            try { app.CreateRibbonTab(TabName); } catch (Exception) { /* tab already exists */ }

            string dll = Assembly.GetExecutingAssembly().Location;

            // --- Project (pyRevit: Project.panel)
            RibbonPanel project = app.CreateRibbonPanel(TabName, "Project");
            var legendCreator = new PushButtonData(
                "RevoBIM_LegendCreator", "Legend\nCreator", dll, typeof(Commands.LegendCreatorCommand).FullName)
            {
                ToolTip = "Builds legends from the model. Family Legend lists the family types placed in the " +
                          "project, per category or combined. System Colour Legend builds Containment, Ductwork " +
                          "and Pipework colour keys from filter and system overrides. Debug tick for a pasteable report.",
                AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                LargeImage = Icon("LegendCreator", 32),
                Image = Icon("LegendCreator", 16),
            };
            project.AddItem(legendCreator);

            // --- Sheet Tools (pyRevit: Sheet Tools.panel)
            RibbonPanel sheetTools = app.CreateRibbonPanel(TabName, "Sheet Tools");
            var proSheets = new PushButtonData(
                "RevoBIM_ProSheetsExporter", "Pro Sheets\nExporter", dll, typeof(Commands.ProSheetsExporterCommand).FullName)
            {
                ToolTip = "RevoBIM Pro Sheets Exporter. Batch export sheets and views to PDF and DWG with custom file " +
                          "naming built from sheet parameters, output folders driven by project parameters, and export " +
                          "templates saved per project.\n\nOpens modeless, so Revit stays usable while it is open. Sheets " +
                          "selected before launching arrive already isolated on the first page.",
                AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                LargeImage = Icon("ProSheetsExporter", 32),
                Image = Icon("ProSheetsExporter", 16),
            };
            sheetTools.AddItem(proSheets);
            var revisionManager = new PushButtonData(
                "RevoBIM_RevisionManager", "Revision\nManager", dll, typeof(Commands.RevisionManagerCommand).FullName)
            {
                ToolTip = "RevoBIM Revision Manager. Add, edit, reorder, merge and delete the project's revisions, with " +
                          "how many sheets use each one, a search on every column, and columns of your own such as " +
                          "Revision notes - kept in the model and pushed into sheet or revision cloud parameters if you " +
                          "map them.\n\nNothing is written until Apply. Also opens from the Document Register tab in " +
                          "Pro Sheets Exporter.",
                AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                LargeImage = Icon("RevisionManager", 32),
                Image = Icon("RevisionManager", 16),
            };
            sheetTools.AddItem(revisionManager);

            return Result.Succeeded;
        }

        public Result OnShutdown(UIControlledApplication app) => Result.Succeeded;

        /// <summary>
        /// A tool's ribbon icon from Resources\&lt;tool&gt;\icon.png (embedded), or
        /// icon.dark.png when Revit's UI theme is dark. Null if it cannot be read,
        /// so a missing icon never stops the ribbon loading.
        /// </summary>
        private static BitmapImage Icon(string tool, int size)
        {
            try
            {
                string file = IsDarkUi() ? "icon.dark.png" : "icon.png";
                string name = "RevoBIM.Resources." + tool + "." + file;
                Assembly assembly = Assembly.GetExecutingAssembly();
                // A tool with no dark icon (the pyRevit original had none) uses its light one.
                using (Stream stream = assembly.GetManifestResourceStream(name)
                                       ?? assembly.GetManifestResourceStream("RevoBIM.Resources." + tool + ".icon.png"))
                {
                    if (stream == null) return null;
                    var image = new BitmapImage();
                    image.BeginInit();
                    image.StreamSource = stream;
                    image.DecodePixelWidth = size;
                    image.DecodePixelHeight = size;
                    image.CacheOption = BitmapCacheOption.OnLoad;
                    image.EndInit();
                    image.Freeze();
                    return image;
                }
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static bool IsDarkUi()
        {
            try
            {
                return UIThemeManager.CurrentTheme == UITheme.Dark;
            }
            catch (Exception)
            {
                return false;
            }
        }
    }
}
