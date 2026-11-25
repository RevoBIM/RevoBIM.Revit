using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.WorksetManagement
{
    /// <summary>
    /// Routine templates (the Workset Assigner's version of a Revit view filter), the assigner's state and the
    /// routine file. Nothing here touches the Revit API. Port of wsm_rules.py.
    /// </summary>
    public static class WsmRules
    {
        public const string FormatVersion = "1";
        public const string FileExtension = ".wsroutine";
        public static string LibraryPath { get { return Path.Combine(WsmCore.AppDataDir, "workset_routine_templates.txt"); } }
        public static string StateDir { get { return Path.Combine(WsmCore.AppDataDir, "workset_routines"); } }

        public const string ModeNone = "none", ModeCategories = "categories", ModeRoutine = "routine";
        public const string AllCategories = "";
        public const string KindText = "text", KindNumber = "number", KindInteger = "integer", KindId = "id";

        public static readonly KeyValuePair<string, string>[] OpLabels =
        {
            new KeyValuePair<string, string>("equals", "equals"),
            new KeyValuePair<string, string>("not_equals", "does not equal"),
            new KeyValuePair<string, string>("contains", "contains"),
            new KeyValuePair<string, string>("not_contains", "does not contain"),
            new KeyValuePair<string, string>("begins", "begins with"),
            new KeyValuePair<string, string>("not_begins", "does not begin with"),
            new KeyValuePair<string, string>("ends", "ends with"),
            new KeyValuePair<string, string>("not_ends", "does not end with"),
            new KeyValuePair<string, string>("gt", "is greater than"),
            new KeyValuePair<string, string>("ge", "is greater than or equal to"),
            new KeyValuePair<string, string>("lt", "is less than"),
            new KeyValuePair<string, string>("le", "is less than or equal to"),
            new KeyValuePair<string, string>("has_value", "has a value"),
            new KeyValuePair<string, string>("no_value", "has no value"),
        };
        public static readonly string[] TextOps = { "equals", "not_equals", "contains", "not_contains", "begins", "not_begins", "ends", "not_ends", "has_value", "no_value" };
        public static readonly string[] NumberOps = { "equals", "not_equals", "gt", "ge", "lt", "le", "has_value", "no_value" };
        public static readonly string[] ValuelessOps = { "has_value", "no_value" };

        private static string Txt(object v) { return WsmCore.Txt(v); }

        public static List<string> OpsFor(string kind)
        {
            return (kind == KindNumber || kind == KindInteger ? NumberOps : TextOps).ToList();
        }

        public static string OpLabel(string op)
        {
            foreach (var pair in OpLabels) if (pair.Key == op) return pair.Value;
            return Txt(op);
        }

        public static bool IsKnownOp(string op) { return OpLabels.Any(p => p.Key == op); }
        public static bool NeedsValue(string op) { return !ValuelessOps.Contains(op); }

        // ================================================================ the tree

        public abstract class Node
        {
            public abstract bool IsSet { get; }
            public abstract Node Copy();
        }

        public class Rule : Node
        {
            public string Param, Label, Kind, Op, Value, Scope;

            public Rule(string param = "", string label = "", string kind = KindText, string op = "equals", string value = "", string scope = AllCategories)
            {
                Param = Txt(param); Label = Txt(label);
                Kind = kind == KindText || kind == KindNumber || kind == KindInteger || kind == KindId ? kind : KindText;
                Op = IsKnownOp(op) ? op : "equals";
                Value = Txt(value); Scope = Txt(scope);
            }

            public override bool IsSet { get { return false; } }
            public override Node Copy() { return new Rule(Param, Label, Kind, Op, Value, Scope); }
            public bool Complete() { return Param.Length > 0 && (!NeedsValue(Op) || Value.Trim().Length > 0); }
        }

        public class RuleSet : Node
        {
            public string Mode;
            public List<Node> Items;

            public RuleSet(string mode = "and", IEnumerable<Node> items = null)
            {
                Mode = Txt(mode).ToLowerInvariant() == "or" ? "or" : "and";
                Items = items == null ? new List<Node>() : items.ToList();
            }

            public override bool IsSet { get { return true; } }
            public override Node Copy() { return new RuleSet(Mode, Items.Select(i => i.Copy())); }
        }

        public class Template
        {
            public string Name;
            public List<string> Categories;
            public Dictionary<string, string> Labels;
            public RuleSet Root;

            public Template(string name, IEnumerable<string> categories = null, Dictionary<string, string> labels = null, RuleSet root = null)
            {
                Name = Txt(name).Trim();
                Categories = categories == null ? new List<string>() : categories.ToList();
                Labels = labels == null ? new Dictionary<string, string>() : new Dictionary<string, string>(labels);
                Root = root ?? new RuleSet("and");
            }

            public Template Copy(string name = null)
            {
                return new Template(name ?? Name, Categories, Labels, (RuleSet)Root.Copy());
            }

            public string CategoryLabel(string key)
            {
                string label;
                return Labels.TryGetValue(key, out label) ? label : key;
            }
        }

        public static List<Rule> WalkRules(Node node)
        {
            var output = new List<Rule>();
            var set = node as RuleSet;
            if (set != null) foreach (Node item in set.Items) output.AddRange(WalkRules(item));
            else output.Add((Rule)node);
            return output;
        }

        public static List<string> ParamsUsed(Template template)
        {
            var keys = new List<string>();
            foreach (Rule rule in WalkRules(template.Root))
                if (rule.Param.Length > 0 && !keys.Contains(rule.Param)) keys.Add(rule.Param);
            return keys;
        }

        public static List<string> TemplateProblems(Template template)
        {
            var problems = new List<string>();
            if (template.Name.Length == 0) problems.Add("it has no name");
            if (template.Categories.Count == 0) problems.Add("no categories are ticked");
            foreach (Rule rule in WalkRules(template.Root))
            {
                string label = rule.Label.Length > 0 ? rule.Label : rule.Param;
                if (rule.Param.Length == 0) problems.Add("a rule has no parameter");
                else if (NeedsValue(rule.Op) && rule.Value.Trim().Length == 0) problems.Add("the rule on " + label + " has no value");
                if (rule.Scope.Length > 0 && !template.Categories.Contains(rule.Scope))
                    problems.Add("the rule on " + label + " is limited to a category no longer ticked");
            }
            return problems;
        }

        public static string Describe(Template template, int limit = 3)
        {
            if (template == null) return "";
            var cats = template.Categories.Select(template.CategoryLabel).ToList();
            string head = string.Join(", ", cats.Take(limit));
            if (cats.Count > limit) head += " +" + (cats.Count - limit);
            var rules = WalkRules(template.Root);
            if (rules.Count == 0) return head.Length > 0 ? head : "(no categories)";
            Rule first = rules[0];
            string text = (first.Label.Length > 0 ? first.Label : first.Param) + " " + OpLabel(first.Op);
            if (NeedsValue(first.Op)) text += " " + first.Value;
            if (rules.Count > 1) text += " (" + (rules.Count - 1) + " more rule" + (rules.Count == 2 ? "" : "s") + ")";
            return head.Length > 0 ? head + "  Â·  " + text : text;
        }

        // ================================================================ evaluating

        /// <summary>One parameter on one element, as the Revit side read it.</summary>
        public class ValueRecord
        {
            public bool Present, Has;
            public string Text;
            public double? Number;

            public ValueRecord(bool present = false, bool has = false, string text = "", double? number = null)
            {
                Present = present; Has = has && present; Text = Txt(text); Number = number;
            }
        }

        public static readonly ValueRecord Missing = new ValueRecord(false, false, "", null);

        private static readonly Regex NumberRe = new Regex(@"^\s*([-+]?\d[\d,]*(?:\.\d+)?|[-+]?\.\d+)", RegexOptions.Compiled);

        public static double? ParseNumber(string text)
        {
            Match m = NumberRe.Match(Txt(text));
            if (!m.Success) return null;
            double d;
            if (double.TryParse(m.Groups[1].Value.Replace(",", ""), NumberStyles.Float, CultureInfo.InvariantCulture, out d)) return d;
            return null;
        }

        private static bool Close(double a, double b)
        {
            return Math.Abs(a - b) <= Math.Max(1e-6, 1e-9 * Math.Max(Math.Abs(a), Math.Abs(b)));
        }

        /// <summary>Revit's own sense of a filter rule: an element without the parameter passes only 'has no value'; text ignores case.</summary>
        public static bool RulePasses(Rule rule, ValueRecord record)
        {
            string op = rule.Op;
            if (op == "has_value") return record.Has;
            if (op == "no_value") return !record.Has;
            if (!record.Present) return false;
            if ((rule.Kind == KindNumber || rule.Kind == KindInteger) && NumberOps.Contains(op))
            {
                double? wanted = ParseNumber(rule.Value), actual = record.Number;
                if (!wanted.HasValue || !actual.HasValue)
                {
                    if (op == "equals") return record.Text.Trim().ToLowerInvariant() == rule.Value.Trim().ToLowerInvariant();
                    if (op == "not_equals") return record.Text.Trim().ToLowerInvariant() != rule.Value.Trim().ToLowerInvariant();
                    return false;
                }
                double a = actual.Value, w = wanted.Value;
                switch (op)
                {
                    case "equals": return Close(a, w);
                    case "not_equals": return !Close(a, w);
                    case "gt": return a > w && !Close(a, w);
                    case "ge": return a > w || Close(a, w);
                    case "lt": return a < w && !Close(a, w);
                    case "le": return a < w || Close(a, w);
                }
                return false;
            }
            string have = record.Text.Trim().ToLowerInvariant(), want = rule.Value.Trim().ToLowerInvariant();
            switch (op)
            {
                case "equals": return have == want;
                case "not_equals": return have != want;
                case "contains": return have.Contains(want);
                case "not_contains": return !have.Contains(want);
                case "begins": return have.StartsWith(want, StringComparison.Ordinal);
                case "not_begins": return !have.StartsWith(want, StringComparison.Ordinal);
                case "ends": return have.EndsWith(want, StringComparison.Ordinal);
                case "not_ends": return !have.EndsWith(want, StringComparison.Ordinal);
            }
            return false;
        }

        /// <summary>True / False, or null when nothing in the node applies to an element of this category.</summary>
        public static bool? NodePasses(Node node, Dictionary<string, ValueRecord> values, string category)
        {
            var set = node as RuleSet;
            if (set == null)
            {
                var rule = (Rule)node;
                if (rule.Scope.Length > 0 && rule.Scope != category) return null;
                ValueRecord record;
                return RulePasses(rule, values.TryGetValue(rule.Param, out record) ? record : Missing);
            }
            var results = set.Items.Select(i => NodePasses(i, values, category)).Where(r => r.HasValue).Select(r => r.Value).ToList();
            if (results.Count == 0) return null;
            return set.Mode == "or" ? results.Any(r => r) : results.All(r => r);
        }

        public static bool Matches(Template template, Dictionary<string, ValueRecord> values, string category)
        {
            if (!template.Categories.Contains(category)) return false;
            bool? result = NodePasses(template.Root, values, category);
            return !result.HasValue || result.Value;
        }

        // ================================================================ text files

        private static string Esc(string text)
        {
            return Txt(text).Replace("%", "%25").Replace("|", "%7C").Replace(";", "%3B").Replace("=", "%3D").Replace("\n", "%0A").Replace("\r", "");
        }

        private static string Unesc(string text)
        {
            return Txt(text).Replace("%0A", "\n").Replace("%3D", "=").Replace("%3B", ";").Replace("%7C", "|").Replace("%25", "%");
        }

        public static List<string> TemplateLines(Template template)
        {
            string name = Esc(template.Name);
            var lines = new List<string>
            {
                "template|" + name + "|categories=" + string.Join(";", template.Categories.Select(Esc)),
                "template|" + name + "|labels=" + string.Join(";", template.Categories.Select(k => Esc(k) + "|" + Esc(template.CategoryLabel(k)))),
            };
            int counter = 0;
            Action<Node, int> emit = null;
            emit = (node, parent) =>
            {
                int index = counter++;
                var set = node as RuleSet;
                if (set != null)
                {
                    lines.Add("template|" + name + "|node." + index + "=" + parent + "|set|" + set.Mode);
                    foreach (Node item in set.Items) emit(item, index);
                }
                else
                {
                    var r = (Rule)node;
                    lines.Add("template|" + name + "|node." + index + "=" + parent + "|rule|" + Esc(r.Scope) + "|" + Esc(r.Param) + "|" +
                              Esc(r.Label) + "|" + r.Kind + "|" + r.Op + "|" + Esc(r.Value));
                }
            };
            emit(template.Root, -1);
            return lines;
        }

        private class RawTemplate
        {
            public List<string> Categories = new List<string>();
            public Dictionary<string, string> Labels = new Dictionary<string, string>();
            public SortedDictionary<int, string[]> Nodes = new SortedDictionary<int, string[]>();
        }

        /// <summary>Lines that are not template lines are ignored; a damaged tree keeps what parsed.</summary>
        public static Dictionary<string, Template> ParseTemplates(IEnumerable<string> lines)
        {
            var raw = new Dictionary<string, RawTemplate>();
            foreach (string line in lines)
            {
                string text = Txt(line).Trim();
                if (!text.StartsWith("template|") || !text.Contains("=")) continue;
                int at = text.IndexOf('=');
                string[] parts = text.Substring(0, at).Split('|');
                string right = text.Substring(at + 1);
                if (parts.Length != 3) continue;
                string name = Unesc(parts[1]).Trim();
                if (name.Length == 0) continue;
                RawTemplate entry;
                if (!raw.TryGetValue(name, out entry)) raw[name] = entry = new RawTemplate();
                string field = parts[2];
                if (field == "categories") entry.Categories = right.Split(';').Where(k => k.Length > 0).Select(Unesc).ToList();
                else if (field == "labels")
                {
                    foreach (string pair in right.Split(';'))
                    {
                        int bar = pair.IndexOf('|');
                        if (bar >= 0) entry.Labels[Unesc(pair.Substring(0, bar))] = Unesc(pair.Substring(bar + 1));
                    }
                }
                else if (field.StartsWith("node."))
                {
                    int index;
                    if (int.TryParse(field.Substring(5), out index)) entry.Nodes[index] = right.Split('|');
                }
            }
            var output = new Dictionary<string, Template>();
            foreach (var pair in raw)
            {
                var built = new Dictionary<int, Node>();
                RuleSet root = null;
                foreach (var nodePair in pair.Value.Nodes)
                {
                    string[] fields = nodePair.Value;
                    int parent;
                    if (!int.TryParse(fields[0], out parent)) continue;
                    Node node;
                    if (fields.Length >= 3 && fields[1] == "set") node = new RuleSet(fields[2]);
                    else if (fields.Length >= 8 && fields[1] == "rule")
                        node = new Rule(Unesc(fields[3]), Unesc(fields[4]), fields[5], fields[6], Unesc(string.Join("|", fields.Skip(7))), Unesc(fields[2]));
                    else continue;
                    built[nodePair.Key] = node;
                    if (parent < 0)
                    {
                        if (node.IsSet && root == null) root = (RuleSet)node;
                    }
                    else
                    {
                        Node holder;
                        if (built.TryGetValue(parent, out holder) && holder.IsSet) ((RuleSet)holder).Items.Add(node);
                    }
                }
                output[pair.Key] = new Template(pair.Key, pair.Value.Categories, pair.Value.Labels, root);
            }
            return output;
        }

        public static bool SameTemplate(Template a, Template b)
        {
            return TemplateLines(a.Copy("x")).SequenceEqual(TemplateLines(b.Copy("x")));
        }

        public static Dictionary<string, Template> LoadLibrary(string path = null)
        {
            return ParseTemplates(WsmCore.ReadLines(path ?? LibraryPath));
        }

        public static bool SaveLibrary(Dictionary<string, Template> library, string path = null)
        {
            var lines = new List<string> { "# RevoBIM - Workset Management routine templates", "format=" + FormatVersion };
            foreach (string name in WsmCore.SortedNatural(library.Keys)) lines.AddRange(TemplateLines(library[name]));
            return WsmCore.WriteLines(path ?? LibraryPath, lines);
        }

        /// <summary>name, or 'name (2)', 'name (3)' ... - whichever is free, ignoring case.</summary>
        public static string UniqueName(string name, IEnumerable<string> taken)
        {
            var lower = new HashSet<string>(taken.Select(t => Txt(t).ToLowerInvariant()));
            string baseName = Txt(name).Trim();
            if (baseName.Length == 0) baseName = "Routine";
            if (!lower.Contains(baseName.ToLowerInvariant())) return baseName;
            int number = 2;
            while (lower.Contains((baseName + " (" + number + ")").ToLowerInvariant())) number++;
            return baseName + " (" + number + ")";
        }

        // ================================================================ assigner state

        /// <summary>The order worksets are applied in, and for each either ticked categories or one routine template - never both.</summary>
        public class AssignState
        {
            public List<string> Order = new List<string>();
            public Dictionary<string, HashSet<string>> Categories = new Dictionary<string, HashSet<string>>();
            public Dictionary<string, string> Routines = new Dictionary<string, string>();

            public string Mode(string workset)
            {
                string r; HashSet<string> c;
                if (Routines.TryGetValue(workset, out r) && r.Length > 0) return ModeRoutine;
                if (Categories.TryGetValue(workset, out c) && c.Count > 0) return ModeCategories;
                return ModeNone;
            }

            public void SetCategories(string workset, IEnumerable<string> keys)
            {
                var set = new HashSet<string>(keys);
                if (set.Count > 0) { Categories[workset] = set; Routines.Remove(workset); }
                else Categories.Remove(workset);
            }

            public void SetRoutine(string workset, string name)
            {
                if (!string.IsNullOrEmpty(name)) { Routines[workset] = Txt(name); Categories.Remove(workset); }
                else Routines.Remove(workset);
            }

            public void Clear(string workset = null)
            {
                if (workset == null) { Categories = new Dictionary<string, HashSet<string>>(); Routines = new Dictionary<string, string>(); }
                else { Categories.Remove(workset); Routines.Remove(workset); }
            }

            public void RenameTemplate(string oldName, string newName)
            {
                foreach (string workset in Routines.Keys.ToList())
                    if (Routines[workset] == oldName) Routines[workset] = newName;
            }

            public void DropTemplate(string name)
            {
                foreach (string workset in Routines.Keys.ToList())
                    if (Routines[workset] == name) Routines.Remove(workset);
            }

            public List<string> UsersOf(string name)
            {
                return Order.Where(w => { string r; return Routines.TryGetValue(w, out r) && r == name; }).ToList();
            }

            public List<string> Active() { return Order.Where(w => Mode(w) != ModeNone).ToList(); }
        }

        /// <summary>Keep the saved order for worksets still in the model; any new workset goes on the end, in natural order.</summary>
        public static List<string> SyncOrder(IEnumerable<string> order, IEnumerable<string> names)
        {
            var present = new HashSet<string>(names);
            var kept = order.Where(present.Contains).ToList();
            var seen = new HashSet<string>(kept);
            var extra = WsmCore.SortedNatural(names.Where(n => !seen.Contains(n)));
            kept.AddRange(extra);
            return kept;
        }

        public static List<string> MoveItem(List<string> order, string name, int index)
        {
            if (!order.Contains(name)) return new List<string>(order);
            var output = order.Where(n => n != name).ToList();
            index = Math.Max(0, Math.Min(index, output.Count));
            output.Insert(index, name);
            return output;
        }

        /// <summary>Where a dragged row lands: rows are stacked top to bottom with these heights; y is the distance from the top.</summary>
        public static int DropIndex(IList<double> heights, double y)
        {
            double top = 0.0;
            for (int index = 0; index < heights.Count; index++)
            {
                if (y < top + heights[index] / 2.0) return index;
                top += heights[index];
            }
            return heights.Count;
        }

        public static List<string> Landing(List<string> order, string name, int insertIndex)
        {
            if (!order.Contains(name)) return new List<string>(order);
            int current = order.IndexOf(name);
            int target = insertIndex > current ? insertIndex - 1 : insertIndex;
            return MoveItem(order, name, target);
        }

        // ================================================================ resolving

        public class Resolved
        {
            public string Workset;
            public List<long> Kept = new List<long>();
            public Dictionary<string, int> Lost = new Dictionary<string, int>();
        }

        /// <summary>rows: [(workset, element ints)] top to bottom. The first workset to claim an element keeps it.</summary>
        public static List<Resolved> ResolveClaims(IEnumerable<KeyValuePair<string, List<long>>> rows)
        {
            var claimed = new Dictionary<long, string>();
            var output = new List<Resolved>();
            foreach (var row in rows)
            {
                var item = new Resolved { Workset = row.Key };
                var seen = new HashSet<long>();
                foreach (long element in row.Value)
                {
                    if (!seen.Add(element)) continue;
                    string winner;
                    if (!claimed.TryGetValue(element, out winner)) { claimed[element] = row.Key; item.Kept.Add(element); }
                    else if (winner != row.Key)
                    {
                        int n; item.Lost.TryGetValue(winner, out n); item.Lost[winner] = n + 1;
                    }
                }
                output.Add(item);
            }
            return output;
        }

        public class PlanEntry
        {
            public string Workset;
            public List<long> ToMove = new List<long>();
            public int Already;
            public Dictionary<string, int> Lost;
        }

        public static List<PlanEntry> PlanMoves(IEnumerable<Resolved> resolved, Dictionary<long, int> current, Dictionary<string, int> targets, out int total)
        {
            var plan = new List<PlanEntry>();
            total = 0;
            foreach (Resolved item in resolved)
            {
                int target;
                if (!targets.TryGetValue(item.Workset, out target)) continue;
                var toMove = item.Kept.Where(e => { int cur; return !(current.TryGetValue(e, out cur) && cur == target); }).ToList();
                plan.Add(new PlanEntry { Workset = item.Workset, ToMove = toMove, Already = item.Kept.Count - toMove.Count, Lost = item.Lost });
                total += toMove.Count;
            }
            return plan;
        }

        public static List<string> PlanLines(IEnumerable<PlanEntry> plan)
        {
            var lines = new List<string>();
            foreach (PlanEntry entry in plan)
            {
                string line = entry.Workset + ":  " + entry.ToMove.Count + " to move";
                if (entry.Already > 0) line += ", " + entry.Already + " already there";
                if (entry.Lost.Count > 0)
                    line += ", " + entry.Lost.Values.Sum() + " taken by worksets above (" + string.Join(", ", WsmCore.SortedNatural(entry.Lost.Keys)) + ")";
                lines.Add(line);
            }
            return lines;
        }

        // ================================================================ the routine file

        public static List<string> RoutineLines(AssignState state, Dictionary<string, Template> library, string project = "", string saved = "")
        {
            var lines = new List<string>
            {
                "# RevoBIM - Workset Management routine", "format=" + FormatVersion, "tool_version=" + WsmCore.Version,
            };
            if (project.Length > 0) lines.Add("project=" + Esc(project));
            if (saved.Length > 0) lines.Add("saved=" + Esc(saved));
            var used = new List<string>();
            for (int index = 0; index < state.Order.Count; index++)
            {
                string workset = state.Order[index];
                string mode = state.Mode(workset);
                if (mode == ModeCategories)
                    lines.Add("row." + index + "=" + Esc(workset) + "|categories|" + string.Join(";", state.Categories[workset].OrderBy(k => k, StringComparer.Ordinal).Select(Esc)));
                else if (mode == ModeRoutine)
                {
                    string name = state.Routines[workset];
                    lines.Add("row." + index + "=" + Esc(workset) + "|routine|" + Esc(name));
                    if (!used.Contains(name)) used.Add(name);
                }
                else lines.Add("row." + index + "=" + Esc(workset) + "|none");
            }
            foreach (string name in used)
            {
                Template template;
                if (library.TryGetValue(name, out template)) lines.AddRange(TemplateLines(template));
            }
            return lines;
        }

        public class RoutineRow { public string Workset; public string Mode; public List<string> Keys; public string Routine; }

        public class RoutineFile
        {
            public List<RoutineRow> Rows = new List<RoutineRow>();
            public Dictionary<string, Template> Templates = new Dictionary<string, Template>();
            public string Project = "";
            public List<string> Problems = new List<string>();
        }

        public static RoutineFile ParseRoutine(IEnumerable<string> allLines)
        {
            var lines = allLines.ToList();
            var parsed = new RoutineFile();
            var rows = new SortedDictionary<int, RoutineRow>();
            foreach (string line in lines)
            {
                string text = Txt(line).Trim();
                if (text.Length == 0 || text.StartsWith("#") || !text.Contains("=")) continue;
                int at = text.IndexOf('=');
                string key = text.Substring(0, at), value = text.Substring(at + 1);
                if (key == "project") parsed.Project = Unesc(value);
                else if (key.StartsWith("row."))
                {
                    int index;
                    if (!int.TryParse(key.Substring(4), out index)) continue;
                    string[] fields = value.Split('|');
                    string workset = Unesc(fields[0]).Trim();
                    if (workset.Length == 0) continue;
                    string mode = fields.Length > 1 ? fields[1] : ModeNone;
                    if (mode == ModeCategories)
                    {
                        var keys = (fields.Length > 2 ? fields[2] : "").Split(';').Where(k => k.Length > 0).Select(Unesc).ToList();
                        rows[index] = new RoutineRow { Workset = workset, Mode = ModeCategories, Keys = keys };
                    }
                    else if (mode == ModeRoutine && fields.Length > 2)
                        rows[index] = new RoutineRow { Workset = workset, Mode = ModeRoutine, Routine = Unesc(fields[2]) };
                    else rows[index] = new RoutineRow { Workset = workset, Mode = ModeNone };
                }
            }
            parsed.Rows = rows.Values.ToList();
            parsed.Templates = ParseTemplates(lines);
            foreach (RoutineRow row in parsed.Rows)
                if (row.Mode == ModeRoutine && !parsed.Templates.ContainsKey(row.Routine))
                    parsed.Problems.Add(row.Workset + ": routine '" + row.Routine + "' is not in the file");
            if (parsed.Rows.Count == 0) parsed.Problems.Add("the file holds no worksets - is it a workset routine?");
            return parsed;
        }

        private static string Squash(string name) { return Regex.Replace(Txt(name).ToLowerInvariant(), "[^a-z0-9]+", ""); }

        /// <summary>Similarity ratio in the manner of difflib.SequenceMatcher: 2 * matches / total.</summary>
        public static double SimilarityRatio(string a, string b)
        {
            int total = a.Length + b.Length;
            if (total == 0) return 1.0;
            return 2.0 * Matching(a, 0, a.Length, b, 0, b.Length) / total;
        }

        private static int Matching(string a, int alo, int ahi, string b, int blo, int bhi)
        {
            int bestI = alo, bestJ = blo, bestSize = 0;
            for (int i = alo; i < ahi; i++)
            {
                for (int j = blo; j < bhi; j++)
                {
                    int k = 0;
                    while (i + k < ahi && j + k < bhi && a[i + k] == b[j + k]) k++;
                    if (k > bestSize) { bestI = i; bestJ = j; bestSize = k; }
                }
            }
            if (bestSize == 0) return 0;
            return bestSize + Matching(a, alo, bestI, b, blo, bestJ) + Matching(a, bestI + bestSize, ahi, b, bestJ + bestSize, bhi);
        }

        /// <summary>{file workset: project workset or null}: exact, then ignoring case, then punctuation, then close names. None offered twice.</summary>
        public static Dictionary<string, string> SuggestMapping(IList<string> fileNames, IEnumerable<string> projectNames)
        {
            var result = new Dictionary<string, string>();
            foreach (string n in fileNames) result[n] = null;
            var free = projectNames.ToList();
            Action<Func<string, string, bool>> take = test =>
            {
                foreach (string name in fileNames)
                {
                    if (result[name] != null) continue;
                    foreach (string candidate in free)
                    {
                        if (test(name, candidate)) { result[name] = candidate; free.Remove(candidate); break; }
                    }
                }
            };
            take((a, b) => a == b);
            take((a, b) => a.ToLowerInvariant() == b.ToLowerInvariant());
            take((a, b) => Squash(a).Length > 0 && Squash(a) == Squash(b));
            var scored = new List<Tuple<double, string, string>>();
            foreach (string name in fileNames)
            {
                if (result[name] != null) continue;
                foreach (string candidate in free)
                {
                    double ratio = SimilarityRatio(Squash(name), Squash(candidate));
                    if (ratio >= 0.8) scored.Add(Tuple.Create(ratio, name, candidate));
                }
            }
            foreach (var item in WsmCore.StableSort(scored, (p, q) => p.Item1.CompareTo(q.Item1), true))
            {
                if (result[item.Item2] == null && free.Contains(item.Item3)) { result[item.Item2] = item.Item3; free.Remove(item.Item3); }
            }
            return result;
        }

        public static List<string> MappingProblems(Dictionary<string, string> mapping)
        {
            var seen = new Dictionary<string, string>();
            var problems = new List<string>();
            foreach (var pair in mapping)
            {
                if (string.IsNullOrEmpty(pair.Value)) continue;
                string other;
                if (seen.TryGetValue(pair.Value, out other)) problems.Add(other + " and " + pair.Key + " both point at " + pair.Value);
                else seen[pair.Value] = pair.Key;
            }
            return problems;
        }

        /// <summary>Bring a file's templates into the library. An identical one is reused; a different one with a taken name comes in as 'name (2)'.</summary>
        public static Dictionary<string, string> MergeTemplates(Dictionary<string, Template> library, Dictionary<string, Template> incoming)
        {
            var renamed = new Dictionary<string, string>();
            foreach (string name in WsmCore.SortedNatural(incoming.Keys))
            {
                Template template = incoming[name], existing;
                library.TryGetValue(name, out existing);
                if (existing != null && SameTemplate(existing, template)) { renamed[name] = name; continue; }
                string final = existing == null ? name : UniqueName(name, library.Keys);
                library[final] = template.Copy(final);
                renamed[name] = final;
            }
            return renamed;
        }

        /// <summary>Put a parsed routine file into the state. The file's order goes first, then any workset it does not mention.</summary>
        public static List<string> ApplyRoutine(AssignState state, RoutineFile parsed, Dictionary<string, string> mapping, Dictionary<string, string> renamed,
                                                ISet<string> knownKeys, IEnumerable<string> projectNames)
        {
            var skipped = new List<string>();
            var order = new List<string>();
            foreach (RoutineRow row in parsed.Rows)
            {
                string target;
                if (!mapping.TryGetValue(row.Workset, out target) || string.IsNullOrEmpty(target))
                {
                    if (row.Mode != ModeNone) skipped.Add(row.Workset + ": not mapped to a workset in this model");
                    continue;
                }
                if (order.Contains(target)) continue;
                order.Add(target);
                if (row.Mode == ModeCategories)
                {
                    var keys = row.Keys.Where(k => knownKeys == null || knownKeys.Contains(k)).ToList();
                    int missing = row.Keys.Count - keys.Count;
                    if (missing > 0) skipped.Add(target + ": " + missing + " categor" + (missing == 1 ? "y" : "ies") + " not in this model");
                    state.SetCategories(target, keys);
                    if (keys.Count == 0) state.Clear(target);
                }
                else if (row.Mode == ModeRoutine)
                {
                    string name;
                    if (renamed.TryGetValue(row.Routine, out name) && name.Length > 0) state.SetRoutine(target, name);
                    else { state.Clear(target); skipped.Add(target + ": routine '" + row.Routine + "' was not in the file"); }
                }
                else state.Clear(target);
            }
            var rest = state.Order.Where(n => !order.Contains(n)).ToList();
            order.AddRange(rest);
            state.Order = SyncOrder(order, projectNames);
            return skipped;
        }

        public static string StatePath(string title) { return Path.Combine(StateDir, WsmCore.ProjectKey(title) + ".state.txt"); }

        public static AssignState LoadState(string title, IList<string> projectNames, Dictionary<string, Template> library)
        {
            var state = new AssignState();
            RoutineFile parsed = ParseRoutine(WsmCore.ReadLines(StatePath(title)));
            var present = new HashSet<string>(projectNames);
            var mapping = new Dictionary<string, string>();
            foreach (RoutineRow row in parsed.Rows) if (present.Contains(row.Workset)) mapping[row.Workset] = row.Workset;
            var renamed = library.Keys.ToDictionary(k => k, k => k);
            ApplyRoutine(state, parsed, mapping, renamed, null, projectNames);
            state.Order = SyncOrder(state.Order, projectNames);
            return state;
        }

        public static bool SaveState(string title, AssignState state)
        {
            return WsmCore.WriteLines(StatePath(title), RoutineLines(state, new Dictionary<string, Template>()));
        }
    }
}

