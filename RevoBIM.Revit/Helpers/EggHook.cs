using System;
using System.Windows;
using System.Windows.Input;

namespace RevoBIM.Helpers
{
    /// <summary>
    /// The logo easter egg, on every tool window: three slow clicks on the RevoBIM logo in the top left
    /// open the RevoBIM Arcade (the game the player starred, or the picker). One counter per logo.
    ///
    /// Armed on the logo only, never the whole window. The click that completes the run is swallowed;
    /// every other click passes through, so the header still drags the window and buttons still work.
    /// A failure to arm or to launch is never allowed to stop the tool it sits in.
    /// </summary>
    public static class EggHook
    {
        /// <summary>
        /// Arms the egg on the given elements of a window (each its own logo or wordmark, sharing one
        /// count). theme is "light" or "dark", or a function returning one, so a tool whose theme can
        /// change while open hands over the palette in use at the moment of the click. Returns whether
        /// anything was armed.
        /// </summary>
        public static bool Attach(Window window, Func<string> theme, params UIElement[] logos)
        {
            if (window == null || logos == null) return false;
            var counter = new SlowClickCounter();
            bool armed = false;
            foreach (UIElement logo in logos)
            {
                if (logo == null) continue;
                try
                {
                    logo.PreviewMouseLeftButtonDown += (sender, args) => OnClick(window, theme, counter, args);
                    armed = true;
                }
                catch (Exception)
                {
                }
            }
            return armed;
        }

        private static void OnClick(Window window, Func<string> theme, SlowClickCounter counter, MouseButtonEventArgs args)
        {
            try
            {
                if (!counter.Click(args.Timestamp)) return;
                args.Handled = true;   // only the click that fires, so a drag from the logo still works
                string palette = null;
                try
                {
                    palette = theme == null ? null : theme();
                }
                catch (Exception)
                {
                }
                ArcadeLauncher.Launch(window, palette);
            }
            catch (Exception)
            {
            }
        }
    }
}
