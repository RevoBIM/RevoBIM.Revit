using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.ProSheets
{
    /// <summary>The Revit side of ps_revisions: reading the project's revisions, the RevitApi that
    /// Execute writes through, and the Document Register's assign / change / remove on sheets.</summary>
    public static partial class PsRevisions
    {
        // ==========================================================================
        // Revit
        // ==========================================================================

        /// <summary>An ElementId from a key (ps_revisions._id; Revit 2024 has ElementId(Int64)).</summary>
        internal static ElementId Id(long value)
        {
            return new ElementId(value);
        }

        /// <summary>An ElementId from a text key - int(value) in the Python, so it throws on bad text.</summary>
        internal static ElementId Id(string value)
        {
            return new ElementId(long.Parse((value ?? "").Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture));
        }

        /// <summary>A List&lt;ElementId&gt;, which is what SetAdditionalRevisionIds takes.</summary>
        internal static List<ElementId> IdList(IEnumerable<string> keys)
        {
            return keys.Select(key => Id(key)).ToList();
        }

        internal static List<ElementId> IdList(IEnumerable<long> keys)
        {
            return keys.Select(key => Id(key)).ToList();
        }

        /// <summary>A revision's text property, trimmed, "" when it cannot be read (ps_revisions._text,
        /// which read the property by name with getattr).</summary>
        internal static string Text(Revision element, string name)
        {
            try
            {
                string value;
                switch (name)
                {
                    case "RevisionDate": value = element.RevisionDate; break;
                    case "Description": value = element.Description; break;
                    case "IssuedTo": value = element.IssuedTo; break;
                    case "IssuedBy": value = element.IssuedBy; break;
                    default: value = ""; break;
                }
                return (value ?? "").Trim();
            }
            catch (Exception)
            {
                return "";
            }
        }

        /// <summary>{element key: name} of the numbering sequences, and the names in Revit's order.</summary>
        public static (Dictionary<long, string> ByKey, List<string> Names) SequenceNames(Document doc)
        {
            var byKey = new Dictionary<long, string>();
            var names = new List<string>();
            List<ElementId> ids;
            try
            {
                ids = RevisionNumberingSequence.GetAllRevisionNumberingSequences(doc).ToList();
            }
            catch (Exception)
            {
                ids = new List<ElementId>();
            }
            foreach (var sequenceId in ids)
            {
                string name;
                try
                {
                    name = doc.GetElement(sequenceId).Name ?? "";
                }
                catch (Exception)
                {
                    continue;
                }
                byKey[PsModel.EidValue(sequenceId)] = name;
                names.Add(name);
            }
            return (byKey, names);
        }

        /// <summary>The sheet number when <paramref name="view"/> is a sheet, else null. Only a ViewSheet
        /// has a SheetNumber.</summary>
        public static string SheetNumberOf(View view)
        {
            if (!(view is ViewSheet sheet))
                return null;
            string text;
            try
            {
                text = sheet.SheetNumber ?? "";
            }
            catch (Exception)
            {
                return null;
            }
            return text.Length > 0 ? text : null;
        }

        /// <summary>
        /// The revision key of every revision cloud among <paramref name="elements"/>, in the order given,
        /// each once. Anything without a RevisionId is skipped, so a selection of walls and one cloud
        /// answers with that cloud's revision. Pure: it reads nothing but the objects handed to it.
        /// </summary>
        public static List<string> RevisionKeysOf(IEnumerable<Element> elements)
        {
            var keys = new List<string>();
            foreach (var element in elements ?? Enumerable.Empty<Element>())
            {
                string key;
                try
                {
                    // Text, because that is what Entry.Key is - a number key here would match nothing in
                    // staging.Order and the list would simply never move.
                    if (!(element is RevisionCloud cloud))
                        continue;
                    key = PsModel.EidValue(cloud.RevisionId).ToString(CultureInfo.InvariantCulture);
                }
                catch (Exception)
                {
                    continue;
                }
                if (string.IsNullOrEmpty(key) || key == "0" || key == "-1" || keys.Contains(key))
                    continue;
                keys.Add(key);
            }
            return keys;
        }

        /// <summary>
        /// A cheap value that changes whenever the selection does (the Python returned a tuple; here the
        /// sorted ids joined into one string, so == compares it). Polling Idling means this runs many
        /// times a second, so the ids alone are read first and the elements only when they have changed.
        /// </summary>
        public static string SelectionToken(UIDocument uidoc, int limit = 200)
        {
            try
            {
                var ids = uidoc.Selection.GetElementIds().Take(limit);
                return string.Join(",", ids.Select(one => PsModel.EidValue(one).ToString(CultureInfo.InvariantCulture))
                                           .OrderBy(one => one, StringComparer.Ordinal));
            }
            catch (Exception)
            {
                return "";
            }
        }

        /// <summary>
        /// The revision keys of the revision clouds now selected in Revit. Reads the document, so it may
        /// only be called from inside a valid API context - Revit's Idling event or an external event.
        /// Never throws.
        /// </summary>
        public static List<string> SelectedRevisionKeys(UIDocument uidoc, int limit = 50)
        {
            Document doc;
            List<ElementId> ids;
            try
            {
                doc = uidoc.Document;
                ids = uidoc.Selection.GetElementIds().Take(limit).ToList();
            }
            catch (Exception)
            {
                return new List<string>();
            }
            var elements = new List<Element>();
            foreach (var one in ids)
            {
                try
                {
                    elements.Add(doc.GetElement(one));
                }
                catch (Exception)
                {
                    continue;
                }
            }
            return RevisionKeysOf(elements);
        }

        /// <summary>{revision key: [series]} from (revision key, series) pairs - each series once per
        /// revision, blanks left out, in natural order.</summary>
        public static Dictionary<T, List<string>> SeriesOf<T>(IEnumerable<(T Key, string Series)> pairs)
        {
            var found = new Dictionary<T, List<string>>();
            foreach (var (key, raw) in pairs)
            {
                string series = (raw ?? "").Trim();
                if (series.Length == 0)
                    continue;
                if (!found.TryGetValue(key, out var bucket))
                    found[key] = bucket = new List<string>();
                if (!bucket.Contains(series))
                    bucket.Add(series);
            }
            foreach (var key in found.Keys.ToList())
                found[key] = found[key].OrderBy(one => one, NaturalComparer.Instance).ToList();
            return found;
        }

        /// <summary>{revision key: {view key: [cloud keys]}} from (revision, cloud, view) triples - the
        /// view each cloud is drawn in. Pure.</summary>
        public static Dictionary<string, Dictionary<string, List<string>>> CloudsByView(
            IEnumerable<(string Revision, string Cloud, string View)> drawn)
        {
            var found = new Dictionary<string, Dictionary<string, List<string>>>(StringComparer.Ordinal);
            foreach (var (revision, cloud, view) in drawn)
            {
                if (!found.TryGetValue(revision, out var byView))
                    found[revision] = byView = new Dictionary<string, List<string>>(StringComparer.Ordinal);
                if (!byView.TryGetValue(view, out var clouds))
                    byView[view] = clouds = new List<string>();
                clouds.Add(cloud);
            }
            return found;
        }

        /// <summary>{view key: [cloud keys]} across the revisions given - every view with one of their
        /// clouds in it, sheets included. Pure.</summary>
        public static Dictionary<string, List<string>> ViewsToOpen(IEnumerable<Entry> entries)
        {
            var found = new Dictionary<string, List<string>>(StringComparer.Ordinal);
            foreach (var entry in entries)
            {
                foreach (var pair in entry.CloudViews ?? new Dictionary<string, List<string>>())
                {
                    if (!found.TryGetValue(pair.Key, out var have))
                        found[pair.Key] = have = new List<string>();
                    foreach (var cloud in pair.Value)
                        if (!have.Contains(cloud))
                            have.Add(cloud);
                }
            }
            return found;
        }

        /// <summary>The keys of every view a sheet shows: each sheet itself, every view placed on one,
        /// and the parent of any placed dependent view - a cloud drawn in the parent shows on the
        /// dependent's sheet.</summary>
        public static HashSet<string> PlacedViews(Document doc)
        {
            var found = new HashSet<string>(StringComparer.Ordinal);
            try
            {
                foreach (var sheet in new FilteredElementCollector(doc).OfClass(typeof(ViewSheet)))
                    found.Add(PsModel.EidValue(sheet.Id).ToString(CultureInfo.InvariantCulture));
            }
            catch (Exception)
            {
            }
            try
            {
                foreach (Viewport viewport in new FilteredElementCollector(doc).OfClass(typeof(Viewport)))
                {
                    long viewKey = PsModel.EidValue(viewport.ViewId);
                    found.Add(viewKey.ToString(CultureInfo.InvariantCulture));
                    try
                    {
                        var view = (View)doc.GetElement(viewport.ViewId);
                        long parent = PsModel.EidValue(view.GetPrimaryViewId());
                        if (parent > 0)
                            found.Add(parent.ToString(CultureInfo.InvariantCulture));
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }
            catch (Exception)
            {
            }
            return found;
        }

        public static string ViewName(Document doc, string viewKey)
        {
            try
            {
                var view = doc.GetElement(Id(viewKey));
                return view.Name ?? "";
            }
            catch (Exception)
            {
                return string.Format("view {0}", viewKey);
            }
        }

        /// <summary>
        /// Open every view in <paramref name="byView"/> ({view key: [cloud keys]}) with its clouds
        /// temporarily isolated - Revit's own Temporary Hide/Isolate, so the view's sunglasses reset it.
        /// On Revit's thread. Returns (views opened, clouds isolated, errors).
        /// </summary>
        public static (int Opened, int Isolated, List<string> Errors) ShowClouds(UIDocument uidoc,
            Dictionary<string, List<string>> byView)
        {
            var doc = uidoc.Document;
            var views = new List<(Element View, List<string> Clouds)>();
            int isolated = 0;
            var errors = new List<string>();
            foreach (var viewKey in byView.Keys.OrderBy(k => k, StringComparer.Ordinal))
            {
                Element view;
                try
                {
                    view = doc.GetElement(Id(viewKey));
                }
                catch (Exception)
                {
                    view = null;
                }
                if (view == null)
                {
                    errors.Add(string.Format("View {0} is no longer in the model.", viewKey));
                    continue;
                }
                views.Add((view, byView[viewKey]));
            }
            if (views.Count == 0)
                return (0, 0, errors);
            using (var transaction = new Transaction(doc, "RevoBIM - Isolate revision clouds"))
            {
                try
                {
                    transaction.Start();
                }
                catch (Exception err)
                {
                    return (0, 0, new List<string> { string.Format("Revit would not start: {0}", err.Message) });
                }
                foreach (var (element, clouds) in views)
                {
                    try
                    {
                        var view = (View)element;
                        try
                        {
                            if (view.IsTemporaryHideIsolateActive())
                                view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate);
                        }
                        catch (Exception)
                        {
                        }
                        view.IsolateElementsTemporary(IdList(clouds));
                        isolated += clouds.Count;
                    }
                    catch (Exception err)
                    {
                        errors.Add(string.Format("{0}: the clouds could not be isolated: {1}", element.Name, err.Message));
                    }
                }
                try
                {
                    transaction.Commit();
                }
                catch (Exception err)
                {
                    try
                    {
                        transaction.RollBack();
                    }
                    catch (Exception)
                    {
                    }
                    errors.Add(string.Format("Revit would not keep the isolation: {0}", err.Message));
                }
            }
            int opened = 0;
            // Opened after the transaction: a view cannot be made active inside one. The first view is
            // opened last, so it is the one in front.
            foreach (var (element, _) in Enumerable.Reverse(views))
            {
                try
                {
                    uidoc.ActiveView = (View)element;
                    opened += 1;
                }
                catch (Exception err)
                {
                    errors.Add(string.Format("{0} would not open: {1}", element.Name, err.Message));
                }
            }
            return (opened, isolated, errors);
        }

        /// <summary>
        /// Open each sheet or view in Revit - Open sheets on the right-click. On Revit's thread, outside
        /// any transaction (a view cannot be made active inside one). The first is opened last, so the
        /// top of the highlight is the one in front. Returns (opened, errors).
        /// </summary>
        public static (int Opened, List<string> Errors) OpenViews(UIDocument uidoc, IEnumerable<View> views)
        {
            int opened = 0;
            var errors = new List<string>();
            foreach (var view in Enumerable.Reverse((views ?? Enumerable.Empty<View>()).ToList()))
            {
                if (view == null)
                    continue;
                try
                {
                    uidoc.ActiveView = view;
                    opened += 1;
                }
                catch (Exception err)
                {
                    string name;
                    try
                    {
                        name = view.Name ?? "";
                    }
                    catch (Exception)
                    {
                        name = "A view";
                    }
                    errors.Add(string.Format("{0} would not open: {1}", name, err.Message));
                }
            }
            return (opened, errors);
        }

        /// <summary>One line on what Open sheets did.</summary>
        public static string OpenedReport(int opened, IList<string> errors, string word = "sheet")
        {
            string text = string.Format("{0} {1}{2} opened.", opened, word, opened == 1 ? "" : "s");
            if (errors != null && errors.Count > 0)
                text += string.Format(" {0} could not be: {1}", errors.Count, string.Join(" ", errors.Take(3)));
            return text;
        }

        /// <summary>One line on what Find clouds on views did.</summary>
        public static string CloudsReport(int opened, int isolated, IList<string> errors)
        {
            string text = string.Format("{0} view{1} opened, {2} cloud{3} isolated in them - Revit's " +
                                        "Temporary Hide/Isolate, reset from the sunglasses.",
                                        opened, opened == 1 ? "" : "s", isolated, isolated == 1 ? "" : "s");
            if (errors != null && errors.Count > 0)
                text += string.Format(" {0} could not be: {1}", errors.Count, string.Join(" ", errors.Take(3)));
            return text;
        }

        /// <summary>The status most of a revision's sheets carry; ties to the first seen. Blanks do not count.</summary>
        public static string CommonStatus(IEnumerable<string> texts)
        {
            var counts = new Dictionary<string, int>(StringComparer.Ordinal);
            var order = new List<string>();
            foreach (var raw in texts)
            {
                string text = (raw ?? "").Trim();
                if (text.Length == 0)
                    continue;
                if (!counts.ContainsKey(text))
                {
                    order.Add(text);
                    counts[text] = 0;
                }
                counts[text] += 1;
            }
            if (order.Count == 0)
                return "";
            return order.Select((one, index) => (one, index))
                .OrderBy(p => -counts[p.one]).ThenBy(p => p.index).First().one;
        }

        /// <summary>
        /// A Staging of the project's revisions, with what uses each one. <paramref name="seriesParam"/>
        /// is the sheet parameter Setup names as the series (BGL_Sheet Series on the house template);
        /// blank leaves the Sheet series column empty. <paramref name="statusParam"/> (BGL_Sheet Status)
        /// fills an empty Issue Status from the sheets carrying the revision - staged, so Apply keeps it
        /// with the revision.
        /// </summary>
        public static Staging Read(Document doc, string seriesParam = "", string statusParam = "")
        {
            var (bySequence, names) = SequenceNames(doc);
            var (columns, stored) = PsRevData.Read(doc);
            var sheets = new Dictionary<long, List<string>>();
            var statuses = new Dictionary<string, List<string>>(StringComparer.Ordinal);
            var pairs = new List<(long Key, string Series)>();
            try
            {
                foreach (ViewSheet sheet in new FilteredElementCollector(doc).OfClass(typeof(ViewSheet)))
                {
                    List<ElementId> carried;
                    try
                    {
                        carried = sheet.GetAllRevisionIds().ToList();
                    }
                    catch (Exception)
                    {
                        carried = new List<ElementId>();
                    }
                    string series = "";
                    if (!string.IsNullOrEmpty(seriesParam) && carried.Count > 0)
                    {
                        try
                        {
                            series = PsModel.ParamText(sheet, seriesParam);
                        }
                        catch (Exception)
                        {
                            series = "";
                        }
                    }
                    string status = "";
                    if (!string.IsNullOrEmpty(statusParam) && carried.Count > 0)
                    {
                        try
                        {
                            status = PsModel.ParamText(sheet, statusParam);
                        }
                        catch (Exception)
                        {
                            status = "";
                        }
                    }
                    foreach (var revisionId in carried)
                    {
                        long key = PsModel.EidValue(revisionId);
                        if (!sheets.TryGetValue(key, out var list))
                            sheets[key] = list = new List<string>();
                        list.Add(sheet.SheetNumber ?? "");
                        pairs.Add((key, series));
                        string text = key.ToString(CultureInfo.InvariantCulture);
                        if (!statuses.TryGetValue(text, out var found))
                            statuses[text] = found = new List<string>();
                        found.Add(status);
                    }
                }
            }
            catch (Exception)
            {
            }
            var seriesByKey = SeriesOf(pairs);
            var clouds = new Dictionary<long, int>();
            var drawn = new List<(string Revision, string Cloud, string View)>();
            try
            {
                foreach (RevisionCloud cloud in new FilteredElementCollector(doc).OfClass(typeof(RevisionCloud)))
                {
                    long key = PsModel.EidValue(cloud.RevisionId);
                    clouds[key] = (clouds.TryGetValue(key, out var n) ? n : 0) + 1;
                    try
                    {
                        drawn.Add((key.ToString(CultureInfo.InvariantCulture),
                                   PsModel.EidValue(cloud.Id).ToString(CultureInfo.InvariantCulture),
                                   PsModel.EidValue(cloud.OwnerViewId).ToString(CultureInfo.InvariantCulture)));
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }
            catch (Exception)
            {
            }
            var byView = CloudsByView(drawn);
            var placed = PlacedViews(doc);

            var entries = new List<Entry>();
            List<ElementId> ids;
            try
            {
                ids = Revision.GetAllRevisionIds(doc).ToList();
            }
            catch (Exception)
            {
                ids = new List<ElementId>();
            }
            for (int index = 0; index < ids.Count; index++)
            {
                var revisionId = ids[index];
                var revision = doc.GetElement(revisionId) as Revision;
                if (revision == null)
                    continue;
                long key = PsModel.EidValue(revisionId);
                string numbering;
                try
                {
                    numbering = bySequence.TryGetValue(PsModel.EidValue(revision.RevisionNumberingSequenceId), out var nm) ? nm : "";
                }
                catch (Exception)
                {
                    numbering = "";
                }
                bool issued;
                try
                {
                    issued = revision.Issued;
                }
                catch (Exception)
                {
                    issued = false;
                }
                string visibility;
                try
                {
                    visibility = revision.Visibility.ToString();
                }
                catch (Exception)
                {
                    visibility = "";
                }
                int sequence;
                try
                {
                    sequence = revision.SequenceNumber;
                }
                catch (Exception)
                {
                    sequence = index + 1;
                }
                string uid;
                try
                {
                    uid = revision.UniqueId ?? "";
                }
                catch (Exception)
                {
                    uid = "";
                }
                var entry = new Entry(
                    key, key, sequence,
                    new Dictionary<string, object>(StringComparer.Ordinal)
                    {
                        { "numbering", numbering },
                        { "date", Text(revision, "RevisionDate") },
                        { "desc", Text(revision, "Description") },
                        { "issued", issued },
                        { "issued_to", Text(revision, "IssuedTo") },
                        { "issued_by", Text(revision, "IssuedBy") },
                        { "show", ShowLabel(visibility) },
                    },
                    (sheets.TryGetValue(key, out var on) ? on : new List<string>()).OrderBy(one => one, NaturalComparer.Instance),
                    clouds.TryGetValue(key, out var count) ? count : 0, uid,
                    stored.TryGetValue(uid, out var row) ? row : new Dictionary<string, string>());
                entries.Add(entry);
                entry.Series = seriesByKey.TryGetValue(key, out var ser) ? ser : new List<string>();
                var views = byView.TryGetValue(key.ToString(CultureInfo.InvariantCulture), out var vs)
                    ? vs : new Dictionary<string, List<string>>(StringComparer.Ordinal);
                entry.CloudViews = views;
                entry.OffViews = views.OrderBy(p => p.Key, StringComparer.Ordinal)
                    .Where(p => !placed.Contains(p.Key))
                    .Select(p => (p.Key, ViewName(doc, p.Key), p.Value.Count)).ToList();
            }

            string numberingMode = PerProject;
            double arcMm = 0.0;
            try
            {
                var settings = RevisionSettings.GetRevisionSettings(doc);
                numberingMode = settings.RevisionNumbering.ToString() == PerSheet ? PerSheet : PerProject;
                arcMm = Math.Round(settings.RevisionCloudSpacing * FeetToMm, 3, MidpointRounding.AwayFromZero);
            }
            catch (Exception)
            {
            }
            var staging = new Staging(entries, numberingMode, arcMm, names, columns);
            staging.FillStatuses(statuses.ToDictionary(p => p.Key, p => CommonStatus(p.Value), StringComparer.Ordinal));
            return staging;
        }

        /// <summary>Execute's view of a Revit document. Called inside a transaction.</summary>
        public class RevitApi
        {
            public Document Doc;
            /// <summary>{sequence name: element key}.</summary>
            public Dictionary<string, long> Sequences;

            public RevitApi(Document doc)
            {
                Doc = doc;
                Sequences = new Dictionary<string, long>(StringComparer.Ordinal);
                foreach (var pair in SequenceNames(doc).ByKey)
                    Sequences[pair.Value] = pair.Key;
            }

            public List<long> Ids()
            {
                return Revision.GetAllRevisionIds(Doc).Select(one => PsModel.EidValue(one)).ToList();
            }

            public string Label(long elementKey)
            {
                try
                {
                    return ((Revision)Doc.GetElement(Id(elementKey))).SequenceNumber.ToString(CultureInfo.InvariantCulture);
                }
                catch (Exception)
                {
                    return elementKey.ToString(CultureInfo.InvariantCulture);
                }
            }

            public long Create()
            {
                return PsModel.EidValue(Revision.Create(Doc).Id);
            }

            public void SetField(long elementKey, string field, object value)
            {
                var revision = (Revision)Doc.GetElement(Id(elementKey));
                if (revision == null)
                    throw new InvalidOperationException(string.Format("revision {0} is no longer in the model", elementKey));
                if (field == "issued")
                {
                    revision.Issued = Truthy(value);
                }
                else if (field == "date")
                {
                    revision.RevisionDate = S(value);
                }
                else if (field == "desc")
                {
                    revision.Description = S(value);
                }
                else if (field == "issued_to")
                {
                    revision.IssuedTo = S(value);
                }
                else if (field == "issued_by")
                {
                    revision.IssuedBy = S(value);
                }
                else if (field == "show")
                {
                    revision.Visibility = (RevisionVisibility)Enum.Parse(typeof(RevisionVisibility), ShowName(S(value)));
                }
                else if (field == "numbering")
                {
                    string name = S(value);
                    if (!Sequences.ContainsKey(name))
                        throw new ArgumentException(string.Format("no numbering sequence called \"{0}\"", name));
                    revision.RevisionNumberingSequenceId = Id(Sequences[name]);
                }
            }

            public void CombineWithPrevious(long elementKey)
            {
                Revision.CombineWithPrevious(Doc, Id(elementKey));
            }

            public void Delete(long elementKey)
            {
                Doc.Delete(Id(elementKey));
            }

            public void Reorder(IEnumerable<long> keys)
            {
                Revision.ReorderRevisionSequence(Doc, IdList(keys));
            }

            public void WriteCustom(List<PsRevData.Column> columns, Dictionary<long, Dictionary<string, string>> valuesByKey)
            {
                var byUid = new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
                foreach (var pair in valuesByKey)
                {
                    try
                    {
                        byUid[Doc.GetElement(Id(pair.Key)).UniqueId ?? ""] = pair.Value;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
                PsRevData.Write(Doc, columns, byUid);
            }

            public (int Count, List<string> Problems) Push(List<PsRevData.Column> columns,
                                                           Dictionary<long, Dictionary<string, string>> valuesByKey)
            {
                return PsRevData.Push(Doc, columns, valuesByKey);
            }

            public void SetSetting(string name, object value)
            {
                var settings = RevisionSettings.GetRevisionSettings(Doc);
                if (name == "numbering")
                    settings.RevisionNumbering = S(value) == PerSheet ? RevisionNumbering.PerSheet : RevisionNumbering.PerProject;
                else if (name == "arc_mm")
                    settings.RevisionCloudSpacing = Convert.ToDouble(value, CultureInfo.InvariantCulture) / FeetToMm;
            }
        }

        /// <summary>plan_assign's result.</summary>
        public class AssignPlan
        {
            /// <summary>{sheet: its new set of revisions put on by hand}.</summary>
            public Dictionary<string, HashSet<string>> Additional = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
            public List<string> Changed = new List<string>();
            public List<(string Sheet, string Why)> Skipped = new List<(string, string)>();
        }

        /// <summary>
        /// Put one revision on sheets, by hand - Revit's Revisions on Sheet. Pure.
        /// <paramref name="additional"/> {sheet: the revisions put on it by hand}; <paramref name="carried"/>
        /// {sheet: every revision it shows, clouds included}. A sheet already carrying the revision is left
        /// - adding it again changes nothing - and an issued revision goes on no sheet: Revit locks it.
        /// </summary>
        public static AssignPlan PlanAssign(IEnumerable<string> sheetKeys, string revision,
                                            IDictionary<string, HashSet<string>> additional,
                                            IDictionary<string, HashSet<string>> carried, IEnumerable<string> issued)
        {
            revision = revision ?? "";
            var result = new AssignPlan();
            var issuedSet = new HashSet<string>(issued ?? Enumerable.Empty<string>(), StringComparer.Ordinal);
            foreach (var sheet in sheetKeys)
            {
                if (issuedSet.Contains(revision))
                {
                    result.Skipped.Add((sheet, SwapIssued));
                    continue;
                }
                HashSet<string> on = null;
                carried?.TryGetValue(sheet, out on);
                if (on != null && on.Contains(revision))
                {
                    result.Skipped.Add((sheet, "already carries it"));
                    continue;
                }
                HashSet<string> byHand = null;
                additional?.TryGetValue(sheet, out byHand);
                var set = new HashSet<string>(byHand ?? new HashSet<string>(), StringComparer.Ordinal) { revision };
                result.Additional[sheet] = set;
                result.Changed.Add(sheet);
            }
            return result;
        }

        /// <summary>Put a revision on the sheets, in one transaction. On Revit's thread.
        /// Returns (assigned sheets, [(sheet, why)] skipped, errors).</summary>
        public static (List<string> Assigned, List<(string Sheet, string Why)> Skipped, List<string> Errors) AssignToSheets(
            Document doc, IList<string> sheetKeys, string revision, Dictionary<string, ViewSheet> sheets = null)
        {
            string KeyOf(ElementId elementId) => PsModel.EidValue(elementId).ToString(CultureInfo.InvariantCulture);

            sheets = new Dictionary<string, ViewSheet>(sheets ?? new Dictionary<string, ViewSheet>(), StringComparer.Ordinal);
            var additional = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
            var carried = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
            foreach (var sheetKey in sheetKeys)
            {
                sheets.TryGetValue(sheetKey, out var sheet);
                if (sheet == null)
                {
                    try
                    {
                        sheet = doc.GetElement(Id(sheetKey)) as ViewSheet;
                    }
                    catch (Exception)
                    {
                        sheet = null;
                    }
                    sheets[sheetKey] = sheet;
                }
                try
                {
                    additional[sheetKey] = new HashSet<string>(sheet.GetAdditionalRevisionIds().Select(KeyOf), StringComparer.Ordinal);
                }
                catch (Exception)
                {
                    additional[sheetKey] = new HashSet<string>(StringComparer.Ordinal);
                }
                try
                {
                    carried[sheetKey] = new HashSet<string>(sheet.GetAllRevisionIds().Select(KeyOf), StringComparer.Ordinal);
                }
                catch (Exception)
                {
                    carried[sheetKey] = new HashSet<string>(additional[sheetKey], StringComparer.Ordinal);
                }
            }
            var issued = new HashSet<string>(StringComparer.Ordinal);
            try
            {
                if (((Revision)doc.GetElement(Id(revision))).Issued)
                    issued.Add(revision);
            }
            catch (Exception)
            {
            }
            var plan = PlanAssign(sheetKeys, revision, additional, carried, issued);
            if (plan.Additional.Count == 0)
                return (new List<string>(), plan.Skipped, new List<string>());
            var errors = new List<string>();
            var done = new List<string>();
            using (var transaction = new Transaction(doc, "RevoBIM - Assign revision to sheets"))
            {
                try
                {
                    transaction.Start();
                }
                catch (Exception err)
                {
                    return (new List<string>(), plan.Skipped,
                            new List<string> { string.Format("The transaction would not start: {0}", err.Message) });
                }
                foreach (var pair in plan.Additional.OrderBy(p => p.Key, StringComparer.Ordinal))
                {
                    try
                    {
                        sheets[pair.Key].SetAdditionalRevisionIds(IdList(pair.Value.OrderBy(k => k, StringComparer.Ordinal)));
                        done.Add(pair.Key);
                    }
                    catch (Exception err)
                    {
                        errors.Add(string.Format("Sheet {0}: Revit would not add it: {1}",
                            SheetLabel(sheets.TryGetValue(pair.Key, out var s) ? s : null, pair.Key), err.Message));
                    }
                }
                try
                {
                    transaction.Commit();
                }
                catch (Exception err)
                {
                    try
                    {
                        transaction.RollBack();
                    }
                    catch (Exception)
                    {
                    }
                    return (new List<string>(), plan.Skipped,
                            new List<string> { string.Format("Revit would not keep the changes: {0}", err.Message) });
                }
            }
            return (done, plan.Skipped, errors);
        }

        /// <summary>Every revision in the project, as text keys.</summary>
        public static List<string> RevisionKeys(Document doc)
        {
            try
            {
                return Revision.GetAllRevisionIds(doc)
                    .Select(one => PsModel.EidValue(one).ToString(CultureInfo.InvariantCulture)).ToList();
            }
            catch (Exception)
            {
                return new List<string>();
            }
        }

        /// <summary>
        /// Create the revision the plan adds, then put it on the picked cells in place of what they carry.
        /// The Document Register's "Create new revision". On Revit's thread. Two transactions: the revision
        /// has to exist before a sheet or a cloud can point at it. Which revision is new is read from the
        /// model - before and after - rather than trusted from the plan.
        /// Returns (new key or "", changed, skipped, errors).
        /// </summary>
        public static (string NewKey, List<(string Sheet, string Revision)> Changed,
                       List<(string Sheet, string Revision, string Why)> Skipped, List<string> Errors) CreateAndSwap(
            Document doc, Plan plan, Dictionary<string, HashSet<string>> picks, Dictionary<string, ViewSheet> sheets = null,
            bool includeShared = false, SwapReport report = null)
        {
            var before = new HashSet<string>(RevisionKeys(doc), StringComparer.Ordinal);
            var (_, written) = Write(doc, plan);
            var errors = new List<string>(written);
            var made = RevisionKeys(doc).Where(key => !before.Contains(key)).ToList();
            if (made.Count != 1)
            {
                errors.Add(made.Count > 0
                    ? "The new revision could not be told apart from the others after it was made, so no sheet was changed onto it."
                    : "The new revision was not created, so no sheet was changed.");
                return ("", new List<(string, string)>(), new List<(string, string, string)>(), errors);
            }
            var (changed, skipped, more) = SwapOnSheets(doc, picks, made[0], sheets, includeShared, report);
            errors.AddRange(more);
            return (made[0], changed, skipped, errors);
        }

        /// <summary>
        /// Make the one revision a plan adds, and say which it is - read from the model before and after,
        /// not trusted from the plan. The register's Create new revision then stages the picked cells onto
        /// it; they wait for Apply revisions. On Revit's thread. Returns (new key or "", errors).
        /// </summary>
        public static (string NewKey, List<string> Errors) CreateOnly(Document doc, Plan plan)
        {
            var existing = new HashSet<string>(RevisionKeys(doc), StringComparer.Ordinal);
            var (_, written) = Write(doc, plan);
            var problems = new List<string>(written);
            var made = RevisionKeys(doc).Where(key => !existing.Contains(key)).ToList();
            if (made.Count == 1)
                return (made[0], problems);
            if (made.Count > 0)
                problems.Add("More than one revision appeared, so the new one could not be told apart. No cell was staged onto it.");
            else
                problems.Add("The revision was not created.");
            return ("", problems);
        }

        /// <summary>The plan, in one transaction. (done, errors).</summary>
        public static (int Done, List<string> Errors) Write(Document doc, Plan plan)
        {
            using (var transaction = new Transaction(doc, "RevoBIM - Revision Manager"))
            {
                try
                {
                    transaction.Start();
                }
                catch (Exception err)
                {
                    return (0, new List<string> { string.Format("The transaction would not start: {0}", err.Message) });
                }
                int done;
                List<string> errors;
                try
                {
                    (done, errors) = Execute(new RevitApi(doc), plan);
                }
                catch (Exception err)
                {
                    try
                    {
                        transaction.RollBack();
                    }
                    catch (Exception)
                    {
                    }
                    return (0, new List<string> { string.Format("Nothing was changed: {0}", err.Message) });
                }
                try
                {
                    transaction.Commit();
                }
                catch (Exception err)
                {
                    return (0, new List<string> { string.Format("Revit would not keep the changes: {0}", err.Message) });
                }
                return (done, errors);
            }
        }

        // ==========================================================================
        // changing the revision a sheet carries - the Document Register's "Change revision on sheet"
        //
        // A revision is on a sheet in one of two ways, and both have to be followed or the swap only
        // half happens:
        //   - added by hand, in Revit's "Revisions on Sheet" - the sheet's additional revisions;
        //   - drawn: a revision cloud on the sheet itself, or in a view placed on it.
        // A cloud is only re-pointed when EVERY sheet it reaches is having that same revision changed.
        // A cloud in a legend on twenty sheets, re-pointed for the two that were picked, would quietly
        // change the other eighteen.
        // ==========================================================================

        public const string SwapIssued = "is issued - Revit keeps an issued revision where it is";

        /// <summary>plan_swap's result.</summary>
        public class SwapPlan
        {
            /// <summary>{sheet key: the sheet's new set of revisions put on by hand}.</summary>
            public Dictionary<string, HashSet<string>> Additional = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
            /// <summary>Cloud keys to re-point at the target (or, removing, to delete).</summary>
            public List<string> Clouds = new List<string>();
            public List<(string Sheet, string Revision, string Why)> Skipped = new List<(string, string, string)>();
            /// <summary>Every pick that will be fully moved.</summary>
            public List<(string Sheet, string Revision)> Changed = new List<(string, string)>();
            /// <summary>Every cloud that also shows on a sheet not picked - left or taken.</summary>
            public List<(string Sheet, string Revision, string Cloud, List<string> Others)> Shared =
                new List<(string, string, string, List<string>)>();
        }

        /// <summary>The swap_on_sheets ``report`` dict: 'shared' out, 'include_shared' passed back.</summary>
        public class SwapReport
        {
            public List<(string Sheet, string Revision, string Cloud, List<string> Others)> Shared =
                new List<(string, string, string, List<string>)>();
            public bool IncludeShared;
        }

        /// <summary>
        /// What "change these cells to that revision" will actually do. Pure.
        /// picks {sheet key: set of revision keys} - the cells picked. target the revision key they are to
        /// become, or null to take the revision off the sheets altogether (see PlanRemove). additional
        /// {sheet key: set of revision keys} put on each picked sheet by hand. clouds [(cloud key, revision
        /// key, set of sheet keys it reaches)]. issued the revision keys that are issued. includeShared
        /// also take a cloud that shows on sheets NOT picked - a cloud is one element: changing it changes
        /// every sheet it shows on. Off, those clouds are left and reported; on - the user having been
        /// asked - they go too. All keys are text.
        /// </summary>
        public static SwapPlan PlanSwap(IDictionary<string, HashSet<string>> picks, string target,
                                        IDictionary<string, HashSet<string>> additional,
                                        IEnumerable<(string Cloud, string Revision, HashSet<string> Reaches)> clouds,
                                        IEnumerable<string> issued, bool includeShared = false)
        {
            var result = new SwapPlan();
            var pickMap = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
            foreach (var pair in picks ?? new Dictionary<string, HashSet<string>>())
                pickMap[pair.Key] = new HashSet<string>(pair.Value ?? new HashSet<string>(), StringComparer.Ordinal);
            var issuedSet = new HashSet<string>(issued ?? Enumerable.Empty<string>(), StringComparer.Ordinal);
            var cloudList = (clouds ?? Enumerable.Empty<(string, string, HashSet<string>)>()).ToList();
            var sortedSheets = pickMap.Keys.OrderBy(k => k, StringComparer.Ordinal).ToList();

            if (target != null && issuedSet.Contains(target))
            {
                foreach (var sheet in sortedSheets)
                    foreach (var old in pickMap[sheet].OrderBy(k => k, StringComparer.Ordinal))
                        result.Skipped.Add((sheet, old, "the revision chosen " + SwapIssued));
                return result;
            }

            // The sheets each old revision is being taken off.
            var leaving = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
            foreach (var pair in pickMap)
            {
                foreach (var old in pair.Value)
                {
                    if (!leaving.TryGetValue(old, out var set))
                        leaving[old] = set = new HashSet<string>(StringComparer.Ordinal);
                    set.Add(pair.Key);
                }
            }

            var chosen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var sheet in sortedSheets)
            {
                foreach (var old in pickMap[sheet].OrderBy(k => k, StringComparer.Ordinal))
                {
                    if (old == target)
                    {
                        result.Skipped.Add((sheet, old, "already that revision"));
                        continue;
                    }
                    if (issuedSet.Contains(old))
                    {
                        result.Skipped.Add((sheet, old, SwapIssued));
                        continue;
                    }
                    bool moved = false;
                    var stuck = new List<string>();
                    HashSet<string> byHand = null;
                    additional?.TryGetValue(sheet, out byHand);
                    byHand = byHand ?? new HashSet<string>(StringComparer.Ordinal);
                    if (byHand.Contains(old))
                    {
                        if (!result.Additional.TryGetValue(sheet, out var now))
                            now = new HashSet<string>(byHand, StringComparer.Ordinal);
                        now.Remove(old);
                        if (target != null)
                            now.Add(target);
                        result.Additional[sheet] = now;
                        moved = true;
                    }
                    var leavingOld = leaving.TryGetValue(old, out var lo) ? lo : new HashSet<string>(StringComparer.Ordinal);
                    foreach (var (cloudKey, cloudRev, reachesRaw) in cloudList)
                    {
                        var reaches = new HashSet<string>(reachesRaw ?? new HashSet<string>(), StringComparer.Ordinal);
                        if (cloudRev != old || !reaches.Contains(sheet))
                            continue;
                        if (reaches.IsSubsetOf(leavingOld))
                        {
                            if (!chosen.Contains(cloudKey))
                            {
                                chosen.Add(cloudKey);
                                result.Clouds.Add(cloudKey);
                            }
                            moved = true;
                            continue;
                        }
                        result.Shared.Add((sheet, old, cloudKey,
                                           reaches.Where(one => !leavingOld.Contains(one)).OrderBy(k => k, StringComparer.Ordinal).ToList()));
                        if (includeShared)
                        {
                            if (!chosen.Contains(cloudKey))
                            {
                                chosen.Add(cloudKey);
                                result.Clouds.Add(cloudKey);
                            }
                            moved = true;
                        }
                        else
                        {
                            stuck.Add(cloudKey);
                        }
                    }
                    if (stuck.Count > 0)
                    {
                        result.Skipped.Add((sheet, old, string.Format(
                            "{0} cloud{1} for it also show{2} on sheets not picked, so " +
                            "they were left and the sheet still carries it - pick " +
                            "those sheets too, or move the cloud{1}",
                            stuck.Count, stuck.Count == 1 ? "" : "s", stuck.Count == 1 ? "s" : "")));
                    }
                    else if (moved)
                    {
                        result.Changed.Add((sheet, old));
                    }
                    else
                    {
                        result.Skipped.Add((sheet, old, "nothing on the sheet carries it any more - press Refresh"));
                    }
                }
            }
            return result;
        }

        /// <summary>
        /// What "remove these revisions from these sheets" will do. Pure. PlanSwap with nowhere to go: a
        /// revision added by hand comes off the sheet, and its clouds reaching only picked sheets are to be
        /// DELETED - Clouds in the result is the clouds to delete. A cloud that also shows on a sheet not
        /// picked is left and reported, exactly as for a change: deleting it would take the revision off
        /// that sheet too.
        /// </summary>
        public static SwapPlan PlanRemove(IDictionary<string, HashSet<string>> picks, IDictionary<string, HashSet<string>> additional,
                                          IEnumerable<(string Cloud, string Revision, HashSet<string> Reaches)> clouds,
                                          IEnumerable<string> issued, bool includeShared = false)
        {
            return PlanSwap(picks, null, additional, clouds, issued, includeShared);
        }

        /// <summary>Take the picked revisions off their sheets, clouds and all. On Revit's API thread;
        /// one transaction. (removed, skipped, errors).</summary>
        public static (List<(string Sheet, string Revision)> Changed, List<(string Sheet, string Revision, string Why)> Skipped,
                       List<string> Errors) RemoveOnSheets(Document doc, Dictionary<string, HashSet<string>> picks,
                                                           Dictionary<string, ViewSheet> sheets = null, bool includeShared = false,
                                                           SwapReport report = null)
        {
            return SwapOnSheets(doc, picks, null, sheets, includeShared, report);
        }

        /// <summary>
        /// The revision clouds of <paramref name="revisions"/> a sheet actually shows. Looked for the way
        /// you would by hand: on the sheet itself, then inside every view placed on it, each with a
        /// view-scoped collector - which gives what that view shows. This is the fix for 1.40.0's "3 clouds
        /// also show on sheets not picked": RevisionCloud.GetSheetIds lists every sheet a cloud MAY appear
        /// on, so a cloud in a parent view was counted on the sheet of every dependent view, crop or no
        /// crop. Never throws.
        /// </summary>
        public static HashSet<string> CloudsSeenOn(Document doc, ViewSheet sheet, ICollection<string> revisions)
        {
            string KeyOf(ElementId elementId) => PsModel.EidValue(elementId).ToString(CultureInfo.InvariantCulture);

            var found = new HashSet<string>(StringComparer.Ordinal);
            var views = new List<ElementId>();
            try
            {
                views.Add(sheet.Id);
            }
            catch (Exception)
            {
                return found;
            }
            try
            {
                views.AddRange(sheet.GetAllPlacedViews());
            }
            catch (Exception)
            {
            }
            foreach (var viewId in views)
            {
                try
                {
                    foreach (RevisionCloud cloud in new FilteredElementCollector(doc, viewId).OfClass(typeof(RevisionCloud)))
                    {
                        if (revisions.Contains(KeyOf(cloud.RevisionId)))
                            found.Add(KeyOf(cloud.Id));
                    }
                }
                catch (Exception)
                {
                    continue;
                }
            }
            return found;
        }

        /// <summary>
        /// Change the picked cells to <paramref name="target"/>, in one transaction (null target: take
        /// them off - RemoveOnSheets). On Revit's API thread. <paramref name="picks"/> is {sheet key: set of
        /// revision keys}; <paramref name="sheets"/> maps a sheet key to its ViewSheet when the caller
        /// already holds them. Reads what PlanSwap needs fresh, here, so the decision is made on the model
        /// as it is now rather than as the register last saw it.
        /// Returns (changed, skipped, errors): the picks moved, the picks left with why, and anything Revit
        /// refused. A <paramref name="report"/>, if given, gets Shared: the clouds that also show on sheets
        /// not picked - for the caller to ask about - and IncludeShared passes the answer back.
        /// </summary>
        public static (List<(string Sheet, string Revision)> Changed, List<(string Sheet, string Revision, string Why)> Skipped,
                       List<string> Errors) SwapOnSheets(Document doc, Dictionary<string, HashSet<string>> picks, string target,
                                                         Dictionary<string, ViewSheet> sheets = null, bool includeShared = false,
                                                         SwapReport report = null)
        {
            string KeyOf(ElementId elementId) => PsModel.EidValue(elementId).ToString(CultureInfo.InvariantCulture);

            sheets = new Dictionary<string, ViewSheet>(sheets ?? new Dictionary<string, ViewSheet>(), StringComparer.Ordinal);
            var additional = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
            foreach (var sheetKey in picks.Keys)
            {
                sheets.TryGetValue(sheetKey, out var sheet);
                if (sheet == null)
                {
                    try
                    {
                        sheet = doc.GetElement(Id(sheetKey)) as ViewSheet;
                    }
                    catch (Exception)
                    {
                        sheet = null;
                    }
                    sheets[sheetKey] = sheet;
                }
                try
                {
                    additional[sheetKey] = new HashSet<string>(sheet.GetAdditionalRevisionIds().Select(KeyOf), StringComparer.Ordinal);
                }
                catch (Exception)
                {
                    additional[sheetKey] = new HashSet<string>(StringComparer.Ordinal);
                }
            }

            var olds = new HashSet<string>(StringComparer.Ordinal);
            foreach (var revisions in picks.Values)
                olds.UnionWith(revisions ?? new HashSet<string>());
            // Every cloud of the old revisions, with the sheets Revit says it MAY appear on. Only a
            // shortlist: see CloudsSeenOn.
            var candidates = new List<(string Cloud, string Revision, HashSet<string> May)>();
            try
            {
                foreach (RevisionCloud cloud in new FilteredElementCollector(doc).OfClass(typeof(RevisionCloud)))
                {
                    string revision = KeyOf(cloud.RevisionId);
                    if (!olds.Contains(revision))
                        continue;
                    HashSet<string> may;
                    try
                    {
                        may = new HashSet<string>(cloud.GetSheetIds().Select(KeyOf), StringComparer.Ordinal);
                    }
                    catch (Exception)
                    {
                        may = new HashSet<string>(StringComparer.Ordinal);
                    }
                    candidates.Add((KeyOf(cloud.Id), revision, may));
                }
            }
            catch (Exception)
            {
            }

            // Then look inside each of those sheets for what it really shows.
            var look = new HashSet<string>(picks.Keys, StringComparer.Ordinal);
            foreach (var (_, _, may) in candidates)
                look.UnionWith(may);
            var seen = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
            foreach (var sheetKey in look.OrderBy(k => k, StringComparer.Ordinal))
            {
                sheets.TryGetValue(sheetKey, out var sheet);
                if (sheet == null)
                {
                    try
                    {
                        sheet = doc.GetElement(Id(sheetKey)) as ViewSheet;
                    }
                    catch (Exception)
                    {
                        sheet = null;
                    }
                }
                if (sheet == null)
                    continue;
                foreach (var cloudKey in CloudsSeenOn(doc, sheet, olds))
                {
                    if (!seen.TryGetValue(cloudKey, out var on))
                        seen[cloudKey] = on = new HashSet<string>(StringComparer.Ordinal);
                    on.Add(sheetKey);
                }
            }
            var clouds = new List<(string Cloud, string Revision, HashSet<string> Reaches)>();
            foreach (var (cloudKey, revision, may) in candidates)
            {
                // Seen somewhere: those sheets are where it is. Seen nowhere - a Revit whose view collector
                // shows no annotation - trust GetSheetIds rather than lose the cloud.
                clouds.Add((cloudKey, revision, seen.TryGetValue(cloudKey, out var s) && s.Count > 0 ? s : may));
            }

            var issued = new HashSet<string>(StringComparer.Ordinal);
            var wantedKeys = new HashSet<string>(olds, StringComparer.Ordinal);
            if (target != null)
                wantedKeys.Add(target);
            foreach (var key in wantedKeys)
            {
                try
                {
                    if (((Revision)doc.GetElement(Id(key))).Issued)
                        issued.Add(key);
                }
                catch (Exception)
                {
                    continue;
                }
            }

            var plan = PlanSwap(picks.ToDictionary(p => p.Key, p => p.Value, StringComparer.Ordinal), target, additional,
                                clouds, issued, includeShared);
            if (report != null)
            {
                report.Shared = new List<(string, string, string, List<string>)>(plan.Shared);
                report.IncludeShared = includeShared;
            }
            if (plan.Additional.Count == 0 && plan.Clouds.Count == 0)
                return (new List<(string, string)>(), plan.Skipped, new List<string>());

            var errors = new List<string>();
            var failed = new HashSet<string>(StringComparer.Ordinal);
            using (var transaction = new Transaction(doc, target == null
                       ? "RevoBIM - Remove revision from sheets"
                       : "RevoBIM - Change revision on sheets"))
            {
                try
                {
                    transaction.Start();
                }
                catch (Exception err)
                {
                    return (new List<(string, string)>(), plan.Skipped,
                            new List<string> { string.Format("The transaction would not start: {0}", err.Message) });
                }
                foreach (var pair in plan.Additional.OrderBy(p => p.Key, StringComparer.Ordinal))
                {
                    try
                    {
                        sheets[pair.Key].SetAdditionalRevisionIds(IdList(pair.Value.OrderBy(k => k, StringComparer.Ordinal)));
                    }
                    catch (Exception err)
                    {
                        failed.Add(pair.Key);
                        errors.Add(string.Format("Sheet {0}: Revit would not change its revisions: {1}",
                            SheetLabel(sheets.TryGetValue(pair.Key, out var s) ? s : null, pair.Key), err.Message));
                    }
                }
                ElementId targetId = target == null ? null : Id(target);
                foreach (var cloudKey in plan.Clouds)
                {
                    try
                    {
                        if (targetId == null)
                            doc.Delete(Id(cloudKey));
                        else
                            ((RevisionCloud)doc.GetElement(Id(cloudKey))).RevisionId = targetId;
                    }
                    catch (Exception err)
                    {
                        errors.Add(string.Format("Revision cloud {0}: Revit would not {1} it: {2}",
                            cloudKey, targetId == null ? "delete" : "move", err.Message));
                    }
                }
                try
                {
                    transaction.Commit();
                }
                catch (Exception err)
                {
                    try
                    {
                        transaction.RollBack();
                    }
                    catch (Exception)
                    {
                    }
                    return (new List<(string, string)>(), plan.Skipped,
                            new List<string> { string.Format("Revit would not keep the changes: {0}", err.Message) });
                }
            }
            var changed = plan.Changed.Where(p => !failed.Contains(p.Sheet)).ToList();
            return (changed, plan.Skipped, errors);
        }

        internal static string SheetLabel(ViewSheet sheet, string fallback)
        {
            try
            {
                string number = sheet.SheetNumber ?? "";
                return number.Length > 0 ? number : fallback;
            }
            catch (Exception)
            {
                return fallback ?? "";
            }
        }
    }
}
