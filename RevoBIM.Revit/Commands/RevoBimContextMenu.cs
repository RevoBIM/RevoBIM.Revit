#if !REVIT2023 && !REVIT2024
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.BulkRename;

namespace RevoBIM.Commands
{
    /// <summary>
    /// RevoBIM's entries at the bottom of Revit's right-click menu, in the Project Browser and the canvas:
    /// "Open in ProSheets" always (on views it opens the Views list filtered to them), "Express Export" when sheets are selected, and "Run Bulk Rename" when any item that
    /// can be renamed (views, sheets, schedules, families, types) is selected. One creator builds all
    /// of them, so the tools show once, together. Revit 2025+ only: the context menu API
    /// (IContextMenuCreator) arrived in 2025, so this file is not compiled for Revit 2024.
    ///
    /// Port of ps_context.py, grown into one menu for every tool. What carries over:
    /// - RegisterContextMenu is on UIApplication from 2025 but only on
    ///   UIControlledApplication from 2026, so on 2025 registration waits for
    ///   ApplicationInitialized, the first moment a UIApplication exists.
    /// - Revit calls BuildContextMenu on every right-click, so the Bulk Rename entry can follow the
    ///   selection. "Open in ProSheets" is always added, never conditionally: Autodesk bug
    ///   REVIT-251042 leaves an empty flyout in the Project Browser when a creator adds nothing.
    /// - Nothing here may throw into Revit; problems go to a log line in
    ///   %APPDATA%\RevoBIM\logs\revobim_context_menu.txt.
    ///
    /// The pyRevit RevoBIM PY extension registers its own "Print in ProSheets" through startup.py. While
    /// that extension is loaded beside this add-in Revit shows both, as two groups with a line between.
    /// That second group is not built here.
    /// </summary>
    public sealed class RevoBimContextMenu : IContextMenuCreator
    {
        public const string OpenText = "Open in ProSheets";
        public const string ExpressText = "Express Export";
        public const string BulkRenameText = "Run Bulk Rename";
        /// <summary>Passed to RegisterContextMenu as the add-in id. Stable and namespaced.</summary>
        public const string AddinId = "RevoBIM.ContextMenu";

        /// <summary>The most items looked at when deciding whether to offer Bulk Rename.</summary>
        private const int SelectionLook = 500;

        private static bool registered;
        private static UIApplication uiapp;

        public void BuildContextMenu(ContextMenu menu)
        {
            try
            {
                string assembly = Assembly.GetExecutingAssembly().Location;
                Scan scan = ScanSelection();
                // Right-clicking views opens Pro Sheets on the Views list, filtered to them.
                string open = scan.Views > 0 && scan.Sheets == 0
                    ? typeof(ProSheetsViewsCommand).FullName
                    : typeof(ProSheetsExporterCommand).FullName;
                menu.AddItem(new CommandMenuItem(OpenText, open, assembly));
                if (scan.Sheets > 0)
                    menu.AddItem(new CommandMenuItem(ExpressText, typeof(ExpressExportCommand).FullName, assembly));
                if (scan.Renamable > 0)
                {
                    var rename = new CommandMenuItem(BulkRenameText, typeof(BulkRenameCommand).FullName, assembly);
                    rename.SetToolTip("Rename the selected Project Browser items: find and replace, add a prefix " +
                                      "or a suffix, with a live preview. Nothing is written until Apply.");
                    menu.AddItem(rename);
                }
            }
            catch (Exception err)
            {
                Log("could not add the entries: " + err.Message);
            }
        }

        /// <summary>What the current selection holds, for choosing which entries to show.</summary>
        private struct Scan
        {
            public int Sheets;
            public int Views;
            public int Renamable;
        }

        /// <summary>
        /// Counts the selected sheets, the selected views (not sheets or templates) and the items Bulk Rename
        /// can rename. When the selection cannot be read, every entry is offered: the command says what it
        /// found when it runs.
        /// </summary>
        private static Scan ScanSelection()
        {
            var scan = new Scan();
            try
            {
                UIApplication app = uiapp;
                if (app == null) return Everything();
                UIDocument uidoc = app.ActiveUIDocument;
                if (uidoc == null) return scan;
                Document doc = uidoc.Document;
                int looked = 0;
                foreach (ElementId id in uidoc.Selection.GetElementIds())
                {
                    if (++looked > SelectionLook) break;
                    Element element = doc.GetElement(id);
                    if (element is ViewSheet) scan.Sheets++;
                    else if (element is View view && !view.IsTemplate) scan.Views++;
                    if (BrnRevit.MakeRow(element) != null) scan.Renamable++;
                }
                return scan;
            }
            catch (Exception err)
            {
                Log("could not read the selection, offering every entry: " + err.Message);
                return Everything();
            }
        }

        private static Scan Everything()
        {
            return new Scan { Sheets = 1, Views = 0, Renamable = 1 };
        }
        /// <summary>Called from App.OnStartup. Never throws.</summary>
        public static void Register(UIControlledApplication app)
        {
            try
            {
                LogReset("RevoBIM context menu");
                // A UIApplication is needed to read the selection when the menu opens, and none exists
                // until Revit has finished starting.
                app.ControlledApplication.ApplicationInitialized += (sender, args) =>
                {
                    try
                    {
                        uiapp = new UIApplication(sender as Application);
#if REVIT2025
                        // 2025: only UIApplication has RegisterContextMenu.
                        if (!registered)
                        {
                            uiapp.RegisterContextMenu(AddinId, new RevoBimContextMenu());
                            registered = true;
                            Log("registered at ApplicationInitialized (Revit 2025)");
                        }
#endif
                    }
                    catch (Exception err)
                    {
                        Log("the late set-up failed: " + err);
                    }
                };
#if REVIT2025
                Log("registration deferred to ApplicationInitialized, where a UIApplication can be built");
#else
                if (registered)
                    return;
                app.RegisterContextMenu(AddinId, new RevoBimContextMenu());
                registered = true;
                Log("\"" + OpenText + "\", \"" + ExpressText + "\" and, with two or more items selected, \"" +
                    BulkRenameText + "\" will appear at the bottom of the right click menu in the Project " +
                    "Browser and the canvas.");
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
                                "RevoBIM", "logs", "revobim_context_menu.txt");
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
