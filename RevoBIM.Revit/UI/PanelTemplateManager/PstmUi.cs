using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.PanelTemplateManager;

using Border = System.Windows.Controls.Border;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using Color = System.Windows.Media.Color;
using ListBox = System.Windows.Controls.ListBox;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.PanelTemplateManager
{
    /// <summary>
    /// The two palettes (theme.py). Dark is Revit's own dark theme, the same slate blue every other RevoBIM tool uses (sampled from Revit's
    /// dark Project Browser); the near-black neutral dark this tool used to have was retired in 1.10.0. Light is unchanged.
    /// </summary>
    internal static class PstmTheme
    {
        private static readonly Dictionary<string, string> Dark = new Dictionary<string, string>
        {
            // surfaces
            { "WindowBg", "#3C4454" }, { "CardBg", "#343C4A" }, { "FieldBg", "#2D3441" }, { "BarBg", "#222933" },
            { "PopupBg", "#343C4A" }, { "ChipBg", "#46505F" },
            // edges
            { "EdgeBrush", "#515C6B" }, { "WindowEdge", "#5A6372" }, { "GridLine", "#4A5463" },
            // text
            { "TextBrush", "#EEF0F4" }, { "MutedBrush", "#A4AAB1" }, { "DisabledBrush", "#7B8290" },
            // accents
            { "BlueBrush", "#5AAEEB" }, { "OrangeBrush", "#E8912D" }, { "OrangeHoverBrush", "#F5A648" },
            { "GreenBrush", "#3FA75A" }, { "GreenHoverBrush", "#4EC06D" }, { "RedBrush", "#D9534F" }, { "RedHoverBrush", "#E7706C" },
            // interaction
            { "SelectionBrush", "#3A7392" }, { "HoverBrush", "#444E5E" }, { "RowAltBrush", "#384050" },
            { "ScrollThumb", "#5A6372" }, { "ScrollThumbHover", "#6E7889" },
            // row / cell states
            { "ChangedBg", "#5C4524" }, { "ChangedEdge", "#E8912D" },   // a change waiting for Apply
            { "ReviewBg", "#6A3234" }, { "ReviewEdge", "#D9534F" },     // Auto Assign could not find a template
            { "MatchedBg", "#2F5E3B" }, { "MatchedEdge", "#3FA75A" },   // Auto Assign found a clean match
            { "UnusedBg", "#323C48" },                                  // template not used anywhere in the project
        };

        private static readonly Dictionary<string, string> Light = new Dictionary<string, string>
        {
            { "WindowBg", "#F1F1F4" }, { "CardBg", "#FFFFFF" }, { "FieldBg", "#FFFFFF" }, { "BarBg", "#E3E3E8" },
            { "PopupBg", "#FFFFFF" }, { "ChipBg", "#D8D8DE" },
            { "EdgeBrush", "#C6C6CC" }, { "WindowEdge", "#B0B0B8" }, { "GridLine", "#DCDCE2" },
            { "TextBrush", "#1F1F22" }, { "MutedBrush", "#5F5F68" }, { "DisabledBrush", "#9A9AA2" },
            // the dark accents are picked to sit on a dark surface and wash out on white, so the light palette darkens them
            { "BlueBrush", "#1B72BE" }, { "OrangeBrush", "#B96A12" }, { "OrangeHoverBrush", "#D07C1D" },
            { "GreenBrush", "#2E8546" }, { "GreenHoverBrush", "#379B53" }, { "RedBrush", "#B33A36" }, { "RedHoverBrush", "#C7514D" },
            { "SelectionBrush", "#BCD9F2" }, { "HoverBrush", "#E8E8EE" }, { "RowAltBrush", "#F7F7FA" },
            { "ScrollThumb", "#BFBFC6" }, { "ScrollThumbHover", "#A2A2AA" },
            { "ChangedBg", "#FCEBD2" }, { "ChangedEdge", "#B96A12" },
            { "ReviewBg", "#F8D9D8" }, { "ReviewEdge", "#B33A36" },
            { "MatchedBg", "#D9EEDF" }, { "MatchedEdge", "#2E8546" },
            { "UnusedBg", "#EAEAEF" },
        };

        public static IDictionary<string, string> Palette(string name)
        {
            return string.Equals(name, "light", StringComparison.OrdinalIgnoreCase) ? Light : Dark;
        }

        public static string Other(string name)
        {
            return string.Equals(name, "light", StringComparison.OrdinalIgnoreCase) ? "dark" : "light";
        }

        public static SolidColorBrush Brush(string hex)
        {
            var b = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
            b.Freeze();
            return b;
        }

        public static string Hex(string name, string key)
        {
            string v;
            IDictionary<string, string> pal = Palette(name);
            if (pal.TryGetValue(key, out v)) return v;
            return Dark.TryGetValue(key, out v) ? v : "#FF00FF";
        }

        /// <summary>Writes the named palette's brushes onto the window's own resources, which sit in front of the merged Theme.xaml.</summary>
        public static void Apply(Window window, string name)
        {
            foreach (var entry in Palette(name))
            {
                try
                {
                    window.Resources[entry.Key] = Brush(entry.Value);
                }
                catch (Exception)
                {
                }
            }
        }
    }

    /// <summary>XAML loading, chrome, full screen and ownership shared by every window of the tool (pstm_ui.py).</summary>
    internal static class PstmChrome
    {
        private const string LayoutPrefix = "RevoBIM.UI.PanelTemplateManager.Layouts.";
        private const string IconResource = "RevoBIM.Resources.PanelTemplateManager.icon.png";

        public static readonly ChromeConfig Config = new ChromeConfig
        {
            IconResource = IconResource,
            Version = PstmCore.Version,
            Log = PstmCore.Log,
        };

        private static readonly Dictionary<Window, WindowDrawer> Drawers = new Dictionary<Window, WindowDrawer>();

        /// <summary>
        /// Parses a layout, merges Theme.xaml into it, applies the palette. Theme.xaml is merged AFTER the layout has been parsed, which is why a layout
        /// may only ever use DynamicResource.
        /// </summary>
        public static Window LoadWindow(string file, string palette)
        {
            Window window = XamlLoader.Load<Window>(LayoutPrefix + file, null);
            try
            {
                window.Resources.MergedDictionaries.Add((ResourceDictionary)XamlReader.Parse(XamlLoader.ReadResource(LayoutPrefix + "Theme.xaml")));
            }
            catch (Exception)
            {
            }
            PstmTheme.Apply(window, palette);
            return window;
        }

        public static void SetIcon(Image image)
        {
            ThemedWindow.LoadIcon(image, IconResource);
        }

        public static T Ctl<T>(Window w, string name) where T : class
        {
            return w.FindName(name) as T;
        }

        public static void SetText(Window w, string name, string text)
        {
            var tb = w.FindName(name) as TextBlock;
            if (tb != null) tb.Text = text;
        }

        /// <summary>The shrink drawer of a window of this tool: the header bar and the ShrinkButton (the style swaps to the green arrow on Tag "shrunk").</summary>
        public static WindowDrawer MakeDrawer(Window w)
        {
            var header = (FrameworkElement)w.FindName("HeaderBar");
            var drawer = new WindowDrawer(Config, w, header, null, w.FindName("ShrinkButton") as Button, null, null, null,
                                          WindowDrawer.ChildrenOf(header.Parent as Panel, header, null));
            Drawers[w] = drawer;
            w.Closed += (s, a) => Drawers.Remove(w);
            w.PreviewKeyDown += (s, a) =>
            {
                try
                {
                    Key key = a.Key == Key.System ? a.SystemKey : a.Key;
                    if (drawer.OnKey(key, RevoChrome.CtrlDown(), RevoChrome.ShiftDown())) a.Handled = true;
                }
                catch (Exception)
                {
                }
            };
            return drawer;
        }

        public static WindowDrawer DrawerOf(Window w)
        {
            WindowDrawer d;
            return w != null && Drawers.TryGetValue(w, out d) ? d : null;
        }

        /// <summary>
        /// Gives a dialog its owner and puts it where it can be seen: a dialog centred on an owner parked at the bottom of the screen is centred on a
        /// fifty pixel bar, so while the owner is parked it opens in the middle of the screen instead. The drawers are linked so the two shrink together.
        /// </summary>
        public static void Adopt(Window dialog, Window owner, WindowDrawer drawer)
        {
            if (owner == null) return;
            try
            {
                dialog.Owner = owner;
            }
            catch (Exception)
            {
                return;
            }
            WindowDrawer parent = DrawerOf(owner);
            if (parent != null)
            {
                if (drawer != null) drawer.SetOwner(parent);
                if (parent.Parked) dialog.WindowStartupLocation = WindowStartupLocation.CenterScreen;
            }
        }

        /// <summary>Drags a WindowStyle=None window by its header; while parked a double click brings it back.</summary>
        public static void WireDrag(Window window, FrameworkElement header, WindowDrawer drawer)
        {
            header.MouseLeftButtonDown += (s, a) =>
            {
                try
                {
                    if (drawer != null)
                    {
                        if (a.ClickCount == 2 && drawer.OnHeaderDoubleClick())
                        {
                            a.Handled = true;
                            return;
                        }
                        if (drawer.Parked)
                        {
                            if (!drawer.Sliding && drawer.CanDrag()) window.DragMove();
                            return;
                        }
                    }
                    window.DragMove();
                }
                catch (Exception)
                {
                }
            };
        }

        /// <summary>Floats above Revit rather than slipping behind it.</summary>
        public static void OwnByRevit(Window window, UIApplication uiapp)
        {
            RevoChrome.OwnToRevit(window, uiapp);
        }
    }

    /// <summary>Full screen by bounds, not WindowState.Maximized (a borderless AllowsTransparency window maximised the normal way covers the task bar).</summary>
    internal sealed class FullScreen
    {
        private readonly Window window;

        public double[] Saved;

        public FullScreen(Window window)
        {
            this.window = window;
        }

        public bool IsFull
        {
            get { return Saved != null; }
        }

        public bool Toggle()
        {
            if (Saved == null) Enter();
            else Leave();
            return IsFull;
        }

        public void Enter()
        {
            try
            {
                Saved = new[] { window.Left, window.Top, window.Width, window.Height };
                double l, t, r, b;
                RevoChrome.WorkArea(window, out l, out t, out r, out b);
                window.Left = l;
                window.Top = t;
                window.Width = r - l;
                window.Height = b - t;
            }
            catch (Exception)
            {
                Saved = null;
            }
        }

        public void Leave()
        {
            if (Saved == null) return;
            try
            {
                window.Left = Saved[0];
                window.Top = Saved[1];
                window.Width = Saved[2];
                window.Height = Saved[3];
            }
            catch (Exception)
            {
            }
            Saved = null;
        }
    }

    /// <summary>One line of the rename preview, read through a converter.</summary>
    internal sealed class RenameRow
    {
        public string Old, New, Note;

        public string Value(string key)
        {
            if (key == "old") return Old;
            if (key == "new") return New;
            return Note;
        }
    }

    /// <summary>The small themed dialogs: a prompt, a chooser, and the batch rename.</summary>
    internal static class PstmDialogs
    {
        /// <summary>A small themed dialog. Returns the index of the button pressed, or -1. buttons: (label, style) where style is primary / danger / accent / ghost.</summary>
        public static int Ask(Window owner, string palette, string title, string message, List<KeyValuePair<string, string>> buttons = null,
                              string accent = "blue", string version = "")
        {
            Window w = PstmChrome.LoadWindow("PstmPrompt.xaml", palette);
            WindowDrawer drawer = PstmChrome.MakeDrawer(w);
            PstmChrome.Adopt(w, owner, drawer);
            int result = -1;
            PstmChrome.SetText(w, "TitleText", title);
            PstmChrome.SetText(w, "MessageText", message);
            PstmChrome.SetText(w, "VersionText", version);
            var tick = w.FindName("AccentTick") as Border;
            if (tick != null)
            {
                string key = accent == "red" ? "RedBrush" : accent == "orange" ? "OrangeBrush" : accent == "green" ? "GreenBrush" : "BlueBrush";
                tick.SetResourceReference(Border.BackgroundProperty, key);
            }
            PstmChrome.WireDrag(w, (FrameworkElement)w.FindName("HeaderBar"), drawer);
            var close = w.FindName("CloseButton") as Button;
            if (close != null)
            {
                close.Click += (s, a) =>
                {
                    result = -1;
                    w.DialogResult = false;
                };
            }
            List<KeyValuePair<string, string>> list = buttons ?? new List<KeyValuePair<string, string>> { new KeyValuePair<string, string>("OK", "default") };
            var host = (Panel)w.FindName("ButtonHost");
            for (int i = 0; i < list.Count; i++)
            {
                int index = i;
                var btn = new Button { Content = list[i].Key, Margin = new Thickness(6, 0, 0, 0), MinWidth = 92 };
                string style = list[i].Value;
                if (style != "default")
                {
                    string styleKey = style == "primary" ? "PrimaryButton" : style == "danger" ? "DangerButton" : style == "accent" ? "AccentButton" : "GhostButton";
                    btn.SetResourceReference(FrameworkElement.StyleProperty, styleKey);
                }
                btn.Click += (s, a) =>
                {
                    result = index;
                    w.DialogResult = true;
                };
                host.Children.Add(btn);
            }
            try
            {
                w.ShowDialog();
            }
            catch (Exception)
            {
            }
            return result;
        }

        public static List<KeyValuePair<string, string>> Buttons(params string[] labelAndStyle)
        {
            var list = new List<KeyValuePair<string, string>>();
            for (int i = 0; i + 1 < labelAndStyle.Length; i += 2) list.Add(new KeyValuePair<string, string>(labelAndStyle[i], labelAndStyle[i + 1]));
            return list;
        }

        public static void Info(Window owner, string palette, string title, string message, string version = "")
        {
            Ask(owner, palette, title, message, Buttons("Close", "default"), "blue", version);
        }

        /// <summary>Pick one thing out of a list. Returns the chosen item, or null.</summary>
        public static string Choose(Window owner, string palette, string title, string message, List<string> choices, string okText = "OK",
                                    string version = "", int preselect = 0)
        {
            Window w = PstmChrome.LoadWindow("PstmChoose.xaml", palette);
            WindowDrawer drawer = PstmChrome.MakeDrawer(w);
            PstmChrome.Adopt(w, owner, drawer);
            string result = null;
            PstmChrome.SetText(w, "TitleText", title);
            PstmChrome.SetText(w, "MessageText", message);
            PstmChrome.SetText(w, "VersionText", version);
            var ok = (Button)w.FindName("OkButton");
            ok.Content = okText;
            var listbox = (ListBox)w.FindName("ChoiceList");
            foreach (string item in choices) listbox.Items.Add(item);
            if (listbox.Items.Count > 0) listbox.SelectedIndex = Math.Min(preselect, listbox.Items.Count - 1);
            Action accept = () =>
            {
                string chosen = listbox.SelectedItem as string;
                if (chosen == null) return;
                result = chosen;
                try { w.DialogResult = true; } catch (Exception) { w.Close(); }
            };
            Action cancel = () =>
            {
                result = null;
                try { w.DialogResult = false; } catch (Exception) { w.Close(); }
            };
            listbox.MouseDoubleClick += (s, a) => accept();
            PstmChrome.WireDrag(w, (FrameworkElement)w.FindName("HeaderBar"), drawer);
            ((Button)w.FindName("CloseButton")).Click += (s, a) => cancel();
            ((Button)w.FindName("CancelButton")).Click += (s, a) => cancel();
            ok.Click += (s, a) => accept();
            try
            {
                w.ShowDialog();
            }
            catch (Exception)
            {
            }
            return result;
        }

        /// <summary>
        /// Find and replace, prefix and suffix over a set of names. The preview is the point of the window: every row shows what it would become
        /// before anything is written. Returns (old, new) for the names that actually change, or null if cancelled.
        /// </summary>
        public static List<KeyValuePair<string, string>> Rename(Window owner, string palette, List<string> names, string version = "")
        {
            Window w = PstmChrome.LoadWindow("PstmRename.xaml", palette);
            WindowDrawer drawer = PstmChrome.MakeDrawer(w);
            PstmChrome.Adopt(w, owner, drawer);
            List<KeyValuePair<string, string>> result = null;
            List<RenamePreviewRow> rows = new List<RenamePreviewRow>();
            PstmChrome.SetText(w, "VersionText", version);
            PstmChrome.SetText(w, "MessageText", names.Count + " template" + (names.Count == 1 ? "" : "s") + " selected.  Nothing is renamed until you press Rename.");

            var preview = (DataGrid)w.FindName("PreviewGrid");
            Func<object, string, object> cellText = (row, key) =>
            {
                var r = row as RenameRow;
                return r == null ? "" : r.Value(key);
            };
            Func<object, string, object> cellFore = (row, key) =>
            {
                var r = row as RenameRow;
                if (r != null && !string.IsNullOrEmpty(r.Note)) return key != "old" ? Brushes.IndianRed : Brushes.Gray;
                try { return w.FindResource("TextBrush"); } catch (Exception) { return Brushes.Gray; }
            };
            var textConv = new RowConverter(cellText);
            var backConv = new RowConverter((row, key) => null);
            var foreConv = new RowConverter(cellFore);
            foreach (var col in new[] { Tuple.Create("Now", "old", 1.0, 150.0), Tuple.Create("After the rename", "new", 1.0, 150.0), Tuple.Create("", "note", 0.8, 90.0) })
            {
                DataTemplate cell = PstmGrid.TextCellTemplate(textConv, backConv, foreConv, col.Item2);
                preview.Columns.Add(PstmGrid.MakeColumn(col.Item1, cell, col.Item4, col.Item2, col.Item4, col.Item3, false));
            }

            Action refresh = () =>
            {
                var tb = (TextBox)w.FindName("FindBox");
                rows = PstmCore.PreviewRename(names, tb.Text ?? "", ((TextBox)w.FindName("ReplaceBox")).Text ?? "",
                                              ((CheckBox)w.FindName("MatchCaseCheck")).IsChecked == true,
                                              ((TextBox)w.FindName("PrefixBox")).Text ?? "", ((TextBox)w.FindName("SuffixBox")).Text ?? "",
                                              ((CheckBox)w.FindName("DropMasterCheck")).IsChecked == true);
                var items = new List<object>();
                int changing = 0, trouble = 0;
                foreach (RenamePreviewRow r in rows)
                {
                    if (!string.IsNullOrEmpty(r.Note)) trouble++;
                    else if (r.New != r.Old) changing++;
                    items.Add(new RenameRow { Old = r.Old, New = r.New, Note = r.Note });
                }
                preview.ItemsSource = items;
                var bits = new List<string>();
                bits.Add(changing > 0 ? changing + " will be renamed" : "nothing would change yet");
                if (trouble > 0) bits.Add(trouble + " cannot be (see the notes)");
                PstmChrome.SetText(w, "CountText", string.Join(", ", bits) + ".");
                ((Button)w.FindName("OkButton")).IsEnabled = changing > 0;
            };
            foreach (string name in new[] { "FindBox", "ReplaceBox", "PrefixBox", "SuffixBox" }) ((TextBox)w.FindName(name)).TextChanged += (s, a) => refresh();
            ((CheckBox)w.FindName("MatchCaseCheck")).Click += (s, a) => refresh();
            ((CheckBox)w.FindName("DropMasterCheck")).Click += (s, a) => refresh();
            PstmChrome.WireDrag(w, (FrameworkElement)w.FindName("HeaderBar"), drawer);
            Action cancel = () =>
            {
                result = null;
                try { w.DialogResult = false; } catch (Exception) { w.Close(); }
            };
            ((Button)w.FindName("CloseButton")).Click += (s, a) => cancel();
            ((Button)w.FindName("CancelButton")).Click += (s, a) => cancel();
            ((Button)w.FindName("OkButton")).Click += (s, a) =>
            {
                result = rows.Where(r => string.IsNullOrEmpty(r.Note) && r.New != r.Old).Select(r => new KeyValuePair<string, string>(r.Old, r.New)).ToList();
                try { w.DialogResult = true; } catch (Exception) { w.Close(); }
            };
            refresh();
            try
            {
                w.ShowDialog();
            }
            catch (Exception)
            {
            }
            return result;
        }
    }
}
