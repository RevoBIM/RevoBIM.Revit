using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Effects;
using System.Windows.Threading;
using RevoBIM.Tools.AddinManager;

using Border = System.Windows.Controls.Border;
using ToolTip = System.Windows.Controls.ToolTip;

namespace RevoBIM.UI.AddinManager
{
    /// <summary>
    /// The favourites grid behind the yellow star: uniform tiles filled left to right and top to bottom, like a phone's home
    /// screen. Press and hold (or drag) a tile to lift it; it follows the cursor and the others make way; letting go drops
    /// it into the slot. A press let go before it lifts is a click and runs the addin. The mouse is captured on the grid,
    /// never on a tile (a tile taken out of the tree while it holds the capture loses it). Port of rba_favs.py; the
    /// easing animations of the original are not ported - tiles move at once.
    /// </summary>
    internal sealed class AmFavs
    {
        private const int TilePad = 26;
        private const int TileMin = 66;
        private const int CardPad = 6;
        private const double LiftScale = 1.14;

        private sealed class Press
        {
            public AmItem Item;
            public string Key;
            public Border Tile;
            public Point Start;
            public Point Grab;
        }

        private sealed class Fx
        {
            public ScaleTransform Scale;
            public TranslateTransform Move;
            public DropShadowEffect Shadow;
        }

        private readonly AmPane pane;
        private readonly WrapPanel panel;
        private readonly DispatcherTimer hold;
        private Dictionary<string, Fx> fx = new Dictionary<string, Fx>();
        private Press press;
        private bool lifted;

        public AmFavs(AmPane pane, WrapPanel panel)
        {
            this.pane = pane;
            this.panel = panel;
            hold = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(AmCore.FavHoldMs) };
            hold.Tick += OnHold;
            panel.PreviewMouseMove += OnMove;
            panel.PreviewMouseLeftButtonUp += OnUp;
            panel.MouseRightButtonUp += OnPanelContext;
            panel.LostMouseCapture += (s, a) => { if (lifted) Drop(); };
        }

        // ------------------------------------------------------------------ state

        private List<string> Keys() { return AmCore.AsList(pane.Settings, "favourites"); }
        public bool LabelsShown() { return AmCore.AsBool(pane.Settings, "fav_labels"); }
        public bool IsFavourite(AmItem item) { return Keys().Contains(item.Key); }

        public void Toggle(AmItem item)
        {
            List<string> keys = Keys();
            string note;
            if (keys.Contains(item.Key))
            {
                keys = AmCore.FavRemove(keys, item.Key);
                note = item.Title + " taken out of favourites";
            }
            else
            {
                keys = AmCore.FavAdd(keys, item.Key);
                note = item.Title + " added to favourites";
            }
            AmCore.SetList(pane.Settings, "favourites", keys);
            bool added = keys.Contains(item.Key);
            if (added) pane.Settings["view"] = "favourites";   // straight to the grid, so the new favourite can be seen
            pane.SaveSettings();
            pane.Render();
            pane.SetStatus(note);
            if (added) Pop(item.Key);
        }

        public void ToggleLabels()
        {
            pane.Settings["fav_labels"] = LabelsShown() ? "0" : "1";
            pane.SaveSettings();
            pane.Render();
        }

        // ------------------------------------------------------------------ render

        /// <summary>Rebuilds the grid; returns how many tiles it drew.</summary>
        public int Render()
        {
            CancelPress();
            panel.Children.Clear();
            fx = new Dictionary<string, Fx>();
            var byKey = new Dictionary<string, AmItem>();
            foreach (AmItem item in pane.Items) byKey[item.Key] = item;

            // a favourite whose button has gone is kept in the list, not shown: it returns to its old spot with the button
            var items = new List<AmItem>();
            foreach (string key in Keys())
            {
                AmItem found;
                if (byKey.TryGetValue(key, out found)) items.Add(found);
            }

            int icon = AmCore.FavIconSize(pane.IconSize());
            double width = Math.Max(TileMin, icon + CardPad * 2 + TilePad);
            panel.ItemWidth = width;
            if (items.Count == 0)
            {
                panel.ItemWidth = double.NaN;
                panel.Children.Add(EmptyNote());
                return 0;
            }
            foreach (AmItem item in items) panel.Children.Add(Tile(item, icon, width));
            return items.Count;
        }

        private FrameworkElement EmptyNote()
        {
            return new TextBlock
            {
                Text = "No favourites yet.\n\nRight click any addin in the list and choose Add to favourites. They fill in here " +
                       "from the top left, and can be dragged into any order.",
                TextWrapping = TextWrapping.Wrap,
                Foreground = pane.Res("FgMuted") as Brush,
                FontFamily = new FontFamily("Segoe UI"),
                FontSize = 12,
                Margin = new Thickness(4, 6, 4, 6),
                MaxWidth = 300,
            };
        }

        private Border Tile(AmItem item, int icon, double width)
        {
            var tile = new Border
            {
                Tag = item.Key,
                Width = width,
                Padding = new Thickness(2, 4, 2, 4),
                Margin = new Thickness(0, 0, 0, 2),
                CornerRadius = new CornerRadius(6),
                Background = pane.Res("BgWindow") as Brush,
                Cursor = Cursors.Hand,
            };
            var scale = new ScaleTransform(1.0, 1.0);
            var move = new TranslateTransform(0.0, 0.0);
            var group = new TransformGroup();
            group.Children.Add(scale);
            group.Children.Add(move);
            tile.RenderTransform = group;
            tile.RenderTransformOrigin = new Point(0.5, 0.5);

            var stack = new StackPanel { HorizontalAlignment = HorizontalAlignment.Center };
            var card = new Border
            {
                Background = pane.Res("BgCard") as Brush,
                CornerRadius = new CornerRadius(7),
                Padding = new Thickness(CardPad),
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 0, 0, 4),
            };
            DropShadowEffect shadow = null;
            try
            {
                shadow = new DropShadowEffect { Color = pane.Res("ShadowColor") is Color ? (Color)pane.Res("ShadowColor") : Colors.Black, Direction = 270 };
                SetShadow(shadow, 0.0);
                card.Effect = shadow;
            }
            catch (Exception err)
            {
                shadow = null;
                AmCore.LogException("fav/shadow", err);
            }
            fx[item.Key] = new Fx { Scale = scale, Move = move, Shadow = shadow };

            card.Child = pane.IconFor(item, icon);
            stack.Children.Add(card);

            if (LabelsShown())
            {
                stack.Children.Add(new TextBlock
                {
                    Text = item.Title,
                    FontFamily = new FontFamily("Segoe UI"),
                    FontSize = 10.5,
                    Foreground = pane.Res("FgText") as Brush,
                    TextAlignment = TextAlignment.Center,
                    TextWrapping = TextWrapping.Wrap,
                    TextTrimming = TextTrimming.CharacterEllipsis,
                    MaxHeight = 30,
                    MaxWidth = width - 4,
                    HorizontalAlignment = HorizontalAlignment.Center,
                });
            }
            tile.Child = stack;
            tile.ToolTip = new ToolTip { Content = item.Tooltip.Length > 0 ? item.Title + "\n" + item.Tooltip : item.Title };

            Brush hover = pane.Res("BgHover") as Brush;
            Brush rest = pane.Res("BgWindow") as Brush;
            tile.MouseEnter += (s, a) => { if (!lifted) ((Border)s).Background = hover; };
            tile.MouseLeave += (s, a) => { if (!lifted) ((Border)s).Background = rest; };
            tile.PreviewMouseLeftButtonDown += (s, a) =>
            {
                if (lifted) return;
                try
                {
                    press = new Press { Item = item, Key = item.Key, Tile = (Border)s, Start = a.GetPosition(panel), Grab = a.GetPosition((Border)s) };
                    hold.Stop();
                    hold.Start();
                }
                catch (Exception)
                {
                    press = null;
                }
            };
            tile.MouseRightButtonUp += (s, a) => pane.ShowMenu((FrameworkElement)s, item, a);
            return tile;
        }

        // ------------------------------------------------------------------ effects

        private void SetShadow(DropShadowEffect shadow, double lift)
        {
            if (shadow == null) return;
            bool dark = pane.ThemeName == "dark";
            double restOpacity = dark ? 0.45 : 0.30;
            double upOpacity = dark ? 0.60 : 0.42;
            shadow.BlurRadius = 7.0 + (18.0 - 7.0) * lift;
            shadow.ShadowDepth = 1.5 + (7.0 - 1.5) * lift;
            shadow.Opacity = restOpacity + (upOpacity - restOpacity) * lift;
        }

        private void SetScale(string key, double value)
        {
            Fx f;
            if (fx.TryGetValue(key, out f)) { f.Scale.ScaleX = value; f.Scale.ScaleY = value; }
        }

        /// <summary>A new favourite arrives: scrolled to and given a little pop.</summary>
        private void Pop(string key)
        {
            Border tile = TileFor(key);
            try { if (tile != null) tile.BringIntoView(); } catch (Exception) { }
            SetScale(key, 1.1);
            var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(220) };
            timer.Tick += (s, a) => { timer.Stop(); SetScale(key, 1.0); };
            timer.Start();
        }

        // ------------------------------------------------------------------ geometry

        private Border TileFor(string key)
        {
            foreach (UIElement child in panel.Children)
            {
                var border = child as Border;
                if (border != null && (border.Tag as string) == key) return border;
            }
            return null;
        }

        /// <summary>Where a tile BELONGS, ignoring any render transform it has.</summary>
        private static double[] Slot(UIElement child)
        {
            Rect r = LayoutInformation.GetLayoutSlot((FrameworkElement)child);
            return new[] { r.X, r.Y, r.Width, r.Height };
        }

        private List<double[]> Slots()
        {
            var list = new List<double[]>();
            foreach (UIElement child in panel.Children)
            {
                try { list.Add(Slot(child)); } catch (Exception) { list.Add(new double[4]); }
            }
            return list;
        }

        // ------------------------------------------------------------------ pick up

        private void CancelPress()
        {
            try { hold.Stop(); } catch (Exception) { }
            if (!lifted) press = null;
        }

        private void OnHold(object sender, EventArgs args)
        {
            hold.Stop();
            if (press == null || lifted) return;
            try
            {
                if (Mouse.LeftButton != MouseButtonState.Pressed)
                {
                    press = null;
                    return;
                }
            }
            catch (Exception) { }
            Lift();
        }

        private void Lift()
        {
            if (press == null || lifted) return;
            hold.Stop();
            lifted = true;
            try { panel.CaptureMouse(); } catch (Exception) { }
            Panel.SetZIndex(press.Tile, 100);
            press.Tile.Cursor = Cursors.SizeAll;
            SetScale(press.Key, LiftScale);
            Fx f;
            if (fx.TryGetValue(press.Key, out f)) SetShadow(f.Shadow, 1.0);
            try { Follow(Mouse.GetPosition(panel), false); } catch (Exception) { }
        }

        private void OnMove(object sender, MouseEventArgs args)
        {
            if (press == null) return;
            Point here;
            try
            {
                if (args.LeftButton != MouseButtonState.Pressed)
                {
                    if (lifted) Drop(); else CancelPress();
                    return;
                }
                here = args.GetPosition(panel);
            }
            catch (Exception)
            {
                return;
            }
            if (!lifted)
            {
                if (Math.Abs(here.X - press.Start.X) < AmCore.FavDragPx && Math.Abs(here.Y - press.Start.Y) < AmCore.FavDragPx) return;
                Lift();
            }
            Follow(here, true);
        }

        /// <summary>Keeps the lifted tile under the cursor and moves its slot to the one below.</summary>
        private void Follow(Point here, bool reorder)
        {
            if (press == null) return;
            Border tile = press.Tile;
            if (reorder)
            {
                int source = panel.Children.IndexOf(tile);
                int target = AmCore.DropIndex(Slots(), here.X, here.Y);
                if (source >= 0 && target >= 0 && target != source)
                {
                    panel.Children.RemoveAt(source);
                    panel.Children.Insert(Math.Min(target, panel.Children.Count), tile);
                    try { panel.UpdateLayout(); } catch (Exception) { }
                }
            }
            Fx f;
            if (!fx.TryGetValue(press.Key, out f)) return;
            double[] slot = Slot(tile);
            f.Move.X = here.X - press.Grab.X - slot[0];
            f.Move.Y = here.Y - press.Grab.Y - slot[1];
        }

        // ------------------------------------------------------------------ let go

        private void OnUp(object sender, MouseButtonEventArgs args)
        {
            if (press == null) return;
            hold.Stop();
            if (lifted)
            {
                Drop();
                args.Handled = true;
                return;
            }
            Press clicked = press;
            press = null;
            pane.Launch(clicked.Item);   // let go before it lifted: a click
        }

        private void Drop()
        {
            Press dropped = press;
            press = null;
            if (!lifted) return;
            lifted = false;
            hold.Stop();
            try { panel.ReleaseMouseCapture(); } catch (Exception) { }
            if (dropped == null) return;

            Fx f;
            if (fx.TryGetValue(dropped.Key, out f))
            {
                f.Move.X = 0; f.Move.Y = 0;
                f.Scale.ScaleX = 1; f.Scale.ScaleY = 1;
                SetShadow(f.Shadow, 0.0);
            }
            Panel.SetZIndex(dropped.Tile, 0);
            dropped.Tile.Cursor = Cursors.Hand;

            var shown = new List<string>();
            foreach (UIElement child in panel.Children)
            {
                var tag = (child as FrameworkElement) == null ? null : ((FrameworkElement)child).Tag as string;
                if (!string.IsNullOrEmpty(tag)) shown.Add(tag);
            }
            List<string> order = AmCore.MergeOrder(Keys(), shown);
            if (!order.SequenceEqual(Keys()))
            {
                AmCore.SetList(pane.Settings, "favourites", order);
                pane.SaveSettings();
                AmCore.Log("favourites reordered");
            }
        }

        // ------------------------------------------------------------------ empty space

        private void OnPanelContext(object sender, MouseButtonEventArgs args)
        {
            if (args.Handled) return;
            try
            {
                var menu = new ContextMenu();
                AmXaml.MergeTheme(menu);
                AmXaml.ApplyMenuTheme(menu, pane.ThemeName);
                var entry = new MenuItem { Header = LabelsShown() ? "Hide the names" : "Show the names" };
                entry.Click += (s, a) => ToggleLabels();
                menu.Items.Add(entry);
                menu.PlacementTarget = panel;
                menu.IsOpen = true;
                args.Handled = true;
            }
            catch (Exception err)
            {
                AmCore.LogException("fav/panel menu", err);
            }
        }
    }
}
