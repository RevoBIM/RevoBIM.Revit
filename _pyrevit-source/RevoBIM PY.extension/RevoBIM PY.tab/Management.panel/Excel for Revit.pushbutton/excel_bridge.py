# -*- coding: utf-8 -*-
"""The two Excel exports and the import that comes back.

Kept apart from script.py so the layout rules and the matching rules can be
bench-tested under plain CPython against fake rows, with no Revit anywhere.
Nothing in here touches the Revit API: it is handed plain values by the caller
and hands back plain values.

**Round trip** writes a hidden-ish key block (element id, and the schedule name
and a stamp on a second sheet) and one column per field, coloured the way the
grid colours them.  Coming back, rows are matched on the element id rather than
on position, so sorting or filtering the sheet in Excel — the whole point of
exporting a list — cannot scramble the import.

**Presentation** writes what the schedule looks like: a title band, headers,
borders, banded rows, sensible widths and wrapped text, and no key block.  It
is one-directional by design; there is nothing in it to match on.
"""

import re

import xlsx_io
from xlsx_io import Workbook, read_sheet, col_letter   # noqa: F401

MARKER = 'RevoBIM Excel for Revit'
KEY_HEADER = 'Revit ID'
ROW_HEADER = '#'

# how wide a column is allowed to get before the text wraps instead
MIN_WIDTH = 9.0
MAX_WIDTH = 46.0


# ---------------------------------------------------------------- palettes --
# Excel is always read on white, so the round-trip colours are the light
# palette's, not the dark one's.  The key is that they match the *meaning* of
# the grid's colours, not their exact hex.

XL = {
    'inst_bg': 'D9E9F8', 'inst_fg': '13507F',
    'type_bg': 'FBE7CC', 'type_fg': '8A4E07',
    'ro_bg': 'F5DDDB', 'ro_fg': '8E3733',
    'key_bg': 'ECECF0', 'key_fg': '5A5A62',
    'head_bg': '1F3D57', 'head_fg': 'FFFFFF',
    'inst_head': '2E6EA6', 'type_head': 'B96A12', 'ro_head': 'A24540',
    'title_bg': '17293A', 'title_fg': 'FFFFFF',
    'band': 'F7F9FC', 'plain': 'FFFFFF',
    'edge': 'C6CBD2',
    'note_fg': '5A5A62',
}


def text_width(value):
    try:
        return len(value or '')
    except Exception:
        return 0


def measure(header, values, cap=MAX_WIDTH):
    """Column width from the content, clamped so nothing runs off the page."""
    widest = text_width(header)
    for v in values:
        widest = max(widest, text_width(v))
    return max(MIN_WIDTH, min(cap, widest * 1.15 + 3.5))


def sanitize(name):
    return xlsx_io.sheet_name_safe(name)


# =================================================================== export ==

def export_round_trip(path, schedule_name, fields, rows, doc_title=''):
    """Sheet 1 a flat list with a key column; sheet 2 the legend and the stamp.

    fields: [{'name','letter','is_type','editable','reason'}]
    rows:   [{'eid': '123456', 'values': ['a','b',...],
              'editable': [True,...], 'is_type': [False,...]}]
    """
    wb = Workbook()
    st = wb.styles

    head_key = st.cell(XL['head_fg'], XL['head_bg'], 11, True, align='center', wrap=True)
    head_inst = st.cell('FFFFFF', XL['inst_head'], 11, True, align='center', wrap=True)
    head_type = st.cell('FFFFFF', XL['type_head'], 11, True, align='center', wrap=True)
    head_ro = st.cell('FFFFFF', XL['ro_head'], 11, True, align='center', wrap=True)

    key_style = st.cell(XL['key_fg'], XL['key_bg'], 11, False, align='center')
    idx_style = st.cell(XL['key_fg'], XL['key_bg'], 11, False, align='center')
    inst_style = st.cell(XL['inst_fg'], XL['inst_bg'], 11, wrap=True, align='left')
    type_style = st.cell(XL['type_fg'], XL['type_bg'], 11, wrap=True, align='left')
    ro_style = st.cell(XL['ro_fg'], XL['ro_bg'], 11, italic=True, wrap=True, align='left')

    sheet = wb.sheet(sanitize(schedule_name or 'Schedule'))

    header = [(ROW_HEADER, head_key, False), (KEY_HEADER, head_key, False)]
    for f in fields:
        if f['is_type']:
            style = head_type
        elif not f['editable']:
            style = head_ro
        else:
            style = head_inst
        header.append((f['name'], style, False))
    sheet.add_row(header, height=34)

    for n, row in enumerate(rows):
        cells = [(str(n + 1), idx_style, True), (row['eid'], key_style, True)]
        for i, f in enumerate(fields):
            value = row['values'][i] if i < len(row['values']) else ''
            editable = row['editable'][i] if i < len(row['editable']) else False
            is_type = row['is_type'][i] if i < len(row['is_type']) else False
            if not editable:
                style = ro_style
            elif is_type:
                style = type_style
            else:
                style = inst_style
            cells.append((value, style, False))
        sheet.add_row(cells)

    sheet.width(0, 5.5)
    sheet.width(1, 12.0)
    for i, f in enumerate(fields):
        column = [r['values'][i] if i < len(r['values']) else '' for r in rows]
        sheet.width(i + 2, measure(f['name'], column))
    sheet.freeze = (1, 2)
    sheet.autofilter = (0, 0, max(0, len(rows)), len(fields) + 1)

    _legend_sheet(wb, st, schedule_name, fields, rows, doc_title, round_trip=True)
    wb.save(path)
    return len(rows)


def export_presentation(path, schedule_name, fields, rows, doc_title=''):
    """What the schedule looks like, for issuing. Nothing to import back."""
    wb = Workbook()
    st = wb.styles

    title_style = st.cell(XL['title_fg'], XL['title_bg'], 16, True,
                          border=False, align='left')
    sub_style = st.cell(XL['note_fg'], None, 10, False, border=False, align='left')
    head_style = st.cell('FFFFFF', XL['head_bg'], 11, True, align='center', wrap=True)
    plain = st.cell('1F1F23', XL['plain'], 11, wrap=True, align='left')
    band = st.cell('1F1F23', XL['band'], 11, wrap=True, align='left')
    plain_num = st.cell('1F1F23', XL['plain'], 11, align='right')
    band_num = st.cell('1F1F23', XL['band'], 11, align='right')

    sheet = wb.sheet(sanitize(schedule_name or 'Schedule'))

    width = max(1, len(fields))
    sheet.add_row([(schedule_name or 'Schedule', title_style, False)] +
                  [(None, title_style, False)] * (width - 1), height=30)
    sheet.merges.append((0, 0, 0, width - 1))
    stamp = doc_title or ''
    sheet.add_row([(stamp, sub_style, False)] +
                  [(None, sub_style, False)] * (width - 1), height=16)
    sheet.merges.append((1, 0, 1, width - 1))
    sheet.add_row([])

    sheet.add_row([(f['name'], head_style, False) for f in fields], height=34)

    numeric_col = []
    for i in range(len(fields)):
        column = [r['values'][i] if i < len(r['values']) else '' for r in rows]
        filled = [v for v in column if (v or '').strip()]
        numeric_col.append(bool(filled) and
                           all(xlsx_io.looks_numeric(v) for v in filled))

    for n, row in enumerate(rows):
        striped = (n % 2) == 1
        cells = []
        for i in range(len(fields)):
            value = row['values'][i] if i < len(row['values']) else ''
            if numeric_col[i]:
                style = band_num if striped else plain_num
            else:
                style = band if striped else plain
            cells.append((value, style, numeric_col[i]))
        sheet.add_row(cells)

    for i, f in enumerate(fields):
        column = [r['values'][i] if i < len(r['values']) else '' for r in rows]
        sheet.width(i, measure(f['name'], column))
    sheet.freeze = (4, 0)
    sheet.autofilter = (3, 0, 3 + len(rows), max(0, len(fields) - 1))

    wb.save(path)
    return len(rows)


def _legend_sheet(wb, st, schedule_name, fields, rows, doc_title, round_trip):
    """Sheet 2: what the colours mean, and the stamp the import checks."""
    sheet = wb.sheet('RevoBIM')
    title = st.cell(XL['title_fg'], XL['title_bg'], 14, True, border=False)
    key = st.cell('1F1F23', None, 11, True, border=False)
    val = st.cell(XL['note_fg'], None, 11, False, border=False, wrap=True)
    note = st.cell(XL['note_fg'], None, 10, italic=True, border=False, wrap=True)

    sheet.add_row([(MARKER, title, False), (None, title, False)], height=26)
    sheet.merges.append((0, 0, 0, 1))
    sheet.add_row([])
    for label, value in (('Schedule', schedule_name or ''),
                         ('Model', doc_title or ''),
                         ('Columns', str(len(fields))),
                         ('Rows', str(len(rows))),
                         ('Layout', 'Round trip' if round_trip else 'Presentation')):
        sheet.add_row([(label, key, False), (value, val, False)])

    sheet.add_row([])
    sheet.add_row([('Cell colours', key, False)])
    swatches = (
        ('Instance parameter', XL['inst_bg'], XL['inst_fg'],
         'Editable. Changing it affects this element only.'),
        ('Type parameter', XL['type_bg'], XL['type_fg'],
         'Editable. Changing it affects every element of that type.'),
        ('Not editable', XL['ro_bg'], XL['ro_fg'],
         'Read only in Revit. Edits to these cells are ignored on import.'),
        ('Key columns', XL['key_bg'], XL['key_fg'],
         'Used to match rows on the way back. Do not edit or delete them.'),
    )
    for label, bg, fg, meaning in swatches:
        chip = st.cell(fg, bg, 11, True, border=True, align='center')
        sheet.add_row([(label, chip, False), (meaning, val, False)])

    sheet.add_row([])
    if round_trip:
        text = ('Edit the coloured value columns and save the file, then use '
                'Import from Excel in the tool. Rows are matched on Revit ID, '
                'so sorting and filtering this sheet is safe. Adding rows, '
                'deleting the ID column or renaming the value headers is not.')
    else:
        text = ('This is a presentation export. It carries no Revit IDs and '
                'cannot be imported back — use the round-trip export for that.')
    sheet.add_row([(text, note, False), (None, note, False)], height=46)
    sheet.merges.append((len(sheet.rows) - 1, 0, len(sheet.rows) - 1, 1))
    sheet.width(0, 22.0)
    sheet.width(1, 64.0)
    return sheet


# =================================================================== import ==

def norm_header(text):
    """Compare headers loosely: case, spacing and punctuation should not matter."""
    return re.sub(r'[^a-z0-9]', '', (text or '').lower())


class ImportResult(object):

    def __init__(self):
        self.changes = []        # (eid, field_index, old, new)
        self.unchanged = 0
        self.skipped_readonly = []   # (eid, field name)
        self.unmatched_rows = []     # eid or row label
        self.unmatched_cols = []     # header text
        self.matched_cols = []       # (header, field_index)
        self.errors = []
        self.rows_seen = 0

    @property
    def ok(self):
        return not self.errors


def parse_import(table, fields, rows_by_eid):
    """Match a sheet back onto the model.

    table:       rows of strings, straight from read_sheet
    fields:      [{'name','letter','is_type','editable'}]
    rows_by_eid: {eid string: {'values': [...], 'editable':[...]}}

    Nothing is written here — it returns what *would* change, and the caller
    stages it.
    """
    res = ImportResult()
    if not table:
        res.errors.append('That file has no rows in it.')
        return res

    header = None
    header_at = -1
    for i, row in enumerate(table[:10]):
        cells = [norm_header(c) for c in row]
        if norm_header(KEY_HEADER) in cells:
            header = row
            header_at = i
            break
    if header is None:
        res.errors.append(
            'No "{0}" column found in the first ten rows. This looks like a '
            'presentation export or a file from somewhere else — only the '
            'round-trip export can be imported.'.format(KEY_HEADER))
        return res

    key_col = -1
    for i, cell in enumerate(header):
        if norm_header(cell) == norm_header(KEY_HEADER):
            key_col = i
            break

    by_norm = {}
    for i, f in enumerate(fields):
        by_norm.setdefault(norm_header(f['name']), i)

    col_map = {}
    for i, cell in enumerate(header):
        if i == key_col:
            continue
        norm = norm_header(cell)
        if not norm or norm == norm_header(ROW_HEADER):
            continue
        if norm in by_norm:
            col_map[i] = by_norm[norm]
            res.matched_cols.append((cell, by_norm[norm]))
        else:
            res.unmatched_cols.append(cell)

    if not col_map:
        res.errors.append('None of the column headings match this schedule. '
                          'Was this exported from a different schedule?')
        return res

    seen = set()
    for row in table[header_at + 1:]:
        if key_col >= len(row):
            continue
        eid = (row[key_col] or '').strip()
        if not eid:
            if any((c or '').strip() for c in row):
                res.unmatched_rows.append('(row with no Revit ID)')
            continue
        res.rows_seen += 1
        if eid in seen:
            res.unmatched_rows.append('{0} (listed twice)'.format(eid))
            continue
        seen.add(eid)
        model_row = rows_by_eid.get(eid)
        if model_row is None:
            res.unmatched_rows.append(eid)
            continue
        for col, fidx in col_map.items():
            if col >= len(row):
                continue
            new = (row[col] or '')
            old = model_row['values'][fidx] if fidx < len(model_row['values']) else ''
            if new == old:
                res.unchanged += 1
                continue
            editable = (model_row['editable'][fidx]
                        if fidx < len(model_row['editable']) else False)
            if not editable:
                res.skipped_readonly.append((eid, fields[fidx]['name']))
                continue
            res.changes.append((eid, fidx, old, new))
    return res
