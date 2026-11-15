// Port of efr_core.py's ThemedDialog and themed_message (lines 2518-2685).
using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using RevoBIM.Tools.ExcelForRevit;
using static RevoBIM.Tools.ExcelForRevit.Efr;
using static RevoBIM.UI.ExcelForRevit.EfrUi;

namespace RevoBIM.UI.ExcelForRevit
{
    /// <summary>A small RevoBIM-themed window built in code, so no extra XAML files.</summary>
    public class ThemedDialog
    {
        /// <summary>The value of the footer button (or CloseWith call) that closed the dialog; null if closed otherwise.</summary>
        public object Result;
        public Window Window;
        public Button ShrinkBtn;
        public StackPanel Body;
        public StackPanel Footer;
        public WindowDrawer Drawer;

        /// <param name="accent">Colour of the subtitle; null = the current palette's C_ORANGE.</param>
        /// <param name="height">Fixed height; null or 0 sizes the window to its content.</param>
        public ThemedDialog(string subtitle, double width = 520, double? height = null, Window owner = null, string accent = null)
        {
            if (accent == null)
                accent = C_ORANGE;
            Result = null;
            Window = new Window();
            Window.Title = "RevoBIM — " + subtitle;
            Window.WindowStyle = WindowStyle.None;
            Window.AllowsTransparency = true;
            Window.Background = Brush("#00FFFFFF");
            Window.ResizeMode = ResizeMode.NoResize;
            Window.WindowStartupLocation = WindowStartupLocation.CenterOwner;
            Window.Width = width;
            Window.FontFamily = new FontFamily("Segoe UI");
            Window.FontSize = 12;
            ThemeWindow(Window);
            if (height.HasValue && height.Value != 0)
                Window.Height = height.Value;
            else
                Window.SizeToContent = SizeToContent.Height;
            if (owner != null)
            {
                try
                {
                    Window.Owner = owner;
                }
                catch (Exception)
                {
                }
                try
                {
                    // an owner shrunk to its own title bar has no middle worth centring
                    // on, so a prompt raised over a parked window goes to the middle of
                    // the screen instead of the taskbar
                    if (owner.ActualHeight < 140)
                        Window.WindowStartupLocation = WindowStartupLocation.CenterScreen;
                }
                catch (Exception)
                {
                }
            }
            else
            {
                Window.WindowStartupLocation = WindowStartupLocation.CenterScreen;
            }

            var shell = new Border();
            shell.Background = Brush(C_WINDOW);
            shell.BorderBrush = Brush(C_EDGE_SOFT);
            shell.BorderThickness = new Thickness(1);
            shell.CornerRadius = new CornerRadius(6);
            Window.Content = shell;

            var root = new Grid();
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            shell.Child = root;

            // header
            var head = new Border();
            head.Background = Brush(C_BAR);
            head.CornerRadius = new CornerRadius(6, 6, 0, 0);
            head.Padding = new Thickness(14, 8, 10, 8);
            var hg = new Grid();
            hg.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            hg.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            hg.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var titles = new StackPanel();
            titles.Children.Add(Tb("RevoBIM", C_BLUE, 20, true));
            TextBlock sub = Tb(subtitle, accent, 15);
            sub.Margin = new Thickness(1, -2, 0, 0);
            titles.Children.Add(sub);
            Grid.SetColumn(titles, 0);
            hg.Children.Add(titles);
            var chrome = new StackPanel();
            chrome.Orientation = Orientation.Horizontal;
            chrome.VerticalAlignment = VerticalAlignment.Top;
            chrome.HorizontalAlignment = HorizontalAlignment.Right;
            chrome.Margin = new Thickness(0, -2, -6, 0);
            TextBlock ver = Tb("v" + Efr.Version, C_MUTED, 11);
            ver.VerticalAlignment = VerticalAlignment.Center;
            ver.Margin = new Thickness(0, 0, 8, 0);
            chrome.Children.Add(ver);
            ShrinkBtn = WinButton(DRAWER_DOWN, DRAWER_TIP_DOWN);
            chrome.Children.Add(ShrinkBtn);
            Grid.SetColumn(chrome, 2);
            hg.Children.Add(chrome);
            head.Child = hg;
            Grid.SetRow(head, 0);
            root.Children.Add(head);
            try
            {
                head.MouseLeftButtonDown += Drag;
            }
            catch (Exception)
            {
            }

            // body
            Body = new StackPanel();
            Body.Margin = new Thickness(16, 14, 16, 14);
            var holder = new ScrollViewer();
            holder.VerticalScrollBarVisibility = ScrollBarVisibility.Auto;
            holder.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled;
            holder.Content = Body;
            Grid.SetRow(holder, 1);
            root.Children.Add(holder);

            // footer
            var foot = new Border();
            foot.Background = Brush(C_BAR);
            foot.BorderBrush = Brush(C_EDGE);
            foot.BorderThickness = new Thickness(0, 1, 0, 0);
            foot.CornerRadius = new CornerRadius(0, 0, 6, 6);
            foot.Padding = new Thickness(12, 10, 12, 10);
            Footer = new StackPanel();
            Footer.Orientation = Orientation.Horizontal;
            Footer.HorizontalAlignment = HorizontalAlignment.Right;
            foot.Child = Footer;
            Grid.SetRow(foot, 2);
            root.Children.Add(foot);

            // every window in the tool shrinks the same way, this one included
            Drawer = new WindowDrawer(Window, head, root, ShrinkBtn);
            try
            {
                ShrinkBtn.Click += (s, a) => Drawer.Toggle();
            }
            catch (Exception)
            {
            }
        }

        private void Drag(object sender, MouseButtonEventArgs args)
        {
            try
            {
                Window.DragMove();
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Put an element on the body stack; returns it.</summary>
        public T Add<T>(T element) where T : UIElement
        {
            Body.Children.Add(element);
            return element;
        }

        /// <summary>
        /// A footer button. Clicking runs handler (if any), then closes with `value` when
        /// close is true. kind: "ghost", "green", "red" or "orange".
        /// </summary>
        public Button AddButton(string label, string kind = "ghost", object value = null, bool close = true, Action handler = null)
        {
            Button btn = StyledButton(label, kind);
            btn.Click += (sender, args) =>
            {
                if (handler != null)
                    handler();
                if (close)
                    CloseWith(value);
            };
            Footer.Children.Add(btn);
            return btn;
        }

        /// <summary>
        /// Close the way a footer button does, so a double-click or Enter on a list can
        /// stand in for pressing the button.
        /// </summary>
        public void CloseWith(object value)
        {
            Result = value;
            try
            {
                Window.DialogResult = true;
            }
            catch (Exception)
            {
            }
            try
            {
                Window.Close();
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Show modally and return Result (null when closed without a button).</summary>
        public object Show()
        {
            try
            {
                Window.ShowDialog();
            }
            catch (Exception)
            {
                Window.Show();
            }
            return Result;
        }

        /// <summary>Result as text ("ok", "cancel", "apply" ...), or null.</summary>
        public string ResultText
        {
            get { return Result as string; }
        }
    }

    public static partial class EfrUi
    {
        /// <summary>A themed message box with one OK button. accent null = the current palette's C_ORANGE.</summary>
        public static object ThemedMessage(string subtitle, string message, Window owner = null, string accent = null, double width = 520)
        {
            var dlg = new ThemedDialog(subtitle, width, null, owner, accent);
            dlg.Add(Tb(message, C_TEXT, 12, false, true));
            dlg.AddButton("OK", "ghost", "ok");
            return dlg.Show();
        }
    }
}
