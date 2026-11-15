# -*- coding: utf-8 -*-
"""The Revision Manager's model: read, stage, and write the project's revisions.

What Revit's own Sheet Issues/Revisions dialog does - add, delete, edit, move
up and down, merge up and down, Per Project / Per Sheet numbering, arc length -
plus what it does not: how many sheets each revision is on, a search on every
column, several rows moved at once, and a question before a revision that is
in use is deleted.

**Nothing is written until Apply.** Every change is staged in a ``Staging``
and shown green; Apply turns the staging into a ``plan`` and the plan is
written in one transaction on Revit's thread. The staging and the plan are
plain Python with no WPF and no Revit in them, so the bench drives them
directly - the window is only a view of a ``Staging``.

The order the plan is written in matters, because Revit locks an issued
revision against edits and only merges revisions that sit next to each other:

1. numbering mode and arc length
2. revisions being un-issued are un-issued first, so they can be edited
3. new revisions are created
4. field edits
5. merges - each one moved next to its target first, then combined
6. deletes
7. the final order
8. revisions being issued are issued last, after their edits
9. the extra columns are stored, and pushed into their parameters - last,
   so a sheet's current revision is the one it will have from now on

Each step is tried on its own. One that Revit refuses is reported and the
rest still go in, the way an export run reports a sheet that failed.
"""

import ps_refs  # noqa: F401  - must be first

from Autodesk.Revit.DB import (ElementId, FilteredElementCollector, Revision,
                               RevisionCloud, RevisionNumbering,
                               RevisionSettings, RevisionVisibility,
                               Transaction, Viewport, ViewSheet)

# Revision numbering sequences arrived in Revit 2022; before that each
# revision carried its own NumberType. The name is asked for on its own,
# because ONE missing name in a grouped import throws at load - and this
# module is imported by the Document Register, which is imported by the
# main window, so Revit 2021 got "Cannot import name
# RevisionNumberingSequence" and no tool at all. Without it the Numbering
# column is empty and says why; everything else works.
try:
    from Autodesk.Revit.DB import RevisionNumberingSequence
except Exception:
    RevisionNumberingSequence = None

import ps_model
import ps_register
import ps_revdata


# The editable fields, in the order the window shows them.
FIELDS = ['numbering', 'date', 'desc', 'issued', 'issued_to', 'issued_by',
          'show']
TEXT_FIELDS = ['date', 'desc', 'issued_to', 'issued_by']

# The fields that never take one value across several selected revisions.
ALL_AT_ONCE_REFUSED = ('date',)

# Show, as Revit's dialog words it, against RevisionVisibility's names.
SHOW_CHOICES = [(u'None', 'Hidden'), (u'Tag', 'TagVisible'),
                (u'Cloud and Tag', 'CloudAndTagVisible')]
SHOW_LABELS = [label for label, _name in SHOW_CHOICES]
DEFAULT_SHOW = u'Cloud and Tag'

PER_PROJECT = 'PerProject'
PER_SHEET = 'PerSheet'

FEET_TO_MM = 304.8


def show_label(visibility_name):
    """'CloudAndTagVisible' -> 'Cloud and Tag'."""
    name = u'{0}'.format(visibility_name or u'').strip()
    for label, enum_name in SHOW_CHOICES:
        if enum_name.lower() == name.lower() or label.lower() == name.lower():
            return label
    return DEFAULT_SHOW


def show_name(label):
    """'Cloud and Tag' -> 'CloudAndTagVisible'."""
    text = u'{0}'.format(label or u'').strip().lower()
    for choice, enum_name in SHOW_CHOICES:
        if choice.lower() == text or enum_name.lower() == text:
            return enum_name
    return 'CloudAndTagVisible'


class Entry(object):
    """One revision, as read and as staged."""

    def __init__(self, key, element_key=None, sequence=0, fields=None,
                 sheets=None, clouds=0, uid=u'', custom=None):
        self.key = u'{0}'.format(key)
        self.uid = uid
        # The extra columns: {column id: value as stored}.
        self.custom = dict(custom or {})
        self.original_custom = None if element_key is None \
            else dict(self.custom)
        self.element_key = element_key          # None for a new revision
        self.sequence = sequence                # as read; 0 for a new one
        self.fields = dict(fields or {})
        for field in FIELDS:
            self.fields.setdefault(field, False if field == 'issued' else u'')
        self.original = None if element_key is None else dict(self.fields)
        self.sheets = list(sheets or [])        # sheet numbers carrying it
        # The sheet series of those sheets, each once, in natural order.
        self.series = []
        self.clouds = int(clouds or 0)
        # Its clouds by the view they are drawn in, {view key: [cloud
        # keys]}; and those views that are on no sheet, [(view key, name,
        # clouds)] - a revision "on 0 sheets" can still have clouds there.
        self.cloud_views = {}
        self.off_views = []
        self.deleted = False
        self.merged_into = None                 # the key it merges into

    @property
    def is_new(self):
        return self.element_key is None

    @property
    def live(self):
        return not self.deleted and self.merged_into is None

    @property
    def used(self):
        return len(self.sheets)

    @property
    def unplaced(self):
        """How many of its clouds are in views placed on no sheet."""
        return sum([count for _view, _name, count in self.off_views])

    def originally_issued(self):
        return bool(self.original and self.original.get('issued'))


# ==========================================================================
# pure decisions - bench-tested
# ==========================================================================

def move_within(keys, selected, step):
    """``keys`` with every selected one moved ``step`` (-1 up, 1 down).

    A selected block moves as a block; one already at the end it is moving
    towards stays put, and so does the rest of its block behind it - the
    way a list in Revit or Explorer behaves with several rows picked.
    """
    result = list(keys)
    picked = set(selected or ())
    if step < 0:
        for index in range(1, len(result)):
            if result[index] in picked and result[index - 1] not in picked:
                result[index - 1], result[index] = \
                    result[index], result[index - 1]
    elif step > 0:
        for index in range(len(result) - 2, -1, -1):
            if result[index] in picked and result[index + 1] not in picked:
                result[index + 1], result[index] = \
                    result[index], result[index + 1]
    return result


def move_keeping(order, movable, selected, step):
    """Move among ``movable`` keys only; the rest keep their places.

    Rows staged for deletion stay where they are, struck through, rather
    than being shuffled by a move they have no part in.
    """
    movable = set(movable)
    slots = [index for index, key in enumerate(order) if key in movable]
    moved = move_within([order[index] for index in slots], selected, step)
    result = list(order)
    for slot, key in zip(slots, moved):
        result[slot] = key
    return result


def insert_at(order, live, key, position):
    """``order`` with ``key`` put in so that it is ``position`` among the
    live revisions (1 = first), ahead of whichever live one held that place.

    Rows staged to go stay where they are - they keep their slot in
    ``order`` but are not counted, which is how Revit will number them
    once they are gone. Past the end, or None, is last.
    """
    order = [one for one in order if one != key]
    live = [one for one in live if one != key]
    try:
        position = int(position)
    except Exception:
        position = len(live) + 1
    if position < 1:
        position = 1
    if position > len(live):
        return order + [key]
    ahead_of = live[position - 1]
    index = order.index(ahead_of)
    return order[:index] + [key] + order[index:]


def matches(values, filters):
    """Whether a row's display values pass every column's search.

    Each search is a case-insensitive "contains"; an empty one passes
    everything. All of them have to pass, as the register's filters do.
    """
    for field, needle in (filters or {}).items():
        needle = u'{0}'.format(needle or u'').strip().lower()
        if not needle:
            continue
        if needle not in u'{0}'.format(values.get(field, u'')).lower():
            return False
    return True


def passes_picks(tokens_of, picks, skip=None):
    """Whether a row passes every column's value filter.

    ``tokens_of(field)`` gives the row's values in that column as a list -
    one for most columns, one per series for Sheet series. ``picks`` is
    {field: set of allowed values}, u'' standing for a blank cell; a column
    with no entry is not filtered. A row passes a column when any of its
    values is allowed - a revision on BW and EC shows under either. ``skip``
    leaves one column out, for that column's own list (Excel's rule).
    """
    for field, allowed in (picks or {}).items():
        if field == skip or allowed is None:
            continue
        tokens = tokens_of(field) or [u'']
        if not [token for token in tokens if token in allowed]:
            return False
    return True


class Staging(object):
    """Every change the window has made, none of them written yet."""

    def __init__(self, entries, numbering=PER_PROJECT, arc_mm=0.0,
                 sequences=None, columns=None):
        self.entries = dict([(entry.key, entry) for entry in entries])
        if columns is None:
            columns = ps_revdata.default_columns()
        self.columns = [column.copy() for column in columns]
        self.original_columns = [column.copy() for column in columns]
        # "Push to parameters" pressed: push even with nothing else staged.
        self.push_requested = False
        self.order = [entry.key for entry in
                      sorted(entries, key=lambda one: one.sequence)]
        self.original_order = list(self.order)
        self.sequences = list(sequences or [])
        self.settings = {'numbering': numbering, 'arc_mm': float(arc_mm)}
        self.original_settings = dict(self.settings)
        self._new = 0

    # -------------------------------------------------------------- reading
    def live_order(self):
        return [key for key in self.order if self.entries[key].live]

    def staged_sequence(self, key):
        live = self.live_order()
        return live.index(key) + 1 if key in live else None

    def locked(self, key):
        """Issued as staged: Revit will not edit an issued revision."""
        return bool(self.entries[key].fields.get('issued'))

    def changed(self, key):
        """The fields of one row that differ from the model, plus 'seq'."""
        entry = self.entries[key]
        if entry.is_new:
            return set(FIELDS) | set(['seq']) | \
                set([u'x_' + column.id for column in self.columns])
        found = set([field for field in FIELDS
                     if entry.fields.get(field) != entry.original.get(field)])
        for column in self.columns:
            if self.custom_value(entry, column) != \
                    self.custom_value(entry, column, original=True):
                found.add(u'x_' + column.id)
        staged = self.staged_sequence(key)
        if staged is not None and staged != self._original_position(key):
            found.add('seq')
        return found

    def _original_position(self, key):
        """Where a surviving revision would sit with no move staged."""
        survivors = [one for one in self.original_order
                     if self.entries[one].live]
        return survivors.index(key) + 1 if key in survivors else None

    def pending(self, key):
        """What is staged for a row, in a word: the Sequence cell's
        tooltip, and what the Change column said before 1.35.0."""
        entry = self.entries[key]
        if entry.merged_into is not None:
            target = self.staged_sequence(entry.merged_into)
            return u'Merge into {0}'.format(target if target else u'?')
        if entry.deleted:
            return u'Delete'
        if entry.is_new:
            return u'New'
        changed = self.changed(key)
        if not changed:
            return u''
        if changed == set(['seq']):
            return u'Moved'
        if not [name for name in changed if not name.startswith(u'x_')]:
            return u'Notes'
        return u'Edited'

    # ---------------------------------------------------------- extra columns
    def column(self, column_id):
        for column in self.columns:
            if column.id == column_id:
                return column
        return None

    @staticmethod
    def custom_value(entry, column, original=False):
        """A row's value in an extra column, normalised for comparing."""
        source = entry.original_custom if original else entry.custom
        value = (source or {}).get(column.id, u'')
        if column.kind == 'yesno':
            return u'1' if value == u'1' else u'0'
        return u'{0}'.format(value or u'')

    def columns_changed(self):
        if len(self.columns) != len(self.original_columns):
            return True
        return not all([one.same(other) for one, other in
                        zip(self.columns, self.original_columns)])

    def set_custom(self, key, column_id, value):
        """(ok, message). Issued revisions take these too: they are the
        tool's own data, not Revit's, and notes are written after issue."""
        entry = self.entries.get(key)
        column = self.column(column_id)
        if entry is None or column is None:
            return False, u'No such column.'
        if not entry.live:
            return False, u'That revision is staged to go - restore it to ' \
                u'edit it.'
        ok, stored = ps_revdata.normalise(column, value)
        if not ok:
            return False, stored
        entry.custom[column.id] = stored
        return True, u''

    def set_field_many(self, keys, field, value):
        """One value into several revisions: (changed keys, refusals).

        Each is set on its own, so an issued one refuses for itself and the
        rest still take it. Never the Date: a date belongs to one issue,
        and the same date on several revisions is a slip, not an edit.
        """
        if field in ALL_AT_ONCE_REFUSED:
            return [], [u'The {0} is set one revision at a time.'.format(
                field)]
        changed, refusals = [], []
        for key in keys:
            ok, message = self.set_field(key, field, value)
            if ok:
                changed.append(key)
            elif message not in refusals:
                refusals.append(message)
        return changed, refusals

    def edit(self, key, fields, custom=None):
        """Everything from the Edit revision window, staged in the order
        Revit will take it: an Issued tick coming off goes first, so the
        rest can change; one going on goes last, after them. Returns the
        refusals - empty when all of it went in."""
        entry = self.entries.get(key)
        if entry is None:
            return [u'That revision is no longer in the project.']
        refusals = []
        wanted = (fields or {}).get('issued')
        was = bool(entry.fields.get('issued'))
        if wanted is not None and was and not wanted:
            self.set_field(key, 'issued', False)
        for field, value in (fields or {}).items():
            if field == 'issued':
                continue
            if u'{0}'.format(entry.fields.get(field) or u'') == \
                    u'{0}'.format(value or u''):
                continue
            ok, message = self.set_field(key, field, value)
            if not ok and message not in refusals:
                refusals.append(message)
        for column_id, value in (custom or {}).items():
            ok, message = self.set_custom(key, column_id, value)
            if not ok and message not in refusals:
                refusals.append(message)
        if wanted is not None and not was and wanted:
            self.set_field(key, 'issued', True)
        return refusals

    def set_custom_many(self, keys, column_id, value):
        """set_field_many for the manager's own columns."""
        changed, refusals = [], []
        for key in keys:
            ok, message = self.set_custom(key, column_id, value)
            if ok:
                changed.append(key)
            elif message not in refusals:
                refusals.append(message)
        return changed, refusals

    def add_column(self, name, kind, choices=None, target=u'', parameter=u'',
                   group=u''):
        """(ok, the new column's id, or why not). An Issued To or Method
        column is Yes/No whatever ``kind`` says."""
        if group in (ps_revdata.ISSUED_TO, ps_revdata.METHOD):
            kind, choices = 'yesno', []
        problem = ps_revdata.column_problem(name, kind, choices, self.columns)
        if problem:
            return False, problem
        if group == ps_revdata.STATUS and \
                ps_revdata.status_column(self.columns) is not None:
            return False, u'There is already an Issue Status column.'
        column = ps_revdata.Column(ps_revdata.new_column_id(self.columns),
                                   name, kind, choices, target, parameter,
                                   group)
        self.columns.append(column)
        return True, column.id

    def update_column(self, column_id, name, choices=None, target=u'',
                      parameter=u'', group=None):
        """Rename, re-choose, re-map - and, for a Yes/No column, move it
        between the Issued To and Method groups (``group`` None keeps it)."""
        column = self.column(column_id)
        if column is None:
            return False, u'No such column.'
        if group is not None and group != column.group:
            movable = (ps_revdata.ISSUED_TO, ps_revdata.METHOD, u'')
            if column.kind != 'yesno' or group not in movable or \
                    column.group == ps_revdata.STATUS:
                return False, u'Only a Yes/No column can join Issued To or ' \
                    u'Method.'
            column.group = group
        problem = ps_revdata.column_problem(name, column.kind, choices,
                                            self.columns, column_id)
        if problem:
            return False, problem
        column.name = u'{0}'.format(name).strip()
        column.choices = [u'{0}'.format(one).strip() for one in choices or []
                          if u'{0}'.format(one).strip()]
        column.target = target if target in ps_revdata.TARGET_LABELS else u''
        column.parameter = u'{0}'.format(parameter or u'').strip()
        return True, u''

    def fill_statuses(self, statuses):
        """Stage each revision's Issue Status from its sheets, where it has
        none stored: ``statuses`` is {revision key: status text}. Returns
        the keys filled. The value is then kept with the revision, so an
        old issue keeps its status when the sheets move on."""
        column = ps_revdata.status_column(self.columns)
        if column is None:
            return []
        filled = []
        for key in self.order:
            entry = self.entries[key]
            wanted = u'{0}'.format(statuses.get(key) or u'').strip()
            if not wanted or not entry.live or \
                    self.custom_value(entry, column):
                continue
            entry.custom[column.id] = wanted
            filled.append(key)
        return filled

    def remove_column(self, column_id):
        before = len(self.columns)
        self.columns = [column for column in self.columns
                        if column.id != column_id]
        return len(self.columns) != before

    def custom_changed(self):
        for key in self.order:
            entry = self.entries[key]
            if not entry.live:
                continue
            if entry.is_new and [value for value in entry.custom.values()
                                 if value not in (u'', u'0')]:
                return True
            if not entry.is_new and [name for name in self.changed(key)
                                     if name.startswith(u'x_')]:
                return True
        return self.columns_changed()

    def settings_changed(self):
        return set([name for name in self.settings
                    if self.settings[name] != self.original_settings[name]])

    def change_count(self):
        count = len(self.settings_changed())
        if self.columns_changed():
            count += 1
        if self.push_requested:
            count += 1
        for key in self.order:
            entry = self.entries[key]
            if entry.is_new or not entry.live or self.changed(key):
                count += 1
        return count

    def dirty(self):
        return self.change_count() > 0

    def values(self, key):
        """What each column shows for a row, as text - what the searches
        match against."""
        entry = self.entries[key]
        staged = self.staged_sequence(key)
        values = dict(entry.fields)
        values['issued'] = u'Yes' if entry.fields.get('issued') else u'No'
        values['seq'] = u'{0}'.format(staged) if staged else u''
        values['used'] = u'{0}'.format(entry.used)
        values['series'] = u', '.join(entry.series)
        values['pending'] = self.pending(key)
        for column in self.columns:
            values[u'x_' + column.id] = ps_revdata.shown(
                column, self.custom_value(entry, column))
        return values

    def tokens(self, key, field, values=None):
        """A row's values in one column, as its filter list sees them:
        every series on its own for Sheet series, u'' for a blank cell."""
        if field == 'series':
            series = [u'{0}'.format(name).strip()
                      for name in self.entries[key].series]
            return [name for name in series if name] or [u'']
        if values is None:
            values = self.values(key)
        return [u'{0}'.format(values.get(field, u'') or u'').strip()]

    def visible(self, filters, picks=None, on_sheet=None):
        """The rows every search and every value filter lets through - and,
        given a sheet number, only the revisions on that sheet. A revision
        added here and not yet applied is on no sheet, but stays: hiding
        the row just made would read as losing it."""
        found = []
        for key in self.order:
            if on_sheet is not None:
                entry = self.entries[key]
                if not entry.is_new and on_sheet not in entry.sheets:
                    continue
            values = self.values(key)
            if not matches(values, filters):
                continue
            if picks and not passes_picks(
                    lambda field: self.tokens(key, field, values), picks):
                continue
            found.append(key)
        return found

    def choices(self, field, filters=None, picks=None):
        """What one column's filter list offers: every value in the rows
        the searches and the OTHER columns' filters leave, each once, in
        natural order, "(Blanks)" last. Its own filter is left out, or the
        values it hides would not be there to tick back on."""
        found = []
        for key in self.order:
            values = self.values(key)
            if not matches(values, filters):
                continue
            if not passes_picks(
                    lambda name: self.tokens(key, name, values), picks,
                    skip=field):
                continue
            found.extend(self.tokens(key, field, values))
        return ps_register.filter_choices(found)

    # -------------------------------------------------------------- staging
    def set_field(self, key, field, value):
        """(ok, message). Refused where Revit would refuse it."""
        entry = self.entries.get(key)
        if entry is None or field not in FIELDS:
            return False, u'No such field.'
        if not entry.live:
            return False, u'That revision is staged to go - restore it to ' \
                u'edit it.'
        if field != 'issued' and self.locked(key):
            return False, (u'Revision {0} is issued, so Revit keeps it as it '
                           u'is. Untick Issued to edit it.'.format(
                               self.staged_sequence(key)))
        if field == 'issued':
            value = bool(value)
        elif field == 'show':
            value = show_label(value)
        else:
            value = u'{0}'.format(value if value is not None else u'')
        entry.fields[field] = value
        return True, u''

    def set_setting(self, name, value):
        if name == 'arc_mm':
            try:
                value = float(value)
            except Exception:
                return False
            if value <= 0:
                return False
        elif name == 'numbering':
            value = PER_SHEET if value == PER_SHEET else PER_PROJECT
        else:
            return False
        self.settings[name] = value
        return True

    def add(self, position=None, fields=None, custom=None):
        """A new revision; returns its key.

        ``position`` is the sequence it is to have, 1 being the top: it goes
        in there and the revision that had that sequence, and every one
        after it, moves down a slot. None, or past the end, puts it last.
        ``fields`` and ``custom`` fill it in; anything not given is as Revit
        would start it - numbered like the last revision, shown with clouds
        and tags, not issued.
        """
        self._new += 1
        key = u'new{0}'.format(self._new)
        live = self.live_order()
        numbering = self.entries[live[-1]].fields.get('numbering') \
            if live else (self.sequences[0] if self.sequences else u'')
        start = {'numbering': numbering or u'', 'show': DEFAULT_SHOW,
                 'issued': False}
        for field, value in (fields or {}).items():
            if field == 'issued':
                start[field] = bool(value)
            elif field == 'show':
                start[field] = show_label(value)
            elif field in FIELDS:
                start[field] = u'{0}'.format(value if value is not None
                                             else u'')
        entry = Entry(key, None, 0, start, custom=dict(custom or {}))
        self.entries[key] = entry
        self.order = insert_at(self.order, live, key, position)
        return key

    def in_use(self, keys):
        """[(sequence, description, sheets, clouds)] for the used ones."""
        found = []
        for key in keys:
            entry = self.entries.get(key)
            if entry is None or entry.is_new or not entry.live:
                continue
            if entry.used or entry.clouds:
                found.append((self.staged_sequence(key),
                              entry.fields.get('desc') or u'',
                              entry.used, entry.clouds, entry.unplaced))
        return found

    def delete(self, keys):
        """Stage deletes, or restore rows already staged. (ok, message).

        Every selected row already staged is restored; otherwise they are
        all staged to go. A new row is simply dropped. Revit needs at
        least one revision in a project, so the last live one is refused.
        """
        keys = [key for key in keys if key in self.entries]
        if not keys:
            return False, u'Select a revision first.'
        if all([not self.entries[key].live for key in keys]):
            for key in keys:
                self.entries[key].deleted = False
                self.entries[key].merged_into = None
            return True, u'{0} revision{1} restored.'.format(
                len(keys), u'' if len(keys) == 1 else u's')
        going = [key for key in keys if self.entries[key].live]
        if len([key for key in self.live_order() if key not in going]) < 1:
            return False, (u'A project has to keep at least one revision, '
                           u'so the last one cannot go.')
        for key in going:
            if self.entries[key].is_new:
                self.order.remove(key)
                del self.entries[key]
            else:
                self.entries[key].deleted = True
        return True, u'{0} revision{1} staged to delete.'.format(
            len(going), u'' if len(going) == 1 else u's')

    def move(self, keys, step):
        movable = self.live_order()
        selected = [key for key in keys if key in movable]
        if not selected:
            return False
        before = list(self.order)
        self.order = move_keeping(self.order, movable, selected, step)
        return self.order != before

    def merge(self, key, step):
        """Stage merging one revision into its neighbour. (ok, message).

        As in Revit: only two revisions that are both unissued, and here
        only ones already in the model - a new one has nothing to merge
        yet. The merged one goes; its clouds move to the other.
        """
        entry = self.entries.get(key)
        if entry is None or not entry.live:
            return False, u'Select one revision that is not already going.'
        live = self.live_order()
        index = live.index(key) + step
        if index < 0 or index >= len(live):
            return False, u'There is no revision {0} it to merge into.' \
                .format(u'above' if step < 0 else u'below')
        target = self.entries[live[index]]
        if entry.is_new or target.is_new:
            return False, u'A new revision has to be applied before it can ' \
                u'be merged.'
        for one in (entry, target):
            if one.fields.get('issued') or one.originally_issued():
                return False, (u'Revision {0} is issued, and Revit only '
                               u'merges unissued revisions.'.format(
                                   self.staged_sequence(one.key)))
        entry.merged_into = target.key
        return True, u'Revision {0} staged to merge into {1}.'.format(
            self.staged_sequence(key) or live.index(key) + 1, index + 1)

    # ----------------------------------------------------------------- plan
    def plan(self):
        """Everything Apply has to do, in the order it has to be done."""
        plan = {'settings': {}, 'unissue': [], 'creates': [], 'edits': [],
                'merges': [], 'deletes': [], 'order': None, 'issue': [],
                'custom': None, 'push': False}
        for name in self.settings_changed():
            plan['settings'][name] = self.settings[name]

        for key in self.order:
            entry = self.entries[key]
            if entry.is_new:
                if not entry.live:
                    continue
                fields = dict([(field, entry.fields[field]) for field in FIELDS
                               if field != 'issued'])
                plan['creates'].append((key, fields))
                if entry.fields.get('issued'):
                    plan['issue'].append(key)
                continue
            if entry.merged_into is not None:
                plan['merges'].append((entry.element_key,
                                       self.entries[entry.merged_into]
                                       .element_key))
                continue
            if entry.deleted:
                plan['deletes'].append(entry.element_key)
                continue
            was = entry.originally_issued()
            now = bool(entry.fields.get('issued'))
            if was and not now:
                plan['unissue'].append(entry.element_key)
            edits = dict([(field, entry.fields[field]) for field in FIELDS
                          if field != 'issued' and
                          entry.fields[field] != entry.original[field]])
            if edits:
                plan['edits'].append((entry.element_key, edits))
            if now and not was:
                plan['issue'].append(entry.element_key)

        # The order Revit would end up in with no reorder: the survivors in
        # their old order, then the new ones as they were created.
        live = self.live_order()
        natural = [key for key in self.original_order if key in live] + \
            [key for key in live if self.entries[key].is_new]
        if live != natural:
            plan['order'] = [self.entries[key].element_key
                             if not self.entries[key].is_new else key
                             for key in live]

        # The extra columns: stored whenever they changed, and pushed into
        # their parameters on every Apply while any column is mapped - a
        # sheet whose current revision moved on takes the new value even
        # when no note was touched.
        pushed = [column for column in self.columns if column.pushed]
        others = not plan_is_empty(plan)
        plan['push'] = bool(pushed) and (self.push_requested or others or
                                         self.custom_changed())
        if self.custom_changed() or plan['push']:
            ids = set([column.id for column in self.columns])
            values = {}
            for key in live:
                entry = self.entries[key]
                values[key if entry.is_new else entry.element_key] = dict(
                    [(column_id, value) for column_id, value in
                     entry.custom.items() if column_id in ids])
            plan['custom'] = {'columns': [column.copy() for column in
                                          self.columns],
                              'values': values}
        return plan


def plan_is_empty(plan):
    return not (plan['settings'] or plan['unissue'] or plan['creates'] or
                plan['edits'] or plan['merges'] or plan['deletes'] or
                plan['order'] or plan['issue'] or plan.get('custom') or
                plan.get('push'))


def execute(api, plan):
    """Write a plan through ``api``. (done, errors).

    ``api`` is the RevitApi below in Revit and a recording fake on the
    bench - the order of the steps is the part worth testing, and it is
    the same object either way. ``done`` counts steps that went in.
    """
    done = 0
    errors = []

    def attempt(label, action, *args):
        try:
            action(*args)
            return True
        except Exception as err:
            errors.append(u'{0}: {1}'.format(label, err))
            return False

    for name, value in sorted(plan['settings'].items()):
        if attempt(u'Setting {0}'.format(name), api.set_setting, name, value):
            done += 1

    for element_key in plan['unissue']:
        if attempt(u'Un-issuing {0}'.format(api.label(element_key)),
                   api.set_field, element_key, 'issued', False):
            done += 1

    made = {}
    for key, fields in plan['creates']:
        try:
            made[key] = api.create()
        except Exception as err:
            errors.append(u'Adding a revision: {0}'.format(err))
            continue
        done += 1
        for field in FIELDS:
            if field in fields and fields[field] not in (u'', None):
                attempt(u'New revision {0}'.format(field), api.set_field,
                        made[key], field, fields[field])

    for element_key, edits in plan['edits']:
        ok = True
        for field in FIELDS:
            if field in edits:
                ok = attempt(u'Revision {0} {1}'.format(
                    api.label(element_key), field), api.set_field,
                    element_key, field, edits[field]) and ok
        if ok:
            done += 1

    for element_key, into in plan['merges']:
        # Revit merges a revision into its neighbour only, so it is moved
        # to sit straight after the one it merges into, then combined
        # with the one before it.
        def merge(element_key=element_key, into=into):
            order = [one for one in api.ids() if one != element_key]
            order.insert(order.index(into) + 1, element_key)
            api.reorder(order)
            api.combine_with_previous(element_key)
        if attempt(u'Merging revision {0}'.format(api.label(element_key)),
                   merge):
            done += 1

    for element_key in plan['deletes']:
        if attempt(u'Deleting revision {0}'.format(api.label(element_key)),
                   api.delete, element_key):
            done += 1

    if plan['order']:
        wanted = [made.get(one, one) for one in plan['order']]
        wanted = [one for one in wanted if not isinstance(one, type(u''))]
        present = api.ids()
        # Anything in the model the plan does not know about keeps its
        # place at the end rather than making Revit refuse the whole list.
        final = [one for one in wanted if one in present] + \
            [one for one in present if one not in wanted]
        if final != present and attempt(u'Reordering', api.reorder, final):
            done += 1

    for one in plan['issue']:
        element_key = made.get(one, one)
        if isinstance(element_key, type(u'')):
            continue
        if attempt(u'Issuing {0}'.format(api.label(element_key)),
                   api.set_field, element_key, 'issued', True):
            done += 1

    custom = plan.get('custom')
    if custom:
        values = {}
        for key, row in custom['values'].items():
            element_key = made.get(key, key)
            if not isinstance(element_key, type(u'')):
                values[element_key] = row
        if attempt(u'Storing the extra columns', api.write_custom,
                   custom['columns'], values):
            done += 1
        if plan.get('push'):
            try:
                pushed, problems = api.push(custom['columns'], values)
                if pushed:
                    done += 1
                errors.extend(problems)
            except Exception as err:
                errors.append(u'Pushing to parameters: {0}'.format(err))
    return done, errors


# ==========================================================================
# Revit
# ==========================================================================

def _id(value):
    # Through make_id, never ElementId(int(...)) - see ps_model.make_id.
    return ps_model.make_id(value)


def _id_list(keys):
    """A .NET List[ElementId], which is what SetAdditionalRevisionIds
    takes - a Python list is refused."""
    from System.Collections.Generic import List
    ids = List[ElementId]()
    for key in keys:
        ids.Add(_id(key))
    return ids


def _text(element, name):
    try:
        return ps_model.to_text(getattr(element, name, u'') or u'').strip()
    except Exception:
        return u''


def sequence_names(doc):
    """{element key: name} of the numbering sequences, and the names in
    Revit's order. Empty before Revit 2022, which had no sequences."""
    by_key = {}
    names = []
    if RevisionNumberingSequence is None:
        return by_key, names
    try:
        ids = list(RevisionNumberingSequence
                   .GetAllRevisionNumberingSequences(doc))
    except Exception:
        ids = []
    for sequence_id in ids:
        try:
            name = ps_model.to_text(doc.GetElement(sequence_id).Name)
        except Exception:
            continue
        by_key[ps_model.eid_value(sequence_id)] = name
        names.append(name)
    return by_key, names


def sheet_number_of(view):
    """The sheet number when ``view`` is a sheet, else None. Only a
    ViewSheet has a SheetNumber; every other view refuses the read."""
    if view is None:
        return None
    try:
        number = view.SheetNumber
    except Exception:
        return None
    text = ps_model.to_text(number)
    return text or None


def revision_keys_of(elements):
    """The revision key of every revision cloud among ``elements``, in the
    order given, each once. Anything without a RevisionId is skipped, so a
    selection of walls and one cloud answers with that cloud's revision.

    Pure: it reads nothing but the objects handed to it.
    """
    keys = []
    for element in elements or []:
        try:
            # Text, because that is what Entry.key is - an int key here
            # would match nothing in staging.order and the list would
            # simply never move.
            key = ps_model.to_text(ps_model.eid_value(element.RevisionId))
        except Exception:
            continue
        if not key or key in (u'0', u'-1') or key in keys:
            continue
        keys.append(key)
    return keys


def selection_token(uidoc, limit=200):
    """A cheap value that changes whenever the selection does.

    Polling Idling means this runs many times a second, so the ids alone
    are read first and the elements only when they have changed.
    """
    try:
        ids = list(uidoc.Selection.GetElementIds())[:limit]
        return tuple(sorted([ps_model.to_text(ps_model.eid_value(one))
                             for one in ids]))
    except Exception:
        return ()


def selected_revision_keys(uidoc, limit=50):
    """The revision keys of the revision clouds now selected in Revit.

    Reads the document, so it may only be called from inside a valid API
    context - Revit's Idling event or an external event. Never raises.
    """
    try:
        doc = uidoc.Document
        ids = list(uidoc.Selection.GetElementIds())[:limit]
    except Exception:
        return []
    elements = []
    for one in ids:
        try:
            elements.append(doc.GetElement(one))
        except Exception:
            continue
    return revision_keys_of(elements)


def series_of(pairs):
    """{revision key: [series]} from (revision key, series) pairs - each
    series once per revision, blanks left out, in natural order."""
    found = {}
    for key, series in pairs:
        series = u'{0}'.format(series or u'').strip()
        if not series:
            continue
        bucket = found.setdefault(key, [])
        if series not in bucket:
            bucket.append(series)
    for key in found:
        found[key].sort(key=ps_model.natural_key)
    return found


def clouds_by_view(drawn):
    """{revision key: {view key: [cloud keys]}} from (revision, cloud,
    view) triples - the view each cloud is drawn in. Pure."""
    found = {}
    for revision, cloud, view in drawn:
        found.setdefault(revision, {}).setdefault(view, []).append(cloud)
    return found


def views_to_open(entries):
    """{view key: [cloud keys]} across the revisions given - every view
    with one of their clouds in it, sheets included. Pure."""
    found = {}
    for entry in entries:
        for view, clouds in (entry.cloud_views or {}).items():
            have = found.setdefault(view, [])
            for cloud in clouds:
                if cloud not in have:
                    have.append(cloud)
    return found


def placed_views(doc):
    """The keys of every view a sheet shows: each sheet itself, every view
    placed on one, and the parent of any placed dependent view - a cloud
    drawn in the parent shows on the dependent's sheet."""
    found = set()
    try:
        for sheet in FilteredElementCollector(doc).OfClass(ViewSheet):
            found.add(u'{0}'.format(ps_model.eid_value(sheet.Id)))
    except Exception:
        pass
    try:
        for viewport in FilteredElementCollector(doc).OfClass(Viewport):
            view_key = ps_model.eid_value(viewport.ViewId)
            found.add(u'{0}'.format(view_key))
            try:
                view = doc.GetElement(viewport.ViewId)
                parent = ps_model.eid_value(view.GetPrimaryViewId())
                if parent and parent > 0:
                    found.add(u'{0}'.format(parent))
            except Exception:
                continue
    except Exception:
        pass
    return found


def view_name(doc, view_key):
    try:
        view = doc.GetElement(_id(view_key))
        return ps_model.to_text(view.Name)
    except Exception:
        return u'view {0}'.format(view_key)


def show_clouds(uidoc, by_view):
    """Open every view in ``by_view`` ({view key: [cloud keys]}) with its
    clouds temporarily isolated - Revit's own Temporary Hide/Isolate, so
    the view's sunglasses reset it. On Revit's thread. Returns (views
    opened, clouds isolated, errors)."""
    doc = uidoc.Document
    views, isolated, errors = [], 0, []
    for view_key in sorted(by_view):
        try:
            view = doc.GetElement(_id(view_key))
        except Exception:
            view = None
        if view is None:
            errors.append(u'View {0} is no longer in the model.'.format(
                view_key))
            continue
        views.append((view, by_view[view_key]))
    if not views:
        return 0, 0, errors
    transaction = Transaction(doc, u'RevoBIM - Isolate revision clouds')
    try:
        transaction.Start()
    except Exception as err:
        return 0, 0, [u'Revit would not start: {0}'.format(err)]
    for view, clouds in views:
        try:
            try:
                from Autodesk.Revit.DB import TemporaryViewMode
                if view.IsTemporaryHideIsolateActive():
                    view.DisableTemporaryViewMode(
                        TemporaryViewMode.TemporaryHideIsolate)
            except Exception:
                pass
            view.IsolateElementsTemporary(_id_list(clouds))
            isolated += len(clouds)
        except Exception as err:
            errors.append(u'{0}: the clouds could not be isolated: {1}'
                          .format(ps_model.to_text(view.Name), err))
    try:
        transaction.Commit()
    except Exception as err:
        try:
            transaction.RollBack()
        except Exception:
            pass
        errors.append(u'Revit would not keep the isolation: {0}'.format(err))
    opened = 0
    # Opened after the transaction: a view cannot be made active inside
    # one. The first view is opened last, so it is the one in front.
    for view, _clouds in reversed(views):
        try:
            uidoc.ActiveView = view
            opened += 1
        except Exception as err:
            errors.append(u'{0} would not open: {1}'.format(
                ps_model.to_text(view.Name), err))
    return opened, isolated, errors


def open_views(uidoc, views):
    """Open each sheet or view in Revit - Open sheets on the right-click.

    On Revit's thread, outside any transaction (a view cannot be made active
    inside one). The first is opened last, so the top of the highlight is
    the one in front. Returns (opened, errors).
    """
    opened = 0
    errors = []
    for view in reversed(list(views or [])):
        if view is None:
            continue
        try:
            uidoc.ActiveView = view
            opened += 1
        except Exception as err:
            try:
                name = ps_model.to_text(view.Name)
            except Exception:
                name = u'A view'
            errors.append(u'{0} would not open: {1}'.format(name, err))
    return opened, errors


def opened_report(opened, errors, word=u'sheet'):
    """One line on what Open sheets did."""
    text = u'{0} {1}{2} opened.'.format(opened, word,
                                        u'' if opened == 1 else u's')
    if errors:
        text += u' {0} could not be: {1}'.format(len(errors),
                                                u' '.join(errors[:3]))
    return text


def clouds_report(opened, isolated, errors):
    """One line on what Find clouds on views did."""
    text = u'{0} view{1} opened, {2} cloud{3} isolated in them - Revit\'s ' \
        u'Temporary Hide/Isolate, reset from the sunglasses.'.format(
            opened, u'' if opened == 1 else u's', isolated,
            u'' if isolated == 1 else u's')
    if errors:
        text += u' {0} could not be: {1}'.format(len(errors),
                                                u' '.join(errors[:3]))
    return text


def common_status(texts):
    """The status most of a revision's sheets carry; ties to the first
    seen. Blanks do not count."""
    counts, order = {}, []
    for text in texts:
        text = u'{0}'.format(text or u'').strip()
        if not text:
            continue
        if text not in counts:
            order.append(text)
        counts[text] = counts.get(text, 0) + 1
    if not order:
        return u''
    return sorted(order, key=lambda one: (-counts[one], order.index(one)))[0]


def read(doc, series_param=u'', status_param=u''):
    """A Staging of the project's revisions, with what uses each one.

    ``series_param`` is the sheet parameter Setup names as the series
    (BGL_Sheet Series on the house template); blank leaves the Sheet
    series column empty. ``status_param`` (BGL_Sheet Status) fills an
    empty Issue Status from the sheets carrying the revision - staged, so
    Apply keeps it with the revision.
    """
    by_sequence, names = sequence_names(doc)
    columns, stored = ps_revdata.read(doc)
    sheets = {}
    statuses = {}
    pairs = []
    try:
        for sheet in FilteredElementCollector(doc).OfClass(ViewSheet):
            try:
                carried = list(sheet.GetAllRevisionIds())
            except Exception:
                carried = []
            series = u''
            if series_param and carried:
                try:
                    series = ps_model.param_text(sheet, series_param)
                except Exception:
                    series = u''
            status = u''
            if status_param and carried:
                try:
                    status = ps_model.param_text(sheet, status_param)
                except Exception:
                    status = u''
            for revision_id in carried:
                key = ps_model.eid_value(revision_id)
                sheets.setdefault(key, []).append(
                    ps_model.to_text(sheet.SheetNumber))
                pairs.append((key, series))
                statuses.setdefault(u'{0}'.format(key), []).append(status)
    except Exception:
        pass
    series_by_key = series_of(pairs)
    clouds = {}
    drawn = []
    try:
        for cloud in FilteredElementCollector(doc).OfClass(RevisionCloud):
            key = ps_model.eid_value(cloud.RevisionId)
            clouds[key] = clouds.get(key, 0) + 1
            try:
                drawn.append((u'{0}'.format(key),
                              u'{0}'.format(ps_model.eid_value(cloud.Id)),
                              u'{0}'.format(ps_model.eid_value(
                                  cloud.OwnerViewId))))
            except Exception:
                continue
    except Exception:
        pass
    by_view = clouds_by_view(drawn)
    placed = placed_views(doc)

    entries = []
    try:
        ids = list(Revision.GetAllRevisionIds(doc))
    except Exception:
        ids = []
    for index, revision_id in enumerate(ids):
        revision = doc.GetElement(revision_id)
        if revision is None:
            continue
        key = ps_model.eid_value(revision_id)
        try:
            numbering = by_sequence.get(ps_model.eid_value(
                revision.RevisionNumberingSequenceId), u'')
        except Exception:
            numbering = u''
        try:
            issued = bool(revision.Issued)
        except Exception:
            issued = False
        try:
            visibility = u'{0}'.format(revision.Visibility)
        except Exception:
            visibility = u''
        try:
            sequence = int(revision.SequenceNumber)
        except Exception:
            sequence = index + 1
        try:
            uid = ps_model.to_text(revision.UniqueId)
        except Exception:
            uid = u''
        entries.append(Entry(
            key, key, sequence,
            {'numbering': numbering,
             'date': _text(revision, 'RevisionDate'),
             'desc': _text(revision, 'Description'),
             'issued': issued,
             'issued_to': _text(revision, 'IssuedTo'),
             'issued_by': _text(revision, 'IssuedBy'),
             'show': show_label(visibility)},
            sorted(sheets.get(key, []), key=ps_model.natural_key),
            clouds.get(key, 0), uid, stored.get(uid, {})))
        entries[-1].series = series_by_key.get(key, [])
        views = by_view.get(u'{0}'.format(key), {})
        entries[-1].cloud_views = views
        entries[-1].off_views = [
            (view, view_name(doc, view), len(found))
            for view, found in sorted(views.items())
            if view not in placed]

    numbering_mode, arc_mm = PER_PROJECT, 0.0
    try:
        settings = RevisionSettings.GetRevisionSettings(doc)
        numbering_mode = PER_SHEET if u'{0}'.format(
            settings.RevisionNumbering) == PER_SHEET else PER_PROJECT
        arc_mm = round(float(settings.RevisionCloudSpacing) * FEET_TO_MM, 3)
    except Exception:
        pass
    staging = Staging(entries, numbering_mode, arc_mm, names, columns)
    staging.fill_statuses(dict([(key, common_status(found))
                                for key, found in statuses.items()]))
    return staging


class RevitApi(object):
    """execute's view of a Revit document. Called inside a transaction."""

    def __init__(self, doc):
        self.doc = doc
        self.sequences = dict([(name, key) for key, name in
                               sequence_names(doc)[0].items()])

    def ids(self):
        return [ps_model.eid_value(one)
                for one in Revision.GetAllRevisionIds(self.doc)]

    def label(self, element_key):
        try:
            return u'{0}'.format(
                self.doc.GetElement(_id(element_key)).SequenceNumber)
        except Exception:
            return u'{0}'.format(element_key)

    def create(self):
        return ps_model.eid_value(Revision.Create(self.doc).Id)

    def set_field(self, element_key, field, value):
        if field == 'numbering' and RevisionNumberingSequence is None:
            raise ValueError(u'numbering sequences need Revit 2022 or later'
                             u' - this Revit has none')
        revision = self.doc.GetElement(_id(element_key))
        if field == 'issued':
            revision.Issued = bool(value)
        elif field == 'date':
            revision.RevisionDate = value
        elif field == 'desc':
            revision.Description = value
        elif field == 'issued_to':
            revision.IssuedTo = value
        elif field == 'issued_by':
            revision.IssuedBy = value
        elif field == 'show':
            revision.Visibility = getattr(RevisionVisibility, show_name(value))
        elif field == 'numbering':
            if value not in self.sequences:
                raise ValueError(u'no numbering sequence called "{0}"'
                                 .format(value))
            revision.RevisionNumberingSequenceId = _id(self.sequences[value])

    def combine_with_previous(self, element_key):
        Revision.CombineWithPrevious(self.doc, _id(element_key))

    def delete(self, element_key):
        self.doc.Delete(_id(element_key))

    def reorder(self, keys):
        from System.Collections.Generic import List
        ids = List[ElementId]()
        for key in keys:
            ids.Add(_id(key))
        Revision.ReorderRevisionSequence(self.doc, ids)

    def write_custom(self, columns, values_by_key):
        by_uid = {}
        for element_key, row in values_by_key.items():
            try:
                by_uid[ps_model.to_text(
                    self.doc.GetElement(_id(element_key)).UniqueId)] = row
            except Exception:
                continue
        ps_revdata.write(self.doc, columns, by_uid)

    def push(self, columns, values_by_key):
        return ps_revdata.push(self.doc, columns, values_by_key)

    def set_setting(self, name, value):
        settings = RevisionSettings.GetRevisionSettings(self.doc)
        if name == 'numbering':
            settings.RevisionNumbering = RevisionNumbering.PerSheet \
                if value == PER_SHEET else RevisionNumbering.PerProject
        elif name == 'arc_mm':
            settings.RevisionCloudSpacing = float(value) / FEET_TO_MM


def plan_assign(sheet_keys, revision, additional, carried, issued):
    """Put one revision on sheets, by hand - Revit's Revisions on Sheet. Pure.

    ``additional`` {sheet: the revisions put on it by hand}; ``carried``
    {sheet: every revision it shows, clouds included}. A sheet already
    carrying the revision is left - adding it again changes nothing - and
    an issued revision goes on no sheet: Revit locks it.

    Returns {'additional': {sheet: new set}, 'changed': [sheets],
             'skipped': [(sheet, why)]}.
    """
    revision = u'{0}'.format(revision)
    result = {'additional': {}, 'changed': [], 'skipped': []}
    issued = set([u'{0}'.format(one) for one in (issued or [])])
    for sheet in [u'{0}'.format(one) for one in sheet_keys]:
        if revision in issued:
            result['skipped'].append((sheet, SWAP_ISSUED))
            continue
        on = set([u'{0}'.format(one)
                  for one in (carried or {}).get(sheet, set())])
        if revision in on:
            result['skipped'].append((sheet, u'already carries it'))
            continue
        by_hand = set([u'{0}'.format(one)
                       for one in (additional or {}).get(sheet, set())])
        result['additional'][sheet] = by_hand | set([revision])
        result['changed'].append(sheet)
    return result


def assign_to_sheets(doc, sheet_keys, revision, sheets=None):
    """Put a revision on the sheets, in one transaction. On Revit's thread.
    Returns (assigned sheets, [(sheet, why)] skipped, errors)."""
    def key_of(element_id):
        return ps_model.to_text(ps_model.eid_value(element_id))

    sheets = dict(sheets or {})
    additional, carried = {}, {}
    for sheet_key in sheet_keys:
        sheet = sheets.get(sheet_key)
        if sheet is None:
            try:
                sheet = doc.GetElement(_id(sheet_key))
            except Exception:
                sheet = None
            sheets[sheet_key] = sheet
        try:
            additional[sheet_key] = set(
                [key_of(one) for one in sheet.GetAdditionalRevisionIds()])
        except Exception:
            additional[sheet_key] = set()
        try:
            carried[sheet_key] = set(
                [key_of(one) for one in sheet.GetAllRevisionIds()])
        except Exception:
            carried[sheet_key] = set(additional[sheet_key])
    issued = set()
    try:
        if doc.GetElement(_id(revision)).Issued:
            issued.add(u'{0}'.format(revision))
    except Exception:
        pass
    plan = plan_assign(sheet_keys, revision, additional, carried, issued)
    if not plan['additional']:
        return [], plan['skipped'], []
    errors = []
    transaction = Transaction(doc, u'RevoBIM - Assign revision to sheets')
    try:
        transaction.Start()
    except Exception as err:
        return [], plan['skipped'], [
            u'The transaction would not start: {0}'.format(err)]
    done = []
    for sheet_key, wanted in sorted(plan['additional'].items()):
        try:
            sheets[sheet_key].SetAdditionalRevisionIds(
                _id_list(sorted(wanted)))
            done.append(sheet_key)
        except Exception as err:
            errors.append(u'Sheet {0}: Revit would not add it: {1}'.format(
                _sheet_label(sheets.get(sheet_key), sheet_key), err))
    try:
        transaction.Commit()
    except Exception as err:
        try:
            transaction.RollBack()
        except Exception:
            pass
        return [], plan['skipped'], [
            u'Revit would not keep the changes: {0}'.format(err)]
    return done, plan['skipped'], errors


def revision_keys(doc):
    """Every revision in the project, as text keys."""
    try:
        return [ps_model.to_text(ps_model.eid_value(one))
                for one in Revision.GetAllRevisionIds(doc)]
    except Exception:
        return []


def create_and_swap(doc, plan, picks, sheets=None, include_shared=False,
                    report=None):
    """Create the revision the plan adds, then put it on the picked cells in
    place of what they carry. The Document Register's "Create new revision".

    On Revit's thread. Two transactions: the revision has to exist before a
    sheet or a cloud can point at it. Which revision is new is read from the
    model - before and after - rather than trusted from the plan.

    Returns (new key or u'', changed, skipped, errors).
    """
    before = set(revision_keys(doc))
    done, errors = write(doc, plan)
    errors = list(errors)
    new = [key for key in revision_keys(doc) if key not in before]
    if len(new) != 1:
        errors.append(u'The new revision could not be told apart from the '
                      u'others after it was made, so no sheet was changed '
                      u'onto it.' if new else
                      u'The new revision was not created, so no sheet was '
                      u'changed.')
        return u'', [], [], errors
    changed, skipped, more = swap_on_sheets(doc, picks, new[0], sheets,
                                            include_shared, report)
    return new[0], changed, skipped, errors + list(more)


def create_only(doc, plan):
    """Make the one revision a plan adds, and say which it is - read from
    the model before and after, not trusted from the plan. The register's
    Create new revision then stages the picked cells onto it; they wait
    for Apply revisions. On Revit's thread. Returns (new key or u'',
    errors)."""
    existing = set(revision_keys(doc))
    _done, problems = write(doc, plan)
    problems = list(problems)
    made = [key for key in revision_keys(doc) if key not in existing]
    if len(made) == 1:
        return made[0], problems
    if made:
        problems.append(u'More than one revision appeared, so the new one '
                        u'could not be told apart. No cell was staged onto '
                        u'it.')
    else:
        problems.append(u'The revision was not created.')
    return u'', problems


def write(doc, plan):
    """The plan, in one transaction. (done, errors)."""
    transaction = Transaction(doc, u'RevoBIM - Revision Manager')
    try:
        transaction.Start()
    except Exception as err:
        return 0, [u'The transaction would not start: {0}'.format(err)]
    try:
        done, errors = execute(RevitApi(doc), plan)
    except Exception as err:
        try:
            transaction.RollBack()
        except Exception:
            pass
        return 0, [u'Nothing was changed: {0}'.format(err)]
    try:
        transaction.Commit()
    except Exception as err:
        return 0, [u'Revit would not keep the changes: {0}'.format(err)]
    return done, errors


# ==========================================================================
# changing the revision a sheet carries - the Document Register's
# "Change revision on sheet"
#
# A revision is on a sheet in one of two ways, and both have to be followed
# or the swap only half happens:
#   - added by hand, in Revit's "Revisions on Sheet" - the sheet's
#     additional revisions;
#   - drawn: a revision cloud on the sheet itself, or in a view placed on
#     it. RevisionCloud.GetSheetIds says which sheets a cloud reaches.
# A cloud is only re-pointed when EVERY sheet it reaches is having that same
# revision changed. A cloud in a legend on twenty sheets, re-pointed for the
# two that were picked, would quietly change the other eighteen.
# ==========================================================================

SWAP_ISSUED = u'is issued - Revit keeps an issued revision where it is'


def plan_swap(picks, target, additional, clouds, issued,
              include_shared=False):
    """What "change these cells to that revision" will actually do. Pure.

    picks       {sheet key: set of revision keys} - the cells picked.
    target      the revision key they are to become, or None to take the
                revision off the sheets altogether (see plan_remove).
    additional  {sheet key: set of revision keys} - the revisions put on
                each picked sheet by hand, as Revit reports them.
    clouds      [(cloud key, revision key, set of sheet keys it reaches)]
    issued      the revision keys that are issued.

    include_shared  also take a cloud that shows on sheets NOT picked. A
                cloud is one element: changing it changes every sheet
                it shows on. Off, those clouds are left and reported;
                on - the user having been asked - they go too.

    All keys are text. Returns
        {'additional': {sheet key: the sheet's new set},
         'clouds': [cloud keys to re-point at target],
         'skipped': [(sheet key, revision key, why)],
         'changed': [(sheet key, revision key)],
         'shared': [(sheet key, revision key, cloud key, [other sheets])]}
    where 'changed' is every pick that will be fully moved, and 'shared' is
    every cloud that also shows on a sheet not picked - left or taken.
    """
    target = None if target is None else u'{0}'.format(target)
    result = {'additional': {}, 'clouds': [], 'skipped': [], 'changed': [],
              'shared': []}
    picks = dict([(u'{0}'.format(sheet), set([u'{0}'.format(one)
                                              for one in revisions]))
                  for sheet, revisions in (picks or {}).items()])
    issued = set([u'{0}'.format(one) for one in (issued or [])])

    if target in issued:
        for sheet in sorted(picks):
            for old in sorted(picks[sheet]):
                result['skipped'].append(
                    (sheet, old, u'the revision chosen ' + SWAP_ISSUED))
        return result

    # The sheets each old revision is being taken off.
    leaving = {}
    for sheet, olds in picks.items():
        for old in olds:
            leaving.setdefault(old, set()).add(sheet)

    chosen = set()
    for sheet in sorted(picks):
        for old in sorted(picks[sheet]):
            if old == target:
                result['skipped'].append(
                    (sheet, old, u'already that revision'))
                continue
            if old in issued:
                result['skipped'].append((sheet, old, SWAP_ISSUED))
                continue
            moved = False
            stuck = []
            by_hand = set([u'{0}'.format(one) for one in
                           (additional or {}).get(sheet, set())])
            if old in by_hand:
                now = result['additional'].get(sheet, set(by_hand))
                now.discard(old)
                if target is not None:
                    now.add(target)
                result['additional'][sheet] = now
                moved = True
            for cloud_key, cloud_rev, reaches in clouds or []:
                cloud_key = u'{0}'.format(cloud_key)
                reaches = set([u'{0}'.format(one) for one in reaches])
                if u'{0}'.format(cloud_rev) != old or sheet not in reaches:
                    continue
                if reaches <= leaving.get(old, set()):
                    if cloud_key not in chosen:
                        chosen.add(cloud_key)
                        result['clouds'].append(cloud_key)
                    moved = True
                    continue
                result['shared'].append(
                    (sheet, old, cloud_key,
                     sorted(reaches - leaving.get(old, set()))))
                if include_shared:
                    if cloud_key not in chosen:
                        chosen.add(cloud_key)
                        result['clouds'].append(cloud_key)
                    moved = True
                else:
                    stuck.append(cloud_key)
            if stuck:
                result['skipped'].append((sheet, old, (
                    u'{0} cloud{1} for it also show{2} on sheets not picked, so '
                    u'they were left and the sheet still carries it - pick '
                    u'those sheets too, or move the cloud{1}'.format(
                        len(stuck), u'' if len(stuck) == 1 else u's',
                        u's' if len(stuck) == 1 else u''))))
            elif moved:
                result['changed'].append((sheet, old))
            else:
                result['skipped'].append((sheet, old, (
                    u'nothing on the sheet carries it any more - press '
                    u'Refresh')))
    return result


def plan_remove(picks, additional, clouds, issued, include_shared=False):
    """What "remove these revisions from these sheets" will do. Pure.

    plan_swap with nowhere to go: a revision added by hand comes off the
    sheet, and its clouds reaching only picked sheets are to be DELETED -
    'clouds' in the result is the clouds to delete. A cloud that also shows
    on a sheet not picked is left and reported, exactly as for a change:
    deleting it would take the revision off that sheet too.
    """
    return plan_swap(picks, None, additional, clouds, issued,
                     include_shared)


def remove_on_sheets(doc, picks, sheets=None, include_shared=False,
                     report=None):
    """Take the picked revisions off their sheets, clouds and all. On
    Revit's API thread; one transaction. (removed, skipped, errors)."""
    return swap_on_sheets(doc, picks, None, sheets, include_shared, report)


def clouds_seen_on(doc, sheet, revisions):
    """The revision clouds of ``revisions`` a sheet actually shows.

    Looked for the way you would by hand: on the sheet itself, then inside
    every view placed on it, each with a view-scoped collector - which gives
    what that view shows. This is the fix for 1.40.0's "3 clouds also show
    on sheets not picked": RevisionCloud.GetSheetIds lists every sheet a
    cloud MAY appear on, so a cloud in a parent view was counted on the
    sheet of every dependent view, crop or no crop. Never raises.
    """
    def key_of(element_id):
        return ps_model.to_text(ps_model.eid_value(element_id))

    found = set()
    views = []
    try:
        views.append(sheet.Id)
    except Exception:
        return found
    try:
        views.extend(list(sheet.GetAllPlacedViews()))
    except Exception:
        pass
    for view_id in views:
        try:
            shown = FilteredElementCollector(doc, view_id).OfClass(
                RevisionCloud)
            for cloud in shown:
                if key_of(cloud.RevisionId) in revisions:
                    found.add(key_of(cloud.Id))
        except Exception:
            continue
    return found


def swap_on_sheets(doc, picks, target, sheets=None, include_shared=False,
                   report=None):
    """Change the picked cells to ``target``, in one transaction.

    On Revit's API thread. ``picks`` is {sheet key: set of revision keys};
    ``sheets`` maps a sheet key to its ViewSheet when the caller already
    holds them. Reads what plan_swap needs fresh, here, so the decision is
    made on the model as it is now rather than as the register last saw it.

    Returns (changed, skipped, errors): the picks moved, the picks left with
    why, and anything Revit refused. A ``report`` dict, if given, gets
    'shared': the clouds that also show on sheets not picked - for the
    caller to ask about - and 'include_shared' passes the answer back in.
    """
    def key_of(element_id):
        return ps_model.to_text(ps_model.eid_value(element_id))

    sheets = dict(sheets or {})
    additional = {}
    for sheet_key in picks:
        sheet = sheets.get(sheet_key)
        if sheet is None:
            try:
                sheet = doc.GetElement(_id(sheet_key))
            except Exception:
                sheet = None
            sheets[sheet_key] = sheet
        try:
            additional[sheet_key] = set(
                [key_of(one) for one in sheet.GetAdditionalRevisionIds()])
        except Exception:
            additional[sheet_key] = set()

    olds = set()
    for revisions in picks.values():
        olds |= set([u'{0}'.format(one) for one in revisions])
    # Every cloud of the old revisions, with the sheets Revit says it MAY
    # appear on. Only a shortlist: see clouds_seen_on.
    candidates = []
    try:
        for cloud in FilteredElementCollector(doc).OfClass(RevisionCloud):
            revision = key_of(cloud.RevisionId)
            if revision not in olds:
                continue
            try:
                may = set([key_of(one) for one in cloud.GetSheetIds()])
            except Exception:
                may = set()
            candidates.append((key_of(cloud.Id), revision, may))
    except Exception:
        pass

    # Then look inside each of those sheets for what it really shows.
    look = set(picks)
    for _cloud, _revision, may in candidates:
        look |= may
    seen = {}
    for sheet_key in sorted(look):
        sheet = sheets.get(sheet_key)
        if sheet is None:
            try:
                sheet = doc.GetElement(_id(sheet_key))
            except Exception:
                sheet = None
        if sheet is None:
            continue
        for cloud_key in clouds_seen_on(doc, sheet, olds):
            seen.setdefault(cloud_key, set()).add(sheet_key)
    clouds = []
    for cloud_key, revision, may in candidates:
        # Seen somewhere: those sheets are where it is. Seen nowhere - a
        # Revit whose view collector shows no annotation - trust GetSheetIds
        # rather than lose the cloud.
        clouds.append((cloud_key, revision, seen.get(cloud_key) or may))

    issued = set()
    wanted = set() if target is None else set([u'{0}'.format(target)])
    for key in olds | wanted:
        try:
            if doc.GetElement(_id(key)).Issued:
                issued.add(key)
        except Exception:
            continue

    plan = plan_swap(picks, target, additional, clouds, issued,
                     include_shared)
    if report is not None:
        report['shared'] = list(plan['shared'])
        report['include_shared'] = bool(include_shared)
    if not plan['additional'] and not plan['clouds']:
        return [], plan['skipped'], []

    errors = []
    transaction = Transaction(doc, u'RevoBIM - Remove revision from sheets'
                              if target is None else
                              u'RevoBIM - Change revision on sheets')
    try:
        transaction.Start()
    except Exception as err:
        return [], plan['skipped'], [
            u'The transaction would not start: {0}'.format(err)]
    failed = set()
    for sheet_key, wanted in sorted(plan['additional'].items()):
        try:
            sheets[sheet_key].SetAdditionalRevisionIds(
                _id_list(sorted(wanted)))
        except Exception as err:
            failed.add(sheet_key)
            errors.append(u'Sheet {0}: Revit would not change its revisions: '
                          u'{1}'.format(_sheet_label(sheets.get(sheet_key),
                                                     sheet_key), err))
    target_id = None if target is None else _id(target)
    for cloud_key in plan['clouds']:
        try:
            if target_id is None:
                doc.Delete(_id(cloud_key))
            else:
                doc.GetElement(_id(cloud_key)).RevisionId = target_id
        except Exception as err:
            errors.append(u'Revision cloud {0}: Revit would not {1} it: {2}'
                          .format(cloud_key, u'delete' if target_id is None
                                  else u'move', err))
    try:
        transaction.Commit()
    except Exception as err:
        try:
            transaction.RollBack()
        except Exception:
            pass
        return [], plan['skipped'], [
            u'Revit would not keep the changes: {0}'.format(err)]
    changed = [(sheet, old) for sheet, old in plan['changed']
               if sheet not in failed]
    return changed, plan['skipped'], errors


def _sheet_label(sheet, fallback):
    try:
        return ps_model.to_text(sheet.SheetNumber) or fallback
    except Exception:
        return u'{0}'.format(fallback)
