// Port of ps_paths.py (Pro Sheets Exporter).
//
// Building the output folder from project and sheet parameters. No WPF and no
// Revit in here either - the token expansion is a plain function over a lookup.
//
// The user gives a root folder they browse to, plus a token string:
//
//     {Project Number}\{BGL_Sheet Discipline}\{Sheet Issue Date}
//
// Every {...} is looked up as a parameter on the sheet, falling back to the
// project information, and each resulting segment is sanitised as a folder name.
// A token with no value collapses to a placeholder rather than an empty folder
// level, because an empty level silently moves every file up a directory and
// nobody notices until a hundred PDFs are in the wrong place.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.ProSheets
{
    public static partial class PsPaths
    {
        public static readonly Regex Token = new Regex(@"\{([^{}]*)\}");

        public const string EmptyPlaceholder = "_unset";

        private static readonly Regex LevelSplit = new Regex(@"[\\/]+");

        // ==================================================================
        // date and time
        //
        // Two spellings, on purpose.
        //
        // The named ones - {Year}, {Month}, {Hour} - are what the picker inserts,
        // because they cannot be misread. The strftime ones are there for people who
        // already know them, and they follow strftime exactly: %m is the MONTH and %M
        // is the MINUTE. That trap is the whole reason the named tokens exist and the
        // whole reason the picker never offers the percent ones.
        // ==================================================================

        public static readonly List<(string Label, string Pattern, string Sample)> NamedTimeTokens =
            new List<(string Label, string Pattern, string Sample)>
            {
                ("Year", "%Y", "2026"),
                ("Year Short", "%y", "26"),
                ("Month", "%m", "09"),
                ("Month Name", "%B", "September"),
                ("Month Short", "%b", "Sep"),
                ("Day", "%d", "28"),
                ("Day Name", "%A", "Monday"),
                ("Hour", "%H", "14"),
                ("Minute", "%M", "05"),
                ("Second", "%S", "32"),
                ("Date", "%Y-%m-%d", "2026-09-28"),
                ("Time", "%H%M", "1405"),
                ("Date Time", "%Y-%m-%d %H%M", "2026-09-28 1405"),
                ("Week", "%W", "39"),
            };

        // The percent codes accepted in a token string, for anyone who reaches for
        // them out of habit. Everything here is plain strftime, with one addition:
        // %h is not a strftime code, but people type it meaning "hour", so it is
        // accepted as an alias for %H rather than left to pass through as literal
        // text and quietly land in a folder name.
        public static readonly HashSet<string> StrftimeCodes = new HashSet<string>(StringComparer.Ordinal)
        {
            "%Y", "%y", "%m", "%b", "%B", "%d", "%a", "%A",
            "%H", "%I", "%M", "%S", "%p", "%j", "%W",
        };

        public static readonly Dictionary<string, string> StrftimeAliases =
            new Dictionary<string, string>(StringComparer.Ordinal) { { "%h", "%H" } };

        internal static readonly Regex Strftime = new Regex("%[A-Za-z%]");

        /// <summary>The current local time (Python: datetime.datetime.now()).</summary>
        internal static DateTime? Now()
        {
            try
            {
                return DateTime.Now;
            }
            catch (Exception)
            {
                return null;
            }
        }

        internal static string FormatNow(string pattern)
        {
            DateTime? moment = Now();
            if (moment == null || string.IsNullOrEmpty(pattern))
                return "";
            try
            {
                return PyStrftime(moment.Value, pattern);
            }
            catch (Exception)
            {
                return "";
            }
        }

        /// <summary>
        /// Python's datetime.strftime for the codes this module uses, in the C locale
        /// (English day and month names). Any other %x is passed through as written.
        /// </summary>
        public static string PyStrftime(DateTime moment, string pattern)
        {
            var inv = CultureInfo.InvariantCulture;
            var output = new StringBuilder();
            for (int i = 0; i < pattern.Length; i++)
            {
                char ch = pattern[i];
                if (ch != '%' || i + 1 >= pattern.Length)
                {
                    output.Append(ch);
                    continue;
                }
                char code = pattern[++i];
                switch (code)
                {
                    case 'Y': output.Append(moment.Year.ToString("0000", inv)); break;
                    case 'y': output.Append((moment.Year % 100).ToString("00", inv)); break;
                    case 'm': output.Append(moment.Month.ToString("00", inv)); break;
                    case 'b': output.Append(moment.ToString("MMM", inv)); break;
                    case 'B': output.Append(moment.ToString("MMMM", inv)); break;
                    case 'd': output.Append(moment.Day.ToString("00", inv)); break;
                    case 'a': output.Append(moment.ToString("ddd", inv)); break;
                    case 'A': output.Append(moment.ToString("dddd", inv)); break;
                    case 'H': output.Append(moment.Hour.ToString("00", inv)); break;
                    case 'I':
                        {
                            int hour = moment.Hour % 12;
                            if (hour == 0)
                                hour = 12;
                            output.Append(hour.ToString("00", inv));
                            break;
                        }
                    case 'M': output.Append(moment.Minute.ToString("00", inv)); break;
                    case 'S': output.Append(moment.Second.ToString("00", inv)); break;
                    case 'p': output.Append(moment.Hour < 12 ? "AM" : "PM"); break;
                    case 'j': output.Append(moment.DayOfYear.ToString("000", inv)); break;
                    case 'W':
                        {
                            // Week of the year, Monday as the first day; days before
                            // the first Monday are week 0.
                            int yday = moment.DayOfYear - 1;
                            int mondayBased = ((int)moment.DayOfWeek + 6) % 7;
                            int week = (yday + 7 - mondayBased) / 7;
                            output.Append(week.ToString("00", inv));
                            break;
                        }
                    case '%': output.Append('%'); break;
                    default:
                        output.Append('%').Append(code);
                        break;
                }
            }
            return output.ToString();
        }

        /// <summary>The value for a named date or time token, or null if it is not one.</summary>
        public static string TimeToken(string name)
        {
            string wanted = (name ?? "").Trim().ToLowerInvariant();
            foreach (var entry in NamedTimeTokens)
            {
                if (entry.Label.ToLowerInvariant() == wanted)
                    return FormatNow(entry.Pattern);
            }
            return null;
        }

        /// <summary>
        /// Replace %Y, %m, %d, %H, %M, %S and friends before the {tokens} run.
        /// strftime's own meanings, so %m is the month and %M is the minute.
        /// That is the trap the named tokens exist to avoid, and it is not worth
        /// inventing a third convention here to soften it.
        /// </summary>
        public static string ExpandStrftime(string text)
        {
            string body = text ?? "";
            if (body.IndexOf('%') < 0)
                return body;
            return Strftime.Replace(body, match =>
            {
                string code = match.Value;
                if (code == "%%")
                    return "%";
                if (StrftimeAliases.TryGetValue(code, out string alias))
                    code = alias;
                if (!StrftimeCodes.Contains(code))
                    return match.Value;
                return FormatNow(code);
            });
        }

        /// <summary>
        /// Everything the folder picker offers: date and time first, then params.
        /// Date and time lead because they are the ones nobody can guess the
        /// spelling of, and because a parameter list is long enough to bury them.
        /// </summary>
        public static List<(string Name, string Group, string Sample)> TokenCatalogue(IEnumerable<(string Name, string Group)> parameterPairs)
        {
            var entries = new List<(string Name, string Group, string Sample)>();
            foreach (var entry in NamedTimeTokens)
                entries.Add((entry.Label, "Date and time", entry.Sample));
            foreach (var pair in parameterPairs ?? Enumerable.Empty<(string Name, string Group)>())
                entries.Add((pair.Name, pair.Group, ""));
            return entries;
        }

        /// <summary>Every token name appearing in a token string, in order, deduplicated.</summary>
        public static List<string> TokensIn(string text)
        {
            var found = new List<string>();
            foreach (Match match in Token.Matches(text ?? ""))
            {
                string name = match.Groups[1].Value.Trim();
                if (name.Length > 0 && !found.Contains(name))
                    found.Add(name);
            }
            return found;
        }

        /// <summary>
        /// Turn a token string into a relative path, one sanitised segment a level.
        /// Both \ and / count as level separators, since people type
        /// whichever they are used to. Empty levels are dropped; a level that exists
        /// but whose token resolved to nothing becomes the placeholder, so the depth
        /// of the tree never depends on whether a parameter happened to be filled in.
        /// </summary>
        public static string Expand(string tokenText, Func<string, string> lookup, string placeholder = EmptyPlaceholder)
        {
            string text = (tokenText ?? "").Trim();
            if (text.Length == 0)
                return "";

            text = ExpandStrftime(text);

            MatchEvaluator replace = match =>
            {
                string name = match.Groups[1].Value.Trim();
                if (name.Length == 0)
                    return "";
                string stamped = TimeToken(name);
                if (stamped != null)
                    return stamped;
                string value;
                try
                {
                    value = lookup(name);
                }
                catch (Exception)
                {
                    value = "";
                }
                return value == null ? "" : value.Trim();
            };

            string filled = Token.Replace(text, replace);
            string[] rawLevels = LevelSplit.Split(filled);
            var levels = new List<string>();
            foreach (string raw in rawLevels)
            {
                string level = raw.Trim();
                if (level.Length == 0)
                    continue;
                levels.Add(PsNaming.Sanitise(level, placeholder));
            }

            // A level that was nothing but an unresolved token comes back empty above
            // and is dropped, which would flatten the tree. Re-walk the original
            // levels so a level that was asked for always exists.
            var originalLevels = LevelSplit.Split(text).Where(lvl => lvl.Trim().Length > 0).ToList();
            if (levels.Count < originalLevels.Count)
            {
                levels = new List<string>();
                foreach (string original in originalLevels)
                {
                    string piece = Token.Replace(original, replace).Trim();
                    levels.Add(piece.Length > 0 ? PsNaming.Sanitise(piece, placeholder) : placeholder);
                }
            }
            return levels.Count > 0 ? OsPathJoin(levels.ToArray()) : "";
        }

        /// <summary>Root + expanded tokens + an optional per-format folder.</summary>
        public static string FullFolder(string root, string tokenText, Func<string, string> lookup, string formatFolder = null)
        {
            var parts = new List<string> { (root ?? "").Trim() };
            string relative = Expand(tokenText, lookup);
            if (relative.Length > 0)
                parts.Add(relative);
            if (!string.IsNullOrEmpty(formatFolder))
                parts.Add(PsNaming.Sanitise(formatFolder, "export"));
            parts = parts.Where(part => part.Length > 0).ToList();
            if (parts.Count == 0)
                return "";
            return OsPathNormPath(OsPathJoin(parts.ToArray()));
        }

        /// <summary>
        /// Whether a folder token is the sheet series: the parameter Setup names
        /// as the series, or anything called Sheet Series when Setup names none.
        /// </summary>
        public static bool IsSeriesToken(string name, string seriesParam)
        {
            name = (name ?? "").Trim().ToLowerInvariant();
            string wanted = (seriesParam ?? "").Trim().ToLowerInvariant();
            if (wanted.Length > 0)
                return name == wanted;
            return name.Contains("sheet series");
        }

        private static List<string> SplitLevels(string text)
        {
            return LevelSplit.Split(text ?? "").Where(part => part.Length > 0).ToList();
        }

        /// <summary>
        /// The folder a run's files sit under, cut off above the series level.
        /// {Date}\{BGL_Sheet Series}\PDF writes into one folder per series
        /// under the dated one, and the dated one is the issue - the folder
        /// somebody opening the export wants to land in. Taken from a folder the
        /// run actually built rather than by expanding the tokens again: a date
        /// or time token expanded a minute later is a different folder.
        /// "" when the folder levels have no series token, or the job's folder
        /// does not sit under the root - the caller falls back to the folder
        /// above the formats.
        /// </summary>
        public static string FolderBefore(string root, string tokenText, string jobFolder, string seriesParam)
        {
            var levels = LevelSplit.Split(tokenText ?? "").Where(level => level.Trim().Length > 0).ToList();
            int? cut = null;
            for (int index = 0; index < levels.Count; index++)
            {
                if (TokensIn(levels[index]).Any(name => IsSeriesToken(name, seriesParam)))
                {
                    cut = index;
                    break;
                }
            }
            if (cut == null)
                return "";
            var rootParts = SplitLevels((root ?? "").Trim());
            var jobParts = SplitLevels(jobFolder ?? "");
            if (rootParts.Count == 0 || jobParts.Count < rootParts.Count + cut.Value)
                return "";
            for (int i = 0; i < rootParts.Count; i++)
            {
                if (jobParts[i].ToLowerInvariant() != rootParts[i].ToLowerInvariant())
                    return "";
            }
            string text = jobFolder ?? "None";
            string separator = (text.Contains("\\") || !text.Contains("/")) ? "\\" : "/";
            var kept = jobParts.Take(rootParts.Count + cut.Value);
            string joined = string.Join(separator, kept);
            if (text.StartsWith("\\\\", StringComparison.Ordinal))
                joined = "\\\\" + joined;          // a UNC share keeps its two
            else if (text.StartsWith("/", StringComparison.Ordinal))
                joined = "/" + joined;
            return joined;
        }

        /// <summary>FolderBefore for the first of a run's folders that gives one.</summary>
        public static string IssueCut(string root, string tokenText, IEnumerable<string> folders, string seriesParam)
        {
            foreach (string folder in folders ?? Enumerable.Empty<string>())
            {
                string found = FolderBefore(root, tokenText, folder, seriesParam);
                if (!string.IsNullOrEmpty(found))
                    return found;
            }
            return "";
        }

        /// <summary>
        /// The folder the tokens name without any sheet: the register alone.
        /// With no sheets ticked there is no sheet to resolve the series or a
        /// discipline against, but the levels above them - project name, date and
        /// time - are the issue folder an Export run with sheets would have used.
        /// Levels are taken from the top down and the walk stops at the series
        /// level, or at the first level with a token the project cannot fill (a
        /// sheet parameter), so no _unset folder is ever made for the
        /// register to sit in.
        /// </summary>
        public static string ProjectFolder(string root, string tokenText, Func<string, string> lookup, string seriesParam)
        {
            root = (root ?? "").Trim();
            if (root.Length == 0)
                return "";
            var kept = new List<string>();
            foreach (string level in LevelSplit.Split(tokenText ?? ""))
            {
                if (level.Trim().Length == 0)
                    continue;
                List<string> names = TokensIn(level);
                if (names.Any(name => IsSeriesToken(name, seriesParam)))
                    break;
                bool resolvable = true;
                foreach (string name in names)
                {
                    if (TimeToken(name) != null)
                        continue;
                    string value;
                    try
                    {
                        value = lookup(name);
                    }
                    catch (Exception)
                    {
                        value = "";
                    }
                    if ((value ?? "").Trim().Length == 0)
                    {
                        resolvable = false;
                        break;
                    }
                }
                if (!resolvable)
                    break;
                string expanded = Expand(level, lookup);
                if (expanded.Length == 0)
                    break;
                kept.Add(expanded);
            }
            if (kept.Count == 0)
                return root;
            var all = new List<string> { root };
            all.AddRange(kept);
            return OsPathNormPath(OsPathJoin(all.ToArray()));
        }

        /// <summary>Create a folder if it is not there. (made, error_text).</summary>
        public static (bool Made, string Error) Ensure(string folder)
        {
            if (string.IsNullOrEmpty(folder))
                return (false, "no folder given");
            try
            {
                if (Directory.Exists(folder))
                    return (true, "");
                Directory.CreateDirectory(folder);
                return (true, "");
            }
            catch (Exception err)
            {
                return (false, err.Message);
            }
        }

        /// <summary>
        /// A folder path in a form two of them can be compared in.
        /// Separators squared up, trailing ones dropped, case folded. Not
        /// Path.GetFullPath: the comparison must not depend on the machine.
        /// </summary>
        public static string TidyFolder(string path)
        {
            string text = (path ?? "").Trim().Replace("/", "\\");
            while (text.Length > 3 && text.EndsWith("\\", StringComparison.Ordinal))
                text = text.Substring(0, text.Length - 1);
            return text.ToLowerInvariant();
        }

        /// <summary>Whether two paths name the same folder.</summary>
        public static bool SameFolder(string first, string second)
        {
            first = TidyFolder(first);
            return first.Length > 0 && first == TidyFolder(second);
        }

        /// <summary>Whether one folder sits under another, or is the same folder.</summary>
        public static bool InsideFolder(string inner, string outer)
        {
            inner = TidyFolder(inner);
            outer = TidyFolder(outer);
            if (inner.Length == 0 || outer.Length == 0)
                return false;
            return inner == outer || inner.StartsWith(outer.TrimEnd('\\') + "\\", StringComparison.Ordinal);
        }

        /// <summary>
        /// Whether a file can actually be written here, by trying it. (ok, error).
        /// Asking the file system about permissions is not the same question as
        /// asking whether this process can write, and a read-only network share
        /// answers the first one cheerfully.
        /// </summary>
        public static (bool Ok, string Error) Writable(string folder)
        {
            try
            {
                var (made, error) = Ensure(folder);
                if (!made)
                    return (false, error);
                string probe = OsPathJoin(folder, "_revobim_write_test.tmp");
                using (var handle = new FileStream(probe, FileMode.Create, FileAccess.Write))
                {
                    handle.WriteByte((byte)'x');
                }
                File.Delete(probe);
                return (true, "");
            }
            catch (Exception err)
            {
                return (false, err.Message);
            }
        }

        /// <summary>
        /// True where the finished path is close enough to 260 to be a problem.
        /// Revit and the print drivers do not all handle long paths, and the failure
        /// when they do not is a file that quietly does not appear.
        /// </summary>
        public static bool LongPathRisk(string path)
        {
            try
            {
                return (path ?? "None").Length >= 240;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>A path in this folder that nothing is using, adding (2), (3) if needed.</summary>
        public static string UniqueOnDisk(string folder, string baseName, string extension)
        {
            string candidate = OsPathJoin(folder, baseName + extension);
            if (!PathExists(candidate))
                return candidate;
            int index = 2;
            while (index < 1000)
            {
                candidate = OsPathJoin(folder, string.Format("{0} ({1}){2}", baseName, index, extension));
                if (!PathExists(candidate))
                    return candidate;
                index++;
            }
            return candidate;
        }

        // ==================================================================
        // Python os.path (ntpath, 2.7) equivalents, so joined and normalised
        // paths come out character for character as the pyRevit tool's do.
        // Path.Combine / GetFullPath differ (GetFullPath resolves against the
        // current directory), so they are not used for this.
        // ==================================================================

        /// <summary>Python os.path.exists: a file or a folder.</summary>
        public static bool PathExists(string path)
        {
            try
            {
                return !string.IsNullOrEmpty(path) && (File.Exists(path) || Directory.Exists(path));
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Python ntpath.splitdrive (2.7.8+, UNC aware).</summary>
        public static (string Drive, string Path) OsPathSplitDrive(string p)
        {
            p = p ?? "";
            if (p.Length > 1)
            {
                string normp = p.Replace('/', '\\');
                if (normp.StartsWith("\\\\", StringComparison.Ordinal) && (normp.Length < 3 || normp[2] != '\\'))
                {
                    // \\machine\mountpoint\directory\etc\...
                    int index = normp.IndexOf('\\', 2);
                    if (index == -1)
                        return ("", p);
                    int index2 = normp.IndexOf('\\', index + 1);
                    if (index2 == index + 1)
                        return ("", p);
                    if (index2 == -1)
                        index2 = p.Length;
                    return (p.Substring(0, index2), p.Substring(index2));
                }
                if (normp[1] == ':')
                    return (p.Substring(0, 2), p.Substring(2));
            }
            return ("", p);
        }

        /// <summary>Python ntpath.join (2.7.8+).</summary>
        public static string OsPathJoin(params string[] paths)
        {
            if (paths == null || paths.Length == 0)
                return "";
            var (resultDrive, resultPath) = OsPathSplitDrive(paths[0] ?? "");
            for (int i = 1; i < paths.Length; i++)
            {
                var (pDrive, pPath) = OsPathSplitDrive(paths[i] ?? "");
                if (pPath.Length > 0 && (pPath[0] == '\\' || pPath[0] == '/'))
                {
                    // Second path is absolute
                    if (pDrive.Length > 0 || resultDrive.Length == 0)
                        resultDrive = pDrive;
                    resultPath = pPath;
                    continue;
                }
                else if (pDrive.Length > 0 && pDrive != resultDrive)
                {
                    if (pDrive.ToLowerInvariant() != resultDrive.ToLowerInvariant())
                    {
                        // Different drives => ignore the first path entirely
                        resultDrive = pDrive;
                        resultPath = pPath;
                        continue;
                    }
                    // Same drive in different case
                    resultDrive = pDrive;
                }
                // Second path is relative to the first
                if (resultPath.Length > 0 && resultPath[resultPath.Length - 1] != '\\' && resultPath[resultPath.Length - 1] != '/')
                    resultPath = resultPath + "\\";
                resultPath = resultPath + pPath;
            }
            // add separator between UNC and non-absolute path
            if (resultPath.Length > 0 && resultPath[0] != '\\' && resultPath[0] != '/'
                && resultDrive.Length > 0 && !resultDrive.EndsWith(":", StringComparison.Ordinal))
                return resultDrive + "\\" + resultPath;
            return resultDrive + resultPath;
        }

        /// <summary>Python ntpath.normpath (2.7).</summary>
        public static string OsPathNormPath(string path)
        {
            path = path ?? "";
            const string backslash = "\\";
            if (path.StartsWith("\\\\.\\", StringComparison.Ordinal) || path.StartsWith("\\\\?\\", StringComparison.Ordinal))
            {
                // in the case of paths with these prefixes:
                // \\.\ -> device names
                // \\?\ -> literal paths
                // do not do any normalization, but return the path unchanged
                return path;
            }
            path = path.Replace("/", "\\");
            var (prefix, rest) = OsPathSplitDrive(path);
            path = rest;
            if (prefix.Length == 0)
            {
                // No drive letter - preserve initial backslashes
                while (path.StartsWith("\\", StringComparison.Ordinal))
                {
                    prefix = prefix + backslash;
                    path = path.Substring(1);
                }
            }
            else
            {
                // We have a drive letter - collapse initial backslashes
                if (path.StartsWith("\\", StringComparison.Ordinal))
                {
                    prefix = prefix + backslash;
                    path = path.TrimStart('\\');
                }
            }
            var comps = path.Split('\\').ToList();
            int i = 0;
            while (i < comps.Count)
            {
                if (comps[i] == "." || comps[i] == "")
                {
                    comps.RemoveAt(i);
                }
                else if (comps[i] == "..")
                {
                    if (i > 0 && comps[i - 1] != "..")
                    {
                        comps.RemoveRange(i - 1, 2);
                        i -= 1;
                    }
                    else if (i == 0 && prefix.EndsWith("\\", StringComparison.Ordinal))
                    {
                        comps.RemoveAt(i);
                    }
                    else
                    {
                        i += 1;
                    }
                }
                else
                {
                    i += 1;
                }
            }
            // If the path is now empty, substitute '.'
            if (prefix.Length == 0 && comps.Count == 0)
                comps.Add(".");
            return prefix + string.Join(backslash, comps);
        }

        /// <summary>Python os.path.splitext.</summary>
        public static (string Root, string Ext) OsPathSplitExt(string path)
        {
            path = path ?? "";
            int sepIndex = Math.Max(path.LastIndexOf('\\'), path.LastIndexOf('/'));
            int altsep = path.LastIndexOf(':');
            sepIndex = Math.Max(sepIndex, altsep);
            int dotIndex = path.LastIndexOf('.');
            if (dotIndex > sepIndex)
            {
                // skip all leading dots
                int filenameIndex = sepIndex + 1;
                while (filenameIndex < dotIndex)
                {
                    if (path[filenameIndex] != '.')
                        return (path.Substring(0, dotIndex), path.Substring(dotIndex));
                    filenameIndex++;
                }
            }
            return (path, "");
        }

        /// <summary>Python ntpath.basename.</summary>
        public static string OsPathBaseName(string path)
        {
            var (_, rest) = OsPathSplitDrive(path ?? "");
            int i = rest.Length;
            while (i > 0 && rest[i - 1] != '\\' && rest[i - 1] != '/')
                i--;
            return rest.Substring(i);
        }
    }
}
