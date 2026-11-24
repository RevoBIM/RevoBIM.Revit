using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.FamilyFindReplace
{
    /// <summary>What one run is asked to do. Mirrors the arguments of replace_all in the pyRevit tool.</summary>
    public sealed class RunOptions
    {
        public List<string> RetainNames = new List<string>();
        public double ZOffsetFt;
        public bool MatchOrientation = true;
        public double ExtraRadians;
        public bool LevelBelowPoint = true;
        public bool RetainCircuits = true;
        public bool RetainTags = true;
        public bool RetainWires = true;
        public bool ReplaceInGroups;
        // drafting views
        public bool Drafting;
        public bool MatchMirror = true;
        public bool ByCentre;
    }

    public static partial class FfrCore
    {
        private static void SetFailureHandling(Transaction transaction)
        {
            try
            {
                FailureHandlingOptions options = transaction.GetFailureHandlingOptions();
                options.SetFailuresPreprocessor(new WarningSwallower());
                options.SetClearAfterRollback(true);
                transaction.SetFailureHandlingOptions(options);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// Report progress, if anyone is listening. Only ever called with NO transaction open: the caller repaints
        /// the window from here, and letting Revit's message loop run between a transaction's Start and Commit can
        /// leave the write with nothing committed. That is why this run is chunked rather than one transaction.
        /// </summary>
        private static void Tick(Action<int, int, string> progress, int done, int total, string label)
        {
            if (progress == null) return;
            try
            {
                progress(done, total, label);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// Swap every instance for the replacement type, in one transaction group. With options.Drafting the
        /// instances are import symbols and each is replaced by a detail item lined up on it and turned to match.
        /// Circuits, wires, levels and groups do not apply there.
        /// </summary>
        public static Report ReplaceAll(Document doc, UIDocument uidoc, List<Element> instances, ElementId symbolId, RunOptions options,
                                        Action<int, int, string> progress)
        {
            if (options.Drafting) options.ReplaceInGroups = false;
            var report = new Report { ByCentre = options.ByCentre };
            ResetRunCaches();
            var symbol = doc.GetElement(symbolId) as FamilySymbol;
            if (symbol == null)
            {
                report.Add("fail", "The replacement type is no longer in the model.");
                return report;
            }
            if (instances.Count > MaxElements)
            {
                report.Add("fail", "The selection reaches " + instances.Count + " elements, past the " + MaxElements + " limit. Narrow the scope and run it again.");
                return report;
            }

            // The types being replaced FROM. Matching group members against the replacement type instead of
            // these is what made 1.4.0 report "nothing inside it would replace" on a group that plainly held
            // the family: it was looking for elements that had already been swapped.
            var sourceTypeIds = new HashSet<long>();
            foreach (Element element in instances)
            {
                try
                {
                    sourceTypeIds.Add(Eid(element.GetTypeId()));
                }
                catch (Exception)
                {
                }
            }

            // Element ids, not handles: the run spans several transactions and everything is re-fetched by id at the point of use.
            List<ElementId> looseIds = instances.Select(e => e.Id).ToList();
            var groupWork = new List<GroupWork>();

            var group = new TransactionGroup(doc, "RevoBIM Family Find & Replace");
            group.Start();
            try
            {
                if (options.ReplaceInGroups)
                {
                    var survey = new Transaction(doc, "Read groups");
                    survey.Start();
                    try
                    {
                        List<Element> loose;
                        groupWork = SurveyGroups(doc, instances, sourceTypeIds, out loose);
                        looseIds = loose.Select(e => e.Id).ToList();
                        report.GroupInstances = CountGroupInstances(groupWork);
                    }
                    finally
                    {
                        survey.RollBack();
                    }
                }

                int total = looseIds.Count + groupWork.Count;
                int done = 0;
                Tick(progress, done, total, "Starting");

                var activate = new Transaction(doc, "Activate type");
                activate.Start();
                SetFailureHandling(activate);
                try
                {
                    if (!symbol.IsActive)
                    {
                        symbol.Activate();
                        doc.Regenerate();
                    }
                    activate.Commit();
                }
                catch (Exception)
                {
                    try
                    {
                        activate.RollBack();
                    }
                    catch (Exception)
                    {
                    }
                }

                // Loose elements, in chunks: one transaction for the whole batch is a way to lose the whole
                // batch, and leaves nowhere safe to report progress from.
                for (int begin = 0; begin < looseIds.Count; begin += ChunkSize)
                {
                    List<ElementId> chunk = looseIds.Skip(begin).Take(ChunkSize).ToList();
                    var transaction = new Transaction(doc, "Replace families");
                    transaction.Start();
                    SetFailureHandling(transaction);
                    try
                    {
                        foreach (ElementId elementId in chunk)
                        {
                            Element source = doc.GetElement(elementId);
                            if (source == null) continue;
                            var sub = new SubTransaction(doc);
                            try
                            {
                                sub.Start();
                                string message;
                                bool ok = options.Drafting
                                    ? ReplaceImportOne(doc, source, symbol, options, report, out message)
                                    : ReplaceOne(doc, source, symbol, options, report, false, out message);
                                if (ok) sub.Commit();
                                else
                                {
                                    sub.RollBack();
                                    report.Add("fail", message);
                                }
                            }
                            catch (Exception err)
                            {
                                try
                                {
                                    sub.RollBack();
                                }
                                catch (Exception)
                                {
                                }
                                report.Add("fail", "Element " + Eid(elementId) + ": " + err.Message);
                            }
                        }
                        transaction.Commit();
                    }
                    catch (Exception err)
                    {
                        try
                        {
                            if (transaction.HasStarted()) transaction.RollBack();
                        }
                        catch (Exception)
                        {
                        }
                        report.Add("fail", "A batch of " + chunk.Count + " was rolled back: " + err.Message);
                    }
                    done += chunk.Count;
                    Tick(progress, done, total, Math.Min(done, looseIds.Count) + " of " + looseIds.Count + " elements");
                }

                // One transaction per group type: taking a group apart and putting it back is one move, so a type
                // that fails rolls back whole, and the gap between two of them is somewhere safe to repaint.
                foreach (GroupWork item in groupWork)
                {
                    var transaction = new Transaction(doc, "Replace families in group");
                    transaction.Start();
                    SetFailureHandling(transaction);
                    try
                    {
                        var attempt = new SubTransaction(doc);
                        attempt.Start();
                        GroupOutcome outcome = ReplaceInGroupType(doc, item, symbol, sourceTypeIds, options, report);
                        if (outcome.Shifted)
                        {
                            // the fast route moved something: undo all of it and rebuild every instance in place instead
                            attempt.RollBack();
                            report.Add("warn", "Group \"" + item.TypeName + "\": moving the other instances onto the new type shifted them, so every " +
                                               "instance was rebuilt in place instead. Slower, but nothing moved.");
                            outcome = ReplaceInGroupTypeSlow(doc, item, symbol, sourceTypeIds, options, report);
                        }
                        else attempt.Commit();

                        if (outcome.Swapped > 0)
                        {
                            transaction.Commit();
                            report.GroupsDone += item.GroupIds.Count;
                            if (outcome.DetailGroups > 0)
                                report.Add("warn", "Group \"" + item.TypeName + "\": " + outcome.DetailGroups +
                                                   " instance(s) had attached detail groups, which do not survive being re-formed.");
                            foreach (string problem in outcome.Problems) report.Add("warn", "Group \"" + item.TypeName + "\": " + problem);
                        }
                        else
                        {
                            transaction.RollBack();
                            report.GroupsFailed += item.GroupIds.Count;
                            string detail = outcome.Problems.Count > 0 ? outcome.Problems[0] : "nothing inside it matched the family being replaced";
                            report.Add("fail", "Group \"" + item.TypeName + "\" was left alone - " + detail);
                        }
                    }
                    catch (Exception err)
                    {
                        try
                        {
                            if (transaction.HasStarted()) transaction.RollBack();
                        }
                        catch (Exception)
                        {
                        }
                        report.GroupsFailed += item.GroupIds.Count;
                        report.Add("fail", "Group \"" + item.TypeName + "\" was left alone: " + err.Message);
                    }
                    done++;
                    Tick(progress, done, total, "group \"" + item.TypeName + "\"");
                }

                group.Assimilate();
                Tick(progress, total, total, "Finished");
            }
            catch (Exception err)
            {
                try
                {
                    group.RollBack();
                }
                catch (Exception)
                {
                }
                report.Add("fail", "The run was rolled back: " + err.Message);
                FfrLog.Write("run: rolled back - " + err);
            }
            return report;
        }

        private static bool ReplaceOne(Document doc, Element source, FamilySymbol symbol, RunOptions options, Report report, bool allowGrouped,
                                       out string message)
        {
            message = "";
            long sourceId = Eid(source.Id);

            // Still guarded even on the group path: by the time this is reached from ReplaceInGroupType the
            // member has been ungrouped, so a live GroupId here means the ungroup did not take.
            try
            {
                if (source.GroupId != null && Eid(source.GroupId) > 0)
                {
                    message = allowGrouped
                        ? "Element " + sourceId + " is still inside a group after it was ungrouped, so it was left alone."
                        : "Element " + sourceId + " is inside a group and was left alone - tick \"Replace inside groups\" to have them handled.";
                    return false;
                }
            }
            catch (Exception)
            {
            }

            XYZ point = InstancePoint(source);
            if (point == null)
            {
                message = "Element " + sourceId + " is line based rather than point based and was left alone.";
                return false;
            }

            string kind = options.MatchOrientation ? ReferenceKind(source) : RefBasisX;
            report.ReferenceKind = kind;
            Level level = ResolveLevel(doc, source, point, options.LevelBelowPoint);
            Element host = null;
            try
            {
                var fi = source as FamilyInstance;
                host = fi == null ? null : fi.Host;
            }
            catch (Exception)
            {
                host = null;
            }
            // Captured before anything is placed, and acted on before the original is deleted: Revit removes a
            // tag whose element has gone and leaves a wire end dangling, so afterwards is too late for both.
            List<IndependentTag> tags = options.RetainTags ? TagsOn(doc, source) : new List<IndependentTag>();
            List<WireLink> wires = options.RetainWires ? WireLinks(doc, source) : new List<WireLink>();
            List<ElectricalSystem> circuits = options.RetainCircuits ? ElectricalSystems(source) : new List<ElectricalSystem>();
            int dropped = 0;
            // Asked for explicitly, so the circuits go when the originals do. Counted rather than ignored, because
            // it is the one setting here that loses something an undo cannot get back.
            if (!options.RetainCircuits) dropped = ElectricalSystems(source).Count;
            bool wasPinned = false;
            try
            {
                wasPinned = source.Pinned;
            }
            catch (Exception)
            {
            }

            var errors = new List<string>();
            string route;
            Element created = CreateReplacement(doc, symbol, point, level, host, PlacementName(symbol), out route, errors);
            if (created == null)
            {
                // every route, not just the last: which ones were tried says what placement type the family reported
                string detail = errors.Count > 0 ? string.Join("; ", errors) : "no placement route was accepted";
                message = "Element " + sourceId + ": the replacement would not place. " + detail;
                return false;
            }
            Report.Bump(report.Routes, route);

            doc.Regenerate();
            // setting a level parameter moves the element, so the level goes on first and the point is corrected afterwards
            string levelNote = ForceLevel(created, level);
            if (levelNote != null) Report.Bump(report.LevelsSet, levelNote);
            doc.Regenerate();
            PlaceAt(doc, created, point, options.ZOffsetFt);
            if (options.MatchOrientation || Math.Abs(options.ExtraRadians) > 1.0e-9) MatchRotation(doc, source, created, kind, options.ExtraRadians);
            doc.Regenerate();

            var failedParams = new List<string>();
            string text;
            if (!CarryWorkset(source, created, out text) && text.Length > 0) failedParams.Add(text);
            // phasing goes on before the circuit is touched: a replacement on the view's phase rather than the original's is refused by AddToCircuit
            if (!CarryPhasing(source, created, out text) && text.Length > 0) failedParams.Add(text);
            foreach (string name in options.RetainNames)
            {
                if (!CopyParameter(source, created, name, out text) && text.Length > 0) failedParams.Add(text);
            }

            if (circuits.Count > 0)
            {
                doc.Regenerate();
                var problems = new List<string>();
                int joined = TransferCircuits(doc, circuits, created, problems);
                if (joined < circuits.Count)
                {
                    // The original still holds the circuit. Deleting it now would take the circuit with it, so the
                    // element is refused instead and left exactly as it was for the user to look at.
                    message = "Element " + sourceId + " was left alone - " + (circuits.Count - joined) + " of " + circuits.Count +
                              " circuit(s) would not take the replacement, and deleting the original would have destroyed them. " +
                              string.Join("; ", problems);
                    return false;
                }
                report.CircuitsKept += joined;
            }

            if (wires.Count > 0)
            {
                var problems = new List<string>();
                report.WiresKept += TransferWires(doc, wires, source, created, problems);
                foreach (string problem in problems) report.Add("warn", "Element " + sourceId + ": " + problem);
            }

            if (tags.Count > 0)
            {
                var problems = new List<string>();
                report.TagsKept += TransferTags(doc, tags, source, created, problems);
                foreach (string problem in problems) report.Add("warn", "Element " + sourceId + ": " + problem);
            }

            try
            {
                if (wasPinned) source.Pinned = false;
            }
            catch (Exception)
            {
            }

            doc.Delete(source.Id);

            // the pin goes on inside the run; the adjust window releases it and puts it back, so a pinned replacement can still be rotated
            if (wasPinned)
            {
                try
                {
                    created.Pinned = true;
                    report.Pinned++;
                }
                catch (Exception)
                {
                    report.Add("warn", "Element " + sourceId + ": the original was pinned and the replacement would not take the pin.");
                }
            }

            report.Replaced++;
            report.CircuitsDropped += dropped;
            report.NewIds.Add(created.Id);
            if (failedParams.Count > 0) report.Add("warn", "Element " + sourceId + ": " + string.Join("; ", failedParams));
            return true;
        }

        // ---- the post-run adjust ----------------------------------------------------------------------

        /// <summary>
        /// Rotate each replacement about its own insertion point and shift it in Z. Called with the difference
        /// from what is already applied, so the numbers in the window read as absolutes. With aboutCentre set
        /// (detail items from a drafting view) each one turns about its own drawn centre and its view's normal
        /// instead, and there is no Z.
        /// </summary>
        public static int AdjustElements(Document doc, List<ElementId> elementIds, double deltaDegrees, double deltaZMm, bool aboutCentre,
                                         List<string> problems)
        {
            double angle = deltaDegrees * Math.PI / 180.0;
            double dz = aboutCentre ? 0.0 : MmToFt(deltaZMm);
            if (Math.Abs(angle) < 1.0e-9 && Math.Abs(dz) < PointTolFt) return 0;

            int moved = 0;
            var transaction = new Transaction(doc, "RevoBIM adjust replacements");
            try
            {
                transaction.Start();
                FailureHandlingOptions options = transaction.GetFailureHandlingOptions();
                options.SetFailuresPreprocessor(new WarningSwallower());
                transaction.SetFailureHandlingOptions(options);
                foreach (ElementId elementId in elementIds)
                {
                    Element element = doc.GetElement(elementId);
                    if (element == null) continue;
                    // a pinned element refuses both transforms, so the pin comes off for the move and goes straight back on
                    bool wasPinned = false;
                    try
                    {
                        wasPinned = element.Pinned;
                        if (wasPinned) element.Pinned = false;
                    }
                    catch (Exception)
                    {
                        wasPinned = false;
                    }
                    try
                    {
                        if (Math.Abs(angle) > 1.0e-9)
                        {
                            XYZ point;
                            XYZ normal;
                            if (aboutCentre)
                            {
                                View view = OwnerView(doc, element);
                                string route;
                                point = MeasureCentre(doc, element, view, null, out route);
                                XYZ right, up;
                                ViewAxes(view, out right, out up, out normal);
                            }
                            else
                            {
                                point = InstancePoint(element);
                                normal = XYZ.BasisZ;
                            }
                            if (point != null)
                            {
                                Line axis = Line.CreateBound(point, point + normal);
                                ElementTransformUtils.RotateElement(doc, elementId, axis, angle);
                            }
                        }
                        if (Math.Abs(dz) > PointTolFt) ElementTransformUtils.MoveElement(doc, elementId, new XYZ(0.0, 0.0, dz));
                        moved++;
                    }
                    catch (Exception err)
                    {
                        problems.Add("Element " + Eid(elementId) + ": " + err.Message);
                    }
                    finally
                    {
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
                    }
                }
                transaction.Commit();
            }
            catch (Exception err)
            {
                try
                {
                    if (transaction.HasStarted()) transaction.RollBack();
                }
                catch (Exception)
                {
                }
                problems.Add(err.Message);
            }
            return moved;
        }

        public static bool SelectElements(UIDocument uidoc, IEnumerable<ElementId> elementIds)
        {
            try
            {
                uidoc.Selection.SetElementIds(elementIds.ToList());
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }
    }
}
