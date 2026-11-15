using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.LegendCreator;
using RevoBIM.UI.LegendCreator;
using static RevoBIM.Tools.LegendCreator.LgcCore;
using static RevoBIM.Tools.LegendCreator.LgcLogic;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Legend Creator: builds legend views from the model. Family Legend lists
    /// the family types placed in the project, one legend per category or all
    /// combined. System Colour Legend builds Containment, Ductwork and Pipework
    /// colour keys from filter and system overrides. Port of the pyRevit tool
    /// (script.py + lgc_app.py), version 3.0.0.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class LegendCreatorCommand : IExternalCommand
    {
        private const string Title = "RevoBIM - Legend Creator";

        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            try
            {
                return Run(data.Application);
            }
            catch (Exception err)
            {
                // Always reported, Debug or not - it may come before the window ever appears.
                try
                {
                    LgcReport.ReportCrash(err, "run");
                }
                catch (Exception)
                {
                    TaskDialog.Show(Title, "Legend Creator could not run.\n\n" + err);
                }
                return Result.Failed;
            }
        }

        private static Result Run(UIApplication uiapp)
        {
            ResetTrace();
            Document doc = uiapp.ActiveUIDocument?.Document;
            LgcReport.App = uiapp.Application;
            LgcReport.Doc = doc;
            LgcTheme.OwnerHandle = uiapp.MainWindowHandle;
            Log("start");

            var settings = LoadSettings();
            // Debug follows the saved tick from the very first line.
            StartDebug(settings.Get("debug", "0") == "1");
            string themeName = LgcTheme.ResolveTheme(settings.Get("theme_mode", ThemeAuto));
            LgcCore.Theme = themeName;
            Log("theme mode " + settings.Get("theme_mode", "") + " -> " + themeName);

            if (doc == null || doc.IsFamilyDocument)
            {
                Log("stopped: no project document");
                TaskDialog.Show(Title, "Open a project document and try again.");
                return Result.Cancelled;
            }
            Log("document: " + doc.Title);

            var model = new LgcModel(doc);
            // The family tab needs a legend component to clone; the system tab
            // only needs somewhere to draw.
            var (seedView, seedComponent) = model.FindSeedLegend();
            View anyLegend = seedView ?? model.FindSeedLegendView();
            Log("seed legend with a component: " + (seedView != null ? LgcModel.ElementName(seedView) : "none") +
                "; any legend: " + (anyLegend != null ? LgcModel.ElementName(anyLegend) : "none"));
            if (anyLegend == null)
            {
                TaskDialog.Show(Title,
                    "Legend Creator needs at least one existing legend view.\n\n" +
                    "The Revit API cannot create a legend view from scratch, so the tool duplicates one. " +
                    "Make an empty legend view and run it again.\n\n" +
                    "The Family Legend tab additionally needs that legend to hold one legend component, " +
                    "since components cannot be created from nothing either - drag any family type into it " +
                    "from the Project Browser.");
                return Result.Cancelled;
            }

            var textTypes = model.TextNoteTypes();
            Log(string.Format(Inv, "text note types: {0}", textTypes.Count));
            if (textTypes.Count == 0)
            {
                TaskDialog.Show(Title, "This project has no text note type available.");
                return Result.Cancelled;
            }

            var phases = model.ProjectPhases();
            Log("phases: " + string.Join(", ", phases.Select(p => p.Name + " (id " + LgcModel.Eid(p.Id) + ")")));
            Log("building the window");
            var window = new LegendCreatorWindow(model, phases, textTypes, settings, seedView != null);
            Log("window built, showing it");
            LgcTheme.ShowOverRevit(window);
            LgcCore.Theme = window.ThemeName ?? themeName;

            bool debugNow = window.DebugTicked;
            StartDebug(debugNow);
            if (!debugNow) DebugOn = false;

            if (!window.HasResult)
            {
                Log("window closed without creating");
                if (debugNow)
                    LgcReport.ShowDebugReport("Debug is ticked and the window was closed without creating anything",
                                              LgcCore.Theme);
                return Result.Cancelled;
            }

            Log(string.Format(Inv, "creating: tab {0}, {1} item(s)", window.Mode,
                              window.Mode == "system" ? window.SystemResult.Count : window.FamilyResult.Count));
            var build = new LgcBuild(uiapp, doc);
            HashSet<string> taken = model.TakenViewNames();
            build.SuppressDialogs(true);
            Result result;
            try
            {
                result = RunEverything(window, build, taken, seedView, seedComponent, anyLegend);
            }
            finally
            {
                build.SuppressDialogs(false);
            }

            if (debugNow) LgcReport.ShowDebugReport("Debug is ticked", LgcCore.Theme);
            return result;
        }

        /// <summary>After the run: the summary, its question, then the browser - every transaction closed.</summary>
        private static void Finish(LgcBuild build, View view, int legends, int components, int skipped,
                                   int scale, string theme, bool debug)
        {
            var window = new LegendCreatorDone(legends, components, skipped, scale, theme,
                                               view != null ? LgcModel.ElementName(view) : "", debug);
            LgcTheme.ShowOverRevit(window);
            if (view == null) return;

            if (window.OpenRequested)
                Log("opened " + LgcModel.ElementName(view) + ": " +
                    (build.OpenView(view) ? "yes" : "no - open it by hand"));
            else
                Log("not opened - user chose Not now");
            build.RevealInBrowser(view);
        }

        private static void LogDialogs(LgcBuild build)
        {
            if (build.DialogsSeen.Count > 0)
                Log("   Revit dialogs answered: " +
                    string.Join(", ", build.DialogsSeen.Distinct().OrderBy(d => d, StringComparer.Ordinal)));
        }

        private static Result RunEverything(LegendCreatorWindow window, LgcBuild build, HashSet<string> taken,
                                            View seedView, Element seedComponent, View anyLegend)
        {
            if (window.Mode == "system")
            {
                SystemOptions opts = window.SystemOpts;
                opts.Groups = GroupedEntries(window.SystemResult, opts.Kind);
                var (view, placed, skipped, notes) = build.RunSystem(opts, anyLegend, taken);

                Log("");
                Log("=== System Colour Legend - " + opts.Kind.Label + " ===");
                Log(string.Format(Inv, "scale 1:{0}, text {1}, heading {2}", opts.Scale, opts.TextTypeName, opts.HeadTypeName));
                Log(string.Format(Inv, "swatches {0} x {1}mm, pitch {2}mm, text {3}mm clear, line weight {4}",
                                  FormatMm(opts.SwatchW), FormatMm(opts.SwatchH), FormatMm(opts.RowPitch),
                                  FormatMm(opts.TextGap), opts.LineWeight));
                Log(view != null
                    ? string.Format(Inv, "{0} - {1} swatch(es)", LgcModel.ElementName(view), placed)
                    : "failed");
                foreach (string note in notes.Concat(window.SysNotes)) Log("   " + note);
                foreach (var (label, reason) in skipped) Log("   skipped " + label + " - " + reason);
                LogDialogs(build);

                Finish(build, view, view != null ? 1 : 0, placed, skipped.Count + window.SysNotes.Count,
                       opts.Scale, opts.Theme, opts.Debug);
                return Result.Succeeded;
            }

            if (seedView == null)
            {
                TaskDialog.Show(Title,
                    "The Family Legend tab needs an existing legend view holding at least one legend component, " +
                    "which this project has not got.\n\n" +
                    "Drag any family type into a legend view from the Project Browser, then run it again.");
                return Result.Cancelled;
            }

            FamilyOptions fam = window.FamilyOpts;
            var progress = new LegendCreatorProgress(fam.Theme);
            List<(string Name, View View, int Count, List<(string Label, string Reason)> Skipped)> results;
            progress.ShowOverRevit();
            try
            {
                results = build.RunBatch(window.FamilyResult, fam, seedView, seedComponent, taken, progress);
            }
            finally
            {
                progress.Close();
            }

            string caseLabel = fam.TextCase == CaseUpper ? "UPPERCASE"
                             : fam.TextCase == CaseCamel ? "Camel Case" : "as written";
            Log("");
            Log("=== Family Legend ===");
            Log(string.Format(Inv, "scale 1:{0}, phase {1}, text from {2} ({3}), style {4}",
                              fam.Scale, fam.Phase, fam.NameParam, caseLabel, fam.TextTypeName));
            Log(string.Format(Inv, "rows {0}mm, text {1}mm right, columns {2}mm",
                              FormatMm(fam.RowSpacing), FormatMm(fam.TextOffset), FormatMm(fam.ColumnSpacing)));

            foreach (var (name, view, count, skipped) in results)
            {
                Log(view == null ? name + " - failed"
                                 : string.Format(Inv, "{0} - {1} component(s)", LgcModel.ElementName(view), count));
                foreach (var (label, reason) in skipped) Log("   skipped " + label + " - " + reason);
            }
            LogDialogs(build);

            var made = results.Where(r => r.View != null).ToList();
            Finish(build, made.Count > 0 ? made[0].View : null, made.Count, made.Sum(r => r.Count),
                   results.Sum(r => r.Skipped.Count), fam.Scale, fam.Theme, fam.Debug);
            return Result.Succeeded;
        }
    }
}
