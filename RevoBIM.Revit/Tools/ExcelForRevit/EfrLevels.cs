// Excel for Revit: level changing (port of efr_core.py lines 1412-1668).
//
// Re-levelling without moving anything.
//
// An element's elevation is stored against its level, so writing a new level
// normally drags it through space by the difference between the two. Some
// categories compensate on their own and some do not, and which is which varies
// by category and by release. Rather than pair every level parameter with the
// right offset parameter and hope, the position is MEASURED BEFORE AND AFTER
// and any movement is undone: correct for every category, including ones this
// tool has never seen.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.ExcelForRevit
{
    public static partial class Efr
    {
        public static readonly string[] LEVEL_PARAM_NAMES =
        {
            "FAMILY_LEVEL_PARAM",            // most family instances
            "RBS_START_LEVEL_PARAM",         // pipes, ducts, trays, conduit
            "INSTANCE_REFERENCE_LEVEL_PARAM",
            "FAMILY_BASE_LEVEL_PARAM",       // things with a base and a top
            "WALL_BASE_CONSTRAINT",
            "STAIRS_BASE_LEVEL_PARAM",
            "ROOF_BASE_LEVEL_PARAM",
            "LEVEL_PARAM",
            "SCHEDULE_LEVEL_PARAM",          // last: read only on plenty of categories
        };

        /// <summary>
        /// The writable level parameter on this element, or null. Built-in parameters are looked up
        /// by name inside the function, so a member missing from one release cannot stop the tool loading.
        /// </summary>
        public static Parameter LevelParamOf(Element elem)
        {
            foreach (string name in LEVEL_PARAM_NAMES)
            {
                BuiltInParameter bip;
                if (!Enum.TryParse(name, out bip)) continue;
                Parameter p;
                try
                {
                    p = elem.get_Parameter(bip);
                }
                catch (Exception)
                {
                    p = null;
                }
                if (p != null && !p.IsReadOnly && p.StorageType == StorageType.ElementId)
                    return p;
            }
            // nothing built in: any writable ElementId parameter already pointing at a
            // level will do, which covers shared parameters used as a level
            try
            {
                foreach (Parameter p in elem.Parameters)
                {
                    if (p.IsReadOnly || p.StorageType != StorageType.ElementId) continue;
                    Element target;
                    try
                    {
                        target = elem.Document.GetElement(p.AsElementId());
                    }
                    catch (Exception)
                    {
                        target = null;
                    }
                    if (target is Level)
                        return p;
                }
            }
            catch (Exception) { }
            return null;
        }

        /// <summary>The default 3D view, or the next best one. Null if there are none.</summary>
        public static View3D Best3dView(Document doc)
        {
            View3D best = null;
            int bestRank = 99;
            try
            {
                foreach (Element el in new FilteredElementCollector(doc).OfClass(typeof(View3D)).WhereElementIsNotElementType())
                {
                    View3D view = el as View3D;
                    if (view == null) continue;
                    try
                    {
                        if (view.IsTemplate) continue;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                    int rank = Default3dRank(ElemName(view));
                    if (rank < bestRank)
                    {
                        best = view;
                        bestRank = rank;
                    }
                }
            }
            catch (Exception)
            {
                return null;
            }
            return best;
        }

        /// <summary>Every level, lowest first.</summary>
        public static List<Level> ProjectLevels(Document doc)
        {
            List<Level> output = new List<Level>();
            try
            {
                foreach (Element el in new FilteredElementCollector(doc).OfClass(typeof(Level)).WhereElementIsNotElementType())
                {
                    Level lv = el as Level;
                    if (lv != null) output.Add(lv);
                }
            }
            catch (Exception)
            {
                return new List<Level>();
            }
            try
            {
                output = output.OrderBy(lv => lv.Elevation).ToList();
            }
            catch (Exception) { }
            return output;
        }

        /// <summary>
        /// A point that stands for where the element is, in feet: the location point or the start of
        /// the location curve where there is one, the centre of the bounding box otherwise. Only the
        /// change in it matters, so any consistent point does the job. Null when there is none.
        /// </summary>
        public static XYZ ElementAnchor(Element elem)
        {
            Location loc;
            try
            {
                loc = elem.Location;
            }
            catch (Exception)
            {
                loc = null;
            }
            try
            {
                LocationPoint lp = loc as LocationPoint;
                if (lp != null) return lp.Point;
                LocationCurve lc = loc as LocationCurve;
                if (lc != null) return lc.Curve.GetEndPoint(0);
            }
            catch (Exception) { }
            try
            {
                BoundingBoxXYZ box = elem.get_BoundingBox(null);
                if (box != null)
                {
                    return new XYZ((box.Min.X + box.Max.X) / 2.0,
                                   (box.Min.Y + box.Max.Y) / 2.0,
                                   (box.Min.Z + box.Max.Z) / 2.0);
                }
            }
            catch (Exception) { }
            return null;
        }

        /// <summary>
        /// Move an element onto another level without moving it in space. Runs inside the caller's
        /// transaction. Returns (ok, message).
        /// </summary>
        public static (bool Ok, string Message) SetLevelKeepingPlace(Document doc, Element elem, ElementId levelId, double tolerance = 1e-7)
        {
            Parameter param = LevelParamOf(elem);
            if (param == null)
                return (false, "no level parameter that can be written");
            try
            {
                if (EidValue(param.AsElementId()) == EidValue(levelId))
                    return (true, "already on that level");
            }
            catch (Exception) { }

            bool wasPinned = false;
            try
            {
                wasPinned = elem.Pinned;
                if (wasPinned)
                    elem.Pinned = false;
            }
            catch (Exception)
            {
                wasPinned = false;
            }

            XYZ before = ElementAnchor(elem);
            try
            {
                param.Set(levelId);
            }
            catch (Exception err)
            {
                if (wasPinned) TryPin(elem);
                return (false, "Revit refused the level: " + err.Message);
            }

            try
            {
                doc.Regenerate();
            }
            catch (Exception) { }

            double moved = 0.0;
            XYZ after = ElementAnchor(elem);
            if (before != null && after != null)
            {
                try
                {
                    XYZ delta = new XYZ(before.X - after.X, before.Y - after.Y, before.Z - after.Z);
                    moved = delta.GetLength();
                    if (moved > tolerance)
                    {
                        ElementTransformUtils.MoveElement(doc, elem.Id, delta);
                        doc.Regenerate();
                    }
                }
                catch (Exception err)
                {
                    if (wasPinned) TryPin(elem);
                    return (false, "the level changed but it could not be put back: " + err.Message);
                }
            }

            if (wasPinned) TryPin(elem);

            // prove it, rather than trusting a call that raised nothing
            try
            {
                Parameter check = LevelParamOf(elem);
                if (check == null || EidValue(check.AsElementId()) != EidValue(levelId))
                    return (false, "the level did not stick");
            }
            catch (Exception) { }
            XYZ final = ElementAnchor(elem);
            if (before != null && final != null)
            {
                try
                {
                    double drift = new XYZ(before.X - final.X, before.Y - final.Y, before.Z - final.Z).GetLength();
                    if (drift > 1e-6)
                    {
                        double mm = Math.Round(drift * 304.8, 1, MidpointRounding.AwayFromZero);
                        return (false, "it ended up " + mm.ToString("0.0", CultureInfo.InvariantCulture) + "mm from where it started");
                    }
                }
                catch (Exception) { }
            }
            if (moved > tolerance)
                return (true, "level changed, position corrected");
            return (true, "level changed");
        }

        private static void TryPin(Element elem)
        {
            try
            {
                elem.Pinned = true;
            }
            catch (Exception) { }
        }

        /// <summary>
        /// Borrow before writing. A write to an element nobody has borrowed writes nothing and says
        /// nothing: Revit asks in a dialog, and a run that suppresses dialogs answers it.
        /// </summary>
        public static void CheckoutElements(Document doc, IEnumerable<ElementId> ids)
        {
            try
            {
                if (!doc.IsWorkshared) return;
            }
            catch (Exception)
            {
                return;
            }
            try
            {
                List<ElementId> bag = new List<ElementId>();
                foreach (ElementId eid in ids)
                {
                    if (eid != null) bag.Add(eid);
                }
                if (bag.Count > 0)
                    WorksharingUtils.CheckoutElements(doc, bag);
            }
            catch (Exception) { }
        }

        /// <summary>Runs inside the apply transaction, so a failure rolls back with it.</summary>
        public static void ApplyLevelEdits(Document doc, ScheduleModel model, ApplyResult res, HashSet<RowInfo> touchedRows)
        {
            List<int> ridxs = new List<int>(model.LevelEdits.Keys);
            ridxs.Sort();
            foreach (int ridx in ridxs)
            {
                ElementId levelId = model.LevelEdits[ridx].LevelId;
                RowInfo row;
                try
                {
                    row = model.Rows[ridx];
                }
                catch (Exception)
                {
                    continue;
                }
                Element elem = null;
                try
                {
                    elem = doc.GetElement(row.ElemId);
                }
                catch (Exception)
                {
                    elem = null;
                }
                string label = "Element [" + EidValue(row.ElemId).ToString(CultureInfo.InvariantCulture) + "]";
                if (elem != null)
                {
                    string nm = ElemName(elem);
                    label = (string.IsNullOrEmpty(nm) ? "Element" : nm) + " [" + EidValue(row.ElemId).ToString(CultureInfo.InvariantCulture) + "]";
                }
                if (elem == null)
                {
                    res.Failures.Add((label, "Level", "the element is gone"));
                    res.Ok = false;
                    continue;
                }
                var result = SetLevelKeepingPlace(doc, elem, levelId);
                if (result.Ok)
                {
                    res.Levels++;
                    touchedRows.Add(row);
                }
                else
                {
                    res.Failures.Add((label, "Level", result.Message));
                    res.Ok = false;
                }
            }
        }
    }
}
