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

            // Addin Manager's dockable pane: Revit only accepts a registration while it is starting up.
            UI.AddinManager.AmDock.Register(app);

            string dll = Assembly.GetExecutingAssembly().Location;

            // --- Coordination (pyRevit: Coordination.panel). Routines is a dropdown that will collect
            //     the routine tools as they are converted; RevoBIM Arcade is its first member.
            // --- Annotation (pyRevit: Annotation.panel): the first panel on the tab, as in pyRevit.
            RibbonPanel annotation = app.CreateRibbonPanel(TabName, "Annotation");
            var annotationTools = new PulldownButtonData("RevoBIM_AnnotationTools", "Annotation\nTools")
            {
                ToolTip = "Annotation tools: Number Sequencer, Bulk Rename and Sheet Name Push.",
                LargeImage = Icon("AnnotationToolsFolder", 32),
                Image = Icon("AnnotationToolsFolder", 16),
            };
            var annotationToolsButton = annotation.AddItem(annotationTools) as PulldownButton;
            annotationToolsButton?.AddPushButton(new PushButtonData(
                "RevoBIM_NumberSequencer", "Number\nSequencer", dll, typeof(Commands.NumberSequencerCommand).FullName)
            {
                ToolTip = "RevoBIM Number Sequencer - number duct and pipe systems into a parameter you choose, branches first then on up the main. " +
                          "Sequencer tab: tab-select or pick systems. System Selector tab: every duct or pipe system in the active view, ordered in a " +
                          "table (drag to re-order), isolated with their tags and coloured to match the list, then Run. Revit stays usable while it is open.",
                LargeImage = Icon("NumberSequencer", 32),
                Image = Icon("NumberSequencer", 16),
            });

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
            // Dropdowns come first on a panel; Find in View is added after them (below Routines).

            // Match Offset (pyRevit: Match Offset.pulldown): take the bottom, middle or top offset off one element and put the
            // elements clicked next on the same offset. Bottom, Middle and Top open no window; give them keyboard shortcuts.
            // Routines holds the Match Offset commands (a dropdown cannot sit inside another dropdown).
            var routines = new PulldownButtonData("RevoBIM_Routines", "Routines")
            {
                ToolTip = "Routine tools.",
                LargeImage = Icon("Routines", 32),
                Image = Icon("Routines", 16),
            };
            var routinesButton = coordination.AddItem(routines) as PulldownButton;
            var matchOffsetButton = routinesButton;
            if (matchOffsetButton != null)
            {
                matchOffsetButton.AddPushButton(new PushButtonData(
                    "RevoBIM_MatchOffsetBottom", "Match Offset Bottom", dll, typeof(Commands.MatchOffsetBottomCommand).FullName)
                {
                    ToolTip = "Match Offset Bottom. First click takes the bottom offset off an element; every click after it puts that " +
                              "element's bottom on the same offset. Escape finishes. Give it a keyboard shortcut and the whole tool is keys, click, click.",
                    Image = Icon("MatchOffsetBottom", 16),
                    LargeImage = Icon("MatchOffsetBottom", 24),
                });
                matchOffsetButton.AddPushButton(new PushButtonData(
                    "RevoBIM_MatchOffsetMiddle", "Match Offset Middle", dll, typeof(Commands.MatchOffsetMiddleCommand).FullName)
                {
                    ToolTip = "Match Offset Middle. First click takes the middle offset off an element; every click after it puts that " +
                              "element's middle on the same offset. Escape finishes. Give it a keyboard shortcut and the whole tool is keys, click, click.",
                    Image = Icon("MatchOffsetMiddle", 16),
                    LargeImage = Icon("MatchOffsetMiddle", 24),
                });
                matchOffsetButton.AddPushButton(new PushButtonData(
                    "RevoBIM_MatchOffsetTop", "Match Offset Top", dll, typeof(Commands.MatchOffsetTopCommand).FullName)
                {
                    ToolTip = "Match Offset Top. First click takes the top offset off an element; every click after it puts that " +
                              "element's top on the same offset. Escape finishes. Give it a keyboard shortcut and the whole tool is keys, click, click.",
                    Image = Icon("MatchOffsetTop", 16),
                    LargeImage = Icon("MatchOffsetTop", 24),
                });
                matchOffsetButton.AddPushButton(new PushButtonData(
                    "RevoBIM_MatchOffsetSlope", "Match Offset Slope", dll, typeof(Commands.MatchOffsetSlopeCommand).FullName)
                {
                    ToolTip = "Match Offset Slope. First click takes the fall and elevation off a main; every click after it puts a branch run " +
                              "on that fall and lands it on the main's centreline where the two cross in plan, then trims and fits it. " +
                              "For connecting an existing drainage run into a main.",
                    Image = Icon("MatchOffsetSlope", 16),
                    LargeImage = Icon("MatchOffsetSlope", 24),
                });
                matchOffsetButton.AddPushButton(new PushButtonData(
                    "RevoBIM_MatchOffsetSettings", "Match Offset Settings", dll, typeof(Commands.MatchOffsetSettingsCommand).FullName)
                {
                    ToolTip = "Rounding, what can be picked, how results are reported, and a one press mapping of the commands onto keyboard shortcuts.",
                    AvailabilityClassName = typeof(Commands.AlwaysAvailable).FullName,
                    Image = Icon("MatchOffsetSettings", 16),
                    LargeImage = Icon("MatchOffsetSettings", 24),
                });
            }

            // Model Tools: tools that change the model geometry. 3D Align and its settings are the first members.
            var modelTools = new PulldownButtonData("RevoBIM_ModelTools", "Model\nTools")
            {
                ToolTip = "Tools that change the geometry of the model.",
                LargeImage = Icon("ModelToolsFolder", 32),
                Image = Icon("ModelToolsFolder", 16),
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

            if (routinesButton != null)
            {
                routinesButton.AddSeparator();
                annotation.AddItem(new PushButtonData(
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
                annotationToolsButton?.AddPushButton(new PushButtonData(
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
                    Image = Icon("UnhideInView", 16),
                    LargeImage = Icon("UnhideInView", 24),
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
                    Image = Icon("Arcade", 16),
                    LargeImage = Icon("Arcade", 24),
                });
            }

            coordination.AddItem(findInView);

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
                LargeImage = Icon("NudgeUp", 24),
            };
            var nudgeDown = new PushButtonData("RevoBIM_NudgeDown", "Nudge Down", dll, typeof(Commands.NudgeDownCommand).FullName)
            {
                ToolTip = nudgeDownTip,
                Image = Icon("NudgeDown", 16),
                LargeImage = Icon("NudgeDown", 24),
            };
            var nudgeSettings = new PushButtonData("RevoBIM_NudgeSettings", "Nudge Settings", dll, typeof(Commands.NudgeSettingsCommand).FullName)
            {
                ToolTip = "Set the increment used by Nudge Up and Nudge Down, and how they behave. Default 50mm. " +
                          "Settings are shared by all three buttons and are kept between sessions.",
                AvailabilityClassName = typeof(Commands.AlwaysAvailable).FullName,
                Image = Icon("NudgeSettings", 16),
                LargeImage = Icon("NudgeSettings", 24),
            };
            // Nudge Up / Down / Settings live in Routines (menu entries use the small 16px icon).
            routinesButton?.AddSeparator();
            routinesButton?.AddPushButton(nudgeUp);
            routinesButton?.AddPushButton(nudgeDown);
            routinesButton?.AddPushButton(nudgeSettings);

            // --- BWIC Tools (pyRevit: BWIC Tools.panel)
            RibbonPanel bwicTools = app.CreateRibbonPanel(TabName, "BWIC Tools");
            var bwicIdPush = new PushButtonData(
                "RevoBIM_BwicIdPush", "BWIC ID\nPush", dll, typeof(Commands.BwicIdPushCommand).FullName)
            {
                ToolTip = "Push CLM_BWIC ID from a linked Generic Model element into BGL_BWIC ID on a host element. " +
                          "Click the linked source, then the host target; repeats until Escape. Finishes silently.",
                AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                LargeImage = Icon("BwicIdPush", 32),
                Image = Icon("BwicIdPush", 16),
            };
            var bwicDropdown = new PulldownButtonData("RevoBIM_BwicTools", "BWIC\nTools")
            {
                ToolTip = "BWIC tools: BWIC ID Push and BWIC Penetration.",
                LargeImage = Icon("BwicToolsFolder", 32),
                Image = Icon("BwicToolsFolder", 16),
            };
            var bwicDropdownButton = bwicTools.AddItem(bwicDropdown) as PulldownButton;
            bwicDropdownButton?.AddPushButton(bwicIdPush);
            var bwicPenetration = new PushButtonData(
                "RevoBIM_BwicPenetration", "BWIC\nPenetration", dll, typeof(Commands.BwicPenetrationCommand).FullName)
            {
                ToolTip = "Opens the RevoBIM BWIC Penetration window, with Wall, Slab and Global Placement tabs.\n\n" +
                          "Wall (rectangular or circular): select the services, press Return, then pick the wall in the linked model. " +
                          "Slab (rectangular, circular or automatic): select the services, press Return, then click the floor. " +
                          "Each tab opens on its family, with its preview and Family settings.\n" +
                          "Global Placement: sweeps the active view and places a BWIC around every group of pipes and cable trays passing " +
                          "through a fire rated or blockwork wall in the chosen link. The settings behind the gear hold clearances, rules " +
                          "and the workset; Global Placement uses the Wall tab's family. Escape returns to the window, which stays open " +
                          "while you navigate. A prompt at the top of the Revit window says what to pick next at each step.",
                AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                LargeImage = Icon("BwicPenetration", 32),
                Image = Icon("BwicPenetration", 16),
            };
            bwicDropdownButton?.AddPushButton(bwicPenetration);

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
            var modelCleanup = new PushButtonData(
                "RevoBIM_ModelCleanup", "Model\nCleanup", dll, typeof(Commands.ModelCleanupCommand).FullName)
            {
                ToolTip = "Model Cleanup. Sync the model, save a detached copy, then remove links, unplaced views " +
                          "and purge the copy ready to send. The live model is never cleaned.",
                AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                LargeImage = Icon("ModelCleanup", 32),
                Image = Icon("ModelCleanup", 16),
            };
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

            var worksetManagement = new PushButtonData(
                "RevoBIM_WorksetManagement", "Workset\nManagement", dll, typeof(Commands.WorksetManagementCommand).FullName)
            {
                ToolTip = "Manage worksets in a sortable, filterable table - rename in bulk, delete or merge several at once moving their " +
                          "elements to one workset, create through Excel - see them in a 3D view coloured by workset, work on scope boxes, and " +
                          "assign elements onto worksets in order, by category or by routine templates built like Revit's view filters. " +
                          "Worksets are checked out automatically when a change needs it. Opens modeless.",
                AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                LargeImage = Icon("WorksetManagement", 32),
                Image = Icon("WorksetManagement", 16),
            };

            // BIM Tools (first on the panel): Filter Manager, Model Cleanup and Workset Management.
            var bimTools = new PulldownButtonData("RevoBIM_BIMTools", "BIM\nTools")
            {
                ToolTip = "BIM management tools: Filter Manager, Model Cleanup and Workset Management.",
                LargeImage = Icon("BIMToolsFolder", 32),
                Image = Icon("BIMToolsFolder", 16),
            };
            var bimToolsButton = management.AddItem(bimTools) as PulldownButton;
            bimToolsButton?.AddPushButton(filterManager);
            bimToolsButton?.AddPushButton(modelCleanup);
            bimToolsButton?.AddPushButton(worksetManagement);
            management.AddItem(excelForRevit);
            management.AddItem(legendCreator);
            var familyFindReplace = new PushButtonData(
                "RevoBIM_FamilyFindReplace", "Family Find\n& Replace", dll, typeof(Commands.FamilyFindReplaceCommand).FullName)
            {
                ToolTip = "Swap one loadable family for another across the model. Find the original by category, family and type, or pick the " +
                          "elements straight out of the model. Choose which instance parameters travel with the swap. Each replacement lands on " +
                          "the original's insertion point and reads the same way round, and electrical circuits, tags and wires are carried across " +
                          "before the original is deleted. Orientation and height are set afterwards, on the whole set at once. " +
                          "In a drafting view it swaps import symbols (AutoCAD blocks) for detail items. Opens modeless.",
                AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                LargeImage = Icon("FamilyFindReplace", 32),
                Image = Icon("FamilyFindReplace", 16),
            };
            management.AddItem(familyFindReplace);
            management.AddItem(new PushButtonData(
                "RevoBIM_AddinManager", "Addin\nManager", dll, typeof(Commands.AddinManagerCommand).FullName)
            {
                ToolTip = "Every button any addin has put on Revit's ribbon, in one searchable dockable panel, grouped by the " +
                          "addin's tab. Search by name, or by what an addin does. Favourites, pins, Quick Access Toolbar and " +
                          "keyboard shortcuts from the right-click menu. Click to show the panel, click again to hide it.",
                AvailabilityClassName = typeof(Commands.AlwaysAvailable).FullName,
                LargeImage = Icon("AddinManager", 32),
                Image = Icon("AddinManager", 16),
            });

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
