using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading;

namespace RevoBIM.Tools.ProSheets
{
    /// <summary>ps_export.py, continued: proving a file landed, finding where a driver put it, folders.</summary>
    public static partial class PsExport
    {
        // ======================================================================
        // os.path stand-ins (ntpath semantics: pure string work, never throws)
        // ======================================================================

        internal static readonly char[] Seps = { '\\', '/' };

        /// <summary>os.path.join(folder, name) for two parts.</summary>
        internal static string PathJoin(string folder, string name)
        {
            folder = folder ?? "";
            name = name ?? "";
            if (folder.Length == 0)
                return name;
            if (name.Length > 0 && (Seps.Contains(name[0]) || (name.Length > 1 && name[1] == ':')))
                return name;
            char last = folder[folder.Length - 1];
            if (last == '\\' || last == '/' || (folder.Length == 2 && last == ':'))
                return folder + name;
            return folder + "\\" + name;
        }

        internal static (string Drive, string Tail) SplitDrive(string path)
        {
            if (path.Length >= 2 && path[1] == ':')
                return (path.Substring(0, 2), path.Substring(2));
            if (path.Length >= 2 && Seps.Contains(path[0]) && Seps.Contains(path[1]))
            {
                // UNC: \\server\share
                int index = path.IndexOfAny(Seps, 2);
                if (index < 0)
                    return ("", path);
                int index2 = path.IndexOfAny(Seps, index + 1);
                if (index2 < 0)
                    index2 = path.Length;
                return (path.Substring(0, index2), path.Substring(index2));
            }
            return ("", path);
        }

        /// <summary>os.path.dirname.</summary>
        internal static string Dirname(string path)
        {
            if (string.IsNullOrEmpty(path))
                return "";
            var (drive, rest) = SplitDrive(path);
            int i = rest.Length;
            while (i > 0 && !Seps.Contains(rest[i - 1]))
                i--;
            string head = rest.Substring(0, i);
            string stripped = head.TrimEnd(Seps);
            return drive + (stripped.Length > 0 ? stripped : head);
        }

        /// <summary>os.path.basename.</summary>
        internal static string Basename(string path)
        {
            if (string.IsNullOrEmpty(path))
                return "";
            var (_, rest) = SplitDrive(path);
            int i = rest.Length;
            while (i > 0 && !Seps.Contains(rest[i - 1]))
                i--;
            return rest.Substring(i);
        }

        /// <summary>os.path.splitext(name)[0].</summary>
        internal static string SplitextStem(string name)
        {
            name = name ?? "";
            int dot = name.LastIndexOf('.');
            int sep = name.LastIndexOfAny(Seps);
            if (dot > sep)
            {
                // Leading dots are part of the name, not an extension.
                int start = sep + 1;
                while (start < dot && name[start] == '.')
                    start++;
                if (start < dot)
                    return name.Substring(0, dot);
            }
            return name;
        }

        /// <summary>os.listdir: entry names (files and folders). Throws as listdir does.</summary>
        internal static List<string> ListDir(string folder)
        {
            return Directory.GetFileSystemEntries(folder).Select(Basename).ToList();
        }

        // ======================================================================
        // proving a file landed
        // ======================================================================

        /// <summary>Every PDF already in a folder, as {path: size}. Never raises.</summary>
        public static Dictionary<string, long> FolderSnapshot(string folder)
        {
            var found = new Dictionary<string, long>(StringComparer.Ordinal);
            try
            {
                foreach (string entry in ListDir(folder))
                {
                    if (!entry.ToLowerInvariant().EndsWith(".pdf", StringComparison.Ordinal))
                        continue;
                    string full = PathJoin(folder, entry);
                    try
                    {
                        found[full] = File.Exists(full) ? new FileInfo(full).Length : 0;
                    }
                    catch (Exception)
                    {
                        found[full] = -1;
                    }
                }
            }
            catch (Exception)
            {
            }
            return found;
        }

        /// <summary>
        /// (jobs waiting, description) for a printer's Windows queue. -1 and the error
        /// when the queue could not be read.
        ///
        /// The one question the tool could not answer before: did the driver even get the
        /// job? A job still sitting in the queue means the driver has it and has not
        /// finished - a completely different problem from a driver that saved somewhere
        /// unexpected. Needs System.Printing.
        /// </summary>
        public static (int Waiting, string Status) QueueState(string printerName)
        {
            try
            {
                using (var server = new System.Printing.LocalPrintServer())
                using (var queue = server.GetPrintQueue(printerName))
                {
                    try
                    {
                        queue.Refresh();
                    }
                    catch (Exception)
                    {
                    }
                    int count = queue.NumberOfJobs;
                    string status;
                    try
                    {
                        status = string.Format(Inv, "{0}", queue.QueueStatus);
                    }
                    catch (Exception)
                    {
                        status = "";
                    }
                    return (count, status);
                }
            }
            catch (Exception err)
            {
                return (-1, Msg(err));
            }
        }

        /// <summary>PDFs that turned up in a folder since a snapshot was taken.</summary>
        internal static List<string> LateArrivals(string folder, Dictionary<string, long> before)
        {
            Dictionary<string, long> current;
            try
            {
                current = FolderSnapshot(folder);
            }
            catch (Exception)
            {
                return new List<string>();
            }
            return current.Keys.Where(path => !before.ContainsKey(path) && current[path] > 0).ToList();
        }

        /// <summary>
        /// How long to give a driver to write the file it was just sent. Scaled off the
        /// render, because a sheet that was slow to spool is a sheet that will be slow to
        /// convert, and floored high enough that a fast render followed by a slow driver is
        /// still caught.
        /// </summary>
        public static double DriverWaitBudget(double renderSeconds, double floor = 60.0, double ceiling = 420.0)
        {
            double scaled = renderSeconds * 6.0;
            if (double.IsNaN(scaled))
                scaled = 0.0;
            return Math.Max(floor, Math.Min(ceiling, scaled));
        }

        /// <summary>
        /// Wait for a PDF the driver has just written into a folder. Matched by "was not
        /// there before", not by name, because the driver names the file itself. A file
        /// that is there but still growing does not count - half a PDF is worse than none.
        /// Returns the path, or "".
        /// </summary>
        public static string WaitForNewPdf(string folder, Dictionary<string, long> before, double seconds = 60.0,
                                           double pause = 0.25, Func<bool> shouldStop = null)
        {
            var lastSize = new Dictionary<string, long>(StringComparer.Ordinal);
            int attempts = Math.Max(1, (int)(seconds / Math.Max(0.05, pause)));
            for (int attempt = 0; attempt < attempts; attempt++)
            {
                if (shouldStop != null)
                {
                    try
                    {
                        if (shouldStop())
                            break;
                    }
                    catch (Exception)
                    {
                    }
                }
                Dictionary<string, long> snapshot = FolderSnapshot(folder);
                foreach (string path in snapshot.Keys.Where(p => !before.ContainsKey(p)).ToList())
                {
                    long size = snapshot[path];
                    if (size > 0 && lastSize.TryGetValue(path, out long previous) && previous == size)
                        return path;
                    lastSize[path] = size;
                }
                Thread.Sleep(TimeSpan.FromSeconds(pause));
            }
            // One last look, in case it landed complete on the final tick.
            Dictionary<string, long> current = FolderSnapshot(folder);
            var fresh = current.Keys.Where(p => !before.ContainsKey(p) && current[p] > 0).ToList();
            if (fresh.Count == 1)
                return fresh[0];
            return "";
        }

        /// <summary>Move the driver's file to the name the naming rules asked for. (moved, final path or error).</summary>
        public static (bool Moved, string Detail) MoveIntoPlace(string source, string target, bool overwrite = true)
        {
            try
            {
                string folder = Dirname(target);
                var (made, error) = PsPaths.Ensure(folder);
                if (!made)
                    return (false, error);
                if (File.Exists(target) || Directory.Exists(target))
                {
                    if (!overwrite)
                        target = PsPaths.UniqueOnDisk(folder, SplitextStem(Basename(target)), ".pdf");
                    else
                        File.Delete(target);
                }
                File.Move(source, target);
                return (true, target);
            }
            catch (Exception)
            {
                // A rename will not always cross a drive, and the staging folder often is
                // on another one. Fall back to a copy and a delete.
                try
                {
                    File.Copy(source, target, true);
                    File.Delete(source);
                    return (true, target);
                }
                catch (Exception err)
                {
                    return (false, Msg(err));
                }
            }
        }

        // ======================================================================
        // finding where a driver actually put the files
        //
        // A driver that collects the job through its own port saves wherever its own
        // settings say, and the user has no particular reason to know where that is.
        // Asking them to go and find it is a poor answer when the tool can look.
        // ======================================================================

        /// <summary>The folders a PDF driver plausibly writes to, best guesses first.</summary>
        internal static List<string> CandidateRoots()
        {
            var roots = new List<string>();

            void Add(string path)
            {
                if (string.IsNullOrEmpty(path))
                    return;
                string full;
                try
                {
                    full = Path.GetFullPath(path).TrimEnd('\\');
                    if (full.EndsWith(":", StringComparison.Ordinal))
                        full += "\\";
                }
                catch (Exception)
                {
                    return;
                }
                if (Directory.Exists(full) && !roots.Contains(full))
                    roots.Add(full);
            }

            string Env(string name)
            {
                return Environment.GetEnvironmentVariable(name) ?? "";
            }

            string profile = Env("USERPROFILE");
            string onedrive = Env("OneDrive");
            if (onedrive.Length == 0)
                onedrive = Env("OneDriveConsumer");
            string appdata = Env("APPDATA");
            string local = Env("LOCALAPPDATA");
            string programdata = Env("ProgramData");

            // The folders a person would pick themselves.
            foreach (string baseDir in new[] { profile, onedrive, Env("OneDriveCommercial") })
            {
                foreach (string leaf in new[] { "Desktop", "Documents", "Downloads" })
                {
                    if (baseDir.Length > 0)
                        Add(PathJoin(baseDir, leaf));
                }
            }

            // The folders a PDF tool picks for itself. DiRoots is here because ProSheets
            // installs its own PDF24 instance and points it somewhere of its own.
            foreach (string baseDir in new[] { appdata, local, programdata })
            {
                if (baseDir.Length == 0)
                    continue;
                foreach (string vendor in new[] { "PDF24", "DiRoots", "DiRoots.ProSheets", "ProSheets" })
                    Add(PathJoin(baseDir, vendor));
            }

            Add(Env("TEMP"));
            Add(Env("TMP"));
            if (Env("PUBLIC").Length > 0)
                Add(PathJoin(Env("PUBLIC"), "Documents"));
            Add(profile);
            return roots;
        }

        // Folders never worth walking: enormous, and no PDF driver writes to them.
        public static readonly HashSet<string> SkipDirs = new HashSet<string>(StringComparer.Ordinal)
        {
            "windows", "winsxs", "program files", "program files (x86)",
            "programdata\\package cache", "$recycle.bin", "system volume information",
            "node_modules", ".git", "packages", "assembly", "installer",
            "inetcache", "webcache", "code cache", "gpucache", "cache2",
            "servicestate", "crashdumps", "d3dscache", "fontcache",
        };

        public const int MaxScanDirs = 5000;
        public const double MaxScanSeconds = 4.0;
        public const int MaxScanDepth = 6;

        internal static void PdfsNewerThan(string folder, DateTime cutoff, List<(DateTime Stamp, string Path)> into)
        {
            try
            {
                foreach (string entry in ListDir(folder))
                {
                    if (!entry.ToLowerInvariant().EndsWith(".pdf", StringComparison.Ordinal))
                        continue;
                    string full = PathJoin(folder, entry);
                    DateTime stamp;
                    try
                    {
                        if (!File.Exists(full) && !Directory.Exists(full))
                            continue;
                        stamp = File.GetLastWriteTimeUtc(full);
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                    if (stamp >= cutoff)
                        into.Add((stamp, full));
                }
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// Every PDF written in the last few minutes, newest first (at most 40).
        ///
        /// Two passes. The quick one looks in the folders a driver is most likely to use
        /// and usually answers on its own. Only if that finds nothing does the slow one walk
        /// the user's profile. The slow pass descends broadly but only reads a directory's
        /// contents when that directory's own timestamp is recent: creating a file updates
        /// the timestamp of the folder holding it and of no other. It is capped by directory
        /// count, depth and wall clock, because a diagnostic that hangs is worse than one
        /// that gives up.
        /// </summary>
        public static List<string> FindRecentPdfs(double seconds = 300)
        {
            DateTime cutoff;
            try
            {
                cutoff = DateTime.UtcNow.AddSeconds(-seconds);
            }
            catch (Exception)
            {
                return new List<string>();
            }

            List<string> roots = CandidateRoots();

            var quick = new List<(DateTime Stamp, string Path)>();
            foreach (string root in roots)
            {
                PdfsNewerThan(root, cutoff, quick);
                try
                {
                    foreach (string entry in ListDir(root))
                    {
                        string full = PathJoin(root, entry);
                        if (Directory.Exists(full))
                            PdfsNewerThan(full, cutoff, quick);
                    }
                }
                catch (Exception)
                {
                    continue;
                }
            }
            if (quick.Count > 0)
            {
                var sorted = quick.OrderByDescending(q => q.Stamp).ThenByDescending(q => q.Path, StringComparer.Ordinal).ToList();
                Debug(string.Format(Inv, "quick scan found {0} recent PDF(s)", quick.Count));
                return sorted.Take(40).Select(q => q.Path).ToList();
            }

            var found = new List<(DateTime Stamp, string Path)>();
            int visited = 0;
            var started = System.Diagnostics.Stopwatch.StartNew();
            var stack = roots.Select(root => (Folder: root, Depth: 0)).ToList();
            var seen = new HashSet<string>(StringComparer.Ordinal);
            while (stack.Count > 0)
            {
                if (visited >= MaxScanDirs || started.Elapsed.TotalSeconds > MaxScanSeconds)
                {
                    Debug(string.Format(Inv, "deep scan stopped at {0} folders", visited));
                    break;
                }
                var (folder, depth) = stack[stack.Count - 1];
                stack.RemoveAt(stack.Count - 1);
                string key = folder.ToLowerInvariant().Replace('/', '\\');
                if (seen.Contains(key))
                    continue;
                seen.Add(key);
                visited += 1;

                try
                {
                    if (Directory.Exists(folder) && Directory.GetLastWriteTimeUtc(folder) >= cutoff)
                        PdfsNewerThan(folder, cutoff, found);
                }
                catch (Exception)
                {
                }

                if (depth >= MaxScanDepth)
                    continue;
                try
                {
                    foreach (string entry in ListDir(folder))
                    {
                        string lowered = entry.ToLowerInvariant();
                        if (SkipDirs.Contains(lowered) || lowered.StartsWith("~", StringComparison.Ordinal))
                            continue;
                        string full = PathJoin(folder, entry);
                        try
                        {
                            if (Directory.Exists(full))
                                stack.Add((full, depth + 1));
                        }
                        catch (Exception)
                        {
                            continue;
                        }
                    }
                }
                catch (Exception)
                {
                    continue;
                }
            }

            var ordered = found.OrderByDescending(q => q.Stamp).ThenByDescending(q => q.Path, StringComparer.Ordinal).ToList();
            Debug(string.Format(Inv, "deep scan visited {0} folder(s), found {1} recent PDF(s)", visited, found.Count));
            return ordered.Take(40).Select(q => q.Path).ToList();
        }

        /// <summary>
        /// The single folder a driver most likely wrote to, or "". Where the recent PDFs are
        /// spread over several folders there is no honest single answer, so it gives none.
        /// </summary>
        public static string LikelyDriverFolder(double seconds = 300)
        {
            List<string> recent = FindRecentPdfs(seconds);
            var folders = new List<string>();
            foreach (string path in recent)
            {
                string folder = Dirname(path);
                if (!folders.Contains(folder))
                    folders.Add(folder);
            }
            if (folders.Count == 1)
                return folders[0];
            return "";
        }

        internal static bool RemoveIfPresent(string path)
        {
            try
            {
                if (File.Exists(path))
                {
                    File.Delete(path);
                    return true;
                }
            }
            catch (Exception)
            {
            }
            return false;
        }

        /// <summary>
        /// Wait briefly for a file to appear and stop growing. A PDF driver writes
        /// asynchronously, so checking immediately reports a failure for a file that lands a
        /// moment later. Equally, a file that exists is not necessarily finished - its size
        /// is checked twice before it counts.
        /// </summary>
        internal static bool WaitFor(string path, int attempts = 12, double pause = 0.25)
        {
            long lastSize = -1;
            for (int attempt = 0; attempt < attempts; attempt++)
            {
                try
                {
                    if (File.Exists(path))
                    {
                        long size = new FileInfo(path).Length;
                        if (size > 0 && size == lastSize)
                            return true;
                        lastSize = size;
                    }
                }
                catch (Exception)
                {
                }
                Thread.Sleep(TimeSpan.FromSeconds(pause));
            }
            try
            {
                return File.Exists(path) && new FileInfo(path).Length > 0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// Show a folder in Explorer, with a file picked out where there is one. /select
        /// opens the folder the file is actually in and highlights it, which lands you at the
        /// bottom of the subfolder tree rather than at the root.
        /// </summary>
        public static bool OpenFolder(string path, string selectFile = "")
        {
            try
            {
                if (!string.IsNullOrEmpty(selectFile) && File.Exists(selectFile))
                {
                    System.Diagnostics.Process.Start("explorer.exe", string.Format(Inv, "/select,\"{0}\"", selectFile));
                    return true;
                }
                if (!string.IsNullOrEmpty(path) && Directory.Exists(path))
                {
                    System.Diagnostics.Process.Start("explorer.exe", string.Format(Inv, "\"{0}\"", path));
                    return true;
                }
            }
            catch (Exception)
            {
            }
            return false;
        }

        /// <summary>The folder the files actually landed in, and one of the files.</summary>
        public static (string Folder, string File) DeepestWritten(Report report)
        {
            List<Outcome> written = report.Written();
            if (written.Count == 0)
                return ("", "");
            // The longest path is the deepest level of the subfolder tree, which is where
            // somebody pressing "Open folder" wants to be.
            Outcome best = written[0];
            foreach (Outcome outcome in written)
            {
                if ((outcome.Path ?? "").Length > (best.Path ?? "").Length)
                    best = outcome;
            }
            return (Dirname(best.Path), best.Path);
        }
    }
}
