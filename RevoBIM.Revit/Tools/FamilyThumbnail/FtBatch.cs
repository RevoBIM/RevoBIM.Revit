using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.FamilyThumbnail
{
    /// <summary>One family offered in the Update Batch list.</summary>
    public sealed class FtEntry
    {
        public Family Family;
        public string Name = "";
        public string Category = "";
        public long Key;
        public bool Checked;
        public bool Preselected;
    }

    /// <summary>Loads the updated family over the one in the project without asking.</summary>
    internal sealed class FtLoadOptions : IFamilyLoadOptions
    {
        public bool OnFamilyFound(bool familyInUse, out bool overwriteParameterValues)
        {
            overwriteParameterValues = true;
            return true;
        }

        public bool OnSharedFamilyFound(Family sharedFamily, bool familyInUse, out FamilySource source, out bool overwriteParameterValues)
        {
            source = FamilySource.Family;
            overwriteParameterValues = true;
            return true;
        }
    }

    /// <summary>
    /// The Update Batch engine: picks the families from the selection, then for each one opens it in the background, gives it
    /// its thumbnail (and parameters), saves it and loads it back into the project. Port of ft_batch.py.
    /// </summary>
    public static class FtBatch
    {
        private static Family FamilyOf(Element element)
        {
            var family = element as Family;
            if (family != null) return family;
            var symbol = element as FamilySymbol;
            if (symbol != null) return symbol.Family;
            var instance = element as FamilyInstance;
            if (instance != null && instance.Symbol != null) return instance.Symbol.Family;
            return null;
        }

        /// <summary>
        /// Every editable, loadable family in the project, with the ones behind the current selection pre-ticked: family
        /// instances picked in a view, and whatever is picked in the Project Browser (passed in as journal paths, since
        /// Revit's API cannot report it).
        /// </summary>
        public static List<FtEntry> CollectFamilies(Document doc, UIDocument uidoc, List<string> browserPaths, out List<string> notes)
        {
            var selected = new HashSet<long>();
            notes = new List<string>();
            int other = 0;
            int selectedCount = 0;
            foreach (ElementId elementId in uidoc.Selection.GetElementIds())
            {
                selectedCount++;
                Family family = null;
                try
                {
                    family = FamilyOf(doc.GetElement(elementId));
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("collect_families.selection", err);
                }
                if (family == null) other++;
                else selected.Add(FtCore.Eid(family.Id));
            }
            FtCore.Log("selection: " + selectedCount + " element(s), " + selected.Count + " family(ies) behind them");

            var entries = new List<FtEntry>();
            var unavailable = new HashSet<string>();
            foreach (Family family in new FilteredElementCollector(doc).OfClass(typeof(Family)).Cast<Family>())
            {
                try
                {
                    long key = FtCore.Eid(family.Id);
                    if (family.IsInPlace || !family.IsEditable)
                    {
                        if (selected.Contains(key)) unavailable.Add(family.Name);
                        continue;
                    }
                    string category = family.FamilyCategory != null ? family.FamilyCategory.Name : "";
                    entries.Add(new FtEntry
                    {
                        Family = family,
                        Name = family.Name,
                        Category = category,
                        Key = key,
                        Checked = selected.Contains(key),
                        Preselected = selected.Contains(key),
                    });
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("collect_families.item", err);
                }
            }
            entries = entries.OrderBy(e => e.Category.ToLowerInvariant(), StringComparer.Ordinal)
                .ThenBy(e => e.Name.ToLowerInvariant(), StringComparer.Ordinal).ToList();

            if (browserPaths != null && browserPaths.Count > 0)
            {
                int otherPaths;
                HashSet<string> found = FtLogic.FamiliesInBrowserPaths(browserPaths,
                    entries.Select(e => new KeyValuePair<string, string>(e.Name, e.Category)), out otherPaths);
                other = otherPaths;
                int ticked = 0;
                foreach (FtEntry entry in entries)
                {
                    if (!found.Contains(FtLogic.PairKey(entry.Name, entry.Category))) continue;
                    entry.Checked = true;
                    entry.Preselected = true;
                    ticked++;
                }
                FtCore.Log("project browser pick: " + browserPaths.Count + " path(s), " + ticked + " family(ies) matched, "
                           + otherPaths + " path(s) not families");
                foreach (string path in browserPaths.Take(20)) FtCore.Log("  browser path: " + path);
                if (ticked > 0) notes.Add(ticked + " ticked from the Project Browser selection");
            }
            if (unavailable.Count > 0)
                notes.Add("Not offered (in-place or not editable): " + string.Join(", ", unavailable.OrderBy(n => n, StringComparer.Ordinal).ToArray()));
            if (other > 0) notes.Add(other + " selected item(s) are not families");
            return entries;
        }

        private static Family FindFamily(Document doc, string name)
        {
            foreach (Family family in new FilteredElementCollector(doc).OfClass(typeof(Family)).Cast<Family>())
                if (family.Name == name) return family;
            return null;
        }

        /// <summary>Saves the updated family as export folder [\Category] \ family.rfa. A failure is a note, not a stop: the family still loads back.</summary>
        private static string SaveFamily(Document famDoc, FtSettings s, string category, string familyName, List<string> notes)
        {
            try
            {
                string folder = FtCore.OutputFolder(s, category);
                Directory.CreateDirectory(folder);
                string path = Path.Combine(folder, familyName + ".rfa");
                famDoc.SaveAs(path, new SaveAsOptions { OverwriteExistingFile = true });
                return path;
            }
            catch (Exception err)
            {
                FtCore.Swallowed("save_family", err);
                notes.Add("family file could not be saved");
                return null;
            }
        }

        /// <summary>Opens the family in the background, updates it, saves it and loads it back.</summary>
        public static FtResult ProcessFamily(Document doc, Family family, FtSettings s)
        {
            var result = new FtResult();
            Document famDoc = null;
            try
            {
                famDoc = doc.EditFamily(family);
                FtResult update = FtRevit.UpdateDocument(famDoc, null, s);
                result.Notes = update.Notes;
                result.Path = update.Path;
                result.Family = update.Family;
                result.Category = update.Category;
                if (!update.Ok)
                {
                    result.Message = update.Message.Length > 0 ? update.Message : "The thumbnail was not made.";
                    return result;
                }
                result.Rfa = SaveFamily(famDoc, s, update.Category, update.Family, result.Notes);
                Family loaded = famDoc.LoadFamily(doc, new FtLoadOptions());
                if (loaded == null) loaded = FindFamily(doc, family.Name);
                FtRevit.ApplyToLoadedFamily(doc, loaded, update.Applied, result.Notes);
                result.Ok = true;
            }
            catch (Exception err)
            {
                FtCore.Swallowed("process_family", err);
                result.Message = err.Message;
                FtCore.Log("process_family error: " + err);
            }
            finally
            {
                if (famDoc != null)
                {
                    try
                    {
                        famDoc.Close(false);
                    }
                    catch (Exception err)
                    {
                        FtCore.Swallowed("process_family.close", err);
                    }
                }
            }
            return result;
        }
    }
}
