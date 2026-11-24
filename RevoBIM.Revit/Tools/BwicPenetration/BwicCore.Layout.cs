using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.BwicPenetration
{
    /// <summary>One opening to make: its shape ("rect" or "round") and the services it takes.</summary>
    public sealed class BwicJob
    {
        public string Shape;
        public List<Service> Services;
        public BwicJob(string shape, List<Service> services) { Shape = shape; Services = services; }
    }

    /// <summary>Tightest rectangle around plan points: angle, width across, depth along, centre.</summary>
    public struct PlanRect
    {
        public double Angle, Width, Depth, CentreX, CentreY;
    }

    public static partial class BwicCore
    {
        public static double ServiceDiameterFt(Service service)
        {
            // Outer diameter of a round service, insulation included; 0 for anything that is not round.
            double[] section = CrossSection(service.Element);
            if (section == null) return 0.0;
            if (Math.Abs(section[0] - section[1]) > MmToFt(0.5)) return 0.0;
            return section[0] * 2.0;
        }

        public static double InsulationThickness(Element element)
        {
            return ParamDouble(element, new[] { "Insulation Thickness" },
                new[] { "RBS_REFERENCE_INSULATION_THICKNESS", "RBS_INSULATION_THICKNESS_FOR_DUCT", "RBS_PIPE_INSULATION_THICKNESS" });
        }

        /// <summary>(hole diameter or null, note) for one service, set out from its OUTSIDE diameter plus the gap each side.</summary>
        public static double? CircularSize(Service service, double gapFt, double roundMm, bool includeInsulation, out string note)
        {
            Element element = service.Element;
            string source;
            bool isOuter;
            double diameter = OutsideDiameter(element, out source, out isOuter);
            if (diameter <= 0)
            {
                List<XYZ> points = ServicePoints(service);
                if (points.Count == 0)
                {
                    note = "no geometry to measure";
                    return null;
                }
                double span = Math.Max(points.Max(p => p.X) - points.Min(p => p.X), points.Max(p => p.Y) - points.Min(p => p.Y));
                double h = RoundUpFt(span + 2 * gapFt, roundMm);
                DebugLog("   " + DescribeElement(element) + ": no diameter, widest plan dimension " + FtToMm(span).ToString("0.0")
                         + " mm -> hole " + FtToMm(h).ToString("0") + " mm");
                note = "no diameter parameter, sized on its widest plan dimension";
                return h;
            }
            note = null;
            if (!isOuter) note = "\"" + source + "\" is the nominal size, not the outside diameter - the hole may be tight";
            double outer = diameter;
            double insulation = includeInsulation ? InsulationThickness(element) : 0.0;
            if (insulation > 1e-9) outer += 2 * insulation;
            double hole = RoundUpFt(outer + 2 * gapFt, roundMm);
            DebugLog("   " + DescribeElement(element) + ": " + source + " = " + FtToMm(diameter).ToString("0.0") + " mm"
                     + (insulation > 1e-9 ? " + insulation " + FtToMm(insulation).ToString("0") + " x2" : "")
                     + " + gap " + FtToMm(gapFt).ToString("0") + " x2 -> hole " + FtToMm(hole).ToString("0") + " mm");
            return hole;
        }

        /// <summary>(xmin, xmax, ymin, ymax) of a service in plan, host coordinates; null with no geometry.</summary>
        public static double[] PlanBounds(Service service)
        {
            List<XYZ> points = ServicePoints(service);
            if (points.Count == 0) return null;
            return new[] { points.Min(p => p.X), points.Max(p => p.X), points.Min(p => p.Y), points.Max(p => p.Y) };
        }

        /// <summary>Andrew's monotone chain, on (x, y) tuples.</summary>
        public static List<Tuple<double, double>> ConvexHull(IEnumerable<Tuple<double, double>> input)
        {
            var points = input.Distinct().OrderBy(p => p.Item1).ThenBy(p => p.Item2).ToList();
            if (points.Count < 3) return points;
            Func<Tuple<double, double>, Tuple<double, double>, Tuple<double, double>, double> cross =
                (o, a, b) => (a.Item1 - o.Item1) * (b.Item2 - o.Item2) - (a.Item2 - o.Item2) * (b.Item1 - o.Item1);
            Func<IEnumerable<Tuple<double, double>>, List<Tuple<double, double>>> half = sequence =>
            {
                var output = new List<Tuple<double, double>>();
                foreach (var point in sequence)
                {
                    while (output.Count >= 2 && cross(output[output.Count - 2], output[output.Count - 1], point) <= 0)
                        output.RemoveAt(output.Count - 1);
                    output.Add(point);
                }
                return output;
            };
            List<Tuple<double, double>> lower = half(points);
            List<Tuple<double, double>> upper = half(Enumerable.Reverse(points));
            lower.RemoveAt(lower.Count - 1);
            upper.RemoveAt(upper.Count - 1);
            lower.AddRange(upper);
            return lower;
        }

        /// <summary>The tightest rectangle around some plan points, at any angle (it sits on one of the hull's edges).</summary>
        public static PlanRect MinAreaRect(IList<Tuple<double, double>> points)
        {
            if (points.Count == 0) return new PlanRect();
            Func<PlanRect> axisAligned = () =>
            {
                double minX = points.Min(p => p.Item1), maxX = points.Max(p => p.Item1);
                double minY = points.Min(p => p.Item2), maxY = points.Max(p => p.Item2);
                return new PlanRect { Angle = 0.0, Width = maxX - minX, Depth = maxY - minY, CentreX = (minX + maxX) / 2.0, CentreY = (minY + maxY) / 2.0 };
            };
            List<Tuple<double, double>> hull = ConvexHull(points);
            if (hull.Count < 3) return axisAligned();
            bool have = false;
            double bestArea = 0;
            PlanRect best = new PlanRect();
            for (int index = 0; index < hull.Count; index++)
            {
                double x0 = hull[index].Item1, y0 = hull[index].Item2;
                double x1 = hull[(index + 1) % hull.Count].Item1, y1 = hull[(index + 1) % hull.Count].Item2;
                if (Math.Abs(x1 - x0) < 1e-12 && Math.Abs(y1 - y0) < 1e-12) continue;
                double angle = Math.Atan2(y1 - y0, x1 - x0);
                double cosA = Math.Cos(-angle), sinA = Math.Sin(-angle);
                double minU = double.MaxValue, maxU = double.MinValue, minV = double.MaxValue, maxV = double.MinValue;
                foreach (var p in hull)
                {
                    double u = p.Item1 * cosA - p.Item2 * sinA;
                    double v = p.Item1 * sinA + p.Item2 * cosA;
                    minU = Math.Min(minU, u); maxU = Math.Max(maxU, u);
                    minV = Math.Min(minV, v); maxV = Math.Max(maxV, v);
                }
                double width = maxU - minU, depth = maxV - minV, area = width * depth;
                if (!have || area < bestArea - 1e-12)
                {
                    double midU = (minU + maxU) / 2.0, midV = (minV + maxV) / 2.0;
                    best = new PlanRect
                    {
                        Angle = angle, Width = width, Depth = depth,
                        CentreX = midU * Math.Cos(angle) - midV * Math.Sin(angle),
                        CentreY = midU * Math.Sin(angle) + midV * Math.Cos(angle),
                    };
                    bestArea = area;
                    have = true;
                }
            }
            return have ? best : axisAligned();
        }

        public static double BoxGap(double[] a, double[] b)
        {
            double dx = Math.Max(0.0, Math.Max(a[0] - b[1], b[0] - a[1]));
            double dy = Math.Max(0.0, Math.Max(a[2] - b[3], b[2] - a[3]));
            return Math.Sqrt(dx * dx + dy * dy);
        }

        public static bool BoxesWithin(double[] a, double[] b, double gap) { return BoxGap(a, b) <= gap; }

        /// <summary>How a service is turned in plan, in degrees 0 to 180 (its long axis); null without geometry.</summary>
        public static double? ServiceAngle(Service service)
        {
            List<XYZ> points = ServicePoints(service);
            if (points.Count == 0) return null;
            PlanRect r = MinAreaRect(points.Select(p => Tuple.Create(p.X, p.Y)).ToList());
            double angle = r.Angle;
            if (r.Width < r.Depth) angle += Math.PI / 2.0;
            double deg = angle * 180.0 / Math.PI;
            return ((deg % 180.0) + 180.0) % 180.0;
        }

        public static bool AnglesAlign(double? a, double? b, double tolerance)
        {
            if (a == null || b == null) return true;
            double difference = Math.Abs(a.Value - b.Value) % 180.0;
            return Math.Min(difference, 180.0 - difference) <= tolerance;
        }

        /// <summary>Group services that sit within gap of each other in plan (transitively); angleTol null ignores orientation.</summary>
        public static List<List<Service>> ClusterServices(IList<Service> services, double gapFt, double? angleTol = null)
        {
            var boxes = new List<double[]>();
            var keep = new List<Service>();
            foreach (Service service in services)
            {
                double[] box = PlanBounds(service);
                if (box == null) continue;
                boxes.Add(box);
                keep.Add(service);
            }
            if (keep.Count == 0) return new List<List<Service>>();
            var parent = Enumerable.Range(0, keep.Count).ToArray();
            Func<int, int> find = null;
            find = i =>
            {
                while (parent[i] != i)
                {
                    parent[i] = parent[parent[i]];
                    i = parent[i];
                }
                return i;
            };
            Action<int, int> union = (i, j) =>
            {
                int ri = find(i), rj = find(j);
                if (ri != rj) parent[rj] = ri;
            };
            var angles = new List<double?>();
            foreach (Service sv in keep) angles.Add(angleTol != null ? ServiceAngle(sv) : null);
            for (int i = 0; i < keep.Count; i++)
                for (int j = i + 1; j < keep.Count; j++)
                {
                    if (!BoxesWithin(boxes[i], boxes[j], gapFt)) continue;
                    if (angleTol != null && !AnglesAlign(angles[i], angles[j], angleTol.Value))
                    {
                        DebugLog("   " + DescribeElement(keep[i].Element) + " and " + DescribeElement(keep[j].Element)
                                 + " are close but " + (angles[i] ?? 0).ToString("0") + " and " + (angles[j] ?? 0).ToString("0")
                                 + " deg apart, so they keep separate openings");
                        continue;
                    }
                    union(i, j);
                }
            var groups = new Dictionary<int, List<Service>>();
            var order = new List<int>();
            for (int index = 0; index < keep.Count; index++)
            {
                int root = find(index);
                if (!groups.ContainsKey(root))
                {
                    groups[root] = new List<Service>();
                    order.Add(root);
                }
                groups[root].Add(keep[index]);
            }
            var ordered = order.Select(r => groups[r])
                .OrderBy(g => g.Min(s => PlanBounds(s)[0])).ThenBy(g => g.Min(s => PlanBounds(s)[2])).ToList();
            DebugLog(keep.Count + " service(s) grouped into " + ordered.Count + " opening(s) at " + FtToMm(gapFt).ToString("0") + " mm");
            return ordered;
        }

        // ---------------------------------------------------------------- level elevations

        /// <summary>Which elevation property matches the geometry ("Elevation" or "ProjectElevation"), decided by measurement.</summary>
        public static string LevelZProp = null;

        private static double? LevelProp(Level level, string prop)
        {
            try
            {
                if (prop == "Elevation") return level.Elevation;
                return level.ProjectElevation;
            }
            catch (Exception) { return null; }
        }

        /// <summary>A level's elevation in the SAME space as element geometry.</summary>
        public static double LevelZ(Level level)
        {
            string[] props = LevelZProp != null ? new[] { LevelZProp } : new[] { "Elevation", "ProjectElevation" };
            foreach (string prop in props)
            {
                double? value = LevelProp(level, prop);
                if (value != null) return value.Value;
            }
            return 0.0;
        }

        /// <summary>Pick the elevation property that puts a level closest to a point known to be in internal coordinates.</summary>
        public static void CalibrateLevels(IList<Level> levels, double? referenceZ)
        {
            LevelZProp = null;
            if (levels == null || levels.Count == 0 || referenceZ == null) return;
            string best = null;
            double bestGap = 0;
            foreach (string prop in new[] { "Elevation", "ProjectElevation" })
            {
                var values = new List<double>();
                foreach (Level level in levels)
                {
                    double? v = LevelProp(level, prop);
                    if (v != null) values.Add(v.Value);
                }
                if (values.Count == 0) continue;
                double gap = values.Min(v => Math.Abs(v - referenceZ.Value));
                DebugLog("level property \"" + prop + "\": nearest is " + FtToMm(gap).ToString("0") + " mm from the floor");
                if (best == null || gap < bestGap)
                {
                    best = prop;
                    bestGap = gap;
                }
            }
            if (best != null)
            {
                LevelZProp = best;
                DebugLog("using \"" + LevelZProp + "\" for level elevations");
            }
        }

        /// <summary>Decide what gets its own opening and what shares one. method: auto, circular or rectangular.</summary>
        public static List<BwicJob> BuildJobs(IList<Service> services, double groupGapFt, double pipeGapFt, string method = "auto",
                                              double angleTol = 15.0)
        {
            if (method == "circular") return services.Select(sv => new BwicJob("round", new List<Service> { sv })).ToList();
            List<Service> rect = services.Where(sv => ServiceShape(sv) == "rect").ToList();
            List<Service> round = services.Where(sv => ServiceShape(sv) != "rect").ToList();
            if (method == "rectangular")
            {
                rect = services.ToList();
                round = new List<Service>();
            }
            List<List<Service>> groups = rect.Count > 0 ? ClusterServices(rect, groupGapFt, angleTol).Select(g => g.ToList()).ToList()
                                                         : new List<List<Service>>();
            var loose = new List<Service>();
            foreach (Service service in round)
            {
                double[] box = PlanBounds(service);
                if (box == null) continue;
                int joined = -1;
                double best = double.MaxValue;
                for (int index = 0; index < groups.Count; index++)
                    foreach (Service member in groups[index])
                    {
                        double[] other = PlanBounds(member);
                        if (other == null) continue;
                        double gap = BoxGap(box, other);
                        if (gap <= pipeGapFt && (joined < 0 || gap < best))
                        {
                            best = gap;
                            joined = index;
                        }
                    }
                if (joined < 0) loose.Add(service);
                else
                {
                    groups[joined].Add(service);
                    DebugLog("   " + DescribeElement(service.Element) + " joins a rectangular opening (" + FtToMm(best).ToString("0") + " mm from it)");
                }
            }
            var jobs = groups.Select(g => new BwicJob("rect", g)).ToList();
            jobs.AddRange(loose.Select(s => new BwicJob("round", new List<Service> { s })));
            DebugLog(groups.Count + " rectangular opening(s), " + loose.Count + " circular");
            return jobs;
        }

        /// <summary>Settings for one slab opening, with its own family's profile.</summary>
        public static Dictionary<string, string> SlabJobSettings(Dictionary<string, string> settings, string shape, FamilySymbol symbol,
                                                                 Dictionary<string, object> profiles)
        {
            string slot = shape == "round" ? "slab_circ" : "slab_rect";
            var values = new Dictionary<string, string>(settings);
            string name = FamilyNameOf(symbol);
            if (!string.IsNullOrEmpty(name)) values[BwicFamilies.SlotFamilyKey(slot)] = name;
            return BwicFamilies.Overlay(values, slot, profiles);
        }

        public static Level NearestLevel(IList<Level> levels, double elevation)
        {
            if (levels == null || levels.Count == 0) return null;
            return levels.OrderBy(l => Math.Abs(LevelZ(l) - elevation)).First();
        }

        private static List<BuiltInParameter> LevelParamIds()
        {
            var found = new List<BuiltInParameter>();
            foreach (string name in new[] { "FAMILY_LEVEL_PARAM", "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM", "INSTANCE_REFERENCE_LEVEL_PARAM",
                                            "SCHEDULE_LEVEL_PARAM", "FAMILY_BASE_LEVEL_PARAM" })
            {
                BuiltInParameter bip;
                if (Enum.TryParse(name, out bip)) found.Add(bip);
            }
            return found;
        }

        /// <summary>The level the instance is actually associated with, or null.</summary>
        public static Level GetInstanceLevel(Document doc, Element instance)
        {
            foreach (BuiltInParameter bip in LevelParamIds())
            {
                try
                {
                    Parameter param = instance.get_Parameter(bip);
                    if (param == null || param.StorageType != StorageType.ElementId) continue;
                    var level = doc.GetElement(param.AsElementId()) as Level;
                    if (level != null) return level;
                }
                catch (Exception) { }
            }
            return null;
        }

        /// <summary>Point the instance at a level: every writable level parameter is set, not just the first.</summary>
        public static bool SetInstanceLevel(Document doc, Element instance, Level level)
        {
            bool changed = false;
            foreach (BuiltInParameter bip in LevelParamIds())
            {
                try
                {
                    Parameter param = instance.get_Parameter(bip);
                    if (param == null || param.IsReadOnly) continue;
                    if (param.StorageType != StorageType.ElementId) continue;
                    param.Set(level.Id);
                    changed = true;
                }
                catch (Exception) { }
            }
            return changed;
        }

        /// <summary>Two character code for a level: Level 03 -> 03, Roof -> RF, any number, else its position from the lowest.</summary>
        public static string LevelCode(Level level, IList<Level> levels)
        {
            string name = (level.Name ?? "").ToUpperInvariant();
            Match numbered = Regex.Match(name, @"LEVEL\s*[-_]?\s*(\d+)");
            if (numbered.Success) return (long.Parse(numbered.Groups[1].Value) % 100).ToString("00");
            foreach (string[] rule in LevelCodeRules)
                if (name.Contains(rule[0].ToUpperInvariant())) return rule[1];
            Match digits = Regex.Match(name, @"\d+");
            if (digits.Success) return (long.Parse(digits.Value) % 100).ToString("00");
            int index = 0;
            for (int i = 0; i < levels.Count; i++)
                if (levels[i].Id == level.Id) { index = i; break; }
            return (index % 100).ToString("00");
        }

        /// <summary>Write the code into the chosen parameter, matching its storage type.</summary>
        public static bool SetLevelCode(Element element, string paramName, string code, out string error)
        {
            error = null;
            Parameter param = element.LookupParameter(paramName);
            if (param == null) { error = "parameter \"" + paramName + "\" not on the family"; return false; }
            if (param.IsReadOnly) { error = "\"" + paramName + "\" is read only"; return false; }
            try
            {
                if (param.StorageType == StorageType.String) param.Set(code);
                else if (param.StorageType == StorageType.Integer) param.Set(int.Parse(code));
                else if (param.StorageType == StorageType.Double) param.Set(double.Parse(code, System.Globalization.CultureInfo.InvariantCulture));
                else { error = "\"" + paramName + "\" cannot hold the level code"; return false; }
            }
            catch (Exception err)
            {
                error = "\"" + paramName + "\" not set: " + err.Message;
                return false;
            }
            return true;
        }

        /// <summary>Writable text/number parameters the BWIC family can carry.</summary>
        public static List<string> CollectParameterNames(Document doc, FamilySymbol symbol)
        {
            var names = new HashSet<string>();
            Action<Element> harvest = element =>
            {
                foreach (Parameter param in element.Parameters)
                {
                    try
                    {
                        if (param.IsReadOnly) continue;
                        if (param.StorageType != StorageType.String && param.StorageType != StorageType.Integer
                            && param.StorageType != StorageType.Double) continue;
                        names.Add(param.Definition.Name);
                    }
                    catch (Exception) { }
                }
            };
            foreach (FamilyInstance inst in new FilteredElementCollector(doc).OfClass(typeof(FamilyInstance)).WhereElementIsNotElementType())
            {
                try
                {
                    if (inst.Symbol != null && inst.Symbol.Family.Name == FamilyName)
                    {
                        harvest(inst);
                        break;
                    }
                }
                catch (Exception) { }
            }
            if (symbol != null)
            {
                harvest(symbol);
                try
                {
                    Category category = symbol.Category;
                    DefinitionBindingMapIterator iterator = doc.ParameterBindings.ForwardIterator();
                    iterator.Reset();
                    while (iterator.MoveNext())
                    {
                        var binding = iterator.Current as InstanceBinding;
                        if (binding != null && binding.Categories.Contains(category)) names.Add(iterator.Key.Name);
                    }
                }
                catch (Exception) { }
            }
            names.Add(LevelParamName);
            return names.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        public static string DefaultLevelParam(IEnumerable<string> names)
        {
            var list = names.ToList();
            foreach (string name in list) if (name == LevelParamName) return name;
            foreach (string name in list) if (name.ToLowerInvariant().Contains(LevelParamKeyword.ToLowerInvariant())) return name;
            return null;
        }

        // ---------------------------------------------------------------- worksets and pinning

        public static List<Workset> ListWorksets(Document doc)
        {
            if (!doc.IsWorkshared) return new List<Workset>();
            try
            {
                return new FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset).ToList()
                    .OrderBy(w => w.Name.ToLowerInvariant(), StringComparer.Ordinal).ToList();
            }
            catch (Exception) { return new List<Workset>(); }
        }

        public static Workset FindWorksetByName(Document doc, string name)
        {
            foreach (Workset w in ListWorksets(doc)) if (w.Name == name) return w;
            return null;
        }

        public static bool AssignWorkset(Element element, Workset workset)
        {
            Parameter param = element.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM);
            if (param == null || param.IsReadOnly) return false;
            param.Set(workset.Id.IntegerValue);
            return true;
        }

        /// <summary>The clearance each side for a family: its own (Family settings), or the tab's when it has none.</summary>
        public static double FamilyClearanceMm(string family, double defaultMm = BwicFamilies.DefaultClearanceMm, Dictionary<string, object> profiles = null)
        {
            if (profiles == null) profiles = LoadProfiles();
            double value = BwicFamilies.ClearanceFor(family, profiles, defaultMm);
            DebugLog("clearance for " + family + ": " + BwicFamilies.G(value) + " mm ("
                     + (value != defaultMm || BwicFamilies.FamilyClearance(family, profiles) != null ? "family settings" : "the tab") + ")");
            return value;
        }

        /// <summary>Put a placed or resized BWIC on its workset (the family's own choice wins, else the Settings one).</summary>
        public static void PlaceOnWorkset(Document doc, Element instance, BwicOptions options, Workset workset,
                                          List<string> notes, Dictionary<string, object> profiles = null)
        {
            if (!doc.IsWorkshared) return;
            string family;
            try { family = FamilyNameOf((instance as FamilyInstance).Symbol); }
            catch (Exception) { family = ""; }
            if (profiles == null) profiles = LoadProfiles();
            string choice = BwicFamilies.FamilyWorkset(family, profiles);
            string settingsName = options.WorksetName ?? "";
            string name = BwicFamilies.WorksetChoice(choice, settingsName);
            DebugLog("workset for " + family + ": family says \"" + choice + "\", Settings \"" + settingsName + "\" -> " + (name ?? "active"));
            if (string.IsNullOrEmpty(name)) return;
            if (workset == null || workset.Name != name) workset = FindWorksetByName(doc, name);
            if (workset == null) notes.Add("workset \"" + name + "\" not found");
            else if (AssignWorkset(instance, workset)) notes.Add("workset \"" + workset.Name + "\"");
            else notes.Add("could not set the workset");
        }

        public static bool PinElement(Element element)
        {
            try
            {
                if (!element.Pinned) element.Pinned = true;
                return true;
            }
            catch (Exception) { return false; }
        }

        // ---------------------------------------------------------------- Comments logging

        /// <summary>"Family: Type" for a loadable family, "Category: Type" otherwise; null when unreadable.</summary>
        public static string DescribeElement(Element element)
        {
            Document doc = element.Document;
            try
            {
                string famName, typeName;
                var fi = element as FamilyInstance;
                if (fi != null && fi.Symbol != null)
                {
                    famName = fi.Symbol.Family.Name;
                    typeName = fi.Symbol.Name;
                }
                else
                {
                    Element etype = doc.GetElement(element.GetTypeId());
                    typeName = etype != null ? etype.Name : "<no type>";
                    famName = element.Category != null ? element.Category.Name : element.GetType().Name;
                }
                return famName + ": " + typeName;
            }
            catch (Exception) { return null; }
        }

        /// <summary>Summarise the selected services: "Pipe Types: Standard x3_Duct: Rect x2".</summary>
        public static string BuildComment(IEnumerable<Service> services)
        {
            var order = new List<string>();
            var counts = new Dictionary<string, int>();
            foreach (Service service in services)
            {
                string key = DescribeElement(service.Element);
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

        public static double Spread(IEnumerable<XYZ> points, XYZ along)
        {
            var values = points.Select(p => p.X * along.X + p.Y * along.Y).ToList();
            return values.Max() - values.Min();
        }

        public static double SpreadZ(IEnumerable<XYZ> points)
        {
            var values = points.Select(p => p.Z).ToList();
            return values.Max() - values.Min();
        }
    }
}
