using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace RevoBIM.Tools.ViewManager
{
    /// <summary>The saved title and detail number rulesets, one file for every project (%APPDATA%\RevoBIM\view_manager_title_rulesets.txt).</summary>
    public static class VmRulesets
    {
        /// <summary>The saved rulesets, title and detail together. A target with none gets its worked example, so there is always one to start from.</summary>
        public static List<VmCore.Ruleset> Load()
        {
            string path = VmCore.RulesetsPath();
            var found = new List<VmCore.Ruleset>();
            try
            {
                if (File.Exists(path)) found = VmCore.ParseRulesets(File.ReadAllText(path, Encoding.UTF8));
            }
            catch (Exception)
            {
                found = new List<VmCore.Ruleset>();
            }
            bool added = false;
            if (!found.Any(r => r.Target == "title"))
            {
                found.Add(VmCore.StarterRuleset());
                added = true;
            }
            if (!found.Any(r => r.Target == "detail"))
            {
                found.Add(VmCore.StarterDetailRuleset());
                added = true;
            }
            if (added)
            {
                string why;
                Save(found, out why);
            }
            return found;
        }

        public static bool Save(IEnumerable<VmCore.Ruleset> rulesets, out string why)
        {
            why = "";
            try
            {
                File.WriteAllText(VmCore.RulesetsPath(), VmCore.FormatRulesets(rulesets), new UTF8Encoding(false));
                return true;
            }
            catch (Exception ex)
            {
                why = VmCore.Describe(ex);
                return false;
            }
        }
    }
}
