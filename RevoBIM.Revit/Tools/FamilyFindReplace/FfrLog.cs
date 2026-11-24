using System;
using System.IO;
using System.Text;

namespace RevoBIM.Tools.FamilyFindReplace
{
    /// <summary>
    /// The debug file (%AppData%\RevoBIM\FamilyFindReplace_debug.txt, the name the pyRevit tool used). Each time
    /// the window opens a new section starts with the tool version, the add-in build (version, build date, DLL
    /// path and write time) and the Revit version; after that come compact "prefix:" lines for each decision
    /// (window, index, pick, refresh, preview, run, adjust) and the drafting detail the pyRevit tool wrote. Past
    /// 2MB the file starts again. Never throws.
    /// </summary>
    public static class FfrLog
    {
        private const long MaxBytes = 2L * 1024 * 1024;
        private static readonly object Gate = new object();
        private static bool started;

        /// <summary>Starts a section for this window session.</summary>
        public static void Begin(string revitVersion, string document)
        {
            lock (Gate)
            {
                started = true;
                bool restart = false;
                try
                {
                    string path = FfrCore.DebugPath();
                    restart = File.Exists(path) && new FileInfo(path).Length > MaxBytes;
                }
                catch (Exception)
                {
                }
                Append(restart,
                    "=== Family Find & Replace " + FfrCore.Version + " (" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + ") ===",
                    "build: " + FfrCore.BuildInfo(),
                    "revit: " + revitVersion + " | document: " + document);
            }
        }

        /// <summary>One line, "prefix: text".</summary>
        public static void Write(string line)
        {
            lock (Gate)
            {
                if (!started) return;
                Append(false, DateTime.Now.ToString("HH:mm:ss.fff") + " " + line);
            }
        }

        /// <summary>Several lines at once, as the drafting run writes them.</summary>
        public static void WriteLines(System.Collections.Generic.IEnumerable<string> lines)
        {
            lock (Gate)
            {
                if (!started) return;
                Append(false, new System.Collections.Generic.List<string>(lines).ToArray());
            }
        }

        private static void Append(bool overwrite, params string[] lines)
        {
            try
            {
                Directory.CreateDirectory(FfrCore.SettingsDir());
                string text = string.Join("\r\n", lines) + "\r\n";
                if (overwrite) File.WriteAllText(FfrCore.DebugPath(), text, new UTF8Encoding(false));
                else File.AppendAllText(FfrCore.DebugPath(), text, new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }
    }
}
