using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;
using OperationCanceledException = Autodesk.Revit.Exceptions.OperationCanceledException;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.BwicPenetration
{
    /// <summary>Size and position a wall opening needs (the dict compute_bwic returned).</summary>
    public sealed class WallGeom
    {
        public double Length, Width, Height, TargetZ;
        public XYZ Point, Normal;
        public Level Level, PreferredLevel;
        public List<Level> Levels;
    }

    public static partial class BwicCore
    {
        // ---------------------------------------------------------------- the placement itself

        /// <summary>Work out the size and position an opening needs. No model changes. Shared by place and resize.</summary>
        public static WallGeom ComputeBwic(Document doc, IList<Service> services, Wall wall, Transform transform, double clearanceFt,
                                           Level preferredLevel, out string error)
        {
            error = null;
            double? thickness = GetWallThickness(wall);
            if (thickness == null)
            {
                error = "could not read a thickness from that wall";
                return null;
            }
            Curve wallCurve = ((LocationCurve)wall.Location).Curve.CreateTransformed(transform);
            var corners = new List<XYZ>();
            foreach (Service service in services) corners.AddRange(ServicePoints(service));
            if (corners.Count == 0)
            {
                error = "the selected elements have no geometry to measure";
                return null;
            }
            var centroid = new XYZ(corners.Average(p => p.X), corners.Average(p => p.Y), corners.Average(p => p.Z));
            XYZ basePt, along, normal;
            WallFrameAt(wallCurve, centroid, out basePt, out along, out normal);

            // measure again, counting straight runs only inside the wall
            var plane = new WallPlane(new XYZ(basePt.X, basePt.Y, 0), new XYZ(normal.X, normal.Y, 0).Normalize(), thickness.Value / 2.0);
            var inside = new List<XYZ>();
            foreach (Service service in services) inside.AddRange(ServicePoints(service, plane));
            if (inside.Count > 0)
            {
                DebugLog("services measured inside the wall: " + FtToMm(Spread(inside, along)).ToString("0.0") + " x "
                         + FtToMm(SpreadZ(inside)).ToString("0.0") + " mm (whole runs " + FtToMm(Spread(corners, along)).ToString("0.0")
                         + " x " + FtToMm(SpreadZ(corners)).ToString("0.0") + " mm)");
                corners = inside;
            }
            var uValues = corners.Select(p => p.X * along.X + p.Y * along.Y).ToList();
            double uMin = uValues.Min(), uMax = uValues.Max(), uMid = (uMin + uMax) / 2.0;
            double zMin = corners.Min(p => p.Z), zMax = corners.Max(p => p.Z);
            double width = RoundUpFt((uMax - uMin) + 2 * clearanceFt);
            double height = RoundUpFt((zMax - zMin) + 2 * clearanceFt);
            double length = thickness.Value;

            if (RoundWall != null)
            {
                double outerMm = 0;
                if (services.Count == 1)
                {
                    string source;
                    bool isOuter;
                    double dia = OutsideDiameter(services[0].Element, out source, out isOuter);
                    if (dia > 0)
                    {
                        if (RoundWall.Insulation) dia += 2 * InsulationThickness(services[0].Element);
                        outerMm = FtToMm(dia);
                        DebugLog("round hole from " + source + " " + outerMm.ToString("0.0") + " mm");
                    }
                }
                double holeMm = BwicFamilies.RoundHoleMm(outerMm, FtToMm(uMax - uMin), FtToMm(zMax - zMin), RoundWall.GapMm, RoundWall.RoundMm);
                DebugLog("round hole " + holeMm.ToString("0") + " mm (" + (outerMm > 0 ? "outside diameter"
                         : "circle around " + FtToMm(uMax - uMin).ToString("0") + " x " + FtToMm(zMax - zMin).ToString("0") + " mm") + ")");
                width = height = MmToFt(holeMm);
            }

            // slide along the wall to the middle of the selection, then re-project so the instance stays on the centre line
            XYZ planPt;
            for (int i = 0; i < 2; i++)
            {
                double baseU = basePt.X * along.X + basePt.Y * along.Y;
                planPt = basePt + along * (uMid - baseU);
                WallFrameAt(wallCurve, planPt, out basePt, out along, out normal);
            }
            double baseU2 = basePt.X * along.X + basePt.Y * along.Y;
            planPt = basePt + along * (uMid - baseU2);

            double targetZ = ElevationMode == "highest_service" ? services.Max(sv => ElementCentreZ(sv)) : (zMin + zMax) / 2.0;
            double originZ;
            if (OriginVertical == "bottom") originZ = targetZ - height / 2.0;
            else if (OriginVertical == "top") originZ = targetZ + height / 2.0;
            else originZ = targetZ;

            List<Level> levels = SortedLevels(doc);
            if (levels.Count == 0)
            {
                error = "this project has no levels";
                return null;
            }
            Level level = preferredLevel ?? LevelBelow(levels, originZ);
            return new WallGeom
            {
                Length = length, Width = width, Height = height, Point = new XYZ(planPt.X, planPt.Y, originZ), Normal = normal,
                TargetZ = targetZ, Level = level, Levels = levels, PreferredLevel = preferredLevel,
            };
        }

        /// <summary>The family type to use, with the type level sizes written if needed.</summary>
        public static FamilySymbol SizedSymbol(Document doc, FamilySymbol symbol, WallGeom geom, List<string> notes)
        {
            if (!symbol.IsActive)
            {
                symbol.Activate();
                doc.Regenerate();
            }
            double length = geom.Length, width = geom.Width, height = geom.Height;
            FamilySymbol placeSymbol = symbol;
            var writes = WallSizeWrites(length, width, height);
            if (writes.Any(w => w.Key.Length > 0 && HasLengthParam(symbol, w.Key)) && DuplicateTypeIfTypeParams)
            {
                string newName = UniqueTypeName(symbol, length, width, height);
                FamilySymbol existing = FindSymbolByName(doc, symbol.Family, newName);
                placeSymbol = existing ?? (FamilySymbol)symbol.Duplicate(newName);
                if (!placeSymbol.IsActive) placeSymbol.Activate();
                doc.Regenerate();
                notes.Add("sized on type \"" + newName + "\"");
            }
            foreach (var write in writes)
            {
                if (HasLengthParam(placeSymbol, write.Key))
                {
                    string msg;
                    if (!SetLengthParam(placeSymbol, write.Key, write.Value, out msg)) notes.Add(msg);
                }
            }
            doc.Regenerate();
            return placeSymbol;
        }

        /// <summary>Size, orient, position and stamp an instance. Shared by place and resize.</summary>
        public static void ApplyToInstance(Document doc, FamilyInstance instance, WallGeom geom, FamilySymbol placeSymbol,
                                           IList<Service> services, BwicOptions options, Workset workset, List<string> notes)
        {
            XYZ targetPoint = geom.Point;
            XYZ normal = geom.Normal;
            List<Level> levels = geom.Levels;
            foreach (var write in WallSizeWrites(geom.Length, geom.Width, geom.Height))
            {
                if (write.Key.Length == 0) continue;
                if (HasLengthParam(instance, write.Key))
                {
                    string msg;
                    if (!SetLengthParam(instance, write.Key, write.Value, out msg)) notes.Add(msg);
                }
                else if (!HasLengthParam(placeSymbol, write.Key)) notes.Add(BwicFamilies.ShowName(write.Key) + " not found on the family");
            }
            doc.Regenerate();

            // align the Front/Back reference plane to the wall centre line
            try
            {
                XYZ facing = instance.FacingOrientation;
                facing = new XYZ(facing.X, facing.Y, 0);
                if (facing.GetLength() > 1e-9)
                {
                    double angle = facing.Normalize().AngleOnPlaneTo(normal, XYZ.BasisZ);
                    if (Math.Abs(angle) > 1e-9)
                    {
                        var lp = instance.Location as LocationPoint;
                        XYZ origin = lp != null ? lp.Point : targetPoint;
                        Line axis = Line.CreateBound(origin, origin + XYZ.BasisZ);
                        ElementTransformUtils.RotateElement(doc, instance.Id, axis, angle);
                    }
                }
            }
            catch (Exception err)
            {
                notes.Add("rotation skipped: " + err.Message);
            }
            doc.Regenerate();

            // X, Y and Z in one move
            var loc = instance.Location as LocationPoint;
            if (loc != null)
            {
                XYZ delta = targetPoint - loc.Point;
                if (delta.GetLength() > 1e-9) ElementTransformUtils.MoveElement(doc, instance.Id, delta);
            }
            doc.Regenerate();

            // level: the one it sits on, or the nearest one beneath it, checked against the final position
            Level wantedLevel = geom.PreferredLevel ?? LevelBelow(levels, targetPoint.Z);
            Level actualLevel = GetInstanceLevel(doc, instance);
            if (wantedLevel != null && (actualLevel == null || actualLevel.Id != wantedLevel.Id))
            {
                if (SetInstanceLevel(doc, instance, wantedLevel))
                {
                    doc.Regenerate();
                    var loc2 = instance.Location as LocationPoint;
                    if (loc2 != null)
                    {
                        XYZ delta = targetPoint - loc2.Point;
                        if (delta.GetLength() > 1e-9) ElementTransformUtils.MoveElement(doc, instance.Id, delta);
                    }
                    doc.Regenerate();
                    actualLevel = GetInstanceLevel(doc, instance) ?? wantedLevel;
                }
                else notes.Add("could not move it onto level " + wantedLevel.Name);
            }
            Level level = actualLevel ?? wantedLevel ?? geom.Level;

            PlaceOnWorkset(doc, instance, options, workset, notes);

            if (!string.IsNullOrEmpty(options.LevelParam) && level != null)
            {
                string code = LevelCode(level, levels), msg;
                if (SetLevelCode(instance, options.LevelParam, code, out msg)) notes.Add(options.LevelParam + " = " + code + " (" + level.Name + ")");
                else notes.Add(msg);
            }
            else if (level != null) notes.Add("level " + level.Name);
            if (level != null && !string.IsNullOrEmpty(options.LevelSource)) notes.Add("level from the " + options.LevelSource);

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

            // pinning last, so nothing else has to fight a pinned element
            if (options.Pin)
            {
                int pinnedServices = services.Count(sv => !sv.Linked && PinElement(sv.Element));
                bool pinnedBwic = PinElement(instance);
                notes.Add("pinned " + pinnedServices + " service" + (pinnedServices == 1 ? "" : "s") + " and " + (pinnedBwic ? "" : "not ") + "the BWIC");
            }
            notes.Add("L " + FtToMm(geom.Length).ToString("0") + " / W " + FtToMm(geom.Width).ToString("0") + " / H "
                      + FtToMm(geom.Height).ToString("0") + " mm at " + FtToMm(geom.TargetZ).ToString("0") + " mm");
        }

        /// <summary>Places and sizes one BWIC. Returns the instance (null when skipped) and fills notes.</summary>
        public static FamilyInstance PlaceOne(Document doc, IList<Service> services, Wall wall, Transform transform, double clearanceFt,
                                              FamilySymbol symbol, BwicOptions options, Workset workset, Level preferredLevel,
                                              List<string> notes)
        {
            string error;
            WallGeom geom = ComputeBwic(doc, services, wall, transform, clearanceFt, preferredLevel, out error);
            if (geom == null)
            {
                notes.Add(error);
                return null;
            }
            FamilySymbol placeSymbol = SizedSymbol(doc, symbol, geom, notes);
            FamilyInstance instance = null;
            try
            {
                instance = doc.Create.NewFamilyInstance(geom.Point, placeSymbol, geom.Level, StructuralType.NonStructural);
            }
            catch (Exception) { }
            if (instance == null)
            {
                instance = doc.Create.NewFamilyInstance(geom.Point, placeSymbol, StructuralType.NonStructural);
                notes.Add("placed without a level, level set afterwards");
            }
            doc.Regenerate();
            ApplyToInstance(doc, instance, geom, placeSymbol, services, options, workset, notes);
            return instance;
        }

        /// <summary>Every length-like parameter name on a placed BWIC and its type.</summary>
        public static List<string> InstanceLengthNames(FamilyInstance instance)
        {
            var names = new HashSet<string>();
            foreach (Element holder in new Element[] { instance, instance == null ? null : instance.Symbol })
            {
                if (holder == null) continue;
                try
                {
                    foreach (Parameter param in holder.Parameters)
                        if (param.StorageType == StorageType.Double) names.Add(param.Definition.Name);
                }
                catch (Exception) { }
            }
            return names.OrderBy(n => n, StringComparer.Ordinal).ToList();
        }

        /// <summary>Families a resize will accept: only those whose Family settings have been saved.</summary>
        public static List<string> ResizeFamilyNames()
        {
            return LoadProfiles().Keys.Where(n => n.Length > 0).ToList();
        }

        /// <summary>(slot, settings) for resizing this BWIC: its own family's settings.</summary>
        public static Tuple<string, Dictionary<string, string>> ResizeSettings(FamilyInstance instance, string context)
        {
            string family = FamilyNameOf(instance.Symbol);
            var r = BwicFamilies.SettingsForFamily(family, context, ReadSettings(), LoadProfiles(), InstanceLengthNames(instance));
            DebugLog("resizing \"" + family + "\" as " + r.Item1 + " with its " + (r.Item3 ? "saved" : "guessed") + " family settings");
            return Tuple.Create(r.Item1, r.Item2);
        }

        /// <summary>What the wall sizing fields held, to put back after a one-off swap.</summary>
        public sealed class WallFamilyState
        {
            public string FamilyName, PLength, PWidth, PHeight, WallShape, PDiameter;
            public bool WallRadius;
            public RoundSpec RoundWall;
        }

        /// <summary>Point the wall sizing at a picked BWIC's own family, for one resize.</summary>
        public static WallFamilyState UseWallFamily(FamilyInstance instance, BwicOptions options)
        {
            var saved = new WallFamilyState
            {
                FamilyName = FamilyName, PLength = PLength, PWidth = PWidth, PHeight = PHeight, WallShape = WallShape,
                PDiameter = PDiameter, WallRadius = WallRadius, RoundWall = RoundWall,
            };
            var r = ResizeSettings(instance, "wall");
            string slot = r.Item1;
            var values = r.Item2;
            string fam = FamilyNameOf(instance.Symbol);
            FamilyName = string.IsNullOrEmpty(fam) ? FamilyName : fam;
            if (slot == "wall_circ")
            {
                PLength = BwicFamilies.Get(values, "wall_circ_length_param");
                PDiameter = BwicFamilies.Get(values, "wall_circ_diameter_param");
                if (PDiameter.Length == 0) PDiameter = "BGL_Diameter";
                WallRadius = BwicFamilies.Get(values, "wall_circ_radius") == "yes";
                WallShape = BwicFamilies.Circ;
                RoundSpec spec = options.RoundWall ?? options.RoundSpecValue ?? new RoundSpec();
                RoundWall = spec.Copy();
                RoundWall.GapMm = FamilyClearanceMm(FamilyName, spec.GapMm);
            }
            else
            {
                string p = BwicFamilies.Get(values, "wall_length_param");
                PLength = p.Length > 0 ? p : DefaultPLength;
                p = BwicFamilies.Get(values, "wall_width_param");
                PWidth = p.Length > 0 ? p : DefaultPWidth;
                p = BwicFamilies.Get(values, "wall_height_param");
                PHeight = p.Length > 0 ? p : DefaultPHeight;
                WallShape = BwicFamilies.Rect;
                PDiameter = "";
                RoundWall = null;
            }
            return saved;
        }

        public static void RestoreWallFamily(WallFamilyState s)
        {
            FamilyName = s.FamilyName; PLength = s.PLength; PWidth = s.PWidth; PHeight = s.PHeight; WallShape = s.WallShape;
            PDiameter = s.PDiameter; WallRadius = s.WallRadius; RoundWall = s.RoundWall;
        }

        /// <summary>Resize and reposition an existing BWIC. Returns the instance (null when skipped) and fills notes.</summary>
        public static FamilyInstance ResizeOne(Document doc, FamilyInstance instance, IList<Service> services, Wall wall, Transform transform,
                                               double clearanceFt, BwicOptions options, Workset workset, Level preferredLevel,
                                               List<string> notes)
        {
            string error;
            WallGeom geom = ComputeBwic(doc, services, wall, transform, clearanceFt, preferredLevel, out error);
            if (geom == null)
            {
                notes.Add(error);
                return null;
            }
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

            FamilySymbol baseSymbol = instance.Symbol;
            try
            {
                Family family = baseSymbol.Family;
                FamilySymbol defaultSymbol = null;
                foreach (ElementId sid in family.GetFamilySymbolIds())
                {
                    var candidate = doc.GetElement(sid) as FamilySymbol;
                    if (candidate != null)
                    {
                        defaultSymbol = candidate;
                        break;
                    }
                }
                string wallNote;
                FamilySymbol wanted = ChooseSymbol(doc, wall, defaultSymbol ?? baseSymbol, new Dictionary<string, FamilySymbol>(), out wallNote);
                notes.Add(wallNote);
                baseSymbol = wanted;
            }
            catch (Exception) { }

            FamilySymbol placeSymbol = SizedSymbol(doc, baseSymbol, geom, notes);
            if (placeSymbol.Id != instance.Symbol.Id)
            {
                try
                {
                    instance.Symbol = placeSymbol;
                    doc.Regenerate();
                }
                catch (Exception err)
                {
                    notes.Add("could not change the type: " + err.Message);
                }
            }
            ApplyToInstance(doc, instance, geom, placeSymbol, services, options, workset, notes);
            if (wasPinned && !options.Pin)
            {
                PinElement(instance);
                notes.Add("re-pinned");
            }
            return instance;
        }

        // ---------------------------------------------------------------- step prompts

        public static readonly Dictionary<string, string[]> Flows = new Dictionary<string, string[]>
        {
            { "wall_place", new[] { "services", "wall" } },
            { "wall_resize", new[] { "bwic", "services", "wall" } },
            { "slab_place", new[] { "services", "floor" } },
            { "slab_resize", new[] { "opening", "services", "floor" } },
        };

        private static readonly Dictionary<string, string[]> StepText = new Dictionary<string, string[]>
        {
            { "bwic", new[] { "Pick the BWIC to resize", "Click the existing BWIC you want re-fitted to new services." } },
            { "opening", new[] { "Pick the slab opening to resize", "Click the existing slab opening you want re-fitted." } },
            { "services", new[] { "Select the services",
                "Pick the pipes, ducts, cable trays or conduit passing through, then click Finish on the Options Bar, top left, or press Return." } },
            { "wall", new[] { "Click the wall", "Click the wall the services pass through. Walls in linked models work too." } },
            { "floor", new[] { "Click the floor", "Click the floor the services pass through. Floors in linked models work too." } },
        };

        private static readonly Dictionary<string, string> StepEnds = new Dictionary<string, string>
        {
            { "services", "finish" }, { "bwic", "click" }, { "opening", "click" }, { "wall", "click" }, { "floor", "click" },
        };

        /// <summary>A step for the prompt. Never raises: a prompt must not stop a run.</summary>
        public static Dictionary<string, object> StepDict(string flow, string key, bool linked = false, int chosen = 0)
        {
            int number = 1, total = 1;
            string title = key, detail = "", ends = "click";
            try
            {
                string[] steps = Flows[flow];
                title = StepText[key][0];
                detail = StepText[key][1];
                if (key == "services" && linked)
                {
                    detail = "Click each pipe, duct, cable tray or conduit - in this model or a linked one, both together - then Finish or Return. "
                             + "Click them one at a time: box selection is not available while linked models are included.";
                    if (chosen > 0)
                        detail = chosen + " already selected. Click any more - in this model or a linked one - then Finish or Return, or Finish now to use just those.";
                }
                number = Array.IndexOf(steps, key) + 1;
                total = steps.Length;
                ends = StepEnds[key];
            }
            catch (Exception err)
            {
                DebugLog("unknown step " + flow + " / " + key + ": " + err.Message);
            }
            return new Dictionary<string, object>
            {
                { "flow", flow }, { "key", key }, { "number", number }, { "total", total }, { "title", title }, { "detail", detail }, { "ends", ends },
            };
        }

        private static Action<string, Dictionary<string, object>> _guide;

        /// <summary>Who to tell where a run has got to. Null stops telling anyone.</summary>
        public static void SetGuide(Action<string, Dictionary<string, object>> callback) { _guide = callback; }

        /// <summary>Tell the window where the run has got to. Never stops the run.</summary>
        public static void Guide(string evt, Dictionary<string, object> details = null)
        {
            Action<string, Dictionary<string, object>> callback = _guide;
            if (callback == null) return;
            try { callback(evt, details ?? new Dictionary<string, object>()); }
            catch (Exception err) { DebugLog("step prompt failed: " + err.Message); }
        }

        public static Dictionary<string, object> Msg(string title, string detail)
        {
            return new Dictionary<string, object> { { "title", title }, { "detail", detail } };
        }

        // ---------------------------------------------------------------- the loop that runs while the window stays open

        /// <summary>Place or resize wall BWICs, rectangular or round. A round run swaps in the circular family for its own length only.</summary>
        public static void RunPlacementLoop(UIApplication uiapp, double clearanceMm, BwicOptions options, Action<string> report, string mode = "place")
        {
            RoundSpec roundWall = options.RoundWall;
            if (roundWall == null)
            {
                WallLoop(uiapp, clearanceMm, options, report, mode);
                return;
            }
            string sFamily = FamilyName, sLength = PLength, sShape = WallShape, sDia = PDiameter, sType = WallType;
            bool sRadius = WallRadius;
            RoundSpec sRound = RoundWall;
            try
            {
                if (!string.IsNullOrEmpty(roundWall.Family)) FamilyName = roundWall.Family;
                PLength = roundWall.Through ?? "";
                PDiameter = string.IsNullOrEmpty(roundWall.Diameter) ? "BGL_Diameter" : roundWall.Diameter;
                WallRadius = roundWall.Radius;
                WallType = roundWall.Type ?? "";
                WallShape = BwicFamilies.Circ;
                RoundWall = roundWall.Copy();
                RoundWall.GapMm = FamilyClearanceMm(FamilyName, roundWall.GapMm);
                WallLoop(uiapp, clearanceMm, options, report, mode);
            }
            finally
            {
                FamilyName = sFamily; PLength = sLength; WallShape = sShape; PDiameter = sDia; WallRadius = sRadius;
                WallType = sType; RoundWall = sRound;
            }
        }

        private static void EmptySelection(UIDocument uidoc)
        {
            try { uidoc.Selection.SetElementIds(new List<ElementId>()); }
            catch (Exception) { }
        }

        private static void WallLoop(UIApplication uiapp, double clearanceMm, BwicOptions options, Action<string> report, string mode)
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            if (uidoc == null)
            {
                report("No active Revit document.");
                return;
            }
            Document doc = uidoc.Document;
            double tabClearanceMm = clearanceMm;
            clearanceMm = FamilyClearanceMm(FamilyName, tabClearanceMm);
            double clearanceFt = MmToFt(clearanceMm);

            StartDebug(doc, "WALL RUN (" + mode + ")", null, options.ToDebug());
            DebugLog("family \"" + FamilyName + "\" clearance " + clearanceMm + " mm");
            DebugLog("size parameters: width " + BwicFamilies.ShowName(PWidth) + ", height " + BwicFamilies.ShowName(PHeight)
                     + ", through " + (BwicFamilies.ShowName(PLength).Length > 0 ? BwicFamilies.ShowName(PLength) : "-")
                     + (WallShape == BwicFamilies.Circ ? ", diameter " + PDiameter : ""));

            FamilySymbol defaultSymbol = FindFamilySymbol(doc);
            if (defaultSymbol == null)
            {
                DebugLog("family \"" + FamilyName + "\" is not loaded");
                report("The family \"" + FamilyName + "\" is not loaded in this project.");
                return;
            }
            var symbolCache = new Dictionary<string, FamilySymbol>();

            Workset workset = null;
            if (!string.IsNullOrEmpty(options.WorksetName))
            {
                workset = FindWorksetByName(doc, options.WorksetName);
                if (workset == null)
                    report("Workset \"" + options.WorksetName + "\" is not in this model - the BWIC will land on the active workset.");
            }

            var wallFilter = new WallPickFilter(doc);
            bool includeLinked = options.IncludeLinked;
            var serviceFilter = new ServicePickFilter(doc, includeLinked);
            bool resizing = mode == "resize";
            List<string> accepted = resizing ? ResizeFamilyNames() : null;
            var bwicFilter = new BwicPickFilter(accepted);
            int placed = 0;
            string flow = resizing ? "wall_resize" : "wall_place";

            while (true)
            {
                FamilyInstance target = null;

                if (resizing)
                {
                    var preselected = uidoc.Selection.GetElementIds().Select(eid => doc.GetElement(eid)).Where(el => IsBwic(el, accepted)).ToList();
                    if (preselected.Count == 1) target = preselected[0] as FamilyInstance;
                    else
                    {
                        try
                        {
                            Guide("step", StepDict(flow, "bwic"));
                            FocusRevit();
                            Reference r = uidoc.Selection.PickObject(ObjectType.Element, bwicFilter, "Pick the BWIC to resize  (Esc returns to the RevoBIM window)");
                            target = doc.GetElement(r.ElementId) as FamilyInstance;
                        }
                        catch (OperationCanceledException) { break; }
                        catch (Exception err)
                        {
                            report("BWIC pick failed: " + err.Message);
                            break;
                        }
                    }
                    EmptySelection(uidoc);
                }

                List<Service> services = PickServices(uidoc, doc, serviceFilter, includeLinked, flow, report, !resizing);
                if (services == null || services.Count == 0) break;
                int linkedCount = services.Count(sv => sv.Linked);

                Reference wallRef;
                try
                {
                    FocusRevit();
                    Guide("step", StepDict(flow, "wall"));
                    wallRef = uidoc.Selection.PickObject(ObjectType.LinkedElement, wallFilter, "Pick the wall to align the BWIC to  (Esc returns to the RevoBIM window)");
                }
                catch (OperationCanceledException)
                {
                    EmptySelection(uidoc);
                    break;
                }
                catch (Exception err)
                {
                    report("Wall pick failed: " + err.Message);
                    break;
                }

                double? pickZ = null;
                try
                {
                    if (wallRef.GlobalPoint != null)
                    {
                        pickZ = wallRef.GlobalPoint.Z;
                        DebugLog("click point Z " + FtToMm(pickZ.Value).ToString("0.0") + " mm (host coordinates)");
                    }
                }
                catch (Exception)
                {
                    DebugLog("the pick gave no global point, falling back to the bounding box");
                }
                if (pickZ != null)
                {
                    List<Level> levels = SortedLevels(doc);
                    CalibrateLevels(levels, pickZ);
                    levels = SortedLevels(doc);
                    if (levels.Count > 0)
                        DebugLog("levels now: lowest \"" + levels[0].Name + "\" at " + FtToMm(LevelZ(levels[0])).ToString("0") + " mm, highest \""
                                 + levels[levels.Count - 1].Name + "\" at " + FtToMm(LevelZ(levels[levels.Count - 1])).ToString("0") + " mm");
                }

                Element picked = doc.GetElement(wallRef.ElementId);
                Transform transform = Transform.Identity;
                Wall wall;
                var linkInst = picked as RevitLinkInstance;
                if (linkInst != null)
                {
                    Document linkDoc = linkInst.GetLinkDocument();
                    if (linkDoc == null)
                    {
                        report("That link is not loaded.");
                        continue;
                    }
                    wall = linkDoc.GetElement(wallRef.LinkedElementId) as Wall;
                    transform = linkInst.GetTotalTransform();
                }
                else wall = picked as Wall;
                if (wall == null)
                {
                    DebugLog("the pick was not a wall");
                    report("That is not a wall - try again.");
                    continue;
                }

                DebugLog("wall \"" + WallTypeName(wall) + "\" in " + (linkInst != null ? "link \"" + linkInst.Name + "\"" : "the host model"));
                DebugLog(services.Count + " service(s) selected");
                foreach (Service sv in services)
                {
                    try { DebugLog("   " + DescribeElement(sv.Element) + " id " + EidValue(sv.Element.Id) + (sv.Linked ? " (linked)" : "")); }
                    catch (Exception) { }
                }

                using (var trans = new Transaction(doc, resizing ? "Resize BWIC penetration" : "Place BWIC penetration"))
                {
                    trans.Start();
                    Quieten(trans);
                    try
                    {
                        Level planLevel = ViewLevel(uidoc.ActiveView);
                        options.LevelSource = planLevel != null ? "active plan view" : "nearest level below";
                        var notes = new List<string>();
                        FamilyInstance instance;
                        if (resizing)
                        {
                            WallFamilyState swapped = UseWallFamily(target, options);
                            try
                            {
                                instance = ResizeOne(doc, target, services, wall, transform, MmToFt(FamilyClearanceMm(FamilyName, tabClearanceMm)),
                                                     options, workset, planLevel, notes);
                            }
                            finally
                            {
                                RestoreWallFamily(swapped);
                            }
                        }
                        else
                        {
                            string wallNote;
                            FamilySymbol symbol = ChooseSymbol(doc, wall, defaultSymbol, symbolCache, out wallNote);
                            notes.Add(wallNote);
                            var more = new List<string>();
                            instance = PlaceOne(doc, services, wall, transform, clearanceFt, symbol, options, workset, planLevel, more);
                            notes.AddRange(more);
                        }
                        if (instance == null)
                        {
                            trans.RollBack();
                            DebugLog("SKIPPED: " + string.Join("; ", notes));
                            report("Skipped: " + string.Join("; ", notes));
                            string detail = string.Join("; ", notes.Where(n => !string.IsNullOrEmpty(n)));
                            Guide("problem", Msg("BWIC not placed", detail.Length > 160 ? detail.Substring(0, 160) : detail));
                        }
                        else
                        {
                            trans.Commit();
                            placed++;
                            DebugLog("placed id " + EidValue(instance.Id) + " : " + string.Join("; ", notes));
                            if (linkedCount > 0) notes.Insert(Math.Min(1, notes.Count), linkedCount + " linked service" + (linkedCount == 1 ? "" : "s") + " included");
                            report("BWIC " + placed + (resizing ? " resized" : " placed") + " - " + string.Join("; ", notes));
                            Guide("placed", Msg(resizing ? "BWIC resized" : "BWIC placed", placed + " this run. Carry on with the next one, or press Esc to stop."));
                        }
                    }
                    catch (Exception err)
                    {
                        if (trans.HasStarted()) trans.RollBack();
                        DebugLog("EXCEPTION during " + (resizing ? "resize" : "placement") + "\n" + err);
                        report((resizing ? "Resize" : "Placement") + " failed: " + err.Message);
                        string text = err.Message;
                        Guide("problem", Msg("BWIC not placed", text.Length > 160 ? text.Substring(0, 160) : text));
                    }
                }
                EmptySelection(uidoc);
            }
            Guide("done");
            report("Finished - " + placed + " BWIC " + (resizing ? "resized" : "placed") + " this run.");
        }
    }
}
