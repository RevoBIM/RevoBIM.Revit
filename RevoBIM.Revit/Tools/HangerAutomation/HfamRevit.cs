using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.DB.Mechanical;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.HangerAutomation
{
    // =====================================================================================================
    // Hanger Automation - Family Hangers tab: everything that touches Revit. Port of hfam_revit.py.
    //
    // Works on Revit ducts, pipes, cable trays and fabrication ducts / pipes alike.  Jobs (run from the
    // window through the shared ExternalEvent):
    //   JobPlace    pick ducts one after another and place the chosen hanger family
    //   JobRealign  pick a duct, then hangers, and re-align them to it
    //   JobAuto     select a duct run and place hangers along it by the placement rules
    // Quiet jobs (no results box): ListJob, PreviewJobFor, ParamsJobFor.
    //
    // The hanger is placed on the duct's level, centred on the duct, its reference level at the duct
    // invert, its two stretch parameters set to half the duct width (plus clearance), turned square to
    // the duct, and optionally its drop rod run up to the soffit.
    //
    // Files: HfamRevit.cs (basics, picking, debug text, family list), HfamRevit.Section.cs (sections,
    // levels, parameters, SoffitFinder), HfamRevit.Place.cs (placing / re-aligning one hanger),
    // HfamRevit.Graph.cs (connector graph), HfamRevit.Dims.cs (dimensions, Dimension placer job),
    // HfamRevit.Locker.cs (alignment locks), HfamRevit.Jobs.cs (bundles, Place / Re-align / Auto jobs,
    // quiet jobs), HfamRevit.Base.cs (temporary 3D view, Target, BaseSurface, Drop rod extender job).
    //
    // Python tuples / dicts became small nested classes (documented where they are built); the
    // module-level settings the window put in the dict ('_fam', '_fams') travel with
    // HfamRevit.SetFamilies (see there); '_mode' stays an entry of the settings dictionary.
    // =====================================================================================================
    public static partial class HfamRevit
    {
        public const double MM = FhaCore.MM;
        public const double EndMargin = 50.0 / MM;   // END_MARGIN
        public const double Tol = 1.0 / MM;          // TOL

        // ---------------------------------------------------------------- private plumbing
        private static long Eid(ElementId id) { return FhaRevit.EidValue(id); }
        private static string ElName(Element el) { return FhaRevit.ElName(el); }
        private static V3 Pt(XYZ v) { return FhaRevit.Pt(v); }
        private static XYZ ToXyz(V3 v) { return FhaRevit.ToXyz(v); }

        /// <summary>Python "{0:.Nf}" for log lines.</summary>
        private static string Fm(double v, int decimals)
        {
            return v.ToString("F" + decimals.ToString(CultureInfo.InvariantCulture), CultureInfo.InvariantCulture);
        }

        private static string Inv(long v) { return v.ToString(CultureInfo.InvariantCulture); }
        private static string Inv(int v) { return v.ToString(CultureInfo.InvariantCulture); }

        /// <summary>settings.get(key, dflt): the dictionary's own value, no FhaCore defaults.</summary>
        private static string SGet(IDictionary<string, string> d, string key, string dflt)
        {
            string v;
            if (d != null && d.TryGetValue(key, out v) && v != null) return v;
            return dflt;
        }

        /// <summary>Python repr of a unicode string in a list (IronPython 2: u'...').</summary>
        private static string ReprStr(string s) { return s == null ? "None" : "u'" + s + "'"; }
        private static string ReprList(IEnumerable<string> items) { return "[" + string.Join(", ", items.Select(ReprStr)) + "]"; }
        private static string ReprIds(IEnumerable<long> ids) { return "[" + string.Join(", ", ids.Select(i => Inv(i))) + "]"; }

        /// <summary>Python truthiness of a number read from a parameter: None and 0 are false.</summary>
        private static double? Truthy(double? v) { return v.HasValue && v.Value != 0.0 ? v : null; }

        /// <summary>getattr(obj, name, None) by reflection (the duck typing the Python relies on).</summary>
        private static object Prop(object o, string name)
        {
            if (o == null) return null;
            System.Reflection.PropertyInfo pi = o.GetType().GetProperty(name);
            return pi == null ? null : pi.GetValue(o, null);
        }

        // ================================================================ basics
        /// <summary>getattr(DB.BuiltInCategory, name, None).</summary>
        public static BuiltInCategory? BicOrNone(string name)
        {
            BuiltInCategory v;
            if (Enum.TryParse<BuiltInCategory>(name, out v) && Enum.IsDefined(typeof(BuiltInCategory), v)) return v;
            return null;
        }

        public static bool CatIs(Element el, string name)
        {
            BuiltInCategory? b = BicOrNone(name);
            try
            {
                return b != null && el.Category != null && Eid(el.Category.Id) == (long)(int)b.Value;
            }
            catch (Exception) { return false; }
        }

        /// <summary>The settings key (BuiltInCategory name) of the hanger category an element is in, or null.</summary>
        public static string HangerCatKey(Element el)
        {
            foreach (var kv in HfamCore.Categories.Skip(1))
            {
                if (CatIs(el, kv.Key)) return kv.Key;
            }
            return null;
        }

        /// <summary>getattr(DB.BuiltInParameter, name, None).</summary>
        public static BuiltInParameter? Bip(string name) { return FhaRevit.Bip(name); }

        public static double? ParamDouble(Element el, string bipName)
        {
            try
            {
                BuiltInParameter? b = Bip(bipName);
                Parameter p = b != null ? el.get_Parameter(b.Value) : null;
                if (p != null && p.HasValue) return p.AsDouble();
            }
            catch (Exception) { }
            return null;
        }

        /// <summary>A Revit MEP curve a hanger can carry: duct, pipe or cable tray.</summary>
        public static bool IsRvtDuct(Element el)
        {
            return el is Duct || el is Pipe || el is CableTray;
        }

        /// <summary>A fabrication duct or pipe part (not a hanger).</summary>
        public static bool IsFabService(Element el)
        {
            if (!(el is FabricationPart) || FhaRevit.IsHanger(el)) return false;
            return FhaRevit.IsDuct(el) || CatIs(el, "OST_FabricationPipework");
        }

        /// <summary>A straight a hanger can go on: a Revit duct, pipe or cable tray, or a fabrication duct / pipe straight.</summary>
        public static bool IsHostDuct(Element el)
        {
            if (IsRvtDuct(el)) return true;
            return IsFabService(el) && FhaRevit.IsStraight(el);
        }

        public static string ServiceKind(Element el)
        {
            if (el is Pipe) return "pipe";
            if (el is CableTray) return "cable tray";
            if (el is Duct) return "duct";
            if (el is FabricationPart) return CatIs(el, "OST_FabricationPipework") ? "FAB pipe" : "FAB duct";
            return "service";
        }

        /// <summary>DW/144 applies to ductwork only.</summary>
        public static bool IsDuctwork(Element el)
        {
            return el is Duct || (el is FabricationPart && FhaRevit.IsDuct(el));
        }

        public static readonly string[] RunCategories =
        {
            "OST_DuctFitting", "OST_DuctAccessory", "OST_PipeFitting", "OST_PipeAccessory", "OST_CableTrayFitting",
        };

        public static bool IsRunMember(Element el)
        {
            if (IsRvtDuct(el)) return true;
            if (el is FabricationPart) return IsFabService(el);
            if (el is FamilyInstance) return RunCategories.Any(c => CatIs(el, c));
            return false;
        }

        public static readonly string[] UnitCategories = { "OST_MechanicalEquipment", "OST_DuctAccessory" };

        /// <summary>Mechanical equipment or a duct accessory a hanger can go under.</summary>
        public static bool IsUnit(Element el)
        {
            return el is FamilyInstance && UnitCategories.Any(c => CatIs(el, c));
        }

        public static bool IsHangerFamily(Element el)
        {
            return el is FamilyInstance && HangerCatKey(el) != null;
        }

        /// <summary>The Python _Filter(test, points=False): an ISelectionFilter around a test function.</summary>
        public class HfamFilter : ISelectionFilter
        {
            public Func<Element, bool> Test;
            public bool Points;

            public HfamFilter(Func<Element, bool> test, bool points = false)
            {
                Test = test;
                Points = points;
            }

            public bool AllowElement(Element e)
            {
                try { return Test(e); }
                catch (Exception) { return false; }
            }

            public bool AllowReference(Reference r, XYZ p) { return Points; }
        }

        /// <summary>The Python (duct, point) pair pick_duct_point returns: Point is null when the click had no point.</summary>
        public class PickedPoint
        {
            public Element Element;
            public V3? Point;
        }

        /// <summary>(duct, picked point or null). A point on the duct's face, so the hanger lands where the user
        /// clicked; falls back to an element pick. Esc throws OperationCanceledException (as the Python re-raised).</summary>
        public static PickedPoint PickDuctPoint(UIDocument uidoc, string prompt, Func<Element, bool> test = null)
        {
            Document doc = uidoc.Document;
            if (test == null) test = IsHostDuct;
            Reference r;
            try
            {
                r = uidoc.Selection.PickObject(ObjectType.PointOnElement, new HfamFilter(test, true), prompt);
            }
            catch (Exception ex)
            {
                if (ex.GetType().Name.Contains("Cancel") || (ex.Message ?? "").ToLowerInvariant().Contains("cancel"))
                    throw;
                r = uidoc.Selection.PickObject(ObjectType.Element, new HfamFilter(test), prompt);
            }
            V3? p = null;
            try
            {
                if (r.GlobalPoint != null) p = Pt(r.GlobalPoint);
            }
            catch (Exception) { p = null; }
            return new PickedPoint { Element = doc.GetElement(r.ElementId), Point = p };
        }

        // ================================================================= debug
        /// <summary>Millimetres of a length in feet, no decimals; "-" for null.</summary>
        public static string Fmm(double? v)
        {
            try { return Fm(v.Value * MM, 0); }
            catch (Exception) { return "-"; }
        }

        /// <summary>'(x, y, z)' in millimetres; "-" for null.</summary>
        public static string Fpt(V3? p)
        {
            try { return "(" + Fm(p.Value.X * MM, 0) + ", " + Fm(p.Value.Y * MM, 0) + ", " + Fm(p.Value.Z * MM, 0) + ")"; }
            catch (Exception) { return "-"; }
        }

        /// <summary>'Duct 123456 (Rectangular Duct : Default)' style label for the log.</summary>
        public static string Describe(Element el)
        {
            string kind;
            try
            {
                kind = (IsRvtDuct(el) || el is FabricationPart) ? ServiceKind(el) : el.Category.Name;
            }
            catch (Exception) { kind = "element"; }
            string name = ElName(el);
            return kind + " " + Inv(Eid(el.Id)) + (name.Length > 0 ? " (" + name + ")" : "");
        }

        /// <summary>Everything worth knowing before a family job starts. symbol / cfg may be null.</summary>
        public static void LogContext(UIDocument uidoc, FhaSettings settings, FhaDebugLog log, string title, FamilySymbol symbol = null, FamConfig cfg = null)
        {
            Document doc = uidoc.Document;
            log.Add("== " + title + (IsFloor(settings) ? " (Family Floor Support tab)" : ""));
            try { log.Add("model: " + doc.Title + " | workshared: " + doc.IsWorkshared.ToString()); }
            catch (Exception) { }
            try
            {
                View v = uidoc.ActiveView;
                log.Add("view: " + ElName(v) + " | type " + v.ViewType.ToString() + " | scale 1:" + Inv(v.Scale));
            }
            catch (Exception) { }
            try
            {
                log.Add("levels: " + string.Join(", ", Levels(doc).Select(le => ElName(le.Level) + " @ " + Fmm(le.Elev))));
            }
            catch (Exception) { }
            if (symbol != null)
            {
                try
                {
                    log.Add("hanger: " + ElName(symbol.Family) + " : " + ElName(symbol) + " | category " + symbol.Category.Name
                            + " | placement " + symbol.Family.FamilyPlacementType.ToString() + " | active " + symbol.IsActive.ToString());
                }
                catch (Exception ex)
                {
                    log.Add("hanger: ? (" + ex.Message + ")");
                }
            }
            if (cfg != null)
            {
                var keys = new List<string>(HfamCore.FamKeys);
                if (cfg.Mode != null) keys.Add("mode");
                keys.Sort(StringComparer.Ordinal);
                log.Add("family settings: " + string.Join(" | ", keys.Select(k => k + "=" + (cfg[k] ?? "None"))));
            }
            var fkeys = settings.Keys.Where(k => k.StartsWith("fam_", StringComparison.Ordinal)).ToList();
            fkeys.Sort(StringComparer.Ordinal);
            log.Add("tab settings: " + string.Join(" | ", fkeys.Select(k => k + "=" + (settings[k] ?? "None"))));
        }

        public static void LogSection(FhaDebugLog log, Section sec)
        {
            if (sec.Unit)
            {
                log.Add("   unit " + Fmm(sec.Width) + " wide x " + Fmm(sec.Length ?? 0.0) + " long x " + Fmm(sec.Depth)
                        + " high | bottom face at " + Fmm(sec.Bottom) + " | hanger runs across it, the unit runs along "
                        + (sec.RunFrom ?? "?") + " | centre line " + Fpt(sec.A) + " -> " + Fpt(sec.B));
                return;
            }
            double ins = sec.Ins;
            log.Add("   duct " + Fmm(sec.BareWidth ?? sec.Width) + " x " + Fmm(sec.BareDepth ?? sec.Depth) + " mm"
                    + (sec.Round ? " round" : "") + " | insulation " + Fmm(ins) + " mm"
                    + (ins > 0 ? (sec.InsUsed ? " (outside it)" : " (inside it)") : "")
                    + " | hanger fits " + Fmm(sec.Width) + " x " + Fmm(sec.Depth) + " | centreline " + Fpt(sec.A) + " -> " + Fpt(sec.B));
        }

        // ============================================================ settings the window hands the jobs
        /// <summary>The window's chosen hanger type (the Python settings['_fam'] dict: id, family, cfg).</summary>
        public class HfamChoice
        {
            public ElementId Id;
            public string Family;
            public FamConfig Cfg;
        }

        private class Extras
        {
            public HfamChoice Choice;
            public Dictionary<string, FamConfig> Fams;
        }

        private static readonly ConditionalWeakTable<FhaSettings, Extras> ExtrasTable = new ConditionalWeakTable<FhaSettings, Extras>();

        /// <summary>The most recent SetFamilies call (a fallback when the job got a COPY of the settings the choice was attached to).</summary>
        public static HfamChoice LastChoice;
        public static Dictionary<string, FamConfig> LastFams;

        /// <summary>The Python settings['_fam'] and settings['_fams'] (FhaSettings only holds strings). The window calls
        /// this on the settings it queues with a job; the jobs read them back with ChoiceOf / FamsOf.</summary>
        public static void SetFamilies(FhaSettings settings, HfamChoice choice, Dictionary<string, FamConfig> fams)
        {
            Extras ex = ExtrasTable.GetOrCreateValue(settings);
            ex.Choice = choice;
            ex.Fams = fams;
            LastChoice = choice;
            LastFams = fams;
        }

        /// <summary>settings['_fam'], or null (the Python empty dict).</summary>
        public static HfamChoice ChoiceOf(FhaSettings settings)
        {
            Extras ex;
            if (settings != null && ExtrasTable.TryGetValue(settings, out ex) && ex.Choice != null) return ex.Choice;
            return LastChoice;
        }

        /// <summary>settings['_fams'] (family name -> its settings), never null.</summary>
        public static Dictionary<string, FamConfig> FamsOf(FhaSettings settings)
        {
            Extras ex;
            if (settings != null && ExtrasTable.TryGetValue(settings, out ex) && ex.Fams != null) return ex.Fams;
            return LastFams ?? new Dictionary<string, FamConfig>(StringComparer.Ordinal);
        }

        // ============================================================ family list
        /// <summary>Every type of every family in the three hanger categories.</summary>
        public static List<FamTypeItem> ListFamilyTypes(Document doc)
        {
            var o = new List<FamTypeItem>();
            foreach (var kv in HfamCore.Categories.Skip(1))
            {
                BuiltInCategory? b = BicOrNone(kv.Key);
                if (b == null) continue;   // MEP Ancillary Framing is not in every release
                FilteredElementCollector col;
                try { col = new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(b.Value); }
                catch (Exception) { continue; }
                foreach (Element e in col)
                {
                    try
                    {
                        FamilySymbol s = (FamilySymbol)e;
                        string fam = ElName(s.Family);
                        string typ = ElName(s);
                        o.Add(new FamTypeItem { Key = HfamCore.ItemKey(fam, typ), Family = fam, Type = typ, Cat = kv.Key, CatLabel = kv.Value, Id = s.Id });
                    }
                    catch (Exception) { continue; }
                }
            }
            return o.Select((x, i) => new { x, i })
                    .OrderBy(z => z.x.Family.ToLowerInvariant(), StringComparer.Ordinal)
                    .ThenBy(z => z.x.Type.ToLowerInvariant(), StringComparer.Ordinal)
                    .ThenBy(z => z.i).Select(z => z.x).ToList();
        }

        /// <summary>PNG bytes of a type's preview image, or null.</summary>
        public static byte[] PreviewBytes(Document doc, ElementId symbolId, int px = 112)
        {
            try
            {
                Element s = doc.GetElement(symbolId);
                using (System.Drawing.Bitmap bmp = ((ElementType)s).GetPreviewImage(new System.Drawing.Size(px, px)))
                {
                    if (bmp == null) return null;
                    using (MemoryStream ms = new MemoryStream())
                    {
                        bmp.Save(ms, System.Drawing.Imaging.ImageFormat.Png);
                        return ms.ToArray();
                    }
                }
            }
            catch (Exception) { return null; }
        }

        /// <summary>family_param_names' (names, source) pair.</summary>
        public class FamParamNames
        {
            public List<string> Names = new List<string>();
            public string Source = "";
        }

        /// <summary>Names of the writable numeric instance parameters of the family.
        /// From an instance already in the model when there is one, otherwise by
        /// opening the family (read only, closed without saving).</summary>
        public static FamParamNames FamilyParamNames(Document doc, ElementId symbolId, FhaDebugLog log)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            string source = "";
            Family fam;
            try
            {
                FamilySymbol s = (FamilySymbol)doc.GetElement(symbolId);
                fam = s.Family;
            }
            catch (Exception)
            {
                return new FamParamNames { Names = new List<string>(), Source = "type not found" };
            }
            try
            {
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FamilyInstance)))
                {
                    FamilyInstance inst = (FamilyInstance)e;
                    try
                    {
                        if (Eid(inst.Symbol.Family.Id) != Eid(fam.Id)) continue;
                    }
                    catch (Exception) { continue; }
                    foreach (Parameter p in inst.Parameters)
                    {
                        try
                        {
                            if (!p.IsReadOnly && p.StorageType == StorageType.Double) names.Add(p.Definition.Name);
                        }
                        catch (Exception) { }
                    }
                    source = "an instance in the model";
                    break;
                }
            }
            catch (Exception ex)
            {
                log.Add("instance params: " + ex.Message);
            }
            if (names.Count == 0)
            {
                Document fdoc = null;
                try
                {
                    fdoc = doc.EditFamily(fam);
                    foreach (FamilyParameter fp in fdoc.FamilyManager.Parameters)
                    {
                        try
                        {
                            if (fp.IsInstance && fp.StorageType == StorageType.Double) names.Add(fp.Definition.Name);
                        }
                        catch (Exception) { }
                    }
                    source = "the family";
                }
                catch (Exception ex)
                {
                    log.Add("family params: " + ex.Message);
                    source = "nothing (place one instance, then try again)";
                }
                finally
                {
                    try
                    {
                        if (fdoc != null) fdoc.Close(false);
                    }
                    catch (Exception) { }
                }
            }
            return new FamParamNames
            {
                Names = names.Select((n, i) => new { n, i }).OrderBy(z => z.n.ToLowerInvariant(), StringComparer.Ordinal).ThenBy(z => z.i).Select(z => z.n).ToList(),
                Source = source,
            };
        }
    }
}

