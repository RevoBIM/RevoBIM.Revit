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
                using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
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
