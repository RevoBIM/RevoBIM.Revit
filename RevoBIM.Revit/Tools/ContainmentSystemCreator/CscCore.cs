using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.ContainmentSystemCreator
{
    /// <summary>A containment kind and every naming token it answers to.</summary>
    public sealed class Kind
    {
        public string Label;
        public List<string> Aliases;

        public Kind(string label, IEnumerable<string> aliases = null)
        {
            Label = label;
            var names = aliases != null ? aliases.ToList() : new List<string> { label };
            if (!names.Contains(label)) names.Add(label);
            // longest first, so the most specific spelling wins
            Aliases = names.OrderBy(a => -CscCore.Norm(a).Length).ToList();
        }

        /// <summary>
        /// The longest alias present in text, spelled as the text spells it. Returning the spelling found rather than
        /// the alias definition matters: grafting the kind onto a new type name must reproduce the model's own
        /// spelling ("TrunkingTray"), not the canonical one ("Trunking Tray").
        /// </summary>
        public string MatchIn(string text)
        {
            if (string.IsNullOrEmpty(text)) return null;
            foreach (string alias in Aliases)
            {
                int[] span = CscCore.KindTokenSpan(text, alias);
                if (span != null)
                {
                    string[] parts = CscCore.SplitParts(text);
                    return string.Concat(parts.Skip(2 * span[0]).Take(2 * span[1] - 1 - 2 * span[0]));
                }
            }
            return null;
        }
    }

    /// <summary>Containment System Creator - the pure naming rules (the first half of script.py): kinds, tokens, prefixes.</summary>
    public static class CscCore
    {
        public const string Version = "1.4.1";
        public const string ToolName = "Containment System Creator";
        public const string ToolKey = "containment_system_creator";

        public static readonly KeyValuePair<string, string[]>[] TrayKindDefs =
        {
            new KeyValuePair<string, string[]>("Cable Tray", new[] { "Cable Tray", "CableTray", "Tray" }),
            new KeyValuePair<string, string[]>("Cable Ladder", new[] { "Cable Ladder", "CableLadder", "Ladder" }),
            new KeyValuePair<string, string[]>("Cable Trunking", new[] { "Trunking Tray", "TrunkingTray", "Trunking" }),
            new KeyValuePair<string, string[]>("Cable Basket", new[] { "Cable Basket", "CableBasket", "Basket" }),
        };

        public const string Unfiltered = "All types (kind auto-detected)";

        public static readonly KeyValuePair<string, string>[] FitSchemes =
        {
            new KeyValuePair<string, string>("Full prefix   e.g.  BGL_Ladder_ELV", "full"),
            new KeyValuePair<string, string>("Name only     e.g.  ELV", "name"),
            new KeyValuePair<string, string>("Swap token    e.g.  LV Sub-Main -> ELV", "swap"),
        };

        public static readonly string[] MarkParamNames = { "BGL_Type Mark", "BGL_TypeMark", "BGL_Type_Mark" };

        public static readonly Regex BadName = new Regex(@"[\\:{}\[\]|;<>?`~]");

        /// <summary>Lower-case, alphanumerics only.</summary>
        public static string Norm(string text)
        {
            if (string.IsNullOrEmpty(text)) return "";
            return Regex.Replace(text.ToLowerInvariant(), "[^a-z0-9]", "");
        }

        /// <summary>Normalised string plus a map from normalised index to original index.</summary>
        public static string NormMap(string text, out List<int> map)
        {
            var chars = new StringBuilder();
            map = new List<int>();
            for (int i = 0; i < text.Length; i++)
            {
                if (char.IsLetterOrDigit(text[i]))
                {
                    chars.Append(char.ToLowerInvariant(text[i]));
                    map.Add(i);
                }
            }
            return chars.ToString();
        }

        /// <summary>Replace find inside text ignoring case and separators ("LV Sub-Main" with find "LV_SubMain" gives repl). Null if not found.</summary>
        public static string LooseReplace(string text, string find, string repl)
        {
            List<int> imap, unused;
            string ntext = NormMap(text, out imap);
            string nfind = NormMap(find, out unused);
            if (nfind.Length == 0 || ntext.Length == 0) return null;
            int pos = ntext.IndexOf(nfind, StringComparison.Ordinal);
            if (pos < 0) return null;
            int start = imap[pos];
            int end = imap[pos + nfind.Length - 1] + 1;
            return text.Substring(0, start) + repl + text.Substring(end);
        }

        /// <summary>Split on separators keeping them, so the name can be rebuilt exactly. Tokens land on even indices, separators on odd ones.</summary>
        public static string[] SplitParts(string name)
        {
            return Regex.Split(name ?? "", @"([_\s\-]+)");
        }

        /// <summary>The word tokens of a name, index-aligned with SplitParts.</summary>
        public static List<string> RawTokens(string name)
        {
            string[] parts = SplitParts(name);
            var tokens = new List<string>();
            for (int i = 0; i < parts.Length; i += 2) tokens.Add(parts[i]);
            return tokens;
        }

        /// <summary>Find kind as a whole run of tokens. Returns (start, end) or null. "BGL_FlexConduit_LV" + "Conduit" gives null.</summary>
        public static int[] KindTokenSpan(string typeName, string kind)
        {
            string needle = Norm(kind);
            if (needle.Length == 0) return null;
            List<string> toks = RawTokens(typeName).Select(Norm).ToList();
            for (int i = 0; i < toks.Count; i++)
            {
                string joined = "";
                for (int j = i; j < toks.Count; j++)
                {
                    joined += toks[j];
                    if (joined == needle) return new[] { i, j + 1 };
                    if (joined.Length > needle.Length) break;
                }
            }
            return null;
        }

        public static List<Kind> TrayKinds()
        {
            return TrayKindDefs.Select(d => new Kind(d.Key, d.Value)).ToList();
        }

        /// <summary>The kind with the longest alias matching text, and that alias; (null, null) if none.</summary>
        public static Kind BestKind(IEnumerable<Kind> kinds, string text, out string alias)
        {
            Kind winner = null;
            alias = null;
            int bestLen = -1;
            foreach (Kind kind in kinds)
            {
                string a = kind.MatchIn(text);
                if (a == null) continue;
                int length = Norm(a).Length;
                if (length > bestLen)
                {
                    winner = kind;
                    alias = a;
                    bestLen = length;
                }
            }
            return winner;
        }

        /// <summary>
        /// The part of a system family name that actually says something. Every Cable Tray type lives in a family called
        /// "Cable Tray with Fittings", so the raw name would match the generic "Cable Tray" kind for Trunking and Basket
        /// types too; strip the "with/without fittings" suffix, and if what is left is just the category name there is no signal.
        /// </summary>
        public static string FamilySignal(string familyName)
        {
            string stripped = Regex.Replace(familyName ?? "", @"with(out)?\s+fittings\s*$", "", RegexOptions.IgnoreCase).Trim(' ', '_', '-');
            string n = Norm(stripped);
            if (n == "cabletray" || n == "conduit" || n.Length == 0) return "";
            return stripped;
        }

        /// <summary>
        /// Works out which containment kind a system type belongs to: the type name first, then the system family name, then the
        /// fitting family names. nameAlias is the alias found in the type name itself (null when it came from elsewhere).
        /// </summary>
        public static Kind AssignKind(string name, string familyName, IEnumerable<string> fittingFamilyNames, List<Kind> kinds,
                                      out string alias, out string nameAlias)
        {
            Kind kind = BestKind(kinds, name, out alias);
            if (kind != null)
            {
                nameAlias = alias;
                return kind;
            }
            nameAlias = null;
            kind = BestKind(kinds, FamilySignal(familyName), out alias);
            if (kind != null) return kind;
            Kind winner = null;
            string winningAlias = null;
            int bestLen = -1;
            foreach (string family in fittingFamilyNames)
            {
                string a;
                Kind found = BestKind(kinds, family, out a);
                if (found == null) continue;
                int length = Norm(a).Length;
                if (length > bestLen)
                {
                    winner = found;
                    winningAlias = a;
                    bestLen = length;
                }
            }
            alias = winningAlias;
            return winner;
        }

        /// <summary>How many leading tokens every name shares (the company prefix).</summary>
        public static int CommonTokenDepth(IEnumerable<string> names)
        {
            List<List<string>> lists = names.Where(n => !string.IsNullOrEmpty(n)).Select(RawTokens).Where(t => t.Count > 0).ToList();
            if (lists.Count == 0) return 0;
            if (lists.Count == 1) return lists[0].Count > 1 ? 1 : 0;
            int depth = 0;
            int shortest = lists.Min(t => t.Count);
            while (depth < shortest - 1)
            {
                string first = lists[0][depth].ToLowerInvariant();
                if (lists.All(t => t[depth].ToLowerInvariant() == first)) depth++;
                else break;
            }
            return depth;
        }

        /// <summary>Auto-detects the containment kind tokens present in a set of names.</summary>
        public static List<string> DetectKinds(List<string> names, out int depth)
        {
            depth = CommonTokenDepth(names);
            var found = new List<string>();
            var seen = new HashSet<string>();
            foreach (string name in names)
            {
                List<string> toks = RawTokens(name);
                string tok;
                if (toks.Count > depth) tok = toks[depth];
                else if (toks.Count > 0) tok = toks[toks.Count - 1];
                else continue;
                if (string.IsNullOrEmpty(tok)) continue;
                if (seen.Add(tok.ToLowerInvariant())) found.Add(tok);
            }
            return found.OrderBy(s => s.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        /// <summary>(prefix, separator) for building the new type name: "BGL_Ladder_LV_SubMain" + alias "Ladder" gives ("BGL_Ladder", "_").</summary>
        public static void PrefixAndSep(string sourceName, string alias, int autoDepth, out string prefix, out string sep)
        {
            string[] parts = SplitParts(sourceName);
            int tokenCount = (parts.Length + 1) / 2;
            int[] span = alias != null ? KindTokenSpan(sourceName, alias) : null;
            int lastToken = span != null ? span[1] - 1 : autoDepth;
            if (lastToken > tokenCount - 1) lastToken = tokenCount - 1;
            if (lastToken < 0) lastToken = 0;
            int cut = 2 * lastToken + 1;
            prefix = string.Concat(parts.Take(cut));
            sep = parts.Length > cut ? parts[cut] : "_";
        }

        /// <summary>The part of the source name that names the service, e.g. LV_SubMain.</summary>
        public static string ServiceToken(string sourceName, string prefix, string sep)
        {
            string tail = sourceName.Substring(Math.Min(prefix.Length, sourceName.Length));
            if (tail.StartsWith(sep, StringComparison.Ordinal)) tail = tail.Substring(sep.Length);
            return tail.Trim('_', '-', ' ');
        }

        /// <summary>The leading tokens every type in the class shares, e.g. "BGL".</summary>
        public static void SharedStem(string sourceName, int autoDepth, out string stem, out string sep)
        {
            string[] parts = SplitParts(sourceName);
            int tokenCount = (parts.Length + 1) / 2;
            int last = autoDepth - 1;
            if (last > tokenCount - 1) last = tokenCount - 1;
            if (last < 0)
            {
                stem = "";
                sep = "_";
                return;
            }
            int cut = 2 * last + 1;
            stem = string.Concat(parts.Take(cut));
            sep = parts.Length > cut ? parts[cut] : "_";
        }

        /// <summary>Where the fixed prefix ends and the editable service name begins.</summary>
        public static void EditSplit(string name, string nameAlias, int autoDepth, out string prefix, out string sep)
        {
            if (nameAlias != null) PrefixAndSep(name, nameAlias, autoDepth, out prefix, out sep);
            else SharedStem(name, autoDepth, out prefix, out sep);
        }

        /// <summary>
        /// The type name the naming rule produces, before any user override. Kind token in the type name: cut there and append;
        /// kind only known from the family naming: graft the kind token onto the shared stem; no kind at all: shared stem plus
        /// the next token.
        /// </summary>
        public static string SuggestTypeName(string sourceName, string nameAlias, string kindAlias, int autoDepth, string newName)
        {
            if (sourceName == null || string.IsNullOrEmpty(newName)) return "";
            string prefix, sep;
            if (nameAlias != null)
            {
                PrefixAndSep(sourceName, nameAlias, autoDepth, out prefix, out sep);
                return prefix + sep + newName;
            }
            if (kindAlias != null)
            {
                SharedStem(sourceName, autoDepth, out prefix, out sep);
                if (prefix.Length > 0) return prefix + sep + kindAlias + sep + newName;
                return kindAlias + "_" + newName;
            }
            PrefixAndSep(sourceName, null, autoDepth, out prefix, out sep);
            return prefix + sep + newName;
        }
    }
}
