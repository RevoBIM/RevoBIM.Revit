using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using RevoBIM.Tools.HangerAutomation;

namespace RevoBIM.UI.HangerAutomation
{
    /// <summary>
    /// Shrink a window to its title bar, slid down to the bottom of its screen like a drawer closing, so Revit can be
    /// seen - and open it again. One per window (the main window and every dialog), per the RevoBIM theme reference.
    /// Port of fha_ui.Drawer.
    ///
    /// Shrink(): MinHeight and SizeToContent are relaxed, the body is pinned at its height (so it is clipped, not
    /// re-laid-out, as the window closes over it), the grips park, then Top and Height slide together (CubicEase,
    /// DrawerMs) to FhaCore.ShrunkTop. On landing the body collapses and the bar gets four round corners.
    /// Expand(): the reverse, to FhaCore.ExpandTop - back where it was, or up from where the bar was dragged. Both
    /// animations are released when they land (BeginAnimation(p, null) in its own try) and the final numbers written
    /// straight on; if an animation cannot start, the same finish runs at once.
    ///
    /// Owner: the drawer of the window a modal dialog belongs to - shrinking the dialog parks the owner too (a slot
    /// below it), and the owner comes back when the dialog opens again or closes.
    /// Body: the elements to collapse while parked (default: the header's siblings). OnChange(shrunk): swap the
    /// button's glyphs.
    /// </summary>
    public sealed class FhaDrawer
    {
        private sealed class Saved
        {
            public double Top, Height, MinHeight;
            public SizeToContent? SizeToContent;
        }

        public readonly Window Win;
        public readonly FhaChrome Chrome;
        public readonly FrameworkElement Header;
        public readonly FrameworkElement Button;
        public readonly UIElement ShrinkIcon, ExpandIcon;
        /// <summary>The elements to collapse while parked.</summary>
        public Func<IEnumerable<UIElement>> Body;
        /// <summary>If set, called on expand instead of re-showing the collapsed elements.</summary>
        public Action ShowBody;
        public Action<bool> OnChange;
        public FhaDrawer Owner;
        public UIElement Grips;

        public bool Shrunk;
        public bool Moving;
        private Saved saved;               // (Top, Height, MinHeight, SizeToContent)
        public double? BarTop;             // where the bar landed
        public List<UIElement> Hidden = new List<UIElement>();   // what shrink collapsed (and expand shows again)
        public bool ParkedOwner;
        /// <summary>The finishing step of the slide in progress (the Python bench ran it in place of WPF's clock).</summary>
        public Action PendingFinish;
        /// <summary>(top, height) the slide in progress is heading for.</summary>
        public double[] Target;
        public int Slot;

        public FhaDrawer(Window win, FhaChrome chrome, FrameworkElement header, FrameworkElement button = null,
                         UIElement shrinkIcon = null, UIElement expandIcon = null, Func<IEnumerable<UIElement>> body = null,
                         Action showBody = null, Action<bool> onChange = null, FhaDrawer owner = null, UIElement grips = null)
        {
            Win = win;
            Chrome = chrome;
            Header = header;
            Button = button;
            ShrinkIcon = shrinkIcon;
            ExpandIcon = expandIcon;
            Body = body ?? (() => FhaUi.HeaderSiblings(header));
            ShowBody = showBody;
            OnChange = onChange;
            Owner = owner;
            Grips = grips;
        }

        // ---- helpers
        public void Toggle()
        {
            if (Moving) return;
            if (Shrunk) Expand();
            else Shrink();
        }

        public double BarHeight()
        {
            try
            {
                double h = Header.ActualHeight;
                return (h > 0 ? h : 56.0) + 12.0 + 2.0;   // the 6 px window margin each side and the 1 px border
            }
            catch (Exception)
            {
                return 70.0;
            }
        }

        private Rect WorkArea()
        {
            try
            {
                return Chrome.WorkArea();
            }
            catch (Exception)
            {
                return SystemParameters.WorkArea;
            }
        }

        private void Glyphs(bool shrunk)
        {
            try
            {
                if (ShrinkIcon != null) ShrinkIcon.Visibility = shrunk ? Visibility.Collapsed : Visibility.Visible;
                if (ExpandIcon != null) ExpandIcon.Visibility = shrunk ? Visibility.Visible : Visibility.Collapsed;
                if (Button != null) Button.ToolTip = shrunk ? FhaUi.ExpandTip : FhaUi.ShrinkTip;
            }
            catch (Exception)
            {
            }
            if (OnChange != null)
            {
                try
                {
                    OnChange(shrunk);
                }
                catch (Exception)
                {
                }
            }
        }

        /// <summary>Hold the body at a fixed height for the slide (clipped, not squashed).</summary>
        private void Pin(double height)
        {
            try
            {
                var root = (FrameworkElement)Win.Content;
                root.Height = height;
                root.VerticalAlignment = VerticalAlignment.Top;
            }
            catch (Exception)
            {
            }
        }

        private void Unpin()
        {
            try
            {
                var root = (FrameworkElement)Win.Content;
                root.Height = double.NaN;
                root.VerticalAlignment = VerticalAlignment.Stretch;
            }
            catch (Exception)
            {
            }
        }

        private void Slide(double top, double height, Action done)
        {
            Window win = Win;
            Moving = true;
            Target = new[] { top, height };
            bool finished = false;

            Action finish = () =>
            {
                if (finished) return;
                finished = true;
                try
                {
                    win.BeginAnimation(Window.TopProperty, null);
                    win.BeginAnimation(FrameworkElement.HeightProperty, null);
                }
                catch (Exception)
                {
                }
                try
                {
                    win.Top = top;
                    win.Height = height;
                }
                catch (Exception)
                {
                }
                Moving = false;
                done();
            };
            PendingFinish = finish;   // the bench runs it in place of WPF's clock
            try
            {
                var aH = FhaUi.Eased(win.ActualHeight, height, FhaUi.DrawerMs);
                var aT = FhaUi.Eased(win.Top, top, FhaUi.DrawerMs);
                aH.Completed += (s, e) => finish();
                win.BeginAnimation(Window.TopProperty, aT);
                win.BeginAnimation(FrameworkElement.HeightProperty, aH);
            }
            catch (Exception)
            {
                finish();   // no animation: land at once
            }
        }

        // ---- shrink
        public void Shrink(int slot = 0)
        {
            if (Shrunk || Moving) return;
            Window win = Win;
            try
            {
                if (Chrome != null && Chrome.Full) Chrome.ToggleFull();
            }
            catch (Exception)
            {
            }
            if (Owner != null && !Owner.Shrunk && !Owner.Moving)
            {
                Owner.Shrink(0);          // a modal dialog takes its owner down, parked beneath it
                ParkedOwner = true;
                slot = 1;
            }
            Slot = slot;
            try
            {
                saved = new Saved { Top = win.Top, Height = win.ActualHeight, MinHeight = win.MinHeight, SizeToContent = win.SizeToContent };
            }
            catch (Exception)
            {
                saved = new Saved { Top = win.Top, Height = win.ActualHeight, MinHeight = 0.0, SizeToContent = null };
            }
            double bar = BarHeight();
            Rect wa = WorkArea();
            BarTop = FhaCore.ShrunkTop(wa.Top, wa.Height, bar, Slot, FhaUi.BarGap);
            try
            {
                win.SizeToContent = SizeToContent.Manual;
            }
            catch (Exception)
            {
            }
            win.MinHeight = 0.0;
            try
            {
                Pin(((FrameworkElement)win.Content).ActualHeight);
            }
            catch (Exception)
            {
            }
            if (Grips != null)
            {
                try
                {
                    Grips.Visibility = Visibility.Collapsed;
                }
                catch (Exception)
                {
                }
            }
            Shrunk = true;
            Glyphs(true);
            Slide(BarTop.Value, bar, ShrinkDone);
        }

        public void ShrinkDone()
        {
            Hidden = new List<UIElement>();
            foreach (UIElement el in Body())
            {
                try
                {
                    if (el.Visibility == Visibility.Visible)
                    {
                        el.Visibility = Visibility.Collapsed;
                        Hidden.Add(el);
                    }
                }
                catch (Exception)
                {
                }
            }
            Unpin();
            try
            {
                ((Border)Header).CornerRadius = new CornerRadius(6.0);
            }
            catch (Exception)
            {
            }
        }

        // ---- expand
        public void Expand()
        {
            if (!Shrunk || Moving) return;
            Window win = Win;
            double top0, h0, min0;
            SizeToContent? stc;
            if (saved != null)
            {
                top0 = saved.Top; h0 = saved.Height; min0 = saved.MinHeight; stc = saved.SizeToContent;
            }
            else
            {
                top0 = win.Top; h0 = 600.0; min0 = 0.0; stc = null;
            }
            Rect wa = WorkArea();
            double top = FhaCore.ExpandTop(top0, BarTop, win.Top, win.ActualHeight, h0, wa.Top, wa.Height);
            try
            {
                ((Border)Header).CornerRadius = new CornerRadius(6.0, 6.0, 0.0, 0.0);
            }
            catch (Exception)
            {
            }
            if (ShowBody != null)
            {
                ShowBody();
            }
            else
            {
                foreach (UIElement el in Hidden)
                {
                    try
                    {
                        el.Visibility = Visibility.Visible;
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            Hidden = new List<UIElement>();
            Pin(Math.Max(0.0, h0 - 12.0));
            Shrunk = false;
            Glyphs(false);
            if (Owner != null && ParkedOwner && Owner.Shrunk)
                Owner.Expand();       // bring the owner back with it (it is not activated)
            ParkedOwner = false;
            Slide(top, h0, () => ExpandDone(min0, stc));
        }

        public void ExpandDone(double minHeight, SizeToContent? sizeToContent = null)
        {
            Unpin();
            try
            {
                Win.MinHeight = minHeight;
            }
            catch (Exception)
            {
            }
            if (sizeToContent != null)
            {
                try
                {
                    Win.SizeToContent = sizeToContent.Value;
                }
                catch (Exception)
                {
                }
            }
            if (Grips != null)
            {
                try
                {
                    Grips.Visibility = Visibility.Visible;
                }
                catch (Exception)
                {
                }
            }
        }

        /// <summary>A dialog is closing: an owner it parked comes back.</summary>
        public void Closing()
        {
            if (Owner != null && ParkedOwner && Owner.Shrunk) Owner.Expand();
            ParkedOwner = false;
        }

        // ---- keys
        /// <summary>
        /// Ctrl+Shift+H toggles; while parked Escape, Enter and F11 open it again. True if the key was used.
        /// </summary>
        public bool Key(KeyEventArgs e)
        {
            System.Windows.Input.Key k;
            ModifierKeys mods;
            try
            {
                k = e.Key;
                mods = Keyboard.Modifiers;
            }
            catch (Exception)
            {
                return false;
            }
            if (k == System.Windows.Input.Key.H && (mods & ModifierKeys.Control) != 0 && (mods & ModifierKeys.Shift) != 0)
            {
                Toggle();
                return true;
            }
            if (Shrunk && (k == System.Windows.Input.Key.Escape || k == System.Windows.Input.Key.Return || k == System.Windows.Input.Key.F11))
            {
                Expand();
                return true;
            }
            return false;
        }
    }
}
