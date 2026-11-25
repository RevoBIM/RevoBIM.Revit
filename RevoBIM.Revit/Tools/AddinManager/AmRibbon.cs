using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Windows.Media;
using Autodesk.Revit.UI;
using AW = Autodesk.Windows;

namespace RevoBIM.Tools.AddinManager
{
    /// <summary>One button an addin has put on Revit's ribbon.</summary>
    internal sealed class AmItem
    {
        public string Title = "";
        public string Tooltip = "";
        public string Description = "";
        public string Tab = "";
        public string Panel = "";
        public string Parent = "";        // pulldown / split button title, blank at panel level
        public string CommandId = "";
        public bool Hidden;               // its tab is switched off in Settings: kept for favourites and search, out of the browse list
        public bool BuiltInTab;           // sits on one of Revit's own tabs
        public ImageSource Icon;
        public AW.RibbonItem Ribbon;      // the live ribbon item behind it

        /// <summary>What the primary search looks at: what the addin is called.</summary>
        public string NameText { get { return Title + " " + Parent; } }

        /// <summary>What the secondary search looks at: what it says it does.</summary>
        public string DetailText { get { return Tooltip + " " + Description + " " + Panel + " " + Tab; } }
        /// <summary>Tab, panel, parent and title, joined with "::" (never "|": lists are saved joined with it).</summary>
        public string Key
        {
            get
            {
                return string.Join(AmCore.KeySep, new[] { Clean(Tab), Clean(Panel), Clean(Parent), Clean(Title) });
            }
        }

        private static string Clean(string s) { return AmCore.Normalise(s).Replace("|", "/"); }
    }

    /// <summary>A collapsible heading and its items.</summary>
    internal sealed class AmGroup
    {
        public string Key;
        public string Title;
        public string Subtitle;
        public List<AmItem> Items = new List<AmItem>();
        public AmGroup(string key, string title, string subtitle) { Key = key; Title = title; Subtitle = subtitle; }
    }

    /// <summary>
    /// Reads the live ribbon (the Autodesk.Windows RibbonControl Revit draws) for every button an addin added,
    /// and runs one. Replaces the pyRevit original's folder scan: any addin's buttons are listed, grouped by tab.
    /// Port of rba_scan.py and rba_launch.py.
    /// </summary>
    internal static class AmRibbon
    {
        /// <summary>Ids of buttons added through the API start with this; Revit's own commands do not.</summary>
        private const string AddinIdPrefix = "CustomCtrl_%";

        /// <summary>The UIApplication, captured at start up so a pane that outlives the command can post commands.</summary>
        public static UIApplication UiApp;

        private static string lastScanLog = "";

        // ------------------------------------------------------------------ reading

        public static List<AmItem> Scan(bool includeBuiltInTabs, string tabFilter)
        {
            var items = new List<AmItem>();
            var seen = new HashSet<string>();
            AW.RibbonControl ribbon = null;
            try { ribbon = AW.ComponentManager.Ribbon; }
            catch (Exception err) { AmCore.LogException("scan/ribbon", err); }
            if (ribbon == null) return items;

            string filter = AmCore.Normalise(tabFilter);
            foreach (AW.RibbonTab tab in ribbon.Tabs.ToList())
            {
                try
                {
                    if (tab.IsContextualTab) continue;
                    string tabTitle = AmCore.Flatten(string.IsNullOrEmpty(tab.Title) ? tab.Id : tab.Title);
                    if (tabTitle.Length == 0) continue;
                    bool addinTab = (tab.Id ?? "").StartsWith(AddinIdPrefix, StringComparison.Ordinal);
                    if (!addinTab && !includeBuiltInTabs) continue;
                    if (filter.Length > 0 && AmCore.Normalise(tabTitle).IndexOf(filter, StringComparison.Ordinal) < 0) continue;
                    foreach (AW.RibbonPanel panel in tab.Panels.ToList())
                    {
                        if (panel.Source == null) continue;
                        string panelTitle = AmCore.Flatten(panel.Source.Title);
                        Walk(panel.Source.Items, items, seen, tabTitle, panelTitle, "", !addinTab, 0);
                    }
                }
                catch (Exception err)
                {
                    AmCore.LogException("scan/tab " + tab.Id, err);
                }
            }
            string summary = "scan: " + items.Count + " addin buttons on " + items.Select(i => i.Tab).Distinct().Count() + " tabs";
            if (summary != lastScanLog) { lastScanLog = summary; AmCore.Log(summary); }   // only when it changes: the panel rescans on a timer
            return items;
        }

        private static void Walk(IEnumerable source, List<AmItem> output, HashSet<string> seen, string tab, string panel,
                                 string parent, bool builtIn, int depth)
        {
            if (source == null || depth > 6) return;
            foreach (object entry in source)
            {
                AW.RibbonItem item = entry as AW.RibbonItem;
                if (item == null) continue;
                IEnumerable children = ChildrenOf(item);
                bool hasChildren = children != null && children.Cast<object>().Any();
                if (hasChildren)
                {
                    string title = TextOf(item);
                    string nextParent = depth == 0 || title.Length == 0 ? title : (parent.Length > 0 ? parent : title);
                    // rows and fold panels hold buttons directly; a pulldown names its children
                    bool container = item is AW.RibbonRowPanel || item is AW.RibbonFoldPanel;
                    Walk(children, output, seen, tab, panel, container ? parent : nextParent, builtIn, depth + 1);
                    continue;
                }
                string id = item.Id ?? "";
                if (!id.StartsWith(AddinIdPrefix, StringComparison.Ordinal)) continue;
                string text = TextOf(item);
                if (text.Length == 0) continue;

                var found = new AmItem
                {
                    Title = text,
                    Tab = tab,
                    Panel = panel,
                    Parent = parent,
                    CommandId = id,
                    BuiltInTab = builtIn,
                    Ribbon = item,
                    Icon = ImageOf(item),
                };
                string[] tip = TooltipOf(item);
                found.Tooltip = AmCore.Flatten(tip[0]);
                found.Description = AmCore.Flatten(tip[1]);
                if (!seen.Add(found.Key + "@" + id)) continue;
                output.Add(found);
            }
        }

        private static IEnumerable ChildrenOf(AW.RibbonItem item)
        {
            try
            {
                var row = item as AW.RibbonRowPanel;
                if (row != null) return row.Items;
                var fold = item as AW.RibbonFoldPanel;
                if (fold != null) return fold.Items;
                var split = item as AW.RibbonSplitButton;
                if (split != null) return split.Items;
                PropertyInfo p = item.GetType().GetProperty("Items", BindingFlags.Public | BindingFlags.Instance);
                if (p != null && typeof(IEnumerable).IsAssignableFrom(p.PropertyType) && p.PropertyType != typeof(string))
                    return p.GetValue(item, null) as IEnumerable;
            }
            catch (Exception)
            {
            }
            return null;
        }

        private static string TextOf(AW.RibbonItem item)
        {
            foreach (string name in new[] { "Text", "AutomationName", "Name" })
            {
                string v = Prop(item, name) as string;
                if (!string.IsNullOrWhiteSpace(v)) return AmCore.Flatten(v);
            }
            return "";
        }

        private static ImageSource ImageOf(AW.RibbonItem item)
        {
            foreach (string name in new[] { "Image", "LargeImage" })
            {
                ImageSource source = Prop(item, name) as ImageSource;
                if (source != null) return source;
            }
            return null;
        }

        /// <summary>(first line, rest) of the tooltip, which may be a plain string or a RibbonToolTip.</summary>
        private static string[] TooltipOf(AW.RibbonItem item)
        {
            object tip = Prop(item, "ToolTip");
            if (tip == null) return new[] { "", "" };
            string s = tip as string;
            if (s != null) return new[] { s, "" };
            string title = Prop(tip, "Title") as string ?? "";
            string content = Prop(tip, "Content") as string ?? "";
            string expanded = Prop(tip, "ExpandedContent") as string ?? "";
            return new[] { string.IsNullOrWhiteSpace(content) ? title : content, string.IsNullOrWhiteSpace(expanded) ? title : expanded };
        }

        private static object Prop(object target, string name)
        {
            try
            {
                PropertyInfo p = target.GetType().GetProperty(name, BindingFlags.Public | BindingFlags.Instance);
                return p == null ? null : p.GetValue(target, null);
            }
            catch (Exception)
            {
                return null;
            }
        }

        // ------------------------------------------------------------------ search and grouping

        /// <summary>(primary, secondary): a name match, and what only matches what the addin says it does.</summary>
        public static void SearchSplit(List<AmItem> items, string search, out List<AmItem> primary, out List<AmItem> secondary)
        {
            List<string> terms = AmCore.Terms(search);
            primary = new List<AmItem>();
            secondary = new List<AmItem>();
            if (terms.Count == 0)
            {
                primary.AddRange(items);
                return;
            }
            foreach (AmItem item in items)
            {
                if (AmCore.MatchesSearch(item.NameText, terms)) primary.Add(item);
                else if (AmCore.MatchesSearch(item.DetailText, terms)) secondary.Add(item);
            }
            secondary.Sort((a, b) => AmCore.NaturalCompare(a.Title, b.Title));
        }

        /// <summary>Groups by tab (default) or by panel. Tabs keep the ribbon's own order; items inside keep the ribbon order too.</summary>
        public static List<AmGroup> GroupItems(List<AmItem> items, string groupBy)
        {
            var groups = new List<AmGroup>();
            var index = new Dictionary<string, AmGroup>();
            foreach (AmItem item in items)
            {
                string key, title, subtitle;
                if (groupBy == "panel")
                {
                    key = AmCore.Normalise(item.Tab) + AmCore.KeySep + AmCore.Normalise(item.Panel);
                    title = item.Panel;
                    subtitle = item.Tab;
                }
                else
                {
                    key = AmCore.Normalise(item.Tab);
                    title = item.Tab;
                    subtitle = item.BuiltInTab ? "Addin buttons on Revit's own tab" : "";
                }
                AmGroup group;
                if (!index.TryGetValue(key, out group))
                {
                    group = new AmGroup(key, title, subtitle);
                    index[key] = group;
                    groups.Add(group);
                }
                group.Items.Add(item);
            }
            // addin tabs first, Revit's own tabs after; the ribbon's order inside each
            var ordered = groups.Where(g => g.Subtitle.Length == 0).Concat(groups.Where(g => g.Subtitle.Length > 0)).ToList();
            return ordered;
        }

        // ------------------------------------------------------------------ running

        /// <summary>Runs a button. PostCommand first (Revit runs it in its own API context, as a ribbon click does).</summary>
        public static bool Launch(AmItem item, out string message)
        {
            message = "";
            UIApplication uiapp = UiApp;
            if (uiapp != null && item.CommandId.Length > 0)
            {
                try
                {
                    RevitCommandId id = RevitCommandId.LookupCommandId(item.CommandId);
                    if (id != null)
                    {
                        uiapp.PostCommand(id);
                        AmCore.Log("launch: posted " + item.CommandId);
                        return true;
                    }
                }
                catch (Exception err)
                {
                    AmCore.LogException("launch/PostCommand", err);
                }
            }
            try
            {
                var command = item.Ribbon as AW.RibbonCommandItem;
                if (command != null && command.CommandHandler != null)
                {
                    object parameter = command.CommandParameter ?? command;
                    if (command.CommandHandler.CanExecute(parameter))
                    {
                        command.CommandHandler.Execute(parameter);
                        AmCore.Log("launch: executed handler for " + item.Title);
                        return true;
                    }
                }
            }
            catch (Exception err)
            {
                AmCore.LogException("launch/CommandHandler", err);
            }
            message = "Revit would not run " + item.Title;
            return false;
        }

        // ------------------------------------------------------------------ Quick Access Toolbar

        private static AW.ToolBars.QuickAccessToolBarSource Qat()
        {
            return AW.ComponentManager.QuickAccessToolBar;
        }

        private static bool QatHolds(string commandId)
        {
            try
            {
                AW.ToolBars.QuickAccessToolBarSource bar = Qat();
                if (bar == null || commandId.Length == 0) return false;
                foreach (AW.RibbonItem entry in bar.Items.ToList())
                    if (entry.Id == commandId) return true;
            }
            catch (Exception err)
            {
                AmCore.LogException("qat/holds", err);
            }
            return false;
        }

        /// <summary>Puts a clone of the ribbon item on the Quick Access Toolbar (a WPF element has one parent, so not the item itself).</summary>
        public static bool QatAdd(AmItem item, out string message)
        {
            message = "";
            string id = item.CommandId;
            if (id.Length == 0 || item.Ribbon == null)
            {
                message = "that addin has no command id to put on the toolbar";
                return false;
            }
            if (QatHolds(id)) return true;
            try
            {
                AW.ToolBars.QuickAccessToolBarSource bar = Qat();
                if (bar == null)
                {
                    message = "Revit did not hand back its Quick Access Toolbar";
                    return false;
                }
                var source = item.Ribbon as AW.RibbonCommandItem;
                var clone = new AW.RibbonButton { Id = id, Text = item.Title, ShowText = false, ShowImage = true };
                if (source != null)
                {
                    clone.Image = source.Image;
                    clone.LargeImage = source.LargeImage;
                    clone.ToolTip = source.ToolTip;
                    clone.CommandHandler = source.CommandHandler;
                    clone.CommandParameter = source.CommandParameter;
                }
                bar.Items.Add(clone);
            }
            catch (Exception err)
            {
                AmCore.LogException("qat/add", err);
                message = "Revit would not take that button on the toolbar";
                return false;
            }
            if (!QatHolds(id))
            {
                message = "Revit accepted the button and then did not show it";
                return false;
            }
            AmCore.Log("qat: added " + item.Title);
            return true;
        }

        public static bool QatRemove(string commandId, out string message)
        {
            message = "";
            try
            {
                AW.ToolBars.QuickAccessToolBarSource bar = Qat();
                if (bar == null)
                {
                    message = "Revit did not hand back its Quick Access Toolbar";
                    return false;
                }
                foreach (AW.RibbonItem entry in bar.Items.ToList())
                    if (entry.Id == commandId) bar.Items.Remove(entry);
            }
            catch (Exception err)
            {
                AmCore.LogException("qat/remove", err);
                message = "Revit would not take that button off the toolbar";
                return false;
            }
            if (QatHolds(commandId))
            {
                message = "Revit removed nothing";
                return false;
            }
            return true;
        }

        /// <summary>Revit rebuilds its toolbar from UIState.dat at start up, so the saved list is put back whenever the panel reads the ribbon.</summary>
        public static int QatReapply(List<AmItem> items, List<string> wantedKeys)
        {
            if (wantedKeys.Count == 0) return 0;
            int done = 0;
            var wanted = new HashSet<string>(wantedKeys);
            foreach (AmItem item in items)
            {
                if (!wanted.Contains(item.Key)) continue;
                string ignored;
                if (QatHolds(item.CommandId) || QatAdd(item, out ignored)) done++;
            }
            if (done > 0) AmCore.Log("qat: " + done + " of " + wantedKeys.Count + " pinned buttons in place");
            return done;
        }
    }
}
