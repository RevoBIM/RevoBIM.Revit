# -*- coding: utf-8 -*-
"""The rows behind the table: filtering, sorting, grouping and the CSV export.

No .NET in here on purpose - this is the part that decides what the table
actually shows, so bench_logic.py runs it under plain CPython.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import shtm_core


FIXED_COLUMNS = [u"Sheet Number", u"Sheet Name"]
BLANK_LABEL = u"(blank)"


class Row(object):
    """One line in the table - either a sheet or a group header."""

    def __init__(self, kind, values=None, sheet=None, level=0,
                 label=u"", count=0, key=None):
        self.kind = kind
        self.values = values or {}
        self.sheet = sheet
        self.level = level
        self.label = label
        self.count = count
        self.key = key
        self.expanded = True
        # which top-level group this row sits in, counted from 0 in table
        # order: a heading and every row under it share one colour, the way
        # Excel for Revit bands its groups. None when the table is not grouped.
        self.band = None


MAX_SORTS = 6


class GridState(object):
    def __init__(self):
        self.columns = list(FIXED_COLUMNS)
        self.search_all = u""
        self.searches = {}
        self.filters = {}
        # sorting is a list of (column, ascending) with the primary first, so
        # shift clicking a second heading adds a level rather than replacing it
        self.sorts = [(u"Sheet Number", True)]
        self.group_by = []
        self.group_by_sort = True
        self.collapsed = set()
        # the decision the view is bound to: (sheet id, column) -> value, taken
        # at F5 and held until it is taken again. Never the values themselves -
        # a view bound to those re-evaluates the instant one changes, and the
        # row being typed into slides away mid-edit.
        self.overlay = {}
        # the sheets picked in Revit before the tool opened: when set, only
        # these are shown. Not a filter Clear filters takes away - it has its
        # own tick box, and unticking it is how every sheet comes back.
        self.only_ids = None

    def clear_filters(self):
        self.searches = {}
        self.filters = {}
        self.search_all = u""

    # ---- sorting ----

    def sort_keys(self):
        return [key for key, _up in self.sorts]

    def sort_index(self, key):
        """0 for the primary sort, 1 for the second, -1 for not sorted on."""
        keys = self.sort_keys()
        return keys.index(key) if key in keys else -1

    def sort_up(self, key):
        for name, up in self.sorts:
            if name == key:
                return up
        return True

    def toggle_sort(self, key, add_level=False):
        """A plain click sorts by that column alone and flips it if it is
        already the only sort. Shift adds a level, or flips one already there.
        """
        keys = self.sort_keys()
        if add_level:
            if key in keys:
                index = keys.index(key)
                self.sorts[index] = (key, not self.sorts[index][1])
            elif len(self.sorts) < MAX_SORTS:
                self.sorts.append((key, True))
            else:
                return False
            return True
        if len(self.sorts) == 1 and keys[0] == key:
            self.sorts = [(key, not self.sorts[0][1])]
        else:
            self.sorts = [(key, True)]
        return True

    def drop_missing_sorts(self):
        """A column taken out of the table cannot go on being sorted on."""
        kept = [pair for pair in self.sorts if pair[0] in self.columns]
        self.sorts = kept or [(self.columns[0], True)]

    # ---- grouping ----

    def grouping(self):
        """What the table actually groups by: the sort columns when 'group by
        sort' is on, otherwise whatever the three dropdowns say."""
        if self.group_by_sort:
            return [key for key, _up in self.sorts]
        return list(self.group_by)


# ====================== the row pipeline ======================

def matches(sheet, state, exclude=None, store=None):
    """Whether a sheet passes the search and every filter.

    `exclude` leaves one column's own filter out - the way Excel builds a
    column's tick list from what the *other* filters allow, so a value the
    column is hiding is still there to tick back on.

    `store` makes the test run against pending values instead of the model's:
    that is how the stale count is worked out, never how the rows are drawn.
    """
    def value_of(column):
        if store is not None:
            return u"{0}".format(store.value_of(sheet, column) or u"")
        return snapshot_value(sheet, column, state)

    only = getattr(state, "only_ids", None)
    if only is not None and sheet.get("id") not in only:
        return False
    text_all = (state.search_all or u"").strip().lower()
    if text_all:
        joined = u" ".join([value_of(c) for c in state.columns]).lower()
        for word in text_all.split():
            if word not in joined:
                return False
    for key in state.searches:
        if key == exclude:
            continue
        needle = (state.searches.get(key) or u"").strip().lower()
        if not needle:
            continue
        if needle not in value_of(key).lower():
            return False
    for key in state.filters:
        if key == exclude:
            continue
        allowed = state.filters.get(key)
        if allowed is None:
            continue
        if value_of(key) not in allowed:
            return False
    return True


def snapshot_value(sheet, column, state):
    """What the view sorts and filters on: the value taken at the last F5, or
    the model's if none has been taken."""
    held = state.overlay.get((sheet["id"], column))
    if held is not None:
        return u"{0}".format(held)
    return u"{0}".format(sheet["values"].get(column, u"") or u"")


def values_allowed(sheets, state, key):
    """The values a column's tick list should offer: those on the sheets the
    other filters let through, with counts. The column's own filter is left
    out, so it can be widened again as well as narrowed."""
    counts = {}
    for sheet in sheets:
        if not matches(sheet, state, exclude=key):
            continue
        value = snapshot_value(sheet, key, state)
        counts[value] = counts.get(value, 0) + 1
    return counts


def stale_count(sheets, state, store):
    """How many rows are sitting out of place because of a pending edit.

    Everything visible is a snapshot: the rows are filtered and sorted on the
    model's values, and an edit does not move its row or make it vanish under
    the cursor. F5 re-takes the snapshot. Until then the status line says how
    many rows would move, so a stale view is never silent.
    """
    if store is None or not store.count():
        return 0
    touched = set([key[0] for key in store.pending])
    moved = 0
    for sheet in sheets:
        if sheet["id"] not in touched:
            continue
        now = matches(sheet, state)
        then = matches(sheet, state, store=store)
        if now != then:
            moved += 1
            continue
        if now and _sort_key(sheet, state) != _sort_key(sheet, state, store):
            moved += 1
    return moved


def _sort_key(sheet, state, store=None):
    out = []
    for key, _up in state.sorts or []:
        if store is not None:
            out.append(shtm_core.natural_key(store.value_of(sheet, key)))
        else:
            out.append(shtm_core.natural_key(snapshot_value(sheet, key, state)))
    return out


def take_snapshot(sheets, state, store):
    """F5. Re-take the filter, the sort and the grouping together, against the
    values as they now stand including the staged edits."""
    overlay = {}
    if store is not None:
        for key in store.pending:
            overlay[key] = store.pending[key]
    state.overlay = overlay


def compute_rows(sheets, state):
    """Filter, sort, then group into the flat list the grid draws."""
    kept = [s for s in sheets if matches(s, state)]
    # least significant level first, because Python's sort is stable - which is
    # what makes a second and third sort level fall out for free
    for key, up in reversed(state.sorts or [(u"Sheet Number", True)]):
        # reverse=True, never a sort followed by list.reverse() - reversing the
        # list also reverses the order the levels below it put equal values in,
        # which quietly undoes the second and third sort
        kept.sort(key=lambda s: shtm_core.natural_key(
            snapshot_value(s, key, state)), reverse=not up)

    levels = state.grouping()
    if not levels:
        return [Row("sheet", s["values"], s) for s in kept], len(kept)

    rows = []
    previous = []
    # a stable grouping: keep the sheet order and start a group where its first
    # sheet appears, the way a drawing register reads
    buckets = []
    index = {}
    for sheet in kept:
        path = tuple([snapshot_value(sheet, level, state) or BLANK_LABEL
                      for level in levels])
        if path not in index:
            index[path] = len(buckets)
            buckets.append((path, []))
        buckets[index[path]][1].append(sheet)

    counts = {}
    bands = {}
    for path, members in buckets:
        for depth in range(1, len(path) + 1):
            counts[path[:depth]] = counts.get(path[:depth], 0) + len(members)
        if path[:1] not in bands:
            bands[path[:1]] = len(bands)

    for path, members in buckets:
        for depth in range(len(path)):
            partial = path[:depth + 1]
            if depth < len(previous) and previous[:depth + 1] == list(partial):
                continue
            buried = False
            for shallower in range(depth):
                if path[:shallower + 1] in state.collapsed:
                    buried = True
                    break
            if buried:
                continue
            row = Row("group", level=depth, label=partial[-1],
                      count=counts.get(partial, 0), key=partial)
            row.expanded = partial not in state.collapsed
            row.band = bands.get(partial[:1])
            rows.append(row)
        previous = list(path)
        hidden = False
        for depth in range(len(path)):
            if path[:depth + 1] in state.collapsed:
                hidden = True
                break
        if hidden:
            continue
        for sheet in members:
            row = Row("sheet", sheet["values"], sheet, level=len(path))
            row.band = bands.get(path[:1])
            rows.append(row)
    return rows, len(kept)


def export_csv(rows, columns, path):
    lines = [u",".join([_csv(c) for c in columns])]
    for row in rows:
        if row.kind != "sheet":
            continue
        lines.append(u",".join([_csv(row.values.get(c, u"")) for c in columns]))
    handle = open(path, "wb")
    try:
        handle.write((u"\n".join(lines) + u"\n").encode("utf-8-sig"))
    finally:
        handle.close()
    return path


def _csv(value):
    text = u"" if value is None else u"{0}".format(value)
    if u"," in text or u'"' in text or u"\n" in text:
        return u'"{0}"'.format(text.replace(u'"', u'""'))
    return text
