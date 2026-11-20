using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
        public partial class Locker
        {
            // ============================================================= symbol-level centre lock + probed bottom lock
            // What the owner's MANUAL alignment (Inspect lock) showed: Revit's Align ties the hanger family's centre plane (a weak
            // reference called "Center") to the SYMBOL-level LINEAR centreline of the service, the Line that
            // GeometryInstance.GetSymbolGeometry() gives with IncludeNonVisibleObjects = true (stable representation
            // "...:INSTANCE:...:LINEAR"). The instance-level centreline (GetInstanceGeometry) is always refused. Every candidate pair
            // is PROBED in a sub-transaction that is rolled back: the alignment Revit allows must also keep the hanger where it is
            // (or move it only along the intended direction) - then it is redone for real and kept.

            private static readonly string[] AllRefKinds =
            {
                "CenterLeftRight", "CenterFrontBack", "CenterElevation", "Left", "Right", "Front", "Back",
                "Top", "Bottom", "StrongReference", "WeakReference", "NotAReference",
            };

            private class SymLine
            {
                public Line Ln;
                public Reference Ref;
                public string Level = "", Stable;
                public XYZ P, D;           // model coordinates
                public bool Pref;          // stable representation holds ":INSTANCE:" and ends with ":LINEAR"
            }

            private class SymState
            {
                public int Refused, Rejected;
                public string LastRefused, LastReject;
            }

            private class Meas
            {
                public double Dx, Dy, Dz, DAlong, DAcross, Rot, Host;
                public bool HostKnown, PosKnown;
                public string Describe()
                {
                    return "hanger moved " + Fm(DAlong * MM, 3) + " mm along the run, " + Fm(DAcross * MM, 3) + " across, " + Fm(Dz * MM, 3) + " vertically, rotated "
                           + Fm(Rot, 6) + " rad" + (HostKnown ? ", service moved " + Fm(Host * MM, 3) + " mm" : "");
                }
            }

            private Meas _lastMeas;

            private class PoseT
            {
                public XYZ O, F, H, C;
            }

            private readonly Dictionary<string, List<SymLine>> _symLines = new Dictionary<string, List<SymLine>>(StringComparer.Ordinal);
            private readonly HashSet<string> _symLogged = new HashSet<string>(StringComparer.Ordinal);
            private readonly Dictionary<string, string> _symKind = new Dictionary<string, string>(StringComparer.Ordinal);       // category -> "source|level"
            private readonly Dictionary<string, EqSpec> _symWorked = new Dictionary<string, EqSpec>(StringComparer.Ordinal);    // family -> hanger reference
            private readonly HashSet<string> _noFaces = new HashSet<string>(StringComparer.Ordinal);                             // category|shape: no side faces
            private readonly HashSet<string> _oldRefused = new HashSet<string>(StringComparer.Ordinal);                          // category: old centreline refused
            private bool _eqSawSides;
            private readonly Dictionary<string, BottomSet> _bottomSets = new Dictionary<string, BottomSet>(StringComparer.Ordinal);
            private readonly Dictionary<string, string> _bottomSrcWorked = new Dictionary<string, string>(StringComparer.Ordinal);

            private class BottomSet
            {
                public List<Element> Owners = new List<Element>();
                public Dictionary<string, List<RefItem>> BySrc = new Dictionary<string, List<RefItem>>(StringComparer.Ordinal);
            }

            private static string CatKey(Element host)
            {
                try
                {
                    string n = host.Category != null ? host.Category.Name : "(no category)";
                    return (host is FabricationPart ? "fab:" : "") + n.ToLowerInvariant();
                }
                catch (Exception) { return "?"; }
            }

            // ---- hanger side
            private static int SymPrio(RefItem it)
            {
                string n = (it.Name ?? "").Trim().ToLowerInvariant();
                string nn = n.Replace(" ", "");
                if (nn == "center(front/back)" || nn == "center(left/right)" || nn == "centre(front/back)" || nn == "centre(left/right)"
                    || n == "center" || n == "centre" || n == "cl" || n == "centerline" || n == "centreline")
                    return 0;
                if (n.Contains("center") || n.Contains("centre") || n.Contains("front") || n.Contains("back")) return 1;
                if (n.Length == 0 && (it.Type == "CenterLeftRight" || it.Type == "CenterFrontBack")) return 1;
                return 2;
            }

            /// <summary>Every reference of the hanger (all FamilyInstanceReferenceTypes), duplicates removed, centre-named planes first.</summary>
            private List<RefItem> SymCands(FamilyInstance inst)
            {
                var raw = InstanceRefs(inst, AllRefKinds);
                var seen = new HashSet<string>(StringComparer.Ordinal);
                var list = new List<RefItem>();
                foreach (RefItem it in raw)
                {
                    string sk = StableKey(Doc, it.Ref);
                    if (sk != null && !seen.Add(sk)) continue;
                    list.Add(it);
                }
                return list.Select((it, i) => new { it, i }).OrderBy(z => SymPrio(z.it)).ThenBy(z => z.i).Select(z => z.it).ToList();
            }

            // ---- measuring an alignment
            private PoseT PoseOf(FamilyInstance inst, Element host)
            {
                var p = new PoseT();
                try { p.O = inst.GetTransform().Origin; }
                catch (Exception)
                {
                    try { p.O = ((LocationPoint)inst.Location).Point; }
                    catch (Exception) { }
                }
                try { p.F = inst.FacingOrientation; p.H = inst.HandOrientation; }
                catch (Exception) { }
                try
                {
                    BoundingBoxXYZ b = host.get_BoundingBox(null);
                    if (b != null) p.C = new XYZ((b.Min.X + b.Max.X) / 2.0, (b.Min.Y + b.Max.Y) / 2.0, (b.Min.Z + b.Max.Z) / 2.0);
                }
                catch (Exception) { }
                return p;
            }

            private static double AngleBetween(XYZ a, XYZ b)
            {
                double c = Math.Max(-1.0, Math.Min(1.0, a.DotProduct(b)));
                return Math.Acos(c);
            }

            private static Meas MeasOf(PoseT a, PoseT b, V3 along, V3 across)
            {
                var m = new Meas();
                if (a.O != null && b.O != null)
                {
                    XYZ d = b.O - a.O;
                    m.Dx = d.X; m.Dy = d.Y; m.Dz = d.Z;
                    m.DAlong = d.X * along.X + d.Y * along.Y;
                    m.DAcross = d.X * across.X + d.Y * across.Y;
                    m.PosKnown = true;
                }
                if (a.F != null && b.F != null && a.H != null && b.H != null)
                    m.Rot = Math.Max(AngleBetween(a.F, b.F), AngleBetween(a.H, b.H));
                if (a.C != null && b.C != null)
                {
                    m.Host = a.C.DistanceTo(b.C);
                    m.HostKnown = true;
                }
                return m;
            }

            private static string CentreCheck(Meas m)
            {
                if (!m.PosKnown) return "the hanger position could not be read";
                if (Math.Abs(m.Dz) > 1.0 / MM) return "it would move the hanger vertically";
                if (Math.Abs(m.DAlong) > 1.0 / MM) return "it would move the hanger along the run";
                if (m.Rot > 1e-4) return "it would rotate the hanger";
                if (m.HostKnown && m.Host > 0.5 / MM) return "it would move the service";
                if (Math.Abs(m.DAcross) > 300.0 / MM) return "it would move the hanger more than 300 mm across the run";
                return null;
            }

            private static Func<Meas, string> BottomCheck(double zLimit)
            {
                return m =>
                {
                    if (!m.PosKnown) return "the hanger position could not be read";
                    if (Math.Abs(m.DAlong) > 1.0 / MM || Math.Abs(m.DAcross) > 1.0 / MM) return "it would move the hanger in plan";
                    if (m.Rot > 1e-4) return "it would rotate the hanger";
                    if (m.HostKnown && m.Host > 0.5 / MM) return "it would move the service";
                    if (Math.Abs(m.Dz) > zLimit) return "it would move the hanger " + Fm(m.Dz * MM, 1) + " mm vertically";
                    return null;
                };
            }

            /// <summary>One NewAlignment(view, first, second) in its own sub-transaction. 0 = Revit refused (err says why), 1 = made but
            /// check() rejected the result (rolled back), 2 = accepted (kept - committed with the dimension locked - only when keep).</summary>
            private int AlignOnce(View view, Reference first, Reference second, FamilyInstance inst, Element host, V3 along, V3 across, bool keep,
                                  Func<Meas, string> check, out string text, out string err)
            {
                text = ""; err = null; _lastMeas = null;
                Stopwatch sw = Stopwatch.StartNew();
                PoseT before = PoseOf(inst, host);
                SubTransaction st = null;
                try
                {
                    st = new SubTransaction(Doc);
                    st.Start();
                }
                catch (Exception ex)
                {
                    text = "no sub-transaction (" + ExText(ex) + ")";
                    err = text;
                    return 0;
                }
                bool commit = false;
                string result = "";
                
                try
                {
                    Dimension dim;
                    try { dim = Doc.Create.NewAlignment(view, first, second); }
                    catch (Exception ex)
                    {
                        err = ExText(ex);
                        result = "refused - " + err;
                        return 0;
                    }
                    try { Doc.Regenerate(); }
                    catch (Exception) { }
                    PoseT after = PoseOf(inst, host);
                    Meas m = MeasOf(before, after, along, across);
                    _lastMeas = m;
                    string bad = check(m);
                    if (bad != null)
                    {
                        result = "made, REJECTED (" + bad + "): " + m.Describe();
                        
                        return 1;
                    }
                    
                    result = "accepted: " + m.Describe();
                    if (keep)
                    {
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
                        catch (Exception ex) { lockState += " (lock: " + ExText(ex) + ")"; }
                        result += ", KEPT, " + lockState;
                        commit = true;
                    }
                    return 2;
                }
                finally
                {
                    try
                    {
                        if (commit) st.Commit();
                        else st.RollBack();
                    }
                    catch (Exception) { }
                    text = result + " [" + Inv(sw.ElapsedMilliseconds) + " ms]";
                }
            }

            // ---- geometry walking (symbol level and instance level, references computed)
            private static void SymWalk(IEnumerable<GeometryObject> geo, Transform cur, string level, List<SymLine> lines, List<FaceZ> faces, int depth)
            {
                if (geo == null || depth > 4) return;
                foreach (GeometryObject g in geo)
                {
                    GeometryInstance gi = g as GeometryInstance;
                    if (gi != null)
                    {
                        Transform t2 = null;
                        try { t2 = cur.Multiply(gi.Transform); }
                        catch (Exception) { }
                        try
                        {
                            if (t2 != null) SymWalk(gi.GetSymbolGeometry(), t2, level + ">sym", lines, faces, depth + 1);
                        }
                        catch (Exception) { }
                        try { SymWalk(gi.GetInstanceGeometry(), cur, level + ">inst", lines, faces, depth + 1); }
                        catch (Exception) { }
                        continue;
                    }
                    Solid so = g as Solid;
                    if (so != null)
                    {
                        if (faces == null) continue;
                        try
                        {
                            foreach (Face f in so.Faces)
                            {
                                PlanarFace pf = f as PlanarFace;
                                if (pf == null) continue;
                                Reference r = null;
                                try { r = pf.Reference; }
                                catch (Exception) { }
                                if (r == null) continue;
                                faces.Add(new FaceZ { Face = pf, Z = cur.OfPoint(pf.Origin).Z, Nz = cur.OfVector(pf.FaceNormal).Z, Level = level });
                            }
                        }
                        catch (Exception) { }
                        continue;
                    }
                    Line ln = g as Line;
                    if (ln != null && lines != null)
                    {
                        try
                        {
                            Reference r = ln.Reference;
                            if (r == null) continue;
                            XYZ p0 = cur.OfPoint(ln.GetEndPoint(0));
                            XYZ d = cur.OfVector(ln.Direction);
                            double dl = d.GetLength();
                            if (dl < 1e-9) continue;
                            lines.Add(new SymLine { Ln = ln, Ref = r, Level = level, P = p0, D = new XYZ(d.X / dl, d.Y / dl, d.Z / dl) });
                        }
                        catch (Exception) { }
                    }
                }
            }

            /// <summary>The service's centreline Lines with references, any level, from one geometry source (IncludeNonVisibleObjects =
            /// true always): src "view" = the plan as that view shows it, else the geometry at that detail level with no view. Cached.</summary>
            private List<SymLine> SymLinesFor(Element host, View view, string src, Section sec, V3 along, string what, string cachedKind, out int rawCount)
            {
                string key = Inv(Eid(host.Id)) + "|" + src + (src == "view" ? "|" + Inv(Eid(view.Id)) : "");
                List<SymLine> raw;
                if (!_symLines.TryGetValue(key, out raw))
                {
                    Stopwatch sw = Stopwatch.StartNew();
                    raw = new List<SymLine>();
                    Options opt = new Options();
                    opt.ComputeReferences = true;
                    opt.IncludeNonVisibleObjects = true;
                    if (src == "view") opt.View = view;
                    else
                    {
                        ViewDetailLevel dl;
                        if (Enum.TryParse<ViewDetailLevel>(src, out dl))
                        {
                            try { opt.DetailLevel = dl; }
                            catch (Exception) { }
                        }
                    }
                    try
                    {
                        GeometryElement geo = host.get_Geometry(opt);
                        if (geo != null) SymWalk(geo, Transform.Identity, "top", raw, null, 0);
                    }
                    catch (Exception ex) { CL("service geometry [" + src + "]: " + ExText(ex)); }
                    foreach (SymLine l in raw)
                    {
                        l.Stable = StableKey(Doc, l.Ref);
                        l.Pref = l.Stable != null && l.Stable.Contains(":INSTANCE:") && l.Stable.EndsWith(":LINEAR", StringComparison.Ordinal);
                    }
                    _symLines[key] = raw;
                    CL("service geometry [" + src + (src == "view" ? " \"" + ElName(view) + "\"" : "") + ", nonvisible included] of " + what + ": " + Inv(raw.Count)
                       + " line(s) with a reference (" + Inv(sw.ElapsedMilliseconds) + " ms)" + (raw.Count > 0 ? ": " + string.Join(" | ", raw.Take(8).Select(l =>
                           l.Level + " " + (l.Stable ?? "?") + " from (" + Fm(l.P.X * MM, 0) + ", " + Fm(l.P.Y * MM, 0) + ", " + Fm(l.P.Z * MM, 0) + ") dir ("
                           + Fm(l.D.X, 4) + ", " + Fm(l.D.Y, 4) + ", " + Fm(l.D.Z, 4) + ")")) : ""));
                }
                rawCount = raw.Count;
                var good = new List<SymLine>();
                int notAlong = 0, far = 0;
                double nearest = double.MaxValue;
                foreach (SymLine l in raw)
                {
                    double xy = Math.Sqrt(l.D.X * l.D.X + l.D.Y * l.D.Y);
                    if (xy < 1e-6 || Math.Abs((l.D.X * along.X + l.D.Y * along.Y) / xy) < 0.9999)
                    {
                        notAlong++;
                        continue;
                    }
                    double dist = Math.Abs((l.P.X - sec.A.X) * along.Y - (l.P.Y - sec.A.Y) * along.X);
                    nearest = Math.Min(nearest, dist);
                    if (dist > 0.02)
                    {
                        far++;
                        continue;
                    }
                    good.Add(l);
                }
                if (_symLogged.Add(key + "|filter"))
                    CL("service lines [" + src + "]: " + Inv(good.Count) + " along the run on its centreline" + (notAlong > 0 ? ", " + Inv(notAlong) + " not along it" : "")
                       + (far > 0 ? ", " + Inv(far) + " off the centreline (nearest " + Fmm(nearest) + " mm)" : ""));
                return good.Select((l, i) => new { l, i })
                           .OrderBy(z => cachedKind != null && cachedKind == src + "|" + z.l.Level ? 0 : 1)
                           .ThenBy(z => z.l.Pref ? 0 : 1)
                           .ThenBy(z => z.l.Level.Contains("sym") ? 0 : 1)
                           .ThenBy(z => z.i).Select(z => z.l).ToList();
            }

            /// <summary>Round services on a level run: the hanger family's Center (Elevation) plane aligned to the service's SYMBOL-level
            /// centreline line, in the lock section (where the horizontal plane and the line both show edge-on), as the centre lock does
            /// for the vertical plane. Each pair is made in a sub-transaction and kept only if the hanger does not move in plan, turn, or
            /// shift the service. False when nothing was locked (the caller then tries the older route).</summary>
            private bool LockElevationSym(FamilyInstance inst, Element host, Section sec, V3 along, string what)
            {
                try
                {
                    V3 across = new V3(-along.Y, along.X, 0.0);
                    ViewSection view = SectionFor(host, sec);
                    if (view == null)
                    {
                        Log.Add("   centre elevation lock: no section view - the symbol route is skipped");
                        return false;
                    }
                    int raw;
                    List<SymLine> lines = SymLinesFor(host, view, "view", sec, along, what, null, out raw);
                    if (lines.Count == 0)
                    {
                        Log.Add("   centre elevation lock: no symbol centreline of the " + what + " in the lock section (" + Inv(raw) + " line(s) read)");
                        return false;
                    }
                    var cands = new List<RefItem>();
                    foreach (RefItem it in SymCands(inst))
                    {
                        string n = (it.Name ?? "").ToLowerInvariant();
                        if (it.Type == "CenterElevation" || n.Contains("elev")) cands.Add(it);
                    }
                    if (cands.Count == 0)
                    {
                        Log.Add("   centre elevation lock: the family offers no Center (Elevation) reference - skipped");
                        return false;
                    }
                    Func<Meas, string> check = m =>
                    {
                        if (!m.PosKnown) return "the hanger position could not be read";
                        if (Math.Abs(m.DAlong) > 1.0 / MM || Math.Abs(m.DAcross) > 1.0 / MM) return "it would move the hanger in plan";
                        if (m.Rot > 1e-4) return "it would rotate the hanger";
                        if (m.HostKnown && m.Host > 0.5 / MM) return "it would move the service";
                        if (Math.Abs(m.Dz) > 100.0 / MM) return "it would move the hanger " + Fm(m.Dz * MM, 1) + " mm vertically";
                        return null;
                    };
                    int tries = 0;
                    string last = "";
                    foreach (SymLine ln in lines.Take(3))
                    {
                        foreach (RefItem cand in cands.Take(4))
                        {
                            for (int o = 0; o < 2; o++)
                            {
                                if (++tries > 16) break;
                                string text, err;
                                int s = AlignOnce(view, o == 0 ? ln.Ref : cand.Ref, o == 0 ? cand.Ref : ln.Ref, inst, host, along, across, true, check, out text, out err);
                                last = text;
                                Log.Add("   centre elevation lock [section " + ElName(view) + ", line " + (ln.Stable ?? "?") + " <-> hanger \"" + cand.Name + "\" ["
                                        + cand.Type + "], " + (o == 0 ? "centreline first" : "hanger plane first") + "]: " + text);
                                if (s == 2)
                                {
                                    Log.Add("   locked the centre elevation: hanger \"" + cand.Name + "\" <-> " + what + " symbol centreline");
                                    return true;
                                }
                            }
                        }
                    }
                    Log.Add("   centre elevation lock: symbol route not locked after " + Inv(tries) + " attempt(s); last: " + last);
                    return false;
                }
                catch (Exception ex)
                {
                    Log.Add("   centre elevation lock (symbol route): " + ExText(ex));
                    return false;
                }
            }

            private int SymTry(View view, string vlabel, string src, SymLine ln, RefItem cand, FamilyInstance inst, Element host, V3 along, V3 across,
                               bool keep, int order, SymState st, ref int budget, out int usedOrder)
            {
                usedOrder = -1;
                int result = 0;
                string candStable = StableKey(Doc, cand.Ref) ?? "?";
                for (int o = order < 0 ? 0 : order; o <= (order < 0 ? 1 : order); o++)
                {
                    if (budget <= 0 && !keep) break;
                    budget--;
                    string ord = o == 0 ? "centreline first" : "hanger plane first";
                    string text, err;
                    int s = AlignOnce(view, o == 0 ? ln.Ref : cand.Ref, o == 0 ? cand.Ref : ln.Ref, inst, host, along, across, keep, CentreCheck, out text, out err);
                    CL((keep ? "KEEP" : "probe") + " [" + vlabel + " / " + src + " " + ln.Level + "] line " + (ln.Stable ?? "?") + " <-> hanger \"" + cand.Name + "\" ["
                       + cand.Type + "] " + candStable + " (" + ord + "): " + text);
                    if (s == 2)
                    {
                        usedOrder = o;
                        return 2;
                    }
                    if (s == 1)
                    {
                        st.Rejected++;
                        st.LastReject = text;
                        result = 1;
                        break;   // the reverse order would only move the other element
                    }
                    st.Refused++;
                    st.LastRefused = err;
                }
                return result;
            }

            /// <summary>Centre lock to the symbol-level centreline. True: aligned and locked. Caller holds the transaction.</summary>
            private bool LockSym(FamilyInstance inst, Element host, Section sec, V3 q, V3 along, V3 across, string what, out string why)
            {
                why = null;
                Stopwatch swAll = Stopwatch.StartNew();
                string famKey = FamKey(inst);
                string ck = famKey + "|sym";
                string cat = CatKey(host);
                if (_eqDumped.Add(famKey)) DumpRefs(inst, InstanceRefs(inst, AllRefKinds));
                List<RefItem> sorted = SymCands(inst);
                if (sorted.Count == 0)
                {
                    why = "the hanger family offers no references";
                    CL("symbol-centreline lock: " + why);
                    return false;
                }
                List<RefItem> cands = sorted;
                EqSpec spec;
                _symWorked.TryGetValue(ck, out spec);
                if (spec != null) cands = PreferEq(sorted, spec);
                string cachedKind;
                _symKind.TryGetValue(cat, out cachedKind);
                CL("symbol-centreline lock: " + what + " " + Inv(Eid(host.Id)) + " (" + cat + "), " + Inv(cands.Count) + " hanger reference(s) in probe order: "
                   + string.Join(" | ", cands.Select(c => "\"" + c.Name + "\" [" + c.Type + "] prio " + Inv(SymPrio(c))))
                   + (spec != null ? "; cached for this family: \"" + spec.Name + "\"" : "") + (cachedKind != null ? "; cached service line kind for " + cat + ": " + cachedKind : ""));
                int budget = 40;
                var st = new SymState();
                var seen = new HashSet<string>(StringComparer.Ordinal);
                var srcNotes = new List<string>();
                int linesTotal = 0;
                string[] baseSrc = { "view", "Fine", "Medium", "Coarse" };
                for (int vi = 0; vi < 2; vi++)
                {
                    View view; string vlabel;
                    if (vi == 0)
                    {
                        if (Plan == null)
                        {
                            CL("the active view is not a plan - using the tool's own lock plan");
                            continue;
                        }
                        string pw;
                        if (!PlanShows(Plan, q.Z, out pw))
                        {
                            CL("the active plan \"" + ElName(Plan) + "\" does not show the " + what + " (centre at " + Fmm(q.Z) + " mm; " + pw + ") - using the tool's own lock plan");
                            continue;
                        }
                        view = Plan;
                        vlabel = "active plan \"" + ElName(Plan) + "\"";
                    }
                    else
                    {
                        view = DedicatedPlan(LevelOf(inst, q));
                        if (view == null) continue;
                        vlabel = "lock plan \"" + ElName(view) + "\"";
                    }
                    string vid = Inv(Eid(view.Id));
                    string[] srcs = cachedKind != null ? baseSrc.OrderBy(s => cachedKind.StartsWith(s + "|", StringComparison.Ordinal) ? 0 : 1).ToArray() : baseSrc;
                    foreach (string src in srcs)
                    {
                        if (budget <= 0) break;
                        int rawCount;
                        List<SymLine> lines = SymLinesFor(host, view, src, sec, along, what, cachedKind, out rawCount);
                        var fresh = lines.Where(l => l.Stable == null || seen.Add(l.Stable + "@" + vid)).ToList();
                        linesTotal += fresh.Count;
                        if (fresh.Count == 0)
                        {
                            srcNotes.Add(src + ": " + (rawCount == 0 ? "no line" : "no new line along the run"));
                            continue;
                        }
                        foreach (SymLine ln in fresh)
                        {
                            string kind = src + "|" + ln.Level;
                            int start = 0;
                            if (spec != null && cachedKind == kind)
                            {
                                int uo;
                                int s0 = SymTry(view, vlabel, src, ln, cands[0], inst, host, along, across, true, -1, st, ref budget, out uo);
                                if (s0 == 2) return SymDone(sorted, cands[0], cat, kind, ck, ln, vlabel, src, swAll);
                                start = 1;
                            }
                            for (int ci = start; ci < cands.Count && budget > 0; ci++)
                            {
                                int uo;
                                int s1 = SymTry(view, vlabel, src, ln, cands[ci], inst, host, along, across, false, -1, st, ref budget, out uo);
                                if (s1 != 2) continue;
                                int uo2;
                                int s2 = SymTry(view, vlabel, src, ln, cands[ci], inst, host, along, across, true, uo, st, ref budget, out uo2);
                                if (s2 == 2) return SymDone(sorted, cands[ci], cat, kind, ck, ln, vlabel, src, swAll);
                            }
                        }
                    }
                }
                if (linesTotal == 0)
                    why = "no centreline line reference along the " + what + " in the symbol / instance geometry (" + (srcNotes.Count > 0 ? string.Join("; ", srcNotes) : "no plan view to work in") + ")";
                else
                    why = Inv(linesTotal) + " centreline line(s) tried against " + Inv(cands.Count) + " hanger reference(s): Revit refused " + Inv(st.Refused)
                          + ", " + Inv(st.Rejected) + " accepted but would have moved the hanger/service wrongly"
                          + (st.LastRefused != null ? " (last refusal: " + st.LastRefused + ")" : "") + (budget <= 0 ? "; attempt budget used up" : "");
                CL("symbol-centreline lock not made: " + why + " (" + Inv(swAll.ElapsedMilliseconds) + " ms)");
                return false;
            }

            private bool SymDone(List<RefItem> sorted, RefItem cand, string cat, string kind, string ck, SymLine ln, string vlabel, string src, Stopwatch sw)
            {
                int idx = sorted.IndexOf(cand);
                _symWorked[ck] = new EqSpec { Type = cand.Type, Name = cand.Name, Ordinal = idx >= 0 ? OrdinalOf(sorted, idx) : 0 };
                _symKind[cat] = kind;
                CL("LOCKED centre: hanger \"" + cand.Name + "\" [" + cand.Type + "] " + (StableKey(Doc, cand.Ref) ?? "?") + " <-> service line " + (ln.Stable ?? "?")
                   + " (source " + src + ", level " + ln.Level + ") in " + vlabel + "; cached for family and for " + cat + " (" + Inv(sw.ElapsedMilliseconds) + " ms)");
                return true;
            }

            // ============================================================= bottom lock
            private static readonly string[] BottomSrcs = { "plain", "section", "nonvisible", "section+nonvisible" };

            private List<FaceZ> SymFaces(Element el, View view)
            {
                Options opt = new Options();
                opt.ComputeReferences = true;
                opt.IncludeNonVisibleObjects = true;
                if (view != null) opt.View = view;
                else
                {
                    try { opt.DetailLevel = ViewDetailLevel.Fine; }
                    catch (Exception) { }
                }
                var faces = new List<FaceZ>();
                try
                {
                    GeometryElement geo = el.get_Geometry(opt);
                    if (geo != null) SymWalk(geo, Transform.Identity, "top", null, faces, 0);
                }
                catch (Exception) { }
                return faces;
            }

            /// <summary>The service's lowest downward faces with references, as one geometry source reads them. Cached per service.</summary>
            private List<RefItem> BottomItems(BottomSet set, string src, ViewSection view, bool unit, Element host, string what)
            {
                List<RefItem> r;
                if (set.BySrc.TryGetValue(src, out r)) return r;
                Stopwatch sw = Stopwatch.StartNew();
                var downs = new List<FaceZ>();
                foreach (Element el in set.Owners)
                {
                    List<FaceZ> fz = new List<FaceZ>();
                    switch (src)
                    {
                        case "plain": fz = ElementFaces(el); break;
                        case "section": if (view != null) fz = ElementFaces(el, view); break;
                        case "nonvisible": fz = SymFaces(el, null); break;
                        case "section+nonvisible": if (view != null) fz = SymFaces(el, view); break;
                    }
                    downs.AddRange(fz.Where(x => x.Nz < -0.99));
                }
                r = new List<RefItem>();
                if (downs.Count > 0)
                {
                    double zl = downs.Min(x => x.Z);
                    foreach (FaceZ fz in downs.Where(x => Math.Abs(x.Z - zl) < 2.0 / MM))
                        r.Add(new RefItem(fz.Face.Reference, "bottom face at " + Fmm(fz.Z) + " [" + src + (fz.Level.Length > 0 && fz.Level != "top" ? " " + fz.Level : "") + "]") { Type = "face", Name = src });
                }
                if (unit && src == "plain") r.AddRange(InstanceRefs(host, new[] { "Bottom" }));
                Log.Add("   bottom lock: " + what + " faces [" + src + "]: " + Inv(downs.Count) + " downward face(s), " + Inv(r.Count) + " at the lowest height ("
                        + Inv(sw.ElapsedMilliseconds) + " ms)" + (r.Count > 0 ? ": " + string.Join(" | ", r.Take(6).Select(i => (StableKey(Doc, i.Ref) ?? "?") + " " + i.Label)) : ""));
                if (downs.Count == 0 && src == "plain")
                {
                    foreach (Element ow in set.Owners)
                        Log.Add("   bottom lock: no flat bottom face - geometry seen (Fine, as the lock reads it) of " + InsEl(ow) + ": " + InsGeoSummary(Doc, ow, null));
                }
                set.BySrc[src] = r;
                return r;
            }

            private void BL(string s) { Log.Add("   bottom lock: " + s); }

            /// <summary>Hanger at the invert <-> the service's (or insulation's / unit's) bottom face, in the service's lock section. Every
            /// hanger reference and every flat face near the invert is PROBED (rolled back) against each bottom face (faces from the plain
            /// geometry, the section view's geometry and the non-visible / symbol geometry): the one kept moves the hanger only vertically,
            /// and least. Returns the summary word for the lock summary line ("yes" / "no (why)").</summary>
            private string LockBottom(FamilyInstance inst, Element host, Section sec, V3 q, V3 along, V3 across, bool unit, string what, List<string> notes)
            {
                Stopwatch swAll = Stopwatch.StartNew();
                double zInv = q.Z - sec.Depth / 2.0;
                string bk = Inv(Eid(host.Id)) + (sec.InsUsed ? "|ins" : "|bare") + (unit ? "|unit" : "");
                BottomSet set;
                if (!_bottomSets.TryGetValue(bk, out set))
                {
                    set = new BottomSet();
                    set.Owners.Add(host);
                    if (sec.InsUsed)
                    {
                        try
                        {
                            var ins = InsulationLiningBase.GetInsulationIds(Doc, host.Id).Select(i => Doc.GetElement(i)).Where(e => e != null).ToList();
                            if (ins.Count > 0) set.Owners = ins;
                        }
                        catch (Exception) { }
                    }
                    _bottomSets[bk] = set;
                }
                ViewSection view = SectionFor(host, sec);
                if (view == null)
                {
                    notes.Add("no section view type for the bottom lock");
                    return "no (no section view type)";
                }
                // ---- the hanger's candidates: flat faces near the invert, then every reference of the family
                List<FaceZ> hfaces = ElementFaces(inst, view);
                string hsrc = "section";
                if (hfaces.Count == 0) { hfaces = ElementFaces(inst); hsrc = "plain"; }
                var flats = hfaces.Where(fz => Math.Abs(fz.Nz) > 0.99 && Math.Abs(fz.Z - zInv) < 2.0 / MM)
                                  .Select((fz, i) => new { fz, i }).OrderBy(z => -z.fz.Nz).ThenBy(z => z.i).Select(z => z.fz).ToList();   // the upward face (bearer top) first
                var cands = flats.Select(fz => new RefItem(fz.Face.Reference, "face at " + Fmm(fz.Z)) { Type = "face", Name = "face" }).ToList();
                int nFlat = cands.Count;
                cands.AddRange(InstanceRefs(inst, AllRefKinds));
                {
                    var seenC = new HashSet<string>(StringComparer.Ordinal);
                    cands = cands.Where(c => { string sk = StableKey(Doc, c.Ref); return sk == null || seenC.Add(sk); }).ToList();
                }
                BL("invert " + Fmm(zInv) + " mm; hanger candidates " + Inv(cands.Count) + " (" + Inv(nFlat) + " flat face(s) near the invert from the " + hsrc + " geometry of " + Inv(hfaces.Count)
                   + " face(s) with references, flats at " + (FlatHeights(hfaces).Length > 0 ? FlatHeights(hfaces) : "-") + "; the rest instance references): "
                   + string.Join(" | ", cands.Select(c => c.Label + " " + (StableKey(Doc, c.Ref) ?? "?"))));
                if (cands.Count == 0)
                {
                    string heights = FlatHeights(hfaces);
                    notes.Add("no face or reference plane of the hanger at the invert " + Fmm(zInv) + " (its flat faces are at "
                              + (heights.Length > 0 ? heights : "-") + ")");
                    return "no (no hanger face or reference at the invert)";
                }
                string bkey = FamKey(inst) + "|bottom";
                cands = Prefer(cands, bkey);
                int budget = Math.Min(40, MaxTries(bkey));
                int n = 0, refused = 0, rejected = 0, noTargets = 0;
                string lastRefused = null, lastReject = null;
                string wl; string ws;
                // ---- what worked last time for this family: one attempt, kept at once
                if (_worked.TryGetValue(bkey, out wl) && _bottomSrcWorked.TryGetValue(bkey, out ws) && NormLabel(cands[0].Label) == wl)
                {
                    List<RefItem> items0 = BottomItems(set, ws, view, unit, host, what);
                    if (items0.Count > 0)
                    {
                        string text, err;
                        n++; budget--;
                        int s = AlignOnce(view, items0[0].Ref, cands[0].Ref, inst, host, along, across, true, BottomCheck(5.0 / MM), out text, out err);
                        BL("attempt " + Inv(n) + " (cached) source=" + ws + " duct face " + (StableKey(Doc, items0[0].Ref) ?? "?") + " <-> hanger " + cands[0].Label + " " + (StableKey(Doc, cands[0].Ref) ?? "?") + ": " + text);
                        if (s == 2)
                        {
                            _worked[bkey] = NormLabel(cands[0].Label);
                            Outcome(bkey, true);
                            BL("LOCKED to the bottom: hanger " + cands[0].Label + " <-> " + what + " " + items0[0].Label + " (" + Inv(swAll.ElapsedMilliseconds) + " ms)");
                            return "yes";
                        }
                        if (s == 1) { rejected++; lastReject = text; } else { refused++; lastRefused = err; }
                    }
                }
                // ---- probe everything
                var seenT = new HashSet<string>(StringComparer.Ordinal);
                string[] srcs = _bottomSrcWorked.TryGetValue(bkey, out ws) ? BottomSrcs.OrderBy(s => s == ws ? 0 : 1).ToArray() : BottomSrcs;
                foreach (string src in srcs)
                {
                    if (budget <= 0) break;
                    List<RefItem> items = BottomItems(set, src, view, unit, host, what);
                    if (items.Count == 0) { noTargets++; continue; }
                    foreach (RefItem target in items)
                    {
                        if (budget <= 0) break;
                        string tstable = StableKey(Doc, target.Ref);
                        if (tstable != null && !seenT.Add(tstable)) { BL("duct face " + tstable + " [" + src + "] already tried from another source"); continue; }
                        RefItem bestC = null;
                        double bestDz = double.MaxValue;
                        foreach (RefItem c in cands)
                        {
                            if (budget <= 0) break;
                            string text, err;
                            n++; budget--;
                            int s = AlignOnce(view, target.Ref, c.Ref, inst, host, along, across, false, BottomCheck(25.0 / MM), out text, out err);
                            BL("attempt " + Inv(n) + " source=" + src + " duct face " + (tstable ?? "?") + " <-> hanger " + c.Label + " [" + c.Type + "] " + (StableKey(Doc, c.Ref) ?? "?") + ": " + text);
                            if (s == 1) { rejected++; lastReject = text; continue; }
                            if (s == 0) { refused++; lastRefused = err; continue; }
                            double dz = _lastMeas != null ? Math.Abs(_lastMeas.Dz) : 0.0;
                            if (dz < bestDz) { bestDz = dz; bestC = c; }
                            if (dz < 0.5 / MM) break;   // exactly in place: no need to look further
                        }
                        if (bestC == null) continue;
                        string t2, e2;
                        int s2 = AlignOnce(view, target.Ref, bestC.Ref, inst, host, along, across, true, BottomCheck(25.0 / MM), out t2, out e2);
                        BL("KEEP source=" + src + " duct face " + (tstable ?? "?") + " <-> hanger " + bestC.Label + " [" + bestC.Type + "]: " + t2);
                        if (s2 == 2)
                        {
                            _worked[bkey] = NormLabel(bestC.Label);
                            _bottomSrcWorked[bkey] = src;
                            Outcome(bkey, true);
                            BL("LOCKED to the bottom: hanger " + bestC.Label + " <-> " + what + " " + target.Label + " (" + Inv(swAll.ElapsedMilliseconds) + " ms)");
                            return "yes";
                        }
                    }
                }
                Outcome(bkey, false);
                if (noTargets == srcs.Length)
                {
                    notes.Add("no flat bottom face found on the " + what);
                    BL("no flat bottom face with a reference from any source (" + Inv(swAll.ElapsedMilliseconds) + " ms)");
                    return "no (no flat bottom face with a reference on the " + what + ")";
                }
                string heights2 = FlatHeights(hfaces);
                string whyNo = Inv(n) + " attempt(s): Revit refused " + Inv(refused) + ", " + Inv(rejected) + " accepted but would have moved the hanger wrongly"
                               + (lastRefused != null ? " (last refusal: " + lastRefused + ")" : "");
                BL("not locked: " + whyNo + " (" + Inv(swAll.ElapsedMilliseconds) + " ms)");
                notes.Add("bottom lock refused - the hanger has nothing exactly at the invert " + Fmm(zInv) + " (its flat faces are at "
                          + (heights2.Length > 0 ? heights2 : "-") + ")" + (!string.IsNullOrEmpty(lastRefused) ? "; Revit: " + lastRefused : "")
                          + (rejected > 0 ? "; " + Inv(rejected) + " accepted alignment(s) would have moved the hanger away from its place" : ""));
                return "no (" + whyNo + ")";
            }
        }
    }
}
