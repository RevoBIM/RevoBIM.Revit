using System;
using System.IO;
using System.Reflection;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.Exceptions;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.BwicIdPush
{
    /// <summary>
    /// BWIC ID Push (port of the pyRevit tool, version 1.2.0). Click 1: a Generic Model element in a LINKED model, read its
    /// "CLM_BWIC ID". Click 2: an element in the HOST model, write the value into its "BGL_BWIC ID". Loops until Escape and ends
    /// silently: feedback for the previous pair rides in the status-bar prompt of the next pick. One TransactionGroup holds the
    /// whole run (one undo step); every pair still commits on its own.
    /// </summary>
    public static class BwicIdPushRun
    {
        public const string ToolVersion = "1.2.0";
        public const string SourceParam = "CLM_BWIC ID";
        public const string TargetParam = "BGL_BWIC ID";

        private static readonly long GenericModelId = (long)BuiltInCategory.OST_GenericModel;

        /// <summary>Runs the pick loop. Returns the number of pairs written.</summary>
        public static int Run(UIDocument uidoc)
        {
            Document doc = uidoc.Document;
            var filter = new LinkedGenericModelFilter(doc);
            var log = new StringBuilder();
            log.AppendLine("bwic_id_push " + ToolVersion + "  " + BuildInfo());
            string status = "";
            int committed = 0;

            using (var group = new TransactionGroup(doc, "BWIC ID Push"))
            {
                group.Start();
                try
                {
                    while (true)
                    {
                        Reference sourceRef = Pick(uidoc, status + "Pick the LINKED source (Esc to finish)", filter);
                        if (sourceRef == null) break;

                        Element source = filter.ResolveLinked(sourceRef);
                        if (source == null)
                        {
                            status = "Could not resolve that link. ";
                            log.AppendLine("pick: link not resolved");
                            continue;
                        }

                        string value = ReadParam(source, SourceParam);
                        if (string.IsNullOrEmpty(value))
                        {
                            status = SourceParam + " was empty. ";
                            log.AppendLine("pick: " + SourceParam + " empty on linked " + Id(source.Id));
                            continue;
                        }

                        Reference targetRef = Pick(uidoc,
                            "Pick the HOST element to receive \"" + value + "\" (Esc to finish)", null);
                        if (targetRef == null) break;

                        Element target = doc.GetElement(targetRef.ElementId);
                        if (target == null)
                        {
                            status = "Could not resolve that element. ";
                            log.AppendLine("pick: host element not resolved");
                            continue;
                        }

                        // Checked before opening a transaction, so a skip costs nothing.
                        Parameter param = target.LookupParameter(TargetParam);
                        if (param == null)
                        {
                            status = "No " + TargetParam + " on that element. ";
                            log.AppendLine("skip: no " + TargetParam + " on " + Id(target.Id));
                            continue;
                        }
                        if (param.IsReadOnly)
                        {
                            status = TargetParam + " is read-only there. ";
                            log.AppendLine("skip: read-only on " + Id(target.Id));
                            continue;
                        }

                        using (var t = new Transaction(doc, "Push BWIC ID"))
                        {
                            t.Start();
                            try
                            {
                                if (!param.Set(value)) throw new System.InvalidOperationException("Revit refused the value");
                                t.Commit();
                                committed++;
                                status = "Pushed \"" + value + "\". ";
                                log.AppendLine("push: \"" + value + "\" linked " + Id(source.Id) + " -> host " + Id(target.Id));
                            }
                            catch (Exception ex)
                            {
                                if (t.HasStarted()) t.RollBack();
                                status = "Write failed: " + ex.Message + ". ";
                                log.AppendLine("fail: host " + Id(target.Id) + ": " + ex.Message);
                            }
                        }
                    }
                }
                finally
                {
                    // Nothing written means nothing to keep on the undo stack.
                    if (committed > 0) group.Assimilate();
                    else group.RollBack();
                }
            }

            log.AppendLine("done: " + committed + " pushed");
            WriteLog(log.ToString());
            return committed;
        }

        private static Reference Pick(UIDocument uidoc, string prompt, ISelectionFilter filter)
        {
            try
            {
                return filter != null
                    ? uidoc.Selection.PickObject(ObjectType.LinkedElement, filter, prompt)
                    : uidoc.Selection.PickObject(ObjectType.Element, prompt);
            }
            catch (Autodesk.Revit.Exceptions.OperationCanceledException)
            {
                return null;
            }
        }

        /// <summary>Parameter value as text, or null when absent or empty.</summary>
        private static string ReadParam(Element element, string name)
        {
            Parameter p = element.LookupParameter(name);
            if (p == null || !p.HasValue) return null;
            return p.StorageType == StorageType.String ? p.AsString() : p.AsValueString();
        }

        private static string Id(ElementId id)
        {
            return id == null ? "-" : id.Value.ToString();
        }

        /// <summary>Restricts picking inside links to Generic Model elements. Link documents are cached: AllowReference
        /// fires on every mouse move.</summary>
        private sealed class LinkedGenericModelFilter : ISelectionFilter
        {
            private readonly Document _host;
            private readonly System.Collections.Generic.Dictionary<long, Document> _links =
                new System.Collections.Generic.Dictionary<long, Document>();

            public LinkedGenericModelFilter(Document host)
            {
                _host = host;
            }

            // Real filtering happens in AllowReference, once the linked element behind the reference can be resolved.
            public bool AllowElement(Element elem)
            {
                return elem is RevitLinkInstance;
            }

            private Document LinkDoc(ElementId linkId)
            {
                long key = linkId.Value;
                if (_links.TryGetValue(key, out Document cached)) return cached;
                Document linkDoc = (_host.GetElement(linkId) as RevitLinkInstance)?.GetLinkDocument();
                _links[key] = linkDoc;
                return linkDoc;
            }

            public bool AllowReference(Reference reference, XYZ position)
            {
                try
                {
                    Document linkDoc = LinkDoc(reference.ElementId);
                    Element linked = linkDoc?.GetElement(reference.LinkedElementId);
                    Category category = linked?.Category;
                    return category != null && category.Id.Value == GenericModelId;
                }
                catch (Exception)
                {
                    return false;
                }
            }

            public Element ResolveLinked(Reference reference)
            {
                Document linkDoc = LinkDoc(reference.ElementId);
                return linkDoc?.GetElement(reference.LinkedElementId);
            }
        }

        // ---- debug log ---------------------------------------------------------------------------------------------

        public static string DataDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }

        public static string LogPath() { return Path.Combine(DataDir(), "bwic_id_push_debug.txt"); }

        public static string ErrorPath() { return Path.Combine(DataDir(), "bwic_id_push_error.txt"); }

        /// <summary>Add-in version, build date, Revit version and DLL path: settles "is the newest build loaded?".</summary>
        public static string BuildInfo()
        {
            try
            {
                Assembly asm = Assembly.GetExecutingAssembly();
                string path = asm.Location;
                string written = File.Exists(path) ? File.GetLastWriteTime(path).ToString("yyyy-MM-dd HH:mm:ss") : "?";
                return "addin " + asm.GetName().Version + "  dll " + path + "  written " + written;
            }
            catch (Exception)
            {
                return "build info unavailable";
            }
        }

        private static void WriteLog(string text)
        {
            try
            {
                Directory.CreateDirectory(DataDir());
                File.WriteAllText(LogPath(), text, new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }
    }
}
