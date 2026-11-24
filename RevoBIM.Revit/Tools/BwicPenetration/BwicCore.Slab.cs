using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;
using OperationCanceledException = Autodesk.Revit.Exceptions.OperationCanceledException;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.BwicPenetration
{
    /// <summary>Size and position a slab opening needs (the dict compute_slab_bwic returned).</summary>
    public sealed class SlabGeom
    {
        public string Rule;
        public double Height, TopHeight, LevelOffset, Length, Width, Angle, Depth, BaseOffset, TopOffset, BaseWorld, TopWorld, TargetZ;
        public double? SlabTop, SlabBottom;
        public XYZ Point;
        public Level Level, PreferredLevel;
        public List<Level> Levels;
        public bool Circular;
    }

    /// <summary>A Generic Model family with the placement kind of its types.</summary>
    public sealed class GenericFamily
    {
        public string Name, Kind, Label;
        public List<string> Types;
    }

    public static partial class BwicCore
    {
        public static readonly Dictionary<string, string> SlabDefaults = new Dictionary<string, string>
        {
            { "slab_family", "" }, { "slab_type", "" }, { "slab_family_kind", "all" }, { "slab_clearance", "50" },
            { "slab_length_param", "BGL_Height" }, { "slab_width_param", "BGL_Width" }, { "slab_datum", "soffit" },
            { "slab_base_extra", "50" }, { "slab_top_extra", "100" }, { "slab_base_level_param", "" }, { "slab_top_level_param", "" },
            { "slab_base_offset_param", "" }, { "slab_top_offset_param", "" }, { "debug", "no" },
        };

        private static readonly string[] BaseLevelBips = { "FAMILY_BASE_LEVEL_PARAM", "FAMILY_LEVEL_PARAM", "SCHEDULE_BASE_LEVEL_PARAM", "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM" };
        private static readonly string[] TopLevelBips = { "FAMILY_TOP_LEVEL_PARAM", "SCHEDULE_TOP_LEVEL_PARAM" };
        private static readonly string[] BaseOffsetBips = { "FAMILY_BASE_LEVEL_OFFSET_PARAM", "INSTANCE_FREE_HOST_OFFSET_PARAM", "SCHEDULE_BASE_LEVEL_OFFSET_PARAM" };
        private static readonly string[] TopOffsetBips = { "FAMILY_TOP_LEVEL_OFFSET_PARAM", "SCHEDULE_TOP_LEVEL_OFFSET_PARAM" };
        private static readonly string[] SizeFallbacks = { "BGL_Length", "BGL_Height", "BGL_Width", "BGL_Depth", "Length", "Width", "Height", "Depth" };

        public static Dictionary<string, string> GetSlabDefaults() { return new Dictionary<string, string>(SlabDefaults); }

        // ---------------------------------------------------------------- picking the slab

        /// <summary>Floors and structural foundation slabs.</summary>
        public static bool IsSlab(Element element)
        {
            try
            {
                if (element is Floor) return true;
                Category category = element.Category;
                if (category == null) return false;
                foreach (string name in new[] { "OST_Floors", "OST_StructuralFoundation" })
                {
                    BuiltInCategory bic;
                    if (Enum.TryParse(name, out bic) && EidValue(category.Id) == (long)bic) return true;
                }
            }
            catch (Exception) { }
            return false;
        }

        public sealed class SlabPickFilter : ISelectionFilter
        {
            private readonly Document _host;
            public SlabPickFilter(Document host) { _host = host; }

            public bool AllowElement(Element element) { return IsSlab(element) || element is RevitLinkInstance; }

            public bool AllowReference(Reference reference, XYZ position)
            {
                try
                {
                    Element element = _host.GetElement(reference.ElementId);
                    var link = element as RevitLinkInstance;
                    if (link != null)
                    {
                        Document linkDoc = link.GetLinkDocument();
                        if (linkDoc == null) return false;
                        return IsSlab(linkDoc.GetElement(reference.LinkedElementId));
                    }
                    return IsSlab(element);
                }
                catch (Exception) { return false; }
            }
        }

        /// <summary>Overall thickness of a floor, in internal units; null when nothing can be read.</summary>
        public static double? SlabDepth(Element slab)
        {
            foreach (string bipName in new[] { "FLOOR_ATTR_THICKNESS_PARAM", "STRUCTURAL_FLOOR_CORE_THICKNESS" })
            {
                BuiltInParameter bip;
                if (!Enum.TryParse(bipName, out bip)) continue;
                try
                {
                    Element stype = slab.Document.GetElement(slab.GetTypeId());
                    foreach (Element holder in new[] { stype, slab })
                    {
                        if (holder == null) continue;
                        Parameter param = holder.get_Parameter(bip);
                        if (param != null && param.StorageType == StorageType.Double)
                        {
                            double value = param.AsDouble();
                            if (value > 1e-9) return value;
                        }
                    }
                }
                catch (Exception) { }
            }
            try
            {
                var stype = slab.Document.GetElement(slab.GetTypeId()) as HostObjAttributes;
                CompoundStructure structure = stype == null ? null : stype.GetCompoundStructure();
                if (structure != null)
                {
                    double width = structure.GetWidth();
                    if (width > 1e-9) return width;
                }
            }
            catch (Exception) { }
            try
            {
                BoundingBoxXYZ bb = slab.get_BoundingBox(null);
                if (bb != null) return Math.Abs(bb.Max.Z - bb.Min.Z);
            }
            catch (Exception) { }
            return null;
        }

        /// <summary>(top, bottom) elevation of the slab, in host coordinates; nulls when unknown.</summary>
        public static void SlabFaces(Element slab, Transform transform, out double? top, out double? bottom)
        {
            top = bottom = null;
            try
            {
                BoundingBoxXYZ bb = slab.get_BoundingBox(null);
                if (bb == null) return;
                var zs = new[] { bb.Min, bb.Max }.Select(p => transform.OfPoint(bb.Transform.OfPoint(p)).Z).ToList();
                top = zs.Max();
                bottom = zs.Min();
            }
            catch (Exception)
            {
                top = bottom = null;
            }
        }

        public static double? SlabTopElevation(Element slab, Transform transform)
        {
            double? top, bottom;
            SlabFaces(slab, transform, out top, out bottom);
            return top;
        }

        // ---------------------------------------------------------------- families available to the slab tool

        /// <summary>("hosted"|"regular", a readable label) for a family symbol.</summary>
        public static Tuple<string, string> FamilyKind(FamilySymbol symbol)
        {
            string placement = "";
            try { placement = symbol.Family.FamilyPlacementType.ToString(); }
            catch (Exception) { }
            string hosting = "";
            try
            {
                Parameter param = symbol.Family.get_Parameter(BuiltInParameter.FAMILY_HOSTING_BEHAVIOR);
                if (param != null)
                {
                    switch (param.AsInteger())
                    {
                        case 1: hosting = "wall"; break;
                        case 2: hosting = "floor"; break;
                        case 3: hosting = "ceiling"; break;
                        case 4: hosting = "roof"; break;
                        case 5: hosting = "face"; break;
                    }
                }
            }
            catch (Exception) { }
            if (placement.Contains("Hosted") || hosting.Length > 0)
                return Tuple.Create("hosted", ((hosting.Length > 0 ? hosting : "host") + " hosted").Trim());
            if (placement.Contains("WorkPlane")) return Tuple.Create("regular", "work plane based");
            if (placement.Contains("TwoLevels")) return Tuple.Create("regular", "two levels");
            if (placement.Contains("CurveBased") || placement.Contains("Curve")) return Tuple.Create("regular", "line based");
            return Tuple.Create("regular", "non-hosted");
        }

        public static bool IsFloorBased(FamilySymbol symbol) { return FamilyKind(symbol).Item1 == "hosted"; }

        /// <summary>Generic model families with the placement kind of each, sorted by name; kindFilter null for all.</summary>
        public static List<GenericFamily> GenericModelFamilies(Document doc, string kindFilter = null)
        {
            var found = new Dictionary<string, GenericFamily>();
            IEnumerable<Element> collector;
            try
            {
                collector = new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_GenericModel).ToList();
            }
            catch (Exception)
            {
                collector = new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).ToList();
            }
            foreach (Element e in collector)
            {
                try
                {
                    var symbol = (FamilySymbol)e;
                    Family family = symbol.Family;
                    if (family == null) continue;
                    var kind = FamilyKind(symbol);
                    if (!string.IsNullOrEmpty(kindFilter) && kind.Item1 != kindFilter) continue;
                    GenericFamily entry;
                    if (!found.TryGetValue(family.Name, out entry))
                    {
                        entry = new GenericFamily { Name = family.Name, Kind = kind.Item1, Label = kind.Item2, Types = new List<string>() };
                        found[family.Name] = entry;
                    }
                    entry.Types.Add(symbol.Name);
                }
                catch (Exception) { }
            }
            DebugLog("generic model families found: " + found.Count + " (filter " + (kindFilter ?? "all") + ")");
            foreach (string name in found.Keys.OrderBy(n => n, StringComparer.Ordinal))
                DebugLog("   " + name + " [" + found[name].Label + "] " + found[name].Types.Count + " type(s)");
            return found.Keys.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).Select(n =>
            {
                found[n].Types = found[n].Types.OrderBy(t => t, StringComparer.Ordinal).ToList();
                return found[n];
            }).ToList();
        }

        /// <summary>{family name: rectangular or circular} for the generic model families, from their length parameters.</summary>
        public static Dictionary<string, string> FamilyShapes(Document doc)
        {
            var lengths = new Dictionary<string, HashSet<string>>();
            var placed = new HashSet<string>();
            Action<string, Element> harvest = (name, element) =>
            {
                try
                {
                    foreach (Parameter param in element.Parameters)
                    {
                        try
                        {
                            if (param.StorageType == StorageType.Double)
                            {
                                if (!lengths.ContainsKey(name)) lengths[name] = new HashSet<string>();
                                lengths[name].Add(param.Definition.Name);
                            }
                        }
                        catch (Exception) { }
                    }
                }
                catch (Exception) { }
            };
            try
            {
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FamilyInstance)).OfCategory(BuiltInCategory.OST_GenericModel).WhereElementIsNotElementType())
                {
                    string name;
                    try { name = ((FamilyInstance)e).Symbol.Family.Name; }
                    catch (Exception) { continue; }
                    if (placed.Contains(name)) continue;
                    placed.Add(name);
                    harvest(name, e);
                }
            }
            catch (Exception) { }
            try
            {
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_GenericModel))
                {
                    string name;
                    try { name = ((FamilySymbol)e).Family.Name; }
                    catch (Exception) { continue; }
                    if (!lengths.ContainsKey(name)) lengths[name] = new HashSet<string>();
                    harvest(name, e);
                }
            }
            catch (Exception) { }
            var shapes = new Dictionary<string, string>();
            foreach (var kv in lengths) shapes[kv.Key] = BwicFamilies.FamilyShape(kv.Value, kv.Key, placed.Contains(kv.Key));
            DebugLog("family shapes: " + string.Join(", ", shapes.OrderBy(k => k.Key, StringComparer.Ordinal)
                .Select(k => k.Key + " " + (k.Value == BwicFamilies.Circ ? "round" : "rect"))));
            return shapes;
        }

        /// <summary>Writable length parameters a family carries (from a placed instance when there is one, else a type).</summary>
        public static List<string> FamilyParameterNames(Document doc, string familyName, bool lengthsOnly = true)
        {
            var names = new HashSet<string>();
            Action<Element> harvest = element =>
            {
                if (element == null) return;
                try
                {
                    foreach (Parameter param in element.Parameters)
                    {
                        try
                        {
                            if (param.IsReadOnly) continue;
                            if (lengthsOnly && param.StorageType != StorageType.Double) continue;
                            names.Add(param.Definition.Name);
                        }
                        catch (Exception) { }
                    }
                }
                catch (Exception) { }
            };
            foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FamilyInstance)).WhereElementIsNotElementType())
            {
                try
                {
                    var inst = (FamilyInstance)e;
                    if (inst.Symbol != null && inst.Symbol.Family.Name == familyName)
                    {
                        harvest(inst);
                        break;
                    }
                }
                catch (Exception) { }
            }
            foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)))
            {
                try
                {
                    var sym = (FamilySymbol)e;
                    if (sym.Family != null && sym.Family.Name == familyName)
                    {
                        harvest(sym);
                        break;
                    }
                }
                catch (Exception) { }
            }
            return names.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        /// <summary>True once the family has an instance in the model.</summary>
        public static bool FamilyIsPlaced(Document doc, string familyName)
        {
            foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FamilyInstance)).WhereElementIsNotElementType())
            {
                try
                {
                    var inst = (FamilyInstance)e;
                    if (inst.Symbol != null && inst.Symbol.Family.Name == familyName) return true;
                }
                catch (Exception) { }
            }
            return false;
        }

        /// <summary>The family type's own preview image, or null (a blank image counts as none).</summary>
        public static System.Drawing.Bitmap FamilyPreview(Document doc, string familyName, string typeName = null, int pixels = 192)
        {
            FamilySymbol symbol = FindSlabSymbol(doc, familyName, typeName);
            if (symbol == null) return null;
            System.Drawing.Bitmap bitmap;
            try { bitmap = symbol.GetPreviewImage(new System.Drawing.Size(pixels, pixels)); }
            catch (Exception err)
            {
                DebugLog("no preview for \"" + familyName + "\": " + err.Message);
                return null;
            }
            if (bitmap == null) return null;
            try
            {
                System.Drawing.Color first = bitmap.GetPixel(0, 0);
                int step = Math.Max(1, pixels / 12);
                for (int x = 0; x < bitmap.Width; x += step)
                    for (int y = 0; y < bitmap.Height; y += step)
                        if (bitmap.GetPixel(x, y) != first) return bitmap;
                bitmap.Dispose();
                return null;
            }
            catch (Exception) { return bitmap; }
        }

        /// <summary>The chosen slab family type, or the family's first type.</summary>
        public static FamilySymbol FindSlabSymbol(Document doc, string familyName, string typeName)
        {
            if (string.IsNullOrEmpty(familyName)) return null;
            FamilySymbol fallback = null;
            foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)))
            {
                try
                {
                    var symbol = (FamilySymbol)e;
                    if (symbol.Family == null || symbol.Family.Name != familyName) continue;
                    if (fallback == null) fallback = symbol;
                    if (!string.IsNullOrEmpty(typeName) && symbol.Name == typeName) return symbol;
                }
                catch (Exception) { }
            }
            return fallback;
        }

        public static string FamilyNameOf(FamilySymbol symbol)
        {
            try { return symbol.Family.Name; }
            catch (Exception) { return ""; }
        }

        // ---------------------------------------------------------------- writing the level and offset parameters

        /// <summary>Write every parameter on an element to the debug log (a missing name is the commonest cause of "did nothing").</summary>
        public static void ListParameters(Element element, string label)
        {
            if (!Debug) return;
            DebugLog("parameters on " + label + ":");
            foreach (var pair in new[] { Tuple.Create((Element)element, "instance"), Tuple.Create(element.Document.GetElement(element.GetTypeId()), "type") })
            {
                if (pair.Item1 == null) continue;
                var names = new List<string>();
                try
                {
                    foreach (Parameter param in pair.Item1.Parameters)
                    {
                        try { names.Add(param.Definition.Name + (param.IsReadOnly ? " (read only)" : "")); }
                        catch (Exception) { }
                    }
                }
                catch (Exception) { continue; }
                foreach (string name in names.OrderBy(n => n, StringComparer.Ordinal)) DebugLog("   [" + pair.Item2 + "] " + name);
            }
        }

        /// <summary>Set a parameter by configured name first, then by built in. value is a Level (isLevel) or a double.</summary>
        public static bool SetByNameOrBip(Element element, string name, string[] bipNames, object value, bool isLevel = false)
        {
            var holders = new List<Parameter>();
            if (!string.IsNullOrEmpty(name))
            {
                Parameter p = element.LookupParameter(name);
                if (p != null) holders.Add(p);
            }
            foreach (string bipName in bipNames)
            {
                BuiltInParameter bip;
                if (!Enum.TryParse(bipName, out bip)) continue;
                try
                {
                    Parameter p = element.get_Parameter(bip);
                    if (p != null) holders.Add(p);
                }
                catch (Exception) { }
            }
            foreach (Parameter param in holders)
            {
                try
                {
                    if (param.IsReadOnly) continue;
                    if (isLevel)
                    {
                        if (param.StorageType != StorageType.ElementId) continue;
                        param.Set(((Level)value).Id);
                    }
                    else
                    {
                        if (param.StorageType != StorageType.Double) continue;
                        param.Set((double)value);
                    }
                    return true;
                }
                catch (Exception) { }
            }
            return false;
        }

        /// <summary>The parameter that actually holds a size, and where it lives; null name when none.</summary>
        public static string ResolveSizeParam(Element instance, Element symbol, string wanted, IList<string> taken, out Element holderOut)
        {
            holderOut = null;
            if (BwicFamilies.DecodeSplit(wanted) != null)
            {
                foreach (Element holder in new[] { instance, symbol })
                {
                    if (holder != null && !taken.Contains(wanted) && HasLengthParam(holder, wanted))
                    {
                        holderOut = holder;
                        return wanted;
                    }
                }
                return null;
            }
            var candidates = new List<string> { wanted };
            candidates.AddRange(SizeFallbacks.Where(n => n != wanted));
            foreach (string name in candidates)
            {
                if (string.IsNullOrEmpty(name) || taken.Contains(name)) continue;
                foreach (Element holder in new[] { instance, symbol })
                {
                    if (holder == null) continue;
                    Parameter param;
                    try { param = holder.LookupParameter(name); }
                    catch (Exception) { continue; }
                    if (param == null || param.IsReadOnly) continue;
                    if (param.StorageType != StorageType.Double) continue;
                    holderOut = holder;
                    return name;
                }
            }
            return null;
        }

        // ---------------------------------------------------------------- the slab placement itself

        /// <summary>Size and position for a slab penetration. No model changes.</summary>
        public static SlabGeom ComputeSlabBwic(Document doc, IList<Service> services, Element slab, Transform transform, double clearanceFt,
                                               double baseExtraFt, double topExtraFt, IList<Level> levels, string datum, double? pickZ,
                                               string rule, double? roundUpMm, double heightExtraFt, double topHeightExtraFt,
                                               Level viewLevelHint, double? overridePlan, out string error)
        {
            error = null;
            var corners = new List<XYZ>();
            foreach (Service service in services) corners.AddRange(ServicePoints(service));
            if (corners.Count == 0)
            {
                error = "the selected elements have no geometry to measure";
                return null;
            }
            double? depthN = SlabDepth(slab);
            if (depthN == null)
            {
                error = "could not read a thickness from that floor";
                return null;
            }
            double depth = depthN.Value;
            DebugLog("floor depth " + FtToMm(depth).ToString("0.0") + " mm");

            double xMin = corners.Min(p => p.X), xMax = corners.Max(p => p.X);
            double yMin = corners.Min(p => p.Y), yMax = corners.Max(p => p.Y);
            double angle = 0.0, width, length, centreX, centreY;
            if (overridePlan != null)
            {
                width = length = overridePlan.Value;
                centreX = (xMin + xMax) / 2.0;
                centreY = (yMin + yMax) / 2.0;
            }
            else
            {
                PlanRect r = MinAreaRect(corners.Select(p => Tuple.Create(p.X, p.Y)).ToList());
                angle = r.Angle;
                centreX = r.CentreX;
                centreY = r.CentreY;
                width = RoundUpFt(r.Width + 2 * clearanceFt, roundUpMm);
                length = RoundUpFt(r.Depth + 2 * clearanceFt, roundUpMm);
                DebugLog("plan fit: " + FtToMm(r.Width).ToString("0") + " x " + FtToMm(r.Depth).ToString("0") + " mm turned "
                         + (((angle * 180 / Math.PI) % 180.0 + 180.0) % 180.0).ToString("0.0") + " deg -> opening "
                         + FtToMm(width).ToString("0") + " x " + FtToMm(length).ToString("0") + " mm");
                double square = RoundUpFt((xMax - xMin) + 2 * clearanceFt, roundUpMm);
                double squareV = RoundUpFt((yMax - yMin) + 2 * clearanceFt, roundUpMm);
                if (square * squareV > width * length * 1.05)
                    DebugLog("   (square to the model it would have been " + FtToMm(square).ToString("0") + " x " + FtToMm(squareV).ToString("0") + " mm)");
            }

            double? topN, bottomN;
            SlabFaces(slab, transform, out topN, out bottomN);
            if (pickZ != null)
            {
                if (topN != null && Math.Abs(topN.Value - pickZ.Value) > MmToFt(1.0))
                    DebugLog("NOTE the floor bounding box says " + FtToMm(topN.Value).ToString("0.0") + " mm but the click is at "
                             + FtToMm(pickZ.Value).ToString("0.0") + " mm - a difference of " + FtToMm(Math.Abs(topN.Value - pickZ.Value)).ToString("0")
                             + " mm. The click wins.");
                topN = pickZ;
                bottomN = pickZ.Value - depth;
            }
            if (topN == null)
            {
                error = "could not work out where that floor sits";
                return null;
            }
            double topZ = topN.Value, bottomZ = bottomN.Value;

            var serviceZ = corners.Select(p => p.Z).ToList();
            DebugLog("services span Z " + FtToMm(serviceZ.Min()).ToString("0.0") + " to " + FtToMm(serviceZ.Max()).ToString("0.0") + " mm");
            if (serviceZ.Max() < bottomZ - MmToFt(2000) || serviceZ.Min() > topZ + MmToFt(2000))
                DebugLog("WARNING the floor at " + FtToMm(topZ).ToString("0") + " mm is nowhere near the services - the opening would be placed away from them");

            Level level = NearestLevel(levels, topZ);
            if (level == null)
            {
                error = "could not work out a level for that floor";
                return null;
            }
            DebugLog("nearest level to " + FtToMm(topZ).ToString("0.0") + " mm is \"" + level.Name + "\" at " + FtToMm(LevelZ(level)).ToString("0.0")
                     + " mm (" + FtToMm(Math.Abs(LevelZ(level) - topZ)).ToString("0") + " mm away)");
            DebugLog("floor top " + FtToMm(topZ).ToString("0.0") + " mm, soffit " + FtToMm(bottomZ).ToString("0.0") + " mm");
            DebugLog("plan extent " + FtToMm(yMax - yMin).ToString("0") + " x " + FtToMm(xMax - xMin).ToString("0") + " mm -> L "
                     + FtToMm(length).ToString("0") + " W " + FtToMm(width).ToString("0"));
            double gap = FtToMm(Math.Abs(LevelZ(level) - topZ));
            if (gap > 5000)
                DebugLog("NOTE the nearest level \"" + level.Name + "\" is " + gap.ToString("0") + " mm from the floor. The opening is set out from the floor itself, so it still lands correctly.");

            double baseWorld;
            if (datum == "top") baseWorld = topZ + baseExtraFt;
            else if (datum == "level") baseWorld = LevelZ(level) + depth + baseExtraFt;
            else baseWorld = bottomZ - baseExtraFt;
            double topWorld = baseWorld + topExtraFt;
            double baseOffset = baseWorld - LevelZ(level);
            double topOffset = topWorld - LevelZ(level);
            DebugLog("datum \"" + datum + "\" -> base " + FtToMm(baseWorld).ToString("0.0") + " mm, top " + FtToMm(topWorld).ToString("0.0") + " mm (world)");
            DebugLog("offsets from \"" + level.Name + "\": base " + FtToMm(baseOffset).ToString("0.0") + " mm, top " + FtToMm(topOffset).ToString("0.0") + " mm");

            double openingHeight, topHeight;
            if (rule == "single_level")
            {
                level = NearestLevel(levels, topZ) ?? level;
                openingHeight = depth + heightExtraFt;
                baseWorld = bottomZ - (datum == "soffit" ? baseExtraFt : 0.0);
                topWorld = baseWorld + openingHeight;
                topHeight = (topZ + topHeightExtraFt) - LevelZ(level);
                DebugLog("single level rule: level \"" + level.Name + "\" at " + FtToMm(LevelZ(level)).ToString("0.0") + " mm, height "
                         + FtToMm(openingHeight).ToString("0.0") + " mm (floor " + FtToMm(depth).ToString("0.0") + " + " + FtToMm(heightExtraFt).ToString("0.0") + ")");
            }
            else
            {
                openingHeight = topWorld - baseWorld;
                topHeight = topWorld - LevelZ(level);
            }
            return new SlabGeom
            {
                Rule = rule, Height = openingHeight, TopHeight = topHeight, LevelOffset = baseWorld - LevelZ(level), Length = length, Width = width,
                Point = new XYZ(centreX, centreY, baseWorld), Angle = angle, Level = level, Levels = levels.ToList(), PreferredLevel = level,
                Depth = depth, BaseOffset = baseOffset, TopOffset = topOffset, BaseWorld = baseWorld, TopWorld = topWorld, TargetZ = baseWorld,
                SlabTop = topZ, SlabBottom = bottomZ,
            };
        }

        /// <summary>Make the opening's footprint match the one asked for (which plan parameter runs along X depends on the family).</summary>
        public static void SwapPlanSizes(Document doc, FamilyInstance instance, FamilySymbol placeSymbol, SlabGeom geom,
                                         Dictionary<string, string> settings, List<string> notes)
        {
            BoundingBoxXYZ bb = instance.get_BoundingBox(null);
            if (bb == null) return;
            double gotX = bb.Max.X - bb.Min.X, gotY = bb.Max.Y - bb.Min.Y;
            double wantX = geom.Width, wantY = geom.Length, tol = MmToFt(1.0);
            if (Math.Abs(gotX - wantX) <= tol && Math.Abs(gotY - wantY) <= tol) return;
            if (!(Math.Abs(gotX - wantY) <= tol && Math.Abs(gotY - wantX) <= tol))
            {
                DebugLog("footprint is " + FtToMm(gotX).ToString("0") + " x " + FtToMm(gotY).ToString("0") + " mm, asked for "
                         + FtToMm(wantX).ToString("0") + " x " + FtToMm(wantY).ToString("0") + " - the family may not size from these parameters");
                return;
            }
            string lengthParam = BwicFamilies.Get(settings, "slab_length_param");
            if (lengthParam.Length == 0) lengthParam = "BGL_Height";
            string widthParam = BwicFamilies.Get(settings, "slab_width_param");
            if (widthParam.Length == 0) widthParam = "BGL_Width";
            var taken = new List<string>();
            foreach (var pair in new[] { Tuple.Create(widthParam, geom.Length), Tuple.Create(lengthParam, geom.Width) })
            {
                Element holder;
                string name = ResolveSizeParam(instance, placeSymbol, pair.Item1, taken, out holder);
                if (name == null) return;
                taken.Add(name);
                string msg;
                SetLengthParam(holder, name, pair.Item2, out msg);
            }
            doc.Regenerate();
            notes.Add("plan sizes swapped to match the family");
            DebugLog("footprint was " + FtToMm(gotX).ToString("0") + " x " + FtToMm(gotY).ToString("0") + " mm, swapped to give "
                     + FtToMm(wantX).ToString("0") + " x " + FtToMm(wantY).ToString("0"));
        }

        /// <summary>Turn the opening to match the services it is set out around.</summary>
        public static void TurnToAngle(Document doc, FamilyInstance instance, double angle, List<string> notes)
        {
            if (Math.Abs(angle) < 1e-6) return;
            try
            {
                var loc = instance.Location as LocationPoint;
                XYZ origin = loc != null ? loc.Point : null;
                if (origin == null)
                {
                    BoundingBoxXYZ bb = instance.get_BoundingBox(null);
                    if (bb == null) return;
                    origin = new XYZ((bb.Min.X + bb.Max.X) / 2.0, (bb.Min.Y + bb.Max.Y) / 2.0, bb.Min.Z);
                }
                Line axis = Line.CreateBound(origin, origin + XYZ.BasisZ);
                ElementTransformUtils.RotateElement(doc, instance.Id, axis, angle);
                doc.Regenerate();
                notes.Add("turned " + (((angle * 180 / Math.PI) % 180.0 + 180.0) % 180.0).ToString("0.0") + " deg to suit");
            }
            catch (Exception err)
            {
                notes.Add("could not turn it: " + err.Message);
            }
        }

        private static string F0(double ft) { return FtToMm(ft).ToString("0"); }
        private static string F1(double ft) { return FtToMm(ft).ToString("0.0"); }

        /// <summary>Size, level, turn and centre a slab opening. Shared by placing a new opening and resizing one.</summary>
        public static FamilyInstance ApplySlabToInstance(Document doc, FamilyInstance instance, FamilySymbol placeSymbol, IList<Service> services,
                                                         SlabGeom geom, Dictionary<string, string> settings, BwicOptions options, Workset workset,
                                                         List<string> notes)
        {
            string lengthParam = BwicFamilies.Get(settings, "slab_length_param");
            if (lengthParam.Length == 0) lengthParam = "BGL_Height";
            string widthParam = BwicFamilies.Get(settings, "slab_width_param");
            if (widthParam.Length == 0) widthParam = "BGL_Width";
            Level level = geom.Level;
            XYZ point = geom.Point;
            Element holder;
            string msg;

            if (geom.Circular)
            {
                string diaParam = BwicFamilies.Get(settings, "slab_circular_param");
                if (diaParam.Length == 0) diaParam = "BGL_Diameter";
                string name = ResolveSizeParam(instance, placeSymbol, diaParam, new List<string>(), out holder);
                if (name == null)
                {
                    notes.Add("SIZE NOT SET - \"" + diaParam + "\" is not on the family");
                    ListParameters(instance, "the placed opening");
                }
                else
                {
                    bool radius = BwicFamilies.Get(settings, "slab_circular_radius") == "yes";
                    double value = BwicFamilies.RoundValue(geom.Width, radius);
                    if (SetLengthParam(holder, name, value, out msg))
                    {
                        notes.Add(name + " = " + F0(value) + " mm");
                        DebugLog("set " + name + " = " + F1(value) + " mm (" + (radius ? "radius" : "diameter") + ")");
                    }
                    else notes.Add(msg);
                }
            }
            else
            {
                var missing = new List<string>();
                var taken = new List<string>();
                foreach (var item in new[] { Tuple.Create(lengthParam, geom.Length, "length"), Tuple.Create(widthParam, geom.Width, "width") })
                {
                    string name = ResolveSizeParam(instance, placeSymbol, item.Item1, taken, out holder);
                    if (name == null)
                    {
                        missing.Add(item.Item1);
                        continue;
                    }
                    taken.Add(name);
                    if (!SetLengthParam(holder, name, item.Item2, out msg))
                    {
                        notes.Add(msg);
                        continue;
                    }
                    DebugLog("set " + name + " = " + F1(item.Item2) + " mm (" + item.Item3 + " slot)");
                    if (name != item.Item1) notes.Add("used \"" + name + "\" for the " + item.Item3 + " - \"" + item.Item1 + "\" is not on this family");
                }
                if (missing.Count > 0)
                {
                    notes.Add("SIZE NOT SET - no parameter found for " + string.Join(" and ", missing));
                    ListParameters(instance, "the placed opening");
                }
            }
            doc.Regenerate();

            if (geom.Rule == "single_level")
            {
                string heightParam = BwicFamilies.Get(settings, "slab_height_param");
                string topParam = BwicFamilies.Get(settings, "slab_top_height_param");
                string offsetParam = BwicFamilies.Get(settings, "slab_level_offset_param");
                if (!SetByNameOrBip(instance, null, BaseLevelBips, level, true))
                    DebugLog("level parameter not writable; the instance keeps the level it was created on");
                if (heightParam.Length > 0)
                {
                    if (SetLengthParam(instance, heightParam, geom.Height, out msg))
                        notes.Add(heightParam + " = " + F0(geom.Height) + " mm (floor " + F0(geom.Depth) + ")");
                    else
                    {
                        notes.Add(msg);
                        ListParameters(instance, "the placed opening");
                    }
                }
                else notes.Add("no vertical height parameter set in Settings");
                if (topParam.Length > 0)
                {
                    bool ok = SetLengthParam(instance, topParam, geom.TopHeight, out msg);
                    notes.Add(ok ? topParam + " = " + F0(geom.TopHeight) + " mm" : msg);
                }
                if (offsetParam.Length > 0)
                {
                    if (!SetLengthParam(instance, offsetParam, geom.LevelOffset, out msg)) DebugLog(msg);
                }
                doc.Regenerate();

                double wanted = geom.BaseWorld;
                for (int attempt = 0; attempt < 2; attempt++)
                {
                    BoundingBoxXYZ bb = instance.get_BoundingBox(null);
                    if (bb == null) break;
                    double drift = wanted - bb.Min.Z;
                    DebugLog("geometry base at " + F1(bb.Min.Z) + " mm, wanted " + F1(wanted) + " mm, drift " + F1(drift) + " mm");
                    if (Math.Abs(drift) <= MmToFt(1.0)) break;
                    ElementTransformUtils.MoveElement(doc, instance.Id, new XYZ(0, 0, drift));
                    doc.Regenerate();
                    notes.Add("moved " + F0(drift) + " mm to sit on the floor");
                }
            }
            else if (SetByNameOrBip(instance, BwicFamilies.Get(settings, "slab_base_level_param"), BaseLevelBips, level, true))
                notes.Add("base level " + level.Name);
            else notes.Add("could not set the base level");

            if (geom.Rule != "single_level")
                SetByNameOrBip(instance, BwicFamilies.Get(settings, "slab_top_level_param"), TopLevelBips, level, true);

            double topSpan = geom.TopOffset - geom.BaseOffset;
            if (geom.Rule == "single_level") { }
            else if (SetByNameOrBip(instance, BwicFamilies.Get(settings, "slab_base_offset_param"), BaseOffsetBips, geom.BaseOffset))
                notes.Add("base offset " + F0(geom.BaseOffset) + " mm (slab " + F0(geom.Depth) + " + " + F0(geom.BaseOffset - geom.Depth) + ")");
            else notes.Add("could not set the base offset");

            if (geom.Rule != "single_level"
                && SetByNameOrBip(instance, BwicFamilies.Get(settings, "slab_top_offset_param"), TopOffsetBips, geom.TopOffset))
                notes.Add("top offset " + F0(geom.TopOffset) + " mm");
            doc.Regenerate();

            // Measure, do not reason: read where the solid actually landed and correct the offset by the difference.
            if (geom.Rule != "single_level")
            {
                for (int attempt = 0; attempt < 2; attempt++)
                {
                    BoundingBoxXYZ bb = instance.get_BoundingBox(null);
                    if (bb == null) break;
                    double drift = geom.BaseWorld - bb.Min.Z;
                    DebugLog("geometry base at " + F1(bb.Min.Z) + " mm, wanted " + F1(geom.BaseWorld) + " mm, drift " + F1(drift) + " mm");
                    if (Math.Abs(drift) <= MmToFt(1.0)) break;
                    double corrected = geom.BaseOffset + drift;
                    if (!SetByNameOrBip(instance, BwicFamilies.Get(settings, "slab_base_offset_param"), BaseOffsetBips, corrected))
                    {
                        notes.Add("could not correct the base offset");
                        break;
                    }
                    geom.BaseOffset = corrected;
                    SetByNameOrBip(instance, BwicFamilies.Get(settings, "slab_top_offset_param"), TopOffsetBips, corrected + topSpan);
                    doc.Regenerate();
                    notes.Add("base offset corrected by " + F0(drift) + " mm");
                }
            }

            // centre the opening on the services, in plan: the GEOMETRY is measured and the box centred on the services
            if (!geom.Circular)
            {
                SwapPlanSizes(doc, instance, placeSymbol, geom, settings, notes);
                TurnToAngle(doc, instance, geom.Angle, notes);
            }
            for (int attempt = 0; attempt < 3; attempt++)
            {
                BoundingBoxXYZ bb = instance.get_BoundingBox(null);
                if (bb == null) break;
                double centreX = (bb.Min.X + bb.Max.X) / 2.0, centreY = (bb.Min.Y + bb.Max.Y) / 2.0;
                double dx = point.X - centreX, dy = point.Y - centreY;
                if (Math.Max(Math.Abs(dx), Math.Abs(dy)) <= MmToFt(0.5)) break;
                DebugLog("centring: geometry centre " + F1(centreX) + ", " + F1(centreY) + " -> wanted " + F1(point.X) + ", " + F1(point.Y)
                         + " (moving " + F1(dx) + ", " + F1(dy) + " mm)");
                ElementTransformUtils.MoveElement(doc, instance.Id, new XYZ(dx, dy, 0));
                doc.Regenerate();
            }
            doc.Regenerate();

            PlaceOnWorkset(doc, instance, options, workset, notes);

            string levelParam = BwicFamilies.Get(settings, "slab_level_code_param");
            if (levelParam.Length == 0) levelParam = options.LevelParam;
            if (string.IsNullOrEmpty(levelParam)) levelParam = LevelParamName;
            if (levelParam.Length > 0)
            {
                string code = LevelCode(level, geom.Levels);
                bool ok = SetLevelCode(instance, levelParam, code, out msg);
                notes.Add(ok ? levelParam + " = " + code + " (" + level.Name + ")" : msg);
                if (!ok) ListParameters(instance, "the placed opening");
            }

            if (options.LogComments)
            {
                try
                {
                    string comment = BuildComment(services);
                    if (comment.Length > 0)
                    {
                        Parameter cparam = instance.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
                        if (cparam != null && !cparam.IsReadOnly)
                        {
                            cparam.Set(comment);
                            notes.Add("comments: " + comment);
                        }
                    }
                }
                catch (Exception err)
                {
                    notes.Add("comments log failed: " + err.Message);
                }
            }
            if (options.Pin)
            {
                int pinned = services.Count(sv => !sv.Linked && PinElement(sv.Element));
                PinElement(instance);
                notes.Add("pinned " + pinned + " service" + (pinned == 1 ? "" : "s") + " and the opening");
            }

            try
            {
                var loc = instance.Location as LocationPoint;
                if (loc != null)
                    DebugLog("instance origin now " + F1(loc.Point.X) + ", " + F1(loc.Point.Y) + ", " + F1(loc.Point.Z) + " mm");
                BoundingBoxXYZ bb = instance.get_BoundingBox(null);
                if (bb != null)
                {
                    DebugLog("instance extent Z " + F1(bb.Min.Z) + " to " + F1(bb.Max.Z) + " mm (slab " + F1(geom.SlabBottom ?? 0) + " to " + F1(geom.SlabTop ?? 0) + ")");
                    double drift = Math.Abs(bb.Min.Z - geom.BaseWorld);
                    if (drift > MmToFt(1.0)) notes.Add("WARNING it settled " + F0(drift) + " mm off");
                    if (geom.SlabTop != null && geom.SlabBottom != null)
                        if (bb.Max.Z < geom.SlabBottom.Value - 1e-6 || bb.Min.Z > geom.SlabTop.Value + 1e-6) notes.Add("WARNING it does not reach the floor");
                }
            }
            catch (Exception) { }

            // does it actually enclose the services? checked in the opening's own frame
            try
            {
                var corners = new List<XYZ>();
                foreach (Service service in services) corners.AddRange(ServicePoints(service));
                BoundingBoxXYZ bb = instance.get_BoundingBox(null);
                if (corners.Count > 0 && bb != null)
                {
                    double midX = (bb.Min.X + bb.Max.X) / 2.0, midY = (bb.Min.Y + bb.Max.Y) / 2.0;
                    double angle = geom.Angle;
                    double cosA = Math.Cos(-angle), sinA = Math.Sin(-angle);
                    bool roundHole = geom.Circular;
                    double halfU = geom.Width / 2.0;
                    double halfV = roundHole ? halfU : geom.Length / 2.0;
                    double? worst = null;
                    foreach (XYZ corner in corners)
                    {
                        double dx = corner.X - midX, dy = corner.Y - midY;
                        double u = dx * cosA - dy * sinA, v = dx * sinA + dy * cosA;
                        double over = roundHole ? Math.Sqrt(u * u + v * v) - halfU : Math.Max(Math.Abs(u) - halfU, Math.Abs(v) - halfV);
                        worst = worst == null ? over : Math.Max(worst.Value, over);
                    }
                    if (worst != null && worst.Value > MmToFt(0.5))
                    {
                        notes.Add("WARNING the opening misses the services by up to " + F0(worst.Value) + " mm");
                        DebugLog("enclosure FAILED by " + F1(worst.Value) + " mm; opening " + F0(geom.Width) + " x " + F0(geom.Length) + " mm at "
                                 + (((angle * 180 / Math.PI) % 180.0 + 180.0) % 180.0).ToString("0.0") + " deg, centre " + F0(midX) + ", " + F0(midY));
                    }
                    else if (worst != null) DebugLog("encloses the services with " + F0(-worst.Value) + " mm to spare");
                }
            }
            catch (Exception) { }

            notes.Add("L " + F0(geom.Length) + " / W " + F0(geom.Width) + " mm at " + F0(geom.BaseWorld) + " mm");
            return instance;
        }

        /// <summary>The type to place, duplicated and sized when the size lives on type.</summary>
        public static FamilySymbol SlabSizedSymbol(Document doc, FamilySymbol symbol, SlabGeom geom, Dictionary<string, string> settings, List<string> notes)
        {
            if (!symbol.IsActive)
            {
                symbol.Activate();
                doc.Regenerate();
            }
            string lengthParam = BwicFamilies.Get(settings, "slab_length_param");
            if (lengthParam.Length == 0) lengthParam = "BGL_Height";
            string widthParam = BwicFamilies.Get(settings, "slab_width_param");
            if (widthParam.Length == 0) widthParam = "BGL_Width";
            bool typeSized = new[] { lengthParam, widthParam }.Any(n => HasLengthParam(symbol, n));
            if (!(typeSized && DuplicateTypeIfTypeParams)) return symbol;
            string newName = symbol.Name + "_L" + Math.Round(FtToMm(geom.Length)).ToString("0") + "_W" + Math.Round(FtToMm(geom.Width)).ToString("0");
            FamilySymbol existing = FindSymbolByName(doc, symbol.Family, newName);
            FamilySymbol placeSymbol = existing ?? (FamilySymbol)symbol.Duplicate(newName);
            if (!placeSymbol.IsActive) placeSymbol.Activate();
            doc.Regenerate();
            foreach (var pair in new[] { Tuple.Create(lengthParam, geom.Length), Tuple.Create(widthParam, geom.Width) })
            {
                if (HasLengthParam(placeSymbol, pair.Item1))
                {
                    string msg;
                    if (!SetLengthParam(placeSymbol, pair.Item1, pair.Item2, out msg)) notes.Add(msg);
                }
            }
            doc.Regenerate();
            notes.Add("sized on type \"" + newName + "\"");
            return placeSymbol;
        }

        /// <summary>Re-fit an existing slab opening to a fresh selection of services; the same code the placement runs.</summary>
        public static FamilyInstance ResizeSlabOne(Document doc, FamilyInstance instance, IList<Service> services, FamilySymbol symbol, SlabGeom geom,
                                                   Dictionary<string, string> settings, BwicOptions options, Workset workset, List<string> notes)
        {
            bool wasPinned = false;
            try
            {
                wasPinned = instance.Pinned;
                if (wasPinned)
                {
                    instance.Pinned = false;
                    notes.Add("unpinned to move it");
                }
            }
            catch (Exception) { }
            FamilySymbol placeSymbol = SlabSizedSymbol(doc, symbol, geom, settings, notes);
            if (placeSymbol.Id != instance.Symbol.Id)
            {
                string was = FamilyNameOf(instance.Symbol);
                try
                {
                    instance.Symbol = placeSymbol;
                    doc.Regenerate();
                    string now = FamilyNameOf(placeSymbol);
                    if (was != now) notes.Add("changed family from \"" + was + "\" to \"" + now + "\"");
                }
                catch (Exception err)
                {
                    notes.Add("could not change the type, so the existing one was kept: " + err.Message);
                }
            }
            ApplySlabToInstance(doc, instance, instance.Symbol, services, geom, settings, options, workset, notes);
            if (wasPinned && !options.Pin)
            {
                PinElement(instance);
                notes.Add("re-pinned");
            }
            return instance;
        }

        /// <summary>Place and size one slab penetration.</summary>
        public static FamilyInstance PlaceSlabOne(Document doc, IList<Service> services, Element slab, FamilySymbol symbol, SlabGeom geom,
                                                  Dictionary<string, string> settings, BwicOptions options, Workset workset, List<string> notes)
        {
            if (!symbol.IsActive)
            {
                symbol.Activate();
                doc.Regenerate();
            }
            FamilySymbol placeSymbol = SlabSizedSymbol(doc, symbol, geom, settings, notes);
            Level level = geom.Level;
            XYZ point = geom.Point;
            FamilyInstance instance = null;
            Element hostSlab = slab.Document.Equals(doc) ? slab : null;
            string kind;
            if (!settings.TryGetValue("slab_family_kind", out kind)) kind = "floor";

            if (kind == "floor" && hostSlab != null)
            {
                try { instance = doc.Create.NewFamilyInstance(point, placeSymbol, hostSlab, level, StructuralType.NonStructural); }
                catch (Exception) { }
            }
            if (instance == null)
            {
                try { instance = doc.Create.NewFamilyInstance(point, placeSymbol, level, StructuralType.NonStructural); }
                catch (Exception) { instance = doc.Create.NewFamilyInstance(point, placeSymbol, StructuralType.NonStructural); }
                if (kind == "floor")
                {
                    if (hostSlab == null) notes.Add("the floor is in a link, so the family is placed unhosted at the right level");
                    else notes.Add("could not host on the floor, placed unhosted");
                }
            }
            doc.Regenerate();
            return ApplySlabToInstance(doc, instance, placeSymbol, services, geom, settings, options, workset, notes);
        }

        private static double Num(Dictionary<string, string> settings, string key, double fallback)
        {
            string text = BwicFamilies.Get(settings, key).Trim();
            if (text.Length == 0) return fallback;
            double v;
            if (!double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out v)) throw new FormatException(key);
            return v;
        }

        /// <summary>Place slab openings, or re-fit an existing one to a new selection.</summary>
        public static void RunSlabLoop(UIApplication uiapp, Dictionary<string, string> settings, BwicOptions options, Action<string> report, string mode = "place")
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            if (uidoc == null)
            {
                report("No active Revit document.");
                return;
            }
            Document doc = uidoc.Document;
            bool resizing = mode == "resize";
            StartDebug(doc, "SLAB RUN (" + mode + ")", settings, options.ToDebug());

            string method = BwicFamilies.Get(settings, "slab_method");
            if (method.Length == 0) method = "auto";
            string rectName = BwicFamilies.Get(settings, "slab_family");
            string circName = BwicFamilies.Get(settings, "slab_circ_family");
            if (circName.Length == 0) circName = rectName;
            FamilySymbol rectSymbol = FindSlabSymbol(doc, rectName, BwicFamilies.Get(settings, "slab_type"));
            string circType = BwicFamilies.Get(settings, "slab_circ_type");
            if (circType.Length == 0) circType = BwicFamilies.Get(settings, "slab_type");
            FamilySymbol circSymbol = FindSlabSymbol(doc, circName, circType);
            if (rectSymbol != null && circSymbol == null && WantsCircular(rectName))
            {
                circSymbol = rectSymbol;
                rectSymbol = null;
            }
            if (rectSymbol == null && circSymbol == null)
            {
                DebugLog("neither family is loaded: rectangular \"" + rectName + "\", circular \"" + circName + "\"");
                DebugLog("generic models present:");
                foreach (GenericFamily gf in GenericModelFamilies(doc)) DebugLog("   " + gf.Name + " [" + gf.Label + "]");
                report("Choose a slab penetration family in Settings first.");
                return;
            }
            if (rectSymbol != null) DebugLog("rectangular family \"" + rectName + "\" type \"" + rectSymbol.Name + "\"");
            if (circSymbol != null) DebugLog("circular family \"" + circName + "\" type \"" + circSymbol.Name + "\"");
            DebugLog("method \"" + method + "\"");
            string datum = BwicFamilies.Get(settings, "slab_datum");
            if (datum.Length == 0) datum = "soffit";
            string rule = BwicFamilies.Get(settings, "slab_rule");
            if (rule.Length == 0) rule = "two_level";
            DebugLog("rule \"" + rule + "\", datum mode \"" + datum + "\"");

            double clearanceFt, baseExtraFt, topExtraFt, roundUpMm, heightExtraFt, topHeightExtraFt, circGapFt, circRoundMm, groupGapFt, pipeGapFt, angleTol;
            bool circInsulation;
            try
            {
                clearanceFt = MmToFt(BwicFamilies.DefaultClearanceMm);
                baseExtraFt = MmToFt(Num(settings, "slab_base_extra", 50));
                topExtraFt = MmToFt(Num(settings, "slab_top_extra", 100));
                roundUpMm = Num(settings, "slab_round_up", RoundUpMm);
                heightExtraFt = MmToFt(Num(settings, "slab_height_extra", 0));
                topHeightExtraFt = MmToFt(Num(settings, "slab_top_height_extra", 0));
                circGapFt = MmToFt(BwicFamilies.DefaultClearanceMm);
                circRoundMm = Num(settings, "slab_circular_round", 10);
                groupGapFt = MmToFt(Num(settings, "slab_group_gap", 100));
                circInsulation = BwicFamilies.Get(settings, "slab_circular_insulation") != "no";
                pipeGapFt = MmToFt(Num(settings, "slab_pipe_tray_gap", 150));
                angleTol = Num(settings, "slab_group_angle", 15);
            }
            catch (FormatException)
            {
                report("The slab round up and height figures must be numbers, in mm.");
                return;
            }
            DebugLog("round: OUTSIDE diameter" + (circInsulation ? " (insulation included)" : "") + " + " + F0(circGapFt) + " mm gap each side, rounded up to " + circRoundMm.ToString("0") + " mm");
            DebugLog("rect: the services plus " + F0(clearanceFt) + " mm each side, rounded up to " + roundUpMm.ToString("0") + " mm; trays and ducts within "
                     + F0(groupGapFt) + " mm share one; a pipe within " + F0(pipeGapFt) + " mm of one joins it");
            DebugLog("     trays only share an opening when they point within " + angleTol.ToString("0") + " deg of each other");

            Workset workset = null;
            if (!string.IsNullOrEmpty(options.WorksetName)) workset = FindWorksetByName(doc, options.WorksetName);

            List<Level> levels = SortedLevels(doc);
            if (levels.Count == 0)
            {
                report("This project has no levels.");
                return;
            }
            DebugLog(levels.Count + " level(s), lowest \"" + levels[0].Name + "\" at " + F0(LevelZ(levels[0])) + " mm, highest \"" + levels[levels.Count - 1].Name
                     + "\" at " + F0(LevelZ(levels[levels.Count - 1])) + " mm");

            bool includeLinked = options.IncludeLinked;
            var serviceFilter = new ServicePickFilter(doc, includeLinked);
            var slabFilter = new SlabPickFilter(doc);
            List<string> accepted = resizing ? ResizeFamilyNames() : new List<string> { rectName, circName };
            var bwicFilter = new BwicPickFilter(accepted);
            Dictionary<string, string> resizeValues = null;
            int placed = 0;
            string flow = resizing ? "slab_resize" : "slab_place";

            while (true)
            {
                FamilyInstance target = null;
                if (resizing)
                {
                    var chosen = uidoc.Selection.GetElementIds().Select(eid => doc.GetElement(eid)).Where(el => IsBwic(el, accepted)).ToList();
                    if (chosen.Count == 1)
                    {
                        target = chosen[0] as FamilyInstance;
                        DebugLog("resizing the pre-selected opening id " + EidValue(target.Id));
                    }
                    else
                    {
                        try
                        {
                            Guide("step", StepDict(flow, "opening"));
                            FocusRevit();
                            Reference r = uidoc.Selection.PickObject(ObjectType.Element, bwicFilter, "Pick the slab opening to resize  (Esc returns to the RevoBIM window)");
                            target = doc.GetElement(r.ElementId) as FamilyInstance;
                            DebugLog("resizing opening id " + EidValue(target.Id));
                        }
                        catch (OperationCanceledException) { break; }
                        catch (Exception err)
                        {
                            report("Opening pick failed: " + err.Message);
                            break;
                        }
                    }
                    EmptySelection(uidoc);
                }

                List<Service> services = PickServices(uidoc, doc, serviceFilter, includeLinked, flow, report);
                if (services == null || services.Count == 0) break;

                Reference slabRef;
                try
                {
                    FocusRevit();
                    Guide("step", StepDict(flow, "floor"));
                    slabRef = uidoc.Selection.PickObject(ObjectType.LinkedElement, slabFilter, "Click the floor the services pass through  (Esc returns to the RevoBIM window)");
                }
                catch (OperationCanceledException)
                {
                    EmptySelection(uidoc);
                    break;
                }
                catch (Exception err)
                {
                    report("Floor pick failed: " + err.Message);
                    break;
                }

                double? pickZ = null;
                try
                {
                    if (slabRef.GlobalPoint != null)
                    {
                        pickZ = slabRef.GlobalPoint.Z;
                        DebugLog("click point Z " + F1(pickZ.Value) + " mm (host coordinates)");
                    }
                }
                catch (Exception)
                {
                    DebugLog("the pick gave no global point, falling back to the bounding box");
                }
                if (pickZ != null)
                {
                    CalibrateLevels(levels, pickZ);
                    levels = SortedLevels(doc);
                    DebugLog("levels now: lowest \"" + levels[0].Name + "\" at " + F0(LevelZ(levels[0])) + " mm, highest \"" + levels[levels.Count - 1].Name
                             + "\" at " + F0(LevelZ(levels[levels.Count - 1])) + " mm");
                }

                Element picked = doc.GetElement(slabRef.ElementId);
                Transform transform = Transform.Identity;
                Element slab;
                var linkInst = picked as RevitLinkInstance;
                if (linkInst != null)
                {
                    Document linkDoc = linkInst.GetLinkDocument();
                    if (linkDoc == null)
                    {
                        report("That link is not loaded.");
                        continue;
                    }
                    slab = linkDoc.GetElement(slabRef.LinkedElementId);
                    transform = linkInst.GetTotalTransform();
                    DebugLog("floor picked in link \"" + linkInst.Name + "\"");
                    try
                    {
                        XYZ o = transform.Origin;
                        DebugLog("link transform origin " + F1(o.X) + ", " + F1(o.Y) + ", " + F1(o.Z) + " mm");
                    }
                    catch (Exception) { }
                }
                else
                {
                    slab = picked;
                    DebugLog("floor picked in the host model");
                }
                DebugLog(services.Count + " service(s) selected");
                foreach (Service sv in services)
                {
                    try { DebugLog("   " + DescribeElement(sv.Element) + " id " + EidValue(sv.Element.Id) + " " + (sv.Linked ? "(linked)" : "")); }
                    catch (Exception) { }
                }
                if (!IsSlab(slab))
                {
                    report("That is not a floor - try again.");
                    continue;
                }

                List<BwicJob> jobs;
                if (resizing)
                {
                    var rs = ResizeSettings(target, "slab");
                    resizeValues = rs.Item2;
                    string shape = rs.Item1 == "slab_circ" ? "round" : "rect";
                    jobs = new List<BwicJob> { new BwicJob(shape, services) };
                    DebugLog("resizing to a " + (shape == "round" ? "circular" : "rectangular") + " opening around " + services.Count + " service(s)");
                }
                else jobs = BuildJobs(services, groupGapFt, pipeGapFt, method, angleTol);
                if (jobs.Count == 0)
                {
                    report("Nothing to place from that selection.");
                    continue;
                }

                Level planLevel = ViewLevel(uidoc.ActiveView);
                DebugLog(jobs.Count + " job(s) to place");
                var group = new TransactionGroup(doc, resizing ? "Resize slab penetration" : "Place slab penetrations");
                group.Start();
                int made = 0, failed = 0;
                var seen = new List<string>();
                Dictionary<string, object> profiles = LoadProfiles();

                for (int index = 0; index < jobs.Count; index++)
                {
                    string shape = jobs[index].Shape;
                    List<Service> job = jobs[index].Services;
                    FamilySymbol symbol = shape == "round" ? circSymbol : rectSymbol;
                    if (symbol == null)
                    {
                        DebugLog("job " + (index + 1) + ": no " + (shape == "round" ? "circular" : "rectangular") + " family set, skipped");
                        failed++;
                        continue;
                    }
                    using (var trans = new Transaction(doc, resizing ? "Resize slab penetration" : "Place slab penetration"))
                    {
                        string jobFamily = FamilyNameOf(symbol);
                        double jobClearanceFt = MmToFt(FamilyClearanceMm(jobFamily, FtToMm(clearanceFt), profiles));
                        double jobGapFt = MmToFt(FamilyClearanceMm(jobFamily, FtToMm(circGapFt), profiles));
                        try
                        {
                            double? overridePlan = null;
                            if (shape == "round")
                            {
                                string note;
                                overridePlan = CircularSize(job[0], jobGapFt, circRoundMm, circInsulation, out note);
                                if (overridePlan == null)
                                {
                                    DebugLog("job " + (index + 1) + ": skipped - " + note);
                                    failed++;
                                    continue;
                                }
                                if (!string.IsNullOrEmpty(note)) DebugLog("job " + (index + 1) + ": " + note);
                            }
                            string error;
                            SlabGeom geom = ComputeSlabBwic(doc, job, slab, transform, jobClearanceFt, baseExtraFt, topExtraFt, levels, datum, pickZ, rule,
                                                            roundUpMm, heightExtraFt, topHeightExtraFt, planLevel, overridePlan, out error);
                            if (geom == null)
                            {
                                DebugLog("job " + (index + 1) + ": compute failed - " + error);
                                failed++;
                                continue;
                            }
                            string key = Math.Round(FtToMm(geom.Point.X), 1) + "|" + Math.Round(FtToMm(geom.Point.Y), 1) + "|" + Math.Round(FtToMm(geom.Width), 1) + "|" + shape;
                            if (seen.Contains(key) && !resizing)
                            {
                                DebugLog("job " + (index + 1) + ": duplicate of one already placed at " + F0(geom.Point.X) + ", " + F0(geom.Point.Y) + " - skipped");
                                continue;
                            }
                            seen.Add(key);
                            geom.Circular = shape == "round";
                            Dictionary<string, string> jobSettings;
                            if (resizing && resizeValues != null)
                            {
                                symbol = target.Symbol;
                                jobSettings = new Dictionary<string, string>(settings);
                                foreach (var kv in resizeValues) jobSettings[kv.Key] = kv.Value;
                            }
                            else jobSettings = SlabJobSettings(settings, shape, symbol, profiles);
                            trans.Start();
                            Quieten(trans);
                            var notes = new List<string>();
                            FamilyInstance instance = resizing
                                ? ResizeSlabOne(doc, target, job, symbol, geom, jobSettings, options, workset, notes)
                                : PlaceSlabOne(doc, job, slab, symbol, geom, jobSettings, options, workset, notes);
                            if (instance == null)
                            {
                                trans.RollBack();
                                DebugLog("job " + (index + 1) + ": nothing placed - " + string.Join("; ", notes));
                                failed++;
                                continue;
                            }
                            trans.Commit();
                            made++;
                            DebugLog("job " + (index + 1) + " (" + shape + ", " + job.Count + " service(s)): placed id " + EidValue(instance.Id) + " : " + string.Join("; ", notes));
                            report((resizing ? "Resized" : made + " of " + jobs.Count + " placed") + " - " + string.Join("; ", notes));
                        }
                        catch (Exception err)
                        {
                            if (trans.HasStarted()) trans.RollBack();
                            failed++;
                            DebugLog("job " + (index + 1) + ": EXCEPTION\n" + err);
                        }
                    }
                }

                if (made > 0)
                {
                    group.Assimilate();
                    placed += made;
                    report(made + " opening" + (made == 1 ? "" : "s") + " " + (resizing ? "resized" : "placed") + (failed > 0 ? ", " + failed + " skipped" : "") + ".");
                    Guide("placed", Msg(resizing ? "BWIC resized" : (made == 1 ? "BWIC placed" : made + " BWICs placed"),
                                        (failed > 0 ? failed + " skipped. " : "") + "Carry on with the next one, or press Esc to stop."));
                }
                else
                {
                    group.RollBack();
                    report("Nothing " + (resizing ? "resized" : "placed") + " - see the debug log.");
                    Guide("problem", Msg("Nothing placed", "Nothing could be placed from that selection. The status line says why."));
                }
                EmptySelection(uidoc);
            }
            Guide("done");
            report("Finished - " + placed + " slab opening" + (placed == 1 ? "" : "s") + " " + (resizing ? "resized" : "placed") + " this run.");
        }
    }
}
