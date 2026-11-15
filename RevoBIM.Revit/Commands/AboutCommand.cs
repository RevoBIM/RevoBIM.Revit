using System;
using System.Globalization;
using System.Linq;
using System.Reflection;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Commands
{
    /// <summary>
    /// About: the RevoBIM Tools build version and the date it was released (built).
    /// Both are stamped into the DLL at build time - the version from the project's
    /// &lt;Version&gt;, the date and Revit version as assembly metadata - so they can
    /// never drift from what is actually installed.
    /// </summary>
    [Transaction(TransactionMode.ReadOnly)]
    public class AboutCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            var dialog = new TaskDialog("About RevoBIM Tools")
            {
                MainInstruction = "RevoBIM Tools",
                MainContent = "Build version: " + Version + "\n" +
                              "Released: " + ReleaseDate + "\n" +
                              "For Revit " + (Metadata("RevitVersion") ?? "?"),
                FooterText = "A² Services LTD",
                CommonButtons = TaskDialogCommonButtons.Close,
                DefaultButton = TaskDialogResult.Close,
            };
            dialog.Show();
            return Result.Succeeded;
        }

        /// <summary>The project's &lt;Version&gt;, e.g. 0.2.0.</summary>
        public static string Version
        {
            get
            {
                Assembly assembly = Assembly.GetExecutingAssembly();
                string informational = assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion;
                if (!string.IsNullOrEmpty(informational))
                    return informational.Split('+')[0]; // .NET 8+ appends +<commit>
                return assembly.GetName().Version?.ToString(3) ?? "?";
            }
        }

        /// <summary>The build date as "15 November 2026", or "unknown".</summary>
        public static string ReleaseDate
        {
            get
            {
                string stamp = Metadata("BuildDate");
                if (DateTime.TryParseExact(stamp, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None,
                                           out DateTime date))
                    return date.ToString("d MMMM yyyy", CultureInfo.InvariantCulture);
                return string.IsNullOrEmpty(stamp) ? "unknown" : stamp;
            }
        }

        private static string Metadata(string key)
        {
            return Assembly.GetExecutingAssembly().GetCustomAttributes<AssemblyMetadataAttribute>()
                           .FirstOrDefault(attribute => attribute.Key == key)?.Value;
        }
    }
}
