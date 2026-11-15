# -*- coding: utf-8 -*-
"""Template-driven duplication: the rules, with no Revit and no WPF.

The flow this backs:

  1. pick the **source sheets**
  2. say what text to **find** in their sheet numbers, sheet names and view
     names
  3. pick **view templates** and push them into the confirm table
  4. on each template's row, say what the found text is **replaced with**,
     and the values for the browser grouping parameters

Each confirm row is one *set*: a full copy of every source sheet and the views
on it, with that row's template on the duplicated views of its type and that
row's replacement text in every name. Three rows, ten source sheets: thirty new
sheets.

Everything here is a pure function of plain data, so bench_logic.py runs the
real thing.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import json

import shtm_core
import shtm_fill
import shtm_plan

# ViewType name -> (family, readable type). Family is how Revit's own Project
# Browser groups views; type is the ViewType as people say it.
VIEW_TYPES = {
    u"FloorPlan": (u"Plans", u"Floor Plan"),
    u"CeilingPlan": (u"Plans", u"Ceiling Plan"),
    u"EngineeringPlan": (u"Plans", u"Structural Plan"),
    u"AreaPlan": (u"Plans", u"Area Plan"),
    u"Section": (u"Sections", u"Section"),
    u"Detail": (u"Sections", u"Detail View"),
    u"Elevation": (u"Elevations", u"Elevation"),
    u"ThreeD": (u"3D Views", u"3D View"),
    u"Walkthrough": (u"3D Views", u"Walkthrough"),
    u"Rendering": (u"3D Views", u"Rendering"),
    u"DraftingView": (u"Drafting", u"Drafting View"),
    u"Legend": (u"Legends", u"Legend"),
    u"Schedule": (u"Schedules", u"Schedule"),
    u"PanelSchedule": (u"Schedules", u"Panel Schedule"),
    u"ColumnSchedule": (u"Schedules", u"Graphical Column Schedule"),
    u"Report": (u"Schedules", u"Report"),
    u"CostReport": (u"Schedules", u"Cost Report"),
    u"LoadsReport": (u"Schedules", u"Loads Report"),
    u"PresureLossReport": (u"Schedules", u"Pressure Loss Report"),
    u"SystemsAnalysisReport": (u"Schedules", u"Systems Analysis Report"),
}

ALL = u"(all)"
LEAVE = u"(leave each sheet's own)"


def family_of(view_type):
    return VIEW_TYPES.get(view_type, (u"Other", view_type))[0]


def type_label(view_type):
    return VIEW_TYPES.get(view_type, (u"Other", view_type))[1]


def template_records(grouped):
    """shtm_model.view_templates' {view type: [{id, name}]} as one flat list
    with family and readable type, in the order the table shows them."""
    out = []
    for view_type in grouped:
        for template in grouped[view_type]:
            out.append({
                "id": template["id"],
                "name": template["name"],
                "view_type": view_type,
                "family": family_of(view_type),
                "type": type_label(view_type),
            })
    # by name (1.9.0): a list filtered to one family reads as an alphabetical
    # list, not as blocks of types
    out.sort(key=lambda t: (shtm_core.natural_key(t["name"]), t["id"]))
    return out


DEFAULT_FAMILY = u"Plans"


def default_family(templates):
    """The family the template list opens on: Plans when the project has any,
    otherwise everything."""
    names = set([t["family"] for t in templates])
    return DEFAULT_FAMILY if DEFAULT_FAMILY in names else ALL


def filter_templates(templates, family=ALL, type_name=ALL, needle=u""):
    needle = (needle or u"").strip().lower()
    out = []
    for template in templates:
        if family and family != ALL and template["family"] != family:
            continue
        if type_name and type_name != ALL and template["type"] != type_name:
            continue
        if needle:
            words = needle.split()
            text = template["name"].lower()
            if not all(word in text for word in words):
                continue
        out.append(template)
    return out


def families(templates):
    return [ALL] + sorted(set([t["family"] for t in templates]))


def types_in(templates, family=ALL):
    pool = [t for t in templates if family in (None, ALL) or t["family"] == family]
    return [ALL] + sorted(set([t["type"] for t in pool]))


def applies_to(template, sources, placements, views):
    """How many of the views on the source sheets this template would go on.

    Dependents are left out: they take their parent's template, so a template
    is counted once against the parent rather than once per crop region.
    """
    source_ids = set([s["id"] for s in sources])
    counted = set()
    for placement in placements:
        if placement["sheet"] not in source_ids:
            continue
        view = views.get(placement["view"])
        if view is None:
            continue
        target = view
        if view.get("primary"):
            target = views.get(view["primary"]) or view
        if target.get("type") == template["view_type"]:
            counted.add(target["id"])
    return len(counted)


def applies_counts(templates, sources, placements, views):
    """applies_to for every template at once, in one pass over the
    placements: count the distinct parent views per view type, then each
    template reads its type's count. Calling applies_to per template walks
    every placement once per template, and ticking a few sheets froze the
    window."""
    source_ids = set([s["id"] for s in sources])
    seen = set()
    per_type = {}
    for placement in placements:
        if placement["sheet"] not in source_ids:
            continue
        view = views.get(placement["view"])
        if view is None:
            continue
        target = view
        if view.get("primary"):
            target = views.get(view["primary"]) or view
        if target["id"] in seen:
            continue
        seen.add(target["id"])
        per_type[target.get("type")] = per_type.get(target.get("type"), 0) + 1
    return dict([(t["id"], per_type.get(t["view_type"], 0)) for t in templates])


def shared_value(sources, parameter):
    """The value every source sheet has for a parameter, or u'' when they
    differ - in which case the cell defaults to leaving each sheet its own."""
    values = set([u"{0}".format(s["values"].get(parameter, u"") or u"")
                  for s in sources])
    if len(values) == 1:
        return values.pop()
    return u""


_UID = [0]


def next_uid():
    """Every row its own id, so a cell can be named by (row, column) even
    after rows above it are added, removed or copied."""
    _UID[0] += 1
    return _UID[0]


def new_row(template, sources, parameters, preset=None):
    """A confirm-table row for a template just pushed across, filled from the
    template's preset when it has one."""
    row = {
        "uid": next_uid(),
        "template_id": template["id"],
        "template_name": template["name"],
        "view_type": template["view_type"],
        "type": template["type"],
        "number": u"",
        "name": u"",
        "view": u"",
        "params": dict([(p, shared_value(sources, p)) for p in parameters]),
        "from_preset": False,
    }
    if preset:
        apply_preset(row, preset)
        row["from_preset"] = True
    return row


def copy_row(row):
    """A second set from the same template - the same template on two levels,
    say - with every value carried across and an id of its own."""
    copy = dict(row)
    copy["params"] = dict(row.get("params") or {})
    copy["uid"] = next_uid()
    return copy


def series_parameter(parameters):
    """The parameter the preview sorts and groups by first: the one whose name
    says Series, else the first one."""
    for name in parameters:
        if u"series" in name.lower():
            return name
    return parameters[0] if parameters else u"Sheet Number"


# ====================== the build ======================

COL_NUMBER = u"Sheet Number"
COL_NAME = u"Sheet Name"
COL_VIEWS = u"Views on sheet"
COL_TEMPLATE = u"View Template"
COL_SOURCE = u"From sheet"
COL_STATUS = u"Status"


def push_columns(parameters, name_params):
    """The name-push parameters the preview adds a column for: the mapped
    ones, in order, less any the table already shows as a grouping column."""
    out = []
    for name in name_params or []:
        if name and name not in parameters and name not in out:
            out.append(name)
    return out


def preview_columns(parameters, name_params=None):
    return ([COL_NUMBER, COL_NAME, COL_VIEWS, COL_TEMPLATE] + list(parameters)
            + push_columns(parameters, name_params) + [COL_SOURCE, COL_STATUS])


def name_push_values(name, name_params, reserved,
                     delimiter=shtm_core.DEFAULT_DELIMITER):
    """What a sheet name pushes into each mapped parameter: split on the
    delimiter, in order, the extra parts joined onto the last. A parameter
    the grouping is writing is left to the grouping."""
    writes, _skipped = shtm_core.name_push_plan(name, name_params, reserved, delimiter)
    return dict(writes)


def contains(text, find, match_case=False):
    text = u"{0}".format(text or u"")
    find = u"{0}".format(find or u"")
    if not find:
        return False
    if match_case:
        return find in text
    return find.lower() in text.lower()


def _kept(find, replacement):
    """The find text to use for a set: none at all when the set's replacement
    is blank, so a blank cell keeps every name as it is."""
    if not (replacement or u"").strip():
        return u""
    return find


def build(sources, rows, finds, placements, views, options, parameters,
          existing_numbers, existing_view_names, name_params=None):
    """Every set to make and every sheet it will make.

    `finds` - {"number", "name", "view", "match_case"}
    `rows`  - the confirm table, in order

    Returns (batches, records). A batch is what the engine runs: a plan, its
    sheet rows, its options (with this row's template) and its grouping. A
    record is one line of the preview: one new sheet.

    Sheet numbers and view names have to be unique across every set, not just
    within one, so each set reserves what it takes before the next is worked
    out.
    """
    taken_numbers = list(existing_numbers or [])
    taken_views = list(existing_view_names or [])
    match_case = bool(finds.get("match_case"))
    source_ids = [s["id"] for s in sources]
    by_id = dict([(s["id"], s) for s in sources])
    batches = []
    records = []

    for index, row in enumerate(rows):
        batch_options = dict(options or {})
        batch_options["templates"] = {row["view_type"]: row["template_id"]}
        batch_options["view_match_case"] = match_case

        plan = shtm_plan.build_plan(source_ids, placements, views, batch_options)
        # a blank replacement cell keeps the names, as its hint says - it
        # does not delete the found text
        shtm_plan.name_the_plan(plan, {"find": _kept(finds.get("view"), row.get("view")),
                                       "replace": row.get("view"),
                                       "prefix": u"",
                                       "match_case": match_case}, taken_views)
        for job in plan["jobs"]:
            if job["action"] != shtm_plan.REUSE:
                taken_views.append(job["new_name"])

        rules = {"number_find": finds.get("number"),
                 "number_replace": row.get("number"),
                 "number_prefix": u"",
                 "name_find": _kept(finds.get("name"), row.get("name")),
                 "name_replace": row.get("name"),
                 "name_prefix": u"",
                 "match_case": match_case}
        sheet_rows = shtm_core.preview_sheets(sources, rules, taken_numbers)
        for sheet_row in sheet_rows:
            sheet_row["key"] = u"{0}:{1}".format(index, sheet_row["id"])
            # the specific reason first: an unchanged number also clashes
            # with its own source, and "already exists" would hide why
            if not contains(sheet_row["old_number"], finds.get("number"),
                            match_case):
                sheet_row["status"] = "bad"
                sheet_row["note"] = (u"the sheet number find text is not "
                                     u"in {0}".format(sheet_row["old_number"]))
            if not (row.get("number") or u"").strip():
                sheet_row["status"] = "bad"
                sheet_row["note"] = u"this row has no sheet number to replace with"
            if sheet_row["status"] != "bad":
                taken_numbers.append(sheet_row["new_number"])

        grouping = {}
        for parameter in parameters:
            value = (row["params"].get(parameter) or u"")
            if value.strip() and value != LEAVE:
                grouping[parameter] = value

        names = dict([(j["old_id"], j["new_name"]) for j in plan["jobs"]])
        for sheet_row in sheet_rows:
            source = by_id.get(sheet_row["id"], {"values": {}})
            on_sheet = [names.get(p["view"], u"") for p in plan["placements"]
                        if p["sheet"] == sheet_row["id"]]
            values = {
                COL_NUMBER: sheet_row["new_number"],
                COL_NAME: sheet_row["new_name"],
                COL_VIEWS: u", ".join([n for n in on_sheet if n]) or u"(no views)",
                COL_TEMPLATE: row["template_name"],
                COL_SOURCE: sheet_row["old_number"],
                COL_STATUS: (u"ready" if sheet_row["status"] == "ok"
                             else sheet_row.get("note") or sheet_row["status"]),
            }
            # what the sheet name push will write, shown before it does; a
            # grouping value set for this set wins over the push
            pushed = (name_push_values(sheet_row["new_name"], name_params,
                                       list(grouping.keys()),
                                       batch_options.get("name_delimiter",
                                                         shtm_core.DEFAULT_DELIMITER))
                      if name_params else {})
            for parameter in parameters:
                if parameter in grouping:
                    values[parameter] = grouping[parameter]
                elif parameter in pushed:
                    values[parameter] = pushed[parameter]
                else:
                    values[parameter] = u"{0}".format(
                        source["values"].get(parameter, u"") or u"")
            for parameter in push_columns(parameters, name_params):
                values[parameter] = pushed.get(parameter, u"")
            records.append({"id": sheet_row["key"], "values": values,
                            "status": sheet_row["status"], "batch": index})

        batches.append({"index": index, "plan": plan, "sheet_rows": sheet_rows,
                        "options": batch_options, "grouping": grouping,
                        "template": row["template_name"]})
    return batches, records


# ====================== cells in the table of sets ======================
# A cell is (row index, key). The keys run left to right in the order the
# table shows them: the three replacements, then the grouping parameters.

FIXED_KEYS = [u"number", u"name", u"view"]
FIXED_LABELS = {u"number": u"Sheet number", u"name": u"Sheet name",
                u"view": u"View name"}


def fit_widths(defaults, wanted):
    """Column widths: each the larger of its default and what its text needs
    (None keeps the default), rounded up to whole pixels."""
    out = []
    for index, default in enumerate(defaults):
        need = wanted[index] if index < len(wanted) else None
        width = default if need is None else max(default, need)
        out.append(float(int(width) + (0 if width == int(width) else 1)))
    return out


def cell_keys(parameters):
    return list(FIXED_KEYS) + list(parameters)


def cell_label(key):
    return FIXED_LABELS.get(key, key)


def cell_value(row, key):
    if key in FIXED_KEYS:
        return u"{0}".format(row.get(key) or u"")
    return u"{0}".format((row.get("params") or {}).get(key) or u"")


def set_cell(row, key, value):
    """Write one cell. Returns what it held before."""
    old = cell_value(row, key)
    value = u"{0}".format(value if value is not None else u"")
    if key in FIXED_KEYS:
        row[key] = value
    else:
        row.setdefault("params", {})[key] = value
    return old


def cell_range(anchor, target, keys):
    """Every cell in the rectangle between two cells, row by row - what a
    shift-click picks."""
    (row_a, key_a), (row_b, key_b) = anchor, target
    if key_a not in keys or key_b not in keys:
        return [target]
    first, last = sorted([keys.index(key_a), keys.index(key_b)])
    return [(row, key) for row in range(min(row_a, row_b), max(row_a, row_b) + 1)
            for key in keys[first:last + 1]]


def toggle_cell(cells, cell):
    """Ctrl-click: in if it was out, out if it was in."""
    if cell in cells:
        return [c for c in cells if c != cell]
    return list(cells) + [cell]


def column_cells(row_count, key):
    return [(row, key) for row in range(row_count)]


def apply_value(rows, cells, value):
    """The same value into every cell. Returns an undo list of the cells that
    actually changed: [(row, key, what it held)]."""
    undo = []
    for row_index, key in cells:
        if not 0 <= row_index < len(rows):
            continue
        if cell_value(rows[row_index], key) == value:
            continue
        undo.append((row_index, key, set_cell(rows[row_index], key, value)))
    return undo


def fill_series_cells(rows, cells):
    """Fill each picked column down from its top picked cell as a series -
    0013, 0014, 0015 - the way Ctrl+E does in the main table. A top cell with
    no number in it is numbered. Returns an undo list."""
    undo = []
    by_key = {}
    for row_index, key in cells:
        if 0 <= row_index < len(rows):
            by_key.setdefault(key, []).append(row_index)
    for key in by_key:
        indexes = sorted(set(by_key[key]))
        if len(indexes) < 2:
            continue
        seed = cell_value(rows[indexes[0]], key)
        plan = shtm_fill.fill_series([seed], len(indexes) - 1, True)
        for offset, row_index in enumerate(indexes[1:]):
            if cell_value(rows[row_index], key) == plan[offset]:
                continue
            undo.append((row_index, key,
                         set_cell(rows[row_index], key, plan[offset])))
    return undo


def undo_cells(rows, undo):
    """Put an undo list back, last change first."""
    for row_index, key, old in reversed(undo or []):
        if 0 <= row_index < len(rows):
            set_cell(rows[row_index], key, old)


def selection_label(cells):
    """What the fill bar says about the picked cells."""
    if not cells:
        return u""
    keys = []
    for _row, key in cells:
        if key not in keys:
            keys.append(key)
    count = shtm_core.plural(len(cells), u"cell")
    if len(keys) == 1:
        return u"{0} in {1}".format(count, cell_label(keys[0]))
    return u"{0} across {1}".format(count, shtm_core.plural(len(keys), u"column"))


# ====================== view template presets ======================
# What a template brings with it when it is added to the table of sets:
# {"number": .., "name": .., "view": .., "params": {parameter: value}}.
# Keyed by template NAME, not id, so a preset follows its template into every
# project that has a template of that name.

def preset_from_row(row, parameters):
    """A row's values as a preset - blanks left out, since a blank means
    "leave it" and should not overwrite a value another source has given."""
    preset = {"params": {}}
    for key in FIXED_KEYS:
        value = (row.get(key) or u"").strip()
        if value:
            preset[key] = value
    for parameter in parameters:
        value = ((row.get("params") or {}).get(parameter) or u"").strip()
        if value and value != LEAVE:
            preset["params"][parameter] = value
    return preset


def merge_preset(old, new, parameters):
    """Update a preset with what this project shows of it - and only that.

    A preset is kept by template name so it follows the template from project
    to project, and projects do not all have the same grouping parameters. The
    values for parameters this project does not have are not on screen, so
    they cannot have been changed here; replacing the whole preset with what
    is on screen would quietly delete them. So: the three replacements and
    this project's parameters come from `new` (a blank clears one), and every
    other parameter is kept from `old`.
    """
    merged = {"params": {}}
    for key in FIXED_KEYS:
        value = ((new or {}).get(key) or u"").strip()
        if value:
            merged[key] = value
    managed = set(parameters or [])
    for parameter, value in ((old or {}).get("params") or {}).items():
        if parameter not in managed and (value or u"").strip():
            merged["params"][parameter] = value
    for parameter, value in ((new or {}).get("params") or {}).items():
        if parameter in managed and (value or u"").strip():
            merged["params"][parameter] = value.strip()
    return merged


def preset_is_empty(preset):
    if not preset:
        return True
    if any((preset.get(key) or u"").strip() for key in FIXED_KEYS):
        return False
    return not any((v or u"").strip() for v in (preset.get("params") or {}).values())


def apply_preset(row, preset):
    """Fill a row from a preset. Only what the preset holds is written; a
    grouping parameter the preset says nothing about keeps the value the
    source sheets share."""
    for key in FIXED_KEYS:
        value = (preset.get(key) or u"").strip()
        if value:
            row[key] = value
    params = row.setdefault("params", {})
    for parameter, value in (preset.get("params") or {}).items():
        value = (value or u"").strip()
        if value and parameter in params:
            params[parameter] = value
    return row


def preset_summary(preset, parameters=None):
    """One line: what a preset will fill in."""
    if preset_is_empty(preset):
        return u"(empty)"
    parts = []
    for key in FIXED_KEYS:
        value = (preset.get(key) or u"").strip()
        if value:
            parts.append(u"{0} \u2192 {1}".format(cell_label(key), value))
    params = preset.get("params") or {}
    order = list(parameters or []) + sorted([p for p in params
                                             if p not in (parameters or [])])
    for parameter in order:
        value = (params.get(parameter) or u"").strip()
        if value:
            parts.append(u"{0}: {1}".format(_short_name(parameter), value))
    return u"   \u00b7   ".join(parts)


def _short_name(parameter):
    text = u"{0}".format(parameter)
    if u"_" in text:
        text = text.split(u"_", 1)[1]
    return text.replace(u"_", u" ")


def presets_from_text(text):
    """The settings value back into {template name: preset}. Anything that
    does not read is dropped rather than allowed to stop the window opening."""
    try:
        raw = json.loads(u"{0}".format(text or u"").strip() or u"{}")
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for name in raw:
        entry = raw[name]
        if not isinstance(entry, dict):
            continue
        preset = {"params": {}}
        for key in FIXED_KEYS:
            if entry.get(key):
                preset[key] = u"{0}".format(entry[key])
        params = entry.get("params")
        if isinstance(params, dict):
            for parameter in params:
                if params[parameter]:
                    preset["params"][u"{0}".format(parameter)] = (
                        u"{0}".format(params[parameter]))
        if not preset_is_empty(preset):
            out[u"{0}".format(name)] = preset
    return out


def presets_to_text(presets):
    """One line of JSON - escaped, so it can never break the key=value file it
    sits in, whatever the values hold."""
    clean = {}
    for name in presets or {}:
        if not preset_is_empty(presets[name]):
            clean[name] = presets[name]
    return json.dumps(clean, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"))


# ====================== each row's own status ======================

def row_states(rows, records, finds):
    """For every row: ("ok" | "todo" | "bad", the one line to show under it).

    "todo" is a row still missing something; "bad" is one whose sheets would
    clash or not change. The line is the row's first sheet, before and after,
    so each set can be read without going to the preview.
    """
    by_batch = {}
    for record in records or []:
        by_batch.setdefault(record.get("batch"), []).append(record)
    out = []
    for index, row in enumerate(rows):
        mine = by_batch.get(index, [])
        if not (row.get("number") or u"").strip():
            out.append(("todo", u"type what the sheet numbers' find text "
                                u"becomes"))
            continue
        if not (finds.get("number") or u"").strip():
            out.append(("todo", u"set the sheet number find text on the left"))
            continue
        bad = [r for r in mine if r.get("status") == "bad"]
        first = mine[0] if mine else None
        if bad:
            out.append(("bad", u"{0} - {1}".format(
                shtm_core.plural(len(bad), u"sheet"),
                bad[0]["values"].get(COL_STATUS, u""))))
            continue
        if first is None:
            out.append(("todo", u"tick some source sheets"))
            continue
        values = first["values"]
        out.append(("ok", u"{0}  \u2192  {1}     {2}".format(
            values.get(COL_SOURCE, u""), values.get(COL_NUMBER, u""),
            values.get(COL_NAME, u""))))
    return out


def readiness(sources, rows, finds, records):
    """Why Next should stay dark, or [] when it can light up."""
    reasons = []
    if not sources:
        reasons.append(u"tick at least one source sheet")
    if not (finds.get("number") or u"").strip():
        reasons.append(u"say what text to find in the sheet numbers")
    if not rows:
        reasons.append(u"add at least one view template to Sets to create")
    empty = [r["template_name"] for r in rows if not (r.get("number") or u"").strip()]
    if empty:
        reasons.append(u"give {0} a sheet number to replace with".format(
            u", ".join(empty[:3]) + (u"..." if len(empty) > 3 else u"")))
    bad = [r for r in records if r.get("status") == "bad"]
    if bad and not empty:
        reasons.append(u"{0} would clash or not change - {1}".format(
            shtm_core.plural(len(bad), u"sheet"),
            bad[0]["values"].get(COL_STATUS, u"")))
    return reasons


def example(sources, rows, finds):
    """The first source sheet run through the first row: one worked example
    under the find boxes, so the rule can be read where it is typed."""
    if not sources or not rows:
        return u""
    source = sources[0]
    row = rows[0]
    match_case = bool(finds.get("match_case"))
    number = shtm_core.apply_find_replace(source.get("number"), finds.get("number"),
                                          row.get("number"), match_case)
    name = shtm_core.apply_find_replace(source.get("name"),
                                        _kept(finds.get("name"), row.get("name")),
                                        row.get("name"), match_case)
    return u"e.g.  {0}  →  {1}\n       {2}  →  {3}".format(
        source.get("number"), number, source.get("name"), name)


# ====================== the views on each source sheet ======================

KIND_WORDS = {"legend": u"legend", "schedule": u"schedule", "drafting": u"drafting view"}


def source_view_lines(sheet_id, placements, views, options, find, match_case,
                      most=6):
    """What the source list shows under a sheet: every view on it, in order,
    each with what the run will do to it.

    Returns (lines, more). A line is {"name", "spans", "action", "note"}:
    `spans` marks what the view find catches - only on views the run copies,
    since a view placed again as it is (or left off) keeps its name.
    """
    on_sheet = []
    for placed in placements:
        if placed["sheet"] != sheet_id:
            continue
        view = views.get(placed["view"])
        if view is not None:
            on_sheet.append(view)
    on_sheet.sort(key=lambda v: shtm_core.natural_key(v.get("name", u"")))
    lines = []
    for view in on_sheet:
        action = shtm_plan.classify(view, options)
        name = view.get("name", u"")
        kind = KIND_WORDS.get(view.get("kind"), u"")
        if action == shtm_plan.SKIP:
            note = u"{0} - left off".format(kind or u"view")
            spans = [(name, False)]
        elif action == shtm_plan.REUSE:
            note = u"{0} - placed again as it is".format(kind or u"view")
            spans = [(name, False)]
        else:
            if action == shtm_plan.DEPENDENT:
                parent = views.get(view.get("primary", 0)) or {}
                note = u"dependent - a copy of {0} comes too".format(
                    parent.get("name", u"its parent"))
            else:
                note = kind
            spans = shtm_core.highlight_spans(name, find, match_case)
        lines.append({"name": name, "spans": spans, "action": action, "note": note})
    return lines[:most], max(0, len(lines) - most)


def view_examples(rows, batches):
    """For every set: the first of its views whose name changes, before and
    after, and how many more change - the line under the sheet example in
    Sets to create. A set whose views keep their names says so."""
    by_index = dict([(b["index"], b) for b in batches or []])
    out = []
    for index, _row in enumerate(rows):
        batch = by_index.get(index)
        if batch is None:
            out.append(u"")
            continue
        changed = [j for j in batch["plan"]["jobs"]
                   if j["action"] != shtm_plan.REUSE
                   and j.get("new_name") and j["new_name"] != j["name"]]
        if not changed:
            out.append(u"views keep their names")
            continue
        first = changed[0]
        text = u"view  {0}  →  {1}".format(first["name"], first["new_name"])
        if len(changed) > 1:
            text += u"     +{0} more".format(len(changed) - 1)
        out.append(text)
    return out


# ====================== saved text to find ======================

FIND_KEYS = ["number", "name", "view"]


def find_presets_from_text(text):
    """{preset name: {"number", "name", "view", "match_case"}} from settings.
    Anything that does not read is dropped."""
    try:
        raw = json.loads(u"{0}".format(text or u"").strip() or u"{}")
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for name in raw:
        entry = raw[name]
        if not isinstance(entry, dict) or not u"{0}".format(name).strip():
            continue
        preset = dict((key, u"{0}".format(entry.get(key) or u"")) for key in FIND_KEYS)
        preset["match_case"] = bool(entry.get("match_case"))
        if any(preset[key] for key in FIND_KEYS):
            out[u"{0}".format(name).strip()] = preset
    return out


def find_presets_to_text(presets):
    clean = {}
    for name in presets or {}:
        entry = presets[name]
        if any(entry.get(key) for key in FIND_KEYS):
            clean[name] = entry
    return json.dumps(clean, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def find_preset(finds):
    """The finds as they stand, as a preset."""
    preset = dict((key, u"{0}".format(finds.get(key) or u"")) for key in FIND_KEYS)
    preset["match_case"] = bool(finds.get("match_case"))
    return preset


def sorted_names(names):
    return sorted(names, key=shtm_core.natural_key)
