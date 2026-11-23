using System;
using System.IO;
using System.Text;

namespace RevoBIM.Tools.FindInView
{
    /// <summary>
    /// The debug file (%AppData%\RevoBIM\find_in_view_debug.txt): one file per run, rewritten each time the
    /// tool starts. The first lines say which build is loaded (tool version, add-in build, DLL path and write
    /// time, Revit version), then compact "prefix:" lines for each decision, so one pasted log settles the
    /// next question. Never throws.
    /// </summary>
    public static class FivLog
    {
        private static readonly object Gate = new object();
        private static readonly StringBuilder Text = new StringBuilder();
        private static bool started;

        /// <summary>Starts a fresh log for this run.</summary>
        public static void Begin(string revitVersion, string document)
        {
            lock (Gate)
            {
                Text.Clear();
                started = true;
                Add("Find in View " + FivCore.Version + " (" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + ")");
                Add("build: " + FivCore.BuildInfo());
                Add("revit: " + revitVersion + " | document: " + document);
                Flush();
            }
        }

        /// <summary>One line, "prefix: text".</summary>
        public static void Write(string line)
        {
            lock (Gate)
            {
                if (!started) return;
                Add(DateTime.Now.ToString("HH:mm:ss.fff") + " " + line);
                Flush();
            }
        }

        private static void Add(string line)
        {
            Text.Append(line).Append("\r\n");
        }

        private static void Flush()
        {
            try
            {
                Directory.CreateDirectory(FivCore.SettingsDir());
                File.WriteAllText(FivCore.DebugPath(), Text.ToString(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }
    }
}
