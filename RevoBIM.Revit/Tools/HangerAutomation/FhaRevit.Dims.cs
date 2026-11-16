using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using DimTargetsT = RevoBIM.Tools.HangerAutomation.DimTargets;

namespace RevoBIM.Tools.HangerAutomation
{
    /// <summary>A ticked sheet and the keys of the views on it that were dimensioned in (the Python (sheet element, [view keys]) pairs).</summary>
    public class SheetTarget
    {
        public ViewSheet Sheet;
        public List<long> Keys = new List<long>();
    }

    /// <summary>The views a run's dimensions go in, and how many runs each got.</summary>
    public class DimTargets
    {
        public List<View> Views;
        public bool Active;
        public List<SheetTarget> Sheets;    // ticked in the picker
        public Dictionary<long, int> Count = new Dictionary<long, int>();

        public DimTargets(List<View> views, bool active = false, List<SheetTarget> sheets = null)
        {
            Views = views;
            Active = active;
            Sheets = sheets ?? new List<SheetTarget>();
        }

        public void Add(View view)
        {
            long k = FhaRevit.EidValue(view.Id);
            int n;
            Count.TryGetValue(k, out n);
            Count[k] = n + 1;
        }

        public string Summary(int dimmed, int runs)
        {
            if (Active)
                return dimmed.ToString(CultureInfo.InvariantCulture) + " of " + runs.ToString(CultureInfo.InvariantCulture)
                       + " runs dimensioned in " + FhaRevit.ElName(Views[0]) + ".";
            int got = Views.Count(v => { int n; return Count.TryGetValue(FhaRevit.EidValue(v.Id), out n) && n != 0; });
            return dimmed.ToString(CultureInfo.InvariantCulture) + " of " + runs.ToString(CultureInfo.InvariantCulture)
                   + " runs dimensioned, in " + got.ToString(CultureInfo.InvariantCulture) + " of the "
                   + Views.Count.ToString(CultureInfo.InvariantCulture) + " views chosen.";
        }
    }

    public static partial class FhaRevit
    {
        // ============================================================ dimensions
        public static readonly string[] DimViewTypes =
        {
            "FloorPlan", "CeilingPlan", "EngineeringPlan", "AreaPlan", "Section", "Elevation", "Detail",
        };

        public static bool CanDimensionIn(View view)
        {
            try { return !(view is View3D) && Array.IndexOf(DimViewTypes, view.ViewType.ToString()) >= 0; }
            catch (Exception) { return false; }
        }

        /// <summary>Planar faces of el whose normal runs along `direction`, with references.</summary>
        public static List<PlanarFace> FacesAcross(Element el, V3 direction, View view)
        {
            var o = new List<PlanarFace>();
            foreach (bool useView in new[] { true, false })
            {
                Options opt = new Options();
                opt.ComputeReferences = true;
                if (useView && view != null) opt.View = view;
                else opt.DetailLevel = ViewDetailLevel.Fine;
                try
                {
                    GeometryElement geo = el.get_Geometry(opt);
                    if (geo != null) WalkFaces(geo, direction, o);
                }
                catch (Exception) { }
                if (o.Count > 0) break;
            }
            return o;
        }

        private static void WalkFaces(IEnumerable<GeometryObject> geo, V3 direction, List<PlanarFace> o)
        {
            foreach (GeometryObject g in geo)
            {
                GeometryInstance gi = g as GeometryInstance;
                Solid so = g as Solid;
                if (gi != null)
                    WalkFaces(gi.GetInstanceGeometry(), direction, o);
                else if (so != null)
                {
                    foreach (Face f in so.Faces)
                    {
                        PlanarFace pf = f as PlanarFace;
                        if (pf != null && pf.Reference != null)
                        {
                            if (Math.Abs(FhaCore.VDot(Pt(pf.FaceNormal), direction)) > 0.99)
                                o.Add(pf);
                        }
                    }
                }
            }
        }

        /// <summary>Python _t: distance of a face's origin from `origin`, measured along `direction`.</summary>
        public static double T(PlanarFace face, V3 origin, V3 direction)
        {
            return FhaCore.VDot(FhaCore.VSub(Pt(face.Origin), origin), direction);
        }

        // ---- views to dimension in (the active one, or chosen in the Dimension views picker)
        /// <summary>(p0, p1) of a run's dimension line in this view: offset to the side in a
        /// plan, below the run and in the view plane in a section / elevation.</summary>
        public static void ViewDimLine(View view, V3 pStart, V3 pEnd, double offsetMm, out V3 p0, out V3 p1)
        {
            p0 = new V3(); p1 = new V3();
            try
            {
                if (Array.IndexOf(FhaCore.PlanViewTypes, view.ViewType.ToString()) < 0)
                {
                    V3 a, b;
                    FhaCore.DimLineInView(pStart, pEnd, offsetMm, Pt(view.UpDirection), Pt(view.ViewDirection), Pt(view.Origin), out a, out b);
                    p0 = a; p1 = b;
                    return;
                }
            }
            catch (Exception) { }
            V3 normal;
            FhaCore.DimLine(pStart, pEnd, offsetMm, out p0, out p1, out normal);
            try   // in a plan the line sits on the view's own level
            {
                double z = view.GenLevel.ProjectElevation;
                p0 = new V3(p0.X, p0.Y, z);
                p1 = new V3(p1.X, p1.Y, z);
            }
            catch (Exception) { }
        }

        /// <summary>A plan takes any horizontal run; a section only a run along it.</summary>
        public static bool RunFitsView(View view, V3 pStart, V3 pEnd)
        {
            try
            {
                if (Array.IndexOf(FhaCore.PlanViewTypes, view.ViewType.ToString()) >= 0) return true;
                V3 r = Pt(view.RightDirection);
                return Math.Abs(FhaCore.VDot(FhaCore.VNorm(FhaCore.VSub(pEnd, pStart)), FhaCore.VNorm(r))) > 0.999;
            }
            catch (Exception) { return true; }
        }

        /// <summary>Every plan / section view a run can be dimensioned in.</summary>
        public static List<ViewRow> DimViewRows(Document doc)
        {
            var rows = new List<ViewRow>();
            foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(View)))
            {
                try
                {
                    View v = (View)e;
                    if (v.IsTemplate || !CanDimensionIn(v)) continue;
                    rows.Add(new ViewRow { Key = EidValue(v.Id), Id = v.Id, Name = ElName(v), Type = v.ViewType.ToString(), Scale = v.Scale });
                }
                catch (Exception) { }
            }
            return rows;
        }

        /// <summary>Sheets carrying such a view.</summary>
        public static List<SheetRow> DimSheetRows(Document doc, HashSet<long> okKeys)
        {
            var o = new List<SheetRow>();
            foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(ViewSheet)))
            {
                ViewSheet sh = (ViewSheet)e;
                try
                {
                    if (sh.IsPlaceholder) continue;
                }
                catch (Exception) { }
                List<long> placed;
                try { placed = sh.GetAllPlacedViews().Select(i => EidValue(i)).ToList(); }
                catch (Exception) { placed = new List<long>(); }
                List<long> views = placed.Where(k => okKeys.Contains(k)).ToList();
                if (views.Count > 0)
                    o.Add(new SheetRow { Key = EidValue(sh.Id), Id = sh.Id, Number = sh.SheetNumber, Name = ElName(sh), Views = views });
            }
            return o;
        }

        /// <summary>Where this run's dimensions go, or null for none. The active view if
        /// it can take dimensions; otherwise (a 3D view) the user is asked - skip, or
        /// tick sheets and views in the picker (settings.Prompts). Call before any
        /// transaction group.</summary>
        public static DimTargetsT DimTargets(UIDocument uidoc, FhaSettings settings, string key, JobResult res, FhaDebugLog log)
        {
            if (!FhaCore.AsBool(settings, key)) return null;
            View view = uidoc.ActiveView;
            if (CanDimensionIn(view)) return new DimTargetsT(new List<View> { view }, true);
            IFhaPrompts ui = settings.Prompts;
            if (ui == null)
            {
                res.Lines.Add("Dimensions skipped: open a plan or section view to get them.");
                return null;
            }
            Document doc = uidoc.Document;
            List<ViewRow> rows = DimViewRows(doc);
            List<SheetRow> sheets = DimSheetRows(doc, new HashSet<long>(rows.Select(r => r.Key)));
            DimChoice choice;
            try
            {
                choice = ui.ChooseDimViews(ElName(view), rows, sheets);
            }
            catch (Exception ex)
            {
                log.Add("dimension views: " + ex.Message);
                choice = null;
            }
            if (choice == null)
            {
                res.Lines.Add("Dimension placement skipped.");
                log.Add("dimensions: skipped from " + ElName(view));
                return null;
            }
            var byKey = new Dictionary<long, ViewRow>();
            foreach (ViewRow r in rows) byKey[r.Key] = r;
            List<long> keys = FhaCore.ChosenViews(choice.Views, choice.Sheets, sheets);
            var views = new List<View>();
            foreach (long k in keys)
            {
                ViewRow vr;
                if (!byKey.TryGetValue(k, out vr)) continue;
                View v = doc.GetElement(vr.Id) as View;
                if (v != null) views.Add(v);
            }
            var chosen = new List<SheetTarget>();
            foreach (SheetRow r in sheets)
            {
                if (!choice.Sheets.Contains(r.Key)) continue;
                ViewSheet sh = doc.GetElement(r.Id) as ViewSheet;
                if (sh != null) chosen.Add(new SheetTarget { Sheet = sh, Keys = r.Views });
            }
            log.Add("dimensions: in " + views.Count.ToString(CultureInfo.InvariantCulture) + " views - "
                    + string.Join(", ", views.Take(20).Select(v => ElName(v))));
            return new DimTargetsT(views, false, chosen);
        }

        /// <summary>Dimension one run in every target view (each its own transaction).
        /// place(view) -> hangers dimensioned. True if any view took it.</summary>
        public static bool DimensionInTargets(Document doc, DimTargetsT targets, V3 pStart, V3 pEnd, Func<View, int> place, FhaDebugLog log)
        {
            bool got = false;
            foreach (View v in targets.Views)
            {
                if (!RunFitsView(v, pStart, pEnd))
                {
                    log.Add("dimension: the run does not lie along " + ElName(v) + " - not dimensioned there");
                    continue;
                }
                Transaction t = StartTxn(doc, "Hanger dimension");
                try
                {
                    int n = place(v);
                    if (n != 0 && Committed(t))
                    {
                        targets.Add(v);
                        got = true;
                    }
                    else if (n == 0)
                    {
                        Rollback(t);
                    }
                }
                catch (Exception ex)
                {
                    log.Add("dimension in " + ElName(v) + ": " + ex.Message);
                    Rollback(t);
                }
            }
            return got;
        }

        public static void OpenViews(UIDocument uidoc, IEnumerable<View> views, FhaDebugLog log)
        {
            foreach (View v in views)
            {
                try { uidoc.ActiveView = v; }
                catch (Exception ex)
                {
                    try { uidoc.RequestViewChange(v); }
                    catch (Exception) { log.Add("open " + ElName(v) + ": " + ex.Message); }
                }
            }
        }

        /// <summary>After a run dimensioned in chosen views: ask whether to open them (or
        /// the ticked sheets they are on). Call with no transaction open.</summary>
        public static void OfferOpen(UIDocument uidoc, FhaSettings settings, DimTargetsT targets, int runs, FhaDebugLog log)
        {
            if (targets == null || targets.Active || runs == 0) return;
            IFhaPrompts ui = settings.Prompts;
            List<View> done = targets.Views.Where(v => { int n; return targets.Count.TryGetValue(EidValue(v.Id), out n) && n != 0; }).ToList();
            if (ui == null || done.Count == 0) return;
            List<ViewSheet> sheets = targets.Sheets.Where(st => st.Keys.Any(k => { int n; return targets.Count.TryGetValue(k, out n) && n != 0; }))
                                                   .Select(st => st.Sheet).ToList();
            string ans;
            try
            {
                ans = ui.AskOpen(runs, done.Select(v => ElName(v)).ToList(),
                                 sheets.Select(sh => sh.SheetNumber + " - " + ElName(sh)).ToList());
            }
            catch (Exception ex)
            {
                log.Add("open views: " + ex.Message);
                return;
            }
            List<View> pick = ans == "sheets" ? sheets.Cast<View>().ToList() : (ans == "views" ? done : new List<View>());
            log.Add("opening " + pick.Count.ToString(CultureInfo.InvariantCulture) + " " + (string.IsNullOrEmpty(ans) ? "nothing" : ans));
            OpenViews(uidoc, pick, log);
        }

        /// <summary>One chained dimension along a span: run start, every hanger, run end.
        ///
        /// Hangers use the face pointing back toward the run start, so the spacing
        /// between hangers reads true. Returns the number of hangers dimensioned.</summary>
        public static int ChainDimension(Document doc, View view, V3 pStart, V3 pEnd, IEnumerable<Element> hangers, Element firstEl, Element lastEl, FhaSettings settings, DimensionType dimType, FhaDebugLog log)
        {
            try { doc.Regenerate(); }   // hangers placed this run need geometry before another view can reference them
            catch (Exception) { }
            V3 d = FhaCore.VNorm(FhaCore.VSub(pEnd, pStart));
            var items = new List<KeyValuePair<double, Reference>>();
            foreach (Element h in hangers)
            {
                List<PlanarFace> fs = FacesAcross(h, d, view);
                V3? hp = HangerPoint(h);
                if (fs.Count == 0 || hp == null) continue;
                double th = FhaCore.VDot(FhaCore.VSub(hp.Value, pStart), d);
                List<PlanarFace> back = fs.Where(f => FhaCore.VDot(Pt(f.FaceNormal), d) < 0).ToList();
                if (back.Count == 0) back = fs;
                PlanarFace best = null; double bestKey = 0;
                foreach (PlanarFace f in back)
                {
                    double k = Math.Abs(T(f, pStart, d) - th);
                    if (best == null || k < bestKey) { best = f; bestKey = k; }
                }
                items.Add(new KeyValuePair<double, Reference>(T(best, pStart, d), best.Reference));
            }
            int nH = items.Count;
            var itemsH = new List<KeyValuePair<double, Reference>>(items);
            foreach (var pair in new[] { new { el = firstEl, atEnd = false }, new { el = lastEl, atEnd = true } })
            {
                List<PlanarFace> fs = FacesAcross(pair.el, d, view);
                if (fs.Count > 0)
                {
                    PlanarFace f = null; double fk = 0;
                    foreach (PlanarFace c in fs)
                    {
                        double k = T(c, pStart, d);
                        if (f == null || (pair.atEnd ? k > fk : k < fk)) { f = c; fk = k; }
                    }
                    items.Add(new KeyValuePair<double, Reference>(T(f, pStart, d), f.Reference));
                }
            }
            items = FhaCore.CollapseRefs(items, 0.01);
            if (items.Count < 2 || nH == 0)
            {
                log.Add("dimension skipped: " + items.Count.ToString(CultureInfo.InvariantCulture) + " references ("
                        + nH.ToString(CultureInfo.InvariantCulture) + " hangers)");
                return 0;
            }
            ReferenceArray refs = new ReferenceArray();
            foreach (var kv in items) refs.Append(kv.Value);
            V3 p0, p1;
            ViewDimLine(view, pStart, pEnd, FhaCore.AsFloat(settings, "dim_offset", 800.0), out p0, out p1);
            Line line = Line.CreateBound(ToXyz(p0), ToXyz(p1));
            for (int pass = 0; pass < 2; pass++)
            {
                string label = pass == 0 ? "run ends and hangers" : "hangers only";
                List<KeyValuePair<double, Reference>> chosen = pass == 0 ? items : null;
                if (chosen == null)   // the full chain was refused: the hangers alone
                {
                    if (nH < 2) break;
                    chosen = FhaCore.CollapseRefs(itemsH, 0.01);
                    refs = new ReferenceArray();
                    foreach (var kv in chosen) refs.Append(kv.Value);
                }
                try
                {
                    if (dimType != null) doc.Create.NewDimension(view, line, refs, dimType);
                    else doc.Create.NewDimension(view, line, refs);
                    log.Add("dimension in " + ElName(view) + ": " + label + ", " + chosen.Count.ToString(CultureInfo.InvariantCulture) + " references");
                    return nH;
                }
                catch (Exception ex)
                {
                    log.Add("NewDimension refused in " + ElName(view) + " (" + label + "): " + ex.Message);
                }
            }
            return 0;
        }

        /// <summary>[(name, DimensionType)] for linear dimension styles.</summary>
        public static List<KeyValuePair<string, DimensionType>> LinearDimensionTypes(Document doc)
        {
            var o = new List<KeyValuePair<string, DimensionType>>();
            try
            {
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(DimensionType)))
                {
                    DimensionType t = (DimensionType)e;
                    try
                    {
                        if (t.StyleType != DimensionStyleType.Linear) continue;
                    }
                    catch (Exception) { }
                    string nm = ElName(t);
                    if (!string.IsNullOrEmpty(nm)) o.Add(new KeyValuePair<string, DimensionType>(nm, t));
                }
            }
            catch (Exception) { }
            return o.Select((x, i) => new { x, i }).OrderBy(z => z.x.Key.ToLowerInvariant(), StringComparer.Ordinal).ThenBy(z => z.i).Select(z => z.x).ToList();
        }

        public static DimensionType FindDimType(Document doc, string name)
        {
            if (string.IsNullOrEmpty(name)) return null;
            foreach (var kv in LinearDimensionTypes(doc))
                if (kv.Key == name) return kv.Value;
            return null;
        }
    }
}
