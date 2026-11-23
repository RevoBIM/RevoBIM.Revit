using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
        // ---------------------------------------------------------------- replay (always rolled back)
        private static void InsReplay(Document doc, View active, List<InsDim> found, FhaDebugLog log, InsTally tally)
        {
            var two = found.Where(d => d.Refs.Count == 2).Take(8).ToList();
            if (two.Count == 0)
            {
                log.Add("inspect: replay skipped - no alignment/dimension with exactly two references");
                return;
            }
            Transaction tr = new Transaction(doc, "Hanger Automation - inspect lock (replay, rolled back)");
            try { tr.Start(); }
            catch (Exception ex)
            {
                log.Add("inspect: replay skipped - the transaction could not start: " + InsEx(ex));
                return;
            }
            tally.Ran = true;
            try
            {
                foreach (InsDim di in two)
                {
                    Dimension d = di.D;
                    var views = new List<KeyValuePair<string, View>>();
                    try
                    {
                        View ov = doc.GetElement(d.OwnerViewId) as View;
                        if (ov != null && !ov.IsTemplate) views.Add(new KeyValuePair<string, View>("owner view \"" + ElName(ov) + "\"", ov));
                    }
                    catch (Exception) { }
                    if (active is ViewPlan && !views.Any(v => Eid(v.Value.Id) == Eid(active.Id)))
                        views.Add(new KeyValuePair<string, View>("active plan \"" + ElName(active) + "\"", active));
                    string s0 = InsStable(doc, di.Refs[0]), s1 = InsStable(doc, di.Refs[1]);
                    log.Add("inspect: REPLAY of dimension " + Inv(Eid(d.Id)) + " in " + Inv(views.Count) + " view(s); refs " + (s0 ?? "?") + "  &  " + (s1 ?? "?"));
                    foreach (bool removed in new[] { false, true })
                    {
                        foreach (KeyValuePair<string, View> vk in views)
                        {
                            foreach (bool swap in new[] { false, true })
                            {
                                foreach (bool parsed in new[] { false, true })
                                {
                                    string outcome = InsTry(doc, d, vk.Value, di.Refs[swap ? 1 : 0], di.Refs[swap ? 0 : 1], swap ? s1 : s0, swap ? s0 : s1, parsed, removed, out bool ok);
                                    if (removed)
                                    {
                                        if (parsed) { tally.RemovedParsedAttempts++; if (ok) tally.RemovedParsedOk++; }
                                        else { tally.RemovedObjAttempts++; if (ok) tally.RemovedObjOk++; }
                                    }
                                    else if (parsed) { tally.ParsedAttempts++; if (ok) tally.ParsedOk++; }
                                    else { tally.ObjAttempts++; if (ok) tally.ObjOk++; }
                                    log.Add("inspect:   NewAlignment(" + vk.Key + ", " + (swap ? "ref1, ref0" : "ref0, ref1") + ", " + (parsed ? "re-parsed from stable text" : "the existing reference objects")
                                            + (removed ? ", original removed first" : ", original still present") + "): " + outcome);
                                }
                            }
                        }
                    }
                }
            }
            finally
            {
                try
                {
                    if (tr.GetStatus() == TransactionStatus.Started) tr.RollBack();
                }
                catch (Exception) { }
            }
            log.Add("inspect: replay rolled back (the model is unchanged)");
        }

        private static string InsTry(Document doc, Dimension original, View view, Reference a, Reference b, string sa, string sb, bool parsed, bool removed, out bool ok)
        {
            ok = false;
            SubTransaction st = new SubTransaction(doc);
            try { st.Start(); }
            catch (Exception ex) { return "sub-transaction could not start: " + InsEx(ex); }
            try
            {
                if (removed)
                {
                    try { doc.Delete(original.Id); }
                    catch (Exception ex) { return "could not remove the original first: " + InsEx(ex); }
                }
                Reference ra = a, rb = b;
                if (parsed)
                {
                    try
                    {
                        ra = Reference.ParseFromStableRepresentation(doc, sa);
                        rb = Reference.ParseFromStableRepresentation(doc, sb);
                    }
                    catch (Exception ex) { return "re-parsing the stable text failed: " + InsEx(ex); }
                    if (ra == null || rb == null) return "re-parsing the stable text gave null";
                }
                try
                {
                    Dimension nd = doc.Create.NewAlignment(view, ra, rb);
                    ok = nd != null;
                    return nd != null ? "OK, accepted (new element " + Inv(Eid(nd.Id)) + ", rolled back)" : "returned null";
                }
                catch (Exception ex) { return "REFUSED " + InsEx(ex); }
            }
            finally
            {
                try { st.RollBack(); }
                catch (Exception) { }
            }
        }
    }
}
