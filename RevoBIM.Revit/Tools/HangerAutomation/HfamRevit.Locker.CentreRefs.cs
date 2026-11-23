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
            // ---- the hanger's references measured against the service centreline
            private const double MoveLimit = 150.0 / MM;   // ft: a centre plane further off than this is not moved onto the centreline
            private const double OnLineTol = 0.001;        // ft (0.3 mm): coincident enough to try the alignment
            private const double FixAngleMax = 0.05;       // rad: a residual rotation up to this is put right
            private const double ParallelTol = 1e-6;       // rad
            private const double RadToDeg = 57.29577951308232;

            /// <summary>One hanger reference measured against the centreline (a plan line).</summary>
            private class RefEval
            {
                public RefItem Item;
                public int Index;
                public string Geo = "none";
                public bool Known, Vertical;
                public double Nx, Ny, Nz;     // plane normal (Nx, Ny unit length in plan)
                public double Angle, Dist;    // rad between plane and line (0 = parallel); signed plan distance (ft)
                public int Prio = 2;          // 0 = Center (Left/Right | Front/Back), 1 = named centre, 2 = other
                public string Note = "";
            }

            private static int CentrePrio(RefItem it)
            {
                if (it.Type == "CenterLeftRight" || it.Type == "CenterFrontBack") return 0;
                string n = (it.Name ?? "").ToLowerInvariant();
                // a plane NAMED like a centre plane counts whatever its FamilyInstanceReferenceType (families often leave the centre
                // plane as a weak / strong reference: "Center (Front/Back)" in the family editor)
                if ((n.Contains("front/back") || n.Contains("front / back")) && (n.Contains("center") || n.Contains("centre"))) return 0;
                if (n.Contains("front/back") || n.Contains("front / back")) return 1;
                if (n.Contains("center") || n.Contains("centre") || n == "cl" || n == "c/l" || n.StartsWith("cl ", StringComparison.Ordinal)) return 1;
                return 2;
            }

            private RefEval EvalRef(FamilyInstance inst, RefItem it, int index, double lox, double loy, double ldx, double ldy)
            {
                RefEval e = new RefEval { Item = it, Index = index, Prio = CentrePrio(it) };
                XYZ n = null, o = null;
                string err = null;
                GeometryObject g = null;
                try { g = inst.GetGeometryObjectFromReference(it.Ref); }
                catch (Exception ex) { err = ex.Message; }
                PlanarFace pf = g as PlanarFace;
                Line ln = g as Line;
                try
                {
                    if (pf != null) { e.Geo = "PlanarFace"; n = pf.FaceNormal; o = pf.Origin; }
                    else if (ln != null)
                    {
                        e.Geo = "Line";
                        XYZ d = ln.Direction;
                        double dl = Math.Sqrt(d.X * d.X + d.Y * d.Y);
                        if (dl > 1e-9 && Math.Abs(d.Z) < 1e-4) { n = new XYZ(-d.Y / dl, d.X / dl, 0.0); o = ln.Origin; }
                        else e.Note += " (line is not horizontal)";
                    }
                    else if (g != null) e.Geo = g.GetType().Name;
                    else if (err != null) e.Note += " (geometry: " + err.Replace("\r", " ").Replace("\n", " ") + ")";
                }
                catch (Exception ex) { e.Note += " (geometry read: " + ex.Message.Replace("\r", " ").Replace("\n", " ") + ")"; n = null; }
                if (n == null && (it.Type == "CenterLeftRight" || it.Type == "CenterFrontBack"))
                {
                    // no geometry for the reference: a Center plane passes through the instance origin, normal = hand / facing
                    try
                    {
                        XYZ v = it.Type == "CenterLeftRight" ? inst.HandOrientation : inst.FacingOrientation;
                        n = new XYZ(v.X, v.Y, v.Z);
                        o = ((LocationPoint)inst.Location).Point;
                        e.Geo += " -> assumed through the origin";
                    }
                    catch (Exception) { n = null; }
                }
                try
                {
                    XYZ gp = it.Ref.GlobalPoint;
                    if (gp != null) e.Note += ", global point (" + Fm(gp.X * MM, 1) + ", " + Fm(gp.Y * MM, 1) + ", " + Fm(gp.Z * MM, 1) + ") mm";
                }
                catch (Exception) { }
                if (n == null || o == null) return e;
                try
                {
                    // geometry of an instance reference should be in model coordinates; if it sits far from the instance it is
                    // in family coordinates - bring it over with the instance transform
                    XYZ io = ((LocationPoint)inst.Location).Point;
                    if (o.DistanceTo(io) > 30.0)
                    {
                        Transform tf = inst.GetTransform();
                        o = tf.OfPoint(o);
                        n = tf.OfVector(n);
                        e.Note += " (geometry was in family coordinates - transformed by the instance)";
                    }
                }
                catch (Exception) { }
                double nl = Math.Sqrt(n.X * n.X + n.Y * n.Y);
                double nn = Math.Sqrt(n.X * n.X + n.Y * n.Y + n.Z * n.Z);
                if (nl < 1e-9 || nn < 1e-9)
                {
                    e.Note += " (horizontal plane)";
                    return e;
                }
                e.Known = true;
                e.Nx = n.X / nl; e.Ny = n.Y / nl; e.Nz = n.Z / nn;
                e.Vertical = Math.Abs(e.Nz) < 1e-4;
                double dot = Math.Abs(e.Nx * ldx + e.Ny * ldy);
                e.Angle = Math.Asin(Math.Min(1.0, dot));
                e.Dist = (o.X - lox) * e.Nx + (o.Y - loy) * e.Ny;
                e.Note += ", origin (" + Fm(o.X * MM, 1) + ", " + Fm(o.Y * MM, 1) + ", " + Fm(o.Z * MM, 1) + ") mm";
                return e;
            }

            private List<RefEval> EvalRefs(FamilyInstance inst, List<RefItem> items, double lox, double loy, double ldx, double ldy, bool log)
            {
                var res = new List<RefEval>();
                for (int i = 0; i < items.Count; i++)
                {
                    RefEval e = EvalRef(inst, items[i], i, lox, loy, ldx, ldy);
                    res.Add(e);
                    if (!log) continue;
                    string m = "   centre lock candidate " + Inv(i + 1) + "/" + Inv(items.Count) + " " + items[i].Label + " [" + items[i].Type + "]: geometry " + e.Geo;
                    if (e.Known)
                        m += ", normal (" + Fm(e.Nx, 6) + ", " + Fm(e.Ny, 6) + ", " + Fm(e.Nz, 6) + "), " + (e.Vertical ? "vertical" : "NOT vertical")
                             + ", angle to the centreline " + Fm(e.Angle, 7) + " rad (" + Fm(e.Angle * RadToDeg, 5) + " deg), parallel: "
                             + (e.Vertical && e.Angle <= FixAngleMax ? (e.Angle <= ParallelTol ? "yes" : "nearly") : "no")
                             + ", offset from the centreline " + Fm(e.Dist * MM, 3) + " mm";
                    else
                        m += ", not evaluable";
                    Log.Add(m + e.Note);
                }
                return res;
            }

            /// <summary>Parallel (or nearly), vertical planes that may be the hanger's centre plane, best first: centre planes within
            /// 150 mm of the centreline, or any plane already on it.</summary>
            private static List<RefEval> Eligible(List<RefEval> ev, string alongType)
            {
                return ev.Where(e => e.Known && e.Vertical && e.Angle <= FixAngleMax
                                     && ((e.Prio <= 1 && Math.Abs(e.Dist) <= MoveLimit) || Math.Abs(e.Dist) <= OnLineTol))
                         .OrderBy(e => e.Prio).ThenBy(e => e.Item.Type == alongType ? 0 : 1).ThenBy(e => Math.Abs(e.Dist)).ThenBy(e => e.Index).ToList();
            }


            private void Regen(string why)
            {
                try { Doc.Regenerate(); }   // orientation, planes and references of an instance just rotated / moved are stale until then
                catch (Exception ex) { Log.Add("   centre lock: regenerate after " + why + ": " + ex.Message); }
            }

            /// <summary>Measures every hanger reference against the centreline (plan line lox/loy + unit direction ldx/ldy), picks
            /// the parallel centre plane nearest to it, puts the hanger exactly onto it (rotating by a residual angle, then
            /// moving sideways) and returns the 1-3 references worth an alignment attempt, best first. Empty list: no
            /// parallel centre plane (problem says why). Null: nothing could be measured (the caller tries every reference).
            /// Caller holds the transaction.</summary>
            private List<RefItem> PrepareCentre(FamilyInstance inst, string[] kinds, double lox, double loy, double ldx, double ldy,
                                                string alongType, string what, out string problem)
            {
                problem = null;
                Log.Add("   centre lock: measuring the hanger's references against the " + what + " centreline (through (" + Fm(lox * MM, 1) + ", " + Fm(loy * MM, 1)
                        + ") mm, direction (" + Fm(ldx, 6) + ", " + Fm(ldy, 6) + "))");
                List<RefItem> raw = InstanceRefs(inst, kinds);
                List<RefEval> ev = EvalRefs(inst, raw, lox, loy, ldx, ldy, true);
                if (!ev.Any(e => e.Known))
                {
                    Log.Add("   centre lock: no reference of the hanger could be measured - trying every reference");
                    return null;
                }
                List<RefEval> good = Eligible(ev, alongType);
                if (good.Count == 0)
                {
                    var par = ev.Where(e => e.Known && e.Vertical && e.Angle <= FixAngleMax).ToList();
                    if (par.Count == 0)
                        problem = "no reference plane of the hanger family runs along the " + what + " (" + Inv(ev.Count(e => e.Known)) + " measured, all cross it"
                                  + (ev.Any(e => !e.Known) ? "; " + Inv(ev.Count(e => !e.Known)) + " could not be measured" : "")
                                  + ") - in the family editor set the centre plane that runs along the " + what + " to Is Reference: " + RefLabels[alongType];
                    else
                        problem = "the hanger's reference plane(s) along the " + what + " are not on its centreline: "
                                  + string.Join(", ", par.Select(e => e.Item.Label + " " + Fm(e.Dist * MM, 1) + " mm off"))
                                  + (par.Any(e => e.Prio <= 1) ? " (a centre plane is only moved up to 150 mm)" : " (none of them is a centre plane)");
                    Log.Add("   centre lock: " + problem);
                    // the family settings say which centre plane runs along the service: if the measuring disagrees, the measuring may be
                    // the one that is wrong (e.g. geometry in another coordinate system) - still try that plane, so Revit has the last word
                    var pref = raw.Where(r => r.Type == alongType).Take(3).ToList();
                    if (pref.Count > 0)
                    {
                        Log.Add("   centre lock: trying " + string.Join("; ", pref.Select(r => r.Label)) + " anyway (the family settings name it as the plane along the run)");
                        return pref;
                    }
                    return new List<RefItem>();
                }
                RefEval pick = good[0];
                string pickLabel = pick.Item.Label;
                int idx = pick.Index;
                Log.Add("   centre lock: centre plane chosen: " + pickLabel + " (offset " + Fm(pick.Dist * MM, 3) + " mm, angle " + Fm(pick.Angle, 7) + " rad)");
                Func<RefEval> again = () =>
                {
                    List<RefItem> r2 = InstanceRefs(inst, kinds);
                    List<RefEval> e2 = EvalRefs(inst, r2, lox, loy, ldx, ldy, false);
                    if (idx < e2.Count && e2[idx].Item.Label == pickLabel) return e2[idx];
                    return e2.FirstOrDefault(x => x.Item.Label == pickLabel);
                };
                // ---- residual rotation: the plane must be parallel to the line to ~1e-6 rad
                if (pick.Angle > ParallelTol)
                {
                    try
                    {
                        double px = -pick.Ny, py = pick.Nx;   // the plane's own plan direction, turned to point with the line
                        double dot = px * ldx + py * ldy;
                        if (dot < 0) { px = -px; py = -py; dot = -dot; }
                        double rot = Math.Atan2(px * ldy - py * ldx, dot);
                        XYZ org = ((LocationPoint)inst.Location).Point;
                        Line axis = Line.CreateBound(org, new XYZ(org.X, org.Y, org.Z + 1.0));
                        ElementTransformUtils.RotateElement(Doc, inst.Id, axis, rot);
                        Regen("the residual rotation");
                        Log.Add("   centre lock: rotated the hanger by " + Fm(rot, 8) + " rad (" + Fm(rot * RadToDeg, 6) + " deg) about its origin to make " + pickLabel + " parallel");
                        RefEval r = again();
                        if (r != null && r.Known)
                        {
                            pick = r;
                            Log.Add("   centre lock: after the rotation: angle " + Fm(r.Angle, 8) + " rad, offset " + Fm(r.Dist * MM, 3) + " mm");
                        }
                    }
                    catch (Exception ex) { Log.Add("   centre lock: residual rotation: " + ex.Message); }
                }
                // ---- sideways move: the plane must lie on the centreline
                if (Math.Abs(pick.Dist) > 1e-6)
                {
                    try
                    {
                        double dd = pick.Dist;
                        ElementTransformUtils.MoveElement(Doc, inst.Id, new XYZ(-dd * pick.Nx, -dd * pick.Ny, 0.0));
                        Regen("the sideways move");
                        Log.Add("   centre lock: moved the hanger " + Fm(Math.Abs(dd) * MM, 3) + " mm sideways so " + pickLabel + " lies on the centreline");
                        RefEval r = again();
                        if (r != null && r.Known)
                        {
                            pick = r;
                            Log.Add("   centre lock: after the move: angle " + Fm(r.Angle, 8) + " rad, offset " + Fm(r.Dist * MM, 4) + " mm");
                        }
                    }
                    catch (Exception ex) { Log.Add("   centre lock: sideways move by " + Fm(Math.Abs(pick.Dist) * MM, 3) + " mm: " + ex.Message); }
                }
                // ---- what to try now: whatever is on the centreline, centre planes first (never more than 3)
                List<RefItem> raw2 = InstanceRefs(inst, kinds);
                List<RefEval> ev2 = EvalRefs(inst, raw2, lox, loy, ldx, ldy, false);
                var fin = ev2.Where(e => e.Known && e.Vertical && e.Angle <= 1e-5 && Math.Abs(e.Dist) <= OnLineTol)
                             .OrderBy(e => e.Item.Label == pickLabel ? 0 : 1).ThenBy(e => e.Prio).ThenBy(e => Math.Abs(e.Dist)).ThenBy(e => e.Index)
                             .Take(3).Select(e => e.Item).ToList();
                if (fin.Count == 0)
                {
                    RefEval r = again();
                    if (r != null) fin.Add(r.Item);
                    Log.Add("   centre lock: nothing lies on the centreline within 0.3 mm after the correction - trying " + pickLabel + " anyway");
                }
                Log.Add("   centre lock: will try " + string.Join("; ", fin.Select(f => f.Label)));
                return fin;
            }

            /// <summary>Centreline against the measured hanger references, both orders (Revit moves the second element; the planes
            /// already coincide), in a sub-transaction kept only when an alignment was made. Logs every refusal and the lock state.</summary>
            private AlignHit AttemptCentre(View view, string vlabel, List<RefItem> targets, List<RefItem> cands, out string err, out int attempts)
            {
                SubTransaction st = null;
                try
                {
                    st = new SubTransaction(Doc);
                    st.Start();
                }
                catch (Exception)
                {
                    st = null;
                }
                AlignHit hit = null;
                err = null;
                attempts = 0;
                try
                {
                    foreach (RefItem c in cands)
                    {
                        foreach (RefItem t in targets)
                        {
                            for (int order = 0; order < 2 && hit == null; order++)
                            {
                                attempts++;
                                string ord = order == 0 ? "centreline first" : "hanger plane first";
                                try
                                {
                                    Dimension dim = order == 0 ? Doc.Create.NewAlignment(view, t.Ref, c.Ref) : Doc.Create.NewAlignment(view, c.Ref, t.Ref);
                                    hit = new AlignHit { TargetLabel = t.Label, CandidateLabel = c.Label };
                                    string lockState = "?";
                                    try
                                    {
                                        if (dim != null)
                                        {
                                            lockState = dim.IsLocked ? "locked" : "not locked";
                                            if (!dim.IsLocked)
                                            {
                                                dim.IsLocked = true;
                                                lockState += " -> set to locked (" + (dim.IsLocked ? "ok" : "still unlocked") + ")";
                                            }
                                        }
                                    }
                                    catch (Exception ex) { lockState += " (lock: " + ex.Message.Replace("\r", " ").Replace("\n", " ") + ")"; }
                                    Log.Add("   centre lock attempt [" + vlabel + "]: " + c.Label + " <-> " + t.Label + " (" + ord + "): alignment made, " + lockState);
                                }
                                catch (Exception ex)
                                {
                                    err = ex.Message;
                                    Log.Add("   centre lock attempt [" + vlabel + "]: " + c.Label + " <-> " + t.Label + " (" + ord + "): refused - "
                                            + ex.Message.Replace("\r", " ").Replace("\n", " "));
                                }
                            }
                            if (hit != null) break;
                        }
                        if (hit != null) break;
                    }
                }
                finally
                {
                    if (st != null)
                    {
                        try
                        {
                            if (hit != null) st.Commit();
                            else st.RollBack();
                        }
                        catch (Exception) { }
                    }
                }
                if (hit != null) err = null;
                return hit;
            }

            /// <summary>One attempt group - every target against every hanger reference in one view - in a sub-transaction
            /// kept only when an alignment was made.</summary>
            private AlignHit Attempt(View view, List<RefItem> targets, List<RefItem> cands, int maxTries, out string err, out int attempts)
            {
                SubTransaction st = null;
                try
                {
                    st = new SubTransaction(Doc);
                    st.Start();
                }
                catch (Exception)
                {
                    st = null;
                }
                AlignHit hit = null;
                err = null;
                attempts = 0;
                try
                {
                    hit = TryAlign(Doc, view, targets, cands, Log, maxTries, out err, out attempts);
                }
                finally
                {
                    if (st != null)
                    {
                        try
                        {
                            if (hit != null) st.Commit();
                            else st.RollBack();
                        }
                        catch (Exception) { }
                    }
                }
                return hit;
            }
        }
    }
}
