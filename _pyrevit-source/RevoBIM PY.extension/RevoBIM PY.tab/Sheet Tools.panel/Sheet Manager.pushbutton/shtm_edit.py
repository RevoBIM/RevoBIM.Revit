# -*- coding: utf-8 -*-
"""Editing the table: everything that decides what a cell should become.

No .NET in here on purpose. The pending-edit store, find and replace, prefix
and suffix, fill down, and the diff of an imported spreadsheet against the
table are all rules, and rules belong where bench_logic.py can run them.

The one principle: **nothing is written until Apply.** Every operation here
produces pending edits - (sheet id, column, new value) - and the store keeps
them until the window hands them to Revit in one go. A pending edit whose value
is the same as what the sheet already has is not an edit and is not kept.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import shtm_core

# the two columns that are not parameters
NUMBER = u"Sheet Number"
NAME = u"Sheet Name"


# where a pending edit came from, which is also the colour it paints
EDITED = "edited"        # typed, filled, pasted, find-and-replaced: green
IMPORTED = "imported"    # from an Excel import: teal
REFUSED = "refused"      # Revit refused it on the last Apply: strong red


class EditStore(object):
    """Pending edits keyed by (sheet id, column), with a history.

    Undo and redo work in batches: one operation, however many cells, is one
    step. Every way of making an edit goes through `take`, which records the
    batch, so nothing can change a cell without being undoable.
    """

    def __init__(self):
        self.pending = {}
        self.originals = {}
        self.origin = {}
        self.refused = {}
        self.undo_stack = []
        self.redo_stack = []
        self.copied = set()

    # ---- single cells ----

    def set(self, sheet_id, column, original, new, origin=EDITED):
        key = (sheet_id, column)
        original = u"{0}".format(original if original is not None else u"")
        new = u"{0}".format(new if new is not None else u"")
        self.refused.pop(key, None)
        was_pending = self.pending.get(key)
        if new == original:
            self.pending.pop(key, None)
            self.originals.pop(key, None)
            self.origin.pop(key, None)
            return was_pending is not None
        self.pending[key] = new
        self.originals[key] = original
        self.origin[key] = origin
        # "changed" means the pending state changed, not that new differs from
        # the original - setting a cell to what is already pending is nothing
        return was_pending != new

    def get(self, sheet_id, column):
        return self.pending.get((sheet_id, column))

    def has(self, sheet_id, column):
        return (sheet_id, column) in self.pending

    def state_of(self, sheet_id, column):
        """The paint state for a cell: edited, imported, refused, copied or
        None. A refusal outranks everything - it has to stay readable - and a
        copy mark never covers a pending edit."""
        key = (sheet_id, column)
        if key in self.refused:
            return REFUSED
        if key in self.pending:
            return self.origin.get(key, EDITED)
        if key in self.copied:
            return "copied"
        return None

    def drop(self, sheet_id, column):
        key = (sheet_id, column)
        self.pending.pop(key, None)
        self.originals.pop(key, None)
        self.origin.pop(key, None)

    def clear(self):
        self.pending = {}
        self.originals = {}
        self.origin = {}
        self.refused = {}
        self.undo_stack = []
        self.redo_stack = []

    def count(self):
        return len(self.pending)

    def sheets_touched(self):
        return len(set([key[0] for key in self.pending]))

    def value_of(self, sheet, column):
        """What the cell shows: the pending value if there is one, else the
        sheet's own."""
        held = self.pending.get((sheet["id"], column))
        if held is not None:
            return held
        return sheet["values"].get(column, u"")

    def jobs(self):
        """The edits as a list the writer can walk, one per cell."""
        out = []
        for key in sorted(self.pending.keys(), key=lambda k: (k[0], k[1])):
            out.append({"id": key[0], "column": key[1],
                        "value": self.pending[key],
                        "was": self.originals.get(key, u"")})
        return out

    # ---- batches ----

    def take(self, edits, origin=EDITED):
        """Absorb a list of (sheet id, column, original, new) as one undo
        step. Returns how many actually changed something."""
        before = self._snapshot([(e[0], e[1]) for e in edits])
        changed = 0
        for sheet_id, column, original, new in edits:
            if self.set(sheet_id, column, original, new, origin):
                changed += 1
        after = self._snapshot([(e[0], e[1]) for e in edits])
        if before != after:
            self.undo_stack.append((before, after))
            self.redo_stack = []
        return changed

    def _snapshot(self, keys):
        out = {}
        for key in set(keys):
            if key in self.pending:
                out[key] = (self.pending[key], self.originals.get(key, u""),
                            self.origin.get(key, EDITED))
            else:
                out[key] = None
        return out

    def _restore(self, snapshot):
        for key in snapshot:
            held = snapshot[key]
            if held is None:
                self.pending.pop(key, None)
                self.originals.pop(key, None)
                self.origin.pop(key, None)
            else:
                self.pending[key], self.originals[key], self.origin[key] = held
            self.refused.pop(key, None)

    def undo(self):
        if not self.undo_stack:
            return False
        before, after = self.undo_stack.pop()
        self._restore(before)
        self.redo_stack.append((before, after))
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        before, after = self.redo_stack.pop()
        self._restore(after)
        self.undo_stack.append((before, after))
        return True

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    # ---- after an Apply ----

    def mark_refused(self, sheet_id, column, reason=u""):
        """Revit refused this write. It stays pending and paints strong red,
        so it can be looked at and tried again."""
        self.refused[(sheet_id, column)] = reason or u"refused"

    def refused_reason(self, sheet_id, column):
        return self.refused.get((sheet_id, column))

    # ---- copy marks ----

    def mark_copied(self, keys):
        self.copied = set(keys)

    def clear_copied(self):
        self.copied = set()


# ====================== bulk operations ======================
# each returns a list of (sheet id, column, original, new) for the store

def find_replace(sheets, columns, find, replace, match_case=False, store=None):
    """Find and replace across the chosen columns of the chosen sheets. The
    search runs against the value the cell currently shows - a pending edit is
    replaced again, not the sheet's original - so two passes stack the way they
    would in Excel."""
    edits = []
    if not find:
        return edits
    for sheet in sheets:
        for column in columns:
            if not writable(sheet, column):
                continue
            current = _current(sheet, column, store)
            new = shtm_core.apply_find_replace(current, find, replace, match_case)
            if new != current:
                edits.append((sheet["id"], column, current, new))
    return edits


def affix(sheets, columns, prefix=u"", suffix=u"", store=None):
    edits = []
    if not prefix and not suffix:
        return edits
    for sheet in sheets:
        for column in columns:
            if not writable(sheet, column):
                continue
            current = _current(sheet, column, store)
            new = u"{0}{1}{2}".format(prefix or u"", current, suffix or u"")
            if new != current:
                edits.append((sheet["id"], column, current, new))
    return edits


def fill_down(sheets, column, value, store=None):
    """One value into one column for every chosen sheet - Excel's fill down,
    without needing the rows to be next to each other."""
    edits = []
    for sheet in sheets:
        if not writable(sheet, column):
            continue
        current = _current(sheet, column, store)
        if value != current:
            edits.append((sheet["id"], column, current, value))
    return edits


def set_value(sheet, column, value, store=None):
    current = _current(sheet, column, store)
    if value == current:
        return []
    return [(sheet["id"], column, current, value)]


def writable(sheet, column):
    """A parameter the sheet will not let anyone write is refused before Apply
    rather than after: a red row in a results window is a worse way to learn
    it than a cell that would not take the edit."""
    return column not in (sheet.get("readonly") or ())


def _current(sheet, column, store):
    if store is not None:
        held = store.get(sheet["id"], column)
        if held is not None:
            return held
    return u"{0}".format(sheet["values"].get(column, u"") or u"")


# ====================== round trip ======================

def export_rows(sheets, columns, store=None):
    """The table as a list of rows, header first, showing pending values -
    what you see is what you export."""
    rows = [list(columns)]
    for sheet in sheets:
        rows.append([_current(sheet, column, store) for column in columns])
    return rows


def import_diff(sheets, columns, rows, key_column=NUMBER):
    """Turn an imported spreadsheet back into pending edits.

    Rows are matched to sheets on the key column - the sheet number - so a
    spreadsheet can be sorted, filtered and have rows deleted and still come
    back in. A column the table does not carry is ignored rather than refused,
    a row whose number matches nothing is reported, and the key column itself
    is never written from the file, because that is the thing rows are matched
    on.

    Returns (edits, unknown_keys, ignored_columns).
    """
    if not rows:
        return [], [], []
    header = [u"{0}".format(h or u"").strip() for h in rows[0]]
    if key_column not in header:
        return [], [], [u"no '{0}' column in the file".format(key_column)]
    key_at = header.index(key_column)
    wanted = {}
    ignored = []
    for index, name in enumerate(header):
        if index == key_at or not name:
            continue
        if name in columns:
            wanted[index] = name
        else:
            ignored.append(name)

    by_key = {}
    for sheet in sheets:
        by_key[u"{0}".format(sheet["values"].get(key_column, u"")).strip()] = sheet

    edits = []
    unknown = []
    for row in rows[1:]:
        if key_at >= len(row):
            continue
        key = u"{0}".format(row[key_at] or u"").strip()
        if not key:
            continue
        sheet = by_key.get(key)
        if sheet is None:
            unknown.append(key)
            continue
        for index in wanted:
            if index >= len(row):
                continue
            if not writable(sheet, wanted[index]):
                continue
            new = u"{0}".format(row[index] if row[index] is not None else u"")
            current = u"{0}".format(sheet["values"].get(wanted[index], u"") or u"")
            if new != current:
                edits.append((sheet["id"], wanted[index], current, new))
    return edits, unknown, ignored


# ====================== CSV ======================

def to_csv(rows):
    lines = []
    for row in rows:
        lines.append(u",".join([_csv_cell(cell) for cell in row]))
    return u"\r\n".join(lines) + u"\r\n"


def _csv_cell(value):
    text = u"{0}".format(value if value is not None else u"")
    if any(ch in text for ch in u",\"\r\n"):
        return u"\"{0}\"".format(text.replace(u"\"", u"\"\""))
    return text


def from_csv(text):
    """A small RFC 4180 reader: quoted fields, doubled quotes, newlines inside
    quotes. Enough for what Excel writes."""
    rows = []
    row = []
    field = []
    quoted = False
    index = 0
    text = text or u""
    length = len(text)
    while index < length:
        ch = text[index]
        if quoted:
            if ch == u"\"":
                if index + 1 < length and text[index + 1] == u"\"":
                    field.append(u"\"")
                    index += 1
                else:
                    quoted = False
            else:
                field.append(ch)
        else:
            if ch == u"\"":
                quoted = True
            elif ch == u",":
                row.append(u"".join(field))
                field = []
            elif ch == u"\n" or ch == u"\r":
                if ch == u"\r" and index + 1 < length and text[index + 1] == u"\n":
                    index += 1
                row.append(u"".join(field))
                field = []
                rows.append(row)
                row = []
            else:
                field.append(ch)
        index += 1
    if field or row:
        row.append(u"".join(field))
        rows.append(row)
    return [r for r in rows if any(cell.strip() for cell in r)]


# ====================== what Apply will do ======================

def apply_summary(store):
    jobs = store.jobs()
    if not jobs:
        return u"nothing to apply"
    by_column = {}
    for job in jobs:
        by_column[job["column"]] = by_column.get(job["column"], 0) + 1
    lines = [u"{0} cell(s) on {1} sheet(s):".format(len(jobs), store.sheets_touched())]
    for column in sorted(by_column):
        lines.append(u"  {0}: {1}".format(column, by_column[column]))
    return u"\n".join(lines)


def blockers(store, sheets):
    """Edits Apply must refuse: a sheet number that would collide with another
    sheet, or with another pending number. Names and parameters can be
    anything."""
    problems = []
    numbers = {}
    for sheet in sheets:
        numbers[sheet["id"]] = u"{0}".format(sheet["values"].get(NUMBER, u"")).strip()
    for job in store.jobs():
        if job["column"] == NUMBER:
            numbers[job["id"]] = job["value"].strip()
    seen = {}
    for sheet_id in numbers:
        value = numbers[sheet_id]
        if not value:
            if store.has(sheet_id, NUMBER):
                problems.append(u"sheet {0}: the number cannot be blank".format(
                    store.originals.get((sheet_id, NUMBER), sheet_id)))
            continue
        key = value.lower()
        if key in seen and seen[key] != sheet_id:
            problems.append(u"'{0}' would be used by two sheets".format(value))
        seen[key] = sheet_id
    return problems
