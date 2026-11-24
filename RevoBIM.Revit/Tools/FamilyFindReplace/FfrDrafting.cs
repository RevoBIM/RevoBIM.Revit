using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.FamilyFindReplace
{
    /// <summary>
    /// Drafting views: import symbols (AutoCAD blocks) become detail items. Find lists imports, Replace with lists
    /// detail items, and each detail item lands on its block's insertion point, turned to the block's rotation.
    /// </summary>
    public static partial class FfrCore
    {
        /// <summary>What the type list shows for an import, which has no family/type split.</summary>
        public const string ImportTypeLabel = "Import symbol";

        /// <summary>Points gathered from one import's linework before the extents are taken; keeps a pathological block from stalling the run.</summary>
        private const int ImportPointCap = 20000;

        /// <summary>How far off a detail item may land before the verify pass moves it again (0.5mm).</summary>
        private static readonly double CentreTolFt = 0.5 / MmPerFt;

        /// <summary>How far a placed detail item may turn from the block before it is put right.</summary>
        private static readonly double AngleTol = 0.01 * Math.PI / 180.0;

        public static bool IsDraftingView(View view)
        {
            try
            {
                return view != null && view.ViewType == ViewType.DraftingView;
            }
            catch (Exception)
            {
                return false;
            }
        }

        private static bool IsDetailItem(Element element)
        {
            try
            {
                return element != null && element.Category != null && Eid(element.Category.Id) == (long)BuiltInCategory.OST_DetailComponents;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Pick filter for the Find side in a drafting view: imports only.</summary>
        public sealed class ImportPickFilter : ISelectionFilter
        {
            public bool AllowElement(Element element) { return element is ImportInstance; }
            public bool AllowReference(Reference reference, XYZ position) { return false; }
        }

        /// <summary>Pick filter for the Replace side in a drafting view: detail items.</summary>
        public sealed class DetailItemPickFilter : ISelectionFilter
        {
            public bool AllowElement(Element element) { return element is FamilyInstance && IsDetailItem(element); }
            public bool AllowReference(Reference reference, XYZ position) { return false; }
        }

        /// <summary>The view an element is drawn in, or null for a model element.</summary>
        public static View OwnerView(Document doc, Element element)
        {
            try
            {
                ElementId viewId = element.OwnerViewId;
                if (viewId == null || Eid(viewId) <= 0) return null;
                return doc.GetElement(viewId) as View;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>The block name an import symbol goes by: the type's name first (after a partial explode, the AutoCAD block name), then the instance's.</summary>
        public static string ImportName(Document doc, Element element)
        {
            var names = new List<string>();
            if (doc != null)
            {
                try
                {
                    names.Add(Name(doc.GetElement(element.GetTypeId())));
                }
                catch (Exception)
                {
                }
            }
            names.Add(Name(element));
            foreach (string name in names)
                if (!string.IsNullOrEmpty(name)) return name;
            return "Unnamed import";
        }

        private static string ImportCategory(Element element)
        {
            try
            {
                if (element.Category != null && !string.IsNullOrEmpty(element.Category.Name)) return element.Category.Name;
            }
            catch (Exception)
            {
            }
            return "Imports";
        }

        /// <summary>The list record for an import, shared by the index and the picker, so a picked import finds its own row.</summary>
        public static TypeRecord ImportRecord(Document doc, Element element, int count)
        {
            return new TypeRecord(element.GetTypeId(), ImportTypeLabel, ImportName(doc, element), ImportCategory(element), "Import", count)
            {
                IsImport = true,
            };
        }

        /// <summary>
        /// Every import that sits in a view, keyed category &gt; block name. View-specific imports only: a detail
        /// item belongs to a view, so an import placed as a model element has nowhere for its replacement to go.
        /// </summary>
        public static Dictionary<string, Dictionary<string, List<TypeRecord>>> BuildImportIndex(Document doc)
        {
            var index = new Dictionary<string, Dictionary<string, List<TypeRecord>>>();
            var seen = new Dictionary<long, TypeRecord>();
            FilteredElementCollector collector;
            try
            {
                collector = new FilteredElementCollector(doc).OfClass(typeof(ImportInstance)).WhereElementIsNotElementType();
            }
            catch (Exception)
            {
                return index;
            }
            foreach (Element element in collector)
            {
                long key;
                try
                {
                    if (OwnerView(doc, element) == null) continue;
                    key = Eid(element.GetTypeId());
                }
                catch (Exception)
                {
                    continue;
                }
                TypeRecord record;
                if (!seen.TryGetValue(key, out record))
                {
                    record = ImportRecord(doc, element, 0);
                    seen[key] = record;
                    AddRecord(index, record);
                }
                record.Count++;
            }
            return index;
        }

        /// <summary>Every detail item type in the project, keyed category &gt; family.</summary>
        public static Dictionary<string, Dictionary<string, List<TypeRecord>>> BuildDetailIndex(Document doc)
        {
            var index = new Dictionary<string, Dictionary<string, List<TypeRecord>>>();
            Dictionary<long, int> counts = InstanceCounts(doc);
            try
            {
                foreach (Element element in new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_DetailComponents))
                {
                    try
                    {
                        var symbol = element as FamilySymbol;
                        if (symbol == null || !IsDetailItem(symbol) || symbol.Family == null) continue;
                        int count;
                        counts.TryGetValue(Eid(symbol.Id), out count);
                        AddRecord(index, new TypeRecord(symbol.Id, Name(symbol), Name(symbol.Family), symbol.Category.Name, PlacementName(symbol), count));
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            catch (Exception)
            {
                return index;
            }
            SortRecords(index);
            return index;
        }

        /// <summary>Every import of the given type inside the chosen scope.</summary>
        public static List<Element> CollectImports(Document doc, UIDocument uidoc, ElementId typeId, string scope)
        {
            var found = new List<Element>();
            if (typeId == null) return found;
            long wanted = Eid(typeId);
            Func<Element, bool> matches = element =>
            {
                try
                {
                    return element is ImportInstance && Eid(element.GetTypeId()) == wanted;
                }
                catch (Exception)
                {
                    return false;
                }
            };
            try
            {
                if (scope == ScopeSelection)
                {
                    foreach (ElementId id in uidoc.Selection.GetElementIds())
                    {
                        Element element = doc.GetElement(id);
                        if (matches(element)) found.Add(element);
                    }
                    return found;
                }
                FilteredElementCollector collector = scope == ScopeView && uidoc.ActiveView != null
                    ? new FilteredElementCollector(doc, uidoc.ActiveView.Id)
                    : new FilteredElementCollector(doc);
                found.AddRange(collector.OfClass(typeof(ImportInstance)).Where(matches));
                return found;
            }
            catch (Exception)
            {
                return new List<Element>();
            }
        }

        // ---- geometry helpers -------------------------------------------------------------------------

        /// <summary>(right, up, normal) of the view the element is drawn in.</summary>
        private static void ViewAxes(View view, out XYZ right, out XYZ up, out XYZ normal)
        {
            try
            {
                right = view.RightDirection;
                up = view.UpDirection;
                normal = view.ViewDirection;
                if (right != null && up != null && normal != null) return;
            }
            catch (Exception)
            {
            }
            right = XYZ.BasisX;
            up = XYZ.BasisY;
            normal = XYZ.BasisZ;
        }

        private static Transform InstanceTransform(Element element)
        {
            var instance = element as Instance;
            if (instance == null) return null;
            try
            {
                Transform transform = instance.GetTransform();
                if (transform != null) return transform;
            }
            catch (Exception)
            {
            }
            try
            {
                return instance.GetTotalTransform();
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>Every drawn point in a piece of geometry, nested blocks included.</summary>
        private static void CollectPoints(IEnumerable<GeometryObject> items, List<XYZ> output, int depth)
        {
            if (depth > 8 || output.Count >= ImportPointCap || items == null) return;
            foreach (GeometryObject item in items)
            {
                if (output.Count >= ImportPointCap) return;
                var instance = item as GeometryInstance;
                if (instance != null)
                {
                    GeometryElement nested = null;
                    try
                    {
                        nested = instance.GetInstanceGeometry();
                    }
                    catch (Exception)
                    {
                    }
                    if (nested != null) CollectPoints(nested, output, depth + 1);
                    continue;
                }
                try
                {
                    var curve = item as Curve;
                    if (curve != null)
                    {
                        output.AddRange(curve.Tessellate());
                        continue;
                    }
                    var polyline = item as PolyLine;
                    if (polyline != null)
                    {
                        output.AddRange(polyline.GetCoordinates());
                        continue;
                    }
                    var solid = item as Solid;
                    if (solid != null)
                    {
                        foreach (Edge edge in solid.Edges) output.AddRange(edge.Tessellate());
                        continue;
                    }
                    var mesh = item as Mesh;
                    if (mesh != null)
                    {
                        output.AddRange(mesh.Vertices);
                        continue;
                    }
                    var point = item as Autodesk.Revit.DB.Point;
                    if (point != null) output.Add(point.Coord);
                }
                catch (Exception)
                {
                }
            }
        }

        /// <summary>
        /// Centre of the extents, measured in a local frame when one is given. Measured in the element's own
        /// axes, a rotated block's centre is the centre of the block as drawn; in world axes it would be the
        /// centre of the box around the rotated block.
        /// </summary>
        private static XYZ ExtentsCentre(List<XYZ> points, Transform toLocal, Transform toWorld)
        {
            double[] lo = null, hi = null;
            foreach (XYZ point in points)
            {
                double[] values;
                try
                {
                    XYZ q = toLocal != null ? toLocal.OfPoint(point) : point;
                    values = new[] { q.X, q.Y, q.Z };
                }
                catch (Exception)
                {
                    continue;
                }
                if (lo == null)
                {
                    lo = (double[])values.Clone();
                    hi = (double[])values.Clone();
                    continue;
                }
                for (int axis = 0; axis < 3; axis++)
                {
                    if (values[axis] < lo[axis]) lo[axis] = values[axis];
                    if (values[axis] > hi[axis]) hi[axis] = values[axis];
                }
            }
            if (lo == null) return null;
            var middle = new XYZ((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, (lo[2] + hi[2]) * 0.5);
            if (toWorld == null) return middle;
            try
            {
                return toWorld.OfPoint(middle);
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>
        /// (centre, how it was found) for an import or a detail item, tried in order of how true an answer each
        /// gives: drawn linework in the element's own axes, in world axes, the view bounding box, and finally
        /// the insertion point.
        /// </summary>
        private static XYZ OwnFrameCentre(Element element, View view, out string route)
        {
            Transform transform = InstanceTransform(element);
            var points = new List<XYZ>();
            try
            {
                var options = new Options();
                if (view != null)
                {
                    try
                    {
                        options.View = view;
                    }
                    catch (Exception)
                    {
                    }
                }
                GeometryElement geometry = element.get_Geometry(options);
                if (geometry != null) CollectPoints(geometry, points, 0);
            }
            catch (Exception)
            {
                points = new List<XYZ>();
            }

            if (points.Count > 0 && transform != null)
            {
                try
                {
                    XYZ centre = ExtentsCentre(points, transform.Inverse, transform);
                    if (centre != null)
                    {
                        route = "own extents";
                        return centre;
                    }
                }
                catch (Exception)
                {
                }
            }
            if (points.Count > 0)
            {
                XYZ centre = ExtentsCentre(points, null, null);
                if (centre != null)
                {
                    route = "drawn extents";
                    return centre;
                }
            }
            try
            {
                BoundingBoxXYZ box = element.get_BoundingBox(view);
                if (box != null)
                {
                    route = "bounding box";
                    return BoxCentre(box);
                }
            }
            catch (Exception)
            {
            }
            if (transform != null)
            {
                route = "insertion point";
                return transform.Origin;
            }
            XYZ at = InstancePoint(element);
            if (at != null)
            {
                route = "insertion point";
                return at;
            }
            route = "";
            return null;
        }

        /// <summary>Middle of a bounding box in model coordinates; Min and Max are in the box's own Transform frame.</summary>
        private static XYZ BoxCentre(BoundingBoxXYZ box)
        {
            XYZ middle = (box.Min + box.Max) * 0.5;
            try
            {
                if (box.Transform != null) return box.Transform.OfPoint(middle);
            }
            catch (Exception)
            {
            }
            return middle;
        }

        /// <summary>Turn a vector by angle about the view normal, in the view's terms.</summary>
        private static XYZ RotateInPlane(XYZ vector, double angle, XYZ right, XYZ up)
        {
            double x = vector.DotProduct(right);
            double y = vector.DotProduct(up);
            XYZ depth = vector - right * x - up * y;
            double c = Math.Cos(angle), s = Math.Sin(angle);
            return right * (x * c - y * s) + up * (x * s + y * c) + depth;
        }

        /// <summary>Mirror a vector across a plane through the origin.</summary>
        private static XYZ ReflectAcross(XYZ vector, XYZ planeNormal)
        {
            return vector - planeNormal * (2.0 * vector.DotProduct(planeNormal));
        }

        /// <summary>Where a centre measured with the element turned square really is: turned forward by +angle about the pivot.</summary>
        private static XYZ CentreFromUnrotated(XYZ squareCentre, XYZ pivot, double angle, XYZ right, XYZ up)
        {
            return pivot + RotateInPlane(squareCentre - pivot, angle, right, up);
        }

        /// <summary>
        /// Where a detail item's middle sits from its insertion point once turned. Turning comes first and
        /// mirroring second, because that is the order the placement does them in.
        /// </summary>
        private static XYZ PlacedOffset(XYZ offset, double angle, XYZ mirrorNormal, XYZ right, XYZ up)
        {
            XYZ moved = RotateInPlane(offset, angle, right, up);
            return mirrorNormal != null ? ReflectAcross(moved, mirrorNormal) : moved;
        }

        /// <summary>The point an element turns about: its insertion point.</summary>
        private static XYZ ElementPivot(Element element)
        {
            Transform transform = InstanceTransform(element);
            if (transform != null) return transform.Origin;
            return InstancePoint(element);
        }

        /// <summary>
        /// Bounding box middle with the element turned square, then turned back. Done in a sub-transaction that
        /// is always rolled back, so the model is never left changed. Needs a transaction to be open.
        /// </summary>
        private static XYZ SquareBoxCentre(Document doc, Element element, View view, XYZ pivot, double angle, XYZ normal)
        {
            if (Math.Abs(angle) < 1.0e-9)
            {
                try
                {
                    BoundingBoxXYZ box = element.get_BoundingBox(view);
                    return box != null ? BoxCentre(box) : null;
                }
                catch (Exception)
                {
                    return null;
                }
            }
            try
            {
                if (!doc.IsModifiable) return null;
            }
            catch (Exception)
            {
                return null;
            }
            var sub = new SubTransaction(doc);
            try
            {
                sub.Start();
            }
            catch (Exception)
            {
                return null;
            }
            XYZ found = null;
            try
            {
                try
                {
                    if (element.Pinned) element.Pinned = false;
                }
                catch (Exception)
                {
                }
                Line axis = Line.CreateBound(pivot, pivot + normal);
                ElementTransformUtils.RotateElement(doc, element.Id, axis, -angle);
                doc.Regenerate();
                BoundingBoxXYZ box = element.get_BoundingBox(view);
                if (box != null) found = BoxCentre(box);
            }
            catch (Exception)
            {
                found = null;
            }
            finally
            {
                try
                {
                    sub.RollBack();
                }
                catch (Exception)
                {
                }
            }
            return found;
        }

        /// <summary>
        /// (centre, route): the middle of an element as drawn, in its own axes. First choice is Revit's own
        /// bounding box taken with the element turned square to the view; falling back, the drawn linework in
        /// the element's own axes, then the box as it stands, then the insertion point.
        /// </summary>
        private static XYZ MeasureCentre(Document doc, Element element, View view, Transform transform, out string route)
        {
            XYZ right, up, normal;
            ViewAxes(view, out right, out up, out normal);
            if (transform == null) transform = InstanceTransform(element);
            double angle = 0.0;
            XYZ pivot = null;
            if (transform != null)
            {
                try
                {
                    angle = PlaneAngle(transform.BasisX, right, up);
                    pivot = transform.Origin;
                }
                catch (Exception)
                {
                    angle = 0.0;
                }
            }
            if (pivot == null) pivot = ElementPivot(element);
            if (pivot != null)
            {
                XYZ square = SquareBoxCentre(doc, element, view, pivot, angle, normal);
                if (square != null)
                {
                    route = "square box";
                    return CentreFromUnrotated(square, pivot, angle, right, up);
                }
            }
            return OwnFrameCentre(element, view, out route);
        }

        /// <summary>Where an import sits and which way round, in its view's terms.</summary>
        public sealed class ImportFrame
        {
            public XYZ Centre;                  // where the detail item is lined up to
            public string Route = "";           // how that point was found
            public XYZ Origin;                  // the block's insertion (base) point
            public string OriginRoute = "";     // which transform it came from
            public Transform Transform;         // the block's placement transform
            public List<KeyValuePair<string, Transform>> Candidates = new List<KeyValuePair<string, Transform>>();
            public double Angle;                // radians, from the view's right, about its normal
            public bool Mirrored;
            public XYZ XDir;                    // the import's own X, flattened into the view
        }

        /// <summary>Angle of a direction in the view plane, measured from the view's right.</summary>
        private static double PlaneAngle(XYZ basisX, XYZ right, XYZ up)
        {
            try
            {
                double x = basisX.DotProduct(right);
                double y = basisX.DotProduct(up);
                if (Math.Abs(x) < 1.0e-12 && Math.Abs(y) < 1.0e-12) return 0.0;
                return Math.Atan2(y, x);
            }
            catch (Exception)
            {
                return 0.0;
            }
        }

        /// <summary>
        /// True when the element's axes run the other way round to the view's. Judged in the view plane rather
        /// than from the transform's determinant, so an import merely flipped through the sheet does not read as mirrored.
        /// </summary>
        private static bool IsMirroredInPlane(XYZ basisX, XYZ basisY, XYZ right, XYZ up)
        {
            try
            {
                double ax = basisX.DotProduct(right), ay = basisX.DotProduct(up);
                double bx = basisY.DotProduct(right), by = basisY.DotProduct(up);
                return (ax * by - ay * bx) < 0.0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// The placement the block's linework is drawn by: the Transform of the one GeometryInstance the import
        /// holds (origin = the AutoCAD base point, axes = the block's rotation). Where the import wraps the block
        /// in an outer instance holding nothing else, the wrapper is stepped through and the transforms combined.
        /// Null when the import is not exactly one block: a whole DWG left unexploded has no single insertion point.
        /// </summary>
        private static Transform BlockTransform(Element element, View view, out int depth)
        {
            depth = 0;
            GeometryElement geometry;
            try
            {
                var options = new Options();
                if (view != null)
                {
                    try
                    {
                        options.View = view;
                    }
                    catch (Exception)
                    {
                    }
                }
                geometry = element.get_Geometry(options);
            }
            catch (Exception)
            {
                return null;
            }
            if (geometry == null) return null;
            List<GeometryInstance> blocks;
            try
            {
                blocks = geometry.OfType<GeometryInstance>().ToList();
            }
            catch (Exception)
            {
                return null;
            }
            if (blocks.Count != 1) return null;
            GeometryInstance current = blocks[0];
            Transform transform;
            try
            {
                transform = current.Transform;
            }
            catch (Exception)
            {
                return null;
            }
            while (depth < 6)
            {
                List<GeometryObject> inner;
                try
                {
                    inner = current.GetSymbolGeometry().ToList();
                }
                catch (Exception)
                {
                    break;
                }
                if (inner.Count != 1 || !(inner[0] is GeometryInstance)) break;
                var next = (GeometryInstance)inner[0];
                try
                {
                    transform = transform.Multiply(next.Transform);
                }
                catch (Exception)
                {
                    break;
                }
                current = next;
                depth++;
            }
            return transform;
        }

        /// <summary>Every route to the import's placement, best first; all of them go to the debug log so a wrong first choice is visible.</summary>
        private static List<KeyValuePair<string, Transform>> InsertionCandidates(Element element, View view)
        {
            var found = new List<KeyValuePair<string, Transform>>();
            int depth;
            Transform block = BlockTransform(element, view, out depth);
            found.Add(new KeyValuePair<string, Transform>(depth == 0 ? "block insertion" : "block insertion, " + depth + " level(s) in", block));
            var instance = element as Instance;
            Transform total = null, local = null;
            try
            {
                if (instance != null) total = instance.GetTotalTransform();
            }
            catch (Exception)
            {
            }
            try
            {
                if (instance != null) local = instance.GetTransform();
            }
            catch (Exception)
            {
            }
            found.Add(new KeyValuePair<string, Transform>("total transform", total));
            found.Add(new KeyValuePair<string, Transform>("instance transform", local));
            return found;
        }

        private static void FrameFromTransform(Transform transform, XYZ right, XYZ up, out XYZ origin, out double angle, out bool mirrored)
        {
            origin = transform.Origin;
            angle = PlaneAngle(transform.BasisX, right, up);
            mirrored = IsMirroredInPlane(transform.BasisX, transform.BasisY, right, up);
        }

        /// <summary>target - got, wrapped to (-pi, pi], so 359 degrees reads as -1.</summary>
        private static double AngleGap(double target, double got)
        {
            double gap = (target - got) % (2.0 * Math.PI);
            if (gap <= -Math.PI) gap += 2.0 * Math.PI;
            else if (gap > Math.PI) gap -= 2.0 * Math.PI;
            return gap;
        }

        /// <summary>
        /// Where an import symbol sits and which way round. Insertion point and rotation come from the block's own
        /// placement transform, the first route in InsertionCandidates that answers. By default the detail item is
        /// lined up insertion point to insertion point; with byCentre, middle to middle using the same transform for the angle.
        /// </summary>
        public static ImportFrame ReadImportFrame(Document doc, Element element, View view, bool byCentre)
        {
            var frame = new ImportFrame();
            XYZ right, up, normal;
            ViewAxes(view, out right, out up, out normal);
            frame.Candidates = InsertionCandidates(element, view);
            foreach (KeyValuePair<string, Transform> candidate in frame.Candidates)
            {
                if (candidate.Value == null) continue;
                try
                {
                    XYZ origin;
                    double angle;
                    bool mirrored;
                    FrameFromTransform(candidate.Value, right, up, out origin, out angle, out mirrored);
                    frame.Transform = candidate.Value;
                    frame.Origin = origin;
                    frame.OriginRoute = candidate.Key;
                    frame.Angle = angle;
                    frame.Mirrored = mirrored;
                    break;
                }
                catch (Exception)
                {
                }
            }
            frame.XDir = right * Math.Cos(frame.Angle) + up * Math.Sin(frame.Angle);
            if (byCentre)
            {
                string route;
                frame.Centre = MeasureCentre(doc, element, view, frame.Transform, out route);
                frame.Route = route;
            }
            else
            {
                frame.Centre = frame.Origin;
                frame.Route = frame.Origin != null ? "insertion point" : "";
            }
            return frame;
        }

        /// <summary>
        /// Normal of the plane to mirror across so the import's own X is kept. The plane holds the import's X axis
        /// and the view normal, so mirroring across it keeps X and flips the other in-plane axis, exactly what a
        /// block mirrored in AutoCAD did.
        /// </summary>
        private static XYZ MirrorPlaneNormal(XYZ viewNormal, XYZ xDir)
        {
            return viewNormal.CrossProduct(xDir).Normalize();
        }

        private static XYZ FlattenToPlane(XYZ vector, XYZ normal)
        {
            return vector - normal * vector.DotProduct(normal);
        }

        private static Element PlaceDetailItem(Document doc, FamilySymbol symbol, View view, ImportFrame frame, double extraRadians,
                                               bool matchRotation, bool matchMirror, Report report, List<string> problems, bool byCentre,
                                               out string message)
        {
            return byCentre
                ? PlaceByCentre(doc, symbol, view, frame, extraRadians, matchRotation, matchMirror, report, problems, out message)
                : PlaceByInsertion(doc, symbol, view, frame, extraRadians, matchRotation, matchMirror, report, problems, out message);
        }

        /// <summary>
        /// Put a detail item's insertion point on the block's, at its rotation: the same rule a family-for-family
        /// swap follows. Then checked: the item's own placement is read back, and if its origin is more than half a
        /// millimetre from the block's, or its X more than a hundredth of a degree from the block's, it is moved or
        /// turned by exactly what is left.
        /// </summary>
        private static Element PlaceByInsertion(Document doc, FamilySymbol symbol, View view, ImportFrame frame, double extraRadians,
                                                bool matchRotation, bool matchMirror, Report report, List<string> problems, out string message)
        {
            XYZ origin = frame.Origin;
            Element created = AttemptPlace(doc, () => doc.Create.NewFamilyInstance(origin, symbol, view), out message);
            if (created == null) return null;

            XYZ right, up, normal;
            ViewAxes(view, out right, out up, out normal);
            double angle = extraRadians;
            if (matchRotation) angle += frame.Angle;
            if (Math.Abs(angle) > 1.0e-9)
            {
                try
                {
                    Line axis = Line.CreateBound(origin, origin + normal);
                    ElementTransformUtils.RotateElement(doc, created.Id, axis, angle);
                    if (matchRotation && Math.Abs(frame.Angle) > 1.0e-9) report.Rotated++;
                }
                catch (Exception err)
                {
                    problems.Add("the detail item would not rotate (" + err.Message + ")");
                }
            }

            bool mirrored = false;
            if (matchMirror && frame.Mirrored)
            {
                try
                {
                    XYZ placedX = right * Math.Cos(angle) + up * Math.Sin(angle);
                    XYZ across = MirrorPlaneNormal(normal, placedX);
                    Plane plane = Plane.CreateByNormalAndOrigin(across, origin);
                    ElementTransformUtils.MirrorElements(doc, new List<ElementId> { created.Id }, plane, false);
                    report.Mirrored++;
                    mirrored = true;
                }
                catch (Exception err)
                {
                    report.MirrorFailed++;
                    problems.Add("the import is mirrored and the detail item would not mirror to match (" + err.Message + ")");
                }
            }
            try
            {
                doc.Regenerate();
            }
            catch (Exception)
            {
            }

            // check against the item's own placement, and put right what is left
            string gapText = "none", turnText = "not checked";
            Transform placed = InstanceTransform(created);
            if (placed == null)
            {
                report.CentreUnverified++;
                problems.Add("the detail item's placement could not be read back, so it was not checked");
            }
            else
            {
                try
                {
                    XYZ gap = FlattenToPlane(origin - placed.Origin, normal);
                    if (gap.GetLength() > CentreTolFt)
                    {
                        ElementTransformUtils.MoveElement(doc, created.Id, gap);
                        report.CentreCorrected++;
                    }
                    if (!mirrored)
                    {
                        // a mirrored item's X can be stored either way round, so only an unmirrored one is turned by what its X says
                        double turn = AngleGap(angle, PlaneAngle(placed.BasisX, right, up));
                        turnText = (turn * 180.0 / Math.PI).ToString("0.000") + " deg";
                        if (Math.Abs(turn) > AngleTol)
                        {
                            Line axis = Line.CreateBound(origin, origin + normal);
                            ElementTransformUtils.RotateElement(doc, created.Id, axis, turn);
                            report.RotationCorrected++;
                        }
                    }
                    doc.Regenerate();
                    placed = InstanceTransform(created);
                    XYZ left = FlattenToPlane(origin - placed.Origin, normal);
                    gapText = FtToMm(left.GetLength()).ToString("0.00") + "mm";
                    if (left.GetLength() > CentreTolFt)
                    {
                        report.CentreUnverified++;
                        problems.Add("the detail item's insertion point is still " + FtToMm(left.GetLength()).ToString("0.0") + "mm from the symbol's");
                    }
                }
                catch (Exception err)
                {
                    report.CentreUnverified++;
                    problems.Add("the detail item could not be checked (" + err.Message + ")");
                }
            }

            report.Debug.Add("  detail " + Eid(created.Id) + ": placed at " + MmText(origin) + ", turned " + (angle * 180.0 / Math.PI).ToString("0.00") +
                             " deg, mirrored " + mirrored + "; insertion point off by " + gapText + "; turn off by " + turnText);
            message = "";
            return created;
        }

        /// <summary>
        /// Put a detail item's middle on an import's middle, turned and handed to match.
        /// 1. Place it on the import's centre, still square, and read where its own middle sits from its insertion point.
        /// 2. Turn it, and mirror it if the block was mirrored, about its insertion point.
        /// 3. Work out where its middle now is (the offset turned and mirrored the same way) and move it onto the import's.
        /// 4. Measure again; if still more than half a millimetre off, move it by what is left, once.
        /// </summary>
        private static Element PlaceByCentre(Document doc, FamilySymbol symbol, View view, ImportFrame frame, double extraRadians,
                                             bool matchRotation, bool matchMirror, Report report, List<string> problems, out string message)
        {
            XYZ centre = frame.Centre;
            Element created = AttemptPlace(doc, () => doc.Create.NewFamilyInstance(centre, symbol, view), out message);
            if (created == null) return null;
            try
            {
                doc.Regenerate();
            }
            catch (Exception)
            {
            }

            XYZ right, up, normal;
            ViewAxes(view, out right, out up, out normal);

            // 1. the item's own middle, relative to its insertion point, while square
            XYZ insert = ElementPivot(created) ?? centre;
            XYZ square = null;
            string route = "";
            try
            {
                BoundingBoxXYZ box = created.get_BoundingBox(view);
                if (box != null)
                {
                    square = BoxCentre(box);
                    route = "square box";
                }
            }
            catch (Exception)
            {
                square = null;
            }
            if (square == null) square = OwnFrameCentre(created, view, out route);
            XYZ offset = square != null ? FlattenToPlane(square - insert, normal) : null;

            // 2. turn and mirror about the insertion point
            double angle = extraRadians;
            if (matchRotation) angle += frame.Angle;
            XYZ placedX = right * Math.Cos(angle) + up * Math.Sin(angle);
            if (Math.Abs(angle) > 1.0e-9)
            {
                try
                {
                    Line axis = Line.CreateBound(insert, insert + normal);
                    ElementTransformUtils.RotateElement(doc, created.Id, axis, angle);
                    if (matchRotation && Math.Abs(frame.Angle) > 1.0e-9) report.Rotated++;
                }
                catch (Exception err)
                {
                    angle = 0.0;
                    problems.Add("the detail item would not rotate (" + err.Message + ")");
                }
            }

            XYZ across = null;
            if (matchMirror && frame.Mirrored)
            {
                try
                {
                    // mirror across the line the item's own X runs along: keeps X, flips the other axis
                    across = MirrorPlaneNormal(normal, placedX);
                    Plane plane = Plane.CreateByNormalAndOrigin(across, insert);
                    ElementTransformUtils.MirrorElements(doc, new List<ElementId> { created.Id }, plane, false);
                    report.Mirrored++;
                }
                catch (Exception err)
                {
                    across = null;
                    report.MirrorFailed++;
                    problems.Add("the import is mirrored and the detail item would not mirror to match (" + err.Message + ")");
                }
            }

            // 3. move its middle onto the import's middle: worked out, not read back
            XYZ firstMove = null;
            if (offset != null)
            {
                XYZ expected = insert + PlacedOffset(offset, angle, across, right, up);
                firstMove = FlattenToPlane(centre - expected, normal);
                if (firstMove.GetLength() > PointTolFt * 10.0)
                {
                    try
                    {
                        ElementTransformUtils.MoveElement(doc, created.Id, firstMove);
                        report.CentreShifted++;
                    }
                    catch (Exception err)
                    {
                        problems.Add("the detail item could not be centred (" + err.Message + ")");
                    }
                }
            }
            try
            {
                doc.Regenerate();
            }
            catch (Exception)
            {
            }

            // 4. verify, and correct once
            string checkRoute;
            XYZ landed = MeasureCentre(doc, created, view, null, out checkRoute);
            XYZ residual = null;
            if (landed != null)
            {
                residual = FlattenToPlane(centre - landed, normal);
                if (residual.GetLength() > CentreTolFt)
                {
                    try
                    {
                        ElementTransformUtils.MoveElement(doc, created.Id, residual);
                        doc.Regenerate();
                        report.CentreCorrected++;
                    }
                    catch (Exception)
                    {
                    }
                    landed = MeasureCentre(doc, created, view, null, out checkRoute);
                    residual = landed != null ? FlattenToPlane(centre - landed, normal) : null;
                }
            }
            if (residual == null)
            {
                report.CentreUnverified++;
                problems.Add("the detail item's centre could not be measured afterwards, so it may not sit on the symbol's centre");
            }
            else if (residual.GetLength() > CentreTolFt)
            {
                report.CentreUnverified++;
                problems.Add("the detail item's centre is still " + FtToMm(residual.GetLength()).ToString("0.0") + "mm from the symbol's centre");
            }

            report.Debug.Add("  detail " + Eid(created.Id) + ": offset " + MmText(offset) + " via " + (string.IsNullOrEmpty(route) ? "none" : route) +
                             "; angle " + (angle * 180.0 / Math.PI).ToString("0.00") + "; mirrored " + (across != null) + "; moved " + MmText(firstMove) +
                             "; check via " + (string.IsNullOrEmpty(checkRoute) ? "none" : checkRoute) + ", off by " +
                             (residual == null ? "none" : FtToMm(residual.GetLength()).ToString("0.00") + "mm"));
            message = "";
            return created;
        }

        /// <summary>Swap one import symbol for a detail item in the same view.</summary>
        private static bool ReplaceImportOne(Document doc, Element source, FamilySymbol symbol, RunOptions options, Report report, out string message)
        {
            message = "";
            long sourceId = Eid(source.Id);
            try
            {
                if (source.GroupId != null && Eid(source.GroupId) > 0)
                {
                    message = "Import " + sourceId + " is inside a detail group and was left alone - groups are not handled in drafting views.";
                    return false;
                }
            }
            catch (Exception)
            {
            }

            View view = OwnerView(doc, source);
            if (view == null)
            {
                message = "Import " + sourceId + " is not drawn in a view, so there is nowhere to put a detail item. It was left alone.";
                return false;
            }

            ImportFrame frame = ReadImportFrame(doc, source, view, options.ByCentre);
            if (frame.Centre == null)
            {
                message = "Import " + sourceId + ": its " + (options.ByCentre ? "centre" : "insertion point") + " could not be found, so it was left alone.";
                return false;
            }

            List<IndependentTag> tags = options.RetainTags ? TagsOn(doc, source) : new List<IndependentTag>();
            bool wasPinned = false;
            try
            {
                wasPinned = source.Pinned;
            }
            catch (Exception)
            {
            }

            report.Debug.Add("Import " + sourceId + " \"" + ImportName(doc, source) + "\" in \"" + Name(view) + "\": lined up by " +
                             (string.IsNullOrEmpty(frame.Route) ? "none" : frame.Route) + " at " + MmText(frame.Centre) + "; insertion from " +
                             (string.IsNullOrEmpty(frame.OriginRoute) ? "none" : frame.OriginRoute) + "; angle " +
                             (frame.Angle * 180.0 / Math.PI).ToString("0.00") + "; mirrored " + frame.Mirrored);
            XYZ right, up, normal;
            ViewAxes(view, out right, out up, out normal);
            foreach (KeyValuePair<string, Transform> candidate in frame.Candidates)
            {
                if (candidate.Value == null)
                {
                    report.Debug.Add("    " + candidate.Key + ": none");
                    continue;
                }
                try
                {
                    XYZ origin;
                    double angle;
                    bool mirrored;
                    FrameFromTransform(candidate.Value, right, up, out origin, out angle, out mirrored);
                    report.Debug.Add("    " + candidate.Key + ": origin " + MmText(origin) + ", angle " + (angle * 180.0 / Math.PI).ToString("0.00") +
                                     ", mirrored " + mirrored);
                }
                catch (Exception)
                {
                    report.Debug.Add("    " + candidate.Key + ": unreadable");
                }
            }

            var problems = new List<string>();
            string placeMessage;
            Element created = PlaceDetailItem(doc, symbol, view, frame, options.ExtraRadians, options.MatchOrientation, options.MatchMirror, report,
                                              problems, options.ByCentre, out placeMessage);
            if (created == null)
            {
                message = "Import " + sourceId + ": the detail item would not place in \"" + Name(view) + "\" (" +
                          (string.IsNullOrEmpty(placeMessage) ? "no reason given" : placeMessage) + ").";
                return false;
            }

            string route = options.ByCentre ? frame.Route : frame.OriginRoute;
            Report.Bump(report.CentreRoutes, route ?? "");
            report.Views[Eid(view.Id)] = Name(view);

            foreach (string name in options.RetainNames)
            {
                string text;
                if (!CopyParameter(source, created, name, out text) && text.Length > 0) problems.Add(text);
            }

            if (tags.Count > 0) report.TagsKept += TransferTags(doc, tags, source, created, problems);

            try
            {
                if (wasPinned) source.Pinned = false;
            }
            catch (Exception)
            {
            }

            doc.Delete(source.Id);

            if (wasPinned)
            {
                try
                {
                    created.Pinned = true;
                    report.Pinned++;
                }
                catch (Exception)
                {
                    problems.Add("the import was pinned and the detail item would not take the pin");
                }
            }

            report.Replaced++;
            report.NewIds.Add(created.Id);
            if (problems.Count > 0) report.Add("warn", "Import " + sourceId + ": " + string.Join("; ", problems));
            return true;
        }
    }
}
