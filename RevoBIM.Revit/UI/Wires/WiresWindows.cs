using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using Autodesk.Revit.UI;
using RevoBIM.Tools.Wires;

using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using Clipboard = System.Windows.Clipboard;
using Control = System.Windows.Controls.Control;
using Slider = System.Windows.Controls.Slider;

namespace RevoBIM.UI.Wires
{
    /// <summary>A themed yes/no: small enough to be a TaskDialog, but a TaskDialog is the one window in this extension that would come up in Revit's own colours.</summary>
    internal static class WiresConfirmWindow
    {
        /// <summary>True where the person said yes. Escape and the X both mean no.</summary>
        public static bool Ask(string message, string detail, string title, string yes, UIApplication uiapp)
        {
            Window window;
            try
            {
                window = WiresUi.LoadWindow("WiresConfirm.xaml");
            }
            catch (Exception)
            {
                return PlainFallback(message, detail);
            }
            WiresUi.DressHeader(window);
            WiresUi.OwnedByRevit(window, uiapp);
            WiresUi.SetText(window, "ToolName", title);
            WiresUi.SetText(window, "MessageText", message);
            WiresUi.SetText(window, "DetailText", detail);
            bool said = false;
            foreach (var pair in new[] { Tuple.Create("YesButton", true), Tuple.Create("NoButton", false) })
            {
                var button = window.FindName(pair.Item1) as Button;
                bool answer = pair.Item2;
                if (button != null)
                {
                    button.Click += (s, a) =>
                    {
                        said = answer;
                        try { window.Close(); } catch (Exception) { }
                    };
                }
            }
            var yesButton = window.FindName("YesButton") as Button;
            if (yesButton != null && !string.IsNullOrEmpty(yes)) yesButton.Content = yes;
            try
            {
                window.ShowDialog();
            }
            catch (Exception)
            {
                return PlainFallback(message, detail);
            }
            return said;
        }

        /// <summary>Revit's own dialog, where the themed one will not build.</summary>
        private static bool PlainFallback(string message, string detail)
        {
            try
            {
                var dialog = new TaskDialog("RevoBIM Wires") { MainInstruction = message, MainContent = detail, CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.Cancel };
                return dialog.Show() == TaskDialogResult.Yes;
            }
            catch (Exception)
            {
                return false;
            }
        }
    }

    /// <summary>Results are reported here, not in a dialog of Revit's, and by default only when something needs a look.</summary>
    internal static class WiresResultsWindow
    {
        public static bool ShouldShow(Report report, Dictionary<string, string> settings)
        {
            if (report == null) return false;
            string mode = WiresSettings.Lower(settings, "show_results", "needed");
            if (mode == "never") return false;
            if (mode == "always") return true;
            return report.NeedsALook();
        }

        /// <summary>Displays the report. Returns false where nothing was shown.</summary>
        public static bool Show(Report report, Dictionary<string, string> settings, UIApplication uiapp, bool force = false)
        {
            if (report == null) return false;
            if (!force && !ShouldShow(report, settings)) return false;
            Window window;
            try
            {
                window = WiresUi.LoadWindow("WiresResults.xaml");
            }
            catch (Exception)
            {
                // A themed window that will not build must never mean the tool looks like it did nothing.
                return PlainFallback(report);
            }
            WiresUi.DressHeader(window);
            WiresUi.OwnedByRevit(window, uiapp);
            WiresUi.SetText(window, "ToolName", report.Title);
            WiresUi.SetText(window, "SummaryText", report.Summary());
            try
            {
                var panel = window.FindName("LineList") as Panel;
                if (panel != null)
                {
                    if (report.Lines.Count == 0) panel.Children.Add(WiresUi.ReportRow(Report.Note, "Nothing needed doing to the wires selected."));
                    foreach (var line in report.Lines) panel.Children.Add(WiresUi.ReportRow(line.Key, line.Value));
                }
            }
            catch (Exception)
            {
            }
            WiresUi.SetText(window, "StatusText", "Settings: " + WiresSettings.SettingsPath());
            try
            {
                var debug = window.FindName("DebugButton") as Button;
                if (debug != null)
                {
                    if (!WiresSettings.Bool(settings, "debug_report")) debug.Visibility = Visibility.Collapsed;
                    else debug.Click += (s, a) => WriteDebug(window, uiapp, settings, report);
                }
            }
            catch (Exception)
            {
            }
            try
            {
                var ok = window.FindName("OkButton") as Button;
                if (ok != null) ok.Click += (s, a) => { try { window.Close(); } catch (Exception) { } };
            }
            catch (Exception)
            {
            }
            try
            {
                window.ShowDialog();
            }
            catch (Exception)
            {
                return PlainFallback(report);
            }
            return true;
        }

        /// <summary>Writes the debug report to disk and puts it on the clipboard.</summary>
        private static void WriteDebug(Window window, UIApplication uiapp, Dictionary<string, string> settings, Report report)
        {
            string text;
            try
            {
                text = WiresModel.DebugReport(uiapp, settings, report);
            }
            catch (Exception error)
            {
                WiresUi.SetText(window, "StatusText", "Could not build the debug report: " + error.Message);
                return;
            }
            string path = WiresModel.WriteDebugReport(text);
            bool copied = false;
            try
            {
                Clipboard.SetText(text);
                copied = true;
            }
            catch (Exception)
            {
            }
            string status;
            if (path != null && copied) status = "Debug report copied to the clipboard and written to " + path;
            else if (path != null) status = "Debug report written to " + path;
            else if (copied) status = "Debug report copied to the clipboard";
            else status = "Could not write or copy the debug report";
            WiresUi.SetText(window, "StatusText", status);
        }

        public static string AsText(Report report)
        {
            var lines = new List<string> { report.Summary(), "" };
            foreach (var line in report.Lines)
            {
                string marker = line.Key == Report.Note ? "- " : line.Key == Report.Skip ? "! " : "  ";
                lines.Add(marker + line.Value);
            }
            return string.Join("\n", lines);
        }

        /// <summary>Revit's own dialog, where the themed one could not be built.</summary>
        private static bool PlainFallback(Report report)
        {
            try
            {
                TaskDialog.Show("RevoBIM " + report.Title, AsText(report));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }
    }

    /// <summary>
    /// The Shuffle prompt: small, parked in the bottom right so the run it just drew is visible behind it, floating by default so the view can be panned and zoomed
    /// while a route is being judged. Two paths, chosen by the modeless_shuffle setting: modeless shows the window and returns (every redraw is handed to an
    /// ExternalEvent); modal blocks Revit behind the window, but a modal window shown from inside a command is still in the command's API context.
    /// </summary>
    internal static class WiresShuffleWindow
    {
        // Floating windows, kept referenced for as long as they are open, or nothing holds them.
        private static readonly List<Window> Live = new List<Window>();

        private sealed class State
        {
            public bool Kept, Busy, Done;
            public WiresEventBridge Bridge;
        }

        /// <summary>Modal: returns true where the route was kept. Modeless: returns null, the window lives on, and the session is finished by its own buttons.</summary>
        public static bool? Show(Session session, string headline, string title, UIApplication uiapp)
        {
            Window window;
            try
            {
                window = WiresUi.LoadWindow("WiresShuffle.xaml");
            }
            catch (Exception)
            {
                session.Keep();
                return true;
            }
            WiresUi.DressHeader(window, true);
            WiresUi.OwnedByRevit(window, uiapp);
            WiresUi.ParkBottomRight(window);
            var state = new State();

            Func<string, FrameworkElement> find = name =>
            {
                try { return window.FindName(name) as FrameworkElement; } catch (Exception) { return null; }
            };

            Action setControls = () =>
            {
                try
                {
                    var label = find("ClashText") as TextBlock;
                    if (label != null)
                    {
                        if (!session.Avoiding()) label.Text = "Off - the shortest route wins, whatever it crosses.";
                        else if (session.Clashing > 0) label.Text = session.Clashing + " span(s) still cross a fitting on another circuit. Shuffle may find a route that does not.";
                        else label.Text = "This route crosses nothing.";
                    }
                }
                catch (Exception) { }
                try
                {
                    var label = find("VertexCount") as TextBlock;
                    if (label != null) label.Text = session.Vertices().ToString();
                    var down = find("VertexDown");
                    if (down != null) down.IsEnabled = session.Vertices() > WiresGeom.MinVertices;
                    var up = find("VertexUp");
                    if (up != null) up.IsEnabled = session.Vertices() < WiresGeom.MaxVertices;
                }
                catch (Exception) { }
                // the segmented arc / chamfer pair: the active one lit blue
                foreach (var pair in new[] { Tuple.Create("ArcButton", "arc"), Tuple.Create("ChamferButton", "chamfer") })
                {
                    try
                    {
                        var button = find(pair.Item1);
                        if (button == null) continue;
                        if (session.Wiring() == pair.Item2)
                        {
                            WiresUi.Paint(button, Control.BackgroundProperty, "Blue");
                            WiresUi.Paint(button, Control.ForegroundProperty, "OnBlue");
                        }
                        else
                        {
                            // back to the Segment style's own field and muted text
                            button.ClearValue(Control.BackgroundProperty);
                            button.ClearValue(Control.ForegroundProperty);
                        }
                    }
                    catch (Exception) { }
                }
                try
                {
                    var label = find("OffsetValue") as TextBlock;
                    if (label != null)
                    {
                        label.Text = session.SagMode() == "paper"
                            ? session.Sag().ToString("0.###") + "mm on paper"
                            : session.Sag().ToString("0.###") + "% of the span";
                    }
                }
                catch (Exception) { }
            };

            Action setText = () =>
            {
                WiresUi.SetText(window, "HeadlineText", headline);
                WiresUi.SetText(window, "RouteText", "Route " + ((session.Variant % Math.Max(1, session.Alternatives)) + 1) + " of " + Math.Max(1, session.Alternatives) + ".");
            };

            WiresUi.SetText(window, "ToolName", title);
            setText();
            try
            {
                var slider = find("OffsetSlider") as Slider;
                if (slider != null)
                {
                    // the slider drives whichever unit the arc depth is set in
                    if (session.SagMode() == "paper")
                    {
                        slider.Maximum = 20;
                        slider.TickFrequency = 0.5;
                    }
                    else
                    {
                        slider.Maximum = 45;
                        slider.TickFrequency = 1;
                    }
                    slider.Value = Math.Min(slider.Maximum, session.Sag());
                }
            }
            catch (Exception) { }
            setControls();

            // Every live control redraws the run, so they all have to be re-entrancy guarded: a repeat button auto-repeats faster than a transaction commits.
            // Modeless, the work is handed to the ExternalEvent and the controls are refreshed when it comes back; modal, it runs here and now.
            Action<Action> redraw = work =>
            {
                if (state.Busy || state.Done) return;
                WiresEventBridge bridge = state.Bridge;
                if (bridge != null)
                {
                    state.Busy = true;
                    Action after = () =>
                    {
                        state.Busy = false;
                        setControls();
                        setText();
                    };
                    if (!bridge.Run(app => work(), after)) state.Busy = false;
                    return;
                }
                state.Busy = true;
                try
                {
                    work();
                    setControls();
                    setText();
                }
                catch (Exception) { }
                finally
                {
                    state.Busy = false;
                }
            };

            Action<bool> closeWith = keep =>
            {
                state.Kept = keep;
                WiresEventBridge bridge = state.Bridge;
                if (bridge == null)
                {
                    try { window.Close(); } catch (Exception) { }
                    return;
                }
                if (state.Done) return;
                state.Done = true;
                Action after = () =>
                {
                    try { window.Close(); } catch (Exception) { }
                };
                if (!bridge.Run(app => session.Finish(keep), after)) state.Done = false;
            };

            Action<double> onOffset = value =>
            {
                if (Math.Abs(value - session.Sag()) < 1.0e-9) return;
                redraw(() => session.SetSag(value));
            };

            try
            {
                var back = find("PreviousButton");
                if (back != null) back.IsEnabled = session.HasPrevious();
            }
            catch (Exception) { }
            try
            {
                var box = find("AvoidClashBox") as CheckBox;
                if (box != null)
                {
                    box.IsChecked = session.Avoiding();
                    box.Click += (s, a) =>
                    {
                        bool wanted = box.IsChecked == true;
                        if (wanted == session.Avoiding()) return;
                        redraw(() => session.SetAvoid(wanted));
                    };
                }
            }
            catch (Exception) { }

            var handlers = new Dictionary<string, Action>
            {
                { "ShuffleButton", () => redraw(() => session.Shuffle()) },
                { "PreviousButton", () => redraw(() => session.Previous()) },
                { "VertexUp", () => redraw(() => session.SetVertices(session.Vertices() + 1)) },
                { "VertexDown", () => redraw(() => session.SetVertices(session.Vertices() - 1)) },
                { "ArcButton", () => { if (session.Wiring() != "arc") redraw(() => session.SetWiring("arc")); } },
                { "ChamferButton", () => { if (session.Wiring() != "chamfer") redraw(() => session.SetWiring("chamfer")); } },
                { "KeepButton", () => closeWith(true) },
                { "CancelButton", () => closeWith(false) },
            };
            foreach (var entry in handlers)
            {
                try
                {
                    var button = find(entry.Key) as ButtonBase;
                    Action handler = entry.Value;
                    if (button != null) button.Click += (s, a) => handler();
                }
                catch (Exception) { }
            }

            // the slider redraws on release rather than on every tick, or a single drag would open a transaction per pixel
            try
            {
                var slider = find("OffsetSlider") as Slider;
                if (slider != null)
                {
                    slider.AddHandler(UIElement.PreviewMouseLeftButtonUpEvent, new MouseButtonEventHandler((s, a) => onOffset(slider.Value)), true);
                    slider.KeyUp += (s, a) => onOffset(slider.Value);
                }
            }
            catch (Exception) { }

            if (!session.Modeless)
            {
                try
                {
                    window.ShowDialog();
                }
                catch (Exception)
                {
                    state.Kept = true;
                }
                if (!state.Kept) session.Cancel();
                return state.Kept;
            }

            // modeless: hand the work to Revit and let the window live
            WiresEventBridge made;
            try
            {
                made = new WiresEventBridge();
            }
            catch (Exception)
            {
                // no bridge, no safe way to touch the document - fall back to modal
                try { window.ShowDialog(); } catch (Exception) { state.Kept = true; }
                if (!state.Kept) session.Cancel();
                return state.Kept;
            }
            state.Bridge = made;
            Live.Add(window);
            window.Closed += (s, a) =>
            {
                // closing with the X is a cancel, like any other dialog
                if (!state.Done)
                {
                    state.Done = true;
                    made.Run(app => session.Finish(false));
                }
                Live.Remove(window);
            };
            try
            {
                window.Show();
            }
            catch (Exception)
            {
                Live.Remove(window);
                session.Cancel();
            }
            return null;
        }
    }
}
