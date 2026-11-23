using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.FindInView;
using RevoBIM.UI.FindInView;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Find in View: select elements, press the button, pick a view, press Show Me - the view opens and
    /// zooms to what was selected. With the selection already drawn in the plan you are in, it just zooms
    /// there. With nothing selected it first asks for element ids, as Revit's Select Elements by ID does.
    /// Port of the pyRevit tool (version 1.17.0), staged like script.py: a failure names its stage, shows the
    /// text and writes it to %APPDATA%\RevoBIM\find_in_view_last_error.txt. The tool only reads, changes the
    /// active view and zooms; the one write (switching a hidden category back on) is a single transaction.
    /// Code in Tools\FindInView\, windows in UI\FindInView\.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class FindInViewCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "starting up";
            try
            {
                UIApplication uiapp = data.Application;
                stage = "reaching Revit";
                UIDocument uidoc = uiapp.ActiveUIDocument;
                if (uidoc == null || uidoc.Document == null)
                {
                    Report(stage, "No document is open.");
                    return Result.Failed;
                }
                Document doc = uidoc.Document;
                FivLog.Begin(uiapp.Application.VersionName + " " + uiapp.Application.VersionBuild, doc.Title);

                stage = "reading the settings";
                Dictionary<string, string> settings = FivCore.LoadSettings();
                string palette = FivUi.PaletteFor(settings);
                FivLog.Write("settings: theme_mode " + FivCore.Get(settings, "theme_mode") + " -> palette " + palette +
                             "; zoom_here " + FivCore.Get(settings, "zoom_here") + ", open_tiled " + FivCore.Get(settings, "open_tiled") +
                             ", unhide " + FivCore.Get(settings, "unhide_categories") + "/" + FivCore.Get(settings, "unhide_mode"));

                stage = "reading the selection";
                // the view the run started in: the one the tiled view opens beside
                long? hostViewId = null;
                try
                {
                    hostViewId = doc.ActiveView.Id.Value;
                }
                catch (Exception)
                {
                }
                List<Element> selected;
                List<ElementId> selectedIds, categoryIds;
                List<string> categoryNames;
                FivModel.ReadSelection(uidoc, out selected, out selectedIds, out categoryIds, out categoryNames);
                bool launchedWithSelection = selected.Count > 0;
                FivLog.Write("selection: " + selected.Count + " element(s), " + categoryNames.Count + " categor" +
                             (categoryNames.Count == 1 ? "y" : "ies") + " [" + string.Join(", ", categoryNames) + "]; active view '" +
                             SafeName(doc.ActiveView) + "'");

                if (!launchedWithSelection)
                {
                    // nothing selected: ask for element ids instead, the way Revit's own Select Elements by
                    // ID does, then carry on with what that finds
                    stage = "asking for element ids";
                    var byId = new FivByIdWindow(uidoc, uiapp, settings);
                    byId.Show();
                    if (byId.Elements.Count == 0 && !byId.Skipped) return Result.Cancelled;
                    if (byId.Elements.Count > 0)
                    {
                        FivModel.SelectElements(uidoc, byId.ElementIds);
                        FivModel.ReadSelection(uidoc, out selected, out selectedIds, out categoryIds, out categoryNames);
                        if (selected.Count == 0)
                        {
                            FivUi.Message("Those elements could not be selected in this model.", palette, uiapp);
                            return Result.Failed;
                        }
                    }
                }

                // Launched on a selection that is already drawn in the view you are in: frame it here and
                // stop. Opening a window to ask which view to go to, when the answer is "this one", is the
                // long way round.
                if (launchedWithSelection)
                {
                    stage = "looking in the view you are in";
                    View here = null;
                    try
                    {
                        here = doc.ActiveView;
                    }
                    catch (Exception)
                    {
                    }
                    if (here != null)
                    {
                        string hereNote;
                        bool zoomed = FivModel.ZoomHere(uidoc, here, selected, selectedIds, settings, out hereNote);
                        if (zoomed) return Result.Succeeded;
                        if (hereNote.Length > 0)
                        {
                            // it is here, but the zoom would not hold - worth saying rather than quietly
                            // opening the window as though it were somewhere else
                            FivUi.Message(hereNote, palette, uiapp);
                            return Result.Succeeded;
                        }
                    }
                }

                stage = "reading the views";
                List<ViewRow> rows = FivModel.ReadViews(doc);
                FivLog.Write("views: " + rows.Count + " listable");
                if (rows.Count == 0)
                {
                    FivUi.Message("This project has no views the tool can open and zoom.\n\n" +
                                  "Drafting views, legends, schedules and sheets are left out because they cannot show model elements.",
                                  palette, uiapp);
                    return Result.Cancelled;
                }

                stage = "showing the window";
                List<FivCore.WinRect> rects = FivModel.ReadWindowRects(uidoc);
                bool alreadyTiled = FivCore.LooksTiled(rects);
                var window = new FivWindow(uidoc, uiapp, settings, rows, selected, selectedIds, categoryIds, categoryNames,
                                           alreadyTiled, rects.Select(r => r.ViewId));
                ViewRow chosen = window.Show();
                if (chosen == null)
                {
                    FivLog.Write("window: closed without a view");
                    return Result.Cancelled;
                }

                // the selection can have been changed from inside the window, by id, so the zoom has to use
                // what the window ended up with rather than what it opened with
                // The window is closed by now: the active view cannot be changed while a modal dialog is open.
                stage = "opening the view";
                settings = FivCore.LoadSettings();
                string note;
                bool ok = FivModel.ActivateAndZoom(uidoc, chosen.View, window.Elements, window.ElementIds, settings, uiapp,
                                                   hostViewId, window.CategoryIds, out note);
                FivLog.Write("result: ok " + ok + (note.Length > 0 ? ", note: " + note.Replace("\n", " / ") : ""));
                // report only when there is something that needs a look
                if (!ok || note.Length > 0) FivUi.Message(note, palette, uiapp);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                FivLog.Write("error at stage '" + stage + "': " + err);
                Report(stage, err.ToString());
                return Result.Failed;
            }
        }

        private static string SafeName(View view)
        {
            try
            {
                return view == null ? "none" : view.Name;
            }
            catch (Exception)
            {
                return "?";
            }
        }

        /// <summary>Says which stage failed, on screen and on disk.</summary>
        private static void Report(string stage, string errorText)
        {
            string text = "Find in View could not start.\n\nStage: " + stage + "\n\n" + errorText;
            try
            {
                Directory.CreateDirectory(FivCore.SettingsDir());
                File.WriteAllText(FivCore.ErrorPath(), text + "\n\n" + FivCore.BuildInfo(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
            try
            {
                new TaskDialog("RevoBIM Find in View")
                {
                    MainInstruction = "Find in View could not start",
                    MainContent = text,
                }.Show();
            }
            catch (Exception)
            {
            }
        }
    }
}
