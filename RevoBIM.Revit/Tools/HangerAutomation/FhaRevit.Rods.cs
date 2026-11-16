using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class FhaRevit
    {
        // ================================================================== rods
        /// <summary>(settings key, BuiltInCategory name) of the structure categories rods can run up to.</summary>
        public static readonly string[][] StructureKeys =
        {
            new[] { "ext_floors", "OST_Floors" },
            new[] { "ext_framing", "OST_StructuralFraming" },
            new[] { "ext_roofs", "OST_Roofs" },
        };

        /// <summary>Ray casts up to structure through a temporary, clean 3D view.
        ///
        /// A view the user owns may hide floors or have a section box, and a
        /// ReferenceIntersector only sees what its view shows, so a fresh isometric
        /// view is made inside the run's transaction group and deleted at the end.</summary>
        public class Soffit
        {
            public Document Doc;
            public FhaDebugLog Log;
            public View3D View;
            public ReferenceIntersector Ri;
            public bool Temp;
            public string Reason = "";

            public Soffit(Document doc, FhaSettings settings, FhaDebugLog log)
            {
                Doc = doc;
                Log = log;
                View = null;
                Ri = null;
                Temp = false;
                Reason = "";
                var cats = new List<BuiltInCategory>();
                foreach (string[] kn in StructureKeys)
                {
                    if (FhaCore.AsBool(settings, kn[0])) cats.Add(Bic(kn[1]));
                }
                if (cats.Count == 0)
                {
                    Reason = "no structure category ticked";
                    return;
                }
                Transaction t = StartTxn(doc, "Temporary 3D view");
                try
                {
                    ViewFamilyType vft = null;
                    foreach (ViewFamilyType v in new FilteredElementCollector(doc).OfClass(typeof(ViewFamilyType)))
                    {
                        if (v.ViewFamily.ToString() == "ThreeDimensional")
                        {
                            vft = v;
                            break;
                        }
                    }
                    View = View3D.CreateIsometric(doc, vft.Id);
                    try { View.ViewTemplateId = ElementId.InvalidElementId; }
                    catch (Exception) { }
                    try { View.IsSectionBoxActive = false; }
                    catch (Exception) { }
                    if (Committed(t))
                        Temp = true;
                    else
                        View = null;
                }
                catch (Exception ex)
                {
                    Rollback(t);
                    View = null;
                    log.Add("temporary 3D view: " + ex.Message);
                }
                if (View == null)
                {
                    foreach (View3D v in new FilteredElementCollector(doc).OfClass(typeof(View3D)))
                    {
                        if (!v.IsTemplate)
                        {
                            View = v;
                            log.Add("using existing 3D view " + ElName(v));
                            break;
                        }
                    }
                }
                if (View == null)
                {
                    Reason = "no 3D view to cast from";
                    return;
                }
                Ri = new ReferenceIntersector(new ElementMulticategoryFilter(cats), FindReferenceTarget.Face, View);
                try { Ri.FindReferencesInRevitLinks = true; }
                catch (Exception) { }
            }

            public bool Ok() { return Ri != null; }

            /// <summary>Z of the first structure face above (x, y, z), or null.</summary>
            public double? Above(double x, double y, double z)
            {
                try
                {
                    ReferenceWithContext hit = Ri.FindNearest(new XYZ(x, y, z), XYZ.BasisZ);
                    if (hit != null) return hit.GetReference().GlobalPoint.Z;
                }
                catch (Exception ex)
                {
                    Log.Add("ray: " + ex.Message);
                }
                return null;
            }

            public void Close()
            {
                if (View == null || !Temp) return;   // never delete a view this run did not make
                Transaction t = StartTxn(Doc, "Remove temporary 3D view");
                try
                {
                    Doc.Delete(View.Id);
                    Committed(t);
                }
                catch (Exception)
                {
                    Rollback(t);
                }
            }
        }

        /// <summary>Run every rod of one hanger up to the soffit above it.
        ///
        /// Returns "extended", "already", "attached" or "failed". Caller holds a
        /// transaction. Each rod is read back after a regenerate.</summary>
        public static string ExtendRods(Document doc, FabricationPart hanger, Soffit soffit, FhaDebugLog log, bool allowAttach = true)
        {
            FabricationRodInfo info;
            int n;
            try
            {
                info = hanger.GetRodInfo();
                n = info.RodCount;
            }
            catch (Exception ex)
            {
                log.Add("hanger " + Inv(EidValue(hanger.Id)) + ": no rod info (" + ex.Message + ")");
                return "failed";
            }
            if (n == 0) return "failed";
            double? baseZ = HangerBottomZ(hanger);
            try
            {
                if (info.CanRodsBeHosted) info.CanRodsBeHosted = false;   // SetRodLength refuses an auto-hosted hanger
            }
            catch (Exception) { }
            var targets = new Dictionary<int, KeyValuePair<double, double>>();
            int already = 0;
            for (int i = 0; i < n; i++)
            {
                try
                {
                    XYZ end = info.GetRodEndPosition(i);
                    // cast from under the hanger: a rod already pushed into the slab
                    // would otherwise see the slab's top face as the next soffit
                    double startZ = baseZ != null ? Math.Min(end.Z, baseZ.Value) - 0.05 : end.Z - 1.0;
                    double? hit = soffit.Ok() ? soffit.Above(end.X, end.Y, startZ) : null;
                    if (hit == null) continue;
                    double ext = 0.0;
                    try { ext = info.GetRodStructureExtension(i); }
                    catch (Exception) { }
                    if (FhaCore.RodOk(end.Z, hit.Value, ext, RodTol))
                    {
                        already++;
                        continue;
                    }
                    double target = FhaCore.RodTargetLength(info.GetRodLength(i), end.Z, hit.Value, ext);
                    if (target <= 0)
                    {
                        log.Add("hanger " + Inv(EidValue(hanger.Id)) + " rod " + i.ToString(CultureInfo.InvariantCulture) + ": soffit below rod start");
                        continue;
                    }
                    if (info.SetRodLength(i, target) == false)
                    {
                        log.Add("hanger " + Inv(EidValue(hanger.Id)) + " rod " + i.ToString(CultureInfo.InvariantCulture)
                                + ": SetRodLength refused " + Fmt(target * MM, 0) + " mm");
                        continue;
                    }
                    targets[i] = new KeyValuePair<double, double>(hit.Value, ext);
                }
                catch (Exception ex)
                {
                    log.Add("hanger " + Inv(EidValue(hanger.Id)) + " rod " + i.ToString(CultureInfo.InvariantCulture) + ": " + ex.Message);
                }
            }
            if (targets.Count > 0)
            {
                try { doc.Regenerate(); }
                catch (Exception) { }
                int good = 0;
                foreach (KeyValuePair<int, KeyValuePair<double, double>> kv in targets)
                {
                    try
                    {
                        if (FhaCore.RodOk(info.GetRodEndPosition(kv.Key).Z, kv.Value.Key, kv.Value.Value, RodTol * 5))
                            good++;
                    }
                    catch (Exception) { }
                }
                if (good > 0) return "extended";
            }
            if (already == n) return "already";
            if (allowAttach)
            {
                try
                {
                    info.AttachToStructure();
                    doc.Regenerate();
                    if (info.IsAttachedToStructure) return "attached";
                }
                catch (Exception ex)
                {
                    log.Add("hanger " + Inv(EidValue(hanger.Id)) + ": AttachToStructure " + ex.Message);
                }
            }
            return "failed";
        }
    }
}
