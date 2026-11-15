// Port of ps_naming.py (Pro Sheets Exporter).
//
// The custom file name engine. No WPF and no Revit in here: every rule that
// decides what a file ends up called is a plain function over plain data.
//
// A name is built from an ordered list of rules. Each rule is one parameter
// plus a prefix, a suffix and a separator:
//
//     prefix + value + suffix   then the separator, before the next segment
//
// The separator belongs to the segment it FOLLOWS: Sheet Number with separator
// "-" then Sheet Name gives "Sheet Number-Sheet Name". The last rule's
// separator is dropped, so a trailing "-" on the bottom row costs nothing.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.ProSheets
{
    public static partial class PsNaming
    {
        // Windows forbids these outright in a file name.
        public const string Illegal = "\\/:*?\"<>|";

        // ...and reserves these whole names, with or without an extension.
        public static readonly HashSet<string> Reserved = new HashSet<string>(StringComparer.Ordinal)
        {
            "CON", "PRN", "AUX", "NUL",
            "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
            "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
        };

        public const int MaxSegment = 160;

        /// <summary>One row of the Custom File Name dialog.</summary>
        public class Rule : IEquatable<Rule>
        {
            public string Param { get; set; }
            public string Prefix { get; set; }
            public string Suffix { get; set; }
            public string Separator { get; set; }

            public Rule(string param, string prefix = "", string suffix = "", string separator = "")
            {
                Param = param ?? "";
                Prefix = prefix ?? "";
                Suffix = suffix ?? "";
                Separator = separator ?? "";
            }

            public override string ToString()
            {
                return string.Format("Rule('{0}', '{1}', '{2}', '{3}')", Param, Prefix, Suffix, Separator);
            }

            public bool Equals(Rule other)
            {
                if (ReferenceEquals(other, null))
                    return false;
                return Param == other.Param && Prefix == other.Prefix
                       && Suffix == other.Suffix && Separator == other.Separator;
            }

            public override bool Equals(object obj)
            {
                return Equals(obj as Rule);
            }

            public override int GetHashCode()
            {
                unchecked
                {
                    int hash = 17;
                    hash = hash * 31 + (Param ?? "").GetHashCode();
                    hash = hash * 31 + (Prefix ?? "").GetHashCode();
                    hash = hash * 31 + (Suffix ?? "").GetHashCode();
                    hash = hash * 31 + (Separator ?? "").GetHashCode();
                    return hash;
                }
            }

            public static bool operator ==(Rule left, Rule right)
            {
                if (ReferenceEquals(left, right))
                    return true;
                if (ReferenceEquals(left, null))
                    return false;
                return left.Equals(right);
            }

            public static bool operator !=(Rule left, Rule right)
            {
                return !(left == right);
            }
        }

        /// <summary>
        /// Read the ordered rules out of a profile dictionary.
        /// Rules are numbered from 1. A gap in the numbering is stepped over rather
        /// than treated as the end, so a hand-edited profile file that deletes rule 2
        /// still loads rules 1 and 3.
        /// </summary>
        public static List<Rule> RulesFromStore(IDictionary<string, string> store, string prefixKey = "name")
        {
            int count;
            try
            {
                store.TryGetValue(prefixKey + ".rule_count", out string raw);
                if (string.IsNullOrEmpty(raw))
                    count = 0;
                else
                    count = PsConfig.PyInt(raw);
            }
            catch (Exception)
            {
                count = 0;
            }
            if (count <= 0)
            {
                // No count written. Probe forward a reasonable distance anyway.
                count = 40;
            }
            var rules = new List<Rule>();
            for (int index = 1; index <= count; index++)
            {
                string bas = string.Format("{0}.rule.{1}.", prefixKey, index);
                if (!store.TryGetValue(bas + "param", out string param) || param == null || param.Trim().Length == 0)
                    continue;
                rules.Add(new Rule(param,
                                   Get(store, bas + "prefix"),
                                   Get(store, bas + "suffix"),
                                   Get(store, bas + "sep")));
            }
            return rules;
        }

        private static string Get(IDictionary<string, string> store, string key)
        {
            return store.TryGetValue(key, out string value) ? value : "";
        }

        /// <summary>Write the rules back into a profile dictionary, clearing old numbers.</summary>
        public static IDictionary<string, string> RulesToStore(IList<Rule> rules, IDictionary<string, string> store, string prefixKey = "name")
        {
            var stale = store.Keys.Where(key => key.StartsWith(prefixKey + ".rule.", StringComparison.Ordinal)).ToList();
            foreach (string key in stale)
            {
                try { store.Remove(key); }
                catch (Exception) { }
            }
            store[prefixKey + ".rule_count"] = rules.Count.ToString(System.Globalization.CultureInfo.InvariantCulture);
            int index = 1;
            foreach (Rule rule in rules)
            {
                string bas = string.Format("{0}.rule.{1}.", prefixKey, index);
                store[bas + "param"] = rule.Param;
                store[bas + "prefix"] = rule.Prefix;
                store[bas + "suffix"] = rule.Suffix;
                store[bas + "sep"] = rule.Separator;
                index++;
            }
            return store;
        }

        /// <summary>
        /// Sheet Number, a hyphen, Sheet Name - what most registers want.
        /// Views have no number worth a file name, so Views mode starts from the
        /// view's own name instead.
        /// </summary>
        public static List<Rule> DefaultRules(string mode = "sheets")
        {
            if (mode == "views")
                return new List<Rule> { new Rule("View Name") };
            return new List<Rule> { new Rule("Sheet Number", separator: "-"), new Rule("Sheet Name") };
        }

        // Sheets keep the original "name." keys so a template written before 1.55.0
        // still opens with its naming; views get keys of their own.
        public static readonly Dictionary<string, string> ModeKeys = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "sheets", "name" },
            { "views", "vname" },
        };

        public static string ModeKey(string mode)
        {
            if (mode != null && ModeKeys.TryGetValue(mode, out string key))
                return key;
            return "name";
        }

        internal static bool HasRules(IDictionary<string, string> store, string prefixKey)
        {
            string marker = prefixKey + ".rule";
            foreach (string key in store.Keys)
            {
                if ((key ?? "").StartsWith(marker, StringComparison.Ordinal))
                    return true;
            }
            return false;
        }

        /// <summary>
        /// Both naming sets out of a profile, as {"sheets": [...], "views": [...]}.
        /// A profile from before 1.55.0 holds one set used for both. Sheets keep it.
        /// Views keep it too when somebody had changed it from the stock sheet name -
        /// that was their naming for views as much as sheets - and otherwise start
        /// from the view name.
        /// </summary>
        public static Dictionary<string, List<Rule>> RulesByMode(IDictionary<string, string> store)
        {
            store = store ?? new Dictionary<string, string>(StringComparer.Ordinal);
            List<Rule> sheets = RulesFromStore(store, ModeKey("sheets"));
            if (sheets.Count == 0)
                sheets = DefaultRules("sheets");
            List<Rule> views;
            if (HasRules(store, ModeKey("views")))
            {
                views = RulesFromStore(store, ModeKey("views"));
                if (views.Count == 0)
                    views = DefaultRules("views");
            }
            else if (!sheets.SequenceEqual(DefaultRules("sheets")))
            {
                views = sheets.Select(rule => new Rule(rule.Param, rule.Prefix, rule.Suffix, rule.Separator)).ToList();
            }
            else
            {
                views = DefaultRules("views");
            }
            return new Dictionary<string, List<Rule>>(StringComparer.Ordinal)
            {
                { "sheets", sheets },
                { "views", views },
            };
        }

        /// <summary>Write both naming sets into a profile.</summary>
        public static IDictionary<string, string> StoreRulesByMode(IDictionary<string, List<Rule>> sets, IDictionary<string, string> store)
        {
            foreach (string mode in new[] { "sheets", "views" })
            {
                List<Rule> rules = null;
                if (sets != null)
                    sets.TryGetValue(mode, out rules);
                if (rules == null || rules.Count == 0)
                    rules = DefaultRules(mode);
                RulesToStore(rules, store, ModeKey(mode));
            }
            return store;
        }

        /// <summary>
        /// Every rule turned into (text, separator), with empties dropped.
        /// lookup takes a parameter name and gives back its value as text, or an
        /// empty string where the parameter is missing or blank on this sheet.
        /// A rule whose value is empty AND which carries no prefix or suffix
        /// contributes nothing at all - not even its separator. Without that, a sheet
        /// with no revision yet comes out as 1101--CONTAINMENT and the run of
        /// separators looks like a bug in the tool rather than an empty parameter.
        /// </summary>
        public static List<(string Text, string Separator)> BuildSegments(IEnumerable<Rule> rules, Func<string, string> lookup)
        {
            var output = new List<(string Text, string Separator)>();
            foreach (Rule rule in rules)
            {
                string value;
                try
                {
                    value = lookup(rule.Param);
                }
                catch (Exception)
                {
                    value = "";
                }
                value = value == null ? "" : value.Trim();
                if (value.Length == 0 && rule.Prefix.Length == 0 && rule.Suffix.Length == 0)
                    continue;
                output.Add((rule.Prefix + value + rule.Suffix, rule.Separator));
            }
            return output;
        }

        /// <summary>Join (text, separator) pairs, dropping the last separator.</summary>
        public static string JoinSegments(IList<(string Text, string Separator)> segments)
        {
            if (segments == null || segments.Count == 0)
                return "";
            var parts = new StringBuilder();
            for (int index = 0; index < segments.Count; index++)
            {
                parts.Append(segments[index].Text);
                if (index < segments.Count - 1)
                    parts.Append(segments[index].Separator);
            }
            return parts.ToString();
        }

        private static readonly Regex Underscores = new Regex("_{3,}");

        /// <summary>
        /// A string Windows will accept as one path segment.
        /// Illegal characters become underscores rather than disappearing, because a
        /// silently shortened name is harder to spot than an obviously substituted
        /// one. Trailing dots and spaces go, since Windows drops them anyway and a
        /// name the tool reports is not the name that ends up on disk.
        /// </summary>
        public static string Sanitise(string text, string fallback = "unnamed")
        {
            string value = text ?? "";
            var output = new StringBuilder(value.Length);
            foreach (char ch in value)
            {
                if (Illegal.IndexOf(ch) >= 0 || ch < 32)
                    output.Append('_');
                else
                    output.Append(ch);
            }
            value = output.ToString().Trim();
            value = value.TrimEnd('.', ' ');
            value = Underscores.Replace(value, "__");
            if (value.Length == 0)
                return fallback;
            if (Reserved.Contains(value.Split('.')[0].ToUpperInvariant()))
                value = "_" + value;
            if (value.Length > MaxSegment)
                value = value.Substring(0, MaxSegment).TrimEnd('.', ' ');
            return value.Length > 0 ? value : fallback;
        }

        /// <summary>The finished, sanitised file name for one sheet or view.</summary>
        public static string BuildName(IList<Rule> rules, Func<string, string> lookup, string fallback = "unnamed")
        {
            if (rules == null || rules.Count == 0)
            {
                string number = lookup("Sheet Number");
                return Sanitise(string.IsNullOrEmpty(number) ? "" : number, fallback);
            }
            return Sanitise(JoinSegments(BuildSegments(rules, lookup)), fallback);
        }

        /// <summary>
        /// The Custom Name Preview line, using parameter names as sample values.
        /// Deliberately unsanitised - this is showing the shape of the name, and
        /// substituting an underscore for a character the user has just typed reads
        /// as the tool refusing it rather than warning about it.
        /// </summary>
        public static string Preview(IEnumerable<Rule> rules)
        {
            var segments = new List<(string Text, string Separator)>();
            foreach (Rule rule in rules)
                segments.Add((rule.Prefix + rule.Param + rule.Suffix, rule.Separator));
            string text = JoinSegments(segments);
            return text.Length > 0 ? text : "(nothing chosen)";
        }

        /// <summary>
        /// Make every name in a list unique, keeping the first of each clash.
        /// pairs is a list of (key, name). Returns a list of (key, name) in the
        /// same order, where a repeated name gains " (2)", " (3)" and so on.
        /// This matters more than it looks: two sheets whose chosen parameters happen
        /// to match would otherwise export one file and silently overwrite it with
        /// the other, and the count at the end would still say two.
        /// </summary>
        public static List<(TKey Key, string Name)> UniqueNames<TKey>(IEnumerable<(TKey Key, string Name)> pairs)
        {
            var seen = new Dictionary<string, int>(StringComparer.Ordinal);
            var output = new List<(TKey Key, string Name)>();
            foreach (var pair in pairs)
            {
                string bas = pair.Name ?? "None";
                string lowered = bas.ToLowerInvariant();
                if (!seen.ContainsKey(lowered))
                {
                    seen[lowered] = 1;
                    output.Add((pair.Key, bas));
                    continue;
                }
                int count = seen[lowered] + 1;
                string candidate = string.Format("{0} ({1})", bas, count);
                while (seen.ContainsKey(candidate.ToLowerInvariant()))
                {
                    count++;
                    candidate = string.Format("{0} ({1})", bas, count);
                }
                seen[lowered] = count;
                seen[candidate.ToLowerInvariant()] = 1;
                output.Add((pair.Key, candidate));
            }
            return output;
        }

        /// <summary>Which names in a list of (key, name) collide, as {lowered name: [keys]}.</summary>
        public static Dictionary<string, List<TKey>> Clashes<TKey>(IEnumerable<(TKey Key, string Name)> pairs)
        {
            var buckets = new Dictionary<string, List<TKey>>(StringComparer.Ordinal);
            foreach (var pair in pairs)
            {
                string lowered = (pair.Name ?? "None").ToLowerInvariant();
                if (!buckets.TryGetValue(lowered, out List<TKey> keys))
                {
                    keys = new List<TKey>();
                    buckets[lowered] = keys;
                }
                keys.Add(pair.Key);
            }
            return buckets.Where(entry => entry.Value.Count > 1)
                          .ToDictionary(entry => entry.Key, entry => entry.Value, StringComparer.Ordinal);
        }
    }
}
