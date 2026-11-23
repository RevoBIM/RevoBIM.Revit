using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
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

        /// <summary>A planar face with its origin z and normal z, in model coordinates (Python (face, z, nz)).</summary>
        public class FaceZ
        {
            public PlanarFace Face;
            public double Z, Nz;
            public string Level = "";
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
    }
}
