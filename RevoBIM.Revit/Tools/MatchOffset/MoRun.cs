using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.MatchOffset
{
    /// <summary>
    /// Deletes warnings, resolves errors where Revit offers a resolution, and writes every failure down. Deleting
    /// warnings alone is half the job: an unresolved error still rolls the transaction back at commit time, which
    /// is where "Revit did not commit the move" came from with nothing said about what Revit objected to.
    /// </summary>
    public sealed class MoSwallowWarnings : IFailuresPreprocessor
    {
        public readonly List<KeyValuePair<string, string>> Seen = new List<KeyValuePair<string, string>>();

        public List<KeyValuePair<string, string>> Drain()
        {
            var found = new List<KeyValuePair<string, string>>(Seen);
            Seen.Clear();
            return found;
        }

        public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
        {
            bool resolved = false;
            try
            {
                foreach (FailureMessageAccessor failure in accessor.GetFailureMessages())
                {
                    FailureSeverity severity = FailureSeverity.None;
                    string description = "";
                    try
                    {
                        severity = failure.GetSeverity();
                        description = failure.GetDescriptionText();
                    }
                    catch (Exception)
                    {
                    }
                    Seen.Add(new KeyValuePair<string, string>(severity.ToString(), description));
                    if (severity == FailureSeverity.Warning)
                    {
                        try
                        {
                            accessor.DeleteWarning(failure);
                            continue;
                        }
                        catch (Exception)
                        {
                        }
                    }
                    try
                    {
                        if (failure.HasResolutions())
                        {
                            accessor.ResolveFailure(failure);
                            resolved = true;
                        }
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            catch (Exception)
            {
            }
            return resolved ? FailureProcessingResult.ProceedWithCommit : FailureProcessingResult.Continue;
        }
    }

    /// <summary>Answers Revit's own dialogs while a run is in progress, and stops answering when disposed.</summary>
    public sealed class MoDialogGuard : IDisposable
    {
        private readonly UIApplication uiapp;
        private readonly EventHandler<DialogBoxShowingEventArgs> handler;

        public MoDialogGuard(UIApplication uiapp)
        {
            this.uiapp = uiapp;
            handler = (sender, args) =>
            {
                try
                {
                    MoCore.Log("Revit dialog suppressed: " + args.DialogId);
                    args.OverrideResult(1);
                }
                catch (Exception)
                {
                }
            };
            try
            {
                uiapp.DialogBoxShowing += handler;
            }
            catch (Exception)
            {
            }
        }

        public void Dispose()
        {
            try
            {
                uiapp.DialogBoxShowing -= handler;
            }
            catch (Exception)
            {
            }
        }
    }

    /// <summary>What a pick-driven run hands back: the settings it ran with and what it has to say.</summary>
    public sealed class MoRunResult
    {
        public Dictionary<string, string> Settings;
        public MoReport Report;
    }

    /// <summary>Everything a run needs, worked out before the first pick (settings are strings on disk).</summary>
    public sealed class MoRunConfig
    {
        public string Anchor, Label;
        public Dictionary<string, string> Settings;
        public MoModel.MeasureOptions Measure = new MoModel.MeasureOptions();
        public bool HangerRods, SkipSloped, SkipFittings, MoveSource, UsePreselection, Remember, Debug, Workshared;
        public double Step;
        public string RoundMode, RoundDatum, ShowResults, Username;
        public List<string> Categories;
        public int HangerDumps;
        /// <summary>The level the datum was read off, so a family on another level can say what its own offset came out at.</summary>
        public MoLevel DatumLevel = new MoLevel();
        public Dictionary<long, string> Reverse;

        public MoRunConfig(Document doc, string anchor, Dictionary<string, string> settings)
        {
            Anchor = anchor;
            Label = MoCore.AnchorLabel(anchor);
            Settings = settings;

            Measure.Measure = MoCore.Get(settings, "measure");
            Measure.PointMeasure = MoCore.Get(settings, "point_measure");
            Measure.FabMeasure = MoCore.Get(settings, "fab_measure");
            Measure.HangerTop = MoCore.Get(settings, "fab_hanger_top");
            Measure.FramingMeasure = MoCore.Get(settings, "framing_measure");
            Measure.IncludeInsulation = MoCore.IsOn(settings, "include_insulation");
            double tol = MoCore.ParseNumber(MoCore.Get(settings, "slope_tol_deg"), 0.5);
            Measure.SlopeTolDeg = tol < 0 ? 0.5 : tol;
            HangerRods = MoCore.IsOn(settings, "fab_hanger_rods");
            SkipSloped = MoCore.Get(settings, "sloped") == "skip";
            SkipFittings = MoCore.Get(settings, "connected_fittings") == "skip";

            Step = MoCore.ParseNumber(MoCore.Get(settings, "round_step_mm"), 0.0);
            if (Step < 0) Step = 0.0;
            RoundMode = MoCore.Get(settings, "round_mode");
            RoundDatum = MoCore.Get(settings, "round_datum");
            MoveSource = Step > 0 && MoCore.IsOn(settings, "move_source_on_round");

            UsePreselection = MoCore.IsOn(settings, "use_preselection");
            Remember = MoCore.IsOn(settings, "remember_datum");
            ShowResults = MoCore.Get(settings, "show_results");
            Categories = MoCore.EnabledCategories(settings);
            Debug = MoCore.IsOn(settings, "debug_report");
            Workshared = MoModel.IsWorkshared(doc);
            Username = Workshared ? MoModel.Username(doc) : "";
            Reverse = MoModel.CategoryKeyMap();
        }

        public double SlopeTol { get { return Measure.SlopeTolDeg; } }

        public MoMeasurement MeasureElement(Document doc, Element element, XYZ atPoint)
        {
            return MoModel.Measure(doc, element, Measure, atPoint);
        }

        public string CategoryKey(Element element)
        {
            try
            {
                string key;
                return Reverse.TryGetValue(element.Category.Id.Value, out key) ? key : "";
            }
            catch (Exception)
            {
                return "";
            }
        }
    }

    /// <summary>
    /// Match Offset Bottom / Middle / Top: the first pick takes the datum off an element, every pick after it puts the
    /// next element on that datum, one transaction each, until Escape. One transaction per element because the picks
    /// sit between the writes: a transaction cannot be held open across a pick. Port of mo_run.py.
    /// </summary>
    public static class MoRun
    {
        private static readonly HashSet<string> FittingKeys =
            new HashSet<string> { "pipe_fittings", "duct_fittings", "cable_tray_fittings", "conduit_fittings" };

        /// <summary>One instance for the whole session: a new preprocessor per transaction is a new managed object per element.</summary>
        public static readonly MoSwallowWarnings Preprocessor = new MoSwallowWarnings();

        /// <summary>Put whatever Revit objected to into the report, in Revit's words.</summary>
        public static List<KeyValuePair<string, string>> DrainFailures(MoReport report, string where)
        {
            List<KeyValuePair<string, string>> found = Preprocessor.Drain();
            if (found.Count > 0 && report.Debug != null)
            {
                report.Debug.Line("  during " + where + ":");
                foreach (KeyValuePair<string, string> failure in found) report.Debug.Failure(failure.Key, failure.Value);
            }
            return found;
        }

        /// <summary>The failures as one sentence, for a problem line.</summary>
        public static string FailureText(List<KeyValuePair<string, string>> found)
        {
            var parts = new List<string>();
            foreach (KeyValuePair<string, string> failure in found)
            {
                string text = (failure.Value ?? "").Trim();
                if (text.Length > 0 && !parts.Contains(text)) parts.Add(text);
            }
            return string.Join("; ", parts.Take(3));
        }

        public static bool Committed(TransactionStatus status) { return status == TransactionStatus.Committed; }

        /// <summary>
        /// Opens a transaction that swallows warnings and resolves errors through the shared preprocessor and clears
        /// itself after a rollback.
        /// </summary>
        public static Transaction StartTransaction(Document doc, string name)
        {
            var transaction = new Transaction(doc, name);
            transaction.Start();
            FailureHandlingOptions options = transaction.GetFailureHandlingOptions();
            options.SetFailuresPreprocessor(Preprocessor);
            options.SetClearAfterRollback(true);
            transaction.SetFailureHandlingOptions(options);
            return transaction;
        }

        // ======================================================================
        // the two halves of the job
        // ======================================================================

        /// <summary>A hanger's own geometry into the debug report: only the first two, every rule is a guess about how somebody drew it.</summary>
        private static void SayHanger(Element element, MoRunConfig config, MoReport report)
        {
            if (report.Debug == null || config.HangerDumps >= 2) return;
            if (!MoModel.IsASupport(element)) return;
            config.HangerDumps++;
            report.Say("support geometry, " + MoModel.Describe(element));
            foreach (string text in MoModel.HangerLines(element)) report.Say("  " + text);
        }

        /// <summary>When a family on one level is matched to something on another, say what its offset came out at against its own level.</summary>
        private static void SayLevel(Document doc, Element element, MoRunConfig config, MoReport report, string name, MoMeasurement after)
        {
            if (after == null || !after.Ok) return;
            MoLevel level = MoModel.LevelOf(doc, element);
            if (!level.Elevation.HasValue) return;
            double? datumLevel = config.DatumLevel.Elevation;
            if (datumLevel.HasValue && Math.Abs(datumLevel.Value - level.Elevation.Value) <= MoCore.TolFt) return;
            double value = MoCore.AnchorValue(after.Bottom, after.Middle, after.Top, config.Anchor);
            string text = MoCore.LevelOffsetText(name + " on " + (level.Name.Length > 0 ? level.Name : "its level"),
                                                 value, level.Elevation.Value, config.Label);
            if (text.Length > 0) report.Note(text);
        }

        /// <summary>The first pick: returns the datum (null when the element cannot give one) and the measurement taken.</summary>
        private static MoCore.Datum TakeDatum(Document doc, Element element, MoRunConfig config, MoReport report, XYZ atPoint,
                                              out MoMeasurement measurement)
        {
            SayHanger(element, config, report);
            measurement = config.MeasureElement(doc, element, atPoint);
            if (!measurement.Ok)
            {
                report.Problem(MoModel.Describe(element) + ": " + measurement.Reason);
                return null;
            }

            if (measurement.Slope > config.SlopeTol && config.SkipSloped)
            {
                report.Problem(MoModel.Describe(element) + " is pitched " + MoCore.FormatMm(measurement.Slope) +
                               " degrees - Match Offset works to one elevation. Drainage Elevation Match is the tool for a falling run.");
                return null;
            }

            double levelFt = 0.0;
            if (config.RoundDatum == "level" && config.Step > 0) levelFt = MoModel.LevelElevation(doc, element);

            MoCore.Datum datum = MoCore.CaptureDatum(measurement.Bottom, measurement.Middle, measurement.Top, config.Anchor, levelFt,
                                                     config.Step, config.RoundMode, config.RoundDatum);
            if (datum.WasRounded)
                report.Note(config.Label + " datum rounded from " + MoCore.FormatMm(datum.RawMm) + " to " + MoCore.FormatMm(datum.RoundedMm) +
                            " (" + MoCore.FormatMm(config.Step) + " step)");

            config.DatumLevel = MoModel.LevelOf(doc, element);
            report.NotePair("datum level", (config.DatumLevel.Name.Length > 0 ? config.DatumLevel.Name : "none found") + " at " +
                            (config.DatumLevel.Elevation.HasValue ? MoCore.FormatMm(MoCore.FtToMm(config.DatumLevel.Elevation.Value)) : "?") + " mm");

            MoCore.Log("datum " + config.Label + " " + MoCore.FormatMm(datum.RoundedMm) + " from " + MoModel.Describe(element) + " via " + measurement.Route);
            report.NotePair("datum measured from", measurement.Route);
            return datum;
        }

        /// <summary>One element onto the datum. Returns true when it moved.</summary>
        private static bool ApplyTo(Document doc, Element element, MoRunConfig config, double datumFt, MoReport report, XYZ atPoint,
                                    MoMeasurement measurement)
        {
            string name = MoModel.Describe(element);

            if (MoModel.InGroup(element))
            {
                report.Problem(name + " is in a group - ungroup it or edit the group");
                return false;
            }

            if (config.Workshared)
            {
                string owner = MoModel.OwnedByOther(doc, element, config.Username);
                if (owner.Length > 0)
                {
                    report.Problem(name + " is owned by " + owner);
                    return false;
                }
            }

            if (config.SkipFittings && FittingKeys.Contains(config.CategoryKey(element)) && MoModel.ConnectedCount(element) > 0)
            {
                report.Problem(name + " is a connected fitting - move the pipes and the fitting follows");
                return false;
            }

            if (measurement == null)
            {
                SayHanger(element, config, report);
                measurement = config.MeasureElement(doc, element, atPoint);
            }
            if (!measurement.Ok)
            {
                report.Problem(name + ": " + measurement.Reason);
                return false;
            }

            if (measurement.Slope > config.SlopeTol && config.SkipSloped)
            {
                report.Problem(name + " is pitched " + MoCore.FormatMm(measurement.Slope) + " degrees and was left alone");
                return false;
            }

            double delta = MoCore.DeltaFor(measurement.Bottom, measurement.Middle, measurement.Top, config.Anchor, datumFt);
            if (Math.Abs(delta) <= MoCore.TolFt)
            {
                report.Note(name + " was already on the datum");
                return false;
            }

            if (config.Workshared) MoModel.Checkout(doc, new[] { element.Id });

            bool wasPinned = MoModel.IsPinned(element);
            var transaction = new Transaction(doc, "RevoBIM Match Offset " + config.Label);
            string route;
            TransactionStatus status;
            try
            {
                transaction.Start();
                FailureHandlingOptions options = transaction.GetFailureHandlingOptions();
                options.SetFailuresPreprocessor(Preprocessor);
                options.SetClearAfterRollback(true);
                transaction.SetFailureHandlingOptions(options);

                if (wasPinned)
                {
                    try
                    {
                        element.Pinned = false;
                    }
                    catch (Exception)
                    {
                    }
                }
                route = MoModel.Shift(doc, element, delta);
                if (config.HangerRods && MoModel.IsAHanger(element))
                {
                    string said = MoModel.KeepRodTops(element, delta);
                    if (said.Length > 0) report.Note(name + ": " + said);
                }
                if (wasPinned)
                {
                    try
                    {
                        element.Pinned = true;
                    }
                    catch (Exception)
                    {
                    }
                }
                status = transaction.Commit();
            }
            catch (Exception err)
            {
                try
                {
                    transaction.RollBack();
                }
                catch (Exception)
                {
                }
                report.Problem(name + ": " + err.Message);
                return false;
            }
            finally
            {
                transaction.Dispose();
            }

            List<KeyValuePair<string, string>> found = DrainFailures(report, "the move");
            if (!Committed(status))
            {
                string said = FailureText(found);
                report.Problem(name + ": Revit rolled the move back" + (said.Length > 0 ? " - " + said :
                               " without saying why. Turn the debug report on in Settings and send the report over."));
                return false;
            }

            // Prove the write. A void API call is not evidence, and Revit does not reliably raise when a write does not take.
            MoMeasurement after = config.MeasureElement(doc, element, atPoint);
            if (after.Ok)
            {
                double left = MoCore.DeltaFor(after.Bottom, after.Middle, after.Top, config.Anchor, datumFt);
                if (Math.Abs(left) > MoCore.TolFt * 10)
                {
                    report.Problem(name + ": asked for " + MoCore.FormatMm(MoCore.FtToMm(delta)) + " and it read back " +
                                   MoCore.FormatMm(MoCore.FtToMm(left)) + " out");
                    return false;
                }
            }

            SayLevel(doc, element, config, report, name, after);

            MoCore.Log(name + " moved " + MoCore.FormatMm(MoCore.FtToMm(delta)) + " mm via " + route);
            report.Say(name + " moved " + MoCore.FormatMm(MoCore.FtToMm(delta)) + " mm via " + route + ", measured from " + measurement.Route);
            report.MatchedOne();
            return true;
        }

        // ======================================================================
        // the loop
        // ======================================================================

        /// <summary>The whole command. Returns the settings and the report.</summary>
        public static MoRunResult Run(UIApplication uiapp, string anchor)
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;
            Dictionary<string, string> settings = MoCore.LoadSettings();
            var report = new MoReport();
            var result = new MoRunResult { Settings = settings, Report = report };

            MoModel.ResetCaches();
            var config = new MoRunConfig(doc, anchor, settings);

            if (config.Debug)
            {
                report.Debug = new MoRecorder("Match Offset " + config.Label);
                report.Debug.Header(uiapp, doc, settings);
            }

            if (config.Categories.Count == 0)
            {
                report.Problem("No categories are enabled in Settings, so there is nothing to pick.");
                return result;
            }

            var selectionFilter = new MoModel.OffsetFilter(config.Categories);

            var preselected = new List<Element>();
            if (config.UsePreselection)
            {
                try
                {
                    foreach (ElementId id in uidoc.Selection.GetElementIds())
                    {
                        Element element = doc.GetElement(id);
                        if (element != null) preselected.Add(element);
                    }
                }
                catch (Exception)
                {
                    preselected.Clear();
                }
                // one borrow for the lot rather than one per element: CheckoutElements is a round trip to central
                if (preselected.Count > 0 && config.Workshared) MoModel.Checkout(doc, preselected.Select(e => e.Id));
            }

            double? datumFt = null;
            double? datumMm = null;
            bool roundedFlag = false;

            if (config.Remember && MoCore.Get(settings, "last_datum_anchor") == anchor)
            {
                double? remembered = MoCore.ParseNumber(MoCore.Get(settings, "last_datum_ft"));
                if (remembered.HasValue)
                {
                    datumFt = remembered;
                    datumMm = MoCore.FtToMm(remembered.Value);
                    report.Note("Using the datum remembered from the last run. Turn 'Remember the datum between runs' off in Settings " +
                                "to pick a fresh one each time.");
                }
            }

            using (new MoDialogGuard(uiapp))
            {
                try
                {
                    while (true)
                    {
                        string prompt = MoCore.PromptText(anchor, datumMm, roundedFlag, config.Step);
                        Reference reference;
                        try
                        {
                            reference = uidoc.Selection.PickObject(ObjectType.Element, selectionFilter, prompt);
                        }
                        catch (Autodesk.Revit.Exceptions.OperationCanceledException)
                        {
                            break;
                        }
                        catch (Exception err)
                        {
                            MoCore.Log("pick ended: " + err.Message);
                            break;
                        }
                        if (reference == null) break;

                        Element element = doc.GetElement(reference.ElementId);
                        if (element == null) continue;
                        XYZ point;
                        try
                        {
                            point = reference.GlobalPoint;
                        }
                        catch (Exception)
                        {
                            point = null;
                        }

                        if (!datumFt.HasValue)
                        {
                            MoMeasurement measurement;
                            MoCore.Datum datum = TakeDatum(doc, element, config, report, point, out measurement);
                            if (datum == null) continue;
                            datumFt = datum.DatumFt;
                            datumMm = datum.RoundedMm;
                            roundedFlag = config.Step > 0;
                            report.DatumText = config.Label + " " + MoCore.FormatMm(datumMm.Value);

                            // The first element goes onto the rounded value itself, so the whole bank - the one it was
                            // read off included - ends up on one number rather than everything but the source.
                            if (config.MoveSource) ApplyTo(doc, element, config, datumFt.Value, report, point, measurement);

                            if (config.Remember)
                            {
                                settings["last_datum_ft"] = datumFt.Value.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
                                settings["last_datum_anchor"] = anchor;
                                MoCore.SaveSettings(settings);
                            }

                            foreach (Element other in preselected)
                            {
                                if (other.Id.Value == element.Id.Value) continue;
                                ApplyTo(doc, other, config, datumFt.Value, report, null, null);
                            }
                            continue;
                        }

                        ApplyTo(doc, element, config, datumFt.Value, report, point, null);
                    }
                }
                finally
                {
                    DrainFailures(report, "the rest of the run");
                    if (report.Debug != null)
                    {
                        report.Debug.Tail(report);
                        report.Debug.Save();
                    }
                    MoCore.Log("run finished: " + report.Matched + " matched, " + report.Problems.Count + " problems");
                    MoCore.FlushLog();
                }
            }
            return result;
        }
    }
}
