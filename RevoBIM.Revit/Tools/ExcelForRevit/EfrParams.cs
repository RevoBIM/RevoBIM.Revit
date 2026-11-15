// Excel for Revit: parameter reading and writing, worksets, combined fields, the fast parameter lookup.
// Port of efr_core.py lines 461-893.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.ExcelForRevit
{
    public static partial class Efr
    {
        // --------------------------------------------------- parameter read/write ----

        static bool SpecIs(Parameter param, ForgeTypeId spec)
        {
            try { return param.Definition.GetDataType() == spec; }
            catch (Exception) { return false; }
        }

        /// <summary>Is this a Yes/No parameter.</summary>
        public static bool IsYesNo(Parameter param)
        {
            return SpecIs(param, SpecTypeId.Boolean.YesNo);
        }

        /// <summary>Is this a plain (unitless) number parameter.</summary>
        public static bool IsPlainNumber(Parameter param)
        {
            return SpecIs(param, SpecTypeId.Number);
        }

        /// <summary>Display text for a parameter, in project display units.</summary>
        public static string ReadParam(Document doc, Parameter param)
        {
            if (param == null) return "";
            try
            {
                StorageType st = param.StorageType;
                if (st == StorageType.String)
                    return param.AsString() ?? "";
                if (st == StorageType.Integer)
                {
                    if (IsYesNo(param)) return param.AsInteger() != 0 ? "Yes" : "No";
                    string vs = param.AsValueString();
                    if (!string.IsNullOrEmpty(vs)) return vs;
                    return ToText(param.AsInteger());
                }
                if (st == StorageType.Double)
                {
                    string vs = param.AsValueString();
                    if (!string.IsNullOrEmpty(vs)) return vs;
                    return ToText(Math.Round(param.AsDouble(), 6, MidpointRounding.AwayFromZero));
                }
                if (st == StorageType.ElementId)
                {
                    string vs = param.AsValueString();
                    if (!string.IsNullOrEmpty(vs)) return vs;
                    ElementId eid = param.AsElementId();
                    if (!IsValidId(eid)) return "";
                    return ElemName(doc.GetElement(eid));
                }
            }
            catch (Exception)
            {
                return "";
            }
            return "";
        }

        // ---------------------------------------------------------------- worksets ---
        //
        // A schedule can show the Workset each element sits on.  The value behind that column is a
        // workset *id* - an integer - shown as the workset's name, so the cell edits as a name and
        // is written as an id.  Every way a value reaches a cell (typing, paste, fill, find and
        // replace, Excel import, the dropdown) passes through stage(), which only accepts the name
        // of a workset that exists; Apply turns that name back into its id.

        /// <summary>The parameter id of an element's Workset (BuiltInParameter.ELEM_PARTITION_PARAM) as a long,
        /// to compare with <see cref="EidValue"/> of a field's parameter id.</summary>
        public static long? PartitionParamId()
        {
            try { return (long)(int)BuiltInParameter.ELEM_PARTITION_PARAM; }
            catch (Exception) { return null; }
        }

        /// <summary>A WorksetId as an integer (null if it cannot be read).</summary>
        public static int? WsidValue(WorksetId workset)
        {
            try { return workset.IntegerValue; }
            catch (Exception) { return null; }
        }

        /// <summary>[(name, id)] for every user workset, in natural name order.  Empty for a model that
        /// is not workshared, which is what makes the column read only.</summary>
        public static List<(string Name, int Id)> ReadWorksets(Document doc)
        {
            var found = new List<(string Name, int Id)>();
            try
            {
                if (!doc.IsWorkshared) return found;
                foreach (Workset ws in new FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
                {
                    int? value = WsidValue(ws.Id);
                    if (value != null) found.Add((ToText(ws.Name), value.Value));
                }
            }
            catch (Exception)
            {
                return new List<(string Name, int Id)>();
            }
            // OrderBy is stable, like Python's sort
            return found.OrderBy(pair => NaturalKey(pair.Name)).ToList();
        }

        /// <summary>The workset a typed or pasted name means, as (name, id), or null.
        /// Matching ignores case and runs of spaces, so "level 2  - mechanical" finds "Level 2 - Mechanical";
        /// the workset's own spelling is what is staged.  Anything that matches no workset is refused
        /// rather than guessed.</summary>
        public static (string Name, int Id)? WorksetNamed(IList<(string Name, int Id)> worksets, string text)
        {
            string want = Squash(ToText(text)).ToLowerInvariant();
            if (want.Length == 0) return null;
            if (worksets == null) return null;
            foreach (var ws in worksets)
                if (Squash(ws.Name).ToLowerInvariant() == want) return ws;
            return null;
        }

        /// <summary>Python ' '.join(text.split()): trim and collapse every run of whitespace to one space.</summary>
        static string Squash(string text)
        {
            return string.Join(" ", (text ?? "").Split((char[])null, StringSplitOptions.RemoveEmptyEntries));
        }

        /// <summary>Fill that copies and never counts - for workset names.
        /// "Level 2 - Mechanical" has a number in it, and the ordinary fill would step it to
        /// "Level 3 - Mechanical", which is not a workset.  The seeds are swapped for digit-free tokens,
        /// passed through the ordinary fill so a block of several still repeats exactly as it does in any
        /// other column, and swapped back. Uses <c>Efr.FillPlan(seeds, count, downward)</c>.</summary>
        public static List<string> FillCopyOnly(IList<string> seeds, int count, bool downward)
        {
            var result = new List<string>();
            if (seeds == null || seeds.Count == 0 || count <= 0) return result;
            var tokens = new List<string>();
            const string letters = "abcdefghijklmnopqrstuvwxyz";
            for (int i = 0; i < seeds.Count; i++)
            {
                string token = "";
                int n = i;
                while (true)
                {
                    token = letters[n % 26] + token;
                    n = n / 26;
                    if (n == 0) break;
                }
                tokens.Add("ws" + token);
            }
            var back = new Dictionary<string, string>();
            for (int i = 0; i < tokens.Count; i++) back[tokens[i]] = seeds[i];
            foreach (string v in FillPlan(tokens, count, downward))
            {
                string s;
                result.Add(back.TryGetValue(v, out s) ? s : seeds[0]);
            }
            return result;
        }

        /// <summary>Move an element to the workset a staged name names. Returns (ok, message).</summary>
        public static (bool Ok, string Message) WriteWorkset(Parameter param, string text, IList<(string Name, int Id)> worksets)
        {
            if (param == null) return (false, "parameter not found on the element");
            var found = WorksetNamed(worksets, text);
            if (found == null) return (false, "no workset called \"" + ToText(text) + "\" in this model");
            try
            {
                if (param.Set(found.Value.Id)) return (true, "");
            }
            catch (Exception ex)
            {
                return (false, ToText(ex));
            }
            return (false, "Revit would not move it — it may be borrowed by someone else, or sit in a group");
        }

        /// <summary>Write display text back. Returns (ok, message).</summary>
        public static (bool Ok, string Message) WriteParam(Parameter param, string text)
        {
            if (param == null) return (false, "parameter not found");
            try
            {
                if (param.IsReadOnly) return (false, "parameter is read only");
            }
            catch (Exception) { }
            text = ToText(text);
            try
            {
                StorageType st = param.StorageType;
                if (st == StorageType.String)
                    return (param.Set(text), "");
                if (st == StorageType.Integer)
                {
                    string low = text.Trim().ToLowerInvariant();
                    if (IsYesNo(param))
                    {
                        if (low == "yes" || low == "y" || low == "true" || low == "1" || low == "on")
                            return (param.Set(1), "");
                        if (low == "no" || low == "n" || low == "false" || low == "0" || low == "off" || low == "")
                            return (param.Set(0), "");
                        return (false, "expected Yes or No");
                    }
                    if (low == "") return (false, "cannot clear a numeric parameter");
                    try
                    {
                        double d;
                        if (!double.TryParse(low, NumberStyles.Float, CultureInfo.InvariantCulture, out d)
                            || double.IsNaN(d) || double.IsInfinity(d))
                            throw new FormatException();
                        return (param.Set(checked((int)Math.Round(d, MidpointRounding.AwayFromZero))), "");
                    }
                    catch (Exception)
                    {
                        if (param.SetValueString(text)) return (true, "");
                        return (false, "not a whole number");
                    }
                }
                if (st == StorageType.Double)
                {
                    if (text.Trim() == "") return (false, "cannot clear a numeric parameter");
                    bool ok = false;
                    try { ok = param.SetValueString(text); }
                    catch (Exception) { ok = false; }
                    if (ok) return (true, "");
                    if (IsPlainNumber(param))
                    {
                        try
                        {
                            double d;
                            if (!double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out d))
                                return (false, "not a number");
                            return (param.Set(d), "");
                        }
                        catch (Exception)
                        {
                            return (false, "not a number");
                        }
                    }
                    return (false, "not a valid value for these units");
                }
                if (st == StorageType.ElementId)
                    return (false, "element-valued parameters are read only in v1.0.0");
            }
            catch (Exception ex)
            {
                return (false, ToText(ex));
            }
            return (false, "unsupported parameter type");
        }

        // ------------------------------------------------------ combined parameters --
        //
        // A "Combine Parameters" schedule field has no ParameterId of its own: it is a list of
        // parts, each a parameter with a prefix, a suffix and the separator that follows it.  The
        // tool used to see the invalid id, call the field read only, and never read it at all - so
        // the column came out blank.

        /// <summary>[(param_id, prefix, suffix, separator)] for a combined field, else null.</summary>
        public static List<(ElementId ParamId, string Prefix, string Suffix, string Separator)> CombinedParts(ScheduleField field)
        {
            try
            {
                if (!field.IsCombinedParameterField) return null;
            }
            catch (Exception)
            {
                return null;
            }
            var parts = new List<(ElementId ParamId, string Prefix, string Suffix, string Separator)>();
            try
            {
                foreach (TableCellCombinedParameterData data in field.GetCombinedParameters())
                    parts.Add((data.ParamId, ToText(data.Prefix ?? ""), ToText(data.Suffix ?? ""), ToText(data.Separator ?? "")));
            }
            catch (Exception)
            {
                return null;
            }
            return parts.Count > 0 ? parts : null;
        }

        /// <summary>Build the text the way Revit's schedule shows it.
        /// pieces: [(prefix, value, suffix, separator)] in field order. Every part contributes
        /// prefix + value + suffix, and each part's separator goes between it and the next one -
        /// never after the last. Revit does not drop the prefix, suffix or separator of a part whose
        /// value is empty, so neither does this: the aim is to show exactly what the schedule shows.</summary>
        public static string JoinCombined(IList<(string Prefix, string Value, string Suffix, string Separator)> pieces)
        {
            var sb = new System.Text.StringBuilder();
            int last = pieces.Count - 1;
            for (int i = 0; i < pieces.Count; i++)
            {
                var piece = pieces[i];
                sb.Append(piece.Prefix).Append(piece.Value).Append(piece.Suffix);
                if (i < last) sb.Append(piece.Separator);
            }
            return sb.ToString();
        }

        /// <summary>The combined text for one element, from its own and its type's parameter sources
        /// (a <see cref="ParamView"/> or a plain Dictionary&lt;long, Parameter&gt; from <see cref="ParamMap"/>;
        /// null means "no parameters").</summary>
        public static string CombinedValue(Document doc,
            IList<(ElementId ParamId, string Prefix, string Suffix, string Separator)> parts,
            ParamSource imap, ParamSource tmap)
        {
            var pieces = new List<(string Prefix, string Value, string Suffix, string Separator)>();
            foreach (var part in parts)
            {
                long key = EidValue(part.ParamId);
                Parameter param = imap != null ? imap.Get(key) : null;
                if (param == null && tmap != null) param = tmap.Get(key);
                string value = param != null ? ReadParam(doc, param) : "";
                pieces.Add((part.Prefix, value, part.Suffix, part.Separator));
            }
            return JoinCombined(pieces);
        }

        // ------------------------------------------------------- parameter lookup ----
        //
        // Reading a schedule used to list every parameter on every element - a hundred to three
        // hundred on a typical MEP family, two calls into .NET each - to use the ten or twenty the
        // schedule actually shows.  On a few thousand rows that listing was most of the time between
        // pressing the button and seeing the grid.
        //
        // The fast path asks the element for exactly the parameter it needs, by its Definition, which
        // Element.get_Parameter has accepted on every release this tool supports.  The Definition is
        // learnt from the first full listing that carries the parameter, so nothing is constructed
        // from an id and no enum is cast from an integer - the two things that differ between 2024
        // and 2026.
        //
        // It is not trusted on faith.  For the first PARAM_VERIFY elements OF EACH CATEGORY that ask
        // for a given parameter, both paths run and are compared; one disagreement and that parameter
        // goes back to the full listing for the rest of the read.  Per category, because a
        // multi-category schedule can list a few hundred ducts before its first pipe, and checking
        // only the first few rows would never see the pipes.  The worst case is therefore the old
        // speed, never a different answer.

        public const int PARAM_VERIFY = 25;

        /// <summary>Every parameter on an element, keyed by parameter id - the slow way.</summary>
        public static Dictionary<long, Parameter> ParamMap(Element elem)
        {
            var pmap = new Dictionary<long, Parameter>();
            if (elem == null) return pmap;
            try
            {
                foreach (Parameter p in elem.Parameters)
                {
                    try { pmap[EidValue(p.Id)] = p; }
                    catch (Exception) { }
                }
            }
            catch (Exception) { }
            return pmap;
        }

        /// <summary>Do two lookups agree: both absent, or the same parameter.</summary>
        public static bool SameParam(Parameter a, Parameter b)
        {
            if (a == null || b == null) return a == null && b == null;
            try { return EidValue(a.Id) == EidValue(b.Id); }
            catch (Exception) { return false; }
        }

        /// <summary>Which category an element belongs to, for per-category checking (null if none).</summary>
        public static long? CategoryKey(Element elem)
        {
            try { return EidValue(elem.Category.Id); }
            catch (Exception) { return null; }
        }
    }

    /// <summary>Anything that answers "which parameter has this id" for one element: a <see cref="ParamView"/>,
    /// or a plain dictionary from <see cref="Efr.ParamMap"/> (implicit conversion).</summary>
    public abstract class ParamSource
    {
        /// <summary>The parameter with this parameter-id value, or null.</summary>
        public abstract Parameter Get(long pid);

        public static implicit operator ParamSource(Dictionary<long, Parameter> map)
        {
            return map == null ? null : new DictParamSource(map);
        }
    }

    /// <summary>A parameter dictionary as a <see cref="ParamSource"/>.</summary>
    public sealed class DictParamSource : ParamSource
    {
        readonly Dictionary<long, Parameter> _map;
        public DictParamSource(Dictionary<long, Parameter> map) { _map = map; }
        public Dictionary<long, Parameter> Map { get { return _map; } }

        public override Parameter Get(long pid)
        {
            Parameter p;
            return _map.TryGetValue(pid, out p) ? p : null;
        }
    }

    /// <summary>What the read has learnt about finding each parameter quickly.</summary>
    public class ParamLookup
    {
        public int Verify;
        /// <summary>pid -> Definition, learnt from a full listing</summary>
        public Dictionary<long, Definition> Defs = new Dictionary<long, Definition>();
        /// <summary>pids the fast path got wrong at least once</summary>
        public HashSet<long> Slow = new HashSet<long>();
        /// <summary>(category, pid) -> elements verified on</summary>
        public Dictionary<(long? Category, long Pid), int> Checks = new Dictionary<(long? Category, long Pid), int>();
        /// <summary>full listings made, for the bench</summary>
        public int Listings;

        public ParamLookup() : this(Efr.PARAM_VERIFY) { }

        public ParamLookup(int verify)
        {
            Verify = verify;
        }

        public ParamView View(Element elem)
        {
            return new ParamView(this, elem, Efr.CategoryKey(elem));
        }
    }

    /// <summary>One element's parameters, read on demand.  Dict-like on purpose: Get(pid) is all the
    /// reader and CombinedValue have ever asked of the old map, so it drops in where the map was.</summary>
    public class ParamView : ParamSource
    {
        public ParamLookup Lookup;
        public Element Elem;
        public long? Category;
        Dictionary<long, Parameter> _full;
        /// <summary>pid -> the answer already given for this element (null answers included)</summary>
        readonly Dictionary<long, Parameter> _known = new Dictionary<long, Parameter>();

        public ParamView(ParamLookup lookup, Element elem, long? category = null)
        {
            Lookup = lookup;
            Elem = elem;
            Category = category;
        }

        public Dictionary<long, Parameter> Full()
        {
            if (_full == null)
            {
                Lookup.Listings += 1;
                _full = Efr.ParamMap(Elem);
            }
            return _full;
        }

        /// <summary>The parameter, or null.
        /// Each element answers each parameter once and remembers it.  A type is one view shared by
        /// every row of that type, so without this its rows would each ask Revit again - and each spend
        /// one of the category's verification checks on the same element, leaving the other families
        /// in the category unchecked.</summary>
        public override Parameter Get(long pid)
        {
            if (Elem == null) return null;
            Parameter p;
            if (_known.TryGetValue(pid, out p)) return p;
            p = Resolve(pid);
            _known[pid] = p;
            return p;
        }

        /// <summary>Python get(pid, default): the parameter, or <paramref name="defaultValue"/> when absent.</summary>
        public Parameter Get(long pid, Parameter defaultValue)
        {
            Parameter p = Get(pid);
            return p ?? defaultValue;
        }

        Parameter FromFull(long pid)
        {
            Parameter q;
            return Full().TryGetValue(pid, out q) ? q : null;
        }

        Parameter Resolve(long pid)
        {
            ParamLookup lk = Lookup;
            Definition defn;
            lk.Defs.TryGetValue(pid, out defn);
            if (defn == null || lk.Slow.Contains(pid))
            {
                Parameter full = FromFull(pid);
                if (full != null && defn == null && !lk.Slow.Contains(pid))
                {
                    try { lk.Defs[pid] = full.Definition; }
                    catch (Exception) { lk.Slow.Add(pid); }
                }
                return full;
            }
            Parameter p;
            try
            {
                p = Elem.get_Parameter(defn);
            }
            catch (Exception)
            {
                lk.Slow.Add(pid);
                return FromFull(pid);
            }
            var tally = (Category, pid);
            int n;
            lk.Checks.TryGetValue(tally, out n);
            if (n < lk.Verify)
            {
                lk.Checks[tally] = n + 1;
                Parameter q = FromFull(pid);
                if (!Efr.SameParam(p, q))
                {
                    lk.Slow.Add(pid);
                    p = q;
                }
            }
            return p;
        }
    }

    public static partial class Efr
    {
        // ------------------------------------------------------------ field types ----

        /// <summary>ScheduleFieldType.Instance (Python SFT_INSTANCE; never null in C#).</summary>
        public static readonly ScheduleFieldType SFT_INSTANCE = ScheduleFieldType.Instance;

        /// <summary>ScheduleFieldType.ElementType (Python SFT_TYPE; never null in C#).</summary>
        public static readonly ScheduleFieldType SFT_TYPE = ScheduleFieldType.ElementType;
    }
}
