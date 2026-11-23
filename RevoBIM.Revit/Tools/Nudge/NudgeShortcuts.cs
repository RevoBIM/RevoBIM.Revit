using System;
using System.IO;
using System.Linq;
using System.Xml;

namespace RevoBIM.Tools.Nudge
{
    /// <summary>
    /// Reads and writes Revit's KeyboardShortcuts.xml. Revit builds that file from the ribbon at startup
    /// and only reads it back at startup, so assigning a shortcut always costs a restart. Port of
    /// revobim.revit_shortcuts.
    /// </summary>
    public class NudgeShortcuts
    {
        private readonly XmlDocument doc;
        private readonly string path;

        private NudgeShortcuts(XmlDocument doc, string path)
        {
            this.doc = doc;
            this.path = path;
        }

        /// <summary>The shortcuts file of the running Revit, or null if it has not been created yet.</summary>
        public static NudgeShortcuts Open(string versionName)
        {
            try
            {
                string file = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                                           "Autodesk", "Revit", versionName, "KeyboardShortcuts.xml");
                if (!File.Exists(file)) return null;
                var xml = new XmlDocument();
                xml.Load(file);
                return new NudgeShortcuts(xml, file);
            }
            catch (Exception)
            {
                return null;
            }
        }

        private XmlElement[] Items() => doc.GetElementsByTagName("ShortcutItem").OfType<XmlElement>().ToArray();

        /// <summary>The item for a command. The button's own command id wins (the Modify tab copy has its own
        /// item with the same name); otherwise the command name, exact first, then contains.</summary>
        public XmlElement Find(string buttonName, string commandName)
        {
            XmlElement[] items = Items();
            string suffix = "%" + buttonName;
            XmlElement byId = items.FirstOrDefault(i => (i.GetAttribute("CommandId") ?? "").EndsWith(suffix, StringComparison.Ordinal));
            if (byId != null) return byId;

            string wanted = Normalise(commandName);
            XmlElement loose = null;
            foreach (XmlElement item in items)
            {
                string name = Normalise(item.GetAttribute("CommandName"));
                if (name == wanted) return item;
                if (loose == null && name.Contains(wanted)) loose = item;
            }
            return loose;
        }

        private static string Normalise(string text) =>
            string.Join(" ", (text ?? "").Split((char[])null, StringSplitOptions.RemoveEmptyEntries)).ToLowerInvariant();

        public static string GetKeys(XmlElement item) => item == null ? "" : (item.GetAttribute("Shortcuts") ?? "").Trim();

        public static void SetKeys(XmlElement item, string keys)
        {
            if (item == null) return;
            keys = (keys ?? "").Trim().ToUpperInvariant();
            if (keys.Length > 0) item.SetAttribute("Shortcuts", keys);
            else if (item.HasAttribute("Shortcuts")) item.RemoveAttribute("Shortcuts");
        }

        /// <summary>Names of the other commands already using any of these keystrokes.</summary>
        public System.Collections.Generic.List<string> Clashes(string keys, XmlElement ignore)
        {
            var wanted = Split(keys);
            var found = new System.Collections.Generic.List<string>();
            if (wanted.Count == 0) return found;
            string skip = ignore?.GetAttribute("CommandId");
            foreach (XmlElement item in Items())
            {
                if (!string.IsNullOrEmpty(skip) && item.GetAttribute("CommandId") == skip) continue;
                if (Split(GetKeys(item)).Overlaps(wanted))
                {
                    string name = item.GetAttribute("CommandName");
                    found.Add(string.IsNullOrEmpty(name) ? "(unnamed)" : name);
                }
            }
            return found;
        }

        /// <summary>Take these keystrokes off every other command that holds them. Returns the names of the commands changed.</summary>
        public System.Collections.Generic.List<string> TakeOff(string keys, XmlElement keep)
        {
            var wanted = Split(keys);
            var changed = new System.Collections.Generic.List<string>();
            if (wanted.Count == 0) return changed;
            string skip = keep?.GetAttribute("CommandId");
            foreach (XmlElement item in Items())
            {
                if (!string.IsNullOrEmpty(skip) && item.GetAttribute("CommandId") == skip) continue;
                var have = Split(GetKeys(item));
                if (!have.Overlaps(wanted)) continue;
                have.ExceptWith(wanted);
                SetKeys(item, string.Join("#", have));
                string name = item.GetAttribute("CommandName");
                changed.Add(string.IsNullOrEmpty(name) ? "(unnamed)" : name);
            }
            return changed;
        }

        private static System.Collections.Generic.HashSet<string> Split(string keys) =>
            new System.Collections.Generic.HashSet<string>(
                (keys ?? "").Split('#').Select(k => k.Trim().ToUpperInvariant()).Where(k => k.Length > 0));

        /// <summary>Write the file back, keeping one .bak copy.</summary>
        public bool Save()
        {
            try
            {
                try
                {
                    File.Copy(path, path + ".bak", true);
                }
                catch (Exception)
                {
                    // a failed backup should not stop the write
                }
                doc.Save(path);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }
    }
}
