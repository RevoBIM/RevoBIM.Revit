using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.HangerAutomation
{
    // =====================================================================================================
    // Hanger Automation - Hanger Service Type Assigner: everything that touches Revit.
    // Port of hsvc_revit.py.
    //
    // Jobs (through the window's ExternalEvent):
    //   ScanJob     (quiet) every hanger in the project - FAB hangers and MEP Ancillary Framing families -
    //               as plain records for the list (returns List<HangerRecord>)
    //   JobApply    rewrite each listed / selected hanger's Comments from the services it carries:
    //               'Pipe Types : Copper (SVP), 2xCable Tray with Fittings : Ladder (LV)'   (returns JobResult)
    //   JobShow3d   the default 3D view, cropped to the selected hangers, those hangers and the services they
    //               carry isolated (temporary), the services see-through, each category its own colour (JobResult)
    //   JobReset3d  puts that 3D view back as it was (JobResult)
    //
    // Which services a hanger carries:
    //   - a FAB hanger: its fabrication host;
    //   - a family hanger / support: every pipe, duct, cable tray or FAB straight whose centreline passes it
    //     inside its box, resting on its bar (the bearer of a hanger at its reference; the first bar of a
    //     floor support), or running through its ring (Circular System Based families) - see HsvcCore.Carried.
    //
    // The hanger ids the window hands to the jobs travel in the settings (a string dictionary) under
    // SvcIdsKey ("_svc_ids") as a comma-separated list of element ids: EncodeIds / ParseIds.
    // =====================================================================================================
    public static class HsvcRevit
    {
        public const double MM = FhaCore.MM;
        public static readonly string[] HangerCats = { "OST_FabricationHangers", "OST_MEPAncillaryFraming" };
        public static readonly string[] ServiceCats = { "OST_DuctCurves", "OST_PipeCurves", "OST_CableTray", "OST_Conduit" };
        public const string ViewName = "Hanger Automation - hanger check";
        public const double BoxPadMm = 1000.0;
        public const int SeeThrough = 60;

        /// <summary>The settings key the window's extra callback fills with EncodeIds(ids) (Python settings['_svc_ids'], a list).</summary>
        public const string SvcIdsKey = "_svc_ids";

        /// <summary>The Python list of ids as the one string a settings dictionary can hold.</summary>
        public static string EncodeIds(IEnumerable<long> ids)
        {
            return string.Join(",", (ids ?? new long[0]).Select(i => i.ToString(CultureInfo.InvariantCulture)));
        }

        /// <summary>EncodeIds read back (blank / unreadable parts are dropped).</summary>
        public static List<long> ParseIds(string text)
        {
            var o = new List<long>();
            if (string.IsNullOrEmpty(text)) return o;
            foreach (string part in text.Split(','))
            {
                long k;
                if (long.TryParse(part.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out k)) o.Add(k);
            }
            return o;
        }

        /// <summary>What the last Show in 3D changed, so Reset 3D can put it back (kept for the Revit session: the
        /// add-in stays loaded). Python _SHOWN = {'view', 'box', 'box_on', 'overrides'}.</summary>
        public sealed class ShownState
        {
            public long? View;
            public BoundingBoxXYZ Box;
            public bool? BoxOn;
            public Dictionary<long, OverrideGraphicSettings> Overrides = new Dictionary<long, OverrideGraphicSettings>();

            public void Clear()
            {
                View = null;
                Box = null;
                BoxOn = null;
                Overrides = new Dictionary<long, OverrideGraphicSettings>();
            }
        }

        public static readonly ShownState Shown = new ShownState();

        // ================================================================ the list
        public static bool IsFabHanger(Element el)
        {
            return el is FabricationPart && FhaRevit.IsHanger(el);
        }

        public static List<Element> HangerElements(Document doc)
        {
            var o = new List<Element>();
            var seen = new HashSet<long>();
            foreach (string name in HangerCats)
            {
                try
                {
                    FilteredElementCollector col = new FilteredElementCollector(doc).OfCategory(FhaRevit.Bic(name)).WhereElementIsNotElementType();
                    foreach (Element e in col)
                    {
                        long k = FhaRevit.EidValue(e.Id);
                        if (seen.Add(k)) o.Add(e);
                    }
                }
                catch (Exception) { }
            }
            return o;
        }

        private static string ValueString(Element el, string bipName)
        {
            try
            {
                BuiltInParameter? b = FhaRevit.Bip(bipName);
                Parameter p = b == null ? null : el.get_Parameter(b.Value);
                if (p != null)
                {
                    string s = p.AsValueString();
                    if (string.IsNullOrEmpty(s)) s = p.AsString();
                    if (string.IsNullOrEmpty(s)) s = "";
                    return s.Trim();
                }
            }
            catch (Exception) { }
            return "";
        }

        /// <summary>(family, type) as the list shows them; a FAB hanger by its part.</summary>
        public static void FamilyAndType(Element el, out string family, out string type)
        {
            if (el is FabricationPart)
            {
                string product = "";
                try { product = ((FabricationPart)el).ProductName; }
                catch (Exception) { }
                family = FhaCore.FirstText(new[] { ValueString(el, "ELEM_FAMILY_PARAM"), "FAB Hanger" });
                type = FhaCore.FirstText(new[] { FhaRevit.ElName(el), product, ValueString(el, "ELEM_TYPE_PARAM") });
                return;
            }
            try
            {
                FamilyInstance fi = el as FamilyInstance;
                if (fi != null)
                {
                    FamilySymbol sym = fi.Symbol;
                    family = FhaRevit.ElName(sym.Family);
                    type = FhaRevit.ElName(sym);
                    return;
                }
            }
            catch (Exception) { }
            family = ValueString(el, "ELEM_FAMILY_PARAM");
            type = ValueString(el, "ELEM_TYPE_PARAM");
        }

        public static string CommentsOf(Element el)
        {
            try
            {
                Parameter p = FhaRevit.ServiceParam(el);
                return p != null ? (p.AsString() ?? "") : "";
            }
            catch (Exception)
            {
                return "";
            }
        }

        public static string LevelName(Document doc, Element el)
        {
            try
            {
                V3? p = HfamRevit.InstancePoint(el);
                Level lv = HfamRevit.ElementLevel(doc, el, p != null ? (double?)p.Value.Z : null);
                return lv != null ? FhaRevit.ElName(lv) : "";
            }
            catch (Exception)
            {
                return "";
            }
        }

        public static HangerRecord RecordOf(Document doc, Element el)
        {
            string fam, typ;
            FamilyAndType(el, out fam, out typ);
            return new HangerRecord
            {
                Id = FhaRevit.EidValue(el.Id),
                Family = fam,
                Type = typ,
                Level = LevelName(doc, el),
                Comments = CommentsOf(el),
                Cat = IsFabHanger(el) ? "fab" : "framing",
            };
        }

        /// <summary>(quiet) Every hanger in the project as a plain record. Returns List&lt;HangerRecord&gt;.</summary>
        public static object ScanJob(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            HaCache.Reset();   // does not go through HfamRevit.LogContext: levels may have changed since the last job
            List<Element> all = HangerElements(doc);
            ParamNames = TextInstanceParams(all);
            return all.Select(e => RecordOf(doc, e)).ToList();
        }

        /// <summary>The writable text instance parameters the project's hangers carry, for the "Write to" list (read after the scan).</summary>
        public static List<string> ParamNames = new List<string>();

        public static List<string> TextInstanceParams(IEnumerable<Element> hangers)
        {
            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var seenTypes = new HashSet<string>();
            foreach (Element e in hangers)
            {
                try
                {
                    // the parameters are the same for every instance of a type: read one of each
                    string key = (e is FabricationPart ? "fab" : "fam") + "|" + FhaRevit.EidValue(e.GetTypeId()).ToString(CultureInfo.InvariantCulture);
                    if (!seenTypes.Add(key)) continue;
                    foreach (Parameter p in e.Parameters)
                    {
                        try
                        {
                            if (p.IsReadOnly || p.StorageType != StorageType.String || p.Definition == null) continue;
                            string n = p.Definition.Name;
                            if (!string.IsNullOrEmpty(n)) names.Add(n);
                        }
                        catch (Exception) { }
                    }
                }
                catch (Exception) { }
            }
            names.Add("Comments");
            var list = names.Where(n => n != "Comments").OrderBy(n => n, StringComparer.OrdinalIgnoreCase).ToList();
            list.Insert(0, "Comments");
            return list;
        }

        public static List<Element> ElementsOf(Document doc, IEnumerable<long> ids)
        {
            var o = new List<Element>();
            foreach (long k in ids ?? new long[0])
            {
                Element e = null;
                try { e = doc.GetElement(RevoBIM.Helpers.RevitCompat.Id(k)); }
                catch (Exception) { }
                if (e != null) o.Add(e);
            }
            return o;
        }

        // ================================================================ services carried
        /// <summary>Every straight a hanger can carry, read once and indexed by plan.</summary>
        public class Services
        {
            public PlanIndex<ServiceRec> Index = new PlanIndex<ServiceRec>();
            public int N;

            public Services(Document doc, FhaDebugLog log)
            {
                var els = new List<Element>();
                foreach (string name in ServiceCats)
                {
                    try
                    {
                        FilteredElementCollector col = new FilteredElementCollector(doc).OfCategory(FhaRevit.Bic(name)).WhereElementIsNotElementType();
                        foreach (Element e in col)
                            if (HfamRevit.IsHostDuct(e)) els.Add(e);
                    }
                    catch (Exception ex)
                    {
                        log.Add("services " + name + ": " + ex.Message);
                    }
                }
                try
                {
                    foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FabricationPart)))
                        if (HfamRevit.IsHostDuct(e)) els.Add(e);
                }
                catch (Exception ex)
                {
                    log.Add("FAB services: " + ex.Message);
                }
                foreach (Element e in els)
                {
                    Section s;
                    try { s = HfamRevit.Section(e); }
                    catch (Exception) { continue; }
                    var rec = new ServiceRec { El = e, A = s.A, B = s.B, Width = s.Width, Depth = s.Depth, Ins = s.Ins };
                    Box b = HsvcCore.SegmentBox(s.A, s.B, Math.Max(s.Width, s.Depth) / 2.0 + rec.Ins);
                    Index.Add(rec, b.Lo, b.Hi);
                    N += 1;
                }
                log.Add("services read: " + N.ToString(CultureInfo.InvariantCulture));
            }
        }

        /// <summary>RuleFor's answer (the Python (rule, tol) / fam triple).</summary>
        public class RuleChoice
        {
            public CarryRule Rule;
            public double Tol;
            public string Fam = "";
        }

        /// <summary>(rule, tol) for a family hanger - see HsvcCore.Carried.</summary>
        public static RuleChoice RuleFor(Element h, Dictionary<string, FamConfig> fams, BoundingBoxXYZ bb, double tol)
        {
            V3? p = HfamRevit.InstancePoint(h);
            string fam = "";
            try { fam = FhaRevit.ElName(((FamilyInstance)h).Symbol.Family); }
            catch (Exception) { }
            if (fams.ContainsKey(fam))
            {
                FamConfig cfg = HfamCore.FamConfigFor(fams, fam);
                if (cfg.Get("style", null) == "circ")
                {
                    double dia = HfamRevit.GetLength(h, cfg.Get("dia", null)) ?? 0.0;
                    double up = HfamRevit.GetLength(h, cfg.Get("circ_height", null)) ?? 0.0;
                    return new RuleChoice { Rule = CarryRule.Ring(p.Value.Z + Math.Max(0.0, up), dia / 2.0), Tol = tol, Fam = fam };
                }
                double? fb = HfamRevit.GetLength(h, cfg.Get("first_bar", null));
                if (fb != null)
                    return new RuleChoice { Rule = CarryRule.Bar(p.Value.Z + fb.Value), Tol = tol, Fam = fam };   // a floor support's first bar
                return new RuleChoice { Rule = CarryRule.Bar(p.Value.Z), Tol = tol, Fam = fam };                 // a hanger's bearer, at its reference
            }
            return new RuleChoice { Rule = CarryRule.Bar(bb.Min.Z), Tol = tol + 100.0 / MM, Fam = fam };         // not set up: its lowest point
        }

        /// <summary>The services a hanger carries, in order across it.</summary>
        public static List<Element> CarriedServices(Document doc, Element h, Services svcs, Dictionary<string, FamConfig> fams, double tol, FhaDebugLog log)
        {
            if (IsFabHanger(h))
            {
                Element host = FhaRevit.HangerHost(doc, h);
                var one = new List<Element>();
                if (host != null) one.Add(host);
                return one;
            }
            BoundingBoxXYZ bb = h.get_BoundingBox(null);
            V3? p = HfamRevit.InstancePoint(h);
            if (bb == null || p == null) return new List<Element>();
            V3 lo = new V3(bb.Min.X, bb.Min.Y, bb.Min.Z), hi = new V3(bb.Max.X, bb.Max.Y, bb.Max.Z);
            RuleChoice rc = RuleFor(h, fams, bb, tol);
            CarryRule rule = rc.Rule;
            List<ServiceRec> near = svcs.Index.Near(lo, hi);
            List<ServiceRec> found = HsvcCore.Carried(new HangerBox(p.Value, lo, hi), near, rule, rc.Tol, 50.0 / MM);
            string labels = string.Join(", ", found.Select(s => FhaRevit.ServiceLabel(s.El)));
            log.Add("   " + (rc.Fam.Length > 0 ? rc.Fam : "?") + " " + FhaRevit.EidValue(h.Id).ToString(CultureInfo.InvariantCulture)
                + ": " + near.Count.ToString(CultureInfo.InvariantCulture) + " near, rule "
                + rule.Kind + " @ " + HfamRevit.Fmm(rule.Z) + " -> " + (labels.Length > 0 ? labels : "nothing"));
            return found.Select(s => s.El).ToList();
        }

        /// <summary>Write each hanger's Comments from the services it carries. Returns a JobResult.</summary>
        public static object JobApply(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            JobResult res = FhaRevit.NewResult("Apply associated service type to hanger");
            string idText;
            settings.TryGetValue(SvcIdsKey, out idText);
            List<Element> hangers = ElementsOf(doc, ParseIds(idText));
            if (hangers.Count == 0)
            {
                res.Lines.Add("No hangers to apply to.");
                return res;
            }
            Dictionary<string, FamConfig> fams = HfamCore.LoadFamilies();
            double tol = FhaCore.AsFloat(settings, "svc_tol", HsvcCore.RestTolMm) / MM;
            log.Add("apply service types to " + hangers.Count.ToString(CultureInfo.InvariantCulture) + " hangers, services resting within " + HfamRevit.Fmm(tol) + " mm");
            Services svcs = new Services(doc, log);
            FhaRevit.Checkout(doc, hangers, log);
            var nothing = new List<Element>();
            var written = new List<KeyValuePair<Element, string>>();
            TransactionGroup tg = new TransactionGroup(doc, "Hanger Automation - service types to hangers");
            tg.Start();
            try
            {
                Transaction t = FhaRevit.StartTxn(doc, "Hanger service types");
                try
                {
                    foreach (Element h in hangers)
                    {
                        List<Element> found = CarriedServices(doc, h, svcs, fams, tol, log);
                        if (found.Count == 0)
                        {
                            nothing.Add(h);
                            continue;
                        }
                        string text = FhaRevit.WriteServiceComment(h, found, log);
                        if (!string.IsNullOrEmpty(text)) written.Add(new KeyValuePair<Element, string>(h, text));
                        else res.Failed += 1;
                    }
                    if (!FhaRevit.Committed(t))
                    {
                        res.Failed += written.Count;
                        written = new List<KeyValuePair<Element, string>>();
                    }
                }
                catch (Exception ex)
                {
                    log.Add("apply: " + ex.Message);
                    FhaRevit.Rollback(t);
                    written = new List<KeyValuePair<Element, string>>();
                    res.Failed += 1;
                }
            }
            finally
            {
                tg.Assimilate();
            }
            foreach (KeyValuePair<Element, string> w in written)
            {
                if (CommentsOf(w.Key) == w.Value) res.Done += 1;
                else
                {
                    res.Failed += 1;
                    res.Lines.Add("Hanger " + FhaRevit.EidValue(w.Key.Id).ToString(CultureInfo.InvariantCulture) + ": Revit did not keep the new Comments (not owned?).");
                }
            }
            res.Skipped = nothing.Count;
            if (nothing.Count > 0)
            {
                res.Lines.Add(nothing.Count.ToString(CultureInfo.InvariantCulture) + " hanger" + (nothing.Count != 1 ? "s" : "")
                    + " carry nothing the tool could find - left alone: "
                    + string.Join(", ", nothing.Take(12).Select(h => FhaRevit.EidValue(h.Id).ToString(CultureInfo.InvariantCulture)))
                    + (nothing.Count > 12 ? " ..." : ""));
            }
            foreach (KeyValuePair<Element, string> w in written.Take(6))
                res.Lines.Add(FhaRevit.EidValue(w.Key.Id).ToString(CultureInfo.InvariantCulture) + ": " + w.Value);
            if (written.Count > 6)
                res.Lines.Add("... and " + (written.Count - 6).ToString(CultureInfo.InvariantCulture) + " more.");
            return res;
        }

        // ================================================================ the 3D check
        /// <summary>The user's default 3D view ({3D - name} / {3D}), else one of the tool's own. made = a view was created.
        /// Returns null when none could be found or made.</summary>
        public static View3D Default3d(Document doc, FhaDebugLog log, out bool made)
        {
            made = false;
            string user = "";
            try { user = doc.Application.Username ?? ""; }
            catch (Exception) { }
            var views = new List<View3D>();
            try
            {
                var tmp = new List<View3D>();
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(View3D)))
                {
                    View3D v = (View3D)e;
                    bool persp = false;
                    try { persp = v.IsPerspective; }
                    catch (Exception) { }
                    if (!v.IsTemplate && !persp) tmp.Add(v);
                }
                views = tmp;
            }
            catch (Exception) { }
            var byName = new Dictionary<string, View3D>(StringComparer.Ordinal);
            foreach (View3D v in views) byName[FhaRevit.ElName(v)] = v;
            foreach (string name in new[] { "{3D - " + user + "}", "{3D}", ViewName })
            {
                View3D hit;
                if (byName.TryGetValue(name, out hit)) return hit;
            }
            foreach (View3D v in views)
                if (FhaRevit.ElName(v).StartsWith("{3D", StringComparison.Ordinal)) return v;
            ViewFamilyType vft = null;
            try
            {
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(ViewFamilyType)))
                {
                    ViewFamilyType ty = (ViewFamilyType)e;
                    if (ty.ViewFamily == ViewFamily.ThreeDimensional)
                    {
                        vft = ty;
                        break;
                    }
                }
            }
            catch (Exception) { }
            if (vft == null) return null;
            Transaction t = FhaRevit.StartTxn(doc, "Hanger Automation - 3D view");
            try
            {
                View3D nv = View3D.CreateIsometric(doc, vft.Id);
                try { nv.Name = ViewName; }   // Revit does not allow braces in a name it did not make
                catch (Exception) { }
                if (FhaRevit.Committed(t))
                {
                    log.Add("made the 3D view \"" + FhaRevit.ElName(nv) + "\"");
                    made = true;
                    return nv;
                }
            }
            catch (Exception ex)
            {
                log.Add("3D view: " + ex.Message);
                FhaRevit.Rollback(t);
            }
            return null;
        }

        public static ElementId SolidFill(Document doc)
        {
            try
            {
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FillPatternElement)))
                {
                    FillPatternElement f = (FillPatternElement)e;
                    if (f.GetFillPattern().IsSolidFill) return f.Id;
                }
            }
            catch (Exception) { }
            return null;
        }

        public static OverrideGraphicSettings ColourOverrides(int[] colour, ElementId fillId, bool seeThrough)
        {
            var o = new OverrideGraphicSettings();
            Color c = new Color((byte)colour[0], (byte)colour[1], (byte)colour[2]);
            try { o.SetProjectionLineColor(c); }
            catch (Exception) { }
            try { o.SetSurfaceForegroundPatternColor(c); }
            catch (Exception) { }
            if (fillId != null)
            {
                try { o.SetSurfaceForegroundPatternId(fillId); }
                catch (Exception) { }
            }
            if (seeThrough)
            {
                try { o.SetSurfaceTransparency(SeeThrough); }
                catch (Exception) { }
            }
            return o;
        }

        private static Box BoxOf(Element el)
        {
            try
            {
                BoundingBoxXYZ bb = el.get_BoundingBox(null);
                return new Box(new V3(bb.Min.X, bb.Min.Y, bb.Min.Z), new V3(bb.Max.X, bb.Max.Y, bb.Max.Z));
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static List<ElementId> Ids(IEnumerable<Element> elements)
        {
            var ids = new List<ElementId>();
            foreach (Element e in elements) ids.Add(e.Id);
            return ids;
        }

        /// <summary>The default 3D view cropped to the selected hangers, with those and their services isolated and coloured. Returns a JobResult.</summary>
        public static object JobShow3d(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            JobResult res = FhaRevit.NewResult("Show hangers in the default 3D view");
            string idText;
            settings.TryGetValue(SvcIdsKey, out idText);
            List<Element> hangers = ElementsOf(doc, ParseIds(idText));
            if (hangers.Count == 0)
            {
                res.Lines.Add("Select one or more rows first.");
                return res;
            }
            Dictionary<string, FamConfig> fams = HfamCore.LoadFamilies();
            double tol = FhaCore.AsFloat(settings, "svc_tol", HsvcCore.RestTolMm) / MM;
            Services svcs = new Services(doc, log);
            var services = new List<Element>();
            var seen = new HashSet<long>();
            foreach (Element h in hangers)
            {
                foreach (Element s in CarriedServices(doc, h, svcs, fams, tol, log))
                {
                    if (seen.Add(FhaRevit.EidValue(s.Id))) services.Add(s);
                }
            }
            bool made;
            View3D view = Default3d(doc, log, out made);
            if (view == null)
            {
                res.Failed += 1;
                res.Lines.Add("No 3D view could be found or made.");
                return res;
            }
            Restore(doc, log);                       // a previous check in this session first
            try
            {
                if (FhaRevit.EidValue(uidoc.ActiveView.Id) != FhaRevit.EidValue(view.Id))
                    uidoc.ActiveView = view;         // outside any transaction
            }
            catch (Exception ex)
            {
                log.Add("open the 3D view: " + ex.Message);
            }
            Box box = HsvcCore.UnionBox(hangers.Select(h => BoxOf(h)).Where(b => b != null).ToList());
            ElementId fill = SolidFill(doc);
            var colours = new Dictionary<string, int[]>(StringComparer.Ordinal);
            var legend = new List<string>();
            Transaction t = FhaRevit.StartTxn(doc, "Hanger Automation - show hangers in 3D");
            try
            {
                Shown.View = FhaRevit.EidValue(view.Id);
                try
                {
                    Shown.BoxOn = view.IsSectionBoxActive;
                    Shown.Box = view.IsSectionBoxActive ? view.GetSectionBox() : null;
                }
                catch (Exception)
                {
                    Shown.BoxOn = null;
                    Shown.Box = null;
                }
                if (box != null)
                {
                    Box padded = HsvcCore.PadBox(box.Lo, box.Hi, BoxPadMm / MM);
                    BoundingBoxXYZ bb = new BoundingBoxXYZ();
                    bb.Min = FhaRevit.ToXyz(padded.Lo);
                    bb.Max = FhaRevit.ToXyz(padded.Hi);
                    try
                    {
                        view.SetSectionBox(bb);
                        view.IsSectionBoxActive = true;
                    }
                    catch (Exception ex)
                    {
                        log.Add("section box: " + ex.Message);
                    }
                }
                var overrides = new Dictionary<long, OverrideGraphicSettings>();
                var targets = new List<KeyValuePair<Element, bool>>();
                foreach (Element h in hangers) targets.Add(new KeyValuePair<Element, bool>(h, false));
                foreach (Element s in services) targets.Add(new KeyValuePair<Element, bool>(s, true));
                foreach (KeyValuePair<Element, bool> target in targets)
                {
                    Element el = target.Key;
                    bool see = target.Value;
                    string cat;
                    try { cat = el.Category.Name; }
                    catch (Exception) { cat = "?"; }
                    if (!colours.ContainsKey(cat))
                    {
                        colours[cat] = HsvcCore.ColourFor(colours.Count);
                        legend.Add(cat);
                    }
                    try
                    {
                        long k = FhaRevit.EidValue(el.Id);
                        overrides[k] = view.GetElementOverrides(el.Id);
                        view.SetElementOverrides(el.Id, ColourOverrides(colours[cat], fill, see));
                    }
                    catch (Exception ex)
                    {
                        log.Add("colour " + FhaRevit.EidValue(el.Id).ToString(CultureInfo.InvariantCulture) + ": " + ex.Message);
                    }
                }
                Shown.Overrides = overrides;
                var keep = new List<Element>(hangers);
                keep.AddRange(services);
                try
                {
                    keep.AddRange(new FilteredElementCollector(doc, view.Id).OfCategory(FhaRevit.Bic("OST_SectionBox")).ToElements());
                }
                catch (Exception) { }
                try
                {
                    view.IsolateElementsTemporary(Ids(keep));
                }
                catch (Exception ex)
                {
                    log.Add("isolate: " + ex.Message);
                }
                if (!FhaRevit.Committed(t))
                {
                    res.Failed += 1;
                    return res;
                }
            }
            catch (Exception ex)
            {
                log.Add("show 3D: " + ex.Message);
                FhaRevit.Rollback(t);
                res.Failed += 1;
                return res;
            }
            try
            {
                uidoc.RefreshActiveView();
                uidoc.Selection.SetElementIds(Ids(hangers));
            }
            catch (Exception) { }
            res.Done = hangers.Count;
            res.Lines.Add(hangers.Count.ToString(CultureInfo.InvariantCulture) + " hangers and " + services.Count.ToString(CultureInfo.InvariantCulture)
                + " services they carry, in \"" + FhaRevit.ElName(view) + "\" (temporary isolate; press Reset 3D to put the view back).");
            res.Lines.Add("Colours: " + string.Join(", ", legend.Select(c => c + " = " + ColourName(colours[c]))));
            return res;
        }

        public static readonly string[] ColourNames = { "blue", "green", "orange", "magenta", "cyan", "red", "violet", "olive", "yellow", "grey" };

        public static string ColourName(int[] rgb)
        {
            int i = HsvcCore.ColourIndex(rgb);
            if (i >= 0 && i < ColourNames.Length) return ColourNames[i];
            return "(" + string.Join(", ", (rgb ?? new int[0]).Select(c => c.ToString(CultureInfo.InvariantCulture))) + ")";
        }

        /// <summary>Put back what the last Show in 3D changed. Caller holds no transaction.</summary>
        private static bool Restore(Document doc, FhaDebugLog log)
        {
            if (Shown.View == null) return false;
            View3D view = null;
            foreach (Element v in ElementsOf(doc, new[] { Shown.View.Value }))
                view = v as View3D;
            if (view == null)
            {
                Shown.View = null;
                return false;
            }
            Transaction t = FhaRevit.StartTxn(doc, "Hanger Automation - reset 3D");
            bool ok;
            try
            {
                foreach (KeyValuePair<long, OverrideGraphicSettings> kv in Shown.Overrides ?? new Dictionary<long, OverrideGraphicSettings>())
                {
                    foreach (Element e in ElementsOf(doc, new[] { kv.Key }))
                    {
                        try { view.SetElementOverrides(e.Id, kv.Value); }
                        catch (Exception) { }
                    }
                }
                try { view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate); }
                catch (Exception) { }
                try
                {
                    if (Shown.Box != null) view.SetSectionBox(Shown.Box);
                    if (Shown.BoxOn != null) view.IsSectionBoxActive = Shown.BoxOn.Value;
                }
                catch (Exception) { }
                ok = FhaRevit.Committed(t);
            }
            catch (Exception ex)
            {
                log.Add("reset 3D: " + ex.Message);
                FhaRevit.Rollback(t);
                ok = false;
            }
            Shown.Clear();
            return ok;
        }

        /// <summary>Puts the 3D view back as it was. Returns a JobResult.</summary>
        public static object JobReset3d(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            JobResult res = FhaRevit.NewResult("Reset the 3D view");
            if (Restore(uidoc.Document, log))
            {
                res.Done = 1;
                try { uidoc.RefreshActiveView(); }
                catch (Exception) { }
                res.Lines.Add("The 3D view is back as it was: colours, section box and isolate.");
            }
            else
            {
                res.Lines.Add("Nothing to reset - no hanger check is showing.");
            }
            return res;
        }
    }
}
