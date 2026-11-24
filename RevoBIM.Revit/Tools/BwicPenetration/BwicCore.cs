using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;
using OperationCanceledException = Autodesk.Revit.Exceptions.OperationCanceledException;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.BwicPenetration
{
    /// <summary>A wall rule: which family type goes in which wall.</summary>
    public sealed class WallRule
    {
        public string Label;
        public string[] Keywords;
        public bool FireRating;
        public string Symbol;

        public WallRule Copy() { return (WallRule)MemberwiseClone(); }
    }

    /// <summary>A service (pipe, duct, tray...) plus the transform that puts it in host coordinates.</summary>
    public sealed class Service
    {
        public Element Element;
        public Transform Transform;
        public bool Linked;

        public Service(Element element, Transform transform = null, bool linked = false)
        {
            Element = element;
            Transform = transform ?? Transform.Identity;
            Linked = linked;
        }

        public Document Doc { get { return Element.Document; } }
    }

    /// <summary>The wall seen from above: point on the centre line, normal, half thickness (host coordinates).</summary>
    public sealed class WallPlane
    {
        public XYZ Origin, Normal;
        public double Half;

        public WallPlane(XYZ origin, XYZ normal, double half) { Origin = origin; Normal = normal; Half = half; }
    }

    /// <summary>
    /// BWIC Penetration, the model side (port of bwic_core.py, version 2.21.0): geometry, level and workset handling, the wall
    /// rules, the slab rules and the settings file. No WPF here. The pyRevit module kept its settings as module globals the
    /// rules read; they are static fields here, written by <see cref="ApplySettings"/>.
    /// </summary>
    public static partial class BwicCore
    {
        public const string ToolVersion = "2.21.0";
        public const string ToolName = "BWIC Penetration";

        public static string FamilyName = "BGL_BWIC_Penetration_Horizontal_Rectangular-Dynamic";
        public static string PLength = "BGL_Length";
        public static string PWidth = "BGL_Width";
        public static string PHeight = "BGL_Height";
        public const string DefaultPLength = "BGL_Length", DefaultPWidth = "BGL_Width", DefaultPHeight = "BGL_Height";
        public static string WallShape = BwicFamilies.Rect;
        public static string PDiameter = "";
        public static bool WallRadius = false;
        public static string WallType = "";
        public static RoundSpec RoundWall = null;

        public static double DefaultClearanceMm = 50.0;
        public const string ElevationMode = "extents_centre";
        public const string OriginVertical = "centre";
        public const bool DuplicateTypeIfTypeParams = true;
        public const string LevelParamName = "BHE_Level";
        public const string LevelParamKeyword = "Level";
        public static double RoundUpMm = 5.0;
        public const string WorksetKeyword = "BWIC";
        public const string QtyDelimiter = "_";
        public const bool SuppressMessages = true;

        public static List<WallRule> WallRules = new List<WallRule>
        {
            new WallRule { Label = "fire rated wall", Keywords = new[] { "FR", "FIRE" }, FireRating = true, Symbol = "BWIC - Fire Rated Wall" },
            new WallRule { Label = "blockwork wall", Keywords = new[] { "BLK" }, FireRating = false, Symbol = "BWIC - Blockwork" },
        };

        public static readonly string[][] LevelCodeRules = { new[] { "ROOF", "RF" }, new[] { "RF", "RF" } };

        public static readonly string[] ServiceCategoryNames =
        {
            "OST_PipeCurves", "OST_FlexPipeCurves", "OST_PipeFitting", "OST_PipeAccessory", "OST_PipeInsulations",
            "OST_DuctCurves", "OST_FlexDuctCurves", "OST_DuctFitting", "OST_DuctAccessory", "OST_DuctInsulations", "OST_DuctTerminal",
            "OST_Conduit", "OST_ConduitFitting", "OST_ConduitRun",
            "OST_CableTray", "OST_CableTrayFitting", "OST_CableTrayRun",
            "OST_Sprinklers", "OST_MechanicalEquipment", "OST_ElectricalEquipment",
            "OST_ElectricalFixtures", "OST_PlumbingFixtures", "OST_GenericModel",
        };

        // ---------------------------------------------------------------- files

        public static string DataDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }

        public static string SettingsPath() { return Path.Combine(DataDir(), "bwic_penetration_settings.txt"); }
        public static string ProfilesPath() { return Path.Combine(DataDir(), "bwic_penetration_families.json"); }
        public static string DebugPath() { return Path.Combine(DataDir(), "bwic_penetration_debug.txt"); }
        public static string ErrorPath() { return Path.Combine(DataDir(), "bwic_penetration_last_error.txt"); }

        public static string LegacyDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM PY");
        }

        /// <summary>The family profiles; until this add-in has saved its own, the pyRevit tool's file is read so Family settings carry over.</summary>
        public static Dictionary<string, object> LoadProfiles()
        {
            string path = ProfilesPath();
            if (!File.Exists(path))
            {
                string legacy = Path.Combine(LegacyDir(), "place_bwic_families.json");
                if (File.Exists(legacy)) path = legacy;
            }
            return BwicFamilies.Load(path);
        }

        /// <summary>Settings with the slot's chosen family profile written over them.</summary>
        public static Dictionary<string, string> FamilySettings(Dictionary<string, string> settings, string slot)
        {
            return BwicFamilies.Overlay(settings, slot, LoadProfiles());
        }

        /// <summary>Add-in version, build date, Revit version and DLL path: settles "is the newest build loaded?".</summary>
        public static string BuildInfo()
        {
            try
            {
                Assembly assembly = typeof(BwicCore).Assembly;
                string path = assembly.Location;
                string written = "";
                try { written = File.GetLastWriteTime(path).ToString("yyyy-MM-dd HH:mm:ss"); } catch (Exception) { }
                string date = "", revit = "";
                foreach (AssemblyMetadataAttribute meta in assembly.GetCustomAttributes(typeof(AssemblyMetadataAttribute), false))
                {
                    if (meta.Key == "BuildDate") date = meta.Value;
                    if (meta.Key == "RevitVersion") revit = meta.Value;
                }
                string info = assembly.GetName().Version == null ? "?" : assembly.GetName().Version.ToString(3);
                return "add-in " + info + " | built " + date + " | Revit " + revit + " build | " + path + " (written " + written + ")";
            }
            catch (Exception err)
            {
                return "build info unavailable: " + err.Message;
            }
        }

        // ---------------------------------------------------------------- debug log

        public static bool Debug;

        public static void SetDebug(bool on) { Debug = on; }

        private static void AppendDebug(string text)
        {
            Directory.CreateDirectory(DataDir());
            // a new file opens with the tool version and which build wrote it
            if (!File.Exists(DebugPath()))
                text = "bwic_penetration " + ToolVersion + "  " + BuildInfo() + "\n" + text;
            File.AppendAllText(DebugPath(), text, new UTF8Encoding(false));
        }

        /// <summary>Append a timestamped line to the debug log, if debugging is on.</summary>
        public static void DebugLog(string message)
        {
            if (!Debug) return;
            try { AppendDebug(DateTime.Now.ToString("HH:mm:ss") + " " + message + "\n"); }
            catch (Exception) { }
        }

        /// <summary>The first lines of the debug file: tool version, build info, then the run's heading, settings and options.</summary>
        public static void StartDebug(Document doc, string heading, Dictionary<string, string> settings = null,
                                      Dictionary<string, string> options = null)
        {
            if (!Debug) return;
            try
            {
                var sb = new StringBuilder();
                sb.Append("\n").Append(new string('=', 70)).Append("\n");
                sb.Append(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")).Append("  ").Append(heading).Append("\n");
                sb.Append("tool version ").Append(ToolVersion).Append("\n");
                sb.Append(BuildInfo()).Append("\n");
                try
                {
                    sb.Append("Revit ").Append(doc.Application.VersionNumber).Append(" build ").Append(doc.Application.VersionBuild).Append("\n");
                }
                catch (Exception) { }
                try { sb.Append("document ").Append(doc.Title).Append(" (workshared: ").Append(doc.IsWorkshared).Append(")\n"); }
                catch (Exception) { }
                if (settings != null)
                {
                    sb.Append("settings:\n");
                    foreach (string key in settings.Keys.OrderBy(k => k, StringComparer.Ordinal))
                        sb.Append("   ").Append(key).Append(" = ").Append(settings[key]).Append("\n");
                }
                if (options != null)
                {
                    sb.Append("options:\n");
                    foreach (string key in options.Keys.OrderBy(k => k, StringComparer.Ordinal))
                        sb.Append("   ").Append(key).Append(" = ").Append(options[key]).Append("\n");
                }
                sb.Append(new string('-', 70)).Append("\n");
                AppendDebug(sb.ToString());
            }
            catch (Exception) { }
        }

        public static void ClearDebug()
        {
            try { if (File.Exists(DebugPath())) File.Delete(DebugPath()); }
            catch (Exception) { }
        }

        // ---------------------------------------------------------------- settings

        /// <summary>Plain key=value file. A missing or damaged file falls back to the defaults key by key.</summary>
        public static Dictionary<string, string> ReadSettings()
        {
            var values = new Dictionary<string, string>(SlabDefaults);
            try
            {
                string path = SettingsPath();
                if (!File.Exists(path))
                {
                    // first run of this add-in: pick up the pyRevit tool's settings
                    path = Path.Combine(LegacyDir(), "place_bwic_settings.txt");
                    if (!File.Exists(path)) return values;
                }
                foreach (string raw in File.ReadAllLines(path, Encoding.UTF8))
                {
                    string line = raw.Trim();
                    if (line.Length == 0 || line.StartsWith("#") || line.IndexOf('=') < 0) continue;
                    int eq = line.IndexOf('=');
                    values[line.Substring(0, eq).Trim()] = line.Substring(eq + 1).Trim();
                }
            }
            catch (Exception)
            {
            }
            return values;
        }

        /// <summary>Push saved settings onto the static fields the rules read.</summary>
        public static void ApplySettings(Dictionary<string, string> values)
        {
            try { values = FamilySettings(values, "wall"); }
            catch (Exception) { }
            WallType = BwicFamilies.Get(values, "wall_type");
            if (BwicFamilies.Get(values, "wall_family").Length > 0) FamilyName = values["wall_family"];
            string p = BwicFamilies.Get(values, "wall_length_param");
            PLength = p.Length > 0 ? p : DefaultPLength;
            p = BwicFamilies.Get(values, "wall_width_param");
            PWidth = p.Length > 0 ? p : DefaultPWidth;
            p = BwicFamilies.Get(values, "wall_height_param");
            PHeight = p.Length > 0 ? p : DefaultPHeight;

            double number;
            string raw = BwicFamilies.Get(values, "clearance");
            if (raw.Length > 0 && TryNumber(raw, out number)) DefaultClearanceMm = number;
            raw = BwicFamilies.Get(values, "round_up");
            if (raw.Length > 0 && TryNumber(raw, out number) && number > 0) RoundUpMm = number;

            string fire = BwicFamilies.Get(values, "wall_type_firerated");
            string block = BwicFamilies.Get(values, "wall_type_blockwork");
            if (fire.Length > 0 || block.Length > 0)
            {
                var rules = new List<WallRule>();
                foreach (WallRule rule in WallRules)
                {
                    WallRule copy = rule.Copy();
                    if (copy.Label.StartsWith("fire") && fire.Length > 0) copy.Symbol = fire;
                    else if (copy.Label.StartsWith("block") && block.Length > 0) copy.Symbol = block;
                    rules.Add(copy);
                }
                WallRules = rules;
            }
        }

        public static bool TryNumber(string text, out double value)
        {
            return double.TryParse((text ?? "").Trim(), System.Globalization.NumberStyles.Float,
                                   System.Globalization.CultureInfo.InvariantCulture, out value);
        }

        public static void WriteSettings(Dictionary<string, string> values)
        {
            try
            {
                Directory.CreateDirectory(DataDir());
                var sb = new StringBuilder();
                foreach (string key in values.Keys.OrderBy(k => k, StringComparer.Ordinal))
                    sb.Append(key).Append("=").Append(values[key]).Append("\n");
                File.WriteAllText(SettingsPath(), sb.ToString(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }

        // ---------------------------------------------------------------- failures

        /// <summary>Clears Revit's own warning dialogs during placement.</summary>
        public sealed class WarningSwallower : IFailuresPreprocessor
        {
            public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
            {
                try
                {
                    foreach (FailureMessageAccessor failure in accessor.GetFailureMessages())
                        if (failure.GetSeverity() == FailureSeverity.Warning) accessor.DeleteWarning(failure);
                }
                catch (Exception) { }
                return FailureProcessingResult.Continue;
            }
        }

        public static void Quieten(Transaction transaction)
        {
            if (!SuppressMessages) return;
            try
            {
                FailureHandlingOptions options = transaction.GetFailureHandlingOptions();
                options.SetFailuresPreprocessor(new WarningSwallower());
                options.SetClearAfterRollback(true);
                transaction.SetFailureHandlingOptions(options);
            }
            catch (Exception) { }
        }

        // ---------------------------------------------------------------- units

        public static long EidValue(ElementId id) { return id == null ? 0 : id.Value; }

        public static double MmToFt(double mm) { return UnitUtils.ConvertToInternalUnits(mm, UnitTypeId.Millimeters); }

        public static double FtToMm(double ft) { return UnitUtils.ConvertFromInternalUnits(ft, UnitTypeId.Millimeters); }

        /// <summary>Round a length UP to the next whole step, working in millimetres.</summary>
        public static double RoundUpFt(double valueFt, double? stepMm = null)
        {
            double step = stepMm ?? RoundUpMm;
            if (step <= 0) return valueFt;
            double mm = FtToMm(valueFt);
            return MmToFt(Math.Ceiling(mm / step - 1e-9) * step);
        }

        // ---------------------------------------------------------------- selection filters

        /// <summary>Walls only, in a link or in the host model.</summary>
        public sealed class WallPickFilter : ISelectionFilter
        {
            private readonly Document _host;
            public WallPickFilter(Document host) { _host = host; }

            public bool AllowElement(Element element) { return element is Wall || element is RevitLinkInstance; }

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
                        return linkDoc.GetElement(reference.LinkedElementId) is Wall;
                    }
                    return element is Wall;
                }
                catch (Exception) { return false; }
            }
        }

        private static HashSet<long> _serviceCategoryIds;

        private static HashSet<long> ServiceCategoryIds()
        {
            if (_serviceCategoryIds == null)
            {
                var ids = new HashSet<long>();
                foreach (string name in ServiceCategoryNames)
                {
                    BuiltInCategory bic;
                    if (Enum.TryParse(name, out bic)) ids.Add((long)bic);
                }
                _serviceCategoryIds = ids;
            }
            return _serviceCategoryIds;
        }

        /// <summary>True for pipes, ducts, trays, conduit and their fittings.</summary>
        public static bool IsService(Element element)
        {
            try
            {
                Category category = element.Category;
                if (category == null) return false;
                if (!ServiceCategoryIds().Contains(EidValue(category.Id))) return false;
                return element.get_BoundingBox(null) != null;
            }
            catch (Exception) { return false; }
        }

        /// <summary>True for an instance of a BWIC family (the wall tool's own, or any of the given names).</summary>
        public static bool IsBwic(Element element, IList<string> names = null)
        {
            try
            {
                var fi = element as FamilyInstance;
                if (fi == null || fi.Symbol == null) return false;
                string family = fi.Symbol.Family.Name;
                if (names != null && names.Count > 0) return names.Any(n => !string.IsNullOrEmpty(n) && n == family);
                return family == FamilyName;
            }
            catch (Exception) { return false; }
        }

        public sealed class BwicPickFilter : ISelectionFilter
        {
            private readonly IList<string> _names;
            public BwicPickFilter(IList<string> names = null) { _names = names; }
            public bool AllowElement(Element element) { return IsBwic(element, _names); }
            public bool AllowReference(Reference reference, XYZ position) { return false; }
        }

        /// <summary>Services - runs, fittings and accessories. With includeLinked, services inside loaded links too (one selection).</summary>
        public sealed class ServicePickFilter : ISelectionFilter
        {
            private readonly Document _host;
            private readonly bool _includeLinked;

            public ServicePickFilter(Document host = null, bool includeLinked = false)
            {
                _host = host;
                _includeLinked = includeLinked;
            }

            public bool AllowElement(Element element)
            {
                if (IsService(element)) return true;
                return _includeLinked && element is RevitLinkInstance;
            }

            public bool AllowReference(Reference reference, XYZ position)
            {
                if (!_includeLinked || _host == null) return false;
                try
                {
                    Element element = _host.GetElement(reference.ElementId);
                    var link = element as RevitLinkInstance;
                    if (link == null) return IsService(element);
                    if (reference.LinkedElementId == ElementId.InvalidElementId) return false;
                    Document linkDoc = link.GetLinkDocument();
                    if (linkDoc == null) return false;
                    return IsService(linkDoc.GetElement(reference.LinkedElementId));
                }
                catch (Exception) { return false; }
            }
        }

        /// <summary>Turn a picked reference into a Service, host or linked.</summary>
        public static Service ResolvePicked(Document doc, Reference reference)
        {
            Element element = doc.GetElement(reference.ElementId);
            var link = element as RevitLinkInstance;
            if (link != null)
            {
                Document linkDoc = link.GetLinkDocument();
                if (linkDoc == null) return null;
                if (reference.LinkedElementId == ElementId.InvalidElementId) return null;
                Element linked;
                try { linked = linkDoc.GetElement(reference.LinkedElementId); }
                catch (Exception) { return null; }
                if (linked == null || !IsService(linked)) return null;
                return new Service(linked, link.GetTotalTransform(), true);
            }
            if (element == null || !IsService(element)) return null;
            return new Service(element);
        }

        public static string ServiceKey(Service service)
        {
            try { return service.Element.Document.PathName + "|" + EidValue(service.Element.Id); }
            catch (Exception) { return service.GetHashCode().ToString(); }
        }

        /// <summary>Services selected before the run started (this model's ids, and linked ones from GetReferences).</summary>
        public static List<Service> PreselectedServices(UIDocument uidoc, Document doc, bool includeLinked)
        {
            var services = new List<Service>();
            foreach (ElementId eid in uidoc.Selection.GetElementIds())
            {
                Element el = doc.GetElement(eid);
                try
                {
                    if (el != null && !(el is RevitLinkInstance) && el.get_BoundingBox(null) != null) services.Add(new Service(el));
                }
                catch (Exception) { }
            }
            if (includeLinked)
            {
                IList<Reference> refs = null;
                try { refs = uidoc.Selection.GetReferences(); }
                catch (Exception) { }
                if (refs != null)
                    foreach (Reference reference in refs)
                    {
                        try { if (reference.LinkedElementId == ElementId.InvalidElementId) continue; }
                        catch (Exception) { continue; }
                        Service service = ResolvePicked(doc, reference);
                        if (service != null) services.Add(service);
                    }
            }
            return services;
        }

        /// <summary>The services for one opening, or null when the user stopped.</summary>
        public static List<Service> PickServices(UIDocument uidoc, Document doc, ISelectionFilter serviceFilter, bool includeLinked,
                                                 string flow, Action<string> report, bool useSelection = true)
        {
            List<Service> services = useSelection ? PreselectedServices(uidoc, doc, includeLinked) : new List<Service>();
            if (services.Count > 0 && !includeLinked) return services;
            ObjectType mode = includeLinked ? ObjectType.PointOnElement : ObjectType.Element;
            IList<Reference> refs;
            try
            {
                Guide("step", StepDict(flow, "services", includeLinked, services.Count));
                FocusRevit();
                refs = uidoc.Selection.PickObjects(mode, serviceFilter,
                    (includeLinked ? "Click each service, in this model or a linked one" : "Select the services")
                    + ", then press Return or Finish  (Esc returns to the RevoBIM window)");
            }
            catch (OperationCanceledException)
            {
                return null;
            }
            catch (Exception err)
            {
                report("Selection failed: " + err.Message);
                return null;
            }
            var seen = new HashSet<string>(services.Select(ServiceKey));
            int dropped = 0;
            foreach (Reference reference in refs)
            {
                Service service = ResolvePicked(doc, reference);
                if (service == null)
                {
                    dropped++;
                    continue;
                }
                string key = ServiceKey(service);
                if (seen.Add(key)) services.Add(service);
            }
            if (dropped > 0)
                report(dropped + " of the clicks were not on a service, or could not be read inside the link, and were left out.");
            DebugLog("services: " + services.Count + " (" + services.Count(sv => sv.Linked) + " linked)"
                     + (dropped > 0 ? ", " + dropped + " picked that are not services" : ""));
            return services;
        }

        // ---------------------------------------------------------------- geometry helpers

        /// <summary>First non-zero value from a list of parameter names or built-ins.</summary>
        public static double ParamDouble(Element element, string[] names, string[] bips)
        {
            foreach (string bipName in bips)
            {
                BuiltInParameter bip;
                if (!Enum.TryParse(bipName, out bip)) continue;
                try
                {
                    Parameter param = element.get_Parameter(bip);
                    if (param != null && param.StorageType == StorageType.Double)
                    {
                        double value = param.AsDouble();
                        if (value > 1e-9) return value;
                    }
                }
                catch (Exception) { }
            }
            foreach (string name in names)
            {
                try
                {
                    Parameter param = element.LookupParameter(name);
                    if (param != null && param.StorageType == StorageType.Double)
                    {
                        double value = param.AsDouble();
                        if (value > 1e-9) return value;
                    }
                }
                catch (Exception) { }
            }
            return 0.0;
        }

        /// <summary>Outer half width and half height of a straight run (insulation included), or null.</summary>
        public static double[] CrossSection(Element element)
        {
            double diameter = ParamDouble(element, new[] { "Diameter", "Overall Size", "Outside Diameter" },
                new[] { "RBS_PIPE_OUTER_DIAMETER", "RBS_CURVE_DIAMETER_PARAM", "RBS_PIPE_DIAMETER_PARAM",
                        "RBS_CONDUIT_OUTER_DIAM_PARAM", "RBS_CONDUIT_DIAMETER_PARAM" });
            double width = ParamDouble(element, new[] { "Width" }, new[] { "RBS_CURVE_WIDTH_PARAM", "RBS_CABLETRAY_WIDTH_PARAM" });
            double height = ParamDouble(element, new[] { "Height" }, new[] { "RBS_CURVE_HEIGHT_PARAM", "RBS_CABLETRAY_HEIGHT_PARAM" });
            double halfW, halfH;
            if (width > 1e-9 && height > 1e-9)
            {
                halfW = width / 2.0; halfH = height / 2.0;
            }
            else if (diameter > 1e-9)
            {
                halfW = halfH = diameter / 2.0;
            }
            else return null;
            double insulation = ParamDouble(element, new[] { "Insulation Thickness" },
                new[] { "RBS_REFERENCE_INSULATION_THICKNESS", "RBS_INSULATION_THICKNESS_FOR_DUCT", "RBS_PIPE_INSULATION_THICKNESS" });
            if (insulation > 1e-9)
            {
                halfW += insulation; halfH += insulation;
            }
            return new[] { halfW, halfH };
        }

        /// <summary>Local axes for a run: along, horizontal perpendicular, and 'up'.</summary>
        public static void RunFrame(XYZ direction, out XYZ along, out XYZ side, out XYZ up)
        {
            along = direction.Normalize();
            var horizontal = new XYZ(along.X, along.Y, 0);
            if (horizontal.GetLength() < 1e-6)
            {
                side = XYZ.BasisX;
                up = XYZ.BasisY;
            }
            else
            {
                side = along.CrossProduct(XYZ.BasisZ);
                if (side.GetLength() < 1e-9) side = XYZ.BasisX;
                side = side.Normalize();
                up = side.CrossProduct(along).Normalize();
            }
        }

        /// <summary>Points describing the outer envelope of a service, in host coordinates.</summary>
        public static List<XYZ> ServicePoints(Service service, WallPlane wallPlane = null)
        {
            Element element = service.Element;
            Transform transform = service.Transform;
            try
            {
                var location = element.Location as LocationCurve;
                double[] section = CrossSection(element);
                if (location != null && section != null)
                {
                    double halfW = section[0], halfH = section[1];
                    Curve curve = location.Curve;
                    XYZ start = curve.GetEndPoint(0), end = curve.GetEndPoint(1);
                    XYZ direction = end - start;
                    if (direction.GetLength() > 1e-9)
                    {
                        XYZ along, side, up;
                        RunFrame(direction, out along, out side, out up);
                        XYZ[] bases = { start, end };
                        if (wallPlane != null)
                        {
                            double[] span = BwicFamilies.WallSpan(
                                (transform.OfPoint(start) - wallPlane.Origin).DotProduct(wallPlane.Normal),
                                (transform.OfPoint(end) - wallPlane.Origin).DotProduct(wallPlane.Normal), wallPlane.Half);
                            if (span != null) bases = new[] { start + direction * span[0], start + direction * span[1] };
                        }
                        var points = new List<XYZ>();
                        foreach (XYZ b in bases)
                            foreach (double sw in new[] { -halfW, halfW })
                                foreach (double sh in new[] { -halfH, halfH })
                                    points.Add(b + side * sw + up * sh);
                        return points.Select(p => transform.OfPoint(p)).ToList();
                    }
                }
            }
            catch (Exception) { }
            List<XYZ> solid = SolidPoints(element, transform);
            if (solid.Count > 0) return solid;
            return BboxCorners(element, transform);
        }

        /// <summary>Every solid in a geometry element, stepping into instances.</summary>
        public static IEnumerable<Solid> WalkGeometry(GeometryElement geometry, bool intoInstances = true)
        {
            var found = new List<Solid>();
            if (geometry == null) return found;
            foreach (GeometryObject item in geometry)
            {
                try
                {
                    var solid = item as Solid;
                    var inst = item as GeometryInstance;
                    var sub = item as GeometryElement;
                    if (solid != null) { if (solid.Volume > 1e-9) found.Add(solid); }
                    else if (inst != null) { if (intoInstances) found.AddRange(WalkGeometry(inst.GetInstanceGeometry(), false)); }
                    else if (sub != null) found.AddRange(WalkGeometry(sub, intoInstances));
                }
                catch (Exception) { }
            }
            return found;
        }

        /// <summary>Corner points of an element's real solids, in host coordinates (for fittings and accessories).</summary>
        public static List<XYZ> SolidPoints(Element element, Transform transform = null)
        {
            var points = new List<XYZ>();
            try
            {
                var options = new Options { DetailLevel = ViewDetailLevel.Fine, IncludeNonVisibleObjects = false };
                GeometryElement geometry = element.get_Geometry(options);
                foreach (Solid solid in WalkGeometry(geometry))
                    foreach (Edge edge in solid.Edges)
                    {
                        try { points.AddRange(edge.Tessellate()); }
                        catch (Exception) { }
                    }
            }
            catch (Exception)
            {
                return new List<XYZ>();
            }
            if (points.Count == 0) return points;
            if (transform != null) points = points.Select(p => transform.OfPoint(p)).ToList();
            return points;
        }

        public static List<XYZ> BboxCorners(Element element, Transform transform = null)
        {
            BoundingBoxXYZ bb = element.get_BoundingBox(null);
            var points = new List<XYZ>();
            if (bb == null) return points;
            Transform local = bb.Transform;
            XYZ mn = bb.Min, mx = bb.Max;
            foreach (double x in new[] { mn.X, mx.X })
                foreach (double y in new[] { mn.Y, mx.Y })
                    foreach (double z in new[] { mn.Z, mx.Z })
                        points.Add(local.OfPoint(new XYZ(x, y, z)));
            if (transform != null) points = points.Select(p => transform.OfPoint(p)).ToList();
            return points;
        }

        public static double ElementCentreZ(Service service)
        {
            Element element = service.Element;
            Transform transform = service.Transform;
            try
            {
                var lc = element.Location as LocationCurve;
                if (lc != null)
                {
                    Curve curve = lc.Curve;
                    XYZ mid = (curve.GetEndPoint(0) + curve.GetEndPoint(1)) / 2.0;
                    return transform.OfPoint(mid).Z;
                }
                var lp = element.Location as LocationPoint;
                if (lp != null) return transform.OfPoint(lp.Point).Z;
            }
            catch (Exception) { }
            List<XYZ> points = SolidPoints(element, transform);
            if (points.Count == 0) points = BboxCorners(element, transform);
            if (points.Count == 0) return 0.0;
            return (points.Min(p => p.Z) + points.Max(p => p.Z)) / 2.0;
        }

        public static double? GetWallThickness(Wall wall)
        {
            try
            {
                double width = wall.Width;
                if (width > 1e-9) return width;
            }
            catch (Exception) { }
            try
            {
                Element wtype = wall.Document.GetElement(wall.GetTypeId());
                Parameter param = wtype.get_Parameter(BuiltInParameter.WALL_ATTR_WIDTH_PARAM);
                if (param != null && param.AsDouble() > 1e-9) return param.AsDouble();
            }
            catch (Exception) { }
            return null;
        }

        /// <summary>(point on the wall centre line, along-wall vector, wall normal).</summary>
        public static void WallFrameAt(Curve wallCurve, XYZ point, out XYZ basePoint, out XYZ direction, out XYZ normal)
        {
            IntersectionResult result = wallCurve.Project(point);
            XYZ dir;
            if (result == null)
            {
                basePoint = wallCurve.GetEndPoint(0);
                dir = wallCurve.GetEndPoint(1) - basePoint;
            }
            else
            {
                basePoint = result.XYZPoint;
                dir = wallCurve.ComputeDerivatives(result.Parameter, false).BasisX;
            }
            direction = new XYZ(dir.X, dir.Y, 0).Normalize();
            normal = direction.CrossProduct(XYZ.BasisZ).Normalize();
        }

        // ---------------------------------------------------------------- family helpers

        public static FamilySymbol FindFamilySymbol(Document doc)
        {
            var symbols = new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>()
                .Where(s => s.Family != null && s.Family.Name == FamilyName).ToList();
            if (symbols.Count == 0) return null;
            foreach (FamilySymbol sym in symbols)
                if (WallType.Length > 0 && sym.Name == WallType) return sym;
            return symbols[0];
        }

        /// <summary>Write a size. A split pair takes half on each side; every part is checked before any is written.</summary>
        public static bool SetLengthParam(Element holder, string name, double valueFt, out string error)
        {
            error = null;
            var parts = BwicFamilies.SplitParts(name);
            var prms = new List<KeyValuePair<Parameter, double>>();
            foreach (var part in parts)
            {
                Parameter param = holder.LookupParameter(part.Key);
                if (param == null) { error = part.Key + " not found"; return false; }
                if (param.IsReadOnly) { error = part.Key + " is read only"; return false; }
                if (param.StorageType != StorageType.Double) { error = part.Key + " is not a length parameter"; return false; }
                prms.Add(new KeyValuePair<Parameter, double>(param, part.Value));
            }
            foreach (var pr in prms) pr.Key.Set(valueFt * pr.Value);
            if (prms.Count > 1)
                DebugLog("split " + BwicFamilies.ShowName(name) + " -> " + FtToMm(valueFt / 2.0).ToString("0.0") + " mm each side ("
                         + FtToMm(valueFt).ToString("0.0") + " overall)");
            return true;
        }

        public static bool HasLengthParam(Element holder, string name)
        {
            if (string.IsNullOrEmpty(name) || holder == null) return false;
            try { return BwicFamilies.SplitParts(name).All(p => holder.LookupParameter(p.Key) != null); }
            catch (Exception) { return false; }
        }

        /// <summary>(parameter, value) pairs a wall BWIC is sized with, by its shape.</summary>
        public static List<KeyValuePair<string, double>> WallSizeWrites(double length, double width, double height)
        {
            var writes = new List<KeyValuePair<string, double>>();
            if (WallShape == BwicFamilies.Circ && PDiameter.Length > 0)
            {
                if (PLength.Length > 0) writes.Add(new KeyValuePair<string, double>(PLength, length));
                writes.Add(new KeyValuePair<string, double>(PDiameter, BwicFamilies.RoundValue(Math.Max(width, height), WallRadius)));
                return writes;
            }
            writes.Add(new KeyValuePair<string, double>(PLength, length));
            writes.Add(new KeyValuePair<string, double>(PWidth, width));
            writes.Add(new KeyValuePair<string, double>(PHeight, height));
            return writes;
        }

        public static string UniqueTypeName(FamilySymbol baseSymbol, double lengthFt, double widthFt, double heightFt)
        {
            return baseSymbol.Name + "_L" + Math.Round(FtToMm(lengthFt)).ToString("0") + "_W" + Math.Round(FtToMm(widthFt)).ToString("0")
                   + "_H" + Math.Round(FtToMm(heightFt)).ToString("0");
        }

        public static FamilySymbol FindSymbolByName(Document doc, Family family, string typeName)
        {
            foreach (ElementId sid in family.GetFamilySymbolIds())
            {
                var sym = doc.GetElement(sid) as FamilySymbol;
                if (sym != null && sym.Name == typeName) return sym;
            }
            return null;
        }

        // ---------------------------------------------------------------- wall classification

        public static string WallTypeName(Wall wall)
        {
            try
            {
                Element wtype = wall.Document.GetElement(wall.GetTypeId());
                if (wtype != null) return wtype.Name ?? "";
            }
            catch (Exception) { }
            try
            {
                Parameter param = wall.get_Parameter(BuiltInParameter.ELEM_TYPE_PARAM);
                if (param != null) return param.AsValueString() ?? "";
            }
            catch (Exception) { }
            return "";
        }

        public static bool WallIsFireRated(Wall wall)
        {
            try
            {
                Element wtype = wall.Document.GetElement(wall.GetTypeId());
                Parameter param = wtype.get_Parameter(BuiltInParameter.FIRE_RATING);
                if (param == null) return false;
                string value = (param.AsString() ?? "").Trim();
                if (value.Length == 0) return false;
                string up = value.ToUpperInvariant();
                return up != "0" && up != "NONE" && up != "N/A" && up != "-";
            }
            catch (Exception) { return false; }
        }

        /// <summary>Whole word match, so BLK does not fire on BLOCKING and FR not on FRAME.</summary>
        public static bool HasKeyword(string text, string keyword)
        {
            string pattern = "(?<![A-Z0-9])" + Regex.Escape(keyword.ToUpperInvariant()) + "(?![A-Z0-9])";
            return Regex.IsMatch((text ?? "").ToUpperInvariant(), pattern);
        }

        public static WallRule ClassifyWall(Wall wall)
        {
            string typeName = WallTypeName(wall);
            foreach (WallRule rule in WallRules)
            {
                if (rule.Keywords.Any(kw => HasKeyword(typeName, kw))) return rule;
                if (rule.FireRating && WallIsFireRated(wall)) return rule;
            }
            return null;
        }

        /// <summary>The family type that suits this wall and a description; falls back to the default type, saying so.</summary>
        public static FamilySymbol ChooseSymbol(Document doc, Wall wall, FamilySymbol defaultSymbol,
                                                Dictionary<string, FamilySymbol> cache, out string description)
        {
            WallRule rule = ClassifyWall(wall);
            string typeName = WallTypeName(wall);
            if (rule == null)
            {
                description = "wall \"" + typeName + "\"";
                return defaultSymbol;
            }
            string wanted = rule.Symbol;
            if (!cache.ContainsKey(wanted)) cache[wanted] = FindSymbolByName(doc, defaultSymbol.Family, wanted);
            FamilySymbol symbol = cache[wanted];
            if (symbol == null)
            {
                description = rule.Label + " \"" + typeName + "\" - type \"" + wanted + "\" not loaded, used the default type";
                return defaultSymbol;
            }
            description = rule.Label + " \"" + typeName + "\" - type \"" + wanted + "\"";
            return symbol;
        }

        // ---------------------------------------------------------------- levels

        public static List<Level> SortedLevels(Document doc)
        {
            return new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>().OrderBy(l => LevelZ(l)).ToList();
        }

        /// <summary>The level a plan view is associated with, or null for anything else.</summary>
        public static Level ViewLevel(View view)
        {
            if (view == null) return null;
            try
            {
                var plan = view as ViewPlan;
                return plan == null ? null : plan.GenLevel;
            }
            catch (Exception) { return null; }
        }

        /// <summary>Nearest level at or below the elevation; where nothing sits below, the NEAREST level.</summary>
        public static Level LevelBelow(IList<Level> levels, double elevation)
        {
            if (levels == null || levels.Count == 0) return null;
            Level below = null;
            foreach (Level lvl in levels) if (LevelZ(lvl) <= elevation + 1e-6) below = lvl;
            if (below != null) return below;
            return levels.OrderBy(l => Math.Abs(LevelZ(l) - elevation)).First();
        }

        // ---------------------------------------------------------------- shapes

        private static readonly string[] RoundCategoryNames =
        {
            "OST_PipeCurves", "OST_FlexPipeCurves", "OST_PipeFitting", "OST_PipeAccessory", "OST_PipeInsulations",
            "OST_Conduit", "OST_ConduitFitting", "OST_ConduitRun", "OST_Sprinklers",
        };

        private static readonly string[] RectCategoryNames =
        {
            "OST_DuctCurves", "OST_FlexDuctCurves", "OST_DuctFitting", "OST_DuctAccessory", "OST_DuctInsulations", "OST_DuctTerminal",
            "OST_CableTray", "OST_CableTrayFitting", "OST_CableTrayRun",
        };

        private static Dictionary<long, string> _shapeIds;

        private static Dictionary<long, string> ShapeCategoryIds()
        {
            if (_shapeIds == null)
            {
                var table = new Dictionary<long, string>();
                foreach (string name in RoundCategoryNames)
                {
                    BuiltInCategory bic;
                    if (Enum.TryParse(name, out bic)) table[(long)bic] = "round";
                }
                foreach (string name in RectCategoryNames)
                {
                    BuiltInCategory bic;
                    if (Enum.TryParse(name, out bic)) table[(long)bic] = "rect";
                }
                _shapeIds = table;
            }
            return _shapeIds;
        }

        /// <summary>"round" for a pipe, "rect" for a tray or duct, "round" by default.</summary>
        public static string ServiceShape(Service service)
        {
            try
            {
                Category category = service.Element.Category;
                string shape;
                if (category != null && ShapeCategoryIds().TryGetValue(EidValue(category.Id), out shape)) return shape;
            }
            catch (Exception) { }
            return "round";
        }

        /// <summary>"circular", "rectangular", or null when the name does not say.</summary>
        public static string FamilyShapeByName(string familyName)
        {
            string name = (familyName ?? "").ToLowerInvariant();
            if (name.Contains("circular")) return "circular";
            if (name.Contains("rectangular") || name.Contains("rectangle")) return "rectangular";
            return null;
        }

        public static bool WantsCircular(string familyName, bool forced = false)
        {
            string shape = FamilyShapeByName(familyName);
            if (shape != null) return shape == "circular";
            return forced;
        }

        private static readonly object[][] OdSources =
        {
            new object[] { "RBS_PIPE_OUTER_DIAMETER", "Outside Diameter", true },
            new object[] { null, "Outside Diameter", true },
            new object[] { null, "Outer Diameter", true },
            new object[] { "RBS_CONDUIT_OUTER_DIAM_PARAM", "Outside Diameter", true },
            new object[] { "RBS_CURVE_DIAMETER_PARAM", "Diameter", false },
            new object[] { "RBS_PIPE_DIAMETER_PARAM", "Diameter", false },
            new object[] { "RBS_CONDUIT_DIAMETER_PARAM", "Diameter", false },
            new object[] { null, "Overall Size", false },
        };

        /// <summary>(diameter or 0, where it came from, is it a true outside diameter).</summary>
        public static double OutsideDiameter(Element element, out string source, out bool isOuter)
        {
            foreach (object[] entry in OdSources)
            {
                string bipName = (string)entry[0], paramName = (string)entry[1];
                bool outer = (bool)entry[2];
                double value = 0.0;
                try
                {
                    Parameter param = null;
                    if (bipName != null)
                    {
                        BuiltInParameter bip;
                        if (Enum.TryParse(bipName, out bip)) param = element.get_Parameter(bip);
                    }
                    else param = element.LookupParameter(paramName);
                    if (param != null && param.StorageType == StorageType.Double) value = param.AsDouble();
                }
                catch (Exception) { value = 0.0; }
                if (value > 1e-9)
                {
                    source = bipName ?? paramName;
                    isOuter = outer;
                    return value;
                }
            }
            source = "no diameter parameter";
            isOuter = false;
            return 0.0;
        }
    }
}
