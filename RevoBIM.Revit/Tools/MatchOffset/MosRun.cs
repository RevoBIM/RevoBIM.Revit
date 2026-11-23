using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.MatchOffset
{
    /// <summary>The slope settings, resolved once before the first pick.</summary>
    public sealed class MosConfig
    {
        public Dictionary<string, string> Settings;
        public bool MatchSlope, Trim, HandFitting, SquareBranch, Apparent, ExtendMain, InLine, Pairs, Debug;
        public string Source, Direction, Fitting, ShowResults;
        public double FixedN, StubMm, Steep, EndTol, InlineDeg, Lateral;
        public int Limit;

        public MosConfig(Dictionary<string, string> settings)
        {
            Settings = settings;
            MatchSlope = MoCore.IsOn(settings, "slope_match_slope");
            string source = MoCore.Get(settings, "slope_source");
            Source = MatchSlope ? source : MosGeom.KeepSlope;
            FixedN = MoCore.ParseNumber(MoCore.Get(settings, "slope_fixed_n"), 80.0);
            Direction = MoCore.Get(settings, "slope_direction");
            Trim = MoCore.IsOn(settings, "slope_trim");
            Fitting = MoCore.Get(settings, "slope_fitting");
            HandFitting = MoCore.IsOn(settings, "slope_hand_fitting");
            SquareBranch = MoCore.IsOn(settings, "slope_square_branch");
            StubMm = MoCore.ParseNumber(MoCore.Get(settings, "slope_stub_mm"), 0.0);
            Apparent = MoCore.IsOn(settings, "slope_apparent");
            ExtendMain = MoCore.IsOn(settings, "slope_extend_main");
            Steep = MoCore.ParseNumber(MoCore.Get(settings, "slope_steep_deg"), 46.0);
            Limit = (int)MoCore.ParseNumber(MoCore.Get(settings, "slope_limit"), 400.0);
            double endTolMm = MoCore.ParseNumber(MoCore.Get(settings, "slope_end_tol_mm"), 1.0);
            EndTol = (endTolMm == 0 ? 1.0 : endTolMm) / MosGeom.MmPerFt;
            InlineDeg = MoCore.ParseNumber(MoCore.Get(settings, "slope_inline_deg"), 2.0);
            InLine = MoCore.IsOn(settings, "slope_in_line");
            Pairs = MoCore.Get(settings, "slope_repeat") == "pairs";
            double lateralMm = MoCore.ParseNumber(MoCore.Get(settings, "slope_inline_offset_mm"), 50.0);
            Lateral = (lateralMm == 0 ? 50.0 : lateralMm) / MosGeom.MmPerFt;
            ShowResults = MoCore.Get(settings, "show_results");
            Debug = MoCore.IsOn(settings, "debug_report");
        }
    }

    /// <summary>The pipe whose fall and elevation are right.</summary>
    public sealed class MosMain
    {
        public readonly Element Element;
        public readonly ElementId Id;
        public readonly MosPt Start, End;
        public readonly double? Gradient;

        public MosMain(Element element)
        {
            Element = element;
            Id = element.Id;
            MosPt[] ends = MosModel.EndsOf(element);
            if (ends != null)
            {
                Start = ends[0];
                End = ends[1];
                Gradient = MosGeom.Gradient(Start, End);
            }
        }

        public string Describe()
        {
            double? fall = MosGeom.OneInN(Gradient);
            return fall.HasValue ? "1 in " + MoCore.FormatMm(fall.Value, 0) : "level";
        }
    }

    /// <summary>
    /// Match Offset Slope: click the main, then click a branch. The branch's horizontal run goes onto the main's fall,
    /// its free end lands on the main's centreline where the two cross in plan, and a fitting goes in. One transaction
    /// per branch, because the picks sit between the writes; the fitting sits in its own transaction inside a group so
    /// a refused fitting never costs the move. Port of mos_run.py.
    /// </summary>
    public static class MosRun
    {
        private static MosMain TakeMain(Document doc, Element element, MosConfig config, MoReport report)
        {
            if (!MosModel.IsPipe(element))
            {
                report.Problem(MoModel.Describe(element) + " is not a pipe");
                return null;
            }
            if (!MosModel.IsStraight(element))
            {
                report.Problem(MoModel.Describe(element) + " is not a straight segment");
                return null;
            }
            var main = new MosMain(element);
            if (main.Start == null)
            {
                report.Problem(MoModel.Describe(element) + " has no usable centreline");
                return null;
            }
            if (MosGeom.PlanLength(main.Start, main.End) < config.EndTol)
            {
                report.Problem(MoModel.Describe(element) + " is vertical - the main has to be a run in plan");
                return null;
            }
            MoCore.Log("main " + MoModel.Describe(element) + " at " + main.Describe());
            if (report.Debug != null)
            {
                report.Debug.Section("the main");
                report.Debug.Pair("element", MoModel.Describe(element));
                report.Debug.Pair("start", MoRecorder.Pt(main.Start));
                report.Debug.Pair("end", MoRecorder.Pt(main.End));
                report.Debug.Pair("plan length", MoRecorder.Mm(MosGeom.PlanLength(main.Start, main.End)) + " mm");
                report.Debug.Pair("gradient", MoRecorder.Fall(main.Gradient));
            }
            return main;
        }

        /// <summary>The connector on the end of the main the crossing is nearest to.</summary>
        private static Connector MainEndConnector(MosMain main, MosPt crossing, double tolerance, out MosPt near)
        {
            near = MosGeom.PlanLength(main.Start, crossing) <= MosGeom.PlanLength(main.End, crossing) ? main.Start : main.End;
            return MosModel.ConnectorAt(main.Element, near, Math.Max(tolerance, 1.0 / MosGeom.MmPerFt));
        }

        /// <summary>How far off the main's own line the branch arrives, 0 to 90.</summary>
        private static double OffTheLine(double angle) { return Math.Min(Math.Abs(angle), Math.Abs(180.0 - Math.Abs(angle))); }

        // ======================================================================
        // one branch
        // ======================================================================

        /// <summary>Put one branch run on the main's fall and join it. True when it moved.</summary>
        private static bool MatchBranch(Document doc, MosMain main, Element element, MosConfig config, MoReport report)
        {
            string name = MoModel.Describe(element);

            if (element.Id.Value == main.Id.Value)
            {
                report.Problem("that is the main itself");
                return false;
            }
            if (!MosModel.IsPipe(element))
            {
                report.Problem(name + " is not a pipe");
                return false;
            }
            if (!MosModel.IsStraight(element))
            {
                report.Problem(name + " is not a straight segment");
                return false;
            }

            double pitch = MosModel.PitchOf(element);
            if (pitch > config.Steep)
            {
                report.Problem(name + " is pitched " + MoCore.FormatMm(pitch) +
                               " degrees, so it is an upright rather than a horizontal run - click the pipe the stack comes off");
                return false;
            }

            MosRunBody body = MosModel.WalkRun(doc, element, config.Steep, config.Limit);
            if (body.Refusal.Length > 0)
            {
                report.Problem(name + ": " + body.Refusal);
                return false;
            }
            if (body.Pipes.Count == 0)
            {
                report.Problem(name + ": nothing in the run could be moved");
                return false;
            }

            // Which end faces the main has to be decided before the crossing is known, so the point on the main nearest
            // this pipe stands in for it.
            MosPt[] ends = MosModel.EndsOf(element);
            var middle = new MosPt((ends[0].X + ends[1].X) / 2.0, (ends[0].Y + ends[1].Y) / 2.0, (ends[0].Z + ends[1].Z) / 2.0);
            MosPt towards = MosModel.ProjectOnto(main.Element, middle);

            MosEndPick picked = MosModel.FreeEndOf(body, towards);
            if (picked == null)
            {
                report.Problem(name + ": the run has no end to bring to the main");
                return false;
            }
            Element endPipe = picked.Pipe;
            MosConKey freeKey = MosModel.ConnectorKey(picked.Connector);
            MosPt freePoint = MosModel.ToPt(picked.Connector.Origin);
            MosPt anchor = MosModel.AnchorOf(endPipe, picked.Connector);
            if (anchor == null)
            {
                report.Problem(name + ": the end pipe has no usable centreline");
                return false;
            }

            MosPt nearEnd;
            Connector mainConnector = MainEndConnector(main, freePoint, config.EndTol, out nearEnd);
            bool mainEndFree = mainConnector != null && !MosModel.IsJoined(mainConnector);

            MosPlan plan = MosGeom.BuildPlan(main.Start, main.End, anchor, freePoint, config.Source, config.Direction, config.FixedN,
                                             config.EndTol, config.Apparent, mainEndFree, config.InlineDeg, config.InLine, config.Lateral);

            if (report.Debug != null)
            {
                MoRecorder debug = report.Debug;
                debug.Section("branch " + MoModel.Describe(element));
                debug.Pair("run walked", body.Count + " elements, " + body.Pipes.Count + " pipes, " + body.Uprights.Count + " uprights");
                debug.Pair("end pipe", MoModel.Describe(endPipe));
                debug.Pair("end was joined and freed", picked.Borrowed);
                debug.Pair("anchor", MoRecorder.Pt(anchor));
                debug.Pair("free end", MoRecorder.Pt(freePoint));
                debug.Pair("branch gradient", MoRecorder.Fall(plan.BranchGradient));
                debug.Pair("target gradient", MoRecorder.Fall(plan.TargetGradient));
                debug.Pair("t along the main", plan.Ta.ToString("F6"));
                debug.Pair("t along the branch", plan.Tb.ToString("F6"));
                debug.Pair("crossing", MoRecorder.Pt(plan.Crossing));
                debug.Pair("off the main's line in plan", MoRecorder.Mm(plan.Lateral) + " mm");
                debug.Pair("main case", plan.MainCase);
                debug.Pair("branch case", plan.BranchCase);
                debug.Pair("junction", plan.Junction);
                debug.Pair("plan angle", plan.PlanAngle.ToString("F2") + " degrees, " + OffTheLine(plan.PlanAngle).ToString("F2") + " off the main line");
                debug.Pair("main end nearest", MoRecorder.Pt(nearEnd));
                debug.Pair("that end is free", mainEndFree);
                debug.Pair("extends the main", plan.ExtendsMain);
                debug.Pair("plan accepted", plan.Ok);
                if (!plan.Ok) debug.Pair("refused because", plan.Refusal);
            }

            if (!plan.Ok)
            {
                report.Problem(name + ": " + MosGeom.RefusalText(plan.Refusal));
                return false;
            }

            if (plan.ExtendsMain && !config.ExtendMain)
            {
                report.Problem(name + ": the crossing falls " + MoCore.FormatMm(MoCore.FtToMm(MosGeom.PlanLength(nearEnd, plan.Crossing))) +
                               " mm past the end of the main, and extending the main is turned off in Settings");
                return false;
            }

            return DoTheMove(doc, main, element, body, endPipe, freeKey, anchor, plan, config, report, picked.Borrowed, mainConnector);
        }

        /// <summary>
        /// The move and the junction, as two transactions inside one group. Two, because a fitting Revit refuses must not
        /// cost the move: with both in one transaction an unresolved error at the fitting rolls the whole thing back.
        /// </summary>
        private static bool DoTheMove(Document doc, MosMain main, Element element, MosRunBody body, Element endPipe, MosConKey freeKey, MosPt anchor,
                                      MosPlan plan, MosConfig config, MoReport report, bool borrowed, Connector mainConnector)
        {
            string name = MoModel.Describe(element);
            var pinned = new List<ElementId>();
            var group = new TransactionGroup(doc, "RevoBIM Match Offset Slope");
            group.Start();
            Transaction transaction = null;
            TransactionStatus status;
            try
            {
                transaction = MoRun.StartTransaction(doc, "RevoBIM Match Offset Slope - move");

                foreach (ElementId elementId in body.Ids)
                {
                    Element item = doc.GetElement(elementId);
                    if (item != null && MoModel.IsPinned(item))
                    {
                        pinned.Add(elementId);
                        try
                        {
                            item.Pinned = false;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }

                if (borrowed)
                {
                    // A run with no spare end has the joint nearest the main freed and used instead, rather than the run being refused.
                    Connector connector = MosModel.ConnectorByKey(doc, freeKey);
                    if (connector != null)
                    {
                        MosModel.UnjoinAll(connector);
                        doc.Regenerate();
                    }
                }

                List<MosUprightLink> links = MosModel.ReleaseUprights(doc, body);

                Connector free = MosModel.ConnectorByKey(doc, freeKey);
                MosPt pivot = free != null ? MosModel.ToPt(free.Origin) : plan.Crossing;
                MosModel.RotateBody(doc, body.Ids, pivot, plan.Axis, plan.Tilt);
                doc.Regenerate();

                // After the tilt the anchor has moved, so the end pipe is re-read rather than the pre-tilt point being reused.
                Element movedPipe = doc.GetElement(endPipe.Id);
                free = MosModel.ConnectorByKey(doc, freeKey);
                if (movedPipe == null || free == null) throw new Exception("the end pipe went missing after the tilt");
                MosPt liveFree = MosModel.ToPt(free.Origin);
                MosPt[] ends = MosModel.EndsOf(movedPipe);
                MosPt fixedEnd = MosGeom.Length(ends[0], liveFree) < MosGeom.Length(ends[1], liveFree) ? ends[1] : ends[0];

                double[] direction = MosGeom.Unit3(fixedEnd, liveFree);
                MosPt landing = direction == null ? null : MosGeom.StretchToPlanPoint(fixedEnd, direction, plan.Crossing.X, plan.Crossing.Y);
                if (landing == null) throw new Exception("the run does not reach the crossing");

                if (report.Debug != null)
                {
                    report.Debug.Pair("end pipe before the stretch", MoRecorder.Pt(ends[0]) + " -> " + MoRecorder.Pt(ends[1]));
                    report.Debug.Pair("end staying put", MoRecorder.Pt(fixedEnd));
                    report.Debug.Pair("end going to", MoRecorder.Pt(landing));
                }

                if (config.Trim)
                {
                    string order;
                    if (!MosModel.Restretch(movedPipe, fixedEnd, landing, out order))
                        throw new Exception("the end pipe would not stretch: " + order);
                    doc.Regenerate();
                    if (report.Debug != null)
                    {
                        MosPt[] after = MosModel.EndsOf(doc.GetElement(endPipe.Id));
                        report.Debug.Pair("curve order kept", order);
                        report.Debug.Pair("end pipe after the stretch", MoRecorder.Pt(after[0]) + " -> " + MoRecorder.Pt(after[1]));
                    }
                }

                // The whole residual, not just the lift: in the in-line case the run is nudged sideways onto the main's
                // line as well, because a union will not take two ends a few millimetres apart.
                double shiftX = plan.Crossing.X - landing.X;
                double shiftY = plan.Crossing.Y - landing.Y;
                double shiftZ = plan.Crossing.Z - landing.Z;
                MosModel.MoveBody(doc, body.Ids, shiftX, shiftY, shiftZ);
                doc.Regenerate();

                MosModel.RefitUprights(doc, links, report);

                foreach (ElementId elementId in pinned)
                {
                    Element item = doc.GetElement(elementId);
                    if (item == null) continue;
                    try
                    {
                        item.Pinned = true;
                    }
                    catch (Exception)
                    {
                    }
                }

                report.NotePair("tilt applied, radians", plan.Tilt.ToString("F6"));
                report.NotePair("landing before the lift", MoRecorder.Pt(landing));
                report.NotePair("moved by", MoRecorder.Mm(Math.Sqrt(shiftX * shiftX + shiftY * shiftY)) + " across, " + MoRecorder.Mm(shiftZ) + " up (mm)");
                status = transaction.Commit();
            }
            catch (Exception err)
            {
                try
                {
                    if (transaction != null) transaction.RollBack();
                }
                catch (Exception)
                {
                }
                MoRun.DrainFailures(report, "the move");
                if (report.Debug != null) report.Debug.BlewUp("the move", err.ToString());
                group.RollBack();
                report.Problem(name + ": " + err.Message);
                return false;
            }
            finally
            {
                if (transaction != null) transaction.Dispose();
            }

            List<KeyValuePair<string, string>> found = MoRun.DrainFailures(report, "the move");
            if (!MoRun.Committed(status))
            {
                string said = MoRun.FailureText(found);
                group.RollBack();
                report.Problem(name + ": Revit rolled the move back" + (said.Length > 0 ? " - " + said : " without saying why. The debug report has the numbers."));
                return false;
            }

            string junction = "";
            if (config.Trim && config.Fitting != "none")
                junction = FitJunction(doc, main, endPipe.Id, plan, config, report, mainConnector, name);
            group.Assimilate();

            double? fall = MosGeom.OneInN(plan.TargetGradient);
            string where = plan.MainCase == MosGeom.InLine ? "brought in line with the main" : "brought to the crossing";
            report.Note(name + " put on " + (fall.HasValue ? "1 in " + MoCore.FormatMm(fall.Value, 0) : "level") + " and " + where +
                        (junction.Length > 0 ? " (" + junction + ")" : ""));
            report.MatchedOne();
            MoCore.Log(name + " matched: tilt " + plan.Tilt.ToString("F5") + " rad, case " + plan.MainCase + ", junction " + plan.Junction);
            return true;
        }

        /// <summary>The fitting, in its own transaction so a refusal never costs the move.</summary>
        private static string FitJunction(Document doc, MosMain main, ElementId branchId, MosPlan plan, MosConfig config, MoReport report,
                                          Connector mainConnector, string name)
        {
            Transaction transaction = null;
            string junction;
            TransactionStatus status;
            try
            {
                transaction = MoRun.StartTransaction(doc, "RevoBIM Match Offset Slope - fitting");
                junction = MakeJunction(doc, main, branchId, plan, config, report, mainConnector, name);
                status = transaction.Commit();
            }
            catch (Exception err)
            {
                try
                {
                    if (transaction != null) transaction.RollBack();
                }
                catch (Exception)
                {
                }
                MoRun.DrainFailures(report, "the fitting");
                if (report.Debug != null) report.Debug.BlewUp("the fitting", err.ToString());
                report.Problem(name + ": the move is in, but the fitting threw: " + err.Message);
                return "";
            }
            finally
            {
                if (transaction != null) transaction.Dispose();
            }

            List<KeyValuePair<string, string>> found = MoRun.DrainFailures(report, "the fitting");
            if (!MoRun.Committed(status))
            {
                string said = MoRun.FailureText(found);
                report.Problem(name + ": the move is in, but Revit rolled the fitting back" +
                               (said.Length > 0 ? " - " + said : ". The debug report has the numbers."));
                return "";
            }
            return junction;
        }

        private static string StubAdvice(double angle)
        {
            double off = OffTheLine(angle);
            if (off > 85.0)
                return "The branch meets the main square on, at " + angle.ToString("F1") + " degrees, so a plain tee should have taken.";
            return "The branch arrives at " + angle.ToString("F1") + " degrees to the main, which is " + off.ToString("F1") +
                   " degrees off its line - that needs an oblique or swept junction family, and most pipe types carry only the 90 degree tee.";
        }

        private static string OfferAdvice(List<string> names)
        {
            if (names.Count == 0)
                return "The main's pipe type has no junction or elbow family in its routing preferences at all, so load one and add it " +
                       "under Manage > MEP Settings > Pipe Settings.";
            return "Its pipe type offers " + string.Join("; ", names) + ".";
        }

        /// <summary>How long the square stub out of the tee should be: auto is three diameters with a 150mm floor.</summary>
        private static double StubLength(Document doc, ElementId branchId, MosConfig config)
        {
            if (config.StubMm > 0) return config.StubMm / MosGeom.MmPerFt;
            double diameter = 0.0;
            try
            {
                diameter = MosModel.OutsideDiameter(doc.GetElement(branchId));
            }
            catch (Exception)
            {
            }
            return Math.Max(150.0 / MosGeom.MmPerFt, diameter * 3.0);
        }

        /// <summary>
        /// Trim and extend, then the fitting: what Revit's own command does, replicated because there is no API for it.
        /// Returns what went in ("" when nothing did).
        /// </summary>
        private static string MakeJunction(Document doc, MosMain main, ElementId branchId, MosPlan plan, MosConfig config, MoReport report,
                                           Connector mainConnector, string name)
        {
            Element liveMain = doc.GetElement(main.Id);
            if (liveMain == null)
            {
                report.Problem("the main went missing before the fitting");
                return "";
            }

            if (plan.Junction == MosGeom.Tee)
            {
                string ruleDetail;
                int rules = MosModel.JunctionRules(doc, liveMain, out ruleDetail);
                if (report.Debug != null)
                {
                    report.Debug.Pair("junction rules on the main's type", rules);
                    if (ruleDetail.Length > 0) report.Debug.Pair("routing preferences said", ruleDetail);
                }
                if (rules == 0)
                {
                    report.Problem(StubAdvice(plan.PlanAngle) + " The main's pipe type carries no junction family at all, so the main was left whole " +
                                   "rather than split for a tee that could not be placed. Load a junction family and add it under the pipe type's " +
                                   "Routing Preferences. Both pipes are touching, so Trim/Extend finishes it by hand.");
                    return "";
                }

                MosTeeResult tee = MosModel.PlaceTee(doc, liveMain, branchId, plan.Crossing, config.HandFitting);
                if (report.Debug != null) foreach (string note in tee.Notes) report.Debug.Pair("junction attempt", note);
                if (tee.Fitting != null)
                {
                    if (tee.Method != "tee")
                        report.Note("Revit would not place a square tee at " + plan.PlanAngle.ToString("F1") +
                                    " degrees, so the junction family was placed, sized from the pipes and turned onto the three");
                    return tee.Method;
                }

                // Revit only ever places a tee square to the run, so an angled branch is brought in the way a drainage
                // layout does it: the tee slides along the main, a stub runs square out of it, a bend turns the branch into it.
                if (config.SquareBranch && OffTheLine(plan.PlanAngle) < 85.0)
                {
                    double stub = StubLength(doc, branchId, config);
                    if (report.Debug != null) report.Debug.Pair("squaring stub length", MoRecorder.Mm(stub) + " mm");
                    List<string> squared;
                    Element squaredFitting = MosModel.SquareIntoMain(doc, liveMain, branchId, plan.Crossing, stub, out squared);
                    if (report.Debug != null) foreach (string note in squared) report.Debug.Pair("squaring attempt", note);
                    tee.Notes.AddRange(squared);
                    if (squaredFitting != null)
                    {
                        // A squared junction is reported as something to look at rather than as a note: it is a change of
                        // design intent, so it must not happen quietly.
                        report.Problem(name + " is joined, but squared: no junction family in the pipe type's routing preferences would take the " +
                                       "branch at " + plan.PlanAngle.ToString("F1") + " degrees, so a square tee went into the main with a stub and a " +
                                       "bend turning the branch into it. For a swept drainage junction, load a " + OffTheLine(plan.PlanAngle).ToString("F0") +
                                       " degree junction family and add it to the pipe type's Routing Preferences. The tick for this is on the Slope " +
                                       "tab in Settings.");
                        return "tee, stub and bend";
                    }
                }

                string takeoffError;
                Element takeoff = MosModel.PlaceTakeoff(doc, liveMain, branchId, plan.Crossing, out takeoffError);
                if (takeoff != null)
                {
                    report.Note("the tee was refused, so a takeoff went in instead");
                    return "takeoff";
                }
                MosRoutingOffer offer = MosModel.LogOffer(doc, liveMain, plan.PlanAngle);
                if (report.Debug != null)
                {
                    report.Debug.Pair("routing rule counts", string.Join(", ", offer.Counts.Select(c => c.Key + "=" + c.Value)));
                    if (offer.Detail.Length > 0) report.Debug.Pair("routing preferences said", offer.Detail);
                }
                var tried = new List<string>(tee.Notes) { takeoffError };
                report.Problem("No junction could be placed. " + StubAdvice(plan.PlanAngle) + " " + OfferAdvice(offer.Names) +
                               " Every family was tried and turned onto the three pipes by hand as well. Both pipes are left touching, so Revit's " +
                               "own Trim/Extend finishes it in two clicks. What was tried: " +
                               (tee.Notes.Count > 0 ? string.Join(" | ", tried) : (takeoffError.Length > 0 ? takeoffError : "nothing")));
                return "";
            }

            if (plan.ExtendsMain)
            {
                if (!MosModel.ExtendMain(doc, liveMain, plan.Crossing))
                {
                    report.Problem("the main would not extend to the apparent crossing");
                    return "";
                }
                doc.Regenerate();
            }

            liveMain = doc.GetElement(main.Id);
            Connector connector = MosModel.ConnectorAt(liveMain, plan.Crossing, Math.Max(config.EndTol, 2.0 / MosGeom.MmPerFt));
            if (connector == null)
            {
                report.Problem("the main has no free end at the crossing, so no bend could go in. Both pipes are left touching.");
                return "";
            }
            if (MosModel.IsJoined(connector))
            {
                report.Problem("the main's end at the crossing already has something joined to it. Both pipes are left touching.");
                return "";
            }

            string error;
            Element fitting = MosModel.PlaceBend(doc, MosModel.ConnectorKey(connector), branchId, plan.Crossing, plan.Junction == MosGeom.Union, out error);
            if (fitting != null) return plan.Junction == MosGeom.Union ? "union" : "bend";
            MosRoutingOffer failed = MosModel.LogOffer(doc, liveMain, plan.PlanAngle);
            if (report.Debug != null)
            {
                report.Debug.Pair("routing rule counts", string.Join(", ", failed.Counts.Select(c => c.Key + "=" + c.Value)));
                if (failed.Detail.Length > 0) report.Debug.Pair("routing preferences said", failed.Detail);
            }
            report.Problem("Revit refused the bend. " + StubAdvice(plan.PlanAngle) + " " + OfferAdvice(failed.Names) +
                           " Both pipes are left touching, so Revit's own Trim/Extend finishes it by hand in two clicks. Revit said: " +
                           (error.Length > 0 ? error : "nothing"));
            return "";
        }

        // ======================================================================
        // the loop
        // ======================================================================

        /// <summary>The status line, the tool's only voice while it runs. It carries the count as well as the question.</summary>
        private static string PromptFor(MosMain main, MosConfig config, int done)
        {
            string soFar = done > 0 ? done + " joined - " : "";
            if (main == null) return soFar + "Match Offset Slope: pick the MAIN, the pipe whose fall and elevation are right. Esc to finish";
            if (config.Pairs) return soFar + "Main " + main.Describe() + " - now pick the pipe to bring into it";
            return soFar + "Main " + main.Describe() + " - pick branches to match, Esc to finish";
        }

        public static MoRunResult Run(UIApplication uiapp)
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;
            Dictionary<string, string> settings = MoCore.LoadSettings();
            var report = new MoReport();
            var result = new MoRunResult { Settings = settings, Report = report };

            MoModel.ResetCaches();
            var config = new MosConfig(settings);
            var selectionFilter = new MoModel.OffsetFilter(new[] { "pipes" });

            if (config.Debug)
            {
                report.Debug = new MoRecorder("Match Offset Slope");
                report.Debug.Header(uiapp, doc, settings);
            }

            MosMain main = null;
            int pairs = 0;
            using (new MoDialogGuard(uiapp))
            {
                try
                {
                    while (true)
                    {
                        Reference reference;
                        try
                        {
                            reference = uidoc.Selection.PickObject(ObjectType.Element, selectionFilter, PromptFor(main, config, report.Matched));
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

                        if (main == null)
                        {
                            main = TakeMain(doc, element, config, report);
                            if (main != null && !config.Pairs) report.DatumText = "Main falling " + main.Describe();
                            continue;
                        }

                        if (config.Trim) MoModel.Checkout(doc, new[] { element.Id, main.Id });
                        MatchBranch(doc, main, element, config, report);
                        if (config.Pairs)
                        {
                            // Back to asking for a main, whether that one went in or not. The prompt is the only feedback
                            // there is during a run, so it has to be honest about what it is asking for next.
                            main = null;
                            pairs++;
                        }
                        else
                        {
                            main = new MosMain(doc.GetElement(main.Id));
                        }
                    }
                }
                finally
                {
                    if (config.Pairs) report.DatumText = pairs + " pair" + (pairs == 1 ? "" : "s") + " picked";
                    MoRun.DrainFailures(report, "the rest of the run");
                    if (report.Debug != null)
                    {
                        report.Debug.Tail(report);
                        report.Debug.Save();
                    }
                    MoCore.Log("slope run finished: " + report.Matched + " matched, " + report.Problems.Count + " problems");
                    MoCore.FlushLog();
                }
            }
            return result;
        }
    }
}
