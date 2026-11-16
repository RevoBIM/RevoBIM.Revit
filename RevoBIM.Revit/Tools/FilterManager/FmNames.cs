using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.FilterManager
{
    /// <summary>One row of the batch rename preview: what a filter is called, what it would be, and why not.</summary>
    public class FmRenameResult
    {
        public object Key;
        public string Old, New, Problem;
    }

    /// <summary>Renaming and duplicate naming. Port of fm_names.py.</summary>
    public static class FmNames
    {
        public const string ParkPrefix = "~RevoBIM rename ";

        /// <summary>Find and replace, then a prefix and a suffix, in that order.</summary>
        public static string Transform(string name, string find = "", string replace = "", bool matchCase = false,
                                       string prefix = "", string suffix = "")
        {
            string result = name ?? "";
            find = find ?? "";
            replace = replace ?? "";
            if (find.Length > 0)
            {
                if (matchCase) result = result.Replace(find, replace);
                else result = Regex.Replace(result, Regex.Escape(find), m => replace, RegexOptions.IgnoreCase);
            }
            return (prefix ?? "") + result + (suffix ?? "");
        }

        /// <summary>
        /// What every selected filter would be renamed to. rows = (key, current name); existing = every filter
        /// name in the project, the selected ones included. Nothing is written from here.
        /// </summary>
        public static List<FmRenameResult> Plan(IEnumerable<KeyValuePair<object, string>> rows, IEnumerable<string> existing,
                                                string find = "", string replace = "", bool matchCase = false,
                                                string prefix = "", string suffix = "")
        {
            var selected = rows.ToList();
            var selectedNames = new HashSet<string>(selected.Select(r => r.Value.ToLowerInvariant()));

            // what will still be called what once the selected ones have moved
            var remaining = new HashSet<string>();
            foreach (string name in existing)
                if (!selectedNames.Contains(name.ToLowerInvariant())) remaining.Add(name.ToLowerInvariant());

            // every new name is worked out first, then judged
            var proposed = selected.Select(r => Tuple.Create(r.Key, r.Value,
                Transform(r.Value, find, replace, matchCase, prefix, suffix))).ToList();

            var tally = new Dictionary<string, int>();
            foreach (var p in proposed)
            {
                string low = p.Item3.ToLowerInvariant();
                int n;
                tally.TryGetValue(low, out n);
                tally[low] = n + 1;
            }

            var results = new List<FmRenameResult>();
            foreach (var p in proposed)
            {
                string low = p.Item3.ToLowerInvariant();
                string problem;
                int count;
                tally.TryGetValue(low, out count);
                if (p.Item3.Trim().Length == 0) problem = "the name would be empty";
                else if (remaining.Contains(low)) problem = "a filter is already called that";
                else if (count > 1) problem = "two of the selected filters would end up the same";
                else if (p.Item3 == p.Item2) problem = "unchanged";
                else problem = "";
                results.Add(new FmRenameResult { Key = p.Item1, Old = p.Item2, New = p.Item3, Problem = problem });
            }
            return results;
        }

        /// <summary>The rows that would actually stop the batch.</summary>
        public static List<FmRenameResult> Blocking(IEnumerable<FmRenameResult> results)
        {
            return results.Where(r => !string.IsNullOrEmpty(r.Problem) && r.Problem != "unchanged").ToList();
        }

        /// <summary>The rows that would really be renamed.</summary>
        public static List<FmRenameResult> Changing(IEnumerable<FmRenameResult> results)
        {
            return results.Where(r => string.IsNullOrEmpty(r.Problem)).ToList();
        }

        /// <summary>'Name' to 'Name (1)', then (2), (3) ... until one is free.</summary>
        public static string DuplicateName(string baseName, IEnumerable<string> taken)
        {
            var lower = new HashSet<string>(taken.Select(t => t.ToLowerInvariant()));
            int index = 1;
            while (true)
            {
                string candidate = baseName + " (" + index + ")";
                if (!lower.Contains(candidate.ToLowerInvariant())) return candidate;
                index++;
            }
        }

        /// <summary>Names nothing else holds, to move through on the way to the real ones.</summary>
        public static List<string> ParkingNames(int count, IEnumerable<string> taken)
        {
            var lower = new HashSet<string>(taken.Select(t => t.ToLowerInvariant()));
            var output = new List<string>();
            int index = 1;
            while (output.Count < count)
            {
                string candidate = ParkPrefix + index;
                if (!lower.Contains(candidate.ToLowerInvariant()))
                {
                    output.Add(candidate);
                    lower.Add(candidate.ToLowerInvariant());
                }
                index++;
            }
            return output;
        }
    }
}
