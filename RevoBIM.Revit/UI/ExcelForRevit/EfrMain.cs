// Excel for Revit: the result dialogs and the entry point (port of efr_core.py lines 10046-10284).
// main() becomes EfrMain.Run, which the command class calls.
using System;
using System.IO;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.ExcelForRevit;
using static RevoBIM.Tools.ExcelForRevit.Efr;
using static RevoBIM.UI.ExcelForRevit.EfrUi;

namespace RevoBIM.UI.ExcelForRevit
{
    public static partial class EfrUi
    {
        private static string ResultPlural(int n)
        {
            return n == 1 ? "" : "s";
        }

        /// <summary>
        /// The "Unsaved edits" prompt. Returns "cancel", "discard" or "apply"
        /// (null when the dialog was closed some other way).
        /// </summary>
        public static string AskExit(Window owner, int pending)
        {
            var dlg = new ThemedDialog("Unsaved edits", 560, null, owner, C_ORANGE);
            dlg.Add(Tb(string.Format("{0} edit{1} have not been written to the model.", pending, ResultPlural(pending)),
                C_TEXT, 14, true, true));
            TextBlock note = Tb("Closing now discards them. Nothing in this session has touched the " +
                                "model yet.", C_MUTED, 12, false, true);
            note.Margin = new Thickness(0, 8, 0, 0);
            dlg.Add(note);
            dlg.AddButton("Cancel", "ghost", "cancel");
            dlg.AddButton("Exit without saving", "red", "discard");
            dlg.AddButton("Apply and exit", "green", "apply");
            return dlg.Show() as string;
        }

        /// <summary>The "Applied to the model" report. Returns the dialog's result ("ok").</summary>
        public static object ShowResults(Window owner, ApplyResult res, int staged)
        {
            int elements = res.Instances + res.Types + res.Levels;
            bool ok = res.Failures.Count == 0;
            string accent = ok ? C_GREEN : C_ORANGE;
            var dlg = new ThemedDialog("Applied to the model", 620, null, owner, accent);

            TextBlock head = Tb(string.Format("{0} element{1} changed", elements, ResultPlural(elements)),
                ok ? C_GREEN : C_ORANGE, 26, true);
            dlg.Add(head);

            var lines = new System.Collections.Generic.List<string>();
            lines.Add(string.Format("{0} cell{1} written of {2} staged.", res.Cells, ResultPlural(res.Cells), staged));
            if (res.Levels != 0)
            {
                lines.Add(string.Format("{0} element{1} moved to a different level, without " +
                                        "moving in the model.", res.Levels, ResultPlural(res.Levels)));
            }
            lines.Add(string.Format("{0} instance parameter{1} and {2} type parameter{3} written.",
                res.Instances, ResultPlural(res.Instances), res.Types, ResultPlural(res.Types)));
            lines.Add(string.Format("{0} scheduled row{1} affected.", res.RowsAffected, ResultPlural(res.RowsAffected)));
            if (res.Types != 0)
            {
                lines.Add("Type parameter changes reach every element of those types, " +
                          "including ones outside this schedule.");
            }
            TextBlock body = Tb(string.Join("\n", lines.ToArray()), C_TEXT, 12, false, true);
            body.Margin = new Thickness(0, 10, 0, 0);
            dlg.Add(body);

            if (res.Failures.Count > 0)
            {
                TextBlock warn = Tb(string.Format("{0} cell{1} refused — left staged and marked red in the grid:",
                    res.Failures.Count, ResultPlural(res.Failures.Count)), C_RED, 12, true, true);
                warn.Margin = new Thickness(0, 14, 0, 6);
                dlg.Add(warn);
                var box = new Border();
                box.Background = Brush(C_FIELD);
                box.BorderBrush = Brush(C_EDGE);
                box.BorderThickness = new Thickness(1);
                box.CornerRadius = new CornerRadius(3);
                box.Padding = new Thickness(8);
                var sv = new ScrollViewer();
                sv.MaxHeight = 220;
                sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto;
                var stack = new StackPanel();
                int shown = 0;
                foreach (var failure in res.Failures)
                {
                    if (shown++ >= 200) break;
                    TextBlock t = Tb(string.Format("{0}  •  {1}  —  {2}",
                        failure.Label, string.IsNullOrEmpty(failure.Param) ? "parameter" : failure.Param,
                        failure.Message), C_MUTED, 11, false, true);
                    t.Margin = new Thickness(0, 1, 0, 1);
                    stack.Children.Add(t);
                }
                sv.Content = stack;
                box.Child = sv;
                dlg.Add(box);
            }

            TextBlock tail = Tb("The window stays open for more edits.", C_MUTED, 11, false, true);
            tail.Margin = new Thickness(0, 12, 0, 0);
            dlg.Add(tail);
            dlg.AddButton("OK", "green", "ok");
            return dlg.Show();
        }
    }
}

namespace RevoBIM.UI.ExcelForRevit
{
    /// <summary>The command's entry point: Python main().</summary>
    public static class EfrMain
    {
        /// <summary>
        /// Write the failure somewhere it can be read after the dialog is gone
        /// (%APPDATA%\RevoBIM\logs\excel_for_revit_last_error.txt). Returns the path, or null.
        /// </summary>
        public static string LogFailure(string stage, string detail)
        {
            try
            {
                string root;
                try
                {
                    root = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
                }
                catch (Exception)
                {
                    root = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                }
                string folder = Path.Combine(root, "RevoBIM", "logs");
                if (!Directory.Exists(folder))
                    Directory.CreateDirectory(folder);
                string path = Path.Combine(folder, "excel_for_revit_last_error.txt");
                File.WriteAllText(path, "stage: " + stage + "\n\n" + detail, new UTF8Encoding(false));
                return path;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>
        /// The wait cursor, for the seconds a large schedule takes to read and lay out: without it the
        /// button looks as if it did nothing, and gets pressed again.
        /// </summary>
        public static void BusyCursor(bool on)
        {
            try
            {
                Mouse.OverrideCursor = on ? Cursors.Wait : null;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// Load in stages, and say which stage failed. A tool this size fails in one of a handful of
        /// places, and "nothing happens" is not a diagnosis. Each stage names itself, so a report can
        /// say where it stopped instead of that it stopped.
        /// Succeeded: the window opened (modeless: it is still open when this returns).
        /// Cancelled: nothing to do, or the user backed out. Failed: an exception.
        /// </summary>
        public static Result Run(UIApplication uiapp)
        {
            string stage = "starting";
            try
            {
                stage = "reading the document";
                UIDocument uidoc = null;
                Document doc = null;
                try
                {
                    uidoc = uiapp.ActiveUIDocument;
                    doc = uidoc != null ? uidoc.Document : null;
                }
                catch (Exception)
                {
                    uidoc = null;
                    doc = null;
                }
                if (doc == null || uidoc == null)
                {
                    ThemedMessage("Excel for Revit", "Open a project before running this tool.");
                    return Result.Cancelled;
                }
                try
                {
                    if (doc.IsFamilyDocument)
                    {
                        ThemedMessage("Excel for Revit",
                            "This tool works on project schedules. Open a project document.");
                        return Result.Cancelled;
                    }
                }
                catch (Exception)
                {
                }

                stage = "finding the schedule";
                ViewSchedule sched = ResolveSchedule(uidoc, doc);
                if (sched == null)
                    return Result.Cancelled;

                stage = "reading the schedule";
                ScheduleModel model;
                BusyCursor(true);
                try
                {
                    model = new ScheduleModel(doc, sched);
                }
                finally
                {
                    BusyCursor(false);          // every prompt below needs a pointer
                }
                if (!string.IsNullOrEmpty(model.Error))
                {
                    ThemedMessage("Excel for Revit", model.Error, accent: C_RED, width: 600);
                    return Result.Cancelled;
                }
                if (model.Rows.Count == 0)
                {
                    ThemedMessage("Excel for Revit",
                        "\"" + ElemName(sched) + "\" has no elements to edit.\n\nIt may be empty, " +
                        "filtered to nothing, or a key schedule with no keys defined.");
                    return Result.Cancelled;
                }

                // not ported: migrate_window_settings / check_modeless_health (they only mended the
                // state a torn-down pyRevit engine left behind, which cannot happen in a compiled add-in)

                stage = "building the window";
                ExcelForRevitWindow win;
                BusyCursor(true);
                try
                {
                    win = new ExcelForRevitWindow(uidoc, doc, model);
                }
                finally
                {
                    BusyCursor(false);
                }

                stage = "showing the window";
                win.Show();
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                BusyCursor(false);
                string detail = ex.ToString();
                LogFailure(stage, detail);
                try
                {
                    ThemedMessage("Excel for Revit",
                        "Failed while " + stage + ".\n\n" + detail + "\n\nThis was also written " +
                        "to %APPDATA%\\RevoBIM\\logs\\excel_for_revit_last_error.txt",
                        accent: C_RED, width: 720);
                }
                catch (Exception)
                {
                }
                return Result.Failed;
            }
        }
    }
}
