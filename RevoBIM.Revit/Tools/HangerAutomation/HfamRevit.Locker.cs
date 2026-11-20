using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
        // ============================================================= locks
        public static readonly string[] PlanTypes = { "FloorPlan", "CeilingPlan", "EngineeringPlan" };

        /// <summary>(lines, planar faces) of an element with references (centreline included).</summary>
        public class GeoItemsResult
        {
            public List<Line> Lines = new List<Line>();
            public List<PlanarFace> Faces = new List<PlanarFace>();
        }

        public static GeoItemsResult GeoItems(Element el, View view)
        {
            var res = new GeoItemsResult();
            Options opt = new Options();
            opt.ComputeReferences = true;
            opt.IncludeNonVisibleObjects = true;
            if (view != null) opt.View = view;
            try
            {
                GeometryElement geo = el.get_Geometry(opt);
                if (geo != null) GeoWalk(geo, res);
            }
            catch (Exception) { }
            return res;
        }

        /// <summary>Lines with a reference in an element's geometry. view != null: the geometry as that view shows it (its detail
        /// level and visibility decide whether a centreline exists); else the geometry at `detail`, whatever any view shows.
        /// Non-visible objects are included (a pipe / duct centreline is one).</summary>
        public static List<Line> GeoLines(Element el, View view, ViewDetailLevel? detail)
        {
            var res = new GeoItemsResult();
            Options opt = new Options();
            opt.ComputeReferences = true;
            opt.IncludeNonVisibleObjects = true;
            if (view != null) opt.View = view;
            else if (detail != null)
            {
                try { opt.DetailLevel = detail.Value; }
                catch (Exception) { }
            }
            try
            {
                GeometryElement geo = el.get_Geometry(opt);
                if (geo != null) GeoWalk(geo, res);
            }
            catch (Exception) { }
            return res.Lines;
        }

        private static void GeoWalk(IEnumerable<GeometryObject> geo, GeoItemsResult res)
        {
            foreach (GeometryObject g in geo)
            {
                GeometryInstance gi = g as GeometryInstance;
                Solid so = g as Solid;
                Line ln = g as Line;
                if (gi != null)
                    GeoWalk(gi.GetInstanceGeometry(), res);
                else if (so != null)
                {
                    foreach (Face f in so.Faces)
                    {
                        PlanarFace pf = f as PlanarFace;
                        if (pf != null && pf.Reference != null) res.Faces.Add(pf);
                    }
                }
                else if (ln != null)
                {
                    try
                    {
                        if (ln.Reference != null) res.Lines.Add(ln);
                    }
                    catch (Exception) { }
                }
            }
        }

        /// <summary>'duct', 'pipe', ... for services; the category name for anything else.</summary>
        public static string HostKind(Element el)
        {
            if (IsRvtDuct(el) || el is FabricationPart) return ServiceKind(el);
            try { return el.Category.Name.ToLowerInvariant(); }
            catch (Exception) { return "element"; }
        }

        public static string LockSectionName(Element host)
        {
            return "Hanger Automation - bottom locks " + HostKind(host) + " " + Inv(Eid(host.Id));
        }

        /// <summary>The tool's own lock views (sections and centre-lock plans) already in the model, read once per Locker,
        /// plus the view family types needed to make more.</summary>
        public class LockViews
        {
            public const string Prefix = "Hanger Automation - ";
            public Dictionary<string, View> Named = new Dictionary<string, View>(StringComparer.Ordinal);
            public ViewFamilyType SectionVft, PlanVft;
            public Dictionary<long, ViewPlan> Plans = new Dictionary<long, ViewPlan>();
            public HashSet<long> PlanFailed = new HashSet<long>();
            private bool _loaded;

            public void Load(Document doc)
            {
                if (_loaded) return;
                _loaded = true;
                foreach (Type t in new[] { typeof(ViewSection), typeof(ViewPlan) })
                {
                    try
                    {
                        foreach (Element e in new FilteredElementCollector(doc).OfClass(t))
                        {
                            View v = (View)e;
                            try
                            {
                                if (v.IsTemplate) continue;
                            }
                            catch (Exception) { }
                            string nm = ElName(v);
                            if (nm.StartsWith(Prefix, StringComparison.Ordinal) && !Named.ContainsKey(nm)) Named[nm] = v;
                        }
                    }
                    catch (Exception) { }
                }
                try
                {
                    foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(ViewFamilyType)))
                    {
                        ViewFamilyType v = (ViewFamilyType)e;
                        if (SectionVft == null && v.ViewFamily == ViewFamily.Section) SectionVft = v;
                        if (PlanVft == null && v.ViewFamily == ViewFamily.FloorPlan) PlanVft = v;
                        if (SectionVft != null && PlanVft != null) break;
                    }
                }
                catch (Exception) { }
            }

            /// <summary>A view made on an earlier run (exact name, else its first '(n)' copy).</summary>
            public View Find(string name)
            {
                // a view made in a placement Revit later undid (a rolled-back transaction) is gone: forget it, never hand it out
                List<string> dead = null;
                foreach (KeyValuePair<string, View> kv in Named)
                {
                    if (!Alive(kv.Value))
                    {
                        if (dead == null) dead = new List<string>();
                        dead.Add(kv.Key);
                    }
                }
                if (dead != null)
                    foreach (string d in dead) Named.Remove(d);
                View best = null;
                foreach (KeyValuePair<string, View> kv in Named)
                {
                    if (kv.Key == name) return kv.Value;
                    if (best == null && kv.Key.StartsWith(name + " (", StringComparison.Ordinal)) best = kv.Value;
                }
                return best;
            }
        }

        /// <summary>A bottom-lock section made on an earlier run (exact name, else its
        /// first '(n)' copy), so each service keeps one.</summary>
        public static ViewSection FindLockSection(Document doc, string name)
        {
            ViewSection best = null;
            try
            {
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(ViewSection)))
                {
                    ViewSection v = (ViewSection)e;
                    try
                    {
                        if (v.IsTemplate) continue;
                    }
                    catch (Exception) { }
                    string nm = ElName(v);
                    if (nm == name) return v;
                    if (best == null && nm.StartsWith(name + " (", StringComparison.Ordinal)) best = v;
                }
            }
            catch (Exception) { }
            return best;
        }

        public static ViewSection MakeLockSection(Document doc, Element service, Section sec, FhaDebugLog log)
        {
            return MakeLockSection(doc, service, sec, log, null);
        }

        /// <summary>A section along the service that holds its hangers' bottom locks
        /// (a lock on a horizontal face lives in a section / elevation view and is
        /// deleted with it). Reuses the one made on an earlier run. `views` (optional): the Locker's
        /// read-once list of the tool's views, so a run over many services does not scan every section for each.</summary>
        public static ViewSection MakeLockSection(Document doc, Element service, Section sec, FhaDebugLog log, LockViews views)
        {
            string baseName = LockSectionName(service);
            ViewSection old;
            if (views != null)
            {
                views.Load(doc);
                old = views.Find(baseName) as ViewSection;
            }
            else
                old = FindLockSection(doc, baseName);
            if (old != null)
            {
                log.Add("   lock section: reusing " + ElName(old));
                return old;
            }
            ViewFamilyType vft = null;
            if (views != null)
                vft = views.SectionVft;
            else
            {
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(ViewFamilyType)))
                {
                    ViewFamilyType v = (ViewFamilyType)e;
                    if (v.ViewFamily == ViewFamily.Section)
                    {
                        vft = v;
                        break;
                    }
                }
            }
            if (vft == null) return null;
            V3 along, across;
            HfamCore.PlanDirs(sec.A, sec.B, out along, out across);
            double L = FhaCore.VLen(FhaCore.VSub(sec.B, sec.A));
            V3 mid = FhaCore.VScale(FhaCore.VAdd(sec.A, sec.B), 0.5);
            Transform tf = Transform.Identity;
            tf.Origin = ToXyz(mid);
            tf.BasisX = new XYZ(along.X, along.Y, 0.0);
            tf.BasisY = XYZ.BasisZ;
            tf.BasisZ = new XYZ(along.Y, -along.X, 0.0);
            BoundingBoxXYZ box = new BoundingBoxXYZ();
            box.Transform = tf;
            double half = L / 2.0 + 1.0;
            box.Min = new XYZ(-half, -(sec.Depth / 2.0 + 3.0), -(sec.Width / 2.0 + 2.0));
            box.Max = new XYZ(half, sec.Depth / 2.0 + 8.0, sec.Width / 2.0 + 2.0);
            ViewSection view = ViewSection.CreateSection(doc, vft.Id, box);
            for (int n = 0; n < 20; n++)
            {
                try
                {
                    view.Name = n == 0 ? baseName : baseName + " (" + Inv(n) + ")";
                    break;
                }
                catch (Exception) { continue; }
            }
            try { doc.Regenerate(); }   // so the new view has geometry to take references from
            catch (Exception) { }
            if (views != null) views.Named[ElName(view)] = view;
            log.Add("   lock section: " + ElName(view));
            return view;
        }

        public static readonly string[] RefTypes =
        {
            "CenterLeftRight", "CenterFrontBack", "CenterElevation", "Left", "Right", "Front", "Back",
            "Top", "Bottom", "StrongReference", "WeakReference",
        };

        public static readonly Dictionary<string, string> RefLabels = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "CenterLeftRight", "Center (Left/Right)" }, { "CenterFrontBack", "Center (Front/Back)" },
            { "CenterElevation", "Center (Elevation)" }, { "StrongReference", "Strong Reference" },
            { "WeakReference", "Weak Reference" },
        };

        /// <summary>A reference and its label (the Python (reference, label) pairs).</summary>
        public class RefItem
        {
            public Reference Ref;
            public string Label;
            /// <summary>FamilyInstanceReferenceType name (instance references) and the reference plane's own name.</summary>
            public string Type = "", Name = "";
            /// <summary>The geometry line a centreline reference came from (for its exact position).</summary>
            public Line Geo;
            public RefItem() { }
            public RefItem(Reference r, string label) { Ref = r; Label = label; }
        }

        /// <summary>[(reference, label)] of a family instance's reference planes of these
        /// FamilyInstanceReferenceTypes, in that order.</summary>
        public static List<RefItem> InstanceRefs(Element inst, IEnumerable<string> kinds)
        {
            var o = new List<RefItem>();
            foreach (string k in kinds)
            {
                FamilyInstanceReferenceType e;
                if (!Enum.TryParse<FamilyInstanceReferenceType>(k, out e) || !Enum.IsDefined(typeof(FamilyInstanceReferenceType), e)) continue;
                IList<Reference> refs;
                try { refs = ((FamilyInstance)inst).GetReferences(e); }
                catch (Exception) { refs = null; }
                if (refs == null) continue;
                foreach (Reference r in refs)
                {
                    string nm = "";
                    try { nm = ((FamilyInstance)inst).GetReferenceName(r) ?? ""; }
                    catch (Exception) { }
                    string lbl;
                    if (!RefLabels.TryGetValue(k, out lbl)) lbl = k;
                    o.Add(new RefItem(r, lbl + (nm.Length > 0 ? " \"" + nm + "\"" : "")) { Type = k, Name = nm });
                }
            }
            return o;
        }

        /// <summary>'Center (Left/Right) "CL", Strong Reference x2 ...' - what the family offers.</summary>
        public static string FamilyReferenceSummary(Element inst)
        {
            var parts = new List<string>();
            foreach (string k in RefTypes)
            {
                List<RefItem> got = InstanceRefs(inst, new[] { k });
                if (got.Count > 0)
                    parts.Add(string.Join(", ", got.Select(g => g.Label)));
            }
            string s = string.Join("; ", parts);
            return s.Length > 0 ? s : "none (every reference plane is Not a Reference)";
        }

        /// <summary>A planar face with its origin z and normal z, in model coordinates (Python (face, z, nz)).</summary>
        public class FaceZ
        {
            public PlanarFace Face;
            public double Z, Nz;
        }

        /// <summary>Planar faces with references and edge points of a geometry tree, in
        /// model coordinates: (face, origin z, normal z).</summary>
        public static void WalkFaces(IEnumerable<GeometryObject> geo, List<FaceZ> faces, List<V3> pts)
        {
            foreach (GeometryObject g in geo)
            {
                GeometryInstance gi = g as GeometryInstance;
                Solid so = g as Solid;
                if (gi != null)
                {
                    try { WalkFaces(gi.GetInstanceGeometry(), faces, pts); }
                    catch (Exception) { }
                }
                else if (so != null)
                {
                    try
                    {
                        foreach (Face f in so.Faces)
                        {
                            PlanarFace pf = f as PlanarFace;
                            if (pf != null && pf.Reference != null)
                                faces.Add(new FaceZ { Face = pf, Z = pf.Origin.Z, Nz = pf.FaceNormal.Z });
                        }
                    }
                    catch (Exception) { }
                    if (pts != null)
                    {
                        try
                        {
                            foreach (Edge ed in so.Edges)
                                foreach (XYZ p in ed.Tessellate())
                                    pts.Add(new V3(p.X, p.Y, p.Z));
                        }
                        catch (Exception) { }
                    }
                }
            }
        }

        public static List<FaceZ> ElementFaces(Element el, View view = null, List<V3> pts = null)
        {
            Options opt = new Options();
            opt.ComputeReferences = true;
            opt.IncludeNonVisibleObjects = false;
            if (view != null)
                opt.View = view;
            else
            {
                try { opt.DetailLevel = ViewDetailLevel.Fine; }
                catch (Exception) { }
            }
            var faces = new List<FaceZ>();
            try
            {
                GeometryElement geo = el.get_Geometry(opt);
                if (geo != null) WalkFaces(geo, faces, pts);
            }
            catch (Exception) { }
            return faces;
        }

        /// <summary>The (target label, candidate label) pair try_align reports for the alignment Revit accepted.</summary>
        public class AlignHit
        {
            public string TargetLabel, CandidateLabel;
        }

        /// <summary>NewAlignment for the first (target, candidate) pair Revit accepts.
        /// Revit only aligns references that already coincide, so a wrong pair is
        /// simply refused. Returns the pair or null; err = the last refusal (null if none).</summary>
        public static AlignHit TryAlign(Document doc, View view, List<RefItem> targets, List<RefItem> candidates, FhaDebugLog log, int maxTries, out string err)
        {
            int attempts;
            return TryAlign(doc, view, targets, candidates, log, maxTries, out err, out attempts);
        }

        /// <summary>As above, also saying how many pairs were tried.</summary>
        public static AlignHit TryAlign(Document doc, View view, List<RefItem> targets, List<RefItem> candidates, FhaDebugLog log, int maxTries, out string err, out int attempts)
        {
            int n = 0;
            string last = null;
            foreach (RefItem t in targets)
            {
                foreach (RefItem c in candidates)
                {
                    n++;
                    if (n > maxTries)
                    {
                        err = last;
                        attempts = n - 1;
                        return null;
                    }
                    try
                    {
                        doc.Create.NewAlignment(view, t.Ref, c.Ref);
                        err = null;
                        attempts = n;
                        return new AlignHit { TargetLabel = t.Label, CandidateLabel = c.Label };
                    }
                    catch (Exception ex)
                    {
                        last = ex.Message;
                    }
                }
            }
            err = last;
            attempts = n;
            return null;
        }

        private static bool Alive(Element el)
        {
            try { return el == null || el.IsValidObject; }
            catch (Exception) { return true; }
        }

        /// <summary>Align-locks a hanger to what it carries.
        ///
        /// Services: the hanger's centre plane along the run to the service centreline
        /// (plan view), and its face / plane at the invert to the service's bottom
        /// face - or its insulation's, when the hanger sits outside it (in a section
        /// kept per service). Units (equipment, duct accessories): to the unit's
        /// centre planes and bottom face. Single services only; shared hangers are
        /// never locked. Every reference the family offers is tried, so a family
        /// whose centre plane is a Strong / Weak reference still locks.
        ///
        /// Centre lock (rewritten): the centreline is looked for in several ways and the alignment is tried in the active plan (when
        /// it shows the service) and in a plan of the tool's own with a view range that shows everything on the level - the
        /// centre plane of the hanger family is aligned to the service's CENTRELINE reference. Every step is logged. Each
        /// attempt group runs in a sub-transaction that is rolled back unless an alignment was made.</summary>
        public partial class Locker
        {
            public Document Doc;
            public FhaDebugLog Log;
            public View Plan;
            public Dictionary<long, ViewSection> Sections = new Dictionary<long, ViewSection>();
            public HashSet<long?> Told = new HashSet<long?>();
            /// <summary>Round services only: also lock the family's Center (Elevation) plane to the centreline in the lock
            /// section (circular hangers, whose reference sits at the service centre). Best effort, never reported as a note.</summary>
            public bool ElevationCentre;

            private readonly LockViews _views = new LockViews();
            private readonly Dictionary<string, List<RefItem>> _targets = new Dictionary<string, List<RefItem>>(StringComparer.Ordinal);
            private readonly Dictionary<string, BottomInfo> _bottoms = new Dictionary<string, BottomInfo>(StringComparer.Ordinal);
            private readonly Dictionary<string, string> _worked = new Dictionary<string, string>(StringComparer.Ordinal);
            private readonly Dictionary<string, int> _fails = new Dictionary<string, int>(StringComparer.Ordinal);
            private string _lastSource;

            private class BottomInfo
            {
                public List<RefItem> Items;
                public double ZLow;
                public bool None;
            }

            private class TargetSource
            {
                public string Key, Label;
                public Func<List<RefItem>> Get;
            }

            public Locker(Document doc, View view, FhaDebugLog log)
            {
                Doc = doc; Log = log;
                Plan = (view != null && Array.IndexOf(PlanTypes, view.ViewType.ToString()) >= 0) ? view : null;
            }

            private ViewSection SectionFor(Element service, Section sec)
            {
                long key = Eid(service.Id);
                if (Sections.ContainsKey(key) && !Alive(Sections[key]))
                    Sections.Remove(key);   // made in a placement Revit then undid: make it again
                if (!Sections.ContainsKey(key))
                {
                    try
                    {
                        Sections[key] = MakeLockSection(Doc, service, sec, Log, _views);
                    }
                    catch (Exception ex)
                    {
                        Log.Add("   lock section: " + ex.Message);
                        Sections[key] = null;
                    }
                }
                return Sections[key];
            }

            private void TellFamily(FamilyInstance inst)
            {
                long? key;
                try { key = Eid(inst.Symbol.Family.Id); }
                catch (Exception) { key = null; }
                if (Told.Contains(key)) return;
                Told.Add(key);
                Log.Add("   family reference planes: " + FamilyReferenceSummary(inst));
            }

            private static string FamKey(FamilyInstance inst)
            {
                try { return Inv(Eid(inst.Symbol.Family.Id)); }
                catch (Exception) { return "?"; }
            }

            /// <summary>The hanger references with the one that worked last time for this family first (labels of faces are
            /// compared without their height).</summary>
            private List<RefItem> Prefer(List<RefItem> items, string key)
            {
                string w;
                if (!_worked.TryGetValue(key, out w)) return items;
                var first = items.Where(i => NormLabel(i.Label) == w).ToList();
                if (first.Count == 0) return items;
                var o = new List<RefItem>(first);
                o.AddRange(items.Where(i => NormLabel(i.Label) != w));
                return o;
            }

            private static string NormLabel(string label)
            {
                return label.StartsWith("face at ", StringComparison.Ordinal) ? "face" : label;
            }

            /// <summary>How many pairs one lock may try: all 80 normally; 16 once this family has refused twice running (a family
            /// that cannot lock would otherwise cost 80 refusals for every hanger).</summary>
            private int MaxTries(string key)
            {
                int n;
                return _fails.TryGetValue(key, out n) && n >= 2 ? 16 : 80;
            }

            private void Outcome(string key, bool ok)
            {
                int n;
                _fails.TryGetValue(key, out n);
                _fails[key] = ok ? 0 : n + 1;
            }

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

            // ------------------------------------------------------------ the lock
            /// <summary>Lock one hanger to its service (or unit); returns the notes for whatever could not be locked.</summary>
            public List<string> Lock(FamilyInstance inst, Element host, Section sec, V3 q, string axis = null)
            {
                var notes = new List<string>();
                TellFamily(inst);
                V3 along, across;
                HfamCore.PlanDirs(sec.A, sec.B, out along, out across);
                bool unit = sec.Unit;
                string what = HostKind(host);
                // ---- centre: hanger plane along the run <-> service centreline / unit centre plane
                // the hanger was just rotated / moved / re-parameterised in this transaction: its orientation and references are stale
                // until the document regenerates
                try { Doc.Regenerate(); }
                catch (Exception ex) { Log.Add("   centre lock: regenerate before locking: " + ex.Message); }
                XYZ h = inst.HandOrientation, f = inst.FacingOrientation;
                string square = HfamCore.ReferenceTypeAcross(new V3(h.X, h.Y, 0.0), new V3(f.X, f.Y, 0.0), along);
                string alongType = square == "CenterLeftRight" ? "CenterFrontBack" : "CenterLeftRight";
                string byOrient = RefLabels[alongType];
                // the family settings decide: the run axis of the family is its Y (axis=Y) -> its Center (Left/Right) plane is the one
                // along the run; axis=X -> Center (Front/Back). The orientation vectors are only the fallback (no setting / units).
                if (!unit && (axis == "Y" || axis == "X"))
                {
                    alongType = axis == "Y" ? "CenterLeftRight" : "CenterFrontBack";
                    square = axis == "Y" ? "CenterFrontBack" : "CenterLeftRight";
                }
                Log.Add("   centre lock: family axis=" + (axis ?? "?") + "; hanger hand (" + Fm(h.X, 5) + ", " + Fm(h.Y, 5) + ") facing (" + Fm(f.X, 5) + ", " + Fm(f.Y, 5)
                        + "), run (" + Fm(along.X, 5) + ", " + Fm(along.Y, 5) + ") -> plane along the run: " + RefLabels[alongType]
                        + " (orientation alone would say " + byOrient + ")");
                using (HaTiming.Time("lock.centre"))
                {
                    // primary: face-based EQ lock (service side face - hanger centre plane - side face); services only.
                    // fallback: the old centreline alignment, which Revit refuses for a line-to-plane pair in plan views.
                    string eqWhy = null;
                    bool eq = false;
                    if (!unit)
                    {
                        using (HaTiming.Time("lock.centre.eq"))
                        {
                            try { eq = LockEq(inst, host, sec, q, along, across, alongType, square, what, out eqWhy); }
                            catch (Exception ex)
                            {
                                eqWhy = ExText(ex);
                                Log.Add("   centre lock: EQ lock failed unexpectedly - " + eqWhy);
                            }
                        }
                    }
                    if (eq)
                    {
                        if (sec.Round && ElevationCentre) LockElevationCentre(inst, host, sec, along, what);
                    }
                    else
                    {
                        if (!unit) Log.Add("   centre lock: falling back to the centreline alignment (" + eqWhy + ")");
                        int before = notes.Count;
                        LockCentre(inst, host, sec, q, along, alongType, square, unit, what, notes);
                        if (!unit && eqWhy != null && notes.Count > before)
                            notes[before] = "face-based EQ lock: " + eqWhy + "; centreline alignment: " + notes[before];
                    }
                }
                // ---- bottom: hanger at the invert <-> service / insulation / unit bottom face
                if (sec.Round)
                {
                    Log.Add("   round " + what + ": centre lock only (no flat bottom face)");
                    return notes;
                }
                using (HaTiming.Time("lock.bottom"))
                    LockBottom(inst, host, sec, q, unit, what, notes);
                return notes;
            }

            private void LockBottom(FamilyInstance inst, Element host, Section sec, V3 q, bool unit, string what, List<string> notes)
            {
                double zInv = q.Z - sec.Depth / 2.0;
                string bk = Inv(Eid(host.Id)) + (sec.InsUsed ? "|ins" : "|bare") + (unit ? "|unit" : "");
                BottomInfo bi;
                if (!_bottoms.TryGetValue(bk, out bi))
                {
                    // the service's own bottom faces: read once per service (every hanger on it shares them)
                    bi = new BottomInfo();
                    var owners = new List<Element> { host };
                    if (sec.InsUsed)
                    {
                        try
                        {
                            var ins = InsulationLiningBase.GetInsulationIds(Doc, host.Id).Select(i => Doc.GetElement(i)).ToList();
                            if (ins.Count > 0) owners = ins;
                        }
                        catch (Exception) { }
                    }
                    var downs = new List<FaceZ>();
                    foreach (Element el in owners)
                        downs.AddRange(ElementFaces(el).Where(fz => fz.Nz < -0.99));
                    if (downs.Count == 0)
                        bi.None = true;
                    else
                    {
                        bi.ZLow = downs.Min(fz => fz.Z);
                        bi.Items = downs.Where(fz => Math.Abs(fz.Z - bi.ZLow) < 2.0 / MM)
                                        .Select(fz => new RefItem(fz.Face.Reference, "bottom face at " + Fmm(fz.Z))).ToList();
                        if (unit)
                            bi.Items.AddRange(InstanceRefs(host, new[] { "Bottom" }));
                    }
                    _bottoms[bk] = bi;
                }
                if (bi.None)
                {
                    notes.Add("no flat bottom face found on the " + what);
                    return;
                }
                List<RefItem> bottoms = bi.Items;
                ViewSection view = SectionFor(host, sec);
                if (view == null)
                {
                    notes.Add("no section view type for the bottom lock");
                    return;
                }
                List<FaceZ> hfaces = ElementFaces(inst, view);
                if (hfaces.Count == 0) hfaces = ElementFaces(inst);
                var flats = hfaces.Where(fz => Math.Abs(fz.Nz) > 0.99 && Math.Abs(fz.Z - zInv) < 2.0 / MM)
                                  .Select((fz, i) => new { fz, i }).OrderBy(z => -z.fz.Nz).ThenBy(z => z.i).Select(z => z.fz).ToList();   // the upward face (bearer top) first
                var cands2 = flats.Select(fz => new RefItem(fz.Face.Reference, "face at " + Fmm(fz.Z))).ToList();
                cands2.AddRange(InstanceRefs(inst, new[] { "Bottom", "Top", "CenterElevation", "StrongReference", "WeakReference" }));
                if (cands2.Count == 0)
                {
                    string heights = FlatHeights(hfaces);
                    notes.Add("no face or reference plane of the hanger at the invert " + Fmm(zInv) + " (its flat faces are at "
                              + (heights.Length > 0 ? heights : "-") + ")");
                    return;
                }
                string bkey = FamKey(inst) + "|bottom";
                cands2 = Prefer(cands2, bkey);
                string err2; int attempts;
                AlignHit hit2 = Attempt(view, bottoms, cands2, MaxTries(bkey), out err2, out attempts);
                Outcome(bkey, hit2 != null);
                if (hit2 != null)
                {
                    _worked[bkey] = NormLabel(hit2.CandidateLabel);
                    Log.Add("   locked to the bottom: hanger " + hit2.CandidateLabel + " <-> " + what + " " + hit2.TargetLabel);
                }
                else
                {
                    string heights = FlatHeights(hfaces);
                    notes.Add("bottom lock refused - the hanger has nothing exactly at the invert " + Fmm(zInv) + " (its flat faces are at "
                              + (heights.Length > 0 ? heights : "-") + ")" + (!string.IsNullOrEmpty(err2) ? "; Revit: " + err2 : ""));
                }
            }

            /// <summary>', '.join(sorted(set(fmm(z) ...))) of the flat faces - sorted as text, as the Python did.</summary>
            private static string FlatHeights(List<FaceZ> hfaces)
            {
                return string.Join(", ", hfaces.Where(fz => Math.Abs(fz.Nz) > 0.99).Select(fz => Fmm(fz.Z))
                                               .Distinct().OrderBy(s => s, StringComparer.Ordinal));
            }
        }

        /// <summary>Lock a single-service hanger; shared hangers are never locked.</summary>
        public static void LockIf(Locker locker, FamilyInstance inst, Element service, Section sec, V3 q, List<string> problems, FhaDebugLog log, FamConfig cfg = null)
        {
            if (locker == null || inst == null) return;
            if ((sec.Keys != null ? sec.Keys.Count : 1) > 1)
            {
                log.Add("   not locked: shared hanger");
                return;
            }
            using (HaTiming.Time("lock"))
            {
                foreach (string n in locker.Lock(inst, service, sec, q, cfg != null ? cfg.Get("axis", "X") : null))
                {
                    log.Add("   lock: " + n);
                    problems.Add("Lock: " + n);
                }
            }
        }
    }
}
