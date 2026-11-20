using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
        public partial class Locker
        {
            // ============================================================= face-based EQ centre lock
            // Revit's Align is like-to-like (plane to plane, edge to edge): a duct's centreline LINE can not be aligned with a
            // reference PLANE of the hanger in a plan view, which is why every NewAlignment(centreline, plane) was refused.
            // The standard way to keep a family centred on a duct is an equality dimension (EQ) across three references:
            // service side face - hanger centre plane - service side face. That is what is made here:
            //   1. the service's two side faces (vertical planar faces, normal across the run, with references);
            //   2. each hanger reference is probed with a TEMPORARY dimension (rolled back) between one side face and the
            //      reference: Revit accepts it only when the plane is parallel to the sides (so the plane's real orientation
            //      is measured, never assumed), and the dimension's Value is the distance of the plane from that face; a second
            //      probe to the other face resolves on which side of the face the plane lies;
            //   3. the hanger is moved so that plane is exactly mid-way, then one dimension over the three references is made
            //      with AreSegmentsEqual = true (fallback: two locked dimensions).
            // The old centreline alignment (LockCentre) remains the fallback when this cannot be applied.

            private const double EqMoveLimit = 150.0 / MM;   // ft: a centre plane further off the middle than this is not moved
            private const double EqOnTol = 1.0 / MM;          // ft (1 mm): a plane this close to the middle needs no move
            private const double EqValueTol = 0.5 / MM;       // ft (0.5 mm): tolerance when matching two measured distances

            private class SideFace
            {
                public PlanarFace Face;
                public double S, Area, AMin, AMax;   // position across the run (ft from the run start), area, extent along the run
                public int Sign;                      // +1 faces towards +across (high side), -1 low side
                public long Owner;
                public bool HasSpan;
            }

            private class EqProbe
            {
                public RefItem Item;
                public int Ordinal, Prio;
                public bool Ok;
                public double X;      // plane position across the run (ft from the run start)
                public string Desc = "";
            }

            private class EqSpec
            {
                public string View, Source, Type, Name;
                public int Ordinal;
            }

            private readonly Dictionary<string, List<SideFace>> _eqSides = new Dictionary<string, List<SideFace>>(StringComparer.Ordinal);
            private readonly Dictionary<string, EqSpec> _eqWorked = new Dictionary<string, EqSpec>(StringComparer.Ordinal);
            private readonly Dictionary<string, int> _eqFails = new Dictionary<string, int>(StringComparer.Ordinal);
            private readonly HashSet<string> _eqDumped = new HashSet<string>(StringComparer.Ordinal);

            private void CL(string s) { Log.Add("   centre lock: " + s); }

            private static string ExText(Exception ex)
            {
                string m = ex.Message ?? "";
                return ex.GetType().Name + ": " + m.Replace("\r", " ").Replace("\n", " ");
            }

            private static int OrdinalOf(List<RefItem> list, int i)
            {
                int n = 0;
                for (int k = 0; k < i; k++)
                    if (list[k].Type == list[i].Type && list[k].Name == list[i].Name) n++;
                return n;
            }

            /// <summary>Every reference of the hanger family, once per family: stable representation, runtime geometry type, kind.</summary>
            private void DumpRefs(FamilyInstance inst, List<RefItem> all)
            {
                CL("hanger references (" + Inv(all.Count) + "):");
                for (int i = 0; i < all.Count; i++)
                {
                    RefItem it = all[i];
                    string st = StableKey(Doc, it.Ref) ?? "?";
                    string gt;
                    try
                    {
                        GeometryObject g = inst.GetGeometryObjectFromReference(it.Ref);
                        gt = g == null ? "null" : g.GetType().FullName + " (visibility " + g.Visibility + ", element geometry " + g.IsElementGeometry + ")";
                    }
                    catch (Exception ex) { gt = "throws " + ExText(ex); }
                    string rt;
                    try { rt = it.Ref.ElementReferenceType.ToString(); }
                    catch (Exception ex) { rt = "? " + ex.GetType().Name; }
                    CL("  ref " + Inv(i + 1) + "/" + Inv(all.Count) + " " + it.Label + " [" + it.Type + "] name \"" + it.Name + "\" stable=" + st
                       + " geometry=" + gt + " referenceType=" + rt);
                }
            }

            // ---- the service's side faces
            private List<Element> SideOwners(Element host, Section sec)
            {
                var owners = new List<Element> { host };
                if (sec.InsUsed)
                {
                    try
                    {
                        var ins = InsulationLiningBase.GetInsulationIds(Doc, host.Id).Select(i => Doc.GetElement(i)).Where(e => e != null).ToList();
                        if (ins.Count > 0) owners = ins;
                    }
                    catch (Exception) { }
                }
                return owners;
            }

            private List<SideFace> CollectSides(List<Element> owners, View view, Section sec, V3 along, V3 across)
            {
                var res = new List<SideFace>();
                foreach (Element el in owners)
                {
                    List<FaceZ> fzs = view != null ? ElementFaces(el, view) : ElementFaces(el);
                    foreach (FaceZ fz in fzs)
                    {
                        try
                        {
                            PlanarFace pf = fz.Face;
                            XYZ n = pf.FaceNormal;
                            if (Math.Abs(n.Z) > 0.02) continue;
                            double na = n.X * along.X + n.Y * along.Y;
                            double nc = n.X * across.X + n.Y * across.Y;
                            if (Math.Abs(na) > 0.02 || Math.Abs(nc) < 0.99) continue;
                            XYZ o = pf.Origin;
                            var sf = new SideFace
                            {
                                Face = pf, Sign = nc > 0 ? 1 : -1, Area = pf.Area,
                                S = (o.X - sec.A.X) * across.X + (o.Y - sec.A.Y) * across.Y,
                                Owner = Eid(el.Id),
                            };
                            try
                            {
                                double lo = double.MaxValue, hi = double.MinValue;
                                foreach (XYZ v in pf.Triangulate().Vertices)
                                {
                                    double a = (v.X - sec.A.X) * along.X + (v.Y - sec.A.Y) * along.Y;
                                    lo = Math.Min(lo, a);
                                    hi = Math.Max(hi, a);
                                }
                                if (lo <= hi) { sf.AMin = lo; sf.AMax = hi; sf.HasSpan = true; }
                            }
                            catch (Exception) { }
                            res.Add(sf);
                        }
                        catch (Exception) { }
                    }
                }
                return res;
            }

            /// <summary>The outermost side face on each side that spans the hanger's position along the run.</summary>
            private static bool PickSides(List<SideFace> all, double qa, out SideFace lo, out SideFace hi)
            {
                lo = null; hi = null;
                foreach (double tol in new[] { 0.05, double.MaxValue })
                {
                    var cover = all.Where(f => !f.HasSpan || tol == double.MaxValue || (qa >= f.AMin - tol && qa <= f.AMax + tol)).ToList();
                    var lows = cover.Where(f => f.Sign < 0).ToList();
                    var highs = cover.Where(f => f.Sign > 0).ToList();
                    if (lows.Count == 0 || highs.Count == 0) continue;
                    double ml = lows.Min(f => f.S), mh = highs.Max(f => f.S);
                    lo = lows.Where(f => f.S - ml < EqOnTol).OrderByDescending(f => f.Area).First();
                    hi = highs.Where(f => mh - f.S < EqOnTol).OrderByDescending(f => f.Area).First();
                    return true;
                }
                return false;
            }

            private List<SideFace> SidesFor(Element host, Section sec, View view, string src, V3 along, V3 across, string what)
            {
                string key = Inv(Eid(host.Id)) + (sec.InsUsed ? "|ins" : "|bare") + "|" + src + (src == "view" ? "|" + Inv(Eid(view.Id)) : "");
                List<SideFace> hit;
                if (_eqSides.TryGetValue(key, out hit)) return hit;
                View v = src == "view" ? view : null;
                List<SideFace> list = CollectSides(SideOwners(host, sec), v, sec, along, across);
                if (list.Count == 0 && sec.InsUsed)
                {
                    list = CollectSides(new List<Element> { host }, v, sec, along, across);
                    if (list.Count > 0) CL("sides [" + src + "]: the insulation has no side faces - using the " + what + "'s own");
                }
                _eqSides[key] = list;
                return list;
            }

            // ---- temporary dimensions
            private Dimension TryDim(View view, Line line, Reference a, Reference b, out double val, out string err, List<ElementId> made)
            {
                val = 0.0; err = null;
                try
                {
                    var ra = new ReferenceArray();
                    ra.Append(a);
                    ra.Append(b);
                    Dimension d = Doc.Create.NewDimension(view, line, ra);
                    if (d == null) { err = "NewDimension returned null"; return null; }
                    if (made != null) made.Add(d.Id);
                    double? v = d.Value;
                    if (!v.HasValue) { err = "the dimension has no value"; return d; }
                    val = v.Value;
                    return d;
                }
                catch (Exception ex)
                {
                    err = ExText(ex);
                    return null;
                }
            }

            private Line AcrossLine(View view, Section sec, V3 along, V3 across, double qa, double s0, double s1)
            {
                double z = 0.0;
                try
                {
                    ViewPlan vp = view as ViewPlan;
                    if (vp != null && vp.GenLevel != null) z = vp.GenLevel.Elevation;
                }
                catch (Exception) { }
                double bx = sec.A.X + along.X * qa, by = sec.A.Y + along.Y * qa;
                return Line.CreateBound(new XYZ(bx + across.X * s0, by + across.Y * s0, z), new XYZ(bx + across.X * s1, by + across.Y * s1, z));
            }

            /// <summary>Probes the hanger references with temporary dimensions (rolled back): which are parallel to the side faces and
            /// where they lie. Stops at the first centre plane. `budget` counts dimensions made.</summary>
            private EqProbe Probe(View view, string vlabel, string src, SideFace lo, SideFace hi, List<RefItem> cands, Section sec, V3 along, V3 across,
                                  double qa, double mid, ref int budget)
            {
                SubTransaction st = null;
                try
                {
                    st = new SubTransaction(Doc);
                    st.Start();
                }
                catch (Exception) { st = null; }
                var made = new List<ElementId>();
                var oks = new List<EqProbe>();
                try
                {
                    Line line = AcrossLine(view, sec, along, across, qa, lo.S - 1.0, hi.S + 1.0);
                    for (int i = 0; i < cands.Count; i++)
                    {
                        if (budget <= 0)
                        {
                            CL("probe [" + vlabel + " / " + src + "]: dimension budget used up - " + Inv(cands.Count - i) + " reference(s) not probed");
                            break;
                        }
                        RefItem it = cands[i];
                        var p = new EqProbe { Item = it, Ordinal = OrdinalOf(cands, i), Prio = CentrePrio(it) };
                        string head = "probe [" + vlabel + " / " + src + "] " + Inv(i + 1) + "/" + Inv(cands.Count) + " " + it.Label + " [" + it.Type + "]: ";
                        double d1, d2; string e1, e2;
                        budget--;
                        Dimension dim1 = TryDim(view, line, lo.Face.Reference, it.Ref, out d1, out e1, made);
                        if (dim1 == null || e1 != null)
                        {
                            CL(head + "dimension to the low face refused (plane parallel to the sides: NO) - " + e1);
                            continue;
                        }
                        budget--;
                        Dimension dim2 = TryDim(view, line, it.Ref, hi.Face.Reference, out d2, out e2, made);
                        if (dim2 == null || e2 != null)
                        {
                            CL(head + "to the low face " + Fm(d1 * MM, 3) + " mm (parallel: yes), but the dimension to the high face was refused - " + e2);
                            continue;
                        }
                        // the plane is at lo.S + d1 or lo.S - d1; the high face tells which
                        double xa = lo.S + d1, xb = lo.S - d1;
                        double ea = Math.Abs(Math.Abs(hi.S - xa) - d2), eb = Math.Abs(Math.Abs(hi.S - xb) - d2);
                        if (Math.Min(ea, eb) > EqValueTol)
                        {
                            CL(head + "inconsistent distances: low face " + Fm(d1 * MM, 3) + " mm, high face " + Fm(d2 * MM, 3) + " mm, sides " + Fm((hi.S - lo.S) * MM, 3) + " mm apart");
                            continue;
                        }
                        p.X = ea <= eb ? xa : xb;
                        p.Ok = true;
                        p.Desc = head;
                        CL(head + "parallel: YES, " + Fm(d1 * MM, 3) + " mm from the low face, " + Fm(d2 * MM, 3) + " mm from the high face -> at "
                           + Fm((p.X - mid) * MM, 3) + " mm from the middle of the sides" + (p.Prio <= 1 ? " (centre plane)" : ""));
                        oks.Add(p);
                        if (p.Prio <= 1 && Math.Abs(p.X - mid) <= EqMoveLimit) break;   // a centre plane: no need to look further
                    }
                }
                catch (Exception ex)
                {
                    CL("probe [" + vlabel + " / " + src + "]: " + ExText(ex));
                }
                finally
                {
                    try
                    {
                        if (st != null) st.RollBack();
                        else
                            foreach (ElementId id in made)
                            {
                                try { Doc.Delete(id); }
                                catch (Exception) { }
                            }
                    }
                    catch (Exception) { }
                }
                return oks.Where(p => (p.Prio <= 1 && Math.Abs(p.X - mid) <= EqMoveLimit) || Math.Abs(p.X - mid) <= EqOnTol)
                          .OrderBy(p => p.Prio).ThenBy(p => Math.Abs(p.X - mid)).FirstOrDefault();
            }

            private static List<RefItem> PreferEq(List<RefItem> cands, EqSpec spec)
            {
                for (int i = 0; i < cands.Count; i++)
                {
                    if (cands[i].Type == spec.Type && cands[i].Name == spec.Name && OrdinalOf(cands, i) == spec.Ordinal)
                    {
                        var o = new List<RefItem> { cands[i] };
                        for (int k = 0; k < cands.Count; k++)
                            if (k != i) o.Add(cands[k]);
                        return o;
                    }
                }
                return cands;
            }

            private string DimState(Dimension d)
            {
                var sb = new System.Text.StringBuilder();
                try { sb.Append("valid " + d.IsValidObject); } catch (Exception) { }
                try { sb.Append(", segments " + Inv(d.NumberOfSegments)); } catch (Exception ex) { sb.Append(", segments ? " + ex.GetType().Name); }
                try { sb.Append(", AreSegmentsEqual " + d.AreSegmentsEqual); } catch (Exception ex) { sb.Append(", AreSegmentsEqual ? " + ex.GetType().Name); }
                try { sb.Append(", IsLocked " + d.IsLocked); } catch (Exception ex) { sb.Append(", IsLocked ? " + ex.GetType().Name); }
                try
                {
                    var vals = new List<string>();
                    foreach (DimensionSegment sg in d.Segments)
                        vals.Add(sg.Value.HasValue ? Fm(sg.Value.Value * MM, 3) : "?");
                    if (vals.Count > 0) sb.Append(", segment values (mm) " + string.Join(" | ", vals));
                    else
                    {
                        double? v = d.Value;
                        if (v.HasValue) sb.Append(", value " + Fm(v.Value * MM, 3) + " mm");
                    }
                }
                catch (Exception ex) { sb.Append(", values ? " + ex.GetType().Name); }
                return sb.ToString();
            }

            /// <summary>The final constraint: one dimension over (low face, hanger plane, high face) with EQ; else two locked dimensions.</summary>
            private bool MakeEq(View view, string vlabel, SideFace lo, SideFace hi, Reference plane, Line line)
            {
                Dimension d3 = null;
                try
                {
                    var ra = new ReferenceArray();
                    ra.Append(lo.Face.Reference);
                    ra.Append(plane);
                    ra.Append(hi.Face.Reference);
                    d3 = Doc.Create.NewDimension(view, line, ra);
                }
                catch (Exception ex)
                {
                    CL("EQ dimension over 3 references [" + vlabel + "] refused - " + ExText(ex));
                }
                if (d3 != null)
                {
                    CL("EQ dimension created [" + vlabel + "]: " + DimState(d3));
                    bool eq = false;
                    try
                    {
                        d3.AreSegmentsEqual = true;
                        Regen("the EQ dimension");
                        eq = d3.AreSegmentsEqual;
                    }
                    catch (Exception ex) { CL("setting AreSegmentsEqual refused - " + ExText(ex)); }
                    CL("EQ dimension after setting EQ: " + DimState(d3) + (eq ? " -> EQ constraint in place (padlock left off: EQ alone keeps the plane in the middle)" : " -> EQ NOT set"));
                    if (eq) return true;
                    try { Doc.Delete(d3.Id); }
                    catch (Exception ex) { CL("could not remove the dimension without EQ - " + ExText(ex)); }
                }
                // fallback: two locked dimensions (face - plane, plane - face) at the measured distances
                var made = new List<Dimension>();
                bool ok = true;
                for (int k = 0; k < 2; k++)
                {
                    try
                    {
                        var ra = new ReferenceArray();
                        ra.Append(k == 0 ? lo.Face.Reference : plane);
                        ra.Append(k == 0 ? plane : hi.Face.Reference);
                        Dimension d = Doc.Create.NewDimension(view, line, ra);
                        d.IsLocked = true;
                        made.Add(d);
                        CL("locked dimension " + Inv(k + 1) + "/2 [" + vlabel + "]: " + DimState(d));
                        if (!d.IsLocked) ok = false;
                    }
                    catch (Exception ex)
                    {
                        CL("locked dimension " + Inv(k + 1) + "/2 [" + vlabel + "] refused - " + ExText(ex));
                        ok = false;
                        break;
                    }
                }
                if (!ok)
                {
                    foreach (Dimension d in made)
                    {
                        try { Doc.Delete(d.Id); }
                        catch (Exception) { }
                    }
                }
                return ok;
            }

            /// <summary>Face-based EQ centre lock. True: the hanger's centre plane is centred between the service's side faces by a
            /// constraint. False: not applicable / refused (why says so); the caller falls back to the centreline alignment.
            /// Caller holds the transaction.</summary>
            private bool LockEq(FamilyInstance inst, Element host, Section sec, V3 q, V3 along, V3 across, string alongType, string square, string what, out string why)
            {
                why = null;
                string famKey = FamKey(inst);
                string ek = famKey + "|eq";
                if (_eqDumped.Add(famKey)) DumpRefs(inst, InstanceRefs(inst, RefTypes));
                string[] kinds = { alongType, square, "StrongReference", "WeakReference", "Left", "Right", "Front", "Back" };
                List<RefItem> cands = InstanceRefs(inst, kinds);
                if (cands.Count == 0)
                {
                    why = "the hanger family offers no reference planes";
                    CL("EQ lock: " + why);
                    return false;
                }
                // centre-plane candidates first (by name too: weak / strong references called "Center ..." / "...Front/Back"); the sort is stable
                cands = cands.OrderBy(c => CentrePrio(c)).ToList();
                CL("centre-plane candidates in probe order: " + string.Join(" | ", cands.Select(c => c.Label + " [" + c.Type + "] prio " + Inv(CentrePrio(c)))));
                EqSpec spec;
                _eqWorked.TryGetValue(ek, out spec);
                if (spec != null) cands = PreferEq(cands, spec);
                int fails;
                _eqFails.TryGetValue(ek, out fails);
                int budget = spec != null ? 4 : (fails >= 2 ? 4 : 12);
                var views = new List<KeyValuePair<string, View>>();
                View lockPlan = DedicatedPlan(LevelOf(inst, q));
                if (lockPlan != null) views.Add(new KeyValuePair<string, View>("lock plan \"" + ElName(lockPlan) + "\"", lockPlan));
                if (Plan != null)
                {
                    string pw;
                    if (PlanShows(Plan, q.Z, out pw)) views.Add(new KeyValuePair<string, View>("active plan \"" + ElName(Plan) + "\"", Plan));
                    else CL("EQ lock: the active plan \"" + ElName(Plan) + "\" does not show the " + what + " (" + pw + ")");
                }
                if (views.Count == 0)
                {
                    why = "no plan view to make the dimensions in";
                    CL("EQ lock: " + why);
                    _eqFails[ek] = fails + 1;
                    return false;
                }
                if (spec != null && spec.View == "active" && views.Count > 1 && views[0].Value != Plan)
                    views.Reverse();
                string[] sources = spec != null && spec.Source == "fine" ? new[] { "fine", "view" } : new[] { "view", "fine" };
                double qa = (q.X - sec.A.X) * along.X + (q.Y - sec.A.Y) * along.Y;
                double qS = (q.X - sec.A.X) * across.X + (q.Y - sec.A.Y) * across.Y;
                CL("EQ lock: " + what + " " + Inv(Eid(host.Id)) + ", hanger at " + Fm(qS * MM, 3) + " mm across the run, budget " + Inv(budget) + " dimension(s), "
                   + Inv(cands.Count) + " reference(s) to probe" + (spec != null ? ", " + spec.Type + " \"" + spec.Name + "\" first (worked for this family)" : ""));
                foreach (KeyValuePair<string, View> vk in views)
                {
                    foreach (string src in sources)
                    {
                        if (budget <= 0) break;
                        List<SideFace> all = SidesFor(host, sec, vk.Value, src, along, across, what);
                        SideFace lo, hi;
                        if (!PickSides(all, qa, out lo, out hi))
                        {
                            CL("sides [" + vk.Key + " / " + src + "]: " + Inv(all.Count) + " vertical face(s) along the run, low " + Inv(all.Count(f => f.Sign < 0))
                               + " / high " + Inv(all.Count(f => f.Sign > 0)) + " - no pair of side faces" + (sec.Round ? " (round " + what + ": no flat sides)" : ""));
                            why = "no side faces with references on the " + what + (sec.Round ? " (round)" : "");
                            // why none: what the geometry walk saw of the service (counts by type per nesting level), once per source
                            if (_eqDumped.Add("geo|" + Inv(Eid(host.Id)) + "|" + src + "|" + (src == "view" ? Inv(Eid(vk.Value.Id)) : "")))
                            {
                                foreach (Element ow in SideOwners(host, sec))
                                    CL("geometry seen [" + vk.Key + " / " + src + "] of " + InsEl(ow) + ": " + InsGeoSummary(Doc, ow, src == "view" ? vk.Value : null));
                            }
                            continue;
                        }
                        _eqSawSides = true;
                        double mid = (lo.S + hi.S) / 2.0, width = hi.S - lo.S;
                        CL("sides [" + vk.Key + " / " + src + "]: " + Inv(all.Count) + " vertical face(s) along the run; low at " + Fm(lo.S * MM, 3) + " mm (element " + Inv(lo.Owner)
                           + ", area " + Fm(lo.Area * MM * MM, 0) + " mm2), high at " + Fm(hi.S * MM, 3) + " mm (element " + Inv(hi.Owner) + ", area " + Fm(hi.Area * MM * MM, 0)
                           + " mm2); width " + Fm(width * MM, 3) + " mm (section says " + Fm(sec.Width * MM, 3) + " mm), middle at " + Fm(mid * MM, 3) + " mm, hanger " + Fm((qS - mid) * MM, 3) + " mm off it");
                        EqProbe pick = Probe(vk.Value, vk.Key, src, lo, hi, cands, sec, along, across, qa, mid, ref budget);
                        if (pick == null)
                        {
                            why = "no reference plane of the hanger is parallel to the " + what + "'s sides and at (or a centre plane near) its middle";
                            continue;
                        }
                        CL("CHOSEN centre reference: name \"" + pick.Item.Name + "\", type " + pick.Item.Type + " (" + pick.Item.Label + "), priority " + Inv(pick.Prio)
                           + ", stable=" + (StableKey(Doc, pick.Item.Ref) ?? "?"));
                        // ---- move the hanger so the plane lies exactly mid-way
                        double delta = mid - pick.X;
                        if (Math.Abs(delta) > 1e-5)
                        {
                            try
                            {
                                ElementTransformUtils.MoveElement(Doc, inst.Id, new XYZ(across.X * delta, across.Y * delta, 0.0));
                                Regen("the centring move");
                                CL("moved the hanger " + Fm(delta * MM, 3) + " mm across the run so " + pick.Item.Label + " lies mid-way between the sides");
                            }
                            catch (Exception ex)
                            {
                                CL("centring move of " + Fm(delta * MM, 3) + " mm refused - " + ExText(ex));
                                why = "the hanger could not be moved to the middle (" + ExText(ex) + ")";
                                continue;
                            }
                        }
                        else CL("the hanger's " + pick.Item.Label + " is already mid-way (" + Fm(delta * MM, 4) + " mm)");
                        // the same reference again after the move / regenerate
                        List<RefItem> fresh = InstanceRefs(inst, kinds);
                        Reference plane = pick.Item.Ref;
                        for (int i = 0; i < fresh.Count; i++)
                            if (fresh[i].Type == pick.Item.Type && fresh[i].Name == pick.Item.Name && OrdinalOf(fresh, i) == pick.Ordinal) { plane = fresh[i].Ref; break; }
                        Line line = AcrossLine(vk.Value, sec, along, across, qa, lo.S - 1.0, hi.S + 1.0);
                        if (MakeEq(vk.Value, vk.Key, lo, hi, plane, line))
                        {
                            _eqWorked[ek] = new EqSpec { View = vk.Value == Plan ? "active" : "lock", Source = src, Type = pick.Item.Type, Name = pick.Item.Name, Ordinal = pick.Ordinal };
                            _eqFails[ek] = 0;
                            CL("locked centred: hanger " + pick.Item.Label + " between the " + what + "'s side faces [" + vk.Key + " / " + src + "]");
                            return true;
                        }
                        why = "Revit refused the equality / locked dimensions across the sides";
                    }
                }
                _eqFails[ek] = fails + 1;
                if (why == null) why = "no side faces / dimension budget used up";
                CL("EQ lock not made: " + why + " (family failures in a row: " + Inv(fails + 1) + ")");
                return false;
            }
        }
    }
}
