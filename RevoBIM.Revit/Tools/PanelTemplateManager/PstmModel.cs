using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;

namespace RevoBIM.Tools.PanelTemplateManager
{
    /// <summary>
    /// Whether an element can be written, and who is in the way if not. Two separate things lock an element in a workshared model and
    /// both are asked about: somebody has borrowed the element itself, or nobody has but its whole workset is owned by somebody.
    /// Both answers come from a local cache of the central model, so Apply asks again at the moment it writes.
    /// </summary>
    public sealed class Ownership
    {
        private readonly Document doc;
        private readonly bool workshared;
        private readonly string user = "";
        private readonly Dictionary<string, string> worksets = new Dictionary<string, string>();

        public Ownership(Document doc)
        {
            this.doc = doc;
            try { workshared = doc.IsWorkshared; } catch (Exception) { workshared = false; }
            try { user = (doc.Application.Username ?? "").Trim(); } catch (Exception) { user = ""; }
        }

        private bool IsMe(string who)
        {
            who = (who ?? "").Trim();
            return who.Length > 0 && string.Equals(who, user, StringComparison.OrdinalIgnoreCase);
        }

        public string OwnerOf(Element element)
        {
            try
            {
                return (WorksharingUtils.GetWorksharingTooltipInfo(doc, element.Id).Owner ?? "").Trim();
            }
            catch (Exception)
            {
                return "";
            }
        }

        private string WorksetLock(Element element)
        {
            WorksetId id;
            try { id = element.WorksetId; } catch (Exception) { return ""; }
            string key = id.ToString();
            string cached;
            if (worksets.TryGetValue(key, out cached)) return cached;
            string answer = "";
            try
            {
                Workset workset = doc.GetWorksetTable().GetWorkset(id);
                string owner = (workset.Owner ?? "").Trim();
                if (owner.Length > 0 && !IsMe(owner)) answer = "workset \"" + workset.Name + "\" is owned by " + owner;
            }
            catch (Exception)
            {
                answer = "";
            }
            worksets[key] = answer;
            return answer;
        }

        /// <summary>"" if this element can be written, otherwise why it cannot.</summary>
        public string Locked(Element element)
        {
            if (element == null || !workshared) return "";
            try
            {
                CheckoutStatus status = WorksharingUtils.GetCheckoutStatus(doc, element.Id);
                if (status == CheckoutStatus.OwnedByOtherUser)
                {
                    string who = OwnerOf(element);
                    return "checked out by " + (who.Length > 0 ? who : "another user");
                }
            }
            catch (Exception)
            {
            }
            return WorksetLock(element);
        }

        public string LockedAny(IEnumerable<Element> elements)
        {
            foreach (Element e in elements)
            {
                string reason = Locked(e);
                if (reason.Length > 0) return reason;
            }
            return "";
        }
    }

    /// <summary>What a template reports about itself.</summary>
    public sealed class TemplateInfo
    {
        public Element Element;
        public ElementId Id;
        public long IdVal;
        public string Name;
        public int Slots;
        public string Config = "", ConfigPretty = "", ScheduleType = "";
        public bool SinglePhase, IsDefault;
        public int UsedCount;
        public List<long> UsedPanels = new List<long>();
        public int? Number;
        public readonly Dictionary<string, bool> Flags = new Dictionary<string, bool>();

        public TemplateInfo(Element element)
        {
            Element = element;
            Id = element.Id;
            IdVal = element.Id.Value;
            Name = PstmModel.ElementName(element);
            Read();
        }

        private void Read()
        {
            var template = Element as PanelScheduleTemplate;
            if (template != null)
            {
                try
                {
                    if (template.IsBranchPanelSchedule) ScheduleType = "Branch Panel";
                    else if (template.IsSwitchboardSchedule) ScheduleType = "Switchboard";
                    else if (template.IsDataPanelSchedule) ScheduleType = "Data Panel";
                }
                catch (Exception)
                {
                }
                if (ScheduleType.Length == 0)
                {
                    try { ScheduleType = PstmModel.NormaliseScheduleType(template.GetPanelScheduleType().ToString()); } catch (Exception) { }
                }
                try { IsDefault = template.IsDefault; } catch (Exception) { IsDefault = false; }
            }
            PanelScheduleData data = PstmModel.TableData(Element);
            if (data == null) return;
            if (ScheduleType.Length == 0)
            {
                try { ScheduleType = PstmModel.NormaliseScheduleType(data.ScheduleType.ToString()); } catch (Exception) { }
            }
            try { Slots = data.NumberOfSlots; } catch (Exception) { Slots = 0; }
            try
            {
                Config = data.PanelConfiguration.ToString();
                ConfigPretty = PstmModel.PrettyEnum(Config);
            }
            catch (Exception)
            {
            }
            Flag("IsPanelSinglePhase", () => data.IsPanelSinglePhase);
            Flag("ShowSlotFromDeviceInsteadOfTemplate", () => data.ShowSlotFromDeviceInsteadOfTemplate);
            Flag("ShowMultipleRowsForMultiphaseCircuits", () => data.ShowMultipleRowsForMultiphaseCircuits);
            Flag("ShowCircuitNumberOnOneRowForMultiphaseCircuits", () => data.ShowCircuitNumberOnOneRowForMultiphaseCircuits);
            Flag("IsUnusedPhaseHidden", () => data.IsUnusedPhaseHidden);
            Flag("PhasesAsCurrents", () => data.PhasesAsCurrents);
            bool single;
            SinglePhase = Flags.TryGetValue("IsPanelSinglePhase", out single) && single;
        }

        private void Flag(string key, Func<bool> read)
        {
            try
            {
                Flags[key] = read();
            }
            catch (Exception)
            {
            }
        }
    }

    /// <summary>One panel with the template it is using and the one pending Apply.</summary>
    public sealed class PanelRow
    {
        public Element Element;
        public Document Doc;
        public ElementId Id;
        public long IdVal;
        public string Name;
        public ElementId ViewId;
        public Element View;
        public string ViewName = "";
        public long CurrentId;           // template currently on the schedule
        public string CurrentName = "";
        public long ChosenId;            // template pending Apply
        public string ChosenName = "";
        public string Status = "";       // '', 'changed', 'review', 'multi', 'locked'
        public string Note = "";
        public string Locked = "";       // why it cannot be written, if it cannot
        public int? CalcSlots;
        public string WaysText = "", PhasesText = "";
        private readonly Dictionary<string, string> cache = new Dictionary<string, string>();

        public PanelRow(Element element, Document doc)
        {
            Element = element;
            Doc = doc;
            Id = element.Id;
            IdVal = element.Id.Value;
            Name = PstmModel.PanelLabel(element, doc);
        }

        public string Value(string paramName)
        {
            if (string.IsNullOrEmpty(paramName)) return "";
            string v;
            if (!cache.TryGetValue(paramName, out v))
            {
                v = PstmModel.ReadParam(Element, Doc, paramName);
                cache[paramName] = v;
            }
            return v;
        }

        public bool Changed
        {
            get { return ChosenId != 0 && ChosenId != CurrentId; }
        }

        public void SetChoice(long templateId, string templateName)
        {
            ChosenId = templateId;
            ChosenName = templateName ?? "";
            if (Changed)
            {
                if (Status != "review" && Status != "multi") Status = "changed";
            }
            else if (Status == "changed") Status = "";
        }

        public void ResetChoice()
        {
            ChosenId = CurrentId;
            ChosenName = CurrentName;
            Status = "";
            Note = "";
        }

        public string DisplayTemplate()
        {
            if (ChosenName.Length > 0) return ChosenName;
            if (CurrentName.Length > 0) return CurrentName;
            return "<none>";
        }
    }

    public sealed class ModelData
    {
        public List<TemplateInfo> Templates = new List<TemplateInfo>();
        public List<PanelRow> Rows = new List<PanelRow>();
        public List<string> ParamNames = new List<string>();
        public Dictionary<long, TemplateInfo> ById = new Dictionary<long, TemplateInfo>();
        public Ownership Ownership;
    }

    public sealed class AssignSummary
    {
        public int Assigned, Already, Review, Multi, Kept, Locked, Total;
    }

    /// <summary>Reading the model: templates, panels, and the panel schedule view that ties one to the other (pstm_model.py).</summary>
    public static class PstmModel
    {
        public static readonly string[] PseudoParams = { "Family and Type", "Family", "Type Name", "Panel Name", "Level", "Workset", "Element Id" };
        public static readonly string[] ScheduleTypes = { "Branch Panel", "Switchboard", "Data Panel" };

        public static string ElementName(Element element)
        {
            try
            {
                return element.Name ?? "";
            }
            catch (Exception)
            {
                return "";
            }
        }

        public static bool SetElementName(Element element, string newName)
        {
            try
            {
                element.Name = newName;
            }
            catch (Exception)
            {
            }
            return ElementName(element) == newName;
        }

        /// <summary>The template's table data, whichever class the element is.</summary>
        public static PanelScheduleData TableData(Element element)
        {
            try
            {
                var template = element as PanelScheduleTemplate;
                if (template != null) return template.GetTableData();
                var view = element as PanelScheduleView;
                if (view != null) return view.GetTableData();
            }
            catch (Exception)
            {
            }
            return null;
        }

        /// <summary>One name per schedule type, whichever route it was read by.</summary>
        public static string NormaliseScheduleType(string raw)
        {
            string text = (raw ?? "").ToLowerInvariant();
            if (text.Length == 0) return "";
            if (text.Contains("branch")) return "Branch Panel";
            if (text.Contains("switch")) return "Switchboard";
            if (text.Contains("data")) return "Data Panel";
            return PrettyEnum(raw);
        }

        /// <summary>'TwoColumnsCircuitsOnLeft' to 'Two Columns Circuits On Left'.</summary>
        public static string PrettyEnum(string name)
        {
            if (string.IsNullOrEmpty(name)) return "";
            var sb = new System.Text.StringBuilder();
            for (int i = 0; i < name.Length; i++)
            {
                if (i > 0 && char.IsUpper(name[i]) && !char.IsUpper(name[i - 1])) sb.Append(' ');
                sb.Append(name[i]);
            }
            return sb.ToString();
        }

        public static List<string> ConfigChoices()
        {
            List<string> names = Enum.GetNames(typeof(PanelConfiguration)).ToList();
            if (names.Count == 0) names = new List<string> { "OneColumn", "TwoColumnsCircuitsOnLeft", "TwoColumnsCircuitsOnRight" };
            return names;
        }

        public static PanelConfiguration? ConfigValue(string name)
        {
            PanelConfiguration c;
            if (!string.IsNullOrEmpty(name) && Enum.TryParse(name, out c)) return c;
            return null;
        }

        // ------------------------------------------------------------------ parameter reading
        private static string ParamText(Parameter param, Document doc)
        {
            if (param == null) return "";
            try
            {
                switch (param.StorageType)
                {
                    case StorageType.String:
                        return param.AsString() ?? "";
                    case StorageType.ElementId:
                    {
                        ElementId pid = param.AsElementId();
                        if (pid != null && pid.Value > 0)
                        {
                            Element el = doc.GetElement(pid);
                            if (el != null) return ElementName(el);
                        }
                        return "";
                    }
                }
                string text = param.AsValueString();
                if (!string.IsNullOrEmpty(text)) return text;
                if (param.StorageType == StorageType.Integer) return param.AsInteger().ToString(CultureInfo.InvariantCulture);
                if (param.StorageType == StorageType.Double) return param.AsDouble().ToString(CultureInfo.InvariantCulture);
            }
            catch (Exception)
            {
                return "";
            }
            return "";
        }

        private static Parameter Lookup(Element element, string name)
        {
            if (element == null || string.IsNullOrEmpty(name)) return null;
            try
            {
                IList<Parameter> found = element.GetParameters(name);
                if (found != null && found.Count > 0) return found[0];
            }
            catch (Exception)
            {
            }
            try
            {
                return element.LookupParameter(name);
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>Instance parameter first, then the type's, then the pseudo columns.</summary>
        public static string ReadParam(Element element, Document doc, string name)
        {
            if (string.IsNullOrEmpty(name)) return "";
            if (PseudoParams.Contains(name)) return Pseudo(element, doc, name);
            string stripped = name;
            bool typeOnly = false;
            if (name.StartsWith("type: ", StringComparison.OrdinalIgnoreCase))
            {
                stripped = name.Substring(6);
                typeOnly = true;
            }
            if (!typeOnly)
            {
                string text = ParamText(Lookup(element, stripped), doc);
                if (text.Length > 0) return text;
            }
            Element typeEl = null;
            try { typeEl = doc.GetElement(element.GetTypeId()); } catch (Exception) { }
            return ParamText(Lookup(typeEl, stripped), doc);
        }

        private static string Pseudo(Element element, Document doc, string name)
        {
            try
            {
                if (name == "Element Id") return element.Id.Value.ToString(CultureInfo.InvariantCulture);
                Element typeEl = null;
                try { typeEl = doc.GetElement(element.GetTypeId()); } catch (Exception) { }
                string fam = "", typ = "";
                var type = typeEl as ElementType;
                if (typeEl != null)
                {
                    typ = ElementName(typeEl);
                    try { fam = type != null ? type.FamilyName ?? "" : ""; } catch (Exception) { fam = ""; }
                }
                if (name == "Family") return fam;
                if (name == "Type Name") return typ;
                if (name == "Family and Type")
                {
                    if (fam.Length > 0 && typ.Length > 0) return fam + " : " + typ;
                    return typ.Length > 0 ? typ : fam;
                }
                if (name == "Panel Name") return PanelLabel(element, doc);
                if (name == "Level")
                {
                    try
                    {
                        Element lvl = doc.GetElement(element.LevelId);
                        if (lvl != null) return ElementName(lvl);
                    }
                    catch (Exception)
                    {
                    }
                    return ReadParam(element, doc, "Schedule Level");
                }
                if (name == "Workset")
                {
                    try
                    {
                        Workset ws = doc.GetWorksetTable().GetWorkset(element.WorksetId);
                        return ws != null ? ws.Name : "";
                    }
                    catch (Exception)
                    {
                        return "";
                    }
                }
            }
            catch (Exception)
            {
                return "";
            }
            return "";
        }

        /// <summary>What the user calls the panel: its Panel Name, else Mark, else Name.</summary>
        public static string PanelLabel(Element element, Document doc)
        {
            try
            {
                string text = ParamText(element.get_Parameter(BuiltInParameter.RBS_ELEC_PANEL_NAME), doc);
                if (text.Length > 0) return text;
            }
            catch (Exception)
            {
            }
            foreach (string name in new[] { "Panel Name", "Mark" })
            {
                string text = ParamText(Lookup(element, name), doc);
                if (text.Length > 0) return text;
            }
            string n = ElementName(element);
            return n.Length > 0 ? n : "Id " + element.Id.Value.ToString(CultureInfo.InvariantCulture);
        }

        /// <summary>
        /// Every project or shared parameter bound to the category. The bindings map is the authority on what the category can carry,
        /// so it is asked directly and unioned with what the elements report.
        /// </summary>
        public static void BoundParams(Document doc, HashSet<string> instanceNames, HashSet<string> typeNames)
        {
            Category category = null;
            try { category = doc.Settings.Categories.get_Item(BuiltInCategory.OST_ElectricalEquipment); } catch (Exception) { }
            if (category == null) return;
            long categoryId = category.Id.Value;
            try
            {
                DefinitionBindingMapIterator it = doc.ParameterBindings.ForwardIterator();
                it.Reset();
                while (it.MoveNext())
                {
                    string name;
                    var binding = it.Current as ElementBinding;
                    try { name = it.Key.Name; } catch (Exception) { continue; }
                    if (string.IsNullOrEmpty(name) || binding == null) continue;
                    bool covered = false;
                    try
                    {
                        foreach (Category cat in binding.Categories)
                        {
                            if (cat.Id.Value == categoryId)
                            {
                                covered = true;
                                break;
                            }
                        }
                    }
                    catch (Exception)
                    {
                        covered = false;
                    }
                    if (!covered) continue;
                    if (binding is TypeBinding) typeNames.Add(name);
                    else instanceNames.Add(name);
                }
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Every parameter name available on the panels, for the pickers. A "Type: x" entry is added only where the same name exists on the instance too.</summary>
        public static List<string> AvailableParams(Document doc, List<Element> elements, int limit = 800)
        {
            var instanceNames = new HashSet<string>();
            var typeNames = new HashSet<string>();
            BoundParams(doc, instanceNames, typeNames);
            var seenTypes = new HashSet<long>();
            foreach (Element el in elements.Take(limit))
            {
                try
                {
                    foreach (Parameter p in el.Parameters)
                    {
                        try { instanceNames.Add(p.Definition.Name); } catch (Exception) { }
                    }
                }
                catch (Exception)
                {
                }
                try
                {
                    foreach (Parameter p in el.GetOrderedParameters())
                    {
                        try { instanceNames.Add(p.Definition.Name); } catch (Exception) { }
                    }
                }
                catch (Exception)
                {
                }
                try
                {
                    long tid = el.GetTypeId().Value;
                    if (tid != 0 && seenTypes.Add(tid))
                    {
                        Element typeEl = doc.GetElement(el.GetTypeId());
                        if (typeEl != null)
                        {
                            foreach (Parameter p in typeEl.Parameters)
                            {
                                try { typeNames.Add(p.Definition.Name); } catch (Exception) { }
                            }
                        }
                    }
                }
                catch (Exception)
                {
                }
            }
            var names = new HashSet<string>(instanceNames);
            names.UnionWith(typeNames);
            var both = new HashSet<string>(instanceNames);
            both.IntersectWith(typeNames);
            foreach (string p in PseudoParams) names.Remove(p);
            var ordered = new List<string>(PseudoParams);
            ordered.AddRange(names.OrderBy(s => s.ToLowerInvariant(), StringComparer.Ordinal));
            ordered.AddRange(both.Select(n => "Type: " + n).OrderBy(s => s.ToLowerInvariant(), StringComparer.Ordinal));
            return ordered;
        }

        // ------------------------------------------------------------------ templates and panels
        /// <summary>
        /// Every panel schedule template in the project: collected both as PanelScheduleTemplate elements and as PanelScheduleView elements
        /// flagged as templates, then de-duplicated by id, because which class a release surfaces them under has not been consistent.
        /// </summary>
        public static List<TemplateInfo> CollectTemplates(Document doc, Dictionary<string, string> settings)
        {
            string rule = PstmCore.Get(settings, "name_number_rule");
            string keyword = PstmCore.Get(settings, "name_number_keyword");
            var found = new Dictionary<long, Element>();
            try
            {
                foreach (Element el in new FilteredElementCollector(doc).OfClass(typeof(PanelScheduleTemplate))) found[el.Id.Value] = el;
            }
            catch (Exception)
            {
            }
            try
            {
                foreach (Element el in new FilteredElementCollector(doc).OfClass(typeof(PanelScheduleView)))
                {
                    var view = (PanelScheduleView)el;
                    try
                    {
                        if (!view.IsPanelScheduleTemplate()) continue;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                    if (!found.ContainsKey(el.Id.Value)) found[el.Id.Value] = el;
                }
            }
            catch (Exception)
            {
            }
            var output = new List<TemplateInfo>();
            foreach (Element el in found.Values)
            {
                TemplateInfo info;
                try
                {
                    info = new TemplateInfo(el);
                }
                catch (Exception)
                {
                    continue;
                }
                info.Number = PstmCore.ExtractTemplateNumber(info.Name, rule, keyword);
                output.Add(info);
            }
            output.Sort((a, b) => string.CompareOrdinal((a.Name ?? "").ToLowerInvariant(), (b.Name ?? "").ToLowerInvariant()));
            return output;
        }

        public static List<Element> CollectPanels(Document doc)
        {
            var output = new List<Element>();
            try
            {
                foreach (Element el in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_ElectricalEquipment).WhereElementIsNotElementType())
                    output.Add(el);
            }
            catch (Exception)
            {
            }
            return output;
        }

        /// <summary>The panel schedule view instances (not templates).</summary>
        public static List<PanelScheduleView> InstanceViews(Document doc)
        {
            var output = new List<PanelScheduleView>();
            try
            {
                foreach (Element el in new FilteredElementCollector(doc).OfClass(typeof(PanelScheduleView)))
                {
                    var view = (PanelScheduleView)el;
                    try { if (view.IsPanelScheduleTemplate()) continue; } catch (Exception) { }
                    try { if (view.IsTemplate) continue; } catch (Exception) { }
                    output.Add(view);
                }
            }
            catch (Exception)
            {
            }
            return output;
        }

        /// <summary>panel id: the panel schedule view instance sitting on it.</summary>
        public static Dictionary<long, PanelScheduleView> CollectInstanceViews(Document doc)
        {
            var views = new Dictionary<long, PanelScheduleView>();
            foreach (PanelScheduleView v in InstanceViews(doc))
            {
                long key = 0;
                try { key = v.GetPanel().Value; } catch (Exception) { }
                if (key != 0 && !views.ContainsKey(key)) views[key] = v;
            }
            return views;
        }

        public static long ViewTemplateId(PanelScheduleView view)
        {
            try
            {
                return view.GetTemplate().Value;
            }
            catch (Exception)
            {
                return 0;
            }
        }

        /// <summary>One pass over the model: everything both tabs need.</summary>
        public static ModelData Read(Document doc, Dictionary<string, string> settings)
        {
            var data = new ModelData();
            data.Templates = CollectTemplates(doc, settings);
            foreach (TemplateInfo t in data.Templates) data.ById[t.IdVal] = t;
            Dictionary<long, PanelScheduleView> views = CollectInstanceViews(doc);
            List<Element> panels = CollectPanels(doc);
            data.ParamNames = AvailableParams(doc, panels);
            data.Ownership = new Ownership(doc);
            foreach (Element el in panels)
            {
                PanelRow row;
                try
                {
                    row = new PanelRow(el, doc);
                }
                catch (Exception)
                {
                    continue;
                }
                PanelScheduleView view;
                views.TryGetValue(row.IdVal, out view);
                // the schedule view is what a template swap writes to, so it is the one that has to be free; the panel matters too for a
                // board with no schedule yet, because making one writes to the panel
                var holders = new List<Element>();
                if (view != null) holders.Add(view);
                holders.Add(el);
                row.Locked = data.Ownership.LockedAny(holders);
                if (view != null)
                {
                    row.View = view;
                    row.ViewId = view.Id;
                    row.ViewName = ElementName(view);
                    row.CurrentId = ViewTemplateId(view);
                    TemplateInfo tpl;
                    row.CurrentName = data.ById.TryGetValue(row.CurrentId, out tpl) ? tpl.Name : "";
                }
                row.ChosenId = row.CurrentId;
                row.ChosenName = row.CurrentName;
                data.Rows.Add(row);
                if (row.CurrentId != 0)
                {
                    TemplateInfo used;
                    if (data.ById.TryGetValue(row.CurrentId, out used))
                    {
                        used.UsedCount++;
                        used.UsedPanels.Add(row.IdVal);
                    }
                }
            }
            data.Rows.Sort((a, b) => NaturalCompare(a.Name, b.Name));
            return data;
        }

        private static readonly Regex Digits = new Regex(@"(\d+)");

        /// <summary>Sort P1, P2, P10 the way a person reads them.</summary>
        public static int NaturalCompare(string a, string b)
        {
            string[] pa = Digits.Split((a ?? "").ToLowerInvariant()).Where(x => x.Length > 0).ToArray(), pb = Digits.Split((b ?? "").ToLowerInvariant()).Where(x => x.Length > 0).ToArray();
            int n = Math.Min(pa.Length, pb.Length);
            for (int i = 0; i < n; i++)
            {
                if (pa[i] == pb[i]) continue;
                bool da = pa[i].Length > 0 && char.IsDigit(pa[i][0]), db = pb[i].Length > 0 && char.IsDigit(pb[i][0]);
                if (da && db)
                {
                    decimal x = decimal.Parse(pa[i], CultureInfo.InvariantCulture), y = decimal.Parse(pb[i], CultureInfo.InvariantCulture);
                    int c = x.CompareTo(y);
                    if (c != 0) return c;
                }
                else if (da != db) return da ? 1 : -1;   // text sorts before a number, as (0, text) < (1, number) did
                else
                {
                    int c = string.CompareOrdinal(pa[i], pb[i]);
                    if (c != 0) return c;
                }
            }
            return pa.Length.CompareTo(pb.Length);
        }

        // ------------------------------------------------------------------ Auto Assign
        private static void LeaveAlone(PanelRow row, AssignSummary summary, string why)
        {
            // A row the user has already picked a template for keeps that pick and stays orange; a row nobody has touched goes red.
            if (row.Changed)
            {
                row.Status = "changed";
                row.Note = why + " - kept your pick";
                summary.Kept++;
            }
            else
            {
                row.Status = "review";
                row.Note = why;
                summary.Review++;
            }
        }

        /// <summary>
        /// Ways x phases, then the first template of that many slots. rows limits the run to a selection (null: every panel);
        /// preferConfig breaks a tie towards the panel configuration on screen.
        /// </summary>
        public static AssignSummary AutoAssign(ModelData data, Dictionary<string, string> settings, IEnumerable<PanelRow> rows = null, string preferConfig = null)
        {
            string waysParam = PstmCore.Get(settings, "ways_param");
            string phasesParam = PstmCore.Get(settings, "phases_param");
            string fallback = PstmCore.Get(settings, "phases_fallback");
            bool matchType = PstmCore.Get(settings, "match_schedule_type") == "1";

            // Match on the template's REAL slot count, not the number in its name (the name carries ways).
            var bySlots = new Dictionary<int, List<TemplateInfo>>();
            foreach (TemplateInfo tpl in data.Templates)
            {
                int size = tpl.Slots != 0 ? tpl.Slots : (tpl.Number ?? 0);
                if (size == 0) continue;
                List<TemplateInfo> list;
                if (!bySlots.TryGetValue(size, out list))
                {
                    list = new List<TemplateInfo>();
                    bySlots[size] = list;
                }
                list.Add(tpl);
            }

            var summary = new AssignSummary();
            foreach (PanelRow row in rows ?? data.Rows)
            {
                summary.Total++;
                if (row.Locked.Length > 0)
                {
                    summary.Locked++;
                    row.Status = "locked";
                    row.Note = "";
                    continue;
                }
                row.Note = "";
                row.CalcSlots = null;
                row.WaysText = waysParam.Length > 0 ? ReadParam(row.Element, row.Doc, waysParam) : "";
                row.PhasesText = phasesParam.Length > 0 ? ReadParam(row.Element, row.Doc, phasesParam) : "";

                int? phases = null;
                List<int> nums = PstmCore.NumbersIn(row.PhasesText);
                if (nums.Count > 0) phases = nums[0];
                else if (fallback.Length > 0)
                {
                    int f = PstmCore.AsInt(fallback, 0);
                    phases = f != 0 ? (int?)f : null;
                }

                string why;
                int? slots = PstmCore.CalcSlots(row.WaysText, phases, out why);
                if (slots == null)
                {
                    LeaveAlone(row, summary, why.Length > 0 ? why : "could not calculate");
                    continue;
                }
                row.CalcSlots = slots;
                List<TemplateInfo> found;
                List<TemplateInfo> candidates = bySlots.TryGetValue(slots.Value, out found) ? found.ToList() : new List<TemplateInfo>();
                if (candidates.Count == 0)
                {
                    LeaveAlone(row, summary, "no template of " + slots.Value + " slots");
                    continue;
                }

                // narrow only where narrowing still leaves something to pick
                if (matchType && row.CurrentId != 0)
                {
                    TemplateInfo current;
                    if (data.ById.TryGetValue(row.CurrentId, out current) && current.ScheduleType.Length > 0)
                    {
                        List<TemplateInfo> same = candidates.Where(c => c.ScheduleType == current.ScheduleType).ToList();
                        if (same.Count > 0) candidates = same;
                    }
                }
                if (!string.IsNullOrEmpty(preferConfig))
                {
                    List<TemplateInfo> same = candidates.Where(c => c.Config == preferConfig).ToList();
                    if (same.Count > 0) candidates = same;
                }

                TemplateInfo pick = candidates[0];   // the first one that fits, as asked
                row.SetChoice(pick.IdVal, pick.Name);
                int spare = candidates.Count - 1;
                string detail = slots.Value + " slots";
                if (spare > 0) detail += " - " + spare + " other" + (spare == 1 ? "" : "s") + " would also fit";
                if (row.Changed)
                {
                    row.Status = "changed";
                    row.Note = detail;
                    summary.Assigned++;
                }
                else
                {
                    row.Status = "";
                    row.Note = detail + " - already right";
                    summary.Already++;
                }
            }
            return summary;
        }
    }
}
