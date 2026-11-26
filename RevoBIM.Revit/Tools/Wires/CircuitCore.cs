using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;
using RevoBIM.Helpers;

using Wire = Autodesk.Revit.DB.Electrical.Wire;

namespace RevoBIM.Tools.Wires
{
    /// <summary>A circuit member drawn in the view and where it sits.</summary>
    public sealed class Member
    {
        public Element Element;
        public XYZ Point;
    }

    /// <summary>One circuit, its members in this view, and what was found about it.</summary>
    public sealed class CircuitJob
    {
        public ElectricalSystem Circuit;
        public string Label;
        public List<Member> Members = new List<Member>();
        public int Offscreen;
        public List<Wire> ExistingWires = new List<Wire>();
        public string SwitchKey = "";
        public Element SwitchElement;
        public XYZ SwitchPoint;
        public Element SwitchFrom;       // the light the switch is connected to
        public string SwitchRoute = "";  // how the switch was found
        public bool IsLighting = true;

        public CircuitJob(ElectricalSystem circuit)
        {
            Circuit = circuit;
            Label = WiresModel.CircuitLabel(circuit);
        }
    }

    /// <summary>What one run of one circuit produced, so Shuffle can replace it.</summary>
    public sealed class Placement
    {
        public CircuitJob Job;
        public List<Wire> Wires = new List<Wire>();
        public List<Element> Extras = new List<Element>();   // detail lines and anything else drawn
        public Element Tag;
        public List<string> Info = new List<string>();       // said for the record, never a dialog
        public int Variant, Options = 1, Flipped, Clashing;
        public List<string> Notes = new List<string>();
        public double Length;

        public Placement(CircuitJob job)
        {
            Job = job;
        }
    }

    /// <summary>A fitting drawn in the view that a wire has to keep clear of.</summary>
    public sealed class Obstacle
    {
        public long Eid;
        public double X, Y, Radius;
    }

    /// <summary>
    /// Wires: circuits (circuit_core.py, first half). Finds circuited fittings in the active view, works out the order to run the wires in, draws them as arcs
    /// between fitting centres, points the home run at the switch where there is one, and tags one wire per circuit.
    /// </summary>
    public static class CircuitCore
    {
        // ------------------------------------------------------------------ switch systems
        private static readonly string[] SwitchParamNames = { "Switch ID", "Switch Id", "SwitchID", "BGL_Switch ID" };

        /// <summary>
        /// The switch system a fitting belongs to, as a string key: a switch-typed electrical system it is a member of, the built-in Switch ID parameter, or a
        /// parameter called Switch ID by any of its usual spellings. An empty string means the fitting is on no switch system, which is its own group.
        /// </summary>
        public static string SwitchIdOf(Element element)
        {
            ElectricalSystemType switchKind;
            if (Enum.TryParse("Switch", out switchKind))
            {
                foreach (ElectricalSystem circuit in WiresModel.ElementCircuits(element))
                {
                    try
                    {
                        if (circuit.SystemType == switchKind) return "sys:" + circuit.Id.Value;
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            try
            {
                BuiltInParameter bip;
                if (Enum.TryParse("RBS_ELEC_SWITCH_ID_PARAM", out bip))
                {
                    Parameter param = element.get_Parameter(bip);
                    if (param != null)
                    {
                        string value = param.AsString();
                        if (!string.IsNullOrWhiteSpace(value)) return "id:" + value.Trim();
                    }
                }
            }
            catch (Exception)
            {
            }
            foreach (string name in SwitchParamNames)
            {
                try
                {
                    Parameter param = element.LookupParameter(name);
                    if (param == null) continue;
                    string value = param.AsString() ?? param.AsValueString();
                    if (!string.IsNullOrWhiteSpace(value)) return "id:" + value.Trim();
                }
                catch (Exception)
                {
                }
            }
            return "";
        }

        public static string SwitchIdOfCircuit(ElectricalSystem circuit)
        {
            foreach (string name in SwitchParamNames)
            {
                try
                {
                    Parameter param = circuit.LookupParameter(name);
                    if (param != null)
                    {
                        string value = param.AsString();
                        if (!string.IsNullOrWhiteSpace(value)) return "id:" + value.Trim();
                    }
                }
                catch (Exception)
                {
                }
            }
            return "";
        }

        public static List<BuiltInCategory> SwitchCategories(Dictionary<string, string> settings)
        {
            List<BuiltInCategory> wanted = WiresSettings.CategoriesFrom(WiresSettings.Get(settings, "switch_categories", "lighting_devices"), null);
            if (wanted.Count == 0)
            {
                BuiltInCategory? bic = WiresSettings.BuiltinCategory("OST_LightingDevices");
                if (bic != null) wanted.Add(bic.Value);
            }
            return wanted;
        }

        private static HashSet<long> CategoryIdValues(IEnumerable<BuiltInCategory> categories)
        {
            var values = new HashSet<long>();
            foreach (BuiltInCategory bic in categories)
            {
                try { values.Add(new ElementId(bic).Value); } catch (Exception) { }
            }
            return values;
        }

        /// <summary>Is this element a switch? Category first, then the family name, because a switch modelled outside Lighting Devices is common enough that a category-only test would miss it.</summary>
        public static Func<Element, bool> MakeSwitchTest(Dictionary<string, string> settings)
        {
            HashSet<long> values = CategoryIdValues(SwitchCategories(settings));
            return element =>
            {
                if (element == null) return false;
                try
                {
                    if (values.Contains(element.Category.Id.Value)) return true;
                }
                catch (Exception)
                {
                }
                try
                {
                    var fi = element as FamilyInstance;
                    if (fi != null && fi.Symbol.Family.Name.ToLowerInvariant().Contains("switch")) return true;
                }
                catch (Exception)
                {
                }
                try
                {
                    return element.Category.Name.ToLowerInvariant().Contains("switch");
                }
                catch (Exception)
                {
                    return false;
                }
            };
        }

        /// <summary>
        /// What decides which leg a fitting belongs to. Space and switch system are combined rather than chosen between, so the run breaks at either boundary
        /// and the span that bridges the break takes the permanent live wire type.
        /// </summary>
        public static string LegKey(Element element, Document doc, Dictionary<string, string> settings, Dictionary<string, object> cache = null)
        {
            var parts = new List<string>();
            if (WiresSettings.Bool(settings, "group_by_space"))
            {
                Dictionary<long, string> spaces;
                object stored;
                if (cache != null && cache.TryGetValue("space", out stored)) spaces = (Dictionary<long, string>)stored;
                else
                {
                    spaces = new Dictionary<long, string>();
                    if (cache != null) cache["space"] = spaces;
                }
                long key = element.Id.Value;
                string spaceName;
                if (!spaces.ContainsKey(key)) spaces[key] = WiresModel.SpaceKey(element, doc, out spaceName);
                parts.Add(spaces[key]);
            }
            if (WiresSettings.Bool(settings, "group_by_switch")) parts.Add(SwitchIdOf(element));
            return string.Join("|", parts);
        }

        /// <summary>The switch actually connected to this light, or null. Walks the light's own connectors, and one hop further through any wire hanging off them.</summary>
        public static Element ConnectedSwitch(Document doc, Element fixture, Func<Element, bool> isSwitch, out string how)
        {
            foreach (Connector connector in WiresModel.ElectricalConnectors(fixture))
            {
                foreach (Element owner in WiresModel.ConnectedOwners(connector))
                {
                    if (isSwitch(owner))
                    {
                        how = "connector";
                        return owner;
                    }
                    var wire = owner as Wire;
                    if (wire != null)
                    {
                        foreach (var end in WiresModel.WireEnds(wire))
                            foreach (Element far in WiresModel.ConnectedOwners(end.Key))
                                if (isSwitch(far))
                                {
                                    how = "wire";
                                    return far;
                                }
                    }
                }
            }
            // a switch system the light belongs to, whose other members include one
            foreach (ElectricalSystem circuit in WiresModel.ElementCircuits(fixture))
            {
                try
                {
                    foreach (Element member in circuit.Elements)
                        if (isSwitch(member))
                        {
                            how = "switch system";
                            return member;
                        }
                }
                catch (Exception)
                {
                }
            }
            how = "";
            return null;
        }

        /// <summary>Every switch-ish device in the view, keyed by switch id.</summary>
        public static Dictionary<string, List<Member>> FindSwitchDevices(Document doc, View view, Dictionary<string, string> settings)
        {
            var devices = new Dictionary<string, List<Member>>();
            List<BuiltInCategory> wanted = SwitchCategories(settings);
            if (wanted.Count == 0) return devices;
            try
            {
                var collector = new FilteredElementCollector(doc, view.Id).WherePasses(new ElementMulticategoryFilter(wanted)).WhereElementIsNotElementType();
                foreach (Element element in collector)
                {
                    string key = SwitchIdOf(element);
                    if (key.Length == 0) continue;
                    XYZ point = WiresModel.ElementPoint(element);
                    if (point == null) continue;
                    List<Member> list;
                    if (!devices.TryGetValue(key, out list))
                    {
                        list = new List<Member>();
                        devices[key] = list;
                    }
                    list.Add(new Member { Element = element, Point = point });
                }
            }
            catch (Exception)
            {
            }
            return devices;
        }

        // ------------------------------------------------------------------ circuits in the view
        private static List<BuiltInCategory> CategoryIds(Dictionary<string, string> settings, string key, string fallback)
        {
            return WiresSettings.CategoriesFrom(WiresSettings.Get(settings, key, fallback), null);
        }

        private static bool LooksLikeLighting(Element element, HashSet<long> lightingIds)
        {
            try
            {
                if (lightingIds.Contains(element.Category.Id.Value)) return true;
            }
            catch (Exception)
            {
            }
            try
            {
                return element.Category.Name.ToLowerInvariant().Contains("light");
            }
            catch (Exception)
            {
                return true;
            }
        }

        /// <summary>Wires in this view belonging to a circuit.</summary>
        public static List<Wire> CircuitWires(Document doc, View view, ElectricalSystem circuit)
        {
            var found = new List<Wire>();
            try
            {
                long target = circuit.Id.Value;
                foreach (Element e in new FilteredElementCollector(doc, view.Id).OfClass(typeof(Wire)))
                {
                    ElectricalSystem foundCircuit = WiresModel.WireCircuit(doc, (Wire)e);
                    if (foundCircuit != null && foundCircuit.Id.Value == target) found.Add((Wire)e);
                }
            }
            catch (Exception)
            {
            }
            return found;
        }

        /// <summary>Wire tags in the view whose host is one of these elements.</summary>
        public static List<IndependentTag> TagsOn(Document doc, View view, IEnumerable<Element> elements)
        {
            var found = new List<IndependentTag>();
            BuiltInCategory? bic = WiresSettings.BuiltinCategory("OST_WireTags");
            if (bic == null) return found;
            var wanted = new HashSet<long>(elements.Select(e => e.Id.Value));
            try
            {
                foreach (Element e in new FilteredElementCollector(doc, view.Id).OfCategory(bic.Value).WhereElementIsNotElementType())
                {
                    var tag = e as IndependentTag;
                    if (tag == null) continue;
                    try
                    {
                        foreach (ElementId hostId in tag.GetTaggedLocalElementIds())
                        {
                            if (wanted.Contains(hostId.Value))
                            {
                                found.Add(tag);
                                break;
                            }
                        }
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            catch (Exception)
            {
            }
            return found;
        }

        /// <summary>Every circuit with a member drawn in this view.</summary>
        public static List<CircuitJob> CollectJobs(Document doc, View view, Dictionary<string, string> settings, List<Element> restrictTo = null, bool wantPower = false)
        {
            List<BuiltInCategory> lighting = CategoryIds(settings, "lighting_categories", "lighting_fixtures");
            List<BuiltInCategory> power = CategoryIds(settings, "power_categories", "electrical_fixtures,electrical_equipment");
            var wanted = new List<BuiltInCategory>(lighting);
            if (wantPower) wanted.AddRange(power.Where(b => !wanted.Contains(b)));
            if (wanted.Count == 0) return new List<CircuitJob>();
            HashSet<long> lightingIds = CategoryIdValues(lighting);

            var inView = new Dictionary<long, Element>();
            try
            {
                var collector = new FilteredElementCollector(doc, view.Id).WherePasses(new ElementMulticategoryFilter(wanted)).WhereElementIsNotElementType();
                foreach (Element element in collector) inView[element.Id.Value] = element;
            }
            catch (Exception)
            {
            }
            if (restrictTo != null && restrictTo.Count > 0)
            {
                var keep = new HashSet<long>(restrictTo.Select(e => e.Id.Value));
                inView = inView.Where(kv => keep.Contains(kv.Key)).ToDictionary(kv => kv.Key, kv => kv.Value);
            }

            var jobs = new Dictionary<long, CircuitJob>();
            var order = new List<long>();
            foreach (Element element in inView.Values.ToList())
            {
                foreach (ElectricalSystem circuit in WiresModel.ElementCircuits(element))
                {
                    long key = circuit.Id.Value;
                    CircuitJob job;
                    if (!jobs.TryGetValue(key, out job))
                    {
                        job = new CircuitJob(circuit) { IsLighting = LooksLikeLighting(element, lightingIds) };
                        jobs[key] = job;
                        order.Add(key);
                    }
                    XYZ point = WiresModel.ElementPoint(element);
                    if (point != null) job.Members.Add(new Member { Element = element, Point = point });
                }
            }
            // members of those circuits that are not drawn in this view
            foreach (CircuitJob job in jobs.Values)
            {
                try
                {
                    int total = 0;
                    foreach (Element member in job.Circuit.Elements) total++;
                    job.Offscreen = Math.Max(0, total - job.Members.Count);
                }
                catch (Exception)
                {
                    job.Offscreen = 0;
                }
                job.ExistingWires = CircuitWires(doc, view, job.Circuit);
            }
            return jobs.Values.OrderBy(j => j.Label, StringComparer.Ordinal).ToList();
        }

        // ------------------------------------------------------------------ keeping clear of fittings that are not on this circuit
        public const int ClashSamples = 10;

        /// <summary>Every fitting drawn in the view, with a plan radius, read once.</summary>
        public static List<Obstacle> CollectObstacles(Document doc, View view, Dictionary<string, string> settings, Dictionary<string, object> cache = null)
        {
            object stored;
            if (cache != null && cache.TryGetValue("obstacles", out stored)) return (List<Obstacle>)stored;
            double clearance = WiresSettings.Mm(WiresSettings.Float(settings, "clash_clearance_mm"));
            var found = new List<Obstacle>();
            List<BuiltInCategory> categories = CategoryIds(settings, "lighting_categories", "lighting_fixtures");
            categories.AddRange(CategoryIds(settings, "power_categories", "electrical_fixtures,electrical_equipment").Where(b => !categories.Contains(b)));
            if (categories.Count > 0)
            {
                try
                {
                    var collector = new FilteredElementCollector(doc, view.Id).WherePasses(new ElementMulticategoryFilter(categories)).WhereElementIsNotElementType();
                    foreach (Element element in collector)
                    {
                        XYZ point = WiresModel.ElementPoint(element);
                        if (point == null) continue;
                        found.Add(new Obstacle { Eid = element.Id.Value, X = point.X, Y = point.Y, Radius = WiresGeom.PlanRadius(element, view) + clearance });
                    }
                }
                catch (Exception)
                {
                }
            }
            if (cache != null) cache["obstacles"] = found;
            return found;
        }

        /// <summary>The fittings the wire has to keep clear of - everything but its own.</summary>
        public static List<Obstacle> ObstaclesOffCircuit(List<Obstacle> obstacles, HashSet<long> memberIds)
        {
            return obstacles.Where(o => !memberIds.Contains(o.Eid)).ToList();
        }

        /// <summary>How many off-circuit fittings this one span would run across.</summary>
        public static int SpanClashes(XYZ pointA, XYZ pointB, double depth, string side, List<Obstacle> obstacles)
        {
            if (obstacles == null || obstacles.Count == 0) return 0;
            List<XYZ> points = WiresGeom.ArcThrough(pointA.X, pointA.Y, pointB.X, pointB.Y, depth, side, ClashSamples, 0.0);
            double midX = (pointA.X + pointB.X) / 2.0, midY = (pointA.Y + pointB.Y) / 2.0;
            double reach = Distance(pointA, pointB) / 2.0 + Math.Abs(depth);
            int hits = 0;
            foreach (Obstacle o in obstacles)
            {
                // coarse reject first: most fittings are nowhere near most spans
                if (Math.Sqrt((o.X - midX) * (o.X - midX) + (o.Y - midY) * (o.Y - midY)) > reach + o.Radius) continue;
                if (!WiresGeom.PolylineClears(points, o.X, o.Y, o.Radius)) hits++;
            }
            return hits;
        }

        private static double Distance(XYZ a, XYZ b)
        {
            return WiresGeom.PlanDistance(a, b);
        }

        private static double PathLength(IList<XYZ> points)
        {
            double total = 0.0;
            for (int i = 0; i < points.Count - 1; i++) total += Distance(points[i], points[i + 1]);
            return total;
        }

        // ------------------------------------------------------------------ the route
        /// <summary>Open path, greedily nearest, from a given start.</summary>
        public static List<int> NearestNeighbour(List<Member> items, int startIndex)
        {
            var remaining = Enumerable.Range(0, items.Count).ToList();
            remaining.Remove(startIndex);
            var order = new List<int> { startIndex };
            while (remaining.Count > 0)
            {
                XYZ here = items[order[order.Count - 1]].Point;
                int bestIndex = -1;
                double bestStep = 0;
                foreach (int index in remaining)
                {
                    double step = Distance(here, items[index].Point);
                    if (bestIndex < 0 || step < bestStep)
                    {
                        bestIndex = index;
                        bestStep = step;
                    }
                }
                order.Add(bestIndex);
                remaining.Remove(bestIndex);
            }
            return order;
        }

        /// <summary>Pulls crossings out of an open path.</summary>
        public static List<int> TwoOpt(List<Member> items, List<int> order, int rounds = 40)
        {
            if (order.Count < 4) return order;
            var best = new List<int>(order);
            bool improved = true;
            int guard = 0;
            while (improved && guard < rounds)
            {
                improved = false;
                guard++;
                for (int i = 0; i < best.Count - 2; i++)
                {
                    for (int j = i + 2; j < best.Count; j++)
                    {
                        XYZ a = items[best[i]].Point, b = items[best[i + 1]].Point, c = items[best[j]].Point;
                        double gain;
                        if (j + 1 < best.Count)
                        {
                            XYZ after = items[best[j + 1]].Point;
                            gain = (Distance(a, b) + Distance(c, after)) - (Distance(a, c) + Distance(b, after));
                        }
                        else gain = Distance(a, b) - Distance(a, c);
                        if (gain > 1.0e-6)
                        {
                            best.Reverse(i + 1, j - i);
                            improved = true;
                        }
                    }
                }
            }
            return best;
        }

        /// <summary>Rows across, alternate direction - what a regular grid of lights wants.</summary>
        public static List<int> Serpentine(List<Member> items, bool alongX)
        {
            var order = new List<int>();
            if (items.Count == 0) return order;
            double spreadX = items.Max(m => m.Point.X) - items.Min(m => m.Point.X);
            double spreadY = items.Max(m => m.Point.Y) - items.Min(m => m.Point.Y);
            double band = Math.Max(1.0e-6, (alongX ? spreadY : spreadX) * 0.18);
            Func<int, double> major = i => alongX ? items[i].Point.Y : items[i].Point.X;
            Func<int, double> minor = i => alongX ? items[i].Point.X : items[i].Point.Y;
            List<int> indexed = Enumerable.Range(0, items.Count).OrderBy(i => major(i)).ToList();
            var rows = new List<List<int>>();
            var current = new List<int>();
            double? anchor = null;
            foreach (int index in indexed)
            {
                double value = major(index);
                if (anchor == null || Math.Abs(value - anchor.Value) <= band)
                {
                    if (anchor == null) anchor = value;
                    current.Add(index);
                }
                else
                {
                    rows.Add(current);
                    current = new List<int> { index };
                    anchor = value;
                }
            }
            if (current.Count > 0) rows.Add(current);
            for (int number = 0; number < rows.Count; number++)
            {
                List<int> row = rows[number];
                row = number % 2 == 1 ? row.OrderByDescending(i => minor(i)).ToList() : row.OrderBy(i => minor(i)).ToList();
                order.AddRange(row);
            }
            return order;
        }

        /// <summary>Round the centroid by angle - reads well on a scattered layout.</summary>
        public static List<int> Sweep(List<Member> items)
        {
            if (items.Count == 0) return new List<int>();
            double cx = items.Average(m => m.Point.X), cy = items.Average(m => m.Point.Y);
            return Enumerable.Range(0, items.Count).OrderBy(i => Math.Atan2(items[i].Point.Y - cy, items[i].Point.X - cx)).ToList();
        }

        /// <summary>The indices of the two fittings furthest apart, cheaply.</summary>
        private static List<int> Extremes(List<Member> items)
        {
            if (items.Count < 2) return new List<int> { 0 };
            int first = 0;
            double best = -1.0;
            for (int index = 1; index < items.Count; index++)
            {
                double step = Distance(items[0].Point, items[index].Point);
                if (step > best)
                {
                    best = step;
                    first = index;
                }
            }
            int second = 0;
            best = -1.0;
            for (int index = 0; index < items.Count; index++)
            {
                double step = Distance(items[first].Point, items[index].Point);
                if (step > best)
                {
                    best = step;
                    second = index;
                }
            }
            return new List<int> { first, second };
        }

        /// <summary>
        /// Several orderings of the same fittings, best first. Each is a whole-run alternative rather than a nudge, so Shuffle actually changes the shape of the
        /// run. cost scores an ordering as (clashes, length): a route that runs over somebody else's light is worse than one a metre longer.
        /// </summary>
        public static List<List<int>> RouteAlternatives(List<Member> items, int? endIndex, bool useTwoOpt, Func<List<int>, Tuple<double, double>> cost)
        {
            if (items.Count < 2) return new List<List<int>> { Enumerable.Range(0, items.Count).ToList() };
            var seeds = new List<int>();
            if (endIndex != null) seeds.Add(endIndex.Value);
            // the two fittings furthest apart make natural ends of an open run
            foreach (int index in Extremes(items)) if (!seeds.Contains(index)) seeds.Add(index);
            if (!seeds.Contains(0)) seeds.Add(0);

            var orders = new List<List<int>>();
            foreach (int seed in seeds.Take(3))
            {
                List<int> order = NearestNeighbour(items, seed);
                if (useTwoOpt) order = TwoOpt(items, order);
                orders.Add(order);
            }
            orders.Add(Serpentine(items, true));
            orders.Add(Serpentine(items, false));
            orders.Add(Sweep(items));

            var cleaned = new List<List<int>>();
            var seen = new List<string>();
            foreach (List<int> order in orders)
            {
                if (order.Count == 0 || order.Count != items.Count) continue;
                string key = string.Join(",", order);
                string backwards = string.Join(",", Enumerable.Reverse(order));
                if (seen.Contains(key) || seen.Contains(backwards)) continue;
                seen.Add(key);
                cleaned.Add(order);
            }
            // the requested end goes last; reverse rather than re-solve
            if (endIndex != null)
            {
                var fixedOrders = new List<List<int>>();
                foreach (List<int> original in cleaned)
                {
                    List<int> order = original;
                    if (order.Count > 0 && order[0] == endIndex.Value) order = Enumerable.Reverse(order).ToList();
                    else if (order.Count > 0 && order[order.Count - 1] != endIndex.Value && order.Contains(endIndex.Value))
                    {
                        if (order.IndexOf(endIndex.Value) < order.Count / 2) order = Enumerable.Reverse(order).ToList();
                    }
                    fixedOrders.Add(order);
                }
                cleaned = fixedOrders;
            }
            Func<List<int>, Tuple<double, double>> key2 = cost ?? (order => Tuple.Create(0.0, PathLength(order.Select(i => items[i].Point).ToList())));
            var comparer = Comparer<List<int>>.Create((x, y) =>
            {
                Tuple<double, double> a = key2(x), b = key2(y);
                int c = a.Item1.CompareTo(b.Item1);
                return c != 0 ? c : a.Item2.CompareTo(b.Item2);
            });
            return cleaned.OrderBy(o => o, comparer).ToList();   // stable, like Python's sort
        }

        /// <summary>Scores a leg's own ordering with the whole run's cost function, mapping the leg's local indices back to the circuit's.</summary>
        private static Func<List<int>, Tuple<double, double>> LegCost(Func<List<int>, Tuple<double, double>> cost, List<int> memberIndices)
        {
            return order => cost(order.Select(i => memberIndices[i]).ToList());
        }

        /// <summary>
        /// Chains each switch group, then joins the groups end to end. Returns the order, the positions in it at which the run steps from one group to the next
        /// (those spans take the permanent live wire type), and how many genuinely different routes exist, so Shuffle can say "route 2 of 4" honestly.
        /// </summary>
        public static List<int> GroupedRoute(List<Member> items, List<string> keys, int? endIndex, bool useTwoOpt, int variant,
                                             Func<List<int>, Tuple<double, double>> cost, out List<int> crossings, out int optionCount)
        {
            var groupKeys = new List<string>();
            var groups = new Dictionary<string, List<int>>();
            for (int index = 0; index < keys.Count; index++)
            {
                List<int> list;
                if (!groups.TryGetValue(keys[index], out list))
                {
                    list = new List<int>();
                    groups[keys[index]] = list;
                    groupKeys.Add(keys[index]);
                }
                list.Add(index);
            }
            crossings = new List<int>();
            if (groups.Count < 2)
            {
                List<List<int>> options0 = RouteAlternatives(items, endIndex, useTwoOpt, cost);
                optionCount = Math.Max(1, options0.Count);
                return options0.Count > 0 ? options0[variant % options0.Count] : new List<int>();
            }

            // order within each group
            var legs = new List<List<int>>();
            optionCount = 1;
            foreach (string key in groupKeys)
            {
                List<int> indices = groups[key];
                List<Member> memberItems = indices.Select(i => items[i]).ToList();
                int? localEnd = null;
                if (endIndex != null && indices.Contains(endIndex.Value)) localEnd = indices.IndexOf(endIndex.Value);
                Func<List<int>, Tuple<double, double>> localCost = cost != null ? LegCost(cost, indices) : null;
                List<List<int>> options = RouteAlternatives(memberItems, localEnd, useTwoOpt, localCost);
                List<int> chosen = options.Count > 0 ? options[variant % options.Count] : Enumerable.Range(0, memberItems.Count).ToList();
                optionCount = Math.Max(optionCount, options.Count);
                legs.Add(chosen.Select(i => indices[i]).ToList());
            }

            // order the legs, nearest end to nearest end, ending on the leg that holds the fitting the home run leaves from
            int? finalLeg = null;
            if (endIndex != null)
            {
                for (int position = 0; position < legs.Count; position++)
                {
                    if (legs[position].Contains(endIndex.Value))
                    {
                        finalLeg = position;
                        break;
                    }
                }
            }
            var remaining = Enumerable.Range(0, legs.Count).ToList();
            var chain = new List<int>();
            if (finalLeg != null)
            {
                // build backwards from the final leg so it lands last
                chain.Add(finalLeg.Value);
                remaining.Remove(finalLeg.Value);
                while (remaining.Count > 0)
                {
                    XYZ head = items[legs[chain[0]][0]].Point;
                    int bestPos = -1;
                    double bestStep = 0;
                    bool bestFlip = false;
                    foreach (int position in remaining)
                    {
                        XYZ tail = items[legs[position][legs[position].Count - 1]].Point;
                        XYZ nose = items[legs[position][0]].Point;
                        foreach (var pair in new[] { Tuple.Create(tail, false), Tuple.Create(nose, true) })
                        {
                            double step = Distance(head, pair.Item1);
                            if (bestPos < 0 || step < bestStep)
                            {
                                bestPos = position;
                                bestStep = step;
                                bestFlip = pair.Item2;
                            }
                        }
                    }
                    if (bestFlip) legs[bestPos] = Enumerable.Reverse(legs[bestPos]).ToList();
                    chain.Insert(0, bestPos);
                    remaining.Remove(bestPos);
                }
            }
            else
            {
                chain.Add(remaining[0]);
                remaining.RemoveAt(0);
                while (remaining.Count > 0)
                {
                    List<int> lastLeg = legs[chain[chain.Count - 1]];
                    XYZ tail = items[lastLeg[lastLeg.Count - 1]].Point;
                    int bestPos = -1;
                    double bestStep = 0;
                    bool bestFlip = false;
                    foreach (int position in remaining)
                    {
                        XYZ nose = items[legs[position][0]].Point;
                        XYZ back = items[legs[position][legs[position].Count - 1]].Point;
                        foreach (var pair in new[] { Tuple.Create(nose, false), Tuple.Create(back, true) })
                        {
                            double step = Distance(tail, pair.Item1);
                            if (bestPos < 0 || step < bestStep)
                            {
                                bestPos = position;
                                bestStep = step;
                                bestFlip = pair.Item2;
                            }
                        }
                    }
                    if (bestFlip) legs[bestPos] = Enumerable.Reverse(legs[bestPos]).ToList();
                    chain.Add(bestPos);
                    remaining.Remove(bestPos);
                }
            }
            var order = new List<int>();
            foreach (int position in chain)
            {
                if (order.Count > 0) crossings.Add(order.Count - 1);
                order.AddRange(legs[position]);
            }
            return order;
        }

        // ------------------------------------------------------------------ placing
        private static Connector FreeConnector(Element element)
        {
            foreach (Connector connector in WiresModel.ElectricalConnectors(element)) return connector;
            return null;
        }

        /// <summary>The arc depth number, in whichever unit the mode is asking for.</summary>
        public static double SagSetting(Dictionary<string, string> settings)
        {
            if (WiresSettings.Lower(settings, "arc_sag_mode", "span") == "paper") return WiresSettings.Float(settings, "arc_sag_paper_mm");
            return WiresSettings.Float(settings, "arc_sag_percent");
        }

        /// <summary>One wire between two fittings, trimmed back from both symbols. Returns (wire, note).</summary>
        public static Wire PlaceSegment(Document doc, View view, Dictionary<string, string> settings, Element elementA, XYZ pointA, Element elementB, XYZ pointB,
                                        ElementType wireType, double planeZ, double sag, string side, out string note, double? midCount = null, string sagMode = null,
                                        string wiring = null)
        {
            double dx = pointB.X - pointA.X, dy = pointB.Y - pointA.Y;
            double length = Math.Sqrt(dx * dx + dy * dy);
            if (length < 1.0e-9)
            {
                note = "the two fittings sit on the same point";
                return null;
            }
            double ux = dx / length, uy = dy / length;
            double trimA, trimB;
            if (WiresSettings.Lower(settings, "trim_from", "extent") == "fixed")
            {
                trimA = trimB = WiresGeom.Paper(view, WiresSettings.Float(settings, "trim_fixed_paper_mm"));
            }
            else
            {
                trimA = WiresGeom.TrimDistance(view, settings, elementA, ux, uy, length);
                trimB = WiresGeom.TrimDistance(view, settings, elementB, ux, uy, length);
            }
            if (midCount == null) midCount = WiresSettings.Float(settings, "mid_vertices");
            if (sagMode == null) sagMode = WiresSettings.Get(settings, "arc_sag_mode", "span");
            // the depth is resolved against this span, so a share of the span means a share of THIS span rather than of the run as a whole
            double depth = WiresGeom.Sagitta(view, sagMode, sag, Math.Max(1.0e-9, length - trimA - trimB));
            string wiringName = wiring ?? WiresSettings.Get(settings, "wiring_type", "arc");
            List<XYZ> points = WiresGeom.SegmentPoints(pointA, pointB, planeZ, depth, side, trimA, trimB, midCount.Value, wiringName,
                                                       WiresSettings.Float(settings, "chamfer_angle_deg"));
            if (points == null || points.Count == 0)
            {
                note = "the segment came out with no length";
                return null;
            }
            Connector connectorA = FreeConnector(elementA), connectorB = FreeConnector(elementB);
            if (connectorA == null || connectorB == null)
            {
                note = "one of the fittings has no electrical connector";
                return null;
            }
            Wire wire;
            try
            {
                wire = Wire.Create(doc, wireType.Id, view.Id, WiresModel.WiringKind(wiring), new List<XYZ>(points), connectorA, connectorB);
            }
            catch (Exception error)
            {
                note = "Revit refused the wire (" + error.Message + ")";
                return null;
            }
            if (wire == null)
            {
                note = "Revit returned no wire";
                return null;
            }
            // Revit may re-seat the ends on the connectors, which undoes the trim. Push them back and read the connection afterwards rather than assume.
            bool trimmed = Retrim(wire, points);
            note = trimmed ? "" : "trim was refused, so the wire ends sit on the connectors rather than short of the symbol - Revit seats a connected wire end on its connector";
            return wire;
        }

        /// <summary>
        /// Pushes the vertices back where they were asked for. Revit does not always keep the vertex list it was given - it may seat the ends on the connectors
        /// and it may change the count - so the ends are set by index whatever the count came back as, and only a refusal from Revit itself counts as a refusal.
        /// </summary>
        private static bool Retrim(Wire wire, List<XYZ> points)
        {
            List<XYZ> current = WiresModel.WireVertices(wire);
            if (current.Count < 2 || points.Count < 2) return false;
            var pairs = new List<Tuple<int, XYZ>>();
            if (current.Count == points.Count)
            {
                for (int i = 0; i < points.Count; i++) pairs.Add(Tuple.Create(i, points[i]));
            }
            else
            {
                // the counts disagree, so align what the trim is actually about
                pairs.Add(Tuple.Create(0, points[0]));
                pairs.Add(Tuple.Create(current.Count - 1, points[points.Count - 1]));
            }
            bool refused = false;
            foreach (var pair in pairs)
            {
                if (pair.Item1 >= current.Count) continue;
                if (WiresGeom.PlanDistance(current[pair.Item1], pair.Item2) <= WiresSettings.Mm(0.5)) continue;
                try
                {
                    wire.SetVertex(pair.Item1, pair.Item2);
                }
                catch (Exception)
                {
                    refused = true;
                }
            }
            return !refused;
        }

        /// <summary>
        /// From the light toward the switch. Two shapes: arrow (default) is a short wire leaving the light in the direction of the switch and stopping well short of
        /// it - connected at the light end only, the condition under which Revit itself draws a home run arrowhead; full runs all the way and connects into the switch.
        /// </summary>
        public static Wire PlaceHomeRun(Document doc, View view, Dictionary<string, string> settings, Element element, XYZ point, XYZ targetPoint, ElementType wireType,
                                        double planeZ, double sag, string side, Element targetElement, string wiring, out string note)
        {
            double dx = targetPoint.X - point.X, dy = targetPoint.Y - point.Y;
            double length = Math.Sqrt(dx * dx + dy * dy);
            if (length < 1.0e-9)
            {
                note = "the switch sits on the fitting";
                return null;
            }
            double ux = dx / length, uy = dy / length;
            double gap = WiresGeom.Paper(view, WiresSettings.Float(settings, "trim_gap_paper_mm"));
            double trimA = WiresGeom.TrimDistance(view, settings, element, ux, uy, length);
            double mids = WiresSettings.Float(settings, "mid_vertices");
            bool arrow = WiresSettings.Lower(settings, "home_run_style", "arrow") != "full";
            string wiringName = wiring ?? WiresSettings.Get(settings, "wiring_type", "arc");
            double chamfer = WiresSettings.Float(settings, "chamfer_angle_deg");
            List<XYZ> points;
            Connector connectorB;
            if (arrow)
            {
                // always one middle vertex, whatever the general setting is: the whole point of the arrow is that it arcs toward the switch
                mids = 1;
                double reach = WiresGeom.Paper(view, WiresSettings.Float(settings, "home_run_arrow_paper_mm"));
                // never overshoot the switch it is pointing at
                reach = Math.Min(reach, Math.Max(0.0, length - trimA - gap));
                if (reach <= 0.0)
                {
                    note = "the switch is too close for an arrow";
                    return null;
                }
                var finish = new XYZ(point.X + ux * (trimA + reach), point.Y + uy * (trimA + reach), planeZ);
                double depth = WiresGeom.Sagitta(view, WiresSettings.Get(settings, "arc_sag_mode", "span"), sag, Math.Max(1.0e-9, reach));
                points = WiresGeom.SegmentPoints(point, finish, planeZ, depth, side, trimA, 0.0, mids, wiringName, chamfer);
                connectorB = null;
                targetElement = null;
            }
            else
            {
                double trimB = gap;
                if (targetElement != null) trimB = WiresGeom.TrimDistance(view, settings, targetElement, ux, uy, length);
                double depth = WiresGeom.Sagitta(view, WiresSettings.Get(settings, "arc_sag_mode", "span"), sag, Math.Max(1.0e-9, length - trimA - trimB));
                points = WiresGeom.SegmentPoints(point, targetPoint, planeZ, depth, side, trimA, trimB, mids, wiringName, chamfer);
                connectorB = targetElement != null ? FreeConnector(targetElement) : null;
            }
            if (points == null || points.Count == 0)
            {
                note = "the home run came out with no length";
                return null;
            }
            Connector connectorA = FreeConnector(element);
            WiringType kind = WiresModel.WiringKind(wiring);
            foreach (Connector second in new[] { connectorB, null })
            {
                Wire wire;
                try
                {
                    wire = Wire.Create(doc, wireType.Id, view.Id, kind, new List<XYZ>(points), connectorA, second);
                }
                catch (Exception)
                {
                    wire = null;
                }
                if (wire != null)
                {
                    Retrim(wire, points);
                    if (second == null && connectorB != null)
                    {
                        note = "the switch would not take the wire, so the home run is a stub";
                        return wire;
                    }
                    note = "";
                    return wire;
                }
            }
            note = "Revit refused the home run";
            return null;
        }

        /// <summary>A detail line from the light fitting to the lighting device, straight and view-specific, on a line style of your choosing.</summary>
        public static DetailCurve PlaceSwitchLine(Document doc, View view, Dictionary<string, string> settings, Element light, XYZ lightPoint, Element sw, XYZ switchPoint,
                                                  Dictionary<string, object> cache, out string note)
        {
            double dx = switchPoint.X - lightPoint.X, dy = switchPoint.Y - lightPoint.Y;
            double length = Math.Sqrt(dx * dx + dy * dy);
            if (length < 1.0e-9)
            {
                note = "the switch sits on the light";
                return null;
            }
            double ux = dx / length, uy = dy / length;
            double trimA = WiresGeom.TrimDistance(view, settings, light, ux, uy, length);
            double trimB = WiresGeom.TrimDistance(view, settings, sw, ux, uy, length);
            if (trimA + trimB >= length)
            {
                double share = length * 0.45;
                trimA = Math.Min(trimA, share);
                trimB = Math.Min(trimB, share);
            }
            double planeZ = WiresModel.DrawingPlaneZ(doc, view);
            var start = new XYZ(lightPoint.X + ux * trimA, lightPoint.Y + uy * trimA, planeZ);
            var finish = new XYZ(switchPoint.X - ux * trimB, switchPoint.Y - uy * trimB, planeZ);
            DetailCurve curve;
            try
            {
                curve = doc.Create.NewDetailCurve(view, Line.CreateBound(start, finish));
            }
            catch (Exception error)
            {
                note = "Revit refused the detail line (" + error.Message + ")";
                return null;
            }
            if (curve == null)
            {
                note = "Revit returned no detail line";
                return null;
            }
            string wanted = WiresSettings.Get(settings, "switch_line_style");
            if (wanted.Length > 0)
            {
                GraphicsStyle style = WiresModel.FindLineStyle(doc, wanted, cache);
                if (style == null)
                {
                    note = "line style \"" + wanted + "\" is not in this model, so the line is on the view default";
                    return curve;
                }
                try
                {
                    curve.LineStyle = style;
                }
                catch (Exception)
                {
                    note = "the line style would not be set";
                    return curve;
                }
            }
            note = "";
            return curve;
        }

        /// <summary>Deletes wires connected at one end only - Revit's panel home runs.</summary>
        public static int RemovePanelHomeRuns(Document doc, IEnumerable<Wire> wires, IEnumerable<long> keepIds = null)
        {
            var keep = new HashSet<long>(keepIds ?? new long[0]);
            int removed = 0;
            foreach (Wire wire in wires)
            {
                try
                {
                    if (keep.Contains(wire.Id.Value)) continue;
                    int connected = 0;
                    foreach (var end in WiresModel.WireEnds(wire))
                        if (!WiresModel.ConnectorIsFree(end.Key)) connected++;
                    if (connected == 1)
                    {
                        doc.Delete(wire.Id);
                        removed++;
                    }
                }
                catch (Exception)
                {
                }
            }
            return removed;
        }

        private static double TagOffset(View view, Dictionary<string, string> settings)
        {
            double value = WiresSettings.Float(settings, "tag_offset_mm");
            return WiresSettings.Bool(settings, "tag_offset_is_paper") ? WiresGeom.Paper(view, value) : WiresSettings.Mm(value);
        }

        /// <summary>One tag, offset square to the wire it sits on.</summary>
        public static IndependentTag PlaceTag(Document doc, View view, Dictionary<string, string> settings, Wire wire, FamilySymbol tagType)
        {
            if (tagType == null || wire == null) return null;
            List<XYZ> points = WiresModel.WireVertices(wire);
            if (points.Count < 2) return null;
            XYZ first = points[0], last = points[points.Count - 1];
            double midX = (first.X + last.X) / 2.0, midY = (first.Y + last.Y) / 2.0;
            double dx = last.X - first.X, dy = last.Y - first.Y;
            double length = Math.Sqrt(dx * dx + dy * dy);
            double offset = TagOffset(view, settings);
            if (length > 1.0e-9)
            {
                midX += (-dy / length) * offset;
                midY += (dx / length) * offset;
            }
            var point = new XYZ(midX, midY, first.Z);
            bool leader = WiresSettings.Bool(settings, "tag_leader");
            try
            {
                if (!tagType.IsActive)
                {
                    tagType.Activate();
                    doc.Regenerate();
                }
            }
            catch (Exception)
            {
            }
            Reference reference = null;
            try { reference = new Reference(wire); } catch (Exception) { }
            if (reference != null)
            {
                try
                {
                    return IndependentTag.Create(doc, tagType.Id, view.Id, reference, leader, TagOrientation.Horizontal, point);
                }
                catch (Exception)
                {
                }
            }
            return null;
        }

        // ------------------------------------------------------------------ one circuit, start to finish
        private static string SegmentWireTypeKey(int position, List<int> order, HashSet<int> crossings, Dictionary<int, bool> emergency, bool wholeCircuitEmergency,
                                                 bool hasLive, bool hasEmergency)
        {
            if (wholeCircuitEmergency && hasEmergency) return "emergency";
            if (crossings.Contains(position) && hasLive) return "live";
            if (hasEmergency)
            {
                bool a, b;
                emergency.TryGetValue(order[position], out a);
                emergency.TryGetValue(order[position + 1], out b);
                if (a || b) return "emergency";
            }
            return "base";
        }

        /// <summary>Which wire type one span takes: emergency throughout on an emergency circuit; otherwise permanent live on a crossing, else the base type.</summary>
        private static ElementType SegmentType(int position, List<int> order, HashSet<int> crossings, Dictionary<int, bool> emergency, ElementType wireType, ElementType liveType,
                                               ElementType emergencyType, bool wholeCircuitEmergency)
        {
            string key = SegmentWireTypeKey(position, order, crossings, emergency, wholeCircuitEmergency, liveType != null, emergencyType != null);
            if (key == "emergency") return emergencyType;
            if (key == "live") return liveType;
            return wireType;
        }

        private static readonly string[] RoutineSpanNotes = { "trim was refused" };

        private static bool IsRoutine(string text)
        {
            return RoutineSpanNotes.Any(s => text.StartsWith(s, StringComparison.Ordinal));
        }

        /// <summary>One line per distinct outcome, with how many spans it happened to.</summary>
        private static void EmitSpanNotes(Placement result, string label, Dictionary<string, int> tally)
        {
            foreach (string text in tally.Keys.OrderBy(t => t, StringComparer.Ordinal))
            {
                int count = tally[text];
                string line = count > 1 ? label + ": " + count + " span(s) - " + text + "." : label + ": " + text + ".";
                if (IsRoutine(text)) result.Info.Add(line);
                else result.Notes.Add(line);
            }
        }

        private static Wire TagTarget(Dictionary<string, string> settings, List<Wire> wires, Wire homeRun)
        {
            string which = WiresSettings.Lower(settings, "tag_which", "homerun");
            if (which == "first") return wires[0];
            if (which == "homerun" && homeRun != null) return homeRun;
            Wire longest = null;
            double best = -1.0;
            foreach (Wire wire in wires)
            {
                List<XYZ> points = WiresModel.WireVertices(wire);
                if (points.Count < 2) continue;
                double step = WiresGeom.PlanDistance(points[0], points[points.Count - 1]);
                if (step > best)
                {
                    best = step;
                    longest = wire;
                }
            }
            return longest ?? wires[0];
        }

        /// <summary>Draws one circuit at the given route variant. Inside a transaction.</summary>
        public static Placement WireOneCircuit(Document doc, View view, Dictionary<string, string> settings, CircuitJob job, int variant = 0, Dictionary<string, object> cache = null,
                                               double? vertexOverride = null, double? sagOverride = null, bool? avoidOverride = null, string wiringOverride = null)
        {
            var result = new Placement(job) { Variant = variant };
            List<Member> items = job.Members;
            if (items.Count < 2 && job.SwitchElement == null)
            {
                result.Notes.Add(job.Label + ": only one fitting in this view, nothing to draw between.");
                return result;
            }
            int limit = (int)WiresSettings.Float(settings, "max_members");
            if (limit == 0) limit = 200;
            if (items.Count > limit)
            {
                result.Notes.Add(job.Label + ": " + items.Count + " fittings, over the " + limit + " limit.");
                return result;
            }
            double planeZ = WiresModel.DrawingPlaneZ(doc, view);
            string sagMode = WiresSettings.Get(settings, "arc_sag_mode", "span");
            double sag = sagOverride ?? SagSetting(settings);
            string side = WiresSettings.Get(settings, "arc_side", "left");
            string wiring = wiringOverride ?? WiresSettings.Get(settings, "wiring_type", "arc");

            if (cache == null) cache = new Dictionary<string, object>();
            ElementType wireType = job.IsLighting
                ? WiresModel.FindWireType(doc, WiresSettings.Get(settings, "lighting_wire_type"), cache)
                : WiresModel.FindWireType(doc, WiresSettings.Get(settings, "power_wire_type"), cache);
            ElementType liveType = WiresModel.FindWireType(doc, WiresSettings.Get(settings, "lighting_live_wire_type"), cache);
            ElementType emergencyType = WiresModel.FindWireType(doc, WiresSettings.Get(settings, "lighting_emergency_wire_type"), cache);
            if (wireType == null)
            {
                result.Notes.Add(job.Label + ": not drawn - no wire type could be found in this model. Check the Lighting tab in Settings.");
                return result;
            }

            // where the run should finish
            int? endIndex = null;
            if (job.SwitchPoint != null && WiresSettings.Bool(settings, "end_chain_at_switch"))
            {
                // the light the switch is actually wired to wins over the nearest one
                if (job.SwitchFrom != null)
                {
                    for (int index = 0; index < items.Count; index++)
                    {
                        if (WiresModel.SameId(items[index].Element.Id, job.SwitchFrom.Id))
                        {
                            endIndex = index;
                            break;
                        }
                    }
                }
                if (endIndex == null)
                {
                    int bestIndex = -1;
                    double bestStep = 0;
                    for (int index = 0; index < items.Count; index++)
                    {
                        double step = Distance(items[index].Point, job.SwitchPoint);
                        if (bestIndex < 0 || step < bestStep)
                        {
                            bestIndex = index;
                            bestStep = step;
                        }
                    }
                    if (bestIndex >= 0) endIndex = bestIndex;
                }
            }

            // what the run has to keep clear of: every fitting in the view that is not a member of this circuit
            bool avoiding = avoidOverride ?? WiresSettings.Bool(settings, "avoid_fittings");
            var obstacles = new List<Obstacle>();
            if (avoiding)
            {
                var memberIds = new HashSet<long>(items.Select(m => m.Element.Id.Value));
                obstacles = ObstaclesOffCircuit(CollectObstacles(doc, view, settings, cache), memberIds);
            }
            Func<XYZ, XYZ, double> spanDepth = (a, b) => WiresGeom.Sagitta(view, sagMode, sag, Math.Max(1.0e-9, Distance(a, b)));
            Func<List<int>, Tuple<double, double>> routeCost = order =>
            {
                double length = 0.0;
                int clashes = 0;
                for (int position = 0; position < order.Count - 1; position++)
                {
                    XYZ a = items[order[position]].Point, b = items[order[position + 1]].Point;
                    length += Distance(a, b);
                    if (obstacles.Count > 0) clashes += SpanClashes(a, b, spanDepth(a, b), side, obstacles);
                }
                return Tuple.Create((double)clashes, length);
            };
            Func<List<int>, Tuple<double, double>> cost = obstacles.Count > 0 ? routeCost : null;

            bool useTwoOpt = WiresSettings.Bool(settings, "two_opt");
            List<int> order2;
            List<int> crossings;
            int optionCount;
            if (WiresSettings.Bool(settings, "group_by_switch") || WiresSettings.Bool(settings, "group_by_space"))
            {
                List<string> keys = items.Select(m => LegKey(m.Element, doc, settings, cache)).ToList();
                order2 = GroupedRoute(items, keys, endIndex, useTwoOpt, variant, cost, out crossings, out optionCount);
            }
            else
            {
                List<List<int>> options = RouteAlternatives(items, endIndex, useTwoOpt, cost);
                order2 = options.Count > 0 ? options[variant % options.Count] : Enumerable.Range(0, items.Count).ToList();
                crossings = new List<int>();
                optionCount = Math.Max(1, options.Count);
            }
            result.Options = optionCount;
            if (order2.Count == 0)
            {
                result.Notes.Add(job.Label + ": no route could be worked out.");
                return result;
            }

            var spanLengths = new List<double>();
            for (int position = 0; position < order2.Count - 1; position++)
                spanLengths.Add(Distance(items[order2[position]].Point, items[order2[position + 1]].Point));
            double wanted = vertexOverride ?? WiresSettings.Float(settings, "mid_vertices");
            // 'each' puts the same number on every wire, so 1 is one vertex at the middle of every span; 'length' shares them out by span instead
            bool byLength = WiresSettings.Lower(settings, "vertex_mode", "each") == "length";
            double spacing = byLength ? WiresGeom.VertexSpacing(spanLengths, wanted) : 0.0;

            int flipped = 0, stillClashing = 0;
            var spanNotes = new Dictionary<string, int>();
            var crossingSet = new HashSet<int>(crossings);
            var emergency = new Dictionary<int, bool>();
            bool allEmergency = false;
            if (job.IsLighting && emergencyType != null)
            {
                for (int index = 0; index < items.Count; index++) emergency[index] = WiresModel.IsEmergency(items[index].Element, doc, settings);
                int marked = emergency.Values.Count(v => v);
                // ANY fitting reading as emergency makes the whole circuit an emergency circuit: requiring all of them meant one fitting with the parameter unset
                // put permanent live spans back into a run that is emergency in every other respect - the wrong way to be wrong.
                allEmergency = marked > 0;
                if (allEmergency && marked == items.Count)
                {
                    result.Info.Add(job.Label + ": every fitting reads as emergency, so the whole circuit is drawn in the emergency wire type and no span is permanent live.");
                }
                else if (allEmergency)
                {
                    result.Notes.Add(job.Label + ": " + marked + " of " + items.Count + " fitting(s) read as emergency, so the whole circuit is drawn in the emergency wire type. Check the " +
                                     WiresSettings.Get(settings, "emergency_parameter") + " parameter on the other " + (items.Count - marked) + " if that is wrong.");
                }
            }

            for (int position = 0; position < order2.Count - 1; position++)
            {
                Element elementA = items[order2[position]].Element, elementB = items[order2[position + 1]].Element;
                XYZ pointA = items[order2[position]].Point, pointB = items[order2[position + 1]].Point;
                ElementType segmentType = SegmentType(position, order2, crossingSet, emergency, wireType, liveType, emergencyType, allEmergency);
                double mids = byLength ? Math.Max(WiresGeom.MinVertices, WiresGeom.VerticesFor(spanLengths[position], spacing)) : WiresGeom.ClampVertices(wanted);
                string spanSide = side;
                if (obstacles.Count > 0)
                {
                    double depth = spanDepth(pointA, pointB);
                    int hits = SpanClashes(pointA, pointB, depth, side, obstacles);
                    if (hits > 0)
                    {
                        string other = side.Trim().ToLowerInvariant() != "right" ? "right" : "left";
                        if (SpanClashes(pointA, pointB, depth, other, obstacles) < hits)
                        {
                            spanSide = other;
                            flipped++;
                        }
                        else stillClashing++;
                    }
                }
                string note;
                Wire wire = PlaceSegment(doc, view, settings, elementA, pointA, elementB, pointB, segmentType, planeZ, sag, spanSide, out note, mids, sagMode, wiring);
                if (wire == null)
                {
                    string key = "refused - " + note;
                    int c;
                    spanNotes.TryGetValue(key, out c);
                    spanNotes[key] = c + 1;
                }
                else
                {
                    result.Wires.Add(wire);
                    result.Length += Distance(pointA, pointB);
                    if (note.Length > 0)
                    {
                        int c;
                        spanNotes.TryGetValue(note, out c);
                        spanNotes[note] = c + 1;
                    }
                }
            }

            // the home run
            Wire homeRun = null;
            if (job.SwitchPoint != null && WiresSettings.Bool(settings, "switch_home_run"))
            {
                Element element = items[order2[order2.Count - 1]].Element;
                XYZ point = items[order2[order2.Count - 1]].Point;
                ElementType homeRunType = wireType;
                if (allEmergency && emergencyType != null) homeRunType = emergencyType;
                string note;
                homeRun = PlaceHomeRun(doc, view, settings, element, point, job.SwitchPoint, homeRunType, planeZ, sag, side, job.SwitchElement, wiring, out note);
                if (homeRun == null)
                {
                    if (WiresSettings.Bool(settings, "stub_if_no_connection")) result.Notes.Add(job.Label + ": no home run - " + note + ".");
                }
                else
                {
                    result.Wires.Add(homeRun);
                    if (note.Length > 0) result.Notes.Add(job.Label + ": " + note + ".");
                }
            }
            else if (job.SwitchPoint == null && WiresSettings.Bool(settings, "switch_home_run"))
            {
                result.Notes.Add(job.Label + ": no switch found, so no home run was drawn and any panel home run has been left alone.");
            }

            EmitSpanNotes(result, job.Label, spanNotes);
            result.Flipped = flipped;
            result.Clashing = stillClashing;
            if (flipped > 0) result.Info.Add(job.Label + ": " + flipped + " span(s) arc the other way to clear a fitting on another circuit.");
            if (stillClashing > 0)
                result.Notes.Add(job.Label + ": " + stillClashing + " span(s) still cross a fitting that is not on this circuit - no route or side clears them. Shuffle may find one.");

            // the drawn connection between the light and its switch
            if (job.SwitchPoint != null && job.SwitchFrom != null && WiresSettings.Bool(settings, "draw_switch_line"))
            {
                string note;
                DetailCurve line = PlaceSwitchLine(doc, view, settings, job.SwitchFrom, WiresModel.ElementPoint(job.SwitchFrom), job.SwitchElement, job.SwitchPoint, cache, out note);
                if (line == null) result.Notes.Add(job.Label + ": no switch line - " + note + ".");
                else
                {
                    result.Extras.Add(line);
                    if (note.Length > 0) result.Notes.Add(job.Label + ": " + note + ".");
                }
            }

            // panel home runs, once there is something to replace them with
            if (homeRun != null && WiresSettings.Bool(settings, "remove_panel_home_runs"))
            {
                List<long> keep = result.Wires.Select(w => w.Id.Value).ToList();
                int removed = RemovePanelHomeRuns(doc, job.ExistingWires, keep);
                if (removed > 0) result.Info.Add(job.Label + ": " + removed + " home run(s) back to the panel removed.");
            }

            // the tag
            if (WiresSettings.Bool(settings, "tag_circuits") && result.Wires.Count > 0)
            {
                FamilySymbol tagType = WiresModel.FindTagType(doc, WiresSettings.Get(settings, "wire_tag_family"), WiresSettings.Get(settings, "wire_tag_type"), cache);
                Wire target = TagTarget(settings, result.Wires, homeRun);
                result.Tag = PlaceTag(doc, view, settings, target, tagType);
                if (result.Tag == null) result.Notes.Add(job.Label + ": the wire tag would not place - check a wire tag family is loaded.");
            }
            return result;
        }

        // ------------------------------------------------------------------ snapshots, so Cancel can put things back
        public sealed class WireEndShot
        {
            public int Index;
            public long? OwnerId;
            public int ConnectorId;
        }

        /// <summary>Enough to rebuild a wire after it has been deleted. Connector objects are not held; the owning element id and the connector's own id are re-resolved at restore time.</summary>
        public sealed class WireShot
        {
            public ElementId TypeId, ViewId;
            public WiringType Wiring;
            public List<XYZ> Points;
            public List<WireEndShot> Ends = new List<WireEndShot>();
        }

        public sealed class TagShot
        {
            public ElementId TypeId, ViewId;
            public List<ElementId> Hosts = new List<ElementId>();
            public XYZ Point;
            public bool Leader;
        }

        public static WireShot SnapshotWire(Document doc, Wire wire)
        {
            List<XYZ> points = WiresModel.WireVertices(wire);
            if (points.Count < 2) return null;
            var shot = new WireShot { TypeId = wire.GetTypeId(), ViewId = wire.OwnerViewId, Wiring = WiresModel.WiringTypeOf(wire), Points = points };
            foreach (var end in WiresModel.WireEnds(wire))
            {
                Connector partner = WiresModel.OppositeConnector(end.Key);
                var e = new WireEndShot { Index = end.Value };
                if (partner != null)
                {
                    try
                    {
                        e.OwnerId = partner.Owner.Id.Value;
                        e.ConnectorId = partner.Id;
                    }
                    catch (Exception)
                    {
                        e.OwnerId = null;
                    }
                }
                shot.Ends.Add(e);
            }
            return shot;
        }

        private static Connector ResolveConnector(Document doc, long? ownerId, int connectorId)
        {
            if (ownerId == null) return null;
            Element owner = null;
            try { owner = doc.GetElement(RevitCompat.Id(ownerId.Value)); } catch (Exception) { }
            if (owner == null) return null;
            foreach (Connector connector in WiresModel.ElectricalConnectors(owner))
            {
                try
                {
                    if (connector.Id == connectorId) return connector;
                }
                catch (Exception)
                {
                }
            }
            return null;
        }

        /// <summary>Puts a snapshotted wire back. Its element id will be a new one.</summary>
        public static Wire RestoreWire(Document doc, WireShot shot)
        {
            if (shot == null) return null;
            int last = shot.Points.Count - 1;
            Connector start = null, finish = null;
            foreach (WireEndShot end in shot.Ends)
            {
                Connector connector = ResolveConnector(doc, end.OwnerId, end.ConnectorId);
                if (end.Index == 0) start = connector;
                else if (end.Index == last) finish = connector;
            }
            try
            {
                return Wire.Create(doc, shot.TypeId, shot.ViewId, shot.Wiring, new List<XYZ>(shot.Points), start, finish);
            }
            catch (Exception)
            {
                return null;
            }
        }

        public static TagShot SnapshotTag(Document doc, IndependentTag tag)
        {
            try
            {
                var shot = new TagShot { TypeId = tag.GetTypeId(), ViewId = tag.OwnerViewId, Point = tag.TagHeadPosition, Leader = tag.HasLeader };
                foreach (ElementId id in tag.GetTaggedLocalElementIds()) shot.Hosts.Add(id);
                return shot;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>Puts a snapshotted tag back, optionally onto a different host (a rebuilt wire is a new element, so a tag on the old one has to be re-pointed).</summary>
        public static IndependentTag RestoreTag(Document doc, TagShot shot, Element host = null)
        {
            if (shot == null) return null;
            if (host == null)
            {
                if (shot.Hosts.Count == 0) return null;
                host = doc.GetElement(shot.Hosts[0]);
            }
            if (host == null) return null;
            try
            {
                return IndependentTag.Create(doc, shot.TypeId, shot.ViewId, new Reference(host), shot.Leader, TagOrientation.Horizontal, shot.Point);
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>Takes out a circuit's existing wires and their tags. With a snapshots list, enough is recorded first to put them back (what Cancel needs).</summary>
        public static void ClearCircuit(Document doc, View view, CircuitJob job, List<KeyValuePair<string, object>> snapshots, out int removedWires, out int removedTags)
        {
            List<Wire> wires = job.ExistingWires.ToList();
            List<IndependentTag> tags = TagsOn(doc, view, wires);
            if (snapshots != null)
            {
                foreach (IndependentTag tag in tags)
                {
                    TagShot shot = SnapshotTag(doc, tag);
                    if (shot != null) snapshots.Add(new KeyValuePair<string, object>("tag", shot));
                }
                foreach (Wire wire in wires)
                {
                    WireShot shot = SnapshotWire(doc, wire);
                    if (shot != null) snapshots.Add(new KeyValuePair<string, object>("wire", shot));
                }
            }
            removedTags = 0;
            removedWires = 0;
            foreach (IndependentTag tag in tags)
            {
                try
                {
                    doc.Delete(tag.Id);
                    removedTags++;
                }
                catch (Exception)
                {
                }
            }
            foreach (Wire wire in wires)
            {
                try
                {
                    doc.Delete(wire.Id);
                    removedWires++;
                }
                catch (Exception)
                {
                }
            }
            job.ExistingWires = new List<Wire>();
        }

        /// <summary>
        /// Finds the circuit's switch, and the light the home run leaves from. Connectivity is asked first and the id parameters second: a switch that is genuinely
        /// wired to one of the lights is a fact; a matching Switch ID is only a claim.
        /// </summary>
        public static void AttachSwitch(CircuitJob job, Dictionary<string, List<Member>> switches, Dictionary<string, string> settings, Document doc = null)
        {
            Func<Element, bool> isSwitch = MakeSwitchTest(settings);
            // 1. a switch actually connected to one of this circuit's lights
            if (doc != null)
            {
                foreach (Member member in job.Members)
                {
                    string how;
                    Element found = ConnectedSwitch(doc, member.Element, isSwitch, out how);
                    if (found != null)
                    {
                        job.SwitchElement = found;
                        job.SwitchPoint = WiresModel.ElementPoint(found);
                        job.SwitchFrom = member.Element;
                        job.SwitchRoute = "connected to " + WiresModel.ElementName(member.Element) + " through its " + how;
                        if (job.SwitchPoint != null) return;
                    }
                }
            }
            // 2. the switch system the fittings name, matched to a device in the view
            var keys = new Dictionary<string, int>();
            foreach (Member member in job.Members)
            {
                string key = SwitchIdOf(member.Element);
                if (key.Length > 0)
                {
                    int c;
                    keys.TryGetValue(key, out c);
                    keys[key] = c + 1;
                }
            }
            if (keys.Count == 0)
            {
                string key = SwitchIdOfCircuit(job.Circuit);
                if (key.Length > 0) keys[key] = 1;
            }
            if (keys.Count == 0) return;
            List<KeyValuePair<string, int>> ordered = keys.OrderByDescending(p => p.Value).ToList();
            foreach (var pair in ordered)
            {
                List<Member> devices;
                if (switches.TryGetValue(pair.Key, out devices) && devices.Count > 0)
                {
                    job.SwitchKey = pair.Key;
                    job.SwitchElement = devices[0].Element;
                    job.SwitchPoint = devices[0].Point;
                    int colon = pair.Key.IndexOf(':');
                    job.SwitchRoute = "matched on switch id " + (colon >= 0 ? pair.Key.Substring(colon + 1) : pair.Key);
                    return;
                }
            }
            job.SwitchKey = ordered[0].Key;
        }
    }
}
