# -*- coding: utf-8 -*-
"""What the duplicate is going to do, worked out before anything is written.

No Revit API in here on purpose: the whole plan - which views get duplicated,
which get reused, how dependents follow their parent, what everything ends up
called - is the part that is easy to get wrong and hard to test in Revit, so it
runs under plain CPython on the bench.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import shtm_core

# actions a view can be given
REUSE = "reuse"            # put the same view on the new sheet
DUPLICATE = "duplicate"    # make an independent copy
PARENT = "parent"          # copy of a primary view, because a dependent of it is on a sheet
DEPENDENT = "dependent"    # a dependent of the new parent
SKIP = "skip"              # left off the new sheet altogether (a legend, by default)

ACTION_LABELS = {
    REUSE: "same view placed again",
    DUPLICATE: "duplicated",
    PARENT: "parent duplicated",
    DEPENDENT: "dependent of the new parent",
}


def classify(view, options):
    """What happens to one view that is placed on a sheet being duplicated."""
    kind = view.get("kind", "model")
    if kind == "legend":
        # legends come across only when asked for (1.9.0: off by default)
        if not options.get("include_legends", True):
            return SKIP
        return REUSE if options.get("legends", "reuse") == "reuse" else DUPLICATE
    if kind == "schedule":
        return REUSE if options.get("schedules", "reuse") == "reuse" else DUPLICATE
    if kind == "drafting":
        return REUSE if options.get("drafting", "duplicate") == "reuse" else DUPLICATE
    if view.get("primary", 0):
        # a dependent always comes across as a dependent of a copy of its
        # parent (1.9.0) - never flattened into a view of its own
        return DEPENDENT
    return DUPLICATE


def build_plan(selected_sheets, placements, views, options):
    """Work out every view job and every placement.

    selected_sheets  ordered list of sheet ids being duplicated
    placements       list of {'sheet': id, 'view': id, 'kind': 'viewport'|'schedule'}
    views            dict of view id -> {'id','name','kind','type','primary'}
    options          the duplicate options

    Returns a dict with:
      jobs        ordered list of view jobs, parents before their dependents
      placements  the placements that can actually be made
      unplaced    views that get created but land on no sheet
      notes       anything worth reporting
    """
    selected = list(selected_sheets)
    selected_set = set(selected)
    jobs = []
    job_index = {}
    out_placements = []
    unplaced = []
    notes = []

    # where each view is placed, so a dependent can find its own sheet
    view_sheet = {}
    for placement in placements:
        view_sheet.setdefault(placement["view"], []).append(placement["sheet"])

    def add_job(view_id, action, parent_old=0):
        if view_id in job_index:
            existing = jobs[job_index[view_id]]
            # a parent already queued as a plain duplicate stays as it is
            return existing
        view = views.get(view_id)
        if view is None:
            return None
        job = {
            "old_id": view_id,
            "action": action,
            "kind": view.get("kind", "model"),
            "type": view.get("type", u"View"),
            "name": view.get("name", u""),
            "parent_old": parent_old,
            "is_primary": action == PARENT,
        }
        job_index[view_id] = len(jobs)
        jobs.append(job)
        return job

    parents_wanted = {}

    for placement in placements:
        if placement["sheet"] not in selected_set:
            continue
        view_id = placement["view"]
        view = views.get(view_id)
        if view is None:
            notes.append(u"a view placed on a sheet could not be read and was skipped")
            continue
        action = classify(view, options)
        if action == SKIP:
            continue
        if action == DEPENDENT:
            parents_wanted.setdefault(view.get("primary", 0), set()).add(view_id)
        else:
            add_job(view_id, action)

    # dependents: the parent comes across, and its dependents come with it
    for primary_id in sorted(parents_wanted.keys()):
        primary = views.get(primary_id)
        if primary is None:
            # the parent is unreadable, so the dependents are duplicated flat
            for view_id in sorted(parents_wanted[primary_id]):
                add_job(view_id, DUPLICATE)
                notes.append(u"the parent of a dependent view could not be read, "
                             u"so it was duplicated on its own")
            continue
        # a primary that was itself placed on one of the sheets is already
        # queued as a plain duplicate; it is still the parent, and the switch
        # that decides whether it lands on a new sheet has to reach it
        parent_job = add_job(primary_id, PARENT)
        if parent_job is not None:
            parent_job["is_primary"] = True

        family = [v["id"] for v in views.values() if v.get("primary", 0) == primary_id]
        if not options.get("all_dependents", True):
            family = [v for v in family
                      if set(view_sheet.get(v, [])) & selected_set]
        for view_id in sorted(family):
            add_job(view_id, DEPENDENT, primary_id)

    # order: everything that is not a dependent first, dependents after their parent
    ordered = [j for j in jobs if j["action"] != DEPENDENT]
    ordered += [j for j in jobs if j["action"] == DEPENDENT]
    for index, job in enumerate(ordered):
        job["order"] = index

    made = set([j["old_id"] for j in ordered])

    job_by_id = {}
    for job in ordered:
        job_by_id[job["old_id"]] = job

    for placement in placements:
        if placement["sheet"] not in selected_set:
            continue
        view_id = placement["view"]
        job = job_by_id.get(view_id)
        if job is None:
            continue
        if job.get("is_primary") and not options.get("place_new_parent", True):
            # the old parent was on one of the sheets being copied, but the new
            # parent is deliberately left off its new sheet
            continue
        out_placements.append({
            "sheet": placement["sheet"],
            "view": view_id,
            "kind": placement.get("kind", "viewport"),
            "src": placement.get("id", 0),
        })

    placed_views = set([p["view"] for p in out_placements])
    for job in ordered:
        if job["old_id"] not in placed_views:
            unplaced.append(job)

    if unplaced:
        notes.append(
            u"{0} view(s) are created but land on no new sheet - a parent view, "
            u"or a dependent whose own sheet is not in the selection".format(len(unplaced)))

    return {
        "jobs": ordered,
        "placements": out_placements,
        "unplaced": unplaced,
        "notes": notes,
    }


def name_the_plan(plan, rules, existing_names):
    """Give every job its new name and flag anything that had to be stepped."""
    taken = set([u"{0}".format(n).strip().lower() for n in existing_names])
    for job in plan["jobs"]:
        if job["action"] == REUSE:
            job["new_name"] = job["name"]
            job["renamed"] = False
            continue
        wanted = shtm_core.apply_rule(job["name"], rules.get("find"),
                                      rules.get("replace"), rules.get("prefix"),
                                      rules.get("match_case"))
        final = shtm_core.unique_name(wanted, taken)
        job["new_name"] = final
        job["renamed"] = (final != wanted)
    return plan


def plan_summary(plan, sheet_rows):
    """The sentence Apply says before it writes anything."""
    jobs = plan["jobs"]
    counts = {}
    for job in jobs:
        counts[job["action"]] = counts.get(job["action"], 0) + 1
    lines = []
    lines.append(u"{0} new sheet(s)".format(len(sheet_rows)))
    if counts.get(DUPLICATE):
        lines.append(u"{0} view(s) duplicated".format(counts[DUPLICATE]))
    if counts.get(PARENT):
        lines.append(u"{0} parent view(s) duplicated".format(counts[PARENT]))
    if counts.get(DEPENDENT):
        lines.append(u"{0} dependent view(s) created".format(counts[DEPENDENT]))
    if counts.get(REUSE):
        lines.append(u"{0} view(s) placed again as they are".format(counts[REUSE]))
    if plan["unplaced"]:
        lines.append(u"{0} view(s) created but not placed on a sheet".format(
            len(plan["unplaced"])))
    return lines


def blockers(sheet_rows):
    """Rows that stop the run rather than warn about it."""
    return [r for r in sheet_rows if r.get("status") == "bad"]
