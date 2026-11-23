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
        // ---- the Finish Selection card
        /// <summary>FhaFinish.Listener: the card is wanted (request) or gone (null). Guarded by the window's Dispatcher.</summary>
        private void OnFinishRequest(FinishRequest req)
        {
            try
            {
                Dispatcher d = Win.Dispatcher;
                if (!d.CheckAccess())
                {
                    d.Invoke(new Action(() => ApplyFinish(req)));
                    return;
                }
                ApplyFinish(req);
            }
            catch (Exception)
            {
            }
        }

        private void ApplyFinish(FinishRequest req)
        {
            finishReq = req;
            if (req != null)
            {
                C<TextBlock>("FinishEyebrow").Text = req.Eyebrow ?? "";
                C<TextBlock>("FinishTitle").Text = req.Title ?? "";
                C<TextBlock>("FinishDetail").Text = req.Detail ?? "";
                C<TextBlock>("FinishHint").Text = req.Hint ?? "";
            }
            ((UIElement)C("BtnFinish")).IsEnabled = req != null;   // not tied to SetBusy: the pick is part of the running job
            SyncFinish();
        }

        /// <summary>
        /// Bring the card and the window height in line with whether a pick is waiting. Shown only while the window is
        /// open and still (not parked, not sliding); the window grows by the card and shrinks back by the same amount.
        /// A card that came or went while the window was parked changes the height it will return to instead.
        /// </summary>
        private void SyncFinish()
        {
            try
            {
                var card = (FrameworkElement)C("FinishCard");
                FhaDrawer dr = Drawer;
                bool shrunk = dr != null && dr.Shrunk;
                bool moving = dr != null && dr.Moving;
                if (finishReq == null)
                {
                    card.Visibility = Visibility.Collapsed;
                    if (finishGrew != 0.0)
                    {
                        if (shrunk)
                        {
                            dr.AdjustSavedHeight(-finishGrew);
                            finishGrew = 0.0;
                            finishShift = 0.0;
                        }
                        else if (!moving)
                        {
                            ShrinkForFinish();
                        }
                    }
                    return;
                }
                if (shrunk || moving) return;   // parked: no card; it is shown when the window has landed
                if (card.Visibility != Visibility.Visible)
                {
                    card.Visibility = Visibility.Visible;
                    if (finishGrew == 0.0) GrowForFinish(card);
                }
            }
            catch (Exception)
            {
            }
        }

        private void GrowForFinish(FrameworkElement card)
        {
            Window win = Win;
            if (Chrome.Full || win.ActualHeight <= 0) return;
            double w = ((FrameworkElement)C("LogBox")).ActualWidth;   // the card has the log box's margins
            card.Measure(new Size(w + card.Margin.Left + card.Margin.Right, double.PositiveInfinity));
            double want = card.DesiredSize.Height;   // includes its margin
            Rect wa = Chrome.WorkArea();
            double h, top;
            FhaCore.FitHeight(win.ActualHeight, 0.0, want, win.MinHeight, win.Top, wa.Top, wa.Height * FhaUi.MaxScreen, out h, out top);
            double grew = h - win.ActualHeight;
            if (grew <= 0.5) return;   // no room: the tab scrolls instead
            finishGrew = grew;
            finishShift = win.Top - top;
            finishTop = top;
            if (Math.Abs(top - win.Top) > 0.5) win.Top = top;
            win.Height = h;
        }

        private void ShrinkForFinish()
        {
            double grew = finishGrew, shift = finishShift;
            finishGrew = 0.0;
            finishShift = 0.0;
            if (grew <= 0.0) return;
            Window win = Win;
            if (Chrome.Full)
            {
                Chrome.AdjustSavedHeight(-grew);
                return;
            }
            if (win.ActualHeight <= 0) return;
            double h = Math.Max(win.MinHeight, win.ActualHeight - grew);
            double top = win.Top;
            if (shift > 0.5 && Math.Abs(win.Top - finishTop) < 1.0)   // lifted to make room and not moved since: put it back where it was
            {
                Rect wa = Chrome.WorkArea();
                top = Math.Max(wa.Top, Math.Min(win.Top + shift, wa.Top + wa.Height - h));
            }
            win.Height = h;
            if (Math.Abs(top - win.Top) > 0.5) win.Top = top;
        }

        /// <summary>Finish Selection: once per pick, then it waits for the pick to end (the card goes with it).</summary>
        private void FinishClick(object sender, RoutedEventArgs e)
        {
            var btn = (UIElement)C("BtnFinish");
            try
            {
                if (!FhaFinish.Armed || FhaFinish.Pressed) return;
                btn.IsEnabled = false;
                if (!FhaFinish.Press() && FhaFinish.Armed && !FhaFinish.Pressed) btn.IsEnabled = true;   // it could not be started: try again
            }
            catch (Exception)
            {
                try
                {
                    if (FhaFinish.Armed && !FhaFinish.Pressed) btn.IsEnabled = true;
                }
                catch (Exception)
                {
                }
            }
        }
    }
}
