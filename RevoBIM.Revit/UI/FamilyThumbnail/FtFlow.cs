using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Windows;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.FamilyThumbnail;

namespace RevoBIM.UI.FamilyThumbnail
{
    /// <summary>The three commands' flows: Update Current, Update Batch and Settings. Port of ft_commands.py and ft_boot.py.</summary>
    public static class FtFlow
    {
        private static string Describe(UIApplication uiapp)
        {
            try
            {
                UIDocument uidoc = uiapp.ActiveUIDocument;
                if (uidoc == null) return "none";
                return uidoc.Document.Title + (uidoc.Document.IsFamilyDocument ? " (family)" : " (project)");
            }
            catch (Exception)
            {
                return "?";
            }
        }

        private static void StartLog(UIApplication uiapp, string command)
        {
            string version = "?";
            try
            {
                version = uiapp.Application.VersionNumber;
            }
            catch (Exception)
            {
            }
            FtCore.BeginLog(command, version, Describe(uiapp));
        }

        /// <summary>Shows a failure and stores the same text, so a blank window is never the only symptom.</summary>
        public static void Report(string stage, Exception err)
        {
            string text = "Family Thumbnail failed at stage: " + stage + "\n\n" + err + "\n\nLog:\n" + string.Join("\n", FtCore.LogSnapshot());
            FtCore.Log("FAILED at " + stage + ": " + err);
            FtCore.FlushLog();
            try
            {
                Directory.CreateDirectory(FtCore.DataDir());
                File.WriteAllText(FtCore.ErrorPath(), text + "\n\n" + FtCore.BuildInfo(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
            try
            {
                new TaskDialog("RevoBIM Family Thumbnail")
                {
                    MainInstruction = "Family Thumbnail could not run (" + stage + ")",
                    MainContent = text.Length > 3000 ? text.Substring(0, 3000) : text,
                }.Show();
            }
            catch (Exception)
            {
            }
        }

        private static void Message(UIApplication uiapp, string heading, string message, string path = null, IList<string> notes = null,
            bool canOpen = false)
        {
            FtPromptWindow.ShowMessage(uiapp, heading, message, path, notes, canOpen, null);
        }

        // ---- Update Current ----------------------------------------------------------------------------

        public static void UpdateCurrent(UIApplication uiapp)
        {
            StartLog(uiapp, "Update Current");
            UIDocument uidoc = uiapp.ActiveUIDocument;
            if (uidoc == null || !uidoc.Document.IsFamilyDocument)
            {
                Message(uiapp, "Family Thumbnail", "Open a family in the Family Editor, then run Update Current.");
                return;
            }
            FtSettings s = FtSettings.Load();
            FtResult result = FtRevit.RunUpdate(uiapp, s);
            FtCore.Log("result ok=" + result.Ok + " path=" + result.Path + " view='" + result.ViewName + "' notes=" + string.Join("; ", result.Notes));
            FtCore.FlushLog();
            if (!result.Ok)
            {
                Message(uiapp, "Family Thumbnail", result.Message.Length > 0 ? result.Message : "The thumbnail was not made.", null, result.Notes);
                return;
            }
            if (result.Path == null) return; // Export Images is off: the view was updated and the tool finishes quietly
            if (s.PromptOpen)
            {
                string message = "Thumbnail saved for '" + result.Family + "'.";
                if (result.Override != null) message += "  Appearance override used: " + result.Override + ".";
                Message(uiapp, "Thumbnail saved", message, result.Path, result.Notes, true);
            }
        }

        // ---- Update Batch ------------------------------------------------------------------------------

        public static void UpdateBatch(UIApplication uiapp)
        {
            StartLog(uiapp, "Update Batch");
            UIDocument uidoc = uiapp.ActiveUIDocument;
            if (uidoc == null || uidoc.Document.IsFamilyDocument)
            {
                Message(uiapp, "Update Batch", "Open a project and run Update Batch. To update the family you are editing, use Update Current.");
                return;
            }
            string journalInfo;
            List<string> browserPaths = FtJournal.ReadBrowserSelection(uiapp.Application, out journalInfo);
            FtCore.Log(journalInfo);
            List<string> skipped;
            List<FtEntry> entries = FtBatch.CollectFamilies(uidoc.Document, uidoc, browserPaths, out skipped);
            if (entries.Count == 0)
            {
                Message(uiapp, "Update Batch", "This project has no editable loadable families.", null, skipped);
                return;
            }
            FtSettings s = FtSettings.Load();
            FtBatchWindow.Open(uiapp, uidoc, entries, skipped, s, owner => OpenSettings(uiapp, owner));
            FtCore.FlushLog();
        }

        // ---- Settings ----------------------------------------------------------------------------------

        public static void Settings(UIApplication uiapp)
        {
            StartLog(uiapp, "Settings");
            OpenSettings(uiapp, null);
            FtCore.FlushLog();
        }

        private static void OpenSettings(UIApplication uiapp, Window owner)
        {
            var categories = new List<string>();
            UIDocument uidoc = uiapp.ActiveUIDocument;
            if (uidoc != null) categories = FtRevit.CategoryNames(uidoc.Document);
            Autodesk.Revit.ApplicationServices.Application app = uiapp.Application;
            Func<string, KeyValuePair<List<string>, string>> loader = path =>
            {
                try
                {
                    string note;
                    List<string> names = FtRevit.SharedDefinitions(app, path, out note);
                    return new KeyValuePair<List<string>, string>(names, note);
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("settings.shared_loader", err);
                    return new KeyValuePair<List<string>, string>(new List<string>(), "The shared parameter file could not be read");
                }
            };
            FtSettingsWindow.Open(uiapp, categories, loader, owner);
        }
    }
}
