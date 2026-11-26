using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;

namespace RevoBIM.Tools.ContainmentSystemCreator
{
    /// <summary>One fitting parameter on a system type, e.g. 'Horizontal Bend'.</summary>
    public sealed class FittingSlot
    {
        public string Name;
        public Definition Definition;
        public FamilySymbol Symbol;
        public ElementId SymbolId;
        public Family Family;
        public string FamilyName, TypeName;

        public FittingSlot(Parameter param, FamilySymbol symbol)
        {
            Name = param.Definition.Name;
            Definition = param.Definition;
            Symbol = symbol;
            SymbolId = symbol.Id;
            Family = symbol.Family;
            FamilyName = CscModel.GetName(symbol.Family);
            TypeName = CscModel.GetName(symbol);
        }

        public string Label()
        {
            return FamilyName + " : " + TypeName;
        }
    }

    /// <summary>A cable tray / conduit system type and the fittings it points at.</summary>
    public sealed class SystemTypeInfo
    {
        public Document Doc;
        public ElementType EType;
        public ElementId Id;
        public string Name, FamilyName, Function, Mark, FunctionParamName, MarkParamName;
        public List<FittingSlot> Slots;
        public List<string> FittingFamilyNames = new List<string>();
        // filled in by TagKinds() once the whole set is known
        public Kind Kind;
        public string KindLabel = "";
        public string KindAlias;
        public string NameAlias;

        public SystemTypeInfo(Document doc, ElementType etype)
        {
            Doc = doc;
            EType = etype;
            Id = etype.Id;
            Name = CscModel.GetName(etype);
            try { FamilyName = etype.FamilyName ?? ""; } catch (Exception) { FamilyName = ""; }
            Parameter fn = CscModel.FindFunctionParam(etype);
            Parameter mk = CscModel.FindMarkParam(etype);
            Function = CscModel.ReadParamText(fn);
            Mark = CscModel.ReadParamText(mk);
            FunctionParamName = CscModel.ParamLabel(fn, "BGL_Function");
            MarkParamName = CscModel.ParamLabel(mk, "BGL_Type Mark");
            Slots = ReadSlots();
            var seen = new HashSet<string>();
            foreach (FittingSlot slot in Slots)
            {
                string key = slot.FamilyName.ToLowerInvariant();
                if (key.Length > 0 && seen.Add(key)) FittingFamilyNames.Add(slot.FamilyName);
            }
        }

        public bool HasFittings
        {
            get { return Slots.Count > 0 || (FamilyName ?? "").ToLowerInvariant().Contains("with fittings"); }
        }

        private List<FittingSlot> ReadSlots()
        {
            var slots = new List<FittingSlot>();
            foreach (Parameter param in EType.Parameters)
            {
                ElementId eid;
                try
                {
                    if (param.StorageType != StorageType.ElementId) continue;
                    eid = param.AsElementId();
                }
                catch (Exception)
                {
                    continue;
                }
                if (eid == null || eid == ElementId.InvalidElementId) continue;
                Element elem = Doc.GetElement(eid);
                if (!CscModel.IsFittingSymbol(elem)) continue;
                try
                {
                    slots.Add(new FittingSlot(param, (FamilySymbol)elem));
                }
                catch (Exception)
                {
                }
            }
            slots.Sort((a, b) => string.CompareOrdinal(a.Name.ToLowerInvariant(), b.Name.ToLowerInvariant()));
            return slots;
        }

        public string SearchBlob()
        {
            var bits = new List<string> { Name, FamilyName, Function, Mark, KindLabel };
            foreach (FittingSlot s in Slots)
            {
                bits.Add(s.Name);
                bits.Add(s.FamilyName);
                bits.Add(s.TypeName);
            }
            return string.Join(" ", bits).ToLowerInvariant();
        }
    }

    public sealed class PlanItem
    {
        public FittingSlot Slot;
        public string NewTypeName;
        public FamilySymbol ExistingSymbol;   // not null: reuse, do not duplicate

        public bool Reused
        {
            get { return ExistingSymbol != null; }
        }
    }

    public sealed class Plan
    {
        public SystemTypeInfo Source;
        public string NewTypeName = "", SuggestedTypeName = "", Function = "", Mark = "";
        public bool ParamsOnFittings = true;
        public List<PlanItem> Items = new List<PlanItem>();
        public List<string> Errors = new List<string>();
        public List<string> Notes = new List<string>();
    }

    public sealed class RenameItem
    {
        public Element Element;
        public string SlotName, OldName, NewName, Note;

        public bool Changes
        {
            get { return !string.IsNullOrEmpty(NewName) && NewName != OldName; }
        }
    }

    public sealed class EditPlan
    {
        public SystemTypeInfo Info;
        public string Prefix = "", Sep = "_", OldToken = "", NewToken = "", NewFullName = "", Function = "", Mark = "";
        public string FunctionParamName = "", MarkParamName = "";
        public bool RenameFittings = true, ParamsOnFittings = true;
        public List<RenameItem> Renames = new List<RenameItem>();
        public List<KeyValuePair<string, Element>> ParamTargets = new List<KeyValuePair<string, Element>>();
        public List<string> Errors = new List<string>();
        public List<string> Notes = new List<string>();

        public List<RenameItem> Renaming
        {
            get { return Renames.Where(r => r.Changes).ToList(); }
        }
    }

    /// <summary>Containment System Creator - reading the model, planning and executing (the second half of script.py).</summary>
    public static class CscModel
    {
        public static string GetName(Element elem)
        {
            if (elem == null) return "";
            try
            {
                return elem.Name ?? "";
            }
            catch (Exception)
            {
                return "";
            }
        }

        private static HashSet<long> fittingCategoryIds;

        public static void ResetCategories(Document doc)
        {
            fittingCategoryIds = new HashSet<long>();
            foreach (BuiltInCategory bic in new[] { BuiltInCategory.OST_CableTrayFitting, BuiltInCategory.OST_ConduitFitting })
            {
                try
                {
                    Category cat = Category.GetCategory(doc, bic);
                    if (cat != null) fittingCategoryIds.Add(cat.Id.Value);
                }
                catch (Exception)
                {
                }
            }
        }

        public static bool IsFittingSymbol(Element elem)
        {
            var symbol = elem as FamilySymbol;
            if (symbol == null) return false;
            Category cat = symbol.Category;
            if (cat == null) return false;
            try
            {
                if (fittingCategoryIds != null && fittingCategoryIds.Contains(cat.Id.Value)) return true;
            }
            catch (Exception)
            {
            }
            try
            {
                return cat.Name.ToLowerInvariant().Contains("fitting");
            }
            catch (Exception)
            {
                return false;
            }
        }

        // ------------------------------------------------------------------ parameter helpers
        /// <summary>BGL_Function, or the closest thing to it on this element.</summary>
        public static Parameter FindFunctionParam(Element elem)
        {
            Parameter param = elem.LookupParameter("BGL_Function");
            if (param != null) return param;
            Parameter best = null;
            foreach (Parameter p in elem.Parameters)
            {
                string pname;
                try { pname = p.Definition.Name; } catch (Exception) { continue; }
                string low = pname.ToLowerInvariant();
                if (!low.Contains("function")) continue;
                if (p.IsReadOnly) continue;
                if (low.StartsWith("bgl", StringComparison.Ordinal)) return p;
                if (best == null) best = p;
            }
            return best;
        }

        /// <summary>The project's own type mark parameter (BGL_Type Mark), falling back to Revit's.</summary>
        public static Parameter FindMarkParam(Element elem)
        {
            foreach (string pname in CscCore.MarkParamNames)
            {
                Parameter param = elem.LookupParameter(pname);
                if (param != null && !param.IsReadOnly) return param;
            }
            foreach (Parameter param in elem.Parameters)
            {
                string n;
                try { n = CscCore.Norm(param.Definition.Name); } catch (Exception) { continue; }
                if (n.StartsWith("bgl", StringComparison.Ordinal) && n.Contains("typemark") && !param.IsReadOnly) return param;
            }
            try
            {
                Parameter param = elem.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_MARK);
                if (param != null) return param;
            }
            catch (Exception)
            {
            }
            return elem.LookupParameter("Type Mark");
        }

        public static string ParamLabel(Parameter param, string fallback = "(not found)")
        {
            if (param == null) return fallback;
            try
            {
                return param.Definition.Name;
            }
            catch (Exception)
            {
                return fallback;
            }
        }

        /// <summary>Renames an element, confirmed by reading the name back rather than trusting that no exception means success.</summary>
        public static bool SetElementName(Element elem, string newName)
        {
            try
            {
                elem.Name = newName;
            }
            catch (Exception)
            {
            }
            return GetName(elem) == newName;
        }

        public static string ReadParamText(Parameter param)
        {
            if (param == null) return "";
            try
            {
                if (param.StorageType == StorageType.String) return param.AsString() ?? "";
                return param.AsValueString() ?? "";
            }
            catch (Exception)
            {
                return "";
            }
        }

        /// <summary>Best-effort write of a string onto a parameter. True on success.</summary>
        public static bool WriteParamText(Parameter param, string value)
        {
            if (param == null || param.IsReadOnly) return false;
            try
            {
                switch (param.StorageType)
                {
                    case StorageType.String:
                        param.Set(value ?? "");
                        return true;
                    case StorageType.Integer:
                        param.Set(int.Parse(value, CultureInfo.InvariantCulture));
                        return true;
                    case StorageType.Double:
                        param.Set(double.Parse(value, CultureInfo.InvariantCulture));
                        return true;
                }
            }
            catch (Exception)
            {
                return false;
            }
            return false;
        }

        /// <summary>Locates the same parameter on another element.</summary>
        public static Parameter FindParamLike(Element elem, Definition definition, string pname)
        {
            try
            {
                Parameter param = elem.get_Parameter(definition);
                if (param != null) return param;
            }
            catch (Exception)
            {
            }
            foreach (Parameter p in elem.Parameters)
            {
                try
                {
                    if (p.Definition != null && p.Definition.Name == pname) return p;
                }
                catch (Exception)
                {
                }
            }
            return null;
        }

        // ------------------------------------------------------------------ model reading
        /// <summary>
        /// Every 'with fittings' system type of a class, tagged with its kind. A type counts if it actually has fitting types
        /// assigned (the real test) or its family name says so.
        /// </summary>
        public static List<SystemTypeInfo> CollectSystemTypes(Document doc, Type cls, List<Kind> kinds)
        {
            var found = new List<SystemTypeInfo>();
            foreach (Element e in new FilteredElementCollector(doc).OfClass(cls).ToElements())
            {
                var info = new SystemTypeInfo(doc, (ElementType)e);
                if (info.HasFittings) found.Add(info);
            }
            found.Sort((a, b) => string.CompareOrdinal(a.Name.ToLowerInvariant(), b.Name.ToLowerInvariant()));
            TagKinds(found, kinds);
            return found;
        }

        public static void TagKinds(List<SystemTypeInfo> infos, List<Kind> kinds)
        {
            foreach (SystemTypeInfo info in infos)
            {
                string alias, nameAlias;
                Kind kind = CscCore.AssignKind(info.Name, info.FamilyName, info.FittingFamilyNames, kinds, out alias, out nameAlias);
                info.Kind = kind;
                info.KindLabel = kind != null ? kind.Label : "";
                info.KindAlias = alias;
                info.NameAlias = nameAlias;
            }
        }

        /// <summary>The kinds that actually have types behind them, in declared order, with counts and the unmatched count.</summary>
        public static List<Kind> KindsPresent(List<SystemTypeInfo> infos, List<Kind> kinds, out Dictionary<string, int> counts, out int unassigned)
        {
            counts = new Dictionary<string, int>();
            foreach (SystemTypeInfo info in infos)
            {
                if (info.Kind == null) continue;
                int c;
                counts.TryGetValue(info.Kind.Label, out c);
                counts[info.Kind.Label] = c + 1;
            }
            var local = counts;
            unassigned = infos.Count(i => i.Kind == null);
            return kinds.Where(k => local.ContainsKey(k.Label) && local[k.Label] > 0).ToList();
        }

        public static List<SystemTypeInfo> TypesForKind(List<SystemTypeInfo> infos, Kind kind)
        {
            if (kind == null) return infos.ToList();
            return infos.Where(i => i.Kind != null && i.Kind.Label == kind.Label).ToList();
        }

        public static HashSet<string> ExistingSystemTypeNames(Document doc, Type cls)
        {
            var names = new HashSet<string>();
            foreach (Element e in new FilteredElementCollector(doc).OfClass(cls).ToElements()) names.Add(GetName(e));
            return names;
        }

        /// <summary>{type name: FamilySymbol} for one family.</summary>
        public static Dictionary<string, FamilySymbol> FamilyTypeMap(Document doc, Family family)
        {
            var map = new Dictionary<string, FamilySymbol>();
            try
            {
                foreach (ElementId sid in family.GetFamilySymbolIds())
                {
                    var sym = doc.GetElement(sid) as FamilySymbol;
                    if (sym != null) map[GetName(sym)] = sym;
                }
            }
            catch (Exception)
            {
            }
            return map;
        }

        // ------------------------------------------------------------------ the plan
        public static Plan BuildPlan(Document doc, Type cls, SystemTypeInfo source, int autoDepth, string newName, string functionValue,
                                     string markValue, string scheme, bool paramsOnFittings, HashSet<string> existingNames = null,
                                     string fullNameOverride = null)
        {
            if (existingNames == null) existingNames = ExistingSystemTypeNames(doc, cls);
            var plan = new Plan { Source = source, Function = functionValue, Mark = markValue, ParamsOnFittings = paramsOnFittings };

            newName = (newName ?? "").Trim();
            if (newName.Length == 0)
            {
                plan.Errors.Add("Enter a name for the new service type.");
                return plan;
            }
            if (CscCore.BadName.IsMatch(newName))
            {
                plan.Errors.Add("The name contains a character Revit will not accept.");
                return plan;
            }
            if (source == null)
            {
                plan.Errors.Add("No source type available for this kind.");
                return plan;
            }

            string prefix, sep;
            CscCore.PrefixAndSep(source.Name, source.NameAlias, autoDepth, out prefix, out sep);
            plan.SuggestedTypeName = CscCore.SuggestTypeName(source.Name, source.NameAlias, source.KindAlias, autoDepth, newName);
            string over = (fullNameOverride ?? "").Trim();
            plan.NewTypeName = over.Length > 0 ? over : plan.SuggestedTypeName;

            if (CscCore.BadName.IsMatch(plan.NewTypeName))
            {
                plan.Errors.Add("The full type name contains a character Revit will not accept.");
                return plan;
            }
            if (existingNames.Contains(plan.NewTypeName))
                plan.Errors.Add("A type called \"" + plan.NewTypeName + "\" already exists.");

            string oldToken = CscCore.ServiceToken(source.Name, prefix, sep);
            var seenSymbols = new HashSet<long>();
            foreach (FittingSlot slot in source.Slots)
            {
                long key = slot.SymbolId.Value;
                if (!seenSymbols.Add(key)) continue;
                string target;
                if (scheme == "name") target = newName;
                else if (scheme == "swap")
                {
                    string swapped = CscCore.LooseReplace(slot.TypeName, oldToken, newName);
                    target = !string.IsNullOrEmpty(swapped) ? swapped : newName;
                }
                else target = plan.NewTypeName;

                Dictionary<string, FamilySymbol> existing = FamilyTypeMap(doc, slot.Family);
                FamilySymbol clash;
                existing.TryGetValue(target, out clash);
                if (clash != null && clash.Id == slot.SymbolId)
                {
                    plan.Errors.Add("Fitting \"" + target + "\" would be renamed onto itself in family \"" + slot.FamilyName + "\".");
                    clash = null;
                }
                plan.Items.Add(new PlanItem { Slot = slot, NewTypeName = target, ExistingSymbol = clash });
            }
            if (plan.Items.Count == 0)
                plan.Errors.Add("This type has no fitting types assigned, so there is nothing to duplicate alongside it.");
            int reused = plan.Items.Count(i => i.Reused);
            if (reused > 0)
                plan.Notes.Add(reused + " fitting type(s) of that name already exist and will be reused rather than duplicated.");
            return plan;
        }

        /// <summary>Runs the plan inside one transaction. Returns (ok, log lines).</summary>
        public static bool ExecutePlan(Document doc, Plan plan, out List<string> log)
        {
            log = new List<string>();
            using (var trans = new Transaction(doc, "RevoBIM: Create Containment System"))
            {
                trans.Start();
                try
                {
                    var newType = plan.Source.EType.Duplicate(plan.NewTypeName);
                    log.Add("System type");
                    log.Add("    " + plan.Source.Name);
                    log.Add("      -> " + GetName(newType));
                    if (!WriteParamText(FindFunctionParam(newType), plan.Function))
                        log.Add("      ! BGL_Function could not be written (parameter missing or read-only)");
                    if (!WriteParamText(FindMarkParam(newType), plan.Mark))
                        log.Add("      ! Type Mark could not be written");
                    log.Add("");
                    log.Add("Fittings");

                    int created = 0, reused = 0;
                    var symbolBySource = new Dictionary<long, FamilySymbol>();
                    foreach (PlanItem item in plan.Items)
                    {
                        FittingSlot slot = item.Slot;
                        long key = slot.SymbolId.Value;
                        FamilySymbol newSymbol;
                        if (symbolBySource.TryGetValue(key, out newSymbol))
                        {
                        }
                        else if (item.Reused)
                        {
                            newSymbol = item.ExistingSymbol;
                            symbolBySource[key] = newSymbol;
                            reused++;
                            log.Add("    " + slot.Name);
                            log.Add("      = " + slot.FamilyName + " : " + item.NewTypeName + "   (existing type reused)");
                        }
                        else
                        {
                            newSymbol = (FamilySymbol)slot.Symbol.Duplicate(item.NewTypeName);
                            symbolBySource[key] = newSymbol;
                            created++;
                            log.Add("    " + slot.Name);
                            log.Add("      " + slot.FamilyName + " : " + slot.TypeName);
                            log.Add("        -> " + slot.FamilyName + " : " + GetName(newSymbol));
                            if (plan.ParamsOnFittings)
                            {
                                bool okFn = WriteParamText(FindFunctionParam(newSymbol), plan.Function);
                                bool okMk = WriteParamText(FindMarkParam(newSymbol), plan.Mark);
                                if (!okFn) log.Add("        ! BGL_Function not written");
                                if (!okMk) log.Add("        ! Type Mark not written");
                            }
                        }
                        Parameter target = FindParamLike(newType, slot.Definition, slot.Name);
                        if (target == null || target.IsReadOnly)
                            log.Add("        ! could not assign this fitting back onto the new system type");
                        else target.Set(newSymbol.Id);
                    }
                    foreach (FamilySymbol symbol in symbolBySource.Values)
                    {
                        try
                        {
                            if (!symbol.IsActive) symbol.Activate();
                        }
                        catch (Exception)
                        {
                        }
                    }
                    doc.Regenerate();
                    trans.Commit();
                    log.Add("");
                    log.Add(created + " fitting type(s) created, " + reused + " reused, all assigned to " + plan.NewTypeName + ".");
                    return true;
                }
                catch (Exception err)
                {
                    if (trans.HasStarted()) trans.RollBack();
                    log = new List<string> { "Nothing was created - the whole operation was rolled back.", "", err.Message };
                    return false;
                }
            }
        }

        // ------------------------------------------------------------------ editing an existing system
        /// <summary>True if name is free within family, ignoring the element itself.</summary>
        public static bool UniqueInFamily(Document doc, Family family, string name, ElementId keepId)
        {
            foreach (var entry in FamilyTypeMap(doc, family))
            {
                if (entry.Key != name) continue;
                if (entry.Value.Id == keepId) continue;
                return false;
            }
            return true;
        }

        public static EditPlan BuildEditPlan(Document doc, Type cls, SystemTypeInfo info, int autoDepth, string newToken, string functionValue,
                                             string markValue, bool renameFittings, bool paramsOnFittings, HashSet<string> existingNames = null)
        {
            var plan = new EditPlan { Info = info, Function = functionValue, Mark = markValue, RenameFittings = renameFittings, ParamsOnFittings = paramsOnFittings };
            if (info == null)
            {
                plan.Errors.Add("Select a system type first.");
                return plan;
            }
            plan.FunctionParamName = ParamLabel(FindFunctionParam(info.EType), "BGL_Function (not on this type)");
            plan.MarkParamName = ParamLabel(FindMarkParam(info.EType), "BGL_Type Mark (not on this type)");

            string prefix, sep;
            CscCore.EditSplit(info.Name, info.NameAlias, autoDepth, out prefix, out sep);
            plan.Prefix = prefix;
            plan.Sep = sep;
            plan.OldToken = CscCore.ServiceToken(info.Name, prefix, sep);

            newToken = (newToken ?? "").Trim();
            plan.NewToken = newToken;
            if (newToken.Length == 0)
            {
                plan.Errors.Add("The type name cannot be empty.");
                return plan;
            }
            if (CscCore.BadName.IsMatch(newToken))
            {
                plan.Errors.Add("The name contains a character Revit will not accept.");
                return plan;
            }
            plan.NewFullName = prefix.Length > 0 ? prefix + sep + newToken : newToken;
            if (existingNames == null) existingNames = ExistingSystemTypeNames(doc, cls);
            if (plan.NewFullName != info.Name && existingNames.Contains(plan.NewFullName))
                plan.Errors.Add("A type called \"" + plan.NewFullName + "\" already exists.");

            plan.Renames.Add(new RenameItem { Element = info.EType, SlotName = "System type", OldName = info.Name, NewName = plan.NewFullName, Note = "" });
            plan.ParamTargets.Add(new KeyValuePair<string, Element>("System type  " + info.Name, info.EType));

            var seen = new HashSet<long>();
            foreach (FittingSlot slot in info.Slots)
            {
                long key = slot.SymbolId.Value;
                if (!seen.Add(key)) continue;
                string target = null;
                string note = "";
                if (CscCore.Norm(slot.TypeName) == CscCore.Norm(info.Name)) target = plan.NewFullName;
                else
                {
                    string swapped = CscCore.LooseReplace(slot.TypeName, plan.OldToken, newToken);
                    if (!string.IsNullOrEmpty(swapped)) target = swapped;
                    else note = "does not carry the service name - left as it is";
                }
                if (!string.IsNullOrEmpty(target) && target != slot.TypeName)
                {
                    if (!UniqueInFamily(doc, slot.Family, target, slot.SymbolId))
                    {
                        note = "\"" + target + "\" already exists in this family - left as it is";
                        target = null;
                    }
                }
                plan.Renames.Add(new RenameItem { Element = slot.Symbol, SlotName = slot.Name, OldName = slot.TypeName, NewName = target, Note = note });
                plan.ParamTargets.Add(new KeyValuePair<string, Element>(slot.Name + "  " + slot.FamilyName + " : " + slot.TypeName, slot.Symbol));
            }
            if (!renameFittings) plan.Renames = plan.Renames.Take(1).ToList();
            if (!paramsOnFittings) plan.ParamTargets = plan.ParamTargets.Take(1).ToList();
            int skipped = plan.Renames.Count(r => !string.IsNullOrEmpty(r.Note));
            if (skipped > 0) plan.Notes.Add(skipped + " fitting type(s) will not be renamed - see the list above.");
            return plan;
        }

        /// <summary>Applies an edit plan inside one transaction. Returns (ok, log lines).</summary>
        public static bool ExecuteEdit(Document doc, EditPlan plan, out List<string> log)
        {
            log = new List<string>();
            using (var trans = new Transaction(doc, "RevoBIM: Edit Containment System"))
            {
                trans.Start();
                try
                {
                    int renamed = 0;
                    log.Add("Renamed");
                    foreach (RenameItem item in plan.Renames)
                    {
                        if (!item.Changes)
                        {
                            if (!string.IsNullOrEmpty(item.Note))
                            {
                                log.Add("    " + item.SlotName);
                                log.Add("      " + item.OldName + "   ! " + item.Note);
                            }
                            continue;
                        }
                        if (SetElementName(item.Element, item.NewName))
                        {
                            renamed++;
                            log.Add("    " + item.SlotName);
                            log.Add("      " + item.OldName);
                            log.Add("        -> " + item.NewName);
                        }
                        else
                        {
                            log.Add("    " + item.SlotName);
                            log.Add("      ! could not rename " + item.OldName);
                        }
                    }
                    if (renamed == 0) log.Add("    (nothing to rename)");

                    log.Add("");
                    log.Add("Parameters");
                    log.Add("    " + plan.FunctionParamName + " = " + plan.Function);
                    log.Add("    " + plan.MarkParamName + " = " + plan.Mark);
                    log.Add("");

                    int written = 0;
                    foreach (var target in plan.ParamTargets)
                    {
                        var problems = new List<string>();
                        var notes = new List<string>();
                        Parameter fn = FindFunctionParam(target.Value);
                        if (!WriteParamText(fn, plan.Function)) problems.Add("BGL_Function");
                        else if (ParamLabel(fn) != plan.FunctionParamName) notes.Add("function written to " + ParamLabel(fn));
                        Parameter mk = FindMarkParam(target.Value);
                        if (!WriteParamText(mk, plan.Mark)) problems.Add("type mark");
                        else if (ParamLabel(mk) != plan.MarkParamName) notes.Add("mark written to " + ParamLabel(mk));   // e.g. the fittings carry Revit's Type Mark
                        if (problems.Count > 0 || notes.Count > 0)
                        {
                            log.Add("    " + target.Key);
                            foreach (string note in notes) log.Add("      -  " + note);
                            if (problems.Count > 0) log.Add("      !  could not write " + string.Join(" and ", problems));
                        }
                        if (problems.Count == 0) written++;
                    }
                    log.Add("    " + written + " of " + plan.ParamTargets.Count + " element(s) took both values.");
                    doc.Regenerate();
                    trans.Commit();
                    log.Add("");
                    log.Add(renamed + " type(s) renamed, " + plan.ParamTargets.Count + " type(s) updated.");
                    return true;
                }
                catch (Exception err)
                {
                    if (trans.HasStarted()) trans.RollBack();
                    log = new List<string> { "Nothing was changed - the whole operation was rolled back.", "", err.Message };
                    return false;
                }
            }
        }
    }

    /// <summary>The debug log: opens with a build line, then one line per step (the pyRevit tool kept no log).</summary>
    public static class CscLog
    {
        private static bool started;

        public static string Dir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }

        public static string LogPath()
        {
            return Path.Combine(Dir(), CscCore.ToolKey + "_debug.txt");
        }

        public static string ErrorPath()
        {
            return Path.Combine(Dir(), CscCore.ToolKey + "_last_error.txt");
        }

        public static string BuildInfo()
        {
            return CscCore.ToolName + " v" + CscCore.Version + ", build " + typeof(CscLog).Assembly.GetName().Version;
        }

        public static void Write(string text)
        {
            try
            {
                Directory.CreateDirectory(Dir());
                var sb = new StringBuilder();
                if (!started)
                {
                    started = true;
                    sb.Append("---- ").Append(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture)).Append("  ").Append(BuildInfo()).Append('\n');
                }
                sb.Append(DateTime.Now.ToString("HH:mm:ss", CultureInfo.InvariantCulture)).Append(' ').Append(text).Append('\n');
                File.AppendAllText(LogPath(), sb.ToString(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }
    }
}
