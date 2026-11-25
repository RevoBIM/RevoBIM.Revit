using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.FilterManager
{
    /// <summary>A filter rule decoded into something a window can edit (the pyRevit "rule dict").</summary>
    public class FmRule
    {
        public ElementId ParamId;
        public string Op = "equals";
        /// <summary>A string, a double/int (internal units until normalised) or an ElementId.</summary>
        public object Value = "";
        public string Storage = "String";    // String | Integer | Double | ElementId
        public ForgeTypeId Spec;
        public bool YesNo;

        public FmRule Copy()
        {
            return new FmRule { ParamId = ParamId, Op = Op, Value = Value, Storage = Storage, Spec = Spec, YesNo = YesNo };
        }
    }

    public class FmOperator
    {
        public string Key, Label, Factory;
        public bool NeedsValue;
    }

    /// <summary>
    /// Everything that touches ParameterFilterElement lives here so the window code stays about the window.
    /// Port of fm_filters.py.
    /// </summary>
    public static class FmFilters
    {
        public const double DoubleEpsilon = 0.000001;
        public const string ParkPrefix = "__RevoBIM_parked_";

        // Anything here costs a scan of the model to work out and does not change until the model does, so it is
        // worked out once and kept. ClearCaches() is called whenever the tool re-reads the document.
        private static Dictionary<long, string> _categories;
        private static readonly Dictionary<string, List<Tuple<ElementId, string>>> ParametersCache = new Dictionary<string, List<Tuple<ElementId, string>>>();
        private static readonly Dictionary<string, ParameterProbe> ProbesCache = new Dictionary<string, ParameterProbe>();
        private static readonly Dictionary<string, Dictionary<string, Tuple<ElementId, string>>> LookupsCache =
            new Dictionary<string, Dictionary<string, Tuple<ElementId, string>>>();

        public static void ClearCaches()
        {
            _categories = null;
            ParametersCache.Clear();
            ProbesCache.Clear();
            LookupsCache.Clear();
        }

        public static string CategorySignature(IEnumerable<ElementId> categoryIds)
        {
            try
            {
                return string.Join(",", (categoryIds ?? new ElementId[0]).Select(c => FmCore.EidValue(c)).OrderBy(v => v).Select(v => v.ToString()));
            }
            catch (Exception) { return ""; }
        }

        // ---------------------------------------------------------------------------
        //  Operators
        // ---------------------------------------------------------------------------
        public static readonly List<FmOperator> Operators = new List<FmOperator>
        {
            Op("equals", "equals", "CreateEqualsRule", true),
            Op("not_equals", "does not equal", "CreateNotEqualsRule", true),
            Op("greater", "is greater than", "CreateGreaterRule", true),
            Op("greater_equal", "is greater than or equal to", "CreateGreaterOrEqualRule", true),
            Op("less", "is less than", "CreateLessRule", true),
            Op("less_equal", "is less than or equal to", "CreateLessOrEqualRule", true),
            Op("contains", "contains", "CreateContainsRule", true),
            Op("not_contains", "does not contain", "CreateNotContainsRule", true),
            Op("begins", "begins with", "CreateBeginsWithRule", true),
            Op("not_begins", "does not begin with", "CreateNotBeginsWithRule", true),
            Op("ends", "ends with", "CreateEndsWithRule", true),
            Op("not_ends", "does not end with", "CreateNotEndsWithRule", true),
            Op("has_value", "has a value", "CreateHasValueParameterRule", false),
            Op("has_no_value", "has no value", "CreateHasNoValueParameterRule", false),
        };

        private static FmOperator Op(string key, string label, string factory, bool needs)
        {
            return new FmOperator { Key = key, Label = label, Factory = factory, NeedsValue = needs };
        }

        public static readonly Dictionary<string, string> OpLabel = Operators.ToDictionary(o => o.Key, o => o.Label);
        public static readonly Dictionary<string, string> OpFactory = Operators.ToDictionary(o => o.Key, o => o.Factory);
        public static readonly Dictionary<string, bool> OpNeedsValue = Operators.ToDictionary(o => o.Key, o => o.NeedsValue);
        public static readonly Dictionary<string, string> LabelToOp = Operators.ToDictionary(o => o.Label, o => o.Key);

        public static bool NeedsValue(string op)
        {
            bool needs;
            return !OpNeedsValue.TryGetValue(op ?? "", out needs) || needs;
        }

        public static string LabelOf(string op)
        {
            string label;
            return OpLabel.TryGetValue(op ?? "", out label) ? label : "";
        }

        public static readonly string[] StringOps =
        {
            "equals", "not_equals", "contains", "not_contains", "begins", "not_begins", "ends", "not_ends",
            "greater", "greater_equal", "less", "less_equal", "has_value", "has_no_value",
        };

        public static readonly string[] NumericOps =
        {
            "equals", "not_equals", "greater", "greater_equal", "less", "less_equal", "has_value", "has_no_value",
        };

        // Revit offers the text operators on an element id parameter as well, because it matches against the
        // name of the element the parameter points at - which is why "System Type contains" is an ordinary rule.
        public static readonly string[] IdTextOps = { "contains", "not_contains", "begins", "not_begins", "ends", "not_ends" };

        public static readonly string[] IdOps =
            new[] { "equals", "not_equals" }.Concat(IdTextOps).Concat(new[] { "has_value", "has_no_value" }).ToArray();

        public static readonly string[] YesNoOps = { "equals", "not_equals", "has_value", "has_no_value" };

        public static string[] OpsForStorage(string storage, bool isYesNo = false)
        {
            if (isYesNo) return YesNoOps;
            if (storage == "String") return StringOps;
            if (storage == "ElementId") return IdOps;
            return NumericOps;
        }

        // ---------------------------------------------------------------------------
        //  Filters in the project
        // ---------------------------------------------------------------------------
        public static List<ParameterFilterElement> GetAllFilters(Document doc)
        {
            var list = new List<ParameterFilterElement>();
            try
            {
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(ParameterFilterElement)).ToElements())
                    list.Add((ParameterFilterElement)e);
            }
            catch (Exception) { }
            try { list.Sort((a, b) => string.Compare(a.Name ?? "", b.Name ?? "", StringComparison.OrdinalIgnoreCase)); }
            catch (Exception) { }
            return list;
        }

        /// <summary>{filter id value: number of views/templates using it}.</summary>
        public static Dictionary<long, int> FilterUsage(Document doc)
        {
            var used = new Dictionary<long, int>();
            try
            {
                foreach (Element element in new FilteredElementCollector(doc).OfClass(typeof(View)))
                {
                    try
                    {
                        var v = (View)element;
                        if (!SupportsFilters(v)) continue;
                        foreach (ElementId fid in v.GetFilters())
                        {
                            long k = FmCore.EidValue(fid);
                            int n;
                            used.TryGetValue(k, out n);
                            used[k] = n + 1;
                        }
                    }
                    catch (Exception) { }
                }
            }
            catch (Exception) { }
            return used;
        }

        public static List<ElementId> FilterCategoryIds(ParameterFilterElement pfe)
        {
            try { return pfe.GetCategories().ToList(); }
            catch (Exception) { return new List<ElementId>(); }
        }

        // ---------------------------------------------------------------------------
        //  Categories
        // ---------------------------------------------------------------------------
        /// <summary>{id value: name} read once out of the document's own category table.</summary>
        public static Dictionary<long, string> CategoryMap(Document doc)
        {
            if (_categories != null) return _categories;
            var map = new Dictionary<long, string>();
            try
            {
                foreach (Category cat in doc.Settings.Categories)
                {
                    try { map[FmCore.EidValue(cat.Id)] = cat.Name; }
                    catch (Exception) { }
                }
            }
            catch (Exception) { }
            _categories = map;
            return map;
        }

        /// <summary>Every category a filter may be built on, sorted by name.</summary>
        public static List<Tuple<ElementId, string>> FilterableCategories(Document doc)
        {
            var result = new List<Tuple<ElementId, string>>();
            Dictionary<long, string> known = CategoryMap(doc);
            ICollection<ElementId> ids;
            try { ids = ParameterFilterUtilities.GetAllFilterableCategories(); }
            catch (Exception) { return result; }

            foreach (ElementId cid in ids)
            {
                string name;
                if (!known.TryGetValue(FmCore.EidValue(cid), out name) || string.IsNullOrEmpty(name))
                    name = BuiltinCategoryName(cid);
                if (!string.IsNullOrEmpty(name)) result.Add(Tuple.Create(cid, name));
            }
            result.Sort((a, b) => string.Compare(a.Item2, b.Item2, StringComparison.OrdinalIgnoreCase));
            return result;
        }

        public static string BuiltinCategoryName(ElementId cid)
        {
            try { return LabelUtils.GetLabelFor((BuiltInCategory)(int)FmCore.EidValue(cid)); }
            catch (Exception) { return null; }
        }

        public static string CategoryName(Document doc, ElementId cid)
        {
            string name;
            if (CategoryMap(doc).TryGetValue(FmCore.EidValue(cid), out name) && !string.IsNullOrEmpty(name)) return name;
            return BuiltinCategoryName(cid);
        }

        // ---------------------------------------------------------------------------
        //  Parameters
        // ---------------------------------------------------------------------------
        /// <summary>(ElementId, name) filterable on every one of these categories.</summary>
        public static List<Tuple<ElementId, string>> CommonParameters(Document doc, IEnumerable<ElementId> categoryIds)
        {
            var result = new List<Tuple<ElementId, string>>();
            List<ElementId> cats = (categoryIds ?? new ElementId[0]).ToList();
            if (cats.Count == 0) return result;

            string signature = CategorySignature(cats);
            List<Tuple<ElementId, string>> cached;
            if (ParametersCache.TryGetValue(signature, out cached)) return cached;
            try
            {
                foreach (ElementId pid in ParameterFilterUtilities.GetFilterableParametersInCommon(doc, cats))
                {
                    string nm = ParameterName(doc, pid);
                    if (!string.IsNullOrEmpty(nm)) result.Add(Tuple.Create(pid, nm));
                }
            }
            catch (Exception) { }
            result.Sort((a, b) => string.Compare(a.Item2, b.Item2, StringComparison.OrdinalIgnoreCase));
            ParametersCache[signature] = result;
            return result;
        }

        /// <summary>A ParameterProbe per set of categories, not per filter: sampling elements is the most expensive thing the tool does.</summary>
        public static ParameterProbe ProbeFor(Document doc, IEnumerable<ElementId> categoryIds)
        {
            List<ElementId> cats = (categoryIds ?? new ElementId[0]).ToList();
            string signature = CategorySignature(cats);
            ParameterProbe probe;
            if (!ProbesCache.TryGetValue(signature, out probe))
            {
                probe = new ParameterProbe(doc, cats);
                ProbesCache[signature] = probe;
            }
            return probe;
        }

        /// <summary>
        /// {lower name: (ElementId, scope)} for anything a rule could point at. Scope is "common" (every category has
        /// it - what Revit's own dialog offers), "partial" (at least one has it) or "project" (a parameter of that
        /// name exists in the project).
        /// </summary>
        public static Dictionary<string, Tuple<ElementId, string>> ParameterLookup(Document doc, IEnumerable<ElementId> categoryIds)
        {
            List<ElementId> cats = (categoryIds ?? new ElementId[0]).ToList();
            string signature = CategorySignature(cats);
            Dictionary<string, Tuple<ElementId, string>> cached;
            if (LookupsCache.TryGetValue(signature, out cached)) return cached;

            var result = new Dictionary<string, Tuple<ElementId, string>>();
            foreach (var p in CommonParameters(doc, cats))
                result[p.Item2.ToLowerInvariant()] = Tuple.Create(p.Item1, "common");

            foreach (ElementId cid in cats)
            {
                try
                {
                    foreach (var p in CommonParameters(doc, new[] { cid }))
                        if (!result.ContainsKey(p.Item2.ToLowerInvariant()))
                            result[p.Item2.ToLowerInvariant()] = Tuple.Create(p.Item1, "partial");
                }
                catch (Exception) { }
            }

            try
            {
                foreach (Element element in new FilteredElementCollector(doc).OfClass(typeof(ParameterElement)).ToElements())
                {
                    string name;
                    try { name = element.Name; }
                    catch (Exception) { continue; }
                    if (!string.IsNullOrEmpty(name) && !result.ContainsKey(name.ToLowerInvariant()))
                        result[name.ToLowerInvariant()] = Tuple.Create(element.Id, "project");
                }
            }
            catch (Exception) { }

            LookupsCache[signature] = result;
            return result;
        }

        public static string ParameterName(Document doc, ElementId pid)
        {
            long val = FmCore.EidValue(pid);
            if (val < 0)
            {
                try { return LabelUtils.GetLabelFor((BuiltInParameter)(int)val); }
                catch (Exception) { }
            }
            try
            {
                Element el = doc.GetElement(pid);
                if (el != null) return el.Name;
            }
            catch (Exception) { }
            return "Parameter " + val;
        }

        // ---------------------------------------------------------------------------
        //  Units - filter values for Double parameters are stored in internal units
        // ---------------------------------------------------------------------------
        public static ForgeTypeId UnitIdFor(Document doc, ForgeTypeId spec)
        {
            if (spec == null) return null;
            try { if (!UnitUtils.IsMeasurableSpec(spec)) return null; }
            catch (Exception) { }
            try { return doc.GetUnits().GetFormatOptions(spec).GetUnitTypeId(); }
            catch (Exception) { return null; }
        }

        public static string UnitLabel(Document doc, ForgeTypeId spec)
        {
            ForgeTypeId uid = UnitIdFor(doc, spec);
            if (uid == null) return "";
            try { return LabelUtils.GetLabelForUnit(uid); }
            catch (Exception) { return ""; }
        }

        public static double ToDisplay(Document doc, double value, ForgeTypeId spec)
        {
            ForgeTypeId uid = UnitIdFor(doc, spec);
            if (uid == null) return value;
            try { return UnitUtils.ConvertFromInternalUnits(value, uid); }
            catch (Exception) { return value; }
        }

        public static double ToInternal(Document doc, double value, ForgeTypeId spec)
        {
            ForgeTypeId uid = UnitIdFor(doc, spec);
            if (uid == null) return value;
            try { return UnitUtils.ConvertToInternalUnits(value, uid); }
            catch (Exception) { return value; }
        }

        // ---------------------------------------------------------------------------
        //  Reading rules off a filter
        // ---------------------------------------------------------------------------
        /// <summary>Match mode ("AND" or "OR") and the decoded rules.</summary>
        public static Tuple<string, List<FmRule>> ReadFilter(Document doc, ParameterFilterElement pfe)
        {
            ElementFilter ef = null;
            try { ef = pfe.GetElementFilter(); }
            catch (Exception) { ef = null; }

            string match = "AND";
            var collected = new List<FilterRule>();
            if (ef != null)
            {
                if (ef is LogicalOrFilter) match = "OR";
                WalkFilter(ef, collected);
            }

            var rules = new List<FmRule>();
            foreach (FilterRule r in collected)
            {
                FmRule info = DecodeRule(doc, r);
                if (info != null) rules.Add(info);
            }
            return Tuple.Create(match, rules);
        }

        private static void WalkFilter(ElementFilter ef, List<FilterRule> output)
        {
            try
            {
                var epf = ef as ElementParameterFilter;
                if (epf != null)
                {
                    output.AddRange(epf.GetRules());
                    return;
                }
                var and = ef as LogicalAndFilter;
                if (and != null)
                {
                    foreach (ElementFilter sub in and.GetFilters()) WalkFilter(sub, output);
                    return;
                }
                var or = ef as LogicalOrFilter;
                if (or != null)
                {
                    foreach (ElementFilter sub in or.GetFilters()) WalkFilter(sub, output);
                }
            }
            catch (Exception) { }
        }

        private static readonly string[][] EvalMap =
        {
            new[] { "GreaterOrEqual", "greater_equal" },
            new[] { "LessOrEqual", "less_equal" },
            new[] { "BeginsWith", "begins" },
            new[] { "EndsWith", "ends" },
            new[] { "Contains", "contains" },
            new[] { "Greater", "greater" },
            new[] { "Less", "less" },
            new[] { "Equals", "equals" },
        };

        private static readonly Dictionary<string, string> Negate = new Dictionary<string, string>
        {
            { "equals", "not_equals" }, { "contains", "not_contains" }, { "begins", "not_begins" }, { "ends", "not_ends" },
            { "greater", "less_equal" }, { "greater_equal", "less" }, { "less", "greater_equal" }, { "less_equal", "greater" },
        };

        /// <summary>Turn a FilterRule into a plain object the window can edit.</summary>
        public static FmRule DecodeRule(Document doc, FilterRule rule)
        {
            bool inverted = false;
            FilterRule inner = rule;
            try
            {
                var inverse = rule as FilterInverseRule;
                if (inverse != null)
                {
                    inverted = true;
                    inner = inverse.GetInnerRule();
                }
            }
            catch (Exception) { }

            string cls = inner == null ? "" : inner.GetType().Name;
            ElementId pid = null;
            try { pid = inner.GetRuleParameter(); }
            catch (Exception) { pid = null; }
            if (pid == null) return null;

            if (cls.Contains("HasNoValue"))
                return Make(pid, inverted ? "has_value" : "has_no_value", "", "String");
            if (cls.Contains("HasValue"))
                return Make(pid, inverted ? "has_no_value" : "has_value", "", "String");

            string op = "equals";
            try
            {
                MethodInfo getEvaluator = inner.GetType().GetMethod("GetEvaluator", Type.EmptyTypes);
                object evaluator = getEvaluator == null ? null : getEvaluator.Invoke(inner, null);
                string ev = evaluator == null ? "" : evaluator.GetType().Name;
                foreach (string[] pair in EvalMap)
                {
                    if (ev.Contains(pair[0])) { op = pair[1]; break; }
                }
            }
            catch (Exception) { }

            if (inverted)
            {
                string negated;
                if (Negate.TryGetValue(op, out negated)) op = negated;
            }

            object value = "";
            string storage = "String";
            try
            {
                var s = inner as FilterStringRule;
                var d = inner as FilterDoubleRule;
                var i = inner as FilterIntegerRule;
                var e = inner as FilterElementIdRule;
                if (s != null) { storage = "String"; value = s.RuleString ?? ""; }
                else if (d != null) { storage = "Double"; value = d.RuleValue; }
                else if (i != null) { storage = "Integer"; value = i.RuleValue; }
                else if (e != null) { storage = "ElementId"; value = e.RuleValue; }
                else if (cls.Contains("GlobalParameterAssociation")) { storage = "String"; value = ""; }
                else
                {
                    storage = "String";
                    value = StringValue(inner);
                }
            }
            catch (Exception) { }

            return Make(pid, op, value, storage);
        }

        private static string StringValue(FilterRule rule)
        {
            foreach (string attr in new[] { "RuleString", "RuleValue" })
            {
                try
                {
                    PropertyInfo p = rule.GetType().GetProperty(attr);
                    if (p == null) continue;
                    object v = p.GetValue(rule, null);
                    if (v != null) return v.ToString();
                }
                catch (Exception) { }
            }
            return "";
        }

        private static FmRule Make(ElementId pid, string op, object value, string storage)
        {
            return new FmRule { ParamId = pid, Op = op, Value = value, Storage = storage, Spec = null };
        }

        // ---------------------------------------------------------------------------
        //  Building rules
        // ---------------------------------------------------------------------------
        private static object CallFactory(string method, params object[] args)
        {
            Type[] types = args.Select(a => a.GetType()).ToArray();
            foreach (MethodInfo m in typeof(ParameterFilterRuleFactory).GetMethods(BindingFlags.Public | BindingFlags.Static))
            {
                if (m.Name != method) continue;
                ParameterInfo[] ps = m.GetParameters();
                if (ps.Length != args.Length) continue;
                bool ok = true;
                for (int i = 0; i < ps.Length; i++)
                    if (!ps[i].ParameterType.IsAssignableFrom(types[i])) { ok = false; break; }
                if (!ok) continue;
                try { return m.Invoke(null, args); }
                catch (TargetInvocationException ex) { throw ex.InnerException ?? ex; }
            }
            return null;
        }

        /// <summary>A FilterRule, or throws with a readable message.</summary>
        public static FilterRule BuildRule(Document doc, ElementId pid, string op, object rawValue, string storage, ForgeTypeId spec, bool yesno = false)
        {
            string factory;
            if (!OpFactory.TryGetValue(op ?? "", out factory)) throw new ArgumentException("Unknown operator '" + op + "'");

            object result;
            if (!NeedsValue(op))
            {
                result = CallFactory(factory, pid);
            }
            else if (storage == "String")
            {
                string text = rawValue == null ? "" : rawValue.ToString();
                result = CallFactory(factory, pid, text);
            }
            else if (storage == "Integer")
            {
                int num;
                if (yesno)
                {
                    string t = (rawValue ?? "").ToString().Trim().ToLowerInvariant();
                    num = (t == "1" || t == "yes" || t == "true" || t == "y") ? 1 : 0;
                }
                else
                {
                    num = (int)Math.Round(double.Parse((rawValue ?? "").ToString().Trim(), System.Globalization.CultureInfo.InvariantCulture));
                }
                result = CallFactory(factory, pid, num);
            }
            else if (storage == "Double")
            {
                double display = double.Parse((rawValue ?? "").ToString().Trim().Replace(',', '.'), System.Globalization.CultureInfo.InvariantCulture);
                double internalValue = ToInternal(doc, display, spec);
                result = CallFactory(factory, pid, internalValue, DoubleEpsilon) ?? CallFactory(factory, pid, internalValue);
            }
            else if (storage == "ElementId")
            {
                if (Array.IndexOf(IdTextOps, op) >= 0)
                {
                    string text = rawValue == null ? "" : rawValue.ToString();
                    result = CallFactory(factory, pid, text);
                }
                else
                {
                    var idValue = rawValue as ElementId;
                    if (idValue != null) result = CallFactory(factory, pid, idValue);
                    else
                    {
                        long parsed;
                        if (long.TryParse((rawValue ?? "").ToString().Trim(), out parsed))
                            result = CallFactory(factory, pid, RevoBIM.Helpers.RevitCompat.Id(parsed));
                        else
                            throw new ArgumentException("'" + rawValue + "' is an element, so equals needs one of its values, not free text. Use contains for a text match.");
                    }
                }
            }
            else throw new ArgumentException("Unsupported storage type '" + storage + "'");

            var rule = result as FilterRule;
            if (rule == null) throw new ArgumentException("This Revit release has no " + factory + " for that parameter type");
            return rule;
        }

        public static ElementFilter BuildElementFilter(IList<FilterRule> rules, string matchMode)
        {
            if (rules == null || rules.Count == 0) return null;
            if (matchMode == "OR")
            {
                var subs = new List<ElementFilter>();
                foreach (FilterRule r in rules) subs.Add(new ElementParameterFilter(r));
                return new LogicalOrFilter(subs);
            }
            return new ElementParameterFilter(rules.ToList());
        }

        // ---------------------------------------------------------------------------
        //  Writing (inside a transaction)
        // ---------------------------------------------------------------------------
        /// <summary>Write name, categories and rules onto an existing filter. Returns notes.</summary>
        public static List<string> ApplyFilter(Document doc, ParameterFilterElement pfe, string name,
                                               IList<ElementId> categoryIds, IList<FilterRule> rules, string matchMode)
        {
            var notes = new List<string>();
            if (!string.IsNullOrEmpty(name))
            {
                try { if (pfe.Name != name) pfe.Name = name; }
                catch (Exception ex) { notes.Add("Name not changed: " + ex.Message); }
            }

            if (categoryIds != null && categoryIds.Count > 0)
            {
                try { pfe.SetCategories(categoryIds.ToList()); }
                catch (Exception ex) { notes.Add("Categories not changed: " + ex.Message); }
            }

            ElementFilter ef = BuildElementFilter(rules, matchMode);
            try
            {
                if (ef == null)
                {
                    pfe.SetElementFilter(new ElementParameterFilter(new List<FilterRule>()));
                    notes.Add("No rules - the filter now matches every element of its categories.");
                }
                else pfe.SetElementFilter(ef);
            }
            catch (Exception ex) { notes.Add("Rules not written: " + ex.Message); }
            return notes;
        }

        public static ParameterFilterElement CreateFilter(Document doc, string name, IEnumerable<ElementId> categoryIds,
                                                          IList<FilterRule> rules = null, string matchMode = "AND")
        {
            List<ElementId> ids = categoryIds.ToList();
            ElementFilter ef = BuildElementFilter(rules, matchMode);
            if (ef != null)
            {
                try { return ParameterFilterElement.Create(doc, name, ids, ef); }
                catch (Exception) { }
            }
            return ParameterFilterElement.Create(doc, name, ids);
        }

        /// <summary>A copy carrying the same categories and the same rules. Must be inside a transaction.</summary>
        public static ParameterFilterElement DuplicateFilter(Document doc, ParameterFilterElement pfe, string newName)
        {
            List<ElementId> ids = FilterCategoryIds(pfe);
            ElementFilter elementFilter = null;
            try { elementFilter = pfe.GetElementFilter(); }
            catch (Exception) { elementFilter = null; }

            if (elementFilter != null)
            {
                try { return ParameterFilterElement.Create(doc, newName, ids, elementFilter); }
                catch (Exception) { }
            }
            ParameterFilterElement copy = ParameterFilterElement.Create(doc, newName, ids);
            if (elementFilter != null)
            {
                try { copy.SetElementFilter(elementFilter); }
                catch (Exception) { }
            }
            return copy;
        }

        /// <summary>Rename an element and prove it took (the name is read back).</summary>
        public static bool SetElementName(Element element, string name)
        {
            try { element.Name = name; }
            catch (Exception) { }
            try { return element.Name == name; }
            catch (Exception) { return false; }
        }

        public static bool RenameFilter(Document doc, ParameterFilterElement pfe, string newName)
        {
            return SetElementName(pfe, newName);
        }

        public static void DeleteFilter(Document doc, ParameterFilterElement pfe)
        {
            doc.Delete(pfe.Id);
        }

        public static string UniqueFilterName(Document doc, string baseName)
        {
            var taken = new HashSet<string>();
            foreach (ParameterFilterElement f in GetAllFilters(doc))
            {
                try { taken.Add(f.Name.ToLowerInvariant()); }
                catch (Exception) { }
            }
            if (!taken.Contains(baseName.ToLowerInvariant())) return baseName;
            int n = 2;
            while (true)
            {
                string candidate = baseName + " " + n;
                if (!taken.Contains(candidate.ToLowerInvariant())) return candidate;
                n++;
            }
        }

        /// <summary>A display name for an element or element id, whatever it is. Element.Name raises for some classes.</summary>
        public static string ElementName(Document doc, object target, string fallback = null)
        {
            Element element = target as Element;
            try
            {
                var id = target as ElementId;
                if (id != null)
                {
                    if (FmCore.EidValue(id) <= 0) return fallback ?? "";
                    element = doc.GetElement(id);
                }
            }
            catch (Exception) { element = null; }

            if (element == null) return fallback ?? "";
            try
            {
                string name = element.Name;
                if (!string.IsNullOrEmpty(name)) return name;
            }
            catch (Exception) { }
            if (fallback != null) return fallback;
            try { return "id " + FmCore.EidValue(element.Id); }
            catch (Exception) { return "(unnamed)"; }
        }

        // ---------------------------------------------------------------------------
        //  Filter Pusher support
        // ---------------------------------------------------------------------------
        public static bool SupportsFilters(View view)
        {
            try { return view.AreGraphicsOverridesAllowed(); }
            catch (Exception) { return false; }
        }

        public static List<View> GetViewTemplates(Document doc)
        {
            var templates = new List<View>();
            foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(View)))
            {
                try
                {
                    var v = (View)e;
                    if (v.IsTemplate && SupportsFilters(v)) templates.Add(v);
                }
                catch (Exception) { }
            }
            try { templates.Sort((a, b) => string.Compare(a.Name, b.Name, StringComparison.OrdinalIgnoreCase)); }
            catch (Exception) { }
            return templates;
        }

        // ViewType names as Revit's own browser words them. Anything not listed is split out of its CamelCase name.
        private static readonly Dictionary<string, string> ViewKindLabels = new Dictionary<string, string>
        {
            { "FloorPlan", "Floor Plan" }, { "CeilingPlan", "Ceiling Plan" }, { "EngineeringPlan", "Structural Plan" },
            { "AreaPlan", "Area Plan" }, { "ThreeD", "3D View" }, { "Section", "Section" }, { "Elevation", "Elevation" },
            { "Detail", "Detail View" }, { "DraftingView", "Drafting View" }, { "Legend", "Legend" },
            { "Walkthrough", "Walkthrough" }, { "Rendering", "Rendering" },
        };

        // never push targets, even where AreGraphicsOverridesAllowed says yes
        private static readonly HashSet<string> NotTargetKinds = new HashSet<string>
        {
            "DrawingSheet", "Schedule", "PanelSchedule", "ColumnSchedule", "ProjectBrowser", "SystemBrowser", "Internal",
            "Undefined", "Report", "CostReport", "LoadsReport", "PresureLossReport", "SystemsAnalysisReport",
        };

        public static string ViewKind(View view)
        {
            string raw;
            try { raw = view.ViewType.ToString(); }
            catch (Exception) { return "Other"; }
            string label;
            if (ViewKindLabels.TryGetValue(raw, out label)) return label;
            string split = Regex.Replace(raw, "(?<=[a-z0-9])(?=[A-Z])", " ");
            return string.IsNullOrEmpty(split) ? "Other" : split;
        }

        private static long FiltersParamValue()
        {
            return FmCore.EidValue(new ElementId(BuiltInParameter.VIS_GRAPHICS_FILTERS));
        }

        /// <summary>True when this template drives V/G Filters on the views it is applied to.</summary>
        public static bool TemplateControlsFilters(View template, long? filtersParam = null)
        {
            if (template == null) return false;
            try
            {
                long target = filtersParam ?? FiltersParamValue();
                foreach (ElementId e in template.GetNonControlledTemplateParameterIds())
                    if (FmCore.EidValue(e) == target) return false;
                return true;
            }
            catch (Exception) { return false; }
        }

        /// <summary>
        /// (template name, locked) for an ordinary view. A view whose template controls V/G Filters refuses
        /// AddFilter - the filters have to go onto the template instead. Templates themselves are never locked.
        /// </summary>
        public static Tuple<string, bool> ViewFilterLock(Document doc, View view, Dictionary<long, Tuple<string, bool>> cache = null, long? filtersParam = null)
        {
            ElementId tid;
            try
            {
                if (view.IsTemplate) return Tuple.Create("", false);
                tid = view.ViewTemplateId;
            }
            catch (Exception) { return Tuple.Create("", false); }

            long tval = tid == null ? -1 : FmCore.EidValue(tid);
            if (tval <= 0) return Tuple.Create("", false);
            Tuple<string, bool> hit;
            if (cache != null && cache.TryGetValue(tval, out hit)) return hit;
            var template = doc.GetElement(tid) as View;
            var result = Tuple.Create(ElementName(doc, template, "(template)"), TemplateControlsFilters(template, filtersParam));
            if (cache != null) cache[tval] = result;
            return result;
        }

        /// <summary>How a push target is written in the prompt and the log.</summary>
        public static string TargetLabel(View view)
        {
            try
            {
                if (view.IsTemplate) return view.Name;
                return view.Name + "  (" + ViewKind(view) + ")";
            }
            catch (Exception) { return "(view)"; }
        }

        /// <summary>The name of a type, e.g. 'Mechanical Plan' for a ViewFamilyType.</summary>
        public static string TypeNameOf(Document doc, ElementId typeId)
        {
            Element element = doc.GetElement(typeId);
            if (element == null) return "";
            try
            {
                string value = element.Name;
                if (!string.IsNullOrEmpty(value)) return value;
            }
            catch (Exception) { }
            foreach (BuiltInParameter bip in new[] { BuiltInParameter.ALL_MODEL_TYPE_NAME, BuiltInParameter.SYMBOL_NAME_PARAM })
            {
                try
                {
                    Parameter param = element.get_Parameter(bip);
                    string value = param == null ? null : param.AsString();
                    if (!string.IsNullOrEmpty(value)) return value;
                }
                catch (Exception) { }
            }
            return "";
        }

        /// <summary>Every ordinary view that can take filters, as rows (Target Views list).</summary>
        public static List<FmViewRow> GetFilterableViews(Document doc)
        {
            var rows = new List<FmViewRow>();
            var typeNames = new Dictionary<long, string>();
            var locks = new Dictionary<long, Tuple<string, bool>>();
            long? filtersParam = null;
            try { filtersParam = FiltersParamValue(); }
            catch (Exception) { }

            foreach (Element element in new FilteredElementCollector(doc).OfClass(typeof(View)))
            {
                try
                {
                    var v = (View)element;
                    if (v.IsTemplate) continue;
                    if (NotTargetKinds.Contains(v.ViewType.ToString())) continue;
                    if (!SupportsFilters(v)) continue;
                    string kind = ViewKind(v);
                    string typeName = "";
                    try
                    {
                        ElementId typeId = v.GetTypeId();
                        long tval = FmCore.EidValue(typeId);
                        if (tval > 0)
                        {
                            if (!typeNames.ContainsKey(tval)) typeNames[tval] = TypeNameOf(doc, typeId);
                            typeName = typeNames[tval];
                        }
                    }
                    catch (Exception) { typeName = ""; }

                    Tuple<string, bool> lockInfo = ViewFilterLock(doc, v, locks, filtersParam);
                    rows.Add(new FmViewRow
                    {
                        Id = v.Id,
                        Idv = FmCore.EidValue(v.Id),
                        Name = ElementName(doc, v, "(view)"),
                        Kind = kind,
                        Type = string.IsNullOrEmpty(typeName) ? kind : typeName,
                        Template = lockInfo.Item1,
                        Locked = lockInfo.Item2,
                    });
                }
                catch (Exception) { }
            }
            rows.Sort((a, b) =>
            {
                int c = string.Compare(a.Kind, b.Kind, StringComparison.OrdinalIgnoreCase);
                return c != 0 ? c : string.Compare(a.Name, b.Name, StringComparison.OrdinalIgnoreCase);
            });
            return rows;
        }

        /// <summary>{template id value: how many filters it carries}, worked out once for the whole list.</summary>
        public static Dictionary<long, int> TemplateFilterCounts(Document doc, IEnumerable<View> templates)
        {
            var counts = new Dictionary<long, int>();
            foreach (View view in templates ?? new View[0])
            {
                try { counts[FmCore.EidValue(view.Id)] = view.GetFilters().Count; }
                catch (Exception) { counts[FmCore.EidValue(view.Id)] = 0; }
            }
            return counts;
        }

        public static List<Tuple<ElementId, string>> GetTemplateFilters(Document doc, View view)
        {
            var result = new List<Tuple<ElementId, string>>();
            try
            {
                foreach (ElementId fid in view.GetFilters())
                {
                    Element fel = doc.GetElement(fid);
                    if (fel == null) continue;
                    try { result.Add(Tuple.Create(fid, fel.Name)); }
                    catch (Exception) { }
                }
            }
            catch (Exception) { }
            result.Sort((a, b) => string.Compare(a.Item2, b.Item2, StringComparison.OrdinalIgnoreCase));
            return result;
        }
    }

    /// <summary>
    /// Works out a parameter's storage type and unit spec from real elements. Built-in parameters have no
    /// ParameterElement to interrogate, so the only reliable route is to find an element that carries the
    /// parameter and read it there. Sample elements are collected once per category set.
    /// </summary>
    public class ParameterProbe
    {
        private readonly Document _doc;
        private readonly Dictionary<long, Tuple<string, ForgeTypeId, bool>> _cache = new Dictionary<long, Tuple<string, ForgeTypeId, bool>>();
        private readonly List<Element> _samples = new List<Element>();

        public ParameterProbe(Document doc, IEnumerable<ElementId> categoryIds, int sampleSize = 250)
        {
            _doc = doc;
            Collect(categoryIds, sampleSize);
        }

        private void Collect(IEnumerable<ElementId> categoryIds, int sampleSize)
        {
            List<ElementId> ids = (categoryIds ?? new ElementId[0]).ToList();
            if (ids.Count == 0) return;
            try
            {
                var mcf = new ElementMulticategoryFilter(ids);
                // iterated rather than ToElements(): only the first few hundred are wanted
                foreach (FilteredElementCollector collector in new[]
                {
                    new FilteredElementCollector(_doc).WherePasses(mcf).WhereElementIsNotElementType(),
                    new FilteredElementCollector(_doc).WherePasses(mcf).WhereElementIsElementType(),
                })
                {
                    int count = 0;
                    foreach (Element e in collector)
                    {
                        _samples.Add(e);
                        count++;
                        if (count >= sampleSize) break;
                    }
                }
            }
            catch (Exception) { }
        }

        /// <summary>(storage, spec or null, is_yesno) for a parameter id.</summary>
        public Tuple<string, ForgeTypeId, bool> Find(ElementId pid)
        {
            long key = FmCore.EidValue(pid);
            Tuple<string, ForgeTypeId, bool> cached;
            if (_cache.TryGetValue(key, out cached)) return cached;

            string storage = "String";
            ForgeTypeId spec = null;
            bool yesno = false;
            bool found = false;
            foreach (Element el in _samples)
            {
                Parameter p = ParamOn(el, key);
                if (p == null) continue;
                try
                {
                    switch (p.StorageType)
                    {
                        case StorageType.String: storage = "String"; break;
                        case StorageType.Integer: storage = "Integer"; break;
                        case StorageType.Double: storage = "Double"; break;
                        case StorageType.ElementId: storage = "ElementId"; break;
                        default: continue;
                    }
                    found = true;
                }
                catch (Exception) { continue; }

                try { spec = p.Definition.GetDataType(); }
                catch (Exception) { spec = null; }

                if (storage == "Integer")
                {
                    try { if (spec != null && spec == SpecTypeId.Boolean.YesNo) yesno = true; }
                    catch (Exception) { }
                }
                break;
            }

            var result = Tuple.Create(storage, found ? spec : null, yesno);
            _cache[key] = result;
            return result;
        }

        /// <summary>(ElementId, name) of the values elements actually hold for an element-id parameter.</summary>
        public List<Tuple<ElementId, string>> IdValues(ElementId pid, int limit = 400)
        {
            var seen = new Dictionary<long, Tuple<ElementId, string>>();
            long key = FmCore.EidValue(pid);
            foreach (Element el in _samples)
            {
                Parameter p = ParamOn(el, key);
                if (p == null) continue;
                try
                {
                    if (p.StorageType != StorageType.ElementId) continue;
                    ElementId v = p.AsElementId();
                    if (v == null || FmCore.EidValue(v) <= 0) continue;
                    long k = FmCore.EidValue(v);
                    if (seen.ContainsKey(k)) continue;
                    seen[k] = Tuple.Create(v, FmFilters.ElementName(_doc, v, k.ToString()));
                }
                catch (Exception) { continue; }
                if (seen.Count >= limit) break;
            }
            var list = seen.Values.ToList();
            list.Sort((a, b) => string.Compare(a.Item2, b.Item2, StringComparison.OrdinalIgnoreCase));
            return list;
        }

        private static Parameter ParamOn(Element element, long pidValue)
        {
            try
            {
                foreach (Parameter p in element.Parameters)
                    if (FmCore.EidValue(p.Id) == pidValue) return p;
            }
            catch (Exception) { }
            return null;
        }
    }
}
