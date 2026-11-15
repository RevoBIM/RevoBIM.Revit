using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using Autodesk.Revit.UI;
using RevoBIM.UI.ProSheets;

namespace RevoBIM.Helpers
{
    /// <summary>
    /// Starts RevoBIM.Arcade.exe. The arcade is its own Windows program, so it keeps running while a
    /// tool is busy and after Revit closes; Revit only launches it. One exe serves every Revit version.
    ///
    /// Launch contract: --theme light|dark, and the calling window's rectangle in screen pixels
    /// (--owner-x --owner-y --owner-w --owner-h) so the arcade opens centred over it. No --game is
    /// passed: the arcade opens the game the player starred as the default, or its picker.
    /// </summary>
    public static class ArcadeLauncher
    {
        public const string ExeName = "RevoBIM.Arcade.exe";

        /// <summary>
        /// The installer puts it in %AppData%\RevoBIM\ArcadeApp\, beside the per-version folders
        /// (%AppData%\RevoBIM\2024\RevoBIM.Revit.dll and so on). Null when it is not installed.
        /// </summary>
        public static string FindExe()
        {
            try
            {
                string dll = Assembly.GetExecutingAssembly().Location;
                string dir = string.IsNullOrEmpty(dll) ? null : Path.GetDirectoryName(dll);
                if (!string.IsNullOrEmpty(dir))
                {
                    string beside = Path.GetFullPath(Path.Combine(dir, "..", "ArcadeApp", ExeName));
                    if (File.Exists(beside)) return beside;
                }
            }
            catch (Exception)
            {
            }
            try
            {
                string appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
                string standard = Path.Combine(appData, "RevoBIM", "ArcadeApp", ExeName);
                if (File.Exists(standard)) return standard;
            }
            catch (Exception)
            {
            }
            return null;
        }

        /// <summary>The command line for a theme and an optional owner rectangle (screen pixels).</summary>
        public static string BuildArguments(string theme, int[] ownerRect)
        {
            string name = string.Equals(theme, "light", StringComparison.OrdinalIgnoreCase) ? "light" : "dark";
            string args = "--theme " + name;
            if (ownerRect != null && ownerRect.Length == 4 && ownerRect[2] > 0 && ownerRect[3] > 0)
            {
                args += string.Format(CultureInfo.InvariantCulture,
                    " --owner-x {0} --owner-y {1} --owner-w {2} --owner-h {3}",
                    ownerRect[0], ownerRect[1], ownerRect[2], ownerRect[3]);
            }
            return args;
        }

        /// <summary>
        /// Opens the arcade. theme is "light" or "dark" (null reads Revit's own); owner, when given, is
        /// the window it opens centred over. Returns false after telling the user why, when it cannot.
        /// </summary>
        public static bool Launch(Window owner = null, string theme = null)
        {
            string exe = FindExe();
            if (exe == null)
            {
                Tell("The RevoBIM Arcade is not installed.\n\nRun the RevoBIM Tools installer again; it adds the " +
                     "arcade (RevoBIM.Arcade.exe) next to the add-in.");
                return false;
            }
            try
            {
                var start = new ProcessStartInfo
                {
                    FileName = exe,
                    Arguments = BuildArguments(theme ?? PsTheme.DetectRevitTheme("dark"), OwnerRect(owner)),
                    WorkingDirectory = Path.GetDirectoryName(exe),
                    UseShellExecute = false,
                };
                Process.Start(start);
                return true;
            }
            catch (Exception err)
            {
                Tell("The RevoBIM Arcade could not start.\n\n" + err.Message);
                return false;
            }
        }

        private static void Tell(string text)
        {
            try
            {
                TaskDialog.Show("RevoBIM Arcade", text);
            }
            catch (Exception)
            {
                try
                {
                    MessageBox.Show(text, "RevoBIM Arcade");
                }
                catch (Exception)
                {
                }
            }
        }

        // ---------------------------------------------------------------- the owner window, in pixels

        [StructLayout(LayoutKind.Sequential)]
        private struct Rect
        {
            public int Left, Top, Right, Bottom;
        }

        [DllImport("user32.dll")]
        private static extern bool GetWindowRect(IntPtr window, out Rect rect);

        /// <summary>x, y, width, height of the window on screen in physical pixels, or null.</summary>
        private static int[] OwnerRect(Window owner)
        {
            try
            {
                if (owner == null) return null;
                IntPtr handle = new WindowInteropHelper(owner).Handle;
                if (handle == IntPtr.Zero) return null;
                Rect r;
                if (!GetWindowRect(handle, out r)) return null;
                return new[] { r.Left, r.Top, r.Right - r.Left, r.Bottom - r.Top };
            }
            catch (Exception)
            {
                return null;
            }
        }
    }
}
