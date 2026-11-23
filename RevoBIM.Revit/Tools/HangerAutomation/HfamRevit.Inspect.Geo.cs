using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
        // ---------------------------------------------------------------- formatting helpers
        private static string InsEx(Exception ex)
        {
            string m = ex.Message ?? "";
            return ex.GetType().FullName + ": " + m.Replace("\r", " ").Replace("\n", " ");
        }

        private static string InsP(XYZ p)
        {
            if (p == null) return "null";
            return "(" + Fm(p.X * MM, 1) + ", " + Fm(p.Y * MM, 1) + ", " + Fm(p.Z * MM, 1) + ")";
        }

        private static string InsDir(XYZ v)
        {
            if (v == null) return "null";
            return "(" + Fm(v.X, 4) + ", " + Fm(v.Y, 4) + ", " + Fm(v.Z, 4) + ")";
        }

        private static string InsStable(Document doc, Reference r)
        {
            if (r == null) return null;
            try { return r.ConvertToStableRepresentation(doc); }
            catch (Exception) { return null; }
        }

        private static string InsCat(Element e)
        {
            try { return e.Category != null ? e.Category.Name : "(no category)"; }
            catch (Exception) { return "(category ?)"; }
        }

        private static string InsEl(Element e)
        {
            if (e == null) return "null";
            string extra = "";
            FamilyInstance fi = e as FamilyInstance;
            if (fi != null)
            {
                try { extra = " family \"" + ElName(fi.Symbol.Family) + "\" type \"" + ElName(fi.Symbol) + "\""; }
                catch (Exception) { }
            }
            return Inv(Eid(e.Id)) + " " + e.GetType().Name + " [" + InsCat(e) + "] \"" + ElName(e) + "\"" + extra;
        }

        private static string InsView(Document doc, ElementId id)
        {
            View v = null;
            try { v = doc.GetElement(id) as View; }
            catch (Exception) { }
            if (v == null) return "none (id " + Inv(Eid(id)) + ")";
            var sb = new StringBuilder();
            sb.Append(Inv(Eid(v.Id)) + " \"" + ElName(v) + "\"");
            try { sb.Append(" type " + v.ViewType); } catch (Exception) { }
            try { sb.Append(" detail " + v.DetailLevel); } catch (Exception) { }
            try { sb.Append(" discipline " + v.Discipline); } catch (Exception) { }
            return sb.ToString();
        }

        private static string InsCurve(Curve c)
        {
            if (c == null) return "null";
            try
            {
                if (!c.IsBound) return c.GetType().Name + " unbound";
                XYZ a = c.GetEndPoint(0), b = c.GetEndPoint(1);
                string dir = "";
                try { dir = " dir " + InsDir((b - a).Normalize()); }
                catch (Exception) { }
                return c.GetType().Name + " from " + InsP(a) + " to " + InsP(b) + dir + " length " + Fm(c.Length * MM, 1) + " mm";
            }
            catch (Exception ex) { return c.GetType().Name + " (" + ex.GetType().Name + ")"; }
        }

        private static string InsGeomDetail(GeometryObject g)
        {
            try
            {
                PlanarFace pf = g as PlanarFace;
                if (pf != null) return "origin " + InsP(pf.Origin) + " normal " + InsDir(pf.FaceNormal) + " area " + Fm(pf.Area * MM * MM, 0) + " mm2";
                Face f = g as Face;
                if (f != null) return "area " + Fm(f.Area * MM * MM, 0) + " mm2";
                Line ln = g as Line;
                if (ln != null)
                {
                    string dir = "";
                    try { dir = " dir " + InsDir(ln.Direction); }
                    catch (Exception) { }
                    return "from " + InsP(ln.GetEndPoint(0)) + " to " + InsP(ln.GetEndPoint(1)) + dir + " length " + Fm(ln.Length * MM, 1) + " mm";
                }
                Curve cu = g as Curve;
                if (cu != null) return InsCurve(cu);
                Edge ed = g as Edge;
                if (ed != null) return "edge curve " + InsCurve(ed.AsCurve());
                Mesh me = g as Mesh;
                if (me != null) return "mesh with " + Inv(me.Vertices.Count) + " vertices, " + Inv(me.NumTriangles) + " triangles";
                Point pt = g as Point;
                if (pt != null) return "point " + InsP(pt.Coord);
            }
            catch (Exception ex) { return "(detail failed: " + ex.GetType().Name + ")"; }
            return "";
        }

        // ---------------------------------------------------------------- geometry walk (counts + references)
        private static void InsWalk(Document doc, IEnumerable<GeometryObject> geo, string path, int depth, Dictionary<string, InsGeoCount> counts, List<InsGeoItem> items)
        {
            InsGeoCount c;
            if (!counts.TryGetValue(path, out c))
            {
                c = new InsGeoCount();
                counts[path] = c;
            }
            foreach (GeometryObject g in geo)
            {
                if (g == null) continue;
                GeometryInstance gi = g as GeometryInstance;
                Solid so = g as Solid;
                Mesh me = g as Mesh;
                Curve cu = g as Curve;
                Point pt = g as Point;
                if (gi != null)
                {
                    c.Instances++;
                    if (depth < 3)
                    {
                        try { InsWalk(doc, gi.GetInstanceGeometry(), path + ">inst", depth + 1, counts, items); }
                        catch (Exception) { c.Errors++; }
                        try { InsWalk(doc, gi.GetSymbolGeometry(), path + ">sym", depth + 1, counts, items); }
                        catch (Exception) { c.Errors++; }
                    }
                }
                else if (so != null)
                {
                    c.Solids++;
                    try
                    {
                        if (so.Faces.Size == 0) c.EmptySolids++;
                        foreach (Face f in so.Faces)
                        {
                            Reference r = null;
                            try { r = f.Reference; }
                            catch (Exception) { }
                            string kind;
                            if (f is PlanarFace) { c.Planar++; kind = "PlanarFace"; if (r == null) c.PlanarNoRef++; }
                            else if (f is CylindricalFace) { c.Cyl++; kind = "CylindricalFace"; if (r == null) c.CylNoRef++; }
                            else { c.OtherFace++; kind = f.GetType().Name; c.Others.Add(kind); if (r == null) c.OtherFaceNoRef++; }
                            if (r != null && items.Count < 3000) items.Add(new InsGeoItem { Path = path, Kind = kind, Stable = InsStable(doc, r), Obj = f });
                        }
                    }
                    catch (Exception) { c.Errors++; }
                    try
                    {
                        foreach (Edge e in so.Edges)
                        {
                            c.Edges++;
                            Reference r = null;
                            try { r = e.Reference; }
                            catch (Exception) { }
                            if (r == null) c.EdgesNoRef++;
                            else if (items.Count < 3000) items.Add(new InsGeoItem { Path = path, Kind = "Edge", Stable = InsStable(doc, r), Obj = e });
                        }
                    }
                    catch (Exception) { c.Errors++; }
                }
                else if (me != null) c.Meshes++;
                else if (cu != null)
                {
                    Reference r = null;
                    try { r = cu.Reference; }
                    catch (Exception) { }
                    bool isLine = cu is Line;
                    if (isLine) c.Lines++; else c.Curves++;
                    if (r == null) { if (isLine) c.LinesNoRef++; else c.CurvesNoRef++; }
                    else if (items.Count < 3000) items.Add(new InsGeoItem { Path = path, Kind = isLine ? "Line" : cu.GetType().Name, Stable = InsStable(doc, r), Obj = cu });
                }
                else if (pt != null)
                {
                    c.Points++;
                    Reference r = null;
                    try { r = pt.Reference; }
                    catch (Exception) { }
                    if (r == null) c.PointsNoRef++;
                    else if (items.Count < 3000) items.Add(new InsGeoItem { Path = path, Kind = "Point", Stable = InsStable(doc, r), Obj = pt });
                }
                else c.Others.Add(g.GetType().Name);
            }
        }

        private static string InsCountText(InsGeoCount c)
        {
            var p = new List<string>();
            if (c.Solids > 0)
                p.Add("solids " + Inv(c.Solids) + (c.EmptySolids > 0 ? " (" + Inv(c.EmptySolids) + " empty)" : "") + ", faces: planar " + Inv(c.Planar) + " (ref null " + Inv(c.PlanarNoRef)
                      + "), cylindrical " + Inv(c.Cyl) + " (ref null " + Inv(c.CylNoRef) + "), other " + Inv(c.OtherFace) + " (ref null " + Inv(c.OtherFaceNoRef) + "), edges " + Inv(c.Edges)
                      + " (ref null " + Inv(c.EdgesNoRef) + ")");
            if (c.Meshes > 0) p.Add("meshes " + Inv(c.Meshes));
            if (c.Lines > 0) p.Add("lines " + Inv(c.Lines) + " (ref null " + Inv(c.LinesNoRef) + ")");
            if (c.Curves > 0) p.Add("arcs/curves " + Inv(c.Curves) + " (ref null " + Inv(c.CurvesNoRef) + ")");
            if (c.Points > 0) p.Add("points " + Inv(c.Points) + " (ref null " + Inv(c.PointsNoRef) + ")");
            if (c.Instances > 0) p.Add("instances " + Inv(c.Instances));
            if (c.Others.Count > 0) p.Add("other types " + string.Join("/", c.Others));
            if (c.Errors > 0) p.Add("errors " + Inv(c.Errors));
            return p.Count == 0 ? "empty" : string.Join(", ", p);
        }

        private static string InsCountsText(Dictionary<string, InsGeoCount> counts)
        {
            return string.Join("; ", counts.Select(kv => kv.Key + " {" + InsCountText(kv.Value) + "}"));
        }

        /// <summary>One compact line: what the geometry of an element holds as the Locker's own walk (ElementFaces) sees it
        /// (ComputeReferences, no hidden objects; the view's geometry or Fine without a view), counted by type per nesting level
        /// (top level, GetInstanceGeometry, GetSymbolGeometry). Used by the lock when it finds no side / bottom faces.</summary>
        public static string InsGeoSummary(Document doc, Element el, View view)
        {
            try
            {
                Options opt = new Options();
                opt.ComputeReferences = true;
                opt.IncludeNonVisibleObjects = false;
                if (view != null) opt.View = view;
                else
                {
                    try { opt.DetailLevel = ViewDetailLevel.Fine; }
                    catch (Exception) { }
                }
                GeometryElement geo = el.get_Geometry(opt);
                if (geo == null) return "get_Geometry returned null";
                var counts = new Dictionary<string, InsGeoCount>();
                InsWalk(doc, geo, "top", 0, counts, new List<InsGeoItem>());
                return InsCountsText(counts);
            }
            catch (Exception ex) { return "geometry could not be read: " + InsEx(ex); }
        }
    }
}
