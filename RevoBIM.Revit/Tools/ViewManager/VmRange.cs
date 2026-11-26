using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using RevoBIM.Helpers;

namespace RevoBIM.Tools.ViewManager
{
    /// <summary>
    /// View Manager - the View Range tab: every plan view's view range (top, cut plane, bottom and view depth, each a level
    /// and an offset) as rows, read in the project's length unit and written back one view at a time.
    /// </summary>
    public static class VmRange
    {
        public const string KeyTop = "rtop", KeyTopOff = "rtopo", KeyCut = "rcut", KeyCutOff = "rcuto",
                            KeyBot = "rbot", KeyBotOff = "rboto", KeyDep = "rdep", KeyDepOff = "rdepo";

        public const string Unlimited = "Unlimited", LevelAbove = "Level Above", LevelBelow = "Level Below";

        public static readonly VmCore.Field FieldName = new VmCore.Field("name", "View Name", "name", false, 280);
        public static readonly VmCore.Field FieldType = new VmCore.Field("vtype", "View Type", "vtype", false, 140);
        public static readonly VmCore.Field FieldTop = new VmCore.Field(KeyTop, "Top Level", "range", true, 130) { Dropdown = true };
        public static readonly VmCore.Field FieldTopOff = new VmCore.Field(KeyTopOff, "Top Offset", "range", true, 100) { Numeric = true };
        public static readonly VmCore.Field FieldCut = new VmCore.Field(KeyCut, "Cut Plane Level", "range", false, 130) { Dropdown = true };
        public static readonly VmCore.Field FieldCutOff = new VmCore.Field(KeyCutOff, "Cut Plane Offset", "range", true, 120) { Numeric = true };
        public static readonly VmCore.Field FieldBot = new VmCore.Field(KeyBot, "Bottom Level", "range", true, 130) { Dropdown = true };
        public static readonly VmCore.Field FieldBotOff = new VmCore.Field(KeyBotOff, "Bottom Offset", "range", true, 110) { Numeric = true };
        public static readonly VmCore.Field FieldDep = new VmCore.Field(KeyDep, "Depth Level", "range", true, 130) { Dropdown = true };
        public static readonly VmCore.Field FieldDepOff = new VmCore.Field(KeyDepOff, "Depth Offset", "range", true, 110) { Numeric = true };

        public static readonly VmCore.Field[] DefaultFields =
        {
            FieldName, FieldType, FieldTop, FieldTopOff, FieldCut, FieldCutOff, FieldBot, FieldBotOff, FieldDep, FieldDepOff,
        };

        /// <summary>The columns that cannot be removed.</summary>
        public static bool IsDefault(string key) { return DefaultFields.Any(f => f.Key == key); }

        /// <summary>level key, offset key, plane, label for one of the four planes.</summary>
        public sealed class PlaneInfo
        {
            public string LevelKey, OffsetKey, Label;
            public PlanViewPlane Plane;
        }

        public static readonly PlaneInfo[] Planes =
        {
            new PlaneInfo { LevelKey = KeyTop, OffsetKey = KeyTopOff, Plane = PlanViewPlane.TopClipPlane, Label = "Top" },
            new PlaneInfo { LevelKey = KeyCut, OffsetKey = KeyCutOff, Plane = PlanViewPlane.CutPlane, Label = "Cut Plane" },
            new PlaneInfo { LevelKey = KeyBot, OffsetKey = KeyBotOff, Plane = PlanViewPlane.BottomClipPlane, Label = "Bottom" },
            new PlaneInfo { LevelKey = KeyDep, OffsetKey = KeyDepOff, Plane = PlanViewPlane.ViewDepthPlane, Label = "View Depth" },
        };

        // ---------------------------------------------------------------- units --

        public static ForgeTypeId LengthUnit(Document doc)
        {
            try { return doc.GetUnits().GetFormatOptions(SpecTypeId.Length).GetUnitTypeId(); }
            catch (Exception) { return UnitTypeId.Millimeters; }
        }

        public static string UnitLabel(Document doc)
        {
            try
            {
                ForgeTypeId u = LengthUnit(doc);
                if (u == UnitTypeId.Millimeters) return "mm";
                if (u == UnitTypeId.Meters) return "m";
                if (u == UnitTypeId.Centimeters) return "cm";
                if (u == UnitTypeId.Feet) return "ft";
                if (u == UnitTypeId.Inches) return "in";
                if (u == UnitTypeId.FeetFractionalInches) return "ft";
                if (u == UnitTypeId.FractionalInches) return "in";
            }
            catch (Exception) { }
            return "";
        }

        public static string FormatOffset(Document doc, double feet)
        {
            double v = UnitUtils.ConvertFromInternalUnits(feet, LengthUnit(doc));
            if (Math.Abs(v) < 0.0005) v = 0;
            return v.ToString("0.###", CultureInfo.InvariantCulture);
        }

        public static bool TryParseOffset(string text, out double number)
        {
            return double.TryParse((text ?? "").Trim().Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out number);
        }

        /// <summary>A reason an offset cell cannot take this text, or "".</summary>
        public static string ValidateCell(string key, string text)
        {
            if (key == KeyTopOff || key == KeyCutOff || key == KeyBotOff || key == KeyDepOff)
            {
                double n;
                if (!TryParseOffset(text, out n)) return "'" + text + "' is not a number.";
            }
            return "";
        }

        // ---------------------------------------------------------------- reading --

        private static string LevelLabel(ElementId id, Dictionary<long, string> names)
        {
            if (id == null) return "";
            if (id.Equals(PlanViewRange.Unlimited)) return Unlimited;
            if (id.Equals(PlanViewRange.LevelAbove)) return LevelAbove;
            if (id.Equals(PlanViewRange.LevelBelow)) return LevelBelow;
            string name;
            return names.TryGetValue(id.Value, out name) ? name : "";
        }

        public static List<string> LevelChoices(Document doc)
        {
            var list = new List<string> { Unlimited, LevelAbove, LevelBelow };
            list.AddRange(VmRevit.CollectLevels(doc).Select(l => l.Name));
            return list;
        }

        /// <summary>The plan views, with their view range as text. Custom parameters are read as on the other tabs.</summary>
        public static List<VmCore.RefRow> ReadRows(Document doc, IEnumerable<string> extraNames, List<string> log, out Dictionary<string, List<string>> choices)
        {
            List<string> extras = extraNames == null ? new List<string>() : extraNames.ToList();
            var names = new Dictionary<long, string>();
            foreach (Level l in VmRevit.CollectLevels(doc)) names[l.Id.Value] = l.Name;
            List<string> levels = LevelChoices(doc);
            choices = new Dictionary<string, List<string>> { { KeyTop, levels }, { KeyBot, levels }, { KeyDep, levels }, { KeyCut, levels } };

            var rows = new List<VmCore.RefRow>();
            var templateControls = new Dictionary<long, bool>();
            int skipped = 0;
            foreach (ViewPlan v in new FilteredElementCollector(doc).OfClass(typeof(ViewPlan)).Cast<ViewPlan>())
            {
                PlanViewRange range;
                string typeName;
                try
                {
                    if (v.IsTemplate) continue;
                    typeName = v.ViewType.ToString();
                    if (Array.IndexOf(VmCore.ExcludedViewTypes, typeName) >= 0) continue;
                    range = v.GetViewRange();
                }
                catch (Exception)
                {
                    skipped++;
                    continue;
                }
                var row = new VmCore.RefRow(VmRevit.Key(v), typeName);
                row.Values["name"] = VmCore.CleanValue(v.Name);
                row.Values["vtype"] = row.TypeLabel;
                row.Values["vid"] = row.ViewId.ToString();
                row.Values["level"] = VmRevit.LevelText(v);
                try
                {
                    foreach (PlaneInfo p in Planes)
                    {
                        ElementId lid = range.GetLevelId(p.Plane);
                        string label = LevelLabel(lid, names);
                        row.Values[p.LevelKey] = label;
                        row.Values[p.OffsetKey] = FormatOffset(doc, range.GetOffset(p.Plane));
                        if (label == Unlimited) row.Locked[p.OffsetKey] = "An unlimited plane has no offset.";
                    }
                }
                catch (Exception ex)
                {
                    skipped++;
                    if (log != null) log.Add("view range unreadable for " + v.Name + ": " + VmCore.Describe(ex));
                    continue;
                }
                row.Locked[KeyCut] = "The cut plane level is shown for reference - change it in Revit's View Range dialog.";

                // a view template that controls the view range takes the right to edit it
                try
                {
                    ElementId tid = v.ViewTemplateId;
                    if (!VmRevit.IsInvalid(tid))
                    {
                        bool controls;
                        if (!templateControls.TryGetValue(tid.Value, out controls))
                        {
                            var tpl = doc.GetElement(tid) as View;
                            controls = tpl != null && !tpl.GetNonControlledTemplateParameterIds().Contains(new ElementId(BuiltInParameter.PLAN_VIEW_RANGE));
                            templateControls[tid.Value] = controls;
                        }
                        if (controls)
                        {
                            string tname = VmRevit.TypeNameOf(doc.GetElement(tid));
                            foreach (PlaneInfo p in Planes)
                            {
                                row.Locked[p.LevelKey] = "The view range is controlled by the view template '" + tname + "'.";
                                row.Locked[p.OffsetKey] = row.Locked[p.LevelKey];
                            }
                        }
                    }
                }
                catch (Exception) { }

                foreach (string pname in extras)
                {
                    string key = VmCore.ParamPrefix + pname;
                    Parameter p = VmRevit.NamedParam(v, pname);
                    row.Values[key] = VmRevit.ParamText(p);
                    if (p == null) row.Locked[key] = "This view has no '" + pname + "' parameter.";
                    else if (p.IsReadOnly) row.Locked[key] = "'" + pname + "' is read-only.";
                    else if (p.StorageType != StorageType.String && p.StorageType != StorageType.Integer && p.StorageType != StorageType.Double)
                        row.Locked[key] = "'" + pname + "' holds a reference, not text.";
                }
                rows.Add(row);
            }
            rows = rows.Select((r, i) => new { r, i })
                       .OrderBy(t => VmCore.ViewTypeRank(t.r.TypeName))
                       .ThenBy(t => VmCore.NaturalKey(t.r.Values["name"]), StringComparer.Ordinal)
                       .ThenBy(t => t.i)
                       .Select(t => t.r).ToList();
            if (log != null) log.Add("Read " + rows.Count + " plan view(s) for the view range list" + (skipped > 0 ? " (" + skipped + " without a readable range)" : "") + ".");
            return rows;
        }

        // ---------------------------------------------------------------- writing --

        private static ElementId LevelIdOf(string label, Dictionary<string, ElementId> byName)
        {
            if (label == Unlimited) return PlanViewRange.Unlimited;
            if (label == LevelAbove) return PlanViewRange.LevelAbove;
            if (label == LevelBelow) return PlanViewRange.LevelBelow;
            ElementId id;
            return byName.TryGetValue(label, out id) ? id : null;
        }

        /// <summary>
        /// Writes staged view range edits, one view at a time inside one transaction: a view Revit refuses is rolled back with the
        /// reason and the others still land. Parameter edits on the same rows go through ApplyRefEdits.
        /// </summary>
        public static void ApplyRangeEdits(Document doc, IList<VmCore.EditItem> items, List<string> log,
                                           out List<VmCore.CellKey> applied, out Dictionary<VmCore.CellKey, string> failed)
        {
            applied = new List<VmCore.CellKey>();
            failed = new Dictionary<VmCore.CellKey, string>();
            var byName = new Dictionary<string, ElementId>();
            foreach (Level l in VmRevit.CollectLevels(doc)) byName[l.Name] = l.Id;
            ForgeTypeId unit = LengthUnit(doc);

            var t = new Transaction(doc, "View Manager - view range");
            t.Start();
            VmRevit.QuietOptions(t);
            try
            {
                foreach (IGrouping<long, VmCore.EditItem> group in items.GroupBy(i => i.ViewId))
                {
                    var view = doc.GetElement(RevitCompat.Id(group.Key)) as ViewPlan;
                    List<VmCore.EditItem> mine = group.ToList();
                    if (view == null)
                    {
                        foreach (VmCore.EditItem i in mine) failed[new VmCore.CellKey(i.ViewId, i.Key)] = "The view is no longer in the model.";
                        continue;
                    }
                    var sub = new SubTransaction(doc);
                    sub.Start();
                    try
                    {
                        PlanViewRange range = view.GetViewRange();
                        // levels first, then offsets; a second pass in the other order for a range Revit will only take that way round
                        Action<bool> write = topDown =>
                        {
                            foreach (PlaneInfo p in Planes)
                            {
                                VmCore.EditItem e = mine.FirstOrDefault(i => i.Key == p.LevelKey);
                                if (e == null) continue;
                                ElementId id = LevelIdOf(e.Text, byName);
                                if (id == null) throw new ArgumentException("'" + e.Text + "' is not a level in this project.");
                                range.SetLevelId(p.Plane, id);
                            }
                            IEnumerable<PlaneInfo> order = topDown ? Planes : Enumerable.Reverse(Planes);
                            foreach (PlaneInfo p in order)
                            {
                                VmCore.EditItem e = mine.FirstOrDefault(i => i.Key == p.OffsetKey);
                                if (e == null) continue;
                                double n;
                                if (!TryParseOffset(e.Text, out n)) throw new ArgumentException("'" + e.Text + "' is not a number.");
                                range.SetOffset(p.Plane, UnitUtils.ConvertToInternalUnits(n, unit));
                            }
                        };
                        try { write(true); }
                        catch (Exception)
                        {
                            range = view.GetViewRange();
                            write(false);
                        }
                        view.SetViewRange(range);
                        sub.Commit();
                        foreach (VmCore.EditItem i in mine) applied.Add(new VmCore.CellKey(i.ViewId, i.Key));
                    }
                    catch (Exception ex)
                    {
                        try { sub.RollBack(); } catch (Exception) { }
                        string why = VmCore.Describe(ex);
                        foreach (VmCore.EditItem i in mine) failed[new VmCore.CellKey(i.ViewId, i.Key)] = why;
                        log.Add("  FAIL view range on [" + group.Key + "] " + view.Name + ": " + why);
                    }
                }
                TransactionStatus status = t.Commit();
                if (status != TransactionStatus.Committed) throw new Exception("transaction status was " + status);
            }
            catch (Exception ex)
            {
                if (t.HasStarted())
                {
                    try { t.RollBack(); } catch (Exception) { }
                }
                log.Add("  transaction failed: " + VmCore.Describe(ex));
                applied = new List<VmCore.CellKey>();
                failed = new Dictionary<VmCore.CellKey, string>();
                foreach (VmCore.EditItem i in items) failed[new VmCore.CellKey(i.ViewId, i.Key)] = "Nothing was written: " + VmCore.Describe(ex);
            }
            finally
            {
                t.Dispose();
            }
        }
    }
}

