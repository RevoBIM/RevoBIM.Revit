using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.FamilyFindReplace
{
    /// <summary>Replacing the family inside group types: take one instance apart, change it, put it back as a new type.</summary>
    public static partial class FfrCore
    {
        /// <summary>One group type that holds the family being replaced.</summary>
        public sealed class GroupWork
        {
            public ElementId TypeId;
            public string TypeName;
            public List<ElementId> GroupIds = new List<ElementId>();   // every placed instance of that type
            public int Targets;                                        // how many of the family sit in one instance
        }

        public sealed class GroupOutcome
        {
            public int Swapped;
            public List<string> Problems = new List<string>();
            public int DetailGroups;
            public bool Shifted;
        }

        /// <summary>
        /// Split the selection into loose elements and the group types involved. Every instance of an affected
        /// group type is listed, not only the ones the scope picked up: a group type is one definition shared by
        /// all its instances, so changing what is inside it changes every one of them, project wide.
        /// </summary>
        public static List<GroupWork> SurveyGroups(Document doc, List<Element> instances, HashSet<long> sourceTypes, out List<Element> loose)
        {
            loose = new List<Element>();
            var work = new Dictionary<long, GroupWork>();
            foreach (Element element in instances)
            {
                ElementId groupId = null;
                try
                {
                    groupId = element.GroupId;
                }
                catch (Exception)
                {
                }
                if (groupId == null || Eid(groupId) <= 0)
                {
                    loose.Add(element);
                    continue;
                }
                var group = doc.GetElement(groupId) as Group;
                if (group == null)
                {
                    loose.Add(element);
                    continue;
                }
                GroupType groupType;
                try
                {
                    groupType = group.GroupType;
                    if (groupType == null) throw new InvalidOperationException();
                }
                catch (Exception)
                {
                    loose.Add(element);
                    continue;
                }
                GroupWork item;
                if (!work.TryGetValue(Eid(groupType.Id), out item))
                {
                    item = new GroupWork { TypeId = groupType.Id, TypeName = Name(groupType), GroupIds = InstancesOfGroupType(doc, groupType) };
                    work[Eid(groupType.Id)] = item;
                }
                item.Targets++;
            }

            // How many of the family sit across ALL instances of each type, not only the ones the scope picked up:
            // that is the number the confirmation should be quoting, because that is the work.
            if (sourceTypes != null && sourceTypes.Count > 0)
            {
                foreach (GroupWork item in work.Values)
                {
                    int total = 0;
                    foreach (ElementId groupId in item.GroupIds)
                    {
                        var group = doc.GetElement(groupId) as Group;
                        if (group != null) total += GroupMemberTargets(doc, group, sourceTypes).Count;
                    }
                    if (total > 0) item.Targets = total;
                }
            }
            return work.Values.ToList();
        }

        private static List<ElementId> InstancesOfGroupType(Document doc, GroupType groupType)
        {
            var ids = new List<ElementId>();
            long wanted = Eid(groupType.Id);
            try
            {
                foreach (Element element in new FilteredElementCollector(doc).OfClass(typeof(Group)))
                {
                    try
                    {
                        var group = element as Group;
                        if (group != null && Eid(group.GroupType.Id) == wanted) ids.Add(group.Id);
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            catch (Exception)
            {
            }
            return ids;
        }

        public static int CountGroupInstances(List<GroupWork> work)
        {
            return work.Sum(item => item.GroupIds.Count);
        }

        /// <summary>The ids inside a group that are of the family being replaced.</summary>
        private static List<ElementId> GroupMemberTargets(Document doc, Group group, HashSet<long> sourceTypeIds)
        {
            var found = new List<ElementId>();
            ICollection<ElementId> memberIds;
            try
            {
                memberIds = group.GetMemberIds();
            }
            catch (Exception)
            {
                return found;
            }
            foreach (ElementId memberId in memberIds)
            {
                var element = doc.GetElement(memberId) as FamilyInstance;
                if (element == null) continue;
                try
                {
                    if (sourceTypeIds.Contains(Eid(element.GetTypeId()))) found.Add(memberId);
                }
                catch (Exception)
                {
                }
            }
            return found;
        }

        /// <summary>Run the ordinary swap over one ungrouped set. Returns the final ids.</summary>
        private static List<ElementId> SwapMembers(Document doc, ICollection<ElementId> memberIds, FamilySymbol symbol, HashSet<long> sourceTypeIds,
                                                   RunOptions options, Report report, List<string> problems, out int swapped)
        {
            var final = new List<ElementId>();
            swapped = 0;
            foreach (ElementId memberId in memberIds)
            {
                Element element = doc.GetElement(memberId);
                if (element == null) continue;
                if (element is Group)
                {
                    // a nested group would need the whole routine again, one level down: left alone and reported
                    problems.Add("a nested group was left alone - the family inside it was not replaced");
                    final.Add(memberId);
                    continue;
                }
                bool isTarget = false;
                try
                {
                    isTarget = element is FamilyInstance && sourceTypeIds.Contains(Eid(element.GetTypeId()));
                }
                catch (Exception)
                {
                    isTarget = false;
                }
                if (!isTarget)
                {
                    final.Add(memberId);
                    continue;
                }
                int before = report.NewIds.Count;
                string message;
                bool ok = ReplaceOne(doc, element, symbol, options, report, true, out message);
                if (ok && report.NewIds.Count > before)
                {
                    final.Add(report.NewIds[report.NewIds.Count - 1]);
                    swapped++;
                }
                else
                {
                    problems.Add(string.IsNullOrEmpty(message) ? "an element in the group would not replace" : message);
                    final.Add(memberId);
                }
            }
            return final;
        }

        /// <summary>Where one member of a given type sits, used to prove nothing shifted.</summary>
        private static XYZ WitnessPoint(Document doc, Group group, HashSet<long> typeIds)
        {
            foreach (ElementId memberId in GroupMemberTargets(doc, group, typeIds))
            {
                XYZ point = InstancePoint(doc.GetElement(memberId));
                if (point != null) return point;
            }
            return null;
        }

        /// <summary>
        /// Swap the family inside every instance of one group type. There is no edit-group-in-place in the API,
        /// so one instance is taken apart, changed, and put back as a new type, and the other instances are
        /// moved onto that type. The swap runs once for the type rather than once per instance.
        /// The risk is that regrouping computes a fresh group origin, and moving an instance to a type whose
        /// origin sits elsewhere can shift its contents. So the first reassignment is checked against a witness
        /// point taken before it, and if anything moved the caller is told to take the slow route instead.
        /// </summary>
        public static GroupOutcome ReplaceInGroupType(Document doc, GroupWork item, FamilySymbol symbol, HashSet<long> sourceTypeIds,
                                                      RunOptions options, Report report)
        {
            var outcome = new GroupOutcome();
            if (item.GroupIds.Count == 0) return outcome;

            foreach (ElementId groupId in item.GroupIds)
            {
                var group = doc.GetElement(groupId) as Group;
                if (group == null) continue;
                try
                {
                    ICollection<ElementId> attached = group.GetAvailableAttachedDetailGroupTypeIds();
                    if (attached != null && attached.Count > 0) outcome.DetailGroups++;
                }
                catch (Exception)
                {
                }
            }

            var first = doc.GetElement(item.GroupIds[0]) as Group;
            if (first == null)
            {
                outcome.Problems.Add("the group instance has gone");
                return outcome;
            }

            // witnesses for every other instance, taken while they are still intact
            var witnesses = new Dictionary<long, XYZ>();
            foreach (ElementId groupId in item.GroupIds.Skip(1))
            {
                var group = doc.GetElement(groupId) as Group;
                if (group == null) continue;
                XYZ point = WitnessPoint(doc, group, sourceTypeIds);
                if (point != null) witnesses[Eid(groupId)] = point;
            }

            bool pinned = UnpinGroup(first);
            ICollection<ElementId> members;
            try
            {
                members = first.UngroupMembers();
            }
            catch (Exception err)
            {
                outcome.Problems.Add("the group would not ungroup: " + err.Message);
                return outcome;
            }
            doc.Regenerate();

            int swapped;
            List<ElementId> final = SwapMembers(doc, members, symbol, sourceTypeIds, options, report, outcome.Problems, out swapped);
            outcome.Swapped = swapped;
            if (swapped == 0) return outcome;

            doc.Regenerate();
            var ids = final.Where(id => doc.GetElement(id) != null).ToList();
            if (ids.Count == 0)
            {
                outcome.Swapped = 0;
                outcome.Problems.Add("the group had nothing left to re-form");
                return outcome;
            }
            Group rebuilt;
            try
            {
                rebuilt = doc.Create.NewGroup(ids);
            }
            catch (Exception err)
            {
                outcome.Swapped = 0;
                outcome.Problems.Add("the group would not re-form: " + err.Message);
                return outcome;
            }
            doc.Regenerate();
            if (pinned) RepinGroup(rebuilt);

            GroupType newType = null;
            try
            {
                newType = rebuilt.GroupType;
            }
            catch (Exception)
            {
            }
            if (newType == null)
            {
                outcome.Problems.Add("the re-formed group has no type");
                return outcome;
            }

            // move every other instance onto the new type, checking the first one
            bool checkedOne = false;
            foreach (ElementId groupId in item.GroupIds.Skip(1))
            {
                var group = doc.GetElement(groupId) as Group;
                if (group == null) continue;
                bool wasPinned = UnpinGroup(group);
                try
                {
                    group.GroupType = newType;
                }
                catch (Exception err)
                {
                    outcome.Problems.Add("an instance kept its own type: " + err.Message);
                    if (wasPinned) RepinGroup(group);
                    continue;
                }
                doc.Regenerate();
                if (wasPinned) RepinGroup(group);
                if (checkedOne) continue;
                checkedOne = true;
                XYZ wanted;
                if (!witnesses.TryGetValue(Eid(groupId), out wanted)) continue;
                XYZ landed = WitnessPoint(doc, group, new HashSet<long> { Eid(symbol.Id) });
                if (landed == null)
                {
                    // cannot prove it, so do not claim it
                    outcome.Problems.Add("an instance could not be checked for movement after being moved to the new type");
                    outcome.Shifted = true;
                    return outcome;
                }
                if (landed.DistanceTo(wanted) > PointTolFt * 100.0)
                {
                    // it shifted: the caller rolls this back and takes the slow route
                    outcome.Shifted = true;
                    return outcome;
                }
            }

            RetireOldGroupType(doc, item, newType, outcome.Problems);
            return outcome;
        }

        /// <summary>
        /// The careful route: rebuild every instance in place, then unify. Slower, but every instance's members
        /// are regrouped exactly where they already were, so nothing can move. Used only when the fast route has
        /// been caught shifting something.
        /// </summary>
        public static GroupOutcome ReplaceInGroupTypeSlow(Document doc, GroupWork item, FamilySymbol symbol, HashSet<long> sourceTypeIds,
                                                          RunOptions options, Report report)
        {
            var outcome = new GroupOutcome();
            var pinned = new HashSet<long>();
            var sets = new List<List<ElementId>>();

            foreach (ElementId groupId in item.GroupIds)
            {
                var group = doc.GetElement(groupId) as Group;
                if (group == null) continue;
                try
                {
                    ICollection<ElementId> attached = group.GetAvailableAttachedDetailGroupTypeIds();
                    if (attached != null && attached.Count > 0) outcome.DetailGroups++;
                }
                catch (Exception)
                {
                }
                if (UnpinGroup(group)) pinned.Add(Eid(groupId));
                try
                {
                    sets.Add(group.UngroupMembers().ToList());
                }
                catch (Exception err)
                {
                    outcome.Problems.Add("group " + Eid(groupId) + " would not ungroup: " + err.Message);
                }
            }
            if (sets.Count == 0) return outcome;

            doc.Regenerate();

            var rebuilt = new List<List<ElementId>>();
            foreach (List<ElementId> members in sets)
            {
                int count;
                rebuilt.Add(SwapMembers(doc, members, symbol, sourceTypeIds, options, report, outcome.Problems, out count));
                outcome.Swapped += count;
            }

            doc.Regenerate();

            var made = new List<Group>();
            foreach (List<ElementId> final in rebuilt)
            {
                var ids = final.Where(id => doc.GetElement(id) != null).ToList();
                if (ids.Count == 0) continue;
                try
                {
                    made.Add(doc.Create.NewGroup(ids));
                }
                catch (Exception err)
                {
                    outcome.Problems.Add("a group would not re-form: " + err.Message);
                }
            }
            if (made.Count == 0) return outcome;

            doc.Regenerate();
            GroupType newType = null;
            try
            {
                newType = made[0].GroupType;
            }
            catch (Exception)
            {
            }
            if (newType != null)
            {
                foreach (Group group in made.Skip(1))
                {
                    try
                    {
                        group.GroupType = newType;
                    }
                    catch (Exception err)
                    {
                        outcome.Problems.Add("a re-formed group kept its own type: " + err.Message);
                    }
                }
                RetireOldGroupType(doc, item, newType, outcome.Problems);
            }
            if (pinned.Count > 0)
                foreach (Group group in made) RepinGroup(group);
            return outcome;
        }

        private static bool UnpinGroup(Group group)
        {
            try
            {
                if (group.Pinned)
                {
                    group.Pinned = false;
                    return true;
                }
            }
            catch (Exception)
            {
            }
            return false;
        }

        private static void RepinGroup(Group group)
        {
            try
            {
                group.Pinned = true;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Delete the emptied original type and take its name back.</summary>
        private static void RetireOldGroupType(Document doc, GroupWork item, GroupType newType, List<string> problems)
        {
            try
            {
                Element oldType = doc.GetElement(item.TypeId);
                if (oldType != null)
                {
                    doc.Delete(oldType.Id);
                    doc.Regenerate();
                }
            }
            catch (Exception)
            {
            }
            if (!SetElementName(newType, item.TypeName))
                problems.Add("the re-formed group type could not be renamed back to \"" + item.TypeName + "\" and is called \"" + Name(newType) + "\"");
        }

        /// <summary>Rename, then read it back: the setter does not reliably raise on failure.</summary>
        private static bool SetElementName(Element element, string name)
        {
            try
            {
                element.Name = name;
            }
            catch (Exception)
            {
            }
            return Name(element) == name;
        }
    }
}
