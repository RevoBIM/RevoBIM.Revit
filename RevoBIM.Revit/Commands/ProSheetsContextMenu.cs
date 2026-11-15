#if !REVIT2024
using System;
using System.IO;
using System.Reflection;
using System.Text;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.UI;

namespace RevoBIM.Commands
{
    /// <summary>
    /// "Print in ProSheets" and "Express Export" at the bottom of Revit's right-click
    /// menu, in the Project Browser and the canvas. Revit 2025+ only: the context
    /// menu API (IContextMenuCreator) arrived in 2025, so this file is not compiled
    /// for Revit 2024.
    ///
    /// Port of ps_context.py, with Express Export added under it. What carries over:
    /// - RegisterContextMenu is on UIApplication from 2025 but only on
    ///   UIControlledApplication from 2026, so on 2025 registration waits for
    ///   ApplicationInitialized, the first moment a UIApplication exists.
    /// - Both entries are always added, never conditionally: Autodesk bug
    ///   REVIT-251042 leaves an empty flyout in the Project Browser when a creator
    ///   adds nothing. The commands say what they found when they run.
    /// - Nothing here may throw into Revit's startup; problems go to a log line in
    ///   %APPDATA%\RevoBIM\logs\pro_sheets_exporter_context_menu.txt.
    /// </summary>
    public sealed class ProSheetsContextMenu : IContextMenuCreator
    {
        public const string PrintText = "Print in ProSheets";
        public const string ExpressText = "Express Export";
        /// <summary>Passed to RegisterContextMenu as the add-in id. Stable and namespaced.</summary>
        public const string AddinId = "RevoBIM.ProSheetsExporter";

        private static bool registered;

        public void BuildContextMenu(ContextMenu menu)
        {
            try
            {
                string assembly = Assembly.GetExecutingAssembly().Location;
                menu.AddItem(new CommandMenuItem(PrintText, typeof(ProSheetsExporterCommand).FullName, assembly));
                menu.AddItem(new CommandMenuItem(ExpressText, typeof(ExpressExportCommand).FullName, assembly));
            }
            catch (Exception err)
            {
                Log("could not add the entries: " + err.Message);
            }
        }

        /// <summary>Called from App.OnStartup. Never throws.</summary>
        public static void Register(UIControlledApplication app)
        {
            try
            {
                LogReset("RevoBIM Pro Sheets Exporter - context menu");
#if REVIT2025
                // 2025: only UIApplication has RegisterContextMenu, and there is none
                // until Revit has finished starting.
                app.ControlledApplication.ApplicationInitialized += (sender, args) =>
                {
                    try
                    {
                        if (registered)
                            return;
                        var uiapp = new UIApplication(sender as Application);
                        uiapp.RegisterContextMenu(AddinId, new ProSheetsContextMenu());
                        registered = true;
                        Log("registered at ApplicationInitialized (Revit 2025)");
                    }
                    catch (Exception err)
                    {
                        Log("the late registration failed: " + err);
                    }
                };
                Log("deferred to ApplicationInitialized, where a UIApplication can be built");
#else
                if (registered)
                    return;
                app.RegisterContextMenu(AddinId, new ProSheetsContextMenu());
                registered = true;
                Log("\"" + PrintText + "\" and \"" + ExpressText + "\" will appear at the bottom of the right " +
                    "click menu in the Project Browser and the canvas.");
#endif
            }
            catch (Exception err)
            {
                Log("registration failed: " + err);
            }
        }

        private static string LogPath()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                                "RevoBIM", "logs", "pro_sheets_exporter_context_menu.txt");
        }

        private static void LogReset(string text)
        {
            try
            {
                if (File.Exists(LogPath()))
                    File.Delete(LogPath());
            }
            catch (Exception)
            {
            }
            Log(text);
        }

        private static void Log(string text)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(LogPath()));
                File.AppendAllText(LogPath(), text + "\n", new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }
    }
}
#endif
