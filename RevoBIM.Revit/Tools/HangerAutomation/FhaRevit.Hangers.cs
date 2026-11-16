using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.HangerAutomation
{
    /// <summary>A hanger button in the loaded services (the Python (label, service_id, button) tuple).</summary>
    public class HangerButton
    {
        public string Label;
        public int ServiceId;
        public FabricationServiceButton Button;
    }

    /// <summary>The Python (label, button, condition index) answer of ButtonPicker.pick; Button is null when nothing was found.</summary>
    public class ButtonChoice
    {
        public string Label;
        public FabricationServiceButton Button;
        public int? Cond;
    }

    /// <summary>The Python (label, button, how) answer of HangerMatcher.button_for.</summary>
    public class MatchChoice
    {
        public string Label;
        public FabricationServiceButton Button;
        public string How;
    }

    /// <summary>A hanger's identity (hanger_signature): the core HangerSignature plus the service id used to pick candidate buttons.</summary>
    public class HangerSig : HangerSignature
    {
        public int? Service;
    }

    public static partial class FhaRevit
    {
        // ======================================================== hanger buttons
        /// <summary>[(label, service_id, button)] for every hanger button in the loaded services.</summary>
        public static List<HangerButton> HangerButtons(Document doc)
        {
            var o = new List<HangerButton>();
            try
            {
                FabricationConfiguration cfg = FabricationConfiguration.GetFabricationConfiguration(doc);
                if (cfg == null) return o;
                foreach (FabricationService svc in cfg.GetAllLoadedServices())
                {
                    try
                    {
                        for (int p = 0; p < svc.PaletteCount; p++)
                        {
                            for (int b = 0; b < svc.GetButtonCount(p); b++)
                            {
                                FabricationServiceButton btn = svc.GetButton(p, b);
                                if (btn != null && btn.IsAHanger)
                                    o.Add(new HangerButton { Label = svc.Name + " : " + btn.Name, ServiceId = svc.ServiceId, Button = btn });
                            }
                        }
                    }
                    catch (Exception) { continue; }
                }
            }
            catch (Exception) { }
            return o;
        }

        /// <summary>The size hanger conditions are keyed on: width, else diameter, else largest.</summary>
        public static double DuctSizeFt(FabricationPart el)
        {
            var vals = new Dictionary<string, double>();
            try
            {
                foreach (FabricationDimensionDefinition d in el.GetDimensions())
                {
                    try { vals[(d.Name ?? "").Trim().ToLowerInvariant()] = el.GetDimensionValue(d); }
                    catch (Exception) { }
                }
            }
            catch (Exception) { }
            foreach (string k in new[] { "width", "diameter", "main width", "main diameter" })
            {
                double v;
                if (vals.TryGetValue(k, out v) && v > 0) return v;
            }
            double m = 0.0;
            foreach (double v in vals.Values) if (v > m) m = v;
            return m;
        }

        /// <summary>[(index, lower, upper, unrestricted)] for a hanger button.</summary>
        public static List<Condition> ButtonConditions(FabricationServiceButton btn)
        {
            var conds = new List<Condition>();
            try
            {
                for (int i = 0; i < btn.ConditionCount; i++)
                {
                    bool unr;
                    try { unr = btn.IsUnrestrictedCondition(i); }
                    catch (Exception) { unr = false; }
                    conds.Add(new Condition(i, btn.GetConditionLowerValue(i), btn.GetConditionUpperValue(i), unr));
                }
            }
            catch (Exception) { }
            return conds;
        }

        /// <summary>(fits, condition index) - a button with no conditions fits anything.</summary>
        public static bool ConditionFor(FabricationServiceButton btn, double sizeFt, out int? idx)
        {
            List<Condition> conds = ButtonConditions(btn);
            if (conds.Count == 0)
            {
                idx = null;
                return true;
            }
            idx = FhaCore.PickCondition(conds, sizeFt);
            return idx != null;
        }

        /// <summary>Chooses the hanger button and condition for a duct, cached per size.</summary>
        public class ButtonPicker
        {
            public List<HangerButton> All;
            public string Wanted;
            public FhaDebugLog Log;
            private readonly Dictionary<string, ButtonChoice> _cache = new Dictionary<string, ButtonChoice>();

            public ButtonPicker(Document doc, string wanted, FhaDebugLog log)
            {
                All = HangerButtons(doc);
                Wanted = (wanted ?? "").Trim();
                Log = log;
            }

            private List<HangerButton> Candidates(int? serviceId)
            {
                if (Wanted.Length > 0)
                {
                    var exact = All.Where(b => b.Label == Wanted).ToList();
                    if (exact.Count > 0) return exact;
                    string low = Wanted.ToLowerInvariant();
                    var part = All.Where(b => b.Label.ToLowerInvariant().Contains(low)).ToList();
                    if (part.Count > 0) return part;
                    Log.Add("button \"" + Wanted + "\" not found, choosing automatically");
                }
                var same = All.Where(b => serviceId != null && b.ServiceId == serviceId.Value).ToList();
                return same.Count > 0 ? same : All;
            }

            public ButtonChoice Pick(FabricationPart host)
            {
                int? sid;
                try { sid = host.ServiceId; }
                catch (Exception) { sid = null; }
                double size = DuctSizeFt(host);
                string key = (sid == null ? "None" : sid.Value.ToString(CultureInfo.InvariantCulture)) + "|"
                             + Math.Round(size, 4, MidpointRounding.AwayFromZero).ToString("R", CultureInfo.InvariantCulture);
                ButtonChoice hit;
                if (_cache.TryGetValue(key, out hit)) return hit;
                var choice = new ButtonChoice { Label = null, Button = null, Cond = null };
                foreach (HangerButton hb in Candidates(sid))
                {
                    int? idx;
                    bool fits = ConditionFor(hb.Button, size, out idx);
                    if (fits)
                    {
                        choice = new ButtonChoice { Label = hb.Label, Button = hb.Button, Cond = idx };
                        break;
                    }
                    if (choice.Button == null)
                        choice = new ButtonChoice { Label = hb.Label, Button = hb.Button, Cond = null };   // keep looking for a better fit
                }
                Log.Add("button for " + Fmt(size * MM, 0) + " mm: " + NoneStr(choice.Label) + " condition "
                        + NoneStr(choice.Cond));
                _cache[key] = choice;
                return choice;
            }
        }

        // ================================================================ comments
        /// <summary>'Family : Type' of a service - a FAB part by its service and part name.</summary>
        public static string FamilyTypeLabel(Element el)
        {
            try
            {
                FabricationPart fp = el as FabricationPart;
                if (fp != null)
                {
                    string svc = (fp.ServiceName ?? "").Trim();
                    string name = (fp.Name ?? "").Trim();
                    if (svc.Length > 0 || name.Length > 0)
                        return string.Join(" : ", new[] { svc, name }.Where(x => x.Length > 0));
                }
            }
            catch (Exception) { }
            try
            {
                ElementType t = el.Document.GetElement(el.GetTypeId()) as ElementType;
                string fam = (t.FamilyName ?? "").Trim();
                string typ = ElName(t).Trim();
                if (fam.Length > 0 || typ.Length > 0)
                    return string.Join(" : ", new[] { fam, typ }.Where(x => x.Length > 0));
            }
            catch (Exception) { }
            try
            {
                Parameter p = el.get_Parameter(BuiltInParameter.ELEM_FAMILY_AND_TYPE_PARAM);
                string v = p != null ? p.AsValueString() : null;
                if (!string.IsNullOrEmpty(v)) return v.Replace(": ", " : ");
            }
            catch (Exception) { }
            return "";
        }

        private static string ParamText(Element el, string bipName = null, string name = null)
        {
            Parameter p = null;
            try
            {
                if (bipName != null)
                {
                    BuiltInParameter? bip = Bip(bipName);
                    if (bip != null) p = el.get_Parameter(bip.Value);
                }
                if (p == null && name != null) p = el.LookupParameter(name);
                if (p == null) return "";
                string v = p.AsString();
                if (string.IsNullOrEmpty(v)) v = p.AsValueString();
                return (v ?? "").Trim();
            }
            catch (Exception) { return ""; }
        }

        /// <summary>A FAB part's service type name from the fabrication configuration.</summary>
        private static string FabServiceType(FabricationPart el)
        {
            try
            {
                FabricationConfiguration cfg = FabricationConfiguration.GetFabricationConfiguration(el.Document);
                return (cfg.GetServiceTypeName(el.ServiceType) ?? "").Trim();
            }
            catch (Exception) { return ""; }
        }

        /// <summary>The service type abbreviation that follows a service's family and type
        /// in a hanger's Comments:
        ///   - pipes, ducts and their fittings: the system abbreviation (SVP, SA);
        ///   - cable trays and conduits: their Service Type (LV);
        ///   - FAB parts: the system abbreviation, else the fabrication service
        ///     abbreviation, else the service type from the fabrication configuration.</summary>
        public static string ServiceAbbreviation(Element el)
        {
            if (el == null) return "";
            Func<string> sysAbbr = () => ParamText(el, "RBS_SYSTEM_ABBREVIATION_PARAM", "System Abbreviation");
            var tries = new List<Func<string>>();
            FabricationPart fp = el as FabricationPart;
            if (fp != null)
            {
                tries.Add(sysAbbr);
                tries.Add(() => ParamText(el, "FABRICATION_SERVICE_ABBREVIATION", "Fabrication Service Abbreviation"));
                tries.Add(() =>
                {
                    // getattr(el, 'ServiceAbbreviation', u'') - by reflection, the member is not in every API version
                    System.Reflection.PropertyInfo pi = el.GetType().GetProperty("ServiceAbbreviation");
                    object v = pi != null ? pi.GetValue(el, null) : null;
                    return v == null ? "" : Convert.ToString(v, CultureInfo.InvariantCulture);
                });
                tries.Add(() => FabServiceType(fp));
            }
            else
            {
                tries.Add(sysAbbr);
                tries.Add(() => ParamText(el, "RBS_CTC_SERVICE_TYPE", "Service Type"));
                tries.Add(() => ParamText(el, "RBS_DUCT_PIPE_SYSTEM_ABBREVIATION_PARAM"));
            }
            foreach (Func<string> t in tries)
            {
                string v;
                try { v = t(); }
                catch (Exception) { v = ""; }
                if (!string.IsNullOrEmpty(v)) return v;
            }
            return "";
        }

        /// <summary>'Family : Type (ABBR)' for one service.</summary>
        public static string ServiceLabel(Element el)
        {
            return FhaCore.LabelWithAbbreviation(FamilyTypeLabel(el), ServiceAbbreviation(el));
        }

        public static string ServiceCommentText(IEnumerable<Element> services)
        {
            return FhaCore.ServiceComment(services.Where(s => s != null).Select(s => ServiceLabel(s)).ToList());
        }

        /// <summary>Write the family, type and service type abbreviation of the service(s)
        /// a hanger carries into its Comments ('2xCable Tray : Ladder (LV), Pipe Types
        /// : Copper (SVP)'). Caller holds the transaction. Returns the text written,
        /// or null.</summary>
        public static string WriteServiceComment(Element hanger, IEnumerable<Element> services, FhaDebugLog log)
        {
            if (hanger == null) return null;
            string text = ServiceCommentText(services);
            if (string.IsNullOrEmpty(text)) return null;
            try
            {
                Parameter p = hanger.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
                if (p == null || p.IsReadOnly)
                {
                    log.Add("   comments: no writable Comments parameter");
                    return null;
                }
                p.Set(text);
                log.Add("   comments: " + text);
                return text;
            }
            catch (Exception ex)
            {
                log.Add("   comments: " + ex.Message);
                return null;
            }
        }

        /// <summary>The service elements a hanger goes round: every service in a shared
        /// hanger (the section's 'keys'), else the one it hangs from.</summary>
        public static List<Element> ServicesOf(Document doc, IEnumerable<long> keys, Element fallback)
        {
            var o = new List<Element>();
            if (keys != null)
            {
                foreach (long k in keys)
                {
                    Element e = null;
                    try { e = doc.GetElement(new ElementId(k)); }
                    catch (Exception) { }
                    if (e != null) o.Add(e);
                }
            }
            if (o.Count == 0) o.Add(fallback);
            return o;
        }

        // ================================================================ hangers
        /// <summary>CreateHanger with the condition overload first, then without.</summary>
        public static FabricationPart CreateHanger(Document doc, FabricationServiceButton btn, int? cond, FabricationPart host, Connector conn, double distFt, FhaDebugLog log)
        {
            Exception last = null;
            for (int attempt = 0; attempt < 2; attempt++)
            {
                if (attempt == 0 && cond == null) continue;
                try
                {
                    FabricationPart h;
                    if (attempt == 0)
                        h = FabricationPart.CreateHanger(doc, btn, cond.Value, host.Id, conn, distFt, false);
                    else
                        h = FabricationPart.CreateHanger(doc, btn, host.Id, conn, distFt, false);
                    if (h != null)
                    {
                        WriteServiceComment(h, new Element[] { host }, log);
                        return h;
                    }
                }
                catch (Exception ex) { last = ex; }
            }
            log.Add("CreateHanger refused on " + Inv(EidValue(host.Id)) + ": " + (last == null ? "None" : last.Message));
            return null;
        }

        public static bool PlaceOnHost(FabricationPart hanger, FabricationPart host, Connector conn, double distFt, FhaDebugLog log)
        {
            FabricationHostedInfo info = hanger.GetHostedInfo();
            Exception last = null;
            foreach (bool disconnectFirst in new[] { false, true })
            {
                try
                {
                    if (disconnectFirst) info.DisconnectFromHost();
                    info.PlaceOnHost(host.Id, conn, distFt);
                    WriteServiceComment(hanger, new Element[] { host }, log);
                    return true;
                }
                catch (Exception ex) { last = ex; }
            }
            log.Add("PlaceOnHost refused for hanger " + Inv(EidValue(hanger.Id)) + ": " + (last == null ? "None" : last.Message));
            return false;
        }

        public static long HostOf(FabricationPart hanger)
        {
            try { return EidValue(hanger.GetHostedInfo().HostId); }
            catch (Exception) { return 0; }
        }

        /// <summary>Copy width / diameter / depth onto same-named hanger dimensions where they differ.</summary>
        public static int SizeToHost(FabricationPart hanger, FabricationPart host, FhaDebugLog log)
        {
            int changed = 0;
            try
            {
                var hd = new Dictionary<string, FabricationDimensionDefinition>();
                foreach (FabricationDimensionDefinition d in hanger.GetDimensions())
                    hd[(d.Name ?? "").Trim().ToLowerInvariant()] = d;
                foreach (FabricationDimensionDefinition d in host.GetDimensions())
                {
                    string k = (d.Name ?? "").Trim().ToLowerInvariant();
                    if (hd.ContainsKey(k) && (k == "width" || k == "diameter" || k == "depth" || k == "height"))
                    {
                        double v = host.GetDimensionValue(d);
                        try
                        {
                            if (Math.Abs(hanger.GetDimensionValue(hd[k]) - v) > 1e-6)
                            {
                                hanger.SetDimensionValue(hd[k], v);
                                changed++;
                            }
                        }
                        catch (Exception) { }
                    }
                }
            }
            catch (Exception ex)
            {
                log.Add("size_to_host: " + ex.Message);
            }
            return changed;
        }

        /// <summary>The hanger's origin, else the middle of its bounding box; null if neither is readable.</summary>
        public static V3? HangerPoint(Element h)
        {
            try { return PartOrigin((FabricationPart)h); }
            catch (Exception) { }
            try
            {
                BoundingBoxXYZ bb = h.get_BoundingBox(null);
                return new V3((bb.Min.X + bb.Max.X) / 2.0, (bb.Min.Y + bb.Max.Y) / 2.0, (bb.Min.Z + bb.Max.Z) / 2.0);
            }
            catch (Exception) { return null; }
        }

        public static double? HangerBottomZ(Element h)
        {
            try { return h.get_BoundingBox(null).Min.Z; }
            catch (Exception)
            {
                V3? p = HangerPoint(h);
                return p != null ? (double?)p.Value.Z : null;
            }
        }

        // ===================================================== replacing a hanger
        /// <summary>What identifies the kind of hanger, size aside.</summary>
        public static HangerSig HangerSignatureOf(FabricationPart h)
        {
            var sig = new HangerSig { Name = ElName(h) };
            try { sig.Product = h.ProductName; } catch (Exception) { }
            try { sig.Alias = h.Alias; } catch (Exception) { }
            try
            {
                int id = h.ItemCustomId;
                sig.ItemId = id != 0 ? id.ToString(CultureInfo.InvariantCulture) : null;   // 0 is falsy in the Python
            }
            catch (Exception) { }
            try { sig.Code = h.ProductCode; } catch (Exception) { }
            try { sig.Service = h.ServiceId; } catch (Exception) { }
            return sig;
        }

        /// <summary>Finds the hanger button that makes the same kind of hanger as an existing one.
        ///
        /// Revit does not say which button a hanger came from, so each candidate button
        /// in the hanger's own service is tried for real inside a SubTransaction that is
        /// rolled back, and the result compared with the old hanger (item id, product,
        /// size-free name words). The answer is cached per kind of hanger.</summary>
        public class HangerMatcher
        {
            public const int MaxProbes = 16;
            public Document Doc;
            public FhaDebugLog Log;
            public ButtonPicker Picker;
            private readonly Dictionary<string, MatchChoice> _cache = new Dictionary<string, MatchChoice>();

            public HangerMatcher(Document doc, string wanted, FhaDebugLog log)
            {
                Doc = doc;
                Log = log;
                Picker = new ButtonPicker(doc, wanted, log);
            }

            private HangerSig Probe(FabricationServiceButton btn, FabricationPart host, Connector conn, double dist)
            {
                double size = DuctSizeFt(host);
                int? cond;
                bool fits = ConditionFor(btn, size, out cond);
                if (!fits) return null;
                SubTransaction st = new SubTransaction(Doc);
                st.Start();
                try
                {
                    FabricationPart h = CreateHanger(Doc, btn, cond, host, conn, dist, Log);
                    return h != null ? HangerSignatureOf(h) : null;
                }
                catch (Exception) { return null; }
                finally
                {
                    try { st.RollBack(); }
                    catch (Exception) { }
                }
            }

            /// <summary>(label, button, how) for re-creating `old` on `host`.</summary>
            public MatchChoice ButtonFor(FabricationPart old, FabricationPart host, Connector conn, double dist)
            {
                HangerSig sig = HangerSignatureOf(old);
                string key = NoneStr(sig.Service) + "|" + NoneStr(sig.ItemId) + "|" + NoneStr(sig.Product) + "|"
                             + string.Join(",", FhaCore.NameTokens(sig.Name).OrderBy(x => x, StringComparer.Ordinal));
                MatchChoice cached;
                if (_cache.TryGetValue(key, out cached)) return cached;
                var same = Picker.All.Where(b => sig.Service != null && b.ServiceId == sig.Service.Value).ToList();
                MatchChoice choice = null;
                if (same.Count == 1)
                {
                    choice = new MatchChoice { Label = same[0].Label, Button = same[0].Button, How = "only hanger button in its service" };
                }
                else if (same.Count > 0)
                {
                    bool have = false;
                    double bestScore = 0; string bestLabel = null; FabricationServiceButton bestBtn = null;
                    foreach (HangerButton hb in same.Take(MaxProbes))
                    {
                        HangerSig got = Probe(hb.Button, host, conn, dist);
                        if (got == null) continue;
                        double score = FhaCore.SignatureScore(sig, got);
                        Log.Add("  probe " + hb.Label + ": score " + Fmt(score, 2));
                        if (!have || score > bestScore)
                        {
                            have = true; bestScore = score; bestLabel = hb.Label; bestBtn = hb.Button;
                        }
                    }
                    if (have && bestScore > 0)
                        choice = new MatchChoice { Label = bestLabel, Button = bestBtn, How = "matched to the existing hanger (" + Fmt(bestScore, 1) + ")" };
                }
                if (choice == null)
                {
                    ButtonChoice pk = Picker.Pick(host);
                    if (pk.Button != null)
                        choice = new MatchChoice { Label = pk.Label, Button = pk.Button, How = "no match - automatic choice for the duct" };
                }
                if (choice == null)
                    choice = new MatchChoice { Label = null, Button = null, How = "no hanger buttons loaded" };
                Log.Add("hanger " + Inv(EidValue(old.Id)) + " (" + sig.Name + ") -> " + NoneStr(choice.Label) + ": " + choice.How);
                _cache[key] = choice;
                return choice;
            }
        }

        public static readonly string[] UserParams = { "Comments", "Mark" };

        /// <summary>Comments, Mark and every writable shared parameter, old -> new.</summary>
        public static int CopyUserParams(Element old, Element nw, FhaDebugLog log)
        {
            int copied = 0;
            List<Parameter> pars = new List<Parameter>();
            try
            {
                foreach (Parameter p in old.Parameters) pars.Add(p);
            }
            catch (Exception) { pars = new List<Parameter>(); }
            foreach (Parameter p in pars)
            {
                try
                {
                    if (p.IsReadOnly || !p.HasValue) continue;
                    string name = p.Definition.Name;
                    bool shared = false;
                    try { shared = p.IsShared; }
                    catch (Exception) { }
                    if (!shared && Array.IndexOf(UserParams, name) < 0) continue;
                    Parameter q = shared ? nw.get_Parameter(p.GUID) : nw.LookupParameter(name);
                    if (q == null || q.IsReadOnly) continue;
                    string kind = p.StorageType.ToString();
                    if (kind == "String") q.Set(p.AsString() ?? "");
                    else if (kind == "Integer") q.Set(p.AsInteger());
                    else if (kind == "Double") q.Set(p.AsDouble());
                    else continue;
                    copied++;
                }
                catch (Exception ex)
                {
                    log.Add("copy parameter: " + ex.Message);
                }
            }
            return copied;
        }

        public static void CopyWorkset(Element old, Element nw)
        {
            try
            {
                Parameter p = nw.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM);
                if (p != null && !p.IsReadOnly) p.Set(WsInt(old.WorksetId));
            }
            catch (Exception) { }
        }

        public static List<double> RodTops(FabricationPart h)
        {
            try
            {
                FabricationRodInfo info = h.GetRodInfo();
                var o = new List<double>();
                for (int i = 0; i < info.RodCount; i++) o.Add(info.GetRodEndPosition(i).Z);
                return o;
            }
            catch (Exception) { return new List<double>(); }
        }

        /// <summary>Give a new hanger's rods the old hanger's top levels (before any extend).</summary>
        public static void SetRodTops(Document doc, FabricationPart h, List<double> tops, FhaDebugLog log)
        {
            if (tops == null || tops.Count == 0) return;
            try
            {
                FabricationRodInfo info = h.GetRodInfo();
                try { info.CanRodsBeHosted = false; }
                catch (Exception) { }
                int n = Math.Min(info.RodCount, tops.Count);
                for (int i = 0; i < n; i++)
                {
                    XYZ end = info.GetRodEndPosition(i);
                    double target = FhaCore.RodTargetLength(info.GetRodLength(i), end.Z, tops[i], 0.0);
                    if (target > 0) info.SetRodLength(i, target);
                }
                doc.Regenerate();
            }
            catch (Exception ex)
            {
                log.Add("rod tops: " + ex.Message);
            }
        }

        /// <summary>Delete `old` and place a new hanger on `host`, exactly as a fresh
        /// placement would - same kind of hanger, condition and size from the duct -
        /// keeping its workset, Comments, Mark, shared parameters and rod tops.
        /// Caller holds the transaction. Returns the new hanger (or null) and the note.</summary>
        public static FabricationPart ReplaceHanger(Document doc, FabricationPart old, FabricationPart host, Connector conn, double dist, HangerMatcher matcher, FhaDebugLog log, Worksets ws, out string note)
        {
            MatchChoice m = matcher.ButtonFor(old, host, conn, dist);
            if (m.Button == null)
            {
                note = m.How;
                return null;
            }
            int? cond;
            ConditionFor(m.Button, DuctSizeFt(host), out cond);
            List<double> tops = RodTops(old);
            FabricationPart nw = CreateHanger(doc, m.Button, cond, host, conn, dist, log);
            if (nw == null)
            {
                note = "Revit refused to create " + NoneStr(m.Label) + " here";
                return null;
            }
            if (ws != null) ws.Apply(nw, host, true, old);
            else CopyWorkset(old, nw);
            CopyUserParams(old, nw, log);
            doc.Delete(old.Id);
            SetRodTops(doc, nw, tops, log);
            note = m.Label + " (" + m.How + ")";
            return nw;
        }
    }
}
