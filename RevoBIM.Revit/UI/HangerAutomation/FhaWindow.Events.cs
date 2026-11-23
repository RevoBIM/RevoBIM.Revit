using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Threading;
using RevoBIM.Tools.HangerAutomation;
using ExternalEvent = Autodesk.Revit.UI.ExternalEvent;
using UIApplication = Autodesk.Revit.UI.UIApplication;

namespace RevoBIM.UI.HangerAutomation
{
    public sealed partial class FhaWindow
    {
        private void TabFabClick(object sender, RoutedEventArgs e)
        {
            ShowTab("fab");
        }

        private void TabFamClick(object sender, RoutedEventArgs e)
        {
            ShowTab("fam");
        }

        private void TabFloorClick(object sender, RoutedEventArgs e)
        {
            ShowTab("floor");
        }

        private void TabSvcClick(object sender, RoutedEventArgs e)
        {
            ShowTab("svc");
        }

        public void Status(string text)
        {
            try
            {
                C<TextBlock>("StatusTxt").Text = text;
            }
            catch (Exception)
            {
            }
        }

        private void HeaderDown(object sender, MouseButtonEventArgs e)
        {
            if (Drawer.Shrunk)
            {
                try
                {
                    if (e.ClickCount == 2)
                    {
                        Drawer.Expand();   // double-click the floating bar opens it again
                        return;
                    }
                }
                catch (Exception)
                {
                }
                if (Busy) return;   // no DragMove (a modal loop) while a job holds Revit's API context
            }
            Chrome.HeaderDown(e, C("Logo"));
        }

        private void FullClick(object sender, RoutedEventArgs e)
        {
            if (Drawer.Shrunk)
            {
                Drawer.Expand();
                return;
            }
            Chrome.ToggleFull();
        }

        private void CloseClick(object sender, RoutedEventArgs e)
        {
            Close();
        }

        /// <summary>Inspect lock (diagnostic): always runs with the debug file on, so Copy debug holds everything.</summary>
        private void InspectLockClick(object sender, RoutedEventArgs e)
        {
            try
            {
                StartJob((u, s, l) => HfamRevit.JobInspectLock(u, s, l), s => { s.Prompts = DimUi; s["debug"] = "1"; });
            }
            catch (Exception)
            {
            }
        }

        private void RehostClick(object sender, RoutedEventArgs e)
        {
            Start("rehost");
        }

        private void ExtendClick(object sender, RoutedEventArgs e)
        {
            Start("extend");
        }

        private void PlaceClick(object sender, RoutedEventArgs e)
        {
            Start("place");
        }

        /// <summary>The "Rod targets..." window: which categories rods can run up to besides floors, framing and roofs.</summary>
        private void RodCatsClick(object sender, RoutedEventArgs e)
        {
            RodCatsDialog.Run(this);
        }

        private void Key(object sender, KeyEventArgs e)
        {
            try
            {
                if (Drawer.Key(e))   // Ctrl+Shift+H; Esc / Enter / F11 open a parked window
                {
                    e.Handled = true;
                    return;
                }
                string k = e.Key.ToString();
                if (k == "F11")
                {
                    Chrome.ToggleFull();
                }
                else if (k == "F5" && Tab == "svc" && !Busy)
                {
                    Svc.Scan();   // read the hangers again
                    e.Handled = true;
                }
                // Escape never closes the tool: it is pressed to leave Revit picks
            }
            catch (Exception)
            {
            }
        }

        public void Close()
        {
            Save();
            try
            {
                Win.Close();
            }
            catch (Exception)
            {
            }
        }

        private void Closed(object sender, EventArgs e)
        {
            Save();   // however the window closed (the Close buttons, Alt+F4, Revit shutting down): keep the settings and the open tab
            current = null;
            StopTimer();
            // the Finish Selection card: no stale armed state, and nobody listening for this window
            finishReq = null;
            finishGrew = 0.0;
            if (ReferenceEquals(FhaFinish.Listener, finishListener)) FhaFinish.Listener = null;
        }

        private void CopyDebug(object sender, RoutedEventArgs e)
        {
            try
            {
                var keys = Gather().ToList();
                keys.Sort((a, b) => string.CompareOrdinal(a.Key, b.Key));
                string text = "Hanger Automation " + FhaCore.Version + "\nwindow open: " + OpenTiming + "\n\n" +
                              (LastDebug.Length > 0 ? LastDebug : "(nothing run yet)") + "\n\nSettings:\n" +
                              string.Join("\n", keys.Select(kv => kv.Key + "=" + kv.Value)) + "\n\nFamily tabs:\n" +
                              string.Join("\n\n", FamTabs().Select(t => t.DebugText()));
                Clipboard.SetText(text);
                C<TextBlock>("StatusTxt").Text = "Debug copied to the clipboard";
            }
            catch (Exception)
            {
            }
        }
    }
}
