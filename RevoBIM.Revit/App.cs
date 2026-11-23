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

            // --- Coordination (pyRevit: Coordination.panel). Routines is a dropdown that will collect
            //     the routine tools as they are converted; RevoBIM Arcade is its first member.
            RibbonPanel coordination = app.CreateRibbonPanel(TabName, "Coordination");
            var findInView = new PushButtonData(
                "RevoBIM_FindInView", "Find in\nView", dll, typeof(Commands.FindInViewCommand).FullName)
            {
                ToolTip = "Select one or more elements, then pick the view you want them in. Narrow the list by view " +
                          "type and by keyword - the search covers the view name, type, sheet and scale at once. " +
                          "Show Me opens the view and zooms to the selection. If the selection is already drawn in " +
                          "the plan you are in, it just zooms there. With nothing selected, type an element id.",
                LargeImage = Icon("FindInView", 32),
                Image = Icon("FindInView", 16),
            };
            coordination.AddItem(findInView);

            // Match Offset (pyRevit: Match Offset.pulldown): take the bottom, middle or top offset off one element and put the
            // elements clicked next on the same offset. Bottom, Middle and Top open no window; give them keyboard shortcuts.
            var matchOffset = new PulldownButtonData("RevoBIM_MatchOffset", "Match\nOffset")
            {
                ToolTip = "Take the top, middle or bottom offset off one element and put the next elements you click on the same offset.",
                LargeImage = Icon("MatchOffset", 32),
                Image = Icon("MatchOffset", 16),
            };
            var matchOffsetButton = coordination.AddItem(matchOffset) as PulldownButton;
            if (matchOffsetButton != null)
            {
                matchOffsetButton.AddPushButton(new PushButtonData(
                    "RevoBIM_MatchOffsetBottom", "Match Offset Bottom", dll, typeof(Commands.MatchOffsetBottomCommand).FullName)
                {
                    ToolTip = "Match Offset Bottom. First click takes the bottom offset off an element; every click after it puts that " +
                              "element's bottom on the same offset. Escape finishes. Give it a keyboard shortcut and the whole tool is keys, click, click.",
                    LargeImage = Icon("MatchOffsetBottom", 32),
                    Image = Icon("MatchOffsetBottom", 16),
                });
                matchOffsetButton.AddPushButton(new PushButtonData(
                    "RevoBIM_MatchOffsetMiddle", "Match Offset Middle", dll, typeof(Commands.MatchOffsetMiddleCommand).FullName)
                {
                    ToolTip = "Match Offset Middle. First click takes the middle offset off an element; every click after it puts that " +
                              "element's middle on the same offset. Escape finishes. Give it a keyboard shortcut and the whole tool is keys, click, click.",
                    LargeImage = Icon("MatchOffsetMiddle", 32),
                    Image = Icon("MatchOffsetMiddle", 16),
                });
                matchOffsetButton.AddPushButton(new PushButtonData(
                    "RevoBIM_MatchOffsetTop", "Match Offset Top", dll, typeof(Commands.MatchOffsetTopCommand).FullName)
                {
                    ToolTip = "Match Offset Top. First click takes the top offset off an element; every click after it puts that " +
                              "element's top on the same offset. Escape finishes. Give it a keyboard shortcut and the whole tool is keys, click, click.",
                    LargeImage = Icon("MatchOffsetTop", 32),
                    Image = Icon("MatchOffsetTop", 16),
                });
                matchOffsetButton.AddPushButton(new PushButtonData(
                    "RevoBIM_MatchOffsetSlope", "Match Offset Slope", dll, typeof(Commands.MatchOffsetSlopeCommand).FullName)
                {
                    ToolTip = "Match Offset Slope. First click takes the fall and elevation off a main; every click after it puts a branch run " +
                              "on that fall and lands it on the main's centreline where the two cross in plan, then trims and fits it. " +
                              "For connecting an existing drainage run into a main.",
                    LargeImage = Icon("MatchOffsetSlope", 32),
                    Image = Icon("MatchOffsetSlope", 16),
                });
                matchOffsetButton.AddPushButton(new PushButtonData(
                    "RevoBIM_MatchOffsetSettings", "Match Offset Settings", dll, typeof(Commands.MatchOffsetSettingsCommand).FullName)
                {
                    ToolTip = "Rounding, what can be picked, how results are reported, and a one press mapping of the commands onto keyboard shortcuts.",
                    AvailabilityClassName = typeof(Commands.AlwaysAvailable).FullName,
                    LargeImage = Icon("MatchOffsetSettings", 32),
                    Image = Icon("MatchOffsetSettings", 16),
                });
            }

            // Model Tools: tools that change the model geometry. 3D Align and its settings are the first members.
            var modelTools = new PulldownButtonData("RevoBIM_ModelTools", "Model\nTools")
            {
                ToolTip = "Tools that change the geometry of the model.",
                LargeImage = Icon("ModelTools", 32),
                Image = Icon("ModelTools", 16),
            };
            var modelToolsButton = coordination.AddItem(modelTools) as PulldownButton;
            if (modelToolsButton != null)
            {
                modelToolsButton.AddPushButton(new PushButtonData(
                    "RevoBIM_Align3D", "3D Align", dll, typeof(Commands.Align3DCommand).FullName)
                {
                    ToolTip = "Centre one pipe, duct, cable tray or conduit on another, in plan.\n\n" +
                              "Click a vertical, then: another vertical is centred on it in X and Y; a horizontal has its centreline " +
                              "run through the vertical's centre. Click a horizontal, then a vertical: the vertical moves onto the " +
                              "horizontal's centreline. Nothing changes height or fall. Pre-select the first element to skip the " +
                              "first click. Keeps going until Escape.",
                    AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                    LargeImage = Icon("Align3D", 32),
                    Image = Icon("Align3D", 16),
                });
                modelToolsButton.AddPushButton(new PushButtonData(
                    "RevoBIM_Align3DSettings", "3D Align Settings", dll, typeof(Commands.Align3DSettingsCommand).FullName)
                {
                    ToolTip = "3D Align settings: keep going or stop after one, when the results window shows, what to do when " +
                              "Revit will not move an element with its connections, the largest move allowed, and the theme.",
                    AvailabilityClassName = typeof(Commands.AlwaysAvailable).FullName,
                    LargeImage = Icon("Align3DSettings", 32),
                    Image = Icon("Align3DSettings", 16),
                });
            }

            var routines = new PulldownButtonData("RevoBIM_Routines", "Routines")
            {
                ToolTip = "Routine tools.",
                LargeImage = Icon("Routines", 32),
                Image = Icon("Routines", 16),
            };
            var routinesButton = coordination.AddItem(routines) as PulldownButton;
            if (routinesButton != null)
            {
                routinesButton.AddPushButton(new PushButtonData(
                    "RevoBIM_BulkRename", "Bulk\nRename", dll, typeof(Commands.BulkRenameCommand).FullName)
                {
                    ToolTip = "Select views, sheets, schedules or families in the Project Browser, then run this to " +
                              "find and replace, add a prefix or add a suffix, with a live preview. Nothing is " +
                              "written until Apply.\n\nAlso on the right-click menu when several Project Browser " +
                              "items are selected.",
                    AvailabilityClassName = typeof(Commands.AlwaysAvailable).FullName,
                    LargeImage = Icon("BulkRename", 32),
                    Image = Icon("BulkRename", 16),
                });
                routinesButton.AddPushButton(new PushButtonData(
                    "RevoBIM_SheetNamePush", "Sheet Name\nPush", dll, typeof(Commands.SheetNamePushCommand).FullName)
                {
                    ToolTip = "Browse, edit and stamp sheets in one window.\n\nTick sheets, click a row to highlight, Ctrl+click to add to " +
                              "the selection, Shift+click for a range. Double-click a sheet number or name to edit it; edits stage in orange " +
                              "and are only written when Apply Edits is pressed. Sheet numbers already in use are flagged red, with a filter " +
                              "to isolate them.\n\nFind & Replace and Prefix / Suffix stage changes the same way, on the ticked sheets (or " +
                              "everything shown if none are ticked).\n\nPush splits each Sheet Name on \"_\" and writes the three segments to " +
                              "the target parameters set behind the gear icon - BGL_Sheet Title 1 / 2 / 3 by default. The chosen text format " +
                              "is remembered between runs.",
                    AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                    LargeImage = Icon("SheetNamePush", 32),
                    Image = Icon("SheetNamePush", 16),
                });
                routinesButton.AddPushButton(new PushButtonData(
                    "RevoBIM_UnhideInView", "Unhide in\nView", dll, typeof(Commands.UnhideInViewCommand).FullName)
                {
                    ToolTip = "Lists every element hidden in a view (Hide in View > Elements) and every category hidden in it, " +
                              "with a count of hidden elements for every view in the project. Tick elements, categories or whole " +
                              "views and Unhide. Modeless - Revit stays usable while it is open.",
                    AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                    LargeImage = Icon("UnhideInView", 32),
                    Image = Icon("UnhideInView", 16),
                });
                routinesButton.AddPushButton(new PushButtonData(
                    "RevoBIM_Arcade", "RevoBIM\nArcade", dll, typeof(Commands.ArcadeCommand).FullName)
                {
                    ToolTip = "Opens the RevoBIM Arcade: Pacman, Tetris and more.\n\n" +
                              "The arcade is its own Windows program, so it keeps playing while a tool is working " +
                              "and keeps playing if Revit is closed. Revit only starts it. It opens the game you " +
                              "starred as your default, or the game picker.\n\n" +
                              "Three slow clicks on the RevoBIM logo of any RevoBIM tool open it too.",
                    AvailabilityClassName = typeof(Commands.AlwaysAvailability).FullName,
                    LargeImage = Icon("Arcade", 32),
                    Image = Icon("Arcade", 16),
                });
            }

            // Nudge Up / Down / Settings: the pyRevit "stack3" stack, three small buttons.
            string nudgeUpTip = "Raise elements by the Nudge increment (default 50mm). " +
                                "Select elements first to raise them all - press again to raise them again. " +
                                "Run with nothing selected and every element you click rises straight away, " +
                                "until you press Escape. Set the increment with Nudge Settings.";
            string nudgeDownTip = "Lower elements by the Nudge increment (default 50mm). " +
                                  "Select elements first to lower them all - press again to lower them again. " +
                                  "Run with nothing selected and every element you click drops straight away, " +
                                  "until you press Escape. Set the increment with Nudge Settings.";
            var nudgeUp = new PushButtonData("RevoBIM_NudgeUp", "Nudge Up", dll, typeof(Commands.NudgeUpCommand).FullName)
            {
                ToolTip = nudgeUpTip,
                Image = Icon("NudgeUp", 16),
                LargeImage = Icon("NudgeUp", 32),
            };
            var nudgeDown = new PushButtonData("RevoBIM_NudgeDown", "Nudge Down", dll, typeof(Commands.NudgeDownCommand).FullName)
            {
                ToolTip = nudgeDownTip,
                Image = Icon("NudgeDown", 16),
                LargeImage = Icon("NudgeDown", 32),
            };
            var nudgeSettings = new PushButtonData("RevoBIM_NudgeSettings", "Nudge Settings", dll, typeof(Commands.NudgeSettingsCommand).FullName)
            {
                ToolTip = "Set the increment used by Nudge Up and Nudge Down, and how they behave. Default 50mm. " +
                          "Settings are shared by all three buttons and are kept between sessions.",
                AvailabilityClassName = typeof(Commands.AlwaysAvailable).FullName,
                Image = Icon("NudgeSettings", 16),
                LargeImage = Icon("NudgeSettings", 32),
            };
            coordination.AddStackedItems(nudgeUp, nudgeDown, nudgeSettings);

            // --- FAB Automation (pyRevit: FAB Automation.panel)
            RibbonPanel fabAutomation = app.CreateRibbonPanel(TabName, "FAB Automation");
            var hangerAutomation = new PushButtonData(
                "RevoBIM_HangerAutomation", "Hanger\nAutomation", dll, typeof(Commands.HangerAutomationCommand).FullName)
            {
                ToolTip = "Fabrication and family hangers - place, size, re-align and extend hangers on duct runs, " +
                          "with DW/144 spacing and chained dimensions.",
                AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                LargeImage = Icon("HangerAutomation", 32),
                Image = Icon("HangerAutomation", 16),
            };
            fabAutomation.AddItem(hangerAutomation);

            // --- Management (pyRevit: Management.panel)
            RibbonPanel management = app.CreateRibbonPanel(TabName, "Management");
            var excelForRevit = new PushButtonData(
                "RevoBIM_ExcelForRevit", "Excel for\nRevit", dll, typeof(Commands.ExcelForRevitCommand).FullName)
            {
                ToolTip = "Opens the active or selected schedule as an editable spreadsheet grid. Instance parameter " +
                          "cells are blue, type parameter cells orange, cells that cannot be edited light red. Copy, " +
                          "paste, fill down, drag to sequence, formulas, numbering, prefixes, highlighting, find and " +
                          "replace, undo and redo, with a dark or light canvas. Export to Excel for editing or for " +
                          "issuing, and import an edited workbook back. Nothing is written to the model until APPLY, " +
                          "which runs every edit in one transaction.",
                AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                LargeImage = Icon("ExcelForRevit", 32),
                Image = Icon("ExcelForRevit", 16),
            };
            management.AddItem(excelForRevit);

            var filterManager = new PushButtonData(
                "RevoBIM_FilterManager", "Filter\nManager", dll, typeof(Commands.FilterManagerCommand).FullName)
            {
                ToolTip = "RevoBIM Filter Manager. Tab 1 lists every view filter in the project and exposes its categories " +
                          "and rules for editing, with Create, Duplicate and Delete. Tab 2 is a table of every filter at once " +
                          "with Excel export and import. Tab 3 is the Filter Pusher: push filters and their graphic override " +
                          "settings from one host view template, or from the project's filter table, into any number of " +
                          "target view templates and views. Every change is logged.",
                AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                LargeImage = Icon("FilterManager", 32),
                Image = Icon("FilterManager", 16),
            };
            management.AddItem(filterManager);

            var modelCleanup = new PushButtonData(
                "RevoBIM_ModelCleanup", "Model\nCleanup", dll, typeof(Commands.ModelCleanupCommand).FullName)
            {
                ToolTip = "Model Cleanup. Sync the model, save a detached copy, then remove links, unplaced views " +
                          "and purge the copy ready to send. The live model is never cleaned.",
                AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                LargeImage = Icon("ModelCleanup", 32),
                Image = Icon("ModelCleanup", 16),
            };
            management.AddItem(modelCleanup);

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

            // --- "RevoBIM" panel on the Modify tab, shown only while a sheet or view is selected.
            //     Built here with the normal API on the RevoBIM tab, then moved across by
            //     UI\Ribbon\ModifyTabPanel.cs: Revit's API cannot add to the Modify tab itself.
            RibbonPanel modifyPanel = app.CreateRibbonPanel(TabName, UI.Ribbon.ModifyTabPanel.PanelName);
            modifyPanel.AddItem(new PushButtonData(
                "RevoBIM_ProSheetsExporter_Modify", "Pro Sheets\nExporter", dll, typeof(Commands.ProSheetsExporterCommand).FullName)
            {
                ToolTip = proSheets.ToolTip,
                AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                LargeImage = Icon("ProSheetsExporter", 32),
                Image = Icon("ProSheetsExporter", 16),
            });
            modifyPanel.AddItem(new PushButtonData(
                "RevoBIM_RevisionManager_Modify", "Revision\nManager", dll, typeof(Commands.RevisionManagerCommand).FullName)
            {
                ToolTip = revisionManager.ToolTip,
                AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                LargeImage = Icon("RevisionManager", 32),
                Image = Icon("RevisionManager", 16),
            });

            // --- "Nudge" panel on the Modify tab, shown only while model elements are selected:
            //     Nudge Up and Nudge Down.
            RibbonPanel nudgePanel = app.CreateRibbonPanel(TabName, UI.Ribbon.ModifyTabPanel.NudgePanelName);
            nudgePanel.AddItem(new PushButtonData(
                "RevoBIM_NudgeUp_Modify", "Nudge\nUp", dll, typeof(Commands.NudgeUpCommand).FullName)
            {
                ToolTip = nudgeUpTip,
                LargeImage = Icon("NudgeUp", 32),
                Image = Icon("NudgeUp", 16),
            });
            nudgePanel.AddItem(new PushButtonData(
                "RevoBIM_NudgeDown_Modify", "Nudge\nDown", dll, typeof(Commands.NudgeDownCommand).FullName)
            {
                ToolTip = nudgeDownTip,
                LargeImage = Icon("NudgeDown", 32),
                Image = Icon("NudgeDown", 16),
            });
            UI.Ribbon.ModifyTabPanel.Install(app, TabName);

            // --- About: always the last panel, on the right of the tab. Build version and release date.
            RibbonPanel about = app.CreateRibbonPanel(TabName, "About");
            about.AddItem(new PushButtonData(
                "RevoBIM_About", "About", dll, typeof(Commands.AboutCommand).FullName)
            {
                ToolTip = "RevoBIM Tools: the build version installed and the date it was released.",
                AvailabilityClassName = typeof(Commands.AlwaysAvailable).FullName,
                LargeImage = Icon("About", 32),
                Image = Icon("About", 16),
            });

#if !REVIT2024
            // Right-click menu (Revit 2025+): one creator for every RevoBIM entry, so each shows once:
            // "Open in ProSheets", "Express Export" and, with several items selected, "Run Bulk Rename".
            Commands.RevoBimContextMenu.Register(app);
#endif

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
