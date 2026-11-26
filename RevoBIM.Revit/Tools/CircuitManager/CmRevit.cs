using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.CircuitManager
{
    /// <summary>Settings shared by every window of the tool (a plain key=value file) and the debug log.</summary>
    public static class CmSettings
    {
        private static Dictionary<string, string> data;

        public static string Dir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }

        public static string SettingsPath()
        {
            return Path.Combine(Dir(), CmLogic.ToolKey + ".txt");
        }

        public static string DebugPath()
        {
            return Path.Combine(Dir(), CmLogic.ToolKey + "_debug.txt");
        }

        public static string ErrorPath()
        {
            return Path.Combine(Dir(), CmLogic.ToolKey + "_last_error.txt");
        }

        private static Dictionary<string, string> Data()
        {
            if (data == null) Load();
            return data;
        }

        public static void Load()
        {
            try
            {
                data = CmLogic.ParseSettings(File.ReadAllText(SettingsPath(), Encoding.UTF8));
            }
            catch (Exception)
            {
                data = CmLogic.ParseSettings("");
            }
        }

        public static void Save()
        {
            try
            {
                Directory.CreateDirectory(Dir());
                File.WriteAllText(SettingsPath(), CmLogic.DumpSettings(Data()), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }

        public static string Get(string key)
        {
            string v;
            if (Data().TryGetValue(key, out v)) return v;
            string d;
            return CmLogic.Defaults().TryGetValue(key, out d) ? d : "";
        }

        public static void Set(string key, string value, bool save = true)
        {
            Data()[key] = value ?? "";
            if (save) Save();
        }

        /// <summary>First line of a debug log: which build wrote it.</summary>
        public static string BuildInfo()
        {
            return "Circuit Manager v" + CmLogic.Version + ", build " + typeof(CmSettings).Assembly.GetName().Version;
        }

        private static bool headerWritten;

        public static void Log(string text)
        {
            if (Get("debug") != "1") return;
            try
            {
                Directory.CreateDirectory(Dir());
                var sb = new StringBuilder();
                if (!headerWritten)
                {
                    headerWritten = true;
                    sb.Append("---- ").Append(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture)).Append("  ")
                      .Append(BuildInfo()).Append('\n');
                }
                sb.Append(DateTime.Now.ToString("HH:mm:ss", CultureInfo.InvariantCulture)).Append(" v").Append(CmLogic.Version).Append(' ')
                  .Append(text).Append('\n');
                File.AppendAllText(DebugPath(), sb.ToString(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }
    }

    /// <summary>One circuit as the table sees it. Values are text, keyed by column.</summary>
    public sealed class CircuitRow
    {
        public long Eid;
        public ElementId ElementId;
        public readonly Dictionary<string, string> Values = new Dictionary<string, string>();
        public readonly Dictionary<string, bool> Editable = new Dictionary<string, bool>();
        public readonly Dictionary<string, string> Kinds = new Dictionary<string, string>();
        public readonly Dictionary<string, string> Reasons = new Dictionary<string, string>();
        public bool CustomOk;

        public string V(string key)
        {
            string v;
            return Values.TryGetValue(key, out v) ? v : "";
        }

        public bool CanEdit(string key)
        {
            bool b;
            return Editable.TryGetValue(key, out b) && b;
        }

        public string Reason(string key, string fallback)
        {
            string v;
            return Reasons.TryGetValue(key, out v) ? v : fallback;
        }

        public string Kind(string key)
        {
            string v;
            return Kinds.TryGetValue(key, out v) ? v : "string";
        }
    }

    public sealed class FixedColumn
    {
        public string Key, Heading, Kind;
        public bool Editable;
    }

    public sealed class ParamInfo
    {
        public string Name, Kind;
        public bool Writable;
    }

    /// <summary>
    /// Reading circuits from the model and writing them back (cm_revit.py). Every write goes out through an
    /// ExternalEvent (the window is modeless), in one transaction with a sub-transaction per circuit so one refusal
    /// does not lose the batch, and every write is read back: a void API call is not evidence.
    /// </summary>
    public static class CmRevit
    {
        public static readonly FixedColumn[] Fixed =
        {
            new FixedColumn { Key = "panel", Heading = "Panel", Kind = "string", Editable = false },
            new FixedColumn { Key = "num", Heading = "Circuit Number", Kind = "string", Editable = false },
            new FixedColumn { Key = "load", Heading = "Load Name", Kind = "string", Editable = false },
            new FixedColumn { Key = "stype", Heading = "System Type", Kind = "string", Editable = false },
            new FixedColumn { Key = "pm", Heading = "Path Mode", Kind = "pm", Editable = true },
            new FixedColumn { Key = "po", Heading = "Path Offset (mm)", Kind = "po", Editable = true },
            new FixedColumn { Key = "len", Heading = "Length (mm)", Kind = "string", Editable = false },
            new FixedColumn { Key = "nelem", Heading = "Elements", Kind = "string", Editable = false },
        };

        public const string ParamPrefix = "p:";
        public const string Varies = "Varies";

        private static string S(object o)
        {
            return o == null ? "" : o.ToString();
        }

        public static string ElemName(Element element)
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

        public static List<ElectricalSystem> CollectCircuits(Document doc)
        {
            return new FilteredElementCollector(doc).OfClass(typeof(ElectricalSystem)).Cast<ElectricalSystem>().ToList();
        }

        private static string PanelName(ElectricalSystem es)
        {
            try
            {
                string name = es.PanelName;
                if (!string.IsNullOrEmpty(name)) return name;
            }
            catch (Exception)
            {
            }
            try
            {
                return ElemName(es.BaseEquipment);
            }
            catch (Exception)
            {
                return "";
            }
        }

        private static string LengthMm(ElectricalSystem es)
        {
            try
            {
                Parameter p = es.get_Parameter(BuiltInParameter.RBS_ELEC_CIRCUIT_LENGTH_PARAM);
                if (p != null && p.HasValue) return CmLogic.FeetToMmText(p.AsDouble());
            }
            catch (Exception)
            {
            }
            try
            {
                return CmLogic.FeetToMmText(es.Length);
            }
            catch (Exception)
            {
                return "";
            }
        }

        public static string PathModeName(ElectricalSystem es)
        {
            try
            {
                return S(es.CircuitPathMode);
            }
            catch (Exception)
            {
                return "";
            }
        }

        public static string PathOffsetText(ElectricalSystem es)
        {
            try
            {
                if (!es.HasPathOffset) return Varies;
            }
            catch (Exception)
            {
            }
            try
            {
                return CmLogic.FeetToMmText(es.PathOffset);
            }
            catch (Exception)
            {
                return "";
            }
        }

        public static string ParamKind(Parameter p)
        {
            try
            {
                switch (p.StorageType)
                {
                    case StorageType.String: return "string";
                    case StorageType.Integer:
                        try
                        {
                            if (p.Definition.GetDataType() == SpecTypeId.Boolean.YesNo) return "yesno";
                        }
                        catch (Exception)
                        {
                        }
                        return "int";
                    case StorageType.Double: return "double";
                }
            }
            catch (Exception)
            {
            }
            return "id";
        }

        public static string ParamText(Parameter p)
        {
            if (p == null) return "";
            try
            {
                switch (p.StorageType)
                {
                    case StorageType.String:
                        return p.AsString() ?? "";
                }
                string vs = p.AsValueString();
                if (vs != null) return vs;
                switch (p.StorageType)
                {
                    case StorageType.Integer: return p.AsInteger().ToString(CultureInfo.InvariantCulture);
                    case StorageType.Double: return p.AsDouble().ToString(CultureInfo.InvariantCulture);
                    case StorageType.ElementId: return p.AsElementId().Value.ToString(CultureInfo.InvariantCulture);
                }
            }
            catch (Exception)
            {
            }
            return "";
        }

        public static bool ParamWritable(Parameter p)
        {
            try
            {
                string kind = ParamKind(p);
                return !p.IsReadOnly && (kind == "string" || kind == "int" || kind == "yesno" || kind == "double");
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static Parameter FindParam(ElectricalSystem es, string name)
        {
            try
            {
                return es.LookupParameter(name);
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>Parameters carried by circuits, sorted by name. Reads up to `sample` circuits so a parameter bound to one circuit type only still shows up.</summary>
        public static List<ParamInfo> AvailableParameters(List<ElectricalSystem> circuits, int sample = 200)
        {
            var found = new Dictionary<string, ParamInfo>();
            foreach (ElectricalSystem es in circuits.Take(sample))
            {
                List<Parameter> list;
                try
                {
                    list = es.Parameters.Cast<Parameter>().ToList();
                }
                catch (Exception)
                {
                    continue;
                }
                foreach (Parameter p in list)
                {
                    string name;
                    try
                    {
                        name = p.Definition.Name;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                    if (string.IsNullOrEmpty(name) || found.ContainsKey(name)) continue;
                    found[name] = new ParamInfo { Name = name, Kind = ParamKind(p), Writable = ParamWritable(p) };
                }
            }
            var result = found.Values.ToList();
            result.Sort((a, b) => CmLogic.NaturalCompare(a.Name, b.Name));
            return result;
        }

        public static CircuitRow ReadRow(ElectricalSystem es, IEnumerable<string> paramKeys)
        {
            var row = new CircuitRow { Eid = es.Id.Value, ElementId = es.Id };
            Dictionary<string, string> v = row.Values;
            v["panel"] = PanelName(es);
            try { v["num"] = es.CircuitNumber ?? ""; } catch (Exception) { v["num"] = ""; }
            try { v["load"] = es.LoadName ?? ""; } catch (Exception) { v["load"] = ""; }
            try { v["stype"] = S(es.SystemType); } catch (Exception) { v["stype"] = ""; }
            v["pm"] = CmLogic.PathModeLabel(PathModeName(es));
            v["po"] = PathOffsetText(es);
            v["len"] = LengthMm(es);
            try { v["nelem"] = es.Elements.Size.ToString(CultureInfo.InvariantCulture); } catch (Exception) { v["nelem"] = ""; }
            foreach (FixedColumn f in Fixed)
            {
                row.Kinds[f.Key] = f.Kind;
                row.Editable[f.Key] = f.Editable;
            }
            try { row.CustomOk = es.HasCustomCircuitPath; } catch (Exception) { row.CustomOk = false; }
            if (v["pm"] == "")
            {
                row.Editable["pm"] = false;
                row.Reasons["pm"] = "path mode not available on this circuit";
            }
            foreach (string key in paramKeys)
            {
                string name = key.Substring(ParamPrefix.Length);
                Parameter p = FindParam(es, name);
                if (p == null)
                {
                    v[key] = "";
                    row.Kinds[key] = "string";
                    row.Editable[key] = false;
                    row.Reasons[key] = "this circuit does not carry the parameter";
                    continue;
                }
                v[key] = ParamText(p);
                row.Kinds[key] = ParamKind(p);
                row.Editable[key] = ParamWritable(p);
                if (!row.Editable[key]) row.Reasons[key] = "read only";
            }
            return row;
        }

        public static List<CircuitRow> ReadRows(Document doc, IEnumerable<string> paramKeys)
        {
            List<string> keys = paramKeys.ToList();
            return CollectCircuits(doc).Select(es => ReadRow(es, keys)).ToList();
        }

        // ------------------------------------------------------------------ writing
        /// <summary>Deletes warnings; records errors so a refusal reports Revit's words.</summary>
        private sealed class Failures : IFailuresPreprocessor
        {
            public readonly List<string> Messages = new List<string>();

            public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
            {
                try
                {
                    foreach (FailureMessageAccessor f in accessor.GetFailureMessages().ToList())
                    {
                        string text = "";
                        try { text = f.GetDescriptionText(); } catch (Exception) { }
                        if (f.GetSeverity() == FailureSeverity.Warning) accessor.DeleteWarning(f);
                        else if (text.Length > 0) Messages.Add(text);
                    }
                }
                catch (Exception)
                {
                }
                return FailureProcessingResult.Continue;
            }
        }

        private static ElectricalCircuitPathMode? ModeEnum(string name)
        {
            ElectricalCircuitPathMode m;
            if (name != null && Enum.TryParse(name, out m)) return m;
            return null;
        }

        /// <summary>Returns {eid: reason} for elements that could not be borrowed.</summary>
        private static Dictionary<long, string> Borrow(Document doc, List<ElementId> eids)
        {
            var refused = new Dictionary<long, string>();
            if (!doc.IsWorkshared || eids.Count == 0) return refused;
            var lookup = new Dictionary<long, ElementId>();
            foreach (ElementId e in eids) lookup[e.Value] = e;
            var held = new HashSet<long>();
            try
            {
                foreach (ElementId e in WorksharingUtils.CheckoutElements(doc, eids)) held.Add(e.Value);
            }
            catch (Exception ex)
            {
                foreach (long k in lookup.Keys) refused[k] = "could not borrow: " + ex.Message;
                return refused;
            }
            foreach (var entry in lookup)
            {
                if (held.Contains(entry.Key)) continue;
                string owner = "";
                try
                {
                    owner = WorksharingUtils.GetWorksharingTooltipInfo(doc, entry.Value).Owner;
                }
                catch (Exception)
                {
                }
                refused[entry.Key] = "owned by " + (string.IsNullOrEmpty(owner) ? "another user" : owner) + " - ask them to sync and relinquish";
            }
            return refused;
        }

        /// <summary>Makes one change and reads it back. Returns null or a refusal reason.</summary>
        private static string WriteOne(Document doc, ElectricalSystem es, string key, string value)
        {
            if (key == "pm")
            {
                string name = CmLogic.ParsePathMode(value);
                ElectricalCircuitPathMode? member = name == null ? null : ModeEnum(name);
                if (member == null) return "Revit has no path mode called " + value;
                if (name == "Custom")
                {
                    try
                    {
                        if (!es.HasCustomCircuitPath) return "no custom path stored - edit the path in Revit first";
                    }
                    catch (Exception)
                    {
                    }
                }
                es.CircuitPathMode = member.Value;
                if (CmLogic.ParsePathMode(PathModeName(es)) != name)
                    return "Revit kept " + CmLogic.PathModeLabel(PathModeName(es));
                return null;
            }
            if (key == "po")
            {
                double? mm = CmLogic.ParseMm(value);
                if (mm == null) return "not a length";
                double target = CmLogic.MmToFeet(mm.Value);
                es.PathOffset = target;
                double? got = null;
                try { got = es.PathOffset; } catch (Exception) { }
                if (got == null || Math.Abs(got.Value - target) > 1e-5) return "Revit kept " + PathOffsetText(es);
                return null;
            }
            if (key.StartsWith(ParamPrefix, StringComparison.Ordinal))
            {
                string name = key.Substring(ParamPrefix.Length);
                Parameter p = FindParam(es, name);
                if (p == null) return "parameter not on this circuit";
                if (p.IsReadOnly) return "read only";
                string kind = ParamKind(p);
                bool ok;
                if (kind == "string")
                {
                    p.Set(value ?? "");
                    ok = (p.AsString() ?? "") == (value ?? "");
                }
                else if (kind == "yesno")
                {
                    int want = CmLogic.IsYes(value) ? 1 : 0;
                    p.Set(want);
                    ok = p.AsInteger() == want;
                }
                else if (kind == "int")
                {
                    int n = int.Parse((value ?? "").Trim(), CultureInfo.InvariantCulture);
                    p.Set(n);
                    ok = p.AsInteger() == n;
                }
                else if (kind == "double")
                {
                    ok = p.SetValueString(value ?? "");
                    if (!ok) return "Revit could not read " + value + " as a value";
                }
                else return "this kind of parameter cannot be edited here";
                if (!ok) return "Revit did not keep the value";
                return null;
            }
            return "column cannot be edited";
        }

        /// <summary>changes: {eid: [(key, value)]} (from CmStage.ByElement). Returns {(eid, key): null or refusal reason}.</summary>
        public static Dictionary<Tuple<long, string>, string> ApplyChanges(Document doc, Dictionary<long, List<KeyValuePair<string, string>>> changes,
                                                                             Action<string> log = null)
        {
            var results = new Dictionary<Tuple<long, string>, string>();
            if (changes.Count == 0) return results;
            var elements = new Dictionary<long, ElectricalSystem>();
            foreach (ElectricalSystem es in CollectCircuits(doc))
            {
                if (changes.ContainsKey(es.Id.Value)) elements[es.Id.Value] = es;
            }
            foreach (var entry in changes)
            {
                if (elements.ContainsKey(entry.Key)) continue;
                foreach (var kv in entry.Value) results[Tuple.Create(entry.Key, kv.Key)] = "circuit no longer in the model";
            }
            Dictionary<long, string> notHeld = Borrow(doc, elements.Values.Select(e => e.Id).ToList());
            foreach (var entry in notHeld)
                foreach (var kv in changes[entry.Key]) results[Tuple.Create(entry.Key, kv.Key)] = entry.Value;
            List<long> todo = elements.Keys.Where(k => !notHeld.ContainsKey(k)).ToList();
            if (todo.Count == 0) return results;

            var fails = new Failures();
            TransactionStatus status;
            using (var t = new Transaction(doc, "Circuit Manager - apply"))
            {
                FailureHandlingOptions opts = t.GetFailureHandlingOptions();
                opts.SetFailuresPreprocessor(fails);
                opts.SetClearAfterRollback(true);
                t.SetFailureHandlingOptions(opts);
                t.Start();
                try
                {
                    foreach (long eid in todo)
                    {
                        ElectricalSystem es = elements[eid];
                        foreach (var kv in changes[eid])
                        {
                            string reason;
                            using (var st = new SubTransaction(doc))
                            {
                                st.Start();
                                try
                                {
                                    reason = WriteOne(doc, es, kv.Key, kv.Value);
                                }
                                catch (Exception ex)
                                {
                                    reason = string.IsNullOrEmpty(ex.Message) ? "Revit refused the change" : ex.Message;
                                }
                                if (reason == null) st.Commit();
                                else st.RollBack();
                            }
                            results[Tuple.Create(eid, kv.Key)] = reason;
                            if (log != null) log(eid + " " + kv.Key + " -> " + kv.Value + ": " + (reason ?? "ok"));
                        }
                    }
                    status = t.Commit();
                }
                catch (Exception ex)
                {
                    try { t.RollBack(); } catch (Exception) { }
                    foreach (long eid in todo)
                        foreach (var kv in changes[eid]) results[Tuple.Create(eid, kv.Key)] = "rolled back: " + ex.Message;
                    return results;
                }
            }
            if (status != TransactionStatus.Committed)
            {
                string why = fails.Messages.Count > 0 ? string.Join("; ", fails.Messages) : "Revit rolled the change back";
                foreach (long eid in todo)
                    foreach (var kv in changes[eid]) results[Tuple.Create(eid, kv.Key)] = why;
                return results;
            }
            // commit regenerates - prove what landed against the model as it now is
            foreach (long eid in todo)
            {
                ElectricalSystem es = elements[eid];
                foreach (var kv in changes[eid])
                {
                    var rk = Tuple.Create(eid, kv.Key);
                    if (results[rk] != null) continue;
                    CircuitRow now = ReadRow(es, kv.Key.StartsWith(ParamPrefix, StringComparison.Ordinal) ? new[] { kv.Key } : new string[0]);
                    string kind = now.Kind(kv.Key);
                    if (kind == "double") continue;   // Revit formats it its own way; SetValueString said yes
                    string want = kv.Value;
                    if (kv.Key == "pm") want = CmLogic.PathModeLabel(CmLogic.ParsePathMode(kv.Value));
                    if (!CmLogic.SameValue(kind, now.V(kv.Key), want))
                        results[rk] = "Revit reset it to " + now.V(kv.Key) + " on commit";
                }
            }
            return results;
        }
    }

    /// <summary>
    /// Queues jobs for Revit's API context through an ExternalEvent. Never clears the queue when Raise() is not
    /// Accepted: Pending means an earlier request is still waiting. A watchdog in the window frees one left busy.
    /// </summary>
    public sealed class CmRunner : IExternalEventHandler
    {
        private readonly Action<string> log;
        private readonly List<KeyValuePair<Func<UIApplication, object>, Action<object, string>>> queue =
            new List<KeyValuePair<Func<UIApplication, object>, Action<object, string>>>();
        private readonly ExternalEvent ev;

        public bool Busy;

        public CmRunner(Action<string> log)
        {
            this.log = log;
            ev = ExternalEvent.Create(this);
        }

        /// <summary>job(uiapp) returns a result; done(result, error) is called after.</summary>
        public bool Submit(Func<UIApplication, object> job, Action<object, string> done)
        {
            var item = new KeyValuePair<Func<UIApplication, object>, Action<object, string>>(job, done);
            queue.Add(item);
            ExternalEventRequest status = ev.Raise();
            if (log != null) log("Raise -> " + status);
            if (status == ExternalEventRequest.Accepted || status == ExternalEventRequest.Pending)
            {
                Busy = true;
                return true;
            }
            queue.Remove(item);
            try
            {
                done(null, "Revit refused the request (" + status + ")");
            }
            catch (Exception)
            {
            }
            return false;
        }

        public void Execute(UIApplication app)
        {
            var jobs = queue.ToList();
            queue.Clear();
            foreach (var item in jobs)
            {
                object result = null;
                string error = null;
                try
                {
                    result = item.Key(app);
                }
                catch (Exception ex)
                {
                    error = ex.ToString();
                }
                try
                {
                    item.Value(result, error);
                }
                catch (Exception ex)
                {
                    if (log != null) log(ex.ToString());
                }
            }
            Busy = false;
        }

        public string GetName()
        {
            return "RevoBIM Circuit Manager";
        }

        public void Free()
        {
            Busy = false;
        }
    }
}
