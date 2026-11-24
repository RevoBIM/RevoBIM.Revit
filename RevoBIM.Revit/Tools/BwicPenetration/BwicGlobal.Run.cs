using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.BwicPenetration
{
    /// <summary>What the window passes to a Global Placement run (the dict the pyRevit window built).</summary>
    public sealed class GlobalSettings
    {
        public ElementId LinkId;
        public double ClearanceMm = 50.0;
        public double GapPipesMm = 200.0, GapTraysMm = 200.0, GapConduitMm = 100.0;
        public bool LogComments = true, UseWorkset = true;
        public string LevelParam = "";
    }

    /// <summary>What a Global Placement run did, for the results window.</summary>
    public sealed class GlobalSummary
    {
        public int Placed, Review, ClashPairs, Skipped, Duplicates, Unmeasured, Failed, Groups, Walls;
        public List<ElementId> ReviewIds = new List<ElementId>();
        public string FailedGroupName, GroupName;
        public List<string> Warnings = new List<string>(), Log = new List<string>();
    }

    public sealed class PlacedRecord
    {
        public ElementId Id;
        public Box Box;
    }

    public sealed class FailureRecord
    {
        public string Text;
        public Box Box;
    }

    public static partial class BwicGlobal
    {
        /// <summary>Union-find over (element, extents) pairs. Grouping is transitive.</summary>
        public static List<List<Element>> ClusterByGap(IList<Tuple<Element, double[]>> entries, double gapFt)
        {
            int count = entries.Count;
            var parent = Enumerable.Range(0, count).ToArray();
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
            for (int i = 0; i < count; i++)
                for (int j = i + 1; j < count; j++)
                    if (GapBetween(entries[i].Item2, entries[j].Item2) <= gapFt + 1e-9)
                    {
                        int ri = find(i), rj = find(j);
                        if (ri != rj) parent[rj] = ri;
                    }
            var groups = new Dictionary<int, List<Element>>();
            var order = new List<int>();
            for (int i = 0; i < count; i++)
            {
                int root = find(i);
                if (!groups.ContainsKey(root))
                {
                    groups[root] = new List<Element>();
                    order.Add(root);
                }
                groups[root].Add(entries[i].Item1);
            }
            return order.Select(r => groups[r]).ToList();
        }

        /// <summary>Boxes of every BWIC instance already in the model.</summary>
        public static List<Box> ExistingBwicBoxes(Document doc)
        {
            var boxes = new List<Box>();
            foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FamilyInstance)).WhereElementIsNotElementType())
            {
                var inst = (FamilyInstance)e;
                try
                {
                    if (inst.Symbol == null || inst.Symbol.Family == null) continue;
                    if (inst.Symbol.Family.Name != FamilyName) continue;
                }
                catch (Exception) { continue; }
                Box box = WorldBox(inst);
                if (box != null) boxes.Add(box);
            }
            return boxes;
        }

        // ---------------------------------------------------------------- the placement itself

        /// <summary>Places and sizes one BWIC around a group of services; never pins. Returns the instance (null when skipped) and fills notes.</summary>
        public static FamilyInstance PlaceOne(Document doc, IList<Element> services, Wall wall, Transform transform, double clearanceFt,
                                              FamilySymbol symbol, GlobalSettings options, Workset workset, List<XYZ> corners,
                                              double[] span, List<string> notes)
        {
            double? thicknessN = BwicCore.GetWallThickness(wall);
            if (thicknessN == null)
            {
                notes.Add("could not read a thickness from that wall");
                return null;
            }
            double thickness = thicknessN.Value;
            Curve wallCurve = ((LocationCurve)wall.Location).Curve.CreateTransformed(transform);
            var frame = new WallFrame(wallCurve);

            if (corners == null || corners.Count == 0)
            {
                corners = new List<XYZ>();
                foreach (Element el in services) corners.AddRange(BboxCorners(el));
            }
            if (corners.Count == 0)
            {
                notes.Add("the selected elements have no geometry to measure");
                return null;
            }
            var stations = new List<double>();
            var offsets = new List<double>();
            foreach (XYZ point in corners)
            {
                double[] station = frame.Station(point);
                if (station == null)
                {
                    notes.Add("could not relate this group to the wall");
                    return null;
                }
                stations.Add(station[0]);
                offsets.Add(station[1]);
            }
            double drift = offsets.Max();
            if (drift > (thickness / 2.0) + Ft(OffWallToleranceMm))
            {
                notes.Add("the crossing measures " + Mm(drift).ToString("0") + " mm off the wall centre line");
                return null;
            }
            double uMin, uMax, zMin, zMax;
            if (span != null)
            {
                uMin = span[0]; uMax = span[1]; zMin = span[2]; zMax = span[3];
            }
            else
            {
                uMin = stations.Min(); uMax = stations.Max();
                zMin = corners.Min(p => p.Z); zMax = corners.Max(p => p.Z);
            }
            double uMid = (uMin + uMax) / 2.0;
            double width = RoundUpFt((uMax - uMin) + 2 * clearanceFt);
            double height = RoundUpFt((zMax - zMin) + 2 * clearanceFt);
            double length = thickness;

            XYZ planPt, along, normal;
            frame.FrameAt(uMid, out planPt, out along, out normal);

            double targetZ = ElevationMode == "highest_service" ? services.Max(el => ElementCentreZ(el)) : (zMin + zMax) / 2.0;
            double originZ;
            if (OriginVertical == "bottom") originZ = targetZ - height / 2.0;
            else if (OriginVertical == "top") originZ = targetZ + height / 2.0;
            else originZ = targetZ;
            var targetPoint = new XYZ(planPt.X, planPt.Y, originZ);

            List<Level> levels = SortedLevels(doc);
            if (levels.Count == 0)
            {
                notes.Add("this project has no levels");
                return null;
            }
            Level level = LevelBelow(levels, originZ);

            if (!symbol.IsActive)
            {
                symbol.Activate();
                doc.Regenerate();
            }
            FamilySymbol placeSymbol = symbol;
            if (new[] { PLength, PWidth, PHeight }.Any(n => BwicCore.HasLengthParam(symbol, n)) && DuplicateTypeIfTypeParams)
            {
                string newName = BwicCore.UniqueTypeName(symbol, length, width, height);
                FamilySymbol existing = BwicCore.FindSymbolByName(doc, symbol.Family, newName);
                placeSymbol = existing ?? (FamilySymbol)symbol.Duplicate(newName);
                if (!placeSymbol.IsActive) placeSymbol.Activate();
                doc.Regenerate();
                notes.Add("sized on type \"" + newName + "\"");
            }
            var writes = new[] { Tuple.Create(PLength, length), Tuple.Create(PWidth, width), Tuple.Create(PHeight, height) };
            string msg;
            foreach (var w in writes)
                if (BwicCore.HasLengthParam(placeSymbol, w.Item1))
                    if (!BwicCore.SetLengthParam(placeSymbol, w.Item1, w.Item2, out msg)) notes.Add(msg);
            doc.Regenerate();

            FamilyInstance instance;
            try { instance = doc.Create.NewFamilyInstance(targetPoint, placeSymbol, level, StructuralType.NonStructural); }
            catch (Exception) { instance = doc.Create.NewFamilyInstance(targetPoint, placeSymbol, StructuralType.NonStructural); }
            doc.Regenerate();

            foreach (var w in writes)
            {
                if (BwicCore.HasLengthParam(instance, w.Item1))
                {
                    if (!BwicCore.SetLengthParam(instance, w.Item1, w.Item2, out msg)) notes.Add(msg);
                }
                else if (!BwicCore.HasLengthParam(placeSymbol, w.Item1)) notes.Add(w.Item1 + " not found on the family");
            }
            doc.Regenerate();

            try
            {
                XYZ facing = instance.FacingOrientation;
                facing = new XYZ(facing.X, facing.Y, 0);
                if (facing.GetLength() > 1e-9)
                {
                    double angle = facing.Normalize().AngleOnPlaneTo(normal, XYZ.BasisZ);
                    if (Math.Abs(angle) > 1e-9)
                    {
                        Line axis = Line.CreateBound(targetPoint, targetPoint + XYZ.BasisZ);
                        ElementTransformUtils.RotateElement(doc, instance.Id, axis, angle);
                    }
                }
            }
            catch (Exception err)
            {
                notes.Add("rotation skipped: " + err.Message);
            }
            doc.Regenerate();

            var loc = instance.Location as LocationPoint;
            if (loc != null)
            {
                XYZ delta = targetPoint - loc.Point;
                if (delta.GetLength() > 1e-9) ElementTransformUtils.MoveElement(doc, instance.Id, delta);
            }
            doc.Regenerate();

            if (options.UseWorkset)
            {
                if (workset == null)
                    notes.Add("workset \"" + (FamilyWorkset.Length > 0 ? FamilyWorkset : WorksetName.Length > 0 ? WorksetName : WorksetKeyword) + "\" not found");
                else if (AssignWorkset(instance, workset)) notes.Add("workset \"" + workset.Name + "\"");
                else notes.Add("could not set the workset");
            }

            if (!string.IsNullOrEmpty(options.LevelParam))
            {
                string code = LevelCode(level, levels);
                if (BwicCore.SetLevelCode(instance, options.LevelParam, code, out msg)) notes.Add(options.LevelParam + " = " + code + " (" + level.Name + ")");
                else notes.Add(msg);
            }
            else notes.Add("level " + level.Name);

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
                        else notes.Add("Comments parameter is not writable");
                    }
                    else notes.Add("nothing to log to Comments");
                }
                catch (Exception err)
                {
                    notes.Add("comments log failed: " + err.Message);
                }
            }
            notes.Add("L " + Mm(length).ToString("0") + " / W " + Mm(width).ToString("0") + " / H " + Mm(height).ToString("0") + " mm at " + Mm(targetZ).ToString("0") + " mm");
            return instance;
        }

        // ---------------------------------------------------------------- keeping Revit quiet

        /// <summary>Dismisses warning dialogs and keeps a tally of what it dismissed; errors are left for Revit.</summary>
        public sealed class WarningCounter : IFailuresPreprocessor
        {
            private readonly Dictionary<string, int> _counts = new Dictionary<string, int>();
            private readonly List<string> _order = new List<string>();
            public int Errors;

            private void Record(string text)
            {
                if (!_counts.ContainsKey(text))
                {
                    _counts[text] = 0;
                    _order.Add(text);
                }
                _counts[text]++;
            }

            public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
            {
                IList<FailureMessageAccessor> messages;
                try { messages = accessor.GetFailureMessages(); }
                catch (Exception) { return FailureProcessingResult.Continue; }
                foreach (FailureMessageAccessor failure in messages)
                {
                    string text;
                    try { text = failure.GetDescriptionText(); }
                    catch (Exception) { text = "unnamed Revit message"; }
                    if (string.IsNullOrEmpty(text)) text = "unnamed Revit message";
                    FailureSeverity severity;
                    try { severity = failure.GetSeverity(); }
                    catch (Exception) { severity = FailureSeverity.Warning; }
                    if (severity == FailureSeverity.Warning)
                    {
                        Record(text);
                        try { accessor.DeleteWarning(failure); }
                        catch (Exception) { }
                    }
                    else
                    {
                        Errors++;
                        Record(text + " (error)");
                    }
                }
                return FailureProcessingResult.Continue;
            }

            /// <summary>"message x12", busiest first.</summary>
            public List<string> Summary()
            {
                return _order.OrderByDescending(t => _counts[t]).Select(t => _counts[t] > 1 ? t + " x" + _counts[t] : t).ToList();
            }
        }

        /// <summary>A started transaction that will not stop to ask about warnings.</summary>
        public static Transaction QuietTransaction(Document doc, string name, WarningCounter swallower)
        {
            var trans = new Transaction(doc, name);
            trans.Start();
            if (swallower != null)
            {
                try
                {
                    FailureHandlingOptions options = trans.GetFailureHandlingOptions();
                    options.SetFailuresPreprocessor(swallower);
                    options.SetClearAfterRollback(true);
                    trans.SetFailureHandlingOptions(options);
                }
                catch (Exception) { }
            }
            return trans;
        }

        // ---------------------------------------------------------------- not placing the same BWIC twice

        public static double[] BoxSize(Box box)
        {
            return new[] { Math.Abs(box.Max.X - box.Min.X), Math.Abs(box.Max.Y - box.Min.Y), Math.Abs(box.Max.Z - box.Min.Z) };
        }

        /// <summary>True when a BWIC of the same size already sits at this spot.</summary>
        public static bool AlreadyPlacedHere(Box box, IEnumerable<Box> records, double toleranceFt)
        {
            if (box == null) return false;
            XYZ centre = BoxCentre(box);
            double[] size = BoxSize(box);
            foreach (Box other in records)
            {
                if (other == null) continue;
                if (centre.DistanceTo(BoxCentre(other)) > toleranceFt) continue;
                double[] os = BoxSize(other);
                if (Math.Abs(size[0] - os[0]) <= toleranceFt && Math.Abs(size[1] - os[1]) <= toleranceFt && Math.Abs(size[2] - os[2]) <= toleranceFt) return true;
            }
            return false;
        }

        // ---------------------------------------------------------------- clashes between the BWICs this run places

        /// <summary>Indices of records whose boxes overlap another in all three axes, and the pairs.</summary>
        public static List<int> FindClashes(IList<PlacedRecord> records, double toleranceFt, out int pairCount)
        {
            var clashing = new SortedSet<int>();
            pairCount = 0;
            for (int i = 0; i < records.Count; i++)
                for (int j = i + 1; j < records.Count; j++)
                    if (BoxesOverlap(records[i].Box, records[j].Box, toleranceFt))
                    {
                        clashing.Add(i);
                        clashing.Add(j);
                        pairCount++;
                    }
            return clashing.ToList();
        }

        /// <summary>Detail lines are view specific and 3D views will not take them.</summary>
        public static bool ViewTakesDetailLines(View view)
        {
            if (view == null || view.IsTemplate) return false;
            switch (view.ViewType)
            {
                case ViewType.FloorPlan:
                case ViewType.CeilingPlan:
                case ViewType.EngineeringPlan:
                case ViewType.AreaPlan:
                case ViewType.Section:
                case ViewType.Elevation:
                case ViewType.Detail:
                case ViewType.DraftingView:
                    return true;
            }
            return false;
        }

        /// <summary>A line style for the marks, created in the given colour if new.</summary>
        public static GraphicsStyle MarkerLineStyle(Document doc, string name, byte[] rgb)
        {
            Categories categories = doc.Settings.Categories;
            Category lines;
            try { lines = categories.get_Item(BuiltInCategory.OST_Lines); }
            catch (Exception) { return null; }
            Category subcategory = null;
            foreach (Category sub in lines.SubCategories)
                if (sub.Name == name)
                {
                    subcategory = sub;
                    break;
                }
            if (subcategory == null)
            {
                try
                {
                    subcategory = categories.NewSubcategory(lines, name);
                    subcategory.LineColor = new Color(rgb[0], rgb[1], rgb[2]);
                    try { subcategory.SetLineWeight(5, GraphicsStyleType.Projection); }
                    catch (Exception) { }
                }
                catch (Exception) { return null; }
            }
            try { return subcategory.GetGraphicsStyle(GraphicsStyleType.Projection); }
            catch (Exception) { return null; }
        }

        /// <summary>Rectangle in the plane of the view around a 3D box.</summary>
        public static List<Line> ViewPlaneRectangle(View view, Box box, double marginFt)
        {
            XYZ origin = view.Origin, right = view.RightDirection, up = view.UpDirection;
            var corners = new List<XYZ>();
            foreach (double x in new[] { box.Min.X, box.Max.X })
                foreach (double y in new[] { box.Min.Y, box.Max.Y })
                    foreach (double z in new[] { box.Min.Z, box.Max.Z })
                        corners.Add(new XYZ(x, y, z));
            var aValues = corners.Select(p => (p - origin).DotProduct(right)).ToList();
            var bValues = corners.Select(p => (p - origin).DotProduct(up)).ToList();
            double aMin = aValues.Min() - marginFt, aMax = aValues.Max() + marginFt;
            double bMin = bValues.Min() - marginFt, bMax = bValues.Max() + marginFt;
            Func<double, double, XYZ> pt = (a, b) => origin + right.Multiply(a) + up.Multiply(b);
            XYZ[] pts = { pt(aMin, bMin), pt(aMax, bMin), pt(aMax, bMax), pt(aMin, bMax) };
            var lines = new List<Line>();
            for (int index = 0; index < 4; index++)
            {
                XYZ start = pts[index], end = pts[(index + 1) % 4];
                if (start.DistanceTo(end) > 1e-6) lines.Add(Line.CreateBound(start, end));
            }
            return lines;
        }

        /// <summary>Draw a rectangle around each box in the view. Returns the line ids.</summary>
        public static List<ElementId> MarkBoxes(Document doc, View view, IEnumerable<Box> boxes, double marginFt, GraphicsStyle style)
        {
            var created = new List<ElementId>();
            foreach (Box box in boxes)
                foreach (Line line in ViewPlaneRectangle(view, box, marginFt))
                {
                    DetailCurve curve;
                    try { curve = doc.Create.NewDetailCurve(view, line); }
                    catch (Exception) { continue; }
                    if (style != null)
                    {
                        try { curve.LineStyle = style; }
                        catch (Exception) { }
                    }
                    created.Add(curve.Id);
                }
            return created;
        }

        /// <summary>Gather the marks into one named group. Returns the name, or null.</summary>
        public static string GroupMarks(Document doc, IList<ElementId> lineIds, string name)
        {
            if (lineIds.Count == 0) return null;
            Group group;
            try { group = doc.Create.NewGroup(lineIds.ToList()); }
            catch (Exception) { return null; }
            try
            {
                group.GroupType.Name = name;
            }
            catch (Exception)
            {
                try
                {
                    group.GroupType.Name = name + " " + BwicCore.EidValue(group.Id);
                    name = group.GroupType.Name;
                }
                catch (Exception) { return null; }
            }
            return name;
        }

        // ---------------------------------------------------------------- one Settings for the whole tool

        /// <summary>Take the family, types, sizes and workset from the tool's Settings (the Wall tab and this tab read the same ones).</summary>
        public static void Configure(Dictionary<string, string> settings)
        {
            Func<string, string> get = k => BwicFamilies.Get(settings, k);
            if (get("wall_family").Length > 0) FamilyName = get("wall_family");
            if (get("wall_type_firerated").Length > 0) TypeFire = get("wall_type_firerated");
            if (get("wall_type_blockwork").Length > 0) TypeBlockwork = get("wall_type_blockwork");
            if (get("wall_length_param").Length > 0) PLength = get("wall_length_param");
            if (get("wall_width_param").Length > 0) PWidth = get("wall_width_param");
            if (get("wall_height_param").Length > 0) PHeight = get("wall_height_param");
            double v;
            if (get("round_up").Length > 0 && BwicCore.TryNumber(get("round_up"), out v)) RoundUpMm = v;
            WorksetName = get("workset");
            FamilyWorkset = get("family_workset");
            FamilyClearance = get("family_clearance");
        }

        // ---------------------------------------------------------------- the global sweep

        private static string Plural(int n, string one = "", string many = "s") { return n == 1 ? one : many; }

        /// <summary>Walk every wall in the link that needs BWICs and place them. Returns a summary, or null when the run could not start.</summary>
        public static GlobalSummary RunGlobalPlacement(UIApplication uiapp, GlobalSettings settings, Action<string> report)
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            if (uidoc == null)
            {
                report("No active Revit document.");
                return null;
            }
            Document doc = uidoc.Document;
            View view = doc.ActiveView;
            var log = new List<string>();
            Action<string> note = line =>
            {
                log.Add(line);
                BwicCore.DebugLog(line);
            };

            if (view == null || view.IsTemplate || view is ViewSheet || view is ViewSchedule)
            {
                report("Open a model view -- this tool works on the active view.");
                return null;
            }
            var symbols = FamilySymbols(doc);
            FamilySymbol defaultSymbol = FindFamilySymbol(doc);
            if (symbols.Count == 0 || defaultSymbol == null)
            {
                report("The family \"" + FamilyName + "\" is not loaded in this project.");
                return null;
            }
            var symbolFor = new Dictionary<string, FamilySymbol>();
            foreach (var pair in new[] { Tuple.Create("fire", TypeFire), Tuple.Create("blockwork", TypeBlockwork) })
            {
                FamilySymbol chosen;
                if (!symbols.TryGetValue(pair.Item2, out chosen))
                {
                    chosen = defaultSymbol;
                    note("Type \"" + pair.Item2 + "\" is not in the family -- " + pair.Item1 + " walls fall back to \"" + defaultSymbol.Name + "\".");
                }
                symbolFor[pair.Item1] = chosen;
            }
            var link = settings.LinkId != null ? doc.GetElement(settings.LinkId) as RevitLinkInstance : null;
            if (link == null)
            {
                report("Choose the link to read the walls from.");
                return null;
            }
            Document linkDoc = link.GetLinkDocument();
            if (linkDoc == null)
            {
                report("That link is not loaded.");
                return null;
            }
            Transform transform = link.GetTotalTransform();

            double clearanceMm = settings.ClearanceMm > 0 ? settings.ClearanceMm : 50.0;
            if (FamilyClearance.Length > 0)
            {
                double fc;
                if (BwicCore.TryNumber(FamilyClearance, out fc))
                {
                    clearanceMm = fc;
                    note("Clearance " + BwicFamilies.G(clearanceMm) + " mm from the family's Family settings.");
                }
            }
            double clearanceFt = Ft(clearanceMm);
            var gaps = new Dictionary<long, double>
            {
                { BicId(CatPipes), Ft(settings.GapPipesMm) },
                { BicId(CatTrays), Ft(settings.GapTraysMm) },
                { BicId(CatConduit), Ft(settings.GapConduitMm > 0 ? settings.GapConduitMm : DefaultGapConduitMm) },
            };
            var options = new GlobalSettings
            {
                LogComments = settings.LogComments, UseWorkset = settings.UseWorkset, LevelParam = settings.LevelParam,
            };
            if (FamilyWorkset == ActiveWorkset) options.UseWorkset = false;
            Workset workset = options.UseWorkset ? FindBwicWorkset(doc) : null;
            if (options.UseWorkset && workset == null)
            {
                if (doc.IsWorkshared && FamilyWorkset.Length > 0)
                    note("Workset \"" + FamilyWorkset + "\" from the family's Family settings is not in this model -- BWICs land on the active workset.");
                else if (doc.IsWorkshared) note("No workset containing \"" + WorksetKeyword + "\" -- BWICs land on the active workset.");
                else note("This model is not workshared -- skipping the workset step.");
            }

            List<WallToPenetrate> walls = WallsToPenetrate(linkDoc);
            if (walls.Count == 0)
            {
                report("No walls in \"" + link.Name + "\" are fire rated (" + FireParam + ") or blockwork (" + BlockworkKeyword + " in the type name).");
                return null;
            }
            Outline crop = ViewOutline(view);

            List<Element> visibleServices = ServicesInView(doc, view);
            if (visibleServices.Count == 0)
            {
                report("No pipes or cable trays are visible in \"" + view.Name + "\". Open the plan for the floor you want to do and run it again.");
                return null;
            }
            Box reach = CombinedBox(visibleServices, Ft(ServiceReachMm));

            List<Box> prior = SkipExisting ? ExistingBwicBoxes(doc) : new List<Box>();
            var placedRecords = new List<PlacedRecord>();

            int fireCount = walls.Count(w => w.Kind == "fire");
            int blockCount = walls.Count - fireCount;
            note(walls.Count + " wall" + Plural(walls.Count) + " to look at in \"" + link.Name + "\" -- " + fireCount + " fire rated, " + blockCount + " blockwork.");
            note(visibleServices.Count + " pipe / cable tray element" + Plural(visibleServices.Count) + " visible in \"" + view.Name + "\" -- that is the floor this run covers.");
            if (crop != null) note("Limited to the active view's crop / section box.");

            WarningCounter swallower = SuppressWarnings ? new WarningCounter() : null;
            double duplicateTol = Ft(DuplicateToleranceMm);

            int outOfReach = 0, wallsHit = 0, groupsFound = 0, placed = 0, skippedExisting = 0, duplicates = 0, unmeasured = 0;
            var failures = new List<FailureRecord>();
            var clashing = new List<int>();
            int pairCount = 0;
            var reviewIds = new List<ElementId>();
            string groupName = null, failedGroupName = null;

            var groupHolder = new TransactionGroup(doc, "BWIC Global Placement");
            groupHolder.Start();
            try
            {
                foreach (WallToPenetrate item in walls)
                {
                    Wall wall = item.Wall;
                    string kind = item.Kind;
                    Box wallBox = WorldBox(wall, transform);
                    if (wallBox == null || !OutlineHits(crop, wallBox)) continue;
                    if (!BoxesTouch(wallBox, reach))
                    {
                        outOfReach++;
                        continue;
                    }
                    Solid solid = WallSolid(wall, transform);
                    if (solid == null)
                    {
                        failures.Add(new FailureRecord { Text = "wall " + BwicCore.EidValue(wall.Id) + " (" + kind + "): no solid geometry", Box = null });
                        continue;
                    }
                    FamilySymbol symbol = symbolFor[kind];
                    Curve wallCurve = ((LocationCurve)wall.Location).Curve.CreateTransformed(transform);
                    var frame = new WallFrame(wallCurve);
                    List<Element> services = ServicesThroughWall(doc, view, solid, wallBox, frame);
                    if (services.Count == 0) continue;
                    wallsHit++;

                    var byCategory = new Dictionary<long, List<Tuple<Element, double[]>>>();
                    var categoryOrder = new List<long>();
                    var crossings = new Dictionary<long, List<XYZ>>();
                    var memberExtents = new Dictionary<long, double[]>();
                    foreach (Element el in services)
                    {
                        long? key = CategoryId(el);
                        if (key == null || !gaps.ContainsKey(key.Value)) continue;
                        List<XYZ> corners = CrossingCorners(el, solid);
                        double? width = WidthFromSection ? SectionWidth(el) : null;
                        double[] extents = WallExtents(corners, frame, width);
                        if (extents == null)
                        {
                            unmeasured++;
                            continue;
                        }
                        long id = BwicCore.EidValue(el.Id);
                        crossings[id] = corners;
                        memberExtents[id] = extents;
                        if (!byCategory.ContainsKey(key.Value))
                        {
                            byCategory[key.Value] = new List<Tuple<Element, double[]>>();
                            categoryOrder.Add(key.Value);
                        }
                        byCategory[key.Value].Add(Tuple.Create(el, extents));
                    }

                    var buckets = new List<Tuple<List<Tuple<Element, double[]>>, double>>();
                    if (kind == "blockwork" && BlockworkSharesHole)
                    {
                        var shared = new List<Tuple<Element, double[]>>();
                        foreach (long k in categoryOrder) shared.AddRange(byCategory[k]);
                        if (shared.Count > 0) buckets.Add(Tuple.Create(shared, gaps.Values.Max()));
                    }
                    else
                    {
                        foreach (long k in categoryOrder) buckets.Add(Tuple.Create(byCategory[k], gaps[k]));
                    }

                    foreach (var bucket in buckets)
                    {
                        foreach (List<Element> group in ClusterByGap(bucket.Item1, bucket.Item2))
                        {
                            groupsFound++;
                            var corners = new List<XYZ>();
                            var spans = new List<double[]>();
                            foreach (Element el in group)
                            {
                                long id = BwicCore.EidValue(el.Id);
                                List<XYZ> c;
                                if (crossings.TryGetValue(id, out c)) corners.AddRange(c);
                                double[] member;
                                if (memberExtents.TryGetValue(id, out member) && member != null) spans.Add(member);
                            }
                            double[] span = UnionExtents(spans);
                            Box box = CornersBox(corners);

                            if (SkipExisting && box != null && prior.Any(other => BoxesOverlap(box, other)))
                            {
                                skippedExisting++;
                                continue;
                            }
                            if (AlreadyPlacedHere(box, placedRecords.Select(r => r.Box), duplicateTol) || AlreadyPlacedHere(box, prior, duplicateTol))
                            {
                                duplicates++;
                                continue;
                            }

                            Transaction trans = QuietTransaction(doc, "Place BWIC penetration", swallower);
                            try
                            {
                                var notes = new List<string>();
                                FamilyInstance instance = PlaceOne(doc, group, wall, transform, clearanceFt, symbol, options, workset, corners, span, notes);
                                if (instance == null)
                                {
                                    trans.RollBack();
                                    failures.Add(new FailureRecord { Text = "wall " + BwicCore.EidValue(wall.Id) + " (" + kind + "): " + string.Join("; ", notes), Box = box });
                                }
                                else
                                {
                                    Box newBox = WorldBox(instance) ?? box;
                                    if (newBox != null && !BoxesOverlap(newBox, wallBox, -Ft(1.0)))
                                    {
                                        trans.RollBack();
                                        failures.Add(new FailureRecord
                                        {
                                            Text = "wall " + BwicCore.EidValue(wall.Id) + " (" + kind + "): the BWIC landed off the wall and was not kept", Box = box,
                                        });
                                    }
                                    else
                                    {
                                        trans.Commit();
                                        placed++;
                                        if (newBox != null) placedRecords.Add(new PlacedRecord { Id = instance.Id, Box = newBox });
                                    }
                                }
                            }
                            catch (Exception err)
                            {
                                if (trans.HasStarted()) trans.RollBack();
                                failures.Add(new FailureRecord { Text = "wall " + BwicCore.EidValue(wall.Id) + " (" + kind + "): " + err.Message, Box = box });
                                BwicCore.DebugLog("global placement error: " + err);
                            }
                            finally
                            {
                                trans.Dispose();
                            }
                        }
                    }
                }

                // mark what needs a human: overlaps, and anything that failed
                clashing = FindClashes(placedRecords, Ft(ClashToleranceMm), out pairCount);
                reviewIds = clashing.Where(i => placedRecords[i].Id != null).Select(i => placedRecords[i].Id).ToList();
                var failedBoxes = failures.Where(f => f.Box != null).Select(f => f.Box).ToList();
                var clashBoxes = clashing.Select(i => placedRecords[i].Box).ToList();
                bool wantMarks = (clashBoxes.Count > 0 && MarkClashes) || (failedBoxes.Count > 0 && MarkFailures);
                if (wantMarks && !ViewTakesDetailLines(view))
                    note("Nothing could be marked -- this view will not take detail lines. Run in a plan or section for the red boxes.");
                else if (wantMarks)
                {
                    string stamp = DateTime.Now.ToString("yyyy-MM-dd HH-mm");
                    var markJobs = new List<Tuple<string, List<Box>, string, byte[], string>>();
                    if (clashBoxes.Count > 0 && MarkClashes)
                        markJobs.Add(Tuple.Create("clash", clashBoxes, ClashLineStyle, new byte[] { 255, 0, 0 }, ClashGroupName + " " + stamp));
                    if (failedBoxes.Count > 0 && MarkFailures)
                        markJobs.Add(Tuple.Create("failed", failedBoxes, FailedLineStyle, new byte[] { 255, 150, 0 }, FailedGroupName + " " + stamp));
                    foreach (var mj in markJobs)
                    {
                        string label = mj.Item1;
                        List<ElementId> lineIds;
                        Transaction marks = QuietTransaction(doc, "Mark BWIC " + label, swallower);
                        try
                        {
                            GraphicsStyle style = MarkerLineStyle(doc, mj.Item3, mj.Item4);
                            lineIds = MarkBoxes(doc, view, mj.Item2, Ft(ClashMarginMm), style);
                            marks.Commit();
                        }
                        catch (Exception err)
                        {
                            if (marks.HasStarted()) marks.RollBack();
                            lineIds = new List<ElementId>();
                            note("Could not draw the " + label + " marks: " + err.Message);
                        }
                        finally
                        {
                            marks.Dispose();
                        }
                        if (lineIds.Count == 0) continue;
                        string made;
                        Transaction grouping = QuietTransaction(doc, "Group BWIC " + label + " marks", swallower);
                        try
                        {
                            made = GroupMarks(doc, lineIds, mj.Item5);
                            grouping.Commit();
                        }
                        catch (Exception err)
                        {
                            if (grouping.HasStarted()) grouping.RollBack();
                            made = null;
                            note("Could not group the " + label + " marks: " + err.Message);
                        }
                        finally
                        {
                            grouping.Dispose();
                        }
                        if (label == "clash") groupName = made;
                        else failedGroupName = made;
                    }
                }
                groupHolder.Assimilate();
            }
            catch (Exception err)
            {
                if (groupHolder.HasStarted()) groupHolder.RollBack();
                report("Run stopped: " + err.Message);
                BwicCore.DebugLog("global run stopped: " + err);
                return null;
            }

            if (outOfReach > 0)
                note(outOfReach + " wall" + Plural(outOfReach) + " sat away from anything visible here and " + (outOfReach == 1 ? "was" : "were") + " not looked at.");
            note(wallsHit + " wall" + Plural(wallsHit) + " with services passing through, " + groupsFound + " group" + Plural(groupsFound) + " found.");
            if (skippedExisting > 0)
                note(skippedExisting + " group" + Plural(skippedExisting) + " already had a BWIC and " + (skippedExisting == 1 ? "was" : "were") + " left alone.");
            if (duplicates > 0) note(duplicates + " opening" + Plural(duplicates) + " came up twice -- the repeat was dropped.");
            if (unmeasured > 0)
                note(unmeasured + " service" + Plural(unmeasured) + " could not be measured at the wall and " + (unmeasured == 1 ? "was" : "were") + " left out.");
            if (failures.Count > 0)
            {
                note(failures.Count + " placement" + Plural(failures.Count) + " failed -- see the debug file for detail.");
                foreach (FailureRecord f in failures.Take(20)) BwicCore.DebugLog("global failure: " + f.Text);
            }
            if (clashing.Count > 0)
                note(clashing.Count + " of the BWICs placed overlap" + (clashing.Count == 1 ? "s" : "") + " another in 3D -- marked To Review.");
            if (groupName != null) note("Overlap marks grouped as \"" + groupName + "\".");
            if (failedGroupName != null) note("Failure marks grouped as \"" + failedGroupName + "\".");
            note(placed + " BWIC placed.");

            List<string> warnings = swallower != null ? swallower.Summary() : new List<string>();
            if (warnings.Count > 0)
            {
                note("Revit messages dismissed during the run:");
                foreach (string line in warnings.Take(8)) note("  - " + line);
                if (warnings.Count > 8) note("  - and " + (warnings.Count - 8) + " more, see the debug file.");
                foreach (string line in warnings) BwicCore.DebugLog("dismissed: " + line);
            }
            report(string.Join("\n", log));
            return new GlobalSummary
            {
                Placed = placed, Review = clashing.Count, ClashPairs = pairCount, ReviewIds = reviewIds, Skipped = skippedExisting, Duplicates = duplicates,
                Unmeasured = unmeasured, FailedGroupName = failedGroupName, Warnings = warnings, Failed = failures.Count, Groups = groupsFound,
                Walls = wallsHit, GroupName = groupName, Log = log,
            };
        }
    }
}
