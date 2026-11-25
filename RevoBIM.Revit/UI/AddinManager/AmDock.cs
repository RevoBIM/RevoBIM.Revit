using System;
using System.IO;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using Autodesk.Revit.UI;
using RevoBIM.Tools.AddinManager;

using Border = System.Windows.Controls.Border;
using Button = System.Windows.Controls.Button;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.AddinManager
{
    /// <summary>
    /// Registering the dockable pane, and saying why not. Revit only sets a dockable pane up while it is building its user
    /// interface, so registration happens from App.OnStartup and nowhere else: a registration from a command is accepted,
    /// raises nothing, and the pane is never created. Port of rba_dock.py.
    /// </summary>
    internal static class AmDock
    {
        private static bool registered;
        private static string registrationError = "";
        private static AmProvider provider;

        public static DockablePaneId PaneId() { return new DockablePaneId(AmCore.PaneGuid); }

        /// <summary>Called from App.OnStartup.</summary>
        public static void Register(UIControlledApplication app)
        {
            try
            {
                // the UIApplication a pane needs to post commands, parked as soon as Revit is up
                app.ControlledApplication.ApplicationInitialized += (sender, args) =>
                {
                    try { AmRibbon.UiApp = new UIApplication((Autodesk.Revit.ApplicationServices.Application)sender); }
                    catch (Exception err) { AmCore.LogException("dock/uiapp", err); }
                };
            }
            catch (Exception err)
            {
                AmCore.LogException("dock/initialised", err);
            }
            try
            {
                var settings = AmCore.LoadSettings();
                AmCore.SetDebug(AmCore.AsBool(settings, "debug"));
                provider = new AmProvider(AmCore.Get(settings, "dock"));
                app.RegisterDockablePane(PaneId(), AmCore.ToolName, provider);
                registered = true;
                AmCore.Log("pane registered, docking " + AmCore.Get(settings, "dock"));
            }
            catch (Exception err)
            {
                registered = false;
                registrationError = err.Message;
                AmCore.LogException("dock/register", err);
            }
        }

        /// <summary>Why the pane is not docked, for the floating window's footer.</summary>
        public static string Status()
        {
            if (registered) return "Floating - Revit would not show the pane";
            return string.IsNullOrEmpty(registrationError) ? "Floating - the pane was not registered at start up" : "Floating - " + registrationError;
        }

        /// <summary>The ribbon button: shows or hides the docked pane, or opens the floating window.</summary>
        public static bool Toggle(UIApplication uiapp, out string message)
        {
            message = "";
            AmRibbon.UiApp = uiapp;
            if (registered)
            {
                try
                {
                    DockablePane pane = uiapp.GetDockablePane(PaneId());
                    if (pane.IsShown()) pane.Hide(); else pane.Show();
                    return true;
                }
                catch (Exception err)
                {
                    AmCore.LogException("show/GetDockablePane", err);
                }
            }
            AmCore.Log("docking unavailable: " + Status());
            return AmWindow.Show(out message);
        }

        // ------------------------------------------------------------------ the provider

        /// <summary>
        /// Hands Revit a host Border and builds the panel inside it on first show. The host is painted with the palette at
        /// once so an empty pane is never the visible state, and a failure is shown readably in the pane and written to disk.
        /// </summary>
        private sealed class AmProvider : IDockablePaneProvider
        {
            private readonly string dock;
            private readonly Border host;
            private readonly System.Collections.Generic.Dictionary<string, string> colours;
            private bool built;

            public AmProvider(string dock)
            {
                this.dock = dock;
                colours = AmTheme.Palette(AmTheme.Resolve(AmCore.Get(AmCore.LoadSettings(), "theme")));
                host = new Border { Background = AmTheme.Brush(colours["BgWindow"]) };
                host.Child = Message("Addin Manager", "Starting...", null);
                host.Loaded += (s, a) => Build();
                host.IsVisibleChanged += (s, a) =>
                {
                    if (!(bool)a.NewValue) return;
                    Build();
                    try { host.Dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(Build)); } catch (Exception) { }
                };
            }

            public void SetupDockablePane(DockablePaneProviderData data)
            {
                data.FrameworkElement = host;
                var state = new DockablePaneState();
                string wanted = (dock ?? "").Trim().ToLowerInvariant();
                if (wanted == "right") state.DockPosition = DockPosition.Right;
                else if (wanted == "floating" || wanted == "float")
                {
                    state.DockPosition = DockPosition.Floating;
                    state.SetFloatingRectangle(new Autodesk.Revit.DB.Rectangle(120, 120, 520, 1000));
                }
                else state.DockPosition = DockPosition.Left;
                data.InitialState = state;
                try { data.VisibleByDefault = false; } catch (Exception) { }
            }

            private void Build()
            {
                if (built) return;
                built = true;
                try
                {
                    var pane = new AmPane("pane");
                    host.Child = pane.Control;
                    pane.FirstReadDone = true;
                    pane.Rescan();
                    try { if (File.Exists(AmCore.ErrorPath())) File.Delete(AmCore.ErrorPath()); } catch (Exception) { }
                    AmCore.Log("pane built on first show");
                }
                catch (Exception err)
                {
                    AmCore.Log("dock/build failed: " + err);
                    try
                    {
                        AmCore.EnsureRoot();
                        File.WriteAllText(AmCore.ErrorPath(), err.ToString(), new UTF8Encoding(false));
                    }
                    catch (Exception) { }
                    host.Child = Message("Addin Manager could not build its panel",
                        "Copy this and send it over. It is also saved to\n" + AmCore.ErrorPath(), err.ToString());
                }
            }

            private UIElement Message(string title, string body, string detail)
            {
                var stack = new StackPanel { Margin = new Thickness(14) };
                stack.Children.Add(new TextBlock
                {
                    Text = title,
                    Foreground = AmTheme.Brush(colours["AccBlue"]),
                    FontWeight = FontWeights.SemiBold,
                    FontSize = 14,
                    TextWrapping = TextWrapping.Wrap,
                });
                stack.Children.Add(new TextBlock
                {
                    Text = body,
                    Foreground = AmTheme.Brush(colours["FgText"]),
                    FontSize = 12,
                    Margin = new Thickness(0, 6, 0, 8),
                    TextWrapping = TextWrapping.Wrap,
                });
                if (detail != null)
                {
                    stack.Children.Add(new TextBox
                    {
                        Text = detail,
                        IsReadOnly = true,
                        TextWrapping = TextWrapping.Wrap,
                        FontFamily = new FontFamily("Consolas"),
                        FontSize = 11,
                        Foreground = AmTheme.Brush(colours["FgText"]),
                        Background = AmTheme.Brush(colours["BgField"]),
                        BorderBrush = AmTheme.Brush(colours["BrdEdge"]),
                        MaxHeight = 420,
                        VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                    });
                    var copy = new Button { Content = "Copy details", Margin = new Thickness(0, 8, 0, 0), HorizontalAlignment = HorizontalAlignment.Left, Padding = new Thickness(10, 3, 10, 3) };
                    copy.Click += (s, a) =>
                    {
                        try { Clipboard.SetDataObject(detail, true); copy.Content = "Copied"; } catch (Exception) { }
                    };
                    stack.Children.Add(copy);
                }
                return new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Content = stack };
            }
        }
    }
}
