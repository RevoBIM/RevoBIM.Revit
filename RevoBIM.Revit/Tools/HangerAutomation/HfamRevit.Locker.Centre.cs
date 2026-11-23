using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
        public partial class Locker
        {
            private void LockCentre(FamilyInstance inst, Element host, Section sec, V3 q, V3 along, string alongType, string square,
                                    bool unit, string what, List<string> notes)
            {
                string famKey = FamKey(inst);
                string ck = famKey + "|centre";
                string[] kinds = { alongType, square, "StrongReference", "WeakReference", "Left", "Right", "Front", "Back" };
                List<RefItem> cands = Prefer(InstanceRefs(inst, kinds), ck);
                if (cands.Count == 0)
                {
                    Log.Add("   centre lock: the hanger family offers no reference planes to lock with");
                    notes.Add("the hanger family has no reference planes to lock with - in the family editor set the centre plane that runs along the "
                              + what + " to Is Reference: " + RefLabels[alongType]);
                    return;
                }
                int maxTries = MaxTries(ck);
                if (maxTries < 80)
                    Log.Add("   centre lock: this family refused the last two hangers - trying only the first " + Inv(maxTries) + " pairs");
                Level level = LevelOf(inst, q);
                string last = null;
                int tried = 0, targetsSeen = 0;
                var seen = new HashSet<string>(StringComparer.Ordinal);
                var sourcesTried = new List<string>();
                // services: each hanger reference is measured against the centreline (once per line) and only the parallel centre
                // plane(s) are tried; null in the cache = the measuring was not possible (every reference is then tried)
                var prepared = new Dictionary<string, List<RefItem>>(StringComparer.Ordinal);
                string prepProblem = null, measuredLabel = null;
                bool stop = false, evaluatedTried = false;
                for (int vi = 0; vi < 2 && !stop; vi++)
                {
                    View view; string vlabel;
                    if (vi == 0)
                    {
                        if (Plan == null)
                        {
                            Log.Add("   centre lock: the active view is not a plan - using the tool's own lock plan");
                            continue;
                        }
                        string why;
                        if (!PlanShows(Plan, q.Z, out why))
                        {
                            Log.Add("   centre lock: the active plan \"" + ElName(Plan) + "\" does not show the " + what + " (centre at " + Fmm(q.Z) + " mm; " + why
                                    + ") - using the tool's own lock plan");
                            continue;
                        }
                        view = Plan;
                        vlabel = "active plan \"" + ElName(Plan) + "\"";
                    }
                    else
                    {
                        view = DedicatedPlan(level);
                        if (view == null) continue;
                        vlabel = "lock plan \"" + ElName(view) + "\"";
                    }
                    List<TargetSource> sources;
                    if (unit)
                    {
                        sources = new List<TargetSource>
                        {
                            new TargetSource { Key = "unit", Label = "centre planes of the unit",
                                               Get = () => InstanceRefs(host, new[] { "CenterLeftRight", "CenterFrontBack", "StrongReference", "WeakReference" }) },
                        };
                    }
                    else
                        sources = CentreSources(host, sec, view, along, what);
                    foreach (TargetSource ts in sources)
                    {
                        List<RefItem> all;
                        try { all = ts.Get(); }
                        catch (Exception ex)
                        {
                            Log.Add("   centre lock [" + vlabel + " / " + ts.Label + "]: " + ex.Message);
                            continue;
                        }
                        var items = new List<RefItem>();
                        foreach (RefItem it in all)
                        {
                            string sk = StableKey(Doc, it.Ref);
                            if (sk == null || seen.Add(sk + "@" + Inv(Eid(view.Id)))) items.Add(it);
                        }
                        targetsSeen += all.Count;
                        if (items.Count == 0)
                        {
                            if (all.Count == 0) sourcesTried.Add(ts.Label + ": none");
                            continue;
                        }
                        // ---- measure the hanger's references against this centreline (plan line: origin + unit direction)
                        List<RefItem> use = cands;
                        bool measured = false;
                        if (!unit)
                        {
                            double lox = sec.A.X, loy = sec.A.Y, ldx = along.X, ldy = along.Y;
                            Line g0 = items[0].Geo;
                            if (g0 != null)
                            {
                                try
                                {
                                    XYZ d0 = g0.Direction, p0 = g0.Origin;
                                    double l0 = Math.Sqrt(d0.X * d0.X + d0.Y * d0.Y);
                                    if (l0 > 1e-6)
                                    {
                                        lox = p0.X; loy = p0.Y; ldx = d0.X / l0; ldy = d0.Y / l0;
                                    }
                                }
                                catch (Exception) { }
                            }
                            string pk = Fm(lox, 5) + "," + Fm(loy, 5) + "," + Fm(ldx, 6) + "," + Fm(ldy, 6);
                            List<RefItem> pr;
                            if (!prepared.TryGetValue(pk, out pr))
                            {
                                string problem;
                                pr = PrepareCentre(inst, kinds, lox, loy, ldx, ldy, alongType, what, out problem);
                                prepared[pk] = pr;
                                if (problem != null) prepProblem = problem;
                            }
                            if (pr != null)
                            {
                                use = pr;
                                measured = true;
                                if (pr.Count == 0)
                                {
                                    stop = true;   // no parallel centre plane: no view or source can change that
                                    break;
                                }
                                measuredLabel = pr[0].Label;
                            }
                        }
                        string err; int attempts;
                        AlignHit hit;
                        if (measured)
                        {
                            hit = AttemptCentre(view, vlabel, items, use, out err, out attempts);
                            evaluatedTried = true;
                        }
                        else
                            hit = Attempt(view, items, use, maxTries - tried, out err, out attempts);
                        tried += attempts;
                        if (hit != null)
                        {
                            Log.Add("   locked to the " + (unit ? "unit centre" : "centreline") + ": hanger " + hit.CandidateLabel + " <-> " + hit.TargetLabel
                                    + " [" + vlabel + " / " + ts.Label + ", pair " + Inv(attempts) + "]");
                            _worked[ck] = NormLabel(hit.CandidateLabel);
                            _lastSource = ts.Key;
                            Outcome(ck, true);
                            if (!unit && sec.Round && ElevationCentre) LockElevationCentre(inst, host, sec, along, what);
                            return;
                        }
                        last = err ?? last;
                        sourcesTried.Add(ts.Label + ": " + Inv(items.Count) + " target(s) refused" + (err != null ? " (" + err + ")" : ""));
                        Log.Add("   centre lock [" + vlabel + " / " + ts.Label + "]: " + Inv(items.Count) + " target(s) x " + Inv(use.Count)
                                + " hanger reference(s) - Revit refused all" + (err != null ? " (last refusal: " + err + ")" : ""));
                        if (measured) break;   // the planes were measured on the line: another source of the same line adds nothing
                        if (tried >= maxTries) break;
                    }
                    if (tried >= maxTries) break;
                }
                Outcome(ck, false);
                if (targetsSeen == 0)
                {
                    Log.Add("   centre lock: no reference to the " + what + (unit ? " centre planes" : " centreline") + " found anywhere (" + string.Join("; ", sourcesTried) + ")");
                    notes.Add(!unit ? "no centreline reference on the " + what : "the " + what + " family has no centre reference planes");
                }
                else if (unit)
                    notes.Add("the hanger is centred on the " + what + "'s geometry, which is off its centre reference planes - no centre lock");
                else if (prepProblem != null)
                    notes.Add(prepProblem + (evaluatedTried ? " - " + measuredLabel + " was tried anyway and Revit refused it" + (!string.IsNullOrEmpty(last) ? " (" + last + ")" : "") : ""));
                else if (evaluatedTried)
                    notes.Add("Revit refused to align the hanger's " + measuredLabel + " with the " + what + " centreline although it was measured on it"
                              + (!string.IsNullOrEmpty(last) ? " (last refusal: " + last + ")" : "") + " - see the debug log");
                else
                    notes.Add("no reference plane of the hanger lies on the " + what + " centreline (" + Inv(cands.Count) + " tried) - in the "
                              + "family editor set the centre plane that runs along the " + what + " to Is Reference: "
                              + RefLabels[alongType] + (!string.IsNullOrEmpty(last) ? " (last refusal: " + last + ")" : ""));
            }

            /// <summary>Round services: the family's Center (Elevation) plane to the centreline in the lock section (a horizontal
            /// plane contains a level service's centreline). Best effort: logged only.</summary>
            private void LockElevationCentre(FamilyInstance inst, Element host, Section sec, V3 along, string what)
            {
                try
                {
                    double len = Math.Max(FhaCore.VLen(FhaCore.VSub(sec.B, sec.A)), 1e-6);
                    if (Math.Abs(sec.B.Z - sec.A.Z) > 0.001 * len)
                    {
                        Log.Add("   centre elevation lock: the " + what + " slopes - skipped");
                        return;
                    }
                    if (LockElevationSym(inst, host, sec, along, what)) return;
                    List<RefItem> cands = InstanceRefs(inst, new[] { "CenterElevation" });
                    if (cands.Count == 0)
                    {
                        Log.Add("   centre elevation lock: the family offers no Center (Elevation) reference - skipped");
                        return;
                    }
                    ViewSection view = SectionFor(host, sec);
                    if (view == null)
                    {
                        Log.Add("   centre elevation lock: no section view type - skipped");
                        return;
                    }
                    string hid = Inv(Eid(host.Id));
                    List<RefItem> targets = CentrelineRefs(hid + "|s" + Inv(Eid(view.Id)), "section " + ElName(view),
                                                           () => GeoLines(host, view, null), along, sec.A, what);
                    if (targets.Count == 0)
                        targets = CentrelineRefs(hid + "|Coarse", "no view, Coarse", () => GeoLines(host, null, ViewDetailLevel.Coarse), along, sec.A, what);
                    if (targets.Count == 0)
                    {
                        Log.Add("   centre elevation lock: no centreline reference in the lock section - skipped");
                        return;
                    }
                    string err; int attempts;
                    AlignHit hit = Attempt(view, targets, cands, 16, out err, out attempts);
                    if (hit != null)
                        Log.Add("   locked the centre elevation: hanger " + hit.CandidateLabel + " <-> " + what + " centreline");
                    else
                        Log.Add("   centre elevation lock: refused" + (err != null ? " (" + err + ")" : "") + " - the family's Center (Elevation) is not at the " + what + " centre");
                }
                catch (Exception ex)
                {
                    Log.Add("   centre elevation lock: " + ex.Message);
                }
            }
        }
    }
}
