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
            // ------------------------------------------------------------ centre lock
            private static string StableKey(Document doc, Reference r)
            {
                try { return r.ConvertToStableRepresentation(doc); }
                catch (Exception) { return null; }
            }

            /// <summary>The geometry lines of a service that run along it (parallel in plan, on its centreline), as references.
            /// Logs what was found and what was turned away - once, the result is cached.</summary>
            private List<RefItem> CentrelineRefs(string cacheKey, string label, Func<List<Line>> read, V3 along, V3 a, string what)
            {
                List<RefItem> hit;
                if (_targets.TryGetValue(cacheKey, out hit)) return hit;
                var o = new List<RefItem>();
                List<Line> lines;
                try { lines = read(); }
                catch (Exception ex)
                {
                    Log.Add("   centreline [" + label + "]: " + ex.Message);
                    lines = new List<Line>();
                }
                int notAlong = 0, far = 0;
                double nearest = double.MaxValue;
                foreach (Line ln in lines)
                {
                    try
                    {
                        XYZ d = ln.Direction;
                        double xy = Math.Sqrt(d.X * d.X + d.Y * d.Y);
                        if (xy < 1e-6 || Math.Abs((d.X * along.X + d.Y * along.Y) / xy) < 0.9999)
                        {
                            notAlong++;
                            continue;
                        }
                        XYZ p = ln.Origin;
                        double dist = Math.Abs((p.X - a.X) * along.Y - (p.Y - a.Y) * along.X);
                        nearest = Math.Min(nearest, dist);
                        if (dist > 0.02)
                        {
                            far++;
                            continue;
                        }
                        o.Add(new RefItem(ln.Reference, "centreline") { Geo = ln });
                    }
                    catch (Exception) { }
                }
                Log.Add("   centreline [" + label + "] of " + what + ": " + Inv(lines.Count) + " line(s) with a reference, " + Inv(o.Count)
                        + " along the run on its centreline" + (notAlong > 0 ? ", " + Inv(notAlong) + " not along it" : "")
                        + (far > 0 ? ", " + Inv(far) + " off the centreline (nearest " + Fmm(nearest) + " mm)" : ""));
                _targets[cacheKey] = o;
                return o;
            }

            private List<TargetSource> CentreSources(Element host, Section sec, View view, V3 along, string what)
            {
                string hid = Inv(Eid(host.Id));
                string vid = Inv(Eid(view.Id));
                string vname = ElName(view);
                var l = new List<TargetSource>();
                l.Add(new TargetSource
                {
                    Key = "view", Label = "geometry as view \"" + vname + "\" shows it",
                    Get = () => CentrelineRefs(hid + "|v" + vid, "view " + vname, () => GeoLines(host, view, null), along, sec.A, what),
                });
                foreach (ViewDetailLevel dl in new[] { ViewDetailLevel.Coarse, ViewDetailLevel.Medium, ViewDetailLevel.Fine })
                {
                    ViewDetailLevel d2 = dl;
                    l.Add(new TargetSource
                    {
                        Key = d2.ToString(), Label = "geometry at " + d2.ToString() + " detail (no view)",
                        Get = () => CentrelineRefs(hid + "|" + d2.ToString(), "no view, " + d2.ToString(), () => GeoLines(host, null, d2), along, sec.A, what),
                    });
                }
                l.Add(new TargetSource
                {
                    Key = "loc", Label = "location curve reference",
                    Get = () =>
                    {
                        List<RefItem> hit;
                        if (_targets.TryGetValue(hid + "|loc", out hit)) return hit;
                        var o = new List<RefItem>();
                        try
                        {
                            LocationCurve lc = host.Location as LocationCurve;
                            Reference r = lc != null && lc.Curve != null ? lc.Curve.Reference : null;
                            if (r != null) o.Add(new RefItem(r, "location curve"));
                        }
                        catch (Exception) { }
                        Log.Add("   centreline [location curve] of " + what + ": " + (o.Count > 0 ? "a reference" : "no reference"));
                        _targets[hid + "|loc"] = o;
                        return o;
                    },
                });
                if (_lastSource != null)   // what worked last time goes first
                {
                    var first = l.Where(s => s.Key == _lastSource).ToList();
                    if (first.Count > 0)
                    {
                        var re = new List<TargetSource>(first);
                        re.AddRange(l.Where(s => s.Key != _lastSource));
                        l = re;
                    }
                }
                return l;
            }

            /// <summary>Does the plan show a service at height z (its view range)? True when that cannot be read.</summary>
            private bool PlanShows(View view, double z, out string why)
            {
                why = "";
                ViewPlan vp = view as ViewPlan;
                if (vp == null) return true;
                try
                {
                    PlanViewRange r = vp.GetViewRange();
                    double lo = double.MaxValue, hi = double.MinValue;
                    foreach (PlanViewPlane pl in new[] { PlanViewPlane.TopClipPlane, PlanViewPlane.CutPlane, PlanViewPlane.BottomClipPlane, PlanViewPlane.ViewDepthPlane })
                    {
                        ElementId lid = r.GetLevelId(pl);
                        Level lv = lid != null ? Doc.GetElement(lid) as Level : null;
                        if (lv == null)
                        {
                            why = "view range uses a relative level - not checked";
                            return true;
                        }
                        double zz = lv.ProjectElevation + r.GetOffset(pl);
                        lo = Math.Min(lo, zz);
                        hi = Math.Max(hi, zz);
                    }
                    why = "view range " + Fmm(lo) + " .. " + Fmm(hi) + " mm";
                    return z >= lo - 0.01 && z <= hi + 0.01;
                }
                catch (Exception) { return true; }
            }

            /// <summary>The tool's own plan for a level: coarse detail, coordination discipline, a view range that shows everything
            /// on the level - so the duct is in it whatever the user's own plans show. Made once per level, reused by name on later runs.</summary>
            private View DedicatedPlan(Level level)
            {
                if (level == null) return null;
                long lk = Eid(level.Id);
                ViewPlan vp;
                if (_views.Plans.TryGetValue(lk, out vp) && vp != null && Alive(vp)) return vp;
                if (_views.PlanFailed.Contains(lk)) return null;
                _views.Load(Doc);
                string name = LockViews.Prefix + "centre locks " + ElName(level);
                vp = _views.Find(name) as ViewPlan;
                if (vp != null)
                {
                    Log.Add("   lock plan: reusing " + ElName(vp));
                    _views.Plans[lk] = vp;
                    return vp;
                }
                if (_views.PlanVft == null)
                {
                    Log.Add("   lock plan: no floor plan view type in the model");
                    _views.PlanFailed.Add(lk);
                    return null;
                }
                try
                {
                    vp = ViewPlan.Create(Doc, _views.PlanVft.Id, level.Id);
                    try { vp.ViewTemplateId = ElementId.InvalidElementId; }
                    catch (Exception) { }
                    try { vp.Discipline = ViewDiscipline.Coordination; }
                    catch (Exception) { }
                    try { vp.DetailLevel = ViewDetailLevel.Coarse; }
                    catch (Exception) { }
                    string range = "?";
                    foreach (double big in new[] { 1000.0, 200.0 })
                    {
                        try
                        {
                            PlanViewRange vr = vp.GetViewRange();
                            foreach (PlanViewPlane pl in new[] { PlanViewPlane.TopClipPlane, PlanViewPlane.CutPlane, PlanViewPlane.BottomClipPlane, PlanViewPlane.ViewDepthPlane })
                                vr.SetLevelId(pl, level.Id);
                            vr.SetOffset(PlanViewPlane.TopClipPlane, big);
                            vr.SetOffset(PlanViewPlane.CutPlane, big - 1.0);
                            vr.SetOffset(PlanViewPlane.BottomClipPlane, -(big - 1.0));
                            vr.SetOffset(PlanViewPlane.ViewDepthPlane, -big);
                            vp.SetViewRange(vr);
                            range = "+/-" + Fm(big * MM, 0) + " mm about the level";
                            break;
                        }
                        catch (Exception ex)
                        {
                            Log.Add("   lock plan: view range +/-" + Fm(big, 0) + " ft refused: " + ex.Message);
                        }
                    }
                    for (int n = 0; n < 20; n++)
                    {
                        try
                        {
                            vp.Name = n == 0 ? name : name + " (" + Inv(n) + ")";
                            break;
                        }
                        catch (Exception) { continue; }
                    }
                    try { Doc.Regenerate(); }   // so the new view has geometry to take references from
                    catch (Exception) { }
                    _views.Named[ElName(vp)] = vp;
                    _views.Plans[lk] = vp;
                    Log.Add("   lock plan: made " + ElName(vp) + " (coarse, view range " + range + ")");
                    return vp;
                }
                catch (Exception ex)
                {
                    Log.Add("   lock plan: could not make a plan for " + ElName(level) + ": " + ex.Message);
                    _views.PlanFailed.Add(lk);
                    return null;
                }
            }

            private Level LevelOf(FamilyInstance inst, V3 q)
            {
                try
                {
                    Level lv = Doc.GetElement(inst.LevelId) as Level;
                    if (lv != null) return lv;
                }
                catch (Exception) { }
                return ElementLevel(Doc, inst, q.Z);
            }
        }
    }
}
