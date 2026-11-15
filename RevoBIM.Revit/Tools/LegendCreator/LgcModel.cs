using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Mechanical;
using Autodesk.Revit.DB.Plumbing;
using static RevoBIM.Tools.LegendCreator.LgcCore;
using static RevoBIM.Tools.LegendCreator.LgcLogic;

namespace RevoBIM.Tools.LegendCreator
{
    /// <summary>A model category plus the type ids of that category actually placed.</summary>
    public sealed class CategoryInfo
    {
        public CategoryInfo(Category category, List<ElementId> typeIds)
        {
            Category = category;
            Name = category.Name;
            TypeIds = typeIds;
        }

        public Category Category { get; }
        public string Name { get; }
        public List<ElementId> TypeIds { get; }
        public int Count => TypeIds.Count;
    }

    /// <summary>One legend row: where it came from, its label and its colour.</summary>
    public sealed class LegendEntry
    {
        public LegendEntry(ElementId sourceId, string sourceName, string label,
                           (int R, int G, int B)? colour, ElementId patternId)
        {
            SourceId = sourceId;
            SourceName = sourceName;
            Label = label;
            Colour = colour;
            PatternId = patternId;
            Key = label;
            Group = "";
        }

        public ElementId SourceId { get; }
        public string SourceName { get; }
        public string Label { get; }
        public (int R, int G, int B)? Colour { get; }
        public ElementId PatternId { get; }
        public string Key { get; set; }   // what a line style is named after
        public string Group { get; set; } // classification, where one applies
        public string HexColour => RgbHex(Colour);
    }

    /// <summary>
    /// Legend Creator - reading the model. Element helpers, the family scan,
    /// phases, text types, seed legends, view template filters and the duct and
    /// pipe systems in use. Nothing here writes. Port of lgc_model.py.
    /// </summary>
    public sealed class LgcModel
    {
        private readonly Document doc;

        public LgcModel(Document document)
        {
            doc = document;
        }

        public Document Doc => doc;

        public static long Eid(ElementId id) => id == null ? 0 : id.Value;

        public static string ElementName(Element element)
        {
            if (element == null) return "";
            try
            {
                return element.Name ?? "";
            }
            catch (Exception err)
            {
                Swallowed(err);
                return "";
            }
        }

        public static string FamilyName(Element elementType)
        {
            try
            {
                return (elementType as ElementType)?.FamilyName ?? "";
            }
            catch (Exception err)
            {
                Swallowed(err);
                return "";
            }
        }

        public static string FamilyTypeLabel(Element elementType)
        {
            return string.Join(" : ", new[] { FamilyName(elementType), ElementName(elementType) }
                                          .Where(p => !string.IsNullOrEmpty(p)));
        }

        /// <summary>Read the nominated parameter off a type, with sensible fallbacks.</summary>
        public static string ParamText(Element elementType, string paramName)
        {
            if (paramName == NameTypeName) return ElementName(elementType);
            if (paramName == NameFamilyType) return FamilyTypeLabel(elementType);

            Parameter param = null;
            try
            {
                param = elementType.LookupParameter(paramName);
            }
            catch (Exception err)
            {
                Swallowed(err);
            }

            if (param == null && paramName == DefaultNameParam)
            {
                try
                {
                    param = elementType.get_Parameter(BuiltInParameter.ALL_MODEL_DESCRIPTION);
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }

            if (param != null && param.HasValue)
            {
                string value = null;
                try
                {
                    value = param.StorageType == StorageType.String ? param.AsString() : param.AsValueString();
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
                if (!string.IsNullOrWhiteSpace(value)) return value.Trim();
            }

            return FamilyTypeLabel(elementType);
        }

        /// <summary>Category id values for the names this Revit has; absent names are skipped.</summary>
        public static HashSet<long> CategoryIdSet(IEnumerable<string> names)
        {
            var ids = new HashSet<long>();
            foreach (string name in names)
                if (Enum.TryParse(name, out BuiltInCategory builtin))
                    ids.Add((long)(int)builtin);
            return ids;
        }

        // -----------------------------------------------------------------
        // Model interrogation
        // -----------------------------------------------------------------
        /// <summary>(name, id) for every phase, in project order.</summary>
        public List<(string Name, ElementId Id)> ProjectPhases()
        {
            var phases = new List<(string, ElementId)>();
            try
            {
                foreach (Phase phase in doc.Phases)
                    phases.Add((ElementName(phase), phase.Id));
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            return phases;
        }

        private static ElementId ElementPhaseId(Element element)
        {
            Parameter param;
            try
            {
                param = element.get_Parameter(BuiltInParameter.PHASE_CREATED);
            }
            catch (Exception err)
            {
                Swallowed(err);
                return null;
            }
            if (param == null || !param.HasValue) return null;
            try
            {
                return param.AsElementId();
            }
            catch (Exception err)
            {
                Swallowed(err);
                return null;
            }
        }

        /// <summary>
        /// CategoryInfo for every usable model category in use. phaseId null
        /// means every phase; otherwise only elements whose Phase Created
        /// matches - an element with no phase at all is left out.
        /// </summary>
        public List<CategoryInfo> CollectUsedTypes(ElementId phaseId)
        {
            var buckets = new Dictionary<long, (Category Cat, List<ElementId> Ids)>();
            var seen = new HashSet<long>();
            var blocked = CategoryIdSet(BlockedCategories);
            long? rawPhase = phaseId != null ? Eid(phaseId) : (long?)null;
            long? wantPhase = UsablePhase(rawPhase);
            if (phaseId != null && wantPhase == null)
                Log(string.Format(Inv, "phase id unreadable ({0}) - listing every phase instead", rawPhase));
            int scanned = 0, noPhase = 0, otherPhase = 0;

            var collector = new FilteredElementCollector(doc)
                .WhereElementIsNotElementType()
                .WhereElementIsViewIndependent();

            foreach (Element element in collector)
            {
                scanned++;
                if (wantPhase != null)
                {
                    ElementId onPhase = ElementPhaseId(element);
                    string verdict = PhaseVerdict(wantPhase, onPhase != null ? Eid(onPhase) : (long?)null);
                    if (verdict == "no phase") { noPhase++; continue; }
                    if (verdict == "other phase") { otherPhase++; continue; }
                }

                ElementId typeId;
                try
                {
                    typeId = element.GetTypeId();
                }
                catch (Exception err)
                {
                    Swallowed(err);
                    continue;
                }
                if (typeId == null || typeId == ElementId.InvalidElementId) continue;

                long key = Eid(typeId);
                if (!seen.Add(key)) continue;

                Element elementType = doc.GetElement(typeId);
                Category category = elementType?.Category;
                if (category == null || category.CategoryType != CategoryType.Model) continue;

                long catKey = Eid(category.Id);
                if (catKey >= 0) continue;           // subcategory or non built-in
                if (blocked.Contains(catKey)) continue; // cannot be a legend component

                if (!buckets.TryGetValue(catKey, out var bucket))
                {
                    bucket = (category, new List<ElementId>());
                    buckets[catKey] = bucket;
                }
                bucket.Ids.Add(typeId);
            }

            var infos = new List<CategoryInfo>();
            foreach (var bucket in buckets.Values)
            {
                var ids = bucket.Ids
                    .OrderBy(i => FamilyName(doc.GetElement(i)).ToLowerInvariant(), StringComparer.Ordinal)
                    .ThenBy(i => ElementName(doc.GetElement(i)).ToLowerInvariant(), StringComparer.Ordinal)
                    .ToList();
                infos.Add(new CategoryInfo(bucket.Cat, ids));
            }

            Log(string.Format(Inv,
                "family scan (phase id {0}): {1} element(s) read, {2} with no phase, {3} on another phase " +
                "-> {4} type(s) in {5} categor(ies)",
                wantPhase?.ToString(Inv) ?? "all", scanned, noPhase, otherPhase,
                infos.Sum(i => i.Count), infos.Count));
            return infos.OrderBy(i => i.Name.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        /// <summary>Parameter names worth offering as the description source, sampled.</summary>
        public List<string> StringParameterNames(IEnumerable<CategoryInfo> infos, int limit = 400)
        {
            var names = new HashSet<string>();
            int sampled = 0;
            foreach (var info in infos)
            {
                foreach (ElementId typeId in info.TypeIds)
                {
                    if (sampled >= limit) break;
                    Element elementType = doc.GetElement(typeId);
                    if (elementType == null) continue;
                    sampled++;
                    ParameterSet parameters;
                    try
                    {
                        parameters = elementType.Parameters;
                    }
                    catch (Exception err)
                    {
                        Swallowed(err);
                        continue;
                    }
                    foreach (Parameter param in parameters)
                    {
                        try
                        {
                            if (param.StorageType != StorageType.String) continue;
                            if (param.Definition == null) continue;
                            names.Add(param.Definition.Name);
                        }
                        catch (Exception err)
                        {
                            Swallowed(err);
                        }
                    }
                }
            }
            return names.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        /// <summary>(name, id) for every text note type, sorted.</summary>
        public List<(string Name, ElementId Id)> TextNoteTypes()
        {
            return new FilteredElementCollector(doc).OfClass(typeof(TextNoteType))
                .Select(t => (ElementName(t), t.Id))
                .OrderBy(t => t.Item1.ToLowerInvariant(), StringComparer.Ordinal)
                .ToList();
        }

        public ElementId DefaultTextTypeId()
        {
            try
            {
                ElementId typeId = doc.GetDefaultElementTypeId(ElementTypeGroup.TextNoteType);
                if (typeId != null && typeId != ElementId.InvalidElementId) return typeId;
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            return new FilteredElementCollector(doc).OfClass(typeof(TextNoteType)).FirstElementId();
        }

        /// <summary>Any legend view - the system tab only needs somewhere to draw.</summary>
        public View FindSeedLegendView()
        {
            foreach (View view in new FilteredElementCollector(doc).OfClass(typeof(View)))
            {
                try
                {
                    if (view.ViewType == ViewType.Legend && !view.IsTemplate) return view;
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }
            return null;
        }

        /// <summary>A legend view and a legend component inside it, to clone from.</summary>
        public (View View, Element Component) FindSeedLegend()
        {
            var components = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_LegendComponents)
                .WhereElementIsNotElementType()
                .ToElements();
            foreach (Element component in components)
            {
                if (doc.GetElement(component.OwnerViewId) is View view && view.ViewType == ViewType.Legend)
                    return (view, component);
            }
            return (null, null);
        }

        public HashSet<string> TakenViewNames()
        {
            return new HashSet<string>(new FilteredElementCollector(doc).OfClass(typeof(View))
                                           .Select(ElementName));
        }

        // -----------------------------------------------------------------
        // System Colour Legend - reading filters out of a view template
        // -----------------------------------------------------------------
        /// <summary>(name, View) for every view template, sorted by name.</summary>
        public List<(string Name, View View)> ViewTemplates()
        {
            var found = new List<(string, View)>();
            foreach (View view in new FilteredElementCollector(doc).OfClass(typeof(View)))
            {
                try
                {
                    if (view.IsTemplate) found.Add((ElementName(view), view));
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }
            return found.OrderBy(t => t.Item1.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        private static HashSet<long> FilterCategoryIds(Element filterElement)
        {
            var ids = new HashSet<long>();
            try
            {
                if (filterElement is ParameterFilterElement pfe)
                    foreach (ElementId catId in pfe.GetCategories())
                        ids.Add(Eid(catId));
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            return ids;
        }

        /// <summary>The string values a filter's rules test for, walking nested filters.</summary>
        private static List<string> RuleValues(Element filterElement)
        {
            var values = new List<string>();

            void Take(FilterRule rule)
            {
                string text = null;
                switch (rule)
                {
                    case FilterStringRule s: text = s.RuleString; break;
                    case FilterIntegerRule i: text = i.RuleValue.ToString(Inv); break;
                    case FilterDoubleRule d: text = PyFloat(d.RuleValue); break;
                    case FilterElementIdRule e: text = e.RuleValue?.ToString(); break;
                }
                text = text?.Trim();
                if (!string.IsNullOrEmpty(text) && !values.Contains(text)) values.Add(text);
            }

            void Walk(ElementFilter filter, int depth)
            {
                if (filter == null || depth > 6) return;
                try
                {
                    if (filter is ElementParameterFilter epf)
                        foreach (FilterRule rule in epf.GetRules()) Take(rule);
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
                try
                {
                    if (filter is ElementLogicalFilter logical)
                        foreach (ElementFilter child in logical.GetFilters()) Walk(child, depth + 1);
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }

            try
            {
                if (filterElement is ParameterFilterElement pfe) Walk(pfe.GetElementFilter(), 0);
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            return values;
        }

        private static (int, int, int)? ColourOf(Color colour)
        {
            if (colour == null || !colour.IsValid) return null;
            return (colour.Red, colour.Green, colour.Blue);
        }

        /// <summary>The colour a filter paints with, preferring the surface fill.</summary>
        private static (int R, int G, int B)? OverrideColour(OverrideGraphicSettings overrides)
        {
            var getters = new Func<Color>[]
            {
                () => overrides.SurfaceForegroundPatternColor,
                () => overrides.CutForegroundPatternColor,
                () => overrides.SurfaceBackgroundPatternColor,
                () => overrides.ProjectionLineColor,
                () => overrides.CutLineColor,
            };
            foreach (var get in getters)
            {
                try
                {
                    var found = ColourOf(get());
                    if (found != null) return found;
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }
            return null;
        }

        private static ElementId OverridePattern(OverrideGraphicSettings overrides)
        {
            var getters = new Func<ElementId>[]
            {
                () => overrides.SurfaceForegroundPatternId,
                () => overrides.CutForegroundPatternId,
                () => overrides.SurfaceBackgroundPatternId,
            };
            foreach (var get in getters)
            {
                try
                {
                    ElementId patternId = get();
                    if (patternId != null && patternId != ElementId.InvalidElementId && Eid(patternId) > 0)
                        return patternId;
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }
            return null;
        }

        /// <summary>Type ids of the systems in use: formed systems, plus the type parameter on members.</summary>
        private Dictionary<long, ElementId> UsedSystemTypeIds(Type systemClass, BuiltInParameter typeParam,
                                                              string[] categories, string noun)
        {
            var ids = new Dictionary<long, ElementId>();
            try
            {
                foreach (Element system in new FilteredElementCollector(doc).OfClass(systemClass))
                {
                    ElementId typeId = system.GetTypeId();
                    if (typeId != null && typeId != ElementId.InvalidElementId) ids[Eid(typeId)] = typeId;
                }
            }
            catch (Exception err)
            {
                Swallowed(err);
            }

            Log(string.Format(Inv, "{0} systems: {1} type(s) from formed systems", noun, ids.Count));
            foreach (string name in categories)
            {
                if (!Enum.TryParse(name, out BuiltInCategory builtin)) continue;
                FilteredElementCollector collector;
                try
                {
                    collector = new FilteredElementCollector(doc).OfCategory(builtin).WhereElementIsNotElementType();
                }
                catch (Exception err)
                {
                    Swallowed(err);
                    continue;
                }
                foreach (Element element in collector)
                {
                    Parameter value;
                    try
                    {
                        value = element.get_Parameter(typeParam);
                    }
                    catch (Exception err)
                    {
                        Swallowed(err);
                        continue;
                    }
                    if (value == null || !value.HasValue) continue;
                    ElementId typeId;
                    try
                    {
                        typeId = value.AsElementId();
                    }
                    catch (Exception err)
                    {
                        Swallowed(err);
                        continue;
                    }
                    if (typeId != null && typeId != ElementId.InvalidElementId) ids[Eid(typeId)] = typeId;
                }
            }
            Log(string.Format(Inv, "{0} systems: {1} type(s) in use after the parameter scan", noun, ids.Count));
            return ids;
        }

        /// <summary>The line colour from a system type's Graphic Overrides, or the packed colour parameter.</summary>
        private static (int R, int G, int B)? SystemColour(Element systemType)
        {
            try
            {
                if (systemType is MEPSystemType mep)
                {
                    var found = ColourOf(mep.LineColor);
                    if (found != null) return found;
                }
            }
            catch (Exception err)
            {
                Swallowed(err);
            }

            ParameterSet parameters;
            try
            {
                parameters = systemType.Parameters;
            }
            catch (Exception err)
            {
                Swallowed(err);
                return null;
            }
            foreach (Parameter param in parameters)
            {
                try
                {
                    if (param.Definition == null) continue;
                    string name = param.Definition.Name.ToLowerInvariant();
                    if (!name.Contains("colour") && !name.Contains("color")) continue;
                    if (param.StorageType != StorageType.Integer) continue;
                    var decoded = DecodeColourInt(param.AsInteger());
                    if (decoded != null) return decoded;
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }
            return null;
        }

        private static string ReadString(Element element, BuiltInParameter builtin, params string[] fallbackNames)
        {
            try
            {
                Parameter param = element.get_Parameter(builtin);
                if (param != null && param.HasValue)
                {
                    string value = param.AsString();
                    if (!string.IsNullOrWhiteSpace(value)) return value.Trim();
                }
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            foreach (string name in fallbackNames)
            {
                Parameter param;
                try
                {
                    param = element.LookupParameter(name);
                }
                catch (Exception err)
                {
                    Swallowed(err);
                    continue;
                }
                if (param == null || !param.HasValue) continue;
                string value;
                try
                {
                    value = param.AsString();
                }
                catch (Exception err)
                {
                    Swallowed(err);
                    continue;
                }
                if (!string.IsNullOrWhiteSpace(value)) return value.Trim();
            }
            return "";
        }

        /// <summary>The short name a line style is built from: the abbreviation, else the type name.</summary>
        private static string SystemKey(Element systemType)
        {
            string abbreviation = ReadString(systemType, BuiltInParameter.RBS_SYSTEM_ABBREVIATION_PARAM);
            return abbreviation.Length > 0 ? abbreviation : ElementName(systemType);
        }

        /// <summary>Abbreviation, then ' - ', then Description. IA - INTAKE AIR.</summary>
        private static string SystemLabel(Element systemType)
        {
            string abbreviation = ReadString(systemType, BuiltInParameter.RBS_SYSTEM_ABBREVIATION_PARAM, "Abbreviation");
            string description = ReadString(systemType, BuiltInParameter.ALL_MODEL_DESCRIPTION, "Description");
            return JoinLabel(abbreviation, description, ElementName(systemType));
        }

        /// <summary>Entries for every duct system type in use, with its override colour.</summary>
        public (List<LegendEntry> Entries, List<string> Notes) ReadDuctSystems(LegendKind kind)
        {
            var entries = new List<LegendEntry>();
            var notes = new List<string>();
            var used = UsedSystemTypeIds(typeof(MechanicalSystem), BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM,
                new[] { "OST_DuctCurves", "OST_FlexDuctCurves", "OST_DuctFitting", "OST_DuctAccessory", "OST_DuctTerminal" },
                "duct");
            if (used.Count == 0)
                return (entries, new List<string> { "no ducts in this model name a duct system type" });

            foreach (ElementId typeId in used.Values)
            {
                Element systemType = doc.GetElement(typeId);
                if (systemType == null) continue;
                string name = ElementName(systemType);
                var colour = SystemColour(systemType);
                if (colour == null) notes.Add(name + " has no graphic override colour - shown grey");
                var entry = new LegendEntry(systemType.Id, name, SystemLabel(systemType), colour, null)
                {
                    Key = SystemKey(systemType),
                };
                Log(string.Format(Inv, "   duct type {0}: label \"{1}\", colour {2}", name, entry.Label, RgbText(entry.Colour)));
                entries.Add(entry);
            }
            return (entries.OrderBy(e => e.Label.ToLowerInvariant(), StringComparer.Ordinal).ToList(), notes);
        }

        /// <summary>The classification group a pipe system belongs to, matched on keywords.</summary>
        private static string PipeGroupName(Element systemType)
        {
            string text = "";
            try
            {
                if (systemType is MEPSystemType mep)
                    text = mep.SystemClassification.ToString().ToLowerInvariant();
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            if (text.Length == 0)
            {
                try
                {
                    Parameter value = systemType.get_Parameter(BuiltInParameter.RBS_SYSTEM_CLASSIFICATION_PARAM);
                    if (value != null && value.HasValue)
                        text = (value.AsString() ?? value.AsValueString() ?? "").ToLowerInvariant();
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }
            if (text.Length == 0) text = ElementName(systemType).ToLowerInvariant();

            string groupFound = ClassifyPipe(text);
            Log(string.Format(Inv, "   {0}: classification \"{1}\" -> {2}", ElementName(systemType), text, groupFound));
            return groupFound;
        }

        /// <summary>Entries for every pipe system type in use, tagged with their group.</summary>
        public (List<LegendEntry> Entries, List<string> Notes) ReadPipeSystems(LegendKind kind)
        {
            var entries = new List<LegendEntry>();
            var notes = new List<string>();
            var used = UsedSystemTypeIds(typeof(PipingSystem), BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM,
                new[] { "OST_PipeCurves", "OST_FlexPipeCurves", "OST_PipeFitting", "OST_PipeAccessory" },
                "pipe");
            if (used.Count == 0)
                return (entries, new List<string> { "no pipes in this model name a piping system type" });

            foreach (ElementId typeId in used.Values)
            {
                Element systemType = doc.GetElement(typeId);
                if (systemType == null) continue;
                string name = ElementName(systemType);
                var colour = SystemColour(systemType);
                if (colour == null) notes.Add(name + " has no graphic override colour - shown grey");
                var entry = new LegendEntry(systemType.Id, name, SystemLabel(systemType), colour, null)
                {
                    Key = SystemKey(systemType),
                };
                entry.Group = PipeGroupName(systemType);
                Log(string.Format(Inv, "   pipe type {0}: label \"{1}\", colour {2}, group {3}",
                                  name, entry.Label, RgbText(colour), entry.Group));
                entries.Add(entry);
            }
            return (entries.OrderBy(e => GroupOrder(e.Group))
                           .ThenBy(e => e.Label.ToLowerInvariant(), StringComparer.Ordinal).ToList(), notes);
        }

        /// <summary>How many filters on a template this legend kind would use.</summary>
        public int MatchingFilterCount(View template, LegendKind kind)
        {
            var wanted = CategoryIdSet(kind.Categories);
            string token = (kind.NameToken ?? "").ToLowerInvariant();
            ICollection<ElementId> filterIds;
            try
            {
                filterIds = template.GetFilters();
            }
            catch (Exception err)
            {
                Swallowed(err);
                return 0;
            }
            int count = 0;
            foreach (ElementId filterId in filterIds)
            {
                Element element = doc.GetElement(filterId);
                if (element == null) continue;
                if (wanted.Count > 0 && !FilterCategoryIds(element).Overlaps(wanted)) continue;
                if (token.Length > 0 && !ElementName(element).ToLowerInvariant().Contains(token)) continue;
                count++;
            }
            return count;
        }

        /// <summary>Filters on the template matching the kind's categories and token.</summary>
        public (List<LegendEntry> Entries, List<string> Notes) ReadTemplateFilters(View template, LegendKind kind)
        {
            var entries = new List<LegendEntry>();
            var notes = new List<string>();
            if (template == null) return (entries, new List<string> { "view template not found" });

            var wanted = CategoryIdSet(kind.Categories);
            string token = (kind.NameToken ?? "").ToLowerInvariant();

            List<ElementId> filterIds;
            try
            {
                filterIds = template.GetFilters().ToList();
            }
            catch (Exception err)
            {
                return (entries, new List<string> { "this template exposes no filters: " + ErrText(err) });
            }

            Log(string.Format(Inv, "template \"{0}\": {1} filter(s); keeping those on {2} named \"{3}\"",
                ElementName(template), filterIds.Count,
                string.Join("/", kind.Categories.Select(c => c.Replace("OST_", ""))), token));
            foreach (ElementId filterId in filterIds)
            {
                Element filterElement = doc.GetElement(filterId);
                if (filterElement == null)
                {
                    Log(string.Format(Inv, "   filter id {0}: no element", Eid(filterId)));
                    continue;
                }
                string name = ElementName(filterElement);

                var on = FilterCategoryIds(filterElement);
                if (wanted.Count > 0 && !on.Overlaps(wanted))
                {
                    Log(string.Format(Inv, "   {0}: skipped - categories [{1}] not wanted",
                                      name, string.Join(", ", on.OrderBy(v => v))));
                    continue;
                }
                if (token.Length > 0 && !name.ToLowerInvariant().Contains(token))
                {
                    Log(string.Format(Inv, "   {0}: skipped - name lacks \"{1}\"", name, token));
                    continue;
                }

                OverrideGraphicSettings overrides = null;
                try
                {
                    overrides = template.GetFilterOverrides(filterId);
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }

                var colour = overrides != null ? OverrideColour(overrides) : null;
                ElementId patternId = overrides != null ? OverridePattern(overrides) : null;
                if (colour == null) notes.Add(name + " has no colour override - shown grey");

                var values = RuleValues(filterElement);
                string label = values.Count > 0 ? TidyLabel(values[0], token) : "";
                if (label.Length == 0)
                {
                    label = TidyLabel(name, token);
                    if (label.Length == 0) label = name;
                }

                Log(string.Format(Inv, "   {0}: kept - label \"{1}\", colour {2}, pattern {3}, rule values [{4}]",
                    name, label, RgbText(colour), patternId != null ? Eid(patternId).ToString(Inv) : "None",
                    string.Join(", ", values.Select(v => "'" + v + "'"))));
                entries.Add(new LegendEntry(filterId, name, label, colour, patternId));
            }

            return (entries.OrderBy(e => e.Label.ToLowerInvariant(), StringComparer.Ordinal).ToList(), notes);
        }
    }
}
