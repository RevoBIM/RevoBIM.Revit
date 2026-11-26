using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.FamilyThumbnail
{
    /// <summary>
    /// The pure maths of Family Thumbnail, no Revit and no drawing: colours, revision numbers, view orientation, image
    /// content detection and crop, and the Project Browser pick read from Revit's journal. Port of ft_logic.py.
    /// </summary>
    public static class FtLogic
    {
        // ---- colours ----------------------------------------------------------------------------------

        /// <summary>'#RRGGBB' (or '#RGB') to its parts.</summary>
        public static bool ParseHex(string value, out int r, out int g, out int b)
        {
            r = g = b = 0;
            try
            {
                string text = (value ?? "").Trim().TrimStart('#');
                if (text.Length == 3) text = "" + text[0] + text[0] + text[1] + text[1] + text[2] + text[2];
                if (text.Length != 6) return false;
                r = int.Parse(text.Substring(0, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
                g = int.Parse(text.Substring(2, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
                b = int.Parse(text.Substring(4, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
                return true;
            }
            catch (FormatException)
            {
                return false;
            }
        }

        public static string ToHex(int r, int g, int b)
        {
            return "#" + r.ToString("X2") + g.ToString("X2") + b.ToString("X2");
        }

        public static string ScaleText(int scale) { return "1 : " + scale.ToString(CultureInfo.InvariantCulture); }

        public static int ParseScaleText(string text, int fallback)
        {
            try
            {
                string[] parts = (text ?? "").Split(':');
                return int.Parse(parts[parts.Length - 1].Trim(), CultureInfo.InvariantCulture);
            }
            catch (Exception)
            {
                return fallback;
            }
        }

        // ---- revision numbers -------------------------------------------------------------------------

        private static readonly Regex RevisionPattern =
            new Regex(@"^\s*[vVrR]?\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?\s*$", RegexOptions.Compiled);

        /// <summary>
        /// Standard MAJOR.MINOR.PATCH numbering. A blank or unreadable value starts at 1.0.0; otherwise the chosen part is
        /// raised by one and the parts after it reset ('1.4.2' + Minor gives '1.5.0'). A leading 'v' or 'R' and a missing
        /// minor or patch are accepted.
        /// </summary>
        public static string NextRevision(string current, string step)
        {
            Match m = RevisionPattern.Match(current ?? "");
            if (!m.Success) return "1.0.0";
            long major = long.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture);
            long minor = m.Groups[2].Success ? long.Parse(m.Groups[2].Value, CultureInfo.InvariantCulture) : 0;
            long patch = m.Groups[3].Success ? long.Parse(m.Groups[3].Value, CultureInfo.InvariantCulture) : 0;
            if (step == "Major") { major++; minor = 0; patch = 0; }
            else if (step == "Patch") patch++;
            else { minor++; patch = 0; }
            return major + "." + minor + "." + patch;
        }

        public static string DateText(int year, int month, int day)
        {
            return year.ToString("0000") + "-" + month.ToString("00") + "-" + day.ToString("00");
        }

        // ---- view orientation (Revit family space: front faces -Y, right is +X, up is +Z) -------------

        private static readonly Dictionary<string, double[]> IsoEye = new Dictionary<string, double[]>
        {
            { "3D View: Top, Front, Right", new[] { 1.0, -1.0, 1.0 } },
            { "3D View: Top, Front, Left", new[] { -1.0, -1.0, 1.0 } },
            { "3D View: Top, Back, Right", new[] { 1.0, 1.0, 1.0 } },
            { "3D View: Top, Back, Left", new[] { -1.0, 1.0, 1.0 } },
        };

        /// <summary>Flat views: forward, then up.</summary>
        private static readonly Dictionary<string, double[][]> Flat = new Dictionary<string, double[][]>
        {
            { "Top", new[] { new[] { 0.0, 0.0, -1.0 }, new[] { 0.0, 1.0, 0.0 } } },
            { "Front", new[] { new[] { 0.0, 1.0, 0.0 }, new[] { 0.0, 0.0, 1.0 } } },
            { "Back", new[] { new[] { 0.0, -1.0, 0.0 }, new[] { 0.0, 0.0, 1.0 } } },
            { "Left", new[] { new[] { 1.0, 0.0, 0.0 }, new[] { 0.0, 0.0, 1.0 } } },
            { "Right", new[] { new[] { -1.0, 0.0, 0.0 }, new[] { 0.0, 0.0, 1.0 } } },
        };

        private static double[] Unit(double x, double y, double z)
        {
            double n = Math.Sqrt(x * x + y * y + z * z);
            return new[] { x / n, y / n, z / n };
        }

        /// <summary>(forward, up) unit vectors for a View Type choice.</summary>
        public static void ViewVectors(string viewType, out double[] forward, out double[] up)
        {
            double[] eye;
            if (viewType != null && IsoEye.TryGetValue(viewType, out eye))
            {
                forward = Unit(-eye[0], -eye[1], -eye[2]);
                double d = forward[2];
                up = Unit(-d * forward[0], -d * forward[1], 1.0 - d * forward[2]);
                return;
            }
            double[][] flat;
            if (viewType != null && Flat.TryGetValue(viewType, out flat))
            {
                forward = flat[0];
                up = flat[1];
                return;
            }
            ViewVectors(FtCore.ViewTypes3D[0], out forward, out up);
        }

        public static double[] EyePosition(double[] forward, double distance)
        {
            return new[] { -forward[0] * distance, -forward[1] * distance, -forward[2] * distance };
        }

        // ---- image content detection (BGRA buffer of a small analysis copy) ----------------------------

        private static bool Close(byte[] buf, int off, int[] reference, int tol)
        {
            return Math.Abs(buf[off + 2] - reference[0]) <= tol
                   && Math.Abs(buf[off + 1] - reference[1]) <= tol
                   && Math.Abs(buf[off] - reference[2]) <= tol;
        }

        private static int[] Px(byte[] buf, int off) { return new int[] { buf[off + 2], buf[off + 1], buf[off] }; }

        private static bool CloseRgb(int[] a, int[] b, int tol)
        {
            return Math.Abs(a[0] - b[0]) <= tol && Math.Abs(a[1] - b[1]) <= tol && Math.Abs(a[2] - b[2]) <= tol;
        }

        /// <summary>
        /// The bounding box of everything that is not the background. A view background (plain or gradient) only changes from
        /// row to row, so each row's reference colour is taken from its left or right edge pixel, following the previous
        /// row when an edge pixel is covered by model content. Returns (x0, y0, x1, y1) inclusive, or null when the image
        /// is all background, with the per-row reference colours.
        /// </summary>
        public static int[] ContentBBox(byte[] buf, int w, int h, int stride, out List<int[]> refs, int tol)
        {
            refs = new List<int[]>();
            int[] prev = null;
            int x0 = w, y0 = h, x1 = -1, y1 = -1;
            for (int y = 0; y < h; y++)
            {
                int row = y * stride;
                int[] left = Px(buf, row);
                int[] right = Px(buf, row + (w - 1) * 4);
                int[] reference;
                if (prev == null) reference = left;
                else
                {
                    bool lc = CloseRgb(left, prev, tol * 2);
                    bool rc = CloseRgb(right, prev, tol * 2);
                    reference = lc ? left : (rc ? right : prev);
                }
                refs.Add(reference);
                prev = reference;
                int first = -1, last = -1;
                for (int x = 0; x < w; x++)
                {
                    if (!Close(buf, row + x * 4, reference, tol))
                    {
                        if (first < 0) first = x;
                        last = x;
                    }
                }
                if (first >= 0)
                {
                    x0 = Math.Min(x0, first);
                    x1 = Math.Max(x1, last);
                    y0 = Math.Min(y0, y);
                    y1 = Math.Max(y1, y);
                }
            }
            if (x1 < 0) return null;
            return new[] { x0, y0, x1, y1 };
        }

        public static void AnalysisSize(int w, int h, int longest, out int aw, out int ah)
        {
            if (w >= h)
            {
                aw = longest;
                ah = Math.Max(1, (int)Math.Round(longest * (double)h / w, MidpointRounding.AwayFromZero));
            }
            else
            {
                aw = Math.Max(1, (int)Math.Round(longest * (double)w / h, MidpointRounding.AwayFromZero));
                ah = longest;
            }
        }

        /// <summary>Maps an analysis-space box back to the full image, padded. Returns x, y, width, height.</summary>
        public static int[] CropRect(int[] bbox, int aw, int ah, int w, int h)
        {
            const double padFrac = 0.04;
            const double minPad = 2;
            if (bbox == null) return new[] { 0, 0, w, h };
            double sx = w / (double)aw;
            double sy = h / (double)ah;
            double x0 = bbox[0] * sx;
            double x1 = (bbox[2] + 1) * sx;
            double y0 = bbox[1] * sy;
            double y1 = (bbox[3] + 1) * sy;
            double pad = Math.Max(minPad, padFrac * Math.Max(x1 - x0, y1 - y0));
            int cx0 = Math.Max(0, (int)(x0 - pad));
            int cy0 = Math.Max(0, (int)(y0 - pad));
            int cx1 = Math.Min(w, (int)Math.Ceiling(x1 + pad));
            int cy1 = Math.Min(h, (int)Math.Ceiling(y1 + pad));
            return new[] { cx0, cy0, Math.Max(1, cx1 - cx0), Math.Max(1, cy1 - cy0) };
        }

        /// <summary>'Resize image to fit': the crop keeps its own aspect, long side = size.</summary>
        public static void ResizeDims(int cw, int ch, int size, out int ow, out int oh)
        {
            double scale = size / (double)Math.Max(cw, ch);
            ow = Math.Max(1, (int)Math.Round(cw * scale, MidpointRounding.AwayFromZero));
            oh = Math.Max(1, (int)Math.Round(ch * scale, MidpointRounding.AwayFromZero));
        }

        /// <summary>'Maintain 1:1': side of the square canvas (source pixels) that holds the crop with margin.</summary>
        public static int SquareSide(int cw, int ch)
        {
            return (int)Math.Ceiling(Math.Max(cw, ch) * (1.0 + 2.0 * 0.06));
        }

        /// <summary>Reference background colour for a source image row, from the analysis rows.</summary>
        public static int[] RowBackground(List<int[]> refs, int srcRow, int srcH)
        {
            if (refs == null || refs.Count == 0) return new[] { 255, 255, 255 };
            int index = (int)(srcRow * refs.Count / (double)srcH);
            return refs[Math.Max(0, Math.Min(refs.Count - 1, index))];
        }

        // ---- Project Browser selection, read from Revit's journal --------------------------------------
        //
        // Revit's API cannot report what is picked in the Project Browser, but the browser writes each pick to the journal as
        //   Jrn.Browser "SelChange" _ , ">>Families>>Category>>Family>>Type>>"
        // A shift or ctrl pick writes "SelChangeMultiple" (first item) followed at once by one "SelChange" for each further
        // item. A single click is a lone "SelChange".

        private const double JournalBurstGap = 0.3; // seconds between lines of one multiple pick

        private static readonly Regex JournalLine = new Regex(
            "^\\s*'[A-Z] \\d\\d-\\w{3}-\\d{4} (\\d\\d):(\\d\\d):(\\d\\d)\\.(\\d{3});"
            + "|Jrn\\.Browser\\s+\"(SelChangeMultiple|SelChange)\"\\s*_\\s*\\r?\\n\\s*,\\s*\"((?:[^\"]|\"\")*)\"",
            RegexOptions.Multiline | RegexOptions.Compiled);

        /// <summary>The Project Browser selection the journal text ends with (can be empty), and its last line's time as seconds of day (-1 when unknown).</summary>
        public static List<string> BrowserSelectionFromJournal(string text, out double lastTime)
        {
            double now = -1;
            var current = new List<string>();
            lastTime = -1;
            bool burst = false;
            foreach (Match match in JournalLine.Matches(text ?? ""))
            {
                if (!match.Groups[5].Success && match.Groups[1].Success)
                {
                    now = int.Parse(match.Groups[1].Value) * 3600 + int.Parse(match.Groups[2].Value) * 60
                          + int.Parse(match.Groups[3].Value) + int.Parse(match.Groups[4].Value) / 1000.0;
                    continue;
                }
                if (!match.Groups[6].Success) continue;
                string kind = match.Groups[5].Value;
                string path = match.Groups[6].Value.Replace("\"\"", "\"");
                bool joined = burst && lastTime >= 0 && now >= 0 && now - lastTime >= 0 && now - lastTime <= JournalBurstGap;
                if (kind == "SelChangeMultiple")
                {
                    current = new List<string> { path };
                    burst = true;
                }
                else if (joined) current.Add(path);
                else
                {
                    current = new List<string> { path };
                    burst = false;
                }
                lastTime = now;
            }
            return current;
        }

        public static List<string> PathParts(string path)
        {
            var parts = new List<string>();
            foreach (string part in (path ?? "").Split(new[] { ">>" }, StringSplitOptions.None))
                if (part.Trim().Length > 0) parts.Add(part);
            return parts;
        }

        /// <summary>
        /// Which families the Project Browser paths point at. families = (name, category) pairs. A path is
        /// &gt;&gt;Families&gt;&gt;Category&gt;&gt;Family&gt;&gt; or ...&gt;&gt;Family&gt;&gt;Type&gt;&gt; (a type counts as its family); a path ending
        /// at a category takes every family in it. Returns the pairs found as "name\nCategory" keys, and the number of
        /// paths that were not family paths.
        /// </summary>
        public static HashSet<string> FamiliesInBrowserPaths(IEnumerable<string> paths, IEnumerable<KeyValuePair<string, string>> families, out int other)
        {
            var pairs = new HashSet<string>();
            var categories = new HashSet<string>();
            var byName = new Dictionary<string, List<string>>();
            foreach (KeyValuePair<string, string> f in families)
            {
                pairs.Add(PairKey(f.Key, f.Value));
                categories.Add(f.Value);
                List<string> list;
                if (!byName.TryGetValue(f.Key, out list)) byName[f.Key] = list = new List<string>();
                if (!list.Contains(f.Value)) list.Add(f.Value);
            }
            var found = new HashSet<string>();
            other = 0;
            foreach (string path in paths)
            {
                List<string> parts = PathParts(path);
                bool hit = false;
                for (int index = 1; index < parts.Count; index++)
                {
                    string name = parts[index];
                    if (index >= 2 && pairs.Contains(PairKey(name, parts[index - 1])))
                    {
                        found.Add(PairKey(name, parts[index - 1]));
                        hit = true;
                        break;
                    }
                }
                List<string> cats;
                if (!hit && parts.Count >= 3 && byName.TryGetValue(parts[2], out cats))
                {
                    foreach (string category in cats) found.Add(PairKey(parts[2], category));
                    hit = true;
                }
                if (!hit && parts.Count == 2 && categories.Contains(parts[1]))
                {
                    foreach (KeyValuePair<string, string> f in families)
                        if (f.Value == parts[1]) found.Add(PairKey(f.Key, f.Value));
                    hit = true;
                }
                if (!hit) other++;
            }
            return found;
        }

        public static string PairKey(string name, string category) { return name + "\n" + category; }
    }
}
