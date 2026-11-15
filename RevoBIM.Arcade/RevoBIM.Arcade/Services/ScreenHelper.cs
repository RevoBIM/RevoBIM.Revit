using System;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Media;

namespace RevoBIM.Arcade.Services
{
    /// <summary>Monitor work areas and owner-centred placement. WPF units are DIPs; Win32 is pixels.</summary>
    public static class ScreenHelper
    {
        [StructLayout(LayoutKind.Sequential)] struct POINT { public int X, Y; }
        [StructLayout(LayoutKind.Sequential)] struct RECT { public int Left, Top, Right, Bottom; }
        [StructLayout(LayoutKind.Sequential)]
        struct MONITORINFO { public int cbSize; public RECT rcMonitor; public RECT rcWork; public uint dwFlags; }

        [DllImport("user32.dll")] static extern IntPtr MonitorFromPoint(POINT pt, uint flags);
        [DllImport("user32.dll")] static extern IntPtr MonitorFromWindow(IntPtr hwnd, uint flags);
        [DllImport("user32.dll")] static extern bool GetMonitorInfo(IntPtr monitor, ref MONITORINFO info);

        const uint MonitorDefaultToNearest = 2;

        static Rect WorkOf(IntPtr monitor, double scaleX, double scaleY)
        {
            var mi = new MONITORINFO { cbSize = Marshal.SizeOf<MONITORINFO>() };
            if (monitor == IntPtr.Zero || !GetMonitorInfo(monitor, ref mi))
                return SystemParameters.WorkArea;
            var r = mi.rcWork;
            return new Rect(r.Left / scaleX, r.Top / scaleY, (r.Right - r.Left) / scaleX, (r.Bottom - r.Top) / scaleY);
        }

        /// <summary>The work area (screen minus taskbar) of the monitor the window is on, in DIPs.</summary>
        public static Rect WorkAreaOf(Window window)
        {
            var dpi = VisualTreeHelper.GetDpi(window);
            var hwnd = new System.Windows.Interop.WindowInteropHelper(window).Handle;
            return WorkOf(MonitorFromWindow(hwnd, MonitorDefaultToNearest), dpi.DpiScaleX, dpi.DpiScaleY);
        }

        /// <summary>
        /// Centre the window over the owner rectangle (screen pixels, as Revit reports its
        /// window), or on the primary work area when there is none. Clamped onto the monitor.
        /// Call from SourceInitialized, once Width and Height are set.
        /// </summary>
        public static void Place(Window window, (int X, int Y, int W, int H)? owner)
        {
            var dpi = VisualTreeHelper.GetDpi(window);
            double sx = dpi.DpiScaleX, sy = dpi.DpiScaleY;

            Rect area;
            double cx, cy;
            if (owner.HasValue)
            {
                var o = owner.Value;
                int px = o.X + o.W / 2, py = o.Y + o.H / 2;
                area = WorkOf(MonitorFromPoint(new POINT { X = px, Y = py }, MonitorDefaultToNearest), sx, sy);
                cx = px / sx; cy = py / sy;
            }
            else
            {
                area = SystemParameters.WorkArea;
                cx = area.Left + area.Width / 2; cy = area.Top + area.Height / 2;
            }

            double w = Math.Min(window.Width, area.Width), h = Math.Min(window.Height, area.Height);
            window.Width = w; window.Height = h;
            window.Left = Clamp(cx - w / 2, area.Left, area.Right - w);
            window.Top = Clamp(cy - h / 2, area.Top, area.Bottom - h);
        }

        public static double Clamp(double v, double lo, double hi) => hi < lo ? lo : Math.Max(lo, Math.Min(hi, v));
    }
}
