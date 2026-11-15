# -*- coding: utf-8 -*-
"""The Document Register as an Excel workbook, laid out as the BGL RD9 sheet.

Cell for cell the office's own RD9 - Document Register & Issue Sheet form
(BGL_Family_Container - Document Register.xlsx; 1.44.0 brought the layout,
1.45.0 the RD9 title back):

| Rows | Content |
| --- | --- |
| 1-2 | the title band: the title, then the company logo and the client logo |
| 3-5 | Project No: / Project Title: with Day / Month / Year beside them, and
        each issue's date up its column |
| 6-7 | Issue Status: and each issue's status (S3, S4...), the legend under |
| 8.. | Issued to: - a row per Issued To column of the Revision Manager,
        then one per Method column, x where the revision is ticked; a
        column nothing on the worksheet is ticked in is left off |
| then | Document No / Document Title / Sheet Size / Scale / Current Rev /
         Document Issued |
| below | the discipline, then the drawings, a blank row between series |
| last | the footer line, boxed |

Current Rev - every drawing's current revision - is the orange column
before the issues (it was Asite Snapshot, at the far right, before
1.44.0). The form keeps at least ``MIN_ISSUE_COLUMNS`` issue columns, blank
ones included, so it has room for the next issues and the same shape from
one issue to the next.

One worksheet per discipline, each carrying only the revision columns its own
drawings use. Rows 1 to the column headings repeat on every printed page; the
print area is the form and nothing else; A4 portrait, fitted to the width.

**Start from the paper form, not from the grid.** A register that looks like
the one the office already sends is adopted; a neat table that does not is
re-typed into the old one by hand.

Nothing here reads Revit. The register tab hands over what it has already
read, which keeps the export testable and lets it run from a plain button
press as well as from inside an export run.
"""

import ps_refs  # noqa: F401  - must be first

import re
import time

import ps_register
import ps_revdata
import ps_xlsx


# Column positions: four drawing columns, Current Rev (unless its heading
# is blank), then the issues.
COL_NUMBER, COL_TITLE, COL_SIZE, COL_SCALE = 1, 2, 3, 4
COL_CURRENT = 5
# Blank issue columns are added up to this many, as on the paper form.
MIN_ISSUE_COLUMNS = 24

# The TIDP form's colours. LABEL_FILL is Project No / Title's own blue; the
# headings are the theme's Text 2 at 90% lighter, written as RGB.
TITLE_BLUE = u'FF35607A'
LABEL_FILL = u'FFDDEBF7'
HEAD_FILL = u'FFDCEAF7'
CURRENT_FILL = u'FFFFC000'
CURRENT_INK = u'FF0E2841'      # the theme's Text 2, on the orange
BLACK = u'FF000000'
TITLE_FONT = u'Gadugi'
CURRENT_FONT = u'Arial'

# Widths in characters and heights in points, from the form.
WIDTHS = {COL_NUMBER: 34.0, COL_TITLE: 48.0, COL_SIZE: 12.44,
          COL_SCALE: 6.11, COL_CURRENT: 3.89}
ISSUE_WIDTH = 3.55
BAND_HEIGHTS = (96.75, 35.25)
TOP_HEIGHTS = {3: 18, 4: 18, 5: 17.4, 6: 13.8, 7: 17.4}
HEAD_HEIGHT = 63
FOOTER_HEIGHT = 34.5
ROW_HEIGHT = 15

# The largest a logo is drawn, in pixels, and the gaps around it.
LOGO_BOX = (300, 168)
LOGO_GAP = 24

DEFAULT_TITLE = u'RD9 - Document Register & Issue Sheet'
DEFAULT_LEGEND = [u'S0 = WIP', u'S1 = Coordination', u'S2 = Information',
                  u'S3 = Review/Comment', u'S4 = Stage Approval',
                  u'S5 = Authorisation']
DEFAULT_SNAPSHOT = u'Current Rev'
DEFAULT_PAPER = u'A4 portrait'

MONTHS = {u'jan': 1, u'feb': 2, u'mar': 3, u'apr': 4, u'may': 5, u'jun': 6,
          u'jul': 7, u'aug': 8, u'sep': 9, u'oct': 10, u'nov': 11, u'dec': 12}


class Info(object):
    """Everything the form needs that is not a sheet or a revision."""

    def __init__(self):
        self.title = DEFAULT_TITLE
        self.logo = u''              # the company's, from Setup
        self.client_logo = u''       # the client's, from Setup
        self.legend = list(DEFAULT_LEGEND)
        self.footer = u''
        self.paper = DEFAULT_PAPER
        # The heading of the Current Rev column, every drawing's current
        # revision. Blank leaves the column off.
        self.snapshot = DEFAULT_SNAPSHOT
        self.project_number = u''
        self.project_name = u''
        self.model_name = u''
        self.series_param = u''
        # As on the register tab: only the revisions the worksheet's own
        # drawings carry, or every revision in the project.
        self.hide_unused = True
        # Disciplines unticked on the tab strip: no worksheet for them.
        self.skip = set()
        # The Revision Manager's own columns and values, by revision
        # UniqueId: the Issued To / Method rows and each Issue Status.
        self.revision_columns = []
        self.revision_values = {}


# ==========================================================================
# pure decisions - bench-tested
# ==========================================================================

_ISO = re.compile(r'^\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s*$')
_UK = re.compile(r'^\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\s*$')
_WORDS = re.compile(r'^\s*(\d{1,2})(?:st|nd|rd|th)?[\s.-]*([A-Za-z]{3,})'
                    r'\.?[\s,.-]*(\d{2,4})\s*$')


def parse_date(text):
    """(day, month, two-digit year) from a revision date as typed, or None.

    Revit holds the revision date as free text, so it is whatever the
    office types: 01/02/26, 01.02.2026, 2026-02-01, 1 Feb 2026. Day first,
    because this is a UK register; ISO is recognised by its four digit
    year at the front. Anything else is shown as typed rather than guessed.
    """
    text = u'{0}'.format(text or u'')
    day = month = year = None
    match = _ISO.match(text)
    if match:
        year, month, day = [int(part) for part in match.groups()]
    else:
        match = _UK.match(text)
        if match:
            day, month, year = [int(part) for part in match.groups()]
        else:
            match = _WORDS.match(text)
            if match:
                day = int(match.group(1))
                month = MONTHS.get(match.group(2)[:3].lower())
                year = int(match.group(3))
    if day is None or month is None or year is None:
        return None
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    return day, month, year % 100


def date_text(text):
    """An issue's date as it runs up its column: dd/mm/yy where it can be
    read, as typed where it cannot."""
    found = parse_date(text)
    if found is None:
        return u'{0}'.format(text or u'').strip()
    return u'{0:02d}/{1:02d}/{2:02d}'.format(*found)


def issue_statuses(revisions, rows, info):
    """{revision key: the status printed over its column}.

    The Revision Manager's Issue Status where one is stored - kept with
    the revision, so an old issue keeps its status - and otherwise the
    status most of the drawings carrying it have now.
    """
    column = ps_revdata.status_column(info.revision_columns)
    found = {}
    for revision in revisions:
        stored = u''
        if column is not None:
            stored = u'{0}'.format((info.revision_values.get(revision.uid)
                                    or {}).get(column.id, u'')).strip()
        if not stored:
            stored = common_status(
                [row.status for row in rows if row.cells.get(revision.key)])
        found[revision.key] = stored
    return found


def common_status(texts):
    """The most common status; ties to the first seen; blanks ignored."""
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


def issued_rows(revisions, info):
    """The "Issued to:" rows for a worksheet's issue columns:
    [(name, group, [ticked per issue])], Issued To then Method, leaving
    out any column none of these issues is ticked in."""
    values = dict([(revision.key, info.revision_values.get(revision.uid)
                    or {}) for revision in revisions])
    return ps_revdata.issue_rows(info.revision_columns, values,
                                 [revision.key for revision in revisions])


def worksheets(rows, skip=None):
    """[(name, rows)] - one per discipline, or one for everything.

    On paper the register is split by discipline. The All tab gets a
    worksheet of its own - first, every discipline under its own heading -
    only when it is ticked on the tab strip (1.46.0). A discipline unticked
    there gets no worksheet, and neither does one with nothing in the
    register.
    """
    skip = set(skip or ())
    tabs = ps_register.discipline_tabs(rows)
    if len(tabs) == 1:
        return [(u'Register', list(rows))] if rows else []
    out = [(label, members) for label, members in tabs
           if label != ps_register.ALL_TAB and label not in skip
           and members]
    if ps_register.all_ticked(skip) and rows:
        out.insert(0, (ps_register.ALL_TAB, list(rows)))
    return out


def text_width(texts, floor, ceiling):
    """A column width in characters that fits the longest text."""
    longest = max([len(u'{0}'.format(text or u'')) for text in texts] or [0])
    return max(floor, min(ceiling, longest * 1.05 + 2))


def paper_setup(text):
    """(Excel paper code, landscape) from a setting like 'A4 portrait'.

    The size alone - how the setting was kept before 1.24.0 - is portrait,
    the form's own orientation.
    """
    words = u'{0}'.format(text or u'').upper().split()
    size = [word for word in words if word in ps_xlsx.PAPER]
    return (ps_xlsx.PAPER[size[0]] if size else ps_xlsx.PAPER['A4'],
            u'LANDSCAPE' in words)


def fit_logos(sizes, start, right_edge, band_height, box=LOGO_BOX,
              gap=LOGO_GAP):
    """[(x, y, width, height)] for logos laid left to right in the band.

    Each is scaled to fit ``box`` keeping its shape, centred top to bottom,
    starting at ``start`` with ``gap`` between. Where the row would run
    past ``right_edge`` - a narrow form - they are all shrunk together, so
    neither lands outside the print area.
    """
    fitted = []
    for width, height in sizes:
        if not width or not height:
            fitted.append(None)
            continue
        scale = min(float(box[0]) / width, float(min(box[1], band_height - 8))
                    / height)
        fitted.append((width * scale, height * scale))
    shown = [size for size in fitted if size]
    if not shown:
        return [None for _size in sizes]
    need = sum([size[0] for size in shown]) + gap * (len(shown) - 1)
    room = right_edge - start - 8
    shrink = 1.0
    if need > room > 0:
        shrink = float(room) / need
    elif room <= 0:
        shrink = 0.25
    placed = []
    x = start
    for size in fitted:
        if size is None:
            placed.append(None)
            continue
        width, height = size[0] * shrink, size[1] * shrink
        placed.append((int(x), int((band_height - height) / 2.0),
                       max(1, int(width)), max(1, int(height))))
        x += width + gap
    return placed


# ==========================================================================
# the workbook
# ==========================================================================

class _Form(object):
    """One worksheet of the form, and where its heavy lines go.

    Thin lines throughout inside a medium frame, as on the TIDP sheet, with
    medium lines: under the title band and over the project rows; under
    Day/Month/Year and under the legend; between the Issued To rows and
    the Method rows; either side of the headings; down the left of Current
    Rev and of the first issue; under the last drawing; round the footer.
    Every cell asks for its look and the frame is worked out from where it
    sits - which is what keeps the edges right whatever the number of
    issues, Issued to rows and drawings.
    """

    def __init__(self, book, sheet, last, first_issue, current):
        self.styles = book.styles
        self.sheet = sheet
        self.last = last              # the last column of the form
        self.first_issue = first_issue
        self.current = current        # the Current Rev column, or 0
        self.split = 0                # the last Issued To row before Method
        self.issued = (0, -1)         # the first and last Issued to row
        self.head = 0                 # the column headings row
        self.data = (0, -1)           # first and last drawing row
        self.footer = 0

    def sides(self, row, col):
        left = right = top = bottom = u'thin'
        if col == 1:
            left = u'medium'
        if col == self.last:
            right = u'medium'
        if row == 1:
            top = u'medium'
        if row == 2:
            bottom = u'medium'
        if row == 3:
            top = u'medium'
        if row == 5 and COL_SIZE <= col < self.first_issue:
            bottom = u'medium'
        if row == 6 and col < self.first_issue:
            # Issue Status: and its legend read as one box.
            bottom = None
        if row == 7 and col < self.first_issue:
            top = None
            bottom = u'medium'
        if self.split and row == self.split and col > COL_NUMBER:
            bottom = u'medium'
        if row in (self.head, self.footer):
            top = bottom = u'medium'
        if row == self.data[1]:
            bottom = u'medium'
        if 3 <= row < self.footer:
            if col == self.first_issue:
                left = u'medium'
            if col == self.first_issue - 1:
                right = u'medium'
        if self.current and self.head <= row < self.footer:
            if col == self.current:
                left = u'medium'
            if col == self.current - 1:
                right = u'medium'
        if self.issued[0] <= row <= self.issued[1]:
            # The Issued to block, as the office drew it on the form: a
            # heavy line round it and between "Issued to:" and the names,
            # and the issue columns carried through it on thin lines.
            if row == self.issued[0]:
                top = u'medium'
            if row == self.issued[1]:
                bottom = u'medium'
            if col == COL_NUMBER:
                right = u'medium'
            if col == COL_TITLE:
                left = u'medium'
            if col == self.first_issue:
                left = u'thin'
            if col == self.first_issue - 1:
                right = u'thin'
        return left, right, top, bottom

    def look(self, row, col, **kw):
        kw.setdefault('border', self.sides(row, col))
        return self.styles.style(**kw)

    def put(self, row, col, value, number=False, **kw):
        self.sheet.set(row, col, value, self.look(row, col, **kw), number)

    def block(self, row1, col1, row2, col2, value=None, **kw):
        """Merge a block, each cell framed for where it sits."""
        for row in range(row1, row2 + 1):
            for col in range(col1, col2 + 1):
                self.put(row, col, value if (row, col) == (row1, col1)
                         else None, **kw)
        if (row1, col1) != (row2, col2):
            self.sheet.merges.append((row1, col1, row2, col2))


def build(revisions, rows, info):
    """The register as a Workbook. ``rows`` are the included drawings."""
    book = ps_xlsx.Workbook(border_color=BLACK, font_size=11)
    statuses = issue_statuses(revisions, rows, info)
    for name, members in worksheets(rows, info.skip):
        _sheet(book, name, members, revisions, info, statuses)
    if not book.sheets:
        _sheet(book, u'Register', [], revisions, info, statuses)
    return book


def _series_groups(rows, info):
    if info.series_param and ps_register.has_values(
            rows, lambda one: one.series):
        return ps_register.first_appearance(
            rows, lambda one: one.series, ps_register.NO_SERIES)
    return [(None, list(rows))]


def sections(name, rows, info):
    """[(heading, series groups)] for a worksheet. The All worksheet has one
    per discipline, in tab order, each under its own heading; any other has
    one, under its discipline."""
    if name == ps_register.ALL_TAB:
        tabs = [(label, members) for label, members in
                ps_register.discipline_tabs(rows)
                if label != ps_register.ALL_TAB and members]
        if len(tabs) > 1:
            return [(label, _series_groups(members, info))
                    for label, members in tabs]
    return [(discipline_heading(name, rows), _series_groups(rows, info))]


def discipline_heading(name, rows):
    """The line over a worksheet's drawings: its discipline, where the
    drawings have one; nothing for a register with no disciplines."""
    found = set([u'{0}'.format(row.discipline or u'').strip()
                 for row in rows])
    found.discard(u'')
    if len(found) == 1:
        return list(found)[0]
    return u'' if name == u'Register' else name


def _sheet(book, name, rows, revisions, info, statuses=None):
    statuses = statuses or {}
    sheet = book.add_sheet(name)
    sheet.paper, sheet.landscape = paper_setup(info.paper)
    sheet.margins = (0.25, 0.25, 0.75, 0.75, 0.3, 0.3)
    sheet.print_area = True
    issues = ps_register.revisions_for(revisions, rows, info.hide_unused)
    columns = max(len(issues), MIN_ISSUE_COLUMNS)
    snapshot = u'{0}'.format(info.snapshot or u'').strip()
    current = COL_CURRENT if snapshot else 0
    first_issue = COL_CURRENT + 1 if snapshot else COL_CURRENT
    last = first_issue + columns - 1
    form = _Form(book, sheet, last, first_issue, current)
    labels_end = first_issue - 1          # Day/Month/Year span C to here
    issued = issued_rows(issues, info)
    parts = sections(name, rows, info)

    # Rows: the Issued to rows (one blank when there are none), the
    # headings, the discipline, the drawings with a blank row between
    # series, the footer.
    issued_to = 8
    end = issued_to + max(1, len(issued)) - 1
    methods = [index for index, one in enumerate(issued)
               if one[1] == ps_revdata.METHOD]
    if methods and methods[0] > 0:
        form.split = issued_to + methods[0] - 1
    form.issued = (issued_to, end)
    form.head = end + 1
    # Each section: its heading line, its drawings, and a blank row
    # between its series.
    used = 0
    for heading, groups in parts:
        used += (1 if heading else 0) + \
            sum([len(members) for _label, members in groups]) + \
            max(0, len(groups) - 1)
    last_data = form.head + used
    form.data = (form.head + 1, max(form.head + 1, last_data))
    form.footer = form.data[1] + 1

    # -- widths: the form's, wider only where the text needs it
    sheet.width(COL_NUMBER, text_width([row.number for row in rows] +
                                       [info.project_number],
                                       WIDTHS[COL_NUMBER], 48))
    sheet.width(COL_TITLE, text_width([row.name for row in rows] +
                                      [info.project_name],
                                      WIDTHS[COL_TITLE], 80))
    for col, values in ((COL_SIZE, [row.size for row in rows]),
                        (COL_SCALE, [row.scale for row in rows])):
        longest = max([len(u'{0}'.format(v or u'')) for v in values] or [0])
        sheet.width(col, max(WIDTHS[col], longest * 0.8 + 1))
    if current:
        sheet.width(current, WIDTHS[COL_CURRENT])
    for col in range(first_issue, last + 1):
        sheet.width(col, ISSUE_WIDTH)

    # -- heights
    sheet.height(1, BAND_HEIGHTS[0])
    sheet.height(2, BAND_HEIGHTS[1])
    for row, points in TOP_HEIGHTS.items():
        sheet.height(row, points)
    for row in range(issued_to, form.footer):
        sheet.height(row, ROW_HEIGHT)
    sheet.height(form.head, HEAD_HEIGHT)
    sheet.height(form.footer, FOOTER_HEIGHT)

    # -- 1-2 the title band, logos after the title
    form.block(1, 1, 2, last, u'{0}'.format(info.title or DEFAULT_TITLE),
               size=18, bold=True, color=TITLE_BLUE, font=TITLE_FONT,
               h=u'left', indent=2)
    _logos(sheet, info, last)

    # -- 3-5 project, and each issue's date up its column
    form.put(3, COL_NUMBER, u'Project No:', bold=True, fill=LABEL_FILL,
             h=u'left')
    form.put(3, COL_TITLE, u'Project Title:', bold=True, fill=LABEL_FILL,
             h=u'left', wrap=True)
    form.block(4, COL_NUMBER, 5, COL_NUMBER, info.project_number or None,
               size=14)
    form.block(4, COL_TITLE, 5, COL_TITLE, info.project_name or None,
               size=14)
    for row, part in ((3, u'Day'), (4, u'Month'), (5, u'Year')):
        form.block(row, COL_SIZE, row, labels_end, part, bold=True,
                   h=u'center', fill=HEAD_FILL)
    for offset in range(columns):
        col = first_issue + offset
        text = date_text(issues[offset].date) if offset < len(issues) \
            else u''
        form.block(3, col, 5, col, text or None, size=8, bold=True,
                   h=u'center', rotate=90, fill=HEAD_FILL)

    # -- 6-7 each issue's status, and the legend
    form.block(6, COL_NUMBER, 6, labels_end, u'Issue Status: ', h=u'right',
               wrap=True)
    form.block(7, COL_NUMBER, 7, labels_end,
               u'  '.join([u'{0}'.format(item).strip() for item in info.legend
                           if u'{0}'.format(item).strip()]),
               size=9, h=u'right', wrap=True)
    for offset in range(columns):
        status = statuses.get(issues[offset].key, u'') \
            if offset < len(issues) else u''
        form.block(6, first_issue + offset, 7, first_issue + offset,
                   status or None, bold=True, h=u'center')

    # -- 8.. Issued to: the Revision Manager's Issued To then Method rows
    form.block(issued_to, COL_NUMBER, end, COL_NUMBER, u'Issued to:',
               bold=True, h=u'center', wrap=True)
    for index in range(end - issued_to + 1):
        row = issued_to + index
        label, _group, ticks = issued[index] if index < len(issued) \
            else (u'', u'', [])
        form.block(row, COL_TITLE, row, labels_end, label or None,
                   bold=True, h=u'right')
        for offset in range(columns):
            went = offset < len(ticks) and ticks[offset]
            form.put(row, first_issue + offset, u'x' if went else None,
                     bold=True, h=u'center')

    # -- the column headings
    head = form.head
    form.put(head, COL_NUMBER, u'Document No', size=14, bold=True,
             h=u'center', fill=HEAD_FILL)
    form.put(head, COL_TITLE, u'Document Title', size=14, bold=True,
             h=u'center', fill=HEAD_FILL)
    form.put(head, COL_SIZE, u'Sheet Size', bold=True, h=u'center',
             fill=HEAD_FILL)
    form.put(head, COL_SCALE, u'Scale', bold=True, h=u'center', rotate=90,
             fill=HEAD_FILL)
    if current:
        form.put(head, current, snapshot, bold=True, h=u'center', rotate=90,
                 fill=CURRENT_FILL)
    form.block(head, first_issue, head, last, u'Document Issued', size=14,
               bold=True, h=u'center', fill=HEAD_FILL)

    # -- the discipline, then the drawings with a blank row between series;
    #    on the All worksheet, one of those per discipline
    row = head
    for heading, groups in parts:
        if heading:
            row += 1
            _blank(form, row, current, last)
            form.block(row, COL_NUMBER, row, COL_TITLE, heading, bold=True,
                       h=u'center', wrap=True)
        row = _drawings(form, row, groups, issues, columns, current,
                        first_issue, last)

    # -- the footer
    footer = info.footer or u'Generated from {0} on {1} by RevoBIM Pro ' \
        u'Sheets Exporter.'.format(info.model_name or u'the model',
                                   time.strftime('%d/%m/%Y'))
    form.block(form.footer, 1, form.footer, last, footer, size=9,
               h=u'center', wrap=True)

    # Rows down to the headings repeat on every printed page.
    sheet.print_rows = (1, head)
    return sheet


def _drawings(form, row, groups, issues, columns, current, first_issue,
              last):
    """One section's drawings from the row after ``row``, a blank row
    between series. Returns the last row written."""
    first = True
    for _label, members in groups:
        if not first:
            row += 1
            _blank(form, row, current, last)
        first = False
        for drawing in members:
            row += 1
            form.put(row, COL_NUMBER, drawing.number, size=10, h=u'center')
            form.put(row, COL_TITLE, drawing.name, size=10, h=u'left',
                     indent=1)
            form.put(row, COL_SIZE, drawing.size or None, size=8,
                     h=u'center')
            form.put(row, COL_SCALE, drawing.scale or None, size=8,
                     h=u'center')
            if current:
                form.put(row, current, drawing.current or None, size=8,
                         bold=True, h=u'center', font=CURRENT_FONT,
                         color=CURRENT_INK, fill=CURRENT_FILL)
            for offset in range(columns):
                code = drawing.cells.get(issues[offset].key, u'') \
                    if offset < len(issues) else u''
                form.put(row, first_issue + offset, code or None, size=9,
                         h=u'center')
    return row


def _blank(form, row, current, last):
    """A spacer row, framed like the drawings either side of it; Current
    Rev stays orange down its whole length."""
    for col in range(1, last + 1):
        if col == current:
            form.put(row, col, None, size=9, bold=True, font=CURRENT_FONT,
                     color=CURRENT_INK, fill=CURRENT_FILL)
        else:
            form.put(row, col, None, size=9)


def _logos(sheet, info, last):
    """The company's logo then the client's to its right, after the title
    in the band (1.46.0 - the client's came first before)."""
    paths = []
    for path in (info.logo, info.client_logo):
        if path and ps_xlsx.Workbook.usable_image(path) is not None and \
                path not in paths:
            paths.append(path)
    if not paths:
        return
    band = ps_xlsx.height_pixels(BAND_HEIGHTS[0]) + \
        ps_xlsx.height_pixels(BAND_HEIGHTS[1])
    right = sum([ps_xlsx.width_pixels(sheet.widths.get(col, 8.43))
                 for col in range(1, last + 1)])
    # Where the title ends: 18pt Gadugi bold runs 13 to 15 pixels a
    # character, after the two-step indent - the wider end, so a long
    # title like the RD9 one never runs under the logo.
    title = u'{0}'.format(info.title or DEFAULT_TITLE)
    start = 24 + int(len(title) * 15) + LOGO_GAP
    sizes = [ps_xlsx.image_size(path) for path in paths]
    for path, place in zip(paths, fit_logos(sizes, start, right, band)):
        if place:
            sheet.image(path, *place)


def write(path, revisions, rows, info):
    """Build and save. (ok, message)."""
    try:
        book = build(revisions, rows, info)
    except Exception as err:
        return False, u'The register could not be laid out: {0}'.format(err)
    ok, error = book.save(path)
    if not ok:
        return False, u'The register could not be written: {0}'.format(error)
    return True, u'Document Register written: {0} drawing{1} on {2} ' \
        u'worksheet{3}.'.format(len(rows), u'' if len(rows) == 1 else u's',
                                len(book.sheets),
                                u'' if len(book.sheets) == 1 else u's')
