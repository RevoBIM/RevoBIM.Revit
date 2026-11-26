using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Windows.Automation;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.FamilyThumbnail
{
    /// <summary>
    /// Debug dump for Family Thumbnail: what the tool can see, written to %AppData%\RevoBIM\family_thumbnail_debug.txt so a
    /// problem can be diagnosed from the file. Written when Update Batch opens (quick facts) and when its Save debug log button
    /// is pressed (adds a dump of Revit's Project Browser pane as Windows UI Automation sees it, with each item's selected
    /// state). Port of ft_debug.py.
    /// </summary>
    public static class FtDebug
    {
        private const int MaxNodes = 900;
        private const int MaxDepth = 9;

        private static string Short(string value, int size)
        {
            string text = (value ?? "").Replace("\r", " ").Replace("\n", " ");
            return text.Length <= size ? text : text.Substring(0, size) + "...";
        }

        private static void QuickFacts(UIApplication uiapp, UIDocument uidoc, List<FtEntry> entries, FtSettings s)
        {
            FtCore.Log("--- quick facts");
            bool isDefault;
            string note;
            string sharedPath = FtCore.ResolveSharedFile(s, out isDefault, out note);
            FtCore.Log("settings: fill_params=" + s.FillParams + " params=[" + s.ParamCreator + ", " + s.ParamRevision + ", " + s.ParamDate
                       + "] revision_step=" + s.RevisionStep + " shared_file=" + sharedPath + (isDefault ? " (built-in)" : "")
                       + " category_folders=" + s.CategoryFolders + " export_folder=" + FtCore.ExportFolder(s));
            FtCore.Log("settings: size=" + s.ImageSize + " " + s.ImageFormat + " fit=" + s.FitMode + " view='" + s.ViewName + "' export_images="
                       + s.ExportImages + " lock=" + s.LockOrientation + " gradient=" + s.Gradient + " overrides=" + s.Overrides.Count);
            if (note.Length > 0) FtCore.Log("shared file note: " + note);
            try
            {
                var ids = new List<Autodesk.Revit.DB.ElementId>(uidoc.Selection.GetElementIds());
                FtCore.Log("Selection.GetElementIds(): " + ids.Count + " item(s)");
                for (int i = 0; i < ids.Count && i < 20; i++)
                {
                    Autodesk.Revit.DB.Element element = uidoc.Document.GetElement(ids[i]);
                    FtCore.Log("  selected: " + (element == null ? "?" : element.GetType().Name + " '" + Short(element.Name, 70) + "'"));
                }
            }
            catch (Exception err)
            {
                FtCore.Swallowed("debug.selection", err);
            }
            int pre = 0;
            foreach (FtEntry e in entries) if (e.Preselected) pre++;
            FtCore.Log("families listed: " + entries.Count + "; pre-ticked: " + pre);
        }

        private static string Describe(AutomationElement element)
        {
            AutomationElement.AutomationElementInformation current = element.Current;
            string kind = (current.ControlType.ProgrammaticName ?? "").Replace("ControlType.", "");
            string state = "";
            try
            {
                object pattern;
                if (element.TryGetCurrentPattern(SelectionItemPattern.Pattern, out pattern))
                    state = ((SelectionItemPattern)pattern).Current.IsSelected ? " [selectable, SELECTED]" : " [selectable]";
            }
            catch (Exception err)
            {
                FtCore.Swallowed("debug.pattern", err);
            }
            return kind + " class='" + Short(current.ClassName, 50) + "' name='" + Short(current.Name, 70) + "' id='"
                   + Short(current.AutomationId, 30) + "' hwnd=" + current.NativeWindowHandle + state;
        }

        private static void DumpTree(TreeWalker walker, AutomationElement element, int depth, int[] count)
        {
            if (depth > MaxDepth || count[0] >= MaxNodes) return;
            count[0]++;
            try
            {
                FtCore.Log("    " + new string(' ', depth * 2) + Describe(element));
            }
            catch (Exception err)
            {
                FtCore.Swallowed("debug.describe", err);
            }
            try
            {
                AutomationElement child = walker.GetFirstChild(element);
                while (child != null && count[0] < MaxNodes)
                {
                    DumpTree(walker, child, depth + 1, count);
                    child = walker.GetNextSibling(child);
                }
            }
            catch (Exception err)
            {
                FtCore.Swallowed("debug.walk", err);
            }
        }

        /// <summary>The Project Browser pane (and what is around it) as Windows UI Automation sees it.</summary>
        private static void UiDump(UIApplication uiapp)
        {
            try
            {
                TreeWalker walker = TreeWalker.RawViewWalker;
                var inRevit = new PropertyCondition(AutomationElement.ProcessIdProperty, Process.GetCurrentProcess().Id);
                AutomationElementCollection everything = AutomationElement.RootElement.FindAll(TreeScope.Descendants, inRevit);
                int count = everything.Count;
                FtCore.Log("UI Automation: " + count + " elements in Revit's process");
                var classes = new Dictionary<string, int>();
                var browsers = new List<AutomationElement>();
                for (int index = 0; index < Math.Min(count, 8000); index++)
                {
                    try
                    {
                        AutomationElement element = everything[index];
                        string name = element.Current.Name ?? "";
                        string className = element.Current.ClassName ?? "";
                        int n;
                        classes[className] = classes.TryGetValue(className, out n) ? n + 1 : 1;
                        if (name.ToLowerInvariant().Contains("project browser") && browsers.Count < 3) browsers.Add(element);
                    }
                    catch (Exception err)
                    {
                        FtCore.Swallowed("debug.scan", err);
                    }
                }
                var top = new List<KeyValuePair<string, int>>(classes);
                top.Sort((a, b) => b.Value.CompareTo(a.Value));
                var parts = new List<string>();
                for (int i = 0; i < top.Count && i < 30; i++) parts.Add(top[i].Key + "=" + top[i].Value);
                FtCore.Log("most common classes: " + string.Join(", ", parts.ToArray()));
                if (browsers.Count > 0)
                {
                    foreach (AutomationElement element in browsers)
                    {
                        FtCore.Log("-- subtree of '" + Short(element.Current.Name, 70) + "':");
                        DumpTree(walker, element, 0, new[] { 0 });
                    }
                }
                else
                {
                    FtCore.Log("no element named 'Project Browser'; main window outline:");
                    DumpTree(walker, AutomationElement.FromHandle(uiapp.MainWindowHandle), 0, new[] { 0 });
                }
            }
            catch (Exception err)
            {
                FtCore.Swallowed("debug.ui_dump", err);
            }
        }

        /// <summary>Writes the debug file. ui adds the Windows UI Automation dump. Returns the file path, or null.</summary>
        public static string Write(UIApplication uiapp, UIDocument uidoc, List<FtEntry> entries, FtSettings s, bool ui)
        {
            QuickFacts(uiapp, uidoc, entries, s);
            if (ui) UiDump(uiapp);
            return FtCore.FlushLog();
        }
    }
}
