using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;
using RevoBIM.Tools.BwicPenetration;

namespace RevoBIM.UI.BwicPenetration
{
    /// <summary>The controls one prompt card is drawn into. The docked card in the tool window and the floating one over Revit share them.</summary>
    internal sealed class PromptParts
    {
        public Border Card, AccentBd, HintBd;
        public TextBlock EyebrowTb, DotsTb, IconTb, TitleTb, DetailTb, HintTb;
    }

    /// <summary>What the main window offers the step prompt.</summary>
    internal interface IPromptHost
    {
        Window Win { get; }
        Drawer Drawer { get; }
        void ShowDockedPrompt(PromptLook look);
        void HideDockedPrompt();
    }

    internal static class BwiPrompts
    {
        /// <summary>Fill a prompt card from a look (see BwicPrompt). find gives a brush resource by name.</summary>
        public static void DrawCard(PromptParts parts, Func<string, object> find, PromptLook look)
        {
            var brush = (Brush)find(look.Accent == "green" ? "Green" : look.Accent == "orange" ? "Orange" : "Blue");
            parts.AccentBd.Background = brush;
            parts.EyebrowTb.Foreground = brush;
            parts.EyebrowTb.Text = look.Eyebrow ?? "";
            parts.DotsTb.Text = PromptState.Dots(look);
            parts.TitleTb.Text = look.Title ?? "";
            parts.TitleTb.Visibility = string.IsNullOrEmpty(look.Title) ? Visibility.Collapsed : Visibility.Visible;
            parts.DetailTb.Text = look.Detail ?? "";
            parts.DetailTb.Visibility = string.IsNullOrEmpty(look.Detail) ? Visibility.Collapsed : Visibility.Visible;
            string icon = look.Kind == "placed" ? "✓" : look.Kind == "problem" ? "!" : "";
            parts.IconTb.Text = icon;
            parts.IconTb.Foreground = brush;
            parts.IconTb.Visibility = icon.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
            string hint = PromptState.HintText(look);
            parts.HintTb.Text = hint;
            parts.HintBd.Visibility = hint.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        }
    }

    /// <summary>
    /// Says what to pick next while a manual placement runs. The card is docked at the bottom of the tool window; while that is parked
    /// on the taskbar the same card floats over Revit instead. What it shows, and for how long, is decided by <see cref="PromptState"/>.
    /// Nothing here takes focus - the tool window taking focus is what once stopped Return finishing a selection.
    /// </summary>
    internal sealed class StepPrompt
    {
        private readonly IPromptHost _tool;
        public readonly PromptState State = new PromptState();
        private DispatcherTimer _timer;
        private EventHandler _tickHandler;
        private FloatingPrompt _floating;

        public StepPrompt(IPromptHost tool) { _tool = tool; }

        /// <summary>Events from the run: step, placed, problem, note, blocked, done.</summary>
        public void Handle(string evt, Dictionary<string, object> details)
        {
            if (evt == "step") Apply(State.Step(details));
            else if (evt == "placed" || evt == "problem" || evt == "note" || evt == "blocked") Apply(State.Flash(evt, details));
            else if (evt == "done") Apply(State.Done());
        }

        private void Apply(PromptAction result)
        {
            if (result == null) return;
            if (result.Action == "hide")
            {
                StopTimer();
                HideAll();
                return;
            }
            Show(result.Look);
            if (result.Look.Seconds != null) StartTimer(result.Look.Seconds.Value);
            Flush();
        }

        private bool Parked()
        {
            if (_tool.Drawer != null && _tool.Drawer.Heading == "parked") return true;
            try { return !_tool.Win.IsVisible; }
            catch (Exception) { return false; }
        }

        private void Show(PromptLook look)
        {
            if (Parked())
            {
                _tool.HideDockedPrompt();
                if (_floating == null) _floating = new FloatingPrompt(_tool.Win);
                _floating.Present(look);
            }
            else
            {
                if (_floating != null) _floating.Conceal();
                _tool.ShowDockedPrompt(look);
            }
        }

        /// <summary>The tool window was parked or opened: move the card across.</summary>
        public void Refresh()
        {
            if (State.Visible && State.Current != null) Show(State.Current);
        }

        private void HideAll()
        {
            try { _tool.HideDockedPrompt(); } catch (Exception) { }
            if (_floating != null) _floating.Conceal();
        }

        private void StartTimer(double seconds)
        {
            StopTimer();
            _timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(seconds) };
            _tickHandler = FlashOver;
            _timer.Tick += _tickHandler;
            _timer.Start();
        }

        private void StopTimer()
        {
            if (_timer != null)
            {
                try
                {
                    _timer.Stop();
                    if (_tickHandler != null) _timer.Tick -= _tickHandler;
                }
                catch (Exception) { }
            }
            _timer = null;
            _tickHandler = null;
        }

        private void FlashOver(object sender, EventArgs args)
        {
            StopTimer();
            Apply(State.FlashOver());
        }

        /// <summary>Draw now: the next pick starts straight after this, and the card has to be on screen before Revit starts waiting.</summary>
        private void Flush()
        {
            try { _tool.Win.Dispatcher.Invoke(new Action(() => { }), DispatcherPriority.Render); }
            catch (Exception) { }
        }

        public void Shut()
        {
            StopTimer();
            State.Reset();
            HideAll();
            if (_floating != null)
            {
                _floating.Shut();
                _floating = null;
            }
        }
    }

    /// <summary>The step card over Revit, for while the tool window is parked: click-through, never activated.</summary>
    internal sealed class FloatingPrompt : BwiWindowBase
    {
        private const int WS_EX_TRANSPARENT = 0x20, WS_EX_TOOLWINDOW = 0x80, WS_EX_NOACTIVATE = 0x08000000, GWL_EXSTYLE = -20;

        [DllImport("user32.dll", EntryPoint = "GetWindowLongW")] private static extern int GetWindowLong(IntPtr hwnd, int index);
        [DllImport("user32.dll", EntryPoint = "SetWindowLongW")] private static extern int SetWindowLong(IntPtr hwnd, int index, int value);

        private readonly Window _tool;
        private readonly PromptParts _parts;

        public FloatingPrompt(Window tool)
        {
            _tool = tool;
            Win = BwiUi.Load("prompt.xaml", new Dictionary<string, Action<object, RoutedEventArgs>>());
            _parts = new PromptParts
            {
                AccentBd = Find<Border>("accent_bd"), EyebrowTb = Find<TextBlock>("eyebrow_tb"), DotsTb = Find<TextBlock>("dots_tb"),
                IconTb = Find<TextBlock>("icon_tb"), TitleTb = Find<TextBlock>("title_tb"), DetailTb = Find<TextBlock>("detail_tb"),
                HintBd = Find<Border>("hint_bd"), HintTb = Find<TextBlock>("hint_tb"),
            };
            Win.SourceInitialized += (s, e) => MakeClickThrough();
        }

        public void Present(PromptLook look)
        {
            BwiPrompts.DrawCard(_parts, Win.FindResource, look);
            Position();
            try { if (!Win.IsVisible) Win.Show(); } catch (Exception) { }
        }

        public void Conceal()
        {
            try { Win.Hide(); } catch (Exception) { }
        }

        /// <summary>Top centre of the Revit window, below the ribbon and Options Bar, clear of Finish.</summary>
        private void Position()
        {
            double scale = BwiUi.DpiScale(_tool), left, top;
            try
            {
                var ext = BwicCore.CurrentApp.MainWindowExtents;
                left = (ext.Left + ext.Right) / 2.0 / scale - Win.Width / 2.0;
                top = ext.Top / scale + 170.0;
            }
            catch (Exception)
            {
                scale = 1.0;
                double[] a = BwiUi.WorkingArea(scale);
                left = a[0] + (a[2] - Win.Width) / 2.0;
                top = a[1] + 170.0;
            }
            double[] area = BwiUi.WorkingArea(scale);
            Win.Left = Math.Min(Math.Max(left, area[0]), area[0] + area[2] - Win.Width);
            Win.Top = Math.Max(top, area[1]);
        }

        private void MakeClickThrough()
        {
            try
            {
                IntPtr hwnd = new WindowInteropHelper(Win).Handle;
                int style = GetWindowLong(hwnd, GWL_EXSTYLE);
                SetWindowLong(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE);
            }
            catch (Exception err)
            {
                BwicCore.DebugLog("prompt could not be made click-through: " + err.Message);
            }
        }

        public void Shut()
        {
            try { Win.Close(); } catch (Exception) { }
        }
    }
}
