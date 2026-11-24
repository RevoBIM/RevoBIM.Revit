using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.FamilyFindReplace
{
    /// <summary>
    /// Family Find &amp; Replace: swap one loadable family for another across the model, keeping the insertion
    /// point, the instance parameters you choose, the circuits, the tags and the wires. In a drafting view,
    /// import symbols become detail items. Port of ffr_core.py (pyRevit tool 1.8.0). No WPF in these files.
    /// The class is split by subject: Core (this file), Electrical, Groups, Placement, Drafting, Run, Log.
    /// </summary>
    public static partial class FfrCore
    {
        public const string Version = "1.8.0";
        public const string ToolName = "Family Find & Replace";

        // ---- constants worth finding at the top of the file -------------------------------------------

        /// <summary>Parameters never offered for retention: the placement or the type drives them.</summary>
        private static readonly string[] ExcludedParamTokens =
        {
            "family and type", "family", "type id", "type name", "level", "host", "reference level", "schedule level",
            "elevation from level", "offset from host", "host id", "design option", "edited by", "phase created by",
            "image", "moves with nearby elements",
        };

        /// <summary>Nothing is ticked by default: retention is a deliberate choice per run.</summary>
        private static readonly string[] DefaultRetainTokens = new string[0];

        public const double VoltageTol = 1.0e-6;

        /// <summary>Elements per transaction. A refused batch loses little and progress moves visibly.</summary>
        public const int ChunkSize = 25;

        public const double PointTolFt = 1.0e-6;
        public const int MaxElements = 5000;

        /// <summary>How many elements are scanned for circuits while the window is being driven.</summary>
        public const int CircuitScanCap = 500;

        public const double MmPerFt = 304.8;

        public const string ScopeModel = "model";
        public const string ScopeView = "view";
        public const string ScopeSelection = "selection";

        // ---- build info and paths ---------------------------------------------------------------------

        /// <summary>The add-in build: version, build date and the DLL's path, for the debug header.</summary>
        public static string BuildInfo()
        {
            try
            {
                Assembly assembly = typeof(FfrCore).Assembly;
                string path = assembly.Location;
                string written = "";
                try
                {
                    written = File.GetLastWriteTime(path).ToString("yyyy-MM-dd HH:mm:ss");
                }
                catch (Exception)
                {
                }
                string date = "";
                string revit = "";
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

        public static string SettingsDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }

        public static string ErrorPath() { return Path.Combine(SettingsDir(), "family_find_replace_last_error.txt"); }

        /// <summary>The pyRevit tool's own file name, kept so both versions write to one log.</summary>
        public static string DebugPath() { return Path.Combine(SettingsDir(), "FamilyFindReplace_debug.txt"); }

        // ---- small helpers ----------------------------------------------------------------------------

        public static long Eid(ElementId id)
        {
            return id == null ? 0 : id.Value;
        }

        public static double MmToFt(double mm) { return mm / MmPerFt; }
        public static double FtToMm(double ft) { return ft * MmPerFt; }

        /// <summary>Internal electrical potential to volts, for display only.</summary>
        public static double Volts(double raw)
        {
            try
            {
                return UnitUtils.ConvertFromInternalUnits(raw, UnitTypeId.Volts);
            }
            catch (Exception)
            {
                return raw;
            }
        }

        public static string Name(Element element)
        {
            if (element == null) return "";
            try
            {
                return element.Name ?? "";
            }
            catch (Exception)
            {
                return "";
            }
        }

        /// <summary>A named property read by reflection, null when the release does not have it. For members that moved between releases.</summary>
        public static object Prop(object target, string name)
        {
            if (target == null) return null;
            try
            {
                PropertyInfo property = target.GetType().GetProperty(name);
                if (property == null) return null;
                return property.GetValue(target, null);
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>A no-argument method called by reflection; null when missing or failing.</summary>
        public static object Call(object target, string name)
        {
            if (target == null) return null;
            try
            {
                MethodInfo method = target.GetType().GetMethod(name, Type.EmptyTypes);
                if (method == null) return null;
                return method.Invoke(target, null);
            }
            catch (Exception)
            {
                return null;
            }
        }

        public static string MmText(XYZ point)
        {
            if (point == null) return "none";
            try
            {
                return "(" + FtToMm(point.X).ToString("0.0") + ", " + FtToMm(point.Y).ToString("0.0") + ")";
            }
            catch (Exception)
            {
                return "?";
            }
        }

        /// <summary>Angle about +Z that turns fromDir onto toDir.</summary>
        public static double SignedPlanAngle(XYZ fromDir, XYZ toDir)
        {
            double dot = fromDir.X * toDir.X + fromDir.Y * toDir.Y;
            double cross = fromDir.X * toDir.Y - fromDir.Y * toDir.X;
            return Math.Atan2(cross, dot);
        }

        // ---- warning suppression and pick filters -----------------------------------------------------

        /// <summary>Deletes warnings raised during a run so nothing stops on a dialog.</summary>
        public sealed class WarningSwallower : IFailuresPreprocessor
        {
            public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
            {
                try
                {
                    foreach (FailureMessageAccessor failure in accessor.GetFailureMessages()) accessor.DeleteWarning(failure);
                }
                catch (Exception)
                {
                }
                return FailureProcessingResult.Continue;
            }
        }

        /// <summary>Pick filter for the Find / Replace-with pick in a model view: family instances only.</summary>
        public sealed class FamilyInstancePickFilter : ISelectionFilter
        {
            public bool AllowElement(Element element)
            {
                try
                {
                    return element is FamilyInstance;
                }
                catch (Exception)
                {
                    return false;
                }
            }

            public bool AllowReference(Reference reference, XYZ position) { return false; }
        }

        // ---- the model index: category -> family -> type ----------------------------------------------

        public sealed class TypeRecord
        {
            public ElementId SymbolId;
            public string TypeName;
            public string FamilyName;
            public string CategoryName;
            public string Placement;
            public int Count;
            public bool IsImport;

            public TypeRecord(ElementId symbolId, string typeName, string familyName, string categoryName, string placement, int count)
            {
                SymbolId = symbolId;
                TypeName = typeName;
                FamilyName = familyName;
                CategoryName = categoryName;
                Placement = placement;
                Count = count;
            }

            /// <summary>An import has no family/type split: the block name is the whole of what it is called.</summary>
            public string Label
            {
                get { return IsImport ? FamilyName : FamilyName + " : " + TypeName; }
            }
        }

        public static string PlacementName(FamilySymbol symbol)
        {
            try
            {
                return symbol.Family.FamilyPlacementType.ToString();
            }
            catch (Exception)
            {
                return "Unknown";
            }
        }

        /// <summary>Every loadable family type in the project, keyed category &gt; family.</summary>
        public static Dictionary<string, Dictionary<string, List<TypeRecord>>> BuildIndex(Document doc)
        {
            var index = new Dictionary<string, Dictionary<string, List<TypeRecord>>>();
            Dictionary<long, int> counts = InstanceCounts(doc);
            foreach (Element element in new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)))
            {
                try
                {
                    var symbol = element as FamilySymbol;
                    if (symbol == null) continue;
                    Category category = symbol.Category;
                    if (category == null) continue;
                    if (category.CategoryType != CategoryType.Model) continue;
                    Family family = symbol.Family;
                    if (family == null) continue;
                    string catName = category.Name;
                    int count;
                    counts.TryGetValue(Eid(symbol.Id), out count);
                    AddRecord(index, new TypeRecord(symbol.Id, Name(symbol), Name(family), catName, PlacementName(symbol), count));
                }
                catch (Exception)
                {
                }
            }
            SortRecords(index);
            return index;
        }

        private static void AddRecord(Dictionary<string, Dictionary<string, List<TypeRecord>>> index, TypeRecord record)
        {
            Dictionary<string, List<TypeRecord>> families;
            if (!index.TryGetValue(record.CategoryName, out families))
            {
                families = new Dictionary<string, List<TypeRecord>>();
                index[record.CategoryName] = families;
            }
            List<TypeRecord> records;
            if (!families.TryGetValue(record.FamilyName, out records))
            {
                records = new List<TypeRecord>();
                families[record.FamilyName] = records;
            }
            records.Add(record);
        }

        private static void SortRecords(Dictionary<string, Dictionary<string, List<TypeRecord>>> index)
        {
            foreach (Dictionary<string, List<TypeRecord>> families in index.Values)
                foreach (List<TypeRecord> records in families.Values)
                    records.Sort((a, b) => string.Compare(a.TypeName, b.TypeName, StringComparison.OrdinalIgnoreCase));
        }

        /// <summary>One pass over the model rather than a collector per type.</summary>
        public static Dictionary<long, int> InstanceCounts(Document doc)
        {
            var counts = new Dictionary<long, int>();
            foreach (Element inst in new FilteredElementCollector(doc).OfClass(typeof(FamilyInstance)).WhereElementIsNotElementType())
            {
                try
                {
                    long key = Eid(inst.GetTypeId());
                    int n;
                    counts.TryGetValue(key, out n);
                    counts[key] = n + 1;
                }
                catch (Exception)
                {
                }
            }
            return counts;
        }

        // ---- finding the instances to replace ---------------------------------------------------------

        public static List<Element> CollectInstances(Document doc, UIDocument uidoc, ElementId symbolId, string scope)
        {
            var found = new List<Element>();
            if (symbolId == null) return found;
            try
            {
                if (scope == ScopeSelection)
                {
                    foreach (ElementId id in uidoc.Selection.GetElementIds())
                    {
                        var element = doc.GetElement(id) as FamilyInstance;
                        if (element != null && Eid(element.GetTypeId()) == Eid(symbolId)) found.Add(element);
                    }
                    return found;
                }
                FilteredElementCollector collector = scope == ScopeView && uidoc.ActiveView != null
                    ? new FilteredElementCollector(doc, uidoc.ActiveView.Id)
                    : new FilteredElementCollector(doc);
                collector = collector.WherePasses(new FamilyInstanceFilter(doc, symbolId));
                found.AddRange(collector);
                return found;
            }
            catch (Exception)
            {
                return new List<Element>();
            }
        }

        // ---- parameters -------------------------------------------------------------------------------

        public sealed class ParamInfo
        {
            public string Name;
            public StorageType Storage;
            public bool IsShared;
            public string Guid;
            public string Sample;
        }

        private static bool Excluded(string name)
        {
            string low = name.ToLowerInvariant();
            foreach (string token in ExcludedParamTokens)
                if (low == token || low.StartsWith(token, StringComparison.Ordinal)) return true;
            return false;
        }

        private static string SampleText(Parameter param)
        {
            try
            {
                if (param.StorageType == StorageType.String) return param.AsString() ?? "";
                string text = param.AsValueString();
                if (!string.IsNullOrEmpty(text)) return text;
                if (param.StorageType == StorageType.Integer) return param.AsInteger().ToString();
                if (param.StorageType == StorageType.Double) return Math.Round(param.AsDouble(), 4).ToString();
                if (param.StorageType == StorageType.ElementId)
                {
                    Element target = param.Element.Document.GetElement(param.AsElementId());
                    return target != null ? Name(target) : "";
                }
            }
            catch (Exception)
            {
            }
            return "";
        }

        /// <summary>Writable instance parameters on a placed element, keyed by name.</summary>
        public static Dictionary<string, ParamInfo> ReadParamInfos(Element instance)
        {
            var infos = new Dictionary<string, ParamInfo>();
            ParameterSet parameters;
            try
            {
                parameters = instance.Parameters;
            }
            catch (Exception)
            {
                return infos;
            }
            foreach (Parameter param in parameters)
            {
                try
                {
                    if (param.IsReadOnly) continue;
                    Definition definition = param.Definition;
                    if (definition == null) continue;
                    string name = definition.Name;
                    if (string.IsNullOrEmpty(name) || Excluded(name)) continue;
                    string guid = "";
                    try
                    {
                        if (param.IsShared) guid = param.GUID.ToString();
                    }
                    catch (Exception)
                    {
                        guid = "";
                    }
                    infos[name] = new ParamInfo
                    {
                        Name = name,
                        Storage = param.StorageType,
                        IsShared = guid.Length > 0,
                        Guid = guid,
                        Sample = SampleText(param),
                    };
                }
                catch (Exception)
                {
                }
            }
            return infos;
        }

        /// <summary>One line in the retain list.</summary>
        public sealed class ParamRow
        {
            public string Name;
            public string Storage;
            public bool IsShared;
            public string Sample;
            public bool OnTarget;
            public string Note;
            public bool Checked;
        }

        /// <summary>
        /// One row per writable instance parameter on the original. targetInfos is null until a replacement
        /// family has been read, and in that state every row is offered rather than greyed out.
        /// </summary>
        public static List<ParamRow> BuildParamRows(Dictionary<string, ParamInfo> sourceInfos, Dictionary<string, ParamInfo> targetInfos)
        {
            bool unknown = targetInfos == null;
            if (unknown) targetInfos = new Dictionary<string, ParamInfo>();
            var rows = new List<ParamRow>();
            foreach (string name in sourceInfos.Keys.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal))
            {
                ParamInfo src = sourceInfos[name];
                ParamInfo tgt;
                targetInfos.TryGetValue(name, out tgt);
                string note = "";
                bool onTarget = unknown || tgt != null;
                if (unknown) note = "replacement family not chosen yet";
                else if (!onTarget) note = "not on the replacement family";
                else if (tgt.Storage != src.Storage)
                {
                    onTarget = false;
                    note = "type mismatch - " + src.Storage + " vs " + tgt.Storage;
                }
                var row = new ParamRow
                {
                    Name = name,
                    Storage = src.Storage.ToString(),
                    IsShared = src.IsShared,
                    Sample = src.Sample,
                    OnTarget = onTarget,
                    Note = note,
                };
                if (onTarget && DefaultRetainTokens.Length > 0)
                {
                    string low = name.ToLowerInvariant();
                    row.Checked = DefaultRetainTokens.Any(t => low.StartsWith(t, StringComparison.Ordinal));
                }
                rows.Add(row);
            }
            return rows;
        }

        private static Parameter FindTargetParam(Element element, string name, string guid)
        {
            Parameter param = null;
            if (!string.IsNullOrEmpty(guid))
            {
                try
                {
                    param = element.get_Parameter(new Guid(guid));
                }
                catch (Exception)
                {
                    param = null;
                }
            }
            if (param == null)
            {
                try
                {
                    IList<Parameter> params2 = element.GetParameters(name);
                    if (params2 != null && params2.Count > 0)
                    {
                        foreach (Parameter candidate in params2)
                        {
                            if (!candidate.IsReadOnly)
                            {
                                param = candidate;
                                break;
                            }
                        }
                        if (param == null) param = params2[0];
                    }
                }
                catch (Exception)
                {
                    param = null;
                }
            }
            if (param == null)
            {
                try
                {
                    param = element.LookupParameter(name);
                }
                catch (Exception)
                {
                    param = null;
                }
            }
            return param;
        }

        /// <summary>Copy one instance parameter by name. Returns false and a message when it did not go.</summary>
        public static bool CopyParameter(Element source, Element target, string name, out string message)
        {
            message = "";
            Parameter src = null;
            try
            {
                IList<Parameter> list = source.GetParameters(name);
                if (list != null && list.Count > 0) src = list[0];
            }
            catch (Exception)
            {
                src = null;
            }
            if (src == null)
            {
                try
                {
                    src = source.LookupParameter(name);
                }
                catch (Exception)
                {
                    src = null;
                }
            }
            if (src == null)
            {
                message = name + ": not found on the original";
                return false;
            }
            string guid = "";
            try
            {
                if (src.IsShared) guid = src.GUID.ToString();
            }
            catch (Exception)
            {
                guid = "";
            }
            Parameter dst = FindTargetParam(target, name, guid);
            if (dst == null)
            {
                message = name + ": not on the replacement";
                return false;
            }
            if (dst.IsReadOnly)
            {
                message = name + ": read only on the replacement";
                return false;
            }
            if (dst.StorageType != src.StorageType)
            {
                message = name + ": storage type differs";
                return false;
            }
            try
            {
                switch (src.StorageType)
                {
                    case StorageType.String: dst.Set(src.AsString() ?? ""); break;
                    case StorageType.Integer: dst.Set(src.AsInteger()); break;
                    case StorageType.Double: dst.Set(src.AsDouble()); break;
                    case StorageType.ElementId: dst.Set(src.AsElementId()); break;
                    default:
                        message = name + ": unsupported storage type";
                        return false;
                }
                return true;
            }
            catch (Exception err)
            {
                message = name + ": " + err.Message;
                return false;
            }
        }

        /// <summary>
        /// Put the replacement on the workset the original sat on: a swap is per element, each replacement
        /// belongs where its own original was. A silent no-op on a model that is not workshared.
        /// </summary>
        private static bool CarryWorkset(Element source, Element target, out string message)
        {
            message = "";
            Parameter src, dst;
            try
            {
                src = source.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM);
                dst = target.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM);
            }
            catch (Exception)
            {
                return true;
            }
            if (src == null || dst == null) return true;
            if (dst.IsReadOnly)
            {
                message = "workset is read only on the replacement";
                return false;
            }
            try
            {
                int wanted = src.AsInteger();
                if (dst.AsInteger() != wanted) dst.Set(wanted);
                return true;
            }
            catch (Exception err)
            {
                message = "workset: " + err.Message;
                return false;
            }
        }

        /// <summary>
        /// Copy Phase Created and Phase Demolished. A new instance takes the phase of the view it was made in,
        /// and circuits are phase-aware, so a replacement on the wrong phase is refused by AddToCircuit.
        /// </summary>
        private static bool CarryPhasing(Element source, Element target, out string message)
        {
            var problems = new List<string>();
            foreach (BuiltInParameter bip in new[] { BuiltInParameter.PHASE_CREATED, BuiltInParameter.PHASE_DEMOLISHED })
            {
                Parameter src, dst;
                try
                {
                    src = source.get_Parameter(bip);
                    dst = target.get_Parameter(bip);
                }
                catch (Exception)
                {
                    continue;
                }
                if (src == null || dst == null || dst.IsReadOnly) continue;
                if (src.StorageType != StorageType.ElementId) continue;
                try
                {
                    ElementId wanted = src.AsElementId();
                    if (Eid(dst.AsElementId()) != Eid(wanted)) dst.Set(wanted);
                }
                catch (Exception err)
                {
                    problems.Add("phasing: " + err.Message);
                }
            }
            message = string.Join("; ", problems);
            return problems.Count == 0;
        }

        // ---- the report -------------------------------------------------------------------------------

        public sealed class Report
        {
            public int Replaced;
            public int CircuitsKept;
            public int CircuitsDropped;
            public int Pinned;
            public int TagsKept;
            public int WiresKept;
            public int GroupsDone;
            public int GroupsFailed;
            public int GroupInstances;
            public Dictionary<string, int> Routes = new Dictionary<string, int>();
            public Dictionary<string, int> LevelsSet = new Dictionary<string, int>();
            // drafting views
            public int Rotated;
            public int Mirrored;
            public int MirrorFailed;
            public int CentreShifted;
            public int CentreCorrected;
            public int CentreUnverified;
            public int RotationCorrected;
            public bool ByCentre;
            public Dictionary<string, int> CentreRoutes = new Dictionary<string, int>();
            public List<string> Debug = new List<string>();
            public Dictionary<long, string> Views = new Dictionary<long, string>();
            public List<ElementId> NewIds = new List<ElementId>();
            public List<KeyValuePair<string, string>> Lines = new List<KeyValuePair<string, string>>();   // kind: ok / warn / fail
            public string ReferenceKind = RefFacing;

            public void Add(string kind, string text)
            {
                Lines.Add(new KeyValuePair<string, string>(kind, text));
            }

            public static void Bump(Dictionary<string, int> map, string key)
            {
                int n;
                map.TryGetValue(key, out n);
                map[key] = n + 1;
            }
        }
    }
}
