# -*- coding: utf-8 -*-
"""The Document Register: every sheet down the page, every revision across.

The read of the model and the decisions about it, with no WPF in here at
all. The tab that draws it is ``ps_regview``; this module hands it plain
Python objects, which is what lets the bench run the logic off Revit.

Lifted from the Drawing Register tool (Management panel), keeping the
decisions that tool paid for and correcting the one it left open:

**The cell is what the sheet prints.** ``GetRevisionNumberOnSheet`` is the
only call that agrees with the sheet's own revision schedule. Revit can number
revisions per sheet or per project, and ``Revision.RevisionNumber`` is the
project-wide one - deprecated since 2022 and gone in later releases. It is not
used here, even as a fallback; the sequence number is.

**Read in one pass.** Revisions are one call, scales are one collector keyed by
sheet. Nothing here runs a collector per sheet.

**Groups and tabs appear where their first drawing does.** Rows are in
natural drawing-number order, and a series or a discipline is placed where its
first member falls. Sorting the names alphabetically shuffles a register into
blocks that read wrong, which is the mistake the Drawing Register made first.

**The issue status letter is derived, never stored.** The alpha prefix of the
codes actually written in a column, majority winning. The Drawing Register
derived it per worksheet, so a discipline tab could read P over a column the
combined register called C. Here it is derived across every sheet in the
project: the letter describes the issue, not the tab you happen to be on.
"""

import ps_refs  # noqa: F401  - must be first

import re

from Autodesk.Revit.DB import (
    BuiltInCategory, FilteredElementCollector, Revision, Viewport, ViewType,
)

import ps_model


# What a blank discipline or series is called on screen. Blank values are
# real - a sheet nobody has filled in yet still has to be printable - so they
# get a tab and a heading of their own rather than vanishing.
NO_DISCIPLINE = u'(no discipline)'
NO_SERIES = u'(no series)'

# The first tab. Every drawing, grouped by discipline then series.
ALL_TAB = u'All'
# Kept among the unticked tabs to mean the opposite for All: ticked, so the
# Excel export gets an All worksheet. Off unless ticked - one name, not a
# discipline, so it can share the project's list of tab ticks.
ALL_INCLUDED = u'+All'


def all_ticked(skip):
    """Whether the All tab is ticked into the Excel export."""
    return ALL_INCLUDED in set(skip or ())


def tab_ticked(label, skip):
    """A tab's tick: a discipline is in unless unticked; All is out
    unless ticked."""
    if label == ALL_TAB:
        return all_ticked(skip)
    return label not in set(skip or ())


def tick_tab(label, wanted, skip):
    """The tab ticks after one is clicked: a new set."""
    skip = set(skip or ())
    if label == ALL_TAB:
        marked = wanted
        label = ALL_INCLUDED
    else:
        marked = not wanted
    if marked:
        skip.add(label)
    else:
        skip.discard(label)
    return skip

# How an empty cell is listed in a column's filter, as Excel lists it.
BLANKS = u'(Blanks)'

# A revision column's key in the table. A letter then the element id, so it
# can never collide with the fixed columns and is a legal DataTable name.
COLUMN_PREFIX = 'r'


# ==========================================================================
# the records
# ==========================================================================

class RevisionColumn(object):
    """One revision in the project, as a column across the register."""

    def __init__(self, element_key, sequence=0, date=u'', description=u'',
                 issued_by=u'', issued_to=u'', issued=False):
        self.element_key = element_key
        self.key = column_key(element_key)
        self.sequence = sequence
        self.date = date
        self.description = description
        self.issued_by = issued_by
        self.issued_to = issued_to
        self.issued = issued
        self.status_letter = u''
        # 1.44.0: Revit's UniqueId - what the Revision Manager keys its own
        # columns by - and the issue's status, as the Excel prints it.
        self.uid = u''
        self.status = u''

    def heading(self):
        """What goes up the rotated header: the date, as typed."""
        if self.date:
            return self.date
        return u'Seq {0}'.format(self.sequence)

    def describe(self):
        """The tooltip: everything Revit holds about this revision."""
        lines = [u'Sequence {0}'.format(self.sequence)]
        if self.date:
            lines.append(u'Date: {0}'.format(self.date))
        if self.description:
            lines.append(u'Description: {0}'.format(self.description))
        if self.issued_by:
            lines.append(u'Issued by: {0}'.format(self.issued_by))
        if self.issued_to:
            lines.append(u'Issued to: {0}'.format(self.issued_to))
        lines.append(u'Issued' if self.issued else u'Not yet issued')
        if self.status_letter:
            lines.append(u'Status: {0}'.format(self.status_letter))
        return u'\n'.join(lines)


class RegisterRow(object):
    """One sheet, as the register sees it."""

    def __init__(self, key, number=u'', name=u''):
        self.key = key
        self.number = number
        self.name = name
        self.size = u''
        self.scale = u''
        self.discipline = u''
        self.series = u''
        # {column key: the revision number this sheet prints for it}
        self.cells = {}
        self.current = u''
        self.current_key = u''
        self.current_date = u''
        # The current revision's sequence number in the project - what
        # Revit's Sheet Issues/Revisions dialog numbers it - as text.
        self.current_sequence = u''
        # The sheet's status parameter (BGL_Sheet Status), as it is now.
        self.status = u''


def register_file_name(project, today=None):
    """The register's file name, dated so each issue keeps its own:
    ``Wrexham AFC - Document Register - 2026-10-06.xlsx``."""
    import datetime
    import ps_config
    when = today or datetime.date.today()
    return u'{0} - Document Register - {1}.xlsx'.format(
        ps_config.safe_name(project or u'Project', u'Project'),
        when.strftime('%Y-%m-%d'))


def sequence_text(sequence):
    """A revision's sequence number as the register shows it: the whole
    number, or nothing where Revit has none."""
    try:
        number = int(sequence)
    except Exception:
        return u''
    return u'{0}'.format(number) if number > 0 else u''


def column_key(element_key):
    return u'{0}{1}'.format(COLUMN_PREFIX, element_key)


def is_column_key(text):
    text = u'{0}'.format(text or u'')
    return (len(text) > len(COLUMN_PREFIX)
            and text.startswith(COLUMN_PREFIX)
            and text[len(COLUMN_PREFIX):].lstrip('-').isdigit())


# ==========================================================================
# pure decisions - everything below this line up to the read is bench-tested
# ==========================================================================

_PREFIX = re.compile(r'^\s*([A-Za-z]+)')


def status_letter(codes):
    """The issue status letter for a column, from the codes written in it.

    P01, P02 and P03 make P; C01 makes C; AB makes AB. Where a column is
    mixed the majority wins, and a tie goes to the alphabetically first so
    the answer does not change from one read to the next. A column of plain
    numbers has no letter.
    """
    counts = {}
    for code in codes or ():
        match = _PREFIX.match(u'{0}'.format(code or u''))
        if not match:
            continue
        letter = match.group(1).upper()
        counts[letter] = counts.get(letter, 0) + 1
    if not counts:
        return u''
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[0][0]


def assign_status_letters(revisions, rows):
    """Write each revision's status letter, derived across every row."""
    for column in revisions:
        codes = [row.cells.get(column.key, u'') for row in rows]
        column.status_letter = status_letter(codes)


def first_appearance(rows, value_of, blank_label):
    """[(label, [rows])] in the order each value first appears.

    Every member of a value is gathered under it, even when the values
    interleave, so a sheet numbered out of step with its series still sits
    with its series. Blank values go last under ``blank_label``: an
    unfilled parameter is the exception, and leading with it buries the
    register under the sheets nobody has finished.
    """
    order = []
    members = {}
    blanks = []
    for row in rows:
        value = u'{0}'.format(value_of(row) or u'').strip()
        if not value:
            blanks.append(row)
            continue
        if value not in members:
            members[value] = []
            order.append(value)
        members[value].append(row)
    groups = [(value, members[value]) for value in order]
    if blanks:
        groups.append((blank_label, blanks))
    return groups


def discipline_tabs(rows):
    """The tabs along the bottom: All first, then one per discipline.

    Disciplines in the order their first drawing appears, blank last. When
    nobody has filled the discipline in on any sheet there is only the All
    tab - a second tab holding exactly the same drawings is noise.
    """
    tabs = [(ALL_TAB, list(rows))]
    groups = first_appearance(rows, lambda row: row.discipline, NO_DISCIPLINE)
    if len(groups) == 1 and groups[0][0] == NO_DISCIPLINE:
        return tabs
    tabs.extend(groups)
    return tabs


def has_values(rows, value_of):
    """Whether the parameter holds a value on at least one sheet."""
    for row in rows:
        if u'{0}'.format(value_of(row) or u'').strip():
            return True
    return False


def columns_used(revisions, rows):
    """The revisions at least one of these rows carries, in sequence order.

    Each tab only shows the columns its own drawings use, as the paper form
    does. A Mechanical tab with forty empty Electrical columns across it is
    a register you have to scroll to read.
    """
    used = set()
    for row in rows:
        for key, text in row.cells.items():
            if u'{0}'.format(text or u'').strip():
                used.add(key)
    ordered = sorted(revisions, key=lambda column: column.sequence)
    return [column for column in ordered if column.key in used]


def carrying(rows, column_key_text):
    """The rows that carry a given revision - what a header click ticks."""
    found = []
    for row in rows:
        if u'{0}'.format(row.cells.get(column_key_text, u'') or u'').strip():
            found.append(row)
    return found


def element_of(column_key_text):
    """The revision's element key behind a column key: "r1234" -> "1234"."""
    text = u'{0}'.format(column_key_text or u'')
    return text[len(COLUMN_PREFIX):] if is_column_key(text) else u''


def column_picks(picked, key, anchor, order, ctrl=False, shift=False):
    """The revision columns picked after a click on one's sequence number.

    Excel's rules, along one row of headings:
      - a plain click picks that column alone, and a second plain click on
        the only one picked lets it go;
      - Ctrl toggles one in or out and moves the anchor to it;
      - Shift picks the run from the anchor to it, Ctrl+Shift adds the run.
    ``order`` is the columns as shown. Returns (picked, anchor), picked in
    ``order``'s order.
    """
    picked = [one for one in (picked or []) if one in order]
    if key not in order:
        return picked, anchor
    if shift and anchor in order:
        start, end = sorted([order.index(anchor), order.index(key)])
        run = set(order[start:end + 1])
        wanted = (set(picked) | run) if ctrl else run
        return [one for one in order if one in wanted], anchor
    if ctrl:
        wanted = set(picked) ^ set([key])
        return [one for one in order if one in wanted], key
    if picked == [key]:
        return [], key
    return [key], key


def cell_picks(picked, cell, anchor, rows, columns, filled,
               ctrl=False, shift=False):
    """The revision cells picked after a click on one.

    ``cell`` and ``anchor`` are (sheet key, column key). ``rows`` and
    ``columns`` are the drawings and revision columns in the order shown;
    ``filled(sheet, column)`` says whether that sheet carries that revision -
    only those can be picked, since an empty cell has no revision to change.
    Same rules as column_picks, with Shift picking the rectangle.
    Returns (picked set, anchor).
    """
    picked = set(picked or [])
    sheet, column = cell
    if not filled(sheet, column):
        return picked, anchor
    if shift and anchor is not None and anchor[0] in rows and \
            anchor[1] in columns and sheet in rows and column in columns:
        top, bottom = sorted([rows.index(anchor[0]), rows.index(sheet)])
        left, right = sorted([columns.index(anchor[1]),
                              columns.index(column)])
        block = set()
        for one in rows[top:bottom + 1]:
            for other in columns[left:right + 1]:
                if filled(one, other):
                    block.add((one, other))
        return ((picked | block) if ctrl else block), anchor
    if ctrl:
        return picked ^ set([cell]), cell
    if picked == set([cell]):
        return set(), cell
    return set([cell]), cell


def isolated_rows(rows, column_keys):
    """The rows carrying ANY of these revisions - Isolate sheets with this
    revision. No revisions picked is no isolation: every row."""
    keys = [u'{0}'.format(one) for one in (column_keys or [])]
    if not keys:
        return list(rows)
    return [row for row in rows
            if [key for key in keys
                if u'{0}'.format(row.cells.get(key, u'') or u'').strip()]]


def passes(values, filters):
    """Whether a row survives every column filter, Excel fashion.

    ``values`` is {column: text}. ``filters`` is {column: set of allowed
    texts}, where u'' stands for a blank cell and None means the column is
    not filtered - everything ticked is no filter, which is not the same
    thing as a filter that happens to allow everything. Every filtered
    column has to allow the row, so filters narrow rather than widen. A
    filter on a column the row does not have is ignored rather than hiding
    everything: a revision column filtered on one discipline must not empty
    the next discipline's tab.
    """
    for column, allowed in (filters or {}).items():
        if allowed is None or column not in values:
            continue
        if u'{0}'.format(values.get(column) or u'').strip() not in allowed:
            return False
    return True


def filter_choices(texts):
    """The values a column's filter list offers, in order, blanks last.

    Natural order, so P-9 comes before P-10. Blank cells are one entry,
    "(Blanks)", at the end - where Excel puts it - and only if the column
    has any.
    """
    seen = set()
    values = []
    blank = False
    for text in texts:
        text = u'{0}'.format(text or u'').strip()
        if not text:
            blank = True
            continue
        if text not in seen:
            seen.add(text)
            values.append(text)
    values.sort(key=_natural)
    if blank:
        values.append(BLANKS)
    return values


def _natural(text):
    key = []
    for part in re.split(r'(\d+)', u'{0}'.format(text)):
        if part.isdigit():
            key.append((1, int(part), u''))
        else:
            key.append((0, 0, part.lower()))
    return key


def group_tree(rows, by_discipline, by_series):
    """[(label, rows, [(label, rows, [])])] - the headings on a tab.

    The All tab is grouped by discipline and then, inside each, by series;
    a discipline's own tab by series alone. Groups go where their first
    drawing is, blanks last. A parameter holding nothing anywhere gives no
    headings at all, rather than one heading saying "(no series)" over
    everything.
    """
    def series_of(members):
        if not by_series or not has_values(members, lambda row: row.series):
            return []
        return [(label, inner, []) for label, inner in first_appearance(
            members, lambda row: row.series, NO_SERIES)]

    if by_discipline:
        return [(label, members, series_of(members))
                for label, members in first_appearance(
                    rows, lambda row: row.discipline, NO_DISCIPLINE)]
    series = series_of(rows)
    if series:
        return series
    return [(None, list(rows), [])]


def revisions_for(revisions, rows, hide_unused):
    """The revision columns to show: only those used, or every one."""
    if hide_unused:
        return columns_used(revisions, rows)
    return sorted(revisions, key=lambda column: column.sequence)


def column_width(widths, header, floor, ceiling, padding=18):
    """Pixels for a column: its widest text plus padding, within limits.

    Measured once per tab and frozen, never left on Auto: Auto re-measures
    as rows are realised, so columns shift under the reader halfway down a
    long list, and it has no ceiling.
    """
    widest = max(list(widths or []) + [header or 0])
    return int(max(floor, min(ceiling, widest + padding)))


def common_folder(paths):
    """The deepest folder every path sits in, or u'' where there is none.

    Split on both separators by hand rather than through os.path, which
    answers for the platform the bench runs on rather than Windows.
    """
    split = []
    for path in paths or ():
        text = u'{0}'.format(path or u'').replace(u'/', u'\\').rstrip(u'\\')
        if text:
            split.append([part for part in text.split(u'\\')])
    if not split:
        return u''
    shared = []
    for parts in zip(*split):
        if all([part.lower() == parts[0].lower() for part in parts]):
            shared.append(parts[0])
        else:
            break
    if not shared or shared == [u'']:
        return u''
    folder = u'\\'.join(shared)
    if folder.endswith(u':'):
        folder += u'\\'
    return folder


def register_folder(job_folders, per_format):
    """Where the register goes alongside an export run.

    The folder *above* the PDF and DWG folders, not the deepest folder the
    run's files share. 1.21.0 used the shared folder, so a run of one
    series in one format put the register inside the PDF folder, among the
    drawings, where nobody looks for it. With a folder per format the
    format is the last part of every path, so it is taken off before the
    paths are compared.
    """
    bases = []
    for folder in job_folders or ():
        text = u'{0}'.format(folder or u'').replace(u'/', u'\\').rstrip(u'\\')
        if not text:
            continue
        if per_format and u'\\' in text:
            text = text.rsplit(u'\\', 1)[0]
        bases.append(text)
    return common_folder(bases)


# The icon on a discipline tab, in a 16 x 16 box: path data for WPF.
TAB_ICONS = {
    # All: every sheet - a grid of four.
    'all': (u'M 0,0 H 7 V 7 H 0 Z M 9,0 H 16 V 7 H 9 Z '
            u'M 0,9 H 7 V 16 H 0 Z M 9,9 H 16 V 16 H 9 Z'),
    # Electrical: a lightning bolt.
    'electrical': u'M 9.5,0 L 2,9.2 H 7 L 5.2,16 L 14,6.2 H 9 L 11,0 Z',
    # Mechanical: a four-bladed fan round its hub.
    'mechanical': (u'M 8.0,6.2 C 7.2,2.0 9.6,0.3 12.6,1.6 C 13.4,4.0 '
                   u'9.6,6.8 8.0,6.2 Z M 9.8,8.0 C 14.0,7.2 15.7,9.6 '
                   u'14.4,12.6 C 12.0,13.4 9.2,9.6 9.8,8.0 Z M 8.0,9.8 '
                   u'C 8.8,14.0 6.4,15.7 3.4,14.4 C 2.6,12.0 6.4,9.2 '
                   u'8.0,9.8 Z M 6.2,8.0 C 2.0,8.8 0.3,6.4 1.6,3.4 '
                   u'C 4.0,2.6 6.8,6.4 6.2,8.0 Z '
                   u'M 6.6,8 A 1.4,1.4 0 1 1 9.4,8 A 1.4,1.4 0 1 1 6.6,8 Z'),
    # Coordination: two rings linked - the trades brought together.
    'coordination': (u'M 0.5,8 A 5,5 0 1 1 10.5,8 A 5,5 0 1 1 0.5,8 Z '
                     u'M 2.1,8 A 3.4,3.4 0 1 0 8.9,8 '
                     u'A 3.4,3.4 0 1 0 2.1,8 Z '
                     u'M 5.5,8 A 5,5 0 1 1 15.5,8 A 5,5 0 1 1 5.5,8 Z '
                     u'M 7.1,8 A 3.4,3.4 0 1 0 13.9,8 '
                     u'A 3.4,3.4 0 1 0 7.1,8 Z'),
    # Builderswork: a brick wall, courses staggered.
    'builderswork': (u'M 0,0 H 7.4 V 4.4 H 0 Z M 8.6,0 H 16 V 4.4 H 8.6 Z '
                     u'M 0,5.8 H 3.4 V 10.2 H 0 Z '
                     u'M 4.6,5.8 H 11.4 V 10.2 H 4.6 Z '
                     u'M 12.6,5.8 H 16 V 10.2 H 12.6 Z '
                     u'M 0,11.6 H 7.4 V 16 H 0 Z '
                     u'M 8.6,11.6 H 16 V 16 H 8.6 Z'),
}

# What in a tab's name says which icon it wears - any case, anywhere in
# it, so "E - Electrical", "MECHANICAL SERVICES" and "BWIC" all match.
TAB_ICON_WORDS = (
    ('builderswork', (u'BUILDERSWORK', u'BUILDERS WORK', u'BUILDERS',
                      u'BWIC')),
    ('coordination', (u'COORDINAT', u'CO-ORDINAT', u'COORD')),
    ('electrical', (u'ELECTRIC',)),
    ('mechanical', (u'MECHANIC',)),
)


def tab_icon(label):
    """The path data for a tab's icon, or None when its name says nothing
    known. The All tab is matched by name, whatever case."""
    text = u'{0}'.format(label or u'').strip().upper().replace(u"'", u'')
    if not text:
        return None
    if text == ALL_TAB.upper():
        return TAB_ICONS['all']
    for name, words in TAB_ICON_WORDS:
        for word in words:
            if word in text:
                return TAB_ICONS[name]
    return None


# ----------------------------------------------------------------------
# Revision changes waiting for Apply revisions
# ----------------------------------------------------------------------
# An edit is a dict, in column keys ("r501"), never element ids:
#   {'kind': 'assign', 'target': col, 'sheets': [sheet, ...]}
#   {'kind': 'change', 'target': col, 'picks': {sheet: [col, ...]}}
#   {'kind': 'remove', 'picks': {sheet: [col, ...]}}
# They are kept in order and written in order, so a later one can act on a
# cell an earlier one put there.

PENDING_ADD = 'add'
PENDING_DEL = 'del'

# A staged change to a revision's issue data - its Issue Status, or a tick
# under Issued To / Issued Method (1.51.0):
#   {'kind': 'meta', 'target': column key, 'field': column id,
#    'value': the new value}
# Shares the undo stack and Apply with the sheet revision edits.
META = 'meta'


def meta_values(stored, edits):
    """{(column key, field id): value}: what is stored, with the staged
    issue data edits played over it in order."""
    now = dict(stored or {})
    for edit in edits or []:
        if edit.get('kind') == META:
            now[(edit.get('target'), edit.get('field'))] = \
                u'{0}'.format(edit.get('value', u''))
    return now


def meta_changed(stored, edits):
    """The issue data cells the staged edits leave different from what
    is stored. A cell edited and edited back is not changed."""
    stored = stored or {}
    now = meta_values(stored, edits)
    return set([cell for cell, value in now.items()
                if value != u'{0}'.format(stored.get(cell, u''))])



def pending_flags(present, edits):
    """What the edits do to the grid: {(sheet, column): 'add' | 'del'}.

    ``present`` is {sheet: set of columns carrying something} as read from
    the model. The edits are played over it in order; a cell that ends up
    as it started is not flagged at all - assign, then remove, is no
    change."""
    now = dict([(sheet, set(columns)) for sheet, columns in
                (present or {}).items()])
    for edit in edits or []:
        kind = edit.get('kind')
        if kind == 'assign':
            for sheet in edit.get('sheets') or []:
                now.setdefault(sheet, set()).add(edit['target'])
        elif kind in ('change', 'remove'):
            for sheet, columns in (edit.get('picks') or {}).items():
                held = now.setdefault(sheet, set())
                for column in columns:
                    held.discard(column)
                if kind == 'change':
                    held.add(edit['target'])
    flags = {}
    for sheet in set(now) | set(present or {}):
        after = now.get(sheet, set())
        before = set((present or {}).get(sheet, set()))
        for column in after - before:
            flags[(sheet, column)] = PENDING_ADD
        for column in before - after:
            flags[(sheet, column)] = PENDING_DEL
    return flags


def pending_cells(edit):
    """How many sheet cells one edit touches."""
    if edit.get('kind') == 'assign':
        return len(edit.get('sheets') or [])
    if edit.get('kind') == META:
        return 1
    return sum([len(columns) for columns in
                (edit.get('picks') or {}).values()])


def outside_set(sheets, columns, included, filled):
    """The sheets carrying any of the columns that are not in the set -
    the ones Included only would hide from an isolated revision."""
    included = set(included or [])
    return [sheet for sheet in sheets
            if sheet not in included and
            [column for column in columns if filled(sheet, column)]]


class PendingEdits(object):
    """The edits made and not yet written, with Undo and Redo."""

    def __init__(self):
        self.edits = []
        self.undone = []

    def __len__(self):
        return len(self.edits)

    def push(self, edit):
        """A new edit. Whatever was undone cannot be redone after it."""
        self.edits.append(edit)
        self.undone = []

    def undo(self):
        if not self.edits:
            return None
        edit = self.edits.pop()
        self.undone.append(edit)
        return edit

    def redo(self):
        if not self.undone:
            return None
        edit = self.undone.pop()
        self.edits.append(edit)
        return edit

    def clear(self):
        self.edits = []
        self.undone = []

    def flags(self, present):
        return pending_flags(present, self.edits)

    def prune(self, columns, sheets, fields=None):
        """After a read: keep only what still names revisions and sheets in
        the model - and, for issue data, a column the model still has
        (``fields``). Returns how many edits went."""
        columns, sheets = set(columns), set(sheets)

        def kept(edit):
            if edit.get('kind') == META:
                if edit.get('target') not in columns:
                    return None
                if fields is not None and edit.get('field') not in fields:
                    return None
                return edit
            if edit.get('kind') != 'remove' and \
                    edit.get('target') not in columns:
                return None
            if edit.get('kind') == 'assign':
                left = [sheet for sheet in edit.get('sheets') or []
                        if sheet in sheets]
                if not left:
                    return None
                return dict(edit, sheets=left)
            picks = {}
            for sheet, chosen in (edit.get('picks') or {}).items():
                left = [column for column in chosen if column in columns]
                if sheet in sheets and left:
                    picks[sheet] = left
            if not picks:
                return None
            return dict(edit, picks=picks)

        before = len(self.edits)
        self.edits = [one for one in [kept(edit) for edit in self.edits]
                      if one is not None]
        self.undone = [one for one in [kept(edit) for edit in self.undone]
                       if one is not None]
        return before - len(self.edits)


def tab_shows(label, members, included, included_only, current):

    """Whether a discipline's tab is on the strip.

    Every tab while everything is showing. Under "Included only" a
    discipline with nothing in the register has nothing to show, so its
    tab goes - except All, which is always there, and the tab already on
    screen, which stays until you leave it rather than vanishing under the
    cursor the moment its last drawing is unticked.
    """
    if not included_only or label == ALL_TAB or current:
        return True
    for row in members:
        if u'{0}'.format(row.key) in included:
            return True
    return False


def heading_ticks_shown(included_only, drawings_showing):
    """Whether the series and discipline headings carry a tick box.

    Only under All sheets: under "Included only" every drawing on screen is
    already in, and a heading tick there could only take a whole series
    out at a stroke. And not with everything collapsed - a column of
    heading ticks with no drawing under any of them reads as a list of
    things to tick, when the drawings themselves are folded away.
    """
    return (not included_only) and bool(drawings_showing)


def scale_label(scales):
    """One distinct scale gives 1:100, several give As Shown, none NTS."""
    distinct = set()
    for value in scales or ():
        try:
            number = int(value)
        except Exception:
            continue
        if number > 0:
            distinct.add(number)
    if not distinct:
        return u'NTS'
    if len(distinct) > 1:
        return u'As Shown'
    return u'1:{0}'.format(list(distinct)[0])


# ==========================================================================
# reading the model
# ==========================================================================

def read_revisions(doc):
    """Every revision in the project, in sequence order."""
    ids = []
    try:
        ids = list(Revision.GetAllRevisionIds(doc))
    except Exception:
        try:
            ids = [element.Id for element in
                   FilteredElementCollector(doc)
                   .OfCategory(BuiltInCategory.OST_Revisions)
                   .WhereElementIsNotElementType()]
        except Exception:
            ids = []

    columns = []
    for index, revision_id in enumerate(ids):
        try:
            revision = doc.GetElement(revision_id)
        except Exception:
            revision = None
        if revision is None:
            continue
        try:
            sequence = int(getattr(revision, 'SequenceNumber', index + 1))
        except Exception:
            sequence = index + 1
        columns.append(RevisionColumn(
            ps_model.eid_value(revision_id),
            sequence=sequence,
            date=_text(revision, 'RevisionDate'),
            description=_text(revision, 'Description'),
            issued_by=_text(revision, 'IssuedBy'),
            issued_to=_text(revision, 'IssuedTo'),
            issued=_flag(revision, 'Issued')))
        columns[-1].uid = _text(revision, 'UniqueId')
    columns.sort(key=lambda column: column.sequence)
    return columns


def _text(element, name):
    try:
        return ps_model.to_text(getattr(element, name, u'') or u'').strip()
    except Exception:
        return u''


def _flag(element, name):
    try:
        return bool(getattr(element, name, False))
    except Exception:
        return False


# Views that carry no meaningful scale on a drawing register: a legend is
# drawn at whatever scale fits the key, a drafting view's scale is a text
# size. Schedules are not viewports at all, so they never get here.
_NO_SCALE_TYPES = set()
for _name in ('Legend', 'DraftingView', 'Schedule', 'Report'):
    try:
        _NO_SCALE_TYPES.add(getattr(ViewType, _name))
    except Exception:
        continue


def read_scales(doc):
    """{sheet key: scale label} from one collector over every viewport."""
    found = {}
    try:
        viewports = list(FilteredElementCollector(doc).OfClass(Viewport))
    except Exception:
        viewports = []
    for viewport in viewports:
        try:
            sheet_key = ps_model.eid_value(viewport.SheetId)
            view = doc.GetElement(viewport.ViewId)
        except Exception:
            continue
        if view is None:
            continue
        try:
            if view.ViewType in _NO_SCALE_TYPES:
                continue
        except Exception:
            pass
        try:
            found.setdefault(sheet_key, []).append(int(view.Scale))
        except Exception:
            continue
    return dict([(key, scale_label(values)) for key, values in found.items()])


def scale_text(sheet, block, parameter, native):
    """The Scale column for one sheet: the parameter's text, read from the
    sheet and then from its title block, or Revit's own scale where the
    parameter is not named or holds nothing."""
    if parameter:
        for element in (sheet, block):
            if element is None:
                continue
            try:
                text = ps_model.param_text(element, parameter).strip()
            except Exception:
                text = u''
            if text:
                return text
    return native


def read_register(doc, sheet_rows, discipline_param, series_param,
                  status_param=u'', scale_param=u''):
    """(revisions, rows) for the register, from the Selection tab's sheets.

    ``sheet_rows`` are ``ps_model.Row`` objects already in natural number
    order, with their paper sizes read - the register reuses them rather
    than reading the title blocks a second time. ``scale_param`` names the
    text parameter the Scale column comes from; blank is Revit's own.
    """
    revisions = read_revisions(doc)
    by_element = dict([(column.element_key, column) for column in revisions])
    scales = read_scales(doc)
    blocks = ps_model.read_title_blocks(doc) if scale_param else {}

    rows = []
    for sheet_row in sheet_rows:
        if not getattr(sheet_row, 'is_sheet', False):
            continue
        sheet = sheet_row.element
        row = RegisterRow(sheet_row.key, sheet_row.number, sheet_row.name)
        row.size = getattr(sheet_row, 'size', u'') or u''
        row.scale = scale_text(sheet, blocks.get(sheet_row.key), scale_param,
                               scales.get(sheet_row.key, u'NTS'))
        if status_param:
            row.status = ps_model.param_text(sheet, status_param).strip()
        if discipline_param:
            row.discipline = ps_model.param_text(sheet, discipline_param).strip()
        if series_param:
            row.series = ps_model.param_text(sheet, series_param).strip()

        try:
            carried = list(sheet.GetAllRevisionIds())
        except Exception:
            carried = []
        for revision_id in carried:
            column = by_element.get(ps_model.eid_value(revision_id))
            if column is None:
                continue
            row.cells[column.key] = _number_on_sheet(sheet, revision_id, column)

        try:
            current = sheet.GetCurrentRevision()
            current_key = ps_model.eid_value(current)
        except Exception:
            current_key = 0
        column = by_element.get(current_key)
        if column is not None:
            row.current_key = column.key
            row.current = row.cells.get(column.key, u'')
            row.current_date = column.date
            row.current_sequence = sequence_text(column.sequence)
        rows.append(row)

    assign_status_letters(revisions, rows)
    return revisions, rows


def _number_on_sheet(sheet, revision_id, column):
    """What this sheet prints for this revision, per sheet numbering."""
    try:
        shown = sheet.GetRevisionNumberOnSheet(revision_id)
        if shown:
            return ps_model.to_text(shown)
    except Exception:
        pass
    # Never Revision.RevisionNumber: it is project-wide, deprecated since
    # 2022, and gone in later releases. The sequence number is at least a
    # number Revit still has.
    return u'{0}'.format(column.sequence)
