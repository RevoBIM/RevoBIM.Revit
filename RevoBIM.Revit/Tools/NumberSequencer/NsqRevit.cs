using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Mechanical;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.NumberSequencer
{
    public class NetworkData
    {
        public Dictionary<long, Node> Nodes = new Dictionary<long, Node>();
        public List<NsqCore.TreeRow> Rows = new List<NsqCore.TreeRow>();
        public Dictionary<long, ElementId> IdMap = new Dictionary<long, ElementId>();
        public Dictionary<long, string> HostCat = new Dictionary<long, string>();
        public Dictionary<long, string> Labels = new Dictionary<long, string>();
        public Dictionary<long, string> SysName = new Dictionary<long, string>();
        public Dictionary<string, string> Storages = new Dictionary<string, string>();
        public Dictionary<long, List<string>> PerElem = new Dictionary<long, List<string>>();
        public HashSet<long> PassThrough = new HashSet<long>();
        public Dictionary<long, double[]> Points = new Dictionary<long, double[]>();
        public List<SysDef> Systems = new List<SysDef>();
        public Dictionary<string, List<ElementId>> Extras = new Dictionary<string, List<ElementId>>();
        public ElementId ViewId;
        public string ViewName = "";
        public string ViewType = "";
        public string DocKey = "";
        public string Kind = "";
        public bool Isolated;
        public bool SkippedIsolated;   // the view is isolated by the tool: nothing was read
        public List<TagChoice> Tags;
        public List<KeyValuePair<string, string>> Views3d = new List<KeyValuePair<string, string>>();
        public List<ElementId> Leftover = new List<ElementId>();
    }

    public class TagJob
    {
        public bool On;
        public TagChoice Choice;
        public Dictionary<string, TagChoice> ByHost = new Dictionary<string, TagChoice>();
        public bool UntaggedOnly = true;
        public bool PlansOnly;
        public List<ElementId> Views = new List<ElementId>();
        public string ViewsDoc;
    }

    public class ApplyJob
    {
        public string Param = "";
        public string Storage = "";
        public List<NsqCore.WriteItem> Writes = new List<NsqCore.WriteItem>();
        public List<long> Same = new List<long>();
        public Dictionary<long, ElementId> IdMap = new Dictionary<long, ElementId>();
        public TagJob Tag;
    }

    public class ApplyResult
    {
        public int Written, Same, Tagged, TagSkipped, TagViews, TagNoTag, TagAlready;
        public List<NsqCore.KeyMsg> Errors = new List<NsqCore.KeyMsg>();
    }

    public class SectionBoxMemory
    {
        public BoundingBoxXYZ Box;
    }

    /// <summary>
    /// Number Sequencer: everything that talks to Revit (port of nsq_revit.py). Reading the selection or a
    /// picked system, the connector graph, parameter and tag choices, and the apply job. Every function that
    /// writes runs inside the ExternalEvent handler (see the window).
    /// </summary>
    public static class NsqRevit
    {
        public static readonly string[] WalkCats =
        {
            "OST_DuctCurves", "OST_DuctFitting", "OST_DuctAccessory", "OST_FlexDuctCurves", "OST_DuctTerminal",
            "OST_FabricationDuctwork", "OST_PlaceHolderDucts",
        };
        public const string EquipCat = "OST_MechanicalEquipment";
        public const int NetworkLimit = 20000;
        public const double SectionBoxMargin = 1.0;   // feet (300 mm) round the systems

        // ============================================================ Small helpers

        public static long EidValue(ElementId id)
        {
            if (id == null) return 0;
            try { return id.Value; } catch (Exception) { return 0; }
        }

        public static List<ElementId> IdList(IEnumerable<ElementId> ids) { return ids.Where(i => i != null).ToList(); }

        private static readonly Dictionary<string, long?> BicCache = new Dictionary<string, long?>();

        public static long? BicInt(string name)
        {
            long? v;
            if (BicCache.TryGetValue(name, out v)) return v;
            BuiltInCategory b;
            if (Enum.TryParse(name, out b)) v = (long)(int)b; else v = null;
            BicCache[name] = v;
            return v;
        }

        public static BuiltInCategory? Bic(string name)
        {
            BuiltInCategory b;
            return Enum.TryParse(name, out b) ? (BuiltInCategory?)b : null;
        }

        public static long? CatInt(Element elem)
        {
            try
            {
                if (elem == null || elem.Category == null) return null;
                return EidValue(elem.Category.Id);
            }
            catch (Exception) { return null; }
        }

        public static string CatLabel(Element elem)
        {
            try { return elem.Category.Name ?? ""; } catch (Exception) { return ""; }
        }

        public static string BicNameOf(Element elem, IEnumerable<string> names)
        {
            long? ci = CatInt(elem);
            foreach (string n in names) if (BicInt(n) == ci) return n;
            return null;
        }

        public static List<string> KnownCats()
        {
            var names = new List<string>(WalkCats) { EquipCat };
            foreach (string kind in NsqCore.Kinds.Keys.OrderBy(x => x, StringComparer.Ordinal))
            {
                var kd = NsqCore.Kinds[kind];
                foreach (string n in kd.Walk.Concat(kd.Through).Concat(kd.Ends)) if (!names.Contains(n)) names.Add(n);
            }
            return names;
        }

        public static string HostCatName(Element elem)
        {
            return BicNameOf(elem, KnownCats()) ?? CatLabel(elem);
        }

        public static string ElemName(Element elem)
        {
            if (elem == null) return "";
            try { return elem.Name ?? ""; } catch (Exception) { return ""; }
        }

        public static string BipText(Element elem, BuiltInParameter bip)
        {
            try
            {
                Parameter p = elem.get_Parameter(bip);
                if (p == null) return "";
                string s = p.AsValueString();
                if (string.IsNullOrEmpty(s)) s = p.AsString();
                return s ?? "";
            }
            catch (Exception) { return ""; }
        }

        private static string PropText(object obj, string name)
        {
            try
            {
                PropertyInfo pi = obj.GetType().GetProperty(name);
                if (pi == null) return "";
                object v = pi.GetValue(obj, null);
                return v == null ? "" : v.ToString();
            }
            catch (Exception) { return ""; }
        }

        /// <summary>Category, family and type names of an element.</summary>
        public static void FamilyType(Document doc, Element elem, out string cat, out string fam, out string typ)
        {
            fam = "";
            typ = "";
            if (elem is FabricationPart)
            {
                foreach (string attr in new[] { "ProductLongDescription", "ProductName", "ProductShortDescription", "Alias" })
                {
                    string v = PropText(elem, attr);
                    if (v.Length > 0) { fam = v; break; }
                }
                foreach (string attr in new[] { "ProductSizeDescription", "Size" })
                {
                    string v = PropText(elem, attr);
                    if (v.Length > 0) { typ = v; break; }
                }
            }
            if (fam.Length == 0) fam = BipText(elem, BuiltInParameter.ELEM_FAMILY_PARAM);
            if (typ.Length == 0) typ = BipText(elem, BuiltInParameter.ELEM_TYPE_PARAM);
            if (fam.Length == 0 || typ.Length == 0)
            {
                Element t = null;
                try { t = doc.GetElement(elem.GetTypeId()); } catch (Exception) { }
                if (t != null)
                {
                    if (fam.Length == 0) { try { fam = (t as ElementType)?.FamilyName ?? ""; } catch (Exception) { fam = ""; } }
                    if (typ.Length == 0) typ = ElemName(t);
                }
            }
            cat = CatLabel(elem);
        }

        // ============================================================ Connectors

        public static ConnectorManager GetConnectorManager(Element elem)
        {
            try
            {
                MEPCurve mc = elem as MEPCurve;
                if (mc != null && mc.ConnectorManager != null) return mc.ConnectorManager;
            }
            catch (Exception) { }
            try
            {
                FabricationPart fp = elem as FabricationPart;
                if (fp != null && fp.ConnectorManager != null) return fp.ConnectorManager;
            }
            catch (Exception) { }
            try
            {
                FamilyInstance fi = elem as FamilyInstance;
                if (fi != null && fi.MEPModel != null) return fi.MEPModel.ConnectorManager;
            }
            catch (Exception) { }
            return null;
        }

        public static bool IsPhysical(Connector conn)
        {
            string t;
            try { t = conn.ConnectorType.ToString(); } catch (Exception) { return false; }
            if (t == "Logical" || t == "Reference" || t == "Invalid" || t == "NodeReference") return false;
            try
            {
                string d = conn.Domain.ToString();
                if (d == "DomainElectrical" || d == "DomainCableTrayConduit") return false;
            }
            catch (Exception) { }
            return true;
        }

        public static List<Connector> IterConnectors(Element elem)
        {
            var o = new List<Connector>();
            ConnectorManager cm = GetConnectorManager(elem);
            if (cm == null) return o;
            try
            {
                foreach (Connector c in cm.Connectors) if (IsPhysical(c)) o.Add(c);
            }
            catch (Exception) { }
            return o;
        }

        public static double ConnArea(Connector conn)
        {
            try
            {
                if (conn.Shape == ConnectorProfileType.Round)
                {
                    double r = conn.Radius;
                    return Math.PI * r * r;
                }
                return conn.Width * conn.Height;
            }
            catch (Exception) { return 0.0; }
        }

        private static double[] Xyz(XYZ p)
        {
            try { return p == null ? null : new[] { p.X, p.Y, p.Z }; } catch (Exception) { return null; }
        }

        public static List<Connector> ConnRefs(Connector conn)
        {
            var o = new List<Connector>();
            try
            {
                foreach (Connector r in conn.AllRefs) if (IsPhysical(r)) o.Add(r);
            }
            catch (Exception) { }
            return o;
        }

        public static bool HasDuctConnectors(Element elem) { return IterConnectors(elem).Count > 0; }

        // ============================================================ Reading what to number

        /// <summary>Selected ids -> elements to number. A selected duct system expands to its network.</summary>
        public static List<Element> ExpandSelection(Document doc, IEnumerable<ElementId> ids)
        {
            var o = new List<Element>();
            var seen = new HashSet<long>();
            Action<Element> add = e =>
            {
                long k = EidValue(e.Id);
                if (seen.Contains(k) || !HasDuctConnectors(e)) return;
                seen.Add(k);
                o.Add(e);
            };
            foreach (ElementId eid in ids)
            {
                Element e = doc.GetElement(eid);
                if (e == null) continue;
                if (HasDuctConnectors(e)) { add(e); continue; }
                MEPSystem sys = e as MEPSystem;
                if (sys != null)
                {
                    try { foreach (Element m in sys.Elements) add(m); } catch (Exception) { }
                }
            }
            return o;
        }

        public static HashSet<long> WalkInts()
        {
            var s = new HashSet<long>();
            foreach (string n in WalkCats) { long? i = BicInt(n); if (i != null) s.Add(i.Value); }
            return s;
        }

        /// <summary>Everything connected to start through duct connectors. Equipment is a boundary.</summary>
        public static List<Element> CollectNetwork(Document doc, Element start, int limit = NetworkLimit)
        {
            var walk = WalkInts();
            var o = new List<Element> { start };
            var seen = new HashSet<long> { EidValue(start.Id) };
            var queue = new Queue<Element>();
            queue.Enqueue(start);
            while (queue.Count > 0 && o.Count < limit)
            {
                Element e = queue.Dequeue();
                foreach (Connector c in IterConnectors(e))
                    foreach (Connector r in ConnRefs(c))
                    {
                        Element owner = null;
                        try { owner = r.Owner; } catch (Exception) { continue; }
                        if (owner == null) continue;
                        long k = EidValue(owner.Id);
                        long? ci = CatInt(owner);
                        if (seen.Contains(k) || ci == null || !walk.Contains(ci.Value)) continue;
                        seen.Add(k);
                        o.Add(owner);
                        queue.Enqueue(owner);
                    }
            }
            return o;
        }

        /// <summary>Elements -> everything the window needs, keyed by id value.</summary>
        public static NetworkData ReadNetwork(Document doc, List<Element> elems, DebugLog log)
        {
            long? eq = BicInt(EquipCat);
            var keys = new HashSet<long>(elems.Select(e => EidValue(e.Id)));
            var data = new NetworkData();
            foreach (Element e in elems)
            {
                long k = EidValue(e.Id);
                data.IdMap[k] = e.Id;
                string cat, fam, typ;
                FamilyType(doc, e, out cat, out fam, out typ);
                data.Rows.Add(new NsqCore.TreeRow { ElementKey = k, Category = cat, Family = fam, Type = typ });
                data.HostCat[k] = HostCatName(e);
                double[] pt = ElemPoint(e);
                if (pt != null) data.Points[k] = pt;
                data.SysName[k] = BipText(e, BuiltInParameter.RBS_SYSTEM_NAME_PARAM);
                data.Labels[k] = cat + " : " + fam + " : " + typ;
                var node = new Node { Key = k, IsEquipment = CatInt(e) == eq && eq != null, Label = data.Labels[k] };
                foreach (Connector c in IterConnectors(e))
                {
                    var conn = new Conn { Cid = c.Id, Area = ConnArea(c), Origin = Xyz(c.Origin) };
                    try { conn.Direction = Xyz(c.CoordinateSystem.BasisZ); } catch (Exception) { conn.Direction = null; }
                    foreach (Connector r in ConnRefs(c))
                    {
                        Element o = null;
                        try { o = r.Owner; } catch (Exception) { continue; }
                        if (o == null) continue;
                        long ok = EidValue(o.Id);
                        if (ok == k) continue;
                        if (keys.Contains(ok)) conn.Links.Add(new KeyValuePair<long, int>(ok, r.Id));
                        else
                        {
                            conn.External = true;
                            if (CatInt(o) == eq && eq != null) conn.Equipment = true;
                        }
                    }
                    node.Conns.Add(conn);
                }
                data.Nodes[k] = node;
            }
            int links = data.Nodes.Values.Sum(n => n.Conns.Sum(c => c.Links.Count)) / 2;
            int butted = NsqCore.LinkOpenEnds(data.Nodes, NsqCore.OpenEndTolMm / 304.8);
            log.Add("read " + data.Nodes.Count + " elements: " + links + " connections in Revit, " + butted +
                    " more joined where open ends touch (parts butted but never connected)");
            return data;
        }

        // ============================================================ Parameters

        private static bool IsYesNo(Parameter p)
        {
            try { return p.Definition.GetDataType().TypeId == SpecTypeId.Boolean.YesNo.TypeId; } catch (Exception) { return false; }
        }

        private static bool IsBuiltIn(Parameter p)
        {
            try
            {
                InternalDefinition d = p.Definition as InternalDefinition;
                return d != null && d.BuiltInParameter != BuiltInParameter.INVALID;
            }
            catch (Exception) { return false; }
        }

        /// <summary>'text', 'integer', or null (not a number or text).</summary>
        public static string Storage(Parameter p)
        {
            try
            {
                if (p.StorageType == StorageType.String) return "text";
                if (p.StorageType == StorageType.Integer)
                {
                    if (IsYesNo(p) || IsBuiltIn(p)) return null;
                    return "integer";
                }
            }
            catch (Exception) { }
            return null;
        }

        /// <summary>Writable text / integer instance parameters per element.</summary>
        public static void ParamMap(IEnumerable<Element> elems, out Dictionary<string, string> storages, out Dictionary<long, List<string>> perElem)
        {
            storages = new Dictionary<string, string>();
            perElem = new Dictionary<long, List<string>>();
            foreach (Element e in elems)
            {
                var names = new List<string>();
                List<Parameter> ps;
                try { ps = e.Parameters.Cast<Parameter>().ToList(); } catch (Exception) { ps = new List<Parameter>(); }
                foreach (Parameter p in ps)
                {
                    string name, st;
                    try
                    {
                        if (p.IsReadOnly) continue;
                        st = Storage(p);
                        if (st == null) continue;
                        name = p.Definition.Name;
                    }
                    catch (Exception) { continue; }
                    if (string.IsNullOrEmpty(name) || names.Contains(name)) continue;
                    names.Add(name);
                    if (!storages.ContainsKey(name)) storages[name] = st;
                }
                perElem[EidValue(e.Id)] = names;
            }
        }

        public static ParamInfo ReadParamInfo(Element elem, string name)
        {
            if (elem == null) return null;
            Parameter p = null;
            try { p = elem.LookupParameter(name); } catch (Exception) { }
            if (p == null) return new ParamInfo { Exists = false };
            var info = new ParamInfo { Exists = true, ReadOnly = p.IsReadOnly, Storage = Storage(p) ?? "" };
            try
            {
                if (info.Storage == "integer")
                {
                    if (p.HasValue) info.Value = p.AsInteger().ToString(); else { info.Value = ""; info.ValueNull = true; }
                }
                else info.Value = p.AsString() ?? "";
            }
            catch (Exception) { info.Value = ""; info.ValueNull = true; }
            return info;
        }

        public static string ReadParamValue(Element elem, string name, string storage)
        {
            try
            {
                Parameter p = elem.LookupParameter(name);
                if (storage == "integer") return p.AsInteger().ToString();
                return p.AsString();
            }
            catch (Exception) { return null; }
        }

        // ============================================================ Tags

        public static List<TagChoice> TagChoices(Document doc)
        {
            var ints = new Dictionary<long, string>();
            foreach (string n in NsqCore.TagHosts.Keys)
            {
                long? i = BicInt(n);
                if (i != null) ints[i.Value] = n;
            }
            var o = new List<TagChoice>();
            List<FamilySymbol> symbols;
            try { symbols = new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>().ToList(); }
            catch (Exception) { symbols = new List<FamilySymbol>(); }
            foreach (FamilySymbol s in symbols)
            {
                long? ci = CatInt(s);
                if (ci == null || !ints.ContainsKey(ci.Value)) continue;
                string fam = "";
                try { fam = s.FamilyName; } catch (Exception) { }
                o.Add(new TagChoice
                {
                    Label = CatLabel(s) + " : " + fam + " : " + ElemName(s),
                    Id = s.Id,
                    TypeId = EidValue(s.Id),
                    TagCat = ints[ci.Value],
                });
            }
            return o.OrderBy(d => d.Label.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        public static bool ViewCanTag(View view, out string why, bool plansOnly = false)
        {
            why = "Not a view";
            if (view == null) return false;
            bool template = false;
            try { template = view.IsTemplate; } catch (Exception) { }
            bool locked = false;
            View3D v3 = view as View3D;
            if (v3 != null) { try { locked = v3.IsLocked; } catch (Exception) { } }
            return NsqCore.TagViewOk(view.ViewType.ToString(), out why, template, locked, plansOnly);
        }

        /// <summary>{element id value: tag type id values} for every tag in the view.</summary>
        public static Dictionary<long, HashSet<long>> TagsInView(Document doc, View view)
        {
            var o = new Dictionary<long, HashSet<long>>();
            List<IndependentTag> tags;
            try { tags = new FilteredElementCollector(doc, view.Id).OfClass(typeof(IndependentTag)).Cast<IndependentTag>().ToList(); }
            catch (Exception) { tags = new List<IndependentTag>(); }
            foreach (IndependentTag t in tags)
            {
                long tid;
                try { tid = EidValue(t.GetTypeId()); } catch (Exception) { continue; }
                List<long> ids;
                try { ids = t.GetTaggedLocalElementIds().Select(EidValue).ToList(); }
                catch (Exception) { ids = new List<long>(); }
                foreach (long i in ids)
                {
                    HashSet<long> set;
                    if (!o.TryGetValue(i, out set)) { set = new HashSet<long>(); o[i] = set; }
                    set.Add(tid);
                }
            }
            return o;
        }

        public static XYZ TagPoint(Element elem, View view)
        {
            try
            {
                Location loc = elem.Location;
                LocationCurve lc = loc as LocationCurve;
                if (lc != null) return lc.Curve.Evaluate(0.5, true);
                LocationPoint lp = loc as LocationPoint;
                if (lp != null) return lp.Point;
            }
            catch (Exception) { }
            foreach (View v in new View[] { view, null })
            {
                try
                {
                    BoundingBoxXYZ bb = elem.get_BoundingBox(v);
                    if (bb != null) return (bb.Min + bb.Max) * 0.5;
                }
                catch (Exception) { }
            }
            return null;
        }

        // ============================================================ The write

        public class WarningSwallower : IFailuresPreprocessor
        {
            public List<string> Messages = new List<string>();

            public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
            {
                try
                {
                    foreach (FailureMessageAccessor f in accessor.GetFailureMessages())
                    {
                        if (f.GetSeverity() == FailureSeverity.Warning) accessor.DeleteWarning(f);
                        else { try { Messages.Add(f.GetDescriptionText()); } catch (Exception) { } }
                    }
                }
                catch (Exception) { }
                return FailureProcessingResult.Continue;
            }
        }

        public static Transaction MakeTransaction(Document doc, string name, out WarningSwallower sw)
        {
            var t = new Transaction(doc, name);
            sw = new WarningSwallower();
            try
            {
                FailureHandlingOptions opts = t.GetFailureHandlingOptions();
                opts.SetFailuresPreprocessor(sw);
                t.SetFailureHandlingOptions(opts);
            }
            catch (Exception) { }
            return t;
        }

        private static bool Committed(TransactionStatus s) { return s == TransactionStatus.Committed; }

        private static void RollBackQuietly(Transaction t)
        {
            try { if (t != null && t.HasStarted() && !t.HasEnded()) t.RollBack(); } catch (Exception) { }
        }

        /// <summary>Borrow before writing. Returns the ok keys and the refused ones.</summary>
        public static List<long> Checkout(Document doc, List<long> keys, Dictionary<long, ElementId> idmap, DebugLog log, out List<NsqCore.KeyMsg> refused)
        {
            refused = new List<NsqCore.KeyMsg>();
            if (keys.Count == 0) return new List<long>();
            bool shared = false;
            try { shared = doc.IsWorkshared; } catch (Exception) { }
            if (!shared) return new List<long>(keys);
            var held = new HashSet<long>();
            try
            {
                foreach (ElementId i in WorksharingUtils.CheckoutElements(doc, keys.Select(k => idmap[k]).ToList())) held.Add(EidValue(i));
            }
            catch (Exception ex) { log.Add("CheckoutElements failed: " + ex); }
            string me = "";
            try { me = doc.Application.Username ?? ""; } catch (Exception) { }
            var ok = new List<long>();
            foreach (long k in keys)
            {
                if (held.Contains(k)) { ok.Add(k); continue; }
                string owner = "";
                try { owner = WorksharingUtils.GetWorksharingTooltipInfo(doc, idmap[k]).Owner ?? ""; } catch (Exception) { }
                if (owner.Length == 0 || owner == me) ok.Add(k);
                else refused.Add(new NsqCore.KeyMsg { Key = k, Msg = "Borrowed by " + owner });
            }
            log.Add("checkout: " + ok.Count + " ok, " + refused.Count + " refused");
            return ok;
        }

        private static string WriteOne(Element elem, string name, NsqCore.WriteItem w)
        {
            Parameter p = elem.LookupParameter(name);
            if (p == null) return "Parameter not on this element";
            if (p.IsReadOnly) return "Parameter is read-only here";
            bool ok = w.IsInt ? p.Set(w.IntValue) : p.Set(w.TextValue ?? "");
            return ok ? null : "Revit refused the value";
        }

        public static ApplyResult ApplyJobRun(UIApplication uiapp, ApplyJob job, DebugLog log)
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;
            string name = job.Param;
            var idmap = job.IdMap;
            var res = new ApplyResult { Same = job.Same.Count };
            var errors = res.Errors;

            var writeKeys = job.Writes.Select(w => w.Key).ToList();
            var values = job.Writes.ToDictionary(w => w.Key, w => w);
            List<NsqCore.KeyMsg> refused;
            List<long> okKeys = Checkout(doc, writeKeys, idmap, log, out refused);
            errors.AddRange(refused);

            var done = new List<long>();
            var tg = new TransactionGroup(doc, "RevoBIM Number Sequencer");
            tg.Start();
            try
            {
                // ---- numbers: one transaction, a sub-transaction per element
                if (okKeys.Count > 0)
                {
                    WarningSwallower sw;
                    Transaction t = MakeTransaction(doc, "Number sequence", out sw);
                    t.Start();
                    var failed = new List<NsqCore.KeyMsg>();
                    foreach (long k in okKeys)
                    {
                        Element elem = doc.GetElement(idmap[k]);
                        var st = new SubTransaction(doc);
                        st.Start();
                        string msg;
                        try { msg = WriteOne(elem, name, values[k]); } catch (Exception ex) { msg = ex.Message; }
                        if (msg != null) { st.RollBack(); failed.Add(new NsqCore.KeyMsg { Key = k, Msg = msg }); }
                        else { st.Commit(); done.Add(k); }
                    }
                    TransactionStatus status = t.Commit();
                    log.Add("numbers transaction: " + status + " (" + done.Count + " set, " + failed.Count + " refused)");
                    if (!Committed(status))
                    {
                        log.Add("falling back per element: " + string.Join("; ", sw.Messages));
                        done = new List<long>();
                        failed = new List<NsqCore.KeyMsg>();
                        foreach (long k in okKeys)
                        {
                            WarningSwallower sw1;
                            Transaction t1 = MakeTransaction(doc, "Number sequence", out sw1);
                            t1.Start();
                            string msg;
                            try { msg = WriteOne(doc.GetElement(idmap[k]), name, values[k]); } catch (Exception ex) { msg = ex.Message; }
                            if (msg != null) { t1.RollBack(); failed.Add(new NsqCore.KeyMsg { Key = k, Msg = msg }); continue; }
                            if (Committed(t1.Commit())) done.Add(k);
                            else failed.Add(new NsqCore.KeyMsg { Key = k, Msg = string.Join("; ", sw1.Messages).Length > 0 ? string.Join("; ", sw1.Messages) : "Revit rolled it back" });
                        }
                    }
                    errors.AddRange(failed);
                }

                // ---- tags
                TagJob tag = job.Tag;
                if (tag != null && tag.On && tag.Choice != null)
                {
                    var tagKeys = done.Concat(job.Same).ToList();
                    TagRun(doc, tag, tagKeys, idmap, res, log);
                }
                tg.Assimilate();
            }
            catch (Exception ex)
            {
                log.Add("apply failed: " + ex);
                try { tg.RollBack(); } catch (Exception) { }
                errors.Add(new NsqCore.KeyMsg { Key = 0, Msg = "Apply failed and was rolled back - see debug" });
                done = new List<long>();
            }

            // ---- read back after the group has closed
            foreach (long k in done)
            {
                string got = ReadParamValue(doc.GetElement(idmap[k]), name, job.Storage);
                if (NsqCore.ValueMatches(values[k], got)) res.Written++;
                else errors.Add(new NsqCore.KeyMsg { Key = k, Msg = "Reads back '" + got + "'" });
            }
            log.Add("result: written " + res.Written + ", unchanged " + res.Same + ", tagged " + res.Tagged + ", tag skipped " +
                    res.TagSkipped + ", errors " + errors.Count);
            return res;
        }

        /// <summary>Tag the numbered elements: in each ticked view, or in the active view.</summary>
        private static void TagRun(Document doc, TagJob tag, List<long> keys, Dictionary<long, ElementId> idmap, ApplyResult res, DebugLog log)
        {
            var ticked = tag.Views ?? new List<ElementId>();
            if (ticked.Count > 0 && tag.ViewsDoc != null && tag.ViewsDoc != DocKey(doc))
            {
                res.Errors.Add(new NsqCore.KeyMsg { Key = 0, Msg = "Tags not placed: the view list belongs to another document - press All views to read this one's" });
                return;
            }
            List<View> views;
            string why;
            if (ticked.Count > 0) views = PrimaryViews(doc, ticked);
            else
            {
                views = new List<View> { doc.ActiveView };
                if (!ViewCanTag(views[0], out why, tag.PlansOnly))
                {
                    res.Errors.Add(new NsqCore.KeyMsg { Key = 0, Msg = "Tags not placed: " + why });
                    return;
                }
            }
            res.TagViews = 0;
            VisibilityProbe probe = ticked.Count > 0 ? MakeVisibilityProbe(doc, keys.Where(idmap.ContainsKey).Select(k => idmap[k]).ToList()) : null;
            foreach (View view in views)
            {
                List<long> here;
                if (ticked.Count > 0)
                {
                    if (!ViewCanTag(view, out why, false))
                    {
                        res.Errors.Add(new NsqCore.KeyMsg { Key = 0, Msg = ElemName(view) + ": " + why });
                        continue;
                    }
                    HashSet<long> shown = VisibleInView(doc, view, null, false, probe);
                    here = keys.Where(shown.Contains).ToList();
                }
                else here = new List<long>(keys);
                if (here.Count == 0) continue;
                int n = TagView(doc, view, tag, here, idmap, res, log);
                if (n > 0) res.TagViews++;
            }
        }

        private static int TagView(Document doc, View view, TagJob tag, List<long> keys, Dictionary<long, ElementId> idmap, ApplyResult res, DebugLog log)
        {
            var marks = TagsInView(doc, view);
            var byHost = tag.ByHost ?? new Dictionary<string, TagChoice>();
            WarningSwallower sw;
            Transaction t = MakeTransaction(doc, "Tag sequence", out sw);
            t.Start();
            var used = new List<ElementId> { tag.Choice.Id };
            used.AddRange(byHost.Values.Where(v => v != null).Select(v => v.Id));
            foreach (ElementId tid in used)
            {
                try
                {
                    FamilySymbol sym = doc.GetElement(tid) as FamilySymbol;
                    if (sym != null && !sym.IsActive) sym.Activate();
                }
                catch (Exception) { }
            }
            var placed = new List<long>();
            foreach (long k in keys)
            {
                Element elem = doc.GetElement(idmap[k]);
                if (elem == null) continue;
                string host = HostCatName(elem);
                TagChoice use;
                if (byHost.ContainsKey(host)) use = byHost[host];
                else use = NsqCore.TagCanHost(tag.Choice.TagCat, host) ? tag.Choice : null;
                if (use == null) { res.TagSkipped++; res.TagNoTag++; continue; }
                HashSet<long> have;
                if (!marks.TryGetValue(EidValue(idmap[k]), out have)) have = new HashSet<long>();
                if (NsqCore.SkipTagging(have, EidValue(use.Id), tag.UntaggedOnly)) { res.TagSkipped++; res.TagAlready++; continue; }
                XYZ pt = TagPoint(elem, view);
                if (pt == null) { res.Errors.Add(new NsqCore.KeyMsg { Key = k, Msg = "No point to place the tag" }); continue; }
                var st = new SubTransaction(doc);
                st.Start();
                try
                {
                    IndependentTag.Create(doc, use.Id, view.Id, new Reference(elem), false, TagOrientation.Horizontal, pt);
                    st.Commit();
                    placed.Add(k);
                }
                catch (Exception ex)
                {
                    st.RollBack();
                    res.Errors.Add(new NsqCore.KeyMsg { Key = k, Msg = "Tag refused in " + ElemName(view) + ": " + ex.Message });
                }
            }
            TransactionStatus status = t.Commit();
            log.Add("tag " + ElemName(view) + ": " + placed.Count + " placed, " + status);
            if (Committed(status)) { res.Tagged += placed.Count; return placed.Count; }
            if (placed.Count > 0)
                res.Errors.Add(new NsqCore.KeyMsg { Key = 0, Msg = "Tags rolled back in " + ElemName(view) + ": " + (sw.Messages.Count > 0 ? string.Join("; ", sw.Messages) : "Revit refused") });
            return 0;
        }

        // ============================================================ Views to tag in

        private static string ParamText(Element elem, string name)
        {
            if (string.IsNullOrEmpty(name)) return "";
            try
            {
                Parameter p = elem.LookupParameter(name);
                if (p == null) return "";
                string s = p.AsValueString();
                if (string.IsNullOrEmpty(s)) s = p.AsString();
                return s ?? "";
            }
            catch (Exception) { return ""; }
        }

        /// <summary>Every view Tag in views offers - floor plans, sections and 3D views, no templates - sorted by name.</summary>
        public static List<View> TagViews(Document doc)
        {
            var o = new List<View>();
            List<View> items;
            try { items = new FilteredElementCollector(doc).OfClass(typeof(View)).Cast<View>().ToList(); } catch (Exception) { items = new List<View>(); }
            foreach (View v in items)
            {
                try { if (v.IsTemplate || !NsqCore.TagViewKinds.ContainsKey(v.ViewType.ToString())) continue; }
                catch (Exception) { continue; }
                o.Add(v);
            }
            return o.OrderBy(v => NsqCore.NaturalKey(ElemName(v)), new NsqCore.NaturalKeyComparer()).ToList();
        }

        public static List<View> FloorPlans(Document doc)
        {
            return TagViews(doc).Where(v => v.ViewType.ToString() == "FloorPlan").ToList();
        }

        /// <summary>Parameter names carried by views (sampled), for the group columns.</summary>
        public static List<string> ViewParamNames(List<View> views)
        {
            var names = new HashSet<string>();
            foreach (View v in views.Take(40))
            {
                try { foreach (Parameter p in v.Parameters) { try { names.Add(p.Definition.Name); } catch (Exception) { } } }
                catch (Exception) { }
            }
            return names.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        public static List<ViewRowData> ViewTable(Document doc, string g1, string g2, out List<string> paramNames)
        {
            List<View> views = TagViews(doc);
            var rows = new List<ViewRowData>();
            foreach (View v in views)
            {
                string level = "";
                try { ViewPlan vp = v as ViewPlan; if (vp != null && vp.GenLevel != null) level = vp.GenLevel.Name; } catch (Exception) { }
                string kind;
                NsqCore.TagViewKinds.TryGetValue(v.ViewType.ToString(), out kind);
                kind = kind ?? "";
                bool locked = true;
                View3D v3 = v as View3D;
                if (kind == "3D" && v3 != null) { try { locked = v3.IsLocked; } catch (Exception) { } }
                var row = new ViewRowData { Id = EidValue(v.Id).ToString(), Eid = v.Id, Uid = v.UniqueId, Locked = locked };
                row.Cols["name"] = ElemName(v);
                row.Cols["level"] = level;
                row.Cols["kind"] = kind;
                row.Cols["kind_text"] = NsqCore.KindText(kind, locked);
                row.Cols["g1"] = ParamText(v, g1);
                row.Cols["g2"] = ParamText(v, g2);
                rows.Add(row);
            }
            paramNames = ViewParamNames(views);
            return rows;
        }

        /// <summary>Every sheet (no placeholders) with the views placed on it that Tag in views lists.</summary>
        public static List<SheetData> SheetTable(Document doc, IEnumerable<long> viewValues)
        {
            var want = new HashSet<long>(viewValues);
            var o = new List<SheetData>();
            List<ViewSheet> sheets;
            try { sheets = new FilteredElementCollector(doc).OfClass(typeof(ViewSheet)).Cast<ViewSheet>().ToList(); } catch (Exception) { sheets = new List<ViewSheet>(); }
            foreach (ViewSheet sh in sheets)
            {
                try { if (sh.IsTemplate || sh.IsPlaceholder) continue; } catch (Exception) { continue; }
                var views = new List<long>();
                int placed = 0;
                try
                {
                    foreach (ElementId vid in sh.GetAllPlacedViews())
                    {
                        placed++;
                        long v = EidValue(vid);
                        if (want.Contains(v)) views.Add(v);
                    }
                }
                catch (Exception) { }
                o.Add(new SheetData { Uid = sh.UniqueId, Eid = sh.Id, Number = sh.SheetNumber ?? "", Name = ElemName(sh), Views = views, Placed = placed });
            }
            return o;
        }

        /// <summary>The views to tag: anything no longer a view is dropped, a dependent view becomes its parent (once each).</summary>
        public static List<View> PrimaryViews(Document doc, IEnumerable<ElementId> viewIds)
        {
            var o = new List<View>();
            var seen = new HashSet<long>();
            foreach (ElementId vid in viewIds)
            {
                View v = doc.GetElement(vid) as View;
                if (v == null) continue;
                try
                {
                    ElementId pid = v.GetPrimaryViewId();
                    if (pid != null && EidValue(pid) > 0)
                    {
                        View parent = doc.GetElement(pid) as View;
                        if (parent != null) v = parent;
                    }
                }
                catch (Exception) { }
                long k = EidValue(v.Id);
                if (seen.Add(k)) o.Add(v);
            }
            return o;
        }

        // ---------------------------------------------------- which views show the elements

        public class VisibilityProbe
        {
            public HashSet<long> Want = new HashSet<long>();
            public List<BuiltInCategory> Cats = new List<BuiltInCategory>();
            public double[] Lo, Hi;
        }

        /// <summary>Worked out once for many views: the wanted ids, their categories and their combined bounding box.</summary>
        public static VisibilityProbe MakeVisibilityProbe(Document doc, List<ElementId> eids)
        {
            var p = new VisibilityProbe();
            foreach (ElementId i in eids) p.Want.Add(EidValue(i));
            var ints = new HashSet<long>();
            foreach (ElementId i in eids)
            {
                Element e = doc.GetElement(i);
                if (e == null) continue;
                long? c = CatInt(e);
                if (c != null) ints.Add(c.Value);
                BoundingBoxXYZ bb = null;
                try { bb = e.get_BoundingBox(null); } catch (Exception) { }
                if (bb != null)
                {
                    double[] mn = { bb.Min.X, bb.Min.Y, bb.Min.Z };
                    double[] mx = { bb.Max.X, bb.Max.Y, bb.Max.Z };
                    p.Lo = p.Lo == null ? mn : new[] { Math.Min(p.Lo[0], mn[0]), Math.Min(p.Lo[1], mn[1]), Math.Min(p.Lo[2], mn[2]) };
                    p.Hi = p.Hi == null ? mx : new[] { Math.Max(p.Hi[0], mx[0]), Math.Max(p.Hi[1], mx[1]), Math.Max(p.Hi[2], mx[2]) };
                }
            }
            foreach (string name in KnownCats())
            {
                long? bi = BicInt(name);
                if (bi != null && ints.Contains(bi.Value)) p.Cats.Add(Bic(name).Value);
            }
            return p;
        }

        public class CropInfo
        {
            public Transform Inverse;
            public XYZ Min, Max;
            public bool UseZ;
        }

        /// <summary>The crop region or 3D section box when one is on, else null.</summary>
        public static CropInfo Crop(View view)
        {
            try
            {
                View3D v3 = view as View3D;
                if (v3 != null && v3.IsSectionBoxActive)
                {
                    BoundingBoxXYZ box = v3.GetSectionBox();
                    return new CropInfo { Inverse = box.Transform.Inverse, Min = box.Min, Max = box.Max, UseZ = true };
                }
                if (view.CropBoxActive)
                {
                    BoundingBoxXYZ box = view.CropBox;
                    return new CropInfo { Inverse = box.Transform.Inverse, Min = box.Min, Max = box.Max, UseZ = false };
                }
            }
            catch (Exception) { }
            return null;
        }

        private static bool BoxMeetsCrop(double[] lo, double[] hi, CropInfo crop)
        {
            var corners = new List<double[]>();
            foreach (double x in new[] { lo[0], hi[0] })
                foreach (double y in new[] { lo[1], hi[1] })
                    foreach (double z in new[] { lo[2], hi[2] })
                    {
                        XYZ p = crop.Inverse.OfPoint(new XYZ(x, y, z));
                        corners.Add(new[] { p.X, p.Y, p.Z });
                    }
            return NsqCore.BoxInCrop(corners, new[] { crop.Min.X, crop.Min.Y, crop.Min.Z }, new[] { crop.Max.X, crop.Max.Y, crop.Max.Z }, crop.UseZ, 0.01);
        }

        public static bool InsideCrop(Element elem, CropInfo crop)
        {
            BoundingBoxXYZ bb = null;
            try { bb = elem.get_BoundingBox(null); } catch (Exception) { }
            if (bb == null) return true;
            return BoxMeetsCrop(new[] { bb.Min.X, bb.Min.Y, bb.Min.Z }, new[] { bb.Max.X, bb.Max.Y, bb.Max.Z }, crop);
        }

        /// <summary>Which of these elements the view shows - its own visibility settings, and inside its crop region.</summary>
        public static HashSet<long> VisibleInView(Document doc, View view, List<ElementId> eids, bool firstOnly = false, VisibilityProbe probe = null)
        {
            probe = probe ?? MakeVisibilityProbe(doc, eids);
            var found = new HashSet<long>();
            if (probe.Want.Count == 0 || probe.Cats.Count == 0) return found;
            CropInfo crop = Crop(view);
            if (crop != null && probe.Lo != null && !BoxMeetsCrop(probe.Lo, probe.Hi, crop)) return found;
            ICollection<ElementId> ids;
            try
            {
                ids = new FilteredElementCollector(doc, view.Id).WherePasses(new ElementMulticategoryFilter(probe.Cats))
                    .WhereElementIsNotElementType().ToElementIds();
            }
            catch (Exception) { return found; }
            foreach (ElementId i in ids)
            {
                long k = EidValue(i);
                if (!probe.Want.Contains(k) || found.Contains(k)) continue;
                if (crop != null && !InsideCrop(doc.GetElement(i), crop)) continue;
                found.Add(k);
                if (firstOnly) break;
            }
            return found;
        }

        /// <summary>Id values of the views that show any of the elements.</summary>
        public static HashSet<long> ViewsShowing(Document doc, IEnumerable<ElementId> viewIds, List<ElementId> eids)
        {
            VisibilityProbe probe = MakeVisibilityProbe(doc, eids);
            var o = new HashSet<long>();
            foreach (ElementId vid in viewIds)
            {
                View view = doc.GetElement(vid) as View;
                if (view == null) continue;
                if (VisibleInView(doc, view, eids, true, probe).Count > 0) o.Add(EidValue(vid));
            }
            return o;
        }

        // ============================================================ Picking and showing

        private class DuctFilter : ISelectionFilter
        {
            private readonly HashSet<long> _ints;
            public DuctFilter(HashSet<long> ints) { _ints = ints; }
            public bool AllowElement(Element elem)
            {
                try { long? c = CatInt(elem); return c != null && _ints.Contains(c.Value); } catch (Exception) { return false; }
            }
            public bool AllowReference(Reference reference, XYZ position) { return false; }
        }

        public static Element PickElement(UIDocument uidoc, HashSet<long> ints, string prompt)
        {
            try
            {
                Reference r = uidoc.Selection.PickObject(ObjectType.Element, new DuctFilter(ints), prompt);
                return r == null ? null : uidoc.Document.GetElement(r.ElementId);
            }
            catch (Exception) { return null; }
        }

        public static Element PickDuctElement(UIDocument uidoc, string prompt) { return PickElement(uidoc, WalkInts(), prompt); }

        /// <summary>Element id values picked (window or one by one, Finish to end). Null when the user pressed Escape.</summary>
        public static List<long> PickMany(UIDocument uidoc, HashSet<long> ints, string prompt)
        {
            try
            {
                IList<Reference> refs = uidoc.Selection.PickObjects(ObjectType.Element, new DuctFilter(ints), prompt);
                return (refs ?? new List<Reference>()).Select(r => EidValue(r.ElementId)).ToList();
            }
            catch (Exception) { return null; }
        }

        public static void SelectAndShow(UIDocument uidoc, IEnumerable<ElementId> ids, bool zoom = true)
        {
            var list = ids.Where(i => i != null).ToList();
            try { uidoc.Selection.SetElementIds(list); } catch (Exception) { }
            if (list.Count == 0 || !zoom) return;
            try { uidoc.ShowElements(list); } catch (Exception) { }
        }

        // ============================================================ System selector

        public static HashSet<long> KindInts(string kind, string part)
        {
            var kd = NsqCore.Kinds[kind];
            string[] names = part == "walk" ? kd.Walk : part == "through" ? kd.Through : kd.Ends;
            var s = new HashSet<long>();
            foreach (string n in names) { long? i = BicInt(n); if (i != null) s.Add(i.Value); }
            return s;
        }

        /// <summary>Elements of these categories visible in the view, no types, kept to the crop region / section box.</summary>
        public static List<Element> ElementsInView(Document doc, View view, IEnumerable<string> names, DebugLog log = null)
        {
            var o = new List<Element>();
            var seen = new HashSet<long>();
            CropInfo crop = Crop(view);
            int dropped = 0;
            foreach (string name in names)
            {
                BuiltInCategory? bic = Bic(name);
                if (bic == null) continue;
                List<Element> items;
                try { items = new FilteredElementCollector(doc, view.Id).OfCategory(bic.Value).WhereElementIsNotElementType().ToList(); }
                catch (Exception) { items = new List<Element>(); }
                foreach (Element e in items)
                {
                    long k = EidValue(e.Id);
                    if (!seen.Add(k)) continue;
                    if (crop != null && !InsideCrop(e, crop)) { dropped++; continue; }
                    o.Add(e);
                }
            }
            if (log != null)
                log.Add("view collector: " + (o.Count + dropped) + " elements, " + dropped + " outside the " +
                        (crop != null && !crop.UseZ ? "crop region" : crop != null ? "section box" : "(no crop on)") + " left out");
            return o;
        }

        /// <summary>The MEPSystem an element is on, or null (fabrication parts often).</summary>
        public static MEPSystem ElemSystem(Element elem)
        {
            try
            {
                MEPCurve mc = elem as MEPCurve;
                if (mc != null && mc.MEPSystem != null) return mc.MEPSystem;
            }
            catch (Exception) { }
            foreach (Connector c in IterConnectors(elem))
            {
                try { if (c.MEPSystem != null) return c.MEPSystem; } catch (Exception) { }
            }
            return null;
        }

        public static string FabService(Element elem)
        {
            string v = PropText(elem, "ServiceName");
            if (v.Length > 0) return v;
            return BipText(elem, BuiltInParameter.FABRICATION_SERVICE_PARAM);
        }

        public class SystemInfo { public string Name = "", Type = "", Abbr = "", Cls = ""; }

        public static SystemInfo GetSystemInfo(Document doc, MEPSystem sysel)
        {
            Element t = null;
            try { t = doc.GetElement(sysel.GetTypeId()); } catch (Exception) { }
            string abbr = "";
            foreach (Element holder in new[] { t, (Element)sysel })
                if (holder != null && abbr.Length == 0) abbr = BipText(holder, BuiltInParameter.RBS_SYSTEM_ABBREVIATION_PARAM);
            string name = ElemName(sysel);
            if (name.Length == 0) name = BipText(sysel, BuiltInParameter.RBS_SYSTEM_NAME_PARAM);
            return new SystemInfo
            {
                Name = name,
                Type = t != null ? ElemName(t) : "",
                Abbr = abbr,
                Cls = BipText(sysel, BuiltInParameter.RBS_SYSTEM_CLASSIFICATION_PARAM),
            };
        }

        private static BuiltInParameter TypeParam(string kind)
        {
            return kind == "duct" ? BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM : BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM;
        }

        /// <summary>Group the elements into systems. Accessories are walked through but never numbered or selected.</summary>
        public static NetworkData SelectorFromElems(Document doc, List<Element> elems, string kind, DebugLog log)
        {
            NetworkData data = ReadNetwork(doc, elems, log);
            ParamMap(elems, out data.Storages, out data.PerElem);
            var through = KindInts(kind, "through");
            var ends = KindInts(kind, "ends");
            var passthrough = new HashSet<long>();
            var labels = new Dictionary<long, string>();
            var info = new Dictionary<string, SystemInfo>();
            var fab = new Dictionary<long, string>();
            foreach (Element e in elems)
            {
                long k = EidValue(e.Id);
                long? ci = CatInt(e);
                if (ci != null && through.Contains(ci.Value)) passthrough.Add(k);
                if (e is FabricationPart) fab[k] = FabService(e);
                MEPSystem sysel = ElemSystem(e);
                if (sysel != null)
                {
                    string sk = "id:" + EidValue(sysel.Id);
                    if (!info.ContainsKey(sk)) info[sk] = GetSystemInfo(doc, sysel);
                    labels[k] = sk;
                    continue;
                }
                string nm = BipText(e, BuiltInParameter.RBS_SYSTEM_NAME_PARAM);
                if (nm.Length > 0)
                {
                    string sk = "name:" + nm;
                    if (!info.ContainsKey(sk))
                    {
                        string ty = BipText(e, TypeParam(kind));
                        if (ty.Length == 0) { string f; ty = fab.TryGetValue(k, out f) ? f : ""; }
                        info[sk] = new SystemInfo { Name = nm, Type = ty };
                    }
                    labels[k] = sk;
                }
                else labels[k] = null;
            }
            Dictionary<long, string> assign = NsqCore.AssignSystems(data.Nodes, labels);
            var groups = new Dictionary<string, List<long>>();
            var groupOrder = new List<string>();
            foreach (long k in assign.Keys.OrderBy(x => x))
            {
                if (!groups.ContainsKey(assign[k])) { groups[assign[k]] = new List<long>(); groupOrder.Add(assign[k]); }
                groups[assign[k]].Add(k);
            }
            var extras = new Dictionary<string, Dictionary<long, ElementId>>();
            foreach (Element e in elems)
            {
                long k = EidValue(e.Id);
                foreach (Connector c in IterConnectors(e))
                    foreach (Connector r in ConnRefs(c))
                    {
                        Element o = null;
                        try { o = r.Owner; } catch (Exception) { continue; }
                        long? oc = o != null ? CatInt(o) : null;
                        if (o != null && oc != null && ends.Contains(oc.Value))
                        {
                            string ak;
                            if (!assign.TryGetValue(k, out ak)) ak = "";
                            if (!extras.ContainsKey(ak)) extras[ak] = new Dictionary<long, ElementId>();
                            extras[ak][EidValue(o.Id)] = o.Id;
                        }
                    }
            }
            var systems = new List<SysDef>();
            foreach (string sk in groupOrder)
            {
                List<long> keys = groups[sk];
                var num = keys.Where(k => !passthrough.Contains(k)).ToList();
                if (num.Count == 0) continue;
                SystemInfo inf;
                if (!info.TryGetValue(sk, out inf))
                {
                    string svc = "";
                    foreach (long k in keys) { string f; if (fab.TryGetValue(k, out f) && !string.IsNullOrEmpty(f)) { svc = f; break; } }
                    inf = new SystemInfo { Name = svc.Length > 0 ? "No system - " + svc : "No system", Type = svc };
                }
                var sd = new SysDef
                {
                    Key = sk, Name = inf.Name.Length > 0 ? inf.Name : sk, Type = inf.Type, Abbr = inf.Abbr, Cls = inf.Cls,
                    Keys = keys, Num = num, On = true,
                };
                Dictionary<long, ElementId> ex;
                if (extras.TryGetValue(sk, out ex)) sd.Extras = ex.Values.ToList();
                systems.Add(sd);
            }
            var cmp = new NsqCore.NaturalKeyComparer();
            systems = systems.OrderBy(sd => sd.Key.StartsWith("piece:") ? 1 : 0).ThenBy(sd => NsqCore.NaturalKey(sd.Name), cmp)
                             .ThenBy(sd => sd.Key, StringComparer.Ordinal).ToList();
            var keep = new HashSet<long>(systems.SelectMany(sd => sd.Num));
            data.Rows = data.Rows.Where(r => keep.Contains(r.ElementKey)).ToList();
            data.PassThrough = passthrough;
            data.Systems = systems;
            log.Add("selector " + kind + ": " + elems.Count + " elements, " + passthrough.Count + " accessories walked through, " + systems.Count + " systems");
            int named = labels.Values.Count(v => v != null && v.StartsWith("id:"));
            int byName = labels.Values.Count(v => v != null && v.StartsWith("name:"));
            log.Add("  labels: " + named + " on a Revit system, " + byName + " by System Name only, " + (labels.Count - named - byName) +
                    " with neither (" + fab.Count + " fabrication parts)");
            int g1, g2, g3, g4;
            NsqCore.GroupSummary(systems, out g1, out g2, out g3, out g4);
            log.Add("  rows: " + g1 + " Revit systems, " + g2 + " named only, " + g3 + " loose pieces (" + g4 + " of one part)");
            foreach (SysDef sd in systems.Take(60)) log.Add("  " + sd.Key + " | " + sd.Name + " | " + sd.Keys.Count + " elements");
            if (systems.Count > 60) log.Add("  ... " + (systems.Count - 60) + " more");
            return data;
        }

        public static NetworkData ReadSelector(Document doc, View view, string kind, DebugLog log)
        {
            var kd = NsqCore.Kinds[kind];
            List<Element> elems = ElementsInView(doc, view, kd.Walk.Concat(kd.Through), log);
            NetworkData data = SelectorFromElems(doc, elems, kind, log);
            data.ViewId = view.Id;
            data.ViewName = ElemName(view);
            data.ViewType = view.ViewType.ToString();
            return data;
        }

        /// <summary>Tags in the view that tag any of these elements.</summary>
        public static List<ElementId> TagsOn(Document doc, View view, IEnumerable<long> idValues)
        {
            var want = new HashSet<long>(idValues);
            var o = new List<ElementId>();
            List<IndependentTag> tags;
            try { tags = new FilteredElementCollector(doc, view.Id).OfClass(typeof(IndependentTag)).Cast<IndependentTag>().ToList(); }
            catch (Exception) { tags = new List<IndependentTag>(); }
            foreach (IndependentTag t in tags)
            {
                List<long> hosts;
                try { hosts = t.GetTaggedLocalElementIds().Select(EidValue).ToList(); } catch (Exception) { hosts = new List<long>(); }
                if (hosts.Any(want.Contains)) o.Add(t.Id);
            }
            return o;
        }

        private static List<ElementId> SectionBoxIds(Document doc, View view)
        {
            try
            {
                View3D v3 = view as View3D;
                if (v3 == null || !v3.IsSectionBoxActive) return new List<ElementId>();
                return view.GetDependentElements(new ElementCategoryFilter(BuiltInCategory.OST_SectionBox)).ToList();
            }
            catch (Exception) { return new List<ElementId>(); }
        }

        public static bool ResetIsolate(UIDocument uidoc, DebugLog log)
        {
            bool ok = ResetIsolateView(uidoc.Document, uidoc.Document.ActiveView.Id, log);
            try { uidoc.RefreshActiveView(); } catch (Exception) { }
            return ok;
        }

        /// <summary>Turn off temporary hide / isolate in a view, active or not.</summary>
        public static bool ResetIsolateView(Document doc, ElementId viewId, DebugLog log)
        {
            View view = doc.GetElement(viewId) as View;
            if (view == null) return false;
            WarningSwallower sw;
            Transaction t = MakeTransaction(doc, "Reset temporary isolate", out sw);
            t.Start();
            foreach (TemporaryViewMode mode in new[] { TemporaryViewMode.TemporaryHideIsolate, TemporaryViewMode.RevealHiddenElements })
            {
                try { view.DisableTemporaryViewMode(mode); } catch (Exception) { }
            }
            TransactionStatus status = t.Commit();
            log.Add("reset isolate in view " + EidValue(viewId) + ": " + status);
            return Committed(status);
        }

        /// <summary>Temporary hide elements in the active view (outside an isolate).</summary>
        public static bool HideTemporary(UIDocument uidoc, List<ElementId> ids, DebugLog log)
        {
            Document doc = uidoc.Document;
            View view = doc.ActiveView;
            WarningSwallower sw;
            Transaction t = MakeTransaction(doc, "Hide removed elements", out sw);
            t.Start();
            TransactionStatus status;
            try
            {
                view.HideElementsTemporary(ids);
                status = t.Commit();
            }
            catch (Exception) { t.RollBack(); throw; }
            log.Add("temporary hide " + ids.Count + ": " + status);
            try { uidoc.RefreshActiveView(); } catch (Exception) { }
            return Committed(status);
        }

        public static string DocKey(Document doc)
        {
            try { return (doc.PathName ?? "") + "|" + (doc.Title ?? ""); } catch (Exception) { return ""; }
        }

        /// <summary>DocKey and document for every open project that can be changed.</summary>
        public static List<KeyValuePair<string, Document>> OpenDocuments(UIApplication uiapp)
        {
            var o = new List<KeyValuePair<string, Document>>();
            List<Document> docs;
            try { docs = uiapp.Application.Documents.Cast<Document>().ToList(); } catch (Exception) { docs = new List<Document>(); }
            foreach (Document d in docs)
            {
                try { if (d.IsLinked || d.IsFamilyDocument) continue; } catch (Exception) { continue; }
                o.Add(new KeyValuePair<string, Document>(DocKey(d), d));
            }
            return o;
        }

        public static List<ElementId> SelectedIds(UIDocument uidoc)
        {
            try { return uidoc.Selection.GetElementIds().ToList(); } catch (Exception) { return new List<ElementId>(); }
        }

        /// <summary>Temporary isolate the systems plus every tag on them, in the active view or the view given.</summary>
        public static int IsolateSystems(UIDocument uidoc, List<ElementId> ids, DebugLog log, View view = null)
        {
            Document doc = uidoc.Document;
            if (view == null) view = doc.ActiveView;
            var values = ids.Select(EidValue).ToList();
            var keep = new List<ElementId>(ids);
            var tg = new TransactionGroup(doc, "RevoBIM Number Sequencer isolate");
            tg.Start();
            Transaction t = null, t2 = null;
            TransactionStatus status;
            try
            {
                WarningSwallower sw;
                t = MakeTransaction(doc, "Reset temporary isolate", out sw);
                t.Start();
                foreach (TemporaryViewMode mode in new[] { TemporaryViewMode.TemporaryHideIsolate, TemporaryViewMode.RevealHiddenElements })
                {
                    try { view.DisableTemporaryViewMode(mode); } catch (Exception) { }
                }
                t.Commit();
                // gathered after the reset: a view collector skips what an isolate hides
                keep = ids.Concat(TagsOn(doc, view, values)).Concat(SectionBoxIds(doc, view)).ToList();
                WarningSwallower sw2;
                t2 = MakeTransaction(doc, "Isolate systems", out sw2);
                t2.Start();
                view.IsolateElementsTemporary(keep);
                status = t2.Commit();
                tg.Assimilate();
            }
            catch (Exception)
            {
                RollBackQuietly(t2);
                RollBackQuietly(t);
                try { tg.RollBack(); } catch (Exception) { }
                throw;
            }
            try { uidoc.RefreshActiveView(); } catch (Exception) { }
            log.Add("isolate: " + keep.Count + " elements + tags, " + status);
            return keep.Count;
        }

        // ============================================================ Isolate in 3D

        /// <summary>Move the section box to the systems (plus a margin). Returns the box it had before when it moved, else null.</summary>
        public static BoundingBoxXYZ FitSectionBox(Document doc, View3D view, IEnumerable<ElementId> ids, DebugLog log, double margin = SectionBoxMargin)
        {
            BoundingBoxXYZ old;
            try
            {
                if (!view.IsSectionBoxActive) return null;
                old = view.GetSectionBox();
            }
            catch (Exception) { return null; }
            double[] lo = null, hi = null;
            int count = 0;
            foreach (ElementId i in ids)
            {
                BoundingBoxXYZ bb = null;
                try { bb = doc.GetElement(i).get_BoundingBox(null); } catch (Exception) { }
                if (bb == null) continue;
                count++;
                double[] a = { bb.Min.X, bb.Min.Y, bb.Min.Z };
                double[] b = { bb.Max.X, bb.Max.Y, bb.Max.Z };
                lo = lo == null ? a : new[] { Math.Min(lo[0], a[0]), Math.Min(lo[1], a[1]), Math.Min(lo[2], a[2]) };
                hi = hi == null ? b : new[] { Math.Max(hi[0], b[0]), Math.Max(hi[1], b[1]), Math.Max(hi[2], b[2]) };
            }
            if (lo == null) return null;
            var box = new BoundingBoxXYZ
            {
                Min = new XYZ(lo[0] - margin, lo[1] - margin, lo[2] - margin),
                Max = new XYZ(hi[0] + margin, hi[1] + margin, hi[2] + margin),
            };
            WarningSwallower sw;
            Transaction t = MakeTransaction(doc, "Fit section box to the systems", out sw);
            t.Start();
            TransactionStatus status;
            try
            {
                view.SetSectionBox(box);
                status = t.Commit();
            }
            catch (Exception ex)
            {
                RollBackQuietly(t);
                log.Add("section box fit failed: " + ex);
                return null;
            }
            log.Add("section box fitted to " + count + " elements: " + status);
            return Committed(status) ? old : null;
        }

        /// <summary>Put a 3D view's section box back as it was before the tool fitted it.</summary>
        public static bool RestoreSectionBox(Document doc, ElementId viewId, BoundingBoxXYZ box, DebugLog log)
        {
            View3D view = doc.GetElement(viewId) as View3D;
            if (view == null || box == null) return false;
            WarningSwallower sw;
            Transaction t = MakeTransaction(doc, "Put the section box back", out sw);
            t.Start();
            TransactionStatus status;
            try
            {
                view.SetSectionBox(box);
                status = t.Commit();
            }
            catch (Exception ex)
            {
                RollBackQuietly(t);
                log.Add("section box restore failed: " + ex);
                return false;
            }
            log.Add("section box put back: " + status);
            return Committed(status);
        }

        /// <summary>Every 3D view Isolate in 3D can use - no templates - as (UniqueId, name), sorted by name.</summary>
        public static List<KeyValuePair<string, string>> Views3d(Document doc)
        {
            var o = new List<KeyValuePair<string, string>>();
            List<View3D> items;
            try { items = new FilteredElementCollector(doc).OfClass(typeof(View3D)).Cast<View3D>().ToList(); } catch (Exception) { items = new List<View3D>(); }
            foreach (View3D v in items)
            {
                try { if (v.IsTemplate) continue; } catch (Exception) { continue; }
                o.Add(new KeyValuePair<string, string>(v.UniqueId, ElemName(v)));
            }
            return o.OrderBy(r => NsqCore.NaturalKey(r.Value), new NsqCore.NaturalKeyComparer()).ToList();
        }

        private static string UserName(Document doc)
        {
            try { return doc.Application.Username ?? ""; } catch (Exception) { return ""; }
        }

        /// <summary>The view Revit's Default 3D View button opens.</summary>
        public static View3D Default3d(Document doc)
        {
            List<string> names = NsqCore.Default3dNames(UserName(doc));
            var found = new Dictionary<string, View3D>();
            List<View3D> items;
            try { items = new FilteredElementCollector(doc).OfClass(typeof(View3D)).Cast<View3D>().ToList(); } catch (Exception) { items = new List<View3D>(); }
            foreach (View3D v in items)
            {
                try { if (v.IsTemplate) continue; } catch (Exception) { continue; }
                string n = ElemName(v);
                if (!found.ContainsKey(n)) found[n] = v;
            }
            string pick = NsqCore.PickDefault3d(found.Keys, names);
            return pick != null ? found[pick] : null;
        }

        public static View3D ViewByUid(Document doc, string uid)
        {
            if (string.IsNullOrEmpty(uid)) return null;
            try
            {
                View3D v = doc.GetElement(uid) as View3D;
                if (v == null || v.IsTemplate) return null;
                return v;
            }
            catch (Exception) { return null; }
        }

        /// <summary>No 3D view to use: make an isometric one and name it like Revit's own.</summary>
        public static View3D CreateDefault3d(Document doc, DebugLog log)
        {
            ViewFamilyType vft = null;
            foreach (ViewFamilyType t_ in new FilteredElementCollector(doc).OfClass(typeof(ViewFamilyType)).Cast<ViewFamilyType>())
            {
                try { if (t_.ViewFamily == ViewFamily.ThreeDimensional) { vft = t_; break; } } catch (Exception) { }
            }
            if (vft == null) throw new Exception("No 3D view type in this model");
            WarningSwallower sw;
            Transaction t = MakeTransaction(doc, "Create default 3D view", out sw);
            t.Start();
            View3D view;
            TransactionStatus status;
            try
            {
                view = View3D.CreateIsometric(doc, vft.Id);
                foreach (string name in NsqCore.Default3dNames(UserName(doc)))
                {
                    try { view.Name = name; break; } catch (Exception) { }
                }
                status = t.Commit();
            }
            catch (Exception) { RollBackQuietly(t); throw; }
            log.Add("created 3D view " + ElemName(view) + ": " + status);
            return view;
        }

        /// <summary>Open each view or sheet in Revit, one after another. Returns how many opened.</summary>
        public static int OpenViews(UIDocument uidoc, IEnumerable<ElementId> viewIds, DebugLog log)
        {
            Document doc = uidoc.Document;
            var list = viewIds.ToList();
            int n = 0;
            View last = null;
            foreach (ElementId vid in list)
            {
                View view = doc.GetElement(vid) as View;
                if (view == null) continue;
                last = view;
                try { uidoc.ActiveView = view; n++; }
                catch (Exception ex) { log.Add("could not open " + ElemName(view) + ": " + ex.Message); }
            }
            if (n == 0 && last != null)
            {
                try { uidoc.RequestViewChange(last); n = 1; } catch (Exception) { }
            }
            log.Add("opened " + n + " of " + list.Count + " views / sheets");
            return n;
        }

        /// <summary>Zoom the open window of a view to fit.</summary>
        public static bool ZoomView(UIDocument uidoc, ElementId viewId)
        {
            try
            {
                foreach (UIView uiv in uidoc.GetOpenUIViews())
                    if (EidValue(uiv.ViewId) == EidValue(viewId)) { uiv.ZoomToFit(); return true; }
            }
            catch (Exception) { }
            return false;
        }

        // ============================================================ Colour each system in the view

        public static ElementId SolidFillId(Document doc)
        {
            try
            {
                foreach (FillPatternElement fp in new FilteredElementCollector(doc).OfClass(typeof(FillPatternElement)).Cast<FillPatternElement>())
                {
                    try { if (fp.GetFillPattern().IsSolidFill) return fp.Id; } catch (Exception) { }
                }
            }
            catch (Exception) { }
            return null;
        }

        public static OverrideGraphicSettings ColourSettings(string hex, ElementId solidId, int? weight = null)
        {
            int r, g, b;
            NsqCore.HexRgb(hex, out r, out g, out b);
            var col = new Autodesk.Revit.DB.Color((byte)r, (byte)g, (byte)b);
            var ogs = new OverrideGraphicSettings();
            ogs.SetProjectionLineColor(col);
            ogs.SetCutLineColor(col);
            ogs.SetSurfaceForegroundPatternColor(col);
            ogs.SetCutForegroundPatternColor(col);
            if (solidId != null)
            {
                ogs.SetSurfaceForegroundPatternId(solidId);
                ogs.SetCutForegroundPatternId(solidId);
                ogs.SetSurfaceForegroundPatternVisible(true);
                ogs.SetCutForegroundPatternVisible(true);
            }
            if (weight != null && weight.Value > 0)
            {
                ogs.SetProjectionLineWeight(weight.Value);
                ogs.SetCutLineWeight(weight.Value);
            }
            // the tool's mark (1% - not visible): a colouring left behind is found by it
            ogs.SetSurfaceTransparency(NsqCore.ColourMark);
            return ogs;
        }

        private static int[] Rgb(Autodesk.Revit.DB.Color c)
        {
            try
            {
                if (c == null || !c.IsValid) return null;
                return new[] { (int)c.Red, (int)c.Green, (int)c.Blue };
            }
            catch (Exception) { return null; }
        }

        /// <summary>Overrides this tool set (see NsqCore.IsToolColouring).</summary>
        public static bool IsToolColour(OverrideGraphicSettings ogs)
        {
            try
            {
                var cols = new List<int[]>
                {
                    Rgb(ogs.ProjectionLineColor), Rgb(ogs.CutLineColor),
                    Rgb(ogs.SurfaceForegroundPatternColor), Rgb(ogs.CutForegroundPatternColor),
                };
                return NsqCore.IsToolColouring(cols, ogs.Transparency);
            }
            catch (Exception) { return false; }
        }

        /// <summary>The elements in ids that still carry the tool's colouring in this view.</summary>
        public static List<ElementId> ToolColoured(View view, IEnumerable<ElementId> ids)
        {
            var o = new List<ElementId>();
            foreach (ElementId i in ids)
            {
                try { if (IsToolColour(view.GetElementOverrides(i))) o.Add(i); } catch (Exception) { }
            }
            return o;
        }

        /// <summary>Take the tool's colouring off these elements.</summary>
        public static int ClearOverrides(Document doc, ElementId viewId, IEnumerable<ElementId> ids, DebugLog log)
        {
            View view = doc.GetElement(viewId) as View;
            var list = ids.ToList();
            if (view == null || list.Count == 0) return 0;
            WarningSwallower sw;
            Transaction t = MakeTransaction(doc, "Clear system colours", out sw);
            t.Start();
            int count = 0;
            foreach (ElementId i in list)
            {
                try
                {
                    if (IsToolColour(view.GetElementOverrides(i)))
                    {
                        view.SetElementOverrides(i, new OverrideGraphicSettings());
                        count++;
                    }
                }
                catch (Exception) { }
            }
            TransactionStatus status = t.Commit();
            log.Add("clear left-over colours: " + count + " elements, " + status);
            return Committed(status) ? count : 0;
        }

        public class ColourGroup
        {
            public string Hex;
            public List<ElementId> Ids = new List<ElementId>();
            public int? Weight;
        }

        /// <summary>Colour the groups (later groups win). snapshot records what each element looked like before the tool first touched it.</summary>
        public static int ColourSystems(Document doc, View view, List<ColourGroup> groups, Dictionary<long, KeyValuePair<ElementId, OverrideGraphicSettings>> snapshot, DebugLog log)
        {
            try
            {
                if (doc.IsWorkshared) WorksharingUtils.CheckoutElements(doc, new List<ElementId> { view.Id });
            }
            catch (Exception ex) { log.Add("view checkout failed: " + ex); }
            ElementId solid = SolidFillId(doc);
            WarningSwallower sw;
            Transaction t = MakeTransaction(doc, "Colour systems", out sw);
            t.Start();
            int count = 0;
            var firstSeen = new Dictionary<long, KeyValuePair<ElementId, OverrideGraphicSettings>>();
            foreach (ColourGroup g in groups)
            {
                OverrideGraphicSettings ogs = ColourSettings(g.Hex, solid, g.Weight);
                foreach (ElementId i in g.Ids)
                {
                    long k = EidValue(i);
                    try
                    {
                        if (!snapshot.ContainsKey(k) && !firstSeen.ContainsKey(k))
                        {
                            OverrideGraphicSettings before = view.GetElementOverrides(i);
                            if (IsToolColour(before)) before = new OverrideGraphicSettings();   // left by an earlier session
                            firstSeen[k] = new KeyValuePair<ElementId, OverrideGraphicSettings>(i, before);
                        }
                        view.SetElementOverrides(i, ogs);
                        count++;
                    }
                    catch (Exception) { }
                }
            }
            TransactionStatus status = t.Commit();
            log.Add("colour systems: " + count + " elements, " + status);
            if (!Committed(status))
                throw new Exception("Revit would not colour the view: " + (sw.Messages.Count > 0 ? string.Join("; ", sw.Messages) : "rolled back"));
            foreach (var kv in firstSeen) snapshot[kv.Key] = kv.Value;
            return count;
        }

        public static bool IsIsolated(View view)
        {
            try { return view.IsInTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate); } catch (Exception) { return false; }
        }

        /// <summary>Put back every element override recorded in the snapshot.</summary>
        public static int RestoreOverrides(Document doc, ElementId viewId, Dictionary<long, KeyValuePair<ElementId, OverrideGraphicSettings>> snapshot, DebugLog log)
        {
            if (snapshot.Count == 0) return 0;
            View view = doc.GetElement(viewId) as View;
            if (view == null) { snapshot.Clear(); return 0; }
            WarningSwallower sw;
            Transaction t = MakeTransaction(doc, "Clear system colours", out sw);
            t.Start();
            int count = 0;
            foreach (long k in snapshot.Keys.ToList())
            {
                var pair = snapshot[k];
                try { view.SetElementOverrides(pair.Key, pair.Value); count++; } catch (Exception) { }
            }
            TransactionStatus status = t.Commit();
            log.Add("clear colours: " + count + " elements, " + status);
            if (Committed(status)) snapshot.Clear();
            return count;
        }

        // ============================================================ Order by position (any category)

        /// <summary>Where an element sits: its location point, the middle of its curve, else the middle of its box.</summary>
        public static double[] ElemPoint(Element e)
        {
            try
            {
                Location loc = e.Location;
                LocationPoint lp = loc as LocationPoint;
                if (lp != null) return Xyz(lp.Point);
                LocationCurve lc = loc as LocationCurve;
                if (lc != null) return Xyz(lc.Curve.Evaluate(0.5, true));
            }
            catch (Exception) { }
            try
            {
                BoundingBoxXYZ bb = e.get_BoundingBox(null);
                if (bb != null) return Xyz((bb.Min + bb.Max) * 0.5);
            }
            catch (Exception) { }
            return null;
        }

        /// <summary>A view's right, up, viewing direction and origin (for projecting points onto it).</summary>
        public class ViewFrame
        {
            public double[] Right = { 1, 0, 0 }, Up = { 0, 1, 0 }, Dir = { 0, 0, 1 }, Origin = { 0, 0, 0 };
        }

        public static ViewFrame FrameOf(View view)
        {
            var f = new ViewFrame();
            try { f.Right = Xyz(view.RightDirection); f.Up = Xyz(view.UpDirection); f.Dir = Xyz(view.ViewDirection); f.Origin = Xyz(view.Origin); }
            catch (Exception) { }
            return f;
        }

        /// <summary>Points on the view's screen: u to the right, v up.</summary>
        public static Dictionary<long, double[]> Project(Dictionary<long, double[]> pts, IEnumerable<long> keys, ViewFrame f)
        {
            var o = new Dictionary<long, double[]>();
            foreach (long k in keys)
            {
                double[] p;
                if (!pts.TryGetValue(k, out p)) continue;
                o[k] = new[] { p[0] * f.Right[0] + p[1] * f.Right[1] + p[2] * f.Right[2], p[0] * f.Up[0] + p[1] * f.Up[1] + p[2] * f.Up[2] };
            }
            return o;
        }

        /// <summary>Can detail lines be drawn in this view?</summary>
        public static bool CanDrawLines(View view, out string why)
        {
            why = "";
            string vt = view.ViewType.ToString();
            if (vt == "ThreeD" || vt == "Schedule" || vt == "DrawingSheet" || vt == "Legend" || vt == "Internal" || vt == "ProjectBrowser" || vt == "Report" || vt == "Rendering" || vt == "Walkthrough")
            {
                why = "Detail lines cannot be drawn in this kind of view - open a plan, section or elevation (the order is shown there)";
                return false;
            }
            bool template = false;
            try { template = view.IsTemplate; } catch (Exception) { }
            if (template) { why = "The active view is a template"; return false; }
            return true;
        }

        public class OrderPreview
        {
            public ElementId ViewId;
            public string DocKey = "";
            public List<ElementId> Lines = new List<ElementId>();
            public bool Isolated;
        }

        /// <summary>Draw a detail line between each pair of elements in order, then isolate the elements and the lines temporarily.</summary>
        public static OrderPreview DrawOrder(UIDocument uidoc, List<long> order, Dictionary<long, double[]> pts, Dictionary<long, ElementId> idmap, ViewFrame f, DebugLog log)
        {
            Document doc = uidoc.Document;
            View view = doc.ActiveView;
            var prev = new OrderPreview { ViewId = view.Id, DocKey = DocKey(doc) };
            Func<double[], XYZ> onPlane = p =>
            {
                double d = (p[0] - f.Origin[0]) * f.Dir[0] + (p[1] - f.Origin[1]) * f.Dir[1] + (p[2] - f.Origin[2]) * f.Dir[2];
                return new XYZ(p[0] - d * f.Dir[0], p[1] - d * f.Dir[1], p[2] - d * f.Dir[2]);
            };
            WarningSwallower sw;
            Transaction t = MakeTransaction(doc, "Number Sequencer order preview", out sw);
            t.Start();
            try
            {
                var red = new OverrideGraphicSettings();
                var green = new OverrideGraphicSettings();
                red.SetProjectionLineColor(new Autodesk.Revit.DB.Color(230, 30, 30)); red.SetProjectionLineWeight(6);
                green.SetProjectionLineColor(new Autodesk.Revit.DB.Color(30, 190, 60)); green.SetProjectionLineWeight(6);
                double[] last = null;
                int n = 0;
                foreach (long k in order)
                {
                    double[] p;
                    if (!pts.TryGetValue(k, out p)) continue;
                    if (last != null)
                    {
                        XYZ a = onPlane(last), b = onPlane(p);
                        if (a.DistanceTo(b) > 0.01)
                        {
                            try
                            {
                                DetailCurve dc = doc.Create.NewDetailCurve(view, Line.CreateBound(a, b));
                                view.SetElementOverrides(dc.Id, n == 0 ? green : red);
                                prev.Lines.Add(dc.Id);
                                n++;
                            }
                            catch (Exception ex) { log.Add("order line failed: " + ex.Message); }
                        }
                    }
                    last = p;
                }
                t.Commit();
            }
            catch (Exception) { RollBackQuietly(t); throw; }
            var keep = order.Where(idmap.ContainsKey).Select(k => idmap[k]).Concat(prev.Lines).ToList();
            IsolateSystems(uidoc, keep, log);
            prev.Isolated = true;
            log.Add("order preview: " + prev.Lines.Count + " lines, " + order.Count + " elements");
            return prev;
        }

        /// <summary>Delete the preview lines and put the view's isolate back.</summary>
        public static void ClearOrder(UIApplication uiapp, OrderPreview prev, DebugLog log)
        {
            if (prev == null) return;
            foreach (var kv in OpenDocuments(uiapp))
            {
                if (kv.Key != prev.DocKey) continue;
                Document doc = kv.Value;
                if (prev.Isolated) { try { ResetIsolateView(doc, prev.ViewId, log); } catch (Exception ex) { log.Add("preview reset failed: " + ex.Message); } }
                var ids = prev.Lines.Where(i => doc.GetElement(i) != null).ToList();
                if (ids.Count > 0)
                {
                    WarningSwallower sw;
                    Transaction t = MakeTransaction(doc, "Remove order preview", out sw);
                    t.Start();
                    try { doc.Delete(ids); t.Commit(); }
                    catch (Exception ex) { RollBackQuietly(t); log.Add("preview delete failed: " + ex.Message); }
                }
            }
            try { uiapp.ActiveUIDocument.RefreshActiveView(); } catch (Exception) { }
        }
    }
}



