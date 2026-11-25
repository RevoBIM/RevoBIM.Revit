using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.AddinManager
{
    /// <summary>
    /// Revit's KeyboardShortcuts.xml, edited as text (a machine-written flat file: an XML round trip would reorder and
    /// re-quote the whole file, and one Revit rejects costs the user every shortcut). Port of rba_shortcuts.py.
    /// </summary>
    internal static class AmShortcuts
    {
        private static readonly Regex Item = new Regex(@"<ShortcutItem\b[^>]*/>", RegexOptions.IgnoreCase | RegexOptions.Compiled);
        private static readonly Regex Attr = new Regex("(\\w+)\\s*=\\s*\"([^\"]*)\"", RegexOptions.Compiled);
        private static readonly Regex ShortcutsAttr = new Regex("Shortcuts\\s*=\\s*\"[^\"]*\"", RegexOptions.Compiled);
        private const char Separator = '#';

        public static string PathFor(string version)
        {
            string baseDir = Environment.GetEnvironmentVariable("APPDATA") ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            return Path.Combine(baseDir, "Autodesk", "Revit", "Autodesk Revit " + version, "KeyboardShortcuts.xml");
        }

        public static string ReadFile(string path)
        {
            try { return File.Exists(path) ? File.ReadAllText(path, Encoding.UTF8) : ""; }
            catch (Exception) { return ""; }
        }

        public static List<Dictionary<string, string>> Parse(string text)
        {
            var items = new List<Dictionary<string, string>>();
            foreach (Match match in Item.Matches(text ?? ""))
            {
                var attributes = new Dictionary<string, string>();
                foreach (Match a in Attr.Matches(match.Value)) attributes[a.Groups[1].Value] = a.Groups[2].Value;
                attributes["_raw"] = match.Value;
                items.Add(attributes);
            }
            return items;
        }

        private static string Get(Dictionary<string, string> item, string key)
        {
            string v;
            return item.TryGetValue(key, out v) ? v : "";
        }

        public static List<string> KeysOf(Dictionary<string, string> item)
        {
            return Get(item, "Shortcuts").Split(Separator).Select(p => p.Trim()).Where(p => p.Length > 0).ToList();
        }

        /// <summary>Upper case and Revit's modifier order, so "ctrl+shift+s" and "Shift+Ctrl+S" compare equal.</summary>
        public static string NormaliseKeys(string keys)
        {
            string text = (keys ?? "").Trim().ToUpperInvariant().Replace(" ", "");
            if (!text.Contains("+")) return text;
            string[] parts = text.Split('+').Where(p => p.Length > 0).ToArray();
            string[] order = { "CTRL", "SHIFT", "ALT" };
            var modifiers = parts.Where(p => order.Contains(p)).OrderBy(p => Array.IndexOf(order, p)).ToList();
            var rest = parts.Where(p => !order.Contains(p)).ToList();
            return string.Join("+", modifiers.Concat(rest));
        }

        public static List<Dictionary<string, string>> FindConflicts(List<Dictionary<string, string>> items, string keys, string commandId)
        {
            string wanted = NormaliseKeys(keys);
            var result = new List<Dictionary<string, string>>();
            if (wanted.Length == 0) return result;
            foreach (var item in items)
            {
                if (!string.IsNullOrEmpty(commandId) && Get(item, "CommandId") == commandId) continue;
                if (KeysOf(item).Any(k => NormaliseKeys(k) == wanted)) result.Add(item);
            }
            return result;
        }

        public static string Describe(Dictionary<string, string> item)
        {
            string name = Get(item, "CommandName");
            if (name.Length == 0) name = Get(item, "Command");
            string paths = Get(item, "Paths").Replace(";", ", ");
            if (name.Length > 0 && paths.Length > 0) return name + "  (" + paths + ")";
            if (name.Length > 0) return name;
            if (paths.Length > 0) return paths;
            string id = Get(item, "CommandId");
            return id.Length > 0 ? id : "unknown command";
        }

        private static Dictionary<string, string> FindItem(List<Dictionary<string, string>> items, string commandId)
        {
            return items.FirstOrDefault(i => Get(i, "CommandId") == commandId);
        }

        private static string Escape(string v)
        {
            return (v ?? "").Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace("\"", "&quot;");
        }

        /// <summary>Sets the shortcut on a command and returns the new file text. An existing entry only has its Shortcuts attribute rewritten.</summary>
        public static string Upsert(string text, string commandId, string name, string paths, string keys)
        {
            text = text ?? "";
            keys = NormaliseKeys(keys);
            var existing = FindItem(Parse(text), commandId);
            if (existing != null)
            {
                string raw = existing["_raw"];
                string updated;
                if (raw.Contains("Shortcuts="))
                {
                    string attr = "Shortcuts=\"" + Escape(keys) + "\"";
                    updated = ShortcutsAttr.Replace(raw, attr.Replace("$", "$$"), 1);
                }
                else
                {
                    updated = raw.Substring(0, raw.Length - 2).TrimEnd() + " Shortcuts=\"" + Escape(keys) + "\" />";
                }
                int at = text.IndexOf(raw, StringComparison.Ordinal);
                return text.Substring(0, at) + updated + text.Substring(at + raw.Length);
            }
            string line = "\t<ShortcutItem CommandName=\"" + Escape(name) + "\" CommandId=\"" + Escape(commandId) +
                          "\" Shortcuts=\"" + Escape(keys) + "\" Paths=\"" + Escape(paths) + "\" />\n";
            Match closing = Regex.Match(text, "</Shortcuts>", RegexOptions.IgnoreCase);
            if (closing.Success) return text.Substring(0, closing.Index) + line + text.Substring(closing.Index);
            if (text.Trim().Length > 0) return text.TrimEnd() + "\n" + line;
            return "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<Shortcuts>\n" + line + "</Shortcuts>\n";
        }

        /// <summary>Takes one shortcut off a command, leaving any others it has.</summary>
        public static string Remove(string text, string commandId, string keys)
        {
            text = text ?? "";
            var existing = FindItem(Parse(text), commandId);
            if (existing == null) return text;
            string wanted = NormaliseKeys(keys);
            var kept = KeysOf(existing).Where(k => NormaliseKeys(k) != wanted).ToList();
            string raw = existing["_raw"];
            string attr = "Shortcuts=\"" + Escape(string.Join(Separator.ToString(), kept)) + "\"";
            string updated = ShortcutsAttr.Replace(raw, attr.Replace("$", "$$"), 1);
            int at = text.IndexOf(raw, StringComparison.Ordinal);
            return text.Substring(0, at) + updated + text.Substring(at + raw.Length);
        }

        public static List<string> CurrentKeys(string text, string commandId)
        {
            var item = FindItem(Parse(text), commandId);
            return item == null ? new List<string>() : KeysOf(item);
        }

        /// <summary>Writes, keeping one backup beside the file first.</summary>
        public static bool WriteFile(string path, string text)
        {
            try
            {
                if (File.Exists(path))
                {
                    try { File.Copy(path, path + ".revobim.bak", true); }
                    catch (Exception err) { AmCore.LogException("shortcuts/backup", err); }
                }
                string folder = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(folder)) Directory.CreateDirectory(folder);
                File.WriteAllText(path, text ?? "", new UTF8Encoding(false));
                AmCore.Log("shortcuts written to " + path);
                return true;
            }
            catch (Exception err)
            {
                AmCore.LogException("shortcuts/write", err);
                return false;
            }
        }
    }
}
