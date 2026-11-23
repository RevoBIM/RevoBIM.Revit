using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.FindInView
{
    /// <summary>One view in the list.</summary>
    public sealed class ViewRow
    {
        public View View;
        public ElementId ViewId;
        public string Name = "";
        public string TypeLabel = "";
        public string Scale = "";
        public string Sheet = "";
        public string Level = "";
        public int SortIndex;
        private string search;

        public string Cell(string key)
        {
            switch (key)
            {
                case "name": return Name;
                case "type": return TypeLabel;
                case "scale": return Scale;
                case "sheet": return Sheet;
                case "level": return Level;
                default: return "";
            }
        }

        /// <summary>Built once on first use - after ReadViews has filled in the sheet - then reused on every keystroke.</summary>
        public string SearchText()
        {
            if (search == null) search = (Name + " " + TypeLabel + " " + Sheet + " " + Scale + " " + Level).ToLowerInvariant();
            return search;
        }
    }

    /// <summary>
    /// Find in View - everything that talks to the Revit document. Port of fiv_model.py. Nothing here writes
    /// to the model except <see cref="MakeVisible"/> (one transaction): the tool otherwise only reads, changes
    /// the active view and zooms.
    /// </summary>
    public static class FivModel
    {
        // -------------------------------------------------------- which view types are worth listing --

        public static readonly KeyValuePair<string, string>[] ViewTypeLabels =
        {
            new KeyValuePair<string, string>("FloorPlan", "Floor Plan"),
            new KeyValuePair<string, string>("CeilingPlan", "Ceiling Plan"),
            new KeyValuePair<string, string>("EngineeringPlan", "Structural Plan"),
            new KeyValuePair<string, string>("AreaPlan", "Area Plan"),
            new KeyValuePair<string, string>("Section", "Section"),
            new KeyValuePair<string, string>("Elevation", "Elevation"),
            new KeyValuePair<string, string>("Detail", "Detail View"),
            new KeyValuePair<string, string>("ThreeD", "3D View"),
            new KeyValuePair<string, string>("Walkthrough", "Walkthrough"),
        };

        /// <summary>The views that belong to a level: what a level filter narrows to, and the only ones the zoom-in-place shortcut runs in.</summary>
        public static readonly string[] PlanLabels = { "Floor Plan", "Ceiling Plan", "Structural Plan", "Area Plan" };

        public static string ViewTypeLabel(View view)
        {
            string name;
            try
            {
                name = view.ViewType.ToString();
            }
            catch (Exception)
            {
                return "View";
            }
            foreach (var pair in ViewTypeLabels) if (pair.Key == name) return pair.Value;
            return name;
        }

        public static bool IsPlan(View view)
        {
            return PlanLabels.Contains(ViewTypeLabel(view));
        }

        /// <summary>A view the tool can activate and zoom in.</summary>
        public static bool IsListable(View view)
        {
            try
            {
                if (view == null || view.IsTemplate) return false;
                if (view is ViewSheet) return false;
                string name = view.ViewType.ToString();
                return ViewTypeLabels.Any(p => p.Key == name);
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static string SafeViewName(View view)
        {
            try
            {
                if (!string.IsNullOrEmpty(view.Name)) return view.Name;
            }
            catch (Exception)
            {
            }
            try
            {
                Parameter parameter = view.get_Parameter(BuiltInParameter.VIEW_NAME);
                if (parameter != null) return parameter.AsString() ?? "";
            }
            catch (Exception)
            {
            }
            return "View " + view.Id.Value;
        }

        public static string ScaleText(View view)
        {
            try
            {
                if (view is View3D) return "";
                if (view.Scale > 0) return "1:" + view.Scale;
            }
            catch (Exception)
            {
            }
            return "";
        }

        /// <summary>The level a plan is cut at, or "" for a view that does not have one.</summary>
        public static string ViewLevelName(View view)
        {
            try
            {
                Level level = view.GenLevel;
                return level == null ? "" : (level.Name ?? "");
            }
            catch (Exception)
            {
                return "";
            }
        }

        public static ViewRow MakeRow(View view)
        {
            return new ViewRow
            {
                View = view,
                ViewId = view.Id,
                Name = SafeViewName(view),
                TypeLabel = ViewTypeLabel(view),
                Scale = ScaleText(view),
                Level = ViewLevelName(view),
            };
        }

        // ---------------------------------------------------------------- reading the project --

        /// <summary>The selected elements and the categories they belong to.</summary>
        public static void ReadSelection(UIDocument uidoc, out List<Element> elements, out List<ElementId> elementIds,
                                         out List<ElementId> categoryIds, out List<string> categoryNames)
        {
            Document doc = uidoc.Document;
            elements = new List<Element>();
            elementIds = new List<ElementId>();
            ICollection<ElementId> ids;
            try
            {
                ids = uidoc.Selection.GetElementIds();
            }
            catch (Exception)
            {
                ids = new List<ElementId>();
            }
            foreach (ElementId id in ids)
            {
                Element element = null;
                try
                {
                    element = doc.GetElement(id);
                }
                catch (Exception)
                {
                }
                if (element == null) continue;
                elements.Add(element);
                elementIds.Add(id);
            }
            CategoriesOf(elements, out categoryIds, out categoryNames);
        }

        /// <summary>The categories a set of elements falls into (ids, names).</summary>
        public static void CategoriesOf(IEnumerable<Element> elements, out List<ElementId> categoryIds, out List<string> categoryNames)
        {
            categoryIds = new List<ElementId>();
            categoryNames = new List<string>();
            var seen = new HashSet<long>();
            foreach (Element element in elements)
            {
                Category category = null;
                try
                {
                    category = element.Category;
                }
                catch (Exception)
                {
                }
                if (category == null) continue;
                long key = category.Id.Value;
                if (!seen.Add(key)) continue;
                categoryIds.Add(category.Id);
                try
                {
                    categoryNames.Add(category.Name);
                }
                catch (Exception)
                {
                    categoryNames.Add("Category " + key);
                }
            }
        }

        /// <summary>One typed id: an element id, or a unique id, or nothing.</summary>
        public static Element ElementFromToken(Document doc, string token)
        {
            string text = (token ?? "").Trim();
            if (text.Length == 0) return null;
            string digits = text.StartsWith("-") ? text.Substring(1) : text;
            long number;
            if (digits.Length > 0 && digits.All(char.IsDigit) && long.TryParse(text, out number))
            {
                try
                {
                    return doc.GetElement(new ElementId(number));
                }
                catch (Exception)
                {
                    return null;
                }
            }
            // not a number: Revit's own dialog does not take these, but a unique id is what gets pasted out
            // of a coordination report, so it is worth trying
            try
            {
                return doc.GetElement(text);
            }
            catch (Exception)
            {
                return null;
            }
        }

        public static void FindByIds(Document doc, IEnumerable<string> tokens, out List<Element> elements,
                                     out List<ElementId> ids, out List<string> missing)
        {
            elements = new List<Element>();
            ids = new List<ElementId>();
            missing = new List<string>();
            var seen = new HashSet<long>();
            foreach (string token in tokens)
            {
                Element element = ElementFromToken(doc, token);
                if (element == null)
                {
                    missing.Add(token);
                    continue;
                }
                if (!seen.Add(element.Id.Value)) continue;
                elements.Add(element);
                ids.Add(element.Id);
            }
        }

        public static bool SelectElements(UIDocument uidoc, IEnumerable<ElementId> ids)
        {
            try
            {
                uidoc.Selection.SetElementIds(new List<ElementId>(ids));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // ------------------------------------------------------------ what the selected element is --

        // The level lives in a different parameter for nearly every category, so the list is tried in
        // order. Each member is looked up by name, so one that does not exist on a given release is skipped.
        private static readonly string[] LevelParams =
        {
            "RBS_START_LEVEL_PARAM", "FAMILY_LEVEL_PARAM", "INSTANCE_REFERENCE_LEVEL_PARAM", "SCHEDULE_LEVEL_PARAM",
            "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM", "LEVEL_PARAM", "WALL_BASE_CONSTRAINT", "ROOF_BASE_LEVEL_PARAM",
            "STAIRS_BASE_LEVEL_PARAM", "ROOM_LEVEL_ID", "GROUP_LEVEL",
        };

        private static readonly string[] LevelParamNames = { "Reference Level", "Level", "Schedule Level", "Base Level", "Base Constraint" };

        private static List<BuiltInParameter> levelMembers;

        private static List<BuiltInParameter> LevelMembers()
        {
            if (levelMembers == null)
            {
                var list = new List<BuiltInParameter>();
                foreach (string name in LevelParams)
                {
                    BuiltInParameter member;
                    if (Enum.TryParse(name, out member)) list.Add(member);
                }
                levelMembers = list;
            }
            return levelMembers;
        }

        private static string LevelNameFromId(Document doc, ElementId id)
        {
            try
            {
                if (id == null || id.Value <= 0) return "";
                Element level = doc.GetElement(id);
                return level == null ? "" : (level.Name ?? "");
            }
            catch (Exception)
            {
                return "";
            }
        }

        private static ElementId AsElementId(Parameter parameter)
        {
            try
            {
                return parameter.StorageType == StorageType.ElementId ? parameter.AsElementId() : null;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>The level a parameter says the element is on, or "".</summary>
        public static string LevelFromParameters(Document doc, Element element)
        {
            foreach (BuiltInParameter member in LevelMembers())
            {
                Parameter parameter = null;
                try
                {
                    parameter = element.get_Parameter(member);
                }
                catch (Exception)
                {
                }
                if (parameter == null) continue;
                string found = LevelNameFromId(doc, AsElementId(parameter));
                if (found.Length > 0) return found;
            }
            foreach (string name in LevelParamNames)
            {
                IList<Parameter> parameters = null;
                try
                {
                    parameters = element.GetParameters(name);
                }
                catch (Exception)
                {
                }
                foreach (Parameter parameter in parameters ?? new List<Parameter>())
                {
                    string found = LevelNameFromId(doc, AsElementId(parameter));
                    if (found.Length > 0) return found;
                    try
                    {
                        string text = parameter.AsValueString();
                        if (!string.IsNullOrEmpty(text)) return text;
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            return "";
        }

        /// <summary>[(name, elevation)] for every level, read once per run.</summary>
        public static List<KeyValuePair<string, double>> ProjectLevels(Document doc)
        {
            var levels = new List<KeyValuePair<string, double>>();
            try
            {
                foreach (Level level in new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>())
                {
                    try
                    {
                        levels.Add(new KeyValuePair<string, double>(level.Name, level.Elevation));
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            catch (Exception)
            {
            }
            return levels;
        }

        private static Element HostOf(Element element)
        {
            try
            {
                var instance = element as FamilyInstance;
                if (instance != null) return instance.Host;
                var opening = element as Opening;
                if (opening != null) return opening.Host;
            }
            catch (Exception)
            {
            }
            return null;
        }

        /// <summary>
        /// (level name, how it was worked out). Parameter first, then the host's, then the nearest level
        /// below the element - and the last of those says so, because a derived answer presented as a read
        /// one is worse than no answer.
        /// </summary>
        public static string ElementLevel(Document doc, Element element, List<KeyValuePair<string, double>> levels, out string note)
        {
            note = "";
            string name = LevelFromParameters(doc, element);
            if (name.Length > 0) return name;

            Element host = HostOf(element);
            if (host != null)
            {
                name = LevelFromParameters(doc, host);
                if (name.Length > 0)
                {
                    note = "from its host";
                    return name;
                }
            }

            try
            {
                name = LevelNameFromId(doc, element.LevelId);
                if (name.Length > 0) return name;
            }
            catch (Exception)
            {
            }

            FivCore.Pt3 low, high;
            if (!ElementsBox(new[] { element }, null, out low, out high)) return "";
            if (levels == null) levels = ProjectLevels(doc);
            string nearest = FivCore.NearestLevel(levels, (low.Z + high.Z) / 2.0);
            if (string.IsNullOrEmpty(nearest)) return "";
            note = "nearest below, not from a parameter";
            return nearest;
        }

        /// <summary>"Family : Type", as the properties palette reads it.</summary>
        public static string TypeNameOf(Document doc, Element element)
        {
            Element type = null;
            try
            {
                type = doc.GetElement(element.GetTypeId());
            }
            catch (Exception)
            {
            }
            if (type == null) return "";
            string typeName = "";
            string familyName = "";
            try
            {
                typeName = type.Name ?? "";
            }
            catch (Exception)
            {
            }
            try
            {
                var elementType = type as ElementType;
                if (elementType != null) familyName = elementType.FamilyName ?? "";
            }
            catch (Exception)
            {
            }
            if (familyName.Length == 0)
            {
                try
                {
                    var symbol = type as FamilySymbol;
                    if (symbol != null && symbol.Family != null) familyName = symbol.Family.Name ?? "";
                }
                catch (Exception)
                {
                }
            }
            if (familyName.Length > 0 && typeName.Length > 0) return familyName + " : " + typeName;
            return typeName.Length > 0 ? typeName : familyName;
        }

        /// <summary>The properties panel rows (label, value, note). One element gets the palette's answers; several get the breakdown.</summary>
        public static List<Tuple<string, string, string>> SelectionProperties(Document doc, List<Element> elements)
        {
            var rows = new List<Tuple<string, string, string>>();
            if (elements == null || elements.Count == 0) return rows;
            List<KeyValuePair<string, double>> levels = ProjectLevels(doc);

            if (elements.Count == 1)
            {
                Element element = elements[0];
                string category = "";
                try
                {
                    category = element.Category.Name;
                }
                catch (Exception)
                {
                }
                string note;
                string level = ElementLevel(doc, element, levels, out note);
                rows.Add(Tuple.Create("Level", level.Length > 0 ? level : "none", note));
                rows.Add(Tuple.Create("Category", category, ""));
                rows.Add(Tuple.Create("Type", TypeNameOf(doc, element), ""));
                rows.Add(Tuple.Create("Id", element.Id.Value.ToString(), ""));
                return rows;
            }

            var names = new List<string>();
            int derived = 0;
            foreach (Element element in elements)
            {
                string note;
                string level = ElementLevel(doc, element, levels, out note);
                names.Add(level.Length > 0 ? level : "no level");
                if (note.Length > 0) derived++;
            }
            rows.Add(Tuple.Create("Levels", FivCore.SummariseLevels(names),
                                  derived == 0 ? "" : derived + " worked out from the elevation"));
            List<long> ids = SelectionIdValues(elements);
            if (ids.Count > 0) rows.Add(Tuple.Create("Ids", FivCore.IdPreview(ids), ""));
            return rows;
        }

        /// <summary>The selected element ids as numbers, lowest first.</summary>
        public static List<long> SelectionIdValues(IEnumerable<Element> elements)
        {
            var values = new List<long>();
            foreach (Element element in elements ?? new Element[0])
            {
                try
                {
                    values.Add(element.Id.Value);
                }
                catch (Exception)
                {
                }
            }
            values.Sort();
            return values;
        }

        /// <summary>Every selected id, semicolon separated, for the clipboard.</summary>
        public static string SelectionIdText(IEnumerable<Element> elements)
        {
            return FivCore.JoinIds(SelectionIdValues(elements));
        }

        /// <summary>The level names the selection sits on, most used first. A derived level counts as much as a read one.</summary>
        public static List<string> SelectionLevels(Document doc, List<Element> elements)
        {
            if (elements == null || elements.Count == 0) return new List<string>();
            List<KeyValuePair<string, double>> levels = ProjectLevels(doc);
            var counts = new Dictionary<string, int>();
            foreach (Element element in elements)
            {
                string name = "";
                try
                {
                    string note;
                    name = ElementLevel(doc, element, levels, out note);
                }
                catch (Exception)
                {
                }
                if (name.Length == 0) continue;
                int count;
                counts.TryGetValue(name, out count);
                counts[name] = count + 1;
            }
            var names = counts.Keys.ToList();
            names.Sort((a, b) => counts[a] != counts[b] ? counts[b].CompareTo(counts[a]) : FivCore.NaturalCompare(a, b));
            return names;
        }

        public static Dictionary<string, int> CategoryCounts(IEnumerable<Element> elements)
        {
            var counts = new Dictionary<string, int>();
            foreach (Element element in elements)
            {
                string name;
                try
                {
                    name = element.Category.Name;
                }
                catch (Exception)
                {
                    name = "No category";
                }
                int count;
                counts.TryGetValue(name, out count);
                counts[name] = count + 1;
            }
            return counts;
        }

        /// <summary>Every listable view, plus which sheet each one is placed on.</summary>
        public static List<ViewRow> ReadViews(Document doc)
        {
            var rows = new List<ViewRow>();
            try
            {
                foreach (View view in new FilteredElementCollector(doc).OfClass(typeof(View)).Cast<View>())
                    if (IsListable(view)) rows.Add(MakeRow(view));
            }
            catch (Exception)
            {
            }

            Dictionary<long, string> sheetByView = ReadSheetMap(doc);
            foreach (ViewRow row in rows)
            {
                string number;
                row.Sheet = sheetByView.TryGetValue(row.ViewId.Value, out number) ? number : "";
            }

            rows.Sort((a, b) =>
            {
                int c = FivCore.NaturalCompare(a.TypeLabel, b.TypeLabel);
                return c != 0 ? c : FivCore.NaturalCompare(a.Name, b.Name);
            });
            for (int i = 0; i < rows.Count; i++) rows[i].SortIndex = i;
            return rows;
        }

        /// <summary>One pass, not a collector per view: this runs on every open.</summary>
        public static Dictionary<long, string> ReadSheetMap(Document doc)
        {
            var mapping = new Dictionary<long, string>();
            try
            {
                foreach (ViewSheet sheet in new FilteredElementCollector(doc).OfClass(typeof(ViewSheet)).Cast<ViewSheet>())
                {
                    string number = "";
                    try
                    {
                        if (sheet.IsTemplate) continue;
                        number = sheet.SheetNumber ?? "";
                    }
                    catch (Exception)
                    {
                    }
                    ICollection<ElementId> placed = null;
                    try
                    {
                        placed = sheet.GetAllPlacedViews();
                    }
                    catch (Exception)
                    {
                    }
                    foreach (ElementId id in placed ?? new List<ElementId>())
                        if (!mapping.ContainsKey(id.Value)) mapping[id.Value] = number;
                }
            }
            catch (Exception)
            {
            }
            return mapping;
        }

        /// <summary>
        /// The one place the filter rule lives. levels narrows the list to the plans cut at the selection's
        /// levels and hides everything else; null or empty means no level filter.
        /// </summary>
        public static bool PassesFilters(ViewRow row, ISet<string> tickedTypes, string query, ISet<string> levels)
        {
            if (!tickedTypes.Contains(row.TypeLabel)) return false;
            if (levels != null && levels.Count > 0)
            {
                if (!PlanLabels.Contains(row.TypeLabel) || !levels.Contains(row.Level)) return false;
            }
            return FivCore.MatchesKeywords(row.SearchText(), query);
        }

        /// <summary>The row for the view used last, by id first (survives a rename) and by name second (survives a rebuild).</summary>
        public static ViewRow FindRemembered(IEnumerable<ViewRow> rows, long viewIdValue, string name)
        {
            if (viewIdValue != 0)
                foreach (ViewRow row in rows) if (row.ViewId.Value == viewIdValue) return row;
            if (!string.IsNullOrEmpty(name))
                foreach (ViewRow row in rows) if (row.Name == name) return row;
            return null;
        }

        /// <summary>The view type labels actually in this project, in a settled order.</summary>
        public static List<string> ViewTypesPresent(List<ViewRow> rows)
        {
            var present = new List<string>();
            foreach (var pair in ViewTypeLabels)
                if (!present.Contains(pair.Value) && rows.Any(r => r.TypeLabel == pair.Value)) present.Add(pair.Value);
            foreach (ViewRow row in rows)
                if (!present.Contains(row.TypeLabel)) present.Add(row.TypeLabel);
            return present;
        }

        // ------------------------------------------------------------------- going to the view --

        private static bool BoxTuple(BoundingBoxXYZ box, out FivCore.Pt3 low, out FivCore.Pt3 high)
        {
            low = new FivCore.Pt3();
            high = new FivCore.Pt3();
            if (box == null) return false;
            try
            {
                XYZ min = box.Min, max = box.Max;
                Transform transform = box.Transform;
                if (transform != null && !transform.IsIdentity)
                {
                    var xs = new List<double>();
                    var ys = new List<double>();
                    var zs = new List<double>();
                    foreach (double x in new[] { min.X, max.X })
                        foreach (double y in new[] { min.Y, max.Y })
                            foreach (double z in new[] { min.Z, max.Z })
                            {
                                XYZ p = transform.OfPoint(new XYZ(x, y, z));
                                xs.Add(p.X); ys.Add(p.Y); zs.Add(p.Z);
                            }
                    low = new FivCore.Pt3(xs.Min(), ys.Min(), zs.Min());
                    high = new FivCore.Pt3(xs.Max(), ys.Max(), zs.Max());
                    return true;
                }
                low = new FivCore.Pt3(min.X, min.Y, min.Z);
                high = new FivCore.Pt3(max.X, max.Y, max.Z);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Union of the selected elements' boxes, in that view where possible.</summary>
        public static bool ElementsBox(IEnumerable<Element> elements, View view, out FivCore.Pt3 low, out FivCore.Pt3 high)
        {
            var boxes = new List<KeyValuePair<FivCore.Pt3, FivCore.Pt3>>();
            foreach (Element element in elements)
            {
                FivCore.Pt3 a = new FivCore.Pt3(), b = new FivCore.Pt3();
                bool got = false;
                if (view != null)
                {
                    try
                    {
                        got = BoxTuple(element.get_BoundingBox(view), out a, out b);
                    }
                    catch (Exception)
                    {
                        got = false;
                    }
                }
                if (!got)
                {
                    try
                    {
                        got = BoxTuple(element.get_BoundingBox(null), out a, out b);
                    }
                    catch (Exception)
                    {
                        got = false;
                    }
                }
                if (got) boxes.Add(new KeyValuePair<FivCore.Pt3, FivCore.Pt3>(a, b));
            }
            return FivCore.UnionBox(boxes, out low, out high);
        }

        /// <summary>Every open view window.</summary>
        public static List<FivCore.WinRect> ReadWindowRects(UIDocument uidoc)
        {
            var rects = new List<FivCore.WinRect>();
            try
            {
                foreach (UIView uiView in uidoc.GetOpenUIViews())
                {
                    try
                    {
                        Rectangle r = uiView.GetWindowRectangle();
                        rects.Add(new FivCore.WinRect(uiView.ViewId.Value, r.Left, r.Top, r.Right, r.Bottom));
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            catch (Exception)
            {
            }
            return rects;
        }

        /// <summary>Close one open view window. Revit refuses to close the last one.</summary>
        public static bool CloseUiView(UIDocument uidoc, long viewIdValue)
        {
            try
            {
                foreach (UIView uiView in uidoc.GetOpenUIViews())
                {
                    if (uiView.ViewId.Value == viewIdValue)
                    {
                        uiView.Close();
                        return true;
                    }
                }
            }
            catch (Exception)
            {
            }
            return false;
        }

        // Every known route to Revit's own tile command, tried in order. The enum member has been spelled
        // differently across releases and the command is only postable in some UI states, so one name is
        // not enough - and a route that fails says WHY, or the only thing the user gets is "Revit said no".
        private static readonly KeyValuePair<string, string>[] TileCommands =
        {
            new KeyValuePair<string, string>("enum", "TileWindows"),
            new KeyValuePair<string, string>("enum", "TileViews"),
            new KeyValuePair<string, string>("enum", "Tile"),
            new KeyValuePair<string, string>("enum", "TileWindow"),
            new KeyValuePair<string, string>("id", "ID_WINDOW_TILE"),
            new KeyValuePair<string, string>("id", "ID_WINDOW_TILE_HORZ"),
            new KeyValuePair<string, string>("id", "ID_WINDOW_TILE_VERT"),
            new KeyValuePair<string, string>("id", "ID_VIEW_TILE"),
        };

        private static RevitCommandId ResolveTileCommand(string kind, string name, out string note)
        {
            note = "";
            try
            {
                RevitCommandId id;
                if (kind == "enum")
                {
                    PostableCommand member;
                    if (!Enum.TryParse(name, out member))
                    {
                        note = "PostableCommand has no member " + name;
                        return null;
                    }
                    id = RevitCommandId.LookupPostableCommandId(member);
                }
                else
                {
                    id = RevitCommandId.LookupCommandId(name);
                }
                if (id == null) note = "Revit does not know " + name;
                return id;
            }
            catch (Exception err)
            {
                note = err.GetType().Name + ": " + err.Message;
                return null;
            }
        }

        /// <summary>
        /// Asks Revit to tile its view windows. There is no API that arranges windows: this is Revit's own
        /// command, posted, and it decides the layout itself. Returns (ok, report) - the report names every
        /// route tried and what each said, because a bare false is indistinguishable from a broken button.
        /// </summary>
        public static bool PostTileWindows(UIApplication uiapp, out string report)
        {
            if (uiapp == null)
            {
                report = "no Revit application to post to";
                return false;
            }
            var tried = new List<string>();
            foreach (var route in TileCommands)
            {
                string note;
                RevitCommandId id = ResolveTileCommand(route.Key, route.Value, out note);
                if (id == null)
                {
                    tried.Add(route.Value + " - " + (note.Length > 0 ? note : "not found"));
                    continue;
                }
                // CanPostCommand is read for the report only, never used as a gate: Tile is greyed out
                // while one view window is open, and Revit does not necessarily create the second window
                // until this command ends.
                bool? allowed = null;
                try
                {
                    allowed = uiapp.CanPostCommand(id);
                }
                catch (Exception)
                {
                }
                try
                {
                    uiapp.PostCommand(id);
                    report = route.Value;
                    return true;
                }
                catch (Exception err)
                {
                    tried.Add(route.Value + " - PostCommand threw: " + err.Message + (allowed == false ? " (CanPostCommand said no)" : ""));
                }
            }
            report = string.Join("\n", tried);
            return false;
        }

        public static string TileFailureMessage(string report)
        {
            return "The view opened beside the one you came from, but Revit would not take the command that tiles " +
                   "the windows, so they are not laid out.\n\n" +
                   "Tile them from View > Tile Views, or with WT.\n\n" +
                   "What was tried:\n" + (string.IsNullOrEmpty(report) ? "nothing" : report) + "\n\n" +
                   "Turn \"warn_tile_failure\" off in\n%APPDATA%\\RevoBIM\\find_in_view.txt to stop this being reported.";
        }

        /// <summary>
        /// Decides what happens to the windows before the view is opened: (view id to close or null, tile mode).
        /// Tile Views is posted in exactly one situation: the view you came from is the only window open.
        /// With more than one open, that arrangement is the user's and is left alone.
        /// </summary>
        public static string PlanTiling(List<FivCore.WinRect> rects, long? hostId, long targetId,
                                        Dictionary<string, string> settings, out long? toClose)
        {
            toClose = null;
            if (!FivCore.AsBool(FivCore.Get(settings, "open_tiled"))) return FivCore.TileNever;

            // already open in its own window: activating it brings that window forward exactly where it is
            if (rects.Any(r => r.ViewId == targetId)) return FivCore.TileNever;

            // the view you came from, on its own
            if (rects.Count <= 1) return FivCore.TileAlways;

            if (FivCore.LooksTiled(rects) && FivCore.AsBool(FivCore.Get(settings, "reuse_tile"), true))
            {
                long? spare = FivCore.PickTileToReuse(rects, hostId, targetId);
                if (spare.HasValue)
                {
                    // take a tile's place rather than adding a window, and never tile
                    toClose = spare;
                    return FivCore.TileNever;
                }
            }
            return FivCore.TileNever;
        }

        // ---------------------------------------- making the selection visible in the view it is opening in --

        /// <summary>The selected categories the view has switched off.</summary>
        public static List<ElementId> HiddenCategoriesIn(View view, IEnumerable<ElementId> categoryIds)
        {
            var hidden = new List<ElementId>();
            foreach (ElementId id in categoryIds ?? new ElementId[0])
            {
                try
                {
                    if (view.GetCategoryHidden(id)) hidden.Add(id);
                }
                catch (Exception)
                {
                    // not every category can be asked about in every view
                }
            }
            return hidden;
        }

        /// <summary>Elements hidden in this view one at a time, rather than by category.</summary>
        public static List<Element> HiddenElementsIn(View view, IEnumerable<Element> elements)
        {
            var hidden = new List<Element>();
            foreach (Element element in elements ?? new Element[0])
            {
                try
                {
                    if (element.IsHidden(view)) hidden.Add(element);
                }
                catch (Exception)
                {
                }
            }
            return hidden;
        }

        public static string CategoryName(Document doc, ElementId categoryId)
        {
            try
            {
                foreach (Category category in doc.Settings.Categories)
                    if (category.Id.Value == categoryId.Value) return category.Name;
            }
            catch (Exception)
            {
            }
            return "category " + categoryId.Value;
        }

        /// <summary>
        /// Which of these the view actually draws, or null where that could not be asked. A view-scoped
        /// collector is the honest test: it accounts for the crop, view filters, phasing, worksets, design
        /// options and the view range. It is narrowed to the selection's own categories inside Revit first.
        /// </summary>
        public static HashSet<long> DrawnInView(Document doc, View view, IEnumerable<ElementId> elementIds, IEnumerable<ElementId> categoryIds)
        {
            ICollection<ElementId> found;
            try
            {
                FilteredElementCollector collector = new FilteredElementCollector(doc, view.Id);
                ElementFilter narrowing = CategoryFilter(categoryIds);
                if (narrowing != null) collector = collector.WherePasses(narrowing);
                found = collector.WhereElementIsNotElementType().ToElementIds();
            }
            catch (Exception)
            {
                return null;
            }
            var wanted = new HashSet<long>(elementIds.Select(i => i.Value));
            var drawn = new HashSet<long>();
            foreach (ElementId id in found)
                if (wanted.Contains(id.Value)) drawn.Add(id.Value);
            return drawn;
        }

        /// <summary>One filter for every category in the selection, or null. An empty multicategory filter matches nothing, so empty is decided first.</summary>
        private static ElementFilter CategoryFilter(IEnumerable<ElementId> categoryIds)
        {
            var wanted = (categoryIds ?? new ElementId[0]).Where(c => c != null).ToList();
            if (wanted.Count == 0) return null;
            try
            {
                return new ElementMulticategoryFilter(wanted);
            }
            catch (Exception)
            {
                return null;
            }
        }

        public static bool ViewHasTemplate(View view)
        {
            try
            {
                return view.ViewTemplateId != null && view.ViewTemplateId.Value > 0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// Switches the selection's categories back on in the view (notes, mode). The only place the tool
        /// writes to the model, in ONE transaction so a single undo puts the view back exactly as it was.
        /// </summary>
        public static string MakeVisible(Document doc, View view, List<ElementId> categoryIds, List<Element> elements,
                                         Dictionary<string, string> settings, List<string> notes)
        {
            List<ElementId> hiddenCategories = HiddenCategoriesIn(view, categoryIds);
            List<Element> hiddenElements = HiddenElementsIn(view, elements);

            string wantedMode = FivCore.Get(settings, "unhide_mode").ToLowerInvariant();
            if (wantedMode.Length == 0) wantedMode = "auto";
            string mode = FivCore.PlanUnhide(FivCore.AsBool(FivCore.Get(settings, "unhide_categories"), true), wantedMode,
                                             hiddenCategories.Count, hiddenElements.Count, ViewHasTemplate(view));
            FivLog.Write("unhide: view '" + view.Name + "' hidden categories " + hiddenCategories.Count +
                         ", hidden elements " + hiddenElements.Count + ", template " + ViewHasTemplate(view) +
                         ", asked '" + wantedMode + "' -> " + mode);
            if (mode == FivCore.UnhideNone) return mode;

            if (wantedMode == FivCore.UnhideTemporary && mode == FivCore.UnhidePermanent)
                notes.Add("The view has no view template, so Revit has no temporary view properties mode to enter. " +
                          "The change was made to the view itself - one undo puts it back.");

            // a view somebody else has is reported by name rather than failing mid write
            try
            {
                WorksharingUtils.CheckoutElements(doc, new List<ElementId> { view.Id });
            }
            catch (Exception)
            {
            }

            var turnedOn = new List<string>();
            var failed = new List<string>();
            using (var transaction = new Transaction(doc, "RevoBIM Find in View - show the selection"))
            {
                try
                {
                    transaction.Start();
                }
                catch (Exception err)
                {
                    notes.Add("The view could not be changed: " + err.Message);
                    return FivCore.UnhideNone;
                }
                try
                {
                    if (mode == FivCore.UnhideTemporary)
                    {
                        try
                        {
                            view.EnableTemporaryViewPropertiesMode(view.ViewTemplateId);
                        }
                        catch (Exception err)
                        {
                            mode = FivCore.UnhidePermanent;
                            notes.Add("Revit would not enter temporary view properties mode (" + err.Message +
                                      "), so the change was made to the view itself - one undo puts it back.");
                        }
                    }

                    foreach (ElementId categoryId in hiddenCategories)
                    {
                        string name = CategoryName(doc, categoryId);
                        bool allowed = true;
                        try
                        {
                            allowed = view.CanCategoryBeHidden(categoryId);
                        }
                        catch (Exception)
                        {
                            allowed = true;
                        }
                        if (!allowed)
                        {
                            failed.Add(name + " cannot be switched on in this view");
                            continue;
                        }
                        try
                        {
                            view.SetCategoryHidden(categoryId, false);
                            turnedOn.Add(name);
                        }
                        catch (Exception err)
                        {
                            failed.Add(name + " would not switch on: " + err.Message);
                        }
                    }

                    if (hiddenElements.Count > 0)
                    {
                        try
                        {
                            view.UnhideElements(hiddenElements.Select(e => e.Id).ToList());
                            turnedOn.Add(FivCore.Plural(hiddenElements.Count, "hidden element"));
                        }
                        catch (Exception err)
                        {
                            failed.Add("elements hidden one at a time would not come back: " + err.Message);
                        }
                    }

                    transaction.Commit();
                }
                catch (Exception err)
                {
                    try
                    {
                        transaction.RollBack();
                    }
                    catch (Exception)
                    {
                    }
                    notes.Add("The view could not be changed: " + err.Message);
                    return FivCore.UnhideNone;
                }
            }

            // prove the write: Revit does not reliably raise when one does not take
            List<ElementId> stillHidden = HiddenCategoriesIn(view, hiddenCategories);
            if (stillHidden.Count > 0)
            {
                List<string> names = stillHidden.Select(id => CategoryName(doc, id)).ToList();
                failed.Add("still switched off after the change: " + string.Join(", ", names) +
                           " - a view template usually controls this");
                foreach (string name in names) turnedOn.Remove(name);
            }

            if (turnedOn.Count > 0)
            {
                string where = mode == FivCore.UnhideTemporary
                    ? "temporarily - the blue border is Revit showing temporary view properties"
                    : "in the view - one undo puts it back";
                notes.Add("Switched on " + string.Join(", ", turnedOn) + " " + where + ".");
            }
            notes.AddRange(failed);
            FivLog.Write("unhide: result mode " + mode + ", on [" + string.Join(", ", turnedOn) + "], failed [" + string.Join("; ", failed) + "]");
            return mode;
        }

        /// <summary>
        /// Frames the view you are already in on the selection (ok, note). Nothing is activated, closed or
        /// written: the view is already open and showing the elements, so this is only the zoom.
        /// </summary>
        public static bool ZoomHere(UIDocument uidoc, View view, List<Element> elements, List<ElementId> elementIds,
                                    Dictionary<string, string> settings, out string note)
        {
            note = "";
            // decided before the collector runs: a 3D view or a section opens the view list whatever it
            // draws, so there is no reason to ask it
            if (!IsPlan(view))
            {
                FivLog.Write("zoom-here: '" + view.Name + "' is not a plan -> window");
                return false;
            }
            List<ElementId> categoryIds;
            List<string> categoryNames;
            CategoriesOf(elements, out categoryIds, out categoryNames);
            HashSet<long> drawn = DrawnInView(uidoc.Document, view, elementIds, categoryIds);
            if (drawn == null)
            {
                FivLog.Write("zoom-here: could not ask the view what it draws -> window");
                return false;
            }
            bool needsAll = FivCore.AsBool(FivCore.Get(settings, "zoom_here_needs_all"), true);
            string decision = FivCore.ZoomHereDecision(FivCore.AsBool(FivCore.Get(settings, "zoom_here"), true),
                                                       IsListable(view), elementIds.Count, drawn.Count, needsAll, IsPlan(view));
            FivLog.Write("zoom-here: view '" + view.Name + "', selected " + elementIds.Count + ", drawn " + drawn.Count +
                         ", needs all " + needsAll + " -> " + decision);
            if (decision != FivCore.HereZoom) return false;

            var here = elements.Where(e => drawn.Contains(e.Id.Value)).ToList();
            if (here.Count == 0) return false;

            try
            {
                uidoc.RefreshActiveView();
            }
            catch (Exception)
            {
            }
            return ZoomToElements(uidoc, view, here, settings, false, out note);
        }

        /// <summary>The view's own origin, right, up and depth directions.</summary>
        public static void ViewFrame(View view, out FivCore.Pt3 origin, out FivCore.Pt3 right, out FivCore.Pt3 up, out FivCore.Pt3 normal)
        {
            origin = new FivCore.Pt3(0, 0, 0);
            try
            {
                XYZ p = view.Origin;
                origin = new FivCore.Pt3(p.X, p.Y, p.Z);
            }
            catch (Exception)
            {
            }
            try
            {
                XYZ r = view.RightDirection, u = view.UpDirection, n = view.ViewDirection;
                right = new FivCore.Pt3(r.X, r.Y, r.Z);
                up = new FivCore.Pt3(u.X, u.Y, u.Z);
                normal = new FivCore.Pt3(n.X, n.Y, n.Z);
            }
            catch (Exception)
            {
                // a plain world frame still zooms a plan correctly
                right = new FivCore.Pt3(1, 0, 0);
                up = new FivCore.Pt3(0, 1, 0);
                normal = new FivCore.Pt3(0, 0, 1);
            }
        }

        public static UIView FindUiView(UIDocument uidoc, ElementId viewId)
        {
            try
            {
                foreach (UIView candidate in uidoc.GetOpenUIViews())
                    if (candidate.ViewId.Value == viewId.Value) return candidate;
            }
            catch (Exception)
            {
            }
            return null;
        }

        /// <summary>The rectangle the window is actually showing, in model coordinates.</summary>
        public static bool ReadZoomCorners(UIView uiView, out FivCore.Pt3 a, out FivCore.Pt3 b)
        {
            a = new FivCore.Pt3();
            b = new FivCore.Pt3();
            try
            {
                IList<XYZ> corners = uiView.GetZoomCorners();
                if (corners == null || corners.Count < 2) return false;
                a = new FivCore.Pt3(corners[0].X, corners[0].Y, corners[0].Z);
                b = new FivCore.Pt3(corners[1].X, corners[1].Y, corners[1].Z);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// Reads the visible rectangle back and says whether it framed the selection. Revit does its own
        /// framing when it opens a window, and ZoomAndCenterRectangle raises nothing when it does not take,
        /// so a call that returned is not evidence that anything moved. Null = could not check.
        /// </summary>
        private static bool? CheckZoom(UIView uiView, View view, FivCore.Pt3 low, FivCore.Pt3 high, out string reason)
        {
            FivCore.Pt3 ca, cb;
            if (!ReadZoomCorners(uiView, out ca, out cb))
            {
                reason = "Revit would not report what the view is showing";
                return null;
            }
            FivCore.Pt3 origin, right, up, normal;
            ViewFrame(view, out origin, out right, out up, out normal);
            return FivCore.ZoomLanded(FivCore.ToFrame(low, origin, right, up, normal), FivCore.ToFrame(high, origin, right, up, normal),
                                      FivCore.ToFrame(ca, origin, right, up, normal), FivCore.ToFrame(cb, origin, right, up, normal),
                                      out reason);
        }

        /// <summary>
        /// Fits the view around the elements, and checks that it took. Tiling is posted rather than called,
        /// so it happens AFTER this zoom and the window it was measured for is about to shrink: zoom wider
        /// than wanted by the tile allowance instead.
        /// </summary>
        public static bool ZoomToElements(UIDocument uidoc, View view, List<Element> elements, Dictionary<string, string> settings,
                                          bool tiling, out string note)
        {
            note = "";
            FivCore.Pt3 boxLow, boxHigh;
            if (!ElementsBox(elements, view, out boxLow, out boxHigh))
            {
                note = "Nothing in the selection had geometry to zoom to.";
                return false;
            }

            UIView uiView = FindUiView(uidoc, view.Id);
            if (uiView == null)
            {
                FivLog.Write("zoom: no open window for '" + view.Name + "'");
                return false;
            }

            FivCore.Pt3 origin, right, up, normal;
            ViewFrame(view, out origin, out right, out up, out normal);
            int paddingPct = FivCore.AsInt(FivCore.Get(settings, "zoom_padding_pct"), 15);
            if (tiling) paddingPct += FivCore.AsInt(FivCore.Get(settings, "tile_zoom_extra_pct"), 35);
            double minPadding = FivCore.MmToFeet(FivCore.AsInt(FivCore.Get(settings, "zoom_min_padding_mm"), 300));
            FivCore.Pt3 low, high;
            FivCore.ZoomRectangle(boxLow, boxHigh, origin, right, up, normal, paddingPct, minPadding, out low, out high);

            int attempts = Math.Max(1, FivCore.AsInt(FivCore.Get(settings, "zoom_attempts"), 3));
            string reason = "";
            for (int attempt = 1; attempt <= attempts; attempt++)
            {
                try
                {
                    uiView.ZoomAndCenterRectangle(new XYZ(low.X, low.Y, low.Z), new XYZ(high.X, high.Y, high.Z));
                }
                catch (Exception err)
                {
                    note = "The zoom was refused: " + err.Message;
                    FivLog.Write("zoom: attempt " + attempt + " refused: " + err.Message);
                    return false;
                }

                bool? landed = CheckZoom(uiView, view, low, high, out reason);
                FivLog.Write("zoom: attempt " + attempt + "/" + attempts + " padding " + paddingPct + "% tiling " + tiling +
                             " -> " + (landed == null ? "unchecked (" + reason + ")" : landed.Value ? "landed" : "missed: " + reason));
                if (landed == null || landed.Value) return true;

                // Revit framed the window itself after the call - most likely because it had only just been
                // created. Let it settle and go again.
                try
                {
                    uidoc.RefreshActiveView();
                }
                catch (Exception)
                {
                }
                uiView = FindUiView(uidoc, view.Id) ?? uiView;
            }

            note = "The view opened but Revit would not hold the zoom: " + (reason.Length > 0 ? reason : "the framing did not take") + ".";
            return false;
        }

        /// <summary>
        /// Opens the view, then fits it around the selected elements (ok, message). Opening and zooming are
        /// separate concerns: a view that opens but will not zoom still leaves the user in the right place.
        /// </summary>
        public static bool ActivateAndZoom(UIDocument uidoc, View view, List<Element> elements, List<ElementId> elementIds,
                                           Dictionary<string, string> settings, UIApplication uiapp, long? hostViewId,
                                           List<ElementId> categoryIds, out string message)
        {
            // The category has to be switched on BEFORE the view is activated: a transaction has to be
            // closed before the active view can change, so doing it first is the only order that works.
            var notes = new List<string>();
            if (elements.Count > 0)
            {
                try
                {
                    MakeVisible(uidoc.Document, view, categoryIds ?? new List<ElementId>(), elements, settings, notes);
                }
                catch (Exception err)
                {
                    notes = new List<string> { "The view could not be changed: " + err.Message };
                }
            }

            long targetId = view.Id.Value;
            List<FivCore.WinRect> rects = ReadWindowRects(uidoc);
            long? toClose;
            string tileMode = PlanTiling(rects, hostViewId, targetId, settings, out toClose);
            FivLog.Write("tiling: open windows " + rects.Count + ", looks tiled " + FivCore.LooksTiled(rects) +
                         ", host " + (hostViewId.HasValue ? hostViewId.Value.ToString() : "none") + ", target " + targetId +
                         " -> mode " + tileMode + (toClose.HasValue ? ", closing " + toClose.Value : ""));
            if (toClose.HasValue) CloseUiView(uidoc, toClose.Value);

            try
            {
                uidoc.ActiveView = view;
            }
            catch (Exception err)
            {
                message = "Revit would not open that view: " + err.Message;
                return false;
            }
            FivLog.Write("open: activated '" + view.Name + "' (" + targetId + ")");

            try
            {
                uidoc.RefreshActiveView();
            }
            catch (Exception)
            {
            }

            if (FivCore.AsBool(FivCore.Get(settings, "reselect_after_zoom"), true))
            {
                try
                {
                    uidoc.Selection.SetElementIds(new List<ElementId>(elementIds));
                }
                catch (Exception)
                {
                }
            }

            bool retile = tileMode == FivCore.TileAlways;

            if (elements.Count == 0)
            {
                // opened with nothing selected: there is nothing to frame, and saying so would be reporting
                // a problem that is not one
                string ignored;
                if (retile) PostTileWindows(uiapp, out ignored);
                message = "";
                return true;
            }

            string missing = StillMissing(uidoc.Document, view, elementIds, categoryIds);
            if (missing.Length > 0) notes.Add(missing);

            string note;
            bool zoomed = ZoomToElements(uidoc, view, elements, settings, retile, out note);

            if (!zoomed && uiapp != null)
            {
                // Revit hands back a UIDocument whose open view list was built before the view was
                // activated, so the UIView for a view that was not already open is missing from it.
                // Asking the application for the ACTIVE UIDocument again picks the new one up.
                UIDocument fresh = null;
                try
                {
                    fresh = uiapp.ActiveUIDocument;
                }
                catch (Exception)
                {
                }
                if (fresh != null)
                {
                    try
                    {
                        fresh.RefreshActiveView();
                    }
                    catch (Exception)
                    {
                    }
                    zoomed = ZoomToElements(fresh, view, elements, settings, retile, out note);
                    FivLog.Write("zoom: retried on a fresh UIDocument -> " + zoomed);
                    if (zoomed) uidoc = fresh;
                }
            }

            if (!zoomed)
            {
                // ShowElements does its own zoom to fit around the elements and needs no UIView, so it is a
                // real fallback. It is second choice because it decides the framing itself.
                try
                {
                    uidoc.ShowElements(new List<ElementId>(elementIds));
                    FivLog.Write("zoom: fell back to ShowElements");
                    message = "";
                    return true;
                }
                catch (Exception err)
                {
                    FivLog.Write("zoom: ShowElements failed: " + err.Message);
                    message = note.Length > 0 ? note : "Opened the view, but Revit would not zoom it.";
                    return true;
                }
            }

            try
            {
                uidoc.RefreshActiveView();
            }
            catch (Exception)
            {
            }

            if (retile)
            {
                string report;
                bool tiled = PostTileWindows(uiapp, out report);
                FivLog.Write("tiling: posted -> " + tiled + " (" + report.Replace("\n", " / ") + ")");
                if (!tiled && FivCore.AsBool(FivCore.Get(settings, "warn_tile_failure"), true))
                    notes.Add(TileFailureMessage(report));
            }
            message = string.Join("\n\n", notes.Where(n => !string.IsNullOrEmpty(n)));
            return true;
        }

        /// <summary>Anything the view still will not draw, and the reasons worth naming.</summary>
        public static string StillMissing(Document doc, View view, List<ElementId> elementIds, List<ElementId> categoryIds)
        {
            HashSet<long> drawn = DrawnInView(doc, view, elementIds, categoryIds);
            if (drawn == null) return "";
            int missing = elementIds.Count - drawn.Count;
            if (missing <= 0) return "";
            return missing + " of the selection " + (missing == 1 ? "is" : "are") + " still not drawn in this view. Switching " +
                   "the category on does not fix a view filter, the crop region, the phase, a closed workset, a design " +
                   "option or the view range.";
        }
    }
}
