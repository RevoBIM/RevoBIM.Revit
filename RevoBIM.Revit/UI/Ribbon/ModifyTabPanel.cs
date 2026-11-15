using System;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;
using AW = Autodesk.Windows;

namespace RevoBIM.UI.Ribbon
{
    /// <summary>
    /// The "RevoBIM" panel (Pro Sheets Exporter, Revision Manager) on Revit's Modify
    /// tab, visible only while the selection holds a sheet or a view - picked in the
    /// Project Browser or on a sheet (a viewport counts as its view).
    ///
    /// Revit's API can only add panels to an add-in's own tab, so the panel is built
    /// on the RevoBIM tab with the normal API (App.cs) and then moved across with
    /// AdWindows, the ribbon library Revit itself is built on. The buttons keep their
    /// command bindings through the move. Nothing here may throw into Revit's startup;
    /// problems go to %APPDATA%\RevoBIM\logs\modify_tab_panel.txt and the buttons stay
    /// on the RevoBIM tab instead.
    /// </summary>
    public static class ModifyTabPanel
    {
        public const string PanelName = "RevoBIM";
        private const string ModifyTabId = "Modify";

        private static AW.RibbonPanel panel;
        private static string ownTab;

        /// <summary>Move the panel now if the ribbon is ready, else once Revit has started. Never throws.</summary>
        public static void Install(UIControlledApplication app, string tabName)
        {
            ownTab = tabName;
            try
            {
                if (!Move())
                {
                    app.ControlledApplication.ApplicationInitialized += (sender, args) =>
                    {
                        if (panel == null)
                            Move();
                    };
                }
                app.SelectionChanged += OnSelectionChanged;
            }
            catch (Exception err)
            {
                Log("install failed: " + err);
            }
        }

        private static bool Move()
        {
            try
            {
                AW.RibbonControl ribbon = AW.ComponentManager.Ribbon;
                if (ribbon == null)
                    return false;
                AW.RibbonTab own = ribbon.Tabs.FirstOrDefault(tab => tab.Id == ownTab);
                AW.RibbonTab modify = ribbon.Tabs.FirstOrDefault(tab => tab.Id == ModifyTabId);
                if (own == null || modify == null)
                    return false;
                AW.RibbonPanel found = own.Panels.FirstOrDefault(p => p.Source != null && p.Source.Title == PanelName);
                if (found == null)
                    return false;
                own.Panels.Remove(found);
                modify.Panels.Add(found);
                found.IsVisible = false;
                panel = found;
                return true;
            }
            catch (Exception err)
            {
                Log("could not move the panel to the Modify tab: " + err);
                return false;
            }
        }

        private static void OnSelectionChanged(object sender, SelectionChangedEventArgs args)
        {
            if (panel == null)
                return;
            bool show = false;
            try
            {
                Document doc = args.GetDocument();
                if (doc != null && !doc.IsFamilyDocument)
                {
                    foreach (ElementId id in args.GetSelectedElements())
                    {
                        Element element = doc.GetElement(id);
                        if (element is Viewport || (element is View view && !view.IsTemplate))
                        {
                            show = true;
                            break;
                        }
                    }
                }
            }
            catch (Exception)
            {
                show = false;
            }
            try
            {
                if (panel.IsVisible != show)
                    panel.IsVisible = show;
            }
            catch (Exception)
            {
            }
        }

        private static void Log(string text)
        {
            try
            {
                string folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                                             "RevoBIM", "logs");
                Directory.CreateDirectory(folder);
                File.AppendAllText(Path.Combine(folder, "modify_tab_panel.txt"),
                                   DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + text + "\n",
                                   new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }
    }
}
