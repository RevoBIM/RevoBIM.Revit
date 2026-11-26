using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Autodesk.Revit.ApplicationServices;

namespace RevoBIM.Tools.FamilyThumbnail
{
    /// <summary>
    /// Reads the Project Browser selection from Revit's recording journal. Revit's API has no call for what is picked in the
    /// Project Browser, and the browser is a web view that Windows UI Automation cannot see (both checked on a live Revit
    /// 2024). The browser does write every pick to the journal as a path (see FtLogic.BrowserSelectionFromJournal), so the
    /// end of the journal is read. Port of ft_journal.py.
    /// </summary>
    public static class FtJournal
    {
        /// <summary>Read this much from the end, then more if no pick was found.</summary>
        private static readonly long[] TailSizes = { 1L << 20, 4L << 20, 16L << 20, 64L << 20 };

        private static string ReadTail(string path, long size, out bool whole)
        {
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            {
                long length = stream.Length;
                long start = Math.Max(0, length - size);
                stream.Seek(start, SeekOrigin.Begin);
                var buffer = new byte[length - start];
                int done = 0;
                while (done < buffer.Length)
                {
                    int got = stream.Read(buffer, done, buffer.Length - done);
                    if (got <= 0) break;
                    done += got;
                }
                whole = start == 0;
                return Encoding.UTF8.GetString(buffer, 0, done);
            }
        }

        /// <summary>
        /// The Project Browser's current selection as journal paths, and a one-line account of what was read (for the debug
        /// log). Never throws: no journal or no pick gives an empty list and the reason.
        /// </summary>
        public static List<string> ReadBrowserSelection(Application app, out string info)
        {
            string path;
            try
            {
                path = app.RecordingJournalFilename;
            }
            catch (Exception err)
            {
                FtCore.Swallowed("journal.path", err);
                info = "journal: Revit gave no journal file name";
                return new List<string>();
            }
            if (string.IsNullOrEmpty(path))
            {
                info = "journal: Revit gave no journal file name";
                return new List<string>();
            }
            try
            {
                foreach (long size in TailSizes)
                {
                    bool whole;
                    string text = ReadTail(path, size, out whole);
                    double when;
                    List<string> paths = FtLogic.BrowserSelectionFromJournal(text, out when);
                    if (paths.Count > 0)
                    {
                        string age = "";
                        if (when >= 0)
                            age = ", last line at " + ((int)(when / 3600)).ToString("00") + ":" + ((int)(when % 3600 / 60)).ToString("00") + ":" + ((int)(when % 60)).ToString("00");
                        info = "journal " + path + ": " + paths.Count + " browser pick(s)" + age;
                        return paths;
                    }
                    if (whole) break;
                }
                info = "journal " + path + ": no Project Browser pick found";
                return new List<string>();
            }
            catch (Exception err)
            {
                FtCore.Swallowed("journal.read", err);
                info = "journal: could not be read";
                return new List<string>();
            }
        }
    }
}
