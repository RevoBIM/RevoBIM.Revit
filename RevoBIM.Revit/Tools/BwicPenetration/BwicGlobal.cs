using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.BwicPenetration
{
    /// <summary>Axis aligned box in host coordinates.</summary>
    public sealed class Box
    {
        public XYZ Min, Max;
        public Box(XYZ min, XYZ max) { Min = min; Max = max; }
    }

    /// <summary>
    /// The wall centre line, addressed by distance along it (station), straight or curved, clamped to its ends.
    /// </summary>
    public sealed class WallFrame
    {
        public readonly Curve Curve;
        private readonly double _start, _end, _span, _length, _baseZ;

        public WallFrame(Curve curve)
        {
            Curve = curve;
            _start = curve.GetEndParameter(0);
            _end = curve.GetEndParameter(1);
            _span = _end - _start;
            _length = curve.Length;
            _baseZ = curve.GetEndPoint(0).Z;
        }

        private double Parameter(double station)
        {
            if (_length < 1e-9) return _start;
            double ratio = station / _length;
            ratio = Math.Min(Math.Max(ratio, 0.0), 1.0);
            return _start + ratio * _span;
        }

        /// <summary>(distance along the wall, distance from the centre line), or null.</summary>
        public double[] Station(XYZ point)
        {
            var flat = new XYZ(point.X, point.Y, _baseZ);
            IntersectionResult result;
            try { result = Curve.Project(flat); }
            catch (Exception) { return null; }
            if (result == null) return null;
            double station = Math.Abs(_span) < 1e-12 ? 0.0 : (result.Parameter - _start) / _span * _length;
            XYZ on = result.XYZPoint;
            double offset = Math.Sqrt((flat.X - on.X) * (flat.X - on.X) + (flat.Y - on.Y) * (flat.Y - on.Y));
            return new[] { station, offset };
        }

        public XYZ PointAt(double station) { return Curve.Evaluate(Parameter(station), false); }

        /// <summary>(point on the centre line, along-wall vector, wall normal).</summary>
        public void FrameAt(double station, out XYZ point, out XYZ along, out XYZ normal)
        {
            double parameter = Parameter(station);
            point = Curve.Evaluate(parameter, false);
            XYZ direction;
            try { direction = Curve.ComputeDerivatives(parameter, false).BasisX; }
            catch (Exception) { direction = Curve.GetEndPoint(1) - Curve.GetEndPoint(0); }
            along = new XYZ(direction.X, direction.Y, 0).Normalize();
            normal = along.CrossProduct(XYZ.BasisZ).Normalize();
        }
    }

    /// <summary>A wall that needs BWICs: the wall, its kind ("blockwork" or "fire") and a description.</summary>
    public sealed class WallToPenetrate
    {
        public Wall Wall;
        public string Kind, Description;
    }

    /// <summary>
    /// The Global Placement engine (port of bwic_global.py, engine version 0.9.0): sweeps the active view and places a BWIC around every
    /// group of pipes, cable trays and conduit passing through a fire rated or blockwork wall in the chosen link. The pyRevit module
    /// kept its settings as module globals set by configure(); they are static fields here.
    /// </summary>
    public static partial class BwicGlobal
    {
        public const string EngineVersion = "0.9.0";

        public static string FamilyName = "BGL_BWIC_Penetration_Horizontal_Rectangular-Dynamic";
        public static string TypeFire = "BWIC - Fire Rated Wall";
        public static string TypeBlockwork = "BWIC - Blockwork";
        public static string BlockworkKeyword = "BLK";
        public static bool BlockworkSharesHole = true;
        public static string LinkNameHint = "-01000";
        public static string PLength = "BGL_Length", PWidth = "BGL_Width", PHeight = "BGL_Height";
        public static double DefaultClearanceMm = 50.0;
        public static string FireParam = "POP_PERF_FireRatingTarget";
        public const string CatPipes = "OST_PipeCurves", CatTrays = "OST_CableTray", CatConduit = "OST_Conduit";
        public static readonly string[] TargetCategories = { CatPipes, CatTrays, CatConduit };
        public static double DefaultGapPipesMm = 200.0, DefaultGapTraysMm = 200.0, DefaultGapConduitMm = 100.0;
        public static bool WidthFromSection = true;
        public static double ServiceReachMm = 1000.0;
        public static double OffWallToleranceMm = 50.0;
        public static double MinCrossingDot = 0.17;
        public static bool SkipExisting = true;
        public static bool MarkClashes = true;
        public static string ClashLineStyle = "BWIC Clash Error";
        public static string ClashGroupName = "BWIC Clash Error";
        public static bool MarkFailures = true;
        public static string FailedLineStyle = "BWIC Failed";
        public static string FailedGroupName = "BWIC Failed";
        public static double ClashMarginMm = 75.0;
        public static double ClashToleranceMm = 1.0;
        public static double DuplicateToleranceMm = 10.0;
        public static bool SuppressWarnings = true;
        public static string ElevationMode = "extents_centre";
        public static string LevelParamName = "BHE_Level";
        public static string LevelParamKeyword = "Level";
        public static string OriginVertical = "centre";
        public static bool DuplicateTypeIfTypeParams = true;
        public static double RoundUpMm = 5.0;
        public static string WorksetKeyword = "BWIC";
        public static string WorksetName = "";
        public static string FamilyWorkset = "";
        public static string FamilyClearance = "";
        public const string ActiveWorkset = "<active>";
        public static string QtyDelimiter = "_";

        private static double Mm(double ft) { return BwicCore.FtToMm(ft); }
        private static double Ft(double mm) { return BwicCore.MmToFt(mm); }

        public static double RoundUpFt(double valueFt, double? stepMm = null)
        {
            double step = stepMm ?? RoundUpMm;
            if (step <= 0) return valueFt;
            return Ft(Math.Ceiling(Mm(valueFt) / step - 1e-9) * step);
        }

        // ---------------------------------------------------------------- geometry helpers

        public static List<XYZ> BboxCorners(Element element)
        {
            BoundingBoxXYZ bb = element.get_BoundingBox(null);
            var pts = new List<XYZ>();
            if (bb == null) return pts;
            Transform tf = bb.Transform;
            foreach (double x in new[] { bb.Min.X, bb.Max.X })
                foreach (double y in new[] { bb.Min.Y, bb.Max.Y })
                    foreach (double z in new[] { bb.Min.Z, bb.Max.Z })
                        pts.Add(tf.OfPoint(new XYZ(x, y, z)));
            return pts;
        }

        public static double ElementCentreZ(Element element)
        {
            try
            {
                var lc = element.Location as LocationCurve;
                if (lc != null) return (lc.Curve.GetEndPoint(0).Z + lc.Curve.GetEndPoint(1).Z) / 2.0;
                var lp = element.Location as LocationPoint;
                if (lp != null) return lp.Point.Z;
            }
            catch (Exception) { }
            BoundingBoxXYZ bb = element.get_BoundingBox(null);
            if (bb == null) return 0.0;
            return (bb.Transform.OfPoint(bb.Min).Z + bb.Transform.OfPoint(bb.Max).Z) / 2.0;
        }

        // ---------------------------------------------------------------- family helpers

        /// <summary>Every type of the BWIC family, keyed by type name.</summary>
        public static Dictionary<string, FamilySymbol> FamilySymbols(Document doc)
        {
            var symbols = new Dictionary<string, FamilySymbol>();
            foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)))
            {
                try
                {
                    var sym = (FamilySymbol)e;
                    if (sym.Family != null && sym.Family.Name == FamilyName) symbols[sym.Name] = sym;
                }
                catch (Exception) { }
            }
            return symbols;
        }

        public static FamilySymbol FindFamilySymbol(Document doc)
        {
            var symbols = new List<FamilySymbol>();
            foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)))
            {
                var sym = (FamilySymbol)e;
                if (sym.Family != null && sym.Family.Name == FamilyName) symbols.Add(sym);
            }
            if (symbols.Count == 0)
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)))
                    if (e.Name == FamilyName) symbols.Add((FamilySymbol)e);
            return symbols.Count == 0 ? null : symbols[0];
        }

        // ---------------------------------------------------------------- levels

        public static List<Level> SortedLevels(Document doc)
        {
            return new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>().OrderBy(l => l.Elevation).ToList();
        }

        /// <summary>Nearest level at or below the elevation; the lowest when none is.</summary>
        public static Level LevelBelow(IList<Level> levels, double elevation)
        {
            if (levels == null || levels.Count == 0) return null;
            Level chosen = levels[0];
            foreach (Level lvl in levels) if (lvl.Elevation <= elevation + 1e-6) chosen = lvl;
            return chosen;
        }

        /// <summary>Two digit code for a level: its own digits when numbered, else its position from the lowest.</summary>
        public static string LevelCode(Level level, IList<Level> levels)
        {
            Match digits = Regex.Match(level.Name, @"\d+");
            if (digits.Success) return (long.Parse(digits.Value) % 100).ToString("00");
            int index = 0;
            for (int i = 0; i < levels.Count; i++) if (levels[i].Id == level.Id) { index = i; break; }
            return (index % 100).ToString("00");
        }

        // ---------------------------------------------------------------- worksets

        /// <summary>The family's own workset; else the one named in Settings; else the first containing the keyword.</summary>
        public static Workset FindBwicWorkset(Document doc)
        {
            if (!doc.IsWorkshared) return null;
            var worksets = new FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset).ToList();
            if (FamilyWorkset.Length > 0 && FamilyWorkset != ActiveWorkset)
            {
                foreach (Workset w in worksets) if (w.Name == FamilyWorkset) return w;
                return null;
            }
            if (WorksetName.Length > 0)
                foreach (Workset w in worksets) if (w.Name == WorksetName) return w;
            var matches = worksets.Where(w => w.Name.ToUpperInvariant().Contains(WorksetKeyword.ToUpperInvariant())).OrderBy(w => w.Name, StringComparer.Ordinal).ToList();
            return matches.Count == 0 ? null : matches[0];
        }

        public static bool AssignWorkset(Element element, Workset workset)
        {
            Parameter param = element.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM);
            if (param == null || param.IsReadOnly) return false;
            param.Set(workset.Id.IntegerValue);
            return true;
        }

        public static string BuildComment(IEnumerable<Element> elements)
        {
            var order = new List<string>();
            var counts = new Dictionary<string, int>();
            foreach (Element el in elements)
            {
                string key = BwicCore.DescribeElement(el);
                if (string.IsNullOrEmpty(key)) continue;
                if (!counts.ContainsKey(key))
                {
                    counts[key] = 0;
                    order.Add(key);
                }
                counts[key]++;
            }
            return string.Join(QtyDelimiter, order.Select(k => counts[k] > 1 ? k + " x" + counts[k] : k));
        }

        // ---------------------------------------------------------------- links

        public sealed class LinkEntry
        {
            public RevitLinkInstance Instance;
            public string Name;
        }

        /// <summary>Every loaded RevitLinkInstance with its display name, sorted by name.</summary>
        public static List<LinkEntry> LoadedLinks(Document doc)
        {
            var found = new List<LinkEntry>();
            foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(RevitLinkInstance)).WhereElementIsNotElementType())
            {
                try
                {
                    var inst = (RevitLinkInstance)e;
                    if (inst.GetLinkDocument() == null) continue;
                    found.Add(new LinkEntry { Instance = inst, Name = inst.Name });
                }
                catch (Exception) { }
            }
            return found.OrderBy(p => p.Name.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        /// <summary>The link instance selected in the model when the window opened.</summary>
        public static RevitLinkInstance PreselectedLink(Autodesk.Revit.UI.UIDocument uidoc)
        {
            try
            {
                Document doc = uidoc.Document;
                foreach (ElementId eid in uidoc.Selection.GetElementIds())
                {
                    var link = doc.GetElement(eid) as RevitLinkInstance;
                    if (link != null && link.GetLinkDocument() != null) return link;
                }
            }
            catch (Exception) { }
            return null;
        }

        // ---------------------------------------------------------------- fire rating

        /// <summary>Readable value of a parameter, or null when it is empty.</summary>
        public static string ParameterValue(Element holder, string name)
        {
            if (holder == null) return null;
            Parameter param;
            try { param = holder.LookupParameter(name); }
            catch (Exception) { return null; }
            if (param == null || !param.HasValue) return null;
            try
            {
                switch (param.StorageType)
                {
                    case StorageType.String:
                    {
                        string text = param.AsString();
                        return string.IsNullOrWhiteSpace(text) ? null : text.Trim();
                    }
                    case StorageType.Integer:
                    {
                        int value = param.AsInteger();
                        return value != 0 ? value.ToString() : null;
                    }
                    case StorageType.Double:
                    {
                        double value = param.AsDouble();
                        if (Math.Abs(value) < 1e-9) return null;
                        string s = param.AsValueString();
                        return string.IsNullOrEmpty(s) ? value.ToString(System.Globalization.CultureInfo.InvariantCulture) : s;
                    }
                    case StorageType.ElementId:
                    {
                        ElementId eid = param.AsElementId();
                        if (eid == null || BwicCore.EidValue(eid) <= 0) return null;
                        Element target = holder.Document.GetElement(eid);
                        return target != null ? target.Name : eid.ToString();
                    }
                }
            }
            catch (Exception) { return null; }
            return null;
        }

        /// <summary>The wall's fire rating target, instance first then type, else null.</summary>
        public static string FireRating(Wall wall)
        {
            string value = ParameterValue(wall, FireParam);
            if (!string.IsNullOrEmpty(value)) return value;
            Element wtype = null;
            try { wtype = wall.Document.GetElement(wall.GetTypeId()); }
            catch (Exception) { }
            return ParameterValue(wtype, FireParam);
        }

        public static string WallTypeName(Wall wall)
        {
            try { return wall.Document.GetElement(wall.GetTypeId()).Name ?? ""; }
            catch (Exception) { return ""; }
        }

        public static string WallFamilyName(Wall wall)
        {
            try { return ((ElementType)wall.Document.GetElement(wall.GetTypeId())).FamilyName ?? ""; }
            catch (Exception) { return ""; }
        }

        public static bool IsBlockwork(Wall wall)
        {
            string keyword = BlockworkKeyword.ToUpperInvariant();
            return WallTypeName(wall).ToUpperInvariant().Contains(keyword) || WallFamilyName(wall).ToUpperInvariant().Contains(keyword);
        }

        /// <summary>Walls needing BWICs: a value in FireParam, or BLK in the type name (both counts as blockwork).</summary>
        public static List<WallToPenetrate> WallsToPenetrate(Document linkDoc)
        {
            var walls = new List<WallToPenetrate>();
            foreach (Element e in new FilteredElementCollector(linkDoc).OfClass(typeof(Wall)).WhereElementIsNotElementType())
            {
                var wall = (Wall)e;
                try { if (!(wall.Location is LocationCurve)) continue; }
                catch (Exception) { continue; }
                string rating;
                bool blockwork;
                try
                {
                    rating = FireRating(wall);
                    blockwork = IsBlockwork(wall);
                }
                catch (Exception) { continue; }
                if (blockwork) walls.Add(new WallToPenetrate { Wall = wall, Kind = "blockwork", Description = WallTypeName(wall) });
                else if (!string.IsNullOrEmpty(rating)) walls.Add(new WallToPenetrate { Wall = wall, Kind = "fire", Description = rating });
            }
            return walls;
        }

        // ---------------------------------------------------------------- boxes and solids

        /// <summary>Axis aligned (min, max) of an element in host coordinates.</summary>
        public static Box WorldBox(Element element, Transform transform = null)
        {
            BoundingBoxXYZ bb = element.get_BoundingBox(null);
            if (bb == null) return null;
            var pts = new List<XYZ>();
            Transform tf = bb.Transform;
            foreach (double x in new[] { bb.Min.X, bb.Max.X })
                foreach (double y in new[] { bb.Min.Y, bb.Max.Y })
                    foreach (double z in new[] { bb.Min.Z, bb.Max.Z })
                    {
                        XYZ pt = tf.OfPoint(new XYZ(x, y, z));
                        if (transform != null) pt = transform.OfPoint(pt);
                        pts.Add(pt);
                    }
            return new Box(new XYZ(pts.Min(p => p.X), pts.Min(p => p.Y), pts.Min(p => p.Z)),
                           new XYZ(pts.Max(p => p.X), pts.Max(p => p.Y), pts.Max(p => p.Z)));
        }

        public static bool BoxesOverlap(Box a, Box b, double tol = 1e-6)
        {
            if (a == null || b == null) return false;
            return a.Min.X < b.Max.X - tol && b.Min.X < a.Max.X - tol
                   && a.Min.Y < b.Max.Y - tol && b.Min.Y < a.Max.Y - tol
                   && a.Min.Z < b.Max.Z - tol && b.Min.Z < a.Max.Z - tol;
        }

        public static Outline OutlineFromBox(Box box, double pad = 0.0)
        {
            return new Outline(new XYZ(box.Min.X - pad, box.Min.Y - pad, box.Min.Z - pad), new XYZ(box.Max.X + pad, box.Max.Y + pad, box.Max.Z + pad));
        }

        private static void WalkSolids(GeometryElement geometry, List<Solid> solids)
        {
            foreach (GeometryObject item in geometry)
            {
                var solid = item as Solid;
                var inst = item as GeometryInstance;
                if (solid != null)
                {
                    try { if (solid.Volume > 1e-9) solids.Add(solid); }
                    catch (Exception) { }
                }
                else if (inst != null) WalkSolids(inst.GetInstanceGeometry(), solids);
            }
        }

        /// <summary>One solid for the wall, in host coordinates.</summary>
        public static Solid WallSolid(Wall wall, Transform transform)
        {
            var options = new Options { DetailLevel = ViewDetailLevel.Medium, ComputeReferences = false, IncludeNonVisibleObjects = false };
            var solids = new List<Solid>();
            try { WalkSolids(wall.get_Geometry(options), solids); }
            catch (Exception) { return null; }
            if (solids.Count == 0) return null;
            Solid solid = solids[0];
            for (int i = 1; i < solids.Count; i++)
            {
                try { solid = BooleanOperationsUtils.ExecuteBooleanOperation(solid, solids[i], BooleanOperationsType.Union); }
                catch (Exception) { if (solids[i].Volume > solid.Volume) solid = solids[i]; }
            }
            try { return SolidUtils.CreateTransformed(solid, transform ?? Transform.Identity); }
            catch (Exception) { return null; }
        }

        public static BuiltInCategory Bic(string name) { return (BuiltInCategory)Enum.Parse(typeof(BuiltInCategory), name); }

        public static long BicId(string name) { return (long)Bic(name); }

        public static long? CategoryId(Element element)
        {
            try { return BwicCore.EidValue(element.Category.Id); }
            catch (Exception) { return null; }
        }

        /// <summary>Every pipe, cable tray and conduit visible in the view (a plan's view range scopes it to the floor).</summary>
        public static List<Element> ServicesInView(Document doc, View view)
        {
            var categories = new List<BuiltInCategory>(TargetCategories.Select(Bic));
            try
            {
                return new FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()
                    .WherePasses(new ElementMulticategoryFilter(categories)).ToList();
            }
            catch (Exception) { return new List<Element>(); }
        }

        /// <summary>One box round everything given, in host coordinates, or null.</summary>
        public static Box CombinedBox(IEnumerable<Element> elements, double padFt = 0.0)
        {
            var boxes = elements.Select(e => WorldBox(e)).Where(b => b != null).ToList();
            if (boxes.Count == 0) return null;
            return new Box(new XYZ(boxes.Min(b => b.Min.X) - padFt, boxes.Min(b => b.Min.Y) - padFt, boxes.Min(b => b.Min.Z) - padFt),
                           new XYZ(boxes.Max(b => b.Max.X) + padFt, boxes.Max(b => b.Max.Y) + padFt, boxes.Max(b => b.Max.Z) + padFt));
        }

        /// <summary>True when two boxes meet or overlap. Touching counts.</summary>
        public static bool BoxesTouch(Box a, Box b)
        {
            if (a == null || b == null) return true;
            return !(a.Max.X < b.Min.X || b.Max.X < a.Min.X || a.Max.Y < b.Min.Y || b.Max.Y < a.Min.Y || a.Max.Z < b.Min.Z || b.Max.Z < a.Min.Z);
        }

        /// <summary>Crop box or section box of the view, in host coordinates, or null.</summary>
        public static Outline ViewOutline(View view)
        {
            bool flat = !(view is View3D);
            try
            {
                BoundingBoxXYZ box;
                var v3 = view as View3D;
                if (v3 != null && v3.IsSectionBoxActive)
                {
                    box = v3.GetSectionBox();
                    flat = false;
                }
                else if (view.CropBoxActive) box = view.CropBox;
                else return null;
                Transform tf = box.Transform;
                var pts = new List<XYZ>();
                foreach (double x in new[] { box.Min.X, box.Max.X })
                    foreach (double y in new[] { box.Min.Y, box.Max.Y })
                        foreach (double z in new[] { box.Min.Z, box.Max.Z })
                            pts.Add(tf.OfPoint(new XYZ(x, y, z)));
                double zMin = flat ? -1.0e6 : pts.Min(p => p.Z);
                double zMax = flat ? 1.0e6 : pts.Max(p => p.Z);
                return new Outline(new XYZ(pts.Min(p => p.X), pts.Min(p => p.Y), zMin), new XYZ(pts.Max(p => p.X), pts.Max(p => p.Y), zMax));
            }
            catch (Exception) { return null; }
        }

        public static bool OutlineHits(Outline outline, Box box, double pad = 0.0)
        {
            if (outline == null || box == null) return true;
            return !(box.Max.X < outline.MinimumPoint.X - pad || box.Min.X > outline.MaximumPoint.X + pad
                     || box.Max.Y < outline.MinimumPoint.Y - pad || box.Min.Y > outline.MaximumPoint.Y + pad
                     || box.Max.Z < outline.MinimumPoint.Z - pad || box.Min.Z > outline.MaximumPoint.Z + pad);
        }

        // ---------------------------------------------------------------- finding the services that pass through a wall

        public static XYZ ElementDirection(Element element)
        {
            try
            {
                var lc = element.Location as LocationCurve;
                if (lc != null)
                {
                    XYZ vec = lc.Curve.GetEndPoint(1) - lc.Curve.GetEndPoint(0);
                    if (vec.GetLength() > 1e-9) return vec.Normalize();
                }
            }
            catch (Exception) { }
            return null;
        }

        public static XYZ BoxCentre(Box box)
        {
            return new XYZ((box.Min.X + box.Max.X) / 2.0, (box.Min.Y + box.Max.Y) / 2.0, (box.Min.Z + box.Max.Z) / 2.0);
        }

        /// <summary>True when the element runs through the wall rather than along it (normal taken where it meets the wall).</summary>
        public static bool CrossesWall(Element element, WallFrame frame)
        {
            XYZ direction = ElementDirection(element);
            if (direction == null) return true;
            Box box = WorldBox(element);
            if (box == null) return true;
            double[] station = frame.Station(BoxCentre(box));
            if (station == null) return true;
            XYZ point, along, normal;
            frame.FrameAt(station[0], out point, out along, out normal);
            return Math.Abs(direction.DotProduct(normal)) >= MinCrossingDot;
        }

        /// <summary>Pipes, cable trays and conduit in the view that pass through the wall solid.</summary>
        public static List<Element> ServicesThroughWall(Document doc, View view, Solid solid, Box wallBox, WallFrame frame)
        {
            var categories = new List<BuiltInCategory>(TargetCategories.Select(Bic));
            List<Element> found;
            try
            {
                found = new FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()
                    .WherePasses(new ElementMulticategoryFilter(categories))
                    .WherePasses(new BoundingBoxIntersectsFilter(OutlineFromBox(wallBox, Ft(10.0))))
                    .WherePasses(new ElementIntersectsSolidFilter(solid)).ToList();
            }
            catch (Exception) { return new List<Element>(); }
            return found.Where(el => CrossesWall(el, frame)).ToList();
        }

        // ---------------------------------------------------------------- the bit of a service that is actually inside the wall

        public static List<Solid> ElementSolids(Element element)
        {
            var options = new Options { DetailLevel = ViewDetailLevel.Medium, ComputeReferences = false, IncludeNonVisibleObjects = false };
            var solids = new List<Solid>();
            try { WalkSolids(element.get_Geometry(options), solids); }
            catch (Exception) { return new List<Solid>(); }
            return solids;
        }

        public static List<XYZ> SolidCorners(Solid solid)
        {
            BoundingBoxXYZ bb;
            try { bb = solid.GetBoundingBox(); }
            catch (Exception) { return new List<XYZ>(); }
            Transform tf = bb.Transform;
            var pts = new List<XYZ>();
            foreach (double x in new[] { bb.Min.X, bb.Max.X })
                foreach (double y in new[] { bb.Min.Y, bb.Max.Y })
                    foreach (double z in new[] { bb.Min.Z, bb.Max.Z })
                        pts.Add(tf.OfPoint(new XYZ(x, y, z)));
            return pts;
        }

        /// <summary>Half width / half height of a linear element, per world axis.</summary>
        public static double[] CrossSectionHalf(Element element, XYZ direction)
        {
            BoundingBoxXYZ bb = element.get_BoundingBox(null);
            if (bb == null) return new[] { Ft(50.0), Ft(50.0), Ft(50.0) };
            Transform tf = bb.Transform;
            XYZ lo = tf.OfPoint(bb.Min), hi = tf.OfPoint(bb.Max);
            double[] spans = { Math.Abs(hi.X - lo.X), Math.Abs(hi.Y - lo.Y), Math.Abs(hi.Z - lo.Z) };
            int axis = 0;
            if (direction != null)
            {
                double[] weights = { Math.Abs(direction.X), Math.Abs(direction.Y), Math.Abs(direction.Z) };
                axis = Array.IndexOf(weights, weights.Max());
            }
            double[] halves = spans.Select(s => s / 2.0).ToArray();
            halves[axis] = halves.Min();
            return halves;
        }

        /// <summary>Corners of the element where its centre line passes into the solid.</summary>
        public static List<XYZ> SegmentCorners(Element element, Solid solid)
        {
            Curve curve = null;
            try
            {
                var lc = element.Location as LocationCurve;
                if (lc != null) curve = lc.Curve;
            }
            catch (Exception) { }
            if (curve == null) return new List<XYZ>();
            SolidCurveIntersection result;
            try { result = solid.IntersectWithCurve(curve, new SolidCurveIntersectionOptions()); }
            catch (Exception) { return new List<XYZ>(); }
            if (result == null || result.SegmentCount == 0) return new List<XYZ>();
            XYZ direction = ElementDirection(element);
            double[] h = CrossSectionHalf(element, direction);
            var corners = new List<XYZ>();
            for (int index = 0; index < result.SegmentCount; index++)
            {
                Curve segment = result.GetCurveSegment(index);
                foreach (XYZ end in new[] { segment.GetEndPoint(0), segment.GetEndPoint(1) })
                    foreach (double sx in new[] { -h[0], h[0] })
                        foreach (double sy in new[] { -h[1], h[1] })
                            foreach (double sz in new[] { -h[2], h[2] })
                                corners.Add(new XYZ(end.X + sx, end.Y + sy, end.Z + sz));
            }
            return corners;
        }

        /// <summary>The element's footprint inside the wall: boolean intersection first, centre line intersection as the fallback.</summary>
        public static List<XYZ> CrossingCorners(Element element, Solid solid)
        {
            var corners = new List<XYZ>();
            foreach (Solid piece in ElementSolids(element))
            {
                Solid cut;
                try { cut = BooleanOperationsUtils.ExecuteBooleanOperation(piece, solid, BooleanOperationsType.Intersect); }
                catch (Exception) { continue; }
                if (cut == null) continue;
                try { if (cut.Volume < 1e-9) continue; }
                catch (Exception) { continue; }
                corners.AddRange(SolidCorners(cut));
            }
            if (corners.Count > 0) return corners;
            corners = SegmentCorners(element, solid);
            if (corners.Count > 0) return corners;
            return new List<XYZ>();
        }

        public static Box CornersBox(IList<XYZ> corners)
        {
            if (corners == null || corners.Count == 0) return null;
            return new Box(new XYZ(corners.Min(p => p.X), corners.Min(p => p.Y), corners.Min(p => p.Z)),
                           new XYZ(corners.Max(p => p.X), corners.Max(p => p.Y), corners.Max(p => p.Z)));
        }

        // ---------------------------------------------------------------- grouping

        public static double? BuiltinLength(Element element, string[] names)
        {
            foreach (string name in names)
            {
                BuiltInParameter bip;
                if (!Enum.TryParse(name, out bip)) continue;
                Parameter parameter;
                try { parameter = element.get_Parameter(bip); }
                catch (Exception) { continue; }
                if (parameter == null || !parameter.HasValue) continue;
                double value;
                try { value = parameter.AsDouble(); }
                catch (Exception) { continue; }
                if (value > 1e-9) return value;
            }
            return null;
        }

        /// <summary>How wide the service is across its own axis (outside diameter for a pipe or conduit, tray width), or null.</summary>
        public static double? SectionWidth(Element element)
        {
            long? category = CategoryId(element);
            if (category == BicId(CatPipes))
            {
                double? width = BuiltinLength(element, new[] { "RBS_PIPE_OUTER_DIAMETER", "RBS_PIPE_OUTER_DIAM_PARAM", "RBS_PIPE_DIAMETER_PARAM" });
                if (width != null && width.Value != 0) return width;
                try { if (((MEPCurve)element).Diameter > 1e-9) return ((MEPCurve)element).Diameter; }
                catch (Exception) { }
            }
            else if (category == BicId(CatTrays))
            {
                double? width = BuiltinLength(element, new[] { "RBS_CABLETRAY_WIDTH_PARAM", "RBS_CURVE_WIDTH_PARAM" });
                if (width != null && width.Value != 0) return width;
                try { if (((MEPCurve)element).Width > 1e-9) return ((MEPCurve)element).Width; }
                catch (Exception) { }
            }
            else if (category == BicId(CatConduit))
            {
                double? width = BuiltinLength(element, new[] { "RBS_CONDUIT_OUTER_DIAM_PARAM", "RBS_CONDUIT_DIAMETER_PARAM" });
                if (width != null && width.Value != 0) return width;
                try { if (((MEPCurve)element).Diameter > 1e-9) return ((MEPCurve)element).Diameter; }
                catch (Exception) { }
            }
            return null;
        }

        /// <summary>(uMin, uMax, zMin, zMax) along the wall, or null. Given a width, the along-wall extent is that width centred on the crossing.</summary>
        public static double[] WallExtents(IList<XYZ> corners, WallFrame frame, double? width = null)
        {
            if (corners == null || corners.Count == 0) return null;
            var stations = new List<double>();
            foreach (XYZ point in corners)
            {
                double[] station = frame.Station(point);
                if (station == null) return null;
                stations.Add(station[0]);
            }
            double uMin = stations.Min(), uMax = stations.Max();
            if (width != null && width.Value > 1e-9)
            {
                double centre = (uMin + uMax) / 2.0;
                uMin = centre - width.Value / 2.0;
                uMax = centre + width.Value / 2.0;
            }
            return new[] { uMin, uMax, corners.Min(p => p.Z), corners.Max(p => p.Z) };
        }

        public static double[] UnionExtents(IEnumerable<double[]> spans)
        {
            var list = spans.Where(s => s != null).ToList();
            if (list.Count == 0) return null;
            return new[] { list.Min(s => s[0]), list.Max(s => s[1]), list.Min(s => s[2]), list.Max(s => s[3]) };
        }

        /// <summary>Clear distance between two extents in the wall plane, 0 if they touch.</summary>
        public static double GapBetween(double[] a, double[] b)
        {
            double du = Math.Max(0.0, Math.Max(a[0] - b[1], b[0] - a[1]));
            double dz = Math.Max(0.0, Math.Max(a[2] - b[3], b[2] - a[3]));
            return Math.Sqrt(du * du + dz * dz);
        }
    }
}
